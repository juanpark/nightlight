"use client";

import { useId, type CSSProperties } from "react";
import styles from "./Mascot.module.css";
import { Mascot } from "./Mascot";
import { POSES, type PoseName } from "./poses";

type Props = {
  pose: PoseName | "thinking";
  size?: number;
  label?: string; // omit to mark it decorative
  className?: string;
};

// The six poses from the mascot sheet, each with its own loop:
// wave (sparkles), walk (waddle in place), sit (rock), peek (inch forward),
// happy (hop), wiggle (shimmy); plus thinking, which is the idle artwork
// with a chat bubble (see Mascot). Still under reduced motion.
export function MascotPose({ pose, ...rest }: Props) {
  if (pose === "thinking") return <Mascot mood="thinking" {...rest} />;
  return <SheetPose pose={pose} {...rest} />;
}

function SheetPose({ pose, size = 160, label, className }: Props & { pose: PoseName }) {
  const p = POSES[pose];
  const halo = `nl-halo-${useId().replace(/:/g, "")}`;
  const pivots = {
    "--hand-x": `${p.hand[0]}px`,
    "--hand-y": `${p.hand[1]}px`,
    "--knot-x": `${p.knot[0]}px`,
    "--knot-y": `${p.knot[1]}px`,
    "--feet-x": `${p.shadow.cx}px`,
    "--feet-y": `${p.shadow.cy}px`,
  } as CSSProperties;

  return (
    <svg
      viewBox="0 0 256 256"
      width={size}
      height={size}
      className={`${styles.root} ${className ?? ""}`}
      data-pose={pose}
      style={pivots}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <defs>
        <radialGradient id={halo}>
          <stop offset="0" stopColor="var(--mascot-star)" stopOpacity="0.5" />
          <stop offset="1" stopColor="var(--mascot-star)" stopOpacity="0" />
        </radialGradient>
      </defs>

      <ellipse className={styles.shadow} cx={p.shadow.cx} cy={p.shadow.cy} rx={p.shadow.rx} ry="4" />

      <g className={styles.marks}>
        {p.marks.map((d) => (
          <path key={d} d={d} fill="var(--mascot-mark)" />
        ))}
      </g>

      <g className={styles.move}>
        <g className={styles.poseSway}>
          <path d={p.line} fill="none" stroke="var(--mascot-string)" strokeWidth="1.3" strokeLinecap="round" />
          <g className={styles.poseBob}>
            <path d={p.string} fill="var(--mascot-string)" />
            <circle
              className={styles.halo}
              cx={p.starCenter[0]}
              cy={p.starCenter[1]}
              r="52"
              fill={`url(#${halo})`}
            />
            <path d={p.star} fill="var(--mascot-star)" />
            {p.shine.map((d) => (
              <path key={d} d={d} fill="var(--mascot-shine)" />
            ))}
          </g>
        </g>

        <g className={styles.breathe}>
          <path d={p.body} fill="var(--mascot-ink)" stroke="var(--mascot-rim)" strokeWidth="1" />
          {p.creases.map((d) => (
            <path key={d} d={d} fill="var(--mascot-crease)" />
          ))}
          <path d={p.face} fill="var(--mascot-face)" />
          <g className={styles.poseGlance}>
            {p.eyes.map((d) => (
              <path key={d} className={styles.poseEye} d={d} fill="var(--mascot-eye)" />
            ))}
          </g>
        </g>
      </g>
    </svg>
  );
}
