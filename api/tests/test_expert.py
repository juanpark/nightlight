"""Expert sessions: commands run only with the owner's passkey signature, checked again on the device."""

import hashlib
import importlib.util
import json
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from nightlight_api import actions, db, expert, real
from conftest import generation
from test_real import FACTS, beat, enrolled

ORIGIN, RP = "https://nightlight.example", "nightlight.example"
EXPERT = {**FACTS, "allowedJobs": {"expert": ["on"]}}


class Passkey:
    """Signs like a browser authenticator (ES256): authenticatorData || sha256(clientDataJSON)."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        pub = self.key.public_key()
        self.pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        n = pub.public_numbers()
        self.cose = bytes([0xA5, 0x01, 0x02, 0x03, 0x26, 0x20, 0x01, 0x21, 0x58, 0x20]) + n.x.to_bytes(32, "big") \
            + bytes([0x22, 0x58, 0x20]) + n.y.to_bytes(32, "big")

    def sign(self, challenge, origin=ORIGIN, rp=RP, flags=0x05):
        auth = hashlib.sha256(rp.encode()).digest() + bytes([flags]) + (1).to_bytes(4, "big")
        client = json.dumps({"type": "webauthn.get", "challenge": challenge, "origin": origin}).encode()
        sig = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"authenticatorData": expert.b64u(auth), "clientDataJSON": expert.b64u(client),
                "signature": expert.b64u(sig)}


@pytest.fixture
def owner(client, started):
    pk = Passkey()
    expert._ref(started).set({"pem": pk.pem, "cose": expert.b64u(pk.cose), "credentialId": "cred", "rpId": RP,
                              "origin": ORIGIN, "fingerprint": "ABCD-1234"})
    dev = enrolled(client)
    beat(client, dev["token"], EXPERT)
    return started, dev, pk


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


def test_a_command_needs_the_passkey_not_a_tap(client, owner):
    uid, dev, pk = owner
    a = actions.propose(uid, session_id="sess_test", turn_id="t1", generation=generation(uid),
                        action_type="expert_command", device_id=dev["deviceId"], params={"command": "brew cleanup"})
    assert a["status"] == "pending" and a["riskClass"] == "destructive"
    assert client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"}).json()["code"] == "needs_passkey"
    bad = pk.sign(a["params"]["challenge"], origin="https://evil.example")
    assert client.post(f"/api/actions/{a['id']}/sign", json=bad).status_code == 422
    assert client.post(f"/api/actions/{a['id']}/sign", json=pk.sign(a["params"]["challenge"])).json()["status"] \
        == "approved"
    _again(dev["token"])
    job = beat(client, dev["token"], EXPERT).json()["jobs"][0]
    assert job["type"] == "expert_command" and job["params"]["payload"]["command"] == "brew cleanup"


def test_a_signed_grant_unlocks_read_only_commands(client, owner):
    uid, dev, pk = owner
    with pytest.raises(ValueError, match="no_investigation"):
        actions.request_read_command(uid, session_id="sess_test", turn_id="t2", generation=generation(uid),
                                     device_id=dev["deviceId"], command="df -h")
    g = actions.propose(uid, session_id="sess_test", turn_id="t3", generation=generation(uid),
                        action_type="expert_grant", device_id=dev["deviceId"], params={"why": "find the crash"})
    assert client.post(f"/api/actions/{g['id']}/sign", json=pk.sign(g["params"]["challenge"])).json()["status"] \
        == "done"
    a = actions.request_read_command(uid, session_id="sess_test", turn_id="t4", generation=generation(uid),
                                     device_id=dev["deviceId"], command="df -h")
    assert a["status"] == "approved" and a["params"]["grant"]["mode"] == "read-only"


def test_devices_without_expert_sessions_get_no_cards(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], FACTS)
    with pytest.raises(ValueError, match="not_allowed_on_device"):
        actions.propose(started, session_id="sess_test", turn_id="t5", generation=generation(started),
                        action_type="expert_command", device_id=dev["deviceId"], params={"command": "ls"})


# ------------------------------------------------------------------ the helper side

SPEC = importlib.util.spec_from_file_location(
    "nightlight_helper", Path(__file__).resolve().parents[2] / "helper" / "nightlight_helper.py")


@pytest.fixture
def helper(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHTLIGHT_HOME", str(tmp_path / "cfg"))
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    monkeypatch.setattr(mod, "APP_DIR", str(tmp_path / "app"))
    return mod


def _pinned(helper, pk):
    helper._save_config({"token": "t" * 43, "deviceId": "dev_x",
                         "expert": {"pem": pk.pem, "rpId": RP, "origin": ORIGIN, "fingerprint": "x"}})


def _signed_command(pk, command="uname", device="dev_x", expires=None, **kw):
    payload = {"device": device, "command": command, "expires": expires or int(time.time()) + 600,
               "nonce": str(time.time_ns())}
    return payload, pk.sign(expert.challenge_for(payload), **kw)


def test_device_runs_only_what_the_passkey_signed(helper):
    pk = Passkey()
    _pinned(helper, pk)
    payload, signed = _signed_command(pk)
    ok, summary, out = helper.run_job({"type": "expert_command", "params": {"payload": payload, "signed": signed}})
    assert ok and "exit code 0" in summary and out
    again = helper.run_job({"type": "expert_command", "params": {"payload": payload, "signed": signed}})
    assert not again[0] and "already used" in again[1]
    tampered = dict(payload, command="rm -rf ~", nonce="n2")
    assert "different command" in helper.expert_check(tampered, signed, helper._load())
    p2, s2 = _signed_command(pk, device="dev_other")
    assert "another device" in helper.expert_check(p2, s2, helper._load())
    p3, s3 = _signed_command(pk, expires=int(time.time()) - 1)
    assert "expired" in helper.expert_check(p3, s3, helper._load())
    p4, s4 = _signed_command(pk, flags=0x01)
    assert "didn't verify the person" in helper.expert_check(p4, s4, helper._load())
    other = Passkey()
    p5, s5 = _signed_command(other)
    assert "didn't check out" in helper.expert_check(p5, s5, helper._load())


def test_device_without_a_pinned_passkey_refuses(helper):
    helper._save_config({"token": "t" * 43, "deviceId": "dev_x"})
    pk = Passkey()
    payload, signed = _signed_command(pk)
    ok, summary, _ = helper.run_job({"type": "expert_command", "params": {"payload": payload, "signed": signed}})
    assert not ok and "aren't switched on" in summary


def test_investigation_grant_allows_only_read_only_commands(helper):
    pk = Passkey()
    _pinned(helper, pk)
    grant = {"device": "dev_x", "mode": "read-only", "expires": int(time.time()) + 600, "nonce": "g1"}
    signed = pk.sign(expert.challenge_for(grant))
    run = lambda cmd: helper.run_job({"type": "expert_read", "params": {"grant": grant, "signed": signed,
                                                                          "command": cmd}})
    assert run("uname")[0] and run("uname")[0]  # reusable until it expires
    assert "isn't on this device's read-only list" in run("rm -rf /tmp/x")[1]
    assert "no pipes" in run("uname; rm x")[1]
    assert "secrets" in run("cat ~/.ssh/id_rsa")[1]
