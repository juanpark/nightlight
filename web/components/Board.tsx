"use client";
// The home as a list: the same devices as the map, grouped by kind, the ones that need you first in each group. Each
// row says the device's status in a word and one plain line; tap it to open the device.
import type { Need } from "@/lib/needsYou";
import NeedsMark from "./NeedsMark";
import StatusWord, { deviceLine, deviceTone } from "./StatusWord";
import type { Device } from "@/lib/types";

const KIND: Record<string, string> = {
  pi: "Raspberry Pi", mac: "Mac", nas: "Storage", gameserver: "Game server", camera: "Cameras", router: "Network",
  computer: "Computer", watched: "Watched",
};
const WORST: Record<string, number> = { crit: 0, warn: 1, offline: 2, ok: 3 };

export default function Board({ devices, selected, onSelect, settingUp = false, marks }: {
  devices: Device[]; selected: string | null; onSelect: (id: string) => void; settingUp?: boolean;
  marks?: Map<string, Need[]>;
}) {
  if (devices.length === 0) {
    return <div className="dlist-empty muted">{settingUp ? "Setting up your sample home…"
      : <>No devices yet. Use <strong>Add a device</strong> to put your first one on the map, or switch on the sample
        home to look around.</>}</div>;
  }
  const groups = new Map<string, Device[]>();
  for (const d of devices) {
    const k = KIND[d.kind ?? ""] ?? d.kind ?? "Other";
    groups.set(k, [...(groups.get(k) ?? []), d]);
  }
  const worst = (ds: Device[]) => Math.min(...ds.map((d) => WORST[d.status] ?? 3));
  const sorted = [...groups].sort(([a, x], [b, y]) => worst(x) - worst(y) || a.localeCompare(b));
  // a heading per kind only helps when some kind has more than one device
  const ordered: [string, Device[]][] = sorted.some(([, ds]) => ds.length > 1) ? sorted : [["", devices]];
  const now = Date.now();
  return (
    <div className="dlist" aria-label="Your home">
      {ordered.map(([kind, ds]) => (
        <section key={kind || "all"} className="dlist-group" aria-label={kind || undefined}>
          {kind && <h3 className="dlist-kind">{kind}</h3>}
          <ul>
            {[...ds].sort((a, b) => (WORST[a.status] ?? 3) - (WORST[b.status] ?? 3) || a.name.localeCompare(b.name)).map((d) => {
              const real = d.realm === "real";
              return (
                <li key={d.id}>
                  <button className={`dlist-row ${d.status} ${selected === d.id ? "sel" : ""}`} onClick={() => onSelect(d.id)}
                    aria-current={selected === d.id ? "true" : undefined}>
                    <span className="dlist-name">{d.name}
                      <span className={`pill ${real ? "live" : "sample"}`}
                        title={real ? "A real device, reporting through the Nightlight helper" : "A simulated sample device"}>
                        {real ? "Live" : "Simulated"}</span>
                      <NeedsMark needs={marks?.get(d.id)} /></span>
                    <StatusWord tone={deviceTone(d)} />
                    <span className="dlist-line">{deviceLine(d, now)}</span>
                  </button>
                </li>);
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
