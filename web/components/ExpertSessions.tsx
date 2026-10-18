"use client";
// Expert sessions for one device: the owner's passkey (created once, in this browser) and whether the device has
// pinned it. Pinning happens on the device itself (`nightlight expert`), after comparing the code shown here, so
// Nightlight's cloud can't switch expert sessions on.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { createPasskey, passkeyProblem, passkeysSupported, useAppHost } from "@/lib/passkey";
import type { Device } from "@/lib/types";

const localKey = (uid: string) => `nl_passkey_fp_${uid}`;
const NO_CODE = "?"; // made in this browser, but the browser didn't hand over the key's bytes to work out its code
const OPTIONS_FRESH_MS = 240_000; // the server's registration challenge lasts 300 s; fetch a new one well before

export default function ExpertSessions({ uid, device, open: openFirst = false }: {
  uid: string; device: Device; open?: boolean;
}) {
  const [key, setKey] = useState<{ enabled: boolean; fingerprint?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(openFirst);
  useEffect(() => { api<{ enabled: boolean; fingerprint?: string }>("GET", "/api/expert").then(setKey).catch(() => {}); }, []);
  const on = (device.allowedJobs?.expert ?? []).includes("on");
  // The code worked out in THIS browser when the passkey was made (not taken from the server).
  const [mine, setMine] = useState<string | null>(null);
  useEffect(() => { try { setMine(localStorage.getItem(localKey(uid))); } catch { /* private mode */ } }, [uid]);

  // Safari only lets a tap open the passkey prompt if nothing slow happens first: the registration options are
  // fetched when this opens (and again before they go stale), so the tap's first wait is the prompt itself.
  const appHost = useAppHost();
  // never while a passkey is being made: the server keeps one challenge per account, and a new one would void it
  const canMake = open && key !== null && !key.enabled && passkeysSupported() && !!appHost?.here && !busy;
  const [options, setOptions] = useState<{ value: Parameters<typeof createPasskey>[0]; at: number } | null>(null);
  const [round, setRound] = useState(0);
  useEffect(() => {
    if (!canMake) return;
    let live = true;
    setOptions(null); // a challenge is used once: what was fetched before is spent or about to be replaced
    api<Parameters<typeof createPasskey>[0]>("POST", "/api/expert/register/options", {})
      .then((value) => { if (live) setOptions({ value, at: Date.now() }); })
      .catch((e) => { if (live) setErr(passkeyProblem(e, appHost?.host)); });
    const again = setTimeout(() => setRound((n) => n + 1), OPTIONS_FRESH_MS);
    return () => { live = false; clearTimeout(again); };
  }, [canMake, round, appHost?.host]);

  async function create() {
    if (!options || Date.now() - options.at > OPTIONS_FRESH_MS) { setRound((n) => n + 1); return; }
    setBusy(true); setErr("");
    try {
      const made = await createPasskey(options.value);
      const saved = await api<{ fingerprint: string }>("POST", "/api/expert/register", made.credential);
      const code = made.fingerprint ?? NO_CODE;
      try { localStorage.setItem(localKey(uid), code); } catch { /* private mode */ }
      setMine(code);
      setKey({ enabled: true, ...saved });
    } catch (e) {
      setErr(passkeyProblem(e, appHost?.host)); // the next challenge is fetched when this one is done (busy ends)
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="expert small">
      <button className="linkish" onClick={() => setOpen(!open)}>
        Expert sessions {on ? "(on)" : "(off)"} {open ? "▾" : "▸"}</button>
      {open && (
        <div className="expert-body">
          <p className="muted">For tricky problems: let Nightlight run its own checks on this device, the way an IT
            expert would, and only with your face or fingerprint (a passkey). Checks that only look need one tap per
            15 minutes; anything that changes something needs your tap on each command. The device checks your
            approval itself, so even Nightlight&apos;s own servers can&apos;t run anything without you.{" "}
            <a href="https://github.com/juanpark/nightlight/blob/main/docs/PASSKEYS.md" target="_blank" rel="noreferrer">
              Learn more</a></p>
          <ol>
            <li>Your passkey: {key?.enabled
              ? mine === NO_CODE
                ? <>ready, made in this browser (it didn&apos;t show the key&apos;s code here), server copy{" "}
                    <strong>{key.fingerprint}</strong>: check the device shows that code</>
              : mine
                ? mine === key.fingerprint
                  ? <>ready, code <strong>{mine}</strong></>
                  : <strong style={{ color: "var(--crit)" }}>the server shows a different key ({key.fingerprint}) than
                      the passkey this browser made ({mine}): don&apos;t switch it on anywhere; tell us.</strong>
                : <>ready (made in another browser: compare the code there), server copy <strong>{key.fingerprint}</strong></>
              : !passkeysSupported()
                ? <span className="muted">this browser can&apos;t create passkeys; use Safari, Chrome, Edge or Firefox
                    (up to date) on a phone or computer</span>
              : appHost && !appHost.here
                ? <span className="muted">passkeys work only at <a href={appHost.url}>{appHost.host}</a>; open Nightlight
                    there to make yours</span>
                : <button disabled={busy || !options} onClick={create}>
                    {busy ? "Waiting for your passkey…" : options ? "Create my passkey" : "Getting ready…"}</button>}</li>
            <li>On the device: {on ? <strong>on</strong> : <>run <code className="perm-cmd">nightlight expert</code> there
              (if that says &quot;command not found&quot;: <code className="perm-cmd">~/.local/bin/nightlight expert</code>) and
              check it shows exactly the code above{mine ? <> ({mine})</> : null}.</>}</li>
          </ol>
          {err && <div style={{ color: "var(--crit)" }}>{err}</div>}
        </div>)}
    </section>
  );
}
