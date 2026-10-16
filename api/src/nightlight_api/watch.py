"""Keeping watch when nobody is looking: device history, devices that go silent, and watched web addresses.

A Cloud Scheduler job calls `POST /internal/sweep` every 5 minutes with a Google-signed identity token. The sweep
reads two small registries (real devices, watched addresses) instead of scanning every user.
"""

import ipaddress
import logging
import socket
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
from google.cloud import firestore

from . import db, real
from .errors import ApiError, not_found
from .ids import new_id
from .redact import scrub

log = logging.getLogger(__name__)

HISTORY_EVERY = timedelta(minutes=5)
HISTORY_KEEP = timedelta(days=8)
SILENT_AFTER = timedelta(minutes=5)
WATCHES_PER_USER = 10
CHECK_TIMEOUT = 5.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def registry():
    return db.client().collection("realDevices")


def watch_registry():
    return db.client().collection("watchRegistry")


def watches(uid: str):
    return db.user(uid).collection("watches")


# ------------------------------------------------------------------ history (written by the heartbeat)

def history_point(tx, uid: str, device_id: str, device: dict, vitals: dict, status: str, open_problems: int) -> dict:
    """At most one point per 5 minutes per device; each expires after 8 days (Firestore TTL on `expiresAt`).
    Returns the device fields to update."""
    last = device.get("historyAt")
    now = _now()
    if last and now - last < HISTORY_EVERY:
        return {}
    tx.set(db.device(uid, device_id).collection("history").document(now.strftime("%Y%m%dT%H%M%S")), {
        "at": now, "cpu": vitals.get("cpu"), "mem": vitals.get("mem"), "disk": vitals.get("diskPct"),
        "status": status, "problems": open_problems, "expiresAt": now + HISTORY_KEEP})
    return {"historyAt": now}


# ------------------------------------------------------------------ watched web addresses

def _public_url(url: str) -> str:
    """Only http(s) addresses that resolve to public internet addresses (no private, loopback or metadata ranges)."""
    u = urllib.parse.urlsplit(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ApiError(422, "bad_url")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except OSError:
        raise ApiError(422, "unknown_host") from None
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ApiError(422, "private_address")  # those are watched by a helper at home, not from the cloud
    return urllib.parse.urlunsplit((u.scheme, u.netloc.lower(), u.path or "/", u.query, ""))


def add_watch(uid: str, name: str, url: str, tags: list[str]) -> dict:
    clean = _public_url(url)
    wid = new_id("w").lower()

    @firestore.transactional
    def run(tx):
        existing = list(watches(uid).limit(WATCHES_PER_USER + 1).get(transaction=tx))
        if len(existing) >= WATCHES_PER_USER:
            raise ApiError(429, "too_many_watches")
        tx.set(watches(uid).document(wid), {"name": scrub(name)[0], "url": clean, "tags": tags, "status": "unknown",
                                            "createdAt": firestore.SERVER_TIMESTAMP, "lastCheckedAt": None})
        tx.set(watch_registry().document(f"{uid}__{wid}"), {"uid": uid, "watchId": wid})

    db.run_transaction(run)
    check_one(uid, wid)
    return {"id": wid, "url": clean}


def remove_watch(uid: str, wid: str) -> dict:
    ref = watches(uid).document(wid)
    if not ref.get().exists:
        raise not_found()
    ref.delete()
    watch_registry().document(f"{uid}__{wid}").delete()
    return {"ok": True}


def _probe(url: str) -> tuple[str, int | None, int | None]:
    """(status, http code, milliseconds). Up = any answer below 500 (redirects not followed). Only the outcome is
    kept, never the page."""
    try:
        _public_url(url)  # re-checked each time: a name can start pointing somewhere private later
    except ApiError:
        return "crit", None, None
    t = time.monotonic()
    try:
        r = httpx.get(url, timeout=CHECK_TIMEOUT, follow_redirects=False,
                      headers={"User-Agent": "Nightlight-uptime-check"})
        ms = int((time.monotonic() - t) * 1000)
        return ("ok" if r.status_code < 500 else "crit"), r.status_code, ms
    except httpx.HTTPError:
        return "crit", None, None


def check_one(uid: str, wid: str) -> None:
    ref = watches(uid).document(wid)
    snap = ref.get()
    if not snap.exists:
        return
    w = snap.to_dict()
    status, code, ms = _probe(w["url"])

    @firestore.transactional
    def run(tx):
        cur = ref.get(transaction=tx).to_dict() or {}
        update = {"status": status, "httpStatus": code, "latencyMs": ms, "lastCheckedAt": _now()}
        if cur.get("status") not in (None, "unknown") and cur.get("status") != status:
            update["lastChange"] = _now()
            words = "is back up" if status == "ok" else "isn't answering"
            real.event(tx, uid, None, "watch_" + status, "info" if status == "ok" else "crit",
                       f"{cur.get('name', 'A watched address')} {words}.", who="nightlight")
        tx.update(ref, update)

    db.run_transaction(run)


# ------------------------------------------------------------------ the sweep

def _mark_silent(uid: str, device_id: str) -> bool:
    ref = db.device(uid, device_id)

    @firestore.transactional
    def run(tx):
        d = ref.get(transaction=tx).to_dict()
        if not d or d.get("revoked") or d.get("watchState") == "silent" or not d.get("lastSeen"):
            return False
        if _now() - d["lastSeen"] < SILENT_AFTER:
            return False
        tx.update(ref, {"watchState": "silent"})
        real.event(tx, uid, device_id, "silent", "warn",
                   f"{d.get('name', 'A device')} stopped reporting (last report "
                   f"{int((_now() - d['lastSeen']).total_seconds() // 60)} minutes ago).", who="nightlight")
        return True

    return db.run_transaction(run)


def sweep() -> dict:
    silent = checked = 0
    for r in registry().stream():
        d = r.to_dict()
        try:
            silent += _mark_silent(d["uid"], d["deviceId"])
        except Exception as e:  # one bad record never stops the sweep
            log.warning("sweep device failed: %s", type(e).__name__)
    for r in watch_registry().stream():
        d = r.to_dict()
        try:
            check_one(d["uid"], d["watchId"])
            checked += 1
        except Exception as e:
            log.warning("sweep watch failed: %s", type(e).__name__)
    return {"ok": True, "newlySilent": silent, "watchesChecked": checked}
