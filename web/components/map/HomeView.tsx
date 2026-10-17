"use client";
// The home as a map (pan, zoom, lines between devices) or as a plain list of tiles, narrowed by the bar above it;
// Map or List is remembered here. Watched websites follow below with the filters that apply to them.
import { useMemo, useState } from "react";
import { usePlaces } from "@/lib/data";
import { applyFilter, applyToWatches, filtering, NO_FILTER, placesOf, type Filter } from "@/lib/homeFilter";
import type { Need } from "@/lib/needsYou";
import type { Device, Link, Watch } from "@/lib/types";
import Board from "../Board";
import WatchedRow from "../WatchedRow";
import HomeBar, { type View } from "./HomeBar";
import HomeMap from "./HomeMap";

const isPhone = () => typeof window !== "undefined" && window.matchMedia("(max-width: 700px)").matches;
const viewKey = () => isPhone() ? "nl_view_phone" : "nl_view";
function startView(): View {
  try { const v = localStorage.getItem(viewKey()); if (v === "map" || v === "list") return v; } catch { /* default */ }
  return isPhone() ? "list" : "map";
}

export default function HomeView({ uid, devices, watches, links, marks, selected, onSelect, onApp, onAsk, now, settingUp }: {
  uid: string; devices: Device[]; watches: Watch[]; links: Link[]; marks?: Map<string, Need[]>; selected: string | null;
  onSelect: (id: string) => void; onApp?: (id: string, svcId: string) => void; onAsk: (q: string) => void; now: number;
  settingUp: boolean;
}) {
  // Phones start on the list (the map is too small to read there) and remember their own choice, apart from a computer's.
  const [view, setView] = useState<View>(() => startView());
  const [filter, setFilter] = useState<Filter>(NO_FILTER);
  const pick = (v: View) => { setView(v); try { localStorage.setItem(viewKey(), v); } catch { /* this visit */ } };
  const names = usePlaces(uid);
  const places = useMemo(() => placesOf(devices, names), [devices, names]);
  const shown = useMemo(() => applyFilter(filter, devices, marks), [filter, devices, marks]);
  const shownWatches = useMemo(() => applyToWatches(filter, watches), [filter, watches]);
  return (
    <div className="homeview">
      {(devices.length > 0 || watches.length > 0 || filtering(filter)) && <HomeBar devices={devices} watches={watches}
        places={places} filter={filter} onFilter={setFilter} view={view} onView={pick} />}
      {devices.length > 0 && shown.length === 0
        ? <p className="small muted">Nothing here matches.{" "}
            <button className="linkish small" onClick={() => setFilter(NO_FILTER)}>Show everything</button></p>
        : view === "list" || devices.length === 0
          ? <Board devices={shown} selected={selected} onSelect={onSelect} marks={marks} settingUp={settingUp} />
          : <HomeMap uid={uid} devices={shown} links={links} marks={marks} selected={selected} onSelect={onSelect}
              onApp={onApp} onAsk={onAsk} now={now} favorites={filter.favorites} />}
      <WatchedRow watches={filtering(filter) ? shownWatches : watches} now={now} onAsk={onAsk} />
    </div>
  );
}
