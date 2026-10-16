"use client";
import { useState } from "react";
import type { Watch } from "@/lib/types";
import { addWatch, MAX_WATCHES, normaliseUrl, removeWatch, watchDot, watchError, watchSummary } from "@/lib/watches";

/** Add a website for Nightlight to check from the internet every 5 minutes, and see or remove the ones watched. */
export default function WatchPanel({ watches, now }: { watches: Watch[]; now: number }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const full = watches.length >= MAX_WATCHES;

  async function submit() {
    if (!url.trim()) return;
    setBusy(true);
    setErr("");
    const address = normaliseUrl(url);
    let fallbackName = address;
    try { fallbackName = new URL(address).hostname; } catch { /* the server explains bad addresses */ }
    try {
      await addWatch(name.trim() || fallbackName, address,
        tags.split(",").map((t) => t.trim()).filter(Boolean).slice(0, 6));
      setName(""); setUrl(""); setTags("");
    } catch (e) {
      setErr(watchError(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setErr("");
    try { await removeWatch(id); } catch (e) { setErr(watchError(e)); }
  }

  return (
    <div className="panel">
      <h3>Watch a website</h3>
      <p className="small muted" style={{ marginTop: 0 }}>Nightlight checks it from the internet every 5 minutes and tells
        you when it stops answering. Up to {MAX_WATCHES} addresses.</p>
      <form className="watch-form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (e.g. Family photos)"
          maxLength={40} aria-label="Name" />
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Address (e.g. https://example.com)"
          maxLength={500} aria-label="Web address" required inputMode="url" />
        <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="Tags (optional, comma-separated)"
          maxLength={120} aria-label="Tags" />
        <button className="primary" disabled={busy || full || !url.trim()}>{busy ? "Adding…" : "Watch it"}</button>
      </form>
      {err && <p className="small" role="alert" style={{ color: "var(--crit)" }}>{err}</p>}
      <div className="list" style={{ marginTop: 10 }}>
        {watches.map((w) => (
          <div key={w.id} className="item">
            <span className={`dot ${watchDot(w)}`} style={{ marginTop: 4 }} />
            <span style={{ flex: 1, minWidth: 0 }}>
              <strong>{w.name}</strong> <a className="small muted" href={w.url} target="_blank" rel="noreferrer noopener">
                {w.url}</a>
              <div className="small muted">{watchSummary(w, now)}</div>
            </span>
            <button className="linkish small" onClick={() => remove(w.id)}>Remove</button>
          </div>
        ))}
        {watches.length === 0 && <span className="muted small">Nothing watched yet.</span>}
      </div>
    </div>
  );
}
