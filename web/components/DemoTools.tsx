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
    catch (e) {
      setMsg(e instanceof ApiError && e.status === 409 ? "The sample home is resetting. Try again in a moment."
        : e instanceof ApiError && e.status === 422 ? "That doesn't apply right now. Reset the sample home and try again."
          : "Couldn't do that. Please try again.");
    }
  }
  return (
    <div className="panel">
      <h3>Demo tools</h3>
      <p className="small muted" style={{ marginTop: -4 }}>Cause trouble in the sample home on purpose, then ask Nightlight
        about it. Only the simulated devices are touched.</p>
      <div className="demo-grid">
        {INCIDENTS.filter((i) => devices.some((d) => d.id === i.device)).map((i) => (
          <button key={i.kind} onClick={() => call("/api/demo/inject", { kind: i.kind, deviceId: i.device },
            `${i.label}: done. Now ask Nightlight what's wrong.`)}>{i.label}</button>
        ))}
      </div>
      <div className="demo-reset">
        <button onClick={() => call("/api/demo/reset", {}, "The sample home is back to a clean start.")}>
          Reset the sample home</button>
        <span className="small muted">Puts every simulated device back the way it started.</span>
      </div>
      {msg && <p className="small muted" role="status">{msg}</p>}
    </div>
  );
}
