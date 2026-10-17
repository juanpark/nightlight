// Public runtime configuration for the browser. Values come from the server's environment at deploy time, so no
// keys live in the repository. (The Firebase web config is public by design; it identifies the project.)
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({
    apiUrl: process.env.API_URL ?? "http://localhost:8080",
    // where Nightlight lives: passkeys belong to this address and work nowhere else (previews, other hosts)
    appUrl: process.env.APP_URL ?? "https://nightlight-web-1032111130355.asia-northeast3.run.app",
    firebase: {
      apiKey: process.env.FIREBASE_API_KEY ?? "",
      authDomain: process.env.FIREBASE_AUTH_DOMAIN ?? "",
      projectId: process.env.FIREBASE_PROJECT_ID ?? "",
      appId: process.env.FIREBASE_APP_ID ?? "",
    },
  });
}
