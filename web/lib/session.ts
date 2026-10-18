"use client";
import { api } from "./api";
import { firebase } from "./firebase";

/** The chat session for this user and sample-home generation (a reset deletes old chats: new generation, new chat).
 * Shared by the chat and by things that report into it (playbook runs). This browser remembers which conversation is
 * open; a browser that has none opens the account's most recent one (so a phone shows what the laptop asked). */
const NEW = "new"; // "New chat" was chosen: the next question starts one, even though older ones exist
const key = (uid: string, generation: number | undefined) => `nl_session_${uid}_${generation ?? 0}`;

/** The conversation this browser has open: an id, "new" for a fresh chat, or null when it has never chosen. */
function stored(uid: string, generation: number | undefined): string | null {
  try { return localStorage.getItem(key(uid, generation)); } catch { return null; }
}
function store(uid: string, generation: number | undefined, sid: string) {
  try { localStorage.setItem(key(uid, generation), sid); } catch { /* private mode: this visit only */ }
}

export type Conversation = { id: string; title: string; createdAt: Date | null; empty: boolean };

/** The account's recent conversations in this generation, newest first. */
export async function recentSessions(uid: string, generation: number | undefined): Promise<Conversation[]> {
  const { db } = await firebase();
  const { collection, getDocs, limit, orderBy, query } = await import("firebase/firestore");
  const snap = await getDocs(query(collection(db, "users", uid, "sessions"), orderBy("createdAt", "desc"), limit(40)));
  return snap.docs.map((d) => ({ d: d.data(), id: d.id }))
    .filter(({ d }) => (d.demoGeneration ?? 0) === (generation ?? 0))
    .map(({ d, id }) => ({ id, title: typeof d.title === "string" ? d.title : "New chat",
      createdAt: d.createdAt?.toDate?.() ?? null, empty: (d.nextSeq ?? 1) <= 1 }));
}

/** The conversation to show when the chat opens: this browser's choice, else the newest one that has messages. */
export async function openSession(uid: string, generation: number | undefined): Promise<string | null> {
  const s = stored(uid, generation);
  if (s) return s === NEW ? null : s;
  const recent = (await recentSessions(uid, generation).catch(() => [])).find((c) => !c.empty);
  if (recent) store(uid, generation, recent.id);
  return recent?.id ?? null;
}

/** Switch this browser to another conversation. */
export function pickSession(uid: string, generation: number | undefined, sid: string) { store(uid, generation, sid); }

/** "New chat": the next question starts a new conversation. */
export function newChat(uid: string, generation: number | undefined) { store(uid, generation, NEW); }

/** The open conversation's id, creating one when there is none yet. */
export async function chatSession(uid: string, generation: number | undefined): Promise<string> {
  const s = stored(uid, generation);
  if (s && s !== NEW) return s;
  const r = await api<{ sessionId: string }>("POST", "/api/chat/sessions", {});
  store(uid, generation, r.sessionId);
  return r.sessionId;
}
