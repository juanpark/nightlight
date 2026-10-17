"use client";
// One agent turn: a work log of what Nightlight checked (its running commentary, each step and what came back), then
// its answer, then any approval cards. Quick answers keep the log folded; investigations show it open.
import { useState } from "react";
import type { Action, Device } from "@/lib/types";
import ApprovalCard from "../ApprovalCard";
import type { AgentTurn, Block } from "./model";

type Step = Extract<Block, { kind: "step" }>;

const secs = (ms?: number) => ms == null ? "" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;

function StepRow({ s }: { s: Step }) {
  const more = !!(s.command || s.details);
  const line = (
    <>
      <span className={`wl-dot ${s.status}`} aria-label={s.status} />
      <span className="wl-label">{s.label}</span>
      {s.summary && <span className="wl-summary"> — {s.summary}</span>}
      {s.status === "stopped" && <span className="wl-summary muted"> — stopped watching</span>}
      {s.ms != null && s.status !== "running" && <span className="wl-ms">{secs(s.ms)}</span>}
    </>
  );
  if (!more) return <div className="wl-step">{line}</div>;
  return (
    <details className="wl-step">
      <summary>{line}</summary>
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
        <span className="wl-chev">{open ? "▾" : "▸"}</span>
        {busy ? `Working… ${n}` : `What I checked · ${n}${ms ? ` · ${secs(ms)}` : ""}`}
      </button>
      {visible.length > 0 && (
        <div className="wl-body">
          {visible.map((b, i) => b.kind === "text"
            ? <p key={i} className="wl-note">{b.text.trim()}</p>
            : b.kind === "step" ? <StepRow key={i} s={b} /> : null)}
        </div>)}
    </div>
  );
}

export default function TurnView({ turn, actions, devices, onFollowUp }: {
  turn: AgentTurn; actions: Action[]; devices: Device[]; onFollowUp: (turnId: string) => void;
}) {
  // The answer is the last thing said; words said before or between steps are commentary in the log.
  let final = -1;
  turn.blocks.forEach((b, i) => { if (b.kind === "text" && b.text.trim()) final = i; });
  const log = turn.blocks.filter((b, i) => b.kind !== "card" && i !== final);
  const hasSteps = log.some((b) => b.kind === "step");
  const cards = turn.blocks.flatMap((b) => b.kind === "card" ? [b.actionId] : []);
  return (
    <div className={`turn agent ${turn.past ? "past" : ""}`}>
      {turn.mode === "investigate" && <span className="pill turn-mode">Investigated</span>}
      {hasSteps && <WorkLog blocks={log} busy={turn.busy} investigate={turn.mode === "investigate"} ms={turn.ms} />}
      {!hasSteps && log.map((b, i) => b.kind === "text" ? <p key={i} className="wl-note">{b.text.trim()}</p> : null)}
      {final >= 0
        ? <div className="bubble agent">{(turn.blocks[final] as { text: string }).text.trim()}</div>
        : turn.busy && !hasSteps && <div className="bubble agent thinking">Thinking…</div>}
      {cards.map((id) => {
        const a = actions.find((x) => x.id === id);
        return <ApprovalCard key={id} action={a} device={devices.find((d) => d.id === a?.deviceId)} onFollowUp={onFollowUp} />;
      })}
      {turn.error && <div className="turn-error small">Problem: {turn.error}</div>}
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
