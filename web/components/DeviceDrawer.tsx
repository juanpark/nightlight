"use client";
import { useServices } from "@/lib/data";
import type { Device } from "@/lib/types";

function Vital({ label, value }: { label: string; value?: number | null }) {
  return (
    <div>
      <div className="small muted">{label}</div>
      <div><strong>{value == null ? "–" : `${Math.round(value)}%`}</strong></div>
      <div className="bar"><i style={{ width: `${Math.min(100, value ?? 0)}%` }} /></div>
    </div>
  );
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
  const real = device.realm === "real";
  const allowed = device.allowedJobs?.restart_container ?? [];
  return (
    <div className="panel drawer">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className={`dot ${device.status}`} />
        <strong style={{ fontSize: 18 }}>{device.name}</strong>
        <span className={`pill ${real ? "live" : ""}`}>{real ? "Live device" : "Sample (simulated)"}</span>
        <span style={{ flex: 1 }} />
        <button onClick={onClose}>Close</button>
      </div>
      <p className="muted" style={{ margin: "6px 0" }}>{device.purpose}</p>
      {real && <p className="small muted">Last report: {ago(device.lastSeen)}{device.os ? ` · ${device.os}` : ""}
        {allowed.length > 0 && <> · You allowed restarting: {allowed.join(", ")}</>}</p>}
      <div className="vitals">
        <Vital label="Disk" value={device.vitals?.diskPct} />
        <Vital label="Memory" value={device.vitals?.mem} />
        <Vital label="CPU" value={device.vitals?.cpu} />
      </div>
      {(device.findings ?? []).map((f, i) => (
        <div key={i} className="finding"><span className={`dot ${f.severity === "info" ? "ok" : f.severity}`} />{" "}
          {f.message} <span className="muted small">({f.evidence})</span></div>
      ))}
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
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        <button className="primary" onClick={() => onAsk(`How is my ${device.name} doing?`)}>Ask about this device</button>
        {device.findings?.[0] && <button onClick={() => onAsk(`What should I do about this on my ${device.name}: ${device.findings![0].message}`)}>
          What should I do?</button>}
      </div>
    </div>
  );
}
