---
name: Nightlight
description: A house-sitter for home servers; a small warm light that watches the machines while you sleep.
colors:
  night-ground: "#0b1430"
  night-panel: "#111c3d"
  night-panel-2: "#18254b"
  night-line: "#22305c"
  night-line-strong: "#33457a"
  night-select: "#1d2b5a"
  night-muted: "#aab3cf"
  cream-ink: "#f4efe4"
  navy-ink: "#15224a"
  star-yellow: "#fdd83a"
  star-hover: "#ffe36a"
  star-gold: "#f2b800"
  day-ground: "#f5efe2"
  day-panel: "#fffaf0"
  day-panel-2: "#efe7d6"
  day-line: "#e2d7c1"
  day-line-strong: "#c4b595"
  day-muted: "#56618a"
  day-select: "rgb(21 34 74 / .08)"
  night-ok: "#8fd6a8"
  night-warn: "#f5b84a"
  night-crit: "#ffb4a3"
  night-offline: "#8a93b3"
  day-ok: "#2f7a4c"
  day-warn: "#9c5a00"
  day-crit: "#c4553f"
  day-offline: "#737a95"
typography:
  display:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.005em"
  title-sm:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: "Funnel Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: "Funnel Sans, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Funnel Sans, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
    lineHeight: 1.2
  badge:
    fontFamily: "Funnel Sans, system-ui, sans-serif"
    fontSize: "11.5px"
    fontWeight: 700
    lineHeight: 1.7
  mono:
    fontFamily: "ui-monospace, Menlo, monospace"
    fontSize: "13px"
rounded:
  xs: "6px"
  sm: "8px"
  control: "10px"
  md: "12px"
  surface: "14px"
  bubble: "16px"
  pill: "99px"
spacing:
  2xs: "4px"
  xs: "6px"
  sm: "8px"
  md: "10px"
  lg: "16px"
  xl: "24px"
  panel: "16px 18px"
  sidebar: "236px"
  chat: "400px"
components:
  button:
    backgroundColor: "{colors.night-panel}"
    textColor: "{colors.cream-ink}"
    rounded: "{rounded.control}"
    padding: "7px 13px"
  button-hover:
    backgroundColor: "{colors.night-panel-2}"
  button-primary:
    backgroundColor: "{colors.star-yellow}"
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.control}"
    padding: "7px 13px"
  button-primary-hover:
    backgroundColor: "{colors.star-hover}"
    textColor: "{colors.navy-ink}"
  button-primary-disabled:
    backgroundColor: "{colors.night-panel-2}"
    textColor: "{colors.night-muted}"
  input:
    backgroundColor: "{colors.night-ground}"
    textColor: "{colors.cream-ink}"
    rounded: "{rounded.control}"
    padding: "8px 11px"
  chip:
    backgroundColor: "{colors.night-panel}"
    textColor: "{colors.cream-ink}"
    rounded: "{rounded.pill}"
    padding: "5px 13px"
  chip-selected:
    backgroundColor: "{colors.night-select}"
    textColor: "{colors.cream-ink}"
    rounded: "{rounded.pill}"
  nav-item:
    textColor: "{colors.night-muted}"
    rounded: "{rounded.control}"
    padding: "9px 10px"
  nav-item-selected:
    backgroundColor: "{colors.night-select}"
    textColor: "{colors.cream-ink}"
    rounded: "{rounded.control}"
  count-badge:
    backgroundColor: "{colors.star-yellow}"
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.pill}"
    height: "20px"
  panel:
    backgroundColor: "{colors.night-panel}"
    textColor: "{colors.cream-ink}"
    rounded: "{rounded.surface}"
    padding: "{spacing.panel}"
  approval-card:
    backgroundColor: "{colors.night-panel}"
    rounded: "{rounded.surface}"
    padding: "14px 16px"
  bubble-user:
    backgroundColor: "{colors.night-panel-2}"
    textColor: "{colors.cream-ink}"
    rounded: "{rounded.bubble}"
    padding: "10px 14px"
  bubble-agent:
    backgroundColor: "{colors.night-ground}"
    textColor: "{colors.cream-ink}"
    rounded: "{rounded.bubble}"
    padding: "10px 14px"
  device-node:
    backgroundColor: "{colors.night-panel}"
    rounded: "{rounded.surface}"
    padding: "9px 10px"
    width: "200px"
---

# Design System: Nightlight

## Overview

**Creative North Star: "The Lamp Left On"**

Nightlight is the landing page's night house turned into a calm working room. The ground is deep navy, text is cream, and the one warm thing in the room is the star yellow light, lit only where something needs the person: the primary button, a count, the verdict when something is wrong. Everything else stays quiet, so the light means something when it appears. The day theme is the same house with the curtains open: warm cream ground, navy ink, the same star.

The app shell is a slim left sidebar, the home in the middle (the verdict sentence on top, then filters and the house map), and the "Ask Nightlight" chat docked on the right. That form was chosen by the owner directly, not generated. Surfaces are soft rounded panels with hairline navy borders and lucide line icons at one stroke weight. Density is moderate: a non-technical owner should read the screen as sentences before they read it as data.

The world is shared with the marketing landing (same navy steps, same star, same Funnel Display and Funnel Sans), so a person who arrives from the landing should feel they walked into the house they were just shown. The landing's typography ramp is larger and more theatrical; the app keeps the faces and the palette, not the scale.

**Key Characteristics:**
- Two themes that share token names: night (navy ground, cream text, star accent) and day (cream ground, navy ink, navy accent, same star for the primary action).
- Star yellow is scarce: primary action, counts, "needs you".
- Status colours (green, amber, soft coral) only ever appear with a word.
- Selection is a lighter navy step with a thin accent ring, never grey.
- The verdict strip's star light is the signature: a slow soft glow when something needs you, a quiet green dot otherwise.
- The traced mascot appears in the empty chat and switches to its thinking mood while Nightlight works.

## Colors

A strict three-colour world, navy, star yellow and cream, with three status hues held on a short leash.

### Primary
- **Star Yellow** (star-yellow): the primary button fill, the count badges in the sidebar and phone tab bar, the verdict light when something needs you, the "needs you" border tint on the verdict strip, and the night theme's accent (focus ring, selected-nav ring and icon, selected device ring). Text on it is always Navy Ink.
- **Star Hover** (star-hover): the primary button's hover fill, a half step lighter. Never used at rest.
- **Star Gold** (star-gold): the dot of light in the wordmark on cream backgrounds only, where full Star Yellow would wash out. Not a UI colour.

### Neutral (night)
- **Night Ground** (night-ground): the page ground and the agent's chat bubbles and inputs, the darkest step.
- **Night Panel** (night-panel): sidebar, chat column, panels, cards and device tiles; one step up from the ground.
- **Night Panel Raised** (night-panel-2): hover fill for buttons and nav items, the person's own chat bubbles, the disabled primary button.
- **Night Selection** (night-select): the selected nav item, chip and segmented option. A lighter navy step, not a grey.
- **Night Hairline** (night-line) and **Night Rule** (night-line-strong): panel and divider hairlines, then control borders.
- **Cream Ink** (cream-ink): all body and heading text on night.
- **Mist** (night-muted): secondary text, idle nav items, legends.

### Neutral (day)
- **Warm Cream Ground** (day-ground), **Paper** (day-panel), **Paper Raised** (day-panel-2): the same three surface steps, inverted warm.
- **Day Hairline** (day-line) and **Day Rule** (day-line-strong): borders, a warm sand rather than grey.
- **Navy Ink** (navy-ink): all text on light surfaces, the day theme's accent (focus ring, selected ring, links), and the text on every Star Yellow fill in both themes.
- **Slate Navy** (day-muted): secondary text on cream.
- **Day Selection** (day-select): a navy tint at 8% over cream.

### Status (both themes; never decorative)
- **Fine** (night-ok / day-ok): device rings and gauges that are healthy, the calm verdict dot, "routine" risk badge.
- **Needs a look** (night-warn / day-warn): amber rings, gauges, "some risk" badge.
- **Broken** (night-crit / day-crit): soft coral rings, the outer warning halo on a broken device, "risky" badge, destructive buttons.
- **Silent** (night-offline / day-offline): devices that are not answering, plain map wires.

The night status hues are pastel so they read on navy; the day hues are deepened so they pass contrast on cream. Pick the set that matches the theme; never mix.

### Named Rules
**The Lamp Rule.** Star Yellow is spent only on the primary action, counts and "needs you". If a screen has two yellow things that are not one of those, one of them is wrong.

**The Said-Aloud Rule.** Green, amber and coral are status only and always travel with a word ("needs you", "1 needs a look", "Disk 94"). A coloured dot or ring is never the whole message.

**The Navy Ink Rule.** Text on a light surface (cream, paper, star yellow) is Navy Ink, never black.

## Typography

**Display Font:** Funnel Display (with system-ui)
**Body Font:** Funnel Sans (with system-ui, -apple-system, Segoe UI)
**Mono Font:** ui-monospace, Menlo (commands and codes only)

**Character:** sister faces from one family; Display carries a little more shape for the sentences that matter, Sans stays plain and friendly for everything else. Both load through next/font as `--font-display` and `--font-sans`.

### Hierarchy
- **Display** (display): the verdict sentence ("2 things need you, 1 urgent" / "All good"). Drops to 19px on phones.
- **Headline** (headline): the empty chat's greeting under the mascot.
- **Title** (title): panel headings; the chat column's "Ask Nightlight" sits one step smaller at 17px.
- **Title Small** (title-sm): sub-section headings inside panels and the device drawer.
- **Body** (body): all UI text, buttons, nav, chat bubbles (bubbles open up to 1.55 line height for long answers).
- **Body Small** (body-sm): details, approval-card terms, chips, legends.
- **Label** (label): the sidebar's group label ("Add to your home"), sentence case, muted, untracked.
- **Badge** (badge): count badges and risk badges; weight 700, tabular feel.

### Named Rules
**The Sentence-First Rule.** The largest type on any app screen is a plain-language sentence about the home, set in Funnel Display at weight 650. Numbers and device names never outrank it.

**The Wordmark-Is-Art Rule.** "nightlight" is never typed in a font. Use the outlined wordmark component (heavy "night", thin "light", the dot of the second i as the light); it follows `color` and takes its light from the logo-light token.

## Layout

**Shell (desktop, above 1180px):** three columns: a 236px sidebar, a fluid home column, and a chat column of 340 to 400px, full viewport height with each column scrolling on its own. The home column pads 22px 24px 32px and caps its content at 880px; its children stack with a 16px gap.

**Narrow desktop (901 to 1180px):** sidebar 216px, chat fixed at 340px, home column padding 18px.

**Phones and narrow windows (900px and below):** one pane at a time. A top bar (wordmark, menu button) replaces the sidebar, which becomes a slide-in drawer (up to 300px or 84vw) over a navy scrim; a two-tab Home / Chat bar sits at the bottom with safe-area padding, the active tab marked by a 2px accent line on top. Icon buttons are 44px square. Inputs in the chat are 16px so iOS does not zoom.

**Map:** the house map canvas is min(64vh, 620px) tall, at least 360px; the filter row above it scrolls sideways with a soft fade at its right edge rather than wrapping. Below 700px the list view becomes a grid of tiles.

**Rhythm:** small steps of 4, 6, 8 and 10px inside components; 16px between panels; panels pad 16px 18px.

## Elevation & Depth

A hybrid: depth is mostly tonal (ground, panel, raised panel), with one soft drop shadow shared by panels, cards, device tiles and floating toolbars. At night the shadow adds a faint top highlight and a deep navy fall-off; by day it is a short navy-tinted shadow. There is no shadow ladder: things are either on the ground or one step up.

### Shadow Vocabulary
- **Panel lift** (night: `0 1px 0 rgb(255 255 255 / .03) inset, 0 10px 28px -12px rgb(3 7 20 / .6)`; day: `0 1px 2px rgb(21 34 74 / .05), 0 10px 26px -14px rgb(21 34 74 / .22)`): panels, approval cards, modals, device tiles, the slide-in sidebar.
- **Status halo** (`0 0 0 3px` of the status or accent colour at 15 to 35%): a broken device tile, a selected device tile, a picked option. A ring, not a lift.
- **Verdict glow** (`0 0 0 4px` star at 22% plus `0 0 18px 2px` star at 55%, breathing to a wider, fainter glow over 3.2s): only on the verdict light when something needs you.
- **Scrim** (navy `rgb(5 10 26 / .6)` with a 2 to 3px backdrop blur): behind modals and the phone sidebar.

### Named Rules
**The Still Control Rule.** Effects never change how a control looks while it is being used. Glows, pulses and line animations live on indicators (the verdict light, a running step dot, a flowing map wire), never on a button, input or chip being pressed, typed into or chosen.

**The One Glow Rule.** Only the verdict light glows. Every other emphasis is a ring or a border.

All motion stops under reduced motion: the verdict glow, pulsing step dots, flowing wires and the sidebar slide.

## Shapes

Soft, rounded and consistent. Controls (buttons, inputs, selects, nav items) take gently rounded 10px corners; surfaces (panels, cards, device tiles, the map canvas, modals) take 14px. Chat bubbles round to 16px with the corner nearest their speaker cut to 4px, so the tail points home. Chips, counts, risk badges and the sample label are full pills. Small insets (code blocks, check-up results) use 6 to 8px. Borders are hairlines (1px, 1.5px on device tiles); dashed borders mean "simulated" (the sample label, sample device tiles) or "drawn by Nightlight" (auto-made map links). Device icons sit in a circle whose 2.5px inner ring carries the status colour.

## Components

### Buttons
Calm and solid; only one per area is yellow.
- **Shape:** gently rounded (rounded.control), 7px 13px, weight 550.
- **Default:** panel fill, Rule border, ink text; hover steps to the raised panel. Colour transitions at 150ms, nothing moves.
- **Primary:** Star Yellow fill, Navy Ink text, no border, weight 650; hover to Star Hover. Disabled primary goes to the raised panel with muted text, not a faded yellow.
- **Danger:** Broken-coral fill with Night Ground text at night and Paper text by day, only for removing a device after a confirm step.
- **Focus:** a 2px accent outline offset by 2px (star at night, navy by day).

### Chips and segmented controls
- **Chips:** full pills, 5px 13px, hairline border, weight 500. Selected: Selection fill, ink text, accent border, weight 600.
- **Segmented (Map / List, Quick / Investigate deeply):** joined buttons with 8px outer corners; the chosen half takes the same Selection fill and accent border.

### Inputs / Fields
- **Style:** ground fill (one step below the panel they sit on), Rule border, 10px corners, 8px 11px. Selects carry a thin chevron.
- **Focus:** the border disappears into a 2px accent outline at zero offset.

### Navigation (sidebar)
- **Items:** lucide icon at 18px and 1.75 stroke plus a label, 9px 10px, muted text; hover takes the raised panel and ink text.
- **Selected:** Selection fill, ink text at weight 650, a 1px inset ring of the accent at 45%, the icon in the accent colour.
- **Count:** a Star Yellow pill with Navy Ink figures at the end of the row.
- **Order:** wordmark, the dashed "Sample home, simulated" pill, Home / Activity / Trust / Memory, the "Add to your home" group, then a foot (demo tools, theme switch, Save with Google, account) above a hairline.

### Verdict strip (signature)
A panel at the top of the home column. The sentence in Display type, its light to the left: a 12px Fine-green dot in a soft ring when all is well; a glowing Star Yellow dot and a star-tinted border when something needs you. Below a hairline, one row per item: status dot, device name in muted text, the plain sentence, and one button (the primary only for the item awaiting approval).

### Device tile (map)
A 200px panel tile with a 1.5px border: a circular icon whose ring is the status colour, the device name, three ring gauges (Disk, Mem, CPU) labelled under each, and a footer of app dots with a worded summary ("2 apps · needs you"). Broken tiles take a coral border and halo; selected tiles take an accent halo; sample tiles are dashed. A count mark sits on the top-right corner.

### Approval card
A raised panel with a Rule border: what happens, what it touches, how to undo, and status in a two-column term list (92px terms), with a risk pill (safe / some risk / risky) and Approve (primary) beside Not now.

### Chat
The docked column on the panel colour, headed "Ask Nightlight" with a chat icon. The person's bubbles sit right on the raised panel; Nightlight's sit left on the ground colour. Earlier turns fade to 75% unless they still hold a waiting card. The work log is a collapsible hairline box in small muted type. Empty chat: the traced mascot, a Headline greeting, and full-width starter questions that take an accent border on hover. While working, the mascot switches to its thinking mood.

### Mascot
Sadika's traced ninja with the star balloon, used as supplied in flat fills, idle or thinking. Never redrawn, restyled, outlined or given gradients beyond its own star halo.

## Do's and Don'ts

### Do:
- **Do** keep the palette to navy, star yellow and cream; use green, amber and soft coral only as status, and always with a word next to them.
- **Do** spend Star Yellow only on the primary action, counts and "needs you".
- **Do** show selection as the Selection navy step with a thin accent ring or border.
- **Do** set every text on cream, paper or yellow in Navy Ink.
- **Do** use the theme's own status set (pastel at night, deepened by day).
- **Do** use lucide icons at 18px and 1.75 stroke in the shell.
- **Do** use the outlined wordmark component and the supplied mascot art as they are.
- **Do** mark anything simulated with a dashed border and the word "simulated" or "sample".

### Don't:
- **Don't** use grey for selection, hover or borders; every neutral here is a navy or a warm sand.
- **Don't** use black text on light surfaces.
- **Don't** let a glow, pulse, lift or animation change how a button, input or chip looks while it is being used.
- **Don't** put a status colour on anything that is not a status, or show a status by colour alone.
- **Don't** set "nightlight" in live text or redraw the mascot.
- **Don't** add a page-level toolbar of buttons above the home column; actions live in the sidebar, in the verdict strip beside the verdict, and next to the thing they act on.
