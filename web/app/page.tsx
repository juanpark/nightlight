import { AppGate } from "@/src/components/landing/AppGate";
import { GlowLanding } from "@/src/components/landing/glow/GlowLanding";

// "/" is the landing page and sign-in in one: one night in a clay dollhouse,
// told on scroll, and replaced by the app once someone is signed in.
export default function Page() {
  return (
    <AppGate>
      <GlowLanding />
    </AppGate>
  );
}
