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
APP_SERVICE = {"mac-1": "immich"}  # the sample app that can go unhealthy, per device


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
    # Device-native findings only; the service-derived ones are rebuilt from the current services below, so cleared
    # service problems disappear and nothing is counted twice.
    findings = [f for f in d.get("findings", []) if f.get("check") not in keep and not f.get("fromService")]
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
        findings += [{**f, "svcId": svc_id, "fromService": True} for f in svc["findings"]]
    findings.sort(key=lambda f: -SEVERITY.get(f["severity"], 0))
    d["findings"] = findings
    worst = max((SEVERITY.get(f["severity"], 0) for f in findings), default=0)
    if worst < 2 and pct is not None and pct >= 80:
        worst = 2
    d["status"] = "crit" if worst >= 3 else "warn" if worst == 2 else "ok"
    return d, svcs


# ------------------------------------------------------------------ incidents (demo panel / seed)

INCIDENTS = {"disk_full", "logs_locked", "server_lagging", "backup_overdue", "update_available"}
INCIDENT_CHECK = {"disk_full": "disk_over_90", "server_lagging": "memory_high", "backup_overdue": "backup_overdue",
                  "update_available": "update_available"}


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
        if game.get("latestVersion") in (None, game.get("version")):  # already current: a newer release appears
            major, _, patch = (game.get("version") or "1.0.0").rpartition(".")
            game["latestVersion"] = f"{major}.{int(patch) + 1}" if patch.isdigit() else f"{game.get('version')}.1"
        game["updateAvailable"] = True
        event = {"kind": "update_available", "severity": "info", "svcId": "minecraft"}
    else:
        raise ValueError("unknown_incident")
    d, svcs = refresh(d, svcs)
    if "message" not in event:
        check = INCIDENT_CHECK[kind]
        match = next((f for f in d["findings"] if f.get("check") == check), None)
        event["message"] = match["message"] if match else f"Something changed on the {d['name']}."
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


def _copy_world(d, game) -> None:
    """Add one copy of the world to the backups folder and mark the backup fresh."""
    world, backups = _consumer(d, "world"), _consumer(d, "backups")
    if world and backups:
        backups["sizeGb"] = round(backups["sizeGb"] + world["sizeGb"], 1)
    game["lastBackupDaysAgo"] = 0


def _backup_apply(d, svcs):
    game = _need_game(svcs)
    before = game.get("lastBackupDaysAgo")
    _copy_world(d, game)
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
    _copy_world(d, game)  # the promised backup, before changing anything
    game["version"] = game.get("latestVersion")
    game["updateAvailable"] = False
    game.setdefault("players", {})["online"] = 0
    d, svcs = refresh(d, svcs)
    return {"summary": f"Backed up the world and updated Minecraft {before} → {game['version']}.",
            "before": {"version": before}, "after": {"version": game["version"]}}, d, svcs


# riskClass sets the trust ceiling; `allowlisted` jobs may run on their own at "Ask me for new things" once approved.
def _game_svc(d):
    return "minecraft"


def _app(d, svcs):
    s = svcs.get(APP_SERVICE.get(d["id"]) or "")
    if not s:
        raise ValueError("no_app")
    return s


def _app_name(s):
    return (s.get("name") or "the app").capitalize()


def _restart_app_card(d, svcs):
    s = _app(d, svcs)
    if s.get("status") == "ok" and not s.get("findings"):
        raise ValueError("app_healthy")
    return {"svcId": APP_SERVICE[d["id"]],
            "plan": f"Restart {_app_name(s)} on the {d['name']} so it reconnects to its database.",
            "dryRun": f"{_app_name(s)} is unavailable for about 30 seconds. Your photos and its database are not "
                      "touched.",
            "rollback": "Nothing to undo: it starts again with the same settings."}


def _restart_app_apply(d, svcs):
    s = _app(d, svcs)
    s.update(status="ok", findings=[], detail="Up 1 minute (healthy)")
    d, svcs = refresh(d, svcs)
    return {"summary": f"Restarted {_app_name(s)}; it reports healthy again and reconnected to its database.",
            "before": {"status": "warn"}, "after": {"status": "ok"}}, d, svcs


ACTIONS = {
    "rotate_logs": {"label": "Clean up old log files", "riskClass": "routine", "allowlisted": True,
                    "svc": lambda d: DISK_SERVICE.get(d["id"]), "card": _rotate_logs_card, "apply": _rotate_logs_apply,
                    "snapshot": lambda d, s: {"diskPct": disk_pct(d)}},
    "backup_world": {"label": "Back up the game world", "riskClass": "routine", "allowlisted": True,
                     "svc": _game_svc, "card": _backup_card, "apply": _backup_apply,
                     "snapshot": lambda d, s: {"lastBackupDaysAgo": (_game(s) or {}).get("lastBackupDaysAgo")}},
    "restart_server": {"label": "Restart the game server", "riskClass": "service", "allowlisted": False,
                       "svc": _game_svc, "card": _restart_card, "apply": _restart_apply,
                       "snapshot": lambda d, s: {"mem": (d.get("vitals") or {}).get("mem")}},
    "restart_app": {"label": "Restart an app", "riskClass": "service", "allowlisted": False,
                    "svc": lambda d: APP_SERVICE.get(d["id"]), "card": _restart_app_card, "apply": _restart_app_apply,
                    "snapshot": lambda d, s: {"status": (s.get(APP_SERVICE.get(d["id"]) or "") or {}).get("status")}},
    "update_server": {"label": "Update the game server", "riskClass": "service", "allowlisted": False,
                      "svc": _game_svc, "card": _update_card, "apply": _update_apply,
                      "snapshot": lambda d, s: {"version": (_game(s) or {}).get("version")}},
}


FIX_FOR = {"disk_over_90": "rotate_logs", "memory_high": "restart_server", "backup_overdue": "backup_world",
           "update_available": "update_server", "container_unhealthy": "restart_app"}  # which job answers which


def fixes(device: dict, services: dict) -> list[dict]:
    """The jobs that answer this device's current problems, with what each card would say: the agent proposes one of
    these by calling the tool of that name (only those that apply right now are listed)."""
    checks = [f.get("check") for f in device.get("findings") or []]
    checks += [f.get("check") for s in services.values() for f in s.get("findings") or []]
    out = []
    for check in dict.fromkeys(checks):
        job = FIX_FOR.get(check)
        if not job:
            continue
        try:
            out.append({"tool": job, "for": check, "plan": card(device, services, job, {})["plan"]})
        except ValueError:
            pass
    return out


def service_for(device: dict, action_type: str) -> str | None:
    """The service a job concerns. Depends only on the device and job, never on mutable state, so a proposal's
    identity is the same before and after the job has run."""
    return ACTIONS[action_type]["svc"](device)


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
        snap = ACTIONS[action_type]["snapshot"](d, svcs)  # unchanged state, shown on the failed card
        return False, {"ok": False, "summary": f"The {d['name']}'s {what}, so nothing was changed.",
                       "before": snap, "after": dict(snap)}, d, svcs
    result, d, svcs = ACTIONS[action_type]["apply"](d, svcs)
    return True, {"ok": True, **result}, d, svcs
