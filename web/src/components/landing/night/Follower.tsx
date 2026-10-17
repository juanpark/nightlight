"use client";

import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import gsap from "gsap";

// Something that drifts after the pointer inside an area: it lags behind,
// leans into the direction it's moving and settles upright when it stops.
// With no pointer (touch, or before the first move) it wanders a slow loop.
export function Follower({
  area,
  children,
  className,
  home = [0.72, 0.3],
}: {
  area: RefObject<HTMLElement | null>;
  children: ReactNode;
  className?: string;
  home?: [number, number]; // resting point, as a fraction of the area
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [homeX, homeY] = home;

  useEffect(() => {
    const el = ref.current;
    const box = area.current;
    if (!el || !box) return;
    const [hx, hy] = [homeX, homeY];
    // Never let it hang off the edge of the area.
    const fitX = (x: number, r: DOMRect) => gsap.utils.clamp(8, r.width - el.offsetWidth - 8, x);
    const place = () => {
      const r = box.getBoundingClientRect();
      gsap.set(el, { x: fitX(r.width * hx, r), y: r.height * hy });
    };
    place();
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      window.addEventListener("resize", place);
      return () => window.removeEventListener("resize", place);
    }

    const tx = gsap.quickTo(el, "x", { duration: 1.4, ease: "power3.out" });
    const ty = gsap.quickTo(el, "y", { duration: 1.4, ease: "power3.out" });
    const tr = gsap.quickTo(el, "rotation", { duration: 0.9, ease: "power2.out" });
    let lastX = 0;
    let pointer = false;
    let wander = 0;

    const move = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      const r = box.getBoundingClientRect();
      const x = e.clientX - r.left;
      const y = e.clientY - r.top;
      if (y < 0 || y > r.height) return;
      pointer = true;
      // Trail a little below and to the right of the cursor, never under it.
      tx(fitX(x + 36, r));
      ty(y + 24);
      tr(gsap.utils.clamp(-16, 16, (x - lastX) * 0.6));
      lastX = x;
      window.clearTimeout(wander);
      wander = window.setTimeout(() => tr(0), 140);
    };

    // The slow loop for when nobody is pointing.
    const loop = gsap.ticker.add((time) => {
      if (pointer) return;
      const r = box.getBoundingClientRect();
      tx(fitX(r.width * hx + Math.sin(time * 0.35) * r.width * 0.05, r));
      ty(r.height * hy + Math.sin(time * 0.7) * r.height * 0.04);
      tr(Math.cos(time * 0.35) * 6);
    });

    window.addEventListener("pointermove", move, { passive: true });
    return () => {
      window.removeEventListener("pointermove", move);
      gsap.ticker.remove(loop);
      window.clearTimeout(wander);
    };
  }, [area, homeX, homeY]);

  return (
    <div ref={ref} className={className} style={{ position: "absolute", left: 0, top: 0, willChange: "transform" }} aria-hidden="true">
      {children}
    </div>
  );
}
