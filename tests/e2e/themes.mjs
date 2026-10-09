// Premium themes (Change Set S, AT-264..AT-269): default, presets on the major screens, glass readability measured on
// the rendered pixels, fallback and effect budget, focus/contrast/reduced motion, and per-account persistence.
// The axe-core WCAG audit in every theme is tests/e2e/a11y.mjs. Synthetic data only.
// Usage: BASE=http://localhost:8000 node tests/e2e/themes.mjs
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const PW = "Sample-Passw0rd!";
const SON_PW = "Son1-Own-Passw0rd";
const OUT = "tests/e2e/out/themes";
fs.mkdirSync(OUT, { recursive: true });
const THEMES = ["green", "blue", "dark", "glass_light", "glass_dark", "mono"];
const SCREENS = [["overview", "/"], ["folders", "/folders"], ["offline", "/offline"], ["notifications", "/notifications"],
  ["appearance", "/settings/account?tab=appearance"], ["security", "/settings/security"], ["search", "/search?q=sample"]];
const results = [];
const report = { contrast: [], effects: {}, frames: {} };
let failed = 0;
const step = async (name, fn) => {
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { failed++; results.push(["FAIL", name, String(e).slice(0, 900)]); console.log("FAIL", name, String(e).slice(0, 900)); }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
const api = (page, url, opts = {}) => page.evaluate(async ([url, opts]) => {
  const csrf = decodeURIComponent((document.cookie.match(/pd_csrftoken=([^;]+)/) || [])[1] || "");
  const r = await fetch(url, { method: opts.method || (opts.body ? "POST" : "GET"), headers: { "Content-Type": "application/json", "X-CSRFToken": csrf }, body: opts.body ? JSON.stringify(opts.body) : undefined });
  return { status: r.status, data: r.headers.get("content-type")?.includes("json") ? await r.json() : null };
}, [url, opts]);
async function signIn(user, pw, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ...opts });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.log("pageerror", String(e).slice(0, 200)));
  await page.goto(BASE + "/login");
  await page.fill("#username", user);
  await page.fill("#password", pw);
  await page.click("button:has-text('Sign in')");
  await page.waitForSelector("text=Good");
  return { ctx, page };
}
const setTheme = (page, t) => api(page, "/api/settings", { method: "PUT", body: { values: { "me.theme": t } } });
const settle = async (page) => { await page.waitForLoadState("networkidle"); await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(300); };

// WCAG relative luminance / contrast of the text colour against the rendered background behind it
const lum = ([r, g, b]) => { const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
async function measuredContrast(page, selector, label, min) {
  const els = await page.$$(selector);
  let worst = null;
  for (const el of els.slice(0, 4)) {
    if (!(await el.isVisible())) continue;
    const color = await el.evaluate((e) => getComputedStyle(e).color);
    const fg = color.match(/[\d.]+/g).slice(0, 3).map(Number);
    // background: the most common colour of the element's rendered box (text pixels are a minority)
    await el.evaluate((e) => { e.dataset.pdProbe = "1"; e.style.setProperty("color", "transparent", "important"); });
    const png = await el.screenshot();
    await el.evaluate((e) => { e.style.removeProperty("color"); delete e.dataset.pdProbe; });
    const bg = await page.evaluate(async (b64) => {
      // decode with an <img> (the app's CSP allows data: images, not fetching data: URLs)
      const bmp = await new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = "data:image/png;base64," + b64; });
      const c = new OffscreenCanvas(bmp.naturalWidth, bmp.naturalHeight); const g = c.getContext("2d"); g.drawImage(bmp, 0, 0);
      bmp.width = bmp.naturalWidth; bmp.height = bmp.naturalHeight;
      const d = g.getImageData(0, 0, bmp.width, bmp.height).data; const counts = new Map();
      for (let i = 0; i < d.length; i += 16) { const k = `${d[i] >> 2},${d[i + 1] >> 2},${d[i + 2] >> 2}`; counts.set(k, (counts.get(k) || 0) + 1); }
      const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0].split(",").map((v) => Number(v) * 4 + 2);
      return top;
    }, png.toString("base64"));
    const r = ratio(fg, bg);
    if (!worst || r < worst.r) worst = { r, fg, bg };
  }
  if (!worst) return null;
  report.contrast.push({ label, selector, ratio: Number(worst.r.toFixed(2)), min, fg: worst.fg, bg: worst.bg });
  return worst.r;
}

const A = await signIn("admin", PW);

await step("AT-264 default Green/White theme for an account that never chose one", async () => {
  const S = await signIn("son1", SON_PW);
  await S.page.goto(BASE + "/");
  await settle(S.page);
  const t = await S.page.evaluate(() => ({ theme: document.documentElement.dataset.theme, brand: getComputedStyle(document.documentElement).getPropertyValue("--brand").trim(),
    bg: getComputedStyle(document.documentElement).backgroundColor, meta: document.querySelector('meta[name="theme-color"]').content }));
  expect(t.theme === "green" && t.brand === "#1f5135" && t.bg === "rgb(255, 255, 255)" && t.meta === "#1f5135", JSON.stringify(t));
  await S.ctx.close();
});

await step("AT-265 Blue, Dark, Glass Light and Glass Dark render the major screens consistently", async () => {
  const problems = [];
  for (const theme of THEMES) {
    await setTheme(A.page, theme);
    for (const [name, path] of SCREENS) {
      await A.page.goto(BASE + path);
      await settle(A.page);
      const info = await A.page.evaluate(() => {
        const cs = getComputedStyle(document.documentElement);
        const hard = [...document.querySelectorAll(".card, .modal, .menu-pop, .btn, input, select, .doc-card, .sidebar, .topbar")].filter((e) => {
          const b = getComputedStyle(e).backgroundColor; return b === "rgb(255, 255, 255)";
        }).length;
        return { applied: document.documentElement.dataset.theme, overflow: document.documentElement.scrollWidth > innerWidth + 1, surface: cs.getPropertyValue("--surface").trim(), whiteSurfaces: hard,
          bodyBg: getComputedStyle(document.body).backgroundColor };
      });
      if (info.applied !== theme) problems.push(`${theme}/${name}: theme not applied (${info.applied})`);
      if (info.overflow) problems.push(`${theme}/${name}: horizontal overflow`);
      // dark themes: no component may stay hard-coded white (that was the old pattern: "background: #fff")
      if (theme.includes("dark") && info.whiteSurfaces) problems.push(`${theme}/${name}: ${info.whiteSurfaces} component(s) still white`);
      await A.page.screenshot({ path: `${OUT}/${theme}-${name}.png` });
    }
    // the document panel with the viewer (document pages stay white on purpose)
    await A.page.goto(BASE + "/folders");
    const card = A.page.locator(".doc-card").first();
    if (await card.count()) { await card.click(); await A.page.waitForSelector(".detail-pane .doc-header"); await settle(A.page); await A.page.screenshot({ path: `${OUT}/${theme}-document.png` }); }
  }
  expect(!problems.length, problems.join("\n"));
});

await step("AT-266 glass readability: text, badges, warnings and document content measured on rendered pixels", async () => {
  const low = [];
  for (const theme of ["glass_light", "glass_dark", "dark", "green", "blue"]) {
    await setTheme(A.page, theme);
    for (const [path, checks] of [
      ["/", [[".card h2", 4.5], [".card .muted", 4.5], [".badge", 4.5], [".sidebar .nav a", 4.5]]],
      ["/folders", [[".doc-card .doc-open", 4.5], [".doc-card .doc-meta", 4.5], [".tree-node span", 4.5]]],
      ["/offline", [["h1", 4.5], [".page-head .muted", 4.5], [".alert", 4.5], [".stat .muted", 4.5]]],
      ["/settings/security", [[".card h2", 4.5], [".badge", 4.5], [".alert", 4.5]]],
    ]) {
      await A.page.goto(BASE + path);
      await settle(A.page);
      for (const [sel, min] of checks) {
        const r = await measuredContrast(A.page, sel, `${theme}${path}`, min);
        if (r !== null && r < min) low.push(`${theme} ${path} ${sel}: ${r.toFixed(2)} < ${min}`);
      }
    }
  }
  fs.writeFileSync(`${OUT}/contrast.json`, JSON.stringify(report.contrast, null, 1));
  expect(!low.length, low.join("\n"));
});

await step("AT-267 glass fallback without blur / reduced transparency, and a bounded effect budget on phones", async () => {
  await setTheme(A.page, "glass_light");
  // 1) reduced transparency (and the @supports fallback, which sets the same values): opaque surfaces
  const cdp = await A.ctx.newCDPSession(A.page);
  await cdp.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-transparency", value: "reduce" }] });
  await A.page.goto(BASE + "/");
  await settle(A.page);
  const solid = await A.page.evaluate(() => getComputedStyle(document.querySelector(".card")).backgroundColor);
  expect(/^rgb\(/.test(solid), "surface still translucent with reduced transparency: " + solid);
  await cdp.send("Emulation.setEmulatedMedia", { features: [] });
  const supportsRule = await A.page.evaluate(() => [...document.styleSheets].flatMap((s) => { try { return [...s.cssRules]; } catch { return []; } })
    .some((r) => r.conditionText && /not.*backdrop-filter/.test(r.conditionText) && /glass_light/.test(r.cssText)));
  expect(supportsRule, "no @supports fallback for browsers without backdrop-filter");
  // 2) phone: blur only on navigation/dialog layers; measure frame rate while scrolling under 4x CPU throttling
  const M = await signIn("admin", PW, { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
  for (const theme of ["glass_light", "glass_dark"]) {
    await setTheme(M.page, theme);
    await M.page.goto(BASE + "/folders");
    await settle(M.page);
    const blurred = await M.page.evaluate(() => [...document.querySelectorAll("*")].filter((e) => { const b = getComputedStyle(e).backdropFilter; return b && b !== "none"; }).map((e) => e.className.toString().split(" ")[0]));
    report.effects[theme] = blurred;
    expect(blurred.length <= 3, `${theme}: ${blurred.length} blurred layers on a phone (${blurred.join(", ")})`);
    const mcdp = await M.ctx.newCDPSession(M.page);
    await mcdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    const fps = await M.page.evaluate(async () => {
      const el = document.scrollingElement; let frames = 0; const t0 = performance.now();
      await new Promise((done) => { const tick = () => { frames++; el.scrollTop = (el.scrollTop + 7) % Math.max(1, el.scrollHeight - innerHeight); if (performance.now() - t0 < 2000) requestAnimationFrame(tick); else done(); }; requestAnimationFrame(tick); });
      return frames / ((performance.now() - t0) / 1000);
    });
    await mcdp.send("Emulation.setCPUThrottlingRate", { rate: 1 });
    report.frames[theme] = Number(fps.toFixed(1));
    await M.page.screenshot({ path: `${OUT}/${theme}-mobile-folders.png` });
  }
  fs.writeFileSync(`${OUT}/effects.json`, JSON.stringify({ blurredLayersOnPhone: report.effects, framesPerSecondScrolling4xCpu: report.frames }, null, 1));
  expect(Object.values(report.frames).every((f) => f >= 20), "scrolling below 20 fps under 4x CPU throttling: " + JSON.stringify(report.frames));
  await M.ctx.close();
});

await step("AT-268 focus visible, reduced motion respected, status not by colour alone — in every theme", async () => {
  const issues = [];
  for (const theme of THEMES) {
    await setTheme(A.page, theme);
    await A.page.emulateMedia({ reducedMotion: "reduce" });
    await A.page.goto(BASE + "/offline");
    await settle(A.page);
    for (let i = 0; i < 6; i++) await A.page.keyboard.press("Tab");
    const focus = await A.page.evaluate(() => { const e = document.activeElement; const cs = getComputedStyle(e); return { tag: e.tagName, ring: cs.boxShadow !== "none" || (cs.outlineStyle !== "none" && cs.outlineWidth !== "0px") }; });
    if (!focus.ring) issues.push(`${theme}: focused ${focus.tag} has no visible focus ring`);
    const motion = await A.page.evaluate(() => getComputedStyle(document.querySelector(".btn")).transitionDuration);
    if (!motion.split(",").every((d) => parseFloat(d) <= 0.001)) issues.push(`${theme}: transitions with reduced motion: ${motion}`);
    await A.page.emulateMedia({ reducedMotion: "no-preference" });
    await A.page.goto(BASE + "/folders");
    await settle(A.page);
    const textless = await A.page.evaluate(() => [...document.querySelectorAll(".badge")].filter((b) => b.offsetParent && !(b.textContent || "").trim() && !b.getAttribute("aria-label")).length);
    if (textless) issues.push(`${theme}: ${textless} badge(s) without text or accessible name`);
  }
  expect(!issues.length, issues.join("\n"));
});

await step("AT-269 theme is per account, follows it to another device and never changes another person's theme", async () => {
  await A.page.goto(BASE + "/settings/account?tab=appearance");
  await A.page.click('[data-theme-option="glass_dark"]');
  await A.page.waitForSelector('[data-theme-option="glass_dark"][aria-checked="true"]');
  await A.page.waitForTimeout(500);
  await A.page.screenshot({ path: `${OUT}/theme-gallery-glass-dark.png`, fullPage: true });
  await A.page.reload();
  await A.page.waitForFunction(() => document.documentElement.dataset.theme === "glass_dark");
  await A.page.waitForFunction(() => document.querySelector('meta[name="theme-color"]').content === "#0b1411", null, { timeout: 5000 })
    .catch(async () => { throw new Error("theme-color meta not updated: " + await A.page.evaluate(() => document.querySelector('meta[name="theme-color"]').content)); });
  const B = await signIn("admin", PW, { viewport: { width: 820, height: 1180 } }); // another device
  await B.page.goto(BASE + "/");
  await B.page.waitForFunction(() => document.documentElement.dataset.theme === "glass_dark");
  await B.ctx.close();
  const S = await signIn("son1", SON_PW);
  const t = await S.page.evaluate(() => document.documentElement.dataset.theme);
  expect(t === "green", "son1 theme changed to " + t);
  await S.ctx.close();
  await A.page.click("button:has-text('Reset to default')");
  await A.page.waitForFunction(() => document.documentElement.dataset.theme === "green");
  await A.page.waitForTimeout(500); // colour transitions settle before the capture
  await A.page.screenshot({ path: `${OUT}/theme-gallery.png`, fullPage: true });
});

await A.ctx.close();
await browser.close();
fs.writeFileSync(`${OUT}/results.json`, JSON.stringify({ results, ...report }, null, 1));
console.log(`\nthemes e2e: ${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
