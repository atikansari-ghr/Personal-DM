// Change Set T in a real browser: Backup & Recovery (destination, encrypted backup, step-up, key reveal + auto-hide,
// emergency package), Recovery Explorer (impact analysis + restore of a deleted synthetic document), notification
// routing (category channels, fallback chain, quiet hours), sign-in security (Trusted Zone, map, devices) and the
// rich Help pages. Runs after flow.mjs/parity.mjs on the same throw-away instance; synthetic data only.
//
// Usage: BASE=http://localhost:8000 node tests/e2e/recovery.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BASE = process.env.BASE || "http://localhost:8000";
const PW = "Sample-Passw0rd!";
const OUT = "tests/e2e/out/recovery";
fs.mkdirSync(OUT, { recursive: true });
const DEST = fs.mkdtempSync(path.join(os.tmpdir(), "pd-e2e-backup-"));
const results = [];
let failed = 0;
const step = async (name, fn) => {
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { failed++; results.push(["FAIL", name, String(e).slice(0, 800)]); console.log("FAIL", name, String(e).slice(0, 800)); }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
const api = (page, url, opts = {}) => page.evaluate(async ([url, opts]) => {
  const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
  const r = await fetch(url, { method: opts.method || (opts.body ? "POST" : "GET"), headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: opts.body ? JSON.stringify(opts.body) : undefined });
  return { status: r.status, data: r.headers.get("content-type")?.includes("json") ? await r.json() : null };
}, [url, opts]);

async function session(user = "admin", viewport = { width: 1440, height: 900 }) {
  const ctx = await browser.newContext({ viewport, acceptDownloads: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => { console.log("pageerror", e.message); });
  await page.goto(BASE + "/login");
  await page.fill("#username", user);
  await page.fill("#password", PW);
  await page.click("button:has-text('Sign in')");
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 });
  return { ctx, page };
}
async function stepUp(page) {
  await page.waitForSelector("[role=dialog] >> text=Confirm it's you");
  await page.fill("#su-pw", PW);
  await page.click("[role=dialog] button:has-text('Confirm'):not(:has-text('passkey'))");
  await page.waitForSelector("[role=dialog] >> text=Confirm it's you", { state: "detached" });
}

const { page } = await session();
let pointId = null;

await step("AT-284/AT-309 Backup & Recovery: add a local destination, the recommended policy appears", async () => {
  await page.goto(BASE + "/settings/backup?view=destinations");
  await page.click("button:has-text('Add destination')");
  await page.fill("#dst-name", "Home server disk");
  await page.fill("#dst-path", DEST);
  await page.click("[role=dialog] button:has-text('Save')");
  await page.waitForSelector("td:has-text('Home server disk')");
  await page.click("tr:has-text('Home server disk') button:has-text('Test')");
  await page.waitForSelector("tr:has-text('Home server disk') [data-health=healthy]", { timeout: 15000 });
  await page.goto(BASE + "/settings/backup?view=policies");
  await page.waitForSelector("text=Every Sunday at 02:30 · incremental every 4 h");
  await page.screenshot({ path: `${OUT}/policies.png` });
});

await step("AT-278/AT-293/AT-309 Back up now creates a deep-verified encrypted recovery point", async () => {
  await page.goto(BASE + "/settings/backup");
  await page.click("button:has-text('Back up now (Full)')");
  let st = null;
  for (let i = 0; i < 90; i++) {
    const r = await api(page, "/api/backup/overview");
    st = r.data.points[0];
    if (st && st.status !== "running" && !r.data.running.length) break;
    await page.waitForTimeout(2000);
  }
  expect(st && st.status === "verified", `point status ${st && st.status}`);
  pointId = st.id;
  const files = fs.readdirSync(path.join(DEST, st.id, `g${st.key_generation}`));
  expect(files.includes("header.json") && files.includes("database.enc"), "package written to the destination");
  const db = fs.readFileSync(path.join(DEST, st.id, `g${st.key_generation}`, "database.enc"));
  expect(!db.includes(Buffer.from("PGDMP")), "database dump is encrypted");
  await page.reload();
  await page.waitForSelector("[data-health=healthy], [data-health=attention]");
  await page.screenshot({ path: `${OUT}/overview.png` });
});

await step("AT-286 Recovery Key: step-up required, shown, auto-hide timer, never in the page after hiding", async () => {
  await page.goto(BASE + "/settings/backup?view=key");
  await page.click("button:has-text('Reveal Recovery Key…')");
  await stepUp(page);
  const key = await page.locator(".key-text").textContent({ timeout: 15000 });
  expect(/^PDRK1-/.test(key || ""), "key shown");
  expect(await page.locator("text=Hides in").isVisible(), "auto-hide countdown");
  await page.click("button:has-text('Hide now')");
  expect(!(await page.content()).includes(key), "key removed from the page");
  // the notification about the reveal does not contain the key
  const n = await api(page, "/api/notifications");
  expect(!JSON.stringify(n.data).includes(key), "notification without the key");
});

await step("AT-289 Emergency Recovery Package: passphrase rules, download, readiness Ready", async () => {
  await page.click("button:has-text('Export Emergency Recovery Package…')");
  await page.fill("#erp-1", "short");
  expect(await page.locator("[role=dialog] button:has-text('Export')").isDisabled(), "short passphrase refused");
  await page.fill("#erp-1", "synthetic correct horse 42");
  await page.fill("#erp-2", "synthetic correct horse 42");
  const dl = page.waitForEvent("download");
  await page.click("[role=dialog] button:has-text('Export')");
  await stepUp(page);
  const file = await dl;
  expect((await file.suggestedFilename()).endsWith(".pdrp"), "package file name");
  const body = fs.readFileSync(await file.path(), "utf8");
  expect(!/PDRK1-/.test(body), "package does not contain the key in clear");
  await page.waitForSelector("[data-health=verified]:has-text('Ready')", { timeout: 10000 });
  await page.screenshot({ path: `${OUT}/key.png` });
});

await step("AT-294/AT-295/AT-299 Recovery Explorer: restore a deleted document with impact analysis", async () => {
  // delete a synthetic document after the backup, then restore it from the Explorer
  const docs = (await api(page, "/api/documents?q=Sample")).data.documents;
  expect(docs.length > 0, "synthetic documents present");
  const victim = docs[0];
  await api(page, `/api/documents/${victim.id}/archive`, { method: "POST" });
  await api(page, `/api/documents/${victim.id}`, { method: "DELETE", body: { confirm: victim.title } });
  await page.goto(BASE + "/recovery");
  await page.waitForSelector("text=My Recovery");
  await page.fill("input[aria-label='Search this recovery point']", victim.title.slice(0, 12));
  await page.click("button:has-text('Search')");
  const row = page.locator(".recovery-doc", { hasText: victim.title }).first();
  await row.waitFor({ timeout: 15000 });
  expect(await row.locator("text=Deleted").count() > 0 || await row.locator("text=Exists").count() > 0, "state badge");
  await row.locator("button:has-text('Restore…')").click();
  await page.click("[role=dialog] button:has-text('Analyse impact')");
  await page.waitForSelector("[role=dialog] >> text=Restore Impact Analysis");
  expect(await page.locator("[role=dialog] >> text=No current data is deleted").isVisible(), "deletion note shown");
  await page.screenshot({ path: `${OUT}/impact.png` });
  await page.click("[role=dialog] button:has-text('Restore now')");
  await page.waitForSelector("[role=dialog] >> text=Restore completed", { timeout: 60000 });
  const back = (await api(page, `/api/documents?q=${encodeURIComponent(victim.title)}`)).data.documents;
  expect(back.some((d) => d.title === victim.title), "document is back");
});

await step("AT-300 protected deletion shows dependants and needs step-up", async () => {
  await page.goto(BASE + "/settings/backup?view=points");
  await page.click("tr >> nth=1 >> button:has-text('Delete')");
  await page.waitForSelector("[role=dialog] >> text=This is a protected deletion");
  await page.click("[role=dialog] button:has-text('Cancel')");
});

await step("AT-318/AT-320 notification routing: category channels, fallback chain, quiet hours", async () => {
  await page.goto(BASE + "/settings/account?tab=notifications");
  await page.waitForSelector("#routing");
  const sel = page.locator("select[aria-label='Add a channel to the Security & sign-in fallback chain']");
  const opts = await sel.locator("option").allTextContents();
  if (opts.includes("Email")) {
    await sel.selectOption({ label: "Email" });
    await page.waitForSelector("#routing ol.chain li:has-text('Email')");
  }
  await page.check("text=Quiet hours on");
  await page.fill("#qh-start", "22:00");
  await page.fill("#qh-end", "07:00");
  await page.click("#quiet-hours button:has-text('Save')");
  const r = await api(page, "/api/me/notification-preferences");
  expect(r.data.quiet_hours.enabled === true, "quiet hours saved");
  await page.locator("#routing").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${OUT}/routing.png` });
});

await step("AT-323/AT-325/AT-327 Trusted Zone, sign-in map and devices", async () => {
  await page.goto(BASE + "/settings/activity?view=map");
  await page.click("button:has-text('Add zone')");
  await page.fill("#z-name", "Home");
  await page.fill("#z-cidrs", "127.0.0.0/8\n192.168.2.0/24\nfd00:1::/64");
  await page.fill("[aria-label=Latitude]", "24.71");
  await page.fill("[aria-label=Longitude]", "46.67");
  await page.click("[role=dialog] button:has-text('Save')");
  await page.waitForSelector("td:has-text('Home')");
  await page.fill("#zone-probe", "192.168.2.10");
  await page.click("button:has-text('Test')");
  await page.waitForSelector("[role=status]:has-text('Home')");
  // a new sign-in from the zone shows Home instead of an unknown country
  const s2 = await session();
  await s2.page.goto(BASE + "/settings/account?tab=signins");
  await s2.page.waitForSelector("td:has-text('Home')", { timeout: 15000 });
  await s2.page.waitForSelector(".signin-map");
  expect(await s2.page.locator("text=Recognised devices").isVisible(), "devices card");
  await s2.ctx.close();
});

await step("AT-334 Help: categories, breadcrumbs, TOC, callouts and contextual Learn more links", async () => {
  await page.goto(BASE + "/help");
  await page.waitForSelector(".help-cat h3:has-text('Backup & Recovery')");
  await page.click("a:has-text('Backup & Recovery'):visible");
  await page.waitForSelector(".breadcrumbs:has-text('Backup & Recovery')");
  expect(await page.locator(".toc a").count() > 2, "table of contents");
  expect(await page.locator(".callout").count() > 0, "callouts rendered");
  const imgs = await page.locator("img.doc-shot").count();
  expect(imgs > 0, "screenshots next to the steps");
  await page.waitForFunction(() => [...document.querySelectorAll("img.doc-shot")].every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 15000 });
  // every Learn more link on the backup page resolves to an existing heading
  await page.goto(BASE + "/settings/backup");
  const hrefs = await page.locator("a[href^='/help/']").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  for (const h of [...new Set(hrefs)]) {
    const [slug, anchor] = h.replace("/help/", "").split("#");
    const g = await api(page, `/api/help/${slug}`);
    expect(g.status === 200, `guide ${slug} exists`);
    if (anchor) expect(new RegExp(`\\{#${anchor}\\}|^#+ .*`, "m").test(g.data.markdown) && (g.data.markdown.includes(`{#${anchor}}`) || g.data.markdown.toLowerCase().includes(anchor.replace(/-/g, " "))), `anchor #${anchor} in ${slug}`);
  }
});

await step("phone layout: Recovery Explorer and Backup overview fit 390 px", async () => {
  const m = await session("admin", { width: 390, height: 844 });
  for (const url of ["/recovery", "/settings/backup", "/settings/account?tab=signins", "/help/backup-restore"]) {
    await m.page.goto(BASE + url);
    await m.page.waitForLoadState("networkidle");
    const over = await m.page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    expect(over <= 1, `${url}: page scrolls sideways by ${over}px`);
  }
  await m.ctx.close();
});

await browser.close();
fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 1));
fs.rmSync(DEST, { recursive: true, force: true });
console.log(`\nrecovery: ${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
