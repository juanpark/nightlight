"use client";

import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";

gsap.registerPlugin(ScrollTrigger, SplitText);

// Shared entrances. Content is always in the HTML and visible without script;
// these only run when motion is allowed (call them inside gsap.matchMedia).

const EASE = "expo.out";

// Lines rise out of a mask, one after another, when the element enters.
export function revealLines(el: Element, opts: { delay?: number; start?: string; scrub?: boolean } = {}) {
  return SplitText.create(el, {
    type: "lines",
    mask: "lines",
    linesClass: "nl-line",
    autoSplit: true,
    onSplit(self) {
      return gsap.from(self.lines, {
        yPercent: 110,
        rotate: 2.5,
        transformOrigin: "0% 100%",
        duration: 1.25,
        ease: EASE,
        stagger: 0.09,
        delay: opts.delay ?? 0,
        scrollTrigger: opts.start === "now" ? undefined : { trigger: el, start: opts.start ?? "top 86%", once: true },
      });
    },
  });
}

// Letters rise one by one (for short, large words like the footer wordmark).
export function revealChars(el: Element, opts: { start?: string; stagger?: number } = {}) {
  return SplitText.create(el, {
    type: "chars",
    mask: "chars",
    autoSplit: true,
    onSplit(self) {
      return gsap.from(self.chars, {
        yPercent: 120,
        duration: 1.1,
        ease: EASE,
        stagger: opts.stagger ?? 0.035,
        scrollTrigger: { trigger: el, start: opts.start ?? "top 90%", once: true },
      });
    },
  });
}

// The parts of a block arrive in order: heading, text, then the rest.
export function riseIn(targets: gsap.TweenTarget, trigger: Element, delay = 0) {
  return gsap.from(targets, {
    y: 28,
    autoAlpha: 0,
    duration: 1,
    ease: "power3.out",
    stagger: 0.075,
    delay,
    scrollTrigger: { trigger, start: "top 84%", once: true },
  });
}
