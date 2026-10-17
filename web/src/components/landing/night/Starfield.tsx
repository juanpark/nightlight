"use client";

import { useEffect, useRef } from "react";

// A quiet field of stars behind the footer. Each star twinkles on its own
// clock and shifts a little with the pointer (nearer stars shift more). It only
// draws while on screen, and under reduced motion it draws once and stops.
export function Starfield({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    type Star = { x: number; y: number; r: number; z: number; t: number; s: number };
    let stars: Star[] = [];
    let w = 0;
    let h = 0;
    let px = 0;
    let py = 0;
    let ox = 0;
    let oy = 0;
    let raf = 0;
    let visible = false;

    const size = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = Math.round((w * h) / 7000);
      stars = Array.from({ length: n }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        z: Math.random(),
        r: 0.4 + Math.random() * 1.1,
        t: Math.random() * Math.PI * 2,
        s: 0.4 + Math.random() * 1.4,
      }));
    };

    const draw = (time: number) => {
      ox += (px - ox) * 0.05;
      oy += (py - oy) * 0.05;
      ctx.clearRect(0, 0, w, h);
      for (const st of stars) {
        const a = still ? 0.6 : 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(st.t + (time / 1000) * st.s));
        const x = st.x - ox * (6 + st.z * 26);
        const y = st.y - oy * (6 + st.z * 26);
        ctx.globalAlpha = a * (0.45 + st.z * 0.55);
        ctx.fillStyle = st.z > 0.92 ? "#fdd83a" : "#efebe3";
        ctx.beginPath();
        ctx.arc(x, y, st.r * (0.7 + st.z * 0.6), 0, Math.PI * 2);
        ctx.fill();
      }
      if (!still && visible) raf = requestAnimationFrame(draw);
    };

    const move = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect();
      px = (e.clientX - r.left) / r.width - 0.5;
      py = (e.clientY - r.top) / r.height - 0.5;
    };

    size();
    draw(0);
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      cancelAnimationFrame(raf);
      if (visible && !still) raf = requestAnimationFrame(draw);
    });
    io.observe(canvas);
    const ro = new ResizeObserver(() => {
      size();
      draw(performance.now());
    });
    ro.observe(canvas);
    window.addEventListener("pointermove", move, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
      ro.disconnect();
      window.removeEventListener("pointermove", move);
    };
  }, []);

  return <canvas ref={ref} className={className} aria-hidden="true" />;
}
