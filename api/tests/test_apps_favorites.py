"""What an app is, in plain words (a fixed catalog: icon keys the web app draws, one line each); favourites on devices
and their apps; reading recent logs is part of the default presets, and can be switched off."""

from nightlight_api import apps, db
from test_real import FACTS, beat, enrolled


def test_known_apps_are_recognised_from_their_image_or_unit_and_unknown_ones_get_nothing():
    cases = {"lscr.io/linuxserver/plex:latest": "plex", "plexinc/pms-docker:1.41": "plex", "pihole-FTL": "pihole",
             "ghcr.io/home-assistant/home-assistant:stable": "homeassistant", "postgres:16": "database",
             "wg-quick@wg0": "wireguard", "tailscaled": "tailscale", "eclipse-mosquitto:2": "mqtt"}
    for name, icon in cases.items():
        assert apps.about(name)["icon"] == icon, name
    assert apps.about("complex-app:1") is None and apps.about("my-thing") is None and apps.about(None, "") is None
    assert apps.about("mystery:1", "plex")["icon"] == "plex"  # the image first, then the name
    assert all(icon in apps.ICONS for _p, icon, _l in apps.CATALOG)
    assert all(len(line) <= 120 for _p, _i, line in apps.CATALOG)


def test_a_devices_apps_carry_what_they_are(client, started):
    dev = enrolled(client, "Pi")
    beat(client, dev["token"], {**FACTS, "containers": [
        {"name": "media", "image": "plexinc/pms-docker:1.41", "state": "running", "status": "Up 2 days"},
        {"name": "thing", "image": "someone/thing:1", "state": "running", "status": "Up"}]})
    svcs = {s.to_dict()["name"]: s.to_dict() for s in db.services(started, dev["deviceId"]).get()}
    assert svcs["media"]["about"] == {"icon": "plex", "oneLiner": apps.about("plex")["oneLiner"], "source": "catalog"}
    assert "about" not in svcs["thing"]


def test_favourites_are_set_and_cleared_alone(client, started):
    dev = enrolled(client, "Pi")
    path = f"/api/devices/{dev['deviceId']}/layout"
    assert client.post(path, json={"favorite": True}).status_code == 200
    assert client.post(path, json={"favoriteApps": ["plex", "plex", "pihole"]}).status_code == 200
    d = db.device(started, dev["deviceId"]).get().to_dict()
    assert (d["favorite"], d["favoriteApps"]) == (True, ["plex", "pihole"])
    assert client.post(path, json={"favoriteApps": []}).status_code == 200
    assert client.post(path, json={"favorite": False}).status_code == 200
    d = db.device(started, dev["deviceId"]).get().to_dict()
    assert (d["favorite"], d["favoriteApps"]) == (False, [])
    assert client.post(path, json={"favoriteApps": [f"a{i}" for i in range(21)]}).status_code == 422
    assert client.post(path, json={"favoriteApps": [""]}).status_code == 422
    assert client.post(path, json={"favorite": "yes"}).status_code == 422


def test_sample_home_has_favourites_and_a_busy_device():
    from nightlight_api.template import HOME_PI
    mac = next(d for d in HOME_PI["devices"] if d["id"] == "mac-1")
    assert len(mac["services"]) >= 12 and mac["favorite"] is True
    assert set(mac["favoriteApps"]) <= {s["id"] for s in mac["services"]}
    assert any(s.get("findings") for s in mac["services"]) and any(s.get("updateAvailable") for s in mac["services"])
