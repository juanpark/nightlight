"use client";

import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { MascotPose } from "../../mascot/MascotPose";
import type { PoseName } from "../../mascot/poses";
import s from "./Night.module.css";

// Tonight's ledger for the sample home: every device and what runs on it, the
// way the map lists them. Hovering a row brings a small card along with the
// cursor: the mascot's reaction and the one plain sentence the app would show.
type Entry = {
  time: string;
  name: string;
  kind: string;
  does: string;
  room: string;
  tone: "ok" | "warn";
  status: string;
  line: string;
  pose: PoseName;
};

const ENTRIES: Entry[] = [
  { time: "02:10", name: "Wi-Fi router", kind: "Network", does: "Gets everything online", room: "Hall", tone: "ok", status: "Fine", line: "Online all night. Nothing to do.", pose: "sit" },
  { time: "02:11", name: "Home NAS", kind: "Files", does: "Keeps the family photos", room: "Office", tone: "ok", status: "Fine", line: "Photo backup ran at 01:30. Disk at 48%.", pose: "happy" },
  { time: "02:12", name: "Mac Mini", kind: "Home", does: "Runs the home automation", room: "Living room", tone: "ok", status: "Fine", line: "Lights and heating rules are running.", pose: "wave" },
  { time: "02:13", name: "Minecraft server", kind: "Games", does: "Hosts the kids’ world", room: "Kids’ room", tone: "ok", status: "Fine", line: "Two players earlier; quiet now. Backed up today.", pose: "wiggle" },
  { time: "02:14", name: "Camera recorder", kind: "Home", does: "Records the front door", room: "Garage", tone: "ok", status: "Fine", line: "Recording. 11 days of space left.", pose: "walk" },
  { time: "02:15", name: "Raspberry Pi", kind: "Network", does: "Home VPN and a car-data logger", room: "Attic", tone: "warn", status: "Needs a look", line: "The disk is 94% full, mostly old logs. I can show you what would go first.", pose: "peek" },
];

export function Ledger() {
  const table = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<number | null>(null);

  useEffect(() => {
    const box = table.current;
    const el = card.current;
    if (!box || !el || !window.matchMedia("(hover: hover)").matches) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const x = gsap.quickTo(el, "x", { duration: still ? 0 : 0.7, ease: "power3.out" });
    const y = gsap.quickTo(el, "y", { duration: still ? 0 : 0.7, ease: "power3.out" });
    const move = (e: PointerEvent) => {
      x(Math.min(e.clientX + 28, window.innerWidth - 260));
      y(e.clientY - 250);
    };
    box.addEventListener("pointermove", move);
    return () => box.removeEventListener("pointermove", move);
  }, []);

  useEffect(() => {
    const el = card.current;
    if (!el) return;
    gsap.to(el, {
      autoAlpha: active === null ? 0 : 1,
      scale: active === null ? 0.85 : 1,
      duration: 0.45,
      ease: active === null ? "power2.in" : "back.out(1.6)",
      overwrite: "auto",
    });
  }, [active]);

  const e = active === null ? null : ENTRIES[active];

  return (
    <div ref={table} className={s.ledger} onPointerLeave={() => setActive(null)}>
      <table className={s.ledgerTable}>
        <caption className={s.srOnly}>Tonight’s checks on the simulated sample home</caption>
        <thead>
          <tr>
            <th scope="col">Checked</th>
            <th scope="col">Device</th>
            <th scope="col" className={s.hideSm}>What it does</th>
            <th scope="col" className={s.hideMd}>Room</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {ENTRIES.map((r, i) => (
            <tr
              key={r.name}
              className={s.ledgerRow}
              data-tone={r.tone}
              data-active={active === i || undefined}
              onPointerEnter={() => setActive(i)}
              tabIndex={0}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              aria-label={`${r.name}: ${r.status}. ${r.line}`}
            >
              <td className={s.ledgerTime}>{r.time}</td>
              <td>
                <span className={s.ledgerName}>{r.name}</span> <span className={s.ledgerKind}>{r.kind}</span>
              </td>
              <td className={s.hideSm}>{r.does}</td>
              <td className={s.hideMd}>{r.room}</td>
              <td className={s.ledgerStatus}>
                <span className={s.ledgerDot} aria-hidden="true" />
                {r.status}
                <span className={s.ledgerArrow} aria-hidden="true">
                  ↗
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div ref={card} className={s.preview} aria-hidden="true">
        {e && (
          <>
            <div className={s.previewMascot}>
              <MascotPose key={e.pose} pose={e.pose} size={84} />
            </div>
            <p className={s.previewName}>{e.name}</p>
            <p className={s.previewLine}>{e.line}</p>
          </>
        )}
      </div>
    </div>
  );
}
