import { AppGate } from "@/src/components/landing/AppGate";
import { Landing } from "@/src/components/landing/Landing";

// "/" is the landing page and sign-in in one: rendered on the server, and
// replaced by the app once someone is signed in.
export default function Page() {
  return (
    <AppGate>
      <Landing />
    </AppGate>
  );
}
