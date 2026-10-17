"""Put conversations to the real agent and print exactly what a person would see: each answer, the steps it took (with
what they found), cards, errors, timings and cost. For testers probing answer quality; scenes come from a JSON file.

Firestore is the local emulator (a fresh sample home per scene); Gemini is the real model on Agent Platform.
Run: FIRESTORE_EMULATOR_HOST=localhost:8095 GOOGLE_CLOUD_PROJECT=demo-nightlight \
  uv run --directory api python ../scripts/chat_probe.py scenes.json [scene ...]

scenes.json: {"name": [step, ...]} where a step is {"ask": text, "mode": "quick"|"investigate"},
{"approve": true}, {"deny": true, "note": optional text}, or {"inject": "kind:deviceId"} (an incident, as in Demo tools).
"""

import json
import os
import sys
import time
import uuid

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")  # ADK builds its own client: Agent Platform, not an API key
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

from fastapi.testclient import TestClient
from google import genai

from nightlight_api import agent as agentlib, demo
from nightlight_api.auth import current_uid, owner_uid
from nightlight_api.config import settings
from nightlight_api.main import app

agentlib._genai_client = genai.Client(vertexai=True, project=os.environ.get("GEMINI_PROJECT", "nightlight-aibc"),
                                      location="global")
os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ.get("GEMINI_PROJECT", "nightlight-aibc")
settings.model_calls_per_ip_hour = settings.model_calls_per_uid_hour = 10_000  # one test machine, many scenes


def run(c, path, body):
    t = time.monotonic()
    r = c.post(path, json=body)
    evs = [json.loads(b[5:]) for b in r.text.split("\n\n") if b.startswith("data:")]
    text = "".join(e.get("delta", "") for e in evs if e["type"] == "text")
    for e in evs:
        if e["type"] == "tool_call":
            print(f"    -> {e['name']} {json.dumps(e.get('args') or {}, ensure_ascii=False)[:200]}")
        elif e["type"] == "tool_result":
            print(f"       <- {(e.get('summary') or '')[:240]}{'' if e.get('ok', True) else ' [FAILED]'}")
        elif e["type"] == "approval_request":
            print(f"    [CARD] {json.dumps({k: v for k, v in e.items() if k != 'type'}, ensure_ascii=False)[:600]}")
        elif e["type"] == "error":
            print(f"    !! error {e.get('code')}: {e.get('message')}")
    m = next((e.get("metrics") or {} for e in evs if e["type"] == "done"), {})
    print(f"  (HTTP {r.status_code}, {time.monotonic() - t:.1f}s, first words {m.get('firstTextMs')} ms, "
          f"{m.get('modelCalls')} model calls, {m.get('toolCalls')} tool calls, ${m.get('costUsd')})")
    print("  ANSWER:", text.strip().replace("\n", "\n          ") or "(no text)")
    return evs


def scene(name, steps):
    uid = f"probe_{uuid.uuid4().hex[:8]}"
    demo.start(uid)
    app.dependency_overrides[current_uid] = lambda: uid
    app.dependency_overrides[owner_uid] = lambda: uid
    c = TestClient(app)
    sid = c.post("/api/chat/sessions", json={}).json()["sessionId"]
    print(f"\n=== {name} ===")
    last = []
    for step in steps:
        if "approve" in step or "deny" in step:
            card = next((e["actionId"] for e in reversed(last) if e["type"] == "approval_request"), None)
            if not card:
                print("  (no card to decide)")
                continue
            body = {"decision": "approve"} if "approve" in step else \
                {"decision": "deny", **({"note": step["note"]} if step.get("note") else {})}
            d = c.post(f"/api/actions/{card}/decide", json=body).json()
            print(f"  {body['decision'].upper()} {card}: {d.get('status')} {d.get('code') or ''}")
            if d.get("continuationTurnId"):
                last = run(c, f"/api/turns/{d['continuationTurnId']}/stream", {})
        elif "inject" in step:
            kind, device = step["inject"].split(":")
            print("  inject:", kind, device, c.post("/api/demo/inject", json={"kind": kind, "deviceId": device}).status_code)
        else:
            mode = step.get("mode", "quick")
            print(f"  Q [{mode}]: {step['ask']}")
            last = run(c, f"/api/chat/sessions/{sid}/messages",
                       {"text": step["ask"], "clientRequestId": str(uuid.uuid4()), "mode": mode})


scenes = json.load(open(sys.argv[1]))
for name in sys.argv[2:] or scenes:
    scene(name, scenes[name])
