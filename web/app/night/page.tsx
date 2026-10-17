import { AppGate } from "@/src/components/landing/AppGate";
import { NightLanding } from "@/src/components/landing/night/NightLanding";

// Swiss-grid night variant of the landing page.
export default function NightPage() {
  return (
    <AppGate>
      <NightLanding />
    </AppGate>
  );
}
