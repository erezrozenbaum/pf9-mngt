import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In Docker the API container is reachable as pf9_api:8000.
// Locally (npm run dev outside Docker) it's at localhost:8000.
// Set VITE_API_TARGET in the environment to override.
const apiTarget = process.env.VITE_API_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        // No rewrite — API routes are registered with /api prefix
      },
    },
  },
});
