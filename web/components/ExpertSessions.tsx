"use client";
// Expert sessions for one device: the owner's passkey (created once, in this browser) and whether the device has
// pinned it. Pinning happens on the device itself (`nightlight expert`), after comparing the code shown here, so
// Nightlight's cloud can't switch expert sessions on.
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { createPasskey, passkeysSupported } from "@/lib/passkey";

const localKey = (uid: string) => `nl_passkey_fp_${uid}`;
import type { Device } from "@/lib/types";

export default function ExpertSessions({ uid, device }: { uid: string; device: Device }) {
  const [key, setKey] = useState<{ enabled: boolean; fingerprint?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => { api<{ enabled: boolean; fingerprint?: string }>("GET", "/api/expert").then(setKey).catch(() => {}); }, []);
  const on = (device.allowedJobs?.expert ?? []).includes("on");
  // The code worked out in THIS browser when the passkey was made (not taken from the server).
  const [mine, setMine] = useState<string | null>(null);
  useEffect(() => { try { setMine(localStorage.getItem(localKey(uid))); } catch { /* private mode */ } }, [uid]);

  async function create() {
    setBusy(true); setErr("");
    try {
      const options = await api<Parameters<typeof createPasskey>[0]>("POST", "/api/expert/register/options", {});
      const made = await createPasskey(options);
      const saved = await api<{ fingerprint: string }>("POST", "/api/expert/register", made.credential);
      if (made.fingerprint) {
        try { localStorage.setItem(localKey(uid), made.fingerprint); } catch { /* private mode */ }
        setMine(made.fingerprint);
      }
      setKey({ enabled: true, ...saved });
    } catch (e) {
      setErr(e instanceof ApiError ? (e.code === "sign_in_required" ? "Sign in first." : e.code)
        : "The passkey wasn't created (cancelled or not supported here).");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="expert small">
      <button className="linkish" onClick={() => setOpen(!open)}>
        Expert sessions {on ? "(on)" : "(off)"} {open ? "▾" : "▸"}</button>
      {open && (
        <div className="expert-body">
          <p className="muted">Let Nightlight investigate with real commands, the way a system administrator would.
            Read-only commands need one tap of your passkey per 15 minutes; anything that changes something needs
            your passkey on each command. The device checks your signature itself, so even Nightlight&apos;s own
            servers can&apos;t run anything without you.</p>
          <ol>
            <li>Your passkey: {key?.enabled
              ? mine
                ? mine === key.fingerprint
                  ? <>ready, code <strong>{mine}</strong></>
                  : <strong style={{ color: "var(--crit)" }}>the server shows a different key ({key.fingerprint}) than
                      the passkey this browser made ({mine}): don&apos;t switch it on anywhere; tell us.</strong>
                : <>ready (made in another browser: compare the code there), server copy <strong>{key.fingerprint}</strong></>
              : passkeysSupported()
                ? <button disabled={busy} onClick={create}>{busy ? "Waiting…" : "Create my passkey"}</button>
                : <span className="muted">this browser can&apos;t create passkeys</span>}</li>
            <li>On the device: {on ? <strong>on</strong> : <>run <code className="perm-cmd">nightlight expert</code> there
              (if that says &quot;command not found&quot;: <code className="perm-cmd">~/.local/bin/nightlight expert</code>) and
              check it shows exactly the code above{mine ? <> ({mine})</> : null}.</>}</li>
          </ol>
          {err && <div style={{ color: "var(--crit)" }}>{err}</div>}
        </div>)}
    </section>
  );
}
