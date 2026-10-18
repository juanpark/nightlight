"use client";
import { useState } from "react";

export interface SparkPoint { t: number; v: number | null }

const W = 300;
/** Points further apart than this are drawn as a gap (the device wasn't reporting). */
const GAP_MS = 15 * 60 * 1000;

const at = (t: number, long: boolean) => new Date(t).toLocaleString([], long
  ? { weekday: "short", hour: "numeric", minute: "2-digit" } : { hour: "numeric", minute: "2-digit" });

/** A tiny line chart with no axes: label and value on top, the line below. Pointing at it (or focusing it and using
 * the arrow keys) shows the reading at that moment in the head, with a hairline on the chart; leaving shows the latest.
 * Dependency-free inline SVG. `from`/`to` fix the time window so a short history sits at the right-hand end. */
export default function Sparkline({ points, label, unit = "%", height = 56, from, to, max }: {
  points: SparkPoint[]; label: string; unit?: string; height?: number; from?: number; to?: number; max?: number;
}) {
  const known = points.filter((p) => p.v != null) as { t: number; v: number }[];
  const [pick, setPick] = useState<number | null>(null); // index into known
  const t0 = from ?? points[0]?.t ?? 0;
  const t1 = to ?? points[points.length - 1]?.t ?? 1;
  const long = t1 - t0 > 2 * 86400000;
  const top = max ?? (unit === "%" ? 100 : Math.max(1, ...known.map((p) => p.v)));
  const x = (t: number) => ((t - t0) / Math.max(1, t1 - t0)) * W;
  const y = (v: number) => height - 2 - (Math.min(v, top) / top) * (height - 4);

  let d = "";
  let prev: number | null = null;
  for (const p of points) {
    if (p.v == null) { prev = null; continue; }
    d += `${prev == null || p.t - prev > GAP_MS ? "M" : "L"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)} `;
    prev = p.t;
  }
  const firstX = known.length ? x(known[0].t) : 0;
  const lastX = known.length ? x(known[known.length - 1].t) : 0;
  const area = d && known.length > 1 ? `${d} L${lastX.toFixed(1)},${height - 1} L${firstX.toFixed(1)},${height - 1} Z` : "";
  const latest = known[known.length - 1];
  const peak = known.length ? Math.max(...known.map((p) => p.v)) : null;
  const shown = pick != null ? known[pick] : latest;

  // the nearest reading to where the pointer is, by time
  const near = (clientX: number, box: DOMRect) => {
    const t = t0 + ((clientX - box.left) / box.width) * (t1 - t0);
    let best = 0;
    known.forEach((p, i) => { if (Math.abs(p.t - t) < Math.abs(known[best].t - t)) best = i; });
    return best;
  };

  return (
    <div className="spark">
      <div className="spark-head small">
        <span className="muted">{label}</span>
        <strong>{shown == null ? "–" : `${Math.round(shown.v)}${unit}`}</strong>
        <span className="muted spark-when">{shown == null ? "" : pick != null ? at(shown.t, long) : "now"}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" height={height} width="100%" role="img"
        tabIndex={known.length ? 0 : undefined}
        aria-label={latest == null ? `${label}: no data yet`
          : `${label}: now ${Math.round(latest.v)}${unit}, highest ${Math.round(peak!)}${unit}. Use the arrow keys to read earlier values.`}
        onPointerMove={(e) => known.length && setPick(near(e.clientX, e.currentTarget.getBoundingClientRect()))}
        onPointerLeave={() => setPick(null)} onBlur={() => setPick(null)}
        onKeyDown={(e) => {
          if (!known.length || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
          e.preventDefault();
          const i = pick ?? known.length - 1;
          setPick(Math.max(0, Math.min(known.length - 1, i + (e.key === "ArrowLeft" ? -1 : 1))));
        }}>
        <rect x="0" y="0" width={W} height={height} className="spark-box" vectorEffect="non-scaling-stroke" />
        {unit === "%" && <line x1="0" x2={W} y1={y(50)} y2={y(50)} className="spark-mid" vectorEffect="non-scaling-stroke" />}
        {area && <path d={area} className="spark-area" />}
        {d && <path d={d} className="spark-line" vectorEffect="non-scaling-stroke" />}
        {pick != null && shown && <line className="spark-cross" x1={x(shown.t)} x2={x(shown.t)} y1={0} y2={height}
          vectorEffect="non-scaling-stroke" />}
      </svg>
      <span className="sr-only" aria-live="polite">{pick != null && shown ? `${label} ${Math.round(shown.v)}${unit} at ${at(shown.t, long)}` : ""}</span>
    </div>
  );
}
