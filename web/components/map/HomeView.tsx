"use client";
// The home as a map (pan, zoom, lines between devices) or as a plain list of tiles, narrowed by the bar above it;
// Map or List is remembered here. Watched websites follow below with the filters that apply to them.
import { useFollowed } from "@/lib/follow";
import { useEffect, useMemo, useRef, useState } from "react";
import { usePlaces } from "@/lib/data";
import { applyFilter, applyToWatches, filtering, NO_FILTER, placesOf, type Filter } from "@/lib/homeFilter";
import type { Need } from "@/lib/needsYou";
import type { Device, Link, Watch } from "@/lib/types";
import Board from "../Board";
import StatusBoard from "../StatusBoard";
import WatchedRow from "../WatchedRow";
import HomeBar, { type View } from "./HomeBar";
import HomeMap from "./HomeMap";

export default function HomeView({ uid, devices, watches, links, marks, selected, onSelect, onApp, onAsk, now, settingUp }: {
  uid: string; devices: Device[]; watches: Watch[]; links: Link[]; marks?: Map<string, Need[]>; selected: string | null;
  onSelect: (id: string) => void; onApp?: (id: string, svcId: string) => void; onAsk: (q: string) => void; now: number;
  settingUp: boolean;
}) {
  const [view, setView] = useState<View>("map");
  const [filter, setFilter] = useState<Filter>(NO_FILTER);
  useEffect(() => { try { const v = localStorage.getItem("nl_view"); if (v === "list" || v === "board") setView(v); } catch { /* default */ } }, []);
  // the chat's context strip asked to see a device: the map shows it
  const show = useFollowed().show;
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!show) return;
    setView("map");
    // after the pane switch has painted: bring the map itself on screen (on a phone it sits below the Needs list)
    const t = setTimeout(() => box.current?.querySelector(".homemap")?.scrollIntoView({ block: "center",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }), 80);
    return () => clearTimeout(t);
  }, [show]);
  const pick = (v: View) => { setView(v); try { localStorage.setItem("nl_view", v); } catch { /* this visit */ } };
  const names = usePlaces(uid);
  const places = useMemo(() => placesOf(devices, names), [devices, names]);
  const shown = useMemo(() => applyFilter(filter, devices, marks), [filter, devices, marks]);
  const shownWatches = useMemo(() => applyToWatches(filter, watches), [filter, watches]);
  return (
    <div className="homeview" data-tour="map" ref={box}>
      {(devices.length > 0 || watches.length > 0 || filtering(filter)) && <HomeBar devices={devices} watches={watches}
        places={places} filter={filter} onFilter={setFilter} view={view} onView={pick} />}
      {devices.length > 0 && shown.length === 0
        ? <p className="small muted">Nothing here matches.{" "}
            <button className="linkish small" onClick={() => setFilter(NO_FILTER)}>Show everything</button></p>
        : view === "board" && devices.length > 0
          ? <StatusBoard uid={uid} devices={shown} watches={filtering(filter) ? shownWatches : watches} now={now} onSelect={onSelect} />
        : view === "list" || devices.length === 0
          ? <Board devices={shown} selected={selected} onSelect={onSelect} marks={marks} settingUp={settingUp} />
          : <HomeMap uid={uid} devices={shown} links={links} marks={marks} selected={selected} onSelect={onSelect}
              onApp={onApp} onAsk={onAsk} now={now} favorites={filter.favorites} />}
      {view !== "board" && <WatchedRow watches={filtering(filter) ? shownWatches : watches} now={now} onAsk={onAsk} />}
    </div>
  );
}
