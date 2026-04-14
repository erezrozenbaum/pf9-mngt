import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In Docker the API container is reachable as tenant_portal:8010.
// Locally (npm run dev) use localhost:8010.
const tenantApiTarget = process.env.VITE_TENANT_API_TARGET || "http://localhost:8010";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8080,
    host: "0.0.0.0",
    proxy: {
      "/tenant": {
        target: tenantApiTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
