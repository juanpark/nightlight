"""Keeping watch: history points, devices that go silent, watched web addresses, the scheduled sweep."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from nightlight_api import db, real, watch
from test_real import FACTS, beat, enrolled


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


@pytest.fixture
def dns(monkeypatch):
    table = {"example.org": "93.184.216.34", "internal.example": "10.0.0.5", "meta.example": "169.254.169.254"}

    def fake(host, port, *a, **k):
        ip = table.get(host, host)
        return [(2, 1, 6, "", (ip, port))]
    monkeypatch.setattr(watch.socket, "getaddrinfo", fake)
    return table


SEEN = []


def _answer(monkeypatch, code=200, fail=False):
    def handler(request):
        SEEN.append(request)
        if fail:
            raise httpx.ConnectError("down")
        return httpx.Response(code, content=b"x" * 1_000_000)
    monkeypatch.setattr(watch, "_TRANSPORT", httpx.MockTransport(handler))


def test_history_is_written_at_most_every_five_minutes(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], FACTS)
    _again(dev["token"])
    beat(client, dev["token"], FACTS)
    hist = list(db.device(started, dev["deviceId"]).collection("history").get())
    assert len(hist) == 1 and hist[0].to_dict()["disk"] == FACTS["diskPct"] and hist[0].to_dict()["expiresAt"]


def test_a_device_that_goes_silent_is_noticed_once_and_welcomed_back(client, started):
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], FACTS)
    db.device(started, dev["deviceId"]).update({"lastSeen": datetime.now(timezone.utc) - timedelta(minutes=9)})
    assert watch.sweep()["newlySilent"] >= 1
    evs = [e.to_dict() for e in db.events(started).get()]
    assert sum(1 for e in evs if e["kind"] == "silent") == 1
    _again(dev["token"])
    beat(client, dev["token"], FACTS)
    assert any(e.to_dict()["kind"] == "back" for e in db.events(started).get())
    assert db.device(started, dev["deviceId"]).get().to_dict().get("watchState") is None


def test_watched_addresses_must_be_public(client, started, dns, monkeypatch):
    _answer(monkeypatch)
    for url, code in (("ftp://example.org", "bad_url"), ("http://internal.example/", "private_address"),
                      ("http://meta.example/computeMetadata", "private_address"), ("http://127.0.0.1", "private_address"),
                      ("https://user:pw@example.org", "bad_url")):
        r = client.post("/api/watches", json={"name": "x", "url": url})
        assert r.status_code == 422 and r.json()["detail"][0]["msg"] == code, url


def test_watch_status_changes_are_recorded(client, started, dns, monkeypatch):
    _answer(monkeypatch, 200)
    wid = client.post("/api/watches", json={"name": "Our website", "url": "https://example.org"}).json()["id"]
    w = watch.watches(started).document(wid).get().to_dict()
    assert w["status"] == "ok" and w["httpStatus"] == 200
    _answer(monkeypatch, fail=True)
    watch.check_one(started, wid)
    assert watch.watches(started).document(wid).get().to_dict()["status"] == "crit"
    assert any(e.to_dict()["kind"] == "watch_crit" for e in db.events(started).get())
    assert client.delete(f"/api/watches/{wid}").status_code == 200
    assert not watch.watch_registry().document(f"{started}__{wid}").get().exists


def test_watch_limit(client, started, dns, monkeypatch):
    _answer(monkeypatch)
    monkeypatch.setattr(watch, "WATCHES_PER_USER", 2)
    for i in range(2):
        assert client.post("/api/watches", json={"name": f"w{i}", "url": "https://example.org"}).status_code == 201
    assert client.post("/api/watches", json={"name": "w3", "url": "https://example.org"}).status_code == 429


def test_probe_connects_to_the_checked_address_and_skips_the_body(started, dns, monkeypatch):  # review 11 #1,#2
    _answer(monkeypatch, 204)
    SEEN.clear()
    assert watch.probe("https://example.org/status")[0:2] == ("ok", 204)
    req = SEEN[-1]
    assert req.url.host == "93.184.216.34" and req.headers["host"] == "example.org"
    assert req.extensions.get("sni_hostname") == "example.org"
    dns["example.org"] = "169.254.169.254"  # the name now points somewhere private
    SEEN.clear()
    assert watch.probe("https://example.org/status")[0] == "crit" and SEEN == []  # never connected


def test_watch_budgets_malformed_urls_and_atomic_removal(client, started, dns, monkeypatch):  # review 11 #3-#5
    _answer(monkeypatch)
    r = client.post("/api/watches", json={"name": "x", "url": "https://example.org:notaport/"})
    assert r.status_code == 422 and r.json()["detail"][0]["msg"] == "bad_url"
    monkeypatch.setattr(watch, "WATCH_ADDS_PER_DAY", 1)
    wid = client.post("/api/watches", json={"name": "a", "url": "https://example.org"}).json()["id"]
    assert client.post("/api/watches", json={"name": "b", "url": "https://example.org"}).json()["code"] == "watch_budget"
    client.delete(f"/api/watches/{wid}")
    assert not watch.watch_registry().document(f"{started}__{wid}").get().exists


def test_old_watches_retire_and_left_devices_leave_the_registry(client, started, dns, monkeypatch):  # review 11 #3,#4
    _answer(monkeypatch)
    wid = client.post("/api/watches", json={"name": "a", "url": "https://example.org"}).json()["id"]
    watch.watches(started).document(wid).update({"expiresAt": datetime.now(timezone.utc) - timedelta(seconds=1)})
    dev = enrolled(client)
    client.post("/helper/leave", json={}, headers={"X-Device-Token": dev["token"]})
    assert not watch.registry().document(f"{started}__{dev['deviceId']}").get().exists
    watch.sweep()
    assert not watch.watches(started).document(wid).get().exists


def test_sweep_needs_the_schedulers_signed_token(client):
    assert client.post("/internal/sweep").status_code == 401
    assert client.post("/internal/sweep", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_probe_has_a_hard_deadline(monkeypatch):  # review 11 rev2 #1
    import time as _t
    monkeypatch.setattr(watch, "PROBE_BUDGET", 0.2)
    import asyncio

    async def stuck(url):
        await asyncio.sleep(1.5)
        return "ok", 200, 1
    monkeypatch.setattr(watch, "_aprobe", stuck)
    t = _t.monotonic()
    assert watch.probe("https://example.org")[0] == "crit" and _t.monotonic() - t < 1


def test_every_watch_gets_its_turn_and_legacy_ones_are_counted(client, started, dns, monkeypatch):  # rev2 #2,#3
    _answer(monkeypatch)
    ids = [client.post("/api/watches", json={"name": f"w{i}", "url": "https://example.org"}).json()["id"]
           for i in range(3)]
    legacy = watch.watches(started).document("w_legacy")
    legacy.set({"name": "old", "url": "https://example.org/", "status": "unknown", "tags": []})
    watch.watch_registry().document(f"{started}__w_legacy").set({"uid": started, "watchId": "w_legacy"})
    monkeypatch.setattr(watch, "WATCHES_TOTAL", 1)
    seen = []
    real_check = watch.check_one
    monkeypatch.setattr(watch, "check_one", lambda uid, wid: (seen.append(wid), real_check(uid, wid))[1])
    for _ in range(8):
        watch.sweep()
    assert set(ids) | {"w_legacy"} <= set(seen)
    assert legacy.get().to_dict()["counted"] is True and legacy.get().to_dict()["expiresAt"]



def test_counter_heals_from_the_registry(client, started, dns, monkeypatch):  # review 11 rev3 #2
    _answer(monkeypatch)
    client.post("/api/watches", json={"name": "a", "url": "https://example.org"})
    db.client().collection("watchStats").document("global").set({"active": 99})
    watch.sweep()
    rows = len(list(watch.watch_registry().stream()))
    assert db.client().collection("watchStats").document("global").get().to_dict()["active"] == rows


def test_a_slow_name_lookup_cannot_hold_the_probe(monkeypatch):  # review 11 rev4 #1
    import time as _t
    monkeypatch.setattr(watch, "PROBE_BUDGET", 0.1)
    monkeypatch.setattr(watch, "_resolve", lambda url: (_t.sleep(1.0), None)[1])
    t = _t.monotonic()
    assert watch.probe("https://example.org")[0] == "crit" and _t.monotonic() - t < 0.6



def test_a_late_name_lookup_is_dropped_quietly(monkeypatch):  # review 11 rev5
    import threading
    import time as _t
    monkeypatch.setattr(watch, "PROBE_BUDGET", 0.05)
    errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))
    monkeypatch.setattr(watch, "_resolve", lambda url: (_t.sleep(0.3), (None, 0, "1.2.3.4"))[1])
    assert watch.probe("https://example.org")[0] == "crit"
    _t.sleep(0.5)  # let the lookup finish after the deadline
    assert errors == []
