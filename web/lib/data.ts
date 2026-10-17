"use client";
// Live, read-only Firestore listeners for the signed-in user's own data (rules allow nothing else).
import { useEffect, useState } from "react";
import { collection, doc, limit, onSnapshot, orderBy, query, Timestamp, where, type DocumentData } from "firebase/firestore";
import { firebase } from "./firebase";
import type { Action, Device, Discovery, EventDoc, HistoryPoint, Note, PlaceDoc, Runbook, Service, TrustDoc, UserDoc, Watch, Link } from "./types";

/** Firestore Timestamps → Date, recursively, so the UI sees one shape (docs/API.md "Times"). */
function plain<T>(id: string, data: DocumentData): T {
  const conv = (v: unknown): unknown =>
    v instanceof Timestamp ? v.toDate()
      : Array.isArray(v) ? v.map(conv)
      : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, conv(x)]))
      : v;
  return { id, ...(conv(data) as object) } as T;
}

/** A collection's rows, and whether they have arrived for this path yet (rows for another path never show here). */
function useCollectionState<T>(uid: string | null, path: string[]): { rows: T[]; loaded: boolean } {
  const [got, setGot] = useState<{ key: string; rows: T[] } | null>(null);
  const key = path.join("/");
  useEffect(() => {
    if (!uid) return;
    let stop = () => {};
    firebase().then(({ db }) => {
      stop = onSnapshot(collection(db, "users", uid, ...(path as [string])), (snap) =>
        setGot({ key, rows: snap.docs.map((d) => plain<T>(d.id, d.data())) }));
    });
    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid, key]);
  return got?.key === key ? { rows: got.rows, loaded: true } : { rows: EMPTY as T[], loaded: false };
}
const EMPTY: never[] = [];

function useCollection<T>(uid: string | null, path: string[]): T[] {
  return useCollectionState<T>(uid, path).rows;
}

export function useUserDoc(uid: string | null): UserDoc | null | undefined {
  const [u, setU] = useState<UserDoc | null | undefined>(undefined);
  useEffect(() => {
    if (!uid) return;
    let stop = () => {};
    firebase().then(({ db }) => {
      stop = onSnapshot(doc(db, "users", uid), (s) => setU(s.exists() ? plain<UserDoc>(s.id, s.data()) : null));
    });
    return () => stop();
  }, [uid]);
  return u;
}

const current = (gen: number | undefined) => (d: { realm?: string; demoGeneration?: number }) =>
  d.realm === "real" || d.demoGeneration === gen;

export function useDevices(uid: string | null, gen: number | undefined): Device[] {
  // the server archives a watched thing you stop watching; ones stopped before it did are only revoked
  return useCollection<Device>(uid, ["devices"]).filter((d) => !d.archived && !(d.kind === "watched" && d.revoked))
    .filter(current(gen));
}

/** Names the person gave their places (one per router; unnamed ones are "Place 1", "Place 2"…). */
export function usePlaces(uid: string | null): PlaceDoc[] {
  return useCollection<PlaceDoc>(uid, ["places"]);
}

/** Lines between devices on the map (the sample home's go away with it). */
export function useLinks(uid: string | null, gen: number | undefined): Link[] {
  return useCollection<Link>(uid, ["links"]).filter(current(gen));
}

export function useServices(uid: string | null, deviceId: string | null): Service[] {
  return useCollection<Service>(uid && deviceId ? uid : null, ["devices", deviceId ?? "_", "services"]);
}
export function useServicesState(uid: string | null, deviceId: string | null) {
  return useCollectionState<Service>(uid && deviceId ? uid : null, ["devices", deviceId ?? "_", "services"]);
}

/** A stored step: older messages have only name and args; textOffset/ok/ms arrived with the layered chat. */
export interface PastStep { name: string; args?: Record<string, unknown>; summary?: string; details?: string;
  textOffset?: number; ok?: boolean; ms?: number; unfinished?: boolean; actionId?: string }
export interface PastMessage { id: string; role: "user" | "assistant"; text: string; seq: number;
  mode?: "quick" | "investigate"; toolCalls?: PastStep[]; actionIds?: string[]; error?: { code: string; message: string } }

/** A chat's saved messages, oldest first (read once when the chat opens). */
export async function loadMessages(uid: string, sessionId: string): Promise<PastMessage[]> {
  const { db } = await firebase();
  const { getDocs } = await import("firebase/firestore");
  const snap = await getDocs(query(collection(db, "users", uid, "sessions", sessionId, "messages"), orderBy("seq"),
    limit(200)));
  return snap.docs.map((d) => plain<PastMessage>(d.id, d.data()));
}

/** The signed helper release on offer (fetched once for the whole app). */
export function useRelease(): { version: string } | null {
  const [r, setR] = useState<{ version: string } | null>(null);
  useEffect(() => {
    import("./api").then(({ api }) => api<{ version: string }>("GET", "/helper/release").then(setR).catch(() => setR(null)));
  }, []);
  return r;
}

/** Whether the owner has a passkey for expert sessions (refreshed when `tick` changes). */
export function useExpertStatus(tick = 0): { enabled: boolean } | null {
  const [r, setR] = useState<{ enabled: boolean } | null>(null);
  useEffect(() => {
    import("./api").then(({ api }) => api<{ enabled: boolean }>("GET", "/api/expert").then(setR).catch(() => setR(null)));
  }, [tick]);
  return r;
}

/** A device's profile (the notes Nightlight keeps about the machine), or undefined. */
export function useProfile(uid: string | null, deviceId: string | null) {
  return useCollection<{ id: string; text: string; by: string; updatedAt: Date | null }>(
    uid && deviceId ? uid : null, ["devices", deviceId ?? "_", "profile"]).find((p) => p.id === "main");
}

/** A device's saved fixes, most used first (a sample device's only from the current sample home). */
export function useRunbooks(uid: string | null, deviceId: string | null, gen: number | undefined): Runbook[] {
  return useCollection<Runbook>(uid && deviceId ? uid : null, ["devices", deviceId ?? "_", "runbooks"])
    .filter((r) => r.demoGeneration == null || r.demoGeneration === gen)
    .sort((a, b) => (b.uses ?? 0) - (a.uses ?? 0));
}

/** A device's notebook, newest first. */
export function useNotes(uid: string | null, deviceId: string | null): Note[] {
  return useCollection<Note>(uid && deviceId ? uid : null, ["devices", deviceId ?? "_", "notes"])
    .sort((a, b) => (b.at?.getTime() ?? 0) - (a.at?.getTime() ?? 0));
}

export function useActions(uid: string | null, gen: number | undefined): Action[] {
  return useCollection<Action>(uid, ["actions"]).filter(current(gen));
}

export function useEvents(uid: string | null, gen: number | undefined): EventDoc[] {
  return useCollection<EventDoc>(uid, ["events"]).filter((e) => e.realm === "real" || e.demoGeneration === gen)
    .sort((a, b) => (b.at?.getTime() ?? 0) - (a.at?.getTime() ?? 0));
}

export function useTrust(uid: string | null, gen: number | undefined): TrustDoc[] {
  return useCollection<TrustDoc>(uid, ["trust"]).filter((t) => t.demoGeneration === gen);
}

/** The last 7 days of a real device's history, oldest first (at most one point per 5 minutes, ~2016 a week).
 * Pass a null deviceId for sample devices: they have no history. */
export function useHistory(uid: string | null, deviceId: string | null): HistoryPoint[] {
  const [rows, setRows] = useState<HistoryPoint[]>([]);
  useEffect(() => {
    setRows([]);
    if (!uid || !deviceId) return;
    let stop = () => {};
    let cancelled = false;
    firebase().then(({ db }) => {
      if (cancelled) return;
      const since = Timestamp.fromMillis(Date.now() - 7 * 86400000);
      const q = query(collection(db, "users", uid, "devices", deviceId, "history"),
        where("at", ">=", since), orderBy("at"), limit(2100));
      stop = onSnapshot(q, (snap) => setRows(snap.docs.map((d) => plain<HistoryPoint>(d.id, d.data()))),
        (err) => console.warn("history listener", err));
    });
    return () => { cancelled = true; stop(); };
  }, [uid, deviceId]);
  return rows;
}

/** Web addresses the owner asked Nightlight to keep an eye on, sorted by name. */
export function useWatches(uid: string | null): Watch[] {
  return useCollection<Watch>(uid, ["watches"]).sort((a, b) => (a.name ?? "").localeCompare(b.name ?? ""));
}

/** A real device that hasn't reported for 5 minutes is offline with unknown health (docs/API.md). Re-checked
 * every 15 s so the board changes even when no new data arrives. */
export function useNow(everyMs = 15000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(t);
  }, [everyMs]);
  return now;
}

export function presented(d: Device, now: number): Device {
  if (d.realm !== "real") return d;
  const silent = !d.lastSeen || now - d.lastSeen.getTime() > 5 * 60 * 1000;
  return d.revoked || silent ? { ...d, status: "offline", health: "unknown", findings: [] } : d;
}

export function useDiscoveries(uid: string | null): Discovery[] {
  return useCollection<Discovery>(uid, ["discoveries"]);
}
