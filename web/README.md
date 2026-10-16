# Nightlight web app

Next.js (App Router, TypeScript). A working skeleton wired to the live API: sign-in (one-click demo or Google), the
home board, device details, chat with live steps and approval cards, trust levels, activity, demo tools and adding a
real device. The visual design is a placeholder: colours and spacing are tokens in `app/globals.css`.

## Run locally

```bash
npm install
export API_URL=https://<api-host> FIREBASE_API_KEY=… FIREBASE_AUTH_DOMAIN=… FIREBASE_PROJECT_ID=… FIREBASE_APP_ID=…
npm run dev        # http://localhost:3000
```

The browser reads its runtime config from `/config` (served from those environment variables), so no keys are
committed. Data shapes and the approval flow: [`../docs/API.md`](../docs/API.md); sample data:
[`../contracts/mocks/`](../contracts/mocks/).

| Where | What |
|---|---|
| `lib/firebase.ts`, `lib/api.ts` | runtime config, Firebase, API calls with the ID token, SSE over POST |
| `lib/data.ts` | live Firestore listeners (own data only), current-generation filter, 5-minute freshness rule |
| `components/` | `Home` (layout), `Board`, `DeviceDrawer`, `Chat`, `ApprovalCard`, `TrustPanel`, `Activity`, `DemoTools`, `AddDevice`, `PairApprove` |
| `app/install.sh`, `app/uninstall.sh`, `lib/installScript.ts` | the one-line installer: downloads `/nightlight_helper.py` from this origin, checks its sha256, then `enrol` (with a code) or `pair`, then `install` |
| `app/pair` | `/pair?code=…`, the page a phone opens from a device's QR code: Google sign-in, then Approve |

## Device helper

`/install.sh` serves `public/nightlight_helper.py`, which is **not committed**: `npm run dev` and `npm run build` copy
it from `../helper/` (`scripts/copy-helper.mjs`). A deploy that uploads only `web/` must copy it in first
(`cp helper/nightlight_helper.py web/public/`); `.gcloudignore` keeps it in the upload. Without it `/install.sh`
answers 503.
