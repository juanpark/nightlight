"use client";

import { useEffect, useRef, type RefObject } from "react";
import gsap from "gsap";
import s from "./Mono.module.css";

// The page's pointer: a small star-yellow light with a thin gold edge and a soft glow. Over anything you can click it
// grows a little and glows warmer; it has no blend mode, so a button always looks exactly like itself. Text fields get
// the system caret back. A big soft halo trails it behind the content, lighting the ground but never a control. Only for a mouse or trackpad with motion allowed; everyone else keeps the system cursor.
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
    const hx = gsap.quickTo(h, "x", { duration: 0.6, ease: "power3.out" });
    const hy = gsap.quickTo(h, "y", { duration: 0.6, ease: "power3.out" });

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
