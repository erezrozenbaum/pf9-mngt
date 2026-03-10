import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";
import "../styles/RunbooksTab.css";
import BulkOnboardingTab from "./BulkOnboardingTab";
import VmProvisioningTab from "./VmProvisioningTab";

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
  onboarding: "📦",
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
export default function RunbooksTab({ userRole = "" }: { userRole?: string }) {
  const isAdmin = userRole === "admin" || userRole === "superadmin";
  const isSuperadmin = userRole === "superadmin";
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [stats, setStats] = useState<ExecutionStats[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: string } | null>(null);

  // Trigger modal state
  const [triggerModal, setTriggerModal] = useState<Runbook | null>(null);
  const [triggerDryRun, setTriggerDryRun] = useState(true);
  const [triggerParams, setTriggerParams] = useState<Record<string, any>>({});
  const [triggering, setTriggering] = useState(false);

  // Bulk Onboarding
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [showProvisioning, setShowProvisioning] = useState(false);

  // My Executions state
  const [myExecs, setMyExecs] = useState<Execution[]>([]);
  const [myExecTotal, setMyExecTotal] = useState(0);
  const [myExecPage, setMyExecPage] = useState(0);
  const [myExecFilter, setMyExecFilter] = useState("");
  const [selectedExec, setSelectedExec] = useState<Execution | null>(null);
  const [showMyExecs, setShowMyExecs] = useState(true);

  // VM Provisioning batch history
  const [vmBatches, setVmBatches] = useState<any[]>([]);
  const [showVmBatches, setShowVmBatches] = useState(true);

  // --- Visibility admin state ----------------------------------------
  const [showVisibility, setShowVisibility] = useState(false);
  const [deptList, setDeptList] = useState<{ id: number; name: string }[]>([]);
  const [visMap, setVisMap] = useState<Record<string, number[]>>({});
  const [visLoading, setVisLoading] = useState(false);
  const [visSaving, setVisSaving] = useState<string | null>(null);

  // --- Integrations admin state --------------------------------------
  const [showIntegrations, setShowIntegrations] = useState(false);
  const [integrations, setIntegrations] = useState<any[]>([]);
  const [integrLoading, setIntegrLoading] = useState(false);
  const [integrForm, setIntegrForm] = useState<any | null>(null); // null = closed
  const [integrSaving, setIntegrSaving] = useState(false);
  const [testingIntegr, setTestingIntegr] = useState<string | null>(null);
  const [integrTestResult, setIntegrTestResult] = useState<Record<string, any>>({});

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

  const fetchVmBatches = useCallback(async () => {
    try {
      const data = await apiFetch<any[]>("/api/vm-provisioning/batches");
      setVmBatches(data);
    } catch (e: any) {
      console.error("Failed to fetch VM provisioning batches:", e);
    }
  }, []);

  const fetchVisibility = useCallback(async () => {
    if (!isAdmin) return;
    setVisLoading(true);
    try {
      const data = await apiFetch<{ departments: any[]; visibility: Record<string, number[]> }>(
        "/api/runbooks/visibility"
      );
      setDeptList(data.departments || []);
      setVisMap(data.visibility || {});
    } catch (e: any) {
      console.error("Failed to fetch visibility:", e);
    } finally {
      setVisLoading(false);
    }
  }, [isAdmin]);

  const saveVisibility = async (name: string, deptIds: number[]) => {
    setVisSaving(name);
    try {
      await apiFetch(`/api/runbooks/visibility/${name}`, {
        method: "PUT",
        body: JSON.stringify({ dept_ids: deptIds }),
      });
      setVisMap((prev) => ({ ...prev, [name]: deptIds }));
      showToast(`Visibility saved for ${name}`, "success");
    } catch (e: any) {
      showToast(`Save failed: ${e.message}`, "error");
    } finally {
      setVisSaving(null);
    }
  };

  const fetchIntegrations = useCallback(async () => {
    if (!isAdmin) return;
    setIntegrLoading(true);
    try {
      const data = await apiFetch<any[]>("/api/integrations");
      setIntegrations(data);
    } catch (e: any) {
      console.error("Failed to fetch integrations:", e);
    } finally {
      setIntegrLoading(false);
    }
  }, [isAdmin]);

  const testIntegration = async (name: string) => {
    setTestingIntegr(name);
    try {
      const result = await apiFetch<any>(`/api/integrations/${name}/test`, { method: "POST" });
      setIntegrTestResult((prev) => ({ ...prev, [name]: result }));
      showToast(
        `Test ${result.test_status === "ok" ? "passed ✓" : "failed: " + result.test_status}`,
        result.test_status === "ok" ? "success" : "error"
      );
    } catch (e: any) {
      showToast(`Test error: ${e.message}`, "error");
    } finally {
      setTestingIntegr(null);
    }
  };

  const saveIntegration = async () => {
    if (!integrForm) return;
    setIntegrSaving(true);
    try {
      const isNew = !integrForm._existing;
      const method = isNew ? "POST" : "PUT";
      const url = isNew ? "/api/integrations" : `/api/integrations/${integrForm.name}`;
      const payload: any = { ...integrForm };
      delete payload._existing;
      if (!isNew && !payload.auth_credential?.length) delete payload.auth_credential;
      await apiFetch(url, { method, body: JSON.stringify(payload) });
      showToast(
        isNew ? "Integration created" : "Integration updated",
        "success"
      );
      setIntegrForm(null);
      await fetchIntegrations();
    } catch (e: any) {
      showToast(`Save failed: ${e.message}`, "error");
    } finally {
      setIntegrSaving(false);
    }
  };

  const deleteIntegration = async (name: string) => {
    if (!confirm(`Delete integration "${name}"? This cannot be undone.`)) return;
    try {
      await apiFetch(`/api/integrations/${name}`, { method: "DELETE" });
      showToast("Integration deleted", "info");
      await fetchIntegrations();
    } catch (e: any) {
      showToast(`Delete failed: ${e.message}`, "error");
    }
  };

  // Initial load
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchRunbooks(), fetchStats(), fetchMyExecs(), fetchVmBatches()]).finally(() => setLoading(false));
  }, [fetchRunbooks, fetchStats, fetchMyExecs, fetchVmBatches]);

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

  /** Flatten execution result to CSV rows */
  const exportExecCsv = (exec: Execution) => {
    const r = exec.result || {};
    const rows: string[][] = [];
    const addSection = (title: string, items: any[]) => {
      if (!items || items.length === 0) return;
      rows.push([`--- ${title} ---`]);
      const keys = Object.keys(items[0]);
      rows.push(keys);
      items.forEach(item => rows.push(keys.map(k => String(item[k] ?? ""))));
      rows.push([]);
    };
    // Header
    rows.push(["Runbook", exec.display_name || exec.runbook_name]);
    rows.push(["Status", exec.status]);
    rows.push(["Triggered", exec.triggered_at]);
    rows.push(["Dry Run", exec.dry_run ? "Yes" : "No"]);
    rows.push(["Items Found", String(exec.items_found)]);
    rows.push(["Items Actioned", String(exec.items_actioned)]);
    rows.push([]);
    // Detect tabular data in result
    const flatten = (obj: any, prefix = "") => {
      for (const [k, v] of Object.entries(obj)) {
        if (Array.isArray(v) && v.length > 0 && typeof v[0] === "object") {
          addSection(prefix + k, v);
        } else if (v && typeof v === "object" && !Array.isArray(v)) {
          // Sub-object with scalar values
          const entries = Object.entries(v as Record<string,any>);
          if (entries.every(([, val]) => typeof val !== "object" || val === null)) {
            rows.push([`--- ${prefix}${k} ---`]);
            entries.forEach(([sk, sv]) => rows.push([sk, String(sv ?? "")]));
            rows.push([]);
          } else {
            flatten(v, `${prefix}${k} > `);
          }
        }
      }
    };
    flatten(r);
    // If nothing tabular was found, dump as key-value
    if (rows.length <= 7) {
      for (const [k, v] of Object.entries(r)) {
        rows.push([k, JSON.stringify(v)]);
      }
    }
    const csv = rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${exec.runbook_name}_${exec.execution_id.slice(0, 8)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  /** Export execution result as JSON */
  const exportExecJson = (exec: Execution) => {
    const data = { runbook: exec.display_name || exec.runbook_name, status: exec.status, dry_run: exec.dry_run, triggered_at: exec.triggered_at, items_found: exec.items_found, items_actioned: exec.items_actioned, result: exec.result };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${exec.runbook_name}_${exec.execution_id.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  /** Print the detail panel (browser print-to-PDF) */
  const printExecResult = () => {
    const panel = document.querySelector(".rb-detail-panel");
    if (!panel) return;
    const printWin = window.open("", "_blank", "width=900,height=700");
    if (!printWin) return;
    printWin.document.write(`<!DOCTYPE html><html><head><title>Runbook Result</title><style>
      body{font-family:system-ui,-apple-system,sans-serif;padding:24px;color:#333}
      table{border-collapse:collapse;width:100%;margin:8px 0}
      th,td{border:1px solid #ddd;padding:6px 10px;text-align:left;font-size:13px}
      th{background:#f5f5f5;font-weight:600}
      h4,h5,h6{margin:12px 0 6px}
      .rb-status-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600}
      .rb-status-badge.completed{background:#d4edda;color:#155724}
      .rb-status-badge.failed{background:#f8d7da;color:#721c24}
      .rb-status-badge.pending_approval{background:#fff3cd;color:#856404}
      .rb-status-badge.executing{background:#d1ecf1;color:#0c5460}
      .rb-detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
      @media print{body{padding:0}}
    </style></head><body>`);
    printWin.document.write(panel.innerHTML);
    printWin.document.write("</body></html>");
    printWin.document.close();
    setTimeout(() => { printWin.print(); }, 400);
  };

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

    // ── VM Health Quick Fix ──
    if (name === "vm_health_quickfix") {
      const checks = r.checks || {};
      const issues = r.issues || [];
      const rem = r.remediation || {};
      return (
        <div className="rb-result-friendly">
          <p className="rb-result-summary">
            VM: <strong>{r.server_name || r.server_id}</strong> · Overall: <span className={`rb-status-badge ${r.overall_healthy ? "completed" : "failed"}`}>{r.overall_healthy ? "Healthy" : `${issues.length} issue(s)`}</span>
          </p>
          <table className="rb-result-table">
            <thead><tr><th>Check</th><th>Status</th><th>Details</th></tr></thead>
            <tbody>
              {Object.entries(checks).map(([key, val]: [string, any]) => (
                <tr key={key}>
                  <td style={{textTransform:"capitalize"}}>{key.replace(/_/g, " ")}</td>
                  <td><span className={`rb-status-badge ${val.ok ? "completed" : "failed"}`}>{val.ok ? "✓ OK" : "✗ Issue"}</span></td>
                  <td style={{fontSize:"0.85em"}}>
                    {key === "power_state" && `${val.vm_status} / ${val.status}`}
                    {key === "hypervisor" && `${val.host || "—"} ${val.state ? `(${val.state}/${val.status})` : ""}`}
                    {key === "ports" && `${val.count || 0} port(s)`}
                    {key === "volumes" && `${val.count || 0} attached`}
                    {key === "network" && `${(val.networks || []).length} net(s), ${(val.floating_ips || []).length} FIP(s)`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {issues.length > 0 && (
            <div className="rb-result-sub rb-result-errors"><h6>Issues</h6><ul>{issues.map((i: string, idx: number) => <li key={idx}>{i}</li>)}</ul></div>
          )}
          {rem.attempted && (
            <div className="rb-result-sub"><h6>Remediation</h6><p>{rem.result}</p></div>
          )}
        </div>
      );
    }

    // ── Snapshot Before Escalation ──
    if (name === "snapshot_before_escalation") {
      return (
        <div className="rb-result-friendly">
          <p className="rb-result-summary">
            VM: <strong>{r.server_name || r.server_id}</strong> · Action: <strong>{r.action || "—"}</strong>
          </p>
          {r.snapshot_id && <p>Snapshot ID: <code>{r.snapshot_id}</code></p>}
          <p>Snapshot Name: <strong>{r.snapshot_name}</strong></p>
          {r.metadata && (
            <table className="rb-result-table">
              <thead><tr><th>Tag</th><th>Value</th></tr></thead>
              <tbody>
                {Object.entries(r.metadata).map(([k, v]: [string, any]) => (
                  <tr key={k}><td>{k}</td><td>{String(v)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          {r.vm_summary && (
            <div className="rb-result-sub">
              <h6>VM State at Snapshot</h6>
              <p>Status: {r.vm_summary.status} · Host: {r.vm_summary.host || "—"} · Volumes: {(r.vm_summary.attached_volumes || []).length}</p>
            </div>
          )}
        </div>
      );
    }

    // ── Upgrade Opportunity Detector ──
    if (name === "upgrade_opportunity_detector") {
      const opps = r.opportunities || [];
      return (
        <div className="rb-result-friendly">
          <p className="rb-result-summary">
            Scanned <strong>{r.total_tenants_scanned || 0}</strong> tenants · <strong>{r.tenants_with_opportunities || 0}</strong> with opportunities · Est. revenue delta: <strong>${r.estimated_revenue_delta_monthly || 0}/mo</strong>
          </p>
          {opps.length === 0 ? <p className="rb-result-empty">No upgrade opportunities found</p> : opps.map((t: any) => (
            <div className="rb-result-sub" key={t.tenant_id}>
              <h6>{t.tenant_name} ({t.vm_count} VMs)</h6>
              <table className="rb-result-table">
                <thead><tr><th>Type</th><th>Resource</th><th>Suggestion</th><th>Revenue Δ</th></tr></thead>
                <tbody>
                  {(t.opportunities || []).map((o: any, i: number) => (
                    <tr key={i}>
                      <td><span className={`rb-status-badge ${o.type === "quota_pressure" ? "pending_approval" : "executing"}`}>{o.type.replace(/_/g, " ")}</span></td>
                      <td>{o.vm_name || o.resource || "—"}</td>
                      <td>{o.suggestion}</td>
                      <td>{o.revenue_delta ? `+$${o.revenue_delta.toFixed(2)}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      );
    }

    // ── Monthly Executive Snapshot ──
    if (name === "monthly_executive_snapshot") {
      const deltas = r.deltas || {};
      const cap = r.capacity_risk || {};
      const rev = r.revenue_estimate || {};
      const risks = r.top_risk_tenants || [];
      return (
        <div className="rb-result-friendly">
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(140px,1fr))",gap:"10px",marginBottom:"12px"}}>
            {[
              {label:"Tenants",value:r.total_tenants,delta:deltas.tenants},
              {label:"VMs",value:r.total_vms,delta:deltas.vms},
              {label:"Volumes",value:r.total_volumes},
              {label:"Storage",value:`${r.total_storage_gb || 0} GB`},
              {label:"Compliance",value:`${r.compliance_pct || 0}%`},
              {label:"Revenue Est.",value:`$${(rev.monthly || 0).toLocaleString()}/mo`},
            ].map((kpi,i) => (
              <div key={i} style={{background:"var(--color-surface-elevated,#f5f5f5)",borderRadius:"8px",padding:"10px",textAlign:"center"}}>
                <div style={{fontSize:"0.75em",opacity:0.7}}>{kpi.label}</div>
                <div style={{fontSize:"1.3em",fontWeight:700}}>{kpi.value ?? "—"}</div>
                {kpi.delta !== undefined && <div style={{fontSize:"0.75em",color:kpi.delta >= 0 ? "#22c55e" : "#ef4444"}}>{kpi.delta >= 0 ? "+" : ""}{kpi.delta}</div>}
              </div>
            ))}
          </div>
          {cap.hypervisors_at_risk !== undefined && (
            <p className="rb-result-summary">Capacity Risk: <strong>{cap.hypervisors_at_risk}</strong> of {cap.total_hypervisors} hypervisors at &gt;80% RAM</p>
          )}
          {risks.length > 0 && (
            <div className="rb-result-sub">
              <h6>Top {risks.length} Risk Tenants</h6>
              <table className="rb-result-table">
                <thead><tr><th>Tenant</th><th>VMs</th><th>Error VMs</th><th>Snapshots</th><th>Risk Score</th></tr></thead>
                <tbody>
                  {risks.map((t: any) => (
                    <tr key={t.tenant_id}>
                      <td>{t.tenant_name}</td>
                      <td>{t.vm_count}</td>
                      <td>{t.error_vms > 0 ? <span className="rb-status-badge failed">{t.error_vms}</span> : "0"}</td>
                      <td>{t.snapshot_count}</td>
                      <td><strong>{t.risk_score}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      );
    }

    // ── Cost Leakage Report ──
    if (name === "cost_leakage_report") {
      const leaks = r.leaks || {};
      const costs = r.costs_monthly || {};
      const categories = [
        {key:"idle_vms",label:"Idle VMs",cols:["VM Name","Tenant","CPU %","vCPUs","$/mo"],fields:["vm_name","tenant_name","cpu_pct","vcpus","monthly_cost"]},
        {key:"shutoff_vms",label:"SHUTOFF VMs",cols:["VM Name","Tenant","Since","vCPUs","$/mo"],fields:["vm_name","tenant_name","shutoff_since","vcpus","monthly_cost"]},
        {key:"detached_volumes",label:"Detached Volumes",cols:["Name","Tenant","Size","Created","$/mo"],fields:["name","tenant_name","size_gb","created_at","monthly_cost"]},
        {key:"unused_fips",label:"Unused Floating IPs",cols:["IP","Tenant","$/mo"],fields:["floating_ip","tenant_name","monthly_cost"]},
        {key:"oversized_vms",label:"Oversized VMs",cols:["VM Name","Tenant","RAM MB","Mem Used %","$/mo"],fields:["vm_name","tenant_name","ram_mb","mem_used_pct","monthly_cost"]},
      ];
      return (
        <div className="rb-result-friendly">
          <div style={{background:"var(--color-surface-elevated,#fff3cd)",borderRadius:"8px",padding:"12px",marginBottom:"12px",textAlign:"center",border:"1px solid #ffc107"}}>
            <div style={{fontSize:"0.85em",opacity:0.8}}>Total Estimated Monthly Waste</div>
            <div style={{fontSize:"1.8em",fontWeight:700,color:"#dc3545"}}>${(r.total_monthly_waste || 0).toLocaleString()}/mo</div>
            <div style={{fontSize:"0.8em",opacity:0.7}}>{r.total_items || 0} resources flagged</div>
          </div>
          {categories.map(cat => {
            const items = leaks[cat.key] || [];
            if (items.length === 0) return null;
            return (
              <div className="rb-result-sub" key={cat.key}>
                <h6>{cat.label} ({items.length}) · ${(costs[cat.key] || 0).toFixed(2)}/mo</h6>
                <table className="rb-result-table">
                  <thead><tr>{cat.cols.map(c => <th key={c}>{c}</th>)}</tr></thead>
                  <tbody>
                    {items.map((item: any, i: number) => (
                      <tr key={i}>{cat.fields.map(f => <td key={f}>{typeof item[f] === "number" ? (f === "monthly_cost" ? `$${item[f].toFixed(2)}` : item[f]) : (f.includes("since") || f.includes("created") ? formatDate(item[f]) : (item[f] || "—"))}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })}
        </div>
      );
    }

    // ── Password Reset + Console Access ──
    if (name === "password_reset_console") {
      const pw = r.password_reset || {};
      const con = r.console_access || {};
      const ci = r.cloud_init_check || {};
      return (
        <div className="rb-result-friendly">
          <p className="rb-result-summary">
            VM: <strong>{r.server_name || r.server_id}</strong>
            {r.action && <> · <em>{r.action}</em></>}
          </p>
          <table className="rb-result-table">
            <thead><tr><th>Step</th><th>Status</th><th>Details</th></tr></thead>
            <tbody>
              <tr>
                <td>Cloud-Init Check</td>
                <td><span className={`rb-status-badge ${ci.supported !== false ? "completed" : "pending_approval"}`}>{ci.supported !== false ? "Supported" : "Uncertain"}</span></td>
                <td>{ci.note || "OK"}</td>
              </tr>
              {pw.attempted && (
                <tr>
                  <td>Password Reset</td>
                  <td><span className={`rb-status-badge ${pw.success ? "completed" : "failed"}`}>{pw.success ? "Success" : "Failed"}</span></td>
                  <td>{pw.success ? <><code style={{background:"var(--color-surface-elevated,#e9ecef)",padding:"2px 6px",borderRadius:"4px"}}>{pw.password}</code> <em style={{fontSize:"0.8em"}}>(save securely)</em></> : (pw.error || pw.note || "—")}</td>
                </tr>
              )}
              {con.attempted && (
                <tr>
                  <td>Console Access</td>
                  <td><span className={`rb-status-badge ${con.success ? "completed" : "failed"}`}>{con.success ? `${con.type} Active` : "Failed"}</span></td>
                  <td>
                    {con.success ? (
                      <><a href={con.url} target="_blank" rel="noreferrer" style={{wordBreak:"break-all"}}>Open Console ↗</a> · Expires: {formatDate(con.expires_at)}</>
                    ) : (con.error || "—")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {r.audit && (
            <div className="rb-result-sub">
              <h6>Audit Log</h6>
              <p>Actor: {r.audit.actor} · Time: {formatDate(r.audit.timestamp)} · Console expiry: {r.audit.console_expiry_minutes} min</p>
            </div>
          )}
        </div>
      );
    }

    // ── Security & Compliance Audit ──
    if (name === "security_compliance_audit") {
      const f = r.findings || {};
      const sev = r.severity_counts || {};
      return (
        <div className="rb-result-friendly">
          <p className="rb-result-summary">
            Total findings: <strong>{r.total_findings || 0}</strong> · 
            <span className="rb-status-badge failed">{sev.critical || 0} critical</span>{" "}
            <span className="rb-status-badge pending_approval">{sev.warning || 0} warning</span>{" "}
            <span className="rb-status-badge completed">{sev.info || 0} info</span>
          </p>
          {(f.sg_violations || []).length > 0 && (
            <div className="rb-result-sub">
              <h6>Security Group Violations ({f.sg_violations.length})</h6>
              <table className="rb-result-table">
                <thead><tr><th>SG Name</th><th>Tenant</th><th>Protocol</th><th>Ports</th><th>Source</th><th>Severity</th></tr></thead>
                <tbody>
                  {f.sg_violations.map((v: any, i: number) => (
                    <tr key={i}>
                      <td>{v.sg_name || v.sg_id}</td>
                      <td>{v.project_name}</td>
                      <td>{v.protocol}</td>
                      <td>{v.port_range}</td>
                      <td>{v.remote_ip_prefix}</td>
                      <td><span className={`rb-status-badge ${v.severity === "critical" ? "failed" : "pending_approval"}`}>{v.severity}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {(f.stale_users || []).length > 0 && (
            <div className="rb-result-sub">
              <h6>Stale Users ({f.stale_users.length})</h6>
              <table className="rb-result-table">
                <thead><tr><th>Username</th><th>Domain</th><th>Enabled</th><th>Last Activity</th><th>Severity</th></tr></thead>
                <tbody>
                  {f.stale_users.map((u: any, i: number) => (
                    <tr key={i}>
                      <td>{u.username}</td>
                      <td>{u.domain}</td>
                      <td>{u.enabled ? "Yes" : "No"}</td>
                      <td>{u.last_activity === "never" ? "Never" : formatDate(u.last_activity)}</td>
                      <td><span className={`rb-status-badge ${u.severity === "warning" ? "pending_approval" : "completed"}`}>{u.severity}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {(f.unencrypted_volumes || []).length > 0 && (
            <div className="rb-result-sub">
              <h6>Unencrypted Volumes ({f.unencrypted_volumes.length})</h6>
              <table className="rb-result-table">
                <thead><tr><th>Name</th><th>Size</th><th>Status</th><th>Tenant</th></tr></thead>
                <tbody>
                  {f.unencrypted_volumes.map((v: any, i: number) => (
                    <tr key={i}>
                      <td>{v.name}</td>
                      <td>{v.size_gb} GB</td>
                      <td>{v.status}</td>
                      <td>{v.tenant_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {(r.total_findings || 0) === 0 && <p className="rb-result-empty">No security or compliance issues found</p>}
        </div>
      );
    }

    // ── User Last Login Report ──
    if (name === "user_last_login") {
      const users = r.users || [];
      const summary = r.summary || {};
      const failed = r.failed_logins || [];
      return (
        <div className="rb-result-friendly">
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(120px,1fr))",gap:"10px",marginBottom:"12px"}}>
            {[
              {label:"Total Users",value:summary.total_users},
              {label:"Active",value:summary.active_users},
              {label:"Inactive",value:summary.inactive_users},
              {label:"Never Logged In",value:summary.never_logged_in},
            ].map((kpi,i) => (
              <div key={i} style={{background:"var(--color-surface-elevated,#f5f5f5)",borderRadius:"8px",padding:"10px",textAlign:"center"}}>
                <div style={{fontSize:"0.75em",opacity:0.7}}>{kpi.label}</div>
                <div style={{fontSize:"1.3em",fontWeight:700}}>{kpi.value ?? "—"}</div>
              </div>
            ))}
          </div>
          <p className="rb-result-summary">Inactive threshold: <strong>{summary.days_inactive_threshold || 30}</strong> days</p>
          {users.length === 0 ? <p className="rb-result-empty">No users found</p> : (
            <table className="rb-result-table">
              <thead><tr><th>Username</th><th>Role</th><th>Last Login</th><th>Last Activity</th><th>IP</th><th>Total Logins</th><th>Sessions</th><th>Days Since</th><th>Status</th></tr></thead>
              <tbody>
                {users.map((u: any) => (
                  <tr key={u.username}>
                    <td>{u.username}</td>
                    <td>{u.role}</td>
                    <td>{u.last_login ? formatDate(u.last_login) : "Never"}</td>
                    <td>{u.last_activity ? formatDate(u.last_activity) : "—"}</td>
                    <td>{u.last_login_ip || "—"}</td>
                    <td>{u.total_logins}</td>
                    <td>{u.active_sessions}</td>
                    <td>{u.days_since_activity !== null && u.days_since_activity !== undefined ? u.days_since_activity : "—"}</td>
                    <td><span className={`rb-status-badge ${u.status === "active" ? "completed" : u.status === "inactive" ? "pending_approval" : "failed"}`}>{u.status === "never_logged_in" ? "Never" : u.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {failed.length > 0 && (
            <div className="rb-result-sub rb-result-errors">
              <h6>Recent Failed Logins ({failed.length})</h6>
              <table className="rb-result-table">
                <thead><tr><th>Username</th><th>Time</th><th>IP</th><th>User Agent</th></tr></thead>
                <tbody>
                  {failed.map((f: any, i: number) => (
                    <tr key={i}>
                      <td>{f.username}</td>
                      <td>{formatDate(f.timestamp)}</td>
                      <td>{f.ip_address || "—"}</td>
                      <td style={{maxWidth:"200px",overflow:"hidden",textOverflow:"ellipsis"}}>{f.user_agent || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      );
    }

    // ── Snapshot Quota Forecast ──
    if (name === "snapshot_quota_forecast") {
      const alerts = r.alerts || [];
      const okProjects = r.ok_projects || [];
      const sum = r.summary || {};
      return (
        <div className="rb-result-friendly">
          <p className="rb-result-summary">
            Projects scanned: <strong>{sum.total_projects_scanned || 0}</strong> ·
            At risk: <strong className="rb-val-bad">{sum.projects_at_risk || 0}</strong> ·
            OK: <strong className="rb-val-ok">{sum.projects_ok || 0}</strong> ·
            Critical: <strong className="rb-val-bad">{sum.critical_count || 0}</strong> ·
            Warning: <strong className="rb-val-warn">{sum.warning_count || 0}</strong>
          </p>
          {alerts.length > 0 && (
            <div className="rb-result-sub">
              <h6>At-Risk Projects</h6>
              <table className="rb-result-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Project</th>
                    <th>Volumes</th>
                    <th>Total Vol GB</th>
                    <th>GB Quota</th>
                    <th>GB Used</th>
                    <th>Snap Quota</th>
                    <th>Snap Used</th>
                    <th>Issues</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.map((a: any, i: number) => (
                    <tr key={i} className={a.severity === 'critical' ? 'row-critical' : 'row-warning'}>
                      <td>
                        <span className={`badge ${a.severity === 'critical' ? 'badge-critical' : 'badge-warning'}`}>
                          {a.severity}
                        </span>
                      </td>
                      <td>{a.project_name}</td>
                      <td>{a.volumes}</td>
                      <td>{a.total_volume_gb}</td>
                      <td>{a.gb_quota_limit ?? '∞'}</td>
                      <td>{a.gb_quota_used ?? '-'}</td>
                      <td>{a.snap_quota_limit ?? '∞'}</td>
                      <td>{a.snap_quota_used ?? '-'}</td>
                      <td>
                        {(a.issues || []).map((iss: any, j: number) => (
                          <div key={j} className="quota-issue-line">
                            <strong>{iss.resource}:</strong>{' '}
                            {iss.shortfall_gb ? `${iss.shortfall_gb}GB shortfall` : ''}
                            {iss.shortfall ? `${iss.shortfall} snapshots short` : ''}
                            {' '}({iss.pct_used ?? iss.used}/{iss.limit})
                          </div>
                        ))}
                        {a.issue && <span>{a.issue}: {a.detail}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {okProjects.length > 0 && (
            <details className="rb-result-sub">
              <summary>OK Projects ({okProjects.length})</summary>
              <table className="rb-result-table">
                <thead>
                  <tr>
                    <th>Project</th>
                    <th>Volumes</th>
                    <th>Total Vol GB</th>
                    <th>GB Quota</th>
                    <th>GB Used</th>
                  </tr>
                </thead>
                <tbody>
                  {okProjects.map((p: any, i: number) => (
                    <tr key={i}>
                      <td>{p.project_name}</td>
                      <td>{p.volumes}</td>
                      <td>{p.total_volume_gb}</td>
                      <td>{p.gb_quota_limit ?? '∞'}</td>
                      <td>{p.gb_quota_used ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          {alerts.length === 0 && <p className="rb-result-empty">All projects have sufficient quota for upcoming snapshot runs</p>}
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
  if (showOnboarding) {
    return <BulkOnboardingTab onBack={() => setShowOnboarding(false)} />;
  }

  if (showProvisioning) {
    return <VmProvisioningTab onBack={() => setShowProvisioning(false)} />;
  }

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
          {/* Bulk Customer Onboarding — special card */}
          <div className="rb-card" style={{ borderColor: "rgba(34,197,94,.3)" }}>
            <div className="rb-card-header">
              <h4 className="rb-card-title">📦 Bulk Customer Onboarding</h4>
              <span className="rb-risk low">low</span>
            </div>
            <p className="rb-card-desc">
              Upload an Excel template to mass-create customer domains, projects,
              networks, and users through a validated dry-run → approval → execute workflow.
            </p>
            <div className="rb-card-meta">
              <span>📁 onboarding</span>
              <span>🧪 Dry-run gate</span>
              <span>✅ Approval required</span>
            </div>
            <div className="rb-card-actions">
              <button className="rb-btn primary" onClick={() => setShowOnboarding(true)}>
                ▶ Open
              </button>
            </div>
          </div>

          {/* VM Provisioning — Runbook 2 */}
          <div className="rb-card" style={{ borderColor: "rgba(59,130,246,.3)" }}>
            <div className="rb-card-header">
              <h4 className="rb-card-title">☁️ VM Provisioning</h4>
              <span className="rb-risk low">low</span>
            </div>
            <p className="rb-card-desc">
              Provision VMs into customer projects via a guided form or Excel upload.
              Boot-from-volume only (disk=0 flavors) · auto cloud-init · quota check ·
              dry-run → approval → execute workflow.
            </p>
            <div className="rb-card-meta">
              <span>📁 provisioning</span>
              <span>🧪 Dry-run gate</span>
              <span>✅ Approval required</span>
            </div>
            <div className="rb-card-actions">
              <button className="rb-btn primary" onClick={() => setShowProvisioning(true)}>
                ▶ Open
              </button>
            </div>
          </div>

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
                  <div style={{display:"flex",gap:"6px",alignItems:"center"}}>
                    <button className="rb-btn small" title="Export as CSV" onClick={() => exportExecCsv(selectedExec)}>📥 CSV</button>
                    <button className="rb-btn small" title="Export as JSON" onClick={() => exportExecJson(selectedExec)}>📥 JSON</button>
                    <button className="rb-btn small" title="Print / Save as PDF" onClick={() => printExecResult()}>🖨️ PDF</button>
                    <button className="rb-btn small" onClick={() => setSelectedExec(null)}>✕ Close</button>
                  </div>
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

      {/* ────── VM PROVISIONING HISTORY ────── */}
      <div className="rb-section">
        <div className="rb-section-header" onClick={() => setShowVmBatches(!showVmBatches)} style={{ cursor: "pointer" }}>
          <h3>{showVmBatches ? "▾" : "▸"} ☁️ VM Provisioning History</h3>
          <div className="rb-section-controls">
            <button className="rb-btn small" onClick={(e) => { e.stopPropagation(); fetchVmBatches(); }}>
              🔄 Refresh
            </button>
            <button className="rb-btn small primary" onClick={(e) => { e.stopPropagation(); setShowProvisioning(true); }}>
              ▶ Open Provisioning
            </button>
            <span className="rb-meta">{vmBatches.length} batches</span>
          </div>
        </div>

        {showVmBatches && (
          <div className="rb-exec-table">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Batch Name</th>
                  <th>Domain / Project</th>
                  <th>Status</th>
                  <th>Approval</th>
                  <th>Created By</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {vmBatches.slice(0, 20).map((b) => {
                  const statusClass = b.status === "complete" ? "completed"
                    : b.status === "failed" || b.status === "partially_failed" ? "failed"
                    : b.status === "executing" ? "executing"
                    : b.status === "dry_run_passed" || b.status === "validated" ? "completed"
                    : "pending_approval";
                  const approvalClass = b.approval_status === "approved" ? "completed"
                    : b.approval_status === "rejected" ? "failed"
                    : "pending_approval";
                  return (
                    <tr key={b.id}>
                      <td className="rb-meta">#{b.id}</td>
                      <td>{b.name || `Batch #${b.id}`}</td>
                      <td className="rb-meta">{b.domain_name} / {b.project_name}</td>
                      <td><span className={`rb-status-badge ${statusClass}`}>{b.status?.replace(/_/g, " ")}</span></td>
                      <td><span className={`rb-status-badge ${approvalClass}`}>{b.approval_status?.replace(/_/g, " ") || "—"}</span></td>
                      <td>{b.created_by}</td>
                      <td className="rb-meta">{formatDate(b.created_at)}</td>
                    </tr>
                  );
                })}
                {vmBatches.length === 0 && (
                  <tr>
                    <td colSpan={7} className="rb-empty-row">No VM provisioning batches yet — click ▶ Open Provisioning to create one!</td>
                  </tr>
                )}
              </tbody>
            </table>
            {vmBatches.length > 20 && (
              <div className="rb-pagination">
                <button className="rb-btn small primary" onClick={() => setShowProvisioning(true)}>
                  View all {vmBatches.length} batches in Provisioning →
                </button>
              </div>
            )}
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

      {/* ────── ADMIN: RUNBOOK VISIBILITY ────── */}
      {isAdmin && (
        <div className="rb-section">
          <div
            className="rb-section-header"
            onClick={() => {
              if (!showVisibility) fetchVisibility();
              setShowVisibility(!showVisibility);
            }}
            style={{ cursor: "pointer" }}
          >
            <h3>{showVisibility ? "▾" : "▸"} 🏢 Runbook Dept Visibility</h3>
            <div className="rb-section-controls">
              <button
                className="rb-btn small"
                onClick={(e) => { e.stopPropagation(); fetchVisibility(); }}
              >
                🔄 Refresh
              </button>
              <span className="rb-meta">Admin only</span>
            </div>
          </div>

          {showVisibility && (
            visLoading ? (
              <div className="rb-loading"><div className="rb-spinner" /> Loading visibility…</div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="rb-result-table" style={{ minWidth: 600 }}>
                  <thead>
                    <tr>
                      <th>Runbook</th>
                      {deptList.map((d) => (
                        <th key={d.id} style={{ fontSize: 12, whiteSpace: "nowrap" }}>{d.name}</th>
                      ))}
                      <th>Save</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runbooks.map((rb) => {
                      const current: number[] = visMap[rb.name] || [];
                      return (
                        <tr key={rb.name}>
                          <td style={{ fontWeight: 500, whiteSpace: "nowrap" }}>
                            {rb.display_name}
                            {current.length === 0 && (
                              <span className="rb-meta" style={{ marginLeft: 6 }}>(all depts)</span>
                            )}
                          </td>
                          {deptList.map((d) => {
                            const checked = current.includes(d.id);
                            return (
                              <td key={d.id} style={{ textAlign: "center" }}>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => {
                                    const next = checked
                                      ? current.filter((x) => x !== d.id)
                                      : [...current, d.id];
                                    setVisMap((prev) => ({ ...prev, [rb.name]: next }));
                                  }}
                                />
                              </td>
                            );
                          })}
                          <td>
                            <button
                              className="rb-btn small primary"
                              disabled={visSaving === rb.name}
                              onClick={() => saveVisibility(rb.name, visMap[rb.name] || [])}
                            >
                              {visSaving === rb.name ? "…" : "💾"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                    {runbooks.length === 0 && (
                      <tr>
                        <td colSpan={deptList.length + 2} className="rb-empty-row">
                          No runbooks loaded
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
                <p className="rb-hint" style={{ marginTop: 8 }}>
                  Unchecked = that dept cannot see the runbook. No boxes checked = visible to all depts.
                </p>
              </div>
            )
          )}
        </div>
      )}

      {/* ────── ADMIN: EXTERNAL INTEGRATIONS ────── */}
      {isAdmin && (
        <div className="rb-section">
          <div
            className="rb-section-header"
            onClick={() => {
              if (!showIntegrations) fetchIntegrations();
              setShowIntegrations(!showIntegrations);
            }}
            style={{ cursor: "pointer" }}
          >
            <h3>{showIntegrations ? "▾" : "▸"} 🔌 External Integrations</h3>
            <div className="rb-section-controls">
              <button
                className="rb-btn small"
                onClick={(e) => { e.stopPropagation(); fetchIntegrations(); }}
              >
                🔄 Refresh
              </button>
              {isSuperadmin && (
                <button
                  className="rb-btn small primary"
                  onClick={(e) => {
                    e.stopPropagation();
                    setIntegrForm({
                      name: "", display_name: "", integration_type: "billing_gate",
                      base_url: "", auth_type: "bearer", auth_credential: "",
                      auth_header_name: "Authorization", request_template: {},
                      response_approval_path: "approved", response_reason_path: "reason",
                      response_charge_id_path: "charge_id",
                      enabled: false, timeout_seconds: 10, verify_ssl: true,
                      _existing: false,
                    });
                    if (!showIntegrations) { fetchIntegrations(); setShowIntegrations(true); }
                  }}
                >
                  + Add
                </button>
              )}
            </div>
          </div>

          {showIntegrations && (
            integrLoading ? (
              <div className="rb-loading"><div className="rb-spinner" /> Loading integrations…</div>
            ) : (
              <>
                <div className="rb-exec-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Base URL</th>
                        <th>Auth</th>
                        <th>Enabled</th>
                        <th>Last Test</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {integrations.map((intg) => {
                        const tr = integrTestResult[intg.name];
                        return (
                          <tr key={intg.name}>
                            <td style={{ fontWeight: 500 }}>{intg.display_name}<br /><span className="rb-meta">{intg.name}</span></td>
                            <td><span className="rb-status-badge pending_approval">{intg.integration_type}</span></td>
                            <td className="rb-meta" style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={intg.base_url}>{intg.base_url}</td>
                            <td className="rb-meta">{intg.auth_type}</td>
                            <td>
                              <span className={`rb-status-badge ${intg.enabled ? "completed" : "failed"}`}>
                                {intg.enabled ? "enabled" : "disabled"}
                              </span>
                            </td>
                            <td className="rb-meta">
                              {intg.last_test_status ? (
                                <span className={`rb-status-badge ${intg.last_test_status === "ok" ? "completed" : "failed"}`}>
                                  {intg.last_test_status}
                                </span>
                              ) : "—"}
                              {tr && (
                                <div style={{ fontSize: 11, marginTop: 2, color: tr.test_status === "ok" ? "#4caf50" : "#f44336" }}>
                                  {tr.test_status}
                                </div>
                              )}
                            </td>
                            <td>
                              <div style={{ display: "flex", gap: 4 }}>
                                <button
                                  className="rb-btn small"
                                  disabled={testingIntegr === intg.name}
                                  onClick={() => testIntegration(intg.name)}
                                >
                                  {testingIntegr === intg.name ? "…" : "🧪 Test"}
                                </button>
                                {isSuperadmin && (
                                  <>
                                    <button
                                      className="rb-btn small primary"
                                      onClick={() =>
                                        setIntegrForm({ ...intg, auth_credential: "", _existing: true })
                                      }
                                    >
                                      ✏️
                                    </button>
                                    <button
                                      className="rb-btn small"
                                      style={{ color: "#f44336" }}
                                      onClick={() => deleteIntegration(intg.name)}
                                    >
                                      🗑
                                    </button>
                                  </>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                      {integrations.length === 0 && (
                        <tr>
                          <td colSpan={7} className="rb-empty-row">
                            No integrations configured.{isSuperadmin ? " Click + Add to create one." : ""}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Integration create/edit form */}
                {integrForm && (
                  <div className="rb-modal-overlay" onClick={() => setIntegrForm(null)}>
                    <div className="rb-modal" style={{ maxWidth: 520 }} onClick={(e) => e.stopPropagation()}>
                      <h3>{integrForm._existing ? `Edit: ${integrForm.name}` : "New Integration"}</h3>

                      {!integrForm._existing && (
                        <div className="rb-form-group">
                          <label>Name (slug)</label>
                          <input type="text" value={integrForm.name}
                            placeholder="e.g. billing"
                            onChange={(e) => setIntegrForm({ ...integrForm, name: e.target.value })} />
                        </div>
                      )}
                      <div className="rb-form-group">
                        <label>Display Name</label>
                        <input type="text" value={integrForm.display_name}
                          onChange={(e) => setIntegrForm({ ...integrForm, display_name: e.target.value })} />
                      </div>
                      <div className="rb-form-group">
                        <label>Type</label>
                        <select value={integrForm.integration_type}
                          onChange={(e) => setIntegrForm({ ...integrForm, integration_type: e.target.value })}>
                          <option value="billing_gate">billing_gate</option>
                          <option value="crm">crm</option>
                          <option value="webhook">webhook</option>
                        </select>
                      </div>
                      <div className="rb-form-group">
                        <label>Base URL</label>
                        <input type="text" value={integrForm.base_url}
                          placeholder="https://billing.example.com/api/approve"
                          onChange={(e) => setIntegrForm({ ...integrForm, base_url: e.target.value })} />
                      </div>
                      <div className="rb-form-group">
                        <label>Auth Type</label>
                        <select value={integrForm.auth_type}
                          onChange={(e) => setIntegrForm({ ...integrForm, auth_type: e.target.value })}>
                          <option value="bearer">bearer</option>
                          <option value="basic">basic</option>
                          <option value="api_key">api_key</option>
                        </select>
                      </div>
                      <div className="rb-form-group">
                        <label>Credential {integrForm._existing && <span className="rb-meta">(leave blank to keep current)</span>}</label>
                        <input type="password" value={integrForm.auth_credential}
                          placeholder={integrForm._existing ? "•••• unchanged ••••" : ""}
                          onChange={(e) => setIntegrForm({ ...integrForm, auth_credential: e.target.value })} />
                      </div>
                      <div className="rb-form-group">
                        <label>Timeout (seconds)</label>
                        <input type="number" value={integrForm.timeout_seconds} min={1} max={120}
                          onChange={(e) => setIntegrForm({ ...integrForm, timeout_seconds: parseInt(e.target.value) || 10 })} />
                      </div>
                      <div className="rb-checkbox-row">
                        <input type="checkbox" id="intgr-enabled" checked={integrForm.enabled}
                          onChange={(e) => setIntegrForm({ ...integrForm, enabled: e.target.checked })} />
                        <label htmlFor="intgr-enabled">Enabled</label>
                      </div>
                      <div className="rb-checkbox-row">
                        <input type="checkbox" id="intgr-ssl" checked={integrForm.verify_ssl}
                          onChange={(e) => setIntegrForm({ ...integrForm, verify_ssl: e.target.checked })} />
                        <label htmlFor="intgr-ssl">Verify SSL</label>
                      </div>

                      <div className="rb-modal-footer">
                        <button className="rb-btn" onClick={() => setIntegrForm(null)}>Cancel</button>
                        <button
                          className="rb-btn primary"
                          disabled={integrSaving}
                          onClick={saveIntegration}
                        >
                          {integrSaving ? "Saving…" : integrForm._existing ? "Update" : "Create"}
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )
          )}
        </div>
      )}

      {/* Toast */}
      {toast && <div className={`rb-toast ${toast.type}`}>{toast.msg}</div>}
    </div>
  );
}
