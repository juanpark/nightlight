// Records the sample-home shots of the demo video (private/plan/video-script-2026-10-18.md, S-rows) and README
// stills from the live Nightlight app. Anonymous sample home only: every shot starts a fresh "Try the demo" session,
// so it is always clean and never needs a Reset. It never signs in. Video comes from Chrome's screencast (sharp
// text) encoded with ffmpeg; Playwright drives the system Chrome. Real-device shots (R-rows) are recorded by hand.
//
//   cd scripts/capture && npm ci && node capture.mjs [shot ...]      (default: every shot below)
//   APP_URL=…   another deployment (a preview)        TAKES=3   record each shot that many times
//   THEMES=light,dark   themes for the video shots (default dark; the README stills are always both)
//
// Account mode (Juan's real signed-in home, video v3: private/plan/video-script-2026-10-18-v3.md). Google blocks
// sign-in in a browser started by automation, so Chrome is started as a plain process and the kit attaches to it:
//   node capture.mjs --open-account             starts Chrome (profile private/video/chrome-profile, debug port 9333)
//                                               at the app; Juan signs in with Google himself, once. The kit never
//                                               types credentials.
//   node capture.mjs --account [shot ...] [--dry]   records acct-<shot>.mp4 in that window (default: every account
//                                               shot). Keep the window in front and unobscured while it records.
//                                               When a person is needed it beeps and prints "▶ JUAN: …", then waits.
//   --dry   rehearsal: types questions but never sends them, and cues don't wait
//   ACCT_PROFILE=…  ACCT_PORT=…   another profile folder / port (tests)   ACCT_VIEWPORT=1920x1080   force the page size
//
// Output (gitignored): private/video/raw/<date>/<shot>[-<take>].mp4 with .png (last frame) and .marks.json (seconds
// from the start of the clip at each step, for placing zooms); stills in private/captures/readme/ and
// private/video/raw/<date>/F*.png.
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const APP = process.env.APP_URL ?? "https://nightlight-web-1032111130355.asia-northeast3.run.app";
const PRIVATE = path.resolve(import.meta.dirname, "../../private");
const RAW = path.join(PRIVATE, "video/raw", new Date().toISOString().slice(0, 10));
const README = path.join(PRIVATE, "captures/readme");
const THEMES = (process.env.THEMES ?? "dark").split(",");
const TAKES = Number(process.env.TAKES ?? 1);
const SIZES = {
  D: { viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 },
  P: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true },
  still: { viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 },
  readme: { viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 },
};
const AGENT_WAIT = 120_000; // the first Gemini call can take a while: wait for the state, never a fixed sleep
const TYPE_MS = 55;

const beat = (ms) => new Promise((r) => setTimeout(r, ms));
const touch = new WeakSet(); // contexts that tap instead of click
let current = null; // the page of the shot being recorded, for a screenshot when it fails

/** A soft dot that follows the mouse and dips on press (desktop), or shows where a finger lands (phone). */
function pointer() {
  const css = `#cap-dot{position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;
    background:rgba(120,128,150,.35);border:2px solid rgba(255,255,255,.9);box-shadow:0 1px 6px rgba(0,0,0,.35);
    pointer-events:none;z-index:2147483647;transition:transform .15s;opacity:0}
    #cap-dot.on{opacity:1}#cap-dot.down{transform:scale(.7)}`;
  const go = () => {
    if (document.getElementById("cap-dot")) return;
    const s = document.createElement("style"); s.textContent = css; document.head.append(s);
    const d = document.createElement("div"); d.id = "cap-dot"; document.body.append(d);
    const at = (x, y) => { d.style.left = `${x}px`; d.style.top = `${y}px`; d.classList.add("on"); };
    addEventListener("mousemove", (e) => at(e.clientX, e.clientY), true);
    addEventListener("mousedown", () => d.classList.add("down"), true);
    addEventListener("mouseup", () => d.classList.remove("down"), true);
    addEventListener("touchstart", (e) => { const t = e.touches[0]; at(t.clientX, t.clientY); d.classList.add("down"); }, true);
    addEventListener("touchend", () => { d.classList.remove("down"); setTimeout(() => d.classList.remove("on"), 600); }, true);
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", go); else go();
}

/** Starts recording the page. `mark(name)` notes a step; `stop()` writes the mp4, its last frame and the marks. */
async function record(page, name) {
  const cdp = await page.context().newCDPSession(page);
  // a page Chrome opened itself (account mode) has no emulated viewport: use its window's
  const vp = page.viewportSize() ?? await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
  const dpr = await page.evaluate(() => devicePixelRatio);
  // frames go to disk as they come (a long Retina take would not fit in memory); only their times are kept
  const frames = [], marks = [], writes = [];
  const dir = path.join(RAW, `.frames-${name}`);
  await rm(dir, { recursive: true, force: true });
  await mkdir(dir, { recursive: true });
  cdp.on("Page.screencastFrame", (f) => {
    const file = `f${String(frames.length).padStart(5, "0")}.jpg`;
    frames.push({ file, t: f.metadata.timestamp });
    writes.push(writeFile(path.join(dir, file), Buffer.from(f.data, "base64")));
    cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
  });
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92,
    maxWidth: Math.round(vp.width * dpr), maxHeight: Math.round(vp.height * dpr) });
  const t0 = Date.now() / 1000;
  const mark = (step) => marks.push({ step, at: +(Date.now() / 1000 - t0).toFixed(2) });
  const stop = async () => {
    await beat(300);
    const end = Date.now() / 1000; // a still screen sends no frames: the last one is held until here
    await cdp.send("Page.stopScreencast").catch(() => {});
    await cdp.detach().catch(() => {});
    await Promise.all(writes);
    if (frames.length < 2) throw new Error("no frames recorded");
    const list = ["ffconcat version 1.0"];
    for (const [i, f] of frames.entries()) {
      const file = f.file;
      const next = frames[i + 1]?.t ?? Math.max(end, f.t) + 0.5; // hold the last frame to the stop, then a moment
      list.push(`file '${file}'`, `duration ${Math.max(0.001, next - f.t).toFixed(3)}`);
    }
    list.push(`file 'f${String(frames.length - 1).padStart(5, "0")}.jpg'`);
    await writeFile(path.join(dir, "list.txt"), list.join("\n"));
    await ffmpeg(["-y", "-f", "concat", "-safe", "0", "-i", path.join(dir, "list.txt"),
      "-vf", "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-crf", "16", "-preset", "slow",
      "-pix_fmt", "yuv420p", "-movflags", "+faststart", path.join(RAW, `${name}.mp4`)]);
    await rm(dir, { recursive: true });
    await page.screenshot({ path: path.join(RAW, `${name}.png`) });
    // the clip starts at the first frame, which can trail the recording start slightly
    const lag = Math.max(0, frames[0].t - t0);
    await writeFile(path.join(RAW, `${name}.marks.json`),
      JSON.stringify(marks.map((m) => ({ ...m, at: +Math.max(0, m.at - lag).toFixed(2) })), null, 1));
  };
  /** Ends a failed take: stops the screencast and drops its frames. */
  const abort = async () => {
    await cdp.send("Page.stopScreencast").catch(() => {});
    await cdp.detach().catch(() => {});
    await Promise.all(writes).catch(() => {});
    await rm(dir, { recursive: true, force: true });
  };
  return { mark, stop, abort };
}

function ffmpeg(args) {
  return new Promise((ok, fail) => {
    const p = spawn("ffmpeg", ["-loglevel", "error", ...args], { stdio: "inherit" });
    p.on("exit", (c) => (c === 0 ? ok() : fail(new Error(`ffmpeg exited ${c}`))));
  });
}

/** Glides the pointer to an element and clicks it (desktop) or taps it (phone), with a pause after. */
async function press(page, target, { pause = 600 } = {}) {
  await target.scrollIntoViewIfNeeded();
  const b = await target.boundingBox();
  if (!b) throw new Error("nothing to press");
  const x = b.x + b.width / 2, y = b.y + b.height / 2;
  if (touch.has(page.context())) await page.touchscreen.tap(x, y);
  else { await page.mouse.move(x, y, { steps: 30 }); await beat(250); await page.mouse.click(x, y); }
  await beat(pause);
}

/** Drags between two points slowly enough to follow on video. */
async function drag(page, from, to) {
  await page.mouse.move(from.x, from.y, { steps: 25 });
  await beat(300);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps: 45 });
  await beat(250);
  await page.mouse.up();
}
const centre = (b) => ({ x: b.x + b.width / 2, y: b.y + b.height / 2 });

/** A fresh anonymous sample home on the map. Records from the landing when `fromLanding`, else from the map. */
async function session(browser, size, theme, name, { fromLanding = false } = {}) {
  const ctx = await browser.newContext({ ...SIZES[size], colorScheme: theme });
  if (SIZES[size].hasTouch) touch.add(ctx);
  await ctx.addInitScript(pointer);
  const page = await ctx.newPage();
  current = page;
  await page.goto(APP);
  const demo = page.getByRole("button", { name: /Try the demo|Take the tour/ });
  await demo.waitFor({ timeout: 30_000 });
  let rec = null;
  if (fromLanding) { rec = await record(page, name); await beat(3000); rec.mark("landing"); await press(page, demo); }
  else await demo.click();
  await page.locator(".dnode").first().waitFor({ timeout: 60_000 });
  await beat(fromLanding ? 3500 : 1500); // the fit animation settles
  if (rec) rec.mark("map");
  else if (name) { rec = await record(page, name); rec.mark("map"); }
  return { ctx, page, ...rec };
}

const chat = (page) => page.locator("aside.right");
const node = (page, name) => page.locator(".react-flow__node").filter({ hasText: name });

/** Waits until the chat has finished answering (the Stop button comes and goes). */
async function answered(page) {
  const stopBtn = page.locator("form.chat-input button", { hasText: "Stop" });
  await stopBtn.waitFor({ state: "visible", timeout: 15_000 }).catch(() => {});
  await stopBtn.waitFor({ state: "hidden", timeout: AGENT_WAIT });
}

/** Types a question into the chat at a readable pace and sends it. */
async function ask(page, text) {
  const input = page.locator("form.chat-input input");
  await press(page, input, { pause: 300 });
  await input.pressSequentially(text, { delay: TYPE_MS });
  await beat(500);
  await page.keyboard.press("Enter");
}

/** Approves the newest card once its answer has finished, then waits for "Done" and the agent's follow-up. */
async function approve(page, mark) {
  await answered(page);
  const card = chat(page).locator(".card").last();
  const replies = await chat(page).locator(".bubble.agent").count();
  const yes = card.locator("button", { hasText: "Approve" });
  await yes.waitFor({ timeout: 30_000 });
  await press(page, yes, { pause: 300 });
  mark?.("approve");
  await card.locator("dd", { hasText: /^Done/ }).waitFor({ timeout: AGENT_WAIT });
  mark?.("done");
  await chat(page).locator(".bubble.agent").nth(replies).waitFor({ timeout: AGENT_WAIT }).catch(() => {});
  await answered(page).catch(() => {});
  mark?.("follow-up");
}

/** A Demo tools incident, from the menu like a person would (the panel closes again after). */
async function inject(page, label) {
  const tools = page.getByRole("button", { name: "Demo tools", exact: true });
  await press(page, tools, { pause: 800 });
  await press(page, page.getByRole("button", { name: label }), { pause: 1500 });
  await press(page, tools, { pause: 600 });
}

const SHOTS = {
  // S2: landing → Try the demo → the map settles → List → back to Map
  async S2(browser, theme, name) {
    const { ctx, page, mark, stop } = await session(browser, "D", theme, name, { fromLanding: true });
    await beat(3000);
    await press(page, page.getByRole("radio", { name: "List" }), { pause: 2500 }); mark("list");
    await press(page, page.getByRole("radio", { name: "Map" }), { pause: 2500 }); mark("map-again");
    await stop(); await ctx.close();
  },
  // S2p: the same on a phone, then the Home and Chat tabs
  async S2p(browser, theme, name) {
    const { ctx, page, mark, stop } = await session(browser, "P", theme, name, { fromLanding: true });
    await page.locator(".homemap").scrollIntoViewIfNeeded(); await beat(2500); mark("phone-map");
    await press(page, page.locator(".pane-tabs button", { hasText: "Chat" }), { pause: 2500 }); mark("chat-tab");
    await press(page, page.locator(".pane-tabs button", { hasText: "Home" }), { pause: 2000 }); mark("home-tab");
    await stop(); await ctx.close();
  },
  // S3: type the question → steps → answer → card → Approve → Done → follow-up
  async S3(browser, theme, name) {
    const { ctx, page, mark, stop } = await session(browser, "D", theme, name);
    await beat(1500);
    await ask(page, "Is anything wrong with my servers?"); mark("asked");
    await chat(page).locator("button", { hasText: "Not now" }).last().waitFor({ timeout: AGENT_WAIT }); mark("card");
    await answered(page); mark("answered");
    const log = chat(page).locator(".wl-head").last();
    if (await log.count()) { await press(page, log, { pause: 2500 }); mark("work-log"); }
    await beat(3000);
    await approve(page, mark);
    await beat(4000);
    await stop(); await ctx.close();
  },
  // S3p: the same card on the phone, tap Approve, the result
  async S3p(browser, theme, name) {
    const { ctx, page, mark, stop } = await session(browser, "P", theme, name);
    await press(page, page.locator(".pane-tabs button", { hasText: "Chat" }), { pause: 1200 }); mark("chat-tab");
    await ask(page, "Is anything wrong with my servers?"); mark("asked");
    await chat(page).locator("button", { hasText: "Not now" }).last().waitFor({ timeout: AGENT_WAIT }); mark("card");
    await answered(page);
    await chat(page).locator(".card").last().scrollIntoViewIfNeeded(); await beat(2500);
    await approve(page, mark);
    await beat(3500);
    await stop(); await ctx.close();
  },
  // S4a: the Trust panel
  async S4a(browser, theme, name) {
    const { ctx, page, mark, stop } = await session(browser, "D", theme, name);
    await beat(1000);
    await press(page, page.getByRole("button", { name: "Trust", exact: true }), { pause: 6000 }); mark("trust");
    await stop(); await ctx.close();
  },
  // S4b: three approved clean-ups → the offer → "Yes, handle it" → the disk fills again and it handles it alone
  async S4b(browser, theme, name) {
    const { ctx, page, mark, stop } = await session(browser, "D", theme, name);
    for (let round = 1; round <= 3; round++) {
      if (round > 1) { await inject(page, "Disk fills up"); mark(`inject-${round}`); }
      await ask(page, round === 1 ? "Is anything wrong with my servers?" : "The Pi's disk is full again. Can you clean it up?");
      await approve(page, (s) => mark(`${s}-${round}`));
      await beat(1500);
    }
    const offer = page.locator(".needs-strip button", { hasText: "Yes, handle it" });
    await offer.waitFor({ timeout: 30_000 }); mark("offer"); await beat(3000);
    await press(page, offer, { pause: 2500 }); mark("accepted");
    await inject(page, "Disk fills up"); mark("inject-4");
    await ask(page, "The Pi's disk is full again. Can you clean it up?");
    await answered(page); mark("handled");
    await beat(4000);
    await stop(); await ctx.close();
  },
  // S4c: the Minecraft lag → the "Some risk" restart card; stop there, never approve
  async S4c(browser, theme, name) {
    const { ctx, page, mark, stop } = await session(browser, "D", theme, name);
    await inject(page, "Minecraft gets laggy"); mark("inject");
    await ask(page, "My kids say Minecraft is laggy tonight. Can you help?"); mark("asked");
    const card = chat(page).locator(".card").last();
    await card.locator("button", { hasText: "Not now" }).waitFor({ timeout: AGENT_WAIT }); mark("card");
    await answered(page);
    await card.scrollIntoViewIfNeeded(); await beat(5000);
    await stop(); await ctx.close();
  },
  // M1 (extra): open a device's panel, drag a device, draw a backup line
  async M1(browser, theme, name) {
    const { ctx, page, mark, stop } = await session(browser, "D", theme, name);
    await beat(1500);
    await press(page, node(page, "Raspberry Pi"), { pause: 3500 }); mark("panel");
    await press(page, page.locator(".drawer button", { hasText: "Close" }), { pause: 600 });
    await page.locator(".homemap").scrollIntoViewIfNeeded(); await beat(1200);
    const cam = await node(page, "Camera recorder").boundingBox();
    await drag(page, { x: cam.x + cam.width / 2, y: cam.y + 14 }, { x: cam.x + cam.width / 2 + 160, y: cam.y + 54 });
    mark("dragged"); await beat(2000);
    const mac = centre(await node(page, "Mac Mini").boundingBox());
    await page.mouse.move(mac.x, mac.y, { steps: 20 }); await beat(600); // hovering shows the dots to draw from
    await drag(page, centre(await node(page, "Mac Mini").locator(".react-flow__handle-bottom").boundingBox()),
      centre(await node(page, "NAS").boundingBox()));
    const kind = page.locator(".hm-linkbar button", { hasText: "Backup" });
    await kind.waitFor({ timeout: 15_000 }); mark("line"); await beat(1200);
    await press(page, kind, { pause: 2500 }); mark("backup");
    const pane = await page.locator(".homemap .react-flow__pane").boundingBox();
    await page.mouse.move(pane.x + 40, pane.y + pane.height - 40, { steps: 20 });
    await page.mouse.click(pane.x + 40, pane.y + pane.height - 40);
    await beat(2500);
    await stop(); await ctx.close();
  },
};

const STILLS = {
  // F1–F3: zoom targets at 2× (the approval card, the Trust panel, a device panel); F4 (Investigate) is a real device
  async F(browser, theme) {
    const { ctx, page } = await session(browser, "still", theme, null);
    await page.mouse.move(0, 0);
    await page.getByRole("button", { name: "Trust", exact: true }).click(); await beat(1200);
    await page.locator(".panel", { hasText: "freedom" }).first().screenshot({ path: path.join(RAW, `F2-trust-${theme}.png`) });
    await page.getByRole("button", { name: "Trust", exact: true }).click();
    await node(page, "Raspberry Pi").click(); await beat(1500);
    await page.locator(".drawer").screenshot({ path: path.join(RAW, `F3-drawer-${theme}.png`) });
    await page.locator(".chat-starter", { hasText: "Is anything wrong with my servers?" }).click();
    const card = chat(page).locator(".card").last();
    await card.locator("button", { hasText: "Not now" }).waitFor({ timeout: AGENT_WAIT });
    await answered(page); await beat(800);
    await card.screenshot({ path: path.join(RAW, `F1-card-${theme}.png`) });
    await ctx.close();
  },
  // README: the map, and the chat with an approval card, 1600 wide
  async readme(browser, theme) {
    const { ctx, page } = await session(browser, "readme", theme, null);
    await page.mouse.move(0, 0);
    await page.screenshot({ path: path.join(README, `map-${theme}.png`) });
    await page.locator(".chat-starter", { hasText: "Is anything wrong with my servers?" }).click();
    await chat(page).locator("button", { hasText: "Not now" }).last().waitFor({ timeout: AGENT_WAIT });
    await answered(page); await beat(800);
    await page.screenshot({ path: path.join(README, `chat-${theme}.png`) });
    await ctx.close();
  },
};

// ---------------------------------------------------------------------------------------------------------------
// Account mode: Juan's real home in a Chrome he signed in to himself. Labels on screen only (the UI is being restyled).

const ACCT_PROFILE = path.resolve(process.env.ACCT_PROFILE ?? path.join(PRIVATE, "video/chrome-profile"));
const ACCT_PORT = Number(process.env.ACCT_PORT ?? 9333);
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const flags = new Set(process.argv.slice(2).filter((a) => a.startsWith("--")));
const DRY = flags.has("--dry");

/** Starts the real Chrome as an ordinary process (no automation flags), so Google lets Juan sign in. */
async function openAccount() {
  await mkdir(ACCT_PROFILE, { recursive: true });
  const p = spawn(CHROME, [`--user-data-dir=${ACCT_PROFILE}`, `--remote-debugging-port=${ACCT_PORT}`,
    "--window-size=1920,1080", "--window-position=0,0", "--no-first-run", "--no-default-browser-check",
    // keep painting while another window covers it (else every scripted key waits for a frame); not automation flags
    "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding", "--disable-background-timer-throttling",
    APP],
  { detached: true, stdio: "ignore" });
  p.unref();
  console.log(`Chrome is open (profile ${ACCT_PROFILE}, port ${ACCT_PORT}).\n`
    + "Sign in with Google in that window, then run --account <shots>");
}

/** A big line for Juan and a beep; then waits (recording goes on) until `until` is true or the time runs out. */
async function cue(text, until, { timeout = 300_000 } = {}) {
  const bar = "█".repeat(Math.min(100, text.length + 8));
  console.log(`\n\x1b[1;30;43m${bar}\n██  ▶ ${text}  ██\n${bar}\x1b[0m\n`);
  spawn("afplay", ["/System/Library/Sounds/Ping.aiff"], { stdio: "ignore" }).on("error", () => {});
  if (DRY || !until) { await beat(DRY ? 3000 : 0); return true; }
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (await until().catch(() => false)) { console.log("   ✓ done, carrying on"); return true; }
    await beat(500);
  }
  console.log("   … timed out, carrying on");
  return false;
}

/** Types a question; sends it unless this is a rehearsal (then it is typed and cleared again). */
async function acctAsk(page, text) {
  const input = page.locator("form.chat-input input");
  await press(page, input, { pause: 300 });
  await input.pressSequentially(text, { delay: TYPE_MS, timeout: 120_000 });
  await beat(700);
  if (DRY) { await beat(1500); await input.fill(""); return false; }
  await page.keyboard.press("Enter");
  return true;
}

/** Back to a calm map: no drawer, no menu, the Map view. */
async function calm(page) {
  if (!page.url().startsWith(APP)) await page.goto(APP);
  await page.evaluate(() => document.activeElement?.blur?.()); // so Escape reaches the drawer, not an input
  await page.keyboard.press("Escape"); await beat(300); await page.keyboard.press("Escape");
  const map = page.getByRole("radio", { name: "Map", exact: true });
  await map.waitFor({ timeout: 60_000 });
  if ((await map.getAttribute("aria-checked")) !== "true") await map.click();
  await page.locator(".dnode").first().waitFor({ timeout: 60_000 });
  await page.evaluate(() => scrollTo(0, 0));
  await beat(800);
}

/** Opens a top-bar panel by its label (or one under More). Pressing it again closes it. */
async function panel(page, label) {
  const direct = page.locator("header.top nav > button", { hasText: label });
  if (await direct.count()) return press(page, direct.first(), { pause: 1200 });
  const item = page.locator(".more-list button", { hasText: label }).first();
  const more = page.locator("header.top button", { hasText: /^More/ }).first();
  await press(page, more, { pause: 700 });
  if (!(await item.isVisible())) await press(page, more, { pause: 700 }); // a hover may already have opened it
  await press(page, item, { pause: 1200 });
}

/** Scrolls an element (default: the window) slowly to its end, at `pps` pixels a second. `onStep` can pause. */
async function slowScroll(page, target, { pps = 120, max = 60_000, onStep } = {}) {
  const t0 = Date.now();
  for (;;) {
    const left = await (target
      ? target.evaluate((el) => { el.scrollTop += 4; return el.scrollHeight - el.scrollTop - el.clientHeight; })
      : page.evaluate(() => { scrollBy(0, 4); return document.documentElement.scrollHeight - scrollY - innerHeight; }));
    if (onStep) await onStep();
    if (left <= 1 || Date.now() - t0 > max) break;
    await beat(4000 / pps);
  }
}

/** A device node on the map by (part of) its name. */
const acctNode = (page, re) => page.locator(".react-flow__node").filter({ hasText: re }).first();
const MAC_MINI = /Mac ?mini/i, PI = /Raspberry|\bPi\b/i;

const ACCOUNT = {
  // 2, 3: each device's card as it is named, the needs line, then Map · List · Status
  async map(page, mark) {
    await beat(2000); mark("map");
    const n = Math.min(10, await page.locator(".react-flow__node:has(.dnode)").count());
    for (let i = 0; i < n; i++) {
      const it = page.locator(".react-flow__node:has(.dnode)").nth(i);
      const name = ((await it.locator(".dhead").first().innerText().catch(() => "")) || `device ${i + 1}`).split("\n")[0];
      await press(page, it, { pause: 2000 }); mark(`device: ${name}`);
      await page.keyboard.press("Escape"); await beat(600);
    }
    const needs = page.locator(".needs-strip, .needs-list").first();
    if (await needs.count()) { await page.mouse.move(...Object.values(centre(await needs.boundingBox())), { steps: 25 }); }
    await beat(2500); mark("needs");
    for (const v of ["Map", "List", "Status", "Map"]) {
      await press(page, page.getByRole("radio", { name: v, exact: true }), { pause: 2200 }); mark(`view: ${v}`);
    }
  },
  // 4–7 replay: Conversations → today's Mac mini chat (the one that mentions Gradle), read slowly to the result
  async replay(page, mark) {
    const match = new RegExp(process.env.REPLAY_MATCH ?? "Gradle", "i");
    const convos = page.getByRole("button", { name: "Conversations", exact: true });
    const today = await page.evaluate(() => new Date().toLocaleDateString(undefined, { month: "short", day: "numeric" }));
    // find it first (off camera): open candidates until one mentions Gradle
    // the list reorders as chats are opened (most recently used first): find a chat by its first question
    const byTitle = (title) => page.locator(".convo").filter({ has: page.locator(".convo-title", { hasText: title }) }).first();
    let pick = null;
    await convos.click(); await page.locator(".convo").first().waitFor({ timeout: 20_000 });
    const rows = await page.locator(".convo").evaluateAll((b) => b.map((x) => ({
      title: x.querySelector(".convo-title")?.textContent ?? "", when: x.innerText })));
    const order = rows.map((r, i) => ({ ...r, i })).sort((a, b) =>
      (+!a.when.includes(today) - +!b.when.includes(today)) || (+!MAC_MINI.test(a.title) - +!MAC_MINI.test(b.title)) || a.i - b.i);
    await page.keyboard.press("Escape");
    for (const { title: t } of order.slice(0, 12)) {
      if (!(await page.locator(".convo").count())) await convos.click();
      await byTitle(t).click();
      await chat(page).locator(".bubble").first().waitFor({ timeout: 20_000 }).catch(() => {});
      await beat(1200);
      if (match.test(await chat(page).locator(".chat-log").innerText())) { pick = t; break; }
    }
    if (!pick) throw new Error(`no conversation mentions ${match}`);
    console.log(`   replay: "${pick}"`);
    await page.getByRole("button", { name: "New chat", exact: true }).click().catch(() => {}); // start the take clean
    await beat(1000);
    return async (mark) => {
      await beat(1500);
      await press(page, convos, { pause: 1500 }); mark("conversations");
      await press(page, byTitle(pick), { pause: 2000 }); mark("opened");
      const log = chat(page).locator(".chat-log");
      await log.evaluate((el) => { el.scrollTop = 0; }); await beat(1500);
      const seen = new Set();
      const spot = async (key, loc, then) => { // pause and mark when something first comes into view
        if (seen.has(key)) return;
        const el = loc.first();
        if (!(await el.count()) || !(await el.isVisible())) return;
        const b = await el.boundingBox(), box = await log.boundingBox();
        if (!b || b.y > box.y + box.height * 0.7) return;
        seen.add(key); mark(key); if (then) await then(el); await beat(2500);
      };
      await slowScroll(page, log, { pps: 110, max: 120_000, onStep: async () => {
        await spot("investigate", chat(page).locator(".chat-system", { hasText: "Investigate deeply" }));
        for (const [k, h] of (await chat(page).locator(".wl-head[aria-expanded=false]").all()).entries())
          await spot(`steps-${k}`, h, (el) => press(page, el, { pause: 800 }));
        await spot("gradle", chat(page).locator(".bubble.agent", { hasText: match }));
        await spot("card", chat(page).locator(".card"));
        await spot("command", chat(page).locator(".card summary", { hasText: "Show the exact command" }),
          (el) => press(page, el, { pause: 800 }));
        await spot("passkey", chat(page).locator(".card", { hasText: /passkey/i }));
        await spot("result", chat(page).locator(".card dt", { hasText: /^Result$/ }));
        await spot("receipt", chat(page).locator(".wl-head", { hasText: "What I checked" }).last());
      } });
      await beat(3000); mark("end");
    };
  },
  // 4 live: a new chat asks about the Mac mini; hold on its node while it glows
  async glow(page, mark) {
    const fresh = page.getByRole("button", { name: "New chat", exact: true });
    if (await fresh.isEnabled()) await fresh.click();
    await page.getByRole("radio", { name: "Quick answers", exact: true }).click().catch(() => {});
    await beat(800);
    return async (mark) => {
      const mini = acctNode(page, MAC_MINI);
      await beat(1500); mark("map");
      const sent = await acctAsk(page, "How is my Mac mini doing?"); mark("asked");
      await page.mouse.move(...Object.values(centre(await mini.boundingBox())), { steps: 30 });
      if (sent) {
        await mini.locator(".lit-working").waitFor({ timeout: 60_000 }).then(() => mark("glow"), () => {});
        await answered(page).catch(() => {}); mark("answered");
      }
      await beat(4000);
    };
  },
  // 7 live: the Mac mini drawer, Overview (the disk gauge) then Knowledge → "Fixes that worked here"
  async drawer(page, mark) {
    await beat(1200);
    await press(page, acctNode(page, MAC_MINI), { pause: 3500 }); mark("overview");
    await press(page, page.locator(".drawer [role=tab]", { hasText: "Knowledge" }), { pause: 1500 }); mark("knowledge");
    const fixes = page.locator(".drawer h4", { hasText: "Fixes that worked here" });
    if (await fixes.count()) { await fixes.first().scrollIntoViewIfNeeded(); mark("fixes"); }
    await beat(4500);
  },
  // 8: the Pi, Investigate deeply, the grant card → Juan approves with his passkey → the follow-up needs no tap
  async pihole(page) {
    const fresh = page.getByRole("button", { name: "New chat", exact: true });
    if (await fresh.isEnabled()) await fresh.click();
    await page.getByRole("radio", { name: "Investigate deeply", exact: true }).click();
    await beat(800);
    return async (mark) => {
      await beat(2000);
      await press(page, acctNode(page, PI), { pause: 2500 }); mark("pi");
      await page.keyboard.press("Escape").catch(() => {});
      const sent = await acctAsk(page, "Earlier today Pi-hole stopped. What happened, and is it healthy now?");
      mark("asked");
      const sign = chat(page).locator(".card button", { hasText: "Approve with passkey" }).last();
      if (sent) {
        const got = await Promise.race([sign.waitFor({ timeout: AGENT_WAIT }).then(() => "card"),
          answered(page).then(() => "answered")]).catch(() => "timeout");
        if (got !== "card") console.log("   no grant card appeared (a grant from an earlier take may still be valid)");
        else {
          mark("card"); await beat(3000);
          await sign.hover(); // the dot rests on the button for Juan
          const card = chat(page).locator(".card").last();
          await cue("JUAN: click Approve with passkey, then Touch ID",
            () => card.locator("dt", { hasText: /^Result$/ }).count().then((c) => c > 0));
          mark("result");
        }
        await answered(page).catch(() => {}); mark("answered");
        await beat(10_000);
      } else await cue("JUAN: (rehearsal) here you would click Approve with passkey, then Touch ID");
      const again = await acctAsk(page, "Which program is using port 53?"); mark("follow-up");
      if (again) { await answered(page).catch(() => {}); mark("follow-up answered"); }
      await beat(5000);
    };
  },
  // 9: More → Trust
  async trust(page, mark) {
    await beat(1000);
    await panel(page, "Trust"); mark("trust"); await beat(4500);
    return { after: () => panel(page, "Trust") };
  },
  // 10: the Status board, slowly
  async status(page, mark) {
    await beat(1000);
    await press(page, page.getByRole("radio", { name: "Status", exact: true }), { pause: 2500 }); mark("status");
    const board = page.locator(".left").first();
    await page.mouse.move(...Object.values(centre(await board.boundingBox())), { steps: 20 });
    for (let i = 0; i < 60; i++) { await page.mouse.wheel(0, 12); await beat(60); }
    mark("scrolled"); await beat(2500);
  },
  // 13: Found nearby (never zoom on its rows: addresses), the printer's drawer, Activity
  async nearby(page, mark) {
    await beat(1000);
    await panel(page, "Found nearby"); mark("found nearby (blur addresses; no zoom)"); await beat(4000);
    await panel(page, "Found nearby");
    const printer = acctNode(page, /printer|laserjet|brother|epson|canon|\bhp\b/i);
    if (await printer.count()) { await press(page, printer, { pause: 3500 }); mark("printer"); await page.keyboard.press("Escape"); }
    await panel(page, "Activity"); mark("activity");
    const moved = page.locator(":text('is now watched from')").first();
    if (await moved.count()) { await moved.scrollIntoViewIfNeeded(); mark("watched from"); }
    await beat(4500);
    return { after: () => panel(page, "Activity") };
  },
};

/** 15: the start screen in a fresh private window (not signed in), each of the three choices pointed at. */
async function startScreen(browser, name) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, colorScheme: "dark" });
  await ctx.addInitScript(pointer);
  const page = await ctx.newPage(); current = page;
  await page.goto(APP);
  await page.getByRole("heading", { name: /Go to sleep/ }).waitFor({ timeout: 30_000 });
  await beat(1000);
  const { mark, stop } = await record(page, name);
  await beat(2500); mark("start");
  for (const re of [/Sign in with Google/, /Take the tour/, /Hands on with a VM|Demo Linux VM/]) {
    const b = page.getByRole("button", { name: re }).first();
    if (!(await b.count())) continue;
    await b.scrollIntoViewIfNeeded();
    await page.mouse.move(...Object.values(centre(await b.boundingBox())), { steps: 30 });
    mark(String(re)); await beat(2500);
  }
  await beat(1500);
  await stop(); await ctx.close();
}

async function account(shots) {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${ACCT_PORT}`).catch(() => {
    throw new Error(`no Chrome on port ${ACCT_PORT}: run node capture.mjs --open-account first`);
  });
  const ctx = browser.contexts()[0];
  const page = ctx.pages().find((p) => p.url().startsWith(APP)) ?? ctx.pages()[0] ?? await ctx.newPage();
  await page.bringToFront();
  await ctx.addInitScript(pointer);
  await page.evaluate(pointer);
  if (process.env.ACCT_VIEWPORT) {
    const [width, height] = process.env.ACCT_VIEWPORT.split("x").map(Number);
    await page.setViewportSize({ width, height });
  }
  const report = [];
  let rec = null;
  for (const shot of shots) {
    const name = `acct-${shot}${DRY ? "-dry" : ""}`, t0 = Date.now();
    current = page;
    try {
      if (shot === "start") await startScreen(browser, name);
      else if (!ACCOUNT[shot]) { report.push(`??    ${shot}: no such account shot`); continue; }
      else {
        await calm(page);
        if (!DRY && /Sample home/.test(await page.locator("header.top").innerText()))
          console.log("   note: this window shows the sample home, not a signed-in account");
        // a shot either records itself whole, or returns the take (after setting things up off camera)
        rec = null;
        const lazy = (step) => rec?.mark(step);
        const early = ["glow", "pihole", "replay"].includes(shot);
        if (!early) { rec = await record(page, name); }
        const r = await ACCOUNT[shot](page, lazy);
        if (typeof r === "function") { rec = await record(page, name); await r(rec.mark); }
        await rec.stop();
        await r?.after?.().catch(() => {});
      }
      report.push(`ok    ${name} (${Math.round((Date.now() - t0) / 1000)} s)`);
    } catch (e) {
      report.push(`FAIL  ${name}: ${e.message.split("\n")[0]}`);
      await page.screenshot({ path: path.join(RAW, `${name}-FAIL.png`) }).catch(() => {});
      await rec?.abort(); rec = null;
    }
  }
  await browser.close(); // disconnects; Juan's Chrome stays open and signed in
  console.log(`${report.join("\n")}\n→ ${RAW}`);
}

const args = process.argv.slice(2).filter((a) => !a.startsWith("--"));
await mkdir(RAW, { recursive: true });
if (flags.has("--open-account")) { await openAccount(); process.exit(0); }
if (flags.has("--account")) {
  await account(args.length ? args : ["map", "replay", "glow", "drawer", "pihole", "trust", "status", "nearby", "start"]);
  process.exit(0);
}

const wanted = args.length ? args : [...Object.keys(SHOTS), ...Object.keys(STILLS)];
await mkdir(README, { recursive: true });
const browser = await chromium.launch({ channel: "chrome" });
const report = [];
for (const shot of wanted) {
  const stills = STILLS[shot];
  if (!stills && !SHOTS[shot]) { report.push(`??    ${shot}: no such shot`); continue; }
  for (const theme of shot === "readme" ? ["light", "dark"] : THEMES) {
    for (let take = 1; take <= (stills ? 1 : TAKES); take++) {
      const name = [shot, THEMES.length > 1 && theme, TAKES > 1 && take].filter(Boolean).join("-");
      const t0 = Date.now();
      try {
        await (stills ?? SHOTS[shot])(browser, theme, name);
        report.push(`ok    ${name || shot} ${theme} (${Math.round((Date.now() - t0) / 1000)} s)`);
      } catch (e) {
        report.push(`FAIL  ${name || shot} ${theme}: ${e.message.split("\n")[0]}`);
        await current?.screenshot({ path: path.join(RAW, `${name || shot}-FAIL.png`) }).catch(() => {});
        await current?.context().close().catch(() => {});
      }
    }
  }
}
await browser.close();
console.log(`${report.join("\n")}\n→ ${RAW}\n→ ${README}`);
