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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TYPE_ICONS: Record<string, string> = {
  capacity_storage:      "💾",
  waste_idle_vm:         "🖥️",
  waste_unattached_volume: "📦",
  waste_old_snapshots:   "📸",
  risk_snapshot_gap:     "⚠️",
  risk_health_decline:   "📉",
  risk_unack_drift:      "🔀",
  sla_risk:              "📋",
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

type InnerTab = "feed" | "risk" | "sla";

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
    const params = new URLSearchParams({ page: String(p), page_size: String(PAGE_SIZE) });
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

  useEffect(() => { loadInsights(1); }, [filterStatus, filterSeverity, filterType, workspace]);
  useEffect(() => { loadSummary(); }, [workspace]);
  useEffect(() => { if (innerTab === "sla") loadSlaSummary(); }, [innerTab]);

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
            <option value="capacity_storage">Capacity</option>
            <option value="waste_idle_vm">Idle VM</option>
            <option value="waste_unattached_volume">Unattached Volume</option>
            <option value="waste_old_snapshots">Stale Snapshots</option>
            <option value="risk_snapshot_gap">Snapshot Gap</option>
            <option value="risk_health_decline">Health Decline</option>
            <option value="risk_unack_drift">Unack Drift</option>
            <option value="sla_risk">SLA Risk</option>
          </select>
          {(filterStatus || filterSeverity || filterType) && (
            <button className="insights-filter-reset" onClick={() => {
              setFilterStatus(""); setFilterSeverity(""); setFilterType("");
            }}>
              Clear filters
            </button>
          )}
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
                      <td colSpan={canWrite ? 7 : 6} style={{ background: "var(--bg-subtle,#f9fafb)", padding: "0.5rem 1rem 0.75rem" }}>
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

  function renderRisk() {
    // Filter to risk + capacity insights from current feed (or re-use summary by_type)
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

    const rows = Object.entries(byEntity).sort(
      ([, a], [, b]) => {
        const maxSev = (arr: Insight[]) => {
          const order: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
          return Math.min(...arr.map((i) => order[i.severity] ?? 9));
        };
        return maxSev(a) - maxSev(b);
      }
    );

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
                <th>Entity</th>
                <th>Tenant / Project</th>
                <th>Highest Severity</th>
                <th>Active Insights</th>
                <th>Types</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([entity, arr]) => {
                const sevOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
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
          {workspace === "engineering" && "Showing: capacity · waste · anomaly (medium+)"}
          {workspace === "operations"  && "Showing: risk · health (medium+)"}
          {workspace === "global"      && "Showing: all insight types"}
        </span>
      </div>

      {/* Inner tab nav */}
      <div className="insights-inner-tabs">
        {(
          [
            { id: "feed" as const, label: "🔔 Insights Feed" },
            { id: "risk" as const, label: "⚠️ Risk & Capacity" },
            { id: "sla"  as const, label: "📋 SLA Summary" },
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

      {innerTab === "feed" && renderFeed()}
      {innerTab === "risk" && renderRisk()}
      {innerTab === "sla"  && renderSla()}

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
