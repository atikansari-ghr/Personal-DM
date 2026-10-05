// Browser checks for the change set "UI, import, notifications, backup and mobile/PWA corrections" and the
// full-page viewer (AT-61..AT-84 parts that need a real browser), plus a screen-by-screen desktop/tablet/mobile audit.
// Runs after flow.mjs against the same instance (uses the "dad" account and Sam Sample's area). Synthetic data only.
// Usage: BASE=http://localhost:8000 PARITY=/tmp/parity node tests/e2e/parity.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE || "http://localhost:8000";
const FIX = process.env.PARITY;
const SHOTS = process.env.PUBLIC_SHOTS || "docs/images/screenshots";
const PW = "Sample-Passw0rd!";
fs.mkdirSync(SHOTS, { recursive: true });
const results = [];
const step = async (name, fn) => {
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { results.push(["FAIL", name, String(e).slice(0, 400)]); console.log("FAIL", name, String(e).slice(0, 400)); }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
const errors = [];
const foreign = new Set();
const watch = (page, label) => {
  page.on("pageerror", (e) => errors.push(`${label}: ${e}`));
  page.on("console", (m) => m.type() === "error" && !/favicon|401|403|404|Failed to load resource/.test(m.text()) && errors.push(`${label}: ${m.text()}`));
  page.on("request", (r) => { const u = new URL(r.url()); if (!["localhost", "127.0.0.1"].includes(u.hostname) && u.protocol.startsWith("http")) foreign.add(u.host); });
};
const api = (page, url, opts = {}) => page.evaluate(async ([url, opts]) => {
  const csrf = (document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "";
  const r = await fetch(url, { method: opts.method || (opts.body ? "POST" : "GET"), headers: { "Content-Type": "application/json", "X-CSRFToken": decodeURIComponent(csrf) }, body: opts.body ? JSON.stringify(opts.body) : undefined });
  return { status: r.status, data: r.headers.get("content-type")?.includes("json") ? await r.json() : null };
}, [url, opts]);

async function signIn(ctx, user = "dad", pw = PW) {
  const page = await ctx.newPage();
  watch(page, user);
  await page.goto(BASE + "/login");
  await page.fill("#username", user);
  await page.fill("#password", pw);
  await page.click("button:has-text('Sign in')");
  await page.waitForSelector("text=Good");
  return page;
}

// ------------------------------------------------------------------ desktop
const desk = await browser.newContext({ viewport: { width: 1366, height: 900 } });
const page = await signIn(desk);
const ids = {};

await step("setup: synthetic folders and files in Sam Sample's area", async () => {
  await api(page, "/api/settings", { method: "PUT", body: { values: { "me.theme": "green" } } }); // default look for screenshots
  await page.reload();
  const f = (await api(page, "/api/folders")).data.folders;
  const sam = f.find((x) => x.kind === "personal_root" && x.owner_user?.display_name === "Sam Sample");
  ids.sam = sam.id;
  ids.parity = (await api(page, "/api/folders", { body: { parent: sam.id, name: "Parity" } })).data.id;
  ids.travel = (await api(page, "/api/folders", { body: { parent: ids.parity, name: "Travel" } })).data.id;
  ids.visa = (await api(page, "/api/folders", { body: { parent: ids.travel, name: "Visa" } })).data.id;
  await page.goto(`${BASE}/folders/${ids.parity}`);
  await page.click("button:has-text('Upload')");
  const files = fs.readdirSync(path.join(FIX, "files")).map((n) => path.join(FIX, "files", n));
  await page.setInputFiles(".modal input[type=file]:not([capture])", files);
  await page.click(`.modal button:has-text('Upload ${files.length}')`);
  await page.waitForSelector(".toast");
  for (let i = 0; i < 90; i++) {
    const docs = (await api(page, `/api/documents?folder=${ids.parity}&limit=50`)).data.documents;
    if (docs.length === files.length && docs.every((d) => !["queued", "processing"].includes(d.state))) {
      for (const d of docs) ids[d.title] = d.id;
      return;
    }
    await page.waitForTimeout(1000);
  }
  throw new Error("processing did not finish");
});

await step("AT-61 signed-in user's own area is identified at the top of the tree", async () => {
  await page.goto(BASE + "/folders");
  await page.waitForSelector(".my-area");
  const txt = await page.locator(".my-area").innerText();
  expect(txt.includes("My Documents") && txt.includes("Atik Ansari"), `my-area text: ${txt}`);
  await page.waitForSelector(".tree-node:has-text('My Documents — Atik Ansari')");
  expect(await page.locator(".tree-node:has-text('Sam Sample') .avatar").count() > 0, "member areas show an avatar");
});

await step("AT-62 file-type icons with readable labels in list and grid", async () => {
  await page.goto(`${BASE}/folders/${ids.parity}`);
  await page.waitForSelector(".doc-card");
  for (const k of ["pdf", "jpeg", "png", "webp", "text", "word"]) expect(await page.locator(`.list-pane .ftype-${k}`).count() > 0, `missing ${k} icon`);
  const label = await page.locator(".list-pane .ftype-jpeg").first().getAttribute("aria-label");
  expect(label === "JPEG image", `label ${label}`);
  await page.screenshot({ path: `${SHOTS}/folders-file-types.png` });
  await page.click("button[aria-label='Grid view']");
  await page.waitForSelector(".doc-grid");
  expect(await page.locator(".doc-grid .ftype").count() >= 6, "grid icons");
  await page.click("button[aria-label='List view']");
});

await step("AT-72 drag a document onto a sub-folder (chip and tree)", async () => {
  await page.goto(`${BASE}/folders/${ids.parity}`);
  await page.dragAndDrop(".doc-card:has-text('Sample notes')", ".list-pane a.btn:has-text('Travel')");
  await page.waitForSelector(".toast:has-text('moved')");
  await page.waitForFunction(() => ![...document.querySelectorAll(".doc-card")].some((e) => e.textContent.includes("Sample notes")));
  // tree target (the open folder's sub-folders are listed in the tree)
  await page.dragAndDrop(".doc-card:has-text('Sample scan')", ".tree-node:has-text('Travel')");
  await page.waitForFunction(() => ![...document.querySelectorAll(".doc-card")].some((e) => e.textContent.includes("Sample scan")));
  const moved = (await api(page, `/api/documents?folder=${ids.travel}`)).data.documents.map((d) => d.title);
  expect(moved.includes("Sample notes") && moved.includes("Sample scan"), `travel has ${moved}`);
});

await step("AT-73 drag a folder; a drop into its own sub-folder is refused", async () => {
  await page.goto(`${BASE}/folders/${ids.travel}`);
  await page.waitForSelector(".tree-node:has-text('Visa')"); // the open folder shows its sub-folders
  await page.dragAndDrop(".tree-node:has-text('Visa')", ".tree-node:has-text('Parity')");
  await page.waitForSelector(".toast:has-text('Folder moved')");
  let visa = (await api(page, `/api/folders/${ids.visa}`)).data;
  expect(visa.parent === ids.parity, "visa moved under Parity");
  await page.goto(`${BASE}/folders/${ids.parity}`);
  await page.waitForSelector(".tree-node:has-text('Visa')");
  await page.dragAndDrop(".tree-node:has-text('Parity')", ".tree-node:has-text('Visa')");
  await page.waitForTimeout(800);
  const parity = (await api(page, `/api/folders/${ids.parity}`)).data;
  expect(parity.parent === ids.sam, "Parity must not move into its own sub-folder");
});

await step("AT-75 Move to… with the folder picker (desktop)", async () => {
  await page.goto(`${BASE}/folders/${ids.parity}`);
  await page.click("button[aria-label='More actions for Sample letter']");
  await page.click("[role=menuitem]:has-text('Move to…')");
  await page.waitForSelector(".folder-picker");
  expect(await page.locator(".picker-pick:has-text('Parity')").isDisabled(), "current folder is disabled (already here)");
  await page.click(".picker-pick:has-text('Visa')");
  await page.click(".modal button:has-text('Next')");
  await page.click(".modal button:has-text('Move')");
  await page.waitForSelector(".toast:has-text('moved')");
  const inVisa = (await api(page, `/api/documents?folder=${ids.visa}`)).data.documents.map((d) => d.title);
  expect(inVisa.includes("Sample letter"), "moved to Visa");
});

await step("AT-81 PDF viewer: zoom, percentage, fit page/width, 100%, pages, keyboard, resize", async () => {
  const before = (await api(page, `/api/documents/${ids["Sample policy (3 pages)"]}`)).data.current_version.sha256;
  await page.goto(`${BASE}/documents/${ids["Sample policy (3 pages)"]}`);
  await page.waitForSelector(".viewer .pdf-page canvas");
  const zoom = () => page.locator(".zoom-value").innerText();
  await page.click(".viewer-toolbar button:has-text('100%')");
  expect(await zoom() === "100%", "reset to 100%");
  await page.click("button[aria-label='Zoom in']");
  expect(await zoom() === "110%", `zoom in -> ${await zoom()}`);
  await page.click("button[aria-label='Zoom out']");
  await page.click("button[aria-label='Zoom out']");
  expect(await zoom() === "90%", `zoom out -> ${await zoom()}`);
  await page.click(".viewer-toolbar button:has-text('Fit page')");
  expect(await page.locator(".viewer-toolbar button:has-text('Fit page')").getAttribute("aria-pressed") === "true", "fit page pressed");
  const fitPage = await zoom();
  await page.click(".viewer-toolbar button:has-text('Fit width')");
  const fitWidth = await zoom();
  expect(fitPage !== fitWidth, `fit page ${fitPage} vs width ${fitWidth}`);
  expect(await page.locator(".viewer-toolbar >> text=Page 1 / 3").count() === 1, "page counter");
  await page.click("button[aria-label='Next page']");
  await page.waitForSelector(".viewer-toolbar >> text=Page 2 / 3");
  // pages are drawn shortly after each zoom change; wait until the first page shows dark (text) pixels
  await page.waitForFunction(() => {
    const c = document.querySelector(".pdf-page canvas");
    if (!c || !c.width) return false;
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 0 && d[i] < 200) return true;
    return false;
  }, null, { timeout: 10000 });
  await page.locator(".viewer").focus();
  await page.click(".viewer-toolbar button:has-text('100%')");
  await page.keyboard.press("+");
  expect(await zoom() === "110%", "keyboard + zooms");
  await page.keyboard.press("0");
  expect(await zoom() === "100%", "keyboard 0 resets");
  await page.click(".viewer-toolbar button:has-text('Fit width')");
  const wide = await zoom();
  await page.setViewportSize({ width: 900, height: 900 });
  await page.waitForTimeout(400);
  expect(await zoom() !== wide, "fit width recalculates after resize");
  await page.setViewportSize({ width: 1366, height: 900 });
  expect(await page.locator(".viewer-toolbar button:has-text('Full screen')").count() === 1, "full screen control");
  expect((await page.locator(".viewer-toolbar a[aria-label=Download]").getAttribute("href")).includes("download=1"), "download link");
  await page.screenshot({ path: `${SHOTS}/document-viewer.png` });
  const after = (await api(page, `/api/documents/${ids["Sample policy (3 pages)"]}`)).data.current_version.sha256;
  expect(before === after, "the stored original is never changed by viewing");
});

await step("AT-82 image viewer keeps the aspect ratio and scrolls when zoomed", async () => {
  for (const name of ["Sample diagram", "Sample photo", "Sample scan"]) {
    const id = ids[name] || (await api(page, `/api/documents?folder=${ids.travel}`)).data.documents.find((d) => d.title === name)?.id;
    await page.goto(`${BASE}/documents/${id}`);
    await page.waitForSelector(".viewer-stage img");
    await page.click(".viewer-toolbar button:has-text('100%')");
    for (let i = 0; i < 4; i++) await page.click("button[aria-label='Zoom in']");
    const m = await page.evaluate(() => {
      const img = document.querySelector(".viewer-stage img");
      const s = document.querySelector(".viewer-scroll");
      return { ratio: img.getBoundingClientRect().width / img.getBoundingClientRect().height, natural: img.naturalWidth / img.naturalHeight, scrolls: s.scrollHeight > s.clientHeight || s.scrollWidth > s.clientWidth };
    });
    expect(Math.abs(m.ratio - m.natural) < 0.01, `${name}: aspect ${m.ratio} vs ${m.natural}`);
    expect(m.scrolls, `${name}: scrollable at high zoom`);
  }
});

await step("AT-84 damaged file fails safely; previews need a session; no external viewer", async () => {
  await page.goto(`${BASE}/documents/${ids["Sample damaged"]}`);
  await page.waitForSelector(".viewer-error, .empty, .viewer");
  await page.waitForTimeout(1500);
  expect(await page.locator("text=Page not found").count() === 0, "page renders");
  const anon = await browser.newContext();
  const ap = await anon.newPage();
  const r = await ap.request.get(`${BASE}/api/documents/${ids["Sample policy (3 pages)"]}/preview`);
  expect([401, 403].includes(r.status()), `anonymous preview status ${r.status()}`);
  await anon.close();
  expect(foreign.size === 0, `requests to other sites: ${[...foreign].join(", ")}`);
});

await step("AT-65/66 dashboard widgets: tick and order visually", async () => {
  await page.goto(BASE + "/settings/account?tab=appearance");
  await page.waitForSelector(".widget-editor");
  await page.locator(".widget-item:has-text('Storage used') input[type=checkbox]").uncheck();
  for (let i = 0; i < 5; i++) await page.click("button[aria-label='Move Recent documents up']").catch(() => undefined);
  await page.screenshot({ path: `${SHOTS}/settings-dashboard-widgets.png` });
  await page.click("text=Save settings");
  await page.waitForSelector(".toast:has-text('Settings saved')");
  await page.goto(BASE + "/");
  await page.waitForSelector(".dash-grid");
  expect(await page.locator(".stat:has-text('Storage used')").count() === 0, "storage widget hidden");
  const order = await page.evaluate(() => [...document.querySelectorAll(".dash-grid h2")].map((h) => h.textContent));
  expect(order.findIndex((t) => t.startsWith("Recent documents")) < order.findIndex((t) => t.startsWith("Family library")), `order ${order}`);
  await page.screenshot({ path: `${SHOTS}/dashboard.png` });
});

await step("AT-68 optional notification matrix persists; critical events locked", async () => {
  await page.goto(BASE + "/settings/account?tab=notifications");
  await page.waitForSelector("table.matrix");
  const box = page.locator("input[aria-label='OCR / processing finished by In-app']");
  await box.click();
  await page.waitForFunction(() => document.querySelector("input[aria-label='OCR / processing finished by In-app']")?.checked);
  await page.reload();
  await page.waitForSelector("table.matrix");
  expect(await page.locator("input[aria-label='OCR / processing finished by In-app']").isChecked(), "choice persisted");
  expect(await page.locator(".crit-list li").count() > 3, "critical list");
  await page.screenshot({ path: `${SHOTS}/notifications.png`, fullPage: true });
});

await step("AT-71 backup frequency shows the right fields and the next run", async () => {
  await page.goto(BASE + "/settings/storage");
  await page.waitForSelector("#s-backup\\.frequency");
  await page.selectOption("#s-backup\\.frequency", "weekly");
  await page.waitForSelector("#s-backup\\.weekday");
  expect(await page.locator("#s-backup\\.month_day").count() === 0, "month day hidden for weekly");
  await page.selectOption("#s-backup\\.frequency", "monthly");
  await page.waitForSelector("#s-backup\\.month_day");
  await page.fill("#s-backup\\.month_day", "31");
  await page.click("section.card:has(#s-backup\\.frequency) button:has-text('Save settings')");
  await page.waitForSelector(".toast:has-text('Settings saved')");
  await page.reload();
  await page.waitForSelector("text=Monthly on day 31");
  await page.screenshot({ path: `${SHOTS}/settings-backup.png`, fullPage: true });
  await api(page, "/api/settings", { method: "PUT", body: { values: { "backup.frequency": "daily", "backup.month_day": 1 } } });
});

await step("AT-63/64 import into a chosen sub-folder with the exact final hierarchy", async () => {
  await page.goto(BASE + "/imports/new");
  await page.setInputFiles("input[type=file][webkitdirectory]", path.join(FIX, "import"));
  await page.waitForURL(/\/imports\/[0-9a-f-]+/);
  await page.selectOption("select[aria-label='Action for Old']", "user");
  await page.selectOption("select[aria-label='Person for Old']", { label: "Sam Sample" });
  await page.click("button[aria-label='Destination sub-folder for Old']");
  await page.click(".modal .picker-pick:has-text('Parity')");
  await page.click(".modal button:has-text('Done')");
  await page.locator("label:has-text('keep “Old” as a folder') input").check();
  await page.click("button:has-text('Check & preview')");
  await page.waitForSelector(".import-tree");
  const tree = await page.locator(".import-tree").innerText();
  expect(tree.includes("Address Update 22July2026") && tree.includes("new") && tree.includes("existing"), tree);
  await page.screenshot({ path: `${SHOTS}/import-folder.png`, fullPage: true });
  await page.click("button:has-text('Start import')");
  await page.waitForSelector("text=Open folders", { timeout: 30000 });
  const f = (await api(page, "/api/folders")).data.folders;
  const old = f.find((x) => x.name === "Old" && x.parent === ids.parity);
  expect(old && f.some((x) => x.name === "Address Update 22July2026" && x.parent === old.id), "hierarchy recreated under Parity / Old");
});

await step("screens for the README (desktop)", async () => {
  await page.goto(`${BASE}/folders/${ids.parity}/${ids["Sample policy (3 pages)"]}`);
  await page.waitForSelector(".detail-pane .viewer canvas");
  await page.screenshot({ path: `${SHOTS}/folders-preview.png` });
  for (const [file, url, wait] of [["settings-security-passkeys.png", "/settings/account?tab=security", "text=Passkeys"],
    ["local-ai.png", "/settings/ai", "text=Local AI"], ["login-audit.png", "/settings/activity?view=logins", "text=Login audit"],
    ["security-access.png", "/settings/security", "text=Geographic access control"]]) {
    await page.goto(BASE + url);
    await page.waitForSelector(wait);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SHOTS}/${file}` });
  }
  const anon = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const lp = await anon.newPage();
  await lp.goto(BASE + "/login");
  await lp.waitForSelector("#username");
  await lp.screenshot({ path: `${SHOTS}/login.png` });
  await anon.close();
});

// ------------------------------------------------------------------ tablet / mobile parity
const ROUTES = ["/", "/folders", `/folders/${ids.parity}`, `/documents/${ids["Sample policy (3 pages)"]}`, "/search?q=sample", "/shared",
  "/offline", "/notifications", "/archive", "/settings/account", "/settings/account?tab=security", "/settings/account?tab=appearance",
  "/settings/account?tab=notifications", "/settings/family", "/settings/notifications", "/settings/storage", "/settings/security",
  "/settings/ai", "/settings/activity?view=logins", "/assistant", "/imports/new", "/help/getting-started"];
const VIEWPORTS = [["tablet", 820, 1180], ["mobile-portrait", 390, 844], ["mobile-landscape", 844, 390]];
const state = await desk.storageState();

for (const [vname, w, h] of VIEWPORTS) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, isMobile: vname !== "tablet", hasTouch: true, storageState: state });
  const mp = await ctx.newPage();
  watch(mp, vname);
  await step(`AT-76/77 ${vname}: every screen renders without horizontal overflow`, async () => {
    const bad = [];
    for (const r of ROUTES) {
      await mp.goto(BASE + r);
      await mp.waitForLoadState("networkidle");
      await mp.waitForTimeout(250);
      const o = await mp.evaluate(() => ({ over: document.documentElement.scrollWidth - window.innerWidth, nf: !!document.querySelector("h1")?.textContent?.includes("Page not found") }));
      if (o.over > 1) bad.push(`${r} overflows by ${o.over}px`);
      if (o.nf) bad.push(`${r} not found`);
    }
    expect(!bad.length, bad.join("; "));
  });
  await step(`AT-83 ${vname}: viewer controls are reachable and large enough`, async () => {
    await mp.goto(`${BASE}/documents/${ids["Sample policy (3 pages)"]}`);
    await mp.waitForSelector(".viewer .pdf-page canvas");
    // the toolbar may scroll sideways on phones: every control must be reachable by scrolling it into view
    const boxes = await mp.evaluate(() => [...document.querySelectorAll(".viewer-toolbar button, .viewer-toolbar a")].map((b) => { b.scrollIntoView({ block: "nearest", inline: "nearest" }); const r = b.getBoundingClientRect(); return { t: b.textContent || b.getAttribute("aria-label"), w: r.width, h: r.height, right: r.right, vw: window.innerWidth }; }));
    const rows = await mp.evaluate(() => { const tb = document.querySelector(".viewer-toolbar"); return Math.round(tb.getBoundingClientRect().height / 40); });
    expect(rows <= 2, `toolbar uses ${rows} rows`);
    const small = boxes.filter((b) => b.w < 24 || b.h < 24).map((b) => b.t);
    const off = boxes.filter((b) => b.right > b.vw + 1).map((b) => b.t);
    expect(!small.length, `small targets: ${small}`);
    expect(!off.length, `off-screen: ${off}`);
    const z0 = await mp.locator(".zoom-value").innerText();
    await mp.tap("button[aria-label='Zoom in']");
    expect(await mp.locator(".zoom-value").innerText() !== z0, "tap zooms");
    await mp.tap(".viewer-toolbar button:has-text('Fit width')");
    if (vname === "mobile-portrait") await mp.screenshot({ path: `${SHOTS}/mobile-viewer.png` });
  });
  if (vname !== "tablet") {
    await step(`AT-75 ${vname}: Move to… by touch, and back navigation`, async () => {
      await mp.goto(`${BASE}/folders/${ids.parity}`);
      await mp.waitForSelector(".doc-card");
      const name = vname === "mobile-portrait" ? "Sample photo" : "Sample diagram";
      await mp.tap(`button[aria-label='More actions for ${name}']`);
      await mp.tap("[role=menuitem]:has-text('Move to…')");
      await mp.tap(".picker-pick:has-text('Travel')");
      await mp.tap(".modal button:has-text('Next')");
      await mp.tap(".modal button:has-text('Move')");
      await mp.waitForSelector(".toast:has-text('moved')");
      await mp.tap(".doc-card >> nth=0");
      await mp.waitForSelector("text=Back to folder");
      await mp.tap("text=Back to folder");
      await mp.waitForSelector(".list-pane .doc-card");
      if (vname === "mobile-portrait") await mp.screenshot({ path: `${SHOTS}/mobile-folders.png` });
    });
  }
  if (vname === "mobile-portrait") {
    await step("AT-78 account preferences changed on desktop appear on mobile and back", async () => {
      await mp.goto(BASE + "/");
      await mp.waitForSelector(".dash-grid");
      expect(await mp.locator(".stat:has-text('Storage used')").count() === 0, "widget choice synced to mobile");
      await mp.screenshot({ path: `${SHOTS}/mobile-dashboard.png`, fullPage: true });
      await api(mp, "/api/settings", { method: "PUT", body: { values: { "me.theme": "blue" } } });
      await page.goto(BASE + "/");
      await page.waitForFunction(() => document.documentElement.dataset.theme === "blue");
      await api(page, "/api/settings", { method: "PUT", body: { values: { "me.theme": "green", "me.dashboard_widgets": ["documents", "members", "expiring", "storage", "review", "family", "saved_views", "recent", "upcoming", "review_queue", "backup"] } } });
    });
  }
  await ctx.close();
}

await step("no uncaught page errors", async () => { expect(!errors.length, errors.join(" | ")); });
await browser.close();
fs.writeFileSync(process.env.PARITY_REPORT || "docs/parity-report.json", JSON.stringify(results, null, 1));
process.exit(results.some((r) => r[0] === "FAIL") ? 1 : 0);
