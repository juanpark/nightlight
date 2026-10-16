#!/usr/bin/env bash
# Deploy the API to Cloud Run. Cost guards are configured by environment; no secrets are needed
# (the service account reaches Firestore and Gemini through Application Default Credentials).
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT=${PROJECT:-nightlight-aibc}
REGION=${REGION:-asia-northeast3}
WEB_ORIGINS=${WEB_ORIGINS:-http://localhost:3000,https://nightlight-web-1032111130355.asia-northeast3.run.app}
# Optional: the Memory Bank id (last segment of .../reasoningEngines/<id>). Unset = memory off.
MEMORY_BANK_ID=${MEMORY_BANK_ID:-}
./scripts/secret_scan.sh
gcloud run deploy nightlight-api --source api --project "$PROJECT" --region "$REGION" \
  --service-account "api-runtime@${PROJECT}.iam.gserviceaccount.com" \
  --allow-unauthenticated --min-instances 0 --max-instances 3 --concurrency 20 --cpu 1 --memory 1Gi \
  --timeout 300 \
  --set-env-vars "^@^GOOGLE_CLOUD_PROJECT=${PROJECT}@GOOGLE_CLOUD_LOCATION=global@GOOGLE_GENAI_USE_ENTERPRISE=True@WEB_ORIGINS=${WEB_ORIGINS}@MODEL_BUDGET_USD=35@MODEL=gemini-3.5-flash-lite@PRICE_IN_PER_M=0.30@PRICE_OUT_PER_M=2.50@MAX_OUTPUT_TOKENS=1024@THINKING_LEVEL=MINIMAL${MEMORY_BANK_ID:+@MEMORY_BANK_ID=${MEMORY_BANK_ID}}"
