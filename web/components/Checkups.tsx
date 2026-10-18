"use client";
// Playbooks for a real device: an expert's steps for a known problem, run without the AI. The checks are read-only;
// any clean-up it finds comes up as an approval card under "Waiting for you".
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { chatSession } from "@/lib/session";
import type { Action, PlaybookOffer, PlaybookResult } from "@/lib/types";

const CARD: Partial<Record<Action["status"], string>> = {
  pending: "A clean-up card is waiting for you.", approved: "Approved; waiting for the device…",
  running: "Cleaning up on the device…", denied: "You declined the clean-up.", stale: "That clean-up card expired.",
};

/** What happened to a finding's clean-up, from the card itself (never assumed). */
function cardWords(f: PlaybookResult["found"][number], actions: Action[], cleanupOn: boolean): string {
  if (!f.fixAllowed) {
    return cleanupOn ? "This device doesn't offer that clean-up." : "Switch on \"Clean up space\" below to fix this with one tap.";
  }
  const card = f.card ? actions.find((a) => a.id === f.card) : undefined;
  if (!card) return f.card ? "Loading the card…" : "No card could be made this time; run the checkup again later.";
  if (card.status === "done" || card.status === "failed") return card.result?.summary ?? "Finished.";
  return CARD[card.status] ?? "";
}

export default function Checkups({ uid, generation, deviceId, actions, cleanupOn }: {
  uid: string; generation?: number; deviceId: string; actions: Action[]; cleanupOn: boolean;
}) {
  const [offers, setOffers] = useState<PlaybookOffer[] | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    setOffers(null);
    api<{ playbooks: PlaybookOffer[] }>("GET", `/api/devices/${deviceId}/playbooks`)
      .then((r) => setOffers(r.playbooks)).catch(() => setOffers([]));
  }, [deviceId]);

  const runs = actions.filter((a) => a.deviceId === deviceId && a.playbook)
    .sort((a, b) => (b.createdAt?.getTime() ?? 0) - (a.createdAt?.getTime() ?? 0));
  const last = runs[0];

  async function run(id: string) {
    setBusy(id);
    setError("");
    try {
      const sessionId = await chatSession(uid, generation);
      await api("POST", `/api/devices/${deviceId}/playbooks/${id}/run`, { sessionId });
    } catch (e) {
      setError(e instanceof ApiError && e.code === "device_not_reporting"
        ? "The device isn't reporting right now, so it can't be checked."
        : "Couldn't start the checkup. Please try again.");
    } finally {
      setBusy("");
    }
  }

  if (offers === null || offers.length === 0) return null;
  const pb = last?.result?.playbook;
  return (
    <section className="checkups">
      <div className="checkup-buttons">
        {offers.map((o) => (
          <button key={o.id} className={o.id === offers.find((x) => x.suggested)?.id ? "primary" : ""} // one suggestion leads disabled={!!busy} title={o.about}
            onClick={() => run(o.id)}>{busy === o.id ? "Starting…" : o.title}</button>))}
      </div>
      {error && <p className="small" style={{ color: "var(--crit-ink)" }}>{error}</p>}
      {last && !pb && ["approved", "running"].includes(last.status) &&
        <p className="small muted">Checking on the device… (updates can take up to a minute)</p>}
      {last && last.status === "failed" && <p className="small">The checkup couldn&apos;t finish: {last.result?.summary}</p>}
      {pb && (
        <div className="checkup-result small">
          <strong>{pb.title}</strong>
          {pb.found.map((f) => (
            <div key={f.cause} className="checkup-row">
              <div>{f.say}</div>
              {f.fix && <div className="muted">{cardWords(f, actions, cleanupOn)}</div>}
              {f.advice && <div className="muted">{f.advice}</div>}
            </div>))}
          {pb.nothing && <div className="muted">{pb.nothing}</div>}
        </div>
      )}
    </section>
  );
}
