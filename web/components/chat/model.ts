// The chat as a list of turns, each agent turn a list of blocks in the order they happened: words, steps (what
// Nightlight checked or ran, and what came back) and approval cards. Live events and stored messages build the same
// shape, so a reloaded chat reads like the live one. UX spec 2026-10-17 §4.
import type { PastMessage, PastStep } from "@/lib/data";
import type { Device, StreamEvent } from "@/lib/types";

export type Mode = "quick" | "investigate";
export type StepStatus = "running" | "done" | "failed" | "stopped";

export type Block =
  | { kind: "text"; text: string }
  | { kind: "step"; name: string; label: string; command?: string; status: StepStatus; summary?: string;
      details?: string; startedAt: number; ms?: number }
  | { kind: "card"; actionId: string };

export type Turn =
  | { kind: "user"; key: string; text: string; past?: boolean }
  | { kind: "system"; key: string; text: string; icon: "mode" | "stopped" }
  // `after`: the actions whose result or approval this turn continues (shown as a system line above it)
  | { kind: "agent"; key: string; turnId?: string; mode: Mode; blocks: Block[]; busy: boolean; error?: string;
      past?: boolean; after?: string[]; ms?: number; stopped?: boolean };

export type AgentTurn = Extract<Turn, { kind: "agent" }>;

export const key = () => Math.random().toString(36).slice(2);

/** What a step is doing, in plain words. */
export function label(name: string, args: Record<string, unknown> | undefined, devices: Device[]): string {
  const id = (args?.device_id as string) ?? "";
  const dev = devices.find((d) => d.id === id)?.name ?? "the device";
  return ({
    list_fleet: "Looking over your home", get_device: `Checking the ${dev}`,
    get_recent_events: "Reading what happened recently", restart_container: `Preparing a fix for the ${dev}`,
    look_into: `Asking the ${dev} what happened to ${(args?.target as string) ?? "it"}`, remember: "Making a note",
    restart_service: `Preparing a fix for the ${dev}`, clean_up: `Preparing a clean-up for the ${dev}`,
    inspect: `Looking around the ${dev}`, run_playbook: `Running a checkup on the ${dev}`,
    write_note: `Noting what I learned about the ${dev}`, how_nightlight_works: "Checking how Nightlight does this",
    remove_device: `Preparing to remove the ${dev}`, update_helper: `Preparing the helper update for the ${dev}`,
    start_investigation: `Asking to investigate the ${dev}`, run_command: `Running a command on the ${dev}`,
    propose_command: `Preparing a command for the ${dev}`, update_profile: `Updating what I know about the ${dev}`,
    research: `Searching the web: ${(args?.question as string) ?? ""}`,
    link_devices: "Adding a line to your map",
  } as Record<string, string>)[name] ?? `Working on the ${dev}`;
}

function command(name: string, args?: Record<string, unknown>): string | undefined {
  return name === "run_command" || name === "propose_command" ? (args?.command as string) || undefined : undefined;
}

/** Older stored steps have no `ok`: their summary said so in words. */
function failed(ok: boolean | undefined, summary?: string) {
  return ok === false || (ok === undefined && !!summary?.startsWith("Couldn't"));
}

/** The next event of a live turn, applied to a copy of it. */
export function apply(t: AgentTurn, e: StreamEvent, devices: Device[]): AgentTurn {
  const blocks = [...t.blocks];
  const last = blocks[blocks.length - 1];
  switch (e.type) {
    case "turn_start":
      return { ...t, turnId: e.turnId, mode: e.mode ?? t.mode };
    case "text":
      if (last?.kind === "text") blocks[blocks.length - 1] = { ...last, text: last.text + e.delta };
      else blocks.push({ kind: "text", text: e.delta });
      return { ...t, blocks };
    case "tool_call":
      blocks.push({ kind: "step", name: e.name, label: label(e.name, e.args, devices),
        command: command(e.name, e.args), status: "running", startedAt: Date.now() });
      return { ...t, blocks };
    case "tool_result": {
      const i = blocks.findIndex((b) => b.kind === "step" && b.name === e.name && b.status === "running");
      if (i < 0) return t;
      const s = blocks[i] as Extract<Block, { kind: "step" }>;
      blocks[i] = { ...s, status: failed(e.ok, e.summary) ? "failed" : "done", summary: e.summary ?? "done",
        details: e.details ?? undefined, ms: e.ms ?? Date.now() - s.startedAt };
      return { ...t, blocks };
    }
    case "approval_request":
      if (blocks.some((b) => b.kind === "card" && b.actionId === e.actionId)) return t;
      return { ...t, blocks: [...blocks, { kind: "card", actionId: e.actionId }] };
    case "error": // the turn is over: a step still waiting will never answer
      return { ...stop(t), busy: t.busy, error: e.message || e.code };
    case "done":
      return { ...t, ms: e.metrics?.latencyMs };
    default:
      return t;
  }
}

/** Steps still running when the person stopped watching. */
export function stop(t: AgentTurn): AgentTurn {
  return { ...t, busy: false,
    blocks: t.blocks.map((b) => b.kind === "step" && b.status === "running" ? { ...b, status: "stopped" } : b) };
}

function pastStep(s: PastStep, devices: Device[]): Block {
  return { kind: "step", name: s.name, label: label(s.name, s.args, devices), command: command(s.name, s.args),
    status: s.unfinished ? "stopped" : failed(s.ok, s.summary) ? "failed" : "done", summary: s.summary,
    details: s.details, startedAt: 0,
    ms: s.ms };
}

/** Stored messages as turns. Steps go back where they happened in the text when the message says where (offsets
 * are UTF-16 units, as JavaScript slices), each card right after the step that made it; older messages (no
 * textOffset) show their steps before the answer, as the live chat used to. */
export function fromHistory(msgs: PastMessage[], devices: Device[]): Turn[] {
  const out: Turn[] = [];
  for (const m of msgs) {
    if (m.role === "user") { out.push({ kind: "user", key: m.id, text: m.text, past: true }); continue; }
    const blocks: Block[] = [];
    let at = 0;
    for (const s of m.toolCalls ?? []) {
      const cut = Math.min(Math.max(s.textOffset ?? 0, at), m.text.length);
      if (m.text.slice(at, cut).trim()) blocks.push({ kind: "text", text: m.text.slice(at, cut) });
      at = cut;
      blocks.push(pastStep(s, devices));
      if (s.actionId) blocks.push({ kind: "card", actionId: s.actionId });
    }
    if (m.text.slice(at).trim()) blocks.push({ kind: "text", text: m.text.slice(at) });
    for (const id of m.actionIds ?? []) {
      if (!blocks.some((b) => b.kind === "card" && b.actionId === id)) blocks.push({ kind: "card", actionId: id });
    }
    // An agent message right after another one is a follow-up: it continues that one's actions.
    const prev = out[out.length - 1];
    const after = prev?.kind === "agent"
      ? prev.blocks.flatMap((b) => b.kind === "card" ? [b.actionId] : []) : undefined;
    out.push({ kind: "agent", key: m.id, mode: m.mode ?? "quick", blocks, busy: false, past: true,
      error: m.error?.message, after });
  }
  return out;
}
