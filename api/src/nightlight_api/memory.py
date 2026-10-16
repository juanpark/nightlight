"""What Nightlight remembers about a person: a thin wrapper over Agent Platform Memory Bank.

Narrow by design. Facts are written only when the agent calls its `remember` tool (no automatic extraction from
transcripts, so no model calls outside our cost guards), and read once per turn. Every fact is scoped to
{app_name, user_id: uid}; the uid always comes from the verified Firebase token.

Memory is optional: with no MEMORY_BANK_ID every function is a no-op. A memory failure is logged and swallowed, so it
can never break a chat turn, a reset or a request.
"""

import logging
import re
import threading
import time
from functools import lru_cache

from google.cloud import firestore

from . import db
from .config import settings
from .redact import scrub

log = logging.getLogger(__name__)

APP = "nightlight"
TTL = "15552000s"  # 180 days
_UID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")  # also keeps the purge filter free of quotes
CACHE_SECONDS = 600
PER_TURN = 10
# Memory Bank lookups take 1-3 s from Seoul, longer than a turn should wait. Each instance keeps a person's newest
# facts for a few minutes, loaded when a chat session opens and updated on every save.
#
# "Forget" must win everywhere, so every purge first bumps `memoryEpoch` on the user's Firestore document. Cache
# entries and in-flight saves carry the epoch they started under; anything from an older epoch is ignored (a cache
# entry) or undone (a save that lands after a purge is purged again). All instances read the same epoch.
_cache: dict[str, tuple[float, int, list[str]]] = {}
_lock = threading.Lock()


def enabled() -> bool:
    return bool(settings.memory_bank_id)


@lru_cache
def _client():
    import agentplatform

    # Project and location are passed explicitly so the memory client never depends on ambient env (e.g. an API key
    # that would switch it to Express mode).
    return agentplatform.Client(project=settings.project_id, location=settings.memory_location)


def _api():
    """The Memory Bank `memories` surface. Tests replace this with a fake."""
    return _client().memory_banks.memories


def _bank() -> str:
    return f"reasoningEngines/{settings.memory_bank_id}"


def _scope(uid: str, ep: int) -> dict:
    """Memory Bank matches scopes exactly, so facts saved under an older epoch are invisible the moment a purge bumps
    the epoch, even before the (asynchronous) purge has deleted them. The purge filter matches all epochs."""
    return {"app_name": APP, "user_id": uid, "epoch": str(ep)}


def _usable(uid: str) -> bool:
    return enabled() and bool(_UID.match(uid or ""))


def _clean(text: str) -> tuple[str, int]:
    """Scrub, collapse whitespace and bound a fact's length."""
    clean, hidden = scrub(text or "")
    clean = " ".join(clean.split())
    limit = settings.memory_fact_chars
    if len(clean) > limit:
        clean = clean[:limit - 1].rstrip() + "…"
    return clean, hidden


def epoch(uid: str) -> int:
    """The user's current memory epoch (bumped by every purge)."""
    snap = db.user(uid).get()
    return int((snap.to_dict() or {}).get("memoryEpoch", 0)) if snap.exists else 0


def remember(uid: str, fact: str, started_epoch: int | None = None) -> dict:
    """Save one short fact for this person. Returns a status the agent can report honestly.

    A fact that looked like it contained a secret (password, key, token, email address...) is not stored at all:
    a scrubbed "[hidden]" fact would be useless, and the person should hear that secrets aren't kept.
    """
    if not _usable(uid):
        return {"status": "off"}
    clean, hidden = _clean(fact)
    if hidden:
        return {"status": "refused", "reason": "it looked like a password, key or address; those are never kept"}
    if not clean:
        return {"status": "refused", "reason": "nothing to remember"}
    ep = epoch(uid)
    if started_epoch is not None and ep != started_epoch:
        return {"status": "error", "reason": "memory was just cleared; nothing was saved"}
    try:
        _api().create(name=_bank(), fact=clean, scope=_scope(uid, ep),
                      config={"wait_for_completion": True, "ttl": TTL})
    except Exception as e:  # never let memory break a turn
        log.warning("memory write failed: %s", type(e).__name__)
        return {"status": "error", "reason": "memory is unavailable right now; nothing was saved"}
    if started_epoch is not None and epoch(uid) != started_epoch:
        _purge(uid)  # a purge ran while we were saving: forgetting wins, so purge again
        return {"status": "error", "reason": "memory was just cleared; nothing was saved"}
    with _lock:
        if uid in _cache:
            at, ep, facts = _cache[uid]
            _cache[uid] = (at, ep, [clean, *[f for f in facts if f != clean]][:PER_TURN])
    return {"status": "saved", "fact": clean}


def _fact(item) -> tuple[str, object, object]:
    m = getattr(item, "memory", item)  # retrieve() wraps each Memory; list-style results are Memory already
    return getattr(m, "fact", None) or "", getattr(m, "name", None), getattr(m, "update_time", None)


def recall(uid: str, query: str, top_k: int = 5) -> list[str]:
    """The few facts most related to `query`, scrubbed and bounded. Empty when off or on any failure."""
    if not _usable(uid) or not (query or "").strip():
        return []
    try:
        found = _api().retrieve(name=_bank(), scope=_scope(uid, epoch(uid)),
                                similarity_search_params={"search_query": scrub(query)[0][:1000], "top_k": top_k})
        facts = []
        for item in found:
            fact = _clean(_fact(item)[0])[0]
            if fact and fact not in facts:
                facts.append(fact)
            if len(facts) >= top_k:
                break
        return facts
    except Exception as e:
        log.warning("memory recall failed: %s", type(e).__name__)
        return []


def list_all(uid: str, limit: int = 50, ep: int | None = None) -> list[dict]:
    """Everything remembered for this person (for the "What Nightlight remembers" panel), newest first."""
    if not _usable(uid):
        return []
    try:
        found = _api().retrieve(name=_bank(), scope=_scope(uid, epoch(uid) if ep is None else ep),
                                simple_retrieval_params={"page_size": limit})
        out = []
        for item in found:
            fact, name, updated = _fact(item)
            fact = _clean(fact)[0]
            if fact:
                out.append({"id": str(name or "").rsplit("/", 1)[-1] or None, "fact": fact,
                            "updatedAt": updated.isoformat() if hasattr(updated, "isoformat") else None})
            if len(out) >= limit:
                break
        out.sort(key=lambda m: m["updatedAt"] or "", reverse=True)
        return out
    except Exception as e:
        log.warning("memory list failed: %s", type(e).__name__)
        return []


def forget_all(uid: str) -> bool:
    """Delete every fact remembered for this person. Best effort: returns False on failure, never raises.

    The purge is started, not awaited: the SDK's wait polls with no deadline, which must never hold a request or a
    reset. The service finishes it within moments.
    """
    if not _usable(uid):
        return False
    try:
        db.user(uid).set({"memoryEpoch": firestore.Increment(1)}, merge=True)
    except Exception as e:
        log.warning("memory epoch bump failed: %s", type(e).__name__)
    with _lock:
        _cache.pop(uid, None)
    return _purge(uid)


def _purge(uid: str) -> bool:
    try:
        # Started, never awaited: the SDK's default waits on the operation with no deadline.
        _api().purge(name=_bank(), filter=f'scope.user_id="{uid}"', force=True,
                     config={"wait_for_completion": False})
        return True
    except Exception as e:
        log.warning("memory purge failed: %s", type(e).__name__)
        return False


def cached(uid: str, current_epoch: int) -> list[str] | None:
    """This person's newest facts if this instance loaded them recently under the current epoch, else None."""
    with _lock:
        hit = _cache.get(uid)
    if hit and hit[1] == current_epoch and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[2]
    return None


def load(uid: str, current_epoch: int | None = None) -> list[str]:
    """Fetch the newest facts (a plain list, no search: faster than recall) and cache them under the epoch read
    before fetching, so a load that overlaps a purge can never be served afterwards."""
    if not _usable(uid):
        return []
    ep = epoch(uid) if current_epoch is None else current_epoch
    facts = [m["fact"] for m in list_all(uid, limit=PER_TURN, ep=ep)]
    with _lock:
        _cache[uid] = (time.monotonic(), ep, facts)
    return facts if epoch(uid) == ep else []


def prefetch(uid: str) -> None:
    """Warm the cache in the background (e.g. when a chat session opens). Never raises, never blocks."""
    if _usable(uid):
        threading.Thread(target=_quiet_load, args=(uid,), daemon=True).start()


def _quiet_load(uid: str) -> None:
    try:
        load(uid)
    except Exception as e:
        log.warning("memory prefetch failed: %s", type(e).__name__)
