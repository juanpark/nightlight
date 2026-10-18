import { AppGate } from "@/src/components/landing/AppGate";
import { MonoLanding } from "@/src/components/landing/mono/MonoLanding";

// "/" is the landing page and sign-in in one: the product shown at work on one sample home,
// replaced by the app once someone is signed in.
export default function Page() {
  return (
    <AppGate>
      <MonoLanding />
    </AppGate>
  );
}
