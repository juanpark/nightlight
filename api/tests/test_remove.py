"""Removing a real device: the helper uninstalls itself when it can, otherwise access is cut; archived, then purged."""

from datetime import datetime, timedelta, timezone

from nightlight_api import actions, agent, archive, db, real, notebook
from conftest import generation
from test_real import FACTS, beat, enrolled

NEW = {**FACTS, "helperVersion": "0.9.6"}


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


def test_reporting_device_uninstalls_itself_and_is_archived(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], NEW)
    r = client.post(f"/api/devices/{dev['deviceId']}/remove", json={})
    assert r.status_code == 202 and r.json()["removed"] == "asked_device"
    aid = r.json()["actionId"]
    _again(dev["token"])
    jobs = beat(client, dev["token"], NEW).json()["jobs"]
    assert jobs == [{"id": aid, "type": "remove_device", "params": {}}]
    assert client.post("/helper/leave", json={"cleanup": "full"},
                       headers={"X-Device-Token": dev["token"]}).status_code == 200
    d = db.device(started, dev["deviceId"]).get().to_dict()
    a = db.action(started, aid).get().to_dict()
    assert d["archived"] and d["purgeAt"] > datetime.now(timezone.utc) + timedelta(days=29)
    assert a["status"] == "done" and "uninstalled itself" in a["result"]["summary"]
    assert not real.is_current(d, generation(started))  # gone from the map and the agent
    assert beat(client, dev["token"], NEW).status_code == 401
    assert [x["id"] for x in client.get("/api/devices/removed").json()["devices"]] == [dev["deviceId"]]


def test_silent_or_old_device_has_its_access_cut_at_once(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], {**FACTS, "helperVersion": "0.9.5"})  # too old to uninstall itself
    r = client.post(f"/api/devices/{dev['deviceId']}/remove", json={})
    assert r.json()["removed"] == "access_cut" and "uninstall line" in r.json()["summary"]
    assert db.device(started, dev["deviceId"]).get().to_dict()["archived"]
    assert beat(client, dev["token"], FACTS).status_code == 401


def test_chat_card_then_approval_finishes_an_offline_removal(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], NEW)
    db.device(started, dev["deviceId"]).update({"lastSeen": datetime.now(timezone.utc) - timedelta(hours=2)})
    a = actions.propose(started, session_id="sess_test", turn_id="t1", generation=generation(started),
                        action_type="remove_device", device_id=dev["deviceId"], params={})
    assert a["status"] == "pending" and "access is cut" in a["dryRun"]  # a card, never automatic
    assert client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"}).status_code in (200, 202)
    assert db.action(started, a["id"]).get().to_dict()["status"] == "done"
    assert db.device(started, dev["deviceId"]).get().to_dict()["archived"]


def test_uninstall_by_hand_also_leaves_the_map(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], FACTS)
    client.post("/helper/leave", json={}, headers={"X-Device-Token": dev["token"]})  # an older helper's body
    assert db.device(started, dev["deviceId"]).get().to_dict()["archived"]


def test_forget_for_good_and_purge_after_30_days(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], FACTS)
    notebook.add(started, dev["deviceId"], "note", "you", generation(started))
    assert client.delete(f"/api/devices/{dev['deviceId']}").json()["code"] == "remove_first"
    client.post(f"/api/devices/{dev['deviceId']}/remove", json={})
    assert client.delete(f"/api/devices/{dev['deviceId']}").status_code == 200
    assert not db.device(started, dev["deviceId"]).get().exists
    assert not list(db.notes(started, dev["deviceId"]).get())
    assert not [e for e in db.events(started).get() if e.to_dict().get("deviceId") == dev["deviceId"]]
    other = enrolled(client, "Other")
    beat(client, other["token"], FACTS)
    client.post(f"/api/devices/{other['deviceId']}/remove", json={})
    archive.index().document(f"{started}__{other['deviceId']}").update(
        {"purgeAt": datetime.now(timezone.utc) - timedelta(minutes=1)})
    assert archive.purge_due() == 1 and not db.device(started, other["deviceId"]).get().exists


def test_sample_devices_cannot_be_removed(client, started):
    sample = next(s.id for s in db.devices(started).get() if s.to_dict().get("realm") != "real")
    assert client.post(f"/api/devices/{sample}/remove", json={}).status_code == 404


def test_remove_device_is_an_action_tool():
    from nightlight_api import turns
    assert "remove_device" in turns.ACTION_TOOLS
    ctx = agent.TurnContext.__new__(agent.TurnContext)
    assert "remove_device" in {t.__name__ for t in agent.make_tools(ctx, read_only=False)}


# ------------------------------------------------------------------ the helper side

import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "nightlight_helper", Path(__file__).resolve().parents[2] / "helper" / "nightlight_helper.py")


@pytest.fixture
def helper(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHTLIGHT_HOME", str(tmp_path / "cfg"))
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    monkeypatch.setattr(mod, "APP_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(mod, "PLIST", str(tmp_path / "agent.plist"))
    return mod


def test_helper_tells_nightlight_then_deletes_files_then_stops_its_service(helper, tmp_path, monkeypatch):
    import os
    steps = []
    os.makedirs(helper.APP_DIR)
    Path(helper.APP_DIR, "nightlight_helper.py").write_text("x")
    Path(helper.PLIST).write_text("plist")
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43})
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    monkeypatch.setattr(helper, "_post", lambda url, body, h=None: steps.append(("leave", body)) or (200, {}))
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **k: steps.append(
        ("run", cmd[:2], os.path.exists(helper.CONFIG), os.path.exists(helper.PLIST))))
    ok, summary, _ = helper.run_job({"type": "remove_device", "params": {}})
    assert ok and steps[0] == ("leave", {"cleanup": "full"})
    assert steps[-1] == ("run", ["launchctl", "bootout"], False, False)  # files and plist gone before the stop
    assert not os.path.exists(os.path.join(helper.APP_DIR, "nightlight_helper.py")) and "exit" in helper._RESTART


def test_without_admin_rights_a_dormant_stub_stays(helper, tmp_path, monkeypatch):
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43})
    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(helper, "UNIT", str(tmp_path / "unit"))
    Path(helper.UNIT).write_text(f"# nightlight-owner={__import__('os').getuid()}\n")
    monkeypatch.setattr(helper, "_sudo_ok", lambda: False)
    sent = []
    monkeypatch.setattr(helper, "_post", lambda url, body, h=None: sent.append(body) or (200, {}))
    ok, summary = helper.remove_from_app()
    assert ok and sent == [{"cleanup": "files_left"}] and helper._load() == {"removed": True}
    with pytest.raises(SystemExit) as e:
        helper.run(60)
    assert e.value.code == 0  # a clean exit: the service doesn't restart it


def test_a_removed_token_makes_the_helper_stop_cleanly(helper, monkeypatch):
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43})
    monkeypatch.setattr(helper, "once", lambda: 401)
    with pytest.raises(SystemExit) as e:
        helper.run(60)
    assert e.value.code == 0
