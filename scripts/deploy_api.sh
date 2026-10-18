#!/usr/bin/env bash
# Deploy the API to Cloud Run. Cost guards are configured by environment; no secrets are needed
# (the service account reaches Firestore and Gemini through Application Default Credentials).
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT=${PROJECT:-nightlight-aibc}
REGION=${REGION:-asia-northeast3}
WEB_ORIGINS=${WEB_ORIGINS:-http://localhost:3000,https://nightlight-web-1032111130355.asia-northeast3.run.app,https://fe-preview---nightlight-web-1032111130355.asia-northeast3.run.app}
# Optional: the Memory Bank id (last segment of .../reasoningEngines/<id>). Unset = memory off.
# Agent Platform Memory Bank (resource id, not a secret). Unset → this bank; MEMORY_BANK_ID='' → memory off.
MEMORY_BANK_ID=${MEMORY_BANK_ID-4443553098354393088}
API_URL=${API_URL:-https://nightlight-api-1032111130355.${REGION}.run.app}
SWEEP_INVOKER=${SWEEP_INVOKER:-sweep-invoker@${PROJECT}.iam.gserviceaccount.com}
./scripts/secret_scan.sh
# The signed helper release devices can update to: refuse to deploy one whose signature doesn't match the key the
# helper itself carries (sign it first with scripts/sign_helper.sh; the signing key stays on the maintainer's machine).
python3 - <<'PY'
import re, subprocess, tempfile
src = open("helper/nightlight_helper.py").read()
key = re.search(r'RELEASE_KEY = """(.*?)"""', src, re.S).group(1).strip() + "\n"
with tempfile.NamedTemporaryFile("w", suffix=".pem") as k:
    k.write(key); k.flush()
    subprocess.run(["openssl", "dgst", "-sha256", "-verify", k.name, "-signature", "helper/nightlight_helper.py.sig",
                    "helper/nightlight_helper.py"], check=True)
PY
mkdir -p api/src/nightlight_api/release
cp helper/nightlight_helper.py helper/nightlight_helper.py.sig api/src/nightlight_api/release/
gcloud run deploy nightlight-api --source api --project "$PROJECT" --region "$REGION" \
  --service-account "api-runtime@${PROJECT}.iam.gserviceaccount.com" \
  --allow-unauthenticated --min-instances "${MIN_INSTANCES:-0}" --max-instances 3 --concurrency 20 --cpu 1 --memory 1Gi \
  --timeout 900 \
  --set-env-vars "^|^GOOGLE_CLOUD_PROJECT=${PROJECT}|GOOGLE_CLOUD_LOCATION=global|GOOGLE_GENAI_USE_ENTERPRISE=True|WEB_ORIGINS=${WEB_ORIGINS}|APP_URL=${APP_URL:-https://nightlight-web-1032111130355.asia-northeast3.run.app}|MODEL_BUDGET_USD=35|MODEL=gemini-3.8-flash|PRICE_IN_PER_M=0.75|PRICE_OUT_PER_M=3.75|MAX_OUTPUT_TOKENS=1024|THINKING_LEVEL=${THINKING_LEVEL:-LOW}|SWEEP_AUDIENCE=${API_URL}/internal/sweep|SWEEP_INVOKER=${SWEEP_INVOKER}${MEMORY_BANK_ID:+|MEMORY_BANK_ID=${MEMORY_BANK_ID}}"
