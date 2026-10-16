// GET /install.sh: the one line in "Add a device" pipes this into sh (see lib/installScript.ts).
import { installScript, scriptResponse } from "@/lib/installScript";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(req: Request) {
  return scriptResponse(installScript(req));
}
