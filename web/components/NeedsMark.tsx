"use client";
// The small count on a device tile: how many things on this device need the person, coloured by the most urgent.
import type { Need } from "@/lib/needsYou";

const TONE = { 1: "crit", 2: "warn", 3: "offline" } as const;

export default function NeedsMark({ needs }: { needs?: Need[] }) {
  if (!needs?.length) return null;
  const top = Math.min(...needs.map((n) => n.priority)) as 1 | 2 | 3;
  return (
    <span className={`needs-mark ${TONE[top]}`} title={needs.map((n) => n.title).join(" · ")}
      aria-label={`${needs.length} ${needs.length === 1 ? "thing needs" : "things need"} you`}>{needs.length}</span>
  );
}
