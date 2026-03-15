// Centralised API configuration.
//
// Production (nginx reverse proxy): both default to "" so all fetch calls use
// relative paths (e.g. /auth/login, /metrics/vms).  The browser sends them to
// the same origin as the UI — no CORS, works from any IP or hostname.
//
// Dev (Vite proxy): Vite's proxy rewrites relative /api/* calls to localhost.
// Set VITE_API_BASE / VITE_MONITORING_BASE in .env.local to override.
export const API_BASE: string =
  import.meta.env.VITE_API_BASE || "";

export const MONITORING_BASE: string =
  import.meta.env.VITE_MONITORING_BASE || "";
