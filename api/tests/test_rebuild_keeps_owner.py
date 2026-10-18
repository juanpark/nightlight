"""A sample-home rebuild (start, template switch, reset) never deletes the owner's own use of Nightlight: only a pure
sample visitor (anonymous, no real device) starts over with no chats."""
import uuid

import pytest
from fastapi.testclient import TestClient

from nightlight_api import db, demo, memory, turns
from nightlight_api.auth import anonymous, current_uid, owner_uid
from nightlight_api.main import app


def _gen(uid):
    return db.user(uid).get().to_dict()["demoGeneration"]


def _chats(client, uid, n=2):
    out = []
    for i in range(n):
        sid = client.post("/api/chat/sessions", json={}).json()["sessionId"]
        turn_id = turns.accept_message(uid, sid, f"question {i}", str(uuid.uuid4()))
        out.append((sid, turn_id))
    return out


def _counts(uid, chats):
    return {
        "sessions": sum(db.session(uid, sid).get().exists for sid, _ in chats),
        "messages": sum(len(db.messages(uid, sid).get()) for sid, _ in chats),
        "turns": sum(len(db.turns(uid, sid).get()) for sid, _ in chats),
        "turnIndex": sum(turns.turn_index(uid, t).get().exists for _, t in chats),
    }


@pytest.fixture
def forgets(monkeypatch):
    calls = []
    monkeypatch.setattr(memory, "forget_all", lambda uid: calls.append(uid) or True)
    return calls


def _real_device(uid):
    db.device(uid, "dev_real").set({"name": "My NAS", "realm": "real", "simulated": False, "version": 1})


def test_signed_in_owner_keeps_chats_across_template_switch_and_reset(client, uid, forgets):
    assert client.post("/api/demo/start", json={"template": "empty"}).status_code == 200
    _real_device(uid)
    chats = _chats(client, uid)
    sid0 = chats[0][0]
    db.actions(uid).document("act_card").set({"type": "restart_service", "deviceId": "pi", "status": "pending",
                                              "realm": "sim", "sessionId": sid0, "demoGeneration": _gen(uid)})
    before = _counts(uid, chats)
    assert before == {"sessions": 2, "messages": 2, "turns": 2, "turnIndex": 2}

    assert client.post("/api/demo/template", json={"template": "home-pi"}).status_code == 200
    assert _counts(uid, chats) == before
    assert client.post("/api/demo/reset", json={}).status_code == 200
    assert _counts(uid, chats) == before
    assert forgets == []  # the owner's memories are theirs
    assert db.device(uid, "dev_real").get().exists

    gen = _gen(uid)
    for sid, _ in chats:  # carried into the new generation: listed by the chat and still usable
        s = db.session(uid, sid).get().to_dict()
        assert s["demoGeneration"] == gen and s["activeTurn"] is None
    turns.accept_message(uid, sid0, "and now?", str(uuid.uuid4()))
    assert len(db.messages(uid, sid0).get()) == 2
    # a card about the old sample home is withdrawn, not left live
    assert db.action(uid, "act_card").get().to_dict()["status"] == "stale"


def test_signed_in_owner_without_real_devices_keeps_chats(client, started, forgets):
    uid = started
    chats = _chats(client, uid, 1)
    assert client.post("/api/demo/reset", json={}).status_code == 200
    assert _counts(uid, chats)["messages"] == 1 and forgets == []


def test_direct_call_defaults_to_keeping(client, started, forgets):
    uid = started
    chats = _chats(client, uid, 1)
    demo.reset(uid)  # no flag: fail safe
    assert _counts(uid, chats)["sessions"] == 1 and forgets == []


@pytest.fixture
def anon_client(uid):
    app.dependency_overrides[current_uid] = lambda: uid
    app.dependency_overrides[owner_uid] = lambda: uid
    app.dependency_overrides[anonymous] = lambda: True
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_anonymous_visitor_reset_clears_its_chats(anon_client, uid, forgets):
    assert anon_client.post("/api/demo/start", json={"template": "home-pi"}).status_code == 200
    chats = _chats(anon_client, uid)
    assert anon_client.post("/api/demo/reset", json={}).status_code == 200
    assert _counts(uid, chats) == {"sessions": 0, "messages": 0, "turns": 0, "turnIndex": 0}
    assert forgets == [uid]


def test_anonymous_account_with_a_real_device_keeps_chats(anon_client, uid, forgets):
    assert anon_client.post("/api/demo/start", json={"template": "home-pi"}).status_code == 200
    _real_device(uid)
    chats = _chats(anon_client, uid)
    assert anon_client.post("/api/demo/template", json={"template": "empty"}).status_code == 200
    assert _counts(uid, chats)["sessions"] == 2 and forgets == []
