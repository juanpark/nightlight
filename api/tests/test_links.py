"""Lines between devices on the map: drawn by the owner, seeded for the sample home, gone with the sample home."""

from nightlight_api import db, demo


def _links(uid):
    return {s.id: s.to_dict() for s in db.links(uid).get()}


def _real(uid, device_id):
    db.device(uid, device_id).set({"name": device_id, "realm": "real", "status": "ok"})


def test_the_sample_home_comes_with_its_links(started):
    got = _links(started)
    assert got["game-1__nas-1"]["kind"] == "backup" and got["pi-1__router-1"]["kind"] == "network"
    assert all(v["realm"] == "sim" for v in got.values())


def test_draw_change_and_remove_a_link(client, started):
    r = client.post("/api/links", json={"from": "nvr-1", "to": "nas-1", "kind": "backup"})
    assert r.status_code == 201 and r.json()["id"] == "nvr-1__nas-1"
    r = client.post("/api/links", json={"from": "nvr-1", "to": "nas-1", "kind": "depends"})  # same pair: new kind
    assert _links(started)["nvr-1__nas-1"]["kind"] == "depends"
    assert client.delete("/api/links/nvr-1__nas-1").json() == {"ok": True}
    assert "nvr-1__nas-1" not in _links(started)
    assert client.delete("/api/links/nvr-1__nas-1").status_code == 404


def test_bad_links_are_refused(client, started):
    assert client.post("/api/links", json={"from": "pi-1", "to": "pi-1", "kind": "network"}).status_code == 422
    assert client.post("/api/links", json={"from": "pi-1", "to": "nas-1", "kind": "love"}).status_code == 422
    assert client.post("/api/links", json={"from": "pi-1", "to": "ghost", "kind": "network"}).status_code == 404


def test_a_reset_keeps_links_between_real_devices_only(client, started):
    _real(started, "box-a")
    _real(started, "box-b")
    assert client.post("/api/links", json={"from": "box-a", "to": "box-b", "kind": "network"}).json()["realm"] == "real"
    assert client.post("/api/links", json={"from": "box-a", "to": "nas-1", "kind": "backup"}).json()["realm"] == "sim"
    demo.reset(started)
    got = _links(started)
    assert "box-a__box-b" in got and "box-a__nas-1" not in got
    assert "game-1__nas-1" in got  # the new sample home brings its own again


def test_sample_lines_cannot_be_deleted_while_the_home_resets(client, started):
    db.user(started).update({"demo.state": "resetting"})
    assert client.delete("/api/links/pi-1__router-1").status_code == 409
    db.user(started).update({"demo.state": "ready"})
    assert client.delete("/api/links/pi-1__router-1").status_code == 200


def test_a_line_from_an_older_sample_home_is_not_found(client, started):
    db.links(started).document("old-1__old-2").set({"from": "old-1", "to": "old-2", "kind": "network", "realm": "sim",
                                                     "demoGeneration": -1})
    assert client.delete("/api/links/old-1__old-2").status_code == 404


def test_the_agent_sees_the_map_lines_in_plain_words(started):
    from nightlight_api import agent as agentlib, db as dbm
    gen = dbm.user(started).get().to_dict()["demoGeneration"]
    text = agentlib.fleet_summary(started, gen)
    assert "How they connect" in text and "game-1 (Game server) backs up to nas-1 (NAS)" in text


def test_a_stale_turn_cannot_draw_lines(started):
    import pytest
    from nightlight_api import links as linklib
    from nightlight_api.errors import ApiError

    def stale(tx):
        raise ApiError(409, "stale")
    with pytest.raises(ApiError):
        linklib.put(started, "nvr-1", "nas-1", "backup", fence=stale)
    assert "nvr-1__nas-1" not in _links(started)
