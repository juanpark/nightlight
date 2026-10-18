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


BOTH = {**OFFERS, "allowedJobs": {**OFFERS["allowedJobs"], "restart_container": ["pi-grafana-1"]}}


def test_a_failed_partial_change_on_the_device_means_measure_again(client, dev):
    uid = dev["uid"]
    beat_again = lambda: (_again(dev["token"]), beat(client, dev["token"], BOTH).json())[1]  # noqa: E731
    beat_again()
    _turn(uid, "turn_q")
    _turn(uid, "turn_q2")
    a = _ask(uid, dev["deviceId"], ["disk"], "turn_q")
    _finish_late(client, dev, a["id"])
    beat_again()  # the device offers the restart again (the helper's last report set what it allows)
    card = actions.propose(uid, session_id=SESSION, turn_id="turn_q", generation=generation(uid),
                           action_type="restart_container", device_id=dev["deviceId"],
                           params={"container": "pi-grafana-1"})
    actions.decide(uid, card["id"], "approve")
    handed = db.device(uid, dev["deviceId"]).get().to_dict().get("changedAt")
    assert [j["id"] for j in beat_again()["jobs"]] == [card["id"]]
    after_handover = db.device(uid, dev["deviceId"]).get().to_dict()["changedAt"]
    assert handed is None or after_handover > handed  # handing a changing job over marks the device
    r = client.post(f"/helper/jobs/{card['id']}/result", json={"ok": False, "summary": "Stopped halfway."},
                    headers={"X-Device-Token": dev["token"]})
    assert r.status_code == 200
    assert db.device(uid, dev["deviceId"]).get().to_dict()["changedAt"] >= after_handover
    b = _ask(uid, dev["deviceId"], ["disk"], "turn_q2")
    assert b["id"] != a["id"] and not b.get("reused")


def test_reuse_lookup_is_constant_no_scan_over_old_actions(client, dev, monkeypatch):
    from google.cloud.firestore_v1.collection import CollectionReference
    uid = dev["uid"]
    batch = db.client().batch()
    old = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for i in range(100):
        batch.set(db.actions(uid).document(f"act_old{i:03d}"),
                  {"deviceId": dev["deviceId"], "type": "inspect", "status": "done", "sessionId": SESSION,
                   "params": {"what": ["disk"]}, "demoGeneration": generation(uid), "createdAt": old,
                   "finishedAt": old})
    batch.commit()
    queried = []
    where = CollectionReference.where
    monkeypatch.setattr(CollectionReference, "where",
                        lambda self, *a, **k: (queried.append(self.id), where(self, *a, **k))[1])
    _turn(uid, "turn_q")
    _turn(uid, "turn_q2")
    a = _ask(uid, dev["deviceId"], ["disk"], "turn_q")
    assert not a.get("reused")
    assert _ask(uid, dev["deviceId"], ["disk"], "turn_q2")["id"] == a["id"]
    assert "actions" not in queried
    recent = db.session(uid, SESSION).get().to_dict()["recentReads"]
    assert len(recent) == 1


def test_concurrent_asks_from_two_turns_make_one_job(client, dev):
    import threading
    uid = dev["uid"]
    turns = [f"turn_c{i}" for i in range(4)]
    for t in turns:
        _turn(uid, t)
    got = []
    threads = [threading.Thread(target=lambda t=t: got.append(_ask(uid, dev["deviceId"], ["disk"], t)["id"]))
               for t in turns]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(got) == 4 and len(set(got)) == 1


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
