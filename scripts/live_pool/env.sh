# Environment for running the API locally against the real project (ADC = your gcloud login) with the live pool on.
# Usage: . scripts/live_pool/env.sh   (no secrets: ids only)
export GOOGLE_CLOUD_PROJECT=nightlight-aibc
export LIVE_POOL="nl-live-1=judge-pool-1,nl-live-2=judge-pool-2,nl-live-3=judge-pool-3,nl-live-4=judge-pool-4,nl-live-5=judge-pool-5"
export LIVE_SIGNER=firebase-adminsdk-fbsvc@nightlight-aibc.iam.gserviceaccount.com
export MEMORY_BANK_ID=4443553098354393088
export LIVE_IDLE_SECONDS=${LIVE_IDLE_SECONDS:-120}
export WEB_ORIGINS=http://localhost:3000
