"use client";
// "What Nightlight may do here": the owner's switches for an app-managed device, or a read-only view of what the
// device applies when it is strict or runs an older helper. The device report (`allowedJobs`) is the truth of what
// is in force; the switches are a wish the device picks up on its next report.
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Device, Permissions as Perms, Service } from "@/lib/types";

const DEFAULTS: Perms = { diagnose: true, logs: [], restart_container: [], restart_service: [] };

function normal(p?: Partial<Perms> | null): Perms {
  return {
    diagnose: p?.diagnose ?? DEFAULTS.diagnose,
    logs: p?.logs ?? [],
    restart_container: p?.restart_container ?? [],
    restart_service: p?.restart_service ?? [],
  };
}

const sameSet = (a: string[], b: string[]) => {
  const x = new Set(a), y = new Set(b);
  return x.size === y.size && [...x].every((v) => y.has(v));
};

const samePerms = (a: Perms, b: Perms) => a.diagnose === b.diagnose && sameSet(a.logs, b.logs)
  && sameSet(a.restart_container, b.restart_container) && sameSet(a.restart_service, b.restart_service);

/** True when what the device reports applying matches the owner's switches ("*" on the device means everything). */
function applied(want: Perms, jobs: Record<string, string[]> = {}, nothingHere = false): boolean {
  const has = (k: string, names: string[]) => {
    const got = jobs[k] ?? [];
    return got.includes("*") ? names.length > 0 : sameSet(got, names);
  };
  // With nothing to check on the device, "check why" has nothing to apply: on and empty counts as applied.
  const diagnoseOk = want.diagnose === (jobs.diagnose?.length ?? 0) > 0 || (want.diagnose && nothingHere);
  const lookOk = want.diagnose || !jobs.inspect?.length; // the same switch covers looking around (helper 0.8+)
  return diagnoseOk && lookOk && has("logs", want.logs)
    && has("restart_container", want.restart_container) && has("restart_service", want.restart_service);
}

const list = (names: string[]) => names.includes("*") ? "everything it checks" : names.join(", ");

/** Plain-words rows for what the device says it applies. */
function Applies({ jobs = {} }: { jobs?: Record<string, string[]> }) {
  const rows = [
    jobs.diagnose?.length ? "Check why something stopped (reads status only)" : null,
    jobs.inspect?.length ? "Look around when asked: disk use, busiest programs, updates, network (reads only)" : null,
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
  useEffect(() => { setOrigin(window.location.origin); }, []);
  // Once the device doc carries what we sent, the server copy is the truth again.
  const serverKey = JSON.stringify(server);
  useEffect(() => {
    if (pending && samePerms(pending, server)) setPending(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey]);
  useEffect(() => { setPending(null); setError(""); }, [device.id]);

  const jobs = device.allowedJobs ?? {};

  if (device.manage !== "app") {
    return (
      <section className="perms">
        <h4>What Nightlight may do here</h4>
        <Applies jobs={jobs} />
        {device.manage === "strict"
          ? <p className="small muted">This device is set to strict: change permissions on the device
              with <code>nightlight settings</code>.</p>
          : <p className="small muted">Update the helper to manage permissions from here. On the device, run
              <code className="perm-cmd">curl -fsSL {origin}/install.sh | sh</code></p>}
      </section>
    );
  }

  const want = pending ?? server;
  const containers = [...new Set([...services.filter((s) => s.kind === "container").map((s) => s.name),
    ...want.restart_container])].sort();
  const units = [...new Set([...services.filter((s) => s.kind === "system" && s.unit).map((s) => s.unit!),
    ...want.restart_service])].sort();
  const targets = [...new Set([...containers, ...units, ...want.logs])].sort();
  const allLogs = targets.length > 0 && targets.every((t) => want.logs.includes(t));

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
  return (
    <section className="perms">
      <h4>What Nightlight may do here</h4>
      <Switch on={want.diagnose} label="Check why something stopped and look around"
        hint="(reads only: status, disk use, busiest programs, updates, network)"
        onChange={(on) => save({ ...want, diagnose: on })} />

      <Switch on={allLogs} label="Read recent log lines" hint="(private details hidden on the device first)"
        disabled={targets.length === 0} onChange={(on) => save({ ...want, logs: on ? targets : [] })} />
      {targets.length === 0 && <div className="small muted perm-note">Nothing to read here yet: this appears when an
        app or service on this device can be checked (containers, or a system service that stopped).</div>}
      {targets.length > 0 && (
        <details className="perm-more small">
          <summary className="muted">{allLogs ? "For everything it checks" : want.logs.length
            ? `For ${want.logs.join(", ")}` : "Or choose one by one"}</summary>
          {targets.map((t) => <Switch key={t} on={want.logs.includes(t)} label={t}
            onChange={(on) => save({ ...want, logs: toggle(want.logs, t, on) })} />)}
        </details>
      )}

      <div className="perm-group">
        <div>Restart a stopped app after you approve</div>
        {containers.length === 0 && units.length === 0 && (
          <div className="small muted">Nothing to restart right now: this lists containers and services that stopped.</div>)}
        {containers.map((c) => <Switch key={c} on={want.restart_container.includes(c)} label={c}
          onChange={(on) => save({ ...want, restart_container: toggle(want.restart_container, c, on) })} />)}
        {units.length > 0 && <>
          {units.map((u) => <Switch key={u} on={want.restart_service.includes(u)} label={u} hint="(system service)"
            onChange={(on) => save({ ...want, restart_service: toggle(want.restart_service, u, on) })} />)}
          <div className="small muted">Needs administrator rights on the device; see the README.</div>
        </>}
      </div>

      {error && <p className="small" style={{ color: "var(--crit)" }}>{error}</p>}
      <p className="small muted perm-foot">
        <span className={`dot ${inForce ? "ok" : "offline"}`} />
        {inForce ? "Applied" : "Waiting for the device…"}
        <span> · Applies within about a minute (on the device&apos;s next report).</span>
      </p>
    </section>
  );
}
