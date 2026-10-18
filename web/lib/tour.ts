// The first-run tour: short pointers to the parts of the screen, in the order a newcomer needs them. Each step points
// at an element marked `data-tour="<anchor>"` (never a class or a position, so a redesign that keeps the attribute
// keeps the tour); when that element is missing or hidden, the step shows in the middle of the screen instead.
// Three tours: the first visit, the first real device, the first approval card. Each is seen once per account in
// this browser; Settings can turn them on again.

export type TourState = { anonymous: boolean; realDevices: number; hasCard: boolean };
export type TourStep = { id: string; anchor?: string; title: string; text: string; when?: (s: TourState) => boolean };
export type TourId = "intro" | "firstDevice" | "firstCard";

export const TOURS: Record<TourId, TourStep[]> = {
  intro: [
    { id: "welcome", title: "Welcome to Nightlight",
      text: "Nightlight keeps an eye on the computers and gadgets at home, tells you in plain words when something needs you, and asks before it changes anything." },
    { id: "needs", anchor: "needs", title: "What needs you",
      text: "Anything that wants your attention shows up here first. When nothing is listed, all is well." },
    { id: "map", anchor: "map", title: "Your home",
      text: "Every device and what runs on it. Tap one to see how it is doing. Status shows every check as a simple list." },
    { id: "try-own", anchor: "try-own", title: "These devices are pretend", when: (s) => s.anonymous,
      text: "This sample home is simulated so you can try things safely. Your own computer takes about two minutes to add." },
    { id: "add", anchor: "add-device", title: "Add your first device", when: (s) => !s.anonymous && s.realDevices === 0,
      text: "Install a small helper program on a computer or Raspberry Pi: one line to paste, about a minute. It only reports; it changes nothing on its own." },
    { id: "chat", anchor: "chat", title: "Ask Nightlight",
      text: "Ask anything about your home, like \"Is anything wrong?\" It looks at your devices before it answers." },
    { id: "card", anchor: "card", title: "It always asks first",
      text: "When something needs fixing, Nightlight shows a card that says what it will do and waits. Nothing changes until you tap Approve." },
    { id: "trust", anchor: "more", title: "Trust, earned slowly",
      text: "After you approve the same kind of safe fix a few times, Nightlight may offer to do it on its own. See it under More → Trust. For now this works on the sample home; your own devices always ask." },
    { id: "settings", anchor: "more", title: "See this again",
      text: "This tour can be turned back on any time in Settings, under More." },
  ],
  firstDevice: [
    { id: "device", anchor: "map", title: "Your device is here",
      text: "Its disk, memory and apps appear within a minute. Tap it to see more, or to choose what Nightlight may do there." },
    { id: "found", anchor: "found-nearby", title: "Found nearby",
      text: "Your device also spots the printers, TVs and phones on your network, named the way they announce themselves." },
    { id: "ask", anchor: "chat", title: "Ask about it",
      text: "Try \"How is my computer doing?\"" },
  ],
  firstCard: [
    { id: "card", anchor: "card", title: "Nightlight is asking",
      text: "This card says exactly what it wants to do and how to undo it. Approve, or Not now: nothing happens without you." },
  ],
};

const key = (uid: string, t: TourId) => `nl_tour_${t}_${uid}`;
export function seen(uid: string, t: TourId): boolean { try { return localStorage.getItem(key(uid, t)) === "1"; } catch { return false; } }
export function markSeen(uid: string, t: TourId) { try { localStorage.setItem(key(uid, t), "1"); } catch { /* this visit only */ } }
function forget(uid: string) { for (const t of Object.keys(TOURS) as TourId[]) { try { localStorage.removeItem(key(uid, t)); } catch { /* fine */ } } }

/** Settings' "Show the tour again": forgets what was seen and starts the first tour now. */
export function restartTour(uid: string) { forget(uid); window.dispatchEvent(new Event("nl-tour")); }
