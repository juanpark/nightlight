// Copies the device helper into public/ so the web app can serve it at /nightlight_helper.py (the install script
// downloads it from the same origin and checks its sha256). The copy is not committed; helper/ is the source.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(web, "..", "helper", "nightlight_helper.py");
const dst = join(web, "public", "nightlight_helper.py");
if (existsSync(src)) {
  mkdirSync(dirname(dst), { recursive: true });
  copyFileSync(src, dst);
  console.log("copied helper/nightlight_helper.py -> public/");
} else if (!existsSync(dst)) {
  console.warn("helper/nightlight_helper.py not found; /install.sh will answer 503 until public/ has the helper");
}
