/*
 * AccountManagerDashboard.tsx — My Portfolio
 * ============================================
 * Role-specific view for Account Management staff.
 * Shows per-tenant SLA status, quota vs real usage, metering cost,
 * resource growth, and open insights for the entire client portfolio.
 *
 * v1.95.13
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

  // Contract vs reality
  contracted_vcpu: number;
  contracted_ram_mb: number;
  contracted_storage_gb: number;
  used_vcpu: number;
  contract_usage_pct: number | null;

  // Quota vs real usage
  quota_vcpu_limit: number | null;
  quota_vcpu_used: number | null;
  quota_vcpu_pct: number | null;
  quota_ram_limit_mb: number | null;
  quota_ram_used_mb: number | null;
  quota_ram_pct: number | null;
  quota_storage_limit_gb: number | null;
  quota_storage_used_gb: number | null;
  quota_storage_pct: number | null;

  // Metering
  metered_avg_vcpus: number | null;
  metered_avg_ram_gb: number | null;
  metered_avg_disk_gb: number | null;
  metered_cost_this_month: number | null;
  metered_currency: string;
  metered_vm_count: number | null;

  // Growth (MoM %)
  vcpu_growth_pct: number | null;
  ram_growth_pct: number | null;
  cost_growth_pct: number | null;

  // Insights
  open_critical_count: number;
  open_total_count: number;
  leakage_insight_count: number;

  // Health score
  health_score: number | null;
  score_grade: string | null;
}

interface PortfolioSummaryResponse {
  portfolio: PortfolioTenant[];
  month: string;
  total: number;
  domains: string[];
}

interface SlaDefenseSummaryResponse {
  open: {
    warning: number;
    critical: number;
  };
  total_open: number;
}

type SortKey = "name" | "tier" | "status" | "quota_vcpu" | "quota_ram" | "vcpu_growth" | "cost" | "critical" | "health_score";

interface Props {
  userRole: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function slaStatusBadge(status: PortfolioTenant["sla_status"]): React.ReactElement {
  const map: Record<string, { label: string; cls: string }> = {
    ok:             { label: "✅ OK",       cls: "badge-ok" },
    at_risk:        { label: "⚠️ At Risk",  cls: "badge-warning" },
    breached:       { label: "🚨 Breached", cls: "badge-critical" },
    not_configured: { label: "— Not Set",   cls: "badge-muted" },
  };
  const { label, cls } = map[status] ?? map.not_configured;
  return <span className={`pf9-badge ${cls}`}>{label}</span>;
}

function usageBar(pct: number | null, used?: number | null, limit?: number | null, unit = ""): React.ReactElement {
  if (pct === null) return <span className="pf9-muted">—</span>;
  const capped = Math.min(pct, 100);
  const cls = pct >= 90 ? "usage-critical" : pct >= 75 ? "usage-warning" : "usage-ok";
  return (
    <div>
      <div className="pf9-usage-bar-wrap" title={`${pct}%`}>
        <div className={`pf9-usage-bar ${cls}`} style={{ width: `${capped}%` }} />
        <span className="pf9-usage-label">{pct}%</span>
      </div>
      {used != null && limit != null && (
        <div className="pf9-muted" style={{ fontSize: "0.72rem", marginTop: "2px" }}>
          {used.toLocaleString()} / {limit.toLocaleString()} {unit}
        </div>
      )}
    </div>
  );
}

function growthBadge(pct: number | null): React.ReactElement {
  if (pct === null) return <span className="pf9-muted">—</span>;
  const color = pct > 10 ? "#22c55e" : pct < -5 ? "#ef4444" : "#94a3b8";
  const arrow = pct > 0 ? "▲" : pct < 0 ? "▼" : "–";
  return (
    <span style={{ color, fontWeight: 600, fontSize: "0.82rem" }}>
      {arrow} {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

function costCell(cost: number | null, currency: string, growth: number | null): React.ReactElement {
  if (cost === null) return <span className="pf9-muted">—</span>;
  return (
    <div>
      <div style={{ fontWeight: 600 }}>{currency} {cost.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
      <div style={{ marginTop: "2px" }}>{growthBadge(growth)}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function currentMonthValue(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function AccountManagerDashboard({ userRole: _userRole }: Props) {
  const [data, setData] = useState<PortfolioSummaryResponse | null>(null);
  const [slaDefense, setSlaDefense] = useState<SlaDefenseSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "breached" | "at_risk" | "ok" | "not_configured">("all");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortAsc, setSortAsc] = useState(true);
  const [selectedMonth, setSelectedMonth] = useState<string>(currentMonthValue());
  const [selectedDomain, setSelectedDomain] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("month", selectedMonth);
      if (selectedDomain) params.set("domain", selectedDomain);
      const [resp, slaDefenseResp] = await Promise.all([
        apiFetch<PortfolioSummaryResponse>(`/api/sla/portfolio/summary?${params}`),
        apiFetch<SlaDefenseSummaryResponse>("/api/admin/sla/defense/alerts/summary"),
      ]);
      setData(resp);
      setSlaDefense(slaDefenseResp);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load portfolio");
    } finally {
      setLoading(false);
    }
  }, [selectedMonth, selectedDomain]);

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

  const sortedFiltered = [...filtered].sort((a, b) => {
    let av: number | string | null = null;
    let bv: number | string | null = null;
    switch (sortKey) {
      case "name":        av = a.tenant_name;           bv = b.tenant_name;          break;
      case "tier":        av = a.tier;                  bv = b.tier;                 break;
      case "status":      av = a.sla_status;            bv = b.sla_status;           break;
      case "quota_vcpu":  av = a.quota_vcpu_pct;        bv = b.quota_vcpu_pct;       break;
      case "quota_ram":   av = a.quota_ram_pct;         bv = b.quota_ram_pct;        break;
      case "vcpu_growth": av = a.vcpu_growth_pct;       bv = b.vcpu_growth_pct;      break;
      case "cost":        av = a.metered_cost_this_month; bv = b.metered_cost_this_month; break;
      case "critical":    av = a.open_critical_count;   bv = b.open_critical_count;  break;
      case "health_score": av = a.health_score;           bv = b.health_score;         break;
    }
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    if (typeof av === "string" && typeof bv === "string") {
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });

  const counts = {
    ok:             portfolio.filter((t) => t.sla_status === "ok").length,
    at_risk:        portfolio.filter((t) => t.sla_status === "at_risk").length,
    breached:       portfolio.filter((t) => t.sla_status === "breached").length,
    not_configured: portfolio.filter((t) => t.sla_status === "not_configured").length,
    critical:       portfolio.reduce((s, t) => s + t.open_critical_count, 0),
    leakage:        portfolio.reduce((s, t) => s + t.leakage_insight_count, 0),
    totalCost:      portfolio.reduce((s, t) => s + (t.metered_cost_this_month ?? 0), 0),
    metered:        portfolio.filter((t) => t.metered_vm_count != null && t.metered_vm_count > 0).length,
  };

  const scoredTenants = portfolio.filter((t) => t.health_score !== null);
  const avgHealthScore = scoredTenants.length > 0
    ? Math.round(scoredTenants.reduce((s, t) => s + (t.health_score ?? 0), 0) / scoredTenants.length)
    : null;

  // Quota pressure: tenants ≥ 80% on any quota dimension
  const quotaUnderPressure = portfolio.filter(
    (t) => (t.quota_vcpu_pct ?? 0) >= 80 || (t.quota_ram_pct ?? 0) >= 80 || (t.quota_storage_pct ?? 0) >= 80
  ).length;

  // Growing tenants (any positive MoM vCPU growth)
  const growingTenants = portfolio.filter((t) => (t.vcpu_growth_pct ?? 0) > 0).length;

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortAsc((v) => !v);
    else { setSortKey(key); setSortAsc(false); }
  }

  function thSort(key: SortKey, label: string) {
    const active = sortKey === key;
    return (
      <th onClick={() => handleSort(key)} style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}>
        {label} {active ? (sortAsc ? "▲" : "▼") : <span style={{ opacity: 0.3 }}>↕</span>}
      </th>
    );
  }

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

      {/* Month + domain filters */}
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "center", marginBottom: "1rem" }}>
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.85rem", color: "#94a3b8" }}>
          📅 Month
          <input
            type="month"
            value={selectedMonth}
            max={currentMonthValue()}
            onChange={(e) => setSelectedMonth(e.target.value)}
            style={{
              background: "var(--pf9-card-bg, #1e293b)",
              border: "1px solid #334155",
              borderRadius: "6px",
              color: "#e2e8f0",
              padding: "0.3rem 0.5rem",
              fontSize: "0.85rem",
              cursor: "pointer",
            }}
          />
        </label>
        {data && data.domains.length > 1 && (
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.85rem", color: "#94a3b8" }}>
            🏢 Org
            <select
              value={selectedDomain}
              onChange={(e) => setSelectedDomain(e.target.value)}
              style={{
                background: "var(--pf9-card-bg, #1e293b)",
                border: "1px solid #334155",
                borderRadius: "6px",
                color: "#e2e8f0",
                padding: "0.3rem 0.5rem",
                fontSize: "0.85rem",
                cursor: "pointer",
              }}
            >
              <option value="">All orgs</option>
              {data.domains.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
        )}
      </div>

      {/* KPI strip */}
      <div className="pf9-kpi-strip" style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginBottom: "1.2rem" }}>
        {[
          { label: "Healthy",            value: counts.ok,             accent: "#22c55e" },
          { label: "At Risk",            value: counts.at_risk,        accent: "#f59e0b" },
          { label: "Breached",           value: counts.breached,       accent: "#ef4444" },
          { label: "Not Configured",     value: counts.not_configured, accent: "#94a3b8" },
          { label: "Open Critical",      value: counts.critical,       accent: "#dc2626" },
          { label: "Leakage Alerts",     value: counts.leakage,        accent: "#f97316" },
          { label: "Quota Under Pressure", value: quotaUnderPressure,  accent: "#a855f7" },
          { label: "Growing Tenants",    value: growingTenants,        accent: "#06b6d4" },
          {
            label: "Avg. Health Score",
            value: avgHealthScore !== null ? `${avgHealthScore}/100` : "—",
            accent: avgHealthScore !== null
              ? avgHealthScore >= 70 ? "#22c55e" : avgHealthScore >= 40 ? "#f59e0b" : "#ef4444"
              : "#94a3b8",
          },
          {
            label: "SLA Defense Alerts",
            value: slaDefense?.total_open ?? 0,
            accent: (slaDefense?.open.critical ?? 0) > 0
              ? "#ef4444"
              : (slaDefense?.open.warning ?? 0) > 0
                ? "#f59e0b"
                : "#22c55e",
          },
          {
            label: "Est. Fleet Cost (mo.)",
            value: counts.totalCost > 0
              ? `$${counts.totalCost.toLocaleString("en-US", { maximumFractionDigits: 0 })}`
              : "—",
            accent: "#60a5fa",
          },
        ].map(({ label, value, accent }) => (
          <div
            key={label}
            className="pf9-kpi-card"
            style={{ borderLeft: `3px solid ${accent}`, padding: "0.6rem 1rem", background: "var(--pf9-card-bg, #1e293b)", borderRadius: "6px", minWidth: "110px" }}
          >
            <div style={{ fontSize: "1.3rem", fontWeight: 700, color: accent }}>{value}</div>
            <div style={{ fontSize: "0.75rem", color: "#94a3b8" }}>{label}</div>
          </div>
        ))}
      </div>

      {slaDefense && slaDefense.total_open > 0 && (
        <section
          style={{
            background: "var(--pf9-card-bg, #1e293b)",
            borderRadius: "8px",
            padding: "0.9rem 1rem",
            borderLeft: `4px solid ${(slaDefense.open.critical ?? 0) > 0 ? "#ef4444" : "#f59e0b"}`,
            marginBottom: "1rem",
          }}
        >
          <div style={{ fontSize: "0.95rem", fontWeight: 600, marginBottom: "0.3rem" }}>🛡️ SLA Defense</div>
          <div style={{ fontSize: "0.85rem", color: "#cbd5e1" }}>
            {slaDefense.total_open} open proactive SLA defense alert{slaDefense.total_open !== 1 ? "s" : ""}
            {" "}({slaDefense.open.critical} critical, {slaDefense.open.warning} warning).
          </div>
        </section>
      )}

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

      {loading && !data && (
        <div className="pf9-loading">Loading portfolio…</div>
      )}

      {!loading && sortedFiltered.length === 0 && (
        <div className="pf9-empty">No clients match the current filter.</div>
      )}

      {sortedFiltered.length > 0 && (
        <div className="pf9-table-wrap" style={{ overflowX: "auto" }}>
          <table className="pf9-table">
            <thead>
              <tr>
                {thSort("name",    "Client")}
                {thSort("tier",    "SLA Tier")}
                {thSort("status",  "Status")}
                {thSort("quota_vcpu", "vCPU Quota")}
                {thSort("quota_ram",  "RAM Quota")}
                <th style={{ whiteSpace: "nowrap" }}>Storage Quota</th>
                <th style={{ whiteSpace: "nowrap" }}>Metered VMs</th>
                {thSort("cost",        "Cost (mo.)")}
                {thSort("vcpu_growth", "vCPU Growth")}
                <th style={{ whiteSpace: "nowrap" }}>Critical</th>
                <th style={{ whiteSpace: "nowrap" }}>Leakage</th>
                <th style={{ whiteSpace: "nowrap" }}>Breach Fields</th>
                {thSort("health_score", "Health")}
              </tr>
            </thead>
            <tbody>
              {sortedFiltered.map((t) => (
                <tr
                  key={t.tenant_id}
                  className={
                    t.sla_status === "breached" ? "row-critical"
                    : t.sla_status === "at_risk" ? "row-warning"
                    : ""
                  }
                >
                  <td style={{ fontWeight: 500, whiteSpace: "nowrap" }}>{t.tenant_name}</td>
                  <td style={{ textTransform: "capitalize" }}>{t.tier === "none" ? "—" : t.tier}</td>
                  <td>{slaStatusBadge(t.sla_status)}</td>

                  {/* vCPU quota */}
                  <td style={{ minWidth: "130px" }}>
                    {usageBar(t.quota_vcpu_pct, t.quota_vcpu_used, t.quota_vcpu_limit, "cores")}
                    {t.contracted_vcpu > 0 && t.quota_vcpu_limit == null && (
                      <div className="pf9-muted" style={{ fontSize: "0.72rem" }}>
                        Contract: {t.used_vcpu} / {t.contracted_vcpu} cores
                      </div>
                    )}
                  </td>

                  {/* RAM quota */}
                  <td style={{ minWidth: "130px" }}>
                    {usageBar(
                      t.quota_ram_pct,
                      t.quota_ram_used_mb != null ? Math.round(t.quota_ram_used_mb / 1024) : null,
                      t.quota_ram_limit_mb != null ? Math.round(t.quota_ram_limit_mb / 1024) : null,
                      "GB"
                    )}
                  </td>

                  {/* Storage quota */}
                  <td style={{ minWidth: "130px" }}>
                    {usageBar(t.quota_storage_pct, t.quota_storage_used_gb, t.quota_storage_limit_gb, "GB")}
                  </td>

                  {/* Metered VMs */}
                  <td style={{ textAlign: "center" }}>
                    {t.metered_vm_count != null
                      ? <span style={{ fontWeight: 600 }}>{t.metered_vm_count}</span>
                      : <span className="pf9-muted">—</span>
                    }
                  </td>

                  {/* Monthly cost */}
                  <td style={{ minWidth: "110px" }}>
                    {costCell(t.metered_cost_this_month, t.metered_currency, t.cost_growth_pct)}
                  </td>

                  {/* vCPU growth MoM */}
                  <td style={{ textAlign: "center" }}>
                    {growthBadge(t.vcpu_growth_pct)}
                  </td>

                  {/* Critical insights */}
                  <td style={{ textAlign: "center" }}>
                    {t.open_critical_count > 0 ? (
                      <span className="pf9-badge badge-critical">{t.open_critical_count}</span>
                    ) : (
                      <span className="pf9-muted">—</span>
                    )}
                  </td>

                  {/* Leakage */}
                  <td style={{ textAlign: "center" }}>
                    {t.leakage_insight_count > 0 ? (
                      <span className="pf9-badge badge-warning">{t.leakage_insight_count}</span>
                    ) : (
                      <span className="pf9-muted">—</span>
                    )}
                  </td>

                  {/* Breach / at-risk fields */}
                  <td style={{ fontSize: "0.78rem", maxWidth: "180px" }}>
                    {t.breach_fields.length > 0
                      ? t.breach_fields.join(", ")
                      : t.at_risk_fields.length > 0
                        ? <span className="pf9-muted">{t.at_risk_fields.join(", ")} (at risk)</span>
                        : <span className="pf9-muted">—</span>
                    }
                  </td>

                  {/* Health score */}
                  <td style={{ textAlign: "center", minWidth: "80px" }}>
                    {t.health_score !== null ? (
                      <span
                        style={{
                          fontWeight: 700,
                          color: t.health_score >= 70 ? "#22c55e" : t.health_score >= 40 ? "#f59e0b" : "#ef4444",
                        }}
                        title={`Grade: ${t.score_grade ?? "—"}`}
                      >
                        {t.health_score}
                        <span style={{ fontSize: "0.72rem", marginLeft: "3px", opacity: 0.7 }}>{t.score_grade}</span>
                      </span>
                    ) : (
                      <span className="pf9-muted">—</span>
                    )}
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
