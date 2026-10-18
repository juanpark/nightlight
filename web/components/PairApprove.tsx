"use client";
// "Your device shows a code": look the code up, show which device asked, then Approve or This isn't mine. A device
// that was here before (reinstalled, or removed and not yet purged) can continue its history instead of starting anew.
// Used in Add a device and on /pair (the page a phone opens from the device's QR code).
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { timeAgo } from "@/lib/time";

export const CODE_RE = /^[A-Z0-9]{4}-?[A-Z0-9]{4}$/;

/** "wxyz 1234" → "WXYZ-1234"; anything else is returned upper-cased so the check can reject it. */
export function normalCode(raw: string) {
  const s = raw.trim().toUpperCase().replace(/\s+/g, "");
  return /^[A-Z0-9]{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4)}` : s;
}

interface Preview { name: string; os?: string; expiresAt?: string;
  continues?: { deviceId: string; name: string; lastSeen: string | null; removed?: boolean } | null }
export type PairResult = { approved: boolean; name: string; continued?: string }; // continued: the earlier device's id

function message(e: unknown) {
  if (e instanceof ApiError) {
    if (e.status === 404) return "That code didn't match, or it has expired (codes last 10 minutes). Check the code on the device.";
    if (e.status === 409) return "That code has already been answered.";
    if (e.status === 401 || e.status === 403 || e.code === "sign_in_required") return "Please sign in with Google first.";
  }
  return "Something went wrong. Please try again.";
}

export default function PairApprove({ initialCode = "", onApprove, onDone, base = "/api/devices/pair" }: {
  initialCode?: string;
  base?: string; // the sample home's simulated install approves at /api/demo/pair
  /** Called just before the approval is sent (Add a device uses it to remember which devices already exist). */
  onApprove?: () => void;
  onDone: (r: PairResult) => void;
}) {
  const [raw, setRaw] = useState(initialCode);
  const [preview, setPreview] = useState<{ code: string; p: Preview } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [keep, setKeep] = useState(true); // continue the earlier device's history (the default when there is one)
  const code = normalCode(raw);
  const valid = CODE_RE.test(code);

  async function look(c = code) {
    setBusy(true); setErr(""); setPreview(null);
    try {
      setPreview({ code: c, p: await api<Preview>("GET", `${base}/${encodeURIComponent(c)}`) });
      setKeep(true);
    } catch (e) {
      setErr(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function decide(approve: boolean) {
    if (!preview) return;
    setBusy(true); setErr("");
    if (approve) onApprove?.();
    try {
      const path = `${base}/${encodeURIComponent(preview.code)}`;
      // continueDevice only when there is something to continue (an API without it refuses unknown fields)
      let continued: string | undefined;
      if (approve && preview.p.continues) {
        try { continued = (await api<{ continues?: string | null }>("POST", path, { approve, continueDevice: keep })).continues ?? undefined; }
        catch (e) {
          if (!(e instanceof ApiError && e.code === "nothing_to_continue")) throw e;
          await api("POST", path, { approve }); // the earlier device is gone after all: add it as new
        }
      } else await api("POST", path, { approve });
      onDone({ approved: approve, name: preview.p.name, continued });
    } catch (e) {
      setErr(message(e));
      setBusy(false);
    }
  }

  // Opened from a QR code: look the code up straight away.
  useEffect(() => {
    const c = normalCode(initialCode);
    if (CODE_RE.test(c)) look(c);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialCode]);

  return (
    <div className="pairbox">
      {!preview ? (
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (valid) look(); }}>
          <input aria-label="Code shown on your device" placeholder="WXYZ-1234" value={raw} maxLength={12}
            autoCapitalize="characters" autoComplete="off" spellCheck={false} className="code-input"
            onChange={(e) => { setRaw(e.target.value); setErr(""); }} />
          <button type="submit" disabled={!valid || busy}>{busy ? "Looking…" : "Look it up"}</button>
        </form>
      ) : (
        <div className="card">
          <strong>Add “{preview.p.name}”{preview.p.os ? ` (${preview.p.os})` : ""}?</strong>
          <span className="small muted">Only approve a device you just set up yourself. Code {preview.code}.</span>
          {preview.p.continues && (() => {
            const c = preview.p.continues;
            const seen = c.lastSeen ? `, last seen ${timeAgo(new Date(c.lastSeen))}` : "";
            return (
              <fieldset className="pair-continue">
                <legend>This looks like your {c.name}{seen}{c.removed ? " (removed)" : ""}. Continue its history?</legend>
                <label><input type="radio" name="continue" checked={keep} onChange={() => setKeep(true)} />{" "}
                  <strong>Continue its history</strong> <span className="small muted">(keeps its notes, saved fixes,
                    jobs and place on the map)</span></label>
                <label><input type="radio" name="continue" checked={!keep} onChange={() => setKeep(false)} />{" "}
                  <strong>Add as a new device</strong></label>
              </fieldset>);
          })()}
          <div className="actions">
            <button className="primary" disabled={busy} onClick={() => decide(true)}>Approve</button>
            <button disabled={busy} onClick={() => decide(false)}>This isn’t mine</button>
          </div>
        </div>
      )}
      {err && <p className="small" style={{ color: "var(--crit-ink)" }}>{err}</p>}
    </div>
  );
}
