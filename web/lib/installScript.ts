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

// Python for the helper. A device with python3 >= 3.8 uses it, as before. One without (or a Mac with only Apple's
// /usr/bin/python3 stub, which would pop up the developer-tools installer) gets Nightlight's own CPython from
// python-build-standalone: the same release the Mac installer bundles (scripts/build_mac_pkg.sh), pinned by sha256
// from that release's SHA256SUMS, unpacked into the helper's own folder (APP_DIR in the helper) and never on the
// system's PATH. No sudo, no package manager. The helper writes its service with the Python that runs `install`
// (sys.executable), so the background service keeps using the same interpreter; uninstall.sh deletes it.
// To move to a newer release, change the tag, the version and every digest together (and the Mac pkg's too).
const PBS_TAG = "20260929";
const PBS_PY = "3.12.14";
// triple -> [sha256, approximate download size in MB]
const PBS: Record<string, readonly [string, number]> = {
  "x86_64-unknown-linux-gnu": ["06c90b93f419b63371c18f20fed0558a1a901f6518c3c24f755077e048447e7f", 67],
  "aarch64-unknown-linux-gnu": ["9c797cf657f6dced51d3e74eeabd7c1ca742d5bf10f66080a290e424ced8edaf", 52],
  "armv7-unknown-linux-gnueabihf": ["1b70b4ac5604b39c3884f2e2b66da217abba59af71e89e238d221f568548ebe8", 39],
  "aarch64-apple-darwin": ["de6b8f94fa765639b423ea353ab340669704c7186f96ee3cab389dcfde770c3c", 25],
  "x86_64-apple-darwin": ["f51ec8a7fa0ede129a5e2e942a2a453ba4830adaca2289da4449390e42443292", 25],
};

const pbs = (triple: string) => `T=${triple}; WANT=${PBS[triple][0]}; MB=${PBS[triple][1]}`;

const PRELUDE = `
say() { printf '%s\\n' "$*"; }
fail() { printf 'Nightlight: %s\\n' "$*" >&2; exit 1; }

PBS_TAG=${PBS_TAG}
PBS_PY=${PBS_PY}
# The helper's own folder (APP_DIR in nightlight_helper.py); Nightlight's own Python lives in python/ inside it.
if [ "$(uname -s)" = Darwin ]; then APP_DIR="$HOME/Library/Application Support/Nightlight"; else APP_DIR="$HOME/.local/share/nightlight"; fi
BUNDLED="$APP_DIR/python/bin/python3"
PY=
# This script's own private folder: always a fresh mktemp -d (mode 700), never a value from the environment.
NL_TMP=

workdir() {
  [ -n "$NL_TMP" ] && return 0
  NL_TMP=$(mktemp -d 2>/dev/null || mktemp -d -t nightlight) && [ -d "$NL_TMP" ] && [ ! -L "$NL_TMP" ] \\
    || fail "couldn't create a private temporary folder."
  chmod 700 "$NL_TMP"
  trap 'rm -rf "$NL_TMP"' EXIT
  trap 'exit 130' INT TERM
}

# sha256 without Python (it may not be here yet).
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
  elif command -v openssl >/dev/null 2>&1; then openssl dgst -sha256 "$1" | sed 's/^.*= *//'
  else fail "this needs sha256sum, shasum or openssl to check what it downloads."
  fi
}

# download URL FILE PROTOCOLS
download() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --proto "$3" -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$2" "$1"
  else
    fail "this needs curl or wget to download the helper."
  fi
}

# python3 on PATH, new enough, and not Apple's stub (without the developer tools it only offers to install them).
system_python_ok() {
  P=$(command -v python3 2>/dev/null) || return 1
  if [ "$(uname -s)" = Darwin ] && [ "$P" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; then return 1; fi
  "$P" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1
}

no_own_python() {
  fail "this needs Python 3.8 or newer, and Nightlight can't bring its own Python for $1. $2 Then run the line again."
}

get_python() {
  OS=$(uname -s); ARCH=$(uname -m)
  case "$OS-$ARCH" in
    Linux-*)
      if ls /lib/ld-musl-* >/dev/null 2>&1; then
        no_own_python "this system (it uses musl, like Alpine Linux)" "Add Python with: sudo apk add python3 (or, as root: apk add python3)."
      fi
      case "$ARCH" in
        x86_64|amd64) ${pbs("x86_64-unknown-linux-gnu")} ;;
        aarch64|arm64)
          # A 64-bit kernel with a 32-bit system (older Raspberry Pi OS) runs only 32-bit programs.
          if [ "$(getconf LONG_BIT 2>/dev/null)" = 32 ]; then ${pbs("armv7-unknown-linux-gnueabihf")}; else ${pbs("aarch64-unknown-linux-gnu")}; fi ;;
        armv7l|armv7*|armv8l) ${pbs("armv7-unknown-linux-gnueabihf")} ;;
        *) no_own_python "this processor ($ARCH)" "Add Python with the system's software installer (for example: sudo apt install python3)." ;;
      esac ;;
    Darwin-arm64) ${pbs("aarch64-apple-darwin")} ;;
    Darwin-x86_64) ${pbs("x86_64-apple-darwin")} ;;
    *) no_own_python "this system ($OS $ARCH)" "Add Python 3 from python.org or the system's software installer." ;;
  esac
  [ -L "$APP_DIR" ] && fail "$APP_DIR is a symbolic link, so nothing was installed there."
  mkdir -p "$APP_DIR" && chmod 700 "$APP_DIR" || fail "couldn't create $APP_DIR."
  workdir
  say "Nightlight: this device has no Python it can use, so Nightlight is fetching its own (about $MB MB, once)."
  say "            It stays inside Nightlight's folder and changes nothing else on this device."
  NAME="cpython-$PBS_PY+$PBS_TAG-$T-install_only.tar.gz"
  download "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/cpython-$PBS_PY%2B$PBS_TAG-$T-install_only.tar.gz" "$NL_TMP/python.tar.gz" '=https' \\
    || fail "couldn't download Python ($NAME). Check the internet connection and try again."
  [ "$(sha256_of "$NL_TMP/python.tar.gz")" = "$WANT" ] || fail "the downloaded Python didn't match its checksum, so nothing was installed. Please try again."
  NEW="$APP_DIR/.python-new"
  rm -rf "$NEW" && mkdir "$NEW" || fail "couldn't write to $APP_DIR."
  tar -xzf "$NL_TMP/python.tar.gz" -C "$NEW" || { rm -rf "$NEW"; fail "couldn't unpack Python into $APP_DIR (is the disk full?)."; }
  # Not needed to run the helper (as in the Mac installer): headers, docs, Tcl/Tk and the GUI, tests, IDLE, pip.
  P="$NEW/python"; L="$P/lib/python3.12"
  rm -rf "$P/include" "$P/share" "$P/lib/pkgconfig" "$P/lib"/itcl* "$P/lib"/tcl* "$P/lib"/thread* "$P/lib"/tk* \\
    "$P/lib"/libtcl* "$P/lib"/libtk* "$L/test" "$L/idlelib" "$L/tkinter" "$L/turtledemo" "$L/ensurepip" "$L/lib2to3" \\
    "$L"/site-packages/pip* "$L"/lib-dynload/_tkinter*
  "$NEW/python/bin/python3" -c 'import ssl, sqlite3' >/dev/null 2>&1 \\
    || { rm -rf "$NEW"; no_own_python "this device (its Python doesn't start here)" "Add Python with the system's software installer (for example: sudo apt install python3)."; }
  rm -rf "$APP_DIR/python" && mv "$NEW/python" "$APP_DIR/python" && rmdir "$NEW" || fail "couldn't put Python in $APP_DIR."
  PY="$BUNDLED"
}

# Nightlight's own Python when it already brought one (so an update keeps the interpreter the service runs on),
# otherwise the system's, otherwise fetch one.
need_python() {
  if [ -x "$BUNDLED" ] && "$BUNDLED" -c 'import sys' >/dev/null 2>&1; then PY="$BUNDLED"
  elif system_python_ok; then PY=$(command -v python3)
  else get_python
  fi
}

# Uninstall: after the helper has removed its own files, delete Nightlight's Python and the then-empty folder.
remove_own_python() {
  [ -L "$APP_DIR" ] && return 0
  if [ -d "$APP_DIR/python" ] && [ ! -L "$APP_DIR/python" ]; then rm -rf "$APP_DIR/python" && say "Removed Nightlight's own Python."; fi
  rm -rf "$APP_DIR/.python-new"
  rmdir "$APP_DIR" 2>/dev/null || true
}

fetch_helper() {
  workdir
  HELPER="$NL_TMP/nightlight_helper.py"
  download "$HELPER_URL" "$HELPER" '=https,http' || fail "couldn't download the helper. Check the internet connection and try again."
  [ "$(sha256_of "$HELPER")" = "$HELPER_SHA256" ] || fail "the downloaded helper didn't match its checksum, so nothing was installed. Please try again."
}

# The script itself arrives on stdin (curl | sh), so the helper must not read from it: give it the terminal if
# there is one, otherwise nothing.
helper() {
  if (: </dev/tty) 2>/dev/null; then
    "$PY" "$HELPER" "$@" </dev/tty
  else
    "$PY" "$HELPER" "$@" </dev/null
  fi
}

# The helper puts a short \`nightlight\` command in ~/.local/bin. Many systems only add that folder to PATH at the
# next login (and only if it existed then), so right after a first install the name isn't found. On Linux, where
# install has just used sudo for the service, link it from /usr/local/bin too (no new password prompt: sudo -n);
# otherwise say plainly how to run it.
LINK=/usr/local/bin/nightlight
link_command() {
  SHORT="$HOME/.local/bin/nightlight"
  [ -f "$SHORT" ] || return 0
  command -v nightlight >/dev/null 2>&1 && return 0
  if [ "$(uname -s)" = Linux ] && [ ! -e "$LINK" ] && [ ! -L "$LINK" ] && [ -d /usr/local/bin ]; then
    case ":$PATH:" in *:/usr/local/bin:*)
      # A failed link must not end the script (set -e): fall through to the note instead.
      if [ "$(id -u)" = 0 ]; then AS=; else AS="sudo -n"; fi
      if $AS ln -s "$SHORT" "$LINK" 2>/dev/null && command -v nightlight >/dev/null 2>&1; then return 0; fi ;;
    esac
  fi
  NOTE="The nightlight command works by name after you next log in. Until then use: ~/.local/bin/nightlight status"
}

unlink_command() {
  [ -L "$LINK" ] && [ "$(readlink "$LINK")" = "$HOME/.local/bin/nightlight" ] || return 0
  if [ "$(id -u)" = 0 ]; then rm -f "$LINK"; else sudo rm -f "$LINK" </dev/tty 2>/dev/null || sudo -n rm -f "$LINK" || true; fi
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
  elif helper joined 2>/dev/null; then
    say "Nightlight: this device is already on your map; updating the helper."
    UPDATED=1
  else
    helper pair "$API_URL" --web "$WEB_URL"
  fi
  helper install
  link_command
  say ""
  if [ -n "\${UPDATED:-}" ]; then
    say "Updated. Nightlight keeps running in the background."
  else
    say "Your device is on its way to your Nightlight map."
    say "To remove it later: curl -fsSL $WEB_URL/uninstall.sh | sh"
  fi
  if [ -n "\${NOTE:-}" ]; then say "$NOTE"; fi
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
  unlink_command
  remove_own_python
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
