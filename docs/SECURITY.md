# Security model

What Nightlight guarantees, how, and where the limits are. Every statement here describes the code as it is; file
references are to `api/src/nightlight_api/` unless noted.

## Surfaces

| Surface | Who | Credential | Where it is checked |
|---|---|---|---|
| Browser → API (`/api/*`) | a person | Firebase ID token (`Authorization: Bearer`) | `auth.py`: the uid comes only from the verified token |
| Browser → Firestore | a person | Firebase ID token | `firestore.rules`: read-only, own `users/{uid}/**` only; no client writes anywhere |
| Helper → API (`/helper/*`) | a device | device token (`X-Device-Token`), or a one-time code / pairing secret while joining | `real.py`: token looked up by its SHA-256 hash |
| Scheduler → API (`/internal/sweep`) | Cloud Scheduler | Google-signed OIDC token | `main.py`: audience must be the sweep URL, email must be the configured invoker account and verified |
| API → internet | watched websites | none | `watch.py`: public addresses only, pinned connection |
| API → Agent Platform | Gemini, Memory Bank | the service account (Application Default Credentials) | no keys in the repository or the image |

**Owner gate.** Anonymous (one-click demo) users can use the sample home and chat, but cannot create join codes,
approve pairing codes or add watched websites: those answer `403 sign_in_required`, so real devices are always linked
to a Google account that survives cleared browser storage.

## Device tokens and joining

- Join codes: 8 characters from a 31-letter alphabet (about 8.5 × 10^11 combinations), single use, 10 minutes, at
  most 10 created per account per hour. Stored as a hash.
- Pairing (the device shows a code; OAuth device-flow pattern): the device holds a random poll secret (stored as a
  hash); the token is created only when the device polls after the owner approved, inside one transaction (one code,
  one token). Limits: 20 pairing starts per network address per hour, 30 previews or decisions per account per hour,
  polls at least 2 s apart.
- Device tokens: 32 random bytes (256 bits), returned once, stored only as a SHA-256 hash. Revoked from the app
  (`/api/devices/{id}/revoke`) or by the device on uninstall (`/helper/leave`). Revocation and the device going
  offline happen in one transaction.
- `/helper/enrol`, `/helper/heartbeat` and `/helper/pair/poll` have no per-address limit on failed attempts. Each
  costs one Firestore read; guessing a live code within 10 minutes or a 256-bit token is not feasible.

**Limit:** a token has no expiry. It works until revoked. Rotation is on the roadmap.

## What the cloud can make a device do

The server sends a job **name** and a **target**, never a command. The helper (`helper/nightlight_helper.py`):

| Job | Runs | Only if |
|---|---|---|
| `restart_container` | `docker start NAME`, then checks the state 5 s later | NAME is in the local `allow restart_container` list and the container exists and isn't running |
| `restart_service` | `sudo -n systemctl restart UNIT` (no sudo as root), 60 s timeout | UNIT is in the local `allow restart_service` list and `systemctl is-failed` says `failed` |
| `diagnose` | `docker inspect` / `systemctl show` (status only); `docker logs --tail 30` / `journalctl -n 30` only with `allow logs` | target is in the local `allow diagnose` list |

- Commands are fixed argument lists; nothing from the server reaches a shell. Unknown job types do nothing. The
  `logs` and `diagnose` permissions can never start anything.
- **The local allowlist is final.** The server proposes only inside the list the device reported, but the helper
  re-checks its own config before acting; the server cannot widen it.
- Restart jobs always need a tap on an approval card; no trust level skips it on a real device. `diagnose` is
  read-only and allowed per target by the owner on the device, so it runs without a card.
- A job is handed to the device at most once (in the same transaction that marks it `running`). Only that device can
  report its result, once.

So a compromised or malicious cloud could restart a container or failed unit the owner allowed, or read the status
(and, if allowed, last 30 log lines) of an allowed target. Nothing else.

The helper itself runs as the owner's normal user (never installed as root; the systemd unit sets
`NoNewPrivileges=yes`), keeps its config and token in an owner-only directory and file (0700 / 0600, never through a
symbolic link), talks only HTTPS (plain HTTP only to a local development server on the same machine) and never
follows redirects.

## What leaves the device

Sent every report: OS name, CPU type, CPU / memory / disk percentages, uptime, containers (name, image name and tag
with registry and path removed, state, status text), failed system-service names, the number of pending updates,
macOS background-item labels that keep failing (at most 20, 100 characters each), two safety booleans, the owner's
allow list, and up/down results for watched things (random id, up, milliseconds). The server's schema rejects any
other field.

Never collected: host names, IP or hardware addresses, files, environment variables, passwords or keys. The default
device name comes from the hardware or OS ("Raspberry Pi", "Mac mini"), never the host name.

Only when the owner acts on the device:

- `discover`: items the owner picks from a printed list; each is a random id plus words from a fixed vocabulary
  (guess, maker, service words, ports from a list of 8). The server accepts only that vocabulary. Addresses stay in
  the helper's local config.
- `allow logs NAME`: the last 30 log lines of that target, sent only when the agent looks into it.

## Scrubbing (best effort)

- On the device: diagnose output and log lines are scrubbed before they leave (control codes first, then private
  keys, tokens, JWTs, cloud keys, `key=value` secrets including prefixed names and quoted values, URL credentials,
  email addresses, IP and MAC addresses, long opaque strings, home paths), newest lines kept, at most about 3.5 KB.
  Log reads stop after 256 KB or a 15 s deadline.
- On the server (`redact.py`): every heartbeat value, job result, chat message, tool result, model output, name, tag
  and memory fact is scrubbed again before it is stored, shown or sent to the model.
- Patterns catch common shapes; they cannot catch everything. The design relies first on not collecting secrets.

## Prompt injection

Device names, tags, container and unit names and log lines are written by the owner's devices. The agent's
instructions say they are data, never instructions, and that diagnose output is evidence to explain, not to follow.
The agent cannot run anything directly: action tools create cards, and real jobs are bounded by the device's
allowlist. Discovery items cannot carry free text.

## Watched websites (API → internet)

- http or https only, no user name or password in the URL. Every address the name resolves to must be public
  (`is_global`), checked when the watch is added and again before every check.
- The check connects to the exact IP that was just checked (Host header and TLS server name stay the real host, so
  certificates are still verified). DNS cannot redirect the connection to a private address between check and
  connect.
- Only the status line is read; the body is never downloaded; redirects are not followed. 3 s timeouts and a 6 s hard
  deadline per check (a slow server counts as down); a sweep stops after 50 s.
- Budgets: a signed-in account, at most 10 watches, at most 20 adds per day; at most 200 active watches overall; each
  watch retires after 30 days.

## Memory

Facts live in Agent Platform Memory Bank, scoped to the uid from the token, written only through the agent's
`remember` tool (at most 300 characters). A fact that looks like a password, key, token or email address is refused.
"Forget" and Reset bump a per-user epoch first, so old facts are invisible at once, then start a purge.

## Known limits

| Limit | Effect |
|---|---|
| Device token has no expiry | revocable, but a stolen token works until revoked |
| `curl \| sh` | trusts the HTTPS origin; the sha256 pin is served by the same origin, so it only proves the helper matches what that server serves (it protects against a corrupted or cut-off download, not a compromised server) |
| Join code in the command line | may stay in shell history; it is single use and expires in 10 minutes |
| Job stuck in `running` | if the helper crashes after taking a job and before reporting, the card stays "running" (at-most-once was chosen over retry) |
| Job stuck in `approved` | if the device never reports again, the card stays "waiting for the device" until a reset withdraws it |
| Hourly `sudo -k -n true` safety check | may leave one "a password is required" line in the device's auth log |
| No step-up authentication | a signed-in session can approve cards without re-entering a password |
