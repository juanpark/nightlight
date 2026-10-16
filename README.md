# Nightlight

**A house-sitter for your home and small-office servers.** Nightlight shows every device you run, and what runs on
it, on one friendly map. A Gemini agent keeps watch, explains problems in plain words, and fixes them with your
permission. It starts by asking about everything and earns more freedom only when you say so.

Built for the Google Cloud AI Builder Cup 2026 (category: Future of Work & Enterprise Productivity).

> Status: in development. The backend and agent are deployed on Cloud Run; the web app is being built.

## Who it's for

People who run a few machines that matter to them but have no IT person: a family with a NAS full of photos, a
Raspberry Pi running a home VPN, home automation, someone hosting a Minecraft world for their kids, a dental clinic or
a small office. Existing AI operations tools are built for engineers (terminals, chat windows, one on/off switch for
the agent). Nightlight is visual and plain-language.

## How it works

1. **See everything.** Places hold devices; devices hold the services that run on them. Each shows a health light and
   one plain sentence ("The Minecraft world hasn't been backed up in 9 days").
2. **Ask.** "Is anything wrong at home?" The agent reads the devices with tools and answers in two short sentences.
3. **Approve.** When a fix helps, the agent proposes it on an approval card: what it will do, a dry run, what it
   touches, how to undo it, and a risk badge (safe / some risk / risky). Nothing changes until you tap Approve.
4. **Trust grows, one kind of job at a time.** After three approved successes of the same kind of job, Nightlight may
   ask whether it can handle that job on its own next time (only for jobs that are allowed to run on their own and
   not pinned by you). Risky jobs have a ceiling (restarting a game server always asks), and a failure moves an
   unpinned job's trust back down a step.

| Trust level | What the agent does |
|---|---|
| Always ask me | explains and waits for a tap |
| Ask me for new things | does familiar safe jobs on its own, asks about anything new |
| Just handle it and tell me | acts, then reports in plain words |

## Try it

The demo uses a **simulated sample home** (clearly labelled): a Raspberry Pi with a VPN and a car-data logger, a Mac
Mini running home automation, a NAS, a Minecraft game server, a camera recorder and a router. Judges can use the
one-click demo; no account is needed.

Sample questions that work:

- "Is anything wrong at home?" (the Pi's disk is 94% full; it proposes cleaning old logs)
- "My kids say Minecraft is really laggy tonight. Can you help?" (memory is nearly full; it proposes a restart)
- "When was the Minecraft world last backed up?"
- "Is there an update for the game server?"

The demo panel can trigger incidents: disk full, a failing job, a lagging game server, an overdue backup, an
available update.

## Real devices (the helper)

A small Python script ([`helper/nightlight_helper.py`](helper/nightlight_helper.py), standard library, psutil if
present) joins your home with a one-time code made in the app and then reports health facts every minute: disk,
memory, CPU, uptime, stopped system services, containers (name, image name and tag, state), pending updates. It never
sends hostnames, IP addresses, logs or credentials, talks HTTPS only, and keeps its device token in an owner-only
file. By default it changes nothing. The owner can allow one kind of job **on the device itself**: restarting a
stopped container they name. Even then it runs only after a tap on the approval card; Nightlight sends a job name and
target, never a command, and the helper decides what it runs. A device that hasn't reported for 5 minutes is shown as offline with unknown health. Tested on a Raspberry Pi
(Python 3.9).

```bash
python3 nightlight_helper.py show                      # preview exactly what would be sent
python3 nightlight_helper.py enrol <API_URL> <CODE>    # join with a one-time code (valid 10 minutes, single use)
python3 nightlight_helper.py run                       # keep reporting
python3 nightlight_helper.py allow restart_container <NAME>   # optional: allow restarting this container
```

### Allow restarting a service

Restarting a system service needs administrator rights. The helper uses `sudo -n` (it never asks for or stores a
password), so allow it for that one service only, once, on the device:

```bash
python3 ~/.local/share/nightlight/nightlight_helper.py allow restart_service pihole-FTL.service
echo "$USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart pihole-FTL.service" \
  | sudo tee /etc/sudoers.d/nightlight-pihole && sudo chmod 0440 /etc/sudoers.d/nightlight-pihole
```

Raspberry Pi OS's default user can already use `sudo` without a password (Nightlight reports this as a safety
finding), so there the first line is enough. Either way, every restart still waits for your tap on the approval card.

## Architecture

```
Browser (Next.js) ── Firebase Authentication (Google sign-in, one-click demo)
   │  HTTPS + ID token (REST + streamed replies)          Firestore (live, read-only listeners per user)
   ▼                                                              ▲
Nightlight API on Cloud Run (FastAPI) ────────────────────────────┘
   └─ Gemini agent (ADK, in-process) ── Gemini 3.5 Flash-Lite on Google Agent Platform
```

- **Only our own authenticated routes are public.** The agent runs inside the API; the user id comes only from the
  verified Firebase token, and every record lives under that user.
- **Every approval is one Firestore transaction**: the decision, the device and service changes, the result, the
  trust update and the queued follow-up turn commit together, so a job never runs twice (tested with 10 simultaneous
  approvals). The follow-up reply is then generated in its own step.
- **The agent proposes, it never acts directly.** Action tools create approval cards; only approved (or explicitly
  trusted) jobs run.
- **Reset is safe under concurrency**: a barrier blocks all demo writes while the sample home is re-created.

## Google technology

| Service | Use |
|---|---|
| Gemini on Google Agent Platform | the agent's reasoning and plain-language explanations (3.5 Flash-Lite by default; configurable, but model, thinking level and pricing must be changed together) |
| Agent Development Kit (ADK, Python) | tools, the agent loop and streaming |
| Cloud Run | hosts the API (and the web app); scales to zero |
| Firestore | devices, services, approval cards, trust levels, chats; security rules keep each user's data private |
| Firebase Authentication | Google sign-in and the one-click demo |

## Guardrails

- **Approval before action**, with dry run, blast radius, rollback and a risk badge; risk ceilings on the trust ladder.
- **Secrets are scrubbed** from chat text, tool results, model output and history before they are stored, shown or
  sent to the model (best effort; patterns plus sensitive keys). Real device helpers are designed to never send
  credentials at all.
- **Cost is bounded before any model call**: each call reserves its worst-case cost (full input and output limits)
  against a model budget, with per-user, per-visitor and daily limits and a kill switch; input size is checked with
  Gemini's own token counter, and output (including thinking) is capped.
- **Stale work can't land**: chat turns hold a lease; after a reset or a takeover, a stale turn can't reserve new
  model calls or commit results (a call already admitted may still run, but its result is discarded).

## Data sources

The demo's devices and incidents are **synthetic** and labelled as such. Health checks are deterministic rules over
device data; the model explains them. It is instructed to use only the supplied summary and its tools and not to
invent device state, but generated explanations can still be wrong; the approval card shows the facts from the
device data.

## Performance

Measured against the real model with `scripts/bench.py` (details in [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md)):
question about 3.8 s, follow-up after approval about 1.6 s, about $0.0012 for the whole story.

## Run locally

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), the Firebase CLI (for the Firestore emulator),
Java 21 (for the emulator).

```bash
./scripts/test_api.sh            # the API test suite against the Firestore emulator (no cloud access needed)
./scripts/secret_scan.sh         # secret scan of staged changes and history
```

The API contract for the web app is in [`docs/API.md`](docs/API.md); sample data for every state is in
[`contracts/mocks/`](contracts/mocks/).

## Known limits

- On real devices the only job is restarting a container the owner allowed on the device; everything else is
  explained, not changed.
- Answers are kept short on purpose; very long conversations are trimmed or refused rather than cut off silently.
- The approval card's "undo" is simulated in the demo.
