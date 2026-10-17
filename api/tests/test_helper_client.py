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

    def once():
        try:
            return next(statuses)
        except StopIteration:
            raise KeyboardInterrupt  # not an Exception: ends the loop (a test must never be able to spin forever)
    sleeps = []
    monkeypatch.setattr(helper, "once", once)
    monkeypatch.setattr(helper.time, "sleep", sleeps.append)
    with pytest.raises(KeyboardInterrupt):
        helper.run(60)
    # backs off on failure, returns to normal after success, waits long (not stops) when the key is refused
    assert sleeps == [120, 240, 60, helper.REFUSED_RETRY]


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


def test_safety_facts(helper, monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(helper.os, "geteuid", lambda: 1000)
    seen = []
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, b"", b""))
    assert helper._passwordless_sudo() is True and seen[-1] == ["sudo", "-k", "-n", "true"]
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b""))
    assert helper._passwordless_sudo() is False
    cfg = tmp_path / "sshd_config"
    cfg.write_text("# comment\nPasswordAuthentication no\n")
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: real_open(cfg if p == "/etc/ssh/sshd_config" else p, *a, **k))
    monkeypatch.setattr(helper.sys, "platform", "linux")
    assert helper._ssh_password_login() is False


def test_the_server_cannot_widen_watched_ports(helper, monkeypatch):  # review 12 #1
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d",
                         "found": {"a1b2c3d4e5f6": {"ip": "192.168.1.20", "ports": [8123]}},
                         "watch": [{"cid": "a1b2c3d4e5f6", "port": 31337}, {"cid": "nope", "port": 8123},
                                   {"cid": "a1b2c3d4e5f6", "port": "8123"}]})
    tried = []
    monkeypatch.setattr("socket.create_connection", lambda addr, timeout=None: tried.append(addr) or (_ for _ in ()).throw(OSError()))
    assert helper._watch_results() == [] and tried == []


def test_ssh_settings_with_includes_are_unknown_and_dnf_counts(helper, monkeypatch, tmp_path):  # review 13 #2,#3
    cfg = tmp_path / "sshd_config"
    cfg.write_text("Include /etc/ssh/sshd_config.d/*.conf\nPasswordAuthentication yes\n")
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: real_open(cfg if p == "/etc/ssh/sshd_config" else p, *a, **k))
    monkeypatch.setattr(helper.sys, "platform", "linux")
    assert helper._ssh_password_login() is None
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/usr/bin/dnf" if n == "dnf" else None)
    monkeypatch.setattr(helper, "_run_status", lambda cmd, timeout=20: (100, "\nkernel.x86_64  6.5.1-1.fc39  updates\n"
                        "vim.x86_64 2:9.0-1.fc39 updates\n"))
    assert helper._count_updates() == 2


def test_restart_service_needs_local_permission(helper, monkeypatch):  # slice 14
    import subprocess
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    state = {"v": "failed"}
    calls = []

    def fake_sp(cmd, **kw):
        calls.append(cmd)
        state["v"] = "active"
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(helper, "_run_status", lambda cmd, timeout=20: (0 if (cmd[1] == "is-failed") == (state["v"] == "failed") else 3,
                                                                       state["v"] + "\n"))
    monkeypatch.setattr(helper.subprocess, "run", fake_sp)
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/bin/" + n)
    monkeypatch.setattr(helper.os, "geteuid", lambda: 1000)
    job = {"id": "act_" + "e" * 26, "type": "restart_service", "params": {"unit": "pihole-FTL.service"}}
    assert helper.run_job(job, wait=0)[0] is False and calls == []
    helper.set_allowed("restart_service", "pihole-FTL.service", True)
    ok, summary, _ = helper.run_job(job, wait=0)
    assert ok and calls == [["sudo", "-n", "systemctl", "restart", "pihole-FTL.service"]]



def test_a_unit_stopped_on_purpose_is_never_restarted(helper, monkeypatch):  # review 14 #2
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    helper.set_allowed("restart_service", "x.service", True)
    calls = []
    monkeypatch.setattr(helper, "_run_status", lambda cmd, timeout=20: (3, "inactive\n"))
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/bin/" + n)
    job = {"id": "act_" + "f" * 26, "type": "restart_service", "params": {"unit": "x.service"}}
    assert helper.run_job(job, wait=0)[0] is False and calls == []


def test_ssh_match_blocks_and_dnf_errors_are_unknown(helper, monkeypatch, tmp_path):  # review 13 rev2
    cfg = tmp_path / "sshd_config"
    cfg.write_text("PasswordAuthentication no\nMatch User guest\n  PasswordAuthentication yes\n")
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: real_open(cfg if p == "/etc/ssh/sshd_config" else p, *a, **k))
    monkeypatch.setattr(helper.sys, "platform", "linux")
    assert helper._ssh_password_login() is None
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/usr/bin/dnf" if n == "dnf" else None)
    monkeypatch.setattr(helper, "_run_status", lambda cmd, timeout=20: (1, "Error: Failed to download metadata"))
    assert helper._count_updates() is None


def test_app_managed_permissions_apply_only_in_app_mode(helper, monkeypatch):
    remote = {"diagnose": True, "logs": ["web"], "restart_container": ["web", "bad name;"], "restart_service": []}
    monkeypatch.setattr(helper, "_containers", lambda: [{"name": "web"}])
    monkeypatch.setattr(helper, "_failed_units", lambda: ["pihole-FTL.service"])
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d", "manage": "strict",
                         "remote": remote, "allow": {"diagnose": ["web"]}})
    assert helper._allowed() == {"diagnose": ["web"]}  # strict: the app's switches are ignored
    cfg = helper._load()
    cfg["manage"] = "app"
    helper._save_config(cfg)
    got = helper._allowed()
    assert got["restart_container"] == ["web"] and got["logs"] == ["web"]
    assert sorted(got["diagnose"]) == ["pihole-FTL.service", "web"]


def test_install_without_a_terminal_chooses_strict(helper, monkeypatch, tmp_path):
    import subprocess
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    monkeypatch.setattr(helper.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(helper, "APP_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(helper, "PLIST", str(tmp_path / "LaunchAgents" / "x.plist"))
    monkeypatch.setattr(helper, "_link_command", lambda *a: None)
    monkeypatch.setattr(helper.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    helper.install()
    assert helper._load()["manage"] == "strict"


def test_joined_check_used_by_the_installer(helper, monkeypatch):
    monkeypatch.setattr(helper.sys, "argv", ["h", "joined"])
    with pytest.raises(SystemExit) as no:
        helper.main()
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d"})
    with pytest.raises(SystemExit) as yes:
        helper.main()
    assert no.value.code == 1 and yes.value.code == 0


def test_a_report_never_undoes_a_local_switch_to_strict(helper, monkeypatch):  # review 15 #1
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d", "manage": "app"})
    stale = helper._load()  # what the service loaded before its request
    helper._update_config(lambda c: c.__setitem__("manage", "strict"))  # the owner switches to strict meanwhile
    helper._remember_about(stale, {"deviceName": "Pi", "permissions": {"diagnose": True,
                                                                       "restart_container": ["web"]}})
    cfg = helper._load()
    assert cfg["manage"] == "strict" and cfg["deviceName"] == "Pi"


def test_app_grants_only_for_things_this_device_reports(helper, monkeypatch):  # review 15 #2
    monkeypatch.setattr(helper, "_containers", lambda: [{"name": "web"}])
    monkeypatch.setattr(helper, "_failed_units", lambda: [])
    got = helper._from_remote({"diagnose": True, "logs": ["web", "other"], "restart_container": ["unreported", "web"],
                               "restart_service": ["ssh.service"]})
    assert got == {"logs": ["web"], "restart_container": ["web"], "diagnose": ["web"], "inspect": sorted(helper.INSPECT),
                   "update": ["signed"]}


def test_wrapper_is_quoted_and_never_clobbers_other_files(helper, monkeypatch, tmp_path):  # review 15 #3,#4
    import subprocess
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(helper.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))
    bindir = tmp_path / ".local" / "bin"
    bindir.mkdir(parents=True)
    theirs = bindir / "nightlight"
    theirs.write_text("#!/bin/sh\n# calls nightlight_helper.py somewhere\necho mine\n")
    helper._link_command(str(tmp_path / "a$HOME b" / "nightlight_helper.py"), "/usr/bin/python3")
    assert "echo mine" in theirs.read_text()  # not ours: untouched
    theirs.unlink()
    helper._link_command(str(tmp_path / "a$HOME b" / "nightlight_helper.py"), "/usr/bin/python3")
    text = theirs.read_text()
    assert helper.WRAPPER_MARK in text and "'" in text and helper._is_our_wrapper(str(theirs))
    out = subprocess.run(["sh", "-n", str(theirs)], capture_output=True)
    assert out.returncode == 0
