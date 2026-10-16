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
