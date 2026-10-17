"use client";
// "Update available" for a real device's helper. The tap is the approval; the device installs the new version only
// if Nightlight's signature checks out (see docs/SECURITY.md), then reports in Activity.
import { useState } from "react";
import { newer } from "@/lib/needsYou";
import { api, ApiError } from "@/lib/api";
import type { Action, Device } from "@/lib/types";

export default function HelperUpdate({ device, actions, origin, latest }: {
  device: Device; actions: Action[]; origin: string; latest?: string;
}) {
  const [error, setError] = useState("");
  if (!latest || !newer(latest, device.helperVersion)) return null;
  const job = actions.find((a) => a.deviceId === device.id && a.type === "update_helper"
    && (a.params as { version?: string } | undefined)?.version === latest);
  const old = newer("0.9.0", device.helperVersion);
  async function go() {
    setError("");
    try {
      await api("POST", `/api/devices/${device.id}/update`, {});
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      setError(code === "updates_off" ? "Updates from the app are switched off for this device (below)."
        : code === "device_not_reporting" ? "The device isn't reporting right now; try again when it is."
        : "Couldn't start the update. Please try again.");
    }
  }
  return (
    <div className="update-bar small">
      <span className="pill live">Update available</span>
      <span>Helper {device.helperVersion ?? "?"} → {latest}</span>
      {old
        ? <span className="muted">This version can&apos;t update itself yet. Once, on the device:
            <code className="perm-cmd">curl -fsSL {origin}/install.sh | sh</code></span>
        : job && ["approved", "running"].includes(job.status)
          ? <span className="muted">Updating on the device…</span>
          : job?.status === "failed" ? <><span>{job.result?.summary}</span><button onClick={go}>Try again</button></>
          : <button className="primary" onClick={go}>Update</button>}
      {error && <span style={{ color: "var(--crit)" }}>{error}</span>}
    </div>
  );
}
