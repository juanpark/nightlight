#!/usr/bin/env bash
# IAM for live demo machines: what the API's runtime account needs. Run once, as a project owner; re-running updates.
#
#  1. Token Creator on itself: sign Firebase custom tokens for the pool accounts through IAM signBlob (no key file).
#     Boundary: that signing power is NOT limited to pool uids; it can mint a custom token for any uid in the project.
#     The API only ever mints for uids from its own LIVE_POOL config, but a compromised runtime crosses this line. To
#     contain it, sign in a separate Firebase project or behind a separately enforced signing service (roadmap).
#  2. liveDemoPoolVm (conditioned to nl-live-* resources): start/stop/get the pool VMs, set their metadata, read guest
#     attributes, attach/detach disks, and get/use/delete nl-live-* disks; read nl-live-* snapshots.
#     Limit: setMetadata can't be narrowed to one key; this grant can change any metadata on nl-live-* VMs (startup
#     script included). The VMs have no service account and only IAP SSH, which bounds what that can reach.
#  3. liveDemoPoolDiskCreate (project level, unconditioned): Google evaluates compute.disks.create at the project, and
#     the request's resource-name attribute is not documented as usable in a condition, so it is granted separately and
#     plainly. A dedicated pool project would contain it fully (roadmap).
#  4. liveDemoPoolAuth (project level): delete a Firebase Auth user, used to reset a pool account after each visit.
#     Firebase Auth permissions can't be scoped to some uids; the same boundary as (1).
# After granting, validate with the runtime identity itself (not owner credentials):
#   gcloud config set auth/impersonate_service_account api-runtime@nightlight-aibc.iam.gserviceaccount.com
#   (from api/) uv run python ../scripts/live_pool/local.py serve   # then: pool_test.py ... 1 --reset-visitor 1 --end --wait-free
#   gcloud config unset auth/impersonate_service_account
# (impersonating needs Token Creator on api-runtime for your own user, granted temporarily.)
set -euo pipefail
PROJECT=${PROJECT:-nightlight-aibc}
SA=api-runtime@${PROJECT}.iam.gserviceaccount.com
ZONE=asia-northeast3-a

role() {  # create the custom role, or update it to exactly these permissions; any other failure stops the script
  local id=$1 title=$2 perms=$3
  if gcloud iam roles describe "$id" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud iam roles update "$id" --project "$PROJECT" --title "$title" --permissions "$perms" --quiet >/dev/null
  else
    gcloud iam roles create "$id" --project "$PROJECT" --title "$title" --permissions "$perms" >/dev/null
  fi
}

gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" \
  --member "serviceAccount:$SA" --role roles/iam.serviceAccountTokenCreator >/dev/null

role liveDemoPoolVm "Nightlight live demo pool VMs" \
  compute.instances.get,compute.instances.start,compute.instances.stop,compute.instances.setMetadata,\
compute.instances.getGuestAttributes,compute.instances.attachDisk,compute.instances.detachDisk,\
compute.disks.get,compute.disks.use,compute.disks.delete,compute.disks.setLabels,compute.snapshots.useReadOnly,\
compute.zoneOperations.get
role liveDemoPoolDiskCreate "Nightlight live demo pool disk create" compute.disks.create
role liveDemoPoolAuth "Nightlight live demo pool account reset" firebaseauth.users.delete,firebaseauth.users.get

P="projects/$PROJECT"
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" \
  --role "$P/roles/liveDemoPoolVm" --condition="title=live-demo-pool-only,expression=\
resource.name.startsWith('$P/zones/$ZONE/instances/nl-live-') || \
resource.name.startsWith('$P/zones/$ZONE/disks/nl-live-') || \
resource.name.startsWith('$P/global/snapshots/nl-live-') || \
resource.type == 'compute.googleapis.com/ZoneOperation'" >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" \
  --role "$P/roles/liveDemoPoolDiskCreate" --condition=None >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" \
  --role "$P/roles/liveDemoPoolAuth" --condition=None >/dev/null
echo "granted; now validate with the runtime identity (see the comment at the top)"
