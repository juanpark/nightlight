"use client";

import { useId } from "react";
import styles from "./Mascot.module.css";
import { BODY, EYES, FACE } from "./shapes";

// The head from the app icon, cropped below the face mask (same crop as LogoIcon).
const HEAD_CROP = "M-10 -10H200V136H137C137 174 114 198 76 198C42 198 17 184 12 156C11 150 10 146 -10 140Z";

export type HeadMood = "idle" | "busy" | "waiting";

type Props = {
  size?: number;
  mood?: HeadMood;
  label?: string; // omit to mark it decorative
  className?: string;
};

// A calm presence for headers and the folded chat. Idle: mostly still, one blink
// and a slow look around now and then. Busy: eyes down on the conversation.
// Waiting: wide eyes on you with a blink, while a card needs an answer.
export function MascotHead({ size = 24, mood = "idle", label, className }: Props) {
  const crop = `nl-head-${useId().replace(/:/g, "")}`;
  return (
    <svg
      viewBox="8 86 136 116"
      width={size}
      height={(size * 116) / 136}
      className={`${styles.root} ${styles.head} ${className ?? ""}`}
      data-head={mood}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <defs>
        <clipPath id={crop}>
          <path d={HEAD_CROP} />
        </clipPath>
      </defs>
      <path d={BODY} fill="var(--mascot-ink)" stroke="var(--mascot-rim)" strokeWidth="2" clipPath={`url(#${crop})`} />
      <path d={FACE} fill="var(--mascot-face)" />
      <g className={styles.headGlance}>
        {EYES.map((d) => (
          <path key={d} className={styles.headEye} d={d} fill="var(--mascot-eye)" />
        ))}
      </g>
    </svg>
  );
}
