// Page-level performance measurements (Change Set X): time until each screen is usable, the number of requests and
// the bytes transferred. Runs against a server holding the synthetic dataset (manage.py perf_dataset).
//
//   BASE=http://localhost:8001 PERF_BIG_FOLDER=<uuid> PERF_FOLDER=<uuid> PERF_OUT=perf-pages.json node tests/e2e/perf.mjs
//
// Conditions (documented in docs/PERFORMANCE.md): Chromium, a fresh browser profile per flow (cold cache) unless the
// flow says "warm"; the network is emulated as a home Wi-Fi / LAN link to the server (20 ms latency, 40 Mbit/s down,
// 20 Mbit/s up) and the CPU is slowed down 2x to stand in for an ordinary laptop or phone. "Usable" means the
// screen's own content is shown and nothing on it is still loading (no element with aria-busy="true").
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const BASE = process.env.BASE || "http://localhost:8001";
const BIG = process.env.PERF_BIG_FOLDER;
const FOLDER = process.env.PERF_FOLDER;
const RUNS = Number(process.env.PERF_RUNS || 3);
const PW = "Sample-Passw0rd!";
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });

async function newPage() {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 20, downloadThroughput: 5_000_000, uploadThroughput: 2_500_000 });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 2 });
  const stats = { requests: 0, api: 0, bytes: 0, js: 0 };
  cdp.on("Network.requestWillBeSent", (e) => { stats.requests++; if (e.request.url.includes("/api/")) stats.api++; });
  cdp.on("Network.loadingFinished", (e) => { stats.bytes += e.encodedDataLength; });
  cdp.on("Network.responseReceived", (e) => { if (e.type === "Script") stats.jsUrls = [...(stats.jsUrls || []), e.requestId]; });
  const jsSizes = new Map();
  cdp.on("Network.responseReceived", (e) => { if (e.type === "Script") jsSizes.set(e.requestId, 0); });
  cdp.on("Network.loadingFinished", (e) => { if (jsSizes.has(e.requestId)) { jsSizes.set(e.requestId, e.encodedDataLength); stats.js = [...jsSizes.values()].reduce((a, b) => a + b, 0); } });
  const reset = () => { stats.requests = 0; stats.api = 0; stats.bytes = 0; stats.js = 0; jsSizes.clear(); };
  return { ctx, page, stats, reset };
}

// usable: the selector is present and nothing in the main area (or the sign-in panel) is still loading
const usable = (page, sel, timeout = 30000) => page.waitForFunction((sel) => {
  const el = document.querySelector(sel);
  return !!el && !document.querySelector("main [aria-busy='true'], .auth [aria-busy='true']");
}, sel, { timeout, polling: 25 });

async function timed(fn) { const t = performance.now(); await fn(); return Math.round(performance.now() - t); }

async function signIn(s, user = "dad") {
  await s.page.goto(BASE + "/login");
  await s.page.waitForSelector("#username");
  await s.page.fill("#username", user);
  await s.page.fill("#password", PW);
  await s.page.click("button:has-text('Sign in')");
  await s.page.waitForURL((u) => !u.pathname.startsWith("/login"));
}

const flows = {
  "Sign-in page usable": async () => {
    const s = await newPage();
    const ms = await timed(async () => { await s.page.goto(BASE + "/login"); await usable(s.page, ".auth[data-design] #username"); });
    return { ms, ...s.stats, close: s.ctx };
  },
  "Sign-in → dashboard usable": async () => {
    const s = await newPage();
    await s.page.goto(BASE + "/login");
    await usable(s.page, ".auth #username");
    await s.page.fill("#username", "dad");
    await s.page.fill("#password", PW);
    s.reset();
    const ms = await timed(async () => { await s.page.click("button:has-text('Sign in')"); await usable(s.page, "main [data-widget]"); });
    return { ms, ...s.stats, close: s.ctx };
  },
  "Settings initial (General)": async () => {
    const s = await newPage();
    await signIn(s);
    await usable(s.page, "main [data-widget]");
    s.reset();
    const ms = await timed(async () => { await s.page.click("a[href='/settings']"); await usable(s.page, "main .setting-row"); });
    return { ms, ...s.stats, close: s.ctx };
  },
  "Settings section first visit (Backup & Recovery)": async () => {
    const s = await newPage();
    await signIn(s);
    await s.page.goto(BASE + "/settings/general");
    await usable(s.page, "main .setting-row");
    s.reset();
    const ms = await timed(async () => { await s.page.click("nav.tabs a:has-text('Backup & Recovery')"); await usable(s.page, "main nav.tabs a.active[href='/settings/backup']"); await s.page.waitForTimeout(0); await usable(s.page, "main .card"); });
    return { ms, ...s.stats, close: s.ctx };
  },
  "Settings section switch, previously loaded": async () => {
    const s = await newPage();
    await signIn(s);
    await s.page.goto(BASE + "/settings/general");
    await usable(s.page, "main .setting-row");
    await s.page.click("nav.tabs a:has-text('Notifications')");
    await usable(s.page, "main nav.tabs a.active[href='/settings/notifications']");
    await usable(s.page, "main .card");
    await s.page.click("nav.tabs a:has-text('General')");
    await usable(s.page, "main .setting-row");
    s.reset();
    const ms = await timed(async () => { await s.page.click("nav.tabs a:has-text('Notifications')"); await usable(s.page, "main nav.tabs a.active[href='/settings/notifications']"); await usable(s.page, "main .card"); });
    return { ms, ...s.stats, close: s.ctx };
  },
  "Folder browse (large folder, first documents)": async () => {
    const s = await newPage();
    await signIn(s);
    await usable(s.page, "main [data-widget]");
    s.reset();
    const ms = await timed(async () => { await s.page.goto(BASE + `/folders/${BIG}`); await usable(s.page, "main .doc-card, main .details-table tbody tr"); });
    return { ms, ...s.stats, close: s.ctx };
  },
  "Folder browse (normal folder)": async () => {
    const s = await newPage();
    await signIn(s);
    await usable(s.page, "main [data-widget]");
    s.reset();
    const ms = await timed(async () => { await s.page.goto(BASE + `/folders/${FOLDER}`); await usable(s.page, "main .doc-card, main .details-table tbody tr"); });
    return { ms, ...s.stats, close: s.ctx };
  },
  "Document Details open": async () => {
    const s = await newPage();
    await signIn(s);
    await s.page.goto(BASE + `/folders/${FOLDER}`);
    await usable(s.page, "main .doc-card, main .details-table tbody tr");
    s.reset();
    const ms = await timed(async () => {
      await s.page.locator("main .doc-card .doc-open, main .details-table .doc-open").first().click();
      await usable(s.page, "[role=tab][aria-selected=true]");
    });
    return { ms, ...s.stats, close: s.ctx };
  },
  "Search (family dataset)": async () => {
    const s = await newPage();
    await signIn(s);
    await usable(s.page, "main [data-widget]");
    s.reset();
    const ms = await timed(async () => { await s.page.goto(BASE + "/search?q=renewal"); await usable(s.page, "main a.list-item"); });
    return { ms, ...s.stats, close: s.ctx };
  },
};

const out = { base: BASE, conditions: "Chromium; 20 ms latency, 40/20 Mbit/s; CPU 2x slowdown; cold browser cache", flows: {} };
for (const [name, fn] of Object.entries(flows)) {
  const runs = [];
  for (let i = 0; i < RUNS; i++) {
    try { const r = await fn(); await r.close.close(); delete r.close; delete r.jsUrls; runs.push(r); }
    catch (e) { runs.push({ error: String(e.message || e).slice(0, 200) }); }
  }
  const ok = runs.filter((r) => !r.error).sort((a, b) => a.ms - b.ms);
  const med = ok[Math.floor((ok.length - 1) / 2)];
  out.flows[name] = med ? { median_ms: med.ms, runs: ok.map((r) => r.ms), requests: med.requests, api_requests: med.api, kb: Math.round(med.bytes / 1024), js_kb: Math.round(med.js / 1024) } : { error: runs[0]?.error };
  console.log(name.padEnd(52), med ? `${String(med.ms).padStart(6)} ms  ${med.requests} req (${med.api} api)  ${Math.round(med.bytes / 1024)} KB  js ${Math.round(med.js / 1024)} KB` : `ERROR ${runs[0]?.error}`);
}
if (process.env.PERF_OUT) writeFileSync(process.env.PERF_OUT, JSON.stringify(out, null, 1));
await browser.close();
