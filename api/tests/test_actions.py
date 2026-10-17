import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from nightlight_api import actions, db, demo
from nightlight_api.errors import ApiError
from nightlight_api.template import HOME_PI
from conftest import device, propose, trust


def test_start_seeds_the_sample_home(started):
    uid = started
    assert len(db.devices(uid).get()) == len(HOME_PI["devices"]) == 6
    pi = device(uid)
    assert pi["vitals"]["diskPct"] == 94 and pi["status"] == "crit" and pi["demoGeneration"] == 1
    assert trust(uid)["level"] == "ask"
    assert demo.start(uid)["demoGeneration"] == 1  # idempotent while ready


def test_approve_once_then_replay_and_conflict(started):
    uid = started
    a = propose(uid)
    assert a["status"] == "pending" and a["riskClass"] == "routine"
    code, body = actions.decide(uid, a["id"], "approve")
    assert code == 202 and body["status"] == "done" and body["continuationTurnId"] == f"cont_{a['id']}"
    pi = device(uid)
    assert pi["vitals"]["diskPct"] == 61 and pi["version"] == 2
    assert trust(uid)["successes"] == [a["id"]]
    cont = db.turns(uid, "sess_test").document(f"cont_{a['id']}").get().to_dict()
    assert cont["status"] == "queued" and cont["kind"] == "event" and cont["event"] == "job_finished"
    assert actions.decide(uid, a["id"], "approve") == (200, body)
    with pytest.raises(ApiError) as e:
        actions.decide(uid, a["id"], "deny")
    assert e.value.code == "decision_conflict"


def test_concurrent_approves_mutate_once(started):
    uid = started
    a = propose(uid)
    with ThreadPoolExecutor(10) as pool:
        results = list(pool.map(lambda _: actions.decide(uid, a["id"], "approve"), range(10)))
    assert sorted(c for c, _ in results) == [200] * 9 + [202]
    assert len({json.dumps(b, sort_keys=True) for _, b in results}) == 1
    assert device(uid)["version"] == 2 and trust(uid)["successes"] == [a["id"]]


def test_approve_racing_deny_has_one_winner(started):
    uid = started
    a = propose(uid)

    def go(d):
        try:
            return actions.decide(uid, a["id"], d)[0]
        except ApiError as e:
            return e.code

    with ThreadPoolExecutor(2) as pool:
        outcomes = sorted(map(str, pool.map(go, ["approve", "deny"])))
    assert outcomes == ["202", "decision_conflict"]


def test_deny_changes_nothing(started):
    uid = started
    a = propose(uid)
    code, body = actions.decide(uid, a["id"], "deny", "not now")
    assert code == 202 and body["status"] == "denied"
    assert device(uid)["version"] == 1 and trust(uid)["successes"] == []
    assert db.turns(uid, "sess_test").document(f"cont_{a['id']}").get().exists


def test_card_goes_stale_when_device_changes(started):
    uid = started
    a = propose(uid)
    demo.inject(uid, "disk_full", "pi-1")
    with pytest.raises(ApiError) as e:
        actions.decide(uid, a["id"], "approve")
    assert e.value.code == "stale"
    assert db.action(uid, a["id"]).get().to_dict()["status"] == "stale"


def test_same_turn_finds_the_same_action(started):
    uid = started
    a = propose(uid, turn="turn_fixed")
    b = propose(uid, turn="turn_fixed")
    cards = lambda: [s for s in db.actions(uid).get() if not s.to_dict().get("seeded")]  # noqa: E731 (not the sample past)
    assert a["id"] == b["id"] and len(cards()) == 1
    c = propose(uid, turn="turn_other")  # another turn while the card waits: the same card again
    assert c["id"] == a["id"] and len(cards()) == 1


def _earn_offer(uid):
    for _ in range(3):
        demo.inject(uid, "disk_full", "pi-1")
        a = propose(uid)
        assert actions.decide(uid, a["id"], "approve")[0] == 202
    return trust(uid)


def test_promotion_offer_accept_and_auto_run(client, started):
    uid = started
    t = _earn_offer(uid)
    assert t["offer"] and len(t["offer"]["successes"]) == 3
    r = client.post("/api/trust/rotate_logs/promotion", json={"accept": True, "offerId": t["offer"]["offerId"]})
    assert r.status_code == 200 and r.json()["level"] == "auto"
    demo.inject(uid, "disk_full", "pi-1")
    version = device(uid)["version"]
    auto = propose(uid)
    assert auto["status"] == "done" and auto["decision"]["by"] == "auto" and "continuationTurnId" not in auto
    assert device(uid)["version"] == version + 1
    assert len(trust(uid)["successes"]) == 3  # automatic runs never count
    again = propose(uid, turn=auto["turnId"])  # recovery re-runs the same turn: no second effect
    assert again["id"] == auto["id"] and device(uid)["version"] == version + 1


def test_automatic_failure_demotes(client, started):
    uid = started
    t = _earn_offer(uid)
    client.post("/api/trust/rotate_logs/promotion", json={"accept": True, "offerId": t["offer"]["offerId"]})
    demo.inject(uid, "disk_full", "pi-1")
    demo.inject(uid, "logs_locked", "pi-1")
    failed = propose(uid)
    assert failed["status"] == "failed" and failed["decision"]["by"] == "auto"
    t = trust(uid)
    assert t["level"] == "ask_new" and t["successes"] == [] and t["failures"] == 1
    assert device(uid)["vitals"]["diskPct"] == 94 and "simFailNext" not in device(uid)


def test_obsolete_offers_are_rejected(client, started):
    uid = started
    offer = _earn_offer(uid)["offer"]["offerId"]
    demo.inject(uid, "disk_full", "pi-1")
    demo.inject(uid, "logs_locked", "pi-1")
    a = propose(uid)
    actions.decide(uid, a["id"], "approve")  # human-approved failure withdraws the offer
    r = client.post("/api/trust/rotate_logs/promotion", json={"accept": True, "offerId": offer})
    assert r.status_code == 409 and r.json()["code"] == "offer_obsolete"

    offer2 = _earn_offer(uid)["offer"]["offerId"]
    demo.reset(uid)
    r = client.post("/api/trust/rotate_logs/promotion", json={"accept": True, "offerId": offer2})
    assert r.status_code == 409 and r.json()["code"] == "offer_obsolete"


def test_trust_precedence_and_ask_new(client, started):
    uid = started
    assert client.put("/api/trust/rotate_logs", json={"level": "auto"}).status_code == 200
    assert client.put("/api/trust/rotate_logs", json={"level": "ask", "deviceId": "pi-1"}).status_code == 200
    assert propose(uid)["status"] == "pending"  # device override beats the job's level
    r = client.put("/api/trust/rotate_logs", json={"level": "ask_new", "deviceId": "pi-1", "svcId": "teslamate"})
    assert r.status_code == 200
    a = propose(uid)
    assert a["status"] == "pending"  # ask_new: not approved on this scope yet
    actions.decide(uid, a["id"], "approve")
    demo.inject(uid, "disk_full", "pi-1")
    assert propose(uid)["status"] == "done"  # same parameterless job, same scope: runs on its own


def test_validation_and_ownership(client, started):
    r = client.post("/api/actions/act_nope/decide", json={"decision": "approve", "uid": "someone"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_body"
    assert r.json()["detail"][0]["loc"] == ["body", "uid"]
    r = client.post("/api/actions/act_nope/decide", json={"decision": "approve"})
    assert r.status_code == 404 and r.json() == {"error": "not_found", "code": "not_found"}
    demo.start("someone_else")
    foreign = propose("someone_else")
    r = client.post(f"/api/actions/{foreign['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 404  # another user's action looks exactly like a missing one
    assert db.action("someone_else", foreign["id"]).get().to_dict()["status"] == "pending"


def test_asking_for_the_same_fix_again_shows_the_waiting_card(started):
    # Two questions (or two chats) that lead to the same fix put up one card, not twins.
    first = propose(started, turn="turn_a")
    again = propose(started, turn="turn_b", session="sess_other")
    assert again["id"] == first["id"] and again["status"] == "pending"
    from nightlight_api import actions as acts
    acts.decide(started, first["id"], "deny")
    fresh = propose(started, turn="turn_c")  # once it's decided, asking again is a new card
    assert fresh["id"] != first["id"]
