"use client";
// Browser notifications while the tab is open (no service worker): one per new, serious, real event.
import { useEffect, useRef, useState } from "react";
import { readLocal, writeLocal } from "./local";
import type { EventDoc } from "./types";

const KEY = "nl_notify";
const ALWAYS = new Set(["silent", "watch_crit"]);

export const notificationsSupported = () => typeof window !== "undefined" && "Notification" in window;

/** The "Notify me" switch, remembered in this browser. Turning it on asks for permission first. */
export function useNotifySetting() {
  const [on, setOn] = useState(false);
  const [denied, setDenied] = useState(false);
  useEffect(() => {
    if (!notificationsSupported()) return;
    setDenied(Notification.permission === "denied");
    setOn(readLocal(KEY) === "1" && Notification.permission === "granted");
  }, []);
  async function toggle() {
    if (!notificationsSupported()) return;
    if (on) { setOn(false); writeLocal(KEY, "0"); return; }
    let perm = Notification.permission;
    if (perm === "default") perm = await Notification.requestPermission();
    setDenied(perm === "denied");
    if (perm === "granted") { setOn(true); writeLocal(KEY, "1"); }
  }
  return { on, denied, toggle, supported: notificationsSupported() };
}

/** Shows a notification for each real event that is a problem (warn or crit, or a device going silent, or a
 * watched website going down) and happened after the page loaded and after the switch was turned on. */
export function useEventNotifications(events: EventDoc[], on: boolean) {
  const since = useRef(Date.now());
  const shown = useRef(new Set<string>());
  useEffect(() => { if (on) since.current = Math.max(since.current, Date.now()); }, [on]);
  useEffect(() => {
    if (!on || !notificationsSupported() || Notification.permission !== "granted") return;
    for (const e of events) {
      if (e.realm !== "real" || shown.current.has(e.id) || !e.at || e.at.getTime() <= since.current) continue;
      if (!(e.severity === "crit" || e.severity === "warn" || ALWAYS.has(e.kind))) continue;
      shown.current.add(e.id);
      try {
        const n = new Notification(e.severity === "crit" ? "Nightlight: needs you now" : "Nightlight",
          { body: e.message, tag: e.id });
        n.onclick = () => { window.focus(); n.close(); };
      } catch { /* some mobile browsers only allow notifications from a service worker */ }
    }
  }, [events, on]);
}
