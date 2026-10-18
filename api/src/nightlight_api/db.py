"""Firestore client and document paths. Every user path hangs off users/{uid}."""

import contextvars
import random
import re
import time
from contextlib import contextmanager
from functools import lru_cache

from google.api_core.exceptions import Aborted

from google.cloud import firestore

from .config import settings


@lru_cache
def client() -> firestore.Client:
    return firestore.Client(project=settings.project_id)


def user(uid: str):
    return client().collection("users").document(uid)


def devices(uid: str):
    return user(uid).collection("devices")


DEVICE_ID = re.compile(r"[a-z0-9_-]{2,40}")  # sample ids (pi-1) and helper ids (dev_<ulid>), as the API routes accept


def device(uid: str, device_id: str):
    """A device's document. Every caller, the agent's tools included, gets here, so an id that isn't one (a path
    like "game-1/services/x", or anything else a model might pass) can never address another document."""
    if not isinstance(device_id, str) or not DEVICE_ID.fullmatch(device_id):
        from .errors import not_found
        raise not_found()
    return devices(uid).document(device_id)


def links(uid: str):
    return user(uid).collection("links")


def services(uid: str, device_id: str):
    return device(uid, device_id).collection("services")


def notes(uid: str, device_id: str):
    return device(uid, device_id).collection("notes")


def actions(uid: str):
    return user(uid).collection("actions")


def action(uid: str, action_id: str):
    return actions(uid).document(action_id)


def events(uid: str):
    return user(uid).collection("events")


def trust(uid: str):
    return user(uid).collection("trust")


def trust_doc(uid: str, realm: str, action_type: str):
    return trust(uid).document(f"{realm}:{action_type}")


def sessions(uid: str):
    return user(uid).collection("sessions")


def session(uid: str, session_id: str):
    return sessions(uid).document(session_id)


def turns(uid: str, session_id: str):
    return session(uid, session_id).collection("turns")


def messages(uid: str, session_id: str):
    return session(uid, session_id).collection("messages")


# A fence every transaction of the current request (or cleanup) passes through: a holder dict set per request by
# FenceMiddleware, filled by auth for a live demo machine's account with a check(tx) that re-reads its lease inside the
# same transaction as the write; or replaced for the duration of a pool cleanup by `fenced(check)`.
_fence: contextvars.ContextVar[dict | None] = contextvars.ContextVar("nl_fence", default=None)


def fence_holder() -> dict | None:
    return _fence.get()


@contextmanager
def fenced(check):
    """Run the block with `check(tx)` at the start of every transaction (and `fence_now()` calls)."""
    token = _fence.set({"check": check})
    try:
        yield
    finally:
        _fence.reset(token)


def fence_now() -> None:
    """Re-check the current fence now, in its own transaction (before a write that can't be transactional)."""
    holder = _fence.get()
    if holder and holder.get("check"):
        @firestore.transactional
        def run(tx):
            holder["check"](tx)
        run(client().transaction())


class FenceMiddleware:
    """Pure ASGI: a fresh fence holder per request. Context copies (thread pools, tasks) share this dict."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token = _fence.set({})
        try:
            await self.app(scope, receive, send)
        finally:
            _fence.reset(token)


def run_transaction(fn, *, max_attempts: int = 25, outer_tries: int = 6):
    """Run a @transactional callback, retrying with jittered back-off when contention aborts it.

    The client already retries inside `max_attempts`; under heavy contention a lock timeout can still surface as
    Aborted, or the attempts run out (ValueError). The callback is pure apart from its transaction writes, so
    running it again is safe: a retried decide simply sees the winner's committed result.
    """
    holder = _fence.get()
    check = holder.get("check") if holder else None
    if check is not None and hasattr(fn, "to_wrap"):
        inner = fn.to_wrap

        def guarded(tx, *a, **k):
            check(tx)  # first read of every attempt: the write commits only if the fence still holds
            return inner(tx, *a, **k)
        fn = firestore.transactional(guarded)
    for attempt in range(outer_tries):
        try:
            return fn(client().transaction(max_attempts=max_attempts))
        except (Aborted, ValueError) as e:
            # The SDK reports exhausted commit attempts as a ValueError chained from Aborted; any other
            # ValueError is a real bug and must not be retried.
            if isinstance(e, ValueError) and not isinstance(e.__cause__, Aborted):
                raise
            if attempt == outer_tries - 1:
                raise
            time.sleep(random.uniform(0.05, 0.2) * (2 ** attempt))
