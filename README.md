# Nightlight

![Live app version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fnightlight-api-1032111130355.asia-northeast3.run.app%2Fapi%2Fversion&query=%24.app&label=app&color=2d3a5e) ![Live build](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fnightlight-api-1032111130355.asia-northeast3.run.app%2Fapi%2Fversion&query=%24.build&label=build&color=596071) ![Helper served](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fnightlight-api-1032111130355.asia-northeast3.run.app%2Fapi%2Fversion&query=%24.helper&label=helper&color=b8720a)

*The badges are read live from the deployed API (`/api/version`). The app version is the repo's `VERSION` file; the
build is the git commit that was deployed. On a device, `nightlight --version` prints the helper's version.*

Nightlight looks after the computers people run at home or in a small office when there is no IT person: the
Raspberry Pi with the VPN, the NAS with the family photos, the kids' Minecraft server, the clinic's file server.
It puts every device and what runs on it on one map. It watches them, explains problems in plain words, and fixes
them only after you tap Approve. Over time it earns permission to handle routine jobs on its own, one kind of job at a
time.

**Live app:** https://nightlight-web-1032111130355.asia-northeast3.run.app (one click, no account needed)

Built for the Google Cloud AI Builder Cup 2026 (theme: Future of Work & Enterprise Productivity) by team **8yte**.

**Trying it for the first time? Start here:** [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md).  
**What we tested, what is wrong, and what comes next:** [`docs/LIMITS-AND-ROADMAP.md`](docs/LIMITS-AND-ROADMAP.md).  
**Why a cloud service can be trusted with your machines:** [`docs/SECURITY-MODEL.md`](docs/SECURITY-MODEL.md);  
**passkeys for owners, step by step:** [`docs/PASSKEYS.md`](docs/PASSKEYS.md).

## Try it in 30 seconds

1. Open the live app and take the guided tour of the sample home. The devices are pretend; Nightlight's AI is real.
   The sample home has a Raspberry Pi (VPN and a car data logger), a Mac Mini (home automation), a NAS (photos and a
   nightly backup), a Minecraft server, a camera recorder and a router. Everything in it is labelled "Sample".
2. In the chat, ask: **"Is anything wrong at home?"**
3. Nightlight reads the devices, answers in two or three short sentences, and puts up an **approval card** for the
   most serious problem: the Pi's disk is 94% full, and it offers to clean old logs. Nothing changes until you tap
   Approve.
4. Tap Approve. The job runs, the card updates, and the chat tells you what happened.

**Demo tools** lets you cause more problems (a full disk, a lagging game server, an overdue backup, an available
update) and reset the sample home. Sign in with Google to add your own devices.

## The core loop

| Step | What Nightlight does | Where it lives |
|---|---|---|
| **Watches** | Each device shows a health light and one plain sentence ("The Minecraft world hasn't been backed up in 9 days"). Devices with the helper report every minute. A sweep every 5 minutes marks devices that stopped reporting and checks watched websites, so problems are noticed when nobody is looking. | `api/.../sim.py`, `real.py`, `watch.py`, `main.py` (`/internal/sweep`) |
| **Explains in plain words** | A Gemini agent reads the devices through tools and answers without jargon. Before answering "why is it full, slow or offline?" about a real device, it runs fixed read-only checks on that device and answers with names and sizes, not guesses. | `agent.py`, `playbooks.yaml`, helper `inspect` |
| **Asks before fixing** | Every change is an approval card: the plan, a dry run, what it touches, how to undo it, a risk badge. One tap approves or declines. A card exists only when the model called the tool that makes one, and the chat shows every card and step from server events, never from the model's words, so the model cannot claim a job it did not propose. | `actions.py`, `capabilities.py`, `agent.py`, `turns.py`, `web/components/ApprovalCard.tsx` |
| **Earns trust per kind of job** | After three approved successes of the same routine job, Nightlight may offer to handle that job on its own. Restarts and updates always ask, however many times you approved them. A failure moves trust back down a step. On real devices every job waits for a tap. | `trust.py`, `web/components/TrustPanel.tsx` |

Trust levels, in the words the app uses:

| Level | What the agent does |
|---|---|
| Always ask me | explains and waits for a tap |
| Ask me for new things | does familiar safe jobs on its own, asks about anything new (restarts and updates still ask) |
| Just handle it and tell me | acts, then reports in plain words |

The trust ladder is built and works end to end: three good runs of a safe job, an offer, your yes, and the next one
runs on its own and says so; a failure moves it back a step. Today it is switched on for the sample home only, on
purpose. On your real devices every restart, clean-up or removal still waits for your tap, whatever the trust settings
say, until the fixed job list has more hours behind it. The one exception is a signed helper update, which may install
on its own if you allowed that.

## What you get

| Area | What it is, and why it matters |
|---|---|
| Map | Every device on a graph-paper canvas that opens fitted to any screen (pan, pinch, zoom). Devices snap to the grid where you drop them. Lines between devices say how they relate (connected through, backs up to, relies on, powered by); you draw one by dragging from one device to another, and the agent uses them to answer "what depends on the router?". Tags, filters, Live / Sample marks and a list view. |
| Device cards | A device's card opens on the map and lists its apps, the ones that need a look first, then starred ones, up to twelve. Tap an app for its own view: what it is in one plain line, how it is doing, its version, and the notes, fixes and jobs about it. |
| Favorites | Star a device or any of its apps. Up to three starred apps show on the device's card, and a Favorites chip narrows the map to what you care about. |
| Device drawer | A panel from the left with one job per tab (Overview, Apps, Knowledge, Settings). The map stays usable beside it. |
| The map follows the chat | While the agent works, the devices its steps touch glow, so you can see where it is looking. When it is done, the main device opens with the apps it named pulsing. It never moves the view while you are touching the map; with reduced motion on, the view moves without animation. |
| Chat | Answers stream in as they are written, with each step and its result shown live. Under every answer a receipt shows steps, seconds, model and cost, so you know what the answer was based on and what it cost. Quick mode for everyday questions; "Investigate deeply" for a longer look, with a visible time budget. A Stop button keeps what was already done. Answers render bold, lists and code safely, and come back in the language you wrote in. |
| Conversations on every device | Chats belong to your account, not to one browser. Sign in on another computer, tablet or phone and the conversation you used last opens; Conversations lists the rest (first question and when) and starts a new one. History is kept 30 days. |
| Status board | Every check on every device at a glance (✓ fine, ! needs a look, ✗ broken), with a summary line like "39 checks: 35 ok, 3 warnings, 1 critical". It is built straight from what the devices reported, with no AI in between: it cannot make anything up, it costs nothing, and it shows instantly even when Gemini is slow. Unknown is shown as unknown. Copyable as text. |
| First-run tour | A short walkthrough of each part of the screen on the first visit, replayable from Settings. |
| An agent that admits limits | It says plainly what Nightlight can't do (Windows, jobs it has no tool for). It never hands out commands for you to type. When you ask for something safer, it offers only alternatives it really has. |
| Checkups (playbooks) | Known problems (disk filling up, slow, no internet, updates, after a restart) are written once as data. The checks run on the device, the causes are matched in code, and safe clean-ups come up as cards, with no AI call. |
| Investigate | A toggle under the chat. The same model thinks longer and may take up to 24 steps; it works through a problem like an administrator would and reports what it checked, what it found and what it recommends. |
| Web research | For an error it does not recognise, one Gemini call grounded with Google Search, with the sources shown. The question is stripped of addresses, secrets and your home's own names before it leaves; 20 searches per person per day. |
| Knowledge per device | What a good administrator keeps in a folder: a profile, notes grouped by app, runbooks (fixes that worked on that device, offered again as cards next time) and a log of every job that ran. The agent reads it before every investigation; you can edit it. |
| Found nearby | Your devices list what else is on the network, with the names and models things announce (Apple devices and printers through Bonjour, the router through UPnP). Add one and Nightlight watches whether it still answers. |
| Activity and history | Who did what (you, the device, Nightlight). For each real device, 24 hours or 7 days of disk, memory and CPU. |
| Watched websites | Up to 10 public addresses per account, checked from the cloud (status code and response time only). |
| Memory | Short facts you tell the agent ("the kids play on weekends"), kept in Agent Platform Memory Bank. A panel lists them and can forget them all. |
| Knows itself | Questions about Nightlight (adding, removing, updating, privacy) are answered from the product's own guide (`guide.yaml`) through a tool, never from the model's memory, so the answer matches the product that is running. |

## Architecture

![Nightlight architecture](docs/architecture/architecture.png)

The same picture in Mermaid (the PNG is generated by `docs/architecture/architecture.py`; keep the two in step):

```mermaid
flowchart LR
    subgraph owner["Owner"]
        B["Browser<br/>map, chat, approval cards"]
        PK["Passkey (WebAuthn)<br/>signs expert commands"]
    end
    subgraph gcp["Google Cloud"]
        AUTH["Firebase Authentication<br/>Google sign-in, anonymous demo"]
        subgraph run["Cloud Run"]
            W["Web app<br/>Next.js"]
            A["API: FastAPI + ADK agent<br/>approval cards, trust ladder,<br/>budgets, signed helper release"]
        end
        FS[("Firestore")]
        SCH["Cloud Scheduler<br/>every 5 min"]
        subgraph ap["Google Agent Platform"]
            G["Gemini 3.8 Flash<br/>Quick: low thinking<br/>Investigate: medium thinking"]
            MB["Memory Bank<br/>facts per person"]
            GS["Google Search grounding<br/>(research)"]
        end
        subgraph deploy["Deploy: gcloud run deploy --source"]
            CB["Cloud Build"] --> AR["Artifact Registry"]
        end
    end
    subgraph home["Owner's devices (Linux, macOS)"]
        H["Signed helper<br/>systemd / launchd, no open ports"]
        S["Apps and services<br/>Docker, systemd"]
    end
    B -->|"page, /config"| W
    B -->|"sign in"| AUTH
    B ==>|"ID token: chat, tap to approve"| A
    PK -.->|"signed command"| A
    FS -.->|"read-only listeners, own data only"| B
    A -->|"one transaction per approval"| FS
    A -->|"tools, capped output + thinking"| G
    A -->|"facts per person"| MB
    A -->|"20/day"| GS
    SCH -->|"/internal/sweep, Google-signed token"| A
    AR -.->|"deploy"| A
    H -->|"report every minute<br/>outgoing HTTPS only"| A
    A ==>|"answers the helper's outgoing request:<br/>job name + target only after a tap; signed release"| H
    H -.->|"fixed jobs, local allow-list"| S
```

### Demo machines for visitors

A visitor who picks the live demo gets a real Linux virtual machine of their own, with real apps in containers. It is
started on demand and restored from a clean disk copy after every visit, so nothing one visitor does reaches the next.
Each visit signs in as its own throwaway identity, which the server maps to that machine. A visit ends after 15
idle minutes or 60 minutes in all, and a sweep every five minutes stops any machine without a visit. Measured: ready
in about a minute; "Start fresh" in about two. The picture:
[`docs/architecture/live_demo.png`](docs/architecture/live_demo.png).

```mermaid
%% Demo machine pool (source: api/src/nightlight_api/live.py, scripts/live_pool/).
flowchart LR
    V["Visitor's browser"]
    subgraph gcp["Google Cloud"]
        A["Cloud Run: API<br/>lease, release, sweep"]
        FS[("Firestore<br/>slot leases (transaction)<br/>idle 15 min, hard cap 60 min")]
        AUTH["Firebase Authentication<br/>a throwaway identity per visit"]
        SCH["Cloud Scheduler<br/>sweep every 5 min"]
        IAP["IAP-only SSH<br/>(operators; no other inbound)"]
        subgraph pool["Compute Engine pool: 5 x e2-small, stopped when idle"]
            VM["nl-live-1 .. nl-live-5<br/>small home server, Docker apps,<br/>signed helper paired to its own pool account"]
            G[("Golden snapshot per VM")]
        end
    end
    V -->|"1. ask for a machine"| A
    A -->|"2. lease a free slot"| FS
    A -->|"3. start on demand"| VM
    A -->|"4. custom token for this visit<br/>(mapped to the machine, lease id as a claim)"| V
    V -.->|"5. sign in; refused once the visit ends"| AUTH
    VM -->|"helper reports outward like any device"| A
    A -->|"release: wipe app data,<br/>restore boot disk, stop"| G
    G -.->|"restore"| VM
    SCH -->|"expired leases, stop orphan VMs"| A
    IAP -.-> VM
```

How the pieces talk:

- **Browser to API.** Every `/api/*` call carries a Firebase ID token. The user id comes only from that verified
  token; nothing in a request body can choose it. The browser reads its own data straight from Firestore with
  listeners (read-only, own subtree only, enforced by `firestore.rules`); every write goes through the API.
- **Chat.** A turn is one in-process ADK agent run. Replies stream as server-sent events: the browser keeps one
  connection open and words arrive as they are written. Every model call first reserves its worst-case cost in a
  Firestore transaction (see Budgets below). Things that happen outside the person's own messages (a job finished, a
  job declined, an investigation approved) are posted as **events**, not as fake user messages
  ([ADR 0002](docs/adr/0002-conversation-events.md)).
- **Approvals.** One Firestore transaction commits the decision, the device and service changes, the result, the
  trust update and the queued follow-up turn, so a job never runs twice.
- **Helper to API.** The helper reports health every minute (and right away after something changed) with a device
  token. Between reports it keeps one request open (`POST /helper/jobs/wait`); the server holds it for up to 25
  seconds and answers the moment an approved job appears, handing each job over at most once. The device only dials
  out; nothing is pushed into it ([ADR 0003](docs/adr/0003-job-channel.md)).
- **Capabilities.** Everything a real device can be asked to do is declared once in `capabilities.py`: how to build
  its card, how it is approved (on the device, one tap, or a passkey signature), and what follows from its result.
  One pipeline handles every capability ([ADR 0001](docs/adr/0001-capability-registry.md)).

## How we use Google Cloud

| Service | What it does here | Why |
|---|---|---|
| **Gemini on Google Agent Platform** | `gemini-3.8-flash` for both modes: everyday questions at low thinking with a few steps; Investigate mode at medium thinking with up to 24 steps and its own budget | On 18 Oct we moved everyday answers from 3.5 Flash-Lite to 3.8 Flash. On the same 12 demo questions, run 3 times each, Flash-Lite passed 26 of 36 and Flash 34 of 35. Flash takes about twice as long per answer (median 9.0 s against 4.6 s) and costs 2.5 times as much; we took the accuracy |
| **Agent Development Kit (ADK, Python)** | the agent loop, tools, and callbacks before and after each model call (cost reservation, size checks, scrubbing) | one place to bound every call |
| **Agent Platform Memory Bank** | facts about the person, scoped to the verified user id, written only by the agent's `remember` tool, kept 180 days | memory that survives a cleared browser, without mining transcripts behind the person's back |
| **Google Search grounding** | one grounded Gemini call for unknown errors, with sources | the agent should not guess at error messages it has never seen |
| **Cloud Run** | the web app (Next.js) and the API (FastAPI); scale to zero, at most 3 instances each | the public link stays up at near-zero idle cost |
| **Cloud Scheduler** | `POST /internal/sweep` every 5 minutes with a Google-signed token (audience and invoker checked) | silent devices and watched websites are noticed with nobody watching |
| **Firestore** | devices, services, history (expires on its own), approval cards, trust, chats, activity, quotas | transactions make approvals and job hand-over exactly-once; listeners give the browser live data |
| **Firebase Authentication** | Google sign-in, and anonymous sign-in for the one-click demo | visitors never have to create an account; real devices are always tied to a Google account |
| **No stored secrets** | the API reaches Firestore, Gemini and Memory Bank as its own Cloud Run service account; there are no API keys, so nothing goes in Secret Manager. The only key in the browser is the Firebase web config, which is public by design. The helper's release-signing key stays offline on the team's machine | a compromised cloud has no key to leak and cannot sign a helper update |
| **Firebase emulator** | the whole API test suite runs against the Firestore emulator | no cloud access needed to test |

## The safety model

The hard problem in Nightlight is **safety against power and convenience**. The benchmark we measure against is a
person running an AI agent in a terminal with their own SSH keys: it can fix anything, and it is only as safe as the
person watching. Nightlight has to come close to that for people who have never opened a terminal, and stay safe even
if Nightlight's own cloud is breached. The threat model (a stolen login, a breached cloud, prompt injection, a lost
phone, a demo visitor) and the layer that answers each is in [`docs/SECURITY-MODEL.md`](docs/SECURITY-MODEL.md); the
reasoning is in [`docs/DESIGN-trust.md`](docs/DESIGN-trust.md); the code-level details are in
[`docs/SECURITY.md`](docs/SECURITY.md); the owner's guide to passkeys is [`docs/PASSKEYS.md`](docs/PASSKEYS.md).

| Layer | What it means |
|---|---|
| **Approval cards** | Every change is proposed, never done. A card shows the plan, a dry run, what it touches, how to undo it (honestly, including "can't be undone") and a risk badge. The agent's tools create cards; they cannot run anything. |
| **Capability registry** | A real device can be asked for a fixed list of jobs: look into and look around (read-only checks), restart an allowed container or failed service, a safe clean-up from a fixed list, a signed helper update, remove the device, and expert commands. Unknown job types do nothing. |
| **Job names, not commands** | The cloud sends a job name and a target, never a command line. The helper maps the name to a fixed argument list with no shell, and re-checks the target against its own local allow-list and its current state before running. So even a breached cloud can only ask for jobs the device already allows. |
| **Signed helper** | The helper is one Python file plus a signature. It installs an update only if the signature matches the release key built into the running copy, the version is newer, and a self-test passes; the old copy is kept for `rollback`. The signing key never touches git, the image or the cloud, and `deploy_api.sh` refuses to ship a release whose signature does not match. |
| **Strict vs app-managed** | Chosen once at install. *Strict:* permissions change only on the device; the cloud cannot widen them. *Managed from the app:* the owner's switches in the app are applied by the helper, but only for targets the device itself reports, and every change still waits for a tap. |
| **Expert sessions with passkeys** | For anything beyond the fixed menu. The owner registers a passkey (WebAuthn, the same Face ID / Touch ID prompt as a password-free login) and pins its public key on each device, at the device, after comparing a fingerprint. Gemini proposes a command; the browser signs the exact command, device id, expiry (15 minutes) and a one-time nonce; the device verifies the signature itself before running. Read-only commands run under one signed 15-minute grant, and the device enforces "read-only" with exact rules (fixed programs, reading sub-commands only, no pipes or chaining, no paths that look like secrets). A breached cloud cannot sign anything. |
| **Scrubbing** | Log lines and check output are scrubbed on the device before they leave (keys, tokens, `key=value` secrets, URL credentials, emails, IP and hardware addresses, home paths). The server scrubs again every heartbeat value, job result, chat message, tool result, model output and memory fact before storing, showing or sending it to the model. Best effort, not a guarantee. |
| **What never leaves a device** | Its host name, IP or hardware addresses, files, environment variables, passwords or keys. The default device name comes from the hardware ("Raspberry Pi", "Mac mini"), never the host name. Addresses of things nearby leave only as keyed fingerprints (HMAC-SHA256 with the account's own key). A maker leaves only if it is on a fixed list of brands, a model only if it is a known Apple model or looks like a product code; the server checks the same rules. The names things announce ("Living Room") are sent because this is your own map; that is on by default and can be turned off. The server's schema rejects any field it does not expect. |
| **Device text is data** | Names, tags, container names and log lines come from devices. The agent's instructions mark them as evidence, never as instructions. Discovery items use a fixed vocabulary the server checks. |
| **Budgets and quotas** | No model call happens unless a reservation for its worst-case cost succeeds first, in one Firestore transaction with the per-person, per-visitor and daily counters and a kill switch. Defaults: a $35 model budget, 120 calls per person per hour, 100 per visitor per hour, 2,000 per day, 40 turns per person per hour, 8 model calls and 8 tool calls per turn (24 in Investigate mode, 240 s), input bounded with Gemini's token counter, output plus thinking capped at 1,024 tokens (4,096 in Investigate mode), 20 web searches per person per day. |
| **Device tokens** | 256 random bits, stored only as a SHA-256 hash, revocable from the app or by uninstalling. Join codes are single use and expire in 10 minutes. |

Each step that added power was reviewed adversarially by a separate AI reviewer working from the code and the rules.
The first version of expert sessions came back with five high-severity findings (for example, "read-only" was a list
of names that `docker system prune` slipped through); each was fixed with a regression test and reviewed again.

## Measured performance

From [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md): 10 runs of the demo story with `scripts/bench.py` against the real
model on Agent Platform, 2026-10-17. At that point the everyday model was `gemini-3.5-flash-lite` (low thinking,
1,024-token output cap). Firestore was the local emulator, so Firestore network time is not included. 9 of 10 runs
completed.

| Step | Median time to first words | Median full answer | 95th percentile | Model calls | Tool calls | Median cost |
|---|---|---|---|---|---|---|
| "Is anything wrong at home?" | 6.7 s | 6.7 s | 8.6 s | 3 | 2 | $0.0062 |
| Follow-up after approval | 2.7 s | 2.7 s | 4.6 s | 1 | 0 | $0.0002 |

Approving a card (one Firestore transaction): median 102 ms. The whole story (question, approval, follow-up) cost
about $0.0068. Worst case per model call under the enforced limits is $0.00736, so the $35 budget covers at least
4,755 calls; whatever a call uses below its reservation is refunded.

The first version (2026-10-15, `gemini-3.8-flash`, fleet listed by tools, follow-up with tools) took 16.4 s for the
question and 14.0 s for the follow-up. Putting the home summary in the instruction and making the follow-up a single
call brought it to the numbers above. On 18 Oct everyday answers moved back to 3.8 Flash for accuracy (the A/B is in
the Google Cloud table above): median 9.0 s per answer, about $0.016 per Quick turn.

## Sample questions

On the sample home, these are known to work:

| Ask | What happens |
|---|---|
| "Is anything wrong at home?" | the Pi's disk is 94% full; a card offers to clean old logs |
| "My kids say Minecraft is really laggy tonight" | memory nearly full; a card offers to restart the server (and says players will be disconnected) |
| "When was the Minecraft world last backed up?" | the answer, and a card to back it up if it is overdue |
| "Is there an update for the game server?" | version and latest version; a card to back up, then update |
| "What depends on the router?" | reasons from the lines on the map |
| "How do I add my own device?" | answered from the built-in guide |
| "Remember that the kids play on weekends" | saved to Memory Bank; shown in the Memory panel |

Answers are kept short on purpose. Very long conversations are trimmed or refused rather than cut off silently.

## Real devices

Signed in with Google, open **Add a device**. The app shows a one-line install command for Linux or macOS. The
installer downloads the helper from the same web address, checks its sha256, joins with a one-time code (or shows a
code and a QR code for you to approve on your phone), and installs a background service that runs as your normal
user. On a Mac it asks once, there and then, whether it may measure Downloads, Desktop, Documents, Movies and the
Trash, so nobody has to come back to the terminal for it. If someone else looks after the device, **Send the steps**
shares the line with three plain steps for them. The helper is
[`helper/nightlight_helper.py`](helper/nightlight_helper.py): Python 3.8+, standard library only, about 4,000 lines,
reviewable in one sitting.

**On a Mac, download the installer.** `Nightlight.pkg` (from **Add a device**, served at `/download/Nightlight.pkg`)
needs no Terminal and no developer tools: it brings its own Python (CPython from python-build-standalone, checked
against pinned sha256 digests). Click through the standard installer; your browser opens Nightlight's approval page;
click **Approve** and the Mac appears on your map. The background service is managed from the app, and the question
about the private folders is asked later. Nothing on the Mac listens for connections, so the firewall never asks. The
package is built by [`scripts/build_mac_pkg.sh`](scripts/build_mac_pkg.sh), which signs and notarizes it once
Developer ID certificates are present. Today's build is unsigned, so macOS shows a warning first and asks for
right-click → Open. Its shared files stay in `/Library/Application Support/Nightlight` after an uninstall; the
uninstall prints the one administrator command that removes them.

**Reinstalling keeps a device's history.** Uninstalling on the device (`nightlight uninstall`) leaves it on your map as
offline, with everything Nightlight knows about it. Install again (the command line or the Mac installer) and the
approval page asks *"This looks like your MacBook, last seen 10 minutes ago. Continue its history?"*: the same device
comes back with its notes, saved fixes, past jobs and place on the map. The match is a hardware fingerprint hashed on
the device and keyed per account on the server. It is offered only at your approval tap, never for a device that is
still reporting, and never across accounts. Removing a device in the app is different: it archives the device for 30
days, and a reinstall before then can still bring it back.

When a device first connects, a one-time setup card asks what Nightlight may do there: Just watch, Watch and fix
safe things (recommended), or Custom. On a device managed from the app, both presets include reading the recent log
lines of the apps it has then, scrubbed on the device; you can switch that off per app.

**Found nearby.** A device with the helper also lists the other things on its network: printers, TVs, phones, a NAS,
the router. It asks the system's own mDNS service (Bonjour on a Mac, Avahi on Linux) and reads the router's UPnP
description; it never opens a port that waits for others, so no firewall prompt appears. A thing keeps its identity
through a keyed fingerprint of its hardware address, so it stays the same thing when the router gives it a new IP
address. One of your own devices seen under another address shows in **Needs you** as a duplicate, with Review and
Keep both. An Apple TV is watched on its AirPlay port. Code: `discover` and `_identify` in the helper, `real.py` on
the server.

Nightlight changes nothing on a device by default. What it can do, and only after you allow it:

| You allow | Nightlight can |
|---|---|
| `diagnose NAME` (or the "look into" switch) | read why a container or service is down; read-only, no card |
| `logs NAME` (on in both setup presets) | include its last 30 log lines, scrubbed on the device |
| `inspect` (or the "check why" switch) | run fixed read-only checks: biggest known folders, busiest programs, waiting updates, Docker disk use, DNS and internet, load, failing services |
| `restart_container NAME` / `restart_service UNIT` | start that one target again after your tap if it stopped or failed; a container that runs but fails its own health check gets a restart card instead (helper 0.9.27+) |
| `fix` (or the "clean up space" switch) | one clean-up from a fixed list (Trash, Homebrew / npm caches, Xcode build data, Docker's untagged images, apt cache, system journal), after your tap |
| `update` (or the "updates" switch) | install a signed, newer helper after your tap (or automatically if you say so) |
| `nightlight expert` at the device | pin your passkey so expert sessions can run commands you sign |

Removing a device is a card too: the helper uninstalls itself and the device leaves the map (archived for 30 days).

## Honest limits

- Real-device jobs are the fixed list above plus passkey-signed expert commands. Everything else is explained, not
  changed.
- The trust ladder (jobs running on their own) applies to the sample home only.
- Which devices are looked after, which are only watched, and what comes next:
  [`docs/DEVICE-SUPPORT.md`](docs/DEVICE-SUPPORT.md).
- The helper supports Linux (systemd) and macOS (launchd). **Windows is not supported**; a Windows PC can only be
  watched from another device (does it answer on the network).
- Adding a Linux device needs one line in a terminal. Only the Mac has an installer; until it is notarized with a
  Developer ID, macOS opens it only through right-click → Open.
- Lines are drawn automatically only for what helpers can see: the router, backups, mounted shared folders and a
  few services in use. Everything else is drawn by the owner, or by the agent when you tell it how two devices relate.
- A router's maker and model come only from UPnP; with UPnP off, the router is found but not named.
- Phones and laptops that use a private Wi-Fi address and announce no name fold into one line; when a phone rotates
  that address, it looks like a new thing.
- Names of things nearby can be turned off in More → Settings ("Show names things announce").
- A device token has no expiry; it is revocable but not rotated.
- `curl | sh` trusts the HTTPS origin; the sha256 pin only proves the helper matches what that server serves.
- A job handed to a helper that crashes before reporting stays "running"; a job approved while the device is offline
  waits until it reports again.
- There is no "delete my account" yet. Removed devices are archived 30 days, then deleted; an API call
  (`DELETE /api/devices/{id}`) deletes one sooner, with no button for it in the app yet.
- Browser notifications work only while the tab is open.
- Scrubbing is pattern-based and best effort. The design relies first on not collecting secrets.

## Roadmap

- An installer for every OS, so no first install needs a terminal: the macOS package exists; next a Linux `.deb`,
  a Docker package for NAS boxes, then Windows.
- Recent logs on by default for apps that appear after setup, not only those present at setup.
- A backup before any clean-up, so even a clean-up that can't be undone can be.
- Device token rotation and expiry; release signing in a hardware security module or CI outside the cloud.
- Retention you choose per account, and account deletion that purges everything at once.
- A local-first mode: the helper keeps watching and answering on the home network when the cloud is away.
- Teams: a family member or an office manager with their own role.

## Run locally

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), the Firebase CLI and Java 21 (for the Firestore
emulator), Node.js 20+.

```bash
./scripts/test_api.sh                  # API and helper tests against the Firestore emulator; no cloud access needed
./scripts/secret_scan.sh               # secret scan of staged changes and history
cd web && npm install && npm run dev   # web app on http://localhost:3000 (environment: see web/README.md)
```

Locally the API runs with no Memory Bank id (memory becomes a no-op) and with the emulator as Firestore. The test
suite has about 500 tests across the agent, approvals, trust, the helper client, pairing, discovery, automatic lines,
device knowledge, expert sessions, playbooks, research, reset and the cost guards. `scripts/chat_probe.py` puts
conversations to the real agent against a fresh sample home and prints what a person would see.

## Deploy

```bash
./scripts/deploy_api.sh   # Cloud Run: verifies the helper's signature, copies the signed release in, deploys
./scripts/build_mac_pkg.sh  # build/mac/Nightlight.pkg: signed and notarized with Developer ID certificates if present
./scripts/deploy_web.sh   # Cloud Run: reads the public Firebase web config at deploy time, deploys, moves traffic
```

Both deploy scripts run the secret scan first. **No secrets live in git or in the images.** Model, thinking level,
prices, budget and quota limits are environment variables set at deploy (`api/src/nightlight_api/config.py` lists them
all with their defaults). The API reaches Firestore, Gemini and Memory Bank through its service account. The web app
serves its Firebase config (public by design) from `/config`, read from environment variables. `.env*`, `*.pem` and
service-account files are gitignored; a scan (`.gitleaks.toml`) gates every deploy.

## Repo map

| Path | What |
|---|---|
| `api/src/nightlight_api/agent.py` | the ADK agent: instruction, tools, callbacks that bound every model call |
| `api/src/nightlight_api/capabilities.py` | the registry of everything a real device can be asked to do |
| `api/src/nightlight_api/actions.py` | approval cards: request, decide, job result (one pipeline) |
| `api/src/nightlight_api/trust.py`, `sim.py`, `template.py`, `demo.py` | the trust ladder and the simulated sample home |
| `api/src/nightlight_api/real.py` | real devices: joining, heartbeats, setup, found things, job hand-over |
| `api/src/nightlight_api/links.py` | lines between devices, drawn or worked out from keyed fingerprints |
| `api/src/nightlight_api/apps.py` | what an app is: a fixed catalog of home apps, each with one plain line |
| `api/src/nightlight_api/turns.py` | a chat turn: streaming, events, one retry when an answer comes back empty or cut off, then an honest "couldn't answer" |
| `api/src/nightlight_api/expert.py` | passkey registration and signing for expert sessions |
| `api/src/nightlight_api/playbooks.py`, `playbooks.yaml` | known problems as data |
| `api/src/nightlight_api/research.py` | Google Search grounded research |
| `api/src/nightlight_api/memory.py`, `notebook.py`, `runbooks.py`, `knowledge.py` | Memory Bank facts; per-device notes, runbooks and job log |
| `api/src/nightlight_api/quota.py`, `redact.py`, `fence.py` | cost reservations, scrubbing, one chat turn at a time per person |
| `api/src/nightlight_api/release.py`, `scripts/sign_helper.sh` | signed helper releases |
| `api/src/nightlight_api/guide.yaml` | what the agent says about Nightlight itself |
| `api/tests/` | the test suite (`fake_llm.py` stands in for Gemini) |
| `helper/nightlight_helper.py`, `.sig` | the device helper and its release signature |
| `web/` | Next.js app: `components/` (`map/`, Chat, ApprovalCard, DeviceDrawer, AppDetail, FoundNearby, TrustPanel, ExpertSessions, ...), `lib/` (Firebase, API, listeners, passkeys), `app/install.sh` and `app/uninstall.sh` routes |
| `docs/API.md` | the contract between web, helper and API |
| `docs/SECURITY-MODEL.md`, `docs/SECURITY.md`, `docs/DESIGN-trust.md`, `docs/PASSKEYS.md` | threat model and layers; code-level details; safety vs power, and why; passkeys for owners |
| `docs/adr/` | decisions: capability registry, conversation events, held job channel |
| `docs/BENCHMARKS.md`, `scripts/bench.py` | measured latency and cost |
| `docs/COSTS.md` | what we spent on Google Cloud and Gemini, the guards that cap it, and why |
| `docs/WALKTHROUGH.md` | the first-visit walkthrough (live machine, simulated home, your own device): the source of truth for docs, deck and video |
| `docs/LIMITS-AND-ROADMAP.md` | how we tested, known limits and their root causes, what comes next |
| `docs/architecture/` | the architecture diagram as code |
| `contracts/mocks/` | sample data for every state of the demo story |
| `firebase.json`, `firestore.rules` | emulator settings; browsers read only their own data |
| `scripts/` | tests, secret scan, deploys, the Mac installer build, benchmark, chat probe, smoke tests, mock generation |

## How we built it

Two AI coding sessions worked in parallel on one repository, with a human lead deciding and a third model reviewing.

- **One repo, two desks.** Git's `worktree` feature checks out a second branch into a second folder of the same
  repository. The orchestrator session (backend, agent, infra) worked on `main` in `nightlight/`; the frontend session
  worked on `fe` in `nightlight-fe/`. Neither switched branches under the other, and every commit landed in the same
  history, so merging needed no copying or extra pushes.
- **Short-lived helpers.** Larger backlog items went to sub-agents, each in its own throwaway worktree and branch.
  The orchestrator verified, fixed and merged them.
- **Reviewed before main.** Every slice was reviewed by a separate model (OpenAI Codex) before it reached `main`.
  Unreviewed work stayed on its side branch, and branches were merged at the exact commit that was approved.
- **The product's AI is Gemini only.** Claude and Codex were development tools; nothing of them ships in Nightlight.

### The day we stopped adding features

AI makes features cheap. The cost moves elsewhere: every quick fix narrows what the next change can safely do.

On the last night, role-played judges scored the chat agent 7.0, 7.6, 7.8, then 7.6 out of 10. The dip came from the
previous round's own fixes: 41 commits to one file had answered each complaint with a patch, mostly server code that
rewrote the model's answer after it was written, and an instruction that had grown to about 70 rules. So on the last
morning we stopped adding features and asked why each class of bug existed:

- **Prose was standing in for state.** The model narrated its own steps and cards while the server already streamed
  both. We deleted the rewriting code (about 300 lines); steps and cards now come from server events only.
- **Rules lived in the prompt.** The instruction became a short charter (11,035 characters down to about 2,100). The
  rules moved into tool contracts that hold whatever the model writes: a waiting card answers a second request for
  the same fix, a restart of an unbacked world puts up the backup first, a clean-up that measured empty says so.
- **Time was faked.** An "answer now" instruction made answers thinner so they would look faster. It is gone. A slow
  call is cut off and retried once; then the turn says honestly that Gemini is slow, with the time budget shown on
  screen.
- **We measured instead of guessing.** A 30-case eval suite runs every case three times. The rebuild scored the same
  as before (81 of 90) without the patches; the model switch, not the rebuild, raised the score. The remaining
  failures are one class we can name, and they are visible instead of quietly rewritten.

Every agent's findings went through review before `main`. What we could not fix in time is written down with its root
cause in [`docs/LIMITS-AND-ROADMAP.md`](docs/LIMITS-AND-ROADMAP.md), and what it all cost is in
[`docs/COSTS.md`](docs/COSTS.md).

## Team

**8yte**

| Who | Role |
|---|---|
| Jeong Hwan Park | lead: product, backend, agent, helper |
| Sadika | frontend and design |
