// GET /uninstall.sh: removes the helper and its service, and revokes the device's key (see lib/installScript.ts).
import { scriptResponse, uninstallScript } from "@/lib/installScript";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(req: Request) {
  return scriptResponse(uninstallScript(req));
}
