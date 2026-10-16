"use client";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Device } from "@/lib/types";
import PairApprove from "./PairApprove";

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "6px 0" }}>
      <pre style={{ flex: 1, margin: 0, padding: 8, background: "var(--bg)", borderRadius: 8, overflowX: "auto" }}>{text}</pre>
      <button onClick={() => navigator.clipboard.writeText(text).then(() => setDone(true))}>{done ? "Copied" : "Copy"}</button>
    </div>
  );
}

/** "Waiting for your device…" until a real device that wasn't there before shows up on the map. */
function Waiting({ devices, before }: { devices: Device[]; before: Set<string> }) {
  const fresh = devices.find((d) => d.realm === "real" && !before.has(d.id));
  return fresh
    ? <p className="live-status ok"><span className="dot ok" /> Connected! {fresh.name} is on your map.</p>
    : <p className="live-status"><span className="dot offline pulse" /> Waiting for your device…</p>;
}

type Tab = "line" | "code";

export default function AddDevice({ anonymous, onSave, devices }: {
  anonymous: boolean; onSave: () => void; devices: Device[];
}) {
  const [tab, setTab] = useState<Tab>("line");
  const [code, setCode] = useState<{ code: string; expiresAt: string } | null>(null);
  const [before, setBefore] = useState<Set<string> | null>(null);
  const [paired, setPaired] = useState<{ approved: boolean; name: string } | null>(null);
  const [origin, setOrigin] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { setOrigin(window.location.origin); }, []);

  if (anonymous) {
    return (
      <div className="panel">
        <h3>Add a real device</h3>
        <p>Real devices stay linked to your account, so first save this home with Google.</p>
        <button className="primary" onClick={onSave}>Save with Google</button>
      </div>
    );
  }

  const snapshot = () => setBefore(new Set(devices.map((d) => d.id)));
  async function getCode() {
    setErr("");
    try {
      const c = await api<{ code: string; expiresAt: string }>("POST", "/api/devices/enrol-code", {});
      snapshot();
      setCode(c);
    } catch (e) {
      setErr(e instanceof ApiError && e.code === "sign_in_required"
        ? "Real devices need a Google account. Use Save with Google first."
        : e instanceof ApiError && e.status === 429
          ? "That's a lot of codes in one hour. Please wait a little and try again."
          : "Couldn't get a code. Please try again.");
    }
  }
  const switchTo = (t: Tab) => { setTab(t); setBefore(null); setCode(null); setPaired(null); setErr(""); };

  return (
    <div className="panel">
      <h3>Add a real device</h3>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "line"} className={tab === "line" ? "on" : ""}
          onClick={() => switchTo("line")}>Paste one line</button>
        <button role="tab" aria-selected={tab === "code"} className={tab === "code" ? "on" : ""}
          onClick={() => switchTo("code")}>Your device shows a code</button>
      </div>

      {tab === "line" && (
        <>
          <p className="small muted">For Linux, Raspberry Pi and Mac. Open a terminal on the device and paste one line.</p>
          {!code
            ? <button className="primary" onClick={getCode}>Get my line</button>
            : (
              <>
                <Copy text={`curl -fsSL ${origin}/install.sh | sh -s -- ${code.code}`} />
                <p className="small muted">The code in it works once, for 10 minutes. It may ask for your password to
                  set up the background service.</p>
                {before && <Waiting devices={devices} before={before} />}
                <p className="small muted" style={{ marginTop: 10 }}>Remove later:</p>
                <Copy text={`curl -fsSL ${origin}/uninstall.sh | sh`} />
              </>
            )}
        </>
      )}

      {tab === "code" && (
        <>
          <p className="small muted">When the device shows a code like WXYZ-1234, type it here (or scan its QR code with
            your phone). To make a device show one, run this on it:</p>
          <Copy text={`curl -fsSL ${origin}/install.sh | sh`} />
          {!paired
            ? <PairApprove onApprove={snapshot} onDone={setPaired} />
            : paired.approved
              ? (before && <Waiting devices={devices} before={before} />)
              : <p className="small">Okay, that device was turned away. Nothing was added.</p>}
        </>
      )}

      <p className="small" style={{ marginTop: 12 }}>A small helper on your device reports its health (disk, memory,
        what is running). It never sends passwords, logs, file contents or network addresses, and it changes nothing
        unless you allow a job on the device itself and then approve it here.</p>
      <p className="small soon">Coming later: installers for Mac, Windows, NAS app stores — no terminal needed.</p>
      {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
    </div>
  );
}
