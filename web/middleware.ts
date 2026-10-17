// Nightlight has one address. Cloud Run also answers on a second, older-style hostname for the same service; anything
// opened there (an old link, a bookmark) moves to the app's own address, where passkeys and sign-in work. Tagged
// previews ("name---service…") keep their own hostnames.
import { NextResponse, type NextRequest } from "next/server";

const APP_URL = process.env.APP_URL ?? "https://nightlight-web-1032111130355.asia-northeast3.run.app";
const OTHER_HOSTS = new Set(["nightlight-web-5bum5nvvpq-du.a.run.app"]);

export function middleware(req: NextRequest) {
  const host = (req.headers.get("host") ?? "").toLowerCase().split(":")[0];
  if (!OTHER_HOSTS.has(host)) return NextResponse.next();
  const to = new URL(req.nextUrl.pathname + req.nextUrl.search, APP_URL);
  return NextResponse.redirect(to, 308); // 308 keeps the method and body (a POST stays a POST)
}

export const config = { matcher: "/:path*" };
