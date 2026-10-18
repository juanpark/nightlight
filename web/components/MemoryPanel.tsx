"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Memories { enabled: boolean; memories: { id: string; fact: string; updatedAt: string | null }[] }

export default function MemoryPanel() {
  const [data, setData] = useState<Memories | null>(null);
  const [err, setErr] = useState("");
  const [sure, setSure] = useState(false); // forgetting can't be undone: one more tap
  const load = () => api<Memories>("GET", "/api/me/memories").then(setData)
    .then(() => setErr(""), () => setErr("Couldn't load what Nightlight remembers. Try Refresh in a moment."));
  useEffect(() => { load(); }, []);
  return (
    <div className="panel">
      <h3>What Nightlight remembers about you</h3>
      <p className="small muted" style={{ marginTop: 0 }}>Things you asked it to keep in mind, like when the kids play.
        Never passwords or device readings (those are always checked live).</p>
      {!data ? <span className="muted small">Loading…</span>
        : !data.enabled ? <span className="muted small">Memory is switched off.</span>
        : data.memories.length === 0 ? <span className="muted small">Nothing yet. Try: &quot;Remember that the kids play
          Minecraft on weekends.&quot;</span>
        : <div className="list">{data.memories.map((m) => <div key={m.id} className="item">• {m.fact}</div>)}</div>}
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button onClick={load}>Refresh</button>
        {data?.memories.length ? (sure
          ? <>
              <button className="danger" onClick={() => api("DELETE", "/api/me/memories").then(() => {
                setData({ ...data, memories: [] }); setSure(false); }, () => setErr("Couldn't forget them. Please try again."))}>
                Yes, forget everything</button>
              <button onClick={() => setSure(false)}>Keep them</button>
            </>
          : <button onClick={() => setSure(true)}>Forget everything</button>) : null}
      </div>
      {err && <p className="small" style={{ color: "var(--crit-ink)" }}>{err}</p>}
    </div>
  );
}
