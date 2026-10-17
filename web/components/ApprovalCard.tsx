"use client";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { challengeFor, passkeysSupported, signWithPasskey } from "@/lib/passkey";
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
      // The challenge is computed HERE from the payload this card displays, never taken from the server as is.
      const payload = (action!.params as { payload?: Record<string, unknown> } | undefined)?.payload;
      if (!payload) throw new Error("This card has nothing to sign.");
      if (payload.device !== action!.deviceId || payload.device !== device?.id) {
        throw new Error("This card's signed device doesn't match the device it shows. Not signed.");
      }
      if (typeof payload.expires !== "number" || payload.expires * 1000 - Date.now() > 16 * 60 * 1000) {
        throw new Error("This card asks for more than 15 minutes. Not signed.");
      }
      const signed = await signWithPasskey(await challengeFor(payload), k.credentialId, k.rpId);
      await api("POST", `/api/actions/${action!.id}/sign`, signed);
    } catch (e) {
      setErr(e instanceof ApiError ? (e.code === "signature_not_accepted" ? "That passkey didn't sign it." : e.code)
        : e instanceof Error ? e.message : "Couldn't sign it");
    } finally {
      setBusy(false);
    }
  }
  // What is shown is what gets signed: the command (or the grant) comes from the signed payload itself.
  const payload = (action.params as { payload?: { command?: string; mode?: string; expires?: number; device?: string } }
    | undefined)?.payload;
  const until = payload?.expires ? new Date(payload.expires * 1000).toLocaleString() : "";
  const command = payload?.command ? `${payload.command}   (valid until ${until})`
    : payload?.mode ? `${payload.mode} commands until ${until}`
    : (action.params as { command?: string } | undefined)?.command;
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
        <dt>Touches</dt><dd>{device?.name ?? action.blastRadius.join(", ")}{device?.realm === "real" ? " (live device)" : " (sample)"}
          {payload?.device && payload.device !== device?.id ? <strong style={{ color: "var(--crit)" }}> (signed for a different device!)</strong> : null}</dd>
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
