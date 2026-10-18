#!/usr/bin/env bash
# IAM for live demo machines: what the API's runtime account needs, and nothing wider. Run once, as a project owner.
#  1. Sign Firebase custom tokens for the pool accounts through IAM signBlob (no key file): Token Creator on itself.
#  2. Start/stop the pool VMs, set their "demo-command" metadata, read their guest attributes, and swap their boot disk
#     for a fresh one made from <vm>-golden: a custom role bound with a condition to nl-live-* resources only.
set -euo pipefail
PROJECT=${PROJECT:-nightlight-aibc}
SA=api-runtime@${PROJECT}.iam.gserviceaccount.com

gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/iam.serviceAccountTokenCreator

gcloud iam roles create liveDemoPool --project "$PROJECT" --title "Nightlight live demo pool" \
  --description "Start, stop and restore the nl-live-* demo VMs" \
  --permissions compute.instances.get,compute.instances.start,compute.instances.stop,compute.instances.setMetadata,\
compute.instances.getGuestAttributes,compute.instances.attachDisk,compute.instances.detachDisk,\
compute.disks.get,compute.disks.create,compute.disks.delete,compute.disks.use,compute.disks.setLabels,\
compute.snapshots.useReadOnly,compute.zoneOperations.get 2>/dev/null || echo "role exists"

gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" \
  --role "projects/$PROJECT/roles/liveDemoPool" \
  --condition='expression=resource.name.startsWith("projects/'"$PROJECT"'/zones/asia-northeast3-a/instances/nl-live-") || resource.name.startsWith("projects/'"$PROJECT"'/zones/asia-northeast3-a/disks/nl-live-") || resource.name.startsWith("projects/'"$PROJECT"'/global/snapshots/nl-live-") || resource.type == "compute.googleapis.com/ZoneOperation",title=live-demo-pool-only'
