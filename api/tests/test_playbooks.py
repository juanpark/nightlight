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
    assert by["docker_images"]["say"].startswith("Docker images take up to 5.2GB")
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
    assert jobs == [{"id": aid, "type": "inspect", "params": {"what": ["disk", "docker"]}}]
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
    assert helper._empty_dir([".Trash"]) is True
    assert list(trash.iterdir()) == [] and (keep / "precious").exists()


def test_a_linked_parent_folder_is_refused(helper, monkeypatch, tmp_path):  # review C #1
    home, keep = _home(helper, monkeypatch, tmp_path)
    (home / "Library").mkdir()
    (home / "Library" / "Developer").symlink_to(keep)  # ~/Library/Developer -> somewhere else
    (keep / "Xcode" / "DerivedData").mkdir(parents=True)
    (keep / "Xcode" / "DerivedData" / "precious").write_text("x")
    assert helper._empty_dir(["Library", "Developer", "Xcode", "DerivedData"]) is False
    assert (keep / "Xcode" / "DerivedData" / "precious").exists()
    (home / ".Trash").symlink_to(keep)  # the folder itself swapped for a link
    assert helper._empty_dir([".Trash"]) is False and (keep / "precious").exists()


def test_a_refused_clean_up_reports_failure(helper, monkeypatch, tmp_path):  # review C #1
    home, keep = _home(helper, monkeypatch, tmp_path)
    (home / ".Trash").symlink_to(keep)
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    helper._save_config({"token": "x", "manage": "strict", "allow": {"fix": ["all"]}, "macPrivateFolders": True})
    ok, summary, _ = helper.run_fix("empty_trash")
    assert not ok and "didn't fully work" in summary and (keep / "precious").exists()


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
