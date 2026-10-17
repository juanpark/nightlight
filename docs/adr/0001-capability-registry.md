# ADR 0001: One capability registry for everything a device can do

Status: accepted (2026-10-17)

## Context
Real-device jobs grew one at a time (restart, look into, look around, clean up, update the helper, remove the
device, expert commands, investigation grants). Each new kind added `if type == ...` branches in several places:
proposing, deciding, the helper's result, follow-ups, Activity, an endpoint-level hook for removals, and playbook
handling inside the result path. Behaviour was correct and tested, but the rules for any one job were scattered, so
the next job would add more branches.

## Decision
Each capability is declared once (`capabilities.py`) with:
- **build**: validate the parameters against the device and return the card (plan, what happens, undo, risk) and
  the clean parameters to store;
- **approval**: `device` (allowed on the device itself, runs without a card), `card` (one tap), `passkey` (a card
  signed with the owner's passkey);
- whether it may be asked for while the device is silent, whether it runs on the device at all (an investigation
  grant only unlocks other jobs), whether its result keeps output;
- optional hooks: after approval (e.g. a removal the device can't do itself finishes at once), on result (e.g. a
  playbook turns findings into clean-up cards), on signature (e.g. a grant is stored).

One pipeline (`actions.request`, `actions.decide`, `actions.job_result`) handles every capability by asking the
registry. The sample home keeps its own simulated pipeline (trust ladder), but its labels come from the same place.

## Consequences
- Adding a capability is one entry plus its build function and tests; no other file learns its name.
- The existing public functions (`propose`, `request_diagnosis`, ...) stay as thin wrappers, so tools and tests keep
  working while the special cases disappear underneath.
