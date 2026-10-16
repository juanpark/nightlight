import { Logo } from "../../brand/Logo";
import { AuthButtons } from "../AuthButtons";
import { display, sans } from "../fonts";
import { DayScene } from "./DayScene";
import { DayMotion } from "./DayMotion";
import s from "./Day.module.css";

// The lit-room variant of the landing hero: a warm plaster room at night,
// with a camera that follows the pointer and an opening played with GSAP. Quiet small type on a sculpted
// scene; the same copy and actions as the night hero.
export function DayHero() {
  return (
    <div
      className={`${s.page} ${display.variable} ${sans.variable}`}
      data-landing
    >
      <a href="#day-main" className={s.skip}>
        Skip to content
      </a>
      <div className={s.frame}>
        <header className={s.nav}>
          <a href="/" className={s.brand} aria-label="Nightlight, home">
            <Logo height={22} />
          </a>
          <p className={s.tagline}>Looks after the machines you run at home</p>
          <nav className={s.links} aria-label="Sections">
            <a href="/#how">How it works</a>
            <a href="/#home">Sample home</a>
            <a href="/#privacy">Privacy</a>
          </nav>
          <AuthButtons size="small" demoOnly styles={s} />
        </header>

        <DayMotion id="day-main" className={s.hero}>
          <DayScene />
          <div className={s.copy}>
            <h1 className={s.h1}>
              A house‑sitter for the machines you run at home.
            </h1>
            <p className={s.lede}>
              Nightlight puts every device on one friendly map, explains
              problems in plain words, and fixes things only when you say yes.
            </p>
            <AuthButtons styles={s} />
            <p className={s.fine}>
              The demo needs no account. It runs on a simulated sample home.
            </p>
          </div>
          <p className={s.sample}>
            <span className={s.sampleDot} aria-hidden="true" />
            Sample home · simulated
          </p>
        </DayMotion>
      </div>
    </div>
  );
}
