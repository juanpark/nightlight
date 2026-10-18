"""Real devices: one-time enrol codes, device tokens, heartbeats, isolation and reset safety."""

from datetime import datetime, timedelta, timezone

import pytest

from nightlight_api import agent as agentlib, actions, db, demo, real
from nightlight_api.errors import ApiError
from conftest import generation

FACTS = {"helperVersion": "0.1.0", "os": "Debian GNU/Linux 11 (bullseye)", "arch": "aarch64", "cpuPct": 4.0,
         "memPct": 12.0, "diskPct": 14.0, "uptimeSec": 36 * 7 * 86400,
         "containers": [{"name": "pi-teslamate-1", "image": "teslamate/teslamate:4.0.1", "state": "running",
                         "status": "Up 2 months"},
                        {"name": "pi-grafana-1", "image": "teslamate/grafana:4.0.1", "state": "exited",
                         "status": "Exited (1) 3 hours ago"}],
         "failedUnits": ["pihole-FTL.service"], "updatesPending": 89}


def enrolled(client, name="My Pi"):
    code = client.post("/api/devices/enrol-code", json={}).json()["code"]
    r = client.post("/helper/enrol", json={"code": code, "name": name})
    assert r.status_code == 201
    return r.json()


def beat(client, token, facts=FACTS):
    return client.post("/helper/heartbeat", json=facts, headers={"X-Device-Token": token})


def test_enrol_then_heartbeat_creates_a_real_device(client, started):
    dev = enrolled(client)
    r = beat(client, dev["token"])
    assert r.status_code == 200 and r.json()["findings"] >= 4
    d = db.device(started, dev["deviceId"]).get().to_dict()
    assert d["realm"] == "real" and d["simulated"] is False and d["status"] == "warn"
    checks = {f["check"] for f in d["findings"]}
    assert {"service_down", "container_down", "updates_pending", "restart_overdue"} <= checks
    assert any("Pi-hole ad blocker has stopped" in f["message"] for f in d["findings"])
    svcs = {s.id for s in db.services(started, dev["deviceId"]).get()}
    assert {"pi-teslamate-1", "pi-grafana-1", "pihole-FTL.service"} <= svcs
    stored = db.client().collection("helperTokens").document(real._sha(dev["token"])).get()
    assert stored.exists and dev["token"] not in str(stored.to_dict())  # only the hash is stored


def test_code_is_single_use_and_expires(client, started):
    code = client.post("/api/devices/enrol-code", json={}).json()["code"]
    assert client.post("/helper/enrol", json={"code": code, "name": "a"}).status_code == 201
    r = client.post("/helper/enrol", json={"code": code, "name": "b"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_code"
    code2 = client.post("/api/devices/enrol-code", json={}).json()["code"]
    db.client().collection("enrolCodes").document(real._sha(code2.replace("-", ""))).update(
        {"expiresAt": datetime.now(timezone.utc) - timedelta(seconds=1)})
    assert client.post("/helper/enrol", json={"code": code2, "name": "c"}).status_code == 401


def test_unknown_or_revoked_token_cannot_write(client, started):
    assert beat(client, "x" * 43).status_code == 401
    dev = enrolled(client)
    assert client.post(f"/api/devices/{dev['deviceId']}/revoke", json={}).status_code == 200
    assert beat(client, dev["token"]).status_code == 401


def test_heartbeats_are_rate_limited_and_strict(client, started):
    dev = enrolled(client)
    assert beat(client, dev["token"]).status_code == 200
    assert beat(client, dev["token"]).status_code == 429
    r = beat(client, dev["token"], {**FACTS, "hostname": "secret-box"})
    assert r.status_code == 422  # anything outside the allowlist is rejected


def test_device_token_cant_be_used_as_a_user_token(client, started, monkeypatch):
    from nightlight_api.main import app
    from nightlight_api.auth import current_uid
    from fastapi.testclient import TestClient
    dev = enrolled(client)
    app.dependency_overrides.pop(current_uid, None)
    r = TestClient(app).post("/api/demo/reset", json={}, headers={"Authorization": f"Bearer {dev['token']}"})
    assert r.status_code == 401


def test_other_users_cannot_revoke(client, started):
    dev = enrolled(client)
    demo.start("someone_else_r")
    with pytest.raises(ApiError) as e:
        real.revoke("someone_else_r", dev["deviceId"])
    assert e.value.status == 404


def test_reset_leaves_real_devices_alone(client, started):
    dev = enrolled(client)
    beat(client, dev["token"])
    demo.reset(started)
    assert db.device(started, dev["deviceId"]).get().exists
    assert len(list(db.services(started, dev["deviceId"]).get())) == 3


def test_agent_sees_real_devices_but_cannot_act_on_them(client, started):
    dev = enrolled(client)
    beat(client, dev["token"])
    summary = agentlib.fleet_summary(started, generation(started))
    assert dev["deviceId"] in summary and "REAL device" in summary and "Pi-hole" in summary
    with pytest.raises(ValueError):
        actions.propose(started, session_id="sess_test", turn_id="turn_r", generation=generation(started),
                        action_type="rotate_logs", device_id=dev["deviceId"], params={})


def test_enrol_codes_are_rate_limited(client, started):
    for _ in range(real.CODES_PER_HOUR):
        assert client.post("/api/devices/enrol-code", json={}).status_code == 201
    assert client.post("/api/devices/enrol-code", json={}).status_code == 429


# ---------------------------------------------------------------- slice-5 review regressions

def test_demo_incidents_cannot_touch_real_devices(client, started):  # H1
    dev = enrolled(client)
    facts = {**FACTS, "containers": [{"name": "minecraft", "image": "mc:1", "state": "running", "status": "Up"}]}
    beat(client, dev["token"], facts)
    before = db.device(started, dev["deviceId"]).get().to_dict()
    events_before = len(list(db.events(started).get()))
    for kind in ("logs_locked", "server_lagging", "disk_full", "update_available"):
        r = client.post("/api/demo/inject", json={"kind": kind, "deviceId": dev["deviceId"]})
        assert r.status_code == 422 and r.json()["code"] == "invalid_body"
    assert db.device(started, dev["deviceId"]).get().to_dict() == before
    assert len(list(db.events(started).get())) == events_before


def test_silent_real_device_shows_offline(client, started):  # M3
    dev = enrolled(client)
    beat(client, dev["token"])
    db.device(started, dev["deviceId"]).update({"lastSeen": datetime.now(timezone.utc) - timedelta(days=2)})
    summary = agentlib.fleet_summary(started, generation(started))
    assert "NOT REPORTING" in summary
    line = next(line for line in summary.splitlines() if dev["deviceId"] in line)
    # an offline device lists no stale problems (its apps list may still name Pi-hole: that's inventory, not health)
    assert "Health: offline" in line and "Pi-hole" not in line.split(" Apps: ")[0]
    db.client().collection("helperTokens").document(real._sha(dev["token"])).update({"lastSeen": None})
    beat(client, dev["token"])  # a fresh report brings it back
    assert "NOT REPORTING" not in agentlib.fleet_summary(started, generation(started))


def test_revoke_racing_heartbeats_ends_revoked_and_offline(client, started):  # M4
    import threading
    dev = enrolled(client)
    results = []

    def heartbeat():
        try:
            results.append(real.heartbeat(dev["token"], FACTS)["ok"])
        except ApiError as e:
            results.append(e.code)

    t = threading.Thread(target=heartbeat)
    t.start()
    real.revoke(started, dev["deviceId"])
    t.join()
    d = db.device(started, dev["deviceId"]).get().to_dict()
    tok = db.client().collection("helperTokens").document(real._sha(dev["token"])).get().to_dict()
    assert tok["revoked"] is True and d["revoked"] is True
    assert real.view(d)["status"] == "offline" and real.view(d)["staleReason"] == "revoked"
    with pytest.raises(ApiError):
        real.heartbeat(dev["token"], FACTS)
