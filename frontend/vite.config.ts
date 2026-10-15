import { cpSync, existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { brotliCompressSync, constants as zc, gzipSync } from "node:zlib";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// PDF.js support files (standard fonts, character maps, image decoders) are served from the app itself, so the
// document viewer never contacts another site. The version is part of the path because /static/ is cached forever.
const PDFJS = resolve(__dirname, "node_modules/pdfjs-dist");
const PDFJS_VERSION = JSON.parse(readFileSync(resolve(PDFJS, "package.json"), "utf8")).version as string;

function pdfjsAssets(): Plugin {
  return {
    name: "pdfjs-assets",
    apply: "build",
    closeBundle() {
      for (const dir of ["standard_fonts", "cmaps", "wasm", "iccs"]) {
        const src = resolve(PDFJS, dir);
        if (existsSync(src)) cpSync(src, resolve(__dirname, `dist/static/app/pdfjs-${PDFJS_VERSION}/${dir}`), { recursive: true });
      }
    },
  };
}

// Change Set X: pre-compressed copies (.br and .gz) of every text asset, written next to the file. The server
// (WhiteNoise) sends them to browsers that accept them; nothing is compressed per request. Node's own zlib: no
// extra dependency.
function precompress(): Plugin {
  const TEXT = /\.(js|mjs|css|html|svg|json|webmanifest|txt|map|bcmap|ttf|pfb)$/i;
  const walk = (dir: string): string[] => readdirSync(dir).flatMap((n) => {
    const p = resolve(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
  return {
    name: "precompress",
    apply: "build",
    closeBundle() {
      const out = resolve(__dirname, "dist");
      for (const f of walk(out)) {
        if (!TEXT.test(f) || statSync(f).size < 1024) continue;
        const buf = readFileSync(f);
        const br = brotliCompressSync(buf, { params: { [zc.BROTLI_PARAM_QUALITY]: 11, [zc.BROTLI_PARAM_SIZE_HINT]: buf.length } });
        const gz = gzipSync(buf, { level: 9 });
        if (br.length < buf.length * 0.95) writeFileSync(f + ".br", br);
        if (gz.length < buf.length * 0.95) writeFileSync(f + ".gz", gz);
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), pdfjsAssets(), precompress()],
  // MapLibre (sign-in map, Change Set V): always the CSP build, whose worker is a same-origin file - the strict
  // Content-Security-Policy (script-src 'self', no blob: workers) stays unchanged. The Leaflet bridge imports
  // "maplibre-gl" too, so the alias covers it.
  resolve: { alias: [{ find: /^maplibre-gl$/, replacement: resolve(__dirname, "node_modules/maplibre-gl/dist/maplibre-gl-csp.js") }] },
  define: { __PDFJS_ASSETS__: JSON.stringify(`/static/app/pdfjs-${PDFJS_VERSION}/`) },
  build: {
    outDir: "dist",
    assetsDir: "static/app",
    sourcemap: false,
    chunkSizeWarningLimit: 600, // PDF.js is loaded on demand, only when a document is viewed
    rollupOptions: { input: { main: "index.html", sw: "src/sw.ts" }, output: { entryFileNames: (c) => (c.name === "sw" ? "sw.js" : "static/app/[name]-[hash].js") } },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8000", "/s/": "http://127.0.0.1:8000" } },
});
