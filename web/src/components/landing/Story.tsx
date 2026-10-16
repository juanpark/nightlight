"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import Lenis from "lenis";
import "lenis/dist/lenis.css";
import { House } from "./House";
import { ApprovalCard, ExplainCard, NoticeCard, TrustCard, type ApprovalState, type TrustState } from "./StoryCards";
import s from "./Story.module.css";

gsap.registerPlugin(ScrollTrigger, useGSAP);

const WIDE = "-560 40 1600 720";

// Camera framings in the house's own coordinates: the whole house, and pushed
// into the attic beside the Pi (a different crop on phones).
const HOME = { x: 0, y: 0, scale: 1 };
const ATTIC = { x: -466, y: -209, scale: 1.85 };
const ATTIC_NARROW = { x: -442, y: -102, scale: 1.85 };
const NARROW = "30 96 980 640";

function subscribeNarrow(cb: () => void) {
  const mq = window.matchMedia("(max-width: 760px)");
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

const BEATS = [
  {
    title: "It notices.",
    body: "Nightlight checks every device about once a minute. When something drifts, it tells you in one sentence, not a wall of graphs.",
  },
  {
    title: "It explains, in plain words.",
    body: "Ask it anything about your home. It looks first, then answers in a few short sentences you’d understand at breakfast.",
  },
  {
    title: "It asks before it touches anything.",
    body: "Every fix comes as a card: what it will do, a dry run, what it touches and how to undo it. Nothing changes until you tap Approve.",
  },
  {
    title: "Trust grows, one kind of job at a time.",
    body: "After three good clean-ups, Nightlight may offer to handle that job itself. Risky jobs always ask, and jobs on your real devices always wait for your tap.",
  },
];

// The night story: a sticky stage with the house, and four beats that scroll
// past it. ScrollTrigger tells the stage which beat is being read and moves
// the camera with the scroll; Lenis smooths the scrolling itself.
export function Story({ hero }: { hero: ReactNode }) {
  const [beat, setBeat] = useState(0);
  const [approval, setApproval] = useState<ApprovalState>("waiting");
  const [trust, setTrust] = useState<TrustState>("offer");
  const world = useRef<HTMLElement>(null);
  const narrow = useSyncExternalStore(
    subscribeNarrow,
    () => window.matchMedia("(max-width: 760px)").matches,
    () => false,
  );

  useGSAP(
    () => {
      const root = world.current;
      if (!root) return;
      const steps = gsap.utils.toArray<HTMLElement>("[data-step]", root);

      // The beat whose text crosses the middle of the screen drives the stage.
      for (const el of steps) {
        ScrollTrigger.create({
          trigger: el,
          start: "top 55%",
          end: "bottom 55%",
          onToggle: (self) => self.isActive && setBeat(Number(el.dataset.step)),
        });
      }

      const mm = gsap.matchMedia();

      // Smooth, weighted scrolling for mouse and trackpad; touch keeps its own.
      mm.add("(pointer: fine) and (prefers-reduced-motion: no-preference)", () => {
        const lenis = new Lenis({ anchors: true, autoRaf: false });
        lenis.on("scroll", ScrollTrigger.update);
        const raf = (time: number) => lenis.raf(time * 1000);
        gsap.ticker.add(raf);
        gsap.ticker.lagSmoothing(0);
        return () => {
          gsap.ticker.remove(raf);
          gsap.ticker.lagSmoothing(500, 33);
          lenis.destroy();
        };
      });

      // The camera rides the scroll: it pushes into the attic as the first beat
      // arrives and pulls back to the lit house for the last one.
      mm.add(
        { wide: "(min-width: 761px) and (prefers-reduced-motion: no-preference)", narrow: "(max-width: 760px) and (prefers-reduced-motion: no-preference)" },
        (ctx) => {
          const cam = root.querySelector("[data-camera]");
          const attic = ctx.conditions?.narrow ? ATTIC_NARROW : ATTIC;
          const [, first, , , last] = steps;
          if (!cam || !first || !last) return;
          gsap.set(cam, { svgOrigin: "0 0", ...HOME });
          const ride = { ease: "power2.inOut", immediateRender: false };
          gsap.fromTo(cam, HOME, { ...attic, ...ride, scrollTrigger: { trigger: first, start: "top 95%", end: "top 30%", scrub: 0.8 } });
          gsap.fromTo(cam, attic, { ...HOME, ...ride, scrollTrigger: { trigger: last, start: "top 95%", end: "top 30%", scrub: 0.8 } });

          // Each beat's words and card rise in as they reach the reading line.
          for (const el of steps.slice(1)) {
            gsap.from(el.children, {
              y: 36,
              opacity: 0,
              duration: 0.9,
              ease: "power3.out",
              stagger: 0.12,
              scrollTrigger: { trigger: el, start: "top 72%", once: true },
            });
          }
        },
      );
      return () => mm.revert();
    },
    { scope: world },
  );

  useEffect(() => {
    if (approval !== "running") return;
    const t = setTimeout(() => setApproval("done"), 1600);
    return () => clearTimeout(t);
  }, [approval]);

  return (
    <section ref={world} className={s.world} aria-label="How Nightlight looks after a home">
      <div className={s.stage} data-beat={beat} data-fixed={beat === 4 || approval === "done"}>
        <Sky />
        <House viewBox={narrow ? NARROW : WIDE} />
        <div className={s.scrim} />
        <p className={s.sample}>
          <span className={s.sampleDot} />
          Sample home · simulated
        </p>
      </div>

      <div className={s.track}>
        <div className={s.hero} data-step="0">
          {hero}
        </div>
        <div id="how" className={s.anchor} />
        {BEATS.map((b, i) => (
          <article key={b.title} className={s.beat} data-step={i + 1}>
            <div className={s.beatText}>
              <h2 className={s.beatTitle}>{b.title}</h2>
              <p className={s.beatBody}>{b.body}</p>
            </div>
            {i === 0 && <NoticeCard />}
            {i === 1 && <ExplainCard />}
            {i === 2 && (
              <>
                <ApprovalCard state={approval} onChange={setApproval} />
                {approval === "waiting" && <p className={s.nudge}>It’s the sample home. Go ahead and tap.</p>}
              </>
            )}
            {i === 3 && <TrustCard state={trust} onChange={setTrust} />}
          </article>
        ))}
      </div>
    </section>
  );
}

// Stars and the moon, fixed to the sky while the camera moves.
function Sky() {
  const stars = [
    [6, 12, 1.2], [14, 30, 0.8], [22, 8, 1], [31, 22, 0.7], [38, 5, 1.3], [44, 34, 0.8], [52, 15, 1],
    [58, 4, 0.7], [63, 27, 1.1], [69, 10, 0.8], [76, 31, 0.9], [83, 6, 1.2], [91, 24, 0.8], [96, 12, 1],
    [10, 44, 0.7], [27, 40, 0.9], [48, 46, 0.7], [72, 42, 0.8], [88, 40, 0.7], [18, 18, 0.6], [57, 38, 0.6],
  ];
  return (
    <svg className={s.sky} viewBox="0 0 100 60" preserveAspectRatio="xMidYMin slice" aria-hidden="true" focusable="false">
      {stars.map(([x, y, r], i) => (
        <circle key={i} cx={x} cy={y} r={r * 0.16} className={i % 4 === 0 ? s.twinkle : undefined} style={{ animationDelay: `${(i % 7) * 0.9}s` }} />
      ))}
      <filter id="nl-moonblur" x="-1" y="-1" width="3" height="3">
        <feGaussianBlur stdDeviation="1.1" />
      </filter>
      <circle className={s.moonHalo} cx="78" cy="13" r="3.6" filter="url(#nl-moonblur)" />
      <circle className={s.moon} cx="78" cy="13" r="1.9" />
      <circle className={s.moonShade} cx="78.8" cy="12.5" r="1.6" />
    </svg>
  );
}
