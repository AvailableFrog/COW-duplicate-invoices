import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The built output is served by the Python process from the same loopback
// port as the API. The dev server below is only a convenience for frontend
// work and proxies API calls to a running backend; a reviewer never needs it.
export default defineConfig({
  plugins: [react()],
  // Vega is a lazily loaded chunk of about 520 kB, read from loopback, so the default 500 kB warning is raised.
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 600 },
  server: { host: "127.0.0.1", proxy: { "/api": "http://127.0.0.1:8765" } },
});
