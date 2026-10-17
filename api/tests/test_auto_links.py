"""Lines the helpers see: keyed fingerprints of addresses (never addresses) become lines between real devices."""

import uuid

from nightlight_api import agent as agentlib, db, demo, links
from nightlight_api.auth import current_uid, owner_uid
from nightlight_api.main import app
from conftest import generation
from test_discovery import ITEM, _again
from test_real import FACTS, beat, enrolled

MAC, NAS, PI, ROUTER = "a" * 20, "b" * 20, "c" * 20, "d" * 20  # fingerprints (any 20 hex characters)


def _net(me, gateway=ROUTER, peers=()):
    return {**FACTS, "net": {"self": me, "gateway": gateway, "peers": [{"tag": t, "why": w} for t, w in peers]}}


def _links(uid):
    return {s.id: s.to_dict() for s in db.links(uid).get() if s.to_dict().get("realm") == "real"}


def _report(client, dev, facts):
    _again(dev["token"])
    r = beat(client, dev["token"], facts)
    assert r.status_code == 200, r.text
    return r.json()


def _other_account(client):
    """A second signed-in account with one helper; the test client acts as the first one again afterwards."""
    first = app.dependency_overrides[current_uid]
    other = f"u_{uuid.uuid4().hex[:12]}"
    demo.start(other)
    app.dependency_overrides[current_uid] = app.dependency_overrides[owner_uid] = lambda: other
    try:
        return other, enrolled(client, "Elsewhere")
    finally:
        app.dependency_overrides[current_uid] = app.dependency_overrides[owner_uid] = first


def test_the_key_reaches_only_its_own_accounts_helpers(client, started):
    a, b = enrolled(client, "Mac"), enrolled(client, "NAS")
    key = beat(client, a["token"]).json()["netKey"]
    assert len(key) == 64 and set(key) <= set("0123456789abcdef")
    assert beat(client, b["token"]).json()["netKey"] == key  # one key per account: tags match across its devices
    assert key not in str(db.user(started).get().to_dict())  # not where browsers can read it
    other, dev = _other_account(client)
    assert beat(client, dev["token"]).json()["netKey"] != key


def test_malformed_fingerprints_are_refused(client, started):
    dev = enrolled(client)
    for net in ({"self": "192.168.1.5"}, {"self": "A" * 20}, {"gateway": "a" * 21},
                {"peers": [{"tag": NAS, "why": "service:22"}]}, {"peers": [{"tag": NAS, "why": "backup"}]},
                {"peers": [{"tag": NAS, "why": "time_machine", "ip": "192.168.1.9"}]},
                {"peers": [{"tag": f"{i:020x}", "why": "network_drive"} for i in range(21)]}, {"mac": "x"}):
        assert beat(client, dev["token"], {**FACTS, "net": net}).status_code == 422, net


def test_time_machine_and_services_become_lines(client, started):
    mac, nas, pi = enrolled(client, "Mac"), enrolled(client, "NAS"), enrolled(client, "Pi")
    _report(client, mac, _net(MAC, peers=[(NAS, "time_machine"), (NAS, "service:445"), ("e" * 20, "network_drive")]))
    assert _links(started) == {}  # the NAS hasn't said who it is yet
    _report(client, pi, _net(PI, peers=[(NAS, "service:5432")]))
    _report(client, nas, _net(NAS))
    got = _links(started)
    backup = got[f"{mac['deviceId']}__{nas['deviceId']}"]
    assert (backup["kind"], backup["source"], backup["why"]) == ("backup", "auto", "Time Machine backs up here")
    db_line = got[f"{pi['deviceId']}__{nas['deviceId']}"]
    assert db_line["kind"] == "depends" and "PostgreSQL" in db_line["why"]
    assert len(got) == 2  # the unknown share isn't on the map; the shared router isn't either
    text = agentlib.fleet_summary(started, generation(started))
    assert "(seen by its helper: Time Machine backs up here)" in text
    assert "are on the same home network (the router isn't on the map" in text


def test_a_router_added_from_found_nearby_gets_network_lines(client, started):
    mac, nas = enrolled(client, "Mac"), enrolled(client, "NAS")
    _report(client, mac, _net(MAC))
    _report(client, nas, _net(NAS))
    h = {"X-Device-Token": mac["token"]}
    router = {**ITEM, "guess": "Device with a web page", "vendor": None, "services": ["web page"], "ports": [80],
              "tag": ROUTER}
    assert client.post("/helper/discoveries", json={"items": [router]}, headers=h).status_code == 200
    rid = client.post(f"/api/discoveries/{mac['deviceId']}/{ITEM['cid']}/add", json={"name": "Router"}).json()["deviceId"]
    assert db.device(started, rid).get().to_dict()["net"] == {"self": ROUTER}
    got = _links(started)
    assert {k for k, v in got.items() if v["kind"] == "network"} == {f"{mac['deviceId']}__{rid}",
                                                                       f"{nas['deviceId']}__{rid}"}
    assert "same home network" not in agentlib.fleet_summary(started, generation(started))


def test_lines_the_person_drew_or_deleted_are_left_alone(client, started):
    mac, nas, pi = enrolled(client, "Mac"), enrolled(client, "NAS"), enrolled(client, "Pi")
    _report(client, nas, _net(NAS))
    m, n, p = mac["deviceId"], nas["deviceId"], pi["deviceId"]
    assert client.post("/api/links", json={"from": m, "to": n, "kind": "depends"}).json()["source"] == "user"
    assert client.post("/api/links", json={"from": n, "to": p, "kind": "power"}).status_code == 201  # reverse pair
    _report(client, mac, _net(MAC, peers=[(NAS, "time_machine")]))
    _report(client, pi, _net(PI, peers=[(NAS, "service:1883")]))
    got = _links(started)
    assert got[f"{m}__{n}"]["kind"] == "depends" and got[f"{m}__{n}"]["source"] == "user"  # never re-kinded
    assert f"{p}__{n}" not in got  # the person already drew a line between these two
    db.links(started).document(f"{n}__{p}").delete()
    links.infer(started)
    assert got_auto(started) == {f"{p}__{n}"}
    assert client.delete(f"/api/links/{p}__{n}").status_code == 200
    _report(client, pi, _net(PI, peers=[(NAS, "service:1883"), (NAS, "service:445")]))  # seen again, still dismissed
    assert links.infer(started) == 0 and got_auto(started) == set()


def got_auto(uid):
    return {k for k, v in _links(uid).items() if v.get("source") == "auto"}


def test_fingerprints_never_match_across_accounts(client, started):
    mac = enrolled(client, "Mac")
    _report(client, mac, _net(MAC, peers=[(NAS, "time_machine")]))
    other, dev = _other_account(client)
    _report(client, dev, _net(NAS, gateway=MAC))  # the same strings in another account mean nothing here
    assert _links(started) == {} and _links(other) == {}


def test_an_older_helper_keeps_the_stored_fingerprints(client, started):
    dev = enrolled(client)
    _report(client, dev, _net(PI))
    _report(client, dev, FACTS)  # no `net`: before 0.9.20
    assert db.device(started, dev["deviceId"]).get().to_dict()["net"]["self"] == PI


def test_a_failed_attempt_is_retried_by_a_later_identical_report(client, started, monkeypatch):  # codex auto_links #1
    mac, nas = enrolled(client, "Mac"), enrolled(client, "NAS")
    _report(client, nas, _net(NAS))
    real_infer, calls = links.infer, []

    def broken_once(uid):
        calls.append(uid)
        if len(calls) == 1:
            raise RuntimeError("Firestore hiccup")
        return real_infer(uid)
    monkeypatch.setattr(links, "infer", broken_once)
    _report(client, mac, _net(MAC, peers=[(NAS, "time_machine")]))
    assert not _links(started)  # the first attempt failed after the fingerprints were stored
    monkeypatch.setattr(links, "RETRY_SECONDS", 0)
    _report(client, mac, _net(MAC, peers=[(NAS, "time_machine")]))  # nothing changed, but lines are still due
    assert any(l["kind"] == "backup" for l in _links(started).values())
    calls.clear()
    _report(client, mac, _net(MAC, peers=[(NAS, "time_machine")]))  # done now: no more work per report
    assert not calls
