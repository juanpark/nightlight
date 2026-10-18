"use client";
// Getting started: five steps derived from what already exists (nothing stored but "hide" and "skip"). No step
// blocks the app; it disappears when all are done or the person hides it. UX spec 2026-10-17 §3.1.
import { useEffect, useState } from "react";
import type { Go } from "@/lib/needsYou";
import type { Device, Discovery } from "@/lib/types";
import { DEFAULTS, normal, samePerms } from "@/lib/permissions";
import { chosePreset } from "./Permissions";

type State = "todo" | "doing" | "done";

function read(k: string) { try { return localStorage.getItem(k); } catch { return null; } }
function write(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* this visit only */ } }

export default function FirstRun({ uid, devices, discoveries, expert, onAdd, onWatch, onSample, onGo }: {
  uid: string; devices: Device[]; discoveries: Discovery[]; expert: { enabled: boolean } | null;
  onAdd: () => void; onWatch: () => void; onSample: () => void; onGo: (g: Go) => void;
}) {
  const [hidden, setHidden] = useState(true); // until localStorage is read, so it never flashes
  const [skipped, setSkipped] = useState(false);
  useEffect(() => {
    setHidden(read(`nl_firstrun_dismissed_${uid}`) === "1");
    setSkipped(read(`nl_firstrun_expert_skip_${uid}`) === "1");
  }, [uid]);

  const real = devices.filter((d) => d.realm === "real" && d.kind !== "watched");
  const first = real[0];
  const reported = real.find((d) => d.lastSeen);
  // chose: the first-connection card saved a choice (setupAt), or older signs of one (a preset picked, changed switches)
  const chose = real.some((d) => d.setupAt || d.manage !== "app" || chosePreset(d.id)
    || !samePerms(normal(d.permissions), DEFAULTS));
  const expertOn = real.some((d) => (d.allowedJobs?.expert ?? []).includes("on"));
  const steps: { title: string; state: State; optional?: boolean; cta?: { label: string; run: () => void };
    note?: string }[] = [
    { title: "Add your first device with one line", state: first ? "done" : "todo",
      cta: { label: "Get my line", run: onAdd } },
    { title: "Watch it appear", state: reported ? "done" : first ? "doing" : "todo",
      note: first && !reported ? "Waiting for your device…" : undefined },
    { title: "Choose how much it may do", state: chose ? "done" : first ? "doing" : "todo",
      cta: first ? { label: "Choose", run: () => onGo({ to: "drawer", deviceId: first.id, tab: "settings" }) } : undefined },
    { title: "Find more devices nearby", optional: true,
      state: discoveries.length > 0 || real.length > 1 ? "done" : "todo",
      cta: { label: "How", run: () => onGo({ to: "panel", panel: "found" }) } },
    { title: "Later, if you like: deeper checks approved with your face or fingerprint (Expert sessions, with a passkey)",
      optional: true,
      state: skipped || (expert?.enabled && expertOn) ? "done" : expert?.enabled || expertOn ? "doing" : "todo",
      cta: first ? { label: "Set up", run: () => onGo({ to: "drawer", deviceId: first.id, tab: "settings" }) } : undefined },
  ];
  const done = steps.filter((s) => s.state === "done").length;
  if (hidden || done === steps.length) return null;
  return (
    <div className="panel firstrun">
      <div className="firstrun-head">
        <strong>Getting started · {done} of {steps.length}</strong>
        <span className="spacer" />
        <button className="linkish small" onClick={() => { write(`nl_firstrun_dismissed_${uid}`, "1"); setHidden(true); }}>
          Hide this</button>
      </div>
      <ol className="firstrun-steps">
        {steps.map((s, i) => (
          <li key={i} className={s.state}>
            <span className={`fr-mark ${s.state}`}>{s.state === "done" ? "✓" : i + 1}</span>
            <span className="fr-title">{s.title}{s.optional && <span className="muted small"> · optional</span>}
              {s.note && <span className="muted small"> · {s.note}</span>}</span>
            {s.state !== "done" && s.cta && <button className="small" onClick={s.cta.run}>{s.cta.label}</button>}
            {i === 4 && s.state !== "done" && <button className="linkish small" onClick={() => {
              write(`nl_firstrun_expert_skip_${uid}`, "1"); setSkipped(true); }}>Skip</button>}
          </li>
        ))}
      </ol>
      {!first && (
        <p className="small muted firstrun-alt">
          Not ready to install anything? <button className="linkish" onClick={onWatch}>Watch a website first</button>
          {" "}or <button className="linkish" onClick={onSample}>look around the sample home</button>.
        </p>
      )}
    </div>
  );
}
