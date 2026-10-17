"""A device that stopped reporting: the agent gets since-when and the neighbours; the return says restart or not."""

from datetime import datetime, timedelta, timezone

from nightlight_api import agent, db, real
from conftest import generation
from test_real import FACTS, beat, enrolled


def _now():
    return datetime.now(timezone.utc)


def test_back_words_tell_a_restart_from_an_outage():
    assert real.back_words(_now() - timedelta(hours=2), 600)["restarted"] is True
    assert real.back_words(_now() - timedelta(minutes=30), 5 * 86400)["restarted"] is False
    assert real.back_words(None, 10)["restarted"] is None


def test_summary_says_how_long_and_who_else_reports(client, started):
    mini, pi = enrolled(client, "Mac mini"), enrolled(client, "Pi")
    for dev in (mini, pi):
        beat(client, dev["token"], FACTS)
        db.device(started, dev["deviceId"]).update({"tags": ["Home"]})
    db.device(started, mini["deviceId"]).update({"lastSeen": _now() - timedelta(hours=3)})
    text = agent.fleet_summary(started, generation(started))
    line = next(ln for ln in text.splitlines() if "Mac mini" in ln)
    assert "NOT REPORTING" in line and "silent for 3 hours" in line and "devices tagged Home still reporting: Pi" in line


def test_coming_back_records_whether_it_restarted(client, started):
    dev = enrolled(client)
    beat(client, dev["token"], FACTS)
    db.device(started, dev["deviceId"]).update({"lastSeen": _now() - timedelta(hours=1), "watchState": "silent"})
    db.client().collection("helperTokens").document(real._sha(dev["token"])).update({"lastSeen": None})
    beat(client, dev["token"], {**FACTS, "uptimeSec": 300})
    d = db.device(started, dev["deviceId"]).get().to_dict()
    assert d["lastGap"]["restarted"] is True
    back = [e.to_dict()["message"] for e in db.events(started).get() if e.to_dict().get("kind") == "back"]
    assert back and "restarted" in back[0]


def test_disk_forecast_and_escalation():
    now = _now()
    trend, to_full = real.disk_forecast([{"at": now - timedelta(hours=3), "pct": 88.0}], 94.0, now)
    assert 2.5 < to_full < 3.5 and trend[-1]["pct"] == 94.0
    f = real.checks({"diskPct": 99.0})
    real.escalate_disk(f, 99.0, None)
    assert "may freeze or crash" in f[0]["message"] and f[0]["severity"] == "crit"
    g = real.checks({"diskPct": 94.0})
    real.escalate_disk(g, 94.0, 3.0)
    assert "full in about 3 hours" in g[0]["message"]
    assert real.disk_forecast([], 50.0, now)[1] is None


def test_silent_device_with_a_full_disk_names_the_likely_cause(client, started):
    dev = enrolled(client, "Mac mini")
    beat(client, dev["token"], {**FACTS, "diskPct": 100.0})
    db.device(started, dev["deviceId"]).update({"lastSeen": _now() - timedelta(hours=5)})
    line = next(ln for ln in agent.fleet_summary(started, generation(started)).splitlines() if "Mac mini" in ln)
    assert "last known: disk 100%" in line and "most likely cause" in line


def test_after_a_restart_nightlight_looks_by_itself_and_writes_it_down(client, started):
    dev = enrolled(client, "Mac mini")
    offers = {**FACTS, "diskPct": 99.0, "allowedJobs": {"inspect": ["disk", "restarts"]}}
    beat(client, dev["token"], offers)
    db.device(started, dev["deviceId"]).update({"lastSeen": _now() - timedelta(hours=5), "watchState": "silent"})
    db.client().collection("helperTokens").document(real._sha(dev["token"])).update({"lastSeen": None})
    beat(client, dev["token"], {**offers, "diskPct": 88.0, "uptimeSec": 600})  # back, after a restart
    looks = [s for s in db.actions(started).get() if s.to_dict().get("playbook") == "after_restart"]
    assert len(looks) == 1 and looks[0].to_dict()["status"] == "approved" and looks[0].to_dict()["sessionId"] is None
    db.client().collection("helperTokens").document(real._sha(dev["token"])).update({"lastSeen": None})
    jobs = beat(client, dev["token"], offers).json()["jobs"]
    assert jobs[0]["params"] == {"what": ["restarts", "disk"]}
    out = ("How it last started:\nThe last start was NOT clean (no shutdown recorded just before it)\n"
           "Crash reports: 2026-10-17 08:37 (kernel panic, report written)")
    client.post(f"/helper/jobs/{looks[0].id}/result", json={"ok": True, "summary": "Checked", "output": out},
                headers={"X-Device-Token": dev["token"]})
    ev = [e.to_dict()["message"] for e in db.events(started).get() if e.to_dict().get("kind") == "looked"]
    notes = [n.to_dict()["text"] for n in db.notes(started, dev["deviceId"]).get()]
    assert ev and "wasn't clean" in ev[0] and "99% full just before" in ev[0]
    assert notes and "Why it restarted" in notes[0]


def test_a_failing_post_mortem_never_breaks_a_report(client, started, monkeypatch):  # review expert #8
    dev = enrolled(client)
    offers = {**FACTS, "allowedJobs": {"inspect": ["disk", "restarts"]}}
    beat(client, dev["token"], offers)
    db.device(started, dev["deviceId"]).update({"lastSeen": _now() - timedelta(hours=2), "watchState": "silent"})
    db.client().collection("helperTokens").document(real._sha(dev["token"])).update({"lastSeen": None})
    from nightlight_api import actions
    monkeypatch.setattr(actions, "request_inspection", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = beat(client, dev["token"], {**offers, "uptimeSec": 60})
    assert r.status_code == 200 and r.json()["ok"] is True
