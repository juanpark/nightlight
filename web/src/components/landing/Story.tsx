"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { House } from "./House";
import { ApprovalCard, ExplainCard, NoticeCard, TrustCard, type ApprovalState, type TrustState } from "./StoryCards";
import s from "./Story.module.css";

const WIDE = "-560 40 1600 720";
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
// past it. The beat in the middle of the screen drives the stage.
export function Story({ hero }: { hero: ReactNode }) {
  const [beat, setBeat] = useState(0);
  const [approval, setApproval] = useState<ApprovalState>("waiting");
  const [trust, setTrust] = useState<TrustState>("offer");
  const track = useRef<HTMLDivElement>(null);
  const narrow = useSyncExternalStore(
    subscribeNarrow,
    () => window.matchMedia("(max-width: 760px)").matches,
    () => false,
  );

  useEffect(() => {
    const items = track.current?.querySelectorAll<HTMLElement>("[data-step]");
    if (!items) return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setBeat(Number(e.target.getAttribute("data-step")));
      },
      { rootMargin: "-50% 0px -40% 0px" },
    );
    items.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (approval !== "running") return;
    const t = setTimeout(() => setApproval("done"), 1600);
    return () => clearTimeout(t);
  }, [approval]);

  return (
    <section className={s.world} aria-label="How Nightlight looks after a home">
      <div className={s.stage} data-beat={beat} data-fixed={beat === 4 || approval === "done"}>
        <Sky />
        <House viewBox={narrow ? NARROW : WIDE} />
        <div className={s.scrim} />
        <p className={s.sample}>
          <span className={s.sampleDot} />
          Sample home · simulated
        </p>
      </div>

      <div className={s.track} ref={track}>
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
      <circle className={s.moonHalo} cx="78" cy="13" r="3.4" />
      <circle className={s.moon} cx="78" cy="13" r="1.9" />
      <circle className={s.moonShade} cx="78.8" cy="12.5" r="1.6" />
    </svg>
  );
}
