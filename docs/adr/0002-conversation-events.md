# ADR 0002: Conversation events instead of synthetic follow-up messages

Status: accepted (2026-10-17)

## Context
The chat continued itself in three different ways: a tool-less "continuation" turn written as English text after a
job ended; a fake user turn whose input said "[The owner approved ...]" to resume an investigation; and automatic
looks that bypassed the chat. Each built its own prompt string.

## Decision
Things that happen outside the person's own messages are **events** posted to the session: `job_finished`,
`job_declined`, `investigation_approved`. An event turn stores the event as data (type, action id, mode). The turn
runner turns events into the model's input with one formatter and applies one policy per event type:
- `job_finished` / `job_declined`: narrate what happened, no new proposals (no tools) — unless the turn that asked
  was an investigation, which may continue with tools;
- `investigation_approved`: continue the investigation with tools, in Investigate mode.
Events without a chat (asked from the app, or by Nightlight itself) go to Activity and, for findings, the device's
notebook, through the same formatter.

## Consequences
- No synthetic user text; the history shows events as what they are.
- One place decides whether the agent may act after an event, so the rule is reviewable.
