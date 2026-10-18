"""From a freestyle run on a real Debian VM (helper 0.9.30): a CPU hog the memory list dropped, a full disk under /srv
the fixed places missed, exit 137 said plainly, and a look into a container whose logs weren't allowed saying what
wasn't read and what would allow it."""

import time

import pytest

from nightlight_api import playbooks
from test_inspect import helper  # noqa: F401 (the fixture)


def _until(helper, seconds=30):
    helper._inspect_until[0] = time.time() + seconds


# ------------------------------------------------------------------ processes: CPU right now, not lifetime averages

def test_a_spinning_program_shows_next_to_the_memory_hogs(helper, monkeypatch):
    first = {str(p): (f"mem{p}", 100, 50_000 + p) for p in range(1, 13)}  # 12 programs heavier in memory
    first["99"] = ("thumbnailer", 0, 10)
    second = {k: (n, t + (100 if n == "thumbnailer" else 0), r) for k, (n, t, r) in first.items()}
    tables = iter([first, second])
    monkeypatch.setattr(helper, "_proc_table", lambda: next(tables))
    monkeypatch.setattr(helper, "_mem_total_kb", lambda: 4 * 1024 * 1024)
    times = iter([(0, 0), (0, 200)])  # all 2 cores busy over the sample
    monkeypatch.setattr(helper, "_cpu_times", lambda: next(times))
    monkeypatch.setattr(helper.os, "sysconf", lambda k: 100 if k == "SC_CLK_TCK" else 4096)
    monkeypatch.setattr(helper.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(helper, "CPU_SAMPLE", 0.2)
    _until(helper)
    out = helper._inspect_processes()
    assert "Processor busy right now: 100% of all 2 cores" in out
    rows = [ln for ln in out.splitlines() if "% mem, " in ln]
    assert rows[0].endswith("% cpu, thumbnailer") and float(rows[0].split("% mem, ")[1].split("%")[0]) > 300
    assert len(rows) == 1 + helper.TOP_MEM  # top by CPU and top by memory, each program once
    got = playbooks.evaluate(playbooks.library()["slow"], out, {})
    assert "busy_cpu" in [f["cause"] for f in got["found"]] and "thumbnailer" in playbooks.summary(got)


def test_each_program_says_whether_it_is_inside_an_app_or_on_the_computer(helper, monkeypatch, tmp_path):
    """Round-4 VM: a host program named thumbnailer was tied to the photos app by its name, and restarting an
    unrelated app was advised. The data now says where each program runs (its control group)."""
    cid = "ab" * 32
    for pid, cg in (("99", "0::/system.slice/nl-thumb1.service\n"),
                    ("7", f"0::/system.slice/docker-{cid}.scope\n"),
                    ("8", f"0::/system.slice/docker-{'cd' * 32}.scope\n")):
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "cgroup").write_text(cg)
    monkeypatch.setattr(helper, "_PROC", str(tmp_path))
    first = {"99": ("thumbnailer", 0, 10), "7": ("postgres", 0, 9_000), "8": ("redis", 0, 8_000)}
    second = {k: (n, t + (100 if n == "thumbnailer" else 0), r) for k, (n, t, r) in first.items()}
    tables = iter([first, second])
    monkeypatch.setattr(helper, "_proc_table", lambda: next(tables))
    monkeypatch.setattr(helper, "_mem_total_kb", lambda: 1024 * 1024)
    monkeypatch.setattr(helper, "_cpu_times", lambda: None)
    monkeypatch.setattr(helper, "_container_ids", lambda: {cid: "notes-db"})
    monkeypatch.setattr(helper, "CPU_SAMPLE", 0.1)
    _until(helper)
    out = helper._inspect_processes()
    assert "thumbnailer (on the computer itself, not inside any app)" in out
    assert "postgres (inside app notes-db)" in out and "redis (inside a container)" in out
    got = playbooks.summary(playbooks.evaluate(playbooks.library()["slow"], out, {}))
    assert "thumbnailer (on the computer itself, not inside any app) keeps a processor core busy" in got


def test_where_a_program_runs_is_only_said_for_layouts_it_knows(helper):
    cid = "ef" * 32
    w = helper._cgroup_where
    assert w("0::/system.slice/ssh.service\n") == ("host", None)
    assert w("0::/\n") == ("host", None) and w("0::/init.scope\n") == ("host", None)
    assert w("12:cpu,cpuacct:/user.slice/user-1000.slice/session-3.scope\n1:name=systemd:/user.slice\n")[0] == "host"
    assert w(f"0::/system.slice/docker-{cid}.scope\n") == ("container", cid)
    assert w(f"0::/user.slice/user-1000.slice/user@1000.service/user.slice/libpod-{cid}.scope\n") == ("container", cid)
    assert w("0::/kubepods.slice/kubepods-burstable.slice/cri-containerd-abc.scope\n") == ("container", None)
    assert w("0::/lxc/101\n")[0] == "container" and w("0::/lxc.payload.web/init.scope\n")[0] == "container"
    assert w("0::/machine.slice/machine-web.scope\n") == ("machine", None)
    assert w("0::/something/else\n") == ("unknown", None) and w("") == ("unknown", None)
    # whole components only: host services named like a runtime stay host services
    assert w("0::/system.slice/docker-cleanup.service\n") == ("host", None)
    assert w("0::/system.slice/machine.slice-monitor.service\n") == ("host", None)
    assert w("0::/system.slice/containerd.service\n") == ("host", None)
    assert w("0::/machine.slice-monitor/x\n") == ("unknown", None)
    assert w(f"4:memory:/docker/{cid}\n") == ("container", cid)
    assert w("0::/system.slice/kubepods-watch.service\n") == ("host", None)  # a unit is never a container
    assert w("0::/system.slice/lxc.payload.monitor.service\n") == ("host", None)
    assert w("4:cpu:/kubepods/burstable/pod1234/abc\n")[0] == "container"  # cgroup v1 layout
    assert w("0::/kubepods.slice/kubepods-besteffort.slice/kubepods-besteffort-pod1.slice/x.scope\n")[0] == \
        "container"


def test_a_program_that_restarted_between_looks_is_not_blamed(helper, monkeypatch):
    tables = iter([{"7": ("old", 10_000, 1)}, {"7": ("new", 10_050, 1)}])  # the pid was reused
    monkeypatch.setattr(helper, "_proc_table", lambda: next(tables))
    monkeypatch.setattr(helper, "_mem_total_kb", lambda: 1024)
    monkeypatch.setattr(helper, "_cpu_times", lambda: None)
    monkeypatch.setattr(helper, "CPU_SAMPLE", 0.1)
    _until(helper)
    assert "0.0% cpu, new" in helper._inspect_processes()


def test_vitals_cpu_is_measured_not_the_load_average(helper, monkeypatch, tmp_path):
    (tmp_path / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    monkeypatch.setattr(helper, "_PROC", str(tmp_path))
    real_sleep = time.sleep
    monkeypatch.setattr(helper.time, "sleep", lambda s: (tmp_path / "stat").write_text(
        "cpu  190 0 110 800 0 0 0 0 0 0\n") or real_sleep(0))
    assert helper._cpu_busy(0.5) == 100.0  # 100 ticks went by, none of them idle
    monkeypatch.setattr(helper, "_PROC", str(tmp_path / "missing"))
    assert helper._cpu_busy(0.5) is None


def test_load_at_or_over_the_cores_is_called_overloaded(helper, monkeypatch):
    monkeypatch.setattr(helper.os, "getloadavg", lambda: (2.03, 0.7, 0.24))
    monkeypatch.setattr(helper.os, "cpu_count", lambda: 2)
    out = helper._inspect_load()
    assert "on 2 CPU cores" in out and "Processor overloaded" in out
    got = playbooks.evaluate(playbooks.library()["slow"], out, {})
    assert [f["cause"] for f in got["found"]] == ["overloaded"] and got["nothing"] is None
    monkeypatch.setattr(helper.os, "getloadavg", lambda: (0.4, 0.3, 0.2))
    calm = playbooks.evaluate(playbooks.library()["slow"], helper._inspect_load(), {})
    assert calm["found"] == [] and "burst" not in calm["nothing"]


# ------------------------------------------------------------------ disk: the biggest folder anywhere on the main disk

def _root(tmp_path):
    root = tmp_path / "root"
    (root / "srv" / "backups" / "2025").mkdir(parents=True)
    (root / "srv" / "backups" / "2025" / "old-laptop.img").write_bytes(b"x" * 3 * 1024 * 1024)
    (root / "srv" / "small").mkdir()
    (root / "usr" / "lib").mkdir(parents=True)
    (root / "usr" / "lib" / "big.so").write_bytes(b"x" * 5 * 1024 * 1024)  # bigger, but the system's own
    (root / "proc").mkdir()
    (root / "proc" / "kcore").write_bytes(b"x" * 1024 * 1024)  # never measured
    (root / "elsewhere").symlink_to(tmp_path)  # never followed
    return root


def test_the_biggest_folder_on_the_main_disk_is_named(helper, monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "_ROOT", str(_root(tmp_path)))
    monkeypatch.setattr(helper, "ROOT_MIN_MB", 1)
    monkeypatch.setattr(helper.shutil, "disk_usage", lambda p: type("U", (), {"used": 9 * 1024 ** 2})())
    _until(helper)
    lines = helper._root_lines()
    assert "Biggest folder on the main disk: /srv/backups/2025: 3 MB" in lines
    assert any(ln.startswith("Folders on the main disk: /usr 5 MB, /srv 3 MB") for ln in lines)
    assert not any("proc" in ln or "elsewhere" in ln or "Not found" in ln for ln in lines)


def test_space_no_measured_folder_holds_is_said(helper, monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "_ROOT", str(_root(tmp_path)))
    monkeypatch.setattr(helper.shutil, "disk_usage", lambda p: type("U", (), {"used": 14 * 1024 ** 3})())
    _until(helper)
    lines = helper._root_lines()
    gap = [ln for ln in lines if ln.startswith("Not found in the measured folders")]
    assert gap and "about 14.0 GB of the 14.0 GB in use" in gap[0]
    got = playbooks.evaluate(playbooks.library()["disk_full"], "\n".join(lines), {"os": "Debian GNU/Linux 12"})
    assert [f["cause"] for f in got["found"]] == ["unmeasured"]


def test_the_disk_scan_stops_when_the_time_is_up(helper, monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "_ROOT", str(_root(tmp_path)))
    _until(helper, 0)
    assert helper._root_lines() == []  # nothing measured, nothing blamed, nothing called missing


def test_linux_disk_check_includes_the_main_disk(helper, monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "_ROOT", str(_root(tmp_path)))
    monkeypatch.setattr(helper, "ROOT_MIN_MB", 1)
    monkeypatch.setattr(helper, "_LOGS", str(tmp_path / "nolog"))
    monkeypatch.setattr(helper, "_disk_places", lambda: [])
    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(helper.shutil, "which", lambda n: None)
    monkeypatch.setattr(helper.shutil, "disk_usage", lambda p: type("U", (), {"used": 9 * 1024 ** 2})())
    _until(helper)
    assert "Biggest folder on the main disk: /srv/backups/2025" in helper._inspect_disk()


def test_disk_playbook_names_a_big_server_folder_and_says_nothing_of_mac_folders_on_linux():
    book = playbooks.library()["disk_full"]
    out = "Biggest known places (sizes):\nBiggest folder on the main disk: /srv/backups/2025: 13.0 GB"
    got = playbooks.evaluate(book, out, {"os": "Debian GNU/Linux 12"})
    assert [f["cause"] for f in got["found"]] == ["big_disk_folder"] and "/srv/backups/2025" in got["found"][0]["say"]
    linux = playbooks.evaluate(book, "Package cache (apt): 218 MB", {"os": "Debian GNU/Linux 12"})["nothing"]
    assert "Documents" not in linux and "Movies" not in linux and "outside" in linux
    mac = playbooks.evaluate(book, "npm cache: 20 MB", {"os": "macOS 15.1"})["nothing"]
    assert "Documents" in mac


# ------------------------------------------------------------------ look into: exit codes and logs not allowed

def _container_state(helper, monkeypatch, code, oom=False):
    import json
    state = {"Status": "exited", "ExitCode": code, "OOMKilled": oom, "StartedAt": "2026-10-18T08:00:00",
             "FinishedAt": "2026-10-18T08:41:00"}
    monkeypatch.setattr(helper, "_run", lambda cmd, timeout=20: json.dumps(state) + " 0")
    monkeypatch.setattr(helper, "_run_both", lambda *a, **k: "log line")


def test_exit_137_is_said_plainly(helper, monkeypatch):
    _container_state(helper, monkeypatch, 137)
    summary, detail = helper._look_container("cache", logs=True)
    # Docker recorded no out-of-memory: the plain fact leads (round 4: the answer said "stopped unexpectedly")
    assert summary.startswith("cache was force-stopped: something killed it") and "didn't record" in summary
    assert "exit code: 137 (was force-stopped: something killed it" in detail
    _container_state(helper, monkeypatch, 137, oom=True)
    assert helper._look_container("cache", logs=True)[0] == "cache was force-stopped because it ran out of memory"


def test_a_service_killed_by_a_signal_or_memory_is_said_plainly(helper):
    assert helper._unit_meaning({"ActiveState": "failed", "Result": "signal", "ExecMainStatus": "9"}) == \
        "was force-stopped (killed, or out of memory)"
    assert "ran out of memory" in helper._unit_meaning({"ActiveState": "failed", "Result": "oom-kill"})
    assert helper._unit_meaning({"ActiveState": "active", "Result": "success", "ExecMainStatus": "0"}) == ""


def test_a_stopped_containers_finding_leads_with_what_its_exit_code_means():
    from nightlight_api import real
    found = real.checks({"containers": [{"name": "cache", "image": "redis:7", "state": "exited",
                                         "status": "Exited (137) 55 seconds ago"},
                                        {"name": "tasks", "image": "x:1", "state": "exited", "status": "Exited (3) 1 m"},
                                        {"name": "new", "image": "x:1", "state": "created", "status": "Created"}]})
    msgs = {f["message"] for f in found}
    assert "cache isn't running: it was force-stopped (exit code 137: killed, or out of memory)." in msgs
    assert "tasks isn't running: it exited with code 3." in msgs and "new isn't running." in msgs


def test_logs_not_allowed_says_what_was_not_read_and_what_would_allow_it(helper, monkeypatch):
    _container_state(helper, monkeypatch, 2)
    monkeypatch.setattr(helper, "_run_both", lambda *a, **k: pytest.fail("logs read without permission"))
    summary, detail = helper._look_container("tasks", logs=False)
    assert summary == "tasks exited with code 2"
    assert "last log lines: not read" in detail and "\"read logs\" permission" in detail


# ------------------------------------------------------------------ the disk scan is bounded in memory and in time

def _fake_du(helper, monkeypatch, script):
    import sys
    monkeypatch.setattr(helper, "_du_cmd", lambda depth: [sys.executable, "-c", script])


def test_a_flood_of_du_output_keeps_only_the_biggest_rows(helper, monkeypatch, tmp_path):
    _fake_du(helper, monkeypatch, "import sys\nw=sys.stdout.write\n"
             "[w(f'{i}\\t./d/{i}\\n') for i in range(100000)]\nw('x'*20000+'\\n')\nw('999999\\t.\\n')")
    _until(helper)
    tree, why = helper._du_tree(str(tmp_path))
    assert why is None and tree["."] == round(999999 / 1024)
    assert len(tree) == helper.DU_ROWS + 1 and "./d/99999" in tree and "./d/0" not in tree


def test_too_much_du_output_is_stopped_and_said(helper, monkeypatch, tmp_path):
    _fake_du(helper, monkeypatch, "import sys\nwhile True: sys.stdout.write('1\\t./x\\n' * 1000)")
    monkeypatch.setattr(helper, "DU_BYTES", 256 * 1024)
    _until(helper)
    assert helper._du_tree(str(tmp_path)) == ({}, "too much output")


def test_a_hanging_du_is_stopped_at_the_deadline_and_said(helper, monkeypatch, tmp_path):
    (tmp_path / "srv").mkdir()
    monkeypatch.setattr(helper, "_ROOT", str(tmp_path))
    _fake_du(helper, monkeypatch, "import time\ntime.sleep(30)")
    monkeypatch.setattr(helper.shutil, "disk_usage", lambda p: type("U", (), {"used": 1024 ** 2})())
    _until(helper, 2)
    t = time.time()
    lines = helper._root_lines()
    assert time.time() - t < 4
    assert lines == ["Not measured on the main disk: /srv (not measured in time)"]
