"""Own home first: an empty start, the sample home switched on and off, moving and renaming devices."""

from nightlight_api import db
from test_real import FACTS, beat, enrolled


def _devices(uid):
    return {s.id: s.to_dict() for s in db.devices(uid).get()}


def test_empty_start_then_sample_on_and_off_keeps_real_devices(client, uid):
    assert client.post("/api/demo/start", json={"template": "empty"}).json()["devices"] == 0
    dev = enrolled(client)
    beat(client, dev["token"], FACTS)
    on = client.post("/api/demo/template", json={"template": "home-pi"}).json()
    assert on["devices"] == 6
    gen = db.user(uid).get().to_dict()["demoGeneration"]
    current = {k for k, d in _devices(uid).items() if d.get("realm") == "real" or d.get("demoGeneration") == gen}
    assert "pi-1" in current and dev["deviceId"] in current
    client.post("/api/demo/template", json={"template": "empty"})
    gen = db.user(uid).get().to_dict()["demoGeneration"]
    current = {k for k, d in _devices(uid).items() if d.get("realm") == "real" or d.get("demoGeneration") == gen}
    assert current == {dev["deviceId"]}  # the sample is gone, the real device stays
    assert client.post("/api/demo/template", json={"template": "nope"}).status_code == 422


def test_move_and_rename(client, started):
    dev = enrolled(client)
    assert client.post(f"/api/devices/{dev['deviceId']}/layout", json={"x": 220, "y": 360, "name": "Pi on ESXi"}) \
        .status_code == 200
    d = db.device(started, dev["deviceId"]).get().to_dict()
    assert (d["x"], d["y"], d["name"]) == (220, 360, "Pi on ESXi")
    assert client.post("/api/devices/pi-1/layout", json={"x": 520}).status_code == 200
    assert client.post("/api/devices/pi-1/layout", json={"name": "x"}).status_code == 422  # samples keep names
    assert client.post("/api/devices/nope-9/layout", json={"x": 1}).status_code == 404
    assert client.post("/api/devices/pi-1/layout", json={"x": -5}).status_code == 422
