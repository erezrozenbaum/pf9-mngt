/*
 * ExecutiveDashboard.tsx — Portfolio Health
 * ==========================================
 * Fleet-wide executive view: SLA health, revenue leakage estimate,
 * critical alert count, and MTTR performance.
 *
 * v1.92.0 (Phase 6)
 */
import React, { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ExecutiveSummary {
  total_clients: number;
  sla_healthy: number;
  sla_at_risk: number;
  sla_breached: number;
  sla_not_configured: number;
  sla_health_pct: number;
  revenue_leakage_monthly: number | null;
  leakage_client_count: number;
  leakage_insight_count: number;
  open_critical_insights: number;
  avg_mttr_hours: number | null;
  avg_mttr_commitment_hours: number | null;
}

interface ExecutiveSummaryResponse {
  summary: ExecutiveSummary;
  month: string;
}

interface Props {
  userRole: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mttrStatus(actual: number | null, commitment: number | null): { label: string; color: string } {
  if (actual === null) return { label: "No data", color: "#94a3b8" };
  if (commitment === null) return { label: `${actual.toFixed(1)}h avg`, color: "#60a5fa" };
  const ratio = actual / commitment;
  if (ratio <= 0.8)  return { label: `${actual.toFixed(1)}h (well within ${commitment}h)`, color: "#22c55e" };
  if (ratio <= 1.0)  return { label: `${actual.toFixed(1)}h (within ${commitment}h)`,      color: "#f59e0b" };
  return { label: `${actual.toFixed(1)}h (EXCEEDS ${commitment}h)`, color: "#ef4444" };
}

function formatMoney(value: number | null): string {
  if (value === null) return "N/A — configure contract pricing";
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface KpiCardProps {
  label: string;
  value: React.ReactNode;
  accent: string;
  sub?: string;
}

function KpiCard({ label, value, accent, sub }: KpiCardProps) {
  return (
    <div
      className="pf9-kpi-card"
      style={{
        borderLeft: `4px solid ${accent}`,
        padding: "1rem 1.2rem",
        background: "var(--pf9-card-bg, #1e293b)",
        borderRadius: "8px",
        minWidth: "160px",
        flex: "1 1 160px",
      }}
    >
      <div style={{ fontSize: "1.8rem", fontWeight: 700, color: accent, lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#e2e8f0", marginTop: "0.25rem" }}>{label}</div>
      {sub && <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginTop: "0.15rem" }}>{sub}</div>}
    </div>
  );
}

function SlaDonut({ summary }: { summary: ExecutiveSummary }) {
  const total = summary.total_clients || 1;
  const segments = [
    { label: "Healthy",        count: summary.sla_healthy,        color: "#22c55e" },
    { label: "At Risk",        count: summary.sla_at_risk,        color: "#f59e0b" },
    { label: "Breached",       count: summary.sla_breached,       color: "#ef4444" },
    { label: "Not Configured", count: summary.sla_not_configured, color: "#475569" },
  ].filter((s) => s.count > 0);

  let offset = 0;
  const bars = segments.map((s) => {
    const pct = (s.count / total) * 100;
    const bar = { ...s, offset, pct };
    offset += pct;
    return bar;
  });

  return (
    <div style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
      {/* Bar chart (horizontal stacked) */}
      <div
        style={{
          display: "flex",
          height: "28px",
          borderRadius: "6px",
          overflow: "hidden",
          flex: "1 1 200px",
          minWidth: "200px",
          maxWidth: "380px",
        }}
      >
        {bars.map((s) => (
          <div
            key={s.label}
            style={{ width: `${s.pct}%`, background: s.color }}
            title={`${s.label}: ${s.count} (${s.pct.toFixed(1)}%)`}
          />
        ))}
      </div>
      {/* Legend */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem" }}>
        {segments.map((s) => (
          <span key={s.label} style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "0.82rem" }}>
            <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: s.color }} />
            <span style={{ color: "#e2e8f0" }}>{s.label}: {s.count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ExecutiveDashboard({ userRole: _userRole }: Props) {
  const [data, setData] = useState<ExecutiveSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch<ExecutiveSummaryResponse>("/api/sla/portfolio/executive-summary");
      setData(resp);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load executive summary");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const s = data?.summary;
  const mttr = s ? mttrStatus(s.avg_mttr_hours, s.avg_mttr_commitment_hours) : null;

  return (
    <div className="pf9-intelligence-view">
      <div className="pf9-section-header">
        <h2>📊 Portfolio Health</h2>
        {data && (
          <span className="pf9-muted" style={{ fontSize: "0.85rem" }}>
            {data.month}
          </span>
        )}
        <button
          className="pf9-btn pf9-btn-sm"
          onClick={load}
          style={{ marginLeft: "auto" }}
          disabled={loading}
        >
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      {error && (
        <div className="pf9-alert pf9-alert-error" style={{ marginBottom: "0.8rem" }}>{error}</div>
      )}

      {loading && !data && (
        <div className="pf9-loading">Loading executive summary…</div>
      )}

      {s && (
        <>
          {/* SLA health overview */}
          <section style={{ marginBottom: "1.5rem" }}>
            <h3 style={{ fontSize: "0.95rem", color: "#94a3b8", marginBottom: "0.6rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              SLA Fleet Health
            </h3>
            <SlaDonut summary={s} />
          </section>

          {/* KPI grid */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.8rem", marginBottom: "1.5rem" }}>
            <KpiCard
              label="Fleet Health"
              value={`${s.sla_health_pct}%`}
              accent={s.sla_health_pct >= 90 ? "#22c55e" : s.sla_health_pct >= 70 ? "#f59e0b" : "#ef4444"}
              sub={`${s.sla_healthy} of ${s.total_clients} clients OK`}
            />
            <KpiCard
              label="SLA Breached"
              value={s.sla_breached}
              accent={s.sla_breached === 0 ? "#22c55e" : "#ef4444"}
              sub={s.sla_breached === 0 ? "No breaches this month" : "Require immediate action"}
            />
            <KpiCard
              label="SLA At Risk"
              value={s.sla_at_risk}
              accent={s.sla_at_risk === 0 ? "#22c55e" : "#f59e0b"}
              sub="Approaching breach threshold"
            />
            <KpiCard
              label="Open Critical Issues"
              value={s.open_critical_insights}
              accent={s.open_critical_insights === 0 ? "#22c55e" : "#dc2626"}
              sub="Across all clients"
            />
            <KpiCard
              label="Est. Revenue Leakage"
              value={s.revenue_leakage_monthly !== null ? `$${s.revenue_leakage_monthly.toLocaleString()}` : "—"}
              accent={s.revenue_leakage_monthly && s.revenue_leakage_monthly > 0 ? "#f97316" : "#22c55e"}
              sub={
                s.revenue_leakage_monthly !== null
                  ? `${s.leakage_client_count} clients affected`
                  : "Set contract unit prices to compute"
              }
            />
            <KpiCard
              label="Avg MTTR"
              value={s.avg_mttr_hours !== null ? `${s.avg_mttr_hours.toFixed(1)}h` : "—"}
              accent={mttr ? mttr.color : "#94a3b8"}
              sub={mttr?.label}
            />
          </div>

          {/* Revenue leakage detail */}
          {s.leakage_insight_count > 0 && (
            <section
              style={{
                background: "var(--pf9-card-bg, #1e293b)",
                borderRadius: "8px",
                padding: "1rem 1.2rem",
                borderLeft: "4px solid #f97316",
                marginBottom: "1rem",
              }}
            >
              <h3 style={{ margin: "0 0 0.4rem", fontSize: "0.95rem" }}>💰 Revenue Leakage Summary</h3>
              <p style={{ margin: 0, fontSize: "0.88rem", color: "#cbd5e1" }}>
                <strong>{s.leakage_insight_count}</strong> leakage signals detected across{" "}
                <strong>{s.leakage_client_count}</strong> client{s.leakage_client_count !== 1 ? "s" : ""}.{" "}
                Estimated monthly impact:{" "}
                <strong style={{ color: "#f97316" }}>{formatMoney(s.revenue_leakage_monthly)}</strong>.
                {s.revenue_leakage_monthly === null && (
                  <span className="pf9-muted"> Dollar estimates require unit_price on contract entitlements.</span>
                )}
              </p>
            </section>
          )}

          {/* MTTR compliance note */}
          {s.avg_mttr_hours !== null && s.avg_mttr_commitment_hours !== null && (
            <section
              style={{
                background: "var(--pf9-card-bg, #1e293b)",
                borderRadius: "8px",
                padding: "1rem 1.2rem",
                borderLeft: `4px solid ${mttr?.color ?? "#60a5fa"}`,
              }}
            >
              <h3 style={{ margin: "0 0 0.4rem", fontSize: "0.95rem" }}>⏱ Mean Time to Recover</h3>
              <p style={{ margin: 0, fontSize: "0.88rem", color: "#cbd5e1" }}>
                Fleet average MTTR:{" "}
                <strong style={{ color: mttr?.color }}>{s.avg_mttr_hours.toFixed(1)} hours</strong> ·
                Average commitment: <strong>{s.avg_mttr_commitment_hours.toFixed(1)} hours</strong>.{" "}
                {s.avg_mttr_hours > s.avg_mttr_commitment_hours
                  ? "⚠️ Average recovery time is exceeding contracted commitments."
                  : "Fleet is recovering within committed windows."}
              </p>
            </section>
          )}
        </>
      )}
    </div>
  );
}
