import { AppGate } from "@/src/components/landing/AppGate";
import { HomeLanding } from "@/src/components/landing/home/HomeLanding";

// "/" is the landing page and sign-in in one: an editorial page about one sample home,
// replaced by the app once someone is signed in.
export default function Page() {
  return (
    <AppGate>
      <HomeLanding />
    </AppGate>
  );
}
