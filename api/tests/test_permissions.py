"""App-managed permissions: only when the device chose it, only reported targets; the device applies them."""

from nightlight_api import db, real
from test_real import FACTS, beat, enrolled

APP = {**FACTS, "manage": "app"}
PERMS = {"diagnose": True, "logs": ["pi-grafana-1"], "restart_container": ["pi-grafana-1"],
         "restart_service": ["pihole-FTL.service"]}


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


def test_owner_switches_reach_an_app_managed_device(client, started):
    dev = enrolled(client)
    first = beat(client, dev["token"], APP).json()
    assert first["permissions"] == real.DEFAULT_PERMISSIONS and "deviceName" in first
    r = client.post(f"/api/devices/{dev['deviceId']}/permissions", json=PERMS)
    assert r.status_code == 200
    _again(dev["token"])
    assert beat(client, dev["token"], APP).json()["permissions"]["restart_service"] == ["pihole-FTL.service"]
    assert any(e.to_dict()["kind"] == "permissions" for e in db.events(started).get())


def test_strict_or_old_devices_refuse_and_only_reported_targets(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], {**FACTS, "manage": "strict"})
    r = client.post(f"/api/devices/{dev['deviceId']}/permissions", json=PERMS)
    assert r.status_code == 409 and r.json()["code"] == "strict_device"
    old = enrolled(client)
    beat(client, old["token"], FACTS)
    assert client.post(f"/api/devices/{old['deviceId']}/permissions", json=PERMS).json()["code"] == "update_helper"
    app = enrolled(client)
    beat(client, app["token"], APP)
    bad = {**PERMS, "restart_container": ["not-there"]}
    r = client.post(f"/api/devices/{app['deviceId']}/permissions", json=bad)
    assert r.status_code == 422
    assert client.post(f"/api/devices/{app['deviceId']}/permissions",
                       json={**PERMS, "restart_container": ["bad name;"]}).status_code == 422
