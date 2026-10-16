"""Keeping watch when nobody is looking: device history, devices that go silent, and watched web addresses.

A Cloud Scheduler job calls `POST /internal/sweep` every 5 minutes with a Google-signed identity token. The sweep
reads two small registries (real devices, watched addresses) instead of scanning every user.
"""

import asyncio
import concurrent.futures
import ipaddress
import threading
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
WATCHES_TOTAL = 200  # across everyone: bounds the scheduled work whatever happens
WATCH_ADDS_PER_DAY = 20  # per account, including removals and re-adds
WATCH_LIFETIME = timedelta(days=30)  # a watch retires after 30 days (re-add it to keep it)
CHECK_TIMEOUT = 3.0
PROBE_BUDGET = 6.0  # seconds for one whole check, connection to headers
SWEEP_BUDGET = 50.0  # seconds for one sweep (the scheduler allows 120)
_TRANSPORT = None  # tests replace the network


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

def _resolve(url: str) -> tuple[urllib.parse.SplitResult, int, str]:
    """(parts, port, one validated public IP). Every address the name resolves to must be public."""
    try:
        u = urllib.parse.urlsplit(url.strip())
        port = u.port or (443 if u.scheme == "https" else 80)
    except ValueError:
        raise ApiError(422, "bad_url") from None
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ApiError(422, "bad_url")
    try:
        infos = socket.getaddrinfo(u.hostname, port, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        raise ApiError(422, "unknown_host") from None
    ips = [info[4][0] for info in infos]
    if not ips or not all(ipaddress.ip_address(ip).is_global for ip in ips):
        raise ApiError(422, "private_address")  # those are watched by a helper at home, not from the cloud
    return u, port, ips[0]


def _public_url(url: str) -> str:
    u, _, _ = _resolve(url)
    return urllib.parse.urlunsplit((u.scheme, u.netloc.lower(), u.path or "/", u.query, ""))


def add_watch(uid: str, name: str, url: str, tags: list[str]) -> dict:
    clean = _public_url(url)
    wid = new_id("w").lower()
    now = _now()
    budget = db.user(uid).collection("quota").document(f"watch_{now.strftime('%Y%m%d')}")
    total = db.client().collection("watchStats").document("global")

    @firestore.transactional
    def run(tx):
        existing = list(watches(uid).limit(WATCHES_PER_USER + 1).get(transaction=tx))
        b = budget.get(transaction=tx)
        g = total.get(transaction=tx)
        adds = (b.to_dict() or {}).get("count", 0) if b.exists else 0
        active = (g.to_dict() or {}).get("active", 0) if g.exists else 0
        if len(existing) >= WATCHES_PER_USER:
            raise ApiError(429, "too_many_watches")
        if adds >= WATCH_ADDS_PER_DAY or active >= WATCHES_TOTAL:
            raise ApiError(429, "watch_budget")
        tx.set(budget, {"count": adds + 1})
        tx.set(total, {"active": active + 1})
        tx.set(watches(uid).document(wid), {"name": scrub(name)[0], "url": clean, "tags": tags, "status": "unknown",
                                            "createdAt": firestore.SERVER_TIMESTAMP, "lastCheckedAt": None,
                                            "expiresAt": now + WATCH_LIFETIME, "counted": True})
        tx.set(watch_registry().document(f"{uid}__{wid}"), {"uid": uid, "watchId": wid,
                                                            "lastCheckedAt": datetime(2000, 1, 1, tzinfo=timezone.utc)})

    db.run_transaction(run)
    check_one(uid, wid)
    return {"id": wid, "url": clean}


def remove_watch(uid: str, wid: str) -> dict:
    """Removes the watch and its registry row together (and frees its place in the global count)."""
    ref = watches(uid).document(wid)
    total = db.client().collection("watchStats").document("global")

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        g = total.get(transaction=tx)
        if not snap.exists:
            raise not_found()
        tx.delete(ref)
        tx.delete(watch_registry().document(f"{uid}__{wid}"))
        if snap.to_dict().get("counted"):  # only watches that took a place give one back
            tx.set(total, {"active": max(0, (g.to_dict() or {}).get("active", 1) - 1)})

    db.run_transaction(run)
    return {"ok": True}



def probe(url: str) -> tuple[str, int | None, int | None]:
    """One check with a hard overall deadline. Runs as async I/O so the deadline really cancels it (the connection
    is closed), name lookup included; a slow or trickling server counts as down."""
    async def bounded():
        try:
            return await asyncio.wait_for(_aprobe(url), timeout=PROBE_BUDGET)
        except asyncio.TimeoutError:
            return "crit", None, None
    return asyncio.run(bounded())


async def _resolve_bounded(url: str):
    """Name lookup in its own daemon thread: if the deadline cancels us, nothing waits for it (the system resolver
    gives up on its own) and the sweep moves on."""
    fut: concurrent.futures.Future = concurrent.futures.Future()

    def work():
        try:
            fut.set_result(_resolve(url))
        except BaseException as e:  # handed to the waiting coroutine
            fut.set_exception(e)

    threading.Thread(target=work, daemon=True, name="watch-dns").start()
    return await asyncio.wrap_future(fut)


async def _aprobe(url: str) -> tuple[str, int | None, int | None]:
    """(status, http code, milliseconds). Up = any answer below 500 (redirects not followed).

    The connection goes to the very IP that was just checked to be public (Host header and TLS name stay the real
    host), so DNS can't redirect it somewhere private between check and connect. Only the status line is read:
    the body is never downloaded."""
    try:
        u, port, ip = await _resolve_bounded(url)  # re-checked each time
    except ApiError:
        return "crit", None, None
    host = f"[{ip}]" if ":" in ip else ip
    target = urllib.parse.urlunsplit((u.scheme, f"{host}:{port}", u.path or "/", u.query, ""))
    t = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(CHECK_TIMEOUT), follow_redirects=False,
                                     transport=_TRANSPORT) as c:
            async with c.stream("GET", target, headers={"Host": u.netloc.split("@")[-1],
                                                        "User-Agent": "Nightlight-uptime-check"},
                                extensions={"sni_hostname": u.hostname}) as r:
                code = r.status_code  # headers only; leaving the block closes the connection unread
        ms = int((time.monotonic() - t) * 1000)
        return ("ok" if code < 500 else "crit"), code, ms
    except (httpx.HTTPError, OSError):
        return "crit", None, None


def check_one(uid: str, wid: str) -> None:
    ref = watches(uid).document(wid)
    snap = ref.get()
    if not snap.exists:
        return
    w = snap.to_dict()
    status, code, ms = probe(w["url"])

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
        tx.set(watch_registry().document(f"{uid}__{wid}"), {"uid": uid, "watchId": wid, "lastCheckedAt": _now()},
               merge=True)  # the sweep takes the least recently checked first

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


def _adopt_legacy(uid: str, wid: str) -> None:
    """Watches from before the global count get counted and a retirement date (once)."""
    ref = watches(uid).document(wid)

    @firestore.transactional
    def run(tx):
        w = ref.get(transaction=tx).to_dict()
        if not w or w.get("counted"):
            return
        tx.update(ref, {"counted": True, "expiresAt": w.get("expiresAt") or _now() + WATCH_LIFETIME})

    db.run_transaction(run)


def _reconcile_count() -> None:
    """Re-derive the global count from the registry, in a transaction with the rows it counts, so a concurrent add
    or remove (which writes a registry row) makes one of the two retry instead of being overwritten."""
    total = db.client().collection("watchStats").document("global")

    @firestore.transactional
    def run(tx):
        rows = list(watch_registry().get(transaction=tx))
        total.get(transaction=tx)
        tx.set(total, {"active": len(rows)})

    db.run_transaction(run)


def sweep() -> dict:
    started = time.monotonic()
    silent = checked = pruned = 0
    for r in registry().stream():
        if time.monotonic() - started > SWEEP_BUDGET / 2:
            break  # devices get half the time; the rest waits for the next sweep
        d = r.to_dict()
        try:
            dsnap = db.device(d["uid"], d["deviceId"]).get()
            if not dsnap.exists or (dsnap.to_dict() or {}).get("revoked"):
                r.reference.delete()  # left, revoked or deleted: stop watching it
                pruned += 1
                continue
            silent += _mark_silent(d["uid"], d["deviceId"])
        except Exception as e:  # one bad record never stops the sweep
            log.warning("sweep device failed: %s", type(e).__name__)
    rows = list(watch_registry().stream())  # small: at most a few hundred rows
    for r in rows:  # rows from before ordering existed: give them a place in the queue (oldest first)
        if time.monotonic() - started > SWEEP_BUDGET:
            break
        if "lastCheckedAt" not in (r.to_dict() or {}):
            r.reference.set({"lastCheckedAt": datetime(2000, 1, 1, tzinfo=timezone.utc)}, merge=True)
    _reconcile_count()
    for r in watch_registry().order_by("lastCheckedAt").limit(WATCHES_TOTAL).stream():
        if time.monotonic() - started > SWEEP_BUDGET:
            break  # the rest waits for the next sweep
        d = r.to_dict()
        try:
            snap = watches(d["uid"]).document(d["watchId"]).get()
            w = snap.to_dict() if snap.exists else None
            if not w or (w.get("expiresAt") and w["expiresAt"] < _now()):
                if w:
                    remove_watch(d["uid"], d["watchId"])  # retired after its lifetime
                else:
                    r.reference.delete()
                pruned += 1
                continue
            if not w.get("counted"):
                _adopt_legacy(d["uid"], d["watchId"])
            check_one(d["uid"], d["watchId"])
            checked += 1
        except Exception as e:
            log.warning("sweep watch failed: %s", type(e).__name__)
    return {"ok": True, "newlySilent": silent, "watchesChecked": checked, "pruned": pruned}
