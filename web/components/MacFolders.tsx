"use client";
// Whether Nightlight may measure a Mac's personal folders (Downloads, Desktop, Documents, Movies, the Trash): macOS
// asks on the Mac itself, so the app can only ask it to ask again. Used in the device's Settings and the setup card.
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Action, Device } from "@/lib/types";

export const FOLDERS_FROM = "0.9.22"; // helpers that can ask macOS for the personal folders when the app asks
const FINISHED = ["done", "failed", "denied", "stale"];

export default function MacFolders({ device: d, actions }: { device: Device; actions: Action[] }) {
  const [asked, setAsked] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const job = asked ? actions.find((a) => a.id === asked) : undefined;
  const asking = !!asked && (!job || !FINISHED.includes(job.status));
  async function ask() {
    setErr("");
    try {
      const r = await api<{ actionId: string }>("POST", `/api/devices/${d.id}/mac-folders`, {});
      setAsked(r.actionId);
    } catch (e) {
      setErr(e instanceof ApiError && e.code === "update_helper" ? "Its helper needs updating first (Updates, below)."
        : e instanceof ApiError && e.code === "not_a_mac" ? "This only applies to Macs." : "Couldn't ask. Please try again.");
    }
  }
  const state = d.macFolders === "allowed" ? "Nightlight can measure them."
    : d.macFolders === "declined" ? "macOS said no last time." : "Not asked yet.";
  return (
    <div className="mac-folders small">
      <span>Personal folders (Downloads, Desktop, Documents, Movies, the Trash): {state}</span>
      {asking
        ? <span className="live-status"><span className="dot offline pulse" /> macOS is asking on the {d.name} now: click
            <em> Allow</em> for each folder there.</span>
        : d.macFolders !== "allowed" && (
          <button className="small" onClick={ask}>{d.macFolders === "declined" || job ? "Ask again" : "Ask on the Mac"}</button>)}
      {job && !asking && job.result?.summary && <span className="muted">{job.result.summary}</span>}
      {err && <span style={{ color: "var(--crit)" }}>{err}</span>}
    </div>
  );
}
