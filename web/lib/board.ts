// The status board: every check Nightlight can make from what devices last reported, without asking the model. Only
// what is actually stored is shown; a value nobody has reported is never shown as fine. Counting (one check each):
// a "reporting" line per real device (or per device gone quiet), each vital present (uptime, disk, memory, CPU),
// each app or service, each problem not about an app or a vital, each watched thing and each watched website. A
// problem the owner marked known or snoozed counts as ok, "(known)"; an "info" problem counts as ok with its note.
import type { Device, Finding, Service, Watch } from "./types";

export type Mark = "ok" | "warn" | "crit" | "unknown";
export type Line = { mark: Mark; label: string; value: string; app?: boolean }; // app: one of the device's apps
export type Block = { id: string; name: string; at: Date | null; lines: Line[]; pending?: boolean };
export type Counts = Record<Mark, number> & { total: number };

export const GLYPH: Record<Mark, string> = { ok: "✓", warn: "!", crit: "✗", unknown: "?" };

const VITAL_CHECKS = (f: Finding) => f.check.startsWith("disk_over") || f.check === "memory_high" || f.check === "restart_overdue";

function ago(at: Date | null | undefined, now: number): string {
  if (!at) return "never";
  const m = Math.round((now - at.getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 48 * 60 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`;
}

export function uptimeWords(sec: number): string {
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${Math.max(1, m)}m`;
}

/** A problem's mark: its severity, unless the owner said they know about it. */
function findingMark(f: Finding): { mark: Mark; known: boolean } {
  if (f.state === "known" || f.state === "snoozed") return { mark: "ok", known: true };
  return { mark: f.severity === "crit" ? "crit" : f.severity === "warn" ? "warn" : "ok", known: false };
}

function vital(label: string, value: string, f: Finding | undefined, stale: boolean): Line {
  if (stale) return { mark: "unknown", label, value: `last known ${value}` };
  if (!f) return { mark: "ok", label, value };
  const { mark, known } = findingMark(f);
  return { mark, label, value: `${value}${known ? " (known)" : f.severity === "info" ? ` · ${f.message}` : ""}` };
}

const SVC: Record<string, Mark> = { ok: "ok", warn: "warn", crit: "crit", offline: "crit" };

/** One device's lines. `services` is null while its apps are still loading (they are left out until then). */
export function deviceBlock(d: Device, services: Service[] | null, now: number): Block {
  const lines: Line[] = [];
  const at = d.kind === "watched" ? d.lastAnswerAt ?? d.lastSeen ?? null : d.lastSeen ?? null;
  if (d.kind === "watched") {
    // a watched thing is only checked for answering: nothing else about it is known
    lines.push(d.status === "ok"
      ? { mark: "ok", label: "Answers", value: d.vitals?.latencyMs != null ? `in ${d.vitals.latencyMs} ms` : "yes" }
      : d.status === "offline" && !d.lastSeen ? { mark: "unknown", label: "Answers", value: "not checked yet" }
        : { mark: "crit", label: "Answers", value: `no · last answered ${ago(d.lastAnswerAt, now)}` });
    return { id: d.id, name: d.name, at, lines };
  }
  const stale = d.status === "offline";
  if (stale) lines.push({ mark: "crit", label: "Reporting", value: `no report for ${ago(d.lastSeen, now).replace(" ago", "")}` });
  else if (d.realm === "real") lines.push({ mark: "ok", label: "Reporting", value: `last report ${ago(d.lastSeen, now)}` });
  const fs = d.findings ?? [];
  const v = d.vitals ?? {};
  if (v.uptime != null) lines.push(vital("Running for", uptimeWords(v.uptime), fs.find((f) => f.check === "restart_overdue"), stale));
  if (v.diskPct != null) lines.push(vital("Disk", `${Math.round(v.diskPct)}% used`, fs.find((f) => f.check.startsWith("disk_over")), stale));
  if (v.mem != null) lines.push(vital("Memory", `${Math.round(v.mem)}% used`, fs.find((f) => f.check === "memory_high"), stale));
  if (v.cpu != null) lines.push(vital("CPU", `${Math.round(v.cpu)}% busy`, undefined, stale));
  for (const s of services ?? []) {
    const mark: Mark = stale ? "unknown" : s.status ? SVC[s.status] ?? "unknown" : "unknown";
    const word = ({ ok: "running", warn: "needs a look", crit: "failed", offline: "stopped" } as Record<string, string>)[s.status ?? ""];
    lines.push({ mark, label: s.name, value: stale ? "last known" : s.detail || word || "not reported", app: true });
  }
  for (const f of fs) {
    if (f.svcId && (services ?? []).some((s) => s.id === f.svcId)) continue; // said on the app's own line
    if (VITAL_CHECKS(f)) continue; // said on the vital's line
    if (stale) { lines.push({ mark: "unknown", label: "Problem", value: `last known: ${f.message}` }); continue; }
    const { mark, known } = findingMark(f);
    lines.push({ mark, label: f.severity === "info" ? "Note" : "Problem", value: `${f.message}${known ? " (known)" : ""}` });
  }
  return { id: d.id, name: d.name, at, lines, pending: services === null };
}

/** Watched websites, as one block. */
export function websiteBlock(watches: Watch[], now: number): Block | null {
  if (!watches.length) return null;
  const lines: Line[] = watches.map((w) => w.status === "ok"
    ? { mark: "ok", label: w.name, value: `answers${w.latencyMs != null ? ` in ${w.latencyMs} ms` : ""}` }
    : w.status === "crit" ? { mark: "crit", label: w.name, value: `down${w.httpStatus ? ` (${w.httpStatus})` : ""} · checked ${ago(w.lastCheckedAt, now)}` }
      : { mark: "unknown", label: w.name, value: "not checked yet" });
  const at = watches.reduce<Date | null>((m, w) => w.lastCheckedAt && (!m || w.lastCheckedAt > m) ? w.lastCheckedAt : m, null);
  return { id: "_websites", name: "Websites", at, lines };
}

export function count(blocks: Block[]): Counts {
  const c: Counts = { ok: 0, warn: 0, crit: 0, unknown: 0, total: 0 };
  for (const b of blocks) for (const l of b.lines) { c[l.mark]++; c.total++; }
  return c;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "23 checks — 17 ok, 5 warnings, 1 critical" (and unknowns when there are any). */
export function summary(c: Counts): string {
  const parts = [`${c.ok} ok`, plural(c.warn, "warning", "warnings"), `${c.crit} critical`];
  if (c.unknown) parts.push(`${c.unknown} unknown`);
  return `${plural(c.total, "check", "checks")} — ${parts.join(", ")}`;
}

/** The whole board as plain text, for copying. */
export function boardText(blocks: Block[], c: Counts, stamp: (d: Date) => string): string {
  const out: string[] = [];
  for (const b of blocks) {
    out.push(`${b.name}${b.at ? `  ${stamp(b.at)}` : ""}`);
    for (const l of b.lines) out.push(`  ${GLYPH[l.mark]} ${l.label}  ${l.value}`.trimEnd());
    out.push("");
  }
  out.push(`Summary: ${summary(c)}`);
  return out.join("\n");
}
