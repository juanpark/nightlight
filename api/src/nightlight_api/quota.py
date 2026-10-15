"""Cost guards: no model call happens unless a reservation for its worst-case cost succeeds first.

Every model call reserves C_max (the cost of the largest request the limits allow) inside one Firestore transaction,
together with the per-user, per-visitor and daily call counters and the kill switch. After the call, the actual cost
from usage metadata replaces the reservation; if usage is unknown, the full reservation is kept.
"""

import hashlib
from datetime import datetime, timezone

from google.cloud import firestore

from . import db
from .config import settings
from .errors import ApiError


class QuotaExceeded(ApiError):
    def __init__(self, code: str, retry_after: int):
        super().__init__(429, code, retryAfter=retry_after)


def ip_hash(ip: str | None) -> str:
    return hashlib.sha256(f"{settings.ip_hash_salt}|{ip or 'unknown'}".encode()).hexdigest()[:32]


def _hour_key(now: datetime) -> str:
    return now.strftime("%Y%m%d%H")


def _day_key(now: datetime) -> str:
    return now.strftime("%Y%m%d")


def _seconds_to_next_hour(now: datetime) -> int:
    return 3600 - (now.minute * 60 + now.second)


def global_ref():
    return db.client().collection("ops").document("quota")


def flags_ref():
    return db.client().collection("ops").document("flags")


def reserve(uid: str, ip: str, now: datetime | None = None) -> float:
    """Reserve one model call. Returns the reserved amount (USD). Raises QuotaExceeded or ApiError(403)."""
    now = now or datetime.now(timezone.utc)
    hour, day = _hour_key(now), _day_key(now)
    c_max = settings.c_max
    if settings.kill_switch:
        raise ApiError(403, "kill_switch")

    @firestore.transactional
    def run(tx):
        flags = flags_ref().get(transaction=tx)
        if flags.exists and flags.to_dict().get("killSwitch"):
            raise ApiError(403, "kill_switch")
        g_ref, u_ref = global_ref(), db.user(uid).collection("quota").document(f"calls_{hour}")
        i_ref = db.client().collection("ipQuotas").document(f"{ip}_{hour}")
        g, u, i = (r.get(transaction=tx) for r in (g_ref, u_ref, i_ref))
        g = g.to_dict() if g.exists else {}
        u_calls = (u.to_dict() or {}).get("count", 0) if u.exists else 0
        i_calls = (i.to_dict() or {}).get("count", 0) if i.exists else 0
        day_calls = g.get("days", {}).get(day, 0)
        if u_calls >= settings.model_calls_per_uid_hour:
            raise QuotaExceeded("quota_uid", _seconds_to_next_hour(now))
        if i_calls >= settings.model_calls_per_ip_hour:
            raise QuotaExceeded("quota_ip", _seconds_to_next_hour(now))
        if day_calls >= settings.model_calls_per_day:
            raise QuotaExceeded("quota_global", 3600)
        if g.get("reservedUsd", 0.0) + c_max > settings.model_budget_usd:
            raise QuotaExceeded("quota_global", 3600)
        tx.set(g_ref, {"reservedUsd": g.get("reservedUsd", 0.0) + c_max, "calls": g.get("calls", 0) + 1,
                       "days": {**g.get("days", {}), day: day_calls + 1}, "cMax": c_max,
                       "budgetUsd": settings.model_budget_usd}, merge=True)
        tx.set(u_ref, {"count": u_calls + 1, "hour": hour})
        tx.set(i_ref, {"count": i_calls + 1, "hour": hour})
        return c_max

    return db.run_transaction(run)


def cost_of(prompt_tokens: int | None, output_tokens: int | None, thinking_tokens: int | None) -> float | None:
    if prompt_tokens is None or output_tokens is None:
        return None
    out = (output_tokens or 0) + (thinking_tokens or 0)
    return (prompt_tokens * settings.price_in_per_m + out * settings.price_out_per_m) / 1e6


def reconcile(reserved: float, actual: float | None) -> None:
    """Swap a reservation for the actual cost. Unknown cost keeps the reservation (never under-counts)."""
    if actual is None:
        return
    refund = max(reserved - actual, 0.0)
    global_ref().set({"reservedUsd": firestore.Increment(-refund), "spentUsd": firestore.Increment(actual)},
                     merge=True)


def count_turn(uid: str, now: datetime | None = None) -> None:
    """Per-user turn limit, counted when a new message is accepted (separate from model calls)."""
    now = now or datetime.now(timezone.utc)
    hour = _hour_key(now)
    ref = db.user(uid).collection("quota").document(f"turns_{hour}")

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        n = (snap.to_dict() or {}).get("count", 0) if snap.exists else 0
        if n >= settings.turns_per_uid_hour:
            raise QuotaExceeded("quota_uid", _seconds_to_next_hour(now))
        tx.set(ref, {"count": n + 1, "hour": hour})

    db.run_transaction(run)
