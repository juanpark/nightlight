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
        tx.set(tokens_ref().document(_sha(token)), {"uid": uid, "deviceId": device_id, "revoked": False,
                                                    "createdAt": firestore.SERVER_TIMESTAMP, "lastSeen": None})
        tx.set(db.device(uid, device_id), {
            "name": name, "kind": "computer", "purpose": "A real device reporting through the Nightlight helper.",
            "realm": "real", "simulated": False, "health": "unknown", "status": "offline", "vitals": {},
            "findings": [], "version": 1, "x": 420, "y": 80, "createdAt": firestore.SERVER_TIMESTAMP,
            "lastSeen": None})
        return uid

    db.run_transaction(run)
    return {"deviceId": device_id, "token": token}


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


def heartbeat(token: str, facts: dict) -> dict:
    tref = tokens_ref().document(_sha(token))
    facts, _ = scrub_value(facts)
    findings = checks(facts)
    severity = max((3 if f["severity"] == "crit" else 2 if f["severity"] == "warn" else 1 for f in findings),
                   default=0)
    status = "crit" if severity == 3 else "warn" if severity == 2 else "ok"
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
        if not dsnap.exists:
            raise ApiError(401, "invalid_token")
        device = dsnap.to_dict()
        tx.update(tref, {"lastSeen": _now()})
        tx.update(dref, {
            "os": facts.get("os"), "arch": facts.get("arch"), "status": status, "health": "verified",
            "vitals": {"cpu": facts.get("cpuPct"), "mem": facts.get("memPct"), "diskPct": facts.get("diskPct"),
                       "uptime": facts.get("uptimeSec")},
            "findings": findings, "lastSeen": firestore.SERVER_TIMESTAMP, "version": device.get("version", 1) + 1,
            "helperVersion": facts.get("helperVersion")})
        for ref in old:
            if ref.id not in services:
                tx.delete(ref)
        for svc_id, svc in services.items():
            tx.set(db.services(uid, device_id).document(svc_id), svc)
        return device_id

    device_id = db.run_transaction(run)
    return {"ok": True, "deviceId": device_id, "findings": len(findings)}


STALE_AFTER = timedelta(minutes=5)


def view(doc: dict, now: datetime | None = None) -> dict:
    """How a device should be presented: a real device that hasn't reported for 5 minutes is offline/unknown,
    whatever its last report said."""
    if doc.get("realm") != "real":
        return doc
    last = doc.get("lastSeen")
    if doc.get("revoked") or not last or (now or _now()) - last > STALE_AFTER:
        return {**doc, "status": "offline", "health": "unknown", "findings": [], "stale": True}
    return {**doc, "stale": False}


def is_current(doc: dict, generation: int) -> bool:
    """Real devices are always part of the home; simulated ones only in the current demo generation."""
    return doc.get("realm") == "real" or doc.get("demoGeneration") == generation


