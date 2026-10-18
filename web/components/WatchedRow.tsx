"use client";
import { useState } from "react";
import type { Watch } from "@/lib/types";
import { timeAgo } from "@/lib/time";
import { removeWatch, watchDot, watchError, watchState, watchSummary } from "@/lib/watches";

/** The "Watched online" row under the board: one small chip per website, and a tiny details card for the one
 * clicked. */
export default function WatchedRow({ watches, now, onAsk }: {
  watches: Watch[]; now: number; onAsk: (q: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const w = watches.find((x) => x.id === open);
  if (watches.length === 0) return null;

  return (
    <div className="watched">
      <div className="small muted" style={{ fontWeight: 600 }}>Watched online</div>
      <div className="watch-chips">
        {watches.map((x) => (
          <button key={x.id} className={`watch-chip ${x.status} ${open === x.id ? "sel" : ""}`}
            onClick={() => { setErr(""); setOpen(open === x.id ? null : x.id); }} title={watchSummary(x, now)}
            aria-expanded={open === x.id}>
            <span className={`dot ${watchDot(x)}`} aria-label={watchState(x)} /> {x.name}
          </button>
        ))}
      </div>
      {w && (
        <div className="card watch-details small">
          <div><strong>{w.name}</strong> <a href={w.url} target="_blank" rel="noreferrer noopener">{w.url}</a></div>
          <div>{watchSummary(w, now)}</div>
          {w.lastChange && <div className="muted">{w.status === "crit" ? "Down since" : "Last changed"}{" "}
            {timeAgo(w.lastChange, now)}</div>}
          {(w.tags ?? []).length > 0 && <div>{w.tags!.map((t) => <span key={t} className="pill" style={{ marginRight: 4 }}>{t}</span>)}</div>}
          <div className="actions">
            <button onClick={() => onAsk(`Is my website "${w.name}" (${w.url}) all right?`)}>Ask about it</button>
            <button className="linkish small" onClick={async () => {
              try { await removeWatch(w.id); setOpen(null); } catch (e) { setErr(watchError(e)); }
            }}>Stop watching</button>
            <button className="linkish small" onClick={() => setOpen(null)}>Close</button>
          </div>
          {err && <div style={{ color: "var(--crit-ink)" }}>{err}</div>}
        </div>
      )}
    </div>
  );
}
