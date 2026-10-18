"use client";
// The bar above the map: Map or List; the two quick toggles (what needs you, favourites); then a menu each for kinds
// of things, places (one per router) and tags. Groups combine; within a menu any ticked choice matches. A chosen place
// can be renamed from its menu. Everything wraps onto a second line rather than scrolling out of sight.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Kinds, ListView as List, MapView as MapIcon, NeedsYou, Opens, Place as PlaceIcon, Star, StatusView, Tags,
  type IconType } from "@/src/components/icons";
import { api } from "@/lib/api";
import { CATEGORIES, SAMPLE, UNKNOWN, categoryOf, filtering, NO_FILTER, starred, type Category, type Filter,
  type Place } from "@/lib/homeFilter";
import type { Need } from "@/lib/needsYou";
import type { Device, Watch } from "@/lib/types";

export type View = "map" | "list" | "board";

const toggle = <T,>(xs: T[], x: T) => xs.includes(x) ? xs.filter((y) => y !== x) : [...xs, x];

/** "All types" / "Computers" / "Computers +1": what a menu is narrowing to, at a glance. */
const summary = (all: string, picked: string[]) =>
  picked.length === 0 ? all : picked.length === 1 ? picked[0] : `${picked[0]} +${picked.length - 1}`;

/** A filter menu: a pill that opens a short list below it. Closes on Escape, a click outside, or moving focus away. */
function Menu({ icon: Icon, label, active, name, children }: {
  icon: IconType; label: string; active: boolean; name: string; children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [toLeft, setToLeft] = useState(false); // opens leftwards when there is no room on the right of the home column
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    box.current?.querySelector<HTMLElement>(".fmenu-panel input, .fmenu-panel button")?.focus();
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="fmenu" ref={box} onBlur={(e) => { if (!box.current?.contains(e.relatedTarget as Node)) setOpen(false); }}>
      <button ref={button} className={`fpill ${active ? "on" : ""}`} aria-expanded={open} aria-haspopup="true"
        onClick={() => {
          const b = button.current?.getBoundingClientRect();
          const edge = button.current?.closest(".left")?.getBoundingClientRect().right ?? window.innerWidth;
          if (b) setToLeft(b.left + 240 > edge); // the panel is at least 220px wide
          setOpen(!open);
        }}>
        <Icon size={15} aria-hidden /> {label} <Opens className="fmenu-caret" size={11} aria-hidden />
      </button>
      {open && <div className={`fmenu-panel ${toLeft ? "to-left" : ""}`} role="group" aria-label={name}>{children}</div>}
    </div>
  );
}

export default function HomeBar({ devices, watches, places, filter, onFilter, view, onView, marks }: {
  devices: Device[]; watches: Watch[]; places: Place[]; filter: Filter; onFilter: (f: Filter) => void;
  view: View; onView: (v: View) => void; marks?: Map<string, Need[]>;
}) {
  const [naming, setNaming] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const kinds = (Object.keys(CATEGORIES) as Category[]).filter((c) => devices.some((d) => categoryOf(d) === c));
  const tags = [...new Set([...devices, ...watches].flatMap((d) => d.tags ?? []))].sort();
  // "Sample" separates the sample home from your own devices, so it only helps when both are on the map
  if (devices.some((d) => d.realm !== "real") && devices.some((d) => d.realm === "real")) tags.push("Sample");
  const chosen = places.find((p) => p.id === filter.place);
  const renamable = chosen && chosen.id !== SAMPLE && chosen.id !== UNKNOWN;
  async function save() {
    if (!chosen || !name.trim()) { setNaming(null); return; }
    setErr("");
    try { await api("POST", `/api/places/${chosen.id}`, { name: name.trim() }); setNaming(null); }
    catch { setErr("Couldn't save the name. Try again."); } // the draft stays for another try
  }
  return (
    <div className="homebar">
      {devices.length > 0 && <div className="mode-switch view-switch" role="radiogroup" aria-label="Show your home as" data-tour="view-switch">
        <button role="radio" aria-checked={view === "map"} className={view === "map" ? "on" : ""} onClick={() => onView("map")}>
          <MapIcon size={15} /> Map</button>
        <button role="radio" aria-checked={view === "list"} className={view === "list" ? "on" : ""} onClick={() => onView("list")}>
          <List size={15} /> List</button>
        <button role="radio" aria-checked={view === "board"} className={view === "board" ? "on" : ""} onClick={() => onView("board")}
          title="Every check as a ✓ ! ✗ line, from what devices last reported"><StatusView size={15} /> Status</button>
      </div>}

      <span className="hb-gap" aria-hidden />
      <div className="fgroup" role="group" aria-label="Show only">
        <button className={`fpill ${filter.needsMe ? "on" : ""}`} aria-pressed={filter.needsMe} aria-label="Only what needs me"
          onClick={() => onFilter({ ...filter, needsMe: !filter.needsMe })}>
          <NeedsYou size={15} aria-hidden /> <span className="fp-long">Only what needs me</span><span className="fp-short">Needs me</span></button>
        {(filter.favorites || devices.some(starred)) && (
          <button className={`fpill ${filter.favorites ? "on" : ""}`} aria-pressed={filter.favorites}
            onClick={() => onFilter({ ...filter, favorites: !filter.favorites })}>
            <Star className={filter.favorites ? "dstar" : undefined} size={15} weight={filter.favorites ? "fill" : undefined} aria-hidden /> Favorites</button>)}
      </div>

      {(kinds.length > 1 || places.length > 1 || tags.length > 0) && <div className="fgroup" role="group" aria-label="Narrow by">
        {kinds.length > 1 && (
          <Menu icon={Kinds} name="Types" active={filter.kinds.length > 0}
            label={summary("All types", filter.kinds.map((c) => CATEGORIES[c]))}>
            {kinds.map((c) => (
              <label key={c}>
                <input type="checkbox" checked={filter.kinds.includes(c)}
                  onChange={() => onFilter({ ...filter, kinds: toggle(filter.kinds, c) })} />
                {CATEGORIES[c]}<span className="fcount-quiet">{devices.filter((d) => categoryOf(d) === c).length}</span>
              </label>))}
            {filter.kinds.length > 0 && <button className="linkish small" onClick={() => onFilter({ ...filter, kinds: [] })}>
              All types</button>}
          </Menu>)}
        {places.length > 1 && (
          <Menu icon={PlaceIcon} name="Places" active={!!filter.place} label={chosen ? chosen.name : "All places"}>
            {[{ id: null, name: "All places", count: devices.length }, ...places].map((p) => (
              <label key={p.id ?? "all"}>
                <input type="radio" name="place" checked={filter.place === p.id}
                  onChange={() => onFilter({ ...filter, place: p.id })} />
                {p.name}<span className="fcount-quiet">{p.count}</span>
              </label>))}
            {renamable && naming !== chosen.id && (
              <button className="linkish small" onClick={() => { setName(chosen.named ? chosen.name : ""); setNaming(chosen.id); }}>
                Name this place</button>)}
            {renamable && naming === chosen.id && (
              <form className="place-name" onSubmit={(e) => { e.preventDefault(); save(); }}>
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoFocus
                  placeholder="e.g. Home, Office, Mum's" aria-label="Place name" />
                <button className="primary small">Save</button>
                <button type="button" className="small" onClick={() => { setNaming(null); setErr(""); }}>Cancel</button>
                {err && <span className="small" style={{ color: "var(--crit-ink)" }}>{err}</span>}
              </form>)}
          </Menu>)}
        {tags.length > 0 && (
          <Menu icon={Tags} name="Tags" active={filter.tags.length > 0} label={summary("Tags", filter.tags)}>
            {tags.map((t) => (
              <label key={t}>
                <input type="checkbox" checked={filter.tags.includes(t)}
                  onChange={() => onFilter({ ...filter, tags: toggle(filter.tags, t) })} />
                {t}
              </label>))}
          </Menu>)}
      </div>}

      {filtering(filter) && <button className="linkish small fclear" onClick={() => onFilter(NO_FILTER)}>Clear filters</button>}
    </div>
  );
}
