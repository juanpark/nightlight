"use client";
// Live, read-only Firestore listeners for the signed-in user's own data (rules allow nothing else).
import { useEffect, useState } from "react";
import { collection, doc, onSnapshot, Timestamp, type DocumentData } from "firebase/firestore";
import { firebase } from "./firebase";
import type { Action, Device, EventDoc, Service, TrustDoc, UserDoc } from "./types";

/** Firestore Timestamps → Date, recursively, so the UI sees one shape (docs/API.md "Times"). */
function plain<T>(id: string, data: DocumentData): T {
  const conv = (v: unknown): unknown =>
    v instanceof Timestamp ? v.toDate()
      : Array.isArray(v) ? v.map(conv)
      : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, conv(x)]))
      : v;
  return { id, ...(conv(data) as object) } as T;
}

function useCollection<T>(uid: string | null, path: string[]): T[] {
  const [rows, setRows] = useState<T[]>([]);
  const key = path.join("/");
  useEffect(() => {
    if (!uid) return;
    let stop = () => {};
    firebase().then(({ db }) => {
      stop = onSnapshot(collection(db, "users", uid, ...(path as [string])), (snap) =>
        setRows(snap.docs.map((d) => plain<T>(d.id, d.data()))));
    });
    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid, key]);
  return rows;
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
  return useCollection<Device>(uid, ["devices"]).filter(current(gen));
}

export function useServices(uid: string | null, deviceId: string | null): Service[] {
  return useCollection<Service>(uid && deviceId ? uid : null, ["devices", deviceId ?? "_", "services"]);
}

export function useActions(uid: string | null, gen: number | undefined): Action[] {
  return useCollection<Action>(uid, ["actions"]).filter(current(gen));
}

export function useEvents(uid: string | null, gen: number | undefined): EventDoc[] {
  return useCollection<EventDoc>(uid, ["events"]).filter((e) => e.demoGeneration === gen)
    .sort((a, b) => (b.at?.getTime() ?? 0) - (a.at?.getTime() ?? 0));
}

export function useTrust(uid: string | null, gen: number | undefined): TrustDoc[] {
  return useCollection<TrustDoc>(uid, ["trust"]).filter((t) => t.demoGeneration === gen);
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
