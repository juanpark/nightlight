"use client";
// The map follows the chat: what the assistant's steps touched in the answer being given (devices, and apps on them by
// name), so the map can light them up while it works and open the main one when it is done. Only what a step actually
// touched counts; nothing is guessed from the words.
import { useSyncExternalStore } from "react";
import type { Service } from "./types";

export type Followed = {
  seq: number; // one per answer
  devices: string[]; // in the order the steps first touched them
  apps: Record<string, string[]>; // device id → app names the steps named (lower case)
  done: boolean; // the answer has finished
  said: string; // the answer's words (lower case, capped): names an app on a device a step touched when no step did
};

let state: Followed = { seq: 0, devices: [], apps: {}, done: true, said: "" };
const SAID_MAX = 4000;
const listeners = new Set<() => void>();
const set = (next: Followed) => { state = next; listeners.forEach((l) => l()); };

/** A new answer has started: forget what the last one touched. Returns the answer's number: an older answer still
 * streaming (a follow-up started while it finished) no longer moves the map. */
export function followBegin(): number { set({ seq: state.seq + 1, devices: [], apps: {}, done: false, said: "" }); return state.seq; }

/** A step started: the device it works on, and the app it names, if any. */
export function followStep(seq: number, args: Record<string, unknown> | undefined) {
  const id = typeof args?.device_id === "string" ? args.device_id : "";
  if (!id || state.done || seq !== state.seq) return;
  const named = [args?.container, args?.service, args?.target].find((v) => typeof v === "string" && v.trim()) as string | undefined;
  const app = named?.trim().toLowerCase();
  const had = state.apps[id] ?? [];
  if (state.devices.includes(id) && (!app || had.includes(app))) return;
  set({ ...state, devices: state.devices.includes(id) ? state.devices : [...state.devices, id],
    apps: app && !had.includes(app) ? { ...state.apps, [id]: [...had, app] } : state.apps });
}

/** Words of the answer as they stream in (kept quietly: the map only reads them once the answer is done). */
export function followText(seq: number, delta: string) {
  if (seq === state.seq && !state.done && state.said.length < SAID_MAX) state = { ...state, said: (state.said + delta.toLowerCase()).slice(0, SAID_MAX) };
}

/** The answer is over (finished, stopped or failed). */
export function followEnd(seq: number) { if (!state.done && seq === state.seq) set({ ...state, done: true }); }

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
const snapshot = () => state;
export function useFollowed(): Followed {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/** Whether a step named this app ("immich", "pihole-FTL.service", "the immich container"…). */
export function named(s: Service, names: string[] | undefined): boolean {
  if (!names?.length) return false;
  const keys = [s.name, s.unit, s.id].filter((k): k is string => !!k && k.length >= 3).map((k) => k.toLowerCase());
  // the whole name, or the name as a word in a longer phrase ("immich" in "the immich container", but not in "immich-db")
  const esc = (k: string) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return names.some((n) => keys.some((k) => n === k || new RegExp(`(^|[^a-z0-9_.-])${esc(k)}($|[^a-z0-9_.-])`).test(n)));
}

/** The apps on a device to light up: those a step named; failing that, once the answer is done, those its words name. */
export function litApps(f: Followed, id: string): string[] | undefined {
  if (!f.devices.includes(id)) return undefined;
  return f.apps[id]?.length ? f.apps[id] : f.done && f.said ? [f.said] : undefined;
}

/** The device to open at the end: the last one whose app a step named, else the last one touched. */
export function mainDevice(f: Followed): string | null {
  const withApp = f.devices.filter((d) => (f.apps[d]?.length ?? 0) > 0);
  return withApp.at(-1) ?? f.devices.at(-1) ?? null;
}
