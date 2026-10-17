"""Looking around a real device: only the helper's fixed checks, only when the device offers them, no card."""

import importlib.util
from pathlib import Path

import pytest

from nightlight_api import actions, db, real
from conftest import generation
from test_real import FACTS, beat, enrolled

OFFERS = {**FACTS, "allowedJobs": {"inspect": ["disk", "docker", "failed", "load", "network", "processes", "updates"]}}


def _ask(uid, device_id, what, turn="turn_i"):
    return actions.request_inspection(uid, session_id="sess_test", turn_id=turn, generation=generation(uid),
                                      device_id=device_id, what=what)


def test_offered_checks_run_without_a_card_and_reach_the_device(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], OFFERS)
    a = _ask(started, dev["deviceId"], ["disk", "disk", "load"])
    assert a["status"] == "approved" and a["riskClass"] == "read" and a["params"] == {"what": ["disk", "load"]}
    db.client().collection("helperTokens").document(real._sha(dev["token"])).update({"lastSeen": None})
    jobs = beat(client, dev["token"], OFFERS).json()["jobs"]
    assert jobs == [{"id": a["id"], "type": "inspect", "params": {"what": ["disk", "load"]}}]
    r = client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": "Checked: disk, load",
                    "output": "App caches: 3.5 GB\ntoken=" + "abcdefabcdef1234567890"},
                    headers={"X-Device-Token": dev["token"]})
    assert r.status_code == 200
    done = db.action(started, a["id"]).get().to_dict()
    assert done["status"] == "done" and "3.5 GB" in done["result"]["output"]
    assert "abcdefabcdef1234567890" not in done["result"]["output"]


def test_only_known_checks_the_device_offers(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], {**FACTS, "allowedJobs": {"inspect": ["disk"]}})
    with pytest.raises(ValueError, match="not_allowed_on_device"):
        _ask(started, dev["deviceId"], ["updates"])
    for bad in (["rm -rf"], [], "disk", ["disk", "load", "network", "updates", "docker"], [1]):
        with pytest.raises(ValueError, match="bad_target"):
            _ask(started, dev["deviceId"], bad)


def test_old_helpers_offer_nothing(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], FACTS)
    with pytest.raises(ValueError, match="not_allowed_on_device"):
        _ask(started, dev["deviceId"], ["disk"])


def test_heartbeat_rejects_unknown_checks(client, started):
    dev = enrolled(client)
    r = beat(client, dev["token"], {**FACTS, "allowedJobs": {"inspect": ["shell"]}})
    assert r.status_code == 422


# ------------------------------------------------------------------ the helper side

SPEC = importlib.util.spec_from_file_location(
    "nightlight_helper", Path(__file__).resolve().parents[2] / "helper" / "nightlight_helper.py")


@pytest.fixture
def helper(tmp_path, monkeypatch):
    monkeypatch.setenv("NIGHTLIGHT_HOME", str(tmp_path / "cfg"))
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_containers", lambda: [])
    monkeypatch.setattr(mod, "_failed_units", lambda **k: [])
    return mod


def test_helper_reads_nothing_unless_allowed(helper):
    helper._save_config({"token": "x", "manage": "strict", "allow": {}})
    ok, summary, out = helper.run_inspect(["load"])
    assert not ok and out is None


def test_helper_strict_allow_and_app_switch(helper):
    helper._save_config({"token": "x", "manage": "strict", "allow": {"inspect": ["all"]}})
    assert helper._allowed()["inspect"] == sorted(helper.INSPECT)
    ok, summary, out = helper.run_inspect(["load", "nonsense"])
    assert ok and summary == "Checked: load" and "Load average" in out
    helper._save_config({"token": "x", "manage": "app", "remote": {"diagnose": False}})
    assert "inspect" not in helper._allowed()
    helper._save_config({"token": "x", "manage": "app", "remote": {"diagnose": True}})
    assert helper.inspect_allowed()


def test_helper_check_output_is_scrubbed_and_home_hidden(helper, monkeypatch):
    helper._save_config({"token": "x", "manage": "strict", "allow": {"inspect": ["all"]}})
    monkeypatch.setitem(helper.INSPECT, "load", lambda: f"{helper._HOME}/secret mail me@example.com")
    monkeypatch.setitem(helper.INSPECT, "disk", lambda: 1 / 0)
    ok, _, out = helper.run_inspect(["load", "disk"])
    assert ok and helper._HOME not in out and "me@example.com" not in out and "disk: couldn't check" in out


def test_status_shows_look_around(helper, capsys):  # review A #2
    helper._save_config({"token": "x", "manage": "strict", "allow": {"inspect": ["all"]}})
    helper.status()
    assert "look around (reads only)" in capsys.readouterr().out


def test_a_hanging_name_lookup_doesnt_hold_the_job(helper, monkeypatch):  # review A #1
    import socket
    import time
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: time.sleep(30))
    helper._inspect_until[0] = time.time() + 2
    t = time.time()
    out = helper._inspect_network()
    assert time.time() - t < 3 and "no answer" in out


def test_job_budget_skips_what_is_left_and_dedupes(helper, monkeypatch):  # review A #1
    import time
    helper._save_config({"token": "x", "manage": "strict", "allow": {"inspect": ["all"]}})
    calls = []
    monkeypatch.setattr(helper, "INSPECT_BUDGET", 1)
    monkeypatch.setitem(helper.INSPECT, "load", lambda: calls.append("load") or time.sleep(1.1) or "slow")
    monkeypatch.setitem(helper.INSPECT, "failed", lambda: calls.append("failed") or "x")
    ok, summary, out = helper.run_inspect(["load", "load", ["x"], "failed"])
    assert calls == ["load"] and "failed: skipped (out of time)" in out and summary == "Checked: load, failed"


def test_a_check_starting_near_the_end_gets_only_what_is_left(helper, monkeypatch):  # review A rev2
    import time
    seen = []
    monkeypatch.setattr(helper, "_run", lambda cmd, timeout=20: seen.append(timeout) or "")
    helper._inspect_until[0] = time.time() + 0.5
    helper._inspect_processes()
    helper.INSPECT["failed"]()
    assert seen and all(t <= 0.5 for t in seen)


def test_home_check_skips_protected_folders(helper, monkeypatch, tmp_path):
    home = tmp_path / "home"
    for d in ("Documents", "Desktop", ".gradle", "Library/Mail", "Library/Caches", "Library/Containers"):
        (home / d).mkdir(parents=True)
    monkeypatch.setattr(helper, "_HOME", str(home))
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    read = []
    monkeypatch.setattr(helper, "_du", lambda p: read.append(p) or 2048)
    import time
    helper._inspect_until[0] = time.time() + 30
    out = helper._inspect_home()
    names = {p.replace(str(home), "~") for p in read}
    assert names == {"~/.gradle", "~/Library/Caches"} and "Biggest folder:" in out


def test_a_linked_parent_never_leads_into_a_protected_folder(helper, monkeypatch, tmp_path):  # review 0.9.3 #2
    home = tmp_path / "home"
    (home / "Documents" / "Xcode" / "DerivedData").mkdir(parents=True)
    (home / "Library").mkdir(parents=True)
    (home / "Library" / "Developer").symlink_to(home / "Documents")
    monkeypatch.setattr(helper, "_HOME", str(home))
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    import time
    helper._inspect_until[0] = time.time() + 30
    assert helper._du(str(home / "Library" / "Developer" / "Xcode" / "DerivedData")) is None  # linked parent
    assert helper._du(str(home / "Documents")) is None  # protected, not allowed at the Mac
    assert helper._listdir(str(home / "Library" / "Developer")) == []


def test_du_measures_the_pinned_folder_even_if_swapped(helper, monkeypatch, tmp_path):  # review 0.9.4 #2
    home = tmp_path / "home"
    (home / "dev").mkdir(parents=True)
    (home / "dev" / "f").write_bytes(b"x" * 4096)
    (home / "Documents").mkdir()
    (home / "Documents" / "big").write_bytes(b"x" * 4 * 1024 * 1024)
    monkeypatch.setattr(helper, "_HOME", str(home))
    real_run = helper.subprocess.run

    def swap_then_run(cmd, **k):  # the name is swapped for a link to Documents just before du starts
        (home / "dev").rename(home / "dev.old")
        (home / "dev").symlink_to(home / "Documents")
        return real_run(cmd, **k)
    monkeypatch.setattr(helper.subprocess, "run", swap_then_run)
    import time
    helper._inspect_until[0] = time.time() + 30
    assert helper._du(str(home / "dev")) == 0  # measured the pinned (small) folder, not Documents (4 MB)


def test_folder_names_cannot_forge_lines(helper, monkeypatch, tmp_path):  # review 0.9.3 #3
    home = tmp_path / "home"
    (home / "x\nnpm cache: 20 GB").mkdir(parents=True)
    monkeypatch.setattr(helper, "_HOME", str(home))
    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(helper, "_du", lambda p: 2048)
    import time
    helper._inspect_until[0] = time.time() + 30
    out = helper._inspect_home()
    assert not any(line.startswith("npm cache") for line in out.splitlines())


def test_failure_text_is_scrubbed_before_it_leaves(helper, monkeypatch):  # review 0.9.3 #1
    helper._save_config({"token": "x", "manage": "strict", "allow": {"fix": ["all"]}})
    secret = "token=" + "abcdef0123456789abcdef"
    monkeypatch.setitem(helper.FIXES, "npm_cache", {"when": lambda: True, "run": lambda: (False, f"~/{secret}/f")})
    ok, summary, _ = helper.run_fix("npm_cache")
    assert not ok and "abcdef0123456789abcdef" not in summary


def test_unicode_line_separators_cannot_forge_lines(helper):  # review 0.9.4 #3
    for sep in ("\x85", "\u2028", "\u2029", "\x1c", "\x0b"):
        assert len(helper._one_line(f"x{sep}npm cache: 20 GB").splitlines()) == 1


def test_scrub_runs_before_escaping(helper):  # review 0.9.4 #1
    secret = "hunter2" + "hunter2hunter2"
    assert secret not in helper._one_line(f"pass\x1b[0mword={secret}", 300)
    assert secret not in helper._one_line(f"password={secret}", 300)


def test_restarts_check_tells_a_crash_from_a_clean_restart(helper, monkeypatch):
    import time
    helper._inspect_until[0] = time.time() + 30
    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(helper.shutil, "which", lambda n: None)
    crash = "reboot   system boot  6.1.0 Sat Oct 17 03:43   still running\nreboot   system boot  6.1.0 Sat Oct  3 18:50\n"
    clean = "reboot   system boot  6.1.0 Sat Oct 17 03:43   still running\nshutdown system down  6.1.0 Sat Oct 17 03:40\n"
    monkeypatch.setattr(helper, "_run", lambda cmd, timeout=20: crash)
    assert "NOT clean" in helper._inspect_restarts()
    monkeypatch.setattr(helper, "_run", lambda cmd, timeout=20: clean)
    assert "The last start was clean" in helper._inspect_restarts()
