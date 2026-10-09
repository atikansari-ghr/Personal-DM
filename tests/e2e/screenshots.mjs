// Repeatable public screenshots (Change Set S, AT-270..AT-274): README story and screens no other test captures.
// Runs last in scripts/e2e.sh, on the synthetic demo state built by flow.mjs and parity.mjs. Every capture:
//   * 1440×900 CSS px at device pixel ratio 2 (phones 390×844 at 2), consistent across all images;
//   * after fonts load and animations settle (reduced motion), with no loading placeholders or toasts;
//   * passes a quality gate (no horizontal overflow, no clipped text, all images decoded) and a privacy gate
//     (no e-mail address outside example domains, no IP outside documentation ranges, no token-like strings).
// Output: docs/images/screenshots/ (PUBLIC_SHOTS overrides) and a manifest with the source of each image.
// Usage: BASE=http://localhost:8000 node tests/e2e/screenshots.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const SHOTS = process.env.PUBLIC_SHOTS || "docs/images/screenshots";
const PW = "Sample-Passw0rd!";
fs.mkdirSync(SHOTS, { recursive: true });
const results = [];
const manifest = [];
let failed = 0;
const step = async (name, fn) => {
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { failed++; results.push(["FAIL", name, String(e).slice(0, 800)]); console.log("FAIL", name, String(e).slice(0, 800)); }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };
const PRIVATE = [
  [/[A-Z0-9._%+-]+@(?!example\.(com|org|net)\b|family\.example\b|test\b|invalid\b|localhost\b)[A-Z0-9.-]+\.[A-Z]{2,}/i, "e-mail address outside example domains"],
  [/\b(?!(?:127|10|192\.0\.2|198\.51\.100|203\.0\.113)\.)(?:\d{1,3}\.){3}\d{1,3}\b/, "IP address outside documentation ranges"],
  [/(?<![A-Za-z0-9_-])(?![A-Za-z0-9_-]*[-_][A-Za-z]{4,}[-_][A-Za-z]{4,})[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_-])/, "token-like string"], // file names made of words are not tokens
];

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
const api = (page, url, opts = {}) => page.evaluate(async ([url, opts]) => {
  const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
  const r = await fetch(url, { method: opts.method || (opts.body ? "POST" : "GET"), headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: opts.body ? JSON.stringify(opts.body) : undefined });
  return { status: r.status, data: r.headers.get("content-type")?.includes("json") ? await r.json() : null };
}, [url, opts]);
async function session(viewport, user = "admin", pw = PW, mobile = false) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2, reducedMotion: "reduce", isMobile: mobile, hasTouch: mobile });
  const page = await ctx.newPage();
  await page.goto(BASE + "/login");
  await page.fill("#username", user);
  await page.fill("#password", pw);
  await page.click("button:has-text('Sign in')");
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 });
  await page.waitForLoadState("networkidle");
  return { ctx, page };
}

/** Quality + privacy gate, then capture. `source` documents where the image comes from (all are the real app). */
async function capture(page, file, caption) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => !document.querySelector(".skeleton") && [...document.images].every((i) => i.complete), null, { timeout: 15000 });
  await page.evaluate(() => document.querySelectorAll(".toast").forEach((t) => t.remove()));
  await page.waitForTimeout(400);
  const q = await page.evaluate(() => {
    const issues = [];
    if (document.documentElement.scrollWidth > innerWidth + 1) issues.push("page scrolls sideways");
    for (const img of document.images) if (img.offsetParent && img.complete && img.naturalWidth === 0) issues.push(`broken image ${img.getAttribute("src")}`);
    for (const el of document.querySelectorAll("h1, h2, h3, .btn, .badge, .nav a, label")) {
      if (!el.offsetParent || el.closest(".sr-only")) continue; // visually hidden labels for screen readers are 1 px on purpose
      const cs = getComputedStyle(el);
      if (cs.overflow === "hidden" && cs.textOverflow !== "ellipsis" && el.scrollWidth > el.clientWidth + 2) issues.push(`clipped text: ${el.textContent.trim().slice(0, 40)}`);
    }
    return { issues: issues.slice(0, 5), text: document.body.innerText };
  });
  expect(!q.issues.length, `${file}: ${q.issues.join("; ")}`);
  for (const [re, what] of PRIVATE) {
    const m = q.text.match(re);
    expect(!m, `${file}: ${what} visible: "${m?.[0]?.slice(0, 60)}"`);
  }
  await page.screenshot({ path: `${SHOTS}/${file}` });
  const vp = page.viewportSize();
  manifest.push({ file, caption, source: "real application, synthetic demo data", viewport: `${vp.width}x${vp.height}`, pixelRatio: 2 });
}

const D = await session({ width: 1440, height: 900 });
await api(D.page, "/api/settings", { method: "PUT", body: { values: { "me.theme": "green" } } });
const search = (q) => api(D.page, `/api/documents?q=${encodeURIComponent(q)}`).then((r) => r.data.documents || []);
const card = (await search("Sample residence card"))[0] || (await search("Sample"))[0];
const photo = (await search("Sample photo"))[0];

await step("AT-270 offline access screens (folder dialog, Offline page, phone)", async () => {
  const folder = card?.folder;
  expect(folder, "demo document missing (run flow.mjs and parity.mjs first)");
  await D.page.goto(`${BASE}/folders/${folder}`);
  await D.page.click(`[aria-label="Folder actions"]`);
  const make = D.page.locator("[role=menuitem]:has-text('Make available offline…')");
  if (await make.count()) {
    await make.click();
    await D.page.locator("[role=dialog] >> text=Estimated size").waitFor();
    await capture(D.page, "offline-folder-dialog.png", "Make a folder available offline: with or without subfolders, count and size");
    await D.page.locator("[role=dialog] button:has-text('Make available offline')").click();
  } else await D.page.keyboard.press("Escape");
  await D.page.waitForFunction(() => Object.keys(localStorage).some((k) => k.startsWith("pd-offline-index-") && Object.keys(JSON.parse(localStorage[k]).items || {}).length > 0), null, { timeout: 30000 });
  await D.page.goto(BASE + "/offline");
  await D.page.waitForSelector("text=Offline folders");
  await D.page.waitForSelector("[data-offline-status=available]");
  await D.page.waitForSelector("button:has-text('Sync now')", { timeout: 60000 }); // sync finished
  await D.page.waitForFunction(() => !document.body.innerText.includes("Not synced yet"));
  await capture(D.page, "offline-access.png", "Offline access on this device: folders, documents, status, storage and Update all");
  await D.page.goto(BASE + "/settings/offline");
  await D.page.waitForSelector("text=People and devices");
  await capture(D.page, "settings-offline-pwa.png", "Settings → Offline & PWA: policy, per-person access, devices and app icons");
});

await step("AT-271 document, OCR text, viewer and notifications", async () => {
  if (card) {
    await D.page.goto(`${BASE}/folders/${card.folder}/${card.id}`).catch(() => undefined);
    if (!(await D.page.locator(".detail-pane .doc-header").count())) await D.page.goto(`${BASE}/documents/${card.id}`);
    await D.page.waitForSelector(".doc-header");
    await capture(D.page, "readme-document.png", "Document with preview, status badges and offline status");
  }
  // The OCR story uses parity's ocr-review.png (a fresh, high-confidence recognition with suggested details).
  if (photo) {
    await D.page.goto(`${BASE}/documents/${photo.id}`);
    await D.page.waitForSelector(".viewer");
    await capture(D.page, "readme-viewer.png", "Full-page viewer: zoom, fit page / width");
  }
  await D.page.goto(BASE + "/notifications");
  await D.page.waitForSelector("h1");
  await capture(D.page, "readme-notifications.png", "Notification Center");
});

await step("AT-272 security, access, sign-in records and Local AI (previously stale captures)", async () => {
  for (const [path, file, caption, wait] of [
    ["/settings/security", "readme-security.png", "Security Health, antivirus and storage", "h2"],
    ["/settings/security?view=access", "security-access.png", "Country/IP access policy and GeoIP", "h2"],
    ["/settings/activity?view=logins", "login-audit.png", "Login audit", "h2"],
    ["/settings/ai", "local-ai.png", "Local AI profiles (optional)", "h2"],
    ["/settings/account?tab=security", "settings-security-passkeys.png", "Password, authenticator app and passkeys", "h2"],
  ]) {
    await D.page.goto(BASE + path);
    await D.page.waitForSelector(wait);
    await D.page.waitForLoadState("networkidle");
    await capture(D.page, file, caption);
  }
});

await step("AT-273 themes: gallery and each preset on real screens", async () => {
  await D.page.goto(BASE + "/settings/account?tab=appearance");
  await D.page.waitForSelector(".theme-grid");
  await D.page.locator(".theme-grid").scrollIntoViewIfNeeded();
  await capture(D.page, "settings-themes.png", "Theme gallery: Default Green, Blue, Dark, Glass Light, Glass Dark, Black & White");
  for (const [theme, path, file] of [["glass_dark", "/folders", "theme-glass-dark.png"], ["glass_light", "/", "theme-glass-light.png"], ["dark", "/offline", "theme-dark.png"], ["blue", "/", "theme-blue.png"]]) {
    await api(D.page, "/api/settings", { method: "PUT", body: { values: { "me.theme": theme } } });
    await D.page.goto(BASE + path);
    await D.page.waitForFunction((t) => document.documentElement.dataset.theme === t, theme);
    await D.page.waitForLoadState("networkidle");
    await capture(D.page, file, `${theme.replace("_", " ")} theme`);
  }
  await api(D.page, "/api/settings", { method: "PUT", body: { values: { "me.theme": "green" } } });
});

await step("AT-274 phone: overview and offline access (installed-app size)", async () => {
  const M = await session({ width: 390, height: 844 }, "admin", PW, true);
  await M.page.goto(BASE + "/offline");
  await M.page.waitForSelector("h1:has-text('Offline access')");
  await capture(M.page, "mobile-offline.png", "Phone: offline access");
  await M.ctx.close();
});

await D.ctx.close();
await browser.close();
fs.writeFileSync(`${SHOTS}/../screenshot-manifest.json`, JSON.stringify(manifest, null, 1) + "\n");
fs.mkdirSync("tests/e2e/out", { recursive: true });
fs.writeFileSync("tests/e2e/out/screenshots-results.json", JSON.stringify(results, null, 1));
console.log(`\nscreenshots: ${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
