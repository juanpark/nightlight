# Nightlight features (for design)

For Sadika and her AI: everything a visitor can see and do today, so the dashboard, the first-run tour and the landing
page can be designed around it. Checked against the code on 2026-10-18 (`web/components`, `web/lib/tour.ts`,
`api/src/nightlight_api`). If it isn't here, it isn't built. Labels in quotes are the app's exact words.

## 1. What it is

A house-sitter for the computers you run at home or in a small office: one map of every device and what runs on it,
and a Gemini assistant that watches, explains problems in plain words, and fixes them only after you tap Approve.

## 2. Every user-facing feature

Notes key: **sample** = sample (simulated) home only · **live** = live demo machine only · **real** = your own devices
only (signed in with Google) · **passkey** = needs a passkey (Face ID, Touch ID or device PIN).

### Start & sign-in (three ways in)

| Feature | What the user gets | Where in the UI | Component file(s) | Tour? | Notes |
|---|---|---|---|---|---|
| Start screen | Three ways in, with the tagline "A house-sitter for your home servers" | First page when signed out | `SignIn.tsx` | no | Shows how many live machines are free |
| Live machine | A real Linux VM in Google Cloud with real apps, ready in about a minute | "Start with" (Everything fine / An app has crashed / An app is unhealthy / The disk is filling up / Old leftovers take up space) then "Start a live machine" | `SignIn.tsx`, `LiveSession.tsx`, `lib/live.ts` | no | live; 5 at a time; progress: "Starting it up…" → "Waiting for your machine to check in…" → "Ready." |
| Simulated home | An instant pretend home (Pi, Mac Mini, NAS, Minecraft server, camera, router) with seeded problems | "Open the simulated home" | `SignIn.tsx`, `Board.tsx` | no | sample; header pill "Sample home: simulated" |
| Google sign-in | Your own home, where real devices can be added | "Sign in with Google" | `SignIn.tsx` | no | real |
| Save a visit | Keep a sample visit by linking Google | Header "Save with Google" | `Home.tsx` | no | sample; handles "That Google account already has its own Nightlight home" |

### Home: map, list, status board, needs

| Feature | What the user gets | Where in the UI | Component file(s) | Tour? | Notes |
|---|---|---|---|---|---|
| Needs strip | A one-line verdict plus every problem that needs you, worst first | Top of Home (`data-tour="needs"`), "Show all N" | `NeedsList.tsx`, `NeedsMark.tsx`, `lib/needsYou.ts` | yes | |
| Ask if anything's wrong | One tap asks the assistant to check all your servers | "Ask if anything's wrong" in needs strip | `Home.tsx` | no | |
| Map | Devices on graph paper; pan, pinch, zoom, drag to place; health light per device | Home, view switch "Map" | `map/HomeView.tsx`, `map/HomeMap.tsx`, `map/DeviceNode.tsx` | yes | |
| Device card on map | Card opens in place with its apps (problems first, then starred) | Tap a device: "Open", "Ask", "Details" | `map/DeviceNode.tsx`, `map/AppSheet.tsx` | no | |
| Lines between devices | Draw how devices relate (connected through, backs up to…); the assistant uses them | "Drag from a dot on a device to another to link them" | `map/LinkEdge.tsx`, `map/HomeMap.tsx` | no | Some drawn automatically on real devices |
| List view | Same devices as a list grouped by kind | View switch "List" | `Board.tsx` | no | |
| Status board | Every check as ✓ / ! / ✗ with a summary line, no AI; copyable | View switch "Status" | `StatusBoard.tsx`, `lib/board.ts` | mentioned | "From what each device last reported. No AI involved." |
| Filters & places | Narrow to "Only what needs me", "Favorites", tags, places | Home bar above map | `map/HomeBar.tsx`, `lib/homeFilter.ts` | no | |
| Favorites | Star devices and apps; up to 3 starred apps show on a card | "Star it" in drawer / app | `lib/favorites.ts`, `DeviceDrawer.tsx` | no | |
| While you were away | Banner summarising what happened since your last visit | Top of Home: "Summarise", "Dismiss" | `AwayBanner.tsx` | no | |
| Phone layout | Home and Chat as two tabs at the bottom, with a needs count | Bottom tabs "Home" / "Chat" | `Home.tsx`, `app/mobile.css` | no | |

### Device drawer (tap a device; tabs: Overview, Apps, Knowledge, Settings)

| Feature | What the user gets | Where in the UI | Component file(s) | Tour? | Notes |
|---|---|---|---|---|---|
| Overview | Status sentence, needs, Disk / Memory / CPU, "Ask about this device" | Tab "Overview" | `DeviceDrawer.tsx` | no | |
| First-connect setup | Right after a device joins: "What may Nightlight do here?" | Top of Overview | `SetupCard.tsx` | no | real |
| Problems | Other findings, each with "What should I do?", "Snooze a week", "I know, leave it" | Overview, "Problems" / "Other problems" | `DeviceDrawer.tsx` | no | A finding that names its fix offers it, e.g. "Look nearby" |
| Checkups | Known problems checked step by step with no AI; safe clean-ups come up as cards | Overview, "Checkups" | `Checkups.tsx`, `api/.../playbooks.yaml` | no | real |
| History | Disk / memory / CPU over 24 h or 7 days | Overview, "History" | `DeviceHistory.tsx`, `Sparkline.tsx` | no | real; builds every 5 min |
| Apps | Every app on the device; tap one for what it is, health, version, notes, fixes, jobs | Tab "Apps" → app → "Ask about this app" | `AppDetail.tsx`, `lib/apps.ts` | no | |
| Knowledge | "About this device" profile, "Notebook", "Fixes that worked here" (saved fixes, "Use it"), "What was done here" (every job), tags, details | Tab "Knowledge" | `DeviceProfile.tsx`, `Notebook.tsx`, `Runbooks.tsx`, `JobLog.tsx` | no | Refuses to save things that look like passwords |
| Permissions | Choose "Just watch", "Watch and fix safe things" (recommended) or "Choose one by one" | Tab "Settings", "What Nightlight may do here" | `Permissions.tsx`, `lib/permissions.ts` | no | real; some devices only accept changes made on the device |
| Mac personal folders | Let the Mac measure personal folders (asks on the Mac) | Settings, "Personal folders" | `MacFolders.tsx` | no | real, Mac only |
| Helper updates | See version; "Update" from the app | Settings, "Updates" | `HelperUpdate.tsx` | no | real |
| Expert sessions | Let the assistant run its own checks/commands, each signed with your passkey | Settings, "Expert sessions (on/off)" → "Create my passkey" | `ExpertSessions.tsx`, `lib/passkey.ts` | no | real, passkey; must also run `nightlight expert` at the device, by design |
| Remove device | Remove it (history kept 30 days) | Settings, "Remove this device…" | `RemoveDevice.tsx` | no | real |
| Found nearby | Printers, TVs, phones, router your devices see, named as they announce; "Add" to watch one | Header "Found nearby" (`data-tour="found-nearby"`), "Look again" | `FoundNearby.tsx`, `lib/found.ts` | yes (first device) | real; added things become "watched" devices |
| Watched thing drawer | For a found/watched thing: what it is, availability for 24 h, "Stop watching it…" | Drawer of a watched device | `WatchedPanel.tsx`, `WatchedRow.tsx` | no | |

### Chat

| Feature | What the user gets | Where in the UI | Component file(s) | Tour? | Notes |
|---|---|---|---|---|---|
| Ask box | Plain-language questions about the home | "Ask Nightlight…", "Send", "Stop" (`data-tour="chat"`) | `Chat.tsx` | yes | Stop keeps what was done |
| Starters | Suggested questions and "Or break something first:" | Empty chat, "Ask about your home" | `Chat.tsx` | no | Break buttons are sample |
| Quick vs Investigate | Fast answers, or a slower step-by-step expert dig | Switch "Quick answers" / "Investigate deeply" under the chat | `Chat.tsx` | **no (missing)** | Investigate costs a few cents |
| Live steps | Each step and its real result while it works: "What I checked · N" | Inside each answer | `chat/TurnView.tsx` | **no (missing)** | |
| Receipt | Steps, seconds, model (Gemini 3.8 Flash), cost under each answer | Under each answer | `chat/TurnView.tsx` | **no (missing)** | |
| Approval cards | What will happen, what it affects, can it be undone, "Show the exact command"; "Approve" / "Not now" | In chat, needs list, drawer (`data-tour="card"`) | `ApprovalCard.tsx` | yes | |
| Risk levels | Badge and colour: "Read-only" (calm), "Some risk", "Risky" | On each card | `ApprovalCard.tsx` | no | |
| Passkey cards | Expert commands approved only with "Approve with passkey"; the device checks the signature | Card badge "Needs your passkey" | `ApprovalCard.tsx`, `lib/passkey.ts` | no | real, passkey |
| Card life | "Waiting for you" → "Running on the device…" → "Result" / "Didn't work" / "Declined" / expired | On card | `ApprovalCard.tsx` | no | |
| Conversations | Chats follow your account to any device; list and "New chat"; kept 30 days | "Conversations" at top of chat | `chat/Conversations.tsx` | no | |
| Map follows chat | Devices being checked glow on the map; when done, the main one opens with named apps pulsing | Map, during an answer | `lib/follow.ts`, `map/HomeMap.tsx` | **no (missing)** | |
| Phone chip strip | On a phone, chips above the chat: "checking…", "found something", "done ✓"; tap shows the map | Top of chat | `chat/ContextStrip.tsx` | no | |
| Web research | When the answer needs facts from outside the home (a known bug, a release note), it searches the web with Google Search and cites its sources | A step line "Searched the web: N sources: …" inside the answer | `api/.../research.py`, `turns.py` | no | |
| Honest answers | Says what it can't see (router firmware, Windows) instead of guessing | Answers | `api/.../agent.py`, `guide.yaml` | no | |

### Trust, Activity, Memory, Watches, Notifications

| Feature | What the user gets | Where in the UI | Component file(s) | Tour? | Notes |
|---|---|---|---|---|---|
| Trust ladder | Per kind of job: "Always ask me" / "Ask me for new things" / "Just handle it and tell me" | More → "Trust" | `TrustPanel.tsx`, `api/.../trust.py` | yes | sample only; real devices always ask; restarts/updates always ask |
| Trust offer | After 3 good approvals of a safe job: "Yes, handle it" / "Keep asking me" | Needs strip | `NeedsList.tsx` | no | sample |
| Handled on its own | Visible line when it acted under trust: "Handled on its own on …" | More → "Activity" | `Activity.tsx` | no | sample |
| Activity | "What happened, and who did it": you, the device, Nightlight; filters by device, time, problems | More → "Activity" | `Activity.tsx` | no | |
| Memory | "What Nightlight remembers about you"; "Forget everything" | More → "Memory" | `MemoryPanel.tsx`, `api/.../memory.py` | no | hidden on live machine |
| Watch a website | Up to 10 public addresses checked from the cloud | Header "Watch a website" | `WatchPanel.tsx`, `lib/watches.ts` | no | |
| Notifications | Browser notification when something goes wrong | Needs strip "Notify me" / "Notifying you" | `lib/notify.ts`, `Home.tsx` | no | only while tab is open |

### Add a device

| Feature | What the user gets | Where in the UI | Component file(s) | Tour? | Notes |
|---|---|---|---|---|---|
| One line | A copyable install line for Linux, Raspberry Pi or Mac; "Waiting for your device…" | Header "Add a device" (`data-tour="add-device"`) | `AddDevice.tsx`, `lib/installScript.ts` | yes (signed-in, no devices) | real |
| Mac installer | Downloadable installer, same helper | "Mac installer" in Add a device | `AddDevice.tsx` | no | real |
| Unsigned warning | "Before you download": not Apple-signed yet, right-click → Open; "Download anyway" | Mac installer step | `AddDevice.tsx` | no | real |
| Send to someone | "Send these steps" to a helper friend | Add a device, "Someone you know" | `AddDevice.tsx` | no | real |
| Pairing code | Device shows a code; approve it in the app; "This isn't mine" turns it away | "Can't paste on that device? Use a code it shows instead", `/pair` | `PairApprove.tsx` | no | real |
| Continue history | Reinstall offers "Continue its history" or "Add as a new device" | Pairing approval | `PairApprove.tsx` | no | real |
| First-run checklist | "Add your first device with one line", "Choose how much it may do", "Find more devices nearby" | Home, left column | `FirstRun.tsx` | yes (`try-own`) | |

### Demo tools, practice home, live machine bar

| Feature | What the user gets | Where in the UI | Component file(s) | Tour? | Notes |
|---|---|---|---|---|---|
| Demo tools | Trigger incidents ("Disk fills up", "Minecraft gets laggy", "World backup overdue", "Game update available", "Next clean-up will fail") and reset | More → "Demo tools" | `DemoTools.tsx`, `api/.../demo.py`, `sim.py` | no | sample |
| Practice home | Signed-in owners can show the sample home next to real devices | Header "Practice home" / "Hide practice home" | `Home.tsx` | no | real accounts |
| Live machine bar | "Break something for real", "Start fresh" (clean copy, ~2 min), "Leave" | Bar at the bottom | `LiveSession.tsx` | **no (missing)** | live |

### Settings

| Feature | What the user gets | Where in the UI | Component file(s) | Tour? | Notes |
|---|---|---|---|---|---|
| Tour replay | "Show the tour again" | More → "Settings" | `AccountSettings.tsx`, `lib/tour.ts` | yes | |
| Names switch | "Show names things announce" (Living Room TV, Alex's iPhone) | More → "Settings" | `AccountSettings.tsx` | no | |
| Versions line | "Nightlight 1.0.0 · web … · API … · helper …" | More → "Settings" | `AccountSettings.tsx` | no | |

## 3. The 8 moments that matter (in order)

1. **It's real, not a slideshow.** Start → "Start with: An app has crashed" → "Start a live machine". Watch the three
   steps and "Ready." in about a minute.
2. **One look says how home is.** The needs strip's verdict and the map with health lights; switch to "Status" for the
   ✓ / ! / ✗ board with no AI.
3. **Ask like an owner.** Chat → "Something on my server stopped working, can you check?" (or "Ask if anything's
   wrong"). Steps appear live; the map glows on the device being checked (phone: chips above the chat).
4. **It finds the real cause.** The answer names the app and the error from its log; under it, the receipt (steps,
   seconds, Gemini 3.8 Flash, cost).
5. **It asks first.** The card: What happens / Affects / Can it be undone? / risk badge → "Approve". A follow-up says
   it came back.
6. **Break it yourself.** Bottom bar → "Break something for real" → e.g. "The disk is filling up" → ask again. Sample
   home: "Or break something first:" buttons, or More → "Demo tools".
7. **Trust is earned.** Sample home: approve the same safe clean-up a few times → offer "Yes, handle it" → More →
   "Trust" shows the ladder; Activity shows "Handled on its own".
8. **It remembers and grows with you.** Tap a device → "Knowledge" (profile, notes, fixes that worked, every job);
   then "Add a device" → one line → device appears → "Found nearby" lists what else is on the network.

## 4. Current tour (`web/lib/tour.ts`, shown by `Tour.tsx`)

Three tours, each seen once per account per browser; replay from Settings. Anchors are `data-tour="…"` attributes.

| Tour | Step | Anchor | Shown when |
|---|---|---|---|
| intro | Welcome to Nightlight | (centre) | always |
| intro | What needs you | `needs` | always |
| intro | Your home (mentions Status) | `map` | always |
| intro | These devices are pretend | `try-own` | sample visitor |
| intro | Add your first device | `add-device` | signed in, no real devices |
| intro | Ask Nightlight | `chat` | always |
| intro | It always asks first | `card` | always (centre if no card on screen) |
| intro | Trust, earned slowly | `more` | always |
| intro | See this again | `more` | always |
| firstDevice | Your device is here | `map` | first real device |
| firstDevice | Found nearby | `found-nearby` | first real device |
| firstDevice | Ask about it | `chat` | first real device |
| firstCard | Nightlight is asking | `card` | first pending card |

Missing compared with section 3:

- **Live machine**: no step for the bottom bar ("Break something for real", "Start fresh", "Leave"). The intro also
  has no live-specific wording (the "pretend" step only fits the sample home).
- **Steps, receipt, map follow**: nothing points at what happens *during* an answer (moments 3–4). Needs a step that
  fires on the first answer, or a tour after it.
- **Quick vs Investigate**: the switch has no anchor and no step.
- **Status board**: only a sentence inside "Your home"; no anchor on the Map / List / Status switch.
- **Knowledge tab, Conversations, Activity, Memory**: not mentioned.
- Two steps share the `more` anchor back to back; the `card` step usually shows centred because no card exists yet.
- Missing anchors to add: live bar, mode switch, view switch, a drawer tab, Conversations.

## 5. Rough edges a designer should know

- **Density.** The header has 4–6 buttons plus a More menu; the drawer's Overview stacks setup, status, needs,
  vitals, problems, checkups and history; Settings stacks permissions, folders, updates, expert sessions, removal.
- **No search.** No way to search devices, apps, conversations or activity; only filters on the home bar.
- **Panels push content.** Header panels (Add a device, Found nearby, Watch a website, Trust, Activity, Settings…)
  open inside the left column above the map and push it down instead of floating; only one is open at a time.
- **Expert sessions need the device's terminal, by design.** Turning them on needs a passkey in the app *and*
  running `nightlight expert` on the device itself. This is a safety choice, not a gap; design it as a clear
  two-step checklist.
- **Trust only works on the sample home.** Real devices always ask; the Trust panel must say so.
- **Live machines are limited** to 5 at a time; the start screen must handle "all in use" and "switched off".
- **Gemini can be slow.** Visible time budget, one retry, then an honest "slow" message; leave room for it.
- **Mac installer is unsigned** until Apple Developer ID certificates arrive, so the warning step stays.
- **Notifications** only work while the tab is open. **Windows** devices can only be watched, not managed.
- **Keep every `data-tour` attribute** when restyling (`docs/UI-NOTES.md`); a missing one centres that step.
