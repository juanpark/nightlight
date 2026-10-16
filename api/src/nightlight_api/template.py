"""The 'home-pi' sample home: simulated devices a judge can try without owning any hardware."""

# Disk sizes are chosen so the story reads cleanly: old logs (2.1 GB) take the Pi from 94% to 61% full.
HOME_PI = {
    "devices": [
        {
            "id": "pi-1", "name": "Raspberry Pi", "kind": "pi", "os": "Debian 12 (simulated)",
            "purpose": "Runs your home VPN and your car's data logger.",
            "health": "verified", "x": 120, "y": 80, "diskGb": 6.4, "baseUsedGb": 1.6,
            "diskConsumers": [
                {"id": "logs", "what": "old log files", "sizeGb": 2.1},
                {"id": "db_backup", "what": "car logger database backup", "sizeGb": 1.4},
                {"id": "images", "what": "unused Docker images", "sizeGb": 0.9},
            ],
            "vitals": {"cpu": 18, "mem": 61, "uptime": 1209600},
            "services": [
                {"id": "wireguard", "name": "WireGuard VPN", "category": "network", "status": "ok",
                 "version": "1.0.20210914", "updateAvailable": False},
                {"id": "teslamate", "name": "TeslaMate", "category": "home", "status": "ok",
                 "version": "1.29.2", "updateAvailable": True},
            ],
        },
        {
            "id": "mac-1", "name": "Mac Mini", "kind": "mac", "os": "macOS 15 (simulated)",
            "purpose": "Runs your home automation.", "health": "verified", "x": 320, "y": 80,
            "diskGb": 256, "baseUsedGb": 133, "diskConsumers": [],
            "vitals": {"cpu": 9, "mem": 48, "uptime": 604800},
            "services": [{"id": "home-assistant", "name": "Home Assistant", "category": "home", "status": "ok",
                          "version": "2026.10.1", "updateAvailable": False}],
        },
        {
            "id": "nas-1", "name": "NAS", "kind": "nas", "os": "NAS OS (simulated)",
            "purpose": "Stores family photos and runs the nightly backup.", "health": "verified", "x": 220, "y": 220,
            "diskGb": 4000, "baseUsedGb": 2840, "diskConsumers": [],
            "vitals": {"cpu": 4, "mem": 33, "uptime": 2592000},
            "services": [
                {"id": "nfs", "name": "Shared folder", "category": "files", "status": "ok", "version": "4.2",
                 "updateAvailable": False},
                {"id": "backup", "name": "Nightly backup", "category": "files", "status": "warn", "version": "n/a",
                 "updateAvailable": False,
                 "findings": [{"id": "f_backup_verify", "check": "backup_never_test_restored", "severity": "warn",
                               "message": "Backups run, but no one has checked that they can be restored.",
                               "evidence": "last test restore: never"}]},
            ],
        },
        {
            "id": "game-1", "name": "Game server", "kind": "gameserver", "os": "Ubuntu 24.04 (simulated)",
            "purpose": "Hosts your family's Minecraft world.", "health": "verified", "x": 120, "y": 360,
            "diskGb": 120, "baseUsedGb": 40,
            "diskConsumers": [
                {"id": "world", "what": "Minecraft world", "sizeGb": 6.2},
                {"id": "backups", "what": "world backups", "sizeGb": 18.6},
                {"id": "logs", "what": "old log files", "sizeGb": 0.8},
            ],
            "vitals": {"cpu": 35, "mem": 78, "uptime": 1728000},
            "services": [
                {"id": "minecraft", "name": "Minecraft server", "category": "games", "status": "ok",
                 "version": "1.21.4", "latestVersion": "1.21.5", "updateAvailable": True,
                 "players": {"online": 2, "max": 10}, "lastBackupDaysAgo": 9},
            ],
        },
        {
            "id": "nvr-1", "name": "Camera recorder", "kind": "camera", "os": "Recorder firmware (simulated)",
            "purpose": "Records the front-door camera.", "health": "unknown", "x": 420, "y": 220,
            "diskGb": 1000, "baseUsedGb": 630, "diskConsumers": [],
            "vitals": {"cpu": None, "mem": None, "uptime": None}, "services": [],
        },
        {
            "id": "router-1", "name": "Router", "kind": "router", "os": "Router firmware (simulated)",
            "purpose": "Connects everything to the internet.", "health": "verified", "x": 270, "y": 360,
            "diskGb": None, "baseUsedGb": None, "diskConsumers": [],
            "vitals": {"cpu": 7, "mem": 40, "uptime": 5184000}, "services": [],
        },
    ],
    # The story starts with the Pi's disk nearly full.
    "initial_incident": {"deviceId": "pi-1", "kind": "disk_full"},
}

# A signed-in owner starts with only their own (real) devices; the sample home can be switched on and off.
EMPTY = {"devices": [], "initial_incident": None}

TEMPLATES = {"home-pi": HOME_PI, "empty": EMPTY}
