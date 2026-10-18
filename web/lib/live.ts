"use client";
// Live demo machines: a real VM in Google Cloud, one per visitor, leased through the API (docs: GET/POST
// /api/demo/live…). Starting one signs the visitor in to the machine's own account with a custom token; leaving (or the
// lease ending) signs them out again. This module keeps the little state the start screen and the session share.
import { useSyncExternalStore } from "react";
import { signInAnonymously, signInWithCustomToken, signOut } from "firebase/auth";
import { api, ApiError } from "./api";
import { firebase } from "./firebase";

export type Scenario = "none" | "crash" | "unhealthy" | "disk" | "leftovers";
export const SCENARIOS: { id: Scenario; label: string }[] = [
  { id: "none", label: "Everything fine" }, { id: "crash", label: "An app has crashed" },
  { id: "unhealthy", label: "An app is unhealthy" }, { id: "disk", label: "The disk is filling up" },
  { id: "leftovers", label: "Old leftovers take up space" },
];

export type LiveStatus = { enabled: boolean; total: number; inUse: number; free: number; running: number;
  etaSeconds?: number; restoreSeconds?: number; idleMinutes?: number; maxMinutes?: number };
export type LiveMe = { phase: "starting" | "reconnecting" | "stopping" | "restoring" | "ready"; machine?: string;
  vm?: string; helperSeenAt?: string | null; secondsSinceLease?: number; restoreSeconds?: number; etaSeconds?: number;
  scenario?: Scenario };
export type Problem = { code: string; total?: number; inUse?: number };

type State = { starting: boolean; problem: Problem | null; resumed: boolean; eta?: number; restore?: number; ended: boolean;
  machineReady: boolean; leaseStart?: number }; // machineReady: the machine is up and nothing covers Home
let state: State = { starting: false, problem: null, resumed: false, ended: false, machineReady: false };
const listeners = new Set<() => void>();
const set = (p: Partial<State>) => { state = { ...state, ...p }; listeners.forEach((l) => l()); };
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
export function useLive(): State { return useSyncExternalStore(subscribe, () => state, () => state); }
export function clearProblem() { set({ problem: null, ended: false }); }
export function resumedSeen() { set({ resumed: false }); }
/** What LiveSession learns from the machine's state, for Home (the tour waits; old reports read as starting). */
export function machineState(p: { machineReady: boolean; leaseStart?: number }) {
  if (p.machineReady !== state.machineReady || (p.leaseStart && p.leaseStart !== state.leaseStart)) set(p);
}

/** Lease a machine (the visitor's own again if they still hold one) and sign in to it. */
export async function startLive(scenario: Scenario) {
  set({ starting: true, problem: null, ended: false });
  const { auth } = await firebase();
  const made = !auth.currentUser;
  try {
    if (made) await signInAnonymously(auth); // the lease belongs to this visitor
    // 409 live_starting: this visitor's machine is still being set up; ask again when the API says to
    let r: { token: string; resumed?: boolean; etaSeconds?: number; restoreSeconds?: number };
    for (let tries = 0; ; tries++) {
      try { r = await api("POST", "/api/demo/live", { scenario }); break; } catch (e) {
        if (!(e instanceof ApiError && e.code === "live_starting") || tries >= 60) throw e;
        await new Promise((ok) => setTimeout(ok, Math.min(Math.max(Number(e.body.retryAfter) || 5, 1), 30) * 1000));
      }
    }
    await signInWithCustomToken(auth, r.token);
    set({ starting: false, resumed: !!r.resumed, eta: r.etaSeconds, restore: r.restoreSeconds });
  } catch (e) {
    // back to the start screen with the reason (an anonymous visitor made just for this goes away again)
    if (made && (auth.currentUser as { isAnonymous: boolean } | null)?.isAnonymous) await signOut(auth).catch(() => {});
    set({ starting: false, problem: e instanceof ApiError
      ? { code: e.code, total: Number(e.body.total) || undefined, inUse: Number(e.body.inUse) || undefined }
      : { code: "network" } });
  }
}

/** Leave the machine: release it now, then sign out (back to the start screen). */
export async function leaveLive(ended = false) {
  if (!ended) await api("POST", "/api/demo/live/end", {}).catch(() => {});
  set({ ended, resumed: false, machineReady: false, leaseStart: undefined });
  await signOut((await firebase()).auth).catch(() => {});
}

/** On a live demo machine, the account whose data this visit sees (each visit signs in as its own throwaway user, and
 * its token names the machine's account); null for any other sign-in. */
export async function liveAccount(user: { uid: string; getIdTokenResult: () => Promise<{ claims: Record<string, unknown> }> }) {
  try {
    const c = (await user.getIdTokenResult()).claims;
    return typeof c.nl_account === "string" ? c.nl_account : "nl_lease" in c ? user.uid : null;
  } catch { return null; }
}

export const minutes = (s?: number) => s == null ? "" : s < 90 ? `${Math.round(s)} seconds` : `${Math.round(s / 60)} minutes`;
