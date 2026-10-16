"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useServices } from "@/lib/data";
import type { Device } from "@/lib/types";
import DeviceHistory from "./DeviceHistory";
import Permissions from "./Permissions";

function Vital({ label, value }: { label: string; value?: number | null }) {
  return (
    <div>
      <div className="small muted">{label}</div>
      <div><strong>{value == null ? "–" : `${Math.round(value)}%`}</strong></div>
      <div className="bar"><i style={{ width: `${Math.min(100, value ?? 0)}%` }} /></div>
    </div>
  );
}

function uptime(sec?: number | null) {
  if (!sec) return "–";
  const d = Math.floor(sec / 86400);
  return d >= 14 ? `${Math.floor(d / 7)} weeks` : d >= 1 ? `${d} days` : `${Math.max(1, Math.round(sec / 3600))} hours`;
}

function ago(d?: Date | null) {
  if (!d) return "never";
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  return s < 90 ? `${s} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : d.toLocaleString();
}

export default function DeviceDrawer({ uid, device, onAsk, onClose }: {
  uid: string; device: Device; onAsk: (q: string) => void; onClose: () => void;
}) {
  const services = useServices(uid, device.id);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(device.name);
  const [tag, setTag] = useState("");
  const saveTags = (tags: string[]) => api("POST", `/api/devices/${device.id}/layout`, { tags }).catch(() => {});
  const mark = (id: string, state: "new" | "known" | "snoozed", days?: number) =>
    api("POST", `/api/devices/${device.id}/issues/${encodeURIComponent(id)}`, { state, ...(days ? { days } : {}) })
      .catch(() => {});
  async function rename() {
    if (name.trim() && name.trim() !== device.name) {
      await api("POST", `/api/devices/${device.id}/layout`, { name: name.trim() }).catch(() => {});
    }
    setEditing(false);
  }
  const real = device.realm === "real";
  return (
    <div className="panel drawer">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className={`dot ${device.status}`} />
        {editing
          ? <form onSubmit={(e) => { e.preventDefault(); rename(); }} style={{ display: "flex", gap: 6 }}>
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoFocus />
              <button className="primary">Save</button>
              <button type="button" onClick={() => setEditing(false)}>Cancel</button>
            </form>
          : <strong style={{ fontSize: 18 }}>{device.name}</strong>}
        {real && !editing && <button className="linkish small" onClick={() => { setName(device.name); setEditing(true); }}>
          Rename</button>}
        <span className={`pill ${real ? "live" : ""}`}>{real ? "Live device" : "Sample (simulated)"}</span>
        <span style={{ flex: 1 }} />
        <button onClick={onClose}>Close</button>
      </div>
      <p className="muted" style={{ margin: "6px 0" }}>{device.purpose}</p>
      {real && (
        <div className="details small">
          <div><span className="muted">Last report</span>{ago(device.lastSeen)}</div>
          <div><span className="muted">Running for</span>{uptime(device.vitals?.uptime)}</div>
          <div><span className="muted">System</span>{device.os ?? "–"}</div>
          <div><span className="muted">Chip</span>{device.arch ?? "–"}</div>
          <div><span className="muted">Updates waiting</span>{device.updatesPending ?? "–"}</div>
          <div><span className="muted">Containers</span>{device.containerCount != null
            ? `${device.containersRunning ?? 0} of ${device.containerCount} running` : "–"}</div>
          <div><span className="muted">Helper</span>{device.helperVersion ? `v${device.helperVersion}` : "–"}</div>
        </div>
      )}
      <div className="vitals">
        <Vital label="Disk" value={device.vitals?.diskPct} />
        <Vital label="Memory" value={device.vitals?.mem} />
        <Vital label="CPU" value={device.vitals?.cpu} />
      </div>
      {real && <DeviceHistory uid={uid} deviceId={device.id} />}
      {(device.findings ?? []).map((f, i) => {
        const state = f.state ?? "new";
        return (
          <div key={f.id ?? i} className={`finding ${state !== "new" ? "is-known" : ""}`}>
            <span className={`dot ${state !== "new" ? "offline" : f.severity === "info" ? "ok" : f.severity}`} />{" "}
            {f.message} <span className="muted small">({f.evidence})</span>
            {state !== "new" && <span className="pill" style={{ marginLeft: 6 }}>{state === "known" ? "Known" : "Snoozed"}</span>}
            {real && f.id && (state === "new"
              ? <span className="issue-actions">
                  <button className="linkish small" onClick={() => mark(f.id!, "known")}>I know, leave it</button>
                  <button className="linkish small" onClick={() => mark(f.id!, "snoozed", 7)}>Snooze a week</button>
                </span>
              : <button className="linkish small issue-actions" onClick={() => mark(f.id!, "new")}>Needs a look again</button>)}
          </div>
        );
      })}
      {real && (
        <div className="tags-edit small">
          <span className="muted">Tags:</span>
          {(device.tags ?? []).map((t) => (
            <span key={t} className="pill">{t} <button className="linkish" aria-label={`Remove ${t}`}
              onClick={() => saveTags((device.tags ?? []).filter((x) => x !== t))}>×</button></span>))}
          {(device.tags ?? []).length < 6 && (
            <form onSubmit={(e) => { e.preventDefault(); if (tag.trim()) { saveTags([...(device.tags ?? []), tag.trim()]); setTag(""); } }}>
              <input value={tag} onChange={(e) => setTag(e.target.value)} maxLength={20} placeholder="Add a tag (e.g. Parents)"
                style={{ padding: "3px 8px" }} />
            </form>)}
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        {services.map((s) => (
          <div key={s.id} className="svc">
            <span className={`dot ${s.status ?? "ok"}`} style={{ marginTop: 5 }} />
            <div style={{ flex: 1 }}>
              <div><strong>{s.name}</strong> {s.version && <span className="small muted">v{s.version}</span>}
                {s.category && <span className="pill" style={{ marginLeft: 6 }}>{s.category}</span>}</div>
              {s.players && <div className="small muted">{s.players.online} of {s.players.max} players online</div>}
              {s.detail && <div className="small muted">{s.detail}</div>}
              {(s.findings ?? []).map((f, i) => <div key={i} className="finding small">{f.message}</div>)}
            </div>
          </div>
        ))}
      </div>
      {real && device.kind !== "watched" && <Permissions device={device} services={services} />}
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        <button className="primary" onClick={() => onAsk(`How is my ${device.name} doing?`)}>Ask about this device</button>
        {device.findings?.[0] && <button onClick={() => onAsk(`What should I do about this on my ${device.name}: ${device.findings![0].message}`)}>
          What should I do?</button>}
      </div>
    </div>
  );
}
