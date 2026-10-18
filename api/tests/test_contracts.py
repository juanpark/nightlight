"""Tool contracts: what a proposal's result says about the state the server owns, so the model learns from results
instead of prompt rules (waiting cards, the last attempt, the safer step first, nothing to free, checking space)."""

import pytest

from nightlight_api import actions, db, demo, playbooks
from nightlight_api.errors import Outcome
from conftest import generation
from test_knowledge import _call, _tools
from test_playbooks import OFFERS
from test_real import FACTS, beat, enrolled
from test_real_jobs import _again


def _propose(uid, job, device="pi-1", turn="turn_c1", session="sess_test", **kw):
    return actions.propose(uid, session_id=session, turn_id=turn, generation=generation(uid), action_type=job,
                           device_id=device, params=kw.pop("params", {}), **kw)


# ------------------------------------------------------------------ 1. a waiting card answers another fix for it

def test_another_fix_for_the_same_problem_points_at_the_waiting_card(started):
    first = _propose(started, "rotate_logs", turn="turn_a")
    other = _propose(started, "clear_images", turn="turn_b")  # e.g. "고쳐줘" again, a different way to free the disk
    assert other["id"] == first["id"] and other["waiting"] and other["type"] == "rotate_logs"
    assert len([s for s in db.actions(started).get()
                if s.to_dict()["deviceId"] == "pi-1" and s.to_dict()["status"] == "pending"]) == 1
    actions.decide(started, first["id"], "deny")
    assert _propose(started, "clear_images", turn="turn_c")["type"] == "clear_images"  # decided: a new card


def test_waiting_tool_result_shape_and_unrelated_jobs_still_get_cards(started):
    tools, _ = _tools(started, "turn_t1")
    first = _call(tools, "rotate_logs", device_id="pi-1")
    assert first["status"] == "pending"
    tools, _ = _tools(started, "turn_t2")
    again = _call(tools, "clear_images", device_id="pi-1")
    assert again["status"] == "waiting" and again["actionId"] == first["actionId"] and again["awaitingTap"]
    assert again["proposed"]["job"] == "rotate_logs" and again["proposed"]["status"] == "pending"
    backup = _call(tools, "backup_world", device_id="game-1")  # another problem on another device: its own card
    assert backup["status"] == "pending" and backup["actionId"] != first["actionId"]


# ------------------------------------------------------------------ 2. the last attempt

def test_a_retry_after_a_failure_says_how_it_failed(started):
    demo.inject(started, "logs_locked", "pi-1")
    a = _propose(started, "rotate_logs", turn="turn_f1")
    assert "lastAttempt" not in a
    assert actions.decide(started, a["id"], "approve")[1]["status"] == "failed"
    tools, _ = _tools(started, "turn_f2")
    again = _call(tools, "rotate_logs", device_id="pi-1")
    assert again["status"] == "pending" and again["lastAttempt"]["status"] == "failed"
    assert "locked" in again["lastAttempt"]["reason"] and again["lastAttempt"]["minutesAgo"] == 0


# ------------------------------------------------------------------ 3. the safer step first

def test_restart_of_an_unbacked_world_puts_up_the_backup_first(started):
    tools, _ = _tools(started, "turn_s1")
    r = _call(tools, "restart_server", device_id="game-1")  # the seeded world is 9 days without a backup
    assert r["status"] == "safer_first" and r["insteadOf"] == "restart_server" and "9 days" in r["why"]
    assert r["proposed"]["job"] == "backup_world" and r["awaitingTap"]
    assert db.action(started, r["actionId"]).get().to_dict()["type"] == "backup_world"
    tools, _ = _tools(started, "turn_s2")
    again = _call(tools, "restart_server", device_id="game-1")  # asked again: still the same backup card
    assert again["status"] == "safer_first" and again["actionId"] == r["actionId"]
    actions.decide(started, r["actionId"], "approve")  # backed up: now the restart itself
    tools, _ = _tools(started, "turn_s3")
    assert _call(tools, "restart_server", device_id="game-1")["status"] == "pending"


def test_a_declined_backup_or_an_explicit_skip_is_not_a_trap(started):
    first = _propose(started, "restart_server", device="game-1", turn="turn_d1")
    assert first["type"] == "backup_world" and first["saferFirst"]
    actions.decide(started, first["id"], "deny")
    restart = _propose(started, "restart_server", device="game-1", turn="turn_d2")
    assert restart["type"] == "restart_server" and "back it up first" in restart["dryRun"]


def test_skip_backup_proposes_the_restart(started):
    tools, _ = _tools(started, "turn_k1")
    r = _call(tools, "restart_server", device_id="game-1", skip_backup=True)
    assert r["status"] == "pending" and "restart" in r["plan"].lower()


# ------------------------------------------------------------------ 4. real devices: nothing to free

def test_measured_measurements_are_kept_and_an_empty_cleanup_gets_no_card(client, started):
    dev = enrolled(client)
    facts = {**OFFERS, "os": "macOS 15.1", "allowedJobs": {**OFFERS["allowedJobs"],
                                                          "fix": ["empty_trash", "npm_cache", "docker_prune"]}}
    beat(client, dev["token"], facts)
    a = actions.request_inspection(started, session_id=None, turn_id="t_m", generation=generation(started),
                                   device_id=dev["deviceId"], what=["disk", "docker"])
    _again(dev["token"])
    beat(client, dev["token"], facts)
    out = ("Biggest known places (sizes):\nTrash: 2.1 GB\n"
           "Docker disk use:\nTYPE  TOTAL  ACTIVE  SIZE  RECLAIMABLE\nImages          3        3         1.1GB     0B (0%)")
    client.post(f"/helper/jobs/{a['id']}/result", json={"ok": True, "summary": "Checked", "output": out},
                headers={"X-Device-Token": dev["token"]})
    m = db.device(started, dev["deviceId"]).get().to_dict()["spaceMeasured"]
    assert m["empty_trash"]["gb"] == 2.1 and m["docker_prune"]["gb"] == 0.0
    assert "npm_cache" not in m  # no line: unknown (small, or not measurable), never a zero
    with pytest.raises(Outcome) as e:
        _propose(started, "fix", device=dev["deviceId"], turn="t_docker", params={"recipe": "docker_prune"})
    assert str(e.value) == "nothing_to_free" and e.value.info["measuredGb"] == 0.0
    for recipe in ("empty_trash", "npm_cache"):
        assert _propose(started, "fix", device=dev["deviceId"], turn=f"t_{recipe}",
                        params={"recipe": recipe})["status"] == "pending"
    tools, _ = _tools(started, "turn_n1")
    r = _call(tools, "clean_up", device_id=dev["deviceId"], recipe="docker_prune")
    assert r["status"] == "nothing_to_free" and r["recipe"] == "docker_prune"


def test_measure_reads_sizes_and_missing_places(started):
    mac = {"os": "macOS 15"}
    got = playbooks.measure("Biggest known places (sizes):\nHomebrew cache: 900 MB\nNot checked (macOS privacy): "
                            "Downloads, Desktop, Documents, Movies, Trash.", ["disk"], mac)
    assert got == {"brew_cleanup": 0.88}  # missing places stay unknown
    assert playbooks.measure("Docker disk use:\nImages  1  1  1GB  100B (0%)", ["docker"], mac) == \
        {"docker_prune": 0.0}  # bytes, never gigabytes
    assert playbooks.measure("", ["disk"], mac) == {}  # nothing said, nothing assumed


# ------------------------------------------------------------------ 5. check_space

def test_check_space_without_a_device_covers_every_sample_device(started):
    tools, _ = _tools(started, "turn_cs")
    r = _call(tools, "check_space")
    by = {d["device"]: d for d in r["devices"]}
    assert r["status"] == "done" and {"pi-1", "game-1"} <= set(by)
    game_logs = next(u for u in by["game-1"]["usedBy"] if u["what"] == "old log files")
    assert game_logs == {"what": "old log files", "sizeGb": 0.8, "freedBy": "rotate_logs"}  # missed before
    assert all("freedBy" not in u for u in by["game-1"]["usedBy"] if u["what"] != "old log files")  # world, backups
    assert {u.get("freedBy") for u in by["pi-1"]["usedBy"]} >= {"rotate_logs", "clear_images"}
    one = _call(tools, "check_space", device_id="pi-1")
    assert [d["device"] for d in one["devices"]] == ["pi-1"]


def test_check_space_on_a_real_device_runs_what_it_offers(client, started, monkeypatch):
    dev = enrolled(client)
    beat(client, dev["token"], {**FACTS, "allowedJobs": {"inspect": ["disk", "home"]}})
    tools, _ = _tools(started, "turn_cr")
    monkeypatch.setattr("nightlight_api.agent.DIAGNOSE_WAIT", 0)  # the device answers later: a follow-up narrates
    r = _call(tools, "check_space", device_id=dev["deviceId"])
    assert r["checked"] == ["disk", "home"] and r["not_offered"] == ["docker"] and r["status"] == "asked"
    a = next(s.to_dict() for s in db.actions(started).get() if s.to_dict().get("type") == "inspect")
    assert a["params"]["what"] == ["disk", "home"] and a["playbook"] == "disk_full"
    none = enrolled(client, "Bare")
    beat(client, none["token"], FACTS)
    r = _call(tools, "check_space", device_id=none["deviceId"])
    assert r["status"] == "error" and r["not_offered"] == ["disk", "home", "docker"]


# ------------------------------------------------------------------ 6. sample-home app updates

def test_update_plex_on_the_sample_home_is_a_real_card(started):
    tools, _ = _tools(started, "turn_u1")
    r = _call(tools, "update_app", device_id="mac-1", app="plex")
    assert r["status"] == "pending" and "1.41.2 → 1.41.3" in r["plan"] and r["risk"] == "service"
    code, body = actions.decide(started, r["actionId"], "approve")
    assert body["status"] == "done"
    plex = db.services(started, "mac-1").document("plex").get().to_dict()
    assert plex["version"] == "1.41.3" and plex["updateAvailable"] is False and plex["image"].endswith(":1.41.3")
    tools, _ = _tools(started, "turn_u2")
    assert _call(tools, "update_app", device_id="mac-1", app="plex")["status"] == "error"  # nothing newer now
    assert _call(tools, "update_app", device_id="pi-1", app="teslamate")["status"] == "error"  # no known version
    assert _call(tools, "update_app", device_id="game-1", app="minecraft")["status"] == "error"  # update_server's


def test_a_waiting_update_for_one_app_never_answers_for_another(started):  # Codex contracts #3
    db.services(started, "mac-1").document("homebridge").update({"updateAvailable": True,
                                                                 "latestVersion": "2026-10-15", "version": "2026-10-01"})
    plex = _propose(started, "update_app", device="mac-1", turn="turn_p1", params={"app": "plex"})
    other = _propose(started, "update_app", device="mac-1", turn="turn_p2", params={"app": "homebridge"})
    assert other["id"] != plex["id"] and not other.get("waiting") and other["params"] == {"app": "homebridge"}


def test_a_failed_automatic_safer_step_is_a_failed_step(started):  # Codex contracts #2
    from nightlight_api import trust as trustlib, turns
    db.trust_doc(started, "sim", "backup_world").set({**trustlib.new_doc("backup_world", generation(started)),
                                                       "level": "auto"})
    db.device(started, "game-1").update({"simFailNext": "backup_world"})
    tools, _ = _tools(started, "turn_af")
    r = _call(tools, "restart_server", device_id="game-1")
    assert r["status"] == "safer_first" and r["proposed"]["status"] == "failed" and not r["awaitingTap"]
    assert "didn't respond" in r["proposed"]["result"]
    assert turns._ok(r) is False and "(it didn't work)" in turns._commentary("restart_server", r)[0]
