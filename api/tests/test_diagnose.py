"""Read-only looks on real devices: owner-allowed targets only, no card, at-most-once, results scrubbed, one narrator."""

import pytest

from nightlight_api import actions, db, real
from conftest import generation
from test_real import FACTS, beat, enrolled

ALLOW = {**FACTS, "allowedJobs": {"diagnose": ["pi-grafana-1", "pihole-FTL.service"], "logs": ["pi-grafana-1"]}}


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None, "lastClaimAt": None})


def _ask(uid, device_id, target="pi-grafana-1", turn="turn_d"):
    return actions.request_diagnosis(uid, session_id="sess_test", turn_id=turn, generation=generation(uid),
                                     device_id=device_id, target=target)


def _result(client, token, aid, **body):
    return client.post(f"/helper/jobs/{aid}/result", json={"ok": True, "summary": "s", **body},
                       headers={"X-Device-Token": token})


def test_allowed_target_is_asked_without_a_card_and_answered_once(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _ask(started, dev["deviceId"])
    assert a["status"] == "approved" and a["riskClass"] == "read" and "log lines" in a["dryRun"]
    _again(dev["token"])
    jobs = beat(client, dev["token"], ALLOW).json()["jobs"]
    assert jobs == [{"id": a["id"], "type": "diagnose", "params": {"target": "pi-grafana-1"}}]
    fake = "password=" + "hunter2hunter2"
    assert _result(client, dev["token"], a["id"], output=f"exit code 1\n{fake}").status_code == 200
    done = db.action(started, a["id"]).get().to_dict()
    assert done["status"] == "done" and "hunter2hunter2" not in done["result"]["output"]
    assert "continuationTurnId" not in done  # the turn that asked was still waiting: it narrates, no follow-up


def test_only_targets_allowed_on_the_device(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    with pytest.raises(ValueError, match="not_allowed_on_device"):
        _ask(started, dev["deviceId"], "pi-teslamate-1")
    with pytest.raises(ValueError, match="bad_target"):
        _ask(started, dev["deviceId"], "--all; rm")
    with pytest.raises(ValueError):
        _ask(started, "pi-1")  # sample devices aren't looked into
    assert _ask(started, dev["deviceId"], "pihole-FTL.service", turn="t2")["status"] == "approved"


def test_late_answer_gets_exactly_one_follow_up(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _ask(started, dev["deviceId"])
    assert actions.await_diagnosis(started, a["id"]) is None  # the turn stopped waiting
    _again(dev["token"])
    beat(client, dev["token"], ALLOW)
    _result(client, dev["token"], a["id"], output="exit code 137")
    done = db.action(started, a["id"]).get().to_dict()
    turn = db.turns(started, "sess_test").document(done["continuationTurnId"]).get().to_dict()
    assert "Look into" in turn["input"] and "exit code 137" in turn["input"]


def test_answer_arriving_as_the_wait_ends_is_returned_not_followed_up(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _ask(started, dev["deviceId"])
    _again(dev["token"])
    beat(client, dev["token"], ALLOW)
    _result(client, dev["token"], a["id"], output="ok")
    doc = actions.await_diagnosis(started, a["id"])
    assert doc["status"] == "done" and "continuationTurnId" not in db.action(started, a["id"]).get().to_dict()


def test_quick_checks_while_chatting(client, started):
    from datetime import datetime, timezone
    dev = enrolled(client)
    assert beat(client, dev["token"], ALLOW).json()["pollEverySec"] == 0
    db.user(started).update({"lastChatAt": datetime.now(timezone.utc)})
    _again(dev["token"])
    assert beat(client, dev["token"], ALLOW).json()["pollEverySec"] == real.FAST_POLL_SECONDS
    a = _ask(started, dev["deviceId"])
    h = {"X-Device-Token": dev["token"]}
    r = client.post("/helper/jobs/claim", json={}, headers=h)
    assert r.status_code == 200 and [j["id"] for j in r.json()["jobs"]] == [a["id"]]
    assert client.post("/helper/jobs/claim", json={}, headers=h).status_code == 429  # too soon
    assert client.post("/helper/jobs/claim", json={}, headers={"X-Device-Token": "x" * 43}).status_code == 401


def test_once_handed_to_a_follow_up_a_retry_never_narrates_it(client, started):  # review 10 #3
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _ask(started, dev["deviceId"])
    assert actions.await_diagnosis(started, a["id"]) is None  # attempt 1 gave up waiting
    _again(dev["token"])
    beat(client, dev["token"], ALLOW)
    _result(client, dev["token"], a["id"], output="exit code 1")
    assert actions.await_diagnosis(started, a["id"]) is None  # a retry sees the hand-off, not the result
    assert db.action(started, a["id"]).get().to_dict()["continuationTurnId"]
