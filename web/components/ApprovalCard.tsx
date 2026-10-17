"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { challengeFor, passkeyProblem, passkeysSupported, signWithPasskey, useAppHost } from "@/lib/passkey";
import { useNow } from "@/lib/data";
import type { Action, Device } from "@/lib/types";
import { ArrowText, Caret, Declined, Done, NotDone, OutOfDate, type IconType } from "@/src/components/icons";

const RISK = { routine: "Safe", service: "Some risk", destructive: "Risky", read: "Read-only" } as const;
const SIGNED = new Set(["expert_command", "expert_grant"]); // approved only with the owner's passkey
const STATUS: Record<Action["status"], string> = {
  pending: "Waiting for you", approved: "Approved, waiting for the device…", running: "Running on the device…",
  done: "Done", failed: "Didn't work", denied: "Declined", stale: "Out of date",
};

// A settled card in the conversation folds to its outcome; the details stay one tap away.
const SETTLED: Partial<Record<Action["status"], { Icon: IconType; tone: string }>> = {
  done: { Icon: Done, tone: "done" }, failed: { Icon: NotDone, tone: "failed" },
  denied: { Icon: Declined, tone: "quiet" }, stale: { Icon: OutOfDate, tone: "quiet" },
};

export default function ApprovalCard({ action, device, onFollowUp, fold }: {
  action: Action | undefined; device?: Device; onFollowUp: (turnId: string) => void;
  fold?: boolean; // in the chat: once decided and finished, show one line
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const followed = useRef(false);
  const appHost = useAppHost();
  const now = useNow(5000);
  const payload0 = (action?.params as { payload?: Record<string, unknown> } | undefined)?.payload;
  const signable = !!action && SIGNED.has(action.type) && action.status === "pending";
  const expired = signable && typeof payload0?.expires === "number" && payload0.expires * 1000 <= now + 5000;
  // what the passkey prompt needs, worked out when the card shows (not on the tap)
  const [prep, setPrep] = useState<{ challenge: string; credentialId: string; rpId: string } | { problem: string } | null>(null);
  useEffect(() => {
    if (!signable || expired || !action) return;
    let live = true;
    (async () => {
      try {
        // The challenge is computed HERE from the payload this card displays, never taken from the server as is.
        const payload = payload0;
        if (!payload) throw new Error("This card has nothing to sign.");
        if (payload.device !== action.deviceId || payload.device !== device?.id) {
          throw new Error("This card's signed device doesn't match the device it shows. Not signed.");
        }
        if (typeof payload.expires !== "number" || payload.expires * 1000 - Date.now() > 16 * 60 * 1000) {
          throw new Error("This card asks for more than 15 minutes. Not signed.");
        }
        const [k, challenge] = await Promise.all([
          api<{ enabled: boolean; credentialId?: string; rpId?: string }>("GET", "/api/expert"), challengeFor(payload)]);
        if (!k.enabled || !k.credentialId || !k.rpId) {
          throw new Error("Make your passkey first: open a device, then Settings, then Expert sessions.");
        }
        if (live) setPrep({ challenge, credentialId: k.credentialId, rpId: k.rpId });
      } catch (e) {
        if (live) setPrep({ problem: passkeyProblem(e) });
      }
    })();
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action?.id, action?.status, signable, expired, device?.id, JSON.stringify(payload0 ?? null)]);

  // A real-device job finishes later (the helper runs it); its follow-up turn appears on the action when it does.
  useEffect(() => {
    // (the chat runs it only if its answer isn't already in the saved conversation, so a reload never repeats it)
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
      setErr(passkeyProblem(e));
    } finally {
      setBusy(false);
    }
  }
  // Safari (iPhone, iPad, Mac) only lets a tap open the passkey prompt if nothing slow happens first, so everything
  // the prompt needs is ready before the tap, and the prompt is the first thing the tap waits for.
  async function signIt() {
    if (!prep || "problem" in prep) return;
    setBusy(true); setErr("");
    try {
      const signed = await signWithPasskey(prep.challenge, prep.credentialId, prep.rpId);
      const r = await api<{ continuationTurnId?: string }>("POST", `/api/actions/${action!.id}/sign`, signed);
      if (r.continuationTurnId) { followed.current = true; onFollowUp(r.continuationTurnId); } // it carries on
    } catch (e) {
      setErr(passkeyProblem(e, appHost?.host));
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
  const settled = fold ? SETTLED[action.status] : undefined;
  const head = (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <strong style={{ flex: 1 }}><ArrowText text={action.plan} /></strong>
      <span className={`risk ${action.riskClass}`}>{RISK[action.riskClass]}</span>
    </div>
  );
  const facts = (
      <dl>
        {command && <><dt>Command</dt><dd><code className="perm-cmd">{command}</code></dd></>}
        <dt>What happens</dt><dd><ArrowText text={action.dryRun} /></dd>
        <dt>Touches</dt><dd>{device?.name ?? action.blastRadius.join(", ")}{device?.realm === "real" ? " (live device)" : " (sample)"}
          {payload?.device && payload.device !== device?.id ? <strong style={{ color: "var(--crit)" }}> (signed for a different device!)</strong> : null}</dd>
        <dt>Undo</dt><dd><ArrowText text={action.rollback} /></dd>
        <dt>Status</dt><dd>{STATUS[action.status]}{action.decision?.by === "auto" ? " (handled on its own, as you allowed)" : ""}</dd>
        {action.result && <><dt>Result</dt><dd><ArrowText text={action.result.summary} /></dd></>}
      </dl>
  );
  if (settled) {
    const { Icon, tone } = settled;
    return (
      <details className={`card folded ${tone}`}>
        <summary>
          <Icon size={18} weight="fill" aria-hidden />
          <span className="fold-text"><b>{STATUS[action.status]}</b> <ArrowText text={action.plan.trim().replace(/\.$/, "")} /></span>
          <Caret className="caret" size={12} aria-hidden /><span className="sr-only">Details</span>
        </summary>
        {facts}
      </details>
    );
  }
  return (
    <div className="card">
      {head}
      {facts}
      {action.status === "pending" && (
        <div className="actions">
          {signedCard
            ? expired ? null
              : appHost && !appHost.here ? null
              : !passkeysSupported() ? null
              : <button className="primary" disabled={busy || !prep || "problem" in prep} onClick={signIt}>
                  {busy ? "Waiting for your passkey…" : prep ? "Approve with passkey" : "Getting ready…"}</button>
            : <button className="primary" disabled={busy} onClick={() => decide("approve")}>Approve</button>}
          <button disabled={busy} onClick={() => decide("deny")}>Not now</button>
        </div>
      )}
      {action.status === "pending" && signedCard && (
        expired ? <div className="small muted">This card expired. Ask again and Nightlight will put up a fresh one.</div>
        : appHost && !appHost.here ? <div className="small muted">Passkeys work only at{" "}
            <a href={appHost.url}>{appHost.host}</a>. Open Nightlight there to approve this.</div>
        : !passkeysSupported() ? <div className="small muted">This browser can&apos;t use passkeys, so the button is off.
            Approve from a phone or computer that can (Safari, Chrome, Edge or Firefox, up to date).</div>
        : prep && "problem" in prep ? <div className="small" style={{ color: "var(--crit)" }}>{prep.problem}</div>
        : null)}
      {err && <div className="small" style={{ color: "var(--crit)" }}>{err}</div>}
    </div>
  );
}
