import { ArrowTo, Check, Close, ListView, Look, Monitor, NeedsYou, Trust, Undo, type IconType } from "../icons";

// The landing page's icons, by name, from the app's one Phosphor set.
const ICONS = {
  check: Check,
  alert: NeedsYou,
  shield: Trust,
  arrow: ArrowTo,
  undo: Undo,
  eye: Look,
  plan: ListView,
  touch: Monitor,
  x: Close,
} satisfies Record<string, IconType>;

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  const C = ICONS[name];
  return <C size={size} className={className} aria-hidden focusable="false" />;
}
