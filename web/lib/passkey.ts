"use client";
// Passkeys for expert sessions (WebAuthn). The browser creates a key pair in the person's authenticator (Face ID,
// Touch ID, a phone, a security key); only the public key leaves it. Approving an expert command signs the exact
// command with that key, so Nightlight's cloud can relay a command but never create or change one.
import { useEffect, useState } from "react";
import { ApiError } from "./api";
import { firebase } from "./firebase";

const b64u = (buf: ArrayBuffer | Uint8Array) => {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = "";
  bytes.forEach((b) => { s += String.fromCharCode(b); });
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

const fromB64u = (s: string) => {
  const pad = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  return Uint8Array.from(atob(pad), (c) => c.charCodeAt(0));
};

export const passkeysSupported = () =>
  typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials;

/** Create the passkey (registration). `options` come from the API (challenge, rp, user). */
export async function createPasskey(options: {
  challenge: string; rp: { id: string; name: string }; user: { id: string; name: string; displayName: string };
}) {
  const cred = await navigator.credentials.create({
    publicKey: {
      challenge: fromB64u(options.challenge),
      rp: options.rp,
      user: { ...options.user, id: fromB64u(options.user.id) },
      pubKeyCredParams: [{ type: "public-key", alg: -7 }], // ES256 (P-256): what the helper verifies with openssl
      authenticatorSelection: { userVerification: "required", residentKey: "preferred" },
      timeout: 60000,
      attestation: "none",
    },
  }) as PublicKeyCredential | null;
  if (!cred) throw new Error("cancelled");
  const r = cred.response as AuthenticatorAttestationResponse;
  const spki = r.getPublicKey?.(); // the key's own bytes, straight from the authenticator
  return {
    credential: {
      id: cred.id, rawId: b64u(cred.rawId), type: cred.type,
      response: { clientDataJSON: b64u(r.clientDataJSON), attestationObject: b64u(r.attestationObject) },
    },
    fingerprint: spki ? await fingerprintOf(new Uint8Array(spki)) : null,
  };
}

/** Sign a challenge (the hash of an expert command) with the passkey: returns what the device verifies. */
export async function signWithPasskey(challenge: string, credentialId: string, rpId: string) {
  const cred = await navigator.credentials.get({
    publicKey: {
      challenge: fromB64u(challenge), rpId, userVerification: "required", timeout: 60000,
      allowCredentials: [{ type: "public-key", id: fromB64u(credentialId) }],
    },
  }) as PublicKeyCredential | null;
  if (!cred) throw new Error("cancelled");
  const r = cred.response as AuthenticatorAssertionResponse;
  return {
    authenticatorData: b64u(r.authenticatorData), clientDataJSON: b64u(r.clientDataJSON), signature: b64u(r.signature),
  };
}

/** 64 bits of SHA-256 over the key's DER bytes, as XXXX-XXXX-XXXX-XXXX: the device works out the same code from the
 * key it receives, so a key swapped on the way can't match. */
export async function fingerprintOf(der: Uint8Array) {
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", der as BufferSource));
  const hex = Array.from(hash.slice(0, 8)).map((b) => b.toString(16).padStart(2, "0")).join("").toUpperCase();
  return hex.match(/.{4}/g)!.join("-");
}

/** The same canonical JSON as the API and the helper (sorted keys, no spaces), so the challenge is computed here
 * from exactly what the card shows. */
function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (v && typeof v === "object") {
    return `{${Object.keys(v as object).sort().map((k) => `${JSON.stringify(k)}:${canonical((v as Record<string, unknown>)[k])}`).join(",")}}`;
  }
  return JSON.stringify(v);
}

export async function challengeFor(payload: Record<string, unknown>) {
  return b64u(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(payload))));
}

/** Where passkeys work: the app's own address (from /config). Elsewhere (a preview, another host) the browser refuses. */
export function useAppHost(): { url: string; host: string; here: boolean } | null {
  const [v, setV] = useState<{ url: string; host: string; here: boolean } | null>(null);
  useEffect(() => {
    firebase().then(({ config }) => {
      const url = config.appUrl ?? window.location.origin;
      let host = url;
      try { host = new URL(url).host; } catch { /* keep as given */ }
      const local = /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname);
      setV({ url, host, here: local || window.location.origin === new URL(url).origin });
    }).catch(() => setV(null));
  }, []);
  return v;
}

/** What went wrong with a passkey or a card, in one plain sentence. */
export function passkeyProblem(e: unknown, host?: string): string {
  if (e instanceof DOMException || (e instanceof Error && /^(NotAllowed|Security|InvalidState|Abort|NotSupported)Error$/.test(e.name))) {
    const name = (e as Error).name;
    if (name === "NotAllowedError" || name === "AbortError") return "Cancelled or timed out. Tap again.";
    if (name === "SecurityError") return `Passkeys work only at ${host ?? "Nightlight's own address"}.`;
    if (name === "InvalidStateError") return "This device already has a passkey for Nightlight. Use that one.";
    if (name === "NotSupportedError") return "This browser can't make that kind of passkey. Try Safari, Chrome or a phone.";
  }
  if (e instanceof ApiError) {
    return ({
      expired: "This card expired. Ask again and Nightlight will put up a fresh one.",
      stale: "This card expired. Ask again and Nightlight will put up a fresh one.",
      not_pending: "This card was already decided.",
      not_found: "This card is gone. Ask again and Nightlight will put up a fresh one.",
      no_passkey: "Make your passkey first: open a device, then Settings, then Expert sessions.",
      start_again: "That took too long. Tap again to start over.",
      passkey_not_accepted: "Nightlight couldn't accept that passkey. Tap again, or try another phone or computer.",
      passkey_type_unsupported: "That passkey is a kind your devices can't check. Try another phone or computer.",
      signature_not_accepted: "That passkey didn't sign it. Use the passkey you made for Nightlight.",
      sign_in_required: "Sign in with Google first: a passkey belongs to an account.",
      rate_limited: "Too many tries. Wait a minute, then tap again.",
    } as Record<string, string>)[e.code] ?? (e.status === 429 ? "Too many tries. Wait a minute, then tap again."
      : e.status >= 500 ? "Nightlight had a problem. Tap again in a moment." : "That didn't work. Tap again.");
  }
  if (e instanceof Error && e.message && !/^(cancelled|Failed to fetch|Load failed|NetworkError)/i.test(e.message)) return e.message;
  if (e instanceof Error && /fetch|network|load failed/i.test(e.message)) return "Couldn't reach Nightlight. Check the connection and tap again.";
  return "Cancelled or timed out. Tap again.";
}
