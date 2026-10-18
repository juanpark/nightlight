"use client";
// The status board: one block per device, a ✓ ! ✗ ? line per check, and the count on top. Built in the browser from
// what devices last reported (lib/board.ts); no model call. Apps that are fine share one line, as in an ops script.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useServicesState } from "@/lib/data";
import { boardText, count, deviceBlock, GLYPH, summary, websiteBlock, type Block, type Line } from "@/lib/board";
import type { Device, Service, Watch } from "@/lib/types";

/** Loads one device's apps and hands them up (null until they have loaded). */
function Feed({ uid, id, onRows }: { uid: string; id: string; onRows: (id: string, rows: Service[] | null) => void }) {
  const { rows, loaded } = useServicesState(uid, id);
  useEffect(() => { onRows(id, loaded ? rows : null); }, [id, rows, loaded, onRows]);
  return null;
}

function stamp(d: Date) {
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  return new Date().toDateString() === d.toDateString() ? hm : `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${hm}`;
}

const Mark = ({ l }: { l: Line }) => <span className={`sb-mark ${l.mark}`} aria-label={l.mark}>{GLYPH[l.mark]}</span>;

function BlockView({ b, onSelect }: { b: Block; onSelect?: (id: string) => void }) {
  const fine = b.lines.filter((l) => l.app && l.mark === "ok");
  const rest = b.lines.filter((l) => !(l.app && l.mark === "ok"));
  return (
    <section className="sb-block">
      <h4>
        {onSelect ? <button className="linkish" onClick={() => onSelect(b.id)}>{b.name}</button> : b.name}
        <span className="sb-at">{b.at ? stamp(b.at) : "no report yet"}</span>
      </h4>
      <ul>
        {rest.map((l, i) => <li key={i}><Mark l={l} /><span className="sb-label">{l.label}</span><span className="sb-value">{l.value}</span></li>)}
        {fine.length > 0 && (
          <li><span className="sb-mark ok" aria-hidden>{GLYPH.ok}</span><span className="sb-label">Apps</span>
            <span className="sb-value sb-apps">{fine.map((l) => <span key={l.label}><Mark l={l} /> {l.label}</span>)}</span></li>)}
        {b.pending && <li className="muted"><span className="sb-mark unknown">…</span><span className="sb-label">Apps</span><span className="sb-value">loading</span></li>}
      </ul>
    </section>
  );
}

export default function StatusBoard({ uid, devices, watches, now, onSelect }: {
  uid: string; devices: Device[]; watches: Watch[]; now: number; onSelect?: (id: string) => void;
}) {
  const [apps, setApps] = useState<Record<string, Service[] | null>>({});
  const onRows = useCallback((id: string, rows: Service[] | null) => setApps((a) => a[id] === rows ? a : { ...a, [id]: rows }), []);
  const [copied, setCopied] = useState(false);
  const blocks = useMemo(() => {
    const out = devices.filter((d) => !d.archived).map((d) => deviceBlock(d, d.kind === "watched" ? [] : apps[d.id] ?? null, now));
    const web = websiteBlock(watches, now);
    return web ? [...out, web] : out;
  }, [devices, watches, apps, now]);
  const c = count(blocks);
  const worst = c.crit ? "crit" : c.warn ? "warn" : c.unknown ? "unknown" : "ok";
  return (
    <div className="panel status-board">
      {devices.filter((d) => d.kind !== "watched").map((d) => <Feed key={d.id} uid={uid} id={d.id} onRows={onRows} />)}
      <div className="sb-head">
        <strong className={`sb-summary ${worst}`}>{summary(c)}</strong>
        <span className="small muted">From what each device last reported. No AI involved.</span>
        <span className="spacer" />
        <button className="small" onClick={() => navigator.clipboard.writeText(boardText(blocks, c, stamp))
          .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }, () => {})}>{copied ? "Copied" : "Copy"}</button>
      </div>
      <div className="sb-grid">{blocks.map((b) => <BlockView key={b.id} b={b} onSelect={b.id === "_websites" ? undefined : onSelect} />)}</div>
    </div>
  );
}
