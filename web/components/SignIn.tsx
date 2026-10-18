"use client";
// The start screen: your own computers (the real thing), the sample home (the full tour, instantly), then (while
// LIVE_DEMO is on and the pool has machines) a borrowed cloud machine.
import { useEffect, useRef, useState } from "react";
import { GoogleAuthProvider, signInAnonymously, signInWithPopup } from "firebase/auth";
import { api } from "@/lib/api";
import { firebase } from "@/lib/firebase";
import WhichDevices from "./WhichDevices";
import { clearProblem, LIVE_DEMO, startLive, useLive, type LiveStatus, type Problem } from "@/lib/live";

function problemText(p: Problem): string | null {
  if (p.code === "live_all_busy") return null; // its own block below
  if (p.code === "live_per_visitor_limit") return "You've started several machines in a short time. Please wait a little, or try the simulated home meanwhile.";
  if (p.code === "live_off") return "Live demo machines are switched off right now.";
  if (p.code === "live_start_failed") return "Your machine didn't start. Please try again in a moment.";
  return "Couldn't start a machine. Please try again.";
}

// Firebase's own messages are technical ("Firebase: Error (auth/popup-blocked)."); say what happened and what to do.
function signInText(code: string, kind: "demo" | "google"): string {
  if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request")
    return "The Google window was closed before you signed in. Try again when you're ready.";
  if (code === "auth/popup-blocked") return "Your browser blocked the Google window. Allow pop-ups for this site, then try again.";
  if (code === "auth/network-request-failed") return "Couldn't reach the internet. Check your connection and try again.";
  return kind === "demo" ? "The tour couldn't start. Please try again in a moment." : "Google sign-in didn't work. Please try again in a moment.";
}

/** The start screen's choices (Juan's wording and logic), shared by the plain start screen and the landing page's
 * start dialog. */
export function StartChoices({ title = "Go to sleep. It's got this." }: { title?: string }) {
  const [busy, setBusy] = useState<"demo" | "google" | null>(null);
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
    setBusy(kind); setErr(""); clearProblem();
    try {
      const { auth } = await firebase();
      if (kind === "demo") await signInAnonymously(auth);
      else await signInWithPopup(auth, new GoogleAuthProvider());
    } catch (e) {
      setErr(signInText((e as { code?: string }).code ?? "", kind));
      setBusy(null);
    }
  }

  const liveOn = LIVE_DEMO && !!status?.enabled;
  const busyAll = live.problem?.code === "live_all_busy";
  const total = live.problem?.total ?? status?.total;
  const said = live.problem && problemText(live.problem);
  const off = busy !== null || live.starting;
  // a problem appears under the last choice; in a scrolling dialog that can be out of sight, so bring it into view
  const problem = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (err || said) problem.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [err, said]);
  return (
      <>
        <div className="brand" style={{ justifyContent: "center" }}><span className="bulb" /> Nightlight</div>
        <h1 id="start-title">{title}</h1>
        <p className="muted">An agent for the machines you run. Nightlight watches, explains issues in plain words, and
          gets things fixed.</p>
        {live.ended && <p className="small" role="status">Your time on the live machine has ended. It is being reset
          for the next visitor.</p>}

        <p className="start-lead"><strong>Nightlight is live.</strong></p>

        <div className="start-option start-own">
          <p><strong>Try the real thing:</strong> Sign in with Google and add your own devices in a few minutes.</p>
          <p className="small">(Mac or Linux machines like the Raspberry Pi)</p>
          <button className="primary" disabled={off} onClick={() => go("google")}>
            {busy === "google" ? "Opening Google…" : "Sign in with Google"}</button>
          <WhichDevices start label="Which devices are supported (as of 2026-10-18)" />
        </div>

        <div className="start-option start-sample">
          <p><strong>Try a guided tour:</strong> Explore a sample home with sample devices. Relax and experience
            Nightlight&apos;s real agent at work.</p>
          <button className="primary" disabled={off} onClick={() => go("demo")}>
            {busy === "demo" ? "Opening the sample home…" : "Take the tour (instant demo)"}</button>
        </div>

        {busyAll ? (
          <div className="start-option" role="alert">
            <p className="small">All {total ?? "the"} cloud machines are in use right now. One is reset and freed within
              a few minutes after each visit; the guided tour above is instant.</p>
          </div>
        ) : liveOn && status && (
          <div className="start-option">
            <p><strong>Try it hands-on without a device:</strong> Demo Linux VM in Google Cloud.</p>
            <p className="small"><span className="pill">Limited demo</span> No passkeys, no adding devices, and nothing
              nearby to find. For the full experience, use your own device or take the guided tour.</p>
            <button disabled={off} onClick={() => startLive("crash")}>
              {live.starting ? "Starting your machine…" : "Hands on with a VM (takes about a minute to boot)"}</button>
            <p className="small muted" aria-live="polite">{status.free} of {status.total} free · reset to a clean copy
              after you leave ({status.idleMinutes ?? 15} minutes without activity, at most {status.maxMinutes ?? 60}).</p>
          </div>
        )}
        <div ref={problem}>
          {said && <p className="small start-error" role="alert" style={{ color: "var(--crit-ink)" }}>{said}</p>}
          {err && <p className="small start-error" role="alert" style={{ color: "var(--crit-ink)" }}>{err}</p>}
        </div>

        <p className="small muted">*Signed in to Nightlight before? Sign out or use a private window to see the choices.</p>
      </>
  );
}

export default function SignIn() {
  return <div className="signin"><div className="modal start"><StartChoices /></div></div>;
}
