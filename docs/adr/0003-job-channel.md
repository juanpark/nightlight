# ADR 0003: A held job channel instead of polling

Status: accepted (2026-10-17)

## Context
A device learned about approved work only when it reported (every minute) or, while the owner was chatting, by
polling a claim endpoint every few seconds. Approvals therefore took up to a minute to start, and the polling rate
was a server-side guess about whether someone was watching.

## Decision
Two channels with one job each:
- **State**: the helper reports health every minute, and **right away whenever its state changed**: after it ran a
  job, after it restarted into a new version, and after a change made at the device. A report that comes too soon
  for the server is retried after the gap the server names (at most 20 s), never treated as a failure.
- **Work**: between reports the helper keeps one request open, `POST /helper/jobs/wait`. The server holds it for up
  to 25 seconds with a Firestore listener on this device's approved jobs and answers the moment one appears
  (handing it over in the same transaction as before: at most once). An empty answer just means "ask again".
The device still only dials out; nothing is pushed into it.

## Consequences
- Approved jobs start within about a second, with no polling-rate guesswork (`pollEverySec` stays only for helpers
  from before this change).
- A held request uses a server thread and keeps an instance warm while devices are connected. Fine at this scale;
  at large scale the same contract can be served by a push service (Pub/Sub, or an HTTP/2 stream) without changing
  the helper's side of it.
- An old server (404) or a network problem makes the helper fall back to waiting until its next report.
