// Disk, memory and CPU as plain meters: a word first ("Almost full"), then the bar and the number. The bar takes the
// status colour only past a threshold, and the word always says the same thing, so colour is never the only signal.
import type { Device } from "@/lib/types";

type Level = "ok" | "warn" | "crit";
const level = (v: number): Level => v >= 90 ? "crit" : v >= 75 ? "warn" : "ok";

const WORDS: Record<string, Record<Level, string>> = {
  Disk: { ok: "Plenty of room", warn: "Getting full", crit: "Almost full" },
  Memory: { ok: "Comfortable", warn: "Busy", crit: "Very busy" },
  CPU: { ok: "Relaxed", warn: "Busy", crit: "Working very hard" },
};

/** The worst of the three, as a short phrase for a folded section's title ("Disk almost full"), or null when all are fine. */
export function vitalsHeadline(d: Device): string | null {
  const vs = [["Disk", d.vitals?.diskPct], ["Memory", d.vitals?.mem], ["CPU", d.vitals?.cpu]] as const;
  let worst: { name: string; v: number } | null = null;
  for (const [name, v] of vs) if (v != null && level(v) !== "ok" && (!worst || v > worst.v)) worst = { name, v };
  return worst ? `${worst.name} ${WORDS[worst.name][level(worst.v)].toLowerCase()}` : null;
}

function Meter({ label, value }: { label: string; value?: number | null }) {
  const v = value == null ? null : Math.min(100, Math.max(0, value));
  const l = v == null ? null : level(v);
  return (
    <div className={`meter ${l ?? "none"}`}>
      <div className="meter-head">
        <span className="meter-label">{label}</span>
        <span className="meter-word">{l ? WORDS[label][l] : "Not known yet"}</span>
        <span className="meter-value">{v == null ? "–" : `${Math.round(v)}%`}</span>
      </div>
      <div className="meter-track" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100}
        aria-valuenow={v ?? undefined} aria-valuetext={v == null ? "not known yet" : `${Math.round(v)}%, ${WORDS[label][l!].toLowerCase()}`}>
        <i style={{ width: `${v ?? 0}%` }} />
      </div>
    </div>
  );
}

export default function Vitals({ device: d }: { device: Device }) {
  return (
    <div className="meters">
      <Meter label="Disk" value={d.vitals?.diskPct} />
      <Meter label="Memory" value={d.vitals?.mem} />
      <Meter label="CPU" value={d.vitals?.cpu} />
    </div>
  );
}
