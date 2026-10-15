"""Redaction and input-bound unit tests (no emulator traffic needed)."""

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


def test_count_failure_fails_closed():
    def counter(req):
        raise RuntimeError("network")
    with pytest.raises(ApiError) as e:
        agentlib.bound_input(Req(10, 3000), counter=counter)
    assert e.value.code == "context_limit"


def test_unfittable_request_fails_closed():
    with pytest.raises(ApiError) as e:
        agentlib.bound_input(Req(1, 40000), counter=lambda r: 20000)
    assert e.value.code == "context_limit"
