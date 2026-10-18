"""Proposing and deciding actions. The only code that changes simulated device state.

`decide` and the automatic path each run as ONE Firestore transaction: decision, simulator mutation, result, trust
update, continuation turn and the stored response commit together or not at all.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from . import capabilities, conversation, db, real, sim, trust as trustlib
from .redact import scrub
from .errors import ApiError, conflict, not_found
from .ids import action_id as make_action_id, canonical_params, continuation_turn_id, proposal_key

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
                      by: str, ok: bool) -> dict:
    """Apply an outcome to trust (returns the new trust doc); on failure also demote unpinned device/service
    overrides for this scope."""
    after = trustlib.after_outcome(trust_doc, action, ok, by, _now())
    tx.set(trust_ref, after)
    if ok:
        return after
    if (update := trustlib.demoted_overrides(device, action["type"])):
        tx.update(db.device(uid, device["id"]), update)
    if service and (update := trustlib.demoted_overrides(service, action["type"])):
        tx.update(db.services(uid, device["id"]).document(service["id"]), update)
    return after


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
        after = _invalidate_trust(tx, uid, a, device, service, trust_doc, trust_ref, by, ok)
        opened = ((after or {}).get("offer") or {}) if not (trust_doc or {}).get("offer") else {}
    else:
        a["status"] = "denied"
        opened = {}
    if by == "user":
        conversation.post(tx, uid, a, "job_finished" if decision == "approve" else "job_declined", device["name"],
                          service=service, offer=opened.get("text"))
        a["response"] = {"actionId": a["id"], "status": a["status"], "continuationTurnId": a["continuationTurnId"]}
    tx.set(db.action(uid, a["id"]), {k: v for k, v in a.items() if k != "id"})
    return a


def label(action_type: str) -> str:
    cap = capabilities.get(action_type)
    return cap.label if cap else sim.ACTIONS[action_type]["label"]


def _read_context(tx, uid: str, device_id: str, action_type: str):
    user_snap = db.user(uid).get(transaction=tx)
    device_snap = db.device(uid, device_id).get(transaction=tx)
    services = [dict(s.to_dict(), id=s.id) for s in db.services(uid, device_id).get(transaction=tx)]
    trust_ref = db.trust_doc(uid, "sim", action_type)
    trust_snap = trust_ref.get(transaction=tx)
    return user_snap, device_snap, services, trust_ref, trust_snap


def _waiting_card(tx, uid: str, device_id: str, action_type: str, params: dict, generation,
                  same_problem: set[str] = frozenset()) -> dict | None:
    """A card on this device still waiting for the person, from any turn, for the same job or for another job that
    answers the same problem (`same_problem`). Asking for a fix again (a second question, another chat, another way
    to free the same disk) gets that card back, marked `waiting`, instead of a twin piling up."""
    q = db.actions(uid).where(filter=FieldFilter("deviceId", "==", device_id)).where(
        filter=FieldFilter("status", "==", "pending"))
    found = []
    for snap in q.get(transaction=tx):
        a = snap.to_dict()
        if a.get("demoGeneration") != generation:
            continue
        if a.get("type") == action_type and (a.get("params") or {}) == (params or {}):
            return dict(a, id=snap.id, waiting=True)
        if a.get("type") != action_type and a.get("type") in same_problem:  # same job, other target: its own card
            found.append(dict(a, id=snap.id, waiting=True))
    return found[0] if found else None


RECENT = timedelta(hours=6)  # how far back an earlier attempt still matters to a new proposal


def _recent(a: dict, session_id: str | None) -> bool:
    if session_id and a.get("sessionId") == session_id:
        return True
    at = a.get("finishedAt")
    return isinstance(at, datetime) and datetime.now(timezone.utc) - at < RECENT


def _ended(tx, uid: str, device_id: str, status: str, action_type: str, generation, session_id: str | None,
           params: dict | None = None) -> dict | None:
    """The latest recent job of this type on this device that ended with `status` (failed, denied), or None."""
    q = db.actions(uid).where(filter=FieldFilter("deviceId", "==", device_id)).where(
        filter=FieldFilter("status", "==", status))
    hits = [a for a in (s.to_dict() for s in q.get(transaction=tx))
            if a.get("type") == action_type and a.get("demoGeneration") == generation and _recent(a, session_id)
            and (params is None or (a.get("params") or {}) == (params or {}))]
    hits.sort(key=lambda a: a["finishedAt"] if isinstance(a.get("finishedAt"), datetime) else datetime.min.replace(
        tzinfo=timezone.utc))
    return hits[-1] if hits else None


def _last_attempt(tx, uid: str, device_id: str, action_type: str, params: dict, generation,
                  session_id: str | None) -> dict | None:
    """When the same job on this device failed recently: how it ended, for the proposal's result (the model then
    says it failed last time and why)."""
    a = _ended(tx, uid, device_id, "failed", action_type, generation, session_id, params)
    if not a:
        return None
    at = a.get("finishedAt")
    return {"status": "failed", "reason": (a.get("result") or {}).get("summary") or "it didn't finish",
            **({"minutesAgo": int((datetime.now(timezone.utc) - at).total_seconds() // 60)}
               if isinstance(at, datetime) else {})}


def propose(uid: str, *, session_id: str, turn_id: str, generation: int, action_type: str, device_id: str,
            params: dict, fence=None, mode: str = "quick", skip_safer: bool = False) -> dict:
    """Create (or find) the action for this logical operation. Sample-home jobs run at once when trust allows; a
    real device's capability follows its own approval rule (capabilities.py).

    What comes back is the action, with at most these marks: `waiting` (a card for this, or for another fix for the
    same problem, was already waiting: nothing new was made), `saferFirst` ({insteadOf, why}: a safer step comes
    first, and this is its card; once it has run, or the person declined it or it failed recently, the job asked for
    is proposed as usual; `skip_safer` when the person said to skip it), `lastAttempt` (the same job here failed
    recently: how).

    `fence(tx)` lets the turn engine abort if its lease or attempt is no longer current.
    """
    if capabilities.get(action_type):
        return request(uid, action_type, device_id, params, session_id=session_id, turn_id=turn_id,
                       generation=generation, fence=fence, mode=mode)
    if action_type not in sim.ACTIONS:
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
        if device.get("realm") == "real":
            raise ValueError("not_applicable")  # simulated jobs on the sample home only
        # Identity first, from stable inputs only: a retried turn must find its action even when the job has
        # already run and would no longer apply (e.g. an update that is now installed).
        key = proposal_key(generation, turn_id, device_id, sim.service_for(device, action_type), action_type, params)
        aid = make_action_id(key)
        existing = db.action(uid, aid).get(transaction=tx)
        if existing.exists:
            return dict(existing.to_dict(), id=aid)
        first = None if skip_safer else sim.safer_first(device, _by_id(services), action_type)
        if first and not any(_ended(tx, uid, device_id, s, first[0], generation, session_id)
                             for s in ("denied", "failed")):  # declined or tried: never a trap
            a = _create_sim(tx, uid, user, device, services, first[0], {}, generation, session_id, turn_id, mode)
            return dict(a, saferFirst={"insteadOf": action_type, "why": first[1]})
        return _create_sim(tx, uid, user, device, services, action_type, params, generation, session_id, turn_id,
                           mode, trust_ref, trust_snap)

    return db.run_transaction(run, max_attempts=MAX_ATTEMPTS)


def _create_sim(tx, uid: str, user: dict, device: dict, services: list[dict], action_type: str, params: dict,
                generation: int, session_id: str, turn_id: str, mode: str, trust_ref=None,
                trust_snap=None) -> dict:
    """Find or make one sample-home proposal inside the caller's transaction (no writes have happened yet)."""
    device_id = device["id"]
    key = proposal_key(generation, turn_id, device_id, sim.service_for(device, action_type), action_type, params)
    aid = make_action_id(key)
    existing = db.action(uid, aid).get(transaction=tx)
    if existing.exists:
        return dict(existing.to_dict(), id=aid)
    if twin := _waiting_card(tx, uid, device_id, action_type, params, generation, sim.same_problem(action_type)):
        return twin
    last = _last_attempt(tx, uid, device_id, action_type, params, generation, session_id)
    if trust_ref is None:
        trust_ref = db.trust_doc(uid, "sim", action_type)
        trust_snap = trust_ref.get(transaction=tx)
    c = sim.card(device, _by_id(services), action_type, params)  # only a genuinely new proposal is validated
    trust_doc = trust_snap.to_dict() if trust_snap.exists else trustlib.new_doc(action_type, generation)
    decision = trustlib.resolve(user, trust_doc, device, _service_doc(services, c["svcId"]), action_type, params)
    action = {"id": aid, "proposalKey": key, "type": action_type, "deviceId": device_id, "params": params,
              **c, "status": "pending", "demoGeneration": generation, "deviceVersion": device["version"],
              "trustLevelAtProposal": decision["level"], "resolvedBy": decision["resolvedBy"], "realm": "sim",
              "sessionId": session_id, "turnId": turn_id, "mode": mode, "createdAt": _now()}
    if decision["auto"]:
        action = _finish(tx, uid, action, device, services, trust_doc, trust_ref, "approve", "auto", None)
    else:
        tx.set(db.action(uid, aid), {k: v for k, v in action.items() if k != "id"})
    return dict(action, lastAttempt=last) if last else action


# ------------------------------------------------------------------ real devices: one pipeline for every capability

REUSE_READ = timedelta(minutes=5)  # a device read finished this recently (or still running) answers the same ask
CHAIN_LIMIT = 1  # an event turn at this chain depth or deeper starts no new device reads (it narrates instead)


def _age(at) -> float | None:
    return (datetime.now(timezone.utc) - at).total_seconds() if isinstance(at, datetime) else None


def _chat_turn(tx, uid: str, session_id: str | None, turn_id: str) -> dict | None:
    """The chat turn asking (its doc), or None when the ask doesn't come from a chat turn (the app, Nightlight)."""
    if not session_id:
        return None
    snap = db.turns(uid, session_id).document(turn_id).get(transaction=tx)
    return snap.to_dict() if snap.exists else None


def _read_key(device_id: str, name: str, params: dict) -> str:
    """A fixed-length map key for a read's identity: Firestore field names are capped at 1,500 bytes, and a signed
    expert read's parameters can be longer (Codex read-chain rev2). A playbook id may follow as "|<playbook>"."""
    ident = f"{device_id}|{name}|{canonical_params(params)}"
    return "r" + hashlib.sha256(ident.encode()).hexdigest()[:40]


RECENT_READS_KEEP = 20  # entries in a chat's recentReads map (pruned by age too)


def _same_read(tx, recent: dict, key: str, device: dict, generation, playbook: str | None) -> dict | None:
    """The same device read in this chat that is still running or finished within REUSE_READ, and that started after
    the device's last possible change (devices/{id}.changedAt, set when a changing job is handed over and when it
    reports, whatever the outcome). Constant cost: the chat's small recentReads map, then one action doc. Production
    2026-10-18: each Investigate follow-up re-ran the same disk checkup, the device took longer than the in-turn
    wait, and the new job's own follow-up asked again: five turns repeating one summary."""
    entries = [e for k, e in recent.items() if k == key or k.startswith(key + "|")]
    entries = [e for e in entries if not playbook or e.get("playbook") == playbook]
    if not entries:
        return None
    entry = max(entries, key=lambda e: e.get("startedAt") or datetime.min.replace(tzinfo=timezone.utc))
    snap = db.action(device["uid"], entry["actionId"]).get(transaction=tx)
    a = dict(snap.to_dict(), id=snap.id) if snap.exists else None
    if not a or a.get("demoGeneration") != generation:
        return None
    started = _age(a.get("createdAt"))
    changed = device.get("changedAt")
    if started is None or (isinstance(changed, datetime) and changed >= a["createdAt"]):
        return None  # something may have changed on the device since: measure again
    if a.get("status") in ("approved", "running"):
        ok = started < READ_REPORT_TIMEOUT.total_seconds()
    else:
        ended = _age(a.get("finishedAt"))
        ok = a.get("status") == "done" and ended is not None and ended < REUSE_READ.total_seconds()
    return dict(a, reused=True, ageSeconds=int(started)) if ok else None


def _remember_read(recent: dict, key: str, action_id_: str, playbook: str | None) -> dict:
    """The chat's recentReads map with this read added, pruned by age and size (written by the caller)."""
    now = datetime.now(timezone.utc)
    keep = REUSE_READ + READ_REPORT_TIMEOUT
    fresh = {k: e for k, e in recent.items()
             if isinstance(e.get("startedAt"), datetime) and now - e["startedAt"] < keep}
    fresh[key + (f"|{playbook}" if playbook else "")] = {"actionId": action_id_, "startedAt": now,
                                                          **({"playbook": playbook} if playbook else {})}
    newest = sorted(fresh.items(), key=lambda kv: kv[1]["startedAt"], reverse=True)[:RECENT_READS_KEEP]
    return dict(newest)

def request(uid: str, name: str, device_id: str, params: dict, *, session_id: str | None, turn_id: str,
            generation: int | None = None, fence=None, origin: str = "chat", mode: str = "quick",
            extra: dict | None = None, once: bool = False) -> dict:
    """Ask a real device for a capability. Who asks decides only one thing: a person confirming in the app
    (`origin="app"`) has approved a one-tap capability already. Everything else comes from the registry: a read the
    device allows runs without a card, other jobs wait for a tap, signed ones for the owner's passkey.
    ValueError(code) when the capability doesn't apply to this device."""
    from . import live
    if name in live.POOL_FORBIDDEN_ACTIONS and live.pool_slot(uid):
        raise ValueError("not_on_demo_machine")  # chat, playbooks and app routes alike: never a card for it
    cap = capabilities.get(name)
    if not cap:
        raise ApiError(422, "unknown_action")

    @firestore.transactional
    def run(tx):
        if fence:
            fence(tx)
        user_snap, device_snap, services, _, _ = _read_context(tx, uid, device_id, name)
        user = user_snap.to_dict() if user_snap.exists else None
        _require_ready(user, generation)
        if not device_snap.exists:
            raise not_found()
        device = dict(device_snap.to_dict(), id=device_id)
        if device.get("realm") != "real" or device.get("archived"):
            raise ValueError("not_applicable")
        gen = user.get("demoGeneration") if generation is None else generation
        key = proposal_key(gen, turn_id, device_id, real.service_for(params), name, params)
        aid = make_action_id(key)
        existing = db.action(uid, aid).get(transaction=tx)
        old = existing.to_dict() if existing.exists else None
        if old and (origin != "app" or once or old.get("status") in ("pending", "approved", "running")):
            return dict(old, id=aid)  # recovery first: identity never depends on current state; `once`: a finished
            # job is never reopened under its identity (a new one needs a new identity)
        if real.view(device).get("stale") and not cap.while_silent:
            raise ValueError("device_not_reporting")
        fields, clean = cap.build(capabilities.Ctx(uid, device, _by_id(services), params))
        chain, remember = {}, None
        if cap.reads and cap.approval == "device" and origin == "chat" and (turn := _chat_turn(tx, uid, session_id,
                                                                                               turn_id)):
            # Reads are de-duplicated per chat, and a chain of automatic follow-ups is bounded: a job started in an
            # event turn makes the next follow-up one step deeper, and at CHAIN_LIMIT it may only narrate.
            playbook = (extra or {}).get("playbook")
            recent = (db.session(uid, session_id).get(transaction=tx).to_dict() or {}).get("recentReads") or {}
            rkey = _read_key(device_id, name, clean)
            same = _same_read(tx, recent, rkey, dict(device, uid=uid), gen, playbook)
            if same:
                return same
            event = turn.get("kind") == "event"
            depth = int(turn.get("chainDepth") or 0) if event else 0
            if event and depth >= CHAIN_LIMIT:
                raise ValueError("chain_limit")
            chain = {"chainDepth": depth + 1 if event else 0, "causedByTurn": turn_id}
            remember = _remember_read(recent, rkey, aid, playbook)
        approved = cap.approval == "device" or (origin == "app" and cap.approval == "card")
        if not approved and (twin := _waiting_card(tx, uid, device_id, name, clean, gen)):
            return twin
        last = None if cap.reads else _last_attempt(tx, uid, device_id, name, clean, gen, session_id)
        a = {"id": aid, "proposalKey": key, "type": name, "deviceId": device_id, "params": clean, **fields,
             "status": "approved" if approved else "pending", "realm": "real", "demoGeneration": gen,
             "deviceVersion": device.get("version"), "trustLevelAtProposal": "ask", "resolvedBy": "real_device",
             "sessionId": session_id, "turnId": turn_id, "mode": mode, "createdAt": _now(), **chain, **(extra or {})}
        if approved:
            a["decision"] = {"by": "owner_allowed_on_device" if cap.approval == "device" else "user",
                             "decision": "approve"}
        tx.set(db.action(uid, aid), {k: v for k, v in a.items() if k != "id"})
        if remember is not None:
            tx.set(db.session(uid, session_id), {"recentReads": remember}, merge=["recentReads"])
        return dict(a, lastAttempt=last) if last else a

    a = db.run_transaction(run, max_attempts=MAX_ATTEMPTS)
    if a.get("reused"):
        return a
    if a.get("status") == "approved" and cap.after_approval:
        cap.after_approval(uid, a)
    return db.action(uid, a["id"]).get().to_dict() | {"id": a["id"]} if cap.after_approval else a


def decide(uid: str, action_id_: str, decision: str, note: str | None = None) -> tuple[int, dict]:
    """Approve or deny a pending card. Returns (HTTP status, body): 202 first time, 200 for a replay."""

    @firestore.transactional
    def run(tx):
        action_snap = db.action(uid, action_id_).get(transaction=tx)
        if not action_snap.exists:
            raise not_found()
        action = dict(action_snap.to_dict(), id=action_id_)
        from . import live
        if decision == "approve" and action.get("type") in live.POOL_FORBIDDEN_ACTIONS and live.pool_slot(uid):
            raise ApiError(403, "live_demo_machine")  # a card made before this rule (or any other way) can't run
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
            return _decide_real(tx, uid, action, device, decision, note,  # no trust ladder for real jobs (yet)
                                _service_doc(services, action.get("svcId")), services=services)
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
    if body.get("status") == "approved":
        approved(uid, action_id_)  # the capability's own follow-up, if it has one
    return status, body


def _decide_real(tx, uid: str, action: dict, device: dict | None, decision: str, note: str | None,
                 service: dict | None = None, services: list | None = None):
    """Approving a real-device job queues it for that device's helper (it runs there, later); declining ends it.

    A real device reports every minute, so its version can't fence the card; the helper re-checks the target on the
    device before acting instead."""
    cap = capabilities.get(action["type"])
    if decision == "approve" and cap and cap.approval == "passkey":
        raise conflict("needs_passkey", actionId=action["id"])  # only the owner's passkey signature approves
    a = dict(action)
    a["decision"] = {k: v for k, v in {"by": "user", "decision": decision, "note": note, "at": _now()}.items()
                     if v is not None}
    if device is None or device.get("revoked") and not (cap and cap.while_silent):
        tx.update(db.action(uid, a["id"]), {"status": "stale", "finishedAt": _now()})
        return 409, {"error": "conflict", "code": "stale", "actionId": a["id"]}
    if decision == "approve" and cap and cap.on_approve:
        # The server carries it out now, in this transaction (e.g. a permission): it is never handed to a device
        try:
            summary = cap.on_approve(tx, uid, a, device, services or [])
        except (ValueError, ApiError):  # overtaken since the card went up (allowed meanwhile, target gone)
            tx.update(db.action(uid, a["id"]), {"status": "stale", "finishedAt": _now()})
            return 409, {"error": "conflict", "code": "stale", "actionId": a["id"]}
        a["status"], a["finishedAt"] = "done", _now()
        a["result"] = {"ok": True, "summary": summary}
        if a.get("sessionId"):
            conversation.post(tx, uid, a, "job_finished", device["name"])
        else:
            a["followUp"] = "none"
        a["response"] = {"actionId": a["id"], "status": "done",
                         **({"continuationTurnId": a["continuationTurnId"]} if a.get("continuationTurnId") else {})}
    elif decision == "approve":
        a["status"] = "approved"
        a["response"] = {"actionId": a["id"], "status": "approved"}
    else:
        a["status"] = "denied"
        a["finishedAt"] = _now()
        conversation.post(tx, uid, a, "job_declined", device["name"], service=service)
        a["response"] = {"actionId": a["id"], "status": "denied", "continuationTurnId": a["continuationTurnId"]}
    tx.set(db.action(uid, a["id"]), {k: v for k, v in a.items() if k != "id"})
    return 202, a["response"]


def approved(uid: str, action_id_: str) -> None:
    """After an approval was committed: the capability's own follow-up (e.g. a removal the device can't do itself
    finishes now). Called by every path that approves."""
    a = db.action(uid, action_id_).get().to_dict() or {}
    cap = capabilities.get(a.get("type"))
    if cap and cap.after_approval and a.get("status") == "approved":
        cap.after_approval(uid, dict(a, id=action_id_))


def signed(uid: str, action_id_: str, signature: dict, result_summary: str | None = None) -> dict:
    """The owner signed a passkey card (the signature was checked by expert.sign). A job for the device is now
    approved and carries the signature; one that only unlocks others (a grant) is done, and the chat that asked
    carries on (an `investigation_approved` event)."""

    @firestore.transactional
    def run(tx):
        ref = db.action(uid, action_id_)
        a = ref.get(transaction=tx).to_dict()
        dsnap = db.device(uid, a["deviceId"]).get(transaction=tx) if a else None
        if not a or a.get("status") != "pending":
            raise conflict("not_pending", actionId=action_id_)
        a = dict(a, id=action_id_)
        cap = capabilities.get(a["type"])
        a["params"] = {**a["params"], "signed": signature}
        a["decision"] = {"by": "user", "decision": "approve", "with": "passkey"}
        writes = cap.on_signed(tx, uid, a) if cap.on_signed else []
        if cap.on_device:
            a["status"] = "approved"
        else:
            a["status"], a["finishedAt"], a["followUp"] = "done", _now(), "none"
            a["result"] = {"ok": True, "summary": result_summary or "Approved."}
            if a.get("sessionId"):
                conversation.post(tx, uid, a, "investigation_approved",
                                  ((dsnap.to_dict() if dsnap and dsnap.exists else {}) or {}).get("name", "device"),
                                  mode="investigate")
        tx.set(ref, {k: v for k, v in a.items() if k != "id"})
        for wref, doc, merge in writes:  # e.g. the grant: activation commits with the card and its event
            tx.set(wref, doc, merge=merge)
        return a

    a = db.run_transaction(run, max_attempts=MAX_ATTEMPTS)
    cap = capabilities.get(a["type"])
    if cap.after_approval and cap.on_device:
        cap.after_approval(uid, a)
    return {"ok": True, "actionId": action_id_, "status": a["status"],
            **({"continuationTurnId": a["continuationTurnId"]} if a.get("continuationTurnId") else {})}


def request_diagnosis(uid: str, *, session_id: str, turn_id: str, generation: int, device_id: str, target: str,
                      fence=None, mode: str = "quick") -> dict:
    """Ask a real device to look into one target (read-only, allowed by the owner on the device: no card)."""
    return request(uid, "diagnose", device_id, {"target": target}, session_id=session_id, turn_id=turn_id,
                   generation=generation, fence=fence, mode=mode)


def request_inspection(uid: str, *, session_id: str | None, turn_id: str, generation: int, device_id: str,
                       what: list, fence=None, extra: dict | None = None, mode: str = "quick") -> dict:
    """Ask a real device to run some of its fixed read-only checks (disk use, programs, updates...)."""
    return request(uid, "inspect", device_id, {"what": what}, session_id=session_id, turn_id=turn_id,
                   generation=generation, fence=fence, extra=extra, mode=mode)


def request_read_command(uid: str, *, session_id: str, turn_id: str, generation: int, device_id: str, command: str,
                         fence=None, mode: str = "quick") -> dict:
    """One read-only command under the owner's signed investigation grant (the device checks both again)."""
    return request(uid, "expert_read", device_id, {"command": command}, session_id=session_id, turn_id=turn_id,
                   generation=generation, fence=fence, mode=mode)


def approved_job(uid: str, device_id: str, action_type: str, params: dict, *, session_id: str | None,
                 turn_id: str) -> dict:
    """A real job the owner asked for directly in the app (their confirmation is the approval)."""
    return request(uid, action_type, device_id, params, session_id=session_id, turn_id=turn_id, origin="app")


def await_diagnosis(uid: str, action_id_: str) -> dict | None:
    """Called when the in-turn wait runs out: returns the result if it just arrived, else asks for a follow-up turn
    when it does (decided in one transaction with job_result, so exactly one of the two narrates it)."""

    @firestore.transactional
    def run(tx):
        ref = db.action(uid, action_id_)
        a = ref.get(transaction=tx).to_dict() or {}
        if a.get("followUp") == "wanted":
            return None  # already handed to the follow-up (e.g. by an earlier attempt of this turn)
        if a.get("status") in ("done", "failed"):
            return a
        tx.update(ref, {"followUp": "wanted"})
        return None

    return db.run_transaction(run, max_attempts=MAX_ATTEMPTS)


def job_result(token: str, action_id_: str, ok: bool, summary: str, state: str | None,
               output: str | None = None) -> dict:
    """The helper reports how a job it ran ended. Only the device the job was handed to can report it, once. The
    result is recorded the same way for every capability; the capability's own hook runs (reads first); then the
    outcome goes where it belongs: the chat that asked (an event), or Activity."""

    @firestore.transactional
    def run(tx):
        uid, device_id = real.token_owner(tx, token)
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        snap = db.action(uid, action_id_).get(transaction=tx)
        a = dict(snap.to_dict(), id=action_id_) if snap.exists else None
        if not a or a.get("deviceId") != device_id or a.get("realm") != "real":
            raise not_found()
        dsnap = db.device(uid, device_id).get(transaction=tx)
        if a["status"] in ("done", "failed"):
            return {"ok": True, "actionId": action_id_, "status": a["status"]}  # a repeated report changes nothing
        if a["status"] != "running":
            raise conflict("illegal_transition", actionId=action_id_)
        cap = capabilities.get(a["type"])
        device = dict(dsnap.to_dict() or {}, id=device_id)
        a["status"] = "done" if ok else "failed"
        a["finishedAt"] = _now()
        a["result"] = {"ok": ok, "summary": scrub(summary)[0][:200]}
        if cap.keeps_output:
            found, hidden = scrub(output or "")
            a["result"].update(output=found[:4000], hidden=hidden)
        if cap.reports_state:
            a["result"].update(before={"state": "stopped"}, after={"state": state})
        # A sample-home reset replaces the chat, never a real device: its state and Activity are always recorded; only
        # what belongs to the conversation (events, new cards) needs the chat that asked to still exist.
        current = user.get("demo", {}).get("state") == "ready" and a.get("demoGeneration") == user.get("demoGeneration")
        writes = cap.on_result(tx, uid, a, device, current) if cap.on_result else []  # its reads happen here
        for ref, doc, merge in writes:
            tx.set(ref, doc, merge=merge)
        _deliver_outcome(tx, uid, a, device, cap, current)
        if not cap.reads and dsnap.exists and a["type"] != "remove_device":  # done, failed or partly done alike
            real.mark_changed(tx, uid, device_id)
        # The helper reports right after a job, so the change shows at once; that one report may come sooner than
        # the heartbeat's minimum gap (real.heartbeat). Before this, it got a 429 and slept ~20 s with its work
        # channel closed, so the next job in the same chat waited past the in-turn wait.
        tx.update(real.tokens_ref().document(real._sha(token)), {"reportDue": True})
        return {"ok": True, "actionId": action_id_, "status": a["status"]}

    return db.run_transaction(run, max_attempts=MAX_ATTEMPTS)


def _deliver_outcome(tx, uid: str, a: dict, device: dict, cap, current: bool) -> None:
    """Where an ended device job goes (writes only): the chat that asked (an event), or Activity; then the job."""
    if not a.get("sessionId"):
        a["followUp"] = "none"
        conversation.to_activity(tx, uid, a, device)
    elif not current:
        a["followUp"] = "skipped_after_reset"  # the chat that asked is gone; the result is still recorded
    elif not cap.reads or a.get("followUp") == "wanted":  # a change, or a read the asking turn stopped waiting for
        conversation.post(tx, uid, a, "job_finished", device.get("name", "device"))
    tx.set(db.action(uid, a["id"]), {k: v for k, v in a.items() if k != "id"})


# A job handed to a device that never reports back (the helper restarted mid-job, the device went away) would stay
# "running" forever and its follow-up would never come: after this long it ends as failed, saying so plainly.
REPORT_TIMEOUT = timedelta(minutes=10)
READ_REPORT_TIMEOUT = timedelta(minutes=3)  # reads (look into, inspect) answer in seconds
NO_REPORT = ("The device didn't report back (it may have restarted). Nothing is known to have changed; ask again to "
             "retry.")


def expire_unreported(uid: str, action_id_: str) -> bool:
    """End a handed-over job whose device never reported, once its time is up: failed, with NO_REPORT as its result,
    and its outcome delivered like any result (the waiting follow-up gets it). True when this call ended it. A late
    report afterwards changes nothing (job_result keeps the first ending)."""

    @firestore.transactional
    def run(tx):
        ref = db.action(uid, action_id_)
        snap = ref.get(transaction=tx)
        a = dict(snap.to_dict(), id=action_id_) if snap.exists else None
        if not a or a.get("realm") != "real" or a.get("status") != "running":
            return False
        cap = capabilities.get(a["type"])
        claimed = a.get("claimedAt")
        limit = READ_REPORT_TIMEOUT if cap and cap.reads else REPORT_TIMEOUT
        if not cap or not isinstance(claimed, datetime) or datetime.now(timezone.utc) - claimed < limit:
            return False
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        device = dict(db.device(uid, a["deviceId"]).get(transaction=tx).to_dict() or {}, id=a["deviceId"])
        a["status"], a["finishedAt"] = "failed", _now()
        a["result"] = {"ok": False, "summary": NO_REPORT, "noReport": True}
        current = user.get("demo", {}).get("state") == "ready" and a.get("demoGeneration") == user.get("demoGeneration")
        _deliver_outcome(tx, uid, a, device, cap, current)
        if not cap.reads and device.get("realm") == "real" and a["type"] != "remove_device":
            real.mark_changed(tx, uid, a["deviceId"])
        return True

    return db.run_transaction(run, max_attempts=MAX_ATTEMPTS)


def expire_device_jobs(uid: str, device_id: str) -> int:
    """The sweep's pass over one device: end its handed-over jobs that never reported (see expire_unreported)."""
    running = db.actions(uid).where(filter=FieldFilter("deviceId", "==", device_id)).where(
        filter=FieldFilter("status", "==", "running")).get()
    return sum(expire_unreported(uid, snap.id) for snap in running)
