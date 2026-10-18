"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ArrowTo, Camera, Check, Computer, Cpu, Gamepad, Nas, Router, StatusBroken, StatusFine, StatusLook, StatusOffline, Close, type IconType } from "../../icons";
import { Logo } from "../../brand/Logo";
import { Mascot } from "../../mascot/Mascot";
import { MascotHead } from "../../mascot/MascotHead";
import { AuthButtons } from "../AuthButtons";
import { scrollToTarget } from "../motion/smooth";
import s from "./Mono.module.css";

// The product, drawn as the day dashboard draws it, on the simulated sample home. Every canvas is a picture of the
// app at work; the chapters' lists beside them choose what it shows. Anything drawn as a button works: the hero's
// buttons lead to the chapter that answers them, the chat answers, and the approval and trust cards respond.

type Tone = "ok" | "warn" | "crit" | "offline";
const WORD: Record<Tone, string> = { ok: "Fine", warn: "Needs a look", crit: "Broken", offline: "Not answering" };
const TONE_ICON: Record<Tone, IconType> = { ok: StatusFine, warn: StatusLook, crit: StatusBroken, offline: StatusOffline };

function Status({ tone, word }: { tone: Tone; word?: string }) {
  const I = TONE_ICON[tone];
  return (
    <span className={s.status} data-tone={tone}>
      <I size={13} />
      {word ?? WORD[tone]}
    </span>
  );
}

function Frame({ children, label, className = "", note = "Sample home · simulated" }: { children: ReactNode; label: string; className?: string; note?: string }) {
  return (
    <figure className={`${s.frame} ${className}`} aria-label={label}>
      {children}
      <figcaption className={s.frameNote}>{note}</figcaption>
    </figure>
  );
}

/* ---------- Hero: the home map, each device reporting in ---------- */

// The sample home exactly as the demo opens it (api template "home-pi"): names, purposes and findings are the seed's.
// The map shows five of its six devices; the camera recorder, whose health is unknown, appears in "It notices".
type Device = { id: string; name: string; room: string; icon: IconType; x: number; y: number; tone: Tone; line: string; short?: string };
const HOME: Device[] = [
  { id: "pi", name: "Raspberry Pi", room: "VPN and car logger", icon: Cpu, x: 17, y: 27, tone: "crit", line: "The disk is 94% full.", short: "Disk 94% full" },
  { id: "mac", name: "Mac Mini", room: "Home automation", icon: Computer, x: 83, y: 27, tone: "warn", line: "Immich, the photo app, says it’s unhealthy.", short: "Photo app unhealthy" },
  { id: "router", name: "Router", room: "Internet", icon: Router, x: 50, y: 42, tone: "ok", line: "Connects everything to the internet." },
  { id: "nas", name: "NAS", room: "Family photos", icon: Nas, x: 17, y: 75, tone: "warn", line: "Backups run, but nobody has tested a restore.", short: "Restore never tested" },
  { id: "game", name: "Game server", room: "Minecraft world", icon: Gamepad, x: 83, y: 75, tone: "warn", line: "The world hasn’t been backed up in 9 days.", short: "No backup in 9 days" },
];
const ROUND = ["router", "nas", "mac", "game", "pi"];
const EVERY = 2600;

// Each device sends a report every minute, so the newest is "just now" and the rest a minute apart.
function ago(k: number) {
  return k === 0 ? "Just now" : `${k} min ago`;
}

function Tile({ d, checking, compact }: { d: Device; checking?: boolean; compact?: boolean }) {
  const I = d.icon;
  return (
    <div className={s.tile} data-tone={d.tone} data-checking={checking || undefined} data-compact={compact || undefined}>
      <div className={s.tileHead}>
        <span className={s.tileIcon} data-tone={d.tone}>
          <I size={16} />
        </span>
        <span className={s.tileName}>
          {d.name}
          <span className={s.tileRoom}>{d.room}</span>
        </span>
      </div>
      <Status tone={d.tone} />
      {!compact && <p className={s.tileLine}>{d.line}</p>}
      <span className={s.tileCheck} aria-hidden="true">
        Reported
      </span>
    </div>
  );
}

export function HeroCanvas() {
  const [step, setStep] = useState(ROUND.length);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setInterval(() => setStep((n) => n + 1), EVERY);
    return () => window.clearInterval(id);
  }, []);

  const current = ROUND[step % ROUND.length];
  const shown = Array.from({ length: 4 }, (_, k) => {
    const i = step - k;
    return { key: i, d: HOME.find((x) => x.id === ROUND[i % ROUND.length])!, time: ago(k) };
  });
  const router = HOME.find((d) => d.id === "router")!;

  return (
    <Frame label="The Nightlight dashboard on a simulated sample home" className={s.heroFrame}>
      <div className={s.appBar}>
        <Logo height={16} />
        <span className={s.samplePill}>Sample home · simulated</span>
        <span className={s.appBarEnd}>
          <button type="button" className={s.canvasBtn} onClick={() => scrollToTarget("#explains")}>
            <MascotHead size={20} />
            Ask Nightlight
          </button>
        </span>
      </div>
      <div className={s.heroBody}>
        <div className={s.needsStrip}>
          <span className={s.needsLight} aria-hidden="true" />
          <span className={s.needsTitle}>4 things need you</span>
          <span className={s.needsCounts}>
            <i data-tone="crit" /> 1 broken <i data-tone="warn" /> 3 need a look
          </span>
          <span className={s.needsItem}>
            <b>Raspberry Pi</b> The disk is 94% full.
          </span>
          <button type="button" className={`${s.canvasBtn} ${s.needsBtn}`} onClick={() => scrollToTarget("#asks")}>
            What should I do?
            <ArrowTo size={14} />
          </button>
        </div>

        <div className={s.map}>
          <svg className={s.wires} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            {HOME.filter((d) => d.id !== "router").map((d) => (
              <path
                key={d.id}
                d={`M${router.x} ${router.y} H${(router.x + d.x) / 2} V${d.y} H${d.x}`}
                data-live={d.id === current || undefined}
              />
            ))}
          </svg>
          {HOME.map((d) => (
            <div key={d.id} className={s.mapSpot} style={{ left: `${d.x}%`, top: `${d.y}%` }}>
              <Tile d={d} checking={d.id === current} />
            </div>
          ))}
        </div>
      </div>

      <div className={s.toasts} aria-hidden="true">
        <p className={s.toastsHead}>
          <span className={s.liveDot} /> Latest reports
        </p>
        <ol>
          {shown.map(({ key, d, time }) => (
            <li key={key} className={s.toast} data-tone={d.tone}>
              <time>{time}</time>
              <span className={s.toastName}>{d.name}</span>
              <Status tone={d.tone} word={d.short} />
            </li>
          ))}
        </ol>
      </div>
    </Frame>
  );
}

/* ---------- 1. It notices ---------- */

export type NoticeKey = "space" | "stops" | "backups" | "quiet";
// Each one is a finding the sample home really has, with the evidence the app keeps for it.
const NOTICES: Record<NoticeKey, { d: Device; headline: string; facts: string[]; meter?: { label: string; value: number; word: string } }> = {
  space: {
    d: HOME[0],
    headline: "The Raspberry Pi’s disk is 94% full.",
    facts: ["Old log files: 2.1 GB", "A backup of the car logger’s data: 1.4 GB", "Unused app downloads (Docker images): 0.9 GB"],
    meter: { label: "Disk", value: 94, word: "94% full" },
  },
  stops: {
    d: HOME[1],
    headline: "Immich, the photo app on the Mac Mini, says it’s unhealthy.",
    facts: ["Its photo database isn’t answering", "Its health check failed 4 times in the last hour", "Notes from last time: this happens after a power cut"],
  },
  backups: {
    d: HOME[4],
    headline: "The Minecraft world hasn’t been backed up in 9 days.",
    facts: ["Last world backup: 9 days ago", "Minecraft 1.21.5 is out (you have 1.21.4)", "2 of 10 players are online"],
  },
  quiet: {
    d: { id: "cam", name: "Camera recorder", room: "Front-door camera", icon: Camera, x: 0, y: 0, tone: "offline", line: "No report, so its health is unknown." },
    headline: "The camera recorder isn’t reporting.",
    facts: ["Without a report, its health is unknown", "The other five devices are still reporting", "On your own computers it also says since when"],
  },
};

export function NoticeCanvas({ which }: { which: NoticeKey }) {
  const n = NOTICES[which];
  const needs = n.d.tone === "crit" ? "Broken" : n.d.tone === "offline" ? "Not reporting" : "Needs a look";
  return (
    <Frame label="A device that needs a look, as the dashboard shows it">
      <div className={s.stage}>
        <div key={which} className={s.swap}>
          <div className={s.needsStrip} data-compact>
            <span className={s.needsLight} aria-hidden="true" />
            <span className={s.needsTitle}>{needs}</span>
            <span className={s.needsItem}>{n.headline}</span>
          </div>
          <div className={s.noticeRow}>
            <div className={s.bigTile}>
              <Tile d={n.d} />
              {n.meter && (
                <div className={s.meterWrap}>
                  <div className={s.meter} data-tone={n.d.tone} role="img" aria-label={`${n.meter.label} ${n.meter.word}`}>
                    <span style={{ width: `${n.meter.value}%` }} />
                  </div>
                  <p className={s.meterLabel}>
                    <span>{n.meter.label}</span>
                    <span>{n.meter.word}</span>
                  </p>
                </div>
              )}
            </div>
            <div className={s.floatCard}>
              <p className={s.floatHead}>What it noticed</p>
              <ul className={s.factList}>
                {n.facts.map((f) => (
                  <li key={f}>
                    <Check size={13} />
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </Frame>
  );
}

/* ---------- 2. It explains ---------- */

export type ExplainKey = "words" | "checked" | "ask";

// What the sample home answers. A question typed in your own words gets the last one: the demo is where it can answer.
// Answers use only what the sample home holds: its findings, the Mac Mini's notes and saved fix, the game server's backup.
const QA: { q: string; steps: string[]; answer: string }[] = [
  {
    q: "Is anything wrong at home?",
    steps: ["Checked 6 devices", "Looked at the Pi’s biggest folders"],
    answer:
      "Four things. The most urgent: the Raspberry Pi’s disk is 94% full, mostly 2.1 GB of old log files that are safe to clear. Also, Immich on the Mac Mini says it’s unhealthy, the Minecraft world hasn’t been backed up in 9 days, and nobody has tested restoring the NAS backups.",
  },
  {
    q: "Why is Immich unhealthy?",
    steps: ["Checked Immich on the Mac Mini", "Read its notes from last time", "Found the fix that worked before"],
    answer:
      "Its photo database isn’t answering: the health check failed 4 times in the last hour. My notes say this happens after a power cut, and 3 days ago restarting Immich fixed it. I can do that again if you approve.",
  },
  {
    q: "When was the Minecraft world last backed up?",
    steps: ["Checked the Minecraft server"],
    answer:
      "9 days ago, which is longer than it should be. I can save a copy now, about 6.2 GB, and players can keep playing.",
  },
];

export function ExplainCanvas({ focus }: { focus: ExplainKey }) {
  const [asked, setAsked] = useState(0);
  const [own, setOwn] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  // each question gets a short think first, as in the app: the mascot mulls it over, then the answer arrives
  const [turn, setTurn] = useState(0);
  const [thinking, setThinking] = useState(false);
  const qa = QA[asked];

  useEffect(() => {
    if (!thinking) return;
    const id = window.setTimeout(() => setThinking(false), 1400);
    return () => window.clearTimeout(id);
  }, [thinking, turn]);

  const ask = () => {
    setTurn((n) => n + 1);
    setThinking(true);
  };
  const pick = (i: number) => {
    setAsked(i);
    setOwn(null);
    ask();
  };
  const send = (e: FormEvent) => {
    e.preventDefault();
    const q = draft.trim();
    if (!q) return;
    setOwn(q);
    setDraft("");
    ask();
  };

  return (
    <Frame label="The Ask Nightlight chat answering a question">
      <div className={s.stage}>
        <div className={s.chat} data-focus={focus}>
          <div className={s.chatHead}>
            <MascotHead size={26} mood={thinking ? "busy" : "idle"} />
            Ask Nightlight
          </div>
          <div key={turn} className={`${s.chatLog} ${s.swap}`} aria-live="polite">
            <p className={s.youBubble}>{own ?? qa.q}</p>
            {thinking ? (
              <div className={s.thinking}>
                <Mascot size={46} mood="thinking" />
                Thinking…
              </div>
            ) : own ? (
              <div className={s.answer} data-part="words">
                <p>
                  On this page I can only answer the suggested questions. In the demo you can ask me that, or anything
                  else, about the six simulated devices.
                </p>
                <AuthButtons size="small" demoOnly styles={s} />
              </div>
            ) : (
              <>
                <ul className={s.chatSteps} data-part="checked">
                  {qa.steps.map((x) => (
                    <li key={x}>
                      <Check size={13} />
                      {x}
                    </li>
                  ))}
                </ul>
                <p className={s.answer} data-part="words">
                  {qa.answer}
                </p>
              </>
            )}
          </div>
          <div className={s.chatFoot} data-part="ask">
            <div className={s.chips}>
              {QA.map((x, i) =>
                i === asked && !own ? null : (
                  <button key={x.q} type="button" className={s.chip} onClick={() => pick(i)}>
                    {x.q}
                  </button>
                ),
              )}
            </div>
            <form className={s.chatInput} onSubmit={send}>
              <label htmlFor="ask-input" className={s.srOnly}>
                Ask Nightlight a question
              </label>
              <input
                id="ask-input"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Ask Nightlight…"
                autoComplete="off"
              />
              <button type="submit" className={s.sendBtn} disabled={!draft.trim()}>
                Send
              </button>
            </form>
          </div>
        </div>
      </div>
    </Frame>
  );
}

/* ---------- 3. It asks first ---------- */

export type AskKey = "plan" | "dry" | "touch" | "undo";
export type ApprovalState = "waiting" | "running" | "done" | "declined";

// The card the sample home really shows for this job, with the app's own labels.
const FACTS: { key: AskKey; term: string; text: string }[] = [
  { key: "plan", term: "Plan", text: "Compress and remove log files older than 7 days on the Raspberry Pi." },
  { key: "dry", term: "What happens", text: "Frees about 2.1 GB (94% → 61% full). Nothing that’s running is stopped." },
  { key: "touch", term: "Affects", text: "Raspberry Pi (sample, nothing real)" },
  { key: "undo", term: "Can it be undone?", text: "Removed logs are kept in an archive for 24 hours." },
];

export function AskCanvas({ focus, state, onChange }: { focus: AskKey; state: ApprovalState; onChange: (s: ApprovalState) => void }) {
  useEffect(() => {
    if (state !== "running") return;
    const id = window.setTimeout(() => onChange("done"), 1800);
    return () => window.clearTimeout(id);
  }, [state, onChange]);

  return (
    <Frame label="An approval card, waiting for your yes">
      <div className={s.stage}>
        <div className={s.approval} data-state={state}>
          <div className={s.approvalHead}>
            <p className={s.approvalTitle}>Clean up old logs on the Raspberry Pi</p>
            <span className={s.risk}>Safe</span>
          </div>
          <dl className={s.terms}>
            {FACTS.map((f) => (
              <div key={f.key} data-on={f.key === focus || undefined}>
                <dt>{f.term}</dt>
                <dd>{f.text}</dd>
              </div>
            ))}
          </dl>
          <div className={s.approvalFoot} aria-live="polite">
            {state === "waiting" && (
              <div className={s.approvalActions}>
                <button type="button" className={s.approve} onClick={() => onChange("running")}>
                  Approve
                </button>
                <button type="button" className={s.notNow} onClick={() => onChange("declined")}>
                  Not now
                </button>
              </div>
            )}
            {state === "running" && (
              <p className={s.result}>
                <Mascot size={30} mood="working" className={s.resultMascot} />
                Cleaning up old logs…
              </p>
            )}
            {state === "done" && (
              <p className={s.result} data-tone="ok">
                <Mascot size={30} mood="done" className={s.resultMascot} />
                Done. Freed 2.1 GB on the Raspberry Pi (94% → 61% full).{" "}
                <button type="button" className={s.link} onClick={() => onChange("waiting")}>
                  Show it again
                </button>
              </p>
            )}
            {state === "declined" && (
              <p className={s.result}>
                Okay, I’ll leave it for now.{" "}
                <button type="button" className={s.link} onClick={() => onChange("waiting")}>
                  Show the card again
                </button>
              </p>
            )}
          </div>
        </div>
      </div>
    </Frame>
  );
}

/* ---------- 4. Trust grows ---------- */

export const LADDER = [
  { name: "Always ask me", does: "Explains and waits for your tap." },
  { name: "Ask me for new things", does: "Does familiar safe jobs on its own, asks about anything new." },
  { name: "Just handle it and tell me", does: "Acts, then reports in plain words." },
];

export function TrustCanvas({ level, onLevel }: { level: number; onLevel: (n: number) => void }) {
  // "Keep asking me" answers the offer without moving the level, so it needs its own memory.
  const [kept, setKept] = useState(false);
  const set = (n: number) => {
    setKept(false);
    onLevel(n);
  };
  const offered = level === 0 && !kept;
  // waiting with the star held out while you decide, a happy hop when you hand the job over, calm otherwise
  const mood = offered ? "waiting" : level > 0 ? "done" : "idle";
  return (
    <Frame label="Nightlight offering to handle one job on its own">
      <div className={s.stage}>
        <div className={s.trust}>
          <div className={s.offer}>
            <Mascot key={mood} size={44} mood={mood} className={s.offerIcon} />
            <p>
              That’s the third time we’ve cleaned up old logs on the Pi, each time with your OK. Want me to do this one on
              my own from now on? I’ll still ask about anything new.
            </p>
          </div>
          <div className={s.approvalFoot} aria-live="polite">
            {offered ? (
              <div className={s.approvalActions}>
                <button type="button" className={s.approve} onClick={() => set(1)}>
                  Yes, handle it
                </button>
                <button type="button" className={s.notNow} onClick={() => setKept(true)}>
                  Keep asking me
                </button>
              </div>
            ) : level === 0 ? (
              <p className={s.result}>
                Okay, I’ll keep asking before every clean-up.{" "}
                <button type="button" className={s.link} onClick={() => set(0)}>
                  Undo
                </button>
              </p>
            ) : (
              <p className={s.result} data-tone="ok">
                <Check size={15} />
                Clean-ups on the Pi moved to “{LADDER[level].name}”.{" "}
                <button type="button" className={s.link} onClick={() => set(0)}>
                  Undo
                </button>
              </p>
            )}
          </div>
          <ol className={s.ladder} aria-label="Trust for cleaning up old logs on the Pi">
            {LADDER.map((step, i) => (
              <li key={step.name} data-current={i === level || undefined}>
                <button type="button" className={s.rungBtn} aria-pressed={i === level} onClick={() => set(i)}>
                  <span className={s.rung} aria-hidden="true" />
                  <span>
                    <strong>{step.name}</strong>
                    <span>{step.does}</span>
                  </span>
                  {i === level && <span className={s.now}>Now</span>}
                </button>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </Frame>
  );
}

/* ---------- What leaves the house ---------- */

export function PrivacyCanvas({ sent, never }: { sent: string[]; never: string[] }) {
  return (
    <Frame label="What Nightlight sends, and what it never sends" className={s.privacyFrame} note="On your own computers">
      <div className={s.privacyStage}>
        <div className={s.privacyCard}>
          <p className={s.floatHead}>Every minute, it sends</p>
          <ul className={s.factList}>
            {sent.map((x) => (
              <li key={x}>
                <Check size={13} />
                {x}
              </li>
            ))}
          </ul>
        </div>
        <div className={s.privacyCard} data-never>
          <p className={s.floatHead}>It never sends</p>
          <ul className={s.factList}>
            {never.map((x) => (
              <li key={x}>
                <Close size={13} />
                {x}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Frame>
  );
}
