"use client";
import { useEffect, useRef, useState } from "react";
import { readLocal, writeLocal } from "@/lib/local";
import type { EventDoc } from "@/lib/types";

const AWAY_MS = 30 * 60 * 1000;

/** When the owner comes back after more than 30 minutes: how many real things happened meanwhile, with a button
 * that asks Nightlight for a short summary. The last visit is remembered in this browser. */
export default function AwayBanner({ uid, events, onSummarise }: {
  uid: string; events: EventDoc[]; onSummarise: (q: string) => void;
}) {
  const [away, setAway] = useState<{ since: number; until: number } | null>(null);
  const [dismissed, setDismissed] = useState(false);

  const computedFor = useRef<string | null>(null);

  useEffect(() => {
    const key = `nl_last_visit_${uid}`;
    if (computedFor.current !== uid) { // once per user, even when React runs effects twice in development
      computedFor.current = uid;
      const last = Number(readLocal(key)) || 0;
      const until = Date.now();
      setAway(last && until - last > AWAY_MS ? { since: last, until } : null);
      setDismissed(false);
      writeLocal(key, String(until));
    }
    const onHide = () => { if (document.visibilityState === "hidden") writeLocal(key, String(Date.now())); };
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
  }, [uid]);

  if (!away || dismissed) return null;
  const count = events.filter((e) => e.realm === "real" && e.at
    && e.at.getTime() > away.since && e.at.getTime() <= away.until).length;
  if (count === 0) return null;

  return (
    <div className="panel away" role="status">
      <span>{count === 1 ? "1 thing happened" : `${count} things happened`} while you were away.</span>
      <span className="spacer" />
      <button onClick={() => {
        onSummarise("What happened while I was away? Keep it short.");
        setDismissed(true);
      }}>Summarise</button>
      <button className="linkish small" onClick={() => setDismissed(true)} aria-label="Dismiss">Dismiss</button>
    </div>
  );
}
