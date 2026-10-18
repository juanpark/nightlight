"""A reinstall continues the same device: the owner chooses it while approving, the device keeps its history."""

from datetime import datetime, timedelta, timezone

import pytest

from nightlight_api import archive, db, demo, notebook, real
from nightlight_api.auth import current_uid, owner_uid
from nightlight_api.main import app
from conftest import generation
from test_real import FACTS, beat, enrolled

MAC = "6cacb92964ac00588d4377db91746132"
OTHER_MAC = "0" * 31 + "1"


@pytest.fixture(autouse=True)
def quick_polls(monkeypatch):
    monkeypatch.setattr(real, "POLL_MIN_SECONDS", 0)


def on_map(client, uid, machine=MAC, name="MacBook Pro"):
    """A device reporting through the command-line helper (with its machine fingerprint), then gone quiet."""
    dev = enrolled(client, name)
    assert beat(client, dev["token"], {**FACTS, "machine": machine}).status_code == 200
    notebook.add(uid, dev["deviceId"], "The fan is loud on Mondays.", "you", generation(uid))
    db.device(uid, dev["deviceId"]).update({"lastSeen": datetime.now(timezone.utc) - timedelta(hours=1),
                                            "x": 111, "y": 222})
    return dev


def pair(client, machine=MAC, via="installer"):
    body = {"name": "Juan's MacBook Pro", "os": "macOS 26.6", "via": via, **({"machine": machine} if machine else {})}
    r = client.post("/helper/pair/start", json=body)
    assert r.status_code == 201
    return r.json()


def poll(client, p):
    return client.post("/helper/pair/poll", json={"code": p["code"], "pollSecret": p["pollSecret"]})


def test_same_machine_is_offered_and_continued_with_its_history(client, started):
    old = on_map(client, started)
    p = pair(client)
    seen = client.get(f"/api/devices/pair/{p['code']}").json()
    assert seen["continues"]["deviceId"] == old["deviceId"] and seen["continues"]["name"] == "MacBook Pro"
    assert seen["continues"]["lastSeen"] and seen["continues"]["removed"] is False
    r = client.post(f"/api/devices/pair/{p['code']}", json={"approve": True, "continueDevice": True})
    assert r.status_code == 200 and r.json()["continues"] == old["deviceId"]
    new = poll(client, p).json()
    assert new["deviceId"] == old["deviceId"] and new["continued"] is True and new["token"] != old["token"]
    assert beat(client, old["token"]).status_code == 401  # the old helper's key is dead
    assert beat(client, new["token"], {**FACTS, "helperVersion": "0.9.33", "manage": "app",
                                       "machine": MAC}).status_code == 200
    d = db.device(started, old["deviceId"]).get().to_dict()
    assert (d["name"], d["x"], d["y"], d["installedWith"]) == ("MacBook Pro", 111, 222, "installer")
    assert d["helperVersion"] == "0.9.33" and d["manage"] == "app" and not d.get("revoked")
    assert [n.to_dict()["text"] for n in db.notes(started, old["deviceId"]).get()] == ["The fan is loud on Mondays."]
    words = [e.to_dict()["message"] for e in db.events(started).get() if e.to_dict().get("deviceId") == old["deviceId"]]
    assert any("reinstalled (installer)" in w and "history kept" in w for w in words)
    real_devices = [s for s in db.devices(started).get() if (s.to_dict() or {}).get("realm") == "real"]
    assert len(real_devices) == 1  # no second device


def test_add_as_new_device_is_the_default_and_different_machines_never_match(client, started):
    old = on_map(client, started)
    p = pair(client, machine=OTHER_MAC)
    assert client.get(f"/api/devices/pair/{p['code']}").json()["continues"] is None
    assert client.post(f"/api/devices/pair/{p['code']}",
                       json={"approve": True, "continueDevice": True}).json()["code"] == "nothing_to_continue"
    q = pair(client)  # the same machine, but the owner picks "Add as a new device" (no flag: an older app)
    assert client.get(f"/api/devices/pair/{q['code']}").json()["continues"]
    client.post(f"/api/devices/pair/{q['code']}", json={"approve": True})
    new = poll(client, q).json()
    assert new["deviceId"] != old["deviceId"] and "continued" not in new
    no_fingerprint = pair(client, machine=None)
    assert client.get(f"/api/devices/pair/{no_fingerprint['code']}").json()["continues"] is None


def test_a_device_still_reporting_is_never_offered(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], {**FACTS, "machine": MAC})  # reporting right now
    p = pair(client)
    assert client.get(f"/api/devices/pair/{p['code']}").json()["continues"] is None


def test_another_accounts_device_is_never_offered(client, started):
    on_map(client, started)
    other = "u_other_" + started[-6:]
    demo.start(other)
    app.dependency_overrides[current_uid] = app.dependency_overrides[owner_uid] = lambda: other
    p = pair(client)
    assert client.get(f"/api/devices/pair/{p['code']}").json()["continues"] is None
    assert client.post(f"/api/devices/pair/{p['code']}",
                       json={"approve": True, "continueDevice": True}).json()["code"] == "nothing_to_continue"


def test_a_removed_device_comes_back_with_its_history(client, started):
    old = on_map(client, started)
    assert client.post(f"/api/devices/{old['deviceId']}/remove", json={}).json()["removed"] == "access_cut"
    assert db.device(started, old["deviceId"]).get().to_dict()["archived"]
    p = pair(client, via="command_line")
    seen = client.get(f"/api/devices/pair/{p['code']}").json()["continues"]
    assert seen["deviceId"] == old["deviceId"] and seen["removed"] is True
    client.post(f"/api/devices/pair/{p['code']}", json={"approve": True, "continueDevice": True})
    new = poll(client, p).json()
    assert new["deviceId"] == old["deviceId"]
    d = db.device(started, old["deviceId"]).get().to_dict()
    assert not d["archived"] and "purgeAt" not in d and real.is_current(d, generation(started))
    assert not archive.index().document(f"{started}__{old['deviceId']}").get().exists
    assert db.client().collection("realDevices").document(f"{started}__{old['deviceId']}").get().exists
    assert [x["id"] for x in client.get("/api/devices/removed").json()["devices"]] == []
    assert len(list(db.notes(started, old["deviceId"]).get())) == 1
    assert beat(client, new["token"], {**FACTS, "machine": MAC}).status_code == 200


def test_a_second_approval_cannot_take_over_after_the_first(client, started):
    old = on_map(client, started)
    p, q = pair(client), pair(client)
    for x in (p, q):
        client.post(f"/api/devices/pair/{x['code']}", json={"approve": True, "continueDevice": True})
    assert poll(client, p).json()["deviceId"] == old["deviceId"]
    db.device(started, old["deviceId"]).update({"helperSince": datetime.now(timezone.utc) + timedelta(seconds=5)})
    second = poll(client, q).json()
    assert second["deviceId"] != old["deviceId"]  # becomes a new device; nothing merged


def test_local_uninstall_keeps_the_device_offline_with_its_history(client, started):
    old = on_map(client, started)
    assert client.post("/helper/leave", json={}, headers={"X-Device-Token": old["token"]}).status_code == 200
    d = db.device(started, old["deviceId"]).get().to_dict()
    assert not d.get("archived") and d["uninstalled"] and real.is_current(d, generation(started))
    assert real.view(d)["status"] == "offline" and beat(client, old["token"]).status_code == 401
    p = pair(client)  # then the Mac installer on the same machine
    assert client.get(f"/api/devices/pair/{p['code']}").json()["continues"]["deviceId"] == old["deviceId"]
    client.post(f"/api/devices/pair/{p['code']}", json={"approve": True, "continueDevice": True})
    assert poll(client, p).json()["deviceId"] == old["deviceId"]
    d = db.device(started, old["deviceId"]).get().to_dict()
    assert not d["uninstalled"] and not d["revoked"]


def test_machine_fingerprint_is_hashed_and_keyed_per_account(client, started):
    old = on_map(client, started)
    stored = db.device(started, old["deviceId"]).get().to_dict()["machine"]
    assert stored != MAC and len(stored) == 20
    assert client.post("/helper/pair/start", json={"name": "x", "machine": "not-hex"}).status_code == 422
