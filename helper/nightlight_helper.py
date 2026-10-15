#!/usr/bin/env python3
"""Nightlight helper: reports a device's health to Nightlight. Read-only.

It sends only: OS name, CPU architecture, CPU / memory / disk percentages, uptime, Docker container names and states,
the names of failed system services, and how many software updates are waiting. It never sends host names, IP
addresses, logs, files or passwords, and it never changes anything on the device.

Usage:
  nightlight_helper.py enrol <API_URL> <CODE> [--name NAME]   # once: trade the one-time code for a device token
  nightlight_helper.py once                                    # send one report
  nightlight_helper.py run [--every SECONDS]                   # keep reporting (default every 60 s)
  nightlight_helper.py show                                    # print what would be sent, without sending

Python 3.8+, standard library only; uses psutil when it is installed.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

VERSION = "0.1.0"
CONFIG_DIR = os.environ.get("NIGHTLIGHT_HOME", os.path.join(os.path.expanduser("~"), ".config", "nightlight"))
CONFIG = os.path.join(CONFIG_DIR, "helper.json")


def _run(cmd, timeout=20):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _os_name():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')[:80]
    except OSError:
        pass
    if sys.platform == "darwin":
        return ("macOS " + platform.mac_ver()[0]).strip()[:80]
    return platform.platform()[:80]


def _cpu_mem_uptime():
    try:
        import psutil  # optional
        boot = psutil.boot_time()
        return psutil.cpu_percent(interval=1), psutil.virtual_memory().percent, int(time.time() - boot)
    except Exception:
        pass
    cpu = mem = up = None
    try:
        load = os.getloadavg()[0]
        cpu = min(round(load / (os.cpu_count() or 1) * 100, 1), 100.0)
    except (OSError, AttributeError):
        pass
    if sys.platform == "darwin":
        mem, up = _mac_mem_uptime()
        return cpu, mem, up
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0])
        mem = round((1 - info["MemAvailable"] / info["MemTotal"]) * 100, 1)
        with open("/proc/uptime") as f:
            up = int(float(f.read().split()[0]))
    except (OSError, KeyError, ValueError):
        pass
    return cpu, mem, up


def _mac_mem_uptime():
    mem = up = None
    out = _run(["memory_pressure"])
    for line in out.splitlines():
        if "free percentage" in line:
            try:
                mem = round(100 - float(line.rsplit(":", 1)[1].strip().rstrip("%")), 1)
            except ValueError:
                pass
    boot = _run(["sysctl", "-n", "kern.boottime"])  # "{ sec = 1726000000, usec = 0 } ..."
    try:
        up = int(time.time() - int(boot.split("sec =")[1].split(",")[0]))
    except (IndexError, ValueError):
        pass
    return mem, up


def _disk():
    # On macOS "/" is the read-only system volume; people's data lives on the Data volume.
    path = "/System/Volumes/Data" if sys.platform == "darwin" and os.path.isdir("/System/Volumes/Data") else "/"
    usage = shutil.disk_usage(path)
    return round(usage.used / usage.total * 100, 1)


def _containers():
    if not shutil.which("docker"):
        return []
    out = _run(["docker", "ps", "-a", "--format", "{{json .}}"])
    rows = []
    for line in out.splitlines()[:50]:
        try:
            c = json.loads(line)
        except ValueError:
            continue
        rows.append({"name": c.get("Names", "")[:64], "image": c.get("Image", "")[:128],
                     "state": c.get("State", "")[:32], "status": c.get("Status", "")[:64]})
    return rows


def _failed_units():
    if not shutil.which("systemctl"):
        return []
    out = _run(["systemctl", "--failed", "--plain", "--no-legend", "--no-pager"])
    return [line.split()[0][:128] for line in out.splitlines() if line.strip()][:50]


def _updates_pending():
    if shutil.which("apt"):
        out = _run(["apt", "list", "--upgradable"], timeout=60)
        return sum(1 for line in out.splitlines() if "upgradable from" in line)
    return None


def facts():
    cpu, mem, up = _cpu_mem_uptime()
    return {"helperVersion": VERSION, "os": _os_name(), "arch": platform.machine()[:16], "cpuPct": cpu,
            "memPct": mem, "diskPct": _disk(), "uptimeSec": up, "containers": _containers(),
            "failedUnits": _failed_units(), "updatesPending": _updates_pending()}


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _load():
    with open(CONFIG) as f:
        return json.load(f)


def enrol(api, code, name):
    status, body = _post(api.rstrip("/") + "/helper/enrol", {"code": code, "name": name})
    if status != 201:
        sys.exit(f"Enrolment failed ({status}): {body.get('code', body)}")
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # the token is a secret: owner-only
    with os.fdopen(fd, "w") as f:
        json.dump({"api": api.rstrip("/"), "token": body["token"], "deviceId": body["deviceId"]}, f)
    print(f"Joined Nightlight as device {body['deviceId']}. Token saved to {CONFIG} (owner-only).")


def once():
    cfg = _load()
    status, body = _post(cfg["api"] + "/helper/heartbeat", facts(), {"X-Device-Token": cfg["token"]})
    print(f"Report sent ({status}): {body}")
    return status


def main():
    p = argparse.ArgumentParser(description="Nightlight helper (read-only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enrol")
    e.add_argument("api")
    e.add_argument("code")
    e.add_argument("--name", default=platform.system() or "My device")
    sub.add_parser("once")
    sub.add_parser("show")
    r = sub.add_parser("run")
    r.add_argument("--every", type=int, default=60)
    a = p.parse_args()
    if a.cmd == "enrol":
        enrol(a.api, a.code, a.name[:40])
    elif a.cmd == "once":
        once()
    elif a.cmd == "show":
        print(json.dumps(facts(), indent=2))
    else:
        while True:
            once()
            time.sleep(max(a.every, 30))


if __name__ == "__main__":
    main()
