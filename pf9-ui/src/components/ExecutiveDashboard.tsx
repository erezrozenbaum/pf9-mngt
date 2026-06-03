/*
 * ExecutiveDashboard.tsx — Portfolio Health
 * ==========================================
 * Fleet-wide executive view: SLA health, metering summary, quota utilisation,
 * resource growth trends, revenue leakage, and MTTR performance.
 *
 * v1.95.13
 */
import React, { useState, useEffect, useCallback, useMemo } from "react";
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

interface FleetTotals {
  avg_vcpus: number | null;
  avg_ram_gb: number | null;
  avg_disk_gb: number | null;
  cost_this_month: number | null;
  vm_count: number;
  currency: string;
  vcpu_growth_pct: number | null;
  cost_growth_pct: number | null;
  is_partial_month?: boolean;
}

interface QuotaResource {
  limit: number | null;
  used: number | null;
  utilization_pct: number | null;
}

interface TrendPoint {
  month: string;
  tenant_count: number;
  total_avg_vcpus: number | null;
  total_avg_ram_gb: number | null;
  total_avg_disk_gb: number | null;
  total_cost: number | null;
  total_vms: number;
}

interface GrowthTenant {
  tenant_name: string;
  vcpus_this_month: number | null;
  vcpus_prev_month: number | null;
  vcpu_growth_pct: number | null;
  cost_this_month: number | null;
  cost_prev_month: number | null;
  cost_growth_pct: number | null;
  currency: string;
}

interface FleetMeteringResponse {
  period?: string;
  month: string;
  fleet_totals: FleetTotals;
  contracted_totals: Record<string, number>;
  quota_health: Record<string, QuotaResource>;
  monthly_trend: TrendPoint[];
  top_growing_tenants: GrowthTenant[];
}

interface SlaDefenseSummaryResponse {
  open: {
    warning: number;
    critical: number;
  };
  total_open: number;
}

interface SlaDefenseAlertItem {
  id: number;
  project_id: string;
  project_name: string | null;
  threat_type: string;
  severity: "warning" | "critical";
  status: "open" | "resolved" | "dismissed";
  triggered_at: string;
  resolution_note: string | null;
}

interface SlaDefenseAlertsResponse {
  items: SlaDefenseAlertItem[];
  count: number;
}

interface ExecutiveInsightTenantRow {
  tenant_id: string;
  tenant_name: string;
  domain_name: string;
  sales_person_id: string;
  prev_vms: number;
  cur_vms: number;
  prev_cost: number;
  cur_cost: number;
  churn_reason?: string;
}

interface ExecutiveSalesRow {
  sales_person_id: string;
  tenant_count: number;
  churned_count: number;
  new_count: number;
  current_vms: number;
  current_cost: number;
}

interface ExecutiveOrderProgressRow {
  stage: string;
  event_count: number;
  tenant_count: number;
}

interface ExecutiveInsightsResponse {
  month: string;
  previous_month: string;
  filters: {
    domain: string | null;
    sales_person: string | null;
    top_n: number;
    available_domains: string[];
    available_sales_people: string[];
  };
  summary: {
    total_tenants: number;
    active_tenants: number;
    top_churned_count: number;
    top_new_count: number;
  };
  top_churned: ExecutiveInsightTenantRow[];
  top_new_connections: ExecutiveInsightTenantRow[];
  sales_person_analysis: ExecutiveSalesRow[];
  churn_reasons: { reason: string; count: number }[];
  order_progress: ExecutiveOrderProgressRow[];
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
  if (ratio <= 0.8) return { label: `${actual.toFixed(1)}h (well within ${commitment}h)`, color: "#22c55e" };
  if (ratio <= 1.0) return { label: `${actual.toFixed(1)}h (within ${commitment}h)`, color: "#f59e0b" };
  return { label: `${actual.toFixed(1)}h (EXCEEDS ${commitment}h)`, color: "#ef4444" };
}

function formatMoney(value: number | null): string {
  if (value === null) return "N/A — configure contract pricing";
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function growthChip(pct: number | null): React.ReactElement {
  if (pct === null) return <span style={{ color: "#94a3b8" }}>—</span>;
  const up = pct > 0;
  const color = up ? "#22c55e" : pct < -5 ? "#ef4444" : "#94a3b8";
  return (
    <span style={{ color, fontWeight: 600, fontSize: "0.82rem" }}>
      {up ? "▲" : "▼"} {Math.abs(pct).toFixed(1)}% MoM
    </span>
  );
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
      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem" }}>
        {segments.map((s) => (
          <span
            key={s.label}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              fontSize: "0.82rem",
              color: "var(--color-text-primary, #1f2937)",
              background: "var(--pf9-card-bg, #1e293b)",
              border: "1px solid var(--color-border, #334155)",
              borderRadius: "999px",
              padding: "0.2rem 0.55rem",
              fontWeight: 600,
            }}
          >
            <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: s.color }} />
            <span>{s.label}: {s.count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/** Horizontal bar showing used vs limit for a quota resource */
function QuotaBar({ label, resource }: { label: string; resource: QuotaResource | undefined }) {
  if (!resource || resource.limit == null) {
    return (
      <div style={{ flex: "1 1 180px" }}>
        <div style={{ fontSize: "0.78rem", color: "#94a3b8", marginBottom: "4px" }}>{label}</div>
        <div style={{ fontSize: "0.85rem", color: "#475569" }}>No quota data</div>
      </div>
    );
  }
  const pct = resource.utilization_pct ?? 0;
  const capped = Math.min(pct, 100);
  const barColor = pct >= 90 ? "#ef4444" : pct >= 75 ? "#f59e0b" : "#22c55e";
  return (
    <div style={{ flex: "1 1 180px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem", color: "#94a3b8", marginBottom: "4px" }}>
        <span>{label}</span>
        <span style={{ color: barColor, fontWeight: 600 }}>{pct}%</span>
      </div>
      <div style={{ height: "10px", background: "#334155", borderRadius: "4px", overflow: "hidden" }}>
        <div style={{ width: `${capped}%`, height: "100%", background: barColor, borderRadius: "4px" }} />
      </div>
      <div style={{ fontSize: "0.72rem", color: "#64748b", marginTop: "3px" }}>
        {(resource.used ?? 0).toLocaleString()} / {resource.limit.toLocaleString()} used
      </div>
    </div>
  );
}

/** Mini SVG sparkline for a numeric trend series */
function Sparkline({ values, color = "#60a5fa", height = 40 }: { values: number[]; color?: string; height?: number }) {
  if (values.length < 2) return null;
  const w = 200;
  const h = height;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const xs = values.map((_, i) => (i / (values.length - 1)) * w);
  const ys = values.map((v) => h - ((v - min) / range) * (h - 4) - 2);
  const d = xs.map((x, i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${ys[i].toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block" }}>
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={xs[xs.length - 1]} cy={ys[ys.length - 1]} r="3" fill={color} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Period selector config
// ---------------------------------------------------------------------------
type Period = "7d" | "30d" | "3m" | "6m" | "12m";
const PERIOD_OPTIONS: { key: Period; label: string; days?: number; months?: number }[] = [
  { key: "7d",  label: "7 days",    days: 7 },
  { key: "30d", label: "30 days",   days: 30 },
  { key: "3m",  label: "3 months",  months: 3 },
  { key: "6m",  label: "6 months",  months: 6 },
  { key: "12m", label: "12 months", months: 12 },
];

export default function ExecutiveDashboard({ userRole: _userRole }: Props) {
  const [data, setData]         = useState<ExecutiveSummaryResponse | null>(null);
  const [metering, setMetering] = useState<FleetMeteringResponse | null>(null);
  const [insights, setInsights] = useState<ExecutiveInsightsResponse | null>(null);
  const [slaDefense, setSlaDefense] = useState<SlaDefenseSummaryResponse | null>(null);
  const [slaDefenseAlerts, setSlaDefenseAlerts] = useState<SlaDefenseAlertItem[]>([]);
  const [actionBusyId, setActionBusyId] = useState<number | null>(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [period, setPeriod]     = useState<Period>("6m");
  const [selectedDomain, setSelectedDomain] = useState("");
  const [selectedSalesPerson, setSelectedSalesPerson] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const pd = PERIOD_OPTIONS.find((x) => x.key === period)!;
      const params = new URLSearchParams();
      if (pd.days)   params.set("days",   String(pd.days));
      else           params.set("months", String(pd.months));

      const insightParams = new URLSearchParams();
      insightParams.set("top_n", "10");
      if (selectedDomain) insightParams.set("domain", selectedDomain);
      if (selectedSalesPerson) insightParams.set("sales_person", selectedSalesPerson);

      const [summaryResp, meteringResp, insightsResp, slaDefenseResp, slaDefenseAlertsResp] = await Promise.all([
        apiFetch<ExecutiveSummaryResponse>("/api/sla/portfolio/executive-summary"),
        apiFetch<FleetMeteringResponse>(`/api/sla/portfolio/fleet-metering?${params}`),
        apiFetch<ExecutiveInsightsResponse>(`/api/sla/portfolio/executive-insights?${insightParams}`),
        apiFetch<SlaDefenseSummaryResponse>("/api/admin/sla/defense/alerts/summary"),
        apiFetch<SlaDefenseAlertsResponse>("/api/admin/sla/defense/alerts?status=open&limit=8"),
      ]);
      setData(summaryResp);
      setMetering(meteringResp);
      setInsights(insightsResp);
      setSlaDefense(slaDefenseResp);
      setSlaDefenseAlerts(slaDefenseAlertsResp.items ?? []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load executive summary");
    } finally {
      setLoading(false);
    }
  }, [period, selectedDomain, selectedSalesPerson]);

  const handleSlaDefenseAction = useCallback(async (alertId: number, action: "resolve" | "dismiss") => {
    setActionBusyId(alertId);
    try {
      await apiFetch(`/api/admin/sla/defense/alerts/${alertId}/${action}`, {
        method: "POST",
        body: JSON.stringify({ note: `${action}d from Portfolio Health dashboard` }),
      });
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `Failed to ${action} alert`);
    } finally {
      setActionBusyId(null);
    }
  }, [load]);

  useEffect(() => { load(); }, [load]);

  const s    = data?.summary;
  const m    = metering;
  const ei   = insights;
  const mttr = s ? mttrStatus(s.avg_mttr_hours, s.avg_mttr_commitment_hours) : null;

  const trendLabels = m?.monthly_trend.map((t) => t.month.slice(0, 7)) ?? [];
  const vcpuTrend   = m?.monthly_trend.map((t) => t.total_avg_vcpus ?? 0) ?? [];
  const costTrend   = m?.monthly_trend.map((t) => t.total_cost ?? 0) ?? [];
  const vmTrend     = m?.monthly_trend.map((t) => t.total_vms ?? 0) ?? [];

  // For multi-month periods (3m/6m/12m) derive aggregated fleet KPIs from trend data
  const isMultiMonth = ["3m", "6m", "12m"].includes(period);
  const periodFleetTotals = useMemo((): FleetTotals | null => {
    if (!m) return null;
    if (!isMultiMonth || m.monthly_trend.length === 0) return m.fleet_totals;
    const trend = m.monthly_trend;
    const count = trend.length;
    return {
      ...m.fleet_totals,
      avg_vcpus:  count > 0 ? Math.round(trend.reduce((s, t) => s + (t.total_avg_vcpus ?? 0), 0) / count * 10) / 10 : null,
      avg_ram_gb: count > 0 ? Math.round(trend.reduce((s, t) => s + (t.total_avg_ram_gb ?? 0), 0) / count * 10) / 10 : null,
      avg_disk_gb: count > 0 ? Math.round(trend.reduce((s, t) => s + (t.total_avg_disk_gb ?? 0), 0) / count * 10) / 10 : null,
      cost_this_month: trend.reduce((s, t) => s + (t.total_cost ?? 0), 0),
      vm_count: Math.max(...trend.map((t) => t.total_vms ?? 0)),
    };
  }, [m, isMultiMonth]);

  const ft = periodFleetTotals ?? m?.fleet_totals ?? null;

  const hasMeteringData = ft !== null && (ft.avg_vcpus != null || ft.cost_this_month != null);

  const periodLabel = PERIOD_OPTIONS.find((x) => x.key === period)?.label ?? period;
  const costKpiLabel = isMultiMonth
    ? `Total Fleet Cost (${periodLabel})`
    : `Fleet Cost (${periodLabel})`;

  return (
    <div className="pf9-intelligence-view">
      <div className="pf9-section-header">
        <h2>📊 Portfolio Health</h2>
        {data && (
          <span className="pf9-muted" style={{ fontSize: "0.85rem" }}>
            {data.month}
          </span>
        )}
        <div style={{ display: "flex", gap: "0.3rem", marginLeft: "0.75rem" }}>
          {PERIOD_OPTIONS.map((pd) => (
            <button
              key={pd.key}
              onClick={() => setPeriod(pd.key)}
              style={{
                background: period === pd.key ? "#3b82f6" : "var(--pf9-card-bg, #1e293b)",
                border: `1px solid ${period === pd.key ? "#3b82f6" : "#334155"}`,
                borderRadius: "6px",
                color: period === pd.key ? "#fff" : "#94a3b8",
                padding: "0.25rem 0.55rem",
                fontSize: "0.78rem",
                cursor: "pointer",
                fontWeight: period === pd.key ? 600 : 400,
              }}
            >
              {pd.label}
            </button>
          ))}
        </div>
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
          {/* ----------------------------------------------------------------
              SLA Fleet Health
          ---------------------------------------------------------------- */}
          <section style={{ marginBottom: "1.5rem" }}>
            <h3 style={{ fontSize: "0.95rem", color: "#94a3b8", marginBottom: "0.6rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              SLA Fleet Health
            </h3>
            <SlaDonut summary={s} />
          </section>

          {/* KPI grid — SLA */}
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
              label="SLA Defense Alerts"
              value={slaDefense?.total_open ?? 0}
              accent={(slaDefense?.open.critical ?? 0) > 0 ? "#ef4444" : (slaDefense?.open.warning ?? 0) > 0 ? "#f59e0b" : "#22c55e"}
              sub={`${slaDefense?.open.critical ?? 0} critical · ${slaDefense?.open.warning ?? 0} warning`}
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

          {/* ----------------------------------------------------------------
              Metering Summary
          ---------------------------------------------------------------- */}
          <section style={{ marginBottom: "1.5rem" }}>
            <h3 style={{ fontSize: "0.95rem", color: "#94a3b8", marginBottom: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              📡 Metering Summary — Last {periodLabel}
            </h3>
            {!hasMeteringData ? (
              <div style={{ color: "#475569", fontSize: "0.88rem", padding: "0.75rem 1rem", background: "var(--pf9-card-bg, #1e293b)", borderRadius: "8px" }}>
                No metering data collected yet. The metering worker populates this section monthly.
              </div>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.8rem" }}>
                <KpiCard
                  label="Avg vCPUs Allocated"
                  value={ft!.avg_vcpus != null ? ft!.avg_vcpus.toLocaleString() : "—"}
                  accent="#60a5fa"
                  sub={undefined}
                />
                <KpiCard
                  label="Avg RAM Allocated"
                  value={ft!.avg_ram_gb != null ? `${ft!.avg_ram_gb.toLocaleString()} GB` : "—"}
                  accent="#a78bfa"
                  sub="Across all tenants"
                />
                <KpiCard
                  label="Avg Disk Allocated"
                  value={ft!.avg_disk_gb != null ? `${ft!.avg_disk_gb.toLocaleString()} GB` : "—"}
                  accent="#34d399"
                  sub="Across all tenants"
                />
                <KpiCard
                  label="Metered VMs"
                  value={ft!.vm_count.toLocaleString()}
                  accent="#fb923c"
                  sub="Distinct VMs this period"
                />
                <KpiCard
                  label={costKpiLabel}
                  value={
                    ft!.cost_this_month != null
                      ? `${ft!.currency} ${ft!.cost_this_month.toLocaleString("en-US", { maximumFractionDigits: 0 })}`
                      : "—"
                  }
                  accent="#f59e0b"
                  sub={ft!.is_partial_month ? "Accrued so far this month" : undefined}
                />
              </div>
            )}
            {/* MoM growth chips — only when API provides them (monthly mode, non-null) */}
            {hasMeteringData && (m!.fleet_totals.vcpu_growth_pct !== null || m!.fleet_totals.cost_growth_pct !== null) && (
              <div style={{ display: "flex", gap: "1rem", marginTop: "0.6rem", flexWrap: "wrap" }}>
                {m!.fleet_totals.vcpu_growth_pct !== null && (
                  <span style={{ fontSize: "0.8rem", color: "#64748b" }}>
                    vCPU growth: {growthChip(m!.fleet_totals.vcpu_growth_pct)}
                  </span>
                )}
                {m!.fleet_totals.cost_growth_pct !== null && (
                  <span style={{ fontSize: "0.8rem", color: "#64748b" }}>
                    Cost growth: {growthChip(m!.fleet_totals.cost_growth_pct)}
                    {m!.fleet_totals.is_partial_month && (
                      <span style={{ color: "#94a3b8", fontSize: "0.72rem", marginLeft: "0.3rem" }}>(projected full month)</span>
                    )}
                  </span>
                )}
              </div>
            )}
          </section>

          {/* ----------------------------------------------------------------
              Quota Health Fleet Total
          ---------------------------------------------------------------- */}
          {m && Object.keys(m.quota_health).length > 0 && (
            <section style={{ marginBottom: "1.5rem" }}>
              <h3 style={{ fontSize: "0.95rem", color: "#94a3b8", marginBottom: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                📊 Quota Utilisation — Fleet Total
              </h3>
              <div style={{ background: "var(--pf9-card-bg, #1e293b)", borderRadius: "8px", padding: "1rem 1.2rem" }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "1.5rem" }}>
                  <QuotaBar label="vCPU Cores"  resource={m.quota_health["cores"]}      />
                  <QuotaBar label="RAM"          resource={m.quota_health["ram"]}        />
                  <QuotaBar label="Storage (GB)" resource={m.quota_health["storage_gb"]} />
                </div>
              </div>
            </section>
          )}

          {/* ----------------------------------------------------------------
              6-Month Resource Trend sparklines
          ---------------------------------------------------------------- */}
          {m && m.monthly_trend.length >= 2 && (
            <section style={{ marginBottom: "1.5rem" }}>
              <h3 style={{ fontSize: "0.95rem", color: "#94a3b8", marginBottom: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                📈 {periodLabel.charAt(0).toUpperCase() + periodLabel.slice(1)} Fleet Trend
              </h3>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
                {([
                  { label: "vCPUs", values: vcpuTrend, color: "#60a5fa" },
                  { label: "Cost",  values: costTrend, color: "#f59e0b" },
                  { label: "VMs",   values: vmTrend,   color: "#34d399" },
                ] as const).map(({ label, values, color }) => (
                  <div
                    key={label}
                    style={{ background: "var(--pf9-card-bg, #1e293b)", borderRadius: "8px", padding: "0.8rem 1rem", flex: "1 1 200px" }}
                  >
                    <div style={{ fontSize: "0.8rem", color: "#94a3b8", marginBottom: "6px" }}>{label}</div>
                    <Sparkline values={[...values]} color={color} />
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.7rem", color: "#475569", marginTop: "4px" }}>
                      <span>{trendLabels[0]}</span>
                      <span>{trendLabels[trendLabels.length - 1]}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ----------------------------------------------------------------
              Top Growing Tenants
          ---------------------------------------------------------------- */}
          {m && m.top_growing_tenants.length > 0 && (
            <section style={{ marginBottom: "1.5rem" }}>
              <h3 style={{ fontSize: "0.95rem", color: "#94a3b8", marginBottom: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                🚀 Fastest-Growing Tenants (vCPU, MoM)
              </h3>
              <div style={{ overflowX: "auto" }}>
                <table className="pf9-table">
                  <thead>
                    <tr>
                      <th>Client</th>
                      <th style={{ textAlign: "right" }}>vCPUs (prev)</th>
                      <th style={{ textAlign: "right" }}>vCPUs (curr)</th>
                      <th style={{ textAlign: "right" }}>vCPU Growth</th>
                      <th style={{ textAlign: "right" }}>Cost (curr)</th>
                      <th style={{ textAlign: "right" }}>Cost Growth</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.top_growing_tenants.map((t) => (
                      <tr key={t.tenant_name}>
                        <td style={{ fontWeight: 500 }}>{t.tenant_name}</td>
                        <td style={{ textAlign: "right" }}>{t.vcpus_prev_month?.toLocaleString() ?? "—"}</td>
                        <td style={{ textAlign: "right" }}>{t.vcpus_this_month?.toLocaleString() ?? "—"}</td>
                        <td style={{ textAlign: "right" }}>{growthChip(t.vcpu_growth_pct)}</td>
                        <td style={{ textAlign: "right" }}>
                          {t.cost_this_month != null
                            ? `${t.currency ?? m!.fleet_totals.currency} ${t.cost_this_month.toLocaleString("en-US", { maximumFractionDigits: 0 })}`
                            : "—"}
                        </td>
                        <td style={{ textAlign: "right" }}>{growthChip(t.cost_growth_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* ----------------------------------------------------------------
              Executive Insights: Churn / New / Sales / Order Progress
          ---------------------------------------------------------------- */}
          {ei && (
            <section style={{ marginBottom: "1.5rem" }}>
              <h3 style={{ fontSize: "0.95rem", color: "#94a3b8", marginBottom: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                📌 Executive Insights — Trusted Data Paths
              </h3>

              <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", marginBottom: "0.85rem" }}>
                <select
                  value={selectedDomain}
                  onChange={(e) => setSelectedDomain(e.target.value)}
                  style={{
                    background: "var(--pf9-card-bg, #1e293b)",
                    border: "1px solid #334155",
                    borderRadius: "6px",
                    color: "#e2e8f0",
                    padding: "0.35rem 0.55rem",
                    fontSize: "0.82rem",
                  }}
                >
                  <option value="">All orgs</option>
                  {(ei.filters.available_domains || []).map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>

                <select
                  value={selectedSalesPerson}
                  onChange={(e) => setSelectedSalesPerson(e.target.value)}
                  style={{
                    background: "var(--pf9-card-bg, #1e293b)",
                    border: "1px solid #334155",
                    borderRadius: "6px",
                    color: "#e2e8f0",
                    padding: "0.35rem 0.55rem",
                    fontSize: "0.82rem",
                  }}
                >
                  <option value="">All sales owners</option>
                  {(ei.filters.available_sales_people || []).map((sp) => (
                    <option key={sp} value={sp}>{sp}</option>
                  ))}
                </select>

                {(selectedDomain || selectedSalesPerson) && (
                  <button
                    className="pf9-btn pf9-btn-sm"
                    onClick={() => {
                      setSelectedDomain("");
                      setSelectedSalesPerson("");
                    }}
                  >
                    Clear Filters
                  </button>
                )}
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.8rem", marginBottom: "1rem" }}>
                <KpiCard label="Active Tenants" value={ei.summary.active_tenants} accent="#22c55e" sub={`of ${ei.summary.total_tenants} total`} />
                <KpiCard label="Churned (Top Set)" value={ei.summary.top_churned_count} accent={ei.summary.top_churned_count > 0 ? "#ef4444" : "#22c55e"} sub={`vs ${ei.previous_month}`} />
                <KpiCard label="New Connections" value={ei.summary.top_new_count} accent={ei.summary.top_new_count > 0 ? "#38bdf8" : "#94a3b8"} sub={`in ${ei.month}`} />
              </div>

              <div style={{ display: "grid", gap: "1rem", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
                <div style={{ background: "var(--pf9-card-bg, #1e293b)", borderRadius: "8px", padding: "0.85rem" }}>
                  <div style={{ fontSize: "0.84rem", color: "#94a3b8", marginBottom: "0.55rem", fontWeight: 600 }}>Top 10 Churned Tenants</div>
                  <div style={{ overflowX: "auto", maxHeight: 260 }}>
                    <table className="pf9-table" style={{ marginBottom: 0 }}>
                      <thead>
                        <tr>
                          <th>Tenant</th>
                          <th style={{ textAlign: "right" }}>Prev VMs</th>
                          <th>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ei.top_churned.length === 0 ? (
                          <tr><td colSpan={3} style={{ color: "#94a3b8" }}>No churn detected in selected slice.</td></tr>
                        ) : ei.top_churned.map((r) => (
                          <tr key={r.tenant_id}>
                            <td>{r.tenant_name}</td>
                            <td style={{ textAlign: "right" }}>{r.prev_vms}</td>
                            <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.churn_reason || ""}>
                              {r.churn_reason || "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div style={{ background: "var(--pf9-card-bg, #1e293b)", borderRadius: "8px", padding: "0.85rem" }}>
                  <div style={{ fontSize: "0.84rem", color: "#94a3b8", marginBottom: "0.55rem", fontWeight: 600 }}>Top 10 New Connections</div>
                  <div style={{ overflowX: "auto", maxHeight: 260 }}>
                    <table className="pf9-table" style={{ marginBottom: 0 }}>
                      <thead>
                        <tr>
                          <th>Tenant</th>
                          <th style={{ textAlign: "right" }}>Current VMs</th>
                          <th>Sales</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ei.top_new_connections.length === 0 ? (
                          <tr><td colSpan={3} style={{ color: "#94a3b8" }}>No new connections in selected slice.</td></tr>
                        ) : ei.top_new_connections.map((r) => (
                          <tr key={r.tenant_id}>
                            <td>{r.tenant_name}</td>
                            <td style={{ textAlign: "right" }}>{r.cur_vms}</td>
                            <td>{r.sales_person_id || "Unassigned"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div style={{ background: "var(--pf9-card-bg, #1e293b)", borderRadius: "8px", padding: "0.85rem" }}>
                  <div style={{ fontSize: "0.84rem", color: "#94a3b8", marginBottom: "0.55rem", fontWeight: 600 }}>Sales Owner Analysis</div>
                  <div style={{ overflowX: "auto", maxHeight: 260 }}>
                    <table className="pf9-table" style={{ marginBottom: 0 }}>
                      <thead>
                        <tr>
                          <th>Sales Owner</th>
                          <th style={{ textAlign: "right" }}>Tenants</th>
                          <th style={{ textAlign: "right" }}>New</th>
                          <th style={{ textAlign: "right" }}>Churn</th>
                        </tr>
                      </thead>
                      <tbody>
                        {ei.sales_person_analysis.length === 0 ? (
                          <tr><td colSpan={4} style={{ color: "#94a3b8" }}>No sales ownership data.</td></tr>
                        ) : ei.sales_person_analysis.map((r) => (
                          <tr key={r.sales_person_id}>
                            <td>{r.sales_person_id}</td>
                            <td style={{ textAlign: "right" }}>{r.tenant_count}</td>
                            <td style={{ textAlign: "right", color: "#38bdf8", fontWeight: 600 }}>{r.new_count}</td>
                            <td style={{ textAlign: "right", color: r.churned_count > 0 ? "#ef4444" : "#94a3b8", fontWeight: 600 }}>{r.churned_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div style={{ background: "var(--pf9-card-bg, #1e293b)", borderRadius: "8px", padding: "0.85rem" }}>
                  <div style={{ fontSize: "0.84rem", color: "#94a3b8", marginBottom: "0.55rem", fontWeight: 600 }}>
                    Alternate Lens: CloudAll / InternetAll / Order Progress
                  </div>
                  <div style={{ display: "grid", gap: "0.45rem" }}>
                    {ei.order_progress.length === 0 ? (
                      <div style={{ color: "#94a3b8", fontSize: "0.82rem" }}>No lifecycle events in the last 30 days.</div>
                    ) : ei.order_progress.map((row) => {
                      const max = Math.max(...ei.order_progress.map((x) => x.event_count), 1);
                      const width = `${Math.round((row.event_count / max) * 100)}%`;
                      return (
                        <div key={row.stage}>
                          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem", marginBottom: "2px" }}>
                            <span>{row.stage}</span>
                            <span>{row.event_count} events · {row.tenant_count} tenants</span>
                          </div>
                          <div style={{ height: "8px", background: "#334155", borderRadius: "4px", overflow: "hidden" }}>
                            <div style={{ width, height: "100%", background: row.stage === "churned" ? "#ef4444" : row.stage === "completed" ? "#22c55e" : "#38bdf8" }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {ei.churn_reasons.length > 0 && (
                <div style={{ marginTop: "0.75rem", fontSize: "0.8rem", color: "#94a3b8" }}>
                  Top churn reasons: {ei.churn_reasons.slice(0, 5).map((r) => `${r.reason} (${r.count})`).join(" · ")}
                </div>
              )}
            </section>
          )}

          {/* ----------------------------------------------------------------
              Revenue leakage detail
          ---------------------------------------------------------------- */}
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

          {slaDefense && slaDefense.total_open > 0 && (
            <section
              style={{
                background: "var(--pf9-card-bg, #1e293b)",
                borderRadius: "8px",
                padding: "1rem 1.2rem",
                borderLeft: `4px solid ${(slaDefense.open.critical ?? 0) > 0 ? "#ef4444" : "#f59e0b"}`,
                marginBottom: "1rem",
              }}
            >
              <h3 style={{ margin: "0 0 0.4rem", fontSize: "0.95rem" }}>🛡️ SLA Defense</h3>
              <p style={{ margin: 0, fontSize: "0.88rem", color: "#cbd5e1" }}>
                <strong>{slaDefense.total_open}</strong> proactive SLA defense alert{slaDefense.total_open !== 1 ? "s" : ""} open across the fleet.
                {" "}<strong style={{ color: "#ef4444" }}>{slaDefense.open.critical}</strong> critical and
                {" "}<strong style={{ color: "#f59e0b" }}>{slaDefense.open.warning}</strong> warning.
              </p>
            </section>
          )}

          {slaDefense && slaDefense.total_open === 0 && (
            <section
              style={{
                background: "var(--pf9-card-bg, #1e293b)",
                borderRadius: "8px",
                padding: "0.75rem 1.2rem",
                borderLeft: "4px solid #22c55e",
                marginBottom: "1rem",
              }}
            >
              <p style={{ margin: 0, fontSize: "0.88rem", color: "#cbd5e1" }}>
                🛡️ SLA Defense is active: no open proactive alerts right now.
              </p>
            </section>
          )}

          <section
            style={{
              background: "var(--pf9-card-bg, #1e293b)",
              borderRadius: "8px",
              padding: "0.9rem 1rem",
              marginBottom: "1rem",
            }}
          >
            <h3 style={{ margin: "0 0 0.6rem", fontSize: "0.95rem" }}>🛡️ SLA Defense Open Alerts</h3>
            {slaDefenseAlerts.length === 0 ? (
              <div style={{ fontSize: "0.84rem", color: "#94a3b8" }}>No open proactive SLA defense alerts.</div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="pf9-table" style={{ marginBottom: 0 }}>
                  <thead>
                    <tr>
                      <th>Project</th>
                      <th>Threat</th>
                      <th>Severity</th>
                      <th>Triggered</th>
                      <th style={{ textAlign: "right" }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {slaDefenseAlerts.map((a) => (
                      <tr key={a.id}>
                        <td>{a.project_name ?? a.project_id}</td>
                        <td>{a.threat_type}</td>
                        <td>
                          <span className={`pf9-badge ${a.severity === "critical" ? "badge-critical" : "badge-warning"}`}>
                            {a.severity}
                          </span>
                        </td>
                        <td>{a.triggered_at?.replace("T", " ").slice(0, 16) ?? "—"}</td>
                        <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          <button
                            className="pf9-btn pf9-btn-sm"
                            onClick={() => handleSlaDefenseAction(a.id, "resolve")}
                            disabled={actionBusyId === a.id}
                            style={{ marginRight: "0.35rem" }}
                          >
                            Resolve
                          </button>
                          <button
                            className="pf9-btn pf9-btn-sm"
                            onClick={() => handleSlaDefenseAction(a.id, "dismiss")}
                            disabled={actionBusyId === a.id}
                          >
                            Dismiss
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

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
