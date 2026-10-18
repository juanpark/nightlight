"use client";
// One device, with progressive disclosure: a status sentence and what needs the person first, then three tabs
// (Overview: how it is and what runs there; Knowledge: what Nightlight knows about it, fixes that worked there and
// what was done; Settings: what it may do).
// UX spec 2026-10-17 §2.
import { useEffect, useRef, useState } from "react";
import { Star, X } from "lucide-react";
import { api } from "@/lib/api";
import { useServicesState } from "@/lib/data";
import { useFavorites } from "@/lib/favorites";
import { newer, statusSentence, type Go, type Need } from "@/lib/needsYou";
import type { Action, Device, Service } from "@/lib/types";
import DeviceHistory from "./DeviceHistory";
import Checkups from "./Checkups";
import HelperUpdate from "./HelperUpdate";
import Notebook from "./Notebook";
import Runbooks from "./Runbooks";
import JobLog from "./JobLog";
import DeviceProfile from "./DeviceProfile";
import RemoveDevice from "./RemoveDevice";
import ExpertSessions from "./ExpertSessions";
import Permissions from "./Permissions";
import NeedsList from "./NeedsList";
import WatchedPanel from "./WatchedPanel";
import AppDetail from "./AppDetail";
import SetupCard from "./SetupCard";
import MacFolders, { FOLDERS_FROM } from "./MacFolders";
import { appIcon, deviceIcon } from "./map/kinds";
import { appOrder } from "@/lib/apps";

export type Tab = "overview" | "apps" | "about" | "settings";

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

const TAB_NAME: Record<Tab, string> = { overview: "Overview", apps: "Apps", about: "Knowledge", settings: "Settings" };
// the last tab opened, per kind of device (your own, sample, watched), so the next one opens there too
const kindOf = (d: Device) => d.kind === "watched" ? "watched" : d.realm === "real" ? "device" : "sample";
function lastTab(d: Device): Tab | null {
  try { return localStorage.getItem(`nl_tab_${kindOf(d)}`) as Tab | null; } catch { return null; }
}
function keepTab(d: Device, t: Tab) {
  try { localStorage.setItem(`nl_tab_${kindOf(d)}`, t); } catch { /* this visit only */ }
}

export default function DeviceDrawer({ uid, generation, device, actions, devices, needs, release, tab, onTab, onGo,
  onFollowUp, onAsk, onClose, app, onApp, hidden }: {
  uid: string; generation?: number; device: Device; actions: Action[]; devices: Device[]; needs: Need[];
  release: { version: string } | null; tab: Tab | null; onTab: (t: Tab) => void; onGo: (g: Go) => void;
  onFollowUp: (turnId: string) => void; onAsk: (q: string) => void; onClose: () => void;
  app?: string | null; onApp?: (svcId: string | null) => void; // one app opened on its own, in the Apps tab
  hidden?: boolean; // on a phone, the chat is showing instead
}) {
  const { rows: services, loaded } = useServicesState(uid, device.id);
  const fav = useFavorites(uid, device);
  const real = device.realm === "real";
  const watched = device.kind === "watched";
  const removing = needs.some((n) => n.kind === "removing");
  const box = useRef<HTMLDivElement>(null);
  // Esc closes the panel (not while typing in it); on a phone the sheet takes the keyboard when it opens
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key === "Escape" && !(t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) onClose();
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  // On a phone the panel is a sheet over the whole page: a modal dialog, with everything behind it out of reach
  // (inert) until it closes or the chat is shown instead. On a wide screen it is a side panel beside a usable map.
  const [phone, setPhone] = useState(false);
  useEffect(() => {
    const m = window.matchMedia("(max-width: 900px)");
    setPhone(m.matches);
    const on = () => setPhone(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  const modal = phone && !hidden;
  useEffect(() => {
    if (!modal) return;
    const behind = [...document.querySelectorAll<HTMLElement>(".shell > .top, .main > .left, .main > .right, .shell > .pane-tabs")];
    behind.forEach((el) => el.setAttribute("inert", ""));
    box.current?.focus({ preventScroll: true });
    return () => behind.forEach((el) => el.removeAttribute("inert"));
  }, [modal, device.id]);
  // Each problem is said once: the urgent one as a row under the status sentence (with its "What should I do?"),
  // the rest under Problems.
  const listed = (f: Finding) => needs.some((n) => n.id === `critical:${device.id}:${f.id ?? f.message}`);
  const urgent = (device.findings ?? []).find(listed);
  const brief = !removing && !(real && device.status === "offline") && (device.status === "crit" || device.status === "warn");
  const tabs: Tab[] = watched ? ["overview", "about", "settings"] : real ? ["overview", "apps", "about", "settings"]
    : ["overview", "apps", "about"];
  const wanted = app ? "apps" : tab ?? lastTab(device) ?? "overview";
  const current: Tab = tabs.includes(wanted) ? wanted : "overview";
  const pick = (t: Tab) => { keepTab(device, t); if (t !== "apps") onApp?.(null); onTab(t); };
  const opened = app ? services.find((s) => s.id === app) : undefined;
  // an app that isn't on this device (any more) closes, so it can't come back by itself later
  useEffect(() => { if (app && loaded && !opened) onApp?.(null); }, [app, loaded, opened, onApp]);
  const favApps = fav.apps.map((id) => services.find((s) => s.id === id)).filter((s) => !!s);
  const openApp = (id: string) => { keepTab(device, "apps"); onTab("apps"); onApp?.(id); };

  return (
    <div className={`drawer side ${watched ? "watched" : ""}`} ref={box} tabIndex={-1} role={modal ? "dialog" : "region"}
      aria-modal={modal || undefined} aria-label={`${device.name}: details`}>
      <Head key={device.id} device={device} fav={opened ? undefined : fav} onClose={onClose} />
      <div className="tabs" role="tablist" aria-label={`About the ${device.name}`}>
        {tabs.map((t) => (
          <button key={t} role="tab" aria-selected={current === t} className={current === t ? "on" : ""}
            onClick={() => pick(t)}>{TAB_NAME[t]}{t === "apps" && services.length > 0 &&
              <span className="tab-count">{services.length}</span>}</button>))}
      </div>
      <div className="drawer-body" role="tabpanel">
      {current === "overview" && watched && <>
        <NeedsList needs={needs} actions={actions} devices={devices} onGo={onGo} onFollowUp={onFollowUp} />
        <WatchedPanel key={`watched:${device.id}`} uid={uid} generation={generation} device={device} devices={devices}
          onAsk={onAsk} onGo={onGo} onClose={onClose} part="overview" />
      </>}

      {current === "overview" && !watched && <>
        <SetupCard key={`setup:${device.id}`} device={device} actions={actions} onGo={onGo} />
        <p className="drawer-status">{brief ? `Needs attention ${device.status === "crit" ? "now" : "soon"}.`
          : statusSentence(device, Date.now(), removing)}</p>
        <NeedsList needs={needs} actions={actions} devices={devices} onGo={onGo} onFollowUp={onFollowUp}
          extra={(n) => urgent && real && n.kind === "critical" ? <IssueActions device={device} finding={urgent} /> : null} />
        <div className="drawer-actions">
          <button className="primary" onClick={() => onAsk(`How is my ${device.name} doing?`)}>Ask about this device</button>
        </div>
        {favApps.length > 0 && (
          <section className="drawer-section">
            <h4>Your favorite apps here</h4>
            <AppGrid apps={favApps} fav={fav} onApp={openApp} />
          </section>)}
        {real && device.status === "offline"
          ? <p className="muted small">Last report {device.lastSeen ? device.lastSeen.toLocaleString() : "never"}: Nightlight
              will check what happened when it&apos;s back.</p>
          : <div className="vitals">
              <Vital label="Disk" value={device.vitals?.diskPct} />
              <Vital label="Memory" value={device.vitals?.mem} />
              <Vital label="CPU" value={device.vitals?.cpu} />
            </div>}
        <Problems device={device} skip={listed} onAsk={onAsk} />
        {real && <Checkups uid={uid} generation={generation} deviceId={device.id}
          actions={actions} cleanupOn={!!device.permissions?.cleanup || !!device.allowedJobs?.fix?.length} />}
        {real && <DeviceHistory uid={uid} deviceId={device.id} />}
      </>}

      {current === "apps" && (opened
        ? <AppDetail key={`app:${device.id}:${opened.id}`} uid={uid} generation={generation} device={device} app={opened}
            actions={actions} fav={fav} onBack={() => onApp?.(null)} onAsk={onAsk} />
        : app
          ? <p className="small muted">{loaded ? "That app isn't on this device any more." : "Loading…"}</p>
          : <section className="drawer-section">
              {loaded && services.length === 0 && <p className="muted small">{real ? "Nothing running that Nightlight "
                + "recognises yet. It lists apps that run in the background (a media server, say) and built-in services "
                + "that have stopped working." : "Nothing listed."}</p>}
              {services.length > 0 && <p className="small muted" style={{ marginTop: 0 }}>Tap one to see how it is and
                what Nightlight knows about it.</p>}
              <AppGrid apps={appOrder(services, fav.apps)} fav={fav} onApp={openApp} />
            </section>)}

      {current === "about" && <>
        {!watched && <DeviceProfile uid={uid} deviceId={device.id} />}
        <Notebook uid={uid} deviceId={device.id} />
        {!watched && <Runbooks key={`rb:${device.id}`} uid={uid} generation={generation} device={device} onAsk={onAsk} />}
        {!watched && <JobLog key={`log:${device.id}`} deviceId={device.id} actions={actions} />}
        <Tags device={device} />
        {!watched && <section className="drawer-section">
          <h4>Details</h4>
          <div className="details small">
            <div><span className="muted">System</span>{device.os ?? "–"}</div>
            <div><span className="muted">Running for</span>{uptime(device.vitals?.uptime)}</div>
            <div><span className="muted">Background apps</span>{device.containerCount != null
              ? `${device.containersRunning ?? 0} of ${device.containerCount} running` : "–"}</div>
            <div><span className="muted">Updates waiting</span>{device.updatesPending ?? "–"}</div>
            <div><span className="muted">Nightlight helper</span>{device.helperVersion ? `version ${device.helperVersion}` : "–"}
              {device.helperVersion && <span className="muted small"> · {updateMode(device)}</span>}</div>
          </div>
          <details className="small">
            <summary className="muted">Technical details</summary>
            <div className="details small">
              <div><span className="muted">Processor type</span>{device.arch ?? "–"}</div>
              <div><span className="muted">Docker containers</span>{device.containerCount != null
                ? `${device.containersRunning ?? 0} of ${device.containerCount} running` : "–"}</div>
            </div>
          </details>
          {device.purpose && <p className="muted small">{device.purpose}</p>}
        </section>}
      </>}

      {current === "settings" && watched && (
        <WatchedPanel key={`watched-s:${device.id}`} uid={uid} generation={generation} device={device} devices={devices}
          onAsk={onAsk} onGo={onGo} onClose={onClose} part="settings" />)}

      {current === "settings" && !watched && <>
        <Permissions key={device.id} device={device} services={services} />
        {device.manage === "app" && /mac/i.test(device.os ?? "") && !newer(FOLDERS_FROM, device.helperVersion) && (
          <section className="drawer-section">
            <h4>Personal folders</h4>
            <MacFolders key={device.id} device={device} actions={actions} />
          </section>)}
        <section className="drawer-section">
          <h4>Updates</h4>
          <HelperUpdate device={device} actions={actions} latest={release?.version}
            origin={typeof window === "undefined" ? "" : window.location.origin} />
          {!(release && device.helperVersion && release.version !== device.helperVersion) &&
            <p className="muted small">Up to date (version {device.helperVersion ?? "?"}) · {updateMode(device)}.</p>}
        </section>
        <ExpertSessions uid={uid} device={device} open={needs.some((n) => n.kind === "expertHalf")} />
        <RemoveDevice device={device} onRemoved={onClose} />
      </>}
      </div>
    </div>
  );
}

/** Apps as chips, two to a row: icon, name, status colour, a star when starred; a tap opens the app. */
function AppGrid({ apps, fav, onApp }: { apps: Service[]; fav: Favorites; onApp: (id: string) => void }) {
  return (
    <div className="app-grid">
      {apps.map((s) => {
        const Icon = appIcon(s);
        return (
          <button key={s.id} className={`app-chip ${s.status ?? "ok"}`} onClick={() => onApp(s.id)}
            aria-label={`${s.name}: ${(s.status ?? "ok") === "ok" ? "running fine" : "needs a look"}`}>
            <Icon size={15} aria-hidden /><span className="app-chip-name">{s.name}</span>
            {fav.isFavoriteApp(s.id) && <Star className="dstar" size={12} aria-hidden />}
            <span className={`dot ${s.status ?? "ok"}`} aria-hidden />
          </button>);
      })}
    </div>
  );
}

type Finding = NonNullable<Device["findings"]>[number];

/** Name (renamable on real devices), what kind of thing it is, Live or Sample, Close. */
function Head({ device, fav, onClose }: { device: Device; fav?: Favorites; onClose: () => void }) {
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
      {fav && <StarButton on={fav.favorite} label={`${device.name} as a favorite`} onClick={fav.toggleDevice} />}
      <button className="drawer-close" onClick={onClose} aria-label="Close"><X size={18} /></button>
      {fav?.err && <p className="small" style={{ color: "var(--crit)", flexBasis: "100%", margin: 0 }}>{fav.err}</p>}
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

type Favorites = ReturnType<typeof useFavorites>;

/** A star that says what it does: "Star …" / "Unstar …" for screen readers, filled when on. */
function StarButton({ on, label, small, onClick }: { on: boolean; label: string; small?: boolean; onClick: () => void }) {
  return (
    <button className={`star-btn ${on ? "on" : ""} ${small ? "small" : ""}`} aria-pressed={on}
      aria-label={`${on ? "Unstar" : "Star"} ${label}`} title={on ? "Starred: tap to unstar" : "Star it"} onClick={onClick}>
      <Star size={small ? 14 : 16} />
    </button>
  );
}
