// Server-only: builds the POSIX sh scripts behind /install.sh and /uninstall.sh. Both download the helper from this
// same origin and check it against the sha256 of the exact file this server serves, computed per request.
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

const HELPER = join(process.cwd(), "public", "nightlight_helper.py");
const URL_RE = /^https?:\/\/[A-Za-z0-9.-]+(:[0-9]{1,5})?(\/[A-Za-z0-9._~\/-]*)?$/;

/** Single-quote a value for sh. Values are also validated, so this is a second fence. */
const sq = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`;

/** The origin people reached us on (Cloud Run sits behind a proxy), falling back to the request URL. */
function originOf(req: Request): string {
  const h = req.headers;
  const host = h.get("x-forwarded-host")?.split(",")[0].trim() || h.get("host") || "";
  const proto = h.get("x-forwarded-proto")?.split(",")[0].trim() || new URL(req.url).protocol.replace(":", "");
  const guess = `${proto}://${host}`;
  return URL_RE.test(guess) ? guess : new URL(req.url).origin;
}

const PRELUDE = `
say() { printf '%s\\n' "$*"; }
fail() { printf 'Nightlight: %s\\n' "$*" >&2; exit 1; }

need_python() {
  command -v python3 >/dev/null 2>&1 || fail "this needs Python 3.8 or newer (python3). Please install it, then run the line again."
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \\
    || fail "this needs Python 3.8 or newer; this device has $(python3 -V 2>&1). Please update Python, then run the line again."
}

fetch_helper() {
  TMP=$(mktemp -d 2>/dev/null || mktemp -d -t nightlight)
  trap 'rm -rf "$TMP"' EXIT
  trap 'exit 130' INT TERM
  HELPER="$TMP/nightlight_helper.py"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --proto '=https,http' -o "$HELPER" "$HELPER_URL" || fail "couldn't download the helper. Check the internet connection and try again."
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$HELPER" "$HELPER_URL" || fail "couldn't download the helper. Check the internet connection and try again."
  else
    fail "this needs curl or wget to download the helper."
  fi
  GOT=$(python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$HELPER")
  [ "$GOT" = "$HELPER_SHA256" ] || fail "the downloaded helper didn't match its checksum, so nothing was installed. Please try again."
}

# The script itself arrives on stdin (curl | sh), so the helper must not read from it: give it the terminal if
# there is one, otherwise nothing.
helper() {
  if (: </dev/tty) 2>/dev/null; then
    python3 "$HELPER" "$@" </dev/tty
  else
    python3 "$HELPER" "$@" </dev/null
  fi
}
`;

type Built = { status: number; body: string };

async function build(req: Request, main: (vars: string) => string): Promise<Built> {
  let file: Buffer;
  try {
    file = await readFile(HELPER);
  } catch {
    return { status: 503, body: "The Nightlight helper isn't available on this server right now. Please try again later.\n" };
  }
  const apiUrl = process.env.API_URL ?? "http://localhost:8080";
  if (!URL_RE.test(apiUrl)) return { status: 503, body: "This server's API address isn't set up correctly.\n" };
  const origin = originOf(req);
  const vars = [
    `API_URL=${sq(apiUrl)}`,
    `WEB_URL=${sq(origin)}`,
    `HELPER_URL=${sq(`${origin}/nightlight_helper.py`)}`,
    `HELPER_SHA256=${sq(createHash("sha256").update(file).digest("hex"))}`,
  ].join("\n");
  return { status: 200, body: `#!/bin/sh\n${main(vars)}` };
}

export function installScript(req: Request) {
  return build(req, (vars) => `# Nightlight: add this device. Usage: curl -fsSL <web>/install.sh | sh -s -- [CODE]
# With a code from the web app it joins your account directly; without one it shows a code to approve in the app.
# Everything runs inside main, which is called on the last line, so a cut-off download runs nothing.
set -eu
${vars}
${PRELUDE}
main() {
  CODE="\${1:-}"
  if [ -n "$CODE" ]; then
    printf '%s' "$CODE" | grep -Eq '^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$' \\
      || fail "that code doesn't look right. It should look like ABCD-1234. Copy the line from the web app again."
  fi
  need_python
  say "Nightlight: downloading the helper…"
  fetch_helper
  if [ -n "$CODE" ]; then
    helper enrol "$API_URL" "$CODE"
  elif helper status 2>/dev/null | grep -q '^Joined as device'; then
    say "Nightlight: this device is already on your map; updating the helper."
    UPDATED=1
  else
    helper pair "$API_URL" --web "$WEB_URL"
  fi
  helper install
  say ""
  if [ -n "\${UPDATED:-}" ]; then say "Updated. Nightlight keeps running in the background."; return 0; fi
  say "Your device is on its way to your Nightlight map."
  say "To remove it later: curl -fsSL $WEB_URL/uninstall.sh | sh"
}

main "$@"
`);
}

export function uninstallScript(req: Request) {
  return build(req, (vars) => `# Nightlight: remove the helper from this device. Usage: curl -fsSL <web>/uninstall.sh | sh
# It stops the background service, deletes the helper's files and tells Nightlight to forget this device's key.
set -eu
${vars}
${PRELUDE}
main() {
  need_python
  fetch_helper
  helper uninstall
  say ""
  say "Nightlight has been removed from this device."
}

main "$@"
`);
}

export async function scriptResponse(built: Promise<Built>) {
  const { status, body } = await built;
  return new Response(body, {
    status,
    headers: {
      "Content-Type": status === 200 ? "text/x-shellscript; charset=utf-8" : "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
