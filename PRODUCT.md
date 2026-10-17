# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

People who look after a handful of machines at home or in a small office (a Raspberry Pi, a NAS, a game server, a router, a website) but are not technical. Someone who has never opened a terminal must understand every screen at a glance. Hackathon judges arrive through the one-click "Try the demo" with a simulated sample home.

## Product Purpose

Nightlight is a house-sitter for home and small-office servers: a small warm light that watches the machines while you sleep. It notices problems, explains them in plain words, asks before acting (an approval card with plan, dry run, what it touches and how to undo), and earns trust over time so routine fixes can run on their own.

## Positioning

Asks first, in plain words, and lets trust grow per device and per service, instead of either alerting with jargon or acting silently.

## Operating Context

One main screen: a map of the home (place → device → service) with the "Ask Nightlight" chat docked beside it, and a "what needs you" strip on top. Side destinations: Activity, Trust, Memory, adding devices or websites, found-nearby devices, demo tools. Phones show one pane at a time.

## Capabilities and Constraints

- Next.js app in web/; backend in api/ is owned by another team member and is never edited. Contract in docs/API.md.
- Risk badge on every action: routine / service / destructive → safe / some risk / risky.
- Simulated devices are always labelled as simulated.
- Feature freeze Sun 18 Oct 2026 10:00 KST.

## Brand Commitments

- Name written "nightlight" with the outlined wordmark (web/src/components/brand/Logo.tsx); icon is the mascot head on cream.
- Mascot is Sadika's traced ninja/star-balloon art; never redrawn, flat fills.
- Palette is navy, star yellow and cream; green (fine) and amber (needs a look) only as status colours, always with a word.
- Voice: calm, friendly, plain, short, never technical.

## Evidence on Hand

Mocks in contracts/mocks/ (phases, gallery, SSE). No testimonials or metrics exist; do not invent any.

## Product Principles

1. Plain words before data: every state reads as a sentence first.
2. Ask, don't surprise: nothing changes without a clear approval or earned trust.
3. Calm by default: colour and motion signal only what needs the person.
4. Nothing requires expertise or dragging; every control has a plain label.

## Accessibility & Inclusion

Text contrast ≥ 4.5:1, icons and borders ≥ 3:1, status never by colour alone, respects reduced motion, both themes checked.
