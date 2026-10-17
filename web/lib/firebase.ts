"use client";
// Firebase is configured at runtime from /config, so the same build runs locally and on Cloud Run.
import { initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";
import { getFirestore, type Firestore } from "firebase/firestore";

export interface RuntimeConfig {
  apiUrl: string;
  appUrl?: string;
  firebase: { apiKey: string; authDomain: string; projectId: string; appId: string };
}

let cached: Promise<{ config: RuntimeConfig; app: FirebaseApp; auth: Auth; db: Firestore }> | null = null;

export function firebase() {
  cached ??= fetch("/config", { cache: "no-store" })
    .then((r) => r.json() as Promise<RuntimeConfig>)
    .then((config) => {
      const app = initializeApp(config.firebase);
      return { config, app, auth: getAuth(app), db: getFirestore(app) };
    });
  return cached;
}
