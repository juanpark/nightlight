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


def _answer(monkeypatch, code=200, fail=False):
    def get(url, **kw):
        if fail:
            raise httpx.ConnectError("down")
        return httpx.Response(code)
    monkeypatch.setattr(watch.httpx, "get", get)


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


def test_sweep_needs_the_schedulers_signed_token(client):
    assert client.post("/internal/sweep").status_code == 401
    assert client.post("/internal/sweep", headers={"Authorization": "Bearer forged"}).status_code == 401
