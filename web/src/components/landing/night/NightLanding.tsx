"use client";

import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { useGSAP } from "@gsap/react";
import { Logo, LogoIcon } from "../../brand/Logo";
import { AuthButtons } from "../AuthButtons";
import { ApprovalCard, ExplainCard, NoticeCard, TrustCard, type ApprovalState, type TrustState } from "../StoryCards";
import { revealLines } from "../motion/reveal";
import { Roll } from "../motion/Roll";
import { scrollToTarget, useSmoothScroll } from "../motion/smooth";
import { archivo } from "./fonts";
import { Ledger } from "./Ledger";
import { Starfield } from "./Starfield";
import s from "./Night.module.css";

gsap.registerPlugin(useGSAP, ScrollTrigger, SplitText);

// "/night": the Swiss-grid variant. Small precise type against very large
// condensed capitals, the night's four moments on a sideways track, a ledger
// of tonight's checks, and a footer under a field of stars.

const LINKS = [
  { href: "#moments", label: "Tonight" },
  { href: "#ledger", label: "Ledger" },
  { href: "#privacy", label: "Privacy" },
];

const MOMENTS = [
  { name: "It notices", device: "Raspberry Pi", time: "02:15", state: "Needs a look" },
  { name: "It explains", device: "In plain words", time: "02:16", state: "No error codes" },
  { name: "It asks first", device: "Your yes", time: "02:16", state: "Try Approve" },
  { name: "It earns trust", device: "One job at a time", time: "Next week", state: "Yours to undo" },
];

const SENT = [
  ["CPU, memory and disk", "as percentages"],
  ["Services and containers", "names and whether they run"],
  ["Updates waiting", "a count"],
  ["Two safety checks", "yes or no"],
];
const NEVER = ["Host names, IP or hardware addresses", "Your files", "Passwords or keys", "Environment variables"];

function useClock() {
  const [t, setT] = useState<string | null>(null);
  useEffect(() => {
    const tick = () => setT(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }));
    tick();
    const id = window.setInterval(tick, 15_000);
    return () => window.clearInterval(id);
  }, []);
  return t;
}

export function NightLanding() {
  const root = useRef<HTMLDivElement>(null);
  const [approval, setApproval] = useState<ApprovalState>("waiting");
  const [trust, setTrust] = useState<TrustState>("offer");
  const [popup, setPopup] = useState(false);
  const clock = useClock();
  useSmoothScroll();

  useEffect(() => {
    if (approval !== "running") return;
    const id = window.setTimeout(() => setApproval("done"), 1800);
    return () => window.clearTimeout(id);
  }, [approval]);

  useGSAP(
    () => {
      const q = gsap.utils.selector(root);
      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        // Header and first screen.
        gsap.from(q("[data-head] > *"), { y: -14, autoAlpha: 0, duration: 0.9, ease: "power3.out", stagger: 0.05, delay: 0.1 });
        SplitText.create(q("[data-hero-title]")[0], {
          type: "chars,lines",
          mask: "lines",
          autoSplit: true,
          onSplit: (self) =>
            gsap.from(self.chars, { yPercent: 115, duration: 1.3, ease: "expo.out", stagger: 0.018, delay: 0.25 }),
        });
        gsap.from(q("[data-hero-foot] > *"), { y: 20, autoAlpha: 0, duration: 1, ease: "power3.out", stagger: 0.08, delay: 0.9 });

        q("[data-lines]").forEach((el) => revealLines(el));
        q("[data-rise]").forEach((el) =>
          gsap.from(el, { y: 26, autoAlpha: 0, duration: 1, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 88%", once: true } }),
        );

        // The statement fills in letter by letter as it passes.
        SplitText.create(q("[data-fill]")[0], {
          type: "chars",
          autoSplit: true,
          onSplit: (self) =>
            gsap.fromTo(
              self.chars,
              { opacity: 0.16 },
              {
                opacity: 1,
                ease: "none",
                stagger: 0.04,
                scrollTrigger: { trigger: q("[data-fill]")[0], start: "top 80%", end: "bottom 35%", scrub: 0.6 },
              },
            ),
        });

        // Ledger rows draw in one after another.
        gsap.from(q("[data-ledger] tbody tr"), {
          y: 22,
          autoAlpha: 0,
          duration: 0.8,
          ease: "power3.out",
          stagger: 0.06,
          scrollTrigger: { trigger: q("[data-ledger]")[0], start: "top 80%", once: true },
        });

        // Footer headline.
        SplitText.create(q("[data-foot-title]")[0], {
          type: "chars,lines",
          mask: "lines",
          autoSplit: true,
          onSplit: (self) =>
            gsap.from(self.chars, {
              yPercent: 115,
              duration: 1.2,
              ease: "expo.out",
              stagger: 0.02,
              scrollTrigger: { trigger: q("[data-foot-title]")[0], start: "top 85%", once: true },
            }),
        });
      });

      mm.add("(prefers-reduced-motion: no-preference) and (min-width: 760px)", () => {
        // Tonight: the four moments slide past sideways.
        const track = q("[data-track]")[0] as HTMLElement;
        const pane = q("[data-moments]")[0] as HTMLElement;
        const distance = () => track.scrollWidth - pane.clientWidth;
        const slide = gsap.to(track, {
          x: () => -distance(),
          ease: "none",
          scrollTrigger: {
            trigger: pane,
            start: "top top",
            end: () => `+=${distance()}`,
            pin: true,
            scrub: 0.8,
            invalidateOnRefresh: true,
          },
        });
        q("[data-panel]").forEach((p) => {
          gsap.from(p.querySelector("[data-panel-card]"), {
            yPercent: 12,
            rotate: 2,
            ease: "none",
            scrollTrigger: { trigger: p, containerAnimation: slide, start: "left right", end: "center center", scrub: true },
          });
        });
      });
    },
    { scope: root },
  );

  const cards = [
    <NoticeCard key="n" />,
    <ExplainCard key="e" />,
    <ApprovalCard key="a" state={approval} onChange={setApproval} />,
    <TrustCard key="t" state={trust} onChange={setTrust} />,
  ];

  const go = (href: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    scrollToTarget(href);
  };

  return (
    <div ref={root} className={`${s.page} ${archivo.variable}`} data-theme="night">
      <a href="#main" className={s.skip}>
        Skip to content
      </a>

      <header className={s.head} data-head>
        <a href="#top" className={s.brand} onClick={go("#top")} aria-label="Nightlight, back to top">
          <Logo height={20} />
        </a>
        <p className={s.headRole}>A house-sitter for home servers</p>
        <p className={s.headLive}>
          <span className={s.liveDot} aria-hidden="true" />
          Sample home, {clock ?? "tonight"}
        </p>
        <nav className={s.headLinks} aria-label="Sections">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} onClick={go(l.href)}>
              <Roll text={l.label} />
            </a>
          ))}
        </nav>
        <div className={s.headDemo}>
          <AuthButtons size="small" demoOnly styles={s} />
        </div>
      </header>

      <main id="main">
        <section id="top" className={s.hero} aria-labelledby="hero-title">
          <h1 id="hero-title" className={s.heroTitle} data-hero-title>
            Watches your home
            <br />
            while you sleep
          </h1>
          <div className={s.heroFoot} data-hero-foot>
            <p className={s.heroLede}>
              Nightlight keeps an eye on the computers in your home or small office, explains what it finds in plain
              words, and never changes anything without your yes.
            </p>
            <AuthButtons styles={s} />
          </div>
        </section>

        <section className={s.hello} aria-labelledby="hello-title">
          <h2 id="hello-title" className={s.helloTitle} data-lines>
            Good evening.
          </h2>
          <p className={s.helloLead} data-lines>
            Nightlight shows every machine you run on one calm map, and keeps watch over them at night.
          </p>
          <div className={s.helloText} data-rise>
            <p>
              It starts by asking about everything. When a fix would help, it shows you the plan, a dry run, what it
              touches and how to undo it, and waits for your tap.
            </p>
            <p>
              After the same safe job has gone well a few times, it may offer to handle that one job on its own. Risky
              jobs always ask.
            </p>
          </div>
          <div className={s.sticker} data-rise aria-hidden="true">
            <LogoIcon size={44} />
            <span className={s.stickerWord}>
              <span>On</span>
              <span>watch</span>
            </span>
          </div>
        </section>

        <section id="moments" className={s.moments} data-moments aria-labelledby="moments-title">
          <div className={s.momentsHead}>
            <h2 id="moments-title" className={s.momentsTitle}>
              Tonight, in four moments
            </h2>
            <p className={s.momentsNote}>The real app cards, on a simulated sample home.</p>
          </div>
          <div className={s.track} data-track>
            {MOMENTS.map((m, i) => (
              <article key={m.name} className={s.panel} data-panel>
                <div className={s.panelStage}>
                  <div className={s.panelCard} data-panel-card data-ui>
                    {cards[i]}
                  </div>
                </div>
                <dl className={s.panelMeta}>
                  <div>
                    <dt className={s.srOnly}>Moment</dt>
                    <dd className={s.panelName}>{m.name}</dd>
                  </div>
                  <div>
                    <dt className={s.srOnly}>About</dt>
                    <dd className={s.panelDim}>{m.device}</dd>
                  </div>
                  <div>
                    <dt className={s.srOnly}>When</dt>
                    <dd>{m.time}</dd>
                  </div>
                  <div>
                    <dt className={s.srOnly}>State</dt>
                    <dd>{m.state}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </section>

        <section className={s.fillWrap} aria-label="The one rule">
          <h2 className={s.fill} data-fill>
            Nothing changes
            <br />
            without your yes
          </h2>
        </section>

        <section id="ledger" className={s.ledgerWrap} data-ledger aria-labelledby="ledger-title">
          <div className={s.sectionHead}>
            <h2 id="ledger-title" className={s.h2} data-lines>
              The ledger
            </h2>
            <p className={s.sectionNote} data-rise>
              Every device on the sample home and what it said tonight. Hover a row to see what the light saw.
            </p>
          </div>
          <Ledger />
        </section>

        <section id="privacy" className={s.privacy} aria-labelledby="privacy-title">
          <div className={s.sectionHead}>
            <h2 id="privacy-title" className={s.h2} data-lines>
              What leaves the house
            </h2>
            <p className={s.sectionNote} data-rise>
              A small helper on each device reports health numbers once a minute. Run it with “show” to print exactly
              what it would send.
            </p>
          </div>
          <div className={s.privacyGrid}>
            <table className={s.privacyTable} data-rise>
              <caption className={s.privacyCap}>Sent</caption>
              <tbody>
                {SENT.map(([a, b]) => (
                  <tr key={a}>
                    <th scope="row">{a}</th>
                    <td>{b}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <table className={s.privacyTable} data-rise>
              <caption className={s.privacyCap}>Never sent</caption>
              <tbody>
                {NEVER.map((a) => (
                  <tr key={a}>
                    <th scope="row">{a}</th>
                    <td>never</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>

      <footer className={s.footer}>
        <Starfield className={s.stars} />
        <div className={s.footCenter}>
          <h2 className={s.footTitle} data-foot-title>
            Go to sleep.
            <br />
            It’s got this.
          </h2>
          <div
            className={s.footCta}
            onPointerEnter={() => setPopup(true)}
            onPointerLeave={() => setPopup(false)}
            onFocus={() => setPopup(true)}
            onBlur={() => setPopup(false)}
          >
            <AuthButtons styles={{ ...s, primary: s.bigButton }} magnetic />
            <p className={s.popup} data-open={popup || undefined} role="note">
              A simulated sample home opens in one click. No account, nothing to install.
            </p>
          </div>
        </div>
        <div className={s.footBar}>
          <p>The demo home is simulated.</p>
          <nav aria-label="Footer" className={s.footLinks}>
            {LINKS.map((l) => (
              <a key={l.href} href={l.href} onClick={go(l.href)}>
                <Roll text={l.label} />
              </a>
            ))}
            <button type="button" onClick={() => scrollToTarget(0)} className={s.footUp}>
              <Roll text="Back to top" />
            </button>
          </nav>
          <p>© 2026 Nightlight</p>
        </div>
      </footer>
    </div>
  );
}
