"""Regressions for Codex's slice-2 review (H1-H4, M1-M6)."""

import asyncio
import json
import threading
import uuid

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from nightlight_api import agent as agentlib, db, demo, quota, turns
from nightlight_api.config import settings
from nightlight_api.errors import ApiError
from fake_llm import FakeLlm, reply
from test_chat import ask, events, new_session  # noqa: F401  (fixture module shared)
from test_chat import fake_model  # noqa: F401


# Fake secret values are assembled at runtime so no secret-shaped literal lives in the repository.
FAKE_PW = "zebra" + "-melon-" + "42"
FAKE_TOKEN = "abc" + "123" + "def456"


def _queue(uid, sid, text="hi"):
    return turns.accept_message(uid, sid, text, str(uuid.uuid4()))


def _collect(gen):
    async def run():
        return [x async for x in gen]
    return asyncio.run(run())


# ---------------------------------------------------------------- H1 redaction boundaries

def test_json_secret_in_chat_never_stored_or_sent(client, started):
    uid, sid = started, new_session(client)
    FakeLlm.behavior = reply("ok")
    ask(client, sid, text='my config is {"pass' + 'word":"' + FAKE_PW + '"}')
    stored = " ".join(m.to_dict()["text"] for m in db.messages(uid, sid).get())
    assert FAKE_PW not in stored
    assert all(FAKE_PW not in call["text"] for call in FakeLlm.log)


def test_secret_split_across_chunks_is_hidden_everywhere(client, started):
    uid, sid = started, new_session(client)
    FakeLlm.behavior = reply("Set pass", "word=plum-", "kiwi-77 then restart. " + "More words. " * 20)
    crid = str(uuid.uuid4())
    live = "".join(e.get("delta", "") for e in events(ask(client, sid, crid=crid)) if e["type"] == "text")
    stored = next(m.to_dict()["text"] for m in db.messages(uid, sid).get() if m.to_dict()["role"] == "assistant")
    replay = "".join(e.get("delta", "") for e in events(ask(client, sid, crid=crid)) if e["type"] == "text")
    for text in (live, stored, replay):
        assert "plum-kiwi-77" not in text and "kiwi-77" not in text
    assert live == stored == replay


def test_decide_note_is_scrubbed(client, started):
    uid, sid = started, new_session(client)
    action_id = next(e["actionId"] for e in events(ask(client, sid)) if e["type"] == "approval_request")
    client.post(f"/api/actions/{action_id}/decide", json={"decision": "deny", "note": "tok" + "en=" + FAKE_TOKEN})
    assert FAKE_TOKEN not in json.dumps(db.action(uid, action_id).get().to_dict(), default=str)


# ---------------------------------------------------------------- H2 exact count on every dispatch

def test_every_model_call_is_counted_and_count_failure_blocks(client, started, monkeypatch):
    sid = new_session(client)
    events(ask(client, sid))
    assert len(FakeLlm.counted) == len(FakeLlm.log) == 3
    FakeLlm.log.clear()
    monkeypatch.setattr(agentlib, "COUNT_RETRY_SECONDS", 0)
    monkeypatch.setattr(agentlib, "COUNTER", lambda req: (_ for _ in ()).throw(RuntimeError("count down")))
    ev = events(ask(client, sid))
    # Still fails closed (nothing sent), but says what happened: the size couldn't be checked, not "too long".
    assert ev[-1]["code"] == "size_check_failed" and ev[-1]["retryable"] is True and FakeLlm.log == []


# ---------------------------------------------------------------- H3 accounting

def test_cost_of_needs_full_usage():
    assert quota.cost_of(None) is None
    assert quota.cost_of(types.GenerateContentResponseUsageMetadata(prompt_token_count=100,
                                                                    candidates_token_count=10)) is None
    u = types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=10,
                                                   total_token_count=150)
    assert quota.cost_of(u) == pytest.approx((100 * settings.price_in_per_m + 50 * settings.price_out_per_m) / 1e6)


def test_reconcile_is_signed_and_keeps_unknown(started):
    ref = quota.global_ref()
    ref.set({"reservedUsd": 1.0, "spentUsd": 0.0})
    quota.reconcile(0.01584, 0.03168)  # overage raises the admission counter
    assert ref.get().to_dict()["reservedUsd"] == pytest.approx(1.0 + 0.01584)
    quota.reconcile(0.01584, None)  # unknown: the reservation stays
    assert ref.get().to_dict()["reservedUsd"] == pytest.approx(1.0 + 0.01584)
    ref.delete()


def test_missing_usage_keeps_full_reservation(client, started):
    sid = new_session(client)
    FakeLlm.behavior = reply("hello", usage=False)
    events(ask(client, sid))
    g = quota.global_ref().get().to_dict()
    assert g["reservedUsd"] == pytest.approx(settings.c_max) and g.get("spentUsd", 0) == 0


def test_concurrent_reservations_respect_budget(started, monkeypatch):
    monkeypatch.setattr(settings, "model_budget_usd", settings.c_max * 5 + 1e-9)
    quota.global_ref().delete()
    ok, err = [], []

    def go(i):
        try:
            quota.reserve(started, f"ip{i}")
            ok.append(i)
        except ApiError as e:
            err.append(e.code)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 5 and set(err) == {"quota_global"}
    quota.global_ref().delete()


# ---------------------------------------------------------------- H4 stale turns never call the model

def test_reset_before_first_call_means_zero_model_calls(client, started):
    uid, sid = started, new_session(client)
    claimed = turns.claim(uid, _queue(uid, sid))
    demo.reset(uid)
    ev = [json.loads(x[5:]) for x in _collect(turns.stream(uid, claimed, "ip")) if x.startswith("data:")]
    assert ev[-1]["code"] == "stale" and FakeLlm.log == []


def test_takeover_between_calls_stops_further_calls(client, started):
    uid, sid = started, new_session(client)
    claimed = turns.claim(uid, _queue(uid, sid))

    async def first_call_then_takeover(llm_request, stream):
        from datetime import datetime, timedelta, timezone
        db.session(uid, sid).update({"activeTurn.leaseUntil": datetime.now(timezone.utc) - timedelta(seconds=1)})
        turns.claim(uid, claimed.turn_id)  # another instance takes the turn over
        part = types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"}))
        yield LlmResponse(content=types.Content(role="model", parts=[part]), partial=False)

    FakeLlm.behavior = first_call_then_takeover
    ev = [json.loads(x[5:]) for x in _collect(turns.stream(uid, claimed, "ip")) if x.startswith("data:")]
    assert ev[-1]["code"] == "stale" and len(FakeLlm.log) == 1


# ---------------------------------------------------------------- M1 lease renews on a clock

def test_quiet_model_keeps_its_lease(client, started, monkeypatch):
    uid, sid = started, new_session(client)
    monkeypatch.setattr(settings, "turn_lease_seconds", 1)
    claimed = turns.claim(uid, _queue(uid, sid))

    async def slow(llm_request, stream):
        await asyncio.sleep(2.5)
        async for r in reply("done")(llm_request, stream):
            yield r

    FakeLlm.behavior = slow
    result = {}

    def intruder():
        import time
        time.sleep(1.5)
        try:
            turns.claim(uid, claimed.turn_id)
            result["claim"] = "stolen"
        except ApiError as e:
            result["claim"] = e.code

    t = threading.Thread(target=intruder)
    t.start()
    ev = [json.loads(x[5:]) for x in _collect(turns.stream(uid, claimed, "ip")) if x.startswith("data:")]
    t.join()
    assert result["claim"] == "turn_in_progress" and ev[-1]["type"] == "done"


# ---------------------------------------------------------------- M2 trimming keeps exchanges whole

def test_trim_never_orphans_a_tool_response():
    call = types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="x", args={}))])
    resp = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(name="x",
                                                                                               response={}))])
    req = type("R", (), {"contents": [call, resp], "config": types.GenerateContentConfig()})()
    with pytest.raises(ApiError) as e:
        agentlib.bound_input(req, counter=lambda r: 99999)
    assert e.value.code == "context_limit"
    assert not (len(req.contents) == 1 and req.contents[0].parts[0].function_response)


# ---------------------------------------------------------------- M3 limits

def test_parallel_tool_calls_are_capped(client, started):
    sid = new_session(client)
    calls = [types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"}))
             for _ in range(9)]

    async def burst(llm_request, stream):
        if any(p.function_response for c in llm_request.contents for p in (c.parts or [])):
            async for r in reply("ok")(llm_request, stream):
                yield r
            return
        yield LlmResponse(content=types.Content(role="model", parts=calls), partial=False)

    FakeLlm.behavior = burst
    ev = events(ask(client, sid))
    results = [e for e in ev if e["type"] == "tool_result"]
    blocked = [e for e in results if "tool limit reached" in e["summary"]]
    assert len(results) == 9 and len(blocked) == 1  # the ninth never ran
    assert ev[-1]["metrics"]["toolCalls"] == 8


def test_tool_result_byte_bound_holds_for_unicode():
    ctx = agentlib.TurnContext(uid="u", session_id="s", turn_id="t", attempt=1, generation=1, ip="i")
    out = agentlib._bounded({"note": "디스크" * 2000}, ctx)
    assert len(json.dumps(out).encode()) <= settings.tool_result_bytes


def test_message_limit_is_bytes(client, started):
    sid = new_session(client)
    r = client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "가" * 2000,
                                                                 "clientRequestId": str(uuid.uuid4())})
    assert r.status_code == 422


# ---------------------------------------------------------------- M4 whitespace equality

def test_whitespace_is_identical_live_stored_replayed(client, started):
    uid, sid = started, new_session(client)
    FakeLlm.behavior = reply(" hello ")
    crid = str(uuid.uuid4())
    live = "".join(e.get("delta", "") for e in events(ask(client, sid, crid=crid)) if e["type"] == "text")
    stored = next(m.to_dict()["text"] for m in db.messages(uid, sid).get() if m.to_dict()["role"] == "assistant")
    replay = "".join(e.get("delta", "") for e in events(ask(client, sid, crid=crid)) if e["type"] == "text")
    assert live == stored == replay


# ---------------------------------------------------------------- M5 duplicate retries count once

def test_concurrent_duplicates_count_once(client, started):
    uid, sid = started, new_session(client)
    crid = str(uuid.uuid4())
    threads = [threading.Thread(target=lambda: turns.accept_message(uid, sid, "hello", crid)) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    from datetime import datetime, timezone
    q = quota.turn_quota_ref(uid, datetime.now(timezone.utc)).get().to_dict()
    assert q["count"] == 1


def test_missing_session_costs_no_quota(client, started):
    with pytest.raises(ApiError):
        turns.accept_message(started, "sess_" + "0" * 26, "hello", str(uuid.uuid4()))
    from datetime import datetime, timezone
    assert not quota.turn_quota_ref(started, datetime.now(timezone.utc)).get().exists


# ---------------------------------------------------------------- M6 forged forwarded prefix

def test_forged_forwarded_prefix_shares_the_bucket():
    from starlette.requests import Request
    from nightlight_api.main import _client_ip

    def req(xff):
        return Request({"type": "http", "headers": [(b"x-forwarded-for", xff.encode())], "client": ("10.0.0.1", 1)})

    assert _client_ip(req("1.1.1.1, 203.0.113.9")) == _client_ip(req("8.8.8.8, 203.0.113.9"))
