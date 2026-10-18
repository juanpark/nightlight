"use client";
// The start screen: your own computers first (the real thing), then the sample home, then (while LIVE_DEMO is on and
// the pool has machines) a real cloud machine.
import { useEffect, useState } from "react";
import { GoogleAuthProvider, signInAnonymously, signInWithPopup } from "firebase/auth";
import { api } from "@/lib/api";
import { firebase } from "@/lib/firebase";
import { clearProblem, LIVE_DEMO, startLive, useLive, type LiveStatus, type Problem } from "@/lib/live";

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
  const live = useLive();

  // the live line, every 10 s while this screen is open (asking also frees machines whose visitors have left)
  useEffect(() => {
    if (!LIVE_DEMO) return;
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

  const liveOn = LIVE_DEMO && !!status?.enabled;
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

        <div className="start-option start-own">
          <p><strong>The real Nightlight runs on your own computers.</strong> Sign in with Google and add your Mac or
            Raspberry Pi in about two minutes: that&apos;s the full experience.</p>
          <button className="primary" disabled={off} onClick={() => go("google")}>Sign in with Google</button>
        </div>

        <div className="start-option">
          <p>Just looking? A pretend home with a few devices and a problem or two to fix.</p>
          <button className="primary" disabled={off} onClick={() => go("demo")}>Open the sample home (instant, simulated)</button>
        </div>

        {busyAll ? (
          <div className="start-option" role="alert">
            <p className="small">All {total ?? "the"} cloud machines are in use right now. One is reset and freed within
              a few minutes after each visit; the sample home above is instant.</p>
          </div>
        ) : liveOn && status && (
          <div className="start-option">
            <p className="small">A real virtual machine in Google Cloud, set up like a small home server with something
              already broken. It isn&apos;t your computer, but everything Nightlight does to it is real.</p>
            <button disabled={off} onClick={() => startLive("crash")}>
              {live.starting ? "Starting your machine…" : "See it on a real cloud machine (about a minute)"}</button>
            <p className="small muted" aria-live="polite">{status.free} of {status.total} free · reset to a clean copy
              after you leave ({status.idleMinutes ?? 15} minutes without activity, at most {status.maxMinutes ?? 60}).</p>
          </div>
        )}
        {said && <p className="small" role="alert" style={{ color: "var(--crit-ink)" }}>{said}</p>}

        <p className="small muted">Signed in to Nightlight before? Sign out or use a private window to see these choices.</p>
        {err && <p className="small" style={{ color: "var(--crit-ink)" }}>{err}</p>}
      </div>
    </div>
  );
}
