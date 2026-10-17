// Records the sample-home shots of the demo video (private/plan/video-script-2026-10-18.md, S-rows) and README
// stills from the live Nightlight app. Anonymous sample home only: every shot starts a fresh "Try the demo" session,
// so it is always clean and never needs a Reset. It never signs in. Video comes from Chrome's screencast (sharp
// text) encoded with ffmpeg; Playwright drives the system Chrome. Real-device shots (R-rows) are recorded by hand.
//
//   cd scripts/capture && npm ci && node capture.mjs [shot ...]      (default: every shot below)
//   APP_URL=…   another deployment (a preview)        TAKES=3   record each shot that many times
//   THEMES=light,dark   themes for the video shots (default dark; the README stills are always both)
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
  addEventListener("DOMContentLoaded", () => {
    const s = document.createElement("style"); s.textContent = css; document.head.append(s);
    const d = document.createElement("div"); d.id = "cap-dot"; document.body.append(d);
    const at = (x, y) => { d.style.left = `${x}px`; d.style.top = `${y}px`; d.classList.add("on"); };
    addEventListener("mousemove", (e) => at(e.clientX, e.clientY), true);
    addEventListener("mousedown", () => d.classList.add("down"), true);
    addEventListener("mouseup", () => d.classList.remove("down"), true);
    addEventListener("touchstart", (e) => { const t = e.touches[0]; at(t.clientX, t.clientY); d.classList.add("down"); }, true);
    addEventListener("touchend", () => { d.classList.remove("down"); setTimeout(() => d.classList.remove("on"), 600); }, true);
  });
}

/** Starts recording the page. `mark(name)` notes a step; `stop()` writes the mp4, its last frame and the marks. */
async function record(page, name) {
  const cdp = await page.context().newCDPSession(page);
  const vp = page.viewportSize(), dpr = await page.evaluate(() => devicePixelRatio);
  const frames = [], marks = [];
  cdp.on("Page.screencastFrame", (f) => {
    frames.push({ data: f.data, t: f.metadata.timestamp });
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
    if (frames.length < 2) throw new Error("no frames recorded");
    const dir = path.join(RAW, `.frames-${name}`);
    await mkdir(dir, { recursive: true });
    const list = ["ffconcat version 1.0"];
    for (const [i, f] of frames.entries()) {
      const file = `f${String(i).padStart(5, "0")}.jpg`;
      await writeFile(path.join(dir, file), Buffer.from(f.data, "base64"));
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
  return { mark, stop };
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
  const demo = page.getByRole("button", { name: /Try the demo/ });
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
    await ask(page, "Is anything wrong at home?"); mark("asked");
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
    await ask(page, "Is anything wrong at home?"); mark("asked");
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
      await ask(page, round === 1 ? "Is anything wrong at home?" : "The Pi's disk is full again. Can you clean it up?");
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
    await page.locator(".chat-starter", { hasText: "Is anything wrong at home?" }).click();
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
    await page.locator(".chat-starter", { hasText: "Is anything wrong at home?" }).click();
    await chat(page).locator("button", { hasText: "Not now" }).last().waitFor({ timeout: AGENT_WAIT });
    await answered(page); await beat(800);
    await page.screenshot({ path: path.join(README, `chat-${theme}.png`) });
    await ctx.close();
  },
};

const wanted = process.argv.slice(2).length ? process.argv.slice(2) : [...Object.keys(SHOTS), ...Object.keys(STILLS)];
await mkdir(RAW, { recursive: true });
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
