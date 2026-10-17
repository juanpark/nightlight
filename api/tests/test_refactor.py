"""Regressions for the capability-registry refactor review (ADR 0001/0002)."""

import pytest

from nightlight_api import actions, db, demo, expert, release
from nightlight_api.config import settings
from conftest import generation
from test_real import FACTS, beat, enrolled
from test_real_jobs import ALLOW, _again


def test_updates_to_different_releases_are_different_actions(client, started, tmp_path, monkeypatch):  # #1
    d = tmp_path / "release"
    d.mkdir()
    monkeypatch.setattr(settings, "release_dir", str(d))
    dev = enrolled(client)
    beat(client, dev["token"], {**FACTS, "helperVersion": "0.9.0", "allowedJobs": {"update": ["signed"]}})
    ids = []
    for v in ("9.9.1", "9.9.2"):
        (d / "nightlight_helper.py").write_text(f'VERSION = "{v}"\n')
        (d / "nightlight_helper.py.sig").write_bytes(b"sig")
        release.latest.cache_clear()
        r = client.post(f"/api/devices/{dev['deviceId']}/update", json={})
        assert r.status_code == 202 and r.json()["version"] == v
        ids.append(r.json()["actionId"])
    release.latest.cache_clear()
    assert ids[0] != ids[1]


def test_a_grant_activates_with_its_card_or_not_at_all(client, started, monkeypatch):  # #2
    from test_expert import EXPERT, ORIGIN, RP, Passkey
    pk = Passkey()
    expert._ref(started).set({"pem": pk.pem, "cose": expert.b64u(pk.cose), "credentialId": "cred", "rpId": RP,
                              "origin": ORIGIN, "fingerprint": "x"})
    dev = enrolled(client)
    beat(client, dev["token"], EXPERT)
    g = actions.propose(started, session_id="sess_test", turn_id="tg", generation=generation(started),
                        action_type="expert_grant", device_id=dev["deviceId"], params={"why": "x"})
    monkeypatch.setattr(expert, "grant_write", lambda uid, a: (_ for _ in ()).throw(RuntimeError("write failed")))
    with pytest.raises(RuntimeError):
        client.post(f"/api/actions/{g['id']}/sign", json=pk.sign(g["params"]["challenge"]))
    assert db.action(started, g["id"]).get().to_dict()["status"] == "pending"  # nothing half-done; sign again
    monkeypatch.undo()
    assert client.post(f"/api/actions/{g['id']}/sign", json=pk.sign(g["params"]["challenge"])).json()["status"] == "done"
    assert expert.active_grant(started, dev["deviceId"])


def test_a_reset_never_hides_what_happened_on_a_real_device(client, started):  # #3
    dev = enrolled(client)
    beat(client, dev["token"], ALLOW)
    a = actions.propose(started, session_id="sess_test", turn_id="tr", generation=generation(started),
                        action_type="restart_container", device_id=dev["deviceId"], params={"container": "pi-grafana-1"})
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    _again(dev["token"])
    beat(client, dev["token"], ALLOW)
    demo.reset(started)  # the chat that asked is gone
    client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": "Started", "state": "running"},
                headers={"X-Device-Token": dev["token"]})
    svc = next(s.to_dict() for s in db.services(started, dev["deviceId"]).get() if s.to_dict().get("name") == "pi-grafana-1")
    done = db.action(started, a["id"]).get().to_dict()
    assert svc["status"] == "ok" and done["followUp"] == "skipped_after_reset" and "continuationTurnId" not in done
