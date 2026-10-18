// A status said three ways at once: an icon, a word and its colour, never the colour alone. The same words appear on
// the map, the list, the device panel and the "needs you" strip: ✓ Fine · ! Needs a look · ✗ Broken · Offline.
import { ago, type Need } from "@/lib/needsYou";
import type { Device } from "@/lib/types";
import { StatusBroken, StatusFine, StatusLater, StatusLook, StatusOffline } from "@/src/components/icons";

export type Tone = "ok" | "warn" | "crit" | "offline" | "later";

const ICON = { ok: StatusFine, warn: StatusLook, crit: StatusBroken, offline: StatusOffline, later: StatusLater };
export const WORD: Record<Tone, string> = { ok: "Fine", warn: "Needs a look", crit: "Broken", offline: "Offline",
  later: "When you can" };

export default function StatusWord({ tone, word, className }: { tone: Tone; word?: string; className?: string }) {
  const Icon = ICON[tone];
  return <span className={`status-word ${tone} ${className ?? ""}`}><Icon size={15} aria-hidden />{word ?? WORD[tone]}</span>;
}

/** Just the mark, for a line whose own words already say what happened; the word is still read aloud. */
export function StatusIcon({ tone, word }: { tone: Tone; word?: string }) {
  const Icon = ICON[tone];
  return <span className={`status-word status-icon ${tone}`}><Icon size={15} aria-hidden />
    <span className="sr-only">{word ?? WORD[tone]}</span></span>;
}

/** How a "needs you" item is labelled: what is wrong for a problem, what is asked for anything else. */
export function needTone(n: Need): { tone: Tone; word: string } {
  if (n.kind === "critical") return { tone: "crit", word: "Broken" };
  if (n.kind === "silent") return { tone: "offline", word: "Offline" };
  if (n.kind === "approve") return { tone: n.priority === 1 ? "crit" : "warn", word: "Needs your OK" };
  if (n.priority === 1) return { tone: "crit", word: "Urgent" };
  if (n.priority === 2) return { tone: "warn", word: "Needs a look" };
  return { tone: "later", word: "When you can" };
}

/** A device's status as a tone: a real device that stopped reporting is Offline whatever it said last. */
export function deviceTone(d: Device): Tone {
  return d.status === "ok" || d.status === "warn" || d.status === "crit" ? d.status : "offline";
}

/** One plain line under a device's name: its top open problem, or that all is well. */
export function deviceLine(d: Device, now: number): string {
  if (d.starting) return "Starting…";
  if (d.status === "offline") return d.lastSeen ? `Silent for ${ago(now - d.lastSeen.getTime())}` : "Not reporting yet";
  const open = (d.findings ?? []).filter((f) => (f.state ?? "new") === "new");
  const top = open.find((f) => f.severity === "crit") ?? open.find((f) => f.severity === "warn") ?? open[0];
  return top?.message ?? "All good";
}
