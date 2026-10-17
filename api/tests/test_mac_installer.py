"""The Mac installer (Nightlight.pkg): approve in the browser, then the helper installs itself with the bundled Python
and keeps using it after signed updates; the package's own files are accounted for on uninstall."""

import http.server
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "helper" / "nightlight_helper.py"
SPEC = importlib.util.spec_from_file_location("nightlight_helper", HELPER)


@pytest.fixture
def helper(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHTLIGHT_HOME", str(tmp_path / "cfg"))
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    monkeypatch.setattr(mod, "APP_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(mod, "PLIST", str(tmp_path / "LaunchAgents" / "com.nightlight.helper.plist"))
    monkeypatch.setattr(mod, "PKG_DIR", str(tmp_path / "Library" / "Nightlight"))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def _serve(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _pairing(approve_after=2, decline=False):
    """A pairing server: approves on the `approve_after`-th poll (or declines on the first)."""
    polls = []

    class Pair(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path.endswith("/start"):
                code, body = 201, {"code": "ABCD-EFGH", "pollSecret": "s" * 43, "interval": 0}
            else:
                polls.append(1)
                if decline:
                    code, body = 401, {"code": "invalid_code"}
                elif len(polls) >= approve_after:
                    code, body = 200, {"deviceId": "dev_x", "token": "t" * 43}
                else:
                    code, body = 202, {"status": "waiting"}
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    return _serve(Pair), polls


def test_the_installer_opens_the_approval_page_then_installs_managed_from_the_app(helper, monkeypatch):
    srv, polls = _pairing()
    opened, notes, installed = [], [], []
    monkeypatch.setattr(helper, "_open_browser", lambda url: opened.append(url) or True)
    monkeypatch.setattr(helper, "_notify", notes.append)
    monkeypatch.setattr(helper, "install", lambda every=60, manage=None: installed.append(manage))
    monkeypatch.setattr(helper.sys, "argv", ["h", "pair", f"http://127.0.0.1:{srv.server_port}", "--web",
                                             "https://web.example/", "--browser", "--install"])
    helper.main()
    srv.shutdown()
    assert opened == ["https://web.example/pair?code=ABCD-EFGH"] and len(polls) == 2
    assert helper._load()["token"] == "t" * 43 and installed == ["app"]
    assert notes == ["This Mac is now on your Nightlight map."]


def test_a_declined_code_installs_nothing_and_says_so(helper, monkeypatch):
    srv, _ = _pairing(decline=True)
    notes = []
    monkeypatch.setattr(helper, "_open_browser", lambda url: True)
    monkeypatch.setattr(helper, "_notify", notes.append)
    monkeypatch.setattr(helper, "install", lambda **k: pytest.fail("nothing to install without an approval"))
    with pytest.raises(SystemExit):
        helper.pair(f"http://127.0.0.1:{srv.server_port}", web="https://web.example", browser=True,
                    then_install=True)
    srv.shutdown()
    assert not os.path.exists(helper.CONFIG) and "installer again" in notes[0]


def test_no_browser_means_the_link_arrives_as_a_notification(helper, monkeypatch):
    srv, _ = _pairing(approve_after=1)
    notes = []
    monkeypatch.setattr(helper, "_open_browser", lambda url: False)
    monkeypatch.setattr(helper, "_notify", notes.append)
    helper.pair(f"http://127.0.0.1:{srv.server_port}", web="https://web.example", browser=True)
    srv.shutdown()
    assert notes == ["Open https://web.example/pair?code=ABCD-EFGH to add this Mac."]


def test_browser_pairing_needs_the_web_address(helper):
    with pytest.raises(SystemExit):
        helper.pair("https://api.example.com", browser=True)


def test_install_without_a_terminal_can_be_told_to_let_the_app_manage(helper, monkeypatch):
    # The folder question stays unasked (no answer on record), so it can be offered later; the private folders stay
    # closed until then.
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    monkeypatch.setattr(helper.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(helper, "_link_command", lambda *a: None)
    monkeypatch.setattr(helper, "_ask", lambda *a: pytest.fail("nobody is at a terminal"))
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    helper.install(manage="app")
    cfg = helper._load()
    assert cfg["manage"] == "app" and "macPrivateFolders" not in cfg and not helper._mac_private_ok()


def _bundled_python(tmp_path):
    """Stands in for the package's Python: a script (so its path is its own, not the real interpreter's) that logs
    each use and runs the real interpreter."""
    py = tmp_path / "Library" / "Nightlight" / "runtime" / "arm64" / "python" / "bin" / "python3.12"
    py.parent.mkdir(parents=True)
    log = tmp_path / "runtime-uses.log"
    py.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexec "{os.path.realpath(sys.executable)}" "$@"\n')
    py.chmod(0o755)
    return str(py), log


def test_the_service_keeps_the_bundled_python_across_a_signed_update(helper, tmp_path, monkeypatch):
    py, log = _bundled_python(tmp_path)
    monkeypatch.setattr(helper.sys, "executable", py)
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    linked = []
    monkeypatch.setattr(helper, "_link_command", lambda script, python: linked.append(python))
    real_run = subprocess.run
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", "")
                        if cmd[0] == "launchctl" else real_run(cmd, **kw))
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    helper.install(manage="app")
    assert plistlib.load(open(helper.PLIST, "rb"))["ProgramArguments"][0] == py and linked == [py]

    # A signed update from the app replaces only the helper file; its self-test runs on the same bundled Python.
    key = tmp_path / "k.pem"
    real_run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)], check=True)
    pub = real_run(["openssl", "ec", "-in", str(key), "-pubout"], capture_output=True, text=True, check=True)
    monkeypatch.setattr(helper, "RELEASE_KEY", pub.stdout)
    d = tmp_path / "srv" / "helper" / "release"
    d.mkdir(parents=True)
    (d / "nightlight_helper.py").write_text(HELPER.read_text().replace(f'VERSION = "{helper.VERSION}"',
                                                                       'VERSION = "9.9.9"', 1))
    real_run(["openssl", "dgst", "-sha256", "-sign", str(key), "-out", str(d / "nightlight_helper.py.sig"),
              str(d / "nightlight_helper.py")], check=True)

    class Files(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(tmp_path / "srv"), **k)

        def log_message(self, *a):
            pass

    srv = _serve(Files)
    target = os.path.join(helper.APP_DIR, "nightlight_helper.py")
    monkeypatch.setattr(helper.sys, "argv", [target, "run"])
    ok, summary, _ = helper.self_update("9.9.9", f"http://127.0.0.1:{srv.server_port}")
    srv.shutdown()
    assert ok, summary
    assert 'VERSION = "9.9.9"' in Path(target).read_text()
    assert plistlib.load(open(helper.PLIST, "rb"))["ProgramArguments"][0] == py  # the service still starts it
    assert log.read_text().strip().endswith("version")  # the new file was tested on the bundled Python


def test_uninstall_points_at_the_installer_files_it_cannot_remove(helper, tmp_path, monkeypatch, capsys):
    os.makedirs(os.path.join(helper.PKG_DIR, "runtime"))
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr(helper, "_post", lambda *a, **k: (200, {"ok": True}))
    monkeypatch.setattr(helper.os, "geteuid", lambda: 501)
    helper.uninstall()
    out = capsys.readouterr().out
    assert os.path.isdir(helper.PKG_DIR) and f"sudo rm -rf '{helper.PKG_DIR}'" in out and "pkgutil --forget" in out
    ran = []
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr(helper.os, "geteuid", lambda: 0)
    helper._pkg_leftovers()
    assert not os.path.exists(helper.PKG_DIR) and ran == [["pkgutil", "--forget", helper.PKG_ID]]


def test_build_dry_run_lays_out_the_payload(tmp_path):
    out = tmp_path / "mac"
    r = subprocess.run(["bash", str(ROOT / "scripts" / "build_mac_pkg.sh"), "--dry-run"], cwd=ROOT, capture_output=True,
                       text=True, timeout=60, check=False,
                       env={**os.environ, "BUILD_DIR": str(out), "WEB_URL": "https://web.example",
                            "API_URL": "https://api.example"})
    assert r.returncode == 0, r.stderr
    app = out / "stage" / "root" / "Library" / "Application Support" / "Nightlight"
    assert (app / "nightlight_helper.py").read_bytes() == HELPER.read_bytes()
    for arch in ("arm64", "x86_64"):
        assert (app / "runtime" / arch / "python" / "bin" / "python3.12").is_file()
    post = out / "stage" / "scripts" / "postinstall"
    assert os.access(post, os.X_OK)
    text = post.read_text()
    assert 'PY="$DIR/runtime/$ARCH/python/bin/python3.12"' in text and "--browser --install" in text
    assert "loginwindow" in text and "launchctl asuser" in text
    conf = (out / "stage" / "scripts" / "nightlight.conf").read_text()
    assert conf == "API_URL='https://api.example'\nWEB_URL='https://web.example'\n"
    assert not list(out.glob("*.pkg")) and not list((out / "cache").iterdir())  # nothing downloaded or packaged
    bad = subprocess.run(["bash", str(ROOT / "scripts" / "build_mac_pkg.sh"), "--dry-run"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60, check=False,
                         env={**os.environ, "BUILD_DIR": str(out), "WEB_URL": "http://web.example'; rm -rf /"})
    assert bad.returncode != 0 and "Not an https origin" in bad.stderr
