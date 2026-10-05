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

await step("first-run setup wizard creates six accounts", async () => {
  await page.goto(BASE + "/");
  await page.waitForURL(/setup/);
  await page.screenshot({ path: `${SHOTS}/01-setup-code.png` });
  await page.fill("#token", process.env.SETUP_TOKEN);
  await page.click("text=Continue");
  const names = ["Atik Ansari", "JR", "AB Ansari", "N Ansari", "AZ Ansari", "AR Ansari"]; // dad, mom, son1, daughter, son2, son3
  for (let i = 0; i < 6; i++) await page.fill(`#n-${i}`, names[i]);
  await page.fill("#p-0", PW);
  await page.screenshot({ path: `${SHOTS}/02-setup-accounts.png`, fullPage: false });
  await page.click("button:has-text('Continue')");
  await page.click("text=Create accounts");
  await page.waitForSelector("text=All set");
  const temp = await page.locator("tr:has-text('son1') td.mono").innerText();
  fs.writeFileSync(`${SHOTS}/../../tests/e2e/.son1`, temp);
  await page.click("text=Go to sign in");
});

await step("login page and sign in as Dad", async () => {
  await page.waitForSelector("text=Welcome back");
  await page.fill("#username", "dad");
  await page.fill("#password", PW);
  await page.screenshot({ path: `${SHOTS}/03-login.png` });
  await page.click("button:has-text('Sign in')");
  await page.waitForSelector("text=Good");
});

await step("upload a scanned passport (synthetic) and process it", async () => {
  await page.click("button:has-text('Upload documents')");
  await page.waitForFunction(() => document.querySelectorAll("#folder-select option").length > 2);
  const opts = await page.locator("#folder-select option").allInnerTexts();
  const samIdx = opts.findIndex((o) => o.includes("AB Ansari"));
  await page.selectOption("#folder-select", { index: samIdx });
  await page.selectOption("#dtype", { label: "Passport" });
  await page.setInputFiles("input[type=file]:not([capture])", process.env.FIXTURE);
  await page.click(".modal button:has-text('Upload 1')");
  await page.waitForSelector(".toast");
  await page.waitForTimeout(25000);
});

await step("dashboard shows stats, members and recent document", async () => {
  await page.goto(BASE + "/");
  await page.waitForSelector("text=Family library");
  await page.waitForSelector("text=AB Ansari Passport");
  await page.screenshot({ path: `${SHOTS}/04-dashboard.png` });
});

await step("three-panel folder browser with preview and suggested details", async () => {
  await page.click("nav >> text=Folders");
  await page.click(".tree-node:has-text('AB Ansari')");
  await page.click(".doc-card:has-text('Passport')");
  await page.waitForSelector(".detail-pane >> text=Details");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/05-folders-three-panel.png` });
});

await step("confirm suggested dates -> generated name with years", async () => {
  const btn = page.locator(".detail-pane button:has-text('Confirm all')");
  if (await btn.count()) await btn.click();
  await page.waitForSelector(".detail-pane h2:has-text('(2016–2026)')", { timeout: 15000 });
  await page.screenshot({ path: `${SHOTS}/06-details-confirmed.png` });
});

await step("search with highlighted snippet", async () => {
  await page.fill("#global-search", "sample");
  await page.keyboard.press("Enter");
  await page.waitForSelector("text=Results for");
  await page.screenshot({ path: `${SHOTS}/07-search.png` });
});

await step("notifications settings (admin) render with reminder days", async () => {
  await page.goto(BASE + "/settings/notifications");
  await page.waitForSelector("text=Expiry reminder days");
  await page.screenshot({ path: `${SHOTS}/08-settings-notifications.png`, fullPage: true });
});

await step("family & access settings", async () => {
  await page.goto(BASE + "/settings/family");
  await page.waitForSelector("text=Family groups");
  await page.screenshot({ path: `${SHOTS}/09-settings-family.png` });
});

await step("profile page and blue theme applies", async () => {
  await page.goto(BASE + "/settings/account?tab=appearance");
  await page.selectOption("#s-me\\.theme", "blue");
  await page.click("text=Save settings");
  await page.waitForFunction(() => document.documentElement.dataset.theme === "blue");
  await page.goto(BASE + "/settings/account");
  await page.waitForSelector("text=Profile information");
  await page.screenshot({ path: `${SHOTS}/10-profile-blue-theme.png` });
});

await step("help guide renders bundled documentation", async () => {
  await page.goto(BASE + "/help/getting-started");
  await page.waitForSelector(".markdown h1");
  await page.screenshot({ path: `${SHOTS}/11-help.png` });
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
  await p2.screenshot({ path: `${SHOTS}/12-mobile-dashboard.png`, fullPage: true });
  const overflow = await p2.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (overflow) throw new Error("horizontal overflow on mobile");
  await p2.goto(BASE + "/folders");
  await p2.waitForSelector(".doc-card, .empty");
  await p2.screenshot({ path: `${SHOTS}/13-mobile-folders.png` });
  const manifest = await p2.evaluate(async () => (await fetch("/manifest.webmanifest")).json());
  if (!manifest.icons?.length || manifest.display !== "standalone") throw new Error("manifest incomplete");
  await c2.close();
});

await step("no uncaught page errors", async () => { if (errors.length) throw new Error(errors.join(" | ")); });

await browser.close();
fs.rmSync("tests/e2e/.son1", { force: true });
fs.writeFileSync(`${SHOTS}/e2e-results.json`, JSON.stringify(results, null, 1));
process.exit(results.some((r) => r[0] === "FAIL") ? 1 : 0);
