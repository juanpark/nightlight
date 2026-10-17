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


def _deliver(client, dev):
    _again(dev["token"])
    return beat(client, dev["token"], ALLOW).json()["jobs"]


def test_reset_withdraws_jobs_not_yet_on_the_device(client, started):  # review 6 #1
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _propose(started, dev["deviceId"])
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    assert client.post("/api/demo/reset", json={}).status_code == 200
    assert _action(started, a["id"])["status"] == "stale"
    assert _deliver(client, dev) == []


def test_result_after_reset_is_recorded_without_a_dead_follow_up(client, started):  # review 6 #1
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _propose(started, dev["deviceId"])
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    assert len(_deliver(client, dev)) == 1
    client.post("/api/demo/reset", json={})
    assert _action(started, a["id"])["status"] == "running"  # already on the device: left alone
    r = client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": "Started.", "state": "running"},
                    headers={"X-Device-Token": dev["token"]})
    done = _action(started, a["id"])
    assert r.status_code == 200 and done["status"] == "done" and done["followUp"] == "skipped_after_reset"
    assert "continuationTurnId" not in done


def test_no_jobs_handed_out_or_follow_ups_written_while_resetting(client, started):  # review 6 #1
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _propose(started, dev["deviceId"])
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    db.user(started).update({"demo.state": "resetting"})
    assert _deliver(client, dev) == []
    db.user(started).update({"demo.state": "ready"})
    assert len(_deliver(client, dev)) == 1
    db.user(started).update({"demo.state": "resetting"})
    client.post(f"/helper/jobs/{a['id']}/result", json={"ok": False, "summary": "no"},
                headers={"X-Device-Token": dev["token"]})
    assert _action(started, a["id"])["followUp"] == "skipped_after_reset"


def test_existing_proposal_is_recovered_even_when_the_device_went_quiet(client, started):  # review 6 #2
    from datetime import datetime, timedelta, timezone
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _propose(started, dev["deviceId"], turn="turn_rec")
    db.device(started, dev["deviceId"]).update({"lastSeen": datetime.now(timezone.utc) - timedelta(minutes=10)})
    assert _propose(started, dev["deviceId"], turn="turn_rec")["id"] == a["id"]
    with pytest.raises(ValueError, match="device_not_reporting"):
        _propose(started, dev["deviceId"], turn="turn_new")


def test_result_state_is_a_known_word_and_summary_is_scrubbed(client, started):  # review 6 #3
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _propose(started, dev["deviceId"])
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    _deliver(client, dev)
    h = {"X-Device-Token": dev["token"]}
    bad = client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": "x", "state": "password=hunter2"},
                      headers=h)
    assert bad.status_code == 422
    fake = "token=" + "abcd1234efgh5678"  # a made-up value, split so secret scanners don't flag the test
    client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": f"{fake} ok", "state": "running"},
                headers=h)
    done = _action(started, a["id"])
    assert "abcd1234efgh5678" not in done["result"]["summary"] and done["result"]["after"]["state"] == "running"


def test_restart_a_failed_service_only_when_allowed(client, started):  # slice 14
    dev = enrolled(client)
    facts = {**FACTS, "allowedJobs": {"restart_service": ["pihole-FTL.service"]}}
    beat(client, dev["token"], facts)
    a = actions.propose(started, session_id="sess_test", turn_id="t_svc", generation=generation(started),
                        action_type="restart_service", device_id=dev["deviceId"], params={"unit": "pihole-FTL.service"})
    assert a["status"] == "pending" and "sudo systemctl restart pihole-FTL.service" in a["dryRun"]
    with pytest.raises(ValueError, match="not_allowed_on_device"):
        actions.propose(started, session_id="sess_test", turn_id="t_svc2", generation=generation(started),
                        action_type="restart_service", device_id=dev["deviceId"], params={"unit": "ssh.service"})
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    _again(dev["token"])
    jobs = beat(client, dev["token"], facts).json()["jobs"]
    assert jobs[0]["type"] == "restart_service" and jobs[0]["params"] == {"unit": "pihole-FTL.service"}



def test_restart_needs_the_exact_failed_unit(client, started):  # review 14 #1
    dev = enrolled(client)
    facts = {**FACTS, "failedUnits": ["demo:app.service"], "allowedJobs": {"restart_service": ["demo_app.service"]}}
    beat(client, dev["token"], facts)
    with pytest.raises(ValueError, match="not_failed"):
        actions.propose(started, session_id="sess_test", turn_id="t_x", generation=generation(started),
                        action_type="restart_service", device_id=dev["deviceId"], params={"unit": "demo_app.service"})


def test_a_restarted_service_gets_no_new_card_until_it_fails_again(client, started):  # review 14 rev2
    dev = enrolled(client)
    facts = {**FACTS, "allowedJobs": {"restart_service": ["pihole-FTL.service"]}}
    beat(client, dev["token"], facts)
    a = actions.propose(started, session_id="sess_test", turn_id="t_r1", generation=generation(started),
                        action_type="restart_service", device_id=dev["deviceId"], params={"unit": "pihole-FTL.service"})
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    _again(dev["token"])
    beat(client, dev["token"], facts)
    client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": "ok", "state": "running"},
                headers={"X-Device-Token": dev["token"]})
    with pytest.raises(ValueError, match="not_failed"):
        actions.propose(started, session_id="sess_test", turn_id="t_r2", generation=generation(started),
                        action_type="restart_service", device_id=dev["deviceId"], params={"unit": "pihole-FTL.service"})


def test_a_report_only_heartbeat_never_takes_jobs(client, started):
    from nightlight_api import actions, db
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = actions.propose(started, session_id="sess_test", turn_id="tj", generation=generation(started),
                        action_type="restart_container", device_id=dev["deviceId"], params={"container": "pi-grafana-1"})
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    _again(dev["token"])
    r = client.post("/helper/heartbeat?jobs=0", json=ALLOW, headers={"X-Device-Token": dev["token"]})
    assert r.status_code == 200 and r.json()["jobs"] == []
    assert db.action(started, a["id"]).get().to_dict()["status"] == "approved"  # still waiting for the service


def test_the_work_channel_answers_as_soon_as_a_job_is_approved(client, started):
    import threading
    import time
    from nightlight_api import actions, db
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = actions.propose(started, session_id="sess_test", turn_id="tw", generation=generation(started),
                        action_type="restart_container", device_id=dev["deviceId"], params={"container": "pi-grafana-1"})
    threading.Timer(1.0, lambda: client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})).start()
    t = time.monotonic()
    r = client.post("/helper/jobs/wait", json={}, headers={"X-Device-Token": dev["token"]})
    assert r.status_code == 200 and [j["id"] for j in r.json()["jobs"]] == [a["id"]]
    assert time.monotonic() - t < 10  # woke on the approval, not at the end of the hold
    assert db.action(started, a["id"]).get().to_dict()["status"] == "running"


def test_the_work_channel_comes_back_empty_after_its_hold(client, started, monkeypatch):
    from nightlight_api import real
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    monkeypatch.setattr(real, "WAIT_SECONDS", 1)
    assert real.wait_for_jobs(dev["token"], hold=1)["jobs"] == []


def test_one_open_wait_per_device_and_the_hold_follows_the_report(client, started):
    import threading
    import time
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    first = threading.Thread(target=lambda: client.post("/helper/jobs/wait?hold=3", json={},
                                                        headers={"X-Device-Token": dev["token"]}))
    first.start()
    time.sleep(1)
    second = client.post("/helper/jobs/wait?hold=3", json={}, headers={"X-Device-Token": dev["token"]})
    assert second.status_code == 429 and second.json()["code"] == "already_waiting"
    first.join()
    t = time.monotonic()
    r = client.post("/helper/jobs/wait?hold=2", json={}, headers={"X-Device-Token": dev["token"]})
    assert r.status_code == 200 and r.json()["jobs"] == [] and time.monotonic() - t < 6


def test_a_late_wait_never_clears_its_successors_lease(client, started, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from nightlight_api import db, real
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    tref = db.client().collection("helperTokens").document(real._sha(dev["token"]))

    def slow_wait(token, t, hold):  # while A is still finishing, its lease expires and B takes over
        tref.update({"waitUntil": datetime.now(timezone.utc) + timedelta(seconds=30), "waitOwner": "wait_B"})
        return {"ok": True, "jobs": []}
    monkeypatch.setattr(real, "_wait", slow_wait)
    real.wait_for_jobs(dev["token"], hold=1)
    assert tref.get().to_dict()["waitOwner"] == "wait_B"  # A didn't clear B's lease


def test_a_running_but_unhealthy_container_is_flagged_and_can_be_restarted(client, started):
    dev = enrolled(client)
    sick = {**FACTS, "allowedJobs": {"restart_container": ["photos", "web"]},
            "containers": [{"name": "photos", "image": "ghcr.io/immich-app/immich-server:v1", "state": "running",
                            "status": "Up 3 days (unhealthy)"},
                           {"name": "web", "image": "nginx:1", "state": "running", "status": "Up 2 days"}]}
    beat(client, dev["token"], sick)  # an older helper: it would answer "already running"
    svc = db.services(started, dev["deviceId"]).document(real._doc_id("photos")).get().to_dict()
    finding = next(f for f in db.device(started, dev["deviceId"]).get().to_dict()["findings"]
                   if f["check"] == "container_unhealthy")
    assert svc["status"] == "warn" and finding["svcId"] == real._doc_id("photos")
    restart = dict(session_id="sess_test", generation=generation(started), action_type="restart_container",
                   device_id=dev["deviceId"], params={"container": "photos", "restart": True})
    with pytest.raises(ValueError, match="helper_too_old"):
        actions.propose(started, turn_id="t_old", **restart)
    _again(dev["token"])
    beat(client, dev["token"], {**sick, "helperVersion": real.UNHEALTHY_RESTART_FROM})
    with pytest.raises(ValueError, match="needs_restart"):  # a start card can't be made for it
        _propose(started, dev["deviceId"], "photos", turn="turn_start")
    card = actions.propose(started, turn_id="turn_sick", **restart)
    assert card["status"] == "pending" and "docker restart photos" in card["dryRun"]
    with pytest.raises(ValueError, match="not_unhealthy"):  # and a restart only for an unhealthy one
        actions.propose(started, turn_id="t_r", **{**restart, "params": {"container": "web", "restart": True}})


def test_only_a_running_result_marks_a_service_recovered(client, started):  # Codex real/passkey rev2 #1
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = _propose(started, dev["deviceId"])
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    _again(dev["token"])
    beat(client, dev["token"], ALLOW)
    client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": "It is exited.", "state": "exited"},
                headers={"X-Device-Token": dev["token"]})
    assert db.services(started, dev["deviceId"]).document("pi-grafana-1").get().to_dict()["status"] == "warn"


SICK = {**FACTS, "helperVersion": real.UNHEALTHY_RESTART_FROM, "allowedJobs": {"restart_container": ["photos"]},
        "containers": [{"name": "photos", "image": "ghcr.io/immich-app/immich-server:v1", "state": "running",
                        "status": "Up 3 days (unhealthy)"}]}


def test_declining_a_real_restart_says_nothing_changed_and_what_the_device_reported(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], SICK)
    sid = client.post("/api/chat/sessions", json={}).json()["sessionId"]
    a = actions.propose(started, session_id=sid, turn_id="turn_sick", generation=generation(started),
                        action_type="restart_container", device_id=dev["deviceId"],
                        params={"container": "photos", "restart": True})
    cont = client.post(f"/api/actions/{a['id']}/decide", json={"decision": "deny"}).json()["continuationTurnId"]
    text = db.turns(started, sid).document(cont).get().to_dict()["input"]
    assert "nothing was changed" in text and "no job ran" in text and a["plan"] in text
    assert 'Last known state of photos: needs a look (the device reported: "Up 3 days (unhealthy)")' in text
    assert "stopped" not in text  # the label "Restart a stopped container" no longer frames a running one


def _handed_over(client, started, sid="sess_test"):
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = actions.propose(started, session_id=sid, turn_id="turn_lost", generation=generation(started),
                        action_type="restart_container", device_id=dev["deviceId"],
                        params={"container": "pi-grafana-1"})
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    assert len(_deliver(client, dev)) == 1 and _action(started, a["id"])["status"] == "running"
    return dev, a


def _claimed_ago(uid, aid, minutes):
    from datetime import datetime, timedelta, timezone
    db.action(uid, aid).update({"claimedAt": datetime.now(timezone.utc) - timedelta(minutes=minutes)})


def test_a_job_the_device_never_reports_ends_as_failed_with_a_plain_follow_up(client, started):
    dev, a = _handed_over(client, started)
    assert actions.expire_device_jobs(started, dev["deviceId"]) == 0  # still within its time
    _claimed_ago(started, a["id"], 9)
    assert actions.expire_device_jobs(started, dev["deviceId"]) == 0
    _claimed_ago(started, a["id"], 11)
    assert actions.expire_device_jobs(started, dev["deviceId"]) == 1
    done = _action(started, a["id"])
    assert done["status"] == "failed" and done["result"]["summary"] == actions.NO_REPORT
    turn = db.turns(started, "sess_test").document(done["continuationTurnId"]).get().to_dict()
    assert turn["status"] == "queued" and "didn't report back" in turn["input"]
    assert actions.expire_device_jobs(started, dev["deviceId"]) == 0  # once
    late = client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": "Started.", "state": "running"},
                       headers={"X-Device-Token": dev["token"]})
    assert late.status_code == 200 and _action(started, a["id"])["status"] == "failed"  # the first ending stands


def test_the_scheduled_sweep_ends_jobs_that_never_reported(client, started, monkeypatch):
    from nightlight_api import archive, watch
    dev, a = _handed_over(client, started)
    _claimed_ago(started, a["id"], 11)
    only = db.client().collection(f"sweepTest_{started}")  # just this device, not every test's on the emulator
    only.document("d").set({"uid": started, "deviceId": dev["deviceId"]})
    monkeypatch.setattr(watch, "registry", lambda: only)
    monkeypatch.setattr(watch, "watch_registry", lambda: db.client().collection(f"sweepTestWatches_{started}"))
    monkeypatch.setattr(watch, "_reconcile_count", lambda: None)
    monkeypatch.setattr(archive, "purge_due", lambda: 0)
    assert watch.sweep()["jobsWithoutReport"] == 1 and _action(started, a["id"])["status"] == "failed"


def test_a_read_times_out_sooner_and_after_a_reset_writes_no_follow_up(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], {**FACTS, "allowedJobs": {"diagnose": ["pi-grafana-1"]}})
    a = actions.request_diagnosis(started, session_id="sess_test", turn_id="turn_read", generation=generation(started),
                                  device_id=dev["deviceId"], target="pi-grafana-1")
    _again(dev["token"])
    beat(client, dev["token"], {**FACTS, "allowedJobs": {"diagnose": ["pi-grafana-1"]}})
    actions.await_diagnosis(started, a["id"])  # the asking turn stopped waiting: a follow-up is wanted
    _claimed_ago(started, a["id"], 4)
    client.post("/api/demo/reset", json={})
    assert actions.expire_unreported(started, a["id"]) is True
    done = _action(started, a["id"])
    assert done["status"] == "failed" and done["followUp"] == "skipped_after_reset" and "continuationTurnId" not in done


def test_the_waiting_follow_up_finishes_instead_of_hanging(client, started, monkeypatch):
    from fake_llm import FakeLlm
    from nightlight_api import agent as agentlib
    real_build = agentlib.build
    monkeypatch.setattr(agentlib, "COUNTER", lambda req: 100)  # exact count, faked (as in test_chat)
    monkeypatch.setattr(agentlib, "build", lambda ctx, continuation, model=None:
                        real_build(ctx, continuation=continuation, model=FakeLlm()))
    FakeLlm.behavior = None
    sid = client.post("/api/chat/sessions", json={}).json()["sessionId"]
    dev, a = _handed_over(client, started, sid)
    cont = f"cont_{a['id']}"
    assert client.post(f"/api/turns/{cont}/stream", json={}).status_code == 404  # not yet: the device may still answer
    _claimed_ago(started, a["id"], 11)
    r = client.post(f"/api/turns/{cont}/stream", json={})  # the browser asks again: the job ends and this answers
    assert r.status_code == 200 and '"type": "done"' in r.text
    assert _action(started, a["id"])["status"] == "failed"
