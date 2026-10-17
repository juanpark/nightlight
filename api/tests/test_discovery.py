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


def test_the_app_can_ask_an_app_managed_device_to_look_nearby(client, started):
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], {**FACTS, "manage": "strict"})
    assert client.post(f"/api/devices/{dev['deviceId']}/discover", json={}).status_code == 409  # strict: at the device
    _again(dev["token"])
    beat(client, dev["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.21"})
    r = client.post(f"/api/devices/{dev['deviceId']}/discover", json={})
    assert r.status_code == 202 and r.json()["status"] == "approved"  # the tap is the approval
    _again(dev["token"])
    jobs = beat(client, dev["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.21"}).json()["jobs"]
    assert [j["type"] for j in jobs] == ["discover"]


def test_things_seen_by_several_devices_are_listed_once_and_your_own_devices_not_at_all(client, started):
    mac, pi = enrolled(client, "Mac"), enrolled(client, "Pi")
    pi_tag, router_tag = "c" * 20, "d" * 20
    beat(client, pi["token"], {**FACTS, "net": {"self": pi_tag, "gateway": router_tag, "peers": []}})
    router = {**ITEM, "cid": "aaaaaaaaaaa1", "guess": "Device with a web page", "vendor": None, "services": ["web page"],
              "ports": [80], "tag": router_tag}
    the_pi = {**ITEM, "cid": "bbbbbbbbbbb1", "tag": pi_tag}
    for dev, items in ((mac, [router, the_pi]), (pi, [{**router, "cid": "ccccccccccc1"}])):
        h = {"X-Device-Token": dev["token"]}
        assert client.post("/helper/discoveries", json={"items": items}, headers=h).status_code == 200
    rows = client.get("/api/found").json()["items"]
    assert len(rows) == 1 and rows[0]["guess"] == "Your router (internet connection)"  # once; the Pi is yours
    assert sorted(s["name"] for s in rows[0]["seenBy"]) == ["Mac", "Pi"]
    assert "seen by Mac, Pi" in agentlib.fleet_summary(started, generation(started)).replace("Pi, Mac", "Mac, Pi")


def test_looking_everywhere_asks_one_device_per_network(client, started):
    a, b, c = enrolled(client, "Mac"), enrolled(client, "Pi"), enrolled(client, "Old")
    home = {"self": "a" * 20, "gateway": "d" * 20, "peers": []}
    beat(client, a["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.21", "net": home})
    beat(client, b["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.21", "net": {**home, "self": "b" * 20}})
    beat(client, c["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.17"})
    r = client.post("/api/discover", json={}).json()
    assert len(r["asked"]) == 1 and r["asked"][0]["name"] in ("Mac", "Pi")  # one home, one look
    assert [s["name"] for s in r["skipped"]] == ["Old"] and "updating" in r["skipped"][0]["why"]


def test_each_look_is_its_own_job_and_an_empty_one_clears_the_list(client, started):  # codex discover #1, #2
    from nightlight_api import actions
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.21"})
    first = client.post(f"/api/devices/{dev['deviceId']}/discover", json={}).json()["actionId"]
    assert client.post(f"/api/devices/{dev['deviceId']}/discover", json={}).json()["actionId"] == first  # same scan
    db.action(started, first).update({"status": "done", "result": {"ok": True, "summary": "Found 1"}})
    second = client.post(f"/api/devices/{dev['deviceId']}/discover", json={}).json()["actionId"]
    assert second != first  # a new look: a late result for the first can't finish it
    h = {"X-Device-Token": dev["token"]}
    assert client.post("/helper/discoveries", json={"items": [ITEM]}, headers=h).status_code == 200
    assert client.post("/helper/discoveries", json={"items": []}, headers=h).status_code == 200
    assert client.get("/api/found").json()["items"] == []
    beat(client, dev["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.20"})
    _again(dev["token"])
    beat(client, dev["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.20"})
    db.action(started, second).update({"status": "done"})
    r = client.post(f"/api/devices/{dev['deviceId']}/discover", json={})
    assert r.status_code == 409 and r.json()["code"] == "update_helper_first"


def test_two_requests_at_once_start_one_look(client, started):  # codex discover rev2 #1
    from concurrent.futures import ThreadPoolExecutor
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.21"})
    with ThreadPoolExecutor(4) as pool:
        ids = list(pool.map(lambda _: real.request_discover(started, dev["deviceId"])["id"], range(4)))
    assert len(set(ids)) == 1
    everywhere = client.post("/api/discover", json={}).json()  # the global button joins the same look
    assert everywhere["asked"][0]["deviceId"] == dev["deviceId"]
    assert len([a for a in db.actions(started).get() if a.to_dict()["type"] == "discover"]) == 1


def test_a_thing_seen_differently_by_two_devices_can_still_be_added(client, started):  # codex discover rev2 #2
    mac, pi = enrolled(client, "Mac"), enrolled(client, "Pi")
    beat(client, mac["token"], FACTS)
    beat(client, pi["token"], FACTS)
    seen_quietly = {**ITEM, "cid": "aaaaaaaaaaa2", "guess": "Unknown device", "services": [], "ports": [],
                    "tag": "e" * 20}
    seen_well = {**ITEM, "cid": "bbbbbbbbbbb2", "tag": "e" * 20}  # Home Assistant on 8123
    for dev, it in ((mac, seen_quietly), (pi, seen_well)):
        h = {"X-Device-Token": dev["token"]}
        assert client.post("/helper/discoveries", json={"items": [it]}, headers=h).status_code == 200
    [row] = client.get("/api/found").json()["items"]
    assert row["guess"] == "Home Assistant" and 8123 in row["ports"]
    first = row["seenBy"][0]
    assert first["canWatch"] and first["deviceId"] == pi["deviceId"]
    r = client.post(f"/api/discoveries/{first['deviceId']}/{first['cid']}/add", json={"name": "Home Assistant"})
    assert r.status_code == 201


def test_a_finished_look_is_never_reopened(client, started):  # codex discover rev3 #1
    from nightlight_api import actions
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.21"})
    first = real.request_discover(started, dev["deviceId"])
    db.action(started, first["id"]).update({"status": "done", "result": {"ok": True, "summary": "Found 1"}})
    again = actions.request(started, "discover", dev["deviceId"], {}, session_id=None, turn_id="app_discover_1",
                            origin="app", once=True)  # a late or retried ask for scan 1
    assert again["id"] == first["id"] and again["status"] == "done"  # left as it finished
    nxt = real.request_discover(started, dev["deviceId"])
    assert nxt["id"] != first["id"] and nxt["status"] == "approved"


def test_add_uses_a_finder_with_room_left(client, started, monkeypatch):  # codex discover rev3 #2
    monkeypatch.setattr(real, "WATCHED_PER_HELPER", 1)
    mac, pi = enrolled(client, "Mac"), enrolled(client, "Pi")
    beat(client, mac["token"], FACTS)
    beat(client, pi["token"], FACTS)
    hm = {"X-Device-Token": mac["token"]}
    other = {**ITEM, "cid": "ddddddddddd3", "tag": "f" * 20}
    assert client.post("/helper/discoveries", json={"items": [other]}, headers=hm).status_code == 200
    assert client.post(f"/api/discoveries/{mac['deviceId']}/{other['cid']}/add", json={"name": "x"}).status_code == 201
    shared = {**ITEM, "cid": "eeeeeeeeeee3", "tag": "a" * 20}
    for dev, cid in ((mac, "eeeeeeeeeee3"), (pi, "eeeeeeeeeee4")):
        h = {"X-Device-Token": dev["token"]}
        assert client.post("/helper/discoveries", json={"items": [{**shared, "cid": cid}]}, headers=h).status_code == 200
    [row] = [r for r in client.get("/api/found").json()["items"] if r["tag"] == "a" * 20]
    first = row["seenBy"][0]
    assert first["deviceId"] == pi["deviceId"] and first["canWatch"]  # the Mac is full
    assert client.post(f"/api/discoveries/{first['deviceId']}/{first['cid']}/add", json={"name": "y"}).status_code == 201


def test_what_a_forgotten_device_found_goes_with_it(client, started):  # codex discover rev4 #1
    mac, pi = enrolled(client, "Mac"), enrolled(client, "Pi")
    beat(client, mac["token"], FACTS)
    beat(client, pi["token"], FACTS)
    for dev, cid in ((mac, "aaaaaaaaaaa5"), (pi, "bbbbbbbbbbb5")):
        h = {"X-Device-Token": dev["token"]}
        assert client.post("/helper/discoveries", json={"items": [{**ITEM, "cid": cid, "tag": "9" * 20}]},
                           headers=h).status_code == 200
    client.post(f"/api/devices/{mac['deviceId']}/remove", json={})
    assert client.delete(f"/api/devices/{mac['deviceId']}").status_code == 200  # forget for good
    [row] = client.get("/api/found").json()["items"]
    assert [f["deviceId"] for f in row["seenBy"]] == [pi["deviceId"]]
    first = row["seenBy"][0]
    assert client.post(f"/api/discoveries/{first['deviceId']}/{first['cid']}/add", json={"name": "HA"}).status_code == 201
    assert not db.user(started).collection("discoveries").document(mac["deviceId"]).get().exists


def test_found_things_are_named_plainly_and_the_router_comes_first(client, started):
    dev = enrolled(client, "MacBook")
    beat(client, dev["token"], {**FACTS, "net": {"self": "1" * 20, "gateway": "2" * 20, "peers": []}})
    phone = {**ITEM, "cid": "aaaaaaaaaaa6", "guess": real.PRIVATE_MAC, "vendor": real.PRIVATE_MAC, "services": [],
             "ports": [], "tag": "3" * 20}
    router = {**ITEM, "cid": "bbbbbbbbbbb6", "guess": "Device with a web page", "vendor": None,
              "services": ["web page"], "ports": [80], "tag": "2" * 20}
    h = {"X-Device-Token": dev["token"]}
    assert client.post("/helper/discoveries", json={"items": [phone, router]}, headers=h).status_code == 200
    rows = client.get("/api/found").json()["items"]
    assert rows[0]["guess"] == "Your router (internet connection)" and rows[0]["router"]
    assert rows[1]["guess"] == "Phone or laptop" and rows[1]["vendor"] is None and rows[1]["privateAddress"]


def test_looking_from_every_device_asks_each_of_them(client, started):
    a, b = enrolled(client, "Mac"), enrolled(client, "Pi")
    home = {"self": "a" * 20, "gateway": "d" * 20, "peers": []}
    beat(client, a["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.21", "net": home})
    beat(client, b["token"], {**FACTS, "manage": "app", "helperVersion": "0.9.21", "net": {**home, "self": "b" * 20}})
    r = client.post("/api/discover", json={"everyDevice": True}).json()
    assert sorted(x["name"] for x in r["asked"]) == ["Mac", "Pi"]


def test_stop_watching_takes_it_off_the_map_and_last_answer_is_kept(client, started):
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], FACTS)
    h = {"X-Device-Token": dev["token"]}
    assert client.post("/helper/discoveries", json={"items": [ITEM]}, headers=h).status_code == 200
    wid = client.post(f"/api/discoveries/{dev['deviceId']}/{ITEM['cid']}/add", json={"name": "HA"}).json()["deviceId"]
    _again(dev["token"])
    beat(client, dev["token"], {**FACTS, "watchResults": [{"cid": ITEM["cid"], "up": True, "ms": 4}]})
    answered = db.device(started, wid).get().to_dict()["lastAnswerAt"]
    _again(dev["token"])
    beat(client, dev["token"], {**FACTS, "watchResults": [{"cid": ITEM["cid"], "up": False, "ms": None}]})
    w = db.device(started, wid).get().to_dict()
    assert w["lastAnswerAt"] == answered and w["lastSeen"] > answered  # a failed check isn't an answer
    assert client.post(f"/api/devices/{wid}/revoke", json={}).status_code == 200
    assert db.device(started, wid).get().to_dict()["archived"] is True
    assert wid not in agentlib.fleet_summary(started, generation(started))
