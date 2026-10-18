"""(Re)take the golden snapshot of each pool VM's current boot disk: stop -> delete old <vm>-golden -> snapshot.
Run only when every pool VM is in the state every visitor should get (healthy home, helper paired and reporting).
Usage: python3 -I scripts/live_pool/golden.py 1 2 3 4 5"""
import json, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

P, Z, R = "nightlight-aibc", "asia-northeast3-a", "asia-northeast3"


def g(*args):
    return subprocess.run(["gcloud", *args, "--project", P], capture_output=True, text=True)


def golden(n):
    vm = f"nl-live-{n}"
    t = time.time()
    g("compute", "instances", "stop", vm, "--zone", Z)
    inst = json.loads(g("compute", "instances", "describe", vm, "--zone", Z, "--format=json").stdout)
    disk = next(d["source"].rsplit("/", 1)[-1] for d in inst["disks"] if d.get("boot"))
    g("compute", "snapshots", "delete", f"{vm}-golden", "--quiet")
    r = g("compute", "snapshots", "create", f"{vm}-golden", "--source-disk", disk, "--source-disk-zone", Z,
          "--storage-location", R, "--labels", "purpose=live-demo-pool")
    print(vm, disk, "ok" if r.returncode == 0 else r.stderr[-300:], f"{time.time() - t:.0f}s", flush=True)


with ThreadPoolExecutor(5) as ex:
    list(ex.map(golden, sys.argv[1:] or ["1", "2", "3", "4", "5"]))
