#!/usr/bin/env bash
# Sign the helper with Nightlight's release key (kept offline, never in git or the cloud). Devices install an update
# from the app only if this signature checks out against the public key built into the helper they already run.
set -euo pipefail
cd "$(dirname "$0")/.."
KEY=${HELPER_SIGNING_KEY:-private/signing/helper-signing.pem}
[ -f "$KEY" ] || { echo "No signing key at $KEY" >&2; exit 1; }
openssl dgst -sha256 -sign "$KEY" -out helper/nightlight_helper.py.sig helper/nightlight_helper.py
openssl ec -in "$KEY" -pubout 2>/dev/null > /tmp/nightlight-pub.$$.pem
openssl dgst -sha256 -verify /tmp/nightlight-pub.$$.pem -signature helper/nightlight_helper.py.sig helper/nightlight_helper.py
rm -f /tmp/nightlight-pub.$$.pem
echo "signed helper $(grep -m1 '^VERSION = ' helper/nightlight_helper.py)"
