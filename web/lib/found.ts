"use client";
// What your devices found nearby, merged across them by the server (GET /api/found): one list for the Found nearby
// panel and the "N things found nearby" count, so both agree.
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Discovery, FoundThing } from "./types";

export interface Found { items: FoundThing[] | null; refresh: () => void }

/** Refetched on every discovery snapshot (a new scan, or something added from another tab), when a list expires
 * (lists last 24 h; `now` is the page's clock), and on refresh(). */
export function useFound(discoveries: Discovery[], now: number): Found {
  const [items, setItems] = useState<FoundThing[] | null>(null);
  const [tick, setTick] = useState(0);
  const current = discoveries.filter((d) => (d.expiresAt?.getTime() ?? Infinity) > now).map((d) => d.id).join();
  useEffect(() => {
    if (!current) { setItems([]); return; } // nothing current reported: nothing to ask the server
    let live = true;
    api<{ items: FoundThing[] }>("GET", "/api/found").then((r) => { if (live) setItems(r.items); })
      .catch(() => { if (live) setItems((cur) => cur ?? []); });
    return () => { live = false; };
  }, [discoveries, current, tick]);
  return { items, refresh: useCallback(() => setTick((n) => n + 1), []) };
}

/** Found things that can go on the map (a helper that saw it can check it). */
export const addable = (items: FoundThing[] | null) => (items ?? []).filter((t) => t.seenBy[0]?.canWatch !== false);
