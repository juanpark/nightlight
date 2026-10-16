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
