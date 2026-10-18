"use client";

import { useCallback, useRef, useState, type ReactNode } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import { Logo } from "../../brand/Logo";
import { Plus } from "../../icons";
import { AuthButtons } from "../AuthButtons";
import { display, sans } from "../fonts";
import { scrollToTarget, useSmoothScroll } from "../motion/smooth";
import {
  AskCanvas,
  ExplainCanvas,
  HeroCanvas,
  LADDER,
  NoticeCanvas,
  PrivacyCanvas,
  TrustCanvas,
  type ApprovalState,
  type AskKey,
  type ExplainKey,
  type NoticeKey,
} from "./Canvases";
import { Cursor } from "./Cursor";
import s from "./Mono.module.css";

gsap.registerPlugin(useGSAP, ScrollTrigger);

// "/": the landing page and sign-in in one, in the day dashboard's light monochrome. The hero is the dashboard on the
// sample home; then the loop in four chapters, each a framed canvas of the app beside a list that chooses what the
// canvas shows; then what leaves the house, who it is for, and the demo.

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#privacy", label: "Privacy" },
  { href: "#who", label: "Who it’s for" },
];

const SENT = [
  "How busy it is, and how full its memory and disk are",
  "The names of its apps, and which ones have stopped",
  "How many updates are waiting",
  "Two yes/no safety checks, like whether remote login accepts passwords",
];
const NEVER = ["Its own name or network addresses", "What’s inside your files", "Passwords or keys", "Your apps’ hidden settings"];

// What each kind of setup really gets: computers with the helper are looked after; other boxes are only watched.
const WHO = [
  { who: "A Raspberry Pi running the home VPN", what: "Full disks and apps that stop" },
  { who: "A Mac running photos and home automation", what: "Apps that stop, updates waiting" },
  { who: "A Minecraft server for the kids", what: "Memory, disk space and apps that stop" },
  { who: "A small office with a few computers", what: "Updates waiting, computers gone quiet" },
  { who: "The router, NAS and printer", what: "Checked that they still answer" },
];

type Item<K extends string> = { key: K; title: string; text: string };

// One open at a time; opening an item changes what the chapter's canvas shows. Clicking the open one closes it, and
// the canvas keeps showing it.
function Steps<K extends string>({ n, items, open, onOpen }: { n: number; items: Item<K>[]; open: K; onOpen: (k: K) => void }) {
  const [shut, setShut] = useState<K | null>(null); // the item closed by hand; choosing any other opens again
  const choose = (k: K) => {
    if (k === open) return setShut(shut === k ? null : k);
    setShut(null);
    onOpen(k);
  };
  return (
    <ul className={s.steps}>
      {items.map((it, i) => {
        const on = it.key === open && shut !== open;
        const id = `step-${n}-${it.key}`;
        return (
          <li key={it.key} className={s.step} data-open={on || undefined}>
            <button type="button" className={s.stepBtn} aria-expanded={on} aria-controls={id} onClick={() => choose(it.key)}>
              <span className={s.stepNum}>
                {n}.{i + 1}
              </span>
              <span className={s.stepTitle}>{it.title}</span>
              <Plus size={16} className={s.stepIcon} />
            </button>
            <div id={id} className={s.stepBody} role="region" aria-label={it.title}>
              <div>
                <p>{it.text}</p>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function Chapter({
  id,
  title,
  quiet,
  text,
  steps,
  canvas,
  flip,
}: {
  id: string;
  title: string;
  quiet: string;
  text: string;
  steps: ReactNode;
  canvas: ReactNode;
  flip?: boolean;
}) {
  return (
    <section id={id} className={s.chapter} data-flip={flip || undefined} aria-labelledby={`${id}-title`} data-chapter>
      <div className={s.chapterText}>
        <h2 id={`${id}-title`} className={s.h2}>
          {title} <span className={s.quiet}>{quiet}</span>
        </h2>
        <p className={s.body}>{text}</p>
        {steps}
      </div>
      <div className={s.chapterCanvas} data-canvas>
        {canvas}
      </div>
    </section>
  );
}

export function MonoLanding() {
  const root = useRef<HTMLDivElement>(null);
  useSmoothScroll();

  const [notice, setNotice] = useState<NoticeKey>("space");
  const [explain, setExplain] = useState<ExplainKey>("words");
  const [ask, setAsk] = useState<AskKey>("plan");
  const [approval, setApproval] = useState<ApprovalState>("waiting");
  const [level, setLevel] = useState(0);
  const onApproval = useCallback((a: ApprovalState) => setApproval(a), []);

  useGSAP(
    () => {
      const q = gsap.utils.selector(root);
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.from(q("[data-hero-rise]"), { y: 18, opacity: 0, duration: 1.1, ease: "expo.out", stagger: 0.07, delay: 0.1 });
        gsap.from(q("[data-hero-canvas]"), { y: 48, opacity: 0, duration: 1.4, ease: "expo.out", delay: 0.35 });
        q("[data-chapter]").forEach((el) => {
          gsap.from(el.querySelectorAll("[data-canvas]"), {
            y: 56,
            opacity: 0,
            duration: 1.2,
            ease: "expo.out",
            scrollTrigger: { trigger: el, start: "top 78%", once: true },
          });
        });
        q("[data-rise]").forEach((el) => {
          gsap.from(el, { y: 24, opacity: 0, duration: 1, ease: "expo.out", scrollTrigger: { trigger: el, start: "top 86%", once: true } });
        });
      });
    },
    { scope: root },
  );

  const go = (href: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    scrollToTarget(href);
  };

  return (
    <div ref={root} className={`${s.page} ${display.variable} ${sans.variable}`} data-theme="day">
      <Cursor scope={root} />
      <a href="#main" className={s.skip}>
        Skip to content
      </a>

      <header className={s.nav}>
        <a href="#top" className={s.brand} aria-label="Nightlight, back to top" onClick={go("#top")}>
          <Logo height={22} />
        </a>
        <nav className={s.navLinks} aria-label="Sections">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} onClick={go(l.href)}>
              {l.label}
            </a>
          ))}
        </nav>
        <div className={s.navEnd}>
          <AuthButtons size="small" demoOnly styles={s} />
        </div>
      </header>

      <main id="main">
        <section id="top" className={s.hero} aria-labelledby="hero-title">
          <div className={s.heroText}>
            <h1 id="hero-title" className={s.h1} data-hero-rise>
              Go to sleep. <span className={s.quiet}>It’s got this.</span>
            </h1>
            <div className={s.heroSide}>
              <p className={s.lede} data-hero-rise>
                Nightlight watches the computers you run at home, like a Raspberry Pi, a Mac or a game server, and checks
                that your router and NAS still answer. It tells you what’s wrong in plain words, and never fixes anything
                without your yes.
              </p>
              <div data-hero-rise>
                <AuthButtons styles={s} />
                <p className={s.fine}>Start on a simulated sample home with no account, or sign in and add your own machines.</p>
              </div>
            </div>
          </div>
          <div className={s.heroCanvas} data-hero-canvas>
            <HeroCanvas />
          </div>
          <div className={s.principles}>
            <p data-rise>
              <strong>It asks first.</strong> Nothing changes without your yes, and every fix says how risky it is and
              whether it can be undone.
            </p>
            <p data-rise>
              <strong>Plain words.</strong> You read “The Pi’s disk is 94% full”, not an error code.
            </p>
            <p data-rise>
              <strong>Trust you set.</strong> On the sample home, routine fixes can run on their own once you say so. Your own
              devices always ask.
            </p>
          </div>
        </section>

        <section className={s.band} aria-labelledby="band-title">
          <div className={s.bandInner}>
            <div>
              <h2 id="band-title" className={s.bandTitle}>
                See it on a sample home.
              </h2>
              <p className={s.bandText}>Six simulated devices with a few everyday problems. Try every button.</p>
            </div>
            <AuthButtons styles={{ ...s, actions: s.bandActions }} demoOnly />
          </div>
        </section>

        <section id="how" className={s.intro} aria-labelledby="intro-title">
          <h2 id="intro-title" className={s.h2Big} data-rise>
            Run a Pi, a NAS or a game server at home? <span className={s.quiet}>Then you’re the IT person. Nightlight helps.</span>
          </h2>
          <p className={s.body} data-rise>
            A small helper on each computer sends a short health report every minute. When something goes wrong, Nightlight
            takes the same four steps.
          </p>
        </section>

        <Chapter
          id="notices"
          title="It notices"
          quiet="often before things break"
          text="When something goes wrong, it shows up at the top of your home as one plain sentence, with what Nightlight already found out."
          steps={
            <Steps
              n={1}
              open={notice}
              onOpen={setNotice}
              items={[
                { key: "space", title: "Space running out", text: "When a disk fills up, it lists what’s taking the room and how big each part is." },
                { key: "stops", title: "Apps that stop", text: "When an app stops or says it’s unhealthy, it looks into why and reads its notes from last time before suggesting a restart." },
                { key: "backups", title: "Backups and updates", text: "One plain sentence when an update is waiting or a backup is days old." },
                { key: "quiet", title: "Devices gone quiet", text: "When a computer stops reporting, it says since when and whether your other computers still report." },
              ]}
            />
          }
          canvas={<NoticeCanvas which={notice} />}
        />

        <Chapter
          id="explains"
          flip
          title="It explains"
          quiet="in words anyone can follow"
          text="Ask about your home in your own words. It answers the same way, and shows what it checked."
          steps={
            <Steps
              n={2}
              open={explain}
              onOpen={setExplain}
              items={[
                { key: "words", title: "Plain words", text: "Answers read like a note from someone who knows your house, not like a log file." },
                { key: "checked", title: "Shows what it checked", text: "Each step it took is listed as it works, so you can see how it reached the answer." },
                { key: "ask", title: "Your own words", text: "Why an app is unhealthy, when the last backup ran, what that new thing on your network is." },
              ]}
            />
          }
          canvas={<ExplainCanvas focus={explain} />}
        />

        <Chapter
          id="asks"
          title="It asks"
          quiet="before it changes anything"
          text="Each fix comes as a card: the plan, what will happen, what it affects and whether it can be undone. Nothing happens until you approve. Go on, approve this one."
          steps={
            <Steps
              n={3}
              open={ask}
              onOpen={setAsk}
              items={[
                { key: "plan", title: "The plan", text: "One sentence on exactly what it will do, and to which device." },
                { key: "dry", title: "What happens", text: "What it expects the result to be, worked out before anything changes." },
                { key: "touch", title: "What it affects", text: "Which device is involved, and whether it’s one of yours or the sample." },
                { key: "undo", title: "Can it be undone?", text: "How to take it back, or a plain warning when it can’t be." },
              ]}
            />
          }
          canvas={<AskCanvas focus={ask} state={approval} onChange={onApproval} />}
        />

        <Chapter
          id="trust"
          flip
          title="Trust grows"
          quiet="one job at a time"
          text="After the same safe fix has worked 3 times with your OK, it offers to handle that one job on its own, and you can take it back any time. For now this is on the sample home only: on your own computers, every change waits for your tap."
          steps={
            <Steps
              n={4}
              open={String(level)}
              onOpen={(k) => setLevel(Number(k))}
              items={LADDER.map((l, i) => ({ key: String(i), title: l.name, text: l.does }))}
            />
          }
          canvas={<TrustCanvas level={level} onLevel={setLevel} />}
        />

        <section id="privacy" className={s.privacy} aria-labelledby="privacy-title">
          <div className={s.privacyText}>
            <h2 id="privacy-title" className={s.h2} data-rise>
              What leaves your house <span className={s.quiet}>and what never does</span>
            </h2>
            <p className={s.body} data-rise>
              A small helper on each computer sends a health report once a minute. It changes nothing by default, it can only
              run the jobs you switched on for that computer, and every restart waits for your tap. Names that nearby devices
              announce, like a TV called “Living Room”, show on your map; you can turn that off.
            </p>
          </div>
          <div data-rise>
            <PrivacyCanvas sent={SENT} never={NEVER} />
          </div>
        </section>

        <section id="who" className={s.who} aria-labelledby="who-title">
          <h2 id="who-title" className={s.h2} data-rise>
            For homes <span className={s.quiet}>with no IT person</span>
          </h2>
          <ul className={s.whoList}>
            {WHO.map((w) => (
              <li key={w.who} className={s.whoRow} data-rise>
                <span className={s.whoName}>{w.who}</span>
                <span className={s.whoWhat}>{w.what}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className={s.cta} aria-labelledby="cta-title">
          <h2 id="cta-title" className={s.ctaTitle} data-rise>
            Don’t lose sleep <span className={s.quiet}>over it.</span>
          </h2>
          <p className={s.ctaText} data-rise>
            Open the sample home and watch it notice, explain and ask. One click, no account.
          </p>
          <div data-rise>
            <AuthButtons styles={{ ...s, actions: s.ctaActions }} />
          </div>
        </section>
      </main>

      <footer className={s.footer}>
        <Logo height={20} />
        <nav aria-label="Footer" className={s.footerLinks}>
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} onClick={go(l.href)}>
              {l.label}
            </a>
          ))}
        </nav>
        <p className={s.footerNote}>
          A house-sitter for home and small-office servers. Built for the Google Cloud AI Builder Cup 2026. The demo home is
          simulated. © 2026 Nightlight
        </p>
      </footer>
    </div>
  );
}
