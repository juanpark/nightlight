# What we tested, what is wrong, and what comes next

Nightlight was built in about 72 hours (2026-10-15 22:00 to 2026-10-19 03:29 KST) by two people with AI coding tools.
This page says plainly how we tested it, what we know is wrong, why, and what we will do about it. Every number here
comes from a log, a report or a commit in this repository; anything we could not re-verify is marked *(unverified)*.
Every number below was measured; where a figure is an estimate, it says so.

## How we tested

| Method | What it is | Scale |
|---|---|---|
| Unit and integration tests | `api/tests/` against the Firestore emulator with a fake model (`fake_llm.py`); `./scripts/test_api.sh` | 509 test functions |
| Probes against the real model | `scripts/chat_probe.py` plays whole conversations (asks, approvals, denials, injected incidents) to Gemini on Agent Platform and prints what a person would see; `scripts/bench.py` times the demo story (`docs/BENCHMARKS.md`) | per slice |
| Role-played judges | Overnight (Sat to Sun), four rounds of an agent scoring text transcripts against the competition rubric, 19 to 25 asks each, Quick and Investigate, approvals and denials | scores 7.0, 7.6, 7.8, 7.6 of 10 |
| Adversarial rounds | Two rounds: prompt injection, social engineering, impossible asks, Korean, typos, two questions in one | 18 scenes, 47 turns in round 2 |
| Real device, scripted incidents | A Debian VM with six Docker apps through the production API: crashed app, failing health check, a 14 GB log filling the disk, leftover images | round 1: 1 of 4 scenarios worked, 2 partly, 1 broken; round 2 (helper 0.9.29): 3 worked, 1 partly |
| Real device, freestyle | Same VM, incidents the agent had not been written for (`scratchpad/probe/vm3`, Sunday morning) | see below |
| Model A/B | 12 demo asks, 3 runs each, Gemini 3.5 Flash-Lite against Gemini 3.8 Flash | 71 asks |
| Eval suite | `scripts/chat_eval.py`: 30 fixed cases in 14 bug classes, each run N times, deterministic checks on events and home state, pass rate per class, optional LLM judge | 30 cases |

The role-played judges read transcripts only. They never saw the map, the work log or the cards, so their user-experience
scores are a floor, not a measurement. The dip from 7.8 to 7.6 in round 4 was caused by our own fixes from round 3:
an answer that was only its opening line ("Let me check the Raspberry Pi. NAS"), and a decline with a reason ("not now,
they're mid-game") followed by a more disruptive card. Both are gone; both are in the eval suite now.

### Model A/B (Sunday morning)

| | Gemini 3.5 Flash-Lite | Gemini 3.8 Flash |
|---|---|---|
| Demo asks passed | 26 of 36 | 34 of 35 |
| Median full answer (Quick) | 4.6 s | 9.0 s |
| 90th percentile | 5.8 s | 18.7 s |
| Cost per Quick turn | $0.0065 | $0.0164 |
| Thinking | minimal (0 thinking tokens) | low (Flash rejects "minimal") |

Flash-Lite's failures were mostly cards described in words but never created, and once calling a sample device
"simulated". We chose 3.8 Flash for both modes: a card that is there when we say it is matters more than four seconds.
The price is a slow tail: about one answer in ten takes over 18 s, we have seen 60 s in probes, and one live production
answer took 24.6 s (21 s to first words; production smoke test, 2026-10-18 09:30 KST).

### Real device, freestyle round (Sunday)

What worked: a stopped container and a killed container (exit 137) were both diagnosed and fixed with a real restart,
2 of 2. What failed, and was fixed the same day (helper 0.9.30, commits `24aac8c`, `48da750`):

| Failure | Root cause | Fix |
|---|---|---|
| A stale note in the device's notebook beat fresh evidence | notes were given to the model undated, before the readings | notes and profile now arrive dated, after the current readings |
| A CPU hog was invisible | the helper reported load but not which process | CPU sampled in real time, top processes by CPU and by memory, load checked against cores |
| Disk scan only looked in fixed places | `/var/log` and Docker only | the main disk's folders are scanned (Linux; see limits) |
| Exit code 137 was unexplained | the raw code was passed through | said plainly: stopped forcibly, often out of memory |
| No way to read an unapproved app's logs | the logs permission did not exist for that app | the answer says so, and a card asks for the permission |
| Investigate hit a model rate limit (429) and said nothing useful | no fallback | it now falls back to a Quick look and says that it did |

### Eval suite

Baseline on the code before Sunday's rebuild (`--repeat 1`, 2026-10-18 09:13): **23 of 30** runs passed; classes
below the 66% floor were `deny_reason`, `invented_cause` (0 of 2), `risk_first` and `second_card`.

| Run | Code | Repeat | Passed | Classes below 66% |
|---|---|---|---|---|
| Baseline | before the rebuild (Sunday 09:13 KST) | 1 | 23/30 | deny_reason, invented_cause, risk_first, second_card |
| Flash, old prompt and patches | `main` before the rebuild (3.8 Flash) | 3 | 81/90 | invented_cause (2/6) |
| After the rebuild | charter + tool contracts (`be-agent-v2`) | 3 | 81/90 | invented_cause (2/6) |

What this says, honestly: the rebuild did **not** raise the pass rate on this suite; the model switch did (Flash-Lite
scored 23/30 that morning). What the rebuild bought is the same score without the patches: a prompt about 80% smaller,
about 300 fewer lines of rewriting code, failures that are visible instead of quietly rewritten (two answers out of 90
claimed a card that wasn't there; the old code would have edited those sentences), and rules that hold as tool
contracts. The two versions fail differently: the old code still stalled, said an app was absent and chose the wrong
device; the rebuilt one did not. Its remaining failures are all one class, a sentence claiming more than the tools
showed (an unhedged "restarting will clear the lag", a "working normally" for a device whose health is unknown), which
is the claim-level citation item under "The way forward". Two of the 18 failed runs across both evaluations were the
judging model itself hitting Google's rate limit, because we ran both evaluations at once.

## Root causes we understand, and what we did about them on the last day

1. **Prose was the source of truth.** We asked the model to narrate its own steps ("Let me check...") and its own cards
   ("I've put a card up") when the server already knows both and streams them as events. Every mismatch between words
   and state became a server-side patch in `agent.py`'s after-model chain: synthesising a call the model announced,
   making the card the model described, deleting the sentence that claimed it. Those patches are removed. Cards and
   steps come from events; a card exists only when the model called its tool; the server never edits an answer to match.
2. **A model below the reliability floor.** Flash-Lite's missed tool calls were not fixable by instructions. The A/B
   above decided it.
3. **Rules in the prompt instead of in the tools.** The system instruction grew to 11,035 characters and about 70
   rules in 48 hours. It is now a charter of about 2,100 characters (who you talk to, what you know, how you act,
   trust). The rules that used to be sentences are tool contracts, so they hold whatever the model does: a waiting card
   for the same problem is returned instead of a second card; a retry carries how the last attempt failed
   (`lastAttempt`); a restart of an unbacked game world puts up the backup card first (`safer_first`); a clean-up that
   measures empty on a real device says `nothing_to_free` instead of making a card; `check_space` measures the whole
   home; the sample home has a real `update_app` job.
4. **Empty or cut-off answers were shown as answers.** The server now checks the answer and, when it is empty or cut
   off, makes one answer-only retry (no tools); if that fails too, you get an honest line saying Nightlight could not
   finish, not a fragment.
5. **You could not see what an answer cost.** Each answer now carries a receipt: steps taken, seconds, model, cost;
   steps are paired with their results by the model's call id, so parallel checks keep their own results.

## Known limits, honestly

**The agent**

- An answer can still state a cause in prose that no tool stated. The charter forbids it and the eval suite has a class
  for it (`invented_cause`), but there is no claim-level citation yet. Treat "likely cause" as likely.
- The slow tail is real (see A/B). Since Sunday a model call that goes silent (30 s Quick, 45 s Investigate) is cancelled
  and retried once; a second time the turn ends saying Gemini is slow, and never claims nothing changed when something
  did. The budget (2 min Quick, 4 min Investigate) is shown while it works. The old "answer now" instruction, which
  made answers thinner, is gone. The budget is soft: a call already running when it ends may finish.
- The Quick fallback (when Investigate cannot run) happens only before any output has been produced.
- Fixed time windows: "recent failures" means the last 6 hours; a measurement counts as fresh for 3 hours.
- `write_note` records a finding but does not link it to the measurement it came from.
- Playbook (checkup) cards do not check for an earlier waiting twin; on real devices a waiting card is matched by exact
  job only, not by problem.
- Answers vary run to run in wording, order and sometimes first step. Facts come from tools and were correct in every
  probe we read; the choice of what to look at first is the model's.
- Dates in history answers are UTC.

**Real devices**

- Jobs are a fixed list: read-only checks, restart an allowed container or failed service, a clean-up from a fixed list,
  a signed helper update, remove, plus passkey-signed expert commands. No app updates on real devices (the sample home
  has them). The trust ladder (acting on its own after three approvals) applies to the sample home only.
- A clean-up on a real device is not refused when nothing was measured first; on some systems that would trap the agent
  into offering a clean-up that frees nothing. `nothing_to_free` covers the measured case only.
- A newly allowed log permission takes up to about a minute to reach the device.
- The main-disk folder scan is Linux only; a folder that takes over 25 s is skipped and named; without root it
  under-counts.
- Clean-ups that need administrator rights are offered only when the helper has them; the installed service runs
  without them, so on most Linux devices they are not offered.
- Linux (systemd) and macOS (launchd) only. Windows PCs, phones, routers, printers and cameras can only be watched.

**Trying it yourself**

- Linux and Mac: a one-line install today. The Mac installer package and its build pipeline exist
  (`scripts/build_mac_pkg.sh`), but shipping a signed, notarized package waits on Developer ID certificates; until then
  macOS needs an "Open Anyway" step, and we do not recommend it to anyone who would not do that knowingly. Windows is
  unsupported.
- If a visitor's Google account already owns a Nightlight account, linking the anonymous demo visit to it fails
  silently; sign in first.
- Live demo machines for judges: a pool of 5 real VMs, one per judge, kept stopped until asked for. Measured Sunday:
  48–59 s from click to ready (22 runs); "Start fresh" restores the disk from a clean copy in 105–110 s (4 runs); a
  judge leaving frees the machine in about a minute. Copying a VM per judge instead took about 70 s plus pairing, so we
  keep a stopped pool. Limits: 5 at once (a sixth is offered the simulated home or their own computer), one zone, no
  waiting list; restores advance only when the 5-minute sweep or a status check runs; a judge's lease is kept alive by
  the open tab, not by chatting.

**Security and data** (details in `docs/SECURITY.md`): scrubbing of names, addresses and secrets is pattern-based and
best effort; the design relies first on not collecting them. Device tokens are revocable but do not expire or rotate.
`curl | sh` trusts the HTTPS origin. There is no account deletion yet; removed devices are kept 30 days unless you choose
"forget for good". Browser notifications work only while the tab is open.

## The way forward

| Next | Why |
|---|---|
| Structured findings with evidence citations: each finding cites the step id it came from; the UI shows the evidence beside each claim | closes the last gap between words and tools (limit 1 above) |
| `check_speed` and `alternatives` tools; `needs_measurement` on clean-ups | "slow" and "safer option" become measured answers, and a clean-up is never offered on nothing |
| Per-call timeout and a visible time budget in both modes | an honest "Nightlight is slow right now" instead of a thinner answer |
| Investigate as a stated loop: hypotheses, each confirmed or ruled out by a named step | the judges' main ask |
| Linux `.deb`, a Docker image for NAS boxes, Windows helper, signed Mac package | installers without a terminal |
| App updates on real devices with rollback to the previous image; a backup before any clean-up | the two jobs people ask for most |
| Token rotation and expiry; account deletion; local-time dates; roles for family or office members | hygiene |

If you find something not on this list, `scripts/chat_probe.py` and `scripts/chat_eval.py` are the fastest way to show
us: they print exactly what a person would have seen.
