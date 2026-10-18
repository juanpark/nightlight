"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import type { View } from "./scene";
import s from "./Home.module.css";

gsap.registerPlugin(ScrollTrigger);

// The sample home as one map: the glow page's clay house, recoloured to this
// page's navy and star. As the section scrolls by, the light walks the wire
// room to room and the camera settles on the Pi in the attic, which is where
// "How a night goes" picks up. three.js loads only when the section comes near,
// and draws only while it is on screen. Phones and machines without WebGL get
// a still of the same view; reduced motion gets the scene, standing still.

const WHOLE: View = {
  tx: 0, ty: 12.6, tz: 0, zoom: 0.84, az: 30, el: 22, ox: 0, oy: 0,
  follow: 0, trail: 0, rings: 0, done: 0, lit: 0, orb: 0,
};
const ON_THE_PI: Partial<View> = { tx: 0, ty: 7.6, tz: -1, zoom: 1.3, az: 26, el: 24, ox: 0, oy: 0, follow: 0.15, rings: 1 };
const STILL: View = { ...WHOLE, ty: 6.2, zoom: 1.05, trail: 1, rings: 1 };

export function HouseMap() {
  const root = useRef<HTMLElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef<View>({ ...WHOLE });
  const [gl, setGl] = useState<"idle" | "on" | "off">("idle");

  useEffect(() => {
    const section = root.current;
    const el = canvas.current;
    if (!section || !el) return;
    if (!window.matchMedia("(min-width: 720px)").matches) return setGl("off");
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let api: { draw: (v: View, t: number) => void; dispose: () => void } | undefined;
    let live = true;
    let seen = false;
    let tl: gsap.core.Timeline | undefined;
    const frame = (time: number) => {
      if (seen) api?.draw(view.current, time);
    };

    const start = () => {
      import("./scene")
        .then(({ createScene }) => {
          if (!live) return;
          api = createScene(el, { calm, palette: "home" });
          gsap.ticker.add(frame);
          setGl("on");
          if (calm) {
            Object.assign(view.current, STILL);
            return;
          }
          const v = view.current;
          tl = gsap
            .timeline({
              defaults: { ease: "power2.inOut" },
              scrollTrigger: { trigger: section, start: "top 75%", end: "bottom 35%", scrub: 0.6 },
            })
            .to(v, { trail: 1, duration: 1, ease: "power1.inOut" }, 0)
            .to(v, { ty: 9, zoom: 1.1, follow: 0.4, duration: 0.5 }, 0)
            .to(v, { ...ON_THE_PI, duration: 0.5 }, 0.5);
        })
        .catch(() => live && setGl("off"));
    };

    // Load when the section is a screen or so away; draw only while it shows.
    const near = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting) return;
        near.disconnect();
        start();
      },
      { rootMargin: "200px 0px" },
    );
    const onScreen = new IntersectionObserver(([e]) => (seen = e.isIntersecting));
    near.observe(section);
    onScreen.observe(el);

    return () => {
      live = false;
      near.disconnect();
      onScreen.disconnect();
      tl?.scrollTrigger?.kill();
      tl?.kill();
      gsap.ticker.remove(frame);
      api?.dispose();
    };
  }, []);

  return (
    <section ref={root} id="map" className={s.map} data-gl={gl} aria-labelledby="map-title">
      <div className={s.mapHead}>
        <h2 id="map-title" className={s.h2} data-lines>
          Every machine,
          <br />
          room by room
        </h2>
        <p className={s.mapText}>
          One friendly map of your home. Tonight the light checks each machine in turn, and finds the Raspberry Pi in
          the attic almost out of space.
        </p>
      </div>
      <div className={s.mapStage}>
        <canvas ref={canvas} className={s.mapCanvas} aria-hidden="true" />
        <Image
          className={s.mapStill}
          src="/brand/house-night.webp"
          alt="The sample home drawn as a small house at night: a light has visited every room, and the attic, where the Raspberry Pi is, glows yellow."
          fill
          sizes="100vw"
        />
      </div>
    </section>
  );
}
