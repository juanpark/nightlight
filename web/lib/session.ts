"use client";
import { api } from "./api";

/** The chat session for this user and sample-home generation (a reset deletes old chats: new generation, new chat).
 * Shared by the chat and by things that report into it (playbook runs). */
/** The saved chat session for this user and generation, without creating one. */
export function savedSession(uid: string, generation: number | undefined): string | null {
  try { return localStorage.getItem(`nl_session_${uid}_${generation ?? 0}`); } catch { return null; }
}

/** Forget the saved session: the next question starts a new chat. */
export function newChat(uid: string, generation: number | undefined) {
  try { localStorage.removeItem(`nl_session_${uid}_${generation ?? 0}`); } catch { /* private mode */ }
}

export async function chatSession(uid: string, generation: number | undefined): Promise<string> {
  const key = `nl_session_${uid}_${generation ?? 0}`;
  let sid = null;
  try { sid = localStorage.getItem(key); } catch { /* private mode */ }
  if (sid) return sid;
  const r = await api<{ sessionId: string }>("POST", "/api/chat/sessions", {});
  try { localStorage.setItem(key, r.sessionId); } catch { /* private mode */ }
  return r.sessionId;
}
