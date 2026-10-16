// Shapes from docs/API.md (Firestore documents and stream events). Only the fields the UI uses.

export type Status = "ok" | "warn" | "crit" | "offline";
export type RiskClass = "routine" | "service" | "destructive";
export type Level = "ask" | "ask_new" | "auto";

export interface Finding {
  id?: string;
  check: string;
  severity: "crit" | "warn" | "info";
  message: string;
  evidence?: string;
  svcId?: string;
  state?: "new" | "known" | "snoozed";
}

export interface Service {
  id: string;
  name: string;
  status?: Status;
  category?: string;
  kind?: string;
  version?: string | null;
  latestVersion?: string;
  updateAvailable?: boolean;
  players?: { online: number; max: number };
  lastBackupDaysAgo?: number;
  detail?: string | null;
  findings?: Finding[];
}

export interface Device {
  id: string;
  name: string;
  kind?: string;
  purpose?: string;
  status: Status;
  health?: "verified" | "unknown";
  vitals?: { cpu?: number | null; mem?: number | null; diskPct?: number | null; uptime?: number | null };
  findings?: Finding[];
  x?: number;
  y?: number;
  simulated?: boolean;
  realm?: "sim" | "real";
  demoGeneration?: number;
  lastSeen?: Date | null;
  revoked?: boolean;
  allowedJobs?: Record<string, string[]>;
  os?: string;
  arch?: string;
  helperVersion?: string;
  updatesPending?: number | null;
  containerCount?: number;
  containersRunning?: number;
  createdAt?: Date | null;
  tags?: string[];
}

export interface Action {
  id: string;
  type: string;
  deviceId: string;
  svcId?: string | null;
  plan: string;
  dryRun: string;
  blastRadius: string[];
  rollback: string;
  riskClass: RiskClass;
  status: "pending" | "approved" | "running" | "done" | "failed" | "denied" | "stale";
  realm?: "sim" | "real";
  demoGeneration?: number;
  decision?: { by: "user" | "auto"; decision: "approve" | "deny"; note?: string };
  result?: { ok: boolean; summary: string };
  continuationTurnId?: string;
  createdAt?: Date | null;
}

export interface TrustDoc {
  id: string;
  actionType: string;
  label: string;
  level: Level;
  pinned?: boolean;
  ceiling: Level;
  riskClass: RiskClass;
  successes?: string[];
  demoGeneration?: number;
  offer?: { offerId: string; text: string; demoGeneration: number } | null;
}

export interface EventDoc {
  id: string;
  deviceId?: string | null;
  kind: string;
  severity: "crit" | "warn" | "info";
  message: string;
  at?: Date | null;
  demoGeneration?: number;
  realm?: "real";
  who?: "you" | "device" | "auto" | "nightlight";
}

/** One history point for a real device: `users/{uid}/devices/{deviceId}/history/{YYYYMMDDTHHMMSS}`, at most one per
 * 5 minutes, kept 8 days. Percentages, or null when the device didn't report that value. */
export interface HistoryPoint {
  id: string;
  at: Date | null;
  cpu: number | null;
  mem: number | null;
  disk: number | null;
  status: "ok" | "warn" | "crit";
  problems: number;
}

/** A web address Nightlight checks from the internet every 5 minutes: `users/{uid}/watches/{watchId}`.
 * "ok" means it answered below HTTP 500. */
export interface Watch {
  id: string;
  name: string;
  url: string;
  tags?: string[];
  status: "ok" | "crit" | "unknown";
  httpStatus?: number | null;
  latencyMs?: number | null;
  lastCheckedAt?: Date | null;
  lastChange?: Date | null;
}

export interface UserDoc {
  demoGeneration: number;
  template?: "home-pi" | "empty";
  demo?: { state: "ready" | "resetting" };
  trustDefault?: Level;
  isDemo?: boolean;
}

export type StreamEvent =
  | { type: "turn_start"; turnId: string; replay?: boolean }
  | { type: "text"; delta: string }
  | { type: "tool_call"; name: string; args?: Record<string, unknown> }
  | { type: "tool_result"; name: string; summary?: string }
  | { type: "approval_request"; actionId: string }
  | { type: "followup_pending"; turnId: string }
  | { type: "error"; code: string; message: string; retryable?: boolean }
  | { type: "done"; turnId: string; metrics?: Record<string, number> };

export interface FoundItem { cid: string; guess: string; vendor?: string | null; services: string[]; ports: number[];
  added?: boolean }
export interface Discovery { id: string; by: string; byName: string; items: FoundItem[]; at?: Date | null;
  expiresAt?: Date | null }
