"use client";
// The home as a map (pan, zoom, lines between devices) or as a plain list of tiles; the choice is remembered here.
import { useEffect, useState } from "react";
import { Map as MapIcon, List } from "lucide-react";
import type { Need } from "@/lib/needsYou";
import type { Device, Link } from "@/lib/types";
import Board from "../Board";
import HomeMap from "./HomeMap";

type View = "map" | "list";

export default function HomeView({ uid, devices, links, marks, selected, onSelect, onAsk, now, settingUp }: {
  uid: string; devices: Device[]; links: Link[]; marks?: Map<string, Need[]>; selected: string | null;
  onSelect: (id: string) => void; onAsk: (q: string) => void; now: number; settingUp: boolean;
}) {
  const [view, setView] = useState<View>("map");
  useEffect(() => { try { if (localStorage.getItem("nl_view") === "list") setView("list"); } catch { /* default */ } }, []);
  const pick = (v: View) => { setView(v); try { localStorage.setItem("nl_view", v); } catch { /* this visit */ } };
  const empty = devices.length === 0;
  return (
    <div className="homeview">
      <div className="mode-switch view-switch" role="radiogroup" aria-label="Show your home as">
        <button role="radio" aria-checked={view === "map"} className={view === "map" ? "on" : ""} onClick={() => pick("map")}>
          <MapIcon size={14} /> Map</button>
        <button role="radio" aria-checked={view === "list"} className={view === "list" ? "on" : ""} onClick={() => pick("list")}>
          <List size={14} /> List</button>
      </div>
      {view === "list" || empty
        ? <Board devices={devices} selected={selected} onSelect={onSelect} marks={marks} settingUp={settingUp} />
        : <HomeMap uid={uid} devices={devices} links={links} marks={marks} selected={selected} onSelect={onSelect}
            onAsk={onAsk} now={now} />}
    </div>
  );
}
