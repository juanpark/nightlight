"""Proposing and deciding actions. The only code that changes simulated device state.

`decide` and the automatic path each run as ONE Firestore transaction: decision, simulator mutation, result, trust
update, continuation turn and the stored response commit together or not at all.
"""

from google.cloud import firestore

from . import db, real, sim, trust as trustlib
from .redact import scrub
from .errors import ApiError, conflict, not_found
from .ids import action_id as make_action_id, continuation_turn_id, proposal_key

MAX_ATTEMPTS = 25  # concurrent decides on one action retry until they see the winner's result


def _now():
    return firestore.SERVER_TIMESTAMP


def _require_ready(user: dict | None, generation: int | None = None):
    if not user:
        raise not_found()
    if user.get("demo", {}).get("state") != "ready":
        raise conflict("resetting", retryAfter=5)
    if generation is not None and user.get("demoGeneration") != generation:
        raise conflict("stale")


def _service_doc(services: list[dict], svc_id: str | None) -> dict | None:
    return next((s for s in services if s["id"] == svc_id), None)


def _by_id(services: list[dict]) -> dict:
    return {s["id"]: {k: v for k, v in s.items() if k != "id"} for s in services}


def _invalidate_trust(tx, uid: str, action: dict, device: dict, service: dict | None, trust_doc: dict, trust_ref,
                      by: str, ok: bool) -> None:
    """Apply an outcome to trust; on failure also demote unpinned device/service overrides for this scope."""
    tx.set(trust_ref, trustlib.after_outcome(trust_doc, action, ok, by, _now()))
    if ok:
        return
    if (update := trustlib.demoted_overrides(device, action["type"])):
        tx.update(db.device(uid, device["id"]), update)
    if service and (update := trustlib.demoted_overrides(service, action["type"])):
        tx.update(db.services(uid, device["id"]).document(service["id"]), update)


def _finish(tx, uid: str, action: dict, device: dict, services: list[dict], trust_doc: dict, trust_ref,
            decision: str, by: str, note: str | None) -> dict:
    """Write a decided action and everything that follows from it. Caller has done all reads."""
    a = dict(action)
    a["decision"] = {k: v for k, v in {"by": by, "decision": decision, "note": note, "at": _now()}.items()
                     if v is not None}
    a["finishedAt"] = _now()
    service = _service_doc(services, a.get("svcId"))
    if decision == "approve":
        ok, result, new_device, new_services = sim.apply(device, _by_id(services), a["type"], a["params"])
        if ok:
            new_device["version"] = device["version"] + 1  # real change: other open cards for it go stale
            new_device["lastSeen"] = _now()
            tx.set(db.device(uid, device["id"]), {k: v for k, v in new_device.items() if k != "id"})
            for svc_id, svc in new_services.items():
                tx.set(db.services(uid, device["id"]).document(svc_id), svc)
        else:
            # Nothing changed on the device. Only the simulator's one-shot failure flag is consumed, and the version
            # stays, so other open cards for this device remain valid.
            tx.update(db.device(uid, device["id"]), {"simFailNext": firestore.DELETE_FIELD})
        a["status"] = "done" if ok else "failed"
        a["result"] = result
        _invalidate_trust(tx, uid, a, device, service, trust_doc, trust_ref, by, ok)
    else:
        a["status"] = "denied"
    if by == "user":
        _queue_continuation(tx, uid, a, device["name"])
        a["response"] = {"actionId": a["id"], "status": a["status"], "continuationTurnId": a["continuationTurnId"]}
    tx.set(db.action(uid, a["id"]), {k: v for k, v in a.items() if k != "id"})
    return a


def label(action_type: str) -> str:
    return (sim.ACTIONS.get(action_type) or real.JOBS[action_type])["label"]


def _queue_continuation(tx, uid: str, a: dict, device_name: str) -> None:
    """Queue the follow-up turn that tells the person how a decided job ended."""
    cont = continuation_turn_id(a["id"])
    verb = {"done": "was approved and completed", "failed": "was approved but failed",
            "denied": "was declined"}[a["status"]]
    summary = f" Result: {a['result']['summary']}" if a.get("result") else ""
    tx.set(db.turns(uid, a["sessionId"]).document(cont), {
        "kind": "continuation", "status": "queued", "attempt": 0, "demoGeneration": a["demoGeneration"],
        "actionId": a["id"], "input": f"{label(a['type'])} on the {device_name} {verb}.{summary}",
        "createdAt": _now()})
    # Lets POST /api/turns/{turnId}/stream find the session that owns this continuation.
    tx.set(db.user(uid).collection("turnIndex").document(cont),
           {"sessionId": a["sessionId"], "demoGeneration": a["demoGeneration"]})
    a["continuationTurnId"] = cont


def _read_context(tx, uid: str, device_id: str, action_type: str):
    user_snap = db.user(uid).get(transaction=tx)
    device_snap = db.device(uid, device_id).get(transaction=tx)
    services = [dict(s.to_dict(), id=s.id) for s in db.services(uid, device_id).get(transaction=tx)]
    trust_ref = db.trust_doc(uid, "sim", action_type)
    trust_snap = trust_ref.get(transaction=tx)
    return user_snap, device_snap, services, trust_ref, trust_snap


def propose(uid: str, *, session_id: str, turn_id: str, generation: int, action_type: str, device_id: str,
            params: dict, fence=None) -> dict:
    """Create (or find) the action for this logical operation. Runs it at once when trust allows.

    `fence(tx)` lets the turn engine abort if its lease or attempt is no longer current.
    """
    if action_type not in sim.ACTIONS and action_type not in real.JOBS:
        raise ApiError(422, "unknown_action")

    @firestore.transactional
    def run(tx):
        if fence:
            fence(tx)
        user_snap, device_snap, services, trust_ref, trust_snap = _read_context(tx, uid, device_id, action_type)
        user = user_snap.to_dict() if user_snap.exists else None
        _require_ready(user, generation)
        if not device_snap.exists:
            raise not_found()
        device = dict(device_snap.to_dict(), id=device_id)
        if (device.get("realm") == "real") != (action_type in real.JOBS):
            raise ValueError("not_applicable")  # simulated jobs on the sample home, real jobs on real devices only
        if device.get("realm") == "real":
            return _propose_real(tx, uid, user, device, services, action_type, params, generation, session_id,
                                 turn_id)
        # Identity first, from stable inputs only: a retried turn must find its action even when the job has
        # already run and would no longer apply (e.g. an update that is now installed).
        key = proposal_key(generation, turn_id, device_id, sim.service_for(device, action_type), action_type, params)
        aid = make_action_id(key)
        existing = db.action(uid, aid).get(transaction=tx)
        if existing.exists:
            return dict(existing.to_dict(), id=aid)
        c = sim.card(device, _by_id(services), action_type, params)  # only a genuinely new proposal is validated
        trust_doc = trust_snap.to_dict() if trust_snap.exists else trustlib.new_doc(action_type, generation)
        decision = trustlib.resolve(user, trust_doc, device, _service_doc(services, c["svcId"]), action_type, params)
        action = {"id": aid, "proposalKey": key, "type": action_type, "deviceId": device_id, "params": params,
                  **c, "status": "pending", "demoGeneration": generation, "deviceVersion": device["version"],
                  "trustLevelAtProposal": decision["level"], "resolvedBy": decision["resolvedBy"], "realm": "sim",
                  "sessionId": session_id, "turnId": turn_id, "createdAt": _now()}
        if decision["auto"]:
            return _finish(tx, uid, action, device, services, trust_doc, trust_ref, "approve", "auto", None)
        tx.set(db.action(uid, aid), {k: v for k, v in action.items() if k != "id"})
        return action

    return db.run_transaction(run, max_attempts=MAX_ATTEMPTS)


def _propose_real(tx, uid, user, device, services, action_type, params, generation, session_id, turn_id) -> dict:
    """A real-device job always waits for a tap: no trust level lets it run on its own."""
    if real.view(device).get("stale"):
        raise ValueError("device_not_reporting")
    key = proposal_key(generation, turn_id, device["id"], real.service_for(params), action_type, params)
    aid = make_action_id(key)
    existing = db.action(uid, aid).get(transaction=tx)
    if existing.exists:
        return dict(existing.to_dict(), id=aid)
    c = real.card(device, _by_id(services), action_type, params)
    action = {"id": aid, "proposalKey": key, "type": action_type, "deviceId": device["id"], "params": params, **c,
              "status": "pending", "demoGeneration": generation, "deviceVersion": device["version"],
              "trustLevelAtProposal": "ask", "resolvedBy": "real_device", "realm": "real",
              "sessionId": session_id, "turnId": turn_id, "createdAt": _now()}
    tx.set(db.action(uid, aid), {k: v for k, v in action.items() if k != "id"})
    return action


def decide(uid: str, action_id_: str, decision: str, note: str | None = None) -> tuple[int, dict]:
    """Approve or deny a pending card. Returns (HTTP status, body): 202 first time, 200 for a replay."""

    @firestore.transactional
    def run(tx):
        action_snap = db.action(uid, action_id_).get(transaction=tx)
        if not action_snap.exists:
            raise not_found()
        action = dict(action_snap.to_dict(), id=action_id_)
        user_snap, device_snap, services, trust_ref, trust_snap = _read_context(
            tx, uid, action["deviceId"], action["type"])
        user = user_snap.to_dict() if user_snap.exists else None
        status = action["status"]
        if status != "pending":
            prior = action.get("decision", {})
            if status == "stale":
                raise conflict("stale", actionId=action_id_)
            if prior.get("by") == "user" and prior.get("decision") == decision and action.get("response"):
                return 200, action["response"]
            if prior.get("by") == "user":
                raise conflict("decision_conflict", actionId=action_id_)
            raise conflict("illegal_transition", actionId=action_id_)
        _require_ready(user)
        device = dict(device_snap.to_dict(), id=action["deviceId"]) if device_snap.exists else None
        if action.get("realm") == "real":
            return _decide_real(tx, uid, action, device, decision, note)  # no trust ladder for real jobs (yet)
        service = _service_doc(services, action.get("svcId"))
        current_generation = action["demoGeneration"] == user.get("demoGeneration")
        trust_doc = trust_snap.to_dict() if trust_snap.exists else trustlib.new_doc(action["type"],
                                                                                    action["demoGeneration"])
        if not current_generation or device is None or device.get("version") != action["deviceVersion"]:
            tx.update(db.action(uid, action_id_), {"status": "stale", "finishedAt": _now()})
            if current_generation and device is not None:
                # A card overtaken by events counts like a failure (build plan §4.5): it ends the track record and
                # withdraws any offer, once (a replay sees status 'stale' and stops above). Old-generation
                # tombstones never touch the new generation's trust.
                _invalidate_trust(tx, uid, action, device, service, trust_doc, trust_ref, "user", False)
            return 409, {"error": "conflict", "code": "stale", "actionId": action_id_}
        done = _finish(tx, uid, action, device, services, trust_doc, trust_ref, decision, "user", note)
        return 202, done["response"]

    status, body = db.run_transaction(run, max_attempts=MAX_ATTEMPTS)
    if status == 409:
        raise conflict(body["code"], actionId=body.get("actionId"))
    return status, body


def _decide_real(tx, uid: str, action: dict, device: dict | None, decision: str, note: str | None):
    """Approving a real-device job queues it for that device's helper (it runs there, later); declining ends it.

    A real device reports every minute, so its version can't fence the card; the helper re-checks the target on the
    device before acting instead."""
    a = dict(action)
    a["decision"] = {k: v for k, v in {"by": "user", "decision": decision, "note": note, "at": _now()}.items()
                     if v is not None}
    if device is None or device.get("revoked"):
        tx.update(db.action(uid, a["id"]), {"status": "stale", "finishedAt": _now()})
        return 409, {"error": "conflict", "code": "stale", "actionId": a["id"]}
    if decision == "approve":
        a["status"] = "approved"
        a["response"] = {"actionId": a["id"], "status": "approved"}
    else:
        a["status"] = "denied"
        a["finishedAt"] = _now()
        _queue_continuation(tx, uid, a, device["name"])
        a["response"] = {"actionId": a["id"], "status": "denied", "continuationTurnId": a["continuationTurnId"]}
    tx.set(db.action(uid, a["id"]), {k: v for k, v in a.items() if k != "id"})
    return 202, a["response"]


def job_result(token: str, action_id_: str, ok: bool, summary: str, state: str | None) -> dict:
    """The helper reports how a job it ran ended. Only the device the job was handed to can report it, once."""

    @firestore.transactional
    def run(tx):
        uid, device_id = real.token_owner(tx, token)
        snap = db.action(uid, action_id_).get(transaction=tx)
        a = dict(snap.to_dict(), id=action_id_) if snap.exists else None
        if not a or a.get("deviceId") != device_id or a.get("realm") != "real":
            raise not_found()
        dsnap = db.device(uid, device_id).get(transaction=tx)
        if a["status"] in ("done", "failed"):
            return {"ok": True, "actionId": action_id_, "status": a["status"]}  # a repeated report changes nothing
        if a["status"] != "running":
            raise conflict("illegal_transition", actionId=action_id_)
        text = scrub(summary)[0][:200]
        a["status"] = "done" if ok else "failed"
        a["finishedAt"] = _now()
        a["result"] = {"ok": ok, "summary": text, "before": {"state": "stopped"}, "after": {"state": state}}
        if ok and a.get("svcId"):
            tx.set(db.services(uid, device_id).document(a["svcId"]), {"status": "ok", "detail": state}, merge=True)
        _queue_continuation(tx, uid, a, (dsnap.to_dict() or {}).get("name", "device"))
        tx.set(db.action(uid, action_id_), {k: v for k, v in a.items() if k != "id"})
        return {"ok": True, "actionId": action_id_, "status": a["status"]}

    return db.run_transaction(run, max_attempts=MAX_ATTEMPTS)
