import { AppGate } from "@/src/components/landing/AppGate";
import { DayHero } from "@/src/components/landing/day/DayHero";

// Daytime variant of the landing hero, kept beside the night one at "/".
export default function DayPage() {
  return (
    <AppGate>
      <DayHero />
    </AppGate>
  );
}
