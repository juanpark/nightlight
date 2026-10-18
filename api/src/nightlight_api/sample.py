"""The sample home's two real-world flows, simulated and always labelled so: "Look for devices nearby" (a scan seen
from the sample Raspberry Pi) and "Add a device" (a scripted install, then the same approve step a real device needs).

Everything here belongs to the sample home's current generation (`demoGeneration`), so a reset clears it, and it only
runs while the sample home is showing (template `home-pi`, state ready). It never touches real devices or pairing."""

import secrets
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

from . import db, links, sim
from .errors import ApiError, conflict, not_found
from .ids import new_id

FINDER = "pi-1"  # the sample device that "looks"
FINDER_NAME = "Raspberry Pi"
ROUTER = "router-1"  # the sample router already on the map
TTL = timedelta(hours=24)
PAIR_TTL = timedelta(minutes=10)

# What the Pi "finds", in the shape a real helper sends (real.save_discoveries): no addresses, fingerprints only.
FOUND = [
    {"cid": "5a3e00000001", "guess": "Router", "services": ["router", "web page"], "ports": [80, 443],
     "tag": "5a3e000000000000aa01", "hw": "5a3e000000000000bb01", "name": "RT-AX58U", "maker": "ASUS",
     "model": "RT-AX58U", "router": True},
    {"cid": "5a3e00000002", "guess": "Printer", "services": ["printer", "web page"], "ports": [631, 80],
     "tag": "5a3e000000000000aa02", "hw": "5a3e000000000000bb02", "name": "Brother HL-L2350DW", "maker": "Brother",
     "model": "HL-L2350DW"},
    {"cid": "5a3e00000003", "guess": "Speaker or TV", "services": ["AirPlay speaker or TV", "media player"],
     "ports": [7000], "tag": "5a3e000000000000aa03", "hw": "5a3e000000000000bb03", "name": "Living Room TV",
     "maker": "Samsung", "model": None},
    {"cid": "5a3e00000004", "guess": "Nintendo", "vendor": "Nintendo", "services": [], "ports": [],
     "tag": "5a3e000000000000aa04", "hw": "5a3e000000000000bb04", "name": None, "maker": None, "model": None},
    {"cid": "5a3e00000005", "guess": "Unknown device", "services": ["Apple device"], "ports": [],
     "tag": "5a3e000000000000aa05", "hw": "5a3e000000000000bb05", "name": "Mina's iPhone", "maker": "Apple",
     "model": None},
    {"cid": "5a3e00000006", "guess": "Unknown device", "vendor": "private address (likely a phone or laptop)",
     "services": [], "ports": [], "tag": "5a3e000000000000aa06", "hw": None, "name": None, "maker": None,
     "model": None},
]
WATCH_PORTS = (8123, 32400, 25565, 445, 631, 443, 80, 22, 7000)  # as real.WATCH_PORTS
ROLE = {"Printer": "printer", "Speaker or TV": "speaker", "Router": "router"}

# The devices "Add a device" can install, one per kind of computer.
NEW_DEVICES = {
    "linux": {
        "id": "laptop-1", "name": "Old laptop (Ubuntu)", "kind": "computer", "os": "Ubuntu 24.04 (simulated)",
        "purpose": "An old laptop you just added: it keeps the family's shared files in sync.",
        "health": "verified", "x": 640, "y": 520, "diskGb": 240, "baseUsedGb": 96, "diskConsumers": [],
        "vitals": {"cpu": 6, "mem": 41, "uptime": 300},
        "findings": [{"id": "f_os_updates", "check": "os_updates_waiting", "severity": "info",
                      "message": "Ubuntu has 23 updates waiting, 4 of them security fixes.",
                      "evidence": "apt: 23 upgradable, 4 from the security archive"}],
        "services": {
            "syncthing": {"name": "Syncthing", "category": "files", "status": "ok", "version": "1.27.2",
                          "updateAvailable": False,
                          "about": {"icon": "files", "oneLiner": "Syncthing: keeps folders in sync between computers.",
                                    "source": "catalog"}},
            "jellyfin": {"name": "jellyfin", "category": "containers", "kind": "container",
                         "image": "jellyfin/jellyfin:10.9.11", "status": "ok", "version": "10.9.11",
                         "updateAvailable": False},
        },
        "lines": ["$ curl -fsSL {web}/install.sh | sh -s -- {code}",
                  "Nightlight: downloading the helper…",
                  "Checking the helper's checksum (SHA-256)… ok",
                  "Installed the helper for this user (no admin rights needed).",
                  "",
                  "  Your code:  {code}",
                  "",
                  "  Open Nightlight > Add a device > Enter code, or scan this with your phone:",
                  "  {web}/pair?code={code}",
                  "",
                  "  Waiting for you to approve it (10 minutes)..."],
    },
    "mac": {
        "id": "macmini-2", "name": "Living-room Mac mini", "kind": "mac", "os": "macOS 15 (simulated)",
        "purpose": "A Mac mini under the TV you just added: it plays music and keeps a Time Machine backup.",
        "health": "verified", "x": 640, "y": 520, "diskGb": 512, "baseUsedGb": 188, "diskConsumers": [],
        "vitals": {"cpu": 4, "mem": 52, "uptime": 300},
        "findings": [{"id": "f_os_updates", "check": "os_updates_waiting", "severity": "info",
                      "message": "macOS 15.1 is available (you have 15.0.1).",
                      "evidence": "softwareupdate: macOS Sequoia 15.1 recommended"}],
        "services": {
            "time-machine": {"name": "Time Machine", "category": "files", "status": "ok", "version": "n/a",
                             "updateAvailable": False,
                             "about": {"icon": "backup", "oneLiner": "Time Machine: backs this Mac up to the NAS.",
                                       "source": "catalog"}},
            "plexamp": {"name": "Plexamp", "category": "media", "status": "ok", "version": "4.11.1",
                        "updateAvailable": False},
        },
        "lines": ["$ curl -fsSL {web}/install.sh | sh -s -- {code}",
                  "Nightlight: downloading the helper…",
                  "Checking the helper's checksum (SHA-256)… ok",
                  "Installed the helper for this user (no admin password needed).",
                  "",
                  "  Your code:  {code}",
                  "",
                  "  Open Nightlight > Add a device > Enter code, or scan this with your phone:",
                  "  {web}/pair?code={code}",
                  "",
                  "  Waiting for you to approve it (10 minutes)..."],
    },
}
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _sample(tx, uid: str) -> dict:
    """The user doc, when the sample home is showing and ready; else 409."""
    snap = db.user(uid).get(transaction=tx)
    user = snap.to_dict() if snap.exists else None
    if not user or user.get("template") != "home-pi":
        raise ApiError(409, "no_sample_home")
    if user.get("demo", {}).get("state") != "ready":
        raise conflict("resetting", retryAfter=5)
    return user


def _event(tx, uid: str, generation: int, device_id: str, kind: str, message: str) -> None:
    tx.set(db.events(uid).document(new_id("ev")), {"deviceId": device_id, "kind": kind, "severity": "info",
                                                   "message": message, "who": "you", "source": "demo",
                                                   "at": firestore.SERVER_TIMESTAMP, "demoGeneration": generation})


# ------------------------------------------------------------------ found nearby

def discover(uid: str) -> dict | None:
    """A simulated look from the sample Raspberry Pi: writes its discoveries doc (the real shape, `simulated: true`).
    Things already put on the map stay marked added. None when the sample home isn't showing."""
    ref = db.user(uid).collection("discoveries").document(FINDER)

    @firestore.transactional
    def run(tx):
        try:
            user = _sample(tx, uid)
        except ApiError:
            return None
        old = ref.get(transaction=tx)
        prev = old.to_dict() if old.exists else {}
        added = {it["cid"] for it in prev.get("items") or [] if it.get("added")} \
            if prev.get("demoGeneration") == user["demoGeneration"] else set()
        items = [{**it, "simulated": True, "added": it["cid"] in added} for it in deepcopy(FOUND)]
        tx.set(ref, {"items": items, "by": FINDER, "byName": FINDER_NAME, "simulated": True,
                     "demoGeneration": user["demoGeneration"], "at": firestore.SERVER_TIMESTAMP,
                     "expiresAt": _now() + TTL})
        _event(tx, uid, user["demoGeneration"], FINDER, "found",
               f"{FINDER_NAME} found {len(items)} thing(s) nearby you can add (simulated).")
        return {"deviceId": FINDER, "name": FINDER_NAME, "simulated": True}

    return db.run_transaction(run)


def add_found(uid: str, helper_id: str, cid: str, name: str | None) -> dict:
    """Put one simulated found thing on the map, watched by the sample Pi, answering like a real watched thing. The
    router is the one already on the map: watching it fills in the name and model it announced instead."""
    ref = db.user(uid).collection("discoveries").document(helper_id)

    @firestore.transactional
    def run(tx):
        user = _sample(tx, uid)
        gen = user["demoGeneration"]
        snap = ref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or not d.get("simulated") or d.get("demoGeneration") != gen or d["expiresAt"] < _now():
            raise not_found()
        item = next((it for it in d["items"] if it.get("cid") == cid), None)
        if not item:
            raise not_found()
        if item.get("added"):
            raise ApiError(409, "already_added")
        port = next((p for p in WATCH_PORTS if p in (item.get("ports") or [])), None)
        if port is None:
            raise ApiError(422, "no_check_port")
        rsnap = db.device(uid, ROUTER).get(transaction=tx) if item.get("router") else None
        tx.update(ref, {"items": [{**it, "added": it.get("cid") == cid or it.get("added")} for it in d["items"]]})
        if rsnap is not None and rsnap.exists:
            tx.update(rsnap.reference, {"name": item["name"], "seenName": item["name"], "maker": item.get("maker"),
                                        "model": item.get("model"), "services": item.get("services") or []})
            _event(tx, uid, gen, ROUTER, "joined",
                   f"Your router announced itself as {item['name']}; its name and model are on the map now.")
            return {"ok": True, "deviceId": ROUTER, "simulated": True}
        device_id = f"found-{cid[-4:]}"
        called = (name or item.get("name") or item.get("guess") or "Found device")[:40]
        role = ROLE.get(item.get("guess"), "other")
        n = sum(1 for it in d["items"] if it.get("added"))
        tx.set(db.device(uid, device_id), {
            "name": called, "kind": "watched", "role": role,
            "purpose": f"{_ROLE_WORDS.get(role, 'Something on your network')}. Watched by the {FINDER_NAME}.",
            "guess": item.get("guess"), "services": item.get("services") or [], "ports": item.get("ports") or [],
            "simulated": True, "watchedBy": FINDER, "cid": cid, "checkPort": port,
            "vendor": item.get("vendor"), "maker": item.get("maker"), "model": item.get("model"),
            "health": "verified", "status": "ok", "vitals": {"latencyMs": 4 + n}, "findings": [],
            "detail": f"Answers on port {port} (simulated check)",
            "version": 1, "x": 960, "y": 120 * n, "createdAt": firestore.SERVER_TIMESTAMP,
            "lastSeen": firestore.SERVER_TIMESTAMP, "demoGeneration": gen,
            **({"seenName": item["name"], "nameFromSeen": not name} if item.get("name") else {})})
        links.seed(tx, uid, gen, [(device_id, ROUTER, "network")])
        _event(tx, uid, gen, device_id, "joined", f"{called} joined your map, watched by the {FINDER_NAME}.")
        return {"ok": True, "deviceId": device_id, "simulated": True}

    return db.run_transaction(run)


_ROLE_WORDS = {"router": "Your router: your devices reach the internet through it", "printer": "A printer",
               "speaker": "A TV or speaker", "other": "Something on your network"}


# ------------------------------------------------------------------ add a device (simulated install)

def _pairs(uid: str):
    return db.user(uid).collection("samplePairs")


def add_device(uid: str, os_name: str, web: str) -> dict:
    """Start a simulated install: the lines a real install prints, and a pending pairing to approve."""
    spec = NEW_DEVICES[os_name]
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    shown = f"{code[:4]}-{code[4:]}"
    expires = _now() + PAIR_TTL

    @firestore.transactional
    def run(tx):
        user = _sample(tx, uid)
        if db.device(uid, spec["id"]).get(transaction=tx).exists:
            raise ApiError(409, "already_added", deviceId=spec["id"])
        tx.set(_pairs(uid).document(code), {"os": os_name, "name": spec["name"], "status": "waiting",
                                            "demoGeneration": user["demoGeneration"], "expiresAt": expires})

    db.run_transaction(run)
    return {"simulated": True, "code": shown, "name": spec["name"], "os": spec["os"],
            "expiresAt": _iso(expires),
            "transcript": [line.format(web=web.rstrip("/"), code=shown) for line in spec["lines"]]}


def _pair(tx, uid: str, code: str):
    ref = _pairs(uid).document(code.replace("-", "").strip().upper())
    snap = ref.get(transaction=tx) if tx is not None else ref.get()
    d = snap.to_dict() if snap.exists else None
    if not d or d["expiresAt"] < _now():
        return ref, None
    return ref, d


def pair_preview(uid: str, code: str) -> dict:
    """Same shape as the real GET /api/devices/pair/{code}, plus `simulated`."""
    _, d = _pair(None, uid, code)
    if not d or d["status"] != "waiting":
        raise not_found()
    return {"name": d["name"], "os": NEW_DEVICES[d["os"]]["os"], "expiresAt": _iso(d["expiresAt"]),
            "continues": None, "simulated": True}


def pair_decide(uid: str, code: str, approve: bool) -> dict:
    """Same shape as the real POST /api/devices/pair/{code}, plus `simulated` and the new `deviceId` on approve."""

    @firestore.transactional
    def run(tx):
        user = _sample(tx, uid)
        ref, d = _pair(tx, uid, code)
        if not d or d.get("demoGeneration") != user["demoGeneration"]:
            raise not_found()
        if d["status"] != "waiting":
            raise ApiError(409, "already_decided")
        spec = deepcopy(NEW_DEVICES[d["os"]])
        dref = db.device(uid, spec["id"])
        exists = dref.get(transaction=tx).exists
        tx.update(ref, {"status": "approved" if approve else "denied"})
        if not approve:
            return {"ok": True, "continues": None, "simulated": True}
        if exists:
            raise ApiError(409, "already_added", deviceId=spec["id"])
        gen = user["demoGeneration"]
        device_id, services = spec.pop("id"), spec.pop("services")
        for k in ("lines",):
            spec.pop(k)
        device, services = sim.refresh({**spec, "id": device_id, "version": 1, "simulated": True,
                                        "demoGeneration": gen}, services)
        device.pop("id")
        tx.set(dref, {**device, "lastSeen": firestore.SERVER_TIMESTAMP, "createdAt": firestore.SERVER_TIMESTAMP})
        for svc_id, svc in services.items():
            tx.set(db.services(uid, device_id).document(svc_id), {**svc, "demoGeneration": gen})
        links.seed(tx, uid, gen, [(device_id, ROUTER, "network")])
        _event(tx, uid, gen, device_id, "joined", f"{spec['name']} joined your map (simulated install).")
        return {"ok": True, "continues": None, "simulated": True, "deviceId": device_id}

    return db.run_transaction(run)
