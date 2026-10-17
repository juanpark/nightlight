"use client";
// "What Nightlight may do here": the owner's switches for an app-managed device, or a read-only view of what the
// device applies when it is strict or runs an older helper. The device report (`allowedJobs`) is the truth of what
// is in force; the switches are a wish the device picks up on its next report.
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { applied, DEFAULTS, normal, samePerms } from "@/lib/permissions";
import type { Device, Permissions as Perms, Service } from "@/lib/types";

// Presets (UX spec §3.3): most people pick one of two, and only a few open the switches. "diagnose" is in both
// because without it Nightlight can't explain anything; "updates" too, since signed updates are how the helper gets
// fixes without a terminal.
type Preset = "watch" | "fix" | "custom";
const WATCH: Perms = { ...DEFAULTS };
const fixAll = (targets: string[], containers: string[], units: string[]): Perms => ({ diagnose: true, cleanup: true,
  updates: true, autoUpdate: true, logs: targets, restart_container: containers, restart_service: units });
export const PRESETS: { id: Preset; name: string; copy: string }[] = [
  { id: "watch", name: "Just watch", copy: "Reports health and explains problems. Changes nothing." },
  { id: "fix", name: "Watch and fix safe things", copy: "Also reads recent logs, restarts stopped apps and cleans up "
    + "space, each after your OK. Keeps its helper up to date." },
  { id: "custom", name: "Custom", copy: "Your own mix below." },
];
const presetKey = (id: string) => `nl_preset_${id}`;
export function chosePreset(id: string): boolean {
  try { return !!localStorage.getItem(presetKey(id)); } catch { return false; }
}

const list = (names: string[]) => names.includes("*") ? "everything it checks" : names.join(", ");

/** Plain-words rows for what the device says it applies. */
function Applies({ jobs = {} }: { jobs?: Record<string, string[]> }) {
  const rows = [
    jobs.diagnose?.length ? "Check why something stopped (reads status only)" : null,
    jobs.inspect?.length ? "Look around when asked: disk use, busiest programs, updates, network (reads only)" : null,
    jobs.fix?.length ? "Clean up space after you approve (Trash, caches that rebuild themselves, unused images)" : null,
    jobs.logs?.length ? `Read recent log lines of ${list(jobs.logs)}` : null,
    jobs.restart_container?.length ? `Restart ${list(jobs.restart_container)} after you approve` : null,
    jobs.restart_service?.length ? `Restart the system service ${list(jobs.restart_service)} after you approve` : null,
  ].filter(Boolean) as string[];
  return (
    <ul className="perm-list small">
      {rows.length ? rows.map((r) => <li key={r}>{r}</li>)
        : <li className="muted">Nothing yet: it only reports how the device is doing.</li>}
    </ul>
  );
}

function Switch({ on, label, hint, onChange, disabled }: {
  on: boolean; label: string; hint?: string; onChange: (on: boolean) => void; disabled?: boolean;
}) {
  return (
    <label className="perm-switch">
      <input type="checkbox" checked={on} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}{hint && <span className="small muted"> {hint}</span>}</span>
    </label>
  );
}

const toggle = (names: string[], name: string, on: boolean) =>
  on ? [...new Set([...names, name])] : names.filter((n) => n !== name);

export default function Permissions({ device, services }: { device: Device; services: Service[] }) {
  const server = normal(device.permissions);
  const [pending, setPending] = useState<Perms | null>(null);
  const [error, setError] = useState("");
  const [origin, setOrigin] = useState("");
  const seq = useRef(0);
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<Preset | null>(null);
  useEffect(() => { setOrigin(window.location.origin); }, []);
  // Once the device doc carries what we sent, the server copy is the truth again.
  const serverKey = JSON.stringify(server);
  useEffect(() => {
    if (pending && samePerms(pending, server)) setPending(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey]);
  useEffect(() => {
    setPending(null); setError(""); setOpen(false);
    try { setChosen(localStorage.getItem(presetKey(device.id)) as Preset | null); } catch { setChosen(null); }
  }, [device.id]);

  const jobs = device.allowedJobs ?? {};
  const want = pending ?? server;
  const containers = [...new Set([...services.filter((s) => s.kind === "container").map((s) => s.name),
    ...want.restart_container])].sort();
  const units = [...new Set([...services.filter((s) => s.kind === "system" && s.unit).map((s) => s.unit!),
    ...want.restart_service])].sort();
  const targets = [...new Set([...containers, ...units, ...want.logs])].sort();
  const fix = fixAll(targets, containers, units);
  const preset: Preset = samePerms(want, WATCH) ? "watch" : samePerms(want, fix) ? "fix" : "custom";
  // Permissions only change on a click: a preset chosen earlier never widens anything by itself. When apps appeared
  // after "Watch and fix safe things" was chosen, the person is told and taps it again to include them.
  const within = (a: string[], b: string[]) => a.every((x) => b.includes(x));
  const grew = chosen === "fix" && preset === "custom" && want.diagnose && want.cleanup && want.updates
    && want.autoUpdate && within(want.logs, fix.logs) && within(want.restart_container, fix.restart_container)
    && within(want.restart_service, fix.restart_service);

  if (device.manage !== "app") {
    return (
      <section className="perms">
        <h4>What Nightlight may do here</h4>
        <Applies jobs={jobs} />
        {device.manage === "strict"
          ? <p className="small muted">Set on the device (strict): change permissions there
              with <code>nightlight settings</code>. Presets are for devices managed from the app.</p>
          : <p className="small muted">Update the helper to manage permissions from here. On the device, run
              <code className="perm-cmd">curl -fsSL {origin}/install.sh | sh</code></p>}
      </section>
    );
  }

  const allLogs = targets.length > 0 && targets.every((t) => want.logs.includes(t));

  function edit(next: Perms) { // a switch by hand: the mix is the person's own from now on
    try { localStorage.setItem(presetKey(device.id), "custom"); } catch { /* this visit only */ }
    setChosen("custom");
    save(next);
  }

  async function save(next: Perms) {
    const mine = ++seq.current;
    setPending(next);
    setError("");
    try {
      await api("POST", `/api/devices/${device.id}/permissions`, next);
    } catch (e) {
      if (mine !== seq.current) return;
      setPending(null);
      setError(e instanceof ApiError && e.status === 409 && e.code === "strict_device"
        ? "This device only accepts changes made on the device itself."
        : "Couldn't save that change. Please try again.");
    }
  }

  const inForce = applied(want, jobs, containers.length === 0 && units.length === 0);
  function pick(p: Preset) {
    try { localStorage.setItem(presetKey(device.id), p); } catch { /* remembered for this visit only */ }
    setChosen(p);
    if (p === "watch") save(WATCH);
    else if (p === "fix") save(fix);
    else setOpen(true);
  }
  return (
    <section className="perms">
      <h4>What Nightlight may do here</h4>
      <div className="mode-switch presets" role="radiogroup" aria-label="How much may Nightlight do here?">
        {PRESETS.map((p) => (
          <button key={p.id} role="radio" aria-checked={(chosen === "custom" ? "custom" : preset) === p.id}
            className={(chosen === "custom" ? "custom" : preset) === p.id ? "on" : ""} onClick={() => pick(p.id)}>
            {p.name}{p.id === "fix" && <span className="small"> (recommended)</span>}</button>
        ))}
        <span className="mode-hint small muted">
          {grew ? "New apps appeared since you chose this. Tap Watch and fix safe things again to include them."
            : PRESETS.find((p) => p.id === (chosen === "custom" ? "custom" : preset))?.copy}</span>
      </div>
      <details className="perm-switches" open={open || preset === "custom"}
        onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
        <summary className="small muted">Choose one by one</summary>
      <Switch on={want.diagnose} label="Check why something stopped and look around"
        hint="(reads only: status, disk use, busiest programs, updates, network)"
        onChange={(on) => edit({ ...want, diagnose: on })} />

      <Switch on={want.cleanup} label="Clean up space after you approve"
        hint="(empty the Trash, clear caches that rebuild themselves, remove unused Docker images; a card each time)"
        onChange={(on) => edit({ ...want, cleanup: on })} />

      <Switch on={want.updates} label="Install Nightlight updates from the app"
        hint="(only versions signed by Nightlight; checked on the device)"
        onChange={(on) => edit({ ...want, updates: on, autoUpdate: on && want.autoUpdate })} />
      {want.updates && <Switch on={want.autoUpdate} label="Install signed updates automatically"
        hint="(otherwise you tap Update each time)" onChange={(on) => edit({ ...want, autoUpdate: on })} />}

      <Switch on={allLogs} label="Read recent log lines" hint="(private details hidden on the device first)"
        disabled={targets.length === 0} onChange={(on) => edit({ ...want, logs: on ? targets : [] })} />
      {targets.length === 0 && <div className="small muted perm-note">Nothing to read here yet: this appears when an
        app or service on this device can be checked (containers, or a system service that stopped).</div>}
      {targets.length > 0 && (
        <details className="perm-more small">
          <summary className="muted">{allLogs ? "For everything it checks" : want.logs.length
            ? `For ${want.logs.join(", ")}` : "Or choose one by one"}</summary>
          {targets.map((t) => <Switch key={t} on={want.logs.includes(t)} label={t}
            onChange={(on) => edit({ ...want, logs: toggle(want.logs, t, on) })} />)}
        </details>
      )}

      <div className="perm-group">
        <div>Restart a stopped app after you approve</div>
        {containers.length === 0 && units.length === 0 && (
          <div className="small muted">Nothing to restart right now: this lists containers and services that stopped.</div>)}
        {containers.map((c) => <Switch key={c} on={want.restart_container.includes(c)} label={c}
          onChange={(on) => edit({ ...want, restart_container: toggle(want.restart_container, c, on) })} />)}
        {units.length > 0 && <>
          {units.map((u) => <Switch key={u} on={want.restart_service.includes(u)} label={u} hint="(system service)"
            onChange={(on) => edit({ ...want, restart_service: toggle(want.restart_service, u, on) })} />)}
          <div className="small muted">Needs administrator rights on the device; see the README.</div>
        </>}
      </div>
      </details>

      {error && <p className="small" style={{ color: "var(--crit)" }}>{error}</p>}
      <p className="small muted perm-foot">
        <span className={`dot ${inForce ? "ok" : "offline"}`} />
        {inForce ? "Applied" : "Waiting for the device…"}
        <span> · Applies within about a minute (on the device&apos;s next report).</span>
      </p>
    </section>
  );
}
