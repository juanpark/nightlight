"use client";

export interface SparkPoint { t: number; v: number | null }

const W = 300;
/** Points further apart than this are drawn as a gap (the device wasn't reporting). */
const GAP_MS = 15 * 60 * 1000;

/** A tiny line chart with no axes: label and latest value on top, the line below. Dependency-free inline SVG.
 * `from`/`to` fix the time window so a short history sits at the right-hand end instead of stretching. */
export default function Sparkline({ points, label, unit = "%", height = 56, from, to, max }: {
  points: SparkPoint[]; label: string; unit?: string; height?: number; from?: number; to?: number; max?: number;
}) {
  const known = points.filter((p) => p.v != null) as { t: number; v: number }[];
  const t0 = from ?? points[0]?.t ?? 0;
  const t1 = to ?? points[points.length - 1]?.t ?? 1;
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
  const latest = known[known.length - 1]?.v;
  const peak = known.length ? Math.max(...known.map((p) => p.v)) : null;

  return (
    <div className="spark">
      <div className="spark-head small">
        <span className="muted">{label}</span>
        <strong>{latest == null ? "–" : `${Math.round(latest)}${unit}`}</strong>
        {unit === "%" && <span className="muted spark-scale">0–100%</span>}
      </div>
      <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" height={height} width="100%" role="img"
        aria-label={latest == null ? `${label}: no data yet`
          : `${label}: now ${Math.round(latest)}${unit}, highest ${Math.round(peak!)}${unit}`}>
        <rect x="0" y="0" width={W} height={height} className="spark-box" vectorEffect="non-scaling-stroke" />
        {unit === "%" && <line x1="0" x2={W} y1={y(50)} y2={y(50)} className="spark-mid" vectorEffect="non-scaling-stroke" />}
        {area && <path d={area} className="spark-area" />}
        {d && <path d={d} className="spark-line" vectorEffect="non-scaling-stroke" />}
      </svg>
    </div>
  );
}
