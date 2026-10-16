"""The on-device helper: HTTPS only, no redirects with credentials, safe token file, minimal image names, retries."""

import http.server
import importlib.util
import json
import os
import stat
import threading
import time
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "nightlight_helper", Path(__file__).resolve().parents[2] / "helper" / "nightlight_helper.py")


@pytest.fixture
def helper(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHTLIGHT_HOME", str(tmp_path / "cfg"))
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    return mod


def test_only_https_or_local_http(helper):
    assert helper.check_api("https://api.example.com/") == "https://api.example.com"
    assert helper.check_api("http://localhost:8080") == "http://localhost:8080"
    for bad in ("http://api.example.com", "ftp://x", "https://"):
        with pytest.raises(SystemExit):
            helper.check_api(bad)


def _server(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_redirects_are_not_followed_with_the_token(helper):
    seen = []

    class Sink(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(self.headers.get("X-Device-Token"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    sink = _server(Sink)

    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{sink.server_port}/steal")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    red = _server(Redirect)
    status, _ = helper._post(f"http://127.0.0.1:{red.server_port}/helper/heartbeat", {}, {"X-Device-Token": "t" * 43})
    assert status == 302 and seen == []  # the token never reached the other server


def test_token_file_is_owner_only_even_over_an_existing_file(helper):
    os.makedirs(helper.CONFIG_DIR, mode=0o755)
    Path(helper.CONFIG).write_text("{}")
    os.chmod(helper.CONFIG, 0o644)
    helper._save_config({"token": "x"})
    assert stat.S_IMODE(os.stat(helper.CONFIG).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(helper.CONFIG_DIR).st_mode) == 0o700


def test_symlinked_config_is_replaced_not_followed(helper, tmp_path):
    os.makedirs(helper.CONFIG_DIR, mode=0o700)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    os.symlink(victim, helper.CONFIG)
    helper._save_config({"token": "x"})
    assert victim.read_text() == "keep me" and not os.path.islink(helper.CONFIG)
    assert json.loads(Path(helper.CONFIG).read_text()) == {"token": "x"}


def test_symlinked_config_dir_is_refused(helper, tmp_path):
    real_dir = tmp_path / "elsewhere"
    real_dir.mkdir()
    os.symlink(real_dir, helper.CONFIG_DIR)
    with pytest.raises(SystemExit):
        helper._save_config({"token": "x"})
    assert list(real_dir.iterdir()) == []


def test_image_names_drop_registry_and_digest(helper):
    assert helper._image_name("192.0.2.8:5000/private/team/world:latest") == "world:latest"
    assert helper._image_name("teslamate/teslamate:4.0.1") == "teslamate:4.0.1"
    assert helper._image_name("ghcr.io/x/y@sha256:abc") == "y"


def test_run_survives_network_failures(helper, monkeypatch):
    statuses = iter([0, 0, 200, 401])
    sleeps = []
    monkeypatch.setattr(helper, "once", lambda: next(statuses))
    monkeypatch.setattr(helper.time, "sleep", sleeps.append)
    with pytest.raises(SystemExit):
        helper.run(60)
    assert sleeps == [120, 240, 60]  # backs off on failure, returns to normal after success, stops when revoked


def test_malformed_reply_is_reported_not_raised(helper):
    class Broken(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.wfile.write(b"HTTP/1.1 500 Oops\r\nContent-Length: 50\r\n\r\nshort")  # body cut off

        def log_message(self, *a):
            pass

    srv = _server(Broken)
    status, body = helper._post(f"http://127.0.0.1:{srv.server_port}/x", {})
    assert status in (0, 500) and isinstance(body, dict)


def test_unreachable_server_is_reported_not_raised(helper):
    status, body = helper._post("http://127.0.0.1:9/x", {})
    assert status == 0 and "error" in body


@pytest.mark.parametrize("payload", [b"<html>proxy page</html>", b"[]", b"null", b"{}"])
def test_bad_acknowledgment_is_not_success(helper, monkeypatch, payload):
    class Ack(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = _server(Ack)
    helper._save_config({"api": f"http://127.0.0.1:{srv.server_port}", "token": "t" * 43, "deviceId": "d"})
    monkeypatch.setattr(helper, "facts", lambda: {})
    assert helper.once() == 0  # not counted as delivered; continuous mode will back off and retry


def test_jobs_run_only_when_allowed_locally(helper, monkeypatch):
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    calls, state = [], {"v": "exited"}

    def fake_run(cmd, timeout=20):
        calls.append(cmd)
        if cmd[:2] == ["docker", "start"]:
            state["v"] = "running"
        return state["v"] + "\n" if cmd[1] == "inspect" else ""

    monkeypatch.setattr(helper, "_run", fake_run)
    monkeypatch.setattr(helper.shutil, "which", lambda name: "/usr/bin/" + name)
    job = {"id": "act_" + "a" * 26, "type": "restart_container", "params": {"container": "demo"}}
    ok, summary, _ = helper.run_job(job, wait=0)
    assert not ok and "isn't allowed" in summary and calls == []  # nothing runs until the owner allows it here
    helper.set_allowed("restart_container", "demo", True)
    assert helper.facts.__module__ and helper._allowed() == {"restart_container": ["demo"]}
    for bad in ({**job, "type": "rm_rf"}, {**job, "params": {"container": "other"}}, {**job, "params": "demo"}):
        assert helper.run_job(bad, wait=0)[0] is False and calls == []
    ok, summary, st = helper.run_job(job, wait=0)
    assert ok and st == "running" and ["docker", "start", "demo"] in calls
    helper.set_allowed("restart_container", "demo", False)
    assert helper._allowed() == {}
    with pytest.raises(SystemExit):
        helper.set_allowed("restart_container", "--privileged", True)


def test_pair_polls_until_approved_then_saves_the_token(helper, monkeypatch):
    calls = []

    class Pair(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.path)
            n = sum(1 for c in calls if c.endswith("/poll"))
            body = ({"code": "ABCD-EFGH", "pollSecret": "s" * 43, "interval": 0} if self.path.endswith("/start")
                    else {"deviceId": "dev_x", "token": "t" * 43} if n >= 2 else {"status": "waiting"})
            code = 201 if self.path.endswith("/start") else 200 if n >= 2 else 202
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    srv = _server(Pair)
    monkeypatch.setattr(helper.time, "sleep", lambda s: None)
    helper.pair(f"http://127.0.0.1:{srv.server_port}", web="https://web.example", name="Mac")
    assert helper._load()["token"] == "t" * 43 and calls.count("/helper/pair/poll") == 2


def test_linux_install_writes_a_service_without_secrets(helper, monkeypatch, tmp_path):
    helper._save_config({"api": "https://api.example.com", "token": "SECRET" + "t" * 37, "deviceId": "d"})
    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(helper, "APP_DIR", str(tmp_path / "app dir"))
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/bin/" + n)
    seen = {}

    def fake_run(cmd, **kw):
        if "install" in cmd and "-m" in cmd:
            seen["unit"] = open(cmd[-2]).read()
        seen.setdefault("cmds", []).append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    import subprocess
    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    helper.install(every=60)
    unit = seen["unit"]
    assert "SECRET" not in unit and "run --every 60" in unit and '"' + str(tmp_path / "app dir") in unit
    assert "NIGHTLIGHT_HOME=" in unit and "Restart=on-failure" in unit
    assert any(c[-2:] == ["--now", "nightlight-helper.service"] for c in seen["cmds"])
    assert stat.S_IMODE(os.stat(helper.CONFIG).st_mode) == 0o600


def test_macos_install_and_uninstall_touch_only_their_own_files(helper, monkeypatch, tmp_path):
    import plistlib
    import subprocess
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    monkeypatch.setattr(helper, "APP_DIR", str(tmp_path / "Application Support" / "Nightlight"))
    monkeypatch.setattr(helper, "PLIST", str(tmp_path / "LaunchAgents" / "com.nightlight.helper.plist"))
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr(helper, "_post", lambda *a, **k: (200, {"ok": True}))
    helper.install(every=180)
    plist = plistlib.load(open(helper.PLIST, "rb"))
    assert plist["ProgramArguments"][-3:] == ["run", "--every", "180"] and "t" * 43 not in str(plist)
    keep = tmp_path / "Application Support" / "Nightlight" / "my-notes.txt"
    keep.write_text("not ours")
    helper.uninstall()
    assert not os.path.exists(helper.PLIST) and not os.path.exists(helper.CONFIG) and keep.exists()



def test_install_refuses_root_odd_paths_and_symlinked_dirs(helper, monkeypatch, tmp_path):  # review 8 #2,#3,#5
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/bin/" + n)
    monkeypatch.setattr(helper.os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit):
        helper.install()
    monkeypatch.setattr(helper.os, "geteuid", lambda: 1000)
    for bad in ("/opt/50%off", "/home/$USER", 'a"b', "line\nbreak"):
        with pytest.raises(SystemExit):
            helper._systemd_value(bad)
    assert helper._systemd_value("/home/pi/My Apps") == '"/home/pi/My Apps"'
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "nightlight_helper.py").write_text("someone else's")
    link = tmp_path / "app-link"
    link.symlink_to(elsewhere)
    monkeypatch.setattr(helper, "APP_DIR", str(link))
    with pytest.raises(SystemExit):
        helper._copy_self()
    monkeypatch.setattr(helper, "UNIT", str(tmp_path / "no-unit"))
    monkeypatch.setattr(helper, "_post", lambda *a, **k: (200, {"ok": True}))
    with pytest.raises(SystemExit):
        helper.uninstall()
    assert (elsewhere / "nightlight_helper.py").exists()  # never deleted through the link


def test_uninstall_keeps_files_when_the_service_wont_stop(helper, monkeypatch, tmp_path):  # review 8 #3
    import subprocess
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    unit = tmp_path / "nightlight-helper.service"
    unit.write_text(f"# nightlight-owner={os.getuid()}\n[Service]\n")
    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(helper, "UNIT", str(unit))
    monkeypatch.setattr(helper, "_post", lambda *a, **k: (200, {"ok": True}))
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", ""))
    with pytest.raises(SystemExit):
        helper.uninstall()
    assert unit.exists() and os.path.exists(helper.CONFIG)



def test_uninstall_recognises_a_service_from_before_the_owner_mark(helper, monkeypatch, tmp_path):
    import subprocess
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    unit = tmp_path / "nightlight-helper.service"
    script = os.path.join(helper.APP_DIR, "nightlight_helper.py")
    unit.write_text(f'[Service]\nUser={helper._me()}\nExecStart="/usr/bin/python3" "{script}" run\n')
    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(helper, "UNIT", str(unit))
    monkeypatch.setattr(helper, "_post", lambda *a, **k: (200, {"ok": True}))
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    helper.uninstall()
    assert not os.path.exists(helper.CONFIG)
    unit.write_text("[Service]\nUser=someoneelse\nExecStart=/x\n")
    assert helper._unit_is_mine() is False



def test_macos_install_never_writes_through_a_plist_link(helper, monkeypatch, tmp_path):  # review 8 rev2 #1
    import subprocess
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    notes = tmp_path / "notes.txt"
    notes.write_text("mine")
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    (agents / "com.nightlight.helper.plist").symlink_to(notes)
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    monkeypatch.setattr(helper, "APP_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(helper, "PLIST", str(agents / "com.nightlight.helper.plist"))
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    helper.install()
    assert notes.read_text() == "mine" and not os.path.islink(helper.PLIST)


@pytest.mark.parametrize("raw,gone", [
    ("password=hunter2", "hunter2"), ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop"),
    ("from 192.168.1.20 port 22", "192.168.1.20"), ("mac 00:11:22:33:44:55", "00:11:22:33:44:55"),
    ("open /home/juan/secret.txt", "juan"), ("token eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4", "eyJhbGci"),
    ("\x1b[31mred\x1b[0m", "\x1b"), ("mail me@example.com", "me@example.com"),
])
def test_device_side_scrub(helper, raw, gone):
    assert gone not in helper.scrub(raw)[0]


def test_look_into_needs_local_permission_and_reads_only(helper, monkeypatch):
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    calls = []

    def fake_run(cmd, timeout=20):
        calls.append(cmd)
        return '{"Status":"exited","ExitCode":137,"OOMKilled":true,"StartedAt":"x","FinishedAt":"y"} 3\n'

    monkeypatch.setattr(helper, "_run", fake_run)
    monkeypatch.setattr(helper, "_run_both", lambda cmd, timeout=15: calls.append(cmd) or "line password=x1\n")
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/bin/" + n)
    assert helper.look_into("grafana")[0] is False and calls == []  # not allowed: nothing runs
    helper.set_allowed("diagnose", "grafana", True)
    ok, summary, out = helper.look_into("grafana")
    assert ok and "out of memory" in summary and "last log lines" not in out  # logs need their own permission
    helper.set_allowed("logs", "grafana", True)
    ok, summary, out = helper.look_into("grafana")
    assert "last log lines" in out and "x1" not in out
    assert all(c[0] == "docker" and c[1] in ("inspect", "logs") for c in calls)  # read-only commands only
    job = {"id": "act_" + "b" * 26, "type": "diagnose", "params": {"target": "grafana; rm -rf /"}}
    assert helper.run_job(job)[0] is False


def test_a_logs_permission_never_starts_a_container(helper, monkeypatch):  # review 10 #1
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    helper.set_allowed("logs", "grafana", True)
    calls = []
    monkeypatch.setattr(helper, "_run", lambda cmd, timeout=20: calls.append(cmd) or "exited\n")
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/bin/" + n)
    for kind in ("logs", "diagnose_x", "restart_container"):
        job = {"id": "act_" + "c" * 26, "type": kind, "params": {"container": "grafana"}}
        assert helper.run_job(job, wait=0)[0] is False
    assert not any(c[:2] == ["docker", "start"] for c in calls)


def test_what_leaves_the_device_is_scrubbed(helper, monkeypatch):  # review 10 #2: at the upload boundary
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    helper.set_allowed("diagnose", "web", True)
    helper.set_allowed("logs", "web", True)
    secrets = ['{"password": "s3cr3tvalue1"}', "DB_PASSWORD=s3cr3tvalue2", "pass\x1b[0mword=s3cr3tvalue3",
               "client 2001:db8::1 connected", "--api-key s3cr3tvalue4", "MY_TOKEN: 's3cr3tvalue5'"]
    monkeypatch.setattr(helper, "_run", lambda cmd, timeout=20:
                        '{"Status":"exited","ExitCode":1,"OOMKilled":false} 0' if cmd[1] == "inspect" else "")
    monkeypatch.setattr(helper, "_run_both", lambda cmd, timeout=15: "\n".join(secrets))
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/bin/" + n)
    sent = []
    monkeypatch.setattr(helper, "_post", lambda url, body, headers=None: sent.append(json.dumps(body)) or (200, {}))
    helper._do_job("https://api.example.com", "t" * 43, {"id": "act_" + "d" * 26, "type": "diagnose",
                                                          "params": {"target": "web"}})
    out = sent[0]
    for leaked in ("s3cr3tvalue1", "s3cr3tvalue2", "s3cr3tvalue3", "2001:db8::1", "s3cr3tvalue4", "s3cr3tvalue5"):
        assert leaked not in out
    assert helper.scrub("at 12:30:45")[0] == "at 12:30:45"


def test_reading_a_huge_log_is_bounded(helper):  # review 10 #5
    import sys as _sys
    out = helper._run_both([_sys.executable, "-c", "import sys; sys.stdout.write('x' * 5_000_000)"], cap=100_000)
    assert 0 < len(out) <= 100_000


def test_escaped_quotes_never_leak_part_of_a_secret(helper):  # review 10 rev2 #1
    out = helper.scrub(r'{"password": "ab\" cd efgh", "user": "bob"}')[0]
    assert "cd efgh" not in out and '"user": "bob"' in out


def test_a_stalled_command_cannot_hang_the_helper(helper):  # review 10 rev2 #2
    import sys as _sys
    t = time.time()
    helper._run_both([_sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.3)
    assert time.time() - t < 2


def test_discovery_sends_only_what_you_pick_and_never_addresses(helper, monkeypatch):
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    monkeypatch.setattr(helper, "_neighbours", lambda: {"192.168.1.20": "b8:27:eb:11:22:33",
                                                        "192.168.1.30": "02:11:22:33:44:55"})
    monkeypatch.setattr(helper, "_mdns", lambda: {"192.168.1.20": {"Home Assistant"}})
    monkeypatch.setattr(helper, "_open_ports", lambda ips: {"192.168.1.20": [8123, 22]})
    sent = []
    monkeypatch.setattr(helper, "_post", lambda url, body, headers=None: sent.append(body) or (200, {"ok": True}))
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    helper.discover()
    assert len(sent) == 1 and len(sent[0]["items"]) == 1
    item = sent[0]["items"][0]
    assert item["guess"] == "Home Assistant" and item["vendor"] == "Raspberry Pi"
    assert "192.168" not in json.dumps(sent) and "b8:27" not in json.dumps(sent)
    assert helper._load()["found"][item["cid"]]["ip"] == "192.168.1.20"  # the address stays here
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    sent.clear()
    helper.discover()
    assert sent == []  # Enter = send nothing
