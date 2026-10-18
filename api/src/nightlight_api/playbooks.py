"""Playbooks (playbooks.yaml): known problems solved the same way every time, without the AI. A run asks the device
for the playbook's read-only checks; when they come back, causes are matched here, in code, and the clean-ups the
device allows are put up as approval cards. Gemini is only needed for what no playbook recognises."""

import re
from functools import lru_cache
from pathlib import Path

import yaml
from google.cloud import firestore

from . import actions, real

_UNIT_GB = {"b": 1 / 1024 ** 3, "k": 1 / 1024 ** 2, "m": 1 / 1024, "g": 1.0, "t": 1024.0}


@lru_cache(maxsize=1)
def library() -> dict[str, dict]:
    books = yaml.safe_load((Path(__file__).with_name("playbooks.yaml")).read_text())
    out = {}
    for b in books:
        assert set(b["checks"]) <= set(real.INSPECT) and 1 <= len(b["checks"]) <= real.MAX_INSPECT, b["id"]
        for c in b["causes"]:
            assert c.get("fix") is None or c["fix"] in real.FIX, (b["id"], c["id"])
            c["_re"] = re.compile(c["match"], re.M)
        out[b["id"]] = b
    return out


def _gb(text: str) -> float | None:
    m = re.fullmatch(r"\s*([\d.]+)\s*([kKmMgGtT])?i?(B)?\s*", text or "")
    if not m:
        return None
    unit = m.group(2) or ("b" if m.group(3) else "g")  # "0B" is bytes; a bare number (journal "1.2G" style) is GB
    try:
        return float(m.group(1)) * _UNIT_GB[unit.lower()]
    except ValueError:
        return None


def _fits(cause: dict, m: re.Match) -> bool:
    groups = m.groupdict()
    if "min_gb" in cause:
        size = _gb(groups.get("size") or "")
        if size is None or size < cause["min_gb"]:
            return False
    for key, least in (cause.get("min_value") or {}).items():
        try:
            if float(groups.get(key) or "nan") < least:
                return False
        except ValueError:
            return False
    return True


def evaluate(book: dict, output: str, device: dict) -> dict:
    """Which known causes the checks' output shows, in the playbook's order; at most one hit per cause."""
    allowed = set((device.get("allowedJobs") or {}).get("fix", []))
    cleanup_on = bool(allowed) or bool((device.get("permissions") or {}).get("cleanup"))
    found = []
    for cause in book["causes"]:
        hit = next((m for m in cause["_re"].finditer(output or "") if _fits(cause, m)), None)
        if not hit:
            continue
        words = {k: (v or "").strip()[:120] for k, v in hit.groupdict().items()}
        row = {"cause": cause["id"], "say": cause["say"].format(**words)}
        if cause.get("advice"):
            row["advice"] = cause["advice"].format(**words)
        if cause.get("fix"):
            row["fix"] = cause["fix"]
            row["fixAllowed"] = cause["fix"] in allowed
            if cleanup_on and not row["fixAllowed"]:
                row["fixUnavailable"] = True  # switched on, but the device doesn't offer it (why isn't known here)
        found.append(row)
    nothing = book.get("nothing")
    if isinstance(nothing, dict):  # said differently per system: a Linux server has no Documents or Movies folder
        nothing = nothing["mac" if "mac" in str(device.get("os") or "").lower() else "other"]
    return {"id": book["id"], "title": book["title"], "found": found, "nothing": None if found else nothing}


def offered(device: dict) -> list[dict]:
    """The playbooks this device can run (it offers all their checks), suggested first when a finding matches."""
    if device.get("realm") != "real":
        return []
    checks = set((device.get("allowedJobs") or {}).get("inspect", []))
    findings = {f.get("id") for f in device.get("findings") or [] if (f.get("state") or "new") == "new"}
    out = [{"id": b["id"], "title": b["title"], "about": b["about"], "suggested": bool(findings & set(b["findings"]))}
           for b in library().values() if set(b["checks"]) <= checks]
    return sorted(out, key=lambda b: not b["suggested"])


def start(uid: str, device_id: str, book_id: str, *, session_id: str, turn_id: str, generation: int,
          fence=None, mode: str = "quick") -> dict:
    book = library().get(book_id)
    if not book:
        raise ValueError("unknown_playbook")
    return actions.request_inspection(uid, session_id=session_id, turn_id=turn_id, generation=generation,
                                      device_id=device_id, what=book["checks"], fence=fence,
                                      extra={"playbook": book_id}, mode=mode)


SPACE = "disk_full"  # the playbook behind "where did my space go / clear the junk"


def space_checks(device: dict) -> tuple[list[str], list[str]]:
    """(checks of the space playbook this device offers, those it doesn't): a device runs what it can, and the
    answer says what couldn't be looked at."""
    offered = set((device.get("allowedJobs") or {}).get("inspect", []))
    checks = library()[SPACE]["checks"]
    return [c for c in checks if c in offered], [c for c in checks if c not in offered]


def measure(output: str, what: list, device: dict) -> dict[str, float]:
    """GB each clean-up would free, from the lines these checks printed (recipe -> GB). A missing line is unknown,
    never zero: the helper leaves out both small places and places it couldn't measure (timeout, unreadable)."""
    sizes: dict[str, float] = {}
    for cause in library()[SPACE]["causes"]:
        fix = cause.get("fix")
        hit = cause["_re"].search(output or "") if fix and fix not in sizes else None
        if hit and (gb := _gb(hit.groupdict().get("size") or "")) is not None:
            sizes[fix] = round(gb, 2)
    return sizes


def summary(result: dict) -> str:
    """The playbook's findings in plain sentences (for the chat follow-up and the agent)."""
    pb = result or {}
    lines = [f"Checkup \"{pb.get('title')}\":"]
    for f in pb.get("found") or []:
        tail = ""
        if f.get("fix"):
            tail = (" I've put up a card to " + (t := real.FIX[f["fix"]][0])[0].lower() + t[1:] + "." if f.get("card")
                    else " A clean-up exists, but it isn't available on this device." if f.get("fixUnavailable")
                    else " A clean-up exists, but \"clean up space\" isn't switched on for this device."
                    if not f.get("fixAllowed") else " A clean-up exists, but no card could be made right now.")
        lines.append(f"- {f['say']}{tail}" + (f" {f['advice']}" if f.get("advice") else ""))
    if pb.get("nothing"):
        lines.append(pb["nothing"])
    return "\n".join(lines)


def cards_for_findings(tx, uid: str, a: dict, device: dict) -> list:
    """One pending clean-up card per allowed fix a playbook found. Reads only (the caller writes, after all reads);
    each finding gets `card` = the card's id, or None when no card could be made."""
    from . import capabilities, db
    from .ids import action_id as make_action_id, proposal_key
    cap = capabilities.get("fix")
    out = []
    for f in a["result"]["playbook"]["found"]:
        if not f.get("fixAllowed"):
            continue
        params = {"recipe": f["fix"]}
        key = proposal_key(a["demoGeneration"], f"{a['turnId']}:{a['id']}", device["id"], None, "fix", params)
        aid = make_action_id(key)
        f["card"] = None
        if db.action(uid, aid).get(transaction=tx).exists:
            continue  # can't happen for a first result; never make a second card
        try:
            fields, clean = cap.build(capabilities.Ctx(uid, device, {}, params))
        except ValueError:
            continue
        f["card"] = aid
        out.append((db.action(uid, aid), {
            "proposalKey": key, "type": "fix", "deviceId": device["id"], "params": clean, **fields,
            "status": "pending", "demoGeneration": a["demoGeneration"], "deviceVersion": device.get("version"),
            "trustLevelAtProposal": "ask", "resolvedBy": "real_device", "realm": "real",
            "sessionId": a["sessionId"], "turnId": a["turnId"], "mode": a.get("mode", "quick"),
            "fromPlaybook": a["id"],
            "createdAt": firestore.SERVER_TIMESTAMP}, False))
    return out
