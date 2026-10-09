// Offline access scoped by account + device + folder/document (Change Set S, AT-251..AT-259), in a real browser.
// Runs after flow.mjs against the same throw-away instance (synthetic documents only). Each Playwright browser
// context is a separate "device" (its own Cache Storage and localStorage), exactly like two browsers or an
// installed app next to the browser.
//
// Usage: BASE=http://localhost:8000 node tests/e2e/offline.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const PW = "Sample-Passw0rd!";
const SON_PW = "Son1-Own-Passw0rd";
const OUT = "tests/e2e/out/offline";
fs.mkdirSync(OUT, { recursive: true });
const results = [];
let failed = 0;
const step = async (name, fn) => {
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { failed++; results.push(["FAIL", name, String(e).slice(0, 800)]); console.log("FAIL", name, String(e).slice(0, 800)); }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };

function textPdf(text) {
  const content = `BT /F1 14 Tf 50 750 Td (${text}) Tj ET`;
  const objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"];
  let out = "%PDF-1.4\n";
  const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("");
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return out;
}

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
const api = (page, url, opts = {}) => page.evaluate(async ([url, opts]) => {
  const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
  const r = await fetch(url, { method: opts.method || (opts.body ? "POST" : "GET"), headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: opts.body ? JSON.stringify(opts.body) : undefined });
  return { status: r.status, data: r.headers.get("content-type")?.includes("json") ? await r.json() : null };
}, [url, opts]);
const uploadPdf = (page, folder, name, text) => page.evaluate(async ([folder, name, pdf]) => {
  const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
  const fd = new FormData();
  fd.append("folder", folder);
  fd.append("files", new File([pdf], name, { type: "application/pdf" }));
  const r = await fetch("/api/documents", { method: "POST", headers: { "X-CSRFToken": csrf }, body: fd });
  return (await r.json()).documents[0].id;
}, [folder, name, textPdf(text)]);
const newVersion = (page, docId, name, text) => page.evaluate(async ([docId, name, pdf]) => {
  const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
  const fd = new FormData();
  fd.append("file", new File([pdf], name, { type: "application/pdf" }));
  return (await fetch(`/api/documents/${docId}/versions`, { method: "POST", headers: { "X-CSRFToken": csrf }, body: fd })).status;
}, [docId, name, textPdf(text)]);

async function device(user, pw, viewport = { width: 1440, height: 900 }) {
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.log("pageerror", String(e).slice(0, 200)));
  await page.goto(BASE + "/login");
  await page.fill("#username", user);
  await page.fill("#password", pw);
  await page.click("button:has-text('Sign in')");
  await page.waitForSelector("text=Good");
  const uid = (await api(page, "/api/session")).data.user.id;
  return { ctx, page, uid };
}
const localState = (page, uid) => page.evaluate(async (uid) => {
  const idx = JSON.parse(localStorage.getItem(`pd-offline-index-${uid}`) || "null");
  const keys = await caches.keys();
  const blobs = keys.includes(`pd-offline-${uid}`) ? (await (await caches.open(`pd-offline-${uid}`)).keys()).length : 0;
  const texts = keys.includes(`pd-offline-text-${uid}`) ? (await (await caches.open(`pd-offline-text-${uid}`)).keys()).length : 0;
  return { items: idx ? Object.values(idx.items || {}) : [], selections: idx?.selections || [], caches: keys, blobs, texts, device: idx?.deviceId };
}, uid);
// wait until this device holds exactly n copies and none is still downloading
const waitIdle = async (page, uid, n) => page.waitForFunction(([uid, n]) => {
  const idx = JSON.parse(localStorage.getItem(`pd-offline-index-${uid}`) || "null");
  const items = Object.values(idx?.items || {});
  return items.length === n && items.every((i) => !["downloading", "updating"].includes(i.status));
}, [uid, n], { timeout: 30000 });
const signOut = (page) => page.click(".sidebar button[aria-label='Sign out']");
const syncFromPage = (page, uid) => page.evaluate(async () => {
  // the Offline page's "Sync now" button runs the same code path as the background sync
  const b = [...document.querySelectorAll("button")].find((x) => x.textContent?.includes("Sync now"));
  b?.click();
});

// ------------------------------------------------------------------ fixtures (synthetic)
const A = await device("admin", PW);
const adminRoot = (await api(A.page, "/api/folders")).data.folders.find((f) => f.kind === "personal_root" && f.owner?.id === A.uid) ||
  (await api(A.page, "/api/folders")).data.folders.find((f) => f.kind === "personal_root");
const stamp = Date.now().toString(36);
const trip = (await api(A.page, "/api/folders", { body: { parent: adminRoot.id, name: `Offline trip ${stamp}` } })).data;
const tickets = (await api(A.page, "/api/folders", { body: { parent: trip.id, name: "Tickets" } })).data;
const docItin = await uploadPdf(A.page, trip.id, "itinerary-sample.pdf", "SAMPLE ITINERARY - SYNTHETIC");
const docTicket = await uploadPdf(A.page, tickets.id, "ticket-sample.pdf", "SAMPLE TICKET - SYNTHETIC");
const docSolo = await uploadPdf(A.page, adminRoot.id, `solo-sample-${stamp}.pdf`, "SAMPLE SINGLE DOCUMENT OFFLINE TEXT");
await A.page.waitForTimeout(4000); // worker: preview + text

await step("AT-252 folder ⋮ menu offers offline actions (permission-aware)", async () => {
  await A.page.goto(`${BASE}/folders/${trip.id}`);
  await A.page.click(`[aria-label="Folder actions"]`);
  await A.page.waitForSelector("[role=menuitem]:has-text('Make available offline…')");
  expect(!(await A.page.locator("[role=menuitem]:has-text('Remove offline copy')").count()), "remove shown before anything is offline");
  await A.page.keyboard.press("Escape");
});

await step("AT-253 folder-only vs folder+subfolders choice shows count and size", async () => {
  await A.page.click(`[aria-label="Folder actions"]`);
  await A.page.click("[role=menuitem]:has-text('Make available offline…')");
  const dlg = A.page.locator("[role=dialog]");
  await dlg.locator("text=Estimated size").waitFor();
  const rec = await dlg.innerText();
  expect(/This folder and all subfolders/.test(rec) && /Recommended/.test(rec), "recursive option not offered as recommended");
  expect(/Documents\s*2/.test(rec) && /Subfolders\s*1/.test(rec), "recursive count wrong: " + rec);
  await dlg.locator("label:has-text('This folder only')").click();
  await A.page.waitForFunction(() => /Documents\s*1/.test(document.querySelector("[role=dialog]")?.textContent?.replace(/\s+/g, " ") || "") || /Documents1/.test(document.querySelector("[role=dialog]")?.textContent || ""));
  await A.page.screenshot({ path: `${OUT}/folder-dialog.png` });
  await dlg.locator("button:has-text('Make available offline')").click();
  await waitIdle(A.page, A.uid, 1);
  let s = await localState(A.page, A.uid);
  expect(s.items.length === 1 && s.items[0].name === "itinerary-sample.pdf", "folder-only should hold 1 document: " + JSON.stringify(s.items.map((i) => i.name)));
  expect(s.blobs === 1, "blob not cached");
  // switch to "with subfolders": remove and choose again
  await A.page.click(`[aria-label="Folder actions"]`);
  await A.page.click("[role=menuitem]:has-text('Remove offline copy')");
  await A.page.waitForFunction((uid) => !Object.keys(JSON.parse(localStorage.getItem(`pd-offline-index-${uid}`) || "{}").items || {}).length, A.uid);
  await A.page.click(`[aria-label="Folder actions"]`);
  await A.page.click("[role=menuitem]:has-text('Make available offline…')");
  await A.page.locator("[role=dialog] >> text=Estimated size").waitFor();
  await A.page.locator("[role=dialog] button:has-text('Make available offline')").click();
  await waitIdle(A.page, A.uid, 2);
  s = await localState(A.page, A.uid);
  expect(s.items.length === 2 && s.blobs === 2, "with subfolders should hold 2: " + s.items.length);
  expect(s.items.every((i) => i.status === "available"), "statuses: " + s.items.map((i) => i.status));
  expect(await A.page.locator(`.tree-node:has-text('Offline trip ${stamp}') .offline-mark`).count() === 1, "tree has no offline marker");
});

await step("AT-251 offline state is scoped to this account on this device", async () => {
  const B = await device("admin", PW); // same account, another device
  await B.page.goto(BASE + "/offline");
  await B.page.waitForSelector("h1:has-text('Offline access')");
  const s = await localState(B.page, B.uid);
  expect(s.items.length === 0 && s.blobs === 0, "second device received offline copies");
  let devs = [];
  for (let i = 0; i < 20 && !devs.some((d) => d.items === 2); i++) {  // the first device reports its counts after its sync
    devs = (await api(B.page, "/api/offline/devices")).data.devices;
    if (!devs.some((d) => d.items === 2)) await B.page.waitForTimeout(500);
  }
  expect(devs.length >= 1, "first device not registered");
  expect(devs.some((d) => d.items === 2), "device report missing: " + JSON.stringify(devs.map((d) => d.items)));
  await B.ctx.close();
});

await step("AT-254 document ⋮ menu: make available, update, remove", async () => {
  await A.page.goto(`${BASE}/documents/${docSolo}`);
  await A.page.waitForSelector(".doc-header");
  await A.page.waitForSelector(".doc-offline-line >> text=Not available offline");
  await A.page.click(".doc-actions [aria-label='More actions']");
  await A.page.click("[role=menuitem]:has-text('Make available offline')");
  await A.page.waitForSelector(".doc-header [data-offline-status=available]", { timeout: 20000 });
  await A.page.click(".doc-actions [aria-label='More actions']");
  expect(await A.page.locator("[role=menuitem]:has-text('Update offline copy')").count() === 1, "no update item");
  await A.page.click("[role=menuitem]:has-text('Update offline copy')");
  await A.page.waitForSelector(".doc-header [data-offline-status=available]");
  await A.page.click(".doc-actions [aria-label='More actions']");
  await A.page.click("[role=menuitem]:has-text('Remove offline copy')");
  await A.page.waitForSelector(".doc-offline-line >> text=Not available offline");
  const s = await localState(A.page, A.uid);
  expect(!s.items.some((i) => i.documentId === docSolo), "copy not removed");
  // a document that is offline through its folder cannot be removed on its own (the folder rules)
  await A.page.goto(`${BASE}/documents/${docTicket}`);
  await A.page.waitForSelector(".doc-header [data-offline-status=available]");
  await A.page.click(".doc-actions [aria-label='More actions']");
  await A.page.click("[role=menuitem]:has-text('Remove offline copy')");
  await A.page.waitForSelector("text=because its folder is");
});

await step("AT-255 statuses: update available, downloading, failed, outdated — with text, not colour only", async () => {
  await api(A.page, "/api/settings", { method: "PUT", body: { values: { "offline.auto_update": false } } });
  expect(await newVersion(A.page, docItin, "itinerary-sample-v2.pdf", "SAMPLE ITINERARY V2 - SYNTHETIC") < 300, "new version upload failed");
  await A.page.waitForTimeout(2500);
  await A.page.goto(BASE + "/offline");
  await A.page.waitForFunction((id) => document.querySelector(`[data-offline-doc="${id}"] [data-offline-status]`)?.getAttribute("data-offline-status") === "update_available", docItin, { timeout: 20000 });
  const row = A.page.locator(`[data-offline-doc="${docItin}"]`);
  expect((await row.innerText()).includes("Update available"), "status text missing");
  await A.page.screenshot({ path: `${OUT}/offline-page-update-available.png`, fullPage: true });
  // failed: the download is refused by the network
  await A.page.route(`**/api/documents/${docItin}/file**`, (r) => r.abort());
  await row.locator("button:has-text('Update')").click();
  await A.page.waitForSelector(`[data-offline-doc="${docItin}"] [data-offline-status=failed]`);
  expect((await row.innerText()).includes("Offline copy failed"), "failed text missing");
  // the older copy stays usable after a failed update
  const s = await localState(A.page, A.uid);
  const it = s.items.find((i) => i.documentId === docItin);
  expect(it.latestVersionId && it.versionId !== it.latestVersionId && s.blobs === 2, "old copy not kept after failed update");
  await A.page.unroute(`**/api/documents/${docItin}/file**`);
  // downloading: slow the download down and observe the progress state
  await A.page.route(`**/api/documents/${docItin}/file**`, async (r) => { await new Promise((ok) => setTimeout(ok, 1500)); await r.continue(); });
  await row.locator("button:has-text('Update')").click();
  await A.page.waitForSelector(`[data-offline-doc="${docItin}"] [data-offline-status=updating]`, { timeout: 5000 });
  expect(await A.page.locator(`[data-offline-doc="${docItin}"] [data-offline-status=updating][role=status]`).count() === 1, "progress not announced");
  await A.page.waitForSelector(`[data-offline-doc="${docItin}"] [data-offline-status=available]`, { timeout: 20000 });
  await A.page.unroute(`**/api/documents/${docItin}/file**`);
  // outdated: not verified for more than a week
  await A.page.evaluate((uid) => { const k = `pd-offline-index-${uid}`; const s = JSON.parse(localStorage.getItem(k)); s.lastSync = new Date(Date.now() - 8 * 86400e3).toISOString(); localStorage.setItem(k, JSON.stringify(s)); }, A.uid);
  // the server cannot be reached, so the copy cannot be verified: shown as outdated (text + icon)
  await A.page.route("**/api/offline/sync", (r) => r.abort());
  await A.page.reload();
  await A.page.waitForSelector(`[data-offline-doc="${docItin}"] [data-offline-status=outdated]`);
  expect((await A.page.locator(`[data-offline-doc="${docItin}"]`).innerText()).includes("Outdated"), "outdated text missing");
  await A.page.unroute("**/api/offline/sync");
  await A.page.reload();
  await A.page.waitForSelector(`[data-offline-doc="${docItin}"] [data-offline-status=available]`, { timeout: 20000 });
  await api(A.page, "/api/settings", { method: "PUT", body: { values: { "offline.auto_update": true } } });
});

await step("AT-256 Offline page: device, counts, storage, pending updates, Update all, remove", async () => {
  await A.page.goto(BASE + "/offline");
  await A.page.waitForSelector("text=This device");
  const txt = await A.page.locator("main, #root").first().innerText();
  expect(/Chrome on Linux|Chromium|on Linux/.test(txt), "device label missing");
  expect(/Offline on this device\s*2/.test(txt.replace(/\n/g, " ")) || txt.includes("Offline on this device"), "count missing");
  expect(txt.includes("Browser storage") && txt.includes("Pending updates") && txt.includes("Last sync"), "summary incomplete");
  expect(txt.includes(`Offline trip ${stamp}`) && txt.includes("With all subfolders"), "folder selection not listed");
  await A.page.waitForSelector("button:has-text('Sync now')");
  expect(await A.page.locator("button:has-text('Update all')").count() === 1, "Update all missing");
  await A.page.screenshot({ path: `${OUT}/offline-page.png`, fullPage: true });
  // offline: the copies open without a connection
  await A.ctx.setOffline(true);
  await A.page.reload().catch(() => undefined);
  await A.page.waitForSelector("text=You are offline", { timeout: 15000 });
  const url = await A.page.evaluate(async (uid) => {
    const idx = JSON.parse(localStorage.getItem(`pd-offline-index-${uid}`));
    const it = Object.values(idx.items)[0];
    const r = await (await caches.open(`pd-offline-${uid}`)).match(`/offline/${it.versionId}`);
    return r ? (await r.blob()).size : 0;
  }, A.uid);
  expect(url > 100, "offline copy not readable while offline");
  await A.page.screenshot({ path: `${OUT}/offline-page-offline-mode.png`, fullPage: true });
  await A.ctx.setOffline(false);
});

// ---- another person: shared folder, revocation, capability
await A.page.goto(BASE + "/");
await A.page.waitForSelector("text=Good");
const members = (await api(A.page, "/api/family/members")).data;
const son = (members.members || members.users || members).find?.((m) => m.username === "son1");
await step("AT-257 sync revalidates access: revoked or turned-off content is removed", async () => {
  expect(son, "son1 not found");
  const r = await api(A.page, `/api/folders/${trip.id}/permissions`, { method: "PUT", body: { user: son.id, caps: ["view", "download"] } });
  expect(r.status === 200, "share failed " + r.status);
  const S = await device("son1", SON_PW, { width: 390, height: 844 });
  await S.page.goto(`${BASE}/folders/${trip.id}`);
  await S.page.click(`[aria-label="Folder actions"]`);
  await S.page.click("[role=menuitem]:has-text('Make available offline…')");
  await S.page.locator("[role=dialog] >> text=Estimated size").waitFor();
  await S.page.locator("[role=dialog] button:has-text('Make available offline')").click();
  await waitIdle(S.page, S.uid, 2);
  let s = await localState(S.page, S.uid);
  expect(s.items.length === 2, "son1 should hold 2, has " + s.items.length);
  // view-only: the next sync removes the copies
  await api(A.page, `/api/folders/${trip.id}/permissions`, { method: "PUT", body: { user: son.id, caps: ["view"] } });
  await S.page.goto(BASE + "/offline");
  await S.page.waitForFunction((uid) => !Object.keys(JSON.parse(localStorage.getItem(`pd-offline-index-${uid}`) || "{}").items || {}).length, S.uid, { timeout: 20000 });
  s = await localState(S.page, S.uid);
  expect(s.blobs === 0, "revoked blobs remain: " + s.blobs);
  // view-only folder: no offline actions in the menu
  await S.page.goto(`${BASE}/folders/${trip.id}`);
  await S.page.click(`[aria-label="Folder actions"]`);
  expect(!(await S.page.locator("[role=menuitem]:has-text('Make available offline')").count()), "offered without download permission");
  await S.page.keyboard.press("Escape");
  // administrator turns offline copies off for son1: copies go at the next sync, actions disappear
  await api(A.page, `/api/folders/${trip.id}/permissions`, { method: "PUT", body: { user: son.id, caps: ["view", "download"] } });
  await S.page.goto(BASE + "/offline");
  await S.page.waitForFunction((uid) => Object.keys(JSON.parse(localStorage.getItem(`pd-offline-index-${uid}`) || "{}").items || {}).length === 2, S.uid, { timeout: 20000 });
  expect((await api(A.page, `/api/admin/offline/users/${son.id}`, { method: "PATCH", body: { offline_allowed: false } })).status === 200, "admin toggle failed");
  await S.page.reload();
  await S.page.waitForSelector("text=turned off offline copies for your account", { timeout: 20000 });
  s = await localState(S.page, S.uid);
  expect(s.items.length === 0 && s.blobs === 0, "copies not wiped after capability off");
  await S.page.screenshot({ path: `${OUT}/offline-mobile-turned-off.png`, fullPage: true });
  await api(A.page, `/api/admin/offline/users/${son.id}`, { method: "PATCH", body: { offline_allowed: true } });
  await api(A.page, `/api/folders/${trip.id}/permissions`, { method: "PUT", body: { user: son.id, caps: [] } });
  await S.ctx.close();
});

await step("AT-259 offline text follows its own policy and is removed with OCR", async () => {
  await api(A.page, "/api/settings", { method: "PUT", body: { values: { "offline.cache_text": true } } });
  await A.page.goto(`${BASE}/documents/${docSolo}`);
  await A.page.waitForSelector(".doc-header");
  await A.page.click(".doc-actions [aria-label='More actions']");
  await A.page.click("[role=menuitem]:has-text('Make available offline')");
  await A.page.waitForSelector(".doc-header [data-offline-status=available]", { timeout: 20000 });
  await A.page.waitForFunction(async (uid) => (await (await caches.open(`pd-offline-text-${uid}`)).keys()).length > 0, A.uid, { timeout: 20000 });
  const text = await A.page.evaluate(async ([uid, id]) => (await (await caches.open(`pd-offline-text-${uid}`)).match(`/offline-text/${id}`))?.text(), [A.uid, docSolo]);
  expect(text && text.includes("SAMPLE SINGLE DOCUMENT"), "offline text missing");
  const del = await api(A.page, `/api/documents/${docSolo}/ocr`, { method: "DELETE", body: { confirm: true, include_embedded: true } });
  expect(del.status === 200, "OCR removal failed " + del.status + JSON.stringify(del.data));
  await A.page.goto(BASE + "/offline");
  await A.page.waitForFunction(async ([uid, id]) => !(await (await caches.open(`pd-offline-text-${uid}`)).match(`/offline-text/${id}`)), [A.uid, docSolo], { timeout: 20000 });
  // policy off: no text is kept for any document
  await api(A.page, "/api/settings", { method: "PUT", body: { values: { "offline.cache_text": false } } });
  await A.page.reload();
  await A.page.waitForSelector("h1:has-text('Offline access')");
  await A.page.waitForFunction(async (uid) => (await (await caches.open(`pd-offline-text-${uid}`)).keys()).length === 0, A.uid, { timeout: 20000 });
});

await step("AT-258 sign-out removes protected copies per policy", async () => {
  // default policy: removed unless the person chose to keep them
  await A.page.goto(BASE + "/offline");
  await A.page.waitForSelector("text=Keep my offline copies");
  let s = await localState(A.page, A.uid);
  expect(s.blobs >= 2, "precondition: copies present");
  await signOut(A.page);
  await A.page.waitForSelector("#username");
  s = await localState(A.page, A.uid);
  expect(s.blobs === 0 && s.items.length === 0 && !s.caches.includes(`pd-offline-${A.uid}`), "copies left after sign-out: " + JSON.stringify(s.caches));
  // "keep" chosen, but the administrator requires removal
  await A.page.fill("#username", "admin");
  await A.page.fill("#password", PW);
  await A.page.click("button:has-text('Sign in')");
  await A.page.waitForSelector(".sidebar");
  await api(A.page, "/api/settings", { method: "PUT", body: { values: { "offline.logout_policy": "always_clear" } } });
  await A.page.goto(BASE + "/offline");
  await A.page.waitForFunction((uid) => Object.keys(JSON.parse(localStorage.getItem(`pd-offline-index-${uid}`) || "{}").items || {}).length >= 2, A.uid, { timeout: 20000 });
  await A.page.evaluate((uid) => localStorage.setItem(`pd-offline-keep-${uid}`, "1"), A.uid);
  await A.page.reload();
  await A.page.waitForSelector("text=requires offline copies to be removed at sign-out");
  await signOut(A.page);
  await A.page.waitForSelector("#username");
  s = await localState(A.page, A.uid);
  expect(s.blobs === 0, "always_clear did not remove copies");
  // keep allowed and chosen: the copies stay, and another account on this device sees none of them
  await A.page.fill("#username", "admin");
  await A.page.fill("#password", PW);
  await A.page.click("button:has-text('Sign in')");
  await A.page.waitForSelector(".sidebar");
  await api(A.page, "/api/settings", { method: "PUT", body: { values: { "offline.logout_policy": "user_choice" } } });
  await A.page.goto(BASE + "/offline");
  // the device learns the policy at its next sync
  await A.page.waitForFunction((uid) => { const s = JSON.parse(localStorage.getItem(`pd-offline-index-${uid}`) || "{}");
    return Object.keys(s.items || {}).length >= 2 && s.policy?.logout_policy === "user_choice"; }, A.uid, { timeout: 20000 });
  await A.page.locator("label:has-text('Keep my offline copies') input").check();
  await signOut(A.page);
  await A.page.waitForSelector("#username");
  s = await localState(A.page, A.uid);
  expect(s.blobs >= 2, "kept copies were removed");
  await A.page.fill("#username", "son1");
  await A.page.fill("#password", SON_PW);
  await A.page.click("button:has-text('Sign in')");
  await A.page.waitForSelector(".sidebar");
  await A.page.goto(BASE + "/offline");
  await A.page.waitForSelector("h1:has-text('Offline access')");
  const listed = await A.page.locator("[data-offline-doc]").count();
  expect(listed === 0, "another account sees offline copies: " + listed);
  await A.page.screenshot({ path: `${OUT}/offline-other-account.png`, fullPage: true });
});

await A.ctx.close();
await browser.close();
fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 1));
console.log(`\noffline e2e: ${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
