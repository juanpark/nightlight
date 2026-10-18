"use client";
import { useEffect, useState } from "react";
import { Cpu, Laptop } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { firebase } from "@/lib/firebase";
import type { Device } from "@/lib/types";
import { leaveLive } from "@/lib/live";
import PairApprove, { type PairResult } from "./PairApprove";

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

/** "Waiting for your device…" until a real device that wasn't there before shows up on the map, or, when a reinstall
 * continues an earlier device, until that device reports after the approval. */
function Waiting({ devices, before, continued }: {
  devices: Device[]; before: Set<string>; continued?: { id: string; since: number };
}) {
  // either way: the server can still add it as new if the earlier device went away before the helper picked it up
  const fresh = devices.find((d) => d.realm === "real" && !before.has(d.id))
    ?? (continued && devices.find((d) => d.id === continued.id && (d.lastSeen?.getTime() ?? 0) > continued.since));
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
        <li><strong>It opens no way in to your computer.</strong> It only reaches out to Nightlight, so your
          computer never shows a security pop-up about it.</li>
        <li><strong>Stays on the machine:</strong> its name and addresses on your network, files, passwords and keys.</li>
        <li><strong>One line removes it</strong>, or remove it from the app.</li>
      </ul>
      <p className="muted">In the first minute: your device&apos;s disk, memory and apps, and <em>Found nearby</em>, the
        printer, TV and phones it can see on your network, by the names they announce.</p>
    </div>
  );
}

const PKG = "/download/Nightlight.pkg";

/** The Mac installer, behind a plain warning first: it isn't signed by Apple yet, so macOS warns about it. Shown only
 * when this site actually serves the package. */
function MacInstaller() {
  const [served, setServed] = useState(false);
  const [asking, setAsking] = useState(false);
  useEffect(() => {
    fetch(PKG, { method: "HEAD" }).then((r) => setServed(r.ok), () => {});
  }, []);
  useEffect(() => {
    if (!asking) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setAsking(false); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [asking]);
  if (!served) return null;
  return (
    <div className="setup-alt">
      <p className="small">Rather not use Terminal on a Mac?{" "}
        <button onClick={() => setAsking(true)}>Mac installer</button></p>
      {asking && (
        <div className="overlay" onClick={(e) => { if (e.target === e.currentTarget) setAsking(false); }}>
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="pkg-title">
            <h3 id="pkg-title">Before you download</h3>
            <p>This installer isn&apos;t signed by Apple yet (signing is pending). macOS will warn that it can&apos;t
              check it for malicious software.</p>
            <p>To open it: right-click the file → <strong>Open</strong>, or <strong>System Settings → Privacy &amp;
              Security → Open Anyway</strong>.</p>
            <p className="small muted">It installs the same helper as the command line.</p>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={() => setAsking(false)}>Cancel</button>
              <a className="button primary" href={PKG} download autoFocus onClick={() => setAsking(false)}>Download anyway</a>
            </div>
          </div>
        </div>)}
    </div>
  );
}

/** How to remove the helper, for each way it was installed. */
function Uninstall({ origin }: { origin: string }) {
  return (
    <details className="small" style={{ marginTop: 8 }}>
      <summary>How to uninstall</summary>
      <p><strong>Installed with the command line:</strong> on the device, run</p>
      <Copy text="nightlight uninstall" />
      <p className="muted">If it says &quot;command not found&quot;, use <code>~/.local/bin/nightlight uninstall</code>,
        or paste this:</p>
      <Copy text={`curl -fsSL ${origin}/uninstall.sh | sh`} />
      <p><strong>Installed with the Mac installer:</strong> run <code>nightlight uninstall</code> in Terminal the same
        way. The installer&apos;s own files need an administrator to remove; if nobody else on this Mac uses
        Nightlight:</p>
      <Copy text="sudo rm -rf '/Library/Application Support/Nightlight' && sudo pkgutil --forget com.nightlight.installer" />
      <p><strong>Easiest:</strong> removing the device in the app (open it on the map → <em>Remove this
        device…</em>) does the uninstall for you.</p>
      <p className="muted">Uninstalling on the device keeps its history in Nightlight: it shows as offline until you
        remove it in the app.</p>
    </details>
  );
}

type Sim = { code: string; name: string; os: string; transcript: string[] };

/** The sample home's pretend install: the lines a real install prints, played one by one, then the same approval a
 * real device asks for. Nothing is installed anywhere; the new device is a sample one. */
function TrySimulated() {
  const [sim, setSim] = useState<Sim | null>(null);
  const [lines, setLines] = useState(0);
  const [done, setDone] = useState<PairResult | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!sim || lines >= sim.transcript.length) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const t = setTimeout(() => setLines(still ? sim.transcript.length : lines + 1), still ? 0 : 250);
    return () => clearTimeout(t);
  }, [sim, lines]);
  async function start(os: Os) {
    setErr(""); setBusy(true); setDone(null);
    try {
      setSim(await api<Sim>("POST", "/api/demo/add_device", { os })); setLines(0);
    } catch (e) {
      setErr(e instanceof ApiError && e.code === "already_added" ? "You already added one; it is on your map."
        : e instanceof ApiError && e.code === "no_sample_home" ? "This works with the sample home showing."
        : e instanceof ApiError && e.code === "live_demo_machine" ? "Not on a live machine: devices can't be added to it."
        : "Couldn't start the simulation. Please try again.");
    } finally { setBusy(false); }
  }
  const played = !!sim && lines >= sim.transcript.length;
  return (
    <div className="try-sim">
      <p className="small"><strong>Try adding one (simulated)</strong>: see what an install looks like, then approve it
        as you would a real device.</p>
      {!sim && (
        <div className="setup-pick" role="group" aria-label="Which kind of device?">
          <button disabled={busy} onClick={() => start("linux")}><Cpu size={22} strokeWidth={1.6} /> Linux or Raspberry Pi</button>
          <button disabled={busy} onClick={() => start("mac")}><Laptop size={22} strokeWidth={1.6} /> A Mac</button>
        </div>)}
      {sim && <>
        <p className="small muted">Simulation: on a real computer you&apos;d paste one line in Terminal.</p>
        <pre className="sim-term" aria-live="polite">{sim.transcript.slice(0, lines).join("\n")}</pre>
        {played && !done && <PairApprove base="/api/demo/pair" initialCode={sim.code} onDone={setDone} />}
        {done && (done.approved
          ? <p className="live-status ok"><span className="dot ok" /> Added: {done.name} is on your map (a sample device).</p>
          : <p className="small">Okay, it was turned away. Nothing was added.</p>)}
      </>}
      {err && <p className="small" style={{ color: "var(--crit-ink)" }}>{err}</p>}
    </div>
  );
}

const Term = ({ text }: { text: string }) => <span className="art-term"><i /><i /><i /><b>{text}</b></span>;

export default function AddDevice({ anonymous, live = false, onSave, devices }: {
  anonymous: boolean; live?: boolean; onSave: () => void; devices: Device[];
}) {
  const [os, setOs] = useState<Os | null>(null);
  const [code, setCode] = useState<{ code: string; expiresAt: string } | null>(null);
  const [before, setBefore] = useState<Set<string> | null>(null);
  const [paired, setPaired] = useState<(PairResult & { at: number }) | null>(null);
  const [origin, setOrigin] = useState("");
  const [err, setErr] = useState("");
  const [other, setOther] = useState(false);
  useEffect(() => { setOrigin(window.location.origin); }, []);

  if (live) {
    return (
      <div className="panel">
        <h3>Try it on your own computer</h3>
        <p>This live machine is a shared demo, so devices can&apos;t be added to it. To put your own laptop or
          Raspberry Pi on a map of your own, leave this machine and sign in with Google (about two minutes).</p>
        <button className="primary" onClick={() => leaveLive()}>Leave and sign in</button>
        <Reassure />
      </div>
    );
  }

  if (anonymous) {
    return (
      <div className="panel">
        <h3>Add a device</h3>
        <TrySimulated />
        <div className="try-real">
          <p className="small"><strong>Do it for real:</strong> your laptop or Raspberry Pi on your own map in about two
            minutes. Real devices belong to an account, so first sign in with Google; this sample home stays.</p>
          <button className="primary" onClick={onSave}>Sign in with Google</button>
        </div>
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
      <p className="small">Nightlight looks after Macs (macOS 10.15+) and Linux computers, including Raspberry Pi.
        Windows PCs, NAS boxes, routers and printers are watched from one of those: install it on one computer and they
        show up under <em>Found nearby</em>.</p>
      <details className="small">
        <summary className="muted">Which devices?</summary>
        <ul style={{ margin: "6px 0", paddingLeft: 20 }}>
          <li><strong>Looked after</strong> (the helper runs on it): disk, memory, apps and services, explained in plain
            words, fixed only after your tap. Linux with systemd (Raspberry Pi OS, Ubuntu, Debian and most others) and
            macOS 10.15 or newer.</li>
          <li><strong>Watched</strong> (seen from a computer with the helper): found on your network, named when it
            announces a name, checked that it still answers; never changed. Routers, NAS boxes, printers, TVs, cameras,
            Windows PCs.</li>
          <li><strong>Watched from the cloud</strong>: checks that a website or online service answers (Watch a
            website).</li>
        </ul>
        <p className="muted" style={{ margin: 0 }}>Windows and NAS boxes are next.</p>
      </details>
      <div className="setup-pick" role="radiogroup" aria-label="Which kind of device?">
        <button role="radio" aria-checked={mac} className={mac ? "on" : ""} onClick={() => pick("mac")}>
          <Laptop size={22} strokeWidth={1.6} /> A Mac</button>
        <button role="radio" aria-checked={os === "linux"} className={os === "linux" ? "on" : ""} onClick={() => pick("linux")}>
          <Cpu size={22} strokeWidth={1.6} /> Linux computer or Raspberry Pi</button>
      </div>

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
            {err && <p className="small" style={{ color: "var(--crit-ink)" }}>{err}{" "}
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

      <MacInstaller />
      <p className="soon small muted">Coming soon: installers for Linux (.deb) and NAS (Docker). Windows isn&apos;t
        supported yet.</p>

      <button className="linkish small" onClick={() => setOther(!other)}>
        {other ? "Hide" : "Can't paste on that device? Use a code it shows instead"}</button>
      {other && (
        <div style={{ marginTop: 8 }}>
          <p className="small muted">Paste <code>curl -fsSL {origin}/install.sh | sh</code> on the device. It shows a code
            like WXYZ-1234 (and a link you can open on your phone). Type the code here:</p>
          {!paired
            ? <PairApprove onApprove={snapshot} onDone={(r) => setPaired({ ...r, at: Date.now() })} />
            : paired.approved
              ? (before && <Waiting devices={devices} before={before}
                  continued={paired.continued ? { id: paired.continued, since: paired.at } : undefined} />)
              : <p className="small">Okay, that device was turned away. Nothing was added.</p>}
        </div>
      )}

      <details className="small" style={{ marginTop: 12 }}>
        <summary>What does the helper do?</summary>
        <p>The Nightlight helper is a small program that runs on your device and reports its health (disk, memory,
          what is running). It never sends the device&apos;s name on the network or its network addresses (host name,
          IP and hardware addresses), files, passwords or keys. Your apps&apos; recent messages (their log lines) are
          sent only after private details are removed on the device, and you can switch that off per app. It changes
          nothing unless you allow that kind of job in the device&apos;s Settings and then approve each one here.</p>
        <p>Pasting the line from another computer you are connected to (over SSH) works just as well.</p>
      </details>
      <Uninstall origin={origin} />
    </div>
  );
}
