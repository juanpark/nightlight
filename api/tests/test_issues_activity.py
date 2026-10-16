"""Known/snoozed problems, real-device activity, tags."""

from datetime import datetime, timedelta, timezone

from nightlight_api import agent as agentlib, db, real
from conftest import generation
from test_real import FACTS, beat, enrolled

ONE_PROBLEM = {**FACTS, "containers": [], "updatesPending": 0, "uptimeSec": 100, "failedUnits": ["pihole-FTL.service"]}


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


def _events(uid):
    return [e.to_dict() for e in db.events(uid).get() if e.to_dict().get("realm") == "real"]


def _dev(uid, dev):
    return db.device(uid, dev["deviceId"]).get().to_dict()


def test_known_problem_stops_lighting_orange_until_it_gets_worse(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], ONE_PROBLEM)
    assert _dev(started, dev)["status"] == "warn"
    fid = real._finding_id("f_unit_", "pihole-FTL.service")
    r = client.post(f"/api/devices/{dev['deviceId']}/issues/{fid}", json={"state": "known"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    _again(dev["token"])
    beat(client, dev["token"], ONE_PROBLEM)
    d = _dev(started, dev)
    assert d["status"] == "ok" and d["findings"][0]["state"] == "known"
    _again(dev["token"])
    beat(client, dev["token"], {**ONE_PROBLEM, "diskPct": 95.0})  # a new, worse problem still lights up
    assert _dev(started, dev)["status"] == "crit"
    summary = agentlib.fleet_summary(started, generation(started))
    assert "1 known problem" in summary


def test_snooze_runs_out(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], ONE_PROBLEM)
    fid = real._finding_id("f_unit_", "pihole-FTL.service")
    assert client.post(f"/api/devices/{dev['deviceId']}/issues/{fid}", json={"state": "snoozed"}).status_code == 422
    client.post(f"/api/devices/{dev['deviceId']}/issues/{fid}", json={"state": "snoozed", "days": 3})
    states = _dev(started, dev)["issueStates"]
    states[fid]["until"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.device(started, dev["deviceId"]).update({"issueStates": states})
    _again(dev["token"])
    beat(client, dev["token"], ONE_PROBLEM)
    assert _dev(started, dev)["status"] == "warn"


def test_activity_records_real_devices_and_survives_reset(client, started):
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], ONE_PROBLEM)
    kinds = [e["kind"] for e in _events(started)]
    assert "joined" in kinds and "status_warn" in kinds
    client.post("/api/demo/reset", json={})
    assert {"joined", "status_warn"} <= {e["kind"] for e in _events(started)}
    client.post("/helper/leave", json={}, headers={"X-Device-Token": dev["token"]})
    assert "left" in {e["kind"] for e in _events(started)}


def test_tags_are_saved_cleaned_and_shown_to_the_agent(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], ONE_PROBLEM)
    r = client.post(f"/api/devices/{dev['deviceId']}/layout", json={"tags": ["Parents", " Parents ", "Home"]})
    assert r.status_code == 200 and _dev(started, dev)["tags"] == ["Home", "Parents"]
    assert client.post(f"/api/devices/{dev['deviceId']}/layout", json={"tags": ["x" * 21]}).status_code == 422
    assert client.post(f"/api/devices/{dev['deviceId']}/layout", json={"tags": list("abcdefg")}).status_code == 422
    assert "Tags: Home, Parents" in agentlib.fleet_summary(started, generation(started))


def test_tags_checked_after_hiding_secrets_and_odd_unit_names_can_be_acknowledged(client, started):  # review 10b
    dev = enrolled(client)
    weird = {**ONE_PROBLEM, "failedUnits": ["demo\\x2dapp.service"]}
    beat(client, dev["token"], weird)
    fid = _dev(started, dev)["findings"][0]["id"]
    assert client.post(f"/api/devices/{dev['deviceId']}/issues/{fid}", json={"state": "known"}).status_code == 200
    r = client.post(f"/api/devices/{dev['deviceId']}/layout", json={"tags": ["account_secret=123"]})
    assert r.status_code == 422


def test_similar_names_never_share_an_acknowledgement(client, started):  # review 10b rev2
    dev = enrolled(client)
    beat(client, dev["token"], {**ONE_PROBLEM, "failedUnits": ["demo\\x2dapp.service"]})
    fid = _dev(started, dev)["findings"][0]["id"]
    client.post(f"/api/devices/{dev['deviceId']}/issues/{fid}", json={"state": "known"})
    _again(dev["token"])
    beat(client, dev["token"], {**ONE_PROBLEM, "failedUnits": ["demo_x2dapp.service"]})
    d = _dev(started, dev)
    assert d["findings"][0]["state"] == "new" and d["status"] == "warn"


def test_safety_and_mac_checks_in_plain_words(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], {**ONE_PROBLEM, "failedUnits": [], "failedAgents": ["org.example.sync"],
                                "safety": {"passwordlessSudo": True, "sshPasswordLogin": True}})
    checks = {f["check"]: f for f in _dev(started, dev)["findings"]}
    assert "take full control without a password" in checks["passwordless_admin"]["message"]
    assert checks["ssh_password_login"]["severity"] == "info" and "background_items_failing" in checks
    assert client.post("/helper/heartbeat", json={**FACTS, "safety": {"rootkit": True}},
                       headers={"X-Device-Token": dev["token"]}).status_code == 422
