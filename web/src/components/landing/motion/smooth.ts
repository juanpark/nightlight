"use client";

import { useEffect } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";

gsap.registerPlugin(ScrollTrigger);
// a phone's address bar showing and hiding changes the viewport height; don't recompute every trigger for it
ScrollTrigger.config({ ignoreMobileResize: true });

// One Lenis for the whole landing page, driven by GSAP's ticker so smooth
// scrolling and ScrollTrigger never disagree about where the page is.
let lenis: Lenis | null = null;

export function reducedMotion() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useSmoothScroll() {
  useEffect(() => {
    if (reducedMotion()) return;
    // a softer glide for wheels and trackpads; touch keeps the device's own native scrolling, which is the smoothest there
    const l = new Lenis({ lerp: 0.075, wheelMultiplier: 1, smoothWheel: true, syncTouch: false });
    lenis = l;
    l.on("scroll", ScrollTrigger.update);
    const tick = (t: number) => l.raf(t * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    // html and body are fixed at 100% height, so Lenis never sees the page grow (fonts arriving, the live-machine box
    // appearing, a list opening) and would stop short of the footer. Watch the page's own content and re-measure.
    let frame = 0;
    const remeasure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        l.resize();
        ScrollTrigger.refresh();
      });
    };
    const ro = new ResizeObserver(remeasure);
    // a wrapper with display: contents (AppGate's) has no box to watch, so watch what is inside it
    const watch = (el: Element) =>
      getComputedStyle(el).display === "contents" ? Array.from(el.children).forEach(watch) : ro.observe(el);
    Array.from(document.body.children).forEach(watch);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(frame);
      gsap.ticker.remove(tick);
      l.destroy();
      if (lenis === l) lenis = null;
    };
  }, []);
}

/** Pause the page's smooth scrolling while a dialog is open (it would otherwise take the wheel), and resume after. */
export function holdSmoothScroll(held: boolean) {
  if (!lenis) return;
  if (held) lenis.stop(); else lenis.start();
}

// Scrolls to an element, a selector or a y offset; jumps under reduced motion.
export function scrollToTarget(target: string | HTMLElement | number) {
  if (lenis) {
    // anchors land below the sticky header rather than under it
    lenis.scrollTo(target, { duration: 1.4, offset: typeof target === "number" ? 0 : -80, easing: (t) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t)) });
    return;
  }
  if (typeof target === "number") window.scrollTo({ top: target });
  else (typeof target === "string" ? document.querySelector(target) : target)?.scrollIntoView();
}
