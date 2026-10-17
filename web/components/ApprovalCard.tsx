"use client";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { passkeysSupported, signWithPasskey } from "@/lib/passkey";
import type { Action, Device } from "@/lib/types";

const RISK = { routine: "Safe", service: "Some risk", destructive: "Risky", read: "Read-only" } as const;
const SIGNED = new Set(["expert_command", "expert_grant"]); // approved only with the owner's passkey
const STATUS: Record<Action["status"], string> = {
  pending: "Waiting for you", approved: "Approved, waiting for the device…", running: "Running on the device…",
  done: "Done", failed: "Didn't work", denied: "Declined", stale: "Out of date",
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
  async function signIt() {
    setBusy(true); setErr("");
    try {
      const k = await api<{ enabled: boolean; credentialId?: string; rpId?: string }>("GET", "/api/expert");
      if (!k.enabled || !k.credentialId || !k.rpId) throw new Error("Create your passkey first (open the device > Expert sessions).");
      const challenge = (action!.params as { challenge?: string } | undefined)?.challenge ?? "";
      const signed = await signWithPasskey(challenge, k.credentialId, k.rpId);
      await api("POST", `/api/actions/${action!.id}/sign`, signed);
    } catch (e) {
      setErr(e instanceof ApiError ? (e.code === "signature_not_accepted" ? "That passkey didn't sign it." : e.code)
        : e instanceof Error ? e.message : "Couldn't sign it");
    } finally {
      setBusy(false);
    }
  }
  const command = (action.params as { command?: string } | undefined)?.command;
  const signedCard = SIGNED.has(action.type);
  return (
    <div className="card">
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <strong style={{ flex: 1 }}>{action.plan}</strong>
        <span className={`risk ${action.riskClass}`}>{RISK[action.riskClass]}</span>
      </div>
      <dl>
        {command && <><dt>Command</dt><dd><code className="perm-cmd">{command}</code></dd></>}
        <dt>What happens</dt><dd>{action.dryRun}</dd>
        <dt>Touches</dt><dd>{device?.name ?? action.blastRadius.join(", ")}{device?.realm === "real" ? " (live device)" : " (sample)"}</dd>
        <dt>Undo</dt><dd>{action.rollback}</dd>
        <dt>Status</dt><dd>{STATUS[action.status]}{action.decision?.by === "auto" ? " (handled on its own, as you allowed)" : ""}</dd>
        {action.result && <><dt>Result</dt><dd>{action.result.summary}</dd></>}
      </dl>
      {action.status === "pending" && (
        <div className="actions">
          {signedCard
            ? <button className="primary" disabled={busy || !passkeysSupported()} onClick={signIt}>
                {busy ? "Waiting for your passkey…" : "Approve with passkey"}</button>
            : <button className="primary" disabled={busy} onClick={() => decide("approve")}>Approve</button>}
          <button disabled={busy} onClick={() => decide("deny")}>Not now</button>
        </div>
      )}
      {err && <div className="small" style={{ color: "var(--crit)" }}>{err}</div>}
    </div>
  );
}
