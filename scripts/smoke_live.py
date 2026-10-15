"""Live end-to-end check of the deployed API with a real Firebase one-click demo (anonymous) account.

Usage: uv run --with httpx python scripts/smoke_live.py <API_URL> <FIREBASE_WEB_API_KEY>
The web API key is public by design (it ships in every browser); pass it in, don't commit it.
"""

import json
import sys
import time
import uuid

import httpx

api, key = sys.argv[1].rstrip("/"), sys.argv[2]
token = httpx.post(f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={key}",
                   json={"returnSecureToken": True}).json()["idToken"]
h = {"Authorization": f"Bearer {token}"}
c = httpx.Client(base_url=api, headers=h, timeout=120)


def stream(path, body):
    t = time.monotonic()
    r = c.post(path, json=body)
    evs = [json.loads(b[5:]) for b in r.text.split("\n\n") if b.startswith("data:")]
    text = "".join(e.get("delta", "") for e in evs if e["type"] == "text")
    print(f"  {r.status_code} {time.monotonic() - t:.1f}s {[e['type'] for e in evs if e['type'] != 'text']}")
    print("  answer:", text.replace("\n", " "))
    return evs


print("start demo:", c.post("/api/demo/start", json={"template": "home-pi"}).json())
sid = c.post("/api/chat/sessions", json={}).json()["sessionId"]
print("question:")
evs = stream(f"/api/chat/sessions/{sid}/messages", {"text": "Is anything wrong at home?",
                                                    "clientRequestId": str(uuid.uuid4())})
print("  metrics:", evs[-1].get("metrics"))
card = next((e["actionId"] for e in evs if e["type"] == "approval_request"), None)
if card:
    d = c.post(f"/api/actions/{card}/decide", json={"decision": "approve"})
    print("approve:", d.status_code, d.json().get("status"))
    print("follow-up:")
    evs = stream(f"/api/turns/{d.json()['continuationTurnId']}/stream", {})
    print("  metrics:", evs[-1].get("metrics"))
print("reset:", c.post("/api/demo/reset", json={}).json())
if card:
    print("old card after reset:", c.post(f"/api/actions/{card}/decide", json={"decision": "approve"}).status_code)
