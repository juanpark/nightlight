"""Discovery: owner-picked items without addresses; adding one makes a device watched by the helper."""

from nightlight_api import agent as agentlib, db, real
from conftest import generation
from test_real import FACTS, beat, enrolled

ITEM = {"cid": "a1b2c3d4e5f6", "guess": "Home Assistant", "vendor": "Raspberry Pi", "services": ["Home Assistant"],
        "ports": [8123]}


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


def test_found_items_become_watched_devices(client, started):
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], FACTS)
    h = {"X-Device-Token": dev["token"]}
    assert client.post("/helper/discoveries", json={"items": [ITEM]}, headers=h).status_code == 200
    assert "Home Assistant" in agentlib.fleet_summary(started, generation(started))
    r = client.post(f"/api/discoveries/{dev['deviceId']}/{ITEM['cid']}/add", json={"name": "Home Assistant"})
    assert r.status_code == 201
    wid = r.json()["deviceId"]
    assert client.post(f"/api/discoveries/{dev['deviceId']}/{ITEM['cid']}/add", json={"name": "x"}).status_code == 409
    _again(dev["token"])
    body = beat(client, dev["token"], FACTS).json()
    assert body["watch"] == [{"cid": ITEM["cid"], "port": 8123}]
    _again(dev["token"])
    beat(client, dev["token"], {**FACTS, "watchResults": [{"cid": ITEM["cid"], "up": False, "ms": None}]})
    w = db.device(started, wid).get().to_dict()
    assert w["status"] == "crit" and w["watchedBy"] == dev["deviceId"] and "isn't answering" in w["findings"][0]["message"]
    _again(dev["token"])
    beat(client, dev["token"], {**FACTS, "watchResults": [{"cid": ITEM["cid"], "up": True, "ms": 12}]})
    assert db.device(started, wid).get().to_dict()["status"] == "ok"


def test_addresses_are_refused(client, started):
    dev = enrolled(client)
    h = {"X-Device-Token": dev["token"]}
    for bad in ({**ITEM, "guess": "printer at 192.168.1.20"}, {**ITEM, "vendor": "aa:bb:cc:dd:ee:ff"},
                {**ITEM, "ip": "192.168.1.20"}, {**ITEM, "cid": "../x"}):
        assert client.post("/helper/discoveries", json={"items": [bad]}, headers=h).status_code == 422
    assert client.post("/helper/discoveries", json={"items": [ITEM]}, headers={"X-Device-Token": "x" * 43}) \
        .status_code == 401


def test_another_users_discovery_cant_be_added(client, started):
    assert client.post("/api/discoveries/dev_" + "0" * 26 + "/a1b2c3d4e5f6/add", json={"name": "x"}).status_code == 404


def test_vocabulary_only(client, started):  # review 12 #2
    dev = enrolled(client)
    h = {"X-Device-Token": dev["token"]}
    for bad in ({**ITEM, "guess": "fe80::1"}, {**ITEM, "vendor": "juans-nas.local"}, {**ITEM, "services": ["x"]},
                {**ITEM, "ports": [-1]}, {**ITEM, "ports": [31337]}):
        assert client.post("/helper/discoveries", json={"items": [bad]}, headers=h).status_code == 422


def test_rediscovery_capacity_and_recovery(client, started, monkeypatch):  # review 12 #3,#4,#5
    from datetime import datetime, timedelta, timezone
    from nightlight_api import watch
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], FACTS)
    h = {"X-Device-Token": dev["token"]}
    client.post("/helper/discoveries", json={"items": [ITEM]}, headers=h)
    wid = client.post(f"/api/discoveries/{dev['deviceId']}/{ITEM['cid']}/add", json={"name": "HA"}).json()["deviceId"]
    client.post("/helper/discoveries", json={"items": [ITEM]}, headers=h)  # the same thing found again
    assert client.post(f"/api/discoveries/{dev['deviceId']}/{ITEM['cid']}/add", json={"name": "x"}).status_code == 409
    noport = {**ITEM, "cid": "000000000001", "ports": [], "services": []}
    client.post("/helper/discoveries", json={"items": [noport]}, headers=h)
    assert client.post(f"/api/discoveries/{dev['deviceId']}/000000000001/add", json={"name": "x"}).status_code == 422
    monkeypatch.setattr(real, "WATCHED_PER_HELPER", 1)
    more = {**ITEM, "cid": "000000000002"}
    client.post("/helper/discoveries", json={"items": [more]}, headers=h)
    assert client.post(f"/api/discoveries/{dev['deviceId']}/000000000002/add", json={"name": "x"}).status_code == 429
    db.device(started, wid).update({"lastSeen": datetime.now(timezone.utc) - timedelta(minutes=9)})
    watch.sweep()
    assert db.device(started, wid).get().to_dict()["watchState"] == "silent"
    _again(dev["token"])
    beat(client, dev["token"], {**FACTS, "watchResults": [{"cid": ITEM["cid"], "up": True, "ms": 5}]})
    assert db.device(started, wid).get().to_dict()["watchState"] is None



def test_removing_a_watched_device_frees_its_place(client, started, monkeypatch):  # review 12 rev2
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], FACTS)
    h = {"X-Device-Token": dev["token"]}
    monkeypatch.setattr(real, "WATCHED_PER_HELPER", 1)
    other = {**ITEM, "cid": "000000000009"}
    client.post("/helper/discoveries", json={"items": [ITEM, other]}, headers=h)
    wid = client.post(f"/api/discoveries/{dev['deviceId']}/{ITEM['cid']}/add", json={"name": "HA"}).json()["deviceId"]
    assert client.post(f"/api/discoveries/{dev['deviceId']}/000000000009/add", json={"name": "x"}).status_code == 429
    assert client.post(f"/api/devices/{wid}/revoke", json={}).status_code == 200
    assert client.post(f"/api/discoveries/{dev['deviceId']}/000000000009/add", json={"name": "x"}).status_code == 201
    _again(dev["token"])
    assert all(w["cid"] != ITEM["cid"] for w in beat(client, dev["token"], FACTS).json()["watch"])
