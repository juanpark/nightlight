import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nightlight_api import agent as agentlib, db, demo, turns
from nightlight_api.errors import ApiError
from fake_llm import FakeLlm


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    FakeLlm.log.clear()
    FakeLlm.behavior = None
    counted = []
    monkeypatch.setattr(agentlib, "COUNTER", lambda req: counted.append(1) or 100)  # exact count, faked
    FakeLlm.counted = counted
    real_build = agentlib.build
    monkeypatch.setattr(agentlib, "build", lambda ctx, continuation, model=None:
                        real_build(ctx, continuation=continuation, model=FakeLlm()))
    db.client().collection("ops").document("flags").delete()
    db.client().collection("ops").document("quota").delete()
    yield


def events(response):
    return [json.loads(b[5:]) for b in response.text.split("\n\n") if b.startswith("data:")]


def ask(client, sid, text="What's wrong with my Pi?", crid=None):
    return client.post(f"/api/chat/sessions/{sid}/messages", json={"text": text, "clientRequestId": crid or str(uuid.uuid4())})


def new_session(client):
    r = client.post("/api/chat/sessions", json={})
    assert r.status_code == 201
    return r.json()["sessionId"]


def test_turn_streams_and_proposes(client, started):
    uid = started
    sid = new_session(client)
    r = ask(client, sid)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = events(r)
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "turn_start" and kinds[-1] == "done"
    assert ["tool_call", "tool_result", "tool_call", "tool_result", "approval_request"] == \
        [k for k in kinds if k in ("tool_call", "tool_result", "approval_request")]
    action_id = next(e["actionId"] for e in ev if e["type"] == "approval_request")
    assert db.action(uid, action_id).get().to_dict()["status"] == "pending"
    done = ev[-1]["metrics"]
    assert done["modelCalls"] == 3 and done["toolCalls"] == 2 and done["costUsd"] > 0
    msgs = sorted((m.to_dict() for m in db.messages(uid, sid).get()), key=lambda m: m["seq"])
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["actionIds"] == [action_id]
    assert db.session(uid, sid).get().to_dict()["activeTurn"] is None


def test_approve_then_continuation_is_read_only(client, started):
    sid = new_session(client)
    action_id = next(e["actionId"] for e in events(ask(client, sid)) if e["type"] == "approval_request")
    r = client.post(f"/api/actions/{action_id}/decide", json={"decision": "approve"})
    assert r.status_code == 202
    cont = r.json()["continuationTurnId"]
    FakeLlm.log.clear()
    ev = events(client.post(f"/api/turns/{cont}/stream", json={}))
    assert ev[-1]["type"] == "done"
    assert FakeLlm.log and all(call["tools"] == [] for call in FakeLlm.log)  # one narrating call, no tools
    assert len(FakeLlm.log) == 1
    assert "Done." in "".join(e.get("delta", "") for e in ev)


def test_retry_replays_without_model_calls(client, started):
    sid = new_session(client)
    crid = str(uuid.uuid4())
    first = events(ask(client, sid, crid=crid))
    calls = len(FakeLlm.log)
    again = events(ask(client, sid, crid=crid))
    assert again[0]["replay"] is True and again[-1]["type"] == "done" and len(FakeLlm.log) == calls
    streamed = "".join(e["delta"] for e in first if e["type"] == "text")
    stored = next(m.to_dict()["text"] for m in db.messages(started, sid).get() if m.to_dict()["role"] == "assistant")
    assert streamed == stored == again[1]["delta"]  # browser, database and replay agree exactly
    r = ask(client, sid, text="something else", crid=crid)
    assert r.status_code == 409 and r.json()["code"] == "request_mismatch"


def _queue(uid, sid, text="hi"):
    return turns.accept_message(uid, sid, text, str(uuid.uuid4()))


def test_single_owner_and_lease_recovery(client, started):
    uid = started
    sid = new_session(client)
    turn_id = _queue(uid, sid)
    first = turns.claim(uid, turn_id)
    with pytest.raises(ApiError) as e:
        turns.claim(uid, turn_id)
    assert e.value.code == "turn_in_progress"
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.session(uid, sid).update({"activeTurn.leaseUntil": past})
    second = turns.claim(uid, turn_id)
    assert second.attempt == first.attempt + 1
    with pytest.raises(ApiError) as e:  # the dead attempt can no longer write
        turns.finish(uid, first, text="late", metrics={}, tool_calls=[], action_ids=[])
    assert e.value.code == "stale"


def test_reset_mid_turn_ends_stale_and_writes_nothing(client, started):
    uid = started
    sid = new_session(client)
    turn_id = _queue(uid, sid)
    claimed = turns.claim(uid, turn_id)
    demo.reset(uid)
    import asyncio

    async def collect():
        return [json.loads(x[5:]) async for x in turns.stream(uid, claimed, "ip")]

    ev = asyncio.run(collect())
    assert ev[-1]["type"] == "error" and ev[-1]["code"] == "stale"
    assert not any(m.to_dict()["role"] == "assistant" for m in db.messages(uid, sid).get())


def test_kill_switch_and_budget_block_before_model(client, started):
    sid = new_session(client)
    db.client().collection("ops").document("flags").set({"killSwitch": True})
    ev = events(ask(client, sid))
    assert ev[-1]["type"] == "error" and ev[-1]["code"] == "kill_switch" and FakeLlm.log == []
    db.client().collection("ops").document("flags").delete()
    from nightlight_api.config import settings
    db.client().collection("ops").document("quota").set({"reservedUsd": settings.model_budget_usd})
    ev = events(ask(client, sid))
    assert ev[-1]["type"] == "error" and ev[-1]["code"] == "quota_global" and FakeLlm.log == []


def test_reconcile_replaces_reservation(client, started):
    sid = new_session(client)
    events(ask(client, sid))
    g = db.client().collection("ops").document("quota").get().to_dict()
    assert g["calls"] == 3 and g["spentUsd"] > 0 and g["reservedUsd"] == pytest.approx(g["spentUsd"], rel=1e-6)


def test_turn_rate_limit(client, started, monkeypatch):
    from nightlight_api.config import settings
    monkeypatch.setattr(settings, "turns_per_uid_hour", 1)
    sid = new_session(client)
    assert ask(client, sid).status_code == 200
    r = ask(client, sid)
    assert r.status_code == 429 and r.json()["code"] == "quota_uid"


def test_fleet_summary_goes_into_the_instruction(started):
    from nightlight_api import agent as agentlib_
    text = agentlib_.fleet_summary(started, 1)
    assert "pi-1" in text and "94%" in text and "game-1" in text and "{" not in text and len(text.splitlines()) == 6


def test_conversations_are_kept_for_30_days_and_readable_in_order(client, started):
    from datetime import datetime, timedelta, timezone
    sid = new_session(client)
    events(ask(client, sid))
    msgs = sorted((m.to_dict() for m in db.messages(started, sid).get()), key=lambda m: m["seq"])
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    soon = datetime.now(timezone.utc) + timedelta(days=29)
    assert all(m["expiresAt"] > soon for m in msgs) and "actionIds" in msgs[1]


def test_stored_messages_keep_each_steps_outcome(client, started):
    sid = new_session(client)
    events(ask(client, sid))
    msg = next(m.to_dict() for m in db.messages(started, sid).get() if m.to_dict()["role"] == "assistant")
    assert msg["toolCalls"] and all("summary" in t for t in msg["toolCalls"])
