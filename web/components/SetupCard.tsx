"use client";
// Once, when one of your own devices first connects: what may Nightlight do there? The usual presets, signed updates,
// and on a Mac whether it may measure the personal folders (macOS asks on the Mac). One call saves it all; the choice
// can be changed any time in the device's Settings.
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { newer, type Go } from "@/lib/needsYou";
import type { Action, Device } from "@/lib/types";
import { PRESETS } from "./Permissions";

const FOLDERS_FROM = "0.9.22"; // helpers that can ask macOS for the personal folders when the app asks

type Reply = { ok: boolean; done?: boolean; applied?: boolean; macFoldersAction?: string | null; why?: string }; // done: setupAt saved

export default function SetupCard({ device: d, actions, onGo }: { device: Device; actions: Action[]; onGo: (g: Go) => void }) {
  const strict = d.manage !== "app";
  const [preset, setPreset] = useState<"watch" | "fix" | "custom">("fix");
  const [auto, setAuto] = useState(true);
  const [folders, setFolders] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<Reply | null>(null);
  const [err, setErr] = useState("");
  const canFolders = /mac/i.test(d.os ?? "") && !strict && !newer(FOLDERS_FROM, d.helperVersion);
  const job = sent?.macFoldersAction ? actions.find((a) => a.id === sent.macFoldersAction) : undefined;
  const asking = !!sent?.macFoldersAction && (!job || !["done", "failed", "denied", "stale"].includes(job.status));
  // gone once the server has the choice, unless macOS is still asking on the Mac
  if (d.realm !== "real" || d.kind === "watched" || (d.setupAt && !asking && !job)) return null;

  async function save() {
    setErr(""); setBusy(true);
    try {
      const r = await api<Reply>("POST", `/api/devices/${d.id}/setup`, strict ? { preset: "watch" }
        : { preset, autoUpdate: auto, ...(canFolders ? { macFolders: folders } : {}) });
      setSent(r);
      if (!strict && preset === "custom" && r.done) onGo({ to: "drawer", deviceId: d.id, tab: "settings" });
    } catch (e) {
      setErr(e instanceof ApiError && e.code === "sign_in_required" ? "Sign in to set this up." : "Couldn't save that. Please try again.");
    } finally { setBusy(false); }
  }
  const fresh = d.createdAt && Date.now() - d.createdAt.getTime() < 86400000;

  if (sent?.macFoldersAction) {
    return (
      <div className="setup-card">
        <strong>Saved.</strong>{" "}
        {asking ? <>macOS is asking on the {d.name} now: click <em>Allow</em> for each folder there.</>
          : job?.status === "done" ? <>{job.result?.summary ?? "The folders can be measured now."}</>
          : <>{job?.result?.summary ?? "macOS didn't allow it."} You can try again from Settings.</>}
      </div>
    );
  }
  return (
    <div className="setup-card">
      <strong>{fresh ? `Your ${d.name} is connected. ` : ""}What may Nightlight do on {fresh ? "it" : `your ${d.name}`}?</strong>
      {strict
        ? <p className="small">This device is set to strict: what Nightlight may do here is set on the device itself,
            in its helper&apos;s settings. Nightlight will watch it and explain problems.</p>
        : <>
            <div className="setup-presets" role="radiogroup" aria-label="What may Nightlight do here?">
              {PRESETS.map((p) => (
                <label key={p.id} className={preset === p.id ? "on" : ""}>
                  <input type="radio" name={`setup-${d.id}`} checked={preset === p.id} onChange={() => setPreset(p.id)} />
                  <span><b>{p.name}{p.id === "fix" ? " (recommended)" : ""}</b><span className="small muted">{p.id === "custom"
                    ? "Pick each thing yourself: the device's Settings open next." : p.copy}</span></span>
                </label>))}
            </div>
            <label className="setup-check small">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              Install signed updates of the helper automatically</label>
            {canFolders && (
              <label className="setup-check small">
                <input type="checkbox" checked={folders} onChange={(e) => setFolders(e.target.checked)} />
                Also measure Downloads, Desktop, Documents, Movies and the Trash (macOS will ask you on the Mac)</label>)}
          </>}
      {sent?.why === "update_helper"
        ? <p className="small">Its helper needs updating first.{" "}
            <button className="linkish small" onClick={() => onGo({ to: "drawer", deviceId: d.id, tab: "settings" })}>Update</button></p>
        : sent?.why === "not_a_mac" && <p className="small muted">The folders option is for Macs; the rest is saved.</p>}
      <div className="setup-actions">
        <button className="primary" onClick={save} disabled={busy}>{strict ? "Got it" : "Done"}</button>
        {!strict && <span className="small muted">You can change this any time in Settings.</span>}
      </div>
      {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
    </div>
  );
}
