"""Firestore client and document paths. Every user path hangs off users/{uid}."""

from functools import lru_cache

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
