import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";
import "../styles/RunbooksTab.css";

/* ===================================================================
   RunbooksTab
   ===================================================================
   Policy-as-Code operational runbooks with:
   - Runbook catalogue (cards with trigger actions)
   - Execution history with full audit trail
   - Approval queue for pending executions
   - Approval policy editor (flexible team → team mapping)
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
  category?: string;
  risk_level?: string;
  status: string;
  dry_run: boolean;
  parameters: Record<string, any>;
  result: Record<string, any>;
  triggered_by: string;
  triggered_at: string;
  approved_by?: string;
  approved_at?: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  items_found: number;
  items_actioned: number;
}

interface ApprovalPolicy {
  policy_id: string;
  runbook_name: string;
  trigger_role: string;
  approver_role: string;
  approval_mode: string;
  escalation_timeout_minutes: number;
  max_auto_executions_per_day: number;
  enabled: boolean;
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

type SubTab = "catalogue" | "history" | "approvals" | "policies";

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
interface Props {
  isAdmin: boolean;
}

export default function RunbooksTab({ isAdmin }: Props) {
  const [subTab, setSubTab] = useState<SubTab>("catalogue");
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [executionTotal, setExecutionTotal] = useState(0);
  const [pendingList, setPendingList] = useState<Execution[]>([]);
  const [policies, setPolicies] = useState<Record<string, ApprovalPolicy[]>>({});
  const [stats, setStats] = useState<ExecutionStats[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: string } | null>(null);

  // Trigger modal state
  const [triggerModal, setTriggerModal] = useState<Runbook | null>(null);
  const [triggerDryRun, setTriggerDryRun] = useState(true);
  const [triggerParams, setTriggerParams] = useState<Record<string, any>>({});
  const [triggering, setTriggering] = useState(false);

  // Detail panel
  const [selectedExecution, setSelectedExecution] = useState<Execution | null>(null);

  // History filters
  const [histRunbook, setHistRunbook] = useState("");
  const [histStatus, setHistStatus] = useState("");
  const [histPage, setHistPage] = useState(0);

  // Policy editor
  const [editPolicy, setEditPolicy] = useState<{
    runbook_name: string;
    trigger_role: string;
    approver_role: string;
    approval_mode: string;
    escalation_timeout_minutes: number;
    max_auto_executions_per_day: number;
  } | null>(null);

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

  const fetchExecutions = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (histRunbook) params.set("runbook_name", histRunbook);
      if (histStatus) params.set("status", histStatus);
      params.set("limit", "25");
      params.set("offset", String(histPage * 25));
      const data = await apiFetch<{ executions: Execution[]; total: number }>(
        `/api/runbooks/executions/history?${params}`
      );
      setExecutions(data.executions);
      setExecutionTotal(data.total);
    } catch (e: any) {
      console.error("Failed to fetch executions:", e);
    }
  }, [histRunbook, histStatus, histPage]);

  const fetchPending = useCallback(async () => {
    try {
      const data = await apiFetch<Execution[]>("/api/runbooks/approvals/pending");
      setPendingList(data);
    } catch (e: any) {
      console.error("Failed to fetch pending:", e);
    }
  }, []);

  const fetchPolicies = useCallback(async () => {
    try {
      const byRunbook: Record<string, ApprovalPolicy[]> = {};
      for (const rb of runbooks) {
        const data = await apiFetch<ApprovalPolicy[]>(`/api/runbooks/policies/${rb.name}`);
        byRunbook[rb.name] = data;
      }
      setPolicies(byRunbook);
    } catch (e: any) {
      console.error("Failed to fetch policies:", e);
    }
  }, [runbooks]);

  // Initial load
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchRunbooks(), fetchStats(), fetchPending()]).finally(() =>
      setLoading(false)
    );
  }, [fetchRunbooks, fetchStats, fetchPending]);

  // Reload when sub-tab changes
  useEffect(() => {
    if (subTab === "history") fetchExecutions();
    if (subTab === "approvals") fetchPending();
    if (subTab === "policies" && runbooks.length) fetchPolicies();
  }, [subTab, fetchExecutions, fetchPending, fetchPolicies, runbooks.length]);

  // ------- Actions -------------------------------------------------------
  const openTriggerModal = (rb: Runbook) => {
    // Initialise params from schema defaults
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
      fetchPending();
      if (subTab === "history") fetchExecutions();
    } catch (e: any) {
      showToast(`❌ Trigger failed: ${e.message}`, "error");
    } finally {
      setTriggering(false);
    }
  };

  const doApproveReject = async (executionId: string, decision: "approved" | "rejected") => {
    try {
      await apiFetch(`/api/runbooks/executions/${executionId}/approve`, {
        method: "POST",
        body: JSON.stringify({ decision, comment: "" }),
      });
      showToast(
        decision === "approved" ? "✅ Execution approved and running" : "❌ Execution rejected",
        decision === "approved" ? "success" : "info"
      );
      fetchPending();
      fetchExecutions();
      fetchStats();
    } catch (e: any) {
      showToast(`Failed: ${e.message}`, "error");
    }
  };

  const doCancel = async (executionId: string) => {
    try {
      await apiFetch(`/api/runbooks/executions/${executionId}/cancel`, { method: "POST" });
      showToast("Execution cancelled", "info");
      fetchPending();
      fetchExecutions();
    } catch (e: any) {
      showToast(`Cancel failed: ${e.message}`, "error");
    }
  };

  const viewExecution = async (executionId: string) => {
    try {
      const data = await apiFetch<Execution>(`/api/runbooks/executions/${executionId}`);
      setSelectedExecution(data);
    } catch (e: any) {
      showToast(`Failed to load execution: ${e.message}`, "error");
    }
  };

  const savePolicyEdit = async () => {
    if (!editPolicy) return;
    try {
      await apiFetch(`/api/runbooks/policies/${editPolicy.runbook_name}`, {
        method: "PUT",
        body: JSON.stringify(editPolicy),
      });
      showToast("Policy saved", "success");
      setEditPolicy(null);
      fetchPolicies();
    } catch (e: any) {
      showToast(`Save failed: ${e.message}`, "error");
    }
  };

  // ------- Helpers -------------------------------------------------------
  const getStatsFor = (name: string) => stats.find((s) => s.runbook_name === name);

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
          Policy-as-code operational runbooks with configurable approval workflows
        </p>
      </div>

      {/* Sub-tabs */}
      <div className="rb-subtabs">
        <button
          className={`rb-subtab ${subTab === "catalogue" ? "active" : ""}`}
          onClick={() => setSubTab("catalogue")}
        >
          Catalogue
        </button>
        <button
          className={`rb-subtab ${subTab === "history" ? "active" : ""}`}
          onClick={() => { setSubTab("history"); setSelectedExecution(null); }}
        >
          Execution History
        </button>
        <button
          className={`rb-subtab ${subTab === "approvals" ? "active" : ""}`}
          onClick={() => setSubTab("approvals")}
        >
          Approvals
          {pendingList.length > 0 && (
            <span className="rb-badge">{pendingList.length}</span>
          )}
        </button>
        {isAdmin && (
          <button
            className={`rb-subtab ${subTab === "policies" ? "active" : ""}`}
            onClick={() => setSubTab("policies")}
          >
            Approval Policies
          </button>
        )}
      </div>

      {/* ────── CATALOGUE ────── */}
      {subTab === "catalogue" && (
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
                    {st && st.total_executions > 0 && (
                      <button
                        className="rb-btn"
                        onClick={() => {
                          setHistRunbook(rb.name);
                          setHistPage(0);
                          setSubTab("history");
                        }}
                      >
                        📜 History
                      </button>
                    )}
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
      )}

      {/* ────── EXECUTION HISTORY ────── */}
      {subTab === "history" && (
        <div className="rb-section">
          {/* Filters */}
          <div className="rb-filters">
            <select value={histRunbook} onChange={(e) => { setHistRunbook(e.target.value); setHistPage(0); }}>
              <option value="">All runbooks</option>
              {runbooks.map((rb) => (
                <option key={rb.name} value={rb.name}>{rb.display_name}</option>
              ))}
            </select>
            <select value={histStatus} onChange={(e) => { setHistStatus(e.target.value); setHistPage(0); }}>
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="executing">Executing</option>
              <option value="pending_approval">Pending Approval</option>
              <option value="rejected">Rejected</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <button className="rb-btn small" onClick={fetchExecutions}>🔄 Refresh</button>
            <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
              {executionTotal} total
            </span>
          </div>

          {/* Detail panel */}
          {selectedExecution && (
            <div className="rb-detail-panel">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h4>
                  Execution Detail — {selectedExecution.display_name || selectedExecution.runbook_name}
                </h4>
                <button className="rb-btn small" onClick={() => setSelectedExecution(null)}>✕ Close</button>
              </div>
              <dl className="rb-detail-grid">
                <dt>Execution ID</dt><dd>{selectedExecution.execution_id}</dd>
                <dt>Status</dt><dd><span className={`rb-status ${selectedExecution.status}`}>{selectedExecution.status}</span></dd>
                <dt>Dry Run</dt><dd>{selectedExecution.dry_run ? "Yes 🧪" : "No (live)"}</dd>
                <dt>Triggered By</dt><dd>{selectedExecution.triggered_by}</dd>
                <dt>Triggered At</dt><dd>{formatDate(selectedExecution.triggered_at)}</dd>
                {selectedExecution.approved_by && <><dt>Approved By</dt><dd>{selectedExecution.approved_by}</dd></>}
                {selectedExecution.approved_at && <><dt>Approved At</dt><dd>{formatDate(selectedExecution.approved_at)}</dd></>}
                {selectedExecution.started_at && <><dt>Started At</dt><dd>{formatDate(selectedExecution.started_at)}</dd></>}
                {selectedExecution.completed_at && <><dt>Completed At</dt><dd>{formatDate(selectedExecution.completed_at)}</dd></>}
                <dt>Items Found</dt><dd>{selectedExecution.items_found}</dd>
                <dt>Items Actioned</dt><dd>{selectedExecution.items_actioned}</dd>
                {selectedExecution.error_message && <><dt>Error</dt><dd style={{ color: "var(--color-danger, #dc2626)" }}>{selectedExecution.error_message}</dd></>}
              </dl>
              <h4>Parameters</h4>
              <pre className="rb-result-json">{JSON.stringify(selectedExecution.parameters, null, 2)}</pre>
              {selectedExecution.result && Object.keys(selectedExecution.result).length > 0 && (
                <>
                  <h4 style={{ marginTop: 16 }}>Result</h4>
                  <pre className="rb-result-json">{JSON.stringify(selectedExecution.result, null, 2)}</pre>
                </>
              )}
            </div>
          )}

          {/* Table */}
          <div className="rb-table-wrap">
            <table className="rb-table">
              <thead>
                <tr>
                  <th>Runbook</th>
                  <th>Status</th>
                  <th>Dry Run</th>
                  <th>Found</th>
                  <th>Actioned</th>
                  <th>Triggered By</th>
                  <th>Time</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {executions.map((ex) => (
                  <tr key={ex.execution_id}>
                    <td>{ex.display_name || ex.runbook_name}</td>
                    <td><span className={`rb-status ${ex.status}`}>{ex.status}</span></td>
                    <td>{ex.dry_run ? "🧪" : "—"}</td>
                    <td>{ex.items_found}</td>
                    <td>{ex.items_actioned}</td>
                    <td>{ex.triggered_by}</td>
                    <td>{formatDate(ex.triggered_at)}</td>
                    <td>
                      <button className="rb-btn small" onClick={() => viewExecution(ex.execution_id)}>
                        👁 View
                      </button>
                    </td>
                  </tr>
                ))}
                {executions.length === 0 && (
                  <tr>
                    <td colSpan={8} style={{ textAlign: "center", padding: 24, color: "var(--color-text-secondary)" }}>
                      No executions found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {executionTotal > 25 && (
            <div className="rb-pagination">
              <button className="rb-btn small" disabled={histPage === 0} onClick={() => setHistPage(histPage - 1)}>
                ← Prev
              </button>
              <span style={{ fontSize: 12 }}>
                Page {histPage + 1} of {Math.ceil(executionTotal / 25)}
              </span>
              <button
                className="rb-btn small"
                disabled={(histPage + 1) * 25 >= executionTotal}
                onClick={() => setHistPage(histPage + 1)}
              >
                Next →
              </button>
            </div>
          )}
        </div>
      )}

      {/* ────── APPROVALS ────── */}
      {subTab === "approvals" && (
        <div className="rb-section">
          {pendingList.length === 0 ? (
            <div className="rb-empty">
              <div className="rb-empty-icon">✅</div>
              <p>No pending approvals</p>
            </div>
          ) : (
            <div className="rb-table-wrap">
              <table className="rb-table">
                <thead>
                  <tr>
                    <th>Runbook</th>
                    <th>Dry Run</th>
                    <th>Triggered By</th>
                    <th>Time</th>
                    <th>Parameters</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingList.map((ex) => (
                    <tr key={ex.execution_id}>
                      <td>
                        <strong>{ex.display_name || ex.runbook_name}</strong>
                        {ex.risk_level && (
                          <span className={`rb-risk ${ex.risk_level}`} style={{ marginLeft: 8 }}>
                            {ex.risk_level}
                          </span>
                        )}
                      </td>
                      <td>{ex.dry_run ? "🧪 Yes" : "No (live)"}</td>
                      <td>{ex.triggered_by}</td>
                      <td>{formatDate(ex.triggered_at)}</td>
                      <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {JSON.stringify(ex.parameters)}
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }}>
                          <button
                            className="rb-btn success small"
                            onClick={() => doApproveReject(ex.execution_id, "approved")}
                          >
                            ✓ Approve
                          </button>
                          <button
                            className="rb-btn danger small"
                            onClick={() => doApproveReject(ex.execution_id, "rejected")}
                          >
                            ✗ Reject
                          </button>
                          <button
                            className="rb-btn small"
                            onClick={() => doCancel(ex.execution_id)}
                          >
                            Cancel
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ────── APPROVAL POLICIES ────── */}
      {subTab === "policies" && isAdmin && (
        <div className="rb-section">
          <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 16 }}>
            Configure which roles can trigger each runbook and what approval is required.
            Policies are flexible — you can create any trigger → approver mapping per runbook.
          </p>

          <div className="rb-policy-grid">
            {runbooks.map((rb) => {
              const rbPolicies = policies[rb.name] || [];
              return (
                <div className="rb-policy-card" key={rb.name}>
                  <h5>
                    {CATEGORY_ICONS[rb.category] || "📋"} {rb.display_name}
                    <span className={`rb-risk ${rb.risk_level}`} style={{ marginLeft: 8 }}>
                      {rb.risk_level}
                    </span>
                  </h5>
                  {rbPolicies.map((p) => (
                    <div className="rb-policy-row" key={p.policy_id}>
                      <strong>{p.trigger_role}</strong>
                      <span className="rb-arrow">→</span>
                      <span>{p.approver_role}</span>
                      <span className={`rb-mode ${p.approval_mode}`}>
                        {p.approval_mode.replace(/_/g, " ")}
                      </span>
                      <button
                        className="rb-btn small"
                        style={{ marginLeft: 4 }}
                        onClick={() =>
                          setEditPolicy({
                            runbook_name: rb.name,
                            trigger_role: p.trigger_role,
                            approver_role: p.approver_role,
                            approval_mode: p.approval_mode,
                            escalation_timeout_minutes: p.escalation_timeout_minutes,
                            max_auto_executions_per_day: p.max_auto_executions_per_day,
                          })
                        }
                      >
                        ✏️
                      </button>
                    </div>
                  ))}
                  {rbPolicies.length === 0 && (
                    <p style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>No policies configured</p>
                  )}
                  <button
                    className="rb-btn small"
                    style={{ marginTop: 8 }}
                    onClick={() =>
                      setEditPolicy({
                        runbook_name: rb.name,
                        trigger_role: "",
                        approver_role: "admin",
                        approval_mode: "single_approval",
                        escalation_timeout_minutes: 60,
                        max_auto_executions_per_day: 50,
                      })
                    }
                  >
                    + Add Policy
                  </button>
                </div>
              );
            })}
          </div>

          {/* Policy editor modal */}
          {editPolicy && (
            <div className="rb-modal-overlay" onClick={() => setEditPolicy(null)}>
              <div className="rb-modal" onClick={(e) => e.stopPropagation()}>
                <h3>Edit Approval Policy</h3>
                <p className="rb-modal-desc">Runbook: {editPolicy.runbook_name}</p>
                <div className="rb-form-group">
                  <label>Trigger Role (who can trigger)</label>
                  <input
                    value={editPolicy.trigger_role}
                    onChange={(e) => setEditPolicy({ ...editPolicy, trigger_role: e.target.value })}
                    placeholder="e.g. operator, admin, tier1, engineering"
                  />
                  <div className="rb-hint">The role that is allowed to trigger this runbook</div>
                </div>
                <div className="rb-form-group">
                  <label>Approver Role (who must approve)</label>
                  <input
                    value={editPolicy.approver_role}
                    onChange={(e) => setEditPolicy({ ...editPolicy, approver_role: e.target.value })}
                    placeholder="e.g. admin, engineering, security"
                  />
                  <div className="rb-hint">The role required to approve execution</div>
                </div>
                <div className="rb-form-group">
                  <label>Approval Mode</label>
                  <select
                    value={editPolicy.approval_mode}
                    onChange={(e) => setEditPolicy({ ...editPolicy, approval_mode: e.target.value })}
                  >
                    <option value="auto_approve">Auto Approve (no human needed)</option>
                    <option value="single_approval">Single Approval (one approver)</option>
                    <option value="multi_approval">Multi Approval (multiple approvers)</option>
                  </select>
                </div>
                <div className="rb-form-group">
                  <label>Escalation Timeout (minutes)</label>
                  <input
                    type="number"
                    value={editPolicy.escalation_timeout_minutes}
                    onChange={(e) =>
                      setEditPolicy({ ...editPolicy, escalation_timeout_minutes: parseInt(e.target.value) || 60 })
                    }
                  />
                  <div className="rb-hint">Auto-escalate if no approval within this time</div>
                </div>
                <div className="rb-form-group">
                  <label>Max Auto-Executions Per Day</label>
                  <input
                    type="number"
                    value={editPolicy.max_auto_executions_per_day}
                    onChange={(e) =>
                      setEditPolicy({ ...editPolicy, max_auto_executions_per_day: parseInt(e.target.value) || 50 })
                    }
                  />
                  <div className="rb-hint">Rate limit for auto-approved runs (per 24h)</div>
                </div>
                <div className="rb-modal-footer">
                  <button className="rb-btn" onClick={() => setEditPolicy(null)}>Cancel</button>
                  <button className="rb-btn primary" onClick={savePolicyEdit}>Save Policy</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

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
