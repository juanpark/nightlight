"use client";
import { useEffect, useState } from "react";
import { onAuthStateChanged, type User } from "firebase/auth";
import { firebase } from "@/lib/firebase";
import { isLiveSession, useLive } from "@/lib/live";
import SignIn from "@/components/SignIn";
import Home from "@/components/Home";
import LiveSession, { LiveStarting } from "@/components/LiveSession";

export default function Page() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [onLive, setOnLive] = useState<{ uid: string; live: boolean } | null>(null); // a live demo machine's account?
  const live = useLive();
  useEffect(() => {
    let stop = () => {};
    firebase().then(({ auth }) => { stop = onAuthStateChanged(auth, setUser); });
    return () => stop();
  }, []);
  useEffect(() => {
    if (!user || user.isAnonymous) return;
    let on = true;
    isLiveSession(user).then((v) => { if (on) setOnLive({ uid: user.uid, live: v }); });
    return () => { on = false; };
  }, [user]);
  if (live.starting) return <LiveStarting />;
  if (user === undefined) return <div className="signin"><p className="muted">Loading…</p></div>;
  if (!user) return <SignIn />;
  const known = user.isAnonymous ? false : onLive?.uid === user.uid ? onLive.live : null;
  if (known === null) return <div className="signin"><p className="muted">Loading…</p></div>;
  return <>{known && <LiveSession key={user.uid} />}<Home user={user} live={known} /></>;
}
