"use client";
import { useEffect, useState } from "react";
import { onAuthStateChanged, type User } from "firebase/auth";
import { firebase } from "@/lib/firebase";
import SignIn from "@/components/SignIn";
import Home from "@/components/Home";

export default function Page() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useEffect(() => {
    let stop = () => {};
    firebase().then(({ auth }) => { stop = onAuthStateChanged(auth, setUser); });
    return () => stop();
  }, []);
  if (user === undefined) return <div className="signin"><p className="muted">Loading…</p></div>;
  return user ? <Home user={user} /> : <SignIn />;
}
