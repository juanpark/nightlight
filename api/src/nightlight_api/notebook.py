"""A notebook per device: short notes Nightlight writes after it investigates or fixes something (quirks, causes,
what worked) and notes the owner writes. Fed back to the agent with the device, so it doesn't start from zero. A note
may belong to one service on the device (the Minecraft server, a container): then it is filed under that service."""

from datetime import datetime, timezone

from google.cloud import firestore

from . import db, real
from .errors import invalid, not_found
from .ids import new_id
from .redact import scrub

NOTE_CHARS = 300
KEEP = 30  # per device; the oldest notes go first, Nightlight's before the owner's
SHOWN = 10  # newest notes given to the agent
SHOWN_PER_SERVICE = 5  # and per service, for at most SHOWN_SERVICES services
SHOWN_SERVICES = 8


def _now():
    return datetime.now(timezone.utc)


def _clean(text: str) -> tuple[str, int]:
    clean, hidden = scrub(text or "")
    clean = " ".join(clean.split())
    return (clean[:NOTE_CHARS - 1].rstrip() + "…" if len(clean) > NOTE_CHARS else clean), hidden


def service_named(services: list, name: str | None) -> tuple[str, str] | None:
    """(service doc id, its name) for a service on the device named by its id or its name, any case. None when
    nothing was named; ValueError("unknown_service") when the device has nothing by that name."""
    want = (name or "").strip().lower()
    if not want:
        return None
    for s in services:
        d = s.to_dict() or {}
        if want in (s.id.lower(), str(d.get("name") or "").lower()):
            return s.id, d.get("name") or s.id
    raise ValueError("unknown_service")


def add(uid: str, device_id: str, text: str, by: str, generation: int | None, fence=None,
        service: str | None = None) -> dict:
    """Add a note. by is "nightlight" or "you". Something that looks like a secret is refused, not stored.
    Like every other write, it waits out a reset and belongs to the current generation; `fence(tx)` lets a turn
    abort if it is no longer the current attempt. `service` (its id or name) files the note under that service."""
    clean, hidden = _clean(text)
    if hidden:
        raise ValueError("looks_secret")
    if not clean:
        raise ValueError("empty")

    @firestore.transactional
    def run(tx):
        if fence:
            fence(tx)
        user = db.user(uid).get(transaction=tx).to_dict()
        from .actions import _require_ready  # not at the top: actions is the heavier module
        _require_ready(user, generation)
        snap = db.device(uid, device_id).get(transaction=tx)
        if not snap.exists or not real.is_current(snap.to_dict(), user.get("demoGeneration")):
            raise not_found()
        d = snap.to_dict()
        svc = service_named(list(db.services(uid, device_id).get(transaction=tx)), service)
        old = list(db.notes(uid, device_id).get(transaction=tx))
        over = len(old) + 1 - KEEP
        if over > 0:  # oldest first, Nightlight's own notes before the owner's
            order = sorted(old, key=lambda s: ((s.to_dict() or {}).get("by") == "you", str((s.to_dict() or {}).get("at"))))
            for s in order[:over]:
                tx.delete(s.reference)
        nid = new_id("note")
        note = {"text": clean, "by": by, "at": _now()}
        if svc:
            note["svcId"], note["service"] = svc
        if d.get("realm") != "real":
            note["demoGeneration"] = d.get("demoGeneration")
        tx.set(db.notes(uid, device_id).document(nid), note)
        return {"id": nid, **note}

    return db.run_transaction(run)


def remove(uid: str, device_id: str, note_id: str) -> dict:
    ref = db.notes(uid, device_id).document(note_id)

    @firestore.transactional
    def run(tx):  # a transaction, so the request's fence (a live demo machine's lease) is checked with the delete
        if not ref.get(transaction=tx).exists:
            raise not_found()
        tx.delete(ref)

    db.run_transaction(run)
    return {"ok": True}


def _all(uid: str, device_id: str, generation: int | None) -> list[dict]:
    """Newest first; a sample device's notes only from the current generation (in case a reset raced a write)."""
    notes = [dict(x, id=s.id) for s, x in ((s, s.to_dict()) for s in db.notes(uid, device_id).get())
             if "demoGeneration" not in x or x["demoGeneration"] == generation]
    notes.sort(key=lambda x: str(x.get("at")), reverse=True)
    return notes


def _short(x: dict) -> dict:
    return {"text": x["text"], "by": x.get("by"), "on": x["at"].date().isoformat() if hasattr(x.get("at"), "date")
            else None}


def recent(uid: str, device_id: str, generation: int | None, n: int = SHOWN) -> list[dict]:
    return [_short(x) for x in _all(uid, device_id, generation)[:n]]


def grouped(uid: str, device_id: str, generation: int | None) -> dict:
    """For the agent: device-wide notes, then each service's own, newest first and bounded."""
    out = {"device": [], "services": {}}
    for x in _all(uid, device_id, generation):
        name = x.get("service")
        if not name:
            if len(out["device"]) < SHOWN:
                out["device"].append(_short(x))
        elif name in out["services"] or len(out["services"]) < SHOWN_SERVICES:
            rows = out["services"].setdefault(name, [])
            if len(rows) < SHOWN_PER_SERVICE:
                rows.append(_short(x))
    return out


def everything(uid: str, device_id: str, generation: int | None) -> dict:
    """For the app: every note (at most KEEP), with its id and time, grouped like `grouped`."""
    out = {"device": [], "services": {}}
    for x in _all(uid, device_id, generation):
        row = {k: x.get(k) for k in ("id", "text", "by", "at", "service") if x.get(k) is not None}
        (out["services"].setdefault(x["service"], []) if x.get("service") else out["device"]).append(row)
    return out


def owner_add(uid: str, device_id: str, text: str, generation: int | None, service: str | None = None) -> dict:
    try:
        return add(uid, device_id, text, "you", generation, service=service)
    except ValueError as e:
        code = str(e)
        if code == "unknown_service":
            raise invalid("service", code) from None
        raise invalid("text", "looks_secret" if code == "looks_secret" else "empty") from None


# ------------------------------------------------------------------ the device profile
# One living document per device (like an administrator's notes on a machine): what it is, what runs there, how it is
# set up, quirks, past incidents and what fixed them. Nightlight rewrites it after investigating; the owner can edit
# it. Read before every investigation.

PROFILE_CHARS = 2000


def _profile_ref(uid: str, device_id: str):
    return db.device(uid, device_id).collection("profile").document("main")


def profile(uid: str, device_id: str) -> dict | None:
    p = _profile_ref(uid, device_id).get().to_dict()
    return {"text": p["text"], "by": p.get("by"), "updatedAt": p.get("updatedAt")} if p else None


def set_profile(uid: str, device_id: str, text: str, by: str, generation: int | None, fence=None) -> dict:
    """Replace the profile (scrubbed; something that looks like a secret is refused, not stored)."""
    clean, hidden = scrub(text or "")
    clean = clean.strip()[:PROFILE_CHARS]
    if hidden:
        raise ValueError("looks_secret")
    if not clean:
        raise ValueError("empty")

    @firestore.transactional
    def run(tx):
        if fence:
            fence(tx)
        user = db.user(uid).get(transaction=tx).to_dict()
        from .actions import _require_ready
        _require_ready(user, generation)
        snap = db.device(uid, device_id).get(transaction=tx)
        if not snap.exists or not real.is_current(snap.to_dict(), user.get("demoGeneration")):
            raise not_found()
        doc = {"text": clean, "by": by, "updatedAt": _now()}
        tx.set(_profile_ref(uid, device_id), doc)
        return doc

    return db.run_transaction(run)
