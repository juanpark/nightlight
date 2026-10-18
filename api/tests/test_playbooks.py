"""Playbooks: known problems handled in code (no AI): checks run, causes matched, clean-up cards only if allowed."""

import importlib.util
from pathlib import Path

import pytest

from nightlight_api import db, playbooks, real
from test_real import FACTS, beat, enrolled

OFFERS = {**FACTS, "diskPct": 93.0, "allowedJobs": {"inspect": sorted(real.INSPECT), "fix": ["empty_trash", "npm_cache"]}}
OUTPUT = ("Biggest known places (sizes):\nApp caches: 3.5 GB\nnpm cache: 1.5 GB\nTrash: 2.1 GB\nHomebrew cache: 900 MB\n"
          "Docker disk use:\nTYPE  TOTAL  ACTIVE  SIZE  RECLAIMABLE\nImages          12        3         8.1GB     5.2GB (64%)")


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


def test_causes_are_matched_in_code_with_thresholds_and_permissions():
    book = playbooks.library()["disk_full"]
    got = playbooks.evaluate(book, OUTPUT, {"allowedJobs": {"fix": ["empty_trash"]}})
    by = {f["cause"]: f for f in got["found"]}
    assert list(by) == ["trash", "brew", "npm", "docker_images", "app_caches"]  # playbook order, Downloads absent
    assert by["trash"]["fixAllowed"] and not by["npm"]["fixAllowed"] and "advice" in by["app_caches"]
    assert by["docker_images"]["say"].startswith("App downloads (Docker images) that no app uses take up to 5.2GB")
    small = playbooks.evaluate(book, "Trash: 120 MB", {})
    assert small["found"] == [] and small["nothing"]


def test_library_is_consistent():
    for book in playbooks.library().values():
        assert set(book["checks"]) <= set(real.INSPECT)
        assert all(c.get("fix") is None or c["fix"] in real.FIX for c in book["causes"])


def test_run_from_the_app_gives_findings_and_cards_for_allowed_fixes(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], OFFERS)
    offered = client.get(f"/api/devices/{dev['deviceId']}/playbooks").json()["playbooks"]
    assert offered[0] == {"id": "disk_full", "title": "Disk filling up", "about": offered[0]["about"], "suggested": True}
    sid = client.post("/api/chat/sessions", json={}).json()["sessionId"]
    r = client.post(f"/api/devices/{dev['deviceId']}/playbooks/disk_full/run", json={"sessionId": sid})
    assert r.status_code == 202
    aid = r.json()["actionId"]
    _again(dev["token"])
    jobs = beat(client, dev["token"], OFFERS).json()["jobs"]
    assert jobs == [{"id": aid, "type": "inspect", "params": {"what": ["disk", "home", "docker"]}}]
    client.post(f"/helper/jobs/{aid}/result", json={"ok": True, "summary": "Checked", "output": OUTPUT},
                headers={"X-Device-Token": dev["token"]})
    pb = db.action(started, aid).get().to_dict()["result"]["playbook"]
    assert [f["cause"] for f in pb["found"] if f.get("fixAllowed")] == ["trash", "npm"]
    cards = {s.id: s.to_dict() for s in db.actions(started).get() if s.to_dict().get("type") == "fix"}
    assert sorted(c["params"]["recipe"] for c in cards.values()) == ["empty_trash", "npm_cache"]
    assert {f["card"] for f in pb["found"] if f.get("fixAllowed")} == set(cards)  # words point at real cards
    cards = list(cards.values())
    assert all(c["status"] == "pending" and ("Can't be undone" in c["rollback"] or "Nothing to undo" in c["rollback"])
               for c in cards)
    # repeated result report: no duplicate cards
    client.post(f"/helper/jobs/{aid}/result", json={"ok": True, "summary": "Checked", "output": OUTPUT},
                headers={"X-Device-Token": dev["token"]})
    assert len([s for s in db.actions(started).get() if s.to_dict().get("type") == "fix"]) == 2


def test_approved_fix_reaches_the_device_and_reports(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], OFFERS)
    from nightlight_api import actions
    from conftest import generation
    a = actions.propose(started, session_id="sess_test", turn_id="t1", generation=generation(started),
                        action_type="fix", device_id=dev["deviceId"], params={"recipe": "npm_cache"})
    assert a["status"] == "pending"
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    _again(dev["token"])
    jobs = beat(client, dev["token"], OFFERS).json()["jobs"]
    assert jobs == [{"id": a["id"], "type": "fix", "params": {"recipe": "npm_cache"}}]
    client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": "Done. Freed 1.4 GB"},
                headers={"X-Device-Token": dev["token"]})
    done = db.action(started, a["id"]).get().to_dict()
    assert done["status"] == "done" and done["result"] == {"ok": True, "summary": "Done. Freed 1.4 GB"}


def test_fixes_only_when_the_device_allows_them(client, started):
    from nightlight_api import actions
    from conftest import generation
    dev = enrolled(client)
    beat(client, dev["token"], OFFERS)
    for recipe in ("docker_prune", "rm_everything"):
        with pytest.raises(ValueError):
            actions.propose(started, session_id="sess_test", turn_id="t2", generation=generation(started),
                            action_type="fix", device_id=dev["deviceId"], params={"recipe": recipe})
    assert beat(client, dev["token"], {**FACTS, "allowedJobs": {"fix": ["rm_everything"]}}).status_code == 422


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


def test_helper_fix_needs_permission_and_reports_space(helper, monkeypatch):
    ran = []
    monkeypatch.setitem(helper.FIXES, "npm_cache", {"when": lambda: True, "run": lambda: ran.append(1) or (True, "")})
    helper._save_config({"token": "x", "manage": "strict", "allow": {}})
    ok, summary, _ = helper.run_fix("npm_cache")
    assert not ok and ran == []
    helper._save_config({"token": "x", "manage": "app", "remote": {"cleanup": True}})
    assert "npm_cache" in helper._allowed()["fix"]
    ok, summary, _ = helper.run_fix("npm_cache")
    assert ok and ran == [1] and "GB free now" in summary
    assert helper.run_fix("rm -rf /")[0] is False


def _home(helper, monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(helper, "_HOME", str(home))
    keep = tmp_path / "keep"
    keep.mkdir()
    (keep / "precious").write_text("x")
    return home, keep


def test_empty_dir_never_follows_links(helper, monkeypatch, tmp_path):
    home, keep = _home(helper, monkeypatch, tmp_path)
    trash = home / ".Trash"
    trash.mkdir()
    (trash / "old").write_text("x")
    (trash / "sub").mkdir()
    (trash / "sub" / "deep").write_text("x")
    (trash / "link").symlink_to(keep)
    assert helper._empty_dir([".Trash"]) == (True, "")
    assert list(trash.iterdir()) == [] and (keep / "precious").exists()


def test_a_linked_parent_folder_is_refused(helper, monkeypatch, tmp_path):  # review C #1
    home, keep = _home(helper, monkeypatch, tmp_path)
    (home / "Library").mkdir()
    (home / "Library" / "Developer").symlink_to(keep)  # ~/Library/Developer -> somewhere else
    (keep / "Xcode" / "DerivedData").mkdir(parents=True)
    (keep / "Xcode" / "DerivedData" / "precious").write_text("x")
    ok, why = helper._empty_dir(["Library", "Developer", "Xcode", "DerivedData"])
    assert not ok and "~/Library/Developer is a link" in why
    assert (keep / "Xcode" / "DerivedData" / "precious").exists()
    (home / ".Trash").symlink_to(keep)  # the folder itself swapped for a link
    ok, why = helper._empty_dir([".Trash"])
    assert not ok and "link" in why and (keep / "precious").exists()


def test_a_refused_clean_up_reports_failure(helper, monkeypatch, tmp_path):  # review C #1
    home, keep = _home(helper, monkeypatch, tmp_path)
    (home / ".Trash").symlink_to(keep)
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    helper._save_config({"token": "x", "manage": "strict", "allow": {"fix": ["all"]}, "macPrivateFolders": True})
    ok, summary, _ = helper.run_fix("empty_trash")
    assert not ok and "is a link" in summary and (keep / "precious").exists()


def test_no_card_claimed_when_none_could_be_made(client, started, monkeypatch):  # review C #3
    def refuse(*a, **k):
        raise ValueError("not_allowed_on_device")
    dev = enrolled(client)
    beat(client, dev["token"], OFFERS)
    sid = client.post("/api/chat/sessions", json={}).json()["sessionId"]
    aid = client.post(f"/api/devices/{dev['deviceId']}/playbooks/disk_full/run", json={"sessionId": sid}).json()[
        "actionId"]
    db.action(started, aid).update({"followUp": "wanted"})  # the chat stopped waiting: a follow-up narrates
    _again(dev["token"])
    beat(client, dev["token"], OFFERS)
    monkeypatch.setattr(real, "card", refuse)
    client.post(f"/helper/jobs/{aid}/result", json={"ok": True, "summary": "Checked", "output": OUTPUT},
                headers={"X-Device-Token": dev["token"]})
    a = db.action(started, aid).get().to_dict()
    assert all(f.get("card") is None for f in a["result"]["playbook"]["found"])
    assert not [s for s in db.actions(started).get() if s.to_dict().get("type") == "fix"]
    turn = db.turns(started, sid).document(a["continuationTurnId"]).get().to_dict()
    assert "I've put up a card" not in turn["input"] and "no card could be made" in turn["input"]


def test_a_failing_item_is_named_with_its_reason(helper, monkeypatch, tmp_path):
    home, _ = _home(helper, monkeypatch, tmp_path)
    trash = home / ".Trash"
    (trash / "locked").mkdir(parents=True)
    (trash / "locked" / "f").write_text("x")
    import os
    os.chmod(trash / "locked", 0o500)  # can't delete inside it
    try:
        ok, why = helper._empty_dir([".Trash"])
    finally:
        os.chmod(trash / "locked", 0o700)
    assert not ok and "~/.Trash/locked/f" in why and "permission" in why


# ------------------------------------------------------------------ from a QA run on a real Debian VM

def test_one_big_log_is_named_and_the_journal_is_apart(helper, monkeypatch, tmp_path):
    logs = tmp_path / "log"
    (logs / "home-backup").mkdir(parents=True)
    (logs / "home-backup" / "backup-debug.log").write_bytes(b"x" * 3 * 1024 * 1024)
    (logs / "home-backup" / "small.log").write_bytes(b"x")
    (logs / "journal").mkdir()
    (logs / "journal" / "system.journal").write_bytes(b"x" * 2 * 1024 * 1024)
    (logs / "syslog").write_bytes(b"x" * 1024)
    (logs / "elsewhere").symlink_to(tmp_path)  # never followed
    monkeypatch.setattr(helper, "_LOGS", str(logs))
    monkeypatch.setattr(helper, "BIG_LOG_MB", 1)
    monkeypatch.setattr(helper, "_disk_places", lambda: [])
    monkeypatch.setattr(helper, "_ROOT", str(tmp_path / "noroot"))  # the main-disk scan has its own tests
    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(helper, "_run", lambda *a, **k: pytest.fail("the journal is measured on disk"))
    helper._inspect_until[0] = __import__("time").time() + 30
    out = helper._inspect_disk()
    assert "Big log: /var/log/home-backup/backup-debug.log: 3 MB" in out
    assert "System journal: 2 MB" in out and "/var/log/journal" not in out  # the journal is never a "big log"
    assert "System logs" not in out  # 3 MB: under the 50 MB line
    assert "elsewhere" not in out


def test_the_log_scan_stops_when_the_time_is_up(helper, monkeypatch, tmp_path):
    logs = tmp_path / "log"
    logs.mkdir()
    for i in range(20):
        (logs / f"app{i}.log").write_bytes(b"x")
    monkeypatch.setattr(helper, "_LOGS", str(logs))
    now, until = [1000.0], [1100.0]
    looked = []

    def slow_left(cap):  # a synthetic clock: every look costs 10 seconds
        looked.append(cap)
        now[0] += 10
        return max(0.0, min(cap, until[0] - now[0]))
    monkeypatch.setattr(helper, "_left", slow_left)
    got = helper._scan(str(logs))
    assert 0 < len(got) < 20 and len(looked) < 15  # stopped near the deadline, the rest never listed
    monkeypatch.setattr(helper, "LOG_NAMES", 3)
    until[0] = now[0] + 10_000
    assert len(helper._scan(str(logs))) == 3  # and never more than the cap
    until[0] = now[0]
    assert helper._logs() == (0, None, [])  # out of time: nothing measured, nothing blamed


def test_a_big_log_is_explained_without_a_card():
    book = playbooks.library()["disk_full"]
    out = ("Biggest known places (sizes):\nSystem logs (not counting the journal): 14.2 GB\nSystem journal: 120 MB\n"
           "Big log: /var/log/home-backup/backup-debug.log: 14.0 GB\nBig log: /var/log/syslog.1: 300 MB")
    got = playbooks.evaluate(book, out, {"allowedJobs": {"fix": ["docker_prune"]}})
    assert [f["cause"] for f in got["found"]] == ["big_log"]  # the small journal and the 300 MB log aren't blamed
    f = got["found"][0]
    assert "/var/log/home-backup/backup-debug.log" in f["say"] and '"home-backup" writes it' in f["say"]
    assert "fix" not in f and "Investigate" in f["advice"]
    assert "card" not in playbooks.summary(got)


def test_small_docker_leftovers_count():
    book = playbooks.library()["disk_full"]
    out = "TYPE  TOTAL  ACTIVE  SIZE  RECLAIMABLE\nImages          5        2         2.1GB     712MB (33%)"
    assert [f["cause"] for f in playbooks.evaluate(book, out, {})["found"]] == ["docker_images"]


def test_a_root_clean_up_the_device_cannot_run_is_said_plainly():
    book = playbooks.library()["disk_full"]
    got = playbooks.evaluate(book, "System journal: 2.0G", {"allowedJobs": {"fix": ["docker_prune"]}})
    f = got["found"][0]
    assert not f["fixAllowed"] and f["fixUnavailable"] and "sudo journalctl" in f["advice"]
    said = playbooks.summary(got)
    assert "isn't available on this device" in said and "administrator" not in said  # no reason the server can't know
    off = playbooks.evaluate(book, "System journal: 2.0G", {"permissions": {"cleanup": False}})
    assert "fixUnavailable" not in off["found"][0] and "isn't switched on" in playbooks.summary(off)


def test_root_clean_ups_are_offered_only_when_root_works(helper, monkeypatch):
    import subprocess
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(helper.os, "geteuid", lambda: 1000)
    asked = []

    def sudo(cmd, **k):
        asked.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, b"", b"sudo: a password is required")
    monkeypatch.setattr(helper.subprocess, "run", sudo)
    fixes = helper._available_fixes()
    assert "apt_clean" not in fixes and "journal_vacuum" not in fixes and "docker_prune" in fixes
    assert asked in ([], [["sudo", "-n", "true"]])  # asked once (never under NoNewPrivileges), and never prompts
    helper._ROOT_OK.clear()
    monkeypatch.setattr(helper.os, "geteuid", lambda: 0)
    assert {"apt_clean", "journal_vacuum"} <= set(helper._available_fixes())
    helper._save_config({"token": "x", "manage": "app", "remote": {"cleanup": True}})
    assert "journal_vacuum" in helper._allowed()["fix"]


def test_a_failed_clean_up_says_why_in_plain_words(helper, monkeypatch):
    import subprocess

    def fails(err):
        return lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", err)
    monkeypatch.setattr(helper.subprocess, "run", fails('sudo: The "no new privileges" flag is set, which prevents '
                                                        "sudo from running as root."))
    ok, why = helper._fix_cmd(["sudo", "-n", "journalctl", "--vacuum-size=200M"])
    assert not ok and why == "it needs administrator rights the helper doesn't have"
    # sudo let it run, but the command itself failed (apt's lock): no claim about rights, no raw text
    monkeypatch.setattr(helper.subprocess, "run", fails("E: Could not get lock /var/lib/dpkg/lock-frontend. "
                                                        "Permission denied, are you root?"))
    assert helper._fix_cmd(["sudo", "-n", "apt-get", "clean"]) == (False, "")
    monkeypatch.setattr(helper.subprocess, "run", fails("npm ERR! EACCES: permission denied token=abc123"))
    assert helper._fix_cmd(["npm", "cache", "clean", "--force"]) == (False, "")

    def absent(cmd, **k):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(helper.subprocess, "run", absent)
    assert helper._fix_cmd(["npm", "cache", "clean", "--force"]) == (False, "")
    monkeypatch.setitem(helper.FIXES, "npm_cache", {"when": lambda: True, "run": lambda: (False, "")})
    helper._save_config({"token": "x", "manage": "strict", "allow": {"fix": ["all"]}})
    ok, summary, _ = helper.run_fix("npm_cache")
    assert not ok and summary.startswith("Couldn't run that clean-up on this device.") and "rights" not in summary
    monkeypatch.setitem(helper.FIXES, "journal_vacuum", {"when": lambda: True, "run": lambda: (
        False, "it needs administrator rights the helper doesn't have")})
    helper._save_config({"token": "x", "manage": "strict", "allow": {"fix": ["all"]}})
    ok, summary, _ = helper.run_fix("journal_vacuum")
    assert not ok and summary.startswith(
        "Couldn't run that clean-up on this device: it needs administrator rights the helper doesn't have.")
