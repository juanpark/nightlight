"""Removing a real device: soft delete first. A removed device leaves the map and the agent's view at once; its
history, notes, activity and the audit trail of what Nightlight did there stay archived for ARCHIVE_DAYS, then the
sweep deletes them. "Forget for good" deletes them at once.

Two ways a helper goes away, on purpose different:
- Removed in the app (the remove card): the device is archived (off the map, purged after ARCHIVE_DAYS).
- Uninstalled on the device itself (`helper uninstall`, /uninstall.sh, the Mac installer's uninstall): the token is
  revoked but the device stays on the map as offline, history kept, as if switched off.
Either way, installing the helper again on the same machine can continue the same device (and bring an archived
one back) when the owner chooses "Continue its history" while approving it (real.pair_preview / pair_decide)."""

from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from . import db, links, real
from .errors import ApiError, not_found

ARCHIVE_DAYS = 30
SELF_UNINSTALL_FROM = "0.9.6"  # helpers from this version uninstall themselves when the owner removes the device


def _now():
    return datetime.now(timezone.utc)


def index():
    return db.client().collection("archivedDevices")


def can_self_uninstall(device: dict) -> bool:
    from . import release
    v = device.get("helperVersion")
    return bool(v) and not release.newer(SELF_UNINSTALL_FROM, v)


def archive(tx, uid: str, device_id: str, name: str, words: str, who: str) -> None:
    """Archive in the caller's transaction (after its reads): hidden at once, purged after ARCHIVE_DAYS."""
    now = _now()
    tx.update(db.device(uid, device_id), {"archived": True, "archivedAt": now,
                                          "purgeAt": now + timedelta(days=ARCHIVE_DAYS), "status": "offline",
                                          "health": "unknown", "revoked": True})
    tx.set(index().document(f"{uid}__{device_id}"), {"uid": uid, "deviceId": device_id, "name": name,
                                                     "purgeAt": now + timedelta(days=ARCHIVE_DAYS)})
    tx.delete(db.client().collection("realDevices").document(f"{uid}__{device_id}"))
    real.event(tx, uid, device_id, "removed", "info", words, who=who)


def remove_now(uid: str, device_id: str, action_id: str | None = None) -> dict:
    """The device can't uninstall its helper (not reporting, or too old): cut its access and archive it now."""
    query = real.tokens_ref().where(filter=FieldFilter("deviceId", "==", device_id))

    @firestore.transactional
    def run(tx):
        dsnap = db.device(uid, device_id).get(transaction=tx)
        d = dsnap.to_dict() if dsnap.exists else None
        if not d or d.get("realm") != "real" or d.get("archived"):
            raise not_found()
        tokens = [t for t in query.get(transaction=tx) if t.to_dict().get("uid") == uid]
        a = db.action(uid, action_id).get(transaction=tx).to_dict() if action_id else None
        for t in tokens:
            tx.update(t.reference, {"revoked": True, "revokedAt": firestore.SERVER_TIMESTAMP})
        name = d.get("name", "A device")
        summary = (f"Removed {name}. It couldn't uninstall the helper itself, so its access was cut; the helper stops "
                   "the next time it starts. To delete its files, run the uninstall line on it.")
        archive(tx, uid, device_id, name, f"You removed {name} from your map (archived for {ARCHIVE_DAYS} days).",
                "you")
        if a and a.get("status") in ("approved", "running"):
            tx.update(db.action(uid, action_id), {"status": "done", "finishedAt": _now(), "followUp": "none",
                                                  "result": {"ok": True, "summary": summary}})
        return {"ok": True, "deviceId": device_id, "removed": "access_cut", "summary": summary}

    return db.run_transaction(run)


def left(tx, uid: str, device_id: str, dsnap, cleanup: str | None) -> None:
    """The helper uninstalled itself (called from /helper/leave's transaction, after its reads): close a removal the
    owner asked for, and archive the device."""
    d = dsnap.to_dict() or {}
    name = d.get("name", "A device")
    running = [a for a in db.actions(uid).where(filter=FieldFilter("deviceId", "==", device_id))
               .where(filter=FieldFilter("type", "==", "remove_device")).get(transaction=tx)
               if (a.to_dict() or {}).get("status") in ("approved", "running")]
    files = " Its background service needs an administrator to remove; run the uninstall line on it." \
        if cleanup == "files_left" else ""
    summary = f"Removed {name}: the helper uninstalled itself.{files}"
    for a in running:
        tx.update(a.reference, {"status": "done", "finishedAt": _now(), "followUp": "none",
                                "result": {"ok": True, "summary": summary}})
    if running:
        archive(tx, uid, device_id, name, f"{name} was removed: the helper uninstalled itself.{files}", "you")
    elif d.get("realm") == "real":  # uninstalled on the device itself (command line or the Mac installer's uninstall)
        tx.update(dsnap.reference, {"status": "offline", "health": "unknown", "revoked": True, "uninstalled": True,
                                    "uninstalledAt": _now()})
        tx.delete(db.client().collection("realDevices").document(f"{uid}__{device_id}"))
        real.event(tx, uid, device_id, "uninstalled", "info",
                   f"The helper was uninstalled on {name}. It stays on your map as offline, with its history: "
                   "install the helper again to continue it, or remove it.", "device")


def request(uid: str, device_id: str) -> dict:
    """The owner confirmed "Remove this device" in the app (the confirmation is the approval)."""
    from . import actions
    ref = db.device(uid, device_id)
    d = ref.get().to_dict()
    if not d or d.get("realm") != "real" or d.get("archived") or d.get("kind") == "watched":
        raise not_found()
    a = actions.request(uid, "remove_device", device_id, {}, session_id=None, turn_id="app_remove", origin="app")
    if a.get("status") == "done":  # the device couldn't do it itself: its access was cut (the capability's hook)
        return {"ok": True, "deviceId": device_id, "removed": "access_cut", "actionId": a["id"],
                "summary": a["result"]["summary"]}
    return {"ok": True, "deviceId": device_id, "removed": "asked_device", "actionId": a["id"],
            "summary": "Asked the device to uninstall its helper; it leaves your map within a minute."}


def after_approval(uid: str, action_id: str) -> None:
    """A removal was approved (the capability's hook): if the device can't do it itself, finish it now."""
    a = db.action(uid, action_id).get().to_dict() or {}
    if a.get("status") != "approved":
        return
    d = db.device(uid, a["deviceId"]).get().to_dict() or {}
    if real.view(dict(d, id=a["deviceId"])).get("stale") or d.get("revoked") or not can_self_uninstall(d):
        remove_now(uid, a["deviceId"], action_id)


def forget(uid: str, device_id: str) -> dict:
    """Delete an archived device and everything kept about it, now."""
    d = db.device(uid, device_id).get().to_dict()
    if not d or not d.get("archived"):
        raise ApiError(409, "remove_first") if d else not_found()
    if not purge(uid, device_id):
        raise ApiError(409, "remove_first")  # brought back meanwhile (a reinstall continued it)
    return {"ok": True, "deviceId": device_id}


def _claim(uid: str, device_id: str, due_only: bool) -> str | None:
    """Mark the device as being deleted, in a transaction on the device itself, before anything is deleted: only an
    archived device (and, for the sweep, one whose own purgeAt has passed: never a stale index entry's word). A
    reinstall that continues a device refuses a claimed one, and a restore makes this refuse. The claim id, or None."""
    from .ids import new_id
    dref = db.device(uid, device_id)
    claim = new_id("purge")

    @firestore.transactional
    def run(tx):
        snap = dref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or not d.get("archived") or (due_only and not (d.get("purgeAt") and d["purgeAt"] < _now())):
            return None
        tx.update(dref, {"purgeClaim": {"id": claim, "at": _now()}})
        return claim

    return db.run_transaction(run)


def _delete_fenced(dref, claim: str, refs: list) -> bool:
    """Delete refs only while the device is still archived and claimed by this purge, checked in the same
    transaction. False (nothing deleted) once the claim is gone."""
    @firestore.transactional
    def run(tx):
        snap = dref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or not d.get("archived") or (d.get("purgeClaim") or {}).get("id") != claim:
            return False
        for r in refs:
            tx.delete(r)
        return True

    return db.run_transaction(run)


def purge(uid: str, device_id: str, due_only: bool = False) -> bool:
    """Delete an archived device and everything kept about it: claimed first (see _claim), then deleted in fenced
    batches, the device document last. False when it wasn't deleted (not archived, not due, or restored)."""
    dref = db.device(uid, device_id)
    claim = _claim(uid, device_id, due_only)
    if not claim:
        if not dref.get().exists or not (dref.get().to_dict() or {}).get("archived"):
            index().document(f"{uid}__{device_id}").delete()  # gone or brought back: the entry is stale
        return False
    refs = [s.reference for sub in ("services", "history", "notes", "profile", "runbooks")
            for s in dref.collection(sub).stream()]
    refs += links.touching(uid, device_id)
    refs.append(db.user(uid).collection("discoveries").document(device_id))  # what it found goes with it
    refs.append(db.user(uid).collection("scans").document(device_id))
    for coll in (db.events(uid), db.actions(uid)):
        refs += [s.reference for s in coll.where(filter=FieldFilter("deviceId", "==", device_id)).stream()]
    for i in range(0, len(refs), 400):
        if not _delete_fenced(dref, claim, refs[i:i + 400]):
            return False
    if not _delete_fenced(dref, claim, [index().document(f"{uid}__{device_id}"), dref]):
        return False
    return True


def purge_due(limit: int = 10) -> int:
    """Called by the sweep: delete archived devices whose time is up."""
    n = 0
    for r in index().where(filter=FieldFilter("purgeAt", "<", _now())).limit(limit).stream():
        d = r.to_dict()
        n += purge(d["uid"], d["deviceId"], due_only=True)
    return n


def removed(uid: str) -> list[dict]:
    """Archived devices, for "Removed devices" in the app."""
    out = []
    for s in db.devices(uid).where(filter=FieldFilter("archived", "==", True)).stream():
        d = s.to_dict()
        out.append({"id": s.id, "name": d.get("name"), "archivedAt": d.get("archivedAt"), "purgeAt": d.get("purgeAt")})
    return sorted(out, key=lambda x: str(x["archivedAt"]), reverse=True)
