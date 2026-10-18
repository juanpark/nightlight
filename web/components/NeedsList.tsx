"use client";
// Rows of "needs you" items with one action each. Used at the top of a device panel and in the strip above the map.
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { Go, Need } from "@/lib/needsYou";
import type { Action, Device } from "@/lib/types";
import { useDismissed } from "@/lib/needsYou";
import ApprovalCard from "./ApprovalCard";
import { Copy } from "./AddDevice";
import { ArrowText, Caret } from "@/src/components/icons";
import StatusWord, { needTone } from "./StatusWord";
import { useWorkingOn } from "@/lib/follow";

export default function NeedsList({ needs, actions, devices, onGo, onFollowUp, max = 3, showDevice = false, plain = false,
  fold = false, extra }: {
  needs: Need[]; actions: Action[]; devices: Device[]; onGo: (go: Go) => void; onFollowUp: (turnId: string) => void;
  max?: number; showDevice?: boolean; plain?: boolean; extra?: (n: Need) => ReactNode; // more controls at the end of a row
  fold?: boolean; // the strip: the worst item always shows, the rest fold under a line that says what is there
}) {
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [unfolded, setUnfolded] = useUnfolded();
  const [, dismiss] = useDismissed();
  const working = useWorkingOn();
  if (!needs.length) return null;
  const folding = fold && needs.length > 1;
  const shown = folding || all ? needs : needs.slice(0, max);
  const name = (id?: string) => devices.find((d) => d.id === id)?.name;
  // one primary button per list: the worst item's; the rest stay quiet
  const lead = shown[0]?.id;
  const kind = (n: Need) => n.id === lead ? "primary small" : "small";
  const row = (n: Need) => {
    const { tone, word } = needTone(n);
    const device = showDevice ? name(n.deviceId) : undefined;
    // the strip says it plainly; the exact figures ("/ at 94% of 6.4 GB") stay in the device panel
    const detail = n.detail && !(plain && (n.kind === "critical" || n.kind === "approve")) ? n.detail : null;
    return (
    <div key={n.id} className={`needs-item ${working(n.deviceId) ? "working" : ""}`}>
      <div className="needs-row">
        <StatusWord tone={tone} word={word} className="needs-status" />
        <span className="needs-text">
          {device && n.deviceId && <button className="needs-device" onClick={() => onGo({ to: "drawer", deviceId: n.deviceId! })}
            aria-label={`Open ${device}`}>{device}</button>}
          {working(n.deviceId) && <span className="working-tag" role="status">Nightlight is checking…</span>}
          <span className="needs-title"><ArrowText text={n.title} /></span>
          {detail && <span className="needs-detail"><ArrowText text={detail} /></span>}
        </span>
        <span className="needs-actions">
        {n.cta.go.to === "offer"
          ? <>
              <button className={kind(n)} onClick={() => offer(n.cta.go, true)}>Yes, handle it</button>
              <button className="small" onClick={() => offer(n.cta.go, false)}>Keep asking me</button>
            </>
          : n.cta.go.to === "card" || n.cta.go.to === "line"
            ? <button className={kind(n)} aria-expanded={open === n.id}
                onClick={() => setOpen(open === n.id ? null : n.id)}>{open === n.id ? "Hide" : n.cta.label}</button>
            : <button className={kind(n)} onClick={() => onGo(n.cta.go)}>{n.cta.label}</button>}
        {n.kind === "duplicate" && <button className="small" onClick={() => dismiss(n.id)}>Keep both</button>}
        {extra?.(n)}
        </span>
      </div>
      {open === n.id && n.cta.go.to === "line" && (
        <div className="needs-line small">
          On the removed device, run:
          <Copy text={`curl -fsSL ${window.location.origin}/uninstall.sh | sh`} />
          <button className="small" onClick={() => dismiss(n.id)}>Done, I ran it</button>
        </div>)}
      {open === n.id && n.cta.go.to === "card" && (() => {
        const a = actions.find((x) => x.id === (n.cta.go as { actionId: string }).actionId);
        return <ApprovalCard action={a} device={devices.find((d) => d.id === a?.deviceId)} onFollowUp={onFollowUp} />;
      })()}
    </div>
    );
  };
  if (folding) {
    const rest = needs.slice(1);
    const urgent = rest.filter((n) => n.priority === 1).length;
    const names = [...new Set(rest.map((n) => name(n.deviceId)).filter(Boolean))];
    return (
      <div className="needs-list">
        {row(needs[0])}
        <div className="needs-more" id="needs-more" data-open={unfolded || undefined} inert={!unfolded}>
          <div>{rest.map(row)}</div>
        </div>
        <button className="needs-fold" aria-expanded={unfolded} aria-controls="needs-more" onClick={() => setUnfolded(!unfolded)}>
          <span className="needs-fold-what">{unfolded ? "Show less"
            : <>{rest.length} more{urgent > 0 && <b className="needs-fold-urgent">, {urgent} urgent</b>}
                {names.length > 0 && <span className="needs-fold-names"> · {names.join(", ")}</span>}</>}</span>
          <span className="needs-fold-cta">{unfolded ? "" : "Show all"}<Caret className="caret" size={12} aria-hidden /></span>
        </button>
      </div>
    );
  }
  return (
    <div className="needs-list">
      {shown.map(row)}
      {needs.length > max && <button className="linkish small" onClick={() => setAll(!all)}>
        {all ? "Show fewer" : `Show all ${needs.length}`}</button>}
    </div>
  );
}

/** Whether the strip shows every item, remembered in this browser (folded until the person opens it). */
function useUnfolded(): [boolean, (v: boolean) => void] {
  const [v, setV] = useState(false);
  useEffect(() => { try { setV(localStorage.getItem("nl_needs_open") === "1"); } catch { /* folded */ } }, []);
  return [v, (next: boolean) => { setV(next); try { localStorage.setItem("nl_needs_open", next ? "1" : "0"); } catch { /* this visit */ } }];
}

function offer(go: Go, accept: boolean) {
  if (go.to !== "offer") return;
  api("POST", `/api/trust/${go.actionType}/promotion`, { accept, offerId: go.offerId }).catch(() => {});
}
