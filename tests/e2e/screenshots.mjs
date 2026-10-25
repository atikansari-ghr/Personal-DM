// Repeatable public screenshots (Change Set S, AT-270..AT-274): README story and screens no other test captures.
// Runs last in scripts/e2e.sh, on the synthetic demo state built by flow.mjs and parity.mjs. Every capture:
//   * 1440×900 CSS px at device pixel ratio 2 (phones 390×844 at 2), consistent across all images;
//   * after fonts load and animations settle (reduced motion), with no loading placeholders or toasts;
//   * passes a quality gate (no horizontal overflow, no clipped text, all images decoded) and a privacy gate
//     (no e-mail address outside example domains, no public IP outside documentation ranges, no token-like strings).
// Output: docs/images/screenshots/ (PUBLIC_SHOTS overrides) and a manifest with the source of each image.
// Usage: BASE=http://localhost:8000 node tests/e2e/screenshots.mjs
import { chromium } from "playwright";
import crypto from "node:crypto";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const SHOTS = process.env.PUBLIC_SHOTS || "docs/images/screenshots";
const PW = "Sample-Passw0rd!";
fs.mkdirSync(SHOTS, { recursive: true });
const results = [];
const manifest = [];
let failed = 0;
// E2E_ONLY=text runs only the steps whose name contains it (re-running one change set's steps during development)
const ONLY = process.env.E2E_ONLY || "";
const step = async (name, fn) => {
  if (ONLY && !name.includes(ONLY)) return;
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { failed++; results.push(["FAIL", name, String(e).slice(0, 800)]); console.log("FAIL", name, String(e).slice(0, 800)); }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };
const PRIVATE = [
  [/[A-Z0-9._%+-]+@(?!example\.(com|org|net)\b|family\.example\b|test\b|invalid\b|localhost\b)[A-Z0-9.-]+\.[A-Z]{2,}/i, "e-mail address outside example domains"],
  // public addresses only from the documentation ranges; private networks (Trusted Zones) cannot identify anyone
  [/\b(?!(?:127|10|192\.168|172\.(?:1[6-9]|2\d|3[01])|192\.0\.2|198\.51\.100|203\.0\.113)\.)(?:\d{1,3}\.){3}\d{1,3}\b/, "IP address outside documentation and private ranges"],
  [/(?<![A-Za-z0-9_-])(?![A-Za-z0-9_-]*[-_][A-Za-z]{4,}[-_][A-Za-z]{4,})[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_-])/, "token-like string"], // file names made of words are not tokens
];

// Map tiles are the only outside requests. In sandboxes that reach the Internet only through an HTTPS proxy
// (HTTPS_PROXY set), the browser uses it for https:// requests.
// If that proxy re-signs TLS, PD_E2E_PROXY_CA names its CA certificate: Chromium then trusts exactly that key
// (an SPKI pin); certificate verification stays on.
const PROXY = process.env.HTTPS_PROXY || process.env.https_proxy || "";
const pin = (file) => crypto.createHash("sha256").update(new crypto.X509Certificate(fs.readFileSync(file)).publicKey.export({ type: "spki", format: "der" })).digest("base64");
// Only https:// goes through the proxy; the app on http://localhost is always reached directly. (Playwright's own
// proxy option would also route localhost through the proxy.)
const args = PROXY ? [`--proxy-server=https=${new URL(PROXY).host}`] : [];
if (PROXY && process.env.PD_E2E_PROXY_CA) args.push(`--ignore-certificate-errors-spki-list=${pin(process.env.PD_E2E_PROXY_CA)}`);
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined, args });
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
    ["/settings/ai", "local-ai.png", "AI profiles: Local and Cloud (optional)", "h2"],
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

await step("AT-333 Backup & Recovery, Recovery Explorer, notifications and sign-in security (documentation screenshots)", async () => {
  // state from recovery.mjs: a local destination, a verified recovery point, a Trusted Zone "Home"
  const P = D.page;
  const dismiss = async () => { await P.keyboard.press("Escape"); await P.waitForTimeout(200); };
  await api(P, "/api/settings", { method: "PUT", body: { values: { "discord.enabled": true, "whatsapp.enabled": true } } });
  await P.goto(BASE + "/settings/backup");
  await P.waitForSelector("[data-health]");
  await P.waitForLoadState("networkidle");
  await capture(P, "backup-overview.png", "Backup & Recovery: health, newest verified point, readiness and destinations");
  await P.goto(BASE + "/settings/backup?view=policies");
  await P.click("tr:has-text('Default') button:has-text('Edit')");
  await P.waitForSelector("[role=dialog] #pol-freq");
  await capture(P, "backup-policy-dialog.png", "Policy: weekly Full backup, incremental every 4 hours, keep 4 weeks");
  await dismiss();
  await P.goto(BASE + "/settings/backup?view=destinations");
  await P.click("button:has-text('Add destination')");
  await P.fill("#dst-name", "Second disk");
  await P.fill("#dst-path", "/srv/backups/personaldocs");
  await capture(P, "backup-destination-dialog.png", "Add destination: a local folder on another disk");
  // Change Set V: the NAS is configured inside the destination (SMB example values, nothing real)
  await P.selectOption("#dst-kind", "nas");
  await P.waitForSelector("#dst-nas-server");
  await P.fill("#dst-name", "Home NAS");
  await P.fill("#dst-nas-server", "nas.example.lan");
  await P.fill("#dst-nas-share", "backups");
  await P.fill("#dst-nas-username", "backup-user");
  await capture(P, "backup-nas-destination.png", "Add destination → NAS share: SMB connection, server, share, folder and account (password write-only)");
  await dismiss();
  await P.waitForSelector(".dest-card");
  await P.waitForLoadState("networkidle");
  await capture(P, "backup-destinations.png", "Destination cards: health, free space, last and next backup, Test Connection and Backup Now; the backup queue");
  await P.locator(".dest-card button:has-text('Backup Now')").first().click();
  await P.waitForSelector("[role=dialog] >> text=This backup cannot be cancelled once it starts.");
  await capture(P, "backup-now-dialog.png", "Backup Now: destination, full-system scope, space, and the no-cancel notice");
  await dismiss();
  await P.goto(BASE + "/settings/backup?view=points");
  await P.waitForSelector(".points-table");
  await capture(P, "backup-points.png", "Recovery points with copies per destination and actions");
  await P.click(".points-table tbody tr >> nth=0 >> button:has-text('Delete')");
  await P.waitForSelector("[role=dialog] >> text=This is a protected deletion");
  await capture(P, "backup-delete-dialog.png", "Protected deletion: dependants, coverage and step-up");
  await dismiss();
  await P.goto(BASE + "/settings/backup?view=key");
  await P.waitForSelector("text=Emergency Recovery Package");
  await capture(P, "backup-key.png", "Recovery Key page: key hidden, readiness, export and rotation");
  await P.click("button:has-text('Reveal Recovery Key…')");
  await P.waitForSelector("[role=dialog] #su-pw");
  await capture(P, "backup-stepup.png", "Step-up confirmation before revealing the Recovery Key");
  await dismiss();
  await P.goto(BASE + "/recovery");
  await P.waitForSelector(".recovery-doc");
  await capture(P, "recovery-explorer.png", "Recovery Explorer: restore points, folders, documents and versions");
  await P.locator(".recovery-doc button:has-text('Restore…')").first().click();
  await P.click("[role=dialog] button:has-text('Analyse impact')");
  await P.waitForSelector("[role=dialog] >> text=Restore Impact Analysis");
  await capture(P, "recovery-impact.png", "Restore Impact Analysis before anything changes");
  await dismiss();
  await P.goto(BASE + "/settings/account?tab=notifications");
  await P.waitForSelector("#routing");
  await P.locator("#routing").scrollIntoViewIfNeeded();
  await capture(P, "notifications-routing.png", "Routing by category: channels, fallback chain and digests");
  await P.waitForSelector("#discord");
  await P.locator("#discord").scrollIntoViewIfNeeded();
  await capture(P, "notifications-channels.png", "Discord webhook and WhatsApp Personal (experimental) cards");
  await P.goto(BASE + "/settings/notifications");
  await P.waitForSelector("text=Notification delivery health");
  await P.locator("text=Notification delivery health").scrollIntoViewIfNeeded();
  await capture(P, "admin-delivery-health.png", "Notification delivery health for administrators (counts only)");
  await P.goto(BASE + "/settings/activity?view=map");
  await P.waitForSelector("td:has-text('Home')");
  await capture(P, "security-trusted-zones.png", "Trusted Zones with several networks and a configured map pin");
  // a second device so the device list has something to distrust
  const other = await session({ width: 1280, height: 800 });
  await other.ctx.close();
  // the real OpenFreeMap vector map (English labels), drawn by this browser through the proxy
  await api(P, "/api/settings", { method: "PUT", body: { values: { "security.map_enabled": true, "security.map_provider": "openfreemap" } } });
  await P.goto(BASE + "/settings/account?tab=signins");
  await P.waitForSelector(".signin-map[data-labels=en]", { timeout: 30000 });
  await P.waitForTimeout(5000); // vector tiles and fonts
  await P.locator(".map-cluster, .signin-map path.leaflet-interactive").first().hover().catch(() => undefined);
  await capture(P, "security-signin-map.png", "Sign-in map: English place names, grouped sign-ins with a count, hover summary and the filters");
  await P.locator(".signin-list tbody tr").first().click();
  await P.waitForSelector(".signin-detail");
  await capture(P, "security-signin-details.png", "Sign-in details next to the map after selecting a sign-in (the list and map stay in sync)");
  await P.locator("#devices").scrollIntoViewIfNeeded();
  const mark = P.locator("#devices button:has-text('Mark Unrecognized')").first();
  if (await mark.count()) { await mark.click(); await P.waitForSelector("[role=dialog] >> text=Mark this device Unrecognized?"); }
  await capture(P, "security-devices.png", "Mark Unrecognized: sessions end, follow-up actions are offered");
  await dismiss();
});

await step("AT-354 Change Set U documentation screenshots (folder tree, map provider, Map unavailable, WhatsApp bridge, sign-in design)", async () => {
  // state from corrective.mjs: nested synthetic folders, the fake WhatsApp bridge running and WhatsApp turned on
  const P = D.page;
  // card headings start below the sticky top bar; toasts from the actions have closed
  const toTop = (page, sel) => page.locator(sel).evaluate((el) => { el.style.scrollMarginTop = "120px"; el.scrollIntoView({ block: "start" }); });
  const noToast = (page) => page.waitForSelector(".toast", { state: "detached", timeout: 15000 }).catch(() => undefined);
  const deep = (await api(P, "/api/folders")).data.folders.find((f) => f.name.startsWith("A very long synthetic folder name"));
  expect(deep, "run corrective.mjs first (nested folders)");
  // a tree pane widened with the divider (stored per account on this device), as the guide suggests for deep trees
  const uid = (await api(P, "/api/session")).data.user.id;
  await P.evaluate((k) => localStorage.setItem(k, JSON.stringify({ tree: 400 })), `pd-panels-${uid}`);
  await P.goto(`${BASE}/folders/${deep.id}`);
  await P.waitForSelector(".tree-node.active .tree-label:has-text('A very long')");
  await capture(P, "folders-tree.png", "Folder tree: expander, icon and name columns line up at every level; long names wrap");
  await P.evaluate((k) => localStorage.removeItem(k), `pd-panels-${uid}`);
  // tile requests are answered locally for these two captures, so the result does not depend on a real provider
  const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
  const ok = await session({ width: 1440, height: 900 });
  await ok.ctx.route("https://tile.openstreetmap.org/**", (r) => r.fulfill({ status: 200, contentType: "image/png", body: PNG, headers: { "Access-Control-Allow-Origin": "*" } }));
  await ok.ctx.route("https://tiles.openfreemap.org/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ version: 8, sources: {}, layers: [] }), headers: { "Access-Control-Allow-Origin": "*" } }));
  await ok.page.goto(BASE + "/settings/security?view=access");
  await ok.page.locator("#map-provider").scrollIntoViewIfNeeded();
  await ok.page.click("#map-provider button:has-text('Test Map Provider')");
  await ok.page.waitForSelector("#map-provider .badge:has-text('Working')");
  await noToast(ok.page);
  await toTop(ok.page, "#map-provider");
  await capture(ok.page, "security-map-provider.png", "Sign-in map provider: preset, key, Test Map Provider and the last result");
  await ok.ctx.close();
  const blocked = await session({ width: 1440, height: 900 });
  await blocked.ctx.route("https://tiles.openfreemap.org/**", (r) => r.fulfill({ status: 403, contentType: "text/plain", body: "blocked", headers: { "Access-Control-Allow-Origin": "*" } }));
  await blocked.ctx.route("https://tile.openstreetmap.org/**", (r) => r.fulfill({ status: 403, contentType: "text/plain", body: "blocked", headers: { "Access-Control-Allow-Origin": "*" } }));
  await blocked.page.goto(BASE + "/settings/account?tab=signins");
  await blocked.page.waitForSelector(".map-unavailable");
  await capture(blocked.page, "security-map-unavailable.png", "Map unavailable (HTTP 403): the reason, the fix, and the sign-in list still works");
  await blocked.ctx.close();
  await P.goto(BASE + "/settings/connections");
  await P.waitForSelector("#conn-whatsapp [data-bridge-state]");
  await toTop(P, "#conn-whatsapp");
  await capture(P, "connections-whatsapp.png", "WhatsApp Personal: bridge service installed, running, version, protocol and compatibility");
  await P.click("#wa-diagnostics button:has-text('Run Diagnostics')");
  await P.waitForSelector("#wa-diagnostics .diag-table");
  await toTop(P, "#wa-diagnostics");
  await capture(P, "whatsapp-diagnostics.png", "WhatsApp diagnostics (main administrator): versions, DNS, network, system time, storage, per-person state; no secrets");
  if (process.env.WA_BRIDGE && process.env.WA_TOKEN) {
    // linking progress after the (fake) scan: the stages, never a QR code
    const wa = (path, body) => fetch(process.env.WA_BRIDGE + path, { method: "POST", headers: { Authorization: `Bearer ${process.env.WA_TOKEN}`, "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    await P.goto(BASE + "/settings/account?tab=notifications");
    await P.waitForSelector("#whatsapp[data-state]");
    if (await P.locator("#whatsapp button:has-text('Unlink')").count()) { await P.click("#whatsapp button:has-text('Unlink')"); await P.waitForSelector("#whatsapp[data-state=not_linked]"); }
    await P.click("#whatsapp button:has-text('Link WhatsApp')");
    await P.waitForSelector("#whatsapp[data-stage=qr_ready]");
    await wa("/_test/stage", { session: "pending", stage: "authenticating" });
    await P.waitForSelector("#whatsapp[data-stage=authenticating]", { timeout: 10000 });
    expect(!(await P.locator("#whatsapp .qr").count()), "QR code on a screenshot");
    await toTop(P, "#whatsapp");
    await capture(P, "whatsapp-linking.png", "Linking WhatsApp: live stages after the phone scanned the code");
    await wa("/_test/connect/pending");
    await P.waitForSelector("#whatsapp[data-key=verified]", { timeout: 15000 });
    await capture(P, "whatsapp-verified.png", "Linked & Verified, with Send Test Notification, Reconnect and Unlink");
  }
  await P.goto(BASE + "/settings/overview");
  await P.waitForSelector(".design-grid");
  await P.click(".design-option:has-text('Nature')");
  await P.waitForSelector(".design-actions button:has-text('Set as Active')");
  await P.locator(".design-grid").scrollIntoViewIfNeeded();
  await capture(P, "settings-login-design.png", "Named sign-in designs: built-in and custom designs, the actions and the live preview");
  // the editor of a custom design with a plain drawn wallpaper (no photo), created here if needed
  const mine = await P.evaluate(async () => {
    const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
    const list = await (await fetch("/api/signin-designs")).json();
    let d = list.designs.find((x) => x.name === "Spring meadow" && x.has_wallpaper);
    if (d) return d;
    d = await (await fetch("/api/signin-designs", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: JSON.stringify({ name: "Spring meadow", template: "nature" }) })).json();
    const c = document.createElement("canvas"); c.width = 1600; c.height = 1000;
    const g = c.getContext("2d");
    const sky = g.createLinearGradient(0, 0, 0, 1000); sky.addColorStop(0, "#e6f3e0"); sky.addColorStop(1, "#b9dcae");
    g.fillStyle = sky; g.fillRect(0, 0, 1600, 1000);
    g.fillStyle = "#7fb36f"; g.beginPath(); g.ellipse(500, 1000, 900, 300, 0, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#4f8a44"; g.beginPath(); g.ellipse(1300, 1050, 700, 280, 0, 0, Math.PI * 2); g.fill();
    const blob = await new Promise((r) => c.toBlob(r, "image/png"));
    const fd = new FormData(); fd.append("file", blob, "meadow.png");
    return (await fetch(`/api/signin-designs/${d.id}/wallpaper`, { method: "POST", headers: { "X-CSRFToken": csrf }, body: fd })).json();
  });
  await P.reload();
  await P.waitForSelector(".design-grid");
  if (mine && mine.id) {
    await P.click(`.design-option[data-design-id='${mine.id}']`);
    await P.click(".design-actions button:has-text('Edit')");
    await P.waitForSelector("[role=dialog] .design-editor");
    await capture(P, "settings-login-design-editor.png", "Design editor: focal point, overlay, colour mode and palette with the device preview");
    await P.keyboard.press("Escape");
  }
});

await step("AT-499 Change Set AB documentation screenshots (Maintenance & Operations, jobs, repair plan, Active Sessions)", async () => {
  const SC = process.env.MAINT_SCENARIO;
  expect(SC, "MAINT_SCENARIO not set (run through scripts/e2e.sh)");
  const p = D.page;
  const jobs = async (q) => (await api(p, `/api/maintenance/jobs?${q}`)).data.jobs;
  await p.goto(BASE + "/settings/system");
  await p.waitForSelector("[data-maintenance] [data-panel=storage]");
  await capture(p, "maintenance-operations.png", "Settings → System → Maintenance & Operations: update check, Update Application, Doctor, Repair, restart and caches");
  // a running upgrade: the live steps while it runs (scripted root command, see tests/e2e/maint_helper.py)
  fs.writeFileSync(SC, "slow");
  await api(p, "/api/backup/stepup", { body: { password: PW } });
  const up = await api(p, "/api/maintenance/run/upgrade", { body: { confirm: true } });
  expect(up.status === 202, `upgrade start ${up.status}`);
  await p.goto(`${BASE}/settings/system?job=${up.data.id}`);
  await p.waitForSelector(".modal [data-step=backup][data-step-status=succeeded] ~ [data-step-status=running], .modal [data-step=backup_verify][data-step-status=running], .modal [data-step=fetch][data-step-status=running]", { timeout: 90000 });
  await capture(p, "maintenance-upgrade-running.png", "A running upgrade: each step with its status and duration, live");
  await p.waitForSelector(".modal [data-job][data-job-status=succeeded]", { timeout: 120000 });
  // a failed upgrade with Technical Details
  fs.writeFileSync(SC, "fail-disk");
  await api(p, "/api/backup/stepup", { body: { password: PW } });
  const bad = await api(p, "/api/maintenance/run/upgrade", { body: { confirm: true } });
  await p.goto(`${BASE}/settings/system?job=${bad.data.id}`);
  await p.waitForSelector(".modal [data-job][data-job-status=failed]", { timeout: 60000 });
  await p.click(".modal [data-technical]");
  await p.waitForSelector(".modal [data-technical-details]");
  await capture(p, "maintenance-upgrade-failed.png", "Upgrade Failed — Existing Version Remains Operational, with Technical Details");
  fs.writeFileSync(SC, "ok");
  // Doctor results
  const doc = (await jobs("operation=doctor"))[0] || (await api(p, "/api/maintenance/doctor", { method: "POST" })).data;
  await p.goto(`${BASE}/settings/system?job=${doc.id}`);
  await p.waitForSelector(".modal [data-doctor] [data-component]", { timeout: 120000 });
  await capture(p, "maintenance-doctor.png", "Doctor: read-only checks grouped by component, PASS / WARNING / FAIL / NOT CONFIGURED");
  // Repair Plan waiting for confirmation (a missing data directory), then cancelled
  fs.rmSync(`${process.env.PD_DATA_DIR}/tmp`, { recursive: true, force: true });
  const rep = await api(p, "/api/maintenance/run/repair", { body: {} });
  await p.goto(`${BASE}/settings/system?job=${rep.data.id}`);
  await p.waitForSelector(".modal [data-job-status=waiting_confirmation] [data-plan-item=directories]", { timeout: 120000 });
  await capture(p, "maintenance-repair-plan.png", "Repair Plan: problem, proposed repair, affected files and services, restart, backup and risk — before any change");
  await api(p, `/api/maintenance/jobs/${rep.data.id}/cancel`, { method: "POST" });
  fs.mkdirSync(`${process.env.PD_DATA_DIR}/tmp`, { recursive: true });
  // Job History
  await p.goto(BASE + "/settings/system");
  await p.locator("[data-job-history]").scrollIntoViewIfNeeded();
  await p.waitForSelector("[data-job-history] [data-history-job]");
  await capture(p, "maintenance-history.png", "Maintenance Job History with operation, status and date filters");
  // Active Sessions (the sessions the earlier suites signed in)
  await p.goto(BASE + "/");
  await p.locator("[data-widget=sessions]").scrollIntoViewIfNeeded();
  await p.waitForSelector("[data-widget=sessions] [data-sessions-tile]");
  await capture(p, "active-sessions-tile.png", "The Active Sessions tile on the Overview: Active, Signed In and Untrusted counts and recent sessions");
  await p.goto(BASE + "/settings/security?view=sessions");
  await p.waitForSelector("[data-active-sessions] [data-session-table]");
  await capture(p, "active-sessions.png", "Settings → Security → Active Sessions: state, address, trust, approximate location, device and risk, with filters");
  await p.locator("[data-session-table] tbody tr").first().click();
  await p.waitForSelector(".modal [data-session-detail]");
  await capture(p, "active-sessions-detail.png", "Session details with Terminate Session (main administrator)");
  await p.keyboard.press("Escape");
});

await step("AT-334 guide screenshots load in Help (after capture)", async () => {
  const P = D.page;
  for (const slug of ["backup-restore", "notifications", "security-map", "discord", "whatsapp-personal", "login-designs", "getting-started"]) {
    await P.goto(BASE + "/help/" + slug);
    await P.waitForSelector(".breadcrumbs");
    expect(await P.locator("img.doc-shot").count() > 0, `${slug}: screenshots next to the steps`);
    // guide images are lazy-loaded, so load and decode each one explicitly instead of waiting for off-screen ones
    const bad = await P.evaluate(async () => {
      const out = [];
      for (const img of document.querySelectorAll("img.doc-shot")) {
        const probe = new Image();
        probe.src = img.currentSrc || img.src;
        try { await probe.decode(); if (!probe.naturalWidth) out.push(img.alt); } catch { out.push(img.alt); }
      }
      return out;
    });
    expect(!bad.length, `${slug}: images that do not load: ${bad.join("; ")}`);
  }
});

await D.ctx.close();
await browser.close();
fs.writeFileSync(`${SHOTS}/../screenshot-manifest.json`, JSON.stringify(manifest, null, 1) + "\n");
fs.mkdirSync("tests/e2e/out", { recursive: true });
fs.writeFileSync("tests/e2e/out/screenshots-results.json", JSON.stringify(results, null, 1));
console.log(`\nscreenshots: ${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
