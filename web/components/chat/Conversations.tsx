"use client";
// The chat's "Conversations" control: the account's recent chats (newest first, by date and first question), to switch
// between them on any device, and New chat.
import { useEffect, useState } from "react";
import { recentSessions, type Conversation } from "@/lib/session";

const when = (d: Date | null) => d
  ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
  : "";

export default function Conversations({ uid, generation, open, disabled, onPick }: {
  uid: string; generation?: number; open: string | null; disabled: boolean;
  onPick: (sid: string | null) => void; // null: New chat
}) {
  const [shown, setShown] = useState(false);
  const [list, setList] = useState<Conversation[] | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    if (!shown) return;
    let on = true;
    setErr(false);
    recentSessions(uid, generation).then((l) => { if (on) setList(l.filter((c) => !c.empty || c.id === open)); },
      () => { if (on) setErr(true); });
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setShown(false); };
    document.addEventListener("keydown", esc);
    return () => { on = false; document.removeEventListener("keydown", esc); };
  }, [shown, uid, generation, open]);
  const choose = (sid: string | null) => { setShown(false); onPick(sid); };

  return (
    <div className="convos">
      <div className="convos-bar">
        <button className="small" aria-expanded={shown} onClick={() => setShown(!shown)}>Conversations</button>
        <button className="small" disabled={disabled || open === null} onClick={() => choose(null)}>New chat</button>
      </div>
      {shown && (
        <div className="convos-list" role="list">
          {err ? <p className="small muted">Couldn&apos;t load your conversations. Try again in a moment.</p>
            : !list ? <p className="small muted">Loading…</p>
              : list.length === 0 ? <p className="small muted">No conversations yet. Ask something below.</p>
                : list.map((c) => (
                  <button key={c.id} role="listitem" className="convo" aria-current={c.id === open || undefined}
                    disabled={disabled} onClick={() => choose(c.id)} title={c.title}>
                    <span className="convo-title">{c.title}</span>
                    <span className="small muted">{when(c.createdAt)}</span>
                  </button>))}
        </div>)}
    </div>
  );
}
