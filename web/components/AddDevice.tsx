"use client";
import { useEffect, useState } from "react";
import { Cpu, Laptop } from "lucide-react";
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

/** The message for someone who can set the device up: what this is, the line, three steps, when the line runs out. */
function setupMessage(owner: string | null, line: string, minutes: number) {
  return [
    `${owner ?? "Someone you know"} uses Nightlight to keep an eye on their home devices and is asking you to set it up `
      + "on one of them now. It takes about a minute.",
    "",
    "1. On that device, open its command window (Terminal). If you usually reach it from another computer, for example over SSH, that works too.",
    "2. Paste this line (it installs Nightlight's helper, a small program that reports how the device is doing):",
    "",
    line,
    "",
    "3. Press Enter. It may ask once for the password you use to log in to that device.",
    "",
    `The line works once and expires in about ${minutes} minute${minutes === 1 ? "" : "s"}. If it has, ask them for a `
      + "new one. After this nobody needs the command window again: everything else happens in the Nightlight app.",
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
    if (left <= 0) { setNote("This line has run out. Get a new one above, then send it."); return; }
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
    <p className="send-line small muted">Setting it up on a computer somewhere else?{" "}
      <button className="linkish small" onClick={send}>Send these steps</button>
      {note && <span> {note}</span>}</p>
  );
}

/** "Waiting for your device…" until a real device that wasn't there before shows up on the map. */
function Waiting({ devices, before }: { devices: Device[]; before: Set<string> }) {
  const fresh = devices.find((d) => d.realm === "real" && !before.has(d.id));
  return fresh
    ? <p className="live-status ok"><span className="dot ok" /> Connected! {fresh.name} is on your map.</p>
    : <p className="live-status"><span className="dot offline pulse" /> Waiting for your device…</p>;
}

type Os = "mac" | "linux";

/** One numbered step: a small drawing of what to look for, then what to do. */
function Step({ n, art, children }: { n: number; art: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="setup-step">
      <span className="setup-n" aria-hidden>{n}</span>
      <span className="setup-art" aria-hidden>{art}</span>
      <div className="setup-text">{children}</div>
    </li>
  );
}

/** What a careful person wants to know before pasting a line from the internet. Facts as in the README ("What never
 * leaves a device", "Real devices"). */
function Reassure() {
  return (
    <div className="promise small">
      <ul>
        <li><strong>Watches, changes nothing.</strong> A fix or clean-up happens only after you tap Approve.</li>
        <li><strong>Nothing can connect in to your computer.</strong> It only reaches out to Nightlight, so your
          computer never shows a security pop-up about it.</li>
        <li><strong>Stays on the machine:</strong> its name and addresses on your network, files, passwords and keys.</li>
        <li><strong>One line removes it</strong>, or remove it from the app.</li>
      </ul>
      <p className="muted">In the first minute: your device&apos;s disk, memory and apps, and <em>Found nearby</em>, the
        printer, TV and phones it can see on your network, by the names they announce.</p>
    </div>
  );
}

const Term = ({ text }: { text: string }) => <span className="art-term"><i /><i /><i /><b>{text}</b></span>;

export default function AddDevice({ anonymous, onSave, devices }: {
  anonymous: boolean; onSave: () => void; devices: Device[];
}) {
  const [os, setOs] = useState<Os | null>(null);
  const [code, setCode] = useState<{ code: string; expiresAt: string } | null>(null);
  const [before, setBefore] = useState<Set<string> | null>(null);
  const [paired, setPaired] = useState<{ approved: boolean; name: string } | null>(null);
  const [origin, setOrigin] = useState("");
  const [err, setErr] = useState("");
  const [other, setOther] = useState(false);
  useEffect(() => { setOrigin(window.location.origin); }, []);

  if (anonymous) {
    return (
      <div className="panel">
        <h3>Try it on your own computer</h3>
        <p>Your laptop or Raspberry Pi on your own map in about two minutes. Real devices belong to an account, so
          first sign in with Google; this sample home stays.</p>
        <button className="primary" onClick={onSave}>Sign in with Google</button>
        <Reassure />
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
  function pick(o: Os) { setOs(o); if (!code) getCode(); }
  const line = code ? `curl -fsSL ${origin}/install.sh | sh -s -- ${code.code}` : "";
  const mac = os === "mac";

  return (
    <div className="panel">
      <h3>Add one of your devices</h3>
      <p className="small muted" style={{ marginTop: 0 }}>Three steps, about a minute. You&apos;ll see it on your map
        the moment it connects.</p>
      <Reassure />
      <div className="setup-pick" role="radiogroup" aria-label="Which kind of device?">
        <button role="radio" aria-checked={mac} className={mac ? "on" : ""} onClick={() => pick("mac")}>
          <Laptop size={22} strokeWidth={1.6} /> A Mac</button>
        <button role="radio" aria-checked={os === "linux"} className={os === "linux" ? "on" : ""} onClick={() => pick("linux")}>
          <Cpu size={22} strokeWidth={1.6} /> Linux computer or Raspberry Pi</button>
      </div>

      {mac && <p className="small muted setup-note">A Mac installer you double-click is coming; it still needs
        Apple&apos;s sign-off. Until then, this one line does the same.</p>}
      {os && (
        <ol className="setup-steps">
          {mac
            ? <Step n={1} art={<span className="art-keys"><kbd>⌘</kbd>+<kbd>Space</kbd></span>}>
                <strong>Open Terminal on the Mac.</strong> Press <kbd>⌘</kbd> <kbd>Space</kbd>, type <em>Terminal</em>,
                and press Enter. A window with a blinking cursor opens.
              </Step>
            : <Step n={1} art={<Term text="$ _" />}>
                <strong>Open its command window (Terminal).</strong> On the device itself, open Terminal from its
                menu. Or, if you usually reach it from another computer, connect to it as you normally do.
              </Step>}
          <Step n={2} art={<Term text="$ curl …" />}>
            <strong>Paste this line into it.</strong>
            {code ? <><Copy key={code.code} text={line} /><span className="small muted">Your own line: it works once, for 10
              minutes. It installs Nightlight&apos;s helper, a small program that stays on the device and reports how
              it is doing, and links it to your account.</span></>
              : !err && <p className="small muted">Making your line…</p>}
            {err && <p className="small" style={{ color: "var(--crit)" }}>{err}{" "}
              <button className="linkish small" onClick={getCode}>Try again</button></p>}
          </Step>
          <Step n={3} art={<span className="art-keys"><kbd>{mac ? "return" : "Enter"}</kbd></span>}>
            <strong>Press Enter.</strong> It may ask once for the password you use to log in to {mac ? "this Mac"
              : "that device"}. Typing it shows nothing on screen; that&apos;s normal, just type it and press Enter.
          </Step>
        </ol>)}

      {os && before && !paired && <Waiting devices={devices} before={before} />}
      {os && code && (
        <>
          <SendLine key={code.code} line={line} expiresAt={code.expiresAt} />
          {new Date(code.expiresAt).getTime() < Date.now() &&
            <button className="linkish small" onClick={getCode}>Get a new line</button>}
        </>)}

      <button className="linkish small" onClick={() => setOther(!other)}>
        {other ? "Hide" : "Can't paste on that device? Use a code it shows instead"}</button>
      {other && (
        <div style={{ marginTop: 8 }}>
          <p className="small muted">Paste <code>curl -fsSL {origin}/install.sh | sh</code> on the device. It shows a code
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
        <p>The Nightlight helper is a small program that runs on your device and reports its health (disk, memory,
          what is running). It never sends the device&apos;s name on the network or its network addresses (host name,
          IP and hardware addresses), files, passwords or keys. Your apps&apos; recent messages (their log lines) are
          sent only after private details are removed on the device, and you can switch that off per app. It changes
          nothing unless you allow that kind of job in the device&apos;s Settings and then approve each one here.</p>
        <p>Pasting the line from another computer you are connected to (over SSH) works just as well.</p>
        <p>To remove it, paste this on the device:</p>
        <Copy text={`curl -fsSL ${origin}/uninstall.sh | sh`} />
        <p className="soon">Coming: the Mac installer, then a Linux package and versions for NAS boxes (home storage).
          Windows isn&apos;t supported yet.</p>
      </details>
    </div>
  );
}
