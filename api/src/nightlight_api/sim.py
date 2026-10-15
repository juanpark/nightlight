"""The simulator: the fake outside world. Pure functions over device and service dicts, safe inside retried
transactions. Only device state is simulated; the agent, approvals and trust run for real on top of it.

Health checks are deterministic rules here, not the model: the model explains them.
Game-server conventions follow the common self-hosted Minecraft setup (a world folder, copies of it as backups,
a server version that updates in place).
"""

from copy import deepcopy

SEVERITY = {"crit": 3, "warn": 2, "info": 1}
# Which service a full disk hurts, for the card and the finding.
DISK_SERVICE = {"pi-1": "teslamate", "game-1": "minecraft"}


def disk_pct(device: dict) -> int | None:
    total = device.get("diskGb")
    if not total:
        return None
    used = (device.get("baseUsedGb") or 0) + sum(c["sizeGb"] for c in device.get("diskConsumers", []))
    return round(used / total * 100)


def _consumer(device: dict, consumer_id: str) -> dict | None:
    return next((c for c in device.get("diskConsumers", []) if c["id"] == consumer_id), None)


def _game(services: dict) -> dict | None:
    return services.get("minecraft")


# ------------------------------------------------------------------ health checks

def _service_findings(svc: dict) -> list[dict]:
    out = []
    if svc.get("id") == "minecraft" or svc.get("kind") == "minecraft":
        days = svc.get("lastBackupDaysAgo")
        if days is not None and days > 2:
            out.append({"id": "f_backup_overdue", "check": "backup_overdue", "severity": "warn",
                        "message": f"The Minecraft world hasn't been backed up in {days} days.",
                        "evidence": f"last world backup: {days} days ago", "svcId": "minecraft"})
        if svc.get("updateAvailable"):
            out.append({"id": "f_update_available", "check": "update_available", "severity": "info",
                        "message": f"Minecraft {svc.get('latestVersion')} is available "
                                   f"(you have {svc.get('version')}).",
                        "evidence": f"installed {svc.get('version')}, latest {svc.get('latestVersion')}",
                        "svcId": "minecraft"})
    return out


def refresh(device: dict, services: dict | None = None) -> tuple[dict, dict]:
    """Recompute derived fields after any change: disk %, findings, health. Returns (device, services)."""
    d, svcs = deepcopy(device), deepcopy(services or {})
    pct = disk_pct(d)
    d.setdefault("vitals", {})["diskPct"] = pct
    keep = {"disk_over_90", "memory_high", "backup_overdue", "update_available"}  # recomputed below
    findings = [f for f in d.get("findings", []) if f.get("check") not in keep]
    if pct is not None and pct >= 90:
        findings.append({"id": f"f_disk_{d['id']}", "check": "disk_over_90", "severity": "crit",
                         "message": f"The {d['name']}'s disk is {pct}% full.",
                         "evidence": f"/ at {pct}% of {d['diskGb']} GB", "svcId": DISK_SERVICE.get(d["id"])})
    mem = (d.get("vitals") or {}).get("mem")
    if _game(svcs) is not None and mem is not None and mem >= 90:
        findings.append({"id": "f_memory_high", "check": "memory_high", "severity": "crit",
                         "message": f"The {d['name']} is almost out of memory ({mem}%), so the game lags.",
                         "evidence": f"memory {mem}% used", "svcId": "minecraft"})
    for svc_id, svc in svcs.items():
        sf = _service_findings({**svc, "id": svc_id})
        base = [f for f in svc.get("findings", []) if f.get("check") not in keep]
        svc["findings"] = base + sf
        worst = max((SEVERITY.get(f["severity"], 0) for f in svc["findings"]), default=0)
        svc["status"] = "crit" if worst >= 3 else "warn" if worst == 2 else "ok"
        # Every service problem also counts toward its device's health light.
        findings += [{**f, "svcId": svc_id} for f in svc["findings"]]
    findings.sort(key=lambda f: -SEVERITY.get(f["severity"], 0))
    d["findings"] = findings
    worst = max((SEVERITY.get(f["severity"], 0) for f in findings), default=0)
    if worst < 2 and pct is not None and pct >= 80:
        worst = 2
    d["status"] = "crit" if worst >= 3 else "warn" if worst == 2 else "ok"
    return d, svcs


# ------------------------------------------------------------------ incidents (demo panel / seed)

INCIDENTS = {"disk_full", "logs_locked", "server_lagging", "backup_overdue", "update_available"}


def inject(device: dict, services: dict, kind: str) -> tuple[dict, dict, dict]:
    """Return (device, services, event fields). Raises ValueError if the incident doesn't apply."""
    d, svcs = deepcopy(device), deepcopy(services)
    game = _game(svcs)
    if kind == "disk_full":
        logs = _consumer(d, "logs")
        if logs is None:
            raise ValueError("no_logs")
        others = (d.get("baseUsedGb") or 0) + sum(c["sizeGb"] for c in d["diskConsumers"] if c["id"] != "logs")
        logs["sizeGb"] = round(max(0.94 * d["diskGb"] - others, 0.1), 1)
        event = {"kind": "disk_full", "severity": "crit", "svcId": DISK_SERVICE.get(d["id"])}
    elif kind == "logs_locked":
        d["simFailNext"] = True
        event = {"kind": "logs_locked", "severity": "info", "svcId": DISK_SERVICE.get(d["id"]),
                 "message": f"Another program is holding the {d['name']}'s log folder."}
    elif kind == "server_lagging":
        if game is None:
            raise ValueError("no_game")
        d.setdefault("vitals", {})["mem"] = 96
        event = {"kind": "server_lagging", "severity": "crit", "svcId": "minecraft",
                 "message": "Players say the Minecraft server is lagging."}
    elif kind == "backup_overdue":
        if game is None:
            raise ValueError("no_game")
        game["lastBackupDaysAgo"] = 9
        event = {"kind": "backup_overdue", "severity": "warn", "svcId": "minecraft"}
    elif kind == "update_available":
        if game is None:
            raise ValueError("no_game")
        game["updateAvailable"] = True
        event = {"kind": "update_available", "severity": "info", "svcId": "minecraft"}
    else:
        raise ValueError("unknown_incident")
    d, svcs = refresh(d, svcs)
    if "message" not in event:
        top = next((f for f in d["findings"] if f.get("svcId") == event["svcId"] or event["kind"] == "disk_full"),
                   None)
        event["message"] = top["message"] if top else f"Something changed on the {d['name']}."
    return d, svcs, event


# ------------------------------------------------------------------ actions

def _rotate_logs_card(d, svcs):
    logs = _consumer(d, "logs")
    if logs is None:
        raise ValueError("no_logs")
    before = disk_pct(d)
    after_dev = deepcopy(d)
    _consumer(after_dev, "logs")["sizeGb"] = 0.0
    return {"svcId": DISK_SERVICE.get(d["id"]),
            "plan": f"Compress and remove log files older than 7 days on the {d['name']}.",
            "dryRun": f"Would free about {round(logs['sizeGb'], 1)} GB ({before}% → {disk_pct(after_dev)}% full). "
                      "No running service is stopped.",
            "rollback": "Removed logs are moved to an archive for 24 hours (simulated). "
                        "Restoring them is not available in this demo."}


def _rotate_logs_apply(d, svcs):
    before = disk_pct(d)
    logs = _consumer(d, "logs")
    freed = round(logs["sizeGb"], 1)
    logs["sizeGb"] = 0.0
    d, svcs = refresh(d, svcs)
    after = d["vitals"]["diskPct"]
    return {"summary": f"Freed {freed} GB on the {d['name']} ({before}% → {after}% full).",
            "before": {"diskPct": before}, "after": {"diskPct": after}}, d, svcs


def _need_game(svcs):
    game = _game(svcs)
    if game is None:
        raise ValueError("no_game")
    return game


def _backup_card(d, svcs):
    game = _need_game(svcs)
    world = (_consumer(d, "world") or {}).get("sizeGb", 0)
    return {"svcId": "minecraft",
            "plan": "Save a copy of the Minecraft world to the backups folder.",
            "dryRun": f"Copies about {world} GB; players can keep playing; last backup was "
                      f"{game.get('lastBackupDaysAgo', '?')} days ago.",
            "rollback": "Nothing to undo: it only adds a copy, and old copies are kept."}


def _backup_apply(d, svcs):
    game = _need_game(svcs)
    before = game.get("lastBackupDaysAgo")
    world = _consumer(d, "world")
    backups = _consumer(d, "backups")
    if world and backups:
        backups["sizeGb"] = round(backups["sizeGb"] + world["sizeGb"], 1)
    game["lastBackupDaysAgo"] = 0
    d, svcs = refresh(d, svcs)
    return {"summary": f"Backed up the Minecraft world (last backup was {before} days ago).",
            "before": {"lastBackupDaysAgo": before}, "after": {"lastBackupDaysAgo": 0}}, d, svcs


def _restart_card(d, svcs):
    game = _need_game(svcs)
    online = (game.get("players") or {}).get("online", 0)
    return {"svcId": "minecraft",
            "plan": "Restart the Minecraft server to clear its memory.",
            "dryRun": f"About 1 minute offline; {online} player(s) online will be disconnected and can rejoin. "
                      f"Memory should drop from {(d.get('vitals') or {}).get('mem')}% to about 45%.",
            "rollback": "Nothing to undo: the server comes back on its own with the same world."}


def _restart_apply(d, svcs):
    game = _need_game(svcs)
    before = (d.get("vitals") or {}).get("mem")
    d.setdefault("vitals", {})["mem"] = 45
    d["vitals"]["uptime"] = 60
    game.setdefault("players", {})["online"] = 0
    d, svcs = refresh(d, svcs)
    return {"summary": f"Restarted the Minecraft server; memory {before}% → 45%. Players can rejoin now.",
            "before": {"mem": before}, "after": {"mem": 45}}, d, svcs


def _update_card(d, svcs):
    game = _need_game(svcs)
    if not game.get("updateAvailable"):
        raise ValueError("no_update")
    return {"svcId": "minecraft",
            "plan": f"Back up the world, then update Minecraft {game.get('version')} → {game.get('latestVersion')}.",
            "dryRun": "About 2 minutes offline; players are disconnected; mods and plugins may need their own updates.",
            "rollback": "Restore the backup taken just before the update (simulated)."}


def _update_apply(d, svcs):
    game = _need_game(svcs)
    before = game.get("version")
    game["version"] = game.get("latestVersion")
    game["updateAvailable"] = False
    game["lastBackupDaysAgo"] = 0
    game.setdefault("players", {})["online"] = 0
    d, svcs = refresh(d, svcs)
    return {"summary": f"Backed up the world and updated Minecraft {before} → {game['version']}.",
            "before": {"version": before}, "after": {"version": game["version"]}}, d, svcs


# riskClass sets the trust ceiling; `allowlisted` jobs may run on their own at "Ask me for new things" once approved.
ACTIONS = {
    "rotate_logs": {"label": "Clean up old log files", "riskClass": "routine", "allowlisted": True,
                    "card": _rotate_logs_card, "apply": _rotate_logs_apply},
    "backup_world": {"label": "Back up the game world", "riskClass": "routine", "allowlisted": True,
                     "card": _backup_card, "apply": _backup_apply},
    "restart_server": {"label": "Restart the game server", "riskClass": "service", "allowlisted": False,
                       "card": _restart_card, "apply": _restart_apply},
    "update_server": {"label": "Update the game server", "riskClass": "service", "allowlisted": False,
                      "card": _update_card, "apply": _update_apply},
}


def card(device: dict, services: dict, action_type: str, params: dict) -> dict:
    """What the approval card shows: plan, dry run, blast radius, rollback, risk. ValueError if it doesn't apply."""
    if action_type not in ACTIONS:
        raise ValueError("unknown_action")
    c = ACTIONS[action_type]["card"](deepcopy(device), deepcopy(services))
    return {**c, "blastRadius": [device["id"]], "riskClass": ACTIONS[action_type]["riskClass"]}


def apply(device: dict, services: dict, action_type: str, params: dict) -> tuple[bool, dict, dict, dict]:
    """Run the action on the simulated device. Returns (ok, result, device, services)."""
    if action_type not in ACTIONS:
        raise ValueError("unknown_action")
    d, svcs = deepcopy(device), deepcopy(services)
    if d.pop("simFailNext", False):
        what = "log folder was locked by another program" if action_type == "rotate_logs" \
            else "game server didn't respond in time"
        return False, {"ok": False, "summary": f"The {d['name']}'s {what}, so nothing was changed.",
                       "before": {}, "after": {}}, d, svcs
    result, d, svcs = ACTIONS[action_type]["apply"](d, svcs)
    return True, {"ok": True, **result}, d, svcs
