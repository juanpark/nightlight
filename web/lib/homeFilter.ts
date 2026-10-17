// What the home view can be narrowed to: a place (devices behind one router), kinds of things, only what needs the
// person, favourites, tags. Pure functions; the bar (components/map/HomeBar.tsx) holds the choices.
import type { Need } from "./needsYou";
import type { Device, PlaceDoc, Watch } from "./types";

export type Category = "computers" | "routers" | "printers" | "storage" | "media" | "smarthome" | "other";
export const CATEGORIES: Record<Category, string> = {
  computers: "Computers", routers: "Routers", printers: "Printers", storage: "Storage", media: "Media",
  smarthome: "Smart home", other: "Other",
};
const BY_KIND: Record<string, Category> = {
  mac: "computers", pi: "computers", computer: "computers", router: "routers", nas: "storage", gameserver: "media",
  camera: "smarthome",
};
const BY_ROLE: Record<string, Category> = {
  computer: "computers", router: "routers", printer: "printers", fileshare: "storage", server: "media",
  speaker: "media", smarthome: "smarthome", other: "other",
};
export const categoryOf = (d: Device): Category =>
  (d.kind === "watched" ? BY_ROLE[d.role ?? "other"] : BY_KIND[d.kind ?? ""]) ?? "other";

export const SAMPLE = "sample", UNKNOWN = "unknown";
/** The place a device is in: its router's fingerprint (a watched thing: its watcher's), the sample home, or unknown. */
export function placeOf(d: Device, devices: Device[]): string {
  if (d.realm !== "real") return SAMPLE;
  const host = d.kind === "watched" ? devices.find((x) => x.id === d.watchedBy) : d;
  return host?.net?.gateway ?? UNKNOWN;
}

export type Place = { id: string; name: string; named: boolean; count: number };
/** The places on the map, biggest first, with the names the person gave them ("Place 1"… otherwise). */
export function placesOf(devices: Device[], names: PlaceDoc[]): Place[] {
  const counts = new Map<string, number>();
  for (const d of devices) counts.set(placeOf(d, devices), (counts.get(placeOf(d, devices)) ?? 0) + 1);
  let n = 0;
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([id, count]) => {
    const given = names.find((p) => p.id === id)?.name;
    const name = id === SAMPLE ? "Sample home" : id === UNKNOWN ? "Not sure where" : given ?? `Place ${++n}`;
    return { id, name, named: !!given, count };
  });
}

export type Filter = { place: string | null; kinds: Category[]; needsMe: boolean; favorites: boolean; tags: string[] };
export const NO_FILTER: Filter = { place: null, kinds: [], needsMe: false, favorites: false, tags: [] };
export const filtering = (f: Filter) => !!f.place || f.kinds.length > 0 || f.needsMe || f.favorites || f.tags.length > 0;
/** A starred device, or one holding a starred app. */
export const starred = (d: Device) => !!d.favorite || (d.favoriteApps?.length ?? 0) > 0;

const tagged = (tags: string[], d: { realm?: string; tags?: string[] }) => tags.length === 0
  || tags.some((t) => t === "Sample" ? d.realm !== "real" : (d.tags ?? []).includes(t));

/** Devices that pass every chosen filter (within one group, any choice matches). */
export function applyFilter(f: Filter, devices: Device[], marks?: Map<string, Need[]>): Device[] {
  return devices.filter((d) => (!f.place || placeOf(d, devices) === f.place)
    && (f.kinds.length === 0 || f.kinds.includes(categoryOf(d)))
    && (!f.needsMe || (marks?.get(d.id)?.length ?? 0) > 0 || d.status !== "ok")
    && (!f.favorites || starred(d))
    && tagged(f.tags, d));
}

/** Watched websites have no place, kind or star: tags and "only what needs me" apply, and none is a favourite. */
export const applyToWatches = (f: Filter, watches: Watch[]): Watch[] =>
  watches.filter((w) => tagged(f.tags, { realm: "real", tags: w.tags }) && (!f.needsMe || w.status === "crit")
    && !f.favorites);
