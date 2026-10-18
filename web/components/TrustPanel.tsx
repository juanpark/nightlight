"use client";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Go } from "@/lib/needsYou";
import type { Device, Level, TrustDoc } from "@/lib/types";

const LEVELS: { id: Level; label: string }[] = [
  { id: "ask", label: "Always ask me" }, { id: "ask_new", label: "Ask me for new things" },
  { id: "auto", label: "Just handle it and tell me" },
];
const ORDER: Level[] = ["ask", "ask_new", "auto"];

/** The trust ladder works on the sample home; on the owner's own devices every change waits for a tap, and what each
 * device allows lives in its own Settings. So a real home leads with that, and the ladder shows only with the sample. */
export default function TrustPanel({ trust, devices, sample, onGo }: {
  trust: TrustDoc[]; devices: Device[]; sample: boolean; onGo: (g: Go) => void; // sample: the sample home is showing
}) {
  const real = devices.filter((d) => d.realm === "real");
  const [err, setErr] = useState("");
  async function call(fn: () => Promise<unknown>) {
    setErr("");
    try { await fn(); } catch (e) { setErr(e instanceof ApiError ? "Couldn't change that. Please try again." : "Something went wrong"); }
  }
  return (
    <div className="panel">
      <h3>How much Nightlight does on its own</h3>
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
      <p className="small muted" style={{ marginTop: 0 }}>For each kind of job on the sample home, choose whether
        Nightlight asks you first. Risky jobs always ask. If a job ever fails, it goes back to asking.</p>
      <div className="list">
        {trust.map((t) => (
          <div key={t.id} className="item" style={{ flexWrap: "wrap" }}>
            <span style={{ flex: 1, minWidth: 180 }}>{t.label} <span className={`risk ${t.riskClass}`}>
              {t.riskClass === "routine" ? "Safe" : t.riskClass === "service" ? "Some risk" : "Risky"}</span></span>
            <select value={t.level} onChange={(e) => call(() => api("PUT", `/api/trust/${t.actionType}`,
              { level: e.target.value, deviceId: null, svcId: null, pinned: false }))}>
              {LEVELS.filter((l) => ORDER.indexOf(l.id) <= ORDER.indexOf(t.ceiling)).map((l) =>
                <option key={l.id} value={l.id}>{l.label}</option>)}
            </select>
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
        ))}
        {trust.length === 0 && <span className="muted small">Nothing yet.</span>}
      </div>
      </>)}
      {!sample && real.length === 0 && <p className="small muted">Add a device first: what Nightlight may do is set
        per device, in its Settings.</p>}
      {err && <p className="small" style={{ color: "var(--crit-ink)" }}>{err}</p>}
    </div>
  );
}
