"use client";

import { useEffect, useRef, type RefObject } from "react";
import gsap from "gsap";
import s from "./Mono.module.css";

// The page's pointer: a small ink dot that sits exactly on the pointer, and a hairline ring that trails it and stretches
// along the way it moves. Over anything you can click the ring opens around it (it never fills or recolours the
// control); over a text field the dot becomes a caret; a press tightens the ring. The star light lives only inside the
// product frames, where the ring's position lights the dot grid. Only for a mouse or trackpad with motion allowed;
// everyone else keeps the system cursor.
const CONTROL = "a, button, select, label, summary, [role='button']";
const FIELD = "input, textarea, [contenteditable='true']";

export function Cursor({ scope }: { scope: RefObject<HTMLElement | null> }) {
  const dot = useRef<HTMLDivElement>(null);
  const ring = useRef<HTMLDivElement>(null);
  const stretch = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const page = scope.current;
    const d = dot.current;
    const r = ring.current;
    const st = stretch.current;
    if (!page || !d || !r || !st) return;
    const mq = window.matchMedia("(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)");
    if (!mq.matches) return;

    page.dataset.cursor = "on";
    const dx = gsap.quickTo(d, "x", { duration: 0.06, ease: "power3.out" });
    const dy = gsap.quickTo(d, "y", { duration: 0.06, ease: "power3.out" });
    const rx = gsap.quickTo(r, "x", { duration: 0.32, ease: "power3.out" });
    const ry = gsap.quickTo(r, "y", { duration: 0.32, ease: "power3.out" });

    // each tick: the ring leans into its own speed, and each frame's light follows it. All measuring happens before any
    // writing, and nothing runs when neither the ring nor the page has moved.
    const frames = Array.from(page.querySelectorAll<HTMLElement>(`.${s.frame}`));
    let px = 0, py = 0, last = "";
    const tick = () => {
      const x = gsap.getProperty(r, "x") as number;
      const y = gsap.getProperty(r, "y") as number;
      const vx = x - px, vy = y - py;
      px = x; py = y;
      const speed = Math.hypot(vx, vy);
      const k = Math.min(speed / 60, 0.3);
      gsap.set(st, { rotation: speed > 0.5 ? (Math.atan2(vy, vx) * 180) / Math.PI : "+=0", scaleX: 1 + k, scaleY: 1 - k * 0.6 });

      const now = `${x}|${y}|${window.scrollY}`;
      if (now === last) return;
      last = now;
      const rects = frames.map((f) => f.getBoundingClientRect());
      frames.forEach((f, i) => {
        const b = rects[i];
        if (y < b.top - 320 || y > b.bottom + 320) return;
        f.style.setProperty("--lx", `${x - b.left}px`);
        f.style.setProperty("--ly", `${y - b.top}px`);
      });
    };
    gsap.ticker.add(tick);

    let shown = false;
    const move = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      if (!shown) {
        // first move: start where the pointer is rather than sliding in from the corner
        gsap.set([d, r], { x: e.clientX, y: e.clientY });
        px = e.clientX; py = e.clientY;
        shown = true;
      }
      dx(e.clientX);
      dy(e.clientY);
      rx(e.clientX);
      ry(e.clientY);
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
      gsap.ticker.remove(tick);
      for (const f of frames) f.style.removeProperty("--lx"), f.style.removeProperty("--ly");
      delete page.dataset.cursor;
      delete page.dataset.cursorOver;
      delete page.dataset.cursorDown;
    };
  }, [scope]);

  return (
    <>
      <div ref={ring} className={s.cursorRing} aria-hidden="true">
        <div ref={stretch} className={s.cursorStretch}>
          <span />
        </div>
      </div>
      <div ref={dot} className={s.cursorDot} aria-hidden="true" />
    </>
  );
}
