"use client";
// Fixes that worked on this device, saved by Nightlight as steps. Using one goes through the chat, so each step is
// still a card the person approves; here they can rename one, say when it helps, or delete it.
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useRunbooks } from "@/lib/data";
import type { Device, Runbook } from "@/lib/types";

function Item({ device, rb, onAsk }: { device: Device; rb: Runbook; onAsk: (q: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(rb.title);
  const [when, setWhen] = useState(rb.when);
  const [deleting, setDeleting] = useState(false);
  const [err, setErr] = useState("");
  async function save() {
    setErr("");
    try {
      await api("POST", `/api/devices/${device.id}/runbooks/${rb.id}`, { title: title.trim(), when: when.trim() });
      setEditing(false);
    } catch (e) {
      setErr(e instanceof ApiError && JSON.stringify(e.body).includes("looks_secret")
        ? "That looked like a password, key or address, so it wasn't saved." : "Couldn't save that. Try again.");
    }
  }
  async function remove() {
    try { await api("DELETE", `/api/devices/${device.id}/runbooks/${rb.id}`); }
    catch { setErr("Couldn't delete it. Try again."); setDeleting(false); }
  }
  return (
    <div className="runbook small">
      {editing
        ? <form className="runbook-edit" onSubmit={(e) => { e.preventDefault(); save(); }}>
            <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={80} aria-label="Name" required />
            <input value={when} onChange={(e) => setWhen(e.target.value)} maxLength={200} aria-label="When it helps" required />
            <span className="runbook-actions">
              <button className="primary small">Save</button>
              <button type="button" className="small" onClick={() => { setEditing(false); setTitle(rb.title); setWhen(rb.when); }}>Cancel</button>
            </span>
          </form>
        : <>
            <div><strong>{rb.title}</strong>{rb.service && <span className="pill" style={{ marginLeft: 6 }}>{rb.service}</span>}</div>
            <div className="muted">Helps when {rb.when.replace(/^when\s+/i, "")}</div>
          </>}
      <ol className="runbook-steps">{rb.steps.map((s, i) => <li key={i}>{s.say}</li>)}</ol>
      <div className="runbook-actions">
        <button className="small" onClick={() => onAsk(`Use the saved fix "${rb.title}" on my ${device.name}.`)}>Use it</button>
        <span className="muted">{rb.uses ? `used ${rb.uses} time${rb.uses === 1 ? "" : "s"}` : "not used yet"}</span>
        {!editing && <button className="linkish small" onClick={() => setEditing(true)}>Edit</button>}
        {!deleting
          ? <button className="linkish small" onClick={() => setDeleting(true)}>Delete</button>
          : <>Delete it? <button className="small" onClick={remove}>Delete</button>
              <button className="small" onClick={() => setDeleting(false)}>Keep</button></>}
      </div>
      {err && <span style={{ color: "var(--crit)" }}>{err}</span>}
    </div>
  );
}

export default function Runbooks({ uid, generation, device, onAsk }: {
  uid: string; generation?: number; device: Device; onAsk: (q: string) => void;
}) {
  const runbooks = useRunbooks(uid, device.id, generation);
  return (
    <section className="drawer-section">
      <h4>Fixes that worked here <span className="muted small">saved by Nightlight; each step still asks you</span></h4>
      {runbooks.length === 0
        ? <p className="small muted">None yet. When a fix works, Nightlight saves the steps here so it can offer them
            again next time.</p>
        : runbooks.map((rb) => <Item key={rb.id} device={device} rb={rb} onAsk={onAsk} />)}
    </section>
  );
}
