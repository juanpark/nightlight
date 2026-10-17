"""What Nightlight keeps per device: notes per service, the job log, runbooks (saved, listed, used only as cards)."""

import asyncio
import uuid

import pytest

from nightlight_api import actions, agent as agentlib, db, demo, notebook, runbooks
from nightlight_api.auth import current_uid
from nightlight_api.main import app
from conftest import generation
from test_real import FACTS, beat, enrolled
from test_real_jobs import ALLOW, _again


def _tools(uid, turn="turn_k"):
    db.session(uid, "sess_test").set({"activeTurn": {"turnId": turn, "attempt": 1}}, merge=True)  # the turn's lease
    ctx = agentlib.TurnContext(uid=uid, session_id="sess_test", turn_id=turn, attempt=1, generation=generation(uid),
                               ip="1.2.3.4", deep=False)
    return {t.__name__: t for t in agentlib.make_tools(ctx, read_only=False)}, ctx


def _call(tools, name, **kw):
    return asyncio.run(tools[name](tool_context=None, **kw))


def _report(client, dev, aid, **body):
    return client.post(f"/helper/jobs/{aid}/result", json={"ok": True, "summary": "Done.", **body},
                       headers={"X-Device-Token": dev["token"]})


def _deliver(client, dev, facts=ALLOW):
    _again(dev["token"])
    return beat(client, dev["token"], facts).json()["jobs"]


# ------------------------------------------------------------------ notes per service

def test_notes_can_belong_to_a_service_and_reach_the_agent_grouped(client, started):
    r = client.post("/api/devices/game-1/notes", json={"text": "World saves lag on Sundays", "service": "minecraft"})
    assert r.status_code == 201 and r.json()["service"] == "Minecraft server" and r.json()["svcId"] == "minecraft"
    notebook.add(started, "game-1", "Fan is loud; it lives in the attic", "nightlight", generation(started))
    tools, _ = _tools(started)
    got = _call(tools, "write_note", device_id="game-1", note="Mods need updating by hand", service="Minecraft Server")
    assert got["status"] == "saved"
    bad = _call(tools, "write_note", device_id="game-1", note="x", service="Plex")
    assert bad["status"] == "refused" and "no service" in bad["reason"]
    assert client.post("/api/devices/game-1/notes", json={"text": "x", "service": "plex"}).json()["detail"][0]["msg"] \
        == "unknown_service"
    book = _call(tools, "get_device", device_id="game-1")["notebook"]
    assert [n["text"] for n in book["device"]] == ["Fan is loud; it lives in the attic"]
    assert [n["text"] for n in book["services"]["Minecraft server"]] == ["Mods need updating by hand",
                                                                         "World saves lag on Sundays"]
    view = client.get("/api/devices/game-1/knowledge").json()
    assert set(view) == {"profile", "notes", "runbooks"} and view["notes"]["services"]["Minecraft server"][0]["id"]


def test_the_agent_sees_a_bounded_number_of_notes_per_service(client, started, monkeypatch):
    monkeypatch.setattr(notebook, "SHOWN_PER_SERVICE", 2)
    for i in range(4):
        notebook.add(started, "game-1", f"note {i}", "you", generation(started), service="minecraft")
    book = notebook.grouped(started, "game-1", generation(started))
    assert [n["text"] for n in book["services"]["Minecraft server"]] == ["note 3", "note 2"] and book["device"] == []


# ------------------------------------------------------------------ the job log

def test_log_lists_finished_jobs_newest_first_scrubbed_with_who_set_them_going(client, started):
    dev = enrolled(client)
    did = dev["deviceId"]
    facts = {**ALLOW, "allowedJobs": {"restart_container": ["pi-grafana-1"], "diagnose": ["pi-grafana-1"],
                                      "logs": ["pi-grafana-1"], "restart_service": ["pihole-FTL.service"]}}
    beat(client, dev["token"], facts)
    look = actions.request_diagnosis(started, session_id="sess_test", turn_id="t_look", generation=generation(started),
                                     device_id=did, target="pi-grafana-1")
    assert _deliver(client, dev, facts)
    _report(client, dev, look["id"], summary="Exited (1)", output="grafana\nDB_PASSWORD=hunter2hunter2 failed")
    card = actions.propose(started, session_id="sess_test", turn_id="t_fix", generation=generation(started),
                           action_type="restart_container", device_id=did, params={"container": "pi-grafana-1"})
    client.post(f"/api/actions/{card['id']}/decide", json={"decision": "approve"})
    assert _deliver(client, dev, facts)
    _report(client, dev, card["id"], summary="Started pi-grafana-1.", state="running")
    pending = actions.propose(started, session_id="sess_test", turn_id="t_wait", generation=generation(started),
                              action_type="restart_service", device_id=did, params={"unit": "pihole-FTL.service"})
    assert pending["status"] == "pending"

    r = client.get(f"/api/devices/{did}/log")
    jobs = r.json()["jobs"]
    assert r.status_code == 200 and [j["actionId"] for j in jobs] == [card["id"], look["id"]]  # unfinished: not shown
    assert jobs[0] | {"at": None} == {"at": None, "kind": "restart_container", "title": card["plan"], "ok": True,
                                      "summary": "Started pi-grafana-1.", "by": "you", "actionId": card["id"],
                                      "service": "pi-grafana-1"}
    assert jobs[1]["by"] == "nightlight" and "hunter2" not in jobs[1]["output"] and "[hidden]" in jobs[1]["output"]
    assert [j["actionId"] for j in client.get(f"/api/devices/{did}/log?limit=1").json()["jobs"]] == [card["id"]]
    assert client.get(f"/api/devices/{did}/log?limit=0").status_code == 422

    tools, _ = _tools(started)
    seen = _call(tools, "read_device_log", device_id=did, service="pi-grafana-1", limit=5)
    assert [j["actionId"] for j in seen["jobs"]] == [card["id"], look["id"]] and len(seen["jobs"][1]["output"]) <= 400
    assert _call(tools, "read_device_log", device_id=did, service="pi-teslamate-1")["jobs"] == []


def test_sample_device_log_belongs_to_its_generation(client, started):
    a = actions.propose(started, session_id="sess_test", turn_id="t1", generation=generation(started),
                        action_type="rotate_logs", device_id="pi-1", params={})
    client.post(f"/api/actions/{a['id']}/decide", json={"decision": "approve"})
    jobs = client.get("/api/devices/pi-1/log").json()["jobs"]
    assert [j["actionId"] for j in jobs] == [a["id"]] and jobs[0]["ok"] and jobs[0]["by"] == "you"
    demo.reset(started)
    assert client.get("/api/devices/pi-1/log").json()["jobs"] == []


def test_another_person_sees_nothing_of_a_device(client, started, uid):
    dev = enrolled(client)
    beat(client, dev["token"])
    rb = runbooks.save(started, "pi-1", "Clear old logs", "Disk nearly full", [{"say": "Clear old logs",
                                                                              "job": "rotate_logs"}],
                       "nightlight", generation(started))
    other = f"u_{uuid.uuid4().hex[:12]}"
    app.dependency_overrides[current_uid] = lambda: other
    try:
        demo.start(other)
        for path in (f"/api/devices/{dev['deviceId']}/log", f"/api/devices/{dev['deviceId']}/knowledge"):
            assert client.get(path).status_code == 404
        assert client.get("/api/devices/pi-1/knowledge").json()["runbooks"] == []  # their own sample Pi
        assert client.delete(f"/api/devices/pi-1/runbooks/{rb['id']}").status_code == 404
    finally:
        app.dependency_overrides[current_uid] = lambda: uid
    assert runbooks.get(started, "pi-1", rb["id"], generation(started))["title"] == "Clear old logs"


# ------------------------------------------------------------------ runbooks

def test_a_runbook_is_saved_listed_and_used_only_as_cards(client, started):
    tools, _ = _tools(started)
    saved = _call(tools, "save_runbook", device_id="pi-1", title="Clear old logs",
                  when="The disk is nearly full of old log files",
                  steps=[{"say": "Check what fills the disk"},
                         {"say": "Clear old logs", "job": {"type": "rotate_logs"}}])
    assert saved["status"] == "saved"
    listed = _call(tools, "get_device", device_id="pi-1")["runbooks"]
    assert listed == [{"id": saved["runbookId"], "title": "Clear old logs",
                       "when": "The disk is nearly full of old log files", "uses": 0}]
    before = db.device(started, "pi-1").get().to_dict()["version"]
    used = _call(tools, "use_runbook", device_id="pi-1", runbook_id=saved["runbookId"])
    assert used["status"] == "pending" and used["steps"][0] == {"say": "Check what fills the disk", "status": "yours"}
    aid = used["steps"][1]["actionId"]
    assert used["actionIds"] == [aid] and db.action(started, aid).get().to_dict()["status"] == "pending"
    assert db.device(started, "pi-1").get().to_dict()["version"] == before  # nothing ran
    _call(tools, "use_runbook", device_id="pi-1", runbook_id=saved["runbookId"])  # a retried turn: still one use
    assert runbooks.get(started, "pi-1", saved["runbookId"], generation(started))["uses"] == 1
    assert _call(tools, "use_runbook", device_id="pi-1", runbook_id="rb_nope")["status"] == "error"


def test_a_real_device_runbook_proposes_its_job_and_its_command_needs_a_passkey(client, started):
    dev = enrolled(client)
    did = dev["deviceId"]
    beat(client, dev["token"], ALLOW)
    rb = runbooks.save(started, did, "Bring Grafana back", "Grafana stopped after an update",
                       [{"say": "Start Grafana again", "job": {"type": "restart_container",
                                                               "params": {"container": "pi-grafana-1"}}},
                        {"say": "Clear its cache", "command": "rm -rf /var/cache/grafana"}],
                       "nightlight", generation(started), service="pi-grafana-1")
    assert rb["service"] == "pi-grafana-1" and rb["steps"][1] == {"say": "Clear its cache",
                                                                   "command": "rm -rf /var/cache/grafana"}
    tools, _ = _tools(started)
    used = _call(tools, "use_runbook", device_id=did, runbook_id=rb["id"])
    job, command = used["steps"]
    assert job["status"] == "pending" and used["status"] == "pending"
    assert command["status"] == "error"  # expert sessions are off on this device: no way to run it
    assert _deliver(client, dev) == []  # a card waits for a tap; nothing reaches the device


def test_runbook_limits(client, started, monkeypatch):
    gen = generation(started)
    step = [{"say": "Clear old logs", "job": "rotate_logs"}]
    for code, steps in (("steps", []), ("steps", step * 11), ("unknown_job", [{"say": "x", "job": "format_disk"}]),
                        ("job_or_command", [{"say": "x", "job": "rotate_logs", "command": "ls"}]),
                        ("looks_secret:say", [{"say": "use token=abcdefgh12345678"}]),  # gitleaks:allow (fake, checks refusal)
                        ("unknown_job", [{"say": "x", "job": {"type": "fix", "params": {"recipe": "x" * 400}}}])):
        with pytest.raises(ValueError, match=code):
            runbooks.save(started, "pi-1", "T", "W", steps, "nightlight", gen)
    monkeypatch.setattr(runbooks, "PER_DEVICE", 2)
    first = runbooks.save(started, "pi-1", "One", "W", step, "nightlight", gen)
    runbooks.save(started, "pi-1", "Two", "W", step, "nightlight", gen)
    with pytest.raises(ValueError, match="too_many_runbooks"):
        runbooks.save(started, "pi-1", "Three", "W", step, "nightlight", gen)
    again = runbooks.save(started, "pi-1", "one", "Better words", step * 2, "nightlight", gen)  # same title: replaced
    assert again["id"] == first["id"] and again["replaced"] and len(runbooks.listed(started, "pi-1", gen)) == 2
    tools, _ = _tools(started)
    out = _call(tools, "save_runbook", device_id="pi-1", title="Three", when="W", steps=step)
    assert out["status"] == "refused" and "already has 2" in out["reason"]


def test_owner_renames_and_deletes_runbooks(client, started):
    rb = runbooks.save(started, "pi-1", "Clear old logs", "W", [{"say": "Clear", "job": "rotate_logs"}],
                       "nightlight", generation(started))
    r = client.post(f"/api/devices/pi-1/runbooks/{rb['id']}", json={"title": "Free up space", "when": "Disk over 90%"})
    assert r.status_code == 200 and r.json()["title"] == "Free up space" and r.json()["when"] == "Disk over 90%"
    assert client.post(f"/api/devices/pi-1/runbooks/{rb['id']}", json={"steps": []}).status_code == 422
    bad = client.post(f"/api/devices/pi-1/runbooks/{rb['id']}", json={"when": "password=" + "hunter2hunter2"})
    assert bad.status_code == 422 and bad.json()["detail"][0]["msg"] == "looks_secret"
    assert client.get("/api/devices/pi-1/knowledge").json()["runbooks"][0]["title"] == "Free up space"
    assert client.delete(f"/api/devices/pi-1/runbooks/{rb['id']}").status_code == 200
    assert client.delete(f"/api/devices/pi-1/runbooks/{rb['id']}").status_code == 404
    assert client.get("/api/devices/pi-1/knowledge").json()["runbooks"] == []


def test_reset_clears_sample_runbooks_but_keeps_real_ones(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], FACTS)
    step = [{"say": "Clear", "job": "fix", "params": {"recipe": "docker_prune"}}]
    runbooks.save(started, "pi-1", "Sample", "W", step, "nightlight", generation(started))
    runbooks.save(started, dev["deviceId"], "Real", "W", step, "nightlight", generation(started))
    demo.reset(started)
    assert list(db.device(started, "pi-1").collection("runbooks").get()) == []
    assert [r["title"] for r in runbooks.listed(started, dev["deviceId"], generation(started))] == ["Real"]


def test_a_long_runbook_keeps_its_cards_when_its_text_is_shortened(client, started, monkeypatch):  # codex kb #1
    from nightlight_api.config import settings
    tools, _ = _tools(started)
    saved = _call(tools, "save_runbook", device_id="pi-1", title="Clear old logs", when="Disk nearly full",
                  steps=[{"say": "Explain step %d in many plain words so it takes up room" % i} for i in range(9)]
                  + [{"say": "Clear old logs", "job": {"type": "rotate_logs"}}])
    monkeypatch.setattr(settings, "tool_result_bytes", 400)
    used = _call(tools, "use_runbook", device_id="pi-1", runbook_id=saved["runbookId"])
    assert used["status"] == "pending" and len(used["actionIds"]) == 1 and "truncated" not in used


def test_a_runbook_whose_step_fails_is_not_reported_done(client, started):  # codex kb #2
    dev = enrolled(client)
    beat(client, dev["token"], FACTS)  # nothing allowed: a restart can't be proposed
    rb = runbooks.save(started, dev["deviceId"], "Restart it", "It stopped",
                       [{"say": "Restart", "job": {"type": "restart_container", "params": {"container": "x"}}}],
                       "nightlight", generation(started))
    tools, _ = _tools(started)
    used = _call(tools, "use_runbook", device_id=dev["deviceId"], runbook_id=rb["id"])
    assert used["status"] != "done" and used["failedSteps"] == 1
