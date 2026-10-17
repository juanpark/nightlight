"""Run the video's conversations against real Gemini and print what a viewer would see: each answer, the steps the
agent took (with what they found), cards, timings and cost. For judging answer quality before recording, not a test.

Firestore is the local emulator (a fresh sample home per scene); Gemini is the real model on Agent Platform.
Run: FIRESTORE_EMULATOR_HOST=localhost:8095 GOOGLE_CLOUD_PROJECT=demo-nightlight \
  uv run --directory api python ../scripts/demo_eval.py [scene ...]
"""

import json
import os
import sys
import time
import uuid

os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "True")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

from fastapi.testclient import TestClient  # noqa: E402
from google import genai  # noqa: E402

from nightlight_api import agent as agentlib, demo  # noqa: E402
from nightlight_api.auth import current_uid, owner_uid  # noqa: E402
from nightlight_api.main import app  # noqa: E402

agentlib._genai_client = genai.Client(project=os.environ.get("GEMINI_PROJECT", "nightlight-aibc"))
os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ.get("GEMINI_PROJECT", "nightlight-aibc")

# Each scene: optional incident to inject first, then turns. A turn is (mode, text); "approve" approves the last card.
SCENES = {
    "checkup": [("quick", "Is anything wrong at home?"), "approve"],
    "laggy": [("inject", "server_lagging:game-1"), ("quick", "My kids say Minecraft is laggy tonight. Can you help?"),
              "approve"],
    "backup": [("quick", "When was the Minecraft world last backed up?")],
    "deep": [("investigate", "The Raspberry Pi's disk keeps filling up. Find out why and what we can safely do.")],
    "router": [("quick", "What would stop working if the router went down tonight?")],
    "add": [("quick", "How do I add my own computer to Nightlight?")],
    "trust": [("quick", "What are you allowed to do without asking me?")],
}


def run(c, path, body):
    t = time.monotonic()
    r = c.post(path, json=body)
    evs = [json.loads(b[5:]) for b in r.text.split("\n\n") if b.startswith("data:")]
    wall = time.monotonic() - t
    text = "".join(e.get("delta", "") for e in evs if e["type"] == "text")
    for e in evs:
        if e["type"] == "tool_call":
            print(f"    → {e['name']} {json.dumps(e.get('args') or {}, ensure_ascii=False)[:140]}")
        elif e["type"] == "tool_result":
            ok = "" if e.get("ok", True) else " [FAILED]"
            print(f"      ← {(e.get('summary') or '')[:160]}{ok}")
        elif e["type"] == "approval_request":
            print(f"    [card {e['actionId']}]")
        elif e["type"] == "error":
            print(f"    !! error {e.get('code')}: {e.get('message')}")
    m = next((e.get("metrics") or {} for e in evs if e["type"] == "done"), {})
    print(f"  ({r.status_code}, {wall:.1f}s wall, first words {m.get('firstTextMs')} ms, {m.get('modelCalls')} model "
          f"calls, {m.get('toolCalls')} tool calls, ${m.get('costUsd')})")
    print("  ANSWER:", text.strip().replace("\n", "\n          "))
    return evs


def scene(name, steps):
    uid = f"eval_{uuid.uuid4().hex[:8]}"
    demo.start(uid)
    app.dependency_overrides[current_uid] = lambda: uid
    app.dependency_overrides[owner_uid] = lambda: uid
    c = TestClient(app)
    sid = c.post("/api/chat/sessions", json={}).json()["sessionId"]
    print(f"\n=== {name} ===")
    last = []
    for step in steps:
        if step == "approve":
            card = next((e["actionId"] for e in reversed(last) if e["type"] == "approval_request"), None)
            if not card:
                print("  (no card to approve)")
                continue
            d = c.post(f"/api/actions/{card}/decide", json={"decision": "approve"}).json()
            print(f"  APPROVED {card}: {d.get('status')}")
            if d.get("continuationTurnId"):
                last = run(c, f"/api/turns/{d['continuationTurnId']}/stream", {})
            continue
        mode, text = step
        if mode == "inject":
            kind, device = text.split(":")
            print("  inject:", c.post("/api/demo/inject", json={"kind": kind, "deviceId": device}).status_code)
            continue
        print(f"  Q [{mode}]: {text}")
        last = run(c, f"/api/chat/sessions/{sid}/messages",
                   {"text": text, "clientRequestId": str(uuid.uuid4()), "mode": mode})


for name in sys.argv[1:] or SCENES:
    scene(name, SCENES[name])
