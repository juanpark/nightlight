"""Investigate mode holds up under a busy model, a slow model and a model that answers with its own notes."""

import uuid

from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types

from nightlight_api import agent as agentlib
from nightlight_api.config import settings
from fake_llm import FakeLlm
from test_chat import events, fake_model, new_session  # noqa: F401 - fake_model is an autouse fixture

FLEET = "- pi-1 (Raspberry Pi, simulated): x\n- nas-1 (NAS, simulated): y\n- game-1 (Game server, simulated): z"


def dig(client, sid, text="Why is my NAS slow?"):
    return client.post(f"/api/chat/sessions/{sid}/messages",
                       json={"text": text, "clientRequestId": str(uuid.uuid4()), "mode": "investigate"})


def said(ev):
    return "".join(e.get("delta", "") for e in ev if e["type"] == "text")


def _usage():
    return types.GenerateContentResponseUsageMetadata(prompt_token_count=500, candidates_token_count=20,
                                                      total_token_count=520)


def _answer(text, finish=None):
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]), partial=False,
                       usage_metadata=_usage(), turn_complete=True, finish_reason=finish)


def _tidied(text, finish=None, fleet=FLEET):
    r = _answer(text, finish)
    agentlib._tidy_thinking(agentlib.TurnContext("u", "s", "t", 1, 1, "ip", fleet=fleet), r)
    return "".join(p.text or "" for p in r.content.parts)


LEAK = ("Checking `nas-1` with get_device first, then `game-1`.\n\n"
        "Wait! If someone asks about the backups I should call read_device_log on nas-1.\n\n"
        "Your NAS is fine: its disk is 40% full and the nightly backup ran. The Game server's backups go there "
        "too. I'd check the restore next and")


def test_leaked_notes_become_a_plain_answer():
    out = _tidied(LEAK)
    assert out == ("Your NAS is fine: its disk is 40% full and the nightly backup ran. The Game server's backups go "
                   "there too.")
    # ids become names and tool names plain words, even without self-talk
    assert _tidied("I read `nas-1` with get_device: the NAS is fine.") == \
        "I read NAS with get device: the NAS is fine."


def test_a_clean_answer_is_never_touched():
    for text in ("Wait about ten minutes, then check the Raspberry Pi again.",
                 "The NAS is fine. Its log is in /var/log/nas-1/rotate_logs today.",
                 "Your Pi is fine"):  # no sentence end, but not cut off by the token limit either
        assert _tidied(text) == text
    # a reply with a tool call is left alone: the guard only rewrites final answers
    r = LlmResponse(content=types.Content(role="model", parts=[
        types.Part(text="Wait! Checking `nas-1`."),
        types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "nas-1"}))]))
    agentlib._tidy_thinking(agentlib.TurnContext("u", "s", "t", 1, 1, "ip", fleet=FLEET), r)
    assert r.content.parts[0].text == "Wait! Checking `nas-1`."
    # cut off by the token limit: the unfinished sentence goes
    assert _tidied("The NAS is fine. I'd check the", types.FinishReason.MAX_TOKENS) == "The NAS is fine."


def test_a_leak_in_an_investigate_turn_reaches_the_person_as_a_plain_answer(client, started):
    async def behave(llm_request, stream):
        yield _answer(LEAK)
    FakeLlm.behavior = behave
    ev = events(dig(client, new_session(client)))
    text = said(ev)
    assert ev[-1]["type"] == "done" and text.startswith("Your NAS is fine")
    assert "`" not in text and "nas-1" not in text and "Wait!" not in text and text.endswith("too.")


def _busy():
    return errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Resource "
                                              "exhausted. Please try again later."}})


def test_a_busy_deep_model_hands_the_turn_to_the_quick_model(client, started):
    asked = []

    async def behave(llm_request, stream):
        asked.append((llm_request.model, llm_request.config.thinking_config.thinking_level))
        if llm_request.model == settings.deep_model:
            raise _busy()
        done = any(p.function_response for c in llm_request.contents for p in (c.parts or []))
        if not done:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(
                function_call=types.FunctionCall(name="get_device", args={"device_id": "nas-1"}))]),
                partial=False, usage_metadata=_usage(), turn_complete=True)
        else:
            yield _answer("Your NAS is fine.")
    FakeLlm.behavior = behave
    ev = events(dig(client, new_session(client)))
    assert ev[-1]["type"] == "done" and said(ev) == "Your NAS is fine."
    # the deep model was tried once; that call and the rest of the turn went to the quick model
    assert [m for m, _ in asked] == [settings.deep_model, settings.model, settings.model]
    assert all(str(t).endswith(settings.thinking_level) for _, t in asked[1:])


def test_when_both_models_are_busy_the_person_reads_a_plain_message(client, started):
    async def behave(llm_request, stream):
        raise _busy()
        yield  # an async generator
    FakeLlm.behavior = behave
    ev = events(dig(client, new_session(client)))
    assert ev[-1]["type"] == "error" and ev[-1]["code"] == "busy" and ev[-1]["retryable"] is True
    assert ev[-1]["message"] == "Nightlight is busy right now. Try again in a minute, or ask in Quick mode."
    FakeLlm.behavior = behave  # Quick mode: no fallback, and no pointing at Quick mode
    ev = events(client.post(f"/api/chat/sessions/{new_session(client)}/messages",
                            json={"text": "hi", "clientRequestId": str(uuid.uuid4())}))
    assert ev[-1]["code"] == "busy" and ev[-1]["message"] == "Nightlight is busy right now. Try again in a minute."


def test_a_silent_investigation_is_told_to_answer_now(client, started, monkeypatch):
    monkeypatch.setattr(settings, "deep_first_words_seconds", 0)
    seen = []

    async def behave(llm_request, stream):
        seen.append((agentlib.HURRY in str(llm_request.config.system_instruction),
                     str(llm_request.config.thinking_config.thinking_level)))
        if len(seen) == 1:
            yield _answer("Let me check the NAS first.")  # not a final answer in practice, but words for the person
        else:
            yield _answer("Done.")
    FakeLlm.behavior = behave
    events(dig(client, new_session(client)))
    assert seen[0][0] is True and seen[0][1].endswith("LOW")
    seen.clear()

    async def speaks_then_checks(llm_request, stream):
        seen.append(agentlib.HURRY in str(llm_request.config.system_instruction))
        if len(seen) == 1:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Let me check the NAS."),
                types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "nas-1"}))]),
                partial=False, usage_metadata=_usage(), turn_complete=True)
        else:
            yield _answer("The NAS is fine.")
    FakeLlm.behavior = speaks_then_checks
    events(dig(client, new_session(client)))
    assert seen == [True, False]  # once the person has words, the next call isn't hurried
