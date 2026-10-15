"""Chat turns: accept a message, claim the turn, run the agent, stream events, finish atomically.

A turn is owned through a lease on its session (`activeTurn {turnId, attempt, leaseUntil}`). Every write a turn makes
is fenced on that lease and on the demo generation, so a stale attempt (crashed instance, reset demo) can never land.
History is rebuilt from Firestore on every turn, so any instance can serve any turn.
"""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.sessions import InMemorySessionService
from google.cloud import firestore
from google.genai import types

from . import agent as agentlib, db, quota
from .config import settings
from .errors import ApiError, conflict, not_found
from .fence import turn_fence
from .ids import new_id
from .redact import StreamScrubber, scrub, scrub_value

APP = "nightlight"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _lease() -> datetime:
    return _utcnow() + timedelta(seconds=settings.turn_lease_seconds)


def _live(until) -> bool:
    return bool(until) and until > _utcnow()


def _ready_user(tx, uid: str) -> dict:
    snap = db.user(uid).get(transaction=tx)
    if not snap.exists:
        raise not_found()
    user = snap.to_dict()
    if user.get("demo", {}).get("state") != "ready":
        raise conflict("resetting", retryAfter=5)
    return user


def turn_index(uid: str, turn_id: str):
    return db.user(uid).collection("turnIndex").document(turn_id)


# ------------------------------------------------------------------ sessions and messages

def create_session(uid: str) -> dict:
    session_id = new_id("sess")

    @firestore.transactional
    def run(tx):
        user = _ready_user(tx, uid)
        tx.set(db.session(uid, session_id), {"createdAt": firestore.SERVER_TIMESTAMP, "title": "New chat",
                                             "nextSeq": 1, "activeTurn": None, "lastTurnId": None,
                                             "demoGeneration": user["demoGeneration"]})

    db.run_transaction(run)
    return {"sessionId": session_id}


def accept_message(uid: str, session_id: str, text: str, client_request_id: str) -> str:
    """Store the user's message and its queued turn, once per clientRequestId. Returns the turn id."""
    turn_id = f"turn_{client_request_id}"
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    clean, _ = scrub(text)
    now = _utcnow()

    @firestore.transactional
    def run(tx):
        user = _ready_user(tx, uid)
        s_snap = db.session(uid, session_id).get(transaction=tx)
        t_ref = db.turns(uid, session_id).document(turn_id)
        t_snap = t_ref.get(transaction=tx)
        q_ref = quota.turn_quota_ref(uid, now)
        q_snap = q_ref.get(transaction=tx)
        if not s_snap.exists:
            raise not_found()
        session = s_snap.to_dict()
        if session.get("demoGeneration") != user["demoGeneration"]:
            raise conflict("stale")
        if t_snap.exists:
            if t_snap.to_dict().get("textSha256") != text_hash:
                raise conflict("request_mismatch", turnId=turn_id)
            return  # a retry finds the existing turn and is not counted again
        count = quota.check_turn_quota(q_snap, now)  # only new, valid messages count toward the hourly limit
        seq = session["nextSeq"]
        msg_id = new_id("msg")
        tx.set(db.messages(uid, session_id).document(msg_id), {
            "role": "user", "text": clean, "seq": seq, "turnId": turn_id, "attempt": 0,
            "demoGeneration": user["demoGeneration"], "createdAt": firestore.SERVER_TIMESTAMP})
        tx.set(t_ref, {"kind": "user", "status": "queued", "attempt": 0, "demoGeneration": user["demoGeneration"],
                       "clientRequestId": client_request_id, "textSha256": text_hash, "userMessageId": msg_id,
                       "input": clean, "createdAt": firestore.SERVER_TIMESTAMP})
        tx.set(turn_index(uid, turn_id), {"sessionId": session_id, "demoGeneration": user["demoGeneration"]})
        title = clean[:40] + ("…" if len(clean) > 40 else "") if seq == 1 else session.get("title")
        tx.update(db.session(uid, session_id), {"nextSeq": seq + 1, "lastTurnId": turn_id, "title": title})
        tx.set(q_ref, {"count": count})

    db.run_transaction(run)
    return turn_id


# ------------------------------------------------------------------ claiming

@dataclass
class Claim:
    mode: str            # "run" | "replay" | "failed"
    session_id: str
    turn_id: str
    turn: dict
    attempt: int
    generation: int


def claim(uid: str, turn_id: str) -> Claim:
    idx = turn_index(uid, turn_id).get()
    if not idx.exists:
        raise not_found()
    session_id = idx.to_dict()["sessionId"]

    @firestore.transactional
    def run(tx):
        user = _ready_user(tx, uid)
        s_ref, t_ref = db.session(uid, session_id), db.turns(uid, session_id).document(turn_id)
        s_snap, t_snap = s_ref.get(transaction=tx), t_ref.get(transaction=tx)
        if not s_snap.exists or not t_snap.exists:
            raise not_found()
        session, turn = s_snap.to_dict(), t_snap.to_dict()
        generation = user["demoGeneration"]
        if turn.get("demoGeneration") != generation:
            raise conflict("stale", turnId=turn_id)
        if turn["status"] == "done":
            return Claim("replay", session_id, turn_id, turn, turn["attempt"], generation)
        if turn["status"] == "failed":
            return Claim("failed", session_id, turn_id, turn, turn["attempt"], generation)
        active = session.get("activeTurn")
        if active and _live(active.get("leaseUntil")):
            wait = max(int((active["leaseUntil"] - _utcnow()).total_seconds()), 1)
            raise conflict("turn_in_progress", turnId=active["turnId"], retryAfter=wait)
        attempt = turn.get("attempt", 0) + 1
        lease = _lease()
        tx.update(t_ref, {"status": "running", "attempt": attempt, "leaseUntil": lease,
                          "startedAt": firestore.SERVER_TIMESTAMP})
        tx.update(s_ref, {"activeTurn": {"turnId": turn_id, "attempt": attempt, "leaseUntil": lease}})
        return Claim("run", session_id, turn_id, {**turn, "attempt": attempt}, attempt, generation)

    return db.run_transaction(run)


def _fenced(uid: str, c: Claim, work) -> None:
    fence = turn_fence(uid, c.session_id, c.turn_id, c.attempt, c.generation)

    @firestore.transactional
    def run(tx):
        fence(tx)
        s_snap = db.session(uid, c.session_id).get(transaction=tx)
        work(tx, s_snap.to_dict())

    db.run_transaction(run)


def renew(uid: str, c: Claim) -> None:
    lease = _lease()

    def work(tx, session):
        tx.update(db.session(uid, c.session_id), {"activeTurn.leaseUntil": lease})
        tx.update(db.turns(uid, c.session_id).document(c.turn_id), {"leaseUntil": lease})

    _fenced(uid, c, work)


def finish(uid: str, c: Claim, *, text: str | None, metrics: dict, tool_calls: list, action_ids: list,
           error: dict | None = None) -> str | None:
    """Final message + terminal status + lease release, in one fenced transaction."""
    msg_id = new_id("msg") if text is not None else None

    def work(tx, session):
        t_ref = db.turns(uid, c.session_id).document(c.turn_id)
        update = {"status": "failed" if error else "done", "metrics": metrics, "leaseUntil": None,
                  "finishedAt": firestore.SERVER_TIMESTAMP}
        session_update = {"activeTurn": None, "lastTurnId": c.turn_id}
        if text is not None:
            seq = session["nextSeq"]
            tx.set(db.messages(uid, c.session_id).document(msg_id), {
                "role": "assistant", "text": text, "seq": seq, "turnId": c.turn_id, "attempt": c.attempt,
                "toolCalls": tool_calls, "actionIds": action_ids, "demoGeneration": c.generation,
                "createdAt": firestore.SERVER_TIMESTAMP})
            update["finalMessageId"] = msg_id
            session_update["nextSeq"] = seq + 1
        if error:
            update["error"] = error
        tx.update(t_ref, update)
        tx.update(db.session(uid, c.session_id), session_update)

    _fenced(uid, c, work)
    return msg_id


# ------------------------------------------------------------------ history

def history(uid: str, c: Claim) -> list[types.Content]:
    """Recent messages as model contents, oldest first, excluding everything from the current turn."""
    msgs = [m.to_dict() for m in db.messages(uid, c.session_id).get()]
    msgs = [m for m in msgs if m.get("turnId") != c.turn_id]
    msgs.sort(key=lambda m: m["seq"])
    picked, chars = [], 0
    for m in reversed(msgs[-settings.history_messages:]):
        chars += len(m.get("text", ""))
        if chars > settings.history_chars:
            break
        picked.append(m)
    contents: list[types.Content] = []
    for m in reversed(picked):
        role = "model" if m["role"] == "assistant" else "user"
        text = m["text"] if m["role"] != "system" else f"[Update] {m['text']}"
        if contents and contents[-1].role == role:  # keep roles alternating
            contents[-1].parts.append(types.Part(text=text))
        else:
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
    return contents


# ------------------------------------------------------------------ running a turn

def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


async def stream(uid: str, c: Claim, ip: str, model=None):
    """Async generator of SSE strings for a claimed turn. Always ends with `done` or `error`.

    The agent runs as a producer task; this loop forwards its events, sends a `: ping` comment every 15 s of
    silence, and a separate timer renews the lease on a clock (not on model events). Losing the lease or the
    generation stops the producer before any further model call.
    """
    t0 = time.monotonic()
    yield sse({"type": "turn_start", "turnId": c.turn_id, "attempt": c.attempt,
               "messageId": c.turn.get("userMessageId"), "at": _iso(_utcnow()),
               **({"replay": True} if c.mode == "replay" else {})})
    if c.mode == "replay":
        msg = await asyncio.to_thread(lambda: db.messages(uid, c.session_id).document(c.turn["finalMessageId"]).get())
        yield sse({"type": "text", "delta": msg.to_dict()["text"]})
        yield sse({"type": "done", "turnId": c.turn_id, "metrics": c.turn.get("metrics", {})})
        return
    if c.mode == "failed":
        err = c.turn.get("error") or {"code": "internal", "message": "This answer failed."}
        yield sse({"type": "error", "code": err.get("code"), "message": err.get("message"), "retryable": False})
        return

    ctx = agentlib.TurnContext(uid=uid, session_id=c.session_id, turn_id=c.turn_id, attempt=c.attempt,
                               generation=c.generation, ip=ip)
    queue: asyncio.Queue = asyncio.Queue()
    lost = asyncio.Event()
    scrubber = StreamScrubber()
    final_raw, tool_calls, first_text_ms = None, [], None

    async def produce():
        try:
            continuation = c.turn["kind"] == "continuation"
            agent = agentlib.build(ctx, continuation=continuation, model=model)
            sessions = InMemorySessionService()
            runner = Runner(app_name=APP, agent=agent, session_service=sessions)
            adk_session = await sessions.create_session(app_name=APP, user_id=uid, state={"uid": uid})
            for content in await asyncio.to_thread(history, uid, c):
                await sessions.append_event(adk_session, Event(
                    author="user" if content.role == "user" else agent.name, content=content))
            prompt = c.turn["input"] if not continuation else f"[Update] {c.turn['input']}"
            message = types.Content(role="user", parts=[types.Part(text=prompt)])
            async for ev in runner.run_async(user_id=uid, session_id=adk_session.id, new_message=message,
                                             run_config=RunConfig(streaming_mode=StreamingMode.SSE,
                                                                  max_llm_calls=settings.model_calls_per_turn)):
                await queue.put(("event", ev))
            await queue.put(("end", None))
        except BaseException as e:  # noqa: B036 - forwarded to the consumer, which decides
            await queue.put(("error", e))

    async def keep_lease():
        while True:
            await asyncio.sleep(settings.turn_lease_seconds / 3)
            try:
                await asyncio.to_thread(renew, uid, c)
            except ApiError:
                lost.set()
                return

    producer = asyncio.create_task(produce())
    renewer = asyncio.create_task(keep_lease())
    try:
        while True:
            if lost.is_set():
                raise ApiError(409, "stale")
            try:
                kind, item = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if kind == "error":
                raise item
            if kind == "end":
                break
            ev = item
            for part in (ev.content.parts if ev.content else []) or []:
                if part.thought:
                    continue
                if part.text:
                    if ev.partial:
                        piece = scrubber.push(part.text)
                        if piece:
                            if first_text_ms is None:
                                first_text_ms = int((time.monotonic() - t0) * 1000)
                            yield sse({"type": "text", "delta": piece})
                    else:
                        final_raw = (final_raw or "") + part.text
                if part.function_call and not ev.partial:
                    args, _ = scrub_value(dict(part.function_call.args or {}))
                    tool_calls.append({"name": part.function_call.name, "args": args})
                    yield sse({"type": "tool_call", "name": part.function_call.name, "args": args})
                if part.function_response:
                    resp = dict(part.function_response.response or {})
                    yield sse({"type": "tool_result", "name": part.function_response.name,
                               "summary": _summary(resp), "redacted": ctx.redacted})
                    if part.function_response.name == "rotate_logs" and resp.get("status") == "pending":
                        yield sse({"type": "approval_request", "actionId": resp.get("actionId")})
        piece, text = scrubber.finish(final_raw if final_raw is not None else None)
        if not text.strip():
            text, piece = agentlib.FALLBACK, agentlib.FALLBACK
        if piece:
            if first_text_ms is None:
                first_text_ms = int((time.monotonic() - t0) * 1000)
            yield sse({"type": "text", "delta": piece})
        # `text` is exactly what the browser has received; it is what we store and replay.
        metrics = {**ctx.metrics, "latencyMs": int((time.monotonic() - t0) * 1000),
                   "firstTextMs": first_text_ms, "costUsd": round(ctx.metrics["costUsd"], 6)}
        await asyncio.to_thread(finish, uid, c, text=text, metrics=metrics, tool_calls=tool_calls,
                                action_ids=[a["id"] for a in ctx.actions])
        yield sse({"type": "done", "turnId": c.turn_id, "metrics": metrics})
    except ApiError as e:
        if e.code == "stale":
            yield sse({"type": "error", "code": "stale", "message": "The demo was reset. Start a new question.",
                       "retryable": False})
            return
        err = {"code": e.code, "message": _error_message(e.code)}
        try:
            await asyncio.to_thread(finish, uid, c, text=None, metrics=ctx.metrics, tool_calls=tool_calls,
                                    action_ids=[], error=err)
        except ApiError:
            pass  # superseded meanwhile: nothing to record
        yield sse({"type": "error", **err, "retryable": e.status == 429})
    except Exception:
        err = {"code": "internal", "message": "Something went wrong on our side. Please try again."}
        try:
            await asyncio.to_thread(finish, uid, c, text=None, metrics=ctx.metrics, tool_calls=tool_calls,
                                    action_ids=[], error=err)
        except ApiError:
            pass
        yield sse({"type": "error", **err, "retryable": True})
    finally:
        for task in (producer, renewer):
            task.cancel()


def _summary(resp: dict) -> str:
    if "devices" in resp:
        return f"{len(resp['devices'])} devices"
    if "events" in resp:
        return f"{len(resp['events'])} recent events"
    if "status" in resp:
        return f"status {resp['status']}"
    if "error" in resp:
        return str(resp["error"])
    if "vitals" in resp:
        return f"disk {(resp.get('vitals') or {}).get('diskPct')}%"
    return "ok"


def _error_message(code: str) -> str:
    return {
        "quota_uid": "You've asked a lot this hour. Please try again a bit later.",
        "quota_ip": "This network has asked a lot this hour. Please try again a bit later.",
        "quota_global": "Nightlight has reached today's limit. Please try again later.",
        "kill_switch": "Nightlight's assistant is paused right now.",
        "context_limit": "This conversation got too long. Please start a new chat.",
        "too_many_steps": "That needed too many steps. Please ask about one thing at a time.",
        "resetting": "The demo is resetting. Please wait a moment.",
    }.get(code, "Something went wrong. Please try again.")
