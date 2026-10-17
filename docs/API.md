# API

The contract between the web app, the device helper and the backend. Frozen on 16 Oct 2026, 02:30 KST: after that,
changes only add routes and fields (this page covers everything up to helper 0.6.0). Example data for the sample-home
shapes is in [`contracts/mocks/`](../contracts/mocks/), as consistent phases of one demo story (start with
`phases/before_approval`). Security design: [`SECURITY.md`](SECURITY.md).

## Basics

- **Auth:** every `/api/*` call sends `Authorization: Bearer <Firebase ID token>`, except `GET /api/health`. The demo
  signs in anonymously (Firebase), so judges never create an account. `/helper/*` routes use a device token
  (`X-Device-Token`) or a join code; `/internal/sweep` accepts only Cloud Scheduler's signed token.
- **Owner gate:** routes marked *owner* need a non-anonymous (Google) sign-in; an anonymous token gets
  `403 sign_in_required`.
- **Bodies:** JSON. Unknown or invalid fields are **rejected** with 422. The reason is in `detail[0].msg` (a code such
  as `private_address` for our own checks, the validator's message for schema errors).
- **Times:** ISO 8601 UTC strings in the API and mocks, e.g. `2026-10-16T17:05:12.345Z`. Firestore listeners return
  Timestamp objects; convert them in one adapter so the UI sees the same shape from both.
- **Reading data:** the browser reads its own data directly from Firestore with listeners, under `users/{uid}/...`
  (read-only). Every write goes through this API.
- **Streams:** chat replies are Server-Sent Events over a `POST`, read with `fetch()` and a `ReadableStream`
  (`EventSource` can't send headers). Every stream ends with a `done` or an `error` event. A `: ping` comment arrives
  after 15 s without other output.
- **Simulated data:** the sample home is simulated and labelled as such (`simulated: true`).

## Data the browser reads (Firestore, read-only)

| Path | What |
|---|---|
| `users/{uid}` | `demoGeneration`, `demo.state` (`ready` / `resetting`), `trustDefault`, `template` (`home-pi` = sample home shown, `empty` = hidden), `lastChatAt`, `memoryEpoch`, `dismissedLinks` (ids of automatic lines the person deleted), `settings.deviceNames` (show the names things nearby announce; missing means on) |
| `users/{uid}/devices/{deviceId}` | name, `kind`, `purpose` (plain words), `status` (`ok`/`warn`/`crit`/`offline`), `health` (`verified`/`unknown`), `vitals`, `version`, `simulated`, `realm` (`real` for helper devices), map position `x`,`y`, `tags[]`, `findings[]` |
| `users/{uid}/links/{from}__{to}` | `{from, to, kind, realm, demoGeneration, createdAt, source, why}`: lines between devices on the map (see `POST /api/links`). `source` is `user` (drawn by the person or by Nightlight when told), `auto` (seen by the helpers, see [Lines the helpers see](#lines-the-helpers-see)) or missing (sample home, drawn before 0.9.20); `auto` lines carry `why` in plain words ("Time Machine backs up here") |
| `…/devices/{deviceId}/services/{svcId}` | name, status, version, `updateAvailable`, `category`, `findings[]` (plain message + evidence) |
| `…/devices/{deviceId}/history/{YYYYMMDDTHHMMSS}` | real devices only: `{at, cpu, mem, disk, status, problems, expiresAt}`, at most one point per 5 minutes, deleted after 8 days (Firestore TTL on `expiresAt`) |
| `users/{uid}/events/{eventId}` | Activity: what happened, when, how serious (see Events) |
| `users/{uid}/actions/{actionId}` | approval cards and jobs: `type`, `params`, `plan`, `dryRun`, `blastRadius`, `rollback`, `riskClass`, `status`, `decision`, `result`, `realm` (`sim`/`real`), `continuationTurnId`, `followUp` |
| `users/{uid}/trust/{realm}:{actionType}` | trust level per kind of job, `pinned`, `successes`, promotion `offer` |
| `users/{uid}/sessions/{sid}` + `/messages` + `/turns` | chats, messages ordered by `seq`, turn status |
| `users/{uid}/watches/{watchId}` | watched websites: `name`, `url`, `tags`, `status` (`unknown`/`ok`/`crit`), `httpStatus`, `latencyMs`, `lastCheckedAt`, `lastChange`, `createdAt`, `expiresAt` (30 days after adding) |
| `users/{uid}/discoveries/{helperDeviceId}` | what a helper found nearby: `items[] {cid, guess, vendor, name, maker, model, services[], ports[], tag, added}` (`name` only while the account shows names, else `null`), `by`, `byName`, `at`, `expiresAt` (24 h) |

Every sample-home document carries `demoGeneration`. Show only documents whose `demoGeneration` equals the user's
current `demoGeneration` (older ones are leftovers from before a reset), plus real devices and real events
(`realm: "real"`), which are always current.

Mocks: `phases/<phase>/user.json`, `devices.json` (services nested), `events.json`, `actions.json`, `trust.json`,
`sessions.json`. Real-device, history, watch and discovery shapes have no mocks; this page is their reference.

## Endpoints: home, chat, trust

| Method and path | Body | Response |
|---|---|---|
| `GET /config` (served by the web app) | | `{apiUrl, firebase:{apiKey, authDomain, projectId, appId}}` |
| `GET /api/health` | | `200 {ok, version}` |
| `POST /api/demo/start` | `{"template":"home-pi"}` or `{"template":"empty"}` | `200 {ok, demoGeneration, devices}`; does nothing if the home is already ready. The web app sends `home-pi` for anonymous users and `empty` for signed-in owners |
| `POST /api/demo/template` | `{"template":"home-pi" \| "empty"}` | `200 {ok, demoGeneration, devices, template}`: shows or hides the sample home (a rebuild under the reset barrier; memories are kept, real devices untouched); `409 reset_in_progress` |
| `POST /api/demo/reset` | `{}` | `200 {ok, demoGeneration}`; `409 reset_in_progress`. Also forgets memories |
| `POST /api/demo/inject` | `{"kind":"disk_full","deviceId":"pi-1"}` | `201 {eventId}`; `422 real_device_read_only` for a real device |
| `POST /api/devices/{deviceId}/layout` | `{"x":-5000-5000, "y":-5000-5000, "role":"router"\|"printer"\|"fileshare"\|"smarthome"\|"server"\|"speaker"\|"computer"\|"other" (watched things only; the person's choice is kept), "name":"…", "tags":["…"]}`, every field optional | `200 {ok, …fields written}`. `name` (1-40) only for real devices (`422 sample_devices_keep_their_names`); `tags` at most 6, 1-20 characters, scrubbed, de-duplicated, sorted (`422 tag_too_long` if scrubbing made one longer). Sample devices: `409 resetting`, `404` for an old generation. Position doesn't change `version` |
| `POST /api/links` | `{"from":deviceId, "to":deviceId, "kind":"network"\|"backup"\|"depends"\|"power"}` | `201 {id, from, to, kind, realm, demoGeneration}`: a line on the map (connected through / backs up to / relies on / powered by). One per ordered pair (`id` = `{from}__{to}`); drawing it again changes the kind (an automatic line drawn again becomes the person's: `source: "user"`). Layout only: no device is touched. `realm` is `real` only when both ends are real devices; other links go away with the sample home on a reset. `422` same device or unknown kind, `404` a device that isn't on the map, `409 too_many_links` (200) |
| `DELETE /api/links/{linkId}` | — | `200 {ok}`; an automatic line (`source: "auto"`) deleted here is never drawn again; `404` if there is none or it belongs to an older sample home; `409 resetting` for a sample line while the sample home is being rebuilt |
| `POST /api/devices/{deviceId}/issues/{findingId}` | `{"state":"new" \| "known" \| "snoozed","days":1-90}` (`days` required for snoozed) | `200 {ok, state, status}`; real devices only (`404` otherwise or if the finding isn't there); `422 snooze_needs_days` |
| `POST /api/chat/sessions` | `{}` | `201 {sessionId}` |
| `POST /api/chat/sessions/{sid}/messages` | `{"text":"…","clientRequestId":"<uuid v4>"}` (text ≤ 2,000 bytes) | `200` stream; same `clientRequestId` → the same turn (a finished turn replays); same id with different text → `409 request_mismatch`; `409 turn_in_progress` |
| `POST /api/turns/{turnId}/stream` | `{}` | `200` stream: runs a queued turn, retries a turn whose lease expired, or replays a finished one; `409 turn_in_progress` while it's live |
| `POST /api/actions/{id}/decide` | `{"decision":"approve"}` or `{"decision":"deny","note":"…"}` | `202 {actionId, status, continuationTurnId}`; for an approved **real-device** job `202 {actionId, status:"approved"}` with no continuation yet; retry → `200` same body; `409 decision_conflict` / `stale` / `illegal_transition` |
| `PUT /api/trust/{actionType}` | `{"level":"auto","deviceId":null,"svcId":null,"pinned":true}` | `200` trust doc (sample-home jobs only) |
| `POST /api/trust/{actionType}/promotion` | `{"accept":true,"offerId":"…"}` | `200` trust doc; `409 offer_obsolete` |
| `GET /api/me/memories` | | `200 {enabled, memories:[{id, fact, updatedAt}]}`, newest first, at most 50 |
| `DELETE /api/me/memories` | | `200 {ok}`: forgets everything remembered about the caller (`ok:false` if Memory Bank couldn't be reached) |

While `demo.state` is `resetting`, every sample-home write and chat answers `409 resetting`.

## Endpoints: real devices (browser side)

| Method and path | Auth | Body | Response |
|---|---|---|---|
| `POST /api/devices/enrol-code` | owner | `{}` | `201 {code:"ABCD-EFGH", expiresAt}`: one-time, 10 minutes, at most 10 per hour (`429 quota_uid`) |
| `GET /api/devices/pair/{code}` | owner | | `200 {name, os, expiresAt}`: preview of a code a device shows; `404` if unknown, expired or already decided |
| `POST /api/devices/pair/{code}` | owner | `{"approve":true}` or `{"approve":false}` | `200 {ok}`; `404`; `409 already_decided`. Previews and decisions together: at most 30 per hour (`429 quota_uid`) |
| `POST /api/devices/{deviceId}/revoke` | token | `{}` | `200 {ok, deviceId}`: the helper's token stops working and the device goes offline. For a watched device (`kind: "watched"`) it takes it off the map instead and offers its discovery item again |
| `POST /api/discoveries/{helperDeviceId}/{cid}/add` | token | `{"name"?:"Printer"}` (1-40) | `201 {ok, deviceId}`: a watched device on the map, called `name`, or without one the name it announced (cut to 40), else its guess; the announced name is kept as `seenName` (`nameFromSeen: true` while the device is still called by it); `404` (expired list, unknown item, helper gone); `409 already_added`; `422 no_check_port`; `429 watch_capacity` (10 watched per helper) |
| `POST /api/watches` | owner | `{"name":"Blog","url":"https://…","tags":[]}` (name 1-40, url 8-300, tags ≤6) | `201 {id, url}` (checked once right away); `422 bad_url` / `unknown_host` / `private_address`; `429 too_many_watches` (10 per account) / `watch_budget` (20 adds per day, 200 active overall) |
| `DELETE /api/watches/{watchId}` | token | | `200 {ok}`; `404` |

## Endpoints: the helper

| Method and path | Auth | Body | Response |
|---|---|---|---|
| `POST /helper/enrol` | the one-time code | `{"code":"ABCD-EFGH","name":"My Pi"}` | `201 {deviceId, token}`: the token is shown only here; `401 invalid_code` if unknown, used or expired |
| `POST /helper/pair/start` | none (20 per network address per hour, `429 quota_ip`) | `{"name":"Raspberry Pi","os":"Debian 12"}` | `201 {code, pollSecret, interval:3, expiresAt}` (10 minutes) |
| `POST /helper/pair/poll` | `pollSecret` | `{"code":"…","pollSecret":"…"}` | `202 {status:"waiting"}`; `200 {deviceId, token}` once, after the owner approved; `401 invalid_code` (unknown, expired, used, declined or wrong secret, all alike); `429 slow_down` (polls under 2 s apart) |
| `POST /helper/heartbeat` | `X-Device-Token` | allowlisted facts (below) | `200 {ok, deviceId, findings, jobs:[{id, type, params}], pollEverySec, watch:[{cid, port}], netKey}`; `401 invalid_token`; `429 too_frequent` (one report per 20 s) |
| `POST /helper/jobs/claim` | `X-Device-Token` | `{}` | `200 {ok, jobs, pollEverySec}`: a light check for approved work between reports; `429 too_frequent` (4 s apart) |
| `POST /helper/jobs/{actionId}/result` | `X-Device-Token` | `{"ok":true,"summary":"…","state":"running","output":null}` | `200 {ok, actionId, status}`; a repeated report changes nothing; `409 illegal_transition` before the job was handed to this device; `404` for any other device |
| `POST /helper/discoveries` | `X-Device-Token` | `{"items":[{cid, guess, vendor, services, ports, tag?, maker?, model?, name?}]}` (≤30) | `200 {ok, items}`: replaces this helper's list (kept 24 h) |
| `POST /api/devices/{deviceId}/discover` | owner | `{}` | `202 {actionId, status:"approved"}`: the app asks one app-managed device (helper 0.9.21+) to look nearby; the tap is the approval. The helper runs its discovery without prompting and sends everything it found (no addresses) as above; the person picks what to add under Found nearby. `409 strict_device` for a strict device (it looks only when someone runs `discover` there), `409 update_helper_first` before 0.9.21. A scan under way is reused; each new scan is its own job. An empty scan sends `items: []`, which clears that device's earlier finds |
| `POST /api/places/{placeId}` | signed in | `{"name": 1-40}` | `200 {ok, placeId, name}`: names a place: the devices behind one router. `placeId` is that router's fingerprint (a device's `net.gateway`, 20 hex). Only a router one of the owner's devices reports (`404` otherwise), at most 20 places (`409 too_many_places`). Stored at `users/{uid}/places/{placeId}` `{name, at}` (readable by the owner) |
| `POST /api/devices/{deviceId}/setup` | owner | `{"preset":"watch"\|"fix"\|"custom", "autoUpdate"?: bool, "macFolders"?: bool}` | `200 {ok, applied, macFoldersAction, why?}`: the one-time setup card when a real device first connects. App-managed devices get the preset applied to what they reported (`fix` = check, clean up, logs and restarts for every reported container and failed service); strict or older helpers are left as they are (`why`). `macFolders` on a Mac (helper 0.9.22+) asks the device to raise macOS's folder prompts now (`mac_folders` job, approved by the choice). Sets `setupAt`/`setupPreset` on the device; Settings changes it later |
| `POST /api/devices/{deviceId}/mac-folders` | owner | `{}` | `202 {actionId, status}`: ask an app-managed Mac (helper 0.9.22+) again to let Nightlight measure its private folders; macOS asks on the Mac. A request under way is reused. `409 not_a_mac` / `update_helper`. The Mac reports its answer as device field `macFolders`: `"allowed"`, `"declined"` or null (never asked) |
| `POST /api/discover` | owner | `{"everyDevice"?: bool}` | `202 {asked:[{deviceId,name}], skipped:[{deviceId,name,why}]}`: look nearby on every network the owner has a device on, once per network: devices sharing a router fingerprint count as one network, and the freshest app-managed device with helper 0.9.21+ looks for it. With `everyDevice: true` every eligible device looks (more complete: each sees mostly what it talked to lately; the list merges). Strict, silent or older devices are skipped with the reason |
| `GET /api/found` | signed in | — | `200 {items:[{guess, vendor, name, maker, model, services, ports, tag?, seenBy:[{deviceId,name,cid}]}]}`: Found nearby once per thing. Items with the same fingerprint (`tag`) from several devices merge into one row; anything whose fingerprint is one of the owner's own devices (any of a helper's addresses, `net.self` or `net.selves`), or already added, is left out. Merged rows keep every service and port seen, the most specific guess, the first announced name and the first maker and model reported (`null` when none); `seenBy[].canWatch` says whether that finder saw a port to check, and finders that can come first, so Add uses `seenBy[0]`'s `deviceId` and `cid` |
| `POST /api/settings` | owner | `{"deviceNames": bool}` | `200 {ok, deviceNames}`: the account's switch for the names things nearby announce (on by default: it is the owner's own dashboard). Off: helpers stop sending names from their next report, new lists keep none, and the names already kept are removed (from every discovery list, and `seenName` from watched devices; one still called by its announced name goes back to its guess). Addresses never leave a device either way |
| `POST /helper/leave` | `X-Device-Token` | `{}` | `200 {ok}`: the device revokes its own token (uninstall); `401 invalid_token` |

**The Mac installer** (`GET /download/Nightlight.pkg` on the web app, with its sha256 at
`/download/Nightlight.pkg.sha256`; `404` until a notarized package is deployed) uses the same pairing: its
postinstall runs `pair <API> --web <WEB> --browser --install` as the person at the screen, which opens
`<WEB>/pair?code=…` in their browser, polls, and installs the background service (managed from the app) once they
approve. No new endpoints.

Heartbeat reply fields:

- `findings`: how many findings this report produced (a number).
- `jobs`: approved jobs handed to this device now, each exactly once (the same transaction marks them `running`).
- `pollEverySec`: `5` while the owner chatted in the last 5 minutes (the helper then calls `/helper/jobs/claim`
  every 5 s), else `0`.
- `watch`: up to 10 found devices this helper should check (`cid` and a port it reported open).
- `netKey`: the account's fingerprint key (64 hex characters), the same for all of its helpers; see
  [Lines the helpers see](#lines-the-helpers-see).
- `deviceNames`: whether found items may carry the names things announce (the owner's switch). A helper sends
  names only after a reply said `true` (an older server never does).

Heartbeat facts (anything else is rejected):

| Field | Limit |
|---|---|
| `helperVersion` | ≤16 characters |
| `os`, `arch` | ≤80, ≤16 |
| `cpuPct`, `memPct`, `diskPct` | 0-100 |
| `uptimeSec` | ≥0 |
| `containers[] {name, image, state, status}` | ≤50; `image` is name and tag only (no registry host, port, path or digest) |
| `failedUnits[]` | ≤50 names, ≤128 characters |
| `updatesPending` | 0-100,000 (apt, dnf or macOS `softwareupdate`, re-counted at most hourly) |
| `allowedJobs` | keys `restart_container`, `restart_service`, `diagnose`, `logs`; ≤20 valid names each: what the owner allowed **on the device** |
| `watchResults[] {cid, up, ms}` | ≤10; `cid` 12 hex characters, `ms` 0-60,000 or null |
| `failedAgents[]` | ≤20 labels, ≤100 characters: macOS background items (not Apple's) whose last run failed |
| `safety` | keys `passwordlessSudo`, `sshPasswordLogin`: true, false or null (unknown) |
| `net` | optional (helper 0.9.20+): `{self, selves[], gateway, peers[] {tag, why}}`; every tag is 20 hex characters or null; `selves` (helper 0.9.22+, ≤8) are all of the device's own private addresses, one per interface, `self` the main one; ≤20 peers; `why` is `time_machine`, `network_drive` or `service:<port>` with a port from 445, 2049, 548, 873, 5432, 3306, 1883, 8123, 32400, 9000. Omitted, the stored `net` stays |

Discovery items use a fixed vocabulary: `guess`, `vendor`, `services` and `ports` (22, 80, 443, 445, 631, 8123,
25565, 32400) must be one of the helper's known words or numbers; `cid` is a random 12-hex id; the optional `tag` is
the keyed fingerprint of its address (20 hex). Helper 0.9.22+ adds `maker` and `model`, read from what the thing
announces (the router's UPnP description, fetched from a few well-known places on the router only, UTF-8 without a
DTD, one 12-second deadline for the whole look: manufacturer, modelName and modelNumber, never friendlyName; mDNS TXT
records of printers, AirPlay and Apple devices, asked of the system's own mDNS service, `dns-sd` or avahi). The helper
only asks and never waits for incoming traffic, so it never raises a firewall prompt. **Both are allow-listed, never
free text**, by the same rules in the helper and the server: `maker` is one of about 70 home and office brands
(`real.MAKERS`, `422` otherwise), written as the list spells it ("Brother Industries, Ltd." is sent as `Brother`);
`model` comes only with a maker and is either an Apple model in plain words from a fixed table ("Macmini9,1" is sent as
`Mac mini`) or shaped like a product code: at most 40 characters and 5 words, a digit somewhere, every word made of
letters, digits and `/+-` and holding a digit, or a short all-capitals code, a single letter or a known series word
(`HL-L2350DW`, `DocuPrint CP115/118 w`, `Nighthawk R7000`). Anything else, a name ("Alex MacBook"), a host name, a
sentence, is dropped before it leaves the device and again on the server. It adds the services `router`, `media
player` and `media server` from the UPnP device type, with the guesses `Router` and `Media server`. No addresses or
other free text. While the account shows names (`deviceNames`), an item may carry `name` (≤60 printable
characters): the best of the Bonjour instance name ("Living Room"; a trailing hardware id such as "(1B:BE:CF)" is
cut), the UPnP friendlyName and the host name without `.local`. These are names, not addresses: the helper and the
server drop one that holds an IP or hardware address, a long hex id or anything the scrubber hides. The agent sees
them quoted, as data. The server scrubs every value of every
helper request. Free-text values such as container names come from the device and are shown as reported.

## Real devices

A real device that hasn't reported for **5 minutes** (or was revoked) is presented as `status: "offline"`,
`health: "unknown"` with no findings; show `lastSeen` so people know how fresh the data is. Real devices have
`realm: "real"` and `simulated: false`; they have no `demoGeneration` and are never touched by Reset or the sample
switch.

Extra device fields from the helper: `os`, `arch`, `helperVersion`, `allowedJobs`, `updatesPending`,
`containerCount`, `containersRunning`, `issueStates`, `historyAt`, `lastSeen`, `net` (fingerprints, below),
`watchState` (`silent` after the sweep noticed it stopped reporting, cleared by the next report), `revoked`,
`uninstalled`. Services come from containers (`category: "containers"`, `kind: "container"`) and failed system
services (`category: "system"`, `kind: "system"`, `unit`, `failed: true`).

**Watched devices** (added from discovery) have `kind: "watched"`, `realm: "real"`, `watchedBy` (the helper's device
id), `cid`, `checkPort`, `vendor`, `maker`, `model`, `vitals.latencyMs`. Their `role` comes from the router fingerprint, a
specific guess, the UPnP services, then words in the maker and model (a LaserJet is a printer, a Synology a file share). Their helper checks them each report (a TCP connect, 1 s):
`ok`, or `crit` with a `watched_down` finding. If the helper stops reporting, they go stale by the same 5-minute rule.

### Lines the helpers see

Helpers (0.9.20+) report which of your devices they rely on, so the map draws lines by itself, without any address
leaving a device. The server gives each account a random key (`netKey`, kept in `netKeys/{uid}`, which browsers can't
read) and hands it to that account's helpers only, in the heartbeat reply. A helper replaces every private IPv4
address (10/8, 172.16/12, 192.168/16; link-local, shared and public addresses are left out) by
`HMAC-SHA256(netKey, address)`, first 20 hex characters, and sends `net`: its own address's tag (`self`), its router's
(`gateway`) and `peers`: its Time Machine destination (`time_machine`), the servers of mounted network folders
(`network_drive`) and established connections to known service ports (`service:<port>`; never remote login, port 22),
looked up at most every 30 minutes. A found device's `tag` becomes its `net.self` when it is added to the map. Equal
tags within one account mean the same address, so the server matches them: a peer that is another device's `self`
gives a `backup` line (Time Machine) or a `depends` line (shared folder, service), from the device that relies to the
one it relies on; a device whose `self` is the others' `gateway` gets a `network` line from each of them. A helper
(0.9.22+) also sends `selves`, every one of its own addresses, so a found thing on its second interface is still
recognised as that device. A watched thing gets a `network` line to the router of the device that found it ("found on
the same network as Mac mini"), unless it is that router. Automatic
lines have `source: "auto"` and `why`; a line the person drew (or one between the same two devices) is never changed,
a deleted automatic line is not drawn again, and automatic lines stay until deleted. **Privacy reasoning:** stored
data, logs, exports and other accounts never see an address, and tags from different accounts can't be compared. A
tag is not encryption: whoever holds the key could try every private address, which is why the key stays on the
server and the account's own helpers. Two places on one account that use the same private addresses (two homes both
on 192.168.1.x) can look like one network.

**Findings** on real devices carry `state`: `new` (needs a look), `known` (leaving it on purpose) or `snoozed`.
The health light counts only `new` findings. A known or snoozed finding becomes `new` again when its severity rises or
the snooze ends; states for findings that went away are dropped. Finding ids are stable per problem and safe to use
in the issues route.

Checks: `disk_over_80`, `disk_over_90`, `memory_high`, `service_down`, `container_down`, `updates_pending`,
`restart_overdue` (over 180 days), `background_items_failing`, `passwordless_admin`, `ssh_password_login`,
`watched_down`.

## Jobs on real devices

| `actionType` | `params` | `riskClass` | Card? | Proposed only when |
|---|---|---|---|---|
| `restart_container` | `{"container":"name"}` | `service` | always | the container is in `allowedJobs.restart_container` and isn't running |
| `restart_service` | `{"unit":"pihole-FTL.service"}` | `service` | always | the exact unit is in `allowedJobs.restart_service` and the device reports it failed |
| `diagnose` | `{"target":"name"}` | `read` | no | the target is in `allowedJobs.diagnose` and the device reported it; log lines only if also in `allowedJobs.logs` |

The server can't widen `allowedJobs`, and the helper re-checks it before acting. The server sends a job name and
target, never a command. A real job never runs without a tap, whatever the trust settings (except `diagnose`, which
is read-only and created already `approved` with `decision.by = "owner_allowed_on_device"`). Proposals for a device
that isn't reporting are refused. Lifecycle:

| `status` | Meaning | What the UI shows |
|---|---|---|
| `pending` | card waiting for the person | Approve / Not now |
| `approved` | approved; the device picks it up on its next report or claim | "Waiting for the device…" |
| `running` | handed to the device (exactly once) | "Running on the device…" |
| `done` / `failed` | the device reported; `result.summary` says what happened | the result; then the follow-up |
| `denied` | declined | follow-up as usual |
| `stale` | withdrawn: a reset happened before the device picked it up, or the device was revoked | "Out of date" |

Results: restart jobs set `result {ok, summary, before, after:{state}}`; `diagnose` sets
`result {ok, summary, output, hidden}`, where `output` (≤4,000 characters) is what the look found, scrubbed on the
device and again on the server, and `hidden` counts values the server hid.

The follow-up turn is created when the device reports: watch the action document and open
`POST /api/turns/{continuationTurnId}/stream` once `continuationTurnId` appears. A job already on the device when a
reset happens is still recorded when it reports, but gets `followUp: "skipped_after_reset"` and no follow-up turn.

**Look into (`diagnose`) in a chat.** The agent's `look_into` tool waits up to 15 s inside the turn. If the device
answers in time, the agent explains it in the same reply. Otherwise the action gets `followUp: "wanted"`, the stream
sends `{"type":"followup_pending","turnId":"cont_act_…"}`, and exactly one follow-up turn is queued when the result
arrives: open that turn's stream once the action has `continuationTurnId` (retry on `409 turn_in_progress`).

**Look around (`inspect`).** Same flow, read-only and without a card. `params: {"what": [names]}`, 1 to 4 of `disk`,
`processes`, `updates`, `docker`, `network`, `load`, `failed`, each one the device lists in `allowedJobs.inspect`
(helper 0.8+, reported when "check why something stopped" is on). The agent's `inspect` tool uses it before answering
questions about space, speed, connectivity or updates. `updates` can take up to a minute, so it usually ends in a
follow-up.

**Playbooks.** `GET /api/devices/{id}/playbooks` lists what a real device can run (`suggested` when a current
problem matches). `POST /api/devices/{id}/playbooks/{playbookId}/run {"sessionId"}` → `202 {actionId}`: an
`inspect` action with `playbook` set. When the device answers, `result.playbook` holds
`{id, title, found: [{cause, say, advice?, fix?, fixAllowed?}], nothing}` (matched on the server, no model call) and
one pending `fix` card is created per allowed clean-up. The library is `api/src/nightlight_api/playbooks.yaml`.

**Clean-ups (`fix`).** `params {"recipe": name}`, one of `empty_trash`, `brew_cleanup`, `npm_cache`,
`xcode_build_data`, `docker_prune`, `apt_clean`, `journal_vacuum`, only when the device lists it in
`allowedJobs.fix` (helper 0.9+). Always an approval card. `result: {ok, summary}` (the summary says how much space was
freed). Permissions: `cleanup` (bool) in `POST /api/devices/{id}/permissions`.

**Capabilities and events (architecture).** Everything a real device can be asked to do is one entry in
`api/src/nightlight_api/capabilities.py` (`docs/adr/0001-capability-registry.md`): how its card is built, how it is
approved (`device`: allowed on the device, no card; `card`: one tap, or the owner's confirmation in the app;
`passkey`: a card signed with the owner's passkey), and what follows its approval and its result. Follow-ups are
**event turns** (`docs/adr/0002-conversation-events.md`): `kind: "event"`, `event` (`job_finished`,
`job_declined`, `investigation_approved`), `mode`, and `policy` (`narrate`: tell what happened, no tools;
`continue`: carry on with tools, e.g. after an investigation was approved). The turn id is still
`cont_<actionId>` and is opened the same way.

**Work channel.** Between reports the helper keeps `POST /helper/jobs/wait {}` open: the server holds it up to 25 s
with a Firestore listener on the device's approved jobs and answers as soon as one appears (`{jobs:[...]}`, the same
at-most-once hand-over as `claim`), or with `{jobs:[]}` when the hold ends. `POST /helper/jobs/claim` stays for helpers
older than 0.9.13 (`docs/adr/0003-job-channel.md`).

**Helper updates.** `GET /helper/release` → `{version, sha256}`; `GET /helper/release/nightlight_helper.py` and
`.sig` (public). Heartbeat responses carry `latestHelper`. `POST /api/devices/{id}/update {}` (signed-in owner) →
`202 {actionId, version}`, an approved `update_helper` job; `409` codes: `no_release`, `up_to_date`,
`update_by_hand` (helper older than 0.9: rerun the install line once), `updates_off`, `device_not_reporting`,
`resetting`. The result goes to Activity. Permissions add `updates` (default true) and `autoUpdate` (default false).

**Chat history.** Messages live at `users/{uid}/sessions/{sid}/messages/{msgId}`
`{role, text, seq, turnId, mode, toolCalls?, actionIds?, error?, createdAt, expiresAt}`. Each tool call is
`{name, args, textOffset, summary?, details?, ok?, ms?, actionId?, unfinished?}`: `textOffset` is the length of
`text` in UTF-16 code units (as JavaScript counts) when the step began; `actionId` is the card the step put up (shown
right after it); `unfinished: true` (with `ok: false`) marks a step that never answered because the turn ended
(splitting `text` there rebuilds the live order of words and steps), `ok` is false when the tool reported
`error`/`refused`/`failed`, `ms` is how long it took. `mode` is `quick` or `investigate`. A turn that failed after
some words were shown keeps them with `error: {code, message}`. Closing the stream stops the turn: it ends
at once as failed with code `stopped` (words and steps so far kept), and the session is free for the next message. Messages are readable by the owner through Firestore
(the web app reads them in `seq` order when the chat opens). `expiresAt` is 30 days after writing; a Firestore TTL
policy on the `messages` collection group deletes them after that.

**Removing a device.** `POST /api/devices/{id}/remove {}` (signed-in owner; the confirmation in the app is the
approval) → `202 {removed: "asked_device", actionId}` when the helper (0.9.6+) will uninstall itself, or
`{removed: "access_cut"}` when the device is silent, revoked or older: tokens revoked and the device archived now.
From chat the agent's `remove_device` tool puts up a pending card; approving it does the same. The helper's
`POST /helper/leave {"cleanup": "full"|"files_left"}` (body optional) archives the device and closes the removal in one
transaction. Archived devices carry `archived`, `archivedAt`, `purgeAt` (30 days); they are hidden from the map and
the agent. `GET /api/devices/removed` lists them; `DELETE /api/devices/{id}` deletes an archived device and its
services, history, notes, events and actions now (`409 remove_first` if it isn't archived). The sweep purges the
rest when `purgeAt` passes.

**Notebook.** `users/{uid}/devices/{id}/notes/{noteId}` `{text, by: "nightlight"|"you", at}`, read with Firestore.
`POST /api/devices/{id}/notes {"text"}` (201; `422` with `msg: "looks_secret"` when it looked like a secret),
`DELETE /api/devices/{id}/notes/{noteId}`. At most 30 per device.

## Keeping watch

- **Sweep:** Cloud Scheduler calls `POST /internal/sweep` every 5 minutes with a Google-signed OIDC token (audience
  `<API>/internal/sweep`, the configured invoker account; `401 invalid_token` / `403 forbidden` otherwise). It marks
  real devices silent after 5 minutes without a report (event `silent`, once), checks watched websites least recently
  checked first, retires watches older than 30 days and prunes registry rows of removed devices. Reply
  `{ok, newlySilent, watchesChecked, pruned}`. Not for browsers.
- **Watched websites:** http(s) only, no user name or password; every resolved address must be public (checked when
  added and before every check). The check connects to that checked IP, reads only the status line (up = any answer
  below 500; redirects not followed, body never downloaded), 6 s deadline. Changes produce `watch_ok` / `watch_crit`
  events.
- **History:** written by the heartbeat, at most every 5 minutes per device, kept 8 days.

## What Nightlight remembers (Memory Bank)

The agent can keep short facts about the person between chats, e.g. "the kids play Minecraft on weekends". It saves
one only when the person tells it something lasting, through a `remember` tool (the stream shows
`{"type":"tool_call","name":"remember","args":{"fact":"…"}}` and a `tool_result` with summary `status saved`,
`status refused` or `status error`). Facts are at most 300 characters; a fact that looks like a password, key, token
or email address is refused, not stored. At the start of each question turn the agent uses the person's newest facts
(cached for a few minutes per server instance); live device facts always win over a remembered fact.

Facts are kept per user (the uid from the token) in Agent Platform Memory Bank, not in Firestore, so there are no
listeners: use `GET /api/me/memories` for a "What Nightlight remembers" panel. `POST /api/demo/reset` also forgets
them; `POST /api/demo/template` doesn't. A deletion may take a moment to show in the list. When `enabled` is `false`
(memory not configured), the list is always empty and the agent has no `remember` tool.

## The approval flow (sample home)

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

## Sample-home jobs, incidents and checks

| Job (`actionType`) | What it does | `riskClass` | Can run on its own? |
|---|---|---|---|
| `rotate_logs` | clean up log files older than 7 days | `routine` | yes, once trusted |
| `backup_world` | save a copy of a game world (players keep playing) | `routine` | yes, once trusted |
| `restart_server` | restart a game server to clear memory (players disconnected ~1 min) | `service` | no, at most "Ask me for new things", and never on its own |
| `update_server` | back up, then update a game server (players disconnected ~2 min) | `service` | no, as above |

Demo incidents (`POST /api/demo/inject` `kind`): `disk_full`, `logs_locked` (the next job fails), `server_lagging`,
`backup_overdue`, `update_available`. Game incidents only apply to game servers (`422 incident_not_applicable`
otherwise).

Findings (`check`) on sample devices and services: `disk_over_90`, `memory_high`, `backup_overdue`,
`update_available`, `backup_never_test_restored`; each has `id`, `severity` (`crit`/`warn`/`info`), a plain
`message`, `evidence` and the `svcId` it concerns. A device's health light reflects its own and its services'
findings.

Game services also carry `version`, `latestVersion`, `updateAvailable`, `players {online, max}` and
`lastBackupDaysAgo`. Services have a `category` (`home`, `network`, `files`, `games`) for the category filter.

## Trust levels

| Level | Shown as |
|---|---|
| `ask` | Always ask me |
| `ask_new` | Ask me for new things |
| `auto` | Just handle it and tell me |

Precedence: a service setting beats a device setting, which beats the job's level, which beats the global default.
Risky jobs have a ceiling. Trust applies to sample-home jobs only; real-device jobs always ask.

## Events (Activity)

| Realm | Fields | `kind` values |
|---|---|---|
| sample home | `deviceId`, `kind`, `severity`, `message`, `svcId`, `source: "demo"`, `demoGeneration`, `at` | the incident kinds above |
| real (`realm: "real"`) | `deviceId` (null for a website), `kind`, `severity`, `message`, `who`, `at` | `joined`, `left`, `revoked`, `removed`, `found`, `status_ok`, `status_warn`, `status_crit`, `issue_new`, `issue_known`, `issue_snoozed`, `silent`, `back`, `watch_ok`, `watch_crit` |

`who` is `you` (the owner did it), `device` (the device reported it) or `nightlight` (the sweep noticed it). Reset
deletes sample-home events only.

## Stream events

```
{"type":"turn_start","turnId":"…","attempt":1,"messageId":"…","at":"…"}            (replay adds "replay":true)
{"type":"text","delta":"…"}
{"type":"tool_call","name":"get_device","args":{"device_id":"pi-1"}}
{"type":"tool_result","name":"get_device","summary":"…","details":null,"ok":true,"ms":412,"redacted":0}
{"type":"approval_request","actionId":"…"}
{"type":"followup_pending","turnId":"cont_act_…"}                                  look_into handed off to a follow-up
{"type":"error","code":"…","message":"…","retryable":false}                         terminal
{"type":"done","turnId":"…","metrics":{"latencyMs":…,"firstTextMs":…,"modelCalls":…,"toolCalls":…,"tokensIn":…,"tokensOut":…,"tokensThinking":…,"costUsd":…}}   terminal
```

## Errors

| Status | Meaning | Body |
|---|---|---|
| 401 | missing, invalid or expired token; unknown, used or expired code | `{error, code:"invalid_token" \| "invalid_code"}` |
| 403 | allowed in principle but not for this caller or switched off: `sign_in_required` (anonymous on an owner route), `kill_switch`, `forbidden` (sweep caller) | `{error, code}` |
| 404 | not found, **or owned by another user** (same answer) | `{error, code:"not_found"}` |
| 409 | `illegal_transition`, `decision_conflict`, `stale`, `turn_in_progress`, `offer_obsolete`, `request_mismatch`, `resetting`, `reset_in_progress`, `already_decided`, `already_added` | `{error, code, actionId?, turnId?, retryAfter?}` |
| 422 | unknown or invalid field; our own reasons: `bad_url`, `unknown_host`, `private_address`, `no_check_port`, `tag_too_long`, `sample_devices_keep_their_names`, `snooze_needs_days`, `unknown_template`, `unknown_incident`, `incident_not_applicable`, `real_device_read_only` | `{"error":"validation_error","code":"invalid_body","detail":[{"loc":[…],"msg":"<reason>"}]}` |
| 429 | a limit: `quota_uid`, `quota_ip`, `quota_global` (usage), `too_frequent`, `slow_down` (helper pacing), `too_many_watches`, `watch_budget`, `watch_capacity` | `{error, code, retryAfter?}` + `Retry-After` when known |

Sample-home error bodies are in `contracts/mocks/errors.json`.

## Chat retries

- Create `clientRequestId` with `crypto.randomUUID()` when the user sends a message; reuse it to retry that message.
- If a stream drops, call `POST /api/turns/{turnId}/stream` for the same turn. A retry never repeats an action the
  agent already took.
- "Ask again" is a new message with a new `clientRequestId`.
