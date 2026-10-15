"""The simulator: the fake outside world. Pure functions over device dicts, safe inside retried transactions.

Only device state is simulated. The agent, approvals and trust run for real on top of it.
"""

from copy import deepcopy

SERVICE_FOR_DISK = {"pi-1": "teslamate"}  # which service a full disk hurts, for the card and the finding


def disk_pct(device: dict) -> int | None:
    total = device.get("diskGb")
    if not total:
        return None
    used = (device.get("baseUsedGb") or 0) + sum(c["sizeGb"] for c in device.get("diskConsumers", []))
    return round(used / total * 100)


def _consumer(device: dict, consumer_id: str) -> dict | None:
    return next((c for c in device.get("diskConsumers", []) if c["id"] == consumer_id), None)


def refresh(device: dict) -> dict:
    """Recompute derived fields (disk %, status, disk finding) after any change."""
    d = deepcopy(device)
    pct = disk_pct(d)
    d.setdefault("vitals", {})["diskPct"] = pct
    findings = [f for f in d.get("findings", []) if f.get("check") != "disk_over_90"]
    if pct is not None and pct >= 90:
        findings.append({"id": f"f_disk_{d['id']}", "check": "disk_over_90", "severity": "crit",
                         "message": f"The {d['name']}'s disk is {pct}% full.",
                         "evidence": f"/ at {pct}% of {d['diskGb']} GB"})
    d["findings"] = findings
    if pct is not None and pct >= 90:
        d["status"] = "crit"
    elif pct is not None and pct >= 80:
        d["status"] = "warn"
    else:
        d["status"] = "ok"
    return d


# ------------------------------------------------------------------ incidents (demo panel / seed)

INCIDENTS = {"disk_full", "logs_locked"}


def inject(device: dict, kind: str) -> tuple[dict, dict]:
    """Return (updated device, event fields). Raises ValueError if the incident doesn't apply."""
    d = deepcopy(device)
    if kind == "disk_full":
        logs = _consumer(d, "logs")
        if logs is None:
            raise ValueError("no_logs")
        target_used = 0.94 * d["diskGb"]
        others = (d.get("baseUsedGb") or 0) + sum(c["sizeGb"] for c in d["diskConsumers"] if c["id"] != "logs")
        logs["sizeGb"] = round(max(target_used - others, 0.1), 1)
        d = refresh(d)
        return d, {"kind": "disk_full", "severity": "crit", "svcId": SERVICE_FOR_DISK.get(d["id"]),
                   "message": f"The {d['name']}'s disk is {d['vitals']['diskPct']}% full."}
    if kind == "logs_locked":
        d["simFailNext"] = True
        return d, {"kind": "logs_locked", "severity": "info", "svcId": SERVICE_FOR_DISK.get(d["id"]),
                   "message": f"Another program is holding the {d['name']}'s log folder."}
    raise ValueError("unknown_incident")


# ------------------------------------------------------------------ actions

ACTIONS = {
    "rotate_logs": {"label": "Clean up old log files", "riskClass": "routine", "parameterless": True},
}


def card(device: dict, action_type: str, params: dict) -> dict:
    """What the approval card shows: plan, dry run, blast radius, rollback, risk."""
    if action_type != "rotate_logs":
        raise ValueError("unknown_action")
    logs = _consumer(device, "logs")
    if logs is None:
        raise ValueError("no_logs")
    before = disk_pct(device)
    freed = max(round(logs["sizeGb"], 1), 0)
    after_dev = deepcopy(device)
    _consumer(after_dev, "logs")["sizeGb"] = 0.0
    after = disk_pct(after_dev)
    return {
        "svcId": SERVICE_FOR_DISK.get(device["id"]),
        "plan": f"Compress and remove log files older than 7 days on the {device['name']}.",
        "dryRun": f"Would free about {freed} GB ({before}% → {after}% full). No running service is stopped.",
        "blastRadius": [device["id"]],
        "rollback": "Removed logs are moved to an archive for 24 hours (simulated). "
                    "Restoring them is not available in this demo.",
        "riskClass": ACTIONS[action_type]["riskClass"],
    }


def apply(device: dict, action_type: str, params: dict) -> tuple[bool, dict, dict]:
    """Run the action against the simulated device. Returns (ok, result, updated device)."""
    if action_type != "rotate_logs":
        raise ValueError("unknown_action")
    d = deepcopy(device)
    before = disk_pct(d)
    if d.pop("simFailNext", False):
        return False, {"ok": False, "summary": f"The {d['name']}'s log folder was locked by another program, "
                                               "so nothing was removed.",
                       "before": {"diskPct": before}, "after": {"diskPct": before}}, d
    logs = _consumer(d, "logs")
    freed = round(logs["sizeGb"], 1)
    logs["sizeGb"] = 0.0
    d = refresh(d)
    after = d["vitals"]["diskPct"]
    return True, {"ok": True, "summary": f"Freed {freed} GB on the {d['name']} ({before}% → {after}% full).",
                  "before": {"diskPct": before}, "after": {"diskPct": after}}, d
