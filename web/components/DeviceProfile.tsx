"use client";
// "About this device": the living notes Nightlight keeps about a machine (what it is, what runs there, quirks, past
// incidents and fixes). Nightlight rewrites it after investigating; you can edit it. It reads it before every dig.
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useProfile } from "@/lib/data";

export default function DeviceProfile({ uid, deviceId }: { uid: string; deviceId: string }) {
  const p = useProfile(uid, deviceId);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  async function save() {
    setErr("");
    try {
      await api("PUT", `/api/devices/${deviceId}/profile`, { text });
      setEditing(false);
    } catch (e) {
      setErr(e instanceof ApiError && JSON.stringify(e.body).includes("looks_secret")
        ? "That looked like a password, key or address, so it wasn't saved." : "Couldn't save it.");
    }
  }
  return (
    <section className="profile small">
      <h4>About this device <span className="muted">what Nightlight knows about this machine</span>
        {!editing && <button className="linkish" style={{ marginLeft: 8 }}
          onClick={() => { setText(p?.text ?? ""); setEditing(true); }}>{p ? "Edit" : "Write one"}</button>}</h4>
      {!editing && (p
        ? <div className="profile-text">{p.text}<div className="muted">{p.by === "you" ? "Written by you" : "Kept by Nightlight"}
            {p.updatedAt ? ` · ${p.updatedAt.toLocaleDateString()}` : ""}</div></div>
        : <p className="muted">Nothing yet. Nightlight writes this after it investigates (what runs here, quirks, past
            problems and fixes), or write your own.</p>)}
      {editing && (
        <div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} rows={8}
            style={{ width: "100%" }} placeholder="What it is, what runs there, how it's set up, quirks…" />
          <div style={{ display: "flex", gap: 6 }}>
            <button className="primary" disabled={!text.trim()} onClick={save}>Save</button>
            <button onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>)}
      {err && <div style={{ color: "var(--crit)" }}>{err}</div>}
    </section>
  );
}
