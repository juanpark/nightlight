"""The Nightlight agent: Gemini through ADK, run in-process for one turn at a time.

Tools read the caller's simulated fleet and *propose* actions; they never change anything directly. Every model call
is preceded by a cost reservation and an input-size bound, and followed by reconciliation (quota.py).
"""

import asyncio
import json
from dataclasses import dataclass, field

from google import genai
from google.adk.agents import LlmAgent
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext
from google.genai import types

from . import actions, db, quota
from .config import settings
from .errors import ApiError
from .fence import turn_fence
from .redact import scrub, scrub_value

INSTRUCTION = """You are Nightlight, a calm house-sitter for someone's home and small-office servers.
The person is not technical. Speak plainly: no jargon, no commands, no acronyms without a short explanation.

How to answer:
- Look before you speak: use the tools to read devices and recent events. Never invent device state.
- Lead with what matters in one or two short sentences: what is wrong, why it matters to them, how serious it is.
- If a fix helps, propose exactly one by calling its tool. Say what it will change and that it can be undone.
- After calling an action tool, report its status honestly:
  pending = "I've put a card up for your approval"; done = say it ran automatically because they allowed it;
  failed = say it didn't work and that nothing changed.
- Never claim something was done unless a tool result says status "done".
- Everything here is a simulated sample home; say so if asked.
- Keep the whole reply under 80 words."""

CONTINUATION = """You are Nightlight. A change the person decided on has just finished. In one or two short, plain
sentences, say what happened and how the device is now. Check the device with a tool first. Do not propose new
actions."""

FALLBACK = ("Sorry, that needed more thinking than I'm allowed for one answer. Could you ask about one device or one "
            "problem at a time?")


@dataclass
class TurnContext:
    uid: str
    session_id: str
    turn_id: str
    attempt: int
    generation: int
    ip: str
    metrics: dict = field(default_factory=lambda: {"modelCalls": 0, "toolCalls": 0, "tokensIn": 0, "tokensOut": 0,
                                                    "tokensThinking": 0, "costUsd": 0.0})
    reservations: list = field(default_factory=list)
    actions: list = field(default_factory=list)  # action docs proposed this turn
    redacted: int = 0


def _bounded(value: dict, ctx: TurnContext) -> dict:
    """Scrub a tool result and keep its final serialised form within tool_result_bytes."""
    clean, n = scrub_value(value)
    ctx.redacted += n
    limit = settings.tool_result_bytes
    if len(json.dumps(clean, default=str).encode()) <= limit:
        return clean
    raw = json.dumps(clean, default=str, ensure_ascii=False)
    keep = len(raw)
    while keep > 0:
        out = {"truncated": True, "summary": raw[:keep]}
        if len(json.dumps(out, default=str).encode()) <= limit:
            return out
        keep = int(keep * 0.8)
    return {"truncated": True, "summary": ""}


def _device_summary(d: dict) -> dict:
    top = next(iter(d.get("findings") or []), None)
    return {"id": d["id"], "name": d.get("name"), "purpose": d.get("purpose"), "status": d.get("status"),
            "health": d.get("health"), "diskPct": (d.get("vitals") or {}).get("diskPct"),
            "topProblem": top and top.get("message"), "simulated": d.get("simulated", True)}


def make_tools(ctx: TurnContext, read_only: bool):
    def _list_fleet_sync(tool_context: ToolContext) -> dict:
        """List every device in the person's home: name, purpose, health and its top problem."""
        devices = [_device_summary(dict(s.to_dict(), id=s.id)) for s in db.devices(ctx.uid).get()
                   if s.to_dict().get("demoGeneration") == ctx.generation]
        return _bounded({"devices": devices}, ctx)

    def _get_device_sync(device_id: str, tool_context: ToolContext) -> dict:
        """Read one device in detail: health, what runs on it, findings and what is using its disk.

        Args:
            device_id: the device id from list_fleet, for example "pi-1".
        """
        snap = db.device(ctx.uid, device_id).get()
        if not snap.exists or snap.to_dict().get("demoGeneration") != ctx.generation:
            return {"error": "no such device"}
        d = dict(snap.to_dict(), id=device_id)
        services = [dict(s.to_dict(), id=s.id) for s in db.services(ctx.uid, device_id).get()]
        keep = ("id", "name", "purpose", "os", "status", "health", "vitals", "findings", "diskConsumers",
                "diskGb", "simulated", "version")
        out = {k: d.get(k) for k in keep}
        out["services"] = [{k: s.get(k) for k in ("id", "name", "status", "version", "updateAvailable", "findings")}
                           for s in services]
        return _bounded(out, ctx)

    def _get_recent_events_sync(tool_context: ToolContext) -> dict:
        """List the ten most recent things that happened on the person's devices."""
        evs = [s.to_dict() for s in db.events(ctx.uid).get()]
        evs = [e for e in evs if e.get("demoGeneration") == ctx.generation]
        evs.sort(key=lambda e: str(e.get("at")), reverse=True)
        return _bounded({"events": [{k: e.get(k) for k in ("deviceId", "kind", "severity", "message", "at")}
                                    for e in evs[:10]]}, ctx)

    def _rotate_logs_sync(device_id: str, tool_context: ToolContext) -> dict:
        """Propose cleaning up log files older than 7 days on a device to free disk space.

        This never runs immediately unless the person has allowed it: usually it puts an approval card in front of
        them. Report the returned status honestly.

        Args:
            device_id: the device id, for example "pi-1".
        """
        try:
            a = actions.propose(ctx.uid, session_id=ctx.session_id, turn_id=ctx.turn_id, generation=ctx.generation,
                                action_type="rotate_logs", device_id=device_id, params={},
                                fence=turn_fence(ctx.uid, ctx.session_id, ctx.turn_id, ctx.attempt, ctx.generation))
        except ApiError as e:
            if e.code == "stale":
                raise
            return {"status": "error", "reason": e.code}
        except ValueError:
            return {"status": "error", "reason": "not applicable to this device"}
        ctx.actions.append(a)
        out = {"status": a["status"], "actionId": a["id"], "plan": a["plan"], "dryRun": a["dryRun"],
               "risk": a["riskClass"]}
        if a.get("result"):
            out["result"] = a["result"]["summary"]
        return _bounded(out, ctx)

    # The model sees async wrappers so blocking Firestore work runs off the event loop (lease renewal and pings keep
    # running). Each wrapper keeps the sync function's name, docstring and parameters for the tool declaration.
    async def list_fleet(tool_context: ToolContext) -> dict:
        return await asyncio.to_thread(_list_fleet_sync, tool_context)

    async def get_device(device_id: str, tool_context: ToolContext) -> dict:
        return await asyncio.to_thread(_get_device_sync, device_id, tool_context)

    async def get_recent_events(tool_context: ToolContext) -> dict:
        return await asyncio.to_thread(_get_recent_events_sync, tool_context)

    async def rotate_logs(device_id: str, tool_context: ToolContext) -> dict:
        return await asyncio.to_thread(_rotate_logs_sync, device_id, tool_context)

    for wrapper, sync in ((list_fleet, _list_fleet_sync), (get_device, _get_device_sync),
                          (get_recent_events, _get_recent_events_sync), (rotate_logs, _rotate_logs_sync)):
        wrapper.__doc__ = sync.__doc__
    tools = [list_fleet, get_device, get_recent_events]
    return tools if read_only else [*tools, rotate_logs]


# ------------------------------------------------------------------ callbacks: bound, reserve, reconcile

_genai_client = None


def _client():
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client()
    return _genai_client


def count_tokens(req) -> int:
    """Exact token count of the complete outgoing request (system instruction, tools, contents)."""
    cfg = types.CountTokensConfig(system_instruction=req.config.system_instruction, tools=req.config.tools)
    return _client().models.count_tokens(model=settings.model, contents=req.contents, config=cfg).total_tokens


COUNTER = count_tokens  # tests replace this; production always counts through the model's own API


def _trim_oldest(req) -> bool:
    """Drop the oldest complete exchange; never leave a tool response without its call, never drop the current input.

    The request is kept starting at a plain user message (not a tool response, not a model turn).
    """
    def starts_cleanly(contents):
        first = contents[0]
        return first.role == "user" and not any(p.function_response for p in (first.parts or []))

    if len(req.contents) <= 1:
        return False
    trimmed = req.contents[1:]
    while trimmed and not starts_cleanly(trimmed):
        trimmed = trimmed[1:]
    if not trimmed:
        return False
    req.contents[:] = trimmed
    return True


def bound_input(req, counter=None) -> None:
    """Guarantee the complete request fits max_input_tokens by exact count, trimming history; otherwise refuse."""
    limit = settings.max_input_tokens
    counter = counter or COUNTER
    for _ in range(50):
        try:
            n = counter(req)
        except Exception:
            raise ApiError(422, "context_limit") from None  # cannot prove the bound: fail closed
        if n <= limit:
            return
        if not _trim_oldest(req):
            break
    raise ApiError(422, "context_limit")


def scrub_content(content) -> None:
    """Scrub a whole message in place: all visible text is joined and scrubbed as one string.

    Scrubbing parts one by one would let a secret that starts in one part and ends in the next slip through. The
    scrubbed text goes into the first visible part; later visible parts are emptied (kept only if they carry an
    opaque thought signature, which must be preserved), so nothing else changes.
    """
    parts = (content.parts if content else None) or []
    visible = [i for i, p in enumerate(parts) if p.text and not p.thought]
    if not visible:
        return
    clean = scrub("".join(parts[i].text for i in visible))[0]
    parts[visible[0]].text = clean
    for i in reversed(visible[1:]):
        if parts[i].thought_signature or parts[i].function_call:
            parts[i].text = None
        else:
            del parts[i]


def make_callbacks(ctx: TurnContext):
    fence = turn_fence(ctx.uid, ctx.session_id, ctx.turn_id, ctx.attempt, ctx.generation)

    async def before_model(callback_context, llm_request):
        if ctx.metrics["modelCalls"] >= settings.model_calls_per_turn:
            raise ApiError(429, "too_many_steps")
        for content in llm_request.contents:  # defence in depth: nothing unscrubbed reaches the model
            scrub_content(content)
        # Blocking work (token count, reservation transaction) runs off the event loop so leases keep renewing.
        await asyncio.to_thread(bound_input, llm_request)
        # Ownership is checked in the same transaction as the reservation: a stale turn can't spend.
        ctx.reservations.append(await asyncio.to_thread(quota.reserve, ctx.uid, ctx.ip, None, fence))
        ctx.metrics["modelCalls"] += 1
        return None

    async def after_model(callback_context, llm_response: LlmResponse):
        if llm_response.partial:
            return None
        # Scrub the model's own words (as one text) before they become history for the next call.
        scrub_content(llm_response.content)
        reserved = ctx.reservations.pop() if ctx.reservations else 0.0
        u = llm_response.usage_metadata
        actual = quota.cost_of(u)
        if u:
            ctx.metrics["tokensIn"] += u.prompt_token_count or 0
            ctx.metrics["tokensOut"] += u.candidates_token_count or 0
            ctx.metrics["tokensThinking"] += u.thoughts_token_count or 0
        if actual is not None:
            ctx.metrics["costUsd"] += actual
        await asyncio.to_thread(quota.reconcile, reserved, actual)  # unknown usage keeps the full reservation
        return None

    def before_tool(tool, args, tool_context):
        # Admission happens before the tool runs, so a batch of parallel calls can't exceed the limit.
        if ctx.metrics["toolCalls"] >= settings.tool_calls_per_turn:
            return {"error": "tool limit reached for this answer; reply with what you have"}
        ctx.metrics["toolCalls"] += 1
        return None

    return before_model, after_model, before_tool


def build(ctx: TurnContext, *, continuation: bool, model=None) -> LlmAgent:
    before_model, after_model, before_tool = make_callbacks(ctx)
    return LlmAgent(
        name="nightlight",
        model=model or settings.model,
        instruction=CONTINUATION if continuation else INSTRUCTION,
        tools=make_tools(ctx, read_only=continuation),
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=settings.max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_level=settings.thinking_level)),
        before_model_callback=before_model,
        after_model_callback=after_model,
        before_tool_callback=before_tool,
    )
