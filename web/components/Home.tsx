"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GoogleAuthProvider, signInWithPopup, signOut, type User } from "firebase/auth";
import { api } from "@/lib/api";
import { firebase } from "@/lib/firebase";
import { presented, useActions, useDevices, useLinks, useDiscoveries, useEvents, useExpertStatus, useNow, useRelease, useTrust,
  useUserDoc, useWatches } from "@/lib/data";
import { byDevice, needsYou, verdict, type Go, useDismissed } from "@/lib/needsYou";
import NeedsList from "./NeedsList";
import FoundNearby from "./FoundNearby";
import { addable, useFound } from "@/lib/found";
import { useEventNotifications, useNotifySetting } from "@/lib/notify";
import WatchPanel from "./WatchPanel";
import AwayBanner from "./AwayBanner";
import HomeView from "./map/HomeView";
import DeviceDrawer, { type Tab } from "./DeviceDrawer";
import AccountSettings from "./AccountSettings";
import Tour from "./Tour";
import { restartTour } from "@/lib/tour";
import { leaveLive, useLive } from "@/lib/live";
import Chat, { type ChatHandle } from "./Chat";
import TrustPanel from "./TrustPanel";
import SampleTour from "./SampleTour";
import Activity from "./Activity";
import DemoTools from "./DemoTools";
import AddDevice from "./AddDevice";
import FirstRun from "./FirstRun";
import "@/app/mobile.css";
import MemoryPanel from "./MemoryPanel";

type Panel = "none" | "trust" | "activity" | "demo" | "add" | "memory" | "watch" | "found" | "settings";

// account: on a live demo machine, the machine's account, whose data this visit (its own throwaway user) sees
export default function Home({ user, account }: { user: User; account?: string }) {
  const live = !!account;
  const uid = account ?? user.uid; // the data (Firestore users/{uid}/…)
  const visit = user.uid; // what this browser remembers (tours, dismissed hints)
  const me = useUserDoc(uid);
  const gen = me?.demoGeneration;
  const now = useNow();
  const rawDevices = useDevices(uid, gen);
  const links = useLinks(uid, gen);
  const machine = useLive();
  // on a live machine, a report from before this visit is the clean copy's: the device is still starting
  const since = live ? machine.leaseStart ?? Infinity : undefined;
  const devices = useMemo(() => rawDevices.map((d) => {
    const p = presented(d, now);
    return since !== undefined && d.realm === "real" && !((d.lastSeen?.getTime() ?? 0) > since)
      ? { ...p, status: "offline" as const, health: "unknown" as const, findings: [], starting: true } : p;
  }), [rawDevices, now, since]);
  const actions = useActions(uid, gen);
  const events = useEvents(uid, gen);
  const trust = useTrust(uid, gen);
  const watches = useWatches(uid);
  const discoveries = useDiscoveries(uid);
  const found = useFound(discoveries, now);
  const release = useRelease();
  const expert = useExpertStatus();
  // Everything waiting for the person, derived once: tile marks, the device panel and the strip use the same items.
  const [dismissed] = useDismissed();
  const needs = useMemo(() => needsYou({ devices, actions, trust, found: addable(found.items), release, expert, now,
    dismissed }), [devices, actions, trust, found.items, release, expert, now, dismissed]);
  const marks = useMemo(() => byDevice(needs), [needs]);
  const [drawerTab, setDrawerTab] = useState<Tab | null>(null); // null: the last tab used for that kind of device
  const notify = useNotifySetting();
  useEventNotifications(events, notify.on);
  const [selected, setSelected] = useState<string | null>(null);
  const [app, setApp] = useState<string | null>(null); // one app on the selected device, opened on its own
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const closeDrawer = useCallback(() => {
    // keyboard focus goes back to the device on the map, when it was in the panel
    const back = selectedRef.current;
    const inPanel = document.activeElement?.closest(".drawer.side");
    setSelected(null); setApp(null);
    if (inPanel && back) requestAnimationFrame(() =>
      (document.querySelector(`.react-flow__node[data-id="${CSS.escape(back)}"]`) as HTMLElement | null)?.focus());
  }, []);
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
  const sampleShown = !live && (user.isAnonymous || sampleOn); // Demo tools only work on the sample home
  const [switching, setSwitching] = useState(false);
  async function toggleSample() {
    setSwitching(true);
    try { await api("POST", "/api/demo/template", { template: sampleOn ? "empty" : "home-pi" }); }
    finally { setSwitching(false); }
  }

  const resetting = me?.demo?.state === "resetting";
  // Phones show one pane at a time (Home or Chat, switched by the tab bar) and fold the header into a menu.
  const [pane, setPane] = useState<"home" | "chat">("home");
  const [menu, setMenu] = useState(false);
  const askChat = (q: string) => { setPane("chat"); chat.current?.ask(q); };
  const [more, setMore] = useState(false); // wide screens: the secondary header links, folded under More
  useEffect(() => {
    if (!more) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !(e.target as Element).closest?.(".more")) setMore(false);
    };
    document.addEventListener("keydown", close); document.addEventListener("pointerdown", close);
    return () => { document.removeEventListener("keydown", close); document.removeEventListener("pointerdown", close); };
  }, [more]);
  const toggle = (p: Panel) => { setMenu(false); setMore(false); setPane("home"); setPanel((cur) => (cur === p ? "none" : p)); };
  function go(g: Go) {
    if (g.to === "drawer") { setSelected(g.deviceId); setDrawerTab(g.app ? "apps" : g.tab ?? null); setApp(g.app ?? null); }
    else if (g.to === "panel") setPanel(g.panel);
    else if (g.to === "chat") askChat(g.ask);
  }

  // "Try the real app": a plain Google sign-in; the anonymous sample visit is simply left behind (a signed-in owner can
  // open the sample home again with Take the tour)
  async function signInReal() {
    const { auth } = await firebase();
    await signInWithPopup(auth, new GoogleAuthProvider()).catch(alertless);
  }

  return (
    <div className="shell">
      <header className="top">
        <div className="brand"><span className="bulb" /> Nightlight</div>
        {user.isAnonymous
          ? <span className="pill">Sample home: simulated</span>
          : !live && <button className="small" disabled={switching || !me} onClick={toggleSample}
              title="A pretend home with a guided tour; your real devices aren't touched">{sampleOn ? "Hide the tour" : "Take the tour (simulated)"}</button>}
        <span className="spacer" />
        <button className="menu-toggle" aria-expanded={menu} onClick={() => setMenu(!menu)}>{menu ? "Close" : "Menu"}</button>
        <nav className={`top-nav ${menu ? "open" : ""}`}>
        <button data-tour="add-device" onClick={() => toggle("add")}>Add a device</button>
        <button onClick={() => toggle("watch")}>Watch a website</button>
        <button data-tour="found-nearby" onClick={() => toggle("found")}>Found nearby</button>
        {user.isAnonymous
          && <button onClick={signInReal} title="Sign in with Google and add your own Mac or Raspberry Pi">Try the real app</button>}
        <div className="more">
          <button className="more-toggle" data-tour="more" aria-expanded={more} aria-haspopup="true"
            onClick={() => setMore(!more)}>More</button>
          <div className={`more-list ${more ? "open" : ""}`}>
            <button onClick={() => toggle("trust")}>Trust</button>
            <button onClick={() => toggle("activity")}>Activity</button>
            {!live && <button onClick={() => toggle("memory")}>Memory</button>}
            {sampleShown && <button onClick={() => toggle("demo")}>Demo tools</button>}
            <button onClick={() => toggle("settings")}>Settings</button>
            {!user.isAnonymous && <span className="small muted" title={user.email ?? undefined}>{user.email}</span>}
            <button onClick={async () => live ? leaveLive() : signOut((await firebase()).auth)}>Sign out</button>
          </div>
        </div>
        </nav>
      </header>
      <div className="main" data-pane={pane}>
        <section className="left">
          {me && sampleShown && <SampleTour uid={visit} actions={actions} devices={devices} discoveries={discoveries}
            onAsk={askChat} onPanel={(p) => { setPanel(p); setPane("home"); }} onSave={signInReal} />}
          <AwayBanner uid={visit} events={events} onSummarise={(q) => askChat(q)} />
          <div className="panel needs needs-strip" data-tour="needs">
            <strong className="verdict">{verdict(needs)}</strong>
            <span className="spacer" />
            {notify.supported && (
              <button className={`small notify-toggle ${notify.on ? "on" : ""}`} onClick={notify.toggle}
                aria-pressed={notify.on} title={notify.denied
                  ? "Notifications are blocked for this site in your browser settings"
                  : "Show a notification when something goes wrong, while this tab is open"}>
                {notify.on ? "Notifying you" : "Notify me"}</button>)}
            <button onClick={() => askChat("Is anything wrong with my servers?")}>Ask if anything&apos;s wrong</button>
            <div style={{ flexBasis: "100%" }}>
              <NeedsList needs={needs} actions={actions} devices={devices} onGo={go} showDevice
                onFollowUp={(id) => { setPane("chat"); chat.current?.followUp(id); }} />
            </div>
          </div>
          {panel === "trust" && <TrustPanel trust={trust} devices={devices} sample={user.isAnonymous || sampleOn} onGo={go} />}
          {panel === "activity" && <Activity events={events} actions={actions} devices={devices} />}
          {panel === "demo" && sampleShown && <DemoTools devices={devices} />}
          {panel === "settings" && <AccountSettings me={me} anonymous={user.isAnonymous} live={live} onSave={signInReal}
            onTour={() => { setPanel("none"); setPane("home"); restartTour(visit); }} />}
          {panel === "memory" && !live && <MemoryPanel />}
          {panel === "watch" && <WatchPanel watches={watches} now={now} />}
          {me && !live && !user.isAnonymous && <FirstRun uid={visit} devices={devices} discoveries={discoveries}
            expert={expert} onAdd={() => setPanel("add")} onWatch={() => setPanel("watch")}
            onSample={() => { if (!sampleOn) toggleSample(); }} onGo={go} />}
          {panel === "found" && <FoundNearby found={found} discoveries={discoveries} devices={devices} onGo={go} sample={sampleShown} />}
          {panel === "add" && <AddDevice anonymous={user.isAnonymous} live={live} sample={sampleShown} onSave={signInReal} devices={devices} />}
          <HomeView uid={uid} devices={devices} watches={watches} links={links} marks={marks} selected={selected} now={now}
            onSelect={(id) => { setSelected(id); setDrawerTab(null); setApp(null); }}
            onApp={(id, svcId) => { setSelected(id); setDrawerTab("apps"); setApp(svcId); }} onAsk={askChat}
            settingUp={!me || me.demo?.state !== "ready" || (user.isAnonymous && devices.length === 0)} />
        </section>
        {/* the device panel: from the left over the map's edge on a wide screen, a full-height sheet on a phone */}
        {selected && devices.find((d) => d.id === selected) && (
          <DeviceDrawer uid={uid} generation={gen} actions={actions} device={devices.find((d) => d.id === selected)!}
            needs={marks.get(selected) ?? []} devices={devices} release={release} tab={drawerTab} onTab={setDrawerTab}
            onGo={go} onFollowUp={(id) => { setPane("chat"); chat.current?.followUp(id); }}
            onAsk={(q) => askChat(q)} onClose={closeDrawer} app={app} onApp={setApp} hidden={pane === "chat"} />
        )}
        <aside className="right">
          <Chat ref={chat} uid={uid} generation={gen} actions={actions} devices={devices} disabled={resetting || !me}
            onShowMap={() => { setPanel("none"); setPane("home"); }} />
        </aside>
      </div>
      <nav className="pane-tabs" aria-label="Show">
        <button className={pane === "home" ? "on" : ""} onClick={() => setPane("home")}>
          Home{needs.length > 0 && <span className="pane-count">{needs.length}</span>}</button>
        <button className={pane === "chat" ? "on" : ""} onClick={() => setPane("chat")}>Chat</button>
      </nav>
      {/* the sample home has its own guided checklist: the popover tour waits (Settings can still start it) */}
      <Tour uid={visit} ready={!!me && me.demo?.state === "ready" && (devices.length > 0 || !user.isAnonymous)
        && (!live || machine.machineReady) && !sampleShown}
        state={{ anonymous: user.isAnonymous, hasCard: actions.some((a) => a.status === "pending"),
          realDevices: devices.filter((d) => d.realm === "real" && d.kind !== "watched").length }} />
      {resetting && <div className="overlay"><div className="modal">Resetting the sample home…</div></div>}
    </div>
  );
}

function alertless(e: unknown) {
  console.warn("link failed", e);
}
