"""Redaction and input-bound unit tests (no emulator traffic needed)."""

import json

import pytest
from google.genai import types

from nightlight_api import agent as agentlib
from nightlight_api.errors import ApiError
from nightlight_api.redact import scrub, scrub_value

# Secret-shaped test values are assembled at runtime so the repository never contains anything that looks like a
# real credential (secret scanners and reviewers would rightly flag it). None of these are real keys.
_DASH = "-" * 5
_KIND = "OPENSSH " + "PRIVATE KEY"
PEM = f"{_DASH}BEGIN {_KIND}{_DASH}\n" + "Q" * 40 + "\n" + "R" * 24 + f"\n{_DASH}END {_KIND}{_DASH}"
WG = "Z" * 7 + "fake" + "Y" * 32 + "="          # 43 base64 chars + "=", the shape of a WireGuard key
AWS = "AKIA" + "FAKE" * 4                       # access-key-id shape
GH = "ghp_" + "Fake" * 9                        # GitHub token shape
GKEY = "AI" + "za" + "Fake" * 8 + "abc"         # Google API key shape (39 chars)


@pytest.mark.parametrize("text,leak", [
    (PEM, "Q" * 40),
    (f"PrivateKey = {WG}", WG),
    ("password=correct-horse user=pi", "correct-horse"),
    ('DB_PASSWORD: "s3cr3t value"', "s3cr3t"),
    ("Authorization: Bearer abcdefghijklmnop123", "abcdefghijklmnop123"),
    (f"export AWS_ACCESS_KEY_ID={AWS}", AWS),
    (f"token {GH}", GH),
    ("mqtt://homeassistant:pa55word@broker.local:1883", "pa55word"),
    ("contact owner@example.com about the NAS", "owner@example.com"),
    (f"key {GKEY}", GKEY),
])
def test_scrub_hides_secrets(text, leak):
    clean, n = scrub(text)
    assert leak not in clean and n >= 1


@pytest.mark.parametrize("text", [
    "The Pi's disk is 94% full; 2.1 GB of logs in /var/log since 2026-10-01.",
    "Remote login with a password is on. Here's a safer setting.",
    "Turn off password login and use a key instead.",
])
def test_scrub_keeps_ordinary_text(text):
    assert scrub(text) == (text, 0)


def test_scrub_value_walks_nested():
    clean, n = scrub_value({"a": ["password=x1", {"b": "fine"}]})
    assert clean == {"a": ["password=[hidden]", {"b": "fine"}]} and n == 1


class Req:
    def __init__(self, n_messages, size):
        self.contents = [types.Content(role="user" if i % 2 == 0 else "model", parts=[types.Part(text="x" * size)])
                         for i in range(n_messages)]
        self.config = types.GenerateContentConfig(system_instruction="sys")


def test_every_request_is_counted_exactly():
    seen = []
    agentlib.bound_input(Req(2, 100), counter=lambda r: seen.append(1) or 50)
    assert seen == [1]  # no shortcut: even a tiny request is counted by the model's own tokenizer


def test_large_request_is_counted_and_trimmed():
    req = Req(10, 3000)  # ~30 KB serialised
    agentlib.bound_input(req, counter=lambda r: len(r.contents) * 3000)
    assert len(req.contents) <= 5


def test_count_failure_fails_closed_after_one_retry(monkeypatch):
    monkeypatch.setattr(agentlib, "COUNT_RETRY_SECONDS", 0)
    tries = []

    def counter(req):
        tries.append(1)
        raise RuntimeError("network")
    with pytest.raises(ApiError) as e:
        agentlib.bound_input(Req(10, 3000), counter=counter)
    assert e.value.code == "size_check_failed" and len(tries) == 2  # asked again once, then refused honestly


def test_transient_count_failure_is_retried(monkeypatch):
    monkeypatch.setattr(agentlib, "COUNT_RETRY_SECONDS", 0)
    tries = []

    def counter(req):
        tries.append(1)
        if len(tries) == 1:
            raise type("Busy", (Exception,), {"code": 429})("RESOURCE_EXHAUSTED")
        return 50
    agentlib.bound_input(Req(2, 100), counter=counter)
    assert len(tries) == 2


def test_permanent_count_failure_is_not_retried(monkeypatch):
    monkeypatch.setattr(agentlib, "COUNT_RETRY_SECONDS", 0)
    tries = []

    def counter(req):
        tries.append(1)
        raise type("Bad", (Exception,), {"code": 400})("INVALID_ARGUMENT")
    with pytest.raises(ApiError) as e:
        agentlib.bound_input(Req(2, 100), counter=counter)
    assert e.value.code == "size_check_failed" and len(tries) == 1


def _investigation(steps: int, history: int = 4):
    """The 18 Oct failure shape: some chat, the current question, then many steps with large outputs (log tails)."""
    contents = [types.Content(role="user" if i % 2 == 0 else "model", parts=[types.Part(text="earlier chat " * 40)])
                for i in range(history)]
    contents.append(types.Content(role="user", parts=[types.Part(text="what else is using port 53?")]))
    for i in range(steps):
        log = "\n".join([f"Oct 18 08:0{i % 10}:{n:02d} pi systemd-resolved[412]: query {n} ok" for n in range(50)]
                        + ["Oct 18 08:01:00 pi dnsmasq[900]: failed to create listening socket for port 53"])
        contents.append(types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
            id=f"c{i}", name="run_command", args={"command": f"journalctl -n 50 #{i}"}))]))
        contents.append(types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=f"c{i}", name="run_command", response={"status": "ok", "exitCode": 0, "output": log[:3900]}))]))
    return type("R", (), {"contents": contents, "config": types.GenerateContentConfig(system_instruction="sys")})()


def _approx_count(req) -> int:  # ~4 bytes a token over everything sent, plus the measured fixed part (4.3k)
    return 4300 + len(json.dumps([c.model_dump(mode="json", exclude_none=True) for c in req.contents])) // 4


def test_long_investigation_shortens_older_results_instead_of_failing():
    req = _investigation(steps=20)
    originals = list(req.contents)
    original_newest = req.contents[-1].parts[0].function_response.response
    assert _approx_count(req) > 16000  # what failed in production: the turn's own steps alone exceed the ceiling
    agentlib.bound_input(req, counter=_approx_count, limit=16000)
    assert _approx_count(req) <= 16000
    calls = [p.function_call.id for c in req.contents for p in c.parts if p.function_call]
    resps = [p.function_response for c in req.contents for p in c.parts if p.function_response]
    assert calls == [r.id for r in resps] == [f"c{i}" for i in range(20)]  # every call keeps its response, in order
    assert resps[-1].response == original_newest  # the newest step is whole
    short = [r.response for r in resps if "shortenedEarlier" in r.response]
    assert short and resps[0].response in short
    first = short[0]
    assert first["status"] == "ok" and first["exitCode"] == 0 and "shortened" in first["shortenedEarlier"]
    assert any("failed to create listening socket" in line for line in first["keyLines"])  # key lines survive
    assert any("dnsmasq" in line for line in first.get("keyLines", []))
    # The session's own record is untouched: shortening replaced contents in the request, never edited them.
    assert all("shortenedEarlier" not in p.function_response.response
               for c in originals for p in c.parts if p.function_response)
    assert any(c.parts[0].text and "port 53" in c.parts[0].text for c in req.contents)  # the question stays


def test_shortening_comes_before_dropping_chat_history():
    req = _investigation(steps=16)
    agentlib.bound_input(req, counter=_approx_count, limit=16000)
    assert req.contents[0].parts[0].text.startswith("earlier chat")  # history kept while shortening was enough


def test_bound_input_reports_what_it_left_out():
    req = Req(10, 3000)
    assert agentlib.bound_input(req, counter=lambda r: len(r.contents) * 3000) == {"shortened": False,
                                                                                    "trimmed": True}
    assert agentlib.bound_input(Req(2, 100), counter=lambda r: 50) == {"shortened": False, "trimmed": False}
    done = agentlib.bound_input(_investigation(steps=16), counter=_approx_count, limit=16000)
    assert done == {"shortened": True, "trimmed": False}


def test_reductions_are_on_the_receipt_even_when_the_turn_then_fails(monkeypatch):
    monkeypatch.setattr(agentlib, "COUNT_RETRY_SECONDS", 0)
    metrics, calls = {}, []

    def counter(r):  # over the limit once (history is dropped), then the counter breaks for good
        calls.append(1)
        if len(calls) == 1:
            return 99999
        raise RuntimeError("network")
    with pytest.raises(ApiError) as e:
        agentlib.bound_input(Req(10, 3000), counter=counter, metrics=metrics)
    assert e.value.code == "size_check_failed" and metrics == {"longChat": True}

    metrics = {}
    with pytest.raises(ApiError) as e:  # never fits: everything older shortened and dropped, then refused
        agentlib.bound_input(_investigation(steps=16), counter=lambda r: 99999, limit=16000, metrics=metrics)
    assert e.value.code == "context_limit" and metrics == {"stepsShortened": True, "longChat": True}


def test_unfittable_request_fails_closed():
    with pytest.raises(ApiError) as e:
        agentlib.bound_input(Req(1, 40000), counter=lambda r: 20000)
    assert e.value.code == "context_limit"
