"""Chat turns: accept a message, claim the turn, run the agent, stream events, finish atomically.

A turn is owned through a lease on its session (`activeTurn {turnId, attempt, leaseUntil}`). Every write a turn makes
is fenced on that lease and on the demo generation, so a stale attempt (crashed instance, reset demo) can never land.
History is rebuilt from Firestore on every turn, so any instance can serve any turn.
"""

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.sessions import InMemorySessionService
from google.cloud import firestore
from google.genai import types

from . import agent as agentlib, db, memory, quota
from .config import settings
from .errors import ApiError, conflict, not_found
from .fence import turn_fence
from .ids import new_id
from .redact import scrub, scrub_value

APP = "nightlight"
ACTION_TOOLS = {"rotate_logs", "clear_images", "backup_world", "restart_server", "restart_app", "update_server",
                "update_app", "restart_container",
                "restart_service",
                "clean_up", "remove_device", "start_investigation", "propose_command", "update_helper", "use_runbook",
                "allow_log_reading"}


# Check-and-return for the one answer failure the harness can see without guessing at meaning: a final answer with no
# words, or one the output limit cut off. The model is asked once more (a counted model call, no new checks); if that
# fails too, the turn says so plainly.
SHORTER = {"empty": "[Nightlight] Your last reply had no words for the person. Answer them now, briefly, from what "
                    "you already found.",
           "cut": "[Nightlight] Your last reply was cut off by the length limit. Answer again in fewer words, from "
                  "what you already found."}
NO_ANSWER = "I couldn't put an answer together this time. Please ask again."
# A model call that stays silent past its gap (agent.TurnContext.call_gap_seconds) is cancelled and asked once more;
# a second silent call ends the turn with SLOW: honest failure, never a quietly thinner answer.
CARRY_ON = "[Nightlight] Your last reply took too long and was cancelled. Carry on from where you were."
SLOW = "Gemini is slow right now; nothing was changed. Please ask again."
SLOW_UNSURE = "Gemini is slow right now, so I couldn't finish this answer. Please ask again."


def _without_text(ev):
    """A copy of a cut-off response without its visible words (function calls and thoughts kept), or None when
    nothing else is left."""
    parts = [p for p in (ev.content.parts if ev.content else None) or [] if not (p.text and not p.thought)]
    if not any(p.function_call for p in parts):
        return None
    out = ev.model_copy(deep=True)
    out.content.parts = parts
    return out


def unanswered(ev) -> str | None:
    """Why the final model response of a run is not an answer ("empty" or "cut"), or None when it is one."""
    if ev is None:
        return "empty"
    parts = (ev.content.parts if ev.content else None) or []
    if any(p.function_call for p in parts):
        return None
    if ev.finish_reason == types.FinishReason.MAX_TOKENS:
        return "cut"
    return None if any(p.text and p.text.strip() and not p.thought for p in parts) else "empty"


QUICK_INSTEAD = "Investigate is busy right now, so here is a quick look instead.\n\n"


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


def accept_message(uid: str, session_id: str, text: str, client_request_id: str, mode: str = "quick") -> str:
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
            "demoGeneration": user["demoGeneration"], "createdAt": firestore.SERVER_TIMESTAMP,
            "expiresAt": _keep_until()})
        tx.set(t_ref, {"kind": "user", "status": "queued", "attempt": 0, "demoGeneration": user["demoGeneration"],
                       "clientRequestId": client_request_id, "textSha256": text_hash, "userMessageId": msg_id,
                       "mode": mode,
                       "input": clean, "createdAt": firestore.SERVER_TIMESTAMP})
        tx.set(turn_index(uid, turn_id), {"sessionId": session_id, "demoGeneration": user["demoGeneration"]})
        title = clean[:40] + ("…" if len(clean) > 40 else "") if seq == 1 else session.get("title")
        tx.update(db.session(uid, session_id), {"nextSeq": seq + 1, "lastTurnId": turn_id, "title": title})
        tx.update(db.user(uid), {"lastChatAt": firestore.SERVER_TIMESTAMP})  # helpers check for work faster now
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
                "toolCalls": [_stored_step(t, error) for t in tool_calls],
                "actionIds": action_ids, "demoGeneration": c.generation, "mode": c.turn.get("mode", "quick"),
                "metrics": metrics,  # the receipt under the answer (steps, time, model, cost) survives a reload
                **({"error": error} if error else {}),
                "createdAt": firestore.SERVER_TIMESTAMP, "expiresAt": _keep_until()})
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
    msgs = [m for m in msgs if m.get("turnId") != c.turn_id and m.get("text")]  # a wordless record isn't history
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


async def _recall(uid: str, ep: int) -> list[str]:
    """Facts remembered about this person that relate to their message; [] if memory is off, slow or failing."""
    if not memory.enabled():
        return []
    try:
        if (facts := memory.cached(uid, ep)) is not None:
            return facts
        return await asyncio.wait_for(asyncio.to_thread(memory.load, uid, ep), timeout=settings.memory_recall_seconds)
    except Exception:  # a slow or failing memory never holds up or breaks the answer
        return []


async def stream(uid: str, c: Claim, ip: str, model=None):
    """Async generator of SSE strings for a claimed turn. Always ends with `done` or `error`.

    The agent runs as a producer task; this loop forwards its events, sends a `: ping` comment every 15 s of
    silence, and a separate timer renews the lease on a clock (not on model events). Losing the lease or the
    generation stops the producer before any further model call.
    """
    t0 = time.monotonic()
    try:
        yield sse({"type": "turn_start", "turnId": c.turn_id, "attempt": c.attempt,
                   "messageId": c.turn.get("userMessageId"), "at": _iso(_utcnow()),
                   "mode": c.turn.get("mode", "quick"), "budgetSeconds": _budget(c),
                   **({"replay": True} if c.mode == "replay" else {})})
    except (asyncio.CancelledError, GeneratorExit):
        if c.mode == "run":  # claimed but stopped before anything ran (replayed or failed turns are already over)
            _stop(uid, c, text=None, tool_calls=[], action_ids=[])
        raise
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
                               generation=c.generation, ip=ip, deep=c.turn.get("mode") == "investigate")
    queue: asyncio.Queue = asyncio.Queue()
    lost = asyncio.Event()
    # Text is released only when a model call has finished, so it is always scrubbed as a whole: a secret can't
    # leak through a partly-seen value. `shown` is exactly what the browser has; it is what we store and replay.
    raw, shown, tool_calls, first_text_ms = "", "", [], None
    finishing = False  # set once a terminal write has started; a stop after that changes nothing
    no_answer = False  # the model was asked twice and gave no answer
    slow = False  # a model call stayed silent twice: the turn ends with a plain error
    last_sent = time.monotonic()

    async def produce():
        try:
            # Event turns follow their policy (conversation.py): narrate only, or continue with tools.
            kind = c.turn["kind"]
            continuation = kind == "continuation" or (kind == "event" and c.turn.get("policy") != "continue")
            if not continuation:
                # One memory lookup per turn, in parallel with the fleet summary; both go into the instruction and
                # so through the same exact token bound as everything else.
                if memory.enabled():
                    try:
                        ctx.memory_epoch = await asyncio.to_thread(memory.epoch, uid)
                    except Exception:  # memory never breaks a turn
                        pass
                ctx.fleet, ctx.memories = await asyncio.gather(
                    asyncio.to_thread(agentlib.fleet_summary, uid, c.generation), _recall(uid, ctx.memory_epoch))
            loop = asyncio.get_running_loop()
            # Each extra attempt happens at most once per turn, whichever run it falls in: the answer-only retry
            # (SHORTER), the retry after a silent call (CARRY_ON), and Quick standing in for a busy Investigate.
            used = {"answer": False, "slow": False}

            async def run_once() -> bool:
                """One agent run over the question; False when the turn must end as model_slow."""
                agent = agentlib.build(ctx, continuation=continuation, model=model)
                sessions = InMemorySessionService()
                runner = Runner(app_name=APP, agent=agent, session_service=sessions)
                adk_session = await sessions.create_session(app_name=APP, user_id=uid, state={"uid": uid})
                for content in await asyncio.to_thread(history, uid, c):
                    await sessions.append_event(adk_session, Event(
                        author="user" if content.role == "user" else agent.name, content=content))
                prompt = c.turn["input"] if kind == "user" else \
                    f"[Event: {c.turn.get('event', 'update')}] {c.turn['input']}"
                message = types.Content(role="user", parts=[types.Part(text=prompt)])
                answer_only = False  # this run's current ADK run is the answer-only retry
                while True:
                    run = runner.run_async(user_id=uid, session_id=adk_session.id, new_message=message,
                                           run_config=RunConfig(streaming_mode=StreamingMode.SSE,
                                                                max_llm_calls=ctx.max_calls))
                    # The silence timer runs only while a model call is in flight (callbacks switch it), never
                    # while a tool works. When it fires, this task is cancelled inside the call and `watch` reports
                    # it expired. A timeout is never "busy": it never brings in the Quick stand-in.
                    watch = asyncio.timeout(None)
                    ctx.watch_call = lambda active: watch.reschedule(
                        loop.time() + ctx.call_gap_seconds if active else None)
                    try:
                        async with watch:
                            await _forward(run, answer_only)
                    except TimeoutError:
                        if not watch.expired():
                            raise
                        # Counted and reserved like any call; its reservation is kept in full (never reconciled),
                        # since Gemini may still bill a call we stopped waiting for.
                        if ctx.reservations:
                            ctx.reservations.pop()
                        ctx.metrics["slowCalls"] = ctx.metrics.get("slowCalls", 0) + 1
                        # One retry per turn, only inside the normal call limit, and not for the answer-only
                        # retry (already the one call past it). Otherwise the turn ends saying so.
                        if used["slow"] or ctx.retry_from is not None or ctx.metrics["modelCalls"] >= ctx.max_calls:
                            return False
                        used["slow"] = True
                        message = types.Content(role="user", parts=[types.Part(text=CARRY_ON)])
                        continue
                    finally:
                        ctx.watch_call = lambda active: None
                    why = unanswered(last_final[0])
                    if why is None:
                        return True
                    if answer_only or used["answer"]:
                        await queue.put(("no_answer", None))
                        return True
                    answer_only = used["answer"] = True
                    ctx.retry_from = ctx.metrics["modelCalls"]  # exactly one more counted call, with no tools
                    message = types.Content(role="user", parts=[types.Part(text=SHORTER[why])])

            try:
                finished = await run_once()
            except Exception as e:
                # Investigate's model is out of capacity before anything was said or done: the same question gets a
                # Quick look instead, and the answer says so first. Busy later (after steps ran) fails as before.
                if not (ctx.deep and not continuation and forwarded[0] == 0 and agentlib.model_busy(e)):
                    raise
                ctx.deep = False
                ctx.retry_from = None
                ctx.reservations.clear()  # the refused call's reservation stays spent (its usage is unknown)
                await queue.put(("notice", QUICK_INSTEAD))
                finished = await run_once()
            if not finished:
                await queue.put(("slow", None))
                return
            await queue.put(("end", None))
        except BaseException as e:  # noqa: B036 - forwarded to the consumer, which decides
            await queue.put(("error", e))

    last_final = [None]  # the latest run's final model response
    forwarded = [0]  # model events passed on: a busy model before any is the only time Quick stands in

    async def _forward(run, answer_only):
        """Forward one ADK run's events to the consumer, keeping its final model response in last_final."""
        last_final[0] = None
        try:
            async for ev in run:
                if not ev.partial and not ev.get_function_responses():
                    last_final[0] = ev
                    calls = any(p.function_call for p in (ev.content.parts if ev.content else None) or [])
                    if answer_only and calls:
                        # The answer-only retry asked for a tool: not an answer. ADK runs a call only
                        # after yielding it, so stopping here means nothing runs (before_tool refuses too).
                        last_final[0] = None
                        break
                    if ev.finish_reason == types.FinishReason.MAX_TOKENS:
                        ev = _without_text(ev)  # cut-off words are never shown; its tool calls still run
                        if ev is None:
                            continue
                if not ev.partial and ev.author != "user" and any(
                        (p.text and p.text.strip() and not p.thought) or p.function_call or p.function_response
                        for p in (ev.content.parts if ev.content else None) or []):
                    forwarded[0] += 1  # the model said something the person saw, or did something
                await queue.put(("event", ev))
        finally:
            await run.aclose()

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
    def out(event: dict) -> str:
        nonlocal last_sent
        last_sent = time.monotonic()
        return sse(event)

    try:
        while True:
            if lost.is_set():
                raise ApiError(409, "stale")
            try:
                # Ping after 15 s without bytes on the wire, whatever the model is doing.
                wait = max(15 - (time.monotonic() - last_sent), 0.05)
                kind, item = await asyncio.wait_for(queue.get(), timeout=wait)
            except asyncio.TimeoutError:
                last_sent = time.monotonic()
                yield ": ping\n\n"
                continue
            if kind == "error":
                raise item
            if kind == "end":
                break
            if kind == "no_answer":
                no_answer = True
                continue
            if kind == "slow":
                slow = True
                break
            if kind == "notice":  # our own words, said before anything else (nothing has been shown yet)
                raw = shown = item
                first_text_ms = first_text_ms or int((time.monotonic() - t0) * 1000)
                yield out({"type": "text", "delta": item})
                continue
            ev = item
            parts = (ev.content.parts if ev.content else None) or []
            if not ev.partial:
                # The whole visible text of a finished response is added and scrubbed at once, never part by part.
                visible = "".join(p.text for p in parts if p.text and not p.thought)
                if visible:
                    if raw.strip() and not raw.endswith(("\n", " ")) and not visible.startswith(("\n", " ")):
                        raw += "\n\n"  # a new model call's words start a new paragraph, not mid-sentence
                    raw += visible
                    clean = scrub(raw)[0]
                    if clean.strip() and clean.startswith(shown):  # hold whitespace until there's substance
                        piece, shown = clean[len(shown):], clean
                        if first_text_ms is None:
                            first_text_ms = int((time.monotonic() - t0) * 1000)
                        yield out({"type": "text", "delta": piece})
            for part in parts:
                if part.thought:
                    continue
                if part.function_call and not ev.partial:
                    args, _ = scrub_value(dict(part.function_call.args or {}))
                    # Where the step falls in the text (to rebuild reason → act → result after a reload) and when it began.
                    call_id = {"callId": part.function_call.id} if part.function_call.id else {}
                    tool_calls.append({"name": part.function_call.name, "args": args, "textOffset": _u16(shown),
                                       "_t": time.monotonic(), **call_id})
                    yield out({"type": "tool_call", "name": part.function_call.name, "args": args, **call_id})
                if part.function_response:
                    resp = dict(part.function_response.response or {})
                    line, details = _commentary(part.function_response.name, resp)
                    # The stored message keeps each step's outcome too, so a reloaded chat shows the same work log.
                    # Paired by the call's id: two parallel calls of one tool (several devices at once) stay apart.
                    rid = part.function_response.id
                    step = next((t for t in tool_calls if "summary" not in t and (
                        t.get("callId") == rid if rid else t["name"] == part.function_response.name)), None)
                    ok, ms = _ok(resp), None
                    if step is not None:
                        step["summary"], step["ok"] = line, ok
                        ms = step["ms"] = int((time.monotonic() - step.pop("_t")) * 1000)
                        if details:
                            step["details"] = details[:DETAILS_CHARS]
                    yield out({"type": "tool_result", "name": part.function_response.name, "summary": line,
                               **({"callId": rid} if rid else {}),
                               "details": details, "ok": ok, "ms": ms, "redacted": ctx.redacted})
                    if part.function_response.name in ACTION_TOOLS and (resp.get("status") == "pending"
                                                                        or resp.get("awaitingTap")):
                        ids = resp.get("actionIds") or [resp.get("actionId")]  # a runbook can put up several
                        shown_ids = {i for t in tool_calls for i in (t.get("actionIds") or [t.get("actionId")])}
                        ids = [i for i in ids if i not in shown_ids]  # a card sits after the first step that got it
                        if step is not None and ids:
                            step["actionId"] = ids[0]  # the card sits right after its step
                            if len(ids) > 1:
                                step["actionIds"] = ids
                        for aid in ids:
                            yield out({"type": "approval_request", "actionId": aid})
                    if part.function_response.name in DEVICE_READS and resp.get("status") == "asked":
                        # The device answers later; the browser opens this follow-up turn once it exists.
                        yield out({"type": "followup_pending", "turnId": resp.get("followUpTurnId")})
        if slow:
            # Gemini went silent twice: say so plainly after whatever was already shown. "Nothing was changed" is
            # said only when provable: a person's question whose turn proposed nothing. A continuation narrates a
            # job that may already have run, so it (and any turn with actions) makes no claim about changes.
            provable = c.turn.get("kind") == "user" and not ctx.actions
            err = {"code": "model_slow", "message": SLOW if provable else SLOW_UNSURE}
            metrics = {**ctx.metrics, "latencyMs": int((time.monotonic() - t0) * 1000),
                       "firstTextMs": first_text_ms, "costUsd": round(ctx.metrics["costUsd"], 6),
                       "budgetSeconds": ctx.turn_seconds}
            finishing = True
            # Stored even with no prose (text ""), so the steps, cards, receipt and error survive a reload.
            await asyncio.to_thread(finish, uid, c, text=shown if shown.strip() else "", metrics=metrics,
                                    tool_calls=tool_calls, action_ids=[a["id"] for a in ctx.actions], error=err)
            yield sse({"type": "error", **err, "retryable": True})
            return
        if no_answer or not shown.strip():
            # Asked twice and still no answer: say so plainly, after whatever was already shown.
            piece = ("\n\n" if shown.strip() else "") + NO_ANSWER
            shown = (shown if shown.strip() else "") + piece
            first_text_ms = first_text_ms or int((time.monotonic() - t0) * 1000)
            yield out({"type": "text", "delta": piece})
        text = shown  # exactly what the browser received; stored and replayed as-is
        metrics = {**ctx.metrics, "latencyMs": int((time.monotonic() - t0) * 1000),
                   "firstTextMs": first_text_ms, "costUsd": round(ctx.metrics["costUsd"], 6),
                   "budgetSeconds": ctx.turn_seconds}
        finishing = True
        await asyncio.to_thread(finish, uid, c, text=text, metrics=metrics, tool_calls=tool_calls,
                                action_ids=[a["id"] for a in ctx.actions])
        yield sse({"type": "done", "turnId": c.turn_id, "metrics": metrics})
    except (asyncio.CancelledError, GeneratorExit):
        # The browser stopped reading (Stop, or the page closed): the turn stops here, like Esc in a terminal. What
        # was said and done so far is kept, and the chat is free for the next question at once (no lingering lease).
        # Synchronous on purpose: nothing can be awaited in a cancelled task.
        if not finishing:
            finishing = True
            _stop(uid, c, text=shown if shown.strip() else None, tool_calls=tool_calls,
                  action_ids=[a["id"] for a in ctx.actions], metrics=ctx.metrics)
        raise
    except ApiError as e:
        if e.code == "stale":
            yield sse({"type": "error", "code": "stale", "message": "The demo was reset. Start a new question.",
                       "retryable": False})
            return
        err = {"code": e.code, "message": _error_message(e.code)}
        finishing = True
        try:
            await asyncio.to_thread(finish, uid, c, text=shown if shown.strip() else None, metrics=ctx.metrics,
                                    tool_calls=tool_calls, action_ids=[a["id"] for a in ctx.actions], error=err)
        except ApiError:
            pass  # superseded meanwhile: nothing to record
        yield sse({"type": "error", **err, "retryable": e.status == 429})
    except Exception as e:
        err = {"code": "internal", "message": "Something went wrong on our side. Please try again."}
        if agentlib.model_busy(e):  # the model itself is out of capacity: say so plainly, nothing technical
            err = {"code": "busy", "message": "Nightlight is busy right now. Try again in a minute"
                   + (", or ask in Quick mode." if ctx.deep else ".")}
        finishing = True
        try:
            await asyncio.to_thread(finish, uid, c, text=shown if shown.strip() else None, metrics=ctx.metrics,
                                    tool_calls=tool_calls, action_ids=[a["id"] for a in ctx.actions], error=err)
        except ApiError:
            pass
        yield sse({"type": "error", **err, "retryable": True})
    finally:
        for task in (producer, renewer):
            task.cancel()


def _budget(c: Claim) -> int:
    """The turn's time budget in seconds, for the "Working… 45 s of 4 min" line (same as TurnContext.turn_seconds)."""
    return settings.deep_turn_seconds if c.turn.get("mode") == "investigate" else settings.quick_turn_seconds


CHAT_KEEP_DAYS = 30  # conversations are shown again when you come back, then expire (Firestore TTL on expiresAt)


def _keep_until():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc) + timedelta(days=CHAT_KEEP_DAYS)


DEVICE_READS = {"look_into", "inspect", "run_playbook", "run_command", "check_space"}  # the device answers; slow ones finish in a follow-up
DETAILS_CHARS = 2000


# Codes a step can come back with, in the owner's words. The chat line never shows a raw code; the code itself stays
# in the step's details for whoever wants it.
REASON_WORDS = {
    "strict_device": "This device only allows changes made on the device itself",
    "update_helper": "The Nightlight helper on this device needs updating before this can be changed from the app",
    "update_helper_first": "The Nightlight helper on this device needs updating first",
    "helper_too_old": "The Nightlight helper on this device is too old for this; it needs updating first",
    "update_by_hand": "The Nightlight helper on this device is too old to update itself; run the install line on it "
                      "once",
    "updates_off": "Updates from the app are switched off for this device",
    "not_allowed_on_device": "You haven't allowed that on this device (see the device's Settings)",
    "not_applicable": "That doesn't apply to this device",
    "not_found": "Nightlight couldn't find that device",
    "bad_target": "Nightlight couldn't tell which app or item that was meant for",
    "no_such_target": "The device doesn't report anything by that name",
    "no_such_container": "The device doesn't report an app by that name",
    "unknown_target": "The device doesn't report anything by that name",
    "unknown_service": "The device doesn't report anything by that name",
    "not_failed": "That service isn't reported as stopped, so there is nothing to restart",
    "not_unhealthy": "That app isn't reported as unhealthy, so a restart isn't needed",
    "already_running": "It is already running",
    "needs_restart": "It is running but unhealthy, so it needs a restart rather than a start",
    "device_not_reporting": "The device isn't reporting right now",
    "already_allowed": "That is already allowed",
    "too_many_targets": "This device already allows that for as many items as it can",
    "up_to_date": "The Nightlight helper there is already up to date",
    "no_release": "There is no new helper version on offer",
    "not_the_release_on_offer": "That isn't the helper version on offer right now",
    "nothing_to_free": "Nothing to free there: it was measured as almost empty a short while ago",
    "no_passkey": "A passkey needs to be set up first (open the device, then Settings, then Expert sessions)",
    "needs_passkey": "This needs your passkey",
    "expired": "That card expired",
    "stale": "Things changed since, so that card is out of date",
    "unknown_kind": "Nightlight doesn't know that kind of item",
    "looks_secret": "It looked like a password, key or address, so it wasn't kept",
    "too_frequent": "That was asked too recently; try again in a little while",
    "research_limit": "Today's limit of web searches is reached",
}
STATUS_WORDS = {
    "done": "Finished", "failed": "It didn't work", "refused": "Not allowed", "stale": "Out of date: things changed",
    "denied": "You said not now", "approved": "Approved", "running": "Running now", "expired": "Expired",
    "active": "On", "off": "Off", "unknown": "Not known yet", "nothing_to_free": REASON_WORDS["nothing_to_free"],
}
_CODE = re.compile(r"^[a-z]+(?:_[a-z0-9]+)+$")


def _plain_reason(reason) -> tuple[str, str | None]:
    """(plain words, details): a known code becomes a sentence; an unknown code a general line with the code kept in
    the details; a reason already written in words stays as it is."""
    text = str(reason)
    if text in REASON_WORDS:
        return REASON_WORDS[text], f"Code: {text}"
    if _CODE.fullmatch(text):
        return "That step couldn't be done here", f"Code: {text}"
    if m := _CODE_IN_TEXT.search(text):  # words mixed with codes (e.g. a list of allowed job names): the words
        lead = text[:m.start()].rstrip(" :,(")  # up to the first code, the full text in the details
        return (f"{lead} (see the details)" if lead else "That step couldn't be done here"), text
    return text, None


_CODE_IN_TEXT = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")


def _commentary(name: str, resp: dict) -> tuple[str, str | None]:
    """One plain line about what a step found (shown live in the chat), plus optional details to expand. Built from
    the tool result, which is already scrubbed and bounded."""
    status, reason = resp.get("status"), resp.get("reason") or resp.get("error")
    if reason and status in (None, "error", "refused"):
        words, code = _plain_reason(reason)
        return f"Couldn't: {words}", code
    if status == "asked":
        return "Asked the device; it hasn't answered yet (I'll report back here when it does)", None
    if status in ("waiting", "safer_first"):
        job = resp.get("proposed") or {}
        if job.get("status") in ("done", "failed"):  # the safer step ran on its own: its outcome is the receipt
            return f"The safer step first ({_status_words(job['status']).lower()}): " \
                f"{job.get('result') or job.get('plan') or ''}", None
        lead = "A card for this was already waiting: " if status == "waiting" else "The safer step first: "
        return lead + (job.get("plan") or ""), None
    if name == "check_space" and status == "done" and "devices" in resp:
        rows = [f"{d.get('name')}: " + ", ".join(f"{u['what']} {u['sizeGb']} GB" for u in d.get("usedBy") or [])
                for d in resp["devices"] if d.get("usedBy")]
        return f"Measured the space on {len(rows)} device(s)", "\n".join(rows) or None
    if "devices" in resp:
        bad = [d.get("name") for d in resp["devices"] if d.get("status") not in ("ok", None)]
        return f"{len(resp['devices'])} devices" + (f"; needs a look: {', '.join(bad[:4])}" if bad else "; all fine"), None
    if "events" in resp:
        return f"Looked at {len(resp['events'])} recent events", None
    if "vitals" in resp:
        v = resp.get("vitals") or {}
        book = resp.get("notebook") or {}
        notes = len(book.get("device") or []) + sum(len(n) for n in (book.get("services") or {}).values())
        bits = [f"disk {v.get('diskPct')}%" if v.get("diskPct") is not None else None,
                f"memory {round(v['mem'])}%" if v.get("mem") is not None else None,
                f"{len(resp.get('findings') or [])} problem(s)",
                f"{notes} note(s) in its notebook" if notes else None,
                f"{len(resp['runbooks'])} saved fix(es)" if resp.get("runbooks") else None]
        return ", ".join(b for b in bits if b), None
    if name == "read_device_log" and "jobs" in resp:
        jobs = resp["jobs"]
        return f"Read what was done there: {len(jobs)} past task(s)", \
            "\n".join(f"{j.get('at')} {j.get('title')}: {j.get('summary')}" for j in jobs)[:DETAILS_CHARS] or None
    if name == "use_runbook" and resp.get("runbook"):
        cards = len(resp.get("actionIds") or [])
        return f"Saved fix \"{resp['runbook']}\": " + (f"{cards} step(s) waiting for your OK" if cards
                                                       else _status_words(resp.get("status")).lower()), None
    if name in ("run_playbook", "check_space") and resp.get("playbook"):
        text = str(resp["playbook"])
        lines = [ln[2:] for ln in text.splitlines() if ln.startswith("- ")]
        return (f"Checkup done: {len(lines)} finding(s)" if lines else "Checkup done: nothing stood out"), \
            text[:DETAILS_CHARS]
    if name in DEVICE_READS and status in ("done", "failed"):
        out = resp.get("output") or ""
        first = next((ln for ln in out.splitlines()[1:] if ln.strip()), "")
        return (resp.get("summary") or _status_words(status)) + (f": {first[:120]}" if first else ""), \
            (out[:DETAILS_CHARS] or None)
    if name == "research" and resp.get("status") == "done":
        src = ", ".join(s.get("title") or "" for s in resp.get("sources") or [])
        return f"Searched the web: {len(resp.get('sources') or [])} source(s){': ' + src if src else ''}", \
            (resp.get("answer") or "")[:DETAILS_CHARS]
    if name == "how_nightlight_works" and resp.get("title"):
        return f"Read Nightlight's guide: {resp['title']}", resp.get("text")
    if status == "pending":
        return "Waiting for your OK (card below)", None
    if status == "saved":
        return "Saved: " + str(resp.get("note") or resp.get("fact") or "")[:120], None
    if status:
        return _status_words(status), None if status in STATUS_WORDS else f"Status: {status}"
    return "Done", None


def _status_words(status) -> str:
    """A step's status in plain words; an unknown one reads as a general line (its code goes to the details)."""
    text = str(status or "")
    return STATUS_WORDS.get(text) or ("Step finished" if _CODE.fullmatch(text) or not text else text)


def _stop(uid: str, c: Claim, *, text: str | None, tool_calls: list, action_ids: list, metrics: dict | None = None):
    """End a claimed turn whose stream was closed: kept as failed `stopped`, and the session freed at once.
    Synchronous on purpose: nothing can be awaited in a cancelled task."""
    try:
        finish(uid, c, text=text, metrics=metrics or {}, tool_calls=tool_calls, action_ids=action_ids,
               error={"code": "stopped", "message": "Stopped before it finished."})
    except Exception:
        pass  # superseded or already finished: nothing to record


def _u16(text: str) -> int:
    """Length in UTF-16 code units: the unit JavaScript slices by, so offsets mean the same on both sides."""
    return len(text.encode("utf-16-le")) // 2


def _stored_step(t: dict, error: dict | None) -> dict:
    """A tool call as stored; one that never answered because the turn ended is marked unfinished, never ok."""
    step = {k: v for k, v in t.items() if not k.startswith("_")}
    if "summary" not in step and error:
        step.update(ok=False, unfinished=True)
    return step


def _ok(resp: dict) -> bool:
    """Whether a step worked, from the tool's own status (the chat marks failed steps; it never hides them)."""
    status = resp.get("status")
    if status in ("waiting", "safer_first"):  # the step's outcome is the card it came back with
        status = (resp.get("proposed") or {}).get("status")
    return not (status in ("error", "refused", "failed") or (status is None and (resp.get("reason") or resp.get("error"))))


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
