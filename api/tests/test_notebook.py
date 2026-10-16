"""A device notebook: short, scrubbed notes from Nightlight and the owner, bounded, gone with the sample home."""

from nightlight_api import db, demo, notebook
from conftest import generation
from test_real import beat, enrolled


def _sample_id(uid):
    return next(s.id for s in db.devices(uid).get() if s.to_dict().get("realm") != "real")


def test_owner_and_nightlight_notes_reach_the_agent_newest_first(client, started):
    dev = _sample_id(started)
    r = client.post(f"/api/devices/{dev}/notes", json={"text": "  Lives in the  hallway cupboard "})
    assert r.status_code == 201 and r.json()["by"] == "you" and r.json()["text"] == "Lives in the hallway cupboard"
    notebook.add(started, dev, "Disk fills from the Minecraft backups; safe to prune.", "nightlight", generation(started))
    got = notebook.recent(started, dev, generation(started))
    assert [n["by"] for n in got] == ["nightlight", "you"] and got[0]["on"]


def test_secrets_are_refused_not_stored(client, started):
    dev = _sample_id(started)
    r = client.post(f"/api/devices/{dev}/notes", json={"text": "router password=" + "hunter2hunter2"})
    assert r.status_code == 422 and r.json()["detail"][0]["msg"] == "looks_secret"
    assert notebook.recent(started, dev, generation(started)) == []


def test_bounded_and_owner_notes_outlive_nightlights(client, started, monkeypatch):
    monkeypatch.setattr(notebook, "KEEP", 3)
    dev = _sample_id(started)
    notebook.add(started, dev, "owner fact", "you", generation(started))
    for i in range(4):
        notebook.add(started, dev, f"finding {i}", "nightlight", generation(started))
    texts = {n["text"] for n in notebook.recent(started, dev, generation(started))}
    assert texts == {"owner fact", "finding 2", "finding 3"}


def test_delete_and_unknown_devices(client, started):
    dev = _sample_id(started)
    nid = client.post(f"/api/devices/{dev}/notes", json={"text": "x"}).json()["id"]
    assert client.delete(f"/api/devices/{dev}/notes/{nid}").status_code == 200
    assert client.delete(f"/api/devices/{dev}/notes/{nid}").status_code == 404
    assert client.post("/api/devices/nope-1/notes", json={"text": "x"}).status_code == 404


def test_reset_clears_sample_notes_but_keeps_real_ones(client, started):
    dev = _sample_id(started)
    notebook.add(started, dev, "sample note", "you", generation(started))
    real_dev = enrolled(client)
    beat(client, real_dev["token"])
    notebook.add(started, real_dev["deviceId"], "real note", "you", generation(started))
    demo.reset(started)
    assert list(db.notes(started, dev).get()) == []
    assert [n["text"] for n in notebook.recent(started, real_dev["deviceId"], generation(started))] == ["real note"]


def test_no_note_while_a_reset_runs_or_from_an_old_turn(client, started):  # review B #1
    import pytest
    from nightlight_api.errors import ApiError
    dev = _sample_id(started)
    db.user(started).update({"demo.state": "resetting"})
    with pytest.raises(ApiError):
        notebook.add(started, dev, "late", "nightlight", generation(started))
    db.user(started).update({"demo.state": "ready"})
    with pytest.raises(ApiError):
        notebook.add(started, dev, "old generation", "nightlight", generation(started) - 1)

    def stale(tx):
        raise ApiError(409, "stale")
    with pytest.raises(ApiError):
        notebook.add(started, dev, "old turn", "nightlight", generation(started), fence=stale)
    assert notebook.recent(started, dev, generation(started)) == []


def test_old_generation_notes_are_never_shown(client, started):  # review B #1, defence in depth
    dev = _sample_id(started)
    db.notes(started, dev).document("note_x").set({"text": "left over", "by": "nightlight", "at": None,
                                                    "demoGeneration": generation(started) - 1})
    assert notebook.recent(started, dev, generation(started)) == []
