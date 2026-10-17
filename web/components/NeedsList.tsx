"use client";
// Rows of "needs you" items with one action each. Used at the top of a device panel and in the strip above the map.
import { useState } from "react";
import { api } from "@/lib/api";
import type { Go, Need } from "@/lib/needsYou";
import type { Action, Device } from "@/lib/types";
import ApprovalCard from "./ApprovalCard";

const TONE = { 1: "crit", 2: "warn", 3: "offline" } as const;

export default function NeedsList({ needs, actions, devices, onGo, onFollowUp, max = 3, showDevice = false }: {
  needs: Need[]; actions: Action[]; devices: Device[]; onGo: (go: Go) => void; onFollowUp: (turnId: string) => void;
  max?: number; showDevice?: boolean;
}) {
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  if (!needs.length) return null;
  const shown = all ? needs : needs.slice(0, max);
  const name = (id?: string) => devices.find((d) => d.id === id)?.name;
  return (
    <div className="needs-list">
      {shown.map((n) => (
        <div key={n.id}>
          <div className="needs-row">
            <span className={`dot ${TONE[n.priority]}`} />
            <span className="needs-text">
              {showDevice && name(n.deviceId) && <span className="muted">{name(n.deviceId)}: </span>}
              {n.title}{n.detail && <span className="muted small"> · {n.detail}</span>}
            </span>
            {n.cta.go.to === "offer"
              ? <>
                  <button className="primary small" onClick={() => offer(n.cta.go, true)}>Yes, handle it</button>
                  <button className="small" onClick={() => offer(n.cta.go, false)}>Keep asking me</button>
                </>
              : n.cta.go.to === "card"
                ? <button className={`small ${n.priority < 3 ? "primary" : ""}`}
                    onClick={() => setOpen(open === n.id ? null : n.id)}>{open === n.id ? "Hide" : n.cta.label}</button>
                : <button className="small" onClick={() => onGo(n.cta.go)}>{n.cta.label}</button>}
          </div>
          {open === n.id && n.cta.go.to === "card" && (() => {
            const a = actions.find((x) => x.id === (n.cta.go as { actionId: string }).actionId);
            return <ApprovalCard action={a} device={devices.find((d) => d.id === a?.deviceId)} onFollowUp={onFollowUp} />;
          })()}
        </div>
      ))}
      {needs.length > max && <button className="linkish small" onClick={() => setAll(!all)}>
        {all ? "Show fewer" : `Show all ${needs.length}`}</button>}
    </div>
  );
}

function offer(go: Go, accept: boolean) {
  if (go.to !== "offer") return;
  api("POST", `/api/trust/${go.actionType}/promotion`, { accept, offerId: go.offerId }).catch(() => {});
}
