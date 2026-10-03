import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    assetsDir: "static/app",
    sourcemap: false,
    rollupOptions: { input: { main: "index.html", sw: "src/sw.ts" }, output: { entryFileNames: (c) => (c.name === "sw" ? "sw.js" : "static/app/[name]-[hash].js") } },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8000", "/s/": "http://127.0.0.1:8000" } },
});
