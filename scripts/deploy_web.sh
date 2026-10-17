#!/usr/bin/env bash
# Deploy the web app to Cloud Run. The Firebase web config (public by design, but kept out of git) is read from the
# Firebase project at deploy time and passed as environment variables; the app serves it at /config.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT=${PROJECT:-nightlight-aibc}
REGION=${REGION:-asia-northeast3}
WEB_APP_ID=${WEB_APP_ID:-1:1032111130355:web:ad4468c6b1182412aa9986}  # public Firebase app id (not a secret)
# PREVIEW=name (3+ characters, e.g. fe-preview) deploys a tagged revision with no traffic, at
# https://name---<service host>, for checking a change
# before it goes live; production keeps serving the previous revision.
PREVIEW=${PREVIEW:-}
API_URL=${API_URL:-$(gcloud run services describe nightlight-api --project "$PROJECT" --region "$REGION" --format 'value(status.url)')}
CFG=$(curl -fsS -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "x-goog-user-project: ${PROJECT}" \
  "https://firebase.googleapis.com/v1beta1/projects/${PROJECT}/webApps/${WEB_APP_ID}/config")
val() { python3 -c "import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])" "$CFG" "$1"; }
./scripts/secret_scan.sh
mkdir -p web/public && cp helper/nightlight_helper.py web/public/nightlight_helper.py  # served for /install.sh (not committed)
# The Mac installer, served at /download/Nightlight.pkg (built by scripts/build_mac_pkg.sh; not committed). Only a
# notarized one ships: other Macs refuse to open anything else. ALLOW_UNSIGNED_PKG=1 ships it anyway (previews).
rm -rf web/public/download
if [ -f build/mac/Nightlight.pkg ]; then
  if xcrun stapler validate build/mac/Nightlight.pkg >/dev/null 2>&1 || [ "${ALLOW_UNSIGNED_PKG:-}" = 1 ]; then
    mkdir -p web/public/download
    cp build/mac/Nightlight.pkg build/mac/Nightlight.pkg.sha256 web/public/download/
  else
    echo "build/mac/Nightlight.pkg isn't notarized, so it isn't deployed (/download/Nightlight.pkg answers 404)."
  fi
fi
# Every revision gets a known name, so production can be pointed at exactly this build: once a preview has pinned
# the traffic split, a plain deploy no longer moves it (it did not, Oct 17 14:40–17:30 KST), and "latest" could be
# someone's preview.
SUFFIX=${PREVIEW:-prod}-$(git rev-parse --short HEAD)-$(date +%H%M%S)
gcloud run deploy nightlight-web --source web --project "$PROJECT" --region "$REGION" --revision-suffix "$SUFFIX" \
  --allow-unauthenticated --min-instances 0 --max-instances 3 --cpu 1 --memory 512Mi \
  ${PREVIEW:+--tag "$PREVIEW" --no-traffic} \
  --set-env-vars "^@^API_URL=${API_URL}@FIREBASE_API_KEY=$(val apiKey)@FIREBASE_AUTH_DOMAIN=$(val authDomain)@FIREBASE_PROJECT_ID=$(val projectId)@FIREBASE_APP_ID=$(val appId)"
if [ -z "$PREVIEW" ]; then
  gcloud run services update-traffic nightlight-web --project "$PROJECT" --region "$REGION" \
    --to-revisions "nightlight-web-${SUFFIX}=100"
  echo "Production now serves nightlight-web-${SUFFIX}"
fi
