"""Game-server care: world backups, restarts, updates, with the right risk and trust behaviour."""

import pytest

from nightlight_api import actions, db, demo
from nightlight_api.errors import ApiError
from conftest import generation


def svc(uid):
    return db.services(uid, "game-1").document("minecraft").get().to_dict()


def dev(uid):
    return db.device(uid, "game-1").get().to_dict()


def propose(uid, action_type, turn="turn_g1"):
    return actions.propose(uid, session_id="sess_test", turn_id=turn, generation=generation(uid),
                           action_type=action_type, device_id="game-1", params={})


def test_seeded_game_server_shows_its_problems(started):
    d, s = dev(started), svc(started)
    checks = {f["check"] for f in d["findings"]}
    assert {"backup_overdue", "update_available"} <= checks and d["status"] == "warn"
    assert s["status"] == "warn" and s["players"]["online"] == 2


def test_backup_world_resolves_the_overdue_backup(started):
    a = propose(started, "backup_world")
    assert a["riskClass"] == "routine" and "players can keep playing" in a["dryRun"]
    code, body = actions.decide(started, a["id"], "approve")
    assert code == 202 and body["status"] == "done"
    assert svc(started)["lastBackupDaysAgo"] == 0
    assert "backup_overdue" not in {f["check"] for f in dev(started)["findings"]}


def test_lag_then_restart_clears_memory(started):
    demo.inject(started, "server_lagging", "game-1")
    assert dev(started)["status"] == "crit"
    a = propose(started, "restart_server", turn="turn_g2")
    assert a["riskClass"] == "service" and "disconnected" in a["dryRun"]
    actions.decide(started, a["id"], "approve")
    d = dev(started)
    assert d["vitals"]["mem"] == 45 and "memory_high" not in {f["check"] for f in d["findings"]}


def test_update_backs_up_and_updates(started):
    a = propose(started, "update_server")
    actions.decide(started, a["id"], "approve")
    s = svc(started)
    assert s["version"] == "1.21.5" and s["updateAvailable"] is False and s["lastBackupDaysAgo"] == 0


def test_restart_can_never_run_on_its_own(client, started):
    r = client.put("/api/trust/restart_server", json={"level": "auto"})
    assert r.status_code == 200 and r.json()["level"] == "ask_new"  # clamped to the service-risk ceiling
    demo.inject(started, "server_lagging", "game-1")
    a = propose(started, "restart_server", turn="turn_g3")
    assert a["status"] == "pending"  # not allowlisted: always asks


def test_game_actions_dont_apply_to_other_devices(started):
    with pytest.raises(ValueError):
        actions.propose(started, session_id="sess_test", turn_id="turn_x", generation=generation(started),
                        action_type="restart_server", device_id="pi-1", params={})


def test_game_incidents_only_on_game_servers(client, started):
    r = client.post("/api/demo/inject", json={"kind": "server_lagging", "deviceId": "pi-1"})
    assert r.status_code == 422
    with pytest.raises(ApiError):
        demo.inject(started, "backup_overdue", "nas-1")
