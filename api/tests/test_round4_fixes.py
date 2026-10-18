"""From the round-4 real-VM run (helper 0.9.31, API rev 00105): get_device came back as one cut string (its step said
"Done"), inspect after a playbook got the playbook's conclusions again (its step said "done"), and a refused (429)
model call ended the answer at once."""

import json
import uuid

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types

from nightlight_api import agent as agentlib, turns
from nightlight_api.config import settings
from fake_llm import FakeLlm
from test_chat import events, fake_model, new_session  # noqa: F401 - fake_model is an autouse fixture

REAL_BUILD = agentlib.build  # taken at import, before the fake_model fixture swaps it


def _ctx():
    return agentlib.TurnContext(uid="u", session_id="s", turn_id="t", attempt=1, generation=1, ip="i")


def _device(notes=12):
    return {"id": "dev_1", "name": "Debian computer", "status": "warn", "vitals": {"diskPct": 17.0, "mem": 36.2},
            "findings": [{"id": "f_ctr_cache", "message": "cache isn't running: it was force-stopped"}],
            "services": [{"id": f"svc{i}", "name": f"app-{i}", "status": "ok"} for i in range(6)],
            "notebook": {"device": [{"text": "a dated note " * 12, "written": "2026-10-17 (1 day ago)"}] * notes,
                         "services": {"cache": [{"text": "cache note " * 20, "written": "today"}] * 3}},
            "runbooks": [], "profile": {"text": "profile text " * 150, "written": "today"}}


def test_an_oversized_device_read_keeps_its_shape_and_its_readings():
    out = agentlib._bounded(_device(), _ctx(), shrink=("profile", "notebook", "runbooks", "diskConsumers"))
    assert len(json.dumps(out).encode()) <= settings.tool_result_bytes
    assert "truncated" not in out and out["vitals"] == {"diskPct": 17.0, "mem": 36.2}
    assert len(out["services"]) == 6 and out["findings"]  # today's readings are whole
    assert "shortened" in out  # and it says history was cut
    line, _ = turns._commentary("get_device", out)
    assert line.startswith("disk 17.0%, memory 36%, 1 problem(s)")


def test_many_findings_keep_a_structured_envelope_with_a_count():
    d = _device(notes=0)
    d["findings"] = [{"id": f"f_ctr_{i}", "check": "container_down", "severity": "warn", "svcId": f"c{i}",
                      "message": f"container-{i} isn't running: it exited with code 1", "evidence": "x" * 40}
                     for i in range(50)]
    out = agentlib._bounded(d, _ctx(), shrink=("profile", "notebook", "runbooks"), readings=("findings", "services"))
    assert len(json.dumps(out).encode()) <= settings.tool_result_bytes and "truncated" not in out
    assert out["vitals"] == {"diskPct": 17.0, "mem": 36.2} and out["findings"][0]["message"].startswith("container-0")
    assert out["findingsOmitted"]["total"] == 50 and out["findingsOmitted"]["notShown"] == 50 - len(out["findings"])
    assert "50 problem(s)" in turns._commentary("get_device", out)[0]


def test_big_permissions_are_bounded_with_counts_and_the_readings_survive():
    d = _device(notes=0)
    d["findings"] = [{"id": f"f{i}", "severity": "warn", "message": f"container-{i} isn't running"} for i in range(50)]
    d["allowedJobs"] = {job: [f"some-long-container-name-{i:02d}" for i in range(20)]
                        for job in ("restart_container", "diagnose", "logs", "inspect")}
    out = agentlib._bounded(d, _ctx(), shrink=("profile", "notebook", "runbooks"), readings=("findings", "services"))
    assert len(json.dumps(out).encode()) <= settings.tool_result_bytes and "truncated" not in out
    assert out["vitals"] == {"diskPct": 17.0, "mem": 36.2} and out["findings"]
    assert out["allowedJobsOmitted"]["diagnose"] == {"notShown": 17, "total": 20}
    assert len(out["allowedJobs"]["diagnose"]) == 3


def test_a_small_result_is_untouched():
    small = {"status": "done", "vitals": {"mem": 1}}
    assert agentlib._bounded(small, _ctx(), shrink=("notebook",)) == small


def test_step_lines_for_reads_never_say_just_done():
    assert turns._commentary("inspect", {"status": "done", "playbook": "Playbook \"Running slowly\":\n- x is busy"}
                             )[0] == "Checkup done: 1 finding(s)"
    line, _ = turns._commentary("inspect", {"status": "done", "summary": None, "output": "Processor busy: 90%\nmore"})
    assert line == "The device answered: Processor busy: 90%"
    assert turns._commentary("get_device", {"truncated": True, "summary": "{..."})[0].startswith("Read it")


# ------------------------------------------------------------------ a refused (429) model call is asked again

class BusyRetryFake(FakeLlm):
    """FakeLlm with the production retry around each call (as RetryingGemini wraps Gemini)."""

    async def generate_content_async(self, llm_request, stream=False):
        parent = super(BusyRetryFake, self)
        async for r in agentlib.busy_retry(lambda: parent.generate_content_async(llm_request, stream),
                                           agentlib.CURRENT_TURN.get()):
            yield r


def _busy():
    return errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "exhausted"}})


def _answer(text):
    usage = types.GenerateContentResponseUsageMetadata(prompt_token_count=500, candidates_token_count=20,
                                                       total_token_count=520)
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]), partial=False,
                       usage_metadata=usage, turn_complete=True)


@pytest.fixture
def retrying(monkeypatch):
    monkeypatch.setattr(agentlib, "BUSY_DELAYS", (0.01, 0.02))
    monkeypatch.setattr(agentlib, "build", lambda ctx, continuation, model=None:
                        REAL_BUILD(ctx, continuation=continuation, model=BusyRetryFake()))
    yield


def _refusals(monkeypatch, ctx, n_busy, reserve_seconds=0.0):
    """Drive busy_retry directly: n_busy refusals, then an answer. Returns (attempts, released, raised)."""
    import asyncio
    import time as _time
    from nightlight_api import agent
    released, attempts = [], []
    monkeypatch.setattr(agent, "BUSY_DELAYS", (0.0, 0.0))
    monkeypatch.setattr(agent.quota, "reconcile", lambda reserved, actual: released.append((reserved, actual)))

    def reserve(*a, **k):
        _time.sleep(reserve_seconds)
        return 1.0
    monkeypatch.setattr(agent.quota, "reserve", reserve)
    monkeypatch.setattr(agent, "turn_fence", lambda *a: None)

    async def call():
        attempts.append(1)
        if len(attempts) <= n_busy:
            raise _busy()
        yield "ok"

    async def run():
        ctx.reservations.append(1.0)  # the first call's reservation, as before_model makes it
        ctx.metrics["modelCalls"] += 1
        return [r async for r in agent.busy_retry(call, ctx)]
    try:
        asyncio.run(run())
        return attempts, released, None
    except Exception as e:
        return attempts, released, e


def test_every_refusal_releases_its_reservation_even_the_last(monkeypatch):
    ctx = _ctx()
    attempts, released, raised = _refusals(monkeypatch, ctx, n_busy=5)
    assert raised is not None and len(attempts) == 1 + agentlib.BUSY_RETRIES
    assert released == [(1.0, 0.0)] * len(attempts) and ctx.reservations == []  # nothing unbillable kept
    assert ctx.metrics["modelCalls"] == len(attempts)  # each attempt counted
    ctx = _ctx()
    ctx.retry_from = 0  # the answer-only retry: no new try, but its refusal is released too
    attempts, released, raised = _refusals(monkeypatch, ctx, n_busy=1)
    assert raised is not None and len(attempts) == 1 and released == [(1.0, 0.0)] and ctx.reservations == []


def test_no_retry_starts_after_the_budget_even_if_reserving_was_slow(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(type(ctx), "turn_seconds", property(lambda self: 0.05))
    attempts, released, raised = _refusals(monkeypatch, ctx, n_busy=1, reserve_seconds=0.08)
    assert raised is not None and len(attempts) == 1  # reserved, then past the budget: never sent
    assert ctx.reservations == [] and ctx.metrics["modelCalls"] == 1


def _quick(client):
    return events(client.post(f"/api/chat/sessions/{new_session(client)}/messages",
                              json={"text": "hi", "clientRequestId": str(uuid.uuid4())}))


def test_a_refused_call_is_asked_again_and_counted(client, started, retrying):
    calls = []

    async def behave(llm_request, stream):
        calls.append(1)
        if len(calls) == 1:
            raise _busy()
        yield _answer("Your Pi is fine.")
    FakeLlm.behavior = behave
    ev = _quick(client)
    assert ev[-1]["type"] == "done" and len(calls) == 2
    m = ev[-1]["metrics"]
    assert m["modelCalls"] == 2 and m["busyRetries"] == 1  # the new try is counted like any call


def test_a_model_that_stays_busy_still_ends_plainly_after_bounded_tries(client, started, retrying):
    calls = []

    async def behave(llm_request, stream):
        calls.append(1)
        raise _busy()
        yield
    FakeLlm.behavior = behave
    ev = _quick(client)
    assert ev[-1]["type"] == "error" and ev[-1]["code"] == "busy"
    assert len(calls) == 1 + agentlib.BUSY_RETRIES
