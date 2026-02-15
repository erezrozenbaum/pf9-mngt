/**
 * Snapshot Restore Audit Tab
 *
 * Full audit / compliance view for all restore operations:
 *   - Searchable, filterable, paginated table of restore jobs
 *   - Expandable rows with step-level drill-down
 *   - Result / failure details
 *   - Duration calculation
 *   - CSV export
 *   - Auto-refresh for running jobs
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE } from "../config";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RestoreJob {
  id: string;
  created_by: string;
  executed_by: string | null;
  project_id: string;
  project_name: string | null;
  vm_id: string;
  vm_name: string | null;
  restore_point_id: string;
  restore_point_name: string | null;
  mode: string;
  ip_strategy: string;
  requested_name: string | null;
  boot_mode: string;
  status: string;
  failure_reason: string | null;
  result_json: Record<string, any> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

interface RestoreJobDetail extends RestoreJob {
  plan_json: Record<string, any>;
  last_heartbeat: string | null;
  canceled_at: string | null;
  steps: RestoreStep[];
  progress: {
    total_steps: number;
    completed_steps: number;
    current_step: string | null;
    percent: number;
  };
}

interface RestoreStep {
  id: number;
  job_id: string;
  step_order: number;
  step_name: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  details_json: Record<string, any> | null;
  error_text: string | null;
  created_at: string;
}

interface JobsResponse {
  total: number;
  jobs: RestoreJob[];
  limit: number;
  offset: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getToken(): string | null {
  return localStorage.getItem("auth_token");
}

async function apiFetch<T>(path: string): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDateShort(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB") + " " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const sec = Math.floor((e - s) / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const remSec = sec % 60;
  if (min < 60) return `${min}m ${remSec}s`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return `${hr}h ${remMin}m`;
}

function statusColor(status: string): string {
  switch (status) {
    case "SUCCEEDED": return "#4caf50";
    case "FAILED": return "#f44336";
    case "RUNNING": return "#2196f3";
    case "PENDING": return "#ff9800";
    case "PLANNED": return "#9e9e9e";
    case "CANCELED": return "#795548";
    case "INTERRUPTED": return "#e91e63";
    default: return "#666";
  }
}

function stepStatusIcon(status: string): string {
  switch (status) {
    case "SUCCEEDED": return "✅";
    case "FAILED": return "❌";
    case "RUNNING": return "⏳";
    case "PENDING": return "⏸️";
    case "SKIPPED": return "⏭️";
    default: return "•";
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const SnapshotRestoreAudit: React.FC = () => {
  // Data
  const [jobs, setJobs] = useState<RestoreJob[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(0);
  const pageSize = 25;

  // Expanded job detail
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [jobDetail, setJobDetail] = useState<RestoreJobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Auto-refresh
  const [autoRefresh, setAutoRefresh] = useState(true);
  const refreshRef = useRef<number | null>(null);

  // Debounce search
  const searchTimerRef = useRef<number | null>(null);
  const [debouncedSearch, setDebouncedSearch] = useState("");

  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = window.setTimeout(() => {
      setDebouncedSearch(search);
      setPage(0);
    }, 400);
    return () => { if (searchTimerRef.current) clearTimeout(searchTimerRef.current); };
  }, [search]);

  // -----------------------------------------------------------------------
  // Load jobs
  // -----------------------------------------------------------------------
  const loadJobs = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String(page * pageSize));
      if (debouncedSearch) params.set("search", debouncedSearch);
      if (statusFilter) params.set("status", statusFilter);
      if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
      if (dateTo) {
        // End of selected day
        const d = new Date(dateTo);
        d.setHours(23, 59, 59, 999);
        params.set("date_to", d.toISOString());
      }
      const res = await apiFetch<JobsResponse>(`/restore/jobs?${params.toString()}`);
      setJobs(res.jobs || []);
      setTotal(res.total);
    } catch (e: any) {
      if (!silent) setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, debouncedSearch, statusFilter, dateFrom, dateTo]);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  // Auto-refresh every 10s if there are running jobs
  useEffect(() => {
    if (refreshRef.current) clearInterval(refreshRef.current);
    if (autoRefresh) {
      refreshRef.current = window.setInterval(() => {
        const hasRunning = jobs.some(j => j.status === "RUNNING" || j.status === "PENDING");
        if (hasRunning) loadJobs(true);
      }, 10000);
    }
    return () => { if (refreshRef.current) clearInterval(refreshRef.current); };
  }, [autoRefresh, jobs, loadJobs]);

  // -----------------------------------------------------------------------
  // Load job detail (steps)
  // -----------------------------------------------------------------------
  const loadJobDetail = useCallback(async (jobId: string) => {
    setDetailLoading(true);
    try {
      const detail = await apiFetch<RestoreJobDetail>(`/restore/jobs/${jobId}`);
      setJobDetail(detail);
    } catch (e: any) {
      console.error("Failed to load job detail:", e);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const toggleExpand = (jobId: string) => {
    if (expandedJobId === jobId) {
      setExpandedJobId(null);
      setJobDetail(null);
    } else {
      setExpandedJobId(jobId);
      loadJobDetail(jobId);
    }
  };

  // -----------------------------------------------------------------------
  // CSV Export
  // -----------------------------------------------------------------------
  const exportCSV = () => {
    const headers = [
      "ID", "Status", "VM Name", "VM ID", "Project", "Mode", "IP Strategy",
      "Boot Mode", "Snapshot", "Requested Name", "Created By", "Created At",
      "Started At", "Finished At", "Duration", "Failure Reason",
      "New Server ID", "New IPs"
    ];

    const rows = jobs.map(j => [
      j.id,
      j.status,
      j.vm_name || "",
      j.vm_id,
      j.project_name || "",
      j.mode,
      j.ip_strategy,
      j.boot_mode,
      j.restore_point_name || j.restore_point_id,
      j.requested_name || "",
      j.created_by,
      j.created_at,
      j.started_at || "",
      j.finished_at || "",
      formatDuration(j.started_at, j.finished_at),
      j.failure_reason || "",
      j.result_json?.new_server_id || "",
      j.result_json?.new_ips ? JSON.stringify(j.result_json.new_ips) : "",
    ]);

    const csvContent = [headers, ...rows]
      .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(","))
      .join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `restore_audit_${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  // -----------------------------------------------------------------------
  // Pagination
  // -----------------------------------------------------------------------
  const totalPages = Math.ceil(total / pageSize);

  // -----------------------------------------------------------------------
  // Stats summary
  // -----------------------------------------------------------------------
  const stats = {
    total,
    succeeded: jobs.filter(j => j.status === "SUCCEEDED").length,
    failed: jobs.filter(j => j.status === "FAILED").length,
    running: jobs.filter(j => j.status === "RUNNING" || j.status === "PENDING").length,
  };

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <div className="restore-audit">
      {/* Header */}
      <div className="restore-audit-header">
        <div>
          <h2 style={{ margin: 0 }}>Snapshot Restore Audit Trail</h2>
          <p style={{ margin: "4px 0 0 0", color: "var(--pf9-text-muted, #888)", fontSize: "0.9rem" }}>
            Full history of all restore operations with step-level detail
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label style={{ fontSize: "0.85rem", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
            Auto-refresh
          </label>
          <button onClick={() => loadJobs()} className="restore-audit-btn restore-audit-btn-secondary">
            🔄 Refresh
          </button>
          <button onClick={exportCSV} disabled={jobs.length === 0} className="restore-audit-btn restore-audit-btn-primary">
            📥 Export CSV
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="restore-audit-stats">
        <div className="restore-audit-stat-card">
          <div className="restore-audit-stat-value">{total}</div>
          <div className="restore-audit-stat-label">Total Jobs</div>
        </div>
        <div className="restore-audit-stat-card" style={{ borderLeft: "3px solid #4caf50" }}>
          <div className="restore-audit-stat-value" style={{ color: "#4caf50" }}>{stats.succeeded}</div>
          <div className="restore-audit-stat-label">Succeeded</div>
        </div>
        <div className="restore-audit-stat-card" style={{ borderLeft: "3px solid #f44336" }}>
          <div className="restore-audit-stat-value" style={{ color: "#f44336" }}>{stats.failed}</div>
          <div className="restore-audit-stat-label">Failed</div>
        </div>
        <div className="restore-audit-stat-card" style={{ borderLeft: "3px solid #2196f3" }}>
          <div className="restore-audit-stat-value" style={{ color: "#2196f3" }}>{stats.running}</div>
          <div className="restore-audit-stat-label">In Progress</div>
        </div>
      </div>

      {/* Filters */}
      <div className="restore-audit-filters">
        <input
          type="text"
          placeholder="🔍 Search VM name, project, user..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="restore-audit-search"
        />
        <select
          value={statusFilter}
          onChange={e => { setStatusFilter(e.target.value); setPage(0); }}
          className="restore-audit-select"
        >
          <option value="">All Statuses</option>
          <option value="SUCCEEDED">✅ Succeeded</option>
          <option value="FAILED">❌ Failed</option>
          <option value="RUNNING">⏳ Running</option>
          <option value="PENDING">⏸️ Pending</option>
          <option value="PLANNED">📋 Planned</option>
          <option value="CANCELED">🚫 Canceled</option>
          <option value="INTERRUPTED">⚠️ Interrupted</option>
        </select>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <label style={{ fontSize: "0.85rem", color: "var(--pf9-text-muted, #888)" }}>From:</label>
          <input
            type="date"
            value={dateFrom}
            onChange={e => { setDateFrom(e.target.value); setPage(0); }}
            className="restore-audit-date"
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <label style={{ fontSize: "0.85rem", color: "var(--pf9-text-muted, #888)" }}>To:</label>
          <input
            type="date"
            value={dateTo}
            onChange={e => { setDateTo(e.target.value); setPage(0); }}
            className="restore-audit-date"
          />
        </div>
        {(search || statusFilter || dateFrom || dateTo) && (
          <button
            onClick={() => { setSearch(""); setStatusFilter(""); setDateFrom(""); setDateTo(""); setPage(0); }}
            className="restore-audit-btn restore-audit-btn-ghost"
          >
            ✕ Clear
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="restore-audit-error">
          {error.includes("503") ? (
            <>🔒 Restore feature is not enabled. Set <code>RESTORE_ENABLED=true</code> in <code>.env</code> and restart.</>
          ) : (
            <>⚠️ {error}</>
          )}
        </div>
      )}

      {/* Loading */}
      {loading && <div className="restore-audit-loading">Loading restore jobs...</div>}

      {/* Table */}
      {!loading && !error && (
        <>
          {jobs.length === 0 ? (
            <div className="restore-audit-empty">
              <span style={{ fontSize: "2rem" }}>📋</span>
              <p>No restore jobs found{(search || statusFilter || dateFrom || dateTo) ? " matching your filters" : ""}.</p>
              {!search && !statusFilter && !dateFrom && !dateTo && (
                <p style={{ color: "var(--pf9-text-muted, #888)", fontSize: "0.85rem" }}>
                  Restore jobs will appear here after using the Snapshot Restore wizard.
                </p>
              )}
            </div>
          ) : (
            <div className="restore-audit-table-wrapper">
              <table className="restore-audit-table">
                <thead>
                  <tr>
                    <th style={{ width: 32 }}></th>
                    <th>Status</th>
                    <th>VM Name</th>
                    <th>Project</th>
                    <th>Mode</th>
                    <th>Snapshot</th>
                    <th>Created By</th>
                    <th>Created At</th>
                    <th>Duration</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map(j => (
                    <React.Fragment key={j.id}>
                      {/* Main Row */}
                      <tr
                        className={`restore-audit-row ${expandedJobId === j.id ? "restore-audit-row-expanded" : ""}`}
                        onClick={() => toggleExpand(j.id)}
                      >
                        <td style={{ textAlign: "center", cursor: "pointer" }}>
                          <span style={{ transition: "transform 0.2s", display: "inline-block", transform: expandedJobId === j.id ? "rotate(90deg)" : "none" }}>
                            ▶
                          </span>
                        </td>
                        <td>
                          <span
                            className="restore-audit-badge"
                            style={{ background: statusColor(j.status), color: "#fff" }}
                          >
                            {j.status}
                          </span>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{j.vm_name || "—"}</div>
                          <div style={{ fontSize: "0.75rem", color: "var(--pf9-text-muted, #999)" }}>{j.vm_id.substring(0, 8)}…</div>
                        </td>
                        <td>{j.project_name || j.project_id.substring(0, 8) + "…"}</td>
                        <td>
                          <span className="restore-audit-mode-badge">{j.mode}</span>
                          <div style={{ fontSize: "0.75rem", color: "var(--pf9-text-muted, #999)" }}>{j.ip_strategy.replace(/_/g, " ")}</div>
                        </td>
                        <td>
                          <div>{j.restore_point_name || "—"}</div>
                          <div style={{ fontSize: "0.75rem", color: "var(--pf9-text-muted, #999)" }}>{j.restore_point_id.substring(0, 8)}…</div>
                        </td>
                        <td>{j.created_by}</td>
                        <td>{formatDateShort(j.created_at)}</td>
                        <td>
                          <span style={{ fontFamily: "monospace", fontSize: "0.85rem" }}>
                            {formatDuration(j.started_at, j.finished_at)}
                          </span>
                          {(j.status === "RUNNING" || j.status === "PENDING") && (
                            <span className="restore-audit-pulse" title="In progress"> ●</span>
                          )}
                        </td>
                        <td>
                          {j.status === "SUCCEEDED" && j.result_json?.new_server_id && (
                            <span style={{ color: "#4caf50", fontSize: "0.8rem" }}>
                              🖥️ {j.requested_name || j.result_json.new_server_id.substring(0, 8) + "…"}
                            </span>
                          )}
                          {j.status === "FAILED" && j.failure_reason && (
                            <span style={{ color: "#f44336", fontSize: "0.8rem" }} title={j.failure_reason}>
                              ❌ {j.failure_reason.substring(0, 40)}{j.failure_reason.length > 40 ? "…" : ""}
                            </span>
                          )}
                          {j.status === "CANCELED" && (
                            <span style={{ color: "#795548", fontSize: "0.8rem" }}>🚫 Canceled</span>
                          )}
                        </td>
                      </tr>

                      {/* Expanded Detail Row */}
                      {expandedJobId === j.id && (
                        <tr className="restore-audit-detail-row">
                          <td colSpan={10}>
                            {detailLoading ? (
                              <div style={{ padding: 20, textAlign: "center", color: "#888" }}>Loading details...</div>
                            ) : jobDetail ? (
                              <div className="restore-audit-detail">
                                {/* Detail Grid */}
                                <div className="restore-audit-detail-grid">
                                  <div className="restore-audit-detail-section">
                                    <h4>Job Information</h4>
                                    <dl>
                                      <dt>Job ID</dt>
                                      <dd><code>{jobDetail.id}</code></dd>
                                      <dt>Created By</dt>
                                      <dd>{jobDetail.created_by}</dd>
                                      <dt>Executed By</dt>
                                      <dd>{jobDetail.executed_by || "—"}</dd>
                                      <dt>Mode</dt>
                                      <dd>{jobDetail.mode} ({jobDetail.boot_mode})</dd>
                                      <dt>IP Strategy</dt>
                                      <dd>{jobDetail.ip_strategy.replace(/_/g, " ")}</dd>
                                      <dt>Requested Name</dt>
                                      <dd>{jobDetail.requested_name || "—"}</dd>
                                    </dl>
                                  </div>

                                  <div className="restore-audit-detail-section">
                                    <h4>Timeline</h4>
                                    <dl>
                                      <dt>Created</dt>
                                      <dd>{formatDate(jobDetail.created_at)}</dd>
                                      <dt>Started</dt>
                                      <dd>{formatDate(jobDetail.started_at)}</dd>
                                      <dt>Finished</dt>
                                      <dd>{formatDate(jobDetail.finished_at)}</dd>
                                      <dt>Duration</dt>
                                      <dd><strong>{formatDuration(jobDetail.started_at, jobDetail.finished_at)}</strong></dd>
                                      {jobDetail.canceled_at && (
                                        <>
                                          <dt>Canceled</dt>
                                          <dd>{formatDate(jobDetail.canceled_at)}</dd>
                                        </>
                                      )}
                                    </dl>
                                  </div>

                                  <div className="restore-audit-detail-section">
                                    <h4>Source</h4>
                                    <dl>
                                      <dt>VM</dt>
                                      <dd>{jobDetail.vm_name || "—"} <span style={{ color: "#999", fontSize: "0.8rem" }}>({jobDetail.vm_id})</span></dd>
                                      <dt>Project</dt>
                                      <dd>{jobDetail.project_name || "—"} <span style={{ color: "#999", fontSize: "0.8rem" }}>({jobDetail.project_id})</span></dd>
                                      <dt>Restore Point</dt>
                                      <dd>{jobDetail.restore_point_name || "—"} <span style={{ color: "#999", fontSize: "0.8rem" }}>({jobDetail.restore_point_id})</span></dd>
                                    </dl>
                                  </div>

                                  {/* Result or Failure */}
                                  {jobDetail.status === "SUCCEEDED" && jobDetail.result_json && (
                                    <div className="restore-audit-detail-section restore-audit-result-success">
                                      <h4>✅ Result</h4>
                                      <dl>
                                        {jobDetail.result_json.new_server_id && (
                                          <>
                                            <dt>New Server ID</dt>
                                            <dd><code>{jobDetail.result_json.new_server_id}</code></dd>
                                          </>
                                        )}
                                        {jobDetail.result_json.new_volume_id && (
                                          <>
                                            <dt>New Volume ID</dt>
                                            <dd><code>{jobDetail.result_json.new_volume_id}</code></dd>
                                          </>
                                        )}
                                        {jobDetail.result_json.new_ips && (
                                          <>
                                            <dt>New IPs</dt>
                                            <dd>
                                              {Array.isArray(jobDetail.result_json.new_ips)
                                                ? jobDetail.result_json.new_ips.join(", ")
                                                : JSON.stringify(jobDetail.result_json.new_ips)}
                                            </dd>
                                          </>
                                        )}
                                        {jobDetail.result_json.new_port_ids && (
                                          <>
                                            <dt>New Port IDs</dt>
                                            <dd style={{ fontSize: "0.8rem" }}>
                                              {jobDetail.result_json.new_port_ids.join(", ")}
                                            </dd>
                                          </>
                                        )}
                                      </dl>
                                    </div>
                                  )}

                                  {jobDetail.status === "FAILED" && jobDetail.failure_reason && (
                                    <div className="restore-audit-detail-section restore-audit-result-failure">
                                      <h4>❌ Failure</h4>
                                      <pre className="restore-audit-error-pre">{jobDetail.failure_reason}</pre>
                                    </div>
                                  )}
                                </div>

                                {/* Steps Timeline */}
                                {jobDetail.steps && jobDetail.steps.length > 0 && (
                                  <div className="restore-audit-steps">
                                    <h4>
                                      Execution Steps
                                      <span style={{ fontWeight: 400, fontSize: "0.85rem", marginLeft: 8, color: "#888" }}>
                                        ({jobDetail.progress.completed_steps}/{jobDetail.progress.total_steps} completed
                                        {jobDetail.progress.current_step ? ` — current: ${jobDetail.progress.current_step}` : ""})
                                      </span>
                                    </h4>

                                    {/* Progress bar */}
                                    <div className="restore-audit-progress-bar">
                                      <div
                                        className="restore-audit-progress-fill"
                                        style={{
                                          width: `${jobDetail.progress.percent}%`,
                                          background: jobDetail.status === "FAILED" ? "#f44336" : jobDetail.status === "SUCCEEDED" ? "#4caf50" : "#2196f3"
                                        }}
                                      />
                                    </div>

                                    <div className="restore-audit-steps-list">
                                      {jobDetail.steps.map((step, idx) => (
                                        <div key={step.id} className={`restore-audit-step ${step.status === "RUNNING" ? "restore-audit-step-active" : ""}`}>
                                          <div className="restore-audit-step-icon">{stepStatusIcon(step.status)}</div>
                                          <div className="restore-audit-step-content">
                                            <div className="restore-audit-step-header">
                                              <span className="restore-audit-step-name">
                                                {idx + 1}. {step.step_name.replace(/_/g, " ")}
                                              </span>
                                              <span className="restore-audit-step-time">
                                                {step.started_at && step.finished_at
                                                  ? formatDuration(step.started_at, step.finished_at)
                                                  : step.status === "RUNNING"
                                                    ? formatDuration(step.started_at, null) + "…"
                                                    : ""}
                                              </span>
                                            </div>
                                            {step.error_text && (
                                              <div className="restore-audit-step-error">{step.error_text}</div>
                                            )}
                                            {step.details_json && Object.keys(step.details_json).length > 0 && (
                                              <details className="restore-audit-step-details">
                                                <summary>Details</summary>
                                                <pre>{JSON.stringify(step.details_json, null, 2)}</pre>
                                              </details>
                                            )}
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            ) : (
                              <div style={{ padding: 20, textAlign: "center", color: "#888" }}>
                                Failed to load job details.
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="restore-audit-pagination">
              <button
                disabled={page === 0}
                onClick={() => setPage(p => Math.max(0, p - 1))}
                className="restore-audit-btn restore-audit-btn-secondary"
              >
                ← Previous
              </button>
              <span style={{ fontSize: "0.9rem", color: "var(--pf9-text-muted, #888)" }}>
                Page {page + 1} of {totalPages} · {total} total jobs
              </span>
              <button
                disabled={page >= totalPages - 1}
                onClick={() => setPage(p => p + 1)}
                className="restore-audit-btn restore-audit-btn-secondary"
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default SnapshotRestoreAudit;
