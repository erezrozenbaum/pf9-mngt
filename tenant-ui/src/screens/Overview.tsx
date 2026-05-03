/**
 * Overview.tsx — Client Health Overview screen for the Tenant Portal.
 *
 * Fetches the client-health summary for the authenticated user's primary project
 * and renders HealthDials + key insight counts + capacity runway.
 */

import { useEffect, useState } from "react";
import { tenantFetch } from "../lib/api";
import { HealthDials, type ClientHealth } from "../components/HealthDials";

export function Overview() {
  const [health, setHealth] = useState<ClientHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    // The tenant portal proxies this from the admin API using the service secret
    tenantFetch<ClientHealth>("/tenant/client-health")
      .then(setHealth)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div style={{ 
        padding: "2rem", 
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        minHeight: "50vh",
      }}>
        <div style={{
          color: "var(--color-text-secondary)",
          fontSize: "1rem",
          display: "flex",
          alignItems: "center",
          gap: "0.75rem",
        }}>
          <div className="loading-spinner"></div>
          Loading health overview…
        </div>
      </div>
    );
  }

  if (error || !health) {
    return (
      <div style={{ 
        padding: "2rem",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        minHeight: "50vh",
      }}>
        <div style={{
          background: "var(--color-surface)",
          border: "1px solid var(--color-error)",
          borderRadius: "var(--radius-lg)",
          padding: "2rem",
          textAlign: "center",
          maxWidth: "400px",
        }}>
          <div style={{
            color: "var(--color-error)",
            fontSize: "1.125rem",
            fontWeight: "600",
            marginBottom: "0.5rem",
          }}>
            Unable to Load Health Overview
          </div>
          {error && (
            <div style={{
              color: "var(--color-text-secondary)",
              fontSize: "0.875rem",
            }}>
              {error}
            </div>
          )}
        </div>
      </div>
    );
  }

  const lastUpdate = (() => {
    try {
      return new Date(health.last_computed).toLocaleString(undefined, {
        month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit",
      });
    } catch {
      return health.last_computed;
    }
  })();

  return (
    <div style={{ padding: "1.25rem 1.5rem", display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Health Overview</h2>
        <span style={{ fontSize: "0.75rem", color: "rgba(255,255,255,0.4)" }}>
          Last computed: {lastUpdate}
        </span>
      </div>

      <HealthDials health={health} />

      {/* Open-insights detail */}
      {(health.open_critical > 0 || health.open_high > 0 || health.open_medium > 0) && (
        <div style={{
          background: "rgba(0,0,0,0.2)",
          borderRadius: "8px",
          padding: "1rem 1.25rem",
          display: "flex",
          gap: "1.5rem",
          flexWrap: "wrap",
        }}>
          <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "rgba(255,255,255,0.6)" }}>
            Open insights:
          </span>
          {health.open_critical > 0 && (
            <span style={{ color: "#f87171" }}>
              <strong>{health.open_critical}</strong> critical
            </span>
          )}
          {health.open_high > 0 && (
            <span style={{ color: "#fb923c" }}>
              <strong>{health.open_high}</strong> high
            </span>
          )}
          {health.open_medium > 0 && (
            <span style={{ color: "#facc15" }}>
              <strong>{health.open_medium}</strong> medium
            </span>
          )}
          <span style={{ fontSize: "0.8rem", color: "rgba(255,255,255,0.4)", marginLeft: "auto" }}>
            Contact your cloud admin for details
          </span>
        </div>
      )}

      {/* Capacity runway */}
      {health.capacity_runway_days != null && (
        <div style={{
          background: health.capacity_runway_days < 14
            ? "rgba(239,68,68,0.15)"
            : health.capacity_runway_days < 30
              ? "rgba(249,115,22,0.12)"
              : "rgba(34,197,94,0.1)",
          border: `1px solid ${health.capacity_runway_days < 14 ? "rgba(239,68,68,0.4)" : health.capacity_runway_days < 30 ? "rgba(249,115,22,0.35)" : "rgba(34,197,94,0.3)"}`,
          borderRadius: "8px",
          padding: "1rem 1.25rem",
        }}>
          <div style={{ fontWeight: 600, fontSize: "0.9rem", marginBottom: "0.25rem" }}>
            Capacity Runway
          </div>
          <div style={{ fontSize: "0.85rem", color: "rgba(255,255,255,0.75)" }}>
            Your <strong>{health.capacity_runway_resource}</strong> quota will reach 90% utilisation
            in approximately <strong>{health.capacity_runway_days} day{health.capacity_runway_days !== 1 ? "s" : ""}</strong>.
          </div>
          {health.capacity_runway_days < 14 && (
            <div style={{ marginTop: "0.5rem", fontSize: "0.8rem", color: "#f87171" }}>
              ⚠️ Contact your admin to request a quota increase before reaching the limit.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default Overview;
