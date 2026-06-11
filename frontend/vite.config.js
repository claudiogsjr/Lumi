import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/chat": "http://localhost:8080",
      "/logs-data": "http://localhost:8080",
      "/results-data": "http://localhost:8080",
      "/settings": "http://localhost:8080",
      "/logs-csv": "http://localhost:8080",
      "/api": "http://localhost:8080",
    },
  },
});
