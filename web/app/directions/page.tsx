"use client";

// TEMPORARY: two light-theme directions for the landing, for Sadika to pick from. Delete after the pick.
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Logo } from "@/src/components/brand/Logo";
import { MascotPose } from "@/src/components/mascot/MascotPose";
import { display, sans } from "@/src/components/landing/fonts";
import { ArrowTo, Check, NeedsYou, Plus, Trust } from "@/src/components/icons";
import s from "./directions.module.css";

const ROWS = [
  { t: "02:01", d: "Home NAS", r: "Office", ok: true, res: "Fine" },
  { t: "02:03", d: "Mac Mini", r: "Living room", ok: true, res: "Fine" },
  { t: "02:04", d: "Minecraft server", r: "Kids’ room", ok: true, res: "Fine" },
  { t: "02:06", d: "Camera recorder", r: "Garage", ok: true, res: "Fine" },
  { t: "02:07", d: "Raspberry Pi", r: "Attic", ok: false, res: "Disk 94% full" },
];

function Nav({ dark }: { dark?: boolean }) {
  return (
    <header className={s.nav} data-dark={dark || undefined}>
      <Logo height={20} />
      <nav className={s.links} aria-label="Sections">
        <a href="#">How a night goes</a><a href="#">What it watches</a><a href="#">Who it’s for</a><a href="#">Privacy</a>
      </nav>
      <a className={s.navCta} href="#">Try the demo</a>
    </header>
  );
}

function Ctas() {
  return (
    <div className={s.ctas}>
      <button className={s.primary}>Try the demo <ArrowTo size={18} aria-hidden /></button>
      <button className={s.secondary}>
        <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>
        Sign in with Google</button>
    </div>
  );
}

function Log() {
  return (
    <div className={s.log}>
      <div className={s.logHead}><span className={s.live} aria-hidden />Tonight, room by room<span className={s.tag}>Sample home · simulated</span></div>
      <ol className={s.rows}>
        {ROWS.map((r) => (
          <li key={r.t} data-needs={!r.ok || undefined}>
            <time>{r.t}</time><b>{r.d}</b><span className={s.room}>{r.r}</span>
            <span className={s.res}>{r.ok ? <Check size={14} aria-hidden /> : <NeedsYou size={16} aria-hidden />}{r.res}</span>
          </li>))}
      </ol>
      <div className={s.logFoot}><b>1 thing needs you.</b> The rest is fine.</div>
    </div>
  );
}

function Approval() {
  return (
    <div className={s.card}>
      <div className={s.cardHead}><b>Clean up old logs on the Raspberry Pi</b><span className={s.risk}><Trust size={14} aria-hidden />Safe</span></div>
      <dl className={s.facts}>
        <div><dt>What I’ll do</dt><dd>Delete the car-data logger’s log files older than 30 days.</dd></div>
        <div><dt>Dry run</dt><dd>412 files, 5.2 GB. The disk goes from 94% to 61%.</dd></div>
        <div><dt>What it touches</dt><dd>Only that one log folder. The VPN keeps running.</dd></div>
        <div><dt>How to undo</dt><dd>It can’t be undone: deleted logs are gone. Nothing else changes.</dd></div>
      </dl>
      <div className={s.cardFoot}><button className={s.primary}>Approve</button><button className={s.secondary}>Not now</button></div>
    </div>
  );
}

function Beat() {
  return (
    <section className={s.beat}>
      <div className={s.beatText}>
        <p className={s.eyebrow}>3.0 — It asks</p>
        <h2 className={s.h2}>Nothing changes <span>until you say yes.</span></h2>
        <p className={s.body}>Before it touches anything, Nightlight shows a card: the plan, a dry run, what it touches and how to undo it.</p>
        <ul className={s.acc}>
          {["The plan, in one sentence", "A dry run first", "What it touches", "How to undo it"].map((x, i) => (
            <li key={x}><span>3.{i + 1}</span>{x}<Plus size={16} aria-hidden /></li>))}
        </ul>
      </div>
      <div className={s.canvas}><Approval /></div>
    </section>
  );
}

function A() {
  return (
    <div className={s.page} data-dir="a">
      <Nav />
      <section className={s.heroA}>
        <div className={s.heroText}>
          <p className={s.eyebrow}>A house-sitter for home servers</p>
          <h1 className={s.h1}>You sleep.<br /><span>It keeps watch.</span></h1>
          <p className={s.lede}>Nightlight looks after the computers in your home or small office. It tells you what’s wrong in plain words, and never fixes anything without your yes.</p>
          <Ctas />
        </div>
        <div className={s.frame}>
          <div className={s.frameBar}><span /><span /><span /><em>Your home</em></div>
          <div className={s.frameBody}>
            <Log />
            <div className={s.mascotPeek}><MascotPose pose="peek" size={150} /></div>
          </div>
        </div>
      </section>
      <Beat />
      <section className={s.bandInk}>
        <h2 className={s.h2}>Don’t lose sleep over it. <span>Try the sample home in one click.</span></h2>
        <Ctas />
      </section>
    </div>
  );
}

function B() {
  return (
    <div className={s.page} data-dir="b">
      <section className={s.heroB}>
        <Nav dark />
        <div className={s.heroBInner}>
          <div className={s.heroText}>
            <p className={s.eyebrow}>A house-sitter for home servers</p>
            <h1 className={s.h1}>You sleep.<br /><span>It keeps watch.</span></h1>
            <p className={s.lede}>Nightlight looks after the computers in your home or small office. It tells you what’s wrong in plain words, and never fixes anything without your yes.</p>
            <Ctas />
          </div>
          <div className={s.sky}>
            {[[8, 14, 1], [22, 62, 0.6], [40, 30, 0.8], [58, 70, 0.5], [70, 18, 1], [86, 48, 0.7], [94, 8, 0.6], [30, 86, 0.5]].map(([x, y, k], i) => (
              <svg key={i} className={s.star} style={{ left: `${x}%`, top: `${y}%`, scale: `${k}` }} viewBox="0 0 20 20" aria-hidden>
                <path d="M10 0c.9 5 4.1 8.2 10 10-5.9 1.8-9.1 5-10 10-.9-5-4.1-8.2-10-10C5.9 8.2 9.1 5 10 0Z" /></svg>))}
            <div className={s.heroMascot} data-theme="night"><MascotPose pose="wave" size={200} /></div>
            <Log />
          </div>
        </div>
        <svg className={s.horizon} viewBox="0 0 1440 80" preserveAspectRatio="none" aria-hidden><path d="M0 80V40C240 8 480 0 720 0s480 8 720 40v40Z" /></svg>
      </section>
      <Beat />
    </div>
  );
}

function Pick() {
  const d = useSearchParams().get("d");
  return <div className={`${display.variable} ${sans.variable}`}>{d === "b" ? <B /> : <A />}</div>;
}

export default function Page() {
  return <Suspense><Pick /></Suspense>;
}
