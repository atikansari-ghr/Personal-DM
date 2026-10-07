// Automated accessibility audit (axe-core, WCAG 2.1 A/AA rules) across the main screens in all three themes,
// plus a keyboard check of the resizable panels. Run against an instance prepared by flow.mjs:
//   BASE=http://localhost:8000 node tests/e2e/a11y.mjs
// Fails on any "serious" or "critical" violation; lists moderate/minor ones for information.
import { chromium } from "playwright";
import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const AXE = fs.readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const BASE = process.env.BASE || "http://localhost:8000";
const USER = process.env.A11Y_USER || "admin";
const PW = process.env.A11Y_PASSWORD || "Sample-Passw0rd!";
const THEMES = ["green", "blue", "mono"];
const PAGES = [
  ["login", "/login", false],
  ["dashboard", "/", true],
  ["folders", "/folders", true],
  ["search", "/search?q=sample", true],
  ["notifications", "/notifications", true],
  ["offline", "/offline", true],
  ["archive", "/archive", true],
  ["settings-account", "/settings/account", true],
  ["settings-security", "/settings/account?tab=security", true],
  ["settings-notifications", "/settings/notifications", true],
  ["settings-family", "/settings/family", true],
  ["settings-storage", "/settings/storage", true],
  ["help", "/help/getting-started", true],
  ["my-notifications", "/settings/account?tab=notifications", true],
  ["appearance-widgets", "/settings/account?tab=appearance", true],
  ["access-security", "/settings/security?view=access", true],
  ["local-ai", "/settings/ai", true],
  ["login-audit", "/settings/activity?view=logins", true],
  ["import", "/imports/new", true],
  ["ocr-review", "/ocr-review", true],
  ["settings-overview-sign-in", "/settings/overview", true],
  ["security-overview", "/settings/security", true],
  ["security-antivirus", "/settings/security?view=antivirus", true],
  ["security-test", "/settings/security?view=test", true],
  ["security-storage", "/settings/security?view=storage", true],
];

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
const results = [];
let blocking = 0;

async function audit(page, name) {
  await page.addScriptTag({ content: AXE });
  const res = await page.evaluate(async () =>
    // eslint-disable-next-line no-undef
    await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] }, resultTypes: ["violations"] }));
  for (const v of res.violations) {
    const serious = ["serious", "critical"].includes(v.impact);
    if (serious) blocking++;
    results.push({ page: name, impact: v.impact, id: v.id, help: v.help, nodes: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) });
  }
  return res.violations.length;
}

for (const theme of THEMES) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, bypassCSP: true });
  const page = await ctx.newPage();
  await page.addInitScript((t) => localStorage.setItem("pd-theme", t), theme);
  // anonymous login page
  await page.goto(BASE + "/login");
  await page.waitForSelector("#username");
  await audit(page, `${theme}/login`);
  await page.fill("#username", USER);
  await page.fill("#password", PW);
  await page.click("button:has-text('Sign in')");
  await page.waitForSelector("text=Good");
  // set the account theme through the real settings API so the app applies it
  await page.evaluate(async (t) => {
    const csrf = document.cookie.match(/pd_csrftoken=([^;]+)/)[1];
    await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: JSON.stringify({ values: { "me.theme": t } }) });
  }, theme);
  for (const [name, path, auth] of PAGES) {
    if (!auth) continue;
    await page.goto(BASE + path);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(400);
    const applied = await page.evaluate(() => document.documentElement.dataset.theme);
    if (applied !== theme) results.push({ page: `${theme}/${name}`, impact: "serious", id: "theme-not-applied", help: `expected ${theme}, got ${applied}`, nodes: [] }), blocking++;
    await audit(page, `${theme}/${name}`);
  }
  if (theme === "green") {
    // document detail panel and dialogs
    await page.goto(BASE + "/folders");
    const card = page.locator(".doc-card").first();
    if (await card.count()) {
      await card.click();
      await page.waitForSelector(".detail-pane >> text=Details");
      await audit(page, `${theme}/document-panel`);
      await page.click(".detail-pane button:has-text('Share')");
      await page.waitForSelector("[role=dialog]");
      await audit(page, `${theme}/share-dialog`);
      await page.keyboard.press("Escape");
    }
    // full-page document viewer and the "Move to…" folder picker
    const first = await page.evaluate(async () => (await (await fetch("/api/documents?limit=1")).json()).documents[0]);
    if (first) {
      await page.goto(`${BASE}/documents/${first.id}`);
      await page.waitForSelector(".viewer, .viewer-error, .empty");
      await page.waitForTimeout(800);
      await audit(page, `${theme}/document-viewer`);
      await page.goto(`${BASE}/folders/${first.folder}`);
      await page.click(`button[aria-label='More actions for ${first.title}']`);
      const move = page.locator("[role=menuitem]:has-text('Move to…')");
      if (await move.count()) {
        await move.click();
        await page.waitForSelector(".folder-picker");
        await audit(page, `${theme}/move-to-dialog`);
        await page.keyboard.press("Escape");
      }
      // an open actions menu, and the details view with sortable headers
      await page.goto(`${BASE}/folders/${first.folder}`);
      await page.click(`button[aria-label='More actions for ${first.title}']`);
      await page.waitForSelector(".menu-pop");
      await audit(page, `${theme}/actions-menu`);
      await page.keyboard.press("Escape");
      await page.click("button[aria-label='Details view']");
      await page.waitForSelector("table.details-table");
      await audit(page, `${theme}/details-view`);
      await page.click("button[aria-label='List view']");
    }
    // keyboard resizing of the folder tree
    const handle = page.locator(".panel-handle").first();
    const before = Number(await handle.getAttribute("aria-valuenow"));
    await handle.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    const after = Number(await page.locator(".panel-handle").first().getAttribute("aria-valuenow"));
    if (!(after > before)) results.push({ page: "folders", impact: "serious", id: "panel-keyboard-resize", help: `width ${before} -> ${after}`, nodes: [] }), blocking++;
    await page.reload();
    const persisted = Number(await page.locator(".panel-handle").first().getAttribute("aria-valuenow"));
    if (persisted !== after) results.push({ page: "folders", impact: "serious", id: "panel-width-persist", help: `${after} vs ${persisted}`, nodes: [] }), blocking++;
    await page.locator(".panel-handle").first().dblclick();
    // mobile layout audit
    const m = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, bypassCSP: true, storageState: await ctx.storageState() });
    const mp = await m.newPage();
    for (const [name, path] of [["mobile-dashboard", "/"], ["mobile-folders", "/folders"]]) {
      await mp.goto(BASE + path);
      await mp.waitForLoadState("networkidle");
      await audit(mp, `${theme}/${name}`);
    }
    await m.close();
  }
  await ctx.close();
}
await browser.close();
// restore default theme for the account
fs.writeFileSync(process.env.A11Y_REPORT || "docs/a11y-report.json", JSON.stringify({ blocking, results }, null, 1));
for (const r of results) console.log(`${["serious", "critical"].includes(r.impact) ? "FAIL" : "info"} [${r.impact}] ${r.page}: ${r.id} — ${r.help} ${r.nodes.join(" | ")}`);
console.log(blocking ? `${blocking} blocking accessibility violation(s)` : "No serious or critical accessibility violations");
process.exit(blocking ? 1 : 0);
