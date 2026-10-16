"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Action, Device, TrustDoc } from "@/lib/types";
import ApprovalCard from "./ApprovalCard";

/** Everything waiting for a decision, in one place: approval cards (also after a reload) and trust offers. */
export default function NeedsYou({ actions, trust, devices, onFollowUp }: {
  actions: Action[]; trust: TrustDoc[]; devices: Device[]; onFollowUp: (turnId: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const cards = actions.filter((a) => a.status === "pending" || a.status === "approved" || a.status === "running")
    .sort((a, b) => (b.createdAt?.getTime() ?? 0) - (a.createdAt?.getTime() ?? 0));
  const offers = trust.filter((t) => t.offer);
  if (cards.length === 0 && offers.length === 0) return null;
  const name = (id: string) => devices.find((d) => d.id === id)?.name ?? "a device";
  return (
    <div className="panel">
      <h3>Waiting for you</h3>
      <div className="list">
        {cards.map((a) => (
          <div key={a.id}>
            <div className="item" style={{ alignItems: "center" }}>
              <span className={`dot ${a.status === "pending" ? "warn" : "ok"}`} />
              <span style={{ flex: 1 }}>{a.plan} <span className="muted small">({name(a.deviceId)}
                {a.status === "approved" ? ", waiting for the device" : a.status === "running" ? ", running" : ""})</span></span>
              <button className={a.status === "pending" ? "primary" : ""} onClick={() => setOpen(open === a.id ? null : a.id)}>
                {open === a.id ? "Hide" : a.status === "pending" ? "Review" : "Details"}</button>
            </div>
            {open === a.id && <ApprovalCard action={a} device={devices.find((d) => d.id === a.deviceId)}
              onFollowUp={onFollowUp} />}
          </div>
        ))}
        {offers.map((t) => (
          <div key={t.id} className="item" style={{ alignItems: "center", flexWrap: "wrap" }}>
            <span className="dot ok" />
            <span style={{ flex: 1 }}>{t.offer!.text}</span>
            <button className="primary" onClick={() => api("POST", `/api/trust/${t.actionType}/promotion`,
              { accept: true, offerId: t.offer!.offerId }).catch(() => {})}>Yes, handle it</button>
            <button onClick={() => api("POST", `/api/trust/${t.actionType}/promotion`,
              { accept: false, offerId: t.offer!.offerId }).catch(() => {})}>Keep asking me</button>
          </div>
        ))}
      </div>
    </div>
  );
}
