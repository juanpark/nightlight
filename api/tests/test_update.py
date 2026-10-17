"""Signed helper updates from the app: the server offers, the device verifies; nothing unsigned or older installs."""

import http.server
import importlib.util
import subprocess
import threading
from pathlib import Path

import pytest

from nightlight_api import db, real, release
from nightlight_api.config import settings
from test_real import FACTS, beat, enrolled

HELPER = Path(__file__).resolve().parents[2] / "helper" / "nightlight_helper.py"


@pytest.fixture
def offer(tmp_path, monkeypatch):
    d = tmp_path / "release"
    d.mkdir()
    (d / "nightlight_helper.py").write_text('VERSION = "9.9.9"\n')
    (d / "nightlight_helper.py.sig").write_bytes(b"sig")
    monkeypatch.setattr(settings, "release_dir", str(d))
    release.latest.cache_clear()
    yield d
    release.latest.cache_clear()


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


def test_release_is_offered_and_served(client, offer):
    assert client.get("/helper/release").json()["version"] == "9.9.9"
    assert client.get("/helper/release/nightlight_helper.py").text == 'VERSION = "9.9.9"\n'
    assert client.get("/helper/release/nightlight_helper.py.sig").content == b"sig"
    assert client.get("/helper/release/other.py").status_code == 404


def test_update_from_the_app(client, started, offer):
    dev = enrolled(client)
    assert beat(client, dev["token"], {**FACTS, "helperVersion": "0.9.0", "allowedJobs": {"update": ["signed"]}}
                ).json()["latestHelper"] == "9.9.9"
    r = client.post(f"/api/devices/{dev['deviceId']}/update", json={})
    assert r.status_code == 202 and r.json()["version"] == "9.9.9"
    aid = r.json()["actionId"]
    assert client.post(f"/api/devices/{dev['deviceId']}/update", json={}).json()["actionId"] == aid  # no duplicate
    _again(dev["token"])
    jobs = beat(client, dev["token"], {**FACTS, "helperVersion": "0.9.0", "allowedJobs": {"update": ["signed"]}}
                ).json()["jobs"]
    assert jobs == [{"id": aid, "type": "update_helper", "params": {"version": "9.9.9"}}]
    r = client.post(f"/helper/jobs/{aid}/result", json={"ok": True, "summary": "Updated from 0.9.0 to 9.9.9"},
                    headers={"X-Device-Token": dev["token"]})
    assert r.status_code == 200, r.text
    a = db.action(started, aid).get().to_dict()
    assert a["status"] == "done" and a["followUp"] == "none"
    assert any("Updated from 0.9.0 to 9.9.9" in e.to_dict()["message"] for e in db.events(started).get())


def test_update_refusals(client, started, offer):
    dev = enrolled(client)
    beat(client, dev["token"], {**FACTS, "helperVersion": "0.7.0"})
    assert client.post(f"/api/devices/{dev['deviceId']}/update", json={}).json()["code"] == "update_by_hand"
    _again(dev["token"])
    beat(client, dev["token"], {**FACTS, "helperVersion": "0.9.0"})
    assert client.post(f"/api/devices/{dev['deviceId']}/update", json={}).json()["code"] == "updates_off"
    _again(dev["token"])
    beat(client, dev["token"], {**FACTS, "helperVersion": "9.9.9", "allowedJobs": {"update": ["signed"]}})
    assert client.post(f"/api/devices/{dev['deviceId']}/update", json={}).json()["code"] == "up_to_date"
    assert beat(client, dev["token"], {**FACTS, "allowedJobs": {"update": ["anything"]}}).status_code == 422


# ------------------------------------------------------------------ the helper side

SPEC = importlib.util.spec_from_file_location("nightlight_helper", HELPER)


@pytest.fixture
def helper(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHTLIGHT_HOME", str(tmp_path / "cfg"))
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    monkeypatch.setattr(mod, "APP_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(mod, "_containers", lambda: [])
    monkeypatch.setattr(mod, "_failed_units", lambda **k: [])
    key = tmp_path / "k.pem"
    subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)], check=True)
    pub = subprocess.run(["openssl", "ec", "-in", str(key), "-pubout"], capture_output=True, text=True, check=True)
    monkeypatch.setattr(mod, "RELEASE_KEY", pub.stdout)
    mod._test_key = key
    return mod


def _release(helper, tmp_path, version, tamper=False):
    """Serve a new helper (this one with another VERSION), signed with the test key."""
    src = HELPER.read_text().replace(f'VERSION = "{helper.VERSION}"', f'VERSION = "{version}"', 1)
    d = tmp_path / "srv" / "helper" / "release"
    d.mkdir(parents=True, exist_ok=True)
    (d / "nightlight_helper.py").write_text(src)
    subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(helper._test_key), "-out",
                    str(d / "nightlight_helper.py.sig"), str(d / "nightlight_helper.py")], check=True)
    if tamper:
        (d / "nightlight_helper.py").write_text(src + "\nprint('evil')\n")
    root = str(tmp_path / "srv")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=root, **k)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def _installed(helper, monkeypatch):
    import os
    os.makedirs(helper.APP_DIR, mode=0o700, exist_ok=True)
    target = os.path.join(helper.APP_DIR, "nightlight_helper.py")
    Path(target).write_text(HELPER.read_text())
    monkeypatch.setattr(helper.sys, "argv", [target, "run"])
    return target


def test_signed_newer_update_installs_and_keeps_the_old_one(helper, tmp_path, monkeypatch):
    target = _installed(helper, monkeypatch)
    helper._save_config({"token": "t" * 43, "manage": "app", "remote": {}})
    srv, api = _release(helper, tmp_path, "9.9.9")
    ok, summary, _ = helper.self_update("9.9.9", api)
    srv.shutdown()
    assert ok and "9.9.9" in summary and helper._RESTART
    assert 'VERSION = "9.9.9"' in Path(target).read_text()
    assert Path(helper.APP_DIR, "nightlight_helper.prev.py").read_text() == HELPER.read_text()


def test_tampered_older_or_disallowed_updates_never_install(helper, tmp_path, monkeypatch):
    target = _installed(helper, monkeypatch)
    before = Path(target).read_text()
    helper._save_config({"token": "t" * 43, "manage": "app", "remote": {}})
    srv, api = _release(helper, tmp_path, "9.9.9", tamper=True)
    ok, summary, _ = helper.self_update("9.9.9", api)
    assert not ok and "signature" in summary
    assert not helper.self_update("0.0.1", api)[0]  # never older
    helper._save_config({"token": "t" * 43, "manage": "strict", "allow": {}})
    assert "isn't allowed" in helper.self_update("9.9.9", api)[1]
    helper._save_config({"token": "t" * 43, "manage": "app", "remote": {"updates": False}})
    assert not helper.self_update("9.9.9", api)[0]
    srv.shutdown()
    assert Path(target).read_text() == before and not helper._RESTART


def test_wrong_version_in_a_signed_file_is_refused(helper, tmp_path, monkeypatch):
    _installed(helper, monkeypatch)
    helper._save_config({"token": "t" * 43, "manage": "app", "remote": {}})
    srv, api = _release(helper, tmp_path, "9.9.8")
    assert "isn't the version" in helper.self_update("9.9.9", api)[1]
    srv.shutdown()


def test_an_old_worker_or_a_repeat_cannot_go_back_or_lose_the_backup(helper, tmp_path, monkeypatch):  # review D #1
    target = _installed(helper, monkeypatch)
    original = Path(target).read_text()
    helper._save_config({"token": "t" * 43, "manage": "app", "remote": {}})
    srv, api = _release(helper, tmp_path, "9.9.9")
    assert helper.self_update("9.9.9", api)[0]
    assert "waiting for the restart" in helper.self_update("9.9.9", api)[1]  # a duplicate job
    helper._RESTART.clear()  # an overlapping old worker that didn't install it
    srv.shutdown()
    srv, api = _release(helper, tmp_path, "9.9.8")
    assert "isn't newer than what is installed" in helper.self_update("9.9.8", api)[1]
    srv.shutdown()
    assert 'VERSION = "9.9.9"' in Path(target).read_text()
    assert Path(helper.APP_DIR, "nightlight_helper.prev.py").read_text() == original


def test_rollback_pauses_automatic_updates_until_the_owner_asks(helper, tmp_path, monkeypatch):  # review D #2
    target = _installed(helper, monkeypatch)
    helper._save_config({"token": "t" * 43, "manage": "app", "remote": {"autoUpdate": True}})
    srv, api = _release(helper, tmp_path, "9.9.9")
    assert helper.self_update("9.9.9", api, auto=True)[0]
    helper.rollback()
    helper._RESTART.clear()
    monkeypatch.setattr(helper, "VERSION", helper._file_version(target))  # restarted on the old version
    assert helper._load()["autoPaused"] and "9.9.9" in helper._load()["skipVersions"]
    assert "paused after a rollback" in helper.self_update("9.9.9", api, auto=True)[1]
    assert helper.self_update("9.9.9", api)[0]  # the owner's tap installs it and ends the pause
    srv.shutdown()
    assert "autoPaused" not in helper._load() and helper._load()["skipVersions"] == []


def test_settings_without_a_terminal_changes_nothing(helper, monkeypatch):  # review D #3
    import io
    helper._save_config({"token": "t" * 43, "manage": "strict", "allow": {}})
    monkeypatch.setattr(helper.sys, "stdin", io.StringIO(""))
    with pytest.raises(SystemExit):
        helper.settings()
    assert helper._load()["allow"] == {}


def test_rollback_during_an_automatic_download_wins(helper, tmp_path, monkeypatch):  # review D rev2 #1
    target = _installed(helper, monkeypatch)
    before = Path(target).read_text()
    helper._save_config({"token": "t" * 43, "manage": "app", "remote": {"autoUpdate": True}})
    srv, api = _release(helper, tmp_path, "9.9.9")
    real_get = helper._get

    def get_then_rollback(url, limit):  # the owner pauses while the file downloads
        helper._update_config(lambda c: c.__setitem__("autoPaused", True))
        return real_get(url, limit)
    monkeypatch.setattr(helper, "_get", get_then_rollback)
    ok, summary, _ = helper.self_update("9.9.9", api, auto=True)
    srv.shutdown()
    assert not ok and "paused during the download" in summary and Path(target).read_text() == before


def test_ctrl_d_in_settings_changes_nothing(helper, monkeypatch):  # review D rev2 #2
    helper._save_config({"token": "t" * 43, "manage": "strict", "allow": {}})
    monkeypatch.setattr(helper.sys.stdin, "isatty", lambda: True, raising=False)

    def eof(*a):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    with pytest.raises(SystemExit):
        helper.settings()
    assert helper._load()["allow"] == {} and helper._load()["manage"] == "strict"


def test_mac_private_folders_are_never_read_unless_allowed_at_the_mac(helper, monkeypatch):
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    read = []
    monkeypatch.setattr(helper, "_du", lambda path: read.append(path) or None)
    helper._save_config({"token": "t" * 43})
    helper._inspect_until[0] = __import__("time").time() + 30
    out = helper._inspect_disk()
    private = {p for _, p in helper._mac_private_places()}
    assert not private & set(read) and "Not checked (macOS privacy)" in out
    assert "empty_trash" not in helper._available_fixes()
    helper._save_config({"token": "t" * 43, "macPrivateFolders": True})
    read.clear()
    helper._inspect_disk()
    assert private <= set(read)


def test_the_chat_can_propose_an_update_card(client, started, offer):
    from nightlight_api import actions, agent
    from conftest import generation
    dev = enrolled(client)
    beat(client, dev["token"], {**FACTS, "helperVersion": "0.9.0", "allowedJobs": {"update": ["signed"]}})
    a = actions.propose(started, session_id="sess_test", turn_id="tu", generation=generation(started),
                        action_type="update_helper", device_id=dev["deviceId"], params={"version": "9.9.9"})
    assert a["status"] == "pending" and "to 9.9.9" in a["plan"]  # a card: the tap is the approval
    assert client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"}).json()["status"] == "approved"
    assert "update 9.9.9 available" in agent.fleet_summary(started, generation(started))
    ctx = agent.TurnContext.__new__(agent.TurnContext)
    assert "update_helper" in {t.__name__ for t in agent.make_tools(ctx, read_only=False)}
