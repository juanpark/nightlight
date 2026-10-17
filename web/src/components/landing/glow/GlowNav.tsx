"use client";

import { useEffect, useRef, useState } from "react";
import { Logo } from "../../brand/Logo";
import { AuthButtons } from "../AuthButtons";
import s from "./Glow.module.css";

// The glow page's nav: one glass capsule floating over the scene. The links
// mark the section on screen with a small warm light that slides between
// them, and a thin glowing line along the capsule's lower edge fills as the
// night goes on. On narrower screens the links fold into a menu; "Try the
// demo" stays in the bar on every screen.

export type NavLink = { href: string; label: string };

export function GlowNav({ links, menuLinks }: { links: NavLink[]; menuLinks: NavLink[] }) {
  const [active, setActive] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [dot, setDot] = useState(0);
  const row = useRef<HTMLElement>(null);
  const line = useRef<HTMLSpanElement>(null);
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

  // The light slides to the active link.
  useEffect(() => {
    const a = row.current?.querySelector<HTMLAnchorElement>(`a[href="#${active}"]`);
    if (a) setDot(a.offsetLeft + a.offsetWidth / 2);
  }, [active]);

  // How far through the page, drawn as the line along the bar. The page's height is
  // kept and refreshed only when something resizes, so scrolling never measures layout.
  useEffect(() => {
    let raf = 0;
    let max = 1;
    const measure = () => {
      max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      onScroll();
    };
    const paint = () => {
      raf = 0;
      if (line.current) line.current.style.transform = `scaleX(${Math.min(1, window.scrollY / max)})`;
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(paint);
    };
    // The page's root grows with its content (body is pinned to the viewport's height
    // by globals.css, so it never resizes).
    const sized = new ResizeObserver(measure);
    sized.observe(line.current?.closest<HTMLElement>("[data-landing]") ?? document.documentElement);
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", measure);
    return () => {
      cancelAnimationFrame(raf);
      sized.disconnect();
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", measure);
    };
  }, []);

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
        <nav
          ref={row}
          className={s.links}
          aria-label="Sections"
          data-dot={active && links.some((l) => l.href === `#${active}`) ? "on" : undefined}
          style={{ "--dot-x": `${dot}px` } as React.CSSProperties}
        >
          {links.map((l) => (
            <a key={l.href} href={l.href} aria-current={active === l.href.slice(1) ? "location" : undefined}>
              {l.label}
            </a>
          ))}
          <span className={s.navDot} aria-hidden="true" />
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
        <span ref={line} className={s.navLine} aria-hidden="true" />
      </div>
      <nav id="glow-menu" className={s.menu} aria-label="Sections" inert={!open}>
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
    </header>
  );
}
