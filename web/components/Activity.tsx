"use client";
import type { Action, Device, EventDoc } from "@/lib/types";

const WHO = (a: Action) => a.decision?.by === "auto" ? "done automatically"
  : a.status === "denied" ? "you declined" : "with your approval";

export default function Activity({ events, actions, devices }: {
  events: EventDoc[]; actions: Action[]; devices: Device[];
}) {
  const name = (id?: string) => devices.find((d) => d.id === id)?.name ?? "";
  const finished = actions.filter((a) => ["done", "failed", "denied"].includes(a.status))
    .sort((a, b) => (b.createdAt?.getTime() ?? 0) - (a.createdAt?.getTime() ?? 0));
  return (
    <div className="panel">
      <h3>What happened</h3>
      <div className="list">
        {finished.map((a) => (
          <div key={a.id} className="item">
            <span className={`dot ${a.status === "done" ? "ok" : a.status === "failed" ? "crit" : "offline"}`} />
            <span>{a.result?.summary ?? a.plan} <span className="muted">({name(a.deviceId)}, {WHO(a)})</span></span>
          </div>
        ))}
        {events.slice(0, 10).map((e) => (
          <div key={e.id} className="item">
            <span className={`dot ${e.severity === "info" ? "ok" : e.severity}`} />
            <span>{e.message} <span className="muted">{e.at?.toLocaleTimeString()}</span></span>
          </div>
        ))}
        {finished.length + events.length === 0 && <span className="muted small">Nothing yet.</span>}
      </div>
    </div>
  );
}
