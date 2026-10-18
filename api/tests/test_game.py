"""Game-server care: world backups, restarts, updates, with the right risk and trust behaviour."""

import pytest

from nightlight_api import actions, db, demo
from nightlight_api.errors import ApiError
from conftest import generation


def svc(uid):
    return db.services(uid, "game-1").document("minecraft").get().to_dict()


def dev(uid):
    return db.device(uid, "game-1").get().to_dict()


def propose(uid, action_type, turn="turn_g1", **kw):
    return actions.propose(uid, session_id="sess_test", turn_id=turn, generation=generation(uid),
                           action_type=action_type, device_id="game-1", params={}, **kw)


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
    a = propose(started, "restart_server", turn="turn_g2", skip_safer=True)
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
    a = propose(started, "restart_server", turn="turn_g3", skip_safer=True)
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


# ---------------------------------------------------------------- regressions from the slice-4 review

def test_retry_after_update_finds_the_completed_action(started):  # H1
    a = propose(started, "update_server", turn="turn_upd")
    actions.decide(started, a["id"], "approve")
    again = propose(started, "update_server", turn="turn_upd")  # recovery of the same turn
    assert again["id"] == a["id"] and again["status"] == "done"
    with pytest.raises(ValueError):  # a fresh turn with nothing to update is still not applicable
        propose(started, "update_server", turn="turn_fresh")


def test_refresh_is_idempotent_and_drops_cleared_problems(started):  # M1
    from nightlight_api import sim
    nas = dict(db.device(started, "nas-1").get().to_dict(), id="nas-1")
    svcs = {s.id: s.to_dict() for s in db.services(started, "nas-1").get()}
    once, s1 = sim.refresh(nas, svcs)
    twice, s2 = sim.refresh(once, s1)
    assert once["findings"] == twice["findings"]
    assert sum(f["check"] == "backup_never_test_restored" for f in twice["findings"]) == 1
    s2["backup"]["findings"] = []
    cleared, _ = sim.refresh(twice, s2)
    assert cleared["findings"] == [] and cleared["status"] == "ok"


def test_service_risk_jobs_get_no_promotion_offer(started):  # M2
    for i in range(3):
        demo.inject(started, "server_lagging", "game-1")
        a = propose(started, "restart_server", turn=f"turn_r{i}", skip_safer=True)
        assert actions.decide(started, a["id"], "approve")[0] == 202
    t = db.trust_doc(started, "sim", "restart_server").get().to_dict()
    assert len(t["successes"]) == 3 and not t.get("offer")


def test_failed_cleanup_keeps_its_disk_snapshot(started):  # M3
    demo.inject(started, "logs_locked", "pi-1")
    a = actions.propose(started, session_id="sess_test", turn_id="turn_f", generation=generation(started),
                        action_type="rotate_logs", device_id="pi-1", params={})
    actions.decide(started, a["id"], "approve")
    r = db.action(started, a["id"]).get().to_dict()["result"]
    assert r["ok"] is False and r["before"] == r["after"] == {"diskPct": 94}


def test_update_adds_a_real_backup_copy(started):  # M4
    before = next(c for c in dev(started)["diskConsumers"] if c["id"] == "backups")["sizeGb"]
    a = propose(started, "update_server", turn="turn_u2")
    actions.decide(started, a["id"], "approve")
    after = next(c for c in dev(started)["diskConsumers"] if c["id"] == "backups")["sizeGb"]
    assert after == pytest.approx(before + 6.2) and svc(started)["lastBackupDaysAgo"] == 0
    propose(started, "update_server", turn="turn_u2")  # replaying the done proposal adds nothing
    assert next(c for c in dev(started)["diskConsumers"] if c["id"] == "backups")["sizeGb"] == after


def test_update_incident_message_and_repeat_cycle(started):  # M5
    ev = demo.inject(started, "update_available", "game-1")
    msg = db.events(started).document(ev["eventId"]).get().to_dict()["message"]
    assert "available" in msg and "backed up" not in msg
    a = propose(started, "update_server", turn="turn_c1")
    actions.decide(started, a["id"], "approve")
    demo.inject(started, "update_available", "game-1")
    s = svc(started)
    assert s["updateAvailable"] and s["latestVersion"] != s["version"] == "1.21.5"
