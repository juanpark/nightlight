"use client";
// Passkeys for expert sessions (WebAuthn). The browser creates a key pair in the person's authenticator (Face ID,
// Touch ID, a phone, a security key); only the public key leaves it. Approving an expert command signs the exact
// command with that key, so Nightlight's cloud can relay a command but never create or change one.

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
