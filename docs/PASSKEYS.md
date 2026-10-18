# Passkeys in Nightlight: your face or fingerprint is the key to your machines

Almost everything in Nightlight works without a passkey: it watches your devices, explains problems, and fixes the
usual ones from a fixed list after you tap Approve. A passkey is only needed for **expert sessions**: the moments
Nightlight wants to run a real command on one of your machines, the way an IT expert would type it. This page says
what a passkey is, why we ask for one, and exactly how to set it up and use it. The security reasoning behind it is
in [`SECURITY-MODEL.md`](SECURITY-MODEL.md).

## What a passkey is

A passkey is a key pair that your phone or computer makes for one website. The **private half never leaves your
device**: it sits in the phone's secure chip (or your platform keychain) and is unlocked by your face, fingerprint or
PIN. The website keeps only the **public half**, which can check a signature but cannot make one. It is the same
technology as password-free sign-in on many sites (the standard is called WebAuthn, part of FIDO2).

Nightlight uses it in an unusual way. When you approve a risky action, your device **signs that exact action**: the
command text, which machine it is for, when the approval expires, and a one-time number. The Nightlight helper on your
machine holds a copy of your public key and **checks the signature itself** before it runs anything. The managed
machine has no passkey of its own, and Nightlight's cloud has only the public key, so:

- Nightlight's servers cannot run a command on your machine without you, even if they were hacked.
- A stolen Nightlight login cannot either: there is no email code or SMS fallback, on purpose.
- The approval is for one command (or one 15-minute read-only session) on one machine; it cannot be reused or
  stretched.

## When Nightlight asks for it

| What you ask for | What you do |
|---|---|
| "Is anything wrong?", status, explanations, history | nothing |
| Look into a stopped app, read-only checks it already has | nothing (allowed per device, no card) |
| Restart an allowed app or service, a clean-up from the fixed list, a helper update, remove a device | one tap on a card |
| **Investigate deeply** on a device with expert sessions: read-only commands (logs, disk use, running programs, network) | one Face ID / Touch ID / PIN, good for 15 minutes on that device |
| A one-off command that **changes** something, proposed by Nightlight | Face ID / Touch ID / PIN **per command**, each on its own card |

Nightlight never asks for a passkey to sign in; signing in is Google. The passkey is only for commands.

## Which devices can make a passkey

Any current phone or computer that can make passkeys should work, because Nightlight asks for the most common kind
(an elliptic-curve "ES256" key with your face, fingerprint or PIN required). Supported in principle:

| Where | How it feels |
|---|---|
| iPhone, iPad, Mac (Safari, Chrome, Edge, Firefox, up to date) | Face ID or Touch ID; the passkey syncs through iCloud Keychain |
| Android phones, including Samsung | fingerprint, face or PIN; Google Password Manager (or Samsung Pass) |
| Windows PC | Windows Hello (face, fingerprint or PIN) |
| A phone approving for your computer | the computer shows a QR code; you scan it with the phone and use its face or fingerprint |
| Password managers that store passkeys (1Password, Bitwarden, Dashlane, ...) | their own unlock prompt |
| Hardware security keys (YubiKey and the like) | touch the key and enter its PIN |

Honest notes. The code carries Safari-specific handling, so the flow was exercised on Apple devices during the
hackathon; the other rows follow from the standard and were not all tried by us *(unverified)*. Very old Windows Hello versions could only make RSA keys, which Nightlight
does not accept; the app then says "That passkey is a kind your devices can't check. Try another phone or computer."
A browser that cannot make passkeys shows "this browser can't create passkeys; use Safari, Chrome, Edge or Firefox
(up to date) on a phone or computer."

## Create your passkey (once per account)

1. Sign in with Google at Nightlight's own address (passkeys do not work on the demo or on preview links; the app
   tells you where to go if you are elsewhere).
2. Open a real device of yours on the map, then its **Settings** tab, then **Expert sessions**.
3. Tap **Create my passkey**. Your phone or computer asks for your face, fingerprint or PIN. (On Safari, tap once the
   button reads "Create my passkey", not "Getting ready…": Safari only opens the prompt right after a tap.)
4. The app shows your passkey's **code**, four groups of four characters like `3F2A-91C0-7E55-B0D4`. Keep this page
   open for the next step.

You make one passkey per Nightlight account and it covers all your devices. The app shows the code worked out in the
browser that made the passkey; another browser shows the server's copy and asks you to compare at the device.

## Switch it on for each machine (once per device)

The helper on each machine must be told to trust your passkey, and that happens **at the machine**, not from the
cloud, so nobody can switch it on for you. In a terminal on that machine (or over SSH):

```
nightlight expert
```

(If the shell says "command not found": `~/.local/bin/nightlight expert`.) The helper fetches your public key,
**works out the code itself** from the key's bytes, prints it, and asks whether the app shows exactly the same code.
Answer yes only if it matches; then "Expert sessions" shows **(on)** for that device in the app within seconds. This
works the same on strict and app-managed devices: the app's switches can never turn it on. A device you do not switch
on keeps working with the fixed checks and fixes; it simply never gets a command card.

## Use it

**Investigate.** Choose "Investigate deeply" under the chat (or ask Nightlight to dig in). On a device with expert
sessions it puts up a card: *"Let Nightlight look deeper into the Mac mini for 15 minutes, with commands that only
look."* Tap **Approve with passkey**, confirm with your face, fingerprint or PIN, and the card's result reads "Investigation
unlocked for the next 15 minutes." while the chat carries on. For the next 15 minutes Nightlight may run read-only commands on that device
without further taps; each one appears as "Run a check that only reads on the Mac mini: `df -h /`" with its result.
The device itself refuses anything that is not read-only: only a fixed list of programs with their reading
sub-commands, no pipes or chaining, file reads only under log folders, and nothing that looks like a secret.

**A one-off command.** When Nightlight thinks a change is needed that is not on the fixed menu, it puts up a card
with the exact command, what it does, what could go wrong, and a red risk badge. Read the command. Tap **Approve
with passkey**, confirm, and the device runs exactly that command, once, with a 60-second limit, and reports the
(scrubbed) output. A transcript of every expert command stays on the device (`expert-transcript.log` in the helper's
folder).

**What each prompt looks like.** Your phone or computer shows its usual passkey sheet ("Nightlight expert sessions"
and Nightlight's address); the app button reads "Waiting for your passkey…" while it is open. Cancelling the sheet
leaves the card untouched ("Cancelled or timed out. Tap again.").

## Without a passkey device

You lose nothing from the ordinary product: watching, explanations, checkups and fixed-menu fixes work the same, and
"Investigate deeply" falls back to the standard read-only checks on devices without expert sessions. If you want
expert sessions but your computer cannot make passkeys, approve from a phone (scan the QR code the computer shows, or
open Nightlight on the phone itself).

## Turn it off or start over

- **Turn expert sessions off on a device:** at that machine, `nightlight expert --off`. The device forgets the key at
  once and reports it; "Expert sessions" shows **(off)**.
- **You lost the phone with the passkey:** nobody can use it without your face, fingerprint or PIN, and it is useless
  without your Google login. Still: remove the passkey in your platform's passkey manager (iCloud Keychain, Google
  Password Manager, Windows Settings), and run `nightlight expert --off` at each device.
- **Remove or replace the passkey itself:** not possible from the app yet; this is a known gap (see
  [`LIMITS-AND-ROADMAP.md`](LIMITS-AND-ROADMAP.md)). Turning it off at each device is the switch today.

## Troubleshooting

| You see | What it means, what to do |
|---|---|
| "Passkeys work only at *host*" | you are on a preview, the demo, or another address; open Nightlight at the address shown |
| "Getting ready…" that never becomes "Create my passkey" / "Approve with passkey" | the app is fetching what the prompt needs; wait a second, or reload; on Safari, make sure you tap once the label changed |
| "Cancelled or timed out. Tap again." | you dismissed the sheet, or it waited more than 60 seconds |
| "This card expired. Ask again and Nightlight will put up a fresh one." | a card is signable for 15 minutes; ask again in the chat |
| "This card's signed device doesn't match the device it shows. Not signed." or "(signed for a different device!)" | the card is inconsistent; do not sign it, and tell us |
| "Make your passkey first: open a device, then Settings, then Expert sessions." | the account has no passkey yet |
| "That passkey didn't sign it. Use the passkey you made for Nightlight." | your device offered a different passkey, or the account's passkey was replaced |
| "This device already has a passkey for Nightlight. Use that one." | your phone or computer already holds one for this account |
| "the server shows a different key (…) than the passkey this browser made (…)" | do not switch it on anywhere; tell us |
| The device says "expert sessions aren't switched on at this device" | run `nightlight expert` there |
| The device says "the signature came from another site" / "is for another site" | the device was pinned from a different Nightlight address than the one you signed at; run `nightlight expert` again there |
| "Deeper checks (Expert sessions) are half set up" in Needs you | a device trusts a passkey the account no longer has; create it again, then re-run `nightlight expert` on the device |

## For the curious: what exactly gets signed

The card carries a small payload: the device id, the command (or `mode: read-only`), an expiry 15 minutes ahead, and a
random nonce. The browser computes SHA-256 of that payload itself, from what the card displays, and asks your passkey
to sign it. The helper re-computes the same hash, checks the device id, the expiry (at most 16 minutes), that the
nonce was not used before, that the signature came from Nightlight's own web address, that your face/fingerprint/PIN
was actually checked, and finally the signature against your public key. Only then does it run. Code:
`web/lib/passkey.ts`, `api/src/nightlight_api/expert.py`, `expert_check` and `readonly_command` in
`helper/nightlight_helper.py`.
