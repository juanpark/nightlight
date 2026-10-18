"use client";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Device } from "@/lib/types";

const INCIDENTS = [
  { kind: "disk_full", label: "Disk fills up", device: "pi-1" },
  { kind: "logs_locked", label: "Next clean-up will fail", device: "pi-1" },
  { kind: "server_lagging", label: "Minecraft gets laggy", device: "game-1" },
  { kind: "backup_overdue", label: "World backup overdue", device: "game-1" },
  { kind: "update_available", label: "Game update available", device: "game-1" },
];

export default function DemoTools({ devices }: { devices: Device[] }) {
  const [msg, setMsg] = useState("");
  async function call(path: string, body: unknown, ok: string) {
    setMsg("");
    try { await api("POST", path, body); setMsg(ok); }
    catch (e) { setMsg(e instanceof ApiError ? e.code : "Something went wrong"); }
  }
  return (
    <div className="panel">
      <h3>Demo tools (sample home only)</h3>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {INCIDENTS.filter((i) => devices.some((d) => d.id === i.device)).map((i) => (
          <button key={i.kind} onClick={() => call("/api/demo/inject", { kind: i.kind, deviceId: i.device },
            `${i.label}: done`)}>{i.label}</button>
        ))}
        <button onClick={() => call("/api/demo/reset", {}, "The sample home is back to a clean start.")}>
          Start fresh</button>
      </div>
      {msg && <p className="small muted">{msg}</p>}
    </div>
  );
}
