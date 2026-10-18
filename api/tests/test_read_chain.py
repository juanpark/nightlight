"""Device reads are de-duplicated per chat, and automatic follow-ups can't chain reads forever.

Production 2026-10-18 (Investigate): one question was followed by five automatic follow-ups, each re-running the same
disk checkup on the Mac mini; the device took longer than the in-turn wait, so each new job's own follow-up asked again.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from nightlight_api import actions, agent as agentlib, db
from nightlight_api.ids import continuation_turn_id
from conftest import generation
from test_inspect import OFFERS
from test_real import beat, enrolled
from test_real_jobs import _again

SESSION = "sess_test"


def _turn(uid, turn_id, **doc):
    db.turns(uid, SESSION).document(turn_id).set({"kind": "user", "status": "running", "mode": "investigate", **doc})


def _ask(uid, device_id, what, turn):
    return actions.request_inspection(uid, session_id=SESSION, turn_id=turn, generation=generation(uid),
                                      device_id=device_id, what=what, mode="investigate")


def _finish_late(client, dev, aid, summary="Checked: disk"):
    """The device answers after the asking turn stopped waiting: the result arrives as an event turn."""
    assert actions.await_diagnosis(dev["uid"], aid) is None  # the in-turn wait ran out: a follow-up is wanted
    _again(dev["token"])
    beat(client, dev["token"], OFFERS)  # hands the job to the device (running)
    r = client.post(f"/helper/jobs/{aid}/result", json={"ok": True, "summary": summary, "output": "App caches: 3 GB"},
                    headers={"X-Device-Token": dev["token"]})
    assert r.status_code == 200
    event = db.turns(dev["uid"], SESSION).document(continuation_turn_id(aid)).get().to_dict()
    assert event["kind"] == "event" and event["policy"] == "continue"
    return continuation_turn_id(aid), event


@pytest.fixture
def dev(client, started):
    d = enrolled(client)
    beat(client, d["token"], OFFERS)
    return {**d, "uid": started}


def test_a_follow_up_asking_for_the_same_check_gets_the_finished_result(client, dev):
    uid = dev["uid"]
    _turn(uid, "turn_q")
    a = _ask(uid, dev["deviceId"], ["disk"], "turn_q")
    assert a["status"] == "approved" and a["chainDepth"] == 0 and not a.get("reused")
    cont, event = _finish_late(client, dev, a["id"])
    assert event["chainDepth"] == 0 and event["causedByTurn"] == "turn_q"
    again = _ask(uid, dev["deviceId"], ["disk"], cont)
    assert again["id"] == a["id"] and again["reused"] is True and again["status"] == "done"
    assert 0 <= again["ageSeconds"] < 60
    jobs = [s for s in db.actions(uid).get() if s.to_dict().get("type") == "inspect"]
    assert len(jobs) == 1  # nothing new was handed to the device


def test_a_check_still_running_is_not_asked_twice(client, dev):
    uid = dev["uid"]
    _turn(uid, "turn_q")
    _turn(uid, "turn_q2")
    a = _ask(uid, dev["deviceId"], ["disk"], "turn_q")
    again = _ask(uid, dev["deviceId"], ["disk"], "turn_q2")
    assert again["id"] == a["id"] and again["reused"] is True and again["status"] == "approved"


def test_a_change_on_the_device_since_means_measure_again(client, dev):
    uid = dev["uid"]
    _turn(uid, "turn_q")
    _turn(uid, "turn_q2")
    a = _ask(uid, dev["deviceId"], ["disk"], "turn_q")
    _finish_late(client, dev, a["id"])
    db.actions(uid).document("act_cleanup").set({"deviceId": dev["deviceId"], "type": "fix", "status": "done",
                                                 "finishedAt": datetime.now(timezone.utc)})
    b = _ask(uid, dev["deviceId"], ["disk"], "turn_q2")
    assert b["id"] != a["id"] and not b.get("reused")


def test_other_chats_and_the_app_still_get_their_own_job(client, dev):
    uid = dev["uid"]
    _turn(uid, "turn_q")
    a = _ask(uid, dev["deviceId"], ["disk"], "turn_q")
    other = actions.request_inspection(uid, session_id="sess_other", turn_id="turn_o", generation=generation(uid),
                                       device_id=dev["deviceId"], what=["disk"])
    assert other["id"] != a["id"] and not other.get("reused")


def test_the_follow_up_chain_stops_after_depth_one(client, dev):
    uid = dev["uid"]
    _turn(uid, "turn_q")
    a = _ask(uid, dev["deviceId"], ["disk"], "turn_q")
    cont_a, _ = _finish_late(client, dev, a["id"])
    # The first follow-up (depth 0) may still look further: a normal Investigate flow.
    b = _ask(uid, dev["deviceId"], ["load"], cont_a)
    assert b["status"] == "approved" and b["chainDepth"] == 1 and b["causedByTurn"] == cont_a
    cont_b, event_b = _finish_late(client, dev, b["id"], "Checked: load")
    assert event_b["chainDepth"] == 1 and event_b["causedByTurn"] == cont_a
    # The follow-up caused by a job a follow-up started narrates: no new device reads...
    with pytest.raises(ValueError, match="chain_limit"):
        _ask(uid, dev["deviceId"], ["network"], cont_b)
    # ...but the same read it already has comes back (reused, nothing runs).
    assert _ask(uid, dev["deviceId"], ["load"], cont_b)["reused"] is True
    # A new question from the person starts fresh.
    _turn(uid, "turn_q3")
    assert _ask(uid, dev["deviceId"], ["network"], "turn_q3")["chainDepth"] == 0


def _tools(uid, turn):
    db.session(uid, SESSION).set({"activeTurn": {"turnId": turn, "attempt": 1}}, merge=True)
    ctx = agentlib.TurnContext(uid=uid, session_id=SESSION, turn_id=turn, attempt=1, generation=generation(uid),
                               ip="1.2.3.4", deep=True)
    return {t.__name__: t for t in agentlib.make_tools(ctx, read_only=False)}


def test_agent_tools_say_reused_and_refuse_past_the_chain_limit(client, dev):
    uid = dev["uid"]
    _turn(uid, "turn_q")
    a = _ask(uid, dev["deviceId"], ["disk"], "turn_q")
    cont_a, _ = _finish_late(client, dev, a["id"])
    out = asyncio.run(_tools(uid, cont_a)["inspect"](dev["deviceId"], ["disk"], tool_context=None))
    assert out["reused"] is True and out["status"] == "done" and "3 GB" in out["output"]
    assert isinstance(out["ageSeconds"], int) and "Not run again" in out["note"]
    b = _ask(uid, dev["deviceId"], ["load"], cont_a)
    cont_b, _ = _finish_late(client, dev, b["id"], "Checked: load")
    tools = _tools(uid, cont_b)
    out = asyncio.run(tools["inspect"](dev["deviceId"], ["network"], tool_context=None))
    assert out["status"] == "error" and out["reason"] == agentlib.CHAIN_LIMIT_SAY
    out = asyncio.run(tools["check_space"](tool_context=None, device_id=dev["deviceId"]))
    assert out["status"] == "error" and out["reason"] == agentlib.CHAIN_LIMIT_SAY
