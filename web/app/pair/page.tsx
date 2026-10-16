"use client";
// /pair?code=WXYZ-1234: the page a phone opens from the QR code a device shows. Sign in with Google (real devices
// belong to an account, never to a demo session), check which device asked, then Approve.
import { useEffect, useState } from "react";
import {
  GoogleAuthProvider, linkWithPopup, onAuthStateChanged, signInWithCredential, signInWithPopup, type User,
} from "firebase/auth";
import { FirebaseError } from "firebase/app";
import { firebase } from "@/lib/firebase";
import PairApprove, { type PairResult } from "@/components/PairApprove";

export default function PairPage() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [code, setCode] = useState("");
  const [done, setDone] = useState<PairResult | null>(null);
  const [err, setErr] = useState("");
  const [, rerender] = useState(0);
  useEffect(() => {
    setCode(new URLSearchParams(window.location.search).get("code") ?? "");
    let stop = () => {};
    firebase().then(({ auth }) => { stop = onAuthStateChanged(auth, setUser); });
    return () => stop();
  }, []);

  async function google() {
    setErr("");
    const { auth } = await firebase();
    const provider = new GoogleAuthProvider();
    try {
      // A demo (anonymous) session keeps its sample home by linking; otherwise sign in normally.
      if (auth.currentUser?.isAnonymous) await linkWithPopup(auth.currentUser, provider);
      else await signInWithPopup(auth, provider);
    } catch (e) {
      const cred = e instanceof FirebaseError && e.code === "auth/credential-already-in-use"
        ? GoogleAuthProvider.credentialFromError(e) : null;
      if (cred) await signInWithCredential(auth, cred).catch(() => setErr("Sign-in didn't finish. Please try again."));
      else setErr("Sign-in didn't finish. Please try again.");
    }
    // linkWithPopup changes the same user object without firing onAuthStateChanged: re-read it.
    setUser(auth.currentUser);
    rerender((n) => n + 1);
  }

  let body: React.ReactNode;
  if (user === undefined) body = <p className="muted">Loading…</p>;
  else if (!user || user.isAnonymous) {
    body = (
      <>
        <h1>Add a device</h1>
        <p className="muted">A device asked to join your Nightlight. Real devices belong to your account, so please
          sign in with Google first{user?.isAnonymous ? " (your demo home comes with you)" : ""}.</p>
        <button className="primary" onClick={google}>Sign in with Google</button>
        {err && <p className="small" style={{ color: "var(--crit)" }}>{err}</p>}
      </>
    );
  } else if (done) {
    body = done.approved ? (
      <>
        <h1>Approved</h1>
        <p>{done.name} will appear on your map in a moment. You can close this page.</p>
        <a className="linkbtn" href="/">Open my map</a>
      </>
    ) : (
      <>
        <h1>Turned away</h1>
        <p>That device wasn’t added. Nothing changed.</p>
        <a className="linkbtn" href="/">Open my map</a>
      </>
    );
  } else {
    body = (
      <>
        <h1>Add a device</h1>
        <p className="small muted">Signed in as {user.email}. Check the code matches the one on your device.</p>
        <PairApprove initialCode={code} onDone={setDone} />
      </>
    );
  }

  return (
    <div className="pair-page">
      <div className="modal">
        <div className="brand"><span className="bulb" /> Nightlight</div>
        {body}
      </div>
    </div>
  );
}
