"use client";
import { useMemo, useState } from "react";
import type { Action, Device, EventDoc } from "@/lib/types";

type Who = "you" | "auto" | "device" | "nightlight";
interface Row { id: string; at: number; who: Who; deviceId?: string; text: string; dot: string; problem: boolean }

const WHO_LABEL: Record<Who, string> = { you: "You", auto: "Automatically", device: "Device", nightlight: "Nightlight" };
const RANGES = { today: 1, week: 7, all: 3650 } as const;

function day(ts: number) {
  const d = new Date(ts), now = new Date();
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(d, now)) return "Today";
  if (same(d, new Date(now.getTime() - 86400000))) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

/** Everything that happened, newest first, as "who did what to what, and the result". Filterable. */
export default function Activity({ events, actions, devices }: {
  events: EventDoc[]; actions: Action[]; devices: Device[];
}) {
  const [device, setDevice] = useState("all");
  const [who, setWho] = useState<"all" | Who | "problems">("all");
  const [range, setRange] = useState<keyof typeof RANGES>("week");
  const name = (id?: string) => devices.find((d) => d.id === id)?.name ?? "a device";

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    for (const a of actions) {
      if (!["done", "failed", "denied"].includes(a.status)) continue;
      const by: Who = a.decision?.by === "auto" ? "auto" : a.type === "diagnose" ? "nightlight" : "you";
      const verb = a.type === "diagnose" ? "looked into" : a.status === "denied" ? "declined" : "approved";
      const what = a.result?.summary ?? a.plan;
      out.push({ id: a.id, at: a.createdAt?.getTime() ?? 0, who: by, deviceId: a.deviceId, problem: a.status === "failed",
        dot: a.status === "done" ? "ok" : a.status === "failed" ? "crit" : "offline",
        text: by === "auto" ? `Handled on its own on ${name(a.deviceId)}: ${what}`
          : by === "nightlight" ? `Nightlight ${verb} ${a.deviceId ? name(a.deviceId) : ""}: ${what}`
          : `You ${verb}: ${what}` });
    }
    for (const e of events) {
      const w: Who = e.who === "you" ? "you" : e.who === "auto" ? "auto" : "device";
      out.push({ id: e.id, at: e.at?.getTime() ?? 0, who: w, deviceId: e.deviceId, text: e.message,
        dot: e.severity === "info" ? "ok" : e.severity, problem: e.severity !== "info" });
    }
    return out.sort((a, b) => b.at - a.at);
  }, [actions, events, devices]); // eslint-disable-line react-hooks/exhaustive-deps

  const since = Date.now() - RANGES[range] * 86400000;
  const shown = rows.filter((r) => r.at >= since && (device === "all" || r.deviceId === device)
    && (who === "all" || (who === "problems" ? r.problem : r.who === who)));
  const groups = shown.reduce<Record<string, Row[]>>((g, r) => ((g[day(r.at)] ??= []).push(r), g), {});

  return (
    <div className="panel">
      <h3>What happened</h3>
      <div className="filters">
        <select value={device} onChange={(e) => setDevice(e.target.value)} aria-label="Device">
          <option value="all">All devices</option>
          {devices.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select value={who} onChange={(e) => setWho(e.target.value as typeof who)} aria-label="Kind">
          <option value="all">Everything</option>
          <option value="problems">Only problems</option>
          {(Object.keys(WHO_LABEL) as Who[]).map((k) => <option key={k} value={k}>{WHO_LABEL[k]}</option>)}
        </select>
        <select value={range} onChange={(e) => setRange(e.target.value as keyof typeof RANGES)} aria-label="When">
          <option value="today">Today</option>
          <option value="week">Last 7 days</option>
          <option value="all">All time</option>
        </select>
        <span className="small muted">{shown.length} of {rows.length}</span>
      </div>
      {Object.entries(groups).map(([label, list]) => (
        <div key={label} style={{ marginTop: 10 }}>
          <div className="small muted" style={{ fontWeight: 600 }}>{label}</div>
          <div className="list">
            {list.map((r) => (
              <div key={r.id} className="item">
                <span className={`dot ${r.dot}`} style={{ marginTop: 4 }} />
                <span style={{ flex: 1 }}>{r.text}</span>
                <span className="small muted">{r.at ? new Date(r.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
      {shown.length === 0 && <p className="muted small">Nothing here for these filters.</p>}
    </div>
  );
}
