"use client";
// On a phone, opening a device lists its apps in a sheet from the bottom instead of growing its card on the map.
import { useEffect } from "react";
import { Close as X } from "@/src/components/icons";
import { appOrder } from "@/lib/apps";
import { useServices } from "@/lib/data";
import type { Device } from "@/lib/types";
import { appIcon, deviceIcon } from "./kinds";

export default function AppSheet({ uid, device: d, onApp, onOpen, onClose }: {
  uid: string; device: Device; onApp: (id: string, svcId: string) => void; onOpen: (id: string) => void;
  onClose: () => void;
}) {
  const services = appOrder(useServices(uid, d.id), d.favoriteApps ?? []);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const Icon = deviceIcon(d);
  return (
    <>
      <div className="sheet-scrim" onClick={onClose} />
      <div className="app-sheet" role="dialog" aria-label={`Apps on ${d.name}`}>
        <div className="app-sheet-head">
          <span className={`dicon ${d.status}`}><Icon size={18} /></span>
          <strong>{d.name}</strong>
          <span style={{ flex: 1 }} />
          <button onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div className="app-sheet-list">
          {services.map((s) => {
            const AppIcon = appIcon(s);
            return (
              <button key={s.id} className={`app-row ${s.status ?? "ok"}`} onClick={() => onApp(d.id, s.id)}>
                <AppIcon size={16} aria-hidden /><span className="app-row-name">{s.name}</span>
                <span className={`dot ${s.status ?? "ok"}`} aria-label={s.status ?? "ok"} />
              </button>);
          })}
        </div>
        <button className="linkish small" onClick={() => onOpen(d.id)}>Everything about the {d.name}</button>
      </div>
    </>
  );
}
