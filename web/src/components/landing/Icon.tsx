// A small drawn icon set for the landing page: one stroke weight, round caps.
const PATHS = {
  check: "M5 12.5l4.2 4.2L19 7",
  ring: "M12 4.5a7.5 7.5 0 1 0 0 15a7.5 7.5 0 1 0 0-15Z",
  alert: "M12 7.5v5.5M12 16.4v.1",
  shield: "M12 3.5l7 2.6v5.2c0 4.4-3 7.6-7 9.2c-4-1.6-7-4.8-7-9.2V6.1Z",
  arrow: "M5 12h13M13 6.5l5.5 5.5L13 17.5",
  undo: "M8.5 7.5L4.5 11.5L8.5 15.5M5 11.5h9.5a5 5 0 0 1 0 10H11",
  eye: "M2.8 12c2.2-4 5.3-6 9.2-6s7 2 9.2 6c-2.2 4-5.3 6-9.2 6s-7-2-9.2-6ZM12 9.4a2.6 2.6 0 1 0 0 5.2a2.6 2.6 0 1 0 0-5.2Z",
  plan: "M8 6.5h11M8 12h11M8 17.5h11M4.5 6.5h.1M4.5 12h.1M4.5 17.5h.1",
  touch: "M4.5 5.5h15v10h-15ZM9 19.5h6M12 15.5v4",
  x: "M6.5 6.5l11 11M17.5 6.5l-11 11",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
      {name === "alert" && <path d={PATHS.ring} />}
    </svg>
  );
}
