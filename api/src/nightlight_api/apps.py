"""What an app is, in plain words: the apps people commonly run at home, recognised from a container's image or name
or a system service's unit. Each gets an icon key (a fixed set the web app draws) and one line a non-expert can read.
Anything not in the table gets nothing here, and the app falls back to its category."""

import re

ICONS = ("plex", "jellyfin", "pihole", "adguard", "homeassistant", "homebridge", "mqtt", "nodered", "tailscale",
         "wireguard", "vpn", "nextcloud", "syncthing", "minecraft", "docker", "database", "web", "dns", "backup",
         "download", "monitoring", "photos", "files", "git", "passwords", "ssh", "generic")

# (pattern on the image or name, icon, one line). First match wins, so specific names come before general ones.
CATALOG = (
    (r"plex", "plex", "Plex: streams your films, shows and music to your TVs and phones."),
    (r"jellyfin", "jellyfin", "Jellyfin: streams your films, shows and music to your TVs and phones."),
    (r"emby", "jellyfin", "Emby: streams your films, shows and music to your TVs and phones."),
    (r"pi-?hole", "pihole", "Pi-hole: blocks ads and trackers for every device on your network."),
    (r"adguard", "adguard", "AdGuard Home: blocks ads and trackers for every device on your network."),
    (r"home-?assistant", "homeassistant", "Home Assistant: runs your smart-home devices and automations."),
    (r"homebridge", "homebridge", "Homebridge: lets Apple Home control devices Apple doesn't support."),
    (r"mosquitto|mqtt|emqx", "mqtt", "MQTT broker: the message hub smart-home gadgets talk through."),
    (r"node-?red", "nodered", "Node-RED: wires devices and services together into automations."),
    (r"zigbee2mqtt|zwave", "homeassistant", "Bridges Zigbee or Z-Wave smart-home gadgets to your hub."),
    (r"tailscale", "tailscale", "Tailscale: a private network so you can reach home from anywhere."),
    (r"zerotier", "vpn", "ZeroTier: a private network so you can reach home from anywhere."),
    (r"wireguard|wg-easy|wg-quick", "wireguard", "WireGuard: a VPN so you can reach home from anywhere."),
    (r"openvpn", "vpn", "OpenVPN: a VPN so you can reach home from anywhere."),
    (r"nextcloud", "nextcloud", "Nextcloud: your own cloud for files, calendars and contacts."),
    (r"syncthing", "syncthing", "Syncthing: keeps folders in sync between your devices."),
    (r"immich", "photos", "Immich: backs up and organises the photos from your phones."),
    (r"photoprism", "photos", "PhotoPrism: organises and browses your photo library."),
    (r"minecraft|papermc|spigot", "minecraft", "A Minecraft server for you and your friends."),
    (r"vaultwarden|bitwarden", "passwords", "Vaultwarden: your own password manager."),
    (r"gitea|forgejo|gitlab", "git", "A code host for your own projects."),
    (r"uptime-?kuma", "monitoring", "Uptime Kuma: checks your sites and services are up."),
    (r"grafana", "monitoring", "Grafana: charts of how your systems are doing."),
    (r"prometheus|node-exporter|cadvisor|netdata", "monitoring", "Collects measurements of how your systems are doing."),
    (r"portainer", "docker", "Portainer: a web page for managing your containers."),
    (r"watchtower", "docker", "Watchtower: updates your containers automatically."),
    (r"duplicati|restic|borg|kopia|urbackup", "backup", "Backs up your files on a schedule."),
    (r"qbittorrent|transmission|deluge|sabnzbd|nzbget", "download", "Downloads files in the background."),
    (r"sonarr|radarr|lidarr|prowlarr|bazarr|overseerr|jellyseerr", "download",
     "Finds and organises shows and films for your media library."),
    (r"postgres|mariadb|mysql|mongo|redis|influxdb|sqlite", "database", "A database: stores data for other apps."),
    (r"nginx-proxy-manager|traefik|caddy|haproxy", "web", "A gateway that sends web traffic to the right app."),
    (r"nginx|apache|httpd|lighttpd", "web", "A web server: serves web pages."),
    (r"unbound|bind9|dnsmasq|coredns", "dns", "A DNS server: turns names into addresses for your network."),
    (r"smbd|samba|nfs|filebrowser", "files", "Shares files with the other computers at home."),
    (r"sshd?$|openssh", "ssh", "Remote login (SSH): lets you or Nightlight sign in to run commands."),
    (r"^docker$|dockerd|containerd", "docker", "Docker: runs your other apps in containers."),
    (r"cron", "generic", "Runs scheduled jobs."),
)
# A known name must start a word: "plex" is Plex, "complex-app" is not.
_COMPILED = tuple((re.compile(rf"(?:^|[^a-z0-9])(?:{p})", re.I), icon, line) for p, icon, line in CATALOG)


def about(*names: str | None) -> dict | None:
    """{icon, oneLiner, source: "catalog"} for the first known app among these names (image first: it is what the
    software is; a container's own name is whatever someone typed), else None."""
    for name in names:
        if not isinstance(name, str) or not name:
            continue
        base = name.rsplit("/", 1)[-1].split(":", 1)[0].split("@", 1)[0]  # "lscr.io/linuxserver/plex:latest" -> plex
        for rx, icon, line in _COMPILED:
            if rx.search(base) or rx.search(name):
                return {"icon": icon, "oneLiner": line, "source": "catalog"}
    return None
