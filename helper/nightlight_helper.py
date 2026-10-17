#!/usr/bin/env python3
"""Nightlight helper: reports a device's health to Nightlight, and runs only the jobs you allow on this machine.

Every report carries: OS name, CPU architecture, CPU / memory / disk percentages, uptime, Docker containers (name,
image name and tag without any registry address or path, state, status text), the names of failed system services
(and, on a Mac, of your own failing background items), how many software updates are waiting, two yes/no safety
facts (administrator commands without a password; SSH password logins), what you allowed here, and up/down results
for things you chose to have it watch. It never sends its host name, IP or hardware addresses, files, environment
variables or passwords. To draw lines between your devices it sends keyed fingerprints of local network addresses
(its own, its router's, and those it backs up to or relies on), never the addresses themselves. Things it finds nearby
are sent as a guess of what they are and their maker and model (only a known brand, and a model that is a known Apple
model or looks like a product code), never their addresses; the names they announce ("Living Room") are sent only
while your account shows names (on by default, a switch in Settings). Log lines leave only for a container or
service you allowed with `allow logs NAME`, and are scrubbed here first. It talks only HTTPS to the address you joined with.

By default it changes nothing. You can allow, per target and on this machine only: restarting a stopped Docker
container, restarting a failed system service, and reading why something is down. Even then a change runs only
after you approve its card in the app; Nightlight sends a job name and target, never a command.

Usage:
  nightlight_helper.py enrol <API_URL> <CODE> [--name NAME]   # join with a one-time code from the app
  nightlight_helper.py pair <API_URL> [--web URL]              # or: show a code to approve in the app / by phone
  nightlight_helper.py pair <API_URL> --web URL --browser --install  # the Mac installer: approve in the browser
  nightlight_helper.py install | uninstall | status            # run in the background (systemd / launchd)
  nightlight_helper.py settings                                # app-managed or strict; strict: what's allowed
  nightlight_helper.py once                                    # send one report
  nightlight_helper.py run [--every SECONDS]                   # keep reporting (default every 60 s)
  nightlight_helper.py show                                    # print what would be sent, without sending
  nightlight_helper.py allow restart_container <NAME>          # allow restarting this container after approval
  nightlight_helper.py allow restart_service <UNIT>            # allow restarting this system service after approval
  nightlight_helper.py allow diagnose <NAME>                   # allow reading why a container/service is down
  nightlight_helper.py allow logs <NAME>                       # ...and its last log lines (scrubbed here first)
  nightlight_helper.py discover [--yes]                        # find things nearby; you pick what to send
  nightlight_helper.py disallow restart_container <NAME>       # take that back

Python 3.8+, standard library only; uses psutil when it is installed.
"""

import argparse
import http.client
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.9.25"
CONFIG_DIR = os.environ.get("NIGHTLIGHT_HOME", os.path.join(os.path.expanduser("~"), ".config", "nightlight"))
CONFIG = os.path.join(CONFIG_DIR, "helper.json")
JOB_TYPES = ("restart_container", "restart_service", "diagnose", "logs", "inspect", "fix", "update")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")  # container names
TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,99}$")  # containers or system services (units)
_POLL = {"every": 0}  # the server asks for quicker checks while the owner is chatting
ACTION_RE = re.compile(r"^act_[0-9a-f]{26}$")
STATES = ("created", "restarting", "running", "removing", "paused", "exited", "dead")  # Docker's own words


def _run_status(cmd, timeout=20):
    """(exit code, stdout) or (None, '') if it couldn't run or timed out."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return out.returncode, out.stdout
    except (OSError, subprocess.SubprocessError):
        return None, ""


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
        rows.append({"name": c.get("Names", "")[:64], "image": _image_name(c.get("Image", "")),
                     "state": c.get("State", "")[:32], "status": c.get("Status", "")[:64]})
    return rows


def _image_name(ref):
    """Only the image's own name and tag: no registry host, port, path or digest leaves the machine."""
    ref = ref.split("@", 1)[0]
    return ref.rsplit("/", 1)[-1][:128]


def _failed_units(timeout=20):
    if not shutil.which("systemctl"):
        return []
    out = _run(["systemctl", "--failed", "--plain", "--no-legend", "--no-pager"], timeout=timeout)
    return [line.split()[0][:128] for line in out.splitlines() if line.strip()][:50]


_SLOW = {}  # slow checks are re-run at most hourly


def _hourly(key, fn, every=3600):
    hit = _SLOW.get(key)
    if hit and time.time() - hit[0] < every:
        return hit[1]
    value = fn()
    _SLOW[key] = (time.time(), value)
    return value


def _count_updates():
    if shutil.which("apt"):
        out = _run(["apt", "list", "--upgradable"], timeout=60)
        return sum(1 for line in out.splitlines() if "upgradable from" in line)
    if shutil.which("dnf"):  # exit 100 = updates available, 0 = none; anything else = couldn't tell
        code, out = _run_status(["dnf", "-q", "check-update"], timeout=60)
        if code not in (0, 100):
            return None
        return sum(1 for line in out.splitlines() if len(line.split()) == 3 and "." in line.split()[0])
    if sys.platform == "darwin" and shutil.which("softwareupdate"):
        out = _run_both(["softwareupdate", "-l"], timeout=90)
        return sum(1 for line in out.splitlines() if line.strip().startswith("* Label:"))
    return None


def _updates_pending():
    return _hourly("updates", _count_updates)


def _failed_agents(timeout=20):
    """macOS: your own background items (not Apple's) whose last run failed."""
    if sys.platform != "darwin" or not shutil.which("launchctl"):
        return []
    out = []
    for line in _run(["launchctl", "list"], timeout=timeout).splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 3 and parts[1] not in ("0", "-") and not parts[2].startswith(("com.apple.", "application.")):
            out.append(parts[2][:100])
    return out[:20]


def _passwordless_sudo():
    """True if this account can become administrator without a password (sudo -k ignores a recent password)."""
    if not shutil.which("sudo") or os.geteuid() == 0:
        return None
    try:
        r = subprocess.run(["sudo", "-k", "-n", "true"], capture_output=True, timeout=5, check=False)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def _ssh_password_login():
    """True if the SSH server allows password logins (keys are safer). None if there's no SSH server config."""
    paths = ["/etc/ssh/sshd_config"]
    try:
        with open(paths[0]) as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    active = [ln.split() for ln in lines if ln.split() and not ln.split()[0].startswith("#")]
    if any(w[0].lower() in ("include", "match") for w in active):
        return None  # the effective setting depends on includes or conditions: don't guess
    for words in active:
        key = words[0].lower()
        if key == "passwordauthentication" and len(words) >= 2:
            return words[1].lower() == "yes"  # sshd uses the first value it finds
    return True if sys.platform != "darwin" else None  # Debian's default is yes


def facts():
    cpu, mem, up = _cpu_mem_uptime()
    out = {"helperVersion": VERSION, "os": _os_name(), "arch": platform.machine()[:16], "cpuPct": cpu,
           "memPct": mem, "diskPct": _disk(), "uptimeSec": up, "containers": _containers(),
           "failedUnits": _failed_units(), "updatesPending": _updates_pending(), "allowedJobs": _allowed(),
           "watchResults": _watch_results(), "failedAgents": _failed_agents(),
           "manage": _manage(),
           "macFolders": _mac_folders_state(),
           "safety": {"passwordlessSudo": _hourly("sudo", _passwordless_sudo),
                      "sshPasswordLogin": _ssh_password_login()}}
    net = _net()
    if net:
        out["net"] = net
    return out


def _mac_folders_state():
    """On a Mac: whether the private folders may be measured ("allowed"), were declined here ("declined"), or were
    never asked (None). Elsewhere None. macOS's own answer per folder stays with macOS."""
    if sys.platform != "darwin":
        return None
    try:
        v = _load().get("macPrivateFolders")
    except (OSError, ValueError):
        return None
    return "allowed" if v is True else "declined" if v is False else None


def _allowed():
    """What this device lets Nightlight do. In app-managed mode (chosen on this device) the owner's switches from the
    app apply; in strict mode only what was allowed here. Either way each action is still checked here before it runs."""
    try:
        cfg = _load()
    except (OSError, ValueError):
        return {}
    if cfg.get("manage") == "app":
        return _from_remote(cfg.get("remote") or {})
    allow = cfg.get("allow") or {}
    out = {k: [n for n in v if _name_re(k).fullmatch(n)][:20] for k, v in allow.items()
           if k in JOB_TYPES and k not in ("inspect", "fix", "update") and v}
    if "all" in (allow.get("inspect") or []):
        out["inspect"] = sorted(INSPECT)
    if "all" in (allow.get("fix") or []) and _available_fixes():
        out["fix"] = _available_fixes()
    if "all" in (allow.get("update") or []):
        out["update"] = ["signed"]
    if (cfg.get("expert") or {}).get("pem"):
        out["expert"] = ["on"]
    return out


def _from_remote(remote):
    """The app's switches, as an allowlist. Only well-formed names; "check why" covers what this device reports now."""
    containers = {c["name"] for c in _containers() if NAME_RE.fullmatch(c.get("name", ""))}
    units = {u for u in _failed_units() if TARGET_RE.fullmatch(u)}
    here = {"logs": containers | units, "restart_container": containers, "restart_service": units}
    out = {}
    for key in ("logs", "restart_container", "restart_service"):
        names = remote.get(key) if isinstance(remote.get(key), list) else []
        # only things this device itself reports right now: a compromised server can't name anything else
        names = [n for n in names if isinstance(n, str) and n in here[key]][:20]
        if names:
            out[key] = names
    if remote.get("diagnose") is True and (containers or units):
        out["diagnose"] = sorted(containers | units)[:20]
    if remote.get("diagnose") is True:
        out["inspect"] = sorted(INSPECT)
    if remote.get("cleanup") is True and _available_fixes():
        out["fix"] = _available_fixes()
    if remote.get("updates", True) is not False:
        out["update"] = ["signed"]
    try:
        if (_load().get("expert") or {}).get("pem"):
            out["expert"] = ["on"]  # pinned at the device: the app can't switch this on
    except (OSError, ValueError):
        pass
    return out


def _name_re(kind):
    return NAME_RE if kind == "restart_container" else TARGET_RE


def _unit_failed(unit):
    """True only when systemd positively says the unit has failed (not merely stopped on purpose)."""
    code, out = _run_status(["systemctl", "is-failed", unit])
    return code == 0 and out.strip() == "failed"


def _unit_active(unit):
    code, out = _run_status(["systemctl", "is-active", unit])
    return out.strip() or "unknown"


def _restart_unit(unit, wait):
    """Restart one system service the owner allowed here; needs sudo without a password for it (or root)."""
    if unit not in _allowed().get("restart_service", []):
        return False, "Restarting this service isn't allowed on this device, so nothing was done.", None
    if not shutil.which("systemctl"):
        return False, "This device has no systemd, so nothing was done.", None
    if _unit_active(unit) == "active":
        return True, f"{unit} was already running; nothing needed doing.", "running"
    if not _unit_failed(unit):
        return False, f"{unit} isn't in a failed state (it may be stopped on purpose), so nothing was done.", None
    cmd = ["systemctl", "restart", unit] if os.geteuid() == 0 else ["sudo", "-n", "systemctl", "restart", unit]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return False, f"Couldn't run the restart for {unit}.", None
    if r.returncode != 0 and "password" in (r.stderr or "").lower():
        return False, ("This device needs a password to restart services, so nothing was done. "
                       "See 'Allow restarting a service' in the Nightlight README."), None
    time.sleep(wait)
    state = _unit_active(unit)
    if state == "active":
        return True, f"Restarted {unit}; it was still running {wait} seconds later.", "running"
    return False, f"Tried to restart {unit}, but it is {state}.", "exited"


def set_allowed(kind, name, on):
    if kind not in JOB_TYPES:
        sys.exit("Unknown job type. Allowed: " + ", ".join(JOB_TYPES))
    if kind in ("inspect", "fix", "update") and name != "all":
        sys.exit(f"Use: allow {kind} all")
    if not _name_re(kind).fullmatch(name):
        sys.exit("That isn't a valid name.")
    def change(cfg):
        names = set((cfg.get("allow") or {}).get(kind, []))
        names = names | {name} if on else names - {name}
        cfg["allow"] = {**(cfg.get("allow") or {}), kind: sorted(names)}
    _update_config(change)
    print(("Allowed" if on else "No longer allowed") + f": {kind} {name}")
    report_now()


def _container_state(name):
    out = _run(["docker", "inspect", "--format", "{{.State.Status}}", name]).strip()
    return out[:32] or None


# ------------------------------------------------------------------ read-only looks (diagnose)
# Scrubbed here, before anything leaves the device (the server scrubs again). Best effort: logs can contain things no
# pattern recognises, which is why sending log lines needs its own `allow logs NAME`.
_CONTROLS = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|[\x00-\x08\x0b-\x1f\x7f]")
_SECRET_WORD = r"[A-Za-z0-9_.-]*(?:pass(?:word)?|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|auth|credential)[A-Za-z0-9_.-]*"
_SCRUB = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[hidden]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [hidden]"),
    # KEY=value, KEY: value, "key": "value", 'key'='value', DB_PASSWORD=..., --password value
    (re.compile(r"(?i)([\"']?" + _SECRET_WORD + r"[\"']?\s*[=:]\s*)(\"(?:[^\"\\]|\\.)*\"?|'(?:[^'\\]|\\.)*'?|[^\s,;}&]+)"),
     r"\1[hidden]"),  # quoted values end at an unescaped quote (or the end of the line)
    (re.compile(r"(?i)(--?" + _SECRET_WORD + r"[ =])(\S+)"), r"\1[hidden]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[hidden]"),
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b|\bAIza[0-9A-Za-z_-]{35}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "[hidden]"),
    (re.compile(r"([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1[hidden]@"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
    (re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b"), "[mac]"),
    (re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b"), "[ip]"),
    (re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){1,7}:(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4})*)?(?![\w:])"), "[ip]"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b|\b[A-Za-z0-9+/_-]{40,}={0,2}"), "[hidden]"),
    (re.compile(r"/(home|Users)/[^/\s]+"), r"/\1/[user]"),
]


def scrub(text):
    """Returns (clean text, how many things were hidden)."""
    hidden = 0
    text = _CONTROLS.sub("", text)  # first: colour codes could otherwise split a keyword from its value
    for pattern, repl in _SCRUB:
        text, n = pattern.subn(repl, text)
        if repl and "hidden" in repl:
            hidden += n
    return text, hidden


def _tail(text, lines=30, width=200, limit=3000):
    """The newest lines, each cut to `width`, the whole kept under `limit` bytes (cutting from the top)."""
    out = [ln[:width] for ln in text.splitlines()[-lines:]]
    while out and len("\n".join(out).encode()) > limit:
        out.pop(0)
    return "\n".join(out)


def _run_both(cmd, timeout=15, cap=256 * 1024):
    """stdout and stderr together, whatever the exit code ('' if it couldn't run). Reads at most `cap` bytes (the
    newest part is kept by the caller), then stops the command, so a huge log can't fill the helper's memory."""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError:
        return ""
    import select
    chunks, size, deadline = [], 0, time.time() + timeout
    fd = p.stdout.fileno()
    try:
        while size < cap:
            left = deadline - time.time()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                break  # silent or stalled for too long
            block = os.read(fd, 65536)
            if not block:
                break
            chunks.append(block)
            size += len(block)
    finally:
        if p.poll() is None:
            p.kill()
        p.stdout.close()
        p.wait()
    return b"".join(chunks)[:cap].decode("utf-8", "replace")


EXIT_MEANING = {0: "finished normally", 1: "stopped with an error", 137: "was stopped forcibly (often out of memory, "
                "or someone stopped it)", 143: "was asked to stop", 139: "crashed", 126: "couldn't start its program",
                127: "couldn't find its program"}


def _look_container(name, logs):
    raw = _run(["docker", "inspect", "--format", "{{json .State}} {{.RestartCount}}", name]).strip()
    try:
        state_json, restarts = raw.rsplit(" ", 1)
        st = json.loads(state_json)
    except ValueError:
        return None
    code = st.get("ExitCode")
    status = st.get("Status", "unknown")
    meaning = EXIT_MEANING.get(code, f"exited with code {code}") if status != "running" else "is running"
    lines = [f"status: {status}", f"exit code: {code} ({meaning})", f"out of memory: {'yes' if st.get('OOMKilled') else 'no'}",
             f"restarts: {restarts}", f"started: {st.get('StartedAt', '')[:19]}", f"stopped: {st.get('FinishedAt', '')[:19]}"]
    if st.get("Error"):
        lines.append(f"error: {st['Error'][:200]}")
    summary = f"{name} {meaning}" + (", out of memory" if st.get("OOMKilled") else "")
    if logs:
        lines += ["last log lines:", _tail(scrub(_run_both(["docker", "logs", "--tail", "30", "--timestamps", name]))[0])]
    return summary, "\n".join(lines)


def _look_unit(name, logs):
    unit = name if "." in name else name + ".service"
    props = _run(["systemctl", "show", unit, "-p", "ActiveState,SubState,Result,ExecMainStatus,NRestarts,"
                  "StateChangeTimestamp", "--no-pager"])
    info = dict(line.split("=", 1) for line in props.splitlines() if "=" in line)
    if not info.get("ActiveState"):
        return None
    summary = f"{unit} is {info.get('ActiveState')} ({info.get('Result', '')}, exit status {info.get('ExecMainStatus')})"
    lines = [f"{k}: {v}" for k, v in info.items()]
    if logs:
        lines += ["last log lines:", _tail(scrub(_run_both(["journalctl", "-u", unit, "-n", "30", "--no-pager",
                                                            "-o", "short-iso"]))[0])]
    return summary, "\n".join(lines)


def look_into(target):
    """Read-only: why is this container or service down? Only for targets the owner allowed here."""
    allowed = _allowed()
    if target not in allowed.get("diagnose", []):
        return False, "Looking into this isn't allowed on this device, so nothing was read.", None
    logs = target in allowed.get("logs", [])
    found = None
    if shutil.which("docker") and NAME_RE.fullmatch(target):
        found = _look_container(target, logs)
    if found is None and shutil.which("systemctl"):
        found = _look_unit(target, logs)
    if found is None:
        return False, f"Couldn't find a container or service named {target} here.", None
    summary, detail = found
    text, hidden = scrub(detail)
    return True, scrub(summary)[0][:200], _tail(text, lines=60, limit=3500) + (
        f"\n({hidden} private values hidden)" if hidden else "")


# ------------------------------------------------------------------ inspect: read-only checks, like an expert would run
# A fixed catalogue. The server can only ask for these names; each is a fixed command list with a timeout; output is
# scrubbed here. Allowed whenever "check why something stopped" is on (app-managed) or `allow inspect all` (strict).

_HOME = os.path.expanduser("~")
INSPECT_BUDGET = 80  # seconds for a whole inspect job, so the helper's report loop is never held up for long
_inspect_until = [0.0]


def _left(cap):
    """Seconds a step may take: at most `cap`, never past the job's budget (0 when it's used up)."""
    return max(0.0, min(cap, _inspect_until[0] - time.time()))


def _guarded(path):
    """True when `path` (as written: no link is followed when it is opened) is inside a folder macOS protects and the
    owner hasn't allowed those at the Mac."""
    if sys.platform != "darwin" or _mac_private_ok():
        return False
    a = os.path.abspath(path)
    return any(a == g or a.startswith(g + os.sep) for g in (os.path.abspath(x) for _l, x in _mac_private_places()))


def _pin(path):
    """A descriptor for `path`, opened from / one component at a time without following any link, or None. What is
    measured or listed afterwards is this exact folder, even if a name is swapped for a link a moment later."""
    a = os.path.abspath(path)
    try:
        fd = os.open("/", _DIR_FLAGS)
    except OSError:
        return None
    try:
        for part in [x for x in a.split(os.sep) if x]:
            nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except OSError:
        os.close(fd)
        return None


def _plain_path(path):
    """True when `path` can be pinned (no link anywhere on the way) and isn't in a protected folder."""
    if _guarded(path):
        return False
    fd = _pin(path)
    if fd is None:
        return False
    os.close(fd)
    return True


def _listdir(path):
    """Names in a pinned, unprotected folder ([] otherwise)."""
    if _guarded(path):
        return []
    fd = _pin(path)
    if fd is None:
        return []
    try:
        return sorted(os.listdir(fd))
    except OSError:
        return []
    finally:
        os.close(fd)


def _du(path):
    """Size of a folder in MB (or None): `du` runs inside the pinned folder (measuring "."), never following links."""
    if _guarded(path) or _left(25) < 1:
        return None
    fd = _pin(path)
    if fd is None:
        return None
    try:  # du exits non-zero when a few files can't be read; the total it prints is still right for what it could read
        out = subprocess.run(["du", "-sk", "-x", "."], capture_output=True, text=True, timeout=_left(25), check=False,
                             pass_fds=(fd,), preexec_fn=lambda: os.fchdir(fd)).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        os.close(fd)
    first = out.split()[:1]
    return round(int(first[0]) / 1024) if first and first[0].isdigit() else None


def _mac_private_places():
    """Folders macOS guards with a privacy prompt ("python would like to access..."). Reading them from the background
    would pop a dialog on a Mac nobody may be watching, and wait for it, so they are read only after the owner said
    yes at the Mac (`nightlight settings`)."""
    h = _HOME
    return [("Downloads", f"{h}/Downloads"), ("Desktop", f"{h}/Desktop"), ("Documents", f"{h}/Documents"),
            ("Movies", f"{h}/Movies"), ("Trash", f"{h}/.Trash"),
            ("iPhone backups", f"{h}/Library/Application Support/MobileSync/Backup"),
            ("Docker Desktop", f"{h}/Library/Containers/com.docker.docker")]


def _mac_private_ok():
    try:
        return _load().get("macPrivateFolders") is True
    except (OSError, ValueError):
        return False


def _disk_places():
    h = _HOME
    if sys.platform == "darwin":
        places = [("App caches", f"{h}/Library/Caches"),
                  ("Xcode build data", f"{h}/Library/Developer/Xcode/DerivedData"),
                  ("Homebrew cache", f"{h}/Library/Caches/Homebrew"), ("npm cache", f"{h}/.npm")]
        if _mac_private_ok():
            places = _mac_private_places() + places
    else:
        places = [("System logs", "/var/log"), ("Package cache (apt)", "/var/cache/apt"), ("User caches", f"{h}/.cache"),
                  ("Downloads", f"{h}/Downloads"), ("Temporary files", "/tmp"), ("npm cache", f"{h}/.npm")]
    return places


def _inspect_disk():
    rows = []
    for label, path in _disk_places():
        mb = _du(path)
        if mb is not None and mb >= 50:
            rows.append((mb, label))
    rows.sort(reverse=True)
    lines = [f"{label}: {mb / 1024:.1f} GB" if mb >= 1024 else f"{label}: {mb} MB" for mb, label in rows[:12]]
    if shutil.which("journalctl") and _left(10) >= 1:
        j = _run(["journalctl", "--disk-usage"], timeout=_left(10)).strip()
        if j:
            lines.append("System journal: " + j.split("take up", 1)[-1].split("in the file system")[0].strip())
    if sys.platform == "darwin" and not _mac_private_ok():
        lines.append("Not checked (macOS privacy): Downloads, Desktop, Documents, Movies, Trash. Allow once at the Mac "
                     "with `nightlight settings`.")
    return "Biggest known places (sizes):\n" + ("\n".join(lines) or "nothing large in the usual places")


def _inspect_processes():
    out = _run(["ps", "-Ao", "pcpu,pmem,comm"], timeout=_left(10)).splitlines()[1:]
    rows = []
    for line in out:
        parts = line.split(None, 2)
        if len(parts) == 3:
            try:
                rows.append((float(parts[1]), float(parts[0]), os.path.basename(parts[2])[:40]))
            except ValueError:
                pass
    rows.sort(reverse=True)
    return "Top programs by memory (memory %, CPU %, program):\n" + "\n".join(
        f"{m:.1f}% mem, {c:.1f}% cpu, {name}" for m, c, name in rows[:10])


def _inspect_updates():
    if shutil.which("apt"):
        names = [ln.split("/")[0] for ln in _run(["apt", "list", "--upgradable"], timeout=_left(60)).splitlines()
                 if "upgradable from" in ln]
        return f"{len(names)} package updates waiting: " + ", ".join(names[:25])
    if sys.platform == "darwin" and shutil.which("softwareupdate"):
        out = _run_both(["softwareupdate", "-l"], timeout=_left(60))
        labels = [ln.split("Label:", 1)[1].strip() for ln in out.splitlines() if "Label:" in ln]
        brew = _run(["brew", "outdated", "--quiet"], timeout=_left(30)).split() \
            if shutil.which("brew") and _left(30) >= 1 else []
        return (f"macOS updates: {', '.join(labels) or 'none'}\nHomebrew outdated ({len(brew)}): "
                + ", ".join(brew[:25]))
    return "No update tool found on this device."


def _inspect_docker():
    if not shutil.which("docker"):
        return "Docker isn't installed here."
    out = _run(["docker", "system", "df"], timeout=_left(30)).strip()
    return "Docker disk use:\n" + out if out else "Docker is installed but not running (or not reachable)."


def _inspect_network():
    import socket as _s
    import threading
    found = []

    def look():  # getaddrinfo has no timeout of its own: run it aside and stop waiting after a few seconds
        try:
            found.extend(_s.getaddrinfo("www.google.com", 443, type=_s.SOCK_STREAM))
        except OSError:
            pass

    t = time.time()
    worker = threading.Thread(target=look, daemon=True)
    worker.start()
    worker.join(_left(4))
    if not found:
        return "Name lookup (DNS): " + ("FAILED" if not worker.is_alive() else "no answer within 4 seconds") + \
            "\nInternet (HTTPS): not tried (no address)"
    lines = [f"Name lookup (DNS): ok in {int((time.time() - t) * 1000)} ms"]
    family, kind, proto, _, addr = found[0]
    t = time.time()
    try:  # connect to the address just found, so no second (unbounded) lookup happens
        with _s.socket(family, kind, proto) as sock:
            sock.settimeout(max(0.5, _left(4)))
            sock.connect(addr)
        lines.append(f"Internet (HTTPS): reachable in {int((time.time() - t) * 1000)} ms")
    except OSError:
        lines.append("Internet (HTTPS): NOT reachable")
    return "\n".join(lines)


def _inspect_load():
    try:
        one, five, fifteen = os.getloadavg()
    except OSError:
        return "Load: unknown"
    return f"Load average (1/5/15 min): {one:.2f} / {five:.2f} / {fifteen:.2f} on {os.cpu_count()} CPU cores"


def _inspect_failed():
    units = _failed_units(timeout=_left(10))
    agents = _failed_agents(timeout=_left(10))
    return ("Failed system services: " + (", ".join(units) or "none") +
            ("\nFailing background items: " + ", ".join(agents) if agents else ""))


# Folders macOS guards (reading them pops a privacy dialog) or that belong to Apple's own data: never measured from
# the background. Everything else in the home folder and its Library is fair game for "where did the space go".
_MAC_GUARDED_TOP = {"Desktop", "Documents", "Downloads", "Movies", "Music", "Pictures", "Library", ".Trash", "Public",
                    "Applications"}
_MAC_GUARDED_LIB = {"Mail", "Messages", "Safari", "Containers", "Group Containers", "Cookies", "HomeKit", "Calendars",
                    "Reminders", "Metadata", "Accounts", "Suggestions", "Biome", "IdentityServices", "Sharing",
                    "Autosave Information", "PersonalizationPortrait", "Daemon Containers", "Application Scripts",
                    "Shortcuts", "Trial", "DuetExpertCenter", "CallServices", "Assistant", "Photos", "Weather", "News",
                    "Stocks", "Passes", "Keychains", "Safari", "SafariSafeBrowsing", "Mobile Documents", "CloudStorage",
                    "Application Support", "Preferences", "StatusKit", "Contacts", "FaceTime", "Intelligence"}


def _one_line(name, limit=60):
    """A short single-line label: scrubbed first (as a whole), then every control character and every line separator
    Python knows (also U+0085, U+2028, U+2029) becomes "?", so nothing in a name can start a line of its own."""
    clean = scrub(name)[0]
    return re.sub(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]", "?", clean)[:limit]


def _inspect_home():
    """The biggest folders directly in the home folder and in ~/Library (sizes only), skipping protected ones."""
    h, rows = _HOME, []
    places = []
    top = _listdir(h)
    guarded_top = _MAC_GUARDED_TOP if sys.platform == "darwin" else set()
    places += [(f"~/{_one_line(n)}", os.path.join(h, n)) for n in top if n not in guarded_top]
    if sys.platform == "darwin":
        lib = _listdir(os.path.join(h, "Library"))
        places += [(f"~/Library/{_one_line(n)}", os.path.join(h, "Library", n)) for n in lib
                   if n not in _MAC_GUARDED_LIB]
    for label, path in places:
        if _left(25) < 1:
            break
        mb = _du(path)
        if mb is not None and mb >= 100:
            rows.append((mb, label))
    rows.sort(reverse=True)
    if not rows:
        return "Biggest folders in the home folder: nothing over 100 MB outside protected folders"
    fmt = lambda mb: f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb} MB"
    lines = [f"Biggest folder: {rows[0][1]}: {fmt(rows[0][0])}"] + [f"{label}: {fmt(mb)}" for mb, label in rows[1:10]]
    return "Biggest folders in the home folder (sizes; protected folders not checked):\n" + "\n".join(lines)


def _restart_lines():
    """(last start, the event just before it) from `last` (newest first): each a (kind, datetime), or None."""
    from datetime import datetime
    cmds = [["last", "reboot"], ["last", "shutdown"]] if sys.platform == "darwin" else \
        [["last", "-x", "reboot", "shutdown"]]
    lines_seen = set()
    events = []
    for line in (ln for c in cmds for ln in _run(c, timeout=_left(10)).splitlines()):
        if line in lines_seen:
            continue
        lines_seen.add(line)
        kind = "reboot" if line.startswith("reboot") else "shutdown" if line.startswith("shutdown") else None
        m = re.search(r"([A-Z][a-z]{2} [A-Z][a-z]{2} +\d+ \d\d:\d\d)", line)
        if not kind or not m:
            continue
        try:
            when = datetime.strptime(" ".join(m.group(1).split()), "%a %b %d %H:%M").replace(year=datetime.now().year)
        except ValueError:
            continue
        events.append((kind, when if when <= datetime.now() else when.replace(year=when.year - 1)))
    events.sort(key=lambda e: e[1], reverse=True)  # newest first, both kinds together
    i = next((n for n, e in enumerate(events) if e[0] == "reboot"), None)
    if i is None:
        return None, None
    before = events[i + 1] if i + 1 < len(events) else None
    if before and before[0] == "reboot" and not any(k == "shutdown" for k, _ in events):
        before = None  # shutdowns aren't recorded here at all: a missing one proves nothing
    return events[i][1], before


def _inspect_restarts():
    """How the device last started, whether that was after a clean shutdown, and crash reports by date (names and
    times only: their contents are never read)."""
    lines = []
    up = facts_uptime()
    if up is not None:
        lines.append(f"Running for: {up // 3600} hours {up % 3600 // 60} minutes")
    boot, before = _restart_lines()
    if boot:
        lines.append(f"Last start: {boot:%Y-%m-%d %H:%M}")
        if before is None:
            lines.append("How it stopped before that: unknown (no earlier record)")
        elif before[0] == "shutdown":
            lines.append(f"Shutdown before it: {before[1]:%Y-%m-%d %H:%M}")
            lines.append("The last start was clean")
        else:  # the record before this start is another start: no shutdown was recorded in between
            lines.append(f"Previous start: {before[1]:%Y-%m-%d %H:%M}, with no shutdown recorded after it")
            lines.append("The last start was NOT clean (no shutdown recorded since the previous start: a crash, "
                         "freeze or power cut)")
    reports = []
    for d in ("/Library/Logs/DiagnosticReports", os.path.expanduser("~/Library/Logs/DiagnosticReports")):
        try:
            names = os.listdir(d) if sys.platform == "darwin" else []
        except OSError:
            names = []
        for n in names:
            low = n.lower()
            if low.startswith(("panic", "resetcounter")) or "watchdog" in low:
                try:
                    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.lstat(os.path.join(d, n)).st_mtime))
                except OSError:
                    continue
                kind = ("kernel panic" if low.startswith("panic") else "watchdog" if "watchdog" in low else "reset") \
                    + ", report written"
                reports.append((when, kind))
    if shutil.which("journalctl"):
        boots = _run(["journalctl", "--list-boots", "--no-pager", "-q"], timeout=_left(10)).strip().splitlines()
        if boots:
            lines.append(f"Boots recorded: {len(boots)}")
    recent = sorted(set(reports), reverse=True)[:5]
    if recent:
        lines.append("Crash reports: " + ", ".join(f"{w} ({k})" for w, k in recent))
    return "How it last started:\n" + ("\n".join(lines) or "unknown")


def facts_uptime():
    try:
        if sys.platform == "darwin":
            m = re.search(r"sec = (\d+)", _run(["sysctl", "-n", "kern.boottime"], timeout=5))
            return int(time.time()) - int(m.group(1)) if m else None
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except (OSError, ValueError):
        return None


INSPECT = {"restarts": _inspect_restarts, "home": _inspect_home, "disk": _inspect_disk, "processes": _inspect_processes, "updates": _inspect_updates,
           "docker": _inspect_docker, "network": _inspect_network, "load": _inspect_load, "failed": _inspect_failed}


def inspect_allowed():
    return bool(_allowed().get("inspect"))


def run_inspect(names):
    if not inspect_allowed():
        return False, "Looking around isn't allowed on this device, so nothing was read.", None
    names = list(dict.fromkeys(n for n in names if isinstance(n, str) and n in INSPECT))[:4] if isinstance(names, list) else []
    if not names:
        return False, "Nothing this helper knows how to check was asked for.", None
    _inspect_until[0] = time.time() + INSPECT_BUDGET
    parts = []
    for n in names:
        if _left(INSPECT_BUDGET) <= 0:
            parts.append(f"{n}: skipped (out of time)")
            continue
        try:
            parts.append(INSPECT[n]())
        except Exception as e:  # one failing check never hides the others
            parts.append(f"{n}: couldn't check ({type(e).__name__})")
    text, hidden = scrub("\n\n".join(parts).replace(_HOME, "~"))
    return True, f"Checked: {', '.join(names)}", _tail(text, lines=80, limit=3500) + (
        f"\n({hidden} private values hidden)" if hidden else "")


# ------------------------------------------------------------------ fix: safe clean-ups, each after the owner approves
# A fixed catalogue like inspect. Each removes only things that are rebuilt or re-downloaded on their own (or, for the
# Trash, what the owner already threw away). Allowed by strict `allow fix all` or the app's "clean up space" switch.

def _as_root(cmd):
    return cmd if os.geteuid() == 0 else ["sudo", "-n", *cmd]


_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _why(err, where):
    """Plain words for why a folder couldn't be used."""
    import errno
    code = getattr(err, "errno", None)
    real = os.path.join(_HOME, where[2:]) if where.startswith("~/") else where
    if code == errno.ELOOP or (code == errno.ENOTDIR and os.path.islink(real)):
        return f"{where} is a link to another place, and Nightlight never follows links when deleting"
    if code == errno.ENOENT:
        return f"{where} doesn't exist"
    if code == errno.EPERM and sys.platform == "darwin":
        return f"macOS privacy protection blocked {where} (allow it once at the Mac with `nightlight settings`)"
    if code in (errno.EACCES, errno.EPERM):
        return f"no permission for {where}"
    return f"{where}: {getattr(err, 'strerror', None) or type(err).__name__}"


def _open_under_home(parts):
    """(descriptor, None) for ~/parts[0]/parts[1]/..., opened one step at a time without following any link, so a
    swapped-in link can't send the clean-up somewhere else; (None, why) when a step is missing, a link or blocked."""
    fd = os.open(_HOME, _DIR_FLAGS)
    walked = "~"
    try:
        for part in parts:
            walked += "/" + part
            nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd, None
    except OSError as e:
        os.close(fd)
        return None, _why(e, walked)


def _clear_fd(fd, errors, where):
    """Delete everything inside the open folder `fd`, through descriptors only. Appends (path, error) per failure."""
    with os.scandir(fd) as it:
        entries = list(it)
    for entry in entries:
        path = f"{where}/{entry.name}"
        try:
            if entry.is_dir(follow_symlinks=False):
                sub = os.open(entry.name, _DIR_FLAGS, dir_fd=fd)
                try:
                    _clear_fd(sub, errors, path)
                finally:
                    os.close(sub)
                os.rmdir(entry.name, dir_fd=fd)
            else:
                os.unlink(entry.name, dir_fd=fd)  # a link is removed itself, never what it points to
        except OSError as e:
            errors.append((path, e))


def _empty_dir(parts):
    """Empty ~/parts... (never the folder itself). (True, "") when everything went; (False, why) otherwise."""
    fd, why = _open_under_home(parts)
    if fd is None:
        return False, why
    errors = []
    try:
        try:
            _clear_fd(fd, errors, "~/" + "/".join(parts))
        except OSError as e:  # the folder itself couldn't be listed
            return False, _why(e, "~/" + "/".join(parts))
    finally:
        os.close(fd)
    if not errors:
        return True, ""
    path, err = errors[0]
    more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
    return False, f"{len(errors)} item(s) couldn't be removed; first: {_why(err, path)}{more}"


def _fix_cmd(cmd, timeout=300):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return False, "it couldn't run"
    if r.returncode != 0 and "password" in (r.stderr or "").lower():
        return False, "this device needs a password for it (sudo)"
    full = scrub(r.stderr or r.stdout or "")[0]  # scrub the whole text first, then pick the last line
    said = _one_line((full.strip().splitlines() or [""])[-1], 140)
    return r.returncode == 0, "" if r.returncode == 0 else f"it reported an error: {said or 'no details'}"


FIXES = {
    "empty_trash": {"when": lambda: sys.platform == "darwin" and _mac_private_ok(),
                    "run": lambda: _empty_dir([".Trash"])},
    "brew_cleanup": {"when": lambda: bool(shutil.which("brew")), "run": lambda: _fix_cmd(["brew", "cleanup", "-s"])},
    "npm_cache": {"when": lambda: bool(shutil.which("npm")),
                  "run": lambda: _fix_cmd(["npm", "cache", "clean", "--force"])},
    "xcode_build_data": {"when": lambda: os.path.isdir(f"{_HOME}/Library/Developer/Xcode/DerivedData")
                         and _plain_path(f"{_HOME}/Library/Developer/Xcode/DerivedData"),
                         "run": lambda: _empty_dir(["Library", "Developer", "Xcode", "DerivedData"])},
    "docker_prune": {"when": lambda: bool(shutil.which("docker")),
                     "run": lambda: _fix_cmd(["docker", "image", "prune", "-f"])},
    "apt_clean": {"when": lambda: bool(shutil.which("apt-get")), "run": lambda: _fix_cmd(_as_root(["apt-get", "clean"]))},
    "journal_vacuum": {"when": lambda: bool(shutil.which("journalctl")),
                       "run": lambda: _fix_cmd(_as_root(["journalctl", "--vacuum-size=200M"]))},
}


def _available_fixes():
    out = []
    for name, f in FIXES.items():
        try:
            if f["when"]():
                out.append(name)
        except Exception:
            pass
    return sorted(out)


def _free_gb():
    try:
        return shutil.disk_usage(_HOME if sys.platform == "darwin" else "/").free / 1024 ** 3
    except OSError:
        return None


def run_fix(name):
    if not isinstance(name, str) or name not in FIXES or name not in _allowed().get("fix", []):
        return False, "This clean-up isn't allowed on this device, so nothing was done.", None
    before = _free_gb()
    try:
        ok, why = FIXES[name]["run"]()
    except Exception as e:
        ok, why = False, f"it hit an error ({type(e).__name__})"
    after = _free_gb()
    freed = f" Freed {max(0.0, after - before):.1f} GB; {after:.1f} GB free now." if None not in (before, after) else ""
    text = (f"Done.{freed}" if ok else f"It didn't work: {_one_line(str(why), 300)}.{freed}").strip()
    return ok, scrub(text)[0], None  # scrubbed again at the boundary


# ------------------------------------------------------------------ update: signed new versions, from the app
# The server can only offer a file; it is installed only if it is signed with Nightlight's release key (kept offline,
# never in the cloud), is newer than this one and passes a self-test. A hacked server can't make this run its code.

RELEASE_KEY = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEHq9FhsTSpuLBzuLSKtoGUdlJWmkr
2m7CnjJbck5mPP0BZNU1eZjNWa5aFDZJGv3mnZKXHrLTxwIwrsumm7hmGw==
-----END PUBLIC KEY-----
"""
MAX_HELPER_BYTES = 1024 * 1024
_RESTART = []  # set after a successful update: the loop restarts itself in place once the result is reported


def _ver(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return ()


def update_allowed():
    try:
        cfg = _load()
    except (OSError, ValueError):
        return False
    if cfg.get("manage") == "app":
        return (cfg.get("remote") or {}).get("updates", True) is not False
    return "all" in ((cfg.get("allow") or {}).get("update") or [])


def _get(url, limit):
    """GET bytes (at most `limit`), no redirects. None on any failure."""
    try:
        with _OPENER.open(urllib.request.Request(url, method="GET"), timeout=30) as r:
            if r.status != 200:
                return None
            data = r.read(limit + 1)
            return data if len(data) <= limit else None
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError):
        return None


def _signed(data, sig):
    """True only if `sig` is a valid release-key signature over `data` (checked by the system's openssl)."""
    tool = shutil.which("openssl")
    if not tool:
        return False
    with tempfile.TemporaryDirectory(dir=_own_dir(APP_DIR)) as d:
        paths = {}
        for name, content in (("f", data), ("s", sig), ("k", RELEASE_KEY.encode())):
            paths[name] = os.path.join(d, name)
            with open(paths[name], "wb") as f:
                f.write(content)
        try:
            r = subprocess.run([tool, "dgst", "-sha256", "-verify", paths["k"], "-signature", paths["s"], paths["f"]],
                               capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return r.returncode == 0 and "Verified OK" in r.stdout


def _file_version(path):
    try:
        with open(path, "rb") as f:
            m = re.search(rb'^VERSION = "([0-9.]+)"$', f.read(), re.M)
        return m.group(1).decode() if m else None
    except OSError:
        return None


def self_update(version, api=None, auto=False):
    """Install release `version` of the helper. Returns (ok, summary, None). One install at a time (a lock), never
    older than what is installed, never twice before the restart; an automatic one never re-installs a version the
    owner rolled back from."""
    if _RESTART:
        return False, "An update is already installed and waiting for the restart.", None
    if not update_allowed():
        return False, "Updating from the app isn't allowed on this device (run `nightlight settings`).", None
    target = os.path.join(APP_DIR, "nightlight_helper.py")
    if os.path.realpath(sys.argv[0]) != os.path.realpath(target) or os.path.islink(target):
        return False, "This copy isn't the installed helper, so it wasn't replaced. Run install once.", None
    lock = _update_lock(wait=False)
    if lock is None:
        return False, "Another update is running right now; nothing changed.", None
    try:
        return _install(version, api, auto, target)
    finally:
        lock.close()  # releases the lock


def _update_lock(wait):
    """The one lock for changing the installed helper (updates and rollback). None if busy and not waiting."""
    import fcntl
    lock = open(os.path.join(_own_dir(APP_DIR), ".update.lock"), "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
    except OSError:
        lock.close()
        return None
    return lock


def _install(version, api, auto, target):
    cfg = _load()
    installed = _file_version(target) or "0"
    if _ver(version) and _ver(version) in (_ver(VERSION), _ver(installed)):
        return True, f"Already on {version}; nothing to do.", None  # the asked-for state is already reached
    floor = max(_ver(VERSION), _ver(installed))
    if not _ver(version) or _ver(version) <= floor:
        return False, f"{version} is older than what is installed, so nothing changed.", None
    if auto and (cfg.get("autoPaused") or version in (cfg.get("skipVersions") or [])):
        return False, f"Automatic updates are paused after a rollback; tap Update in the app to install {version}.", None
    base = check_api(api or _load()["api"]) + "/helper/release/"
    data, sig = _get(base + "nightlight_helper.py", MAX_HELPER_BYTES), _get(base + "nightlight_helper.py.sig", 4096)
    if not data or not sig:
        return False, "Couldn't download the update; nothing changed.", None
    if not _signed(data, sig):
        return False, "The update's signature didn't check out, so it was NOT installed.", None
    m = re.search(rb'^VERSION = "([0-9.]+)"$', data, re.M)
    if not m or m.group(1).decode() != version:
        return False, "The signed file isn't the version that was asked for; nothing changed.", None
    for old in os.listdir(APP_DIR):  # leftovers from an update that was interrupted
        if old.startswith(".update-") and old.endswith(".py"):
            try:
                os.remove(os.path.join(APP_DIR, old))
            except OSError:
                pass
    fd, tmp = tempfile.mkstemp(dir=APP_DIR, prefix=".update-", suffix=".py")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(tmp, 0o700)
    try:
        test = subprocess.run([sys.executable, tmp, "version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        test = None
    if not test or test.returncode != 0 or test.stdout.strip() != version:
        os.remove(tmp)
        return False, "The new version failed its self-test on this device, so it was NOT installed.", None
    fresh = _load()
    if auto and (fresh.get("autoPaused") or version in (fresh.get("skipVersions") or [])):
        os.remove(tmp)  # the owner rolled back while this was downloading: their choice wins
        return False, "Automatic updates were paused during the download; nothing changed.", None
    prev = os.path.join(APP_DIR, "nightlight_helper.prev.py")
    if os.path.isfile(target):  # (it can be missing if something deleted it: then the update simply restores it)
        with open(target, "rb") as cur, open(prev + ".tmp", "wb") as out:
            out.write(cur.read())
        os.chmod(prev + ".tmp", 0o700)
        os.replace(prev + ".tmp", prev)  # kept for `nightlight rollback`
    os.replace(tmp, target)
    _RESTART.append(True)
    if not auto:  # the owner asked for this one: that ends a pause after a rollback
        _update_config(lambda c: (c.pop("autoPaused", None),
                                  c.__setitem__("skipVersions", [v for v in c.get("skipVersions") or [] if v != version])))
    return True, f"Updated from {VERSION} to {version} (signature checked); restarting.", None


def rollback():
    prev = os.path.join(APP_DIR, "nightlight_helper.prev.py")
    target = os.path.join(APP_DIR, "nightlight_helper.py")
    lock = _update_lock(wait=True)  # waits for an update in progress, so it can't undo this rollback
    try:
        if not os.path.isfile(prev) or os.path.islink(prev):
            sys.exit("There is no earlier version to go back to.")
        rejected = _file_version(target)
        # Pause first, then swap: an automatic update that checks after this sees the pause.
        _update_config(lambda c: (c.__setitem__("autoPaused", True), c.__setitem__(
            "skipVersions", sorted(set((c.get("skipVersions") or []) + ([rejected] if rejected else [])))[-10:])))
        os.replace(prev, target)
    finally:
        if lock:
            lock.close()
    print(f"Back on the earlier version (automatic updates paused; {rejected} won't install by itself). Restart the "
          "background service (or log out and in) to use it.")


# ------------------------------------------------------------------ expert sessions: owner-signed commands
# Off until the owner pins their passkey's public key here, at the device (`nightlight expert`, after comparing the
# fingerprint the app shows). A command runs only with a valid passkey signature over exactly this command, for this
# device, before its expiry, used once. The cloud can relay such a command but can't make one. docs/DESIGN-trust.md

import base64
import hashlib

EXPERT_TIMEOUT = 60
EXPERT_OUTPUT = 64 * 1024


def _b64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _openssl_verify(pem, data, sig):
    tool = shutil.which("openssl")
    if not tool:
        return False
    with tempfile.TemporaryDirectory(dir=_own_dir(APP_DIR)) as d:
        paths = {}
        for name, content in (("k", pem.encode()), ("d", data), ("s", sig)):
            paths[name] = os.path.join(d, name)
            with open(paths[name], "wb") as f:
                f.write(content)
        try:
            r = subprocess.run([tool, "dgst", "-sha256", "-verify", paths["k"], "-signature", paths["s"], paths["d"]],
                               capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return r.returncode == 0 and "Verified OK" in r.stdout


def expert_check(payload, signed, cfg, now=None, reusable=False):
    """None if the owner's passkey signed exactly this command for this device and it is still valid; else why not."""
    pinned = cfg.get("expert") or {}
    if not pinned.get("pem"):
        return "expert sessions aren't switched on at this device (run `nightlight expert` there)"
    if not isinstance(payload, dict) or not isinstance(signed, dict):
        return "the command isn't signed"
    if payload.get("device") != cfg.get("deviceId"):
        return "the command was signed for another device"
    if not isinstance(payload.get("expires"), int) or payload["expires"] < (now or time.time()):
        return "the signature has expired"
    if payload["expires"] > (now or time.time()) + 16 * 60:
        return "the signature is valid for too long (15 minutes at most)"
    if not reusable and payload.get("nonce") in (cfg.get("usedNonces") or {}):
        return "this signed command was already used"
    try:
        auth = _b64u(signed["authenticatorData"])
        client_raw = _b64u(signed["clientDataJSON"])
        client = json.loads(client_raw)
        sig = _b64u(signed["signature"])
    except (KeyError, ValueError, TypeError):
        return "the signature is malformed"
    want = base64.urlsafe_b64encode(hashlib.sha256(_canonical(payload)).digest()).decode().rstrip("=")
    if client.get("type") != "webauthn.get" or client.get("challenge") != want:
        return "the signature is for a different command"
    if client.get("origin") != pinned.get("origin") or client.get("crossOrigin") or "topOrigin" in client:
        return "the signature came from another site"
    if len(auth) < 37 or auth[:32] != hashlib.sha256(pinned.get("rpId", "").encode()).digest():
        return "the signature is for another site"
    if auth[32] & 0x05 != 0x05:  # user present (0x01) and user verified (0x04)
        return "the passkey didn't verify the person"
    if auth[32] & 0x10 and not auth[32] & 0x08:  # "backed up" without "backup eligible" is malformed
        return "the passkey's flags are inconsistent"
    if not _openssl_verify(pinned["pem"], auth + hashlib.sha256(client_raw).digest(), sig):
        return "the signature didn't check out"
    return None


# Investigation sessions: with one signed, time-boxed grant, the agent may run READ-ONLY commands in a loop. "Read
# only" is decided here, on the device, by exact rules per program: which sub-commands, which options (and what
# their values may look like), which arguments; programs come only from system folders, never from a path the
# command names; file contents only from log folders; nothing that looks like a secret. Anything else is refused.

_RO_DIRS = ("/bin", "/usr/bin", "/sbin", "/usr/sbin")
_RO_EXTRA_DIRS = {"docker": ("/usr/local/bin", "/opt/homebrew/bin"), "brew": ("/opt/homebrew/bin", "/usr/local/bin")}
_RO_LOG_ROOTS = ("/var/log", "/Library/Logs", "~/Library/Logs", "/private/var/log")
_RO_SECRET_WORDS = (".ssh", "keychain", ".gnupg", ".env", "id_rsa", "id_ed25519", "credential", ".aws", "gcloud",
                    "token", "passw", "secret", "shadow", "cookie", ".netrc", "nightlight", "private")
_RO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:/+-]{0,127}$")  # unit, container, host, interface, disk names
_RO_INT = re.compile(r"^\d{1,6}$")
_RO_SINCE = re.compile(r"^[0-9a-zA-Z:. -]{1,40}$")  # "1 hour ago", "2026-10-17 03:00", "today", "-1"

# prog: {subs: allowed first argument (None = no sub-command), then: {sub: allowed second word},
#        flags: options without a value, values: {option: kind}, args: kind of plain arguments, max: how many}
# kinds: "int", "name", "text" (any single argument), "since", "choice:a|b", "log" (a log file), "path" (a folder)
_RO_RULES = {
    "uptime": {}, "sw_vers": {}, "id": {}, "groups": {}, "vm_stat": {}, "hostinfo": {}, "mount": {},
    "date": {"flags": {"-u"}},
    "uname": {"flags": {"-a", "-m", "-r", "-s", "-v"}},
    "free": {"flags": {"-h", "-m", "-g"}},
    "lsblk": {"flags": {"-f"}},
    "df": {"flags": {"-h", "-k", "-H", "-i", "-l", "-P"}, "args": "path", "max": 3},
    "du": {"flags": {"-s", "-h", "-k", "-x"}, "values": {"-d": "int"}, "args": "path", "max": 3},
    # processes by name only (command lines can carry secrets): ps -axo pid,pcpu,pmem,comm
    "ps": {"flags": {"-e", "-A", "-x", "-ax"}, "values": {"-o": "fields", "-axo": "fields", "-eo": "fields",
                                                          "-Ao": "fields"}, "need_any": {"-o", "-axo", "-eo", "-Ao"}},
    "last": {"flags": {"-x", "-F"}, "values": {"-n": "int"}, "args": "choice:reboot|shutdown", "max": 2},
    "sysctl": {"flags": {"-n"}, "args": "name", "max": 6},
    "pmset": {"subs": {"-g"}, "args": "choice:batt|custom|assertions|log|sched|ps|therm|sysload|stats|live", "max": 1},
    "log": {"subs": {"show"}, "flags": {"--info", "--debug"},
            "values": {"--last": "since", "--predicate": "text", "--style": "choice:syslog|compact|default",
                       "--start": "since", "--end": "since"}},
    "journalctl": {"flags": {"--no-pager", "-k", "--list-boots", "-r", "-q", "-x"},
                   "values": {"-n": "int", "-p": "name", "-u": "name", "-b": "since", "--since": "since",
                              "--until": "since"}},
    "systemctl": {"subs": {"status", "list-units", "list-timers", "is-active", "is-failed", "is-enabled"},
                  "flags": {"--failed", "--no-pager", "--all"}, "values": {"--type": "name", "--state": "name"},
                  "args": "name", "max": 5},
    "launchctl": {"subs": {"list"}, "args": "name", "max": 1},
    "docker": {"subs": {"ps", "logs", "stats", "images", "version", "system"},
               "then": {"system": {"df"}}, "flags": {"-a", "--no-stream", "-t"},
               "values": {"--tail": "int", "--since": "since"}, "args": "name", "max": 3},
    "ip": {"subs": {"addr", "address", "route", "link"}, "then": {"link": {"show"}, "addr": {"show"},
                                                                  "address": {"show"}, "route": {"show"}},
           "args": "name", "max": 2},
    "ifconfig": {"args": "name", "max": 1},
    "netstat": {"flags": {"-r", "-n", "-a", "-t", "-u", "-l", "-i"}},
    "ping": {"values": {"-c": "int"}, "args": "name", "max": 1, "need": {"-c"}},
    "dig": {"flags": {"+short"}, "args": "name", "max": 2},
    "nslookup": {"args": "name", "max": 1}, "host": {"args": "name", "max": 1},
    "cat": {"args": "log", "max": 3},
    "head": {"values": {"-n": "int"}, "args": "log", "max": 3},
    "tail": {"values": {"-n": "int"}, "args": "log", "max": 3},
    "wc": {"flags": {"-l", "-c"}, "args": "log", "max": 3},
    "grep": {"flags": {"-i", "-E", "-F", "-c", "-v", "-n", "-h"}, "values": {"-m": "int", "-A": "int", "-B": "int",
                                                                              "-C": "int"},
             "pattern": True, "args": "log", "max": 3},
    "top": {"values": {"-l": "int", "-n": "int", "-o": "choice:cpu|mem"}, "flags": {"-b"}},
    "brew": {"subs": {"list", "outdated", "config"}, "flags": {"--versions", "--quiet", "--cask", "--formula"}},
    "apt": {"subs": {"list"}, "flags": {"--upgradable", "--installed"}},
    "softwareupdate": {"subs": {"-l", "--list"}},
    "diskutil": {"subs": {"list", "info", "apfs"}, "then": {"apfs": {"list"}}, "args": "name", "max": 1},
    "tmutil": {"subs": {"status", "latestbackup", "destinationinfo", "listbackups"}},
    "system_profiler": {"values": {"-detailLevel": "choice:mini|basic"}, "args": "sp", "max": 3},
}


def _ro_executable(prog):
    for d in _RO_DIRS + _RO_EXTRA_DIRS.get(prog, ()):
        path = os.path.join(d, prog)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _ro_value_ok(kind, v):
    if kind == "int":
        return bool(_RO_INT.match(v))
    if kind == "name":
        return bool(_RO_NAME.match(v))
    if kind == "since":
        return bool(_RO_SINCE.match(v))
    if kind == "text":
        return len(v) <= 300
    if kind.startswith("choice:"):
        return v in kind[7:].split("|")
    if kind == "fields":
        return all(f in ("pid", "ppid", "pcpu", "pmem", "rss", "vsz", "comm", "etime", "stat", "user", "lstart")
                   for f in v.split(","))
    if kind == "sp":
        return bool(re.match(r"^SP[A-Za-z]+DataType$", v))
    return False


def _ro_file_ok(kind, v):
    """A log file (contents are read) or a folder (only its size or free space is read)."""
    if v.startswith("-") or not v:
        return False
    real = os.path.realpath(os.path.expanduser(v))
    if kind == "path":
        return os.path.isdir(real)
    roots = [os.path.realpath(os.path.expanduser(r)) for r in _RO_LOG_ROOTS]
    return os.path.isfile(real) and any(real.startswith(r + os.sep) for r in roots)


def _ro_split_flags(tokens, rule):
    """-sh -> -s -h when every letter is a known flag without a value."""
    flags = rule.get("flags", set())
    out = []
    for t in tokens:
        if len(t) > 2 and t[0] == "-" and t[1] != "-" and all(f"-{c}" in flags for c in t[1:]):
            out.extend(f"-{c}" for c in t[1:])
        else:
            out.append(t)
    return out


def readonly_command(command):
    """(argv with the trusted program path, None) if `command` is read-only by this device's rules; (None, why)."""
    import shlex
    if not isinstance(command, str) or not command.strip() or len(command) > 500:
        return None, "empty or too long"
    if any(c in command for c in ";|&<>`$\n\r\\") or "\x00" in command:
        return None, "only one plain command is allowed (no pipes, redirects, chaining or substitution)"
    if any(w in command.lower() for w in _RO_SECRET_WORDS):
        return None, "it touches a place where secrets are kept"
    try:
        argv = shlex.split(command)
    except ValueError:
        return None, "it couldn't be read as one command"
    prog = argv[0]
    rule = _RO_RULES.get(prog)
    if "/" in prog or rule is None:
        return None, f"{prog} isn't on this device's read-only list (programs are named without a path)"
    exe = _ro_executable(prog)
    if not exe:
        return None, f"{prog} isn't installed in the system folders here"
    rest = _ro_split_flags(argv[1:], rule)
    if rule.get("subs") is not None:
        if not rest or rest[0] not in rule["subs"]:
            return None, f"only these {prog} sub-commands are allowed: {', '.join(sorted(rule['subs']))}"
        sub, rest = rest[0], rest[1:]
        then = (rule.get("then") or {}).get(sub)
        if then is not None:
            if rest and rest[0] in then:
                rest = rest[1:]
            elif rest and not rest[0].startswith("-") or sub == "system":
                return None, f"only `{prog} {sub} {'/'.join(sorted(then))}` is allowed"
    plain, seen, i = [], set(), 0
    values = rule.get("values", {})
    while i < len(rest):
        t = rest[i]
        if t in rule.get("flags", set()):
            seen.add(t)
        elif t in values:
            if i + 1 >= len(rest) or not _ro_value_ok(values[t], rest[i + 1]):
                return None, f"{t} needs a simple value"
            seen.add(t)
            i += 1
        elif "=" in t and t.split("=", 1)[0] in values:
            k, v = t.split("=", 1)
            if not _ro_value_ok(values[k], v):
                return None, f"{k} needs a simple value"
            seen.add(k)
        elif t.startswith("-") and not (rule.get("pattern") and not plain):
            return None, f"the option {t} isn't allowed for {prog}"
        else:
            plain.append(t)
        i += 1
    for need in rule.get("need", ()):
        if need not in seen:
            return None, f"{prog} needs {need}"
    if rule.get("need_any") and not seen & rule["need_any"]:
        return None, f"{prog} needs one of {', '.join(sorted(rule['need_any']))} (fields to show)"
    if rule.get("pattern"):
        if not plain or len(plain[0]) > 200:
            return None, f"{prog} needs a pattern"
        plain = plain[1:]
    kind, most = rule.get("args"), rule.get("max", 0)
    if len(plain) > most:
        return None, f"too many arguments for {prog}"
    for a in plain:
        ok = _ro_file_ok(kind, a) if kind in ("log", "path") else _ro_value_ok(kind or "", a)
        if not ok:
            return None, (f"{prog} may only read log files under {', '.join(_RO_LOG_ROOTS)}" if kind == "log"
                          else f"{a!r} isn't allowed here")
    if kind == "log" and not plain:
        return None, f"{prog} needs a log file"
    if prog == "ping" and int(rest[rest.index("-c") + 1]) > 10:
        return None, "ping at most 10 times"
    out = [exe] + argv[1:]
    if prog == "docker" and argv[1:2] == ["ps"]:  # its COMMAND column can carry secrets: only these columns
        out += ["--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
    return out, None


def readonly_ok(command):
    """None if read-only by this device's rules; else why not."""
    return readonly_command(command)[1]


def run_readonly(params):
    """One read-only command under a signed investigation grant (checked here: signature, device, expiry)."""
    params = params if isinstance(params, dict) else {}
    cfg = _load()
    grant, signed, command = params.get("grant"), params.get("signed"), params.get("command")
    if not isinstance(grant, dict) or grant.get("mode") != "read-only":
        return False, "Not run: there's no read-only investigation grant.", None
    why = expert_check(grant, signed, cfg, reusable=True)
    if why:
        return False, f"Not run: {why}.", None
    argv, why = readonly_command(command)
    if why:
        return False, f"Not run on this device: {why}.", None
    return _execute(command, argv=argv)


def run_expert(params):
    params = params if isinstance(params, dict) else {}
    cfg = _load()
    payload, signed = params.get("payload"), params.get("signed")
    why = expert_check(payload, signed, cfg)
    if why:
        return False, f"Not run: {why}.", None
    taken = []

    def consume(c):  # under the config lock: check and record in one step, so a signature runs at most once
        old = c.get("usedNonces") or {}
        if isinstance(old, list):  # from 0.9.8: no expiry recorded, so keep each for the longest possible lifetime
            old = {n: int(time.time()) + 16 * 60 for n in old}
        used = {n: e for n, e in old.items() if e > time.time()}
        if payload["nonce"] in used:
            return
        used[payload["nonce"]] = payload["expires"]
        c["usedNonces"] = used
        taken.append(True)
    _update_config(consume)
    if not taken:
        return False, "Not run: this signed command was already used.", None
    return _execute(payload["command"], shell=True)


def _execute(command, shell=False, argv=None):
    """Run it (a shell only for a command the owner signed by itself; read-only ones run without a shell), keep a
    transcript on the device, and return the scrubbed output."""
    import shlex
    try:
        argv = ["/bin/sh", "-c", command] if shell else (argv or shlex.split(command))
        env = {"PATH": ":".join(_RO_DIRS), "LANG": "C", "HOME": _HOME}  # nothing inherited steers what runs
        r = subprocess.run(argv, capture_output=True, timeout=EXPERT_TIMEOUT, env=env if not shell else None,
                           cwd=_HOME, stdin=subprocess.DEVNULL, check=False)
        out, code = (r.stdout[-EXPERT_OUTPUT:] + r.stderr[-EXPERT_OUTPUT:]).decode(errors="replace"), r.returncode
    except subprocess.TimeoutExpired:
        out, code = "(stopped after 60 seconds)", None
    except OSError as e:
        out, code = f"couldn't run it ({type(e).__name__})", None
    try:  # a transcript stays on the device (owner-only folder)
        with open(os.path.join(_own_dir(APP_DIR), "expert-transcript.log"), "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} exit={code} $ {command}\n")
    except OSError:
        pass
    text, hidden = scrub(out.replace(_HOME, "~"))
    tail = _tail(text, lines=80, limit=3500) + (f"\n({hidden} private values hidden)" if hidden else "")
    return code == 0, f"Ran it (exit code {code})." if code is not None else "It didn't finish.", tail


def expert_setup(turn_off=False):
    """At the device: pin (or forget) the owner's passkey for expert sessions, after comparing its fingerprint."""
    if turn_off:
        _update_config(lambda c: c.pop("expert", None))
        print("Expert sessions are off on this device.")
        report_now()
        return
    cfg = _load()
    st, body = _get_json(check_api(cfg["api"]) + "/helper/expert-key", cfg["token"])
    if st != 200:
        sys.exit("The owner hasn't created a passkey for expert sessions yet (in the app: the device > Expert sessions).")
    fp = key_fingerprint(body.get("pem", ""))  # computed here from the key itself, never taken from the cloud
    if not fp:
        sys.exit("That key couldn't be read; nothing was changed.")
    print(f"The passkey's code, worked out on this device: {fp}")
    if not sys.stdin.isatty() or not _ask("Does the app (in the browser where you created the passkey) show exactly "
                                          "this code?", False):
        sys.exit("Nothing was changed.")
    pinned = {"pem": body["pem"], "rpId": body["rpId"], "origin": body["origin"], "fingerprint": fp}
    _update_config(lambda c: c.__setitem__("expert", pinned))
    print("Expert sessions are on: commands you sign with that passkey can run here. `nightlight expert --off` "
          "turns them off.")
    report_now()


def key_fingerprint(pem):
    """A 64-bit code from the public key's own bytes (SHA-256 of its DER form), shown as XXXX-XXXX-XXXX-XXXX."""
    try:
        der = base64.b64decode("".join(l for l in pem.strip().splitlines() if not l.startswith("-----")))
    except (ValueError, TypeError):
        return None
    h = hashlib.sha256(der).hexdigest()[:16].upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4)) if der else None


def report_now():
    """Tell Nightlight right away (a change made here shows in the app in seconds, not at the next regular report).
    Only the report itself: jobs stay with the background service. Waits out the server's short minimum gap.
    Only when a person runs the command in a terminal; scripted use waits for the next regular report."""
    if not sys.stdout.isatty():
        return
    for attempt in range(3):
        try:
            cfg = _load()
            st, body = _post(check_api(cfg["api"]) + "/helper/heartbeat?jobs=0", facts(),
                             {"X-Device-Token": cfg["token"]})
        except Exception:  # a courtesy: never let it fail the command that just succeeded
            return
        if st == 200:
            print("The app shows it now.")
            return
        if st != 429:
            break
        time.sleep(min(int(body.get("retryAfter") or 20), 20) + 1)
    print("The app shows it at the next report (within a minute).")


def _get_json(url, token):
    req = urllib.request.Request(url, method="GET", headers={"X-Device-Token": token})
    try:
        with _OPENER.open(req, timeout=30) as r:
            return r.status, json.loads(r.read(65536) or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        return 0, {}


def run_job(job, wait=5):
    """Run one approved job, only if it is a known kind on a target the owner allowed here. Returns
    (ok, summary, state). Commands are fixed argument lists; nothing from the server reaches a shell."""
    kind, params = job.get("type"), job.get("params")
    if kind == "expert_command":
        return run_expert(params)
    if kind == "expert_read":
        return run_readonly(params)
    if kind == "remove_device":  # allowed in both modes: it only removes Nightlight itself
        ok, summary = remove_from_app()
        _RESTART.append("exit")  # nothing to restart into: the loop ends after reporting
        return ok, summary, None
    if kind == "discover":
        # Asked from the app: the owner's tap is the consent, on a device they let the app manage. A strict device
        # only looks when someone runs `discover` here.
        if _manage() != "app":
            return False, "This device only looks for devices nearby when someone runs it there.", None
        ok, n = discover(yes=True, quiet=True)
        if not ok:
            return False, "Looked nearby but couldn't send the list.", None
        return True, (f"Found {n} thing(s) nearby; they're under Found nearby to add." if n
                      else "Looked nearby: nothing new to suggest."), None
    if kind == "mac_folders":
        # Chosen by the owner in the app's setup card while they're at the Mac: the same yes as at install.
        if sys.platform != "darwin":
            return False, "Only a Mac has private folders to allow; nothing was done.", None
        if _manage() != "app":
            return False, "This Mac is set to strict: run `nightlight settings` on it to allow its folders.", None
        _allow_mac_private()
        return True, "macOS asked about your folders; click Allow on the Mac.", None
    if kind == "update_helper":
        return self_update(params.get("version") if isinstance(params, dict) else None)
    if kind == "fix":
        return run_fix(params.get("recipe") if isinstance(params, dict) else None)
    if kind == "inspect":
        return run_inspect(params.get("what") if isinstance(params, dict) else None)
    if kind == "diagnose":
        target = params.get("target") if isinstance(params, dict) else None
        if not isinstance(target, str) or not TARGET_RE.fullmatch(target):
            return False, "That isn't something this helper can look into.", None
        return look_into(target)
    if kind == "restart_service":
        unit = params.get("unit") if isinstance(params, dict) else None
        if not isinstance(unit, str) or not TARGET_RE.fullmatch(unit):
            return False, "That isn't a service this helper can restart.", None
        return _restart_unit(unit, wait)
    name = params.get("container") if isinstance(params, dict) else None
    if kind != "restart_container" or not isinstance(name, str) or name not in _allowed().get(kind, []):
        return False, "This job isn't allowed on this device, so nothing was done.", None
    if not shutil.which("docker"):
        return False, "Docker isn't available on this device, so nothing was done.", None
    state = _container_state(name)
    if state is None:
        return False, f"There is no container named {name} here, so nothing was done.", None
    if state == "running":
        return True, f"{name} was already running; nothing needed doing.", state
    _run(["docker", "start", name], timeout=60)
    time.sleep(wait)
    state = _container_state(name)
    if state == "running":
        return True, f"Started {name}; it was still running {wait} seconds later.", state
    return False, f"Tried to start {name}, but it is {state or 'not running'}.", state


LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def check_api(url):
    """The API must be HTTPS (plain HTTP only for a local development server on this machine)."""
    u = urllib.parse.urlsplit(url)
    if u.scheme == "https" and u.hostname:
        return url.rstrip("/")
    if u.scheme == "http" and u.hostname in LOOPBACK:
        return url.rstrip("/")
    sys.exit("Refusing to send credentials to a non-HTTPS address: " + url)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects with a code or token attached; a redirect is treated as an error."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _post(url, body, headers=None):
    """POST JSON. Returns (status, body dict); status 0 means the network failed."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with _OPENER.open(req, timeout=30) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            raw = e.read()
        except (OSError, http.client.HTTPException):
            raw = b""
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        return 0, {"error": str(getattr(e, "reason", e))[:200]}
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return status, {"error": "unexpected response"}
    return status, body if isinstance(body, dict) else {"error": "unexpected response"}


def _load():
    with open(CONFIG) as f:
        return json.load(f)


def _update_config(change):
    """Read-modify-write the config under a lock, on a FRESH copy, so the background service and a person running
    `nightlight settings` can never overwrite each other's changes (e.g. a report undoing a switch to strict)."""
    import fcntl
    _own_dir(CONFIG_DIR)
    with open(os.path.join(CONFIG_DIR, ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            cfg = _load()
        except (OSError, ValueError):
            cfg = {}
        change(cfg)
        _save_config(cfg)
        return cfg


def _save_config(data):
    """Write the token file owner-only: a fresh 0600 file, atomically replacing the entry (never through a symlink)."""
    if os.path.islink(CONFIG_DIR):
        sys.exit(f"Refusing to use {CONFIG_DIR}: it is a symbolic link.")
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    st = os.stat(CONFIG_DIR)
    if st.st_uid != os.getuid():
        sys.exit(f"Refusing to use {CONFIG_DIR}: it belongs to another user.")
    if stat.S_IMODE(st.st_mode) & 0o077:
        os.chmod(CONFIG_DIR, 0o700)
    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".helper-", suffix=".json")  # created 0600
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG)  # replaces the directory entry itself, not a symlink's target
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def enrol(api, code, name):
    api = check_api(api)
    status, body = _post(api + "/helper/enrol", {"code": code, "name": name})
    if status != 201:
        sys.exit(f"Enrolment failed ({status or 'network error'}): {body.get('code') or body.get('error') or body}")
    _save_config({"api": api, "token": body["token"], "deviceId": body["deviceId"]})
    print(f"Joined Nightlight as device {body['deviceId']}. Token saved to {CONFIG} (owner-only).")


_RETRY_AFTER = {"s": 0}  # the gap the server asked for when a report came too soon


def once():
    cfg = _load()
    api = check_api(cfg["api"])
    status, body = _post(api + "/helper/heartbeat", facts(), {"X-Device-Token": cfg["token"]})
    if status == 200 and body.get("ok") is not True:
        status = 0  # a 200 without our acknowledgment is a protocol error, not a delivered report
        body = {"error": body.get("error") or "unexpected response"}
    _RETRY_AFTER["s"] = int(body.get("retryAfter") or 20) if status == 429 else 0
    if status == 200:
        print(f"Report sent: {body.get('findings', 0)} finding(s).")
        _remember_about(cfg, body)
        poll = body.get("pollEverySec")
        _POLL["every"] = poll if isinstance(poll, int) and 0 < poll <= 60 else 0
        watch = body.get("watch")
        if isinstance(watch, list) and watch != cfg.get("watch"):
            wl = [w for w in watch if isinstance(w, dict)][:10]
            _update_config(lambda c: c.__setitem__("watch", wl))  # only this field; addresses stay local
        key = body.get("netKey")
        if isinstance(key, str) and NET_KEY_RE.fullmatch(key) and key != cfg.get("netKey"):
            _update_config(lambda c: c.__setitem__("netKey", key))  # for fingerprints from the next report on
        names = body.get("deviceNames") is True  # the owner's switch; an older server never says yes
        if names != (cfg.get("deviceNames") is True):
            _update_config(lambda c: c.__setitem__("deviceNames", names))
        jobs = body.get("jobs")
        for job in jobs if isinstance(jobs, list) else []:
            if isinstance(job, dict) and isinstance(job.get("id"), str) and ACTION_RE.fullmatch(job["id"]):
                _do_job(api, cfg["token"], job)
        latest = body.get("latestHelper")
        fresh = _load()
        if not _RESTART and isinstance(latest, str) and _ver(latest) > _ver(VERSION) and \
                fresh.get("manage") == "app" and (fresh.get("remote") or {}).get("autoUpdate") is True:
            print(self_update(latest, api, auto=True)[1])  # the owner chose "install signed updates automatically"
    elif status == 401:
        print("This device's access was revoked or is unknown. Enrol again with a new code.")
    else:
        print(f"Report not sent ({status or 'network error'}): {body.get('code') or body.get('error')}")
    return status


def _do_job(api, token, job):
    try:
        ok, summary, extra = run_job(job)
    except Exception as e:  # report a crash as a failed job rather than leaving it unfinished
        ok, summary, extra = False, f"The helper hit an error ({type(e).__name__}).", None
    print(("Job done: " if ok else "Job failed: ") + summary)
    body = {"ok": ok, "summary": summary[:200]}
    if job.get("type") in ("diagnose", "inspect", "expert_command", "expert_read"):
        body["output"] = (extra or "")[:4000] or None  # what the look found (already scrubbed here)
    else:
        body["state"] = extra if extra in STATES else None
    for attempt in range(3):
        status, _ = _post(f"{api}/helper/jobs/{job['id']}/result", body, {"X-Device-Token": token})
        if status in (200, 401, 404, 409):
            return
        time.sleep(5 * (attempt + 1))


def _remember_about(cfg, body):
    """Keep what `status` shows, and the app's permission switches (used only in app-managed mode)."""
    about = {"lastReport": {"at": time.strftime("%Y-%m-%d %H:%M"), "result": "ok"}}
    for key in ("deviceName", "ownerHint"):
        if isinstance(body.get(key), str):
            about[key] = body[key][:80]
    if isinstance(body.get("permissions"), dict):
        about["remote"] = body["permissions"]
    if any(cfg.get(k) != v for k, v in about.items() if k != "lastReport") or \
            time.time() - cfg.get("_aboutSaved", 0) > 600:
        _update_config(lambda c: c.update(about, _aboutSaved=int(time.time())))  # never touches manage/allow


REFUSED_RETRY = 1800  # seconds between tries while the key is refused
REFUSED_GIVE_UP = 7 * 86400


def run(every):
    """Keep reporting; network or server trouble is retried with growing waits, a revoked token stops."""
    try:
        if _load().get("removed"):
            sys.exit(0)  # removed from the app; only the service definition is left (it needs an administrator)
    except (OSError, ValueError):
        pass
    wait, refused = every, None
    while True:
        try:
            status = once()
        except Exception as e:  # never let one bad report end monitoring
            print(f"Report failed: {type(e).__name__}")
            status = 0
        if "exit" in _RESTART:
            sys.exit(0)
        if status == 401:  # refused: removed in the app, or a server problem. Keep asking, slowly, so a server
            refused = refused or time.time()  # problem heals itself; give up only after REFUSED_GIVE_UP
            if time.time() - refused > REFUSED_GIVE_UP:
                print("Nightlight has refused this device for a week: it was removed. The helper stops here; to "
                      "delete its files, run the uninstall line from the Nightlight app on this device.")
                sys.exit(0)  # a clean exit isn't restarted
            print("Nightlight refused this device's key; trying again later.")
            time.sleep(REFUSED_RETRY)  # no work can come while the key is refused
            continue
        refused = None
        if _RESTART:  # a signed update was installed and reported: become the new version, same process
            sys.stdout.flush()
            os.execv(sys.executable, [sys.executable, os.path.join(APP_DIR, "nightlight_helper.py"), *sys.argv[1:]])
        if status == 429:  # too soon after the last report (e.g. right after a restart): not a failure
            time.sleep(min(max(_RETRY_AFTER["s"], 1), 30) + 1)
            continue
        wait = every if status == 200 else min(max(wait, every) * 2, 900)
        _wait_and_claim(wait)  # returns early after running a job: the change is then reported right away


_CHANNEL = {"ok": True}  # False once a server said it has no work channel (an older server): poll instead


def _wait_and_claim(seconds):
    """Until the next report, keep the work channel open (docs/adr/0003-job-channel.md): the server holds the
    request and answers the moment a job is approved here, so approvals start within about a second."""
    end = time.monotonic() + seconds
    while time.monotonic() < end and not _RESTART:
        if not _CHANNEL["ok"]:
            return _poll_until(max(0.0, end - time.monotonic()))
        try:
            cfg = _load()
            api, token = check_api(cfg["api"]), cfg["token"]
        except Exception:  # not joined (or config unreadable): nothing to wait for
            time.sleep(max(0.0, end - time.monotonic()))
            return
        hold = int(min(25, max(0.0, end - time.monotonic())))  # answered by the time the next report is due
        if hold < 1:
            return
        try:
            st, body = _post(api + f"/helper/jobs/wait?hold={hold}", {}, {"X-Device-Token": token})
        except Exception:
            st, body = 0, {}
        if st == 404:
            _CHANNEL["ok"] = False
            continue
        if st != 200:  # network or server trouble (or a wait already open): wait a little, never spin
            time.sleep(min(15.0, max(0.0, end - time.monotonic())))
            continue
        jobs = [j for j in (body.get("jobs") if isinstance(body.get("jobs"), list) else [])
                if isinstance(j, dict) and isinstance(j.get("id"), str) and ACTION_RE.fullmatch(j["id"])]
        for job in jobs:
            _do_job(api, token, job)
        if jobs:
            return  # state just changed on this device: report it now, not at the next regular tick


def _poll_until(seconds):
    """For older servers: sleep until the next report; while the owner is chatting, check for work every few
    seconds."""
    if not _POLL["every"]:
        time.sleep(seconds)
        return
    end = time.time() + seconds
    while time.time() < end:
        step = _POLL["every"]
        if not step:
            time.sleep(max(0.0, end - time.time()))
            return
        time.sleep(min(step, max(0.0, end - time.time())))
        try:
            cfg = _load()
            api = check_api(cfg["api"])
            st, body = _post(api + "/helper/jobs/claim", {}, {"X-Device-Token": cfg["token"]})
        except Exception:
            continue
        if st != 200:
            continue
        poll = body.get("pollEverySec")
        _POLL["every"] = poll if isinstance(poll, int) and 0 < poll <= 60 else 0
        jobs = body.get("jobs")
        for job in jobs if isinstance(jobs, list) else []:
            if isinstance(job, dict) and isinstance(job.get("id"), str) and ACTION_RE.fullmatch(job["id"]):
                _do_job(api, cfg["token"], job)
        if _RESTART:
            return  # an update was installed: the loop restarts into it now


def _manage():
    try:
        m = _load().get("manage")
    except (OSError, ValueError):
        return None
    return m if m in ("app", "strict") else None


def _ask(question, default_yes):
    """A yes/no question on the terminal. No terminal (or no answer) = the default."""
    try:
        ans = input(question + (" [Y/n] " if default_yes else " [y/N] ")).strip().lower()
    except EOFError:  # Ctrl-D: stop without changing anything
        print()
        sys.exit("No answer; nothing was changed.")
    return default_yes if not ans else ans.startswith("y")


def default_name():
    """A friendly default device name from the hardware or OS, never the host name."""
    if sys.platform == "darwin":
        model = _run(["sysctl", "-n", "hw.model"]).strip()
        return "Mac mini" if model.startswith("Macmini") else "MacBook" if "Book" in model else "Mac"
    try:
        with open("/proc/device-tree/model") as f:
            if "Raspberry Pi" in f.read():
                return "Raspberry Pi"
    except OSError:
        pass
    return (_os_name().split(" ")[0] or "Linux") + " computer"


PAIR_WAIT = 600
BROWSER_WAIT = 900  # the Mac installer's path: signing in first can take a while (the server's code may end sooner)


def _open_browser(url):
    """Open the default browser on `url`. False if there is no way to."""
    tool = "open" if sys.platform == "darwin" else shutil.which("xdg-open")
    if not tool:
        return False
    try:
        return subprocess.run([tool, url], capture_output=True, timeout=20, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _notify(text):
    """A Mac notification for someone who isn't at a terminal (the installer's path). Best effort."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(["osascript", "-e", "on run argv", "-e", 'display notification (item 1 of argv) with title '
                        '"Nightlight"', "-e", "end run", text], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def pair(api, web=None, name=None, browser=False, then_install=False):
    """Join by a code this device shows: the owner types it in the app or scans the QR with a phone. With `browser`
    (the Mac installer: nobody at a terminal) the approval page opens by itself, and `then_install` sets up the
    background service right after the approval, managed from the app."""
    api = check_api(api)
    if browser and not web:
        sys.exit("--browser needs --web (the Nightlight web address).")
    again = "Open the Nightlight installer again for a new code." if browser else "Run pair again for a new one."

    def give_up(text):
        if browser:
            _notify(text)
        sys.exit("  " + text)

    status, body = _post(api + "/helper/pair/start", {"name": (name or default_name())[:40], "os": _os_name()})
    if status != 201:
        give_up(f"Couldn't start pairing ({status or 'network error'}): {body.get('code') or body.get('error')}")
    code, interval = body["code"], max(int(body.get("interval", 3)), 2)
    print(f"\n  Your code:  {code}\n")
    if web:
        link = f"{web.rstrip('/')}/pair?code={code}"
        print(f"  Open Nightlight > Add a device > Enter code, or scan this with your phone:\n  {link}\n")
        if browser:
            if not _open_browser(link):
                _notify(f"Open {link} to add this Mac.")
        elif shutil.which("qrencode"):
            subprocess.run(["qrencode", "-t", "ANSIUTF8", link], check=False)
    wait = BROWSER_WAIT if browser else PAIR_WAIT
    print(f"  Waiting for you to approve it ({wait // 60} minutes)...")
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(interval)
        st, res = _post(api + "/helper/pair/poll", {"code": code, "pollSecret": body["pollSecret"]})
        if st == 200 and res.get("token"):
            _save_config({"api": api, "token": res["token"], "deviceId": res["deviceId"]})
            print("  Approved. This device is now on your Nightlight map.")
            if then_install:
                try:
                    install(manage="app")
                except (SystemExit, OSError, subprocess.SubprocessError) as e:
                    print(f"  Install failed: {e}")
                    give_up("Approved, but the background service didn't start. Open the Nightlight installer again.")
                if browser:
                    _notify("This Mac is now on your Nightlight map.")
            return
        if st == 401:
            give_up("The code was declined or has expired. " + again)
    give_up("The code expired. " + again)


# ------------------------------------------------------------------ discovery (owner-run, reviewed here first)
# What's nearby on this network. Addresses (IP, MAC) stay on this device; only a guess of what each thing is
# ("Home Assistant", "Printer"), its maker and model, which known services answer and, while the account shows names,
# the name it announces are sent, and only the ones you pick.

PORTS = {22: "remote login (SSH)", 80: "web page", 443: "secure web page", 445: "file sharing", 631: "printer",
         7000: "AirPlay receiver", 8123: "Home Assistant", 25565: "Minecraft", 32400: "Plex"}
MDNS = {"_home-assistant._tcp": "Home Assistant", "_plexmediasvr._tcp": "Plex", "_smb._tcp": "file sharing",
        "_ipp._tcp": "printer", "_printer._tcp": "printer", "_googlecast._tcp": "Chromecast / Google speaker",
        "_airplay._tcp": "AirPlay speaker or TV", "_hap._tcp": "HomeKit accessory", "_ssh._tcp": "remote login (SSH)",
        "_raop._tcp": "AirPlay speaker", "_companion-link._tcp": "Apple device", "_apple-mobdev2._tcp": "Apple device"}
# A small, public table of makers by the first half of the hardware address (IEEE registry), common in homes.
VENDORS = {"b827eb": "Raspberry Pi", "dca632": "Raspberry Pi", "e45f01": "Raspberry Pi", "28cdc1": "Raspberry Pi",
           "d83add": "Raspberry Pi", "2ccf67": "Raspberry Pi", "001132": "Synology", "245ebe": "QNAP",
           "00089b": "QNAP", "000c29": "VMware virtual machine", "005056": "VMware virtual machine",
           "001788": "Philips Hue", "000e58": "Sonos", "949f3e": "Sonos", "48a6b8": "Sonos",
           "240ac4": "Espressif (smart-home gadget)", "30aea4": "Espressif (smart-home gadget)",
           "84f3eb": "Espressif (smart-home gadget)", "a4cf12": "Espressif (smart-home gadget)",
           "3c71bf": "Espressif (smart-home gadget)", "bcddc2": "Espressif (smart-home gadget)",
           "f4f5d8": "Google", "546009": "Google", "3c5ab4": "Google", "44650d": "Amazon", "6854fd": "Amazon",
           "fc65de": "Amazon", "24a43c": "Ubiquiti", "788a20": "Ubiquiti", "fcecda": "Ubiquiti", "7483c2": "Ubiquiti",
           "18e829": "Ubiquiti", "98b6e9": "Nintendo"}


def _neighbours():
    """IP -> MAC from the system's neighbour table (no scanning)."""
    out = {}
    try:
        with open("/proc/net/arp") as f:
            for line in f.read().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
                    out[parts[0]] = parts[3].lower()
        return out
    except OSError:
        pass
    for line in _run(["arp", "-an"]).splitlines():  # macOS: "? (192.168.1.5) at aa:bb:cc:dd:ee:ff on en0 ..."
        m = re.search(r"\(([\d.]+)\) at ([0-9a-fA-F:]+)", line)
        if m and m.group(2) != "ff:ff:ff:ff:ff:ff":
            mac = ":".join(x.zfill(2) for x in m.group(2).lower().split(":"))
            out[m.group(1)] = mac
    return out


def _mdns():
    """IP -> set of service kinds announced on the network (asked of the system's mDNS service)."""
    out = {}
    for ip, kind, *_rest in _hourly("mdns", _mdns_records, every=60):
        if kind in MDNS:
            out.setdefault(ip, set()).add(MDNS[kind])
    return out


def _open_ports(ips):
    import concurrent.futures
    import socket as _s

    def probe(pair):
        ip, port = pair
        try:
            with _s.create_connection((ip, port), timeout=0.3):
                return ip, port
        except OSError:
            return None

    pairs = [(ip, p) for ip in list(ips)[:64] for p in PORTS]
    found = {}
    with concurrent.futures.ThreadPoolExecutor(32) as ex:
        for hit in ex.map(probe, pairs):
            if hit:
                found.setdefault(hit[0], []).append(hit[1])
    return found


def _vendor(mac):
    if not mac:
        return None
    first = int(mac[:2], 16)
    if first & 0x02:
        return "private address (likely a phone or laptop)"
    return VENDORS.get(mac.replace(":", "")[:6])


def _guess(vendor, services, ports):
    """A plain-words guess of what something is, from what answers on it and who made it."""
    for service, name in (("Home Assistant", "Home Assistant"), ("Plex", "Plex media server"),
                          ("Minecraft", "Minecraft server"), ("printer", "Printer"), ("router", "Router"),
                          ("file sharing", "File share (NAS or computer)"), ("media server", "Media server")):
        if service in services:
            return name
    if any("speaker" in x or "Chromecast" in x or "TV" in x or x == "media player" for x in services):
        return "Speaker or TV"
    if vendor in ("Raspberry Pi", "VMware virtual machine"):
        return vendor
    if 22 in ports:
        return "Computer (remote login)"
    if "AirPlay receiver" in services:  # a Mac has this too, but also remote login (above)
        return "Speaker or TV"
    if 80 in ports or 443 in ports:
        return "Device with a web page"
    return vendor or "Unknown device"


# Who made it and which model, as the things themselves announce it. Only outgoing questions, never a socket that
# waits for others to call in (an unattended helper must never raise a firewall prompt): mDNS records come from the
# system's own service (`dns-sd` on a Mac, avahi on Linux), and the router's UPnP description file is fetched from a
# few well-known places on the router only. What they announce is free text a person may have typed ("Alex MacBook"),
# so nothing of it leaves as written: the maker must be one of the brands below (sent as the table spells it), and the
# model must be an Apple model from the table below or look like a product code ("HL-L2350DW", "DocuPrint CP115/118
# w"). Anything else is dropped here, and the server checks the same rules again. Names (Bonjour instance names, a
# UPnP friendlyName, host names) are a separate field, sent only while the owner shows names (`_seen_name`).

IDENTIFY_BUDGET = 12  # seconds for the whole look at makers and models, start to finish
MDNS_SECONDS = 3  # how long the mDNS listings run (side by side) before they are stopped
DESCRIPTION_BYTES = 64 * 1024
MDNS_ASK = ("_ipp._tcp", "_printer._tcp", "_airplay._tcp", "_raop._tcp", "_device-info._tcp", "_googlecast._tcp",
            "_smb._tcp", "_hap._tcp", "_home-assistant._tcp", "_companion-link._tcp",
            "_apple-mobdev2._tcp")
# Where routers commonly keep their UPnP description (miniupnpd, Netgear, TP-Link, AVM, Broadcom/Realtek kits).
UPNP_PLACES = ((1900, "/rootDesc.xml"), (5000, "/rootDesc.xml"), (49152, "/description.xml"), (2189, "/gatedesc.xml"),
               (52869, "/picsdesc.xml"), (80, "/rootDesc.xml"), (49000, "/igddesc.xml"))
UPNP_KIND = (("InternetGatewayDevice", "router"), ("MediaRenderer", "media player"),
             ("MediaServer", "media server"), ("Printer", "printer"))
APPLE_MODELS = (("MacBookPro", "MacBook Pro"), ("MacBookAir", "MacBook Air"), ("MacBook", "MacBook"),
                ("Macmini", "Mac mini"), ("MacPro", "Mac Pro"), ("iMac", "iMac"), ("iPhone", "iPhone"),
                ("iPad", "iPad"), ("AppleTV", "Apple TV"), ("AudioAccessory", "HomePod"), ("Mac", "Mac"))
# Makers common in homes and small offices: how they announce themselves (lower case, punctuation as spaces; a longer
# announcement that starts with one of these counts, "brother industries ltd") -> how Nightlight writes them. The
# server keeps the same list (real.MAKERS).
KNOWN_MAKERS = {
    "apple": "Apple", "brother": "Brother", "canon": "Canon", "epson": "Epson", "seiko epson": "Epson", "hp": "HP",
    "hewlett packard": "HP", "xerox": "Xerox", "fuji xerox": "Fuji Xerox", "fujifilm": "Fujifilm", "lexmark": "Lexmark",
    "samsung": "Samsung", "kyocera": "Kyocera", "ricoh": "Ricoh", "konica minolta": "Konica Minolta", "sharp": "Sharp",
    "oki": "OKI", "dell": "Dell", "pantum": "Pantum", "netgear": "Netgear", "tp link": "TP-Link", "asus": "ASUS",
    "asustek": "ASUS", "linksys": "Linksys", "d link": "D-Link", "ubiquiti": "Ubiquiti", "avm": "AVM",
    "synology": "Synology", "qnap": "QNAP", "western digital": "Western Digital", "wd": "Western Digital",
    "seagate": "Seagate", "buffalo": "Buffalo", "asustor": "Asustor", "terramaster": "TerraMaster", "sonos": "Sonos",
    "bose": "Bose", "sony": "Sony", "lg": "LG", "philips": "Philips", "signify": "Philips", "panasonic": "Panasonic",
    "yamaha": "Yamaha", "denon": "Denon", "marantz": "Marantz", "onkyo": "Onkyo", "pioneer": "Pioneer",
    "harman": "Harman", "roku": "Roku", "google": "Google", "amazon": "Amazon", "microsoft": "Microsoft",
    "nintendo": "Nintendo", "raspberry pi": "Raspberry Pi", "huawei": "Huawei", "zte": "ZTE", "xiaomi": "Xiaomi",
    "tenda": "Tenda", "mercusys": "Mercusys", "zyxel": "Zyxel", "eero": "eero", "arris": "Arris",
    "technicolor": "Technicolor", "sagemcom": "Sagemcom", "cisco": "Cisco", "mikrotik": "MikroTik", "belkin": "Belkin",
    "vizio": "Vizio", "tcl": "TCL", "hisense": "Hisense", "nvidia": "NVIDIA", "iptime": "ipTIME", "allradio": "allRadio"}
# Words allowed in a model besides codes ("LaserJet Pro M404dn"): series names, never anything that is also a name.
SERIES_WORDS = {"docuprint", "laserjet", "officejet", "deskjet", "envy", "pixma", "imageclass", "ecotank", "workforce",
                "nighthawk", "archer", "deco", "orbi", "diskstation", "rackstation", "fritz", "box", "mycloud",
                "readynas", "terastation", "linkstation", "airport", "bravia", "color", "colour", "pro", "plus",
                "mini", "ultra", "series", "wireless", "multifunction", "mfp", "lite"}


def _maker(text):
    """The table's spelling of a known maker, or None for anything else."""
    if not isinstance(text, str):
        return None
    words = " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())
    return next((name for key, name in sorted(KNOWN_MAKERS.items(), key=lambda kv: -len(kv[0]))
                 if words == key or words.startswith(key + " ")), None)


# Hardware ids in a model field: hex pairs joined by - or : ("AA-BB-CC-DD-EE-12"), or a long run of hex digits.
HARDWARE_SHAPE = re.compile(r"(?i)(?:\b|^)[0-9a-f]{2}(?:[-:][0-9a-f]{2}){2,}|[0-9a-f]{8,}")

def _product_code(text):
    """A model kept only when it looks like a product code: at most 40 characters and 5 words, with a digit somewhere;
    each word made of letters, digits and / + - only, and either holding a digit, or a short all-capitals code, a single
    letter, or a known series word. "Alex MacBook", host names and sentences never pass."""
    if not isinstance(text, str):
        return None
    text = re.sub(r"(?i)\s+series$", "", " ".join(text.split()))
    if scrub(text)[0] != text:
        return None  # holds something the scrubber hides (an address, a key)
    words = text.split(" ")
    if not text or len(text) > 40 or len(words) > 5 or not re.search(r"\d", text):
        return None
    for w in words:
        if not (w.lower() in SERIES_WORDS or (len(w) == 1 and w.isalnum()) or (
                re.fullmatch(r"[A-Z0-9][A-Z0-9/+-]*[a-z]{0,3}", w) and not HARDWARE_SHAPE.search(w)
                and (re.search(r"\d", w) or (w.isalpha() and w.isupper() and len(w) <= 6)))):
            return None  # a word that isn't a code: a name, a host name, a hardware address
    return text


def _apple_model(code):
    """ "Macmini9,1" -> "Mac mini"; an Apple model code we don't know -> None."""
    if not isinstance(code, str):
        return None
    return next((words for prefix, words in APPLE_MODELS if re.fullmatch(prefix + r"\d+,\d+", code)), None)


def _txt_about(kind, txt):
    """{maker, model} as announced in one mDNS TXT record of a printer, an AirPlay speaker or TV, or an Apple device
    (raw: `_keep` decides what may leave)."""
    if kind in ("_ipp._tcp", "_printer._tcp"):
        maker, model, ty = txt.get("usb_MFG"), txt.get("usb_MDL"), txt.get("ty") or ""
        if not model and ty:  # "Brother HL-L2350DW series"
            maker = maker or ty
            model = ty
        return {"maker": maker, "model": model}
    if kind in ("_airplay._tcp", "_raop._tcp", "_device-info._tcp"):
        code = txt.get("model") or txt.get("am")
        if _apple_model(code):
            return {"maker": "Apple", "model": _apple_model(code)}
        if kind != "_device-info._tcp" and code and not re.fullmatch(r"[A-Za-z]+\d+,\d+", code):
            return {"maker": txt.get("manufacturer"), "model": code}  # another maker's AirPlay speaker or TV
    if kind == "_companion-link._tcp":  # iPhones, iPads, Macs and Apple TVs: only Apple announces this
        return {"maker": "Apple", "model": _apple_model(txt.get("rpMd"))}
    if kind == "_apple-mobdev2._tcp":  # iPhones and iPads; the name comes from the host ("Juans-iPhone")
        return {"maker": "Apple"}
    return {}


def _unescape(text):
    """DNS-SD escapes: "\\032" (a decimal byte) and "\\x" (a literal character)."""
    return re.sub(r"\\(\d{3}|.)", lambda m: chr(int(m.group(1))) if m.group(1).isdigit() else m.group(1), text)


def _txt(field):
    """A TXT record as printed, '"ty=Brother HL" "txtvers=1"', as a dict."""
    out = {}
    for entry in re.findall(r'"((?:[^"\\]|\\.)*)"', field):
        key, eq, value = _unescape(entry).partition("=")
        if eq:
            out.setdefault(key, value)
    return out


def _watch(cmds, seconds):
    """Run listing commands that never end by themselves side by side for `seconds`, then stop them. Returns what
    each printed by then (at most 256 KB each)."""
    import select
    procs = []
    for cmd in cmds:
        try:
            procs.append(subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL))
        except OSError:
            pass
    got = {p.stdout: [] for p in procs}
    reading = list(got)
    deadline = time.monotonic() + seconds
    try:
        while reading:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            for f in select.select(reading, [], [], left)[0]:
                chunk = os.read(f.fileno(), 65536)
                got[f].append(chunk)
                if not chunk or sum(map(len, got[f])) > 256 * 1024:
                    reading.remove(f)
    except (OSError, ValueError):
        pass
    finally:
        for p in procs:
            try:
                p.kill()
                p.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
            p.stdout.close()
    return [b"".join(got[p.stdout]).decode("utf-8", "replace") for p in procs]


def _dns_sd_zone(text, kind):
    """[(host, kind, txt, instance name)] from `dns-sd -Z <kind>` output (zone-file lines: PTR, then SRV and TXT per
    instance)."""
    hosts, txts = {}, {}
    for line in text.splitlines():
        m = re.match(r"^(\S+)\s+(SRV|TXT)\s+(.*)$", line)
        if not m:
            continue
        if m.group(2) == "SRV":
            parts = m.group(3).split()
            if len(parts) >= 4:
                hosts[m.group(1)] = parts[3].rstrip(".")
        else:
            txts[m.group(1)] = _txt(m.group(3))
    return [(host, kind, txts.get(owner, {}), _unescape(owner[:-len(kind) - 1] if owner.endswith("." + kind) else ""))
            for owner, host in hosts.items()]


def _mdns_records(seconds=MDNS_SECONDS):
    """[(address, kind, txt, {"instance", "host"})] for services announced nearby, from the system's mDNS service (asked, not listened
    for). Takes at most twice `seconds`: on Linux avahi resolves the addresses itself; on a Mac the listings run for
    `seconds` and the host names are looked up in the time left."""
    out = []
    if shutil.which("avahi-browse"):
        for line in _run(["avahi-browse", "-aprtk"], timeout=max(1.0, 2 * seconds)).splitlines():
            f = line.split(";")
            if len(f) >= 9 and f[0] == "=" and f[2] == "IPv4" and f[4] in MDNS_ASK and _private_v4(f[7]):
                out.append((f[7], f[4], _txt(f[9]) if len(f) > 9 else {},
                            {"instance": _unescape(f[3]), "host": f[6]}))
        return out
    if sys.platform != "darwin" or not shutil.which("dns-sd"):
        return out
    deadline = time.monotonic() + 2 * seconds
    found = []
    for kind, text in zip(MDNS_ASK, _watch([["dns-sd", "-Z", k, "local"] for k in MDNS_ASK], seconds)):
        found += _dns_sd_zone(text, kind)
    addresses = {}
    for host in list(dict.fromkeys(f[0] for f in found))[:20]:
        left = deadline - time.monotonic()
        if left <= 0.2:
            break
        addresses[host] = _resolve(host, min(1.0, left))
    return [(addresses[h], k, t, {"instance": i, "host": h}) for h, k, t, i in found
            if _private_v4(addresses.get(h))]


def _upnp_about(data):
    """{maker, model, kind} as a UPnP description file announces them (raw: `_keep` decides what may leave). Only
    UTF-8 (or ASCII) files are read, and one with a DOCTYPE or ENTITY is refused (entities can make a few bytes expand
    without end): the check runs on the decoded text, so another encoding can't hide them. The friendlyName is a name
    someone gave it: it leaves only while the owner shows names (see `_seen_name`)."""
    import xml.etree.ElementTree as ET
    if not data or len(data) > DESCRIPTION_BYTES or data[:2] in (b"\xfe\xff", b"\xff\xfe") or b"\0" in data:
        return {}
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {}
    declared = re.match(r"\s*<\?xml[^>]*?encoding\s*=\s*[\"']([^\"']*)", text)
    if (declared and declared.group(1).lower() not in ("utf-8", "us-ascii", "ascii")) \
            or re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
        return {}
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except (ET.ParseError, ValueError):
        return {}
    device = next((e for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "device"), None)
    if device is None:
        return {}
    got = {}
    for child in device:
        key = child.tag.rsplit("}", 1)[-1]
        if key in ("manufacturer", "modelName", "modelNumber", "deviceType", "friendlyName") \
                and (child.text or "").strip():
            got[key] = child.text.strip()[:100]
    name, number = got.get("modelName", ""), got.get("modelNumber", "")
    models = [" ".join(x for x in (name, number if number not in name else "") if x), name, number]
    kind = next((w for t, w in UPNP_KIND if ":" + t + ":" in got.get("deviceType", "")), None)
    return {"maker": got.get("manufacturer"), "model": next((m for m in models if _product_code(m)), None),
            "kind": kind, "name": got.get("friendlyName")}


def _fetch(host, port, path, deadline):
    """The body of a plain HTTP GET, or b"" (an error, not 200, too big, or the deadline passed). Connecting,
    sending and every read are held to the one deadline; the connection is closed when it passes."""
    import socket as _s
    left = deadline - time.monotonic()
    if left <= 0.05:
        return b""
    data = b""
    try:
        with _s.create_connection((host, port), timeout=left) as sock:
            sock.sendall(("GET %s HTTP/1.0\r\nHost: %s:%d\r\nConnection: close\r\n\r\n" % (path, host, port)).encode())
            while len(data) <= DESCRIPTION_BYTES + 4096:
                left = deadline - time.monotonic()
                if left <= 0:
                    return b""  # out of time: what came so far is not used
                sock.settimeout(left)
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            else:
                return b""  # too big to be a description
    except (OSError, ValueError):
        return b""
    head, _sep, body = data.partition(b"\r\n\r\n")
    return body if re.match(rb"HTTP/1\.[01] 200 ", head) else b""


def _router_about(deadline):
    """(router address, {maker, model, kind}) from its UPnP description, tried at a few well-known places on the
    router only (plain outgoing requests, at most 1 s each); (None, {}) when there's no answer by `deadline`."""
    gateway = _gateway(timeout=max(0.1, min(5.0, deadline - time.monotonic())))
    if not _private_v4(gateway):
        return None, {}
    for port, path in UPNP_PLACES:
        if deadline - time.monotonic() <= 0.2:
            break
        about = _upnp_about(_fetch(gateway, port, path, min(deadline, time.monotonic() + 1.0)))
        if about.get("maker") or about.get("model"):
            return gateway, about
    return gateway, {}


def _keep(mine, about):
    """Keep the first maker and model that may leave the device: a known maker (as the table spells it) and a model
    from the Apple table or shaped like a product code. An unknown maker means neither is kept."""
    maker = _maker(about.get("maker"))
    if not maker:
        return
    model = about.get("model") if isinstance(about.get("model"), str) else ""
    if maker == "Apple":
        model = model if model in {w for _p, w in APPLE_MODELS} else None  # only ever from the table
    else:
        for prefix in (about.get("maker") or "", maker):  # "FUJI XEROX DocuPrint CP115" made by FUJI XEROX
            if prefix and model.lower().startswith(prefix.lower() + " "):
                model = model[len(prefix) + 1:]
        model = _product_code(model)
    if model and not mine.get("model"):
        mine["model"], mine["maker"] = model, maker
    elif not mine.get("maker"):
        mine["maker"] = maker


def _seen_name(text):
    """A name a thing announces ("Living Room", "Juans-MacBook-Pro"), as the owner would recognise it, or None. Sent
    only while the owner shows names (on by default; a switch in Settings). Never anything holding an address or a
    hardware id: a trailing "(1B:BE:CF)" is cut, and a name still holding one is dropped."""
    if not isinstance(text, str):
        return None
    text = re.sub(r"\s*\((?:[0-9A-Fa-f]{2}[:-]){2,5}[0-9A-Fa-f]{2}\)$", "", " ".join(text.split()))
    text = re.sub(r"(?i)\.local\.?$", "", text)
    if not text or not text.isprintable() or scrub(text)[0] != text \
            or re.search(r"\b[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){2,}\b|\d{1,3}[-.]\d{1,3}[-.]\d{1,3}[-.]\d{1,3}", text) \
            or any(re.search(r"\d", run) for run in re.findall(r"[0-9A-Fa-f]{6,}", text)):
        return None
    return text[:60].strip() or None


def _name_from(mine, text, rank):
    """Keep the best name seen: a Bonjour instance name (0), then a UPnP friendlyName (1), then a host name (2)."""
    name = _seen_name(text)
    if name and rank < mine.get("_rank", 9):
        mine["name"], mine["_rank"] = name, rank


def _identify(budget=IDENTIFY_BUDGET):
    """{address: {"services": set, "maker", "model"}} for things that say who made them. One deadline covers it all,
    from the mDNS listings to the last byte of the router's description; what doesn't fit is left out, and nothing
    here can fail the look."""
    deadline = time.monotonic() + budget
    out = {}
    try:
        for ip, kind, txt, *label in _hourly("mdns", lambda: _mdns_records(min(MDNS_SECONDS, budget / 3)),
                                             every=60):
            mine = out.setdefault(ip, {"services": set()})
            if kind in MDNS:
                mine["services"].add(MDNS[kind])
            _keep(mine, _txt_about(kind, txt))
            label = label[0] if label and isinstance(label[0], dict) else {}
            _name_from(mine, label.get("instance"), 0)
            _name_from(mine, label.get("host"), 2)
        router, about = _router_about(deadline)
        if about:
            mine = out.setdefault(router, {"services": set()})
            if about.get("kind"):
                mine["services"].add(about["kind"])
            _keep(mine, about)
            _name_from(mine, about.get("name"), 1)
    except Exception:  # makers and models are a nicety: they never cost the look
        pass
    for mine in out.values():
        mine.pop("_rank", None)
    return out


def discover(yes=False, quiet=False):
    """Look for other things on this network and send what is picked (all of them with `yes`), without addresses.
    Returns (sent, how many). `quiet`: run as a job from the app, nothing printed."""
    say = (lambda *_a, **_k: None) if quiet else print
    cfg = _load()
    about = _identify()  # first: whatever answers is then in the neighbour table too
    neigh, mdns = _neighbours(), _mdns()
    ips = set(neigh) | set(mdns) | {ip for ip in about if _private_v4(ip)}
    ports = _open_ports(ips)
    ips = _one_per_machine(ips, neigh, lambda ip: len(ports.get(ip, [])) + len(mdns.get(ip, ())) + len(about.get(ip) or {}))
    found = cfg.get("found") or {}
    known = {v.get("ip"): k for k, v in found.items()}  # same thing, same id as last time
    known_hw = {v["hw"]: k for k, v in found.items() if v.get("hw")}  # ... even at a new address
    items, local, elsewhere = [], {}, set()
    for ip in sorted(ips):
        vendor = _vendor(neigh.get(ip))
        told = about.get(ip) or {}
        services = sorted(mdns.get(ip, set()) | told.get("services", set()) | {PORTS[p] for p in ports.get(ip, [])})
        if not services and not vendor and not told.get("model"):
            continue  # nothing to say about it
        hw = hw_tag(cfg.get("netKey"), neigh.get(ip))  # the same thing after its address changes
        at_ip = known.get(ip)
        if at_ip and hw and found[at_ip].get("hw") not in (None, hw):
            elsewhere.add(at_ip)  # another machine has that address now: the old thing isn't here
            at_ip = None
        cid = (hw and known_hw.get(hw)) or at_ip or secrets_hex(6)
        items.append({"cid": cid, "guess": _guess(vendor, services, ports.get(ip, [])), "vendor": vendor,
                      "services": services[:8], "ports": sorted(ports.get(ip, []))[:8]})
        for k in ("maker", "model") + (("name",) if cfg.get("deviceNames") is True else ()):
            if told.get(k):
                items[-1][k] = told[k]
        tag = net_tag(cfg.get("netKey"), ip)  # lets the app match it (say, your router) to lines on the map
        if tag:
            items[-1]["tag"] = tag
        if hw:
            items[-1]["hw"] = hw
        before = found.get(cid) or {}
        seen = set(ports.get(ip, [])) | (set(before.get("ports") or []) if hw and before.get("hw") == hw else set())
        local[cid] = {"ip": ip, "ports": sorted(seen), **({"hw": hw} if hw else {})}  # a watch follows it when it moves
    if not items:
        say("Didn't find anything to suggest on this network.")
        if not quiet:
            return True, 0  # at a terminal nothing is sent unless picked
        items = []  # asked from the app: an empty list replaces what an earlier look found
    say(f"Found {len(items)} thing(s) nearby. Only what you pick is sent, without addresses:")
    for n, it in enumerate(items, 1):
        made = " ".join(x for x in (it.get("maker"), it.get("model")) if x) or it["vendor"]
        say(f"  {n}. {it['guess']}" + (f" - {made}" if made else "")
              + (f" ({', '.join(it['services'])})" if it["services"] else ""))
    if yes or quiet:
        chosen = items
    else:
        try:
            ans = input("Send which? (e.g. 1,3 or all; Enter = none): ").strip().lower()
        except EOFError:
            ans = ""
        if ans == "all":
            chosen = items
        else:
            nums = {int(x) for x in re.findall(r"\d+", ans)}
            chosen = [it for n, it in enumerate(items, 1) if n in nums]
    if not chosen and not quiet:
        say("Nothing sent.")
        return True, 0
    picked = {it["cid"]: local[it["cid"]] for it in chosen}
    moved = {cid: {**found[cid], "ip": None} for cid in elsewhere - set(local)}  # its watch says "not reachable"
    _update_config(lambda c: c.__setitem__("found", {**(c.get("found") or {}), **moved, **picked}))
    st, body = _post(check_api(cfg["api"]) + "/helper/discoveries", {"items": chosen[:30]},
                     {"X-Device-Token": cfg["token"]})
    say(f"Sent {len(chosen)}. Open Nightlight to add them to your map." if st == 200
        else f"Couldn't send ({st or 'network error'}).")
    return st == 200, len(chosen[:30])


def secrets_hex(n):
    return os.urandom(n).hex()


def _watch_results():
    """Check the found devices the owner added ("watched by this device"): can we still reach their service?"""
    import socket as _s
    try:
        cfg = _load()
    except (OSError, ValueError):
        return []
    found, out = cfg.get("found") or {}, []
    for w in (cfg.get("watch") or [])[:10]:
        target = found.get(w.get("cid")) if isinstance(w.get("cid"), str) else None
        port = w.get("port")
        if not target or type(port) is not int or port not in PORTS or port not in target.get("ports", []):
            continue  # only a port this device saw open on that thing, from the fixed list
        if not target.get("ip"):
            out.append({"cid": w["cid"], "up": False, "ms": None})  # not at its old address any more
            continue
        t = time.time()
        try:
            with _s.create_connection((target["ip"], port), timeout=1):
                out.append({"cid": w["cid"], "up": True, "ms": int((time.time() - t) * 1000)})
        except OSError:
            out.append({"cid": w["cid"], "up": False, "ms": None})
    return out


# ------------------------------------------------------------------ lines on the map, without addresses
# Which of your devices rely on each other, told without any address leaving this one. Each private IPv4 address
# (10/8, 172.16/12, 192.168/16) is replaced by a keyed fingerprint: HMAC-SHA256 with your account's own key (sent only
# to your account's helpers), first 20 hex characters. Your devices give the same address the same fingerprint, so the
# app can match "this Mac backs up to that NAS" without learning either address. Link-local (169.254/16), shared or
# public addresses are left out: they say nothing stable about your own network.

NET_PORTS = (445, 2049, 548, 873, 5432, 3306, 1883, 8123, 32400, 9000)  # services others rely on; never SSH (22)
NET_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
NET_EVERY = 1800  # what this device relies on is looked up at most every 30 minutes
_PRIVATE = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")


def _private_v4(ip):
    import ipaddress
    try:
        a = ipaddress.IPv4Address(ip if isinstance(ip, str) else "")
    except ValueError:
        return False
    return any(a in ipaddress.IPv4Network(n) for n in _PRIVATE)


def net_tag(key, ip):
    """The keyed fingerprint of a private IPv4 address, or None for anything else."""
    import hashlib
    import hmac
    if not _private_v4(ip) or not isinstance(key, str) or not NET_KEY_RE.fullmatch(key):
        return None
    return hmac.new(bytes.fromhex(key), ip.encode(), hashlib.sha256).hexdigest()[:20]


def hw_tag(key, mac):
    """The keyed fingerprint of a hardware (MAC) address, or None. It stays the same when the router hands the thing
    a new IP address; a phone's private Wi-Fi address is usually fixed per network. Never the address itself."""
    import hashlib
    import hmac
    if not isinstance(mac, str) or not re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac) or int(mac[:2], 16) & 1 \
            or mac == "00:00:00:00:00:00" or not isinstance(key, str) or not NET_KEY_RE.fullmatch(key):
        return None
    return hmac.new(bytes.fromhex(key), b"hw:" + mac.encode(), hashlib.sha256).hexdigest()[:20]


def _one_per_machine(ips, neigh, score):
    """One address per hardware address: the neighbour table can still hold a thing's old addresses after the router
    gave it a new one. Keeps the address that says the most (then the lowest, so it is stable)."""
    best = {}
    for ip in sorted(ips):
        mac = neigh.get(ip)
        if not mac:
            best[ip] = ip
        elif mac not in best or score(ip) > score(best[mac]):
            best[mac] = ip
    return set(best.values())


def _own_ip():
    """This device's address on the local network: the one it would use to reach the internet (a UDP "connect" only
    picks the route; no packet is sent)."""
    import socket as _s
    s = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


SELVES = 8  # own addresses reported at most (Wi-Fi, cable, Docker bridges, VPNs...)


def _own_ips(timeout=3):
    """Every private IPv4 address of this device, on every interface, the main one first: `ip` or /proc/net/fib_trie
    on Linux, `ifconfig` on a Mac. Found nearby leaves out what is really one of your own devices."""
    found = []
    if sys.platform == "darwin":
        found = re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)", _run(["ifconfig"], timeout=timeout))
    else:
        found = re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)/", _run(["ip", "-4", "-o", "addr"], timeout=timeout)
                           if shutil.which("ip") else "")
        if not found:
            try:
                with open("/proc/net/fib_trie") as f:
                    lines = f.read().splitlines()
                found = [lines[i - 1].split()[-1] for i, ln in enumerate(lines)
                         if i and ln.strip() == "/32 host LOCAL" and lines[i - 1].split()]
            except OSError:
                pass
    main = _own_ip()
    return [ip for ip in dict.fromkeys([main] + found) if _private_v4(ip)][:SELVES]


def _hex_v4(h):
    """An IPv4 address as /proc/net prints it (hex, in this machine's byte order)."""
    import socket as _s
    import struct
    return _s.inet_ntoa(struct.pack("=I", int(h, 16)))


def _gateway(timeout=5):
    try:
        with open("/proc/net/route") as f:
            for line in f.read().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[1] == "00000000" and int(parts[3], 16) & 2:  # default route, via a gateway
                    return _hex_v4(parts[2])
        return None
    except (OSError, ValueError):
        pass
    if sys.platform == "darwin":
        m = re.search(r"gateway:\s*([\d.]+)", _run(["route", "-n", "get", "default"], timeout=timeout))
        return m.group(1) if m else None
    return None


def _resolve(host, timeout=3):
    """A host name to an IPv4 address, here on the device; None if it doesn't resolve in time."""
    import socket as _s
    import threading
    if _private_v4(host):
        return host
    got = []
    t = threading.Thread(target=lambda: got.append(_s.gethostbyname(host)), daemon=True)  # no timeout of its own
    t.start()
    t.join(timeout)
    return got[0] if got else None


def _mount_host(source):
    """The server's name in a network mount source: //user@nas.local/share, nas:/export, afp_x@nas._afpovertcp..."""
    if source.startswith("//"):
        host = source[2:].split("/", 1)[0].rsplit("@", 1)[-1]
    elif ":" in source:
        host = source.split(":", 1)[0]
    else:
        return None
    host = urllib.parse.unquote(host).split(":")[0]
    return re.sub(r"\._[a-z-]+\._tcp(\.local)?\.?$", ".local", host).rstrip(".") or None


def _time_machine_hosts(timeout=5):
    if sys.platform != "darwin" or not shutil.which("tmutil"):
        return []
    urls = re.findall(r"^URL\s*:\s*(\S+)", _run(["tmutil", "destinationinfo"], timeout=timeout), re.M)
    return [h for h in (_mount_host("//" + u.split("://", 1)[-1]) for u in urls) if h]


def _drive_hosts(timeout=5):
    if sys.platform == "darwin":
        lines = [m.group(1) for m in (re.match(r"^(\S+) on .+ \((smbfs|afpfs|nfs|webdav)\b", ln)
                                      for ln in _run(["mount"], timeout=timeout).splitlines()) if m]
    else:
        try:
            with open("/proc/mounts") as f:
                lines = [p[0] for p in (ln.split() for ln in f)
                         if len(p) > 2 and p[2] in ("nfs", "nfs4", "cifs", "smb3")]
        except OSError:
            lines = []
    return [h for h in map(_mount_host, lines) if h]


def _connections(timeout=5):
    """(remote address, port) of established TCP connections from here to a known service port."""
    out = []
    try:
        with open("/proc/net/tcp") as f:
            for line in f.read().splitlines()[1:]:
                parts = line.split()
                if len(parts) > 3 and parts[3] == "01":  # ESTABLISHED
                    ip, port = parts[2].split(":")
                    out.append((_hex_v4(ip), int(port, 16)))
    except (OSError, ValueError):
        for line in _run(["netstat", "-an", "-p", "tcp"], timeout=timeout).splitlines():
            parts = line.split()  # tcp4  0  0  192.168.1.5.51234  192.168.1.10.5432  ESTABLISHED
            if len(parts) >= 6 and parts[0] == "tcp4" and parts[5] == "ESTABLISHED" and "." in parts[4]:
                ip, port = parts[4].rsplit(".", 1)
                if port.isdigit():
                    out.append((ip, int(port)))
    return [(ip, port) for ip, port in out if port in NET_PORTS]


NET_BUDGET = 10  # seconds for the whole look (commands and name lookups); a report never waits longer for it
NET_HOSTS = 8  # names looked up per kind: duplicates go first, then the list is cut


def _relied_on(budget=NET_BUDGET):
    """[(address, why)]: where this device backs up to, whose shared folders it mounts, which services it uses. One
    deadline covers everything; what didn't fit in it is simply left out of this report."""
    deadline = time.monotonic() + budget

    def resolved(hosts, why):
        out = []
        for host in list(dict.fromkeys(hosts))[:NET_HOSTS]:
            left = deadline - time.monotonic()
            if left <= 0.2:
                break
            ip = _resolve(host, min(3, left))
            if ip:
                out.append((ip, why))
        return out

    def left():  # what a command may still take: the shared deadline, never more than 5 s
        return max(0.5, min(5.0, deadline - time.monotonic()))

    found = []
    for step in (lambda: [(ip, "service:%d" % port) for ip, port in _connections(left())],
                 lambda: resolved(_time_machine_hosts(left()), "time_machine"),
                 lambda: resolved(_drive_hosts(left()), "network_drive")):
        if deadline - time.monotonic() <= 0.5:
            break
        try:
            found += [(ip, why) for ip, why in step() if ip]
        except Exception:  # one probe failing never hides the others
            pass
    return found


def _net():
    """What the app needs to draw lines between your devices, as fingerprints; None before the key arrived."""
    try:
        key = _load().get("netKey")
        if not isinstance(key, str) or not NET_KEY_RE.fullmatch(key):
            return None
        me = net_tag(key, _own_ip())
        selves = [t for t in dict.fromkeys(net_tag(key, ip) for ip in _hourly("selves", _own_ips, every=300)) if t]
        peers, seen = [], set()
        for ip, why in _hourly("net", _relied_on, every=NET_EVERY):
            tag = net_tag(key, ip)
            if tag and tag != me and tag not in selves and (tag, why) not in seen and len(peers) < 20:
                seen.add((tag, why))
                peers.append({"tag": tag, "why": why})
        return {"self": me, "selves": selves[:SELVES], "gateway": net_tag(key, _gateway()), "peers": peers}
    except Exception:  # never let this cost a report
        return None


# ------------------------------------------------------------------ running in the background

APP_DIR = (os.path.expanduser("~/Library/Application Support/Nightlight") if sys.platform == "darwin"
           else os.path.expanduser("~/.local/share/nightlight"))
UNIT = "/etc/systemd/system/nightlight-helper.service"
PKG_DIR = "/Library/Application Support/Nightlight"  # Nightlight.pkg's own Python and helper, shared by every user
PKG_ID = "com.nightlight.installer"
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.nightlight.helper.plist")
LABEL = "com.nightlight.helper"


def _sudo(cmd):
    return cmd if os.geteuid() == 0 else ["sudo", *cmd]


def _own_dir(path):
    """A real directory owned by this user (never through a symlink), created 0700 if missing."""
    if os.path.islink(path):
        sys.exit(f"Refusing to use {path}: it is a symbolic link.")
    os.makedirs(path, mode=0o700, exist_ok=True)
    if os.stat(path).st_uid != os.getuid():
        sys.exit(f"Refusing to use {path}: it belongs to another user.")
    return path


def _copy_self():
    target = os.path.join(_own_dir(APP_DIR), "nightlight_helper.py")
    if os.path.abspath(__file__) != target:
        fd, tmp = tempfile.mkstemp(dir=APP_DIR, prefix=".helper-", suffix=".py")
        with os.fdopen(fd, "wb") as out, open(os.path.abspath(__file__), "rb") as src:
            out.write(src.read())
        os.chmod(tmp, 0o700)
        os.replace(tmp, target)  # replaces the entry itself; never writes through a symlink
    return target


def _systemd_value(v):
    """Quote a value for a unit file; refuse characters systemd would expand or that could break the line."""
    if re.search(r'[\x00-\x1f\x7f%$"\\]', v):
        sys.exit(f"Unsupported character in path {v!r}; please install from a simpler folder.")
    return '"' + v + '"'


def _me():
    """This process's own user, from the OS (not from environment variables)."""
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def _unit_is_mine():
    """Our service file: it carries this user's owner mark, or (installed by helper 0.3.0, before the mark) runs this
    user's own helper copy as this user."""
    text = _read(UNIT)
    legacy = f"User={_me()}\n" in text and os.path.join(APP_DIR, "nightlight_helper.py") in text
    return f"# nightlight-owner={os.getuid()}" in text or legacy


def install(every=60, manage=None):
    """Run the helper in the background from now on (and after restarts). Needs the device to be joined first.
    `manage` ("app" or "strict") answers the permissions question without a terminal (the Mac installer)."""
    try:
        _load()
    except (OSError, ValueError):
        sys.exit("Join first: run enrol (with a code from the app) or pair.")
    cfg = _load()
    if cfg.get("manage") not in ("app", "strict"):
        interactive = sys.stdin.isatty()
        app = manage == "app" if manage else interactive and _ask(
            "Let the Nightlight app manage what it may do on this device? You'll switch things on and off in the app; "
            "every restart still asks you first. (n = strict: changes only on this device)", True)
        _update_config(lambda c: c.setdefault("manage", "app" if app else "strict"))
        print("Managed from the app." if app else "Strict: change permissions here with `nightlight settings`.")
    # The one moment someone is at this Mac's terminal: settle macOS's folder prompts now, not in a later visit.
    # Without a terminal (the Mac installer) nothing is recorded: still not asked, so it can be offered later, and
    # until then the private folders are never read.
    if sys.platform == "darwin" and sys.stdin.isatty() and "macPrivateFolders" not in _load():
        _ask_mac_private(True)
    # The Python running this install also runs the service: from the Mac installer that is its own bundled Python,
    # which signed updates leave in place (they replace only the helper file and restart with this same Python).
    script, py, home = _copy_self(), os.path.realpath(sys.executable), os.path.abspath(CONFIG_DIR)
    _link_command(script, py)
    every = max(int(every), 30)
    if sys.platform == "darwin":
        import plistlib
        agents = os.path.dirname(PLIST)
        if os.path.islink(agents) or (os.path.exists(agents) and os.stat(agents).st_uid != os.getuid()):
            sys.exit(f"Refusing to use {agents}: it is a link or belongs to another user.")
        os.makedirs(agents, exist_ok=True)
        logs = os.path.expanduser("~/Library/Logs/nightlight-helper.log")
        fd, tmp = tempfile.mkstemp(dir=agents, prefix=".nightlight-", suffix=".plist")
        with os.fdopen(fd, "wb") as f:
            plistlib.dump({"Label": LABEL, "ProgramArguments": [py, script, "run", "--every", str(every)],
                           "EnvironmentVariables": {"NIGHTLIGHT_HOME": home}, "RunAtLoad": True,
                           "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": 30,
                           "StandardOutPath": logs, "StandardErrorPath": logs}, f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, PLIST)  # replaces the entry itself, never writes through a link
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, PLIST], capture_output=True, check=False)
        subprocess.run(["launchctl", "bootstrap", domain, PLIST], check=True)
        print("Installed. Nightlight now runs in the background whenever you're logged in to this Mac.")
        return
    if not shutil.which("systemctl"):
        sys.exit("This system has no systemd. Keep `python3 nightlight_helper.py run` running another way.")
    if os.geteuid() == 0:
        sys.exit("Run install as your normal user (not with sudo); it asks for your password when it needs it.")
    if os.path.exists(UNIT) and not _unit_is_mine():
        sys.exit("Another user's Nightlight helper is installed on this machine; uninstall it there first.")
    q = _systemd_value
    unit = (
        f"# nightlight-owner={os.getuid()}\n"
        "[Unit]\nDescription=Nightlight helper (reports health; runs only jobs you allow)\n"
        "Wants=network-online.target\nAfter=network-online.target\n\n"
        f"[Service]\nUser={_me()}\nEnvironment={q('NIGHTLIGHT_HOME=' + home)}\n"
        f"ExecStart={q(py)} {q(script)} run --every {every}\n"
        "Restart=on-failure\nRestartSec=30\nNoNewPrivileges=yes\n\n[Install]\nWantedBy=multi-user.target\n")
    fd, tmp = tempfile.mkstemp(suffix=".service")
    with os.fdopen(fd, "w") as f:
        f.write(unit)
    print("Setting up the background service (your password may be asked once)...")
    try:
        subprocess.run(_sudo(["install", "-m", "0644", tmp, UNIT]), check=True)
    finally:
        os.unlink(tmp)
    subprocess.run(_sudo(["systemctl", "daemon-reload"]), check=True)
    subprocess.run(_sudo(["systemctl", "enable", "--now", "nightlight-helper.service"]), check=True)
    subprocess.run(_sudo(["systemctl", "restart", "nightlight-helper.service"]), check=True)  # picks up an update
    print("Installed. Nightlight now runs in the background, also after restarts.")


def uninstall():
    """Stop and remove everything this helper installed, and tell Nightlight this device has left."""
    try:
        cfg = _load()
        st, _ = _post(check_api(cfg["api"]) + "/helper/leave", {}, {"X-Device-Token": cfg["token"]})
        print("Nightlight was told this device left." if st == 200 else "Couldn't reach Nightlight; remove the "
              "device in the app too.")
    except (OSError, ValueError, KeyError):
        pass
    if sys.platform == "darwin":
        if os.path.exists(PLIST):
            r = subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", PLIST], capture_output=True, check=False)
            loaded = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True,
                                    check=False).returncode == 0
            if r.returncode != 0 and loaded:
                sys.exit("Couldn't stop the background service; nothing was removed. Try again or restart first.")
            os.unlink(PLIST)
    elif os.path.exists(UNIT):
        if not _unit_is_mine():
            sys.exit("The installed service belongs to another user on this machine; nothing was removed.")
        stop = subprocess.run(_sudo(["systemctl", "disable", "--now", "nightlight-helper.service"]), check=False)
        if stop.returncode != 0:
            sys.exit("Couldn't stop the background service; nothing was removed. Try again.")
        subprocess.run(_sudo(["rm", "-f", UNIT]), check=True)
        subprocess.run(_sudo(["systemctl", "daemon-reload"]), check=False)
    for d in (APP_DIR, CONFIG_DIR):
        if os.path.islink(d) or (os.path.isdir(d) and os.stat(d).st_uid != os.getuid()):
            sys.exit(f"Refusing to clean {d}: it is a link or belongs to another user. The service is stopped.")
    short = os.path.expanduser("~/.local/bin/nightlight")
    if _is_our_wrapper(short) and not os.path.islink(os.path.dirname(short)):
        os.unlink(short)  # only our own managed script
    for path in (os.path.join(APP_DIR, "nightlight_helper.py"), CONFIG):
        if os.path.isfile(path) and not os.path.islink(path):
            os.unlink(path)
    for d in (APP_DIR, CONFIG_DIR):
        try:
            os.rmdir(d)  # only if empty: never removes anything we didn't put there
        except OSError:
            pass
    print("Uninstalled. Nothing of Nightlight is left running on this device.")
    _pkg_leftovers()


def _pkg_leftovers():
    """Nightlight.pkg's shared folder needs an administrator to remove: removed when run as root, otherwise say how."""
    if sys.platform != "darwin" or not os.path.isdir(PKG_DIR) or os.path.islink(PKG_DIR):
        return
    if os.geteuid() == 0:
        shutil.rmtree(PKG_DIR)
        subprocess.run(["pkgutil", "--forget", PKG_ID], capture_output=True, check=False)
        print(f"Removed the Mac installer's files ({PKG_DIR}).")
        return
    print(f"The Mac installer's files are still in {PKG_DIR} (its own Python; nothing runs from it now). If nobody "
          f"else on this Mac uses Nightlight, remove them with:\n  sudo rm -rf '{PKG_DIR}' && sudo pkgutil --forget "
          f"{PKG_ID}")


def _sudo_ok():
    if os.geteuid() == 0:
        return True
    try:
        return subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=10, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def remove_from_app():
    """The owner removed this device in the app (approved). Tell Nightlight first (that closes the card and archives
    the device), then delete this helper's files, then its service definition, and stop the service last: stopping
    it ends this very process. Where the service can't be removed without a password (Linux without password-free
    sudo), a dormant stub stays and says how to finish; it never runs again. Returns (ok, summary) when it is still
    alive afterwards."""
    cfg = _load()
    linux_full = sys.platform == "darwin" or not os.path.exists(UNIT) or (_unit_is_mine() and _sudo_ok())
    try:
        _post(check_api(cfg["api"]) + "/helper/leave", {"cleanup": "full" if linux_full else "files_left"},
              {"X-Device-Token": cfg["token"]})
    except (OSError, ValueError, KeyError):
        pass
    short = os.path.expanduser("~/.local/bin/nightlight")
    if _is_our_wrapper(short) and not os.path.islink(os.path.dirname(short)):
        os.unlink(short)
    if not linux_full:  # keep the program (the service still points at it) but forget the key: it exits at once
        _save_config({"removed": True})
        return True, "Removed from Nightlight. The background service needs an administrator to remove it: run " \
                     "the uninstall line from the Nightlight app (ask \"how do I uninstall the helper\") on the device."
    for path in (os.path.join(APP_DIR, "nightlight_helper.py"), os.path.join(APP_DIR, "nightlight_helper.prev.py"),
                 os.path.join(APP_DIR, ".update.lock"), CONFIG):
        if os.path.isfile(path) and not os.path.islink(path):
            os.unlink(path)
    for d in (APP_DIR, CONFIG_DIR):
        try:
            os.rmdir(d)
        except OSError:
            pass
    if sys.platform == "darwin":
        if os.path.exists(PLIST) and not os.path.islink(PLIST):
            os.unlink(PLIST)
        sys.stdout.flush()
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, check=False)
    elif os.path.exists(UNIT):
        subprocess.run(_as_root(["systemctl", "disable", "nightlight-helper.service"]), capture_output=True,
                       check=False)
        subprocess.run(_as_root(["rm", "-f", UNIT]), capture_output=True, check=False)
        subprocess.run(_as_root(["systemctl", "daemon-reload"]), capture_output=True, check=False)
        sys.stdout.flush()
        subprocess.run(_as_root(["systemctl", "stop", "nightlight-helper.service"]), capture_output=True, check=False)
    return True, "Removed: the helper uninstalled itself."


WRAPPER_MARK = "# nightlight-helper wrapper (managed; safe to delete with `nightlight uninstall`)"


def _is_our_wrapper(path):
    """Ours only if it's a regular file we own whose second line is exactly our mark."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    lines = _read(path).splitlines()
    return stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and len(lines) == 3 and lines[1] == WRAPPER_MARK


def _link_command(script, py):
    """A short `nightlight` command in ~/.local/bin (a two-line script; nothing else on the system changes)."""
    bindir = os.path.expanduser("~/.local/bin")
    try:
        _own_dir(bindir)
        target = os.path.join(bindir, "nightlight")
        if os.path.islink(target) or (os.path.exists(target) and not _is_our_wrapper(target)):
            return  # something else lives there: leave it alone
        import shlex
        fd, tmp = tempfile.mkstemp(dir=bindir, prefix=".nightlight-")
        with os.fdopen(fd, "w") as f:
            f.write(f"#!/bin/sh\n{WRAPPER_MARK}\nexec {shlex.quote(py)} {shlex.quote(script)} \"$@\"\n")
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)
        if bindir not in os.environ.get("PATH", "").split(os.pathsep):
            shell_rc = "~/.zshrc" if os.environ.get("SHELL", "").endswith("zsh") else "~/.bashrc"
            print(f"The `nightlight` command is in {bindir}, which isn't on your PATH yet. Use "
                  f"`~/.local/bin/nightlight status`, or add it once:\n"
                  f"  echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> {shell_rc} && exec $SHELL")
    except (OSError, SystemExit):
        pass


def status():
    try:
        cfg = _load()
    except (OSError, ValueError):
        print("Not joined yet. Add this device from the Nightlight app.")
        return
    mode = {"app": "managed from the Nightlight app", "strict": "strict (changes only on this device)"}.get(
        cfg.get("manage"), "not chosen yet (run install)")
    seen = cfg.get("lastReport") or {}
    print(f"Nightlight helper {VERSION}")
    print(f"  Connected to:   {cfg.get('api')}")
    print(f"  This device:    {cfg.get('deviceName') or '?'} ({cfg.get('deviceId')})")
    print(f"  Owner account:  {cfg.get('ownerHint') or 'shown after the next report'}")
    print(f"  Last report:    {seen.get('at', 'none yet')} ({seen.get('result', '-')})")
    print(f"  Permissions:    {mode}")
    if sys.platform == "darwin":
        out = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, text=True)
        print("Background service: " + ("running" if "state = running" in out.stdout else
                                         "installed, not running" if out.returncode == 0 else "not installed"))
    elif shutil.which("systemctl"):
        out = _run(["systemctl", "is-active", "nightlight-helper.service"]).strip()
        print(f"Background service: {out or 'not installed'}")
    allowed = _allowed()
    words = {"diagnose": "check why it stopped", "logs": "read recent log lines", "restart_container": "restart",
             "restart_service": "restart the service", "inspect": "look around (reads only)",
             "fix": "clean up space after you approve", "update": "install signed updates from the app",
             "expert": "run commands you sign with your passkey"}
    print("  Nightlight may: " + ("; ".join(f"{words.get(k, k)}: {', '.join(v)}" for k, v in allowed.items())
                                  or "nothing yet"))


def _ask_mac_private(default_yes):
    """Ask (in a terminal, with someone there) whether the Mac's private folders may be measured, and raise macOS's
    own Allow prompts right away, so nobody has to come back to the terminal for this later."""
    if _ask("Let Nightlight measure Downloads, Desktop, Documents, Movies and the Trash (sizes only)? macOS will "
            "ask you to allow each one now; click Allow.", default_yes):
        _allow_mac_private()
    else:
        _update_config(lambda c: c.__setitem__("macPrivateFolders", False))  # a recorded no: not asked again


def _allow_mac_private():
    """Record the yes, then measure the private folders once so macOS raises its Allow prompts now. The yes comes
    first: the privacy guard reads it, so only then can the folders be opened, while someone is there to answer."""
    _update_config(lambda c: c.__setitem__("macPrivateFolders", True))
    _inspect_until[0] = time.time() + 120
    for _label, path in _mac_private_places():
        _du(path)


def settings():
    """Change, on this device, whether the app manages permissions, and (strict mode) what is allowed."""
    if not sys.stdin.isatty():
        sys.exit("Run `nightlight settings` in a terminal: it asks before changing anything.")
    cfg = _load()
    print(f"Permissions are now {'managed from the app' if cfg.get('manage') == 'app' else 'strict'}.")
    if sys.platform == "darwin":
        _ask_mac_private(cfg.get("macPrivateFolders") is True)
    app = _ask("Let the Nightlight app manage what it may do on this device?", cfg.get("manage") == "app")
    cfg["manage"] = "app" if app else "strict"
    if not app:
        targets = [c["name"] for c in _containers()] + _failed_units()
        allow = {k: [] for k in JOB_TYPES}
        if _ask("May Nightlight check why something stopped and look around (reads only: disk use, programs, "
                "updates, network)?", True):
            allow["diagnose"] = [t for t in targets if TARGET_RE.fullmatch(t)][:20]
            allow["inspect"] = ["all"]
        if _ask("May you install signed Nightlight updates from the app (each one checked against Nightlight's key)?",
                True):
            allow["update"] = ["all"]
        if _ask("May Nightlight clean up space after you approve each time (empty the Trash, clear caches that "
                "rebuild themselves, remove unused Docker images)?", False):
            allow["fix"] = ["all"]
        for t in targets[:20]:
            if _ask(f"  Read recent log lines of {t}?", False):
                allow["logs"].append(t)
            kind = "restart_container" if t in [c["name"] for c in _containers()] else "restart_service"
            if _ask(f"  Restart {t} when it has stopped (after you approve)?", False):
                allow[kind].append(t)
        cfg["allow"] = {k: v for k, v in allow.items() if v}
    chosen = {k: cfg[k] for k in ("manage", "allow") if k in cfg}
    _update_config(lambda c: c.update(chosen))
    print("Saved.")
    report_now()


def main():
    try:  # the background service writes to a log file: one line at a time, so the log shows what happened
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(description="Nightlight helper")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enrol")
    e.add_argument("api")
    e.add_argument("code")
    e.add_argument("--name", default=None)
    pa = sub.add_parser("pair")
    pa.add_argument("api")
    pa.add_argument("--web", default=None)
    pa.add_argument("--name", default=None)
    pa.add_argument("--browser", action="store_true", help="open the approval page in the browser (Mac installer)")
    pa.add_argument("--install", action="store_true", help="install the background service once approved")
    ins = sub.add_parser("install")
    ins.add_argument("--every", type=int, default=60)
    sub.add_parser("uninstall")
    sub.add_parser("status")
    sub.add_parser("settings")
    sub.add_parser("version")
    ex = sub.add_parser("expert", help="switch expert sessions on (pin your passkey) or off, at this device")
    ex.add_argument("--off", action="store_true")
    sub.add_parser("rollback", help="go back to the version before the last update")
    sub.add_parser("joined", help="exit 0 if this device is already joined (used by the installer)")
    dsc = sub.add_parser("discover")
    dsc.add_argument("--yes", action="store_true", help="send everything found without asking")
    sub.add_parser("once")
    sub.add_parser("show")
    for verb in ("allow", "disallow"):
        x = sub.add_parser(verb)
        x.add_argument("kind")
        x.add_argument("target")
    r = sub.add_parser("run")
    r.add_argument("--every", type=int, default=60)
    a = p.parse_args()
    if a.cmd == "enrol":
        enrol(a.api, a.code, (a.name or default_name())[:40])
    elif a.cmd == "pair":
        pair(a.api, a.web, a.name, a.browser, a.install)
    elif a.cmd == "install":
        install(a.every)
    elif a.cmd == "uninstall":
        uninstall()
    elif a.cmd == "status":
        status()
    elif a.cmd == "version":
        print(VERSION)
    elif a.cmd == "expert":
        expert_setup(a.off)
    elif a.cmd == "rollback":
        rollback()
    elif a.cmd == "settings":
        settings()
    elif a.cmd == "joined":
        try:
            sys.exit(0 if _load().get("token") else 1)
        except (OSError, ValueError):
            sys.exit(1)
    elif a.cmd == "discover":
        discover(a.yes)
    elif a.cmd == "once":
        once()
    elif a.cmd in ("allow", "disallow"):
        set_allowed(a.kind, a.target, a.cmd == "allow")
    elif a.cmd == "show":
        print(json.dumps(facts(), indent=2))
    else:
        run(max(a.every, 30))


if __name__ == "__main__":
    main()
