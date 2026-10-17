"use client";
// One agent turn: a work log of what Nightlight checked (its running commentary, each step and what came back), then
// its answer, then any approval cards. Quick answers keep the log folded; investigations show it open.
import { useState, type JSX } from "react";
import type { Action, Device, Status } from "@/lib/types";
import ApprovalCard from "../ApprovalCard";
import { Mascot, type Mood } from "@/src/components/mascot/Mascot";
import { ArrowText, Caret, Done, NotDone, Working } from "@/src/components/icons";
import type { AgentTurn, Block } from "./model";

type Step = Extract<Block, { kind: "step" }>;

/** An answer as paragraphs: a blank line starts a new one, a single line break stays a line break. */
const paragraphs = (text: string) =>
  text.trim().split(/\n\s*\n/).map((p, i) => <p key={i}><ArrowText text={p.trim()} /></p>);

const MASCOT = 30; // in a turn: small enough to sit on one line with the text

const secs = (ms?: number) => ms == null ? "" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;

function StepRow({ s }: { s: Step }) {
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
    <details className="wl-step">
      <summary>{line}<Caret className="caret wl-more" size={11} aria-hidden /></summary>
      {s.command && <code className="wl-cmd">$ {s.command}</code>}
      {s.details && <pre className="wl-out">{s.details}</pre>}
    </details>
  );
}

function WorkLog({ blocks, busy, investigate, ms }: { blocks: Block[]; busy: boolean; investigate: boolean; ms?: number }) {
  const [open, setOpen] = useState(investigate);
  const steps = blocks.filter((b): b is Step => b.kind === "step");
  const running = steps.find((s) => s.status === "running");
  const n = `${steps.length} step${steps.length === 1 ? "" : "s"}`;
  // Folded, the log still shows what is happening now and anything that went wrong: failures are never hidden.
  const visible = open ? blocks : blocks.filter((b) => b.kind === "step" && (b === running || b.status === "failed"));
  return (
    <div className={`worklog ${open ? "open" : ""}`}>
      <button className="wl-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Caret className="caret wl-chev" size={11} aria-hidden />
        {busy ? `Working… ${n}` : `What I checked · ${n}${ms ? ` · ${secs(ms)}` : ""}`}
      </button>
      {visible.length > 0 && (
        <div className="wl-body">
          {visible.map((b, i) => b.kind === "text"
            ? <p key={i} className="wl-note"><ArrowText text={b.text.trim()} /></p>
            : b.kind === "step" ? <StepRow key={i} s={b} /> : null)}
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

export default function TurnView({ turn, actions, devices, onFollowUp, latest, health }: {
  turn: AgentTurn; actions: Action[]; devices: Device[]; onFollowUp: (turnId: string) => void;
  latest?: boolean; health?: Status;
}) {
  // The answer is the last thing said; words said before or between steps are commentary in a work log. Everything
  // keeps its order: a card appears where it was put up, between the steps around it.
  let final = -1;
  turn.blocks.forEach((b, i) => { if (b.kind === "text" && b.text.trim()) final = i; });
  const parts: JSX.Element[] = [];
  let seg: Block[] = [];
  const lastStep = turn.blocks.reduce((n, b, i) => b.kind === "step" ? i : n, -1);
  const flush = (i: number) => {
    if (!seg.length) return;
    const blocks = seg;
    seg = [];
    if (blocks.some((b) => b.kind === "step")) {
      const isLast = i > lastStep; // the segment holding the last step carries the turn's totals
      parts.push(<WorkLog key={`log${i}`} blocks={blocks} busy={turn.busy && isLast}
        investigate={turn.mode === "investigate"} ms={isLast ? turn.ms : undefined} />);
    } else {
      blocks.forEach((b, j) => b.kind === "text" && parts.push(<p key={`n${i}.${j}`} className="wl-note"><ArrowText text={b.text.trim()} /></p>));
    }
  };
  turn.blocks.forEach((b, i) => {
    if (b.kind === "card") {
      flush(i);
      const a = actions.find((x) => x.id === b.actionId);
      parts.push(<ApprovalCard key={b.actionId} fold action={a} device={devices.find((d) => d.id === a?.deviceId)}
        onFollowUp={onFollowUp} />);
    } else if (i === final) {
      flush(i);
      parts.push(<div key="answer" className="answer">{paragraphs((b as { text: string }).text)}</div>);
    } else {
      seg.push(b);
    }
  });
  flush(turn.blocks.length);
  const mood = latest && !turn.busy ? settled(turn, actions) : null;
  return (
    <div className={`turn agent ${turn.past ? "past" : ""}`}>
      {turn.mode === "investigate" && <span className="pill turn-mode">Investigated</span>}
      {parts}
      {turn.busy && (final < 0 && lastStep < 0
        ? <div className="turn-mascot thinking"><Mascot size={MASCOT} mood="thinking" health={health} /> Thinking…</div>
        : <div className="turn-mascot"><Mascot size={MASCOT} mood="working" health={health} label="Nightlight is working" /></div>)}
      {turn.error && <div className="turn-error small">{/[ .]/.test(turn.error) ? turn.error : `Problem: ${turn.error}`}</div>}
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
