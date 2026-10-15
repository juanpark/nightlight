"""The demo sandbox: start, reset (behind a barrier) and inject incidents.

Reset protocol (build plan §4.4):
1. One transaction bumps `demoGeneration` and sets `demo = {state: resetting, resetOpId, resetLeaseUntil}`.
2. Cleanup and seeding run as small transactions, each fenced on `state == resetting`, the same `resetOpId` and the
   new generation. A worker whose fence fails stops at once, so a paused, superseded worker can't overwrite a newer
   reset. Each batch renews the lease.
3. A final fenced transaction sets `state = ready`.
While resetting, every demo write and chat answers 409 `resetting`.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from . import db, sim, trust as trustlib
from .config import settings
from .errors import ApiError, conflict, not_found
from .ids import new_id
from .template import TEMPLATES


class Superseded(Exception):
    """This reset worker no longer owns the barrier; it must stop without writing."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _lease() -> datetime:
    return _utcnow() + timedelta(seconds=settings.reset_lease_seconds)


def _lease_live(demo: dict) -> bool:
    until = demo.get("resetLeaseUntil")
    return bool(until) and until > _utcnow()


def _begin(uid: str, template: str, *, only_if_missing: bool) -> tuple[str, int] | dict:
    """Open the barrier. Returns (resetOpId, generation), or the current state dict when nothing needs doing."""

    @firestore.transactional
    def run(tx):
        snap = db.user(uid).get(transaction=tx)
        user = snap.to_dict() if snap.exists else None
        demo = (user or {}).get("demo", {})
        if user and only_if_missing and demo.get("state") == "ready":
            return {"ok": True, "demoGeneration": user["demoGeneration"]}
        if user and demo.get("state") == "resetting" and _lease_live(demo):
            seconds = max(int((demo["resetLeaseUntil"] - _utcnow()).total_seconds()), 1)
            raise conflict("reset_in_progress", retryAfter=seconds)
        generation = (user or {}).get("demoGeneration", 0) + 1
        op = new_id("reset")
        base = user or {"createdAt": firestore.SERVER_TIMESTAMP, "isDemo": True, "trustDefault": "ask"}
        tx.set(db.user(uid), {**base, "template": template, "demoGeneration": generation,
                              "demo": {"state": "resetting", "resetOpId": op, "resetLeaseUntil": _lease()}})
        return op, generation

    return run(db.client().transaction())


def _fenced(uid: str, op: str, generation: int, work) -> None:
    """Run `work(tx)` in a transaction that first proves this worker still owns the reset."""

    @firestore.transactional
    def run(tx):
        snap = db.user(uid).get(transaction=tx)
        demo = (snap.to_dict() or {}).get("demo", {}) if snap.exists else {}
        if (demo.get("state") != "resetting" or demo.get("resetOpId") != op
                or snap.to_dict().get("demoGeneration") != generation):
            raise Superseded()
        work(tx)
        tx.update(db.user(uid), {"demo.resetLeaseUntil": _lease()})

    run(db.client().transaction())


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _delete_older(uid: str, op: str, generation: int, refs: list, hook) -> None:
    """Delete docs whose generation is older than `generation`, re-reading each one inside the fenced transaction."""
    for chunk in _chunks(refs, settings.reset_batch_size):
        hook("batch")

        def work(tx, chunk=chunk):
            snaps = [r.get(transaction=tx) for r in chunk]
            for r, s in zip(chunk, snaps, strict=True):
                if s.exists and (s.to_dict() or {}).get("demoGeneration", 0) < generation:
                    tx.delete(r)

        _fenced(uid, op, generation, work)


def _stale_pending(uid: str, op: str, generation: int, hook) -> None:
    refs = [s.reference for s in db.actions(uid).where(filter=FieldFilter("status", "==", "pending")).get()]
    for chunk in _chunks(refs, settings.reset_batch_size):
        hook("batch")

        def work(tx, chunk=chunk):
            snaps = [r.get(transaction=tx) for r in chunk]
            for r, s in zip(chunk, snaps, strict=True):
                d = s.to_dict() if s.exists else None
                if d and d.get("status") == "pending" and d.get("demoGeneration", 0) < generation:
                    tx.update(r, {"status": "stale", "finishedAt": firestore.SERVER_TIMESTAMP})

        _fenced(uid, op, generation, work)


def _seed(uid: str, op: str, generation: int, template: str, hook) -> int:
    t = TEMPLATES[template]
    hook("seed")

    def work(tx):
        for raw in t["devices"]:
            device = deepcopy(raw)
            services = device.pop("services")
            device_id = device.pop("id")
            device.update(version=1, simulated=True, demoGeneration=generation, lastSeen=firestore.SERVER_TIMESTAMP,
                          findings=[])
            device = sim.refresh({**device, "id": device_id})
            device.pop("id")
            if t["initial_incident"]["deviceId"] == device_id:
                device, _ = sim.inject({**device, "id": device_id}, t["initial_incident"]["kind"])
                device.pop("id")
            tx.set(db.device(uid, device_id), device)
            for svc in services:
                svc = deepcopy(svc)
                svc_id = svc.pop("id")
                svc.setdefault("findings", [])
                tx.set(db.services(uid, device_id).document(svc_id), {**svc, "demoGeneration": generation})
        for action_type in sim.ACTIONS:
            tx.set(db.trust_doc(uid, "sim", action_type), trustlib.new_doc(action_type, generation))

    _fenced(uid, op, generation, work)
    return len(t["devices"])


def _finalize(uid: str, op: str, generation: int, hook) -> None:
    hook("finalize")

    @firestore.transactional
    def run(tx):
        snap = db.user(uid).get(transaction=tx)
        demo = (snap.to_dict() or {}).get("demo", {})
        if demo.get("resetOpId") != op or snap.to_dict().get("demoGeneration") != generation:
            raise Superseded()
        tx.update(db.user(uid), {"demo": {"state": "ready", "resetOpId": op, "resetLeaseUntil": None}})

    run(db.client().transaction())


def _rebuild(uid: str, op: str, generation: int, template: str, hook) -> int:
    old_devices = [s.reference for s in db.devices(uid).get()]
    service_refs = [s.reference for d in old_devices for s in d.collection("services").get()]
    _delete_older(uid, op, generation, service_refs, hook)
    _delete_older(uid, op, generation, old_devices, hook)
    _delete_older(uid, op, generation, [s.reference for s in db.events(uid).get()], hook)
    old_sessions = [s.reference for s in db.sessions(uid).get()]
    inner = [m.reference for s in old_sessions for sub in ("messages", "turns") for m in s.collection(sub).get()]
    _delete_older(uid, op, generation, inner, hook)
    _delete_older(uid, op, generation, old_sessions, hook)
    _delete_older(uid, op, generation, [s.reference for s in db.trust(uid).get()], hook)
    _stale_pending(uid, op, generation, hook)
    count = _seed(uid, op, generation, template, hook)
    _finalize(uid, op, generation, hook)
    return count


def _no_hook(_: str) -> None:
    pass


def start(uid: str, template: str = "home-pi", hook=_no_hook) -> dict:
    """Give this user a sample home. Calling it again while the demo is ready changes nothing."""
    if template not in TEMPLATES:
        raise ApiError(422, "unknown_template")
    began = _begin(uid, template, only_if_missing=True)
    if isinstance(began, dict):
        began["devices"] = len(TEMPLATES[template]["devices"])
        return began
    op, generation = began
    count = _rebuild(uid, op, generation, template, hook)
    return {"ok": True, "demoGeneration": generation, "devices": count}


def reset(uid: str, hook=_no_hook) -> dict:
    snap = db.user(uid).get()
    if not snap.exists:
        raise not_found()
    template = snap.to_dict().get("template", "home-pi")
    op, generation = _begin(uid, template, only_if_missing=False)
    _rebuild(uid, op, generation, template, hook)
    return {"ok": True, "demoGeneration": generation}


def inject(uid: str, kind: str, device_id: str) -> dict:
    if kind not in sim.INCIDENTS:
        raise ApiError(422, "unknown_incident")

    @firestore.transactional
    def run(tx):
        user_snap = db.user(uid).get(transaction=tx)
        device_snap = db.device(uid, device_id).get(transaction=tx)
        if not user_snap.exists or not device_snap.exists:
            raise not_found()
        user = user_snap.to_dict()
        if user.get("demo", {}).get("state") != "ready":
            raise conflict("resetting", retryAfter=5)
        device = dict(device_snap.to_dict(), id=device_id)
        try:
            updated, event = sim.inject(device, kind)
        except ValueError:
            raise ApiError(422, "incident_not_applicable") from None
        updated.pop("id")
        updated["version"] = device["version"] + 1
        tx.set(db.device(uid, device_id), updated)
        event_id = new_id("ev")
        tx.set(db.events(uid).document(event_id), {**event, "deviceId": device_id, "source": "demo",
                                                    "at": firestore.SERVER_TIMESTAMP,
                                                    "demoGeneration": user["demoGeneration"]})
        return {"eventId": event_id}

    return run(db.client().transaction())
