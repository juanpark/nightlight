"""Real devices: enrolment, device tokens and heartbeats from the read-only helper.

A device joins with a one-time code its owner created in the app; it receives a random token that only it keeps (we
store a hash). Heartbeats carry an allowlisted set of health facts; deterministic checks turn them into findings.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import re

from . import db, links, release
from .errors import ApiError, not_found
from .ids import action_id as make_action_id, new_id, proposal_key
from .redact import scrub_value

CODE_TTL = timedelta(minutes=10)
CODES_PER_HOUR = 10
HEARTBEAT_MIN_SECONDS = 20
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no look-alikes (0/O, 1/I/L)
CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
TARGET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,99}$")  # a container or a system service (unit) name
CHAT_ACTIVE = timedelta(minutes=5)  # while the owner chats, helpers check for work every few seconds
FAST_POLL_SECONDS = 5
CLAIM_MIN_SECONDS = 4

# What a real device can be asked to do is declared in capabilities.py; the card builders for its jobs live here.
# The helper's fixed clean-ups (job `fix`, params {"recipe": name}). Each removes only things that come back on their
# own, except the Trash (what the owner already threw away). Words for the approval card.
FIX = {
    "empty_trash": ("Empty the Trash", "Deletes everything in the Trash", "Can't be undone: files in the Trash are "
                    "deleted for good. Look in the Trash first if you're unsure."),
    "brew_cleanup": ("Clear Homebrew's old downloads", "Runs \"brew cleanup -s\": removes old versions and cached "
                     "downloads", "Nothing to undo: Homebrew downloads again what it needs."),
    "npm_cache": ("Clear the npm cache", "Runs \"npm cache clean --force\"",
                  "Nothing to undo: npm downloads packages again when needed."),
    "xcode_build_data": ("Clear Xcode's build data", "Empties Xcode's DerivedData folder",
                         "Nothing to undo: Xcode rebuilds it on the next build (the first build is slower)."),
    "docker_prune": ("Remove Docker's leftover images", "Runs \"docker image prune -f\": removes only untagged "
                     "images (leftovers from updates and rebuilds) that no container uses", "Nothing to undo: "
                     "images with a name and all containers are not touched."),
    "apt_clean": ("Clear downloaded system updates", "Runs \"sudo apt-get clean\": removes downloaded package files",
                  "Nothing to undo: installed software is not touched."),
    "journal_vacuum": ("Shrink the system log", "Runs \"sudo journalctl --vacuum-size=200M\": keeps the newest "
                       "200 MB of system logs", "Can't be undone: older log entries are deleted."),
}
# Read-only and owner-allowed per target on the device: no approval card. `logs` additionally lets the helper send the
# last log lines (scrubbed on the device); without it only structured status leaves the device.
ALLOW_KEYS = ("restart_container", "restart_service", "diagnose", "logs", "inspect", "fix", "update")
# The helper's fixed read-only checks (`inspect`); it runs only these names, at most MAX_INSPECT per job.
INSPECT = {"disk": "which known folders take the most space", "processes": "which programs use the most memory and CPU",
           "updates": "which updates are waiting (can take up to a minute)", "docker": "how much space Docker uses",
           "network": "whether name lookup (DNS) and the internet work", "load": "how busy the processor is",
           "failed": "which services or background items keep failing",
           "home": "the biggest folders in the home folder (and its Library), outside protected ones",
           "restarts": "when it last started, whether that was after a crash, and crash reports by date"}
MAX_INSPECT = 4

# Plain names for system services people commonly run at home.
FRIENDLY = {
    "pihole-FTL": "Pi-hole ad blocker", "lighttpd": "web server", "docker": "Docker", "ssh": "remote login (SSH)",
    "sshd": "remote login (SSH)", "home-assistant": "Home Assistant", "homebridge": "Homebridge",
    "wg-quick@wg0": "WireGuard VPN", "smbd": "file sharing (Samba)", "nfs-server": "file sharing (NFS)",
    "cron": "scheduled jobs", "tailscaled": "Tailscale VPN", "zerotier-one": "ZeroTier VPN",
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def codes_ref():
    return db.client().collection("enrolCodes")


def tokens_ref():
    return db.client().collection("helperTokens")


# ------------------------------------------------------------------ enrolment

def create_code(uid: str) -> dict:
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    now = _now()
    hour = now.strftime("%Y%m%d%H")
    counter = db.user(uid).collection("quota").document(f"enrol_{hour}")

    @firestore.transactional
    def run(tx):
        user = db.user(uid).get(transaction=tx)
        c = counter.get(transaction=tx)
        if not user.exists:
            raise not_found()
        n = (c.to_dict() or {}).get("count", 0) if c.exists else 0
        if n >= CODES_PER_HOUR:
            raise ApiError(429, "quota_uid", retryAfter=3600 - now.minute * 60)
        tx.set(counter, {"count": n + 1})
        tx.set(codes_ref().document(_sha(code)), {"uid": uid, "expiresAt": now + CODE_TTL, "used": False,
                                                   "createdAt": firestore.SERVER_TIMESTAMP})

    db.run_transaction(run)
    return {"code": f"{code[:4]}-{code[4:]}", "expiresAt": (now + CODE_TTL).isoformat().replace("+00:00", "Z")}


def enrol(code: str, name: str) -> dict:
    """Redeem a one-time code exactly once; create the device and its token. The token is returned only here."""
    normalized = code.replace("-", "").strip().upper()
    ref = codes_ref().document(_sha(normalized))
    token = secrets.token_urlsafe(32)
    device_id = new_id("dev").lower()

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        data = snap.to_dict() if snap.exists else None
        if not data or data.get("used") or data["expiresAt"] < _now():
            raise ApiError(401, "invalid_code")  # unknown, used or expired look the same
        uid = data["uid"]
        tx.update(ref, {"used": True, "usedAt": firestore.SERVER_TIMESTAMP, "deviceId": device_id})
        _create_device(tx, uid, device_id, token, name)
        return uid

    db.run_transaction(run)
    return {"deviceId": device_id, "token": token}


def _create_device(tx, uid: str, device_id: str, token: str, name: str) -> None:
    """The device record and its token (stored hashed). Shared by enrolment and pairing."""
    event(tx, uid, device_id, "joined", "info", f"{name} joined your Nightlight map.", who="you")
    tx.set(db.client().collection("realDevices").document(f"{uid}__{device_id}"), {"uid": uid, "deviceId": device_id})
    tx.set(tokens_ref().document(_sha(token)), {"uid": uid, "deviceId": device_id, "revoked": False,
                                                "createdAt": firestore.SERVER_TIMESTAMP, "lastSeen": None})
    tx.set(db.device(uid, device_id), {
        "name": name, "kind": "computer", "purpose": "A real device reporting through the Nightlight helper.",
        "realm": "real", "simulated": False, "health": "unknown", "status": "offline", "vitals": {},
        "findings": [], "version": 1, "x": 420, "y": 80, "createdAt": firestore.SERVER_TIMESTAMP,
        "lastSeen": None, "registered": True})


# ------------------------------------------------------------------ pairing (the device shows a code)
# The OAuth device-authorization pattern: the device asks for a short code, the owner approves it in the app (typed
# or by scanning a QR with a phone), and the device, polling with a secret only it holds, then receives its token.
# The token is created at that moment and never stored in plaintext.

PAIR_TTL = timedelta(minutes=10)
PAIR_PER_IP_HOUR = 20
PAIR_CHECKS_PER_UID_HOUR = 30  # previews + decisions: guessing an 8-character code is hopeless at this rate
POLL_MIN_SECONDS = 2  # the device is told 3


def _count_check(uid: str) -> None:
    """Budget for looking up or deciding codes (RFC 8628 §5.1: limit guessing)."""
    now = _now()
    ref = db.user(uid).collection("quota").document(f"pair_{now.strftime('%Y%m%d%H')}")

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        n = (snap.to_dict() or {}).get("count", 0) if snap.exists else 0
        if n >= PAIR_CHECKS_PER_UID_HOUR:
            raise ApiError(429, "quota_uid", retryAfter=3600 - now.minute * 60)
        tx.set(ref, {"count": n + 1})

    db.run_transaction(run)


def pairs_ref():
    return db.client().collection("pairRequests")


def pair_start(name: str, os_name: str | None, ip: str) -> dict:
    now = _now()
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    poll_secret = secrets.token_urlsafe(32)
    bucket = db.client().collection("pairLimits").document(f"{_sha(ip)[:32]}_{now.strftime('%Y%m%d%H')}")

    @firestore.transactional
    def run(tx):
        b = bucket.get(transaction=tx)
        n = (b.to_dict() or {}).get("count", 0) if b.exists else 0
        if n >= PAIR_PER_IP_HOUR:
            raise ApiError(429, "quota_ip", retryAfter=3600 - now.minute * 60)
        tx.set(bucket, {"count": n + 1, "expiresAt": now + timedelta(hours=2)})
        tx.set(pairs_ref().document(_sha(code)), {"pollHash": _sha(poll_secret), "name": name, "os": os_name,
                                                   "status": "waiting", "uid": None, "expiresAt": now + PAIR_TTL,
                                                   "createdAt": firestore.SERVER_TIMESTAMP})

    db.run_transaction(run)
    return {"code": f"{code[:4]}-{code[4:]}", "pollSecret": poll_secret, "interval": 3,
            "expiresAt": (now + PAIR_TTL).isoformat().replace("+00:00", "Z")}


def _pair_doc(tx, code: str):
    ref = pairs_ref().document(_sha(code.replace("-", "").strip().upper()))
    snap = ref.get(transaction=tx) if tx is not None else ref.get()  # an empty transaction is falsy
    data = snap.to_dict() if snap.exists else None
    if not data or data["expiresAt"] < _now():
        return ref, None
    return ref, data


def pair_preview(uid: str, code: str) -> dict:
    _count_check(uid)
    _, data = _pair_doc(None, code)
    if not data or data["status"] != "waiting":
        raise not_found()
    return {"name": data["name"], "os": data.get("os"),
            "expiresAt": data["expiresAt"].isoformat().replace("+00:00", "Z")}


def pair_decide(uid: str, code: str, approve: bool) -> dict:
    _count_check(uid)

    @firestore.transactional
    def run(tx):
        ref, data = _pair_doc(tx, code)
        if not data:
            raise not_found()
        if data["status"] != "waiting":
            raise ApiError(409, "already_decided")
        tx.update(ref, {"status": "approved" if approve else "denied", "uid": uid if approve else None,
                        "decidedAt": firestore.SERVER_TIMESTAMP})

    db.run_transaction(run)
    return {"ok": True}


def pair_poll(code: str, poll_secret: str) -> tuple[int, dict]:
    token = secrets.token_urlsafe(32)
    device_id = new_id("dev").lower()

    @firestore.transactional
    def run(tx):
        ref, data = _pair_doc(tx, code)
        if not data or not secrets.compare_digest(data["pollHash"], _sha(poll_secret)) \
                or data["status"] in ("denied", "consumed"):
            raise ApiError(401, "invalid_code")  # unknown, expired, used, declined or not this device: all alike
        last = data.get("lastPollAt")
        if last and (_now() - last).total_seconds() < POLL_MIN_SECONDS:
            raise ApiError(429, "slow_down", retryAfter=POLL_MIN_SECONDS)
        if data["status"] == "waiting":
            tx.update(ref, {"lastPollAt": _now()})  # only the real device (right secret) gets here
            return 202, {"status": "waiting"}
        tx.update(ref, {"status": "consumed", "deviceId": device_id, "consumedAt": firestore.SERVER_TIMESTAMP})
        _create_device(tx, data["uid"], device_id, token, data["name"])
        return 200, {"deviceId": device_id, "token": token}

    return db.run_transaction(run)


# ------------------------------------------------------------------ discovery and devices watched by a helper

DISCOVERY_TTL = timedelta(hours=24)
WATCHED_PER_HELPER = 10
# The helper's vocabulary (nightlight_helper.py PORTS / MDNS / VENDORS / _guess); anything else is refused.
FOUND_PORTS = (22, 80, 443, 445, 631, 8123, 25565, 32400)
FOUND_SERVICES = ("remote login (SSH)", "web page", "secure web page", "file sharing", "printer", "Home Assistant",
                  "Minecraft", "Plex", "Chromecast / Google speaker", "AirPlay speaker or TV", "HomeKit accessory",
                  "AirPlay speaker")
FOUND_VENDORS = ("Raspberry Pi", "Synology", "QNAP", "VMware virtual machine", "Philips Hue", "Sonos",
                 "Espressif (smart-home gadget)", "Google", "Amazon", "Ubiquiti", "Nintendo",
                 "private address (likely a phone or laptop)")
PRIVATE_MAC = "private address (likely a phone or laptop)"  # the helper's word for a randomized hardware address
FOUND_GUESSES = ("Home Assistant", "Plex media server", "Minecraft server", "Printer", "File share (NAS or computer)",
                 "Speaker or TV", "Raspberry Pi", "VMware virtual machine", "Computer (remote login)",
                 "Device with a web page", "Unknown device", *FOUND_VENDORS)


def discoveries_ref(uid: str):
    return db.user(uid).collection("discoveries")


def save_discoveries(token: str, items: list[dict]) -> dict:
    """What a helper found nearby and its owner chose to send (no addresses). Replaces the previous list."""
    @firestore.transactional
    def run(tx):
        uid, device_id = token_owner(tx, token)
        dsnap = db.device(uid, device_id).get(transaction=tx)
        watched = db.devices(uid).where(filter=FieldFilter("watchedBy", "==", device_id)).get(transaction=tx)
        name = (dsnap.to_dict() or {}).get("name", "A device")
        added = {w.to_dict().get("cid") for w in watched}  # already on the map: stays "added" across rediscovery
        tx.set(discoveries_ref(uid).document(device_id), {
            "items": [{**it, "added": it["cid"] in added} for it in items], "by": device_id, "byName": name,
            "at": firestore.SERVER_TIMESTAMP, "expiresAt": _now() + DISCOVERY_TTL})
        event(tx, uid, device_id, "found", "info", f"{name} found {len(items)} thing(s) nearby you can add.")
        return {"ok": True, "items": len(items)}

    return db.run_transaction(run)


WATCH_PORTS = (8123, 32400, 25565, 445, 631, 443, 80, 22)  # a watched thing is checked on the first one it answers


ROLES = ("router", "printer", "fileshare", "smarthome", "server", "speaker", "computer", "other")
ROLE_FROM_GUESS = {"Printer": "printer", "File share (NAS or computer)": "fileshare", "Home Assistant": "smarthome",
                   "Plex media server": "server", "Minecraft server": "server", "Speaker or TV": "speaker",
                   "Raspberry Pi": "computer", "Computer (remote login)": "computer",
                   "VMware virtual machine": "computer", "Synology": "fileshare", "QNAP": "fileshare",
                   "Philips Hue": "smarthome", "Espressif (smart-home gadget)": "smarthome", "Sonos": "speaker"}


ROLE_WORDS = {"router": "Your router: your devices reach the internet through it", "printer": "A printer",
              "fileshare": "A file share (a NAS or a computer sharing folders)", "smarthome": "A smart-home hub or gadget",
              "server": "A media or game server", "speaker": "A TV or speaker", "computer": "A computer",
              "other": "Something on your network"}


def role_purpose(role: str, watcher: str | None) -> str:
    """The plain description the app and the agent show for a watched thing, always from its current role."""
    return f"{ROLE_WORDS.get(role, ROLE_WORDS['other'])}. Watched by {watcher or 'one of your devices'}."


def role_for(item: dict, routers: set) -> str:
    """What a found thing most likely is, in the app's few words (the person can correct it)."""
    if item.get("tag") and item["tag"] in routers:
        return "router"
    return ROLE_FROM_GUESS.get(item.get("guess")) or ROLE_FROM_GUESS.get(item.get("vendor")) or "other"


def found_view(uid: str) -> list[dict]:
    """Everything found nearby that isn't on the map yet, once each: two devices that saw the same thing share its
    fingerprint (same address, same account key), so it becomes one row listing who saw it; a thing whose fingerprint
    is one of your own devices is left out. Untagged items (older helpers) stay one row per finder."""
    now = _now()
    mine = {(d.get("net") or {}).get("self") for d in (s.to_dict() for s in db.devices(uid).get())
            if not d.get("archived")} - {None}
    rows: dict[str, dict] = {}
    for snap in discoveries_ref(uid).get():
        d = snap.to_dict()
        if d.get("expiresAt") and d["expiresAt"] < now:
            continue
        for it in d.get("items") or []:
            if it.get("added") or it.get("tag") in mine:
                continue
            key = it.get("tag") or f"{snap.id}:{it.get('cid')}"
            row = rows.setdefault(key, {"guess": it.get("guess"), "vendor": it.get("vendor"), "tag": it.get("tag"),
                                        "services": [], "ports": [], "seenBy": []})
            row["vendor"] = row["vendor"] or it.get("vendor")
            row["services"] = sorted(set(row["services"]) | set(it.get("services") or []))[:8]
            row["ports"] = sorted(set(row["ports"]) | set(it.get("ports") or []))[:8]
            if row["guess"] in (None, "Unknown device", "Device with a web page") and it.get("guess"):
                row["guess"] = it["guess"]  # the more specific guess wins
            row["seenBy"].append({"deviceId": snap.id, "name": d.get("byName"), "cid": it.get("cid"),
                                  "canWatch": any(p in WATCH_PORTS for p in it.get("ports") or [])})
    # A finder can watch it when it saw a port to check, is still a working device of yours, and has room left.
    helpers = {snap.id: snap.to_dict() for snap in db.devices(uid).get()}
    routers = {(h.get("net") or {}).get("gateway") for h in helpers.values() if not h.get("archived")} - {None}
    room = {}
    for h in helpers.values():
        if h.get("watchedBy") and not h.get("revoked"):
            room[h["watchedBy"]] = room.get(h["watchedBy"], 0) + 1
    for row in rows.values():
        # Plain words: what the server knows beats a guess (the thing your devices reach the internet through is your
        # router), and a randomized hardware address says "phone or laptop", not a maker.
        if row["vendor"] == PRIVATE_MAC:
            row["vendor"] = None
            row["privateAddress"] = True
            if row["guess"] in (PRIVATE_MAC, "Unknown device", None):
                row["guess"] = "Phone or laptop"
        if row.get("tag") and row["tag"] in routers:
            row["guess"], row["router"] = "Your router (internet connection)", True
        row["seenBy"] = [f for f in row["seenBy"] if f["deviceId"] in helpers]  # a forgotten device saw nothing
        for f in row["seenBy"]:
            h = helpers[f["deviceId"]]
            f["canWatch"] = f["canWatch"] and not h.get("archived") and not h.get("revoked") \
                and room.get(f["deviceId"], 0) < WATCHED_PER_HELPER
        row["seenBy"].sort(key=lambda f: not f["canWatch"])  # Add uses the first finder
    out = [row for row in rows.values() if row["seenBy"]]
    return sorted(out, key=lambda r: (not r.get("router"), not (r["seenBy"] and r["seenBy"][0]["canWatch"])))


DISCOVER_FROM = "0.9.21"  # helpers that can look nearby when the app asks


def request_discover(uid: str, device_id: str) -> dict:
    """Ask one device to look nearby. A scan still under way is that scan (asking twice doesn't queue a second); a new
    scan gets its own identity, so a late result from an earlier one can never finish it.

    Scans are numbered per device; scan n is the job with identity `app_discover_<n>` (`once`: a finished one is never
    reopened). One transaction reads the counter and that job: missing or under way, ask for scan n again (whoever
    asked first may still be making it; asking again finds it); finished, move to n + 1. Nothing else is recorded, so
    an interruption anywhere leaves nothing half done."""
    from . import actions
    slot = db.user(uid).collection("scans").document(device_id)

    @firestore.transactional
    def which(tx):
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        snap = slot.get(transaction=tx)
        n = (snap.to_dict() or {}).get("n", 0) if snap.exists else 0
        a = db.action(uid, _scan_action_id(user, device_id, n)).get(transaction=tx) if n else None
        if n and (not a.exists or (a.to_dict() or {}).get("status") in ("pending", "approved", "running")):
            return n
        tx.set(slot, {"n": n + 1})
        return n + 1

    for _ in range(3):  # a scan finishing between choosing and asking: choose again
        n = db.run_transaction(which)
        a = actions.request(uid, "discover", device_id, {}, session_id=None, turn_id=f"app_discover_{n}",
                            origin="app", once=True)
        if a.get("status") in ("pending", "approved", "running"):
            return a
    return a


def _scan_action_id(user: dict, device_id: str, n: int) -> str:
    """The job identity of scan n on this device (as actions.request derives it)."""
    return make_action_id(proposal_key(user.get("demoGeneration"), f"app_discover_{n}", device_id,
                                       service_for({}), "discover", {}))


def discover_everywhere(uid: str, every_device: bool = False) -> dict:
    """Look nearby on every network you have a device on: one device per router (the freshest app-managed one with a
    new enough helper), so a home is scanned once, not once per device. Each device mostly sees what it has talked to
    lately, so `every_device` asks all of them (the list merges what they saw). Says which devices couldn't and why."""
    from . import release
    asked, skipped, best = [], [], {}
    for snap in db.devices(uid).get():
        d = dict(snap.to_dict(), id=snap.id)
        if d.get("realm") != "real" or d.get("kind") == "watched" or d.get("archived") or d.get("revoked"):
            continue
        why = ("it isn't reporting right now" if view(d).get("stale")
               else "it is set to strict (it looks only when someone runs it there)" if d.get("manage") != "app"
               else "its helper needs updating first" if release.newer(DISCOVER_FROM, d.get("helperVersion"))
               else None)
        if why:
            skipped.append({"deviceId": d["id"], "name": d.get("name"), "why": why})
            continue
        network = d["id"] if every_device else (d.get("net") or {}).get("gateway") or d["id"]  # unknown: its own
        seen = d.get("lastSeen")
        if network not in best or (seen and (best[network].get("lastSeen") is None or seen > best[network]["lastSeen"])):
            best[network] = d
    for d in best.values():
        try:
            request_discover(uid, d["id"])
            asked.append({"deviceId": d["id"], "name": d.get("name")})
        except (ValueError, ApiError) as e:
            skipped.append({"deviceId": d["id"], "name": d.get("name"), "why": str(e)})
    return {"asked": asked, "skipped": skipped}


def add_found(uid: str, helper_id: str, cid: str, name: str) -> dict:
    """Put one found thing on the map, watched by the helper that found it (it checks the thing still answers)."""
    dref = discoveries_ref(uid).document(helper_id)
    device_id = new_id("dev").lower()

    @firestore.transactional
    def run(tx):
        snap = dref.get(transaction=tx)
        hsnap = db.device(uid, helper_id).get(transaction=tx)
        watched = [w.to_dict() for w in
                   db.devices(uid).where(filter=FieldFilter("watchedBy", "==", helper_id)).get(transaction=tx)]
        helpers_now = list(db.devices(uid).where(filter=FieldFilter("realm", "==", "real")).get(transaction=tx))
        d = snap.to_dict() if snap.exists else None
        if not d or d["expiresAt"] < _now() or not hsnap.exists:
            raise not_found()
        item = next((it for it in d["items"] if it.get("cid") == cid), None)
        if not item:
            raise not_found()
        if item.get("added") or any(w.get("cid") == cid and not w.get("revoked") for w in watched):
            raise ApiError(409, "already_added")
        if sum(1 for w in watched if not w.get("revoked")) >= WATCHED_PER_HELPER:  # removed ones free a place
            raise ApiError(429, "watch_capacity")
        port = next((p for p in WATCH_PORTS if p in (item.get("ports") or [])), None)
        if port is None:
            raise ApiError(422, "no_check_port")  # nothing we could check answers on it
        helper_name = hsnap.to_dict().get("name", "your device")
        tx.update(dref, {"items": [{**it, "added": it.get("cid") == cid or it.get("added")} for it in d["items"]]})
        routers = {(h.to_dict().get("net") or {}).get("gateway") for h in helpers_now
                   if not h.to_dict().get("archived")} - {None}
        role = role_for(item, routers)
        tx.set(db.device(uid, device_id), {
            "name": name, "kind": "watched", "role": role,
            "purpose": role_purpose(role, helper_name),
            "guess": item.get("guess"), "services": item.get("services") or [], "ports": item.get("ports") or [],
            "realm": "real", "simulated": False, "watchedBy": helper_id, "cid": cid, "checkPort": port,
            "vendor": item.get("vendor"), "health": "unknown", "status": "offline", "vitals": {}, "findings": [],
            "version": 1, "x": 420, "y": 220, "createdAt": firestore.SERVER_TIMESTAMP, "lastSeen": None,
            "registered": True, **({"net": {"self": item["tag"]}} if item.get("tag") else {})})
        tx.set(db.client().collection("realDevices").document(f"{uid}__{device_id}"),
               {"uid": uid, "deviceId": device_id})
        event(tx, uid, device_id, "joined", "info", f"{name} joined your map, watched by {helper_name}.", who="you")
        links.mark_due(tx, uid)  # a found thing with a fingerprint may be someone's router: lines may change
        return {"ok": True, "deviceId": device_id}, bool(item.get("tag"))

    result, fingerprinted = db.run_transaction(run)
    if fingerprinted:
        links.infer_quietly(uid)  # e.g. the router: the devices behind it get their lines
    return result


def leave(token: str, cleanup: str | None = None) -> dict:
    """The helper revokes its own token (it uninstalled itself, from the app or by hand): the device is archived and
    a removal the owner asked for is closed, in one transaction."""
    from . import archive
    tref = tokens_ref().document(_sha(token))

    @firestore.transactional
    def run(tx):
        snap = tref.get(transaction=tx)
        t = snap.to_dict() if snap.exists else None
        if not t or t.get("revoked"):
            raise ApiError(401, "invalid_token")
        dref = db.device(t["uid"], t["deviceId"])
        dsnap = dref.get(transaction=tx)
        if dsnap.exists and not (dsnap.to_dict() or {}).get("archived"):
            archive.left(tx, t["uid"], t["deviceId"], dsnap, cleanup)  # reads first, then writes
            tx.update(dref, {"uninstalled": True})
        tx.update(tref, {"revoked": True, "revokedAt": firestore.SERVER_TIMESTAMP})

    db.run_transaction(run)
    return {"ok": True}


def remove_watched(uid: str, device_id: str) -> dict:
    """Take a device watched by a helper off the map: its helper stops checking it, and its place is freed."""
    ref = db.device(uid, device_id)

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or d.get("kind") != "watched" or d.get("revoked"):
            raise not_found()
        dref = discoveries_ref(uid).document(d.get("watchedBy", "_"))
        disc = dref.get(transaction=tx)
        tx.update(ref, {"revoked": True, "status": "offline", "health": "unknown", "watchedBy": None})
        tx.delete(db.client().collection("realDevices").document(f"{uid}__{device_id}"))
        if disc.exists:
            items = disc.to_dict().get("items") or []
            tx.update(dref, {"items": [{**it, "added": False if it.get("cid") == d.get("cid") else it.get("added")}
                                       for it in items]})
        event(tx, uid, device_id, "removed", "info", f"You took {d.get('name', 'a device')} off the map.", who="you")
        return {"ok": True, "deviceId": device_id}

    return db.run_transaction(run)


def revoke(uid: str, device_id: str) -> dict:
    """Revoke the device's token(s) and mark it offline, together, in one transaction."""
    query = tokens_ref().where(filter=FieldFilter("deviceId", "==", device_id))

    @firestore.transactional
    def run(tx):
        tokens = [t for t in query.get(transaction=tx) if t.to_dict().get("uid") == uid]
        dsnap = db.device(uid, device_id).get(transaction=tx)
        if not tokens or not dsnap.exists:
            raise not_found()
        for t in tokens:
            tx.update(t.reference, {"revoked": True, "revokedAt": firestore.SERVER_TIMESTAMP})
        tx.update(db.device(uid, device_id), {"status": "offline", "health": "unknown", "revoked": True})
        tx.delete(db.client().collection("realDevices").document(f"{uid}__{device_id}"))
        event(tx, uid, device_id, "revoked", "info",
              f"You removed {dsnap.to_dict().get('name', 'a device')}'s access.", who="you")

    db.run_transaction(run)
    return {"ok": True, "deviceId": device_id}


# ------------------------------------------------------------------ heartbeats

def _finding_id(prefix: str, name: str) -> str:
    """Route-safe and unique per original name (a safe form plus a short hash of the exact name)."""
    return f"{prefix}{_doc_id(name)[:80]}_{_sha(name)[:8]}"


def _doc_id(name: str) -> str:
    """A safe Firestore document id for a container or unit name."""
    return (re.sub(r"[^A-Za-z0-9_.@-]", "_", name) or "unnamed")[:100]


def _friendly(unit: str) -> str:
    base = unit.removesuffix(".service")
    return FRIENDLY.get(base, base)


TREND_EVERY = timedelta(minutes=20)  # one disk sample per 20 minutes, the last 18 kept (6 hours)


def disk_forecast(trend: list, pct: float | None, now: datetime) -> tuple[list, float | None]:
    """Keep a short disk-use trend on the device and estimate the hours until it is full (None if not filling)."""
    trend = [p for p in (trend or []) if isinstance(p, dict) and p.get("at") and now - p["at"] < timedelta(hours=6)]
    if pct is None:
        return trend, None
    if not trend or now - trend[-1]["at"] >= TREND_EVERY:
        trend = (trend + [{"at": now, "pct": pct}])[-18:]
    first = trend[0]
    hours = (now - first["at"]).total_seconds() / 3600
    if hours < 1 or pct <= first["pct"]:
        return trend, None
    rate = (pct - first["pct"]) / hours  # percentage points per hour
    return trend, max(0.0, (100 - pct) / rate) if rate >= 0.2 else None


def _hours(h: float) -> str:
    return "less than an hour" if h < 1 else f"about {round(h)} hour{'s' if round(h) != 1 else ''}" if h < 48 \
        else f"about {round(h / 24)} days"


def escalate_disk(findings: list[dict], pct: float | None, to_full: float | None) -> None:
    """A full disk can freeze or crash a computer: say so plainly, and say when it will be full at this rate."""
    f = next((x for x in findings if x.get("id") == "f_disk"), None)
    if f is None or pct is None:
        return
    if pct >= 98:
        f["severity"] = "crit"
        f["message"] = (f"The disk is {pct:.0f}% full: the computer may freeze or crash any moment. "
                        "Free some space now.")
    if to_full is not None and pct < 99.5:
        f["message"] += f" At this rate it will be full in {_hours(to_full)}."


def checks(facts: dict) -> list[dict]:
    """Deterministic findings from real facts. The model explains these; it doesn't decide them."""
    out = []
    disk, mem = facts.get("diskPct"), facts.get("memPct")
    if disk is not None and disk >= 90:
        out.append({"id": "f_disk", "check": "disk_over_90", "severity": "crit",
                    "message": f"The disk is {disk:.0f}% full.", "evidence": f"/ at {disk:.0f}%"})
    elif disk is not None and disk >= 80:
        out.append({"id": "f_disk", "check": "disk_over_80", "severity": "warn",
                    "message": f"The disk is {disk:.0f}% full.", "evidence": f"/ at {disk:.0f}%"})
    if mem is not None and mem >= 90:
        out.append({"id": "f_mem", "check": "memory_high", "severity": "crit",
                    "message": f"Memory is {mem:.0f}% used.", "evidence": f"memory {mem:.0f}%"})
    for unit in facts.get("failedUnits") or []:
        out.append({"id": _finding_id("f_unit_", unit), "check": "service_down", "severity": "warn",
                    "message": f"{_friendly(unit)} has stopped working.", "evidence": f"system service {unit}: failed",
                    "svcId": _doc_id(unit)})
    for c in facts.get("containers") or []:
        if c.get("state") not in ("running", None):
            out.append({"id": _finding_id("f_ctr_", c["name"]), "check": "container_down", "severity": "warn",
                        "message": f"{c['name']} isn't running.", "evidence": f"container state: {c.get('state')}",
                        "svcId": _doc_id(c["name"])})
    agents = facts.get("failedAgents") or []
    if agents:
        out.append({"id": "f_agents", "check": "background_items_failing", "severity": "info",
                    "message": f"{len(agents)} background item(s) on this Mac keep failing.",
                    "evidence": ", ".join(a[:60] for a in agents[:3])})
    safety = facts.get("safety") or {}
    if safety.get("passwordlessSudo"):
        out.append({"id": "f_sudo_nopasswd", "check": "passwordless_admin", "severity": "warn",
                    "message": "This account can run administrator commands without typing a password.",
                    "evidence": "sudo ran a test command with no password"})
    if safety.get("sshPasswordLogin"):
        out.append({"id": "f_ssh_password", "check": "ssh_password_login", "severity": "info",
                    "message": "The remote-login (SSH) settings allow password logins; keys are safer against guessing.",
                    "evidence": "SSH PasswordAuthentication yes"})
    pending = facts.get("updatesPending")
    if pending:
        out.append({"id": "f_updates", "check": "updates_pending", "severity": "info",
                    "message": f"{pending} system updates are waiting (the operating system and installed programs, "
                               "not Nightlight).", "evidence": f"{pending} upgradable packages"})
    uptime = facts.get("uptimeSec")
    if uptime and uptime > 180 * 86400:
        weeks = int(uptime // (7 * 86400))
        out.append({"id": "f_uptime", "check": "restart_overdue", "severity": "info",
                    "message": f"It hasn't restarted in {weeks} weeks; some updates only take effect after a restart.",
                    "evidence": f"uptime {weeks} weeks"})
    return out


def service_for(params: dict) -> str | None:
    name = params.get("container") or params.get("unit")
    return _doc_id(name) if isinstance(name, str) else None


def _unit_card(device: dict, services: dict, params: dict) -> dict:
    if set(params) != {"unit"}:
        raise ValueError("not_applicable")
    unit = params["unit"]
    if not isinstance(unit, str) or not TARGET_NAME.fullmatch(unit):
        raise ValueError("bad_target")
    if unit not in (device.get("allowedJobs") or {}).get("restart_service", []):
        raise ValueError("not_allowed_on_device")
    svc = services.get(_doc_id(unit))
    if not svc or svc.get("kind") != "system" or svc.get("unit") != unit or not svc.get("failed"):
        raise ValueError("not_failed")  # only the exact service the device reports as failed
    friendly = _friendly(unit)
    return {"svcId": _doc_id(unit), "plan": f"Restart {friendly} ({unit}) on the {device['name']}.",
            "dryRun": f"The helper on the device runs \"sudo systemctl restart {unit}\" and checks it is still running "
                      f"a few seconds later. Nothing else is touched.",
            "rollback": "Nothing to undo: if it fails again, it simply stays stopped and you'll see why.",
            "blastRadius": [device["id"]], "riskClass": "service"}


def _fix_card(device: dict, params: dict) -> dict:
    if set(params) != {"recipe"} or params["recipe"] not in FIX:
        raise ValueError("bad_target")
    if params["recipe"] not in (device.get("allowedJobs") or {}).get("fix", []):
        raise ValueError("not_allowed_on_device")
    title, what, undo = FIX[params["recipe"]]
    return {"svcId": None, "plan": f"{title} on the {device['name']}.",
            "dryRun": f"{what}. The helper reports how much space it freed. Nothing else is touched.",
            "rollback": undo, "blastRadius": [device["id"]], "riskClass": "service"}


def _remove_card(device: dict, params: dict) -> dict:
    from .archive import ARCHIVE_DAYS, can_self_uninstall
    if params or device.get("archived") or device.get("kind") == "watched":
        raise ValueError("not_applicable")
    name = device.get("name", "this device")
    itself = not view(device).get("stale") and not device.get("revoked") and can_self_uninstall(device)
    return {"svcId": None, "plan": f"Remove {name} from Nightlight.",
            "dryRun": ("The helper on it uninstalls itself (stops its background service, deletes its files and its "
                       "key) and the device leaves your map." if itself else
                       "It isn't reporting (or its helper is too old to uninstall itself), so its access is cut now "
                       "and it leaves your map; to delete the helper's files, run the uninstall line on it."),
            "rollback": f"Its history, notes and activity are kept for {ARCHIVE_DAYS} days, then deleted. To bring it "
                        "back, add it again (it becomes a new device).",
            "blastRadius": [device["id"]], "riskClass": "service"}


def card(device: dict, services: dict, action_type: str, params: dict) -> dict:
    """The approval card for a real-device job. ValueError when it doesn't apply, including when the device's owner
    hasn't allowed this job on this target on the device itself."""
    if action_type == "remove_device":
        return _remove_card(device, params)
    if action_type == "fix":
        return _fix_card(device, params)
    if action_type == "restart_service":
        return _unit_card(device, services, params)
    if action_type != "restart_container" or set(params) != {"container"}:
        raise ValueError("not_applicable")
    name = params["container"]
    if not isinstance(name, str) or not CONTAINER_NAME.fullmatch(name):
        raise ValueError("bad_target")
    if name not in (device.get("allowedJobs") or {}).get(action_type, []):
        raise ValueError("not_allowed_on_device")
    svc = services.get(_doc_id(name))
    if not svc or svc.get("kind") != "container":
        raise ValueError("no_such_container")
    if svc.get("status") == "ok":
        raise ValueError("already_running")
    return {"svcId": _doc_id(name), "plan": f"Start the stopped {name} container again on the {device['name']}.",
            "dryRun": f"The helper on the device runs \"docker start {name}\" and checks it is still running a few "
                      f"seconds later. Nothing else is touched.",
            "rollback": f"Stop {name} again (from the app or with \"docker stop {name}\").",
            "blastRadius": [device["id"]], "riskClass": "service"}


def _span(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m} minutes" if m < 120 else f"{m // 60} hours" if m < 2880 else f"{m // 1440} days"


def back_words(last_seen, uptime_sec) -> dict:
    """How a silent device came back: if it has been up for less time than it was silent, it restarted."""
    if not last_seen:
        return {"restarted": None, "words": "it was silent."}
    silent = max(0.0, (_now() - last_seen).total_seconds())
    if isinstance(uptime_sec, (int, float)) and uptime_sec < silent + 120:
        return {"restarted": True, "words": f"it restarted about {_span(uptime_sec)} ago, after {_span(silent)} "
                                            "without a report (a restart or power cut)."}
    if isinstance(uptime_sec, (int, float)):
        return {"restarted": False, "words": f"it was unreachable for {_span(silent)} but didn't restart (probably "
                                             "asleep, logged out or off the network)."}
    return {"restarted": None, "words": f"it was silent for {_span(silent)}."}


def heartbeat(token: str, facts: dict, take_jobs: bool = True) -> dict:
    tref = tokens_ref().document(_sha(token))
    facts, _ = scrub_value(facts)
    findings = checks(facts)
    services = {}
    for c in facts.get("containers") or []:
        image = c.get("image") or ""
        services[_doc_id(c["name"])] = {"name": c["name"], "category": "containers", "kind": "container",
                               "status": "ok" if c.get("state") == "running" else "warn",
                               "version": image.rsplit(":", 1)[1] if ":" in image else None,
                               "detail": c.get("status"), "findings": []}
    for unit in facts.get("failedUnits") or []:
        services[_doc_id(unit)] = {"name": _friendly(unit), "unit": unit, "category": "system", "kind": "system",
                                   "status": "warn", "failed": True,
                          "findings": [f for f in findings if f.get("svcId") == _doc_id(unit)]}

    @firestore.transactional
    def run(tx):
        snap = tref.get(transaction=tx)
        t = snap.to_dict() if snap.exists else None
        if not t or t.get("revoked"):
            raise ApiError(401, "invalid_token")
        last = t.get("lastSeen")
        if last and (_now() - last).total_seconds() < HEARTBEAT_MIN_SECONDS:
            raise ApiError(429, "too_frequent", retryAfter=HEARTBEAT_MIN_SECONDS)
        uid, device_id = t["uid"], t["deviceId"]
        dref = db.device(uid, device_id)
        dsnap = dref.get(transaction=tx)
        old = [s.reference for s in db.services(uid, device_id).get(transaction=tx)]
        approved = db.actions(uid).where(filter=FieldFilter("deviceId", "==", device_id)).where(
            filter=FieldFilter("status", "==", "approved")).get(transaction=tx)
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        watched = [w for w in db.devices(uid).where(filter=FieldFilter("watchedBy", "==", device_id)).get(transaction=tx)
                   if not (w.to_dict() or {}).get("revoked")]
        if not dsnap.exists:
            raise ApiError(401, "invalid_token")
        device = dsnap.to_dict()
        net = facts.get("net")  # fingerprints only; an older helper sends none and keeps what was there
        net_changed = net is not None and net != device.get("net")
        net_key, lines_due = links.net_state(tx, uid, net_changed)  # the last read (it may write)
        trend, to_full = disk_forecast(device.get("diskTrend"), facts.get("diskPct"), _now())
        escalate_disk(findings, facts.get("diskPct"), to_full)
        marked, states = apply_issue_states(findings, device.get("issueStates") or {})
        status = health_of(marked)
        previous = real_status(device)
        if previous != status:
            top = next((f for f in marked if f.get("state") == "new" and f["severity"] != "info"), None)
            words = {"ok": "is back to normal", "warn": "needs a look", "crit": "needs attention now"}[status]
            event(tx, uid, device_id, "status_" + status, status if status != "ok" else "info",
                  f"{device.get('name', 'A device')} {words}" + (f": {top['message']}" if top and status != "ok" else "."),
                  who="device")
        from .watch import history_point  # (watch imports this module)
        vitals = {"cpu": facts.get("cpuPct"), "mem": facts.get("memPct"), "diskPct": facts.get("diskPct"),
                  "uptime": facts.get("uptimeSec")}
        extra = history_point(tx, uid, device_id, device, vitals, status,
                              sum(1 for f in marked if f.get("state") == "new"))
        if not device.get("registered"):  # devices from before the sweep registry join it on their next report
            tx.set(db.client().collection("realDevices").document(f"{uid}__{device_id}"),
                   {"uid": uid, "deviceId": device_id})
            extra["registered"] = True
        if device.get("watchState") == "silent":
            extra["watchState"] = None
            gap = back_words(device.get("lastSeen"), facts.get("uptimeSec"))
            extra["lastGap"] = {"from": device.get("lastSeen"), "to": _now(), "restarted": gap["restarted"],
                                "diskBefore": (device.get("vitals") or {}).get("diskPct")}
            restarted[0] = gap["restarted"] is True
            event(tx, uid, device_id, "back", "info", f"{device.get('name', 'A device')} is reporting again: "
                  + gap["words"])
        tx.update(tref, {"lastSeen": _now()})
        extra["diskTrend"] = trend
        if net_changed:
            extra["net"] = net
        tx.update(dref, {**extra,
            "os": facts.get("os"), "arch": facts.get("arch"), "status": status, "health": "verified",
            "vitals": {"cpu": facts.get("cpuPct"), "mem": facts.get("memPct"), "diskPct": facts.get("diskPct"),
                       "uptime": facts.get("uptimeSec")},
            "findings": marked, "issueStates": states, "lastSeen": firestore.SERVER_TIMESTAMP,
            "version": device.get("version", 1) + 1,
            "helperVersion": facts.get("helperVersion"), "allowedJobs": facts.get("allowedJobs") or {},
            "updatesPending": facts.get("updatesPending"), "containerCount": len(facts.get("containers") or []),
            "manage": facts.get("manage"),
            "containersRunning": sum(1 for c in facts.get("containers") or [] if c.get("state") == "running")})
        for ref in old:
            if ref.id not in services:
                tx.delete(ref)
        for svc_id, svc in services.items():
            tx.set(db.services(uid, device_id).document(svc_id), svc)
        results = {r["cid"]: r for r in facts.get("watchResults") or []}
        for w in watched:
            wd = w.to_dict()
            r = results.get(wd.get("cid"))
            if not r:
                continue
            up = r.get("up")
            what = (f"{wd.get('name')} isn't answering" if not up else None)
            if wd.get("watchState") == "silent":
                event(tx, uid, w.id, "back", "info", f"{wd.get('name')} is being checked again.")
            tx.update(w.reference, {"watchState": None, "status": "ok" if up else "crit", "health": "verified",
                                    "lastSeen": _now(),
                                    "vitals": {"latencyMs": r.get("ms")},
                                    "findings": [] if up else [{"id": "f_watch_down", "check": "watched_down",
                                                                "severity": "crit", "message": what + ".",
                                                                "evidence": f"checked by {device.get('name')}",
                                                                "state": "new"}]})
            if real_status(wd) != ("ok" if up else "crit"):
                event(tx, uid, w.id, "status_" + ("ok" if up else "crit"), "info" if up else "crit",
                      f"{wd.get('name')} " + ("is answering again." if up else "isn't answering."), who="device")
        watch_list = [{"cid": w.to_dict().get("cid"), "port": w.to_dict().get("checkPort")} for w in watched
                      if w.to_dict().get("checkPort")][:10]
        about = {"deviceName": device.get("name"), "ownerHint": user.get("ownerHint"),
                 "permissions": device.get("permissions") or DEFAULT_PERMISSIONS}
        jobs = _hand_over(tx, approved, user) if take_jobs else []
        return uid, device_id, jobs, _poll_every(user), watch_list, {**about, "netKey": net_key}, lines_due

    restarted = [False]
    uid, device_id, jobs, poll, watch_list, about, lines_due = db.run_transaction(run)
    if restarted[0]:
        post_mortem(token, device_id, facts)
    if lines_due:
        links.infer_quietly(uid)  # fingerprints changed (or an earlier attempt failed): lines may have too
    offer = release.latest()
    return {"ok": True, "deviceId": device_id, "findings": len(findings), "jobs": jobs, "pollEverySec": poll,
            "watch": watch_list, **about, **({"latestHelper": offer["version"]} if offer else {})}


def post_mortem(token: str, device_id: str, facts: dict) -> None:
    """A device came back after a restart: find out why, by itself (read-only checks the device allows, no card).
    The result lands in Activity and the device's notebook."""
    try:  # optional: nothing here may break the report that was just delivered
        offered = set((facts.get("allowedJobs") or {}).get("inspect", []))
        what = [w for w in ("restarts", "disk") if w in offered]
        if "restarts" not in what:
            return  # an older helper, or looking around isn't allowed there
        from . import actions
        t = tokens_ref().document(_sha(token)).get().to_dict() or {}
        uid = t.get("uid")
        user = db.user(uid).get().to_dict() or {} if uid else {}
        if not uid or user.get("demo", {}).get("state") != "ready":
            return
        actions.request_inspection(uid, session_id=None, turn_id=f"after_restart_{_now():%Y%m%d%H%M}",
                                   generation=user.get("demoGeneration"), device_id=device_id, what=what,
                                   extra={"playbook": "after_restart"})
    except Exception as e:  # never let the look-after break a report
        import logging
        logging.getLogger(__name__).info("post-mortem not started: %s", type(e).__name__)


SEVERITY = {"info": 1, "warn": 2, "crit": 3}


def apply_issue_states(findings: list[dict], states: dict) -> tuple[list[dict], dict]:
    """Mark each finding new / known / snoozed. A known or snoozed problem comes back as new if it got worse (or a
    snooze ran out). States for problems that went away are dropped."""
    now, out, keep = _now(), [], {}
    for f in findings:
        s = states.get(f["id"])
        state = "new"
        if s:
            worse = SEVERITY[f["severity"]] > SEVERITY.get(s.get("severity"), 3)
            expired = s.get("until") and s["until"] < now
            if not worse and not expired:
                state = s["state"]
                keep[f["id"]] = s
        out.append({**f, "state": state})
    return out, keep


def health_of(findings: list[dict]) -> str:
    """The health light counts only problems that still need a look."""
    worst = max((SEVERITY[f["severity"]] for f in findings if f.get("state", "new") == "new"), default=0)
    return "crit" if worst == 3 else "warn" if worst == 2 else "ok"


def real_status(device: dict) -> str | None:
    return None if device.get("lastSeen") is None else device.get("status")


def event(tx, uid: str, device_id: str | None, kind: str, severity: str, message: str, who: str = "device") -> None:
    """One line in Activity about a real device (kept through demo resets: it has no demo generation)."""
    tx.set(db.events(uid).document(new_id("ev")), {"deviceId": device_id, "kind": kind, "severity": severity,
                                                   "message": message[:300], "who": who, "realm": "real",
                                                   "at": firestore.SERVER_TIMESTAMP})


DEFAULT_PERMISSIONS = {"diagnose": True, "cleanup": False, "updates": True, "autoUpdate": False, "logs": [],
                       "restart_container": [], "restart_service": []}


def set_permissions(uid: str, device_id: str, perms: dict) -> dict:
    """Only for a device whose owner chose "let the app manage it" on the device, and only for things that device
    reported. The helper applies them on its next report (and still checks each action itself)."""
    ref = db.device(uid, device_id)

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or d.get("realm") != "real" or d.get("kind") == "watched" or d.get("revoked"):
            raise not_found()
        if d.get("manage") != "app":
            raise ApiError(409, "strict_device" if d.get("manage") == "strict" else "update_helper")
        services = {s.id: s.to_dict() for s in db.services(uid, device_id).get(transaction=tx)}
        containers = {s.get("name") for s in services.values() if s.get("kind") == "container"}
        units = {s.get("unit") for s in services.values() if s.get("kind") == "system" and s.get("unit")}
        if not set(perms["restart_container"]) <= containers or not set(perms["restart_service"]) <= units \
                or not set(perms["logs"]) <= containers | units:
            raise ApiError(422, "unknown_target")  # only things this device reported
        before = d.get("permissions") or DEFAULT_PERMISSIONS
        clean = {"diagnose": bool(perms["diagnose"]), "cleanup": bool(perms.get("cleanup")),
                 "updates": perms.get("updates") is not False, "autoUpdate": bool(perms.get("autoUpdate")),
                 **{k: sorted(set(perms[k])) for k in
                                                         ("logs", "restart_container", "restart_service")}}
        tx.update(ref, {"permissions": clean, "permissionsAt": firestore.SERVER_TIMESTAMP})
        words = []
        if clean["diagnose"] != before.get("diagnose"):
            words.append(("may now check" if clean["diagnose"] else "no longer checks") + " why things stop")
        if clean["updates"] != (before.get("updates") is not False):
            words.append("updates from the app are now " + ("allowed" if clean["updates"] else "off"))
        if clean["autoUpdate"] != bool(before.get("autoUpdate")):
            words.append("signed updates now install " + ("automatically" if clean["autoUpdate"] else "only when you ask"))
        if clean["cleanup"] != bool(before.get("cleanup")):
            words.append(("may now" if clean["cleanup"] else "may no longer") + " clean up space after you approve")
        for key, what in (("logs", "read log lines of"), ("restart_container", "restart"),
                          ("restart_service", "restart the service")):
            added = sorted(set(clean[key]) - set(before.get(key, [])))
            removed = sorted(set(before.get(key, [])) - set(clean[key]))
            if added:
                words.append(f"may {what} {', '.join(added)}")
            if removed:
                words.append(f"may no longer {what} {', '.join(removed)}")
        if words:
            event(tx, uid, device_id, "permissions", "info",
                  f"You changed what Nightlight may do on {d.get('name', 'a device')}: {'; '.join(words)}.", who="you")
        return {"ok": True, "permissions": clean}

    return db.run_transaction(run)


def set_issue_state(uid: str, device_id: str, finding_id: str, state: str, days: int | None) -> dict:
    """The owner marks one problem: still needs a look (new), known (leaving it on purpose) or snoozed for N days."""
    ref = db.device(uid, device_id)

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or d.get("realm") != "real":
            raise not_found()
        f = next((x for x in d.get("findings") or [] if x.get("id") == finding_id), None)
        if not f:
            raise not_found()
        states = dict(d.get("issueStates") or {})
        if state == "new":
            states.pop(finding_id, None)
        else:
            states[finding_id] = {"state": state, "severity": f["severity"], "at": _now(),
                                  "until": _now() + timedelta(days=days) if state == "snoozed" and days else None}
        marked, states = apply_issue_states([{k: v for k, v in x.items() if k != "state"}
                                             for x in d.get("findings") or []], states)
        status = health_of(marked) if d.get("lastSeen") else d.get("status")
        tx.update(ref, {"issueStates": states, "findings": marked, "status": status})
        words = {"new": "needs a look again", "known": "is known (you're leaving it for now)",
                 "snoozed": f"is snoozed for {days} days"}[state]
        event(tx, uid, device_id, "issue_" + state, "info", f"{f['message']} {words}", who="you")
        return {"ok": True, "state": state, "status": status}

    return db.run_transaction(run)


def _hand_over(tx, approved, user: dict) -> list[dict]:
    """Approved jobs are handed over once (at most once: a job claimed here is never handed out again)."""
    ready = user.get("demo", {}).get("state") == "ready"
    jobs = []
    for a in approved:
        if not ready or a.get("demoGeneration") != user.get("demoGeneration"):
            continue  # a reset is withdrawing it (or has): never hand it out
        tx.update(a.reference, {"status": "running", "claimedAt": firestore.SERVER_TIMESTAMP})
        jobs.append({"id": a.id, "type": a.get("type"), "params": a.get("params")})
    return jobs


def _poll_every(user: dict) -> int:
    last = user.get("lastChatAt")
    return FAST_POLL_SECONDS if last and _now() - last < CHAT_ACTIVE else 0


def claim(token: str, rate_limited: bool = True) -> dict:
    """Hand over this device's approved work (at most once). Older helpers poll this between reports; newer ones
    wait on `wait_for_jobs`, which calls it when work appears."""
    tref = tokens_ref().document(_sha(token))

    @firestore.transactional
    def run(tx):
        snap = tref.get(transaction=tx)
        t = snap.to_dict() if snap.exists else None
        if not t or t.get("revoked"):
            raise ApiError(401, "invalid_token")
        last = t.get("lastClaimAt")
        if rate_limited and last and (_now() - last).total_seconds() < CLAIM_MIN_SECONDS:
            raise ApiError(429, "too_frequent", retryAfter=CLAIM_MIN_SECONDS)
        uid, device_id = t["uid"], t["deviceId"]
        approved = db.actions(uid).where(filter=FieldFilter("deviceId", "==", device_id)).where(
            filter=FieldFilter("status", "==", "approved")).get(transaction=tx)
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        tx.update(tref, {"lastClaimAt": _now()})
        return _hand_over(tx, approved, user), _poll_every(user)

    jobs, poll = db.run_transaction(run)
    return {"ok": True, "jobs": jobs, "pollEverySec": poll}


WAIT_SECONDS = 25


def wait_for_jobs(token: str, hold: float = WAIT_SECONDS) -> dict:
    """The work channel (docs/adr/0003-job-channel.md): answer as soon as this device has approved work, or after
    `hold` seconds with none. A Firestore listener on the device's approved jobs wakes it; the hand-over itself is
    the same at-most-once transaction as every other."""
    import threading
    hold = max(0.0, min(hold, WAIT_SECONDS))
    tref = tokens_ref().document(_sha(token))

    @firestore.transactional
    def lease(tx):  # one open wait per device, across instances; a crashed one expires by itself
        t = tref.get(transaction=tx).to_dict()
        if not t or t.get("revoked"):
            raise ApiError(401, "invalid_token")
        busy = t.get("waitUntil")
        if busy and busy > _now():
            raise ApiError(429, "already_waiting", retryAfter=max(1, int((busy - _now()).total_seconds())))
        tx.update(tref, {"waitUntil": _now() + timedelta(seconds=hold + 5), "waitOwner": owner})
        return t

    @firestore.transactional
    def release(tx):  # only our own lease: a late finisher never clears its successor's
        if (tref.get(transaction=tx).to_dict() or {}).get("waitOwner") == owner:
            tx.update(tref, {"waitUntil": None, "waitOwner": None})

    owner = new_id("wait")
    t = db.run_transaction(lease)
    try:
        return _wait(token, t, hold)
    finally:
        db.run_transaction(release)


def _wait(token: str, t: dict, hold: float) -> dict:
    import threading
    first = claim(token, rate_limited=False)
    if first["jobs"]:
        return first
    woke = threading.Event()
    query = db.actions(t["uid"]).where(filter=FieldFilter("deviceId", "==", t["deviceId"])).where(
        filter=FieldFilter("status", "==", "approved"))
    watch = query.on_snapshot(lambda docs, changes, read_time: woke.set() if docs else None)
    try:
        woke.wait(hold)
    finally:
        watch.unsubscribe()
    return claim(token, rate_limited=False) if woke.is_set() else {"ok": True, "jobs": [], "pollEverySec": 0}


def diagnose_target_ok(device: dict, services: dict, target: str) -> None:
    """ValueError unless the owner allowed looking into this target on the device and the device reported it."""
    if not isinstance(target, str) or not TARGET_NAME.fullmatch(target):
        raise ValueError("bad_target")
    if target not in (device.get("allowedJobs") or {}).get("diagnose", []):
        raise ValueError("not_allowed_on_device")
    if _doc_id(target) not in services and _doc_id(target + ".service") not in services:
        raise ValueError("no_such_target")


def inspect_ok(device: dict, what) -> list[str]:
    """The checks to run (deduplicated, in order); ValueError unless the device offers every one of them."""
    if not isinstance(what, list) or not what or not all(isinstance(w, str) for w in what):
        raise ValueError("bad_target")
    names = list(dict.fromkeys(what))
    if len(names) > MAX_INSPECT or any(n not in INSPECT for n in names):
        raise ValueError("bad_target")
    offered = (device.get("allowedJobs") or {}).get("inspect", [])
    if any(n not in offered for n in names):
        raise ValueError("not_allowed_on_device")
    return names


def token_owner(tx, token: str) -> tuple[str, str]:
    """(uid, deviceId) for a live device token, read inside the caller's transaction; 401 otherwise."""
    snap = tokens_ref().document(_sha(token)).get(transaction=tx)
    t = snap.to_dict() if snap.exists else None
    if not t or t.get("revoked"):
        raise ApiError(401, "invalid_token")
    return t["uid"], t["deviceId"]


STALE_AFTER = timedelta(minutes=5)


def view(doc: dict, now: datetime | None = None) -> dict:
    """How a device should be presented: a real device that hasn't reported for 5 minutes is offline/unknown,
    whatever its last report said."""
    if doc.get("realm") != "real":
        return doc
    last = doc.get("lastSeen")
    reason = "revoked" if doc.get("revoked") else "no_report_yet" if not last else \
        "overdue" if (now or _now()) - last > STALE_AFTER else None
    if reason:
        return {**doc, "status": "offline", "health": "unknown", "findings": [], "stale": True, "staleReason": reason}
    return {**doc, "stale": False}


def is_current(doc: dict, generation: int) -> bool:
    """Real devices are part of the home until removed (archived); simulated ones only in the current generation."""
    if doc.get("archived"):
        return False
    return doc.get("realm") == "real" or doc.get("demoGeneration") == generation


