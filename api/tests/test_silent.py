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
