"use client";
// The sample home's label in the header: always says the devices are simulated, and opens a short note with the way
// to try Nightlight on your own computer.
import { useEffect, useRef, useState } from "react";

export default function SamplePill({ onTry }: { onTry: () => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="sample" ref={box}>
      <button className="sample-pill" aria-expanded={open} aria-controls="sample-note" onClick={() => setOpen(!open)}
        data-tour="try-own">
        <span className="dot sample" aria-hidden /><span>Sample<span className="sample-long"> home · simulated</span></span></button>
      {open && (
        <div id="sample-note" className="sample-note" role="dialog" aria-label="About the sample home">
          <p>These devices are pretend, so you can try fixes safely. Nothing real is touched.</p>
          <p className="muted small">Your own computer takes about two minutes to add.</p>
          <button className="small" onClick={() => { setOpen(false); onTry(); }}>Try it on your own computer</button>
        </div>
      )}
    </div>
  );
}
