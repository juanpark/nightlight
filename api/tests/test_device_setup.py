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


def test_an_older_helper_keeps_its_setup_card_until_updated(client, started):
    dev = enrolled(client, "Old")
    beat(client, dev["token"], {**FACTS, "manage": None})
    r = client.post(f"/api/devices/{dev['deviceId']}/setup", json={"preset": "fix"}).json()
    assert not r["done"] and r["why"] == "update_helper"
    assert "setupAt" not in db.device(started, dev["deviceId"]).get().to_dict()


def test_setup_runs_once_and_never_undoes_later_settings(client, started):  # codex setup #1
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], {**FACTS, "manage": "app", "os": "Debian 12"})
    assert client.post(f"/api/devices/{dev['deviceId']}/setup", json={"preset": "fix"}).json()["applied"]
    assert client.post(f"/api/devices/{dev['deviceId']}/permissions",
                       json={"diagnose": True, "cleanup": False, "logs": [], "restart_container": [],
                             "restart_service": []}).status_code == 200
    again = client.post(f"/api/devices/{dev['deviceId']}/setup", json={"preset": "fix"}).json()
    assert again["already"] and db.device(started, dev["deviceId"]).get().to_dict()["permissions"]["cleanup"] is False


def test_fix_keeps_to_the_switch_limits(client, started):  # codex setup #2
    dev = enrolled(client, "Box")
    beat(client, dev["token"], {**FACTS, "manage": "app", "os": "Debian 12",
                               "containers": [{"name": f"c{i:02d}", "state": "running"} for i in range(21)]})
    r = client.post(f"/api/devices/{dev['deviceId']}/setup", json={"preset": "fix"}).json()
    p = db.device(started, dev["deviceId"]).get().to_dict()["permissions"]
    assert r["trimmed"] and len(p["restart_container"]) == 20 and len(p["logs"]) <= 20


def test_a_sleeping_mac_still_finishes_setup_with_a_reason(client, started):  # codex setup #3
    from datetime import datetime, timedelta, timezone
    mac = enrolled(client, "Mac")
    beat(client, mac["token"], {**FACTS, "manage": "app", "os": "macOS 26.1", "helperVersion": "0.9.23"})
    db.device(started, mac["deviceId"]).update({"lastSeen": datetime.now(timezone.utc) - timedelta(hours=2)})
    r = client.post(f"/api/devices/{mac['deviceId']}/setup", json={"preset": "watch", "macFolders": True})
    assert r.status_code == 200 and r.json()["applied"] and r.json()["why"] == "device_not_reporting"
    assert db.device(started, mac["deviceId"]).get().to_dict()["setupAt"]


def test_mac_folders_can_be_asked_again_and_the_answer_is_reported(client, started):
    mac = enrolled(client, "Mac")
    beat(client, mac["token"], {**FACTS, "manage": "app", "os": "macOS 26.1", "helperVersion": "0.9.23",
                               "macFolders": "declined"})
    assert db.device(started, mac["deviceId"]).get().to_dict()["macFolders"] == "declined"
    a = client.post(f"/api/devices/{mac['deviceId']}/mac-folders", json={}).json()
    assert client.post(f"/api/devices/{mac['deviceId']}/mac-folders", json={}).json()["actionId"] == a["actionId"]
    db.action(started, a["actionId"]).update({"status": "done"})
    assert client.post(f"/api/devices/{mac['deviceId']}/mac-folders", json={}).json()["actionId"] != a["actionId"]
    pi = enrolled(client, "Pi")
    beat(client, pi["token"], {**FACTS, "manage": "app", "os": "Debian 12", "helperVersion": "0.9.23"})
    assert client.post(f"/api/devices/{pi['deviceId']}/mac-folders", json={}).json()["code"] == "not_a_mac"


def test_an_interrupted_setup_is_finished_later_with_its_own_choices(client, started):  # codex release #2
    from datetime import datetime, timedelta, timezone
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], {**FACTS, "manage": "app", "os": "Debian 12"})
    db.device(started, dev["deviceId"]).update({"setup": {"preset": "fix", "autoUpdate": True, "macFolders": False,
                                                         "state": "applying",
                                                         "claimedAt": datetime.now(timezone.utc) - timedelta(minutes=5)}})
    r = client.post(f"/api/devices/{dev['deviceId']}/setup", json={"preset": "watch"}).json()
    d = db.device(started, dev["deviceId"]).get().to_dict()
    assert r["done"] and d["setupPreset"] == "fix" and d["permissions"]["cleanup"] and d["permissions"]["autoUpdate"]


def test_resuming_setup_never_undoes_settings_changed_meanwhile(client, started):  # codex release rev2 #1
    from datetime import datetime, timedelta, timezone
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], {**FACTS, "manage": "app", "os": "Debian 12"})
    ref = db.device(started, dev["deviceId"])
    # an attempt that applied Fix (recorded with the permissions), then stopped before finishing
    ref.update({"setup": {"preset": "fix", "autoUpdate": False, "macFolders": False, "state": "applying",
                          "permsApplied": True,
                          "claimedAt": datetime.now(timezone.utc) - timedelta(minutes=5)}})
    assert client.post(f"/api/devices/{dev['deviceId']}/permissions",
                       json={"diagnose": True, "cleanup": False, "logs": [], "restart_container": [],
                             "restart_service": []}).status_code == 200  # the owner restricts it meanwhile
    r = client.post(f"/api/devices/{dev['deviceId']}/setup", json={"preset": "fix"}).json()
    assert r["done"] and ref.get().to_dict()["permissions"]["cleanup"] is False


def test_asking_for_mac_folders_four_times_at_once_makes_one_request(client, started):  # codex release rev2 #2
    from concurrent.futures import ThreadPoolExecutor
    from nightlight_api import real
    mac = enrolled(client, "Mac")
    beat(client, mac["token"], {**FACTS, "manage": "app", "os": "macOS 26.1", "helperVersion": "0.9.23"})
    with ThreadPoolExecutor(4) as pool:
        ids = list(pool.map(lambda _: real.request_mac_folders(started, mac["deviceId"])["actionId"], range(4)))
    assert len(set(ids)) == 1
