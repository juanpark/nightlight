"""The honest time ceiling: a silent model call is cancelled and retried once, a second one ends the turn plainly,
and a spent time budget is said out loud instead of quietly thinning the answer."""

import asyncio

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from nightlight_api import agent as agentlib, db, quota, turns
from nightlight_api.config import settings
from fake_llm import FakeLlm
from test_chat import ask, events, fake_model, new_session  # noqa: F401 - fake_model is an autouse fixture
from test_investigate import _answer, _usage, dig, said

GAP = 0.3


@pytest.fixture(autouse=True)
def short_gaps(monkeypatch):
    monkeypatch.setattr(settings, "call_gap_seconds", GAP)
    monkeypatch.setattr(settings, "deep_call_gap_seconds", GAP)


def _check_pi(text="Let me check the Pi."):
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text), types.Part(
        function_call=types.FunctionCall(name="get_device", args={"device_id": "pi-1"}))]),
        partial=False, usage_metadata=_usage(), turn_complete=True)


def _script(*steps):
    """A behavior playing one step per model call: a response, or "hang" (silent far past the gap)."""
    seen = []

    async def behave(llm_request, stream):
        step = steps[len(seen)]
        seen.append(llm_request)
        if step == "hang":
            await asyncio.sleep(30)  # cancelled by the turn long before this ends
        yield step
    behave.seen = seen
    return behave


def _quota():
    return db.client().collection("ops").document("quota").get().to_dict()


def _assistant(uid, sid):
    return [m.to_dict() for m in db.messages(uid, sid).get() if m.to_dict()["role"] == "assistant"]


def test_a_silent_call_is_retried_once_and_the_answer_arrives(client, started):
    FakeLlm.behavior = b = _script("hang", _answer("The Pi is fine."))
    ev = events(ask(client, new_session(client)))
    assert ev[0]["budgetSeconds"] == settings.quick_turn_seconds  # turn_start: "Working… 45 s of 2 min"
    assert ev[-1]["type"] == "done" and said(ev) == "The Pi is fine."
    m = ev[-1]["metrics"]
    assert m["modelCalls"] == 2 and m["slowCalls"] == 1 and m["budgetSeconds"] == settings.quick_turn_seconds
    assert turns.CARRY_ON in " ".join(p.text or "" for c in b.seen[1].contents for p in c.parts or [])
    # Both calls were reserved; the cancelled one keeps its full reservation (Gemini may still bill it).
    q = _quota()
    assert q["calls"] == 2
    assert q["reservedUsd"] - q["spentUsd"] == pytest.approx(settings.c_max)
    assert q["spentUsd"] == pytest.approx(quota.cost_of(_usage(), None))


def test_two_silent_calls_end_the_turn_plainly_after_what_was_shown(client, started):
    uid = started
    sid = new_session(client)
    FakeLlm.behavior = _script(_check_pi(), "hang", "hang")
    ev = events(ask(client, sid))
    assert ev[-1] == {"type": "error", "code": "model_slow", "retryable": True,
                      "message": "Gemini is slow right now; nothing was changed. Please ask again."}
    assert said(ev) == "Let me check the Pi."  # what was already shown stays; nothing is made up after it
    stored = _assistant(uid, sid)
    assert len(stored) == 1 and stored[0]["text"] == "Let me check the Pi."
    assert stored[0]["metrics"]["modelCalls"] == 3 and stored[0]["metrics"]["slowCalls"] == 2
    assert stored[0]["error"]["code"] == "model_slow"
    turn = db.turns(uid, sid).document(ev[0]["turnId"]).get().to_dict()
    assert turn["status"] == "failed" and turn["error"]["code"] == "model_slow"
    assert db.session(uid, sid).get().to_dict()["activeTurn"] is None
    assert not [a for a in db.actions(uid).get() if a.to_dict().get("turnId") == ev[0]["turnId"]]  # nothing proposed
    assert _quota()["calls"] == 3


def test_a_retry_needs_a_free_call(client, started, monkeypatch):
    # The timed-out call used the turn's last call: no retry beyond the limit, the turn says so at once.
    monkeypatch.setattr(settings, "model_calls_per_turn", 1)
    FakeLlm.behavior = b = _script("hang", _answer("never"))
    ev = events(ask(client, new_session(client)))
    assert ev[-1]["code"] == "model_slow" and len(b.seen) == 1 and _quota()["calls"] == 1


def test_a_silent_answer_only_retry_is_not_retried_again(client, started):
    # The answer-only retry (empty reply → asked once more) is already the one call past the limit; if it goes
    # silent the turn ends plainly instead of taking a third extra call.
    empty = LlmResponse(content=types.Content(role="model", parts=[types.Part(text="")]), partial=False,
                        usage_metadata=_usage(), turn_complete=True)
    FakeLlm.behavior = b = _script(empty, "hang", _answer("never"))
    ev = events(ask(client, new_session(client)))
    assert ev[-1]["code"] == "model_slow" and len(b.seen) == 2
    q = _quota()
    assert q["calls"] == 2 and q["reservedUsd"] - q["spentUsd"] == pytest.approx(settings.c_max)


def test_streamed_chunks_keep_a_long_answer_alive(client, started):
    # The gap is silence, not total length: a reply that keeps sending chunks is never cut.
    async def slow_stream(llm_request, stream):
        for word in ("The ", "Pi ", "is ", "fine."):
            await asyncio.sleep(GAP * 0.6)
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=word)]), partial=True)
        yield _answer("The Pi is fine.")
    FakeLlm.behavior = slow_stream
    ev = events(ask(client, new_session(client)))
    assert ev[-1]["type"] == "done" and said(ev) == "The Pi is fine." and "slowCalls" not in ev[-1]["metrics"]


def test_a_spent_budget_is_said_plainly_with_no_new_checks(client, started, monkeypatch):
    monkeypatch.setattr(settings, "deep_turn_seconds", 0.2)

    seen = []

    async def behave(llm_request, stream):
        seen.append(llm_request)
        if len(seen) == 1:
            await asyncio.sleep(0.25)  # under the silence gap, but the turn's budget runs out meanwhile
            yield _check_pi("Let me check the NAS.")
        else:
            yield _answer("I couldn't check the NAS in time; its disk and backups are still unchecked.")
    FakeLlm.behavior = behave
    ev = events(dig(client, new_session(client)))
    assert ev[0]["budgetSeconds"] == 0.2
    assert ev[-1]["type"] == "done"
    results = [e for e in ev if e["type"] == "tool_result"]
    assert results and "time budget" in results[0]["summary"]  # the check the model asked for was refused
    one, two = seen
    assert agentlib.BUDGET_SPENT not in str(one.config.system_instruction)
    assert agentlib.BUDGET_SPENT in str(two.config.system_instruction)
    assert two.config.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.NONE
    assert str(two.config.thinking_config.thinking_level).endswith(settings.deep_thinking)  # no secret downgrade
    assert "still unchecked" in said(ev)


def test_no_hurry_left():
    assert not hasattr(agentlib, "HURRY") and not hasattr(settings, "deep_first_words_seconds")
    assert "spoke" not in agentlib.TurnContext.__dataclass_fields__
