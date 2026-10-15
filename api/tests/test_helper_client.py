"""The on-device helper: HTTPS only, no redirects with credentials, safe token file, minimal image names, retries."""

import http.server
import importlib.util
import json
import os
import stat
import threading
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
