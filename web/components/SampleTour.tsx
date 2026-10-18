"use client";
// The sample home's guided tour: a docked checklist at the top of the home pane. Each step says why in one sentence and
// has one button that does it; it ticks itself off from what really happens (an answer finishing, a card done, a
// device on the map), so it is a guide, not a slideshow. Only on the sample home; progress is kept in this browser.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import { useFollowed } from "@/lib/follow";
import type { Action, Device, Discovery } from "@/lib/types";

type StepId = "ask" | "approve" | "break" | "nearby" | "add" | "trust";
type Saved = { done: StepId[]; open: boolean; started?: number; base?: number; asked?: number; brokeAt?: number };

const ASK = "Is anything wrong at home?";
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
  const loaded = useRef(false);
  useEffect(() => { const v = load(uid); setS({ ...v, started: v.started ?? Date.now() }); loaded.current = true; }, [uid]);
  useEffect(() => { if (loaded.current) try { localStorage.setItem(key(uid), JSON.stringify(s)); } catch { /* this visit only */ } }, [uid, s]);
  const f = useFollowed();
  const tick = (id: StepId) => setS((c) => c.done.includes(id) ? c : { ...c, done: [...c.done, id] });
  const has = (id: StepId) => s.done.includes(id);
  const own = devices.filter((d) => d.kind !== "watched").length;

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

  async function breakIt() {
    setNote("");
    try {
      await api("POST", "/api/demo/inject", { kind: "server_lagging", deviceId: "game-1" });
      setS((c) => ({ ...c, brokeAt: Date.now() }));
    } catch (e) {
      setNote(e instanceof ApiError && e.status === 422 ? "Minecraft is already lagging: ask about it."
        : "Couldn't make it lag. Try again in a moment.");
      setS((c) => ({ ...c, brokeAt: c.brokeAt ?? Date.now() }));
    }
  }
  function showCard() {
    const el = document.querySelector<HTMLElement>(".chat-log [data-tour=card]") ?? document.querySelector<HTMLElement>("[data-tour=card]");
    if (!el) { setNote("No card yet: do step 1 first, and the card appears in the chat."); return; }
    setNote("");
    onAsk(""); // brings the chat into view on a phone (an empty question is ignored)
    el.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    el.classList.add("tour-flash");
    setTimeout(() => el.classList.remove("tour-flash"), 2400);
  }

  const steps: { id: StepId; title: string; why: string; act: ReactNode; hint?: string }[] = [
    { id: "ask", title: "Ask what's wrong", why: "Nightlight looks at every device before it answers.",
      act: <button className="small primary" disabled={!f.done} title={f.done ? undefined : "Nightlight is answering; one moment"}
        onClick={() => { setS((c) => ({ ...c, asked: f.seq })); onAsk(ASK); }}>Ask: {ASK}</button>,
      hint: "Watch the steps appear as it checks, and the Pi glow on the map." },
    { id: "approve", title: "Approve the fix", why: "Nothing changes until you tap Approve on its card.",
      act: <button className="small" onClick={showCard}>Show me the card</button>, hint: "The Pi's disk goes from 94% to about 61%." },
    { id: "break", title: "Break something yourself", why: "Make a problem, then see how it handles it.",
      act: <span className="tour-acts"><button className="small" onClick={breakIt}>Make Minecraft lag</button>
        <button className="small" onClick={() => onAsk(LAG)}>Ask about it</button></span>,
      hint: "It offers a backup before restarting." },
    { id: "nearby", title: "Find devices nearby", why: "Your computers spot the printer, TV and router on the network.",
      act: <button className="small" onClick={() => onPanel("found")}>Look nearby</button> },
    { id: "add", title: "Add a device", why: "See what installing on a computer looks like, then approve it.",
      act: <button className="small" onClick={() => onPanel("add")}>Try adding one</button> },
    { id: "trust", title: "Earn trust", why: "After three good clean-ups of the same kind, Nightlight offers to handle it on its own.",
      act: <button className="small" onClick={() => { tick("trust"); onPanel("trust"); }}>Open Trust</button> },
  ];
  const count = steps.filter((x) => has(x.id)).length;
  const next = steps.find((x) => !has(x.id));
  return (
    <section className="panel sample-tour" aria-label="Your tour">
      <button className="tour-head" aria-expanded={s.open} onClick={() => setS((c) => ({ ...c, open: !c.open }))}>
        <strong>Your tour</strong> <span className="muted">· {count} of {steps.length}</span>
        <span className="spacer" /><span className="small muted">{s.open ? "Hide" : "Show"}</span>
      </button>
      {s.open && <>
        <ol className="tour-steps">
          {steps.map((x) => (
            <li key={x.id} className={has(x.id) ? "done" : x === next ? "now" : ""}>
              <span className="tour-tick" aria-hidden>{has(x.id) ? "✓" : ""}</span>
              <div>
                <strong>{x.title}</strong> <span className="small">{x.why}</span>
                {!has(x.id) && <div className="tour-act">{x.act}</div>}
                {!has(x.id) && x === next && x.hint && <div className="small muted">{x.hint}</div>}
              </div>
            </li>))}
        </ol>
        {note && <p className="small" role="status">{note}</p>}
        <p className="small tour-end">{count === steps.length ? "That's the tour. " : ""}The real thing runs on your own Mac or
          Raspberry Pi:{" "}<button className="small primary" onClick={onSave}>Try the real app</button></p>
      </>}
    </section>
  );
}
