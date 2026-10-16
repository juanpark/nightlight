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
            <button key={k} className={`small ${range === k ? "on" : ""}`} onClick={() => setRange(k)}>
              {RANGES[k].label}</button>))}
        </span>
      </div>
      {shown.length === 0
        ? <p className="small muted" style={{ margin: "4px 0" }}>History starts building now (one point every 5 minutes).</p>
        : <>
            <StatusStrip points={shown} from={from} to={to} />
            <div className="sparks">
              <Sparkline label="Disk" points={series("disk")} from={from} to={to} />
              <Sparkline label="Memory" points={series("mem")} from={from} to={to} />
              <Sparkline label="CPU" points={series("cpu")} from={from} to={to} />
            </div>
          </>}
    </div>
  );
}
