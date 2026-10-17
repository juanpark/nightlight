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


def reserve(uid: str, ip: str, now: datetime | None = None, fence=None, c_max: float | None = None) -> float:
    """Reserve one model call. Returns the reserved amount (USD). Raises QuotaExceeded or ApiError(403/409).

    `fence(tx)` (the turn's ownership check) runs in the same transaction, so a turn made stale by a reset or a
    takeover can never reserve, and therefore never call the model.
    """
    now = now or datetime.now(timezone.utc)
    hour, day = _hour_key(now), _day_key(now)
    c_max = c_max or settings.c_max
    if settings.kill_switch:
        raise ApiError(403, "kill_switch")

    @firestore.transactional
    def run(tx):
        if fence:
            fence(tx)
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


def cost_of(usage, prices: tuple[float, float] | None = None) -> float | None:
    """Actual cost of one model call from its usage metadata, or None if billable usage isn't fully known.

    Prompt tokens bill at the input price; every other counted token (output, thinking, tool-use prompt) is billed
    at the output price, which is never cheaper, so the figure is an upper bound of the real charge.
    """
    if usage is None or usage.prompt_token_count is None or usage.total_token_count is None:
        return None
    prompt = usage.prompt_token_count
    rest = max(usage.total_token_count - prompt, 0)
    p_in, p_out = prices or (settings.price_in_per_m, settings.price_out_per_m)
    return (prompt * p_in + rest * p_out) / 1e6


def reconcile(reserved: float, actual: float | None) -> None:
    """Swap a reservation for the actual cost (signed: an overage raises the admission counter).

    Unknown cost keeps the reservation, so the budget is never under-counted.
    """
    if actual is None:
        return
    global_ref().set({"reservedUsd": firestore.Increment(actual - reserved), "spentUsd": firestore.Increment(actual)},
                     merge=True)


def turn_quota_ref(uid: str, now: datetime):
    return db.user(uid).collection("quota").document(f"turns_{_hour_key(now)}")


def check_turn_quota(snapshot, now: datetime) -> int:
    """Per-user turn limit for new messages. Call with the quota doc read inside the caller's transaction.

    Returns the new count to write; raises QuotaExceeded when the hour is used up.
    """
    n = (snapshot.to_dict() or {}).get("count", 0) if snapshot.exists else 0
    if n >= settings.turns_per_uid_hour:
        raise QuotaExceeded("quota_uid", _seconds_to_next_hour(now))
    return n + 1
