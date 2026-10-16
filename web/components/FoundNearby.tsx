"use client";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Discovery } from "@/lib/types";

/** Things a helper found on its network and its owner chose to share (no addresses). Add = put it on the map,
 * watched by that helper (it checks the thing still answers). */
export default function FoundNearby({ discoveries }: { discoveries: Discovery[] }) {
  const [names, setNames] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const live = discoveries.filter((d) => (d.expiresAt?.getTime() ?? 0) > Date.now());
  async function add(d: Discovery, cid: string, guess: string) {
    setMsg("");
    try {
      await api("POST", `/api/discoveries/${d.id}/${cid}/add`, { name: (names[cid] ?? guess).trim() || guess });
    } catch (e) {
      setMsg(e instanceof ApiError && e.code === "already_added" ? "That one is already on your map." : "Couldn't add it.");
    }
  }
  return (
    <div className="panel">
      <h3>Found nearby</h3>
      {live.length === 0 && (
        <p className="small muted" style={{ marginTop: 0 }}>Nothing yet. On a device with the helper, run
          <code> python3 ~/.local/share/nightlight/nightlight_helper.py discover</code> (on a Mac:
          <code> ~/Library/Application\ Support/Nightlight/</code>). It shows what it found and sends only what you
          pick, never addresses.</p>
      )}
      {live.map((d) => (
        <div key={d.id} style={{ marginTop: 8 }}>
          <div className="small muted">Found by {d.byName}</div>
          <div className="list">
            {d.items.map((it) => (
              <div key={it.cid} className="item" style={{ alignItems: "center" }}>
                <span style={{ flex: 1 }}><strong>{it.guess}</strong>
                  {it.vendor && <span className="muted"> · {it.vendor}</span>}
                  {it.services.length > 0 && <span className="muted small"> ({it.services.join(", ")})</span>}</span>
                {it.added ? <span className="pill live">On your map</span> : (
                  <>
                    <input value={names[it.cid] ?? it.guess} maxLength={40} aria-label="Name"
                      onChange={(e) => setNames({ ...names, [it.cid]: e.target.value })} style={{ width: 160 }} />
                    <button className="primary" onClick={() => add(d, it.cid, it.guess)}>Add</button>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
      {msg && <p className="small" style={{ color: "var(--crit)" }}>{msg}</p>}
    </div>
  );
}
