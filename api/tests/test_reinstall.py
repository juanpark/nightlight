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
    monkeypatch.setattr(real, "PAIR_PER_IP_HOUR", 10_000)  # every test here pairs from the test client's address


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


def _archived_and_due(client, uid):
    old = on_map(client, uid)
    client.post(f"/api/devices/{old['deviceId']}/remove", json={})
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.device(uid, old["deviceId"]).update({"purgeAt": past})
    archive.index().document(f"{uid}__{old['deviceId']}").update({"purgeAt": past})
    return old


def test_a_sweep_that_saw_the_entry_before_a_restore_deletes_nothing(client, started):
    old = _archived_and_due(client, started)
    entry = archive.index().document(f"{started}__{old['deviceId']}").get().to_dict()  # the sweep's snapshot
    p = pair(client)
    client.post(f"/api/devices/pair/{p['code']}", json={"approve": True, "continueDevice": True})
    new = poll(client, p).json()
    assert new["continued"] is True
    assert archive.purge(entry["uid"], entry["deviceId"], due_only=True) is False  # the paused purge resumes
    assert db.device(started, old["deviceId"]).get().exists
    assert len(list(db.notes(started, old["deviceId"]).get())) == 1
    assert beat(client, new["token"], {**FACTS, "machine": MAC}).status_code == 200


def test_a_purge_that_claimed_the_device_wins_and_the_reinstall_becomes_new(client, started):
    old = _archived_and_due(client, started)
    p = pair(client)
    client.post(f"/api/devices/pair/{p['code']}", json={"approve": True, "continueDevice": True})
    assert archive._claim(started, old["deviceId"], due_only=True)  # the sweep claims it first
    new = poll(client, p).json()
    assert new["deviceId"] != old["deviceId"] and "continued" not in new
    assert archive.purge(started, old["deviceId"], due_only=True) is True
    assert not db.device(started, old["deviceId"]).get().exists
    assert db.device(started, new["deviceId"]).get().exists


def test_forget_after_a_restore_refuses(client, started, monkeypatch):
    old = _archived_and_due(client, started)
    claimed = archive._claim

    def restore_first(uid, device_id, due_only):  # a reinstall continues it between the check and the claim
        p = pair(client)
        client.post(f"/api/devices/pair/{p['code']}", json={"approve": True, "continueDevice": True})
        assert poll(client, p).json()["continued"] is True
        return claimed(uid, device_id, due_only)

    monkeypatch.setattr(archive, "_claim", restore_first)
    assert client.delete(f"/api/devices/{old['deviceId']}").status_code == 409
    assert len(list(db.notes(started, old["deviceId"]).get())) == 1


def test_if_the_old_helper_comes_back_before_the_poll_it_keeps_its_device(client, started):
    old = on_map(client, started)
    p = pair(client)
    client.post(f"/api/devices/pair/{p['code']}", json={"approve": True, "continueDevice": True})
    db.client().collection("helperTokens").document(real._sha(old["token"])).update({"lastSeen": None})
    assert beat(client, old["token"], {**FACTS, "machine": MAC}).status_code == 200  # reporting again
    new = poll(client, p).json()
    assert new["deviceId"] != old["deviceId"] and "continued" not in new
    db.client().collection("helperTokens").document(real._sha(old["token"])).update({"lastSeen": None})
    assert beat(client, old["token"], {**FACTS, "machine": MAC}).status_code == 200  # its token still works


def test_the_pairing_request_keeps_only_the_keyed_fingerprint_once_decided(client, started):
    on_map(client, started)
    p = pair(client)
    client.post(f"/api/devices/pair/{p['code']}", json={"approve": True})
    doc = db.client().collection("pairRequests").document(real._sha(p["code"].replace("-", ""))).get().to_dict()
    assert "machine" not in doc and doc["machineTag"] and doc["machineTag"] != MAC


def test_stale_entry_cleanup_never_erases_a_fresh_archive_schedule(started):  # Codex reinstall rev2
    from nightlight_api import archive
    dev, iref = db.device(started, "dz1"), archive.index().document(f"{started}__dz1")
    dev.set({"name": "Old Mac", "realm": "real", "archived": True})  # removed again: archived, with a new entry
    iref.set({"uid": started, "deviceId": "dz1"})
    archive._drop_stale_entry(started, "dz1")
    assert iref.get().exists  # the new schedule survives
    dev.update({"archived": False})  # brought back: now the entry really is stale
    archive._drop_stale_entry(started, "dz1")
    assert not iref.get().exists


# ------------------------------------------------------------------ what it watched comes back after a reinstall
ROUTER = {"cid": "aaaaaaaaaaa1", "guess": "Router", "vendor": "Ubiquiti", "services": ["web page", "router"],
          "ports": [80, 443], "hw": "1" * 20, "tag": "2" * 20}
PRINTER = {"cid": "aaaaaaaaaaa2", "guess": "Printer", "vendor": None, "services": ["printer"], "ports": [631],
           "hw": "3" * 20, "tag": "4" * 20}
APP = {**FACTS, "helperVersion": "0.9.33", "manage": "app", "machine": MAC}
PERMS = {"diagnose": True, "cleanup": True, "logs": ["pi-grafana-1"], "restart_container": ["pi-grafana-1"],
         "restart_service": ["pihole-FTL.service"]}


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


def watching_then_quiet(client, uid):
    """An app-managed device with permissions set in the app, watching a router and a printer, then gone quiet."""
    dev = enrolled(client, "MacBook Pro")
    h = {"X-Device-Token": dev["token"]}
    assert beat(client, dev["token"], APP).status_code == 200
    assert client.post(f"/api/devices/{dev['deviceId']}/permissions", json=PERMS).status_code == 200
    assert client.post("/helper/discoveries", json={"items": [ROUTER, PRINTER]}, headers=h).status_code == 200
    watched = [client.post(f"/api/discoveries/{dev['deviceId']}/{it['cid']}/add", json={"name": name}).json()["deviceId"]
               for it, name in ((ROUTER, "Router"), (PRINTER, "Printer"))]
    _again(dev["token"])
    beat(client, dev["token"], {**APP, "watchResults": [{"cid": ROUTER["cid"], "up": True, "ms": 3},
                                                       {"cid": PRINTER["cid"], "up": True, "ms": 5}]})
    db.device(uid, dev["deviceId"]).update({"lastSeen": datetime.now(timezone.utc) - timedelta(hours=1)})
    return dev, watched


def continued(client, old):
    p = pair(client)
    client.post(f"/api/devices/pair/{p['code']}", json={"approve": True, "continueDevice": True})
    new = poll(client, p).json()
    assert new["deviceId"] == old["deviceId"] and new["continued"]
    return new


def test_a_continued_app_managed_device_keeps_its_permissions_and_watches_again(client, started):
    old, watched = watching_then_quiet(client, started)
    new = continued(client, old)
    first = beat(client, new["token"], APP).json()  # a fresh helper: it found nothing nearby yet, so no results
    assert {k: first["permissions"][k] for k in PERMS} == PERMS  # the app-side permissions carried over
    assert db.device(started, old["deviceId"]).get().to_dict()["rewatch"]["state"] == "asked"
    assert all(db.device(started, w).get().to_dict()["watchedBy"] == old["deviceId"] for w in watched)
    _again(new["token"])
    jobs = beat(client, new["token"], APP).json()["jobs"]
    assert [j["type"] for j in jobs] == ["discover"]  # it looks nearby once, by itself
    d = db.device(started, old["deviceId"]).get().to_dict()
    assert not any(f["id"] == "f_rewatch" for f in d["findings"])  # no ask while the look is under way
    again = [{**ROUTER, "cid": "bbbbbbbbbbb1", "tag": "9" * 20}, {**PRINTER, "cid": "bbbbbbbbbbb2"}]  # new ids
    h = {"X-Device-Token": new["token"]}
    assert client.post("/helper/discoveries", json={"items": again}, headers=h).status_code == 200
    _again(new["token"])
    body = beat(client, new["token"], APP).json()
    assert sorted(body["watch"], key=lambda w: w["cid"]) == [{"cid": "bbbbbbbbbbb1", "port": 443},
                                                            {"cid": "bbbbbbbbbbb2", "port": 631}]
    _again(new["token"])
    beat(client, new["token"], {**APP, "watchResults": [{"cid": "bbbbbbbbbbb1", "up": True, "ms": 2},
                                                       {"cid": "bbbbbbbbbbb2", "up": True, "ms": 4}]})
    for w in watched:
        wd = db.device(started, w).get().to_dict()
        assert wd["status"] == "ok" and wd["watchedBy"] == old["deviceId"]
        assert wd["lastAnswerAt"] > datetime.now(timezone.utc) - timedelta(minutes=1)  # answering again
    assert "rewatch" not in db.device(started, old["deviceId"]).get().to_dict()


def test_a_continued_strict_device_asks_the_owner_to_watch_again(client, started):
    old, watched = watching_then_quiet(client, started)
    new = continued(client, old)
    strict = {**APP, "manage": "strict"}
    assert beat(client, new["token"], strict).json()["jobs"] == []
    d = db.device(started, old["deviceId"]).get().to_dict()
    ask = next(f for f in d["findings"] if f["id"] == "f_rewatch")
    assert ask["message"].startswith("Reinstalled: re-allow watching Router and Printer?")
    assert "nightlight discover" in ask["message"] and d["status"] == "warn"
    assert not [a for a in db.actions(started).get() if a.to_dict().get("type") == "discover"
                and a.to_dict().get("deviceId") == old["deviceId"] and a.to_dict().get("status") == "approved"]
    # the owner runs `nightlight discover` there and picks them: they are checked again and the ask goes
    h = {"X-Device-Token": new["token"]}
    again = [{**ROUTER, "cid": "ccccccccccc1"}, {**PRINTER, "cid": "ccccccccccc2"}]
    assert client.post("/helper/discoveries", json={"items": again}, headers=h).status_code == 200
    _again(new["token"])
    beat(client, new["token"], {**strict, "watchResults": [{"cid": "ccccccccccc1", "up": True, "ms": 2},
                                                          {"cid": "ccccccccccc2", "up": False, "ms": None}]})
    d = db.device(started, old["deviceId"]).get().to_dict()
    assert not any(f["id"] == "f_rewatch" for f in d["findings"]) and "rewatch" not in d


def test_a_look_that_misses_one_asks_about_that_one(client, started):
    old, watched = watching_then_quiet(client, started)
    new = continued(client, old)
    beat(client, new["token"], APP)
    h = {"X-Device-Token": new["token"]}
    assert client.post("/helper/discoveries", json={"items": [{**ROUTER, "cid": "ddddddddddd1"}]},
                       headers=h).status_code == 200  # the printer is switched off
    _again(new["token"])
    beat(client, new["token"], {**APP, "watchResults": [{"cid": "ddddddddddd1", "up": True, "ms": 2}]})
    ask = next(f for f in db.device(started, old["deviceId"]).get().to_dict()["findings"] if f["id"] == "f_rewatch")
    assert "re-allow watching Printer?" in ask["message"] and "Look nearby" in ask["message"]


def test_a_moved_printer_is_rebound_by_its_hardware_never_by_its_old_address(client, started):  # Codex rewatch #1
    old, watched = watching_then_quiet(client, started)
    new = continued(client, old)
    beat(client, new["token"], APP)
    h = {"X-Device-Token": new["token"]}
    squatter = {"cid": "eeeeeeeeeee1", "guess": "Printer", "vendor": None, "services": ["printer"], "ports": [631],
                "tag": PRINTER["tag"]}  # another machine at the printer's old address, no hardware fingerprint
    moved = {**PRINTER, "cid": "eeeeeeeeeee2", "tag": "5" * 20}  # the printer itself, at a new address
    router = {**ROUTER, "cid": "eeeeeeeeeee3"}
    assert client.post("/helper/discoveries", json={"items": [squatter, router, moved]}, headers=h).status_code == 200
    assert db.device(started, watched[1]).get().to_dict()["cid"] == "eeeeeeeeeee2"
    # the printer switched off: the squatter at its old address is never taken for it
    assert client.post("/helper/discoveries", json={"items": [{**squatter, "cid": "fffffffffff1"}, router]},
                       headers=h).status_code == 200
    assert db.device(started, watched[1]).get().to_dict()["cid"] == "eeeeeeeeeee2"
    _again(new["token"])
    beat(client, new["token"], {**APP, "watchResults": [{"cid": "eeeeeeeeeee3", "up": True, "ms": 2},
                                                       {"cid": "eeeeeeeeeee2", "up": True, "ms": 3}]})
    assert "rewatch" not in db.device(started, old["deviceId"]).get().to_dict()


def test_a_known_hardware_thing_is_not_rebound_on_address_alone(client, started):  # Codex rewatch #1
    old, watched = watching_then_quiet(client, started)
    new = continued(client, old)
    beat(client, new["token"], APP)
    h = {"X-Device-Token": new["token"]}
    squatter = {"cid": "abababababa1", "guess": "Printer", "vendor": None, "services": ["printer"], "ports": [631],
                "tag": PRINTER["tag"]}
    assert client.post("/helper/discoveries", json={"items": [squatter, {**ROUTER, "cid": "abababababa2"}]},
                       headers=h).status_code == 200
    assert db.device(started, watched[1]).get().to_dict()["cid"] == PRINTER["cid"]  # left alone
    _again(new["token"])
    beat(client, new["token"], {**APP, "watchResults": [{"cid": "abababababa2", "up": True, "ms": 2}]})
    ask = next(f for f in db.device(started, old["deviceId"]).get().to_dict()["findings"] if f["id"] == "f_rewatch")
    assert "re-allow watching Printer?" in ask["message"]


def test_a_new_device_is_unaffected(client, started):
    old, watched = watching_then_quiet(client, started)
    p = pair(client)
    client.post(f"/api/devices/pair/{p['code']}", json={"approve": True})  # "Add as a new device"
    new = poll(client, p).json()
    assert new["deviceId"] != old["deviceId"]
    body = beat(client, new["token"], APP).json()
    assert body["watch"] == [] and body["jobs"] == []
    d = db.device(started, new["deviceId"]).get().to_dict()
    assert "rewatch" not in d and not any(f["id"] == "f_rewatch" for f in d["findings"])
    assert all(db.device(started, w).get().to_dict()["watchedBy"] == old["deviceId"] for w in watched)
    assert "rewatch" not in db.device(started, old["deviceId"]).get().to_dict()


def _aged(uid, watched):
    """The watched things haven't been checked for a while (the reinstalled helper can't check them yet)."""
    for w in watched:
        db.device(uid, w).update({"lastSeen": datetime.now(timezone.utc) - timedelta(hours=1)})


def _mini(client, facts=None):
    """Another of the owner's helpers on the same network (the Mac mini)."""
    mini = enrolled(client, "Mac mini")
    assert beat(client, mini["token"], facts or {**APP, "machine": OTHER_MAC}).status_code == 200
    return mini


def _events(uid, device_id):
    return [e.to_dict()["message"] for e in db.events(uid).get() if e.to_dict().get("deviceId") == device_id]


def _look(client, dev, items):
    assert client.post("/helper/discoveries", json={"items": items},
                       headers={"X-Device-Token": dev["token"]}).status_code == 200


def test_a_watch_its_watcher_cannot_check_moves_to_a_device_that_can(client, started):  # production 10/18
    old, watched = watching_then_quiet(client, started)
    mini = _mini(client)
    new = continued(client, old)
    beat(client, new["token"], APP)
    _aged(started, watched)
    _look(client, mini, [{**PRINTER, "cid": "9a9a9a9a9a91", "ports": [80, 631]}])
    # the MacBook's last look is still the old helper's (it saw 631 then): nothing moves yet
    assert db.device(started, watched[1]).get().to_dict()["watchedBy"] == old["deviceId"]
    # the reinstalled MacBook sees the printer, but no port it could check on it
    _look(client, new, [{**ROUTER, "cid": "9b9b9b9b9b91", "ports": [80]}, {**PRINTER, "cid": "9b9b9b9b9b92", "ports": []}])
    p = db.device(started, watched[1]).get().to_dict()
    assert (p["watchedBy"], p["cid"], p["checkPort"]) == (mini["deviceId"], "9a9a9a9a9a91", 631)
    assert p["purpose"] == "A printer. Watched by Mac mini."
    assert "Printer is now watched from Mac mini: MacBook Pro couldn't reach it." in _events(started, watched[1])
    r = db.device(started, watched[0]).get().to_dict()
    assert (r["watchedBy"], r["cid"]) == (old["deviceId"], "9b9b9b9b9b91")  # the router stays where it is checked
    look = real.discoveries_ref(started).document(mini["deviceId"]).get().to_dict()["items"]
    assert look[0]["added"] is True  # on the map: not offered in Found nearby
    _again(mini["token"])
    body = beat(client, mini["token"], {**APP, "machine": OTHER_MAC}).json()
    assert body["watch"] == [{"cid": "9a9a9a9a9a91", "port": 631}]  # the Mac mini starts checking at once
    _again(mini["token"])
    beat(client, mini["token"], {**APP, "machine": OTHER_MAC,
                                 "watchResults": [{"cid": "9a9a9a9a9a91", "up": True, "ms": 4}]})
    p = db.device(started, watched[1]).get().to_dict()
    assert p["status"] == "ok" and p["lastAnswerAt"] > datetime.now(timezone.utc) - timedelta(minutes=1)
    _again(new["token"])
    beat(client, new["token"], {**APP, "watchResults": [{"cid": "9b9b9b9b9b91", "up": True, "ms": 2}]})
    d = db.device(started, old["deviceId"]).get().to_dict()
    assert "rewatch" not in d and not any(f["id"] == "f_rewatch" for f in d["findings"])


def test_the_ask_to_rewatch_goes_when_its_last_unchecked_thing_moves(client, started):
    old, watched = watching_then_quiet(client, started)
    mini = _mini(client)
    new = continued(client, old)
    strict = {**APP, "manage": "strict"}
    beat(client, new["token"], strict)
    _look(client, new, [{**ROUTER, "cid": "8c8c8c8c8c81"}])  # it finds the router again, not the printer
    _again(new["token"])
    beat(client, new["token"], {**strict, "watchResults": [{"cid": "8c8c8c8c8c81", "up": True, "ms": 2}]})
    assert any(f["id"] == "f_rewatch" for f in db.device(started, old["deviceId"]).get().to_dict()["findings"])
    _aged(started, watched[1:])
    _look(client, mini, [{**PRINTER, "cid": "8d8d8d8d8d81"}])
    assert db.device(started, watched[1]).get().to_dict()["watchedBy"] == mini["deviceId"]
    d = db.device(started, old["deviceId"]).get().to_dict()
    assert "rewatch" not in d and not any(f["id"] == "f_rewatch" for f in d["findings"])


def test_a_watcher_that_can_still_check_keeps_its_watch(client, started):
    old, watched = watching_then_quiet(client, started)
    mini = _mini(client)
    new = continued(client, old)
    beat(client, new["token"], APP)
    _aged(started, watched)
    _look(client, mini, [{**PRINTER, "cid": "7e7e7e7e7e71"}])
    _look(client, new, [{**ROUTER, "cid": "7f7f7f7f7f71"}, {**PRINTER, "cid": "7f7f7f7f7f72"}])
    for w, cid in zip(watched, ("7f7f7f7f7f71", "7f7f7f7f7f72")):
        d = db.device(started, w).get().to_dict()
        assert (d["watchedBy"], d["cid"]) == (old["deviceId"], cid)
    assert not any("is now watched from" in m for m in _events(started, watched[1]))


def test_a_watch_nobody_else_can_check_stays_and_the_ask_stays(client, started):
    old, watched = watching_then_quiet(client, started)
    mini = _mini(client)
    older = _mini(client, FACTS)  # an older helper (neither app-managed nor strict) sees it: never handed to it
    new = continued(client, old)
    strict = {**APP, "manage": "strict"}
    beat(client, new["token"], strict)
    _aged(started, watched)
    _look(client, mini, [{**PRINTER, "cid": "6a6a6a6a6a61", "ports": []}])
    _look(client, older, [{**PRINTER, "cid": "6b6b6b6b6b61"}])
    _look(client, new, [{**ROUTER, "cid": "6c6c6c6c6c61"}])
    p = db.device(started, watched[1]).get().to_dict()
    assert (p["watchedBy"], p["cid"]) == (old["deviceId"], PRINTER["cid"])
    _again(new["token"])
    beat(client, new["token"], {**strict, "watchResults": [{"cid": "6c6c6c6c6c61", "up": True, "ms": 2}]})
    ask = next(f for f in db.device(started, old["deviceId"]).get().to_dict()["findings"] if f["id"] == "f_rewatch")
    assert "re-allow watching Printer?" in ask["message"]


def test_a_watcher_that_sees_it_on_another_port_keeps_it_and_checks_that_port(client, started):  # Codex handover #1
    old, watched = watching_then_quiet(client, started)
    mini = _mini(client)
    _aged(started, watched)
    _look(client, mini, [{**PRINTER, "cid": "5a5a5a5a5a51"}])
    _look(client, old, [ROUTER, {**PRINTER, "ports": [80]}])  # same id, but 631 isn't open now
    p = db.device(started, watched[1]).get().to_dict()
    assert (p["watchedBy"], p["cid"], p["checkPort"]) == (old["deviceId"], PRINTER["cid"], 80)
    assert not any("is now watched from" in m for m in _events(started, watched[1]))
    _again(old["token"])
    assert {"cid": PRINTER["cid"], "port": 80} in beat(client, old["token"], APP).json()["watch"]


def test_an_offline_helper_never_takes_a_watch(client, started):  # Codex handover #2
    old, watched = watching_then_quiet(client, started)
    mini = _mini(client)
    new = continued(client, old)
    beat(client, new["token"], APP)
    _aged(started, watched)
    _look(client, mini, [{**PRINTER, "cid": "4a4a4a4a4a41"}])
    db.device(started, mini["deviceId"]).update({"lastSeen": datetime.now(timezone.utc) - timedelta(hours=23)})
    _look(client, new, [{**ROUTER, "cid": "4b4b4b4b4b41"}, {**PRINTER, "cid": "4b4b4b4b4b42", "ports": []}])
    assert db.device(started, watched[1]).get().to_dict()["watchedBy"] == old["deviceId"]


def test_a_check_from_before_the_reinstall_keeps_the_ask(client, started):  # Codex handover #3
    old, watched = watching_then_quiet(client, started)  # both checked moments before the reinstall
    mini = _mini(client)
    new = continued(client, old)
    strict = {**APP, "manage": "strict"}
    beat(client, new["token"], strict)
    _look(client, new, [])  # it finds nothing yet
    _aged(started, watched[1:])
    _look(client, mini, [{**PRINTER, "cid": "3a3a3a3a3a31"}])
    assert db.device(started, watched[1]).get().to_dict()["watchedBy"] == mini["deviceId"]
    ask = next(f for f in db.device(started, old["deviceId"]).get().to_dict()["findings"] if f["id"] == "f_rewatch")
    assert ask  # the router isn't checked by the new install yet: the ask stays
