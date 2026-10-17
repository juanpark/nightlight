"""The sample home starts lived in: notes, a runbook and a few past jobs, which a reset replaces rather than adds to."""

from nightlight_api import db
from conftest import generation


def _jobs(client, did, query=""):
    r = client.get(f"/api/devices/{did}/log{query}")
    assert r.status_code == 200
    return r.json()["jobs"]


def test_a_fresh_demo_has_notes_a_runbook_and_past_jobs(client, started):
    view = client.get("/api/devices/mac-1/knowledge").json()
    immich = [n["text"] for n in view["notes"]["services"]["immich"]]
    assert len(immich) == 2 and immich[0].startswith("Immich's photo database")  # newest first
    assert "Photos from the family phones upload here every night." in immich
    [rb] = view["runbooks"]
    assert rb["title"] == "Restart Immich when it can't reach its database" and rb["service"] == "immich"
    assert [s["job"]["type"] for s in rb["steps"]] == ["restart_app"]

    [job] = _jobs(client, "mac-1")
    assert job["kind"] == "restart_app" and job["ok"] and job["service"] == "immich" and job["by"] == "you"
    assert job["summary"] == "Restarted Immich; it reconnected to its database."
    assert [j["actionId"] for j in _jobs(client, "mac-1", "?service=immich")] == [job["actionId"]]
    assert _jobs(client, "mac-1", "?service=immich-db") == []

    pi = client.get("/api/devices/pi-1/knowledge").json()
    assert ["TeslaMate" in n["text"] for n in pi["notes"]["services"]["TeslaMate"]] == [True]
    assert [j["kind"] for j in _jobs(client, "pi-1")] == ["clear_images", "rotate_logs"]  # 10 days, then 14 days ago

    # The past jobs are finished sample jobs: nothing to deliver, approve or continue.
    for snap in db.actions(started).get():
        a = snap.to_dict()
        assert a["status"] == "done" and a["realm"] == "sim" and a["demoGeneration"] == generation(started)
        assert not a.get("sessionId") and not a.get("turnId")


def test_a_reset_replaces_the_history_instead_of_adding_to_it(client, started):
    for _ in range(2):
        assert client.post("/api/demo/reset", json={}).status_code == 200
    gen = generation(started)
    assert len(client.get("/api/devices/mac-1/knowledge").json()["notes"]["services"]["immich"]) == 2
    assert len(client.get("/api/devices/mac-1/knowledge").json()["runbooks"]) == 1
    assert len(_jobs(client, "mac-1")) == 1 and len(_jobs(client, "pi-1")) == 2
    stored = [s.to_dict() for s in db.actions(started).get()]
    assert len(stored) == 3 and {a["demoGeneration"] for a in stored} == {gen}
    assert len(list(db.notes(started, "mac-1").get())) == 2
