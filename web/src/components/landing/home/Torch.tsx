"use client";

import { useEffect, useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { reducedMotion } from "../motion/smooth";
import s from "./Home.module.css";

// The hero's torch: a white disc that follows the pointer with a little lag,
// blending in difference mode so the night turns light under it and the text
// turns navy. It lives only in the first screen. As the hero scrolls away the
// disc shrinks, turns star yellow and flies into the dot on the logo's "i",
// so the light goes home; scrolling back up lets it out again. It is widest
// mid-hero and narrows toward the top and bottom edges. It flickers on
// at the first move, steps aside over anything pressable, and hides when the pointer
// leaves or someone moves with the keyboard. Touch and reduced motion get none.

// Where the light sits in the Logo's viewBox ("-40 -1230 5414 1530").
const DOT = { x: (3376 + 40) / 5414, y: (-800 + 1230) / 1530, r: 150 / 1530 };

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const ramp = (a: number, b: number, v: number) => clamp01((v - a) / (b - a));

// How small the light gets at the hero's top and bottom edges, as a share of
// its full size in the middle band.
const EDGE = 0.45;
// Full size through the middle of the hero, easing down toward either edge.
const bell = (v: number) => {
  const u = Math.abs(clamp01(v) * 2 - 1);
  return 1 - (1 - EDGE) * u * u * (3 - 2 * u);
};

export function Torch() {
  const disc = useRef<HTMLDivElement>(null);
  const tint = useRef<HTMLDivElement>(null);
  const dot = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const d = disc.current;
    const n = tint.current;
    const y = dot.current;
    const hero = document.querySelector<HTMLElement>("[data-hero]");
    const logo = document.querySelector<SVGElement>(`.${s.brand} svg`);
    if (!d || !n || !y || !hero || !logo) return;
    if (reducedMotion() || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;

    const target = { x: 0, y: 0 };
    const pos = { x: 0, y: 0 };
    const st = { on: false, vis: 0, hover: 1, p: 0 };

    // 0 while the hero fills the screen, 1 once it has mostly scrolled away.
    const trigger = ScrollTrigger.create({
      trigger: hero,
      start: "top top",
      end: "75% top",
      onUpdate: (self) => (st.p = self.progress),
    });
    st.p = trigger.progress;

    const tick = () => {
      if (!st.on) return;
      pos.x += (target.x - pos.x) * 0.16;
      pos.y += (target.y - pos.y) * 0.16;

      const R = d.offsetWidth / 2 || 1;
      const hb = hero.getBoundingClientRect();
      const reach = bell((pos.y - hb.top) / (hb.height || 1));
      const lb = logo.getBoundingClientRect();
      const home = { x: lb.left + DOT.x * lb.width, y: lb.top + DOT.y * lb.height, r: DOT.r * lb.height };

      // Ease the flight so it leaves the pointer slowly and lands softly.
      const t = gsap.parseEase("power2.inOut")(st.p);
      const x = pos.x + (home.x - pos.x) * t;
      const yy = pos.y + (home.y - pos.y) * t;
      const scale = (1 + (home.r / R - 1) * t) * (1 + (st.hover * reach - 1) * (1 - t));
      const transform = `translate3d(${x}px, ${yy}px, 0) scale(${scale})`;

      const docked = st.p >= 0.999;
      d.style.transform = transform;
      n.style.transform = transform;
      y.style.transform = transform;
      d.style.opacity = String(st.vis * (1 - ramp(0.55, 0.85, st.p)) * (docked ? 0 : 1));
      n.style.opacity = d.style.opacity;
      y.style.opacity = String(st.vis * ramp(0.5, 0.8, st.p) * (docked ? 0 : 1));
    };
    gsap.ticker.add(tick);

    const show = (to: number, duration = 0.5) => gsap.to(st, { vis: to, duration, overwrite: "auto" });
    const switchOn = (e: PointerEvent) => {
      st.on = true;
      pos.x = target.x = e.clientX;
      pos.y = target.y = e.clientY;
      // A torch catching: two quick blips, then steady.
      gsap
        .timeline()
        .to(st, { vis: 0.55, duration: 0.08 })
        .to(st, { vis: 0.15, duration: 0.07 })
        .to(st, { vis: 0.85, duration: 0.09 })
        .to(st, { vis: 0.5, duration: 0.06 })
        .to(st, { vis: 1, duration: 0.5, ease: "power2.out" });
    };
    const move = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      target.x = e.clientX;
      target.y = e.clientY;
      if (!st.on) switchOn(e);
      else if (st.vis < 1) show(1);
    };
    const away = () => st.on && show(0, 0.6);
    // Over anything that can be pressed the disc shrinks away, so buttons and
    // links show their own colours and hover states, never an inverted copy.
    const over = (e: PointerEvent) => {
      const hot = (e.target as Element | null)?.closest("a, button");
      gsap.to(st, { hover: hot ? 0 : 1, duration: hot ? 0.35 : 0.6, ease: "power3.out", overwrite: "auto" });
    };

    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerover", over, { passive: true });
    document.documentElement.addEventListener("pointerleave", away);
    window.addEventListener("blur", away);
    window.addEventListener("keydown", away);
    return () => {
      gsap.ticker.remove(tick);
      trigger.kill();
      gsap.killTweensOf(st);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerover", over);
      document.documentElement.removeEventListener("pointerleave", away);
      window.removeEventListener("blur", away);
      window.removeEventListener("keydown", away);
    };
  }, []);

  return (
    <>
      <div className={`${s.torch} ${s.torchInvert}`} aria-hidden="true">
        <div ref={disc} className={s.torchDisc} />
      </div>
      <div className={`${s.torch} ${s.torchTint}`} aria-hidden="true">
        <div ref={tint} className={s.torchDisc} />
      </div>
      <div className={s.torch} aria-hidden="true">
        <div ref={dot} className={`${s.torchDisc} ${s.torchDot}`} />
      </div>
    </>
  );
}
