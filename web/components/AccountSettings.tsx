"use client";
// Settings for the whole account (not one device): for now, whether things nearby may be shown by the names they
// announce. On by default (it is the owner's own map); off deletes the names kept so far. No confirmation: the switch
// can be turned back on, and names return as things announce them again.
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { UserDoc } from "@/lib/types";

export default function AccountSettings({ me, anonymous, onSave }: {
  me: UserDoc | null | undefined; anonymous: boolean; onSave: () => void; // demo accounts can look, not change
}) {
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
    catch { setDraft(null); setErr("Couldn't change that. Try again."); }
    finally { busy.current = false; setSaving(false); }
  }
  return (
    <div className="panel">
      <h3>Settings</h3>
      <label className={`setting-row ${!me || anonymous ? "off" : ""}`}>
        <input type="checkbox" role="switch" checked={on} onChange={flip} disabled={!me || anonymous}
          aria-busy={saving || undefined} aria-describedby={`names-help${anonymous ? " names-demo" : ""}`} />
        <span><strong>Show names things announce</strong> <span className="muted">(Living Room TV, Alex&apos;s iPhone)</span></span>
      </label>
      <p id="names-help" className="small muted setting-help">Names stay on your own map. Turning this off deletes the
        names kept so far; they come back only when things announce them again.</p>
      {anonymous && <p id="names-demo" className="small muted">Settings are for your own account.{" "}
        <button className="linkish small" onClick={onSave}>Save with Google</button> to change them.</p>}
      {err && <p className="small" role="alert" style={{ color: "var(--crit)" }}>{err}</p>}
    </div>
  );
}
