"""Found things carry their maker and model (never a name or address); a helper's other addresses are still its own;
anything found nearby sits behind its finder's router on the map."""

from nightlight_api import agent as agentlib, db, real
from conftest import generation
from test_auto_links import MAC, ROUTER, _links, _net, _report
from test_discovery import ITEM
from test_real import FACTS, beat, enrolled

PRINTER = {**ITEM, "cid": "c0c0c0c0c0c1", "guess": "Printer", "vendor": None, "services": ["printer"], "ports": [631],
           "maker": "Brother", "model": "HL-L2350DW"}


def _send(client, dev, items):
    r = client.post("/helper/discoveries", json={"items": items}, headers={"X-Device-Token": dev["token"]})
    assert r.status_code == 200, r.text


def test_maker_and_model_are_kept_and_merged(client, started):
    a, b = enrolled(client, "Mac"), enrolled(client, "Pi")
    _send(client, a, [{**PRINTER, "tag": "5" * 20, "maker": None, "model": None}])
    _send(client, b, [{**PRINTER, "tag": "5" * 20}])
    row = client.get("/api/found").json()["items"][0]
    assert (row["maker"], row["model"]) == ("Brother", "HL-L2350DW") and len(row["seenBy"]) == 2
    assert "Printer, Brother HL-L2350DW (seen by" in agentlib.fleet_summary(started, generation(started))


def test_maker_and_model_refuse_names_and_odd_characters(client, started):
    dev = enrolled(client)
    h = {"X-Device-Token": dev["token"]}
    for bad in ({"model": "Juan's iPhone"}, {"model": "x" * 61}, {"maker": "y" * 41}, {"model": "nas:445"},
                {"maker": "<b>"}, {"model": " leading space"}, {"model": "Café"}):
        assert client.post("/helper/discoveries", json={"items": [{**PRINTER, **bad}]}, headers=h).status_code == 422
    _send(client, dev, [{**PRINTER, "maker": "Apple", "model": "iPhone de Juan"},
                        {**PRINTER, "cid": "c0c0c0c0c0c2", "maker": "Juans-MacBook", "model": "192.168.1.5"},
                        {**PRINTER, "cid": "c0c0c0c0c0c3", "model": "1234567"}])
    stored = db.user(started).collection("discoveries").document(dev["deviceId"]).get().to_dict()["items"]
    assert [(i["maker"], i["model"]) for i in stored] == [("Apple", None), (None, None), ("Brother", None)]


def test_a_helpers_other_addresses_are_its_own(client, started):
    mac, pi = enrolled(client, "Mac"), enrolled(client, "Pi")
    second = "6" * 20
    _report(client, mac, {**FACTS, "net": {"self": MAC, "selves": [MAC, second], "gateway": ROUTER, "peers": []}})
    _send(client, pi, [{**PRINTER, "tag": second}, {**PRINTER, "cid": "c0c0c0c0c0c2", "tag": "7" * 20}])
    assert [r["tag"] for r in client.get("/api/found").json()["items"]] == ["7" * 20]  # the Mac's Wi-Fi is the Mac
    for bad in ({"selves": ["192.168.1.5"]}, {"selves": [f"{i:020x}" for i in range(9)]}):
        assert beat(client, mac["token"], {**FACTS, "net": {"self": MAC, **bad}}).status_code == 422


def test_role_comes_from_model_hints():
    assert real.role_for({"guess": "Device with a web page", "maker": "Synology", "model": "DS920+"}, set()) \
        == "fileshare"
    assert real.role_for({"guess": "Unknown device", "maker": "HP", "model": "LaserJet Pro M404"}, set()) == "printer"
    assert real.role_for({"guess": "Router", "services": ["router", "web page"]}, set()) == "router"
    assert real.role_for({"guess": "Device with a web page", "services": ["router"]}, set()) == "router"
    assert real.role_for({"guess": "Speaker or TV", "services": ["media player"]}, set()) == "speaker"
    assert real.role_for({"guess": "Device with a web page", "model": "BRAVIA 4K"}, set()) == "speaker"
    assert real.role_for({"guess": "Printer", "model": "Mac mini"}, set()) == "printer"  # a printer service wins
    assert real.role_for({"guess": "Computer (remote login)", "maker": "Apple", "model": "Mac mini"}, set()) \
        == "computer"
    assert real.role_for({"guess": "Unknown device"}, set()) == "other"


def test_a_watched_thing_sits_behind_its_finders_router(client, started):
    mac = enrolled(client, "Mac")
    _report(client, mac, _net(MAC))
    router = {**ITEM, "guess": "Device with a web page", "vendor": None, "services": ["web page"], "ports": [80],
              "tag": ROUTER}
    _send(client, mac, [router, PRINTER])
    rid = client.post(f"/api/discoveries/{mac['deviceId']}/{ITEM['cid']}/add", json={"name": "Router"}).json()
    pid = client.post(f"/api/discoveries/{mac['deviceId']}/{PRINTER['cid']}/add", json={"name": "Printer"}).json()
    rid, pid = rid["deviceId"], pid["deviceId"]
    got = _links(started)
    line = got[f"{pid}__{rid}"]
    assert (line["kind"], line["source"], line["why"]) == ("network", "auto", "found on the same network as Mac")
    assert f"{rid}__{rid}" not in got and not any(k.startswith(f"{rid}__") for k in got)  # the router: no line
    printer = db.device(started, pid).get().to_dict()
    assert (printer["role"], printer["maker"], printer["model"]) == ("printer", "Brother", "HL-L2350DW")
    assert "Printer (Brother HL-L2350DW)" in agentlib.fleet_summary(started, generation(started))
