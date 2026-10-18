"use client";
import { useEffect, useState } from "react";
import { onAuthStateChanged, type User } from "firebase/auth";
import { firebase } from "@/lib/firebase";
import { liveAccount, useLive } from "@/lib/live";
import SignIn from "@/components/SignIn";
import Home from "@/components/Home";
import LiveSession, { LiveStarting } from "@/components/LiveSession";

// "/" is the landing page and sign-in in one: rendered on the server, and
// replaced by the app once someone is signed in.
export default function Page() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [onLive, setOnLive] = useState<{ uid: string; account: string | null } | null>(null); // on a live demo machine?
  const live = useLive();
  useEffect(() => {
    let stop = () => {};
    firebase().then(({ auth }) => { stop = onAuthStateChanged(auth, setUser); });
    return () => stop();
  }, []);
  useEffect(() => {
    if (!user || user.isAnonymous) return;
    let on = true;
    liveAccount(user).then((a) => { if (on) setOnLive({ uid: user.uid, account: a }); });
    return () => { on = false; };
  }, [user]);
  if (live.starting) return <LiveStarting />;
  if (user === undefined) return <div className="signin"><p className="muted">Loading…</p></div>;
  if (!user) return <SignIn />;
  const known = user.isAnonymous ? null : onLive?.uid === user.uid ? onLive.account : undefined;
  if (known === undefined) return <div className="signin"><p className="muted">Loading…</p></div>;
  return <>{known && <LiveSession key={user.uid} />}<Home user={user} account={known ?? undefined} /></>;
}
