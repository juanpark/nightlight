"""Jobs on real devices: owner allowlist on the device, approval, at-most-once delivery, result from that device only."""

import pytest

from nightlight_api import actions, db, real
from conftest import generation
from test_real import FACTS, beat, enrolled

ALLOW = {**FACTS, "allowedJobs": {"restart_container": ["pi-grafana-1"]}}


def _again(token):
    """Let the next heartbeat through the 20-second limit."""
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


def _propose(uid, device_id, container="pi-grafana-1", turn="turn_j"):
    return actions.propose(uid, session_id="sess_test", turn_id=turn, generation=generation(uid),
                           action_type="restart_container", device_id=device_id, params={"container": container})


def _action(uid, aid):
    return db.action(uid, aid).get().to_dict()


def test_approved_job_is_delivered_once_and_reported_by_its_device(client, started):
    dev = enrolled(client)
    assert beat(client, dev["token"], ALLOW).json()["jobs"] == []
    a = _propose(started, dev["deviceId"])
    assert a["status"] == "pending" and a["realm"] == "real" and "docker start pi-grafana-1" in a["dryRun"]
    _again(dev["token"])
    assert beat(client, dev["token"], ALLOW).json()["jobs"] == []  # not approved yet: nothing handed over
    r = client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 202 and r.json()["status"] == "approved"
    _again(dev["token"])
    jobs = beat(client, dev["token"], ALLOW).json()["jobs"]
    assert jobs == [{"id": a["id"], "type": "restart_container", "params": {"container": "pi-grafana-1"}}]
    assert _action(started, a["id"])["status"] == "running"
    _again(dev["token"])
    assert beat(client, dev["token"], ALLOW).json()["jobs"] == []  # at most once
    res = client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": "Started pi-grafana-1.",
                                                              "state": "running"},
                      headers={"X-Device-Token": dev["token"]})
    assert res.status_code == 200 and res.json()["status"] == "done"
    done = _action(started, a["id"])
    assert done["result"]["ok"] is True and done["continuationTurnId"]
    turn = db.turns(started, "sess_test").document(done["continuationTurnId"]).get().to_dict()
    assert turn["status"] == "queued" and "Restart a stopped container" in turn["input"]
    assert db.services(started, dev["deviceId"]).document("pi-grafana-1").get().to_dict()["status"] == "ok"
    again = client.post(f"/helper/jobs/{a['id']}/result", json={"ok": False, "summary": "x"},
                        headers={"X-Device-Token": dev["token"]})
    assert again.status_code == 200 and _action(started, a["id"])["status"] == "done"  # first report stands


def test_only_allowed_stopped_containers_on_real_devices(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    for container, reason in (("pi-teslamate-1", "not_allowed_on_device"), ("nope", "not_allowed_on_device"),
                              ("-rm", "bad_target")):
        with pytest.raises(ValueError, match=reason):
            _propose(started, dev["deviceId"], container, turn=f"turn_{reason}")
    running = {**ALLOW, "allowedJobs": {"restart_container": ["pi-teslamate-1"]}}
    _again(dev["token"])
    beat(client, dev["token"], running)
    with pytest.raises(ValueError, match="already_running"):
        _propose(started, dev["deviceId"], "pi-teslamate-1")
    with pytest.raises(ValueError):  # simulated jobs never target real devices, and real jobs never simulated ones
        actions.propose(started, session_id="sess_test", turn_id="t1", generation=generation(started),
                        action_type="rotate_logs", device_id=dev["deviceId"], params={})
    with pytest.raises(ValueError):
        actions.propose(started, session_id="sess_test", turn_id="t2", generation=generation(started),
                        action_type="restart_container", device_id="pi-1", params={"container": "x"})


def test_only_the_device_that_got_the_job_can_report_it(client, started):
    dev, other = enrolled(client), enrolled(client, "Other")
    beat(client, dev["token"], ALLOW)
    a = _propose(started, dev["deviceId"])
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    body = {"ok": True, "summary": "done"}
    assert client.post(f"/helper/jobs/{a['id']}/result", json=body,
                       headers={"X-Device-Token": dev["token"]}).status_code == 409  # not handed over yet
    _again(dev["token"])
    beat(client, dev["token"], ALLOW)
    assert client.post(f"/helper/jobs/{a['id']}/result", json=body,
                       headers={"X-Device-Token": other["token"]}).status_code == 404
    assert client.post(f"/helper/jobs/{a['id']}/result", json=body,
                       headers={"X-Device-Token": "x" * 43}).status_code == 401
    assert _action(started, a["id"])["status"] == "running"


def test_declined_job_is_never_delivered(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _propose(started, dev["deviceId"])
    r = client.post(f"/api/actions/{a['id']}/decide", json={"decision": "deny"})
    assert r.status_code == 202 and r.json()["status"] == "denied" and r.json()["continuationTurnId"]
    _again(dev["token"])
    assert beat(client, dev["token"], ALLOW).json()["jobs"] == []


def test_silent_device_gets_no_new_jobs(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    from datetime import datetime, timedelta, timezone
    db.device(started, dev["deviceId"]).update({"lastSeen": datetime.now(timezone.utc) - timedelta(minutes=10)})
    with pytest.raises(ValueError, match="device_not_reporting"):
        _propose(started, dev["deviceId"])


@pytest.mark.parametrize("allowed", [{"delete_everything": ["a"]}, {"restart_container": ["bad name"]},
                                     {"restart_container": [f"c{i}" for i in range(21)]}])
def test_allowlist_in_reports_is_strict(client, started, allowed):
    dev = enrolled(client)
    assert beat(client, dev["token"], {**FACTS, "allowedJobs": allowed}).status_code == 422


def test_every_action_tool_raises_an_approval_card_event():
    from nightlight_api import agent as agentlib, turns
    ctx = agentlib.TurnContext.__new__(agentlib.TurnContext)
    names = {t.__name__ for t in agentlib.make_tools(ctx, read_only=False)}
    read = {t.__name__ for t in agentlib.make_tools(ctx, read_only=True)}
    assert names - read == turns.ACTION_TOOLS
