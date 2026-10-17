"""Regressions for Codex's slice-1 review (H1, H2, M1-M4, failed-run version policy)."""

import threading

import pytest
from fastapi.testclient import TestClient

from nightlight_api import actions, config, db, demo
from nightlight_api.errors import ApiError
from nightlight_api.main import app
from conftest import device, propose, trust


def _fail_next(uid):
    demo.inject(uid, "logs_locked", "pi-1")


@pytest.mark.parametrize("target", [{"deviceId": "pi-1"}, {"deviceId": "pi-1", "svcId": "teslamate"}])
def test_failure_demotes_unpinned_scoped_grant(client, started, target):  # H1
    uid = started
    assert client.put("/api/trust/rotate_logs", json={"level": "auto", **target}).status_code == 200
    _fail_next(uid)
    assert propose(uid)["status"] == "failed"
    nxt = propose(uid)
    assert nxt["status"] == "pending"  # the scoped "just handle it" no longer runs on its own


def test_pinned_scoped_grant_survives_failure(client, started):  # H1, explicit pin policy
    uid = started
    client.put("/api/trust/rotate_logs", json={"level": "auto", "deviceId": "pi-1", "pinned": True})
    _fail_next(uid)
    assert propose(uid)["status"] == "failed"
    assert device(uid)["trustOverride"]["rotate_logs"] == "auto"
    assert propose(uid)["status"] == "done"


def _earn_offer(uid):
    for _ in range(3):
        demo.inject(uid, "disk_full", "pi-1")
        actions.decide(uid, propose(uid)["id"], "approve")
    return trust(uid)["offer"]["offerId"]


def test_stale_card_withdraws_offer_once(client, started):  # H2
    uid = started
    offer = _earn_offer(uid)
    card = propose(uid)
    demo.inject(uid, "disk_full", "pi-1")  # device changes under the open card
    for _ in range(2):
        with pytest.raises(ApiError) as e:
            actions.decide(uid, card["id"], "approve")
        assert e.value.code == "stale"
    assert trust(uid)["failures"] == 1 and trust(uid)["offer"] is None  # once, not per replay
    r = client.post("/api/trust/rotate_logs/promotion", json={"accept": True, "offerId": offer})
    assert r.status_code == 409 and r.json()["code"] == "offer_obsolete"


def test_old_generation_tombstone_leaves_new_trust_alone(started):  # H2
    uid = started
    card = propose(uid)
    demo.reset(uid)
    with pytest.raises(ApiError):
        actions.decide(uid, card["id"], "approve")
    assert trust(uid)["failures"] == 0


@pytest.mark.parametrize("path,body", [
    ("/api/demo/inject", {"kind": "meteor", "deviceId": "pi-1"}),
    ("/api/demo/inject", {"kind": "disk_full", "deviceId": ""}),
    ("/api/demo/inject", {"kind": "disk_full", "deviceId": "a/b"}),
    ("/api/demo/inject", {"kind": "disk_full", "deviceId": "router-1"}),  # incident doesn't apply
    ("/api/demo/start", {"template": "castle"}),
])
def test_invalid_bodies_use_documented_422(client, started, path, body):  # M1
    r = client.post(path, json=body)
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error" and r.json()["code"] == "invalid_body" and r.json()["detail"]


@pytest.mark.parametrize("body", [{"level": "auto", "svcId": "teslamate"}, {"level": "auto", "deviceId": ""}])
def test_trust_target_validation(client, started, body):  # M1
    r = client.put("/api/trust/rotate_logs", json=body)
    assert r.status_code == 422 and r.json()["code"] == "invalid_body"
    assert trust(started)["level"] == "ask"  # nothing fell through to a type-wide change


def test_malformed_action_id_is_not_found(client, started):  # M1
    r = client.post("/api/actions/..%2Fsecret/decide", json={"decision": "approve"})
    assert r.status_code == 404


def test_cors_origins_accept_spaces_and_commas(monkeypatch):  # M2
    monkeypatch.setenv("WEB_ORIGINS", "https://web.example http://localhost:3000,https://b.example")
    assert config._list("WEB_ORIGINS") == ["https://web.example", "http://localhost:3000", "https://b.example"]
    c = TestClient(app)
    allowed = c.options("/api/demo/start", headers={"Origin": "http://localhost:3000",
                                                     "Access-Control-Request-Method": "POST",
                                                     "Access-Control-Request-Headers": "authorization"})
    assert allowed.status_code == 200 and allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    denied = c.options("/api/demo/start", headers={"Origin": "https://evil.example",
                                                    "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in denied.headers


def test_barrier_answers_resetting_mid_cleanup(client, started):  # M3
    uid = started
    offer = _earn_offer(uid)
    gate, release = threading.Event(), threading.Event()

    def hook(stage):
        if stage == "seed":  # devices and trust are deleted, not yet re-seeded
            gate.set()
            release.wait(10)

    t = threading.Thread(target=lambda: demo.reset(uid, hook=hook))
    t.start()
    assert gate.wait(10)
    try:
        assert not db.device(uid, "pi-1").get().exists
        r = client.post("/api/demo/inject", json={"kind": "disk_full", "deviceId": "pi-1"})
        assert r.status_code == 409 and r.json()["code"] == "resetting"
        r = client.post("/api/trust/rotate_logs/promotion", json={"accept": True, "offerId": offer})
        assert r.status_code == 409 and r.json()["code"] == "resetting"
        with pytest.raises(ApiError) as e:
            propose(uid)
        assert e.value.code == "resetting"
    finally:
        release.set()
        t.join(10)


def test_declined_offer_is_not_repeated(client, started):  # M4
    uid = started
    offer = _earn_offer(uid)
    r = client.post("/api/trust/rotate_logs/promotion", json={"accept": False, "offerId": offer})
    assert r.status_code == 200 and r.json()["level"] == "ask"
    demo.inject(uid, "disk_full", "pi-1")
    actions.decide(uid, propose(uid)["id"], "approve")
    assert trust(uid)["offer"] is None  # offered once; not again for this track record


def test_failed_run_keeps_device_version(started):  # open question: failure changes nothing on the device
    uid = started
    _fail_next(uid)  # injecting the failure itself changes the device, so open cards come after it
    other = propose(uid, turn="turn_other", device="game-1")  # a different open card (same job twice is one card)
    before = device(uid)["version"]
    failed = propose(uid)
    actions.decide(uid, failed["id"], "approve")
    assert device(uid)["version"] == before and "simFailNext" not in device(uid)
    assert actions.decide(uid, other["id"], "approve")[0] == 202  # sibling card still valid
