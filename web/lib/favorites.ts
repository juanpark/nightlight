"use client";
// Stars: a device the owner cares about, and the apps on it they care about. A tap shows at once; the device's doc
// catches up through its listener, and a save that fails puts the star back and says so.
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Device } from "./types";

export const MAX_FAVORITE_APPS = 20; // the server keeps at most this many per device

// What was tapped here and not yet seen in the doc, per device and per kind of star; n is the tap that set it.
type Draft = { id: string; favorite?: { v: boolean; n: number }; apps?: { v: string[]; n: number } };

// the server de-duplicates and may keep its own order, so the doc agrees when it holds the same set
const same = (a: string[], b: string[]) => new Set(a).size === new Set(b).size && a.every((x) => b.includes(x));
const empty = (x: Draft) => !x.favorite && !x.apps;

/** The device's stars as the owner last set them here, and the toggles. Drafts belong to one device and are dropped
 * once its doc agrees; a failed save undoes only itself, and only when no later tap of the same kind came after it. */
export function useFavorites(d: Device) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [err, setErr] = useState("");
  const seq = useRef(0);
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
    const n = ++seq.current, id = d.id;
    setErr("");
    setDraft((x) => ({ ...(x?.id === id ? x : {}), id, [key]: { v, n } }));
    try {
      await api("POST", `/api/devices/${id}/layout`, key === "favorite" ? { favorite: v } : { favoriteApps: v });
    } catch {
      setDraft((x) => {
        if (x?.id !== id || x[key]?.n !== n) return x;
        const y = { ...x };
        delete y[key];
        return empty(y) ? null : y;
      });
      setErr("Couldn't save the star. Try again.");
    }
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
