"use client";

import { useEffect } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";

gsap.registerPlugin(ScrollTrigger);

// One Lenis for the whole landing page, driven by GSAP's ticker so smooth
// scrolling and ScrollTrigger never disagree about where the page is.
let lenis: Lenis | null = null;

export function reducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useSmoothScroll() {
  useEffect(() => {
    if (reducedMotion()) return;
    const l = new Lenis({ lerp: 0.09, wheelMultiplier: 0.95 });
    lenis = l;
    l.on("scroll", ScrollTrigger.update);
    const tick = (t: number) => l.raf(t * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    return () => {
      gsap.ticker.remove(tick);
      l.destroy();
      if (lenis === l) lenis = null;
    };
  }, []);
}

// Scrolls to an element, a selector or a y offset; jumps under reduced motion.
export function scrollToTarget(target: string | HTMLElement | number) {
  if (lenis) {
    lenis.scrollTo(target, { duration: 1.6, easing: (t) => 1 - Math.pow(1 - t, 4) });
    return;
  }
  if (typeof target === "number") window.scrollTo({ top: target });
  else (typeof target === "string" ? document.querySelector(target) : target)?.scrollIntoView();
}
