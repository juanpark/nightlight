"use client";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Action, Device } from "@/lib/types";

const RISK = { routine: "Safe", service: "Some risk", destructive: "Risky" } as const;
const STATUS: Record<Action["status"], string> = {
  pending: "Waiting for you", approved: "Approved, waiting for the device…", running: "Running on the device…",
  done: "Done", failed: "Didn't work: nothing was changed", denied: "Declined", stale: "Out of date",
};

export default function ApprovalCard({ action, device, onFollowUp }: {
  action: Action | undefined; device?: Device; onFollowUp: (turnId: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const followed = useRef(false);

  // A real-device job finishes later (the helper runs it); its follow-up turn appears on the action when it does.
  useEffect(() => {
    if (action?.continuationTurnId && !followed.current && action.decision?.by === "user"
        && ["done", "failed"].includes(action.status) && action.realm === "real") {
      followed.current = true;
      onFollowUp(action.continuationTurnId);
    }
  }, [action, onFollowUp]);

  if (!action) return <div className="card muted small">Loading the card…</div>;
  async function decide(decision: "approve" | "deny") {
    setBusy(true); setErr("");
    try {
      const r = await api<{ status: string; continuationTurnId?: string }>("POST", `/api/actions/${action!.id}/decide`,
        { decision });
      if (r.continuationTurnId) { followed.current = true; onFollowUp(r.continuationTurnId); }
    } catch (e) {
      setErr(e instanceof ApiError ? e.code : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card">
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <strong style={{ flex: 1 }}>{action.plan}</strong>
        <span className={`risk ${action.riskClass}`}>{RISK[action.riskClass]}</span>
      </div>
      <dl>
        <dt>What happens</dt><dd>{action.dryRun}</dd>
        <dt>Touches</dt><dd>{device?.name ?? action.blastRadius.join(", ")}{device?.realm === "real" ? " (live device)" : " (sample)"}</dd>
        <dt>Undo</dt><dd>{action.rollback}</dd>
        <dt>Status</dt><dd>{STATUS[action.status]}{action.decision?.by === "auto" ? " (handled on its own, as you allowed)" : ""}</dd>
        {action.result && <><dt>Result</dt><dd>{action.result.summary}</dd></>}
      </dl>
      {action.status === "pending" && (
        <div className="actions">
          <button className="primary" disabled={busy} onClick={() => decide("approve")}>Approve</button>
          <button disabled={busy} onClick={() => decide("deny")}>Not now</button>
        </div>
      )}
      {err && <div className="small" style={{ color: "var(--crit)" }}>{err}</div>}
    </div>
  );
}
