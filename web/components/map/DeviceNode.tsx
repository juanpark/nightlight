"use client";
// One device on the map, read at a glance: its icon ringed in its status colour, three small gauges (disk, memory,
// CPU), a dot per app it runs, and a mark when something needs the person. Zoomed out, only the icon and name stay.
// Hover or select it for quick actions; drag from an edge dot to another device to draw a relationship.
import { memo } from "react";
import { Handle, NodeToolbar, Position, useStore, type Node, type NodeProps } from "@xyflow/react";
import { Info, MessageCircle } from "lucide-react";
import { ago, answering, type Need } from "@/lib/needsYou";
import { useServices } from "@/lib/data";
import type { Device } from "@/lib/types";
import NeedsMark from "../NeedsMark";
import { deviceIcon, roleOf } from "./kinds";

export type DeviceNodeData = {
  device: Device; uid: string; needs?: Need[]; now: number; by?: string; // by: the device that watches it
  onOpen: (id: string) => void; onAsk: (q: string) => void;
};
export type DeviceNodeType = Node<DeviceNodeData, "device">;

const tone = (v?: number | null) => v == null ? "none" : v >= 90 ? "crit" : v >= 75 ? "warn" : "ok";

/** A small ring gauge: the arc is the value, the number sits inside. */
function Gauge({ label, value }: { label: string; value?: number | null }) {
  const r = 13, c = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.min(100, Math.max(0, value));
  return (
    <div className={`gauge ${tone(value)}`} title={`${label}: ${value == null ? "unknown" : `${Math.round(v)}%`}`}>
      <svg viewBox="0 0 32 32" width="32" height="32" aria-hidden>
        <circle cx="16" cy="16" r={r} className="g-track" />
        <circle cx="16" cy="16" r={r} className="g-arc" strokeDasharray={`${(v / 100) * c} ${c}`}
          transform="rotate(-90 16 16)" />
        <text x="16" y="19.5" textAnchor="middle">{value == null ? "–" : Math.round(v)}</text>
      </svg>
      <span>{label}</span>
    </div>
  );
}

const SIDES = [Position.Top, Position.Right, Position.Bottom, Position.Left];

function DeviceNode({ data, selected }: NodeProps<DeviceNodeType>) {
  const { device: d, needs, now } = data;
  const services = useServices(data.uid, d.id);
  const compact = useStore((s) => s.transform[2] < 0.45); // zoomed far out: icon and name only
  const Icon = deviceIcon(d);
  const sample = d.realm !== "real";
  const silent = d.realm === "real" && d.status === "offline";
  const bad = services.filter((s) => (s.status ?? "ok") !== "ok").length;
  const tools = (
    <NodeToolbar position={Position.Top} className="dtools">
      <button onClick={() => data.onAsk(`How is my ${d.name} doing?`)}><MessageCircle size={14} /> Ask</button>
      <button onClick={() => data.onOpen(d.id)}><Info size={14} /> Details</button>
    </NodeToolbar>
  );
  // A thing a helper watches (a router, a printer…): Nightlight only knows whether it answers, so no gauges.
  if (d.kind === "watched") {
    return (
      <div className={`dnode watched ${d.status} ${roleOf(d) === "router" ? "router" : ""} ${selected ? "sel" : ""} ${compact ? "compact" : ""}`}
        onDoubleClick={() => data.onOpen(d.id)}>
        {SIDES.map((p) => <Handle key={p} id={p} type="source" position={p} className="dhandle" />)}
        {tools}
        <div className="dhead">
          <span className={`dicon ${d.status}`}><Icon size={compact ? 26 : 18} strokeWidth={1.8} /></span>
          <strong className="dname" title={d.purpose ?? d.name}>{d.name}</strong>
          <NeedsMark needs={needs} />
        </div>
        {!compact && <div className={`dwatch ${d.status}`}>{answering(d, now)}</div>}
        {!compact && data.by && <div className="dby">watched by the {data.by}</div>}
      </div>
    );
  }
  return (
    <div className={`dnode ${d.status} ${sample ? "sample" : ""} ${selected ? "sel" : ""} ${compact ? "compact" : ""}`}
      onDoubleClick={() => data.onOpen(d.id)}>
      {SIDES.map((p) => <Handle key={p} id={p} type="source" position={p} className="dhandle" />)}
      {tools}
      <div className="dhead">
        <span className={`dicon ${d.status}`}><Icon size={compact ? 26 : 18} strokeWidth={1.8} /></span>
        <strong className="dname" title={d.purpose ?? d.name}>{d.name}</strong>
        <NeedsMark needs={needs} />
      </div>
      {!compact && (silent
        ? <div className="dsilent">Silent for {d.lastSeen ? ago(now - d.lastSeen.getTime()) : "a while"}</div>
        : <div className="dgauges">
            <Gauge label="Disk" value={d.vitals?.diskPct} />
            <Gauge label="Mem" value={d.vitals?.mem} />
            <Gauge label="CPU" value={d.vitals?.cpu} />
          </div>)}
      {!compact && services.length > 0 && (
        <div className="dapps" title={services.map((s) => `${s.name}: ${s.status ?? "ok"}`).join("\n")}>
          {services.slice(0, 5).map((s) => <span key={s.id} className={`dot ${s.status ?? "ok"}`} />)}
          {services.length > 5 && <span className="more">+{services.length - 5}</span>}
          <span className="dapps-text">{services.length} app{services.length === 1 ? "" : "s"}
            {bad > 0 ? <b> · {bad} need{bad === 1 ? "s" : ""} a look</b>
              : (d.status === "crit" || d.status === "warn") && <b className={d.status}> · {d.status === "crit" ? "needs you" : "needs a look"}</b>}</span>
        </div>)}
    </div>
  );
}

export default memo(DeviceNode);
