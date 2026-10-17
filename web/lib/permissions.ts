// Permission values shared by the switches, the presets and the "needs you" list (pure, no React).
import type { Permissions as Perms } from "./types";

export const DEFAULTS: Perms = { diagnose: true, cleanup: false, updates: true, autoUpdate: false, logs: [],
  restart_container: [], restart_service: [] };

export function normal(p?: Partial<Perms> | null): Perms {
  return {
    diagnose: p?.diagnose ?? DEFAULTS.diagnose,
    cleanup: p?.cleanup ?? false,
    updates: p?.updates ?? true,
    autoUpdate: p?.autoUpdate ?? false,
    logs: p?.logs ?? [],
    restart_container: p?.restart_container ?? [],
    restart_service: p?.restart_service ?? [],
  };
}

export const sameSet = (a: string[], b: string[]) => {
  const x = new Set(a), y = new Set(b);
  return x.size === y.size && [...x].every((v) => y.has(v));
};

export const samePerms = (a: Perms, b: Perms) => a.diagnose === b.diagnose && a.cleanup === b.cleanup
  && a.updates === b.updates && a.autoUpdate === b.autoUpdate && sameSet(a.logs, b.logs)
  && sameSet(a.restart_container, b.restart_container) && sameSet(a.restart_service, b.restart_service);

/** True when what the device reports applying matches the owner's switches ("*" on the device means everything). */
export function applied(want: Perms, jobs: Record<string, string[]> = {}, nothingHere = false): boolean {
  const has = (k: string, names: string[]) => {
    const got = jobs[k] ?? [];
    return got.includes("*") ? names.length > 0 : sameSet(got, names);
  };
  // With nothing to check on the device, "check why" has nothing to apply: on and empty counts as applied.
  const diagnoseOk = want.diagnose === (jobs.diagnose?.length ?? 0) > 0 || (want.diagnose && nothingHere);
  const lookOk = want.diagnose || !jobs.inspect?.length; // the same switch covers looking around (helper 0.8+)
  const cleanOk = want.cleanup === (jobs.fix?.length ?? 0) > 0;
  return diagnoseOk && lookOk && cleanOk && has("logs", want.logs)
    && has("restart_container", want.restart_container) && has("restart_service", want.restart_service);
}
