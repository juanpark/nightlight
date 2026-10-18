"use client";
// The start screen as a dialog over the landing page: the same choices as the plain start screen (StartChoices, so the
// wording and logic live in one place), in the landing page's type and colours. Escape or the close button returns to
// the landing page.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { StartChoices } from "@/components/SignIn";
import { display, sans } from "./fonts";
import { holdSmoothScroll } from "./motion/smooth";
import s from "./StartModal.module.css";

export function StartModal({ onClose }: { onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  const [mounted, setMounted] = useState(false); // the page's animated sections transform their children: render at body
  useEffect(() => setMounted(true), []);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden"; // the landing page stays put underneath
    holdSmoothScroll(true); // and its smooth scrolling lets the dialog have the wheel
    return () => {
      document.removeEventListener("keydown", esc); document.body.style.overflow = overflow; holdSmoothScroll(false);
      before?.focus?.();
    };
  }, [onClose, mounted]);
  if (!mounted) return null;
  return createPortal(
    <div className={`${s.scrim} ${display.variable} ${sans.variable}`} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal start ${s.dialog}`} role="dialog" aria-modal="true" aria-labelledby="start-title" data-lenis-prevent>
        <button ref={close} type="button" className={s.close} onClick={onClose} aria-label="Close">×</button>
        <StartChoices />
      </div>
    </div>,
    document.body,
  );
}
