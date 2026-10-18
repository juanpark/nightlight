"""From a freestyle run on a real Debian VM: notes reach the agent as dated history after the current readings, and a
look into a container whose logs aren't allowed ends with a card to allow them, never "read the logs yourself"."""

from datetime import datetime, timedelta, timezone

from nightlight_api import agent as agentlib, db, notebook, real
from conftest import generation
from test_knowledge import _call, _tools
from test_real import FACTS, beat, enrolled

APP = {**FACTS, "manage": "app", "allowedJobs": {"diagnose": ["pi-grafana-1"]}}


def _again(token):
    db.client().collection("helperTokens").document(real._sha(token)).update({"lastSeen": None})


# ------------------------------------------------------------------ notes are dated history, after current readings

def test_notes_and_profile_reach_the_agent_dated_and_after_the_readings(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], APP)
    did, gen = dev["deviceId"], generation(started)
    notebook.add(started, did, "/var/log/home-backup/backup-debug.log was 13.4 GB", "nightlight", gen)
    old = db.notes(started, did).limit(1).get()[0]
    old.reference.update({"at": datetime.now(timezone.utc) - timedelta(days=3, hours=1)})
    notebook.set_profile(started, did, "Debian VM; backups under /srv.", "nightlight", gen)
    tools, _ = _tools(started)
    got = _call(tools, "get_device", device_id=did)
    keys = list(got)
    assert keys.index("vitals") < keys.index("history") < keys.index("notebook")  # readings first, history after
    note = got["notebook"]["device"][0]
    assert "3 days ago; may be out of date" in note["written"]
    assert "less than an hour ago; may be out of date" in got["profile"]["written"]
    assert got["profile"]["text"] == "Debian VM; backups under /srv."


def test_age_in_words():
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    assert notebook.age(now - timedelta(minutes=5), now) == "less than an hour ago"
    assert notebook.age(now - timedelta(hours=1), now) == "1 hour ago"
    assert notebook.age(now - timedelta(hours=30), now) == "1 day ago"
    assert notebook.age(None, now) is None


# ------------------------------------------------------------------ logs not allowed: say so, and offer the card

def test_a_look_into_without_log_permission_says_so_and_how_to_ask(client, started, monkeypatch):
    dev = enrolled(client)
    beat(client, dev["token"], APP)
    monkeypatch.setattr(agentlib, "DIAGNOSE_WAIT", 0)
    monkeypatch.setattr(agentlib.actions, "await_diagnosis", lambda uid, aid: None)
    tools, _ = _tools(started)
    got = _call(tools, "look_into", device_id=dev["deviceId"], target="pi-grafana-1")
    assert "isn't allowed" in got["logs"] and "allow_log_reading" in got["logs"]


def test_the_owner_allows_reading_logs_with_one_card(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], APP)
    tools, ctx = _tools(started)
    got = _call(tools, "allow_log_reading", device_id=dev["deviceId"], target="pi-grafana-1")
    assert got["status"] == "pending" and "read the last log lines of pi-grafana-1" in got["plan"]
    r = client.post(f"/api/actions/{got['actionId']}/decide", json={"decision": "approve"})
    assert r.status_code == 202 and r.json()["status"] == "done" and r.json()["continuationTurnId"]
    d = db.device(started, dev["deviceId"]).get().to_dict()
    assert d["permissions"]["logs"] == ["pi-grafana-1"]
    a = db.action(started, got["actionId"]).get().to_dict()
    assert a["status"] == "done" and "may now read the log lines of pi-grafana-1" in a["result"]["summary"]
    _again(dev["token"])
    seen = beat(client, dev["token"], APP).json()
    assert seen["permissions"]["logs"] == ["pi-grafana-1"] and seen.get("jobs", []) == []  # never a device job
    later, _ = _tools(started, turn="turn_later")  # the same turn finds its own (done) card again
    again = _call(later, "allow_log_reading", device_id=dev["deviceId"], target="pi-grafana-1")
    assert again["status"] == "error" and "already allowed" in again["reason"]


def test_a_service_can_be_named_without_its_suffix_and_unknown_or_strict_ones_are_refused(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], APP)
    tools, _ = _tools(started)
    got = _call(tools, "allow_log_reading", device_id=dev["deviceId"], target="pihole-FTL")
    assert got["status"] == "pending" and "pihole-FTL.service" in got["plan"]
    assert "doesn't report" in _call(tools, "allow_log_reading", device_id=dev["deviceId"], target="nope")["reason"]
    strict = enrolled(client, "Strict box")
    beat(client, strict["token"], {**FACTS, "manage": "strict"})
    said = _call(tools, "allow_log_reading", device_id=strict["deviceId"], target="pi-grafana-1")["reason"]
    assert "nightlight allow logs" in said
