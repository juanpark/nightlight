"""Live demo machines: leases are exclusive under concurrency, idempotent per visitor and rate limited; a pool account
is known by uid and works only with its slot's current lease (API and Firestore rules); it can never unpair or replace
the machine, by route, chat card or approval; a release puts the account back to its exact baseline or the slot goes
to maintenance; restore completion follows the slot's current state; the hard deadline never moves. Compute and
Firebase Auth calls are faked; Firestore (and its rules) is the emulator."""
import base64
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from nightlight_api import actions, db, demo, live, real
from nightlight_api.auth import POOL_DENY
from nightlight_api.config import settings
from nightlight_api.errors import ApiError
from nightlight_api.main import app

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


@pytest.fixture
def pool(monkeypatch):
    tag = uuid.uuid4().hex[:6]
    names = [f"nl-live-t{tag}-{n}" for n in range(1, 6)]
    uids = [f"pool-{tag}-{i}" for i in range(1, 6)]
    monkeypatch.setattr(settings, "live_pool", [f"{n}={u}" for n, u in zip(names, uids)])
    monkeypatch.setattr(settings, "live_admissions_per_hour", 50)
    calls = []
    monkeypatch.setattr(live, "vm_command", lambda name, value: calls.append(("cmd", name, value)))
    monkeypatch.setattr(live, "vm_start", lambda name: calls.append(("start", name)))
    monkeypatch.setattr(live, "vm_stop", lambda name: calls.append(("stop", name)))
    monkeypatch.setattr(live, "vm_status", lambda name, max_age=0: "TERMINATED")
    monkeypatch.setattr(live, "restore_step", lambda slot, min_gap=0: False)
    monkeypatch.setattr(live, "mint_token", lambda uid, slot, lease_id: f"tok:{uid}:{lease_id}")
    monkeypatch.setattr(live, "reset_auth_user", lambda uid: calls.append(("auth_reset", uid)))
    live._lease_cache.clear()
    yield names, uids, calls
    for n in names:
        live.slots().document(n).delete()


def _ask(v, ip=None):
    try:
        return live.lease(v, ip or f"ip-{v}")
    except ApiError as e:
        return e


# ------------------------------------------------------------------ leasing

def test_six_at_once_get_five_distinct_machines_and_one_clear_refusal(pool):
    names, _, calls = pool
    with ThreadPoolExecutor(6) as ex:
        out = list(ex.map(_ask, [f"v{i}" for i in range(6)]))
    ok = [o for o in out if isinstance(o, dict)]
    refused = [o for o in out if isinstance(o, ApiError)]
    assert len({o["slot"] for o in ok}) == 5 and len(ok) == 5
    assert len(refused) == 1 and refused[0].status == 409 and refused[0].code == "live_all_busy"
    assert sorted(c[1] for c in calls if c[0] == "start") == sorted(names)


def test_same_visitor_gets_the_same_machine_back_as_resumed(pool):
    first = live.lease("v1", "ip1")
    again = live.lease("v1", "ip1")
    assert again["slot"] == first["slot"] and again["leaseId"] == first["leaseId"]
    assert first["resumed"] is False and again["resumed"] is True


def test_one_address_holds_at_most_live_per_ip(pool, monkeypatch):
    monkeypatch.setattr(settings, "live_per_ip", 2)
    live.lease("a", "same")
    live.lease("b", "same")
    with pytest.raises(ApiError) as e:
        live.lease("c", "same")
    assert e.value.status == 429


def test_admissions_per_address_per_hour_are_limited_beyond_the_concurrent_limit(pool, monkeypatch):
    monkeypatch.setattr(settings, "live_admissions_per_hour", 2)
    ip = f"adm-{uuid.uuid4().hex[:6]}"
    for v in ("a", "b"):
        got = live.lease(v, ip)
        live.slots().document(got["slot"]).update({"state": "free"})  # left at once: not held concurrently
    with pytest.raises(ApiError) as e:
        live.lease("c", ip)
    assert e.value.code == "live_admissions_limit"


def test_lease_binds_uid_to_slot_and_resets_the_auth_user_first(pool):
    _, _, calls = pool
    got = live.lease("v1", "ip1")
    assert db.client().collection("livePoolUids").document(got["uid"]).get().to_dict() == {"slot": got["slot"]}
    assert ("auth_reset", got["uid"]) in calls


# ------------------------------------------------------------------ finding 1: identity by uid, not by claims

def _client_with(monkeypatch, claims):
    from nightlight_api import auth
    monkeypatch.setattr(auth.fb_auth, "verify_id_token", lambda token, app=None: claims)
    return TestClient(app)


def test_pool_uid_without_lease_claims_is_refused(pool, monkeypatch):
    got = live.lease("v1", "ip1")
    # e.g. an email/password login linked to the pool account: same uid, no lease claims
    c = _client_with(monkeypatch, {"uid": got["uid"], "firebase": {"sign_in_provider": "password"}})
    r = c.get("/api/devices/removed", headers={"Authorization": "Bearer x"})
    assert r.status_code == 401 and r.json()["code"] == "lease_ended"


def test_pool_uid_with_another_slots_lease_is_refused_and_the_right_one_works(pool, monkeypatch):
    names, _, _ = pool
    got = live.lease("v1", "ip1")
    other = next(n for n in names if n != got["slot"])
    bad = _client_with(monkeypatch, {"uid": got["uid"], "nl_slot": other, "nl_lease": got["leaseId"],
                                     "firebase": {"sign_in_provider": "custom"}})
    assert bad.get("/api/devices/removed", headers={"Authorization": "Bearer x"}).status_code == 401
    good = _client_with(monkeypatch, {"uid": got["uid"], "nl_slot": got["slot"], "nl_lease": got["leaseId"],
                                      "firebase": {"sign_in_provider": "custom"}})
    assert good.get("/api/devices/removed", headers={"Authorization": "Bearer x"}).status_code == 200


def test_lease_claims_on_a_non_pool_uid_are_refused(pool, monkeypatch):
    c = _client_with(monkeypatch, {"uid": "someone-else", "nl_slot": pool[0][0], "nl_lease": "x",
                                   "firebase": {"sign_in_provider": "custom"}})
    assert c.get("/api/devices/removed", headers={"Authorization": "Bearer x"}).status_code == 401


def test_release_resets_the_auth_user(pool, monkeypatch):
    _, _, calls = pool
    monkeypatch.setattr(live, "wipe", lambda uid: None)
    got = live.lease("v1", "ip1")
    calls.clear()
    live.end(got["slot"], got["leaseId"])
    assert ("auth_reset", got["uid"]) in calls
    assert live.slots().document(got["slot"]).get().to_dict()["state"] == "restoring"


# ------------------------------------------------------------------ finding 5: rules (emulator) and no stale cache

def _jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    now = int(time.time())
    body = {"iss": f"https://securetoken.google.com/{settings.project_id}", "aud": settings.project_id,
            "iat": now, "exp": now + 3600, "auth_time": now, **claims}
    return f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc(body)}."


def _read_as(uid, claims):
    host = os.environ["FIRESTORE_EMULATOR_HOST"]
    url = (f"http://{host}/v1/projects/{settings.project_id}/databases/(default)/documents/users/{uid}/devices/d1")
    tok = _jwt({"sub": uid, "user_id": uid, "firebase": {"sign_in_provider": "custom"}, **claims})
    return httpx.get(url, headers={"Authorization": f"Bearer {tok}"}).status_code


def test_rules_need_this_slots_current_lease_for_a_pool_uid(pool):
    got = live.lease("v1", "ip1")
    uid, slot, lid = got["uid"], got["slot"], got["leaseId"]
    db.device(uid, "d1").set({"name": "x"})
    ok = {"nl_slot": slot, "nl_lease": lid}
    assert _read_as(uid, ok) == 200
    assert _read_as(uid, {}) == 403  # linked login, no claims
    assert _read_as(uid, {"nl_slot": slot, "nl_lease": "old"}) == 403  # an earlier visit
    live.slots().document(slot).update({"wiping": True})
    assert _read_as(uid, ok) == 403
    live.slots().document(slot).update({"wiping": False, "expiresAt": NOW() - timedelta(seconds=1)})
    assert _read_as(uid, ok) == 403  # expired by time, before any cleanup ran
    live.slots().document(slot).update({"expiresAt": NOW() + timedelta(minutes=5),
                                        "hardExpiresAt": NOW() - timedelta(seconds=1)})
    assert _read_as(uid, ok) == 403
    assert _read_as("ordinary-user", {}) in (200, 404)  # everyone else: unchanged


def test_no_cached_admission_past_expiry(pool):
    got = live.lease("v1", "ip1")
    assert live.lease_doc(got["slot"], got["leaseId"]) is not None  # now cached
    live.slots().document(got["slot"]).update({"expiresAt": NOW() - timedelta(seconds=1)})
    live._lease_cache[(got["slot"], got["leaseId"])][1]["expiresAt"] = NOW() - timedelta(seconds=1)
    assert live.lease_doc(got["slot"], got["leaseId"]) is None


def test_writes_during_a_start_fresh_wipe_are_fenced(pool, monkeypatch):
    got = live.lease("v1", "ip1")
    live.slots().document(got["slot"]).update({"wiping": True})
    c = _client_with(monkeypatch, {"uid": got["uid"], "nl_slot": got["slot"], "nl_lease": got["leaseId"],
                                   "firebase": {"sign_in_provider": "custom"}})
    r = c.post("/api/chat/sessions", json={}, headers={"Authorization": "Bearer x"})
    assert r.status_code == 409 and r.json()["code"] == "machine_resetting"


# ------------------------------------------------------------------ finding 2: capability policy where actions are made

@pytest.mark.parametrize("line,denied", [
    ("POST /api/devices/dev_x/remove", True), ("DELETE /api/devices/dev_x", True),
    ("POST /api/devices/enrol-code", True), ("GET /api/devices/pair/ABCD-EFGH", True),
    ("POST /api/devices/dev_x/revoke", True), ("POST /api/devices/dev_x/update", True),
    ("POST /api/devices/dev_x/permissions", True), ("POST /api/devices/dev_x/setup", True),
    ("POST /api/expert/register/options", True), ("POST /api/settings", True),
    ("POST /api/chat/sessions", False), ("POST /api/demo/live/reset", False),
    ("GET /api/devices/dev_x/knowledge", False),
])
def test_pool_routes(line, denied):
    assert bool(POOL_DENY.search(line)) is denied


def test_a_chat_made_remove_card_is_refused_for_a_pool_uid(pool):
    uid = pool[1][0]
    for kind in ("remove_device", "update_helper", "expert_grant"):
        with pytest.raises(ValueError, match="not_on_demo_machine"):
            actions.request(uid, kind, "dev_x", {}, session_id="s", turn_id="t")


def test_approving_an_existing_remove_card_is_refused_for_a_pool_uid(pool):
    uid = pool[1][0]
    db.action(uid, "act_rm").set({"type": "remove_device", "deviceId": "dev_x", "status": "pending", "realm": "real"})
    with pytest.raises(ApiError) as e:
        actions.decide(uid, "act_rm", "approve")
    assert e.value.status == 403
    assert db.action(uid, "act_rm").get().to_dict()["status"] == "pending"


@pytest.mark.parametrize("call", [
    lambda u: real.set_permissions(u, "dev_x", {}), lambda u: real.device_setup(u, "dev_x", "fix", False, False),
    lambda u: real.create_code(u), lambda u: real.pair_decide(u, "ABCDEFGH", True), lambda u: real.revoke(u, "dev_x"),
])
def test_pool_changes_are_refused_where_they_are_made(pool, call):
    with pytest.raises(ApiError) as e:
        call(pool[1][0])
    assert e.value.code == "live_demo_machine"


# ------------------------------------------------------------------ finding 3: exact baseline, or maintenance

def _seed_pool_account(uid):
    demo.start(uid, "empty")
    db.device(uid, "dev_base").set({"realm": "real", "name": "homeserver", "tags": [], "x": 1, "y": 2,
                                    "permissions": {"diagnose": True}, "version": 3, "manage": "app"})
    db.services(uid, "dev_base").document("svc1").set({"name": "photos", "kind": "container"})
    live.record_baseline(uid)


def test_wipe_restores_the_exact_baseline_and_deletes_visitor_state(pool):
    uid = pool[1][0]
    _seed_pool_account(uid)
    db.device(uid, "dev_base").update({"name": "Judge's secret box", "tags": ["private"], "x": 900,
                                       "issueStates": {"f": "known"}, "permissions": {"diagnose": False}})
    db.services(uid, "dev_base").document("svc1").update({"name": "renamed"})
    db.notes(uid, "dev_base").document("n1").set({"text": "13.4 GB log"})
    db.user(uid).collection("places").document("p1").set({"name": "Judge's flat"})
    db.links(uid).document("l1").set({"from": "dev_base", "to": "x", "realm": "real"})
    db.user(uid).collection("discoveries").document("d1").set({"name": "printer"})
    db.device(uid, "dev_extra").set({"realm": "real", "kind": "watched", "name": "added by a visitor"})
    live.wipe(uid)
    d = db.device(uid, "dev_base").get().to_dict()
    assert d["name"] == "homeserver" and d["tags"] == [] and d["x"] == 1 and "issueStates" not in d
    assert d["permissions"] == {"diagnose": True} and d["version"] > 3
    assert db.services(uid, "dev_base").document("svc1").get().to_dict()["name"] == "photos"
    assert not db.device(uid, "dev_extra").get().exists
    for col in ("places", "links", "discoveries", "sessions", "events", "actions"):
        assert not list(db.user(uid).collection(col).limit(1).get()), col
    assert not list(db.notes(uid, "dev_base").limit(1).get())


def test_wipe_without_a_baseline_fails_loudly(pool):
    with pytest.raises(RuntimeError):
        live.wipe(f"no-baseline-{uuid.uuid4().hex[:6]}")


def test_failed_cleanup_puts_the_slot_in_maintenance_until_a_retry_works(pool, monkeypatch):
    got = live.lease("v1", "ip1")

    def broken(uid):
        raise RuntimeError("memory_not_cleared")

    monkeypatch.setattr(live, "wipe", broken)
    live.end(got["slot"], got["leaseId"])
    d = live.slots().document(got["slot"]).get().to_dict()
    assert d["state"] == "maintenance" and d["needsCleanup"]
    monkeypatch.setattr(live, "all_status", lambda max_age=0: {})
    assert next(m for m in live.status()["machines"] if m["machine"] == live._label(got["slot"]))["state"] \
        == "maintenance"
    others = [live.lease(f"w{i}", f"ipw{i}")["slot"] for i in range(4)]
    assert got["slot"] not in others  # a maintenance slot is never handed out
    with pytest.raises(ApiError):
        live.lease("w9", "ipw9")
    monkeypatch.setattr(live, "wipe", lambda uid: None)
    monkeypatch.setattr(live, "advance_restores", lambda budget=0: [])
    live.sweep()
    assert live.slots().document(got["slot"]).get().to_dict()["state"] == "restoring"


# ------------------------------------------------------------------ finding 4: restore completion is serialized

def test_a_stale_start_fresh_completion_after_a_release_frees_the_slot_and_starts_nothing(pool, monkeypatch):
    _, _, calls = pool
    monkeypatch.setattr(live, "wipe", lambda uid: None)
    got = live.lease("v1", "ip1")
    live.reset_mine(got["slot"], got["leaseId"])
    captured = live.slots().document(got["slot"]).get().to_dict()["restore"]
    assert captured["then"] == "start"
    live.end(got["slot"], got["leaseId"])  # the same restore now ends the release
    calls.clear()
    live._restore_done(got["slot"], captured)  # the stale caller still thinks "start"
    assert not [c for c in calls if c[0] in ("start", "cmd")]
    assert live.slots().document(got["slot"]).get().to_dict()["state"] == "free"


def test_a_start_fresh_completion_restarts_the_visitors_machine(pool, monkeypatch):
    _, _, calls = pool
    monkeypatch.setattr(live, "wipe", lambda uid: None)
    got = live.lease("v1", "ip1")
    live.reset_mine(got["slot"], got["leaseId"])
    plan = live.slots().document(got["slot"]).get().to_dict()["restore"]
    calls.clear()
    live._restore_done(got["slot"], plan)
    assert ("start", got["slot"]) in calls
    d = live.slots().document(got["slot"]).get().to_dict()
    assert d["state"] == "leased" and "restore" not in d


# ------------------------------------------------------------------ finding 6: fixed deadline, limited resets

def test_resets_never_move_the_hard_deadline_and_are_limited(pool, monkeypatch):
    monkeypatch.setattr(live, "wipe", lambda uid: None)
    monkeypatch.setattr(settings, "live_resets_per_lease", 2)
    got = live.lease("v1", "ip1")
    hard = live.slots().document(got["slot"]).get().to_dict()["hardExpiresAt"]
    for _ in range(2):
        live.reset_mine(got["slot"], got["leaseId"])
        live.slots().document(got["slot"]).update({"restore": live.firestore.DELETE_FIELD})
        assert live.slots().document(got["slot"]).get().to_dict()["hardExpiresAt"] == hard
    with pytest.raises(ApiError) as e:
        live.reset_mine(got["slot"], got["leaseId"])
    assert e.value.code == "live_reset_limit"


def test_no_reset_without_time_for_it_and_no_use_after_the_hard_deadline(pool, monkeypatch):
    monkeypatch.setattr(live, "wipe", lambda uid: None)
    got = live.lease("v1", "ip1")
    live.slots().document(got["slot"]).update({"hardExpiresAt": NOW() + timedelta(seconds=60)})
    with pytest.raises(ApiError) as e:
        live.reset_mine(got["slot"], got["leaseId"])
    assert e.value.code == "live_not_enough_time"
    live.slots().document(got["slot"]).update({"hardExpiresAt": NOW() - timedelta(seconds=1)})
    assert not live.lease_live(got["slot"], got["leaseId"], max_age=0)


def test_phases_follow_the_machine():
    now = NOW()
    d = {"command": "c1"}
    assert live._phase({**d, "restore": {"op": "r"}}, "RUNNING", None, None) == "stopping"
    assert live._phase({**d, "restore": {"op": "r"}}, "TERMINATED", None, None) == "restoring"
    assert live._phase(d, "STAGING", None, None) == "starting"
    assert live._phase(d, "RUNNING", ("resetting", "c1", now.timestamp()), None) == "reconnecting"
    assert live._phase(d, "RUNNING", ("ready", "c0", now.timestamp()), now) == "reconnecting"
    assert live._phase(d, "RUNNING", ("ready", "c1", now.timestamp() - 5), now) == "ready"


# ------------------------------------------------------------------ rev2: visit epochs and write fences

def _free_after_release(slot):
    plan = live.slots().document(slot).get().to_dict()["restore"]
    assert live._restore_done(slot, plan)
    assert live.slots().document(slot).get().to_dict()["state"] == "free"


def _only_first_slot_free(names):
    for n in names[1:]:
        live.slots().document(n).set({"state": "maintenance"})


def test_a_stale_cleanup_never_touches_the_next_visit_or_its_auth_user(pool):
    names, uids, calls = pool
    _only_first_slot_free(names)
    slot, uid = names[0], uids[0]
    _seed_pool_account(uid)
    assert live.lease("v1", "ip1")["slot"] == slot
    live.slots().document(slot).update({"expiresAt": NOW() - timedelta(seconds=1)})
    stale = live._claim_release(slot)  # release 1 claims, then stalls before its cleanup
    live.slots().document(slot).update({"releaseStartedAt": NOW() - timedelta(minutes=10)})
    assert live._release(slot)  # release 2 takes over (a new epoch), cleans, restores
    _free_after_release(slot)
    second = live.lease("v2", "ip2")  # the next visit
    db.notes(uid, "dev_base").document("n_next").set({"text": "the next judge's note"})
    calls.clear()
    with pytest.raises(live.CleanupLost):
        live.cleanup(slot, uid, stale["epoch"])  # release 1 resumes
    assert db.notes(uid, "dev_base").document("n_next").get().exists
    assert ("auth_reset", uid) not in calls
    assert live.slots().document(slot).get().to_dict()["leaseId"] == second["leaseId"]


def test_a_write_admitted_in_one_visit_cannot_land_in_the_next(pool, monkeypatch):
    names, uids, _ = pool
    _only_first_slot_free(names)
    slot, uid = names[0], uids[0]
    _seed_pool_account(uid)
    first = live.lease("v1", "ip1")
    admitted = live.slots().document(slot).get().to_dict()
    live.end(slot, first["leaseId"])
    _free_after_release(slot)
    live.lease("v2", "ip2")
    # the old request passed auth before its lease ended; its endpoint runs only now
    real_lease_doc = live.lease_doc
    monkeypatch.setattr(live, "lease_doc", lambda s, lid, fresh=False: admitted if lid == first["leaseId"]
                        else real_lease_doc(s, lid, fresh=fresh))
    c = _client_with(monkeypatch, {"uid": uid, "nl_slot": slot, "nl_lease": first["leaseId"],
                                   "firebase": {"sign_in_provider": "custom"}})
    r = c.post("/api/devices/dev_base/layout", json={"name": "Judge one's private box"},
               headers={"Authorization": "Bearer x"})
    assert r.status_code == 401 and r.json()["code"] == "lease_ended"
    assert db.device(uid, "dev_base").get().to_dict()["name"] == "homeserver"


def test_restore_completion_waits_for_the_wipe_and_restarts_after_it(pool, monkeypatch):
    _, _, calls = pool
    got = live.lease("v1", "ip1")
    seen = {}

    def wipe_while_restore_finishes(uid):
        plan = live.slots().document(got["slot"]).get().to_dict()["restore"]
        seen["during"] = live._restore_done(got["slot"], plan)  # the disk half finishes mid-wipe

    monkeypatch.setattr(live, "wipe", wipe_while_restore_finishes)
    live.reset_mine(got["slot"], got["leaseId"])
    assert seen["during"] is False
    d = live.slots().document(got["slot"]).get().to_dict()
    assert d["wiping"] is False and d.get("restore")  # the op stays until both halves are done
    calls.clear()
    assert live._restore_done(got["slot"], d["restore"])
    assert ("start", got["slot"]) in calls
    assert "restore" not in live.slots().document(got["slot"]).get().to_dict()


def test_restore_completion_never_restarts_for_an_ended_lease(pool, monkeypatch):
    _, _, calls = pool
    monkeypatch.setattr(live, "wipe", lambda uid: None)
    got = live.lease("v1", "ip1")
    live.reset_mine(got["slot"], got["leaseId"])
    plan = live.slots().document(got["slot"]).get().to_dict()["restore"]
    live.slots().document(got["slot"]).update({"expiresAt": NOW() - timedelta(seconds=1)})
    calls.clear()
    assert live._restore_done(got["slot"], plan) is False
    assert not [c for c in calls if c[0] == "start"]


def test_any_visitor_transaction_rechecks_the_lease_with_its_write(pool):
    from nightlight_api import notebook
    got = live.lease("v1", "ip1")
    uid = got["uid"]
    demo.start(uid, "empty")
    db.device(uid, "dev_base").set({"realm": "real", "name": "homeserver"})
    live.slots().document(got["slot"]).update({"expiresAt": NOW() - timedelta(seconds=1)})
    with db.fenced(live.visitor_check(got["slot"], got["leaseId"])):
        with pytest.raises(ApiError):
            notebook.add(uid, "dev_base", "late note", "you", None)
    assert not list(db.notes(uid, "dev_base").get())


def test_a_reset_cleanup_stops_when_a_release_takes_over(pool, monkeypatch):
    _, _, calls = pool
    got = live.lease("v1", "ip1")

    def wipe_interrupted(uid):
        live.slots().document(got["slot"]).update({"expiresAt": NOW() - timedelta(seconds=1)})
        live._claim_release(got["slot"])  # a release takes the slot: new epoch
        db.fence_now()  # the reset's next destructive step

    monkeypatch.setattr(live, "wipe", wipe_interrupted)
    live.reset_mine(got["slot"], got["leaseId"])  # returns; its cleanup stopped at the fence
    assert live.slots().document(got["slot"]).get().to_dict()["state"] == "releasing"
