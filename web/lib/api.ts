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
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

export async function api<T = Record<string, unknown>>(method: string, path: string, body?: unknown): Promise<T> {
  const { config } = await firebase();
  const r = await fetch(config.apiUrl + path, { method, headers: await headers(), body: JSON.stringify(body ?? {}) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, data.code ?? "error", data);
  return data as T;
}

/** POST that answers with Server-Sent Events. Calls onEvent for each event; resolves when the stream ends. */
export async function stream(path: string, body: unknown, onEvent: (e: StreamEvent) => void): Promise<void> {
  const { config } = await firebase();
  const r = await fetch(config.apiUrl + path, { method: "POST", headers: await headers(), body: JSON.stringify(body) });
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
