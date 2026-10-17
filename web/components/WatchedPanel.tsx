"use client";
// The device panel for a thing a helper watches (a router, a printer, a NAS without the helper…). Nightlight only
// knows whether it answers and what it answered on, so this says that plainly, lets the person say what it is, shows
// when it was reachable today, and offers the way to see more (install the helper) or to stop watching it.
import { useState } from "react";
import { api } from "@/lib/api";
import { useEvents, useLinks, useNow } from "@/lib/data";
import { madeBy } from "@/lib/found";
import { answering, when, type Go } from "@/lib/needsYou";
import type { Device, EventDoc, Role } from "@/lib/types";
import { ROLES, roleOf } from "./map/kinds";

const PORTS: Record<number, string> = { 22: "remote login", 80: "web page", 443: "secure web page", 445: "file sharing",
  631: "printer", 8123: "Home Assistant", 25565: "Minecraft", 32400: "Plex" };
// whether it answers (reachability) vs. whether anyone was checking (coverage: the watcher went silent and came back)
const UP = new Set(["status_ok", "watch_ok"]), DOWN = new Set(["status_crit", "watch_crit"]);
const GONE = "silent", BACK = "back";
const DAY = 86400000;

type Seg = { from: number; to: number; state: "ok" | "crit" | "none" };

/** The last 24 hours from the device's status events: answering, not answering, or unknown (before it was added, or
 * while its watcher wasn't reporting). Status changes are always recorded, so with none the state held throughout. */
function availability(events: EventDoc[], d: Device, now: number): Seg[] {
  const start = now - DAY, born = Math.max(start, d.createdAt?.getTime() ?? start);
  const evs = events.filter((e) => e.deviceId === d.id && e.at && (UP.has(e.kind) || DOWN.has(e.kind)
    || e.kind === GONE || e.kind === BACK)).sort((a, b) => a.at!.getTime() - b.at!.getTime());
  const reach = (e: EventDoc) => (UP.has(e.kind) ? "ok" : "crit") as "ok" | "crit";
  const changes = evs.filter((e) => UP.has(e.kind) || DOWN.has(e.kind));
  const before = changes.filter((e) => e.at!.getTime() <= born).at(-1);
  const firstIn = changes.find((e) => e.at!.getTime() > born);
  // reachability at the window's start: the last change before it, else the opposite of the first change in it,
  // else what it is now
  // (with no changes at all, a thing down now that answered inside the window was up until that answer)
  const lastOk = !changes.length && d.status === "crit" && d.lastAnswerAt && d.lastAnswerAt.getTime() > born
    ? d.lastAnswerAt.getTime() : null;
  let reachable: "ok" | "crit" | null = before ? reach(before) : firstIn ? (reach(firstIn) === "ok" ? "crit" : "ok")
    : lastOk ? "ok" : d.status === "ok" || d.status === "crit" ? d.status : null;
  const cover = evs.filter((e) => e.at!.getTime() <= born && (e.kind === GONE || e.kind === BACK)).at(-1);
  let watched = cover?.kind !== GONE;
  const segs: Seg[] = born > start ? [{ from: start, to: born, state: "none" }] : [];
  const state = (): Seg["state"] => watched && reachable ? reachable : "none";
  let t = born;
  // the last answer is a change to "not answering" just after it, in time order with the coverage events
  const timeline = [...evs.filter((x) => x.at!.getTime() > born).map((e) => ({ t: e.at!.getTime(), kind: e.kind })),
    ...(lastOk ? [{ t: lastOk, kind: "status_crit" }] : [])].filter((e) => e.t <= now).sort((a, b) => a.t - b.t);
  for (const e of timeline) {
    segs.push({ from: t, to: e.t, state: state() });
    t = e.t;
    if (e.kind === GONE) watched = false; else if (e.kind === BACK) watched = true; else reachable = UP.has(e.kind) ? "ok" : "crit";
  }
  segs.push({ from: t, to: now, state: state() });
  // merge neighbours in the same state, so one outage is one stretch
  return segs.filter((s) => s.to > s.from).reduce<Seg[]>((out, s) => {
    const last = out.at(-1);
    if (last && last.state === s.state) last.to = s.to; else out.push({ ...s });
    return out;
  }, []);
}

/** When it stopped answering: after its last answer, or (older data) its latest change to "not answering". */
function downSince(events: EventDoc[], d: Device): Date | null {
  if (d.status === "crit" && d.lastAnswerAt) return d.lastAnswerAt;
  const last = events.filter((e) => e.deviceId === d.id && e.at && (UP.has(e.kind) || DOWN.has(e.kind)))
    .sort((a, b) => b.at!.getTime() - a.at!.getTime())[0];
  return d.status === "crit" && last && DOWN.has(last.kind) ? last.at! : null;
}

function Availability({ segs, now }: { segs: Seg[]; now: number }) {
  const down = segs.filter((s) => s.state === "crit");
  const mins = Math.round(down.reduce((n, s) => n + s.to - s.from, 0) / 60000);
  // an outage its watcher was silent in the middle of is still one outage
  let outages = 0, prev: Seg["state"] | null = null;
  for (const s of segs) {
    if (s.state === "none") continue;
    if (s.state === "crit" && prev !== "crit") outages++;
    prev = s.state;
  }
  const known = segs.some((s) => s.state !== "none");
  return (
    <section className="drawer-section">
      <h4>Availability, last 24 hours</h4>
      <div className="avail" role="img" aria-label={outages ? `Not answering ${outages} times` : "Answering throughout"}>
        {segs.map((s) => <i key={s.from} className={s.state} style={{ width: `${((s.to - s.from) / DAY) * 100}%` }}
          title={`${s.state === "ok" ? "Answering" : s.state === "crit" ? "Not answering" : "Not watched yet"} from ${when(new Date(s.from), now)}`} />)}
      </div>
      <div className="avail-scale small muted"><span>24 h ago</span><span>now</span></div>
      <p className="small muted">{!known ? "Nothing to show yet: it was added just now."
        : outages === 0 ? "Answered every check."
        : `Didn't answer ${outages} time${outages === 1 ? "" : "s"}, ${mins < 90 ? `${Math.max(1, mins)} min` : `${Math.round(mins / 60)} hours`} in all.`}</p>
    </section>
  );
}

export default function WatchedPanel({ uid, generation, device: d, devices, onAsk, onGo, onClose, part = "overview" }: {
  uid: string; generation?: number; device: Device; devices: Device[]; onAsk: (q: string) => void;
  onGo: (g: Go) => void; onClose: () => void; part?: "overview" | "settings"; // Settings: stop watching it
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
  const since = downSince(events, d);
  const made = madeBy(d);
  // the name it announces (quoted: its words, not the owner's), when the owner calls it something else
  const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();
  const calls = d.seenName && !d.nameFromSeen && !same(d.seenName, d.name) ? d.seenName : null;
  const sentence = d.status === "crit"
    ? (since ? `Hasn't answered since ${when(since, now)}.` : "Isn't answering.")
      + (by ? ` The ${by} keeps checking it${d.lastSeen ? ` (last check ${when(d.lastSeen, now)})` : ""}.`
        : d.lastSeen ? ` Last checked ${when(d.lastSeen, now)}.` : "")
    : d.status === "offline" ? `Not checked lately: ${by ? `the ${by}` : "the device that watches it"} isn't reporting.`
    : `${answering(d, now).replace(/^a/, "A")}, checked every minute by ${by ? `the ${by}` : "one of your devices"}.`;
  async function setRole(r: Role) {
    await api("POST", `/api/devices/${d.id}/layout`, { role: r }).catch(() => setNote("Couldn't save that."));
  }
  async function stop() {
    try { await api("POST", `/api/devices/${d.id}/revoke`, {}); onClose(); }
    catch { setNote("Couldn't stop watching it. Please try again."); setStopping(false); }
  }
  if (part === "settings") {
    return (
      <section className="drawer-section">
        <h4>Stop watching</h4>
        <div className="remove-device small">
          {!stopping
            ? <button className="linkish" onClick={() => setStopping(true)}>Stop watching it…</button>
            : <>Take it off the map? Nothing changes on the device itself.{" "}
                <button className="small" onClick={stop}>Stop watching</button>{" "}
                <button className="small" onClick={() => setStopping(false)}>Keep it</button></>}
        </div>
        {note && <p className="small" style={{ color: "var(--crit)" }}>{note}</p>}
      </section>
    );
  }
  return (
    <>
      <p className="drawer-status">{sentence}</p>
      <div className="drawer-actions">
        <button className="primary" onClick={() => onAsk(role === "router" ? "Is my internet connection all right?"
          : `How is my ${d.name} doing?`)}>Ask about it</button>
      </div>
      <section className="drawer-section">
        <h4>What it is</h4>
        <label className="small role-pick">What is it?{" "}
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(Object.keys(ROLES) as Role[]).map((r) => <option key={r} value={r}>{ROLES[r].label}</option>)}
          </select>
          {d.roleSetBy !== "user" && <span className="muted"> (Nightlight&apos;s guess)</span>}
        </label>
        <div className="details small">
          <div><span className="muted">Made by</span>{made || "not known"}</div>
          {calls && <div><span className="muted">Calls itself</span>&ldquo;{calls}&rdquo;</div>}
          <div><span className="muted">Offers</span>{d.services?.length ? d.services.join(", ") : "–"}</div>
          <div><span className="muted">Checked on</span>{d.checkPort
            ? `port ${d.checkPort}${PORTS[d.checkPort] ? ` (${PORTS[d.checkPort]})` : ""}` : "–"}</div>
        </div>
      </section>
      {role === "router" && (
        <section className="drawer-section">
          <h4>Your internet connection</h4>
          <p className="small">Your devices reach the internet through it.{through.length > 0 &&
            <> Connected through it: {through.join(", ")}.</>}</p>
        </section>)}
      <Availability segs={availability(events, d, now)} now={now} />
      {(role === "computer" || role === "fileshare" || role === "server") && (
        <section className="drawer-section">
          <h4>See inside it</h4>
          <p className="small muted">Nightlight can only see that it answers. With the helper on it, you&apos;d see its disk,
            memory and what runs there, and Nightlight could fix things on it.</p>
          <button onClick={() => onGo({ to: "panel", panel: "add" })}>Install the helper on it</button>
        </section>)}
      {note && <p className="small" style={{ color: "var(--crit)" }}>{note}</p>}
    </>
  );
}
