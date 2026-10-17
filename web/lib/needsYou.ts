// "Needs you": one derived list of everything that is waiting for the person, computed from data the app already
// has. The same items, with the same words, appear as a mark on the device tile, at the top of the device panel and
// in the strip above the map. Nothing is stored: an item disappears when its reason does.
import { useCallback, useEffect, useState } from "react";
import { applied, normal } from "./permissions";
import type { Action, Device, FoundThing, TrustDoc } from "./types";

export type NeedKind = "approve" | "critical" | "silent" | "update" | "removing" | "uninstallLine" | "expertHalf"
  | "permsWaiting" | "found" | "offer";
export type Priority = 1 | 2 | 3; // 1 act now (red), 2 decide (orange), 3 finish setting up (grey)
export type Go =
  | { to: "card"; actionId: string }
  | { to: "drawer"; deviceId: string; tab?: "overview" | "about" | "settings" }
  | { to: "panel"; panel: "found" }
  | { to: "chat"; ask: string }
  | { to: "offer"; actionType: string; offerId: string }
  | { to: "line"; line: "uninstall" }; // shown in place, with Copy and Done

export interface Need {
  id: string; kind: NeedKind; priority: Priority; deviceId?: string; title: string; detail?: string;
  cta: { label: string; go: Go }; at: number;
}

export interface NeedsInput {
  devices: Device[]; actions: Action[]; trust: TrustDoc[]; found: FoundThing[]; // found: what can go on the map
  release?: { version: string } | null; expert?: { enabled: boolean } | null; now: number;
  dismissed?: string[]; // items the person marked done (only the ones that can't clear themselves)
}

/** Needs the person marked done, kept in this browser (an uninstall line pasted elsewhere can't be seen). */
export function useDismissed(): [string[], (id: string) => void] {
  const [ids, setIds] = useState<string[]>([]);
  useEffect(() => {
    try { setIds(JSON.parse(localStorage.getItem("nl_dismissed") ?? "[]")); } catch { setIds([]); }
    const on = (e: Event) => setIds((e as CustomEvent<string[]>).detail);
    window.addEventListener("nl_dismissed", on);
    return () => window.removeEventListener("nl_dismissed", on);
  }, []);
  const dismiss = useCallback((id: string) => {
    let next: string[] = [id];
    try { next = [...new Set([...JSON.parse(localStorage.getItem("nl_dismissed") ?? "[]"), id])].slice(-50);
      localStorage.setItem("nl_dismissed", JSON.stringify(next)); } catch { /* this visit only */ }
    window.dispatchEvent(new CustomEvent("nl_dismissed", { detail: next }));
  }, []);
  return [ids, dismiss];
}

const WEEK = 7 * 86400000;
const PERMS_GRACE = 3 * 60000; // a device picks a change up on its next report, about a minute

/** True when version a is newer than b ("0.9.10" > "0.9.9"). */
export function newer(a?: string, b?: string): boolean {
  const k = (v?: string) => (v ?? "").split(".").map((x) => parseInt(x, 10) || 0);
  const x = k(a), y = k(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) > (y[i] ?? 0);
  }
  return false;
}

export function ago(ms: number): string {
  const m = Math.round(ms / 60000);
  return m < 90 ? `${Math.max(1, m)} min` : m < 2880 ? `${Math.round(m / 60)} hours` : `${Math.round(m / 1440)} days`;
}

export function needsYou(i: NeedsInput): Need[] {
  const out: Need[] = [];
  const name = (id: string) => i.devices.find((d) => d.id === id)?.name ?? "a device";
  const open = (a: Action) => ["approved", "running"].includes(a.status);
  for (const a of i.actions) {
    if (a.status !== "pending") continue;
    out.push({ id: `approve:${a.id}`, kind: "approve", deviceId: a.deviceId,
      priority: a.riskClass === "destructive" || a.type === "remove_device" ? 1 : 2,
      title: a.plan, detail: "Waiting for your OK", cta: { label: "Review", go: { to: "card", actionId: a.id } },
      at: a.createdAt?.getTime() ?? 0 });
  }
  for (const d of i.devices) {
    const real = d.realm === "real";
    const removing = i.actions.some((a) => a.deviceId === d.id && a.type === "remove_device" && open(a));
    if (removing) {
      out.push({ id: `removing:${d.id}`, kind: "removing", priority: 2, deviceId: d.id,
        title: "Being removed, waiting for the device", cta: { label: "Details", go: { to: "drawer", deviceId: d.id } },
        at: i.now });
      continue;
    }
    if (real && d.status === "offline" && !d.revoked) {
      const silentFor = d.lastSeen ? i.now - d.lastSeen.getTime() : 0;
      out.push({ id: `silent:${d.id}`, kind: "silent", priority: silentFor > 86400000 ? 1 : 2, deviceId: d.id,
        title: d.lastSeen ? `Hasn't reported for ${ago(silentFor)}` : "Hasn't reported yet",
        detail: "Nightlight can't reach in; it will tell you when it's back",
        cta: { label: "Why?", go: { to: "chat", ask: `Why isn't my ${d.name} reporting?` } }, at: i.now });
      continue; // its other signals are out of date while it is silent
    }
    const crit = (d.findings ?? []).find((f) => (f.state ?? "new") === "new" && f.severity === "crit");
    if (crit && d.status === "crit") {
      out.push({ id: `critical:${d.id}:${crit.id ?? crit.message}`, kind: "critical", priority: 1, deviceId: d.id,
        title: crit.message, detail: crit.evidence,
        cta: { label: "What should I do?", go: { to: "chat", ask: `What should I do about this on my ${d.name}: ${crit.message}` } },
        at: i.now });
    }
    if (real && i.release && d.helperVersion && newer(i.release.version, d.helperVersion)
        && !newer("0.9.0", d.helperVersion)
        && !i.actions.some((a) => a.deviceId === d.id && a.type === "update_helper" && open(a))) {
      out.push({ id: `update:${d.id}:${i.release.version}`, kind: "update", priority: 3, deviceId: d.id,
        title: `Helper update ${d.helperVersion} → ${i.release.version}`,
        cta: { label: "Update", go: { to: "drawer", deviceId: d.id, tab: "settings" } }, at: i.now });
    }
    const sent = d.permissionsAt?.getTime();
    if (real && d.manage === "app" && sent && i.now - sent > PERMS_GRACE
        && !applied(normal(d.permissions), d.allowedJobs ?? {}, (d.containerCount ?? 0) === 0)) {
      out.push({ id: `perms:${d.id}`, kind: "permsWaiting", priority: 3, deviceId: d.id,
        title: "Permission change not yet applied", detail: "The device hasn't picked it up",
        cta: { label: "Details", go: { to: "drawer", deviceId: d.id, tab: "settings" } }, at: sent });
    }
    // Only a real mismatch: the device trusts a passkey the app no longer has (expert sessions are opt-in per
    // device, so a device without them is not "half set up").
    const pinned = (d.allowedJobs?.expert ?? []).includes("on");
    if (real && i.expert && pinned && !i.expert.enabled) {
      out.push({ id: `expert:${d.id}`, kind: "expertHalf", priority: 3, deviceId: d.id,
        title: "Expert sessions half set up", detail: "This device trusts a passkey: create it again in the app",
        cta: { label: "Finish", go: { to: "drawer", deviceId: d.id, tab: "settings" } }, at: i.now });
    }
  }
  // A removed device is gone from the map, but if it couldn't uninstall itself the person still has one step to do.
  for (const a of i.actions) {
    const at = (a.finishedAt ?? a.createdAt)?.getTime() ?? 0;
    if (a.type !== "remove_device" || a.status !== "done" || !a.result?.summary.includes("uninstall line")
        || i.now - at > WEEK || i.dismissed?.includes(`uninstall:${a.id}`)) continue;
    out.push({ id: `uninstall:${a.id}`, kind: "uninstallLine", priority: 3,
      title: `Finish removing it: paste the uninstall line on the device`, detail: a.result.summary,
      cta: { label: "Show line", go: { to: "line", line: "uninstall" } }, at });
  }
  const found = i.found.length;
  if (found > 0) {
    out.push({ id: "found", kind: "found", priority: 3, title: `${found} thing${found === 1 ? "" : "s"} found nearby you can add`,
      cta: { label: "Review", go: { to: "panel", panel: "found" } }, at: i.now });
  }
  for (const t of i.trust) {
    if (!t.offer) continue;
    out.push({ id: `offer:${t.id}`, kind: "offer", priority: 3, title: t.offer.text,
      cta: { label: "Decide", go: { to: "offer", actionType: t.actionType, offerId: t.offer.offerId } }, at: i.now });
  }
  return out.sort((a, b) => a.priority - b.priority || b.at - a.at);
}

export function byDevice(needs: Need[]): Map<string, Need[]> {
  const m = new Map<string, Need[]>();
  for (const n of needs) if (n.deviceId) m.set(n.deviceId, [...(m.get(n.deviceId) ?? []), n]);
  return m;
}

export function verdict(needs: Need[]): string {
  if (needs.length === 0) return "All quiet at home";
  const urgent = needs.filter((n) => n.priority === 1).length;
  return `${needs.length} ${needs.length === 1 ? "thing needs" : "things need"} you` + (urgent && needs.length > 1
    ? `, ${urgent} urgent` : "");
}

/** One plain sentence about a device, for the top of its panel. */
export function statusSentence(d: Device, now: number, removing = false): string {
  if (removing) return "Being removed. Waiting for the device to uninstall its helper.";
  const first = (sev: string) => (d.findings ?? []).find((f) => (f.state ?? "new") === "new" && f.severity === sev);
  if (d.realm === "real" && d.status === "offline") {
    return d.lastSeen ? `Not reporting for ${ago(now - d.lastSeen.getTime())}. Last seen ${d.lastSeen.toLocaleString()}.`
      : "Hasn't reported yet.";
  }
  if (d.status === "crit") return `Needs attention now: ${first("crit")?.message ?? "see below"}`;
  if (d.status === "warn") return `Needs attention soon: ${first("warn")?.message ?? "see below"}`;
  if (d.realm !== "real") return "All good.";
  if (d.createdAt && now - d.createdAt.getTime() < 86400000) return "All good. Learning what normal looks like here (first day).";
  return d.lastSeen ? `All good. Reported ${ago(now - d.lastSeen.getTime())} ago.` : "All good.";
}
