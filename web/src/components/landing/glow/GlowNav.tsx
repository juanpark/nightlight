"use client";

import { useEffect, useRef, useState } from "react";
import { Logo } from "../../brand/Logo";
import { AuthButtons } from "../AuthButtons";
import s from "./Glow.module.css";

// The glow page's nav: one glass capsule floating over the scene. The link
// for the section on screen turns star yellow. On narrower screens the links
// fold into a menu, with "Sign in with Google" at its foot; "Try the demo"
// stays in the bar on every screen.

export type NavLink = { href: string; label: string };

export function GlowNav({ links, menuLinks }: { links: NavLink[]; menuLinks: NavLink[] }) {
  const [active, setActive] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);

  // The section crossing the middle of the screen is the one we're in.
  useEffect(() => {
    const ids = menuLinks.map((l) => l.href.slice(1));
    const seen = new Map<string, boolean>();
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => seen.set(e.target.id, e.isIntersecting));
        setActive(ids.find((id) => seen.get(id)) ?? null);
      },
      { rootMargin: "-50% 0px -50% 0px" },
    );
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (el) io.observe(el);
    });
    return () => io.disconnect();
  }, [menuLinks]);

  // The menu closes on Escape (focus goes back to its button) and when the screen widens.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    const wide = window.matchMedia("(min-width: 1101px)");
    const onWide = () => wide.matches && setOpen(false);
    window.addEventListener("keydown", onKey);
    wide.addEventListener("change", onWide);
    return () => {
      window.removeEventListener("keydown", onKey);
      wide.removeEventListener("change", onWide);
    };
  }, [open]);

  return (
    <header className={s.nav} data-open={open || undefined}>
      <div className={s.bar}>
        <a href="#glow-main" className={s.brand} aria-label="Nightlight, back to top">
          <Logo height={22} />
        </a>
        <nav className={s.links} aria-label="Sections">
          {links.map((l) => (
            <a key={l.href} href={l.href} aria-current={active === l.href.slice(1) ? "location" : undefined}>
              {l.label}
            </a>
          ))}
        </nav>
        <div className={s.navActions}>
          <AuthButtons size="small" styles={s} />
        </div>
        <button
          ref={button}
          type="button"
          className={s.menuButton}
          aria-expanded={open}
          aria-controls="glow-menu"
          aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen((o) => !o)}
        >
          <span className={s.menuIcon} aria-hidden="true">
            <span />
            <span />
          </span>
        </button>
      </div>
      <div id="glow-menu" className={s.menu} inert={!open}>
        <nav aria-label="Sections">
          {menuLinks.map((l) => (
            <a
              key={l.href}
              href={l.href}
              aria-current={active === l.href.slice(1) ? "location" : undefined}
              onClick={() => setOpen(false)}
            >
              {l.label}
            </a>
          ))}
        </nav>
        {/* "Try the demo" stays in the bar; the menu carries the other way in. */}
        <div className={s.menuActions}>
          <AuthButtons googleOnly styles={s} />
        </div>
      </div>
    </header>
  );
}
