"use client";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { aboutApp } from "@/lib/apps";
import { useNotes } from "@/lib/data";
import type { Service } from "@/lib/types";

/** What Nightlight and the owner learned about this device (or, given an app, about that app on it); Nightlight
 * reads it before it investigates. */
export default function Notebook({ uid, deviceId, app }: { uid: string; deviceId: string; app?: Service }) {
  const all = useNotes(uid, deviceId);
  const notes = app ? all.filter(aboutApp(app)) : all;
  const [text, setText] = useState("");
  const [problem, setProblem] = useState("");
  const [open, setOpen] = useState(false);
  async function add() {
    if (!text.trim()) return;
    setProblem("");
    try {
      await api("POST", `/api/devices/${deviceId}/notes`, { text: text.trim() });
      setText("");
    } catch (e) {
      setProblem(e instanceof ApiError && JSON.stringify(e.body).includes("looks_secret")
        ? "That looked like a password, key or address, so it wasn't saved."
        : "Couldn't save the note. Try again.");
    }
  }
  // device-wide notes first, then the notes about each app or service on it
  const general = app ? notes : notes.filter((n) => !n.service);
  const services = app ? [] : [...new Set(notes.filter((n) => n.service).map((n) => n.service!))].sort();
  const shown = open ? general : general.slice(0, 3);
  const row = (n: (typeof notes)[number]) => (
    <div key={n.id} className="note small">
      <span className={`pill ${n.by === "you" ? "" : "live"}`}>{n.by === "you" ? "You" : "Nightlight"}</span>
      <span style={{ flex: 1 }}>{n.text}</span>
      <span className="muted">{n.at ? n.at.toLocaleDateString() : ""}</span>
      <button className="linkish" aria-label="Remove note"
        onClick={() => api("DELETE", `/api/devices/${deviceId}/notes/${n.id}`).catch(() => {})}>×</button>
    </div>
  );
  return (
    <section className="notebook">
      <h4>Notebook <span className="muted small">what Nightlight and you noted about this {app ? "app" : "device"}</span></h4>
      {notes.length === 0 && (app
        ? <p className="small muted">Nothing about {app.name} yet. Nightlight adds what it learns when it looks into it.</p>
        : <p className="small muted">Nothing yet. Nightlight adds what it learns here when it looks into a problem; you
            can add things too (where it is, who uses it, quirks).</p>)}
      {shown.map(row)}
      {general.length > 3 && <button className="linkish small" onClick={() => setOpen(!open)}>
        {open ? "Show fewer" : `Show all ${general.length}`}</button>}
      {services.map((s) => (
        <div key={s} className="note-group">
          <div className="small muted"><strong>{s}</strong></div>
          {notes.filter((n) => n.service === s).map(row)}
        </div>))}
      {!app && <form className="note-add" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} maxLength={300}
          placeholder="Add a note (e.g. in the hallway cupboard; the kids' game server)" />
        <button disabled={!text.trim()}>Add</button>
      </form>}
      {problem && <p className="small" style={{ color: "var(--crit)" }}>{problem}</p>}
    </section>
  );
}
