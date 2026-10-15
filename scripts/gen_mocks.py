"""Generate the frontend mock fixtures in contracts/mocks/ from one consistent story.

Run from the repo root: python3 scripts/gen_mocks.py

Every phase directory is one coherent snapshot of the same demo user. The story:
  before_approval  (default) the Pi's disk is 94% full; the agent proposed log cleanup; the card is pending.
                   Two earlier cleanups were approved and succeeded.
  after_approval   the user approved: disk 61%, third success, a promotion offer appears, continuation reply done.
  auto_success     the user accepted the offer; the disk filled again; a new question ran cleanup automatically.
  auto_failed      same as auto_success, but the automatic cleanup failed: trust drops one step, offer cleared.
  resetting        the user pressed Reset: generation bumped, demo blocked until ready.
  after_reset      fresh sample home at the new generation; old cards remain only as hidden stale tombstones.
"""

import copy
import hashlib
import json
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "contracts" / "mocks"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_rng = random.Random(20261016)
T0 = datetime(2026, 10, 16, 15, 0, 0, tzinfo=timezone.utc)
UID = "uid_demo_01"
GEN = 3


def ts(minutes: float) -> str:
    t = T0 + timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def ulid(minutes: float) -> str:
    ms = int((T0 + timedelta(minutes=minutes)).timestamp() * 1000)
    time_part = "".join(CROCKFORD[(ms >> (5 * i)) & 31] for i in reversed(range(10)))
    return time_part + "".join(_rng.choice(CROCKFORD) for _ in range(16))


def uuid4() -> str:
    h = "%032x" % _rng.getrandbits(128)
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-{'89ab'[_rng.randrange(4)]}{h[17:20]}-{h[20:32]}"


def proposal(gen: int, turn_id: str, device: str, svc: str, kind: str, params: dict) -> tuple[str, str]:
    canon = json.dumps(params, sort_keys=True, separators=(",", ":"))
    key = hashlib.sha256(f"{gen}|{turn_id}|{device}|{svc}|{kind}|{canon}".encode()).hexdigest()
    return key, "act_" + key[:26]


# ---------------------------------------------------------------- fleet

def fleet(gen: int, pi_disk: int, pi_version: int) -> list[dict]:
    pi_status = "crit" if pi_disk >= 90 else "ok"
    disk_finding = [{
        "id": "f_disk_pi-1", "check": "disk_over_90", "severity": "crit",
        "message": f"The Pi's disk is {pi_disk}% full.",
        "evidence": f"/ at {pi_disk}% of 31 GB", "firstSeen": ts(100),
    }] if pi_disk >= 90 else []

    def device(id_, name, kind, os_, purpose, status, health, vitals, version, x, y, services, **extra):
        d = {
            "id": id_, "name": name, "kind": kind, "os": os_, "purpose": purpose, "status": status,
            "health": health, "vitals": vitals, "version": version, "lastSeen": ts(125),
            "simulated": True, "demoGeneration": gen, "x": x, "y": y,
        }
        d.update(extra)
        d["services"] = [dict(s, demoGeneration=gen) for s in services]
        return d

    return [
        device("pi-1", "Raspberry Pi", "pi", "Debian 12 (simulated)",
               "Runs your home VPN and your car's data logger.", pi_status, "verified",
               {"cpu": 18, "mem": 61, "diskPct": pi_disk, "uptime": 1209600}, pi_version, 120, 80,
               [{"id": "wireguard", "name": "WireGuard VPN", "status": "ok", "version": "1.0.20210914",
                 "updateAvailable": False, "findings": []},
                {"id": "teslamate", "name": "TeslaMate", "status": "warn" if pi_disk >= 90 else "ok",
                 "version": "1.29.2", "updateAvailable": True, "findings": disk_finding}],
               diskConsumers=[{"what": "old log files", "sizeGb": 2.1 if pi_disk >= 90 else 0.1},
                              {"what": "car logger database backup", "sizeGb": 1.4},
                              {"what": "unused Docker images", "sizeGb": 0.9}]),
        device("mac-1", "Mac Mini", "mac", "macOS 15 (simulated)", "Runs your home automation.", "ok", "verified",
               {"cpu": 9, "mem": 48, "diskPct": 52, "uptime": 604800}, 2, 320, 80,
               [{"id": "home-assistant", "name": "Home Assistant", "status": "ok", "version": "2026.10.1",
                 "updateAvailable": False, "findings": []}]),
        device("nas-1", "NAS", "nas", "NAS OS (simulated)", "Stores family photos and runs the nightly backup.",
               "warn", "verified", {"cpu": 4, "mem": 33, "diskPct": 71, "uptime": 2592000}, 4, 220, 220,
               [{"id": "nfs", "name": "Shared folder", "status": "ok", "version": "4.2", "updateAvailable": False,
                 "findings": []},
                {"id": "backup", "name": "Nightly backup", "status": "warn", "version": "n/a",
                 "updateAvailable": False,
                 "findings": [{"id": "f_backup_verify", "check": "backup_never_test_restored", "severity": "warn",
                               "message": "Backups run, but no one has checked that they can be restored.",
                               "evidence": "last test restore: never", "firstSeen": ts(0)}]}]),
        device("nvr-1", "Camera recorder", "camera", "Recorder firmware (simulated)", "Records the front-door camera.",
               "ok", "unknown", {"cpu": None, "mem": None, "diskPct": 63, "uptime": None}, 1, 420, 220, []),
        device("router-1", "Router", "router", "Router firmware (simulated)", "Connects everything to the internet.",
               "ok", "verified", {"cpu": 7, "mem": 40, "diskPct": None, "uptime": 5184000}, 1, 270, 360, []),
    ]


# ---------------------------------------------------------------- story building blocks

RISK = {"rotate_logs": "routine"}
ROLLBACK = ("Removed logs are moved to an archive for 24 hours (simulated). "
            "Restoring them is not available in this demo.")


class Story:
    def __init__(self, gen: int):
        self.gen = gen
        self.sessions: list[dict] = []
        self.actions: list[dict] = []
        self.events: list[dict] = []

    def session(self, minutes: float, title: str) -> dict:
        s = {"id": "sess_" + ulid(minutes), "title": title, "createdAt": ts(minutes), "demoGeneration": self.gen,
             "nextSeq": 1, "activeTurn": None, "lastTurnId": None, "messages": [], "turns": []}
        self.sessions.append(s)
        return s

    def message(self, s: dict, minutes: float, role: str, text: str, turn_id: str, **extra) -> dict:
        m = {"id": "msg_" + ulid(minutes), "role": role, "text": text, "seq": s["nextSeq"], "turnId": turn_id,
             "attempt": 1, "demoGeneration": self.gen, "createdAt": ts(minutes)}
        m.update(extra)
        s["nextSeq"] += 1
        s["messages"].append(m)
        return m

    def event(self, minutes: float, device: str, svc: str, kind: str, severity: str, message: str):
        self.events.append({"id": "ev_" + ulid(minutes), "deviceId": device, "svcId": svc, "kind": kind,
                            "severity": severity, "message": message, "at": ts(minutes), "source": "demo",
                            "demoGeneration": self.gen})

    def user_turn(self, s: dict, minutes: float, question: str, answer: str, metrics: dict,
                  action: dict | None = None, status: str = "done", tools: tuple = ("get_device",)) -> dict:
        crid = uuid4()
        turn_id = f"turn_{crid}"
        um = self.message(s, minutes, "user", question, turn_id)
        turn = {"id": turn_id, "kind": "user", "status": status, "attempt": 1, "demoGeneration": self.gen,
                "clientRequestId": crid, "textSha256": hashlib.sha256(question.encode()).hexdigest(),
                "userMessageId": um["id"], "createdAt": ts(minutes), "startedAt": ts(minutes + 0.01)}
        if status == "done":
            am = self.message(s, minutes + 0.05, "assistant", answer, turn_id,
                              toolCalls=[{"name": n, "args": {"device_id": "pi-1"}} for n in tools],
                              actionIds=[action["id"]] if action else [])
            turn.update(finalMessageId=am["id"], metrics=metrics, finishedAt=ts(minutes + 0.06))
        s["turns"].append(turn)
        s["lastTurnId"] = turn_id
        return turn

    def propose(self, s: dict, turn: dict, minutes: float, disk_from: int, device_version: int,
                trust_level: str) -> dict:
        key, aid = proposal(self.gen, turn["id"], "pi-1", "teslamate", "rotate_logs", {})
        a = {"id": aid, "proposalKey": key, "type": "rotate_logs", "deviceId": "pi-1", "svcId": "teslamate",
             "params": {}, "plan": "Compress and remove log files older than 7 days on the Pi.",
             "dryRun": f"Would free about 2.1 GB ({disk_from}% → 61% full). No running service is stopped.",
             "blastRadius": ["pi-1"], "rollback": ROLLBACK, "riskClass": RISK["rotate_logs"],
             "status": "pending", "demoGeneration": self.gen, "deviceVersion": device_version,
             "trustLevelAtProposal": trust_level,
             "resolvedBy": "trust/sim:rotate_logs" if trust_level != "ask" else "users.trustDefault",
             "realm": "sim", "sessionId": s["id"], "turnId": turn["id"], "turnAttempt": 1,
             "createdAt": ts(minutes)}
        self.actions.append(a)
        return a

    def decide(self, s: dict, a: dict, minutes: float, decision: str, ok: bool = True, disk_from: int = 94,
               cont_status: str = "done"):
        a["decision"] = {"by": "user", "decision": decision, "at": ts(minutes)}
        cont = f"cont_{a['id']}"
        if decision == "approve":
            a["status"] = "done" if ok else "failed"
            a["result"] = ({"ok": True, "summary": "Freed 2.1 GB on the Pi.", "before": {"diskPct": disk_from},
                            "after": {"diskPct": 61}} if ok else
                           {"ok": False, "summary": "The log folder was locked by another program, so nothing "
                                                    "was removed.", "before": {"diskPct": disk_from},
                            "after": {"diskPct": disk_from}})
        else:
            a["status"] = "denied"
        a["continuationTurnId"] = cont
        a["response"] = {"actionId": a["id"], "status": a["status"], "continuationTurnId": cont}
        a["finishedAt"] = ts(minutes)
        verb = {"approve": "approved", "deny": "declined"}[decision]
        self.message(s, minutes, "system", f"You {verb}: clean up old log files on the Pi.", cont,
                     actionIds=[a["id"]])
        reply = ("Done. The Pi is now 61% full and your car logger is recording normally." if decision == "approve" and ok
                 else "That didn't work: the log folder was locked, so nothing changed. I can try again later."
                 if decision == "approve" else "OK, I left the Pi as it is. The disk is still nearly full.")
        if cont_status == "queued":
            s["turns"].append({"id": cont, "kind": "continuation", "status": "queued", "attempt": 0,
                               "demoGeneration": self.gen, "actionId": a["id"], "createdAt": ts(minutes)})
            s["lastTurnId"] = cont
            return
        fm = self.message(s, minutes + 0.04, "assistant", reply, cont)
        s["turns"].append({"id": cont, "kind": "continuation", "status": "done", "attempt": 1,
                           "demoGeneration": self.gen, "actionId": a["id"], "finalMessageId": fm["id"],
                           "metrics": M_CONT, "createdAt": ts(minutes), "startedAt": ts(minutes + 0.01),
                           "finishedAt": ts(minutes + 0.05)})
        s["lastTurnId"] = cont

    def auto(self, a: dict, minutes: float, ok: bool, disk_from: int):
        a["status"] = "done" if ok else "failed"
        a["decision"] = {"by": "auto", "decision": "approve", "at": ts(minutes)}
        a["result"] = ({"ok": True, "summary": "Freed 2.1 GB on the Pi. Done automatically: you allowed this.",
                        "before": {"diskPct": disk_from}, "after": {"diskPct": 61}} if ok else
                       {"ok": False, "summary": "Tried to clean up logs automatically, but the log folder was "
                                                "locked. Nothing changed.",
                        "before": {"diskPct": disk_from}, "after": {"diskPct": disk_from}})
        a["finishedAt"] = ts(minutes)


M_USER = {"latencyMs": 3100, "firstTextMs": 900, "modelCalls": 2, "toolCalls": 1, "tokensIn": 5400,
          "tokensOut": 420, "tokensThinking": 180, "costUsd": 0.0063}
M_AUTO = {"latencyMs": 3600, "firstTextMs": 1700, "modelCalls": 3, "toolCalls": 2, "tokensIn": 7900,
          "tokensOut": 380, "tokensThinking": 210, "costUsd": 0.0084}
M_CONT = {"latencyMs": 2300, "firstTextMs": 1400, "modelCalls": 2, "toolCalls": 1, "tokensIn": 6100,
          "tokensOut": 60, "tokensThinking": 90, "costUsd": 0.0052}
ASK_ANSWER = ("The Pi's disk is {d}% full, mostly from old log files (2.1 GB). If it fills up, your car logger "
              "stops recording. I can clean up logs older than 7 days; that frees about 2.1 GB.")


def history(story: Story) -> list[str]:
    """Two earlier incidents, each approved and successful. Returns their action ids."""
    ids = []
    for i, start in enumerate((5, 45)):
        s = story.session(start, f"Pi disk full ({'first' if i == 0 else 'second'} time)")
        story.event(start - 1, "pi-1", "teslamate", "disk_full", "crit", "The Pi's disk is 93% full.")
        t = story.user_turn(s, start, "What's wrong with the Pi?", ASK_ANSWER.format(d=93), M_USER)
        a = story.propose(s, t, start + 0.05, 93, 3 + 2 * i, "ask")
        story.decide(s, a, start + 1, "approve", disk_from=93)
        ids.append(a["id"])
    return ids


def trust_doc(gen: int, level: str, successes: list[str], failures: int = 0, offer: dict | None = None) -> list[dict]:
    docs = [{"id": "sim:rotate_logs", "actionType": "rotate_logs", "label": "Clean up old log files",
             "level": level, "pinned": False, "ceiling": "auto", "riskClass": "routine",
             "successes": successes, "failures": failures, "demoGeneration": gen},
            {"id": "sim:disable_password_ssh", "actionType": "disable_password_ssh", "label": "Turn off password login",
             "level": "ask", "pinned": True, "ceiling": "ask", "riskClass": "destructive",
             "successes": [], "failures": 0, "demoGeneration": gen}]
    if offer:
        docs[0]["offer"] = offer
    return docs


def user_doc(gen: int, state: str = "ready", reset_op: str | None = None, lease: str | None = None) -> dict:
    return {"uid": UID, "createdAt": ts(0), "isDemo": True, "template": "home-pi", "demoGeneration": gen,
            "demo": {"state": state, "resetOpId": reset_op, "resetLeaseUntil": lease}, "trustDefault": "ask"}


def write(phase: str, **files):
    d = ROOT / "phases" / phase
    d.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (d / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def sse(name: str, events: list[dict], comment: str):
    d = ROOT / "sse"
    d.mkdir(parents=True, exist_ok=True)
    body = f": {comment}\n\n" + "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
    (d / f"{name}.txt").write_text(body)


def text_events(text: str) -> list[dict]:
    half = len(text) // 2
    cut = text.rfind(" ", 0, half) + 1 or half
    return [{"type": "text", "delta": text[:cut]}, {"type": "text", "delta": text[cut:]}]


# ---------------------------------------------------------------- phases

def main():
    if ROOT.exists():
        for p in ("phases", "sse"):
            shutil.rmtree(ROOT / p, ignore_errors=True)
        for f in ROOT.glob("*.json"):
            if f.name not in ("config.json", "errors.json"):
                f.unlink()
        (ROOT / "sse-sample.txt").unlink(missing_ok=True)

    # before_approval (default)
    st = Story(GEN)
    prior = history(st)
    s = st.session(100, "Pi disk full again")
    st.event(99, "pi-1", "teslamate", "disk_full", "crit", "The Pi's disk is 94% full.")
    t = st.user_turn(s, 100, "What's wrong with the Pi?", ASK_ANSWER.format(d=94), M_USER)
    current = st.propose(s, t, 100.05, 94, 7, "ask")
    s["messages"][-1]["actionIds"] = [current["id"]]
    before_snapshot = copy.deepcopy(st)
    write("before_approval", user=user_doc(GEN), devices=fleet(GEN, 94, 7), events=st.events,
          actions=st.actions, trust=trust_doc(GEN, "ask", prior), sessions=st.sessions)
    sse("before_approval_user_turn",
        [{"type": "turn_start", "turnId": t["id"], "attempt": 1, "messageId": t["userMessageId"], "at": t["createdAt"]},
         {"type": "tool_call", "name": "get_device", "args": {"device_id": "pi-1"}},
         {"type": "tool_result", "name": "get_device", "summary": "disk 94%, 2.1 GB of old logs", "redacted": 0},
         *text_events(ASK_ANSWER.format(d=94)),
         {"type": "approval_request", "actionId": current["id"]},
         {"type": "done", "turnId": t["id"], "metrics": M_USER}],
        f"POST /api/chat/sessions/{s['id']}/messages "
        f"{{\"text\":\"What's wrong with the Pi?\",\"clientRequestId\":\"{t['clientRequestId']}\"}}")
    sse("replay_finished_turn",
        [{"type": "turn_start", "turnId": t["id"], "attempt": 1, "messageId": t["userMessageId"],
          "at": t["createdAt"], "replay": True},
         {"type": "text", "delta": ASK_ANSWER.format(d=94)},
         {"type": "done", "turnId": t["id"], "metrics": M_USER}],
        "Same clientRequestId sent again after the turn finished: a short replay of the stored answer")

    # after_approval
    st.decide(s, current, 101, "approve")
    successes = prior + [current["id"]]
    offer = {"offerId": "offer_" + ulid(101.1), "demoGeneration": GEN, "successes": successes, "at": ts(101.1),
             "text": "Cleaning up old logs has gone well 3 times. Let me handle it on my own next time?"}
    cont = s["turns"][-1]
    write("after_approval", user=user_doc(GEN), devices=fleet(GEN, 61, 8), events=st.events, actions=st.actions,
          trust=trust_doc(GEN, "ask", successes, offer=offer), sessions=st.sessions,
          decide_response={"first_call_202": current["response"], "replay_200_same_body": current["response"]})
    sse("after_approval_continuation",
        [{"type": "turn_start", "turnId": cont["id"], "attempt": 1, "messageId": s["messages"][-2]["id"],
          "at": cont["createdAt"]},
         {"type": "tool_call", "name": "get_device", "args": {"device_id": "pi-1"}},
         {"type": "tool_result", "name": "get_device", "summary": "disk 61%", "redacted": 0},
         *text_events("Done. The Pi is now 61% full and your car logger is recording normally."),
         {"type": "done", "turnId": cont["id"], "metrics": M_CONT}],
        f"After POST /api/actions/{current['id']}/decide → 202, the browser opens "
        f"POST /api/turns/{cont['id']}/stream {{}}")

    # auto_success and auto_failed extend the after_approval story (same ids), after the offer is accepted
    after_story = copy.deepcopy(st)
    for ok in (True, False):
        st2 = copy.deepcopy(after_story)
        s3 = st2.session(160, "Pi disk full, handled automatically")
        st2.event(159, "pi-1", "teslamate", "disk_full", "crit", "The Pi's disk is 95% full.")
        answer = ("The Pi's disk was 95% full from old logs. You let me handle this on my own, so I cleaned up logs "
                  "older than 7 days: it's now 61% full." if ok else
                  "The Pi's disk is 95% full from old logs. I tried to clean them up automatically, as you allowed, "
                  "but the log folder was locked by another program, so nothing changed. I've switched this job "
                  "back to asking you for new things first.")
        t3 = st2.user_turn(s3, 160, "Why is the Pi red again?", answer, M_AUTO, tools=("get_device", "rotate_logs"))
        a3 = st2.propose(s3, t3, 160.03, 95, 9, "auto")
        st2.auto(a3, 160.03, ok, 95)
        s3["messages"][-1]["actionIds"] = [a3["id"]]
        # human-approved successes only; auto runs never count. Failure clears successes and demotes one step.
        level, trust_succ, fails = ("auto", list(successes), 0) if ok else ("ask_new", [], 1)
        name = "auto_success" if ok else "auto_failed"
        trust = trust_doc(GEN, level, trust_succ, fails)
        trust[0]["promotionAccepted"] = {"offerId": offer["offerId"], "at": ts(101.5)}
        write(name, user=user_doc(GEN), devices=fleet(GEN, 61 if ok else 95, 10 if ok else 9), events=st2.events,
              actions=st2.actions, trust=trust, sessions=st2.sessions)
        sse(f"{name}_user_turn",
            [{"type": "turn_start", "turnId": t3["id"], "attempt": 1, "messageId": t3["userMessageId"],
              "at": t3["createdAt"]},
             {"type": "tool_call", "name": "get_device", "args": {"device_id": "pi-1"}},
             {"type": "tool_result", "name": "get_device", "summary": "disk 95%, 2.1 GB of old logs", "redacted": 0},
             {"type": "tool_call", "name": "rotate_logs", "args": {"device_id": "pi-1"}},
             {"type": "tool_result", "name": "rotate_logs",
              "summary": "done automatically" if ok else "failed: log folder locked", "redacted": 0},
             *text_events(answer),
             {"type": "done", "turnId": t3["id"], "metrics": M_AUTO}],
            "Automatic action: no approval_request event and no continuation turn; the reply is in this turn")

    # resetting: generation bumped, demo blocked; listeners may still show older docs (hide them)
    write("resetting", user=user_doc(GEN + 1, "resetting", "reset_" + ulid(200), ts(201)),
          note={"ui": "Show a blocking 'Resetting the demo…' state until users/{uid}.demo.state is 'ready'. "
                      "Every demo write or chat answers 409 resetting meanwhile.",
                "error_409": {"error": "conflict", "code": "resetting", "retryAfter": 5}})
    sse("reset_mid_stream",
        [{"type": "turn_start", "turnId": f"turn_{uuid4()}", "attempt": 1, "messageId": "msg_" + ulid(199.9),
          "at": ts(199.9)},
         {"type": "text", "delta": "Let me check the backup on the NAS"},
         {"type": "error", "code": "stale", "message": "The demo was reset. Start a new question.",
          "retryable": False}],
        "The demo was reset while this turn was streaming: the stream ends with a terminal error")

    # after_reset: new generation, fresh template; old actions stay as stale tombstones (hidden by the filter)
    tomb = []
    for a in before_snapshot.actions:
        if a["status"] == "pending":
            tomb.append(dict(a, status="stale", finishedAt=ts(200.5)))
        else:
            tomb.append(a)
    write("after_reset", user=user_doc(GEN + 1), devices=fleet(GEN + 1, 94, 1), events=[], actions=tomb,
          trust=trust_doc(GEN + 1, "ask", []), sessions=[],
          note={"ui": "Show only actions whose demoGeneration equals users/{uid}.demoGeneration (4). "
                      "The listed actions are generation-3 leftovers, hidden by that filter. The card that was "
                      "still waiting when Reset was pressed is now status 'stale'; deciding it answers 409 stale.",
                "staleActionId": current["id"]})

    # gallery: every card state side by side (not one moment in time)
    gal = Story(GEN)
    gs = gal.session(300, "Gallery: every card state")
    states = []
    for i, kind in enumerate(("pending", "done", "denied", "failed", "auto_done", "auto_failed", "stale")):
        gt = gal.user_turn(gs, 300 + i, f"Example {i + 1}", ASK_ANSWER.format(d=94), M_USER)
        ga = gal.propose(gs, gt, 300 + i + 0.05, 94, 7, "auto" if kind.startswith("auto") else "ask")
        if kind == "done":
            gal.decide(gs, ga, 300 + i + 0.5, "approve")
        elif kind == "denied":
            gal.decide(gs, ga, 300 + i + 0.5, "deny")
        elif kind == "failed":
            gal.decide(gs, ga, 300 + i + 0.5, "approve", ok=False)
        elif kind.startswith("auto"):
            gal.auto(ga, 300 + i + 0.05, kind == "auto_done", 94)
        states.append(ga)
    old = Story(GEN - 1)
    os_ = old.session(299, "Old generation")
    ot = old.user_turn(os_, 299, "Example (old generation)", ASK_ANSWER.format(d=94), M_USER)
    oa = old.propose(os_, ot, 299.05, 94, 7, "ask")
    oa.update(status="stale", finishedAt=ts(299.5))
    states.append(oa)
    # turn states: queued continuation, running with an expired lease, failed
    ts_ = gal.session(320, "Gallery: turn states")
    qt = gal.user_turn(ts_, 320, "Clean up the Pi", ASK_ANSWER.format(d=94), M_USER)
    qa = gal.propose(ts_, qt, 320.05, 94, 7, "ask")
    gal.decide(ts_, qa, 320.5, "approve", cont_status="queued")
    states.append(qa)
    rt = gal.user_turn(ts_, 321, "Is my backup OK?", "", M_USER, status="running")
    rt["leaseUntil"] = ts(321.3)
    ts_["activeTurn"] = {"turnId": rt["id"], "attempt": 1, "leaseUntil": ts(321.3)}
    rt["_note"] = "lease expired: the UI calls POST /api/turns/{turnId}/stream to retry the same turn"
    ft = gal.user_turn(ts_, 322, "Check everything", "", M_USER, status="failed")
    ft.update(attempt=2, error={"code": "quota_global", "message": "Daily limit reached"}, finishedAt=ts(322.02))
    write("gallery", actions=states, sessions=gal.sessions + old.sessions,
          note={"purpose": "Every approval-card state and every turn state side by side for styling. "
                           "Not one moment in time."})

    (ROOT / "phases.json").write_text(json.dumps({
        "default": "before_approval",
        "order": ["before_approval", "after_approval", "auto_success", "auto_failed", "resetting", "after_reset"],
        "transitions": {
            "before_approval → after_approval": f"POST /api/actions/{current['id']}/decide {{\"decision\":\"approve\"}}",
            "after_approval → auto_success": "accept the promotion offer, inject disk_full, ask again (auto cleanup works)",
            "after_approval → auto_failed": "same, but the automatic cleanup fails: trust drops to ask_new",
            "any → resetting": "POST /api/demo/reset",
            "resetting → after_reset": "the server finishes the reset and sets demo.state = ready",
        },
        "sse": {"before_approval": "sse/before_approval_user_turn.txt",
                "after_approval": "sse/after_approval_continuation.txt",
                "auto_success": "sse/auto_success_user_turn.txt",
                "auto_failed": "sse/auto_failed_user_turn.txt",
                "resetting": "sse/reset_mid_stream.txt",
                "replay": "sse/replay_finished_turn.txt"},
    }, indent=2) + "\n")
    print("wrote", ROOT)


if __name__ == "__main__":
    main()
