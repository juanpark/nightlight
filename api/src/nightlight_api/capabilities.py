"""Everything a real device can be asked to do, declared once (docs/adr/0001-capability-registry.md).

A capability says how to build its card from the device and the parameters, how it is approved, and what follows
from its approval and its result. The pipeline in `actions.py` handles every capability the same way and never
names one; the sample home keeps its own simulated pipeline (`sim.py`, with the trust ladder).
"""

from dataclasses import dataclass
from typing import Callable

from . import real, release


@dataclass
class Ctx:
    uid: str
    device: dict
    services: dict  # service doc id -> service doc
    params: dict


@dataclass(frozen=True)
class Capability:
    name: str
    label: str
    approval: str  # "device": allowed on the device itself, no card | "card": one tap | "passkey": signed card
    build: Callable[[Ctx], tuple[dict, dict]]  # -> (card fields, clean params); ValueError(code) when it can't
    reads: bool = False  # only reads: its result is evidence the asking turn narrates (no follow-up of its own)
    keeps_output: bool = False  # the result keeps what the device printed (scrubbed there and here)
    reports_state: bool = False  # the result says what state the target was left in (e.g. running)
    on_device: bool = True  # handed to the device's helper (False: the server finishes it, e.g. a grant)
    while_silent: bool = False  # may be asked for while the device isn't reporting
    after_approval: Callable | None = None  # (uid, action) after it was approved, outside the transaction
    on_signed: Callable | None = None  # (tx, uid, action) -> [(ref, doc, merge)]: committed with the signature
    # (tx, uid, action, device, current) -> [(ref, doc, merge)]: reads here, writes returned. `current` is False
    # when a sample-home reset replaced the chat that asked: the device's own state is still recorded then, but
    # nothing new is created for the old conversation.
    on_result: Callable | None = None


def _card(device: dict, plan: str, what: str, undo: str, risk: str, svc_id: str | None = None) -> dict:
    return {"svcId": svc_id, "plan": plan, "dryRun": what, "rollback": undo, "blastRadius": [device["id"]],
            "riskClass": risk}


# ------------------------------------------------------------------ builders (validation + the card)

def _restart_container(c: Ctx):
    return real.card(c.device, c.services, "restart_container", c.params), c.params


def _restart_service(c: Ctx):
    return real.card(c.device, c.services, "restart_service", c.params), c.params


def _fix(c: Ctx):
    return real.card(c.device, c.services, "fix", c.params), c.params


def _remove(c: Ctx):
    return real.card(c.device, c.services, "remove_device", c.params), c.params


def _update(c: Ctx):
    offer = release.latest()
    d = c.device
    if not offer:
        raise ValueError("no_release")
    if c.params != {"version": offer["version"]}:  # the version is part of the request (and so of its identity)
        raise ValueError("not_the_release_on_offer")
    if d.get("kind") == "watched" or d.get("revoked"):
        raise ValueError("not_applicable")
    if not release.newer(offer["version"], d.get("helperVersion")):
        raise ValueError("up_to_date")
    if "signed" not in (d.get("allowedJobs") or {}).get("update", []):
        raise ValueError("update_by_hand" if not release.newer(d.get("helperVersion"), "0.8.99") else "updates_off")
    return _card(d, f"Update the Nightlight helper on the {d.get('name')} from {d.get('helperVersion')} to "
                    f"{offer['version']}.",
                 "The helper downloads the new version, installs it only if Nightlight's signature checks out and it "
                 "passes a self-test, then restarts itself.",
                 "On the device: nightlight rollback (the previous version is kept).", "service"), \
        {"version": offer["version"]}


def _diagnose(c: Ctx):
    target = c.params.get("target")
    real.diagnose_target_ok(c.device, c.services, target)
    logs = target in (c.device.get("allowedJobs") or {}).get("logs", [])
    return _card(c.device, f"Look into {target} on the {c.device['name']} (read-only).",
                 "Reads its status" + (" and its last log lines" if logs else "") + "; changes nothing.",
                 "Nothing to undo.", "read"), {"target": target}


def _inspect(c: Ctx):
    what = real.inspect_ok(c.device, c.params.get("what"))
    return _card(c.device, f"Look around the {c.device['name']}: {', '.join(what)} (read-only).",
                 "Runs the helper's fixed read-only checks; changes nothing.", "Nothing to undo.", "read"), \
        {"what": what}


def _discover(c: Ctx):
    from . import real, release
    if c.device.get("manage") != "app":
        raise ValueError("strict_device")  # a strict device looks only when someone runs it there
    if release.newer(real.DISCOVER_FROM, c.device.get("helperVersion")):
        raise ValueError("update_helper_first")
    return _card(c.device, f"Look for other devices on the {c.device['name']}'s network (read-only).",
                 "Lists what answers nearby: a guess at what each thing is, its maker and the services it offers. "
                 "Addresses never leave the device; nothing joins your map until you add it under Found nearby.",
                 "Nothing to undo.", "read"), {}


def _expert_read(c: Ctx):
    from . import expert
    clean = expert.read_params(c.uid, c.device, c.params.get("command"))
    return _card(c.device, f"Run on the {c.device['name']} (read-only): {clean['command']}",
                 "A read-only command under the investigation you signed; the device checks it is read-only.",
                 "Nothing to undo.", "read"), clean


def _expert_command(c: Ctx):
    from . import expert
    return expert.card(c.device, c.params)


def _expert_grant(c: Ctx):
    from . import expert
    return expert.grant_card(c.device, c.params)


# ------------------------------------------------------------------ hooks

def _finish_removal(uid: str, a: dict) -> None:
    from . import archive
    archive.after_approval(uid, a["id"])


def _playbook_result(tx, uid: str, a: dict, device: dict, current: bool) -> list:
    """A playbook's checks came back: match causes in code; for the chat that asked, a card per allowed clean-up."""
    from . import playbooks
    book = playbooks.library().get(a.get("playbook"))
    if not book or not a["result"]["ok"]:
        return []
    a["result"]["playbook"] = playbooks.evaluate(book, a["result"].get("output") or "", device)
    return playbooks.cards_for_findings(tx, uid, a, device) if current else []


def _store_grant(tx, uid: str, a: dict) -> list:
    from . import expert
    return [expert.grant_write(uid, a)]


def _helper_updated(tx, uid: str, a: dict, device: dict, current: bool) -> list:
    """The device says it now runs (or already ran) this version: the app shows it at once, not at the next report."""
    from . import db
    if not a["result"]["ok"]:
        return []
    return [(db.device(uid, device["id"]), {"helperVersion": a["params"]["version"]}, True)]


def _service_recovered(tx, uid: str, a: dict, device: dict, current: bool) -> list:
    from . import db
    if not a["result"]["ok"] or not a.get("svcId"):
        return []
    # recovered: no new restart card until the device reports it failed again
    return [(db.services(uid, device["id"]).document(a["svcId"]),
             {"status": "ok", "detail": (a["result"].get("after") or {}).get("state"), "failed": False}, True)]


REGISTRY: dict[str, Capability] = {c.name: c for c in (
    Capability("restart_container", "Restart a stopped container", "card", _restart_container,
               reports_state=True, on_result=_service_recovered),
    Capability("restart_service", "Restart a stopped system service", "card", _restart_service,
               reports_state=True, on_result=_service_recovered),
    Capability("fix", "Clean up space", "card", _fix),
    Capability("update_helper", "Update the helper", "card", _update, on_result=_helper_updated),
    Capability("remove_device", "Remove a device", "card", _remove, while_silent=True,
               after_approval=_finish_removal),
    Capability("diagnose", "Look into", "device", _diagnose, reads=True, keeps_output=True),
    Capability("inspect", "Look around", "device", _inspect, reads=True, keeps_output=True,
               on_result=_playbook_result),
    Capability("discover", "Look for devices nearby", "card", _discover, reads=True),
    Capability("expert_read", "Investigate (read-only command)", "device", _expert_read, reads=True,
               keeps_output=True),
    Capability("expert_command", "Run a command you signed", "passkey", _expert_command, keeps_output=True),
    Capability("expert_grant", "Investigate with commands (read-only, 15 minutes)", "passkey", _expert_grant,
               on_device=False, on_signed=_store_grant),
)}


def get(name: str) -> Capability | None:
    return REGISTRY.get(name)
