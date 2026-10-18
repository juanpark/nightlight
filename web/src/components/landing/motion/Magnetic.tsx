"use client";

import { useEffect, useRef, type ReactNode } from "react";
import gsap from "gsap";
import { reducedMotion } from "./smooth";

// Leans its child toward the pointer while the pointer is near, then springs
// back. The inner layer moves further than the outer one, so a button's label
// trails its body a little.
export function Magnetic({
  children,
  strength = 0.35,
  className,
}: {
  children: ReactNode;
  strength?: number;
  className?: string;
}) {
  const outer = useRef<HTMLSpanElement>(null);
  const inner = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = outer.current;
    const kid = inner.current;
    if (!el || !kid || reducedMotion() || !window.matchMedia("(hover: hover)").matches) return;
    const ox = gsap.quickTo(el, "x", { duration: 0.6, ease: "power3.out" });
    const oy = gsap.quickTo(el, "y", { duration: 0.6, ease: "power3.out" });
    const ix = gsap.quickTo(kid, "x", { duration: 0.6, ease: "power3.out" });
    const iy = gsap.quickTo(kid, "y", { duration: 0.6, ease: "power3.out" });

    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2);
      const dy = e.clientY - (r.top + r.height / 2);
      ox(dx * strength);
      oy(dy * strength);
      ix(dx * strength * 0.35);
      iy(dy * strength * 0.35);
    };
    const leave = () => {
      gsap.to([el, kid], { x: 0, y: 0, duration: 0.9, ease: "elastic.out(1, 0.4)", overwrite: true });
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", leave);
    };
  }, [strength]);

  return (
    <span ref={outer} className={className} style={{ display: "inline-block" }}>
      <span ref={inner} style={{ display: "inline-block" }}>
        {children}
      </span>
    </span>
  );
}
