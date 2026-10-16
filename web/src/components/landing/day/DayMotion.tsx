"use client";

import { useRef, type ReactNode } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";

gsap.registerPlugin(useGSAP);

// All the motion on the lit-room hero, with GSAP:
// - an opening around the mascot, which is there from the start: the room's
//   light comes up, the machines settle onto their plinths and their status lights come on one by one, as if just checked;
// - the camera follows the pointer (--mx/--my) and the mascot's eyes look at
//   it (--lx/--ly), each with its own weight; the mascot itself stays still;
// - the mascot blinks now and then.
// Under reduced motion everything is shown at rest; touch screens get the
// opening and the blinking but no pointer camera.
export function DayMotion({ className, id, children }: { className?: string; id?: string; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const el = ref.current;
      if (!el) return;
      const mm = gsap.matchMedia();

      mm.add(
        { calm: "(prefers-reduced-motion: reduce)", fine: "(pointer: fine)" },
        (ctx) => {
          el.dataset.motion = "on";
          const { calm, fine } = ctx.conditions as { calm: boolean; fine: boolean };
          if (calm) return;

          // Opening
          const q = gsap.utils.selector(el);
          gsap
            .timeline({ defaults: { ease: "power3.out" } })
            .from(q("[data-anim='light']"), { opacity: 0, duration: 1.6, ease: "power2.inOut" }, 0)
            .from(q("[data-anim='device']"), { y: -22, opacity: 0, duration: 0.9, stagger: 0.14 }, 0.45)
            .from(
              q("[data-anim='led']"),
              { opacity: 0, scale: 0.3, transformOrigin: "50% 50%", duration: 0.5, ease: "back.out(2)", stagger: 0.32 },
              1.25,
            );

          // Blinking, at uneven intervals, sometimes twice.
          const eyes = q("[data-part='eye']");
          let next: gsap.core.Tween | undefined;
          const blink = () => {
            const twice = Math.random() < 0.25;
            gsap.to(eyes, {
              scaleY: 0.08,
              transformOrigin: "50% 60%",
              duration: 0.07,
              ease: "power2.in",
              yoyo: true,
              repeat: twice ? 3 : 1,
            });
            next = gsap.delayedCall(gsap.utils.random(2.6, 6.5), blink);
          };
          next = gsap.delayedCall(2.4, blink);

          if (!fine) return () => next?.kill();

          // Pointer: a slow, weighted camera and quicker eyes.
          const eyeBox = el.querySelector('[data-part="eyes"]');
          const camX = gsap.quickTo(el, "--mx", { duration: 1.4, ease: "power3" });
          const camY = gsap.quickTo(el, "--my", { duration: 1.4, ease: "power3" });
          const lookX = gsap.quickTo(el, "--lx", { duration: 0.45, ease: "power3" });
          const lookY = gsap.quickTo(el, "--ly", { duration: 0.45, ease: "power3" });

          const move = (e: PointerEvent) => {
            camX((e.clientX / innerWidth) * 2 - 1);
            camY((e.clientY / innerHeight) * 2 - 1);
            if (!eyeBox) return;
            // Direction from the eyes to the pointer, full strength from ~300px away.
            const r = eyeBox.getBoundingClientRect();
            const dx = (e.clientX - (r.left + r.width / 2)) / 300;
            const dy = (e.clientY - (r.top + r.height / 2)) / 300;
            const k = Math.max(1, Math.hypot(dx, dy));
            lookX(dx / k);
            lookY(dy / k);
          };
          const leave = () => {
            camX(0);
            camY(0);
            lookX(0);
            lookY(0);
          };
          addEventListener("pointermove", move, { passive: true });
          document.documentElement.addEventListener("pointerleave", leave);
          return () => {
            next?.kill();
            removeEventListener("pointermove", move);
            document.documentElement.removeEventListener("pointerleave", leave);
          };
        },
      );
      return () => mm.revert();
    },
    { scope: ref },
  );

  return (
    <main ref={ref} id={id} className={className} data-motion="pending">
      {children}
    </main>
  );
}
