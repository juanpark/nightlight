"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { GoogleAuthProvider, linkWithPopup, signOut, type User } from "firebase/auth";
import { api } from "@/lib/api";
import { firebase } from "@/lib/firebase";
import { presented, useActions, useDevices, useEvents, useNow, useTrust, useUserDoc } from "@/lib/data";
import Board from "./Board";
import DeviceDrawer from "./DeviceDrawer";
import Chat, { type ChatHandle } from "./Chat";
import TrustPanel from "./TrustPanel";
import Activity from "./Activity";
import DemoTools from "./DemoTools";
import AddDevice from "./AddDevice";
import MemoryPanel from "./MemoryPanel";

type Panel = "none" | "trust" | "activity" | "demo" | "add" | "memory";

export default function Home({ user }: { user: User }) {
  const uid = user.uid;
  const me = useUserDoc(uid);
  const gen = me?.demoGeneration;
  const now = useNow();
  const rawDevices = useDevices(uid, gen);
  const devices = useMemo(() => rawDevices.map((d) => presented(d, now)), [rawDevices, now]);
  const actions = useActions(uid, gen);
  const events = useEvents(uid, gen);
  const trust = useTrust(uid, gen);
  const [selected, setSelected] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>("none");
  const chat = useRef<ChatHandle>(null);
  const starting = useRef(false);

  // First visit: the one-click demo gets the sample home; a signed-in owner starts with only their own devices.
  useEffect(() => {
    if (me === null && !starting.current) {
      starting.current = true;
      api("POST", "/api/demo/start", { template: user.isAnonymous ? "home-pi" : "empty" })
        .catch(() => { starting.current = false; });
    }
  }, [me, user.isAnonymous]);
  const sampleOn = me?.template !== "empty";
  const [switching, setSwitching] = useState(false);
  async function toggleSample() {
    setSwitching(true);
    try { await api("POST", "/api/demo/template", { template: sampleOn ? "empty" : "home-pi" }); }
    finally { setSwitching(false); }
  }

  const needs = devices.filter((d) => d.status === "crit" || d.status === "warn").length;
  const pending = actions.filter((a) => a.status === "pending").length;
  const resetting = me?.demo?.state === "resetting";
  const toggle = (p: Panel) => setPanel((cur) => (cur === p ? "none" : p));

  async function saveWithGoogle() {
    const { auth } = await firebase();
    if (auth.currentUser) await linkWithPopup(auth.currentUser, new GoogleAuthProvider()).catch((e) => alertless(e));
  }

  return (
    <div className="shell">
      <header className="top">
        <div className="brand"><span className="bulb" /> Nightlight</div>
        {user.isAnonymous
          ? <span className="pill">Sample home: simulated</span>
          : <button className="small" disabled={switching || !me} onClick={toggleSample}
              title="Simulated devices to try things safely">{sampleOn ? "Hide sample home" : "Show sample home"}</button>}
        <span className="spacer" />
        <button onClick={() => toggle("trust")}>Trust</button>
        <button onClick={() => toggle("activity")}>Activity</button>
        <button onClick={() => toggle("memory")}>Memory</button>
        <button onClick={() => toggle("add")}>Add a device</button>
        <button onClick={() => toggle("demo")}>Demo tools</button>
        {user.isAnonymous
          ? <button onClick={saveWithGoogle} title="Keep this home by linking a Google account">Save with Google</button>
          : <span className="small muted">{user.email}</span>}
        <button onClick={async () => signOut((await firebase()).auth)}>Sign out</button>
      </header>
      <div className="main">
        <section className="left">
          <div className="panel needs">
            <strong>{needs ? `${needs} ${needs === 1 ? "thing needs" : "things need"} you` : "All quiet at home"}</strong>
            {pending > 0 && <span className="pill">{pending} waiting for your approval</span>}
            <span className="spacer" />
            <button onClick={() => chat.current?.ask("Is anything wrong at home?")}>Check-up now</button>
          </div>
          {panel === "trust" && <TrustPanel trust={trust} />}
          {panel === "activity" && <Activity events={events} actions={actions} devices={devices} />}
          {panel === "demo" && <DemoTools devices={devices} />}
          {panel === "memory" && <MemoryPanel />}
          {panel === "add" && <AddDevice anonymous={user.isAnonymous} onSave={saveWithGoogle} devices={devices} />}
          <Board devices={devices} selected={selected} onSelect={setSelected} />
          {selected && devices.find((d) => d.id === selected) && (
            <DeviceDrawer uid={uid} device={devices.find((d) => d.id === selected)!}
              onAsk={(q) => chat.current?.ask(q)} onClose={() => setSelected(null)} />
          )}
        </section>
        <aside className="right">
          <Chat ref={chat} uid={uid} actions={actions} devices={devices} disabled={resetting || !me} />
        </aside>
      </div>
      {resetting && <div className="overlay"><div className="modal">Resetting the demo…</div></div>}
    </div>
  );
}

function alertless(e: unknown) {
  console.warn("link failed", e);
}
