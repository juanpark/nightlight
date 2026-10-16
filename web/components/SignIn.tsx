"use client";
import { useState } from "react";
import { GoogleAuthProvider, signInAnonymously, signInWithPopup } from "firebase/auth";
import { firebase } from "@/lib/firebase";

export default function SignIn() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function go(kind: "demo" | "google") {
    setBusy(true); setErr("");
    try {
      const { auth } = await firebase();
      if (kind === "demo") await signInAnonymously(auth);
      else await signInWithPopup(auth, new GoogleAuthProvider());
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <div className="signin">
      <div className="modal">
        <div className="brand" style={{ justifyContent: "center" }}><span className="bulb" /> Nightlight</div>
        <h1>A house-sitter for your home servers</h1>
        <p className="muted">One friendly map of every device you run. An assistant that watches, explains in plain
          words, and fixes things only when you say so.</p>
        <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 16, flexWrap: "wrap" }}>
          <button className="primary" disabled={busy} onClick={() => go("demo")}>Try the demo (no account)</button>
          <button disabled={busy} onClick={() => go("google")}>Sign in with Google</button>
        </div>
        <p className="small muted" style={{ marginTop: 14 }}>The demo uses a simulated sample home, clearly labelled.</p>
        {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
      </div>
    </div>
  );
}
