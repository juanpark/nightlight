"use client";
// On a live demo machine: a waiting screen until the machine is ready (its real phases), then a small bar with Start
// fresh, Break something for real, and Leave. Keeps the lease alive while the page is visible; when the lease ends,
// signs out back to the start screen.
import { useCallback, useEffect, useState } from "react";
import { useNow } from "@/lib/data";
import { api, ApiError } from "@/lib/api";
import { leaveLive, machineState, minutes, resumedSeen, useLive, type LiveMe, type Scenario } from "@/lib/live";

const PHASE: Record<LiveMe["phase"], string> = {
  stopping: "Stopping your machine…", restoring: "Putting back a clean copy of its disk…", starting: "Starting it up…",
  reconnecting: "Waiting for your machine to check in…", ready: "Ready.",
};
const ORDER: LiveMe["phase"][] = ["stopping", "restoring", "starting", "reconnecting", "ready"];

/** A clock that counts up from a moment: "0:42". */
function Elapsed({ from }: { from?: number }) {
  const now = useNow(1000);
  if (!from) return null;
  const s = Math.max(0, Math.floor((now - from) / 1000));
  return <p className="live-elapsed" aria-live="off">{Math.floor(s / 60)}:{String(s % 60).padStart(2, "0")}</p>;
}

/** The waiting screen before the machine is signed in to (the lease is being made). */
export function LiveStarting() {
  const live = useLive();
  return (
    <div className="signin"><div className="modal start" role="status" aria-live="polite">
      <div className="brand" style={{ justifyContent: "center" }}><span className="bulb" /> Nightlight</div>
      <p><strong>{PHASE.starting}</strong></p>
      <Elapsed from={live.clicked} />
      <p className="small muted">Starting your machine: about {minutes(live.eta ?? 60)}.</p>
    </div></div>
  );
}

export default function LiveSession() {
  const live = useLive();
  const [me, setMe] = useState<LiveMe | null>(null);
  const [err, setErr] = useState("");
  const [working, setWorking] = useState(false);
  const [restartAt, setRestartAt] = useState<number>(); // Start fresh: the waiting clock counts from that tap
  const ended = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) { leaveLive(true); return true; }
    return false;
  }, []);

  // the machine's state: every 2 s until it is ready (asking also moves a Start fresh along)
  const ready = me?.phase === "ready";
  useEffect(() => {
    if (ready) return;
    let on = true;
    const load = () => api<LiveMe>("GET", "/api/demo/live/me").then((m) => { if (on) setMe(m); }, (e) => { ended(e); });
    load();
    const t = setInterval(load, 2000);
    return () => { on = false; clearInterval(t); };
  }, [ready, ended]);

  // keep the lease while the page is being looked at
  useEffect(() => {
    const beat = () => { if (document.visibilityState === "visible") api("POST", "/api/demo/live/heartbeat", {}).catch(ended); };
    beat();
    const t = setInterval(beat, 60000);
    document.addEventListener("visibilitychange", beat);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", beat); };
  }, [ended]);

  async function act(path: string, body: unknown) {
    setWorking(true); setErr(""); resumedSeen(); setRestartAt(Date.now());
    try {
      const r = await api<{ phase?: LiveMe["phase"] }>("POST", path, body);
      setMe((m) => ({ ...(m ?? {}), phase: r.phase ?? "reconnecting" }));
    } catch (e) {
      if (!ended(e)) setErr(e instanceof ApiError && e.code === "reset_in_progress"
        ? "Your machine is already being put back. One moment." : "Couldn't do that. Please try again.");
    } finally { setWorking(false); }
  }
  const fresh = (scenario: Scenario = "none") => act("/api/demo/live/reset", { scenario });
  // tell Home: when the lease began (reports before it are the clean copy's), and whether the machine is ready
  const since = me?.secondsSinceLease;
  const [leaseStart, setLeaseStart] = useState<number>();
  useEffect(() => { if (since != null) setLeaseStart((t) => t ?? Date.now() - since * 1000); }, [since]);
  useEffect(() => { machineState({ machineReady: ready && !live.resumed, leaseStart }); }, [ready, live.resumed, leaseStart]);

  const restore = me?.restoreSeconds ?? live.restore ?? 120;
  // while the bar floats at the bottom, the panes that scroll under it leave room for it (app/needs.css)
  const barShown = ready && !(live.resumed && me);
  const [open, setOpen] = useState(false); // phones: the bar's controls, folded to one line until tapped
  useEffect(() => {
    if (!barShown) return;
    document.documentElement.classList.add("has-live-bar");
    return () => document.documentElement.classList.remove("has-live-bar");
  }, [barShown]);

  if (live.resumed && me) {
    return (
      <div className="overlay"><div className="modal start" role="dialog" aria-modal="true" aria-label="Your live machine">
        <p><strong>You still have {me.machine ?? "your machine"}.</strong></p>
        <div className="start-row">
          <button className="primary" onClick={resumedSeen}>Continue where you left off</button>
          <button onClick={() => fresh()}>Start fresh (restores your machine from a clean copy: about {minutes(restore)})</button>
        </div>
      </div></div>
    );
  }
  if (!ready) {
    const at = me ? ORDER.indexOf(me.phase) : 2;
    return (
      <div className="overlay"><div className="modal start" role="status" aria-live="polite">
        <p><strong>{me?.machine ?? "Your machine"}</strong></p>
        <Elapsed from={restartAt ?? live.clicked ?? leaseStart} />
        <ol className="live-phases">
          {ORDER.slice(me?.phase === "stopping" || me?.phase === "restoring" ? 0 : 2).map((p) => (
            <li key={p} className={ORDER.indexOf(p) < at ? "done" : ORDER.indexOf(p) === at ? "now" : ""}>{PHASE[p]}</li>))}
        </ol>
        <p className="small muted">{me?.phase === "stopping" || me?.phase === "restoring"
          ? `Restoring your machine from a clean copy: about ${minutes(restore)}.`
          : `Starting your machine: about ${minutes(me?.etaSeconds ?? live.eta ?? 60)}.`}</p>
        <button className="small" onClick={() => leaveLive()}>Leave</button>
      </div></div>
    );
  }
  return (
    <div className="live-bar" role="region" aria-label="Live demo machine" data-tour="live-bar" data-open={open || undefined}>
      <span className="live-dot" aria-hidden /> <strong>{me?.machine ?? "Live machine"}</strong>
      <span className="small muted live-what">a real computer in Google Cloud</span>
      {/* phones: one slim line; its controls open on a tap */}
      <button className="small live-toggle" aria-expanded={open} aria-controls="live-controls" onClick={() => setOpen(!open)}>
        {open ? "Close" : "Start fresh or leave"}</button>
      <span className="live-controls" id="live-controls">
        <button className="small" disabled={working} onClick={() => fresh()}>Start fresh</button>
        <button className="small" onClick={() => leaveLive()}>Leave</button>
      </span>
      {err && <span className="small" role="alert" style={{ color: "var(--crit-ink)" }}>{err}</span>}
    </div>
  );
}
