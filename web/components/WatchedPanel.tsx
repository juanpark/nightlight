"use client";
// The device panel for a thing a helper watches (a router, a printer, a NAS without the helper…). Nightlight only
// knows whether it answers and what it answered on, so this says that plainly, lets the person say what it is, shows
// when it was reachable today, and offers the way to see more (install the helper) or to stop watching it.
import { useState } from "react";
import { api } from "@/lib/api";
import { useEvents, useLinks, useNow } from "@/lib/data";
import { answering, when, type Go } from "@/lib/needsYou";
import type { Device, EventDoc, Role } from "@/lib/types";
import { ROLES, roleOf } from "./map/kinds";

const PORTS: Record<number, string> = { 22: "remote login", 80: "web page", 443: "secure web page", 445: "file sharing",
  631: "printer", 8123: "Home Assistant", 25565: "Minecraft", 32400: "Plex" };
const UP = new Set(["status_ok", "watch_ok", "back"]), DOWN = new Set(["status_crit", "watch_crit", "silent"]);
const DAY = 86400000;

type Seg = { from: number; to: number; state: "ok" | "crit" | "none" };

/** The last 24 hours as up/down stretches, from the device's status events (unknown before it was added). */
function availability(events: EventDoc[], d: Device, now: number): Seg[] {
  const start = now - DAY, born = Math.max(start, d.createdAt?.getTime() ?? start);
  const evs = events.filter((e) => e.deviceId === d.id && e.at && (UP.has(e.kind) || DOWN.has(e.kind)))
    .sort((a, b) => a.at!.getTime() - b.at!.getTime());
  const stateOf = (e: EventDoc) => (UP.has(e.kind) ? "ok" : "crit") as Seg["state"];
  const before = evs.filter((e) => e.at!.getTime() <= born).at(-1);
  const inside = evs.filter((e) => e.at!.getTime() > born);
  // with nothing before the window, the first change inside it tells what came before it; with no changes at all,
  // a thing that isn't answering now was answering until its last answer
  const quiet = d.status === "crit" && d.lastSeen && d.lastSeen.getTime() > born ? d.lastSeen.getTime() : null;
  let state: Seg["state"] = before ? stateOf(before) : inside[0] ? (stateOf(inside[0]) === "ok" ? "crit" : "ok")
    : quiet || d.status === "ok" ? "ok" : d.status === "crit" ? "crit" : "none";
  if (!evs.length && quiet) inside.push({ id: "quiet", kind: "status_crit", severity: "crit", message: "", at: new Date(quiet) });
  const segs: Seg[] = born > start ? [{ from: start, to: born, state: "none" }] : [];
  let t = born;
  for (const e of inside) {
    segs.push({ from: t, to: e.at!.getTime(), state });
    t = e.at!.getTime(); state = stateOf(e);
  }
  segs.push({ from: t, to: now, state });
  return segs.filter((s) => s.to > s.from);
}

function Availability({ segs, now }: { segs: Seg[]; now: number }) {
  const down = segs.filter((s) => s.state === "crit");
  const mins = Math.round(down.reduce((n, s) => n + s.to - s.from, 0) / 60000);
  const known = segs.some((s) => s.state !== "none");
  return (
    <section className="drawer-section">
      <h4>Availability, last 24 hours</h4>
      <div className="avail" role="img" aria-label={down.length ? `Not answering ${down.length} times` : "Answering throughout"}>
        {segs.map((s) => <i key={s.from} className={s.state} style={{ width: `${((s.to - s.from) / DAY) * 100}%` }}
          title={`${s.state === "ok" ? "Answering" : s.state === "crit" ? "Not answering" : "Not watched yet"} from ${when(new Date(s.from), now)}`} />)}
      </div>
      <div className="avail-scale small muted"><span>24 h ago</span><span>now</span></div>
      <p className="small muted">{!known ? "Nothing to show yet: it was added just now."
        : down.length === 0 ? "Answered every check."
        : `Didn't answer ${down.length} time${down.length === 1 ? "" : "s"}, ${mins < 90 ? `${Math.max(1, mins)} min` : `${Math.round(mins / 60)} hours`} in all.`}</p>
    </section>
  );
}

export default function WatchedPanel({ uid, generation, device: d, devices, onAsk, onGo, onClose }: {
  uid: string; generation?: number; device: Device; devices: Device[]; onAsk: (q: string) => void;
  onGo: (g: Go) => void; onClose: () => void;
}) {
  const now = useNow(60000);
  const events = useEvents(uid, generation);
  const links = useLinks(uid, generation);
  const [stopping, setStopping] = useState(false);
  const [note, setNote] = useState("");
  const role = roleOf(d);
  const by = devices.find((x) => x.id === d.watchedBy)?.name;
  const name = (id: string) => devices.find((x) => x.id === id)?.name;
  const through = links.filter((l) => l.kind === "network" && (l.from === d.id || l.to === d.id))
    .map((l) => name(l.from === d.id ? l.to : l.from)).filter(Boolean) as string[];
  const sentence = d.status === "crit"
    ? `Hasn't answered since ${d.lastSeen ? when(d.lastSeen, now) : "it was added"}${by ? `. The ${by} keeps checking it` : ""}.`
    : d.status === "offline" ? `Not checked lately: ${by ? `the ${by}` : "the device that watches it"} isn't reporting.`
    : `${answering(d, now).replace(/^a/, "A")}, checked every minute by ${by ? `the ${by}` : "one of your devices"}.`;
  async function setRole(r: Role) {
    await api("POST", `/api/devices/${d.id}/layout`, { role: r }).catch(() => setNote("Couldn't save that."));
  }
  async function stop() {
    try { await api("POST", `/api/devices/${d.id}/revoke`, {}); onClose(); }
    catch { setNote("Couldn't stop watching it. Please try again."); setStopping(false); }
  }
  return (
    <>
      <p className="drawer-status">{sentence}</p>
      <div className="drawer-actions">
        <button className="primary" onClick={() => onAsk(role === "router" ? "Is my internet connection all right?"
          : `How is my ${d.name} doing?`)}>Ask about it</button>
      </div>
      {role === "router" && (
        <section className="drawer-section">
          <h4>Your internet connection</h4>
          <p className="small">Your devices reach the internet through it.{through.length > 0 &&
            <> Connected through it: {through.join(", ")}.</>}</p>
        </section>)}
      <section className="drawer-section">
        <h4>What it is</h4>
        <label className="small role-pick">What is it?{" "}
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(Object.keys(ROLES) as Role[]).map((r) => <option key={r} value={r}>{ROLES[r].label}</option>)}
          </select>
          {d.roleSetBy !== "user" && <span className="muted"> (Nightlight&apos;s guess)</span>}
        </label>
        <div className="details small">
          <div><span className="muted">Maker</span>{d.vendor ?? "not known"}</div>
          <div><span className="muted">Answered as</span>{d.services?.length ? d.services.join(", ") : "–"}</div>
          <div><span className="muted">Checked on</span>{d.checkPort
            ? `port ${d.checkPort}${PORTS[d.checkPort] ? ` (${PORTS[d.checkPort]})` : ""}` : "–"}</div>
        </div>
      </section>
      <Availability segs={availability(events, d, now)} now={now} />
      {(role === "computer" || role === "fileshare" || role === "server") && (
        <section className="drawer-section">
          <h4>See inside it</h4>
          <p className="small muted">Nightlight can only see that it answers. With the helper on it, you&apos;d see its disk,
            memory and what runs there, and Nightlight could fix things on it.</p>
          <button onClick={() => onGo({ to: "panel", panel: "add" })}>Install the helper on it</button>
        </section>)}
      <div className="remove-device small">
        {!stopping
          ? <button className="linkish" onClick={() => setStopping(true)}>Stop watching it…</button>
          : <>Take it off the map? Nothing changes on the device itself.{" "}
              <button className="small" onClick={stop}>Stop watching</button>{" "}
              <button className="small" onClick={() => setStopping(false)}>Keep it</button></>}
      </div>
      {note && <p className="small" style={{ color: "var(--crit)" }}>{note}</p>}
    </>
  );
}
