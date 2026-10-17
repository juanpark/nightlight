"use client";

import { useEffect, useState, type ReactNode } from "react";
import { onAuthStateChanged, type User } from "firebase/auth";
import { firebase } from "@/lib/firebase";
import Home from "@/components/Home";
import { Mascot } from "@/src/components/mascot/Mascot";
import { display, sans } from "@/src/components/landing/fonts";

// The landing page is rendered on the server and shown right away. When
// Firebase reports a signed-in user (returning visitor, or after Try the demo /
// Sign in with Google), the app takes its place.
//
// A returning visitor would see the landing page flash while Firebase restores
// the session, so we remember "signed in" in localStorage; a script in the root
// layout reads it before the first paint, swaps the landing page for a
// loading screen in the visitor's theme, and AppGate clears it once Firebase
// answers.
const SESSION_KEY = "nl-session";

function rememberSession(signedIn: boolean) {
  try {
    if (signedIn) localStorage.setItem(SESSION_KEY, "1");
    else localStorage.removeItem(SESSION_KEY);
  } catch {}
  const root = document.documentElement.dataset;
  delete root.session;
  delete root.theme; // only set for the loading screen; the app shell carries its own
}

// The mascot on patrol while the session comes back. Fades in after a beat so a
// quick restore shows nothing but the night background.
function SessionLoader() {
  return (
    <div className={`session-loader ${display.variable} ${sans.variable}`} role="status">
      <Mascot size={112} mood="working" />
      <p>Checking on your home…</p>
    </div>
  );
}

export function AppGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    let stop = () => {};
    let live = true;
    firebase()
      .then(({ auth }) => {
        if (live)
          stop = onAuthStateChanged(auth, (u) => {
            rememberSession(!!u);
            setUser(u);
          });
      })
      .catch(() => {
        rememberSession(false);
        // No config yet: stay on the landing page; the buttons report the error.
      });
    return () => {
      live = false;
      stop();
    };
  }, []);

  return user ? <Home key={user.uid} user={user} /> : (
    <>
      <SessionLoader />
      <div className="landing-gate">{children}</div>
    </>
  ); // a new account starts the app afresh
}
