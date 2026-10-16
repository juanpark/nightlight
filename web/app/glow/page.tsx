import { AppGate } from "@/src/components/landing/AppGate";
import { GlowLanding } from "@/src/components/landing/glow/GlowLanding";

// 3D variant of the landing page: one night in a clay dollhouse, told on scroll.
export default function GlowPage() {
  return (
    <AppGate>
      <GlowLanding />
    </AppGate>
  );
}
