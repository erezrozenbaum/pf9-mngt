import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";
import "../styles/RunbooksTab.css";

/* ===================================================================
   RunbooksTab  – Catalogue & Trigger (operator-facing)
   ===================================================================
   Browse available runbooks, view parameters, trigger with dry-run
   support.  Governance features (execution history, approvals,
   approval policies) live in the Admin → Auth Management panel.
*/

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Runbook {
  runbook_id: string;
  name: string;
  display_name: string;
  description: string;
  category: string;
  risk_level: string;
  supports_dry_run: boolean;
  enabled: boolean;
  parameters_schema: Record<string, any>;
}

interface Execution {
  execution_id: string;
  runbook_name: string;
  display_name?: string;
  status: string;
  dry_run: boolean;
  parameters: Record<string, any>;
  result: Record<string, any>;
  triggered_by: string;
  triggered_at: string;
  items_found: number;
  items_actioned: number;
}

interface ExecutionStats {
  runbook_name: string;
  total_executions: number;
  completed: number;
  failed: number;
  pending: number;
  rejected: number;
  total_items_found: number;
  total_items_actioned: number;
  last_run: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getToken(): string | null {
  return localStorage.getItem("auth_token");
}

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

const CATEGORY_ICONS: Record<string, string> = {
  vm: "🖥️",
  network: "🔌",
  security: "🔒",
  quota: "📊",
  diagnostics: "🔍",
  general: "📋",
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function RunbooksTab() {
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [stats, setStats] = useState<ExecutionStats[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: string } | null>(null);

  // Trigger modal state
  const [triggerModal, setTriggerModal] = useState<Runbook | null>(null);
  const [triggerDryRun, setTriggerDryRun] = useState(true);
  const [triggerParams, setTriggerParams] = useState<Record<string, any>>({});
  const [triggering, setTriggering] = useState(false);

  // My Executions state
  const [myExecs, setMyExecs] = useState<Execution[]>([]);
  const [myExecTotal, setMyExecTotal] = useState(0);
  const [myExecPage, setMyExecPage] = useState(0);
  const [myExecFilter, setMyExecFilter] = useState("");
  const [selectedExec, setSelectedExec] = useState<Execution | null>(null);
  const [showMyExecs, setShowMyExecs] = useState(true);

  // ------- Toast helper --------------------------------------------------
  const showToast = useCallback((msg: string, type: string = "info") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  }, []);

  // ------- Data fetching -------------------------------------------------
  const fetchRunbooks = useCallback(async () => {
    try {
      const data = await apiFetch<Runbook[]>("/api/runbooks");
      setRunbooks(data);
    } catch (e: any) {
      console.error("Failed to fetch runbooks:", e);
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const data = await apiFetch<ExecutionStats[]>("/api/runbooks/stats/summary");
      setStats(data);
    } catch (e: any) {
      console.error("Failed to fetch stats:", e);
    }
  }, []);

  const fetchMyExecs = useCallback(async () => {
    try {
      const p = new URLSearchParams();
      if (myExecFilter) p.set("status", myExecFilter);
      p.set("limit", "15");
      p.set("offset", String(myExecPage * 15));
      const data = await apiFetch<{ executions: Execution[]; total: number }>(
        `/api/runbooks/executions/mine?${p}`
      );
      setMyExecs(data.executions);
      setMyExecTotal(data.total);
    } catch (e: any) {
      console.error("Failed to fetch my executions:", e);
    }
  }, [myExecFilter, myExecPage]);

  const fetchExecDetail = useCallback(async (id: string) => {
    try {
      const data = await apiFetch<Execution>(`/api/runbooks/executions/${id}`);
      setSelectedExec(data);
    } catch (e: any) {
      showToast(`Failed to load detail: ${e.message}`, "error");
    }
  }, [showToast]);

  // Initial load
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchRunbooks(), fetchStats(), fetchMyExecs()]).finally(() => setLoading(false));
  }, [fetchRunbooks, fetchStats, fetchMyExecs]);

  // ------- Actions -------------------------------------------------------
  const openTriggerModal = (rb: Runbook) => {
    const defaults: Record<string, any> = {};
    const props = rb.parameters_schema?.properties || {};
    for (const [key, schema] of Object.entries(props) as any) {
      if (schema.default !== undefined) defaults[key] = schema.default;
      else if (schema.type === "string") defaults[key] = "";
      else if (schema.type === "integer") defaults[key] = 0;
      else if (schema.type === "array") defaults[key] = schema.default || [];
    }
    setTriggerParams(defaults);
    setTriggerDryRun(rb.supports_dry_run);
    setTriggerModal(rb);
  };

  const doTrigger = async () => {
    if (!triggerModal) return;
    setTriggering(true);
    try {
      const result = await apiFetch<Execution>("/api/runbooks/trigger", {
        method: "POST",
        body: JSON.stringify({
          runbook_name: triggerModal.name,
          dry_run: triggerDryRun,
          parameters: triggerParams,
        }),
      });
      showToast(
        result.status === "completed"
          ? `✅ ${triggerModal.display_name} completed — ${result.items_found} found, ${result.items_actioned} actioned`
          : result.status === "pending_approval"
          ? `⏳ ${triggerModal.display_name} is awaiting approval`
          : `${triggerModal.display_name}: ${result.status}`,
        result.status === "completed" ? "success" : "info"
      );
      setTriggerModal(null);
      fetchRunbooks();
      fetchStats();
      fetchMyExecs();
    } catch (e: any) {
      showToast(`❌ Trigger failed: ${e.message}`, "error");
    } finally {
      setTriggering(false);
    }
  };

  // ------- Helpers -------------------------------------------------------
  const getStatsFor = (name: string) => stats.find((s) => s.runbook_name === name);

  /** Render execution result in a human-friendly way instead of raw JSON */
  const renderFriendlyResult = (exec: Execution) => {
    const r = exec.result || {};
    const name = exec.runbook_name;

    // ── Stuck VM Remediation ──
    if (name === "stuck_vm_remediation") {
      const vms = r.stuck_vms || [];
      const remediated = r.remediated || [];
      return (
        <div className="rb-result-friendly">
          <p className="rb-result-summary">
            Action: <strong>{r.action || "report_only"}</strong> · Threshold: {r.threshold_minutes || "?"}min
          </p>
          {vms.length === 0 ? <p className="rb-result-empty">No stuck VMs found</p> : (
            <table className="rb-result-table">
              <thead><tr><th>VM Name</th><th>Status</th><th>Tenant</th><th>Host</th><th>Since</th></tr></thead>
              <tbody>
                {vms.map((vm: any) => (
                  <tr key={vm.vm_id}>
                    <td>{vm.vm_name || vm.vm_id}</td>
                    <td><span className={`rb-status-badge ${vm.status === "ERROR" ? "failed" : "pending_approval"}`}>{vm.status}{vm.task_state ? ` (${vm.task_state})` : ""}</span></td>
                    <td>{vm.tenant_name || vm.tenant_id}</td>
                    <td>{vm.host || "—"}</td>
                    <td>{formatDate(vm.updated)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {remediated.length > 0 && (
            <div className="rb-result-sub">
              <h6>Remediated ({remediated.length})</h6>
              <ul>{remediated.map((r: any) => <li key={r.vm_id}>{r.vm_name}: {r.action} → {r.status}</li>)}</ul>
            </div>
          )}
          {(r.errors || []).length > 0 && (
            <div className="rb-result-sub rb-result-errors">
              <h6>Errors ({r.errors.length})</h6>
              <ul>{r.errors.map((e: any, i: number) => <li key={i}>{e.vm_name || e.vm_id}: {e.error}</li>)}</ul>
            </div>
          )}
        </div>
      );
    }

    // ── Orphan Resource Cleanup ──
    if (name === "orphan_resource_cleanup") {
      const orphans = r.orphans || {};
      const deleted = r.deleted || {};
      const errs = r.errors || {};
      return (
        <div className="rb-result-friendly">
          {/* Ports */}
          {(orphans.ports || []).length > 0 && (
            <div className="rb-result-sub">
              <h6>Orphan Ports ({orphans.ports.length}){deleted.ports ? ` · ${deleted.ports.length} deleted` : ""}</h6>
              <table className="rb-result-table">
                <thead><tr><th>Port ID</th><th>Tenant</th><th>MAC</th><th>Created</th></tr></thead>
                <tbody>
                  {orphans.ports.map((p: any) => (
                    <tr key={p.port_id}>
                      <td title={p.port_id}>{p.port_name || p.port_id.slice(0, 8)}…</td>
                      <td>{p.project_name || p.project_id}</td>
                      <td>{p.mac_address}</td>
                      <td>{formatDate(p.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {/* Volumes */}
          {(orphans.volumes || []).length > 0 && (
            <div className="rb-result-sub">
              <h6>Orphan Volumes ({orphans.volumes.length}){deleted.volumes ? ` · ${deleted.volumes.length} deleted` : ""}</h6>
              <table className="rb-result-table">
                <thead><tr><th>Volume Name</th><th>Size</th><th>Tenant</th><th>Created</th></tr></thead>
                <tbody>
                  {orphans.volumes.map((v: any) => (
                    <tr key={v.volume_id}>
                      <td title={v.volume_id}>{v.name || v.volume_id.slice(0, 8)}</td>
                      <td>{v.size_gb} GB</td>
                      <td>{v.project_name || v.project_id}</td>
                      <td>{formatDate(v.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {/* Floating IPs */}
          {(orphans.floating_ips || []).length > 0 && (
            <div className="rb-result-sub">
              <h6>Orphan Floating IPs ({orphans.floating_ips.length}){deleted.floating_ips ? ` · ${deleted.floating_ips.length} deleted` : ""}</h6>
              <table className="rb-result-table">
                <thead><tr><th>Floating IP</th><th>Tenant</th><th>Created</th></tr></thead>
                <tbody>
                  {orphans.floating_ips.map((f: any) => (
                    <tr key={f.fip_id}>
                      <td>{f.floating_ip_address || f.fip_id.slice(0, 8)}</td>
                      <td>{f.project_name || f.project_id}</td>
                      <td>{formatDate(f.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {Object.keys(orphans).length === 0 && <p className="rb-result-empty">No orphaned resources found</p>}
          {/* Errors */}
          {Object.entries(errs).filter(([, v]) => (v as any[]).length > 0).map(([k, v]) => (
            <div className="rb-result-sub rb-result-errors" key={k}>
              <h6>Errors — {k} ({(v as any[]).length})</h6>
              <ul>{(v as any[]).map((e: any, i: number) => <li key={i}>{JSON.stringify(e)}</li>)}</ul>
            </div>
          ))}
        </div>
      );
    }

    // ── Security Group Audit ──
    if (name === "security_group_audit") {
      const violations = r.violations || [];
      return (
        <div className="rb-result-friendly">
          {violations.length === 0 ? <p className="rb-result-empty">No violations found</p> : (
            <table className="rb-result-table">
              <thead><tr><th>Security Group</th><th>Tenant</th><th>Protocol</th><th>Ports</th><th>Source</th><th>Flagged Ports</th></tr></thead>
              <tbody>
                {violations.map((v: any, i: number) => (
                  <tr key={i}>
                    <td>{v.sg_name || v.sg_id}</td>
                    <td>{v.project_name || v.project_id}</td>
                    <td>{v.protocol}</td>
                    <td>{v.port_range}</td>
                    <td>{v.remote_ip_prefix}</td>
                    <td>{(v.flagged_ports || []).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      );
    }

    // ── Quota Threshold Check ──
    if (name === "quota_threshold_check") {
      const alerts = r.alerts || [];
      return (
        <div className="rb-result-friendly">
          <p className="rb-result-summary">Thresholds: ⚠ {r.warning_pct || 80}% · 🔴 {r.critical_pct || 95}%</p>
          {alerts.length === 0 ? <p className="rb-result-empty">All quotas within limits</p> : (
            <table className="rb-result-table">
              <thead><tr><th>Project</th><th>Resource</th><th>Usage</th><th>Limit</th><th>%</th><th>Level</th></tr></thead>
              <tbody>
                {alerts.map((a: any, i: number) => (
                  <tr key={i}>
                    <td>{a.project_name || a.project_id}</td>
                    <td>{a.resource}</td>
                    <td>{a.in_use}</td>
                    <td>{a.limit}</td>
                    <td>{a.utilisation_pct}%</td>
                    <td><span className={`rb-status-badge ${a.level === "critical" ? "failed" : "pending_approval"}`}>{a.level}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      );
    }

    // ── Fallback: raw JSON ──
    return (
      <details className="rb-result-raw">
        <summary>Raw Result</summary>
        <pre>{JSON.stringify(r, null, 2)}</pre>
      </details>
    );
  };

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  if (loading) {
    return (
      <div className="rb-container">
        <div className="rb-loading">
          <div className="rb-spinner" />
          Loading runbooks…
        </div>
      </div>
    );
  }

  return (
    <div className="rb-container">
      {/* Header */}
      <div className="rb-header">
        <h2>📋 Runbooks</h2>
        <p className="rb-subtitle">
          Policy-as-code operational runbooks · select a runbook and trigger with optional dry-run
        </p>
      </div>

      {/* ────── CATALOGUE ────── */}
      <div className="rb-section">
        <div className="rb-grid">
          {runbooks.map((rb) => {
            const st = getStatsFor(rb.name);
            return (
              <div className="rb-card" key={rb.name}>
                <div className="rb-card-header">
                  <h4 className="rb-card-title">
                    {CATEGORY_ICONS[rb.category] || "📋"} {rb.display_name}
                  </h4>
                  <span className={`rb-risk ${rb.risk_level}`}>{rb.risk_level}</span>
                </div>
                <p className="rb-card-desc">{rb.description}</p>
                <div className="rb-card-meta">
                  <span>📁 {rb.category}</span>
                  {rb.supports_dry_run && <span>🧪 Dry-run</span>}
                  {st && <span>▶ {st.total_executions} runs</span>}
                  {st?.last_run && <span>🕐 {formatDate(st.last_run)}</span>}
                </div>
                <div className="rb-card-actions">
                  <button
                    className="rb-btn primary"
                    onClick={() => openTriggerModal(rb)}
                    disabled={!rb.enabled}
                  >
                    ▶ Run
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {runbooks.length === 0 && (
          <div className="rb-empty">
            <div className="rb-empty-icon">📋</div>
            <p>No runbooks configured</p>
          </div>
        )}
      </div>

      {/* ────── MY EXECUTIONS ────── */}
      <div className="rb-section">
        <div className="rb-section-header" onClick={() => setShowMyExecs(!showMyExecs)} style={{ cursor: "pointer" }}>
          <h3>{showMyExecs ? "▾" : "▸"} My Executions</h3>
          <div className="rb-section-controls">
            <select
              className="rb-select"
              value={myExecFilter}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => { setMyExecFilter(e.target.value); setMyExecPage(0); }}
            >
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="pending_approval">Pending Approval</option>
              <option value="rejected">Rejected</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <button className="rb-btn small" onClick={(e) => { e.stopPropagation(); fetchMyExecs(); }}>
              🔄 Refresh
            </button>
            <span className="rb-meta">{myExecTotal} total</span>
          </div>
        </div>

        {showMyExecs && (
          <>
            {/* Detail panel */}
            {selectedExec && (
              <div className="rb-detail-panel">
                <div className="rb-detail-header">
                  <h4>{selectedExec.display_name || selectedExec.runbook_name} — Execution Detail</h4>
                  <button className="rb-btn small" onClick={() => setSelectedExec(null)}>✕ Close</button>
                </div>
                <div className="rb-detail-grid">
                  <div><strong>Status:</strong> <span className={`rb-status-badge ${selectedExec.status}`}>{selectedExec.status}</span></div>
                  <div><strong>Dry Run:</strong> {selectedExec.dry_run ? "Yes 🧪" : "No (live)"}</div>
                  <div><strong>Triggered:</strong> {formatDate(selectedExec.triggered_at)}</div>
                  {selectedExec.completed_at && <div><strong>Completed:</strong> {formatDate(selectedExec.completed_at)}</div>}
                  <div><strong>Items Found:</strong> {selectedExec.items_found}</div>
                  <div><strong>Items Actioned:</strong> {selectedExec.items_actioned}</div>
                  {selectedExec.error_message && (
                    <div className="rb-detail-error"><strong>Error:</strong> {selectedExec.error_message}</div>
                  )}
                </div>

                {/* Friendly result rendering */}
                {selectedExec.result && Object.keys(selectedExec.result).length > 0 && (
                  <div className="rb-result-section">
                    <h5>Results</h5>
                    {renderFriendlyResult(selectedExec)}
                  </div>
                )}
              </div>
            )}

            {/* Table */}
            <div className="rb-exec-table">
              <table>
                <thead>
                  <tr>
                    <th>Runbook</th>
                    <th>Status</th>
                    <th>Dry Run</th>
                    <th>Found</th>
                    <th>Actioned</th>
                    <th>Time</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {myExecs.map((ex) => (
                    <tr key={ex.execution_id}>
                      <td>{ex.display_name || ex.runbook_name}</td>
                      <td><span className={`rb-status-badge ${ex.status}`}>{ex.status}</span></td>
                      <td>{ex.dry_run ? "🧪" : "—"}</td>
                      <td>{ex.items_found}</td>
                      <td>{ex.items_actioned}</td>
                      <td>{formatDate(ex.triggered_at)}</td>
                      <td>
                        <button className="rb-btn small primary" onClick={() => fetchExecDetail(ex.execution_id)}>
                          👁 View
                        </button>
                      </td>
                    </tr>
                  ))}
                  {myExecs.length === 0 && (
                    <tr>
                      <td colSpan={7} className="rb-empty-row">No executions yet — run a runbook above!</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {myExecTotal > 15 && (
              <div className="rb-pagination">
                <button className="rb-btn small" disabled={myExecPage === 0} onClick={() => setMyExecPage(myExecPage - 1)}>
                  ← Prev
                </button>
                <span className="rb-meta">Page {myExecPage + 1} of {Math.ceil(myExecTotal / 15)}</span>
                <button className="rb-btn small" disabled={(myExecPage + 1) * 15 >= myExecTotal} onClick={() => setMyExecPage(myExecPage + 1)}>
                  Next →
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* ────── TRIGGER MODAL ────── */}
      {triggerModal && (
        <div className="rb-modal-overlay" onClick={() => setTriggerModal(null)}>
          <div className="rb-modal" onClick={(e) => e.stopPropagation()}>
            <h3>
              {CATEGORY_ICONS[triggerModal.category] || "📋"} {triggerModal.display_name}
            </h3>
            <p className="rb-modal-desc">{triggerModal.description}</p>

            {/* Render parameters from schema */}
            {Object.entries(triggerModal.parameters_schema?.properties || {}).map(
              ([key, schema]: [string, any]) => (
                <div className="rb-form-group" key={key}>
                  <label>{key.replace(/_/g, " ")}</label>
                  {schema.enum ? (
                    <select
                      value={triggerParams[key] ?? schema.default ?? ""}
                      onChange={(e) => setTriggerParams({ ...triggerParams, [key]: e.target.value })}
                    >
                      {schema.enum.map((v: string) => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  ) : schema.type === "integer" ? (
                    <input
                      type="number"
                      value={triggerParams[key] ?? schema.default ?? 0}
                      onChange={(e) =>
                        setTriggerParams({ ...triggerParams, [key]: parseInt(e.target.value) || 0 })
                      }
                    />
                  ) : (
                    <input
                      type="text"
                      value={triggerParams[key] ?? schema.default ?? ""}
                      onChange={(e) => setTriggerParams({ ...triggerParams, [key]: e.target.value })}
                      placeholder={schema.description || ""}
                    />
                  )}
                  {schema.description && <div className="rb-hint">{schema.description}</div>}
                </div>
              )
            )}

            {triggerModal.supports_dry_run && (
              <div className="rb-checkbox-row">
                <input
                  type="checkbox"
                  id="rb-dryrun"
                  checked={triggerDryRun}
                  onChange={(e) => setTriggerDryRun(e.target.checked)}
                />
                <label htmlFor="rb-dryrun" style={{ fontSize: 14 }}>
                  🧪 Dry Run (scan only, no changes)
                </label>
              </div>
            )}

            <div className="rb-modal-footer">
              <button className="rb-btn" onClick={() => setTriggerModal(null)}>
                Cancel
              </button>
              <button
                className={`rb-btn ${triggerDryRun ? "primary" : "danger"}`}
                onClick={doTrigger}
                disabled={triggering}
              >
                {triggering
                  ? "Running…"
                  : triggerDryRun
                  ? "🧪 Run Dry-Run"
                  : "⚡ Execute Live"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && <div className={`rb-toast ${toast.type}`}>{toast.msg}</div>}
    </div>
  );
}
