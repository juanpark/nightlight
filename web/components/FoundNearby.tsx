"use client";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { newer, type Go } from "@/lib/needsYou";
import type { Device, Discovery, FoundThing } from "@/lib/types";

const LOOKS = "0.9.21"; // first helper that looks nearby when the app asks

/** The command a strict device needs, run on the device itself (where the installer put the helper). */
const discoverCmd = (d: Device) => /mac/i.test(d.os ?? "")
  ? "python3 ~/Library/Application\\ Support/Nightlight/nightlight_helper.py discover"
  : "python3 ~/.local/share/nightlight/nightlight_helper.py discover";

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
  async function look() {
    setErr(""); setBusy(true);
    const base = Object.fromEntries(discoveries.map((d) => [d.id, d.at?.getTime() ?? 0])); // before asking
    try {
      const r = await api<Omit<Asked, "base">>("POST", "/api/discover", {});
      setRun({ base, ...r });
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 429 ? "That's a lot of looking. Please wait a little." : "Couldn't ask your devices to look.");
    } finally { setBusy(false); }
  }
  if (!own.length) return <p className="small muted">Add one of your own devices first; it can then look for others nearby.</p>;
  const looking = run?.asked.filter((a) => !looked(a.deviceId)) ?? [];
  return (
    <div className="look-nearby">
      <button className={again ? "" : "primary"} onClick={look} disabled={busy || looking.length > 0}>
        {again ? "Look again" : "Look for devices nearby"}</button>
      {looking.length > 0 && (
        <p className="small live-status"><span className="dot offline pulse" /> Looking from the {names(looking.map((a) => a.name))}…
          results appear here in a minute.</p>)}
      {run && run.asked.length > 0 && looking.length === 0 && (
        <p className="small muted">The {names(run.asked.map((a) => a.name))} {run.asked.length === 1 ? "has" : "have"} looked.</p>)}
      {run && run.asked.length === 0 && <p className="small muted">None of your devices could look this time:</p>}
      {run?.skipped.map((s) => {
        const d = own.find((x) => x.id === s.deviceId);
        return (
          <p key={s.deviceId} className="small muted">{s.name}: {s.why}.
            {d && d.manage === "app" && newer(LOOKS, d.helperVersion) && <>{" "}
              <button className="linkish small" onClick={() => onGo({ to: "drawer", deviceId: d.id, tab: "settings" })}>
                Update</button></>}
            {d && d.manage !== "app" && <> Or on the device: <code>{discoverCmd(d)}</code></>}
          </p>);
      })}
      {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
    </div>
  );
}

/** Things your devices found on their networks (no addresses), once per thing however many devices saw it. Add =
 * put it on the map, watched by a helper that saw it (it checks the thing still answers); the server lists a finder
 * that can watch it first. */
export default function FoundNearby({ discoveries, devices, onGo }: {
  discoveries: Discovery[]; devices: Device[]; onGo: (g: Go) => void;
}) {
  const [items, setItems] = useState<FoundThing[] | null>(null);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [tick, setTick] = useState(0);
  // every discovery snapshot (a new scan, or something added from another tab) refreshes the server's merged view
  useEffect(() => {
    let live = true;
    api<{ items: FoundThing[] }>("GET", "/api/found").then((r) => { if (live) setItems(r.items); })
      .catch(() => { if (live) setItems((cur) => cur ?? []); });
    return () => { live = false; };
  }, [discoveries, tick]);
  const key = (t: FoundThing) => t.tag ?? `${t.seenBy[0]?.deviceId}:${t.seenBy[0]?.cid}`;
  async function add(t: FoundThing) {
    const by = t.seenBy[0];
    if (!by) return;
    setMsg("");
    try {
      await api("POST", `/api/discoveries/${by.deviceId}/${by.cid}/add`, { name: (labels[key(t)] ?? t.guess).trim() || t.guess });
      setTick((n) => n + 1);
    } catch (e) {
      setMsg(e instanceof ApiError && e.code === "already_added" ? "That one is already on your map."
        : e instanceof ApiError && e.code === "no_check_port" ? "Nightlight can't check that one, so it can't watch it."
        : e instanceof ApiError && e.code === "watch_capacity" ? "That device already watches as many things as it can (10)."
        : "Couldn't add it.");
    }
  }
  const found = items ?? [];
  return (
    <div className="panel">
      <h3>Found nearby</h3>
      {items && found.length === 0 && (
        <p className="small muted" style={{ marginTop: 0 }}>Nothing found yet. One of your devices can look around its
          network for printers, storage and other servers. It sends back what it finds, never addresses, and you choose
          what goes on the map.</p>
      )}
      {found.length > 0 && (
        <div className="list">
          {found.map((t) => (
            <div key={key(t)} className="item" style={{ alignItems: "center" }}>
              <span style={{ flex: 1 }}><strong>{t.guess}</strong>
                {t.vendor && <span className="muted"> · {t.vendor}</span>}
                {t.services.length > 0 && <span className="muted small"> ({t.services.join(", ")})</span>}
                <span className="muted small"> · seen by the {names(t.seenBy.map((b) => b.name))}</span></span>
              {t.seenBy[0]?.canWatch === false
                ? <span className="small muted">Nightlight can&apos;t check this one (it answered on no port it can watch).</span>
                : <>
                    <input value={labels[key(t)] ?? t.guess} maxLength={40} aria-label="Name"
                      onChange={(e) => setLabels({ ...labels, [key(t)]: e.target.value })} style={{ width: 160 }} />
                    <button className="primary" onClick={() => add(t)}>Add</button>
                  </>}
            </div>
          ))}
        </div>
      )}
      {msg && <p className="small" style={{ color: "var(--crit)" }}>{msg}</p>}
      {items && <LookNearby devices={devices} discoveries={discoveries} onGo={onGo} again={found.length > 0} />}
    </div>
  );
}
