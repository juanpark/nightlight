"use client";

import { useEffect, useRef } from "react";
import gsap from "gsap";
import { AuthButtons } from "../AuthButtons";
import { Roll } from "../motion/Roll";
import { reducedMotion, scrollToTarget, stopScroll } from "../motion/smooth";
import s from "./Home.module.css";

export const LINKS = [
  { href: "#loop", label: "How a night goes" },
  { href: "#watch", label: "What it looks after" },
  { href: "#who", label: "Who it’s for" },
  { href: "#privacy", label: "Privacy" },
];

// Full-screen menu. The panel wipes down from the top, then the links rise in
// one after another. Escape or any link closes it.
export function Menu({ open, onClose }: { open: boolean; onClose: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const first = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    stopScroll(open);
    const quick = reducedMotion();
    const items = el.querySelectorAll("[data-menu-item]");
    gsap.killTweensOf([el, items]);
    if (open) {
      gsap.set(el, { visibility: "visible" });
      gsap.fromTo(
        el,
        { clipPath: "inset(0% 0% 100% 0%)" },
        { clipPath: "inset(0% 0% 0% 0%)", duration: quick ? 0 : 0.9, ease: "expo.inOut" },
      );
      gsap.fromTo(
        items,
        { yPercent: 110 },
        { yPercent: 0, duration: quick ? 0 : 1, ease: "expo.out", stagger: 0.06, delay: quick ? 0 : 0.35 },
      );
      first.current?.focus({ preventScroll: true });
      const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
      window.addEventListener("keydown", key);
      return () => window.removeEventListener("keydown", key);
    }
    gsap.to(el, {
      clipPath: "inset(0% 0% 100% 0%)",
      duration: quick ? 0 : 0.7,
      ease: "expo.inOut",
      onComplete: () => gsap.set(el, { visibility: "hidden" }),
    });
  }, [open, onClose]);

  return (
    <div ref={root} id="menu" className={s.menu} role="dialog" aria-modal="true" aria-label="Menu" hidden={false}>
      <nav aria-label="Sections" className={s.menuLinks}>
        {LINKS.map((l, i) => (
          <span key={l.href} className={s.menuMask}>
            <a
              ref={i === 0 ? first : undefined}
              data-menu-item
              href={l.href}
              tabIndex={open ? 0 : -1}
              onClick={(e) => {
                e.preventDefault();
                onClose();
                window.setTimeout(() => scrollToTarget(l.href), 350);
              }}
            >
              <Roll text={l.label} />
            </a>
          </span>
        ))}
      </nav>
      <div className={s.menuFoot}>
        <span className={s.menuMask}>
          <span data-menu-item className={s.menuNote}>
            Free to try. The demo is a simulated sample home; nothing of yours is touched.
          </span>
        </span>
        <span className={s.menuMask}>
          <span data-menu-item>{open && <AuthButtons styles={s} magnetic />}</span>
        </span>
      </div>
    </div>
  );
}
