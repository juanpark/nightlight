"""Real devices: enrolment, device tokens and heartbeats from the read-only helper.

A device joins with a one-time code its owner created in the app; it receives a random token that only it keeps (we
store a hash). Heartbeats carry an allowlisted set of health facts; deterministic checks turn them into findings.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import re

from . import db
from .errors import ApiError, not_found
from .ids import new_id
from .redact import scrub_value

CODE_TTL = timedelta(minutes=10)
CODES_PER_HOUR = 10
HEARTBEAT_MIN_SECONDS = 20
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no look-alikes (0/O, 1/I/L)
CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
TARGET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,99}$")  # a container or a system service (unit) name
CHAT_ACTIVE = timedelta(minutes=5)  # while the owner chats, helpers check for work every few seconds
FAST_POLL_SECONDS = 5
CLAIM_MIN_SECONDS = 4

# Jobs a real device can run. The helper has its own copy and runs only these, only on targets its owner allowed on
# that machine; the server sends a job name and a target, never a command.
JOBS = {"restart_container": {"label": "Restart a stopped container", "riskClass": "service"}}
# Read-only and owner-allowed per target on the device: no approval card. `logs` additionally lets the helper send the
# last log lines (scrubbed on the device); without it only structured status leaves the device.
READS = {"diagnose": {"label": "Look into", "riskClass": "read"}}
ALLOW_KEYS = ("restart_container", "diagnose", "logs")

# Plain names for system services people commonly run at home.
FRIENDLY = {
    "pihole-FTL": "Pi-hole ad blocker", "lighttpd": "web server", "docker": "Docker", "ssh": "remote login (SSH)",
    "sshd": "remote login (SSH)", "home-assistant": "Home Assistant", "homebridge": "Homebridge",
    "wg-quick@wg0": "WireGuard VPN", "smbd": "file sharing (Samba)", "nfs-server": "file sharing (NFS)",
    "cron": "scheduled jobs", "tailscaled": "Tailscale VPN", "zerotier-one": "ZeroTier VPN",
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def codes_ref():
    return db.client().collection("enrolCodes")


def tokens_ref():
    return db.client().collection("helperTokens")


# ------------------------------------------------------------------ enrolment

def create_code(uid: str) -> dict:
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    now = _now()
    hour = now.strftime("%Y%m%d%H")
    counter = db.user(uid).collection("quota").document(f"enrol_{hour}")

    @firestore.transactional
    def run(tx):
        user = db.user(uid).get(transaction=tx)
        c = counter.get(transaction=tx)
        if not user.exists:
            raise not_found()
        n = (c.to_dict() or {}).get("count", 0) if c.exists else 0
        if n >= CODES_PER_HOUR:
            raise ApiError(429, "quota_uid", retryAfter=3600 - now.minute * 60)
        tx.set(counter, {"count": n + 1})
        tx.set(codes_ref().document(_sha(code)), {"uid": uid, "expiresAt": now + CODE_TTL, "used": False,
                                                   "createdAt": firestore.SERVER_TIMESTAMP})

    db.run_transaction(run)
    return {"code": f"{code[:4]}-{code[4:]}", "expiresAt": (now + CODE_TTL).isoformat().replace("+00:00", "Z")}


def enrol(code: str, name: str) -> dict:
    """Redeem a one-time code exactly once; create the device and its token. The token is returned only here."""
    normalized = code.replace("-", "").strip().upper()
    ref = codes_ref().document(_sha(normalized))
    token = secrets.token_urlsafe(32)
    device_id = new_id("dev").lower()

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        data = snap.to_dict() if snap.exists else None
        if not data or data.get("used") or data["expiresAt"] < _now():
            raise ApiError(401, "invalid_code")  # unknown, used or expired look the same
        uid = data["uid"]
        tx.update(ref, {"used": True, "usedAt": firestore.SERVER_TIMESTAMP, "deviceId": device_id})
        _create_device(tx, uid, device_id, token, name)
        return uid

    db.run_transaction(run)
    return {"deviceId": device_id, "token": token}


def _create_device(tx, uid: str, device_id: str, token: str, name: str) -> None:
    """The device record and its token (stored hashed). Shared by enrolment and pairing."""
    event(tx, uid, device_id, "joined", "info", f"{name} joined your Nightlight map.", who="you")
    tx.set(db.client().collection("realDevices").document(f"{uid}__{device_id}"), {"uid": uid, "deviceId": device_id})
    tx.set(tokens_ref().document(_sha(token)), {"uid": uid, "deviceId": device_id, "revoked": False,
                                                "createdAt": firestore.SERVER_TIMESTAMP, "lastSeen": None})
    tx.set(db.device(uid, device_id), {
        "name": name, "kind": "computer", "purpose": "A real device reporting through the Nightlight helper.",
        "realm": "real", "simulated": False, "health": "unknown", "status": "offline", "vitals": {},
        "findings": [], "version": 1, "x": 420, "y": 80, "createdAt": firestore.SERVER_TIMESTAMP,
        "lastSeen": None, "registered": True})


# ------------------------------------------------------------------ pairing (the device shows a code)
# The OAuth device-authorization pattern: the device asks for a short code, the owner approves it in the app (typed
# or by scanning a QR with a phone), and the device, polling with a secret only it holds, then receives its token.
# The token is created at that moment and never stored in plaintext.

PAIR_TTL = timedelta(minutes=10)
PAIR_PER_IP_HOUR = 20
PAIR_CHECKS_PER_UID_HOUR = 30  # previews + decisions: guessing an 8-character code is hopeless at this rate
POLL_MIN_SECONDS = 2  # the device is told 3


def _count_check(uid: str) -> None:
    """Budget for looking up or deciding codes (RFC 8628 §5.1: limit guessing)."""
    now = _now()
    ref = db.user(uid).collection("quota").document(f"pair_{now.strftime('%Y%m%d%H')}")

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        n = (snap.to_dict() or {}).get("count", 0) if snap.exists else 0
        if n >= PAIR_CHECKS_PER_UID_HOUR:
            raise ApiError(429, "quota_uid", retryAfter=3600 - now.minute * 60)
        tx.set(ref, {"count": n + 1})

    db.run_transaction(run)


def pairs_ref():
    return db.client().collection("pairRequests")


def pair_start(name: str, os_name: str | None, ip: str) -> dict:
    now = _now()
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    poll_secret = secrets.token_urlsafe(32)
    bucket = db.client().collection("pairLimits").document(f"{_sha(ip)[:32]}_{now.strftime('%Y%m%d%H')}")

    @firestore.transactional
    def run(tx):
        b = bucket.get(transaction=tx)
        n = (b.to_dict() or {}).get("count", 0) if b.exists else 0
        if n >= PAIR_PER_IP_HOUR:
            raise ApiError(429, "quota_ip", retryAfter=3600 - now.minute * 60)
        tx.set(bucket, {"count": n + 1, "expiresAt": now + timedelta(hours=2)})
        tx.set(pairs_ref().document(_sha(code)), {"pollHash": _sha(poll_secret), "name": name, "os": os_name,
                                                   "status": "waiting", "uid": None, "expiresAt": now + PAIR_TTL,
                                                   "createdAt": firestore.SERVER_TIMESTAMP})

    db.run_transaction(run)
    return {"code": f"{code[:4]}-{code[4:]}", "pollSecret": poll_secret, "interval": 3,
            "expiresAt": (now + PAIR_TTL).isoformat().replace("+00:00", "Z")}


def _pair_doc(tx, code: str):
    ref = pairs_ref().document(_sha(code.replace("-", "").strip().upper()))
    snap = ref.get(transaction=tx) if tx is not None else ref.get()  # an empty transaction is falsy
    data = snap.to_dict() if snap.exists else None
    if not data or data["expiresAt"] < _now():
        return ref, None
    return ref, data


def pair_preview(uid: str, code: str) -> dict:
    _count_check(uid)
    _, data = _pair_doc(None, code)
    if not data or data["status"] != "waiting":
        raise not_found()
    return {"name": data["name"], "os": data.get("os"),
            "expiresAt": data["expiresAt"].isoformat().replace("+00:00", "Z")}


def pair_decide(uid: str, code: str, approve: bool) -> dict:
    _count_check(uid)

    @firestore.transactional
    def run(tx):
        ref, data = _pair_doc(tx, code)
        if not data:
            raise not_found()
        if data["status"] != "waiting":
            raise ApiError(409, "already_decided")
        tx.update(ref, {"status": "approved" if approve else "denied", "uid": uid if approve else None,
                        "decidedAt": firestore.SERVER_TIMESTAMP})

    db.run_transaction(run)
    return {"ok": True}


def pair_poll(code: str, poll_secret: str) -> tuple[int, dict]:
    token = secrets.token_urlsafe(32)
    device_id = new_id("dev").lower()

    @firestore.transactional
    def run(tx):
        ref, data = _pair_doc(tx, code)
        if not data or not secrets.compare_digest(data["pollHash"], _sha(poll_secret)) \
                or data["status"] in ("denied", "consumed"):
            raise ApiError(401, "invalid_code")  # unknown, expired, used, declined or not this device: all alike
        last = data.get("lastPollAt")
        if last and (_now() - last).total_seconds() < POLL_MIN_SECONDS:
            raise ApiError(429, "slow_down", retryAfter=POLL_MIN_SECONDS)
        if data["status"] == "waiting":
            tx.update(ref, {"lastPollAt": _now()})  # only the real device (right secret) gets here
            return 202, {"status": "waiting"}
        tx.update(ref, {"status": "consumed", "deviceId": device_id, "consumedAt": firestore.SERVER_TIMESTAMP})
        _create_device(tx, data["uid"], device_id, token, data["name"])
        return 200, {"deviceId": device_id, "token": token}

    return db.run_transaction(run)


def leave(token: str) -> dict:
    """The helper revokes its own token (on uninstall) and its device goes offline."""
    tref = tokens_ref().document(_sha(token))

    @firestore.transactional
    def run(tx):
        snap = tref.get(transaction=tx)
        t = snap.to_dict() if snap.exists else None
        if not t or t.get("revoked"):
            raise ApiError(401, "invalid_token")
        dref = db.device(t["uid"], t["deviceId"])
        dsnap = dref.get(transaction=tx)
        tx.update(tref, {"revoked": True, "revokedAt": firestore.SERVER_TIMESTAMP})
        if dsnap.exists:
            tx.update(dref, {"status": "offline", "health": "unknown", "revoked": True, "uninstalled": True})
            event(tx, t["uid"], t["deviceId"], "left", "info",
                  f"{dsnap.to_dict().get('name', 'A device')} was uninstalled and left your map.", who="device")

    db.run_transaction(run)
    return {"ok": True}


def revoke(uid: str, device_id: str) -> dict:
    """Revoke the device's token(s) and mark it offline, together, in one transaction."""
    query = tokens_ref().where(filter=FieldFilter("deviceId", "==", device_id))

    @firestore.transactional
    def run(tx):
        tokens = [t for t in query.get(transaction=tx) if t.to_dict().get("uid") == uid]
        dsnap = db.device(uid, device_id).get(transaction=tx)
        if not tokens or not dsnap.exists:
            raise not_found()
        for t in tokens:
            tx.update(t.reference, {"revoked": True, "revokedAt": firestore.SERVER_TIMESTAMP})
        tx.update(db.device(uid, device_id), {"status": "offline", "health": "unknown", "revoked": True})
        event(tx, uid, device_id, "revoked", "info",
              f"You removed {dsnap.to_dict().get('name', 'a device')}'s access.", who="you")

    db.run_transaction(run)
    return {"ok": True, "deviceId": device_id}


# ------------------------------------------------------------------ heartbeats

def _doc_id(name: str) -> str:
    """A safe Firestore document id for a container or unit name."""
    return (re.sub(r"[^A-Za-z0-9_.@-]", "_", name) or "unnamed")[:100]


def _friendly(unit: str) -> str:
    base = unit.removesuffix(".service")
    return FRIENDLY.get(base, base)


def checks(facts: dict) -> list[dict]:
    """Deterministic findings from real facts. The model explains these; it doesn't decide them."""
    out = []
    disk, mem = facts.get("diskPct"), facts.get("memPct")
    if disk is not None and disk >= 90:
        out.append({"id": "f_disk", "check": "disk_over_90", "severity": "crit",
                    "message": f"The disk is {disk:.0f}% full.", "evidence": f"/ at {disk:.0f}%"})
    elif disk is not None and disk >= 80:
        out.append({"id": "f_disk", "check": "disk_over_80", "severity": "warn",
                    "message": f"The disk is {disk:.0f}% full.", "evidence": f"/ at {disk:.0f}%"})
    if mem is not None and mem >= 90:
        out.append({"id": "f_mem", "check": "memory_high", "severity": "crit",
                    "message": f"Memory is {mem:.0f}% used.", "evidence": f"memory {mem:.0f}%"})
    for unit in facts.get("failedUnits") or []:
        out.append({"id": f"f_unit_{unit}", "check": "service_down", "severity": "warn",
                    "message": f"{_friendly(unit)} has stopped working.", "evidence": f"system service {unit}: failed",
                    "svcId": _doc_id(unit)})
    for c in facts.get("containers") or []:
        if c.get("state") not in ("running", None):
            out.append({"id": f"f_ctr_{c['name']}", "check": "container_down", "severity": "warn",
                        "message": f"{c['name']} isn't running.", "evidence": f"container state: {c.get('state')}",
                        "svcId": _doc_id(c["name"])})
    pending = facts.get("updatesPending")
    if pending:
        out.append({"id": "f_updates", "check": "updates_pending", "severity": "info",
                    "message": f"{pending} software updates are waiting.", "evidence": f"{pending} upgradable packages"})
    uptime = facts.get("uptimeSec")
    if uptime and uptime > 180 * 86400:
        weeks = int(uptime // (7 * 86400))
        out.append({"id": "f_uptime", "check": "restart_overdue", "severity": "info",
                    "message": f"It hasn't restarted in {weeks} weeks; some updates only take effect after a restart.",
                    "evidence": f"uptime {weeks} weeks"})
    return out


def service_for(params: dict) -> str | None:
    name = params.get("container")
    return _doc_id(name) if isinstance(name, str) else None


def card(device: dict, services: dict, action_type: str, params: dict) -> dict:
    """The approval card for a real-device job. ValueError when it doesn't apply, including when the device's owner
    hasn't allowed this job on this target on the device itself."""
    if action_type not in JOBS or set(params) != {"container"}:
        raise ValueError("not_applicable")
    name = params["container"]
    if not isinstance(name, str) or not CONTAINER_NAME.fullmatch(name):
        raise ValueError("bad_target")
    if name not in (device.get("allowedJobs") or {}).get(action_type, []):
        raise ValueError("not_allowed_on_device")
    svc = services.get(_doc_id(name))
    if not svc or svc.get("kind") != "container":
        raise ValueError("no_such_container")
    if svc.get("status") == "ok":
        raise ValueError("already_running")
    return {"svcId": _doc_id(name), "plan": f"Start the stopped {name} container again on the {device['name']}.",
            "dryRun": f"The helper on the device runs \"docker start {name}\" and checks it is still running a few "
                      f"seconds later. Nothing else is touched.",
            "rollback": f"Stop {name} again (from the app or with \"docker stop {name}\").",
            "blastRadius": [device["id"]], "riskClass": JOBS[action_type]["riskClass"]}


def heartbeat(token: str, facts: dict) -> dict:
    tref = tokens_ref().document(_sha(token))
    facts, _ = scrub_value(facts)
    findings = checks(facts)
    services = {}
    for c in facts.get("containers") or []:
        image = c.get("image") or ""
        services[_doc_id(c["name"])] = {"name": c["name"], "category": "containers", "kind": "container",
                               "status": "ok" if c.get("state") == "running" else "warn",
                               "version": image.rsplit(":", 1)[1] if ":" in image else None,
                               "detail": c.get("status"), "findings": []}
    for unit in facts.get("failedUnits") or []:
        services[_doc_id(unit)] = {"name": _friendly(unit), "category": "system", "kind": "system", "status": "warn",
                          "findings": [f for f in findings if f.get("svcId") == unit]}

    @firestore.transactional
    def run(tx):
        snap = tref.get(transaction=tx)
        t = snap.to_dict() if snap.exists else None
        if not t or t.get("revoked"):
            raise ApiError(401, "invalid_token")
        last = t.get("lastSeen")
        if last and (_now() - last).total_seconds() < HEARTBEAT_MIN_SECONDS:
            raise ApiError(429, "too_frequent", retryAfter=HEARTBEAT_MIN_SECONDS)
        uid, device_id = t["uid"], t["deviceId"]
        dref = db.device(uid, device_id)
        dsnap = dref.get(transaction=tx)
        old = [s.reference for s in db.services(uid, device_id).get(transaction=tx)]
        approved = db.actions(uid).where(filter=FieldFilter("deviceId", "==", device_id)).where(
            filter=FieldFilter("status", "==", "approved")).get(transaction=tx)
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        if not dsnap.exists:
            raise ApiError(401, "invalid_token")
        device = dsnap.to_dict()
        marked, states = apply_issue_states(findings, device.get("issueStates") or {})
        status = health_of(marked)
        previous = real_status(device)
        if previous != status:
            top = next((f for f in marked if f.get("state") == "new" and f["severity"] != "info"), None)
            words = {"ok": "is back to normal", "warn": "needs a look", "crit": "needs attention now"}[status]
            event(tx, uid, device_id, "status_" + status, status if status != "ok" else "info",
                  f"{device.get('name', 'A device')} {words}" + (f": {top['message']}" if top and status != "ok" else "."),
                  who="device")
        from .watch import history_point  # (watch imports this module)
        vitals = {"cpu": facts.get("cpuPct"), "mem": facts.get("memPct"), "diskPct": facts.get("diskPct"),
                  "uptime": facts.get("uptimeSec")}
        extra = history_point(tx, uid, device_id, device, vitals, status,
                              sum(1 for f in marked if f.get("state") == "new"))
        if not device.get("registered"):  # devices from before the sweep registry join it on their next report
            tx.set(db.client().collection("realDevices").document(f"{uid}__{device_id}"),
                   {"uid": uid, "deviceId": device_id})
            extra["registered"] = True
        if device.get("watchState") == "silent":
            extra["watchState"] = None
            event(tx, uid, device_id, "back", "info", f"{device.get('name', 'A device')} is reporting again.")
        tx.update(tref, {"lastSeen": _now()})
        tx.update(dref, {**extra,
            "os": facts.get("os"), "arch": facts.get("arch"), "status": status, "health": "verified",
            "vitals": {"cpu": facts.get("cpuPct"), "mem": facts.get("memPct"), "diskPct": facts.get("diskPct"),
                       "uptime": facts.get("uptimeSec")},
            "findings": marked, "issueStates": states, "lastSeen": firestore.SERVER_TIMESTAMP,
            "version": device.get("version", 1) + 1,
            "helperVersion": facts.get("helperVersion"), "allowedJobs": facts.get("allowedJobs") or {},
            "updatesPending": facts.get("updatesPending"), "containerCount": len(facts.get("containers") or []),
            "containersRunning": sum(1 for c in facts.get("containers") or [] if c.get("state") == "running")})
        for ref in old:
            if ref.id not in services:
                tx.delete(ref)
        for svc_id, svc in services.items():
            tx.set(db.services(uid, device_id).document(svc_id), svc)
        return device_id, _hand_over(tx, approved, user), _poll_every(user)

    device_id, jobs, poll = db.run_transaction(run)
    return {"ok": True, "deviceId": device_id, "findings": len(findings), "jobs": jobs, "pollEverySec": poll}


SEVERITY = {"info": 1, "warn": 2, "crit": 3}


def apply_issue_states(findings: list[dict], states: dict) -> tuple[list[dict], dict]:
    """Mark each finding new / known / snoozed. A known or snoozed problem comes back as new if it got worse (or a
    snooze ran out). States for problems that went away are dropped."""
    now, out, keep = _now(), [], {}
    for f in findings:
        s = states.get(f["id"])
        state = "new"
        if s:
            worse = SEVERITY[f["severity"]] > SEVERITY.get(s.get("severity"), 3)
            expired = s.get("until") and s["until"] < now
            if not worse and not expired:
                state = s["state"]
                keep[f["id"]] = s
        out.append({**f, "state": state})
    return out, keep


def health_of(findings: list[dict]) -> str:
    """The health light counts only problems that still need a look."""
    worst = max((SEVERITY[f["severity"]] for f in findings if f.get("state", "new") == "new"), default=0)
    return "crit" if worst == 3 else "warn" if worst == 2 else "ok"


def real_status(device: dict) -> str | None:
    return None if device.get("lastSeen") is None else device.get("status")


def event(tx, uid: str, device_id: str | None, kind: str, severity: str, message: str, who: str = "device") -> None:
    """One line in Activity about a real device (kept through demo resets: it has no demo generation)."""
    tx.set(db.events(uid).document(new_id("ev")), {"deviceId": device_id, "kind": kind, "severity": severity,
                                                   "message": message[:300], "who": who, "realm": "real",
                                                   "at": firestore.SERVER_TIMESTAMP})


def set_issue_state(uid: str, device_id: str, finding_id: str, state: str, days: int | None) -> dict:
    """The owner marks one problem: still needs a look (new), known (leaving it on purpose) or snoozed for N days."""
    ref = db.device(uid, device_id)

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or d.get("realm") != "real":
            raise not_found()
        f = next((x for x in d.get("findings") or [] if x.get("id") == finding_id), None)
        if not f:
            raise not_found()
        states = dict(d.get("issueStates") or {})
        if state == "new":
            states.pop(finding_id, None)
        else:
            states[finding_id] = {"state": state, "severity": f["severity"], "at": _now(),
                                  "until": _now() + timedelta(days=days) if state == "snoozed" and days else None}
        marked, states = apply_issue_states([{k: v for k, v in x.items() if k != "state"}
                                             for x in d.get("findings") or []], states)
        status = health_of(marked) if d.get("lastSeen") else d.get("status")
        tx.update(ref, {"issueStates": states, "findings": marked, "status": status})
        words = {"new": "needs a look again", "known": "is known (you're leaving it for now)",
                 "snoozed": f"is snoozed for {days} days"}[state]
        event(tx, uid, device_id, "issue_" + state, "info", f"{f['message']} {words}", who="you")
        return {"ok": True, "state": state, "status": status}

    return db.run_transaction(run)


def _hand_over(tx, approved, user: dict) -> list[dict]:
    """Approved jobs are handed over once (at most once: a job claimed here is never handed out again)."""
    ready = user.get("demo", {}).get("state") == "ready"
    jobs = []
    for a in approved:
        if not ready or a.get("demoGeneration") != user.get("demoGeneration"):
            continue  # a reset is withdrawing it (or has): never hand it out
        tx.update(a.reference, {"status": "running", "claimedAt": firestore.SERVER_TIMESTAMP})
        jobs.append({"id": a.id, "type": a.get("type"), "params": a.get("params")})
    return jobs


def _poll_every(user: dict) -> int:
    last = user.get("lastChatAt")
    return FAST_POLL_SECONDS if last and _now() - last < CHAT_ACTIVE else 0


def claim(token: str) -> dict:
    """A light check for approved work between reports (only used while the owner is chatting)."""
    tref = tokens_ref().document(_sha(token))

    @firestore.transactional
    def run(tx):
        snap = tref.get(transaction=tx)
        t = snap.to_dict() if snap.exists else None
        if not t or t.get("revoked"):
            raise ApiError(401, "invalid_token")
        last = t.get("lastClaimAt")
        if last and (_now() - last).total_seconds() < CLAIM_MIN_SECONDS:
            raise ApiError(429, "too_frequent", retryAfter=CLAIM_MIN_SECONDS)
        uid, device_id = t["uid"], t["deviceId"]
        approved = db.actions(uid).where(filter=FieldFilter("deviceId", "==", device_id)).where(
            filter=FieldFilter("status", "==", "approved")).get(transaction=tx)
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        tx.update(tref, {"lastClaimAt": _now()})
        return _hand_over(tx, approved, user), _poll_every(user)

    jobs, poll = db.run_transaction(run)
    return {"ok": True, "jobs": jobs, "pollEverySec": poll}


def diagnose_target_ok(device: dict, services: dict, target: str) -> None:
    """ValueError unless the owner allowed looking into this target on the device and the device reported it."""
    if not isinstance(target, str) or not TARGET_NAME.fullmatch(target):
        raise ValueError("bad_target")
    if target not in (device.get("allowedJobs") or {}).get("diagnose", []):
        raise ValueError("not_allowed_on_device")
    if _doc_id(target) not in services and _doc_id(target + ".service") not in services:
        raise ValueError("no_such_target")


def token_owner(tx, token: str) -> tuple[str, str]:
    """(uid, deviceId) for a live device token, read inside the caller's transaction; 401 otherwise."""
    snap = tokens_ref().document(_sha(token)).get(transaction=tx)
    t = snap.to_dict() if snap.exists else None
    if not t or t.get("revoked"):
        raise ApiError(401, "invalid_token")
    return t["uid"], t["deviceId"]


STALE_AFTER = timedelta(minutes=5)


def view(doc: dict, now: datetime | None = None) -> dict:
    """How a device should be presented: a real device that hasn't reported for 5 minutes is offline/unknown,
    whatever its last report said."""
    if doc.get("realm") != "real":
        return doc
    last = doc.get("lastSeen")
    reason = "revoked" if doc.get("revoked") else "no_report_yet" if not last else \
        "overdue" if (now or _now()) - last > STALE_AFTER else None
    if reason:
        return {**doc, "status": "offline", "health": "unknown", "findings": [], "stale": True, "staleReason": reason}
    return {**doc, "stale": False}


def is_current(doc: dict, generation: int) -> bool:
    """Real devices are always part of the home; simulated ones only in the current demo generation."""
    return doc.get("realm") == "real" or doc.get("demoGeneration") == generation


