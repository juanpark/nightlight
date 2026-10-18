"""Concurrency test for the live demo machine pool: N anonymous visitors ask for a live machine at the same moment.

Usage: python3 -I scripts/live_pool/pool_test.py <api> <n> [--scenario crash] [--hold S] [--end] [--same-ip]
Each visitor: anonymous Firebase sign-up -> POST /api/demo/live -> signInWithCustomToken -> poll /api/demo/live/me until
the VM runs and its helper has reported ("ready"), sending heartbeats. Prints one row per visitor and a summary.
"""
import argparse, json, subprocess, threading, time, urllib.error, urllib.request

# Operator-only: freestyle drift of the kind seen in a real freestyle test, made over IAP SSH (never by visitors).
DRIFT = ("sudo fallocate -l 13G /srv/big-download.bin; "
         "sudo docker run -d --name crashloop --restart always alpine:3.20 sh -c 'sleep 2; exit 1' >/dev/null; "
         "sudo docker update --restart no photos >/dev/null; "
         "nohup sh -c 'while :; do :; done' >/dev/null 2>&1 & echo drifted")
CHECK = ("echo srv=$(ls /srv | tr '\n' ,) containers=$(sudo docker ps -a --format '{{.Names}}' | sort | tr '\n' ,) "
         "hog=$(pgrep -fc 'while :; do :; done') photos_restart=$(sudo docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' photos) "
         "disk=$(df --output=pcent / | tail -1 | tr -d ' ') helper=$(systemctl is-active nightlight-helper)")

WEB = "https://nightlight-web-1032111130355.asia-northeast3.run.app"
REF = {"Referer": WEB + "/"}
# The public Firebase web API key, read from the web app's /config (as the browser does), so it isn't copied here.
KEY = json.load(urllib.request.urlopen(WEB + "/config", timeout=20))["firebase"]["apiKey"]


def http(method, url, body=None, headers=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def anon():
    _, r = http("POST", f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={KEY}", {"returnSecureToken": True}, REF)
    return r["idToken"]


def custom(token):
    _, r = http("POST", f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={KEY}",
                {"token": token, "returnSecureToken": True}, REF)
    return r["idToken"]


def ssh(slot, cmd):
    out = subprocess.run(["gcloud", "compute", "ssh", slot, "--project", "nightlight-aibc", "--zone", "asia-northeast3-a",
                          "--tunnel-through-iap", "--command", cmd], capture_output=True, text=True, timeout=300).stdout
    return (out.strip().splitlines() or [""])[-1]


def visitor(i, a, barrier, rows):
    row = {"visitor": i}
    rows.append(row)
    tok = anon()
    time.sleep(a.skew)  # a local server whose clock runs behind Google's refuses brand-new tokens ("used too early")
    ip = "198.51.100.7" if a.same_ip else f"198.51.100.{10 + i}"
    barrier.wait()
    if a.late and i > a.n - a.late:
        time.sleep(a.late_delay)  # a visitor who arrives later (e.g. while another one resets)
    t0 = time.time()
    code, r = http("POST", a.api + "/api/demo/live", {"scenario": a.scenario},
                   {"Authorization": "Bearer " + tok, "X-Forwarded-For": ip})
    row.update(leaseStatus=code, leaseSeconds=round(time.time() - t0, 1))
    if code != 200:
        row["result"] = r.get("code"); row.update({k: r[k] for k in ("inUse", "total") if k in r}); return
    row.update(machine=r["machine"], slot=r["slot"], resumed=r.get("resumed"))
    if a.twice:  # the same visitor asking again gets the same machine
        c2, r2 = http("POST", a.api + "/api/demo/live", {}, {"Authorization": "Bearer " + tok, "X-Forwarded-For": ip})
        row["again"] = r2.get("slot") if c2 == 200 else c2
    pool = {"Authorization": "Bearer " + custom(r["token"])}
    time.sleep(a.skew)
    row["token"] = pool["Authorization"]
    running = None
    while time.time() - t0 < 240:
        c, m = http("GET", a.api + "/api/demo/live/me", None, pool)
        if c != 200:
            row["result"] = f"me {c} {m.get('code')}"; return
        if m["vm"] == "RUNNING" and running is None:
            running = round(time.time() - t0, 1)
        if m["phase"] == "ready":
            row.update(runningAt=running, readyAt=round(time.time() - t0, 1), result="ready"); break
        time.sleep(2)
    else:
        row["result"] = "timeout"; return
    if a.check:
        row["checkAtReady"] = ssh(r["slot"], CHECK)
    if i in a.drift:
        row["drift"] = ssh(r["slot"], DRIFT)
        row["checkAfterDrift"] = ssh(r["slot"], CHECK)
    if i == a.reset_visitor:  # start fresh on the same machine, and time it until ready again
        t1 = time.time()
        c, rr = http("POST", a.api + "/api/demo/live/reset", {"scenario": a.reset_scenario}, pool)
        row["reset"] = c
        c2, rr2 = http("POST", a.api + "/api/demo/live/reset", {}, pool)
        row["secondResetWhileBusy"] = f"{c2} {rr2.get('code')}"
        phases = []
        while time.time() - t1 < 400:
            c, m = http("GET", a.api + "/api/demo/live/me", None, pool)
            ph = m.get("phase") or f"{c} {m.get('code')}"
            if not phases or phases[-1][0] != ph:
                phases.append((ph, round(time.time() - t1)))
            if ph == "ready" and len(phases) > 1:
                break
            time.sleep(2)
        row.update(resetReadySeconds=round(time.time() - t1, 1),
                   resetPhases=" ".join(f"{p}@{t}s" for p, t in phases))
        if a.check:
            row["checkAfterReset"] = ssh(r["slot"], CHECK)
    hb_end = time.time() + a.hold
    while time.time() < hb_end:
        http("POST", a.api + "/api/demo/live/heartbeat", {}, pool)
        time.sleep(min(30, max(1, hb_end - time.time())))
    if a.job:  # a real job on the helper (playbook checks, no AI), then leave at once: release during an in-flight job
        dev = http("GET", f"https://firestore.googleapis.com/v1/projects/nightlight-aibc/databases/(default)/documents/users/{r['uid']}/devices", None, pool)[1]
        dev_id = next(d["name"].rsplit("/", 1)[-1] for d in dev.get("documents", []) if d["fields"].get("realm", {}).get("stringValue") == "real")
        sid = http("POST", a.api + "/api/chat/sessions", {}, pool)[1].get("sessionId")
        books = http("GET", f"{a.api}/api/devices/{dev_id}/playbooks", None, pool)[1]
        book = ((books.get("playbooks") or [{}])[0].get("id")) or "disk_full"
        row["job"] = http("POST", f"{a.api}/api/devices/{dev_id}/playbooks/{book}/run", {"sessionId": sid}, pool)
        if row["job"][0] != 202:  # strict devices refuse playbooks: a network discovery job instead
            row["job"] = http("POST", f"{a.api}/api/devices/{dev_id}/discover", {}, pool)
        time.sleep(3)  # let the helper claim it
    if a.end:
        t1 = time.time()
        row["end"] = http("POST", a.api + "/api/demo/live/end", {}, pool)[0]
        row["endSeconds"] = round(time.time() - t1, 1)
        row["afterEnd"] = http("GET", a.api + "/api/demo/live/me", None, pool)[1].get("code")
        if a.wait_free:  # the public status drives the disk restore; time until this machine is free again
            while time.time() - t1 < 400:
                st = http("GET", a.api + "/api/demo/live/status")[1]
                m = next(x for x in st["machines"] if x["machine"] == row["machine"])
                if m["state"] == "free":
                    break
                time.sleep(3)
            row["freeAgainSeconds"] = round(time.time() - t1, 1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("api"); p.add_argument("n", type=int)
    p.add_argument("--scenario", default="none"); p.add_argument("--hold", type=int, default=0)
    p.add_argument("--end", action="store_true"); p.add_argument("--same-ip", action="store_true")
    p.add_argument("--twice", action="store_true"); p.add_argument("--out")
    p.add_argument("--late", type=int, default=0); p.add_argument("--late-delay", type=float, default=0)
    p.add_argument("--reset-visitor", type=int, default=0); p.add_argument("--reset-scenario", default="none")
    p.add_argument("--drift", type=int, nargs="*", default=[]); p.add_argument("--check", action="store_true")
    p.add_argument("--skew", type=float, default=0); p.add_argument("--job", action="store_true"); p.add_argument("--wait-free", action="store_true")
    a = p.parse_args()
    barrier = threading.Barrier(a.n)
    rows = []
    ts = [threading.Thread(target=visitor, args=(i + 1, a, barrier, rows)) for i in range(a.n)]
    [t.start() for t in ts]; [t.join() for t in ts]
    for r in sorted(rows, key=lambda r: r["visitor"]):
        print(json.dumps({k: v for k, v in r.items() if k != "token"}))
    slots = [r["slot"] for r in rows if r.get("slot")]
    print(f"leased={len(slots)} distinct={len(set(slots))} refused={sum(1 for r in rows if r.get('leaseStatus') != 200)}")
    if a.out:
        json.dump(rows, open(a.out, "w"))


if __name__ == "__main__":
    main()
