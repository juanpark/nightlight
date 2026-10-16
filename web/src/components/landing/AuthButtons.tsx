"use client";

import { useState } from "react";
import { GoogleAuthProvider, signInAnonymously, signInWithPopup } from "firebase/auth";
import { firebase } from "@/lib/firebase";
import { Icon } from "./Icon";
import landing from "./Landing.module.css";

type Kind = "demo" | "google";

// "Try the demo" (anonymous, one click) and "Sign in with Google". Once Firebase
// reports a user, AppGate swaps the landing page for the app.
export function AuthButtons({
  size = "large",
  demoOnly = false,
  styles: s = landing,
}: {
  size?: "large" | "small";
  demoOnly?: boolean;
  styles?: Record<string, string>; // the day hero passes its own
}) {
  const [busy, setBusy] = useState<Kind | null>(null);
  const [err, setErr] = useState("");

  async function go(kind: Kind) {
    setBusy(kind);
    setErr("");
    try {
      const { auth } = await firebase();
      if (kind === "demo") await signInAnonymously(auth);
      else await signInWithPopup(auth, new GoogleAuthProvider());
    } catch (e) {
      const code = (e as { code?: string }).code ?? "";
      setErr(
        code === "auth/popup-closed-by-user"
          ? "The Google window was closed before you signed in. Try again when you're ready."
          : kind === "demo"
            ? "The demo couldn't start. Check your connection and try again."
            : "Google sign-in didn't work. Check your connection and try again.",
      );
      setBusy(null);
    }
  }

  return (
    <div className={size === "large" ? s.actions : s.actionsSmall}>
      <div className={s.actionRow}>
        <button type="button" className={s.primary} disabled={busy !== null} onClick={() => go("demo")}>
          {busy === "demo" ? "Starting the demo…" : "Try the demo"}
          {busy !== "demo" && <Icon name="arrow" size={size === "large" ? 18 : 16} />}
        </button>
        {!demoOnly && (
          <button type="button" className={s.secondary} disabled={busy !== null} onClick={() => go("google")}>
            {busy === "google" ? "Opening Google…" : "Sign in with Google"}
          </button>
        )}
      </div>
      {err && (
        <p className={s.error} role="alert">
          {err}
        </p>
      )}
    </div>
  );
}
