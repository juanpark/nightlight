"use client";

import { useEffect, useRef, type RefObject } from "react";
import gsap from "gsap";
import s from "./Mono.module.css";

// The page's pointer: a small star-yellow light with a thin gold edge and a soft glow. Over anything you can click it
// grows a little and glows warmer; it has no blend mode, so a button always looks exactly like itself. Text fields get
// the system caret back. A big soft light follows it under the content: it warms the ground and, inside each product
// frame, lights the dot grid near it, so it reads as one light across the page and never sits on a card or a control. Only for a mouse or trackpad with motion allowed; everyone else keeps the system cursor.
const CONTROL = "a, button, select, label, summary, [role='button']";
const FIELD = "input, textarea, [contenteditable='true']";

export function Cursor({ scope }: { scope: RefObject<HTMLElement | null> }) {
  const dot = useRef<HTMLDivElement>(null);
  const halo = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const page = scope.current;
    const d = dot.current;
    const h = halo.current;
    if (!page || !d || !h) return;
    const mq = window.matchMedia("(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)");
    if (!mq.matches) return;

    page.dataset.cursor = "on";
    gsap.set([d, h], { xPercent: -50, yPercent: -50 });
    const dx = gsap.quickTo(d, "x", { duration: 0.12, ease: "power3.out" });
    const dy = gsap.quickTo(d, "y", { duration: 0.12, ease: "power3.out" });
    const hx = gsap.quickTo(h, "x", { duration: 0.3, ease: "power3.out" });
    const hy = gsap.quickTo(h, "y", { duration: 0.3, ease: "power3.out" });

    // each frame paints the light on its own dot grid, so it needs the light's position in its own coordinates. Only
    // when the light or the page has moved, and all the measuring before any writing, so a frame costs one layout.
    const frames = Array.from(page.querySelectorAll<HTMLElement>(`.${s.frame}`));
    let last = "";
    const shine = () => {
      const x = gsap.getProperty(h, "x") as number;
      const y = gsap.getProperty(h, "y") as number;
      const now = `${x}|${y}|${window.scrollY}`;
      if (now === last) return;
      last = now;
      const rects = frames.map((f) => f.getBoundingClientRect());
      frames.forEach((f, i) => {
        const r = rects[i];
        if (y < r.top - 320 || y > r.bottom + 320) return;
        f.style.setProperty("--lx", `${x - r.left}px`);
        f.style.setProperty("--ly", `${y - r.top}px`);
      });
    };
    gsap.ticker.add(shine);

    let shown = false;
    const move = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      if (!shown) {
        // first move: start where the pointer is rather than sliding in from the corner
        gsap.set([d, h], { x: e.clientX, y: e.clientY });
        shown = true;
      }
      dx(e.clientX);
      dy(e.clientY);
      hx(e.clientX);
      hy(e.clientY);
      const t = e.target as Element | null;
      page.dataset.cursorOver = t?.closest(FIELD) ? "field" : t?.closest(CONTROL) ? "control" : "page";
    };
    const leave = () => (page.dataset.cursorOver = "away");
    const down = () => (page.dataset.cursorDown = "true");
    const up = () => delete page.dataset.cursorDown;

    window.addEventListener("pointermove", move, { passive: true });
    document.documentElement.addEventListener("pointerleave", leave);
    window.addEventListener("pointerdown", down);
    window.addEventListener("pointerup", up);
    window.addEventListener("blur", leave);
    return () => {
      window.removeEventListener("pointermove", move);
      document.documentElement.removeEventListener("pointerleave", leave);
      window.removeEventListener("pointerdown", down);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("blur", leave);
      gsap.ticker.remove(shine);
      for (const f of frames) f.style.removeProperty("--lx"), f.style.removeProperty("--ly");
      delete page.dataset.cursor;
      delete page.dataset.cursorOver;
      delete page.dataset.cursorDown;
    };
  }, [scope]);

  return (
    <>
      <div ref={halo} className={s.cursorHalo} aria-hidden="true" />
      <div ref={dot} className={s.cursorDot} aria-hidden="true" />
    </>
  );
}
