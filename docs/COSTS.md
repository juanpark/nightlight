# What Nightlight costs to run

Last updated: 2026-10-18 (about 11:00 KST). We will refresh these numbers before submission.

What we spent, where, how and why. **Measured** means a number our code or Google recorded.
**Estimate** means list price × usage. Each estimate says how we worked it out.

## Summary

| Category | Amount (USD) | Measured or estimate | What it bought |
|---|---|---|---|
| Production model calls (all time) | **$2.17** spent, 689 calls | measured (budget ledger) | every real answer on the live app since launch: our tests, demos and visitors |
| Development testing with real Gemini and cloud | **about $6.25** (roughly $6) | measured per run by our test harnesses | model choice, prompt rebuild, demo VM checks, demo VM pool build (details below) |
| Cloud Run, Firestore, Scheduler, Cloud Build, Artifact Registry | close to $0 | estimate | the live app; it scales to zero when nobody uses it |
| Demo VM pool (5 e2-small VMs, kept stopped) | about $0.03 per visitor-hour while one runs; about $12/month standing (disks) + under $1/month (snapshots) | estimate (list price) | each visitor gets their own real Linux server to watch Nightlight fix |
| Hard cap on production model spend | **$35** | set in code | a runaway is impossible (see below) |

Claude Code, Codex and Fable were our development tools only. They are not part of the product, and the team pays
for them from its own subscriptions.

## Guards that bound spending

Code: `api/src/nightlight_api/quota.py` and `config.py`.

- **Reserve the worst case first, refund after.** Before each model call, the API reserves the cost of the biggest
  request our limits allow, inside one Firestore transaction. For an everyday (Quick) answer that is $0.01584 per call.
  After the call, it records the real cost from Gemini's usage numbers and gives back the difference. If Gemini does
  not report usage, the full reservation stays counted.
- **Hard budget: $35** (`MODEL_BUDGET_USD`). If a reservation would push the total over $35, the call is refused
  before it reaches Gemini.
- **Call limits:** 120 model calls per user per hour, 100 per visitor address per hour, 2,000 per day in total,
  40 turns per user per hour, 8 model calls per Quick turn, 24 per Investigate turn.
- **Kill switch:** one flag (an environment variable or a Firestore document) stops every model call at once.
- **Scale to zero:** Cloud Run runs 0 to 3 instances for each service, so an idle app costs almost nothing.

## Production usage

The ledger in Firestore (`ops/quota`), read 2026-10-18 at about 10:50 KST:

| Field | Value | Meaning |
|---|---|---|
| `spentUsd` | $2.17 | real cost of finished calls |
| `reservedUsd` | $2.23 | spent plus anything still held; this is what the $35 cap is checked against |
| `calls` | 689 | model calls since launch |

That is about $0.003 per model call on average ($2.17 ÷ 689). Most of those calls ran on the cheaper Flash-Lite
before we moved to 3.8 Flash on 18 Oct.

## Development testing

Each run reported its own cost: Gemini's token counts × list price.

| Run | Cost | What it was for | What we learned |
|---|---|---|---|
| Model A/B: Flash-Lite vs 3.8 Flash, 12 demo questions × 3 | ~$1.18 (Lite $0.33, Flash $0.83) | choose the everyday model | Flash passed 34 of 35, Flash-Lite 26 of 36. We switched to Flash. |
| Eval suite build + baseline (30 runs, twice) | ~$0.65 | make a repeatable test of answer quality | baseline passed 20 then 23 of 30, which showed where the prompt was weak |
| Eval on the rebuilt agent (90 runs) | $1.85 | check the new prompt | 81 of 90 passed |
| Same eval on the old prompt (90 runs) | $1.97 | a fair comparison | also 81 of 90, but the new prompt was right about which device more often (6/6 vs 4/6) and cost a little less |
| Demo VM: free-form test | ~$0.13 | does it work on a real server? | yes |
| Demo VM: round 1 (23 questions) | ~$0.35 | test the demo script on the VM | found leftovers to clean up (a pending card, a stuck job) |
| Visitor-style round 3 (25 questions, 6 Investigate) | total not recorded | rehearse what a first-time visitor would do | no errors, no rate limits; the most expensive turn was $0.032 |
| Demo VM pool: build and tests | ~$0.15 | build 5 demo VMs, golden disk copies, lease and restore tests | restore and lease expiry work |

Total for the measured runs: about $6.25 (roughly $6), all outside the app's own ledger. The eval judge (a second Gemini call that grades each answer) cost only
about $0.03 per 90-run eval.

## Infrastructure

No per-service bill is broken out yet. These are list-price estimates.

| Service | Cost | Basis |
|---|---|---|
| Cloud Run (API and web) | close to $0 at idle | minimum instances = 0; billed only while serving requests. Keeping one instance warm on each service would cost about $1–3 a day. That decision is still open. |
| Firestore | close to $0 | small documents, well inside the free daily quota at our traffic (not measured separately) |
| Cloud Scheduler | close to $0 | one job every 5 minutes; a few jobs a month are free |
| Cloud Build, Artifact Registry | cents | builds on each deploy; container images of a few hundred MB |
| Demo VM pool (5 × e2-small, 20 GB disk each) | about $0.03 per visitor-hour while one runs (VM about $0.02/hour + external IP; a restore adds seconds of an extra disk). Standing cost about $12/month for the 5 disks, under $1/month for golden snapshots. | list prices. VMs are kept stopped, so only disks are billed while idle. |

**Why a pool, and why it can't run up a bill.** Each visitor gets their own real machine. After use it is rolled back
to a clean disk copy. A lease ends after 15 minutes idle (60 minutes at most), and the 5-minute sweep stops any VM
that has no lease, so nothing runs forever.

## What one answer costs

| Kind | Cost | Source |
|---|---|---|
| Quick answer, 3.8 Flash | median about $0.016 | A/B test |
| Quick answer, Flash-Lite | median about $0.0065 | A/B test |
| Investigate (up to 24 steps, medium thinking) | up to about $0.03 per turn in practice | most expensive turn in visitor round 3: $0.032 |

**Why pay 2.5 times more per answer?** Flash-Lite answered wrongly or gave up on about 1 in 4 demo questions;
3.8 Flash on about 1 in 35. For a tool that suggests fixes on someone's server, a wrong answer costs far more
than a cent.

**A busy judging day (estimate):** 500 Quick answers × $0.016 ≈ $8. Even if every call hit the worst case, the
2,000-calls-a-day limit holds a day to about $32 (2,000 × $0.01584). The $35 total cap holds everything else.
At the worst case per call, $35 buys about 2,200 calls; at real costs, many more.

## How to check spend yourself

- **The ledger:** the Firestore document `ops/quota` (`spentUsd`, `reservedUsd`, `calls`). Every answer record
  in the app also stores its own `costUsd` and model name.
- **Cloud Billing:** the Billing reports page in the Google Cloud console, grouped by service, shows the real
  invoice: Agent Platform (Gemini), Cloud Run, Compute Engine (demo VM), Firestore.
- **Our test harnesses** print the cost at the end of each run, for example
  `cost: agent $1.8231 + judge $0.0294 = $1.8525`.
