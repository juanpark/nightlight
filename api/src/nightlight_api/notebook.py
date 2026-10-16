"""A notebook per device: short notes Nightlight writes after it investigates or fixes something (quirks, causes,
what worked) and notes the owner writes. Fed back to the agent with the device, so it doesn't start from zero."""

from datetime import datetime, timezone

from google.cloud import firestore

from . import db, real
from .errors import invalid, not_found
from .ids import new_id
from .redact import scrub

NOTE_CHARS = 300
KEEP = 30  # per device; the oldest notes go first, Nightlight's before the owner's
SHOWN = 10  # newest notes given to the agent


def _now():
    return datetime.now(timezone.utc)


def _clean(text: str) -> tuple[str, int]:
    clean, hidden = scrub(text or "")
    clean = " ".join(clean.split())
    return (clean[:NOTE_CHARS - 1].rstrip() + "…" if len(clean) > NOTE_CHARS else clean), hidden


def add(uid: str, device_id: str, text: str, by: str, generation: int | None) -> dict:
    """Add a note. by is "nightlight" or "you". Something that looks like a secret is refused, not stored."""
    clean, hidden = _clean(text)
    if hidden:
        raise ValueError("looks_secret")
    if not clean:
        raise ValueError("empty")

    @firestore.transactional
    def run(tx):
        snap = db.device(uid, device_id).get(transaction=tx)
        if not snap.exists or (generation is not None and not real.is_current(snap.to_dict(), generation)):
            raise not_found()
        d = snap.to_dict()
        old = list(db.notes(uid, device_id).get(transaction=tx))
        over = len(old) + 1 - KEEP
        if over > 0:  # oldest first, Nightlight's own notes before the owner's
            order = sorted(old, key=lambda s: ((s.to_dict() or {}).get("by") == "you", str((s.to_dict() or {}).get("at"))))
            for s in order[:over]:
                tx.delete(s.reference)
        nid = new_id("note")
        note = {"text": clean, "by": by, "at": _now()}
        if d.get("realm") != "real":
            note["demoGeneration"] = d.get("demoGeneration")
        tx.set(db.notes(uid, device_id).document(nid), note)
        return {"id": nid, **note}

    return db.run_transaction(run)


def remove(uid: str, device_id: str, note_id: str) -> dict:
    ref = db.notes(uid, device_id).document(note_id)
    if not ref.get().exists:
        raise not_found()
    ref.delete()
    return {"ok": True}


def recent(uid: str, device_id: str, n: int = SHOWN) -> list[dict]:
    notes = [s.to_dict() for s in db.notes(uid, device_id).get()]
    notes.sort(key=lambda x: str(x.get("at")), reverse=True)
    return [{"text": x["text"], "by": x.get("by"), "on": x["at"].date().isoformat() if hasattr(x.get("at"), "date")
             else None} for x in notes[:n]]


def owner_add(uid: str, device_id: str, text: str, generation: int | None) -> dict:
    try:
        return add(uid, device_id, text, "you", generation)
    except ValueError as e:
        raise invalid("text", "looks_secret" if str(e) == "looks_secret" else "empty") from None
