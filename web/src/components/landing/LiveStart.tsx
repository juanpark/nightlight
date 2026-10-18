"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { clearProblem, minutes, SCENARIOS, startLive, useLive, type LiveStatus, type Problem, type Scenario } from "@/lib/live";

function problemText(p: Problem): string {
  if (p.code === "live_per_visitor_limit") return "You've started several machines in a short time. Please wait a little, or try the demo meanwhile.";
  if (p.code === "live_off") return "Live demo machines are switched off right now.";
  if (p.code === "live_start_failed") return "Your machine didn't start. Please try again in a moment.";
  return "Couldn't start a machine. Please try again.";
}

// The landing page's way onto a live demo machine: a real VM in Google Cloud, leased for this visit (lib/live.ts).
// Shown only while the pool is on; a visit that just ended, or a start that failed, says so here.
export function LiveStart({ styles: s }: { styles: Record<string, string> }) {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [scenario, setScenario] = useState<Scenario>("none");
  const live = useLive();
  const box = useRef<HTMLDivElement>(null);

  // the live line, every 10 s while the page is open (asking also frees machines whose visitors have left)
  useEffect(() => {
    let on = true;
    const load = () => api<LiveStatus>("GET", "/api/demo/live/status").then((r) => { if (on) setStatus(r); }, () => {});
    load();
    const t = setInterval(load, 10000);
    return () => { on = false; clearInterval(t); };
  }, []);

  // a message about the last visit or start sits down here, so bring it into view
  const said = !!(live.ended || live.problem);
  useEffect(() => { if (said) box.current?.scrollIntoView({ block: "center" }); }, [said]);

  const busyAll = live.problem?.code === "live_all_busy";
  if (!status?.enabled && !said) return null;
  const total = live.problem?.total ?? status?.total;
  return (
    <div ref={box} className={s.live} aria-live="polite">
      {live.ended && <p className={s.fine}>Your time on the live machine has ended. It is being reset for the next visitor.</p>}
      {busyAll
        ? <p className={s.fine} role="alert">All {total ?? "the"} live demo machines are in use right now. One is reset and
            freed within a few minutes after each visit; meanwhile, try the demo.</p>
        : live.problem && <p className={s.error} role="alert">{problemText(live.problem)}</p>}
      {status?.enabled && <>
        <p className={s.fine}>Or try it on a real machine: a virtual computer in Google Cloud with real apps, set up like a
          small home server. Everything Nightlight does to it is real. Ready in about {minutes(status.etaSeconds ?? 60)}.</p>
        <div className={s.actionRow}>
          <label className={s.liveLabel}>Start with{" "}
            <select value={scenario} disabled={live.starting} onChange={(e) => setScenario(e.target.value as Scenario)}>
              {SCENARIOS.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
            </select></label>
          <button type="button" className={s.secondary} disabled={live.starting || busyAll}
            onClick={() => { clearProblem(); startLive(scenario); }}>
            {live.starting ? "Starting your machine…" : "Start a live machine"}</button>
        </div>
        <p className={s.liveCount}>Live machines: {status.running} of {status.total} running · {status.inUse} in use.
          Each is reset after you leave ({status.idleMinutes ?? 15} minutes idle, at most {status.maxMinutes ?? 60} minutes).</p>
      </>}
    </div>
  );
}
