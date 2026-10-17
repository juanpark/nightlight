"""The one-time setup card: agree once when a device first connects; Settings changes it later."""

from nightlight_api import db
from test_real import FACTS, beat, enrolled


def test_setup_applies_a_preset_once_and_marks_the_device_set_up(client, started):
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], {**FACTS, "manage": "app", "os": "Debian 12",
                               "containers": [{"name": "teslamate", "state": "running"}]})
    r = client.post(f"/api/devices/{dev['deviceId']}/setup", json={"preset": "fix", "autoUpdate": True}).json()
    d = db.device(started, dev["deviceId"]).get().to_dict()
    assert r["applied"] and d["setupAt"] and d["setupPreset"] == "fix"
    p = d["permissions"]
    assert p["cleanup"] and p["autoUpdate"] and p["restart_container"] == ["teslamate"]


def test_a_strict_device_is_marked_set_up_without_changing_it(client, started):
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], {**FACTS, "manage": "strict"})
    r = client.post(f"/api/devices/{dev['deviceId']}/setup", json={"preset": "fix"}).json()
    assert not r["applied"] and r["why"] == "strict_device"
    assert db.device(started, dev["deviceId"]).get().to_dict()["setupAt"]


def test_mac_folders_are_asked_on_a_mac_with_a_new_enough_helper(client, started):
    mac = enrolled(client, "Mac")
    beat(client, mac["token"], {**FACTS, "manage": "app", "os": "macOS 26.1", "helperVersion": "0.9.22"})
    r = client.post(f"/api/devices/{mac['deviceId']}/setup", json={"preset": "watch", "macFolders": True}).json()
    a = db.action(started, r["macFoldersAction"]).get().to_dict()
    assert a["type"] == "mac_folders" and a["status"] == "approved"  # the choice is the approval
    pi = enrolled(client, "Pi")
    beat(client, pi["token"], {**FACTS, "manage": "app", "os": "Debian 12", "helperVersion": "0.9.22"})
    r = client.post(f"/api/devices/{pi['deviceId']}/setup", json={"preset": "watch", "macFolders": True}).json()
    assert r["macFoldersAction"] is None and r["why"] == "not_a_mac"
