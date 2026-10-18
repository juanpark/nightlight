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

const SENT = ["CPU, memory and disk percentages", "Which services and containers run", "How many updates are waiting", "Two safety checks"];
const NEVER = ["Host names or addresses", "Your files", "Passwords or keys", "Environment variables"];

const WHO = [
  { who: "A family with a NAS full of photos", what: "Disk space and backups" },
  { who: "A Raspberry Pi running the home VPN", what: "Services that stop" },
  { who: "A Minecraft world hosted for the kids", what: "Lag, memory and restarts" },
  { who: "A small office, or a dental clinic", what: "Updates and quiet devices" },
];

type Item<K extends string> = { key: K; title: string; text: string };

// One open at a time; opening an item changes what the chapter's canvas shows.
function Steps<K extends string>({ n, items, open, onOpen }: { n: number; items: Item<K>[]; open: K; onOpen: (k: K) => void }) {
  return (
    <ul className={s.steps}>
      {items.map((it, i) => {
        const on = it.key === open;
        const id = `step-${n}-${it.key}`;
        return (
          <li key={it.key} className={s.step} data-open={on || undefined}>
            <button type="button" className={s.stepBtn} aria-expanded={on} aria-controls={id} onClick={() => onOpen(it.key)}>
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
        gsap.from(q("[data-hero-rise]"), { y: 18, autoAlpha: 0, duration: 1.1, ease: "expo.out", stagger: 0.07, delay: 0.1 });
        gsap.from(q("[data-hero-canvas]"), { y: 48, autoAlpha: 0, duration: 1.4, ease: "expo.out", delay: 0.35 });
        q("[data-chapter]").forEach((el) => {
          gsap.from(el.querySelectorAll("[data-canvas]"), {
            y: 56,
            autoAlpha: 0,
            duration: 1.2,
            ease: "expo.out",
            scrollTrigger: { trigger: el, start: "top 78%", once: true },
          });
        });
        q("[data-rise]").forEach((el) => {
          gsap.from(el, { y: 24, autoAlpha: 0, duration: 1, ease: "expo.out", scrollTrigger: { trigger: el, start: "top 86%", once: true } });
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
              Your home’s computers, <span className={s.quiet}>looked after while you sleep.</span>
            </h1>
            <div className={s.heroSide}>
              <p className={s.lede} data-hero-rise>
                Nightlight watches the NAS, the Raspberry Pi, the game server and the router. It tells you what’s wrong in
                plain words, and never fixes anything without your yes.
              </p>
              <div data-hero-rise>
                <AuthButtons styles={s} />
                <p className={s.fine}>The demo opens a simulated sample home. No account, nothing to install.</p>
              </div>
            </div>
          </div>
          <div className={s.heroCanvas} data-hero-canvas>
            <HeroCanvas />
          </div>
          <div className={s.principles}>
            <p data-rise>
              <strong>Asks before acting —</strong> Nothing changes without your yes, and every job says how risky it is
              and how to undo it.
            </p>
            <p data-rise>
              <strong>Plain words —</strong> No error codes or dashboards to decode. Every state reads as a sentence first.
            </p>
            <p data-rise>
              <strong>Trust you set —</strong> Routine fixes can run on their own once you say so, per device and per job.
            </p>
          </div>
        </section>

        <section className={s.band} aria-labelledby="band-title">
          <div className={s.bandInner}>
            <div>
              <h2 id="band-title" className={s.bandTitle}>
                See it on a sample home.
              </h2>
              <p className={s.bandText}>Six simulated devices, one of them in trouble. Try every button.</p>
            </div>
            <AuthButtons styles={{ ...s, actions: s.bandActions }} demoOnly />
          </div>
        </section>

        <section id="how" className={s.intro} aria-labelledby="intro-title">
          <h2 id="intro-title" className={s.h2Big} data-rise>
            Most homes now run a small data centre. <span className={s.quiet}>Nobody is on call for it. Nightlight is.</span>
          </h2>
          <p className={s.body} data-rise>
            A NAS full of photos, a Pi running the VPN, a game server for the kids, the router. Nightlight checks each one every
            minute and follows the same four steps whenever something drifts.
          </p>
        </section>

        <Chapter
          id="notices"
          title="It notices"
          quiet="before anything breaks"
          text="Every machine reports how it’s doing each minute. When something drifts, it lands at the top of your home as one sentence, with what it already found out."
          steps={
            <Steps
              n={1}
              open={notice}
              onOpen={setNotice}
              items={[
                { key: "space", title: "Space running out", text: "Disks filling up, old logs and caches, Docker images. It names what takes the room, with sizes." },
                { key: "stops", title: "Things that stop", text: "Containers, services, game servers, the home VPN. Before suggesting a restart it looks into why it stopped." },
                { key: "backups", title: "Updates and backups", text: "One plain sentence when an update is waiting or a backup hasn’t run in days." },
                { key: "quiet", title: "Devices gone quiet", text: "When a machine goes silent it says since when, and which neighbours still check in." },
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
          text="Ask it anything about your home. It says what’s wrong, why it matters and what it already checked, without a single error code."
          steps={
            <Steps
              n={2}
              open={explain}
              onOpen={setExplain}
              items={[
                { key: "words", title: "Plain words", text: "Answers read like a note from someone who knows your house, not like a log file." },
                { key: "checked", title: "Shows what it checked", text: "Each step it took is listed as it works, so you can see how it reached the answer." },
                { key: "ask", title: "Ask about anything", text: "Why the game lags, when the last backup ran, what that new device is. Questions in your own words." },
              ]}
            />
          }
          canvas={<ExplainCanvas focus={explain} />}
        />

        <Chapter
          id="asks"
          title="It asks first,"
          quiet="every time it matters"
          text="Nothing changes without your yes. Each fix comes as a card with the plan, a dry run, what it touches and how to undo it. Go on, approve this one."
          steps={
            <Steps
              n={3}
              open={ask}
              onOpen={setAsk}
              items={[
                { key: "plan", title: "The plan", text: "One sentence on exactly what it will do, and to which device." },
                { key: "dry", title: "A dry run", text: "It tries the job without changing anything first, so you see the result before saying yes." },
                { key: "touch", title: "What it touches", text: "Which files, apps or services are involved, and what keeps running." },
                { key: "undo", title: "How to undo", text: "How to take it back, or a plain warning when a job can’t be undone." },
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
          text="After the same safe fix a few times, it offers to handle that one job on its own. Trust is set per device and per job, and you can take it back any time."
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
              A small helper on each machine sends health numbers once a minute. It changes nothing by default, and on a real
              device every restart waits for your tap, whatever the trust settings say.
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
