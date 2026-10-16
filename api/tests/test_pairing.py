"""Pairing where the device shows a code (OAuth device-authorization pattern), self-revoke on uninstall, owner gate."""

import pytest
from fastapi.testclient import TestClient

from nightlight_api import db, real
from nightlight_api.auth import owner_uid
from nightlight_api.main import app
from test_real import FACTS, beat


def start(client, name="Mac"):
    r = client.post("/helper/pair/start", json={"name": name, "os": "macOS 26.6"})
    assert r.status_code == 201
    return r.json()


def poll(client, p, secret=None):
    return client.post("/helper/pair/poll", json={"code": p["code"], "pollSecret": secret or p["pollSecret"]})


def test_device_shows_code_owner_approves_device_gets_token_once(client, started):
    p = start(client)
    assert poll(client, p).status_code == 202  # waiting
    assert client.get(f"/api/devices/pair/{p['code']}").json()["name"] == "Mac"
    assert client.post(f"/api/devices/pair/{p['code']}", json={"approve": True}).status_code == 200
    assert poll(client, p, secret="x" * 43).status_code == 401  # someone else who saw the code
    r = poll(client, p)
    assert r.status_code == 200 and r.json()["token"]
    dev = r.json()
    d = db.device(started, dev["deviceId"]).get().to_dict()
    assert d["realm"] == "real" and d["name"] == "Mac"
    assert beat(client, dev["token"]).status_code == 200
    assert poll(client, p).status_code == 401  # only once
    stored = db.client().collection("pairRequests").document(real._sha(p["code"].replace("-", ""))).get()
    assert dev["token"] not in str(stored.to_dict())  # never stored in plaintext


def test_declined_unknown_and_expired_codes(client, started):
    from datetime import datetime, timedelta, timezone
    p = start(client)
    client.post(f"/api/devices/pair/{p['code']}", json={"approve": False})
    assert poll(client, p).status_code == 401
    assert client.post(f"/api/devices/pair/{p['code']}", json={"approve": True}).status_code == 409
    assert client.get("/api/devices/pair/ZZZZ-ZZZZ").status_code == 404
    q = start(client)
    db.client().collection("pairRequests").document(real._sha(q["code"].replace("-", ""))).update(
        {"expiresAt": datetime.now(timezone.utc) - timedelta(seconds=1)})
    assert client.get(f"/api/devices/pair/{q['code']}").status_code == 404
    assert poll(client, q).status_code == 401


def test_pair_requests_are_limited_per_address(client, started, monkeypatch):
    for d in db.client().collection("pairLimits").stream():  # other tests used this test client's address
        d.reference.delete()
    monkeypatch.setattr(real, "PAIR_PER_IP_HOUR", 2)
    start(client), start(client)
    assert client.post("/helper/pair/start", json={"name": "x"}).status_code == 429


def test_uninstall_revokes_the_device_itself(client, started):
    p = start(client)
    client.post(f"/api/devices/pair/{p['code']}", json={"approve": True})
    dev = poll(client, p).json()
    beat(client, dev["token"], FACTS)
    assert client.post("/helper/leave", json={}, headers={"X-Device-Token": dev["token"]}).status_code == 200
    assert beat(client, dev["token"]).status_code == 401
    assert real.view(db.device(started, dev["deviceId"]).get().to_dict())["staleReason"] == "revoked"
    assert client.post("/helper/leave", json={}, headers={"X-Device-Token": dev["token"]}).status_code == 401


def test_one_click_demo_accounts_cannot_add_real_devices(uid):
    def anonymous():
        from nightlight_api.errors import ApiError
        raise ApiError(403, "sign_in_required")
    app.dependency_overrides[owner_uid] = anonymous
    try:
        c = TestClient(app)
        assert c.post("/api/devices/enrol-code", json={}).json()["code"] == "sign_in_required"
        assert c.get("/api/devices/pair/ABCD-EFGH").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_owner_gate_reads_the_sign_in_provider(monkeypatch):
    from nightlight_api import auth
    from nightlight_api.errors import ApiError

    class Req:
        headers = {"authorization": "Bearer t"}
    monkeypatch.setattr(auth, "_app", lambda: None)
    monkeypatch.setattr(auth.fb_auth, "verify_id_token",
                        lambda t, app=None: {"uid": "u1", "firebase": {"sign_in_provider": "anonymous"}})
    with pytest.raises(ApiError):
        auth.owner_uid(Req())
    monkeypatch.setattr(auth.fb_auth, "verify_id_token",
                        lambda t, app=None: {"uid": "u1", "firebase": {"sign_in_provider": "google.com"}})
    assert auth.owner_uid(Req()) == "u1"
