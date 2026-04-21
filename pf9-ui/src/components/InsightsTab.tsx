/*
 * InsightsTab.tsx  —  Operational Intelligence + SLA feed
 * =========================================================
 * Views:
 *   1. Insights Feed — filterable list of active insights with ack/snooze/resolve actions
 *   2. Risk & Capacity — pivot table: risk insights by project, capacity forecast by tenant
 *   3. SLA Summary    — portfolio-wide SLA compliance at a glance
 *
 * v1.85.0
 */
import React, { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../lib/api";
import "../styles/InsightsTab.css";
import IntelligenceSettingsPanel from "./IntelligenceSettingsPanel";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Insight {
  id: number;
  type: string;
  severity: string;
  entity_type: string;
  entity_id: string;
  entity_name?: string;
  title: string;
  message: string;
  metadata: Record<string, unknown>;
  status: string;
  acknowledged_by?: string;
  acknowledged_at?: string;
  snooze_until?: string;
  resolved_at?: string;
  detected_at: string;
  last_seen_at: string;
}

interface InsightSummary {
  by_severity: { critical: number; high: number; medium: number; low: number };
  by_type: { type: string; count: number }[];
  total_open: number;
}

interface SlaSummaryRow {
  tenant_id: string;
  tenant_name: string;
  tier?: string;
  breach_fields: string[];
  at_risk_fields: string[];
  overall_status: string;
}

interface SlaTierTemplate {
  tier: string;          // PK: bronze | silver | gold | custom
  display_name: string;  // e.g. "Gold"
  uptime_pct: number | null;
  rto_hours: number | null;
  rpo_hours: number | null;
  mtta_hours: number | null;
  mttr_hours: number | null;
  backup_freq_hours: number | null;
}

interface TenantOption {
  id: string;
  name: string;
}

interface Recommendation {
  id: number;
  action_type: string;
  action_payload: Record<string, unknown>;
  estimated_impact?: string;
  status: string;
}

interface ForecastResource {
  used: number;
  quota: number;
  used_pct: number | null;
  days_to_90: number | null;
  trend_per_day: number;
  confidence: number;
}

interface ProjectForecast {
  project_id: string;
  project_name: string;
  resources: Record<string, ForecastResource>;
}

interface RegionRow {
  region_id: string;
  hypervisors: number;
  total_vcpus: number;
  allocated_vcpus: number;
  vcpu_utilization: number;
  total_ram_mb: number;
  allocated_ram_mb: number;
  ram_utilization: number;
  running_vms: number;
  open_critical: number;
  open_high: number;
  capacity_runway_days: number | null;
  growth_rate_pct: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TYPE_ICONS: Record<string, string> = {
  capacity_storage:          "💾",
  capacity_compute:          "🖧",
  capacity_quota_vcpu:       "⚡",
  capacity_quota_ram:        "🧠",
  capacity_quota_instances:  "📦",
  capacity_quota_floating_ip: "🌐",
  waste_idle_vm:             "🖥️",
  waste_unattached_volume:   "📦",
  waste_old_snapshots:       "📸",
  risk_snapshot_gap:         "⚠️",
  risk_health_decline:       "📉",
  risk_unack_drift:          "🔀",
  sla_risk:                  "📋",
  cross_region_imbalance:    "⚖️",
  cross_region_concentration: "🎯",
  cross_region_growth:       "📈",
  anomaly_snapshot_spike:    "🚨",
  anomaly_vm_spike:          "🔺",
  anomaly_api_errors:        "🔴",
  leakage_overconsumption:   "📈",
  leakage_ghost:             "👻",
};

function typeIcon(type: string): string {
  return TYPE_ICONS[type] ?? "🔔";
}

function fmtTs(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function sevClass(sev: string): string {
  return `sev-badge sev-${sev}`;
}

function statusClass(s: string): string {
  return `status-badge status-${s}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface InsightsTabProps {
  userRole?: string;
}

type InnerTab = "feed" | "risk" | "forecast" | "regions" | "sla" | "settings";

export default function InsightsTab({ userRole }: InsightsTabProps) {
  const [innerTab, setInnerTab] = useState<InnerTab>("feed");

  // Workspace (department) selector
  // Role-based defaults: operator → engineering, others → global
  const defaultWorkspace = userRole === "operator" ? "engineering" : "global";
  const [workspace, setWorkspace] = useState<string>(() =>
    localStorage.getItem("pf9_intelligence_workspace") || defaultWorkspace
  );

  // Feed state
  const [insights, setInsights]   = useState<Insight[]>([]);
  const [summary, setSummary]     = useState<InsightSummary | null>(null);
  const [total, setTotal]         = useState(0);
  const [page, setPage]           = useState(1);
  const PAGE_SIZE = 50;

  // Filters
  const [filterStatus,   setFilterStatus]   = useState("");
  const [filterSeverity, setFilterSeverity] = useState("");
  const [filterType,     setFilterType]     = useState("");
  const [sortBy,         setSortBy]         = useState("severity");

  // Risk table sort
  const [riskSort, setRiskSort] = useState<{col: string; dir: 1|-1}>({col: "severity", dir: 1});

  // Capacity Forecast sort
  const [fcSort, setFcSort] = useState<{col: string; dir: 1|-1}>({col: "runway", dir: 1});

  // SLA Summary
  const [slaSummary, setSlaSummary] = useState<SlaSummaryRow[]>([]);
  const [slaLoading, setSlaLoading] = useState(false);
  const [slaLoadError, setSlaLoadError] = useState("");

  // SLA assign modal
  const [slaModalOpen, setSlaModalOpen] = useState(false);
  const [slaTiers, setSlaTiers] = useState<SlaTierTemplate[]>([]);
  const [slaTenants, setSlaTenants] = useState<TenantOption[]>([]);
  const [slaPickTenant, setSlaPickTenant] = useState("");
  const [slaPickTier, setSlaPickTier] = useState("bronze");
  const [slaSaving, setSlaSaving] = useState(false);
  const [slaError, setSlaError] = useState("");

  // Recommendations
  const [expandedRecs, setExpandedRecs] = useState<Record<number, Recommendation[]>>({});
  const [loadingRecs, setLoadingRecs] = useState<Record<number, boolean>>({});

  // Capacity Forecast
  const [forecasts, setForecasts] = useState<ProjectForecast[]>([]);
  const [forecastLoading, setForecastLoading] = useState(false);

  // Region Comparison
  const [regions, setRegions] = useState<RegionRow[]>([]);
  const [regionsLoading, setRegionsLoading] = useState(false);

  // Snooze modal
  const [snoozeTarget, setSnoozeTarget] = useState<number | null>(null);
  const [snoozeUntil,  setSnoozeUntil]  = useState("");

  const canWrite = userRole === "admin" || userRole === "superadmin";

  // Workspace preset severity filters (type filtering is handled server-side via ?department=)
  function applyWorkspacePresets(ws: string) {
    switch (ws) {
      case "support":     setFilterSeverity("high");   setFilterStatus(""); setFilterType(""); break;
      case "engineering": setFilterSeverity("medium"); setFilterStatus(""); setFilterType(""); break;
      case "operations":  setFilterSeverity("medium"); setFilterStatus(""); setFilterType(""); break;
      default:            setFilterSeverity("");        setFilterStatus(""); setFilterType(""); break;
    }
  }

  function changeWorkspace(ws: string) {
    localStorage.setItem("pf9_intelligence_workspace", ws);
    setWorkspace(ws);
    applyWorkspacePresets(ws);
  }

  // ------- Fetch insights + summary -------

  const loadInsights = useCallback(async (p: number = 1) => {
    const params = new URLSearchParams({ page: String(p), page_size: String(PAGE_SIZE), sort_by: sortBy });
    if (filterStatus)                        params.set("status",     filterStatus);
    if (filterSeverity)                      params.set("severity",   filterSeverity);
    if (filterType)                          params.set("type",       filterType);
    if (workspace && workspace !== "global") params.set("department", workspace);
    const data = await apiFetch<{ insights: Insight[]; total: number }>(
      `/api/intelligence/insights?${params}`
    );
    setInsights(data.insights);
    setTotal(data.total);
    setPage(p);
  }, [filterStatus, filterSeverity, filterType, workspace]);

  const loadSummary = useCallback(async () => {
    const qs = workspace && workspace !== "global" ? `?department=${workspace}` : "";
    const data = await apiFetch<InsightSummary>(`/api/intelligence/insights/summary${qs}`);
    setSummary(data);
  }, [workspace]);

  const loadSlaSummary = useCallback(async () => {
    setSlaLoading(true);
    setSlaLoadError("");
    try {
      const data = await apiFetch<{ summary: SlaSummaryRow[]; month: string }>("/api/sla/compliance/summary");
      setSlaSummary(data.summary ?? []);
    } catch (e: unknown) {
      setSlaLoadError(e instanceof Error ? e.message : "Failed to load SLA summary.");
    } finally {
      setSlaLoading(false);
    }
  }, []);

  const loadForecast = useCallback(async () => {
    setForecastLoading(true);
    try {
      const data = await apiFetch<{ forecasts: ProjectForecast[] }>("/api/intelligence/forecast");
      setForecasts(data.forecasts ?? []);
    } catch (e) {
      setForecasts([]);
    } finally {
      setForecastLoading(false);
    }
  }, []);

  const loadRegions = useCallback(async () => {
    setRegionsLoading(true);
    try {
      const data = await apiFetch<{ regions: RegionRow[] }>("/api/intelligence/regions");
      setRegions(data.regions ?? []);
    } catch (e) {
      setRegions([]);
    } finally {
      setRegionsLoading(false);
    }
  }, []);

  useEffect(() => { loadInsights(1); }, [filterStatus, filterSeverity, filterType, workspace, sortBy]);
  useEffect(() => { loadSummary(); }, [workspace]);
  useEffect(() => { if (innerTab === "sla") loadSlaSummary(); }, [innerTab]);
  useEffect(() => { if (innerTab === "forecast") loadForecast(); }, [innerTab]);
  useEffect(() => { if (innerTab === "regions") loadRegions(); }, [innerTab]);

  async function openSlaModal() {
    setSlaError("");
    setSlaPickTenant("");
    setSlaPickTier("bronze");
    setSlaModalOpen(true);
    const [tiersData, tenantsData] = await Promise.all([
      apiFetch<{ tiers: SlaTierTemplate[] }>("/api/sla/tiers"),
      apiFetch<{ data: TenantOption[] }>("/api/resources/context/projects"),
    ]);
    setSlaTiers(tiersData.tiers ?? []);
    setSlaTenants(tenantsData.data ?? []);
  }

  async function saveSlaCommitment() {
    if (!slaPickTenant) { setSlaError("Please select a tenant."); return; }
    setSlaSaving(true);
    setSlaError("");
    try {
      await apiFetch(`/api/sla/commitments/${slaPickTenant}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier: slaPickTier }),
      });
      setSlaModalOpen(false);
      loadSlaSummary();
    } catch (e: unknown) {
      setSlaError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSlaSaving(false);
    }
  }

  // ------- Lifecycle actions -------

  async function doAcknowledge(id: number) {
    await apiFetch(`/api/intelligence/insights/${id}/acknowledge`, { method: "POST" });
    loadInsights(page);
    loadSummary();
  }

  async function doResolve(id: number) {
    await apiFetch(`/api/intelligence/insights/${id}/resolve`, { method: "POST" });
    loadInsights(page);
    loadSummary();
  }

  async function doSnooze() {
    if (!snoozeTarget || !snoozeUntil) return;
    await apiFetch(`/api/intelligence/insights/${snoozeTarget}/snooze`, {
      method: "POST",
      body: JSON.stringify({ snooze_until: snoozeUntil }),
    });
    setSnoozeTarget(null);
    setSnoozeUntil("");
    loadInsights(page);
    loadSummary();
  }

  // ------- Bulk actions -------

  async function doBulkAcknowledge(severity?: string) {
    const body: Record<string, string> = {};
    if (severity) body.severity = severity;
    const data = await apiFetch<{ acknowledged: number }>("/api/intelligence/insights/bulk-acknowledge", {
      method: "POST",
      body: JSON.stringify(body),
    });
    await loadInsights(1);
    await loadSummary();
    return data.acknowledged;
  }

  async function doBulkResolve(type?: string) {
    const body: Record<string, string> = {};
    if (type) body.type = type;
    const data = await apiFetch<{ resolved: number }>("/api/intelligence/insights/bulk-resolve", {
      method: "POST",
      body: JSON.stringify(body),
    });
    await loadInsights(1);
    await loadSummary();
    return data.resolved;
  }

  // ------- Recommendations -------

  async function toggleRecommendations(insightId: number) {
    if (expandedRecs[insightId] !== undefined) {
      setExpandedRecs((prev) => { const n = { ...prev }; delete n[insightId]; return n; });
      return;
    }
    setLoadingRecs((prev) => ({ ...prev, [insightId]: true }));
    try {
      const data = await apiFetch<{ recommendations: Recommendation[] }>(
        `/api/intelligence/insights/${insightId}/recommendations`
      );
      setExpandedRecs((prev) => ({ ...prev, [insightId]: data.recommendations ?? [] }));
    } finally {
      setLoadingRecs((prev) => ({ ...prev, [insightId]: false }));
    }
  }

  async function dismissRecommendation(insightId: number, recId: number) {
    await apiFetch(`/api/intelligence/insights/${insightId}/recommendations/${recId}/dismiss`, {
      method: "POST",
    });
    setExpandedRecs((prev) => ({
      ...prev,
      [insightId]: (prev[insightId] ?? []).map((r) =>
        r.id === recId ? { ...r, status: "dismissed" } : r
      ),
    }));
  }

  // ------- Render helpers -------

  function renderSummaryBar() {
    if (!summary) return null;
    const { by_severity, total_open } = summary;
    return (
      <div className="insights-summary-bar">
        {(["critical","high","medium","low"] as const).map((s) => (
          <span
            key={s}
            className={`sev-pill ${s}`}
            style={{ cursor: "pointer" }}
            onClick={() => setFilterSeverity(filterSeverity === s ? "" : s)}
          >
            {s}: {by_severity[s]}
          </span>
        ))}
        <span style={{ marginLeft: "auto", fontSize: "0.82rem", color: "var(--text-secondary,#6b7280)" }}>
          {total_open} active insight{total_open !== 1 ? "s" : ""}
        </span>
      </div>
    );
  }

  function renderFeed() {
    return (
      <>
        {renderSummaryBar()}
        <div className="insights-filters">
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="snoozed">Snoozed</option>
            <option value="resolved">Resolved</option>
          </select>
          <select value={filterSeverity} onChange={(e) => setFilterSeverity(e.target.value)}>
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select value={filterType} onChange={(e) => setFilterType(e.target.value)}>
            <option value="">All types</option>
            <optgroup label="Capacity">
              <option value="capacity_storage">Storage Capacity</option>
              <option value="capacity_compute">Compute Capacity</option>
              <option value="capacity_quota_vcpu">vCPU Quota</option>
              <option value="capacity_quota_ram">RAM Quota</option>
            </optgroup>
            <optgroup label="Waste">
              <option value="waste_idle_vm">Idle VM</option>
              <option value="waste_unattached_volume">Unattached Volume</option>
              <option value="waste_old_snapshots">Stale Snapshots</option>
            </optgroup>
            <optgroup label="Risk">
              <option value="risk_snapshot_gap">Snapshot Gap</option>
              <option value="risk_health_decline">Health Decline</option>
              <option value="risk_unack_drift">Unack Drift</option>
              <option value="sla_risk">SLA Risk</option>
            </optgroup>
            <optgroup label="Anomaly">
              <option value="anomaly_snapshot_spike">Snapshot Spike</option>
              <option value="anomaly_vm_spike">VM Count Spike</option>
              <option value="anomaly_api_errors">API Error Spike</option>
            </optgroup>
            <optgroup label="Cross-Region">
              <option value="cross_region_imbalance">Utilization Imbalance</option>
              <option value="cross_region_concentration">Risk Concentration</option>
              <option value="cross_region_growth">Growth Divergence</option>
            </optgroup>
            <optgroup label="Revenue Leakage">
              <option value="leakage_overconsumption">Over-Consumption</option>
              <option value="leakage_ghost">Ghost Resources</option>
            </optgroup>
          </select>
          {(filterStatus || filterSeverity || filterType) && (
            <button className="insights-filter-reset" onClick={() => {
              setFilterStatus(""); setFilterSeverity(""); setFilterType("");
            }}>
              Clear filters
            </button>
          )}
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            title="Sort insights by"
            style={{ marginLeft: "auto" }}
          >
            <option value="severity">Sort: Severity</option>
            <option value="detected_at">Sort: Newest first</option>
            <option value="last_seen">Sort: Last seen</option>
            <option value="type">Sort: Type</option>
            <option value="entity">Sort: Entity</option>
          </select>
          {canWrite && (
            <div className="insights-bulk-actions">
              <span style={{ fontSize: "0.78rem", color: "var(--text-secondary,#6b7280)", marginRight: "0.5rem" }}>
                Bulk:
              </span>
              <button className="btn-sm" title="Acknowledge all open medium insights"
                onClick={() => doBulkAcknowledge("medium")}>
                Ack medium
              </button>
              <button className="btn-sm" title="Resolve all idle-VM waste insights"
                onClick={() => doBulkResolve("waste_idle_vm")}>
                Resolve idle VMs
              </button>
              <button className="btn-sm" title="Resolve all waste insights (any type)"
                onClick={() => doBulkResolve(filterType || undefined)}>
                {filterType ? `Resolve all ${filterType.replace(/_/g," ")}` : "Resolve current type"}
              </button>
            </div>
          )}
        </div>

        <div className="insights-feed">
          {insights.length === 0 ? (
            <div className="insights-empty">
              <div className="insights-empty-icon">✅</div>
              <p className="insights-empty-text">No insights match your filters.</p>
            </div>
          ) : (
            <table className="insights-table">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Type</th>
                  <th>Entity</th>
                  <th>Tenant</th>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Detected</th>
                  {canWrite && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {insights.map((ins) => (
                  <React.Fragment key={ins.id}>
                  <tr>
                    <td><span className={sevClass(ins.severity)}>{ins.severity}</span></td>
                    <td>
                      <span className="type-icon">{typeIcon(ins.type)}</span>
                      <span style={{ fontSize: "0.78rem", color: "var(--text-secondary,#6b7280)" }}>
                        {ins.type.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>
                        {ins.entity_name || ins.entity_id}
                      </div>
                      <div style={{ fontSize: "0.75rem", color: "var(--text-secondary,#6b7280)" }}>
                        {ins.entity_type}
                      </div>
                    </td>
                    <td style={{ fontSize: "0.8rem", color: "var(--text-secondary,#6b7280)" }}>
                      {(ins.metadata?.project as string) || (ins.metadata?.tenant_name as string) || "—"}
                    </td>
                    <td>
                      <div style={{ maxWidth: 280 }}>
                        <div style={{ fontWeight: 500, fontSize: "0.88rem" }}>{ins.title}</div>
                        <div style={{ fontSize: "0.78rem", color: "var(--text-secondary,#6b7280)", marginTop: 2 }}>
                          {ins.message}
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className={statusClass(ins.status)}>{ins.status}</span>
                      {ins.snooze_until && (
                        <div style={{ fontSize: "0.7rem", color: "var(--text-secondary,#6b7280)", marginTop: 2 }}>
                          until {fmtTs(ins.snooze_until)}
                        </div>
                      )}
                    </td>
                    <td style={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>
                      {fmtTs(ins.detected_at)}
                    </td>
                    {canWrite && (
                      <td>
                        <div className="insight-actions">
                          {ins.status === "open" && (
                            <button className="btn-sm primary" onClick={() => doAcknowledge(ins.id)}>
                              Ack
                            </button>
                          )}
                          {(ins.status === "open" || ins.status === "acknowledged") && (
                            <button className="btn-sm" onClick={() => setSnoozeTarget(ins.id)}>
                              Snooze
                            </button>
                          )}
                          {ins.status !== "resolved" && (
                            <button className="btn-sm" onClick={() => doResolve(ins.id)}>
                              Resolve
                            </button>
                          )}
                          {/* Recommendations toggle */}
                          {(ins.type.startsWith("waste_") || ins.type.startsWith("risk_")) && (
                            <button
                              className="btn-sm"
                              title="Show recommendations"
                              onClick={() => toggleRecommendations(ins.id)}
                            >
                              {loadingRecs[ins.id] ? "…" : expandedRecs[ins.id] !== undefined ? "▲ Recs" : "▼ Recs"}
                            </button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                  {/* Recommendations expansion panel */}
                  {expandedRecs[ins.id] !== undefined && (
                    <tr key={`recs-${ins.id}`}>
                      <td colSpan={canWrite ? 8 : 7} style={{ background: "var(--bg-subtle,#f9fafb)", padding: "0.5rem 1rem 0.75rem" }}>
                        <strong style={{ fontSize: "0.78rem" }}>Recommendations</strong>
                        {expandedRecs[ins.id].length === 0 ? (
                          <span style={{ fontSize: "0.78rem", color: "var(--text-secondary,#6b7280)", marginLeft: "0.5rem" }}>
                            No recommendations available.
                          </span>
                        ) : (
                          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginTop: "0.35rem" }}>
                            {expandedRecs[ins.id].map((rec) => (
                              <div key={rec.id} style={{
                                display: "flex", alignItems: "center", gap: "0.4rem",
                                background: "var(--card-bg,#fff)", border: "1px solid var(--border,#e5e7eb)",
                                borderRadius: 6, padding: "0.3rem 0.6rem", fontSize: "0.8rem",
                                opacity: rec.status !== "pending" ? 0.5 : 1,
                              }}>
                                <span>{rec.action_type === "runbook" ? "🔧" : rec.action_type === "resize" ? "⬇️" : "💡"}</span>
                                <span>
                                  <strong>{rec.action_type}</strong>
                                  {typeof rec.action_payload?.runbook_key === "string" && (
                                    <span style={{ color: "var(--text-secondary,#6b7280)", marginLeft: "0.25rem" }}>
                                      — {rec.action_payload.runbook_key}
                                    </span>
                                  )}
                                  {typeof rec.action_payload?.suggestion === "string" && (
                                    <span style={{ color: "var(--text-secondary,#6b7280)", marginLeft: "0.25rem" }}>
                                      — {rec.action_payload.suggestion}
                                    </span>
                                  )}
                                </span>
                                {rec.estimated_impact && (
                                  <span style={{ color: "var(--success,#059669)", fontSize: "0.75rem" }}>
                                    {rec.estimated_impact}
                                  </span>
                                )}
                                {rec.status === "pending" && canWrite && (
                                  <button
                                    className="btn-sm"
                                    style={{ fontSize: "0.7rem", padding: "0.1rem 0.4rem" }}
                                    onClick={() => dismissRecommendation(ins.id, rec.id)}
                                  >
                                    Dismiss
                                  </button>
                                )}
                                {rec.status !== "pending" && (
                                  <span style={{ fontSize: "0.7rem", color: "var(--text-secondary,#6b7280)" }}>
                                    {rec.status}
                                  </span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
              </tbody>
            </table>
          )}

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem", justifyContent: "center" }}>
              <button className="btn-sm" disabled={page === 1} onClick={() => loadInsights(page - 1)}>
                ← Prev
              </button>
              <span style={{ padding: "0.25rem 0.5rem", fontSize: "0.85rem" }}>
                {page} / {Math.ceil(total / PAGE_SIZE)}
              </span>
              <button
                className="btn-sm"
                disabled={page * PAGE_SIZE >= total}
                onClick={() => loadInsights(page + 1)}
              >
                Next →
              </button>
            </div>
          )}
        </div>
      </>
    );
  }

  function renderRisk() {    // Filter to risk + capacity insights from current feed (or re-use summary by_type)
    const riskInsights = insights.filter(
      (i) => i.type.startsWith("risk_") || i.type.startsWith("capacity_") || i.type.startsWith("waste_")
    );

    // Group by entity (project)
    const byEntity: Record<string, Insight[]> = {};
    for (const ins of riskInsights) {
      const key = ins.entity_name || ins.entity_id;
      if (!byEntity[key]) byEntity[key] = [];
      byEntity[key].push(ins);
    }

    const sevOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

    function sortRiskRows(entries: [string, Insight[]][]) {
      return [...entries].sort(([, a], [, b]) => {
        const { col, dir } = riskSort;
        if (col === "severity") {
          const maxSev = (arr: Insight[]) => Math.min(...arr.map((i) => sevOrder[i.severity] ?? 9));
          return (maxSev(a) - maxSev(b)) * dir;
        }
        if (col === "entity") {
          const ka = (a[0]?.entity_name || a[0]?.entity_id || "").toLowerCase();
          const kb = (b[0]?.entity_name || b[0]?.entity_id || "").toLowerCase();
          return ka < kb ? -dir : ka > kb ? dir : 0;
        }
        if (col === "count") return (a.length - b.length) * dir;
        return 0;
      });
    }

    function riskSortIcon(col: string) {
      if (riskSort.col !== col) return <span style={{ color: "var(--text-secondary,#6b7280)", fontSize: "0.65rem" }}>⇅</span>;
      return <span style={{ fontSize: "0.65rem" }}>{riskSort.dir === 1 ? "▲" : "▼"}</span>;
    }

    function toggleRiskSort(col: string) {
      setRiskSort((s) => s.col === col ? { col, dir: (s.dir === 1 ? -1 : 1) } : { col, dir: 1 });
    }

    const rows = sortRiskRows(Object.entries(byEntity));

    return (
      <div className="insights-feed">
        {rows.length === 0 ? (
          <div className="insights-empty">
            <div className="insights-empty-icon">✅</div>
            <p className="insights-empty-text">No active risk or capacity insights.</p>
          </div>
        ) : (
          <table className="insights-table">
            <thead>
              <tr>
                <th style={{ cursor: "pointer" }} onClick={() => toggleRiskSort("entity")}>
                  Entity {riskSortIcon("entity")}
                </th>
                <th>Tenant / Project</th>
                <th style={{ cursor: "pointer" }} onClick={() => toggleRiskSort("severity")}>
                  Highest Severity {riskSortIcon("severity")}
                </th>
                <th style={{ cursor: "pointer" }} onClick={() => toggleRiskSort("count")}>
                  Active Insights {riskSortIcon("count")}
                </th>
                <th>Types</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([entity, arr]) => {
                const worst = arr.reduce((w, i) =>
                  (sevOrder[i.severity] ?? 9) < (sevOrder[w.severity] ?? 9) ? i : w
                );
                const types = [...new Set(arr.map((i) => i.type.replace(/_/g, " ")))];
                const tenant = (arr[0]?.metadata?.project as string) || (arr[0]?.metadata?.tenant_name as string) || "—";
                return (
                  <tr key={entity}>
                    <td style={{ fontWeight: 600 }}>{entity}</td>
                    <td style={{ fontSize: "0.78rem", color: "var(--text-secondary,#6b7280)" }}>{tenant}</td>
                    <td><span className={sevClass(worst.severity)}>{worst.severity}</span></td>
                    <td>{arr.length}</td>
                    <td style={{ fontSize: "0.78rem", color: "var(--text-secondary,#6b7280)" }}>
                      {types.join(", ")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Capacity Forecast tab
  // ---------------------------------------------------------------------------

  function renderForecast() {
    if (forecastLoading) {
      return (
        <div style={{ padding: "2rem 1.5rem", color: "var(--text-secondary,#6b7280)" }}>
          Loading capacity forecast…
        </div>
      );
    }

    const RESOURCE_LABELS: Record<string, string> = {
      storage_gb:  "Storage (GB)",
      vcpus:       "vCPUs",
      ram_mb:      "RAM (MB)",
      instances:   "Instances",
      floating_ips: "Floating IPs",
    };

    function runwayColor(days: number | null): string {
      if (days === null) return "var(--text-secondary,#6b7280)";
      if (days <= 7)  return "var(--color-danger,#ef4444)";
      if (days <= 14) return "var(--color-warning,#f59e0b)";
      return "var(--success,#059669)";
    }

    function confidenceBadge(c: number) {
      const pct = Math.round(c * 100);
      const color = c >= 0.7 ? "var(--success,#059669)"
                  : c >= 0.4 ? "var(--color-warning,#f59e0b)"
                  : "var(--text-secondary,#6b7280)";
      return (
        <span style={{ fontSize: "0.7rem", color, marginLeft: "0.25rem" }} title={`Forecast confidence: ${pct}%`}>
          {pct}% conf.
        </span>
      );
    }

    function fcSortIcon(col: string) {
      if (fcSort.col !== col) return <span style={{ color: "var(--text-secondary,#6b7280)", fontSize: "0.65rem" }}>⇅</span>;
      return <span style={{ fontSize: "0.65rem" }}>{fcSort.dir === 1 ? "▲" : "▼"}</span>;
    }

    function toggleFcSort(col: string) {
      setFcSort((s) => s.col === col ? { col, dir: (s.dir === 1 ? -1 : 1) } : { col, dir: 1 });
    }

    function sortedForecasts() {
      return [...forecasts].sort((a, b) => {
        const { col, dir } = fcSort;
        if (col === "project") {
          return a.project_name.localeCompare(b.project_name) * dir;
        }
        // runway = min days_to_90 across all resources (null = infinite)
        const minRunway = (f: ProjectForecast) => {
          const vals = Object.values(f.resources).map((r) => r.days_to_90);
          const finite = vals.filter((v): v is number => v !== null);
          return finite.length > 0 ? Math.min(...finite) : Infinity;
        };
        return (minRunway(a) - minRunway(b)) * dir;
      });
    }

    return (
      <div className="insights-feed">
        <div style={{ padding: "0.75rem 1rem 0.25rem", display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <span style={{ fontSize: "0.82rem", color: "var(--text-secondary,#6b7280)" }}>
            Per-project resource runway — days until 90% quota. Click column headers to sort.
          </span>
          <button className="btn-sm" onClick={loadForecast} title="Refresh forecast">↻ Refresh</button>
        </div>

        {forecasts.length === 0 ? (
          <div className="insights-empty">
            <div className="insights-empty-icon">📊</div>
            <p className="insights-empty-text">No forecast data yet — requires at least 3 days of metering history.</p>
          </div>
        ) : (
          <table className="insights-table">
            <thead>
              <tr>
                <th style={{ cursor: "pointer" }} onClick={() => toggleFcSort("project")}>
                  Project {fcSortIcon("project")}
                </th>
                {Object.keys(forecasts[0]?.resources ?? {}).map((k) => (
                  <th key={k} style={{ cursor: "pointer" }} onClick={() => toggleFcSort(k)}>
                    {RESOURCE_LABELS[k] ?? k} {fcSortIcon(k)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedForecasts().map((f) => (
                <tr key={f.project_id}>
                  <td style={{ fontWeight: 600 }}>{f.project_name}</td>
                  {Object.entries(f.resources).map(([key, res]) => (
                    <td key={key}>
                      <div style={{ fontSize: "0.82rem" }}>
                        <span style={{ color: runwayColor(res.days_to_90), fontWeight: 600 }}>
                          {res.days_to_90 === null ? "—"
                           : res.days_to_90 === 0  ? "⚠️ Now"
                           : `${res.days_to_90}d`}
                        </span>
                        {confidenceBadge(res.confidence)}
                      </div>
                      <div style={{ fontSize: "0.72rem", color: "var(--text-secondary,#6b7280)" }}>
                        {res.used_pct !== null ? `${res.used_pct}% used` : "—"}
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Cross-Region Comparison tab
  // ---------------------------------------------------------------------------

  function renderRegions() {
    if (regionsLoading) {
      return (
        <div style={{ padding: "2rem 1.5rem", color: "var(--text-secondary,#6b7280)" }}>
          Loading region data…
        </div>
      );
    }

    function utilBar(pct: number) {
      const color = pct >= 85 ? "var(--color-danger,#ef4444)"
                  : pct >= 65 ? "var(--color-warning,#f59e0b)"
                  : "var(--success,#059669)";
      return (
        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <div style={{
            width: 60, height: 8, borderRadius: 4,
            background: "var(--border,#374151)", overflow: "hidden",
          }}>
            <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: color, borderRadius: 4 }} />
          </div>
          <span style={{ fontSize: "0.8rem", color }}>{pct}%</span>
        </div>
      );
    }

    return (
      <div className="insights-feed">
        <div style={{ padding: "0.75rem 1rem 0.25rem" }}>
          <span style={{ fontSize: "0.82rem", color: "var(--text-secondary,#6b7280)" }}>
            Per-region compute utilization, active insights, and capacity runway.
          </span>
          <button className="btn-sm" style={{ marginLeft: "0.75rem" }} onClick={loadRegions}>↻ Refresh</button>
        </div>

        {regions.length === 0 ? (
          <div className="insights-empty">
            <div className="insights-empty-icon">🌍</div>
            <p className="insights-empty-text">No region data available.</p>
          </div>
        ) : (
          <table className="insights-table">
            <thead>
              <tr>
                <th>Region</th>
                <th>Hypervisors</th>
                <th>vCPU Utilization</th>
                <th>RAM Utilization</th>
                <th>Running VMs</th>
                <th>Critical</th>
                <th>High</th>
                <th>Storage Runway</th>
                <th>VM Growth</th>
              </tr>
            </thead>
            <tbody>
              {regions.map((r) => (
                <tr key={r.region_id}>
                  <td style={{ fontWeight: 600, fontSize: "0.85rem" }}>{r.region_id}</td>
                  <td style={{ textAlign: "center" }}>{r.hypervisors}</td>
                  <td>{utilBar(r.vcpu_utilization)}</td>
                  <td>{utilBar(r.ram_utilization)}</td>
                  <td style={{ textAlign: "center" }}>{r.running_vms}</td>
                  <td style={{ textAlign: "center" }}>
                    {r.open_critical > 0
                      ? <span style={{ color: "var(--color-danger,#ef4444)", fontWeight: 700 }}>{r.open_critical}</span>
                      : <span style={{ color: "var(--text-secondary,#6b7280)" }}>—</span>}
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {r.open_high > 0
                      ? <span style={{ color: "var(--color-warning,#f59e0b)", fontWeight: 600 }}>{r.open_high}</span>
                      : <span style={{ color: "var(--text-secondary,#6b7280)" }}>—</span>}
                  </td>
                  <td>
                    {r.capacity_runway_days === null ? (
                      <span style={{ color: "var(--text-secondary,#6b7280)" }}>—</span>
                    ) : r.capacity_runway_days <= 7 ? (
                      <span style={{ color: "var(--color-danger,#ef4444)", fontWeight: 700 }}>
                        {r.capacity_runway_days}d ⚠️
                      </span>
                    ) : (
                      <span style={{ color: "var(--success,#059669)" }}>{r.capacity_runway_days}d</span>
                    )}
                  </td>
                  <td>
                    {r.growth_rate_pct > 0
                      ? <span style={{ color: r.growth_rate_pct > 15 ? "var(--color-warning,#f59e0b)" : "var(--text-secondary,#6b7280)" }}>
                          +{r.growth_rate_pct}%
                        </span>
                      : <span style={{ color: "var(--text-secondary,#6b7280)" }}>—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  }

  function renderSla() {
    if (slaLoading) {
      return <div style={{ padding: "2rem 1.5rem", color: "var(--text-secondary,#6b7280)" }}>Loading SLA summary…</div>;
    }

    if (slaLoadError) {
      return (
        <div style={{ padding: "2rem 1.5rem" }}>
          <div className="insights-empty-icon">⚠️</div>
          <p style={{ color: "var(--danger,#dc2626)", fontSize: "0.88rem" }}>{slaLoadError}</p>
          <button className="btn-sm" onClick={loadSlaSummary}>Retry</button>
        </div>
      );
    }

    const statusOrder: Record<string, number> = { breached: 0, at_risk: 1, ok: 2, not_configured: 9 };
    const configuredRows = slaSummary
      .filter((r) => r.tier && r.tier !== "none" && r.overall_status !== "not_configured")
      .sort((a, b) => (statusOrder[a.overall_status] ?? 9) - (statusOrder[b.overall_status] ?? 9));
    const unconfiguredCount = slaSummary.length - configuredRows.length;

    const selectedTier = slaTiers.find((t) => t.tier === slaPickTier);

    return (
      <div className="insights-feed">
        {/* Header row with assign button */}
        {canWrite && (
          <div style={{ display: "flex", justifyContent: "flex-end", padding: "0.75rem 1rem 0" }}>
            <button className="insights-action-btn" onClick={openSlaModal}>
              ＋ Assign SLA Tier
            </button>
          </div>
        )}

        {configuredRows.length === 0 ? (
          <div className="insights-empty">
            <div className="insights-empty-icon">📋</div>
            <p className="insights-empty-text">No SLA commitments configured.</p>
            {canWrite && (
              <p style={{ fontSize: "0.85rem", color: "var(--text-secondary,#9ca3af)", marginTop: "0.5rem" }}>
                Use the <strong>Assign SLA Tier</strong> button above to set a tier for a tenant.
                The SLA worker will compute compliance on its next run (every 4 hours).
              </p>
            )}
          </div>
        ) : (
          <>
          <table className="insights-table">
            <thead>
              <tr>
                <th>Tenant</th>
                <th>Tier</th>
                <th>Breached KPIs</th>
                <th>At-Risk KPIs</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {configuredRows.map((row) => (
                <tr key={row.tenant_id}>
                  <td style={{ fontWeight: 600 }}>{row.tenant_name || row.tenant_id}</td>
                  <td>
                    {row.tier && row.tier !== "none"
                      ? <span className="sla-tier-badge">{row.tier}</span>
                      : <span style={{ color: "var(--text-secondary,#9ca3af)" }}>—</span>}
                  </td>
                  <td>
                    {row.breach_fields.length > 0
                      ? <span style={{ color: "var(--color-danger,#ef4444)" }}>{row.breach_fields.join(", ")}</span>
                      : <span style={{ color: "var(--text-secondary,#9ca3af)" }}>none</span>}
                  </td>
                  <td>
                    {row.at_risk_fields.length > 0
                      ? <span style={{ color: "var(--color-warning,#f59e0b)" }}>{row.at_risk_fields.join(", ")}</span>
                      : <span style={{ color: "var(--text-secondary,#9ca3af)" }}>none</span>}
                  </td>
                  <td>
                    <span className={`sla-status-${row.overall_status}`}>
                      {row.overall_status.replace(/_/g, " ")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {unconfiguredCount > 0 && (
            <p style={{ fontSize: "0.78rem", color: "var(--text-secondary,#6b7280)", padding: "0.5rem 1rem 0", margin: 0 }}>
              {unconfiguredCount} tenant{unconfiguredCount !== 1 ? "s" : ""} not yet configured. Use <strong>Assign SLA Tier</strong> to add them.
            </p>
          )}
          </>
        )}

        {/* Assign SLA Tier modal */}
        {slaModalOpen && (
          <div className="insights-modal-overlay" onClick={() => setSlaModalOpen(false)}>
            <div className="insights-modal" onClick={(e) => e.stopPropagation()}>
              <div className="insights-modal-header">
                <span>Assign SLA Tier</span>
                <button className="insights-modal-close" onClick={() => setSlaModalOpen(false)}>✕</button>
              </div>
              <div className="insights-modal-body" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>

                <label style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                  <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-secondary,#6b7280)" }}>TENANT</span>
                  <select
                    className="insights-select"
                    value={slaPickTenant}
                    onChange={(e) => setSlaPickTenant(e.target.value)}
                  >
                    <option value="">— select tenant —</option>
                    {slaTenants.map((t) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                </label>

                <label style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                  <span style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-secondary,#6b7280)" }}>TIER</span>
                  <select
                    className="insights-select"
                    value={slaPickTier}
                    onChange={(e) => setSlaPickTier(e.target.value)}
                  >
                    <option value="">— select tier —</option>
                    {(slaTiers.length > 0
                      ? slaTiers
                      : [{tier:"gold",display_name:"Gold"},{tier:"silver",display_name:"Silver"},{tier:"bronze",display_name:"Bronze"},{tier:"custom",display_name:"Custom"}] as SlaTierTemplate[]
                    ).map((t) => <option key={t.tier} value={t.tier}>{t.display_name}</option>)}
                  </select>
                </label>

                {selectedTier && (
                  <div style={{ fontSize: "0.78rem", background: "var(--bg-secondary,#1e2028)", borderRadius: "6px", padding: "0.75rem 0.9rem", color: "var(--text-secondary,#9ca3af)", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                    {/* Tier description */}
                    <div style={{ color: "var(--text-primary,#e5e7eb)", fontWeight: 600, fontSize: "0.82rem" }}>
                      {selectedTier.tier === "gold"   && "🥇 Gold — Mission-critical workloads. Highest uptime guarantee. Any SLA breach auto-generates a critical incident insight and triggers notifications."}
                      {selectedTier.tier === "silver" && "🥈 Silver — Standard production workloads. Balanced SLA with automated compliance monitoring. Breaches generate high-severity insights."}
                      {selectedTier.tier === "bronze" && "🥉 Bronze — Dev / test / non-critical workloads. Best-effort SLA. Breaches generate medium-severity insights."}
                      {selectedTier.tier === "custom" && "⚙️ Custom — Fully configurable targets. Set exact thresholds when assigning. Use for enterprise contracts with negotiated SLAs."}
                    </div>
                    {/* KPI grid */}
                    {selectedTier.tier !== "custom" && (
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.35rem 0.75rem" }}>
                        {selectedTier.uptime_pct != null && (
                          <div><span style={{ opacity: 0.6 }}>Uptime </span><strong style={{ color: "var(--text-primary,#e5e7eb)" }}>≥ {selectedTier.uptime_pct}%</strong></div>
                        )}
                        {selectedTier.rto_hours != null && (
                          <div><span style={{ opacity: 0.6 }}>RTO </span><strong style={{ color: "var(--text-primary,#e5e7eb)" }}>{selectedTier.rto_hours}h</strong></div>
                        )}
                        {selectedTier.rpo_hours != null && (
                          <div><span style={{ opacity: 0.6 }}>RPO </span><strong style={{ color: "var(--text-primary,#e5e7eb)" }}>{selectedTier.rpo_hours}h</strong></div>
                        )}
                        {selectedTier.mtta_hours != null && (
                          <div><span style={{ opacity: 0.6 }}>MTTA </span><strong style={{ color: "var(--text-primary,#e5e7eb)" }}>{selectedTier.mtta_hours}h</strong></div>
                        )}
                        {selectedTier.mttr_hours != null && (
                          <div><span style={{ opacity: 0.6 }}>MTTR </span><strong style={{ color: "var(--text-primary,#e5e7eb)" }}>{selectedTier.mttr_hours}h</strong></div>
                        )}
                        {selectedTier.backup_freq_hours != null && (
                          <div><span style={{ opacity: 0.6 }}>Backup </span><strong style={{ color: "var(--text-primary,#e5e7eb)" }}>every {selectedTier.backup_freq_hours}h</strong></div>
                        )}
                      </div>
                    )}
                    <div style={{ fontSize: "0.72rem", opacity: 0.55, fontStyle: "italic" }}>
                      Abbreviations: RTO = Recovery Time Objective · RPO = Recovery Point Objective · MTTA = Mean Time to Acknowledge · MTTR = Mean Time to Resolve
                    </div>
                  </div>
                )}

                {slaError && (
                  <p style={{ color: "var(--color-danger,#ef4444)", fontSize: "0.85rem", margin: 0 }}>{slaError}</p>
                )}
              </div>
              <div className="insights-modal-footer">
                <button className="insights-action-btn" onClick={saveSlaCommitment} disabled={slaSaving}>
                  {slaSaving ? "Saving…" : "Save"}
                </button>
                <button className="insights-cancel-btn" onClick={() => setSlaModalOpen(false)}>Cancel</button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Main render
  // ---------------------------------------------------------------------------

  return (
    <div className="insights-tab">
      {/* Workspace selector */}
      <div className="insights-workspace-bar">
        {(
          [
            { id: "global",      label: "🌐 Global" },
            { id: "support",     label: "🎧 Support" },
            { id: "engineering", label: "⚙️ Engineering" },
            { id: "operations",  label: "📊 Operations" },
          ] as { id: string; label: string }[]
        ).map((ws) => (
          <button
            key={ws.id}
            className={`insights-workspace-btn${workspace === ws.id ? " active" : ""}`}
            onClick={() => changeWorkspace(ws.id)}
          >
            {ws.label}
          </button>
        ))}
        <span className="insights-workspace-hint">
          {workspace === "support"     && "Showing: drift · snapshot · incident · risk (high+)"}
          {workspace === "engineering" && "Showing: capacity · waste · anomaly · cross-region (medium+)"}
          {workspace === "operations"  && "Showing: risk · health · leakage (medium+)"}
          {workspace === "global"      && "Showing: all insight types"}
        </span>
      </div>

      {/* Inner tab nav */}
      <div className="insights-inner-tabs">
        {(
          [
            { id: "feed"     as const, label: "🔔 Insights Feed" },
            { id: "risk"     as const, label: "⚠️ Risk & Capacity" },
            { id: "forecast" as const, label: "📈 Capacity Forecast" },
            { id: "regions"  as const, label: "🌍 Cross-Region" },
            { id: "sla"      as const, label: "📋 SLA Summary" },
            ...(canWrite ? [{ id: "settings" as const, label: "⚙️ Settings" }] : []),
          ] as { id: InnerTab; label: string }[]
        ).map((t) => (
          <button
            key={t.id}
            className={`insights-inner-tab${innerTab === t.id ? " active" : ""}`}
            onClick={() => setInnerTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {innerTab === "feed"     && renderFeed()}
      {innerTab === "risk"     && renderRisk()}
      {innerTab === "forecast" && renderForecast()}
      {innerTab === "regions"  && renderRegions()}
      {innerTab === "sla"      && renderSla()}
      {innerTab === "settings" && <IntelligenceSettingsPanel userRole={userRole} />}

      {/* Snooze modal */}
      {snoozeTarget !== null && (
        <div className="snooze-overlay" onClick={() => setSnoozeTarget(null)}>
          <div className="snooze-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Snooze insight</h3>
            <label>Snooze until</label>
            <input
              type="datetime-local"
              value={snoozeUntil}
              onChange={(e) => setSnoozeUntil(e.target.value)}
            />
            <div className="snooze-actions">
              <button className="btn-sm" onClick={() => setSnoozeTarget(null)}>Cancel</button>
              <button className="btn-sm primary" onClick={doSnooze} disabled={!snoozeUntil}>
                Snooze
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
