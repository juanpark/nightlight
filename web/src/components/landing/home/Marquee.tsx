"use client";

import { useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import s from "./Home.module.css";

gsap.registerPlugin(useGSAP, ScrollTrigger);

// The machines a home runs, drifting past in two rows that run opposite ways.
// Scrolling pushes them faster for a moment, in the direction you scroll.
const ROWS = [
  ["Raspberry Pi", "Home NAS", "Wi-Fi router", "Minecraft server", "Mac Mini", "Camera recorder"],
  ["Home VPN", "Ad blocker", "Photo backups", "Home automation", "Media server", "Office printer"],
];

function Star() {
  return (
    <svg className={s.marqueeStar} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 1.5l2.9 6.6 7.1.7-5.4 4.8 1.6 7-6.2-3.7-6.2 3.7 1.6-7L2 8.8l7.1-.7Z" />
    </svg>
  );
}

export function Marquee() {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const tracks = gsap.utils.toArray<HTMLElement>("[data-track]", root.current);
        const loops = tracks.map((t, i) =>
          gsap.fromTo(
            t,
            { xPercent: i % 2 ? -50 : 0 },
            { xPercent: i % 2 ? 0 : -50, duration: 38 + i * 6, ease: "none", repeat: -1 },
          ),
        );
        let dir = 1;
        ScrollTrigger.create({
          trigger: root.current,
          start: "top bottom",
          end: "bottom top",
          onUpdate(self) {
            const v = self.getVelocity();
            if (Math.abs(v) < 1) return;
            dir = v < 0 ? -1 : 1;
            const boost = gsap.utils.clamp(1, 5, 1 + Math.abs(v) / 500);
            loops.forEach((l) =>
              gsap.fromTo(l, { timeScale: boost * dir }, { timeScale: dir, duration: 1.2, ease: "power2.out", overwrite: true }),
            );
          },
        });
      });
    },
    { scope: root },
  );

  return (
    <div ref={root} className={s.marquee} role="img" aria-label="Machines Nightlight watches: Raspberry Pi, NAS, router, game servers and more">
      {ROWS.map((row, i) => (
        <div key={i} className={s.marqueeRow} data-dim={i === 1 || undefined} aria-hidden="true">
          <div className={s.marqueeTrack} data-track>
            {[0, 1].map((copy) => (
              <span key={copy} className={s.marqueeSet}>
                {row.map((w) => (
                  <span key={w} className={s.marqueeItem}>
                    {w}
                    <Star />
                  </span>
                ))}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
