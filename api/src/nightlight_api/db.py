"""Firestore client and document paths. Every user path hangs off users/{uid}."""

import random
import time
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


def device(uid: str, device_id: str):
    return devices(uid).document(device_id)


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


def run_transaction(fn, *, max_attempts: int = 25, outer_tries: int = 6):
    """Run a @transactional callback, retrying with jittered back-off when contention aborts it.

    The client already retries inside `max_attempts`; under heavy contention a lock timeout can still surface as
    Aborted, or the attempts run out (ValueError). The callback is pure apart from its transaction writes, so
    running it again is safe: a retried decide simply sees the winner's committed result.
    """
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
