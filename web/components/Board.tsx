"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Device } from "@/lib/types";

const KIND: Record<string, string> = {
  pi: "Raspberry Pi", mac: "Mac", nas: "Storage", gameserver: "Game server", camera: "Cameras", router: "Network",
  computer: "Computer",
};

// Devices sit on a grid so they never overlap. Stored positions are abstract units (x = 120 + 100 per column,
// y = 80 + 140 per row), which keeps the sample home's original layout.
const toCell = (d: Device) => ({ col: Math.max(0, Math.round(((d.x ?? 120) - 120) / 100)),
  row: Math.max(0, Math.round(((d.y ?? 80) - 80) / 140)) });
const fromCell = (col: number, row: number) => ({ x: 120 + col * 100, y: 80 + row * 140 });
const CARD_W = 180, ROW_H = 150, PAD = 12;

/** Each device gets its wanted cell, or the nearest free one (first come, first served; sample devices first). */
function place(devices: Device[], cols: number) {
  const taken = new Set<string>();
  const out = new Map<string, { col: number; row: number }>();
  const order = [...devices].sort((a, b) => Number(a.realm === "real") - Number(b.realm === "real")
    || a.id.localeCompare(b.id));
  for (const d of order) {
    const want = toCell(d);
    let cell = { col: Math.min(want.col, cols - 1), row: want.row };
    for (let i = 0; taken.has(`${cell.col},${cell.row}`); i++) {
      cell = { col: (want.col + i + 1) % cols, row: want.row + Math.floor((want.col + i + 1) / cols) };
    }
    taken.add(`${cell.col},${cell.row}`);
    out.set(d.id, cell);
  }
  return out;
}

export default function Board({ devices, selected, onSelect }: {
  devices: Device[]; selected: string | null; onSelect: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [moved, setMoved] = useState<Record<string, { x: number; y: number }>>({});
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number; sx: number; sy: number } | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const cols = Math.max(2, Math.floor((width - PAD * 2) / (CARD_W + 16)));
  const colW = (width - PAD * 2) / cols;
  const shown = useMemo(() => devices.map((d) => (moved[d.id] ? { ...d, ...moved[d.id] } : d)), [devices, moved]);
  const cells = useMemo(() => place(shown, cols), [shown, cols]);
  const rows = Math.max(1, ...[...cells.values()].map((c) => c.row + 1));

  function drop(id: string, px: number, py: number) {
    const col = Math.min(cols - 1, Math.max(0, Math.round((px - PAD) / colW)));
    const row = Math.max(0, Math.round((py - 14) / ROW_H));
    const others = new Set([...cells].filter(([k]) => k !== id).map(([, c]) => `${c.col},${c.row}`));
    if (others.has(`${col},${row}`)) return; // occupied: it springs back
    const pos = fromCell(col, row);
    setMoved((m) => ({ ...m, [id]: pos }));
    api("POST", `/api/devices/${id}/layout`, pos).catch(() => setMoved((m) => {
      const { [id]: _, ...rest } = m;
      return rest;
    }));
  }

  return (
    <div ref={ref} className="board" aria-label="Your home" style={{ height: rows * ROW_H + 40 }}
      onPointerMove={(e) => drag && setDrag({ ...drag, dx: e.clientX - drag.sx, dy: e.clientY - drag.sy })}
      onPointerUp={(e) => {
        if (!drag) return;
        const far = Math.abs(drag.dx) + Math.abs(drag.dy) > 6;
        const c = cells.get(drag.id)!;
        if (far) drop(drag.id, PAD + c.col * colW + drag.dx, 14 + c.row * ROW_H + drag.dy);
        else onSelect(drag.id);
        setDrag(null);
        e.preventDefault();
      }}
      onPointerLeave={() => setDrag(null)}>
      {shown.map((d) => {
        const c = cells.get(d.id)!;
        const top = d.findings?.[0];
        const real = d.realm === "real";
        const dragging = drag?.id === d.id;
        return (
          <button key={d.id} className={`node ${d.status} ${selected === d.id ? "sel" : ""} ${dragging ? "dragging" : ""}`}
            style={{ left: PAD + c.col * colW + (dragging ? drag.dx : 0), top: 14 + c.row * ROW_H + (dragging ? drag.dy : 0),
              width: Math.min(CARD_W, colW - 12) }}
            onPointerDown={(e) => { (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
              setDrag({ id: d.id, dx: 0, dy: 0, sx: e.clientX, sy: e.clientY }); }}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelect(d.id); }}
            title="Click for details. Drag to move.">
            <div className="row">
              <span className={`dot ${d.status}`} />
              <span className="name">{d.name}</span>
            </div>
            <div className="row small muted" style={{ marginTop: 2 }}>
              {KIND[d.kind ?? ""] ?? d.kind}
              <span className={`pill ${real ? "live" : ""}`}>{real ? "Live" : "Sample"}</span>
            </div>
            <div className="problem">
              {d.status === "offline" ? "Not reporting right now" : top ? top.message : "All good"}
            </div>
          </button>
        );
      })}
      {devices.length === 0 && (
        <p className="muted" style={{ padding: 20 }}>No devices yet. Use <strong>Add a device</strong> to put your first
          one on the map, or switch on the sample home to look around.</p>
      )}
    </div>
  );
}
