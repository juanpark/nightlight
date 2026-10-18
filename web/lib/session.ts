"use client";
import { api } from "./api";
import { firebase } from "./firebase";

/** The chat session for this user and sample-home generation (a reset deletes old chats: new generation, new chat).
 * Shared by the chat and by things that report into it (playbook runs). The chat opens the account's most recently
 * used conversation, on whichever device it was used (so a phone continues what the laptop asked); this browser
 * remembers it, or "New chat" chosen here until some conversation is used after that. */
const NEW = "new:"; // "new:<ms>": New chat was chosen then; the next question starts one
const key = (uid: string, generation: number | undefined) => `nl_session_${uid}_${generation ?? 0}`;

/** The conversation this browser has open: an id, "new:<ms>" for a fresh chat, or null when it has never chosen. */
function stored(uid: string, generation: number | undefined): string | null {
  try { return localStorage.getItem(key(uid, generation)); } catch { return null; }
}
function store(uid: string, generation: number | undefined, sid: string) {
  try { localStorage.setItem(key(uid, generation), sid); } catch { /* private mode: this visit only */ }
}

export type Conversation = { id: string; title: string; usedAt: Date | null; empty: boolean };

/** The account's recent conversations in this generation, most recently used first. Older sessions have no updatedAt
 * (and an orderBy leaves out documents without its field), so the newest-started ones are merged in. */
export async function recentSessions(uid: string, generation: number | undefined): Promise<Conversation[]> {
  const { db } = await firebase();
  const { collection, getDocs, limit, orderBy, query } = await import("firebase/firestore");
  const col = collection(db, "users", uid, "sessions");
  const [used, started] = await Promise.all([getDocs(query(col, orderBy("updatedAt", "desc"), limit(40))),
    getDocs(query(col, orderBy("createdAt", "desc"), limit(40)))]);
  const seen = new Map<string, Conversation>();
  for (const d of [...used.docs, ...started.docs]) {
    const x = d.data();
    if (seen.has(d.id) || (x.demoGeneration ?? 0) !== (generation ?? 0)) continue;
    seen.set(d.id, { id: d.id, title: typeof x.title === "string" ? x.title : "New chat",
      usedAt: (x.updatedAt ?? x.createdAt)?.toDate?.() ?? null, empty: (x.nextSeq ?? 1) <= 1 });
  }
  return [...seen.values()].sort((a, b) => (b.usedAt?.getTime() ?? 0) - (a.usedAt?.getTime() ?? 0));
}

/** The conversation to show when the chat opens: the most recently used one that has messages, unless New chat was
 * chosen here after it was last used. */
export async function openSession(uid: string, generation: number | undefined): Promise<string | null> {
  const s = stored(uid, generation);
  const list = await recentSessions(uid, generation).catch(() => null);
  if (!list) return s && !s.startsWith(NEW) ? s : null; // couldn't look: stay with this browser's
  const recent = list.find((c) => !c.empty);
  if (!recent) return null; // no conversations yet
  if (s?.startsWith(NEW) && Number(s.slice(NEW.length)) > (recent.usedAt?.getTime() ?? 0)) return null;
  store(uid, generation, recent.id);
  return recent.id;
}

/** Switch this browser to another conversation. */
export function pickSession(uid: string, generation: number | undefined, sid: string) { store(uid, generation, sid); }

/** "New chat": the next question starts a new conversation. */
export function newChat(uid: string, generation: number | undefined) { store(uid, generation, NEW + Date.now()); }

/** The open conversation's id, creating one when there is none yet. */
export async function chatSession(uid: string, generation: number | undefined): Promise<string> {
  const s = stored(uid, generation);
  if (s && !s.startsWith(NEW)) return s;
  const r = await api<{ sessionId: string }>("POST", "/api/chat/sessions", {});
  store(uid, generation, r.sessionId);
  return r.sessionId;
}
