#!/usr/bin/env python3
"""Nightlight helper: reports a device's health to Nightlight, and runs only the jobs you allow on this machine.

Every report carries: OS name, CPU architecture, CPU / memory / disk percentages, uptime, Docker containers (name,
image name and tag without any registry address or path, state, status text), the names of failed system services
(and, on a Mac, of your own failing background items), how many software updates are waiting, two yes/no safety
facts (administrator commands without a password; SSH password logins), what you allowed here, and up/down results
for things you chose to have it watch. It never sends host names, IP or hardware addresses, files, environment
variables or passwords. Log lines leave only for a container or service you allowed with `allow logs NAME`, and are
scrubbed here first. It talks only HTTPS to the address you joined with.

By default it changes nothing. You can allow, per target and on this machine only: restarting a stopped Docker
container, restarting a failed system service, and reading why something is down. Even then a change runs only
after you approve its card in the app; Nightlight sends a job name and target, never a command.

Usage:
  nightlight_helper.py enrol <API_URL> <CODE> [--name NAME]   # join with a one-time code from the app
  nightlight_helper.py pair <API_URL> [--web URL]              # or: show a code to approve in the app / by phone
  nightlight_helper.py install | uninstall | status            # run in the background (systemd / launchd)
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

VERSION = "0.6.0"
CONFIG_DIR = os.environ.get("NIGHTLIGHT_HOME", os.path.join(os.path.expanduser("~"), ".config", "nightlight"))
CONFIG = os.path.join(CONFIG_DIR, "helper.json")
JOB_TYPES = ("restart_container", "restart_service", "diagnose", "logs")
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


def _failed_units():
    if not shutil.which("systemctl"):
        return []
    out = _run(["systemctl", "--failed", "--plain", "--no-legend", "--no-pager"])
    return [line.split()[0][:128] for line in out.splitlines() if line.strip()][:50]


_SLOW = {}  # slow checks are re-run at most hourly


def _hourly(key, fn):
    hit = _SLOW.get(key)
    if hit and time.time() - hit[0] < 3600:
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


def _failed_agents():
    """macOS: your own background items (not Apple's) whose last run failed."""
    if sys.platform != "darwin" or not shutil.which("launchctl"):
        return []
    out = []
    for line in _run(["launchctl", "list"]).splitlines()[1:]:
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
    return {"helperVersion": VERSION, "os": _os_name(), "arch": platform.machine()[:16], "cpuPct": cpu,
            "memPct": mem, "diskPct": _disk(), "uptimeSec": up, "containers": _containers(),
            "failedUnits": _failed_units(), "updatesPending": _updates_pending(), "allowedJobs": _allowed(),
            "watchResults": _watch_results(), "failedAgents": _failed_agents(),
            "safety": {"passwordlessSudo": _hourly("sudo", _passwordless_sudo),
                       "sshPasswordLogin": _ssh_password_login()}}


def _allowed():
    """What the owner allowed on this machine (from the local config; the server can't change it)."""
    try:
        allow = _load().get("allow") or {}
    except (OSError, ValueError):
        return {}
    return {k: [n for n in v if _name_re(k).fullmatch(n)][:20] for k, v in allow.items() if k in JOB_TYPES and v}


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
    if not _name_re(kind).fullmatch(name):
        sys.exit("That isn't a valid name.")
    cfg = _load()
    names = set((cfg.get("allow") or {}).get(kind, []))
    names = names | {name} if on else names - {name}
    cfg["allow"] = {**(cfg.get("allow") or {}), kind: sorted(names)}
    _save_config(cfg)
    print(("Allowed" if on else "No longer allowed") + f": {kind} {name}")


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


def run_job(job, wait=5):
    """Run one approved job, only if it is a known kind on a target the owner allowed here. Returns
    (ok, summary, state). Commands are fixed argument lists; nothing from the server reaches a shell."""
    kind, params = job.get("type"), job.get("params")
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


def once():
    cfg = _load()
    api = check_api(cfg["api"])
    status, body = _post(api + "/helper/heartbeat", facts(), {"X-Device-Token": cfg["token"]})
    if status == 200 and body.get("ok") is not True:
        status = 0  # a 200 without our acknowledgment is a protocol error, not a delivered report
        body = {"error": body.get("error") or "unexpected response"}
    if status == 200:
        print(f"Report sent: {body.get('findings', 0)} finding(s).")
        poll = body.get("pollEverySec")
        _POLL["every"] = poll if isinstance(poll, int) and 0 < poll <= 60 else 0
        watch = body.get("watch")
        if isinstance(watch, list) and watch != cfg.get("watch"):
            cfg["watch"] = [w for w in watch if isinstance(w, dict)][:10]
            _save_config(cfg)  # what to check next time (the owner's choices; addresses stay local)
        jobs = body.get("jobs")
        for job in jobs if isinstance(jobs, list) else []:
            if isinstance(job, dict) and isinstance(job.get("id"), str) and ACTION_RE.fullmatch(job["id"]):
                _do_job(api, cfg["token"], job)
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
    if job.get("type") == "diagnose":
        body["output"] = (extra or "")[:4000] or None  # what the look found (already scrubbed here)
    else:
        body["state"] = extra if extra in STATES else None
    for attempt in range(3):
        status, _ = _post(f"{api}/helper/jobs/{job['id']}/result", body, {"X-Device-Token": token})
        if status in (200, 401, 404, 409):
            return
        time.sleep(5 * (attempt + 1))


def run(every):
    """Keep reporting; network or server trouble is retried with growing waits, a revoked token stops."""
    wait = every
    while True:
        try:
            status = once()
        except Exception as e:  # never let one bad report end monitoring
            print(f"Report failed: {type(e).__name__}")
            status = 0
        if status == 401:
            sys.exit(1)
        wait = every if status == 200 else min(max(wait, every) * 2, 900)
        _wait_and_claim(wait if status == 200 else wait)


def _wait_and_claim(seconds):
    """Sleep until the next report; while the owner is chatting, check for approved work every few seconds."""
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


def pair(api, web=None, name=None):
    """Join by a code this device shows: the owner types it in the app or scans the QR with a phone."""
    api = check_api(api)
    status, body = _post(api + "/helper/pair/start", {"name": (name or default_name())[:40], "os": _os_name()})
    if status != 201:
        sys.exit(f"Couldn't start pairing ({status or 'network error'}): {body.get('code') or body.get('error')}")
    code, interval = body["code"], max(int(body.get("interval", 3)), 2)
    print(f"\n  Your code:  {code}\n")
    if web:
        link = f"{web.rstrip('/')}/pair?code={code}"
        print(f"  Open Nightlight > Add a device > Enter code, or scan this with your phone:\n  {link}\n")
        if shutil.which("qrencode"):
            subprocess.run(["qrencode", "-t", "ANSIUTF8", link], check=False)
    print("  Waiting for you to approve it (10 minutes)...")
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(interval)
        st, res = _post(api + "/helper/pair/poll", {"code": code, "pollSecret": body["pollSecret"]})
        if st == 200 and res.get("token"):
            _save_config({"api": api, "token": res["token"], "deviceId": res["deviceId"]})
            print("  Approved. This device is now on your Nightlight map.")
            return
        if st == 401:
            sys.exit("  The code was declined or has expired. Run pair again for a new one.")
    sys.exit("  The code expired. Run pair again for a new one.")


# ------------------------------------------------------------------ discovery (owner-run, reviewed here first)
# What's nearby on this network. Addresses (IP, MAC) and names stay on this device; only a guess of what each thing is
# ("Home Assistant", "Printer"), its maker and which known services answer are sent, and only the ones you pick.

PORTS = {22: "remote login (SSH)", 80: "web page", 443: "secure web page", 445: "file sharing", 631: "printer",
         8123: "Home Assistant", 25565: "Minecraft", 32400: "Plex"}
MDNS = {"_home-assistant._tcp": "Home Assistant", "_plexmediasvr._tcp": "Plex", "_smb._tcp": "file sharing",
        "_ipp._tcp": "printer", "_printer._tcp": "printer", "_googlecast._tcp": "Chromecast / Google speaker",
        "_airplay._tcp": "AirPlay speaker or TV", "_hap._tcp": "HomeKit accessory", "_ssh._tcp": "remote login (SSH)",
        "_raop._tcp": "AirPlay speaker"}
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
    """IP -> set of service kinds announced on the network (avahi on Linux; skipped elsewhere)."""
    out = {}
    if not shutil.which("avahi-browse"):
        return out
    for line in _run(["avahi-browse", "-aprtk"], timeout=6).splitlines():
        f = line.split(";")
        if len(f) >= 9 and f[0] == "=" and f[2] == "IPv4" and f[4] in MDNS:
            out.setdefault(f[7], set()).add(MDNS[f[4]])
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
                          ("Minecraft", "Minecraft server"), ("printer", "Printer"),
                          ("file sharing", "File share (NAS or computer)")):
        if service in services:
            return name
    if any("speaker" in x or "Chromecast" in x or "TV" in x for x in services):
        return "Speaker or TV"
    if vendor in ("Raspberry Pi", "VMware virtual machine"):
        return vendor
    if 22 in ports:
        return "Computer (remote login)"
    if 80 in ports or 443 in ports:
        return "Device with a web page"
    return vendor or "Unknown device"


def discover(yes=False):
    cfg = _load()
    neigh, mdns = _neighbours(), _mdns()
    ips = set(neigh) | set(mdns)
    ports = _open_ports(ips)
    known = {v.get("ip"): k for k, v in (cfg.get("found") or {}).items()}  # same thing, same id as last time
    items, local = [], {}
    for ip in sorted(ips):
        vendor = _vendor(neigh.get(ip))
        services = sorted(mdns.get(ip, set()) | {PORTS[p] for p in ports.get(ip, [])})
        if not services and not vendor:
            continue  # nothing to say about it
        cid = known.get(ip) or secrets_hex(6)
        items.append({"cid": cid, "guess": _guess(vendor, services, ports.get(ip, [])), "vendor": vendor,
                      "services": services[:8], "ports": sorted(ports.get(ip, []))[:8]})
        local[cid] = {"ip": ip, "ports": sorted(ports.get(ip, []))}
    if not items:
        print("Didn't find anything to suggest on this network.")
        return
    print(f"Found {len(items)} thing(s) nearby. Only what you pick is sent, without addresses:")
    for n, it in enumerate(items, 1):
        print(f"  {n}. {it['guess']}" + (f" - {it['vendor']}" if it["vendor"] else "")
              + (f" ({', '.join(it['services'])})" if it["services"] else ""))
    if yes:
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
    if not chosen:
        print("Nothing sent.")
        return
    cfg["found"] = {**(cfg.get("found") or {}), **{it["cid"]: local[it["cid"]] for it in chosen}}
    _save_config(cfg)
    st, body = _post(check_api(cfg["api"]) + "/helper/discoveries", {"items": chosen[:30]},
                     {"X-Device-Token": cfg["token"]})
    print(f"Sent {len(chosen)}. Open Nightlight to add them to your map." if st == 200
          else f"Couldn't send ({st or 'network error'}).")


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
        t = time.time()
        try:
            with _s.create_connection((target["ip"], port), timeout=1):
                out.append({"cid": w["cid"], "up": True, "ms": int((time.time() - t) * 1000)})
        except OSError:
            out.append({"cid": w["cid"], "up": False, "ms": None})
    return out


# ------------------------------------------------------------------ running in the background

APP_DIR = (os.path.expanduser("~/Library/Application Support/Nightlight") if sys.platform == "darwin"
           else os.path.expanduser("~/.local/share/nightlight"))
UNIT = "/etc/systemd/system/nightlight-helper.service"
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


def install(every=60):
    """Run the helper in the background from now on (and after restarts). Needs the device to be joined first."""
    try:
        _load()
    except (OSError, ValueError):
        sys.exit("Join first: run enrol (with a code from the app) or pair.")
    script, py, home = _copy_self(), os.path.realpath(sys.executable), os.path.abspath(CONFIG_DIR)
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
    for path in (os.path.join(APP_DIR, "nightlight_helper.py"), CONFIG):
        if os.path.isfile(path) and not os.path.islink(path):
            os.unlink(path)
    for d in (APP_DIR, CONFIG_DIR):
        try:
            os.rmdir(d)  # only if empty: never removes anything we didn't put there
        except OSError:
            pass
    print("Uninstalled. Nothing of Nightlight is left running on this device.")


def status():
    try:
        cfg = _load()
        print(f"Joined as device {cfg.get('deviceId')} ({cfg.get('api')}).")
    except (OSError, ValueError):
        print("Not joined yet.")
    if sys.platform == "darwin":
        out = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, text=True)
        print("Background service: " + ("running" if "state = running" in out.stdout else
                                         "installed, not running" if out.returncode == 0 else "not installed"))
    elif shutil.which("systemctl"):
        out = _run(["systemctl", "is-active", "nightlight-helper.service"]).strip()
        print(f"Background service: {out or 'not installed'}")
    allowed = _allowed()
    print("Jobs you allowed here: " + (", ".join(f"{k} {', '.join(v)}" for k, v in allowed.items()) or "none"))


def main():
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
    ins = sub.add_parser("install")
    ins.add_argument("--every", type=int, default=60)
    sub.add_parser("uninstall")
    sub.add_parser("status")
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
        pair(a.api, a.web, a.name)
    elif a.cmd == "install":
        install(a.every)
    elif a.cmd == "uninstall":
        uninstall()
    elif a.cmd == "status":
        status()
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
