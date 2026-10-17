"use client";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { firebase } from "@/lib/firebase";
import type { Device } from "@/lib/types";
import PairApprove from "./PairApprove";

export function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "6px 0" }}>
      <pre style={{ flex: 1, margin: 0, padding: 8, background: "var(--bg)", borderRadius: 8, overflowX: "auto" }}>{text}</pre>
      <button onClick={() => navigator.clipboard.writeText(text).then(() => setDone(true))}>{done ? "Copied" : "Copy"}</button>
    </div>
  );
}

/** The message for whoever set the device up: what this is, the line, three steps, and when the line runs out. */
function setupMessage(owner: string | null, line: string, minutes: number) {
  return [
    `${owner ?? "Someone you know"} uses Nightlight to keep an eye on their home devices and asked you to set it up on `
      + "one of them. It takes about a minute.",
    "",
    "1. On that device, open Terminal (or connect to it over SSH).",
    "2. Paste this line:",
    "",
    line,
    "",
    "3. Press Enter. It may ask for the device's password once.",
    "",
    `The line works once and expires in about ${minutes} minute${minutes === 1 ? "" : "s"}. If it has, ask them for a `
      + "new one. After this nobody needs the terminal again: everything else happens in the Nightlight app.",
  ].join("\n");
}

/** Hand the one-time setup to someone else: the phone's share sheet where there is one, otherwise the clipboard. */
function SendLine({ line, expiresAt }: { line: string; expiresAt: string }) {
  const [owner, setOwner] = useState<string | null>(null);
  const [note, setNote] = useState("");
  useEffect(() => {
    firebase().then(({ auth }) => setOwner(auth.currentUser?.displayName?.split(" ")[0] || null)).catch(() => {});
  }, []);
  async function send() {
    const left = new Date(expiresAt).getTime() - Date.now();
    if (left <= 0) { setNote("This line has run out. Close this and get a new one."); return; }
    const minutes = Math.max(1, Math.round(left / 60000));
    const text = setupMessage(owner, line, minutes);
    if (navigator.share) {
      try { await navigator.share({ title: "Set up Nightlight", text }); return; }
      catch (e) { if (e instanceof DOMException && e.name === "AbortError") return; } // otherwise fall back to copying
    }
    await navigator.clipboard.writeText(text).then(() => setNote("Copied. Paste it into a message to them."),
      () => setNote("Couldn't copy. Copy the line above and send it with these steps."));
  }
  return (
    <div className="send-line">
      <button onClick={send}>Send to whoever set up this device</button>
      {note && <span className="small muted">{note}</span>}
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

export default function AddDevice({ anonymous, onSave, devices }: {
  anonymous: boolean; onSave: () => void; devices: Device[];
}) {
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
  const [other, setOther] = useState(false);
  const line = code ? `curl -fsSL ${origin}/install.sh | sh -s -- ${code.code}` : "";

  return (
    <div className="panel">
      <h3>Add one of your devices</h3>
      <p className="small muted" style={{ marginTop: 0 }}>Works on a Raspberry Pi, a Linux computer or a Mac. Takes about
        a minute.</p>
      <ol className="steps-list">
        <li>
          <strong>Get your line.</strong>{" "}
          {!code ? <button className="primary" onClick={getCode}>Get my line</button>
            : <span className="small muted">(works once, for 10 minutes)</span>}
          {code && <Copy text={line} />}
          {code && <SendLine line={line} expiresAt={code.expiresAt} />}
        </li>
        <li><strong>Paste it on the device</strong>: open its Terminal (on a Mac: Applications &gt; Utilities &gt;
          Terminal), paste, press Enter. It may ask for the device&apos;s password once.</li>
        <li><strong>That&apos;s it.</strong> We&apos;ll show it here the moment it connects.
          {before && !paired && <Waiting devices={devices} before={before} />}</li>
      </ol>

      <button className="linkish small" onClick={() => setOther(!other)}>
        {other ? "Hide" : "Can't paste on that device? Use a code it shows instead"}</button>
      {other && (
        <div style={{ marginTop: 8 }}>
          <p className="small muted">Run <code>curl -fsSL {origin}/install.sh | sh</code> on the device. It shows a code
            like WXYZ-1234 (and a link you can open on your phone). Type the code here:</p>
          {!paired
            ? <PairApprove onApprove={snapshot} onDone={setPaired} />
            : paired.approved
              ? (before && <Waiting devices={devices} before={before} />)
              : <p className="small">Okay, that device was turned away. Nothing was added.</p>}
        </div>
      )}

      <details className="small" style={{ marginTop: 12 }}>
        <summary>What does the helper do? How do I remove it?</summary>
        <p>A small helper on your device reports its health (disk, memory, what is running). It never sends passwords,
          logs, file contents or network addresses, and it changes nothing unless you allow a job on the device itself
          and then approve it here.</p>
        <p>To remove it, run this on the device:</p>
        <Copy text={`curl -fsSL ${origin}/uninstall.sh | sh`} />
        <p className="soon">Coming later: installers for Mac, Windows and NAS app stores, no terminal needed.</p>
      </details>
      {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
    </div>
  );
}
