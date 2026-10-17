import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nightlight_api import agent as agentlib, db, demo, turns
from nightlight_api.errors import ApiError
from fake_llm import FakeLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types


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
    for d in db.client().collection("ipQuotas").list_documents():  # probes sharing this emulator count calls too
        d.delete()
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
    assert "pi-1" in text and "94%" in text and "game-1" in text and "{" not in text and len(text.split("\nHow they connect")[0].splitlines()) == 6


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
    # enough to rebuild the live work log after a reload: where each step sat in the text, whether it worked, how long
    assert all(isinstance(t["textOffset"], int) and t["ok"] is True and t["ms"] >= 0 and "_t" not in t
               for t in msg["toolCalls"])
    assert msg["mode"] == "quick"


def _moon_then_check(llm_request, stream):
    """Says a few words with a character outside the BMP, then reads the Pi; then answers."""
    async def gen():
        asked = any(p.function_response for c in llm_request.contents for p in (c.parts or []))
        parts = [types.Part(text="Done.")] if asked else [
            types.Part(text="Night \U0001F319 check."),
            types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"}))]
        yield LlmResponse(content=types.Content(role="model", parts=parts), partial=False, turn_complete=True)
    return gen()


def test_step_offsets_count_utf16_units_like_the_browser(client, started):
    FakeLlm.behavior = _moon_then_check
    sid = new_session(client)
    events(ask(client, sid))
    msg = next(m.to_dict() for m in db.messages(started, sid).get() if m.to_dict()["role"] == "assistant")
    off = msg["toolCalls"][0]["textOffset"]
    before = msg["text"].encode("utf-16-le")[:2 * off].decode("utf-16-le")  # raises if a pair were split
    assert before.strip() == "Night \U0001F319 check."


def test_a_dropped_stream_stops_the_turn_and_frees_the_chat(client, started):
    # Stop in the browser (or a closed page) ends the reading; the turn then ends as "stopped" at once, keeps what was
    # already done, and the next question isn't refused with turn_in_progress while a lease runs out.
    import asyncio
    FakeLlm.behavior = _moon_then_check
    sid = new_session(client)
    turn_id = turns.accept_message(started, sid, "What's wrong with my Pi?", str(uuid.uuid4()))
    claimed = turns.claim(started, turn_id)

    async def read_a_little_then_drop():
        gen = turns.stream(started, claimed, "127.0.0.1")
        seen = [json.loads((await gen.__anext__())[5:])]
        while seen[-1]["type"] != "tool_call":
            chunk = await gen.__anext__()
            if chunk.startswith("data:"):
                seen.append(json.loads(chunk[5:]))
        await gen.aclose()
        return seen

    seen = asyncio.run(read_a_little_then_drop())
    assert seen[-1]["type"] == "tool_call"
    turn = db.turns(started, sid).document(turn_id).get().to_dict()
    assert turn["status"] == "failed" and turn["error"]["code"] == "stopped"
    assert db.session(started, sid).get().to_dict()["activeTurn"] is None
    kept = next(m.to_dict() for m in db.messages(started, sid).get() if m.to_dict()["role"] == "assistant")
    assert kept["error"]["code"] == "stopped" and kept["text"].startswith("Night")
    step = kept["toolCalls"][0]  # it never answered: stored as unfinished, never as a success
    assert step.get("unfinished") is True and step["ok"] is False
    FakeLlm.behavior = None
    assert ask(client, sid, "And now?").status_code == 200  # the chat is free right away


def test_stopping_on_the_first_frame_also_frees_the_chat(client, started):
    import asyncio
    sid = new_session(client)
    turn_id = turns.accept_message(started, sid, "Hello?", str(uuid.uuid4()))
    claimed = turns.claim(started, turn_id)

    async def first_frame_then_drop():
        gen = turns.stream(started, claimed, "127.0.0.1")
        assert json.loads((await gen.__anext__())[5:])["type"] == "turn_start"
        await gen.aclose()

    asyncio.run(first_frame_then_drop())
    turn = db.turns(started, sid).document(turn_id).get().to_dict()
    assert turn["status"] == "failed" and turn["error"]["code"] == "stopped"
    assert db.session(started, sid).get().to_dict()["activeTurn"] is None
    # a turn that is already over is never touched by a dropped replay
    replay = turns.claim(started, turn_id)
    assert replay.mode == "failed"


def test_a_card_claimed_without_a_card_is_corrected(client, started):
    from fake_llm import reply
    FakeLlm.behavior = reply("I've put a card up for your approval to clean up old logs.")
    ev = events(ask(client, new_session(client), "Clean up the Pi please"))
    text = "".join(e.get("delta", "") for e in ev if e["type"] == "text")
    assert text.endswith(turns.NO_CARD) and not any(e["type"] == "approval_request" for e in ev)
    FakeLlm.behavior = reply("The card I put up earlier is still waiting for you.")
    ev = events(ask(client, new_session(client), "Is the card still there?"))
    assert turns.NO_CARD not in "".join(e.get("delta", "") for e in ev if e["type"] == "text")


def test_the_sample_mac_minis_unhealthy_app_has_a_fix(client, started):
    from nightlight_api import actions, sim
    from conftest import generation
    svcs = {s.id: s.to_dict() for s in db.services(started, "mac-1").get()}
    device = dict(db.device(started, "mac-1").get().to_dict(), id="mac-1")
    assert any(f["tool"] == "restart_app" for f in sim.fixes(device, svcs))
    card = actions.propose(started, session_id="s", turn_id="t", generation=generation(started),
                           action_type="restart_app", device_id="mac-1", params={})
    assert card["status"] == "pending" and "Immich" in card["plan"]
    d = client.post(f"/api/actions/{card['id']}/decide", json={"decision": "approve"}).json()
    assert d["status"] == "done"
    immich = db.services(started, "mac-1").document("immich").get().to_dict()
    assert immich["status"] == "ok" and immich["findings"] == []
    svcs = {s.id: s.to_dict() for s in db.services(started, "mac-1").get()}
    assert not any(f["tool"] == "restart_app" for f in sim.fixes(device, svcs))


def test_a_full_sample_pi_offers_logs_first_and_unused_images_as_an_option(client, started):
    from nightlight_api import actions, sim
    from conftest import generation
    device = dict(db.device(started, "pi-1").get().to_dict(), id="pi-1")
    svcs = {s.id: s.to_dict() for s in db.services(started, "pi-1").get()}
    assert [f["tool"] for f in sim.fixes(device, svcs) if f["for"] == "disk_over_90"] == ["rotate_logs", "clear_images"]
    card = actions.propose(started, session_id="s", turn_id="t", generation=generation(started),
                           action_type="clear_images", device_id="pi-1", params={})
    assert "Nothing to undo" in card["rollback"]
    assert client.post(f"/api/actions/{card['id']}/decide", json={"decision": "approve"}).json()["status"] == "done"
    device = dict(db.device(started, "pi-1").get().to_dict(), id="pi-1")
    assert device["vitals"]["diskPct"] < 94
    assert "clear_images" not in [f["tool"] for f in sim.fixes(device, svcs)]


def test_an_unbacked_card_claim_becomes_the_tool_call(client, started):
    # The model reads the full Pi, then only *says* it put a card up: the claim is turned into the fix it offered.
    from google.adk.models.llm_response import LlmResponse as R
    calls = []

    async def behave(llm_request, stream):
        calls.append(1)
        if len(calls) == 1:
            part = types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"}))
        elif len(calls) == 2:
            part = types.Part(text="The Pi is 94% full. I've put a card up to clean up old log files.")
        else:
            part = types.Part(text="A card to clean up old logs is waiting for your tap.")
        u = types.GenerateContentResponseUsageMetadata(prompt_token_count=500, candidates_token_count=20,
                                                       total_token_count=520)
        yield R(content=types.Content(role="model", parts=[part]), partial=False, usage_metadata=u,
                turn_complete=True)
    FakeLlm.behavior = behave
    ev = events(ask(client, new_session(client), "Is anything wrong at home?"))
    names = [e["name"] for e in ev if e["type"] == "tool_call"]
    text = "".join(e.get("delta", "") for e in ev if e["type"] == "text")
    assert names == ["get_device", "rotate_logs"] and any(e["type"] == "approval_request" for e in ev)
    assert turns.NO_CARD not in text and "I've put a card up" not in text
