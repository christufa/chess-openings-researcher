import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The build is copied into the API image and served next to /api (docker/Dockerfile.api).
// For local work, `npm run dev` proxies /api to an API on :8000 (e.g. a port-forward), or to
// API_PROXY when set.
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { proxy: { "/api": loadEnv(mode, ".", "API_").API_PROXY || "http://127.0.0.1:8000" } },
}));
