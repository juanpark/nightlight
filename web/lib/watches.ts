"use client";
// Watched web addresses: plain-words status, adding and removing (POST/DELETE /api/watches).
import { api, ApiError } from "./api";
import { timeAgo } from "./time";
import type { Watch } from "./types";

export const MAX_WATCHES = 10;

/** The dot class used on the board for a watch's status. */
export const watchDot = (w: Watch) => (w.status === "ok" ? "ok" : w.status === "crit" ? "crit" : "offline");

export function watchState(w: Watch): string {
  if (w.status === "ok") return "Up";
  if (w.status === "crit") return w.httpStatus ? `Down (error ${w.httpStatus})` : "Down (no answer)";
  return "Not checked yet";
}

/** "Up · answered in 120 ms · checked 2 min ago" */
export function watchSummary(w: Watch, now = Date.now()): string {
  const parts = [watchState(w)];
  if (w.status === "ok" && w.latencyMs != null) parts.push(`answered in ${Math.round(w.latencyMs)} ms`);
  if (w.lastCheckedAt) parts.push(`checked ${timeAgo(w.lastCheckedAt, now)}`);
  return parts.join(" · ");
}

const ERRORS: Record<string, string> = {
  bad_url: "That doesn't look like a web address. Try something like https://example.com.",
  unknown_host: "We couldn't find that address on the internet. Please check the spelling.",
  private_address: "That is a private or home address, so it can't be reached from the internet. Addresses inside "
    + "your home are watched by the Nightlight helper on one of your devices, not from here.",
  too_many_watches: `You can watch up to ${MAX_WATCHES} addresses. Remove one to add another.`,
  watch_budget: "That's a lot of changes for one day. Please try again tomorrow.",
  sign_in_required: "Watching websites needs a Google account. Use Save with Google first.",
};

export function watchError(e: unknown): string {
  if (!(e instanceof ApiError)) return "Something went wrong. Please try again.";
  // 422 reasons come in the standard validation shape: detail[0].msg
  const detail = (e.body.detail as { msg?: string }[] | undefined)?.[0]?.msg;
  return ERRORS[e.code] || (detail && ERRORS[detail]) || "Something went wrong. Please try again.";
}

/** Adds https:// when the owner typed just "example.com". */
export function normaliseUrl(raw: string): string {
  const s = raw.trim();
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(s) ? s : `https://${s}`;
}

export function addWatch(name: string, url: string, tags: string[]) {
  return api<{ id: string; url: string }>("POST", "/api/watches", { name, url, ...(tags.length ? { tags } : {}) });
}

export function removeWatch(id: string) {
  return api<{ ok: boolean }>("DELETE", `/api/watches/${encodeURIComponent(id)}`);
}
