// Builds every app icon from the single master frontend/public/icon.svg (its "mark" group), with Chromium.
//   node scripts/make_icons.mjs            (needs: cd tests/e2e && npm ci; CHROMIUM=/path/to/chrome optional)
// Outputs in frontend/public/:
//   icon-192.png, icon-512.png                     purpose "any": rounded square, transparent corners
//   icon-maskable-192.png, icon-maskable-512.png   purpose "maskable": full bleed, artwork inside the 80% safe circle
//   apple-touch-icon.png (180), apple-touch-icon-precomposed.png
//                                                   full bleed, opaque (iOS rounds the corners itself)
//   favicon-32.png, favicon-16.png, favicon.ico     simplified mark (no text lines at 16 px)
// Commit the outputs; the build does not regenerate them.
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(resolve(root, "tests/e2e/package.json"));
const { chromium } = require("playwright");
const pub = resolve(root, "frontend/public");
const master = readFileSync(resolve(pub, "icon.svg"), "utf8");
const defs = master.match(/<defs>[\s\S]*?<\/defs>/)[0];
const mark = master.match(/<g id="mark"[\s\S]*<\/g>\s*<\/svg>/)[0].replace(/<\/svg>\s*$/, "");
const noLines = mark.replace(/<g id="lines"[\s\S]*?<\/g>/, "");

// The mark's visual centre is (256, 256) after its own translate; scale it about the centre.
const compose = ({ rx, scale, lines = true }) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">${defs}
  <rect width="512" height="512" rx="${rx}" fill="url(#pd-bg)"/>
  <g transform="translate(256 256) scale(${scale}) translate(-256 -256)">${lines ? mark : noLines}</g></svg>`;

const variants = [
  { file: "icon-512.png", size: 512, svg: compose({ rx: 112, scale: 1 }) },
  { file: "icon-192.png", size: 192, svg: compose({ rx: 112, scale: 1 }) },
  { file: "icon-maskable-512.png", size: 512, svg: compose({ rx: 0, scale: 0.78 }) },
  { file: "icon-maskable-192.png", size: 192, svg: compose({ rx: 0, scale: 0.78 }) },
  { file: "apple-touch-icon.png", size: 180, svg: compose({ rx: 0, scale: 0.9 }) },
  { file: "apple-touch-icon-precomposed.png", size: 180, svg: compose({ rx: 0, scale: 0.9 }) },
  { file: "favicon-32.png", size: 32, svg: compose({ rx: 96, scale: 1.08 }) },
  { file: "favicon-16.png", size: 16, svg: compose({ rx: 96, scale: 1.15, lines: false }) },
  { file: "favicon-48.png", size: 48, svg: compose({ rx: 96, scale: 1.05 }), temp: true },
];

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
const page = await browser.newPage({ deviceScaleFactor: 1 });
const png = {};
for (const v of variants) {
  await page.setViewportSize({ width: v.size, height: v.size });
  await page.setContent(`<html><body style="margin:0;background:transparent">${v.svg.replace("<svg ", `<svg width="${v.size}" height="${v.size}" `)}</body></html>`);
  const buf = await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: v.size, height: v.size } });
  png[v.file] = buf;
  if (!v.temp) writeFileSync(resolve(pub, v.file), buf);
  console.log(`${v.file}  ${v.size}x${v.size}  ${buf.length} bytes`);
}
await browser.close();

// favicon.ico: an ICO container holding PNG images (supported by every current browser)
const imgs = [[16, png["favicon-16.png"]], [32, png["favicon-32.png"]], [48, png["favicon-48.png"]]];
const head = Buffer.alloc(6 + 16 * imgs.length);
head.writeUInt16LE(0, 0); head.writeUInt16LE(1, 2); head.writeUInt16LE(imgs.length, 4);
let offset = head.length;
imgs.forEach(([size, data], i) => {
  const o = 6 + 16 * i;
  head.writeUInt8(size, o); head.writeUInt8(size, o + 1); head.writeUInt8(0, o + 2); head.writeUInt8(0, o + 3);
  head.writeUInt16LE(1, o + 4); head.writeUInt16LE(32, o + 6); head.writeUInt32LE(data.length, o + 8); head.writeUInt32LE(offset, o + 12);
  offset += data.length;
});
writeFileSync(resolve(pub, "favicon.ico"), Buffer.concat([head, ...imgs.map(([, d]) => d)]));
console.log("favicon.ico  16/32/48");
