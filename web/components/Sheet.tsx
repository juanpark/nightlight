"use client";
// A panel (Trust, Activity, Add a device…) floating over the home from the right. The map stays where it was
// underneath; Esc or the close button puts the person back exactly there.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Close } from "@/src/components/icons";

export default function Sheet({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const back = document.activeElement as HTMLElement | null; // focus returns to what opened it
    ref.current?.focus();
    // what opened it may be gone (a menu item): then the More button, which leads back to it
    return () => (back?.isConnected ? back : document.querySelector<HTMLElement>("[data-tour=more]"))?.focus();
  }, [label]);
  // On a phone the sheet fills the screen: everything behind it is out of reach until it closes.
  const [phone, setPhone] = useState(false);
  useEffect(() => {
    const m = window.matchMedia("(max-width: 900px)");
    const on = () => setPhone(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  useEffect(() => {
    if (!phone) return;
    const behind = [...document.querySelectorAll<HTMLElement>(".shell > .top, .main > .left, .main > .right, .shell > .pane-tabs")];
    behind.forEach((el) => el.setAttribute("inert", ""));
    return () => behind.forEach((el) => el.removeAttribute("inert"));
  }, [phone]);
  return (
    <div ref={ref} className="sheet" role="dialog" aria-modal={phone || undefined} aria-label={label} tabIndex={-1}
      onKeyDown={(e) => { if (e.key === "Escape" && !e.defaultPrevented) onClose(); }}>
      <button className="sheet-close" onClick={onClose} aria-label={`Close ${label}`} title="Close">
        <Close size={18} aria-hidden /></button>
      <div className="sheet-body">{children}</div>
    </div>
  );
}
