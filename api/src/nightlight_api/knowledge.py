"""What Nightlight knows about one device, like an administrator's folder on a machine: its profile, its notebook (per
service too), its runbooks, and the log of every job that ran there. The log is read from the jobs themselves
(`actions`), so nothing is stored twice."""

from google.cloud.firestore_v1.base_query import FieldFilter

from . import db, notebook, playbooks, real, runbooks
from .errors import not_found
from .redact import scrub

LOG_LIMIT = 100
OUTPUT_CHARS = 2000  # what a log row keeps of a job's printed output (already scrubbed when it was stored)


def _device(uid: str, device_id: str, generation: int | None) -> dict:
    snap = db.device(uid, device_id).get()
    if not snap.exists or not real.is_current(snap.to_dict(), generation):
        raise not_found()
    return dict(snap.to_dict(), id=device_id)


def _by(a: dict) -> str:
    """Who set the job going: "you" (the person approved or asked for it), "nightlight" (on its own: a read the owner
    allows on the device, or a job they let run without asking) or "device" (the device's own report started it, as
    with the look after a restart)."""
    who = (a.get("decision") or {}).get("by")
    if who == "user":
        return "you"
    if who == "owner_allowed_on_device" and not a.get("sessionId"):
        return "device"
    return "nightlight"


def _row(a: dict, services: dict, output_chars: int) -> dict:
    r = a.get("result") or {}
    p = a.get("params") or {}
    pb = r.get("playbook")
    row = {"at": a.get("finishedAt") or a.get("decidedAt") or a.get("createdAt"), "kind": "playbook" if a.get("playbook") else a.get("type"),
           "title": f"Checkup: {pb.get('title')}" if pb else a.get("plan"),
           "ok": a.get("status") == "done",
           "summary": scrub(playbooks.summary(pb) if pb else str(r.get("summary") or ""))[0][:600],
           "by": _by(a), "actionId": a["id"]}
    service = p.get("container") or p.get("unit") or p.get("target") or services.get(a.get("svcId"))
    if service:
        row["service"] = service
    if r.get("output") and output_chars:
        row["output"] = scrub(r["output"])[0][:output_chars]
    if p.get("command") and isinstance(p["command"], str):
        row["command"] = scrub(p["command"])[0][:500]
    return row


def log(uid: str, device_id: str, generation: int | None, limit: int = 50, service: str | None = None,
        output_chars: int = OUTPUT_CHARS) -> list[dict]:
    """Every job that finished on this device, newest first: what it was, who set it going, how it ended. A sample
    device shows only its current generation's jobs; `service` keeps the jobs about that service (id or name)."""
    d = _device(uid, device_id, generation)
    names = {s.id: (s.to_dict() or {}).get("name") or s.id for s in db.services(uid, device_id).get()}
    q = db.actions(uid).where(filter=FieldFilter("deviceId", "==", device_id)).where(
        filter=FieldFilter("status", "in", ["done", "failed"]))
    jobs = [dict(s.to_dict(), id=s.id) for s in q.get()]
    if d.get("realm") != "real":
        jobs = [a for a in jobs if a.get("demoGeneration") == generation]
    jobs.sort(key=lambda a: str(a.get("finishedAt")), reverse=True)
    want = (service or "").strip().lower()
    rows = []
    for a in jobs:
        row = _row(a, names, output_chars)
        if want and want not in (str(row.get("service") or "").lower(), str(a.get("svcId") or "").lower()):
            continue
        rows.append(row)
        if len(rows) >= max(1, min(limit, LOG_LIMIT)):
            break
    return rows


def view(uid: str, device_id: str, generation: int | None) -> dict:
    """Everything the app shows on a device's knowledge page."""
    _device(uid, device_id, generation)
    return {"profile": notebook.profile(uid, device_id), "notes": notebook.everything(uid, device_id, generation),
            "runbooks": runbooks.listed(uid, device_id, generation)}
