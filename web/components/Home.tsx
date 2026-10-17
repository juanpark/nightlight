"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { GoogleAuthProvider, linkWithPopup, signOut, type User } from "firebase/auth";
import { api } from "@/lib/api";
import { firebase } from "@/lib/firebase";
import { presented, useActions, useDevices, useDiscoveries, useEvents, useExpertStatus, useNow, useRelease, useTrust,
  useUserDoc, useWatches } from "@/lib/data";
import { byDevice, needsYou, verdict, type Go, useDismissed } from "@/lib/needsYou";
import NeedsList from "./NeedsList";
import FoundNearby from "./FoundNearby";
import { useEventNotifications, useNotifySetting } from "@/lib/notify";
import WatchPanel from "./WatchPanel";
import WatchedRow from "./WatchedRow";
import AwayBanner from "./AwayBanner";
import Board from "./Board";
import DeviceDrawer from "./DeviceDrawer";
import Chat, { type ChatHandle } from "./Chat";
import TrustPanel from "./TrustPanel";
import Activity from "./Activity";
import DemoTools from "./DemoTools";
import AddDevice from "./AddDevice";
import FirstRun from "./FirstRun";
import "@/app/mobile.css";
import MemoryPanel from "./MemoryPanel";

type Panel = "none" | "trust" | "activity" | "demo" | "add" | "memory" | "watch" | "found";

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
  const watches = useWatches(uid);
  const discoveries = useDiscoveries(uid);
  const release = useRelease();
  const expert = useExpertStatus();
  // Everything waiting for the person, derived once: tile marks, the device panel and the strip use the same items.
  const [dismissed] = useDismissed();
  const needs = useMemo(() => needsYou({ devices, actions, trust, discoveries, release, expert, now, dismissed }),
    [devices, actions, trust, discoveries, release, expert, now, dismissed]);
  const marks = useMemo(() => byDevice(needs), [needs]);
  const [drawerTab, setDrawerTab] = useState<"overview" | "about" | "settings">("overview");
  const notify = useNotifySetting();
  useEventNotifications(events, notify.on);
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

  const [tagFilter, setTagFilter] = useState<string[]>([]);
  const allTags = useMemo(() => [...new Set([...devices, ...watches].flatMap((d) => d.tags ?? []))].sort(),
    [devices, watches]);
  const visible = tagFilter.length === 0 ? devices : devices.filter((d) => tagFilter.some((t) =>
    t === "Sample" ? d.realm !== "real" : (d.tags ?? []).includes(t)));
  // Watched websites are never samples: under a filter they show only when they carry one of its tags.
  const visibleWatches = tagFilter.length === 0 ? watches
    : watches.filter((w) => tagFilter.some((t) => (w.tags ?? []).includes(t)));
  const resetting = me?.demo?.state === "resetting";
  // Phones show one pane at a time (Home or Chat, switched by the tab bar) and fold the header into a menu.
  const [pane, setPane] = useState<"home" | "chat">("home");
  const [menu, setMenu] = useState(false);
  const askChat = (q: string) => { setPane("chat"); chat.current?.ask(q); };
  const toggle = (p: Panel) => { setMenu(false); setPane("home"); setPanel((cur) => (cur === p ? "none" : p)); };
  function go(g: Go) {
    if (g.to === "drawer") { setSelected(g.deviceId); setDrawerTab(g.tab ?? "overview"); }
    else if (g.to === "panel") setPanel(g.panel);
    else if (g.to === "chat") askChat(g.ask);
  }

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
        <button className="menu-toggle" aria-expanded={menu} onClick={() => setMenu(!menu)}>{menu ? "Close" : "Menu"}</button>
        <nav className={`top-nav ${menu ? "open" : ""}`}>
        <button onClick={() => toggle("trust")}>Trust</button>
        <button onClick={() => toggle("activity")}>Activity</button>
        <button onClick={() => toggle("memory")}>Memory</button>
        <button onClick={() => toggle("add")}>Add a device</button>
        <button onClick={() => toggle("watch")}>Watch a website</button>
        <button onClick={() => toggle("found")}>Found nearby</button>
        <button onClick={() => toggle("demo")}>Demo tools</button>
        {user.isAnonymous
          ? <button onClick={saveWithGoogle} title="Keep this home by linking a Google account">Save with Google</button>
          : <span className="small muted">{user.email}</span>}
        <button onClick={async () => signOut((await firebase()).auth)}>Sign out</button>
        </nav>
      </header>
      <div className="main" data-pane={pane}>
        <section className="left">
          <AwayBanner uid={uid} events={events} onSummarise={(q) => askChat(q)} />
          <div className="panel needs needs-strip">
            <strong className="verdict">{verdict(needs)}</strong>
            <span className="spacer" />
            {notify.supported && (
              <button className={`small notify-toggle ${notify.on ? "on" : ""}`} onClick={notify.toggle}
                aria-pressed={notify.on} title={notify.denied
                  ? "Notifications are blocked for this site in your browser settings"
                  : "Show a notification when something goes wrong, while this tab is open"}>
                {notify.on ? "Notifying you" : "Notify me"}</button>)}
            <button onClick={() => askChat("Is anything wrong at home?")}>Check-up now</button>
            <div style={{ flexBasis: "100%" }}>
              <NeedsList needs={needs} actions={actions} devices={devices} onGo={go} showDevice
                onFollowUp={(id) => { setPane("chat"); chat.current?.followUp(id); }} />
            </div>
          </div>
          {panel === "trust" && <TrustPanel trust={trust} />}
          {panel === "activity" && <Activity events={events} actions={actions} devices={devices} />}
          {panel === "demo" && <DemoTools devices={devices} />}
          {panel === "memory" && <MemoryPanel />}
          {panel === "watch" && <WatchPanel watches={watches} now={now} />}
          {me && <FirstRun uid={uid} anonymous={user.isAnonymous} devices={devices} discoveries={discoveries}
            expert={expert} onAdd={() => setPanel("add")} onWatch={() => setPanel("watch")} onSave={saveWithGoogle}
            onSample={() => { if (!sampleOn) toggleSample(); }} onGo={go} />}
          {panel === "found" && <FoundNearby discoveries={discoveries} />}
          {panel === "add" && <AddDevice anonymous={user.isAnonymous} onSave={saveWithGoogle} devices={devices} />}
          {(allTags.length > 0 || devices.some((d) => d.realm !== "real")) && (
            <div className="chips" aria-label="Show only">
              <button className={tagFilter.length === 0 ? "on" : ""} onClick={() => setTagFilter([])}>All</button>
              {[...allTags, ...(devices.some((d) => d.realm !== "real") ? ["Sample"] : [])].map((t) => (
                <button key={t} className={tagFilter.includes(t) ? "on" : ""} onClick={() =>
                  setTagFilter((cur) => cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t])}>{t}</button>
              ))}
            </div>
          )}
          <Board devices={visible} selected={selected} onSelect={(id) => { setSelected(id); setDrawerTab("overview"); }}
            marks={marks}
            settingUp={!me || me.demo?.state !== "ready" || (user.isAnonymous && devices.length === 0)} />
          <WatchedRow watches={visibleWatches} now={now} onAsk={(q) => askChat(q)} />
          {selected && devices.find((d) => d.id === selected) && (
            <DeviceDrawer uid={uid} generation={gen} actions={actions} device={devices.find((d) => d.id === selected)!}
              needs={marks.get(selected) ?? []} devices={devices} release={release} tab={drawerTab} onTab={setDrawerTab}
              onGo={go} onFollowUp={(id) => { setPane("chat"); chat.current?.followUp(id); }}
              onAsk={(q) => askChat(q)} onClose={() => setSelected(null)} />
          )}
        </section>
        <aside className="right">
          <Chat ref={chat} uid={uid} generation={gen} actions={actions} devices={devices} disabled={resetting || !me} />
        </aside>
      </div>
      <nav className="pane-tabs" aria-label="Show">
        <button className={pane === "home" ? "on" : ""} onClick={() => setPane("home")}>
          Home{needs.length > 0 && <span className="pane-count">{needs.length}</span>}</button>
        <button className={pane === "chat" ? "on" : ""} onClick={() => setPane("chat")}>Chat</button>
      </nav>
      {resetting && <div className="overlay"><div className="modal">Resetting the demo…</div></div>}
    </div>
  );
}

function alertless(e: unknown) {
  console.warn("link failed", e);
}
