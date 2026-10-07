// Browser checks for the change set "UI, import, notifications, backup and mobile/PWA corrections" and the
// full-page viewer (AT-61..AT-84 parts that need a real browser), plus a screen-by-screen desktop/tablet/mobile audit.
// Runs after flow.mjs against the same instance (uses the "admin" account and Son1's area). Synthetic data only.
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

// Fake weather provider (Open-Meteo-shaped answers with synthetic values) for the weather widget.
import http from "node:http";
const wxServer = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  const days = [...Array(5)].map((_, i) => new Date(Date.now() + i * 864e5).toISOString().slice(0, 10));
  const body = u.pathname.endsWith("/search")
    ? { results: [{ name: "Riyadh", country: "Saudi Arabia", country_code: "SA", admin1: "Riyadh Region", latitude: 24.69, longitude: 46.72, timezone: "Asia/Riyadh" }] }
    : { current: { temperature_2m: 41, weather_code: 1, relative_humidity_2m: 10, wind_speed_10m: 12 },
        daily: { time: days, weather_code: [1, 0, 2, 3, 1], temperature_2m_max: [42, 43, 41, 40, 39], temperature_2m_min: [29, 30, 28, 27, 26] } };
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
});
await new Promise((r) => wxServer.listen(0, "127.0.0.1", r));
const WX = `http://127.0.0.1:${wxServer.address().port}`;

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

async function signIn(ctx, user = "admin", pw = PW) {
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
const desk = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await signIn(desk);
const ids = {};

await step("setup: synthetic folders and files in Son1's area", async () => {
  await api(page, "/api/settings", { method: "PUT", body: { values: { "me.theme": "green" } } }); // default look for screenshots
  await page.reload();
  const f = (await api(page, "/api/folders")).data.folders;
  const sam = f.find((x) => x.kind === "personal_root" && x.owner_user?.display_name === "Son1");
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
  expect(txt.includes("My Documents") && txt.includes("A. Ansari"), `my-area text: ${txt}`);
  await page.waitForSelector(".tree-node:has-text('My Documents — A. Ansari')");
  expect(await page.locator(".tree-node:has-text('Son1') .avatar").count() > 0, "member areas show an avatar");
});

await step("AT-62 file-type icons with readable labels in list and grid", async () => {
  await page.goto(`${BASE}/folders/${ids.parity}`);
  await page.waitForSelector(".doc-card");
  for (const k of ["pdf", "jpeg", "png", "webp", "text", "word"]) expect(await page.locator(`.list-pane .ftype-${k}`).count() > 0, `missing ${k} icon`);
  const label = await page.locator(".list-pane .ftype-jpeg").first().getAttribute("aria-label");
  expect(label === "JPEG image", `label ${label}`);
  await page.screenshot({ path: `${SHOTS}/folders-file-types.png` });
  await page.click("button[aria-label='Thumbnails view']");
  await page.waitForSelector(".doc-grid");
  expect(await page.locator(".doc-grid .ftype").count() >= 6, "grid icons");
  await page.click("button[aria-label='List view']");
});

await step("AT-92 own library on top and expanded; other areas collapsed", async () => {
  const fresh = await desk.newPage();
  watch(fresh, "landing");
  await fresh.goto(BASE + "/folders");
  await fresh.waitForSelector(".tree-node");
  const mine = (await api(fresh, "/api/folders")).data.folders.find((x) => x.kind === "personal_root" && x.owner_user?.display_name === "A. Ansari");
  await fresh.waitForURL(new RegExp(`/folders/${mine.id}`));
  const first = await fresh.locator("[role=tree] > li >> nth=0").innerText();
  expect(first.startsWith("My Documents — A. Ansari") || first.includes("My Documents — A. Ansari"), `first tree item: ${first.slice(0, 60)}`);
  const samItem = fresh.locator("[role=tree] li[role=treeitem]:has(> .tree-node:has-text('Son1'))").first();
  expect(await samItem.getAttribute("aria-expanded") === "false", "another member's area is not expanded automatically");
  await fresh.close();
});

await step("AT-85 overflow menus are not clipped, stay in the viewport and work with the keyboard", async () => {
  await page.goto(`${BASE}/folders/${ids.parity}`);
  await page.waitForSelector(".doc-card");
  await page.click("button[aria-label='Folder actions']");
  const menu = page.locator(".menu-pop[role=menu]");
  await menu.waitFor();
  const check = async () => page.evaluate(() => {
    const m = document.querySelector(".menu-pop");
    const r = m.getBoundingClientRect();
    const items = [...m.querySelectorAll("[role=menuitem]")];
    const topmost = items.every((it) => { const b = it.getBoundingClientRect(); const el = document.elementFromPoint(b.left + 8, b.top + b.height / 2); return el && it.contains(el); });
    return { inside: r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight, topmost, n: items.length, parent: m.parentElement === document.body };
  });
  let c = await check();
  expect(c.inside && c.topmost && c.parent && c.n >= 6, `folder menu ${JSON.stringify(c)}`);
  for (const t of ["Open", "Rename…", "Change icon…", "Move to…", "Share / who has access", "Archive folder…"]) expect(await menu.locator(`[role=menuitem]:text-is('${t}')`).count() === 1, `folder menu item ${t}`);
  await page.screenshot({ path: `${SHOTS}/folder-actions-menu.png` });
  // one menu at a time
  await page.click("button[aria-label='More actions for Sample policy (3 pages)']");
  expect(await page.locator(".menu-pop").count() === 1, "opening a row menu closes the folder menu");
  c = await check();
  expect(c.inside && c.topmost, `row menu ${JSON.stringify(c)}`);
  for (const t of ["Open", "Rename…", "Move to…", "Download", "Share…", "Archive…", "Delete permanently…"]) expect(await page.locator(`.menu-pop [role=menuitem]:text-is('${t}')`).count() === 1, `document menu item ${t}`);
  // outside click closes
  await page.mouse.click(5, 300);
  expect(await page.locator(".menu-pop").count() === 0, "outside click closes");
  // keyboard: open with Enter, move with arrows, Escape returns focus
  await page.focus("button[aria-label='More actions for Sample policy (3 pages)']");
  await page.keyboard.press("Enter");
  await page.waitForSelector(".menu-pop");
  expect(await page.evaluate(() => document.activeElement?.textContent) === "Open", "first item focused");
  await page.keyboard.press("ArrowDown");
  expect(await page.evaluate(() => document.activeElement?.textContent) === "Rename…", "arrow moves");
  await page.keyboard.press("Escape");
  expect(await page.locator(".menu-pop").count() === 0, "Escape closes");
  expect(await page.evaluate(() => document.activeElement?.getAttribute("aria-label")) === "More actions for Sample policy (3 pages)", "focus returns to the trigger");
  // a menu near the bottom edge opens upwards inside the viewport
  await page.setViewportSize({ width: 1366, height: 520 });
  const last = page.locator(".list-pane .doc-card").last();
  await last.scrollIntoViewIfNeeded();
  await last.locator("button[aria-haspopup=menu]").click();
  c = await check();
  expect(c.inside, `bottom menu ${JSON.stringify(c)}`);
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1366, height: 900 });
});

await step("AT-86 rename and archive a document from its menu (with confirmation)", async () => {
  await page.goto(`${BASE}/folders/${ids.parity}`);
  const up = await page.evaluate(async (folder) => {
    const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
    const fd = new FormData();
    fd.set("folder", folder);
    fd.append("files", new File(["synthetic note to archive"], "to-archive.txt", { type: "text/plain" }));
    const r = await fetch("/api/documents", { method: "POST", body: fd, headers: { "X-CSRFToken": csrf } });
    return (await r.json()).documents[0];
  }, ids.parity);
  await page.reload();
  await page.click(`button[aria-label='More actions for ${up.title}']`);
  await page.click(".menu-pop [role=menuitem]:text-is('Rename…')");
  await page.fill("#dname", "Sample note renamed");
  await page.click(".modal button:has-text('Rename')");
  await page.waitForSelector(".doc-card:has-text('Sample note renamed')");
  await page.click("button[aria-label='More actions for Sample note renamed']");
  await page.click(".menu-pop [role=menuitem]:text-is('Archive…')");
  await page.waitForSelector(".modal:has-text('Archive document')");
  await page.click(".modal button:has-text('Archive')");
  await page.waitForSelector(".toast:has-text('Document archived')");
  await page.waitForFunction(() => ![...document.querySelectorAll(".doc-card")].some((e) => e.textContent.includes("Sample note renamed")));
  const log = (await api(page, `/api/audit?action=document.archive&target=${up.id}`)).data;
  expect(log.total >= 1, "archive recorded in the audit log");
});

await step("AT-87/88 sub-folders get the standard icon; icon picker and reset", async () => {
  await page.goto(`${BASE}/folders/${ids.parity}`);
  await page.click("button[aria-label='Folder actions']");
  await page.click(".menu-pop [role=menuitem]:text-is('New subfolder…')");
  await page.fill("#fname", "Passport copies");
  await page.click(".modal button:has-text('Create')");
  await page.waitForFunction((old) => /\/folders\/[0-9a-f-]+$/.test(location.pathname) && !location.pathname.endsWith(old), ids.parity);
  const id = page.url().split("/").pop();
  expect(id !== ids.parity, "navigated to the new folder");
  let f = (await api(page, `/api/folders/${id}`)).data;
  expect(f.emoji === "📁" && !f.emoji_is_custom, `default icon ${f.emoji}`);
  await page.click("button[aria-label='Folder actions']");
  await page.click(".menu-pop [role=menuitem]:text-is('Change icon…')");
  await page.click(".modal .emoji-grid button[aria-label='passport']");
  await page.click(".modal button:has-text('Save')");
  await page.waitForSelector(".toast:has-text('Icon changed')");
  f = (await api(page, `/api/folders/${id}`)).data;
  expect(f.emoji === "🛂" && f.emoji_is_custom, "custom icon");
  await page.click("button[aria-label='Folder actions']");
  await page.click(".menu-pop [role=menuitem]:text-is('Change icon…')");
  await page.click(".modal button:has-text('Reset to default')");
  await page.waitForSelector(".toast:has-text('Default icon restored')");
  f = (await api(page, `/api/folders/${id}`)).data;
  expect(f.emoji === "📁" && !f.emoji_is_custom, "reset to default");
  ids.passportCopies = id;
});

await step("AT-89 list, thumbnails and details views; sorting; preference syncs", async () => {
  try {
  await page.goto(`${BASE}/folders/${ids.parity}`);
  await page.click("button[aria-label='Details view']");
  await page.waitForSelector("table.details-table");
  await page.click("table.details-table th button:has-text('Name')");
  // the header state changes at once; the rows follow when the server returns the new order
  const ordered = (dir) => page.waitForFunction((dir) => {
    const names = [...document.querySelectorAll("table.details-table tbody .doc-open")].map((e) => e.textContent.toLowerCase());
    if (names.length < 3 || !document.querySelector(`table.details-table th[aria-sort=${dir}]`)) return false;
    const sorted = [...names].sort((a, b) => a.localeCompare(b));
    if (dir === "descending") sorted.reverse();
    return names.join("|") === sorted.join("|");
  }, dir, { timeout: 10000 }).then(() => true, () => false);
  expect(await ordered("ascending"), "rows sorted by name A–Z");
  await page.click("table.details-table th button:has-text('Name')");
  expect(await ordered("descending"), "rows sorted by name Z–A");
  await page.screenshot({ path: `${SHOTS}/folders-details-view.png` });
  const other = await desk.browser().newContext({ viewport: { width: 1366, height: 900 }, storageState: await desk.storageState() });
  const op = await other.newPage();
  await op.goto(`${BASE}/folders/${ids.parity}`);
  await op.waitForSelector("table.details-table");
  expect(await op.locator("table.details-table th[aria-sort=descending]").count() === 1, "view and sort followed to another session");
  await other.close();
  // empty and error states
  await page.goto(`${BASE}/folders/${ids.passportCopies}`);
  await page.waitForSelector(".empty:has-text('drag files and folders here')");
  } finally { // later steps expect the list view
    await api(page, "/api/settings", { method: "PUT", body: { values: { "me.doc_view": "list", "me.doc_sort": "-added" } } });
    await page.reload();
  }
});

await step("AT-90 files dropped from the desktop upload into the drop target", async () => {
  await page.goto(`${BASE}/folders/${ids.passportCopies}`);
  await page.waitForSelector(".empty");
  await page.evaluate(() => {
    const dt = new DataTransfer();
    dt.items.add(new File(["synthetic dropped note one"], "dropped-one.txt", { type: "text/plain" }));
    dt.items.add(new File(["synthetic dropped note two"], "dropped-two.txt", { type: "text/plain" }));
    const pane = document.querySelector(".list-pane");
    pane.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
    pane.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
  });
  await page.waitForSelector(".drop-progress:has-text('Upload finished')");
  const card = await page.locator(".drop-progress").innerText();
  expect(card.includes("2 of 2"), card);
  await page.waitForSelector(".doc-card:has-text('dropped-one')");
  await page.screenshot({ path: `${SHOTS}/drop-upload.png` });
  await page.click("button[aria-label='Close upload summary']");
});

await step("AT-101/106/112 selective OCR: manual by default, chosen pages and languages, review queue", async () => {
  const card = { id: ids["Sample residence card"] };
  await page.goto(`${BASE}/documents/${card.id}`);
  await page.click("[role=tab]:has-text('Text (OCR)')");
  await page.waitForSelector(".ocr-panel >> text=OCR: Not processed"); // Manual is the default for new installations
  await page.click("button:has-text('Run OCR…')");
  await page.waitForSelector(".modal:has-text('Text recognition (OCR)')");
  await page.fill(".modal input[aria-label^='Pages of']", "1");
  for (const lang of ["English", "Arabic", "Hindi"]) expect(await page.locator(`.modal label:has-text('${lang}')`).count() === 1, `language ${lang} offered`);
  await page.screenshot({ path: `${SHOTS}/ocr-run.png` });
  await page.click(".modal button:has-text('Run OCR')");
  await page.waitForSelector(".toast:has-text('Text recognition queued')");
  await page.waitForSelector("text=OCR: Needs review", { timeout: 90000 });
  expect(await page.locator(".badge:has-text('OCR confidence')").count() >= 1, "confidence shown");
  await page.goto(BASE + "/ocr-review");
  await page.waitForSelector("text=Sample residence card");
  await page.screenshot({ path: `${SHOTS}/ocr-review.png` });
  // a photo can be re-run with a forced rotation
  await page.goto(`${BASE}/documents/${ids["Sample scan"]}`);
  await page.click("[role=tab]:has-text('Text (OCR)')");
  await page.click("button:has-text('Run OCR…')");
  await page.selectOption("#ocr-rot", "180");
  await page.click(".modal button:has-text('Run OCR')");
  await page.waitForSelector(".toast:has-text('Text recognition queued')");
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
  await page.locator(".widget-item:has-text('Recent activity') input[type=checkbox]").uncheck();
  for (let i = 0; i < 5; i++) await page.click("button[aria-label='Move Recent documents up']").catch(() => undefined);
  await page.click("text=Save settings");
  await page.waitForSelector(".toast:has-text('Settings saved')");
  await page.goto(BASE + "/");
  await page.waitForSelector(".ov-grid");
  expect(await page.locator("[data-widget=activity]").count() === 0, "activity widget hidden");
  const order = await page.evaluate(() => [...document.querySelectorAll(".ov-grid [data-widget]")].map((h) => h.dataset.widget));
  expect(order.indexOf("recent") < order.indexOf("shared"), `order ${order}`);
});

await step("AT-116..121/125/127 Overview: customize, weather city, calendar and holidays", async () => {
  // weather against a local fake provider (synthetic numbers, no internet)
  await api(page, "/api/settings", { method: "PUT", body: { values: { "weather.enabled": true, "weather.base_url": `${WX}/v1/forecast`, "weather.geocoding_url": `${WX}/v1/search` } } });
  await api(page, "/api/settings", { method: "PUT", body: { values: { "me.dashboard_widgets": ["date", "weather", "summary", "calendar", "holidays", "upcoming", "recent", "shared"], "me.overview_layout": {} } } });
  await page.goto(BASE + "/");
  await page.click("[data-widget=weather] button:has-text('Choose your city')");
  await page.fill(".modal input[aria-label='City name']", "Riyadh");
  await page.click(".modal button:has-text('Search')");
  await page.click(".modal button:has-text('Riyadh')");
  await page.waitForSelector("[data-widget=weather] .ov-forecast");
  const wx = await page.locator("[data-widget=weather]").innerText();
  expect(wx.includes("41°C") && wx.includes("Riyadh"), `weather ${wx}`);
  await page.waitForSelector("[data-widget=calendar] .ov-cal-day.today");
  const hijri = await page.locator("[data-widget=date] .ov-hijri").innerText();
  expect(/\d+ .+ 14\d\d AH/.test(hijri), `hijri ${hijri}`);
  // calendar navigation keeps holiday markers and returns to today
  const label = await page.locator("[data-widget=calendar] strong").first().innerText();
  await page.click("[data-widget=calendar] button[aria-label='Next month']");
  await page.waitForFunction((l) => document.querySelector("[data-widget=calendar] strong")?.textContent !== l, label);
  await page.click("[data-widget=calendar] button:has-text('Today')");
  await page.waitForFunction((l) => document.querySelector("[data-widget=calendar] strong")?.textContent === l, label);
  expect(await page.locator("[data-widget=holidays] li").count() > 0, "upcoming holidays listed");
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${SHOTS}/overview.png` });
  // edit layout: style, size, keyboard reorder, remove, add; then save
  await page.click("button:has-text('Customize Overview')");
  await page.waitForSelector(".ov-editbar");
  await page.selectOption("select[aria-label='Today (Gregorian + Hijri) style']", "circle");
  expect(await page.locator("select[aria-label='Month calendar style'] option[value=circle]").count() === 0, "lists and calendars stay rectangular");
  await page.click("button[aria-label='Make Documents summary wider']");
  await page.click("button[aria-label='Move Weather later']");
  await page.click("button[aria-label='Remove Shared with me']");
  await page.selectOption("select[aria-label='Add widget']", "activity");
  const wide = page.locator("button[aria-label='Make Month calendar wider']");
  expect(await wide.isDisabled(), "calendar cannot grow past its maximum");
  await page.evaluate(() => { window.scrollTo(0, 0); document.querySelectorAll("main, .main, .content").forEach((m) => m.scrollTo?.(0, 0)); });
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/overview-customize.png` });
  await page.click("button:has-text('Save layout')");
  await page.waitForSelector(".toast:has-text('Overview saved')");
  await page.reload();
  await page.waitForSelector("[data-widget=date] .ov-card.circle");
  const order = await page.evaluate(() => [...document.querySelectorAll(".ov-grid [data-widget]")].map((h) => h.dataset.widget));
  expect(order.join() === "date,summary,weather,calendar,holidays,upcoming,recent,activity", `saved order ${order}`);
  const fit = await page.evaluate(() => [...document.querySelectorAll(".ov-cell")].every((c) => c.getBoundingClientRect().right <= window.innerWidth + 1));
  expect(fit, "no widget off-screen");
});

await step("AT-123/124 holiday countries and corrections in settings", async () => {
  await page.goto(BASE + "/settings/overview");
  await page.waitForSelector("text=Holiday countries");
  await page.fill("input[aria-label='Add to Holiday countries']", "United Arab");
  await page.click(".country-matches button:has-text('United Arab Emirates')");
  expect(await page.locator(".chip:has-text('United Arab Emirates')").count() === 1, "country chip");
  await page.click("button[aria-label='Remove United Arab Emirates']");
  expect(await page.locator(".chip").count() === 2, "back to SA + IN");
  await page.waitForSelector("text=Holiday corrections");
  await page.waitForSelector(".badge:has-text('Provisional'), .badge:has-text('Confirmed')");
  await page.screenshot({ path: `${SHOTS}/settings-overview.png` });
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
  await page.screenshot({ path: `${SHOTS}/notifications.png` });
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
  await page.screenshot({ path: `${SHOTS}/settings-backup.png` });
  await api(page, "/api/settings", { method: "PUT", body: { values: { "backup.frequency": "daily", "backup.month_day": 1 } } });
});

await step("AT-63/64 import into a chosen sub-folder with the exact final hierarchy", async () => {
  await page.goto(BASE + "/imports/new");
  await page.setInputFiles("input[type=file][webkitdirectory]", path.join(FIX, "import"));
  await page.waitForURL(/\/imports\/[0-9a-f-]+/);
  await page.selectOption("select[aria-label='Action for Old']", "user");
  await page.selectOption("select[aria-label='Person for Old']", { label: "Son1" });
  await page.click("button[aria-label='Destination sub-folder for Old']");
  await page.click(".modal .picker-pick:has-text('Parity')");
  await page.click(".modal button:has-text('Done')");
  await page.locator("label:has-text('keep “Old” as a folder') input").check();
  await page.click("button:has-text('Check & preview')");
  await page.waitForSelector(".import-tree");
  const tree = await page.locator(".import-tree").innerText();
  expect(tree.includes("Address Update 22July2026") && tree.includes("new") && tree.includes("existing"), tree);
  await page.screenshot({ path: `${SHOTS}/import-folder.png` });
  await page.click("button:has-text('Start import')");
  await page.waitForSelector("text=Open folders", { timeout: 30000 });
  const f = (await api(page, "/api/folders")).data.folders;
  const old = f.find((x) => x.name === "Old" && x.parent === ids.parity);
  expect(old && f.some((x) => x.name === "Address Update 22July2026" && x.parent === old.id), "hierarchy recreated under Parity / Old");
});

await step("AT-138/140/141 antivirus: background scan, quarantine and release (EICAR test string)", async () => {
  // the EICAR anti-virus test string (harmless); assembled in two halves so this file itself is not flagged
  const eicar = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS" + "-TEST-FILE!$H+H*";
  const up = await page.evaluate(async ([folder, text]) => {
    const csrf = (document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "";
    const fd = new FormData();
    fd.append("folder", folder);
    fd.append("files", new Blob([text], { type: "text/plain" }), "eicar-test.txt");
    const r = await fetch("/api/documents", { method: "POST", body: fd, headers: { "X-CSRFToken": decodeURIComponent(csrf) } });
    return { status: r.status, data: await r.json() };
  }, [ids.parity, eicar]);
  expect(up.status === 201, `upload ${up.status}`);
  const id = up.data.documents[0].id;
  ids.eicar = id;
  let status = "";
  for (let i = 0; i < 60 && status !== "quarantined"; i++) {
    status = (await api(page, `/api/documents/${id}`)).data.current_version.antivirus.status;
    if (status !== "quarantined") await page.waitForTimeout(1000);
  }
  expect(status === "quarantined", `antivirus status ${status}`);
  const file = await page.evaluate(async (u) => (await fetch(u)).status, `/api/documents/${id}/file`);
  expect(file === 423, `quarantined file served with ${file}`);
  await page.goto(`${BASE}/documents/${id}`);
  await page.waitForSelector("text=Quarantined by the antivirus");
  await page.goto(BASE + "/settings/security?view=antivirus");
  await page.waitForSelector("td:has-text('eicar-test.txt')");
  await page.waitForSelector(".badge:has-text('Eicar')");
  await page.screenshot({ path: `${SHOTS}/security-antivirus.png` });
  await page.click("tr:has-text('eicar-test.txt') button:has-text('Release…')");
  await page.waitForSelector(".modal:has-text('ClamAV detected malware')");
  expect(await page.locator(".modal button:has-text('Release file')").isDisabled(), "release needs confirmation and a reason");
  await page.fill("#rel-reason", "Synthetic EICAR test file used by the browser tests");
  await page.check(".modal input[type=checkbox]");
  await page.click(".modal button:has-text('Release file')");
  await page.waitForSelector(".toast:has-text('released')");
  expect((await api(page, `/api/documents/${id}`)).data.current_version.antivirus.status === "released", "released");
});

await step("AT-149/150/156/159 security center: health score, Internet test, storage", async () => {
  await page.goto(BASE + "/settings/security");
  await page.waitForSelector(".score-ring");
  await page.waitForSelector("text=Internet exposure");
  await page.screenshot({ path: `${SHOTS}/security-overview.png` });
  await page.goto(BASE + "/settings/security?view=test");
  await page.click("button:has-text('Run Security Test')");
  await page.waitForSelector(".toast:has-text('Security test started')");
  for (let i = 0; i < 120; i++) {
    const runs = (await api(page, "/api/security/tests")).data.runs;
    if (runs[0] && runs[0].status !== "running") break;
    await page.waitForTimeout(2000);
  }
  await page.reload();
  await page.waitForSelector("text=Latest result");
  expect(await page.locator(".finding-group").count() >= 6, "finding categories shown");
  await page.screenshot({ path: `${SHOTS}/security-test.png` });
  await page.goto(BASE + "/settings/security?view=storage");
  await page.waitForSelector("text=Storage Health");
  await page.waitForSelector("text=Documents (originals)");
  await page.screenshot({ path: `${SHOTS}/security-storage.png` });
  for (const [view, text] of [["updates", "Debian security updates"], ["firewall", "Firewall status"], ["records", "Security records"]]) {
    await page.goto(`${BASE}/settings/security?view=${view}`);
    await page.waitForSelector(`h2:has-text('${text}')`);
  }
  expect(await page.locator("button:has-text('Enable firewall'), button:has-text('Open port')").count() === 0, "no firewall controls");
  const prefs = (await api(page, "/api/session")).data.preferences.dashboard_widgets;
  await api(page, "/api/settings", { method: "PUT", body: { values: { "me.dashboard_widgets": [...prefs.filter((w) => w !== "security"), "security"] } } });
  await page.goto(BASE + "/");
  await page.waitForSelector("[data-widget=security] .score-ring");
});

await step("AT-146 authentik settings and sign-in button", async () => {
  await api(page, "/api/settings", { method: "PUT", body: { values: { "authentik.enabled": true, "authentik.issuer": "https://auth.example.test/application/o/personal-dm/",
    "authentik.client_id": "personal-dm-demo", "authentik.client_secret": "demo-secret-not-real" } } });
  await page.goto(BASE + "/settings/authentication");
  await page.waitForSelector("text=External identity providers — authentik");
  await page.locator("h2:has-text('External identity providers — authentik')").evaluate((el) => {
    el.scrollIntoView({ block: "start" });
    window.scrollBy(0, -90); // keep the heading below the sticky top bar
  });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/settings-authentik.png` });
  const anon = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const lp = await anon.newPage();
  await lp.goto(BASE + "/login");
  await lp.waitForSelector("a:has-text('Sign in with authentik')");
  expect(await lp.locator("#password").isVisible(), "local sign-in stays available");
  await anon.close();
});

await step("screens for the README (desktop)", async () => {
  await page.goto(`${BASE}/folders/${ids.parity}/${ids["Sample policy (3 pages)"]}`);
  await page.waitForSelector(".detail-pane .viewer canvas");
  await page.screenshot({ path: `${SHOTS}/folders-preview.png` });
  for (const [file, url, wait] of [["settings-security-passkeys.png", "/settings/account?tab=security", "text=Passkeys"],
    ["local-ai.png", "/settings/ai", "text=Local AI"], ["login-audit.png", "/settings/activity?view=logins", "text=Login audit"],
    ["security-access.png", "/settings/security?view=access", "text=Geographic access control"]]) {
    await page.goto(BASE + url);
    await page.waitForSelector(wait);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SHOTS}/${file}` });
  }
});

await step("AT-128/130 every sign-in design keeps the same sign-in methods (desktop and phone)", async () => {
  await api(page, "/api/settings", { method: "PUT", body: { values: { "auth.allow_passkeys": true, "auth.allow_passwordless": true } } });
  for (const [design, w, h] of [["minimal", 1440, 900], ["nature", 1440, 900], ["travel", 1440, 900], ["family", 1440, 900], ["neutral", 1440, 900], ["travel", 390, 844]]) {
    await api(page, "/api/settings", { method: "PUT", body: { values: { "login.design": design } } });
    const anon = await browser.newContext({ viewport: { width: w, height: h }, isMobile: w < 500, hasTouch: w < 500 });
    const lp = await anon.newPage();
    watch(lp, `login-${design}`);
    await lp.goto(BASE + "/login");
    await lp.waitForSelector(`.auth-art.design-${design}`);
    for (const sel of ["#username", "#password", "button:has-text('Sign in')", "button:has-text('passkey')"]) expect(await lp.locator(sel).first().isVisible(), `${design}: ${sel} visible`);
    const o = await lp.evaluate(() => ({ over: document.documentElement.scrollWidth - window.innerWidth, formTop: document.querySelector(".auth-form").getBoundingClientRect().top }));
    expect(o.over <= 1, `${design}: overflow ${o.over}`);
    if (w < 500) {
      expect(o.formTop < 260, `phone: the form comes first (top ${o.formTop})`);
      await lp.screenshot({ path: `${SHOTS}/mobile-login.png` });
    } else if (["minimal", "nature", "travel", "family"].includes(design)) {
      await lp.screenshot({ path: `${SHOTS}/${design === "minimal" ? "login" : `login-${design}`}.png` });
    }
    if (design === "travel" && w > 500) {
      await lp.fill("#username", "son1");
      await lp.fill("#password", "wrong-password");
      await lp.click("button:has-text('Sign in')");
      await lp.waitForSelector("[role=alert]");
    }
    await anon.close();
  }
  await page.goto(BASE + "/settings/overview");
  await page.waitForSelector(".design-grid");
  await page.locator(".design-grid").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/settings-login-design.png` });
  await api(page, "/api/settings", { method: "PUT", body: { values: { "login.design": "minimal", "auth.allow_passwordless": false } } });
});

// ------------------------------------------------------------------ tablet / mobile parity
const ROUTES = ["/", "/ocr-review", "/settings/overview", "/settings/security", "/settings/security?view=antivirus", "/settings/security?view=test", "/settings/security?view=storage", "/folders", `/folders/${ids.parity}`, `/documents/${ids["Sample policy (3 pages)"]}`, "/search?q=sample", "/shared",
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
      await mp.waitForSelector(".ov-grid [data-widget=date] .ov-card.circle");
      expect(await mp.locator("[data-widget=shared]").count() === 0, "widget choice synced to mobile");
      const one = await mp.evaluate(() => getComputedStyle(document.querySelector(".ov-grid")).gridTemplateColumns.split(" ").length);
      expect(one === 1, `phone uses one column (${one})`);
      await mp.screenshot({ path: `${SHOTS}/mobile-overview.png` });
      await api(mp, "/api/settings", { method: "PUT", body: { values: { "me.theme": "blue" } } });
      await page.goto(BASE + "/");
      await page.waitForFunction(() => document.documentElement.dataset.theme === "blue");
      await api(page, "/api/settings", { method: "PUT", body: { values: { "me.theme": "green", "me.dashboard_widgets": ["date", "weather", "summary", "calendar", "holidays", "upcoming", "shared", "recent", "activity", "review_queue", "backup"] } } });
    });
  }
  await ctx.close();
}

await step("no uncaught page errors", async () => { expect(!errors.length, errors.join(" | ")); });
await browser.close();
wxServer.close();
fs.writeFileSync(process.env.PARITY_REPORT || "docs/parity-report.json", JSON.stringify(results, null, 1));
process.exit(results.some((r) => r[0] === "FAIL") ? 1 : 0);
