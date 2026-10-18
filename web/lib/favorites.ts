"use client";
// Stars: a device the owner cares about, and the apps on it they care about. A tap shows at once; the device's doc
// catches up through its listener, and a save that fails puts the star back and says so.
import { useEffect, useState } from "react";
import { api } from "./api";
import type { Device } from "./types";

export const MAX_FAVORITE_APPS = 20; // the server keeps at most this many per device

// What was tapped here and not yet seen in the doc, per device and per kind of star; n is the tap that set it.
type Draft = { id: string; favorite?: { v: boolean; n: number }; apps?: { v: string[]; n: number } };

// the server de-duplicates and may keep its own order, so the doc agrees when it holds the same set
const same = (a: string[], b: string[]) => new Set(a).size === new Set(b).size && a.every((x) => b.includes(x));
const empty = (x: Draft) => !x.favorite && !x.apps;

// Saves of one kind of star on one device go one at a time, newest last: a tap while one is on its way waits and
// replaces any tap still waiting, so the server always ends on the latest choice. Kept for the page's life (by user,
// device and kind), so closing and reopening the panel mid-save joins the same line.
const busy: Record<string, boolean> = {};
// each waiting tap carries how to undo itself in the panel that made it (which may not be the one sending it)
type Job = { v: boolean | string[]; n: number; undo: () => void };
const waiting: Record<string, Job> = {};
let tap = 0;

/** The device's stars as the owner last set them here, and the toggles. Drafts belong to one device and are dropped
 * once its doc agrees; saves go in order, and a failed one undoes only itself when no later tap of its kind came. */
export function useFavorites(uid: string, d: Device) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [err, setErr] = useState("");
  const mine = draft?.id === d.id ? draft : null;
  useEffect(() => setDraft((x) => {
    if (!x || x.id !== d.id) return null;
    const y = { ...x };
    if (y.favorite && y.favorite.v === !!d.favorite) delete y.favorite;
    if (y.apps && same(y.apps.v, d.favoriteApps ?? [])) delete y.apps;
    return empty(y) ? null : y;
  }), [d.id, d.favorite, d.favoriteApps]);
  useEffect(() => setErr(""), [d.id]);
  const favorite = mine?.favorite?.v ?? !!d.favorite;
  const apps = mine?.apps?.v ?? d.favoriteApps ?? [];

  async function save(key: "favorite" | "apps", v: boolean | string[]) {
    const n = ++tap, id = d.id, k = `${uid}:${id}:${key}`;
    setErr("");
    setDraft((x) => ({ ...(x?.id === id ? x : {}), id, [key]: { v, n } }));
    const undo = () => { // this tap failed and nothing newer of its kind came: put the star back and say so
      setDraft((x) => {
        if (x?.id !== id || x[key]?.n !== n) return x;
        const y = { ...x };
        delete y[key];
        return empty(y) ? null : y;
      });
      setErr("Couldn't save the star. Try again.");
    };
    if (busy[k]) { waiting[k] = { v, n, undo }; return; }
    busy[k] = true;
    let job: Job | undefined = { v, n, undo };
    while (job) {
      let failed = false;
      try {
        await api("POST", `/api/devices/${id}/layout`, key === "favorite" ? { favorite: job.v } : { favoriteApps: job.v });
      } catch { failed = true; }
      const next: Job | undefined = waiting[k];
      delete waiting[k];
      if (failed && !next) job.undo();
      job = next; // a newer choice supersedes this one, saved or not
    }
    busy[k] = false;
  }
  return {
    favorite, apps, err,
    isFavoriteApp: (svcId: string) => apps.includes(svcId),
    toggleDevice: () => save("favorite", !favorite),
    toggleApp: (svcId: string) => {
      const next = apps.includes(svcId) ? apps.filter((x) => x !== svcId) : [...apps, svcId];
      if (next.length > MAX_FAVORITE_APPS) { setErr(`You can star up to ${MAX_FAVORITE_APPS} apps on one device.`); return; }
      return save("apps", next);
    },
  };
}
