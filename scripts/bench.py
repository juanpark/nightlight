"""Benchmark the demo story against real Gemini and write docs/BENCHMARKS.md.

Each run: start a fresh sample home, ask "Is anything wrong at home?", approve the proposed card, stream the
follow-up reply. Firestore is the local emulator; Gemini is the real model on Agent Platform.

Run: firebase emulators:exec --only firestore --project demo-nightlight \
  "cd api && GOOGLE_CLOUD_PROJECT=demo-nightlight uv run python ../scripts/bench.py 5"
"""

import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "True")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

from fastapi.testclient import TestClient  # noqa: E402
from google import genai  # noqa: E402

from nightlight_api import agent as agentlib, demo  # noqa: E402
from nightlight_api.auth import current_uid  # noqa: E402
from nightlight_api.config import settings  # noqa: E402
from nightlight_api.main import app  # noqa: E402

GEMINI_PROJECT = os.environ.get("GEMINI_PROJECT", "nightlight-aibc")
agentlib._genai_client = genai.Client(project=GEMINI_PROJECT)
os.environ["GOOGLE_CLOUD_PROJECT"] = GEMINI_PROJECT

RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
QUESTION = "Is anything wrong at home?"


def stream(client, path, body):
    t = time.monotonic()
    r = client.post(path, json=body)
    wall = (time.monotonic() - t) * 1000
    evs = [json.loads(b[5:]) for b in r.text.split("\n\n") if b.startswith("data:")]
    return r.status_code, evs, wall


rows, failures = [], []
for i in range(RUNS):
    uid = f"bench_{uuid.uuid4().hex[:8]}"
    demo.start(uid)
    app.dependency_overrides[current_uid] = lambda uid=uid: uid
    c = TestClient(app)
    sid = c.post("/api/chat/sessions", json={}).json()["sessionId"]
    code, evs, wall = stream(c, f"/api/chat/sessions/{sid}/messages",
                             {"text": QUESTION, "clientRequestId": str(uuid.uuid4())})
    done = evs[-1] if evs and evs[-1]["type"] == "done" else None
    card = next((e["actionId"] for e in evs if e["type"] == "approval_request"), None)
    if code != 200 or not done or not card:
        failures.append({"run": i, "step": "question", "status": code, "last": evs[-1] if evs else None})
        continue
    rows.append({"run": i, "step": "question", "wallMs": wall, **done["metrics"]})
    t = time.monotonic()
    d = c.post(f"/api/actions/{card}/decide", json={"decision": "approve"})
    approve_ms = (time.monotonic() - t) * 1000
    code, evs, wall = stream(c, f"/api/turns/{d.json()['continuationTurnId']}/stream", {})
    done = evs[-1] if evs and evs[-1]["type"] == "done" else None
    if code != 200 or not done:
        failures.append({"run": i, "step": "continuation", "status": code, "last": evs[-1] if evs else None})
        continue
    rows.append({"run": i, "step": "after approval", "wallMs": wall, "approveMs": approve_ms, **done["metrics"]})
    print(f"run {i}: ok", flush=True)


def stat(step, key, fn):
    vals = [r[key] for r in rows if r["step"] == step and r.get(key) is not None]
    return fn(vals) if vals else None


def p95(v):
    return sorted(v)[max(int(round(0.95 * len(v))) - 1, 0)]


now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
lines = [
    "# Benchmarks",
    "",
    f"Measured {now} with `scripts/bench.py`: {RUNS} runs of the demo story against the real model "
    f"(`{settings.model}`, thinking level {settings.thinking_level}, output cap {settings.max_output_tokens} tokens) "
    "on Google Agent Platform. Devices are the simulated sample home; Firestore was the local emulator, so network "
    "time to Firestore is not included. Prices: "
    f"${settings.price_in_per_m} / ${settings.price_out_per_m} per million input / output tokens (Agent Platform "
    "list price read 2026-10-16; thinking tokens bill as output).",
    "",
    f"Completed runs: {len({r['run'] for r in rows if r['step'] == 'after approval'})} of {RUNS}. "
    f"Failures: {len(failures)}.",
    "",
    "| Step | Median time to first words | Median full answer | 95th pct full answer | Model calls | Tool calls | "
    "Median cost |",
    "|---|---|---|---|---|---|---|",
]
for step in ("question", "after approval"):
    lines.append(
        f"| {step} | {stat(step, 'firstTextMs', statistics.median) or 0:.0f} ms | "
        f"{stat(step, 'latencyMs', statistics.median) or 0:.0f} ms | {stat(step, 'latencyMs', p95) or 0:.0f} ms | "
        f"{stat(step, 'modelCalls', statistics.median) or 0:.0f} | {stat(step, 'toolCalls', statistics.median) or 0:.0f} | "
        f"${stat(step, 'costUsd', statistics.median) or 0:.4f} |")
total = sum(r["costUsd"] for r in rows)
story = total / max(len({r['run'] for r in rows}), 1)
lines += [
    "",
    f"Whole story (question + approval + follow-up): about **${story:.4f}** per run. "
    f"Approve itself (one Firestore transaction): median {stat('after approval', 'approveMs', statistics.median) or 0:.0f} ms.",
    "",
    "Worst case per model call under the enforced limits (16,000 input tokens, 1,024 output+thinking tokens): "
    f"${settings.c_max:.5f}; the ${settings.model_budget_usd:.0f} model budget therefore admits at most "
    f"{int(settings.model_budget_usd // settings.c_max):,} model calls.",
    "",
    "## History",
    "",
    "| Date (UTC) | Setup | Question, median full answer | After approval | Story cost |",
    "|---|---|---|---|---|",
    "| 2026-10-15 18:39 | gemini-3.8-flash (low thinking); fleet listed by tool; follow-up with tools | 16.4 s (3 model "
    "calls) | 14.0 s (3 calls) | $0.0045 |",
    f"| {now} | {settings.model} ({settings.thinking_level.lower()} thinking); fleet summary in the instruction; "
    f"one-call follow-up | {(stat('question', 'latencyMs', statistics.median) or 0) / 1000:.1f} s | "
    f"{(stat('after approval', 'latencyMs', statistics.median) or 0) / 1000:.1f} s | ${story:.4f} |",
    "",
    "## Raw runs",
    "",
    "```json",
    json.dumps({"rows": rows, "failures": failures}, indent=1),
    "```",
]
out = Path(__file__).resolve().parent.parent / "docs" / "BENCHMARKS.md"
out.write_text("\n".join(lines) + "\n")
print("\n".join(lines[:16]))
