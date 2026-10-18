# Trust design: how much power Nightlight has over your devices, and why

**Short version.** Nightlight's cloud is a *messenger, not a master*. Today a device runs only a fixed, signed menu of
jobs, so even a fully breached Nightlight cloud can't take over your machines. Expert work (anything a sysadmin would
type) works the same way: commands the AI proposes run only after **your passkey** signs them on your own phone
or laptop. The power of a sysadmin, with the keys in your pocket, not ours.

## The central tension: safety vs. power and convenience

This is the hardest problem in Nightlight, and the one we spent the most effort on. The benchmark we hold ourselves
to is a person running an AI coding agent in a terminal on their own machine, with their own SSH keys and a folder of
notes about their servers: it can investigate anything, fix anything, and it is only as safe as the person watching.
Nightlight has to come close to that **for people who have never opened a terminal**, while being safe even if
Nightlight itself is breached. Every gain in power or convenience is a potential gain for an attacker, so each step
had to answer two questions at once: *does it make the agent more capable?* and *who could abuse it, and how do we
stop them without asking a lay user to be a security expert?*

| Step | Power / convenience gained | The risk it raised | How we closed it |
|---|---|---|---|
| Fixed job menu | restarts, checks, clean-ups from the app | a breached cloud could run jobs | job names, not commands; the device's own allowlist; cards for every change |
| Signed helper updates | no terminal to update, ever | a breached cloud could push code | release key kept offline; the device verifies the signature, refuses older versions |
| Playbooks | expert answers for common problems, the same every time | none new (no new abilities) | data only: checks and clean-ups that already exist |
| Automatic post-mortems | it finds out why a device crashed without being asked | it must not invent evidence | read-only checks; "unknown" when the history can't prove a crash |
| Investigate mode + research | a stronger model that digs in, and searches the web | cost; personal details leaking to a search engine | budgets per turn and per day; the home's names, addresses and secrets stripped first |
| Expert sessions | real commands in a loop, like an administrator | a breached cloud, prompt injection, replay, secret exfiltration | the owner's passkey signs; the device verifies; read-only enforced on the device by exact rules |

**Independent review is part of the design.** Each step was reviewed adversarially (by a separate AI reviewer working
from the code and the rules, with probes). The first version of expert sessions was sent back with five high-severity
findings: "read-only" was a list of names that `docker system prune` slipped through; the card showed one command
while signing an opaque challenge; the device trusted a fingerprint supplied by the cloud; replay protection forgot
old tokens. Each was fixed with a regression test, then reviewed again, until the reviewer couldn't break it. That
loop, more than any single feature, is how the gap between safe and capable keeps closing.

## The fork we faced

Juan's own setup (a folder of notes plus an AI in a terminal with his SSH keys) can fix almost anything. A product for
people who have never opened a terminal should come close to that. Three ways to get there:

| | A. Remote shell from the cloud | B. A fixed menu of skills (today) | C. Owner-signed expert sessions (shipped) |
|---|---|---|---|
| What the AI can do | anything | named jobs: checks, restarts, clean-ups, updates, removal | anything it proposes, once you sign it |
| Who holds the keys | our cloud | our cloud holds job names; the device holds the rules | **you** (a passkey on your phone/laptop); the device checks your signature |
| If our cloud is breached | every customer machine is open | the attacker can only ask for named jobs the owner switched on, behind cards | the attacker can't sign anything; nothing runs |
| If a log line tries to talk to the AI (prompt injection) | it can become a real command | it can at most trigger a named job, still behind a card | it can propose a command; your signature is still needed |
| Who does this today | IT remote-management tools (RMM: NinjaOne, ConnectWise, Kaseya) | monitoring tools (Datadog, Netdata, Uptime Kuma) | identity-gated access (Tailscale SSH "check mode", Teleport, AWS Session Manager) |

The cautionary tale for A: in 2021 attackers used Kaseya VSA, an RMM product, to push ransomware to about 1,500
businesses at once, through exactly this kind of central "run anything" channel.

## Why B first, and why it is not a dead end

- **Bounded by construction.** The cloud sends job *names*; the helper maps them to fixed argument lists and checks
  them against what the device's owner allowed. New skills arrive only as helper releases signed with an offline key
  (`docs/SECURITY.md`), so an attacker can't add a skill either.
- **Each skill is enumerable.** We can write down the worst case of every job (restart this service, empty that
  cache). That list is the security review.
- **Playbooks make it smart without making it powerful.** An expert's steps for a known problem run the same way every
  time, without the AI (`playbooks.yaml`); the AI explains and investigates within the same read-only checks.
- **The ceiling is real.** A fixed menu can't fix what nobody foresaw. That's what C is for.

## C: owner-signed expert sessions

1. The owner registers a **passkey** for expert sessions (WebAuthn, the same Face ID / Touch ID / phone prompt as a
   password-free login). On each device where the owner turns expert sessions on (`nightlight expert`, at the device), the helper fetches that public key after the owner compares its fingerprint, and stores it.
2. In an expert session, Gemini investigates with the read-only checks and **proposes commands**, each with what it
   does and what could go wrong.
3. The owner approves a command (or a short, time-boxed read-only bundle) with the passkey. The browser signs the exact
   command text, the device id and an expiry. The cloud relays the signed request; it cannot create or change one.
4. The helper verifies the signature against the stored public key (the same `openssl` check it already uses for
   signed updates), checks the device id and expiry, runs the command with a timeout, and keeps a transcript on the
   device. Anything unsigned, expired, or for another device is refused.

What this protects against: a breached cloud (can't sign), a stolen Nightlight session cookie (no passkey), prompt
injection (a human signs every command). What it doesn't: an owner approving a harmful command they didn't read; the
card shows the AI's explanation and a risk level to help, and read-only bundles are the default.

## The trust ladder: freedom earned one kind of job at a time (sample home)

Cards answer "may it do this, now?". The ladder answers "may it do this kind of job without asking next time?". Each
kind of job has a level: **Always ask me**, **Ask me for new things**, **Just handle it and tell me**. After three
approved successes of the same safe (routine) kind, such as a log clean-up, Nightlight offers to stop asking for it;
the owner accepts or declines, and the Trust panel can move any kind back down. A failure moves a kind back a step on
its own. Restarts and updates always ask, however often they went well (`trust.py`).

It runs on the sample home only. On real devices every change still waits for a tap, because the fixed menu needs more
hours behind it before we let it act alone there. That is the next step this design is built for, not a missing piece.

## How we got here

1. Read-only monitoring and explanations (sample home).
2. A fixed job menu on real devices, every change behind a card; strict vs app-managed devices.
3. Signed helper updates from the app (offline release key).
4. Playbooks: known problems handled the same way every time, without the AI.
5. Owner-signed expert sessions: shipped and tested (see [`PASSKEYS.md`](PASSKEYS.md) and [`SECURITY-MODEL.md`](SECURITY-MODEL.md)).

## Roadmap items that follow from this

- Expert sessions: a "read-only" classifier for bundles (per-command signing, the 15-minute read-only grant and the
  on-device audit log of signed commands have shipped).
- Release signing in a hardware security module or a CI pipeline outside the cloud that talks to devices.
- Installers so the first install needs no terminal line: the Mac `.pkg` has shipped (unsigned until Developer ID
  certificates arrive); a Raspberry Pi image and a Linux `.deb` are next.
- Retention you choose per account (7 / 30 / 90 / 365 days) and cold archives in Cloud Storage.
- Account deletion that purges everything at once.
