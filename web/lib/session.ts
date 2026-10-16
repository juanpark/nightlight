"use client";
import { api } from "./api";

/** The chat session for this user and sample-home generation (a reset deletes old chats: new generation, new chat).
 * Shared by the chat and by things that report into it (playbook runs). */
export async function chatSession(uid: string, generation: number | undefined): Promise<string> {
  const key = `nl_session_${uid}_${generation ?? 0}`;
  let sid = null;
  try { sid = localStorage.getItem(key); } catch { /* private mode */ }
  if (sid) return sid;
  const r = await api<{ sessionId: string }>("POST", "/api/chat/sessions", {});
  try { localStorage.setItem(key, r.sessionId); } catch { /* private mode */ }
  return r.sessionId;
}
