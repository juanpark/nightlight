"use client";
// Settings for the whole account (not one device): for now, whether things nearby may be shown by the names they
// announce. On by default (it is the owner's own map); off deletes the names kept so far. No confirmation: the switch
// can be turned back on, and names return as things announce them again.
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { firebase } from "@/lib/firebase";

/** The time zone the assistant speaks in: the browser's unless the owner picks another. */
function TimeZone({ me }: { me: UserDoc | null | undefined }) {
  const here = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { return "UTC"; } })();
  const saved = me?.settings?.timeZone;
  const [draft, setDraft] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const zones = (() => {
    try { return (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone") ?? []; }
    catch { return []; }
  })();
  const shown = draft ?? saved ?? here;
  const auto = !saved || me?.settings?.timeZoneAuto;
  async function pick(z: string) {
    setDraft(z); setErr("");
    try { await api("POST", "/api/settings", { timeZone: z }); }
    catch { setDraft(null); setErr("Couldn't save the time zone, so it stays as it was. Try again in a moment."); }
  }
  return (
    <div className="setting-row" style={{ flexWrap: "wrap", gap: 8 }}>
      <span><strong>Time zone</strong>: {shown}{auto && !draft ? " (from this browser)" : ""}</span>
      {zones.length > 0 && me && (
        <select aria-label="Time zone" value={shown} onChange={(e) => pick(e.target.value)}>
          {!zones.includes(shown) && <option value={shown}>{shown}</option>}
          {zones.map((z) => <option key={z} value={z}>{z}</option>)}
        </select>)}
      {err && <span className="small" role="alert" style={{ color: "var(--crit-ink)" }}>{err}</span>}
    </div>
  );
}

/** "Nightlight 1.0.0 · web a1b2c3d · API e4f5g6h · helper 0.9.34", leaving out what isn't known. */
function Versions() {
  const [line, setLine] = useState("");
  useEffect(() => {
    let on = true;
    Promise.all([firebase().then((f) => f.config).catch(() => null),
      api<{ app?: string; build?: string; helper?: string }>("GET", "/api/version").catch(() => null)])
      .then(([web, a]) => {
        const short = (b?: string) => b ? b.slice(0, 7) : "";
        const parts = [`Nightlight ${web?.version || a?.app || "dev"}`, web?.build && `web ${short(web.build)}`,
          a?.build && `API ${short(a.build)}`, a?.helper && `helper ${a.helper}`].filter(Boolean);
        if (on) setLine(parts.join(" · "));
      });
    return () => { on = false; };
  }, []);
  return line ? <p className="small muted setting-help">{line}</p> : null;
}
import type { UserDoc } from "@/lib/types";

export default function AccountSettings({ me, anonymous, live = false, onSave, onTour }: {
  me: UserDoc | null | undefined; anonymous: boolean; onSave: () => void; // demo accounts can look, not change
  live?: boolean; // a live demo machine's visit: its account's settings stay as they are
  onTour: () => void; // the first-run tour, from the start
}) {
  const locked = anonymous || live;
  const saved = me?.settings?.deviceNames !== false;
  const [draft, setDraft] = useState<boolean | null>(null); // tapped here, not yet back from the account
  const [err, setErr] = useState("");
  const busy = useRef(false); // one save at a time, so the last tap is what the server ends on
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (draft !== null && draft === saved) setDraft(null); }, [draft, saved]);
  const on = draft ?? saved;
  async function flip() {
    if (busy.current) return;
    busy.current = true; setSaving(true);
    const next = !on;
    setDraft(next); setErr("");
    try { await api("POST", "/api/settings", { deviceNames: next }); }
    catch (e) {
      setDraft(null);
      setErr(e instanceof ApiError && (e.status === 401 || e.status === 403)
        ? "This account can't change its settings, so the switch stays as it was."
        : "Couldn't save that, so the switch stays as it was. Try again in a moment.");
    }
    finally { busy.current = false; setSaving(false); }
  }
  return (
    <div className="panel">
      <h3>Settings</h3>
      {live
        // a shared live machine can't change settings: say what the setting is, rather than a greyed switch that
        // looks off and does nothing when tapped
        ? <p className="setting-row" style={{ margin: 0 }}><span><strong>Show names things announce</strong>{" "}
            <span className="muted">(Living Room TV, Alex&apos;s iPhone)</span>: <strong>{on ? "on" : "off"}</strong></span></p>
        : <label className={`setting-row ${!me || locked ? "off" : ""}`}>
            <input type="checkbox" role="switch" checked={on} onChange={flip} disabled={!me || locked}
              aria-busy={saving || undefined} aria-describedby={`names-help${locked ? " names-demo" : ""}`} />
            <span><strong>Show names things announce</strong> <span className="muted">(Living Room TV, Alex&apos;s iPhone)</span></span>
          </label>}
      <p id="names-help" className="small muted setting-help">Names stay on your own map. Turning this off deletes the
        names kept so far; they come back only when things announce them again.</p>
      {live && <p id="names-demo" className="small muted">This live machine is shared with other visitors, so its
        settings can&apos;t be changed here. On your own account this is a switch.</p>}
      {!live && !anonymous && <TimeZone me={me} />}
      {anonymous && <p id="names-demo" className="small muted">Settings are for your own account.{" "}
        <button className="linkish small" onClick={onSave}>Save with Google</button> to change them.</p>}
      {err && <p className="small" role="alert" style={{ color: "var(--crit-ink)" }}>{err}</p>}
      <p className="small setting-help"><button className="small" onClick={onTour}>Show the tour again</button>{" "}
        <span className="muted">A short walk through what each part of the screen does.</span></p>
      <Versions />
    </div>
  );
}
