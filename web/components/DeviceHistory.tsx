"use client";
import { useState } from "react";
import { useHistory } from "@/lib/data";
import type { HistoryPoint } from "@/lib/types";
import Sparkline from "./Sparkline";

const RANGES = { day: { label: "Last 24 hours", ms: 86400000 }, week: { label: "7 days", ms: 7 * 86400000 } } as const;
const STEP_MS = 5 * 60 * 1000;
const STATUS_WORD = { ok: "all good", warn: "needs attention", crit: "urgent" } as const;

/** A thin bar across the window: one coloured segment per history point, lasting until the next point (or one
 * reporting interval). Blank where the device wasn't reporting. */
function StatusStrip({ points, from, to }: { points: HistoryPoint[]; from: number; to: number }) {
  const W = 300;
  const x = (t: number) => ((t - from) / (to - from)) * W;
  return (
    <svg className="status-strip" viewBox={`0 0 ${W} 6`} preserveAspectRatio="none" width="100%" height={6}
      role="img" aria-label="Health over time">
      {points.map((p, i) => {
        const t = p.at!.getTime();
        const next = points[i + 1]?.at?.getTime() ?? t + STEP_MS;
        const end = Math.min(next, t + 2 * STEP_MS, to);
        return <rect key={p.id} x={x(t)} y={0} width={Math.max(0.6, x(end) - x(t))} height={6}
          style={{ fill: `var(--${p.status})` }}><title>{`${p.at!.toLocaleString()}: ${STATUS_WORD[p.status] ?? p.status}`}</title></rect>;
      })}
    </svg>
  );
}

const pct = (v: number | null | undefined) => v == null ? "–" : `${Math.round(v)}%`;

/** One reading per step (the latest in each), newest first: the history as a short table. */
function sample(points: HistoryPoint[], step: number): HistoryPoint[] {
  const byStep = new Map<number, HistoryPoint>();
  for (const p of points) byStep.set(Math.floor(p.at!.getTime() / step), p);
  return [...byStep.values()].reverse();
}

/** The health strip in words: "All good for the last 24 hours" / "Needed attention 3 times in 7 days". */
function healthWords(points: HistoryPoint[], range: string): string {
  let times = 0;
  points.forEach((p, i) => { if (p.status !== "ok" && points[i - 1]?.status === "ok") times++; });
  if (points[0] && points[0].status !== "ok") times++;
  return times === 0 ? `Healthy the whole time (${range}).`
    : `Needed attention ${times === 1 ? "once" : `${times} times`} (${range}); the coloured marks above show when.`;
}

/** Disk, memory and CPU over the last day or week, for a real device. */
export default function DeviceHistory({ uid, deviceId }: { uid: string; deviceId: string }) {
  const history = useHistory(uid, deviceId);
  const [range, setRange] = useState<keyof typeof RANGES>("day");
  const to = Date.now();
  const from = to - RANGES[range].ms;
  const shown = history.filter((p) => p.at && p.at.getTime() >= from);
  const series = (k: "disk" | "mem" | "cpu") => shown.map((p) => ({ t: p.at!.getTime(), v: p[k] }));

  return (
    <div className="history">
      <div className="history-head">
        <span className="small muted" style={{ fontWeight: 600 }}>History</span>
        <span className="tabs" role="group" aria-label="Time range">
          {(Object.keys(RANGES) as (keyof typeof RANGES)[]).map((k) => (
            <button key={k} className={`small ${range === k ? "on" : ""}`} aria-pressed={range === k} onClick={() => setRange(k)}>
              {RANGES[k].label}</button>))}
        </span>
      </div>
      {shown.length === 0
        ? <p className="small muted" style={{ margin: "4px 0" }}>History starts building now (one point every 5 minutes).</p>
        : <>
            <StatusStrip points={shown} from={from} to={to} />
            <p className="small muted strip-words">{healthWords(shown, RANGES[range].label.toLowerCase())}</p>
            <div className="sparks">
              <Sparkline label="Disk" points={series("disk")} from={from} to={to} />
              <Sparkline label="Memory" points={series("mem")} from={from} to={to} />
              <Sparkline label="CPU" points={series("cpu")} from={from} to={to} />
            </div>
            <details className="history-table small">
              <summary>Show as a table</summary>
              <table>
                <thead><tr><th scope="col">Time</th><th scope="col">Health</th><th scope="col">Disk</th>
                  <th scope="col">Memory</th><th scope="col">CPU</th></tr></thead>
                <tbody>{sample(shown, range === "day" ? 3600000 : 12 * 3600000).map((p) => (
                  <tr key={p.id}><td>{p.at!.toLocaleString([], range === "day" ? { hour: "numeric", minute: "2-digit" }
                    : { weekday: "short", hour: "numeric" })}</td>
                    <td>{STATUS_WORD[p.status as keyof typeof STATUS_WORD] ?? p.status}</td>
                    <td>{pct(p.disk)}</td><td>{pct(p.mem)}</td><td>{pct(p.cpu)}</td></tr>))}</tbody>
              </table>
            </details>
          </>}
    </div>
  );
}
