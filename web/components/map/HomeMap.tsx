"use client";
// The home as a canvas: graph paper you can pan and zoom, devices that snap to it where you drop them, and lines for
// how they relate. It opens fitted to whatever screen it is on. Positions and lines are layout only: saving them
// never touches a device.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import {
  Background, BackgroundVariant, ConnectionMode, Controls, MiniMap, Position, ReactFlow, useNodesState,
  type FinalConnectionState, type NodeChange, type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "@/app/map.css";
import { api } from "@/lib/api";
import type { Need } from "@/lib/needsYou";
import type { Device, Link, LinkKind } from "@/lib/types";
import { litApps, mainDevice, useFollowed } from "@/lib/follow";
import AppSheet from "./AppSheet";
import DeviceNode, { type DeviceNodeType } from "./DeviceNode";
import LinkEdge, { type LinkEdgeType } from "./LinkEdge";
import { GRID, LINK, LINK_KINDS, NODE_H, NODE_W } from "./kinds";

const nodeTypes = { device: DeviceNode };
const STATUS_HEX: Record<string, string> = { ok: "#3aa776", warn: "#e0a028", crit: "#d9534f", offline: "#9aa1ad" };
const edgeTypes = { link: LinkEdge };
const snap = (v: number) => Math.round(v / GRID) * GRID;
const stamp = (l: Link) => l.createdAt?.getTime() ?? 0;

/** Where each device sits: its saved spot, nudged right when it would cover another; new ones in a row below. */
function arrange(devices: Device[]): Map<string, { x: number; y: number }> {
  const out = new Map<string, { x: number; y: number }>();
  const clash = (p: { x: number; y: number }) => [...out.values()].some((q) =>
    Math.abs(q.x - p.x) < NODE_W + 20 && Math.abs(q.y - p.y) < NODE_H + 20);
  const order = [...devices].sort((a, b) => Number(a.realm === "real") - Number(b.realm === "real")
    || a.id.localeCompare(b.id));
  const placed = order.filter((d) => d.x != null && d.y != null);
  let nextY = Math.max(0, ...placed.map((d) => d.y!)) + NODE_H + 80, nextX = 0;
  for (const d of order) {
    let p = d.x != null && d.y != null ? { x: snap(d.x), y: snap(d.y) } : { x: nextX, y: snap(nextY) };
    if (d.x == null || d.y == null) nextX += NODE_W + 40;
    while (clash(p)) p = { x: p.x + NODE_W + 40, y: p.y };
    out.set(d.id, p);
  }
  return out;
}

/** The sides a line leaves and enters by, so it takes the short way between two devices. */
function sides(a: { x: number; y: number }, b: { x: number; y: number }): [Position, Position] {
  const dx = b.x - a.x, dy = b.y - a.y;
  if (Math.abs(dx) * (NODE_H / NODE_W) >= Math.abs(dy)) return dx >= 0 ? [Position.Right, Position.Left] : [Position.Left, Position.Right];
  return dy >= 0 ? [Position.Bottom, Position.Top] : [Position.Top, Position.Bottom];
}

const HANDS_OFF_MS = 3000; // the chat leaves the view alone this long after the person last moved it
const FOCUS_ZOOM = 1.3, UNFOCUS_ZOOM = 1.2; // zoomed in this far, the card in the middle opens; a bit less, it closes

/** An opened card grows downward: the cards below it, in its column, move down together to make room. Display only;
 * it is never saved (a drag saves the card's real spot plus how far it was dragged). */
function makeRoom(spots: Map<string, { x: number; y: number }>, id: string, h: number) {
  const f = spots.get(id);
  if (!f || h <= NODE_H) return spots;
  const below = [...spots.entries()].filter(([k, p]) => k !== id && Math.abs(p.x - f.x) < NODE_W + 20 && p.y > f.y);
  const top = Math.min(...below.map(([, p]) => p.y));
  const dy = below.length ? Math.max(0, snap(f.y + h + 40 - top + GRID / 2)) : 0;
  if (!dy) return spots;
  const out = new Map(spots);
  for (const [k, p] of below) out.set(k, { x: p.x, y: p.y + dy });
  return out;
}

export default function HomeMap({ uid, devices, links, marks, selected, onSelect, onApp, onAsk, now, favorites }: {
  uid: string; devices: Device[]; links: Link[]; marks?: Map<string, Need[]>; selected: string | null;
  onSelect: (id: string) => void; onApp?: (id: string, svcId: string) => void; onAsk: (q: string) => void; now: number;
  favorites?: boolean;
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState<DeviceNodeType>([]);
  const [edgeSel, setEdgeSel] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, LinkKind>>({}); // kind changed here, not yet back
  // Lines removed here, by the createdAt of the removed one: a line written again under the same id is newer and shows.
  const [removed, setRemoved] = useState<Record<string, number>>({});
  // Devices dropped here whose new spot isn't back yet; n tells a later drop's save from an earlier one's.
  const [held, setHeld] = useState<Record<string, { x: number; y: number; n: number }>>({});
  const drops = useRef(0);
  const flow = useRef<ReactFlowInstance<DeviceNodeType, LinkEdgeType> | null>(null);
  const fitted = useRef(0);
  // The parent's callbacks change every render; nodes get stable ones that call the latest.
  const cb = useRef({ onSelect, onAsk, onApp });
  cb.current = { onSelect, onAsk, onApp };
  const open = useCallback((id: string) => cb.current.onSelect(id), []);
  const ask = useCallback((q: string) => cb.current.onAsk(q), []);
  const app = useCallback((id: string, svcId: string) => (cb.current.onApp ?? ((d: string) => cb.current.onSelect(d)))(id, svcId), []);
  // One card at a time opens in place to show every app: by its Open button, or by zooming in on it. On a phone the
  // apps come up in a sheet instead.
  const [focus, setFocus] = useState<{ id: string; by: "tap" | "zoom" | "chat" } | null>(null);
  const [focusH, setFocusH] = useState(0);
  const [sheet, setSheet] = useState<string | null>(null);
  const phone = useRef(false);
  useEffect(() => {
    const m = window.matchMedia("(max-width: 700px)");
    phone.current = m.matches;
    const on = () => { phone.current = m.matches; };
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  const focusOn = useCallback((id: string) => {
    if (phone.current) setSheet(id); else { setFocusH(0); setFocus({ id, by: "tap" }); }
  }, []);
  useEffect(() => {
    if (!focus) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setFocus(null); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [focus]);
  // The chat's answer lights up the devices its steps touch; when it is done, the main one opens with the apps it named
  // pulsing. Never the device panel, never on a phone (the chat covers the map there), and never a camera move while
  // the person's hands are on the map. A tap on empty map puts the lights out.
  const followed = useFollowed();
  const [dimmed, setDimmed] = useState(0);
  const busyHands = useRef(false), lastHands = useRef(0);
  const lit = useCallback((id: string): "working" | "done" | undefined => followed.seq === dimmed
    || !followed.devices.includes(id) ? undefined : followed.done ? "done" : "working", [followed, dimmed]);
  const fingers = useRef(new Set<number>()); // pointers down on the map (two for a pinch)
  const hands = useCallback((e: React.PointerEvent) => {
    const id = e.pointerId;
    fingers.current.add(id);
    busyHands.current = true;
    const up = (u: PointerEvent) => {
      if (u.pointerId !== id) return;
      fingers.current.delete(id);
      if (fingers.current.size === 0) { busyHands.current = false; lastHands.current = Date.now(); }
      window.removeEventListener("pointerup", up); window.removeEventListener("pointercancel", up);
    };
    window.addEventListener("pointerup", up); window.addEventListener("pointercancel", up);
  }, []);
  const opened = useRef(0);
  useEffect(() => {
    if (!followed.done || opened.current === followed.seq || followed.seq === dimmed) return;
    opened.current = followed.seq;
    const main = mainDevice(followed);
    if (!main || phone.current || !devices.some((d) => d.id === main && d.kind !== "watched")) return;
    if (focus?.id === main) return;
    shown.current = null;
    setFocusH(0);
    setFocus({ id: main, by: "chat" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [followed]);
  const sized = useCallback((id: string, h: number) => setFocusH((x) => (x === h ? x : h)), []);

  // Devices from the database become nodes. A node being dragged keeps its place, and a dropped one stays where it
  // was dropped until the database has the new spot (or the save fails). base is where each one really is (what gets
  // saved); spots is where it shows, moved down while a card above it is open.
  const base = useMemo(() => {
    const b = arrange(devices);
    for (const [id, p] of Object.entries(held)) if (b.has(id)) b.set(id, { x: p.x, y: p.y });
    return b;
  }, [devices, held]);
  const focusId = focus && devices.some((d) => d.id === focus.id) ? focus.id : null;
  const spots = useMemo(() => focusId ? makeRoom(base, focusId, focusH) : base, [base, focusId, focusH]);
  // how far a card was shown away from its real spot when its drag began; the drop saves the real spot plus the drag
  const shift = useRef<Record<string, { dx: number; dy: number }>>({});
  useEffect(() => setHeld((h) => {
    const left = Object.entries(h).filter(([id, p]) => devices.some((d) => d.id === id && (d.x !== p.x || d.y !== p.y)));
    return left.length === Object.keys(h).length ? h : Object.fromEntries(left);
  }), [devices]);
  useEffect(() => {
    setNodes((cur) => devices.map((d) => {
      const old = cur.find((n) => n.id === d.id);
      return {
        id: d.id, type: "device", deletable: false, selected: d.id === selected, dragging: old?.dragging,
        position: old?.dragging ? old.position : spots.get(d.id)!,
        data: { device: d, uid, needs: marks?.get(d.id), now, onOpen: open, onAsk: ask, favorites,
          focused: d.id === focusId, onFocus: focusOn, onApp: app, onSize: sized,
          lit: lit(d.id), litApps: lit(d.id) ? litApps(followed, d.id) : undefined,
          by: d.watchedBy ? devices.find((x) => x.id === d.watchedBy)?.name : undefined },
      };
    }));
  }, [devices, spots, marks, selected, uid, now, open, ask, favorites, focusId, focusOn, app, sized, lit, followed, setNodes]);
  // A removed line's marker goes once the database no longer has that line (gone, or written again since).
  const hidden = useCallback((l: Link) => removed[l.id] === stamp(l), [removed]);
  useEffect(() => setRemoved((m) => {
    const left = Object.entries(m).filter(([id, t]) => links.some((l) => l.id === id && stamp(l) === t));
    return left.length === Object.keys(m).length ? m : Object.fromEntries(left);
  }), [links]);
  // Fit the whole home on screen when it first appears and whenever devices come or go.
  useEffect(() => {
    if (devices.length !== fitted.current && flow.current) {
      fitted.current = devices.length;
      requestAnimationFrame(() => flow.current?.fitView({ padding: 0.08, maxZoom: 1, duration: 300 }));
    }
  }, [devices.length, nodes.length]);

  const pos = useCallback((id: string) => nodes.find((n) => n.id === id)?.position ?? spots.get(id), [nodes, spots]);
  const setKind = useCallback((l: Link, kind: LinkKind) => {
    setDrafts((m) => ({ ...m, [l.id]: kind }));
    api("POST", "/api/links", { from: l.from, to: l.to, kind }).catch(() => {}).finally(() =>
      setDrafts(({ [l.id]: _, ...rest }) => rest));
  }, []);
  const remove = useCallback((l: Link) => {
    setRemoved((m) => ({ ...m, [l.id]: stamp(l) }));
    setEdgeSel(null);
    api("DELETE", `/api/links/${l.id}`).catch(() => setRemoved(({ [l.id]: _, ...rest }) => rest));
  }, []);

  const named = useCallback((id: string) => devices.find((d) => d.id === id)?.name ?? id, [devices]);
  const edges: LinkEdgeType[] = useMemo(() => {
    const on = new Set(devices.map((d) => d.id));
    const silent = new Set(devices.filter((d) => d.status === "offline").map((d) => d.id));
    return links.filter((l) => on.has(l.from) && on.has(l.to) && !hidden(l)).map((l) => {
      const a = pos(l.from), b = pos(l.to);
      const [s, t] = a && b ? sides(a, b) : [Position.Right, Position.Left];
      const kind = drafts[l.id] ?? l.kind;
      return {
        id: l.id, source: l.from, target: l.to, sourceHandle: s, targetHandle: t, type: "link",
        selected: edgeSel === l.id, ariaLabel: `${named(l.from)} ${LINK[kind].verb} ${named(l.to)}`,
        data: { kind, faded: silent.has(l.from) || silent.has(l.to), why: l.source === "auto" ? l.why ?? "seen by the helpers" : undefined },
      };
    });
  }, [links, devices, drafts, edgeSel, pos, hidden, named]);
  // The selected line's controls sit in a bar at screen size, whatever the zoom and wherever the line is.
  const chosen = links.find((l) => l.id === edgeSel && !hidden(l));
  const chosenKind = chosen && (drafts[chosen.id] ?? chosen.kind);

  function connect(c: { source: string | null; target: string | null }) {
    if (!c.source || !c.target || c.source === c.target) return;
    const id = `${c.source}__${c.target}`;
    setRemoved(({ [id]: _, ...rest }) => rest);
    api("POST", "/api/links", { from: c.source, to: c.target, kind: "network" }).then(() => setEdgeSel(id))
      .catch(() => {});
  }

  // A line let go anywhere over a device (not only on one of its dots) links to that device.
  function connectEnd(e: MouseEvent | TouchEvent, s: FinalConnectionState) {
    if (s.isValid || !s.fromNode) return;
    const p = "changedTouches" in e ? e.changedTouches[0] : e;
    const to = document.elementFromPoint(p.clientX, p.clientY)?.closest(".react-flow__node")?.getAttribute("data-id");
    if (to) connect({ source: s.fromNode.id, target: to });
  }

  // A card opened by its button (or by the chat) slides into view once it knows how tall it is (zoom stays as it was).
  // The chat never moves the view while the person is moving it, or just did; with reduced motion it jumps.
  const shown = useRef<string | null>(null);
  useEffect(() => {
    if (!focus || focus.by === "zoom" || !focusH || shown.current === focus.id) return;
    shown.current = focus.id;
    if (focus.by === "chat" && (busyHands.current || Date.now() - lastHands.current < HANDS_OFF_MS)) return;
    const p = spots.get(focus.id), f = flow.current;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (p && f) f.setCenter(p.x + NODE_W / 2, p.y + focusH / 2, { zoom: f.getZoom(), duration: still ? 0 : 300 });
  }, [focus, focusH, spots]);
  useEffect(() => { if (!focus) shown.current = null; }, [focus]);

  // On a wide screen the device panel covers the map's left edge: a chosen device hidden under it (or off screen)
  // slides into the part of the map still in view. Zoom stays as it was.
  useEffect(() => {
    if (!selected || window.matchMedia("(max-width: 900px)").matches) return;
    const id = requestAnimationFrame(() => {
      const f = flow.current, el = box.current, p = spots.get(selected);
      if (!f || !el || !p) return;
      const r = el.getBoundingClientRect();
      const panel = document.querySelector(".drawer.side")?.getBoundingClientRect();
      const cover = panel ? Math.max(0, Math.min(r.width, panel.right - r.left)) : 0;
      const { x, y, zoom } = f.getViewport();
      const sx = p.x * zoom + x, sy = p.y * zoom + y, w = NODE_W * zoom, h = NODE_H * zoom;
      if (sx >= cover + 8 && sx + w <= r.width - 8 && sy >= 8 && sy + h <= r.height - 8) return;
      const cx = cover + (r.width - cover) / 2, cy = r.height / 2;
      f.setViewport({ x: cx - (p.x + NODE_W / 2) * zoom, y: cy - (p.y + NODE_H / 2) * zoom, zoom }, { duration: 300 });
    });
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  // Zoomed in far enough, the card nearest the middle of the view opens; zoomed back out, a card opened that way closes.
  const box = useRef<HTMLDivElement>(null);
  function moved(v: { x: number; y: number; zoom: number }) {
    if (phone.current) return;
    if (v.zoom < UNFOCUS_ZOOM) { if (focus?.by === "zoom") setFocus(null); return; }
    if (v.zoom < FOCUS_ZOOM) return;
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    const cx = (r.width / 2 - v.x) / v.zoom, cy = (r.height / 2 - v.y) / v.zoom;
    let best: string | null = null, dist = Infinity;
    for (const [id, p] of base) {
      const dd = Math.hypot(p.x + NODE_W / 2 - cx, p.y + NODE_H / 2 - cy);
      if (dd < dist && devices.find((d) => d.id === id)?.kind !== "watched") { best = id; dist = dd; }
    }
    if (focus?.by === "tap" || focus?.by === "chat" || !best || focus?.id === best) return;
    setFocusH(0);
    setFocus({ id: best, by: "zoom" });
  }

  function dropped(id: string, p: { x: number; y: number }) {
    const x = Math.max(-5000, Math.min(5000, snap(p.x))), y = Math.max(-5000, Math.min(5000, snap(p.y)));
    const n = ++drops.current;
    setHeld((h) => ({ ...h, [id]: { x, y, n } }));
    api("POST", `/api/devices/${id}/layout`, { x, y }).catch(() => setHeld((h) => {
      if (h[id]?.n !== n) return h; // a later drop is still saving
      const { [id]: _, ...rest } = h;
      return rest;
    }));
  }

  return (
    <div className="homemap" aria-label="Map of your home" onKeyDown={(e) => {
      // Enter on a focused device opens it, as a click does (Tab moves between devices)
      const id = (e.target as HTMLElement).closest(".react-flow__node")?.getAttribute("data-id");
      if (e.key === "Enter" && id) open(id);
    }}>
      {/* any hand on the map (a card, the paper, the minimap, the zoom buttons, a pinch, a wheel) keeps the chat's
          camera still until it has been off for a few seconds */}
      <div className="hm-canvas" ref={box} onPointerDownCapture={hands} onWheelCapture={() => { lastHands.current = Date.now(); }}>
      <ReactFlow<DeviceNodeType, LinkEdgeType>
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        onNodesChange={(ch: NodeChange<DeviceNodeType>[]) => onNodesChange(ch.filter((c) => c.type !== "remove"))}
        onInit={(i) => { flow.current = i; }}
        onNodeClick={(_, n) => { setEdgeSel(null); open(n.id); }}
        onNodeDragStart={(_, n) => {
          busyHands.current = true;
          const b = base.get(n.id), v = spots.get(n.id);
          shift.current[n.id] = b && v ? { dx: v.x - b.x, dy: v.y - b.y } : { dx: 0, dy: 0 };
        }}
        onNodeDragStop={(_, n) => {
          busyHands.current = false; lastHands.current = Date.now();
          const o = shift.current[n.id] ?? { dx: 0, dy: 0 };
          delete shift.current[n.id];
          dropped(n.id, { x: n.position.x - o.dx, y: n.position.y - o.dy });
        }}
        onMoveStart={(e) => { if (e) busyHands.current = true; }} // e: the person moved it (not the app)
        onMoveEnd={(e, v) => { if (e) { busyHands.current = false; lastHands.current = Date.now(); } moved(v); }}
        onEdgeClick={(_, e) => setEdgeSel(e.id)}
        onPaneClick={() => { setEdgeSel(null); setFocus(null); setDimmed(followed.seq); }}
        onConnect={connect} onConnectEnd={connectEnd} connectionMode={ConnectionMode.Loose} connectionRadius={30}
        onEdgesDelete={(es) => es.forEach((e) => { const l = links.find((x) => x.id === e.id); if (l) remove(l); })}
        snapToGrid snapGrid={[GRID, GRID]} minZoom={0.2} maxZoom={2}
        panOnScroll zoomOnScroll={false} zoomOnPinch zoomOnDoubleClick={false}
        fitView fitViewOptions={{ padding: 0.08, maxZoom: 1 }}>
        {/* graph paper: fine squares, with a stronger line every fifth */}
        <Background id="fine" variant={BackgroundVariant.Lines} gap={GRID} lineWidth={0.5} color="rgba(120,128,150,.16)" />
        <Background id="major" variant={BackgroundVariant.Lines} gap={GRID * 5} lineWidth={1} color="rgba(120,128,150,.3)" />
        <Controls showInteractive={false} position="top-right" />
        <MiniMap className="hm-minimap" pannable zoomable style={{ width: 140, height: 90 }}
          nodeColor={(n) => STATUS_HEX[(n.data as { device: Device }).device.status] ?? STATUS_HEX.offline} />
      </ReactFlow>
      {chosen && chosenKind && (
        <div className="hm-linkbar" role="group" aria-label="This line">
          <span className="small">{named(chosen.from)} {LINK[chosenKind].verb} {named(chosen.to)}
            {chosen.source === "auto" && <span className="muted"> · Nightlight drew this: {chosen.why ?? "seen by the helpers"}</span>}</span>
          <span className="etools">
            {LINK_KINDS.map((k) => (
              <button key={k} className={k === chosenKind ? "on" : ""} aria-pressed={k === chosenKind} onClick={() => setKind(chosen, k)}>{LINK[k].label}</button>))}
            <button onClick={() => remove(chosen)} aria-label="Remove this line" title="Remove this line"><Trash2 size={15} /></button>
          </span>
        </div>)}
      </div>
      {sheet && devices.some((d) => d.id === sheet) && (
        <AppSheet uid={uid} device={devices.find((d) => d.id === sheet)!} onApp={(id, svcId) => { setSheet(null); app(id, svcId); }}
          onOpen={(id) => { setSheet(null); open(id); }} onClose={() => setSheet(null)} />)}
      {/* the key sits under the map, never over a device */}
      <div className="hm-legend small">
        {LINK_KINDS.map((k) => (
          <span key={k} title={LINK[k].verb}>
            <svg width="26" height="8" aria-hidden><line x1="1" y1="4" x2="25" y2="4"
              style={{ stroke: LINK[k].color, strokeWidth: 2, strokeDasharray: LINK[k].dash }} />
            </svg>{LINK[k].verb}</span>))}
        <span className="hm-hint">Drag from a dot on a device to another to link them · pinch or use the buttons to zoom</span>
      </div>
    </div>
  );
}
