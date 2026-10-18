"use client";
// The start screen: a live demo machine (a real VM, when the pool is on), the simulated home, or your own computer.
import { useEffect, useState } from "react";
import { GoogleAuthProvider, signInAnonymously, signInWithPopup } from "firebase/auth";
import { api } from "@/lib/api";
import { firebase } from "@/lib/firebase";
import { clearProblem, minutes, SCENARIOS, startLive, useLive, type LiveStatus, type Problem, type Scenario } from "@/lib/live";

function problemText(p: Problem): string | null {
  if (p.code === "live_all_busy") return null; // its own block below
  if (p.code === "live_per_visitor_limit") return "You've started several machines in a short time. Please wait a little, or try the simulated home meanwhile.";
  if (p.code === "live_off") return "Live demo machines are switched off right now.";
  if (p.code === "live_start_failed") return "Your machine didn't start. Please try again in a moment.";
  return "Couldn't start a machine. Please try again.";
}

export default function SignIn() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [scenario, setScenario] = useState<Scenario>("none");
  const live = useLive();

  // the live line, every 10 s while this screen is open (asking also frees machines whose visitors have left)
  useEffect(() => {
    let on = true;
    const load = () => api<LiveStatus>("GET", "/api/demo/live/status").then((s) => { if (on) setStatus(s); }, () => {});
    load();
    const t = setInterval(load, 10000);
    return () => { on = false; clearInterval(t); };
  }, []);

  async function go(kind: "demo" | "google") {
    setBusy(true); setErr(""); clearProblem();
    try {
      const { auth } = await firebase();
      if (kind === "demo") await signInAnonymously(auth);
      else await signInWithPopup(auth, new GoogleAuthProvider());
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  const liveOn = !!status?.enabled;
  const busyAll = live.problem?.code === "live_all_busy";
  const total = live.problem?.total ?? status?.total;
  const said = live.problem && problemText(live.problem);
  const off = busy || live.starting;
  return (
    <div className="signin">
      <div className="modal start">
        <div className="brand" style={{ justifyContent: "center" }}><span className="bulb" /> Nightlight</div>
        <h1>A house-sitter for your home servers</h1>
        <p className="muted">One friendly map of every device you run. An assistant that watches, explains in plain
          words, and fixes things only when you say so.</p>
        {live.ended && <p className="small" role="status">Your time on the live machine has ended. It is being reset
          for the next visitor.</p>}

        {busyAll ? (
          <div className="start-option" role="alert">
            <p>All {total ?? "the"} live demo machines are in use right now. A machine is reset and freed within a few
              minutes after each visit. Meanwhile:{" "}
              <button className="linkish" disabled={off} onClick={() => go("demo")}>simulated home</button> or{" "}
              <button className="linkish" disabled={off} onClick={() => go("google")}>your own computer</button>.</p>
          </div>
        ) : liveOn && status && (
          <div className="start-option">
            <p>This demo uses a real virtual machine in Google Cloud, with real apps running in containers, set up like
              a small home server. It isn&apos;t your computer, but everything Nightlight does to it is real. Starting
              your machine: about {minutes(status.etaSeconds ?? 60)}.</p>
            <div className="start-row">
              <button className="primary" disabled={off} onClick={() => startLive(scenario)}>
                {live.starting ? "Starting your machine…" : "Start a live machine"}</button>
              <label className="small muted">Start with{" "}
                <select value={scenario} disabled={off} onChange={(e) => setScenario(e.target.value as Scenario)}>
                  {SCENARIOS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                </select></label>
            </div>
            <p className="small muted" aria-live="polite">Live demo machines: {status.running} of {status.total} running
              · {status.inUse} in use</p>
          </div>
        )}
        {said && <p className="small" role="alert" style={{ color: "var(--crit)" }}>{said}</p>}

        <div className="start-option">
          <p>{liveOn ? "Short on time? Try the fully simulated home instead (instant)." : "Try a fully simulated home (instant)."}</p>
          <button className={liveOn ? "" : "primary"} disabled={off} onClick={() => go("demo")}>Open the simulated home</button>
        </div>
        <div className="start-option">
          <p>Best of all: try it on your own computer or Raspberry Pi with your Google account (about two minutes;
            read-only until you approve anything).</p>
          <button disabled={off} onClick={() => go("google")}>Sign in with Google</button>
        </div>
        {liveOn && <p className="small muted">Your machine is reset to a clean copy after you leave
          ({status?.idleMinutes ?? 15} minutes without activity, at most {status?.maxMinutes ?? 60} minutes).</p>}
        {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
      </div>
    </div>
  );
}
