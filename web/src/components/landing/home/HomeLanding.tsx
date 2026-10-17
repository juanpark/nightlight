"use client";

import { useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import { Logo } from "../../brand/Logo";
import { AuthButtons } from "../AuthButtons";
import { display, sans } from "../fonts";
import { Magnetic } from "../motion/Magnetic";
import { revealChars, revealLines, riseIn } from "../motion/reveal";
import { Roll } from "../motion/Roll";
import { scrollToTarget, useSmoothScroll } from "../motion/smooth";
import { Loop } from "./Loop";
import { Marquee } from "./Marquee";
import { NightLog } from "./NightLog";
import { Torch } from "./Torch";
import s from "./Home.module.css";

gsap.registerPlugin(useGSAP, ScrollTrigger);

// "/": the landing page and sign-in in one. A dark, editorial page: one very
// large headline, the sample home's checks ticking by on the visitor's own
// clock, the night told in four pinned beats with the real cards, then what it
// looks after, who it is for, what leaves the house, and the wordmark as the
// close.

const WATCH = [
  {
    title: ["Space", "running out"],
    items: ["Disks filling up", "Old logs and caches", "Docker images", "The biggest folders"],
    text: "It finds what’s taking the room, names it with sizes, and offers a clean-up you approve.",
  },
  {
    title: ["Things", "that stop"],
    items: ["Containers", "System services", "Game servers", "The home VPN"],
    text: "Before asking to restart anything, it looks into why: exit codes, memory, restarts.",
  },
  {
    title: ["Updates", "and backups"],
    items: ["Updates waiting", "Backups overdue", "Lagging game worlds", "Safety checks"],
    text: "One plain sentence when an update is waiting or a backup hasn’t run in days.",
  },
  {
    title: ["Devices", "gone quiet"],
    items: ["Since when", "For how long", "Who still reports", "Back, or restarted"],
    text: "When a machine goes silent it tells you since when, and which neighbours still check in.",
  },
];

const WHO = [
  { who: "A family with a NAS full of photos", what: "Disk space and backups" },
  { who: "A Raspberry Pi running the home VPN", what: "Services that stop" },
  { who: "A Minecraft world hosted for the kids", what: "Lag, memory and restarts" },
  { who: "A small office, or a dental clinic", what: "Updates and quiet devices" },
];

const SENT = [
  "CPU, memory and disk percentages",
  "Which services and containers run",
  "How many updates are waiting",
  "Two safety checks",
];
const LINKS = [
  { href: "#loop", label: "How a night goes" },
  { href: "#watch", label: "What it looks after" },
  { href: "#who", label: "Who it’s for" },
  { href: "#privacy", label: "Privacy" },
];

const NEVER = ["Host names or addresses", "Your files", "Passwords or keys", "Environment variables"];

export function HomeLanding() {
  const root = useRef<HTMLDivElement>(null);
  useSmoothScroll();

  useGSAP(
    () => {
      const q = gsap.utils.selector(root);
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        // First screen: the headline rises line by line, then the rest.
        revealLines(q("[data-hero-title]")[0], { start: "now", delay: 0.15 });
        gsap.from(q("[data-hero-rise]"), { y: 24, autoAlpha: 0, duration: 1.1, ease: "power3.out", stagger: 0.08, delay: 0.55 });

        // The hero drifts up a little slower than the page as it leaves.
        gsap.to(q("[data-hero-inner]"), {
          yPercent: -12,
          ease: "none",
          scrollTrigger: { trigger: q("[data-hero]")[0], start: "top top", end: "bottom top", scrub: true },
        });

        q("[data-lines]").forEach((el) => revealLines(el));
        q("[data-block]").forEach((el) => riseIn(el.querySelectorAll("[data-part]"), el));
        q("[data-who-row]").forEach((el, i) => riseIn(el, el, i * 0.04));

        // Privacy: the yellow field opens from a band to the full width.
        gsap.fromTo(
          q("[data-field]"),
          { clipPath: "inset(6% 4% 6% 4% round 28px)" },
          {
            clipPath: "inset(0% 0% 0% 0% round 0px)",
            ease: "none",
            scrollTrigger: { trigger: q("[data-field]")[0], start: "top bottom", end: "top 25%", scrub: true },
          },
        );

        // Close: the wordmark's letters rise.
        revealChars(q("[data-wordmark]")[0], { start: "top 95%" });
      });

      // The scroll cue has done its job once the visitor scrolls: it fades out,
      // and comes back only at the very top. Instant when motion is reduced.
      const cue = q("[data-scroll-cue]")[0];
      ScrollTrigger.create({
        start: 80,
        end: "max",
        onToggle: ({ isActive }) =>
          gsap.to(cue, {
            autoAlpha: isActive ? 0 : 1,
            y: isActive ? 12 : 0,
            duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 0.5,
            ease: "power2.out",
            overwrite: "auto",
          }),
      });
    },
    { scope: root },
  );

  return (
    <div ref={root} className={`${s.page} ${display.variable} ${sans.variable}`} data-theme="night">
      <a href="#main" className={s.skip}>
        Skip to content
      </a>

      <header className={s.nav}>
        <a href="#top" className={s.brand} aria-label="Nightlight, back to top" onClick={(e) => { e.preventDefault(); scrollToTarget(0); }}>
          <Logo height={26} />
        </a>
        <nav className={s.navLinks} aria-label="Sections">
          {LINKS.slice(0, 3).map((l) => (
            <a key={l.href} href={l.href} onClick={(e) => { e.preventDefault(); scrollToTarget(l.href); }}>
              <Roll text={l.label} />
            </a>
          ))}
        </nav>
        <div className={s.navEnd}>
          <span className={s.navDemo}>
            <AuthButtons size="small" demoOnly styles={s} />
          </span>
        </div>
      </header>
      <Torch />

      <main id="main">
        <section id="top" className={s.hero} data-hero aria-labelledby="hero-title">
          <div className={s.heroInner} data-hero-inner>
            <h1 id="hero-title" className={s.heroTitle} data-hero-title>
              You sleep.
              <br />
              It keeps watch.
            </h1>
            <div className={s.heroBody}>
              <div className={s.heroCopy}>
                <p className={s.lede} data-hero-rise>
                  Nightlight looks after the computers in your home or small office. It tells you what’s wrong in
                  plain words, and never fixes anything without your yes.
                </p>
                <div data-hero-rise>
                  <AuthButtons styles={{ ...s, primary: `${s.primary} ${s.primaryNavy}` }} magnetic />
                </div>
              </div>
              <div className={s.heroSide}>
                <div data-hero-rise className={s.heroLog}>
                  <NightLog />
                </div>
              </div>
            </div>
            <button type="button" className={s.scrollCue} onClick={() => scrollToTarget("#watch-intro")} data-hero-rise data-scroll-cue>
              <Roll text="Scroll" />
              <span className={s.scrollTrack} aria-hidden="true">
                <span className={s.scrollDot} />
              </span>
            </button>
          </div>
        </section>

        <section id="watch-intro" className={s.intro} aria-label="What Nightlight watches">
          <Marquee />
          <p className={s.statement} data-lines>
            Most homes now run a small data centre: a NAS, a Pi, a game server, the router. Nobody is on call for it.
            Nightlight is.
          </p>
        </section>

        <Loop />


        <section id="watch" className={s.watch} aria-labelledby="watch-title">
          <h2 id="watch-title" className={s.h2} data-lines>
            What it keeps
            <br />
            an eye on
          </h2>
          <div className={s.watchGrid}>
            {WATCH.map((w) => (
              <article key={w.title[0]} className={s.watchBlock} data-block>
                <h3 className={s.watchTitle} data-part>
                  {w.title[0]}
                  <br />
                  {w.title[1]}
                </h3>
                <ul className={s.watchItems} data-part>
                  {w.items.map((it) => (
                    <li key={it}>{it}</li>
                  ))}
                </ul>
                <p className={s.watchText} data-part>
                  {w.text}
                </p>
              </article>
            ))}
          </div>
        </section>

        <section id="who" className={s.who} aria-labelledby="who-title">
          <h2 id="who-title" className={s.h2} data-lines>
            For homes with
            <br />
            no IT person
          </h2>
          <ul className={s.whoList}>
            {WHO.map((w) => (
              <li key={w.who} className={s.whoRow} data-who-row data-roll>
                <span className={s.whoName}>{w.who}</span>
                <span className={s.whoWhat}>{w.what}</span>
              </li>
            ))}
          </ul>
        </section>

        <section id="privacy" className={s.privacy} aria-labelledby="privacy-title">
          <div className={s.field} data-field>
            <h2 id="privacy-title" className={s.h2} data-lines>
              What leaves
              <br />
              your house
            </h2>
            <div className={s.privacyCols}>
              <div data-block>
                <h3 className={s.privacyHead} data-part>
                  Health numbers, every minute
                </h3>
                <ul className={s.privacyList} data-part>
                  {SENT.map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
              </div>
              <div data-block>
                <h3 className={s.privacyHead} data-part>
                  Never
                </h3>
                <ul className={s.privacyList} data-part data-never>
                  {NEVER.map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
              </div>
              <p className={s.privacyNote} data-block>
                <span data-part>
                  It changes nothing by default. On a real device, every restart waits for your tap, whatever the
                  trust settings say.
                </span>
              </p>
            </div>
          </div>
        </section>

        <section className={s.cta} aria-labelledby="cta-title">
          <h2 id="cta-title" className={s.ctaTitle} data-lines>
            Don’t lose
            <br />
            sleep over it.
          </h2>
          <div className={s.ctaSide} data-block>
            <p className={s.ctaText} data-part>
              The demo opens a simulated sample home in one click. No account, nothing to install.
            </p>
            <div data-part>
              <Magnetic strength={0.45}>
                <AuthButtons styles={{ ...s, primary: s.round, actions: s.roundWrap }} demoOnly />
              </Magnetic>
            </div>
          </div>
        </section>
      </main>

      <footer className={s.footer}>
        <div className={s.footerTop}>
          <nav aria-label="Footer" className={s.footerLinks}>
            {LINKS.map((l) => (
              <a key={l.href} href={l.href} onClick={(e) => { e.preventDefault(); scrollToTarget(l.href); }}>
                <Roll text={l.label} />
              </a>
            ))}
          </nav>
          <p className={s.footerNote}>
            A house-sitter for your home and small-office servers. Built for the Google Cloud AI Builder Cup 2026.
          </p>
          <button type="button" className={s.goUp} onClick={() => scrollToTarget(0)}>
            <Roll text="Go up" />
            <span aria-hidden="true">↑</span>
          </button>
        </div>
        <div className={s.wordmarkWrap}>
          <p className={s.wordmark} data-wordmark aria-label="nightlight">
            <span className={s.wmNight}>night</span>
            <span className={s.wmLight}>light</span>
          </p>
        </div>
        <p className={s.footerBase}>
          <span>© 2026 Nightlight</span>
          <span>The demo home is simulated.</span>
        </p>
      </footer>
    </div>
  );
}
