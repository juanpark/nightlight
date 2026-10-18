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
    assert msg["metrics"]["modelCalls"] >= 1 and "latencyMs" in msg["metrics"] and "model" in msg["metrics"]


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


def _two_devices_at_once(llm_request, stream):
    """Reads two devices with the same tool in one response (parallel calls); then answers."""
    async def gen():
        asked = any(p.function_response for c in llm_request.contents for p in (c.parts or []))
        parts = [types.Part(text="Both read.")] if asked else [
            types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"})),
            types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "nas-1"}))]
        yield LlmResponse(content=types.Content(role="model", parts=parts), partial=False, turn_complete=True)
    return gen()


def test_parallel_calls_of_one_tool_pair_with_their_own_results(client, started):
    FakeLlm.behavior = _two_devices_at_once
    sid = new_session(client)
    ev = events(ask(client, sid))
    calls = [e for e in ev if e["type"] == "tool_call"]
    results = [e for e in ev if e["type"] == "tool_result"]
    assert len(calls) == 2 and len({c["callId"] for c in calls}) == 2
    assert sorted(r["callId"] for r in results) == sorted(c["callId"] for c in calls)
    msg = next(m.to_dict() for m in db.messages(started, sid).get() if m.to_dict()["role"] == "assistant")
    by_id = {t["callId"]: t for t in msg["toolCalls"]}
    for r in results:  # each stored step holds its own result, whichever answered first
        assert by_id[r["callId"]]["summary"] == r["summary"]
    assert {t["args"]["device_id"] for t in msg["toolCalls"]} == {"pi-1", "nas-1"}
    names = {t["args"]["device_id"]: t["summary"] for t in msg["toolCalls"]}
    assert names["pi-1"] != names["nas-1"]


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


def test_the_answer_is_never_rewritten_to_match_the_cards(client, started):
    # Cards come from approval_request events, not from the words: the server neither makes a card from prose nor
    # edits the prose. What the model said is exactly what is shown and stored.
    from fake_llm import reply
    said = "I've put a card up for your approval to clean up old logs."
    FakeLlm.behavior = reply(said)
    sid = new_session(client)
    ev = events(ask(client, sid, "Clean up the Pi please"))
    text = "".join(e.get("delta", "") for e in ev if e["type"] == "text")
    stored = next(m.to_dict()["text"] for m in db.messages(started, sid).get() if m.to_dict()["role"] == "assistant")
    assert text == stored == said and not any(e["type"] in ("approval_request", "tool_call") for e in ev)


def _final(text=None, finish=None):
    from google.adk.models.llm_response import LlmResponse as R
    u = types.GenerateContentResponseUsageMetadata(prompt_token_count=500, candidates_token_count=20,
                                                   total_token_count=520)
    parts = [types.Part(text=text)] if text is not None else []
    return R(content=types.Content(role="model", parts=parts), partial=False, usage_metadata=u, turn_complete=True,
             finish_reason=finish)


def test_an_empty_answer_is_asked_for_once_more_without_new_checks(client, started):
    seen = []

    async def behave(llm_request, stream):
        cfg = llm_request.config.tool_config
        seen.append((cfg and cfg.function_calling_config.mode, FakeLlm.log[-1]["text"]))
        yield _final("" if len(seen) == 1 else "The Pi's disk is 94% full.")
    FakeLlm.behavior = behave
    sid = new_session(client)
    ev = events(ask(client, sid, "How is the Pi?"))
    text = "".join(e.get("delta", "") for e in ev if e["type"] == "text")
    assert text == "The Pi's disk is 94% full." and ev[-1]["type"] == "done"
    assert len(seen) == 2 and ev[-1]["metrics"]["modelCalls"] == 2  # counted like any call
    assert seen[0][0] is None and seen[1][0] == types.FunctionCallingConfigMode.NONE
    assert turns.SHORTER["empty"] in seen[1][1]


def test_a_cut_off_answer_is_not_shown_and_is_asked_for_shorter(client, started):
    calls = []

    async def behave(llm_request, stream):
        calls.append(1)
        if len(calls) == 1:
            yield _final("The Pi's disk is nearly full because its logs have grown and I'd", types.FinishReason.MAX_TOKENS)
        else:
            yield _final("The Pi's disk is 94% full of old logs.")
    FakeLlm.behavior = behave
    sid = new_session(client)
    ev = events(ask(client, sid, "How is the Pi?"))
    text = "".join(e.get("delta", "") for e in ev if e["type"] == "text")
    assert text == "The Pi's disk is 94% full of old logs." and len(calls) == 2
    assert turns.SHORTER["cut"] in FakeLlm.log[-1]["text"]


def test_no_answer_twice_ends_honestly(client, started):
    async def behave(llm_request, stream):
        yield _final("")
    FakeLlm.behavior = behave
    sid = new_session(client)
    ev = events(ask(client, sid, "How is the Pi?"))
    text = "".join(e.get("delta", "") for e in ev if e["type"] == "text")
    stored = next(m.to_dict()["text"] for m in db.messages(started, sid).get() if m.to_dict()["role"] == "assistant")
    assert text == stored == turns.NO_ANSWER and ev[-1]["type"] == "done" and ev[-1]["metrics"]["modelCalls"] == 2


def test_words_already_shown_stay_and_the_failure_follows_them(client, started):
    calls = []

    async def behave(llm_request, stream):
        calls.append(1)
        if len(calls) == 1:
            yield LlmResponse(content=types.Content(role="model", parts=[
                types.Part(text="Checking the Pi."),
                types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"}))]),
                partial=False, turn_complete=True)
        else:
            yield _final(None)
    FakeLlm.behavior = behave
    ev = events(ask(client, new_session(client), "How is the Pi?"))
    text = "".join(e.get("delta", "") for e in ev if e["type"] == "text")
    assert text == "Checking the Pi.\n\n" + turns.NO_ANSWER and len(calls) == 3


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


def _scripted(*steps):
    from google.adk.models.llm_response import LlmResponse as R
    calls = []

    async def behave(llm_request, stream):
        step = steps[min(len(calls), len(steps) - 1)]
        calls.append(1)
        part = types.Part(function_call=types.FunctionCall(name=step[0], args=step[1])) if isinstance(step, tuple) \
            else types.Part(text=step)
        u = types.GenerateContentResponseUsageMetadata(prompt_token_count=500, candidates_token_count=20,
                                                       total_token_count=520)
        yield R(content=types.Content(role="model", parts=[part]), partial=False, usage_metadata=u,
                turn_complete=True)
    return behave


def test_a_log_lock_fails_only_the_log_clean_up(client, started):  # Codex agent quality #2
    from nightlight_api import actions
    from conftest import generation
    assert client.post("/api/demo/inject", json={"kind": "logs_locked", "deviceId": "pi-1"}).status_code == 201
    card = actions.propose(started, session_id="s", turn_id="t", generation=generation(started),
                           action_type="clear_images", device_id="pi-1", params={})
    assert client.post(f"/api/actions/{card['id']}/decide", json={"decision": "approve"}).json()["status"] == "done"
    card = actions.propose(started, session_id="s", turn_id="t2", generation=generation(started),
                           action_type="rotate_logs", device_id="pi-1", params={})
    d = client.post(f"/api/actions/{card['id']}/decide", json={"decision": "approve"}).json()
    assert d["status"] == "failed"
    assert "locked" in db.action(started, card["id"]).get().to_dict()["result"]["summary"]


def test_a_waiting_trust_offer_is_in_the_home_summary(client, started):
    from nightlight_api import trust as trustlib
    from conftest import generation
    g = generation(started)
    assert "Trust offers" not in agentlib.fleet_summary(started, g)
    doc = {**trustlib.new_doc("rotate_logs", g), "offer": {"offerId": "offer_x", "demoGeneration": g, "text": "x"}}
    db.trust_doc(started, "sim", "rotate_logs").set(doc)
    assert "Trust offers waiting for their answer in the Trust panel: Clean up old activity files (logs)" in \
        agentlib.fleet_summary(started, g)


def test_a_declined_card_says_nothing_changed_and_carries_the_known_state(client, started):
    from nightlight_api import actions
    from conftest import generation
    sid = new_session(client)
    card = actions.propose(started, session_id=sid, turn_id="turn_decline", generation=generation(started),
                           action_type="restart_app", device_id="mac-1", params={})
    r = client.post(f"/api/actions/{card['id']}/decide", json={"decision": "deny"})
    cont = r.json()["continuationTurnId"]
    turn = db.turns(started, sid).document(cont).get().to_dict()
    assert "nothing was changed" in turn["input"] and card["plan"] in turn["input"]
    assert "Up 3 days (unhealthy)" in turn["input"]  # the state the server knows, never a guess
    FakeLlm.log.clear()
    events(client.post(f"/api/turns/{cont}/stream", json={}))
    assert "If they declined with a reason, acknowledge" in " ".join(FakeLlm.log[0]["system"].split())
    assert "Up 3 days (unhealthy)" in FakeLlm.log[0]["text"]


def test_the_prompt_is_a_short_charter():
    # Which tool to call when lives in the tools and the home summary; the prompt says who Nightlight is.
    assert len(agentlib.INSTRUCTION) <= 2400 and len(agentlib.DEEP) <= 900
    assert len(agentlib.CONTINUATION) <= 500 and len(agentlib.MEMORY_RULES) <= 300
    said = " ".join((agentlib.INSTRUCTION + agentlib.DEEP).split())
    assert "Let me check" not in said and "I've put a card up" not in said and "simulated" not in said
    assert "write down a cause you found" in said and "don't contradict a cause this conversation established" in said


def test_the_home_summary_lists_apps_and_never_calls_unknown_healthy(client, started):
    from conftest import generation
    text = agentlib.fleet_summary(started, generation(started))
    assert "Apps: " in text and "plex" in text
    camera = next(line for line in text.splitlines() if line.startswith("- nvr-1 "))
    assert "Health: not checked (nothing reports from it" in camera and "answer" not in camera
    assert "simulated" not in text and "sample" not in text.lower()  # no word in the context it shouldn't say


def test_a_decline_reason_and_an_opened_trust_offer_reach_the_chat(client, started):
    from nightlight_api import actions, trust as trustlib
    from conftest import generation
    g = generation(started)
    sid = new_session(client)
    card = actions.propose(started, session_id=sid, turn_id="t_d", generation=g, action_type="backup_world",
                           device_id="game-1", params={})
    r = client.post(f"/api/actions/{card['id']}/decide", json={"decision": "deny", "note": "they're mid-game"})
    turn = db.turns(started, sid).document(r.json()["continuationTurnId"]).get().to_dict()
    assert "they're mid-game" in turn["input"] and "propose nothing more disruptive" in turn["input"]
    ref = db.trust_doc(started, "sim", "rotate_logs")
    doc = trustlib.new_doc("rotate_logs", g)
    doc["successes"] = [{"actionId": f"a{i}", "at": None} for i in range(2)]
    ref.set(doc)
    card = actions.propose(started, session_id=sid, turn_id="t_o", generation=g, action_type="rotate_logs",
                           device_id="pi-1", params={})
    r = client.post(f"/api/actions/{card['id']}/decide", json={"decision": "approve"})
    turn = db.turns(started, sid).document(r.json()["continuationTurnId"]).get().to_dict()
    if (ref.get().to_dict() or {}).get("offer"):
        assert "Trust:" in turn["input"] and "Trust panel" in turn["input"]


def test_a_restart_card_warns_when_the_world_isnt_backed_up(client, started):
    from nightlight_api import actions
    from conftest import generation
    client.post("/api/demo/inject", json={"kind": "server_lagging", "deviceId": "game-1"})
    card = actions.propose(started, session_id="s", turn_id="t_r", generation=generation(started),
                           action_type="restart_server", device_id="game-1", params={}, skip_safer=True)
    assert "hasn't been backed up in 9 days: back it up first" in card["dryRun"]  # backup skipped: still warned


def test_a_narration_follow_up_never_gets_a_made_up_tool_call(client, started):  # Codex final polish #1
    from nightlight_api import actions
    from conftest import generation
    sid = new_session(client)
    card = actions.propose(started, session_id=sid, turn_id="t_n", generation=generation(started),
                           action_type="rotate_logs", device_id="pi-1", params={})
    cont = client.post(f"/api/actions/{card['id']}/decide", json={"decision": "deny"}).json()["continuationTurnId"]
    FakeLlm.behavior = _scripted("Let me check the Raspberry Pi.")
    ev = events(client.post(f"/api/turns/{cont}/stream", json={}))
    assert not any(e["type"] == "tool_call" for e in ev) and ev[-1]["type"] == "done"


def test_a_decline_never_promises_a_reminder(client, started):  # Codex final polish #2
    from nightlight_api import conversation
    text = conversation.render("job_declined", {"type": "rotate_logs", "plan": "Clean up.",
                                                "decision": {"note": "not now"}}, "Raspberry Pi")
    assert "remind" not in text and "ask again whenever it suits them" in text


def test_a_long_app_list_says_it_is_partial(client, started):  # Codex final polish #3
    from conftest import generation
    text = agentlib.fleet_summary(started, generation(started))
    mac = next(line for line in text.splitlines() if line.startswith("- mac-1 "))
    assert "and more (get_device lists them all)" in mac  # the sample Mac Mini runs 14 apps


def test_the_answer_only_retry_never_runs_a_tool(client, started):  # Codex charter #1
    calls = []

    async def behave(llm_request, stream):
        calls.append(1)
        if len(calls) == 1:
            yield _final("")
        else:  # ignores the NONE tool mode and asks for a card anyway
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(
                function_call=types.FunctionCall(name="rotate_logs", args={"device_id": "pi-1"}))]),
                partial=False, turn_complete=True)
    FakeLlm.behavior = behave
    ev = events(ask(client, new_session(client), "How is the Pi?"))
    text = "".join(e.get("delta", "") for e in ev if e["type"] == "text")
    assert text == turns.NO_ANSWER and len(calls) == 2 and ev[-1]["type"] == "done"
    assert not any(e["type"] in ("tool_call", "approval_request") for e in ev)
    assert not [a for a in db.actions(started).get() if a.to_dict().get("status") == "pending"]


def test_cut_off_words_beside_a_tool_call_are_never_shown(client, started):  # Codex charter #2
    calls = []

    async def behave(llm_request, stream):
        calls.append(1)
        if len(calls) == 1:
            yield LlmResponse(content=types.Content(role="model", parts=[
                types.Part(text="The cause is definitely the disk and you must"),
                types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"}))]),
                partial=False, turn_complete=True, finish_reason=types.FinishReason.MAX_TOKENS)
        else:
            yield _final("The Pi's disk is 94% full.")
    FakeLlm.behavior = behave
    sid = new_session(client)
    ev = events(ask(client, sid, "How is the Pi?"))
    text = "".join(e.get("delta", "") for e in ev if e["type"] == "text")
    stored = next(m.to_dict()["text"] for m in db.messages(started, sid).get() if m.to_dict()["role"] == "assistant")
    assert text == stored == "The Pi's disk is 94% full." and len(calls) == 2
    assert [e["name"] for e in ev if e["type"] == "tool_call"] == ["get_device"]
    assert any(e["type"] == "tool_result" for e in ev)


def test_one_command_per_response_and_no_tools_while_retrying():  # Codex charter coverage
    class T:
        def __init__(self, name):
            self.name = name
    ctx = agentlib.TurnContext("u", "s", "t", 1, 1, "ip", deep=True)
    _bm, _am, before_tool = agentlib.make_callbacks(ctx)
    assert before_tool(T("run_command"), {}, None) is None
    assert "one command at a time" in before_tool(T("run_command"), {}, None)["reason"]
    assert before_tool(T("get_device"), {}, None) is None  # other reads in the same response are fine
    ctx.metrics["modelCalls"] += 1
    assert before_tool(T("run_command"), {}, None) is None  # the next response may run the next command
    ctx.retry_from = ctx.metrics["modelCalls"]
    assert before_tool(T("get_device"), {}, None) == {"error": "no more checks in this answer"}


def test_the_home_summary_names_saved_fixes(client, started):  # Codex charter coverage
    from conftest import generation
    text = agentlib.fleet_summary(started, generation(started))
    mac = next(line for line in text.splitlines() if line.startswith("- mac-1 "))
    assert "Saved fixes that worked here before (runbooks): " in mac


def test_one_card_returned_by_two_steps_sits_after_the_first(client, started):  # Codex contracts #4
    FakeLlm.behavior = _scripted(("rotate_logs", {"device_id": "pi-1"}), ("clear_images", {"device_id": "pi-1"}),
                                 "The Pi is full.")
    sid = new_session(client)
    ev = events(ask(client, sid, "고쳐줘"))
    assert len([e for e in ev if e["type"] == "approval_request"]) == 1
    msg = next(m.to_dict() for m in db.messages(started, sid).get() if m.to_dict()["role"] == "assistant")
    assert [bool(t.get("actionId")) for t in msg["toolCalls"]] == [True, False]  # a reload rebuilds one card


def test_long_chat_is_flagged_on_the_receipt(client, started, monkeypatch):
    """A chat whose older messages no longer fit the history window keeps going; its receipt carries longChat so
    the chat can suggest a fresh start."""
    from nightlight_api.config import settings
    monkeypatch.setattr(settings, "history_messages", 2)
    sid = new_session(client)
    first = events(ask(client, sid))
    assert first[-1]["type"] == "done" and "longChat" not in first[-1]["metrics"]
    events(ask(client, sid, text="And my NAS?"))
    third = events(ask(client, sid, text="And the Mac mini?"))
    assert third[-1]["type"] == "done" and third[-1]["metrics"]["longChat"] is True
