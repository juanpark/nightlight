"""Deterministic checks of db.run_transaction's retry branches (no emulator traffic)."""

import pytest
from google.api_core.exceptions import Aborted

from nightlight_api import db


class FakeClient:
    def __init__(self):
        self.made = []

    def transaction(self, max_attempts=None):
        tx = object()
        self.made.append(tx)
        return tx


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    sleeps = []
    monkeypatch.setattr(db, "client", lambda: client)
    monkeypatch.setattr(db.time, "sleep", sleeps.append)
    return client, sleeps


def _exhausted():
    try:
        raise Aborted("lock timeout")
    except Aborted as cause:
        try:
            raise ValueError("Failed to commit transaction in 25 attempts.") from cause
        except ValueError as e:
            return e


def test_recovers_from_aborted(fake):
    client, sleeps = fake
    calls = iter([Aborted("x"), "ok"])

    def fn(tx):
        r = next(calls)
        if isinstance(r, Exception):
            raise r
        return r

    assert db.run_transaction(fn) == "ok"
    assert len(client.made) == 2 and client.made[0] is not client.made[1] and len(sleeps) == 1


def test_recovers_from_exhausted_attempts(fake):
    client, sleeps = fake
    calls = iter([_exhausted(), "ok"])

    def fn(tx):
        r = next(calls)
        if isinstance(r, Exception):
            raise r
        return r

    assert db.run_transaction(fn) == "ok" and len(sleeps) == 1


def test_persistent_contention_is_bounded(fake):
    client, sleeps = fake

    def fn(tx):
        raise Aborted("x")

    with pytest.raises(Aborted):
        db.run_transaction(fn, outer_tries=3)
    assert len(client.made) == 3 and len(sleeps) == 2


def test_unrelated_value_error_is_not_retried(fake):
    client, sleeps = fake

    def fn(tx):
        raise ValueError("bug: bad attempts count")

    with pytest.raises(ValueError):
        db.run_transaction(fn)
    assert len(client.made) == 1 and sleeps == []
