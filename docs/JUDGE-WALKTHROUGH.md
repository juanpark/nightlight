# Judge walkthrough

The source of truth for how someone meets Nightlight for the first time: what to open, what to try, what they
should see, and how long each step takes. The README, the deck, the demo video and the in-app nudges are written from
this page. **When the product changes, update this page first**, then the places that quote it.

Last checked: 2026-10-18 (Sunday), against production.

## Start here

Open **https://nightlight-web-1032111130355.asia-northeast3.run.app** in a private window (not signed in).
The start screen offers three ways in:

| Option | What it is | Time |
|---|---|---|
| **Start a live machine** | your own real Linux virtual machine in Google Cloud, with real apps in containers, set up like a small home server | ready in about a minute |
| **Open the simulated home** | a sample home (Raspberry Pi, Mac Mini, NAS, game server, camera, router) with seeded problems | instant |
| **Sign in with Google** | try it on your own computer or Raspberry Pi | about two minutes |

A live line shows how many demo machines are running and in use. When all five are in use, the screen says so and
offers the other two ways in.

## Path A: a live machine (recommended for judges)

1. **Choose a starting point** in "Start with": everything fine, an app crashed, an app unhealthy, the disk nearly
   full, or leftovers from updates. Then **Start a live machine**.
2. **Wait about a minute** while the steps show: *Starting it up… → Waiting for your machine to check in… → Ready.*
   The machine was stopped until you asked for it. Measured: ready in 48–65 s.
3. **The first-run tour** appears once the machine is ready (7 short steps; it can be replayed from Settings).
4. **Ask like an owner would.** For a crashed app: *"Something on my server stopped working, can you check?"*
   - While it works, the chat shows each step and its result, the map highlights the device, and on a phone a chip
     at the top of the chat shows its state (checking, found something, done).
   - The answer names the app, the real cause from its log, and puts up a **card** to restart it.
   - Under the answer, a receipt: steps, seconds, model (Gemini 3.8 Flash), cost.
5. **Approve the card.** The restart runs on the machine; a follow-up says it came back and passes its health check.
6. **Break something for real** from the bar at the bottom (for example a full disk), then ask again. Each scenario
   changes the real machine; nothing is replayed.
7. **Start fresh** restores the machine from a clean copy (about 2 minutes). **Leave** ends the visit; the machine is
   wiped, restored and stopped within about a minute.

Good questions to try, with what a good answer looks like:

| Ask | A good answer |
|---|---|
| "Something on my server stopped working, can you check?" | names the stopped app and its error; restart card |
| "My server says it's almost full. What's taking the space?" | names the exact folder or file and its size; only clean-ups that free something |
| "My server feels slow today." | names the busy program, says whether it runs inside an app or on the machine itself |
| "Is my router's firmware up to date?" | says honestly that it can't see the router, and what to do instead |
| "Can you do this on your own next time?" | explains the trust ladder truthfully |

## Path B: the simulated home

1. **Open the simulated home.** The Needs list leads with the Raspberry Pi's disk at 94%.
2. Try the question chips, or **break something first**: *Make the Pi's disk fill up*, *Make Minecraft lag*, *Let the
   world backup fall behind*.
3. Things worth seeing: a backup is offered **before** a restart for a game world that hasn't been backed up; the
   **Status** view (Map · List · Status) shows every check as ✓ / ! / ✗ with a summary line, without any AI; after a
   few approvals of the same safe job, a **Trust** offer appears.

## Path C: your own computer or Raspberry Pi

Works on Linux (including Raspberry Pi) and macOS 10.15+; Windows PCs, NAS boxes and routers are watched from one of
those, not looked after directly ([`DEVICE-SUPPORT.md`](DEVICE-SUPPORT.md)).

1. **Sign in with Google**, then **Add a device**. Copy the one line into Terminal (Linux or Mac), or on a Mac use
   the **Mac installer** (it shows a warning first: the installer isn't signed by Apple yet; right-click → Open).
2. Your device appears on the map within a minute, with disk, memory and apps, and **Found nearby** lists the
   printers, TVs and phones it can see on your network.
3. Ask anything. Nothing changes without your tap; a raw command needs your **passkey** (Face ID, Touch ID or your
   device PIN), and the device checks that signature itself. See [`PASSKEYS.md`](PASSKEYS.md).
4. Uninstalling keeps the device's history (it shows as offline); reinstalling offers *"Continue its history?"*.

## What to notice (the claims, and where they show)

| Claim | Where you see it |
|---|---|
| It's live, not scripted | real machines, your own break, receipts with seconds and cost, steps with real outputs |
| Nothing changes without your tap | every change is a card; risk shown by colour; passkey for raw commands |
| It's honest | says what it can't see; "unknown" stays unknown on the status board; failures say so |
| It remembers per device | Knowledge tab: profile, notes, saved fixes, every job that ran |
| It follows you | conversations open on any device you sign in on |

## Known rough edges (say them, don't hide them)

Kept in [`LIMITS-AND-ROADMAP.md`](LIMITS-AND-ROADMAP.md). The ones a visitor may meet: an occasional slow Gemini
answer (a visible time budget, one retry, then an honest "Gemini is slow" message); the Mac installer isn't signed
yet; trust offers work on the sample home only; five live machines at a time.

## Where this page is used

README "Try it" section · the deck's demo slide · the demo video's shot list · start-screen and tour wording ·
the submission description. Change those from here, not the other way round.
