"use client";

import { useEffect, useState, type ReactNode } from "react";
import { onAuthStateChanged, type User } from "firebase/auth";
import { firebase } from "@/lib/firebase";
import Home from "@/components/Home";

// The landing page is rendered on the server and shown right away. When
// Firebase reports a signed-in user (returning visitor, or after Try the demo /
// Sign in with Google), the app takes its place.
export function AppGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    let stop = () => {};
    let live = true;
    firebase()
      .then(({ auth }) => {
        if (live) stop = onAuthStateChanged(auth, setUser);
      })
      .catch(() => {
        // No config yet: stay on the landing page; the buttons report the error.
      });
    return () => {
      live = false;
      stop();
    };
  }, []);

  return user ? <Home user={user} /> : <>{children}</>;
}
