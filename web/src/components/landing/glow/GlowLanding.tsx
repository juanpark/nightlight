"use client";

import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import Lenis from "lenis";
import { Logo } from "../../brand/Logo";
import { AuthButtons } from "../AuthButtons";
import { Icon, type IconName } from "../Icon";
import { ApprovalCard, ExplainCard, NoticeCard, TrustCard, type ApprovalState, type TrustState } from "../StoryCards";
import { display, sans } from "../fonts";
import type { View } from "./scene";
import s from "./Glow.module.css";

gsap.registerPlugin(useGSAP, ScrollTrigger);

// The glow variant of the landing page: one night in a clay dollhouse, drawn in
// 3D behind the page. Scrolling moves the camera while a small warm light goes
// room to room checking each machine (01), finds the Pi's disk almost full and
// explains it (02), asks before cleaning up (03), and is trusted with the job
// next time (04). The real story cards sit beside it. Under reduced motion the
// camera jumps between still views instead of travelling.

const STEPS = [
  {
    title: "It notices",
    text: "The light goes room to room and checks every machine. Tonight the Raspberry Pi in the attic is almost out of space.",
  },
  {
    title: "It explains",
    text: "No error codes. It says what’s wrong, why it matters and what it already looked at, in words anyone can follow.",
  },
  {
    title: "It asks first",
    text: "Nothing changes without your yes. You see the plan, a dry run, what it touches and how to undo it.",
  },
  {
    title: "Trust grows",
    text: "After the same safe fix a few times, it offers to handle that one job on its own. You can take it back any time.",
  },
];

const FEATURES: { icon: IconName; title: string; text: string }[] = [
  { icon: "eye", title: "One friendly map", text: "Every machine at home, what it does, and the one thing that needs you." },
  { icon: "plan", title: "Plain words", text: "Problems explained the way a patient neighbour would, never as a log file." },
  { icon: "shield", title: "Your yes, every time", text: "Each job shows its risk. Nothing risky ever happens on its own." },
  { icon: "check", title: "Stays at home", text: "Only health numbers leave a device. Never your files, passwords or machine names." },
];

// Where the camera is at each beat: 0 is the top of the page, 1–4 the steps.
const BASE: View = {
  tx: 0, ty: 12.6, tz: 0, zoom: 0.84, az: 30, el: 22, ox: 0, oy: 0,
  follow: 0, trail: 0, rings: 0, done: 0, lit: 0, orb: 0,
};
const KEYS: Partial<View>[] = [
  BASE,
  { tx: 0, ty: 6.4, tz: -1, zoom: 1.65, az: 26, el: 28, ox: -0.1, oy: 0.2, follow: 0.25, rings: 1 },
  { tx: 0.2, ty: 6.6, tz: -1.4, zoom: 2.05, az: 20, el: 24, ox: -0.12, oy: 0.2, follow: 0, rings: 1 },
  { tx: 0.2, ty: 6.7, tz: -1.4, zoom: 2.4, az: 14, el: 21, ox: -0.13, oy: 0.2, follow: 0, rings: 1 },
  { tx: 0, ty: 5.6, tz: 0, zoom: 0.9, az: 28, el: 20, ox: -0.12, oy: 0.18, follow: 0, rings: 0, lit: 1, orb: 1 },
];
// The still view for each beat (reduced motion).
const STILL: View[] = KEYS.map((_, i) => ({
  ...BASE,
  ...KEYS[i],
  trail: i === 0 ? 0 : 1,
  done: i === 4 ? 1 : 0,
}));

export function GlowLanding() {
  const root = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef<View>({ ...BASE });
  const fixed = useRef({ done: 0 }); // the Approve button fixes the Pi too
  const [step, setStep] = useState(0);
  const shown = useRef(0); // the step on screen, so scrolling only re-renders when it changes
  const covered = useRef(false);
  const [gl, setGl] = useState<"loading" | "on" | "off">("loading");
  const [approval, setApproval] = useState<ApprovalState>("waiting");
  const [trust, setTrust] = useState<TrustState>("offer");

  // The scene, loaded on its own so three.js stays off the first paint.
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let api: { draw: (v: View, t: number) => void; dispose: () => void } | undefined;
    let live = true;
    const frame = (time: number) => {
      if (covered.current) return;
      api?.draw({ ...view.current, done: Math.max(view.current.done, fixed.current.done) }, time);
    };
    import("./scene")
      .then(({ createScene }) => {
        if (!live) return;
        api = createScene(el, { calm });
        gsap.ticker.add(frame);
        setGl("on");
      })
      .catch(() => live && setGl("off"));
    return () => {
      live = false;
      gsap.ticker.remove(frame);
      api?.dispose();
    };
  }, []);

  // Scroll: smooth scrolling, and one timeline from the top of the page to the last step.
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add({ calm: "(prefers-reduced-motion: reduce)", motion: "(prefers-reduced-motion: no-preference)" }, (ctx) => {
        const { calm } = ctx.conditions as { calm: boolean };
        // Beat i is reached when step i's top meets the top of the screen. Steps can be
        // taller than the screen (phones), so the beats are measured, not assumed.
        let marks = [0, 1, 2, 3, 4];
        const measure = () => {
          marks = [0, 1, 2, 3, 4].map((i) =>
            i === 0 ? 0 : (document.getElementById(`step-${i}`)?.getBoundingClientRect().top ?? 0) + window.scrollY,
          );
        };
        const beat = (y: number) => {
          for (let i = 1; i < marks.length; i++) {
            if (y < marks[i]) return i - 1 + (y - marks[i - 1]) / Math.max(1, marks[i] - marks[i - 1]);
          }
          return 4;
        };
        measure();

        if (calm) {
          ScrollTrigger.create({
            start: 0,
            end: () => marks[4],
            onRefresh: measure,
            onUpdate: (self) => {
              const i = Math.round(beat(self.scroll()));
              shown.current = i;
              setStep(i);
              Object.assign(view.current, STILL[i]);
            },
          });
          return;
        }

        const lenis = new Lenis({ anchors: true });
        lenis.on("scroll", ScrollTrigger.update);
        const raf = (t: number) => lenis.raf(t * 1000);
        gsap.ticker.add(raf);
        gsap.ticker.lagSmoothing(0);

        const v = view.current;
        const ease = "power2.inOut";
        const tl = gsap.timeline({ paused: true, defaults: { ease } });
        // 0 → 1: the camera follows the light along the wire, then settles on the Pi.
        tl.to(v, { trail: 1, duration: 1, ease: "power1.inOut" }, 0)
          .to(v, { tx: 0, ty: 4, zoom: 1.35, az: 30, ox: -0.08, oy: 0.2, follow: 0.6, rings: 0, duration: 0.45 }, 0)
          .to(v, { ...KEYS[1], duration: 0.55 }, 0.45)
          .to(v, { ...KEYS[2], duration: 1 }, 1)
          .to(v, { ...KEYS[3], duration: 1 }, 2)
          .to(v, { done: 1, duration: 0.35 }, 3)
          .to(v, { ...KEYS[4], duration: 1 }, 3);

        // Scrubbed by hand, so each beat lands on its own step. Lenis already smooths the
        // scroll; the timeline only takes a light, frame-rate-independent damping on top.
        let want = 0;
        const follow = (y: number) => {
          const b = beat(y);
          want = b / 4;
          const i = Math.round(b);
          if (i !== shown.current) {
            shown.current = i;
            setStep(i);
          }
        };
        const damp = (_t: number, dtMs: number) => {
          const p = tl.progress();
          if (p === want) return;
          const next = p + (want - p) * (1 - Math.exp(-(dtMs / 1000) * 6));
          tl.progress(Math.abs(want - next) < 1e-5 ? want : next);
        };
        gsap.ticker.add(damp);
        ScrollTrigger.create({
          start: 0,
          end: () => marks[4],
          onRefresh: (self) => {
            measure();
            follow(self.scroll());
          },
          onUpdate: (self) => follow(self.scroll()),
        });

        // Past the feature grid the scene is covered: stop drawing it.
        ScrollTrigger.create({
          trigger: "#why",
          start: "center top",
          end: "max",
          onToggle: (self) => {
            covered.current = self.isActive;
          },
        });

        // The opening: the copy rises in while the light starts up.
        const q = gsap.utils.selector(root);
        gsap.from(q("[data-rise]"), { y: 24, opacity: 0, duration: 1.1, stagger: 0.09, ease: "power3.out", delay: 0.15 });

        return () => {
          gsap.ticker.remove(raf);
          gsap.ticker.remove(damp);
          lenis.destroy();
        };
      });
    },
    { scope: root },
  );

  // Approve → a short run → done, and the Pi's light turns green.
  useEffect(() => {
    if (approval === "running") {
      const t = setTimeout(() => setApproval("done"), 1600);
      return () => clearTimeout(t);
    }
    gsap.to(fixed.current, { done: approval === "done" ? 1 : 0, duration: 0.8, ease: "power2.out" });
  }, [approval]);

  return (
    <div ref={root} className={`${s.page} ${display.variable} ${sans.variable}`} data-landing data-gl={gl}>
      <a href="#glow-main" className={s.skip}>
        Skip to content
      </a>
      <canvas ref={canvas} className={s.scene} aria-hidden="true" />
      <div className={s.vignette} aria-hidden="true" />

      <header className={s.nav}>
        <nav className={s.links} aria-label="Sections">
          <a href="#story">The night story</a>
          <a href="#why">Why it’s different</a>
        </nav>
        <a href="/" className={s.brand} aria-label="Nightlight, home">
          <Logo height={24} />
        </a>
        <div className={s.navActions}>
          <AuthButtons size="small" styles={s} />
        </div>
      </header>

      <main id="glow-main" className={s.main}>
        <section className={s.hero} aria-labelledby="glow-title">
          <h1 id="glow-title" className={s.h1} data-rise>
            A house‑sitter for the machines you run at home.
          </h1>
          <p className={s.lede} data-rise>
            Nightlight watches every device while you sleep, explains problems in plain words, and fixes things only
            when you say yes.
          </p>
          <div data-rise>
            <AuthButtons styles={s} />
          </div>
          <a href="#step-1" className={s.cue} data-rise>
            Scroll to watch one night
          </a>
          <p className={s.sample}>
            <span className={s.sampleDot} aria-hidden="true" />
            Sample home · simulated
          </p>
        </section>

        <section id="story" className={s.story} aria-label="One night with Nightlight">
          <div className={s.railWrap}>
            <nav className={s.rail} data-show={step > 0} aria-label="Steps">
              <ol>
                {STEPS.map((st, i) => (
                  <li key={st.title} data-active={step === i + 1 || undefined}>
                    <a href={`#step-${i + 1}`} aria-current={step === i + 1 ? "step" : undefined}>
                      <span className={s.num}>{String(i + 1).padStart(2, "0")}</span>
                      <span className={s.railTitle}>{st.title}</span>
                    </a>
                    <p className={s.railText} aria-hidden="true">
                      {st.text}
                    </p>
                  </li>
                ))}
              </ol>
            </nav>
          </div>

          {STEPS.map((st, i) => (
            <article key={st.title} id={`step-${i + 1}`} className={s.step} data-active={step === i + 1 || undefined}>
              <div className={s.stepCopy}>
                <p className={s.stepNum}>{String(i + 1).padStart(2, "0")}</p>
                <h2 className={s.stepTitle}>{st.title}</h2>
                <p className={s.stepText}>{st.text}</p>
              </div>
              <div className={s.cardSlot}>
                {i === 0 && <NoticeCard />}
                {i === 1 && <ExplainCard />}
                {i === 2 && <ApprovalCard state={approval} onChange={setApproval} />}
                {i === 3 && <TrustCard state={trust} onChange={setTrust} />}
              </div>
            </article>
          ))}
        </section>

        <section id="why" className={s.why} aria-labelledby="why-title">
          <h2 id="why-title" className={s.h2}>
            Made for people who have never opened a terminal.
          </h2>
          <ul className={s.grid}>
            {FEATURES.map((f) => (
              <li key={f.title}>
                <span className={s.featIcon}>
                  <Icon name={f.icon} size={22} />
                </span>
                <h3>{f.title}</h3>
                <p>{f.text}</p>
              </li>
            ))}
          </ul>
        </section>

        <section className={s.closing} aria-labelledby="closing-title">
          <h2 id="closing-title" className={s.h2}>
            Go to sleep. Nightlight keeps the light on.
          </h2>
          <AuthButtons styles={s} />
          <p className={s.fine}>The demo needs no account. It runs on a simulated sample home.</p>
        </section>
      </main>

      <footer className={s.footer}>
        <Logo height={18} />
        <nav aria-label="Other versions">
          <a href="/">Night story</a>
          <a href="/day">Lit room</a>
        </nav>
        <p>Every device on this page is simulated.</p>
      </footer>
    </div>
  );
}
