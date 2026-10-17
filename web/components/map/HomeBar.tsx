"use client";
// The bar above the map: Map or List, then what to show: a place (one per router), kinds of things, only what needs
// you, tags. Groups combine; within a group any choice matches. A chosen place can be renamed.
import { useState } from "react";
import { List, Map as MapIcon } from "lucide-react";
import { api } from "@/lib/api";
import { CATEGORIES, SAMPLE, UNKNOWN, categoryOf, filtering, NO_FILTER, type Category, type Filter, type Place } from "@/lib/homeFilter";
import type { Device, Watch } from "@/lib/types";

export type View = "map" | "list";

const toggle = <T,>(xs: T[], x: T) => xs.includes(x) ? xs.filter((y) => y !== x) : [...xs, x];

export default function HomeBar({ devices, watches, places, filter, onFilter, view, onView }: {
  devices: Device[]; watches: Watch[]; places: Place[]; filter: Filter; onFilter: (f: Filter) => void;
  view: View; onView: (v: View) => void;
}) {
  const [naming, setNaming] = useState<string | null>(null);
  const [name, setName] = useState("");
  const kinds = (Object.keys(CATEGORIES) as Category[]).filter((c) => devices.some((d) => categoryOf(d) === c));
  const tags = [...new Set([...devices, ...watches].flatMap((d) => d.tags ?? []))].sort();
  // "Sample" separates the sample home from your own devices, so it only helps when both are on the map
  if (devices.some((d) => d.realm !== "real") && devices.some((d) => d.realm === "real")) tags.push("Sample");
  const chosen = places.find((p) => p.id === filter.place);
  const renamable = chosen && chosen.id !== SAMPLE && chosen.id !== UNKNOWN;
  async function save() {
    if (chosen && name.trim()) await api("POST", `/api/places/${chosen.id}`, { name: name.trim() }).catch(() => {});
    setNaming(null);
  }
  return (
    <div className="homebar">
      <div className="mode-switch view-switch" role="radiogroup" aria-label="Show your home as">
        <button role="radio" aria-checked={view === "map"} className={view === "map" ? "on" : ""} onClick={() => onView("map")}>
          <MapIcon size={14} /> Map</button>
        <button role="radio" aria-checked={view === "list"} className={view === "list" ? "on" : ""} onClick={() => onView("list")}>
          <List size={14} /> List</button>
      </div>
      {places.length > 1 && (
        <div className="chips" role="group" aria-label="Place">
          <button className={!filter.place ? "on" : ""} onClick={() => onFilter({ ...filter, place: null })}>All places</button>
          {places.map((p) => (
            <button key={p.id} className={filter.place === p.id ? "on" : ""} aria-pressed={filter.place === p.id}
              onClick={() => onFilter({ ...filter, place: filter.place === p.id ? null : p.id })}>{p.name}</button>))}
          {renamable && naming !== chosen.id && (
            <button className="linkish small" onClick={() => { setName(chosen.named ? chosen.name : ""); setNaming(chosen.id); }}>
              Name this place</button>)}
          {renamable && naming === chosen.id && (
            <form className="place-name" onSubmit={(e) => { e.preventDefault(); save(); }}>
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoFocus
                placeholder="e.g. Home, Office, Mum's" aria-label="Place name" />
              <button className="primary small">Save</button>
              <button type="button" className="small" onClick={() => setNaming(null)}>Cancel</button>
            </form>)}
        </div>)}
      {kinds.length > 1 && (
        <div className="chips" role="group" aria-label="Kind">
          {kinds.map((c) => (
            <button key={c} className={filter.kinds.includes(c) ? "on" : ""} aria-pressed={filter.kinds.includes(c)}
              onClick={() => onFilter({ ...filter, kinds: toggle(filter.kinds, c) })}>{CATEGORIES[c]}</button>))}
        </div>)}
      <div className="chips" role="group" aria-label="Show">
        <button className={filter.needsMe ? "on" : ""} aria-pressed={filter.needsMe}
          onClick={() => onFilter({ ...filter, needsMe: !filter.needsMe })}>Only what needs me</button>
        {tags.map((t) => (
          <button key={t} className={filter.tags.includes(t) ? "on" : ""} aria-pressed={filter.tags.includes(t)}
            onClick={() => onFilter({ ...filter, tags: toggle(filter.tags, t) })}>{t}</button>))}
        {filtering(filter) && <button className="linkish small" onClick={() => onFilter(NO_FILTER)}>Show everything</button>}
      </div>
    </div>
  );
}
