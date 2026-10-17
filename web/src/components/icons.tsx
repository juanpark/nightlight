// The app's icons: Phosphor in its duotone weight, a rounded outline with a soft flat fill in the same colour, so they
// sit with the mascot's flat, matte look. Import icons from here, never from the library, so the set stays one weight.
// A favourite star passes weight="fill" to read as on. The fill layer is a touch stronger than Phosphor's (globals.css)
// so it still reads on navy.
import { Fragment, type ComponentType } from "react";
import type { IconProps } from "@phosphor-icons/react";
import {
  AppWindow as PAppWindow, Archive as PArchive, ArrowLeft as PArrowLeft, ArrowRight, ArrowsClockwise, ArrowsLeftRight,
  ArrowDown, Binoculars as PBinoculars, CaretRight, Check as PCheck, Clock, MinusCircle, StopCircle,
  Broadcast, ChatCircle, CheckCircle, HourglassMedium, WarningCircle, Cloud as PCloud, Cpu as PCpu, Cube as PCube, Database as PDatabase, Desktop, DownloadSimple,
  FilmStrip, Flask, FlowArrow, Folder as PFolder, GameController, GitBranch as PGitBranch, Globe as PGlobe, HardDrive,
  HardDrives, House as PHouse, Image as PImage, Info as PInfo, Key, Laptop as PLaptop, List, ListBullets,
  Lock as PLock, MapTrifold, Moon as PMoon, Network as PNetwork, NotePencil, PlusCircle, Printer as PPrinter, Pulse,
  Question, SecurityCamera, Shield as PShield, ShieldCheck as PShieldCheck, ShippingContainer, SidebarSimple, SignOut,
  Signpost as PSignpost, SpeakerHifi, SquaresFour, Star as PStar, Sun as PSun, TerminalWindow, Trash as PTrash,
  WifiHigh, XCircle,
} from "@phosphor-icons/react/ssr";

export type IconType = ComponentType<IconProps>;

const duo = (C: IconType, mirrored?: boolean): IconType => {
  const Duo = ({ weight = "duotone", className, ...p }: IconProps) =>
    <C weight={weight} mirrored={mirrored} className={`icon ${className ?? ""}`} {...p} />;
  Duo.displayName = C.displayName;
  return Duo;
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
export const Stopped = duo(StopCircle);
export const Switched = duo(ArrowsLeftRight);

/** Text from the server or the agent with each "→" drawn as an arrow, read aloud as "to". */
export function ArrowText({ text }: { text: string }) {
  const parts = text.split(/\s*→\s*/);
  if (parts.length === 1) return <>{text}</>;
  return <>{parts.map((p, i) => <Fragment key={i}>
    {i > 0 && <span className="arrow-to"><ArrowTo size="0.9em" aria-hidden /><span className="sr-only"> to </span></span>}{p}
  </Fragment>)}</>;
}

// Shell and controls
export const Activity = duo(Pulse);
export const ArrowLeft = duo(PArrowLeft);
export const FoundNearby = duo(PBinoculars);
export const Chat = duo(ChatCircle);
export const Close = duo(XCircle);
export const DemoTools = duo(Flask);
export const Favorites = duo(PStar);
export const Globe = duo(PGlobe);
export const Grid = duo(SquaresFour);
export const House = duo(PHouse);
export const Info = duo(PInfo);
export const ListView = duo(ListBullets);
export const MapView = duo(MapTrifold);
export const Memory = duo(NotePencil);
export const Menu = duo(List);
export const Moon = duo(PMoon);
export const Plus = duo(PlusCircle);
export const HideChat = duo(SidebarSimple, true); // the panel on the right
export const SignOutIcon = duo(SignOut);
export const Star = duo(PStar);
export const Sun = duo(PSun);
export const Trash = duo(PTrash);
export const Trust = duo(PShieldCheck);

// How a job went (with a word beside it, never alone)
export const Done = duo(CheckCircle);
export const NotDone = duo(WarningCircle);
export const Working = duo(HourglassMedium);
export const Declined = duo(MinusCircle);
export const OutOfDate = duo(Clock);
export const ToLatest = mark(ArrowDown);

// Devices, roles and apps
export const AppWindow = duo(PAppWindow);
export const Archive = duo(PArchive);
export const Camera = duo(SecurityCamera);
export const Cloud = duo(PCloud);
export const Computer = duo(PLaptop);
export const Container = duo(ShippingContainer);
export const Cpu = duo(PCpu);
export const Database = duo(PDatabase);
export const Download = duo(DownloadSimple);
export const Film = duo(FilmStrip);
export const Folder = duo(PFolder);
export const GameBlock = duo(PCube); // Minecraft: a block
export const Gamepad = duo(GameController);
export const GitBranch = duo(PGitBranch);
export const Image = duo(PImage);
export const KeyIcon = duo(Key);
export const Lock = duo(PLock);
export const Monitor = duo(Desktop);
export const Nas = duo(HardDrive);
export const Network = duo(PNetwork);
export const Printer = duo(PPrinter);
export const Radio = duo(Broadcast);
export const Refresh = duo(ArrowsClockwise);
export const Router = duo(WifiHigh);
export const Server = duo(HardDrives);
export const Shield = duo(PShield);
export const Signpost = duo(PSignpost);
export const Speaker = duo(SpeakerHifi);
export const Terminal = duo(TerminalWindow);
export const Unknown = duo(Question);
export const Workflow = duo(FlowArrow);
