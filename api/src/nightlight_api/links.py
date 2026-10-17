"""Links between devices on the map: how things relate, drawn by the owner (or seeded for the sample home).

A link is layout, not device state: it changes nothing on any device. One link per ordered pair of devices (drawing
it again changes its kind). A link is "real" only when both ends are real devices; any other link belongs to the sample
home and goes away with it on a reset.
"""

from google.cloud import firestore

from . import db
from .errors import ApiError, conflict, not_found

KINDS = ("network", "backup", "depends", "power")  # connected through · backs up to · relies on · powered by
MAX_LINKS = 200


def link_id(src: str, dst: str) -> str:
    return f"{src}__{dst}"


def _usable(d: dict | None, user: dict) -> bool:
    """A device the owner sees on the map: real and not archived, or in the current sample home."""
    if not d or d.get("archived"):
        return False
    return d.get("realm") == "real" or d.get("demoGeneration") == user.get("demoGeneration")


def put(uid: str, src: str, dst: str, kind: str) -> dict:
    if kind not in KINDS:
        raise ApiError(422, "unknown_kind")
    if src == dst:
        raise ApiError(422, "same_device")
    ref = db.links(uid).document(link_id(src, dst))

    @firestore.transactional
    def run(tx):
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        a, b = (db.device(uid, x).get(transaction=tx) for x in (src, dst))
        ends = [s.to_dict() if s.exists else None for s in (a, b)]
        if not all(_usable(d, user) for d in ends):
            raise not_found()
        if any(d.get("realm") != "real" for d in ends) and user.get("demo", {}).get("state") != "ready":
            raise conflict("resetting", retryAfter=5)
        existing = ref.get(transaction=tx)
        if not existing.exists and len(list(db.links(uid).limit(MAX_LINKS).get(transaction=tx))) >= MAX_LINKS:
            raise ApiError(409, "too_many_links")
        real = all(d.get("realm") == "real" for d in ends)
        doc = {"from": src, "to": dst, "kind": kind, "realm": "real" if real else "sim",
               "demoGeneration": user.get("demoGeneration", 0), "createdAt": firestore.SERVER_TIMESTAMP}
        tx.set(ref, doc)
        return {"id": ref.id, **{k: v for k, v in doc.items() if k != "createdAt"}}

    return db.run_transaction(run)


def remove(uid: str, lid: str) -> None:
    """Delete a line. A sample-home line follows the same barrier as every other demo write: never while a reset is
    rebuilding the home, and never one from an older sample home."""
    ref = db.links(uid).document(lid)

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        link = snap.to_dict() if snap.exists else None
        if not link:
            raise not_found()
        if link.get("realm") != "real":
            if user.get("demo", {}).get("state") != "ready":
                raise conflict("resetting", retryAfter=5)
            if link.get("demoGeneration") != user.get("demoGeneration"):
                raise not_found()
        tx.delete(ref)

    db.run_transaction(run)


def touching(uid: str, device_id: str) -> list:
    """References of every link that has this device at either end (for purging a removed device)."""
    from google.cloud.firestore_v1.base_query import FieldFilter
    return [s.reference for f in ("from", "to")
            for s in db.links(uid).where(filter=FieldFilter(f, "==", device_id)).stream()]


def seed(tx, uid: str, generation: int, pairs: list) -> None:
    """The sample home's own links, written with its devices."""
    for src, dst, kind in pairs:
        tx.set(db.links(uid).document(link_id(src, dst)), {"from": src, "to": dst, "kind": kind, "realm": "sim",
                                                          "demoGeneration": generation,
                                                          "createdAt": firestore.SERVER_TIMESTAMP})
