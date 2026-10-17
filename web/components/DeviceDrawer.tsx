"use client";
// One device, with progressive disclosure: a status sentence and what needs the person first, then three tabs
// (Overview: how it is and what runs there; About: what Nightlight knows about it; Settings: what it may do).
// UX spec 2026-10-17 §2.
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useServices } from "@/lib/data";
import { statusSentence, type Go, type Need } from "@/lib/needsYou";
import type { Action, Device } from "@/lib/types";
import DeviceHistory from "./DeviceHistory";
import Checkups from "./Checkups";
import HelperUpdate from "./HelperUpdate";
import Notebook from "./Notebook";
import DeviceProfile from "./DeviceProfile";
import RemoveDevice from "./RemoveDevice";
import ExpertSessions from "./ExpertSessions";
import Permissions from "./Permissions";
import NeedsList from "./NeedsList";
import WatchedPanel from "./WatchedPanel";
import { deviceIcon } from "./map/kinds";

type Tab = "overview" | "about" | "settings";

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

/** How this device gets helper updates, in plain words (the switches are in Settings). */
function updateMode(d: Device) {
  if (d.manage === "app") {
    if (d.permissions?.updates === false) return "updates from the app are off";
    return d.permissions?.autoUpdate ? "updates automatically" : "updates when you tap Update";
  }
  return (d.allowedJobs?.update ?? []).includes("signed") ? "updates when you tap Update" : "updates only on the device";
}

export default function DeviceDrawer({ uid, generation, device, actions, devices, needs, release, tab, onTab, onGo,
  onFollowUp, onAsk, onClose }: {
  uid: string; generation?: number; device: Device; actions: Action[]; devices: Device[]; needs: Need[];
  release: { version: string } | null; tab: Tab; onTab: (t: Tab) => void; onGo: (g: Go) => void;
  onFollowUp: (turnId: string) => void; onAsk: (q: string) => void; onClose: () => void;
}) {
  const services = useServices(uid, device.id);
  const [allServices, setAllServices] = useState(false);
  const real = device.realm === "real";
  const watched = device.kind === "watched";
  const removing = needs.some((n) => n.kind === "removing");
  // Opened from the map, the panel sits below it: bring it into view when its top would be off screen (phones).
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const top = box.current?.getBoundingClientRect().top ?? 0;
    if (top > window.innerHeight * 0.6) box.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [device.id]);
  // Each problem is said once: the urgent one as a row under the status sentence (with its "What should I do?"),
  // the rest under Problems.
  const listed = (f: Finding) => needs.some((n) => n.id === `critical:${device.id}:${f.id ?? f.message}`);
  const urgent = (device.findings ?? []).find(listed);
  const brief = !removing && !(real && device.status === "offline") && (device.status === "crit" || device.status === "warn");
  const tabs: Tab[] = real && !watched ? ["overview", "about", "settings"] : [];
  const current: Tab = tabs.includes(tab) ? tab : "overview";
  if (watched) {
    return (
      <div className="panel drawer" ref={box}>
        <Head key={device.id} device={device} onClose={onClose} />
        <NeedsList needs={needs} actions={actions} devices={devices} onGo={onGo} onFollowUp={onFollowUp} />
        <WatchedPanel key={`watched:${device.id}`} uid={uid} generation={generation} device={device} devices={devices} onAsk={onAsk} onGo={onGo}
          onClose={onClose} />
      </div>
    );
  }
  return (
    <div className="panel drawer" ref={box}>
      <Head key={device.id} device={device} onClose={onClose} />
      <p className="drawer-status">{brief ? `Needs attention ${device.status === "crit" ? "now" : "soon"}.`
        : statusSentence(device, Date.now(), removing)}</p>
      <NeedsList needs={needs} actions={actions} devices={devices} onGo={onGo} onFollowUp={onFollowUp}
        extra={(n) => urgent && real && n.kind === "critical" ? <IssueActions device={device} finding={urgent} /> : null} />
      <div className="drawer-actions">
        <button className="primary" onClick={() => onAsk(`How is my ${device.name} doing?`)}>Ask about this device</button>
      </div>
      {tabs.length > 0 && (
        <div className="tabs" role="tablist">
          {tabs.map((t) => (
            <button key={t} role="tab" aria-selected={current === t} className={current === t ? "on" : ""}
              onClick={() => onTab(t)}>{t === "overview" ? "Overview" : t === "about" ? "About" : "Settings"}</button>
          ))}
        </div>
      )}

      {current === "overview" && <>
        {real && device.status === "offline"
          ? <p className="muted small">Last report {device.lastSeen ? device.lastSeen.toLocaleString() : "never"}: Nightlight
              will check what happened when it&apos;s back.</p>
          : <div className="vitals">
              <Vital label="Disk" value={device.vitals?.diskPct} />
              <Vital label="Memory" value={device.vitals?.mem} />
              <Vital label="CPU" value={device.vitals?.cpu} />
            </div>}
        <Problems device={device} skip={listed} onAsk={onAsk} />
        {real && !watched && <Checkups uid={uid} generation={generation} deviceId={device.id}
          actions={actions} cleanupOn={!!device.permissions?.cleanup || !!device.allowedJobs?.fix?.length} />}
        <section className="drawer-section">
          <h4>What runs here</h4>
          {services.length === 0 && <p className="muted small">{real ? "Nothing running that Nightlight recognises yet. It "
            + "lists Docker containers and failed system services." : "Nothing listed."}</p>}
          {services.filter((s) => allServices || (s.status ?? "ok") !== "ok").map((s) => (
            <div key={s.id} className="svc">
              <span className={`dot ${s.status ?? "ok"}`} style={{ marginTop: 5 }} />
              <div style={{ flex: 1 }}>
                <div><strong>{s.name}</strong> {s.version && s.version !== "n/a" && <span className="small muted">v{s.version}</span>}
                  {s.category && <span className="pill" style={{ marginLeft: 6 }}>{s.category}</span>}</div>
                {s.players && <div className="small muted">{s.players.online} of {s.players.max} players online</div>}
                {s.detail && <div className="small muted">{s.detail}</div>}
                {(s.findings ?? []).filter((f) => !(device.findings ?? []).some((g) => g.message === f.message)) // said above
                  .map((f, i) => <div key={i} className="finding small">{f.message}</div>)}
              </div>
            </div>
          ))}
          {services.some((s) => (s.status ?? "ok") === "ok") && (
            <button className="linkish small" onClick={() => setAllServices(!allServices)}>
              {allServices ? "Show only what needs a look"
                : `Show all ${services.length} (${services.filter((s) => (s.status ?? "ok") === "ok").length} running fine)`}
            </button>)}
        </section>
        {real && <DeviceHistory uid={uid} deviceId={device.id} />}
        {!real && <DeviceProfile uid={uid} deviceId={device.id} />}
        {!real && <Notebook uid={uid} deviceId={device.id} />}
      </>}

      {current === "about" && <>
        <DeviceProfile uid={uid} deviceId={device.id} />
        <Notebook uid={uid} deviceId={device.id} />
        <Tags device={device} />
        <section className="drawer-section">
          <h4>Details</h4>
          <div className="details small">
            <div><span className="muted">System</span>{device.os ?? "–"}</div>
            <div><span className="muted">Chip</span>{device.arch ?? "–"}</div>
            <div><span className="muted">Running for</span>{uptime(device.vitals?.uptime)}</div>
            <div><span className="muted">Containers</span>{device.containerCount != null
              ? `${device.containersRunning ?? 0} of ${device.containerCount} running` : "–"}</div>
            <div><span className="muted">System updates</span>{device.updatesPending ?? "–"}</div>
            <div><span className="muted">Helper</span>{device.helperVersion ? `v${device.helperVersion}` : "–"}
              {device.helperVersion && <span className="muted small"> · {updateMode(device)}</span>}</div>
          </div>
          {device.purpose && <p className="muted small">{device.purpose}</p>}
        </section>
      </>}

      {current === "settings" && <>
        <Permissions key={device.id} device={device} services={services} />
        <section className="drawer-section">
          <h4>Updates</h4>
          <HelperUpdate device={device} actions={actions} latest={release?.version}
            origin={typeof window === "undefined" ? "" : window.location.origin} />
          {!(release && device.helperVersion && release.version !== device.helperVersion) &&
            <p className="muted small">Up to date (v{device.helperVersion ?? "?"}) · {updateMode(device)}.</p>}
        </section>
        <ExpertSessions uid={uid} device={device} open={needs.some((n) => n.kind === "expertHalf")} />
        <RemoveDevice device={device} onRemoved={onClose} />
      </>}
    </div>
  );
}

type Finding = NonNullable<Device["findings"]>[number];

/** Name (renamable on real devices), what kind of thing it is, Live or Sample, Close. */
function Head({ device, onClose }: { device: Device; onClose: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(device.name);
  const real = device.realm === "real";
  const Icon = deviceIcon(device);
  async function rename() {
    if (name.trim() && name.trim() !== device.name) {
      await api("POST", `/api/devices/${device.id}/layout`, { name: name.trim() }).catch(() => {});
    }
    setEditing(false);
  }
  return (
    <div className="drawer-head">
      <span className={`dicon ${device.status}`}><Icon size={18} strokeWidth={1.8} /></span>
      {editing
        ? <form onSubmit={(e) => { e.preventDefault(); rename(); }} style={{ display: "flex", gap: 6 }}>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoFocus />
            <button className="primary">Save</button>
            <button type="button" onClick={() => setEditing(false)}>Cancel</button>
          </form>
        : <strong style={{ fontSize: 18 }}>{device.name}</strong>}
      {real && !editing && <button className="linkish small" onClick={() => { setName(device.name); setEditing(true); }}>
        Rename</button>}
      <span className={`pill ${real ? "live" : ""}`}>{real ? (device.kind === "watched" ? "Watched" : "Live") : "Sample"}</span>
      <span style={{ flex: 1 }} />
      <button onClick={onClose}>Close</button>
    </div>
  );
}

/** Leave a problem alone for good or for a week, or bring it back (real devices; the server keeps the state). */
function IssueActions({ device, finding: f }: { device: Device; finding: Finding }) {
  if (device.realm !== "real" || !f.id) return null;
  const mark = (state: "new" | "known" | "snoozed", days?: number) =>
    api("POST", `/api/devices/${device.id}/issues/${encodeURIComponent(f.id!)}`, { state, ...(days ? { days } : {}) })
      .catch(() => {});
  return (f.state ?? "new") === "new"
    ? <span className="issue-actions">
        <button className="linkish small" onClick={() => mark("known")}>I know, leave it</button>
        <button className="linkish small" onClick={() => mark("snoozed", 7)}>Snooze a week</button>
      </span>
    : <button className="linkish small issue-actions" onClick={() => mark("new")}>Needs a look again</button>;
}

function Problems({ device, skip, onAsk }: { device: Device; skip: (f: Finding) => boolean; onAsk: (q: string) => void }) {
  const [showKnown, setShowKnown] = useState(false);
  const all = device.findings ?? [];
  const open = all.filter((f) => (f.state ?? "new") === "new" && !skip(f));
  const known = all.filter((f) => (f.state ?? "new") !== "new");
  const urgent = all.some(skip);
  const row = (f: Finding, i: number) => {
    const state = f.state ?? "new";
    return (
      <div key={f.id ?? i} className={`finding ${state !== "new" ? "is-known" : ""}`}>
        <span className={`dot ${state !== "new" ? "offline" : f.severity === "info" ? "ok" : f.severity}`} />{" "}
        {f.message} <span className="muted small">({f.evidence})</span>
        {state !== "new" && <span className="pill" style={{ marginLeft: 6 }}>{state === "known" ? "Known" : "Snoozed"}</span>}
        {state === "new" && <button className="linkish small issue-actions"
          onClick={() => onAsk(`What should I do about this on my ${device.name}: ${f.message}`)}>What should I do?</button>}
        <IssueActions device={device} finding={f} />
      </div>
    );
  };
  if (urgent && open.length === 0 && known.length === 0) return null; // the row at the top already says it all
  return (
    <section className="drawer-section">
      <h4>{urgent ? "Other problems" : "Problems"}</h4>
      {open.length === 0 && <p className="muted small">{urgent ? "Nothing else needs a look." : "Nothing needs a look."}</p>}
      {open.map(row)}
      {known.length > 0 && <button className="linkish small" onClick={() => setShowKnown(!showKnown)}>
        {showKnown ? "Hide" : `${known.length} known or snoozed`}</button>}
      {showKnown && known.map(row)}
    </section>
  );
}

function Tags({ device }: { device: Device }) {
  const [tag, setTag] = useState("");
  const save = (tags: string[]) => api("POST", `/api/devices/${device.id}/layout`, { tags }).catch(() => {});
  return (
    <section className="drawer-section tags-edit small">
      <h4>Tags</h4>
      {(device.tags ?? []).map((t) => (
        <span key={t} className="pill">{t} <button className="linkish" aria-label={`Remove ${t}`}
          onClick={() => save((device.tags ?? []).filter((x) => x !== t))}>×</button></span>))}
      {(device.tags ?? []).length < 6 && (
        <form onSubmit={(e) => { e.preventDefault(); if (tag.trim()) { save([...(device.tags ?? []), tag.trim()]); setTag(""); } }}>
          <input value={tag} onChange={(e) => setTag(e.target.value)} maxLength={20}
            placeholder="Add a tag (e.g. Parents)" style={{ padding: "3px 8px" }} />
        </form>)}
    </section>
  );
}
