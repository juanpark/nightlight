"use client";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { loadMessages } from "@/lib/data";
import { chatSession, newChat, savedSession } from "@/lib/session";
import { api, ApiError, stream } from "@/lib/api";
import type { Action, Device, StreamEvent } from "@/lib/types";
import ApprovalCard from "./ApprovalCard";

export interface ChatHandle { ask: (text: string) => void; followUp: (turnId: string) => void }

type Item =
  | { kind: "user"; text: string; past?: boolean }
  | { kind: "agent"; text: string; steps: Step[]; cards: string[]; error?: string; busy: boolean; past?: boolean };

/** One thing Nightlight did while answering, and (once it came back) what it found. */
interface Step { name: string; label: string; result?: string; details?: string }

const SUGGESTIONS = ["Is anything wrong at home?", "My kids say Minecraft is laggy tonight. Can you help?",
  "When was the Minecraft world last backed up?"];

function step(e: Extract<StreamEvent, { type: "tool_call" }>, devices: Device[]) {
  const id = (e.args?.device_id as string) ?? "";
  const name = devices.find((d) => d.id === id)?.name ?? "the device";
  return ({
    list_fleet: "Looking over your home…", get_device: `Checking the ${name}…`,
    get_recent_events: "Reading what happened recently…", restart_container: `Preparing a fix for the ${name}…`,
    look_into: `Asking the ${name} what happened to ${(e.args?.target as string) ?? "it"}…`, remember: "Making a note…",
    restart_service: `Preparing a fix for the ${name}…`, clean_up: `Preparing a clean-up for the ${name}…`,
    inspect: `Looking around the ${name}…`, run_playbook: `Running a checkup on the ${name}…`,
    write_note: `Noting what I learned about the ${name}…`, how_nightlight_works: "Checking how Nightlight does this…",
    remove_device: `Preparing to remove the ${name}…`,
    start_investigation: `Asking to investigate the ${name}…`,
    run_command: `$ ${(e.args?.command as string) ?? ""}`,
    propose_command: `Preparing a command for the ${name}…`,
  } as Record<string, string>)[e.name] ?? `Working on the ${name}…`;
}

const Chat = forwardRef<ChatHandle, {
  uid: string; actions: Action[]; devices: Device[]; disabled: boolean; generation?: number;
}>(
  function Chat({ uid, actions, devices, disabled, generation }, ref) {
    const [items, setItems] = useState<Item[]>([]);
    const [text, setText] = useState("");
    const [busy, setBusy] = useState(false);
    const [deep, setDeep] = useState(false); // Investigate: a stronger model that digs in (slower, a few cents)
    const log = useRef<HTMLDivElement>(null);
    const streamed = useRef(new Set<string>());
    const pending = useRef(new Set<string>()); // follow-ups promised by a device that hasn't answered yet
    const [pendingTick, setPendingTick] = useState(0); // re-check actions when a new promise arrives
    const devicesRef = useRef(devices);
    devicesRef.current = devices;

    useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" }); }, [items]);
    // The saved conversation comes back when the chat opens (kept 30 days); a reset (new generation) starts clean.
    useEffect(() => {
      setItems([]);
      const sid = savedSession(uid, generation);
      if (!sid) return;
      let cancelled = false;
      loadMessages(uid, sid).then((msgs) => {
        if (cancelled || !msgs.length) return;
        const past: Item[] = msgs.map((m) => m.role === "user"
          ? { kind: "user", text: m.text, past: true }
          : { kind: "agent", text: m.text, busy: false, past: true, cards: m.actionIds ?? [],
              steps: (m.toolCalls ?? []).map((t) => ({ name: t.name, result: "",
                label: step({ type: "tool_call", name: t.name, args: t.args ?? {} } as Extract<StreamEvent, { type: "tool_call" }>,
                  devicesRef.current) })) });
        setItems((cur) => [...past, ...cur]);
      }).catch(() => {});
      return () => { cancelled = true; };
    }, [uid, generation]);

    const update = (fn: (a: Extract<Item, { kind: "agent" }>) => void) =>
      setItems((cur) => {
        const next = [...cur];
        const last = next[next.length - 1];
        if (last?.kind === "agent") {
          const copy = { ...last, steps: last.steps.map((s) => ({ ...s })), cards: [...last.cards] };
          fn(copy);
          next[next.length - 1] = copy;
        }
        return next;
      });

    const run = useCallback(async (path: string, body: unknown, retries = 0) => {
      // A follow-up can't start while the turn that asked is still finishing (409): wait and try again.
      for (let i = 0; i < retries; i++) {
        try {
          await stream(path, body, () => {});
          break;
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 409)) break;
          await new Promise((r) => setTimeout(r, 3000));
        }
      }
      setItems((cur) => [...cur, { kind: "agent", text: "", steps: [], cards: [], busy: true }]);
      try {
        await stream(path, body, (e) => update((a) => {
          if (e.type === "text") a.text += e.delta;
          else if (e.type === "tool_call") a.steps.push({ name: e.name, label: step(e, devicesRef.current) });
          else if (e.type === "tool_result") {
            const s = a.steps.find((x) => x.name === e.name && x.result === undefined);
            if (s) { s.result = e.summary ?? "done"; s.details = e.details ?? undefined; }
          }
          else if (e.type === "approval_request" && !a.cards.includes(e.actionId)) a.cards.push(e.actionId);
          else if (e.type === "followup_pending") { pending.current.add(e.turnId); setPendingTick((n) => n + 1); }
          else if (e.type === "error") a.error = e.message || e.code;
        }));
      } catch (e) {
        update((a) => { a.error = e instanceof ApiError ? e.code : "connection problem"; });
      } finally {
        update((a) => { a.busy = false; });
      }
    }, []);

    const session = () => chatSession(uid, generation);

    const ask = useCallback(async (q: string) => {
      if (!q.trim() || busy) return;
      setBusy(true);
      setText("");
      setItems((cur) => [...cur, { kind: "user", text: q }]);
      try {
        const sid = await session();
        await run(`/api/chat/sessions/${sid}/messages`,
          { text: q, clientRequestId: crypto.randomUUID(), mode: deep ? "investigate" : "quick" });
      } finally {
        setBusy(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [busy, run, uid, generation, deep]);



    // When a slow device answers, its action gets the follow-up turn: open it.
    useEffect(() => {
      for (const a of actions) {
        if (a.continuationTurnId && pending.current.has(a.continuationTurnId)) {
          pending.current.delete(a.continuationTurnId);
          if (!streamed.current.has(a.continuationTurnId)) {
            streamed.current.add(a.continuationTurnId);
            run(`/api/turns/${a.continuationTurnId}/stream`, {}, 20);
          }
        }
      }
    }, [actions, run, pendingTick]);

    // eslint-disable-next-line react-hooks/exhaustive-deps
    useImperativeHandle(ref, () => ({ ask, followUp: (id: string) => followUp(id) }), [ask]);

    const followUp = useCallback((turnId: string) => {
      if (streamed.current.has(turnId)) return;
      streamed.current.add(turnId);
      run(`/api/turns/${turnId}/stream`, {});
    }, [run]);

    return (
      <>
        <div className="chat-log" ref={log}>
          {items.length === 0 && (
            <div className="muted small">Ask Nightlight about your home. It explains in plain words and asks before it
              changes anything.</div>
          )}
          {items.some((it) => it.past) && (
            <div className="chat-past-note small muted">Earlier in this chat (kept 30 days) ·{" "}
              <button className="linkish" disabled={busy} onClick={() => { newChat(uid, generation); setItems([]); }}>
                Start a new chat</button></div>
          )}
          {items.map((it, i) => it.kind === "user"
            ? <div key={i} className={`bubble user ${it.past ? "past" : ""}`}>{it.text}</div>
            : (
              <div key={i} className={it.past ? "past" : ""} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {it.steps.length > 0 && (
                  <div className="steps" aria-label="What Nightlight did">
                    {it.steps.map((s, j) => (
                      <div key={j} className="step">
                        <span className={`step-dot ${s.result === undefined ? "busy" : s.result.startsWith("Couldn't") ? "bad" : "ok"}`} />
                        <span>{s.label.replace(/…$/, "")}{s.result ? <span className="step-result"> — {s.result}</span> : null}</span>
                        {s.details && <details className="step-details"><summary>details</summary><pre>{s.details}</pre></details>}
                      </div>))}
                  </div>)}
                {(it.text || it.busy) && <div className="bubble agent">{it.text || "…"}</div>}
                {it.cards.map((id) => {
                  const a = actions.find((x) => x.id === id);
                  return <ApprovalCard key={id} action={a} device={devices.find((d) => d.id === a?.deviceId)}
                    onFollowUp={followUp} />;
                })}
                {it.error && <div className="small" style={{ color: "var(--crit)" }}>Problem: {it.error}</div>}
              </div>
            ))}
        </div>
        <div className="suggest">
          {SUGGESTIONS.map((s) => <button key={s} disabled={busy || disabled} onClick={() => ask(s)}>{s}</button>)}
        </div>
        <label className="deep-toggle small" title="A stronger model that investigates step by step (slower)">
          <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} /> Investigate deeply
        </label>
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask Nightlight…"
            maxLength={1000} disabled={disabled} />
          <button className="primary" disabled={busy || disabled || !text.trim()}>Send</button>
        </form>
      </>
    );
  });

export default Chat;
