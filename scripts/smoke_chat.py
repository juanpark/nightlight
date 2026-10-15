"""Live smoke test: one real question to Gemini through the API, against the Firestore emulator.

Run: firebase emulators:exec --only firestore --project demo-nightlight \
  "cd api && GOOGLE_CLOUD_PROJECT=demo-nightlight uv run python ../scripts/smoke_chat.py"
Gemini is reached through Application Default Credentials on the real project (GEMINI_PROJECT).
"""

import json
import os
import time
import uuid

os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "True")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

from fastapi.testclient import TestClient  # noqa: E402
from google import genai  # noqa: E402

from nightlight_api import agent as agentlib, demo  # noqa: E402
from nightlight_api.auth import current_uid  # noqa: E402
from nightlight_api.main import app  # noqa: E402

# Firestore stays on the emulator project; Gemini calls go to the real project.
agentlib._genai_client = genai.Client(project=os.environ.get("GEMINI_PROJECT", "nightlight-aibc"))
os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ.get("GEMINI_PROJECT", "nightlight-aibc")

uid = f"smoke_{uuid.uuid4().hex[:8]}"
demo.start(uid)
app.dependency_overrides[current_uid] = lambda: uid
c = TestClient(app)
sid = c.post("/api/chat/sessions", json={}).json()["sessionId"]


def run(path, body):
    t = time.monotonic()
    r = c.post(path, json=body)
    evs = [json.loads(b[5:]) for b in r.text.split("\n\n") if b.startswith("data:")]
    text = "".join(e.get("delta", "") for e in evs if e["type"] == "text")
    print(f"  {r.status_code} in {time.monotonic() - t:.1f}s: {[e['type'] for e in evs if e['type'] != 'text']}")
    print("  answer:", text)
    return evs


QUESTION = os.environ.get("SMOKE_QUESTION", "Is anything wrong at home?")
if os.environ.get("SMOKE_INJECT"):  # e.g. "server_lagging:game-1"
    kind, device = os.environ["SMOKE_INJECT"].split(":")
    print("inject:", c.post("/api/demo/inject", json={"kind": kind, "deviceId": device}).json())
print("Q:", QUESTION)
evs = run(f"/api/chat/sessions/{sid}/messages", {"text": QUESTION, "clientRequestId": str(uuid.uuid4())})
print("  metrics:", evs[-1].get("metrics"))
card = next((e["actionId"] for e in evs if e["type"] == "approval_request"), None)
if card:
    r = c.post(f"/api/actions/{card}/decide", json={"decision": "approve"})
    print("approve:", r.status_code, r.json())
    print("Continuation:")
    evs = run(f"/api/turns/{r.json()['continuationTurnId']}/stream", {})
    print("  metrics:", evs[-1].get("metrics"))
