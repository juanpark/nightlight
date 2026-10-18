"""The owner's time zone: kept on the account (explicit, or learned once from the browser's X-Time-Zone), and every
time the agent reads or a step line shows is written in it with its abbreviation; UTC, labelled, when unknown."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from nightlight_api import agent as agentlib, clock, db, notebook
from nightlight_api.config import settings
from nightlight_api.main import app
from fake_llm import FakeLlm
from test_chat import ask, events, new_session

AT = datetime(2026, 10, 18, 4, 50, tzinfo=timezone.utc)
SEEN: list = []


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    FakeLlm.log.clear()
    SEEN.clear()
    monkeypatch.setattr(agentlib, "COUNTER", lambda req: 100)
    real_build = agentlib.build
    monkeypatch.setattr(agentlib, "build", lambda ctx, continuation, model=None:
                        real_build(ctx, continuation=continuation, model=FakeLlm()))
    db.client().collection("ops").document("flags").delete()
    db.client().collection("ops").document("quota").delete()
    for d in db.client().collection("ipQuotas").list_documents():
        d.delete()

    async def read_log_then_answer(llm_request, stream):
        responses = [p.function_response for c in llm_request.contents for p in (c.parts or []) if p.function_response]
        SEEN.append((str(llm_request.config.system_instruction or ""), [dict(r.response or {}) for r in responses]))
        part = types.Part(text="Done.") if responses else types.Part(function_call=types.FunctionCall(
            name="read_device_log", args={"device_id": "pi-1"}))
        yield LlmResponse(content=types.Content(role="model", parts=[part]), partial=False, turn_complete=True)

    FakeLlm.behavior = read_log_then_answer
    yield
    FakeLlm.behavior = None


def _job(uid):
    gen = db.user(uid).get().to_dict()["demoGeneration"]
    db.actions(uid).document(f"act_{uuid.uuid4().hex[:20]}").set({
        "deviceId": "pi-1", "status": "done", "type": "rotate_logs", "plan": "Tidy the logs", "demoGeneration": gen,
        "createdAt": AT, "finishedAt": AT, "result": {"ok": True, "summary": "tidied"}})


def _turn(client, uid, header=None):
    sid = new_session(client)
    if header:
        client.headers["X-Time-Zone"] = header
    try:
        ev = events(ask(client, sid))
    finally:
        client.headers.pop("X-Time-Zone", None)
    step = next(e for e in ev if e["type"] == "tool_result" and e["name"] == "read_device_log")
    system, responses = SEEN[-1]
    return step, system, str(responses)


def test_zone_set_shows_local_times_in_tool_results_and_step_lines(client, started):
    assert client.post("/api/settings", json={"timeZone": "Asia/Seoul"}).json()["timeZone"] == "Asia/Seoul"
    _job(started)
    step, system, seen = _turn(client, started)
    assert "18 Oct 13:50 KST" in seen and "04:50" not in seen
    assert "18 Oct 13:50 KST" in step["details"]
    assert "owner's time zone (Asia/Seoul)" in system


def test_no_zone_reads_as_labelled_utc(client, started):
    _job(started)
    step, system, seen = _turn(client, started)
    assert "18 Oct 04:50 UTC" in seen and "18 Oct 04:50 UTC" in step["details"]
    assert "UTC" in system
    assert client.get("/api/settings").json()["timeZone"] is None


def test_browser_zone_is_kept_once_and_an_explicit_one_wins(client, started):
    _job(started)
    step, _, _ = _turn(client, started, header="Asia/Seoul")
    assert "13:50 KST" in step["details"]
    s = client.get("/api/settings").json()
    assert s["timeZone"] == "Asia/Seoul" and s["timeZoneAuto"] is True
    step, _, _ = _turn(client, started, header="Europe/Istanbul")  # still learned, so a new browser zone replaces it
    assert client.get("/api/settings").json()["timeZone"] == "Europe/Istanbul"
    client.post("/api/settings", json={"timeZone": "Asia/Seoul"})
    step, _, _ = _turn(client, started, header="America/New_York")
    assert "13:50 KST" in step["details"]
    s = client.get("/api/settings").json()
    assert s["timeZone"] == "Asia/Seoul" and s["timeZoneAuto"] is False


def test_invalid_zone_rejected_and_bad_header_ignored(client, started):
    for bad in ("Mars/Olympus", "localtime", "../etc/passwd", ""):
        assert client.post("/api/settings", json={"timeZone": bad}).status_code == 422
    assert client.post("/api/settings", json={}).status_code == 422
    _job(started)
    step, _, _ = _turn(client, started, header="Not/AZone")
    assert "04:50 UTC" in step["details"]
    assert client.get("/api/settings").json()["timeZone"] is None


def test_preflight_allows_the_time_zone_header():
    origin = settings.web_origins[0]
    r = TestClient(app).options("/api/chat/sessions/x/messages", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,x-time-zone"})
    assert r.status_code == 200 and "x-time-zone" in r.headers["access-control-allow-headers"].lower()


def test_rendering_helpers():
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    assert clock.fmt(AT, "Asia/Seoul", now) == "18 Oct 13:50 KST"
    assert clock.fmt(AT, None, now) == "18 Oct 04:50 UTC"
    assert clock.fmt(datetime(2025, 1, 2, 3, 4, tzinfo=timezone.utc), "UTC", now) == "2 Jan 2025 03:04 UTC"
    out = clock.localize({"at": AT, "s": "2026-10-18T04:50:00Z", "n": [str(AT)], "text": "at 2026-10-18 now"},
                         "Asia/Seoul")
    assert out["at"].endswith("13:50 KST") and out["s"].endswith("13:50 KST") and out["n"][0].endswith("13:50 KST")
    assert out["text"] == "at 2026-10-18 now"
    token = clock.ZONE.set("Asia/Seoul")
    try:
        assert notebook.written(AT, now=AT).startswith("18 Oct 13:50 KST")
    finally:
        clock.ZONE.reset(token)
