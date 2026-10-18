#!/usr/bin/env bash
# Build Nightlight.pkg: the no-Terminal way to add a Mac. It carries its own Python (python-build-standalone, checked
# against pinned sha256 digests), so nothing asks to install developer tools, and the helper. After the files are in
# place, the installer opens the browser on Nightlight's approval page; once the person clicks Approve the helper
# installs its background service as that person. Nothing listens on the network, so the firewall never asks.
#
#   bash scripts/build_mac_pkg.sh [--dry-run]
#     WEB_URL / API_URL   where the installed helper joins (default: production)
#     TEAM_ID             whose Developer ID certificates sign it (default: Juan's personal team)
#     NOTARY_PROFILE      notarytool keychain profile (default: nightlight-notary)
#     BUILD_DIR           output folder (default: build/mac, gitignored)
#
# --dry-run lays out the payload with placeholder runtimes and stops before downloading, signing or packaging.
# Without the Developer ID certificates (or the notary profile) it builds an unsigned package and says what to set up.
set -euo pipefail
cd "$(dirname "$0")/.."

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
WEB_URL=${WEB_URL:-https://nightlight-web-1032111130355.asia-northeast3.run.app}
API_URL=${API_URL:-https://nightlight-api-1032111130355.asia-northeast3.run.app}
TEAM_ID=${TEAM_ID:-FVN5HC592M}
NOTARY_PROFILE=${NOTARY_PROFILE:-nightlight-notary}
BUILD_DIR=${BUILD_DIR:-build/mac}
PKG_ID=com.nightlight.installer
VERSION=$(sed -n 's/^VERSION = "\([0-9.]*\)"$/\1/p' helper/nightlight_helper.py)

# python-build-standalone release 20260929 (CPython 3.12.14). Digests copied from that release's SHA256SUMS; a
# download that doesn't match is refused. To move to a newer release, change all three lines together.
PBS_TAG=20260929
PBS_PY=3.12.14
PBS_SHA_arm64=de6b8f94fa765639b423ea353ab340669704c7186f96ee3cab389dcfde770c3c
PBS_SHA_x86_64=f51ec8a7fa0ede129a5e2e942a2a453ba4830adaca2289da4449390e42443292

URL_RE='^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$'
for u in "$WEB_URL" "$API_URL"; do
  [[ $u =~ $URL_RE ]] || { echo "Not an https origin: $u" >&2; exit 1; }
done
[ -n "$VERSION" ] || { echo "No VERSION in helper/nightlight_helper.py" >&2; exit 1; }

STAGE="$BUILD_DIR/stage"
APP="$STAGE/root/Library/Application Support/Nightlight"
rm -rf "$STAGE"
mkdir -p "$APP/runtime" "$STAGE/scripts" "$BUILD_DIR/cache"

sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }

# One CPython per architecture, unpacked to runtime/<arm64|x86_64>/python and trimmed to what the helper can use.
runtime() {
  local arch=$1 triple=$2 want=$3
  local name="cpython-${PBS_PY}+${PBS_TAG}-${triple}-install_only.tar.gz"
  local tgz="$BUILD_DIR/cache/$name" out="$APP/runtime/$arch"
  if [ "$DRY" = 1 ]; then
    mkdir -p "$out/python/bin"
    printf '#!/bin/sh\necho "placeholder for %s"\n' "$name" > "$out/python/bin/python3.12"
    chmod 755 "$out/python/bin/python3.12"
    return
  fi
  if [ ! -f "$tgz" ] || [ "$(sha256 "$tgz")" != "$want" ]; then
    curl -fsSL --proto '=https' -o "$tgz.part" \
      "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${name/+/%2B}"
    mv "$tgz.part" "$tgz"
  fi
  local got
  got=$(sha256 "$tgz")
  if [ "$got" != "$want" ]; then
    rm -f "$tgz"
    echo "Checksum mismatch for $name: got $got, expected $want. Refusing to package it." >&2
    exit 1
  fi
  mkdir -p "$out"
  tar -xzf "$tgz" -C "$out"
  local py="$out/python" lib="$out/python/lib/python3.12"
  # Not needed to run the helper: headers, docs, Tcl/Tk and the GUI modules, pip, the 2to3 and IDLE tools, and the
  # shared libpython (the python3.12 binary is statically linked).
  rm -rf "$py/include" "$py/share" "$py/lib/pkgconfig" "$py/lib"/itcl* "$py/lib"/tcl* "$py/lib"/thread* "$py/lib"/tk* \
    "$py/lib"/libtcl* "$py/lib/libpython3.12.dylib" \
    "$lib"/{test,idlelib,tkinter,turtledemo,turtle.py,ensurepip,lib2to3,config-3.12-darwin} \
    "$lib"/site-packages/pip* "$lib"/lib-dynload/_tkinter*
  find "$py/bin" -mindepth 1 ! -name python3.12 ! -name python3 ! -name python -exec rm -f {} +
}
runtime arm64 aarch64-apple-darwin "$PBS_SHA_arm64"
runtime x86_64 x86_64-apple-darwin "$PBS_SHA_x86_64"

install -m 0644 helper/nightlight_helper.py "$APP/nightlight_helper.py"
[ -f helper/nightlight_helper.py.sig ] && install -m 0644 helper/nightlight_helper.py.sig "$APP/nightlight_helper.py.sig"

# Where this build joins, read by postinstall. Checked above, so plain single quotes are safe.
printf "API_URL='%s'\nWEB_URL='%s'\n" "$API_URL" "$WEB_URL" > "$STAGE/scripts/nightlight.conf"
cat > "$STAGE/scripts/postinstall" <<'SH'
#!/bin/sh
# Runs as root once the files are in place. Starts the helper as the person at the screen, detached, so the installer
# can finish: it opens their browser on the approval page and, after they approve, installs its background service
# for them. A Mac that is already on the map just gets the new helper.
DIR="/Library/Application Support/Nightlight"
. "$(dirname "$0")/nightlight.conf"
WHO=$(stat -f%Su /dev/console)
case "$WHO" in
  ""|root|loginwindow|_mbsetupuser)
    echo "Nightlight: nobody is logged in at the screen; open the installer again from your own account."
    exit 0 ;;
esac
WHO_UID=$(id -u "$WHO") || exit 0
# The Mac's own processor, also when this script runs under Rosetta.
if [ "$(sysctl -in hw.optional.arm64)" = 1 ]; then ARCH=arm64; else ARCH=x86_64; fi
PY="$DIR/runtime/$ARCH/python/bin/python3.12"
HELPER="$DIR/nightlight_helper.py"
if launchctl asuser "$WHO_UID" sudo -u "$WHO" -H "$PY" "$HELPER" joined >/dev/null 2>&1; then
  set -- install
else
  set -- pair "$API_URL" --web "$WEB_URL" --browser --install
fi
# The log file is created by that person, not by root, in their own Logs folder.
nohup launchctl asuser "$WHO_UID" sudo -u "$WHO" -H /bin/sh -c \
  'cd "$HOME" && exec "$0" "$@" >>"$HOME/Library/Logs/nightlight-install.log" 2>&1 </dev/null' \
  "$PY" "$HELPER" "$@" >/dev/null 2>&1 &
exit 0
SH
chmod 755 "$STAGE/scripts/postinstall"

if [ "$DRY" = 1 ]; then
  echo "Dry run: payload for helper $VERSION in $STAGE (placeholder runtimes; nothing downloaded or signed)"
  (cd "$STAGE" && find . -type f | LC_ALL=C sort)
  exit 0
fi

# ---- signing (only with Juan's Developer ID certificates; otherwise an unsigned package for local testing)
APP_ID=$(security find-identity -v -p codesigning | grep -o "\"Developer ID Application: [^\"]*(${TEAM_ID})\"" | head -1 | tr -d '"' || true)
INST_ID=$(security find-identity -v -p basic | grep -o "\"Developer ID Installer: [^\"]*(${TEAM_ID})\"" | head -1 | tr -d '"' || true)
if [ -n "$APP_ID" ]; then
  echo "Signing the runtimes with $APP_ID"
  # Hardened runtime, no entitlements: checked 2026-10-17 with a same-team certificate, the runtime then still runs
  # the helper, HTTPS and ctypes callbacks (library validation passes because every file carries the same team).
  while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q '^Mach-O'; then
      codesign --force --timestamp --options runtime -s "$APP_ID" "$f"
    fi
  done < <(find "$APP/runtime" -type f -print0)
fi

COMPONENT="$BUILD_DIR/Nightlight-component.pkg"
PKG="$BUILD_DIR/Nightlight.pkg"
rm -f "$COMPONENT" "$PKG" "$PKG.sha256"
pkgbuild --root "$STAGE/root" --scripts "$STAGE/scripts" --identifier "$PKG_ID" --version "$VERSION" \
  --install-location / "$COMPONENT"
cat > "$STAGE/distribution.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>Nightlight</title>
  <options customize="never" require-scripts="false" hostArchitectures="arm64,x86_64"/>
  <domains enable_localSystem="true"/>
  <volume-check><allowed-os-versions><os-version min="10.15"/></allowed-os-versions></volume-check>
  <choices-outline><line choice="default"><line choice="$PKG_ID"/></line></choices-outline>
  <choice id="default"/>
  <choice id="$PKG_ID" visible="false"><pkg-ref id="$PKG_ID"/></choice>
  <pkg-ref id="$PKG_ID" version="$VERSION" onConclusion="none">Nightlight-component.pkg</pkg-ref>
</installer-gui-script>
XML
productbuild --distribution "$STAGE/distribution.xml" --package-path "$BUILD_DIR" "$BUILD_DIR/Nightlight-unsigned.pkg"
rm -f "$COMPONENT"

CERTS="Xcode > Settings > Accounts > (your personal team, $TEAM_ID) > Manage Certificates > +"
todo=()
[ -n "$APP_ID" ] || todo+=("Create a Developer ID Application certificate: $CERTS > Developer ID Application.")
[ -n "$INST_ID" ] || todo+=("Create a Developer ID Installer certificate: $CERTS > Developer ID Installer.")
xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1 || todo+=("Store notary credentials \
once, in Terminal (it asks for an app-specific password from account.apple.com):
     xcrun notarytool store-credentials $NOTARY_PROFILE --apple-id <your Apple ID> --team-id $TEAM_ID")
if [ -n "$INST_ID" ] && [ -n "$APP_ID" ]; then
  productsign --timestamp --sign "$INST_ID" "$BUILD_DIR/Nightlight-unsigned.pkg" "$PKG"
  rm -f "$BUILD_DIR/Nightlight-unsigned.pkg"
  if [ ${#todo[@]} -eq 0 ]; then
    out=$(xcrun notarytool submit "$PKG" --keychain-profile "$NOTARY_PROFILE" --wait)
    echo "$out"
    grep -q "status: Accepted" <<<"$out" || { echo "Notarization was not accepted. Details: xcrun notarytool log \
<submission id> --keychain-profile $NOTARY_PROFILE" >&2; exit 1; }
    xcrun stapler staple "$PKG"
    xcrun stapler validate "$PKG"
  fi
else
  mv "$BUILD_DIR/Nightlight-unsigned.pkg" "$PKG"
fi

sha256 "$PKG" > "$PKG.sha256"
echo "Built $PKG ($(du -h "$PKG" | cut -f1 | tr -d ' '), helper $VERSION) sha256 $(cat "$PKG.sha256")"
if [ ${#todo[@]} -gt 0 ]; then
  echo
  echo "This package is NOT notarized: macOS will refuse to open it on other Macs. To ship it:"
  for t in "${todo[@]}"; do echo "  - $t"; done
  echo "  Then run this script again."
fi
