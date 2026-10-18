"""Run the API locally with the live pool on, against the real project (ADC = your gcloud login), or a one-off.
Usage (from api/):  uv run python ../scripts/live_pool/local.py serve|sweep|slots"""
import json
import os
import sys

ENV = {
    "GOOGLE_CLOUD_PROJECT": "nightlight-aibc",
    "LIVE_POOL": ",".join(f"nl-live-{n}=judge-pool-{n}" for n in range(1, 6)),
    "LIVE_SIGNER": "firebase-adminsdk-fbsvc@nightlight-aibc.iam.gserviceaccount.com",
    "MEMORY_BANK_ID": "4443553098354393088",
    "LIVE_IDLE_SECONDS": os.environ.get("LIVE_IDLE_SECONDS", "120"),
    "WEB_ORIGINS": "http://localhost:3000",
}
os.environ.update(ENV)

cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
if cmd == "serve":
    import uvicorn
    uvicorn.run("nightlight_api.main:app", port=8731)
else:
    from nightlight_api import live
    if cmd == "sweep":
        print(json.dumps(live.sweep()))
    elif cmd == "expire-sweep":  # test: wait for a lease to expire on its own (no heartbeat), then run the sweep
        import time
        from datetime import datetime, timezone
        t = time.time()
        while time.time() - t < 300:
            docs = {n: live.slots().document(n).get().to_dict() or {} for n in live.pool()}
            due = [n for n, d in docs.items() if d.get("state") == "leased" and d["expiresAt"] <= datetime.now(timezone.utc)]
            if due:
                break
            time.sleep(5)
        print("expired:", due, f"after {time.time() - t:.0f}s;", "vms:", live.all_status(0))
        t = time.time()
        print("sweep:", json.dumps(live.sweep()), f"{time.time() - t:.0f}s")
        print("vms:", live.all_status(0))
    elif cmd == "baseline":  # with the golden snapshots: record each clean pool account, and bind uid -> slot for rules
        for n, uid in live.pool().items():
            live.db.client().collection("livePoolUids").document(uid).set({"slot": n})
            print(n, uid, live.record_baseline(uid))
    elif cmd == "free-all":  # after maintenance (e.g. new golden snapshots): every slot free, VMs must be stopped
        for n in live.pool():
            live.slots().document(n).set({"state": "free"})
    elif cmd == "maintenance":  # take every slot out of the pool (leases refused) without touching the VMs
        for n in live.pool():
            live.slots().document(n).set({"state": "maintenance"})
    elif cmd == "slots":
        for n in live.pool():
            d = live.slots().document(n).get().to_dict() or {}
            print(n, d.get("state"), d.get("expiresAt"), d.get("command"), d.get("scenario"), live.vm_status(n, 0))
