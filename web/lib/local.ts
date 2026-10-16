"use client";
// localStorage can be missing or throw (private windows, blocked site data): every access is guarded.

export function readLocal(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

export function writeLocal(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* not available: the feature just forgets */ }
}
