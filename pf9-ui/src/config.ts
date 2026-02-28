// Centralised API configuration — override via VITE_API_BASE environment variable.
// Default is the API container on localhost:8000 (direct calls with CORS).
// Set VITE_API_BASE="" to use relative URLs through the Vite proxy instead.
export const API_BASE: string =
  import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// Monitoring service base URL (port 8001 by default).
export const MONITORING_BASE: string =
  import.meta.env.VITE_MONITORING_BASE ?? "http://localhost:8001";
