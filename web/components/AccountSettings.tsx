"use client";
// Settings for the whole account (not one device): for now, whether things nearby may be shown by the names they
// announce. On by default (it is the owner's own map); off removes the names already kept. No confirmation: it can be
// turned back on.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { UserDoc } from "@/lib/types";

export default function AccountSettings({ me, anonymous, onSave }: {
  me: UserDoc | null | undefined; anonymous: boolean; onSave: () => void; // demo accounts can look, not change
}) {
  const saved = me?.settings?.deviceNames !== false;
  const [draft, setDraft] = useState<boolean | null>(null); // tapped here, not yet back from the account
  const [err, setErr] = useState("");
  useEffect(() => { if (draft !== null && draft === saved) setDraft(null); }, [draft, saved]);
  const on = draft ?? saved;
  async function flip() {
    const next = !on;
    setDraft(next); setErr("");
    try { await api("POST", "/api/settings", { deviceNames: next }); }
    catch { setDraft(null); setErr("Couldn't change that. Try again."); }
  }
  return (
    <div className="panel">
      <h3>Settings</h3>
      <label className="setting-row">
        <input type="checkbox" role="switch" checked={on} onChange={flip} disabled={!me || anonymous} />
        <span>
          <strong>Show names things announce</strong> <span className="muted">(Living Room TV, Alex&apos;s iPhone)</span>
          <span className="small muted setting-help">Names stay on your own map. Turning this off removes the ones kept.</span>
        </span>
      </label>
      {anonymous && <p className="small muted">Settings are for your own account.{" "}
        <button className="linkish small" onClick={onSave}>Save with Google</button> to change them.</p>}
      {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
    </div>
  );
}
