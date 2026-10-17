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
