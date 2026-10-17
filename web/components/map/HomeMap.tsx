"use client";
// The home as a canvas: graph paper you can pan and zoom, devices that snap to it where you drop them, and lines for
// how they relate. It opens fitted to whatever screen it is on. Positions and lines are layout only: saving them
// never touches a device.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background, BackgroundVariant, ConnectionMode, Controls, MiniMap, Position, ReactFlow, useNodesState,
  type Connection, type NodeChange, type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "@/app/map.css";
import { api } from "@/lib/api";
import type { Need } from "@/lib/needsYou";
import type { Device, Link, LinkKind } from "@/lib/types";
import DeviceNode, { type DeviceNodeType } from "./DeviceNode";
import LinkEdge, { type LinkEdgeType } from "./LinkEdge";
import { GRID, LINK, LINK_KINDS, NODE_H, NODE_W } from "./kinds";

const nodeTypes = { device: DeviceNode };
const STATUS_HEX: Record<string, string> = { ok: "#3aa776", warn: "#e0a028", crit: "#d9534f", offline: "#9aa1ad" };
const edgeTypes = { link: LinkEdge };
const snap = (v: number) => Math.round(v / GRID) * GRID;

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

export default function HomeMap({ uid, devices, links, marks, selected, onSelect, onAsk, now }: {
  uid: string; devices: Device[]; links: Link[]; marks?: Map<string, Need[]>; selected: string | null;
  onSelect: (id: string) => void; onAsk: (q: string) => void; now: number;
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState<DeviceNodeType>([]);
  const [edgeSel, setEdgeSel] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, LinkKind | null>>({}); // drawn or changed here, not yet back
  const flow = useRef<ReactFlowInstance<DeviceNodeType, LinkEdgeType> | null>(null);
  const fitted = useRef(0);
  // The parent's callbacks change every render; nodes get stable ones that call the latest.
  const cb = useRef({ onSelect, onAsk });
  cb.current = { onSelect, onAsk };
  const open = useCallback((id: string) => cb.current.onSelect(id), []);
  const ask = useCallback((q: string) => cb.current.onAsk(q), []);

  // Devices from the database become nodes; a node being dragged keeps its place until it is dropped.
  const spots = useMemo(() => arrange(devices), [devices]);
  useEffect(() => {
    setNodes((cur) => devices.map((d) => {
      const old = cur.find((n) => n.id === d.id);
      return {
        id: d.id, type: "device", deletable: false, selected: d.id === selected,
        position: old?.dragging ? old.position : spots.get(d.id)!,
        data: { device: d, uid, needs: marks?.get(d.id), now, onOpen: open, onAsk: ask },
      };
    }));
  }, [devices, spots, marks, selected, uid, now, open, ask, setNodes]);
  // Fit the whole home on screen when it first appears and whenever devices come or go.
  useEffect(() => {
    if (devices.length !== fitted.current && flow.current) {
      fitted.current = devices.length;
      requestAnimationFrame(() => flow.current?.fitView({ padding: 0.2, maxZoom: 1.1, duration: 300 }));
    }
  }, [devices.length, nodes.length]);

  const pos = useCallback((id: string) => nodes.find((n) => n.id === id)?.position ?? spots.get(id), [nodes, spots]);
  const setKind = useCallback((l: Link, kind: LinkKind) => {
    setDrafts((m) => ({ ...m, [l.id]: kind }));
    api("POST", "/api/links", { from: l.from, to: l.to, kind }).catch(() => {}).finally(() =>
      setDrafts(({ [l.id]: _, ...rest }) => rest));
  }, []);
  const remove = useCallback((l: Link) => {
    setDrafts((m) => ({ ...m, [l.id]: null }));
    setEdgeSel(null);
    api("DELETE", `/api/links/${l.id}`).catch(() => setDrafts(({ [l.id]: _, ...rest }) => rest));
  }, []);

  const edges: LinkEdgeType[] = useMemo(() => {
    const on = new Set(devices.map((d) => d.id));
    const silent = new Set(devices.filter((d) => d.status === "offline").map((d) => d.id));
    return links.filter((l) => on.has(l.from) && on.has(l.to) && drafts[l.id] !== null).map((l) => {
      const a = pos(l.from), b = pos(l.to);
      const [s, t] = a && b ? sides(a, b) : [Position.Right, Position.Left];
      const kind = drafts[l.id] ?? l.kind;
      return {
        id: l.id, source: l.from, target: l.to, sourceHandle: s, targetHandle: t, type: "link",
        selected: edgeSel === l.id, ariaLabel: `${l.from} ${LINK[kind].verb} ${l.to}`,
        data: { kind, faded: silent.has(l.from) || silent.has(l.to), onKind: (k) => setKind(l, k), onDelete: () => remove(l) },
      };
    });
  }, [links, devices, drafts, edgeSel, pos, setKind, remove]);

  function connect(c: Connection) {
    if (!c.source || !c.target || c.source === c.target) return;
    const id = `${c.source}__${c.target}`;
    api("POST", "/api/links", { from: c.source, to: c.target, kind: "network" }).then(() => setEdgeSel(id))
      .catch(() => {});
  }

  function dropped(id: string, p: { x: number; y: number }) {
    const x = Math.max(-5000, Math.min(5000, snap(p.x))), y = Math.max(-5000, Math.min(5000, snap(p.y)));
    api("POST", `/api/devices/${id}/layout`, { x, y }).catch(() => {});
  }

  return (
    <div className="homemap" aria-label="Map of your home">
      <ReactFlow<DeviceNodeType, LinkEdgeType>
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        onNodesChange={(ch: NodeChange<DeviceNodeType>[]) => onNodesChange(ch.filter((c) => c.type !== "remove"))}
        onInit={(i) => { flow.current = i; }}
        onNodeClick={(_, n) => { setEdgeSel(null); open(n.id); }}
        onNodeDragStop={(_, n) => dropped(n.id, n.position)}
        onEdgeClick={(_, e) => setEdgeSel(e.id)}
        onPaneClick={() => setEdgeSel(null)}
        onConnect={connect} connectionMode={ConnectionMode.Loose}
        onEdgesDelete={(es) => es.forEach((e) => { const l = links.find((x) => x.id === e.id); if (l) remove(l); })}
        snapToGrid snapGrid={[GRID, GRID]} minZoom={0.2} maxZoom={2}
        panOnScroll zoomOnScroll={false} zoomOnPinch zoomOnDoubleClick={false}
        fitView fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}>
        {/* graph paper: fine squares, with a stronger line every fifth */}
        <Background id="fine" variant={BackgroundVariant.Lines} gap={GRID} lineWidth={0.5} color="rgba(120,128,150,.16)" />
        <Background id="major" variant={BackgroundVariant.Lines} gap={GRID * 5} lineWidth={1} color="rgba(120,128,150,.3)" />
        <Controls showInteractive={false} position="top-right" />
        <MiniMap className="hm-minimap" pannable zoomable style={{ width: 140, height: 90 }}
          nodeColor={(n) => STATUS_HEX[(n.data as { device: Device }).device.status] ?? STATUS_HEX.offline} />
      </ReactFlow>
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
