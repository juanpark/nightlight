"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FirebaseError } from "firebase/app";
import { GoogleAuthProvider, linkWithPopup, signInWithCredential, signInWithPopup, signOut, type AuthCredential, type User } from "firebase/auth";
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
import AccountSettings from "./AccountSettings";
import Tour from "./Tour";
import { restartTour } from "@/lib/tour";
import { leaveLive, useLive } from "@/lib/live";
import "@/app/mobile.css";
import "@/app/shell.css";
import MemoryPanel from "./MemoryPanel";
import SamplePill from "./SamplePill";
import Sheet from "./Sheet";
import { Activity as ActivityIcon, Bell, DemoTools as FlaskConical, Globe, House, SignOutIcon as LogOut, Menu,
  Chat as MessageCircle, Moon, Memory as NotebookPen, HideChat as PanelRightClose, Plus, FoundNearby as Radar,
  Settings as Gear, Trust as ShieldCheck, Sun, Close as X, type IconType as LucideIcon } from "@/src/components/icons";
import { Logo } from "@/src/components/brand/Logo";
import { Mascot } from "@/src/components/mascot/Mascot";
import { MascotHead } from "@/src/components/mascot/MascotHead";
import { display, sans } from "@/src/components/landing/fonts";

type Panel = "none" | "trust" | "activity" | "demo" | "add" | "memory" | "watch" | "found" | "settings";
const PANEL_NAME: Record<Panel, string> = { none: "Home", trust: "Trust", activity: "Activity", demo: "Demo tools",
  add: "Add a device", memory: "Memory", watch: "Watch a website", found: "Found nearby", settings: "Settings" };

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
  // the panel itself hands focus back to whatever opened it (a device on the map, a link in the strip)
  const closeDrawer = useCallback(() => { setSelected(null); setApp(null); }, []);
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
  const moreBtn = useRef<HTMLButtonElement>(null);
  // the menu: Esc closes it and hands focus back; arrows move between its items
  function menuKeys(e: React.KeyboardEvent<HTMLDivElement>) {
    const items = [...e.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")]
      .filter((b) => b.getClientRects().length > 0);
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") { setMenu(false); moreBtn.current?.focus(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
    }
  }
  useEffect(() => {
    if (menu) requestAnimationFrame(() => document.querySelector<HTMLButtonElement>("#more-menu button")?.focus());
  }, [menu]);
  // whether the verdict strip is on screen; when it isn't, the header carries the verdict
  const stripRef = useRef<HTMLElement>(null);
  const [stripSeen, setStripSeen] = useState(true);
  useEffect(() => {
    const el = stripRef.current;
    if (!el) { setStripSeen(false); return; }
    const io = new IntersectionObserver(([e]) => setStripSeen(e.isIntersecting), { threshold: 0.4 });
    io.observe(el);
    return () => io.disconnect();
  }, [panel, pane]);
  // Wide screens can fold the chat into a slim rail; asking for it from anywhere unfolds it.
  const [folded, setFolded] = useFolded();
  const [chatBusy, setChatBusy] = useState(false);
  const waiting = actions.filter((a) => a.status === "pending").length;
  const headMood = chatBusy ? "busy" : waiting ? "waiting" : "idle"; // an answer being written outranks a card that can wait
  const foldBtn = useRef<HTMLButtonElement>(null);
  const railBtn = useRef<HTMLButtonElement>(null);
  const fold = (f: boolean) => {
    setFolded(f);
    requestAnimationFrame(() => (f ? railBtn : foldBtn).current?.focus()); // focus stays on the control that moved
  };
  const showChat = () => { setPane("chat"); setFolded(false); };
  const askChat = (q: string) => { showChat(); chat.current?.ask(q); };
  // A panel replaces whatever was open over the home (the device panel included), so closing it lands on the home.
  const open = (p: Panel) => { setMenu(false); setPane("home"); setSelected(null); setApp(null); setPanel(p); };
  const [theme, flipTheme] = useTheme();
  // Back closes what is open over the home (a panel or a device) instead of leaving the app, which matters most on a
  // phone where they fill the screen. The entry carries Next's own state so its router treats it as the same page.
  const layerOpen = panel !== "none" || !!selected;
  useEffect(() => {
    if (!layerOpen) return;
    history.pushState({ ...history.state, nlLayer: true }, "");
    const back = () => { setPanel("none"); closeDrawer(); };
    window.addEventListener("popstate", back);
    return () => {
      window.removeEventListener("popstate", back);
      if (history.state?.nlLayer) history.back(); // closed with a button: drop the entry it added
    };
  }, [layerOpen, closeDrawer]);
  function go(g: Go) {
    // on a phone the device panel and the panels live in the Home pane, so a link from the chat switches to it
    if (g.to === "drawer") { setMenu(false); setPane("home"); setPanel("none"); setSelected(g.deviceId);
      // a link names its tab or means the problem itself (Overview); only a tap on the map reopens the last tab used
      setDrawerTab(g.app ? "apps" : g.tab ?? "overview"); setApp(g.app ?? null); }
    else if (g.to === "panel") open(g.panel);
    else if (g.to === "chat") askChat(g.ask);
  }

  // Save with Google: the demo's guest account takes on a Google login and keeps its home. Every outcome says what
  // happened in one plain line (closing the Google window is the person's choice, so that one stays quiet).
  const [saving, setSaving] = useState(false);
  // a Google account that already has its own home can't take this one: say so and offer to sign in to it instead
  const [linkTaken, setLinkTaken] = useState<AuthCredential | null | false>(false); // null: sign in afresh
  const [linkExpired, setLinkExpired] = useState(false);
  const [notice, setNotice] = useState<string | null>(peekNotice);
  useEffect(() => leaveNotice(null), []); // shown once: read on the first render, cleared after it
  const [, redraw] = useState(0);
  const attempt = useRef(0); // only the latest try may update the button or the message
  // Firebase notices a closed Google window only after about 8 s; coming back to the page means it closed, so the
  // button is ready again shortly after (a sign-in that did finish still lands and says so).
  useEffect(() => {
    if (!saving) return;
    let t: ReturnType<typeof setTimeout>;
    const back = () => { t = setTimeout(() => setSaving(false), 1500); };
    window.addEventListener("focus", back);
    return () => { window.removeEventListener("focus", back); clearTimeout(t); };
  }, [saving]);
  async function saveWithGoogle() {
    const mine = ++attempt.current;
    const latest = () => mine === attempt.current;
    setSaving(true);
    setNotice(null);
    const { auth } = await firebase();
    const guest = auth.currentUser;
    try {
      if (!guest) return;
      await linkWithPopup(guest, new GoogleAuthProvider());
      // The same user now has Google: get a token that says so (owner-only requests check it), and redraw, because
      // linking changes the user in place without announcing a sign-in.
      await guest.getIdToken(true);
      setNotice(`Saved. This home now belongs to ${guest.email ?? "your Google account"}; sign in with Google to open it anywhere.`);
      redraw((n) => n + 1);
    } catch (e) {
      const code = e instanceof FirebaseError ? e.code : "";
      if (!latest() && code === "auth/cancelled-popup-request") return; // replaced by a newer try
      if (code === "auth/credential-already-in-use" || code === "auth/email-already-in-use") {
        setLinkExpired(false);
        setLinkTaken(GoogleAuthProvider.credentialFromError(e as FirebaseError));
      } else if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request" || code === "auth/user-cancelled") {
        // closed on purpose: nothing to say
      } else if (code === "auth/popup-blocked") {
        setNotice("Your browser blocked the Google window. Allow pop-ups for this site, then try again.");
      } else if (code === "auth/network-request-failed") {
        setNotice("Couldn't reach Google. Check your connection, then try again.");
      } else {
        console.warn("link failed", e);
        setNotice("Couldn't connect your Google account. Please try again.");
      }
    } finally {
      if (latest()) setSaving(false);
    }
  }

  // the visit stays until one of these succeeds (the app restarts for that account)
  async function useTakenAccount() {
    const { auth } = await firebase();
    leaveNotice("This Google account already had a Nightlight home, so we opened it. This visit's practice changes weren't kept.");
    if (linkTaken) {
      // the credential from the failed link can expire: then ask for a fresh Google sign-in instead
      await signInWithCredential(auth, linkTaken).catch(() => { leaveNotice(null); setLinkTaken(null); setLinkExpired(true); });
    } else {
      await signInWithPopup(auth, new GoogleAuthProvider()).catch(() => {
        leaveNotice(null); setNotice("Couldn't open that account. Please try again."); });
    }
  }

  const foundCount = addable(found.items).length;
  const sample = user.isAnonymous || sampleOn;
  // the More menu: everything that isn't the home itself, in the order an owner reaches for it
  const item = (p: Panel, label: string, Icon: LucideIcon, count?: number, tour?: string) => (
    <button role="menuitem" className={`more-item ${panel === p ? "on" : ""}`} aria-current={panel === p ? "page" : undefined}
      onClick={() => open(p)} data-tour={tour}>
      <Icon size={18} aria-hidden /> <span>{label}</span>
      {!!count && <span className="more-count" aria-label={`${count} new`}>{count}</span>}
    </button>
  );

  return (
    <div className={`shell ${display.variable} ${sans.variable}`} data-theme={theme} data-chat={folded ? "folded" : undefined}>
      <header className="top">
        <Logo height={22} className="top-logo" />
        {user.isAnonymous
          ? <SamplePill onTry={async () => { await saveWithGoogle(); open("add"); }} />
          : <button className="sample-pill practice" disabled={switching || !me} onClick={toggleSample}
              title="A safe pretend home to try fixes; your real devices aren't touched">
              <span className="dot sample" aria-hidden />{sampleOn ? "Hide practice home" : "Practice home"}</button>}
        {/* the verdict, here whenever the strip itself is out of sight (scrolled away, or a panel is open) */}
        <button className="top-verdict" data-state={needs.length ? "needs" : "ok"} data-shown={stripSeen ? undefined : "yes"}
          onClick={() => { setPanel("none"); setPane("home"); requestAnimationFrame(() =>
            stripRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })); }}
          tabIndex={stripSeen ? -1 : undefined} aria-hidden={stripSeen ? true : undefined}>
          <span className="verdict-light" aria-hidden />{needs.length ? `${needs.length} need you` : "All good"}</button>
        <span className="spacer" />
        <button className="top-add" onClick={() => open("add")} data-tour="add-device" aria-current={panel === "add" ? "page" : undefined}>
          <Plus size={18} aria-hidden /><span>Add a device</span></button>
        <div className="more">
          <button ref={moreBtn} className="top-more" aria-haspopup="menu" aria-expanded={menu} aria-controls="more-menu"
            onClick={() => setMenu(!menu)} data-tour="more" aria-label="More" title="More">
            <Menu size={18} aria-hidden /><span className="top-more-word">More</span>
            {foundCount > 0 && <span className="more-dot" aria-label={`${foundCount} found nearby`} />}</button>
          {menu && <>
            <button className="more-scrim" aria-label="Close menu" tabIndex={-1} onClick={() => setMenu(false)} />
            <div id="more-menu" className="more-menu" role="menu" aria-label="More" onKeyDown={menuKeys}>
              {user.isAnonymous && <button role="menuitem" className="primary more-save" onClick={() => { setMenu(false); saveWithGoogle(); }}
                disabled={saving} title="Keep this home by linking a Google account">{saving ? "Opening Google…" : "Save with Google"}</button>}
              <p className="more-label">Your home</p>
              {item("activity", "Activity", ActivityIcon)}
              {item("trust", "Trust", ShieldCheck, undefined, "trust")}
              {!live && item("memory", "Memory", NotebookPen)}
              <p className="more-label">Add to your home</p>
              <span className="more-phone">{item("add", "Add a device", Plus)}</span>
              {!user.isAnonymous && <span className="more-phone">
                <button role="menuitem" className="more-item" disabled={switching || !me} onClick={() => { setMenu(false); toggleSample(); }}>
                  <House size={18} aria-hidden /><span>{sampleOn ? "Hide practice home" : "Practice home"}</span></button></span>}
              {item("found", "Found nearby", Radar, foundCount, "found-nearby")}
              {item("watch", "Watch a website", Globe)}
              <hr />
              {notify.supported && <button role="menuitemcheckbox" aria-checked={notify.on} className="more-item"
                onClick={notify.toggle} title={notify.denied ? "Notifications are blocked for this site in your browser settings"
                  : "Show a notification when something goes wrong, while this tab is open"}>
                <Bell size={18} aria-hidden /><span>{notify.on ? "Notifying you" : "Notify me"}</span>
                <span className={`more-switch ${notify.on ? "on" : ""}`} aria-hidden /></button>}
              <button role="menuitem" className="more-item" onClick={flipTheme}>
                {theme === "night" ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
                <span>{theme === "night" ? "Day theme" : "Night theme"}</span></button>
              {sample && item("demo", "Demo tools", FlaskConical)}
              {item("settings", "Settings", Gear, undefined, "settings")}
              <hr />
              {!user.isAnonymous && <span className="small muted more-email" title={user.email ?? undefined}>{user.email}</span>}
              <button role="menuitem" className="more-item" onClick={async () => live ? leaveLive() : signOut((await firebase()).auth)}>
                <LogOut size={18} aria-hidden /> <span>{live ? "Leave" : "Sign out"}</span></button>
            </div>
          </>}
        </div>
      </header>
      <div className="main" data-pane={pane}>
        <section className="left">
          {notice && <div className="panel save-notice" role="status">
            <span>{notice}</span>
            <button className="linkish small" onClick={() => setNotice(null)}>Dismiss</button></div>}
          {linkTaken !== false && (
            <div className="panel" role="alert">
              <p style={{ marginTop: 0 }}>That Google account already has its own Nightlight home, so this visit can&apos;t
                be saved into it.</p>
              <div className="actions" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="primary" onClick={useTakenAccount}>{linkExpired ? "Sign in with Google again"
                  : "Sign in to that account instead"}</button>
                <button onClick={() => setLinkTaken(false)}>Stay here</button>
              </div>
              {linkExpired && <p className="small" style={{ color: "var(--crit-ink)" }}>That sign-in expired. Sign in with
                Google again.</p>}
              <p className="small muted">This visit&apos;s practice changes won&apos;t carry over.</p>
            </div>)}
          <AwayBanner uid={visit} events={events} onSummarise={(q) => askChat(q)} />
            <section ref={stripRef} className="panel needs-strip" data-state={needs.length ? "needs" : "ok"} data-tour="needs"
              aria-labelledby="verdict">
              <div className="strip-head">
                <span className="verdict-light" aria-hidden />
                <div className="verdict-text">
                  <h1 className="verdict" id="verdict">{verdict(needs)}</h1>
                  {!needs.length && <p className="verdict-sub">Nothing needs you right now. Nightlight keeps watching.</p>}
                </div>
                <button className="small" onClick={() => askChat("Is anything wrong at home?")}>Ask if anything&apos;s wrong</button>
              </div>
              {needs.length > 0 && <NeedsList needs={needs} actions={actions} devices={devices} onGo={go} showDevice plain
                onFollowUp={(id) => { showChat(); chat.current?.followUp(id); }} />}
            </section>
            {me && !live && !user.isAnonymous && <FirstRun uid={visit} devices={devices} discoveries={discoveries}
              expert={expert} onAdd={() => open("add")} onWatch={() => open("watch")}
              onSample={() => { if (!sampleOn) toggleSample(); }} onGo={go} />}
            <HomeView uid={uid} devices={devices} watches={watches} links={links} marks={marks} selected={selected} now={now}
              onSelect={(id) => { setSelected(id); setDrawerTab(null); setApp(null); }}
              onApp={(id, svcId) => { setSelected(id); setDrawerTab("apps"); setApp(svcId); }} onAsk={askChat}
              settingUp={!me || me.demo?.state !== "ready" || (user.isAnonymous && devices.length === 0)} />
        </section>
        {/* panels float over the home as a sheet from the right; the map stays where it was underneath */}
        {panel !== "none" && <Sheet label={PANEL_NAME[panel]} onClose={() => setPanel("none")}>
            {panel === "trust" && <TrustPanel trust={trust} devices={devices} sample={user.isAnonymous || sampleOn} onGo={go} />}
            {panel === "activity" && <Activity events={events} actions={actions} devices={devices} />}
            {panel === "demo" && <DemoTools devices={devices} />}
            {panel === "settings" && <AccountSettings me={me} anonymous={user.isAnonymous} live={live} onSave={saveWithGoogle}
              onTour={() => { setPanel("none"); setPane("home"); restartTour(visit); }} />}
            {panel === "memory" && !live && <MemoryPanel />}
            {panel === "watch" && <WatchPanel watches={watches} now={now} />}
            {panel === "found" && <FoundNearby found={found} discoveries={discoveries} devices={devices} onGo={go} />}
            {panel === "add" && <AddDevice anonymous={user.isAnonymous} live={live} onSave={saveWithGoogle} devices={devices} />}
        </Sheet>}
        {/* the device panel: from the left over the map's edge on a wide screen, a full-height sheet on a phone */}
        {panel === "none" && selected && devices.find((d) => d.id === selected) && (
          <DeviceDrawer uid={uid} generation={gen} actions={actions} device={devices.find((d) => d.id === selected)!}
            needs={marks.get(selected) ?? []} devices={devices} release={release} tab={drawerTab} onTab={setDrawerTab}
            onGo={go} onFollowUp={(id) => { showChat(); chat.current?.followUp(id); }}
            onAsk={(q) => askChat(q)} onClose={closeDrawer} app={app} onApp={setApp} hidden={pane === "chat"} />
        )}
        <aside className="right" aria-label="Ask Nightlight">
          <button ref={railBtn} className="chat-rail" onClick={() => fold(false)} title="Show the chat"
            aria-label={`Show the chat${waiting ? `, ${waiting} ${waiting === 1 ? "card" : "cards"} to approve` : ""}`}>
            <MascotHead size={34} mood={headMood} />
            <span className="rail-label">Chat</span>
            {waiting > 0 && <span className="rail-count"><b>{waiting}</b> to approve</span>}
          </button>
          <Chat ref={chat} uid={uid} generation={gen} actions={actions} devices={devices} disabled={resetting || !me}
            onBusy={setChatBusy} onShowMap={() => { setPanel("none"); setPane("home"); }}
            title={<><MascotHead size={28} mood={headMood} /><h2>Ask Nightlight</h2></>}
            end={<button ref={foldBtn} className="chat-fold" onClick={() => fold(true)} title="Hide the chat"
              aria-label="Hide the chat"><PanelRightClose size={18} aria-hidden /></button>} />
        </aside>
      </div>
      <nav className="pane-tabs" aria-label="Show">
        <button className={pane === "home" ? "on" : ""} aria-current={pane === "home" ? "page" : undefined}
          onClick={() => setPane("home")}>
          <House size={18} aria-hidden /> Home
          {needs.length > 0 && <span className="pane-count">{needs.length}</span>}</button>
        <button className={pane === "chat" ? "on" : ""} aria-current={pane === "chat" ? "page" : undefined}
          onClick={() => setPane("chat")}><MessageCircle size={18} aria-hidden /> Chat</button>
      </nav>
      <Tour uid={visit} ready={!!me && me.demo?.state === "ready" && (devices.length > 0 || !user.isAnonymous)
        && (!live || machine.machineReady)}
        state={{ anonymous: user.isAnonymous, hasCard: actions.some((a) => a.status === "pending"),
          realDevices: devices.filter((d) => d.realm === "real" && d.kind !== "watched").length }} />
      {resetting && <div className="overlay"><div className="modal resetting" role="status">
        <Mascot size={56} mood="thinking" /> <span>Resetting the sample home…</span></div></div>}
    </div>
  );
}

// Whether the chat is folded on a wide screen, remembered in this browser.
function useFolded(): [boolean, (f: boolean) => void] {
  const [folded, setFolded] = useState(false);
  useEffect(() => {
    try { setFolded(localStorage.getItem("nl_chat") === "folded"); } catch { /* open */ }
  }, []);
  const set = (f: boolean) => {
    setFolded(f);
    try { localStorage.setItem("nl_chat", f ? "folded" : "open"); } catch { /* this visit */ }
  };
  return [folded, set];
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
  // on the page too, so what sits outside the shell (the live machine bar, the tour) wears the same theme
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    return () => { delete document.documentElement.dataset.theme; };
  }, [theme]);
  const flip = () => {
    const next = theme === "night" ? "day" : "night";
    setPicked(next);
    try { localStorage.setItem("nl_theme", next); } catch { /* this visit */ }
  };
  return [theme, flip];
}

// A message that has to outlive a switch of account (the app restarts for the new user), kept for this tab only.
function leaveNotice(text: string | null) {
  try { if (text) sessionStorage.setItem("nl_notice", text); else sessionStorage.removeItem("nl_notice"); } catch { /* lost */ }
}
function peekNotice(): string | null {
  try { return sessionStorage.getItem("nl_notice"); } catch { return null; }
}
