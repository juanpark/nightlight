"use client";
// The chat's context strip: the devices the current (or last) answer's steps touched, each with how it is going, so a
// phone (where the chat covers the map) still sees what Nightlight is looking at. A tap shows that device on the map.
import { followShow, stepState, useFollowed, type StepState } from "@/lib/follow";
import type { Device } from "@/lib/types";

const WORDS: Record<StepState, string> = { checking: "checking…", found: "found something", done: "done ✓" };

export default function ContextStrip({ devices, onShow }: { devices: Device[]; onShow?: () => void }) {
  const f = useFollowed();
  const shown = f.devices.map((id) => devices.find((d) => d.id === id)).filter((d): d is Device => !!d);
  if (!shown.length) return null;
  return (
    <div className="ctx-strip" role="list" aria-label={f.done ? "Devices the last answer looked at" : "Devices Nightlight is looking at"}>
      {shown.map((d) => {
        const st = stepState(f, d.id) ?? (f.done ? "done" : "checking");
        const note = f.steps[d.id]?.note;
        return (
          <button key={d.id} role="listitem" className={`ctx-chip ${st} ${d.status}`} title={note ? `${d.name}: ${note}` : d.name}
            onClick={() => { followShow(d.id); onShow?.(); }}>
            <span className="ctx-dot" aria-hidden /><span className="ctx-name">{d.name}</span>
            <span className="ctx-state">{WORDS[st]}</span>
          </button>);
      })}
    </div>
  );
}
