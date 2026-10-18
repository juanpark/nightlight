---
name: Nightlight
description: A house-sitter for home servers; a small warm light that watches the machines while you sleep.
colors:
  paper: "#fcfbf8"
  card-white: "#ffffff"
  paper-raised: "#f3f2ee"
  frame-paper: "#f4f3ef"
  hairline: "#e8e6e0"
  rule: "#cfccc3"
  rule-hover: "#b9b5aa"
  field-line: "#8d8a82"
  ink: "#1a1a18"
  ink-hover: "#3a3935"
  graphite: "#5e5d58"
  pencil: "#8a8882"
  dot-grid: "#d9d6cd"
  star-yellow: "#fdd83a"
  star-hover: "#ffe14f"
  star-edge: "#e9c21f"
  star-deep: "#b38600"
  logo-light: "#f5c400"
  ok-text: "#1d7a3c"
  ok-fill: "#22a447"
  warn-text: "#b85a00"
  warn-text-landing: "#a24f00"
  warn-fill: "#d97706"
  crit-text: "#c0352b"
  crit-fill: "#ec3d32"
  offline-text: "#5e5d58"
  offline-fill: "#8e8c86"
  night-ground: "#0b1430"
  night-panel: "#111c3d"
  night-panel-raised: "#18254b"
  night-line: "#22305c"
  night-rule: "#33457a"
  night-select: "#1d2b5a"
  night-field-line: "#5f72a8"
  cream-ink: "#f4efe4"
  night-muted: "#a5a7ab"
  night-star-hover: "#ffe36a"
  navy-ink: "#15224a"
  night-ok: "#70d795"
  night-warn: "#fab050"
  night-crit: "#fb817a"
  night-offline: "#97a1bb"
typography:
  display:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "clamp(2.9rem, 7vw, 6rem)"
    fontWeight: 450
    lineHeight: 0.98
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "clamp(1.9rem, 3vw, 2.75rem)"
    fontWeight: 450
    lineHeight: 1.08
    letterSpacing: "-0.025em"
  verdict:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Funnel Display, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.005em"
  lede:
    fontFamily: "Funnel Sans, system-ui, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 400
    lineHeight: 1.5
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
  button-landing: "12px"
  surface: "14px"
  frame: "16px"
  bubble: "18px"
  dialog: "24px"
  pill: "99px"
spacing:
  2xs: "4px"
  xs: "6px"
  sm: "8px"
  md: "10px"
  lg: "16px"
  xl: "24px"
  panel: "14px 16px"
  gutter: "clamp(16px, 4vw, 56px)"
  content-max: "1200px"
  chat: "340px to 400px"
components:
  button:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 13px"
  button-hover:
    backgroundColor: "{colors.paper-raised}"
  button-primary:
    backgroundColor: "{colors.star-yellow}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 13px"
  button-primary-hover:
    backgroundColor: "{colors.star-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.graphite}"
  button-landing-primary:
    backgroundColor: "{colors.star-yellow}"
    textColor: "{colors.ink}"
    rounded: "{rounded.button-landing}"
    height: "48px"
    padding: "0 20px"
  button-landing-secondary:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.button-landing}"
    height: "48px"
    padding: "0 20px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 11px"
  chip:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "5px 11px"
  panel:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.surface}"
    padding: "{spacing.panel}"
  approval-card:
    backgroundColor: "{colors.card-white}"
    rounded: "{rounded.surface}"
    padding: "14px 16px"
  accordion-step:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.button-landing}"
    padding: "14px 16px"
  product-frame:
    backgroundColor: "{colors.frame-paper}"
    rounded: "{rounded.frame}"
  start-dialog:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.dialog}"
    padding: "32px 28px 24px"
  bubble-user:
    textColor: "{colors.ink}"
    rounded: "{rounded.bubble}"
    padding: "9px 14px"
  count-badge:
    backgroundColor: "{colors.star-yellow}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    height: "20px"
  night-panel:
    backgroundColor: "{colors.night-panel}"
    textColor: "{colors.cream-ink}"
    rounded: "{rounded.surface}"
  night-button-primary:
    backgroundColor: "{colors.star-yellow}"
    textColor: "{colors.navy-ink}"
    rounded: "{rounded.control}"
---

# Design System: Nightlight

## Overview

**Creative North Star: "The Lamp Left On"**

Nightlight is a quiet room with one warm light in it. The room is calm paper and near-black ink: a near-white cream ground, white cards on hairlines, graphite for everything secondary. The one warm thing is the star yellow, and it is lit only where the person is needed: the main action, a count, the verdict when something is wrong. Because nothing else glows, the light means something when it appears. The same house has a night setting (deep navy ground, cream ink, the same star), offered as a toggle rather than the default.

The world is shared end to end. The "/" landing is a walk through the product itself: a large two-tone headline (ink, then a softer pencil grey for the quiet half), then the real dashboard framed on a dot grid, chapter by chapter, with a list beside each frame that changes what it shows. The app is the same palette at working scale: a calm header, the home with its verdict strip and house map, and the "Ask Nightlight" chat docked on the right. A visitor who clicks Get started should feel they stepped into the frame they were just looking at.

Density is moderate and sentence-led. A non-technical owner reads every screen as plain sentences before data. Motion is slow and soft (an exponential ease-out) and lives on indicators and reveals, never on a control being used. Character comes from the outlined wordmark, the traced mascot used sparingly, and the precision of the details, not from decoration.

**Key Characteristics:**
- Light mono by default: near-black ink on near-white cream, white cards, warm hairlines; navy night as an alternative theme with the same token names.
- Star yellow is scarce: the main action, counts, "needs you", and the verdict light.
- Status colours (green, amber, red, slate) only ever travel with a word.
- Two-tone headlines: the first half in ink, the quiet half in pencil grey.
- The product is shown, not described: framed canvases of the real dashboard on a dot grid, labelled "Sample home · simulated".
- Phosphor regular icons at one stroke weight, through a single icon module.

## Colors

A strict monochrome of paper and ink, with one warm star and four status hues on a short leash.

### Primary
- **Star Yellow** (star-yellow): the fill of the one main action per area (Get started, Add a device, Approve, Sign in with Google in the start dialog), count badges, the verdict light when something needs you, and the "needs you" tint on the verdict strip's border. Text on it is always Ink in day and Navy Ink at night.
- **Star Hover** (star-hover): the main action's hover fill, a half step lighter. Never at rest.
- **Star Edge** (star-edge): the 1px border that holds a star-filled button against white.
- **Star Deep** (star-deep): the cursor light's rim on the landing and the gold of its lit dot grid; also the favourite star's edge in the app. Never a fill.
- **Logo Light** (logo-light): the dot of light in the wordmark only.

### Neutral (day, the default)
- **Paper** (paper): the page ground, inputs, and the start dialog's surface.
- **Card White** (card-white): panels, cards, device tiles, accordion rows, chat column.
- **Paper Raised** (paper-raised): hover fill for buttons and menu items, the disabled main button.
- **Frame Paper** (frame-paper) with **Dot Grid** (dot-grid): the ground of every framed product canvas on the landing, a 1px dot every 18px.
- **Hairline** (hairline) and **Rule** (rule): panel and divider hairlines, then control borders. **Rule Hover** (rule-hover) is a control's border on hover.
- **Field Line** (field-line): the outline of anything you type in or pick from, at least 3:1 on every surface.
- **Ink** (ink): all body and heading text, the focus ring, the day accent, and the text on star yellow. **Ink Hover** (ink-hover) is an ink-filled button on hover.
- **Graphite** (graphite): secondary text, legends, idle icons, step numbers.
- **Pencil** (pencil): the quiet half of a two-tone headline. Large text only (it is 3.5:1 on white).

### Status (day)
Each status has a text strength (≥ 4.5:1, for words and small icons) and a livelier fill (≥ 3:1, for dots, rings, borders and meters).
- **Fine**: ok-text / ok-fill.
- **Needs a look**: warn-text / warn-fill. The landing deepens the text strength to warn-text-landing so it holds 4.5:1 on its tinted toasts; the app still ships warn-text.
- **Broken**: crit-text / crit-fill.
- **Not answering**: offline-text / offline-fill, with dashed borders.

### Night theme
The same roles under the same token names: **Night Ground** (night-ground), **Night Panel** (night-panel), **Night Panel Raised** (night-panel-raised), **Night Hairline** (night-line), **Night Rule** (night-rule), **Night Selection** (night-select), **Night Field Line** (night-field-line), **Cream Ink** (cream-ink) for text, **Night Mist** (night-muted) for secondary text. At night the accent is the star itself (focus ring, selected ring), and text on yellow is **Navy Ink** (navy-ink). Night status hues are pastel (night-ok, night-warn, night-crit, night-offline) so they read on navy; pick the set that matches the theme and never mix.

### Named Rules
**The Lamp Rule.** Star yellow is spent only on the main action, counts, "needs you" and the verdict light. If an area has two yellow things that are not one of those, one of them is wrong.

**The Said-Aloud Rule.** Green, amber, red and slate are status only, and always travel with a word ("Needs a look", "Disk 94% full"). A coloured dot or ring is never the whole message.

**The Ink-Not-Black Rule.** Text is warm near-black Ink, never #000; neutrals are warm sands and graphites, never cool greys.

## Typography

**Display Font:** Funnel Display (with system-ui)
**Body Font:** Funnel Sans (with system-ui, -apple-system, Segoe UI)
**Mono Font:** ui-monospace, Menlo (commands and codes only)

**Character:** sister faces from one family. Display at a light weight carries the landing's big calm sentences and at a firm weight carries the app's verdict; Sans stays plain and friendly for everything else. Both load through next/font as `--font-display` and `--font-sans`.

### Hierarchy
- **Display** (450, clamp(2.9rem, 7vw, 6rem), 0.98): the landing hero only ("Go to sleep." / "It's got this."), the quiet half on its own line in Pencil.
- **Headline** (450, clamp(1.9rem, 3vw, 2.75rem), 1.08): landing chapter headings, two-tone. Big statements and the closing call step up to clamp(2rem, 3.6vw, 3.25rem).
- **Verdict** (650, 22px, 1.2): the app's verdict sentence ("4 things need you" / "All good"); 19px on phones.
- **Title** (650, 18px, 1.3): panel headings in the app.
- **Lede** (400, 1.1875rem, 1.5, max 40ch): the landing's opening paragraph, in Graphite.
- **Body** (400, 15px, 1.5): all app UI text, buttons, chat. The landing reads at 16px with 17px chapter text, max 46ch.
- **Body Small** (400, 13px): details, approval-card terms, chips, legends.
- **Label** (600, 12.5px): menu group labels, sentence case, untracked.
- **Badge** (700, 11.5px): counts and risk pills.

### Named Rules
**The Sentence-First Rule.** The largest type on any app screen is a plain sentence about the home. Numbers and device names never outrank it.

**The Two-Tone Rule.** A landing heading says one thing in Ink and finishes it in Pencil ("It notices / often before things break"). Never a third colour, never gradient text.

**The Wordmark-Is-Art Rule.** "nightlight" is never typed in a font. Use the outlined wordmark component (heavy "night", thin "light", the dot of the second i as the light).

## Layout

**Landing:** one content column, max 1200px, centred with a fluid side gutter of clamp(16px, 4vw, 56px). The sticky header's frosted bar runs edge to edge, but its contents sit on the same 1200px column. The hero sets the headline left and the lede with actions right, both sitting on the headline's baseline, then a full-width framed dashboard starting above the fold. Chapters alternate text-left/canvas-right and flip; sections are separated generously (roughly 96 to 176px). Below 960px everything stacks to one column, and in a chapter the canvas sits between the words and the list that changes it.

**App shell (desktop):** a calm header (wordmark, the dashed sample pill, the verdict when the strip is scrolled away, Add a device as the one yellow button, More), then the home column and the chat docked right at 340 to 400px. Each column scrolls on its own. Panels stack with a 16px gap.

**Phones (900px and below in the app):** one pane at a time with a Home / Chat tab bar at the bottom, safe-area padded. Inputs are 16px so iOS does not zoom.

**Touch:** on coarse pointers every control is at least 44px; the landing's product canvases keep their app-scale density for a mouse and grow for a finger.

**Rhythm:** small steps of 4, 6, 8 and 10px inside components; 16px between panels.

## Elevation & Depth

A hybrid, mostly tonal: paper ground, white card, raised paper on hover. One soft long shadow lifts panels, cards and tiles; a stronger lift marks something raised above its siblings (selected, opened, a sheet, a floating card). There is no ladder beyond that: things sit on the ground, lift one step, or float.

### Shadow Vocabulary
- **Card shadow** (`0 1px 2px rgb(26 26 24 / .04), 0 18px 40px -22px rgb(26 26 24 / .22)`; app `--shadow` is the shorter `0 12px 28px -16px` cut): panels, cards, device tiles, open accordion rows.
- **Float shadow** (`0 2px 4px rgb(26 26 24 / .04), 0 28px 56px -24px rgb(26 26 24 / .3)`): cards floating over a canvas, the start dialog (deeper, `0 40px 80px -32px` at .4).
- **Status halo** (`0 0 0 3px` of a status fill at 15 to 20%): a broken device tile. A ring, not a lift.
- **Verdict glow** (`0 0 0 4px` star at 22% plus `0 0 18px 2px` star at 55%, breathing wider over 3.2s): only the verdict light when something needs you.
- **Night panel lift** (`0 1px 0 rgb(255 255 255 / .03) inset, 0 10px 28px -12px rgb(3 7 20 / .6)`): the night theme's version of the card shadow.

### Named Rules
**The Still Control Rule.** Effects never change how a control looks while it is being used. Glows, pulses, the cursor light and flowing wires live on indicators and the ground, never on a button, input or chip being pressed, typed into or chosen.

**The One Glow Rule.** Only the verdict light glows. Every other emphasis is a ring, a border or a lift.

Under reduced motion every reveal shows in place, the verdict glow and flowing wires stop, and the custom cursor turns off.

## Shapes

Soft and consistent. App controls (buttons, inputs, selects, menu items) round to 10px; the landing's larger buttons and accordion rows to 12px; panels, cards and device tiles to 14px; product frames to 16px; chat bubbles to 18px with the corner nearest the speaker cut to 6px; the start dialog to 24px. Chips, counts, risk badges and the sample pill are full pills. Borders are hairlines (1px; 1.5px on device tiles). Dashed borders mean one of two things only: simulated (the sample pill, sample tiles) or not answering (an offline tile).

## Components

### Buttons
Calm and solid; only one per area is yellow.
- **Shape:** 10px in the app (7px 13px, weight 550); 12px and 48px tall on the landing (38 to 44px in the header).
- **Main:** Star Yellow with a Star Edge border and Ink text, weight 600 to 650; hover to Star Hover. Disabled goes to Paper Raised with Graphite text, never a faded yellow.
- **Default / Secondary:** Card White, Rule border, Ink text; hover to Paper Raised with Rule Hover border. Colour transitions at 150ms; nothing moves.
- **Danger:** Broken red fill, only after a confirm step.
- **Focus:** a 2px Ink outline offset 2 to 3px (the star at night).

### Chips
Full pills, hairline Rule border, weight 500; hover takes Paper Raised and an Ink border. Used for suggested questions and filters.

### Inputs / Fields
Paper fill, Field Line border, 10px corners, 8px 11px. Focus drops the border into a 2px Ink outline at zero offset. Selects carry a thin chevron.

### Navigation
- **Landing header:** sticky frosted bar (paper at 86% with a 12px blur): wordmark left, a segmented pill of section links centre (Graphite, hover to Paper Raised and Ink), Get started right. Below 960px the links fold away.
- **App header:** wordmark, the dashed "Sample home · simulated" pill, the verdict pill when the strip is out of view, Add a device (yellow), and a More menu holding the side destinations, theme switch and account. Selected menu items take a faint ink selection fill with a thin accent ring.

### Accordion steps (landing)
White rows with a hairline, 12px corners: a Graphite step number ("1.1"), a 600-weight title and a plus that turns to a cross when open. One open at a time; clicking the open row closes it; the body slides open on grid rows over 0.4s. Hover (pointer devices only) strengthens the border, warms a closed row a step and inks the number and icon. Opening a row changes the canvas beside it.

### Product frame (landing signature)
Every picture of the product sits in a 16px-rounded frame on Frame Paper with a dot grid, captioned "Sample home · simulated" bottom-left. Inside, the dashboard is drawn at app scale: verdict strip, device tiles on wires, the chat, the approval card, the trust ladder. Anything drawn as a button works. On a mouse, the pointer's position lights the dot grid near it: a soft star wash and the nearest dots turning gold, inside frames only.

### Pointer (landing, mouse only)
A 6px Ink dot with a paper edge sits exactly on the pointer; a 34px hairline ring trails it and stretches along its direction of travel. Over anything clickable the ring opens to 52px around it with no fill, so the control looks exactly like itself; over a text field the dot becomes a 2×20 caret; a press tightens the ring. Touch screens and reduced motion keep the system pointer.

### Motion (landing)
One authored moment: the home coming online. The hero headline rises line by line through a mask, the dashboard opens from a clipped inset, its wires spread out from the router, the tiles settle in from the centre and the reports arrive last (about 2s, nothing waits on it). Further down, headings reveal by line, chapter lists cascade and each canvas opens with its contents in order; on a desktop with a mouse the canvases drift ±36px against the scroll. Smooth scrolling (Lenis) glides wheels and trackpads; touch scrolls natively. Everything uses the expo ease-out and is visible without script, in print and under reduced motion.

### Verdict strip (app signature)
A panel at the top of the home. The sentence in Verdict type with its light to the left: a 12px green dot in a soft ring when all is well; a breathing Star Yellow light and a star-tinted border when something needs you. Below a hairline, one row per item: status, device, the plain sentence and one action.

### Device tile
A white tile with a 1.5px border: a circular icon whose 2px inner ring carries the status fill, the name with its purpose beneath in Graphite, the status word with its icon, and one plain line. Broken tiles take a red border and halo; offline tiles are dashed; a tile being checked takes an Ink border.

### Approval card
A white card with a Rule border: what it will do, what happens, what it affects and whether it can be undone, as a term list (92px terms in Graphite), a risk pill (safe / some risk / risky), then the main action (Approve, yellow) beside Not now.

### Start dialog
Opened by Get started, centred on a softened ink scrim (bottom-anchored on phones). Paper surface, 24px corners, the wordmark on top, a Display-face question, a green "Nightlight is live" status line, then the start choices as white cards. Only the first card's button is yellow. Its content scrolls inside a still frame so Close stays in reach; Tab is kept inside and the page behind is inert.

### Chat
The person's bubbles sit right on a faint ink tint; Nightlight answers as plain text up to 62ch, with its checked steps listed above in small Graphite type. Suggested questions are chips; the field and Send sit in one bordered row.

### Mascot
Sadika's traced ninja with the star balloon, used as supplied in flat fills (idle, working, done). Small and purposeful: the chat's empty state and working moments, never the subject of the landing. Never redrawn, restyled, outlined or given gradients beyond its own star halo.

## Do's and Don'ts

### Do:
- **Do** keep the day palette to paper, white, warm hairlines and Ink, with Star Yellow as the only non-status colour.
- **Do** spend Star Yellow only on the main action, counts, "needs you" and the verdict light: one yellow button per area.
- **Do** pair every status colour with a word, using the text strength for words and the fill for dots, rings and meters.
- **Do** show the product inside a dot-grid frame labelled "Sample home · simulated" rather than describing it.
- **Do** set landing headings two-tone, Ink then Pencil, at Funnel Display 450.
- **Do** use Phosphor regular icons through the shared icon module, at one stroke weight.
- **Do** give every control at least 44px on touch screens and a 2px Ink focus ring.
- **Do** keep the night theme on the same token names, with its own pastel status set.

### Don't:
- **Don't** use #000 or cool greys; every neutral here is a warm sand, graphite or ink.
- **Don't** put two yellow things in one area unless both are counts or "needs you".
- **Don't** show a status by colour alone, or put a status colour on anything that is not a status.
- **Don't** let a glow, pulse, cursor effect or animation change how a button, input or chip looks while it is being used.
- **Don't** use Pencil for small text; it is for the large quiet half of a heading only.
- **Don't** type "nightlight" in live text or redraw the mascot; don't make the mascot the subject of the landing.
- **Don't** use duotone icons, Lucide, emoji or Unicode glyphs as icons.
- **Don't** add 3D renders or pixel art.
