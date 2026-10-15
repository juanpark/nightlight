# API

The contract between the web app and the backend. Frozen on 16 Oct 2026, 02:30 KST: after that, changes only add
fields. Example data for every shape is in [`contracts/mocks/`](../contracts/mocks/), as consistent phases of one demo story
(start with `phases/before_approval`).

## Basics

- **Auth:** every `/api/*` call sends `Authorization: Bearer <Firebase ID token>`, except `GET /api/health`. The demo
  signs in anonymously (Firebase), so judges never create an account.
- **Bodies:** JSON. Unknown or invalid fields are **rejected** with 422.
- **Times:** ISO 8601 UTC strings in the API and mocks, e.g. `2026-10-16T17:05:12.345Z`. Firestore listeners return
  Timestamp objects; convert them in one adapter so the UI sees the same shape from both.
- **Reading data:** the browser reads its own data directly from Firestore with listeners, under `users/{uid}/...`
  (read-only). Every write goes through this API.
- **Streams:** chat replies are Server-Sent Events over a `POST`, read with `fetch()` and a `ReadableStream`
  (`EventSource` can't send headers). Every stream ends with a `done` or an `error` event. A `: ping` comment arrives
  every 15 s on long streams.
- **Simulated data:** the sample home is simulated and labelled as such.

## Data the browser reads (Firestore, read-only)

| Path | What | Mock |
|---|---|---|
| `users/{uid}` | `demoGeneration`, `demo.state` (`ready` / `resetting`), `trustDefault`, `template` | `phases/<phase>/user.json` |
| `users/{uid}/devices/{deviceId}` | name, kind, `purpose` (plain words), `status` (`ok`/`warn`/`crit`/`offline`), `health` (`verified`/`unknown`), `vitals`, `version`, `simulated`, map position `x`,`y` | `phases/<phase>/devices.json` |
| `…/devices/{deviceId}/services/{svcId}` | name, status, version, `updateAvailable`, `findings[]` (plain message + evidence) | nested under each device in `devices.json` for convenience |
| `users/{uid}/events/{eventId}` | what happened, when, how serious | `phases/<phase>/events.json` |
| `users/{uid}/actions/{actionId}` | approval cards: `plan`, `dryRun`, `blastRadius`, `rollback`, `status`, `decision`, `result` | `phases/<phase>/actions.json` |
| `users/{uid}/trust/{realm}:{actionType}` | trust level per kind of job, `pinned`, `successes`, promotion `offer` | `phases/<phase>/trust.json` |
| `users/{uid}/sessions/{sid}` + `/messages` + `/turns` | chats, messages ordered by `seq`, turn status | `phases/<phase>/sessions.json` |

Every demo document carries `demoGeneration`. Show only documents whose `demoGeneration` equals the user's current
`demoGeneration` (older ones are leftovers from before a reset), plus real devices (`realm: "real"`), which are always
current.

## Endpoints

| Method and path | Body | Response |
|---|---|---|
| `GET /config` (served by the web app) | | `{apiUrl, firebase:{apiKey, authDomain, projectId, appId}}` |
| `GET /api/health` | | `200 {ok, version}` |
| `POST /api/demo/start` | `{"template":"home-pi"}` | `200 {ok, demoGeneration, devices}` |
| `POST /api/demo/reset` | `{}` | `200 {ok, demoGeneration}`; `409 reset_in_progress` |
| `POST /api/demo/inject` | `{"kind":"disk_full","deviceId":"pi-1"}` | `201 {eventId}` |
| `POST /api/chat/sessions` | `{}` | `201 {sessionId}` |
| `POST /api/chat/sessions/{sid}/messages` | `{"text":"…","clientRequestId":"<uuid v4>"}` (text ≤ 2 KB) | `200` stream; same `clientRequestId` → the same turn (a finished turn replays); same id with different text → `409 request_mismatch`; `409 turn_in_progress` |
| `POST /api/turns/{turnId}/stream` | `{}` | `200` stream: runs a queued turn, retries a turn whose lease expired, or replays a finished one; `409 turn_in_progress` while it's live |
| `POST /api/actions/{id}/decide` | `{"decision":"approve"}` or `{"decision":"deny","note":"…"}` | `202 {actionId, status, continuationTurnId}`; retry → `200` same body; `409 decision_conflict` / `stale` / `illegal_transition` |
| `PUT /api/trust/{actionType}` | `{"level":"auto","deviceId":null,"svcId":null,"pinned":true}` | `200` trust doc |
| `POST /api/trust/{actionType}/promotion` | `{"accept":true,"offerId":"…"}` | `200` trust doc; `409 offer_obsolete` |

While `demo.state` is `resetting`, every demo write and chat answers `409 resetting`.

## The approval flow

1. The user asks a question → stream. If the agent wants to change something, the stream sends
   `{"type":"approval_request","actionId":"…"}`. The card's details are in Firestore at `users/{uid}/actions/{actionId}`.
2. The user taps Approve or Not now → `POST /api/actions/{id}/decide` → `202` with `continuationTurnId`.
3. The browser opens `POST /api/turns/{continuationTurnId}/stream` to show the agent's follow-up ("Done. The Pi is now
   61% full.").
4. If the kind of job has gone well 3 times, a promotion `offer` appears on its trust doc. The user accepts with
   `POST /api/trust/{actionType}/promotion`.

When trust allows a job to run automatically, there is no card and no follow-up turn: the action is created already
finished, `done` or `failed`, with `decision.by = "auto"`, and the agent explains the outcome in the same reply. A
failed automatic job lowers its trust level by one step.

## Real devices (read-only helper)

| Method and path | Auth | Body | Response |
|---|---|---|---|
| `POST /api/devices/enrol-code` | Firebase token | `{}` | `201 {code: "ABCD-EFGH", expiresAt}`: one-time, 10 minutes, at most 10 per hour |
| `POST /helper/enrol` | the one-time code | `{"code":"ABCD-EFGH","name":"My Pi"}` | `201 {deviceId, token}`: the token is shown only here and kept by the helper; `401 invalid_code` if unknown, used or expired |
| `POST /helper/heartbeat` | header `X-Device-Token` | allowlisted facts (below) | `200 {ok, deviceId, findings}`; `401 invalid_token`; `429 too_frequent` (one report per 20 s) |
| `POST /api/devices/{deviceId}/revoke` | Firebase token | `{}` | `200 {ok, deviceId}`: the helper's token stops working |

Heartbeat facts (anything else is rejected): `helperVersion`, `os`, `arch`, `cpuPct`, `memPct`, `diskPct`,
`uptimeSec`, `containers[] {name, image, state, status}`, `failedUnits[]`, `updatesPending`. No host names, IP
addresses, logs or credentials are accepted.

Real devices have `realm: "real"` and `simulated: false`; they are always shown (they have no `demoGeneration`),
are never touched by Reset, and jobs don't run on them (read-only). Their services come from containers
(`category: "containers"`) and failed system services (`category: "system"`). Checks: `disk_over_80`,
`disk_over_90`, `memory_high`, `service_down`, `container_down`, `updates_pending`, `restart_overdue`.

The helper: [`helper/nightlight_helper.py`](../helper/nightlight_helper.py) (`enrol`, `once`, `run`, `show`).

## Jobs, incidents and checks

| Job (`actionType`) | What it does | `riskClass` | Can run on its own? |
|---|---|---|---|
| `rotate_logs` | clean up log files older than 7 days | `routine` | yes, once trusted |
| `backup_world` | save a copy of a game world (players keep playing) | `routine` | yes, once trusted |
| `restart_server` | restart a game server to clear memory (players disconnected ~1 min) | `service` | no, at most "Ask me for new things", and never on its own |
| `update_server` | back up, then update a game server (players disconnected ~2 min) | `service` | no, as above |

Demo incidents (`POST /api/demo/inject` `kind`): `disk_full`, `logs_locked` (the next job fails), `server_lagging`,
`backup_overdue`, `update_available`. Game incidents only apply to game servers (`422` otherwise).

Findings (`check`) on devices and services: `disk_over_90`, `memory_high`, `backup_overdue`, `update_available`,
`backup_never_test_restored`; each has `severity` (`crit`/`warn`/`info`), a plain `message`, `evidence` and the
`svcId` it concerns. A device's health light reflects its own and its services' findings.

Game services also carry `version`, `latestVersion`, `updateAvailable`, `players {online, max}` and
`lastBackupDaysAgo`. Services have a `category` (`home`, `network`, `files`, `games`) for the category filter.

## Trust levels

| Level | Shown as |
|---|---|
| `ask` | Always ask me |
| `ask_new` | Ask me for new things |
| `auto` | Just handle it and tell me |

Precedence: a service setting beats a device setting, which beats the job's level, which beats the global default.
Risky jobs have a ceiling (e.g. turning off password login always asks).

## Stream events

```
{"type":"turn_start","turnId":"…","attempt":1,"messageId":"…","at":"…"}            (replay adds "replay":true)
{"type":"text","delta":"…"}
{"type":"tool_call","name":"get_device","args":{"device_id":"pi-1"}}
{"type":"tool_result","name":"get_device","summary":"…","redacted":0}
{"type":"approval_request","actionId":"…"}
{"type":"error","code":"…","message":"…","retryable":false}                         terminal
{"type":"done","turnId":"…","metrics":{"latencyMs":…,"firstTextMs":…,"modelCalls":…,"toolCalls":…,"tokensIn":…,"tokensOut":…,"tokensThinking":…,"costUsd":…}}   terminal
```

## Errors

| Status | Meaning | Body |
|---|---|---|
| 401 | missing, invalid or expired token | `{error, code:"invalid_token"}` |
| 403 | allowed in principle but switched off (e.g. kill switch) | `{error, code}` |
| 404 | not found, **or owned by another user** (same answer) | `{error, code:"not_found"}` |
| 409 | `illegal_transition`, `decision_conflict`, `stale`, `turn_in_progress`, `offer_obsolete`, `request_mismatch`, `resetting`, `reset_in_progress` | `{error, code, actionId?, turnId?, retryAfter?}` |
| 422 | unknown or invalid field | `{"error":"validation_error","code":"invalid_body","detail":[…]}` |
| 429 | usage limit | `{error, code:"quota_uid"|"quota_ip"|"quota_global"}` + `Retry-After` |

All bodies are in `contracts/mocks/errors.json`.

## Chat retries

- Create `clientRequestId` with `crypto.randomUUID()` when the user sends a message; reuse it to retry that message.
- If a stream drops, call `POST /api/turns/{turnId}/stream` for the same turn. A retry never repeats an action the
  agent already took.
- "Ask again" is a new message with a new `clientRequestId`.
