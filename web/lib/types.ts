// Shapes from docs/API.md (Firestore documents and stream events). Only the fields the UI uses.

export type Status = "ok" | "warn" | "crit" | "offline";
export type RiskClass = "routine" | "service" | "destructive" | "read";
export type Level = "ask" | "ask_new" | "auto";

export interface Finding {
  id?: string;
  check: string;
  severity: "crit" | "warn" | "info";
  message: string;
  evidence?: string;
  svcId?: string;
  state?: "new" | "known" | "snoozed";
  fix?: string; // a fix the page can offer itself: "discover" (Look nearby), "discover_on_device" (a line to run there)
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
  /** What it is, in a line, and which icon it gets (a key from a fixed set; see components/map/kinds.ts). */
  about?: { icon?: string; oneLiner?: string; source?: "catalog" | "agent" } | null;
  ports?: number[];
  /** For a failed system service (kind "system"): the exact unit name, e.g. "nginx.service". */
  unit?: string;
}

/** What the owner lets Nightlight do on an app-managed device (`devices/{id}.permissions`). Names are ones the
 * device reported: container names, and exact unit names for system services. */
export interface Permissions {
  diagnose: boolean;
  cleanup: boolean;
  updates: boolean;
  autoUpdate: boolean;
  logs: string[];
  restart_container: string[];
  restart_service: string[];
}

export interface Device {
  archived?: boolean;
  id: string;
  name: string;
  kind?: string;
  purpose?: string;
  status: Status;
  health?: "verified" | "unknown";
  vitals?: { cpu?: number | null; mem?: number | null; diskPct?: number | null; uptime?: number | null;
    latencyMs?: number | null }; // latencyMs: watched things
  findings?: Finding[];
  x?: number;
  y?: number;
  simulated?: boolean;
  realm?: "sim" | "real";
  demoGeneration?: number;
  lastSeen?: Date | null;
  starting?: boolean; // page only: a live demo machine that hasn't reported since this visit began
  permissionsAt?: Date | null; // when the owner last changed the switches
  revoked?: boolean;
  allowedJobs?: Record<string, string[]>;
  /** Reported by the helper: "app" lets the owner change permissions here; "strict" only on the device. Missing on
   * older helpers. */
  manage?: "app" | "strict";
  permissions?: Permissions;
  os?: string;
  arch?: string;
  helperVersion?: string;
  updatesPending?: number | null;
  containerCount?: number;
  containersRunning?: number;
  createdAt?: Date | null;
  tags?: string[];
  /** Watched things (kind "watched", added from Found nearby): what it is, who checks it and how. */
  role?: Role; roleSetBy?: "auto" | "user"; guess?: string; services?: string[]; ports?: number[];
  vendor?: string | null; maker?: string | null; model?: string | null; seenName?: string | null;
  nameFromSeen?: boolean;
  /** Starred by the owner: the device itself, and its apps by Service.id (at most 20). */
  favorite?: boolean; favoriteApps?: string[];
  checkPort?: number | null; watchedBy?: string | null; cid?: string;
  lastAnswerAt?: Date | null; // a watched thing's last successful check (lastSeen is the last check of any kind)
  net?: { self?: string | null; selves?: string[]; gateway?: string | null; hw?: string } | null; // keyed fingerprints, never addresses
  setupAt?: Date | null; setupPreset?: "watch" | "fix" | "custom"; // the owner's first choice of what it may do
  macFolders?: "allowed" | "declined" | null; // a Mac's personal folders (null: never asked); helper 0.9.23+
}
/** A place's name (`users/{uid}/places/{placeId}`, placeId = a router's fingerprint, `net.gateway`). */
export interface PlaceDoc { id: string; name: string }
export type Role = "router" | "printer" | "fileshare" | "smarthome" | "server" | "speaker" | "computer" | "other";

/** How two devices relate, drawn as a line on the map: connected through, backs up to, relies on, powered by. */
export type LinkKind = "network" | "backup" | "depends" | "power";
export interface Link { id: string; from: string; to: string; kind: LinkKind; realm?: "sim" | "real";
  demoGeneration?: number; createdAt?: Date; source?: "user" | "auto"; why?: string }

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
  result?: { ok: boolean; summary: string; playbook?: PlaybookResult };
  playbook?: string;
  params?: Record<string, unknown>;
  command?: string; // the exact command it runs, when it runs one (shown folded; the plan says it in words)
  continuationTurnId?: string;
  createdAt?: Date | null;
  decidedAt?: Date | null;
  finishedAt?: Date | null;
}

export interface PlaybookResult {
  id: string;
  title: string;
  found: { cause: string; say: string; advice?: string; fix?: string; fixAllowed?: boolean; card?: string | null }[];
  nothing: string | null;
}

export interface PlaybookOffer { id: string; title: string; about: string; suggested: boolean }

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
export interface Note {
  id: string;
  text: string;
  by: "nightlight" | "you";
  at: Date | null;
  service?: string | null; // a note about one container or service on the device
  svcId?: string | null; // that app's Service.id, when known
}

/** A fix that worked on a device, as steps (`users/{uid}/devices/{id}/runbooks/{runbookId}`); never runs by itself. */
export interface Runbook {
  id: string; title: string; when: string; service?: string | null; svcId?: string | null; uses?: number; lastUsedAt?: Date | null;
  steps: { say: string; job?: { type: string; params?: Record<string, unknown> }; command?: string }[];
  createdAt?: Date | null; demoGeneration?: number;
}

/** One finished job on a device (`GET /api/devices/{id}/log`). */
export interface LogJob {
  at: string; kind: string; title: string; ok: boolean; summary?: string; by: "you" | "nightlight" | "device";
  actionId: string; service?: string | null; output?: string | null; command?: string | null;
}

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
  settings?: { deviceNames?: boolean }; // deviceNames missing: on
}

export type StreamEvent =
  | { type: "turn_start"; turnId: string; replay?: boolean; mode?: "quick" | "investigate"; budgetSeconds?: number }
  | { type: "text"; delta: string }
  | { type: "tool_call"; name: string; args?: Record<string, unknown>; callId?: string }
  | { type: "tool_result"; name: string; callId?: string; summary?: string; details?: string | null; ok?: boolean; ms?: number | null }
  | { type: "approval_request"; actionId: string }
  | { type: "followup_pending"; turnId: string }
  | { type: "error"; code: string; message: string; retryable?: boolean }
  | { type: "done"; turnId: string; metrics?: Metrics };

export interface FoundItem { cid: string; guess: string; vendor?: string | null; services: string[]; ports: number[];
  added?: boolean }
/** One thing found nearby, merged across the devices that saw it (`GET /api/found`). */
export interface FoundThing { guess: string; vendor?: string | null; name?: string | null; maker?: string | null;
  model?: string | null; services: string[]; ports: number[];
  tag?: string | null; seenBy: { deviceId: string; name: string; cid: string; canWatch?: boolean }[];
  router?: boolean; privateAddress?: boolean }
export interface Discovery { id: string; by: string; byName: string; items: FoundItem[]; at?: Date | null;
  expiresAt?: Date | null }

/** What one answer took: from the stream's `done`, and on stored messages once the server keeps them there. */
export interface Metrics { latencyMs?: number; toolCalls?: number; modelCalls?: number; costUsd?: number; model?: string;
  budgetSeconds?: number; slowCalls?: number }
