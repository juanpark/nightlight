"use client";
// One app on a device (a container or a system service): what it is in a line, how it is, its version, and what
// Nightlight knows about it (notes, fixes that worked, what was done to it). Opened from an app chip on the map or
// from the device's list of what runs there.
import { ArrowLeft, Star } from "@/src/components/icons";
import type { useFavorites } from "@/lib/favorites";
import type { Action, Device, Service } from "@/lib/types";
import JobLog from "./JobLog";
import Notebook from "./Notebook";
import Runbooks from "./Runbooks";
import { appIcon } from "./map/kinds";

const KIND: Record<string, string> = { container: "Runs in a Docker container.", system: "A system service." };

/** How it is, in words. */
function state(s: Service): string {
  const st = s.status ?? "ok";
  return st === "ok" ? "Running fine." : st === "crit" ? "Needs a look now." : st === "warn" ? "Needs a look soon."
    : "Not reporting right now.";
}

export default function AppDetail({ uid, generation, device: d, app: s, actions, fav, onBack, onAsk }: {
  uid: string; generation?: number; device: Device; app: Service; actions: Action[];
  fav: ReturnType<typeof useFavorites>; onBack: () => void; onAsk: (q: string) => void;
}) {
  const Icon = appIcon(s);
  const starred = fav.isFavoriteApp(s.id);
  const what = s.about?.oneLiner || KIND[s.kind ?? ""] || "";
  return (
    <div className="app-detail">
      <button className="linkish small" onClick={onBack}><ArrowLeft size={13} /> Back to {d.name}</button>
      <div className="app-detail-head">
        <span className={`dicon ${s.status ?? "ok"}`}><Icon size={18} /></span>
        <strong style={{ fontSize: 17 }}>{s.name}</strong>
        {s.kind === "container" && <span className="pill">container</span>}
        <span style={{ flex: 1 }} />
        <button className={`star-btn ${starred ? "on" : ""}`} aria-pressed={starred}
          aria-label={`${starred ? "Unstar" : "Star"} ${s.name} as a favorite`} onClick={() => fav.toggleApp(s.id)}>
          <Star size={16} weight={starred ? "fill" : undefined} /></button>
      </div>
      {fav.err && <p className="small" style={{ color: "var(--crit-ink)" }}>{fav.err}</p>}
      {what && <p className="app-what">{what}</p>}
      <p className="drawer-status"><span className={`dot ${s.status ?? "ok"}`} /> {state(s)}
        {s.detail && <span className="muted small"> {s.detail}</span>}</p>
      {(s.findings ?? []).map((f, i) => <div key={i} className="finding small">{f.message}</div>)}
      <div className="drawer-actions">
        <button className="primary" onClick={() => onAsk(`How is ${s.name} on my ${d.name} doing?`)}>Ask about this app</button>
        {(s.findings?.length ?? 0) > 0 &&
          <button onClick={() => onAsk(`What should I do about ${s.name} on my ${d.name}?`)}>What should I do?</button>}
      </div>
      <div className="details small">
        {s.version && s.version !== "n/a" && <div><span className="muted">Version</span>{s.version}
          {s.updateAvailable && <> · <b>{s.latestVersion ? `${s.latestVersion} is out` : "an update is out"}</b></>}</div>}
        {s.ports && s.ports.length > 0 && <div><span className="muted">Answers on</span>port{s.ports.length > 1 ? "s" : ""}{" "}
          {s.ports.join(", ")}</div>}
        {s.players && <div><span className="muted">Players</span>{s.players.online} of {s.players.max} online</div>}
        {s.lastBackupDaysAgo != null && <div><span className="muted">Last backup</span>{s.lastBackupDaysAgo === 0 ? "today"
          : `${s.lastBackupDaysAgo} day${s.lastBackupDaysAgo === 1 ? "" : "s"} ago`}</div>}
        {s.unit && <div><span className="muted">Service name</span><code>{s.unit}</code></div>}
      </div>
      <Notebook uid={uid} deviceId={d.id} app={s} />
      <Runbooks key={`rb:${d.id}:${s.id}`} uid={uid} generation={generation} device={d} app={s} onAsk={onAsk} />
      <JobLog key={`log:${d.id}`} deviceId={d.id} actions={actions} app={s} />
    </div>
  );
}
