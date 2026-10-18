"""Investigate mode holds up under a busy model, a slow model and a model that answers with its own notes."""

import uuid

from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types

from nightlight_api import agent as agentlib
from nightlight_api.config import settings
from fake_llm import FakeLlm
from test_chat import events, fake_model, new_session  # noqa: F401 - fake_model is an autouse fixture

FLEET = "- pi-1 (Raspberry Pi): x\n- nas-1 (NAS): y\n- game-1 (Game server): z"


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


def test_ids_become_names_and_nothing_else_changes():
    # The one rewrite left is a lookup on a known table: ids → names, fixed tool names → plain words.
    assert _tidied("I read `nas-1` with get_device: the NAS is fine.") == "I read NAS with get device: the NAS is fine."
    for text in ("Wait about ten minutes, then check the Raspberry Pi again.",
                 "The NAS is fine. Its log is in /var/log/nas-1/rotate_logs today.",
                 "Your Pi is fine",
                 "Let me think. If someone asks about backups, the NAS keeps them."):  # meaning is never guessed at
        assert _tidied(text) == text
    # cut off by the token limit: not trimmed here (turns asks for a shorter answer instead)
    assert _tidied("The NAS is fine. I'd check the", types.FinishReason.MAX_TOKENS) == "The NAS is fine. I'd check the"
    # a reply with a tool call is left alone
    r = LlmResponse(content=types.Content(role="model", parts=[
        types.Part(text="Checking `nas-1`."),
        types.Part(function_call=types.FunctionCall(name="get_device", args={"device_id": "nas-1"}))]))
    agentlib._tidy_thinking(agentlib.TurnContext("u", "s", "t", 1, 1, "ip", fleet=FLEET), r)
    assert r.content.parts[0].text == "Checking `nas-1`."


def test_an_investigate_answer_reaches_the_person_with_names_for_ids(client, started):
    async def behave(llm_request, stream):
        yield _answer(LEAK)
    FakeLlm.behavior = behave
    ev = events(dig(client, new_session(client)))
    text = said(ev)
    assert ev[-1]["type"] == "done" and "nas-1" not in text and "`" not in text
    assert "Wait! If someone asks about the backups" in text  # its words are its own: nothing is deleted


def _busy():
    return errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Resource "
                                              "exhausted. Please try again later."}})


def test_a_real_warning_is_never_taken_for_a_note(client, started):  # Codex investigate #2
    text = "The NAS backup failed.\n\nWait! Do not restart it until a backup succeeds.\n\nYou can check its disk next."
    assert _tidied(text) == text
    assert _tidied("Hold on: the Pi is still copying files. Leave it plugged in.") == \
        "Hold on: the Pi is still copying files. Leave it plugged in."


def test_a_busy_model_ends_the_turn_with_a_plain_message(client, started):  # Codex #1
    calls = []

    async def behave(llm_request, stream):
        calls.append(llm_request.model)
        raise _busy()
        yield  # an async generator
    FakeLlm.behavior = behave
    ev = events(dig(client, new_session(client)))
    # Investigate busy before anything ran: one Quick look, said as such (never hidden); busy there too: the error
    assert said(ev) == "Investigate is busy right now, so here is a quick look instead.\n\n"
    assert ev[-1]["type"] == "error" and ev[-1]["code"] == "busy" and ev[-1]["retryable"] is True
    assert ev[-1]["message"] == "Nightlight is busy right now. Try again in a minute."
    assert len(calls) == 2  # Investigate's call, then one Quick call; no more
    calls.clear()
    FakeLlm.behavior = behave  # Quick mode: no pointing at Quick mode, no second call
    ev = events(client.post(f"/api/chat/sessions/{new_session(client)}/messages",
                            json={"text": "hi", "clientRequestId": str(uuid.uuid4())}))
    assert ev[-1]["code"] == "busy" and ev[-1]["message"] == "Nightlight is busy right now. Try again in a minute."
    assert len(calls) == 1


def test_investigate_busy_at_once_gives_a_quick_look_that_says_so(client, started):
    deep = []

    async def behave(llm_request, stream):
        deep.append(llm_request.config.max_output_tokens == settings.deep_max_output_tokens)
        if len(deep) == 1:
            raise _busy()
        yield _answer("The NAS is fine: its disk is 40% full.")
    FakeLlm.behavior = behave
    ev = events(dig(client, new_session(client)))
    assert ev[-1]["type"] == "done" and deep == [True, False]  # the second call is a Quick one
    assert said(ev) == ("Investigate is busy right now, so here is a quick look instead.\n\n"
                        "The NAS is fine: its disk is 40% full.")


def test_a_hidden_cut_answer_still_lets_quick_stand_in(client, started):  # Codex merge v2 #1
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types
    deep = []

    async def behave(llm_request, stream):
        deep.append(llm_request.config.max_output_tokens == settings.deep_max_output_tokens)
        if len(deep) == 1:  # a partial the person never sees, then a reply the length limit cut off
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="The NAS")]), partial=True)
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="The NAS is slow bec")]),
                              partial=False, turn_complete=True, finish_reason=types.FinishReason.MAX_TOKENS)
        elif len(deep) == 2:  # the answer-only retry: the model is busy
            raise _busy()
        else:
            yield _answer("The NAS is fine: its disk is 40% full.")
    FakeLlm.behavior = behave
    ev = events(dig(client, new_session(client)))
    assert ev[-1]["type"] == "done" and deep == [True, True, False]
    assert said(ev) == ("Investigate is busy right now, so here is a quick look instead.\n\n"
                        "The NAS is fine: its disk is 40% full.")


def test_busy_after_steps_ran_is_not_retried(client, started):
    calls = []

    async def behave(llm_request, stream):
        calls.append(1)
        if len(calls) == 1:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(
                function_call=types.FunctionCall(name="list_fleet", args={}))]), partial=False, usage_metadata=_usage())
            return
        raise _busy()
    FakeLlm.behavior = behave
    ev = events(dig(client, new_session(client)))
    assert ev[-1]["code"] == "busy" and len(calls) == 2 and "quick look" not in said(ev)
