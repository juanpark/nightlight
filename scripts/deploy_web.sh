#!/usr/bin/env bash
# Deploy the web app to Cloud Run. The Firebase web config (public by design, but kept out of git) is read from the
# Firebase project at deploy time and passed as environment variables; the app serves it at /config.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT=${PROJECT:-nightlight-aibc}
REGION=${REGION:-asia-northeast3}
WEB_APP_ID=${WEB_APP_ID:?set WEB_APP_ID to the Firebase web app id}
API_URL=${API_URL:-$(gcloud run services describe nightlight-api --project "$PROJECT" --region "$REGION" --format 'value(status.url)')}
CFG=$(curl -fsS -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "x-goog-user-project: ${PROJECT}" \
  "https://firebase.googleapis.com/v1beta1/projects/${PROJECT}/webApps/${WEB_APP_ID}/config")
val() { python3 -c "import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])" "$CFG" "$1"; }
./scripts/secret_scan.sh
cp helper/nightlight_helper.py web/public/nightlight_helper.py  # served for /install.sh (not committed)
gcloud run deploy nightlight-web --source web --project "$PROJECT" --region "$REGION" \
  --allow-unauthenticated --min-instances 0 --max-instances 3 --cpu 1 --memory 512Mi \
  --set-env-vars "^@^API_URL=${API_URL}@FIREBASE_API_KEY=$(val apiKey)@FIREBASE_AUTH_DOMAIN=$(val authDomain)@FIREBASE_PROJECT_ID=$(val projectId)@FIREBASE_APP_ID=$(val appId)"
