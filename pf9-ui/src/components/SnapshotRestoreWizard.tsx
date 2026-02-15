/**
 * Snapshot Restore Wizard Component
 *
 * 3-screen wizard:
 *   Screen 1 — Select Context:  Tenant → VM list (with flavor/network/IP/last-snapshot columns)
 *   Screen 2 — Configure Restore: Mode, snapshot picker, IP strategy, new name → live plan preview
 *   Screen 3 — Review & Execute → Progress tracker
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE } from "../config";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RestoreConfig {
  enabled: boolean;
  dry_run: boolean;
  service_user_configured: boolean;
}

interface Tenant {
  tenant_id: string;
  tenant_name: string;
  domain_name: string;
}

interface VM {
  vm_id: string;
  vm_name: string;
  status: string;
  flavor_name: string | null;
  ips: string | null;
  domain_name: string;
  tenant_name: string;
  project_name: string | null;
  created_at: string | null;
}

interface QuotaResource {
  limit: number;
  in_use: number;
  remaining: number;
}

interface Quota {
  project_id: string;
  instances: QuotaResource;
  cores: QuotaResource;
  ram_mb: QuotaResource;
  volumes: QuotaResource;
  gigabytes: QuotaResource;
}

interface RestorePoint {
  id: string;
  name: string | null;
  volume_id: string;
  size_gb: number | null;
  status: string;
  created_at: string | null;
  description: string | null;
}

interface RestorePointsResponse {
  vm_id: string;
  vm_name: string;
  boot_mode: string;
  boot_mode_supported: boolean;
  volumes: any[];
  restore_points: RestorePoint[];
  message: string | null;
}

interface NetworkPlanEntry {
  network_id: string | null;
  network_name: string | null;
  subnet_id: string | null;
  original_fixed_ip: string | null;
  will_request_fixed_ip: boolean;
  requested_ip: string | null;
  note: string;
}

interface PlanAction {
  step: string;
  details: Record<string, any>;
}

interface RestorePlan {
  plan_id: string;
  job_id: string;
  eligible: boolean;
  boot_mode: string;
  mode: string;
  ip_strategy: string;
  vm: {
    id: string;
    name: string;
    status: string;
    flavor_id: string;
    flavor_name: string | null;
    flavor_vcpus: number | null;
    flavor_ram_mb: number | null;
    flavor_disk_gb: number | null;
  };
  restore_point: {
    id: string;
    name: string | null;
    volume_id: string;
    size_gb: number | null;
    created_at: string | null;
    status: string;
  };
  new_vm_name: string;
  project_id: string;
  quota_check: {
    can_create_new_vm: boolean;
    reasons: string[];
    details: Record<string, any>;
  };
  network_plan: NetworkPlanEntry[];
  actions: PlanAction[];
  warnings: string[];
}

interface JobStep {
  id: number;
  step_order: number;
  step_name: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  details_json: Record<string, any> | null;
  error_text: string | null;
}

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
  plan_json: any;
  result_json: any;
  failure_reason: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  steps: JobStep[];
  progress: {
    total_steps: number;
    completed_steps: number;
    current_step: string | null;
    percent: number;
  };
}

type WizardScreen = "select" | "configure" | "execute";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("auth_token");
  return token ? { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } : { "Content-Type": "application/json" };
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options?.headers || {}) },
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
  }
  return (await res.json()) as T;
}

function formatDateShort(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function stepLabel(name: string): string {
  const labels: Record<string, string> = {
    VALIDATE_LIVE_STATE: "Validate live state",
    ENSURE_SERVICE_USER: "Authenticate service user",
    QUOTA_CHECK: "Verify quota",
    DELETE_EXISTING_VM: "Delete existing VM",
    WAIT_VM_DELETED: "Wait for VM deletion",
    CREATE_VOLUME_FROM_SNAPSHOT: "Create volume from snapshot",
    WAIT_VOLUME_AVAILABLE: "Wait for volume",
    CREATE_PORTS: "Create network ports",
    CREATE_SERVER: "Create server",
    WAIT_SERVER_ACTIVE: "Wait for server active",
    FINALIZE: "Finalize",
  };
  return labels[name] || name;
}

function statusBadge(status: string): React.ReactNode {
  const colors: Record<string, string> = {
    PLANNED: "#2196f3",
    PENDING: "#ff9800",
    RUNNING: "#2196f3",
    SUCCEEDED: "#4caf50",
    FAILED: "#f44336",
    CANCELED: "#9e9e9e",
    INTERRUPTED: "#ff5722",
    SKIPPED: "#9e9e9e",
  };
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: 12,
        fontSize: "0.8rem",
        fontWeight: 600,
        color: "#fff",
        background: colors[status] || "#607d8b",
      }}
    >
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

const SnapshotRestoreWizard: React.FC = () => {
  // Feature config
  const [config, setConfig] = useState<RestoreConfig | null>(null);
  const [configLoading, setConfigLoading] = useState(true);

  // Screen state
  const [screen, setScreen] = useState<WizardScreen>("select");

  // Screen 1: Select
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [selectedTenantId, setSelectedTenantId] = useState<string>("");
  const [vms, setVms] = useState<VM[]>([]);
  const [selectedVmId, setSelectedVmId] = useState<string>("");
  const [quota, setQuota] = useState<Quota | null>(null);
  const [vmSearch, setVmSearch] = useState("");

  // Screen 2: Configure
  const [restorePoints, setRestorePoints] = useState<RestorePointsResponse | null>(null);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string>("");
  const [mode, setMode] = useState<"NEW" | "REPLACE">("NEW");
  const [ipStrategy, setIpStrategy] = useState<"NEW_IPS" | "TRY_SAME_IPS" | "SAME_IPS_OR_FAIL">("NEW_IPS");
  const [newVmName, setNewVmName] = useState("");
  const [plan, setPlan] = useState<RestorePlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  // Screen 3: Execute
  const [job, setJob] = useState<RestoreJob | null>(null);
  const [executing, setExecuting] = useState(false);
  const [executeError, setExecuteError] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState("");

  // Job history
  const [jobHistory, setJobHistory] = useState<any[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  // On-demand snapshot pipeline ("Sync & Snapshot Now")
  const [syncRunning, setSyncRunning] = useState(false);
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const [syncSteps, setSyncSteps] = useState<any[]>([]);
  const syncPollingRef = useRef<number | null>(null);

  // General
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<number | null>(null);

  // -----------------------------------------------------------------------
  // Load feature config on mount
  // -----------------------------------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const cfg = await apiFetch<RestoreConfig>("/restore/config");
        setConfig(cfg);
      } catch {
        setConfig({ enabled: false, dry_run: false, service_user_configured: false });
      } finally {
        setConfigLoading(false);
      }
    })();
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      if (syncPollingRef.current) clearInterval(syncPollingRef.current);
    };
  }, []);

  // -----------------------------------------------------------------------
  // On-Demand Snapshot Pipeline — trigger + poll
  // -----------------------------------------------------------------------
  const triggerSyncAndSnapshot = useCallback(async () => {
    if (syncRunning) return;
    setSyncRunning(true);
    setSyncStatus("running");
    setSyncSteps([]);
    try {
      await apiFetch<any>("/snapshot/run-now", { method: "POST" });
    } catch (e: any) {
      setSyncStatus("failed");
      setSyncRunning(false);
      return;
    }
    // start polling
    syncPollingRef.current = window.setInterval(async () => {
      try {
        const st = await apiFetch<any>("/snapshot/run-now/status");
        setSyncSteps(st.steps || []);
        setSyncStatus(st.status);
        if (st.status !== "running") {
          if (syncPollingRef.current) clearInterval(syncPollingRef.current);
          syncPollingRef.current = null;
          setSyncRunning(false);
          // refresh VMs after pipeline completes
          if (selectedTenantId) {
            try {
              const vmRes = await apiFetch<{ items: VM[] }>(`/tenants/${selectedTenantId}/vms`);
              setVms(vmRes.items || []);
            } catch { /* ignore */ }
          }
        }
      } catch {
        if (syncPollingRef.current) clearInterval(syncPollingRef.current);
        syncPollingRef.current = null;
        setSyncRunning(false);
      }
    }, 3000);
  }, [syncRunning, selectedTenantId]);

  // -----------------------------------------------------------------------
  // Load tenants on mount
  // -----------------------------------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const res = await apiFetch<{ items: Tenant[] }>(`/tenants`);
        setTenants((res.items || []).filter((t) => t.tenant_id !== "__ALL__"));
      } catch (e) {
        console.error("Failed to load tenants", e);
      }
    })();
  }, []);

  // -----------------------------------------------------------------------
  // Load VMs + quota when tenant changes
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (!selectedTenantId) {
      setVms([]);
      setQuota(null);
      return;
    }
    setLoading(true);
    setError(null);

    // Find tenant name for filtering servers
    const t = tenants.find((tn) => tn.tenant_id === selectedTenantId);
    const tenantName = t?.tenant_name || "";

    (async () => {
      try {
        // Load VMs for this tenant
        const vmRes = await apiFetch<{ items: VM[]; total: number }>(
          `/servers?tenant_name=${encodeURIComponent(tenantName)}&page_size=500`
        );
        setVms(vmRes.items || []);

        // Load quota
        try {
          const q = await apiFetch<Quota>(`/restore/quota/${selectedTenantId}`);
          setQuota(q);
        } catch {
          setQuota(null);
        }
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [selectedTenantId, tenants]);

  // -----------------------------------------------------------------------
  // Load restore points when VM is selected on configure screen
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (!selectedVmId || screen !== "configure") return;
    setRestorePoints(null);
    setSelectedSnapshotId("");
    setPlan(null);

    (async () => {
      try {
        const rp = await apiFetch<RestorePointsResponse>(`/restore/vms/${selectedVmId}/restore-points`);
        setRestorePoints(rp);
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, [selectedVmId, screen]);

  // -----------------------------------------------------------------------
  // Load job history
  // -----------------------------------------------------------------------
  const loadJobHistory = useCallback(async () => {
    try {
      const res = await apiFetch<{ jobs: any[] }>(`/restore/jobs?limit=20`);
      setJobHistory(res.jobs || []);
    } catch {
      // silently ignore
    }
  }, []);

  useEffect(() => {
    if (showHistory) loadJobHistory();
  }, [showHistory, loadJobHistory]);

  // -----------------------------------------------------------------------
  // Build plan (debounced)
  // -----------------------------------------------------------------------
  const buildPlan = useCallback(async () => {
    if (!selectedVmId || !selectedSnapshotId || !selectedTenantId) return;
    setPlanLoading(true);
    setPlanError(null);
    setPlan(null);

    try {
      const body = {
        project_id: selectedTenantId,
        vm_id: selectedVmId,
        restore_point_id: selectedSnapshotId,
        mode,
        new_vm_name: newVmName || null,
        ip_strategy: ipStrategy,
      };
      const p = await apiFetch<RestorePlan>("/restore/plan", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setPlan(p);
    } catch (e: any) {
      setPlanError(e.message);
    } finally {
      setPlanLoading(false);
    }
  }, [selectedVmId, selectedSnapshotId, selectedTenantId, mode, newVmName, ipStrategy]);

  // Auto-build plan when selections change
  useEffect(() => {
    if (screen === "configure" && selectedSnapshotId) {
      const timer = setTimeout(buildPlan, 400);
      return () => clearTimeout(timer);
    }
  }, [screen, selectedSnapshotId, mode, ipStrategy, newVmName, buildPlan]);

  // -----------------------------------------------------------------------
  // Execute restore
  // -----------------------------------------------------------------------
  const executeRestore = async () => {
    if (!plan) return;
    setExecuting(true);
    setExecuteError(null);

    try {
      const body: any = { plan_id: plan.job_id };
      if (mode === "REPLACE") {
        body.confirm_destructive = confirmText;
      }
      const res = await apiFetch<{ job_id: string }>("/restore/execute", {
        method: "POST",
        body: JSON.stringify(body),
      });

      // Start polling for progress
      setScreen("execute");
      startPolling(res.job_id);
    } catch (e: any) {
      setExecuteError(e.message);
    } finally {
      setExecuting(false);
    }
  };

  // -----------------------------------------------------------------------
  // Poll job progress
  // -----------------------------------------------------------------------
  const startPolling = (jobId: string) => {
    if (pollingRef.current) clearInterval(pollingRef.current);

    const poll = async () => {
      try {
        const j = await apiFetch<RestoreJob>(`/restore/jobs/${jobId}`);
        setJob(j);
        if (["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(j.status)) {
          if (pollingRef.current) clearInterval(pollingRef.current);
        }
      } catch {
        // continue polling
      }
    };

    poll(); // immediate first call
    pollingRef.current = window.setInterval(poll, 3000);
  };

  // -----------------------------------------------------------------------
  // Cancel job
  // -----------------------------------------------------------------------
  const cancelJob = async () => {
    if (!job) return;
    try {
      await apiFetch(`/restore/jobs/${job.id}/cancel`, {
        method: "POST",
        body: JSON.stringify({ reason: "Canceled by user" }),
      });
    } catch {
      // best effort
    }
  };

  // -----------------------------------------------------------------------
  // Reset wizard
  // -----------------------------------------------------------------------
  const resetWizard = () => {
    setScreen("select");
    setSelectedVmId("");
    setSelectedSnapshotId("");
    setPlan(null);
    setJob(null);
    setExecuteError(null);
    setConfirmText("");
    setMode("NEW");
    setIpStrategy("NEW_IPS");
    setNewVmName("");
    if (pollingRef.current) clearInterval(pollingRef.current);
  };

  // -----------------------------------------------------------------------
  // Render: Loading / Feature disabled
  // -----------------------------------------------------------------------
  if (configLoading) {
    return <div style={{ padding: 32, textAlign: "center" }}>Loading restore configuration...</div>;
  }

  if (config && !config.enabled) {
    return (
      <div style={{ padding: 32, textAlign: "center" }}>
        <h3 style={{ marginBottom: 12 }}>🔒 Snapshot Restore is Disabled</h3>
        <p style={{ color: "#666", maxWidth: 500, margin: "0 auto" }}>
          The restore feature is currently disabled. Set <code>RESTORE_ENABLED=true</code> in your
          environment configuration and restart the API service to enable it.
        </p>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Render: Screen 1 — Select Context
  // -----------------------------------------------------------------------
  const renderSelectScreen = () => {
    const filteredVms = vms.filter(
      (vm) =>
        !vmSearch ||
        vm.vm_name?.toLowerCase().includes(vmSearch.toLowerCase()) ||
        vm.vm_id?.toLowerCase().includes(vmSearch.toLowerCase()) ||
        vm.ips?.toLowerCase().includes(vmSearch.toLowerCase())
    );

    return (
      <div>
        {/* Tenant Selector */}
        <div style={{ display: "flex", gap: 16, alignItems: "flex-end", marginBottom: 20 }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontWeight: 600, display: "block", marginBottom: 6 }}>
              Select Tenant / Project
            </label>
            <select
              value={selectedTenantId}
              onChange={(e) => {
                setSelectedTenantId(e.target.value);
                setSelectedVmId("");
              }}
              style={{ width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid #ccc", fontSize: "0.95rem" }}
            >
              <option value="">— Select a tenant —</option>
              {tenants.map((t) => (
                <option key={t.tenant_id} value={t.tenant_id}>
                  {t.tenant_name} ({t.domain_name})
                </option>
              ))}
            </select>
          </div>

          {/* Sync & Snapshot Now Button */}
          <button
            onClick={triggerSyncAndSnapshot}
            disabled={syncRunning}
            title="Run the full snapshot pipeline now: policy assignment, inventory sync, and auto snapshots"
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: "1px solid #1976d2",
              background: syncRunning ? "#e3f2fd" : "#1976d2",
              color: syncRunning ? "#1976d2" : "#fff",
              fontWeight: 600,
              fontSize: "0.85rem",
              cursor: syncRunning ? "not-allowed" : "pointer",
              whiteSpace: "nowrap",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {syncRunning ? "⏳" : "🔄"} Sync & Snapshot Now
          </button>
        </div>

        {/* On-Demand Pipeline Progress */}
        {syncStatus && syncStatus !== "idle" && (
          <div
            style={{
              marginBottom: 20,
              padding: 14,
              background: syncStatus === "completed" ? "#e8f5e9" : syncStatus === "failed" ? "#fbe9e7" : "#e3f2fd",
              borderRadius: 8,
              border: `1px solid ${syncStatus === "completed" ? "#a5d6a7" : syncStatus === "failed" ? "#ef9a9a" : "#90caf9"}`,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: syncSteps.length ? 10 : 0 }}>
              <span style={{ fontWeight: 600, fontSize: "0.85rem" }}>
                {syncStatus === "running" ? "⏳ Snapshot pipeline running..." :
                 syncStatus === "completed" ? "✅ Snapshot pipeline completed" :
                 "❌ Snapshot pipeline failed"}
              </span>
              {syncStatus !== "running" && (
                <button
                  onClick={() => { setSyncStatus(null); setSyncSteps([]); }}
                  style={{ background: "none", border: "none", cursor: "pointer", fontSize: "0.8rem", color: "#666" }}
                >
                  Dismiss
                </button>
              )}
            </div>
            {syncSteps.length > 0 && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {syncSteps.map((step: any) => (
                  <span
                    key={step.key}
                    style={{
                      padding: "4px 10px",
                      borderRadius: 12,
                      fontSize: "0.78rem",
                      fontWeight: 500,
                      background: step.status === "completed" ? "#c8e6c9" :
                                  step.status === "running" ? "#bbdefb" :
                                  step.status === "failed" ? "#ffcdd2" : "#f5f5f5",
                      color: step.status === "completed" ? "#2e7d32" :
                             step.status === "running" ? "#1565c0" :
                             step.status === "failed" ? "#c62828" : "#757575",
                    }}
                  >
                    {step.status === "completed" ? "✓" :
                     step.status === "running" ? "▶" :
                     step.status === "failed" ? "✗" : "○"}{" "}
                    {step.label}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Quota Summary */}
        {quota && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: 12,
              marginBottom: 20,
              padding: 16,
              background: "var(--pf9-card-bg, #f8f9fa)",
              borderRadius: 8,
              border: "1px solid var(--pf9-border, #e0e0e0)",
            }}
          >
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#666", gridColumn: "1/-1" }}>
              Free Resources in Project
            </div>
            {([
              ["Instances", quota.instances],
              ["vCPUs", quota.cores],
              ["RAM (MB)", quota.ram_mb],
              ["Volumes", quota.volumes],
              ["Storage (GB)", quota.gigabytes],
            ] as [string, QuotaResource][]).map(([label, res]) => (
              <div key={label} style={{ textAlign: "center" }}>
                <div
                  style={{
                    fontSize: "1.4rem",
                    fontWeight: 700,
                    color: res.remaining <= 0 && res.limit > 0 ? "#f44336" : res.remaining <= 2 && res.limit > 0 ? "#ff9800" : "#4caf50",
                  }}
                >
                  {res.limit < 0 ? "∞" : res.remaining}
                </div>
                <div style={{ fontSize: "0.75rem", color: "#888" }}>
                  {label}
                  {res.limit > 0 && <span> ({res.in_use}/{res.limit})</span>}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* VM Search */}
        {selectedTenantId && (
          <div style={{ marginBottom: 12 }}>
            <input
              type="text"
              placeholder="Search VMs by name, ID, or IP..."
              value={vmSearch}
              onChange={(e) => setVmSearch(e.target.value)}
              style={{ width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid #ccc", fontSize: "0.9rem" }}
            />
          </div>
        )}

        {/* VM List */}
        {loading && <div style={{ padding: 20, textAlign: "center", color: "#888" }}>Loading VMs...</div>}
        {error && <div style={{ padding: 12, background: "#fce4ec", color: "#c62828", borderRadius: 6 }}>{error}</div>}

        {!loading && selectedTenantId && filteredVms.length === 0 && (
          <div style={{ padding: 20, textAlign: "center", color: "#888" }}>No VMs found in this tenant.</div>
        )}

        {!loading && filteredVms.length > 0 && (
          <div style={{ maxHeight: 400, overflowY: "auto", border: "1px solid var(--pf9-border, #e0e0e0)", borderRadius: 8 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
              <thead>
                <tr style={{ background: "var(--pf9-header-bg, #f0f0f0)", position: "sticky", top: 0 }}>
                  <th style={{ padding: "8px 12px", textAlign: "left" }}></th>
                  <th style={{ padding: "8px 12px", textAlign: "left" }}>VM Name</th>
                  <th style={{ padding: "8px 12px", textAlign: "left" }}>Status</th>
                  <th style={{ padding: "8px 12px", textAlign: "left" }}>Flavor</th>
                  <th style={{ padding: "8px 12px", textAlign: "left" }}>IPs</th>
                  <th style={{ padding: "8px 12px", textAlign: "left" }}>Created</th>
                </tr>
              </thead>
              <tbody>
                {filteredVms.map((vm) => (
                  <tr
                    key={vm.vm_id}
                    onClick={() => setSelectedVmId(vm.vm_id)}
                    style={{
                      cursor: "pointer",
                      background: selectedVmId === vm.vm_id ? "var(--pf9-selected-bg, #e3f2fd)" : "transparent",
                      borderBottom: "1px solid var(--pf9-border, #eee)",
                    }}
                  >
                    <td style={{ padding: "8px 12px" }}>
                      <input
                        type="radio"
                        checked={selectedVmId === vm.vm_id}
                        onChange={() => setSelectedVmId(vm.vm_id)}
                      />
                    </td>
                    <td style={{ padding: "8px 12px", fontWeight: 500 }}>{vm.vm_name}</td>
                    <td style={{ padding: "8px 12px" }}>
                      <span
                        style={{
                          padding: "2px 8px",
                          borderRadius: 10,
                          fontSize: "0.78rem",
                          fontWeight: 600,
                          color: "#fff",
                          background: vm.status === "ACTIVE" ? "#4caf50" : vm.status === "SHUTOFF" ? "#ff9800" : "#9e9e9e",
                        }}
                      >
                        {vm.status}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px" }}>{vm.flavor_name || "—"}</td>
                    <td style={{ padding: "8px 12px", fontFamily: "monospace", fontSize: "0.82rem" }}>{vm.ips || "—"}</td>
                    <td style={{ padding: "8px 12px" }}>{formatDateShort(vm.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Navigate forward */}
        <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end", gap: 12 }}>
          <button
            onClick={() => setShowHistory(!showHistory)}
            style={{
              padding: "10px 20px",
              borderRadius: 6,
              border: "1px solid #ccc",
              background: "white",
              cursor: "pointer",
              fontSize: "0.9rem",
            }}
          >
            {showHistory ? "Hide" : "📋"} Job History
          </button>
          <button
            disabled={!selectedVmId}
            onClick={() => setScreen("configure")}
            style={{
              padding: "10px 24px",
              borderRadius: 6,
              border: "none",
              background: selectedVmId ? "#1976d2" : "#ccc",
              color: "#fff",
              cursor: selectedVmId ? "pointer" : "default",
              fontWeight: 600,
              fontSize: "0.95rem",
            }}
          >
            Configure Restore →
          </button>
        </div>

        {/* Job History Panel */}
        {showHistory && (
          <div style={{ marginTop: 20 }}>
            <h4 style={{ margin: "0 0 12px 0" }}>Recent Restore Jobs</h4>
            {jobHistory.length === 0 ? (
              <p style={{ color: "#888" }}>No restore jobs yet.</p>
            ) : (
              <div style={{ maxHeight: 300, overflowY: "auto", border: "1px solid #e0e0e0", borderRadius: 8 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
                  <thead>
                    <tr style={{ background: "#f0f0f0", position: "sticky", top: 0 }}>
                      <th style={{ padding: "6px 10px", textAlign: "left" }}>VM</th>
                      <th style={{ padding: "6px 10px", textAlign: "left" }}>Mode</th>
                      <th style={{ padding: "6px 10px", textAlign: "left" }}>Status</th>
                      <th style={{ padding: "6px 10px", textAlign: "left" }}>Created</th>
                      <th style={{ padding: "6px 10px", textAlign: "left" }}>By</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobHistory.map((j: any) => (
                      <tr
                        key={j.id}
                        style={{ borderBottom: "1px solid #eee", cursor: "pointer" }}
                        onClick={() => {
                          startPolling(j.id);
                          setScreen("execute");
                        }}
                      >
                        <td style={{ padding: "6px 10px" }}>{j.vm_name || j.vm_id}</td>
                        <td style={{ padding: "6px 10px" }}>{j.mode}</td>
                        <td style={{ padding: "6px 10px" }}>{statusBadge(j.status)}</td>
                        <td style={{ padding: "6px 10px" }}>{formatDateShort(j.created_at)}</td>
                        <td style={{ padding: "6px 10px" }}>{j.created_by}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  // -----------------------------------------------------------------------
  // Render: Screen 2 — Configure Restore
  // -----------------------------------------------------------------------
  const renderConfigureScreen = () => {
    const selectedVm = vms.find((v) => v.vm_id === selectedVmId);
    const selectedSnapshot = restorePoints?.restore_points.find((s) => s.id === selectedSnapshotId);

    return (
      <div>
        {/* VM Summary */}
        <div
          style={{
            padding: 14,
            marginBottom: 20,
            background: "var(--pf9-card-bg, #f8f9fa)",
            borderRadius: 8,
            border: "1px solid var(--pf9-border, #e0e0e0)",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            Restoring: {selectedVm?.vm_name || selectedVmId}
          </div>
          <div style={{ fontSize: "0.85rem", color: "#666" }}>
            Status: {selectedVm?.status} · Flavor: {selectedVm?.flavor_name || "—"} · IPs: {selectedVm?.ips || "—"}
          </div>
          {restorePoints && !restorePoints.boot_mode_supported && (
            <div
              style={{
                marginTop: 10,
                padding: 10,
                background: "#fff3e0",
                borderRadius: 6,
                color: "#e65100",
                fontSize: "0.88rem",
              }}
            >
              ⚠️ {restorePoints.message}
            </div>
          )}
        </div>

        {/* Two columns: Config + Plan preview */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
          {/* Left: Configuration */}
          <div>
            {/* Restore Mode */}
            <div style={{ marginBottom: 18 }}>
              <label style={{ fontWeight: 600, display: "block", marginBottom: 8 }}>Restore Mode</label>
              <div style={{ display: "flex", gap: 12 }}>
                <label
                  style={{
                    flex: 1,
                    padding: 12,
                    border: `2px solid ${mode === "NEW" ? "#1976d2" : "#ddd"}`,
                    borderRadius: 8,
                    cursor: "pointer",
                    background: mode === "NEW" ? "#e3f2fd" : "white",
                  }}
                >
                  <input
                    type="radio"
                    name="mode"
                    value="NEW"
                    checked={mode === "NEW"}
                    onChange={() => setMode("NEW")}
                    style={{ marginRight: 8 }}
                  />
                  <strong>Side-by-Side</strong>
                  <div style={{ fontSize: "0.8rem", color: "#666", marginTop: 4 }}>
                    Create new VM alongside existing. Safe, no data loss.
                  </div>
                </label>
                <label
                  style={{
                    flex: 1,
                    padding: 12,
                    border: `2px solid ${mode === "REPLACE" ? "#f44336" : "#ddd"}`,
                    borderRadius: 8,
                    cursor: "pointer",
                    background: mode === "REPLACE" ? "#fce4ec" : "white",
                  }}
                >
                  <input
                    type="radio"
                    name="mode"
                    value="REPLACE"
                    checked={mode === "REPLACE"}
                    onChange={() => setMode("REPLACE")}
                    style={{ marginRight: 8 }}
                  />
                  <strong>⚠️ Replace Existing</strong>
                  <div style={{ fontSize: "0.8rem", color: "#666", marginTop: 4 }}>
                    Delete VM, then recreate from snapshot. Destructive!
                  </div>
                </label>
              </div>
            </div>

            {/* Snapshot Picker */}
            <div style={{ marginBottom: 18 }}>
              <label style={{ fontWeight: 600, display: "block", marginBottom: 8 }}>
                Restore Point (Snapshot)
              </label>
              {!restorePoints ? (
                <div style={{ color: "#888" }}>Loading snapshots...</div>
              ) : restorePoints.restore_points.length === 0 ? (
                <div style={{ color: "#888", background: "#fff3e0", padding: 12, borderRadius: 6 }}>
                  No available snapshots found for this VM's volumes.
                </div>
              ) : (
                <div style={{ maxHeight: 200, overflowY: "auto", border: "1px solid #ddd", borderRadius: 6 }}>
                  {restorePoints.restore_points.map((rp) => (
                    <label
                      key={rp.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: "8px 12px",
                        borderBottom: "1px solid #eee",
                        cursor: "pointer",
                        background: selectedSnapshotId === rp.id ? "#e3f2fd" : "transparent",
                      }}
                    >
                      <input
                        type="radio"
                        name="snapshot"
                        checked={selectedSnapshotId === rp.id}
                        onChange={() => setSelectedSnapshotId(rp.id)}
                      />
                      <div>
                        <div style={{ fontWeight: 500, fontSize: "0.9rem" }}>
                          {formatDateShort(rp.created_at)}
                        </div>
                        <div style={{ fontSize: "0.78rem", color: "#888" }}>
                          {rp.name || rp.id.slice(0, 8)} · {rp.size_gb || "?"}GB · {rp.status}
                        </div>
                      </div>
                    </label>
                  ))}
                </div>
              )}
            </div>

            {/* IP Strategy */}
            <div style={{ marginBottom: 18 }}>
              <label style={{ fontWeight: 600, display: "block", marginBottom: 8 }}>IP Strategy</label>
              <select
                value={ipStrategy}
                onChange={(e) => setIpStrategy(e.target.value as any)}
                style={{ width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid #ccc" }}
              >
                <option value="NEW_IPS">Allocate new IPs (safest)</option>
                <option value="TRY_SAME_IPS">Try to keep same IPs (best effort)</option>
                <option value="SAME_IPS_OR_FAIL">Must keep same IPs (fail if unavailable)</option>
              </select>
            </div>

            {/* New VM Name */}
            <div style={{ marginBottom: 18 }}>
              <label style={{ fontWeight: 600, display: "block", marginBottom: 8 }}>
                New VM Name <span style={{ fontWeight: 400, color: "#888" }}>(optional)</span>
              </label>
              <input
                type="text"
                value={newVmName}
                onChange={(e) => setNewVmName(e.target.value)}
                placeholder={mode === "REPLACE" ? selectedVm?.vm_name || "Same as original" : "Auto-generated if empty"}
                style={{ width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid #ccc" }}
              />
            </div>
          </div>

          {/* Right: Plan Preview */}
          <div>
            <div style={{ fontWeight: 600, marginBottom: 12 }}>
              Restore Plan Preview
            </div>

            {planLoading && <div style={{ color: "#888", padding: 20 }}>Building plan...</div>}
            {planError && (
              <div style={{ padding: 12, background: "#fce4ec", color: "#c62828", borderRadius: 6 }}>
                {planError}
              </div>
            )}

            {plan && (
              <div>
                {/* Eligibility */}
                {!plan.eligible && (
                  <div style={{ padding: 12, background: "#fce4ec", color: "#c62828", borderRadius: 6, marginBottom: 12 }}>
                    <strong>Not eligible for restore:</strong>
                    <ul style={{ margin: "4px 0 0 16px" }}>
                      {plan.quota_check.reasons.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Warnings */}
                {plan.warnings.length > 0 && (
                  <div style={{ padding: 12, background: "#fff3e0", color: "#e65100", borderRadius: 6, marginBottom: 12, fontSize: "0.88rem" }}>
                    {plan.warnings.map((w, i) => (
                      <div key={i} style={{ marginBottom: i < plan.warnings.length - 1 ? 6 : 0 }}>{w}</div>
                    ))}
                  </div>
                )}

                {/* VM Info */}
                <div style={{ padding: 12, background: "#f5f5f5", borderRadius: 6, marginBottom: 12, fontSize: "0.85rem" }}>
                  <div><strong>Source VM:</strong> {plan.vm.name} ({plan.vm.status})</div>
                  <div><strong>Flavor:</strong> {plan.vm.flavor_name} — {plan.vm.flavor_vcpus} vCPU / {plan.vm.flavor_ram_mb}MB RAM / {plan.vm.flavor_disk_gb}GB disk</div>
                  <div><strong>New Name:</strong> {plan.new_vm_name}</div>
                  <div><strong>Snapshot:</strong> {plan.restore_point.name || plan.restore_point.id.slice(0, 8)} ({formatDateShort(plan.restore_point.created_at)})</div>
                  <div>
                    <strong>Cloud-Init:</strong>{" "}
                    {(plan.vm as any).user_data ? (
                      <span style={{ color: "#2e7d32" }}>✅ Will be preserved (original user_data re-applied)</span>
                    ) : (
                      <span style={{ color: "#e65100" }}>⚠️ No user_data found — cloud-init may reset credentials on first boot</span>
                    )}
                  </div>
                </div>

                {/* Network Plan */}
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontWeight: 600, fontSize: "0.85rem", marginBottom: 6 }}>Network Mapping</div>
                  {plan.network_plan.map((n, i) => (
                    <div
                      key={i}
                      style={{
                        padding: "6px 10px",
                        background: "#fafafa",
                        borderRadius: 4,
                        marginBottom: 4,
                        fontSize: "0.82rem",
                        border: "1px solid #eee",
                      }}
                    >
                      <span style={{ fontWeight: 500 }}>{n.network_name || n.network_id || "Unknown"}</span>
                      {n.original_fixed_ip && (
                        <span style={{ color: "#888", marginLeft: 8 }}>
                          (was: {n.original_fixed_ip})
                        </span>
                      )}
                      <span style={{ color: "#1976d2", marginLeft: 8 }}>{n.note}</span>
                    </div>
                  ))}
                </div>

                {/* Action Steps */}
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontWeight: 600, fontSize: "0.85rem", marginBottom: 6 }}>Execution Steps</div>
                  <ol style={{ margin: 0, paddingLeft: 20, fontSize: "0.82rem" }}>
                    {plan.actions.map((a, i) => (
                      <li key={i} style={{ marginBottom: 3 }}>
                        {stepLabel(a.step)}
                      </li>
                    ))}
                  </ol>
                </div>

                {/* REPLACE confirmation */}
                {mode === "REPLACE" && (
                  <div style={{ padding: 12, background: "#fce4ec", borderRadius: 6, marginBottom: 12 }}>
                    <label style={{ fontWeight: 600, fontSize: "0.85rem", display: "block", marginBottom: 8 }}>
                      Type <code>DELETE AND RESTORE {plan.vm.name}</code> to confirm:
                    </label>
                    <input
                      type="text"
                      value={confirmText}
                      onChange={(e) => setConfirmText(e.target.value)}
                      placeholder={`DELETE AND RESTORE ${plan.vm.name}`}
                      style={{
                        width: "100%",
                        padding: "8px 12px",
                        borderRadius: 6,
                        border: "2px solid #f44336",
                        fontFamily: "monospace",
                      }}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Navigation */}
        {executeError && (
          <div style={{ padding: 12, background: "#fce4ec", color: "#c62828", borderRadius: 6, marginTop: 12 }}>
            {executeError}
          </div>
        )}

        <div style={{ marginTop: 20, display: "flex", justifyContent: "space-between" }}>
          <button
            onClick={() => {
              setScreen("select");
              setPlan(null);
              setSelectedSnapshotId("");
            }}
            style={{
              padding: "10px 24px",
              borderRadius: 6,
              border: "1px solid #ccc",
              background: "white",
              cursor: "pointer",
              fontSize: "0.95rem",
            }}
          >
            ← Back
          </button>
          <button
            disabled={!plan || !plan.eligible || executing || (mode === "REPLACE" && confirmText !== `DELETE AND RESTORE ${plan?.vm.name}`)}
            onClick={executeRestore}
            style={{
              padding: "10px 28px",
              borderRadius: 6,
              border: "none",
              background:
                plan && plan.eligible && !executing
                  ? mode === "REPLACE"
                    ? "#f44336"
                    : "#4caf50"
                  : "#ccc",
              color: "#fff",
              cursor: plan && plan.eligible && !executing ? "pointer" : "default",
              fontWeight: 700,
              fontSize: "0.95rem",
            }}
          >
            {executing
              ? "Starting..."
              : mode === "REPLACE"
              ? "⚠️ Delete & Restore"
              : "Execute Restore"}
          </button>
        </div>
      </div>
    );
  };

  // -----------------------------------------------------------------------
  // Render: Screen 3 — Execute / Progress
  // -----------------------------------------------------------------------
  const renderExecuteScreen = () => {
    if (!job) {
      return <div style={{ padding: 32, textAlign: "center", color: "#888" }}>Starting restore job...</div>;
    }

    const isTerminal = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"].includes(job.status);

    return (
      <div>
        {/* Job Header */}
        <div
          style={{
            padding: 16,
            marginBottom: 20,
            background: "var(--pf9-card-bg, #f8f9fa)",
            borderRadius: 8,
            border: "1px solid var(--pf9-border, #e0e0e0)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div>
            <div style={{ fontWeight: 600, fontSize: "1.05rem" }}>
              Restoring: {job.vm_name || job.vm_id}
            </div>
            <div style={{ fontSize: "0.85rem", color: "#888", marginTop: 4 }}>
              Mode: {job.mode} · IP Strategy: {job.ip_strategy} · New Name: {job.requested_name || "—"}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {statusBadge(job.status)}
            {!isTerminal && (
              <button
                onClick={cancelJob}
                style={{
                  padding: "6px 16px",
                  borderRadius: 6,
                  border: "1px solid #f44336",
                  background: "white",
                  color: "#f44336",
                  cursor: "pointer",
                  fontWeight: 600,
                  fontSize: "0.85rem",
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </div>

        {/* Progress Bar */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, fontSize: "0.85rem" }}>
            <span>Progress: {job.progress.completed_steps}/{job.progress.total_steps} steps</span>
            <span>{job.progress.percent}%</span>
          </div>
          <div style={{ height: 8, background: "#e0e0e0", borderRadius: 4, overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${job.progress.percent}%`,
                background:
                  job.status === "FAILED"
                    ? "#f44336"
                    : job.status === "SUCCEEDED"
                    ? "#4caf50"
                    : "#1976d2",
                borderRadius: 4,
                transition: "width 0.5s ease",
              }}
            />
          </div>
        </div>

        {/* Steps */}
        <div style={{ marginBottom: 24 }}>
          {job.steps.map((step) => {
            const isActive = step.status === "RUNNING";
            const isComplete = step.status === "SUCCEEDED";
            const isFailed = step.status === "FAILED";

            return (
              <div
                key={step.id}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 12,
                  padding: "10px 14px",
                  marginBottom: 4,
                  borderRadius: 6,
                  background: isActive
                    ? "#e3f2fd"
                    : isFailed
                    ? "#fce4ec"
                    : isComplete
                    ? "#e8f5e9"
                    : "transparent",
                  border: isActive ? "1px solid #90caf9" : "1px solid transparent",
                }}
              >
                {/* Status icon */}
                <div style={{ fontSize: "1.1rem", minWidth: 24, textAlign: "center" }}>
                  {isComplete ? "✅" : isFailed ? "❌" : isActive ? "🔄" : "⏳"}
                </div>
                {/* Step info */}
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: "0.9rem" }}>
                    {step.step_order}. {stepLabel(step.step_name)}
                  </div>
                  {(step.started_at || step.finished_at) && (
                    <div style={{ fontSize: "0.78rem", color: "#888", marginTop: 2 }}>
                      {step.started_at && `Started: ${formatDateShort(step.started_at)}`}
                      {step.finished_at && ` · Finished: ${formatDateShort(step.finished_at)}`}
                    </div>
                  )}
                  {step.error_text && (
                    <div
                      style={{
                        marginTop: 4,
                        padding: "4px 8px",
                        background: "#ffebee",
                        borderRadius: 4,
                        fontSize: "0.82rem",
                        color: "#c62828",
                        fontFamily: "monospace",
                      }}
                    >
                      {step.error_text}
                    </div>
                  )}
                  {step.details_json && step.status === "SUCCEEDED" && step.step_name === "WAIT_SERVER_ACTIVE" && (
                    <div style={{ marginTop: 4, fontSize: "0.82rem" }}>
                      {(step.details_json as any).final_ips?.map((ip: any, i: number) => (
                        <span key={i} style={{ marginRight: 12, fontFamily: "monospace" }}>
                          {ip.network}: {ip.ip}
                        </span>
                      ))}
                    </div>
                  )}
                  {step.details_json && step.status === "SUCCEEDED" && step.step_name === "CREATE_SERVER" && (
                    <div style={{ marginTop: 4, fontSize: "0.82rem", color: (step.details_json as any).user_data_preserved ? "#2e7d32" : "#e65100" }}>
                      {(step.details_json as any).user_data_preserved
                        ? "✅ Cloud-init user_data preserved"
                        : "⚠️ No cloud-init user_data — credentials may need manual reset"}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Failure reason */}
        {job.failure_reason && (
          <div style={{ padding: 12, background: "#fce4ec", color: "#c62828", borderRadius: 6, marginBottom: 16, fontSize: "0.9rem" }}>
            <strong>Failure:</strong> {job.failure_reason}
          </div>
        )}

        {/* Success summary */}
        {job.status === "SUCCEEDED" && job.result_json && (
          <div style={{ padding: 16, background: "#e8f5e9", borderRadius: 8, marginBottom: 16 }}>
            <div style={{ fontWeight: 700, color: "#2e7d32", marginBottom: 8, fontSize: "1rem" }}>
              ✅ Restore Completed Successfully
            </div>
            <div style={{ fontSize: "0.88rem" }}>
              <div><strong>New Server ID:</strong> <code>{job.result_json.server_id}</code></div>
              <div><strong>New Volume ID:</strong> <code>{job.result_json.volume_id}</code></div>
              {job.result_json.port_ids?.length > 0 && (
                <div><strong>Ports:</strong> {job.result_json.port_ids.join(", ")}</div>
              )}
            </div>
          </div>
        )}

        {/* Back button */}
        <div style={{ display: "flex", justifyContent: "flex-start" }}>
          <button
            onClick={resetWizard}
            style={{
              padding: "10px 24px",
              borderRadius: 6,
              border: "1px solid #ccc",
              background: "white",
              cursor: "pointer",
              fontSize: "0.95rem",
            }}
          >
            ← Start New Restore
          </button>
        </div>
      </div>
    );
  };

  // -----------------------------------------------------------------------
  // Main render
  // -----------------------------------------------------------------------
  return (
    <div style={{ padding: "0 0 32px 0" }}>
      {/* Wizard Header / Breadcrumb */}
      <div
        style={{
          display: "flex",
          gap: 0,
          marginBottom: 24,
          borderBottom: "2px solid #e0e0e0",
          paddingBottom: 0,
        }}
      >
        {(["select", "configure", "execute"] as WizardScreen[]).map((s, i) => {
          const labels = ["1. Select VM", "2. Configure", "3. Execute"];
          const isActive = screen === s;
          const isPast =
            (s === "select" && (screen === "configure" || screen === "execute")) ||
            (s === "configure" && screen === "execute");

          return (
            <div
              key={s}
              style={{
                flex: 1,
                padding: "12px 16px",
                textAlign: "center",
                fontWeight: isActive ? 700 : 500,
                fontSize: "0.95rem",
                color: isActive ? "#1976d2" : isPast ? "#4caf50" : "#999",
                borderBottom: isActive ? "3px solid #1976d2" : isPast ? "3px solid #4caf50" : "3px solid transparent",
                cursor: isPast ? "pointer" : "default",
              }}
              onClick={() => {
                if (isPast) {
                  if (s === "select") resetWizard();
                  else setScreen(s);
                }
              }}
            >
              {isPast ? "✓ " : ""}
              {labels[i]}
            </div>
          );
        })}
      </div>

      {/* Screen content */}
      {screen === "select" && renderSelectScreen()}
      {screen === "configure" && renderConfigureScreen()}
      {screen === "execute" && renderExecuteScreen()}
    </div>
  );
};

export default SnapshotRestoreWizard;
