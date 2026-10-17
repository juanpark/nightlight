// The apps on a device (containers and system services alike), in the order the person wants to see them: what
// needs a look first, then what they starred, then the rest by name.
import type { Service } from "./types";

export const needsLook = (s: Service) => (s.status ?? "ok") !== "ok";

export function appOrder(services: Service[], favorites: string[]): Service[] {
  return [...services].sort((a, b) => Number(needsLook(b)) - Number(needsLook(a))
    || Number(favorites.includes(b.id)) - Number(favorites.includes(a.id)) || a.name.localeCompare(b.name));
}

export const APP_CAP = 12; // an opened card shows this many; the rest are a tap away
