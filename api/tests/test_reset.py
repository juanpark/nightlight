import threading
from datetime import datetime, timedelta, timezone

import pytest

from nightlight_api import actions, db, demo
from nightlight_api.errors import ApiError
from conftest import device, generation, propose, trust


def _snapshot(uid):
    docs = {}
    for col in (db.devices(uid), db.trust(uid), db.events(uid), db.sessions(uid)):
        for s in col.get():
            docs[s.reference.path] = s.to_dict()
    for d in db.devices(uid).get():
        for s in d.reference.collection("services").get():
            docs[s.reference.path] = s.to_dict()
    docs["user"] = db.user(uid).get().to_dict()
    return docs


def _expire_lease(uid):
    db.user(uid).update({"demo.resetLeaseUntil": datetime.now(timezone.utc) - timedelta(seconds=1)})


def test_reset_stales_old_cards_and_reseeds(started):
    uid = started
    a = propose(uid)
    actions.decide(uid, propose(uid, device="game-1")["id"], "approve")  # another job (the same one twice is one card)
    demo.inject(uid, "disk_full", "pi-1")
    out = demo.reset(uid)
    assert out["demoGeneration"] == 2 and generation(uid) == 2
    old = db.action(uid, a["id"]).get().to_dict()
    assert old["status"] == "stale" and old["demoGeneration"] == 1  # tombstone kept
    with pytest.raises(ApiError) as e:
        actions.decide(uid, a["id"], "approve")
    assert e.value.code == "stale"
    pi = device(uid)
    assert pi["demoGeneration"] == 2 and pi["version"] == 1 and pi["vitals"]["diskPct"] == 94
    assert trust(uid)["successes"] == [] and trust(uid)["demoGeneration"] == 2
    assert db.events(uid).get() == []


def test_writes_wait_while_resetting(started):
    uid = started
    gate = threading.Event()
    release = threading.Event()

    def hook(stage):
        if stage == "seed":
            gate.set()
            release.wait(10)

    t = threading.Thread(target=lambda: demo.reset(uid, hook=hook))
    t.start()
    assert gate.wait(10)
    for call in (lambda: demo.inject(uid, "disk_full", "pi-1"), lambda: demo.reset(uid), lambda: propose(uid)):
        with pytest.raises(ApiError) as e:
            call()
        assert e.value.code in ("resetting", "reset_in_progress", "stale", "not_found")
    release.set()
    t.join(10)
    assert db.user(uid).get().to_dict()["demo"]["state"] == "ready"


def test_paused_worker_cannot_overwrite_newer_reset(started):
    uid = started
    paused = threading.Event()
    release = threading.Event()
    outcome = {}

    def hook(stage):
        if stage == "seed" and not paused.is_set():
            paused.set()
            release.wait(10)

    def worker_a():
        try:
            demo.reset(uid, hook=hook)
            outcome["a"] = "finished"
        except demo.Superseded:
            outcome["a"] = "superseded"

    t = threading.Thread(target=worker_a)
    t.start()
    assert paused.wait(10)
    _expire_lease(uid)
    assert demo.reset(uid)["demoGeneration"] == 3  # worker B takes over and finishes
    before = _snapshot(uid)
    release.set()
    t.join(10)
    assert outcome["a"] == "superseded"
    assert _snapshot(uid) == before


def test_killed_reset_recovers(started):
    uid = started

    def crash(stage):
        if stage == "seed":
            raise RuntimeError("process died")

    with pytest.raises(RuntimeError):
        demo.reset(uid, hook=crash)
    assert db.user(uid).get().to_dict()["demo"]["state"] == "resetting"
    _expire_lease(uid)
    out = demo.start(uid)
    assert out["demoGeneration"] == 3 and db.user(uid).get().to_dict()["demo"]["state"] == "ready"
    assert len(db.devices(uid).get()) == 6
