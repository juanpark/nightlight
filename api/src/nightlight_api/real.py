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

from . import apps, db, links, release
from .errors import ApiError, Outcome, not_found
from .ids import action_id as make_action_id, new_id, proposal_key
from .redact import scrub, scrub_value

EXIT_MEANING = {0: "finished normally", 1: "stopped with an error", 2: "stopped with an error (exit code 2)",
                137: "was force-stopped (exit code 137: killed, or out of memory)",
                143: "was asked to stop (exit code 143)", 139: "crashed (exit code 139)",
                126: "couldn't start its program (exit code 126)", 127: "couldn't find its program (exit code 127)"}


def _stopped_words(status) -> str:
    """Why a stopped container stopped, in plain words first, from Docker's status ("Exited (137) 5 minutes ago"):
    the meaning is the fact to report, the number only backs it up."""
    m = re.match(r"Exited \((-?\d+)\)", status or "")
    if not m:
        return "isn't running"
    code = int(m.group(1))
    return "isn't running: it " + EXIT_MEANING.get(code, f"exited with code {code}")


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
FIX = {  # recipe -> (title, what happens in plain words, undo, the exact command the helper runs or None)
    "empty_trash": ("Empty the Trash", "Deletes everything in the Trash", "Can't be undone: files in the Trash are "
                    "deleted for good. Look in the Trash first if you're unsure.", None),
    "brew_cleanup": ("Clear old downloads of developer tools (Homebrew)", "Removes old versions and saved downloads "
                     "of Homebrew's tools", "Nothing to undo: Homebrew downloads again what it needs.",
                     "brew cleanup -s"),
    "npm_cache": ("Clear a programming tool's download cache (npm)", "Removes the packages npm saved for reuse",
                  "Nothing to undo: npm downloads packages again when needed.", "npm cache clean --force"),
    "xcode_build_data": ("Clear Xcode's temporary build files", "Empties Xcode's build folder (DerivedData)",
                         "Nothing to undo: Xcode rebuilds it on the next build (the first build is slower).", None),
    "docker_prune": ("Remove leftover app downloads", "Removes app downloads (Docker images) that have no name "
                     "and that no app uses: mostly old versions left over from updates, but also unnamed images "
                     "someone built on this device", "Can't be undone for what it removes, but apps in use and "
                     "named images are not touched; an unnamed image you built yourself would have to be built "
                     "again.", "docker image prune -f"),
    "apt_clean": ("Clear downloaded system updates", "Removes the saved installation downloads (package files), "
                  "including ones that were downloaded but never installed",
                  "Nothing to undo: installed software stays exactly as it is; anything still needed is downloaded "
                  "again.", "sudo apt-get clean"),
    "journal_vacuum": ("Shrink the system's event diary (log)", "Keeps only the newest 200 MB of the system's record "
                       "of events", "Can't be undone: older entries are deleted.",
                       "sudo journalctl --vacuum-size=200M"),
}
# The device's last measurement per clean-up (device field `spaceMeasured`, written when its disk checks come back and
# when a clean-up ran): one that measured at most NOTHING_GB within MEASURED_FOR gets no card, it would free nothing.
NOTHING_GB = 0.1
MEASURED_FOR = timedelta(hours=3)
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
    from . import live
    live.forbid_pool(uid)  # never on a live demo machine's account
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


def pair_start(name: str, os_name: str | None, ip: str, machine: str | None = None, via: str | None = None) -> dict:
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
                                                   "machine": machine, "via": via,
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


# ------------------------------------------------------------------ a reinstall continues the same device
# The helper reports a fingerprint of its machine: SHA-256 of the machine's own hardware id (macOS IOPlatformUUID,
# Linux /etc/machine-id), never the id itself. It can't be keyed with the account's netKey like the other
# fingerprints, because an unpaired helper has no account yet; so the server keys it per account (HMAC with that
# account's netKey) before keeping it on a device or comparing. Matches therefore never cross accounts, and nothing is
# continued without the owner choosing "Continue its history" when approving.

def keyed_machine(key: str | None, machine: str | None) -> str | None:
    """The account-keyed form of a helper's machine fingerprint (20 hex characters), or None."""
    if not key or not machine:
        return None
    import hmac
    return hmac.new(bytes.fromhex(key), b"machine:" + machine.encode(), hashlib.sha256).hexdigest()[:20]


def _machine_tag(tx, uid: str, machine: str | None) -> str | None:
    """Read only: an account without a key yet has no device with a fingerprint either."""
    if not machine:
        return None
    snap = links._net_ref(uid).get(transaction=tx)
    return keyed_machine((snap.to_dict() or {}).get("key") if snap.exists else None, machine)


def _may_continue(d: dict) -> bool:
    """A helper device not reporting (offline, uninstalled, revoked) or archived, and not being deleted (a purge that
    has claimed it always wins: see archive.purge)."""
    return d.get("realm") == "real" and d.get("kind") != "watched" and not d.get("purgeClaim") \
        and bool(d.get("archived") or view(d).get("stale"))


def _continuable(snaps) -> tuple[str, dict] | None:
    """Of this account's devices with the same machine fingerprint, the one a reinstall may continue: a helper device
    that is offline, uninstalled or removed (archived, not yet deleted); the most recently seen. A device still
    reporting is never offered (that would cut a working helper off)."""
    out = []
    for s in snaps:
        d = s.to_dict() or {}
        if _may_continue(d):
            out.append((s.id, d))
    if not out:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return max(out, key=lambda x: x[1].get("lastSeen") or x[1].get("archivedAt") or epoch)


def _same_machine(tx, uid: str, machine: str | None) -> tuple[str | None, tuple[str, dict] | None]:
    tag = _machine_tag(tx, uid, machine)
    if not tag:
        return None, None
    return tag, _continuable(db.devices(uid).where(filter=FieldFilter("machine", "==", tag)).get(transaction=tx))


def _iso(t) -> str | None:
    return t.isoformat().replace("+00:00", "Z") if isinstance(t, datetime) else None


def pair_preview(uid: str, code: str) -> dict:
    """What the owner sees before approving, with `continues` when this looks like one of their devices reinstalled
    ({deviceId, name, lastSeen, removed}), else None."""
    from . import live
    live.forbid_pool(uid)  # never on a live demo machine's account
    _count_check(uid)
    _, data = _pair_doc(None, code)
    if not data or data["status"] != "waiting":
        raise not_found()
    out = {"name": data["name"], "os": data.get("os"),
           "expiresAt": data["expiresAt"].isoformat().replace("+00:00", "Z"), "continues": None}
    if data.get("machine"):
        @firestore.transactional
        def run(tx):
            return _same_machine(tx, uid, data["machine"])[1]
        found = db.run_transaction(run)
        if found:
            device_id, d = found
            out["continues"] = {"deviceId": device_id, "name": d.get("name"), "lastSeen": _iso(d.get("lastSeen")),
                                "removed": bool(d.get("archived"))}
    return out


def pair_decide(uid: str, code: str, approve: bool, continue_device: bool = False) -> dict:
    """The owner's tap. With continue_device, the approved helper takes over the device the preview offered: found
    again here from the fingerprint the helper sent and this account's own devices, never an id from the browser."""
    from . import live
    live.forbid_pool(uid)  # never on a live demo machine's account
    _count_check(uid)

    @firestore.transactional
    def run(tx):
        ref, data = _pair_doc(tx, code)
        if not data:
            raise not_found()
        if data["status"] != "waiting":
            raise ApiError(409, "already_decided")
        target = None
        tag, found = _same_machine(tx, uid, data.get("machine")) if approve else (None, None)
        if approve and continue_device:
            if not found:
                raise ApiError(409, "nothing_to_continue")
            target = found[0]
        # from here on only the account-keyed fingerprint is kept with the request
        tx.update(ref, {"status": "approved" if approve else "denied", "uid": uid if approve else None,
                        "continues": target, "machineTag": tag, "machine": firestore.DELETE_FIELD,
                        "decidedAt": _now()})
        return target

    target = db.run_transaction(run)
    return {"ok": True, "continues": target}


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
        kept = _continue_reads(tx, data) if data.get("continues") else None
        if kept:
            tx.update(ref, {"status": "consumed", "deviceId": data["continues"],
                            "consumedAt": firestore.SERVER_TIMESTAMP})
            _rebind(tx, data, token, *kept)
            return 200, {"deviceId": data["continues"], "token": token, "continued": True}
        tx.update(ref, {"status": "consumed", "deviceId": device_id, "consumedAt": firestore.SERVER_TIMESTAMP})
        _create_device(tx, data["uid"], device_id, token, data["name"])
        return 200, {"deviceId": device_id, "token": token}

    return db.run_transaction(run)


def _continue_reads(tx, data: dict):
    """Everything the continuation needs, read: (device snapshot, its tokens), or None when the device can't be
    continued any more: deleted or being deleted (a purge claimed it), its fingerprint changed, its own helper is
    reporting again (its working token is never revoked), or another reinstall took it over after this approval.
    Then the helper becomes a new device instead: nothing is ever merged without the owner's choice."""
    uid, device_id = data["uid"], data["continues"]
    dsnap = db.device(uid, device_id).get(transaction=tx)
    d = dsnap.to_dict() if dsnap.exists else None
    tag = data.get("machineTag")
    tokens = [t for t in tokens_ref().where(filter=FieldFilter("deviceId", "==", device_id)).get(transaction=tx)
              if (t.to_dict() or {}).get("uid") == uid]
    if not d or not tag or d.get("machine") != tag or not _may_continue(d):
        return None
    since, decided = d.get("helperSince"), data.get("decidedAt")
    if isinstance(since, datetime) and isinstance(decided, datetime) and since > decided:
        return None
    return dsnap, tokens


def _rebind(tx, data: dict, token: str, dsnap, old_tokens) -> None:
    """The reinstalled helper takes over its device: the old tokens die; the document, with its history, notes, saved
    fixes, jobs, events, place on the map and name, stays; a removed device comes back. Writes only."""
    from . import archive
    uid, device_id = data["uid"], data["continues"]
    d = dsnap.to_dict() or {}
    for t in old_tokens:
        if not (t.to_dict() or {}).get("revoked"):
            tx.update(t.reference, {"revoked": True, "revokedAt": firestore.SERVER_TIMESTAMP})
    tx.set(tokens_ref().document(_sha(token)), {"uid": uid, "deviceId": device_id, "revoked": False,
                                                "createdAt": firestore.SERVER_TIMESTAMP, "lastSeen": None})
    tx.set(db.client().collection("realDevices").document(f"{uid}__{device_id}"), {"uid": uid, "deviceId": device_id})
    tx.delete(archive.index().document(f"{uid}__{device_id}"))
    tx.update(dsnap.reference, {
        "archived": False, "archivedAt": firestore.DELETE_FIELD, "purgeAt": firestore.DELETE_FIELD,
        "revoked": False, "uninstalled": False, "status": "offline", "health": "unknown", "registered": True,
        "helperSince": _now(), "installedWith": data.get("via"),
        # what the new install says about itself (version, managed from the app or not) comes with its first report
        "helperVersion": None, "manage": None, "allowedJobs": {},
        # The owner's app-side permissions ("permissions") are kept and reach the new helper with its first report.
        # What it watched nearby is not: the old helper's local list of found things (their addresses, which never
        # leave a device) went with it, so the watched things are looked up again (see _rewatch).
        "rewatch": {"state": "new", "at": _now()}})
    how = {"installer": "installer", "command_line": "command line"}.get(data.get("via"))
    event(tx, uid, device_id, "reinstalled", "info",
          f"Helper reinstalled{f' ({how})' if how else ''} on {d.get('name', 'a device')}; history kept."
          + (" It is back on your map." if d.get("archived") else ""), who="you")


# ------------------------------------------------------------------ discovery and devices watched by a helper

DISCOVERY_TTL = timedelta(hours=24)
WATCHED_PER_HELPER = 10
# The helper's vocabulary (nightlight_helper.py PORTS / MDNS / VENDORS / _guess); anything else is refused.
FOUND_PORTS = (22, 80, 443, 445, 631, 7000, 8123, 25565, 32400)
FOUND_SERVICES = ("remote login (SSH)", "web page", "secure web page", "file sharing", "printer", "Home Assistant",
                  "Minecraft", "Plex", "Chromecast / Google speaker", "AirPlay speaker or TV", "HomeKit accessory",
                  "AirPlay speaker", "router", "media player", "media server", "Apple device", "AirPlay receiver")
FOUND_VENDORS = ("Raspberry Pi", "Synology", "QNAP", "VMware virtual machine", "Philips Hue", "Sonos",
                 "Espressif (smart-home gadget)", "Google", "Amazon", "Ubiquiti", "Nintendo",
                 "private address (likely a phone or laptop)")
PRIVATE_MAC = "private address (likely a phone or laptop)"  # the helper's word for a randomized hardware address
FOUND_GUESSES = ("Home Assistant", "Plex media server", "Minecraft server", "Printer", "File share (NAS or computer)",
                 "Speaker or TV", "Raspberry Pi", "VMware virtual machine", "Computer (remote login)",
                 "Device with a web page", "Unknown device", "Router", "Media server", *FOUND_VENDORS)
# Maker and model are allow-listed, never free text (a device's own words can carry a person's name): the maker is one
# of these brands as spelled here (the helper's KNOWN_MAKERS, normalised there), the model an Apple model from the
# helper's table or something shaped like a product code (see product_code). Same rules as nightlight_helper.py.
MAKERS = ("Apple", "Brother", "Canon", "Epson", "HP", "Xerox", "Fuji Xerox", "Fujifilm", "Lexmark", "Samsung", "Kyocera",
          "Ricoh", "Konica Minolta", "Sharp", "OKI", "Dell", "Pantum", "Netgear", "TP-Link", "ASUS", "Linksys", "D-Link",
          "Ubiquiti", "AVM", "Synology", "QNAP", "Western Digital", "Seagate", "Buffalo", "Asustor", "TerraMaster",
          "Sonos", "Bose", "Sony", "LG", "Philips", "Panasonic", "Yamaha", "Denon", "Marantz", "Onkyo", "Pioneer",
          "Harman", "Roku", "Google", "Amazon", "Microsoft", "Nintendo", "Raspberry Pi", "Huawei", "ZTE", "Xiaomi",
          "Tenda", "Mercusys", "Zyxel", "eero", "Arris", "Technicolor", "Sagemcom", "Cisco", "MikroTik", "Belkin",
          "Vizio", "TCL", "Hisense", "NVIDIA", "ipTIME", "allRadio")
APPLE_MODELS = ("MacBook Pro", "MacBook Air", "MacBook", "Mac mini", "Mac Pro", "iMac", "iPhone", "iPad", "Apple TV",
                "HomePod", "Mac")
SERIES_WORDS = {"docuprint", "laserjet", "officejet", "deskjet", "envy", "pixma", "imageclass", "ecotank", "workforce",
                "nighthawk", "archer", "deco", "orbi", "diskstation", "rackstation", "fritz", "box", "mycloud",
                "readynas", "terastation", "linkstation", "airport", "bravia", "color", "colour", "pro", "plus",
                "mini", "ultra", "series", "wireless", "multifunction", "mfp", "lite"}
MODEL_CHARS = r"^[A-Za-z0-9][A-Za-z0-9 /+-]{0,39}$"


# Hardware ids in a model field: hex pairs joined by - or : ("AA-BB-CC-DD-EE-12"), or a long run of hex digits.
HARDWARE_SHAPE = re.compile(r"(?i)(?:\b|^)[0-9a-f]{2}(?:[-:][0-9a-f]{2}){2,}|[0-9a-f]{8,}")

def product_code(text: str | None) -> str | None:
    """A model that looks like a product code ("HL-L2350DW", "DocuPrint CP115/118 w"): at most 40 characters and 5
    words, a digit somewhere, each word of letters, digits and / + - holding a digit, or a short all-capitals code, a
    single letter, or a known series word. Names ("Alex MacBook"), host names and sentences never pass."""
    if not isinstance(text, str):
        return None
    words = text.split(" ")
    if not text or len(text) > 40 or len(words) > 5 or not re.search(r"\d", text):
        return None
    for w in words:
        if not (w.lower() in SERIES_WORDS or (len(w) == 1 and w.isalnum()) or (
                re.fullmatch(r"[A-Z0-9][A-Z0-9/+-]*[a-z]{0,3}", w) and not HARDWARE_SHAPE.search(w)
                and (re.search(r"\d", w) or (w.isalpha() and w.isupper() and len(w) <= 6)))):
            return None  # a word that isn't a code: a name, a host name, a hardware address
    return text


def product(maker: str | None, model: str | None) -> tuple[str | None, str | None]:
    """(maker, model) as stored: a known maker, and a model only with one (an Apple model from the table, or a
    product code); anything else is dropped."""
    if maker not in MAKERS:
        return None, None
    if maker == "Apple":
        return maker, model if model in APPLE_MODELS else None
    if product_code(model) != model or scrub(model or "")[0] != model:
        return maker, None  # not a product code, or holds something the scrubber hides
    return maker, model


def set_device_names(uid: str, on: bool) -> dict:
    """The owner's switch for names of things nearby. Turning it off also removes every name already kept: from the
    lists of what was found, and from watched things (one still called by its announced name goes back to its
    guess). New lists keep no names from the moment the switch is saved."""
    from . import live
    live.forbid_pool(uid)  # never on a live demo machine's account
    db.user(uid).set({"settings": {"deviceNames": on}}, merge=True)
    if on:
        return {"ok": True, "deviceNames": True}
    # Each change is decided on the document as it is now (a transaction per document), so a list saved or a rename
    # made meanwhile is never undone by this cleanup.
    @firestore.transactional
    def clear_list(tx, ref):
        snap = ref.get(transaction=tx)
        items = (snap.to_dict() or {}).get("items") or [] if snap.exists else []
        if any(it.get("name") for it in items):
            tx.update(ref, {"items": [{**it, "name": None} for it in items]})

    @firestore.transactional
    def clear_device(tx, ref):
        snap = ref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or not (d.get("seenName") or d.get("nameFromSeen")):
            return
        still_announced = d.get("nameFromSeen") is True and d.get("name") == (d.get("seenName") or "")[:40]
        tx.update(ref, {"seenName": firestore.DELETE_FIELD, "nameFromSeen": firestore.DELETE_FIELD,
                        **({"name": (d.get("guess") or "Found device")[:40]} if still_announced else {})})

    for snap in discoveries_ref(uid).get():
        clear_list(db.client().transaction(), snap.reference)
    for snap in db.devices(uid).where(filter=FieldFilter("kind", "==", "watched")).get():
        clear_device(db.client().transaction(), snap.reference)
    return {"ok": True, "deviceNames": False}


def discoveries_ref(uid: str):
    return db.user(uid).collection("discoveries")


def names_on(user: dict) -> bool:
    """Whether this account shows the names things nearby announce ("Living Room"): on unless the owner turned it
    off in Settings. Addresses never leave a device either way."""
    return (user.get("settings") or {}).get("deviceNames", True) is not False


def found_name(text: str | None) -> str | None:
    """A name a thing announces, kept for the owner's own map: never one that holds an address, a hardware id or
    something the scrubber hid."""
    if not isinstance(text, str) or not text.strip() or not text.isprintable() or len(text) > 60:
        return None
    if re.search(r"\[(ip|mac|email|hidden|user)\]|(?<![0-9A-Za-z])[0-9A-Fa-f]{2}(?:[:_-][0-9A-Fa-f]{2}){2,}(?![0-9A-Za-z])"
                 r"|\d{1,3}[-.]\d{1,3}[-.]\d{1,3}[-.]\d{1,3}", text) \
            or any(re.search(r"\d", run) for run in re.findall(r"[0-9A-Fa-f]{6,}", text)):
        return None
    return text.strip()


def _same_thing(d: dict, it: dict, device_id: str) -> bool:
    """Whether a found item is this thing on the map. The hardware fingerprint decides when both have one (another
    machine can get its old address); the finder's id or the address only stand in when one of them has none."""
    hw = (d.get("net") or {}).get("hw")
    if hw and it.get("hw"):
        return hw == it["hw"]
    tag = (d.get("net") or {}).get("self")
    return (d.get("watchedBy") == device_id and it.get("cid") == d.get("cid")) or bool(tag and it.get("tag") == tag)


def _filled_in(d: dict, device_id: str, items: list[dict], taken: set) -> dict:
    """What a new look adds to a thing already on the map: its maker, model, services and announced name when they
    were missing (it may have been added before the helper could tell), and its hardware fingerprint when it had none
    and no other thing on the map holds it. Fills blanks only, and its name only while it is still the guess it was
    given, so nothing the owner typed is changed."""
    if d.get("archived") or d.get("revoked"):
        return {}
    it = next((i for i in items if _same_thing(d, i, device_id)), None)
    if not it:
        return {}
    update = {}
    if not (d.get("net") or {}).get("hw") and it.get("hw") and it["hw"] not in taken:
        update["net.hw"] = it["hw"]
        taken.add(it["hw"])
    if not d.get("model") and it.get("model"):
        update["maker"], update["model"] = it.get("maker") or d.get("maker"), it["model"]  # maker and model together
    elif not d.get("maker") and it.get("maker"):
        update["maker"] = it["maker"]
    if not d.get("vendor") and it.get("vendor"):
        update["vendor"] = it["vendor"]
    services = sorted(set(d.get("services") or []) | set(it.get("services") or []))[:8]
    if services != sorted(d.get("services") or []):
        update["services"] = services
    seen = it.get("name")
    if seen and not d.get("seenName"):
        update["seenName"] = seen
        if d.get("nameFromSeen") is not False and d.get("name") == (d.get("guess") or "Found device")[:40]:
            update["name"], update["nameFromSeen"] = seen[:40], True
    return update


def _rebound(watched, items: list[dict], device_id: str) -> dict:
    """Things this helper watches that a new look found under another id (a reinstalled helper starts its local list
    afresh, so it names them anew): {doc id: the new id, and a port to check that the look saw open}. Matched by
    hardware or address fingerprint (_same_thing); each found item binds at most one watched thing."""
    out, used = {}, {(w.to_dict() or {}).get("cid") for w in watched}
    for w in watched:
        d = w.to_dict() or {}
        if d.get("revoked") or any(it.get("cid") == d.get("cid") for it in items):
            continue
        it = next((i for i in items if i.get("cid") not in used and _same_thing({**d, "cid": None}, i, device_id)),
                  None)
        if not it:
            continue
        ports = it.get("ports") or []
        port = d.get("checkPort") if d.get("checkPort") in ports else next((p for p in WATCH_PORTS if p in ports), None)
        if port is None:
            continue  # nothing to check answers on it now
        used.add(it["cid"])
        out[w.id] = {"cid": it["cid"], "checkPort": port}
    return out


def save_discoveries(token: str, items: list[dict]) -> dict:
    """What a helper found nearby and its owner chose to send (no addresses). Replaces the previous list. Names are
    kept only while the account shows them."""
    @firestore.transactional
    def run(tx):
        uid, device_id = token_owner(tx, token)
        dsnap = db.device(uid, device_id).get(transaction=tx)
        watched = db.devices(uid).where(filter=FieldFilter("watchedBy", "==", device_id)).get(transaction=tx)
        names = names_on(db.user(uid).get(transaction=tx).to_dict() or {})
        name = (dsnap.to_dict() or {}).get("name", "A device")
        on_map = db.devices(uid).where(filter=FieldFilter("kind", "==", "watched")).get(transaction=tx)
        mapped = [w.to_dict() for w in watched]  # already on the map: stays "added" across rediscovery
        kept = [{**it, "name": found_name(it.get("name")) if names else None,
                 "added": any(_same_thing(w, it, device_id) for w in mapped if not w.get("revoked"))} for it in items]
        taken = {(w.to_dict().get("net") or {}).get("hw") for w in on_map} - {None}
        moved = _rebound(watched, kept, device_id)
        rw = (dsnap.to_dict() or {}).get("rewatch")
        if isinstance(rw, dict) and rw.get("state") != "unmatched" and \
                any(w.to_dict().get("checkPort") and not w.to_dict().get("revoked") and w.id not in moved
                    and not any(it.get("cid") == w.to_dict().get("cid") for it in kept) for w in watched):
            tx.update(dsnap.reference, {"rewatch": {**rw, "state": "unmatched"}})  # the owner is asked about the rest
        tx.set(discoveries_ref(uid).document(device_id), {
            "items": kept, "by": device_id, "byName": name,
            "at": firestore.SERVER_TIMESTAMP, "expiresAt": _now() + DISCOVERY_TTL})
        for w in on_map:
            update = {**moved.get(w.id, {}), **_filled_in(w.to_dict(), device_id, kept, taken)}
            if update:
                tx.update(w.reference, update)
        event(tx, uid, device_id, "found", "info", f"{name} found {len(items)} thing(s) nearby you can add.")
        return {"ok": True, "items": len(items)}

    return db.run_transaction(run)


WATCH_PORTS = (8123, 32400, 25565, 445, 631, 443, 80, 22, 7000)  # checked on the first one it answers; AirPlay last


ROLES = ("router", "printer", "fileshare", "smarthome", "server", "speaker", "computer", "other")
ROLE_FROM_GUESS = {"Printer": "printer", "File share (NAS or computer)": "fileshare", "Home Assistant": "smarthome",
                   "Plex media server": "server", "Minecraft server": "server", "Speaker or TV": "speaker",
                   "Raspberry Pi": "computer", "Computer (remote login)": "computer",
                   "VMware virtual machine": "computer", "Synology": "fileshare", "QNAP": "fileshare",
                   "Philips Hue": "smarthome", "Espressif (smart-home gadget)": "smarthome", "Sonos": "speaker",
                   "Router": "router", "Media server": "server"}
GENERIC_GUESSES = ("Raspberry Pi", "VMware virtual machine", "Computer (remote login)", "Device with a web page",
                   "Unknown device", *FOUND_VENDORS)
# What a maker and model say a thing is, when its guess is only generic; the first that matches wins.
ROLE_HINTS = (("router", r"(?i)\b(router|gateway|airport|archer|nighthawk|eero|orbi|deco|fritz|mesh wi-?fi)\b"),
              ("printer", r"(?i)\b(printer|laserjet|deskjet|officejet|pixma|ecotank|workforce|imageclass|mfc|"
                          r"dcp|hl-\w+|ecosys|bizhub)\b"),
              ("fileshare", r"(?i)\b(synology|qnap|diskstation|my ?cloud|asustor|terramaster|readynas|nas)\b"),
              ("speaker", r"(?i)\b(tv|bravia|sonos|roku|chromecast|apple tv|homepod|echo|soundbar|speaker)\b"),
              ("computer", r"(?i)\b(mac mini|macbook|imac|mac pro|mac|raspberry pi|thinkpad)\b"))


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
    if item.get("guess") not in GENERIC_GUESSES and ROLE_FROM_GUESS.get(item.get("guess")):
        return ROLE_FROM_GUESS[item["guess"]]  # what answers on it (a printer service) beats a name
    services = set(item.get("services") or [])
    if "router" in services:
        return "router"
    if "media player" in services:
        return "speaker"
    made = " ".join(x for x in (item.get("maker"), item.get("model")) if x)
    hint = next((role for role, words in ROLE_HINTS if made and re.search(words, made)), None)
    return hint or ROLE_FROM_GUESS.get(item.get("guess")) or ROLE_FROM_GUESS.get(item.get("vendor")) or "other"


def own_tags(devices) -> set:
    """Every address fingerprint that is one of your own devices (each helper's main address and all its others)."""
    return set().union(*(links.tags_of(d) for d in devices if not d.get("archived")))


def found_view(uid: str) -> list[dict]:
    """Everything found nearby that isn't on the map yet, once each: two devices that saw the same thing share its
    fingerprint (same address, same account key), so it becomes one row listing who saw it; a thing whose fingerprint
    is one of your own devices is left out. Untagged items (older helpers) stay one row per finder."""
    now = _now()
    devices = [s.to_dict() for s in db.devices(uid).get()]
    mine = own_tags(devices)
    mine_hw = {(d.get("net") or {}).get("hw") for d in devices if not d.get("archived")} - {None}
    hw_at = {t: (d.get("net") or {}).get("hw") for d in devices if not d.get("archived") for t in links.tags_of(d)}
    looks = [(snap.id, d) for snap in discoveries_ref(uid).get() for d in [snap.to_dict()]
             if not (d.get("expiresAt") and d["expiresAt"] < now)]
    # The hardware fingerprint outlasts an address; an older helper's row joins it through the address both saw.
    same = {it["tag"]: it["hw"] for _id, d in looks for it in d.get("items") or [] if it.get("tag") and it.get("hw")}
    rows: dict[str, dict] = {}
    for snap_id, d in looks:
        for it in d.get("items") or []:
            moved_in = it.get("hw") and hw_at.get(it.get("tag")) and hw_at[it["tag"]] != it["hw"]  # new machine, old address
            if it.get("added") or (it.get("tag") in mine and not moved_in) or it.get("hw") in mine_hw:
                continue
            key = it.get("hw") or same.get(it.get("tag")) or it.get("tag") or f"{snap_id}:{it.get('cid')}"
            row = rows.setdefault(key, {"guess": it.get("guess"), "vendor": it.get("vendor"), "tag": it.get("tag"),
                                        "name": None, "maker": None, "model": None, "services": [], "ports": [],
                                        "seenBy": []})
            row["name"] = row["name"] or it.get("name")
            row["vendor"] = row["vendor"] or it.get("vendor")
            if not row["model"] and it.get("model"):
                row["maker"], row["model"] = it.get("maker") or row["maker"], it["model"]  # maker and model together
            row["maker"] = row["maker"] or it.get("maker")
            row["services"] = sorted(set(row["services"]) | set(it.get("services") or []))[:8]
            row["ports"] = sorted(set(row["ports"]) | set(it.get("ports") or []))[:8]
            if row["guess"] in (None, "Unknown device", "Device with a web page") and it.get("guess"):
                row["guess"] = it["guess"]  # the more specific guess wins
            row["seenBy"].append({"deviceId": snap_id, "name": d.get("byName"), "cid": it.get("cid"),
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


DISCOVER_FROM = "0.9.21"
UNHEALTHY_RESTART_FROM = "0.9.27"  # helpers that restart a running container that fails its health check  # helpers that can look nearby when the app asks


def request_discover(uid: str, device_id: str) -> dict:
    """Ask one device to look nearby. A scan still under way is that scan (asking twice doesn't queue a second); a new
    scan gets its own identity, so a late result from an earlier one can never finish it."""
    return _numbered_request(uid, device_id, "discover")


def _numbered_request(uid: str, device_id: str, kind: str) -> dict:
    """One job of this kind under way per device, each with its own identity. Jobs are numbered per device and kind;
    job n is the action with identity `app_<kind>_<n>` (`once`: a finished one is never reopened). One transaction
    reads the counter and that job: missing or under way, ask for job n again (whoever asked first may still be making
    it; asking again finds it); finished, move to n + 1. Nothing else is recorded, so an interruption anywhere leaves
    nothing half done, and simultaneous requests agree on one job."""
    from . import actions
    slot = db.user(uid).collection("scans").document(device_id if kind == "discover" else f"{device_id}__{kind}")

    @firestore.transactional
    def which(tx):
        user = db.user(uid).get(transaction=tx).to_dict() or {}
        snap = slot.get(transaction=tx)
        n = (snap.to_dict() or {}).get("n", 0) if snap.exists else 0
        a = db.action(uid, _scan_action_id(user, device_id, n, kind)).get(transaction=tx) if n else None
        if n and (not a.exists or (a.to_dict() or {}).get("status") in ("pending", "approved", "running")):
            return n
        tx.set(slot, {"n": n + 1})
        return n + 1

    for _ in range(3):  # a job finishing between choosing and asking: choose again
        n = db.run_transaction(which)
        a = actions.request(uid, kind, device_id, {}, session_id=None, turn_id=f"app_{kind}_{n}",
                            origin="app", once=True)
        if a.get("status") in ("pending", "approved", "running"):
            return a
    return a

def _scan_action_id(user: dict, device_id: str, n: int, kind: str = "discover") -> str:
    """The identity of job n of this kind on this device (as actions.request derives it)."""
    return make_action_id(proposal_key(user.get("demoGeneration"), f"app_{kind}_{n}", device_id,
                                       service_for({}), kind, {}))


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


def add_found(uid: str, helper_id: str, cid: str, name: str | None) -> dict:
    """Put one found thing on the map, watched by the helper that found it (it checks the thing still answers). With
    no name typed, it takes the name it announced (`seenName`), else its guess."""
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
        own = next((h.to_dict() for h in helpers_now if h.to_dict().get("kind") != "watched"
                    and not h.to_dict().get("archived") and item.get("tag") in links.tags_of(h.to_dict())), None)
        if own:  # one of its other addresses (Wi-Fi, a VPN): it is already on the map as itself
            raise ApiError(409, "your_own_device", name=own.get("name"))
        if sum(1 for w in watched if not w.get("revoked")) >= WATCHED_PER_HELPER:  # removed ones free a place
            raise ApiError(429, "watch_capacity")
        port = next((p for p in WATCH_PORTS if p in (item.get("ports") or [])), None)
        if port is None:
            raise ApiError(422, "no_check_port")  # nothing we could check answers on it
        helper_name = hsnap.to_dict().get("name", "your device")
        seen = item.get("name")
        called = name or (seen or item.get("guess") or "Found device")[:40]
        tx.update(dref, {"items": [{**it, "added": it.get("cid") == cid or it.get("added")} for it in d["items"]]})
        routers = {(h.to_dict().get("net") or {}).get("gateway") for h in helpers_now
                   if not h.to_dict().get("archived")} - {None}
        role = role_for(item, routers)
        tx.set(db.device(uid, device_id), {
            "name": called, "kind": "watched", "role": role,
            "purpose": role_purpose(role, helper_name),
            "guess": item.get("guess"), "services": item.get("services") or [], "ports": item.get("ports") or [],
            "realm": "real", "simulated": False, "watchedBy": helper_id, "cid": cid, "checkPort": port,
            "vendor": item.get("vendor"), "maker": item.get("maker"), "model": item.get("model"),
            "health": "unknown", "status": "offline", "vitals": {}, "findings": [],
            "version": 1, "x": 420, "y": 220, "createdAt": firestore.SERVER_TIMESTAMP, "lastSeen": None,
            "registered": True,
            **({"net": {k: v for k, v in (("self", item.get("tag")), ("hw", item.get("hw"))) if v}}
               if item.get("tag") or item.get("hw") else {}),
            **({"seenName": seen, "nameFromSeen": not name} if seen else {})})
        tx.set(db.client().collection("realDevices").document(f"{uid}__{device_id}"),
               {"uid": uid, "deviceId": device_id})
        event(tx, uid, device_id, "joined", "info", f"{called} joined your map, watched by {helper_name}.", who="you")
        links.mark_due(tx, uid)  # it sits behind its finder's router, and may be the router itself: lines change
        return {"ok": True, "deviceId": device_id}

    result = db.run_transaction(run)
    links.infer_quietly(uid)  # its line to the router; if it is the router, the devices behind it get theirs
    return result


def leave(token: str, cleanup: str | None = None) -> dict:
    """The helper revokes its own token (it uninstalled itself, from the app or by hand), in one transaction. A
    removal the owner asked for in the app is closed and the device archived; an uninstall done on the device leaves
    it on the map as offline, history kept (archive.left)."""
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
    from . import live
    live.forbid_pool(uid)  # never on a live demo machine's account
    ref = db.device(uid, device_id)

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or d.get("kind") != "watched" or d.get("revoked"):
            raise not_found()
        dref = discoveries_ref(uid).document(d.get("watchedBy", "_"))
        disc = dref.get(transaction=tx)
        from . import archive
        tx.update(ref, {"watchedBy": None})
        # Off the map for everyone and kept like any removed device (purged after the archive period).
        archive.archive(tx, uid, device_id, d.get("name", "a device"), f"You took {d.get('name', 'a device')} off the map.",
                        "you")
        if disc.exists:
            items = disc.to_dict().get("items") or []
            tx.update(dref, {"items": [{**it, "added": False if it.get("cid") == d.get("cid") else it.get("added")}
                                       for it in items]})
        return {"ok": True, "deviceId": device_id}

    return db.run_transaction(run)


def revoke(uid: str, device_id: str) -> dict:
    """Revoke the device's token(s) and mark it offline, together, in one transaction."""
    from . import live
    live.forbid_pool(uid)  # never on a live demo machine's account
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
        if c.get("state") == "running" and "(unhealthy)" in (c.get("status") or ""):
            out.append({"id": _finding_id("f_ctr_", c["name"]), "check": "container_unhealthy", "severity": "warn",
                        "message": f"{c['name']} is running but failing its own health check.",
                        "evidence": f"container status: {c.get('status')}", "svcId": _doc_id(c["name"])})
        if c.get("state") not in ("running", None):
            out.append({"id": _finding_id("f_ctr_", c["name"]), "check": "container_down", "severity": "warn",
                        "message": f"{c['name']} {_stopped_words(c.get('status'))}.",
                        "evidence": f"container state: {c.get('state')}",
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
    return {"svcId": _doc_id(unit), "plan": f"Restart {friendly} on the {device['name']}: it stopped working.",
            "dryRun": f"Nightlight's helper starts {friendly} (a background service, {unit}) again and checks it is "
                      "still running a few seconds later. Nothing else is touched.",
            "rollback": "Nothing to undo: if it fails again, it simply stays stopped and you'll see why.",
            "command": f"sudo systemctl restart {unit}",
            "blastRadius": [device["id"]], "riskClass": "service"}


def _fix_card(device: dict, params: dict) -> dict:
    if set(params) != {"recipe"} or params["recipe"] not in FIX:
        raise ValueError("bad_target")
    if params["recipe"] not in (device.get("allowedJobs") or {}).get("fix", []):
        raise ValueError("not_allowed_on_device")
    measured = ((device.get("spaceMeasured") or {}).get(params["recipe"]) or {})
    at = measured.get("at")
    age = (_now() - at) if isinstance(at, datetime) else timedelta(0)  # not a datetime yet: written just now
    if measured.get("gb") is not None and measured["gb"] <= NOTHING_GB and age < MEASURED_FOR:
        raise Outcome("nothing_to_free", recipe=params["recipe"], measuredGb=measured["gb"],
                      minutesAgo=int(age.total_seconds() // 60))
    title, what, undo, command = FIX[params["recipe"]]
    return {"svcId": None, "plan": f"{title} on the {device['name']}.",
            "dryRun": f"{what}. Nightlight's helper reports how much space it freed. Nothing else is touched.",
            "rollback": undo, "blastRadius": [device["id"]], "riskClass": "service",
            **({"command": command} if command else {})}


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
                        "back, install the helper on it again and choose \"Continue its history\" when approving.",
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
    if action_type != "restart_container" or set(params) - {"restart"} != {"container"} \
            or params.get("restart", True) is not True:
        raise ValueError("not_applicable")
    name = params["container"]
    if not isinstance(name, str) or not CONTAINER_NAME.fullmatch(name):
        raise ValueError("bad_target")
    if name not in (device.get("allowedJobs") or {}).get(action_type, []):
        raise ValueError("not_allowed_on_device")
    svc = services.get(_doc_id(name))
    if not svc or svc.get("kind") != "container":
        raise ValueError("no_such_container")
    unhealthy = "(unhealthy)" in (svc.get("detail") or "")
    if params.get("restart") and not unhealthy:
        raise ValueError("not_unhealthy")
    if svc.get("status") == "ok":
        raise ValueError("already_running")
    if unhealthy and not params.get("restart"):
        raise ValueError("needs_restart")  # a start card would do nothing for a running container
    if unhealthy:  # running but failing its health check: the restart the card names is the job's own parameter
        if release.newer(UNHEALTHY_RESTART_FROM, device.get("helperVersion")):
            raise ValueError("helper_too_old")
        return {"svcId": _doc_id(name), "plan": f"Restart {name} on the {device['name']}: it is on but not "
                                                f"responding properly (its own health check fails).",
                "dryRun": f"Nightlight's helper restarts {name} and checks it is healthy a few seconds later. {name} "
                          f"is unavailable for a moment. Nothing else is touched.",
                "rollback": "Nothing to undo: it starts again with the same settings and data.",
                "command": f"docker restart {name}",
                "blastRadius": [device["id"]], "riskClass": "service"}
    return {"svcId": _doc_id(name), "plan": f"Start {name} again on the {device['name']}: it has stopped.",
            "dryRun": f"Nightlight's helper starts {name} (an app packaged with Docker) and checks it is still "
                      f"running a few seconds later. Nothing else is touched.",
            "rollback": f"You can stop {name} again on the device (\"docker stop {name}\").",
            "command": f"docker start {name}",
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
    machine = facts.get("machine")  # a fingerprint (validated hex), kept as sent
    facts, _ = scrub_value(facts)
    findings = checks(facts)
    services = {}
    for c in facts.get("containers") or []:
        image = c.get("image") or ""
        services[_doc_id(c["name"])] = {"name": c["name"], "category": "containers", "kind": "container",
                               "status": "ok" if c.get("state") == "running"
                               and "(unhealthy)" not in (c.get("status") or "") else "warn",
                               "version": image.rsplit(":", 1)[1] if ":" in image else None,
                               "detail": c.get("status"), "findings": [],
                               **({"about": a} if (a := apps.about(image, c["name"])) else {})}
    for unit in facts.get("failedUnits") or []:
        services[_doc_id(unit)] = {"name": _friendly(unit), "unit": unit, "category": "system", "kind": "system",
                                   "status": "warn", "failed": True,
                                   **({"about": a} if (a := apps.about(unit)) else {}),
                          "findings": [f for f in findings if f.get("svcId") == _doc_id(unit)]}

    @firestore.transactional
    def run(tx):
        snap = tref.get(transaction=tx)
        t = snap.to_dict() if snap.exists else None
        if not t or t.get("revoked"):
            raise ApiError(401, "invalid_token")
        last = t.get("lastSeen")
        # The minimum gap bounds a misbehaving client, never a helper's normal cadence: the report a helper sends
        # right after finishing a job (so the change shows at once) is let through once per job result.
        if last and (_now() - last).total_seconds() < HEARTBEAT_MIN_SECONDS and not t.get("reportDue"):
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
        rewatch, ask_look, asked = _rewatch(device, watched, facts)
        look[0] = ask_look
        marked, states = apply_issue_states(findings + asked, device.get("issueStates") or {})
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
        tx.update(tref, {"lastSeen": _now(), "reportDue": False})
        extra["diskTrend"] = trend
        if net_changed:
            extra["net"] = net
        if rewatch is not None:
            extra["rewatch"] = rewatch
        mtag = keyed_machine(net_key, machine)
        if mtag and mtag != device.get("machine"):
            extra["machine"] = mtag  # lets a later reinstall on this machine continue this device
        tx.update(dref, {**extra,
            "os": facts.get("os"), "arch": facts.get("arch"), "status": status, "health": "verified",
            "vitals": {"cpu": facts.get("cpuPct"), "mem": facts.get("memPct"), "diskPct": facts.get("diskPct"),
                       "uptime": facts.get("uptimeSec")},
            "findings": marked, "issueStates": states, "lastSeen": firestore.SERVER_TIMESTAMP,
            "version": device.get("version", 1) + 1,
            "helperVersion": facts.get("helperVersion"), "allowedJobs": facts.get("allowedJobs") or {},
            "updatesPending": facts.get("updatesPending"), "containerCount": len(facts.get("containers") or []),
            "manage": facts.get("manage"),
            "macFolders": facts.get("macFolders"),
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
                                    "lastSeen": _now(),  # the last check, answered or not
                                    **({"lastAnswerAt": _now()} if up else {}),
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
                 "permissions": device.get("permissions") or DEFAULT_PERMISSIONS,
                 "deviceNames": names_on(user)}  # whether the helper sends names of things nearby
        jobs = _hand_over(tx, approved, user, uid, device_id) if take_jobs else []
        return uid, device_id, jobs, _poll_every(user), watch_list, {**about, "netKey": net_key}, lines_due

    restarted, look = [False], [False]
    uid, device_id, jobs, poll, watch_list, about, lines_due = db.run_transaction(run)
    if restarted[0]:
        post_mortem(token, device_id, facts)
    if look[0]:  # a reinstalled app-managed device looks nearby once, so it finds what it watched again
        try:
            request_discover(uid, device_id)
        except (ValueError, ApiError):
            pass  # the owner gets the ask instead, once the grace runs out
    if lines_due:
        links.infer_quietly(uid)  # fingerprints changed (or an earlier attempt failed): lines may have too
    offer = release.latest()
    return {"ok": True, "deviceId": device_id, "findings": len(findings), "jobs": jobs, "pollEverySec": poll,
            "watch": watch_list, **about, **({"latestHelper": offer["version"]} if offer else {})}


REWATCH_GRACE = timedelta(minutes=15)  # a look asked for after a reinstall that hasn't brought them back by then


def _rewatch(device: dict, watched, facts: dict) -> tuple:
    """After a reinstall continued this device, the things it watched keep it as their watcher, but the new helper
    can check them only once it has found them nearby again. An app-managed helper is asked to look once (its
    results are matched to the watched things in save_discoveries); a strict one, or a look that didn't find them,
    puts an ask in front of the owner on this device. Returns (new value of the device's `rewatch`: DELETE_FIELD, a
    dict, or None for unchanged; whether to ask for a look; findings to add). Pure: the caller writes."""
    rw = device.get("rewatch")
    if not isinstance(rw, dict):
        return None, False, []
    reported = {r.get("cid") for r in facts.get("watchResults") or []}
    missing = [w.to_dict() for w in watched if (w.to_dict() or {}).get("checkPort")
               and (w.to_dict() or {}).get("cid") not in reported]
    if not missing:
        return firestore.DELETE_FIELD, False, []  # every watched thing is checked again (or there is none)
    app = facts.get("manage") == "app" and not release.newer(DISCOVER_FROM, facts.get("helperVersion"))
    if app and rw.get("state") == "new":
        return {"state": "asked", "at": _now()}, True, []
    at = rw.get("at")
    if app and rw.get("state") == "asked" and isinstance(at, datetime) and _now() - at < REWATCH_GRACE:
        return None, False, []  # the look is under way
    names = [m.get("name") or "a watched device" for m in missing]
    said = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    how = ("Tap Look nearby on this device while they are switched on: it finds them again and checks them as "
           "before." if app else "Run `nightlight discover` on this device and pick them: it then checks them as "
           "before.")
    return None, False, [{"id": "f_rewatch", "check": "reinstalled_watch", "severity": "warn",
                          "message": f"Reinstalled: re-allow watching {said}? {how}",
                          "evidence": "the helper was reinstalled; its list of things found nearby starts empty",
                          "fix": "discover" if app else "discover_on_device"}]


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


MAC_FOLDERS_FROM = "0.9.22"  # helpers that can raise the Mac folder prompts when the app asks


def device_setup(uid: str, device_id: str, preset: str, auto_update: bool, mac_folders: bool) -> dict:
    """The one-time choice made when a device first connects: what Nightlight may do there (a preset, applied to
    what the device reported), automatic updates, and on a Mac the private folders (macOS asks right away, while the
    person is at the Mac). Runs once: a repeated or concurrent request gets the first one's result and never undoes
    what the owner changed in Settings since. Settings changes it later."""
    from . import live
    live.forbid_pool(uid)  # never on a live demo machine's account
    from . import actions, release
    ref = db.device(uid, device_id)

    @firestore.transactional
    def claim(tx):
        snap = ref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or d.get("realm") != "real" or d.get("kind") == "watched" or d.get("archived"):
            raise not_found()
        prior = d.get("setup") or {}
        stalled = prior.get("state") == "applying" and prior.get("claimedAt") is not None \
            and (_now() - prior["claimedAt"]).total_seconds() > SETUP_STALL_SECONDS
        if prior and not stalled:  # already chosen (or being applied right now): that outcome stands
            return d, None
        # The choices are kept with the claim, so an attempt interrupted part-way is finished later with the same
        # choices (never this request's, which may differ), and its folder job keeps one identity.
        choice = {k: prior.get(k) for k in ("preset", "autoUpdate", "macFolders", "permsApplied")} if stalled else \
            {"preset": preset, "autoUpdate": auto_update, "macFolders": mac_folders}
        if d.get("manage") == "app":
            choice["attempt"] = new_id("setup")  # this attempt's identity: only it may write or finish this setup
            tx.update(ref, {"setup": {**choice, "state": "applying", "claimedAt": _now()}})
        return d, choice

    d, choice = db.run_transaction(claim)
    if choice is None:
        return {"ok": True, **(d.get("setup") or {}), "already": True}
    preset, auto_update, mac_folders = choice["preset"], choice["autoUpdate"], choice["macFolders"]
    out = {"preset": preset, "applied": False, "trimmed": False, "macFoldersAction": None}
    why = None
    if d.get("manage") == "app":
        services = [s.to_dict() for s in db.services(uid, device_id).get()]
        containers = sorted({s.get("name") for s in services if s.get("kind") == "container" and s.get("name")})
        units = sorted({s.get("unit") for s in services if s.get("kind") == "system" and s.get("unit")})
        out["trimmed"] = len(containers) > PERMISSION_TARGETS or len(units) > PERMISSION_TARGETS \
            or len(containers) + len(units) > PERMISSION_TARGETS
        containers, units = containers[:PERMISSION_TARGETS], units[:PERMISSION_TARGETS]
        logs = (containers + units)[:PERMISSION_TARGETS]  # the same limits as the switches (and the helper)
        current = d.get("permissions") or DEFAULT_PERMISSIONS
        perms = {"watch": {**DEFAULT_PERMISSIONS, "autoUpdate": auto_update, "logs": logs},  # reading logs is watching
                 "fix": {"diagnose": True, "cleanup": True, "updates": True, "autoUpdate": auto_update,
                         "logs": logs, "restart_container": containers, "restart_service": units},
                 "custom": {**DEFAULT_PERMISSIONS, **current, "autoUpdate": auto_update}}[preset]
        if not choice.get("permsApplied"):  # an earlier attempt that already applied them: leave them
            try:  # recorded in the same transaction as the permissions, and only while this attempt owns the setup
                set_permissions(uid, device_id, perms, also={"setup.permsApplied": True},
                                setup_attempt=choice.get("attempt"))
            except ApiError as e:
                if e.code != "setup_superseded":
                    raise
                return {"ok": True, **((ref.get().to_dict() or {}).get("setup") or {}), "already": True}
        out["applied"] = True
    else:
        why = "strict_device" if d.get("manage") == "strict" else "update_helper"
    if mac_folders:
        if "mac" not in (d.get("os") or "").lower():
            why = why or "not_a_mac"
        elif d.get("manage") != "app" or release.newer(MAC_FOLDERS_FROM, d.get("helperVersion")):
            why = why or "update_helper"
        else:
            try:  # one identity per device: a retry finds the same job
                out["macFoldersAction"] = actions.request(uid, "mac_folders", device_id, {}, session_id=None,
                                                          turn_id="app_macfolders_setup", origin="app",
                                                          once=True)["id"]
            except ValueError as e:
                why = why or str(e)  # e.g. device_not_reporting: the rest of the choice still stands
    done = out["applied"] or d.get("manage") == "strict"
    # Done once chosen: applied, or a strict device (its choices are made on the device). A helper too old to take
    # the choice keeps its card until it is updated.
    @firestore.transactional
    def finish(tx):  # only the attempt that owns the setup finishes it
        cur = ((ref.get(transaction=tx).to_dict() or {}).get("setup") or {})
        if d.get("manage") == "app" and cur.get("attempt") != choice.get("attempt"):
            return False
        if done:
            tx.update(ref, {"setupAt": firestore.SERVER_TIMESTAMP, "setupPreset": preset,
                            "setup": {**out, "state": "done", "attempt": choice.get("attempt"),
                                      **({"why": why} if why else {})}})
        else:
            tx.update(ref, {"setup": firestore.DELETE_FIELD})
        return True

    if not db.run_transaction(finish):
        return {"ok": True, **((ref.get().to_dict() or {}).get("setup") or {}), "already": True}
    return {"ok": True, **out, "done": done, **({"why": why} if why else {})}


PERMISSION_TARGETS = 20  # per list, as PermissionsBody and the helper allow
SETUP_STALL_SECONDS = 120  # a setup still "applying" after this was interrupted: the next request finishes it


def request_mac_folders(uid: str, device_id: str) -> dict:
    """Ask an app-managed Mac (helper 0.9.22+) to raise macOS's folder prompts now. One request under way at a time:
    asking again while it runs returns it; a finished one is followed by a new one (each its own identity)."""
    from . import actions, release
    d = db.device(uid, device_id).get().to_dict() or {}
    if d.get("realm") != "real" or d.get("kind") == "watched" or d.get("archived"):
        raise not_found()
    if "mac" not in (d.get("os") or "").lower():
        raise ValueError("not_a_mac")
    if d.get("manage") != "app" or release.newer(MAC_FOLDERS_FROM, d.get("helperVersion")):
        raise ValueError("update_helper")
    a = _numbered_request(uid, device_id, "mac_folders")
    return {"actionId": a["id"], "status": a["status"]}

def set_permissions(uid: str, device_id: str, perms: dict, also: dict | None = None,
                    setup_attempt: str | None = None) -> dict:
    """Only for a device whose owner chose "let the app manage it" on the device, and only for things that device
    reported. The helper applies them on its next report (and still checks each action itself)."""
    from . import live
    live.forbid_pool(uid)  # never on a live demo machine's account
    ref = db.device(uid, device_id)

    @firestore.transactional
    def run(tx):
        snap = ref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d or d.get("realm") != "real" or d.get("kind") == "watched" or d.get("revoked"):
            raise not_found()
        if d.get("manage") != "app":
            raise ApiError(409, "strict_device" if d.get("manage") == "strict" else "update_helper")
        if setup_attempt is not None:  # a setup attempt writes only while it still owns an unfinished setup
            st = d.get("setup") or {}
            if st.get("attempt") != setup_attempt or st.get("state") != "applying" or st.get("permsApplied"):
                raise ApiError(409, "setup_superseded")
        services = [s.to_dict() for s in db.services(uid, device_id).get(transaction=tx)]
        clean = permission_writes(tx, uid, device_id, d, services, perms, also)
        return {"ok": True, "permissions": clean}

    return db.run_transaction(run)


def log_targets(services) -> set:
    """What this device reported that log reading can be allowed for: its containers and system services."""
    return {s.get("name") for s in services if s.get("kind") == "container"} | \
        {s.get("unit") for s in services if s.get("kind") == "system" and s.get("unit")}


def permission_writes(tx, uid: str, device_id: str, d: dict, services, perms: dict,
                      also: dict | None = None) -> dict:
    """Validate and write a device's new permissions with their Activity line (writes only: the caller has read the
    device `d` and its `services` in this transaction). Returns the clean permissions."""
    ref = db.device(uid, device_id)
    containers = {s.get("name") for s in services if s.get("kind") == "container"}
    units = {s.get("unit") for s in services if s.get("kind") == "system" and s.get("unit")}
    if not set(perms["restart_container"]) <= containers or not set(perms["restart_service"]) <= units \
            or not set(perms["logs"]) <= containers | units:
        raise ApiError(422, "unknown_target")  # only things this device reported
    before = d.get("permissions") or DEFAULT_PERMISSIONS
    clean = {"diagnose": bool(perms["diagnose"]), "cleanup": bool(perms.get("cleanup")),
             "updates": perms.get("updates") is not False, "autoUpdate": bool(perms.get("autoUpdate")),
             **{k: sorted(set(perms[k])) for k in ("logs", "restart_container", "restart_service")}}
    tx.update(ref, {"permissions": clean, "permissionsAt": firestore.SERVER_TIMESTAMP, **(also or {})})
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
    return clean


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


def _hand_over(tx, approved, user: dict, uid: str, device_id: str) -> list[dict]:
    """Approved jobs are handed over once (at most once: a job claimed here is never handed out again)."""
    from . import capabilities
    ready = user.get("demo", {}).get("state") == "ready"
    jobs = []
    for a in approved:
        if not ready or a.get("demoGeneration") != user.get("demoGeneration"):
            continue  # a reset is withdrawing it (or has): never hand it out
        tx.update(a.reference, {"status": "running", "claimedAt": firestore.SERVER_TIMESTAMP})
        jobs.append({"id": a.id, "type": a.get("type"), "params": a.get("params")})
    if any(not getattr(capabilities.get(j["type"]), "reads", False) for j in jobs):
        mark_changed(tx, uid, device_id)
    return jobs


def mark_changed(tx, uid: str, device_id: str) -> None:
    """The device may change from now on (a changing job was handed over, or one reported, whatever its outcome):
    readings taken before this are no longer reused (actions._same_read). Writes only."""
    tx.set(db.device(uid, device_id), {"changedAt": firestore.SERVER_TIMESTAMP}, merge=True)


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
        return _hand_over(tx, approved, user, uid, device_id), _poll_every(user)

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


