import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In Docker the API container is reachable as pf9_api:8000 / pf9_monitoring:8001.
// Locally (npm run dev outside Docker) use localhost.
// Set VITE_API_TARGET / VITE_MONITORING_TARGET in the environment to override.
const apiTarget        = process.env.VITE_API_TARGET        || "http://localhost:8000";
const monitoringTarget = process.env.VITE_MONITORING_TARGET || "http://localhost:8001";

// All path prefixes that must be forwarded to pf9_api.
// Mirrors the nginx location blocks so dev and prod behave identically.
const apiPrefixes = [
  "/api",
  "/auth",
  "/admin",
  "/settings",
  "/dashboard",
  "/notifications",
  "/monitoring",
  "/history",
  "/audit",
  "/drift",
  "/tenant-health",
  "/user",
  "/static",
  "/restore",
  "/domains",
  "/tenants",
  "/projects",
  "/servers",
  "/volumes",
  "/snapshots",
  "/networks",
  "/subnets",
  "/ports",
  "/floatingips",
  "/flavors",
  "/security-groups",
  "/security-group-rules",
  "/images",
  "/hypervisors",
  "/keypairs",
  "/host-aggregates",
  "/volume-types",
  "/server-groups",
  "/project-quotas",
  "/users",
  "/roles",
  "/user-activity-summary",
  "/role-assignments",
  "/os-distribution",
  "/demo-mode",
  "/health",
  "/metrics",
  "/docs",
  "/redoc",
  "/openapi.json",
];

const proxyEntries: Record<string, { target: string; changeOrigin: boolean }> = {};

// /metrics/ with trailing slash → monitoring service (must be first to win over /metrics)
proxyEntries["^/metrics/"] = { target: monitoringTarget, changeOrigin: false };

// All other API prefixes → pf9_api
for (const prefix of apiPrefixes) {
  proxyEntries[prefix] = { target: apiTarget, changeOrigin: false };
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: proxyEntries,
  },
});
