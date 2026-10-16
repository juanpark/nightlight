"use client";
// "Remove this device…": the helper uninstalls itself (or, if it can't, its access is cut) and the device leaves
// the map; what Nightlight kept about it stays archived for 30 days. The inline confirm is the approval.
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Device } from "@/lib/types";

export default function RemoveDevice({ device, onRemoved }: { device: Device; onRemoved: () => void }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  async function remove() {
    setBusy(true);
    setNote("");
    try {
      const r = await api<{ summary: string; removed: string }>("POST", `/api/devices/${device.id}/remove`, {});
      setNote(r.summary);
      if (r.removed === "access_cut") setTimeout(onRemoved, 2500);
    } catch (e) {
      setNote(e instanceof ApiError && e.code === "sign_in_required" ? "Sign in to remove devices."
        : "Couldn't remove it. Please try again.");
    } finally {
      setBusy(false);
      setAsking(false);
    }
  }
  return (
    <div className="remove-device small">
      {!asking && !note && <button className="linkish" onClick={() => setAsking(true)}>Remove this device…</button>}
      {asking && (
        <div className="remove-confirm">
          <div>Remove <strong>{device.name}</strong> from Nightlight? Its helper uninstalls itself and it leaves your map.
            Its history and notes are kept for 30 days.</div>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <button className="danger" disabled={busy} onClick={remove}>{busy ? "Removing…" : "Remove"}</button>
            <button disabled={busy} onClick={() => setAsking(false)}>Keep it</button>
          </div>
        </div>)}
      {note && <div className="muted">{note}</div>}
    </div>
  );
}
