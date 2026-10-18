// The map's visual vocabulary: an icon per kind of device, a line style per kind of relationship.
import { Activity, AppWindow, Archive, Camera as Cctv, Unknown as CircleHelp, Cloud, Container, Cpu, Database,
  Download, Film, Folder, Gamepad as Gamepad2, GitBranch, Globe, Nas as HardDrive, House, Image,
  KeyIcon as KeyRound, Computer as Laptop, Lock, Monitor, Network, GameBlock as Pickaxe, Printer, Radio,
  Refresh as RefreshCw, Router, Server, Shield, Signpost, Speaker, Terminal, Workflow,
  type IconType as LucideIcon } from "@/src/components/icons";
import type { Device, LinkKind, Role, Service } from "@/lib/types";

export const DEVICE_ICON: Record<string, LucideIcon> = {
  pi: Cpu, mac: Monitor, nas: HardDrive, gameserver: Gamepad2, camera: Cctv, router: Router, computer: Laptop,
  watched: Globe,
};
export const iconFor = (kind?: string): LucideIcon => DEVICE_ICON[kind ?? ""] ?? Server;

/** What a watched thing is (the person can correct Nightlight's guess), in the order the picker shows them. */
export const ROLES: Record<Role, { label: string; icon: LucideIcon }> = {
  router: { label: "Router", icon: Router },
  printer: { label: "Printer", icon: Printer },
  fileshare: { label: "File share or NAS", icon: HardDrive },
  smarthome: { label: "Smart home", icon: House },
  server: { label: "Media or game server", icon: Server },
  speaker: { label: "TV or speaker", icon: Speaker },
  computer: { label: "Computer", icon: Laptop },
  other: { label: "Other", icon: CircleHelp },
};
export const roleOf = (d: Device): Role => d.role && d.role in ROLES ? d.role : "other";
/** The icon for any device: a watched thing by its role, the rest by kind. */
export const deviceIcon = (d: Device): LucideIcon => d.kind === "watched" ? ROLES[roleOf(d)].icon : iconFor(d.kind);

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

/** An app's icon: the key Nightlight gave it (Service.about.icon), else one for its category, else a plain window. */
const APP_ICON: Record<string, LucideIcon> = {
  plex: Film, jellyfin: Film, pihole: Shield, adguard: Shield, homeassistant: House, homebridge: House, mqtt: Radio,
  nodered: Workflow, tailscale: Network, wireguard: KeyRound, vpn: KeyRound, nextcloud: Cloud, syncthing: RefreshCw,
  minecraft: Pickaxe, docker: Container, database: Database, web: Globe, dns: Signpost, backup: Archive,
  download: Download, monitoring: Activity, photos: Image, files: Folder, git: GitBranch, passwords: Lock, ssh: Terminal,
  generic: AppWindow,
};
const CATEGORY_ICON: Record<string, LucideIcon> = {
  home: House, files: Folder, system: Cpu, network: Network, games: Gamepad2, containers: Container, media: Film,
};
export const appIcon = (s: Service): LucideIcon =>
  APP_ICON[s.about?.icon ?? ""] ?? CATEGORY_ICON[s.category ?? ""] ?? AppWindow;
