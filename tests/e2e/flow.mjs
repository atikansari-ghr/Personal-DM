// End-to-end browser flow against a running instance with a fresh database.
// Usage: BASE=http://localhost:8000 SETUP_TOKEN=... FIXTURE=/path/scan.pdf node tests/e2e/flow.mjs
// Uses only synthetic names and files. Saves screenshots to docs/screenshots/.
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const SHOTS = process.env.SHOTS || "docs/screenshots";
const PW = "Sample-Passw0rd!";
const results = [];
const step = async (name, fn) => {
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { results.push(["FAIL", name, String(e).slice(0, 300)]); console.log("FAIL", name, String(e).slice(0, 300)); }
};

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && !/favicon|401|403|404/.test(m.text()) && errors.push(m.text()));

await step("first-run setup: Main Administrator, then optional family members", async () => {
  await page.goto(BASE + "/");
  await page.waitForURL(/setup/);
  await page.screenshot({ path: `${SHOTS}/01-setup-code.png` });
  await page.fill("#token", process.env.SETUP_TOKEN);
  await page.click("text=Continue");
  await page.waitForSelector("h1:has-text('Main administrator')");
  await page.fill("#admin-n", "A. Ansari");
  await page.fill("#admin-u", "admin");
  await page.fill("#admin-r", "Father");
  await page.fill("#admin-p", PW);
  await page.screenshot({ path: `${SHOTS}/02-setup-admin.png` });
  await page.click("button:has-text('Continue')");
  await page.waitForSelector("h1:has-text('Add family members')");
  if (!(await page.locator("button:has-text('Skip for now')").count())) throw new Error("members step must be skippable");
  // demonstration labels only: added here by the administrator, never created by the application
  const members = [["Mom", "mom", "Mother"], ["Son1", "son1", "Son"], ["Son2", "son2", "Son"], ["Son3", "son3", "Son"], ["Daughter", "daughter", "Daughter"]];
  for (let i = 0; i < members.length; i++) {
    await page.click("button:has-text('Add a family member')");
    await page.fill(`#m${i}-n`, members[i][0]);
    await page.fill(`#m${i}-u`, members[i][1]);
    await page.fill(`#m${i}-r`, members[i][2]);
  }
  await page.screenshot({ path: `${SHOTS}/03-setup-members.png` });
  await page.click("button:has-text('Continue')");
  await page.click("button:has-text('Create 6 accounts')");
  await page.waitForSelector("text=All set");
  const temp = await page.locator("tr:has-text('son1') td.mono").innerText();
  fs.writeFileSync(`${SHOTS}/../../tests/e2e/.son1`, temp);
  await page.click("text=Go to sign in");
});

await step("login page and sign in as the administrator", async () => {
  await page.waitForSelector("text=Welcome back");
  await page.fill("#username", "admin");
  await page.fill("#password", PW);
  await page.screenshot({ path: `${SHOTS}/04-login.png` });
  await page.click("button:has-text('Sign in')");
  await page.waitForSelector("text=Good");
});

await step("upload a scanned passport (synthetic) and process it", async () => {
  await page.click("button:has-text('Upload documents')");
  await page.waitForFunction(() => document.querySelectorAll("#folder-select option").length > 2);
  const opts = await page.locator("#folder-select option").allInnerTexts();
  const samIdx = opts.findIndex((o) => o.includes("Son1"));
  await page.selectOption("#folder-select", { index: samIdx });
  await page.selectOption("#dtype", { label: "Passport" });
  await page.setInputFiles("input[type=file]:not([capture])", process.env.FIXTURE);
  await page.click(".modal button:has-text('Upload 1')");
  await page.waitForSelector(".toast");
  await page.waitForTimeout(8000);
});

await step("passport type is Manual: nothing is recognised until Run OCR is chosen", async () => {
  await page.click("nav >> text=Folders");
  await page.click(".tree-node:has-text('Son1')");
  await page.click(".doc-card:has-text('Passport')");
  await page.click(".detail-pane [role=tab]:has-text('Text (OCR)')");
  await page.waitForSelector(".detail-pane .ocr-panel >> text=OCR: Not processed");
  await page.click(".detail-pane button:has-text('Run OCR…')");
  await page.waitForSelector(".modal:has-text('Text recognition (OCR)')");
  await page.screenshot({ path: `${SHOTS}/05-ocr-run.png` });
  await page.click(".modal button:has-text('Run OCR')");
  await page.waitForSelector(".toast:has-text('Text recognition queued')");
  await page.waitForSelector(".detail-pane >> text=OCR: Needs review", { timeout: 90000 });
});

await step("Overview shows the date, holidays and the recent document", async () => {
  await page.goto(BASE + "/");
  await page.waitForSelector(".ov-grid [data-widget=date] .ov-hijri");
  await page.waitForSelector(".ov-grid [data-widget=calendar] .ov-cal-grid");
  await page.waitForSelector(".ov-grid >> text=Son1 Passport");
  await page.screenshot({ path: `${SHOTS}/06-overview.png` });
});

await step("three-panel folder browser with preview and suggested details", async () => {
  await page.click("nav >> text=Folders");
  await page.click(".tree-node:has-text('Son1')");
  await page.click(".doc-card:has-text('Passport')");
  await page.waitForSelector(".detail-pane >> text=Details");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/07-folders-three-panel.png` });
});

await step("confirm suggested dates -> generated name with years", async () => {
  const btn = page.locator(".detail-pane button:has-text('Confirm all')");
  if (await btn.count()) await btn.click();
  await page.waitForSelector(".detail-pane h2:has-text('(2016–2026)')", { timeout: 15000 });
  await page.screenshot({ path: `${SHOTS}/08-details-confirmed.png` });
});

await step("search with highlighted snippet", async () => {
  await page.fill("#global-search", "sample");
  await page.keyboard.press("Enter");
  await page.waitForSelector("text=Results for");
  await page.screenshot({ path: `${SHOTS}/09-search.png` });
});

await step("notifications settings (admin) render with reminder days", async () => {
  await page.goto(BASE + "/settings/notifications");
  await page.waitForSelector("text=Expiry reminder days");
  await page.screenshot({ path: `${SHOTS}/10-settings-notifications.png` });
});

await step("family & access settings", async () => {
  await page.goto(BASE + "/settings/family");
  await page.waitForSelector("text=Family groups");
  await page.screenshot({ path: `${SHOTS}/11-settings-family.png` });
});

await step("profile page and blue theme applies", async () => {
  await page.goto(BASE + "/settings/account?tab=appearance");
  await page.selectOption("#s-me\\.theme", "blue");
  await page.click("text=Save settings");
  await page.waitForFunction(() => document.documentElement.dataset.theme === "blue");
  await page.goto(BASE + "/settings/account");
  await page.waitForSelector("text=Profile information");
  await page.screenshot({ path: `${SHOTS}/12-profile-blue-theme.png` });
});

await step("help guide renders bundled documentation", async () => {
  await page.goto(BASE + "/help/getting-started");
  await page.waitForSelector(".markdown h1");
  await page.screenshot({ path: `${SHOTS}/13-help.png` });
});

await step("another user keeps their own (green) theme and forced password change", async () => {
  const c2 = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const p2 = await c2.newPage();
  p2.on("pageerror", (e) => errors.push(String(e)));
  await p2.goto(BASE + "/login");
  await p2.fill("#username", "son1");
  await p2.fill("#password", fs.readFileSync("tests/e2e/.son1", "utf8").trim());
  await p2.click("button:has-text('Sign in')");
  await p2.waitForSelector("text=Set your own password");
  await p2.fill("#cur", fs.readFileSync("tests/e2e/.son1", "utf8").trim());
  await p2.fill("#npw", "Son1-Own-Passw0rd");
  await p2.fill("#npw2", "Son1-Own-Passw0rd");
  await p2.click("button:has-text('Change password')");
  await p2.waitForSelector("text=Good");
  const theme = await p2.evaluate(() => document.documentElement.dataset.theme);
  if (theme !== "green") throw new Error("expected green theme for son1, got " + theme);
  await p2.screenshot({ path: `${SHOTS}/14-mobile-overview.png` });
  const overflow = await p2.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (overflow) throw new Error("horizontal overflow on mobile");
  await p2.goto(BASE + "/folders");
  await p2.waitForSelector(".doc-card, .empty");
  await p2.screenshot({ path: `${SHOTS}/15-mobile-folders.png` });
  const manifest = await p2.evaluate(async () => (await fetch("/manifest.webmanifest")).json());
  if (!manifest.icons?.length || manifest.display !== "standalone") throw new Error("manifest incomplete");
  await c2.close();
});

await step("no uncaught page errors", async () => { if (errors.length) throw new Error(errors.join(" | ")); });

await browser.close();
fs.rmSync("tests/e2e/.son1", { force: true });
fs.writeFileSync(`${SHOTS}/e2e-results.json`, JSON.stringify(results, null, 1));
process.exit(results.some((r) => r[0] === "FAIL") ? 1 : 0);
