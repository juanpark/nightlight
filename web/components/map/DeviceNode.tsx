"use client";
// One device on the map, read at a glance: its icon ringed in its status colour, its status in a word with one plain
// line (its top problem, or "All good"), up to three starred apps by name, a dot per app it runs, and a mark when something needs the person. Zoomed out, only the icon and name stay.
// Hover or select it for quick actions; drag from an edge dot to another device to draw a relationship.
import { memo, useLayoutEffect, useRef } from "react";
import { Handle, NodeToolbar, Position, useStore, type Node, type NodeProps } from "@xyflow/react";
import { Info, Grid as LayoutGrid, Chat as MessageCircle, Star } from "@/src/components/icons";
import { answering, type Need } from "@/lib/needsYou";
import { APP_CAP, appOrder } from "@/lib/apps";
import { useServices } from "@/lib/data";
import { named, type StepState } from "@/lib/follow";

const LIT_WORDS: Record<StepState, string> = { checking: "Checking…", found: "Found something", done: "Done" };
import type { Device } from "@/lib/types";
import NeedsMark from "../NeedsMark";
import StatusWord, { deviceLine, deviceTone } from "../StatusWord";
import { appIcon, deviceIcon, roleOf } from "./kinds";

export type DeviceNodeData = {
  device: Device; uid: string; needs?: Need[]; now: number; by?: string; // by: the device that watches it
  favorites?: boolean; // the Favorites filter is on: starred apps stand out
  focused?: boolean; // opened in place: every app as a chip
  lit?: "working" | "done"; litApps?: string[]; // the chat's answer is working on it / worked on it, and the apps it named
  litState?: StepState; settle?: boolean; // how its steps are going; the answer's main device, just finished
  onOpen: (id: string) => void; onAsk: (q: string) => void;
  onFocus: (id: string) => void; onApp: (id: string, svcId: string) => void;
  onSize: (id: string, h: number) => void; // an opened card says how tall it grew, so its neighbours make room
};
export type DeviceNodeType = Node<DeviceNodeData, "device">;

const SIDES = [Position.Top, Position.Right, Position.Bottom, Position.Left];

function DeviceNode({ data, selected }: NodeProps<DeviceNodeType>) {
  const { device: d, needs, now } = data;
  const services = useServices(data.uid, d.id);
  const compact = useStore((s) => s.transform[2] < 0.45); // zoomed far out: icon and name only
  const Icon = deviceIcon(d);
  const sample = d.realm !== "real";
  const bad = services.filter((s) => (s.status ?? "ok") !== "ok").length;
  // the apps the owner starred, in the order they starred them
  const favs = (d.favoriteApps ?? []).map((id) => services.find((s) => s.id === id)).filter((s) => !!s).slice(0, 3);
  const box = useRef<HTMLDivElement>(null);
  const { focused, onSize } = data;
  useLayoutEffect(() => {
    const el = box.current;
    if (!focused || !el) return;
    const ro = new ResizeObserver(() => onSize(d.id, el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, [focused, onSize, d.id]);
  const tools = (
    <NodeToolbar position={Position.Top} className="dtools">
      <button onClick={() => data.onAsk(`How is my ${d.name} doing?`)}><MessageCircle size={14} /> Ask</button>
      {d.kind !== "watched" && services.length > 0 && !focused &&
        <button onClick={() => data.onFocus(d.id)}><LayoutGrid size={14} /> Open</button>}
      <button onClick={() => data.onOpen(d.id)}><Info size={14} /> Details</button>
    </NodeToolbar>
  );
  // A thing a helper watches (a router, a printer…): Nightlight only knows whether it answers, so no gauges.
  if (d.kind === "watched") {
    return (
      <div className={`dnode watched ${d.status} ${roleOf(d) === "router" ? "router" : ""} ${selected ? "sel" : ""} ${compact ? "compact" : ""} ${data.lit ? `lit-${data.lit}` : ""}`}
        onDoubleClick={() => data.onOpen(d.id)}>
        {SIDES.map((p) => <Handle key={p} id={p} type="source" position={p} className="dhandle" />)}
        {tools}
        <div className="dhead">
          <span className={`dicon ${d.status}`}><Icon size={compact ? 26 : 18} /></span>
          <strong className="dname" title={d.purpose ?? d.name}>{d.name}</strong>
          {d.favorite && <Star className="dstar" size={13} weight="fill" aria-label="Favorite" />}
          <NeedsMark needs={needs} />
        </div>
        {!compact && <div className="dstate"><StatusWord tone={deviceTone(d)} />
          <span className="dline">{answering(d, now).replace(/^./, (c) => c.toUpperCase())}</span></div>}
        {!compact && data.by && <div className="dby">watched by the {data.by}</div>}
      </div>
    );
  }
  const shown = focused ? appOrder(services, d.favoriteApps ?? []) : [];
  return (
    <div ref={box} className={`dnode ${d.status} ${sample ? "sample" : ""} ${selected ? "sel" : ""} ${compact ? "compact" : ""} ${focused ? "focused" : ""} ${data.lit ? `lit-${data.lit}` : ""} ${data.settle ? "settle" : ""}`}
      onDoubleClick={() => data.onOpen(d.id)}>
      {data.litState && <span className={`dlit ${data.litState}`} role="status">
        {/* a step here finished but the answer is still going: "Checked", and "Done" only once it is over */}
        {data.litState === "done" && data.lit === "working" ? "Checked" : LIT_WORDS[data.litState]}</span>}
      {SIDES.map((p) => <Handle key={p} id={p} type="source" position={p} className="dhandle" />)}
      {tools}
      <div className="dhead">
        <span className={`dicon ${d.status}`}><Icon size={compact ? 26 : 18} /></span>
        <strong className="dname" title={d.purpose ?? d.name}>{d.name}</strong>
        {d.favorite && <Star className="dstar" size={13} weight="fill" aria-label="Favorite" />}
        <NeedsMark needs={needs} />
      </div>
      {!compact && <div className="dstate">
        <StatusWord tone={d.starting ? "later" : deviceTone(d)} word={d.starting ? "Starting" : undefined} />
        <span className="dline">{deviceLine(d, now)}</span>
      </div>}
      {focused && ( // an opened card shows its apps at any zoom
        <div className="dappgrid" role="group" aria-label={`Apps on ${d.name}`}>
          {shown.slice(0, APP_CAP).map((s) => {
            const Icon = appIcon(s);
            const fav = (d.favoriteApps ?? []).includes(s.id);
            return (
              <button key={s.id} className={`dchip ${s.status ?? "ok"} ${fav && data.favorites ? "hl" : ""} ${named(s, data.litApps) ? "lit-app" : ""} nodrag`}
                title={`${s.name}: ${s.status ?? "ok"}`}
                onClick={(e) => { e.stopPropagation(); data.onApp(d.id, s.id); }}>
                <Icon size={12} aria-hidden /><span>{s.name}</span>
                {fav && <Star className="dstar" size={10} weight="fill" aria-label="Favorite" />}
              </button>);
          })}
          {shown.length > APP_CAP && (
            <button className="dchip more nodrag" onClick={(e) => { e.stopPropagation(); data.onOpen(d.id); }}>
              +{shown.length - APP_CAP} more</button>)}
        </div>)}
      {!focused && !compact && favs.length > 0 && (
        <div className={`dfavs ${data.favorites ? "hl" : ""}`}>
          {favs.map((s) => {
            const Icon = appIcon(s);
            return <span key={s.id} className={`dchip ${s.status ?? "ok"} ${named(s, data.litApps) ? "lit-app" : ""}`} title={`${s.name}: ${s.status ?? "ok"}`}>
              <Icon size={12} aria-hidden /><span>{s.name}</span></span>;
          })}
        </div>)}
      {!focused && !compact && services.length > 0 && (
        <button className="dapps nodrag" title={`See all ${services.length}: ${services.map((s) => s.name).join(", ")}`}
          aria-label={`See the ${services.length} app${services.length === 1 ? "" : "s"} on ${d.name}`}
          onClick={(e) => { e.stopPropagation(); data.onFocus(d.id); }}>
          {services.slice(0, 5).map((s) => <span key={s.id} className={`dot ${s.status ?? "ok"}`} />)}
          {services.length > 5 && <span className="more">+{services.length - 5}</span>}
          <span className="dapps-text">{services.length} app{services.length === 1 ? "" : "s"}
            {bad > 0 && <b> · {bad} need{bad === 1 ? "s" : ""} a look</b>}</span>
        </button>)}
    </div>
  );
}

export default memo(DeviceNode);
