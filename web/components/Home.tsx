"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GoogleAuthProvider, linkWithPopup, signOut, type User } from "firebase/auth";
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
import Chat, { type ChatHandle } from "./Chat";
import TrustPanel from "./TrustPanel";
import Activity from "./Activity";
import DemoTools from "./DemoTools";
import AddDevice from "./AddDevice";
import FirstRun from "./FirstRun";
import "@/app/mobile.css";
import "@/app/shell.css";
import MemoryPanel from "./MemoryPanel";
import { Activity as ActivityIcon, FlaskConical, Globe, House, LogOut, Menu, MessageCircle, Moon, NotebookPen, Plus,
  Radar, ShieldCheck, Sun, X, type LucideIcon } from "lucide-react";
import { Logo } from "@/src/components/brand/Logo";
import { Mascot } from "@/src/components/mascot/Mascot";
import { display, sans } from "@/src/components/landing/fonts";

type Panel = "none" | "trust" | "activity" | "demo" | "add" | "memory" | "watch" | "found";

export default function Home({ user }: { user: User }) {
  const uid = user.uid;
  const me = useUserDoc(uid);
  const gen = me?.demoGeneration;
  const now = useNow();
  const rawDevices = useDevices(uid, gen);
  const links = useLinks(uid, gen);
  const devices = useMemo(() => rawDevices.map((d) => presented(d, now)), [rawDevices, now]);
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
  const open = (p: Panel) => { setMenu(false); setPane("home"); setPanel(p); };
  const [theme, flipTheme] = useTheme();
  function go(g: Go) {
    if (g.to === "drawer") { setPanel("none"); setSelected(g.deviceId); setDrawerTab(g.app ? "apps" : g.tab ?? null); setApp(g.app ?? null); }
    else if (g.to === "panel") setPanel(g.panel);
    else if (g.to === "chat") askChat(g.ask);
  }

  async function saveWithGoogle() {
    const { auth } = await firebase();
    if (auth.currentUser) await linkWithPopup(auth.currentUser, new GoogleAuthProvider()).catch((e) => alertless(e));
  }

  const item = (p: Panel, label: string, Icon: LucideIcon, count?: number) => (
    <button className={`side-item ${panel === p ? "on" : ""}`} aria-current={panel === p ? "page" : undefined}
      onClick={() => open(p)}>
      <Icon size={18} strokeWidth={1.75} aria-hidden /> <span>{label}</span>
      {!!count && <span className="side-count">{count}</span>}
    </button>
  );

  return (
    <div className={`shell ${display.variable} ${sans.variable}`} data-theme={theme}>
      <header className="top">
        <Logo height={22} className="top-logo" />
        <span className="spacer" />
        <button className="icon-btn" aria-expanded={menu} aria-controls="side" onClick={() => setMenu(!menu)}
          aria-label={menu ? "Close menu" : "Open menu"}>{menu ? <X size={20} /> : <Menu size={20} />}</button>
      </header>
      <aside id="side" className={`side ${menu ? "open" : ""}`}>
        <div className="side-brand"><Logo height={26} /></div>
        <button className="icon-btn side-close" aria-label="Close menu" onClick={() => setMenu(false)}><X size={20} /></button>
        {user.isAnonymous
          ? <span className="side-sample" title="These devices are simulated, so you can try things safely">
              <span className="dot sample" aria-hidden /> Sample home, simulated</span>
          : <button className="side-sample as-button" disabled={switching || !me} onClick={toggleSample}
              title="Simulated devices to try things safely">{sampleOn ? "Hide sample home" : "Show sample home"}</button>}
        <nav className="side-nav" aria-label="Main">
          {item("none", "Home", House, needs.length)}
          {item("activity", "Activity", ActivityIcon)}
          {item("trust", "Trust", ShieldCheck)}
          {item("memory", "Memory", NotebookPen)}
          <p className="side-label">Add to your home</p>
          {item("add", "Add a device", Plus)}
          {item("watch", "Watch a website", Globe)}
          {item("found", "Found nearby", Radar, addable(found.items).length)}
        </nav>
        <div className="side-foot">
          {item("demo", "Demo tools", FlaskConical)}
          <button className="side-item" onClick={flipTheme} aria-label={`Switch to ${theme === "night" ? "day" : "night"} theme`}>
            {theme === "night" ? <Sun size={18} strokeWidth={1.75} /> : <Moon size={18} strokeWidth={1.75} />}
            <span>{theme === "night" ? "Day theme" : "Night theme"}</span></button>
          <div className="side-account">
            {user.isAnonymous
              ? <button className="primary side-save" onClick={saveWithGoogle}
                  title="Keep this home by linking a Google account">Save with Google</button>
              : <span className="small muted side-email">{user.email}</span>}
            <button className="side-item" onClick={async () => signOut((await firebase()).auth)}>
              <LogOut size={18} strokeWidth={1.75} /> <span>Sign out</span></button>
          </div>
        </div>
      </aside>
      {menu && <button className="side-scrim" aria-label="Close menu" onClick={() => setMenu(false)} />}
      <div className="main" data-pane={pane}>
        <section className="left">
          {panel === "none" ? <>
            <AwayBanner uid={uid} events={events} onSummarise={(q) => askChat(q)} />
            <div className="panel needs needs-strip" data-state={needs.length ? "needs" : "ok"}>
              <span className="verdict-light" aria-hidden />
              <h1 className="verdict">{verdict(needs)}</h1>
              <span className="spacer" />
              {notify.supported && (
                <button className={`small notify-toggle ${notify.on ? "on" : ""}`} onClick={notify.toggle}
                  aria-pressed={notify.on} title={notify.denied
                    ? "Notifications are blocked for this site in your browser settings"
                    : "Show a notification when something goes wrong, while this tab is open"}>
                  {notify.on ? "Notifying you" : "Notify me"}</button>)}
              <button className="small" onClick={() => askChat("Is anything wrong at home?")}>Check-up now</button>
              {needs.length > 0 && <div className="needs-body">
                <NeedsList needs={needs} actions={actions} devices={devices} onGo={go} showDevice
                  onFollowUp={(id) => { setPane("chat"); chat.current?.followUp(id); }} />
              </div>}
            </div>
            {me && <FirstRun uid={uid} anonymous={user.isAnonymous} devices={devices} discoveries={discoveries}
              expert={expert} onAdd={() => open("add")} onWatch={() => open("watch")} onSave={saveWithGoogle}
              onSample={() => { if (!sampleOn) toggleSample(); }} onGo={go} />}
            <HomeView uid={uid} devices={devices} watches={watches} links={links} marks={marks} selected={selected} now={now}
              onSelect={(id) => { setSelected(id); setDrawerTab(null); setApp(null); }}
              onApp={(id, svcId) => { setSelected(id); setDrawerTab("apps"); setApp(svcId); }} onAsk={askChat}
              settingUp={!me || me.demo?.state !== "ready" || (user.isAnonymous && devices.length === 0)} />
          </> : <div className="page">
            {panel === "trust" && <TrustPanel trust={trust} />}
            {panel === "activity" && <Activity events={events} actions={actions} devices={devices} />}
            {panel === "demo" && <DemoTools devices={devices} />}
            {panel === "memory" && <MemoryPanel />}
            {panel === "watch" && <WatchPanel watches={watches} now={now} />}
            {panel === "found" && <FoundNearby found={found} discoveries={discoveries} devices={devices} onGo={go} />}
            {panel === "add" && <AddDevice anonymous={user.isAnonymous} onSave={saveWithGoogle} devices={devices} />}
          </div>}
        </section>
        {/* the device panel: from the left over the map's edge on a wide screen, a full-height sheet on a phone */}
        {panel === "none" && selected && devices.find((d) => d.id === selected) && (
          <DeviceDrawer uid={uid} generation={gen} actions={actions} device={devices.find((d) => d.id === selected)!}
            needs={marks.get(selected) ?? []} devices={devices} release={release} tab={drawerTab} onTab={setDrawerTab}
            onGo={go} onFollowUp={(id) => { setPane("chat"); chat.current?.followUp(id); }}
            onAsk={(q) => askChat(q)} onClose={closeDrawer} app={app} onApp={setApp} hidden={pane === "chat"} />
        )}
        <aside className="right" aria-label="Ask Nightlight">
          <div className="chat-head">
            <MessageCircle size={18} strokeWidth={1.75} aria-hidden />
            <h2>Ask Nightlight</h2>
          </div>
          <Chat ref={chat} uid={uid} generation={gen} actions={actions} devices={devices} disabled={resetting || !me} />
        </aside>
      </div>
      <nav className="pane-tabs" aria-label="Show">
        <button className={pane === "home" ? "on" : ""} aria-current={pane === "home" ? "page" : undefined}
          onClick={() => setPane("home")}>
          <House size={18} strokeWidth={1.75} aria-hidden /> Home
          {needs.length > 0 && <span className="pane-count">{needs.length}</span>}</button>
        <button className={pane === "chat" ? "on" : ""} aria-current={pane === "chat" ? "page" : undefined}
          onClick={() => setPane("chat")}><MessageCircle size={18} strokeWidth={1.75} aria-hidden /> Chat</button>
      </nav>
      {resetting && <div className="overlay"><div className="modal resetting" role="status">
        <Mascot size={56} mood="thinking" /> <span>Resetting the demo…</span></div></div>}
    </div>
  );
}

// Night or day: follows the system until the person picks one, then remembers it in this browser.
function useTheme(): ["night" | "day", () => void] {
  const [picked, setPicked] = useState<"night" | "day" | null>(null);
  const [system, setSystem] = useState<"night" | "day">("night");
  useEffect(() => {
    try { const t = localStorage.getItem("nl_theme"); if (t === "night" || t === "day") setPicked(t); } catch { /* system */ }
    const q = window.matchMedia("(prefers-color-scheme: light)");
    const read = () => setSystem(q.matches ? "day" : "night");
    read();
    q.addEventListener("change", read);
    return () => q.removeEventListener("change", read);
  }, []);
  const theme = picked ?? system;
  const flip = () => {
    const next = theme === "night" ? "day" : "night";
    setPicked(next);
    try { localStorage.setItem("nl_theme", next); } catch { /* this visit */ }
  };
  return [theme, flip];
}

function alertless(e: unknown) {
  console.warn("link failed", e);
}
