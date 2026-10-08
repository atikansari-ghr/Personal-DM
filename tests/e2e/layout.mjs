// Application-wide layout audit and geometry regression (Change Set R, AT-231..AT-245; step names use those numbers).
// Runs after flow.mjs / parity.mjs against the same throw-away instance (synthetic data only).
//
// For every audited screen at seven viewport classes it checks, in the real browser:
//   overflow   the page scrolls sideways (horizontal UI breakage)
//   squeezed   multi-word text forced into a column so narrow that it wraps word by word
//   btnwrap    a button label wraps onto several lines
//   iconalign  the icon and the label of a button are not vertically centred on each other
//   overlap    two controls (buttons, links, fields) overlap each other
//   offscreen  a control sticks out of the viewport without a scrolling container
//   noname     an icon-only control has no accessible name
// plus, on the document screen: the reproduced header defect (title squeezed beside the actions), menus and dialogs
// inside the viewport, keyboard focus visible, and Arabic / very long filenames.
//
// Geometry of the document header is compared with tests/e2e/layout-baseline.json (x/width ±6 px, y/height ±24 px); run with
// UPDATE_BASELINE=1 to write a new baseline and review its diff in the pull request. Screenshots for human review
// are written to tests/e2e/out/layout/ (uploaded as a CI artifact, not committed).
//
// Usage: BASE=http://localhost:8000 node tests/e2e/layout.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.BASE || "http://localhost:8000";
const PW = "Sample-Passw0rd!";
const OUT = process.env.LAYOUT_OUT || "tests/e2e/out/layout";
const BASELINE = "tests/e2e/layout-baseline.json";
const REPORT = process.env.LAYOUT_REPORT || "docs/layout-report.json";
fs.mkdirSync(OUT, { recursive: true });

const VIEWPORTS = [
  ["desktop-1920", 1920, 1080], ["desktop-1440", 1440, 900], ["desktop-1366", 1366, 768],
  ["tablet-landscape", 1180, 820], ["tablet-portrait", 820, 1180], ["mobile-430", 430, 932], ["mobile-390", 390, 844],
];
// synthetic filenames: short, normal, long, very long without spaces, Arabic + digits
const NAMES = ["Iqama.jpg", "Iqama Renewal Fees 2018-19.JPG",
  "Family residence permit renewal receipt and payment confirmation 2018-19 final copy.JPG",
  "Very-long-file-name_without_spaces_2018-2019_residence-permit-renewal-fees-receipt-scan-0001-final-final.JPG",
  "تجديد الإقامة رسوم ٢٠١٨-١٩ إيصال الدفع.jpg"];

const results = [];
const defects = [];
let failed = 0;
const step = async (name, fn) => {
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { failed++; results.push(["FAIL", name, String(e).slice(0, 600)]); console.log("FAIL", name, String(e).slice(0, 600)); }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
const api = (page, url, opts = {}) => page.evaluate(async ([url, opts]) => {
  const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
  const r = await fetch(url, { method: opts.method || (opts.body ? "POST" : "GET"), headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: opts.body ? JSON.stringify(opts.body) : undefined });
  return { status: r.status, data: r.headers.get("content-type")?.includes("json") ? await r.json() : null };
}, [url, opts]);

async function signIn(ctx) {
  const page = await ctx.newPage();
  await page.goto(BASE + "/login");
  await page.fill("#username", "admin");
  await page.fill("#password", PW);
  await page.click("button:has-text('Sign in')");
  await page.waitForSelector("text=Good");
  return page;
}

// ------------------------------------------------------------------ fixtures: synthetic documents with hard names
const setup = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const sp = await signIn(setup);
const me = (await api(sp, "/api/session")).data.user;
const root = (await api(sp, "/api/folders")).data.folders.find((f) => f.kind === "personal_root" && f.owner === me.id);
const docs = await sp.evaluate(async ([names, folder]) => {
  const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
  const out = [];
  for (const n of names) {
    const c = document.createElement("canvas"); c.width = 900; c.height = 600; const g = c.getContext("2d");
    g.fillStyle = "white"; g.fillRect(0, 0, 900, 600); g.fillStyle = "black"; g.font = "40px sans-serif"; g.fillText("SAMPLE ONLY", 40, 120);
    const blob = await new Promise((r) => c.toBlob(r, "image/jpeg"));
    const f = new FormData(); f.append("folder", folder); f.append("files", blob, n);
    const r = await fetch("/api/documents", { method: "POST", body: f, headers: { "X-CSRFToken": csrf } });
    out.push((await r.json()).documents[0].id);
  }
  return out;
}, [NAMES, root.id]);
const DOC = docs[1]; // the screenshot case: "Iqama Renewal Fees 2018-19.JPG"
await setup.close();

const ROUTES = [
  ["overview", "/"], ["folders", `/folders/${root.id}`], ["document-preview", `/folders/${root.id}/${DOC}`],
  ["document-full", `/documents/${DOC}`], ["document-arabic", `/folders/${root.id}/${docs[4]}`],
  ["document-very-long", `/folders/${root.id}/${docs[3]}`], ["search", "/search?q=sample"], ["shared", "/shared"],
  ["offline", "/offline"], ["archive", "/archive"], ["ocr-review", "/ocr-review"], ["notifications", "/notifications"],
  ["settings", "/settings"], ["settings-family", "/settings/family"], ["settings-account-security", "/settings/account?tab=security"],
  ["settings-documents", "/settings/documents"], ["settings-ocr", "/settings/processing"], ["settings-notifications", "/settings/notifications"],
  ["security-overview", "/settings/security"], ["security-antivirus", "/settings/security?view=antivirus"],
  ["security-test", "/settings/security?view=test"], ["security-updates", "/settings/security?view=updates"],
  ["security-firewall", "/settings/security?view=firewall"], ["security-records", "/settings/security?view=records"],
  ["security-storage", "/settings/security?view=storage"], ["security-access", "/settings/security?view=access"],
  ["help", "/help/getting-started"],
];

// in-page checks; returns a list of {kind, el, detail}
const audit = () => {
  const out = [];
  const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none" && !el.closest("[aria-hidden=true], .sr-only"); };
  const label = (el) => (el.getAttribute("aria-label") || el.textContent || el.getAttribute("title") || el.tagName).trim().replace(/\s+/g, " ").slice(0, 60);
  const over = document.documentElement.scrollWidth - innerWidth;
  if (over > 1) out.push({ kind: "overflow", el: "page", detail: `${over}px` });
  // squeezed text: three or more words in a box so narrow that it needs a line per word or two
  for (const el of document.querySelectorAll("h1, h2, h3, h4, p, li, td, th, label, dt, dd, .small, .muted, .badge, .btn, legend, figcaption")) {
    if (!vis(el) || el.closest(".viewer-scroll, pre, code, .ftype, svg, table.responsive")) continue;
    const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(" ").trim();
    const words = own.split(/\s+/).filter((w) => w.length > 1);
    if (words.length < 3) continue;
    const r = el.getBoundingClientRect(); const lh = parseFloat(getComputedStyle(el).lineHeight) || 20;
    const lines = Math.round(r.height / lh);
    if (lines >= Math.max(3, Math.ceil(words.length * 0.6)) && r.width < 140) out.push({ kind: "squeezed", el: label(el), detail: `${Math.round(r.width)}px wide, ${lines} lines for ${words.length} words` });
  }
  for (const el of document.querySelectorAll(".btn")) {
    if (!vis(el) || el.closest(".viewer-scroll")) continue;
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    const lh = parseFloat(cs.lineHeight) || 20;
    const txt = [...el.childNodes].filter((n) => n.nodeType === 3 || (n.nodeType === 1 && n.tagName === "SPAN" && !n.querySelector("svg"))).map((n) => n.textContent).join("").trim();
    if (txt && r.height > Math.max(parseFloat(cs.minHeight) || 0, lh) + lh * 0.9) out.push({ kind: "btnwrap", el: label(el), detail: `${Math.round(r.height)}px tall` });
    const svg = el.querySelector(":scope > svg"); const textNode = [...el.childNodes].find((n) => (n.nodeType === 3 && n.textContent.trim()) || (n.nodeType === 1 && n.tagName === "SPAN" && n.textContent.trim() && getComputedStyle(n).display !== "none"));
    if (svg && textNode && r.height < 60) {
      const range = document.createRange(); range.selectNodeContents(textNode);
      const tr = range.getBoundingClientRect(); const ir = svg.getBoundingClientRect();
      const d = Math.abs((tr.top + tr.bottom) / 2 - (ir.top + ir.bottom) / 2);
      if (tr.height && d > 3) out.push({ kind: "iconalign", el: label(el), detail: `${d.toFixed(1)}px off` });
    }
  }
  const ctrls = [...document.querySelectorAll("a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=tab]")].filter(vis);
  for (const el of ctrls) {
    const r = el.getBoundingClientRect();
    let sc = el.parentElement, scrolls = false;
    while (sc && sc !== document.body) { const o = getComputedStyle(sc).overflowX; if ((o === "auto" || o === "scroll") && sc.scrollWidth > sc.clientWidth) { scrolls = true; break; } sc = sc.parentElement; }
    if (!scrolls && (r.right > innerWidth + 1 || r.left < -1)) out.push({ kind: "offscreen", el: label(el), detail: `${Math.round(r.left)}..${Math.round(r.right)}` });
    if (["BUTTON", "A"].includes(el.tagName) && !el.textContent.trim() && !el.getAttribute("aria-label") && !el.getAttribute("title") && !el.getAttribute("aria-labelledby") && !el.querySelector("img[alt]"))
      out.push({ kind: "noname", el: el.outerHTML.slice(0, 80), detail: "icon-only control without a name" });
  }
  for (let i = 0; i < ctrls.length; i++) for (let j = i + 1; j < ctrls.length; j++) {
    const a = ctrls[i], b = ctrls[j];
    if (a.contains(b) || b.contains(a) || a.closest("label") === b.closest("label") && a.closest("label")) continue;
    // inline links that wrap over several lines are compared line fragment by line fragment
    let w = 0, h = 0;
    for (const A of a.getClientRects()) for (const B of b.getClientRects()) {
      const ow = Math.min(A.right, B.right) - Math.max(A.left, B.left), oh = Math.min(A.bottom, B.bottom) - Math.max(A.top, B.top);
      if (ow > 3 && oh > 3) { w = ow; h = oh; }
    }
    if (w > 3 && h > 3) {
      // controls stacked in different scroll layers (sticky toolbars, fixed bars) are not an overlap of the layout
      const fixed = (e) => { for (let n = e; n; n = n.parentElement) { const p = getComputedStyle(n).position; if (p === "fixed" || p === "sticky") return n; } return null; };
      if (fixed(a) !== fixed(b)) continue;
      out.push({ kind: "overlap", el: `${label(a)} × ${label(b)}`, detail: `${Math.round(w)}×${Math.round(h)}px` });
    }
  }
  return out;
};

// document header geometry (relative to the pane), used by the baseline and the AT-232 assertions
const headerGeometry = () => {
  const h = document.querySelector(".doc-header"); if (!h) return null;
  const box = (sel) => { const e = h.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(), p = h.getBoundingClientRect(); return [Math.round(r.left - p.left), Math.round(r.top - p.top), Math.round(r.width), Math.round(r.height)]; };
  const hr = h.getBoundingClientRect();
  return { header: [0, 0, Math.round(hr.width), Math.round(hr.height)], title: box(".doc-title"), badges: box(".doc-badges"), meta: box(".doc-meta"), actions: box(".doc-actions") };
};

const baseline = fs.existsSync(BASELINE) ? JSON.parse(fs.readFileSync(BASELINE, "utf8")) : {};
const geometry = {};
const ALLOW = new Set((process.env.LAYOUT_ALLOW || "").split(",").filter(Boolean));

for (const [vname, w, h] of VIEWPORTS) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, isMobile: w < 500, hasTouch: w < 1200, deviceScaleFactor: 1 });
  const page = await signIn(ctx);
  await step(`AT-237 ${vname}: every audited screen without overflow, squeezed text, wrapped buttons, misaligned icons, overlaps or unnamed controls`, async () => {
    const found = [];
    for (const [rname, url] of ROUTES) {
      await page.goto(BASE + url);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(350);
      const nf = await page.evaluate(() => !!document.querySelector("h1")?.textContent?.includes("Page not found"));
      expect(!nf, `${rname}: page not found`);
      for (const d of await page.evaluate(audit)) if (!ALLOW.has(`${rname}:${d.kind}`)) found.push({ vp: vname, route: rname, ...d });
      if (["document-preview", "folders", "overview", "settings-ocr", "security-overview", "notifications"].includes(rname))
        await page.screenshot({ path: path.join(OUT, `${vname}-${rname}.png`) });
    }
    defects.push(...found);
    expect(found.length === 0, `${found.length} layout defect(s): ${JSON.stringify(found.slice(0, 8))}`);
  });

  await step(`AT-232/233 ${vname}: document header uses the pane width; title, badges, file details and actions aligned`, async () => {
    for (const [i, id] of docs.entries()) {
      await page.goto(`${BASE}/folders/${root.id}/${id}`);
      await page.waitForSelector(".doc-header .doc-title");
      await page.waitForTimeout(250);
      const g = await page.evaluate(headerGeometry);
      const pane = g.header[2];
      // the reproduced defect: a 746 px pane gave the title 192 px beside the buttons
      expect(g.title[2] >= pane - 4, `${NAMES[i]}: title ${g.title[2]}px of ${pane}px header`);
      expect(g.actions[1] >= g.title[1] + g.title[3] - 2 || g.actions[0] >= g.title[0] + g.title[2], `${NAMES[i]}: actions overlap the title`);
      const lines = await page.evaluate(() => { const t = document.querySelector(".doc-title"); return Math.round(t.getBoundingClientRect().height / parseFloat(getComputedStyle(t).lineHeight)); });
      const words = NAMES[i].split(/[\s]+/).length;
      expect(lines <= Math.max(1, Math.ceil(words / 2)) || NAMES[i].length > 60, `${NAMES[i]}: ${lines} lines (word-by-word wrapping)`);
      if (i === 1) geometry[vname] = g;
    }
  });

  await step(`AT-242 ${vname}: menus and dialogs stay inside the viewport and are keyboard reachable`, async () => {
    await page.goto(`${BASE}/folders/${root.id}/${DOC}`);
    await page.waitForSelector(".doc-actions button[aria-label='More actions']");
    await page.click(".doc-actions button[aria-label='More actions']");
    await page.waitForSelector(".menu-pop");
    const m = await page.evaluate(() => { const r = document.querySelector(".menu-pop").getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom, innerWidth, innerHeight, document.activeElement?.getAttribute("role")]; });
    expect(m[0] >= 0 && m[1] >= 0 && m[2] <= m[4] && m[3] <= m[5], `menu outside viewport ${m}`);
    expect(m[6] === "menuitem", "keyboard focus moves into the menu");
    await page.keyboard.press("Escape");
    await page.click(".doc-actions button[aria-label='Share']");
    await page.waitForSelector(".modal");
    const d = await page.evaluate(() => { const r = document.querySelector(".modal").getBoundingClientRect(); return [r.left, r.right, innerWidth, document.querySelector(".modal").contains(document.activeElement)]; });
    expect(d[0] >= 0 && d[1] <= d[2], `dialog outside viewport ${d}`);
    expect(d[3], "focus inside the dialog");
    await page.keyboard.press("Escape");
  });

  if (w >= 1366) await step(`AT-243 ${vname}: keyboard focus is visible on header actions`, async () => {
    await page.goto(`${BASE}/folders/${root.id}/${DOC}`);
    await page.waitForSelector(".doc-actions a.btn");
    await page.focus(".doc-actions a.btn");
    await page.keyboard.press("Tab");
    const f = await page.evaluate(() => { const e = document.activeElement; const cs = getComputedStyle(e); return { name: e.getAttribute("aria-label") || e.textContent.trim(), ring: cs.outlineStyle !== "none" || cs.boxShadow !== "none" }; });
    expect(f.name && f.ring, `focus ring on ${JSON.stringify(f)}`);
  });
  await ctx.close();
}

await step("AT-238/239/240 geometry regression against the reviewed baseline (document header, all viewports)", async () => {
  if (process.env.UPDATE_BASELINE === "1" || !Object.keys(baseline).length) {
    fs.writeFileSync(BASELINE, JSON.stringify(geometry, null, 1) + "\n");
    console.log(`baseline written: ${BASELINE} (review the diff)`);
    return;
  }
  const diffs = [];
  for (const [vp, g] of Object.entries(geometry)) for (const [k, box] of Object.entries(g)) {
    const b = baseline[vp]?.[k];
    if (!b || !box) { if (b !== box) diffs.push(`${vp}.${k}: ${JSON.stringify(b)} -> ${JSON.stringify(box)}`); continue; }
    // x and width are layout (strict); y and height also depend on the fonts of the machine (looser)
    if (box.some((v, i) => Math.abs(v - b[i]) > (i % 2 === 0 ? 6 : 24))) diffs.push(`${vp}.${k}: ${JSON.stringify(b)} -> ${JSON.stringify(box)}`);
  }
  expect(diffs.length === 0, `layout changed (review, then UPDATE_BASELINE=1): ${diffs.join("; ")}`);
});

await browser.close();
fs.writeFileSync(REPORT, JSON.stringify({ results, defects }, null, 1) + "\n");
console.log(`${results.length - failed} PASS, ${failed} FAIL`);
process.exit(failed ? 1 : 0);
