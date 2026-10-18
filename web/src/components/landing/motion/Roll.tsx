import type { CSSProperties } from "react";
import s from "./Roll.module.css";

// Text that rolls up into a copy of itself on hover, letter by letter. Screen
// readers get the plain words once; the letters are decoration.
export function Roll({ text, className }: { text: string; className?: string }) {
  const chars = Array.from(text);
  return (
    <span className={`${s.roll} ${className ?? ""}`}>
      <span className={s.sr}>{text}</span>
      {chars.map((c, i) => (
        <span key={i} className={s.char} style={{ "--i": i } as CSSProperties} aria-hidden="true" data-c={c}>
          {c === " " ? " " : c}
        </span>
      ))}
    </span>
  );
}
