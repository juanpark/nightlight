"use client";
// One agent turn: a work log of what Nightlight checked (its running commentary, each step and what came back), then
// its answer, then any approval cards. Quick answers keep the log folded; investigations show it open.
import { useState, type JSX } from "react";
import type { Action, Device, Metrics } from "@/lib/types";
import ApprovalCard from "../ApprovalCard";
import { withLead, type AgentTurn, type Block } from "./model";

type Step = Extract<Block, { kind: "step" }>;

const secs = (ms?: number) => ms == null ? "" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;

/** "gemini-3.8-flash" → "Gemini 3.8 Flash". */
const modelName = (id: string) => id.split(/[-_]/).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
const cents = (usd: number) => { const c = usd * 100; return c < 0.1 ? "under 0.1¢" : `${c.toFixed(c < 10 ? 1 : 0)}¢`; };

/** The receipt for an answer: how long it took, which model wrote it and what it cost. */
function receipt(ms?: number, m?: Metrics): string {
  return [ms ? secs(ms) : "", m?.model ? modelName(m.model) : "", m?.costUsd != null ? cents(m.costUsd) : ""]
    .filter(Boolean).join(" · ");
}

function StepRow({ s, show }: { s: Step; show?: boolean }) {
  const more = !!(s.command || s.details);
  const line = (
    <>
      <span className={`wl-dot ${s.status}`} aria-label={s.status} />
      <span className="wl-label">{s.label}</span>
      {s.summary && <span className="wl-summary"> — {s.summary}</span>}
      {s.status === "stopped" && <span className="wl-summary muted"> — stopped</span>}
      {s.ms != null && s.status !== "running" && <span className="wl-ms">{secs(s.ms)}</span>}
    </>
  );
  if (!more) return <div className="wl-step">{line}</div>;
  return (
    <details className="wl-step" open={show || undefined}>{/* an investigation shows its outputs */}
      <summary>{line}</summary>
      {s.command && <code className="wl-cmd">$ {s.command}</code>}
      {s.details && <pre className="wl-out">{s.details}</pre>}
    </details>
  );
}

function WorkLog({ blocks, busy, investigate, ms, metrics }: {
  blocks: Block[]; busy: boolean; investigate: boolean; ms?: number; metrics?: Metrics;
}) {
  const [open, setOpen] = useState(investigate);
  const steps = blocks.filter((b): b is Step => b.kind === "step");
  const n = `${steps.length} step${steps.length === 1 ? "" : "s"}`;
  // Folded, the log still lists every step with what came back (its outputs stay one tap away); open, it adds the
  // commentary said between steps.
  const visible = open ? blocks : blocks.filter((b) => (b.kind === "lead" && busy) || b.kind === "step");
  const paid = receipt(ms, metrics);
  return (
    <div className={`worklog ${open ? "open" : ""}`}>
      <button className="wl-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="wl-chev">{open ? "▾" : "▸"}</span>
        {busy ? `Working… ${n}` : `What I checked · ${n}${paid ? ` · ${paid}` : ""}`}
      </button>
      {visible.length > 0 && (
        <div className="wl-body">
          {visible.map((b, i) => b.kind === "text"
            ? <p key={i} className="wl-note">{b.text.trim()}</p>
            : b.kind === "lead" ? <div key={i} className="wl-step wl-lead">{b.text}</div>
            : b.kind === "step" ? <StepRow key={i} s={b} show={investigate} /> : null)}
        </div>)}
    </div>
  );
}

export default function TurnView({ turn, actions, devices, onFollowUp }: {
  turn: AgentTurn; actions: Action[]; devices: Device[]; onFollowUp: (turnId: string) => void;
}) {
  // The answer is the last thing said; words said before or between steps are commentary in a work log. Everything
  // keeps its order: a card appears where it was put up, between the steps around it.
  const blocks = withLead(turn.blocks);
  let final = -1;
  blocks.forEach((b, i) => { if (b.kind === "text" && b.text.trim()) final = i; });
  const parts: JSX.Element[] = [];
  let seg: Block[] = [];
  const lastStep = blocks.reduce((n, b, i) => b.kind === "step" ? i : n, -1);
  const flush = (i: number) => {
    if (!seg.length) return;
    const blocks = seg;
    seg = [];
    if (blocks.some((b) => b.kind === "step")) {
      const isLast = i > lastStep; // the segment holding the last step carries the turn's totals
      parts.push(<WorkLog key={`log${i}`} blocks={blocks} busy={turn.busy && isLast}
        investigate={turn.mode === "investigate"} ms={isLast ? turn.ms : undefined}
        metrics={isLast ? turn.metrics : undefined} />);
    } else {
      blocks.forEach((b, j) => b.kind === "text" && parts.push(<p key={`n${i}.${j}`} className="wl-note">{b.text.trim()}</p>));
    }
  };
  blocks.forEach((b, i) => {
    if (b.kind === "card") {
      flush(i);
      const a = actions.find((x) => x.id === b.actionId);
      parts.push(<ApprovalCard key={b.actionId} action={a} device={devices.find((d) => d.id === a?.deviceId)}
        onFollowUp={onFollowUp} />);
    } else if (i === final) {
      flush(i);
      parts.push(<div key="answer" className="bubble agent">{(b as { text: string }).text.trim()}</div>);
    } else {
      seg.push(b);
    }
  });
  flush(blocks.length);
  return (
    <div className={`turn agent ${turn.past ? "past" : ""}`}>
      {turn.mode === "investigate" && <span className="pill turn-mode">Investigated</span>}
      {parts}
      {/* an answer with no steps still says what it took */}
      {!turn.busy && lastStep < 0 && final >= 0 && receipt(turn.ms, turn.metrics) &&
        <div className="wl-receipt small muted">Answered from what I know · {receipt(turn.ms, turn.metrics)}</div>}
      {turn.busy && final < 0 && lastStep < 0 && <div className="bubble agent thinking">Thinking…</div>}
      {turn.error && <div className="turn-error small">{/[ .]/.test(turn.error) ? turn.error : `Problem: ${turn.error}`}</div>}
    </div>
  );
}

/** The line above a follow-up: what it continues, from the actions themselves (nothing extra is stored). */
export function afterLine(ids: string[] | undefined, actions: Action[], devices: Device[]): string | null {
  const a = actions.find((x) => ids?.includes(x.id) && (x.result || ["approved", "running"].includes(x.status)));
  if (!a) return null;
  const dev = devices.find((d) => d.id === a.deviceId)?.name ?? "the device";
  return a.result ? `${a.plan} · finished on the ${dev}: ${a.result.summary}` : `You approved: ${a.plan}`;
}
