"""Links between devices on the map: how things relate, drawn by the owner (or seeded for the sample home), or seen
by the helpers (`source: "auto"`).

A link is layout, not device state: it changes nothing on any device. One link per ordered pair of devices (drawing
it again changes its kind). A link is "real" only when both ends are real devices; any other link belongs to the sample
home and goes away with it on a reset.

Automatic lines come from keyed fingerprints, never addresses: a helper reports `net`, the fingerprints of its own
local address, of its router's, and of the addresses it relies on (a Time Machine disk, a mounted shared folder, a
database it is connected to). A fingerprint is HMAC-SHA256 with the account's own key (`netKey`), so within one account
equal fingerprints mean the same address. A line the person drew is never changed, and an automatic line the person
deleted is not drawn again.
"""

import secrets
from datetime import datetime, timezone

from google.cloud import firestore

from . import db
from .errors import ApiError, conflict, not_found

KINDS = ("network", "backup", "depends", "power")  # connected through · backs up to · relies on · powered by
MAX_LINKS = 200
# Ports a helper may report a connection to (nightlight_helper.py NET_PORTS), in plain words. Remote login (22) is left
# out on purpose: someone administering a machine is not something it relies on.
SERVICE_PORTS = {445: "shared folders", 2049: "shared folders (NFS)", 548: "shared folders (AFP)",
                 873: "rsync backups", 5432: "PostgreSQL database", 3306: "MySQL database",
                 1883: "smart-home messages (MQTT)", 8123: "Home Assistant", 32400: "Plex", 9000: None}


def link_id(src: str, dst: str) -> str:
    return f"{src}__{dst}"


def _usable(d: dict | None, user: dict) -> bool:
    """A device the owner sees on the map: real and not archived, or in the current sample home."""
    if not d or d.get("archived"):
        return False
    return d.get("realm") == "real" or d.get("demoGeneration") == user.get("demoGeneration")


def put(uid: str, src: str, dst: str, kind: str, fence=None) -> dict:
    """Draw (or re-kind) one line. `fence(tx)` lets a chat turn write only while it still owns the conversation."""
    if kind not in KINDS:
        raise ApiError(422, "unknown_kind")
    if src == dst:
        raise ApiError(422, "same_device")
    if not all(isinstance(x, str) and db.DEVICE_ID.fullmatch(x) for x in (src, dst)):
        raise not_found()  # checked before any path is built from them
    ref = db.links(uid).document(link_id(src, dst))

    @firestore.transactional
    def run(tx):
        if fence:
            fence(tx)
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        a, b = (db.device(uid, x).get(transaction=tx) for x in (src, dst))
        ends = [s.to_dict() if s.exists else None for s in (a, b)]
        if not all(_usable(d, user) for d in ends):
            raise not_found()
        if any(d.get("realm") != "real" for d in ends) and user.get("demo", {}).get("state") != "ready":
            raise conflict("resetting", retryAfter=5)
        existing = ref.get(transaction=tx)
        if not existing.exists and len(list(db.links(uid).limit(MAX_LINKS).get(transaction=tx))) >= MAX_LINKS:
            raise ApiError(409, "too_many_links")
        real = all(d.get("realm") == "real" for d in ends)
        doc = {"from": src, "to": dst, "kind": kind, "realm": "real" if real else "sim", "source": "user",
               "demoGeneration": user.get("demoGeneration", 0), "createdAt": firestore.SERVER_TIMESTAMP}
        tx.set(ref, doc)
        return {"id": ref.id, **{k: v for k, v in doc.items() if k != "createdAt"}}

    return db.run_transaction(run)


def remove(uid: str, lid: str) -> None:
    """Delete a line. A sample-home line follows the same barrier as every other demo write: never while a reset is
    rebuilding the home, and never one from an older sample home. A deleted automatic line is not drawn again."""
    ref = db.links(uid).document(lid)

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        link = snap.to_dict() if snap.exists else None
        if not link:
            raise not_found()
        if link.get("realm") != "real":
            if user.get("demo", {}).get("state") != "ready":
                raise conflict("resetting", retryAfter=5)
            if link.get("demoGeneration") != user.get("demoGeneration"):
                raise not_found()
        if link.get("source") == "auto":
            tx.set(db.user(uid), {"dismissedLinks": firestore.ArrayUnion([lid])}, merge=True)
        tx.delete(ref)

    db.run_transaction(run)


def summary(uid: str, generation: int, names: dict) -> list[str]:
    """The map's lines in plain words, for the agent ("game-1 (Game server) backs up to nas-1 (NAS)")."""
    verb = {"network": "is connected through", "backup": "backs up to", "depends": "relies on", "power": "is powered by"}
    out = []
    for snap in db.links(uid).get():
        l = snap.to_dict()
        if l.get("realm") != "real" and l.get("demoGeneration") != generation:
            continue
        if l.get("from") in names and l.get("to") in names:
            seen = f" (seen by its helper: {l['why']})" if l.get("source") == "auto" and l.get("why") else ""
            out.append(f"- {l['from']} ({names[l['from']]}) {verb.get(l.get('kind'), 'is linked to')} "
                       f"{l['to']} ({names[l['to']]}){seen}")
    return sorted(out)


def same_network(devices: dict) -> list[str]:
    """Devices whose helpers report the same router while the router itself isn't on the map, in plain words."""
    selves = {(d.get("net") or {}).get("self") for d in devices.values()}
    groups = {}
    for i, d in devices.items():
        gateway = (d.get("net") or {}).get("gateway")
        if gateway and gateway not in selves:
            groups.setdefault(gateway, []).append(f"{i} ({d.get('name', i)})")
    return sorted(f"- {', '.join(sorted(names))} are on the same home network (the router isn't on the map; it may be "
                  "under Found nearby)" for names in groups.values() if len(names) >= 2)


# ------------------------------------------------------------------ lines the helpers see

RETRY_SECONDS = 60  # lines still due after a failed attempt are tried again by a later report, at most this often


def _net_ref(uid: str):
    return db.client().collection("netKeys").document(uid)


def net_state(tx, uid: str, changed: bool) -> tuple[str, bool]:
    """(the account's fingerprint key, whether lines should be worked out after this report).

    The key (32 random bytes, hex) is created on first use and kept outside `users/{uid}`, which browsers can read:
    only the account's own helpers receive it, in their report replies. A report whose fingerprints `changed` marks
    the account's lines as due in the same transaction that stores them; only a successful `infer` clears that, so a
    failed or interrupted attempt is retried by a later report (at most once a minute per account). Reads, then may
    write: call it after the transaction's other reads."""
    ref = _net_ref(uid)
    snap = ref.get(transaction=tx)
    doc = snap.to_dict() if snap.exists else {}
    keyless = not isinstance(doc.get("key"), str)  # never made, or the state was started elsewhere (mark_due)
    if keyless:
        doc = {**doc, "key": secrets.token_hex(32), "createdAt": firestore.SERVER_TIMESTAMP}
    tried = doc.get("triedAt")
    retry = bool(doc.get("linesDue")) and (tried is None or (datetime.now(timezone.utc) - tried).total_seconds()
                                           > RETRY_SECONDS)
    if changed or keyless:
        tx.set(ref, {**doc, **({"linesDue": True} if changed else {})})
    return doc["key"], changed or retry


def mark_due(tx, uid: str) -> None:
    """Something that can change the lines (a device added from Found nearby) happened in this transaction: the lines
    stay due until worked out, whatever happens to the attempt that follows. A write only: call after all reads."""
    tx.set(_net_ref(uid), {"linesDue": True}, merge=True)


def _why(reason: str) -> tuple[str, str]:
    """(kind, plain words) for one reason a helper gave."""
    if reason == "time_machine":
        return "backup", "Time Machine backs up here"
    if reason == "network_drive":
        return "depends", "uses its shared folder"
    port = int(reason.split(":", 1)[1])
    words = SERVICE_PORTS.get(port)
    return "depends", f"connects to its {words} (port {port})" if words else f"connects to port {port}"


def wanted(devices: dict) -> dict:
    """The lines the fingerprints show among these real devices: {link id: (from, to, kind, why)}."""
    by_self = {}
    for i, d in sorted(devices.items(), key=lambda x: x[1].get("kind") == "watched"):  # a helper's own device wins
        by_self.setdefault((d.get("net") or {}).get("self"), i)  # over the same box added from Found nearby
    by_self.pop(None, None)
    out = {}
    for i, d in devices.items():
        net = d.get("net") or {}
        for peer in net.get("peers") or []:
            dst = by_self.get(peer.get("tag"))
            if not dst or peer.get("tag") == net.get("self"):
                continue  # not on the map, or itself
            kind, why = _why(peer.get("why", ""))
            lid = link_id(i, dst)
            if lid not in out or (kind == "backup" and out[lid][2] != "backup"):
                out[lid] = (i, dst, kind, why)
        router = by_self.get(net.get("gateway"))
        if router and net.get("gateway") != net.get("self") and link_id(i, router) not in out:
            out[link_id(i, router)] = (i, router, "network", "its router: it reaches the internet through it")
    return out


def infer(uid: str) -> int:
    """Draw the lines the helpers' fingerprints show. Never touches a line the person drew (nor draws another between
    the same two devices), and never draws again one the person deleted. Lines stay until deleted. Returns how many
    lines were drawn or changed."""
    @firestore.transactional
    def run(tx):
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        state = _net_ref(uid).get(transaction=tx)
        devices = {s.id: s.to_dict() for s in db.devices(uid).get(transaction=tx)}
        existing = {s.id: s.to_dict() for s in db.links(uid).get(transaction=tx)}
        devices = {i: d for i, d in devices.items() if d.get("realm") == "real" and not d.get("archived")}
        dismissed = set(user.get("dismissedLinks") or [])
        drawn = {frozenset((l.get("from"), l.get("to"))) for l in existing.values() if l.get("source") != "auto"}
        count, changed = len(existing), 0
        for lid, (src, dst, kind, why) in wanted(devices).items():
            old = existing.get(lid)
            if lid in dismissed or frozenset((src, dst)) in drawn or (not old and count >= MAX_LINKS):
                continue
            if old and (old.get("kind"), old.get("why")) == (kind, why):
                continue
            tx.set(db.links(uid).document(lid), {"from": src, "to": dst, "kind": kind, "realm": "real",
                                                 "source": "auto", "why": why,
                                                 "demoGeneration": user.get("demoGeneration", 0),
                                                 "createdAt": firestore.SERVER_TIMESTAMP})
            count += not old
            changed += 1
        # A watched thing your devices reach the internet through is your router (unless you said otherwise).
        gateways = {(d.get("net") or {}).get("gateway") for d in devices.values()} - {None}
        for i, d in devices.items():
            if d.get("kind") == "watched" and (d.get("net") or {}).get("self") in gateways \
                    and d.get("role") != "router" and d.get("roleSetBy") != "user":
                rename = {"name": "Router"} if d.get("name") in (d.get("guess"), "Device with a web page") else {}
                tx.update(db.device(uid, i), {"role": "router", **rename,
                                              "purpose": "Your router: your devices reach the internet through it."})
                changed += 1
        if state.exists and state.to_dict().get("linesDue"):
            tx.update(_net_ref(uid), {"linesDue": False})  # done: only a success clears it
        return changed

    return db.run_transaction(run)


def infer_quietly(uid: str) -> None:
    """`infer` after a report or an added device: drawing lines must never break what just succeeded. A failure leaves
    the account's lines due, so a later report tries again."""
    try:
        _net_ref(uid).set({"triedAt": firestore.SERVER_TIMESTAMP}, merge=True)  # spaces out retries
        infer(uid)
    except Exception as e:
        import logging
        logging.getLogger(__name__).info("automatic lines not drawn: %s", type(e).__name__)


def touching(uid: str, device_id: str) -> list:
    """References of every link that has this device at either end (for purging a removed device)."""
    from google.cloud.firestore_v1.base_query import FieldFilter
    return [s.reference for f in ("from", "to")
            for s in db.links(uid).where(filter=FieldFilter(f, "==", device_id)).stream()]


def seed(tx, uid: str, generation: int, pairs: list) -> None:
    """The sample home's own links, written with its devices."""
    for src, dst, kind in pairs:
        tx.set(db.links(uid).document(link_id(src, dst)), {"from": src, "to": dst, "kind": kind, "realm": "sim",
                                                          "demoGeneration": generation,
                                                          "createdAt": firestore.SERVER_TIMESTAMP})
