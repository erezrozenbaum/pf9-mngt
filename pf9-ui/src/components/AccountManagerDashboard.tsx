/*
 * AccountManagerDashboard.tsx — My Portfolio
 * ============================================
 * Role-specific view for Account Management staff.
 * Shows per-tenant SLA status, contract usage, and open insights
 * for the entire client portfolio at a glance.
 *
 * v1.92.0 (Phase 6)
 */
import React, { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PortfolioTenant {
  tenant_id: string;
  tenant_name: string;
  tier: string;
  sla_status: "ok" | "at_risk" | "breached" | "not_configured";
  breach_fields: string[];
  at_risk_fields: string[];
  contracted_vcpu: number;
  used_vcpu: number;
  contract_usage_pct: number | null;
  open_critical_count: number;
  open_total_count: number;
  leakage_insight_count: number;
}

interface PortfolioSummaryResponse {
  portfolio: PortfolioTenant[];
  month: string;
  total: number;
}

interface Props {
  userRole: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function slaStatusBadge(status: PortfolioTenant["sla_status"]): React.ReactElement {
  const map: Record<string, { label: string; cls: string }> = {
    ok:             { label: "✅ OK",           cls: "badge-ok" },
    at_risk:        { label: "⚠️ At Risk",      cls: "badge-warning" },
    breached:       { label: "🚨 Breached",     cls: "badge-critical" },
    not_configured: { label: "—  Not Set",      cls: "badge-muted" },
  };
  const { label, cls } = map[status] ?? map.not_configured;
  return <span className={`pf9-badge ${cls}`}>{label}</span>;
}

function usageBar(pct: number | null): React.ReactElement {
  if (pct === null) return <span className="pf9-muted">—</span>;
  const capped = Math.min(pct, 100);
  const cls = pct >= 90 ? "usage-critical" : pct >= 75 ? "usage-warning" : "usage-ok";
  return (
    <div className="pf9-usage-bar-wrap" title={`${pct}%`}>
      <div className={`pf9-usage-bar ${cls}`} style={{ width: `${capped}%` }} />
      <span className="pf9-usage-label">{pct}%</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AccountManagerDashboard({ userRole: _userRole }: Props) {
  const [data, setData] = useState<PortfolioSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "breached" | "at_risk" | "ok" | "not_configured">("all");
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch<PortfolioSummaryResponse>("/api/sla/portfolio/summary");
      setData(resp);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load portfolio");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const portfolio = data?.portfolio ?? [];
  const filtered = portfolio.filter((t) => {
    const matchStatus = filter === "all" || t.sla_status === filter;
    const matchSearch = search === "" || t.tenant_name.toLowerCase().includes(search.toLowerCase());
    return matchStatus && matchSearch;
  });

  const counts = {
    ok:             portfolio.filter((t) => t.sla_status === "ok").length,
    at_risk:        portfolio.filter((t) => t.sla_status === "at_risk").length,
    breached:       portfolio.filter((t) => t.sla_status === "breached").length,
    not_configured: portfolio.filter((t) => t.sla_status === "not_configured").length,
    critical:       portfolio.reduce((s, t) => s + t.open_critical_count, 0),
    leakage:        portfolio.reduce((s, t) => s + t.leakage_insight_count, 0),
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="pf9-intelligence-view">
      <div className="pf9-section-header">
        <h2>📋 My Portfolio</h2>
        {data && (
          <span className="pf9-muted" style={{ fontSize: "0.85rem" }}>
            {data.total} clients · {data.month}
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

      {/* KPI strip */}
      <div className="pf9-kpi-strip" style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginBottom: "1.2rem" }}>
        {[
          { label: "Healthy",        value: counts.ok,             accent: "#22c55e" },
          { label: "At Risk",        value: counts.at_risk,        accent: "#f59e0b" },
          { label: "Breached",       value: counts.breached,       accent: "#ef4444" },
          { label: "Not Configured", value: counts.not_configured, accent: "#94a3b8" },
          { label: "Open Critical",  value: counts.critical,       accent: "#dc2626" },
          { label: "Leakage Alerts", value: counts.leakage,        accent: "#f97316" },
        ].map(({ label, value, accent }) => (
          <div
            key={label}
            className="pf9-kpi-card"
            style={{ borderLeft: `3px solid ${accent}`, padding: "0.6rem 1rem", background: "var(--pf9-card-bg, #1e293b)", borderRadius: "6px", minWidth: "110px" }}
          >
            <div style={{ fontSize: "1.4rem", fontWeight: 700, color: accent }}>{value}</div>
            <div style={{ fontSize: "0.78rem", color: "#94a3b8" }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Filter + search bar */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.8rem", flexWrap: "wrap", alignItems: "center" }}>
        {(["all", "ok", "at_risk", "breached", "not_configured"] as const).map((f) => (
          <button
            key={f}
            className={`pf9-filter-btn${filter === f ? " active" : ""}`}
            onClick={() => setFilter(f)}
          >
            {f === "all" ? "All" : f === "ok" ? "✅ OK" : f === "at_risk" ? "⚠️ At Risk" : f === "breached" ? "🚨 Breached" : "— Not Configured"}
          </button>
        ))}
        <input
          className="pf9-input"
          type="text"
          placeholder="Search clients…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ marginLeft: "auto", maxWidth: "220px" }}
        />
      </div>

      {/* Error */}
      {error && (
        <div className="pf9-alert pf9-alert-error" style={{ marginBottom: "0.8rem" }}>
          {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && !data && (
        <div className="pf9-loading">Loading portfolio…</div>
      )}

      {/* Table */}
      {!loading && filtered.length === 0 && (
        <div className="pf9-empty">No clients match the current filter.</div>
      )}

      {filtered.length > 0 && (
        <div className="pf9-table-wrap" style={{ overflowX: "auto" }}>
          <table className="pf9-table">
            <thead>
              <tr>
                <th>Client</th>
                <th>SLA Tier</th>
                <th>Status</th>
                <th>vCPU Usage</th>
                <th>Critical Issues</th>
                <th>Leakage Alerts</th>
                <th>Breach Fields</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={t.tenant_id} className={t.sla_status === "breached" ? "row-critical" : t.sla_status === "at_risk" ? "row-warning" : ""}>
                  <td style={{ fontWeight: 500 }}>{t.tenant_name}</td>
                  <td style={{ textTransform: "capitalize" }}>{t.tier === "none" ? "—" : t.tier}</td>
                  <td>{slaStatusBadge(t.sla_status)}</td>
                  <td style={{ minWidth: "120px" }}>
                    {usageBar(t.contract_usage_pct)}
                    {t.contracted_vcpu > 0 && (
                      <span className="pf9-muted" style={{ fontSize: "0.75rem" }}>
                        {t.used_vcpu} / {t.contracted_vcpu} cores
                      </span>
                    )}
                  </td>
                  <td>
                    {t.open_critical_count > 0 ? (
                      <span className="pf9-badge badge-critical">{t.open_critical_count}</span>
                    ) : (
                      <span className="pf9-muted">—</span>
                    )}
                  </td>
                  <td>
                    {t.leakage_insight_count > 0 ? (
                      <span className="pf9-badge badge-warning">{t.leakage_insight_count}</span>
                    ) : (
                      <span className="pf9-muted">—</span>
                    )}
                  </td>
                  <td style={{ fontSize: "0.8rem" }}>
                    {t.breach_fields.length > 0
                      ? t.breach_fields.join(", ")
                      : t.at_risk_fields.length > 0
                        ? <span className="pf9-muted">{t.at_risk_fields.join(", ")} (at risk)</span>
                        : <span className="pf9-muted">—</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
