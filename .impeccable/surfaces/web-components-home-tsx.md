---
version: 1
slug: "web-components-home-tsx"
primary_target: "web/components/Home.tsx"
related_targets: []
---

# App shell (after sign-in)

Mode: Operate. Scope: web/components/Home.tsx and every screen it hosts (map, needs strip, chat, panels, device drawer, approval cards).
Audience: non-technical home owners; judges via one-click demo. Job: see at a glance whether home is fine, act on what needs them, ask in plain words.
Constraints: keep every function, label and data flow; navy / star yellow / cream only, green + amber (+ soft coral for broken) as status with a word.
Structure locked by Sadika (2026-10-17): slim left sidebar, map in the middle, chat docked right; phones keep the Home/Chat tab bar.

## Direction contract

THESIS: The landing's night house, now a calm working room: the lamp is lit only where something needs you. Refuses the grey admin dashboard with a button row across the top.
OWN-WORLD: Night = deep navy steps (#0b1430 ground, lighter navy surfaces), cream text, star yellow only for the primary action, selection and "needs you". Day = warm cream ground, navy ink, the same star. Funnel Display headings, Funnel Sans UI. Soft rounded surfaces, hairline navy borders, lucide icons at one stroke.
STORY: The person sees the verdict sentence first ("1 thing needs you" / "All good"), the item and its one button, then their house map; anything they wonder about goes to the chat beside it.
FIRST VIEWPORT: 232px sidebar (wordmark, sample chip, Home/Activity/Trust/Memory, Add group, demo/account/theme at foot); main column: verdict strip with the star glow, filters, map filling the rest; 400px chat with the mascot greeting the empty state.
FORM: sidebar shell, chosen by the user directly (no concept-seed run; structure locked in the interview).
SIGNATURE: the verdict strip's star light: steady soft glow when something needs you, a quiet green "All good" dot otherwise; the mascot in chat switches to thinking while Nightlight works.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
