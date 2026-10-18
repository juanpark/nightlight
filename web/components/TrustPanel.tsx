"use client";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Go } from "@/lib/needsYou";
import type { Device, Level, TrustDoc } from "@/lib/types";

const LEVELS: { id: Level; label: string }[] = [
  { id: "ask", label: "Always ask me" }, { id: "ask_new", label: "Ask me for new things" },
  { id: "auto", label: "Just handle it and tell me" },
];

/** The trust ladder works on the sample home; on the owner's own devices every change waits for a tap, and what each
 * device allows lives in its own Settings. So a real home leads with that, and the ladder shows only with the sample. */
export default function TrustPanel({ trust, devices, sample, onGo }: {
  trust: TrustDoc[]; devices: Device[]; sample: boolean; onGo: (g: Go) => void; // sample: the sample home is showing
}) {
  const real = devices.filter((d) => d.realm === "real");
  // kinds with something to show (a success, an offer, a level above asking) first; the rest folded away
  const active = (t: TrustDoc) => (t.successes ?? []).length > 0 || !!t.offer || (t.ceiling === "auto" && t.level !== "ask");
  const busy = trust.filter(active), rest = trust.filter((t) => !active(t));
  const quiet = rest.length > 2;
  const [err, setErr] = useState("");
  async function call(fn: () => Promise<unknown>) {
    setErr("");
    try { await fn(); } catch (e) { setErr(e instanceof ApiError ? "Couldn't change that. Please try again." : "Something went wrong"); }
  }
  return (
    <div className="panel">
      <h3 style={{ marginBottom: 2 }}>Trust</h3>
      <p className="small muted" style={{ marginTop: 0 }}>How much Nightlight does on its own</p>
      {real.length > 0 && (<>
        <p className="small" style={{ marginTop: 0 }}>On your own devices every change waits for your tap (by design).
          What Nightlight may do on each device is set in that device&apos;s Settings; fixes that worked are saved per
          device under <em>Knowledge → Fixes that worked here</em>.</p>
        <div className="list">
          {real.map((d) => (
            <div key={d.id} className="item">
              <span style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{d.name}</span>
              <button className="small" onClick={() => onGo({ to: "drawer", deviceId: d.id, tab: "settings" })}>Settings</button>
            </div>))}
        </div>
      </>)}
      {sample && (<>
      {real.length > 0 && <h4 style={{ marginBottom: 4 }}>Sample home</h4>}
      <p className="small" style={{ marginTop: 0 }}>Nightlight asks before every change. For the safe jobs below, after
        three go well it offers to handle them on its own; you can also set that here. Restarts and updates always ask.
        If a job fails, it goes back to asking.</p>
      <div className="list">
        {(quiet ? busy : trust).map((t) => row(t))}
        {quiet && rest.length > 0 && (
          <details className="small">
            <summary className="muted">{busy.length ? `Other kinds of job (${rest.length}, nothing yet)`
              : `Nothing has gone well yet. See the ${rest.length} kinds of job`}</summary>
            <div className="list" style={{ marginTop: 6 }}>{rest.map((t) => row(t))}</div>
          </details>)}
        {trust.length === 0 && <span className="muted small">Nothing yet.</span>}
      </div>
      </>)}
      {!sample && real.length === 0 && <p className="small muted">Add a device first: what Nightlight may do is set
        per device, in its Settings.</p>}
      {err && <p className="small" style={{ color: "var(--crit-ink)" }}>{err}</p>}
    </div>
  );

  function row(t: TrustDoc) {
    return (
          <div key={t.id} className="item" style={{ flexWrap: "wrap" }}>
            <span style={{ flex: 1, minWidth: 180 }}>{t.label} <span className={`risk ${t.riskClass}`}>
              {t.riskClass === "routine" ? "Safe" : t.riskClass === "service" ? "Some risk" : "Risky"}</span></span>
            {/* only safe kinds can ever run on their own; for the rest the other choices would change nothing */}
            {t.ceiling === "auto"
              ? <select value={t.level} onChange={(e) => call(() => api("PUT", `/api/trust/${t.actionType}`,
                  { level: e.target.value, deviceId: null, svcId: null, pinned: false }))}>
                  {LEVELS.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
                </select>
              : <span className="small">Always asks</span>}
            <span className="small muted">{(t.successes ?? []).length} went well</span>
            {t.offer && (
              <div className="card" style={{ width: "100%" }}>
                <div>{t.offer.text}</div>
                <div className="actions">
                  <button className="primary" onClick={() => call(() => api("POST", `/api/trust/${t.actionType}/promotion`,
                    { accept: true, offerId: t.offer!.offerId }))}>Yes, handle it</button>
                  <button onClick={() => call(() => api("POST", `/api/trust/${t.actionType}/promotion`,
                    { accept: false, offerId: t.offer!.offerId }))}>Keep asking me</button>
                </div>
              </div>
            )}
          </div>
    );
  }
}
