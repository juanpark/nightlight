"""Runbooks: when a fix worked on a device, the steps are kept for that device (and maybe one of its services), so next
time Nightlight can offer "last time this fixed it". A runbook is never run by itself: using one proposes its steps the
normal way (a card per job; an expert command still needs the owner's passkey signature). Job parameters are checked
by the capability registry when the runbook is used, not when it is saved: the device may have changed since."""

import json

from google.cloud import firestore

from . import db, notebook, real, sim
from .errors import invalid, not_found
from .ids import new_id
from .redact import scrub, scrub_value

PER_DEVICE = 20
STEPS = 10
TITLE_CHARS = 80
WHEN_CHARS = 200
SAY_CHARS = 200
COMMAND_CHARS = 500  # as long as an expert command may be (expert.MAX_COMMAND)
PARAMS_BYTES = 300
# The jobs a runbook may name: changes the person approves. Reads are for investigating, which the agent does itself.
JOBS = {"restart_container", "restart_service", "fix", *sim.ACTIONS}


def _ref(uid: str, device_id: str):
    return db.device(uid, device_id).collection("runbooks")


def _text(value, limit: int, field: str, required: bool = True) -> str:
    clean, hidden = scrub(" ".join(str(value or "").split()))
    if hidden:
        raise ValueError(f"looks_secret:{field}")
    if required and not clean:
        raise ValueError(f"empty:{field}")
    return clean[:limit - 1].rstrip() + "…" if len(clean) > limit else clean


def clean_steps(steps) -> list[dict]:
    """Each step: something to say, plus at most one job ({type, params}) or one expert command (kept as text only).
    A job may also be given as its type with `params` next to it. ValueError(code) when a step can't be kept."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= STEPS:
        raise ValueError("steps")
    out = []
    for raw in steps:
        if not isinstance(raw, dict):
            raise ValueError("steps")
        step = {"say": _text(raw.get("say"), SAY_CHARS, "say")}
        job, command = raw.get("job"), raw.get("command")
        if job and command:
            raise ValueError("job_or_command")
        if job:
            kind, params = (job.get("type"), job.get("params")) if isinstance(job, dict) else (job, raw.get("params"))
            params = params or {}
            if kind not in JOBS or not isinstance(params, dict) or len(json.dumps(params)) > PARAMS_BYTES:
                raise ValueError("unknown_job")
            params, hidden = scrub_value(params)
            if hidden:
                raise ValueError("looks_secret:params")
            step["job"] = {"type": kind, "params": params}
        elif command:
            if not isinstance(command, str) or len(command) > COMMAND_CHARS or "\x00" in command:
                raise ValueError("command")
            step["command"] = _text(command, COMMAND_CHARS, "command")
        out.append(step)
    return out


def _current(docs, generation: int | None) -> list:
    return [s for s in docs if (s.to_dict() or {}).get("demoGeneration", generation) == generation]


def save(uid: str, device_id: str, title: str, when: str, steps, by: str, generation: int | None, fence=None,
         service: str | None = None) -> dict:
    """Keep (or, under the same title, replace) a runbook for this device. Text is scrubbed: something that looks like
    a secret is refused, not stored. At most PER_DEVICE per device."""
    title = _text(title, TITLE_CHARS, "title")
    when = _text(when, WHEN_CHARS, "when")
    steps = clean_steps(steps)

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
        svc = notebook.service_named(list(db.services(uid, device_id).get(transaction=tx)), service)
        have = _current(_ref(uid, device_id).get(transaction=tx), user.get("demoGeneration"))
        same = next((s for s in have if str((s.to_dict() or {}).get("title")).lower() == title.lower()), None)
        if not same and len(have) >= PER_DEVICE:
            raise ValueError("too_many_runbooks")
        old = same.to_dict() if same else {}
        rid = same.id if same else new_id("rb")
        doc = {"title": title, "when": when, "steps": steps, "createdBy": by,
               "createdAt": old.get("createdAt") or firestore.SERVER_TIMESTAMP,
               "updatedAt": firestore.SERVER_TIMESTAMP, "uses": old.get("uses", 0),
               "lastUsedAt": old.get("lastUsedAt")}
        if svc:
            doc["svcId"], doc["service"] = svc
        if snap.to_dict().get("realm") != "real":
            doc["demoGeneration"] = user.get("demoGeneration")
        tx.set(_ref(uid, device_id).document(rid), doc)
        return {"id": rid, "replaced": bool(same),
                **{k: v for k, v in doc.items() if k not in ("createdAt", "updatedAt")}}

    return db.run_transaction(run)


def _row(s) -> dict:
    d = s.to_dict() or {}
    return {"id": s.id, **{k: d.get(k) for k in ("title", "when", "service", "steps", "createdBy", "uses",
                                                  "lastUsedAt", "createdAt") if d.get(k) is not None}}


def listed(uid: str, device_id: str, generation: int | None) -> list[dict]:
    """Every runbook for the device, the most used first, then the newest."""
    rows = [_row(s) for s in _current(_ref(uid, device_id).get(), generation)]
    rows.sort(key=lambda r: str(r.get("createdAt")), reverse=True)
    rows.sort(key=lambda r: r.get("uses") or 0, reverse=True)
    return rows


def titles(uid: str, device_id: str, generation: int | None) -> list[dict]:
    """What the agent sees with the device: enough to offer one ("Last time this fixed it: ...")."""
    return [{k: r[k] for k in ("id", "title", "when", "service", "uses") if r.get(k) is not None}
            for r in listed(uid, device_id, generation)]


def get(uid: str, device_id: str, runbook_id: str, generation: int | None) -> dict:
    snap = _ref(uid, device_id).document(runbook_id).get()
    if not snap.exists or not _current([snap], generation):
        raise not_found()
    return _row(snap)


def used(uid: str, device_id: str, runbook_id: str, turn_id: str) -> None:
    """Count a use, once per turn (a retried turn proposes the same cards again; it is still one use)."""

    @firestore.transactional
    def run(tx):
        ref = _ref(uid, device_id).document(runbook_id)
        d = ref.get(transaction=tx).to_dict()
        if not d or d.get("lastUsedTurn") == turn_id:
            return
        tx.update(ref, {"uses": (d.get("uses") or 0) + 1, "lastUsedAt": firestore.SERVER_TIMESTAMP,
                        "lastUsedTurn": turn_id})

    db.run_transaction(run)


def edit(uid: str, device_id: str, runbook_id: str, generation: int | None, title: str | None = None,
         when: str | None = None) -> dict:
    """The owner renames a runbook or rewrites when to use it (steps are not edited here)."""
    try:
        update = {k: _text(v, n, k) for k, v, n in (("title", title, TITLE_CHARS), ("when", when, WHEN_CHARS))
                  if v is not None}
    except ValueError as e:
        code, field = str(e).split(":")
        raise invalid(field, code) from None

    @firestore.transactional
    def run(tx):
        user = db.user(uid).get(transaction=tx).to_dict()
        from .actions import _require_ready
        _require_ready(user)
        ref = _ref(uid, device_id).document(runbook_id)
        snap = ref.get(transaction=tx)
        if not snap.exists or not _current([snap], user.get("demoGeneration")):
            raise not_found()
        if update:
            tx.update(ref, {**update, "updatedAt": firestore.SERVER_TIMESTAMP})
        return {"id": runbook_id, **(snap.to_dict() or {}), **update}

    out = db.run_transaction(run)
    return {k: v for k, v in out.items() if k not in ("updatedAt", "lastUsedTurn", "svcId", "demoGeneration")}


def remove(uid: str, device_id: str, runbook_id: str, generation: int | None) -> dict:
    get(uid, device_id, runbook_id, generation)
    ref = _ref(uid, device_id).document(runbook_id)

    @firestore.transactional
    def run(tx):  # a transaction, so the request's fence (a live demo machine's lease) is checked with the delete
        ref.get(transaction=tx)
        tx.delete(ref)

    db.run_transaction(run)
    return {"ok": True}
