import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";
import "../styles/TenantHealthView.css";

/* ──────────────────────────────────────────────────────────── */
/*  Types                                                       */
/* ──────────────────────────────────────────────────────────── */

interface TenantHealth {
  project_id: string;
  project_name: string;
  domain_id: string;
  domain_name: string;
  health_score: number;
  // Servers
  total_servers: number;
  active_servers: number;
  shutoff_servers: number;
  error_servers: number;
  other_servers: number;
  // Compute allocation
  total_vcpus: number;
  total_ram_mb: number;
  total_flavor_disk_gb: number;
  active_vcpus: number;
  active_ram_mb: number;
  hypervisor_count: number;
  power_on_pct: number;
  // Volumes
  total_volumes: number;
  total_volume_gb: number;
  available_volumes: number;
  in_use_volumes: number;
  error_volumes: number;
  other_volumes: number;
  // Networking
  total_networks: number;
  total_subnets: number;
  total_ports: number;
  total_floating_ips: number;
  active_fips: number;
  down_fips: number;
  // Security
  total_security_groups: number;
  // Snapshots
  total_snapshots: number;
  available_snapshots: number;
  error_snapshots: number;
  total_snapshot_gb: number;
  // Drift
  total_drift_events: number;
  critical_drift: number;
  warning_drift: number;
  info_drift: number;
  new_drift: number;
  drift_7d: number;
  drift_30d: number;
  // Compliance
  total_compliance_items: number;
  compliant_items: number;
  compliance_pct: number;
}

interface OverviewSummary {
  total_tenants: number;
  healthy: number;
  warning: number;
  critical: number;
  avg_health_score: number;
}

interface DriftEvent {
  id: number;
  severity: string;
  resource_type: string;
  resource_name: string;
  field_changed: string;
  old_value: string;
  new_value: string;
  description: string;
  detected_at: string;
  acknowledged: boolean;
}

interface StatusCount {
  status: string;
  count: number;
}

interface TopVolume {
  id: string;
  name: string;
  size_gb: number;
  status: string;
}

interface TenantDetail {
  tenant: TenantHealth;
  recent_drift_events: DriftEvent[];
  server_status_breakdown: StatusCount[];
  volume_status_breakdown: StatusCount[];
  top_volumes: TopVolume[];
}

interface QuotaResource {
  limit: number;
  in_use: number;
  reserved: number;
}

interface QuotaData {
  available: boolean;
  reason?: string;
  project_id?: string;
  compute?: {
    instances: QuotaResource;
    cores: QuotaResource;
    ram_mb: QuotaResource;
  };
  storage?: {
    volumes: QuotaResource;
    gigabytes: QuotaResource;
    snapshots: QuotaResource;
  };
}

interface HeatmapTenant {
  project_id: string;
  project_name: string;
  domain_name: string;
  health_score: number;
  total_servers: number;
  active_servers: number;
  shutoff_servers: number;
  error_servers: number;
  total_vcpus: number;
  active_vcpus: number;
  total_ram_mb: number;
  active_ram_mb: number;
  power_on_pct: number;
  total_volumes: number;
  total_volume_gb: number;
  total_drift_events: number;
  critical_drift: number;
  compliance_pct: number;
  utilization_score: number;
}

export interface TenantHealthViewProps {
  selectedDomain?: string;
  selectedTenant?: string;
}

/* ──────────────────────────────────────────────────────────── */
/*  Helpers                                                     */
/* ──────────────────────────────────────────────────────────── */

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = localStorage.getItem("auth_token");
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (opts?.body) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: { ...headers, ...((opts?.headers as Record<string, string>) || {}) },
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

function scoreClass(score: number): string {
  if (score >= 80) return "healthy";
  if (score >= 50) return "warning";
  return "critical";
}

function pct(value: number, total: number): string {
  if (total === 0) return "0";
  return ((value / total) * 100).toFixed(0);
}

function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return (
    d.toLocaleDateString() +
    " " +
    d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );
}

function fmtRam(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb} MB`;
}

function heatColor(score: number): string {
  if (score >= 80) return "#22c55e";
  if (score >= 60) return "#84cc16";
  if (score >= 40) return "#f59e0b";
  if (score >= 20) return "#f97316";
  return "#ef4444";
}

/* ──────────────────────────────────────────────────────────── */
/*  Main Component                                              */
/* ──────────────────────────────────────────────────────────── */

export default function TenantHealthView({
  selectedDomain,
  selectedTenant,
}: TenantHealthViewProps) {
  const [summary, setSummary] = useState<OverviewSummary | null>(null);
  const [tenants, setTenants] = useState<TenantHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [sortBy, setSortBy] = useState("health_score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [search, setSearch] = useState("");

  // View mode: table or heatmap
  const [viewMode, setViewMode] = useState<"table" | "heatmap">("table");
  const [heatmapData, setHeatmapData] = useState<HeatmapTenant[]>([]);
  const [heatmapLoading, setHeatmapLoading] = useState(false);

  // Detail panel
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TenantDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [quota, setQuota] = useState<QuotaData | null>(null);
  const [quotaLoading, setQuotaLoading] = useState(false);

  const globalDomain =
    selectedDomain && selectedDomain !== "__ALL__" ? selectedDomain : undefined;
  const globalTenant =
    selectedTenant && selectedTenant !== "__ALL__" ? selectedTenant : undefined;

  /* ─── Fetch overview ─── */
  const fetchOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (globalDomain) params.append("domain_id", globalDomain);
      params.append("sort_by", sortBy);
      params.append("sort_dir", sortDir);
      const qs = params.toString() ? `?${params}` : "";
      const data = await apiFetch<{
        summary: OverviewSummary;
        tenants: TenantHealth[];
      }>(`/tenant-health/overview${qs}`);
      setSummary(data.summary);
      setTenants(data.tenants);
    } catch (e: any) {
      setError(e.message || "Failed to fetch tenant health data");
    } finally {
      setLoading(false);
    }
  }, [globalDomain, sortBy, sortDir]);

  useEffect(() => {
    fetchOverview();
  }, [fetchOverview]);

  /* ─── Fetch heatmap ─── */
  const fetchHeatmap = useCallback(async () => {
    setHeatmapLoading(true);
    try {
      const params = new URLSearchParams();
      if (globalDomain) params.append("domain_id", globalDomain);
      const qs = params.toString() ? `?${params}` : "";
      const data = await apiFetch<{ tenants: HeatmapTenant[] }>(
        `/tenant-health/heatmap${qs}`
      );
      setHeatmapData(data.tenants);
    } catch {
      /* heatmap is supplementary */
    } finally {
      setHeatmapLoading(false);
    }
  }, [globalDomain]);

  useEffect(() => {
    if (viewMode === "heatmap") fetchHeatmap();
  }, [viewMode, fetchHeatmap]);

  /* ─── Fetch detail + quota ─── */
  const openDetail = useCallback(async (projectId: string) => {
    setSelectedId(projectId);
    setDetailLoading(true);
    setQuota(null);
    try {
      const data = await apiFetch<TenantDetail>(`/tenant-health/${projectId}`);
      setDetail(data);
    } catch (e: any) {
      setDetail(null);
      setError(`Detail error: ${e.message}`);
    } finally {
      setDetailLoading(false);
    }
    // Fetch quota in parallel (best-effort)
    setQuotaLoading(true);
    try {
      const q = await apiFetch<QuotaData>(
        `/tenant-health/quota/${projectId}`
      );
      setQuota(q);
    } catch {
      /* quota is optional */
    } finally {
      setQuotaLoading(false);
    }
  }, []);

  const closeDetail = () => {
    setSelectedId(null);
    setDetail(null);
    setQuota(null);
  };

  /* ─── Auto-open tenant when global filter is active ─── */
  useEffect(() => {
    if (globalTenant && tenants.length > 0) {
      const match = tenants.find((t) => t.project_id === globalTenant);
      if (match && selectedId !== globalTenant) {
        openDetail(globalTenant);
      }
    }
  }, [globalTenant, tenants, openDetail, selectedId]);

  /* ─── Client-side search filter ─── */
  const filtered = search
    ? tenants.filter(
        (t) =>
          t.project_name.toLowerCase().includes(search.toLowerCase()) ||
          t.domain_name.toLowerCase().includes(search.toLowerCase())
      )
    : tenants;

  /* ─── Column sort handler ─── */
  const handleSort = (col: string) => {
    if (col === sortBy) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("asc");
    }
  };

  const sortArrow = (col: string) => {
    if (col !== sortBy) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  };

  /* ─── CSV Export ─── */
  function exportCSV() {
    if (filtered.length === 0) return;
    const headers = [
      "Project",
      "Domain",
      "Health Score",
      "Servers",
      "Active",
      "Shutoff",
      "Error",
      "vCPUs",
      "Active vCPUs",
      "RAM (MB)",
      "Active RAM (MB)",
      "Power On %",
      "Volumes",
      "Volume GB",
      "In-Use Volumes",
      "Networks",
      "Floating IPs",
      "Security Groups",
      "Snapshots",
      "Snapshot GB",
      "Drift Events",
      "Critical Drift",
      "Compliance %",
    ];
    const rows = filtered.map((t) => [
      t.project_name,
      t.domain_name,
      t.health_score,
      t.total_servers,
      t.active_servers,
      t.shutoff_servers,
      t.error_servers,
      t.total_vcpus,
      t.active_vcpus,
      t.total_ram_mb,
      t.active_ram_mb,
      t.power_on_pct,
      t.total_volumes,
      t.total_volume_gb,
      t.in_use_volumes,
      t.total_networks,
      t.total_floating_ips,
      t.total_security_groups,
      t.total_snapshots,
      t.total_snapshot_gb,
      t.total_drift_events,
      t.critical_drift,
      t.compliance_pct,
    ]);
    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `tenant_health_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  /* ─── Aggregate totals for summary bar ─── */
  const totalVCPUs = tenants.reduce((s, t) => s + t.total_vcpus, 0);
  const totalRAM = tenants.reduce((s, t) => s + t.total_ram_mb, 0);
  const totalVMs = tenants.reduce((s, t) => s + t.total_servers, 0);
  const activeVMs = tenants.reduce((s, t) => s + t.active_servers, 0);
  const shutoffVMs = tenants.reduce((s, t) => s + t.shutoff_servers, 0);

  /* ──────────────────────────────────────────────────────────── */
  /*  Render                                                      */
  /* ──────────────────────────────────────────────────────────── */

  return (
    <div className="th-container">
      <h2>🏥 Tenant Health Overview</h2>

      {error && <div className="th-error">⚠ {error}</div>}

      {/* ── Summary cards ── */}
      {summary && (
        <>
          <div className="th-summary-row">
            <div className="th-summary-card">
              <div className="th-card-value">{summary.total_tenants}</div>
              <div className="th-card-label">Total Tenants</div>
            </div>
            <div className="th-summary-card">
              <div className="th-card-value th-val-healthy">{summary.healthy}</div>
              <div className="th-card-label">Healthy (≥80)</div>
            </div>
            <div className="th-summary-card">
              <div className="th-card-value th-val-warning">{summary.warning}</div>
              <div className="th-card-label">Warning (50-79)</div>
            </div>
            <div className="th-summary-card">
              <div className="th-card-value th-val-critical">{summary.critical}</div>
              <div className="th-card-label">Critical (&lt;50)</div>
            </div>
            <div className="th-summary-card">
              <div className="th-card-value th-val-avg">{summary.avg_health_score}</div>
              <div className="th-card-label">Avg Score</div>
            </div>
          </div>

          {/* ── Compute summary row ── */}
          <div className="th-compute-row">
            <div className="th-compute-card">
              <span className="th-compute-icon">🖥️</span>
              <div>
                <div className="th-compute-value">{totalVMs}</div>
                <div className="th-compute-label">Total VMs</div>
              </div>
              <div className="th-compute-sub">
                <span className="th-dot-green" /> {activeVMs} on
                <span className="th-dot-gray" style={{ marginLeft: 8 }} /> {shutoffVMs} off
              </div>
            </div>
            <div className="th-compute-card">
              <span className="th-compute-icon">⚡</span>
              <div>
                <div className="th-compute-value">{totalVCPUs}</div>
                <div className="th-compute-label">Total vCPUs</div>
              </div>
            </div>
            <div className="th-compute-card">
              <span className="th-compute-icon">🧠</span>
              <div>
                <div className="th-compute-value">{fmtRam(totalRAM)}</div>
                <div className="th-compute-label">Total RAM</div>
              </div>
            </div>
            <div className="th-compute-card">
              <span className="th-compute-icon">📊</span>
              <div>
                <div className="th-compute-value">
                  {totalVMs > 0
                    ? `${((activeVMs / totalVMs) * 100).toFixed(0)}%`
                    : "N/A"}
                </div>
                <div className="th-compute-label">Power-On Rate</div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* ── Toolbar ── */}
      <div className="th-toolbar">
        <input
          type="text"
          placeholder="Search tenants…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="th-view-toggle">
          <button
            className={`th-btn ${viewMode === "table" ? "primary" : ""}`}
            onClick={() => setViewMode("table")}
          >
            📋 Table
          </button>
          <button
            className={`th-btn ${viewMode === "heatmap" ? "primary" : ""}`}
            onClick={() => setViewMode("heatmap")}
          >
            🗺️ Heatmap
          </button>
        </div>
        <button
          className="th-btn"
          onClick={() => {
            fetchOverview();
            if (viewMode === "heatmap") fetchHeatmap();
          }}
          title="Refresh"
        >
          🔄 Refresh
        </button>
        <button
          className="th-btn"
          onClick={exportCSV}
          disabled={filtered.length === 0}
        >
          📥 Export CSV
        </button>
      </div>

      {/* ── Loading ── */}
      {loading && <div className="th-loading">Loading tenant health data…</div>}

      {/* ── TABLE VIEW ── */}
      {!loading && viewMode === "table" && filtered.length === 0 && (
        <div className="th-empty">
          <div className="th-empty-icon">📊</div>
          <p>No tenants found{search ? " matching your search" : ""}.</p>
        </div>
      )}

      {!loading && viewMode === "table" && filtered.length > 0 && (
        <div className="th-table-wrap">
          <table className="th-table">
            <thead>
              <tr>
                <th onClick={() => handleSort("health_score")}>
                  Score{sortArrow("health_score")}
                </th>
                <th onClick={() => handleSort("project_name")}>
                  Tenant{sortArrow("project_name")}
                </th>
                <th onClick={() => handleSort("domain_name")}>
                  Domain{sortArrow("domain_name")}
                </th>
                <th onClick={() => handleSort("total_servers")}>
                  VMs{sortArrow("total_servers")}
                </th>
                <th>Power State</th>
                <th>vCPUs / RAM</th>
                <th onClick={() => handleSort("total_volumes")}>
                  Volumes{sortArrow("total_volumes")}
                </th>
                <th onClick={() => handleSort("total_networks")}>
                  Networks{sortArrow("total_networks")}
                </th>
                <th onClick={() => handleSort("total_drift_events")}>
                  Drift{sortArrow("total_drift_events")}
                </th>
                <th onClick={() => handleSort("compliance_pct")}>
                  Compliance{sortArrow("compliance_pct")}
                </th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => {
                const cls = scoreClass(t.health_score);
                return (
                  <tr
                    key={t.project_id}
                    onClick={() => openDetail(t.project_id)}
                  >
                    <td>
                      <span className={`th-score th-score-${cls}`}>
                        {t.health_score}
                      </span>
                    </td>
                    <td>
                      <strong>{t.project_name}</strong>
                    </td>
                    <td>{t.domain_name}</td>
                    <td>
                      {t.total_servers}
                      {t.error_servers > 0 && (
                        <span
                          className="th-badge th-badge-critical"
                          style={{ marginLeft: 6 }}
                        >
                          {t.error_servers} err
                        </span>
                      )}
                    </td>
                    <td>
                      {t.total_servers > 0 ? (
                        <div className="th-mini-bar">
                          {t.active_servers > 0 && (
                            <div
                              className="th-mini-seg th-seg-active"
                              style={{
                                width: `${pct(t.active_servers, t.total_servers)}%`,
                              }}
                              title={`${t.active_servers} active`}
                            />
                          )}
                          {t.shutoff_servers > 0 && (
                            <div
                              className="th-mini-seg th-seg-shutoff"
                              style={{
                                width: `${pct(t.shutoff_servers, t.total_servers)}%`,
                              }}
                              title={`${t.shutoff_servers} shutoff`}
                            />
                          )}
                          {t.error_servers > 0 && (
                            <div
                              className="th-mini-seg th-seg-error"
                              style={{
                                width: `${pct(t.error_servers, t.total_servers)}%`,
                              }}
                              title={`${t.error_servers} error`}
                            />
                          )}
                        </div>
                      ) : (
                        <span
                          style={{
                            color: "var(--color-text-secondary, #94a3b8)",
                          }}
                        >
                          —
                        </span>
                      )}
                    </td>
                    <td>
                      {t.total_vcpus > 0 ? (
                        <span style={{ fontSize: "0.82rem" }}>
                          {t.total_vcpus} vCPU · {fmtRam(t.total_ram_mb)}
                        </span>
                      ) : (
                        <span
                          style={{
                            color: "var(--color-text-secondary, #94a3b8)",
                          }}
                        >
                          —
                        </span>
                      )}
                    </td>
                    <td>
                      {t.total_volumes}
                      <span
                        style={{
                          fontSize: "0.75rem",
                          color: "var(--color-text-secondary, #64748b)",
                          marginLeft: 4,
                        }}
                      >
                        ({t.total_volume_gb} GB)
                      </span>
                    </td>
                    <td>{t.total_networks}</td>
                    <td>
                      {t.total_drift_events > 0 ? (
                        <>
                          {t.critical_drift > 0 && (
                            <span
                              className="th-badge th-badge-critical"
                              style={{ marginRight: 4 }}
                            >
                              {t.critical_drift}C
                            </span>
                          )}
                          {t.warning_drift > 0 && (
                            <span
                              className="th-badge th-badge-warning"
                              style={{ marginRight: 4 }}
                            >
                              {t.warning_drift}W
                            </span>
                          )}
                          {t.info_drift > 0 && (
                            <span className="th-badge th-badge-healthy">
                              {t.info_drift}I
                            </span>
                          )}
                        </>
                      ) : (
                        <span
                          style={{
                            color: "var(--color-text-secondary, #94a3b8)",
                          }}
                        >
                          —
                        </span>
                      )}
                    </td>
                    <td>
                      {t.total_compliance_items > 0 ? (
                        <span
                          className={`th-badge th-badge-${
                            t.compliance_pct >= 90
                              ? "healthy"
                              : t.compliance_pct >= 60
                              ? "warning"
                              : "critical"
                          }`}
                        >
                          {t.compliance_pct}%
                        </span>
                      ) : (
                        <span
                          style={{
                            color: "var(--color-text-secondary, #94a3b8)",
                          }}
                        >
                          N/A
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={`th-badge th-badge-${cls}`}>
                        {cls === "healthy"
                          ? "✓ Healthy"
                          : cls === "warning"
                          ? "⚠ Warning"
                          : "✗ Critical"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ── HEATMAP VIEW ── */}
      {!loading && viewMode === "heatmap" && (
        <div className="th-heatmap-section">
          <h3>Resource Utilization Heatmap</h3>
          <p className="th-heatmap-subtitle">
            Each tile represents a tenant. Size reflects VM count. Color reflects
            utilization (green&nbsp;=&nbsp;high active&nbsp;%, red&nbsp;=&nbsp;low
            / issues).
          </p>
          {heatmapLoading ? (
            <div className="th-loading">Loading heatmap…</div>
          ) : heatmapData.length === 0 ? (
            <div className="th-empty">
              <div className="th-empty-icon">🗺️</div>
              <p>No tenants with resources found.</p>
            </div>
          ) : (
            <>
              <div className="th-heatmap-legend">
                <span
                  className="th-heatmap-legend-swatch"
                  style={{ background: "#ef4444" }}
                />
                <span className="th-heatmap-legend-label">Low</span>
                <span
                  className="th-heatmap-legend-swatch"
                  style={{ background: "#f59e0b" }}
                />
                <span
                  className="th-heatmap-legend-swatch"
                  style={{ background: "#84cc16" }}
                />
                <span
                  className="th-heatmap-legend-swatch"
                  style={{ background: "#22c55e" }}
                />
                <span className="th-heatmap-legend-label">High</span>
              </div>
              <div className="th-heatmap-grid">
                {heatmapData.map((t) => {
                  const size = Math.max(
                    90,
                    Math.min(200, 90 + t.total_servers * 15)
                  );
                  return (
                    <div
                      key={t.project_id}
                      className="th-heatmap-tile"
                      style={{
                        width: size,
                        height: size,
                        background: heatColor(t.utilization_score),
                      }}
                      onClick={() => openDetail(t.project_id)}
                      title={`${t.project_name}: ${t.total_servers} VMs, ${t.active_servers} active, ${t.total_vcpus} vCPUs, ${fmtRam(t.total_ram_mb)} RAM, Util: ${t.utilization_score}%`}
                    >
                      <div className="th-heatmap-tile-name">
                        {t.project_name}
                      </div>
                      <div className="th-heatmap-tile-stats">
                        {t.total_servers} VMs · {t.active_servers} on
                      </div>
                      <div className="th-heatmap-tile-stats">
                        {t.total_vcpus} vCPU · {fmtRam(t.total_ram_mb)}
                      </div>
                      <div className="th-heatmap-tile-score">
                        {t.utilization_score}%
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Detail Panel ── */}
      {selectedId && (
        <div className="th-detail-overlay" onClick={closeDetail}>
          <div
            className="th-detail-panel"
            onClick={(e) => e.stopPropagation()}
          >
            {detailLoading && (
              <div className="th-loading">Loading tenant details…</div>
            )}
            {!detailLoading && detail && (
              <DetailContent
                detail={detail}
                quota={quota}
                quotaLoading={quotaLoading}
                onClose={closeDetail}
              />
            )}
            {!detailLoading && !detail && (
              <div className="th-empty">
                <p>Could not load details.</p>
                <button className="th-btn" onClick={closeDetail}>
                  Close
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────── */
/*  Quota Bar                                                   */
/* ──────────────────────────────────────────────────────────── */

function QuotaBar({ label, res }: { label: string; res: QuotaResource }) {
  const used = res.in_use + res.reserved;
  const limit = res.limit;
  const unlimited = limit <= 0;
  const usedPct = unlimited ? 0 : Math.min(100, (used / limit) * 100);
  const cls =
    usedPct >= 90 ? "critical" : usedPct >= 70 ? "warning" : "healthy";
  return (
    <div className="th-quota-item">
      <div className="th-quota-label">
        <span>{label}</span>
        <span>
          {used}
          {unlimited ? "" : ` / ${limit}`}
          {unlimited ? " (unlimited)" : ""}
        </span>
      </div>
      {!unlimited && (
        <div className="th-quota-bar">
          <div
            className={`th-quota-fill th-quota-${cls}`}
            style={{ width: `${usedPct}%` }}
          />
        </div>
      )}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────── */
/*  Detail Content                                              */
/* ──────────────────────────────────────────────────────────── */

function DetailContent({
  detail,
  quota,
  quotaLoading,
  onClose,
}: {
  detail: TenantDetail;
  quota: QuotaData | null;
  quotaLoading: boolean;
  onClose: () => void;
}) {
  const t = detail.tenant;
  const cls = scoreClass(t.health_score);

  return (
    <>
      {/* Header */}
      <div className="th-detail-header">
        <h3>{t.project_name}</h3>
        <button className="th-detail-close" onClick={onClose}>
          ✕
        </button>
      </div>

      {/* Score hero */}
      <div className="th-detail-score-hero">
        <div className={`th-detail-score-circle th-score-${cls}`}>
          {t.health_score}
        </div>
        <div className="th-detail-score-info">
          <h4>
            {cls === "healthy"
              ? "Healthy"
              : cls === "warning"
              ? "Needs Attention"
              : "Critical Issues"}
          </h4>
          <p>
            Domain: <strong>{t.domain_name}</strong> &nbsp;|&nbsp; Power-On:{" "}
            <strong>{t.power_on_pct}%</strong> &nbsp;|&nbsp; Hypervisors:{" "}
            <strong>{t.hypervisor_count}</strong>
          </p>
          <p style={{ fontSize: "0.75rem", opacity: 0.7 }}>{t.project_id}</p>
        </div>
      </div>

      {/* ── Compute & Resource Grid ── */}
      <div className="th-detail-section">
        <h4>📊 Resource Summary</h4>
        <div className="th-detail-grid">
          <div className="th-detail-stat">
            <div className="th-stat-value">{t.total_servers}</div>
            <div className="th-stat-label">Servers</div>
            <div className="th-stat-sub">
              {t.active_servers} on · {t.shutoff_servers} off · {t.error_servers}{" "}
              err
            </div>
          </div>
          <div className="th-detail-stat">
            <div className="th-stat-value">{t.total_vcpus}</div>
            <div className="th-stat-label">vCPUs</div>
            <div className="th-stat-sub">{t.active_vcpus} active</div>
          </div>
          <div className="th-detail-stat">
            <div className="th-stat-value">{fmtRam(t.total_ram_mb)}</div>
            <div className="th-stat-label">RAM</div>
            <div className="th-stat-sub">{fmtRam(t.active_ram_mb)} active</div>
          </div>
          <div className="th-detail-stat">
            <div className="th-stat-value">{t.total_flavor_disk_gb} GB</div>
            <div className="th-stat-label">Flavor Disk</div>
          </div>
          <div className="th-detail-stat">
            <div className="th-stat-value">{t.total_volumes}</div>
            <div className="th-stat-label">Volumes</div>
            <div className="th-stat-sub">{t.total_volume_gb} GB total</div>
          </div>
          <div className="th-detail-stat">
            <div className="th-stat-value">{t.total_networks}</div>
            <div className="th-stat-label">Networks</div>
            <div className="th-stat-sub">{t.total_subnets} subnets</div>
          </div>
          <div className="th-detail-stat">
            <div className="th-stat-value">{t.total_floating_ips}</div>
            <div className="th-stat-label">Floating IPs</div>
            <div className="th-stat-sub">
              {t.active_fips} active · {t.down_fips} down
            </div>
          </div>
          <div className="th-detail-stat">
            <div className="th-stat-value">{t.total_ports}</div>
            <div className="th-stat-label">Ports</div>
          </div>
          <div className="th-detail-stat">
            <div className="th-stat-value">{t.total_security_groups}</div>
            <div className="th-stat-label">Security Groups</div>
          </div>
          <div className="th-detail-stat">
            <div className="th-stat-value">{t.total_snapshots}</div>
            <div className="th-stat-label">Snapshots</div>
            <div className="th-stat-sub">{t.total_snapshot_gb} GB</div>
          </div>
          <div className="th-detail-stat">
            <div
              className="th-stat-value"
              style={{
                color:
                  t.compliance_pct >= 90
                    ? "#22c55e"
                    : t.compliance_pct >= 60
                    ? "#f59e0b"
                    : "#ef4444",
              }}
            >
              {t.total_compliance_items > 0 ? `${t.compliance_pct}%` : "N/A"}
            </div>
            <div className="th-stat-label">Compliance</div>
            <div className="th-stat-sub">
              {t.compliant_items}/{t.total_compliance_items}
            </div>
          </div>
        </div>
      </div>

      {/* ── VM Power State ── */}
      {t.total_servers > 0 && (
        <div className="th-detail-section">
          <h4>🖥️ VM Power State</h4>
          <div className="th-power-grid">
            <div className="th-power-item th-power-active">
              <div className="th-power-value">{t.active_servers}</div>
              <div className="th-power-label">Powered On</div>
            </div>
            <div className="th-power-item th-power-shutoff">
              <div className="th-power-value">{t.shutoff_servers}</div>
              <div className="th-power-label">Powered Off</div>
            </div>
            <div className="th-power-item th-power-error">
              <div className="th-power-value">{t.error_servers}</div>
              <div className="th-power-label">Error</div>
            </div>
            <div className="th-power-item th-power-other">
              <div className="th-power-value">{t.other_servers}</div>
              <div className="th-power-label">Other</div>
            </div>
          </div>
          <div className="th-status-bar" style={{ marginTop: 10 }}>
            {t.active_servers > 0 && (
              <div
                className="th-status-segment th-seg-active"
                style={{
                  width: `${pct(t.active_servers, t.total_servers)}%`,
                }}
              >
                {pct(t.active_servers, t.total_servers)}%
              </div>
            )}
            {t.shutoff_servers > 0 && (
              <div
                className="th-status-segment th-seg-shutoff"
                style={{
                  width: `${pct(t.shutoff_servers, t.total_servers)}%`,
                }}
              >
                {pct(t.shutoff_servers, t.total_servers)}%
              </div>
            )}
            {t.error_servers > 0 && (
              <div
                className="th-status-segment th-seg-error"
                style={{
                  width: `${pct(t.error_servers, t.total_servers)}%`,
                }}
              >
                {pct(t.error_servers, t.total_servers)}%
              </div>
            )}
            {t.other_servers > 0 && (
              <div
                className="th-status-segment th-seg-other"
                style={{
                  width: `${pct(t.other_servers, t.total_servers)}%`,
                }}
              >
                {pct(t.other_servers, t.total_servers)}%
              </div>
            )}
          </div>
          <div className="th-status-legend">
            <span>
              <span className="th-legend-dot" style={{ background: "#22c55e" }} />{" "}
              Active ({t.active_servers})
            </span>
            <span>
              <span className="th-legend-dot" style={{ background: "#94a3b8" }} />{" "}
              Shutoff ({t.shutoff_servers})
            </span>
            <span>
              <span className="th-legend-dot" style={{ background: "#ef4444" }} />{" "}
              Error ({t.error_servers})
            </span>
            <span>
              <span className="th-legend-dot" style={{ background: "#a78bfa" }} />{" "}
              Other ({t.other_servers})
            </span>
          </div>
        </div>
      )}

      {/* ── Volume Status ── */}
      {t.total_volumes > 0 && (
        <div className="th-detail-section">
          <h4>💾 Volume Status</h4>
          <div className="th-status-bar">
            {t.in_use_volumes > 0 && (
              <div
                className="th-status-segment th-seg-in-use"
                style={{
                  width: `${pct(t.in_use_volumes, t.total_volumes)}%`,
                }}
              >
                {t.in_use_volumes}
              </div>
            )}
            {t.available_volumes > 0 && (
              <div
                className="th-status-segment th-seg-available"
                style={{
                  width: `${pct(t.available_volumes, t.total_volumes)}%`,
                }}
              >
                {t.available_volumes}
              </div>
            )}
            {t.error_volumes > 0 && (
              <div
                className="th-status-segment th-seg-error"
                style={{
                  width: `${pct(t.error_volumes, t.total_volumes)}%`,
                }}
              >
                {t.error_volumes}
              </div>
            )}
            {t.other_volumes > 0 && (
              <div
                className="th-status-segment th-seg-other"
                style={{
                  width: `${pct(t.other_volumes, t.total_volumes)}%`,
                }}
              >
                {t.other_volumes}
              </div>
            )}
          </div>
          <div className="th-status-legend">
            <span>
              <span className="th-legend-dot" style={{ background: "#3b82f6" }} />{" "}
              In Use ({t.in_use_volumes})
            </span>
            <span>
              <span className="th-legend-dot" style={{ background: "#22c55e" }} />{" "}
              Available ({t.available_volumes})
            </span>
            <span>
              <span className="th-legend-dot" style={{ background: "#ef4444" }} />{" "}
              Error ({t.error_volumes})
            </span>
          </div>
        </div>
      )}

      {/* ── Quota vs Usage ── */}
      <div className="th-detail-section">
        <h4>📈 Quota vs Usage</h4>
        {quotaLoading && (
          <div className="th-loading" style={{ padding: "12px 0" }}>
            Loading quota…
          </div>
        )}
        {!quotaLoading &&
          quota &&
          quota.available &&
          quota.compute &&
          quota.storage && (
            <div className="th-quota-grid">
              <div className="th-quota-group">
                <div className="th-quota-group-title">Compute</div>
                <QuotaBar label="Instances" res={quota.compute.instances} />
                <QuotaBar label="vCPUs" res={quota.compute.cores} />
                <QuotaBar label="RAM (MB)" res={quota.compute.ram_mb} />
              </div>
              <div className="th-quota-group">
                <div className="th-quota-group-title">Storage</div>
                <QuotaBar label="Volumes" res={quota.storage.volumes} />
                <QuotaBar label="Gigabytes" res={quota.storage.gigabytes} />
                <QuotaBar label="Snapshots" res={quota.storage.snapshots} />
              </div>
            </div>
          )}
        {!quotaLoading && quota && !quota.available && (
          <p
            style={{
              color: "var(--color-text-secondary, #64748b)",
              fontSize: "0.85rem",
            }}
          >
            Quota data unavailable:{" "}
            {quota.reason || "OpenStack credentials not configured"}
          </p>
        )}
        {!quotaLoading && !quota && (
          <p
            style={{
              color: "var(--color-text-secondary, #64748b)",
              fontSize: "0.85rem",
            }}
          >
            Quota data not loaded.
          </p>
        )}
      </div>

      {/* ── Top Volumes ── */}
      {detail.top_volumes.length > 0 && (
        <div className="th-detail-section">
          <h4>📦 Top Volumes by Size</h4>
          <table className="th-drift-mini">
            <thead>
              <tr>
                <th>Name</th>
                <th>Size (GB)</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {detail.top_volumes.map((v) => (
                <tr key={v.id}>
                  <td>{v.name || v.id}</td>
                  <td>{v.size_gb}</td>
                  <td>{v.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Drift Events ── */}
      <div className="th-detail-section">
        <h4>🔍 Drift Activity (30 days)</h4>
        {t.total_drift_events === 0 ? (
          <p
            style={{
              color: "var(--color-text-secondary, #64748b)",
              fontSize: "0.85rem",
            }}
          >
            No drift events detected.
          </p>
        ) : (
          <>
            <div
              style={{
                marginBottom: 8,
                fontSize: "0.85rem",
                color: "var(--color-text-secondary, #64748b)",
              }}
            >
              Last 7 days: <strong>{t.drift_7d}</strong> &nbsp;|&nbsp; Last 30
              days: <strong>{t.drift_30d}</strong> &nbsp;|&nbsp; Unacknowledged:{" "}
              <strong>{t.new_drift}</strong>
            </div>
            {detail.recent_drift_events.length > 0 && (
              <table className="th-drift-mini">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Resource</th>
                    <th>Field</th>
                    <th>Change</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.recent_drift_events.slice(0, 10).map((e) => (
                    <tr key={e.id}>
                      <td>
                        <span className={`th-sev th-sev-${e.severity}`}>
                          {e.severity}
                        </span>
                      </td>
                      <td>{e.resource_name}</td>
                      <td>{e.field_changed}</td>
                      <td>
                        <span
                          style={{
                            textDecoration: "line-through",
                            opacity: 0.6,
                          }}
                        >
                          {e.old_value}
                        </span>
                        {" → "}
                        <strong>{e.new_value}</strong>
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {fmtDate(e.detected_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    </>
  );
}
