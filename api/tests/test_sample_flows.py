"""The sample home's simulated flows: look nearby, add a device (simulated install), and the live-machine guard."""

import pytest

from nightlight_api import agent as agentlib, db, demo, live
from nightlight_api.config import settings
from conftest import generation


def test_look_nearby_in_the_sample_home(client, started):
    r = client.post("/api/discover", json={})
    assert r.status_code == 202
    body = r.json()
    assert body["simulated"] is True
    assert body["asked"][0] == {"deviceId": "pi-1", "name": "Raspberry Pi", "simulated": True}
    items = client.get("/api/found").json()["items"]
    assert all(i.get("simulated") for i in items) and len(items) == 6
    assert items[0]["router"] is True and items[0]["guess"] == "Your router (internet connection)"
    private = [i for i in items if i.get("privateAddress")]
    assert len(private) == 1 and private[0]["guess"] == "Phone or laptop" and not private[0]["seenBy"][0]["canWatch"]
    printer = next(i for i in items if i["guess"] == "Printer")
    assert printer["seenBy"][0] == {"deviceId": "pi-1", "name": "Raspberry Pi", "cid": "5a3e00000002",
                                    "canWatch": True}
    # watch the printer: it lands on the map, answering, watched by the Pi
    r = client.post("/api/discoveries/pi-1/5a3e00000002/add", json={"name": "Brother HL-L2350DW"})
    assert r.status_code == 201, r.text
    d = db.device(started, r.json()["deviceId"]).get().to_dict()
    assert d["kind"] == "watched" and d["status"] == "ok" and d["watchedBy"] == "pi-1" and d["simulated"]
    assert d["role"] == "printer" and d["demoGeneration"] == generation(started)
    assert "Brother HL-L2350DW" in agentlib.fleet_summary(started, generation(started))
    assert client.post("/api/discoveries/pi-1/5a3e00000002/add", json={}).status_code == 409
    assert client.post("/api/discoveries/pi-1/5a3e00000004/add", json={}).status_code == 422  # console: no port
    # the router fills in the one already on the map
    r = client.post("/api/discoveries/pi-1/5a3e00000001/add", json={"name": "Router"})
    assert r.json()["deviceId"] == "router-1"
    assert db.device(started, "router-1").get().to_dict()["model"] == "RT-AX58U"
    # looking again keeps what was added; a reset clears it all
    client.post("/api/discover", json={})
    assert {i["guess"] for i in client.get("/api/found").json()["items"]} >= {"Speaker or TV"}
    assert not any(i["guess"] == "Printer" for i in client.get("/api/found").json()["items"])
    demo.reset(started)
    assert not db.device(started, d and "found-0002").get().exists
    assert client.get("/api/found").json()["items"] == []


def test_no_sample_look_without_the_sample_home(client, uid):
    demo.start(uid, "empty")
    body = client.post("/api/discover", json={}).json()
    assert body["simulated"] is False and body["asked"] == []


@pytest.mark.parametrize("os_name,device_id", [("linux", "laptop-1"), ("mac", "macmini-2")])
def test_add_a_device_simulated(client, started, os_name, device_id):
    r = client.post("/api/demo/add_device", json={"os": os_name})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["simulated"] and body["code"] in body["transcript"][-6] and "checksum" in body["transcript"][2]
    p = client.get(f"/api/demo/pair/{body['code']}").json()
    assert p["name"] == body["name"] and p["continues"] is None and p["simulated"]
    r = client.post(f"/api/demo/pair/{body['code']}", json={"approve": True})
    assert r.status_code == 200 and r.json()["deviceId"] == device_id
    d = db.device(started, device_id).get().to_dict()
    assert d["simulated"] and d["status"] == "ok" and len(d["findings"]) == 1 and d["findings"][0]["severity"] == "info"
    assert len(list(db.services(started, device_id).get())) == 2
    assert body["name"] in agentlib.fleet_summary(started, generation(started))
    assert client.post(f"/api/demo/pair/{body['code']}", json={"approve": True}).status_code == 409  # already decided
    assert client.post("/api/demo/add_device", json={"os": os_name}).status_code == 409  # already on the map
    demo.reset(started)
    assert not db.device(started, device_id).get().exists


def test_add_device_needs_the_sample_home(client, uid):
    demo.start(uid, "empty")
    assert client.post("/api/demo/add_device", json={"os": "linux"}).status_code == 409


def test_live_machine_cant_reset_or_inject_from_the_sample_panel(client, started, monkeypatch):
    monkeypatch.setattr(settings, "live_pool", [f"live-1={started}"])
    monkeypatch.setattr(live, "enabled", lambda: True)
    assert client.post("/api/demo/reset", json={}).status_code == 403
    assert client.post("/api/demo/inject", json={"kind": "disk_full", "deviceId": "pi-1"}).status_code == 403
    assert client.post("/api/demo/add_device", json={"os": "linux"}).status_code == 403


def test_anonymous_look_never_schedules_real_devices(client, started, monkeypatch):
    from nightlight_api import real
    from nightlight_api.auth import anonymous
    from nightlight_api.main import app
    monkeypatch.setattr(real, "discover_everywhere", lambda *a, **k: pytest.fail("real scheduler reached"))
    app.dependency_overrides[anonymous] = lambda: True
    body = client.post("/api/discover", json={}).json()
    assert body["simulated"] and body["asked"][0]["deviceId"] == "pi-1"


def test_live_machine_cant_rebuild_through_start_or_template(client, started, monkeypatch):
    monkeypatch.setattr(settings, "live_pool", [f"live-1={started}"])
    assert client.post("/api/demo/template", json={"template": "home-pi"}).status_code == 403
    assert client.post("/api/demo/start", json={"template": "home-pi"}).status_code == 403
