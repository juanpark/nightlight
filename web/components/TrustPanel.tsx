"use client";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Level, TrustDoc } from "@/lib/types";

const LEVELS: { id: Level; label: string }[] = [
  { id: "ask", label: "Always ask me" }, { id: "ask_new", label: "Ask me for new things" },
  { id: "auto", label: "Just handle it and tell me" },
];
const ORDER: Level[] = ["ask", "ask_new", "auto"];

export default function TrustPanel({ trust }: { trust: TrustDoc[] }) {
  const [err, setErr] = useState("");
  async function call(fn: () => Promise<unknown>) {
    setErr("");
    try { await fn(); } catch (e) { setErr(e instanceof ApiError ? "Couldn't change that. Please try again." : "Something went wrong"); }
  }
  return (
    <div className="panel">
      <h3>How much Nightlight does on its own</h3>
      <p className="small muted" style={{ marginTop: 0 }}>For each kind of job, choose whether Nightlight asks you first.
        Risky jobs always ask. If a job ever fails, it goes back to asking.</p>
      <p className="small muted" style={{ marginTop: 0 }}>This works on the sample home for now. On your own devices,
        every restart, clean-up or removal waits for your tap whatever you choose here; what Nightlight may do on
        each of them is set in that device&apos;s Settings.</p>
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
      {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
    </div>
  );
}
