"use client";

import { useEffect, useState } from "react";
import s from "./Home.module.css";

// Tonight's rounds on the sample home, on the sample night's own clock: the
// last few checks from a little after two, then a new one every few seconds. The Pi is the one
// thing that needs a look, as everywhere else on the page.
type Row = { device: string; room: string; result: string; tone: "ok" | "warn" };

const ROUND: Row[] = [
  { device: "Wi-Fi router", room: "Hall", result: "Fine", tone: "ok" },
  { device: "Home NAS", room: "Office", result: "Fine", tone: "ok" },
  { device: "Mac Mini", room: "Living room", result: "Fine", tone: "ok" },
  { device: "Minecraft server", room: "Kids’ room", result: "Fine", tone: "ok" },
  { device: "Camera recorder", room: "Garage", result: "Fine", tone: "ok" },
  { device: "Raspberry Pi", room: "Attic", result: "Disk 94% full", tone: "warn" },
];
const SHOWN = 5;
const EVERY = 3200;

// The night starts at 02:00 and each check comes a minute and a half after the
// last, so the server and the browser always agree on the times.
const START = 2 * 60;
const GAP = 1.5;

function clock(i: number) {
  const m = Math.floor(START + i * GAP) % (24 * 60);
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

export function NightLog() {
  const [step, setStep] = useState(ROUND.length);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setInterval(() => setStep((n) => n + 1), EVERY);
    return () => window.clearInterval(id);
  }, []);

  const rows = Array.from({ length: SHOWN }, (_, k) => {
    const i = step - SHOWN + k;
    return { key: i, row: ROUND[((i % ROUND.length) + ROUND.length) % ROUND.length] };
  });
  const needs = rows.some((r) => r.row.tone === "warn");

  return (
    <figure className={s.log} data-ui aria-label="Tonight’s checks on the sample home">
      <figcaption className={s.logHead}>
        <span className={s.logTitle}>
          <span className={s.logLive} aria-hidden="true" />
          Tonight, room by room
        </span>
        <span className={s.logTag}>Sample home</span>
      </figcaption>
      <ol className={s.logRows} aria-live="off">
        {rows.map(({ key, row }) => (
          <li key={key} className={s.logRow} data-tone={row.tone}>
            <time className={s.logTime}>{clock(key)}</time>
            <span className={s.logDevice}>
              {row.device}
              <span className={s.logRoom}>{row.room}</span>
            </span>
            <span className={s.logResult}>
              <span className={s.logDot} aria-hidden="true" />
              {row.result}
            </span>
          </li>
        ))}
      </ol>
      <p className={s.logFoot}>
        {needs ? (
          <>
            <strong>1 thing needs you.</strong> The rest is fine.
          </>
        ) : (
          "All fine so far."
        )}
        <span key={step} className={s.logNext} style={{ "--every": `${EVERY}ms` } as React.CSSProperties} aria-hidden="true" />
      </p>
    </figure>
  );
}
