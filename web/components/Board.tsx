"use client";
import type { Device } from "@/lib/types";

const KIND: Record<string, string> = {
  pi: "Raspberry Pi", mac: "Mac", nas: "Storage", gameserver: "Game server", camera: "Cameras", router: "Network",
  computer: "Computer",
};

export default function Board({ devices, selected, onSelect }: {
  devices: Device[]; selected: string | null; onSelect: (id: string) => void;
}) {
  const sorted = [...devices].sort((a, b) => (a.y ?? 0) - (b.y ?? 0) || (a.x ?? 0) - (b.x ?? 0));
  // Map positions are abstract; spread them across whatever width the board has.
  const xs = devices.map((d) => d.x ?? 0), ys = devices.map((d) => d.y ?? 0);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const fx = (x: number) => (x1 > x0 ? (x - x0) / (x1 - x0) : 0);
  const rows = y1 > y0 ? (y1 - y0) * 1.25 : 0;
  return (
    <div className="board" aria-label="Your home" style={{ height: rows + 170 }}>
      {sorted.map((d) => {
        const top = d.findings?.[0];
        const real = d.realm === "real";
        return (
          <button key={d.id} className={`node ${d.status} ${selected === d.id ? "sel" : ""}`}
            style={{ left: `calc(12px + (100% - 194px) * ${fx(d.x ?? 0)})`, top: ((d.y ?? 0) - y0) * 1.25 + 14 }}
            onClick={() => onSelect(d.id)}>
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
    </div>
  );
}
