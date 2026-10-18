"use client";

import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import { ApprovalCard, ExplainCard, NoticeCard, TrustCard, type ApprovalState, type TrustState } from "../StoryCards";
import s from "./Home.module.css";

gsap.registerPlugin(useGSAP, ScrollTrigger);

// One night in four beats, with the app's real cards. On a wide screen with
// motion allowed, the section holds still while scrolling turns the beats like
// pages: the words leave upward through a mask and the next card wipes in.
// Everywhere else the beats simply stack.
const BEATS = [
  {
    title: "It notices.",
    text: "Every minute each machine reports how it’s doing. Tonight the Raspberry Pi in the attic is almost out of space.",
  },
  {
    title: "It explains.",
    text: "No error codes. It says what’s wrong, why it matters and what it already checked, in words anyone can follow.",
  },
  {
    title: "It asks first.",
    text: "Nothing changes without your yes. You see the plan, a dry run, what it touches and how to undo it. Go on, you approve it.",
  },
  {
    title: "It earns trust.",
    text: "After the same safe fix three times, it offers to do that one job on its own. You can take it back any time.",
  },
];

export function Loop() {
  const root = useRef<HTMLElement>(null);
  const [approval, setApproval] = useState<ApprovalState>("waiting");
  const [trust, setTrust] = useState<TrustState>("offer");

  useEffect(() => {
    if (approval !== "running") return;
    const id = window.setTimeout(() => setApproval("done"), 1800);
    return () => window.clearTimeout(id);
  }, [approval]);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(min-width: 960px) and (min-height: 640px) and (prefers-reduced-motion: no-preference)", () => {
        const stage = root.current!.querySelector<HTMLElement>("[data-stage]")!;
        const beats = gsap.utils.toArray<HTMLElement>("[data-beat]", stage);
        const marks = gsap.utils.toArray<HTMLElement>("[data-mark]", root.current);
        stage.dataset.pinned = "true";

        const words = (b: HTMLElement) => b.querySelectorAll("[data-rise]");
        const card = (b: HTMLElement) => b.querySelector("[data-card]");

        beats.forEach((b, i) => {
          if (i === 0) return;
          gsap.set(b, { autoAlpha: 0 });
          gsap.set(words(b), { yPercent: 105 });
          gsap.set(card(b), { clipPath: "inset(100% 0% 0% 0%)", y: 60 });
        });

        const tl = gsap.timeline({
          defaults: { ease: "power3.inOut", duration: 1 },
          scrollTrigger: {
            trigger: stage,
            start: "top top",
            end: () => `+=${window.innerHeight * (beats.length - 1) * 0.85}`,
            pin: true,
            scrub: 0.8,
            snap: { snapTo: "labels", duration: { min: 0.25, max: 0.7 }, delay: 0.08, ease: "power2.inOut" },
            invalidateOnRefresh: true,
          },
        });
        tl.addLabel("b0");
        beats.forEach((b, i) => {
          if (i === 0) return;
          const prev = beats[i - 1];
          // The next beat starts rising while the last one is still leaving, so
          // there is never a moment with nothing on screen.
          const out = `b${i - 1}+=0.15`;
          const inn = `b${i - 1}+=0.5`;
          tl.to(words(prev), { yPercent: -105, stagger: 0.05, duration: 0.8 }, out)
            .to(card(prev), { clipPath: "inset(0% 0% 100% 0%)", y: -60, duration: 0.8 }, out)
            .set(b, { autoAlpha: 1 }, inn)
            .to(words(b), { yPercent: 0, stagger: 0.06 }, inn)
            .to(card(b), { clipPath: "inset(0% 0% 0% 0%)", y: 0 }, inn)
            .to(marks[i], { scaleX: 1, duration: 0.6 }, inn)
            .set(prev, { autoAlpha: 0 })
            .addLabel(`b${i}`);
        });
        gsap.set(marks[0], { scaleX: 1 });

        return () => {
          delete stage.dataset.pinned;
        };
      });

      // Without the pin, each beat still arrives in order as it scrolls in.
      mm.add("(max-width: 959px), (max-height: 639px)", () => {
        gsap.utils.toArray<HTMLElement>("[data-beat]", root.current).forEach((b) => {
          gsap.from(b.querySelectorAll("[data-rise], [data-card]"), {
            y: 28,
            autoAlpha: 0,
            duration: 0.9,
            ease: "power3.out",
            stagger: 0.08,
            scrollTrigger: { trigger: b, start: "top 82%", once: true },
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

  return (
    <section ref={root} id="loop" className={s.loop} aria-labelledby="loop-title">
      <div className={s.loopStage} data-stage>
        <div className={s.loopHead}>
          <h2 id="loop-title" className={s.loopTitle}>
            How a night goes
          </h2>
          <div className={s.loopMarks} aria-hidden="true">
            {BEATS.map((b) => (
              <span key={b.title} className={s.loopMark}>
                <span data-mark />
              </span>
            ))}
          </div>
        </div>
        <ol className={s.beats}>
          {BEATS.map((b, i) => (
            <li key={b.title} className={s.beat} data-beat>
              <div className={s.beatText}>
                <h3 className={s.beatTitle}>
                  <span className={s.mask}>
                    <span data-rise>{b.title}</span>
                  </span>
                </h3>
                <p className={s.beatBody}>
                  <span className={s.mask}>
                    <span data-rise>{b.text}</span>
                  </span>
                </p>
              </div>
              <div className={s.beatCard} data-card data-ui>
                {cards[i]}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
