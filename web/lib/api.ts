"use client";
// Every write goes through our API with the Firebase ID token. Chat replies are SSE over POST (read with fetch).
import { firebase } from "./firebase";
import type { StreamEvent } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, public body: Record<string, unknown>) {
    super(code);
  }
}

async function headers() {
  const { auth } = await firebase();
  const token = await auth.currentUser?.getIdToken();
  // the browser's time zone, so the assistant can speak in local time (the server keeps it once, unless the owner
  // chose one in Settings)
  let tz = "";
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone ?? ""; } catch { /* old browser: the server keeps UTC */ }
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(tz ? { "X-Time-Zone": tz } : {}) };
}

export async function api<T = Record<string, unknown>>(method: string, path: string, body?: unknown): Promise<T> {
  const { config } = await firebase();
  const r = await fetch(config.apiUrl + path, {
    method, headers: await headers(), body: method === "GET" ? undefined : JSON.stringify(body ?? {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, data.code ?? "error", data);
  return data as T;
}

/** POST that answers with Server-Sent Events. Calls onEvent for each event; resolves when the stream ends. Aborting
 * the signal closes the stream, which stops the turn on the server (what it already did is kept). */
export async function stream(path: string, body: unknown, onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal): Promise<void> {
  const { config } = await firebase();
  const r = await fetch(config.apiUrl + path,
    { method: "POST", headers: await headers(), body: JSON.stringify(body), signal });
  if (!r.ok || !r.body) {
    const data = await r.json().catch(() => ({}));
    throw new ApiError(r.status, data.code ?? "error", data);
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      for (const line of block.split("\n")) {
        if (line.startsWith("data:")) onEvent(JSON.parse(line.slice(5)) as StreamEvent);
      }
    }
  }
}
