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


def test_read_only_rules_close_the_reviewed_escapes(helper, tmp_path):  # review expert #1, #2
    fake = tmp_path / "uname"
    fake.write_text("#!/bin/sh\ntouch /tmp/nl_pwned\n")
    fake.chmod(0o755)
    for bad in ("docker system prune --force --volumes", "ip link set eth0 down", f"{fake}", "file -f/etc/hosts",
                "cat /etc/hosts", "grep -r x /var/log", "du -sh /tmp; rm x", "tail -f /var/log/system.log",
                "ps aux --forest=$(id)"):
        assert helper.readonly_ok(bad) is not None, bad
    argv, why = helper.readonly_command("uname -a")
    assert why is None and argv[0] in ("/bin/uname", "/usr/bin/uname")  # a system program, never one named by path


def test_fingerprint_is_worked_out_on_the_device(helper):  # review expert #3
    pk = Passkey()
    der = serialization.load_pem_public_key(pk.pem.encode()).public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    assert helper.key_fingerprint(pk.pem) == expert._fingerprint(der)
    assert len(helper.key_fingerprint(pk.pem)) == 19 and helper.key_fingerprint(Passkey().pem) != expert._fingerprint(der)


def test_a_signature_runs_once_even_after_many_others(helper):  # review expert #5
    pk = Passkey()
    _pinned(helper, pk)
    helper._update_config(lambda c: c.__setitem__("usedNonces", {f"old{i}": int(time.time()) + 600 for i in range(300)}))
    payload, signed = _signed_command(pk)
    assert helper.run_job({"type": "expert_command", "params": {"payload": payload, "signed": signed}})[0]
    again = helper.run_job({"type": "expert_command", "params": {"payload": payload, "signed": signed}})
    assert not again[0] and "already used" in again[1]
    assert payload["nonce"] in helper._load()["usedNonces"]


def test_stricter_webauthn_checks(helper):  # review expert #6
    pk = Passkey()
    _pinned(helper, pk)
    payload = {"device": "dev_x", "command": "uname", "expires": int(time.time()) + 600, "nonce": "c1"}
    auth = hashlib.sha256(RP.encode()).digest() + bytes([0x05]) + (1).to_bytes(4, "big")
    for client in ({"type": "webauthn.get", "challenge": expert.challenge_for(payload), "origin": ORIGIN,
                    "crossOrigin": True},
                   {"type": "webauthn.get", "challenge": expert.challenge_for(payload), "origin": ORIGIN,
                    "topOrigin": "https://evil.example"}):
        raw = json.dumps(client).encode()
        sig = pk.key.sign(auth + hashlib.sha256(raw).digest(), ec.ECDSA(hashes.SHA256()))
        signed = {"authenticatorData": expert.b64u(auth), "clientDataJSON": expert.b64u(raw),
                  "signature": expert.b64u(sig)}
        assert "another site" in helper.expert_check(payload, signed, helper._load())
    p2, s2 = _signed_command(pk, flags=0x15)  # backed up (0x10) without backup-eligible (0x08)
    assert "inconsistent" in helper.expert_check(p2, s2, helper._load())


def test_the_card_signs_exactly_the_payload_it_shows(client, owner):  # review expert #4
    uid, dev, pk = owner
    a = actions.propose(uid, session_id="sess_test", turn_id="t9", generation=generation(uid),
                        action_type="expert_command", device_id=dev["deviceId"], params={"command": "uname"})
    db.action(uid, a["id"]).update({"params.challenge": "forged"})  # a server lying about the challenge changes nothing
    signed = pk.sign(expert.challenge_for(a["params"]["payload"]))
    assert client.post(f"/api/actions/{a['id']}/sign", json=signed).json()["status"] == "approved"


def test_rev2_reads_without_environment_dumps(helper):  # rev2 #1
    for bad in ("docker inspect app", "systemctl show ssh", "launchctl print gui/501/x", "ps aux", "ps -ef"):
        assert helper.readonly_ok(bad) is not None, bad
    assert helper.readonly_ok("ps -axo pid,pcpu,pmem,comm") is None


def test_rev2_a_grant_can_not_be_stretched(helper):  # rev2 #2
    pk = Passkey()
    _pinned(helper, pk)
    long = {"device": "dev_x", "mode": "read-only", "expires": int(time.time()) + 365 * 86400, "nonce": "g"}
    assert "too long" in helper.expert_check(long, pk.sign(expert.challenge_for(long)), helper._load(), reusable=True)


def test_rev2_old_nonce_lists_are_kept(helper):  # rev2 #3
    pk = Passkey()
    _pinned(helper, pk)
    payload, signed = _signed_command(pk)
    helper._update_config(lambda c: c.__setitem__("usedNonces", [payload["nonce"]]))  # consumed under 0.9.8
    p2, s2 = _signed_command(pk)
    assert helper.run_job({"type": "expert_command", "params": {"payload": p2, "signed": s2}})[0]  # migrates
    again = helper.run_job({"type": "expert_command", "params": {"payload": payload, "signed": signed}})
    assert not again[0] and "already used" in again[1]


def test_rev3_docker_listing_never_shows_container_commands(helper):  # rev3 #1
    assert helper.readonly_ok("docker ps --no-trunc") is not None
    argv, why = helper.readonly_command("docker ps -a")
    if why is None:  # docker installed here
        assert argv[-2:] == ["--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
    else:
        assert "isn't installed" in why


def test_registration_of_a_real_shaped_passkey(client, started):  # the path the browser takes
    import cbor2
    opts = expert.register_options(started, ORIGIN if ORIGIN in expert.settings.web_origins else None)
    rp_id, origin = opts["rp"]["id"], expert._ref(started).get().to_dict()["pending"]["origin"]
    pk = Passkey()
    cred_id = b"\x01" * 16
    auth = (hashlib.sha256(rp_id.encode()).digest() + bytes([0x45]) + (0).to_bytes(4, "big")
            + bytes(16) + len(cred_id).to_bytes(2, "big") + cred_id + pk.cose)
    att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
    client_data = json.dumps({"type": "webauthn.create", "challenge": opts["challenge"], "origin": origin}).encode()
    credential = {"id": expert.b64u(cred_id), "rawId": expert.b64u(cred_id), "type": "public-key",
                  "response": {"clientDataJSON": expert.b64u(client_data), "attestationObject": expert.b64u(att)}}
    r = client.post("/api/expert/register", json=credential)
    assert r.status_code == 200, r.text
    der = serialization.load_pem_public_key(pk.pem.encode()).public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    assert r.json()["fingerprint"] == expert._fingerprint(der)  # the same code the browser and the device compute
    assert expert.status(started)["enabled"]
