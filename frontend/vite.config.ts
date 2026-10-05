import { cpSync, existsSync, readFileSync } from "node:fs";
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

export default defineConfig({
  plugins: [react(), pdfjsAssets()],
  define: { __PDFJS_ASSETS__: JSON.stringify(`/static/app/pdfjs-${PDFJS_VERSION}/`) },
  build: {
    outDir: "dist",
    assetsDir: "static/app",
    sourcemap: false,
    rollupOptions: { input: { main: "index.html", sw: "src/sw.ts" }, output: { entryFileNames: (c) => (c.name === "sw" ? "sw.js" : "static/app/[name]-[hash].js") } },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8000", "/s/": "http://127.0.0.1:8000" } },
});
