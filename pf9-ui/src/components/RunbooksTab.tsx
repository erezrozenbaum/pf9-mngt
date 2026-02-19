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

  // Initial load
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchRunbooks(), fetchStats()]).finally(() => setLoading(false));
  }, [fetchRunbooks, fetchStats]);

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
    } catch (e: any) {
      showToast(`❌ Trigger failed: ${e.message}`, "error");
    } finally {
      setTriggering(false);
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
