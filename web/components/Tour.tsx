"use client";
// Runs the tours in lib/tour.ts with driver.js: the first visit's tour once the home has loaded, then a short one when
// the first real device arrives and one when the first approval card appears. Keyboard: arrows move, Esc closes.
import { useEffect, useRef } from "react";
import { driver, type DriveStep } from "driver.js";
import "driver.js/dist/driver.css";
import { markSeen, seen, TOURS, type TourId, type TourState } from "@/lib/tour";

/** The element a step points at, if it is on screen (a phone hides the menu and the other pane). */
function anchor(name?: string): Element | undefined {
  if (!name) return undefined;
  const el = document.querySelector(`[data-tour="${name}"]`);
  return el && el.getClientRects().length > 0 && !el.closest("[inert]") ? el : undefined;
}

export default function Tour({ uid, state, ready }: { uid: string; state: TourState; ready: boolean }) {
  const running = useRef(false);
  const st = useRef(state);
  st.current = state;

  function run(t: TourId) {
    if (running.current) return;
    const steps: DriveStep[] = TOURS[t].filter((s) => !s.when || s.when(st.current)).map((s) => {
      const el = anchor(s.anchor);
      return { ...(el ? { element: el } : {}), popover: { title: s.title, description: s.text } };
    });
    if (!steps.length) return;
    running.current = true;
    // what this tour already covers needs no tour of its own later
    markSeen(uid, t);
    if (t === "intro" && st.current.realDevices > 0) markSeen(uid, "firstDevice");
    if (t === "intro" && st.current.hasCard) markSeen(uid, "firstCard");
    const still = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    const d = driver({
      steps, animate: !still, smoothScroll: !still, showProgress: steps.length > 1, allowKeyboardControl: true,
      popoverClass: "nl-tour", overlayOpacity: 0.45, stagePadding: 6, stageRadius: 12,
      nextBtnText: "Next", prevBtnText: "Back", doneBtnText: "Done", progressText: "{{current}} of {{total}}",
      onPopoverRender: (p) => {
        p.wrapper.setAttribute("role", "dialog");
        p.wrapper.setAttribute("aria-label", p.title.textContent ?? "Tour");
        requestAnimationFrame(() => p.nextButton.focus());
      },
      onDestroyed: () => { running.current = false; },
    });
    d.drive();
  }

  // the next tour that applies, a moment after things settle (never over a half-loaded screen)
  useEffect(() => {
    if (!ready || running.current) return;
    const next: TourId | null = !seen(uid, "intro") ? "intro"
      : state.realDevices > 0 && !seen(uid, "firstDevice") ? "firstDevice"
        : state.hasCard && !seen(uid, "firstCard") && anchor("card") ? "firstCard" : null;
    if (!next) return;
    const t = setTimeout(() => run(next), 1500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid, ready, state.realDevices, state.hasCard, state.anonymous]);

  // Settings: "Show the tour again"
  useEffect(() => {
    const again = () => run("intro");
    window.addEventListener("nl-tour", again);
    return () => window.removeEventListener("nl-tour", again);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid]);
  return null;
}
