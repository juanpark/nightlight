"use client";
// Every job that finished on this device, newest first: what ran, who started it, how it went, and what a look
// printed. Read from the server when the panel opens and whenever another job here finishes.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { aboutApp } from "@/lib/apps";
import type { Action, LogJob, Service } from "@/lib/types";

const BY = { you: "You approved", nightlight: "Nightlight, as you allowed", device: "The device" } as const;

export default function JobLog({ deviceId, actions, app }: { deviceId: string; actions: Action[]; app?: Service }) {
  const [loaded, setJobs] = useState<LogJob[] | null>(null);
  const jobs = loaded && app ? loaded.filter(aboutApp(app)) : loaded; // given an app, only the jobs about it
  const [all, setAll] = useState(false);
  // a new finished job on this device refreshes the log
  const finished = actions.filter((a) => a.deviceId === deviceId && (a.status === "done" || a.status === "failed")).length;
  useEffect(() => {
    let live = true;
    api<{ jobs: LogJob[] }>("GET", `/api/devices/${deviceId}/log?limit=50`)
      .then((r) => { if (live) setJobs(r.jobs); }).catch(() => { if (live) setJobs((cur) => cur ?? []); });
    return () => { live = false; };
  }, [deviceId, finished]);
  const shown = (jobs ?? []).slice(0, all ? 50 : 5);
  return (
    <section className="drawer-section">
      <h4>What was done here</h4>
      {jobs && jobs.length === 0 && <p className="small muted">{app ? `Nothing done to ${app.name} yet.`
        : "Nothing yet. Every job that runs here will be listed."}</p>}
      {shown.map((j) => (
        <div key={j.actionId} className="logrow small">
          <span className={`dot ${j.ok ? "ok" : "crit"}`} />
          <div className="logrow-body">
            <div><strong>{j.title}</strong>{j.service && <span className="pill" style={{ marginLeft: 6 }}>{j.service}</span>}</div>
            {j.summary && <div>{j.summary}</div>}
            <div className="muted">{new Date(j.at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })} · {BY[j.by] ?? j.by}</div>
            {(j.output || j.command) && (
              <details><summary className="muted">{j.command ? "Command and output" : "What it printed"}</summary>
                {j.command && <code className="wl-cmd">{j.command}</code>}
                {j.output && <pre className="wl-out">{j.output}</pre>}
              </details>)}
          </div>
        </div>))}
      {(jobs?.length ?? 0) > 5 && <button className="linkish small" onClick={() => setAll(!all)}>
        {all ? "Show fewer" : `Show all ${jobs!.length}`}</button>}
    </section>
  );
}
