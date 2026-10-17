// The map's visual vocabulary: an icon per kind of device, a line style per kind of relationship.
import { Cctv, Cpu, Gamepad2, Globe, HardDrive, Laptop, Monitor, Router, Server, type LucideIcon } from "lucide-react";
import type { LinkKind } from "@/lib/types";

export const DEVICE_ICON: Record<string, LucideIcon> = {
  pi: Cpu, mac: Monitor, nas: HardDrive, gameserver: Gamepad2, camera: Cctv, router: Router, computer: Laptop,
  watched: Globe,
};
export const iconFor = (kind?: string): LucideIcon => DEVICE_ICON[kind ?? ""] ?? Server;

/** Each relationship reads differently at a glance: solid wire, flowing dashes, dots, dash-dot. */
export const LINK: Record<LinkKind, { label: string; verb: string; color: string; dash?: string; arrow: boolean;
  flow: boolean }> = {
  network: { label: "Network", verb: "connected through", color: "var(--offline)", arrow: false, flow: false },
  backup: { label: "Backup", verb: "backs up to", color: "var(--accent)", dash: "7 5", arrow: true, flow: true },
  depends: { label: "Relies on", verb: "relies on", color: "var(--ink)", dash: "1.5 5", arrow: true, flow: false },
  power: { label: "Power", verb: "powered by", color: "var(--glow)", dash: "10 4 2 4", arrow: true, flow: false },
};
export const LINK_KINDS = Object.keys(LINK) as LinkKind[];

export const GRID = 20; // graph-paper square; nodes snap to it
export const NODE_W = 200, NODE_H = 132;
