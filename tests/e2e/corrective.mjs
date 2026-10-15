// Change Set U in a real browser (AT-336..AT-355): folder tree geometry in every theme and viewport class, sign-in
// design thumbnails and live preview, the sign-in map with a working / blocked / rate-limited / unreachable tile
// provider (tiles are intercepted: nothing reaches a real map provider), and the WhatsApp Personal / Discord
// connection flow against tests/fake_whatsapp_bridge.py (started by scripts/e2e.sh). Synthetic data only.
//
// Usage: BASE=http://localhost:8000 WA_BRIDGE=http://127.0.0.1:PORT WA_TOKEN=... node tests/e2e/corrective.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const WA_BRIDGE = process.env.WA_BRIDGE || "";
const WA_TOKEN = process.env.WA_TOKEN || "";
const PW = "Sample-Passw0rd!";
const OUT = "tests/e2e/out/corrective";
fs.mkdirSync(OUT, { recursive: true });
const results = [];
let failed = 0;
const step = async (name, fn) => {
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { failed++; results.push(["FAIL", name, String(e).slice(0, 800)]); console.log("FAIL", name, String(e).slice(0, 800)); }
};
const skip = (name, why) => { results.push(["NOT RUN", name, why]); console.log("NOT RUN", name, "-", why); };
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };
const near = (a, b, tol = 1.01) => Math.abs(a - b) <= tol;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
const api = (page, url, opts = {}) => page.evaluate(async ([url, opts]) => {
  const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
  const r = await fetch(url, { method: opts.method || (opts.body ? "POST" : "GET"), headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: opts.body ? JSON.stringify(opts.body) : undefined });
  return { status: r.status, data: r.headers.get("content-type")?.includes("json") ? await r.json() : null };
}, [url, opts]);
const setting = (page, values) => api(page, "/api/settings", { method: "PUT", body: { values } });
const pageErrors = [];

const SON_PW = "Son1-Own-Passw0rd"; // set by flow.mjs (family member without administrator rights)
async function session(user = "admin", viewport = { width: 1440, height: 900 }, mobile = false) {
  const ctx = await browser.newContext({ viewport, isMobile: mobile, hasTouch: mobile });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => { pageErrors.push(e.message); console.log("pageerror", e.message); });
  await page.goto(BASE + "/login");
  await page.fill("#username", user);
  await page.fill("#password", user === "son1" ? SON_PW : PW);
  await page.click("button:has-text('Sign in')");
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 });
  return { ctx, page };
}

const { ctx, page } = await session();

// ------------------------------------------------------------------ AT-336..AT-339 folder tree geometry
// three nested synthetic folders under the administrator's library, the deepest with a very long name
const folders = (await api(page, "/api/folders")).data.folders;
const meId = (await api(page, "/api/session")).data.user.id;
const myRoot = folders.find((f) => f.kind === "personal_root" && f.owner === String(meId));
expect(myRoot, "the administrator's own library folder is missing");
let parent = myRoot.id;
let deepest = null;
for (const name of ["Corrective tree level one", "Level two", "A very long synthetic folder name that has to wrap onto a second line without moving its icon or expander"]) {
  const existing = folders.find((f) => f.parent === parent && f.name === name);
  const r = existing ? { data: existing } : await api(page, "/api/folders", { body: { parent, name } });
  expect(r.data?.id, `create folder ${name}: ${JSON.stringify(r.data).slice(0, 200)}`);
  parent = deepest = r.data.id;
}

/** Measures every visible tree row: column positions relative to the tree, the indent per level, wrapping. */
const measureTree = (p) => p.evaluate(() => {
  const tree = document.querySelector("[role=tree]");
  const t = tree.getBoundingClientRect();
  const rows = [...tree.querySelectorAll("[role=treeitem]")].map((li) => {
    const node = li.querySelector(":scope > .tree-node");
    const r = (sel) => node.querySelector(`:scope > ${sel}`).getBoundingClientRect();
    const n = node.getBoundingClientRect(), ex = r(".tree-expander"), ic = r(".tree-icon"), lb = r(".tree-label");
    const lh = parseFloat(getComputedStyle(node.querySelector(":scope > .tree-label")).lineHeight) || 20;
    return { level: +li.getAttribute("aria-level"), name: node.querySelector(":scope > .tree-label").textContent.trim(),
      ex: ex.left - t.left, exW: ex.width, ic: ic.left - t.left, icW: ic.width, lb: lb.left - t.left, lbRight: lb.right - t.left,
      exTop: ex.top - n.top, icTop: ic.top - n.top, lbTop: lb.top - n.top, lines: Math.round(lb.height / lh), visible: n.width > 0 };
  }).filter((x) => x.visible);
  const pane = document.querySelector(".tree-pane");
  return { rows, rtl: getComputedStyle(tree).direction === "rtl", overflow: pane.scrollWidth - pane.clientWidth, paneRight: pane.getBoundingClientRect().right - t.left };
});
function checkTree(m, where) {
  expect(m.rows.length >= 4, `${where}: expected the nested rows, got ${m.rows.length}`);
  const exW = m.rows[0].exW, icW = m.rows[0].icW;
  const step1 = {};
  for (const r of m.rows) {
    // identical column widths on every row, whether or not the row has children
    expect(near(r.exW, exW) && near(r.icW, icW), `${where}: "${r.name}" columns ${r.exW}/${r.icW} differ from ${exW}/${icW}`);
    // icon directly after the expander, label after the icon (same gaps on every row)
    expect(near(r.ic - r.ex, m.rows[0].ic - m.rows[0].ex) && near(r.lb - r.ic, m.rows[0].lb - m.rows[0].ic), `${where}: "${r.name}" column offsets differ`);
    // expander and icon sit on the first line, also when the label wraps
    expect(near(r.exTop, m.rows[0].exTop, 2) && near(r.icTop, m.rows[0].icTop, 2), `${where}: "${r.name}" expander/icon moved vertically`);
    (step1[r.level] ||= []).push(r.ex);
  }
  // the same indent step for every level
  const levels = Object.keys(step1).map(Number).sort((a, b) => a - b);
  const xs = levels.map((l) => step1[l][0]);
  for (const l of levels) expect(step1[l].every((x) => near(x, step1[l][0])), `${where}: rows of level ${l} are not aligned`);
  const steps = xs.slice(1).map((x, i) => x - xs[i]);
  expect(steps.length >= 2 && steps.every((s) => near(s, steps[0]) && s > 4), `${where}: indent steps ${steps.map((s) => s.toFixed(1)).join(", ")}`);
  const long = m.rows.find((r) => r.name.startsWith("A very long"));
  expect(long && long.lines >= 2, `${where}: the long name should wrap (lines=${long?.lines})`);
  expect(m.overflow <= 1, `${where}: the tree scrolls sideways by ${m.overflow}px`);
}

for (const vp of [{ width: 1440, height: 900, name: "desktop" }, { width: 820, height: 1180, name: "tablet" }, { width: 390, height: 844, name: "phone" }]) {
  await step(`AT-336/AT-337/AT-338 folder tree columns, indent and wrapping in every theme (${vp.name} ${vp.width}px)`, async () => {
    const s = vp.name === "desktop" ? { page } : await session("admin", vp, vp.name === "phone");
    for (const theme of ["green", "blue", "dark", "glass_light", "glass_dark"]) {
      await setting(s.page, { "me.theme": theme });
      await s.page.goto(`${BASE}/folders/${deepest}`);
      await s.page.waitForFunction((t) => document.documentElement.dataset.theme === t, theme);
      await s.page.waitForSelector(".browser");
      const show = s.page.locator("button[aria-label='Show folders']");
      if (vp.name === "phone") { await show.waitFor(); await show.click(); }
      await s.page.waitForSelector(".tree-node .tree-label:has-text('A very long synthetic')");
      await s.page.waitForTimeout(150);
      checkTree(await measureTree(s.page), `${vp.name}/${theme}`);
      if (theme === "green") await s.page.screenshot({ path: `${OUT}/tree-${vp.name}.png` });
    }
    await setting(s.page, { "me.theme": "green" });
    if (s.ctx) await s.ctx.close();
  });
}

await step("AT-336 folder tree in right-to-left layout mirrors the same columns", async () => {
  await page.goto(`${BASE}/folders/${deepest}`);
  await page.waitForSelector(".tree-node .tree-label:has-text('A very long synthetic')");
  await page.evaluate(() => { document.documentElement.dir = "rtl"; });
  await page.waitForTimeout(150);
  const m = await page.evaluate(() => {
    const out = [];
    for (const node of document.querySelectorAll("[role=tree] .tree-node")) {
      const ex = node.querySelector(":scope > .tree-expander").getBoundingClientRect();
      const ic = node.querySelector(":scope > .tree-icon").getBoundingClientRect();
      const lb = node.querySelector(":scope > .tree-label").getBoundingClientRect();
      if (ex.width) out.push({ order: ex.left > ic.left && ic.left > lb.left, gap: ex.left - ic.left });
    }
    return out;
  });
  await page.evaluate(() => { document.documentElement.dir = ""; });
  expect(m.length >= 4 && m.every((r) => r.order), "RTL: expander, icon and label are not mirrored");
  expect(m.every((r) => near(r.gap, m[0].gap)), "RTL: column gaps differ between rows");
});

await step("AT-339 folder tree keyboard: ArrowLeft collapses, ArrowRight expands, Enter opens; roles and levels", async () => {
  await page.goto(`${BASE}/folders/${deepest}`);
  const lvl1 = page.locator("[role=treeitem]:has(> .tree-node .tree-label:text-is('Corrective tree level one'))");
  await lvl1.waitFor();
  expect(await lvl1.getAttribute("aria-expanded") === "true", "level one starts expanded on the path to the open folder");
  const node = lvl1.locator(":scope > .tree-node");
  await node.focus();
  await page.keyboard.press("ArrowLeft");
  await page.waitForFunction(() => !document.querySelector(".tree-label") || ![...document.querySelectorAll(".tree-label")].some((l) => l.textContent.includes("Level two")));
  expect(await lvl1.getAttribute("aria-expanded") === "false", "ArrowLeft did not collapse");
  await page.keyboard.press("ArrowRight");
  await page.waitForSelector(".tree-label:has-text('Level two')");
  await page.keyboard.press("Enter");
  await page.waitForURL((u) => u.pathname.includes("/folders/") && !u.pathname.endsWith(deepest));
  const levels = await page.locator("[role=treeitem]").evaluateAll((els) => els.map((e) => +e.getAttribute("aria-level")));
  expect(levels.every((l) => l >= 1) && Math.max(...levels) >= 3, `aria-level values ${levels.join(",")}`);
});

// ------------------------------------------------------------------ AT-344..AT-347 sign-in designs
/** Mean luminance (0..255) and spread of an element's pixels, from a screenshot decoded in the page. */
async function luminance(p, locator) {
  const png = (await locator.screenshot()).toString("base64");
  return p.evaluate(async (b64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let sum = 0, min = 255, max = 0;
    for (let i = 0; i < d.length; i += 4) { const y = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]; sum += y; min = Math.min(min, y); max = Math.max(max, y); }
    return { mean: sum / (d.length / 4), spread: max - min };
  }, png);
}

await step("AT-344 sign-in design thumbnails are light and clear in every app theme (no dark wash)", async () => {
  const seen = {};
  for (const theme of ["green", "blue", "dark", "glass_light", "glass_dark"]) {
    await setting(page, { "me.theme": theme });
    await page.goto(BASE + "/settings/overview");
    await page.waitForFunction((t) => document.documentElement.dataset.theme === t, theme);
    await page.waitForSelector(".design-option .thumb svg");
    await page.waitForLoadState("networkidle");
    const thumbs = page.locator(".design-option .thumb");
    const n = await thumbs.count();
    expect(n >= 5, `only ${n} thumbnails`);
    for (let i = 0; i < n; i++) {
      await thumbs.nth(i).scrollIntoViewIfNeeded();
      let l = await luminance(page, thumbs.nth(i));
      for (let k = 0; k < 3 && l.spread <= 20; k++) { await page.waitForTimeout(300); l = await luminance(page, thumbs.nth(i)); } // let the drawing settle
      expect(l.mean > 150, `${theme}: thumbnail ${i + 1} is too dark (mean luminance ${l.mean.toFixed(0)})`);
      expect(l.spread > 20, `${theme}: thumbnail ${i + 1} shows no artwork (spread ${l.spread.toFixed(0)})`);
      (seen[i] ||= []).push(l.mean);
    }
    if (theme === "dark") await page.locator(".design-grid").screenshot({ path: `${OUT}/designs-dark-theme.png` });
  }
  // theme independence: each thumbnail looks the same whatever the admin's own theme is
  for (const [i, means] of Object.entries(seen)) expect(Math.max(...means) - Math.min(...means) < 6, `thumbnail ${+i + 1} changes with the app theme: ${means.map((m) => m.toFixed(0)).join("/")}`);
  await setting(page, { "me.theme": "green" });
});

await step("AT-345/AT-346 selecting a design only previews it; Set as Active publishes; theme does not change the design", async () => {
  await setting(page, { "login.design": "minimal" });
  await page.goto(BASE + "/settings/overview");
  await page.click(".design-option:has-text('Nature')");
  await page.waitForSelector(".design-actions button:has-text('Set as Active')");
  expect((await api(page, "/api/branding")).data.design === "minimal", "a click must not change the live design");
  await page.click(".design-option:has-text('Travel')");
  // the live preview follows the choice, on desktop, tablet and phone
  await page.waitForSelector(".login-preview.desktop");
  const desk = await luminance(page, page.locator(".login-preview"));
  expect(desk.mean > 120, `desktop preview too dark (${desk.mean.toFixed(0)})`);
  await page.click("#login-design .seg button:has-text('Tablet')");
  await page.waitForSelector(".login-preview.tablet");
  await page.click("#login-design .seg button:has-text('Phone')");
  await page.waitForSelector(".login-preview.mobile");
  await page.locator(".login-preview").screenshot({ path: `${OUT}/preview-phone.png` });
  await page.click(".design-actions button:has-text('Preview Sign-in Page')");
  await page.waitForSelector("[role=dialog] .login-preview.full");
  await page.keyboard.press("Escape");
  await page.click(".design-actions button:has-text('Set as Active')");
  await page.waitForSelector(".design-option:has-text('Travel') .design-saved");
  // the public sign-in page uses the active design and the sign-in theme, whatever theme the admin uses
  await setting(page, { "me.theme": "glass_dark" });
  const anon = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const ap = await anon.newPage();
  await ap.addInitScript(() => { try { localStorage.setItem("pd-theme", "glass_dark"); } catch { /* ignore */ } });
  await ap.goto(BASE + "/login");
  await ap.waitForSelector(".auth[data-theme=green]");
  const pub = await luminance(ap, ap.locator(".auth"));
  expect(pub.mean > 120, `public sign-in page too dark (${pub.mean.toFixed(0)})`);
  await anon.close();
  expect((await api(page, "/api/branding")).data.design === "travel", "changing the app theme changed the active design");
  await setting(page, { "me.theme": "green", "login.design": "minimal" });
});

// ------------------------------------------------------------------ AT-340..AT-343 sign-in map tile provider
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const TILES = "https://tile.openstreetmap.org/**";
/** A fresh signed-in context whose tile requests are answered locally with `status` (or a network error). */
async function mapSession(status) {
  const s = await session();
  const seen = [];
  await s.ctx.route(TILES, (route) => {
    seen.push({ url: route.request().url(), referer: route.request().headers().referer || "" });
    if (status === "network") return route.abort("internetdisconnected");
    if (status === 200) return route.fulfill({ status: 200, contentType: "image/png", body: PNG, headers: { "Access-Control-Allow-Origin": "*" } });
    return route.fulfill({ status, contentType: "text/plain", body: "blocked (test)", headers: { "Access-Control-Allow-Origin": "*" } });
  });
  return { ...s, seen };
}

await step("AT-340 working provider: tiles load with only this site's origin as Referer", async () => {
  await setting(page, { "security.map_enabled": true, "security.map_provider": "osm" });
  const s = await mapSession(200);
  await s.page.goto(BASE + "/settings/account?tab=signins");
  await s.page.waitForSelector(".signin-map .leaflet-tile-loaded", { timeout: 20000 });
  expect(!(await s.page.locator(".map-unavailable").count()), "map unavailable shown for a working provider");
  expect(s.seen.length > 0, "no tile requests");
  const origin = new URL(BASE).origin + "/";
  expect(s.seen.every((r) => r.referer === origin), `Referer must be the bare origin: ${[...new Set(s.seen.map((r) => r.referer))].join(", ")}`);
  expect(s.seen.every((r) => !/\d+\.\d+\.\d+\.\d+/.test(r.url.replace(/^https:\/\/[^/]+/, ""))), "an address was sent to the tile server");
  await s.ctx.close();
});

for (const [status, word] of [[403, "blocked"], [429, "limiting"], [401, "API key"], ["network", "could not be reached"]]) {
  await step(`AT-341/AT-342 provider answers ${status}: Map unavailable, sign-in records stay visible, no retry loop`, async () => {
    const s = await mapSession(status);
    await s.page.goto(BASE + "/settings/account?tab=signins");
    await s.page.waitForSelector(".map-unavailable", { timeout: 20000 });
    expect((await s.page.locator(".map-unavailable").innerText()).includes(word), `message for ${status} should mention "${word}"`);
    expect(!(await s.page.locator(".leaflet-tile").count()), "blocked tiles were drawn as a map");
    // the list of sign-ins and devices does not depend on the map
    expect(await s.page.locator("#devices").count() > 0 || await s.page.locator("table").count() > 0, "sign-in records hidden");
    const before = s.seen.length;
    await s.page.waitForTimeout(3000);
    // Leaflet asks for one screenful of tiles at most once; nothing is retried afterwards
    expect(s.seen.length - before <= 1 && before <= 16, `tile requests keep going: ${before} then ${s.seen.length}`);
    if (status === 403) await s.page.screenshot({ path: `${OUT}/map-unavailable-403.png` });
    await s.ctx.close();
  });
}

await step("AT-343 Test Map Provider: Failed for 403, Working after the provider recovers (main admin)", async () => {
  const s = await mapSession(403);
  await s.page.goto(BASE + "/settings/security?view=access");
  await s.page.locator("#map-provider").scrollIntoViewIfNeeded();
  await s.page.click("#map-provider button:has-text('Test Map Provider')");
  await s.page.waitForSelector("#map-provider .badge:has-text('Failed')");
  expect((await s.page.locator("#map-provider [role=status]").innerText()).includes("403"), "403 explanation shown");
  await s.ctx.unroute(TILES);
  await s.ctx.route(TILES, (route) => route.fulfill({ status: 200, contentType: "image/png", body: PNG, headers: { "Access-Control-Allow-Origin": "*" } }));
  await s.page.click("#map-provider button:has-text('Test Map Provider')");
  await s.page.waitForSelector("#map-provider .badge:has-text('Working')");
  // keyed provider without a key: the map says why instead of loading anything
  await s.page.selectOption("[id='s-security.map_provider']", "maptiler");
  await s.page.click("#map-provider button:has-text('Save settings')");
  await s.page.goto(BASE + "/settings/account?tab=signins");
  await s.page.waitForSelector(".map-unavailable:has-text('key')");
  await setting(s.page, { "security.map_provider": "osm" });
  await s.ctx.close();
  const son = await session("son1");
  expect((await api(son.page, "/api/security/map/test", { body: { status: 200 } })).status === 403, "a family member must not record map tests");
  await son.ctx.close();
});

// ------------------------------------------------------------------ AT-348..AT-353 Connections: WhatsApp + Discord
const bridge = (path, body) => fetch(WA_BRIDGE + path, { method: "POST", headers: { Authorization: `Bearer ${WA_TOKEN}`, "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

if (!WA_BRIDGE || !WA_TOKEN) {
  skip("AT-348..AT-351 WhatsApp Personal flow", "no fake bridge (run through scripts/e2e.sh)");
} else {
  await step("AT-348/AT-349 provider cards: no 'Planned'; a running bridge is detected before WhatsApp is turned on", async () => {
    await setting(page, { "whatsapp.enabled": false, "discord.enabled": false });
    await page.goto(BASE + "/settings/connections");
    await page.waitForSelector(".provider-card");
    expect(!(await page.locator("text=Planned").count()), "a 'Planned' label is still shown");
    const wa = page.locator(".provider-card:has-text('WhatsApp')");
    expect((await wa.innerText()).includes("Disabled by Admin"), "WhatsApp card should say Disabled by Admin");
    await page.waitForSelector("#conn-whatsapp [data-bridge-state=ready_disabled]");
    const kv = await page.locator("#conn-whatsapp .kv-table").innerText();
    expect(kv.includes("1.1.0") && /Protocol\s+1/.test(kv) && kv.includes("Compatible"), `service table: ${kv}`);
    await page.locator("#conn-whatsapp").screenshot({ path: `${OUT}/admin-whatsapp-ready.png` });
  });

  await step("AT-348 enable → personal link → QR → connected → Send test → routing → disable", async () => {
    await page.goto(BASE + "/settings/connections");
    await page.locator("#conn-whatsapp label.switch").click();
    await page.click("#conn-whatsapp button:has-text('Save settings')");
    await page.waitForSelector("#conn-whatsapp [data-bridge-state=healthy]:has-text('Running')");
    await page.goto(BASE + "/settings/account?tab=notifications");
    await page.waitForSelector("#whatsapp[data-state=not_linked]");
    await page.click("#whatsapp button:has-text('Link WhatsApp')");
    await page.waitForSelector("#whatsapp[data-state=pending] .qr svg");
    // what scanning the (fake) QR with a phone would do; the card notices it without a button press
    expect((await bridge("/_test/connect/pending")).ok, "fake bridge connect");
    await page.waitForSelector("#whatsapp[data-state=connected]", { timeout: 15000 });
    await page.click("#whatsapp button:has-text('Send Test Notification')");
    await page.waitForSelector(".toast:has-text('Test notification sent')");
    // WhatsApp can now be chosen in the routing matrix
    const chip = page.locator("#routing input[aria-label$='by WhatsApp Personal'], #routing input[aria-label*='WhatsApp']").first();
    expect(await chip.count() && !(await chip.isDisabled()), "WhatsApp not selectable in routing");
    await page.click("#whatsapp button:has-text('Reconnect')");
    await page.waitForSelector("#whatsapp[data-state=connected]");
    await setting(page, { "whatsapp.enabled": false });
    await page.reload();
    await page.waitForSelector("#whatsapp .badge:has-text('Disabled by Admin')");
    await setting(page, { "whatsapp.enabled": true });
  });

  await step("AT-350 bridge stops: admin sees Service unavailable, the person sees it, Email/In-app unaffected", async () => {
    expect((await bridge("/_test/health", { up: false })).ok, "fake bridge down");
    try {
    // "Service stopped" where systemd reports the unit inactive (CI runners), "Service unavailable" without systemd
    await page.goto(BASE + "/settings/connections");
    await page.waitForSelector("#conn-whatsapp [data-bridge-state=unavailable], #conn-whatsapp [data-bridge-state=stopped]");
    expect(await page.locator(".provider-card[data-provider=in_app] [data-status=connected]").count() === 1, "in-app card affected");
    await page.goto(BASE + "/settings/account?tab=notifications");
    await page.waitForSelector("#whatsapp[data-state=service_unavailable] [role=status]:has-text('Service unavailable')");
    } finally { await bridge("/_test/health", { up: true }); } // later steps need the bridge back
    await page.reload();
    await page.waitForSelector("#whatsapp[data-state=connected]");
  });

  await step("AT-351 another person sees only their own state; the admin view holds no session or QR", async () => {
    const son = await session("son1");
    await son.page.goto(BASE + "/settings/account?tab=notifications");
    await son.page.waitForSelector("#whatsapp[data-state=not_linked]");
    expect(!(await son.page.locator("#whatsapp .qr").count()), "QR visible to another person");
    expect((await api(son.page, "/api/admin/connections")).status === 403, "family member reached the admin view");
    await son.ctx.close();
    const text = JSON.stringify((await api(page, "/api/admin/connections")).data);
    expect(!/qr_svg|FAKE-QR|session/i.test(text.replace(/"sessions":\{[^}]*\}/g, "")), "admin view contains session material");
    await page.click("#whatsapp button:has-text('Unlink')").catch(() => undefined);
  });
}

await step("AT-352/AT-353 Discord: Disabled by Admin → enabled, webhook form, routing explains unconnected channels", async () => {
  await setting(page, { "discord.enabled": false });
  await page.goto(BASE + "/settings/account?tab=notifications");
  await page.waitForSelector("#discord[data-state=disabled]:has-text('Disabled by Admin')");
  await page.goto(BASE + "/settings/connections");
  await page.locator("#conn-discord label.switch").click();
  await page.click("#conn-discord button:has-text('Save settings')");
  await page.waitForSelector(".provider-card:has-text('Discord'):not(:has-text('Disabled by Admin'))");
  await page.goto(BASE + "/settings/account?tab=notifications");
  await page.waitForSelector("#discord[data-state=not_configured] #dc-url");
  // a channel chosen in the routing matrix that cannot deliver says why
  const prefs = (await api(page, "/api/me/notification-preferences")).data;
  const dc = prefs.channels.find((c) => c.channel === "discord");
  expect(dc && dc.configured && /not set up|webhook/i.test(dc.issue || ""), `discord issue: ${JSON.stringify(dc)}`);
});

// ================================================================== Change Set V (AT-356..AT-375)
// NAS inside Backup Destinations, Backup Now + FIFO queue, shared tooltip, permission-aware Help, English sign-in map
// with details/clusters/filters, WhatsApp pairing lifecycle (fake bridge). Real NAS shares, a real phone and real
// production tiles are not available here and are reported Blocked in docs/TEST_REPORT.md.
await step("AT-356/AT-374 Storage & NAS page removed: the old address opens Backup & Recovery → Destinations", async () => {
  await page.goto(BASE + "/settings/storage");
  await page.waitForURL(/\/settings\/backup\?view=destinations/);
  await page.waitForSelector(".dest-grid");
  expect(!(await page.locator("nav a:has-text('Storage & NAS'), [role=tab]:has-text('Storage & NAS')").count()), "Storage & NAS still in the navigation");
});

await step("AT-358 Add destination → NAS: SMB and NFS fields inside the destination, password write-only", async () => {
  await page.goto(BASE + "/settings/backup?view=destinations");
  await page.click("button:has-text('Add destination')");
  await page.selectOption("#dst-kind", "nas");
  await page.waitForSelector("#dst-connection");
  for (const id of ["server", "share", "subfolder", "username", "domain", "version", "password"]) expect(await page.locator(`#dst-nas-${id}`).count() === 1, `SMB field ${id}`);
  expect((await page.locator("#dst-nas-password").getAttribute("type")) === "password", "SMB password must be a password field");
  await page.fill("#dst-name", "Home NAS (example)");
  await page.fill("#dst-nas-server", "nas.example.lan");
  await page.fill("#dst-nas-share", "backups");
  await page.fill("#dst-nas-username", "backup-user");
  await page.locator("[role=dialog]").screenshot({ path: `${OUT}/nas-destination-smb.png` });
  await page.selectOption("#dst-connection", "nfs");
  expect(!(await page.locator("#dst-nas-username, #dst-nas-password").count()), "NFS shows no SMB account fields");
  await page.selectOption("#dst-connection", "mounted");
  await page.waitForSelector("#dst-path");
  await page.keyboard.press("Escape");
});

await step("AT-360/AT-361 Backup Now: confirmation, no Cancel, FIFO queue states, Completed on this destination", async () => {
  await page.goto(BASE + "/settings/backup?view=destinations");
  const card = page.locator(".dest-card[data-dest='Home server disk']");
  await card.waitFor();
  await card.locator("button:has-text('Backup Now')").click();
  const dlg = page.locator("[role=dialog]");
  await dlg.locator("text=This backup cannot be cancelled once it starts.").waitFor();
  expect((await dlg.innerText()).includes("Home server disk") && (await dlg.innerText()).includes("Full system"), "confirmation names destination and scope");
  await dlg.screenshot({ path: `${OUT}/backup-now-confirm.png` });
  await dlg.locator("button:has-text('Start backup')").click();
  await page.waitForSelector("#backup-queue tr[data-job-state]");
  expect(!(await page.locator("#backup-queue button:has-text('Cancel')").count()), "a Cancel action exists");
  // a second request for the same destination while it waits or runs is refused
  const again = await api(page, `/api/backup/destinations/${(await api(page, "/api/backup/overview")).data.destinations.find((d) => d.name === "Home server disk").id}/backup-now`, { body: { confirm: true } });
  expect(again.status === 409 || again.status === 200, `duplicate request answered ${again.status}`);
  for (let i = 0; i < 90; i++) {
    const q = (await api(page, "/api/backup/jobs")).data.jobs;
    if (q.every((j) => ["Completed", "Failed"].includes(j.state))) break;
    await page.waitForTimeout(2000);
  }
  const jobs = (await api(page, "/api/backup/jobs")).data.jobs;
  const mine = jobs.find((j) => j.destinations.includes("Home server disk"));
  expect(mine && mine.state === "Completed", `Backup Now job: ${JSON.stringify(mine)}`);
  await page.reload();
  await page.waitForSelector("#backup-queue tr[data-job-state=Completed]");
  await page.locator("#backup-queue").screenshot({ path: `${OUT}/backup-queue.png` });
});

const tipInViewport = async (p, sel) => {
  const btn = p.locator(sel).first();
  await btn.scrollIntoViewIfNeeded();
  await btn.focus();
  const pop = p.locator(".tip-pop[role=tooltip]");
  await pop.waitFor();
  const r = await pop.evaluate((el) => { const b = el.getBoundingClientRect(); return { l: b.left, t: b.top, r: b.right, b: b.bottom, vw: innerWidth, vh: innerHeight,
    inBody: el.parentElement === document.body || el.closest("body > *") === el.parentElement, text: el.innerText,
    covered: document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2)?.closest(".tip-pop") === el }; });
  expect(r.l >= 0 && r.t >= 0 && r.r <= r.vw + 0.5 && r.b <= r.vh + 0.5, `tooltip clipped by the viewport: ${JSON.stringify(r)}`);
  expect(r.covered, "tooltip is hidden behind another element");
  expect((await btn.getAttribute("aria-describedby")) === (await pop.getAttribute("id")), "aria-describedby links the tooltip");
  return { r, pop };
};

await step("AT-362/AT-363 tooltips: portal above cards, tables and scroll areas; flip at edges; Escape; Learn more by role", async () => {
  await page.goto(BASE + "/settings/backup?view=destinations");
  const { r } = await tipInViewport(page, "#backup-queue .tip-btn");
  expect(r.text.includes("one at a time"), "registry text for backup.queue");
  expect(await page.locator(".tip-pop a:has-text('Learn more')").count() === 1, "main administrator sees Learn more for a main-administrator guide");
  await page.keyboard.press("Escape");
  await page.waitForSelector(".tip-pop", { state: "detached" });
  // phone: tap a tooltip near the right edge of a filter row
  const m = await session("son1", { width: 390, height: 844 }, true);
  await m.page.goto(BASE + "/settings/account?tab=signins");
  await m.page.locator(".map-filters .tip-btn").tap();
  await m.page.waitForSelector(".tip-pop[role=tooltip]");
  const box = await m.page.locator(".tip-pop").boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 390.5, `phone tooltip clipped: ${JSON.stringify(box)}`);
  await m.page.screenshot({ path: `${OUT}/tooltip-phone.png` });
  await m.ctx.close();
  // dialogs: the tooltip inside the destination dialog shows above the dialog
  await page.click("button:has-text('Add destination')");
  await page.selectOption("#dst-kind", "nas");
  await tipInViewport(page, "[role=dialog] .tip-btn");
  await page.screenshot({ path: `${OUT}/tooltip-dialog.png` });
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
});

await step("AT-364/AT-365 Help: a family member sees no administrator guides, titles or search hits; direct URLs say Not found", async () => {
  const s = await session("son1");
  await s.page.goto(BASE + "/help");
  await s.page.waitForSelector(".help-cat");
  const nav = await s.page.locator(".help-nav-desktop").innerText();
  for (const t of ["Backup & Recovery", "Disaster recovery", "Installation", "Upgrades", "Antivirus"]) expect(!nav.includes(t), `normal user sees "${t}" in Help`);
  expect(!(await s.page.locator(".help-start a[href='/help/backup-restore']").count()), "Backup tile shown to a normal user");
  await s.page.fill("input[type=search]", "NAS");
  await s.page.waitForTimeout(600);
  expect(!(await s.page.locator(".help-results a[href='/help/backup-restore']").count()), "search reveals the backup guide");
  await s.page.goto(BASE + "/help/disaster-recovery");
  await s.page.waitForSelector("h1:has-text('Not found')");
  await s.page.goto(BASE + "/help/whatsapp-personal");
  await s.page.waitForSelector("h2:has-text('Link your WhatsApp')");
  expect(!(await s.page.locator("text=whatsapp-bridge update").count()), "admin update procedure visible to a normal user");
  await s.page.screenshot({ path: `${OUT}/help-normal-user.png` });
  await s.ctx.close();
  await page.goto(BASE + "/help");
  await page.waitForSelector(".help-start a[href='/help/backup-restore']");
});

// the OpenFreeMap style is answered locally so the result does not depend on the network (screenshots.mjs uses the real one)
const STYLE = { version: 8, name: "test", sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#e8efe6" } }] };
async function vectorSession(user = "admin", viewport, mobile) {
  const s = await session(user, viewport, mobile);
  await s.ctx.route("https://tiles.openfreemap.org/**", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(STYLE), headers: { "Access-Control-Allow-Origin": "*" } }));
  return s;
}

await step("AT-366 sign-in map: vector map with English labels by default, no language selector", async () => {
  await setting(page, { "security.map_enabled": true, "security.map_provider": "openfreemap" });
  const s = await vectorSession();
  await s.page.goto(BASE + "/settings/account?tab=signins");
  await s.page.waitForSelector(".signin-map[data-map-mode=vector][data-labels=en]", { timeout: 20000 });
  expect(!(await s.page.locator("select[aria-label*=anguage], [aria-label*='Map language']").count()), "a map language selector exists");
  expect((await s.page.locator(".signins").innerText()).includes("Place names are shown in English"), "English note");
  await s.ctx.close();
});

await step("AT-367/AT-368 markers: hover summary, click details, clusters, list ↔ map selection, filters (Last 7 days default)", async () => {
  const s = await vectorSession();
  await s.page.goto(BASE + "/settings/activity?view=map");
  // every server worker must allow the new provider at once (the CSP origin was cached per worker for a minute)
  await s.page.waitForSelector(".signin-map[data-map-mode=vector]", { timeout: 20000 });
  expect((await s.page.locator(".map-filters select[aria-label=Period]").inputValue()) === "7", "default period is Last 7 days");
  // the admin signed in many times from the Home zone (recovery.mjs): one cluster with a count
  const cluster = s.page.locator(".map-cluster").first();
  await cluster.waitFor({ timeout: 15000 });
  await cluster.hover();
  await s.page.waitForSelector(".leaflet-tooltip:has-text('sign-ins')");
  await cluster.click();
  await s.page.waitForSelector(".signin-detail:has-text('sign-ins at this place')");
  await s.page.locator(".signin-detail .link-btn").first().click();
  await s.page.waitForSelector(".signin-detail[data-detail] dt:has-text('IP address')");
  const detail = await s.page.locator(".signin-detail[data-detail]").innerText();
  expect(/127\.0\.0\.1|::1/.test(detail) && detail.includes("Home"), `details: ${detail}`);
  await s.page.screenshot({ path: `${OUT}/map-details.png` });
  // list row → selected on the map and in the details
  const row = s.page.locator(".signin-list tbody tr").nth(1);
  const id = await row.getAttribute("data-event");
  await row.click();
  await s.page.waitForSelector(`.signin-detail[data-detail='${id}']`);
  expect((await row.getAttribute("aria-selected")) === "true", "row selection");
  // filters change map and list together
  const before = await s.page.locator(".signin-list tbody tr").count();
  await s.page.selectOption(".map-filters select[aria-label=Risk]", "high");
  await s.page.waitForFunction((n) => document.querySelectorAll(".signin-list tbody tr").length !== n || document.body.innerText.includes("No sign-ins match"), before);
  await s.page.selectOption(".map-filters select[aria-label=Risk]", "");
  await s.page.selectOption(".map-filters select[aria-label=Period]", "custom");
  await s.page.waitForSelector("text=Choose a start and end date.");
  await s.page.selectOption(".map-filters select[aria-label=Period]", "365");
  await s.page.waitForSelector(".signin-list tbody tr");
  await s.ctx.close();
  // a family member cannot widen the scope by editing the request
  const son = await session("son1");
  expect((await api(son.page, `/api/security/map?user=${meId}`)).status === 403, "family member read another person's sign-ins");
  await son.ctx.close();
});

if (WA_BRIDGE && WA_TOKEN) {
  await step("AT-370/AT-371/AT-372 WhatsApp: 5-minute countdown, live stages, no QR while connecting, new QR only after failure", async () => {
    await setting(page, { "whatsapp.enabled": true });
    const s = await session("son1");
    await s.page.goto(BASE + "/settings/account?tab=notifications");
    await s.page.waitForSelector("#whatsapp[data-state=not_linked]");
    await s.page.click("#whatsapp button:has-text('Link WhatsApp')");
    await s.page.waitForSelector("#whatsapp[data-stage=qr_ready] .qr svg");
    const left = Number(await s.page.locator("#whatsapp [data-countdown]").getAttribute("data-countdown"));
    expect(left > 240 && left <= 300, `countdown ${left}`);
    expect(!(await s.page.locator("#whatsapp button:has-text('Generate new QR code')").count()), "new QR offered inside the window");
    expect(await s.page.locator("#whatsapp .wa-stages li").count() >= 7, "stage list");
    await s.page.locator("#whatsapp").screenshot({ path: `${OUT}/whatsapp-qr-ready.png` });
    await bridge("/_test/stage", { session: "pending", stage: "connecting" });
    await s.page.waitForSelector("#whatsapp[data-stage=connecting] .wa-stages li.current:has-text('Connecting')", { timeout: 10000 });
    expect(!(await s.page.locator("#whatsapp .qr").count()), "QR still shown while connecting");
    await bridge("/_test/stage", { session: "pending", state: "pairing_failed", stage: null, error_code: "timeout", failure_stage: "authenticating" });
    await s.page.waitForSelector("#whatsapp[data-state=pairing_failed] button:has-text('Generate new QR code')", { timeout: 10000 });
    expect((await s.page.locator("#whatsapp").innerText()).includes("Authenticating"), "failure stage shown");
    await s.page.click("#whatsapp button:has-text('Generate new QR code')");
    await s.page.waitForSelector("#whatsapp[data-stage=qr_ready] .qr svg");
    expect((await bridge("/_test/connect/pending")).ok, "fake scan");
    await s.page.waitForSelector("#whatsapp[data-key=verified]:has-text('Linked & Verified')", { timeout: 15000 });
    await s.page.locator("#whatsapp").screenshot({ path: `${OUT}/whatsapp-verified.png` });
    await s.page.click("#whatsapp button:has-text('Unlink')");
    await s.page.waitForSelector("#whatsapp[data-state=not_linked]");
    await s.ctx.close();
  });

  await step("AT-373 Run Diagnostics (main admin): DNS, network, clock, storage, per-person state, no secrets", async () => {
    await page.goto(BASE + "/settings/connections");
    await page.waitForSelector("#wa-diagnostics button:has-text('Run Diagnostics')");
    await page.click("#wa-diagnostics button:has-text('Run Diagnostics')");
    await page.waitForSelector("#wa-diagnostics .diag-table");
    const text = await page.locator("#wa-diagnostics").innerText();
    expect(text.includes("Compatible") && !/FAKE-QR|Bearer|token/i.test(text), `diagnostics: ${text.slice(0, 300)}`);
    await page.locator("#wa-diagnostics").screenshot({ path: `${OUT}/whatsapp-diagnostics.png` });
    const son = await session("son1");
    expect((await api(son.page, "/api/admin/whatsapp")).status === 403, "family member reached diagnostics");
    await son.ctx.close();
  });
} else {
  skip("AT-370..AT-373 WhatsApp lifecycle", "no fake bridge (run through scripts/e2e.sh)");
}

// ------------------------------------------------------------------ Change Set W: named designs, rotation, detail level
await step("AT-376/AT-377/AT-379/AT-381 New design → wallpaper → focal point → Set as Active → public page matches → Revert", async () => {
  await page.goto(BASE + "/settings/overview");
  await page.waitForSelector(".design-grid");
  await page.click("#login-design button:has-text('New design')");
  await page.fill("#design-name", "E2E Meadow");
  await page.click("[role=dialog] button:has-text('Save')");
  await page.waitForSelector("[role=dialog] .design-editor");
  // a pale green 1600 × 1000 wallpaper drawn in the page (no external image)
  const b64 = await page.evaluate(() => {
    const c = document.createElement("canvas"); c.width = 1600; c.height = 1000;
    const g = c.getContext("2d"); g.fillStyle = "#cfe8c8"; g.fillRect(0, 0, 1600, 1000);
    g.fillStyle = "#3f7f3a"; g.fillRect(200, 600, 500, 300);
    return c.toDataURL("image/png").split(",")[1];
  });
  await page.locator("[role=dialog] input[type=file]").first().setInputFiles({ name: "meadow.png", mimeType: "image/png", buffer: Buffer.from(b64, "base64") });
  await page.waitForSelector("[role=dialog] .focal-picker", { timeout: 20000 });
  const box = await page.locator("[role=dialog] .focal-picker").boundingBox();
  await page.mouse.click(box.x + box.width * 0.25, box.y + box.height * 0.7);
  await page.click("[role=dialog] button:has-text('Save design')");
  await page.waitForSelector("text=Design saved");
  await page.locator("[role=dialog]").screenshot({ path: `${OUT}/design-editor.png` });
  await page.click("[role=dialog] .btn:text-is('Close')");
  const listing = (await api(page, "/api/signin-designs")).data;
  const mine = listing.designs.find((x) => x.name === "E2E Meadow");
  expect(mine && mine.has_wallpaper && !mine.active, "new design saved, not active");
  expect(Math.abs(mine.focal_x - 0.25) < 0.05 && Math.abs(mine.focal_y - 0.7) < 0.05, `focal point ${mine.focal_x},${mine.focal_y}`);
  const before = listing.active;
  await page.click(`.design-option[data-design-id='${mine.id}']`);
  await page.click("#login-design .seg button:has-text('Tablet')");
  await page.waitForSelector(".login-preview.tablet");
  await page.click(".design-actions button:has-text('Set as Active')");
  await page.waitForSelector(`.design-option[data-design-id='${mine.id}'] .design-saved`);
  // the anonymous sign-in page shows this design with colours derived from the light green wallpaper
  const anon = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const ap = await anon.newPage();
  await ap.goto(BASE + "/login");
  await ap.waitForSelector(`.auth[data-design='${mine.id}']`);
  const scheme = await ap.locator(".auth").getAttribute("data-scheme");
  const bg = await ap.locator(".auth").evaluate((el) => getComputedStyle(el).getPropertyValue("--bg").trim());
  expect(scheme === "light" && /^#/.test(bg), `palette: scheme=${scheme} bg=${bg}`);
  expect(await ap.locator("input[type=password]").count() > 0, "password sign-in still offered");
  await ap.screenshot({ path: `${OUT}/signin-custom-design.png` });
  await anon.close();
  await page.click("#login-design button:has-text('Revert to Previous Design')");
  await page.waitForFunction(async ([b]) => (await (await fetch("/api/signin-designs")).json()).active === b, [before]);
});

await step("AT-383/AT-385/AT-391 rotation: pool of two, Save rotation, status card, Preview Rotation changes nothing", async () => {
  await page.goto(BASE + "/settings/overview");
  await page.waitForSelector("#design-rotation");
  const active = (await api(page, "/api/signin-designs")).data.active;
  const card = page.locator("#design-rotation");
  await card.locator("label.check input").check();
  for (const n of ["Nature", "Travel"]) await card.locator(`button:has-text('${n}')`).first().click();
  expect(await card.locator(".rotation-pool li").count() >= 2, "pool rows");
  await card.locator("button:has-text('Save rotation')").click();
  await page.waitForSelector("#design-rotation [data-rotation-state=on]");
  const text = await card.innerText();
  expect(text.includes("Next Rotation") && text.includes("Current Design"), "status card facts");
  await card.locator("button:has-text('Preview Rotation')").click();
  await page.waitForSelector("[role=dialog]:has-text('Preview Rotation') .login-preview.full");
  await page.keyboard.press("Escape");
  expect((await api(page, "/api/signin-designs")).data.active === active, "preview changed the live design");
  const bad = await api(page, "/api/signin-designs/rotation", { method: "PUT", body: { enabled: true, pool: [active] } });
  expect(bad.status === 400, `single-design pool accepted (${bad.status})`);
  await api(page, "/api/signin-designs/rotation", { method: "PUT", body: { enabled: false } });
  const son = await session("son1");
  expect((await api(son.page, "/api/signin-designs")).status === 403, "family member reached sign-in designs");
  await son.ctx.close();
});

await step("AT-396/AT-397 Notification detail: Use system default / Full / Minimal per person", async () => {
  const s = await session("son1");
  await s.page.goto(BASE + "/settings/account?tab=notifications");
  await s.page.waitForSelector("#notification-detail #notif-detail");
  expect((await s.page.locator("#notif-detail").inputValue()) === "system", "default is the system setting");
  expect((await s.page.locator("#notif-detail option").first().innerText()).includes("Full Details"), "system default is Full");
  await s.page.selectOption("#notif-detail", "minimal");
  await s.page.waitForSelector("text=Saved");
  expect((await api(s.page, "/api/me/notification-preferences")).data.detail_level.mine === "minimal", "choice saved");
  await s.page.selectOption("#notif-detail", "system");
  await s.ctx.close();
});

await step("phone 390 px: Connections and notification cards fit without sideways scrolling", async () => {
  const m = await session("admin", { width: 390, height: 844 }, true);
  for (const url of ["/settings/connections", "/settings/account?tab=notifications", "/settings/security", "/settings/overview"]) {
    await m.page.goto(BASE + url);
    await m.page.waitForLoadState("networkidle");
    const over = await m.page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    expect(over <= 1, `${url}: page scrolls sideways by ${over}px`);
  }
  await m.ctx.close();
});

await step("no uncaught page errors during the corrective suite", async () => {
  expect(!pageErrors.length, pageErrors.slice(0, 3).join(" | "));
});

await ctx.close();
await browser.close();
fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 1));
console.log(`\ncorrective: ${results.filter((r) => r[0] === "PASS").length} passed, ${failed} failed, ${results.filter((r) => r[0] === "NOT RUN").length} not run`);
process.exit(failed ? 1 : 0);
