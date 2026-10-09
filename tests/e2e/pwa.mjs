// Installed-app identity (Change Set S, AT-260..AT-263) checked in Chromium, signed out (phones fetch icons without
// the session). Real iPhone/iPad/Android installs cannot run here: they are recorded as Not Run in docs/TEST_REPORT.md.
// Usage: BASE=http://localhost:8000 node tests/e2e/pwa.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const OUT = "tests/e2e/out/pwa";
fs.mkdirSync(OUT, { recursive: true });
const results = [];
let failed = 0;
const step = async (name, fn) => {
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { failed++; results.push(["FAIL", name, String(e).slice(0, 800)]); console.log("FAIL", name, String(e).slice(0, 800)); }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
// a persistent (non-incognito) profile: Chromium refuses to install apps from incognito windows
const ctx = await chromium.launchPersistentContext(fs.mkdtempSync("/tmp/pd-pwa-"), { executablePath: process.env.CHROMIUM || undefined, viewport: { width: 1280, height: 800 } }); // never signed in
const page = ctx.pages()[0] || await ctx.newPage();
await page.goto(BASE + "/login");
await page.waitForSelector("#username");

// fetch without cookies and decode the image in the browser
const probe = (url) => page.evaluate(async (url) => {
  const r = await fetch(url, { credentials: "omit", cache: "no-store", redirect: "manual" });
  const type = r.headers.get("Content-Type") || "";
  const out = { status: r.status, type };
  if (r.ok && type.startsWith("image/")) {
    const blob = await r.blob();
    try {
      const bmp = await createImageBitmap(blob);
      const c = new OffscreenCanvas(bmp.width, bmp.height);
      const g = c.getContext("2d");
      g.drawImage(bmp, 0, 0);
      const px = (x, y) => Array.from(g.getImageData(x, y, 1, 1).data);
      out.width = bmp.width; out.height = bmp.height;
      out.corners = [px(0, 0), px(bmp.width - 1, 0), px(0, bmp.height - 1), px(bmp.width - 1, bmp.height - 1)];
      // white artwork outside the maskable safe circle (radius 40 % of the size)?
      let outside = 0;
      const d = g.getImageData(0, 0, bmp.width, bmp.height).data, r0 = 0.4 * bmp.width, cx = bmp.width / 2;
      for (let y = 0; y < bmp.height; y += 2) for (let x = 0; x < bmp.width; x += 2) {
        if ((x - cx) ** 2 + (y - cx) ** 2 <= r0 * r0) continue;
        const i = (y * bmp.width + x) * 4;
        if (d[i] > 200 && d[i + 1] > 200 && d[i + 2] > 200 && d[i + 3] > 200) outside++;
      }
      out.whiteOutsideSafeZone = outside;
    } catch (e) { out.decodeError = String(e); }
  }
  return out;
}, url);

let manifest;
await step("AT-260 manifest: identity, scope, display, colours and icons validate and load without sign-in", async () => {
  const r = await page.evaluate(async () => { const r = await fetch("/manifest.webmanifest", { credentials: "omit" }); return { status: r.status, type: r.headers.get("Content-Type"), body: await r.text() }; });
  expect(r.status === 200 && /application\/manifest\+json/.test(r.type), `manifest served as ${r.status} ${r.type}`);
  manifest = JSON.parse(r.body);
  expect(manifest.name === "Personal Documents Management System" && manifest.short_name === "Personal DM", "names");
  expect(manifest.start_url === "/" && manifest.scope === "/" && manifest.display === "standalone" && manifest.id === "/", "start/scope/display/id");
  expect(/^#[0-9a-f]{6}$/i.test(manifest.theme_color) && /^#[0-9a-f]{6}$/i.test(manifest.background_color), "colours");
  for (const icon of manifest.icons) {
    const p = await probe(icon.src);
    expect(p.status === 200 && p.type.startsWith(icon.type), `${icon.src}: ${p.status} ${p.type}`);
    if (icon.type === "image/png") expect(`${p.width}x${p.height}` === icon.sizes, `${icon.src} is ${p.width}x${p.height}, manifest says ${icon.sizes}`);
  }
  expect(manifest.icons.some((i) => i.purpose === "maskable" && i.sizes === "512x512"), "no 512 maskable icon");
  // Chromium's own manifest parser and installability checks (the same ones behind "Install app")
  const cdp = await ctx.newCDPSession(page);
  const parsed = await cdp.send("Page.getAppManifest");
  expect(!parsed.errors?.length, "manifest parse errors: " + JSON.stringify(parsed.errors));
  await page.waitForFunction(() => navigator.serviceWorker?.controller || navigator.serviceWorker?.ready, null, { timeout: 15000 }).catch(() => undefined);
  await page.reload();
  await page.waitForSelector("#username");
  const inst = await cdp.send("Page.getInstallabilityErrors");
  expect(!inst.installabilityErrors?.length, "installability errors: " + JSON.stringify(inst.installabilityErrors));
});

await step("AT-261 Apple touch icon: markup, 180×180, opaque, title, and conventional root paths", async () => {
  const head = await page.evaluate(() => ({
    touch: [...document.querySelectorAll('link[rel="apple-touch-icon"]')].map((l) => [l.getAttribute("href"), l.getAttribute("sizes")]),
    title: document.querySelector('meta[name="apple-mobile-web-app-title"]')?.getAttribute("content"),
    capable: document.querySelector('meta[name="apple-mobile-web-app-capable"]')?.getAttribute("content"),
  }));
  expect(head.touch.length === 1 && head.touch[0][0] === "/apple-touch-icon.png" && head.touch[0][1] === "180x180", "touch icon link: " + JSON.stringify(head.touch));
  expect(head.title === "Personal DM" && head.capable === "yes", "apple meta tags");
  for (const u of ["/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"]) {
    const p = await probe(u);
    expect(p.status === 200 && p.type === "image/png" && p.width === 180 && p.height === 180, `${u}: ${JSON.stringify(p).slice(0, 200)}`);
    expect(p.corners.every((c) => c[3] === 255), `${u} has transparent corners (iOS paints them black)`);
  }
});

await step("AT-262 desktop identity in Chromium: installable, service worker, theme colour, favicon", async () => {
  const sw = await page.evaluate(async () => (await navigator.serviceWorker.getRegistration())?.active?.scriptURL || "");
  expect(sw.endsWith("/sw.js"), "service worker not active: " + sw);
  const shell = await page.evaluate(async () => (await caches.keys()).filter((k) => k.startsWith("pd-shell-")));
  expect(shell.includes("pd-shell-v2"), "app shell cache: " + shell);
  const shellKeys = await page.evaluate(async () => (await (await caches.open("pd-shell-v2")).keys()).map((r) => new URL(r.url).pathname));
  expect(!shellKeys.some((k) => k.startsWith("/api/") || k.startsWith("/offline")), "user data in the shell cache: " + shellKeys);
  const ico = await probe("/favicon.ico");
  expect(ico.status === 200 && /icon/.test(ico.type), "favicon.ico: " + JSON.stringify(ico).slice(0, 120));
  const f32 = await probe("/favicon-32.png");
  expect(f32.width === 32, "favicon-32");
});

await step("AT-263 icon scaling: recognisable, unclipped, maskable artwork inside the safe zone", async () => {
  const m512 = await probe("/icon-maskable-512.png");
  expect(m512.corners.every((c) => c[3] === 255), "maskable icon not full bleed");
  expect(m512.whiteOutsideSafeZone === 0, `maskable artwork leaves the safe zone (${m512.whiteOutsideSafeZone} px)`);
  const any = await probe("/icon-512.png");
  expect(any.corners.every((c) => c[3] === 0), "rounded 'any' icon should have transparent corners");
  // a missing file is a 404, never the app page (an HTML answer made iPhones show a letter tile)
  for (const u of ["/apple-touch-icon-120x120.png", "/does-not-exist.ico"]) {
    const p = await probe(u);
    expect(p.status === 404 && !p.type.startsWith("text/html"), `${u}: ${p.status} ${p.type}`);
  }
  // contact sheet for human review (CI artifact)
  await page.setContent(`<body style="margin:0;padding:24px;display:flex;gap:28px;align-items:flex-end;font:13px system-ui;background:#eef2ef">
    ${[["/icon-512.png", 192, "512 any"], ["/icon-maskable-512.png", 160, "maskable (circle)"], ["/apple-touch-icon.png", 180, "180 Apple"], ["/icon-192.png", 96, "192"], ["/favicon-32.png", 32, "32"], ["/favicon-16.png", 16, "16"]]
      .map(([s, w, l]) => `<figure style="margin:0;text-align:center"><img src="${BASE}${s}" width="${w}" style="${l.startsWith("maskable") ? "border-radius:50%" : l.startsWith("180") ? "border-radius:22%" : ""}"><figcaption>${l}</figcaption></figure>`).join("")}</body>`);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/icons.png` });
});

await ctx.close();
await browser.close();
fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 1));
console.log(`\npwa e2e: ${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
