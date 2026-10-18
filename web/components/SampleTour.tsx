"use client";
// The sample home's guided tour: a docked guide at the top of the home pane. Each step has a title, one sentence of why
// and one main button that does it; it ticks itself off from what really happens (an answer finishing, a card done, a
// device on the map), so it is a guide, not a slideshow. Any step can be opened from the row of steps, in any order.
// Only on the sample home; progress is kept in this browser.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import { useFollowed } from "@/lib/follow";
import type { Action, Device, Discovery } from "@/lib/types";
import { ArrowTo, Caret, Check } from "@/src/components/icons";

type StepId = "ask" | "approve" | "break" | "nearby" | "add" | "trust";
type Saved = { done: StepId[]; open: boolean; started?: number; base?: number; asked?: number; brokeAt?: number };
type Step = { id: StepId; title: string; why: string; act: ReactNode; hint?: string; status?: string };

const ASK = "Is anything wrong with my servers?";
const LAG = "Minecraft is laggy, what's going on?";
const key = (uid: string) => `nl_sample_tour_${uid}`;
function load(uid: string): Saved {
  try { const v = JSON.parse(localStorage.getItem(key(uid)) ?? ""); if (v && Array.isArray(v.done)) return v; } catch { /* fresh */ }
  return { done: [], open: true };
}

export default function SampleTour({ uid, actions, devices, discoveries, onAsk, onPanel, onSave }: {
  uid: string; actions: Action[]; devices: Device[]; discoveries: Discovery[];
  onAsk: (q: string) => void; onPanel: (p: "found" | "add" | "trust") => void; onSave: () => void;
}) {
  const [s, setS] = useState<Saved>({ done: [], open: true });
  const [note, setNote] = useState("");
  const [view, setView] = useState<StepId | null>(null); // a step opened from the row; otherwise the next one to do
  const [praise, setPraise] = useState(""); // "Done: Ask what's wrong", for a few seconds after a step ticks
  const loaded = useRef(false);
  const before = useRef<StepId[] | null>(null); // what was done last time we looked (restored progress isn't news)
  useEffect(() => {
    const v = load(uid); before.current = v.done;
    setS({ ...v, started: v.started ?? Date.now() }); loaded.current = true;
  }, [uid]);
  useEffect(() => { if (loaded.current) try { localStorage.setItem(key(uid), JSON.stringify(s)); } catch { /* this visit only */ } }, [uid, s]);
  const f = useFollowed();
  const tick = (id: StepId) => setS((c) => c.done.includes(id) ? c : { ...c, done: [...c.done, id] });
  const has = (id: StepId) => s.done.includes(id);
  const own = devices.filter((d) => d.kind !== "watched").length;
  const hasCard = actions.some((a) => a.status === "pending");

  // ticks from what really happened
  // the answer the tour's own question started (the next one after the tap), finished well
  useEffect(() => { if (s.asked !== undefined && f.seq === s.asked + 1 && f.done && f.ok) tick("ask"); }, [f.seq, f.done, f.ok, s.asked]);
  // only jobs from this visit's tour count (the sample home comes with some history)
  useEffect(() => {
    if (s.started && actions.some((a) => a.status === "done" && a.decision?.by === "user"
      && (a.createdAt?.getTime() ?? 0) >= s.started! - 60000)) tick("approve");
  }, [actions, s.started]);
  useEffect(() => {
    // it offers a backup first, or (with a fresh backup already) the restart itself
    if (s.brokeAt && actions.some((a) => (a.type === "backup_world" || (a.type === "restart_server" && a.deviceId === "game-1"))
      && (a.createdAt?.getTime() ?? 0) >= s.brokeAt! - 5000)) tick("break");
  }, [actions, s.brokeAt]);
  useEffect(() => { if (discoveries.some((d) => d.items.length > 0)) tick("nearby"); }, [discoveries]);
  useEffect(() => {
    if (s.base === undefined && own > 0) setS((c) => ({ ...c, base: own }));
    else if (s.base !== undefined && own > s.base) tick("add");
  }, [own, s.base]);

  // a step that ticks says so, then the guide moves on to the next one (a step opened from the row moves on too)
  useEffect(() => {
    const prev = before.current;
    // (the first pass after a load still holds the empty default: wait for the restored list)
    if (!loaded.current || !prev || s.done.length < prev.length) return;
    before.current = s.done;
    const fresh = s.done.find((id) => !prev.includes(id));
    if (!fresh) return;
    setPraise(TITLE[fresh]); setNote("");
    setView((v) => (v === fresh ? null : v));
    const t = setTimeout(() => setPraise(""), 5000);
    return () => clearTimeout(t);
  }, [s.done]);

  async function breakIt() {
    setNote("");
    try {
      await api("POST", "/api/demo/inject", { kind: "server_lagging", deviceId: "game-1" });
      setS((c) => ({ ...c, brokeAt: Date.now() }));
    } catch (e) {
      setNote(e instanceof ApiError && e.status === 422 ? "Minecraft is already lagging, so go ahead and ask about it."
        : "Couldn't make it lag. Try again in a moment.");
      if (e instanceof ApiError && e.status === 422) setS((c) => ({ ...c, brokeAt: c.brokeAt ?? Date.now() }));
    }
  }
  function showCard() {
    const el = document.querySelector<HTMLElement>(".chat-log [data-tour=card]") ?? document.querySelector<HTMLElement>("[data-tour=card]");
    if (!el) { setNote("The card isn't on screen yet. Ask what's wrong first, and it appears in the chat."); return; }
    setNote("");
    onAsk(""); // brings the chat into view on a phone (an empty question is ignored)
    el.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    el.classList.add("tour-flash");
    setTimeout(() => el.classList.remove("tour-flash"), 2400);
  }

  const asking = s.asked !== undefined && f.seq === s.asked + 1;
  const askFailed = asking && f.done && !f.ok;
  const steps: Step[] = [
    { id: "ask", title: TITLE.ask, why: "Nightlight looks at every device before it answers.",
      act: <button className="primary" disabled={!f.done} onClick={() => { setS((c) => ({ ...c, asked: f.seq })); onAsk(ASK); }}>
        {f.done ? <>Ask &ldquo;{ASK}&rdquo;</> : "Checking…"}</button>,
      status: !f.done ? "Nightlight is checking your devices. The answer is coming in the chat."
        : askFailed ? "That answer didn't finish. Ask again." : undefined,
      hint: "Watch the steps appear as it checks, and the Pi glow on the map." },
    { id: "approve", title: TITLE.approve, why: "Nothing changes until you tap Approve on its card.",
      act: hasCard ? <button className="primary" onClick={showCard}>Show me the card</button>
        : <button onClick={() => { setNote(""); setView("ask"); }}>Ask what&apos;s wrong first</button>,
      hint: hasCard ? "The Pi's disk goes from 94% to about 61%." : "The card appears in the chat once Nightlight has answered." },
    { id: "break", title: TITLE.break, why: "Make a problem, then see how Nightlight handles it.",
      act: s.brokeAt
        ? <span className="tour-acts"><button className="primary" onClick={() => onAsk(LAG)}>Ask about it</button>
          <button onClick={breakIt}>Make it lag again</button></span>
        : <button className="primary" onClick={breakIt}>Make Minecraft lag</button>,
      status: s.brokeAt ? "Minecraft is lagging now." : undefined,
      hint: "It offers a backup before restarting." },
    { id: "nearby", title: TITLE.nearby, why: "Your computers spot the printer, TV and router on the network.",
      act: <button className="primary" onClick={() => onPanel("found")}>Look nearby</button> },
    { id: "add", title: TITLE.add, why: "See what installing on a computer looks like, then approve it.",
      act: <button className="primary" onClick={() => onPanel("add")}>Try adding one</button> },
    { id: "trust", title: TITLE.trust, why: "After three good clean-ups of the same kind, Nightlight offers to handle it on its own.",
      act: <button className="primary" onClick={() => { tick("trust"); onPanel("trust"); }}>Open Trust</button> },
  ];
  const count = steps.filter((x) => has(x.id)).length;
  const next = steps.find((x) => !has(x.id));
  const shown = steps.find((x) => x.id === view) ?? next;
  const finished = !next;
  const after = shown && steps.slice(steps.indexOf(shown) + 1).concat(steps).find((x) => !has(x.id) && x !== shown);

  return (
    <section className="panel sample-tour" aria-label="Your tour" data-open={s.open || undefined}>
      <button className="tour-head" aria-expanded={s.open} aria-controls="tour-body"
        onClick={() => setS((c) => ({ ...c, open: !c.open }))}>
        <strong className="tour-name">Your tour</strong>
        <span className="tour-count">{finished ? "All done" : `${count} of ${steps.length} done`}</span>
        {!s.open && next && <span className="tour-peek">Next: {next.title}</span>}
        <span className="tour-fold">{s.open ? "Hide" : "Show"}<Caret size={12} className="caret" aria-hidden /></span>
      </button>
      {/* how far along, at a glance, even folded */}
      <div className="tour-meter" aria-hidden>
        {steps.map((x) => <span key={x.id} className={has(x.id) ? "done" : x === shown && s.open ? "now" : ""} />)}
      </div>
      {s.open && <div id="tour-body" className="tour-body">
        <ol className="tour-steps" aria-label="Steps">
          {steps.map((x, i) => (
            <li key={x.id}>
              <button className={`tour-step ${has(x.id) ? "done" : ""}`} aria-current={x === shown ? "step" : undefined}
                onClick={() => { setNote(""); setView(x === next ? null : x.id); }}>
                <span className="tour-num" aria-hidden>{has(x.id) ? <Check size={11} /> : i + 1}</span>
                {x.title}{has(x.id) && <span className="sr-only"> (done)</span>}</button>
            </li>))}
        </ol>
        <p className="tour-praise" role="status">{praise && <><Check size={14} aria-hidden /> Done: {praise}.</>}</p>
        {shown ? (
          <div className="tour-now" key={shown.id}>
            <h2 className="tour-title">{shown.title}{has(shown.id) && <span className="tour-was"> · done</span>}</h2>
            <p className="tour-why">{shown.why}</p>
            <div className="tour-act">
              {shown.act}
              {/* a step can be skipped (or done some other way) without blocking the rest */}
              {!has(shown.id) ? <button className="linkish small tour-skip" onClick={() => tick(shown.id)}>Skip this step</button>
                : after && <button className="linkish small tour-skip" onClick={() => setView(after === next ? null : after.id)}>
                  Next: {after.title}</button>}
            </div>
            {(note || shown.status) && <p className="small tour-status" role="status">{note || shown.status}</p>}
            {shown.hint && <p className="small muted tour-hint">{shown.hint}</p>}
          </div>
        ) : null}
        {finished && !view && (
          <div className="tour-now tour-fin">
            <h2 className="tour-title">That&apos;s the tour</h2>
            <p className="tour-why">You&apos;ve seen it ask first, fix with your OK, and earn trust. The real thing runs on your
              own Mac or Raspberry Pi and takes about two minutes to add.</p>
            <div className="tour-act"><button className="primary" onClick={onSave}>Try the real app<ArrowTo size={14} aria-hidden /></button>
              <button className="linkish small tour-skip" onClick={() => setS((c) => ({ ...c, open: false }))}>Hide the tour</button></div>
          </div>)}
        <p className="small muted tour-foot">
          <span>Pretend devices, real Gemini: answers take a few seconds.</span>
          {!finished && <button className="linkish small" onClick={onSave}>Try it on your own computer</button>}
        </p>
      </div>}
    </section>
  );
}

const TITLE: Record<StepId, string> = {
  ask: "Ask what's wrong", approve: "Approve the fix", break: "Break something yourself",
  nearby: "Find devices nearby", add: "Add a device", trust: "Earn trust",
};
