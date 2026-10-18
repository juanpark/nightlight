"use client";
// One agent turn: a work log of what Nightlight checked (its running commentary, each step and what came back), then
// its answer, then any approval cards. Quick answers keep the log folded; investigations show it open.
import { useState, type JSX } from "react";
import { useNow } from "@/lib/data";
import type { Action, Device, Metrics, Status } from "@/lib/types";
import ApprovalCard from "../ApprovalCard";
import { Mascot, type Mood } from "@/src/components/mascot/Mascot";
import { ArrowText, Caret, Done, NotDone, Working } from "@/src/components/icons";
import type { AgentTurn, Block } from "./model";
import Markdown from "./Markdown";

type Step = Extract<Block, { kind: "step" }>;

const MASCOT = 30; // in a turn: small enough to sit on one line with the text

const secs = (ms?: number) => ms == null ? "" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;

/** "gemini-3.8-flash" → "Gemini 3.8 Flash". */
const modelName = (id: string) => id.split(/[-_]/).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
const cents = (usd: number) => { const c = usd * 100; return c < 0.1 ? "under 0.1¢" : `${c.toFixed(c < 10 ? 1 : 0)}¢`; };

/** What went wrong with an answer, as a sentence with a way on. The server's own sentences pass through; its short
 *  codes ("rate_limited") and the browser's "connection problem" become plain words. */
function plainError(e: string): string {
  if (/[ .]/.test(e) && e !== "connection problem") return e;
  if (e === "connection problem") return "Lost the connection to Nightlight. Check your internet, then ask again.";
  if (/rate|too_many|quota/.test(e)) return "That's a lot of questions at once. Wait a minute, then ask again.";
  if (/timeout|slow|deadline/.test(e)) return "Gemini is slow right now, so this answer stopped early. Ask again, or switch to Quick answers.";
  if (/sign_in|auth|forbidden/.test(e)) return "Your sign-in ran out. Reload the page, then ask again.";
  return "Nightlight couldn't finish this answer. Ask again in a moment.";
}

/** The receipt for an answer: how long it took, which model wrote it and what it cost. */
function receipt(ms?: number, m?: Metrics): string {
  const slow = m?.slowCalls ? `${m.slowCalls} slow call${m.slowCalls === 1 ? "" : "s"} retried` : "";
  return [ms ? secs(ms) : "", m?.model ? modelName(m.model) : "", m?.costUsd != null ? cents(m.costUsd) : "", slow]
    .filter(Boolean).join(" · ");
}

const span = (s: number) => s >= 60 && s % 60 === 0 ? `${s / 60} min` : s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;

/** "45 s of 4 min": how long this answer has been working, against the time the server gives it. */
function Elapsed({ from, budget }: { from: number; budget: number }) {
  const now = useNow(1000);
  return <> · {span(Math.max(0, Math.min(budget, Math.round((now - from) / 1000))))} of {span(budget)}</>;
}

function StepRow({ s, show }: { s: Step; show?: boolean }) {
  const more = !!(s.command || s.details);
  const line = (
    <>
      <span className={`wl-dot ${s.status}`} aria-label={s.status} />
      <span className="wl-label">{s.label}</span>
      {s.summary && <span className="wl-summary"> — <ArrowText text={s.summary} /></span>}
      {s.status === "stopped" && <span className="wl-summary muted"> — stopped</span>}
      {s.ms != null && s.status !== "running" && <span className="wl-ms">{secs(s.ms)}</span>}
    </>
  );
  if (!more) return <div className="wl-step">{line}</div>;
  return (
    <details className="wl-step" open={show || undefined}>{/* an investigation shows its outputs */}
      <summary>{line}<Caret className="caret wl-more" size={11} aria-hidden /></summary>
      {s.command && <code className="wl-cmd">$ {s.command}</code>}
      {s.details && <pre className="wl-out">{s.details}</pre>}
    </details>
  );
}

function WorkLog({ blocks, busy, investigate, from, budget }: {
  blocks: Block[]; busy: boolean; investigate: boolean; from?: number; budget?: number;
}) {
  const [open, setOpen] = useState(investigate);
  const steps = blocks.filter((b): b is Step => b.kind === "step");
  const n = `${steps.length} step${steps.length === 1 ? "" : "s"}`;
  // Folded, the log still lists every step with what came back (its outputs stay one tap away); open, it adds the
  // commentary said between steps.
  const visible = open ? blocks : blocks.filter((b) => b.kind === "step");
  return (
    <div className={`worklog ${open ? "open" : ""}`}>
      <button className="wl-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Caret className="caret wl-chev" size={11} aria-hidden />
        {busy ? <>Working… {n}{from && budget ? <Elapsed from={from} budget={budget} /> : null}</>
          : `What I checked · ${n}`}
      </button>
      {visible.length > 0 && (
        <div className="wl-body">
          {visible.map((b, i) => b.kind === "text"
            ? <div key={i} className="wl-note"><Markdown text={b.text.trim()} /></div>
            : b.kind === "step" ? <StepRow key={i} s={b} show={investigate} /> : null)}
        </div>)}
    </div>
  );
}

/** How the mascot feels at the end of the latest finished turn: a problem, a card waiting, or a job that went well.
 *  While a turn runs it is thinking until there are words or steps, then working (also while the answer is written). */
function settled(turn: AgentTurn, actions: Action[]): Mood | null {
  const ids = [...turn.blocks.flatMap((b) => b.kind === "card" ? [b.actionId] : []), ...(turn.after ?? [])];
  // A follow-up can start before its action says it continues this turn, so the live link counts too.
  const mine = actions.filter((a) => ids.includes(a.id) || (turn.turnId && a.continuationTurnId === turn.turnId));
  if (turn.error || mine.some((a) => a.status === "failed" || a.result?.ok === false)) return "trouble";
  if (mine.some((a) => a.status === "pending")) return "waiting"; // still needs the person, even after a stop
  if (turn.stopped || turn.blocks.some((b) => b.kind === "step" && b.status === "stopped")) return "trouble";
  if (mine.some((a) => a.status === "done")) return "done";
  return null;
}

export default function TurnView({ turn, actions, devices, onFollowUp, latest, health, onRetry }: {
  turn: AgentTurn; actions: Action[]; devices: Device[]; onFollowUp: (turnId: string) => void;
  latest?: boolean; health?: Status;
  onRetry?: () => void; // asks the same question again, offered when the server says trying again may work
}) {
  // The answer is the last thing said; words said before or between steps are commentary in a work log. Everything
  // keeps its order: a card appears where it was put up, between the steps around it.
  const blocks = turn.blocks;
  let final = -1;
  blocks.forEach((b, i) => { if (b.kind === "text" && b.text.trim()) final = i; });
  const parts: JSX.Element[] = [];
  let seg: Block[] = [];
  const lastStep = blocks.reduce((n, b, i) => b.kind === "step" ? i : n, -1);
  const steps = blocks.filter((b) => b.kind === "step").length;
  const flush = (i: number) => {
    if (!seg.length) return;
    const blocks = seg;
    seg = [];
    if (blocks.some((b) => b.kind === "step")) {
      const isLast = i > lastStep; // the segment holding the last step carries the turn's totals
      parts.push(<WorkLog key={`log${i}`} blocks={blocks} busy={turn.busy && isLast}
        investigate={turn.mode === "investigate"} from={turn.startedAt} budget={turn.budget} />);
    } else {
      blocks.forEach((b, j) => b.kind === "text" && parts.push(<div key={`n${i}.${j}`} className="wl-note"><Markdown text={b.text.trim()} /></div>));
    }
  };
  blocks.forEach((b, i) => {
    if (b.kind === "card") {
      flush(i);
      const a = actions.find((x) => x.id === b.actionId);
      parts.push(<ApprovalCard key={b.actionId} fold action={a} device={devices.find((d) => d.id === a?.deviceId)}
        onFollowUp={onFollowUp} />);
    } else if (i === final) {
      flush(i);
      parts.push(<div key="answer" className="answer"><Markdown text={(b as { text: string }).text.trim()} /></div>);
    } else {
      seg.push(b);
    }
  });
  flush(blocks.length);
  const mood = latest && !turn.busy ? settled(turn, actions) : null;
  return (
    <div className={`turn agent ${turn.past ? "past" : ""}`}>
      {turn.mode === "investigate" && <span className="pill turn-mode">Investigated</span>}
      {parts}
      {/* the receipt, small and quiet under the answer: steps, time, model, cost */}
      {!turn.busy && final >= 0 && receipt(turn.ms, turn.metrics) &&
        <div className="wl-receipt">{steps ? `${steps} step${steps === 1 ? "" : "s"}` : "Answered from what I know"}
          {" · "}{receipt(turn.ms, turn.metrics)}</div>}
      {turn.busy && (final < 0 && lastStep < 0
        ? <div className="turn-mascot thinking"><Mascot size={MASCOT} mood="thinking" health={health} /> Thinking…</div>
        : <div className="turn-mascot"><Mascot size={MASCOT} mood="working" health={health} label="Nightlight is working" /></div>)}
      {turn.error && <div className="turn-error small" role="alert">{plainError(turn.error)}
        {!turn.busy && onRetry && <>{" "}<button className="linkish small" onClick={onRetry}>Ask again</button></>}</div>}
      {mood && <div className="turn-mascot"><Mascot key={mood} size={MASCOT} mood={mood} health={health} /></div>}
    </div>
  );
}

/** Above a follow-up: the job it continues, from the action itself (nothing extra is stored). How it went comes first,
 *  as a word with its own icon, then what was asked, then what the device said. */
export function JobLine({ ids, turnId, actions }: { ids?: string[]; turnId?: string; actions: Action[] }) {
  // A follow-up can start before its action says it continues this turn, so the live link counts too.
  const a = actions.find((x) => (ids?.includes(x.id) || (turnId && x.continuationTurnId === turnId))
    && (x.result || ["approved", "running", "failed"].includes(x.status)));
  if (!a) return null;
  const state = a.result?.ok === false || a.status === "failed" ? "failed" : a.result ? "done" : "working";
  const { Icon, word } = JOB[state];
  return (
    <div className={`job-line ${state}`}>
      <Icon size={18} weight="fill" aria-hidden />
      <p className="job-head"><b>{word}</b> <ArrowText text={a.plan.trim().replace(/\.$/, "")} /></p>
      {a.result?.summary && <p className="job-result"><ArrowText text={a.result.summary} /></p>}
    </div>
  );
}

const JOB = {
  done: { Icon: Done, word: "Done" },
  failed: { Icon: NotDone, word: "Didn't work" }, // the card's own words
  working: { Icon: Working, word: "Approved, working on it" },
};
