"""A fixed, repeatable evaluation of the chat agent: cases grouped by bug class, each run N times, checked by
deterministic assertions on the stream events and the home's final state (plus an optional, clearly marked LLM judge).
It proves a whole class of bug is gone, not one instance, and measures how consistently.

Firestore is the local emulator (every run of every case gets a fresh sample home under its own user, the same
`demo.start` the probe and tests use); Gemini is the real model on Agent Platform.
Run: FIRESTORE_EMULATOR_HOST=127.0.0.1:8095 GOOGLE_CLOUD_PROJECT=demo-nightlight \
  uv run --directory api python ../scripts/chat_eval.py [--repeat 3] [--class stall,...] [--cases a,b] \
  [--out DIR] [--min-pass 0.66] [--workers 1] [--no-judge] [--cases-file FILE]

Exit code 1 if any class's pass rate (passed runs / runs) falls below --min-pass.

Use an emulator nobody else is testing against (the API tests flip ops/flags.killSwitch and contend for locks on a
shared one), e.g. java -jar ~/.cache/firebase/emulators/cloud-firestore-emulator-*.jar --host 127.0.0.1 --port 8096
and FIRESTORE_EMULATOR_HOST=127.0.0.1:8096. On a private emulator --workers 3 is fine.
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")  # ADK builds its own client: Agent Platform, not an API key
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

import yaml  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from nightlight_api import agent as agentlib, db, demo  # noqa: E402
from nightlight_api.auth import current_uid, owner_uid  # noqa: E402
from nightlight_api.config import settings  # noqa: E402
from nightlight_api.main import app  # noqa: E402

GEMINI_PROJECT = os.environ.get("GEMINI_PROJECT", "nightlight-aibc")
agentlib._genai_client = genai.Client(vertexai=True, project=GEMINI_PROJECT, location="global")
os.environ["GOOGLE_CLOUD_PROJECT"] = GEMINI_PROJECT
settings.model_calls_per_ip_hour = settings.model_calls_per_uid_hour = 10_000  # one test machine, many runs

# Each request names its own user, so runs can go in parallel against one app.
def _eval_uid(request: Request) -> str:
    return request.headers["x-eval-uid"]


app.dependency_overrides[current_uid] = app.dependency_overrides[owner_uid] = _eval_uid

NOT_RUN = {"pending", "denied", "stale"}
FLAGS = re.I | re.M

# ---------------------------------------------------------------- global invariants (on every step with a turn)
STALL = re.compile(r"^\s*(let me|i'?ll|i will|checking|one moment|give me a (moment|second))\b[^.!?\n]*[.!?…]?\s*\S{0,25}\s*$",
                   re.I)
CARD_CLAIM = re.compile(r"\b(i'?ve|i have|i'?ll|i will|i)\s+(just\s+)?(put|placed|set|posted|raised|added|opened)\s+(up\s+)?"
                        r"(a|an|the)\s+(\w+\s+){0,3}card|\bcard\s+(is|has been)\s+(up|ready|waiting)|"
                        r"카드를?\s*(올려|띄워)", re.I)
OFFER_Q = re.compile(r"\b(would you like|do you want|shall i|should i|want me to)\b[^?\n]{0,80}?\b(put up|propose|restart|"
                     r"clean|clear|remove|delete|back (it )?up|update|free|run|switch|go ahead|do (that|it|this))\b", re.I)


def invariants(step: dict, r: dict) -> list[dict]:
    out = []
    if r["status"] != 200 or r["errors"]:
        out.append({"check": "no_error", "ok": False, "why": f"HTTP {r['status']} errors {r['errors']}"})
    text = r["text"].strip()
    korean = _hangul_ratio(text) > 0.5
    stalled = not text or STALL.match(text) or len(text) < (12 if korean else 30)
    out.append({"check": "not_stall", "ok": not stalled, "why": f"answer: {text[:120]!r}" if stalled else ""})
    if CARD_CLAIM.search(text) and not r["cards"] and r["pending_after"] == 0:
        out.append({"check": "no_unbacked_card_claim", "ok": False, "why": "claims a card; none in step, none waiting"})
    if "ask" in step and not (step.get("expect") or {}).get("allow_offer_question"):
        m = OFFER_Q.search(text)
        if m and not r["cards"]:
            out.append({"check": "no_offer_instead_of_card", "ok": False, "why": f"asks {m.group(0)!r} with no card"})
    return out


def _hangul_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum("가" <= c <= "힣" for c in letters) / len(letters) if letters else 0.0


# ---------------------------------------------------------------- per-step expectations
def expectations(exp: dict, r: dict) -> list[dict]:
    out, text = [], r["text"]

    def add(name, ok, why=""):
        out.append({"check": name, "ok": bool(ok), "why": "" if ok else why})

    for rx in exp.get("text_re", []):
        add(f"text_re:{rx}", re.search(rx, text, FLAGS), "missing")
    if exp.get("text_any_re"):
        add("text_any_re", any(re.search(rx, text, FLAGS) for rx in exp["text_any_re"]),
            f"none of {exp['text_any_re']}")
    for rx in exp.get("text_not_re", []):
        m = re.search(rx, text, FLAGS)
        add(f"text_not_re:{rx}", not m, f"matched {m.group(0)!r}" if m else "")
    types_ = [c["type"] for c in r["cards"]]
    if "card" in exp:
        add("card" if exp["card"] else "no_card", bool(r["cards"]) == exp["card"], f"cards: {types_}")
    if "card_types" in exp:
        add("card_types", all(t in exp["card_types"] for t in types_), f"cards: {types_}")
    if "card_types_not" in exp:
        add("card_types_not", not any(t in exp["card_types_not"] for t in types_), f"cards: {types_}")
    if "card_device" in exp:
        devs = [c["deviceId"] for c in r["cards"]]
        add("card_device", all(d == exp["card_device"] for d in devs), f"devices: {devs}")
    if "first_card_type" in exp and r["cards"]:
        add("first_card_type", types_[0] == exp["first_card_type"], f"first card: {types_[0]}")
    if "pending_max" in exp:
        add("pending_max", r["pending_after"] <= exp["pending_max"], f"{r['pending_after']} pending")
    if "executed_max" in exp:
        add("executed_max", r["executed_after"] <= exp["executed_max"], f"{r['executed_after']} ran")
    tools = [t["name"] for t in r["tools"]]
    if "tools_any" in exp:
        add("tools_any", any(t in tools for t in exp["tools_any"]), f"tools: {tools}")
    for t in exp.get("tools_all", []):
        add(f"tools_all:{t}", t in tools, f"tools: {tools}")
    if "tools_none" in exp:
        add("tools_none", not any(t in exp["tools_none"] for t in tools), f"tools: {tools}")
    for tool, devs in (exp.get("tool_device_any") or {}).items():
        add(f"tool_device_any:{tool}", any(t["name"] == tool and (t["args"] or {}).get("device_id") in devs
                                            for t in r["tools"]), f"tools: {r['tools']}")
    if exp.get("hangul"):
        ratio = _hangul_ratio(text)
        add("hangul", ratio > 0.5, f"Korean share {ratio:.2f}")
    return out


# ---------------------------------------------------------------- optional LLM judge (clearly separate)
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", settings.model)
JUDGE_PROMPT = """You are a strict evaluator of one answer from a home-server assistant called Nightlight.
Apply ONLY the rubric. If the rubric's PASS condition is not clearly met, the verdict is FAIL.

RUBRIC: {rubric}

PERSON ASKED: {ask}

ASSISTANT'S STEPS (tools it called, with what they returned): {steps}

ASSISTANT ANSWERED: {answer}

Reply as JSON: {{"pass": true|false, "reason": "<one sentence>"}}"""


def judge(rubric: str, ask: str, r: dict) -> dict:
    steps = "; ".join(f"{t['name']}({json.dumps(t['args'], ensure_ascii=False)[:80]}) -> {t['result'][:160]}"
                      for t in r["tools"]) or "(none)"
    prompt = JUDGE_PROMPT.format(rubric=rubric, ask=ask, steps=steps, answer=r["text"] or "(empty)")
    try:
        resp = agentlib._genai_client.models.generate_content(
            model=JUDGE_MODEL, contents=prompt,
            config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"))
        u = resp.usage_metadata
        cost = ((u.prompt_token_count or 0) * settings.price_in_per_m
                + ((u.candidates_token_count or 0) + (u.thoughts_token_count or 0)) * settings.price_out_per_m) / 1e6
        v = json.loads(resp.text)
        return {"check": "LLM_JUDGE", "ok": bool(v.get("pass")), "why": v.get("reason", ""), "cost": cost}
    except Exception as e:  # a broken judge is a failed check, never a silent pass
        return {"check": "LLM_JUDGE", "ok": False, "why": f"judge error: {e}", "cost": 0.0}


# ---------------------------------------------------------------- running one case once
def stream(c: TestClient, path: str, body: dict, uid: str) -> dict:
    t = time.monotonic()
    resp = c.post(path, json=body, headers={"x-eval-uid": uid})
    wall = time.monotonic() - t
    evs = [json.loads(b[5:]) for b in resp.text.split("\n\n") if b.startswith("data:")]
    tools, pending_call = [], {}
    for e in evs:
        if e["type"] == "tool_call":
            pending_call = {"name": e["name"], "args": e.get("args") or {}, "result": ""}
            tools.append(pending_call)
        elif e["type"] == "tool_result" and pending_call:
            pending_call["result"] = (e.get("summary") or "") + ("" if e.get("ok", True) else " [FAILED]")
    card_ids = list(dict.fromkeys(e["actionId"] for e in evs if e["type"] == "approval_request"))
    cards = []
    for aid in card_ids:
        doc = db.action(uid, aid).get().to_dict() or {}
        cards.append({"id": aid, "type": doc.get("type"), "deviceId": doc.get("deviceId"), "status": doc.get("status")})
    m = next((e.get("metrics") or {} for e in evs if e["type"] == "done"), {})
    return {"status": resp.status_code, "wallS": round(wall, 2), "text": "".join(e.get("delta", "") for e in evs
                                                                              if e["type"] == "text"),
            "tools": tools, "cards": cards, "errors": [e for e in evs if e["type"] == "error"],
            "firstTextMs": m.get("firstTextMs"), "costUsd": m.get("costUsd") or 0.0}


def home_state(uid: str, seeded: set[str]) -> tuple[int, int]:
    """(pending cards, actions that ran) in this home, leaving out the finished jobs the sample history seeds."""
    statuses = [(s.to_dict() or {}).get("status") for s in db.actions(uid).stream() if s.id not in seeded]
    return sum(s == "pending" for s in statuses), sum(s not in NOT_RUN for s in statuses)


def run_case(name: str, case: dict, rep: int, use_judge: bool) -> dict:
    uid = f"eval_{uuid.uuid4().hex[:10]}"
    demo.start(uid)  # a fresh sample home, as the probe and tests do
    seeded = {s.id for s in db.actions(uid).stream()}  # the sample history's past jobs
    c = TestClient(app, client=(f"chat-eval-{uuid.uuid4().hex[:6]}", 50000))
    sid = c.post("/api/chat/sessions", json={}, headers={"x-eval-uid": uid}).json()["sessionId"]
    steps, last_cards, t0 = [], [], time.monotonic()
    for i, step in enumerate(case["steps"]):
        rec = {"i": i, "step": {k: v for k, v in step.items() if k != "expect"}, "checks": []}
        r = None
        if "inject" in step:
            kind, device = step["inject"].split(":")
            code = c.post("/api/demo/inject", json={"kind": kind, "deviceId": device},
                          headers={"x-eval-uid": uid}).status_code
            rec["checks"].append({"check": "inject", "ok": code == 201, "why": f"HTTP {code}"})
        elif "approve" in step or "deny" in step:
            if not last_cards:
                rec["checks"].append({"check": "decide", "ok": False, "why": "no card to decide"})
            else:
                body = {"decision": "approve"} if "approve" in step else \
                    {"decision": "deny", **({"note": step["note"]} if step.get("note") else {})}
                d = c.post(f"/api/actions/{last_cards[-1]['id']}/decide", json=body, headers={"x-eval-uid": uid}).json()
                rec["decided"] = {"status": d.get("status"), "code": d.get("code")}
                if d.get("continuationTurnId"):
                    r = stream(c, f"/api/turns/{d['continuationTurnId']}/stream", {}, uid)
                elif step.get("expect"):
                    rec["checks"].append({"check": "continuation", "ok": False, "why": f"no continuation: {d}"})
        else:
            r = stream(c, f"/api/chat/sessions/{sid}/messages",
                       {"text": step["ask"], "clientRequestId": str(uuid.uuid4()), "mode": step.get("mode", "quick")},
                       uid)
        if r is not None:
            r["pending_after"], r["executed_after"] = home_state(uid, seeded)
            if r["cards"]:
                last_cards = r["cards"]
            rec["result"] = r
            rec["checks"] += invariants(step, r) + expectations(step.get("expect") or {}, r)
            if use_judge and (step.get("expect") or {}).get("judge"):
                ask = step.get("ask") or f"({'approved' if 'approve' in step else 'declined'} the card"\
                                         f"{': ' + step['note'] if step.get('note') else ''})"
                rec["checks"].append(judge(step["expect"]["judge"], ask, r))
        steps.append(rec)
    failed = [f"step {s['i']}: {ch['check']} ({ch['why']})" for s in steps for ch in s["checks"] if not ch["ok"]]
    results = [s["result"] for s in steps if "result" in s]
    return {"case": name, "class": case["class"], "rep": rep, "uid": uid, "pass": not failed, "failed": failed,
            "totalS": round(sum(r["wallS"] for r in results), 2), "caseWallS": round(time.monotonic() - t0, 2),
            "firstTextMs": [r["firstTextMs"] for r in results],
            "costUsd": round(sum(r["costUsd"] for r in results), 6),
            "judgeCostUsd": round(sum(ch.get("cost", 0) for s in steps for ch in s["checks"]), 6), "steps": steps}


# ---------------------------------------------------------------- the suite
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases-file", default=str(Path(__file__).with_name("chat_eval_cases.yaml")))
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--class", dest="classes", default="", help="comma-separated classes to run")
    ap.add_argument("--cases", default="", help="comma-separated case names to run")
    ap.add_argument("--out", default="", help="directory for results JSON (default: no file)")
    ap.add_argument("--min-pass", type=float, default=0.66, help="minimum pass rate per class (0-1); 0.66 lets 2 of 3 pass")
    ap.add_argument("--workers", type=int, default=1, help="runs in parallel (1 on a shared emulator; 3 on a private one)")
    ap.add_argument("--no-judge", action="store_true", help="skip the optional LLM-judge checks")
    a = ap.parse_args()

    cases = yaml.safe_load(open(a.cases_file))["cases"]
    want_c = {x for x in a.classes.split(",") if x}
    want_n = {x for x in a.cases.split(",") if x}
    unknown = want_n - set(cases)
    if unknown:
        sys.exit(f"unknown cases: {sorted(unknown)}")
    chosen = {n: c for n, c in cases.items() if (not want_c or c["class"] in want_c) and (not want_n or n in want_n)}
    if not chosen:
        sys.exit("no cases selected")
    jobs = [(n, c, rep) for rep in range(a.repeat) for n, c in chosen.items()]
    print(f"{len(chosen)} cases x {a.repeat} = {len(jobs)} runs, {a.workers} at a time, model {settings.model}"
          f"{'' if a.no_judge else f', judge {JUDGE_MODEL}'}", flush=True)

    def one(job):
        n, c, rep = job
        try:
            out = run_case(n, c, rep, not a.no_judge)
        except Exception as e:  # a crashed run is a failed run
            out = {"case": n, "class": c["class"], "rep": rep, "pass": False, "failed": [f"crash: {e!r}"],
                   "totalS": None, "firstTextMs": [], "costUsd": 0.0, "judgeCostUsd": 0.0, "steps": []}
        print(f"  {'PASS' if out['pass'] else 'FAIL'} {n} #{rep + 1}"
              + ("" if out["pass"] else "  <- " + "; ".join(out["failed"])[:400]), flush=True)
        return out

    with ThreadPoolExecutor(max_workers=max(a.workers, 1)) as pool:
        runs = list(pool.map(one, jobs))

    rows, by_class = [], {}
    for n, c in chosen.items():
        rs = [r for r in runs if r["case"] == n]
        k = sum(r["pass"] for r in rs)
        totals = [r["totalS"] for r in rs if r["totalS"] is not None]
        firsts = [ms for r in rs for ms in r["firstTextMs"] if ms is not None]
        rows.append({"case": n, "class": c["class"], "passed": k, "runs": len(rs),
                     "medianTotalS": round(statistics.median(totals), 1) if totals else None,
                     "medianFirstWordsS": round(statistics.median(firsts) / 1000, 1) if firsts else None,
                     "costUsd": round(sum(r["costUsd"] for r in rs), 4),
                     "judgeCostUsd": round(sum(r["judgeCostUsd"] for r in rs), 4)})
        by_class.setdefault(c["class"], [0, 0])
        by_class[c["class"]][0] += k
        by_class[c["class"]][1] += len(rs)

    print(f"\n{'case':28} {'class':16} {'pass':>5} {'total s':>8} {'first s':>8} {'cost $':>8}")
    for r in sorted(rows, key=lambda r: (r["class"], r["case"])):
        print(f"{r['case']:28} {r['class']:16} {r['passed']}/{r['runs']:<3} {r['medianTotalS'] or '-':>8} "
              f"{r['medianFirstWordsS'] or '-':>8} {r['costUsd']:>8.4f}")
    print(f"\n{'class':16} {'pass':>7}  {'rate':>5}")
    below = []
    for cl, (k, nn) in sorted(by_class.items()):
        rate = k / nn
        if rate < a.min_pass:
            below.append(cl)
        print(f"{cl:16} {k:>3}/{nn:<3}  {rate:>5.0%}{'  BELOW' if rate < a.min_pass else ''}")
    agent_cost = sum(r["costUsd"] for r in rows)
    judge_cost = sum(r["judgeCostUsd"] for r in rows)
    print(f"\ncost: agent ${agent_cost:.4f} + judge ${judge_cost:.4f} = ${agent_cost + judge_cost:.4f}; "
          f"{sum(x[0] for x in by_class.values())}/{len(runs)} runs passed; classes below {a.min_pass:.0%}: "
          f"{', '.join(below) or 'none'}")

    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = out / f"chat_eval-{stamp}.json"
        path.write_text(json.dumps({"at": stamp, "model": settings.model, "deepModel": settings.deep_model,
                                    "judgeModel": None if a.no_judge else JUDGE_MODEL, "repeat": a.repeat,
                                    "minPass": a.min_pass, "summary": rows,
                                    "classes": {k: {"passed": v[0], "runs": v[1]} for k, v in by_class.items()},
                                    "below": below, "runs": runs}, ensure_ascii=False, indent=1, default=str))
        print(f"results: {path}")
    return 1 if below else 0


if __name__ == "__main__":
    sys.exit(main())
