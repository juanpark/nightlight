"use client";

import { useEffect, useState } from "react";
import { Logo } from "../brand/Logo";
import { AuthButtons } from "./AuthButtons";
import s from "./Landing.module.css";

// Stays on top the whole way down, so Try the demo is always one click away.
export function NavBar() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 24);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  return (
    <header className={s.nav} data-scrolled={scrolled}>
      <a href="#top" className={s.brand} aria-label="Nightlight, back to top">
        <Logo height={24} />
      </a>
      <nav className={s.links} aria-label="Sections">
        <a href="#how">How it works</a>
        <a href="#home">Sample home</a>
        <a href="#privacy">Privacy</a>
      </nav>
      <AuthButtons size="small" />
    </header>
  );
}
