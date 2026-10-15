"""Regressions for Codex's slice-2 re-review (R1-R4)."""

import asyncio
import json
import threading
import time
import uuid

from google.adk.models.llm_response import LlmResponse
from google.genai import types

from nightlight_api import agent as agentlib, db, turns
from nightlight_api.config import settings
from nightlight_api.errors import ApiError
from fake_llm import FakeLlm, reply
from test_chat import ask, events, new_session  # noqa: F401
from test_chat import fake_model  # noqa: F401

WORDS = " ".join(f"w{i}rd" for i in range(60))   # a long multiword synthetic value (> the old 160-char window)
MARK = "w42rd"


def _texts(uid, sid, crid, client):
    live = "".join(e.get("delta", "") for e in events(ask(client, sid, crid=crid)) if e["type"] == "text")
    stored = next(m.to_dict()["text"] for m in db.messages(uid, sid).get() if m.to_dict()["role"] == "assistant")
    replay = "".join(e.get("delta", "") for e in events(ask(client, sid, crid=crid)) if e["type"] == "text")
    return live, stored, replay


def test_long_quoted_value_never_leaks(client, started):  # R1
    uid, sid = started, new_session(client)
    FakeLlm.behavior = reply('Use this: pass' + 'word: "', WORDS[:90], WORDS[90:], '" and restart.')
    live, stored, replay = _texts(uid, sid, str(uuid.uuid4()), client)
    for text in (live, stored, replay):
        assert MARK not in text
    assert live == stored == replay


def test_generated_secret_not_sent_back_to_model(client, started):  # R2
    sid = new_session(client)

    async def leak_then_tool(llm_request, stream):
        if any(p.function_response for c in llm_request.contents for p in (c.parts or [])):
            async for r in reply("all good")(llm_request, stream):
                yield r
            return
        parts = [types.Part(text="noted tok" + "en=" + "Zq9" + "Xv7" + "Lm3 "),
                 types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"}))]
        yield LlmResponse(content=types.Content(role="model", parts=parts), partial=False)

    FakeLlm.behavior = leak_then_tool
    events(ask(client, sid))
    assert len(FakeLlm.log) == 2 and all("Zq9Xv7Lm3" not in call["text"] for call in FakeLlm.log)


def test_slow_token_count_keeps_the_lease(client, started, monkeypatch):  # R3
    uid, sid = started, new_session(client)
    monkeypatch.setattr(settings, "turn_lease_seconds", 1)
    monkeypatch.setattr(agentlib, "COUNTER", lambda req: time.sleep(2.5) or 100)
    FakeLlm.behavior = reply("done")
    claimed = turns.claim(uid, turns.accept_message(uid, sid, "hi", str(uuid.uuid4())))
    result = {}

    def intruder():
        time.sleep(1.5)
        try:
            turns.claim(uid, claimed.turn_id)
            result["claim"] = "stolen"
        except ApiError as e:
            result["claim"] = e.code

    t = threading.Thread(target=intruder)
    t.start()

    async def run():
        return [json.loads(x[5:]) async for x in turns.stream(uid, claimed, "ip") if x.startswith("data:")]

    ev = asyncio.run(run())
    t.join()
    assert result["claim"] == "turn_in_progress" and ev[-1]["type"] == "done"


def test_whitespace_only_answer_is_consistent(client, started):  # R4
    uid, sid = started, new_session(client)
    FakeLlm.behavior = reply(" " * 200, " " * 200)
    live, stored, replay = _texts(uid, sid, str(uuid.uuid4()), client)
    assert live == stored == replay == agentlib.FALLBACK


def _multipart(text_parts, with_tool=False):
    """A finished response whose visible text is split across parts, with a thought part in between."""
    async def gen(llm_request, stream):
        if with_tool and any(p.function_response for c in llm_request.contents for p in (c.parts or [])):
            async for r in reply("all good")(llm_request, stream):
                yield r
            return
        parts = [types.Part(text=text_parts[0]), types.Part(text="thinking…", thought=True),
                 *[types.Part(text=t) for t in text_parts[1:]]]
        if with_tool:
            parts.append(types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"})))
        yield LlmResponse(content=types.Content(role="model", parts=parts), partial=False)
    return gen


SPLIT = ['Here is the setting: pass' + 'word: "', WORDS, '" then restart the Pi.']


def test_multipart_response_never_leaks(client, started):  # R1, completed multipart
    uid, sid = started, new_session(client)
    FakeLlm.behavior = _multipart(SPLIT)
    live, stored, replay = _texts(uid, sid, str(uuid.uuid4()), client)
    for text in (live, stored, replay):
        assert MARK not in text
    assert live == stored == replay


def test_multipart_secret_not_sent_back_to_model(client, started):  # R2, completed multipart + tool loop
    sid = new_session(client)
    FakeLlm.behavior = _multipart(SPLIT, with_tool=True)
    events(ask(client, sid))
    assert len(FakeLlm.log) == 2 and all(MARK not in call["text"] for call in FakeLlm.log)
