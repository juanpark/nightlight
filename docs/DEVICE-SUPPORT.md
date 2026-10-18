# Which devices Nightlight supports

Nightlight works through a small **helper** program that runs on your own computers. What it can do for a device
depends on whether the helper can run there. This page says exactly that, so you know what to expect today and what
comes next.

## Three levels of support

| Level | What Nightlight does | Devices today |
|---|---|---|
| **1. Looked after** (the helper runs on it) | sees disk, memory, apps and services, explains problems in plain words, and fixes them from a fixed list of jobs, each one only after your tap | **Linux** with systemd (Raspberry Pi OS, Ubuntu, Debian and most others) and **macOS** 10.15 or newer |
| **2. Watched** (seen from a computer that has the helper) | finds it on your network, names it when it announces a name, and checks that it still answers; no changes, ever | routers, NAS boxes, printers, TVs and speakers, cameras, game consoles, phones, **Windows PCs**, other computers |
| **3. Watched from the cloud** | checks that a website or online service answers | websites you add under Watches |

A level-2 device needs at least one level-1 computer on the same network: the helper on that computer does the
looking and the checking. Nothing is installed on the watched device, and Nightlight never logs in to it.

## What "watched" can and can't tell you

- **Can:** that it is on the network, its name and maker when it announces them, whether it still answers on the
  port you chose, and when it stopped answering.
- **Can't:** its disk, its apps, its firmware version, or anything inside it. Nightlight says so when you ask (for
  example "is my router's firmware up to date?") rather than guessing.

## Not supported yet, and the plan

| Device | Today | Plan |
|---|---|---|
| Windows PC | watched only (level 2) | a Windows helper (a Windows service instead of systemd or launchd) |
| NAS boxes (Synology, QNAP, Unraid, TrueNAS) | watched only; the helper is untested on their systems | a Docker package installed from the NAS's own app or container screen |
| Linux without systemd (Alpine, some minimal systems) | the helper won't install as a background service | support for other service managers |
| Linux desktop for beginners | needs the one-line command in Terminal | a `.deb` installer |
| Chromebook | not supported | low priority: it isn't a server, and its Linux is sandboxed |
| Phones and tablets | watched only | the app itself works in the phone's browser; a helper isn't planned |
| Routers, printers, cameras | watched only | deeper checks through what they publish (UPnP, SNMP), still without logging in |

The order follows what home servers most often run. Windows and NAS boxes come first after the contest.
[`LIMITS-AND-ROADMAP.md`](LIMITS-AND-ROADMAP.md) has the full roadmap.

## Python, in one line

The helper is written in Python. You never install Python yourself: the Mac installer brings its own copy, and on
Linux the one-line command uses the system's Python 3.8+ or brings its own copy when there is none.
