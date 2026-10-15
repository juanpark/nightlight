"""The Nightlight agent: Gemini through ADK, run in-process for one turn at a time.

Tools read the caller's simulated fleet and *propose* actions; they never change anything directly. Every model call
is preceded by a cost reservation and an input-size bound, and followed by reconciliation (quota.py).
"""

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
from .redact import scrub_value

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
    clean, n = scrub_value(value)
    ctx.redacted += n
    raw = json.dumps(clean, default=str)
    if len(raw.encode()) > settings.tool_result_bytes:
        return {"truncated": True, "summary": raw[: settings.tool_result_bytes - 200]}
    return clean


def _device_summary(d: dict) -> dict:
    top = next(iter(d.get("findings") or []), None)
    return {"id": d["id"], "name": d.get("name"), "purpose": d.get("purpose"), "status": d.get("status"),
            "health": d.get("health"), "diskPct": (d.get("vitals") or {}).get("diskPct"),
            "topProblem": top and top.get("message"), "simulated": d.get("simulated", True)}


def make_tools(ctx: TurnContext, read_only: bool):
    def list_fleet(tool_context: ToolContext) -> dict:
        """List every device in the person's home: name, purpose, health and its top problem."""
        devices = [_device_summary(dict(s.to_dict(), id=s.id)) for s in db.devices(ctx.uid).get()
                   if s.to_dict().get("demoGeneration") == ctx.generation]
        return _bounded({"devices": devices}, ctx)

    def get_device(device_id: str, tool_context: ToolContext) -> dict:
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

    def get_recent_events(tool_context: ToolContext) -> dict:
        """List the ten most recent things that happened on the person's devices."""
        evs = [s.to_dict() for s in db.events(ctx.uid).get()]
        evs = [e for e in evs if e.get("demoGeneration") == ctx.generation]
        evs.sort(key=lambda e: str(e.get("at")), reverse=True)
        return _bounded({"events": [{k: e.get(k) for k in ("deviceId", "kind", "severity", "message", "at")}
                                    for e in evs[:10]]}, ctx)

    def rotate_logs(device_id: str, tool_context: ToolContext) -> dict:
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

    tools = [list_fleet, get_device, get_recent_events]
    return tools if read_only else [*tools, rotate_logs]


# ------------------------------------------------------------------ callbacks: bound, reserve, reconcile

_genai_client = None


def _client():
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client()
    return _genai_client


def _request_bytes(req) -> int:
    payload = {"contents": [c.model_dump(mode="json", exclude_none=True) for c in req.contents],
               "system": str(req.config.system_instruction or ""),
               "tools": [t.model_dump(mode="json", exclude_none=True) for t in (req.config.tools or [])]}
    return len(json.dumps(payload).encode())


def _count(req) -> int:
    cfg = types.CountTokensConfig(system_instruction=req.config.system_instruction, tools=req.config.tools)
    return _client().models.count_tokens(model=settings.model, contents=req.contents, config=cfg).total_tokens


def _trim_oldest(req) -> bool:
    """Drop the oldest history entry without leaving a function response whose call was removed."""
    if len(req.contents) <= 1:
        return False
    req.contents.pop(0)
    while len(req.contents) > 1 and any(p.function_response for p in (req.contents[0].parts or [])):
        req.contents.pop(0)
    return True


def bound_input(req, counter=None) -> None:
    """Guarantee the request fits max_input_tokens, or refuse to call the model.

    Tokens never exceed the UTF-8 bytes of the serialised request (byte-fallback tokeniser), so a request whose JSON
    is within the limit is admitted without a count. Larger requests are counted exactly and trimmed.
    """
    limit = settings.max_input_tokens
    if _request_bytes(req) <= limit:
        return
    counter = counter or _count
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


def make_callbacks(ctx: TurnContext):
    def before_model(callback_context, llm_request):
        if ctx.metrics["modelCalls"] >= settings.model_calls_per_turn:
            raise ApiError(429, "too_many_steps")
        bound_input(llm_request)
        ctx.reservations.append(quota.reserve(ctx.uid, ctx.ip))
        ctx.metrics["modelCalls"] += 1
        return None

    def after_model(callback_context, llm_response: LlmResponse):
        if llm_response.partial:
            return None
        u = llm_response.usage_metadata
        reserved = ctx.reservations.pop() if ctx.reservations else 0.0
        if not u:
            return None  # usage unknown: the full reservation stays counted
        ctx.metrics["tokensIn"] += u.prompt_token_count or 0
        ctx.metrics["tokensOut"] += u.candidates_token_count or 0
        ctx.metrics["tokensThinking"] += u.thoughts_token_count or 0
        actual = quota.cost_of(u.prompt_token_count, u.candidates_token_count, u.thoughts_token_count)
        if actual is not None:
            ctx.metrics["costUsd"] += actual
        quota.reconcile(reserved, actual)
        return None

    def after_tool(tool, args, tool_context, tool_response):
        ctx.metrics["toolCalls"] += 1
        return None

    return before_model, after_model, after_tool


def build(ctx: TurnContext, *, continuation: bool, model=None) -> LlmAgent:
    before_model, after_model, after_tool = make_callbacks(ctx)
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
        after_tool_callback=after_tool,
    )
