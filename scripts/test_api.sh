#!/usr/bin/env bash
# Run the API tests against the Firestore emulator (no Google Cloud project or credentials needed).
set -euo pipefail
cd "$(dirname "$0")/.."
exec firebase emulators:exec --only firestore --project demo-nightlight \
  "cd api && GOOGLE_CLOUD_PROJECT=demo-nightlight uv run pytest -q $*"
