"""Live demo machines: a small pool of real VMs, one per visitor at a time, started on demand and stopped after use.

Each pool slot is a stopped Compute Engine VM (a small "home server" with Docker apps) whose helper is paired to its own
pool account (uid judge-pool-N). A visitor who asks for the live demo leases a free slot in a Firestore transaction;
the API starts that VM and hands the browser a Firebase custom token for the pool account, carrying the lease id. When
the lease ends (the visitor leaves, stops sending heartbeats, or reaches the hard cap) the slot is released: the pool
account's chats, notes, runbooks, jobs, trust and memories are wiped, the token stops working, and the VM is stopped.
The scheduled sweep releases expired leases and stops any pool VM that runs without a live lease, so nothing runs on.

The VM side needs no inbound access: a tiny agent on each VM watches the instance metadata key "demo-command"
(scenario:nonce) and, on every new value, resets the home and applies the scenario. The API sets it with
compute.instances.setMetadata, so a lease always starts from a known state, with or without a reboot.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from . import db
from .config import settings
from .errors import ApiError
from .ids import new_id

log = logging.getLogger(__name__)

SCENARIOS = ("none", "crash", "unhealthy", "disk", "leftovers")
VM_UP = {"PROVISIONING", "STAGING", "RUNNING"}
RELEASE_STALE = timedelta(minutes=5)  # a release that never finished (crash, timeout) is taken over after this
COMPUTE = "https://compute.googleapis.com/compute/v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enabled() -> bool:
    return bool(settings.live_pool)


def pool() -> dict[str, str]:
    """instance name -> pool account uid, from LIVE_POOL ("nl-live-1=judge-pool-1,nl-live-2=judge-pool-2")."""
    out = {}
    for item in settings.live_pool:
        name, _, uid = item.partition("=")
        if name and uid:
            out[name] = uid
    return out


def slots():
    return db.client().collection("livePool")


def pool_slot(uid: str | None) -> str | None:
    """The pool slot this uid belongs to, from server configuration (never from a token): None for everyone else."""
    if not uid or not enabled():
        return None
    return next((name for name, pool_uid in pool().items() if pool_uid == uid), None)


# What a live demo machine's account may never do, whatever asks for it (route, chat tool, card approval): things that
# would unpair, replace or outlive the machine for the next visitor.
POOL_FORBIDDEN_ACTIONS = frozenset({"remove_device", "update_helper", "expert_grant", "expert_command"})


def forbid_pool(uid: str) -> None:
    """Called where pool-forbidden changes are made (pairing, removal, permissions, setup, passkeys, settings)."""
    if pool_slot(uid):
        raise ApiError(403, "live_demo_machine")


def _label(name: str) -> str:
    return "Machine " + name.rsplit("-", 1)[-1]


# ------------------------------------------------------------------ Compute Engine (REST, the API's own identity)

@lru_cache
def _session():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return AuthorizedSession(creds)


def _instance_url(name: str) -> str:
    return f"{COMPUTE}/projects/{settings.project_id}/zones/{settings.live_zone}/instances/{name}"


def vm_get(name: str) -> dict:
    r = _session().get(_instance_url(name), timeout=10)
    r.raise_for_status()
    return r.json()


def vm_start(name: str) -> None:
    r = _session().post(_instance_url(name) + "/start", timeout=15)
    if r.status_code not in (200, 409):  # 409: an operation is already under way
        r.raise_for_status()


def vm_stop(name: str) -> None:
    # discardLocalSsd is irrelevant here (no local SSD); a plain stop keeps the boot disk.
    r = _session().post(_instance_url(name) + "/stop", timeout=15)
    if r.status_code not in (200, 409):
        r.raise_for_status()


def vm_command(name: str, value: str) -> None:
    """Set the "demo-command" metadata the VM's agent applies (reset, then the scenario). Keeps every other item."""
    for _ in range(4):
        inst = vm_get(name)
        md = inst.get("metadata") or {}
        items = [i for i in md.get("items") or [] if i.get("key") != "demo-command"]
        items.append({"key": "demo-command", "value": value})
        r = _session().post(_instance_url(name) + "/setMetadata", timeout=15,
                            json={"fingerprint": md.get("fingerprint"), "items": items})
        if r.status_code in (409, 412):  # someone else changed the metadata in between: read it again
            time.sleep(0.5)
            continue
        r.raise_for_status()
        return
    raise ApiError(503, "live_machine_busy", retryAfter=5)


def vm_guest(name: str) -> tuple[str, str, float] | None:
    """The VM agent's progress from the guest attribute demo/state: (resetting|ready, nonce, unix time)."""
    r = _session().get(_instance_url(name) + "/getGuestAttributes", params={"queryPath": "demo/"}, timeout=10)
    if r.status_code == 404:  # nothing written yet (just booted)
        return None
    r.raise_for_status()
    for item in (r.json().get("queryValue") or {}).get("items") or []:
        if item.get("key") == "state":
            parts = str(item.get("value", "")).split(":")
            if len(parts) >= 3:
                try:
                    return parts[0], ":".join(parts[1:-1]), float(parts[-1])
                except ValueError:
                    return None
    return None


_vm_cache: dict[str, tuple[float, str]] = {}
_vm_lock = threading.Lock()


def vm_status(name: str, max_age: float = 8.0) -> str:
    """The VM's real state (RUNNING, STAGING, STOPPING, TERMINATED, ...), cached briefly. UNKNOWN when unreadable."""
    with _vm_lock:
        hit = _vm_cache.get(name)
    if hit and time.monotonic() - hit[0] < max_age:
        return hit[1]
    try:
        status = vm_get(name).get("status", "UNKNOWN")
    except Exception as e:
        log.warning("live vm_get %s failed: %s", name, type(e).__name__)
        status = "UNKNOWN"
    with _vm_lock:
        _vm_cache[name] = (time.monotonic(), status)
    return status


def _forget_status(name: str) -> None:
    with _vm_lock:
        _vm_cache.pop(name, None)


def all_status(max_age: float = 8.0) -> dict[str, str]:
    names = list(pool())
    with ThreadPoolExecutor(max_workers=max(1, len(names))) as ex:
        return dict(zip(names, ex.map(lambda n: vm_status(n, max_age), names)))


# ------------------------------------------------------------------ tokens

@lru_cache
def _signer_app():
    import firebase_admin
    return firebase_admin.initialize_app(
        options={"projectId": settings.project_id, "serviceAccountId": settings.live_signer}, name="live-signer")


def mint_token(pool_uid: str, slot: str, lease_id: str) -> str:
    """A Firebase custom token for the pool account, signed through IAM (no key file). The lease id rides along as a
    claim, so the token (and every ID token made from it) stops working the moment that lease ends."""
    from firebase_admin import auth as fb_auth
    token = fb_auth.create_custom_token(pool_uid, {"nl_slot": slot, "nl_lease": lease_id}, app=_signer_app())
    return token.decode() if isinstance(token, bytes) else token


_lease_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def lease_doc(slot: str, lease_id: str, *, fresh: bool = False) -> dict | None:
    """The slot's data when this is its current, unexpired lease, else None. Reads may reuse a check up to 2 s old,
    never past the lease's own deadlines; anything that changes state (fresh=True) always reads the slot again."""
    key = (slot, lease_id)
    hit = _lease_cache.get(key)
    now = _now()
    if not fresh and hit and time.monotonic() - hit[0] < 2.0 and _live(hit[1], now):
        return hit[1]
    snap = slots().document(slot).get() if slot in pool() else None
    d = (snap.to_dict() or {}) if snap is not None and snap.exists else {}
    if not (_live(d, now) and d.get("leaseId") == lease_id):
        _lease_cache.pop(key, None)
        return None
    if len(_lease_cache) > 500:
        _lease_cache.clear()
    _lease_cache[key] = (time.monotonic(), d)
    return d


def lease_live(slot: str, lease_id: str, max_age: float = 2.0) -> bool:
    return lease_doc(slot, lease_id, fresh=not max_age) is not None


def reset_auth_user(uid: str) -> None:
    """Delete the pool account's Firebase Auth user: any login a visitor linked to it (Google, password) and every
    refresh token die with the visit. The next custom-token sign-in creates the user again; Firestore data is by uid."""
    from firebase_admin import auth as fb_auth
    from .auth import _app
    try:
        fb_auth.delete_user(uid, app=_app())
    except fb_auth.UserNotFoundError:
        pass


# ------------------------------------------------------------------ leases

def _live(d: dict, now: datetime) -> bool:
    """A current lease: leased, before its idle deadline and before its fixed hard deadline (which never moves)."""
    return d.get("state") == "leased" and d.get("expiresAt") is not None and d["expiresAt"] > now \
        and d.get("hardExpiresAt") is not None and d["hardExpiresAt"] > now


def lease(requester: str, ip_hash: str, scenario: str = "none") -> dict:
    """Give this visitor a machine: their current lease if they have one, else a free slot. All busy -> 409."""
    if not enabled():
        raise ApiError(503, "live_off")
    if scenario not in SCENARIOS:
        raise ApiError(422, "unknown_scenario")
    names = pool()

    @firestore.transactional
    def run(tx):
        now = _now()
        docs = {n: (slots().document(n).get(transaction=tx).to_dict() or {}) for n in names}
        for n, d in docs.items():
            if _live(d, now) and d.get("holder") == requester:
                return n, d, False
        if sum(1 for d in docs.values() if _live(d, now) and d.get("ipHash") == ip_hash) >= settings.live_per_ip:
            raise ApiError(429, "live_per_visitor_limit")
        free = [n for n, d in docs.items() if d.get("state", "free") == "free"]
        if not free:
            return None, None, False
        adm_ref = db.client().collection("liveAdmissions").document(ip_hash)
        recent = [t for t in (adm_ref.get(transaction=tx).to_dict() or {}).get("at", []) if t > now - timedelta(hours=1)]
        if len(recent) >= settings.live_admissions_per_hour:  # new machines per visitor address per hour
            raise ApiError(429, "live_admissions_limit", retryAfter=600)
        # Prefer the slot stopped longest (spreads wear, and a slot just released may still be stopping).
        n = min(free, key=lambda x: docs[x].get("freedAt") or datetime(2000, 1, 1, tzinfo=timezone.utc))
        d = {"state": "leased", "instance": n, "uid": names[n], "leaseId": new_id("lease"), "holder": requester,
             "ipHash": ip_hash, "scenario": scenario, "leasedAt": now,
             "expiresAt": now + timedelta(seconds=settings.live_idle_seconds),
             "hardExpiresAt": now + timedelta(seconds=settings.live_max_seconds), "lastBeat": now}
        d["command"] = d["leaseId"]  # the VM agent's first command for this lease: reset, then the scenario
        tx.set(slots().document(n), d)
        tx.set(adm_ref, {"at": recent + [now]})
        # The uid -> slot binding the Firestore rules read: this uid's reads need a token for this slot's live lease.
        tx.set(db.client().collection("livePoolUids").document(names[n]), {"slot": n})
        return n, d, True

    slot, d, fresh = db.run_transaction(run)
    if slot is None:
        try:
            release_expired()  # abandoned leases start their way back now rather than at the next sweep
            advance_restores()
        except Exception as e:
            log.warning("live release on demand failed: %s", type(e).__name__)
        raise ApiError(409, "live_all_busy", **counts())
    if fresh:
        try:
            reset_auth_user(d["uid"])  # also done at release; again here so no earlier login can survive into this visit
            vm_command(slot, f"{scenario}:{d['leaseId']}")
            try:
                vm_start(slot)
            except Exception:
                if vm_get(slot).get("status") != "STOPPING":
                    raise
                # still stopping from the last release: mine() starts it once it has stopped
            _forget_status(slot)
        except ApiError:
            _abandon(slot, d["leaseId"])
            raise
        except Exception as e:
            log.warning("live start %s failed: %s", slot, type(e).__name__)
            _abandon(slot, d["leaseId"])
            raise ApiError(503, "live_start_failed", retryAfter=10) from None
    # resumed: this visitor already held a live lease (came back to the page). The screen offers "Continue where
    # you left off" or "Start fresh" (POST /api/demo/live/reset).
    return {**_public(slot, d), "token": mint_token(d["uid"], slot, d["leaseId"]), "fresh": fresh,
            "resumed": not fresh}


def _abandon(slot: str, lease_id: str) -> None:
    """The VM couldn't be started: give the slot back as it was (stopped, nothing to wipe)."""
    @firestore.transactional
    def run(tx):
        d = slots().document(slot).get(transaction=tx).to_dict() or {}
        if d.get("leaseId") == lease_id:
            tx.set(slots().document(slot), {"state": "free", "freedAt": _now()})
    db.run_transaction(run)


def _public(slot: str, d: dict) -> dict:
    return {"machine": _label(slot), "slot": slot, "leaseId": d["leaseId"], "uid": d["uid"],
            "expiresAt": d["expiresAt"].isoformat(), "hardExpiresAt": d["hardExpiresAt"].isoformat(),
            "scenario": d.get("scenario", "none"), "etaSeconds": settings.live_eta_seconds,
            "restoreSeconds": settings.live_restore_seconds}


def _held(slot: str, lease_id: str) -> dict:
    snap = slots().document(slot).get()
    d = snap.to_dict() or {}
    if not (_live(d, _now()) and d.get("leaseId") == lease_id):
        raise ApiError(401, "lease_ended")
    return d


def heartbeat(slot: str, lease_id: str) -> dict:
    """The visitor is still here: push the idle deadline out (never past the hard cap)."""
    @firestore.transactional
    def run(tx):
        now = _now()
        ref = slots().document(slot)
        d = ref.get(transaction=tx).to_dict() or {}
        if not (_live(d, now) and d.get("leaseId") == lease_id):
            raise ApiError(401, "lease_ended")
        expires = min(now + timedelta(seconds=settings.live_idle_seconds), d["hardExpiresAt"])
        tx.update(ref, {"expiresAt": expires, "lastBeat": now})
        return {**d, "expiresAt": expires}

    d = db.run_transaction(run)
    return {"ok": True, "expiresAt": d["expiresAt"].isoformat(), "hardExpiresAt": d["hardExpiresAt"].isoformat()}


def mine(slot: str, lease_id: str) -> dict:
    """What the waiting screen shows: the VM's real state, and whether its helper has reported since the lease began.
    A lease whose VM is found stopped (it was still stopping when leased) is started again here."""
    d = _held(slot, lease_id)
    vm = vm_status(slot, max_age=3.0)
    if vm == "TERMINATED" and not d.get("restore"):
        try:
            vm_start(slot)
            _forget_status(slot)
            vm = "STAGING"
        except Exception as e:
            log.warning("live restart %s failed: %s", slot, type(e).__name__)
    helper_seen = None
    for s in db.devices(d["uid"]).where(filter=FieldFilter("realm", "==", "real")).get():
        seen = (s.to_dict() or {}).get("lastSeen")
        if seen and (helper_seen is None or seen > helper_seen):
            helper_seen = seen
    guest = None
    if vm == "RUNNING":
        try:
            guest = vm_guest(slot)
        except Exception as e:
            log.warning("live guest %s failed: %s", slot, type(e).__name__)
    if d.get("restore"):
        restore_step(slot, min_gap=2.0)  # the waiting screen's polling drives a Start fresh forward
        d = slots().document(slot).get().to_dict() or d
        if d.get("restore"):
            vm = vm_status(slot, max_age=0)
    phase = _phase(d, vm, guest, helper_seen)
    return {**_public(slot, d), "vm": vm, "phase": phase, "restoreSeconds": settings.live_restore_seconds,
            "helperSeenAt": helper_seen.isoformat() if helper_seen else None,
            "secondsSinceLease": round((_now() - d["leasedAt"]).total_seconds())}


def _phase(d: dict, vm: str, guest, helper_seen) -> str:
    """stopping -> restoring (Start fresh: the disk goes back to the golden copy) -> starting (VM booting) ->
    reconnecting (VM up; the home is being reset / the scenario applied, or the helper hasn't reported since) -> ready
    (the home is ready for this command AND the machine's helper has reported after that)."""
    if d.get("restore"):
        return "stopping" if vm in VM_UP or vm == "STOPPING" else "restoring"
    if vm != "RUNNING":
        return "starting"
    if not guest or guest[1] != d.get("command") or guest[0] != "ready":
        return "reconnecting"
    applied = datetime.fromtimestamp(guest[2], timezone.utc)
    return "ready" if helper_seen is not None and helper_seen > applied else "reconnecting"


def _command_done(slot: str, d: dict) -> bool:
    try:
        g = vm_guest(slot)
    except Exception:
        return False
    return bool(g and g[0] == "ready" and g[1] == d.get("command"))


def set_scenario(slot: str, lease_id: str, scenario: str) -> dict:
    """Break something for real (or put it right) during a visit: the VM's agent runs `demo reset`, then applies the
    scenario. Chats and notes stay (same visit). One at a time: refused while the previous one is still applying."""
    if scenario not in SCENARIOS:
        raise ApiError(422, "unknown_scenario")
    nonce = new_id("cmd")
    snap = slots().document(slot).get().to_dict() or {}
    done = _command_done(slot, snap)  # read outside the transaction: it calls the Compute API

    @firestore.transactional
    def run(tx):
        now = _now()
        ref = slots().document(slot)
        d = ref.get(transaction=tx).to_dict() or {}
        if not (_live(d, now) and d.get("leaseId") == lease_id):
            raise ApiError(401, "lease_ended")
        busy_since = d.get("commandAt") or d.get("leasedAt")
        settled = done and d.get("command") == snap.get("command")
        if d.get("restore") or d.get("wiping") or (now - busy_since < timedelta(minutes=3) and not settled):
            raise ApiError(409, "reset_in_progress", retryAfter=5)
        expires = min(now + timedelta(seconds=settings.live_idle_seconds), d["hardExpiresAt"])
        tx.update(ref, {"command": nonce, "commandAt": now, "scenario": scenario, "expiresAt": expires,
                        "lastBeat": now})

    db.run_transaction(run)
    vm_command(slot, f"{scenario}:{nonce}")
    return {"ok": True, "scenario": scenario, "phase": "reconnecting"}


def reset_mine(slot: str, lease_id: str, scenario: str = "none") -> dict:
    """Start fresh on the same machine: wipe this pool account back to its baseline, restore the VM's boot disk from
    its golden snapshot (stop -> new disk -> boot), keep the lease. One at a time, at most LIVE_RESETS_PER_LEASE, and
    only with time left before the lease's fixed deadline for the restore to finish.
    Progress: GET /api/demo/live/me (stopping -> restoring -> starting -> reconnecting -> ready)."""
    if scenario not in SCENARIOS:
        raise ApiError(422, "unknown_scenario")
    plan = _restore_plan(slot, "start", lease_id)

    @firestore.transactional
    def run(tx):
        now = _now()
        ref = slots().document(slot)
        d = ref.get(transaction=tx).to_dict() or {}
        if not (_live(d, now) and d.get("leaseId") == lease_id):
            raise ApiError(401, "lease_ended")
        if d.get("restore") or d.get("wiping"):
            raise ApiError(409, "reset_in_progress", retryAfter=10)
        if d.get("resets", 0) >= settings.live_resets_per_lease:
            raise ApiError(429, "live_reset_limit")
        if d["hardExpiresAt"] - now < timedelta(seconds=settings.live_restore_seconds + 120):
            raise ApiError(409, "live_not_enough_time")
        # The idle clock restarts with room for the restore; the hard deadline never moves.
        expires = min(now + timedelta(seconds=settings.live_idle_seconds + settings.live_restore_seconds),
                      d["hardExpiresAt"])
        tx.update(ref, {"restore": plan, "scenario": scenario, "wiping": True, "expiresAt": expires, "lastBeat": now,
                        "resetAt": now, "resets": d.get("resets", 0) + 1})
        return d

    d = db.run_transaction(run)
    ok = False
    try:
        restore_step(slot)  # first step now: the VM starts stopping while the account is wiped
        wipe(d["uid"])
        ok = True
    finally:
        _end_wiping(slot, plan["op"], ok)
    return {"ok": True, "scenario": scenario, "phase": "stopping", "restoreSeconds": settings.live_restore_seconds}


def _end_wiping(slot: str, op: str, ok: bool) -> None:
    """Clear the wiping flag only on the restore this reset started (a release may have taken the slot meanwhile).
    A failed wipe leaves the account unclean: the lease ends now and the release (wipe again, or maintenance) follows."""
    @firestore.transactional
    def run(tx):
        ref = slots().document(slot)
        d = ref.get(transaction=tx).to_dict() or {}
        if (d.get("restore") or {}).get("op") != op or d.get("state") != "leased":
            return
        tx.update(ref, {"wiping": False, **({} if ok else {"expiresAt": _now(), "wipeFailed": True})})
    db.run_transaction(run)


def end(slot: str, lease_id: str) -> dict:
    """The visitor is done: release now (wipe, stop) instead of waiting for the idle timeout."""
    @firestore.transactional
    def run(tx):
        ref = slots().document(slot)
        d = ref.get(transaction=tx).to_dict() or {}
        if d.get("leaseId") != lease_id or d.get("state") != "leased":
            return False
        tx.update(ref, {"expiresAt": _now()})
        return True

    if db.run_transaction(run):
        _release(slot)
    return {"ok": True}


# ------------------------------------------------------------------ release: wipe the account, stop the VM

def _claim_release(slot: str) -> dict | None:
    """Move an expired lease (or a stale release) to "releasing", once. Returns the slot's data if this caller won."""
    @firestore.transactional
    def run(tx):
        now = _now()
        ref = slots().document(slot)
        d = ref.get(transaction=tx).to_dict() or {}
        expired = d.get("state") == "leased" and not _live(d, now)
        stale = d.get("state") == "releasing" and (d.get("releaseStartedAt") or now) <= now - RELEASE_STALE
        if not (expired or stale):
            return None
        tx.update(ref, {"state": "releasing", "releaseStartedAt": now})
        return {**d, "_claimedAt": now}

    return db.run_transaction(run)


def _release(slot: str) -> bool:
    d = _claim_release(slot)
    if d is None:
        return False
    claimed_at = d["_claimedAt"]
    try:
        vm_stop(slot)  # first: the machine stops costing money even if the cleanup below fails
        _forget_status(slot)
    except Exception as e:
        log.warning("live stop %s failed: %s", slot, type(e).__name__)  # the sweep stops orphans
    # Not free yet: the boot disk goes back to its golden snapshot (a true rollback of anything the visitor changed on
    # the machine). A Start fresh still under way keeps its disk and steps; it now ends with the slot free.
    plan = {**(d.get("restore") or _restore_plan(slot, "free")), "then": "free"}
    try:
        cleanup(d["uid"])
        after = {"state": "restoring"}
    except Exception as e:
        # Never back in service unclean: maintenance, shown in the public status, retried by the sweep.
        log.warning("live cleanup %s failed: %s", slot, type(e).__name__)
        after = {"state": "maintenance", "reason": "cleanup_failed", "needsCleanup": True}

    @firestore.transactional
    def finish(tx):
        ref = slots().document(slot)
        cur = ref.get(transaction=tx).to_dict() or {}
        if cur.get("state") != "releasing" or cur.get("releaseStartedAt") != claimed_at:
            return False  # someone else took this release over (stale-release takeover): theirs stands
        tx.set(ref, {**after, "uid": d["uid"], "lastLeaseId": d.get("leaseId"), "restore": plan})
        return True

    return db.run_transaction(finish)


def cleanup(uid: str) -> None:
    """Everything a visit leaves on the account side goes: the data (wipe) and the Firebase Auth user (logins a visitor
    linked, refresh tokens). Raises if any part fails."""
    wipe(uid)
    reset_auth_user(uid)


# ------------------------------------------------------------------ disk restore from the golden snapshot

def _disk_url(name: str = "") -> str:
    return f"{COMPUTE}/projects/{settings.project_id}/zones/{settings.live_zone}/disks" + (f"/{name}" if name else "")


def _restore_plan(slot: str, then: str, lease_id: str | None = None) -> dict:
    op = "r" + format(int(time.time() * 1000), "x")[-9:] + new_id("x")[-4:].lower()
    return {"op": op, "target": f"{slot}-{op}", "then": then, "startedAt": _now(), "leaseId": lease_id}


_step_at: dict[str, float] = {}


def restore_step(slot: str, min_gap: float = 0.0) -> bool:
    """Advance a disk restore by at most one Compute call; never waits. True when there is nothing (left) to do.
    Steps: stop the VM -> create a disk from <slot>-golden -> detach the old boot disk -> attach the new one as boot
    -> delete the old disk -> free the slot (after a release) or start the VM again (a restore during a lease)."""
    now_m = time.monotonic()
    if min_gap and now_m - _step_at.get(slot, 0) < min_gap:
        return False
    _step_at[slot] = now_m
    d = slots().document(slot).get().to_dict() or {}
    r = d.get("restore")
    if not r:
        return True
    try:
        inst = vm_get(slot)
        boot = next((x for x in inst.get("disks") or [] if x.get("boot")), None)
        boot_name = boot["source"].rsplit("/", 1)[-1] if boot else None
        if boot_name == r["target"]:
            if r.get("old"):
                rr = _session().delete(_disk_url(r["old"]), timeout=15)
                if rr.status_code not in (200, 404):
                    return False  # the detach may still be settling: try again on the next step
            return _restore_done(slot, r)
        status = inst.get("status")
        if status != "TERMINATED":
            if status not in ("STOPPING", "SUSPENDING"):
                vm_stop(slot)
                _forget_status(slot)
            return False
        disk = _session().get(_disk_url(r["target"]), timeout=10)
        if disk.status_code == 404:
            _session().post(_disk_url(), timeout=15, json={
                "name": r["target"], "sourceSnapshot": f"global/snapshots/{slot}-golden",
                "type": f"zones/{settings.live_zone}/diskTypes/pd-balanced",
                "labels": {"purpose": "live-demo-pool"}}).raise_for_status()
            return False
        disk.raise_for_status()
        if disk.json().get("status") != "READY":
            return False
        if boot:
            slots().document(slot).update({"restore.old": boot_name})
            _session().post(_instance_url(slot) + "/detachDisk", params={"deviceName": boot["deviceName"]},
                            timeout=15).raise_for_status()
            return False
        _session().post(_instance_url(slot) + "/attachDisk", timeout=15, json={
            "source": f"projects/{settings.project_id}/zones/{settings.live_zone}/disks/{r['target']}",
            "boot": True, "autoDelete": True, "deviceName": "boot"}).raise_for_status()
        return False
    except Exception as e:  # an operation still running ("resource not ready") or a blip: the next step retries
        log.info("live restore %s step: %s", slot, type(e).__name__)
        return False


def _restore_done(slot: str, r: dict) -> bool:
    """The disk swap is finished. What happens next is decided from the slot's state now, in one transaction (a
    release may have turned a Start fresh into a release meanwhile): back to service, still maintenance, or (a Start
    fresh whose lease is still current) the visitor's machine starts again."""
    took = round((_now() - r["startedAt"]).total_seconds())

    @firestore.transactional
    def run(tx):
        ref = slots().document(slot)
        d = ref.get(transaction=tx).to_dict() or {}
        cur = d.get("restore") or {}
        if cur.get("op") != r["op"]:
            return None
        if d.get("state") == "leased" and cur.get("then") == "start" and cur.get("leaseId") == d.get("leaseId"):
            nonce = new_id("cmd")
            tx.update(ref, {"restore": firestore.DELETE_FIELD, "command": nonce, "commandAt": _now(), "restored": took})
            return f"{d.get('scenario', 'none')}:{nonce}"
        if d.get("state") == "restoring":
            tx.set(ref, {"state": "free", "freedAt": _now(), "lastLeaseId": d.get("lastLeaseId"),
                         "lastRestoreSeconds": took})
        else:  # maintenance (cleanup failed), or a lease that ended: the disk is clean, the slot stays as it is
            tx.update(ref, {"restore": firestore.DELETE_FIELD})
        return None

    cmd = db.run_transaction(run)
    if cmd:  # a restore during a lease: the visitor's machine starts again on the clean disk
        vm_command(slot, cmd)
        vm_start(slot)
        _forget_status(slot)
    return True


def advance_restores(budget: float = 0.0) -> list[str]:
    """Push every pending restore forward: one step each (budget 0), or loop until done or out of time (sweep)."""
    pending = [n for n in pool() if (slots().document(n).get().to_dict() or {}).get("restore")]
    if not pending:
        return []
    end = time.monotonic() + budget

    def drive(n):
        while True:
            if restore_step(n, min_gap=0 if budget else 3.0):
                return n
            if time.monotonic() > end:
                return None
            time.sleep(3)

    with ThreadPoolExecutor(max_workers=len(pending)) as ex:
        return [n for n in ex.map(drive, pending) if n]


KEEP_USER_COLLECTIONS = ("devices", "quota", "trust")  # trust: freshly seeded by the reset below; quota: rate limits


def record_baseline(uid: str) -> dict:
    """Record what a clean pool account looks like (its paired devices and their services, exactly), once, when the
    golden snapshots are taken. wipe() puts this back after every visit."""
    devices = {}
    for snap in db.devices(uid).get():
        devices[snap.id] = {"doc": snap.to_dict(),
                            "services": {s.id: s.to_dict() for s in db.services(uid, snap.id).get()}}
    db.client().collection("livePoolBaseline").document(uid).set({"devices": devices, "recordedAt": _now()})
    return {"devices": len(devices)}


def wipe(uid: str) -> None:
    """Put a pool account back to its recorded baseline. Every visitor-owned thing goes: chats, turns, notes,
    runbooks, profiles, jobs and cards, events, links, places, scans, discoveries, watches, trust, memories; devices
    and their services are restored exactly (names, tags, positions, favourites, issue states, permissions); devices
    that aren't in the baseline are deleted. Raises (never half-succeeds silently) if anything fails or doesn't verify."""
    from copy import deepcopy
    from . import demo, memory, watch
    base = (db.client().collection("livePoolBaseline").document(uid).get().to_dict() or {}).get("devices")
    if not base:
        raise RuntimeError("no_baseline")
    if db.user(uid).get().exists:
        demo.reset(uid)  # chats, turns, trust (reseeded), non-real things
    else:
        demo.start(uid, "empty")
    if memory.enabled() and not memory.forget_all(uid):
        raise RuntimeError("memory_not_cleared")
    for w in watch.watches(uid).get():
        watch.remove_watch(uid, w.id)  # also leaves the global watch registry
    client = db.client()
    for col in db.user(uid).collections():
        if col.id not in KEEP_USER_COLLECTIONS:
            client.recursive_delete(col)
    for snap in db.devices(uid).get():
        if snap.id not in base:
            client.recursive_delete(snap.reference)
            continue
        for sub in snap.reference.collections():
            if sub.id != "history":  # health history the machine itself produced
                client.recursive_delete(sub)
    batch = client.batch()
    for device_id, b in base.items():
        ref = db.device(uid, device_id)
        cur = ref.get().to_dict() or {}
        doc = deepcopy(b["doc"])
        doc["version"] = max(int(cur.get("version") or 0), int(doc.get("version") or 0)) + 1
        batch.set(ref, doc)
        for svc_id, svc in (b.get("services") or {}).items():
            batch.set(db.services(uid, device_id).document(svc_id), svc)
    batch.commit()
    _verify_wiped(uid, base)


VERIFY_FIELDS = ("name", "tags", "x", "y", "favorite", "favoriteApps", "issueStates", "permissions", "manage")


def _verify_wiped(uid: str, base: dict) -> None:
    extra = [c.id for c in db.user(uid).collections() if c.id not in KEEP_USER_COLLECTIONS]
    if extra:
        raise RuntimeError("left_collections:" + ",".join(sorted(extra)))
    devices = {s.id: s.to_dict() or {} for s in db.devices(uid).get()}
    if set(devices) != set(base):
        raise RuntimeError("devices_differ")
    for device_id, b in base.items():
        if any(devices[device_id].get(f) != b["doc"].get(f) for f in VERIFY_FIELDS):
            raise RuntimeError("device_fields_differ")
        if [c.id for c in db.device(uid, device_id).collections() if c.id not in ("services", "history")]:
            raise RuntimeError("device_collections_left")


def release_expired(limit: int | None = None) -> int:
    n = 0
    now = _now()
    for name in pool():
        d = slots().document(name).get().to_dict() or {}
        due = (d.get("state") == "leased" and not _live(d, now)) or \
              (d.get("state") == "releasing" and (d.get("releaseStartedAt") or now) <= now - RELEASE_STALE)
        if due and _release(name):
            n += 1
            if limit and n >= limit:
                break
    return n


def sweep() -> dict:
    """Scheduled: release expired leases, then stop every pool VM that is up without a live lease."""
    if not enabled():
        return {"enabled": False}
    released = release_expired()
    for name in pool():  # maintenance after a failed cleanup: try again; back to restoring/free only when it works
        d = slots().document(name).get().to_dict() or {}
        if d.get("state") == "maintenance" and d.get("needsCleanup") and d.get("uid"):
            try:
                cleanup(d["uid"])
                slots().document(name).update({"state": "restoring" if d.get("restore") else "free",
                                               "needsCleanup": firestore.DELETE_FIELD,
                                               "reason": firestore.DELETE_FIELD, "freedAt": _now()})
            except Exception as e:
                log.warning("live cleanup retry %s failed: %s", name, type(e).__name__)
    restored = advance_restores(budget=240)  # the scheduled request may run 15 min; a restore takes ~1-2
    stopped = []
    now = _now()
    status = all_status(max_age=0)
    for name, vm in status.items():
        d = slots().document(name).get().to_dict() or {}
        if vm in VM_UP and not _live(d, now) and not d.get("restore"):
            try:
                vm_stop(name)
                _forget_status(name)
                stopped.append(name)
            except Exception as e:
                log.warning("live sweep stop %s failed: %s", name, type(e).__name__)
    return {"enabled": True, "released": released, "restored": restored, "stoppedOrphans": stopped}


def counts() -> dict:
    now = _now()
    docs = {n: slots().document(n).get().to_dict() or {} for n in pool()}
    status = all_status()
    in_use = sum(1 for d in docs.values() if _live(d, now))
    return {"total": len(docs), "inUse": in_use, "free": sum(1 for d in docs.values()
                                                               if d.get("state", "free") == "free"),
            "running": sum(1 for v in status.values() if v in VM_UP)}


def status() -> dict:
    """Public, for the line "Live demo machines: 2 of 5 running". No uids, no lease ids."""
    if not enabled():
        return {"enabled": False, "total": 0, "inUse": 0, "free": 0, "running": 0, "machines": []}
    try:
        advance_restores()  # one throttled step per pending restore, so freed machines come back between sweeps
    except Exception as e:
        log.warning("live advance failed: %s", type(e).__name__)
    now = _now()
    vms = all_status()
    machines = []
    for name in pool():
        d = slots().document(name).get().to_dict() or {}
        st = d.get("state", "free")
        state = "in_use" if _live(d, now) else (
            "free" if st == "free" else "maintenance" if st == "maintenance" else "resetting")
        machines.append({"machine": _label(name), "state": state, "vm": vms.get(name, "UNKNOWN")})
    return {"enabled": True, "total": len(machines), "inUse": sum(m["state"] == "in_use" for m in machines),
            "free": sum(m["state"] == "free" for m in machines),
            "running": sum(m["vm"] in VM_UP for m in machines), "etaSeconds": settings.live_eta_seconds,
            "restoreSeconds": settings.live_restore_seconds, "idleMinutes": settings.live_idle_seconds // 60, "maxMinutes": settings.live_max_seconds // 60,
            "machines": machines}
