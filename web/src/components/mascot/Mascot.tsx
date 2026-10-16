"use client";

import { useId } from "react";
import styles from "./Mascot.module.css";
import { BODY, EYES, FACE, SHINE, STAR, STRING } from "./shapes";

type Props = {
  size?: number;
  label?: string; // omit to mark it decorative
  mood?: "idle" | "thinking";
  className?: string;
};


// Idle: slow breath, wandering eyes, the star balloon drifting on its string.
// Thinking: eyes held up on the star, a slow pondering tilt, a brighter
// pulsing star and a chat bubble with typing dots. Still under reduced motion.
export function Mascot({ size = 160, label, mood = "idle", className }: Props) {
  const id = useId().replace(/:/g, "");
  const halo = `nl-halo-${id}`;
  const pool = `nl-pool-${id}`;

  return (
    <svg
      viewBox="0 0 193 243"
      width={size}
      height={(size * 243) / 193}
      className={`${styles.root} ${className ?? ""}`}
      data-mood={mood}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <defs>
        <radialGradient id={halo}>
          <stop offset="0" stopColor="var(--mascot-star)" stopOpacity="0.5" />
          <stop offset="1" stopColor="var(--mascot-star)" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={pool}>
          <stop offset="0" stopColor="var(--mascot-star)" stopOpacity="0.22" />
          <stop offset="1" stopColor="var(--mascot-star)" stopOpacity="0" />
        </radialGradient>
      </defs>

      <ellipse className={styles.pool} cx="80" cy="234" rx="100" ry="14" fill={`url(#${pool})`} />
      <ellipse className={styles.shadow} cx="76" cy="234.3" rx="73" ry="4.5" />

      <g className={styles.tilt}>
        <g className={styles.bubble}>
          <path
            d="M8 56C14 46 40 44 50 52C58 58 56 72 48 77C50 82 53 85 54 87.5C54.6 89.8 52.4 90.6 50.2 89.6C45.5 87.6 42 84 39 80C28 83 12 82 6 74C0 67 2 61 8 56Z"
            fill="var(--mascot-ink)"
            stroke="var(--mascot-rim)"
            strokeWidth="1"
          />
          <g fill="var(--mascot-face)">
            <ellipse cx="17" cy="65.5" rx="3.6" ry="4.4" />
            <ellipse cx="28.5" cy="64.3" rx="3.6" ry="4.4" />
            <ellipse cx="40" cy="63.1" rx="3.6" ry="4.4" />
          </g>
        </g>
        <g className={styles.balloonLift}>
          <g className={styles.sway}>
            <path d={STRING} fill="var(--mascot-string)" />
            <g className={styles.bob}>
              <circle className={styles.halo} cx="144.8" cy="46" r="62" fill={`url(#${halo})`} />
              <path d={STAR} fill="var(--mascot-star)" />
              {SHINE.map((d) => (
                <path key={d} d={d} fill="var(--mascot-shine)" />
              ))}
              <g className={styles.sparkles} stroke="var(--mascot-star)" strokeWidth="2.2" strokeLinecap="round">
                <line x1="92" y1="8" x2="97" y2="14" />
                <line x1="194" y1="30" x2="188" y2="34" />
                <line x1="192" y1="74" x2="186" y2="72" />
              </g>
            </g>
          </g>
        </g>

        <g className={styles.breathe}>
          <path d={BODY} fill="var(--mascot-ink)" stroke="var(--mascot-rim)" strokeWidth="1" />
          <path
            d="M34.3 192C35.4 201 33.4 210.6 25 215.8C30.6 209.6 32.6 201.4 34.3 192Z"
            fill="var(--mascot-crease)"
          />
          <path d="M133.3 173L132 183.8" stroke="var(--mascot-string)" strokeWidth="1.3" strokeLinecap="round" />
          <path d="M130.8 155C129.6 163 131 176 136.5 182.5" fill="none" stroke="var(--mascot-crease)" strokeWidth="0.9" strokeLinecap="round" />
          <path d={FACE} fill="var(--mascot-face)" />
          <g className={styles.glance}>
            {EYES.map((d) => (
              <path key={d} className={styles.eye} d={d} fill="var(--mascot-eye)" />
            ))}
          </g>
        </g>
      </g>
    </svg>
  );
}
