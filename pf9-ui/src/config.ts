// Centralised API configuration — override via VITE_API_BASE environment variable.
// In Docker-compose, the Vite dev-server proxy (/api → pf9_api:8000) is available,
// so you can set VITE_API_BASE="" to use relative URLs.  For local development
// outside Docker the default http://localhost:8000 is used.
export const API_BASE: string =
  import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// Monitoring service base URL (port 8001 by default).
export const MONITORING_BASE: string =
  import.meta.env.VITE_MONITORING_BASE ?? "http://localhost:8001";
