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
  ok: boolean; // ...and finished well (not stopped, failed or reset)
  said: string; // the answer's words (lower case, capped): names an app on a device a step touched when no step did
  last: string | null; lastWithApp: string | null; // the device the latest step touched, and that named an app
  steps: Record<string, DeviceSteps>; // device id → how the steps on it are going
  open: { callId?: string; name: string; device: string }[]; // steps started and not answered yet
  show: { id: string; n: number } | null; // "show me this device on the map" (the chat's context strip)
};
export type DeviceSteps = { running: number; found: boolean; note?: string };
export type StepState = "checking" | "found" | "done";

const EMPTY = { devices: [], apps: {}, said: "", last: null, lastWithApp: null, steps: {}, open: [] };
let state: Followed = { seq: 0, done: true, ok: false, show: null, ...EMPTY };
const SAID_MAX = 4000;
const listeners = new Set<() => void>();
const set = (next: Followed) => { state = next; listeners.forEach((l) => l()); };

/** A new answer has started: forget what the last one touched. Returns the answer's number: an older answer still
 * streaming (a follow-up started while it finished) no longer moves the map. */
export function followBegin(): number { set({ ...state, seq: state.seq + 1, done: false, ok: false, ...EMPTY }); return state.seq; }

/** The chat that owns the answers went away or changed home (sign-out, another sample): its answers still streaming
 * no longer count, and nothing they lit stays lit. */
export function followReset() { set({ seq: state.seq + 1, done: true, ok: false, show: null, ...EMPTY }); }

/** A step started: the device it works on, and the app it names, if any. */
export function followStep(seq: number, args: Record<string, unknown> | undefined, name = "", callId?: string) {
  const id = typeof args?.device_id === "string" ? args.device_id : "";
  if (!id || state.done || seq !== state.seq) return;
  const named = [args?.container, args?.service, args?.target].find((v) => typeof v === "string" && v.trim()) as string | undefined;
  const app = named?.trim().toLowerCase();
  const had = state.apps[id] ?? [];
  // the latest step decides which card opens at the end, even when it revisits a device it already lit
  set({ ...state, devices: state.devices.includes(id) ? state.devices : [...state.devices, id],
    apps: app && !had.includes(app) ? { ...state.apps, [id]: [...had, app] } : state.apps,
    last: id, lastWithApp: app ? id : state.lastWithApp,
    steps: { ...state.steps, [id]: { ...(state.steps[id] ?? { found: false }), running: (state.steps[id]?.running ?? 0) + 1 } },
    open: [...state.open, { callId, name, device: id }] });
}

/** A step answered: by its call id, else the oldest open step with its name. A failed step counts as found. */
export function followResult(seq: number, name: string, callId: string | undefined, ok: boolean, summary?: string) {
  if (state.done || seq !== state.seq) return;
  const i = state.open.findIndex((o) => callId && o.callId ? o.callId === callId : o.name === name);
  if (i < 0) return;
  const id = state.open[i].device, had = state.steps[id];
  set({ ...state, open: state.open.filter((_, j) => j !== i),
    steps: { ...state.steps, [id]: { running: Math.max(0, (had?.running ?? 1) - 1), found: (had?.found ?? false) || !ok,
      note: summary?.trim() || had?.note } } });
}

/** The answer put up a card: it found something to fix on the device the latest step touched. */
export function followCard(seq: number) {
  const id = state.last;
  if (!id || state.done || seq !== state.seq) return;
  set({ ...state, steps: { ...state.steps, [id]: { ...(state.steps[id] ?? { running: 0 }), found: true, note: "asks you first" } } });
}

/** How the steps on a device are going: checking while one runs, found when one failed or put up a card, else done. */
export function stepState(f: Followed, id: string): StepState | undefined {
  const s = f.steps[id];
  if (!s) return undefined;
  return s.running > 0 && !f.done ? "checking" : s.found ? "found" : "done";
}

/** The context strip asks the map to show a device (the map view switches to it and centers it). */
export function followShow(id: string) { set({ ...state, show: { id, n: (state.show?.n ?? 0) + 1 } }); }

/** Words of the answer as they stream in (kept quietly: the map only reads them once the answer is done). */
export function followText(seq: number, delta: string) {
  if (seq === state.seq && !state.done && state.said.length < SAID_MAX) state = { ...state, said: (state.said + delta.toLowerCase()).slice(0, SAID_MAX) };
}

/** The answer is over (finished, stopped or failed). */
export function followEnd(seq: number, ok = false) { if (!state.done && seq === state.seq) set({ ...state, done: true, ok }); }

const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
const snapshot = () => state;
export function useFollowed(): Followed {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/** Whether an answer is working on this device right now (its steps touched it and the answer hasn't finished):
 *  the list and the "needs you" strip show it the same way the map does. */
export function useWorkingOn(): (deviceId?: string) => boolean {
  const f = useFollowed();
  return (id) => !!id && !f.done && f.devices.includes(id);
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

/** The device to open at the end: the one the latest app-naming step touched, else the one the latest step touched. */
export function mainDevice(f: Followed): string | null {
  return f.lastWithApp ?? f.last;
}
