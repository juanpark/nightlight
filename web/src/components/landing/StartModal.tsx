"use client";
// The start screen as a dialog over the landing page: the same choices as the plain start screen (StartChoices, so the
// wording and logic live in one place), in the landing page's type and colours. Escape or the close button returns to
// the landing page. While it is open the page behind it is inert, so Tab and screen readers stay in the dialog.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { StartChoices } from "@/components/SignIn";
import { Logo } from "../brand/Logo";
import { Close } from "../icons";
import { display, sans } from "./fonts";
import { holdSmoothScroll } from "./motion/smooth";
import s from "./StartModal.module.css";

const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), select, textarea, summary, [tabindex]:not([tabindex="-1"])';

export function StartModal({ onClose }: { onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  const scrim = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(false); // the page's animated sections transform their children: render at body
  useEffect(() => setMounted(true), []);
  const closeRef = useRef(onClose); // the parent passes a new function each render; the dialog shouldn't re-open for it
  closeRef.current = onClose;
  useEffect(() => {
    if (!mounted) return;
    const before = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const keys = (e: KeyboardEvent) => {
      if (e.key === "Escape") return closeRef.current();
      if (e.key !== "Tab" || !scrim.current) return;
      // inert covers the page; this keeps Tab cycling inside the dialog rather than out to the browser's own UI
      const all = Array.from(scrim.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null);
      if (!all.length) return;
      const first = all[0], last = all[all.length - 1];
      const at = document.activeElement;
      if (e.shiftKey && (at === first || !scrim.current.contains(at))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (at === last || !scrim.current.contains(at))) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", keys);
    // everything else at the body's top level goes inert (and leaves it as it found it)
    const others = Array.from(document.body.children).filter((el): el is HTMLElement => el instanceof HTMLElement && el !== scrim.current && !el.inert);
    others.forEach((el) => (el.inert = true));
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden"; // the landing page stays put underneath
    holdSmoothScroll(true); // and its smooth scrolling lets the dialog have the wheel
    return () => {
      document.removeEventListener("keydown", keys); document.body.style.overflow = overflow; holdSmoothScroll(false);
      others.forEach((el) => (el.inert = false));
      before?.focus?.();
    };
  }, [mounted]);
  if (!mounted) return null;
  return createPortal(
    <div ref={scrim} className={`${s.scrim} ${display.variable} ${sans.variable}`} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal start ${s.dialog}`} role="dialog" aria-modal="true" aria-labelledby="start-title">
        {/* the content scrolls inside a still frame, so Close stays in reach on a long dialog */}
        <button ref={close} type="button" className={s.close} onClick={onClose} aria-label="Close">
          <Close size={18} aria-hidden />
        </button>
        <div className={s.scroll} data-lenis-prevent>
          <Logo height={22} className={s.logo} />
          <StartChoices title="How do you want to start?" />
        </div>
      </div>
    </div>,
    document.body,
  );
}
