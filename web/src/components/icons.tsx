// The app's icons: Phosphor in its regular weight, one clean line with no fill. Import icons from here, never from
// the library, so the set stays one weight. A favourite star (and a settled job's status) passes weight="fill".
import { Fragment, type ComponentType } from "react";
import type { IconProps } from "@phosphor-icons/react";
import {
  AppWindow as PAppWindow, Archive as PArchive, ArrowLeft as PArrowLeft, ArrowRight, ArrowsClockwise, ArrowsLeftRight,
  ArrowCounterClockwise, ArrowDown, ArrowsOutCardinal, CaretDown, MapPin, SlidersHorizontal, Tag, Binoculars as PBinoculars, CaretRight, Check as PCheck, Clock, MinusCircle, StopCircle,
  Broadcast, ChatCircle, ChatsCircle, CheckCircle, HourglassMedium, WarningCircle, Cloud as PCloud, Cpu as PCpu, Cube as PCube, Database as PDatabase, Desktop, DownloadSimple,
  Eye as PEye, FilmStrip, Fingerprint, Flask, GearSix, FlowArrow, Folder as PFolder, GameController, GitBranch as PGitBranch, Globe as PGlobe, HardDrive,
  HardDrives, House as PHouse, Image as PImage, Info as PInfo, Key, Laptop as PLaptop, List, ListBullets, ListChecks,
  Lock as PLock, MapTrifold, Moon as PMoon, Network as PNetwork, NotePencil, Plus as PPlus, Printer as PPrinter, Pulse,
  Question, SecurityCamera, Shield as PShield, ShieldCheck as PShieldCheck, ShieldWarning, ShippingContainer, SidebarSimple, SignOut,
  Signpost as PSignpost, SpeakerHifi, SquaresFour, Star as PStar, Sun as PSun, TerminalWindow, Trash as PTrash,
  WifiHigh, WifiSlash, Bell as PBell, X as PX, ExclamationMark, ClockCountdown,
} from "@phosphor-icons/react/ssr";

export type IconType = ComponentType<IconProps>;

const line = (C: IconType, mirrored?: boolean): IconType => {
  const Line = ({ weight = "regular", className, ...p }: IconProps) =>
    <C weight={weight} mirrored={mirrored} className={`icon ${className ?? ""}`} {...p} />;
  Line.displayName = C.displayName;
  return Line;
};

// Small marks inside text and controls: a bolder line, no fill, so they hold up at text size.
const mark = (C: IconType): IconType => {
  const Mark = ({ weight = "bold", className, ...p }: IconProps) => <C weight={weight} className={`icon ${className ?? ""}`} {...p} />;
  Mark.displayName = C.displayName;
  return Mark;
};
export const ArrowTo = mark(ArrowRight);
export const Caret = mark(CaretRight); // points down when its control is open (rotated in CSS)
export const Check = mark(PCheck);
// The four statuses, always drawn beside their word (StatusWord.tsx): ✓ Fine · ! Needs a look · ✗ Broken · Offline
export const StatusFine = mark(PCheck);
export const StatusLook = mark(ExclamationMark);
export const StatusBroken = mark(PX);
export const StatusOffline = line(WifiSlash);
export const StatusLater = line(ClockCountdown);
export const Stopped = line(StopCircle);
export const Switched = line(ArrowsLeftRight);

/** Text from the server or the agent with each "→" drawn as an arrow, read aloud as "to". */
export function ArrowText({ text }: { text: string }) {
  const parts = text.split(/\s*→\s*/);
  if (parts.length === 1) return <>{text}</>;
  return <>{parts.map((p, i) => <Fragment key={i}>
    {i > 0 && <span className="arrow-to"><ArrowTo size="0.9em" aria-hidden /><span className="sr-only"> to </span></span>}{p}
  </Fragment>)}</>;
}

// Shell and controls
export const Activity = line(Pulse);
export const Bell = line(PBell);
export const ArrowLeft = line(PArrowLeft);
export const FoundNearby = line(PBinoculars);
export const Chat = line(ChatCircle);
export const Chats = line(ChatsCircle);
export const Close = line(PX);
export const DemoTools = line(Flask);
export const Favorites = line(PStar);
export const Globe = line(PGlobe);
export const Grid = line(SquaresFour);
export const House = line(PHouse);
export const Info = line(PInfo);
export const ListView = line(ListBullets);
export const MapView = line(MapTrifold);
export const StatusView = line(ListChecks); // the ✓ ! ✗ status board
export const MoveMap = line(ArrowsOutCardinal);
export const Memory = line(NotePencil);
export const Menu = line(List);
export const Moon = line(PMoon);
export const Plus = line(PPlus);
export const HideChat = line(SidebarSimple, true); // the panel on the right
export const Settings = line(GearSix);
export const SignOutIcon = line(SignOut);
export const Star = line(PStar);
export const Sun = line(PSun);
export const Trash = line(PTrash);
export const Trust = line(PShieldCheck);
export const Passkey = line(Fingerprint); // a card that needs your passkey
export const Risky = line(ShieldWarning); // a risky card

// How a job went (with a word beside it, never alone)
export const Done = line(CheckCircle);
export const NotDone = line(WarningCircle);
export const Working = line(HourglassMedium);
export const Declined = line(MinusCircle);
export const OutOfDate = line(Clock);
export const ToLatest = mark(ArrowDown);
export const Opens = mark(CaretDown); // a menu button's "opens below"
export const Kinds = line(SlidersHorizontal);
export const Place = line(MapPin);
export const Tags = line(Tag);
export const NeedsYou = line(WarningCircle);

// Devices, roles and apps
export const AppWindow = line(PAppWindow);
export const Archive = line(PArchive);
export const Camera = line(SecurityCamera);
export const Cloud = line(PCloud);
export const Computer = line(PLaptop);
export const Container = line(ShippingContainer);
export const Cpu = line(PCpu);
export const Database = line(PDatabase);
export const Download = line(DownloadSimple);
export const Film = line(FilmStrip);
export const Folder = line(PFolder);
export const GameBlock = line(PCube); // Minecraft: a block
export const Gamepad = line(GameController);
export const GitBranch = line(PGitBranch);
export const Image = line(PImage);
export const KeyIcon = line(Key);
export const Lock = line(PLock);
export const Monitor = line(Desktop);
export const Nas = line(HardDrive);
export const Network = line(PNetwork);
export const Printer = line(PPrinter);
export const Radio = line(Broadcast);
export const Refresh = line(ArrowsClockwise);
export const Router = line(WifiHigh);
export const Server = line(HardDrives);
export const Shield = line(PShield);
export const Signpost = line(PSignpost);
export const Speaker = line(SpeakerHifi);
export const Terminal = line(TerminalWindow);
export const Unknown = line(Question);
export const Workflow = line(FlowArrow);

// The landing page's story cards
export const Look = line(PEye); // a dry run: what would happen
export const Undo = line(ArrowCounterClockwise);
