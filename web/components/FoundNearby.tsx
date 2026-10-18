"use client";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { newer, type Go } from "@/lib/needsYou";
import { madeBy, type Found } from "@/lib/found";
import type { Device, Discovery, FoundThing } from "@/lib/types";

const LOOKS = "0.9.21"; // first helper that looks nearby when the app asks

/** The command a strict device needs, run on the device itself (where the installer put the helper). */
const DISCOVER = "nightlight discover";

const names = (xs: string[]) => xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs.at(-1)}`;

type Asked = { base: Record<string, number>; asked: { deviceId: string; name: string }[]; skipped: { deviceId: string; name: string; why: string }[] };

/** "Look for devices nearby": the server asks one device per network (the tap is the approval); results arrive in
 * the list. Devices that couldn't look say why, with the way round it. */
function LookNearby({ devices, discoveries, onGo, again }: {
  devices: Device[]; discoveries: Discovery[]; onGo: (g: Go) => void; again: boolean;
}) {
  const [run, setRun] = useState<Asked | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const own = devices.filter((d) => d.realm === "real" && d.kind !== "watched");
  // a device has looked once its list is newer than the one it had when we asked (or it had none)
  const looked = (id: string) => !!run
    && (discoveries.find((x) => x.id === id)?.at?.getTime() ?? -1) > (run.base[id] ?? -1);
  // one device per network by default; every device sees more (each mostly knows what it talked to lately)
  async function look(everyDevice = false) {
    setErr(""); setBusy(true);
    const base = Object.fromEntries(discoveries.map((d) => [d.id, d.at?.getTime() ?? 0])); // before asking
    try {
      const r = await api<Omit<Asked, "base">>("POST", "/api/discover", everyDevice ? { everyDevice: true } : {});
      setRun({ base, ...r });
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 429 ? "That's a lot of looking. Please wait a little." : "Couldn't ask your devices to look.");
    } finally { setBusy(false); }
  }
  if (!own.length) return <p className="small muted">Add one of your own devices first; it can then look for others nearby.</p>;
  const looking = run?.asked.filter((a) => !looked(a.deviceId)) ?? [];
  return (
    <div className="look-nearby">
      <div className="look-row">
        <button className={again ? "" : "primary"} onClick={() => look()} disabled={busy || looking.length > 0}>
          {again ? "Look again" : "Look for devices nearby"}</button>
        {own.length > 1 && <button className="linkish small" onClick={() => look(true)} disabled={busy || looking.length > 0}>
          Look from all my devices (more complete)</button>}
      </div>
      {looking.length > 0 && (
        <p className="small live-status"><span className="dot offline pulse" /> Looking from the {names(looking.map((a) => a.name))}…
          results appear here in a minute.</p>)}
      {run && run.asked.length > 0 && looking.length === 0 && (
        <p className="small muted">{run.asked.map((a) => {
          const n = discoveries.find((x) => x.id === a.deviceId)?.items.length ?? 0;
          return `The ${a.name} looked just now: ${n} thing${n === 1 ? "" : "s"}.`;
        }).join(" ")}</p>)}
      {run && run.asked.length === 0 && <p className="small muted">None of your devices could look this time:</p>}
      {run?.skipped.map((s) => {
        const d = own.find((x) => x.id === s.deviceId);
        return (
          <p key={s.deviceId} className="small muted">{s.name}: {s.why}.
            {d && d.manage === "app" && newer(LOOKS, d.helperVersion) && <>{" "}
              <button className="linkish small" onClick={() => onGo({ to: "drawer", deviceId: d.id, tab: "settings" })}>
                Update</button></>}
            {d && d.manage !== "app" && <> Or on the device: <code>{DISCOVER}</code> (if it says &quot;command not
              found&quot;: <code>~/.local/bin/nightlight discover</code>)</>}
          </p>);
      })}
      {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
    </div>
  );
}

/** Things your devices found on their networks (no addresses), once per thing however many devices saw it. Add =
 * put it on the map, watched by a helper that saw it (it checks the thing still answers); the server lists a finder
 * that can watch it first. */
export default function FoundNearby({ found: { items, refresh }, discoveries, devices, onGo }: {
  found: Found; discoveries: Discovery[]; devices: Device[]; onGo: (g: Go) => void;
}) {
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [showPrivate, setShowPrivate] = useState(false);
  useEffect(() => { refresh(); }, [refresh]); // opening the panel always shows the server's current list
  const key = (t: FoundThing) => t.tag ?? `${t.seenBy[0]?.deviceId}:${t.seenBy[0]?.cid}`;
  async function add(t: FoundThing) {
    const by = t.seenBy[0];
    if (!by) return;
    setMsg("");
    try {
      await api("POST", `/api/discoveries/${by.deviceId}/${by.cid}/add`, { name: label(t).trim() || named(t) });
      refresh();
    } catch (e) {
      setMsg(e instanceof ApiError && e.code === "already_added" ? "That one is already on your map."
        : e instanceof ApiError && e.code === "no_check_port" ? "Nightlight can't check that one, so it can't watch it."
        : e instanceof ApiError && e.code === "your_own_device"
          ? `That's your ${typeof e.body.name === "string" ? e.body.name : "own device"}, already on your map.`
        : e instanceof ApiError && e.code === "watch_capacity" ? "That device already watches as many things as it can (10)."
        : "Couldn't add it.");
    }
  }
  const found = items ?? [];
  const named = (t: FoundThing) => (t.router ? "Router" : t.name ?? t.guess).slice(0, 40); // the API takes 40
  const label = (t: FoundThing) => labels[key(t)] ?? named(t);
  // phones and laptops with a private Wi-Fi address, no name and nothing to check fold into one line: there is
  // nothing to tell them apart by (one a finder can check stays in the Add list)
  const anon = (t: FoundThing) => !!t.privateAddress && !t.name && t.guess === "Phone or laptop"
    && t.seenBy[0]?.canWatch === false;
  const privates = found.filter(anon), rest = found.filter((t) => !anon(t));
  // what can go on the map first (the server puts the router at the top); the rest folds into one line
  const watchable = rest.filter((t) => t.seenBy[0]?.canWatch !== false);
  const unwatchable = rest.filter((t) => t.seenBy[0]?.canWatch === false);
  const what = (t: FoundThing) => <>
    <strong>{t.name ?? t.guess}</strong>
    {t.name && <span className="muted"> · {t.guess}</span>}
    {t.privateAddress && t.services.length > 0 ? <span className="muted small"> · uses a private Wi-Fi address</span>
      : madeBy(t) && <span className="muted"> · {madeBy(t)}</span>}
    {t.services.length > 0 && <span className="muted small"> ({t.services.join(", ")})</span>}
    <span className="muted small"> · seen by the {names(t.seenBy.map((b) => b.name))}</span>
  </>;
  return (
    <div className="panel">
      <h3>Found nearby</h3>
      {items && found.length === 0 && (
        <p className="small muted" style={{ marginTop: 0 }}>Nothing found yet. One of your devices can look around its
          network for printers, storage and other servers. It sends back what it finds, never addresses, and you choose
          what goes on the map.</p>
      )}
      {watchable.length > 0 && (
        <div className="list">
          {watchable.map((t) => (
            <div key={key(t)} className={`item found-row ${t.router ? "router" : ""}`}>
              <span className="found-what">{what(t)}
                {t.router && <span className="found-hint small">Add your router to see how your devices connect.</span>}</span>
              <span className="found-add">
                <input value={label(t)} maxLength={40} aria-label={`Name for ${t.guess}`}
                  onChange={(e) => setLabels({ ...labels, [key(t)]: e.target.value })} />
                <button className="primary" onClick={() => add(t)}>Add</button>
              </span>
            </div>
          ))}
        </div>
      )}
      {unwatchable.length > 0 && (
        <div className="found-more small muted">
          {unwatchable.length} {watchable.length ? "more " : ""}Nightlight can&apos;t check{" "}
          <button className="linkish small" onClick={() => setShowAll(!showAll)}>{showAll ? "Hide" : "Show"}</button>
          {showAll && <ul>{unwatchable.map((t) => <li key={key(t)}>{what(t)}</li>)}</ul>}
        </div>
      )}
      {privates.length > 0 && (
        <div className="found-more small muted">
          {privates.length === 1
            ? "1 phone or laptop: a private Wi-Fi address, Nightlight can't check it. It makes up a new address on each network to stay private, so there's nothing to know it by."
            : `${privates.length} phones and laptops: private Wi-Fi addresses, Nightlight can't check them. They make up a new address on each network to stay private, so there's nothing to tell them apart by.`}{" "}
          <button className="linkish small" onClick={() => setShowPrivate(!showPrivate)}>{showPrivate ? "Hide" : "Show"}</button>
          {showPrivate && <ul>{privates.map((t) => <li key={key(t)}>{what(t)}</li>)}</ul>}
        </div>
      )}
      {msg && <p className="small" style={{ color: "var(--crit)" }}>{msg}</p>}
      {items && <LookNearby devices={devices} discoveries={discoveries} onGo={onGo} again={found.length > 0} />}
    </div>
  );
}
