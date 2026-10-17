"use client";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { loadMessages } from "@/lib/data";
import { chatSession, newChat, savedSession } from "@/lib/session";
import { ApiError, stream } from "@/lib/api";
import { followBegin, followEnd, followStep, followText } from "@/lib/follow";
import type { Action, Device, StreamEvent } from "@/lib/types";
import { apply, fromHistory, key, stop, type AgentTurn, type Mode, type Turn } from "./chat/model";
import TurnView, { afterLine } from "./chat/TurnView";
import "@/app/chat.css";

export interface ChatHandle { ask: (text: string) => void; followUp: (turnId: string) => void }

const rank = (s?: string) => ({ crit: 0, warn: 1, offline: 2 } as Record<string, number>)[s ?? ""] ?? 3;

/** Questions to start with, about what is actually on the map: the sample home's story, or the person's own devices. */
function suggestions(devices: Device[]): string[] {
  if (devices.some((d) => d.realm !== "real")) {
    return ["Is anything wrong at home?", "My kids say Minecraft is laggy tonight. Can you help?",
      "When was the Minecraft world last backed up?"];
  }
  const own = devices.filter((d) => d.kind !== "watched");
  if (!own.length) return ["What can you do for me?", "How do I add my first device?"];
  const worst = [...own].sort((a, b) => rank(a.status) - rank(b.status))[0];
  return ["Is anything wrong at home?", `How is my ${worst.name} doing?`,
    own.length > 1 ? "Which device needs attention first?" : `What runs on my ${worst.name}?`];
}


const MODES: { id: Mode; name: string; hint: string }[] = [
  { id: "quick", name: "Quick", hint: "Fast answers from what Nightlight already knows" },
  { id: "investigate", name: "Investigate deeply",
    hint: "Works like an administrator: hypotheses, checks, commands. Slower, a few cents" },
];

function savedMode(): Mode {
  try { return localStorage.getItem("nl_mode") === "investigate" ? "investigate" : "quick"; } catch { return "quick"; }
}

const Chat = forwardRef<ChatHandle, {
  uid: string; actions: Action[]; devices: Device[]; disabled: boolean; generation?: number;
}>(
  function Chat({ uid, actions, devices, disabled, generation }, ref) {
    const [turns, setTurns] = useState<Turn[]>([]);
    const [text, setText] = useState("");
    const [mode, setMode] = useState<Mode>("quick");
    const log = useRef<HTMLDivElement>(null);
    const nearBottom = useRef(true);
    const streamed = useRef(new Set<string>());
    const pending = useRef(new Set<string>()); // follow-ups promised by a device that hasn't answered yet
    const [pendingTick, setPendingTick] = useState(0); // re-check actions when a new promise arrives
    const watching = useRef(new Set<AbortController>());
    const devicesRef = useRef(devices);
    devicesRef.current = devices;
    const actionsRef = useRef(actions);
    actionsRef.current = actions;
    const [sending, setSending] = useState(false); // from Send until the answer's turn exists (session may be created)
    const sendingRef = useRef(false);
    const busy = sending || turns.some((t) => t.kind === "agent" && t.busy);

    useEffect(() => { setMode(savedMode()); }, []);
    // Follow the conversation only while the person is at the bottom; reading further up is never interrupted.
    useEffect(() => {
      if (nearBottom.current) log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" });
    }, [turns]);
    // The saved conversation comes back when the chat opens (kept 30 days); a reset (new generation) starts clean.
    useEffect(() => {
      setTurns([]);
      const sid = savedSession(uid, generation);
      if (!sid) return;
      let cancelled = false;
      loadMessages(uid, sid).then((msgs) => {
        if (!cancelled && msgs.length) setTurns((cur) => [...fromHistory(msgs, devicesRef.current), ...cur]);
      }).catch(() => {});
      return () => { cancelled = true; };
    }, [uid, generation]);

    const update = (k: string, fn: (t: AgentTurn) => AgentTurn) =>
      setTurns((cur) => cur.map((t) => t.kind === "agent" && t.key === k ? fn(t) : t));

    const run = useCallback(async (path: string, body: unknown, turnMode: Mode, after?: string[], retries = 0) => {
      const k = key();
      const ctl = new AbortController();
      watching.current.add(ctl);
      setTurns((cur) => [...cur, { kind: "agent", key: k, mode: turnMode, blocks: [], busy: true, after }]);
      const followed = followBegin(); // the map lights up what this answer's steps touch
      const onEvent = (e: StreamEvent) => {
        if (e.type === "tool_call") followStep(followed, e.args);
        else if (e.type === "text") followText(followed, e.delta);
        // A device that answers later promises a follow-up turn: open it once its action points to it.
        if (e.type === "followup_pending") { pending.current.add(e.turnId); setPendingTick((n) => n + 1); }
        else update(k, (t) => apply(t, e, devicesRef.current));
      };
      try {
        // A follow-up can't start while the turn that asked is still finishing (409): wait and try again.
        for (let i = 0; ; i++) {
          try {
            await stream(path, body, onEvent, ctl.signal);
            break;
          } catch (e) {
            if (!(e instanceof ApiError && e.status === 409 && i < retries)) throw e;
            const wait = Math.min(10, Number(e.body.retryAfter) || 3); // the server says how long the other turn holds
            await new Promise((r) => setTimeout(r, wait * 1000));
          }
        }
        update(k, (t) => ({ ...t, busy: false }));
      } catch (e) {
        if (ctl.signal.aborted) {
          update(k, stop);
        } else {
          update(k, (t) => ({ ...stop(t), error: t.error ?? (e instanceof ApiError ? e.code : "connection problem") }));
        }
      } finally {
        watching.current.delete(ctl);
        followEnd(followed);
      }
    }, []);

    /** Stop the answers in progress: closing the stream ends the turn on the server, keeping what it already did. */
    const stopWatching = () => {
      if (!watching.current.size) return;
      for (const c of watching.current) c.abort();
      setTurns((cur) => [...cur, { kind: "system", key: key(), icon: "stopped",
        text: "Stopped. What Nightlight already did is kept; ask again to go on." }]);
    };

    const ask = useCallback(async (q: string) => {
      // Reserved synchronously: a second Send while the session is being created can't start a second answer.
      if (!q.trim() || busy || sendingRef.current) return;
      sendingRef.current = true;
      setSending(true);
      setText("");
      nearBottom.current = true;
      setTurns((cur) => [...cur, { kind: "user", key: key(), text: q }]);
      let sid: string;
      try {
        sid = await chatSession(uid, generation);
      } catch {
        setTurns((cur) => [...cur, { kind: "agent", key: key(), mode, blocks: [], busy: false,
          error: "Couldn't start the chat. Please try again." }]);
        return;
      } finally {
        sendingRef.current = false;
        setSending(false);
      }
      await run(`/api/chat/sessions/${sid}/messages`, { text: q, clientRequestId: crypto.randomUUID(), mode }, mode);
    }, [busy, run, uid, generation, mode]);

    // Approve can be tapped while the answer that showed the card is still streaming: its follow-up then waits its turn.
    const followUp = useCallback((turnId: string, retries = 10) => {
      if (streamed.current.has(turnId)) return;
      streamed.current.add(turnId);
      const after = actionsRef.current.filter((a) => a.continuationTurnId === turnId).map((a) => a.id);
      run(`/api/turns/${turnId}/stream`, {}, "quick", after, retries);
    }, [run]);

    // When a slow device answers, its action gets the follow-up turn: open it.
    useEffect(() => {
      for (const a of actions) {
        if (a.continuationTurnId && pending.current.has(a.continuationTurnId)) {
          pending.current.delete(a.continuationTurnId);
          followUp(a.continuationTurnId, 20);
        }
      }
    }, [actions, followUp, pendingTick]);
    useImperativeHandle(ref, () => ({ ask, followUp: (id: string) => followUp(id) }), [ask, followUp]);

    function pickMode(m: Mode) {
      if (m === mode) return;
      setMode(m);
      try { localStorage.setItem("nl_mode", m); } catch { /* private window: this chat only */ }
      if (turns.length) {
        setTurns((cur) => [...cur, { kind: "system", key: key(), icon: "mode",
          text: m === "investigate" ? "Switched to Investigate deeply" : "Switched to Quick answers" }]);
      }
    }

    return (
      <>
        <div className="chat-log" ref={log} onScroll={(e) => {
          const el = e.currentTarget;
          nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}>
          {turns.length === 0 && (
            <div className="chat-empty">
              <strong>Ask about your home</strong>
              <p className="muted small">Nightlight looks at your devices, explains what it finds in plain words, and asks
                before it changes anything.</p>
              {suggestions(devices).map((s) => (
                <button key={s} className="chat-starter" disabled={busy || disabled} onClick={() => ask(s)}>{s}</button>))}
            </div>
          )}
          {turns.some((t) => "past" in t && t.past) && (
            <div className="chat-past-note small muted">Earlier in this chat (kept 30 days) ·{" "}
              <button className="linkish" disabled={busy} onClick={() => { newChat(uid, generation); setTurns([]); }}>
                Start a new chat</button></div>
          )}
          {turns.map((t) => {
            if (t.kind === "user") return <div key={t.key} className={`bubble user ${t.past ? "past" : ""}`}>{t.text}</div>;
            if (t.kind === "system") return <div key={t.key} className={`chat-system ${t.icon}`}>{t.text}</div>;
            const line = afterLine(t.after, actions, devices);
            return (
              <div key={t.key} className="turn-wrap">
                {line && <div className="chat-system job">{line}</div>}
                <TurnView turn={t} actions={actions} devices={devices} onFollowUp={followUp} />
              </div>
            );
          })}
        </div>
        <div className="mode-switch" role="radiogroup" aria-label="How Nightlight answers">
          {MODES.map((m) => (
            <button key={m.id} role="radio" aria-checked={mode === m.id} className={mode === m.id ? "on" : ""}
              onClick={() => pickMode(m.id)}>{m.name}</button>
          ))}
          <span className="mode-hint small muted">{MODES.find((m) => m.id === mode)?.hint}</span>
        </div>
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask Nightlight…"
            maxLength={1000} disabled={disabled} />
          {busy
            ? <button type="button" onClick={stopWatching} title="Stop this answer (what was already done is kept)">
                Stop</button>
            : <button className="primary" disabled={disabled || !text.trim()}>Send</button>}
        </form>
      </>
    );
  });

export default Chat;
