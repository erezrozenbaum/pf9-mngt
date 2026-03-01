/**
 * SourceAnalysis — Post-upload view showing VM inventory, tenant assignment,
 *                  risk/complexity scoring, migration mode classification,
 *                  and assessment controls.
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE } from "../../config";
import type { MigrationProject } from "../MigrationPlannerTab";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function getToken(): string | null {
  return localStorage.getItem("auth_token");
}

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(opts?.headers as Record<string, string> || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  if (!(opts?.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = err.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d: any) => `${(d.loc || []).join('.')}: ${d.msg}`).join('; ')
      : (detail || `API error ${res.status}`);
    throw new Error(msg);
  }
  return res.json();
}

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface MigrationVM {
  vm_id: string;
  vm_name: string;
  cpu_count: number;
  ram_mb: number;
  total_disk_gb: number;
  in_use_mb: number;
  in_use_gb: number;
  partition_used_gb: number;
  provisioned_mb: number;
  guest_os: string;
  os_family: string;
  os_version: string;
  power_state: string;
  folder_path: string;
  resource_pool: string;
  vapp_name: string;
  host_name: string;
  cluster: string;
  datacenter: string;
  disk_count: number;
  nic_count: number;
  network_name: string;
  snapshot_count: number;
  primary_ip: string;
  dns_name: string;
  tenant_name: string | null;
  org_vdc: string | null;
  risk_score: number | null;
  risk_category: string | null;
  risk_reasons?: string[] | null;
  migration_mode: string | null;
  estimated_minutes: number | null;
  cpu_usage_percent: number | null;
  memory_usage_percent: number | null;
  cpu_demand_mhz: number | null;
  memory_usage_mb: number | null;
  // Phase 2.10
  id?: number;
  migration_status?: string;
  migration_status_note?: string;
  migration_mode_override?: string | null;
}

interface Tenant {
  id: number;  // actual DB primary key returned by API
  tenant_id?: number;  // deprecated alias
  tenant_name: string;
  org_vdc: string | null;
  detection_method: string;
  vm_count: number;
  total_vcpu: number;
  total_ram_mb: number;
  total_disk_gb: number;
  total_in_use_gb: number;
  // Phase 2A
  include_in_plan: boolean;
  exclude_reason: string | null;
  // Phase 2B
  target_domain_name: string | null;
  target_project_name: string | null;
  target_display_name: string | null;       // project description / friendly name
  target_domain_description: string | null; // domain description
  target_confirmed?: boolean;  // false = auto-seeded, needs review
  // Phase 2.10
  migration_priority?: number;
  cohort_id?: number | null;
  cohort_name?: string | null;
}

// Phase 3.0 — Tenant Ease Score
interface TenantEaseScore {
  tenant_id: number;
  tenant_name: string;
  ease_score: number;
  ease_label: "Easy" | "Medium" | "Hard";
  vm_count: number;
  total_used_gb: number;
  avg_risk_score: number;
  os_support_rate: number;
  distinct_network_count: number;
  cross_tenant_dep_count: number;
  cold_vm_ratio: number;
  unconfirmed_ratio: number;
  dimension_scores: Record<string, number>;
  dimension_weights: Record<string, number>;
}

interface NetworkSummary {
  id: number;
  network_name: string;
  vlan_id: number | null;
  network_type: string;
  vm_count: number;
  subnet: string | null;
  gateway: string | null;
  dns_servers: string | null;
  ip_range: string | null;
  pcd_target: string | null;
  notes: string | null;
}

interface Props {
  project: MigrationProject;
  onProjectUpdated: (p: MigrationProject) => void;
}

type SubView = "dashboard" | "vms" | "tenants" | "cohorts" | "waves" | "networks" | "netmap" | "users" | "risk" | "plan" | "capacity" | "readiness" | "prepare";

// Phase 3 — Wave Planning types
interface Wave {
  id: number;
  project_id: string;
  wave_number: number;
  name: string;
  wave_type: "pilot" | "regular" | "cleanup";
  cohort_id: number | null;
  cohort_name?: string;
  status: "planned" | "pre_checks_passed" | "executing" | "validating" | "complete" | "failed" | "cancelled";
  agent_slots_override: number | null;
  scheduled_start: string | null;
  scheduled_end: string | null;
  owner_name: string | null;
  notes: string | null;
  vm_count: number;
  started_at: string | null;
  completed_at: string | null;
  vms?: WaveVM[];
}

interface WaveVM {
  id: number;
  vm_name: string;
  tenant_name: string;
  risk_category: string;
  migration_mode: string;
  migration_status: string;
  total_disk_gb: number;
  in_use_gb: number;
  wave_vm_status: string;
  migration_order: number;
}

interface WavePreflight {
  id: number;
  check_name: string;
  check_label: string;
  check_status: "pending" | "pass" | "fail" | "skipped" | "na";
  severity: "info" | "warning" | "blocker";
  notes: string | null;
  checked_at: string | null;
}

interface MigrationFunnel {
  total: number;
  not_started?: number;
  assigned?: number;
  in_progress?: number;
  migrated?: number;
  failed?: number;
  skipped?: number;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function SourceAnalysis({ project, onProjectUpdated }: Props) {
  const pid = project.project_id;
  const [subView, setSubView] = useState<SubView>("dashboard");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  /* ---- Data ---- */
  const [stats, setStats] = useState<any>(null);
  const [vms, setVms] = useState<MigrationVM[]>([]);
  const [vmTotal, setVmTotal] = useState(0);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [hosts, setHosts] = useState<any[]>([]);
  const [clusters, setClusters] = useState<any[]>([]);
  const [riskConfig, setRiskConfig] = useState<any>(null);

  /* ---- VM filters ---- */
  const [vmPage, setVmPage] = useState(1);
  const [vmLimit] = useState(50);
  const [vmSort, setVmSort] = useState("vm_name");
  const [vmOrder, setVmOrder] = useState("asc");
  const [vmSearch, setVmSearch] = useState("");
  const [vmRisk, setVmRisk] = useState("");
  const [vmMode, setVmMode] = useState("");
  const [vmTenant, setVmTenant] = useState("");
  const [vmOsFamily, setVmOsFamily] = useState("");
  const [vmOsVersion, setVmOsVersion] = useState("");
  const [vmPower, setVmPower] = useState("");
  const [vmCluster, setVmCluster] = useState("");

  /* ---- VM detail expansion ---- */
  const [expandedVm, setExpandedVm] = useState<string | null>(null);
  const [expandedVmData, setExpandedVmData] = useState<MigrationVM | null>(null);
  const [vmDisks, setVmDisks] = useState<any[]>([]);
  const [vmNics, setVmNics] = useState<any[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  /* Phase 2.10 — VM deps, status, mode override ---- */
  const [vmDeps, setVmDeps] = useState<any[]>([]);
  const [depsLoading, setDepsLoading] = useState(false);
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [modeOverrideUpdating, setModeOverrideUpdating] = useState(false);
  const [vmStatusLocal, setVmStatusLocal] = useState<Record<string, string>>({});
  const [vmModeOverrideLocal, setVmModeOverrideLocal] = useState<Record<string, string | null>>({});

  /* ---- Networks ---- */
  const [networks, setNetworks] = useState<NetworkSummary[]>([]);

  /* ---- Loaders ---- */
  const loadStats = useCallback(async () => {
    try {
      const data = await apiFetch<{ stats: any }>(`/api/migration/projects/${pid}/stats`);
      setStats(data.stats);
    } catch {}
  }, [pid]);

  const loadVMs = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        sort_by: vmSort, sort_dir: vmOrder,
        limit: String(vmLimit),
        offset: String((vmPage - 1) * vmLimit),
      });
      if (vmSearch) params.set("search", vmSearch);
      if (vmRisk) params.set("risk", vmRisk);
      if (vmMode) params.set("mode", vmMode);
      if (vmTenant) params.set("tenant", vmTenant);
      if (vmOsFamily) params.set("os_family", vmOsFamily);
      if (vmOsVersion) params.set("os_version", vmOsVersion);
      if (vmPower) params.set("power_state", vmPower);
      if (vmCluster) params.set("cluster", vmCluster);
      const data = await apiFetch<{ vms: MigrationVM[]; total: number }>(
        `/api/migration/projects/${pid}/vms?${params}`
      );
      setVms(data.vms);
      setVmTotal(data.total);
    } catch {}
  }, [pid, vmPage, vmLimit, vmSort, vmOrder, vmSearch, vmRisk, vmMode, vmTenant, vmOsFamily, vmOsVersion, vmPower, vmCluster]);

  const loadVmDetails = useCallback(async (vmName: string) => {
    setDetailLoading(true);
    try {
      const data = await apiFetch<{ disks: any[]; nics: any[] }>(
        `/api/migration/projects/${pid}/vms/${encodeURIComponent(vmName)}/details`
      );
      setVmDisks(data.disks);
      setVmNics(data.nics);
    } catch { setVmDisks([]); setVmNics([]); }
    finally { setDetailLoading(false); }
  }, [pid]);

  const toggleVmExpand = (vm: MigrationVM) => {
    if (expandedVm === vm.vm_name) {
      setExpandedVm(null);
      setExpandedVmData(null);
      setVmDeps([]);
    } else {
      setExpandedVm(vm.vm_name);
      setExpandedVmData(vm);
      loadVmDetails(vm.vm_name);
      if (vm.id) loadVmDeps(vm.id);
    }
  };

  const loadVmDeps = useCallback(async (vmId: number) => {
    setDepsLoading(true);
    try {
      const data = await apiFetch<{ dependencies: any[] }>(
        `/api/migration/projects/${pid}/vm-dependencies?vm_id=${vmId}`
      );
      setVmDeps(data.dependencies);
    } catch { setVmDeps([]); }
    finally { setDepsLoading(false); }
  }, [pid]);

  const updateVmStatus = async (vmId: number, status: string) => {
    setStatusUpdating(true);
    try {
      await apiFetch(`/api/migration/projects/${pid}/vms/${vmId}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setVmStatusLocal(prev => ({ ...prev, [vmId]: status }));
      loadVMs();
    } catch (e: any) { alert(e.message); }
    finally { setStatusUpdating(false); }
  };

  const updateVmModeOverride = async (vmId: number, override: string | null) => {
    setModeOverrideUpdating(true);
    try {
      await apiFetch(`/api/migration/projects/${pid}/vms/${vmId}/mode-override`, {
        method: "PATCH",
        body: JSON.stringify({ override }),
      });
      setVmModeOverrideLocal(prev => ({ ...prev, [vmId]: override }));
      loadVMs();
    } catch (e: any) { alert(e.message); }
    finally { setModeOverrideUpdating(false); }
  };

  const loadTenants = useCallback(async () => {
    try {
      const data = await apiFetch<{ tenants: Tenant[] }>(`/api/migration/projects/${pid}/tenants`);
      setTenants(data.tenants);
    } catch {}
  }, [pid]);

  const loadHosts = useCallback(async () => {
    try {
      const data = await apiFetch<{ hosts: any[] }>(`/api/migration/projects/${pid}/hosts`);
      setHosts(data.hosts);
    } catch {}
  }, [pid]);

  const loadClusters = useCallback(async () => {
    try {
      const data = await apiFetch<{ clusters: any[] }>(`/api/migration/projects/${pid}/clusters`);
      setClusters(data.clusters);
    } catch {}
  }, [pid]);

  const loadNetworks = useCallback(async () => {
    try {
      const data = await apiFetch<{ networks: NetworkSummary[] }>(`/api/migration/projects/${pid}/networks`);
      setNetworks(data.networks);
    } catch {}
  }, [pid]);

  const loadRiskConfig = useCallback(async () => {
    try {
      const data = await apiFetch<{ config: any }>(`/api/migration/projects/${pid}/risk-config`);
      setRiskConfig(data.config);
    } catch {}
  }, [pid]);

  useEffect(() => { loadStats(); loadTenants(); loadNetworks(); }, [loadStats, loadTenants, loadNetworks]);
  useEffect(() => { loadVMs(); }, [loadVMs]);
  useEffect(() => {
    if (subView === "dashboard" || subView === "vms") { loadHosts(); loadClusters(); }
  }, [subView, loadHosts, loadClusters]);
  useEffect(() => {
    if (subView === "risk") { loadRiskConfig(); }
  }, [subView, loadRiskConfig]);

  /* ---- Actions ---- */
  const runAssessment = async () => {
    setLoading(true);
    setError("");
    try {
      await apiFetch<any>(`/api/migration/projects/${pid}/assess`, { method: "POST" });
      await loadStats();
      await loadVMs();
      const proj = await apiFetch<{ project: MigrationProject }>(`/api/migration/projects/${pid}`);
      onProjectUpdated(proj.project);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const resetAssessment = async () => {
    if (!confirm("Clear all computed risk scores and migration modes? Source data will be kept.")) return;
    setLoading(true);
    try {
      await apiFetch<any>(`/api/migration/projects/${pid}/reset-assessment`, { method: "POST" });
      await loadStats();
      await loadVMs();
      const proj = await apiFetch<{ project: MigrationProject }>(`/api/migration/projects/${pid}`);
      onProjectUpdated(proj.project);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  /* ---- Approve ---- */
  const approveProject = async () => {
    if (!confirm("Approve this migration project? This enables PCD target preparation.")) return;
    try {
      const data = await apiFetch<{ project: MigrationProject }>(
        `/api/migration/projects/${pid}/approve`, { method: "POST" }
      );
      onProjectUpdated(data.project);
    } catch (e: any) {
      setError(e.message);
    }
  };

  /* ---- Re-parse ONLY the vMemory sheet (fix Consumed → Active, no data loss) ---- */
  const reparseMemoryRef = useRef<HTMLInputElement>(null);
  const [reparseMsg, setReparseMsg] = useState("");
  const onReparseMemoryFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    e.target.value = "";
    setLoading(true);
    setReparseMsg("");
    setError("");
    try {
      const fd = new FormData();
      fd.append("file", f);
      const res = await apiFetch<{ message: string; updated_vms: number }>(
        `/api/migration/projects/${pid}/reparse-memory`,
        { method: "POST", body: fd },
      );
      setReparseMsg(`✓ ${res.message}`);
      loadVMs();
      loadStats();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  /* ---- Clear all uploaded RVTools data ---- */
  const clearRvtoolsData = async () => {
    if (!confirm("Delete ALL uploaded RVTools data (VMs, disks, NICs, tenants, etc.)? Project settings will be preserved. This cannot be undone.")) return;
    setLoading(true);
    setError("");
    try {
      await apiFetch<any>(`/api/migration/projects/${pid}/rvtools`, { method: "DELETE" });
      setVms([]);
      setVmTotal(0);
      setTenants([]);
      setStats(null);
      const proj = await apiFetch<{ project: MigrationProject }>(`/api/migration/projects/${pid}`);
      onProjectUpdated(proj.project);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  /* ================================================================ */
  /*  Render                                                          */
  /* ================================================================ */
  const totalPages = Math.ceil(vmTotal / vmLimit);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Source Analysis — {project.name}</h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={runAssessment} disabled={loading || !project.rvtools_filename} style={btnPrimary}>
            {loading ? "Running..." : "🔄 Run Assessment"}
          </button>
          {(project.status === "assessment" || project.status === "planned") && (
            <button onClick={approveProject} style={btnApprove}>
              ✅ Approve for Migration
            </button>
          )}
          <button onClick={resetAssessment} disabled={loading} style={btnDanger}>
            ♻️ Reset Assessment
          </button>
          {project.rvtools_filename && (
            <>
              {/* Hidden file input for vMemory-only re-parse */}
              <input ref={reparseMemoryRef} type="file" accept=".xlsx,.xls"
                style={{ display: "none" }} onChange={onReparseMemoryFile} />
              <button
                onClick={() => reparseMemoryRef.current?.click()}
                disabled={loading}
                title="Re-parse only the vMemory sheet to replace Consumed with Active memory — no other data is changed"
                style={{ ...btnSecondary, fontSize: "0.82rem" }}>
                🧠 Fix Mem %
              </button>
            </>
          )}
          {project.rvtools_filename && (
            <button onClick={clearRvtoolsData} disabled={loading}
              style={{ ...btnDanger, background: "#9333ea" }}>
              🗑️ Clear RVTools Data
            </button>
          )}
        </div>
      </div>

      {error && <div style={alertError}>{error}</div>}
      {reparseMsg && (
        <div style={{ ...alertError, background: "#d1fae5", border: "1px solid #34d399", color: "#065f46",
                      display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>{reparseMsg}</span>
          <button onClick={() => setReparseMsg("")} style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1rem" }}>✕</button>
        </div>
      )}

      {/* Sub-nav */}
      <div style={{ display: "flex", gap: 4, marginBottom: 16, borderBottom: "2px solid var(--border, #e5e7eb)" }}>
        {([
          { id: "dashboard" as SubView, label: "📊 Dashboard" },
          { id: "vms" as SubView, label: "🖥️ VMs" },
          { id: "tenants" as SubView, label: "🏢 Tenants" },
          { id: "cohorts" as SubView, label: "🗃️ Cohorts" },
          { id: "waves" as SubView, label: "🌊 Wave Planner" },
          { id: "networks" as SubView, label: "🌐 Networks" },
          { id: "netmap" as SubView, label: "🔌 Network Map" },
          { id: "users" as SubView, label: "👤 Users" },
          { id: "capacity" as SubView, label: "⚖️ Capacity" },
          { id: "readiness" as SubView, label: "🎯 PCD Readiness" },
          { id: "prepare" as SubView, label: "⚙️ Prepare PCD" },
          { id: "plan" as SubView, label: "📋 Migration Plan" },
          { id: "risk" as SubView, label: "⚠️ Risk Config" },
        ]).map(t => (
          <button key={t.id} onClick={() => setSubView(t.id)}
            style={{
              ...subTabStyle,
              ...(subView === t.id ? subTabActive : {}),
            }}>{t.label}</button>
        ))}
      </div>

      {/* ---- Dashboard ---- */}
      {subView === "dashboard" && stats && (
        <DashboardView stats={stats} hosts={hosts} clusters={clusters} tenants={tenants} />
      )}
      {subView === "dashboard" && !stats && (
        <p style={{ color: "#6b7280" }}>Upload RVTools data and run assessment to see the dashboard.</p>
      )}

      {/* ---- VM Table ---- */}
      {subView === "vms" && (
        <div>
          {/* Filters */}
          <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
            <input placeholder="Search VMs..." value={vmSearch}
              onChange={e => { setVmSearch(e.target.value); setVmPage(1); }}
              style={{ ...inputStyle, maxWidth: 220 }} />
            <select value={vmRisk} onChange={e => { setVmRisk(e.target.value); setVmPage(1); }} style={inputStyle}>
              <option value="">All Risk</option>
              <option value="GREEN">🟢 Green</option>
              <option value="YELLOW">🟡 Yellow</option>
              <option value="RED">🔴 Red</option>
            </select>
            <select value={vmMode} onChange={e => { setVmMode(e.target.value); setVmPage(1); }} style={inputStyle}>
              <option value="">All Modes</option>
              <option value="warm_eligible">Warm Eligible</option>
              <option value="warm_risky">Warm Risky</option>
              <option value="cold_required">Cold Required</option>
            </select>
            <select value={vmTenant} onChange={e => { setVmTenant(e.target.value); setVmPage(1); }} style={inputStyle}>
              <option value="">All Tenants</option>
              {tenants.map((t, i) => <option key={t.id ?? `${t.tenant_name}-${i}`} value={t.tenant_name}>{t.tenant_name}</option>)}
            </select>
            <select value={vmOsFamily} onChange={e => { setVmOsFamily(e.target.value); setVmPage(1); }} style={inputStyle}>
              <option value="">All OS Family</option>
              <option value="windows">🪟 Windows</option>
              <option value="linux">🐧 Linux</option>
              <option value="other">💻 Other</option>
            </select>
            <input placeholder="OS version..." value={vmOsVersion}
              onChange={e => { setVmOsVersion(e.target.value); setVmPage(1); }}
              style={{ ...inputStyle, maxWidth: 140 }} />
            <select value={vmPower} onChange={e => { setVmPower(e.target.value); setVmPage(1); }} style={inputStyle}>
              <option value="">All Power</option>
              <option value="poweredOn">● Powered On</option>
              <option value="poweredOff">○ Powered Off</option>
              <option value="suspended">⏸ Suspended</option>
            </select>
            <select value={vmCluster} onChange={e => { setVmCluster(e.target.value); setVmPage(1); }} style={inputStyle}>
              <option value="">All Clusters</option>
              {clusters.map(c => <option key={c.cluster_name} value={c.cluster_name}>{c.cluster_name}</option>)}
            </select>
            <span style={{ fontSize: "0.85rem", color: "#6b7280" }}>{vmTotal} VMs</span>
          </div>

          {/* Table */}
          <div style={{ overflowX: "auto" }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={{ ...thStyle, width: 30 }}></th>
                  {[
                    { key: "vm_name", label: "VM Name" },
                    { key: "cpu_count", label: "vCPU" },
                    { key: "cpu_usage_percent", label: "CPU %" },
                    { key: "ram_mb", label: "RAM (MB)" },
                    { key: "memory_usage_percent", label: "Mem %" },
                    { key: "total_disk_gb", label: "Alloc (GB)" },
                    { key: "in_use_gb", label: "Used (GB)" },
                    { key: "disk_count", label: "Disks" },
                    { key: "nic_count", label: "NICs" },
                    { key: "os_family", label: "OS Family" },
                    { key: "os_version", label: "OS Version" },
                    { key: "power_state", label: "Power" },
                    { key: "network_name", label: "Network" },
                    { key: "tenant_name", label: "Tenant" },
                    { key: "risk_category", label: "Risk" },
                    { key: "migration_mode", label: "Mode" },
                    { key: "migration_status", label: "Status" },
                    { key: "primary_ip", label: "IP" },
                  ].map(col => (
                    <th key={col.key}
                      style={{ ...thStyle, cursor: "pointer", userSelect: "none",
                        background: vmSort === col.key ? "#1e40af" : undefined }}
                      title={`Sort by ${col.label}`}
                      onClick={() => {
                        if (vmSort === col.key) setVmOrder(o => o === "asc" ? "desc" : "asc");
                        else { setVmSort(col.key); setVmOrder("asc"); }
                      }}>
                      {col.label} {vmSort === col.key ? (vmOrder === "asc" ? " ▲" : " ▼") : " ⇅"}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {vms.map(vm => (
                  <React.Fragment key={vm.vm_id}>
                    <tr style={{ borderBottom: "1px solid var(--border, #e5e7eb)", cursor: "pointer" }}
                        onClick={() => toggleVmExpand(vm)}>
                      <td style={tdStyle}>
                        <span style={{ fontSize: "0.8rem", color: "#9ca3af" }}>
                          {expandedVm === vm.vm_name ? "▼" : "▶"}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        <strong>{vm.vm_name}</strong>
                        <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>{vm.folder_path}</div>
                      </td>
                      <td style={tdStyle}>{vm.cpu_count || "—"}</td>
                      <td style={tdStyle}>
                        {vm.cpu_usage_percent != null && Number(vm.cpu_usage_percent) > 0 ? (
                          <span style={{ color: Number(vm.cpu_usage_percent) > 80 ? "#dc2626" : Number(vm.cpu_usage_percent) > 60 ? "#f59e0b" : "#10b981" }}>
                            {Number(vm.cpu_usage_percent).toFixed(1)}%
                          </span>
                        ) : <span style={{ color: "#d1d5db" }}>—</span>}
                      </td>
                      <td style={tdStyle}>{vm.ram_mb ? vm.ram_mb.toLocaleString() : "—"}</td>
                      <td style={tdStyle}>
                        {vm.memory_usage_percent != null && Number(vm.memory_usage_percent) > 0 ? (
                          (() => {
                            const pct = Number(vm.memory_usage_percent);
                            const color = pct > 100 ? "#7c3aed" : pct > 85 ? "#dc2626" : pct > 70 ? "#f59e0b" : "#10b981";
                            return (
                              <span style={{ color, fontWeight: pct > 100 ? 700 : undefined }} title={pct > 100 ? "Memory overcommit / ballooning active" : undefined}>
                                {pct.toFixed(1)}%{pct > 100 ? " ↑" : ""}
                              </span>
                            );
                          })()
                        ) : <span style={{ color: "#d1d5db" }}>—</span>}
                      </td>
                      <td style={tdStyle}>{vm.total_disk_gb != null ? Number(vm.total_disk_gb).toFixed(1) : "—"}</td>
                      <td style={tdStyle}>
                        {vm.in_use_gb != null ? (
                          <>
                            {Number(vm.in_use_gb).toFixed(1)}
                            {vm.total_disk_gb ? (
                              <span style={{ fontSize: "0.7rem", color: "#9ca3af", marginLeft: 4 }}>
                                ({Math.round((Number(vm.in_use_gb) / Number(vm.total_disk_gb)) * 100)}%)
                              </span>
                            ) : null}
                          </>
                        ) : "—"}
                      </td>
                      <td style={tdStyle}>{vm.disk_count || "—"}</td>
                      <td style={tdStyle}>{vm.nic_count || "—"}</td>
                      <td style={tdStyle}>
                        <span style={{ fontSize: "0.85rem" }}>{osIcon(vm.os_family)} {vm.os_family || "—"}</span>
                      </td>
                      <td style={tdStyle}>
                        <span style={{ fontSize: "0.85rem" }}>{vm.os_version || "—"}</span>
                      </td>
                      <td style={tdStyle}>
                        <span style={{
                          ...pillStyle,
                          background: vm.power_state === "poweredOn" ? "#dcfce7" : "#f3f4f6",
                          color: vm.power_state === "poweredOn" ? "#16a34a" : "#6b7280",
                        }}>
                          {vm.power_state === "poweredOn" ? "●" : "○"} {vm.power_state}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        <span style={{ fontSize: "0.85rem" }}>{vm.network_name || "—"}</span>
                      </td>
                      <td style={tdStyle}>
                        {vm.tenant_name || <span style={{ color: "#d1d5db" }}>—</span>}
                        {vm.org_vdc && <div style={{ fontSize: "0.7rem", color: "#9ca3af" }}>{vm.org_vdc}</div>}
                      </td>
                      <td style={tdStyle}>
                        {vm.risk_category ? (
                          <span style={{ ...pillStyle, ...riskPillColor(vm.risk_category) }}>
                            {vm.risk_category} ({vm.risk_score})
                          </span>
                        ) : "—"}
                      </td>
                      <td style={tdStyle}>
                        {vm.migration_mode ? (
                          <span style={{ ...pillStyle, ...modePillColor(vm.migration_mode) }}>
                            {vm.migration_mode_override ? "🔒 " : ""}{vm.migration_mode.replace(/_/g, " ")}
                          </span>
                        ) : "—"}
                      </td>
                      <td style={tdStyle}>
                        {(() => {
                          const st = vmStatusLocal[vm.id ?? -1] ?? vm.migration_status ?? "not_started";
                          const colors: Record<string, [string, string]> = {
                            not_started: ["#f3f4f6", "#6b7280"],
                            assigned:    ["#dbeafe", "#1d4ed8"],
                            in_progress: ["#fef9c3", "#854d0e"],
                            migrated:    ["#dcfce7", "#15803d"],
                            failed:      ["#fee2e2", "#dc2626"],
                            skipped:     ["#f3f4f6", "#9ca3af"],
                          };
                          const [bg, col] = colors[st] || colors.not_started;
                          return <span style={{ ...pillStyle, background: bg, color: col, fontSize: "0.7rem" }}>{st.replace(/_/g, " ")}</span>;
                        })()}
                      </td>
                      <td style={tdStyle}>
                        <span style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>{vm.primary_ip || "—"}</span>
                      </td>
                    </tr>
                    {/* ── Expanded detail row ── */}
                    {expandedVm === vm.vm_name && (
                      <tr>
                        <td colSpan={20} style={{ padding: "8px 16px 12px 40px", background: "var(--card-bg, #f9fafb)" }}>
                          {detailLoading ? (
                            <span style={{ color: "#6b7280" }}>Loading details...</span>
                          ) : (
                            <>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                              {/* Disks */}
                              <div>
                                <h4 style={{ margin: "0 0 6px", fontSize: "0.85rem" }}>
                                  💾 Disks ({vmDisks.length})
                                </h4>
                                {vmDisks.length === 0 ? (
                                  <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>No disk data</span>
                                ) : (
                                  <table style={{ ...tableStyle, fontSize: "0.8rem" }}>
                                    <thead>
                                      <tr>
                                        <th style={thStyleSm}>Label</th>
                                        <th style={thStyleSm}>Size (GB)</th>
                                        <th style={thStyleSm}>Thin</th>
                                        <th style={thStyleSm}>Datastore</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {vmDisks.map((dk, i) => (
                                        <tr key={i}>
                                          <td style={tdStyleSm}>{dk.disk_label || `Disk ${i + 1}`}</td>
                                          <td style={tdStyleSm}>{dk.capacity_gb != null ? Number(dk.capacity_gb).toFixed(1) : "—"}</td>
                                          <td style={tdStyleSm}>{dk.thin_provisioned ? "✓" : "—"}</td>
                                          <td style={tdStyleSm}>{dk.datastore || "—"}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                )}
                              </div>
                              {/* NICs */}
                              <div>
                                <h4 style={{ margin: "0 0 6px", fontSize: "0.85rem" }}>
                                  🌐 Network Adapters ({vmNics.length})
                                </h4>
                                {vmNics.length === 0 ? (
                                  <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>No NIC data</span>
                                ) : (
                                  <table style={{ ...tableStyle, fontSize: "0.8rem" }}>
                                    <thead>
                                      <tr>
                                        <th style={thStyleSm}>Adapter</th>
                                        <th style={thStyleSm}>Network</th>
                                        <th style={thStyleSm}>Type</th>
                                        <th style={thStyleSm}>IP</th>
                                        <th style={thStyleSm}>MAC</th>
                                        <th style={thStyleSm}>Up</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {vmNics.map((nic, i) => (
                                        <tr key={i}>
                                          <td style={tdStyleSm}>{nic.nic_label || `NIC ${i + 1}`}</td>
                                          <td style={tdStyleSm}><strong>{nic.network_name || "—"}</strong></td>
                                          <td style={tdStyleSm}>{nic.adapter_type || "—"}</td>
                                          <td style={{ ...tdStyleSm, fontFamily: "monospace" }}>{nic.ip_address || "—"}</td>
                                          <td style={{ ...tdStyleSm, fontFamily: "monospace", fontSize: "0.7rem" }}>{nic.mac_address || "—"}</td>
                                          <td style={tdStyleSm}>{nic.connected ? "✓" : "✗"}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                )}
                              </div>
                            </div>
                            {/* Risk Breakdown */}
                            {vm.risk_reasons && (vm.risk_reasons as string[]).length > 0 && (
                              <div style={{ marginTop: 12, padding: "8px 14px",
                                background: "#fffbeb", borderRadius: 6,
                                border: "1px solid #fde68a" }}>
                                <h4 style={{ margin: "0 0 6px", fontSize: "0.85rem", color: "#92400e" }}>⚠️ Risk Factors</h4>
                                <ul style={{ margin: 0, paddingLeft: 18 }}>
                                  {(vm.risk_reasons as string[]).map((r, i) => (
                                    <li key={i} style={{ fontSize: "0.8rem", color: "#92400e", lineHeight: 1.6 }}>{r}</li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {/* Phase 2.10: Mode Override + Status + Dependencies */}
                            <div style={{ marginTop: 12, display: "flex", gap: 16, flexWrap: "wrap" }}>
                              {/* Mode Override */}
                              {vm.id && (
                                <div style={{ padding: "8px 14px", background: "#eff6ff", borderRadius: 6, border: "1px solid #bfdbfe", minWidth: 220 }}>
                                  <h4 style={{ margin: "0 0 6px", fontSize: "0.85rem", color: "#1d4ed8" }}>🔒 Mode Override</h4>
                                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                                    <span style={{ fontSize: "0.8rem", color: "#6b7280" }}>Engine: <strong>{vm.migration_mode || "(none)"}</strong></span>
                                    <span style={{ fontSize: "0.75rem", color: "#9ca3af" }}>→ Override:</span>
                                    <select
                                      value={vmModeOverrideLocal[vm.id] !== undefined ? (vmModeOverrideLocal[vm.id] ?? "") : (vm.migration_mode_override ?? "")}
                                      disabled={modeOverrideUpdating}
                                      onChange={e => updateVmModeOverride(vm.id!, e.target.value || null)}
                                      style={{ fontSize: "0.8rem", padding: "2px 6px", borderRadius: 4, border: "1px solid #93c5fd" }}
                                    >
                                      <option value="">Auto (engine)</option>
                                      <option value="warm">🔥 Warm</option>
                                      <option value="cold">❄️ Cold</option>
                                    </select>
                                  </div>
                                </div>
                              )}
                              {/* Migration Status */}
                              {vm.id && (
                                <div style={{ padding: "8px 14px", background: "#f0fdf4", borderRadius: 6, border: "1px solid #bbf7d0", minWidth: 220 }}>
                                  <h4 style={{ margin: "0 0 6px", fontSize: "0.85rem", color: "#15803d" }}>🟢 Migration Status</h4>
                                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                                    <select
                                      value={vmStatusLocal[vm.id] ?? vm.migration_status ?? "not_started"}
                                      disabled={statusUpdating}
                                      onChange={e => updateVmStatus(vm.id!, e.target.value)}
                                      style={{ fontSize: "0.8rem", padding: "2px 6px", borderRadius: 4, border: "1px solid #86efac" }}
                                    >
                                      <option value="not_started">not started</option>
                                      <option value="assigned">assigned</option>
                                      <option value="in_progress">in progress</option>
                                      <option value="migrated">✅ migrated</option>
                                      <option value="failed">❌ failed</option>
                                      <option value="skipped">skipped</option>
                                    </select>
                                  </div>
                                </div>
                              )}
                            </div>
                            {/* VM Dependencies */}
                            {vm.id && (
                              <div style={{ marginTop: 12, padding: "8px 14px", background: "#fafafa", borderRadius: 6, border: "1px solid #e5e7eb" }}>
                                <h4 style={{ margin: "0 0 6px", fontSize: "0.85rem", color: "#374151" }}>🔗 Dependencies</h4>
                                {depsLoading ? <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>Loading...</span> : (
                                  vmDeps.length === 0
                                    ? <span style={{ color: "#9ca3af", fontSize: "0.8rem" }}>No dependencies. This VM migrates independently.</span>
                                    : <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                                        {vmDeps.map(d => (
                                          <span key={d.id} style={{ ...pillStyle, background: "#e5e7eb", color: "#374151", fontSize: "0.78rem" }}>
                                            must wait for → <strong>{d.depends_on_vm_name}</strong>
                                          </span>
                                        ))}
                                      </div>
                                )}
                              </div>
                            )}
                            </>
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
                {vms.length === 0 && (
                  <tr><td colSpan={20} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
                    No VMs found. Upload RVTools data first.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 12, alignItems: "center" }}>
              <button disabled={vmPage <= 1} onClick={() => setVmPage(p => p - 1)} style={btnSmall}>← Prev</button>
              <span style={{ fontSize: "0.85rem" }}>Page {vmPage} / {totalPages}</span>
              <button disabled={vmPage >= totalPages} onClick={() => setVmPage(p => p + 1)} style={btnSmall}>Next →</button>
            </div>
          )}
        </div>
      )}

      {/* ---- Tenants ---- */}
      {subView === "tenants" && (
        <TenantsView tenants={tenants} projectId={pid} onRefresh={() => { loadTenants(); loadStats(); }} />
      )}

      {/* ---- Cohorts ---- */}
      {subView === "cohorts" && (
        <CohortsView projectId={pid} project={project} tenants={tenants} onRefreshTenants={() => { loadTenants(); loadStats(); }} />
      )}

      {/* ---- Networks ---- */}
      {subView === "networks" && (
        <NetworksView networks={networks} projectId={pid} onRefresh={loadNetworks} />
      )}

      {/* ---- Network Map ---- */}
      {subView === "netmap" && (
        <NetworkMappingView projectId={pid} />
      )}

      {/* ---- Users (Phase 4A.4) ---- */}
      {subView === "users" && (
        <TenantUsersView projectId={pid} />
      )}

      {/* ---- Capacity Planning ---- */}
      {subView === "capacity" && (
        <CapacityPlanningView projectId={pid} />
      )}

      {/* ---- PCD Readiness ---- */}
      {subView === "readiness" && (
        <PcdReadinessView projectId={pid} />
      )}

      {/* ---- Risk Config ---- */}
      {subView === "risk" && (
        <RiskConfigView riskConfig={riskConfig} projectId={pid}
          onRefresh={() => { loadRiskConfig(); }} />
      )}

      {/* ---- Wave Planner ---- */}
      {subView === "waves" && (
        <WavePlannerView projectId={pid} project={project} tenants={tenants} />
      )}

      {/* ---- Migration Plan ---- */}
      {subView === "plan" && (
        <MigrationPlanView projectId={pid} projectName={project.name} />
      )}

      {/* ---- Prepare PCD (Phase 4B) ---- */}
      {subView === "prepare" && (
        <PreparePcdView projectId={pid} />
      )}
    </div>
  );
}

/* ================================================================== */
/*  Dashboard Sub-Component                                           */
/* ================================================================== */

function DashboardView({ stats, hosts, clusters, tenants }: {
  stats: any; hosts: any[]; clusters: any[]; tenants: Tenant[]
}) {
  return (
    <div>
      {/* Summary cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 12, marginBottom: 16 }}>
        <StatCard label="Total VMs" value={stats.total_vms} />
        <StatCard label="Total vCPUs" value={stats.total_vcpus} />
        <StatCard label="Total RAM (GB)" value={stats.total_ram_mb ? (stats.total_ram_mb / 1024).toFixed(0) : 0} />
        <StatCard label="Provisioned (TB)" value={stats.total_provisioned_gb ? (stats.total_provisioned_gb / 1024).toFixed(1) : "0.0"} />
        <StatCard label="In Use (TB)" value={stats.total_in_use_gb ? (stats.total_in_use_gb / 1024).toFixed(1) : "0.0"} />
        <StatCard label="Tenants" value={stats.tenant_count} />
      </div>

      {/* Risk distribution */}
      {stats.risk_distribution && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>Risk Distribution</h3>
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            {Object.entries(stats.risk_distribution).map(([level, count]) => (
              <div key={level} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{
                  width: 16, height: 16, borderRadius: 4,
                  background: level === "GREEN" ? "#22c55e" : level === "YELLOW" ? "#eab308" : "#ef4444",
                }} />
                <span style={{ fontWeight: 600 }}>{level}: {count as number}</span>
              </div>
            ))}
          </div>
          {/* Bar */}
          {stats.total_vms > 0 && (
            <div style={{ display: "flex", height: 24, borderRadius: 6, overflow: "hidden", marginTop: 8 }}>
              {(["GREEN", "YELLOW", "RED"] as const)
                .filter(level => ((stats.risk_distribution?.[level] || 0) as number) > 0)
                .map(level => {
                  const count = (stats.risk_distribution[level] || 0) as number;
                  const pct = (count / stats.total_vms) * 100;
                  return (
                    <div key={level} style={{
                      width: `${pct}%`,
                      background: level === "GREEN" ? "#22c55e" : level === "YELLOW" ? "#eab308" : "#ef4444",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: "0.75rem", color: "#fff", fontWeight: 600,
                    }}>
                      {count}
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      )}

      {/* Migration mode distribution */}
      {stats.mode_distribution && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>Migration Mode</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            {Object.entries(stats.mode_distribution).map(([mode, count]) => (
              <div key={mode} style={{
                padding: 12, borderRadius: 6, textAlign: "center",
                background: mode === "warm_eligible" ? "var(--pf9-safe-bg)" :
                             mode === "warm_risky" ? "var(--pf9-warning-bg)" : "var(--pf9-danger-bg)",
                border: `1px solid ${mode === "warm_eligible" ? "var(--pf9-safe-border)" :
                                    mode === "warm_risky" ? "var(--pf9-warning-border)" : "var(--pf9-danger-border)"}`,
              }}>
                <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--color-text-primary)" }}>{count as number}</div>
                <div style={{ fontSize: "0.85rem", color: mode === "warm_eligible" ? "var(--pf9-safe-text)" : mode === "warm_risky" ? "var(--pf9-warning-text)" : "var(--pf9-danger-text)" }}>{(mode as string).replace(/_/g, " ")}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* OS family distribution */}
      {stats.os_distribution && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>OS Distribution</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {Object.entries(stats.os_distribution).map(([os, count]) => (
              <span key={os} style={{
                padding: "4px 12px", borderRadius: 12, fontSize: "0.85rem",
                background: "var(--card-bg, #f3f4f6)", border: "1px solid var(--border, #e5e7eb)",
              }}>
                {osIcon(os)} {os}: {count as number}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tenants summary */}
      {tenants.length > 0 && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>Detected Tenants</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
            {tenants.map((t, idx) => (
              <div key={t.id ?? t.tenant_id ?? `${t.tenant_name}-${idx}`} style={{
                padding: 10, borderRadius: 6, border: "1px solid var(--pf9-border)",
                background: "var(--card-bg, #fff)",
              }}>
                <div style={{ fontWeight: 600 }}>{t.tenant_name}</div>
                <div style={{ fontSize: "0.8rem", color: "var(--pf9-text-secondary)" }}>
                  {t.vm_count} VMs · {t.total_vcpu || 0} vCPU · {t.total_ram_mb ? (t.total_ram_mb / 1024).toFixed(0) : 0} GB RAM
                  {t.total_disk_gb ? <> · {Number(t.total_disk_gb).toFixed(0)} GB alloc</> : null}
                  {t.total_in_use_gb ? <> · {Number(t.total_in_use_gb).toFixed(0)} GB used</> : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Hosts */}
      {hosts.length > 0 && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>ESXi Hosts ({hosts.length})</h3>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Host</th>
                <th style={thStyle}>Cluster</th>
                <th style={thStyle}>CPU Model</th>
                <th style={thStyle}>Cores</th>
                <th style={thStyle}>RAM (GB)</th>
                <th style={thStyle}>ESXi Version</th>
              </tr>
            </thead>
            <tbody>
              {hosts.map((h, i) => (
                <tr key={i} style={{ borderBottom: "1px solid var(--border, #e5e7eb)" }}>
                  <td style={tdStyle}>{h.host_name}</td>
                  <td style={tdStyle}>{h.cluster_name}</td>
                  <td style={tdStyle}>{h.cpu_model}</td>
                  <td style={tdStyle}>{h.cpu_cores}</td>
                  <td style={tdStyle}>{h.memory_gb}</td>
                  <td style={tdStyle}>{h.esxi_version}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Clusters */}
      {clusters.length > 0 && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>Clusters ({clusters.length})</h3>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Cluster</th>
                <th style={thStyle}>Datacenter</th>
                <th style={thStyle}>HA</th>
                <th style={thStyle}>DRS</th>
                <th style={thStyle}>Hosts</th>
              </tr>
            </thead>
            <tbody>
              {clusters.map((c, i) => (
                <tr key={i} style={{ borderBottom: "1px solid var(--border, #e5e7eb)" }}>
                  <td style={tdStyle}>{c.cluster_name}</td>
                  <td style={tdStyle}>{c.datacenter}</td>
                  <td style={tdStyle}>{c.ha_enabled ? "✅" : "—"}</td>
                  <td style={tdStyle}>{c.drs_enabled ? "✅" : "—"}</td>
                  <td style={tdStyle}>{c.host_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  Tenants View  (Phase 2A — Scoping · Phase 2B — Target Mapping)   */
/* ================================================================== */

function TenantsView({ tenants, projectId, onRefresh }: {
  tenants: Tenant[]; projectId: number; onRefresh: () => void
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newMethod, setNewMethod] = useState("vm_name_prefix");
  const [newPattern, setNewPattern] = useState("");
  const [error, setError] = useState("");

  /* ---- Inline editing state (basic + Phase 2A/2B + Phase 2.10D) ---- */
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editOrgVdc, setEditOrgVdc] = useState("");
  const [editInclude, setEditInclude] = useState(true);
  const [editExcludeReason, setEditExcludeReason] = useState("");
  const [editDomain, setEditDomain] = useState("");
  const [editProject, setEditProject] = useState("");
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editDomainDesc, setEditDomainDesc] = useState("");
  const [editPriority, setEditPriority] = useState<number>(999);
  const [editSaving, setEditSaving] = useState(false);

  /* Phase 3.0 — Ease scores ---- */
  const [easeScores, setEaseScores] = useState<Record<number, TenantEaseScore>>({});
  const [easePopover, setEasePopover] = useState<number | null>(null);

  useEffect(() => {
    apiFetch<{ tenant_ease_scores: TenantEaseScore[] }>(
      `/api/migration/projects/${projectId}/tenant-ease-scores`
    ).then(d => {
      const map: Record<number, TenantEaseScore> = {};
      for (const s of d.tenant_ease_scores) map[s.tenant_id] = s;
      setEaseScores(map);
    }).catch(() => {});
  }, [projectId, tenants.length]);

  /* Phase 2.10H — readiness cache ---- */
  const [readinessCache, setReadinessCache] = useState<Record<number, { overall: string; score: string }>>({});

  const loadReadiness = async (tenantId: number) => {
    try {
      const data = await apiFetch<{ overall: string; score: string }>(
        `/api/migration/projects/${projectId}/tenants/${tenantId}/readiness`
      );
      setReadinessCache(prev => ({ ...prev, [tenantId]: { overall: data.overall, score: data.score } }));
    } catch {}
  };

  /* ---- Search + Sort state ---- */
  const [tenantSearch, setTenantSearch] = useState("");
  const [tenantSort, setTenantSort] = useState("tenant_name");
  const [tenantSortDir, setTenantSortDir] = useState<"asc" | "desc">("asc");

  /* ---- Bulk-scope state ---- */
  const [selected, setSelected] = useState<Set<number>>(new Set());

  /* ---- Find & Replace state ---- */
  const [showFindReplace, setShowFindReplace] = useState(false);
  const [frField, setFrField] = useState<"target_domain_name" | "target_domain_description" | "target_project_name" | "target_display_name">("target_project_name");
  const [frFind, setFrFind] = useState("");
  const [frReplace, setFrReplace] = useState("");
  const [frCaseSensitive, setFrCaseSensitive] = useState(false);
  const [frUnconfirmedOnly, setFrUnconfirmedOnly] = useState(false);
  const [frPreview, setFrPreview] = useState<{ id: number; tenant_name: string; org_vdc: string | null; old_value: string; new_value: string }[] | null>(null);
  const [frLoading, setFrLoading] = useState(false);
  const [frApplied, setFrApplied] = useState(false);
  const [confirmingAll, setConfirmingAll] = useState(false);

  const runFindReplace = async (applyMode: boolean) => {
    if (!frFind.trim()) return;
    setFrLoading(true); setFrApplied(false);
    try {
      const data = await apiFetch<{ preview: typeof frPreview; affected_count: number }>(
        `/api/migration/projects/${projectId}/tenants/bulk-replace-target`,
        {
          method: "POST",
          body: JSON.stringify({
            field: frField,
            find: frFind,
            replace: frReplace,
            case_sensitive: frCaseSensitive,
            unconfirmed_only: frUnconfirmedOnly,
            preview_only: !applyMode,
          }),
        }
      );
      setFrPreview(data.preview);
      if (applyMode) {
        setFrApplied(true);
        onRefresh();
        setFrFind(""); setFrReplace(""); setFrPreview(null);
      }
    } catch (e: any) { setError(e.message); }
    finally { setFrLoading(false); }
  };

  const toggleOne = (id: number) => setSelected(prev => {
    const n = new Set(prev);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });

  const bulkScope = async (include: boolean) => {
    if (selected.size === 0) return;
    setError("");
    try {
      const ids = Array.from(selected).filter(id => id != null && Number.isFinite(id));
      if (ids.length === 0) { setSelected(new Set()); return; }
      await apiFetch(`/api/migration/projects/${projectId}/tenants/bulk-scope`, {
        method: "PATCH",
        body: JSON.stringify({ tenant_ids: ids, include_in_plan: include }),
      });
      setSelected(new Set());
      onRefresh();
    } catch (e: any) { setError(e.message); }
  };

  const startEdit = (t: Tenant) => {
    setEditId(t.id);
    setEditName(t.tenant_name);
    setEditOrgVdc(t.org_vdc || "");
    setEditInclude(t.include_in_plan !== false);
    setEditExcludeReason(t.exclude_reason || "");
    setEditDomain(t.target_domain_name || "");
    setEditProject(t.target_project_name || "");
    setEditDisplayName(t.target_display_name || "");
    setEditDomainDesc(t.target_domain_description || "");
    setEditPriority(t.migration_priority ?? 999);
  };

  const cancelEdit = () => { setEditId(null); };

  const saveEdit = async () => {
    if (!editId || !editName.trim()) return;
    setEditSaving(true);
    setError("");
    try {
      await apiFetch(`/api/migration/projects/${projectId}/tenants/${editId}`, {
        method: "PATCH",
        body: JSON.stringify({
          tenant_name: editName.trim(),
          org_vdc: editOrgVdc.trim() || null,
          include_in_plan: editInclude,
          exclude_reason: !editInclude && editExcludeReason.trim() ? editExcludeReason.trim() : null,
          target_domain_name: editDomain.trim() || null,
          target_project_name: editProject.trim() || null,
          target_display_name: editDisplayName.trim() || null,
          target_domain_description: editDomainDesc.trim() || null,
          target_confirmed: true,  // saving = user reviewed and confirmed
          migration_priority: editPriority,
        }),
      });
      cancelEdit();
      onRefresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setEditSaving(false);
    }
  };

  const addTenant = async () => {
    if (!newName.trim() || !newPattern.trim()) return;
    setError("");
    try {
      await apiFetch(`/api/migration/projects/${projectId}/tenants`, {
        method: "POST",
        body: JSON.stringify({
          tenant_name: newName.trim(),
          detection_method: newMethod,
          pattern_value: newPattern.trim(),
        }),
      });
      setNewName("");
      setNewPattern("");
      setShowAdd(false);
      onRefresh();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const rerun = async () => {
    try {
      await apiFetch(`/api/migration/projects/${projectId}/tenants/detect`, { method: "POST" });
      onRefresh();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const scopedCount = tenants.filter(t => t.include_in_plan !== false).length;

  /* ---- Filtered + sorted display list ---- */
  const displayTenants = (() => {
    let list = [...tenants];
    if (tenantSearch) {
      const q = tenantSearch.toLowerCase();
      list = list.filter(t =>
        (t.tenant_name || "").toLowerCase().includes(q) ||
        (t.org_vdc || "").toLowerCase().includes(q) ||
        (t.target_domain_name || "").toLowerCase().includes(q) ||
        (t.target_project_name || "").toLowerCase().includes(q)
      );
    }
            list.sort((a: any, b: any) => {
      let av: any, bv: any;
      switch (tenantSort) {
        case "vm_count":           av = a.vm_count || 0;               bv = b.vm_count || 0;               break;
        case "total_vcpu":         av = a.total_vcpu || 0;             bv = b.total_vcpu || 0;             break;
        case "total_ram_gb":       av = a.total_ram_mb || 0;           bv = b.total_ram_mb || 0;           break;
        case "total_disk_gb":      av = a.total_disk_gb || 0;          bv = b.total_disk_gb || 0;          break;
        case "migration_priority": av = a.migration_priority ?? 999;   bv = b.migration_priority ?? 999;  break;
        case "ease_score":          av = easeScores[a.id]?.ease_score ?? 999; bv = easeScores[b.id]?.ease_score ?? 999; break;
        default:                   av = (a.tenant_name || "").toLowerCase(); bv = (b.tenant_name || "").toLowerCase();
      }
      const cmp = typeof av === "string" ? av.localeCompare(bv) : (av - bv);
      return tenantSortDir === "asc" ? cmp : -cmp;
    });
    return list;
  })();
  const allSelected = displayTenants.length > 0 && displayTenants.every(t => selected.has(t.id));
  const toggleAll = () => setSelected(allSelected
    ? new Set([...selected].filter(id => !displayTenants.find(t => t.id === id)))
    : new Set([...selected, ...displayTenants.map(t => t.id)]));

  return (
    <div>
      {/* Toolbar */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
        <button onClick={() => setShowAdd(!showAdd)} style={btnSecondary}>+ Add Tenant Rule</button>
        <button onClick={rerun} style={btnSecondary}>🔄 Re-run Detection</button>
        <button onClick={() => { setShowFindReplace(!showFindReplace); setFrPreview(null); setFrApplied(false); }}
          style={{ ...btnSecondary, background: showFindReplace ? "#eff6ff" : undefined, color: showFindReplace ? "#2563eb" : undefined }}>
          🔍 Find &amp; Replace
        </button>
        <button
          disabled={confirmingAll}
          onClick={async () => {
            if (!window.confirm("Mark ALL unconfirmed tenant target names as confirmed?")) return;
            setConfirmingAll(true);
            try {
              const r = await apiFetch<{ affected_count: number }>(
                `/api/migration/projects/${projectId}/tenants/confirm-all`,
                { method: "POST" }
              );
              onRefresh();
              alert(`✓ ${r.affected_count} tenant${r.affected_count !== 1 ? "s" : ""} confirmed.`);
            } catch (e: any) { setError(e.message); }
            finally { setConfirmingAll(false); }
          }}
          style={{ ...btnSecondary, background: "#f0fdf4", color: "#15803d", border: "1px solid #86efac" }}>
          {confirmingAll ? "⏳..." : "✓ Confirm All"}
        </button>
        {selected.size > 0 && (
          <>
            <span style={{ fontSize: "0.85rem", color: "#6b7280", margin: "0 4px" }}>
              {selected.size} selected:
            </span>
            <button onClick={() => bulkScope(true)}
              style={{ ...btnSmall, background: "#16a34a", color: "#fff" }}>
              ✓ Include in Plan
            </button>
            <button onClick={() => bulkScope(false)}
              style={{ ...btnSmall, background: "#dc2626", color: "#fff" }}>
              ✗ Exclude from Plan
            </button>
          </>
        )}
        <input
          placeholder="Search tenants..."
          value={tenantSearch}
          onChange={e => setTenantSearch(e.target.value)}
          style={{ ...inputStyle, width: 200, padding: "4px 8px" }}
        />
        {tenantSearch && (
          <button onClick={() => setTenantSearch("")} style={btnSmall}>✕ Clear</button>
        )}
        <span style={{ marginLeft: "auto", fontSize: "0.85rem", color: "#6b7280" }}>
          {tenantSearch
            ? `${displayTenants.length} / ${tenants.length} tenants`
            : `${scopedCount} / ${tenants.length} tenants in scope`
          }
        </span>
      </div>
      {error && <div style={alertError}>{error}</div>}

      {/* Find & Replace panel */}
      {showFindReplace && (
        <div style={{ ...sectionStyle, marginBottom: 12, border: "1px solid #bfdbfe", background: "#eff6ff" }}>
          <div style={{ fontWeight: 700, marginBottom: 10, color: "#1d4ed8" }}>🔍 Find &amp; Replace in Target Names</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8, marginBottom: 10, alignItems: "end" }}>
            <div>
              <label style={labelStyle}>Field</label>
              <select value={frField} onChange={e => { setFrField(e.target.value as any); setFrPreview(null); }}
                style={inputStyle}>
                <option value="target_project_name">Target Project Name</option>
                <option value="target_display_name">Project Description</option>
                <option value="target_domain_name">Target Domain Name</option>
                <option value="target_domain_description">Domain Description</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>Find (substring)</label>
              <input value={frFind} onChange={e => { setFrFind(e.target.value); setFrPreview(null); }}
                style={inputStyle} placeholder={`e.g. _vDC_`} />
            </div>
            <div>
              <label style={labelStyle}>Replace with</label>
              <input value={frReplace} onChange={e => { setFrReplace(e.target.value); setFrPreview(null); }}
                style={inputStyle} placeholder="leave empty to strip" />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label style={{ ...labelStyle, marginBottom: 0 }}>
                <input type="checkbox" checked={frCaseSensitive}
                  onChange={e => { setFrCaseSensitive(e.target.checked); setFrPreview(null); }}
                  style={{ marginRight: 4 }} />
                Case sensitive
              </label>
              <label style={{ ...labelStyle, marginBottom: 0 }}>
                <input type="checkbox" checked={frUnconfirmedOnly}
                  onChange={e => { setFrUnconfirmedOnly(e.target.checked); setFrPreview(null); }}
                  style={{ marginRight: 4 }} />
                Unconfirmed rows only
              </label>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: frPreview ? 12 : 0 }}>
            <button onClick={() => runFindReplace(false)} disabled={frLoading || !frFind.trim()}
              style={{ ...btnSecondary, background: "#dbeafe", color: "#1d4ed8" }}>
              {frLoading && !frApplied ? "..." : "👁 Preview"}
            </button>
            {frPreview !== null && frPreview.length > 0 && (
              <button onClick={() => runFindReplace(true)} disabled={frLoading}
                style={{ ...btnPrimary }}>
                {frLoading ? "..." : `✅ Apply to ${frPreview.length} row${frPreview.length !== 1 ? "s" : ""}`}
              </button>
            )}
            {frPreview !== null && frPreview.length === 0 && (
              <span style={{ fontSize: "0.85rem", color: "#6b7280" }}>No matches found.</span>
            )}
            {frApplied && (
              <span style={{ fontSize: "0.85rem", color: "#16a34a", fontWeight: 600 }}>✓ Applied! Rows marked unconfirmed for review.</span>
            )}
          </div>
          {/* Preview table */}
          {frPreview !== null && frPreview.length > 0 && (
            <div style={{ maxHeight: 260, overflowY: "auto", border: "1px solid #bfdbfe", borderRadius: 6 }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
                <thead>
                  <tr style={{ background: "#dbeafe", position: "sticky", top: 0 }}>
                    <th style={{ ...thStyle, textAlign: "left" }}>Tenant</th>
                    <th style={{ ...thStyle, textAlign: "left" }}>OrgVDC</th>
                    <th style={{ ...thStyle, textAlign: "left", color: "#dc2626" }}>Before</th>
                    <th style={{ ...thStyle, textAlign: "left", color: "#16a34a" }}>After</th>
                  </tr>
                </thead>
                <tbody>
                  {frPreview.map(row => (
                    <tr key={row.id} style={{ borderTop: "1px solid #e0e7ff" }}>
                      <td style={tdStyle}>{row.tenant_name}</td>
                      <td style={{ ...tdStyle, color: "#6b7280", fontSize: "0.78rem" }}>{row.org_vdc || "—"}</td>
                      <td style={{ ...tdStyle, color: "#dc2626", fontFamily: "monospace" }}>{row.old_value}</td>
                      <td style={{ ...tdStyle, color: "#16a34a", fontFamily: "monospace" }}>
                        {row.new_value || <span style={{ color: "#9ca3af", fontStyle: "italic" }}>(empty)</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Add Tenant Rule form */}
      {showAdd && (
        <div style={{ ...sectionStyle, marginBottom: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 8, alignItems: "end" }}>
            <div>
              <label style={labelStyle}>Tenant Name</label>
              <input value={newName} onChange={e => setNewName(e.target.value)}
                style={inputStyle} placeholder="e.g. customer-acme" />
            </div>
            <div>
              <label style={labelStyle}>Detection Method</label>
              <select value={newMethod} onChange={e => setNewMethod(e.target.value)} style={inputStyle}>
                <option value="folder_path">Folder Path Contains</option>
                <option value="resource_pool">Resource Pool Contains</option>
                <option value="vapp_name">vApp Name Contains</option>
                <option value="vm_name_prefix">VM Name Prefix</option>
                <option value="annotation_field">Annotation Contains</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>Pattern / Value</label>
              <input value={newPattern} onChange={e => setNewPattern(e.target.value)}
                style={inputStyle} placeholder="e.g. acme" />
            </div>
            <button onClick={addTenant} style={btnPrimary}>Add</button>
          </div>
        </div>
      )}

      {/* Tenants table */}
      <div style={{ overflowX: "auto" }}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={{ ...thStyle, width: 32, textAlign: "center" }}>
                <input type="checkbox" checked={allSelected} onChange={toggleAll} title="Select all" />
              </th>
              <th style={{ ...thStyle, width: 24, textAlign: "center" }} title="In scope">📋</th>
              {([
                { key: "tenant_name",        label: "Tenant"    },
                { key: "org_vdc",            label: "OrgVDC",   noSort: true },
                { key: "vm_count",           label: "VMs"       },
                { key: "total_vcpu",         label: "vCPU"      },
                { key: "total_ram_gb",       label: "RAM GB"    },
                { key: "total_disk_gb",      label: "Disk GB"   },
                { key: "migration_priority", label: "Priority"  },
                { key: "ease_score",         label: "Ease ↓"     },
              ] as {key:string;label:string;noSort?:boolean}[]).map(col => (
                <th key={col.key}
                  style={{ ...thStyle,
                    cursor: col.noSort ? undefined : "pointer",
                    userSelect: "none",
                    background: !col.noSort && tenantSort === col.key ? "#1e40af" : undefined }}
                  onClick={() => {
                    if (col.noSort) return;
                    if (tenantSort === col.key) setTenantSortDir(d => d === "asc" ? "desc" : "asc");
                    else { setTenantSort(col.key); setTenantSortDir("asc"); }
                  }}>
                  {col.label}{!col.noSort && (tenantSort === col.key
                    ? (tenantSortDir === "asc" ? " ⇑" : " ⇓")
                    : " ⇍")}
                </th>
              ))}
              <th style={thStyle}>Target Domain</th>
              <th style={{ ...thStyle, color: "#6b7280", fontStyle: "italic", fontSize: "0.78rem" }} title="Optional description for the PCD Domain">Domain Desc.</th>
              <th style={thStyle}>Target Project</th>
              <th style={{ ...thStyle, color: "#6b7280", fontStyle: "italic", fontSize: "0.78rem" }} title="Optional description for the PCD Project (pre-filled from Project name)">Proj. Desc.</th>
              <th style={thStyle} title="Cohort assignment">Cohort</th>
              <th style={thStyle} title="Run readiness checks to see status">Readiness</th>
              <th style={thStyle}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {displayTenants.map((t, tIdx) => {
              const included = t.include_in_plan !== false;
              const rowStyle: React.CSSProperties = {
                borderBottom: "1px solid var(--border, #e5e7eb)",
                opacity: included ? 1 : 0.55,
                background: included ? undefined : "var(--card-bg, #f9fafb)",
              };
              const rowKey = t.id ?? tIdx;
              if (editId === t.id) {
                return (
                  <React.Fragment key={rowKey}>
                    <tr style={rowStyle}>
                      <td style={{ ...tdStyle, textAlign: "center" }}>
                        <input type="checkbox" checked={selected.has(t.id)}
                          onChange={() => toggleOne(t.id)} />
                      </td>
                      <td style={{ ...tdStyle, textAlign: "center" }}>
                        <input type="checkbox" checked={editInclude}
                          onChange={e => setEditInclude(e.target.checked)} title="Include in plan" />
                      </td>
                      <td style={tdStyle}>
                        <input value={editName} onChange={e => setEditName(e.target.value)}
                          style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem" }}
                          onKeyDown={e => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") cancelEdit(); }} />
                      </td>
                      <td style={tdStyle}>
                        <input value={editOrgVdc} onChange={e => setEditOrgVdc(e.target.value)}
                          style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem" }}
                          placeholder="(optional)"
                          onKeyDown={e => { if (e.key === "Escape") cancelEdit(); }} />
                      </td>
                      <td style={tdStyle}>{t.vm_count}</td>
                      <td style={tdStyle}>{t.total_vcpu || 0}</td>
                      <td style={tdStyle}>{t.total_ram_mb ? (t.total_ram_mb / 1024).toFixed(0) : "0"}</td>
                      <td style={tdStyle}>{t.total_disk_gb ? Number(t.total_disk_gb).toFixed(0) : "0"}</td>
                      <td style={tdStyle}>
                        <input type="number" value={editPriority}
                          onChange={e => setEditPriority(Number(e.target.value) || 999)}
                          style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem", width: 64 }}
                          min={1} max={9999}
                          onKeyDown={e => { if (e.key === "Escape") cancelEdit(); }} />
                      </td>
                      <td style={tdStyle}>
                        <input value={editDomain} onChange={e => setEditDomain(e.target.value)}
                          style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem" }}
                          placeholder="e.g. Default"
                          onKeyDown={e => { if (e.key === "Escape") cancelEdit(); }} />
                      </td>
                      <td style={tdStyle}>
                        <input value={editDomainDesc} onChange={e => setEditDomainDesc(e.target.value)}
                          style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem" }}
                          placeholder="Domain description (optional)"
                          onKeyDown={e => { if (e.key === "Escape") cancelEdit(); }} />
                      </td>
                      <td style={tdStyle}>
                        <input value={editProject} onChange={e => setEditProject(e.target.value)}
                          style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem" }}
                          placeholder="e.g. acme-prod"
                          onKeyDown={e => { if (e.key === "Escape") cancelEdit(); }} />
                      </td>
                      <td style={tdStyle}>
                        <input value={editDisplayName} onChange={e => setEditDisplayName(e.target.value)}
                          style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem" }}
                          placeholder="Project description (optional)"
                          onKeyDown={e => { if (e.key === "Escape") cancelEdit(); }} />
                      </td>
                      <td style={{ ...tdStyle, fontSize: "0.8rem", color: "#9ca3af" }}>
                        {t.cohort_id ? <span style={{ ...pillStyle, background: "#e0e7ff", color: "#4338ca", fontSize: "0.72rem" }}>C{t.cohort_id}</span> : "—"}
                      </td>
                      <td style={{ ...tdStyle, textAlign: "center" }}>—</td>
                      <td style={tdStyle}>
                        <div style={{ display: "flex", gap: 4 }}>
                          <button onClick={saveEdit} disabled={editSaving}
                            style={{ ...btnSmall, background: "#16a34a", color: "#fff" }} title="Save">
                            {editSaving ? "..." : "✓"}
                          </button>
                          <button onClick={cancelEdit} style={{ ...btnSmall, background: "#e5e7eb" }} title="Cancel">✕</button>
                        </div>
                      </td>
                    </tr>
                    {!editInclude && (
                      <tr key={`${rowKey}-reason`} style={{ background: "#fff7ed" }}>
                        <td colSpan={2} />
                        <td colSpan={14} style={{ ...tdStyle, paddingTop: 4, paddingBottom: 8 }}>
                          <label style={{ ...labelStyle, display: "inline", marginRight: 8 }}>Exclude reason:</label>
                          <input value={editExcludeReason}
                            onChange={e => setEditExcludeReason(e.target.value)}
                            style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem", width: 320 }}
                            placeholder="e.g. dev/test environment, not migrating" />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              }
              return (
                <tr key={rowKey} style={rowStyle}>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    <input type="checkbox" checked={selected.has(t.id)}
                      onChange={() => toggleOne(t.id)} />
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center" }} title={included ? "In plan" : t.exclude_reason || "Excluded"}>
                    {included ? "✅" : "🚫"}
                  </td>
                  <td style={tdStyle}>
                    <strong>{t.tenant_name}</strong>
                    {!included && t.exclude_reason && (
                      <div style={{ fontSize: "0.75rem", color: "#9ca3af", fontStyle: "italic" }}>{t.exclude_reason}</div>
                    )}
                  </td>
                  <td style={{ ...tdStyle, fontSize: "0.8rem", color: "#6b7280" }}>{t.org_vdc || "—"}</td>
                  <td style={tdStyle}>{t.vm_count}</td>
                  <td style={tdStyle}>{t.total_vcpu || 0}</td>
                  <td style={tdStyle}>{t.total_ram_mb ? (t.total_ram_mb / 1024).toFixed(0) : "0"}</td>
                  <td style={tdStyle}>{t.total_disk_gb ? Number(t.total_disk_gb).toFixed(0) : "0"}</td>
                  <td style={{ ...tdStyle, textAlign: "center", color: (t.migration_priority ?? 999) < 999 ? "#1d4ed8" : "#9ca3af" }}>
                    {(t.migration_priority ?? 999) < 999 ? t.migration_priority : "—"}
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center", position: "relative" }}>
                    {(() => {
                      const es = easeScores[t.id];
                      if (!es) return <span style={{ color: "#d1d5db" }}>—</span>;
                      const bg = es.ease_score < 30 ? "#dcfce7" : es.ease_score < 60 ? "#fef9c3" : "#fee2e2";
                      const col = es.ease_score < 30 ? "#15803d" : es.ease_score < 60 ? "#854d0e" : "#dc2626";
                      return (
                        <span
                          title="Click for breakdown"
                          onClick={() => setEasePopover(easePopover === t.id ? null : t.id)}
                          style={{ ...pillStyle, background: bg, color: col, cursor: "pointer", fontSize: "0.72rem", fontWeight: 700 }}>
                          {es.ease_score.toFixed(0)}
                        </span>
                      );
                    })()}
                    {easePopover === t.id && (() => {
                      const es = easeScores[t.id]!;
                      const dimLabels: Record<string, string> = {
                        disk: "Disk (used GB)", risk: "Avg Risk", os: "OS (unsupported)",
                        vm_count: "VM Count", networks: "Networks", deps: "Cross-tenant deps",
                        cold: "Cold VM ratio", unconf: "Unconfirmed mappings",
                      };
                      return (
                        <div onClick={e => e.stopPropagation()} style={{
                          position: "absolute", zIndex: 100, top: "110%", left: "50%", transform: "translateX(-50%)",
                          background: "var(--card-bg, #fff)", border: "1px solid #e5e7eb", borderRadius: 8,
                          boxShadow: "0 4px 16px rgba(0,0,0,0.15)", padding: "12px 16px", minWidth: 260, textAlign: "left"
                        }}>
                          <div style={{ fontWeight: 700, marginBottom: 6, fontSize: "0.9rem" }}>
                            Ease Score: {es.ease_score.toFixed(1)} — {es.ease_label}
                          </div>
                          <table style={{ width: "100%", fontSize: "0.78rem", borderCollapse: "collapse" }}>
                            <tbody>
                              {Object.entries(es.dimension_scores).map(([dim, val]) => (
                                <tr key={dim}>
                                  <td style={{ padding: "2px 4px", color: "#6b7280" }}>{dimLabels[dim] || dim}</td>
                                  <td style={{ padding: "2px 4px", textAlign: "right", fontWeight: 600,
                                    color: val > es.dimension_weights[dim] * 0.7 ? "#dc2626" : "#15803d" }}>
                                    {val.toFixed(1)} / {es.dimension_weights[dim].toFixed(0)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <div style={{ marginTop: 8, fontSize: "0.72rem", color: "#9ca3af", borderTop: "1px solid #e5e7eb", paddingTop: 4 }}>
                            {es.vm_count} VMs · {es.total_used_gb.toFixed(1)} GB used · Risk {es.avg_risk_score.toFixed(0)}
                          </div>
                          <button onClick={() => setEasePopover(null)} style={{ ...btnSmall, marginTop: 6, width: "100%" }}>Close</button>
                        </div>
                      );
                    })()}
                  </td>
                  <td style={{ ...tdStyle, fontSize: "0.8rem" }}>
                    {t.target_domain_name
                      ? <span>
                          {t.target_domain_name}
                          {!t.target_confirmed && (
                            <span title="Auto-seeded from source name — edit to confirm"
                              style={{ marginLeft: 4, fontSize: "0.7rem", color: "#ea580c", cursor: "help" }}>⚠️</span>
                          )}
                        </span>
                      : <span style={{ color: "#9ca3af" }}>—</span>}
                  </td>
                  <td style={{ ...tdStyle, fontSize: "0.78rem", color: "#6b7280", fontStyle: t.target_domain_description ? undefined : "italic" }}>{t.target_domain_description || <span style={{ color: "#d1d5db" }}>—</span>}</td>
                  <td style={{ ...tdStyle, fontSize: "0.8rem" }}>
                    {t.target_project_name
                      ? <span>
                          {t.target_project_name}
                          {!t.target_confirmed && (
                            <span title="Auto-seeded from source name — edit to confirm"
                              style={{ marginLeft: 4, fontSize: "0.7rem", color: "#ea580c", cursor: "help" }}>⚠️</span>
                          )}
                        </span>
                      : <span style={{ color: "#9ca3af" }}>—</span>}
                  </td>
                  <td style={{ ...tdStyle, fontSize: "0.78rem", color: "#6b7280", fontStyle: t.target_display_name ? undefined : "italic" }}>{t.target_display_name || <span style={{ color: "#d1d5db" }}>—</span>}</td>
                  <td style={{ ...tdStyle, textAlign: "center", fontSize: "0.78rem" }}>
                    {t.cohort_id
                      ? <span style={{ ...pillStyle, background: "#e0e7ff", color: "#4338ca", fontSize: "0.72rem" }}>C{t.cohort_id}</span>
                      : <span style={{ color: "#d1d5db" }}>unassigned</span>}
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    {readinessCache[t.id] ? (
                      <span style={{ cursor: "default" }} title={`${readinessCache[t.id].score} checks passed`}>
                        {readinessCache[t.id].overall === "pass" ? "🟢" : readinessCache[t.id].overall === "fail" ? "🔴" : "🟡"}
                        <span style={{ fontSize: "0.7rem", color: "#6b7280", marginLeft: 4 }}>{readinessCache[t.id].score}</span>
                      </span>
                    ) : (
                      <button onClick={() => loadReadiness(t.id)}
                        style={{ ...btnSmall, fontSize: "0.7rem", padding: "1px 5px" }}
                        title="Check readiness">check</button>
                    )}
                  </td>
                  <td style={tdStyle}>
                    <button onClick={() => startEdit(t)} style={btnSmall} title="Edit">✏️</button>
                  </td>
                </tr>
              );
            })}
            {displayTenants.length === 0 && (
              <tr><td colSpan={16} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
                {tenants.length === 0
                  ? "No tenants detected. Add rules above or run assessment."
                  : `No tenants match "${tenantSearch}".`}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  Networks View                                                     */
/* ================================================================== */

function NetworksView({ networks, projectId, onRefresh }: {
  networks: NetworkSummary[]; projectId: number; onRefresh: () => void
}) {
  const [netSearch, setNetSearch] = useState("");

  const typeColor = (t: string): React.CSSProperties => {
    if (t === "vlan_based") return { background: "#dbeafe", color: "#1d4ed8" };
    if (t === "nsx_t") return { background: "#ede9fe", color: "#7c3aed" };
    if (t === "isolated") return { background: "#fef3c7", color: "#92400e" };
    return { background: "#f3f4f6", color: "#6b7280" };
  };

  const filteredNetworks = netSearch
    ? networks.filter(n =>
        (n.network_name || "").toLowerCase().includes(netSearch.toLowerCase()) ||
        (n.tenant_names || "").toLowerCase().includes(netSearch.toLowerCase()) ||
        (n.network_type || "").toLowerCase().includes(netSearch.toLowerCase())
      )
    : networks;

  return (
    <div>
      <p style={{ color: "#6b7280", fontSize: "0.85rem", marginBottom: 8 }}>
        Network inventory discovered from RVTools — read-only reference view. VLAN IDs and types are auto-detected from naming patterns.
        To map source networks to PCD targets and fill in subnet / gateway / DNS details, use the <strong>Network Map</strong> tab.
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <input
          placeholder="Search networks, tenants, type…"
          value={netSearch}
          onChange={e => setNetSearch(e.target.value)}
          style={{ ...inputStyle, maxWidth: 320 }}
        />
        {netSearch && (
          <button onClick={() => setNetSearch("")} style={btnSmall}>✕ Clear</button>
        )}
        <span style={{ fontSize: "0.8rem", color: "#6b7280" }}>{filteredNetworks.length} / {networks.length} networks</span>
      </div>

      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Network Name</th>
            <th style={{ ...thStyle, width: 80 }}>VLAN ID</th>
            <th style={{ ...thStyle, width: 110 }}>Type</th>
            <th style={{ ...thStyle, width: 60, textAlign: "center" }}>VMs</th>
            <th style={thStyle}>Tenants</th>
          </tr>
        </thead>
        <tbody>
          {filteredNetworks.map(n => (
            <tr key={n.id} style={{ borderBottom: "1px solid var(--border, #e5e7eb)" }}>
              <td style={tdStyle}><strong>{n.network_name}</strong></td>
              <td style={{ ...tdStyle, fontFamily: "monospace" }}>{n.vlan_id ?? "—"}</td>
              <td style={tdStyle}>
                <span style={{ ...pillStyle, ...typeColor(n.network_type) }}>{n.network_type.replace(/_/g, " ")}</span>
              </td>
              <td style={{ ...tdStyle, textAlign: "center" }}>{n.vm_count}</td>
              <td style={{ ...tdStyle, fontSize: "0.8rem", color: "#6b7280" }}>
                {n.tenant_names || "—"}
              </td>
            </tr>
          ))}
          {networks.length === 0 && (
            <tr><td colSpan={5} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
              No networks found. Upload RVTools data first.
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/* ================================================================== */
/*  Network Mapping View  (Phase 2.10F)                              */
/* ================================================================== */

function NetworkMappingView({ projectId }: { projectId: number }) {
  const [mappings, setMappings] = useState<any[]>([]);
  const [unconfirmedCount, setUnconfirmedCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<number | null>(null);
  const [editValues, setEditValues] = useState<Record<number, string>>({});
  const [editVlanValues, setEditVlanValues] = useState<Record<number, string>>({});
  const [error, setError] = useState("");

  /* ---- Find & Replace state ---- */
  const [showFR, setShowFR] = useState(false);
  const [frFind, setFrFind] = useState("");
  const [frReplace, setFrReplace] = useState("");
  const [frCaseSensitive, setFrCaseSensitive] = useState(false);
  const [frUnconfirmedOnly, setFrUnconfirmedOnly] = useState(false);
  const [frPreview, setFrPreview] = useState<{ id: number; source_network_name: string; old_value: string; new_value: string }[] | null>(null);
  const [frLoading, setFrLoading] = useState(false);
  const [frApplied, setFrApplied] = useState(false);
  const [confirmingAll, setConfirmingAll] = useState(false);
  const [confirmingSubnets, setConfirmingSubnets] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ updated: number; skipped: number; diagnostics?: any } | null>(null);
  const importFileRef = React.useRef<HTMLInputElement>(null);
  const [expandedSubnet, setExpandedSubnet] = useState<number | null>(null);
  const [subnetEdits, setSubnetEdits] = useState<Record<number, any>>({});
  const [savingSubnet, setSavingSubnet] = useState<number | null>(null);
  const [savingKind, setSavingKind] = useState<number | null>(null);
  const [subnetReady, setSubnetReady] = useState<{ missing: number; confirmed: number } | null>(null);

  const loadSubnetReadiness = useCallback(async () => {
    try {
      const r = await apiFetch<{ missing_subnet_details: number; confirmed_count: number }>(
        `/api/migration/projects/${projectId}/network-mappings/readiness`
      );
      setSubnetReady({ missing: r.missing_subnet_details, confirmed: r.confirmed_count });
    } catch { /* non-critical */ }
  }, [projectId]);

  const downloadNetworkTemplate = async () => {
    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/api/migration/projects/${projectId}/network-mappings/export-template`, {
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (!res.ok) { setError(`Download failed: ${res.statusText}`); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `network_map_template_${projectId}.xlsx`;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: any) { setError(e.message); }
  };

  const importNetworkTemplate = async (f: File) => {
    setImporting(true); setImportResult(null); setError("");
    try {
      const token = getToken();
      const fd = new FormData(); fd.append("file", f);
      const res = await fetch(`${API_BASE}/api/migration/projects/${projectId}/network-mappings/import-template`, {
        method: "POST",
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || "Import failed"); return; }
      setImportResult({ updated: data.updated, skipped: data.skipped, diagnostics: data.diagnostics });
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setImporting(false); if (importFileRef.current) importFileRef.current.value = ""; }
  };

  const saveSubnetDetails = async (id: number) => {
    setSavingSubnet(id);
    try {
      const rawEdits = { ...subnetEdits[id] || {} };
      // Convert dns_nameservers from comma-string to array before sending to API
      if (typeof rawEdits.dns_nameservers === "string") {
        rawEdits.dns_nameservers = rawEdits.dns_nameservers
          .split(",").map((s: string) => s.trim()).filter(Boolean);
      }
      // When DHCP is disabled, clear the allocation pool — no pool needed for static-only subnets
      if (rawEdits.dhcp_enabled === false) {
        rawEdits.allocation_pool_start = null;
        rawEdits.allocation_pool_end = null;
      }
      await apiFetch(`/api/migration/projects/${projectId}/network-mappings/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ ...rawEdits, subnet_details_confirmed: true }),
      });
      setExpandedSubnet(null);
      setSubnetEdits(prev => { const n = { ...prev }; delete n[id]; return n; });
      load();
      loadSubnetReadiness();
    } catch (e: any) { setError(e.message); }
    finally { setSavingSubnet(null); }
  };

  const updateSubnetEdit = (id: number, field: string, value: any) => {
    setSubnetEdits(prev => ({ ...prev, [id]: { ...(prev[id] || {}), [field]: value } }));
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ mappings: any[]; unconfirmed_count: number }>(
        `/api/migration/projects/${projectId}/network-mappings`
      );
      setMappings(data.mappings);
      setUnconfirmedCount(data.unconfirmed_count);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); loadSubnetReadiness(); }, [load, loadSubnetReadiness]);

  const runNetworkFR = async (applyMode: boolean) => {
    if (!frFind.trim()) return;
    setFrLoading(true); setFrApplied(false);
    try {
      const data = await apiFetch<{ preview: typeof frPreview; affected_count: number }>(
        `/api/migration/projects/${projectId}/network-mappings/bulk-replace`,
        {
          method: "POST",
          body: JSON.stringify({
            find: frFind,
            replace: frReplace,
            case_sensitive: frCaseSensitive,
            unconfirmed_only: frUnconfirmedOnly,
            preview_only: !applyMode,
          }),
        }
      );
      setFrPreview(data.preview);
      if (applyMode) {
        setFrApplied(true);
        load();
        setFrFind(""); setFrReplace(""); setFrPreview(null);
      }
    } catch (e: any) { setError(e.message); }
    finally { setFrLoading(false); }
  };

  const saveMapping = async (id: number) => {
    setSaving(id);
    try {
      const mapping = mappings.find(m => m.id === id);
      // Fall back to the current server value so clicking Confirm on an unedited row
      // doesn't accidentally null-out the target network name.
      const currentName = mapping?.target_network_name ?? null;
      const value = editValues[id] !== undefined ? editValues[id] : currentName;
      const body: Record<string, any> = { target_network_name: value, confirmed: true };
      // Only send vlan_id if the user actually edited it
      if (editVlanValues[id] !== undefined) {
        const parsed = parseInt(editVlanValues[id], 10);
        body.vlan_id = isNaN(parsed) ? null : parsed;
      }
      await apiFetch(`/api/migration/projects/${projectId}/network-mappings/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setEditValues(prev => { const n = { ...prev }; delete n[id]; return n; });
      setEditVlanValues(prev => { const n = { ...prev }; delete n[id]; return n; });
      load();
    } catch (e: any) { setError(e.message); }
    finally { setSaving(null); }
  };

  const startEditMapping = (id: number, currentValue: string, currentVlan: number | null) => {
    setEditValues(prev => ({ ...prev, [id]: currentValue }));
    setEditVlanValues(prev => ({ ...prev, [id]: currentVlan != null ? String(currentVlan) : "" }));
  };

  const cancelEditMapping = (id: number) => {
    setEditValues(prev => { const n = { ...prev }; delete n[id]; return n; });
    setEditVlanValues(prev => { const n = { ...prev }; delete n[id]; return n; });
  };

  if (loading) return <div style={{ color: "#6b7280", padding: 16 }}>Loading network mappings...</div>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div>
          <h3 style={{ margin: 0 }}>🔌 Source → PCD Network Mapping</h3>
          <p style={{ margin: "4px 0 0", color: "#6b7280", fontSize: "0.85rem" }}>
            Map each source VMware network to its corresponding PCD network. All powered-on VM networks are auto-populated.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => { setShowFR(!showFR); setFrPreview(null); setFrApplied(false); }}
            style={{ ...btnSecondary, background: showFR ? "#eff6ff" : undefined }}>
            🔍 Find &amp; Replace
          </button>
          <button onClick={downloadNetworkTemplate} style={{ ...btnSecondary, background: "#f0fdf4", color: "#15803d", border: "1px solid #86efac" }}>
            📥 Download Template
          </button>
          <button
            onClick={() => importFileRef.current?.click()}
            disabled={importing}
            style={{ ...btnSecondary, background: "#eff6ff", color: "#1d4ed8", border: "1px solid #bfdbfe" }}>
            {importing ? "⏳ Importing..." : "📤 Import Template"}
          </button>
          <input
            ref={importFileRef}
            type="file"
            accept=".xlsx"
            style={{ display: "none" }}
            onChange={e => { const f = e.target.files?.[0]; if (f) importNetworkTemplate(f); }}
          />
          <button
            disabled={confirmingAll}
            onClick={async () => {
              if (!window.confirm("Mark ALL unconfirmed network mappings as confirmed?")) return;
              setConfirmingAll(true);
              try {
                const r = await apiFetch<{ affected_count: number }>(
                  `/api/migration/projects/${projectId}/network-mappings/confirm-all`,
                  { method: "POST" }
                );
                load();
                alert(`✓ ${r.affected_count} network${r.affected_count !== 1 ? "s" : ""} confirmed.`);
              } catch (e: any) { setError(e.message); }
              finally { setConfirmingAll(false); }
            }}
            style={{ ...btnSecondary, background: "#f0fdf4", color: "#15803d", border: "1px solid #86efac" }}>
            {confirmingAll ? "⏳..." : "✓ Confirm All"}
          </button>
          <button onClick={load} style={btnSecondary}>🔄 Refresh</button>
          <button
            disabled={confirmingSubnets}
            onClick={async () => {
              setConfirmingSubnets(true);
              try {
                const r = await apiFetch<{ affected_count: number }>(
                  `/api/migration/projects/${projectId}/network-mappings/confirm-subnets`,
                  { method: "POST" }
                );
                await load();
                await loadSubnetReadiness();
                if (r.affected_count === 0) alert("No rows with CIDR set were pending — nothing to confirm.");
              } catch (e: any) { setError(e.message); }
              finally { setConfirmingSubnets(false); }
            }}
            style={{ ...btnSecondary, background: "#f0fdf4", color: "#15803d", border: "1px solid #86efac" }}>
            {confirmingSubnets ? "⏳..." : "✓ Confirm Subnets"}
          </button>
          {subnetReady !== null && (
            <span style={{
              padding: "4px 10px", borderRadius: 6, fontSize: "0.78rem", fontWeight: 600,
              background: subnetReady.missing === 0 ? "#dcfce7" : "#fff7ed",
              color: subnetReady.missing === 0 ? "#15803d" : "#9a3412",
              border: `1px solid ${subnetReady.missing === 0 ? "#86efac" : "#fdba74"}`,
            }}>
              🌐 Subnet Details: {subnetReady.confirmed}/{subnetReady.confirmed + subnetReady.missing}
            </span>
          )}
        </div>
      </div>
      {showFR && (
        <div style={{ marginBottom: 16, padding: 16, background: "#eff6ff",
          border: "1px solid #bfdbfe", borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 10, color: "#1e40af" }}>🔍 Find &amp; Replace — Target Network Name</div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 10 }}>
            <div>
              <label style={{ fontSize: "0.78rem", color: "#374151", display: "block", marginBottom: 3 }}>Find</label>
              <input value={frFind} onChange={e => { setFrFind(e.target.value); setFrPreview(null); }}
                placeholder="e.g. _vlan_"
                style={{ ...inputStyle, width: 180, padding: "5px 8px", fontSize: "0.85rem" }} />
            </div>
            <div>
              <label style={{ fontSize: "0.78rem", color: "#374151", display: "block", marginBottom: 3 }}>Replace with</label>
              <input value={frReplace} onChange={e => { setFrReplace(e.target.value); setFrPreview(null); }}
                placeholder="leave empty to strip"
                style={{ ...inputStyle, width: 200, padding: "5px 8px", fontSize: "0.85rem" }} />
            </div>
            <div style={{ display: "flex", gap: 16, alignSelf: "center", paddingTop: 4 }}>
              <label style={{ fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
                <input type="checkbox" checked={frCaseSensitive}
                  onChange={e => { setFrCaseSensitive(e.target.checked); setFrPreview(null); }} />
                Case sensitive
              </label>
              <label style={{ fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
                <input type="checkbox" checked={frUnconfirmedOnly}
                  onChange={e => { setFrUnconfirmedOnly(e.target.checked); setFrPreview(null); }} />
                Unconfirmed only
              </label>
            </div>
            <button onClick={() => runNetworkFR(false)} disabled={frLoading || !frFind.trim()}
              style={{ ...btnSecondary, alignSelf: "flex-end" }}>
              {frLoading && !frApplied ? "⏳ Searching..." : "👁 Preview"}
            </button>
          </div>
          {frApplied && (
            <div style={{ color: "#15803d", fontWeight: 500, marginBottom: 8 }}>✓ Applied! Rows marked unconfirmed for review.</div>
          )}
          {frPreview !== null && (
            <>
              {frPreview.length === 0
                ? <div style={{ color: "#6b7280", fontSize: "0.85rem" }}>No matches found.</div>
                : (
                  <>
                    <div style={{ fontSize: "0.82rem", color: "#374151", marginBottom: 6 }}>
                      {frPreview.length} network{frPreview.length !== 1 ? "s" : ""} will be affected.
                    </div>
                    <div style={{ overflowX: "auto", maxHeight: 240, overflowY: "auto" }}>
                      <table style={{ ...tableStyle, fontSize: "0.8rem" }}>
                        <thead>
                          <tr>
                            <th style={thStyle}>Source Network</th>
                            <th style={thStyle}>Before</th>
                            <th style={thStyle}>After</th>
                          </tr>
                        </thead>
                        <tbody>
                          {frPreview.map(row => (
                            <tr key={row.id} style={{ borderBottom: "1px solid #e5e7eb" }}>
                              <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.78rem" }}>{row.source_network_name}</td>
                              <td style={{ ...tdStyle, fontFamily: "monospace", color: "#dc2626", fontSize: "0.78rem" }}>{row.old_value}</td>
                              <td style={{ ...tdStyle, fontFamily: "monospace", color: "#16a34a", fontSize: "0.78rem" }}>{row.new_value}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <button onClick={() => runNetworkFR(true)} disabled={frLoading}
                      style={{ ...btnPrimary, marginTop: 10 }}>
                      {frLoading ? "⏳ Applying..." : `✅ Apply to ${frPreview.length} network${frPreview.length !== 1 ? "s" : ""}`}
                    </button>
                  </>
                )}
            </>
          )}
        </div>
      )}
      {importResult && (
        <div style={{ marginBottom: 12, padding: "8px 14px",
          background: importResult.updated > 0 ? "#f0fdf4" : "#fffbeb",
          borderRadius: 6,
          border: importResult.updated > 0 ? "1px solid #86efac" : "1px solid #fcd34d",
          color: importResult.updated > 0 ? "#15803d" : "#92400e",
          fontSize: "0.85rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <span>{importResult.updated > 0 ? "✅" : "⚠️"} Template imported — <strong>{importResult.updated}</strong> network{importResult.updated !== 1 ? "s" : ""} updated, {importResult.skipped} skipped.</span>
            <button onClick={() => setImportResult(null)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1rem", marginLeft: 12 }}>×</button>
          </div>
          {importResult.updated === 0 && importResult.diagnostics && (
            <div style={{ marginTop: 6, fontSize: "0.8rem", lineHeight: 1.6 }}>
              {importResult.diagnostics.skipped_empty_patch > 0 && (
                <div>• <strong>{importResult.diagnostics.skipped_empty_patch}</strong> rows had no editable values — cells may be empty or contain formulas referencing external files. In Excel: select all blue columns → Copy → Paste Special → Values Only → Save → re-upload.</div>
              )}
              {importResult.diagnostics.skipped_no_db_match > 0 && (
                <div>• <strong>{importResult.diagnostics.skipped_no_db_match}</strong> rows had no matching network in this project's map.</div>
              )}
              {importResult.diagnostics.sample_sources_in_file?.length > 0 && (
                <div style={{ marginTop: 4 }}>File source names (sample): <code style={{ fontSize: "0.78rem" }}>{importResult.diagnostics.sample_sources_in_file.join(", ")}</code></div>
              )}
              {importResult.diagnostics.sample_sources_in_db?.length > 0 && (
                <div>DB source names (sample): <code style={{ fontSize: "0.78rem" }}>{importResult.diagnostics.sample_sources_in_db.join(", ")}</code></div>
              )}
            </div>
          )}
        </div>
      )}
      {unconfirmedCount > 0 && (
        <div style={{ marginBottom: 12, padding: "8px 14px", background: "#fff7ed",
          borderRadius: 6, border: "1px solid #fdba74", color: "#9a3412", fontSize: "0.85rem" }}>
          ⚠️ {unconfirmedCount} network{unconfirmedCount !== 1 ? "s" : ""} pre-filled from source name but not yet confirmed.
          Review the PCD target name for each row and click <strong>Confirm</strong> to approve.
        </div>
      )}
      {error && <div style={alertError}>{error}</div>}
      <div style={{ overflowX: "auto" }}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Source Network (VMware)</th>
              <th style={{ ...thStyle, width: 70, textAlign: "center" }}>VMs</th>
              <th style={thStyle}>PCD Target Network</th>
              <th style={{ ...thStyle, width: 80 }}>VLAN ID</th>
              <th style={{ ...thStyle, width: 90 }}>Kind</th>
              <th style={{ ...thStyle, width: 90 }}>Status</th>
              <th style={{ ...thStyle, width: 90 }}>Action</th>
              <th style={{ ...thStyle, width: 110, textAlign: "center" }}>Subnet Details</th>
            </tr>
          </thead>
          <tbody>
            {mappings.map(m => {
              const editVal = editValues[m.id];
              const current = editVal !== undefined ? editVal : (m.target_network_name || "");
              const isEditing = editVal !== undefined;
              const isDirty = isEditing && editVal !== (m.target_network_name || "");
              const isConfirmed = m.confirmed === true;
              const isSubnetExpanded = expandedSubnet === m.id;
              const se = subnetEdits[m.id] ?? {};
              const kindLabel = (k?: string) => {
                if (k === "physical_l2") return { label: "L2", bg: "#f3e8ff", color: "#7c3aed" };
                if (k === "virtual") return { label: "Virtual", bg: "#e0f2fe", color: "#0369a1" };
                return { label: "Physical", bg: "#eff6ff", color: "#1d4ed8" };
              };
              const kStyle = kindLabel(m.network_kind);
              return (
                <React.Fragment key={m.id}>
                  <tr style={{
                    borderBottom: isSubnetExpanded ? undefined : "1px solid var(--border, #e5e7eb)",
                    background: isConfirmed ? undefined : "#fffbeb",
                  }}>
                    <td style={tdStyle}>
                      <strong style={{ fontFamily: "monospace", fontSize: "0.85rem" }}>{m.source_network_name}</strong>
                    </td>
                    <td style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>{m.vm_count ?? 0}</td>
                    <td style={tdStyle}>
                      <input
                        value={current}
                        onChange={e => {
                          setEditValues(prev => ({ ...prev, [m.id]: e.target.value }));
                          setEditVlanValues(prev => {
                            if (prev[m.id] !== undefined) return prev;
                            return { ...prev, [m.id]: m.vlan_id != null ? String(m.vlan_id) : "" };
                          });
                        }}
                        placeholder="PCD network name..."
                        style={{ ...inputStyle, padding: "4px 8px", fontSize: "0.85rem",
                          background: isDirty ? "#eff6ff" : undefined }}
                        onKeyDown={e => { if (e.key === "Enter") saveMapping(m.id); }}
                      />
                    </td>
                    <td style={{ ...tdStyle, color: "#6b7280", fontSize: "0.8rem" }}>
                      {isEditing || !isConfirmed ? (
                        <input
                          type="number"
                          value={editVlanValues[m.id] ?? (m.vlan_id != null ? String(m.vlan_id) : "")}
                          onChange={e => setEditVlanValues(prev => ({ ...prev, [m.id]: e.target.value }))}
                          placeholder="VLAN"
                          style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.8rem", width: 72 }}
                          onKeyDown={e => { if (e.key === "Enter") saveMapping(m.id); }}
                        />
                      ) : (m.vlan_id ?? "—")}
                    </td>
                    <td style={{ ...tdStyle, textAlign: "center" }}>
                      <select
                        value={m.network_kind ?? "physical_managed"}
                        disabled={savingKind === m.id}
                        onChange={async e => {
                          const newKind = e.target.value;
                          setSavingKind(m.id);
                          try {
                            await apiFetch(`/api/migration/projects/${projectId}/network-mappings/${m.id}`, {
                              method: "PATCH",
                              body: JSON.stringify({ network_kind: newKind }),
                            });
                            await load();
                          } catch (err: any) { setError(err.message); }
                          finally { setSavingKind(null); }
                        }}
                        style={{
                          fontSize: "0.75rem", padding: "2px 6px", borderRadius: 4,
                          border: `1px solid ${kStyle.color}40`,
                          background: kStyle.bg, color: kStyle.color,
                          cursor: "pointer", fontWeight: 500,
                        }}>
                        <option value="physical_managed">Physical</option>
                        <option value="physical_l2">L2</option>
                        <option value="virtual">Virtual</option>
                      </select>
                    </td>
                    <td style={{ ...tdStyle, textAlign: "center" }}>
                      {isConfirmed
                        ? <span style={{ ...pillStyle, background: "#dcfce7", color: "#15803d", fontSize: "0.72rem" }}>✓ confirmed</span>
                        : <span style={{ ...pillStyle, background: "#fff7ed", color: "#ea580c", fontSize: "0.72rem" }}>⚠ review</span>}
                    </td>
                    <td style={tdStyle}>
                      {isEditing || !isConfirmed ? (
                        <div style={{ display: "flex", gap: 4 }}>
                          <button
                            onClick={() => saveMapping(m.id)}
                            disabled={saving === m.id}
                            style={{ ...btnSmall,
                              background: isDirty ? "#2563eb" : "#f97316",
                              color: "#fff" }}
                            title={isDirty ? "Save changes" : "Confirm this mapping"}>
                            {saving === m.id ? "..." : isDirty ? "Save" : "Confirm"}
                          </button>
                          {isEditing && (
                            <button
                              onClick={() => cancelEditMapping(m.id)}
                              disabled={saving === m.id}
                              style={{ ...btnSmall, background: "#e5e7eb", color: "#374151" }}
                              title="Cancel edit">
                              ✕
                            </button>
                          )}
                        </div>
                      ) : (
                        <button
                          onClick={() => startEditMapping(m.id, m.target_network_name || "", m.vlan_id ?? null)}
                          style={{ ...btnSmall, background: "#f3f4f6", color: "#374151", fontSize: "0.75rem" }}
                          title="Edit this mapping">
                          ✏️ Edit
                        </button>
                      )}
                    </td>
                    <td style={{ ...tdStyle, textAlign: "center" }}>
                      {m.is_external ? (
                        <span style={{ ...pillStyle, background: "#f3f4f6", color: "#6b7280", fontSize: "0.72rem" }}>skip (ext)</span>
                      ) : m.subnet_details_confirmed ? (
                        <button
                          onClick={() => {
                            if (isSubnetExpanded) {
                              setExpandedSubnet(null);
                            } else {
                              setExpandedSubnet(m.id);
                              setSubnetEdits(prev => ({
                                ...prev,
                                [m.id]: {
                                  network_kind: m.network_kind ?? "physical_managed",
                                  cidr: m.cidr ?? "",
                                  gateway_ip: m.gateway_ip ?? "",
                                  dns_nameservers: (m.dns_nameservers ?? []).join(", "),
                                  allocation_pool_start: m.allocation_pool_start ?? "",
                                  allocation_pool_end: m.allocation_pool_end ?? "",
                                  dhcp_enabled: m.dhcp_enabled ?? true,
                                  is_external: m.is_external ?? false,
                                },
                              }));
                            }
                          }}
                          title={m.cidr ? `CIDR: ${m.cidr}${m.gateway_ip ? " | GW: " + m.gateway_ip : ""}` : "Subnet confirmed"}
                          style={{ ...btnSmall,
                            background: isSubnetExpanded ? "#eff6ff" : "#dcfce7",
                            color: isSubnetExpanded ? "#1d4ed8" : "#15803d",
                            fontSize: "0.72rem", fontFamily: m.cidr ? "monospace" : undefined,
                            maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          ✓ {m.cidr || "subnet ready"}
                        </button>
                      ) : isConfirmed ? (
                        <button
                          onClick={() => {
                            if (isSubnetExpanded) {
                              setExpandedSubnet(null);
                            } else {
                              setExpandedSubnet(m.id);
                              setSubnetEdits(prev => ({
                                ...prev,
                                [m.id]: {
                                  network_kind: m.network_kind ?? "physical_managed",
                                  cidr: m.cidr ?? "",
                                  gateway_ip: m.gateway_ip ?? "",
                                  dns_nameservers: (m.dns_nameservers ?? []).join(", "),
                                  allocation_pool_start: m.allocation_pool_start ?? "",
                                  allocation_pool_end: m.allocation_pool_end ?? "",
                                  dhcp_enabled: m.dhcp_enabled ?? true,
                                  is_external: m.is_external ?? false,
                                },
                              }));
                            }
                          }}
                          title={m.cidr ? `CIDR: ${m.cidr} — click to review & confirm` : "Enter subnet details"}
                          style={{ ...btnSmall,
                            background: isSubnetExpanded ? "#eff6ff" : (m.cidr ? "#fff7ed" : "#f3f4f6"),
                            color: isSubnetExpanded ? "#1d4ed8" : (m.cidr ? "#c2410c" : "#374151"),
                            fontSize: "0.72rem", fontFamily: m.cidr ? "monospace" : undefined,
                            maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {isSubnetExpanded ? "✕ Close" : (m.cidr ? `⚠ ${m.cidr}` : "⚙ Subnet")}
                        </button>
                      ) : (
                        <span style={{ color: "#9ca3af", fontSize: "0.78rem" }}>—</span>
                      )}
                    </td>
                  </tr>
                  {isSubnetExpanded && (
                    <tr style={{ borderBottom: "1px solid var(--border, #e5e7eb)", background: "#f0f9ff" }}>
                      <td colSpan={8} style={{ padding: "14px 18px" }}>
                        <div style={{ fontWeight: 600, marginBottom: 10, color: "#0c4a6e", fontSize: "0.88rem" }}>
                          🌐 Subnet Details — {m.source_network_name}
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 10, marginBottom: 12 }}>
                          <div>
                            <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 3 }}>Network Kind</label>
                            <select
                              value={se.network_kind ?? "physical_managed"}
                              onChange={e => updateSubnetEdit(m.id, "network_kind", e.target.value)}
                              style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }}>
                              <option value="physical_managed">Physical Managed</option>
                              <option value="physical_l2">Physical L2</option>
                              <option value="virtual">Virtual</option>
                            </select>
                          </div>
                          <div>
                            <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 3 }}>CIDR</label>
                            <input value={se.cidr ?? ""} onChange={e => updateSubnetEdit(m.id, "cidr", e.target.value)}
                              placeholder="e.g. 10.0.0.0/24"
                              style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }} />
                          </div>
                          <div>
                            <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 3 }}>Gateway IP</label>
                            <input value={se.gateway_ip ?? ""} onChange={e => updateSubnetEdit(m.id, "gateway_ip", e.target.value)}
                              placeholder="e.g. 10.0.0.1"
                              style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }} />
                          </div>
                          <div>
                            <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 3 }}>DNS Nameservers</label>
                            <input value={se.dns_nameservers ?? ""} onChange={e => updateSubnetEdit(m.id, "dns_nameservers", e.target.value)}
                              placeholder="8.8.8.8, 8.8.4.4"
                              style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }} />
                          </div>
                        </div>
                        {/* DHCP + Is External checkboxes — before pool so operator sets intent first */}
                        <div style={{ display: "flex", gap: 20, marginBottom: 10 }}>
                          <label style={{ fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                            <input type="checkbox" checked={se.dhcp_enabled ?? true}
                              onChange={e => {
                                updateSubnetEdit(m.id, "dhcp_enabled", e.target.checked);
                                // Clear pool when DHCP is disabled — no pool needed for static-only subnets
                                if (!e.target.checked) {
                                  updateSubnetEdit(m.id, "allocation_pool_start", "");
                                  updateSubnetEdit(m.id, "allocation_pool_end", "");
                                }
                              }} />
                            DHCP Enabled
                          </label>
                          <label style={{ fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                            <input type="checkbox" checked={se.is_external ?? false}
                              onChange={e => updateSubnetEdit(m.id, "is_external", e.target.checked)} />
                            Is External Network
                          </label>
                        </div>
                        {/* DHCP Allocation Pool — only shown when DHCP is enabled */}
                        {(se.dhcp_enabled ?? true) && (
                          <div style={{ background: "#f0f9ff", border: "1px solid #bae6fd", borderRadius: 6, padding: "10px 12px", marginBottom: 12 }}>
                            <div style={{ fontSize: "0.78rem", fontWeight: 600, color: "#0369a1", marginBottom: 6 }}>
                              DHCP Allocation Pool
                            </div>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 6 }}>
                              <div>
                                <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 3 }}>Pool Start</label>
                                <input value={se.allocation_pool_start ?? ""} onChange={e => updateSubnetEdit(m.id, "allocation_pool_start", e.target.value)}
                                  placeholder="e.g. 10.0.0.10"
                                  style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }} />
                              </div>
                              <div>
                                <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 3 }}>Pool End</label>
                                <input value={se.allocation_pool_end ?? ""} onChange={e => updateSubnetEdit(m.id, "allocation_pool_end", e.target.value)}
                                  placeholder="e.g. 10.0.0.200"
                                  style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }} />
                              </div>
                            </div>
                            <div style={{ fontSize: "0.72rem", color: "#0369a1" }}>
                              💡 The pool is the DHCP-assigned range. IPs in the subnet <strong>outside</strong> this pool remain available for static assignment (servers, VIPs, etc.).
                            </div>
                          </div>
                        )}
                        <div style={{ display: "flex", gap: 8 }}>
                          <button
                            onClick={() => saveSubnetDetails(m.id)}
                            disabled={savingSubnet === m.id}
                            style={{ ...btnSmall, background: "#16a34a", color: "#fff", fontSize: "0.82rem", padding: "6px 14px" }}>
                            {savingSubnet === m.id ? "⏳ Saving..." : "✓ Save Subnet Details"}
                          </button>
                          <button
                            onClick={() => setExpandedSubnet(null)}
                            style={{ ...btnSmall, background: "#e5e7eb", color: "#374151", fontSize: "0.82rem", padding: "6px 14px" }}>
                            Cancel
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
            {mappings.length === 0 && (
              <tr><td colSpan={8} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
                No networks found. Upload RVTools data and run assessment first.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  Cohorts View  (Phase 2.10G)                                       */
/* ================================================================== */

interface Cohort {
  id: number;
  project_id: string;
  name: string;
  description: string | null;
  cohort_order: number;
  status: string;
  scheduled_start: string | null;
  scheduled_end: string | null;
  owner_name: string | null;
  depends_on_cohort_id: number | null;
  schedule_duration_days: number | null;  // planned working days
  target_vms_per_day: number | null;       // VMs/day override (null = use project level)
  tenant_count: number;
  vm_count: number;
  total_vcpu: number;
  total_ram_gb: number;
}

function CohortsView({ projectId, project, tenants, onRefreshTenants }: {
  projectId: number; project: MigrationProject; tenants: Tenant[]; onRefreshTenants: () => void
}) {
  const [cohorts, setCohorts] = useState<Cohort[]>([]);
  const [unassignedCount, setUnassignedCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newOrder, setNewOrder] = useState(1);
  const [newOwner, setNewOwner] = useState("");
  const [newStart, setNewStart] = useState("");
  const [newEnd, setNewEnd] = useState("");
  const [newDependsOn, setNewDependsOn] = useState<number | "">("");
  const [newDurationDays, setNewDurationDays] = useState<number | "">("");
  const [newVmsPerDay, setNewVmsPerDay] = useState<number | "">("");
  const [creating, setCreating] = useState(false);
  const [selectedCohort, setSelectedCohort] = useState<number | null>(null);
  const [selectedTenants, setSelectedTenants] = useState<Set<number>>(new Set());
  const [assigning, setAssigning] = useState(false);
  const [autoStrategy, setAutoStrategy] = useState("easiest_first");
  const [autoAssigning, setAutoAssigning] = useState(false);
  const [showAutoPanel, setShowAutoPanel] = useState(false);
  const [numCohorts, setNumCohorts] = useState(3);
  const [maxVms, setMaxVms] = useState(9999);
  const [maxDiskTb, setMaxDiskTb] = useState(9999);
  const [maxAvgRisk, setMaxAvgRisk] = useState(100);
  const [minOsSupport, setMinOsSupport] = useState(0);
  const [pilotSize, setPilotSize] = useState(5);
  const [pilotWaves, setPilotWaves] = useState<string[]>(["\u{1F9EA} Pilot", "\u{1F504} Wave 1", "\u{1F680} Main"]);
  const [autoPreview, setAutoPreview] = useState<any>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [cohortEaseScores, setCohortEaseScores] = useState<Record<number, TenantEaseScore>>({});
  const [showWhatIf, setShowWhatIf] = useState(false);
  const [expandedCohort, setExpandedCohort] = useState<number | null>(null);
  const [reassigning, setReassigning] = useState<Record<number, boolean>>({});
  const [bandwidthMbps, setBandwidthMbps] = useState(1000);
  const [agentSlots, setAgentSlots] = useState(2);
  const [rampMode, setRampMode] = useState(false);
  const [cohortProfiles, setCohortProfiles] = useState<{ name: string; max_vms: number | null }[]>([
    { name: "🧪 Pilot",  max_vms: 10 },
    { name: "🔄 Wave 1", max_vms: 50 },
    { name: "🚀 Wave 2", max_vms: null },
  ]);

  const loadCohorts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ cohorts: Cohort[]; unassigned_tenant_count: number }>(
        `/api/migration/projects/${projectId}/cohorts`
      );
      setCohorts(data.cohorts);
      setUnassignedCount(data.unassigned_tenant_count);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { loadCohorts(); }, [loadCohorts]);

  const createCohort = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await apiFetch(`/api/migration/projects/${projectId}/cohorts`, {
        method: "POST",
        body: JSON.stringify({
          name: newName.trim(),
          cohort_order: newOrder,
          owner_name: newOwner.trim() || null,
          scheduled_start: newStart || null,
          scheduled_end: newEnd || null,
          depends_on_cohort_id: newDependsOn || null,
          schedule_duration_days: newDurationDays || null,
          target_vms_per_day: newVmsPerDay || null,
        }),
      });
      setNewName(""); setNewOrder(cohorts.length + 1); setNewOwner("");
      setNewStart(""); setNewEnd(""); setNewDependsOn("");
      setNewDurationDays(""); setNewVmsPerDay("");
      setShowCreate(false);
      loadCohorts();
    } catch (e: any) { setError(e.message); }
    finally { setCreating(false); }
  };

  const deleteCohort = async (id: number) => {
    if (!confirm("Delete this cohort? Tenants will be unassigned (not deleted).")) return;
    try {
      await apiFetch(`/api/migration/projects/${projectId}/cohorts/${id}`, { method: "DELETE" });
      loadCohorts(); onRefreshTenants();
    } catch (e: any) { setError(e.message); }
  };

  const assignTenants = async () => {
    if (!selectedCohort || selectedTenants.size === 0) return;
    setAssigning(true);
    try {
      await apiFetch(`/api/migration/projects/${projectId}/cohorts/${selectedCohort}/assign-tenants`, {
        method: "POST",
        body: JSON.stringify({ tenant_ids: Array.from(selectedTenants) }),
      });
      setSelectedTenants(new Set());
      loadCohorts(); onRefreshTenants();
    } catch (e: any) { setError(e.message); }
    finally { setAssigning(false); }
  };

  useEffect(() => {
    apiFetch<{ tenant_ease_scores: TenantEaseScore[] }>(
      `/api/migration/projects/${projectId}/tenant-ease-scores`
    ).then(d => {
      const map: Record<number, TenantEaseScore> = {};
      for (const s of d.tenant_ease_scores) map[s.tenant_id] = s;
      setCohortEaseScores(map);
    }).catch(() => {});
  }, [projectId, tenants.length]);

  const buildGuardrails = () => ({
    max_vms_per_cohort: maxVms,
    max_disk_tb_per_cohort: maxDiskTb,
    max_avg_risk: maxAvgRisk,
    min_os_support_rate: minOsSupport,
    pilot_size: pilotSize,
  });

  const previewAutoAssign = async () => {
    setPreviewLoading(true); setAutoPreview(null);
    try {
      const isPilotWave = !rampMode && autoStrategy === "pilot_bulk";
      const result = await apiFetch(`/api/migration/projects/${projectId}/cohorts/auto-assign`, {
        method: "POST",
        body: JSON.stringify({
          strategy: autoStrategy,
          num_cohorts: rampMode ? cohortProfiles.length : isPilotWave ? pilotWaves.length : numCohorts,
          guardrails: buildGuardrails(), dry_run: true, create_cohorts_if_missing: true,
          cohort_profiles: rampMode ? cohortProfiles : isPilotWave ? pilotWaves.map(n => ({ name: n, max_vms: null })) : undefined,
        }),
      });
      setAutoPreview(result);
    } catch (e: any) { setError(e.message); }
    finally { setPreviewLoading(false); }
  };

  const autoAssign = async () => {
    if (!confirm(`Apply auto-assign using "${autoStrategy}" strategy? This will update tenant cohort assignments.`)) return;
    setAutoAssigning(true);
    try {
      const isPilotWave = !rampMode && autoStrategy === "pilot_bulk";
      await apiFetch(`/api/migration/projects/${projectId}/cohorts/auto-assign`, {
        method: "POST",
        body: JSON.stringify({
          strategy: autoStrategy,
          num_cohorts: rampMode ? cohortProfiles.length : isPilotWave ? pilotWaves.length : numCohorts,
          guardrails: buildGuardrails(), dry_run: false, create_cohorts_if_missing: true,
          cohort_profiles: rampMode ? cohortProfiles : isPilotWave ? pilotWaves.map(n => ({ name: n, max_vms: null })) : undefined,
        }),
      });
      setAutoPreview(null); setShowAutoPanel(false);
      loadCohorts(); onRefreshTenants();
    } catch (e: any) { setError(e.message); }
    finally { setAutoAssigning(false); }
  };

  const statusColors: Record<string, [string, string]> = {
    planning:  ["#f3f4f6", "#6b7280"],
    ready:     ["#dbeafe", "#1d4ed8"],
    executing: ["#fef9c3", "#854d0e"],
    complete:  ["#dcfce7", "#15803d"],
    paused:    ["#f5f3ff", "#7c3aed"],
  };

  const unassignedTenants = tenants.filter(t => !t.cohort_id && t.include_in_plan !== false);

  if (loading) return <div style={{ color: "#6b7280", padding: 16 }}>Loading cohorts...</div>;

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>🗃️ Migration Cohorts</h3>
        <span style={{ fontSize: "0.85rem", color: "#6b7280" }}>
          {cohorts.length} cohort{cohorts.length !== 1 ? "s" : ""} &nbsp;·&nbsp;
          {unassignedCount} tenant{unassignedCount !== 1 ? "s" : ""} unassigned
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button onClick={() => { setShowAutoPanel(v => !v); setAutoPreview(null); }}
            style={{ ...btnSecondary, background: showAutoPanel ? "#eff6ff" : undefined, color: showAutoPanel ? "#1d4ed8" : undefined }}
            title="Smart auto-assign tenants to cohorts">
            ⚡ Smart Auto-Assign {showAutoPanel ? "▲" : "▼"}
          </button>
          <button onClick={() => setShowCreate(!showCreate)} style={btnPrimary}>+ New Cohort</button>
        </div>
      </div>
      {error && <div style={alertError}>{error}</div>}

      {/* ── Smart Auto-Assign panel ── */}
      {showAutoPanel && (
        <div style={{ ...sectionStyle, marginBottom: 16, background: "#f0f9ff", borderColor: "#bae6fd" }}>

          {/* Header + mode toggle */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
            <div style={{ fontWeight: 700, fontSize: "0.9rem", color: "#0369a1" }}>⚡ Smart Auto-Assign — Phase 3.0</div>
            <div style={{ display: "flex", background: "#e0f2fe", borderRadius: 20, padding: 2, gap: 2 }}>
              <button onClick={() => { setRampMode(false); setAutoPreview(null); }}
                style={{ padding: "3px 14px", borderRadius: 18, border: "none", cursor: "pointer", fontSize: "0.78rem",
                  background: !rampMode ? "#0369a1" : "transparent", color: !rampMode ? "#fff" : "#0369a1", fontWeight: 600 }}>
                Uniform
              </button>
              <button onClick={() => { setRampMode(true); setAutoPreview(null); }}
                style={{ padding: "3px 14px", borderRadius: 18, border: "none", cursor: "pointer", fontSize: "0.78rem",
                  background: rampMode ? "#0369a1" : "transparent", color: rampMode ? "#fff" : "#0369a1", fontWeight: 600 }}
                title="Define named cohorts with individual VM caps — e.g. Pilot (5 VMs) → Wave 1 (30 VMs) → Wave 2 (unlimited)">
                Ramp Profile
              </button>
            </div>
          </div>

          {/* Unassigned pool distribution bar */}
          {(() => {
            const unassigned = tenants.filter(t => !t.cohort_id && t.include_in_plan !== false);
            const us = unassigned.map(t => cohortEaseScores[t.id]).filter(Boolean);
            if (!unassigned.length) return null;
            const easy = us.filter(e => e.ease_score < 30).length;
            const med  = us.filter(e => e.ease_score >= 30 && e.ease_score < 60).length;
            const hard = us.filter(e => e.ease_score >= 60).length;
            const total = us.length || 1;
            return (
              <div style={{ marginBottom: 12, background: "#e0f2fe", borderRadius: 6, padding: "6px 10px" }}>
                <div style={{ fontSize: "0.75rem", color: "#0369a1", fontWeight: 600, marginBottom: 4 }}>
                  {unassigned.length} unassigned tenant{unassigned.length !== 1 ? "s" : ""} in pool
                  {us.length < unassigned.length && <span style={{ marginLeft: 6, color: "#9ca3af", fontWeight: 400 }}>(ease scores loading…)</span>}
                </div>
                {us.length > 0 && (
                  <>
                    <div style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", gap: 1, marginBottom: 3 }}>
                      {easy > 0 && <div style={{ flex: easy, background: "#86efac" }} title={`${easy} easy tenants`} />}
                      {med  > 0 && <div style={{ flex: med,  background: "#fde68a" }} title={`${med} medium tenants`} />}
                      {hard > 0 && <div style={{ flex: hard, background: "#fca5a5" }} title={`${hard} hard tenants`} />}
                    </div>
                    <div style={{ display: "flex", gap: 12, fontSize: "0.72rem" }}>
                      {easy > 0 && <span style={{ color: "#15803d" }}>● {easy} easy ({Math.round(easy/total*100)}%)</span>}
                      {med  > 0 && <span style={{ color: "#854d0e" }}>● {med} medium ({Math.round(med/total*100)}%)</span>}
                      {hard > 0 && <span style={{ color: "#dc2626" }}>● {hard} hard ({Math.round(hard/total*100)}%)</span>}
                    </div>
                  </>
                )}
              </div>
            );
          })()}

          {/* Strategy picker + description */}
          <div style={{ marginBottom: 12 }}>
            <label style={labelStyle}>
              Strategy <span title="How tenants are sorted and distributed across cohorts" style={{ cursor: "help", color: "#9ca3af", fontSize: "0.75rem" }}>ⓘ</span>
            </label>
            <select value={autoStrategy} onChange={e => {
              const s = e.target.value;
              setAutoStrategy(s);
              setAutoPreview(null);
              // initialise pilot wave list when switching to pilot_bulk
              if (s === "pilot_bulk" && pilotWaves.length < 2) {
                setPilotWaves(["\u{1F9EA} Pilot", "\u{1F504} Wave 1", "\u{1F680} Main"]);
              }
            }}
              style={{ ...inputStyle, maxWidth: 260 }}>
              <option value="easiest_first">Easiest First</option>
              <option value="riskiest_last">Riskiest Last</option>
              <option value="pilot_bulk">Pilot + Waves</option>
              <option value="balanced_load">Balanced Load (by disk GB)</option>
              <option value="os_first">OS First (Linux → Windows)</option>
              <option value="by_priority">By Priority</option>
            </select>
            <div style={{ marginTop: 5, fontSize: "0.75rem", color: "#6b7280", fontStyle: "italic", maxWidth: 520 }}>
              {({
                easiest_first: "Tenants sorted by ease score (lowest = easiest). Each cohort fills to its limit before the next. Best for low-risk early waves.",
                riskiest_last: "High-risk tenants (above threshold %) always land in the final cohort. Safe tenants fill earlier cohorts by ease score.",
                pilot_bulk:    "The N easiest tenants form a small Pilot cohort. Remaining tenants fill Wave 1 … Wave N-1 in ease order, with the last cohort as Main. Use Target Cohorts to set how many waves (2 = Pilot + Main, 3 = Pilot + Wave 1 + Main, etc.).",
                balanced_load: "Greedy bin-packing by used-disk GB to equalise migration workload across cohorts. Best for bandwidth budget planning.",
                os_first:      "Linux tenants fill early cohorts, Windows fill later ones. Use when Linux migrations are faster or simpler for your team.",
                by_priority:   "Uses the Migration Priority number you assigned per tenant. Lower number = earlier cohort. Ties broken by ease score.",
              } as Record<string,string>)[autoStrategy]}
            </div>
          </div>

          {/* ── UNIFORM MODE ── */}
          {!rampMode && (
            <div style={{ marginBottom: 12 }}>
              {/* Pilot+Waves: interactive wave list */}
              {autoStrategy === "pilot_bulk" ? (
                <div>
                  <div style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <span style={{ fontSize: "0.75rem", color: "#0369a1", fontWeight: 600 }}>Quick presets:</span>
                    {([
                      { label: "Pilot → Main",   waves: ["\u{1F9EA} Pilot", "\u{1F680} Main"] },
                      { label: "3-Wave",         waves: ["\u{1F9EA} Pilot", "\u{1F504} Wave 1", "\u{1F680} Main"] },
                      { label: "4-Wave",         waves: ["\u{1F9EA} Pilot", "\u{1F504} Wave 1", "\u{1F504} Wave 2", "\u{1F680} Main"] },
                      { label: "5-Wave",         waves: ["\u{1F9EA} Pilot", "\u{1F504} Wave 1", "\u{1F504} Wave 2", "\u{1F504} Wave 3", "\u{1F680} Main"] },
                    ] as { label: string; waves: string[] }[]).map(p => (
                      <button key={p.label} onClick={() => { setPilotWaves(p.waves); setAutoPreview(null); }}
                        style={{ ...btnSmall, fontSize: "0.72rem" }}>{p.label}</button>
                    ))}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 8 }}>
                    {pilotWaves.map((name, idx) => (
                      <div key={idx} style={{ display: "flex", gap: 6, alignItems: "center", background: "#fff",
                        borderRadius: 6, padding: "5px 10px", border: "1px solid #bae6fd" }}>
                        <span style={{ fontSize: "0.72rem", color: "#0369a1", fontWeight: 700, minWidth: 18, textAlign: "right" }}>{idx + 1}.</span>
                        <input value={name}
                          onChange={e => { setPilotWaves(ws => ws.map((w, i) => i === idx ? e.target.value : w)); setAutoPreview(null); }}
                          style={{ ...inputStyle, maxWidth: 200, marginBottom: 0 }} placeholder="Wave name" />
                        {idx === 0 && (
                          <span style={{ fontSize: "0.72rem", color: "#6b7280", whiteSpace: "nowrap" }}>
                            Pilot size: <input type="number" min={1} value={pilotSize}
                              onChange={e => { setPilotSize(Number(e.target.value)); setAutoPreview(null); }}
                              style={{ ...inputStyle, maxWidth: 52, marginBottom: 0, display: "inline-block" }} />
                          </span>
                        )}
                        {pilotWaves.length > 2 && idx > 0 && idx < pilotWaves.length - 1 && (
                          <button onClick={() => { setPilotWaves(ws => ws.filter((_, i) => i !== idx)); setAutoPreview(null); }}
                            style={{ ...btnSmall, color: "#dc2626", padding: "1px 6px" }} title="Remove this wave">✕</button>
                        )}
                      </div>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                    <button onClick={() => {
                      setPilotWaves(ws => [
                        ...ws.slice(0, -1),
                        `\u{1F504} Wave ${ws.length - 1}`,
                        ws[ws.length - 1],
                      ]); setAutoPreview(null);
                    }} style={btnSmall}>+ Add Wave</button>
                    <span style={{ fontSize: "0.72rem", color: "#6b7280" }}>ⓘ Pilot catches the N easiest tenants. Remaining tenants fill waves in ease order. Last cohort catches overflow.</span>
                  </div>
                  {/* Guardrail row for pilot_bulk */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(155px, 1fr))", gap: 8 }}>
                    <div>
                      <label style={labelStyle}>Max VMs / Wave <span title="Hard cap on VM count per wave. Overflow goes to the next wave." style={{ cursor: "help", color: "#9ca3af", fontSize: "0.75rem" }}>ⓘ</span></label>
                      <input type="number" min={1} value={maxVms === 9999 ? "" : maxVms} placeholder="unlimited"
                        onChange={e => { setMaxVms(e.target.value ? Number(e.target.value) : 9999); setAutoPreview(null); }} style={inputStyle} />
                    </div>
                    <div>
                      <label style={labelStyle}>Max Disk TB / Wave <span title="Hard cap on used-disk per wave (TB)." style={{ cursor: "help", color: "#9ca3af", fontSize: "0.75rem" }}>ⓘ</span></label>
                      <input type="number" min={0.1} step={0.1} value={maxDiskTb === 9999 ? "" : maxDiskTb} placeholder="unlimited"
                        onChange={e => { setMaxDiskTb(e.target.value ? Number(e.target.value) : 9999); setAutoPreview(null); }} style={inputStyle} />
                    </div>
                  </div>
                </div>
              ) : (
                /* All other strategies: uniform grid of guardrail controls */
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(155px, 1fr))", gap: 8 }}>
                  <div>
                    <label style={labelStyle}>Target Cohorts <span title="Number of cohorts to distribute tenants into. New cohorts are created automatically when Apply is clicked." style={{ cursor: "help", color: "#9ca3af", fontSize: "0.75rem" }}>ⓘ</span></label>
                    <input type="number" min={1} max={20} value={numCohorts}
                      onChange={e => { setNumCohorts(Number(e.target.value)); setAutoPreview(null); }} style={inputStyle} />
                  </div>
                  <div>
                    <label style={labelStyle}>Max VMs / Cohort <span title="Hard cap on VM count per cohort. When a tenant would push over this, the engine overflows it into the next cohort." style={{ cursor: "help", color: "#9ca3af", fontSize: "0.75rem" }}>ⓘ</span></label>
                    <input type="number" min={1} value={maxVms === 9999 ? "" : maxVms} placeholder="unlimited"
                      onChange={e => { setMaxVms(e.target.value ? Number(e.target.value) : 9999); setAutoPreview(null); }} style={inputStyle} />
                  </div>
                  <div>
                    <label style={labelStyle}>Max Disk TB / Cohort <span title="Hard cap on total used-disk (TB) per cohort. 1 TB = 1024 GB." style={{ cursor: "help", color: "#9ca3af", fontSize: "0.75rem" }}>ⓘ</span></label>
                    <input type="number" min={0.1} step={0.1} value={maxDiskTb === 9999 ? "" : maxDiskTb} placeholder="unlimited"
                      onChange={e => { setMaxDiskTb(e.target.value ? Number(e.target.value) : 9999); setAutoPreview(null); }} style={inputStyle} />
                  </div>
                  <div>
                    <label style={labelStyle}>Max Avg Risk % <span title="If a cohort's running average risk score would exceed this %, the overflowing tenant is pushed to the next cohort." style={{ cursor: "help", color: "#9ca3af", fontSize: "0.75rem" }}>ⓘ</span></label>
                    <input type="number" min={0} max={100} value={maxAvgRisk === 100 ? "" : maxAvgRisk} placeholder="100"
                      onChange={e => { setMaxAvgRisk(e.target.value ? Number(e.target.value) : 100); setAutoPreview(null); }} style={inputStyle} />
                  </div>
                  <div>
                    <label style={labelStyle}>Min OS Support % <span title="Minimum % of VMs in a cohort that must have a recognised OS." style={{ cursor: "help", color: "#9ca3af", fontSize: "0.75rem" }}>ⓘ</span></label>
                    <input type="number" min={0} max={100} step={5} value={minOsSupport || ""} placeholder="0"
                      onChange={e => { setMinOsSupport(e.target.value ? Number(e.target.value) : 0); setAutoPreview(null); }} style={inputStyle} />
                  </div>
                  {autoStrategy === "riskiest_last" && (
                    <div>
                      <label style={labelStyle}>Risk Threshold %
                        <span title="Tenants whose average risk score is at or above this value are always placed in the last cohort."
                          style={{ cursor: "help", color: "#9ca3af", fontSize: "0.75rem", marginLeft: 3 }}>ⓘ</span>
                      </label>
                      <input type="number" min={0} max={100} defaultValue={70} placeholder="70"
                        onChange={e => setMaxAvgRisk(e.target.value ? Number(e.target.value) : 70)} style={inputStyle} />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── RAMP PROFILE MODE ── */}
          {rampMode && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap", alignItems: "center" }}>
                <span style={{ fontSize: "0.75rem", color: "#0369a1", fontWeight: 600 }}>Quick presets:</span>
                {([
                  { label: "Pilot → Bulk",  profiles: [{ name: "🧪 Pilot", max_vms: 5 }, { name: "🚀 Bulk", max_vms: null }] },
                  { label: "3-Wave",        profiles: [{ name: "🧪 Pilot", max_vms: 10 }, { name: "🔄 Wave 1", max_vms: 50 }, { name: "🚀 Wave 2", max_vms: null }] },
                  { label: "4-Wave",        profiles: [{ name: "🧪 Pilot", max_vms: 5 }, { name: "🔄 Wave 1", max_vms: 25 }, { name: "🔄 Wave 2", max_vms: 60 }, { name: "🚀 Wave 3", max_vms: null }] },
                  { label: "5-Wave",        profiles: [{ name: "🧪 Pilot", max_vms: 5 }, { name: "🔄 Wave 1", max_vms: 15 }, { name: "🔄 Wave 2", max_vms: 35 }, { name: "🔄 Wave 3", max_vms: 60 }, { name: "🚀 Wave 4", max_vms: null }] },
                ] as { label: string; profiles: { name: string; max_vms: number | null }[] }[]).map(p => (
                  <button key={p.label} onClick={() => { setCohortProfiles(p.profiles); setAutoPreview(null); }}
                    style={{ ...btnSmall, fontSize: "0.72rem" }}>{p.label}</button>
                ))}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                {cohortProfiles.map((profile, idx) => (
                  <div key={idx} style={{ display: "flex", gap: 6, alignItems: "center", background: "#fff",
                    borderRadius: 6, padding: "6px 10px", border: "1px solid #bae6fd" }}>
                    <span style={{ fontSize: "0.72rem", color: "#0369a1", fontWeight: 700, minWidth: 18, textAlign: "right" }}>{idx + 1}.</span>
                    <input value={profile.name}
                      onChange={e => { setCohortProfiles(pf => pf.map((p, i) => i === idx ? { ...p, name: e.target.value } : p)); setAutoPreview(null); }}
                      style={{ ...inputStyle, maxWidth: 180, marginBottom: 0 }} placeholder="Cohort name" />
                    <span style={{ fontSize: "0.75rem", color: "#6b7280", whiteSpace: "nowrap" }}>
                      Max VMs <span title="Maximum number of VMs this cohort can absorb. When full, remaining tenants spill into the next cohort. Leave blank for unlimited (the last cohort always catches all overflow)." style={{ cursor: "help", color: "#9ca3af" }}>ⓘ</span>
                    </span>
                    <input type="number" min={1} value={profile.max_vms ?? ""} placeholder="∞"
                      onChange={e => { setCohortProfiles(pf => pf.map((p, i) => i === idx ? { ...p, max_vms: e.target.value ? Number(e.target.value) : null } : p)); setAutoPreview(null); }}
                      style={{ ...inputStyle, maxWidth: 72, marginBottom: 0 }} />
                    {cohortProfiles.length > 1 && (
                      <button onClick={() => { setCohortProfiles(pf => pf.filter((_, i) => i !== idx)); setAutoPreview(null); }}
                        style={{ ...btnSmall, color: "#dc2626", padding: "1px 6px" }} title="Remove this cohort">✕</button>
                    )}
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
                <button onClick={() => setCohortProfiles(pf => [...pf, { name: `🔄 Wave ${pf.length}`, max_vms: null }])}
                  style={btnSmall}>+ Add Cohort</button>
                <span style={{ fontSize: "0.72rem", color: "#6b7280" }}>
                  ⓘ Tenants are sorted by the selected strategy and fill each cohort in order. The last cohort always catches overflow.
                </span>
              </div>
            </div>
          )}

          {/* Action row */}
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 4 }}>
            <button onClick={previewAutoAssign} disabled={previewLoading} style={{ ...btnSecondary }}>
              {previewLoading ? "⏳ Calculating..." : "🔍 Preview"}
            </button>
            <button onClick={autoAssign} disabled={autoAssigning || !autoPreview} style={{ ...btnPrimary }}
              title={!autoPreview ? "Run Preview first to validate before committing" : undefined}>
              {autoAssigning ? "Applying..." : "✅ Apply"}
            </button>
            <button onClick={() => { setShowAutoPanel(false); setAutoPreview(null); }} style={btnSecondary}>✕ Close</button>
            {!autoPreview && (
              <span style={{ fontSize: "0.78rem", color: "#6b7280" }}>
                🔒 Preview first — Apply is locked until you see the projected assignment.
              </span>
            )}
          </div>

          {/* Preview results */}
          {autoPreview && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontWeight: 600, marginBottom: 8, color: "#0369a1" }}>
                Preview — {autoPreview.assignments?.length ?? 0} tenants →{" "}
                {(autoPreview.cohort_summaries ?? []).length} cohorts
                {autoPreview.warnings?.length > 0 && (
                  <span style={{ marginLeft: 8, color: "#ea580c", fontSize: "0.78rem" }}>
                    ⚠️ {autoPreview.warnings.length} warning{autoPreview.warnings.length > 1 ? "s" : ""}
                  </span>
                )}
              </div>
              {autoPreview.warnings?.map((w: string, i: number) => (
                <div key={i} style={{ fontSize: "0.78rem", color: "#ea580c", marginBottom: 4 }}>⚠️ {w}</div>
              ))}
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", fontSize: "0.78rem", borderCollapse: "collapse", background: "#fff", borderRadius: 6 }}>
                  <thead>
                    <tr style={{ background: "#f0f9ff" }}>
                      {["Cohort", "Tenants", "VMs", "Disk (GB)", "Avg Risk", "Avg Ease"].map(h => (
                        <th key={h} style={{ padding: "5px 8px", textAlign: h === "Cohort" ? "left" : "right",
                          fontWeight: 600, color: "#374151", borderBottom: "1px solid #bae6fd" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(autoPreview.cohort_summaries ?? []).map((row: any, i: number) => (
                      <tr key={i} style={{ borderBottom: "1px solid #e5e7eb" }}>
                        <td style={{ padding: "4px 8px", fontWeight: 600 }}>{row.name ?? `Cohort ${i+1}`}</td>
                        <td style={{ padding: "4px 8px", textAlign: "right" }}>{row.tenant_count ?? "—"}</td>
                        <td style={{ padding: "4px 8px", textAlign: "right" }}>{row.vm_count ?? "—"}</td>
                        <td style={{ padding: "4px 8px", textAlign: "right" }}>{typeof row.total_disk_gb === "number" ? row.total_disk_gb.toFixed(0) : "—"}</td>
                        <td style={{ padding: "4px 8px", textAlign: "right",
                          color: (row.avg_risk ?? row.avg_risk_score ?? 0) > 70 ? "#dc2626" : "#15803d" }}>
                          {typeof (row.avg_risk ?? row.avg_risk_score) === "number" ? (row.avg_risk ?? row.avg_risk_score).toFixed(0) : "—"}
                        </td>
                        <td style={{ padding: "4px 8px", textAlign: "right", fontWeight: 700,
                          color: (row.avg_ease_score ?? 50) < 30 ? "#15803d" : (row.avg_ease_score ?? 50) < 60 ? "#854d0e" : "#dc2626" }}>
                          {typeof row.avg_ease_score === "number" ? row.avg_ease_score.toFixed(0) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div style={{ ...sectionStyle, marginBottom: 16 }}>
          <h4 style={{ margin: "0 0 8px" }}>New Cohort</h4>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8, marginBottom: 8 }}>
            <div>
              <label style={labelStyle}>Name *</label>
              <input value={newName} onChange={e => setNewName(e.target.value)}
                style={inputStyle} placeholder="e.g. Wave 1 - Dev/Test" />
            </div>
            <div>
              <label style={labelStyle}>Order</label>
              <input type="number" value={newOrder} onChange={e => setNewOrder(Number(e.target.value))}
                style={inputStyle} min={1} />
            </div>
            <div>
              <label style={labelStyle}>Owner</label>
              <input value={newOwner} onChange={e => setNewOwner(e.target.value)}
                style={inputStyle} placeholder="e.g. Cloud Team" />
            </div>
            <div>
              <label style={labelStyle}>Depends On</label>
              <select value={newDependsOn} onChange={e => setNewDependsOn(e.target.value ? Number(e.target.value) : "")}
                style={inputStyle}>
                <option value="">None (can start any time)</option>
                {cohorts.map(c => (
                  <option key={c.id} value={c.id}>Cohort {c.cohort_order}: {c.name}</option>
                ))}
              </select>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 8, alignItems: "end" }}>
            <div>
              <label style={labelStyle}>Scheduled Start</label>
              <input type="date" value={newStart} onChange={e => setNewStart(e.target.value)} style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>Scheduled End</label>
              <input type="date" value={newEnd} onChange={e => setNewEnd(e.target.value)} style={inputStyle} />
            </div>
            <div />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 8, alignItems: "end" }}>
            <div>
              <label style={labelStyle}>Duration (working days)</label>
              <input type="number" min={1} value={newDurationDays} placeholder="e.g. 10"
                onChange={e => setNewDurationDays(e.target.value ? Number(e.target.value) : "")}
                style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>VMs / day <span style={{ color: "#9ca3af", fontWeight: 400 }}>(overrides project)</span></label>
              <input type="number" min={1} value={newVmsPerDay} placeholder="e.g. 5"
                onChange={e => setNewVmsPerDay(e.target.value ? Number(e.target.value) : "")}
                style={inputStyle} />
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <button onClick={createCohort} disabled={creating || !newName.trim()}
                style={{ ...btnPrimary }}>{creating ? "..." : "Create"}</button>
              <button onClick={() => setShowCreate(false)} style={btnSecondary}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Cohort cards */}
      {cohorts.length === 0 ? (
        <div style={{ padding: "40px 24px", textAlign: "center", color: "#9ca3af", background: "var(--card-bg, #f9fafb)", borderRadius: 8, border: "1px dashed #d1d5db" }}>
          <div style={{ fontSize: "2rem", marginBottom: 8 }}>🗃️</div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>No cohorts yet</div>
          <div style={{ fontSize: "0.85rem" }}>
            Create cohorts to split your migration into manageable groups.<br />
            Each cohort gets its own schedule, owner, and tenant assignments.
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16, marginBottom: 20 }}>
          {cohorts.map(c => {
            const [sbg, scol] = statusColors[c.status] || statusColors.planning;
            // Phase 3.0: compute ease stats from member tenants
            const members = tenants.filter(t => t.cohort_id === c.id);
            const memberScores = members.map(t => cohortEaseScores[t.id]).filter(Boolean);
            const avgEase = memberScores.length > 0
              ? memberScores.reduce((s, e) => s + e.ease_score, 0) / memberScores.length : null;
            const totalDiskGb = memberScores.reduce((s, e) => s + e.total_used_gb, 0);
            const avgRisk = memberScores.length > 0
              ? memberScores.reduce((s, e) => s + e.avg_risk_score, 0) / memberScores.length : null;
            const easyCount = memberScores.filter(e => e.ease_score < 30).length;
            const medCount  = memberScores.filter(e => e.ease_score >= 30 && e.ease_score < 60).length;
            const hardCount = memberScores.filter(e => e.ease_score >= 60).length;
            return (
              <div key={c.id} style={{ border: "1px solid var(--border, #e5e7eb)", borderRadius: 8, padding: 16,
                background: "var(--card-bg, #ffffff)",
                boxShadow: selectedCohort === c.id ? "0 0 0 2px #2563eb" : undefined }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                  <div>
                    <span style={{ fontSize: "0.7rem", fontWeight: 700, color: "#9ca3af", letterSpacing: "0.05em" }}>
                      COHORT {c.cohort_order}
                    </span>
                    <div style={{ fontWeight: 700, fontSize: "1rem" }}>{c.name}</div>
                    {c.owner_name && <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>👤 {c.owner_name}</div>}
                  </div>
                  <div style={{ display: "flex", gap: 4, flexDirection: "column", alignItems: "flex-end" }}>
                    <span style={{ ...pillStyle, background: sbg, color: scol, fontSize: "0.72rem" }}>{c.status}</span>
                    {c.depends_on_cohort_id && (
                      <span style={{ fontSize: "0.7rem", color: "#9ca3af" }}>
                        🔒 after C{cohorts.find(x => x.id === c.depends_on_cohort_id)?.cohort_order ?? "?"}
                      </span>
                    )}
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 8, fontSize: "0.82rem" }}>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{c.tenant_count}</div>
                    <div style={{ color: "#6b7280" }}>Tenants</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{c.vm_count}</div>
                    <div style={{ color: "#6b7280" }}>VMs</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{c.total_vcpu}</div>
                    <div style={{ color: "#6b7280" }}>vCPU</div>
                  </div>
                </div>

                {/* Phase 3.0 — enhanced stats row */}
                {memberScores.length > 0 && (
                  <div style={{ fontSize: "0.75rem", background: "var(--bg, #f9fafb)", borderRadius: 6,
                    padding: "6px 10px", marginBottom: 8, display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 4 }}>
                    <div>
                      <div style={{ color: "#6b7280", marginBottom: 2 }}>Avg Ease</div>
                      <div style={{ fontWeight: 700,
                        color: avgEase! < 30 ? "#15803d" : avgEase! < 60 ? "#854d0e" : "#dc2626" }}>
                        {avgEase!.toFixed(0)}
                        <span style={{ fontWeight: 400, color: "#9ca3af", marginLeft: 2 }}>/ 100</span>
                      </div>
                    </div>
                    <div>
                      <div style={{ color: "#6b7280", marginBottom: 2 }}>Total Disk</div>
                      <div style={{ fontWeight: 700 }}>{totalDiskGb > 1024 ? (totalDiskGb / 1024).toFixed(1) + " TB" : totalDiskGb.toFixed(0) + " GB"}</div>
                    </div>
                    <div>
                      <div style={{ color: "#6b7280", marginBottom: 2 }}>Avg Risk</div>
                      <div style={{ fontWeight: 700,
                        color: (avgRisk ?? 0) > 70 ? "#dc2626" : (avgRisk ?? 0) > 40 ? "#854d0e" : "#15803d" }}>
                        {avgRisk ? avgRisk.toFixed(0) : "—"}%
                      </div>
                    </div>
                    {/* Mini difficulty bar */}
                    {memberScores.length > 0 && (
                      <div style={{ gridColumn: "1 / -1", marginTop: 4 }}>
                        <div style={{ display: "flex", height: 6, borderRadius: 3, overflow: "hidden", gap: 1 }}>
                          {easyCount > 0 && <div style={{ flex: easyCount, background: "#86efac" }} title={`${easyCount} easy`} />}
                          {medCount  > 0 && <div style={{ flex: medCount,  background: "#fde68a" }} title={`${medCount} medium`} />}
                          {hardCount > 0 && <div style={{ flex: hardCount, background: "#fca5a5" }} title={`${hardCount} hard`} />}
                        </div>
                        <div style={{ display: "flex", gap: 8, marginTop: 2, color: "#9ca3af" }}>
                          {easyCount > 0 && <span style={{ color: "#15803d" }}>●{easyCount} easy</span>}
                          {medCount  > 0 && <span style={{ color: "#854d0e" }}>●{medCount} med</span>}
                          {hardCount > 0 && <span style={{ color: "#dc2626" }}>●{hardCount} hard</span>}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {(c.scheduled_start || c.scheduled_end) && (
                  <div style={{ fontSize: "0.78rem", color: "#6b7280", marginBottom: 8 }}>
                    📅 {c.scheduled_start || "?"} → {c.scheduled_end || "?"}
                  </div>
                )}
                {(c.schedule_duration_days || c.target_vms_per_day) && (
                  <div style={{ fontSize: "0.78rem", color: "#6b7280", marginBottom: 8 }}>
                    {c.schedule_duration_days && <span>⏱ {c.schedule_duration_days} days</span>}
                    {c.schedule_duration_days && c.target_vms_per_day && <span style={{ margin: "0 4px" }}>·</span>}
                    {c.target_vms_per_day && <span>⚡ {c.target_vms_per_day} VMs/day</span>}
                  </div>
                )}

                {/* Expandable tenant list with reassignment */}
                {members.length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    <button onClick={() => setExpandedCohort(expandedCohort === c.id ? null : c.id)}
                      style={{ ...btnSmall, color: "#2563eb", background: "none", border: "none",
                        padding: "2px 0", fontWeight: 500, cursor: "pointer", fontSize: "0.78rem" }}>
                      {expandedCohort === c.id ? "▴" : "▾"} {members.length} Tenant{members.length !== 1 ? "s" : ""}
                    </button>
                    {expandedCohort === c.id && (
                      <div style={{ maxHeight: 200, overflowY: "auto", marginTop: 4, border: "1px solid #e5e7eb",
                        borderRadius: 6, background: "var(--bg, #f9fafb)" }}>
                        <table style={{ width: "100%", fontSize: "0.75rem", borderCollapse: "collapse" }}>
                          <thead>
                            <tr style={{ background: "#eff6ff" }}>
                              <th style={{ padding: "3px 8px", textAlign: "left", fontWeight: 600, color: "#1e40af" }}>Tenant</th>
                              <th style={{ padding: "3px 8px", textAlign: "center", fontWeight: 600, color: "#1e40af" }}>Ease</th>
                              <th style={{ padding: "3px 8px", textAlign: "right", fontWeight: 600, color: "#1e40af" }}>Move to</th>
                            </tr>
                          </thead>
                          <tbody>
                            {members.map(t => {
                              const sc = cohortEaseScores[t.id];
                              const ease = sc?.ease_score ?? null;
                              return (
                                <tr key={t.id} style={{ borderTop: "1px solid #e5e7eb" }}>
                                  <td style={{ padding: "3px 8px", maxWidth: 140, overflow: "hidden",
                                    textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                                    title={t.tenant_name}>{t.tenant_name}</td>
                                  <td style={{ padding: "3px 8px", textAlign: "center" }}>
                                    {ease !== null ? (
                                      <span style={{
                                        background: ease < 30 ? "#dcfce7" : ease < 60 ? "#fef9c3" : "#fee2e2",
                                        color:      ease < 30 ? "#15803d" : ease < 60 ? "#854d0e" : "#dc2626",
                                        padding: "1px 6px", borderRadius: 10, fontWeight: 600
                                      }}>{ease.toFixed(0)}</span>
                                    ) : "—"}
                                  </td>
                                  <td style={{ padding: "3px 8px", textAlign: "right" }}>
                                    {reassigning[t.id] ? (
                                      <span style={{ color: "#6b7280" }}>Moving…</span>
                                    ) : (
                                      <select
                                        value=""
                                        onChange={async e => {
                                          const targetId = Number(e.target.value);
                                          if (!targetId) return;
                                          setReassigning(r => ({ ...r, [t.id]: true }));
                                          try {
                                            await apiFetch(`/api/migration/projects/${projectId}/cohorts/${targetId}/assign-tenants`, {
                                              method: "POST", headers: { "Content-Type": "application/json" },
                                              body: JSON.stringify({ tenant_ids: [t.id] })
                                            });
                                            loadCohorts();
                                            if (onRefreshTenants) onRefreshTenants();
                                          } catch (_) {}
                                          setReassigning(r => ({ ...r, [t.id]: false }));
                                        }}
                                        style={{ fontSize: "0.72rem", padding: "1px 4px", borderRadius: 4,
                                          border: "1px solid #d1d5db", cursor: "pointer", maxWidth: 110 }}>
                                        <option value="">Move…</option>
                                        {cohorts.filter(x => x.id !== c.id).map(x => (
                                          <option key={x.id} value={x.id}>{x.cohort_order}. {x.name}</option>
                                        ))}
                                      </select>
                                    )}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}

                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <button onClick={() => setSelectedCohort(selectedCohort === c.id ? null : c.id)}
                    style={{ ...btnSmall, background: selectedCohort === c.id ? "#2563eb" : "#e5e7eb",
                      color: selectedCohort === c.id ? "#fff" : undefined }}>
                    {selectedCohort === c.id ? "✓ Selected" : "Select for Assignment"}
                  </button>
                  <button onClick={() => deleteCohort(c.id)}
                    style={{ ...btnSmall, color: "#dc2626" }} title="Delete cohort">🗑</button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ⸺ What-if estimator ⸺ */}
      {cohorts.length > 0 && Object.keys(cohortEaseScores).length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <button onClick={() => setShowWhatIf(v => !v)}
            style={{ ...btnSecondary, fontSize: "0.82rem", background: showWhatIf ? "#f5f3ff" : undefined, color: showWhatIf ? "#7c3aed" : undefined }}>
            🔮 What-If Estimator {showWhatIf ? "▲" : "▼"}
          </button>
          {showWhatIf && (
            <div style={{ ...sectionStyle, marginTop: 8, background: "#faf5ff", borderColor: "#e9d5ff" }}>
              <div style={{ fontWeight: 700, marginBottom: 12, color: "#7c3aed", fontSize: "0.9rem" }}>🔮 Migration Time Estimator</div>
              <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginBottom: 14, alignItems: "flex-end" }}>
                <div>
                  <label style={{ ...labelStyle, color: "#7c3aed" }}>
                    Bandwidth (Mbps)
                    <span title="Total available network bandwidth between source and target. Used to estimate data transfer time. Effective throughput is ~75% of this (protocol & network overhead). Increase for faster links (10 GbE = 10000 Mbps, 100 GbE = 100000 Mbps)."
                      style={{ cursor: "help", color: "#9ca3af", fontSize: "0.72rem", marginLeft: 4 }}>ⓘ</span>
                  </label>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <input type="range" min={100} max={100000} step={100} value={bandwidthMbps}
                      onChange={e => setBandwidthMbps(Number(e.target.value))}
                      style={{ display: "block", width: 200 }} />
                    <input type="number" min={100} max={400000} step={100} value={bandwidthMbps}
                      onChange={e => setBandwidthMbps(Math.max(100, Number(e.target.value)))}
                      style={{ ...inputStyle, width: 90, marginBottom: 0, fontSize: "0.78rem" }} />
                    <span style={{ fontSize: "0.78rem", color: "#7c3aed", minWidth: 60 }}>
                      {bandwidthMbps >= 1000 ? (bandwidthMbps / 1000).toFixed(bandwidthMbps % 1000 === 0 ? 0 : 1) + " Gbps" : bandwidthMbps + " Mbps"}
                    </span>
                  </div>
                </div>
                <div>
                  <label style={{ ...labelStyle, color: "#7c3aed" }}>
                    Parallel Agent Slots
                    <span title="Number of PF9 migration agents running concurrently. Each agent handles one tenant at a time. More agents = more tenants migrating in parallel, reducing total wall-clock time. Does NOT increase network bandwidth — all agents share the same pipe."
                      style={{ cursor: "help", color: "#9ca3af", fontSize: "0.72rem", marginLeft: 4 }}>ⓘ</span>
                  </label>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <input type="range" min={1} max={32} step={1} value={agentSlots}
                      onChange={e => setAgentSlots(Number(e.target.value))}
                      style={{ display: "block", width: 120 }} />
                    <span style={{ fontSize: "0.78rem", color: "#7c3aed" }}>{agentSlots} slot{agentSlots !== 1 ? "s" : ""}</span>
                  </div>
                </div>
              </div>
              {(() => {
                // --- VM-slots / schedule model (mirrors the project engine) ---
                // This is what produced the original "30 days" estimate in the Migration Plan.
                // Based on: how many VMs can flow through concurrent agent slots per working day.
                const workHours = project.working_hours_per_day || 8;
                const configuredDays = project.migration_duration_days || 0;
                const concSlots = (project.agent_count || 2) * (project.agent_concurrent_vms || 5);
                const avgVmH = 2; // rough average hours per VM migration cycle
                const derivedVmsPerDay = concSlots * (workHours / avgVmH);
                const effectiveVmsPerDay = (project.target_vms_per_day || 0) > 0
                  ? (project.target_vms_per_day as number) : derivedVmsPerDay;

                let totalBwDays = 0;
                let totalSchedDays = 0;

                const rows = cohorts.map(c => {
                  const members = tenants.filter(t => t.cohort_id === c.id);
                  const memberScores2 = members.map(t => cohortEaseScores[t.id]).filter(Boolean);
                  const diskGb = memberScores2.reduce((s, e) => s + (e.total_used_gb || 0), 0);

                  // Bandwidth model
                  const effMbps = bandwidthMbps * 0.75;
                  const rawTransferH = diskGb > 0 && effMbps > 0
                    ? (diskGb * 1024 * 8) / (effMbps * 3_600) : 0;
                  const transferH = rawTransferH * 1.14;
                  const cutoverH = members.length > 0 ? (members.length * 0.25) / Math.max(agentSlots, 1) : 0;
                  const totalH = transferH + cutoverH;
                  const bwDays = totalH / workHours;

                  // VM-slots/schedule model (cohorts run sequentially)
                  const schedDays = c.vm_count > 0 && effectiveVmsPerDay > 0
                    ? c.vm_count / effectiveVmsPerDay : 0;

                  totalBwDays += bwDays;
                  totalSchedDays += schedDays;
                  return { c, members, diskGb, transferH, cutoverH, totalH, bwDays, schedDays };
                });

                return (
                  <>
                    <div style={{ overflowX: "auto" }}>
                      <table style={{ width: "100%", fontSize: "0.8rem", borderCollapse: "collapse" }}>
                        <thead>
                          <tr style={{ background: "#ede9fe" }}>
                            {([
                              { h: "Cohort",      tip: "" },
                              { h: "Tenants",     tip: "Number of tenants in this cohort" },
                              { h: "VMs",         tip: "Total VMs in this cohort" },
                              { h: "Used GB",     tip: "Total used disk (GB) across all VMs — the actual data volume to transfer" },
                              { h: "Transfer h",  tip: "Data transfer time: UsedGB × 8 bits / (BW × 75%) / 3600. All agents share the same pipe." },
                              { h: "Cutover h",   tip: "Cutover overhead: 15 min per tenant ÷ agent slots." },
                              { h: "Total h",     tip: "Transfer (×1.14 live re-sync) + cutover hours." },
                              { h: "BW Days",     tip: `Bandwidth model: Total h ÷ ${workHours}h working day. ${bandwidthMbps >= 1000 ? (bandwidthMbps/1000).toFixed(1)+"Gbps" : bandwidthMbps+"Mbps"} link, 75% efficiency.` },
                              { h: "Sched. Days", tip: `VM-slots model: cohort VMs ÷ ${effectiveVmsPerDay.toFixed(0)} VMs/day. ` +
                                ((project.target_vms_per_day || 0) > 0
                                  ? `Project configured to ${project.target_vms_per_day} VMs/day.`
                                  : `Derived from ${project.agent_count} agents × ${project.agent_concurrent_vms} concurrent × ${workHours}h/day ÷ ${avgVmH}h/VM. This is what the Migration Plan engine uses.`) },
                            ] as {h:string; tip:string}[]).map(({ h, tip }) => (
                              <th key={h} style={{ padding: "4px 10px", fontWeight: 600, color: "#4c1d95",
                                textAlign: h === "Cohort" ? "left" : "right", borderBottom: "1px solid #ddd6fe" }}>
                                {h}{tip && <span title={tip} style={{ cursor: "help", color: "#a78bfa", marginLeft: 3, fontWeight: 400 }}>ⓘ</span>}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map(({ c, diskGb, transferH, cutoverH, totalH, bwDays, schedDays }) => (
                            <tr key={c.id} style={{ borderBottom: "1px solid #e5e7eb" }}>
                              <td style={{ padding: "4px 10px", fontWeight: 600 }}>{c.cohort_order}. {c.name}</td>
                              <td style={{ padding: "4px 10px", textAlign: "right" }}>{c.tenant_count}</td>
                              <td style={{ padding: "4px 10px", textAlign: "right" }}>{c.vm_count}</td>
                              <td style={{ padding: "4px 10px", textAlign: "right" }}>{diskGb > 0 ? diskGb.toFixed(0) : "—"}</td>
                              <td style={{ padding: "4px 10px", textAlign: "right", color: "#6b7280" }}>
                                {transferH > 0 ? transferH.toFixed(1) : "—"}
                              </td>
                              <td style={{ padding: "4px 10px", textAlign: "right", color: "#6b7280" }}>
                                {cutoverH > 0 ? cutoverH.toFixed(1) : "—"}
                              </td>
                              <td style={{ padding: "4px 10px", textAlign: "right",
                                color: totalH > 48 ? "#dc2626" : totalH > 16 ? "#d97706" : "#15803d", fontWeight: 700 }}>
                                {totalH > 0 ? totalH.toFixed(1) : "—"}
                              </td>
                              <td style={{ padding: "4px 10px", textAlign: "right",
                                color: bwDays > (configuredDays || 9999) ? "#dc2626" : bwDays > 14 ? "#d97706" : "#15803d" }}>
                                {bwDays > 0 ? bwDays.toFixed(1) : "—"}
                              </td>
                              <td style={{ padding: "4px 10px", textAlign: "right",
                                color: schedDays > (configuredDays || 9999) ? "#dc2626" : schedDays > 14 ? "#d97706" : "#15803d", fontWeight: 600 }}>
                                {schedDays > 0 ? schedDays.toFixed(1) : "—"}
                              </td>
                            </tr>
                          ))}
                          {/* Totals row */}
                          <tr style={{ borderTop: "2px solid #ddd6fe", background: "#f5f3ff", fontWeight: 700 }}>
                            <td style={{ padding: "4px 10px" }} colSpan={7}>Total (sequential)</td>
                            <td style={{ padding: "4px 10px", textAlign: "right",
                              color: configuredDays > 0 && totalBwDays > configuredDays ? "#dc2626" : "#15803d" }}>
                              {totalBwDays.toFixed(1)}
                            </td>
                            <td style={{ padding: "4px 10px", textAlign: "right",
                              color: configuredDays > 0 && totalSchedDays > configuredDays ? "#dc2626" : "#15803d" }}>
                              {totalSchedDays.toFixed(1)}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>

                    {/* Project deadline check */}
                    {configuredDays > 0 && (
                      <div style={{ marginTop: 8, padding: "6px 10px", borderRadius: 6, fontSize: "0.78rem",
                        background: (totalBwDays > configuredDays || totalSchedDays > configuredDays) ? "#fef2f2" : "#f0fdf4",
                        border: `1px solid ${(totalBwDays > configuredDays || totalSchedDays > configuredDays) ? "#fca5a5" : "#86efac"}`,
                        color: (totalBwDays > configuredDays || totalSchedDays > configuredDays) ? "#dc2626" : "#15803d" }}>
                        {(totalBwDays > configuredDays || totalSchedDays > configuredDays) ? "⚠️" : "✅"}
                        {" "}Project deadline: <strong>{configuredDays} days</strong>
                        {" · "}{totalSchedDays > configuredDays
                          ? `Sched. model needs ${totalSchedDays.toFixed(1)} days — ${(totalSchedDays - configuredDays).toFixed(1)} days over budget.`
                          : `Sched. model fits (${totalSchedDays.toFixed(1)} days).`}
                        {" · "}{totalBwDays > configuredDays
                          ? `BW model needs ${totalBwDays.toFixed(1)} days — ${(totalBwDays - configuredDays).toFixed(1)} days over budget.`
                          : `BW model fits (${totalBwDays.toFixed(1)} days).`}
                      </div>
                    )}

                    <div style={{ marginTop: 6, fontSize: "0.72rem", color: "#9ca3af" }}>
                      <strong>BW Days</strong> = bandwidth/transfer model ({bandwidthMbps >= 1000 ? (bandwidthMbps/1000).toFixed(1)+"Gbps" : bandwidthMbps+"Mbps"} link, 75% effective, {workHours}h/day).
                      {" "}<strong>Sched. Days</strong> = VM-slots model ({effectiveVmsPerDay.toFixed(0)} VMs/day via {project.agent_count} agents × {project.agent_concurrent_vms} concurrent{(project.target_vms_per_day||0)>0 ? " [configured]" : " [derived]"}).
                      {" "}Use the higher of the two — that's your real bottleneck.
                      {configuredDays > 0 && ` Project configured for ${configuredDays} days.`}
                    </div>
                  </>
                );
              })()}
            </div>
          )}
        </div>
      )}

      {/* Tenant assignment panel */}
      {unassignedTenants.length > 0 && (
        <div style={sectionStyle}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
            <h4 style={{ margin: 0 }}>Unassigned Tenants ({unassignedTenants.length})</h4>
            {selectedCohort !== null && selectedTenants.size > 0 && (
              <button onClick={assignTenants} disabled={assigning}
                style={{ ...btnPrimary, marginLeft: "auto" }}>
                {assigning ? "..." : `Assign ${selectedTenants.size} tenant${selectedTenants.size !== 1 ? "s" : ""} → Cohort ${cohorts.find(c => c.id === selectedCohort)?.cohort_order}`}
              </button>
            )}
            {selectedCohort === null && (
              <span style={{ marginLeft: "auto", fontSize: "0.8rem", color: "#9ca3af" }}>
                Select a cohort card above to enable assignment
              </span>
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {unassignedTenants.map(t => (
              <div key={t.id}
                onClick={() => {
                  if (selectedCohort === null) return;
                  setSelectedTenants(prev => {
                    const n = new Set(prev);
                    n.has(t.id) ? n.delete(t.id) : n.add(t.id);
                    return n;
                  });
                }}
                style={{
                  padding: "6px 12px", borderRadius: 6,
                  border: "1px solid",
                  borderColor: selectedTenants.has(t.id) ? "#2563eb" : "var(--border, #e5e7eb)",
                  background: selectedTenants.has(t.id) ? "#eff6ff" : "var(--card-bg, #ffffff)",
                  cursor: selectedCohort !== null ? "pointer" : "default",
                  fontSize: "0.82rem",
                  userSelect: "none",
                }}>
                <span style={{ fontWeight: 600 }}>{t.tenant_name}</span>
                <span style={{ color: "#9ca3af", marginLeft: 6 }}>{t.vm_count} VMs</span>
                {(t.migration_priority ?? 999) < 999 && (
                  <span style={{ color: "#1d4ed8", marginLeft: 4 }}>P{t.migration_priority}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


/* ================================================================== */
/*  Wave Planner View  (Phase 3)                                      */
/* ================================================================== */

const WAVE_STATUS_COLORS: Record<string, string> = {
  planned:           "#6b7280",
  pre_checks_passed: "#3b82f6",
  executing:         "#f59e0b",
  validating:        "#8b5cf6",
  complete:          "#22c55e",
  failed:            "#ef4444",
  cancelled:         "#d1d5db",
};

const WAVE_STATUS_LABELS: Record<string, string> = {
  planned:           "📋 Planned",
  pre_checks_passed: "✅ Pre-checks Passed",
  executing:         "🚀 Executing",
  validating:        "🔍 Validating",
  complete:          "✅ Complete",
  failed:            "❌ Failed",
  cancelled:         "🚫 Cancelled",
};

const WAVE_STATUS_NEXT: Record<string, string[]> = {
  planned:           ["pre_checks_passed", "cancelled"],
  pre_checks_passed: ["executing", "planned"],
  executing:         ["validating", "failed"],
  validating:        ["complete", "failed"],
  complete:          [],
  failed:            ["planned"],
  cancelled:         ["planned"],
};

const PREFLIGHT_STATUS_ICONS: Record<string, string> = {
  pending: "⏳", pass: "✅", fail: "❌", skipped: "⏭️", na: "—",
};

function WavePlannerView({ projectId, project, tenants }: {
  projectId: number;
  project: MigrationProject;
  tenants: Tenant[];
}) {
  const [waves, setWaves] = useState<Wave[]>([]);
  const [funnel, setFunnel] = useState<MigrationFunnel | null>(null);
  const [cohorts, setCohorts] = useState<any[]>([]);
  const [selectedCohortId, setSelectedCohortId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expandedWave, setExpandedWave] = useState<number | null>(null);
  const [expandedPreflights, setExpandedPreflights] = useState<number | null>(null);
  const [preflights, setPreflights] = useState<Record<number, WavePreflight[]>>({});
  const [loadingPreflights, setLoadingPreflights] = useState<Record<number, boolean>>({});
  const [showAutoPanel, setShowAutoPanel] = useState(false);
  const [autoStrategy, setAutoStrategy] = useState("pilot_first");
  const [autoMaxVms, setAutoMaxVms] = useState(30);
  const [autoPilotCount, setAutoPilotCount] = useState(5);
  const [autoPrefix, setAutoPrefix] = useState("Wave");
  const [autoDryRun, setAutoDryRun] = useState(true);
  const [autoPreview, setAutoPreview] = useState<any>(null);
  const [loadingAuto, setLoadingAuto] = useState(false);
  const [advancingWave, setAdvancingWave] = useState<number | null>(null);
  const [deletingWave, setDeletingWave] = useState<number | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [wavesData, funnelData, cohortsData] = await Promise.all([
        apiFetch<any>(`/api/migration/projects/${projectId}/waves${selectedCohortId ? `?cohort_id=${selectedCohortId}` : ""}`),
        apiFetch<any>(`/api/migration/projects/${projectId}/migration-funnel`),
        apiFetch<any>(`/api/migration/projects/${projectId}/cohorts`),
      ]);
      setWaves(wavesData.waves || []);
      setFunnel(funnelData.funnel || null);
      setCohorts(cohortsData.cohorts || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [projectId, selectedCohortId]);

  useEffect(() => { loadData(); }, [loadData]);

  const loadPreflights = async (waveId: number) => {
    if (preflights[waveId]) { setExpandedPreflights(expandedPreflights === waveId ? null : waveId); return; }
    setLoadingPreflights(p => ({ ...p, [waveId]: true }));
    try {
      const data = await apiFetch<any>(`/api/migration/projects/${projectId}/waves/${waveId}/preflights`);
      setPreflights(p => ({ ...p, [waveId]: data.checks || [] }));
      setExpandedPreflights(waveId);
    } catch (e: any) { setError(e.message); }
    finally { setLoadingPreflights(p => ({ ...p, [waveId]: false })); }
  };

  const updatePreflight = async (waveId: number, checkName: string, status: string) => {
    try {
      await apiFetch(`/api/migration/projects/${projectId}/waves/${waveId}/preflights/${checkName}`,
        { method: "PATCH", body: JSON.stringify({ check_status: status }) });
      setPreflights(p => ({
        ...p,
        [waveId]: (p[waveId] || []).map(c =>
          c.check_name === checkName ? { ...c, check_status: status as any } : c
        )
      }));
    } catch (e: any) { setError(e.message); }
  };

  const advanceWave = async (waveId: number, toStatus: string) => {
    setAdvancingWave(waveId);
    try {
      await apiFetch(`/api/migration/projects/${projectId}/waves/${waveId}/advance`,
        { method: "POST", body: JSON.stringify({ status: toStatus }) });
      await loadData();
    } catch (e: any) { setError(e.message); }
    finally { setAdvancingWave(null); }
  };

  const deleteWave = async (waveId: number) => {
    if (!window.confirm("Delete this wave? All VM assignments in this wave will be removed.")) return;
    setDeletingWave(waveId);
    try {
      await apiFetch(`/api/migration/projects/${projectId}/waves/${waveId}`, { method: "DELETE" });
      await loadData();
    } catch (e: any) { setError(e.message); }
    finally { setDeletingWave(null); }
  };

  const runAutoWaves = async (dryRun: boolean) => {
    setLoadingAuto(true);
    setError("");
    try {
      const data = await apiFetch<any>(`/api/migration/projects/${projectId}/auto-waves`, {
        method: "POST",
        body: JSON.stringify({
          strategy: autoStrategy,
          cohort_id: selectedCohortId ?? null,
          max_vms_per_wave: autoMaxVms,
          pilot_vm_count: autoPilotCount,
          wave_name_prefix: autoPrefix,
          dry_run: dryRun,
        }),
      });
      if (dryRun) {
        setAutoPreview(data);
      } else {
        setAutoPreview(null);
        setShowAutoPanel(false);
        await loadData();
      }
    } catch (e: any) { setError(e.message); }
    finally { setLoadingAuto(false); }
  };

  const totalVms = funnel?.total ?? 0;
  const migratedVms = funnel?.migrated ?? 0;
  const assignedVms = funnel?.assigned ?? 0;
  const failedVms = funnel?.failed ?? 0;
  const notStartedVms = funnel?.not_started ?? 0;

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>🌊 Migration Wave Planner</h3>

      {/* ---- Migration Funnel ---- */}
      {funnel && totalVms > 0 && (
        <div style={{ ...sectionStyle, marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontWeight: 600, fontSize: "0.9rem" }}>📊 VM Migration Progress</span>
            {[
              { label: "Not Started", value: notStartedVms, color: "#9ca3af" },
              { label: "Assigned", value: assignedVms, color: "#3b82f6" },
              { label: "In Progress", value: funnel.in_progress ?? 0, color: "#f59e0b" },
              { label: "Migrated", value: migratedVms, color: "#22c55e" },
              { label: "Failed", value: failedVms, color: "#ef4444" },
              { label: "Skipped", value: funnel.skipped ?? 0, color: "#d1d5db" },
            ].map(({ label, value, color }) => value > 0 ? (
              <div key={label} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.85rem" }}>
                <div style={{ width: 12, height: 12, borderRadius: 3, background: color }} />
                <span>{label}: <strong>{value}</strong></span>
              </div>
            ) : null)}
            <span style={{ marginLeft: "auto", fontSize: "0.85rem", color: "#6b7280" }}>
              {totalVms > 0 ? `${Math.round(migratedVms / totalVms * 100)}% migrated` : "0%"}
            </span>
          </div>
          {/* Progress bar */}
          <div style={{ marginTop: 8, height: 8, borderRadius: 4, background: "#f3f4f6", overflow: "hidden", display: "flex" }}>
            {[
              { value: migratedVms, color: "#22c55e" },
              { value: funnel.in_progress ?? 0, color: "#f59e0b" },
              { value: assignedVms, color: "#3b82f6" },
              { value: failedVms, color: "#ef4444" },
            ].map(({ value, color }, i) => (
              <div key={i} style={{ width: `${(value / Math.max(totalVms, 1)) * 100}%`, background: color, height: "100%" }} />
            ))}
          </div>
        </div>
      )}

      {error && <div style={alertError}>{error}</div>}

      {/* ---- Toolbar ---- */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        {/* Cohort filter */}
        {cohorts.length > 0 && (
          <select value={selectedCohortId ?? ""} onChange={e => setSelectedCohortId(e.target.value ? Number(e.target.value) : null)}
            style={inputStyle}>
            <option value="">All Cohorts</option>
            {cohorts.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
        <button onClick={() => setShowAutoPanel(!showAutoPanel)} style={btnSecondary}>
          🤖 {showAutoPanel ? "Hide Auto-Build" : "Auto-Build Waves"}
        </button>
        <button onClick={loadData} disabled={loading} style={btnSecondary}>
          🔄 Refresh
        </button>
        <span style={{ marginLeft: "auto", fontSize: "0.85rem", color: "#6b7280" }}>
          {waves.length} wave{waves.length !== 1 ? "s" : ""}
          {selectedCohortId ? ` in ${cohorts.find(c => c.id === selectedCohortId)?.name ?? "cohort"}` : ""}
        </span>
      </div>

      {/* ---- Auto-Build Panel ---- */}
      {showAutoPanel && (
        <div style={{ ...sectionStyle, marginBottom: 16, background: "#f8fafc", border: "1px solid #cbd5e1" }}>
          <h4 style={{ marginTop: 0 }}>🤖 Auto-Build Wave Plan</h4>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 12, marginBottom: 12 }}>
            <div>
              <label style={{ display: "block", fontSize: "0.82rem", fontWeight: 600, marginBottom: 4 }}>
                Strategy
              </label>
              <select value={autoStrategy} onChange={e => { setAutoStrategy(e.target.value); setAutoPreview(null); }} style={inputStyle}>
                <option value="pilot_first">🧪 Pilot First — safest VMs in Wave 0</option>
                <option value="by_tenant">🏢 By Tenant — one wave per tenant</option>
                <option value="by_risk">🎯 By Risk — green → yellow → red</option>
                <option value="by_priority">🔢 By Priority — tenant migration priority</option>
                <option value="balanced">⚖️ Balanced — equal disk per wave</option>
              </select>
              <p style={{ fontSize: "0.75rem", color: "#6b7280", margin: "4px 0 0" }}>
                {autoStrategy === "pilot_first" && "Creates a small pilot wave with the safest/smallest VMs to validate the toolchain first."}
                {autoStrategy === "by_tenant" && "One wave per tenant (sorted by migration priority). Large tenants are split if they exceed the VM cap."}
                {autoStrategy === "by_risk" && "Groups VMs by risk band: Green (low risk) → Yellow → Red. Validates on safe VMs before attempting risky ones."}
                {autoStrategy === "by_priority" && "Fills waves in tenant priority order (lower number = earlier). Same priority tenants are spread evenly."}
                {autoStrategy === "balanced" && "Distributes VMs to minimise variance in total disk GB per wave so each wave takes roughly equal time."}
              </p>
            </div>
            <div>
              <label style={{ display: "block", fontSize: "0.82rem", fontWeight: 600, marginBottom: 4 }}>
                Max VMs per Wave &nbsp;<span style={{ fontWeight: 400, color: "#6b7280" }}>({autoMaxVms})</span>
              </label>
              <input type="range" min={5} max={100} value={autoMaxVms}
                onChange={e => { setAutoMaxVms(Number(e.target.value)); setAutoPreview(null); }}
                style={{ width: "100%" }} />
            </div>
            {autoStrategy === "pilot_first" && (
              <div>
                <label style={{ display: "block", fontSize: "0.82rem", fontWeight: 600, marginBottom: 4 }}>
                  Pilot VM Count &nbsp;<span style={{ fontWeight: 400, color: "#6b7280" }}>({autoPilotCount})</span>
                </label>
                <input type="range" min={1} max={20} value={autoPilotCount}
                  onChange={e => { setAutoPilotCount(Number(e.target.value)); setAutoPreview(null); }}
                  style={{ width: "100%" }} />
              </div>
            )}
            <div>
              <label style={{ display: "block", fontSize: "0.82rem", fontWeight: 600, marginBottom: 4 }}>Wave Name Prefix</label>
              <input value={autoPrefix} onChange={e => setAutoPrefix(e.target.value)} style={inputStyle} />
            </div>
          </div>

          {/* Preview table */}
          {autoPreview && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 8, fontSize: "0.9rem" }}>
                Preview — {autoPreview.waves?.length ?? 0} waves
                {(autoPreview.cohort_count ?? 0) > 1 && (
                  <span style={{ marginLeft: 8, background: "#dbeafe", color: "#1d4ed8",
                    padding: "2px 7px", borderRadius: 10, fontSize: "0.76rem", fontWeight: 600 }}>
                    📦 {autoPreview.cohort_count} cohorts
                  </span>
                )}
                {autoPreview.warnings?.length > 0 && (
                  <span style={{ color: "#d97706", marginLeft: 8, fontSize: "0.82rem" }}>
                    ⚠️ {autoPreview.warnings.length} warning{autoPreview.warnings.length > 1 ? "s" : ""}
                  </span>
                )}
              </div>
              {autoPreview.unassigned_vm_ids?.length > 0 && (
                <div style={{ fontSize: "0.78rem", color: "#b45309", marginBottom: 6 }}>
                  ⚠️ {autoPreview.unassigned_vm_ids.length} VM{autoPreview.unassigned_vm_ids.length > 1 ? "s" : ""} could not be assigned to any wave.
                </div>
              )}
              <table style={tableStyle}>
                <thead>
                  <tr>
                    <th style={thStyleSm}>#</th>
                    <th style={thStyleSm}>Name</th>
                    {(autoPreview.cohort_count ?? 0) > 1 && <th style={thStyleSm}>Cohort</th>}
                    <th style={thStyleSm}>Type</th>
                    <th style={thStyleSm}>VMs</th>
                    <th style={thStyleSm}>Disk (GB)</th>
                    <th style={thStyleSm}>Risk</th>
                    <th style={thStyleSm}>Tenants</th>
                  </tr>
                </thead>
                <tbody>
                  {(autoPreview.waves || []).map((w: any) => (
                    <tr key={w.wave_number}>
                      <td style={tdStyleSm}>{w.wave_number}</td>
                      <td style={tdStyleSm}>{w.name}</td>
                      {(autoPreview.cohort_count ?? 0) > 1 && (
                        <td style={tdStyleSm}>
                          {w.cohort_name
                            ? <span style={{ fontSize: "0.75rem", background: "#f0f9ff", color: "#0369a1",
                                padding: "2px 5px", borderRadius: 6 }}>{w.cohort_name}</span>
                            : <span style={{ color: "#9ca3af" }}>—</span>}
                        </td>
                      )}
                      <td style={tdStyleSm}>
                        <span style={{ padding: "2px 6px", borderRadius: 4, fontSize: "0.75rem",
                          background: w.wave_type === "pilot" ? "#e0f2fe" : "#f0f9ff",
                          color: w.wave_type === "pilot" ? "#0369a1" : "#0284c7" }}>
                          {w.wave_type}
                        </span>
                      </td>
                      <td style={tdStyleSm}>{w.vm_count}</td>
                      <td style={tdStyleSm}>{typeof w.total_disk_gb === "number" ? w.total_disk_gb.toFixed(0) : w.total_disk_gb}</td>
                      <td style={tdStyleSm}>
                        {w.risk_distribution && (
                          <span style={{ fontSize: "0.75rem" }}>
                            {w.risk_distribution.GREEN > 0 ? `🟢${w.risk_distribution.GREEN} ` : ""}
                            {w.risk_distribution.YELLOW > 0 ? `🟡${w.risk_distribution.YELLOW} ` : ""}
                            {w.risk_distribution.RED > 0 ? `🔴${w.risk_distribution.RED}` : ""}
                          </span>
                        )}
                      </td>
                      <td style={tdStyleSm}>{w.tenant_names?.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {autoPreview.warnings?.length > 0 && (
                <ul style={{ margin: "8px 0 0", padding: "0 0 0 16px", fontSize: "0.8rem", color: "#d97706" }}>
                  {autoPreview.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
                </ul>
              )}
            </div>
          )}

          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => runAutoWaves(true)} disabled={loadingAuto} style={btnSecondary}>
              {loadingAuto ? "…" : "🔍 Preview"}
            </button>
            {autoPreview && (
              <button onClick={() => runAutoWaves(false)} disabled={loadingAuto}
                style={{ ...btnPrimary, background: "#22c55e" }}>
                {loadingAuto ? "Building…" : "✅ Apply & Create Waves"}
              </button>
            )}
          </div>
        </div>
      )}

      {loading && <p style={{ color: "#6b7280" }}>Loading waves…</p>}

      {/* ---- Wave Cards ---- */}
      {!loading && waves.length === 0 && (
        <div style={{ ...sectionStyle, textAlign: "center", color: "#6b7280", padding: 32 }}>
          <p style={{ fontSize: "1.1rem", margin: "0 0 8px" }}>🌊 No waves yet</p>
          <p style={{ fontSize: "0.85rem", margin: 0 }}>
            Use <strong>Auto-Build Waves</strong> to generate a wave plan automatically, or create waves manually via the API.
          </p>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {waves.map(wave => {
          const isExpanded = expandedWave === wave.id;
          const isPreflightsExpanded = expandedPreflights === wave.id;
          const wavePreflights = preflights[wave.id] || [];
          const statusColor = WAVE_STATUS_COLORS[wave.status] ?? "#6b7280";
          const nextStatuses = WAVE_STATUS_NEXT[wave.status] ?? [];
          const passedChecks = wavePreflights.filter(c => c.check_status === "pass").length;
          const blockerFails = wavePreflights.filter(c => c.severity === "blocker" && c.check_status === "fail").length;

          return (
            <div key={wave.id} style={{
              border: `2px solid ${statusColor}30`,
              borderLeft: `4px solid ${statusColor}`,
              borderRadius: 8,
              background: "var(--bg, #fff)",
              overflow: "hidden",
            }}>
              {/* Card header */}
              <div style={{ padding: "12px 16px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                {/* Wave number badge */}
                <div style={{
                  width: 32, height: 32, borderRadius: 6, background: statusColor,
                  color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
                  fontWeight: 700, fontSize: "0.9rem", flexShrink: 0,
                }}>
                  {wave.wave_number}
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontWeight: 700, fontSize: "1rem" }}>{wave.name}</span>
                    {/* Type badge */}
                    <span style={{
                      padding: "2px 8px", borderRadius: 12, fontSize: "0.72rem", fontWeight: 600,
                      background: wave.wave_type === "pilot" ? "#dbeafe" : wave.wave_type === "cleanup" ? "#fef9c3" : "#f3f4f6",
                      color: wave.wave_type === "pilot" ? "#1d4ed8" : wave.wave_type === "cleanup" ? "#854d0e" : "#374151",
                    }}>
                      {wave.wave_type === "pilot" ? "🧪 Pilot" : wave.wave_type === "cleanup" ? "🧹 Cleanup" : "🔄 Regular"}
                    </span>
                    {/* Status badge */}
                    <span style={{
                      padding: "2px 8px", borderRadius: 12, fontSize: "0.72rem", fontWeight: 600,
                      background: `${statusColor}18`, color: statusColor,
                    }}>
                      {WAVE_STATUS_LABELS[wave.status] ?? wave.status}
                    </span>
                    {/* Cohort badge */}
                    {wave.cohort_name && (
                      <span style={{ fontSize: "0.75rem", color: "#6b7280", background: "#f3f4f6",
                        padding: "2px 6px", borderRadius: 8 }}>
                        {wave.cohort_name}
                      </span>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: 16, marginTop: 4, fontSize: "0.8rem", color: "#6b7280", flexWrap: "wrap" }}>
                    <span>{wave.vm_count} VM{wave.vm_count !== 1 ? "s" : ""}</span>
                    {wave.owner_name && <span>👤 {wave.owner_name}</span>}
                    {wave.scheduled_start && <span>📅 {wave.scheduled_start} → {wave.scheduled_end ?? "?"}</span>}
                    {wave.agent_slots_override && <span>⚡ {wave.agent_slots_override} agents</span>}
                    {wavePreflights.length > 0 && (
                      <span style={{ color: blockerFails > 0 ? "#dc2626" : passedChecks === wavePreflights.length ? "#16a34a" : "#6b7280" }}>
                        {blockerFails > 0 ? `❌ ${blockerFails} blocker` : passedChecks === wavePreflights.length ? "✅ All checks passed" : `⏳ ${passedChecks}/${wavePreflights.length} checks`}
                      </span>
                    )}
                  </div>
                </div>

                {/* Action buttons */}
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  {/* Advance status */}
                  {nextStatuses.map(ns => (
                    <button key={ns} onClick={() => advanceWave(wave.id, ns)}
                      disabled={advancingWave === wave.id}
                      style={{
                        ...btnSmall,
                        background: ns === "complete" ? "#22c55e" : ns === "executing" ? "#f59e0b" :
                          ns === "failed" || ns === "cancelled" ? "#ef4444" : "#3b82f6",
                        color: "#fff", border: "none", fontWeight: 600, fontSize: "0.75rem",
                      }}>
                      {advancingWave === wave.id ? "…" : (
                        ns === "executing" ? "▶️ Start" : ns === "complete" ? "✅ Complete" :
                        ns === "pre_checks_passed" ? "✅ Pass Checks" : ns === "validating" ? "🔍 Validate" :
                        ns === "failed" ? "❌ Fail" : ns === "cancelled" ? "🚫 Cancel" :
                        ns === "planned" ? "↩ Reopen" : ns
                      )}
                    </button>
                  ))}

                  {/* Pre-flight toggle */}
                  <button onClick={() => loadPreflights(wave.id)}
                    disabled={loadingPreflights[wave.id]}
                    style={{ ...btnSmall, fontSize: "0.75rem" }}>
                    {loadingPreflights[wave.id] ? "…" : isPreflightsExpanded ? "▴ Checks" : "▾ Checks"}
                  </button>

                  {/* VM list toggle */}
                  <button onClick={() => setExpandedWave(isExpanded ? null : wave.id)}
                    style={{ ...btnSmall, fontSize: "0.75rem" }}>
                    {isExpanded ? "▴ VMs" : `▾ VMs (${wave.vm_count})`}
                  </button>

                  {/* Delete (only planned) */}
                  {wave.status === "planned" && (
                    <button onClick={() => deleteWave(wave.id)}
                      disabled={deletingWave === wave.id}
                      style={{ ...btnSmall, color: "#ef4444", borderColor: "#ef4444", fontSize: "0.75rem" }}>
                      {deletingWave === wave.id ? "…" : "🗑️"}
                    </button>
                  )}
                </div>
              </div>

              {/* Pre-flight checklist */}
              {isPreflightsExpanded && wavePreflights.length > 0 && (
                <div style={{ borderTop: "1px solid var(--border, #e5e7eb)", padding: "12px 16px",
                  background: "#fafafa" }}>
                  <div style={{ fontWeight: 600, fontSize: "0.85rem", marginBottom: 8 }}>
                    🔍 Pre-flight Checklist
                  </div>
                  <table style={tableStyle}>
                    <thead>
                      <tr>
                        <th style={thStyleSm}>Check</th>
                        <th style={thStyleSm}>Severity</th>
                        <th style={thStyleSm}>Status</th>
                        <th style={thStyleSm}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {wavePreflights.map(c => (
                        <tr key={c.check_name} style={{ background: c.check_status === "fail" && c.severity === "blocker" ? "#fef2f2" : undefined }}>
                          <td style={tdStyleSm}>{c.check_label}</td>
                          <td style={tdStyleSm}>
                            <span style={{
                              padding: "1px 6px", borderRadius: 6, fontSize: "0.72rem",
                              background: c.severity === "blocker" ? "#fef2f2" : c.severity === "warning" ? "#fffbeb" : "#f0f9ff",
                              color: c.severity === "blocker" ? "#dc2626" : c.severity === "warning" ? "#d97706" : "#0369a1",
                            }}>
                              {c.severity}
                            </span>
                          </td>
                          <td style={tdStyleSm}>
                            {PREFLIGHT_STATUS_ICONS[c.check_status]} {c.check_status}
                          </td>
                          <td style={tdStyleSm}>
                            <div style={{ display: "flex", gap: 4 }}>
                              {c.check_status !== "pass" && (
                                <button onClick={() => updatePreflight(wave.id, c.check_name, "pass")}
                                  style={{ ...btnSmall, fontSize: "0.7rem", background: "#dcfce7", border: "1px solid #86efac", color: "#166534" }}>
                                  ✅ Pass
                                </button>
                              )}
                              {c.check_status !== "fail" && (
                                <button onClick={() => updatePreflight(wave.id, c.check_name, "fail")}
                                  style={{ ...btnSmall, fontSize: "0.7rem", background: "#fef2f2", border: "1px solid #fca5a5", color: "#dc2626" }}>
                                  ❌ Fail
                                </button>
                              )}
                              {c.check_status !== "skipped" && (
                                <button onClick={() => updatePreflight(wave.id, c.check_name, "skipped")}
                                  style={{ ...btnSmall, fontSize: "0.7rem" }}>
                                  ⏭️ Skip
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* VM list */}
              {isExpanded && (
                <div style={{ borderTop: "1px solid var(--border, #e5e7eb)", padding: "12px 16px" }}>
                  {(!wave.vms || wave.vms.length === 0) ? (
                    <p style={{ color: "#6b7280", fontSize: "0.85rem", margin: 0 }}>No VMs assigned to this wave.</p>
                  ) : (
                    <table style={tableStyle}>
                      <thead>
                        <tr>
                          <th style={thStyleSm}>VM Name</th>
                          <th style={thStyleSm}>Tenant</th>
                          <th style={thStyleSm}>Mode</th>
                          <th style={thStyleSm}>Risk</th>
                          <th style={thStyleSm}>Used (GB)</th>
                          <th style={thStyleSm}>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {wave.vms.map((v, i) => (
                          <tr key={`${wave.id}-${v.vm_name ?? i}`}>
                            <td style={tdStyleSm}>{v.vm_name}</td>
                            <td style={tdStyleSm}>{v.tenant_name}</td>
                            <td style={tdStyleSm}>
                              <span style={{ fontSize: "0.75rem", padding: "1px 5px", borderRadius: 4,
                                background: v.migration_mode?.includes("warm") ? "#dcfce7" : "#fef9c3",
                                color: v.migration_mode?.includes("warm") ? "#166534" : "#854d0e" }}>
                                {v.migration_mode?.replace("_", " ") ?? "—"}
                              </span>
                            </td>
                            <td style={tdStyleSm}>
                              <span style={{ color: v.risk_classification === "GREEN" ? "#16a34a" :
                                v.risk_classification === "RED" ? "#dc2626" : "#d97706" }}>
                                {v.risk_classification === "GREEN" ? "🟢" : v.risk_classification === "RED" ? "🔴" : "🟡"}
                                {v.risk_classification ?? "—"}
                              </span>
                            </td>
                            <td style={tdStyleSm}>{v.in_use_gb?.toFixed(1) ?? "—"}</td>
                            <td style={tdStyleSm}>
                              <span style={{ fontSize: "0.72rem", padding: "1px 5px", borderRadius: 4,
                                background: v.wave_vm_status === "complete" ? "#dcfce7" :
                                  v.wave_vm_status === "failed" ? "#fef2f2" : "#f3f4f6",
                                color: v.wave_vm_status === "complete" ? "#166534" :
                                  v.wave_vm_status === "failed" ? "#dc2626" : "#374151" }}>
                                {v.wave_vm_status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}


/* ================================================================== */
/*  Migration Plan View                                               */
/* ================================================================== */

function MigrationPlanView({ projectId, projectName }: { projectId: number; projectName: string }) {
  const [plan, setPlan] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expandedTenant, setExpandedTenant] = useState<string | null>(null);

  const loadPlan = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch<any>(`/api/migration/projects/${projectId}/export-plan`);
      setPlan(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { loadPlan(); }, [loadPlan]);

  const downloadJson = () => {
    if (!plan) return;
    const blob = new Blob([JSON.stringify(plan, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `migration-plan-${projectName.replace(/\s+/g, "_")}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadCsv = () => {
    if (!plan?.tenant_plans) return;
    const rows: string[] = ["Tenant,OrgVDC,VM Name,vCPU,CPU %,RAM (MB),Mem %,Alloc (GB),Used (GB),OS Family,OS Version,Power,NICs,Network,Mode,Risk,Disks,IP,Warm Phase1 (h),Warm Cutover (h),Warm Downtime (h),Cold Total (h),Cold Downtime (h)"];
    for (const tp of plan.tenant_plans) {
      for (const vm of tp.vms) {
        rows.push([
          `"${tp.tenant_name}"`, `"${tp.org_vdc || ""}"`,
          `"${vm.vm_name}"`, vm.cpu_count, vm.cpu_usage_percent || "", vm.ram_mb, vm.memory_usage_percent || "",
          vm.total_disk_gb, vm.in_use_gb, `"${vm.os_family || ""}"`, `"${vm.os_version || ""}"`,
          vm.power_state, vm.nic_count || 0, `"${vm.network_name || ""}"`,
          vm.migration_mode, vm.risk_category, vm.disk_count,
          vm.primary_ip || "",
          vm.warm_phase1_hours, vm.warm_cutover_hours, vm.warm_downtime_hours,
          vm.cold_total_hours, vm.cold_downtime_hours,
        ].join(","));
      }
    }
    const blob = new Blob([rows.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `migration-plan-${projectName.replace(/\s+/g, "_")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadAuthBlob = async (apiPath: string, filename: string) => {
    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}${apiPath}`, {
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (!res.ok) { alert(`Download failed: ${res.status} ${res.statusText}`); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: any) { alert(`Download error: ${e.message}`); }
  };

  const downloadXlsx = () =>
    downloadAuthBlob(
      `/api/migration/projects/${projectId}/export-report.xlsx`,
      `migration-plan-${projectName.replace(/\s+/g, "_")}.xlsx`
    );

  const downloadPdf = () =>
    downloadAuthBlob(
      `/api/migration/projects/${projectId}/export-report.pdf`,
      `migration-plan-${projectName.replace(/\s+/g, "_")}.pdf`
    );

  if (loading) return <p style={{ color: "#6b7280" }}>Generating migration plan...</p>;
  if (error) return <div style={alertError}>{error}</div>;
  if (!plan) return <p style={{ color: "#6b7280" }}>No plan data. Run assessment first.</p>;

  const ps = plan.project_summary;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button onClick={loadPlan} style={btnSecondary}>🔄 Refresh Plan</button>
        <button onClick={downloadJson} style={btnSecondary}>📄 Export JSON</button>
        <button onClick={downloadCsv} style={btnSecondary}>📊 Export CSV</button>
        <button onClick={downloadXlsx} style={btnPrimary}>📥 Export Excel</button>
        <button onClick={downloadPdf} style={{ ...btnPrimary, background: "#7c3aed" }}>📑 Export PDF</button>
      </div>

      {/* Project summary */}
      <div style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Project Summary</h3>
        {ps.excluded_tenants > 0 && (
          <div style={{ marginBottom: 10, padding: "6px 12px", background: "#fef3c7", borderRadius: 6,
            border: "1px solid #fbbf24", fontSize: "0.85rem", color: "#92400e" }}>
            ⚠️ <strong>{ps.excluded_tenants} tenant{ps.excluded_tenants > 1 ? "s" : ""} excluded</strong> from this plan. Totals reflect included tenants only.
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
          <StatCard label="Total VMs" value={ps.total_vms} />
          <StatCard label="Total Disk (TB)" value={ps.total_disk_tb} />
          <StatCard label="Warm Eligible" value={ps.warm_eligible} />
          <StatCard label="Cold Required" value={ps.cold_required} />
          <StatCard label="Tenants (incl.)" value={ps.total_tenants} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginTop: 12 }}>
          <StatCard label="Agents" value={ps.agent_count} />
          <StatCard label="Concurrent Slots" value={ps.total_concurrent_slots} />
          <StatCard label="Schedule Days" value={ps.estimated_schedule_days} />
          <StatCard label="Total Downtime (h)" value={ps.total_downtime_hours} />
        </div>
        <div style={{ marginTop: 8, fontSize: "0.85rem", color: "#6b7280" }}>
          Bottleneck: <strong>{ps.bottleneck_mbps} Mbps</strong> · 
          Project duration: <strong>{ps.project_duration_days} days</strong> ({ps.effective_working_days} effective)
        </div>
      </div>

      {/* Cohort schedule summary */}
      {plan.cohort_schedule_summary?.length > 0 && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>📦 Cohort Execution Plan</h3>
          <p style={{ color: "#6b7280", fontSize: "0.85rem", marginTop: -8, marginBottom: 10 }}>
            Each cohort runs sequentially. The schedule below shows which calendar days
            are allocated to each wave. Total: <strong>{ps.estimated_schedule_days} working days</strong>.
          </p>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr style={{ background: "#eff6ff" }}>
                {["Cohort", "VMs", "Start Day", "End Day", "Duration (days)"].map(h => (
                  <th key={h} style={{ padding: "5px 12px", fontWeight: 600, color: "#1e40af",
                    textAlign: h === "Cohort" ? "left" : "right", borderBottom: "2px solid #93c5fd" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {plan.cohort_schedule_summary.map((cs: any) => (
                <tr key={cs.cohort_name} style={{ borderBottom: "1px solid #e5e7eb" }}>
                  <td style={{ padding: "5px 12px", fontWeight: 600 }}>
                    {cs.cohort_order != null ? `${cs.cohort_order}. ` : ""}{cs.cohort_name}
                  </td>
                  <td style={{ padding: "5px 12px", textAlign: "right" }}>{cs.vm_count}</td>
                  <td style={{ padding: "5px 12px", textAlign: "right" }}>Day {cs.start_day}</td>
                  <td style={{ padding: "5px 12px", textAlign: "right" }}>Day {cs.end_day}</td>
                  <td style={{ padding: "5px 12px", textAlign: "right", fontWeight: 600,
                    color: cs.duration_days > 14 ? "#d97706" : "#15803d" }}>
                    {cs.duration_days}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Per-tenant plans — grouped by cohort */}
      <div style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Per-Tenant Assessment</h3>
        {(() => {
          // Group tenant_plans by cohort_order (null → uncohorted at end)
          const plans: any[] = plan.tenant_plans;
          const cohortGroups: Map<string, any[]> = new Map();
          for (const tp of plans) {
            const key = tp.cohort_order != null
              ? `${String(tp.cohort_order).padStart(4, "0")}:${tp.cohort_name}`
              : "9999:Uncohorted";
            if (!cohortGroups.has(key)) cohortGroups.set(key, []);
            cohortGroups.get(key)!.push(tp);
          }
          const sortedKeys = [...cohortGroups.keys()].sort();
          const tableColSpan = 15;
          return (
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={{ ...thStyle, width: 30 }}></th>
                  <th style={thStyle}>Tenant</th>
                  <th style={thStyle}>OrgVDC</th>
                  <th style={thStyle}>VMs</th>
                  <th style={thStyle}>vCPU</th>
                  <th style={thStyle}>RAM (GB)</th>
                  <th style={thStyle}>Disk (GB)</th>
                  <th style={thStyle}>In Use (GB)</th>
                  <th style={thStyle}>Warm</th>
                  <th style={thStyle}>Warm Risky</th>
                  <th style={thStyle}>Cold</th>
                  <th style={thStyle}>Copy/Phase1 (h)</th>
                  <th style={thStyle}>Cutover (h)</th>
                  <th style={thStyle}>Downtime</th>
                  <th style={thStyle}>Risk</th>
                </tr>
              </thead>
              <tbody>
                {sortedKeys.map(key => {
                  const group = cohortGroups.get(key)!;
                  const isUncohorted = key.startsWith("9999:");
                  const labelParts = key.split(":");
                  const cohortLabel = isUncohorted
                    ? "Uncohorted Tenants"
                    : `Cohort ${parseInt(labelParts[0])}: ${labelParts.slice(1).join(":")}`;
                  // Subtotals for this cohort
                  const subtotalVMs    = group.reduce((s, tp) => s + tp.vm_count, 0);
                  const subtotalDisk   = group.reduce((s, tp) => s + Number(tp.total_disk_gb), 0);
                  const subtotalUsed   = group.reduce((s, tp) => s + Number(tp.total_in_use_gb), 0);
                  const subtotalDown   = group.reduce((s, tp) => s + Number(tp.total_downtime_hours), 0);
                  return (
                    <React.Fragment key={key}>
                      {/* Cohort header row */}
                      <tr style={{ background: isUncohorted ? "#f9fafb" : "#eff6ff", borderTop: "2px solid #93c5fd" }}>
                        <td colSpan={tableColSpan} style={{ padding: "6px 12px", fontWeight: 700,
                          color: isUncohorted ? "#9ca3af" : "#1e40af", fontSize: "0.82rem", letterSpacing: "0.02em" }}>
                          {isUncohorted ? "⚠️" : "📦"} {cohortLabel}
                          <span style={{ fontWeight: 400, color: "#6b7280", marginLeft: 8 }}>
                            {group.length} tenant{group.length !== 1 ? "s" : ""} · {subtotalVMs} VMs · {subtotalDisk.toFixed(0)} GB alloc · {subtotalUsed.toFixed(0)} GB used
                          </span>
                        </td>
                      </tr>
                      {/* Tenant rows */}
                      {group.map((tp: any) => (
                        <React.Fragment key={tp.tenant_name}>
                          <tr style={{ borderBottom: "1px solid var(--border, #e5e7eb)", cursor: "pointer" }}
                              onClick={() => setExpandedTenant(expandedTenant === tp.tenant_name ? null : tp.tenant_name)}>
                            <td style={tdStyle}>
                              <span style={{ fontSize: "0.8rem", color: "#9ca3af" }}>
                                {expandedTenant === tp.tenant_name ? "▼" : "▶"}
                              </span>
                            </td>
                            <td style={tdStyle}><strong>{tp.tenant_name}</strong></td>
                            <td style={{ ...tdStyle, fontSize: "0.8rem", color: "#6b7280" }}>{tp.org_vdc || "—"}</td>
                            <td style={tdStyle}>{tp.vm_count}</td>
                            <td style={tdStyle}>{tp.total_vcpu || 0}</td>
                            <td style={tdStyle}>{tp.total_ram_mb ? (tp.total_ram_mb / 1024).toFixed(0) : "0"}</td>
                            <td style={tdStyle}>{Number(tp.total_disk_gb).toFixed(1)}</td>
                            <td style={tdStyle}>{Number(tp.total_in_use_gb).toFixed(1)}</td>
                            <td style={tdStyle}>
                              <span style={{ ...pillStyle, background: "#dcfce7", color: "#16a34a" }}>{tp.warm_count}</span>
                            </td>
                            <td style={tdStyle}>
                              {tp.warm_risky_count > 0 && <span style={{ ...pillStyle, background: "#fef9c3", color: "#a16207" }}>{tp.warm_risky_count}</span>}
                              {!tp.warm_risky_count && "—"}
                            </td>
                            <td style={tdStyle}>
                              {tp.cold_count > 0 && <span style={{ ...pillStyle, background: "#fee2e2", color: "#dc2626" }}>{tp.cold_count}</span>}
                              {!tp.cold_count && "—"}
                            </td>
                            <td style={tdStyle}>{Number(tp.total_warm_phase1_hours).toFixed(1)}</td>
                            <td style={tdStyle}>{Number(tp.total_warm_cutover_hours + tp.total_cold_hours).toFixed(1)}</td>
                            <td style={tdStyle}><strong>{Number(tp.total_downtime_hours).toFixed(1)}h</strong></td>
                            <td style={tdStyle}>
                              <span style={{ fontSize: "0.75rem" }}>
                                {tp.risk_distribution.GREEN > 0 && <span style={{ color: "#22c55e" }}>🟢{tp.risk_distribution.GREEN} </span>}
                                {tp.risk_distribution.YELLOW > 0 && <span style={{ color: "#eab308" }}>🟡{tp.risk_distribution.YELLOW} </span>}
                                {tp.risk_distribution.RED > 0 && <span style={{ color: "#ef4444" }}>🔴{tp.risk_distribution.RED}</span>}
                              </span>
                            </td>
                          </tr>
                          {/* Expanded VM list for this tenant */}
                          {expandedTenant === tp.tenant_name && (
                            <tr>
                              <td colSpan={tableColSpan} style={{ padding: "4px 16px 12px 40px", background: "var(--card-bg, #f9fafb)" }}>
                                <table style={{ ...tableStyle, fontSize: "0.8rem" }}>
                                  <thead>
                                    <tr>
                                      <th style={thStyleSm}>VM Name</th>
                                      <th style={thStyleSm}>vCPU</th>
                                      <th style={thStyleSm}>RAM</th>
                                      <th style={thStyleSm}>Disk (GB)</th>
                                      <th style={thStyleSm}>In Use</th>
                                      <th style={thStyleSm}>OS</th>
                                      <th style={thStyleSm}>OS Ver</th>
                                      <th style={thStyleSm}>Mode</th>
                                      <th style={thStyleSm}>Risk</th>
                                      <th style={thStyleSm}>Copy / Phase 1</th>
                                      <th style={thStyleSm}>Cutover / Cold</th>
                                      <th style={thStyleSm}>Downtime</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {tp.vms.map((v: any) => (
                                      <tr key={v.vm_name} style={{ borderBottom: "1px solid #e5e7eb" }}>
                                        <td style={tdStyleSm}><strong>{v.vm_name}</strong></td>
                                        <td style={tdStyleSm}>{v.cpu_count || "—"}</td>
                                        <td style={tdStyleSm}>{v.ram_mb ? `${(v.ram_mb / 1024).toFixed(1)}G` : "—"}</td>
                                        <td style={tdStyleSm}>{Number(v.total_disk_gb).toFixed(1)}</td>
                                        <td style={tdStyleSm}>{Number(v.in_use_gb).toFixed(1)}</td>
                                        <td style={tdStyleSm}>{osIcon(v.os_family)} {v.os_family || "—"}</td>
                                        <td style={tdStyleSm}>{v.os_version || "—"}</td>
                                        <td style={tdStyleSm}>
                                          <span style={{ ...pillStyle, ...modePillColor(v.migration_mode), fontSize: "0.7rem" }}>
                                            {v.migration_mode?.replace(/_/g, " ")}
                                          </span>
                                        </td>
                                        <td style={tdStyleSm}>
                                          <span style={{ ...pillStyle, ...riskPillColor(v.risk_category), fontSize: "0.7rem" }}>
                                            {v.risk_category}
                                          </span>
                                        </td>
                                        <td style={tdStyleSm}>
                                          {(() => {
                                            const h = v.migration_mode !== "cold_required"
                                              ? Number(v.warm_phase1_hours)
                                              : Number(v.cold_total_hours);
                                            return h < 0.017 ? "<1min" : h < 1 ? `${Math.round(h * 60)}min` : `${h.toFixed(2)}h`;
                                          })()}
                                        </td>
                                        <td style={tdStyleSm}>
                                          {(() => {
                                            const h = Number(v.warm_cutover_hours);
                                            return h < 1 ? `${Math.round(h * 60)}min` : `${h.toFixed(2)}h`;
                                          })()}
                                        </td>
                                        <td style={tdStyleSm}>
                                          <strong>
                                            {(() => {
                                              const h = v.migration_mode !== "cold_required"
                                                ? Number(v.warm_cutover_hours)
                                                : Number(v.cold_downtime_hours);
                                              return h < 1 ? `${Math.round(h * 60)}min` : `${h.toFixed(2)}h`;
                                            })()}
                                          </strong>
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      ))}
                      {/* Cohort subtotal row */}
                      <tr style={{ background: isUncohorted ? "#f9fafb" : "#dbeafe",
                        borderBottom: "2px solid #93c5fd", fontSize: "0.78rem", color: "#1e40af", fontWeight: 600 }}>
                        <td colSpan={3} style={{ padding: "4px 12px", textAlign: "right", color: "#6b7280", fontWeight: 400 }}>
                          Subtotal ({group.length} tenants)
                        </td>
                        <td style={{ padding: "4px 8px", textAlign: "right" }}>{subtotalVMs}</td>
                        <td colSpan={2} style={{ padding: "4px 8px" }}></td>
                        <td style={{ padding: "4px 8px", textAlign: "right" }}>{subtotalDisk.toFixed(0)}</td>
                        <td style={{ padding: "4px 8px", textAlign: "right" }}>{subtotalUsed.toFixed(0)}</td>
                        <td colSpan={5} style={{ padding: "4px 8px" }}></td>
                        <td style={{ padding: "4px 8px", textAlign: "right" }}>{subtotalDown.toFixed(1)}h</td>
                        <td></td>
                      </tr>
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          );
        })()}
      </div>

      {/* Daily schedule */}
      {plan.daily_schedule?.length > 0 && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>Daily Migration Schedule (Estimated)</h3>
          <p style={{ color: "#6b7280", fontSize: "0.85rem", marginBottom: 12 }}>
            VMs ordered by <strong>cohort → tenant → priority → disk size</strong>. Each day fills up to {ps.total_concurrent_slots} concurrent slots.
          </p>
          <div style={{ maxHeight: 500, overflowY: "auto" }}>
            <table style={{ ...tableStyle, fontSize: "0.8rem" }}>
              <thead>
                <tr>
                  <th style={thStyleSm}>Day</th>
                  <th style={thStyleSm}>Cohort(s)</th>
                  <th style={thStyleSm}>VMs</th>
                  <th style={thStyleSm}>Tenant / VM Detail</th>
                  <th style={thStyleSm}>Est. Hours</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  let lastCohort: string | null = null;
                  return plan.daily_schedule.map((day: any) => {
                    const dayCohortLabel = (day.cohorts?.length > 0)
                      ? day.cohorts.join(" + ")
                      : "Uncohorted";
                    const cohortChanged = dayCohortLabel !== lastCohort;
                    lastCohort = dayCohortLabel;
                    return (
                      <React.Fragment key={day.day}>
                        {cohortChanged && (
                          <tr style={{ background: "#eff6ff", borderTop: "2px solid #93c5fd" }}>
                            <td colSpan={5} style={{ padding: "5px 10px", fontWeight: 700,
                              color: "#1e40af", fontSize: "0.78rem" }}>
                              📦 {dayCohortLabel}
                            </td>
                          </tr>
                        )}
                        <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                          <td style={tdStyleSm}><strong>Day {day.day}</strong></td>
                          <td style={{ ...tdStyleSm, fontSize: "0.7rem", color: "#6b7280" }}>{dayCohortLabel}</td>
                          <td style={tdStyleSm}>{day.vm_count}</td>
                          <td style={tdStyleSm}>
                            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                              {Object.entries(
                                day.vms.reduce((acc: any, v: any) => {
                                  const tenant = v.tenant_name || "Unassigned";
                                  if (!acc[tenant]) acc[tenant] = [];
                                  acc[tenant].push(v);
                                  return acc;
                                }, {})
                              ).map(([tenantName, vms]: [string, any]) => (
                                <div key={tenantName} style={{ marginBottom: 4, width: "100%" }}>
                                  <div style={{ fontSize: "0.7rem", fontWeight: 600, color: "#4f46e5", marginBottom: 2 }}>
                                    📁 {tenantName} ({(vms as any[]).length} VMs)
                                  </div>
                                  <div style={{ display: "flex", gap: 2, flexWrap: "wrap", marginLeft: 8 }}>
                                    {(vms as any[]).map((v: any) => (
                                      <span key={v.vm_name} style={{
                                        ...pillStyle, fontSize: "0.65rem", padding: "2px 4px",
                                        background: v.mode === "cold_required" ? "#fee2e2" : "#dcfce7",
                                        color: v.mode === "cold_required" ? "#dc2626" : "#16a34a",
                                      }}>
                                        {v.vm_name} ({v.disk_gb}GB)
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </td>
                          <td style={tdStyleSm}>{day.total_estimated_hours.toFixed(1)}h</td>
                        </tr>
                      </React.Fragment>
                    );
                  });
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  Risk Config View                                                  */
/* ================================================================== */

function RiskConfigView({ riskConfig, projectId, onRefresh }: {
  riskConfig: any, projectId: number, onRefresh: () => void
}) {
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    const w = riskConfig?.rules?.risk_weights;
    if (w && typeof w === "object") setWeights(w);
  }, [riskConfig]);

  const save = async () => {
    setSaving(true);
    setMsg("");
    try {
      const updatedRules = { ...(riskConfig?.rules || {}), risk_weights: weights };
      await apiFetch(`/api/migration/projects/${projectId}/risk-config`, {
        method: "PUT", body: JSON.stringify({ rules: updatedRules }),
      });
      setMsg("Saved. Re-run assessment to apply.");
      onRefresh();
    } catch (e: any) {
      setMsg("Error: " + e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={sectionStyle}>
      <h3 style={{ marginTop: 0 }}>Risk Scoring Weights</h3>
      <p style={{ color: "#6b7280", fontSize: "0.85rem" }}>
        Adjust weights used to compute risk scores. Higher weight = more impact.
        Re-run assessment after changes.
      </p>
      {msg && <div style={{ ...alertSuccess, marginBottom: 12 }}>{msg}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
        {Object.entries(weights).map(([key, val]) => (
          <div key={key}>
            <label style={labelStyle}>{key.replace(/_/g, " ")}</label>
            <input type="number" value={val} min={0} max={100}
              onChange={e => setWeights(prev => ({ ...prev, [key]: +e.target.value }))}
              style={inputStyle} />
          </div>
        ))}
      </div>
      <button onClick={save} disabled={saving} style={{ ...btnPrimary, marginTop: 12 }}>
        {saving ? "Saving..." : "Save Weights"}
      </button>
    </div>
  );
}

/* ================================================================== */
/*  Capacity Planning View  (Phase 2C — Quota · Phase 2D — Sizing)   */
/* ================================================================== */

interface OvercommitProfile {
  id: number;
  profile_name: string;
  display_name: string;
  description: string;
  cpu_ratio: number;
  ram_ratio: number;
  disk_snapshot_factor: number;
}

interface QuotaResult {
  profile: string;
  totals_allocated: { vcpu: number; ram_gb: number; ram_used_gb: number; disk_tb: number };
  totals_recommended: { vcpu: number; ram_gb: number; disk_tb: number };
  per_tenant: Array<{
    tenant_name: string;
    vcpu_alloc?: number; ram_gb_alloc?: number; disk_gb_alloc?: number;
    vcpu_allocated?: number; ram_gb_allocated?: number; disk_tb_allocated?: number;
    ram_used_gb?: number;
    vcpu_recommended: number; ram_gb_recommended: number; disk_gb_recommended?: number; disk_tb_recommended?: number;
  }>;
}

interface NodeProfile {
  id: number;
  profile_name: string;
  cpu_cores: number;
  cpu_threads: number;
  ram_gb: number;
  storage_tb: number;
  max_cpu_util_pct: number;
  max_ram_util_pct: number;
  max_disk_util_pct: number;
  is_default: boolean;
}

interface SizingResult {
  // Live cluster
  node_count_current: number;
  cluster_vcpu_total: number;
  cluster_ram_total: number;
  vcpu_per_node: number;
  ram_per_node: number;
  // Policy
  max_util_pct: number;
  peak_buffer_pct: number;
  // Sizing math
  safe_vcpu: number;
  safe_ram: number;
  already_used_vcpu: number;
  already_used_ram: number;
  headroom_vcpu: number;
  headroom_ram: number;
  demand_vcpu: number;
  demand_ram: number;
  deficit_vcpu: number;
  deficit_ram: number;
  nodes_to_add: number;
  nodes_total: number;
  binding_dimension: string;
  post_cpu_pct: number;
  post_ram_pct: number;
  disk_tb_required?: number;
  steps: string[];
  warnings: string[];
  // VM footprint (source of physical demand)
  vm_powered_on_count?: number;
  vm_vcpu_actual?: number;      // actual running vCPU (perf) OR alloc÷overcommit (fallback)
  vm_ram_gb_actual?: number;    // active RAM (perf) OR allocated (fallback)
  vm_vcpu_alloc?: number;       // raw allocated vCPU (always from RVtools)
  vm_ram_gb_alloc?: number;     // raw allocated RAM GB (always from RVtools)
  sizing_basis?: string;        // "actual_performance" | "allocation" | "quota"
  source_node_count?: number;   // distinct vSphere hosts running the VMs
  perf_coverage_pct?: number;   // % of powered-on VMs that have cpu_usage_percent
  // Legacy aliases
  nodes_recommended: number;
  nodes_additional_required: number;
  existing_nodes: number;
  ha_spares: number;
  ha_policy: string;
}

function CapacityPlanningView({ projectId }: { projectId: number }) {
  const [profiles, setProfiles] = useState<OvercommitProfile[]>([]);
  const [activeProfile, setActiveProfile] = useState<string>("balanced");
  const [quotaResult, setQuotaResult] = useState<QuotaResult | null>(null);
  const [nodeProfiles, setNodeProfiles] = useState<NodeProfile[]>([]);
  const [sizingResult, setSizingResult] = useState<SizingResult | null>(null);
  const [maxUtilPct, setMaxUtilPct] = useState(70);
  const [peakBufferPct, setPeakBufferPct] = useState(15);
  const [liveCluster, setLiveCluster] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [autoDetecting, setAutoDetecting] = useState(false);

  /* New node-profile form */
  const [showNewProfile, setShowNewProfile] = useState(false);
  const [npForm, setNpForm] = useState({
    profile_name: "Custom Nodes", cpu_cores: 32, cpu_threads: 64,
    ram_gb: 512, storage_tb: 20, max_cpu_util_pct: 75,
    max_ram_util_pct: 75, max_disk_util_pct: 85, is_default: false,
  });

  const autoDetectNodeProfile = async () => {
    setAutoDetecting(true);
    setError("");
    try {
      const result = await apiFetch<any>(`/api/migration/projects/${projectId}/pcd-auto-detect-profile`);
      if (result.status === "no_data") {
        setError(result.message);
        return;
      }
      const d = result.dominant_profile;
      setNpForm({
        profile_name: d.suggested_name || `${d.cpu_threads}vCPU-${d.ram_gb}GB`,
        cpu_cores: d.cpu_cores,
        cpu_threads: d.cpu_threads,
        ram_gb: d.ram_gb,
        storage_tb: d.storage_tb,
        max_cpu_util_pct: 75,
        max_ram_util_pct: 75,
        max_disk_util_pct: 85,
        is_default: true,
      });
      setShowNewProfile(true);
      setMsg(result.message);
      setTimeout(() => setMsg(""), 6000);
    } catch (e: any) { setError(e.message); }
    setAutoDetecting(false);
  };

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [profResp, nodeProf] = await Promise.all([
        apiFetch("/api/migration/overcommit-profiles"),
        apiFetch(`/api/migration/projects/${projectId}/node-profiles`),
      ]);
      setProfiles(profResp.profiles || []);
      setNodeProfiles(nodeProf.profiles || []);

      // Load live PCD cluster data from hypervisors table
      const liveResp = await apiFetch(`/api/migration/projects/${projectId}/pcd-live-inventory`).catch(() => null);
      if (liveResp?.live) setLiveCluster(liveResp.live);

      const quotaResp = await apiFetch(`/api/migration/projects/${projectId}/quota-requirements`).catch(() => null);
      const quota = quotaResp?.quota;
      if (quota) setQuotaResult(quota);
      if (quota?.profile) setActiveProfile(typeof quota.profile === 'object' ? quota.profile.profile_name : quota.profile);

      // Auto-compute sizing if node profiles exist
      const sizingResp = await apiFetch(`/api/migration/projects/${projectId}/node-sizing?max_util_pct=${maxUtilPct}&peak_buffer_pct=${peakBufferPct}`).catch(() => null);
      if (sizingResp?.sizing) {
        setSizingResult(sizingResp.sizing);
        if (sizingResp.live_cluster) setLiveCluster(sizingResp.live_cluster);
      }
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  };

  const computeSizing = async (util = maxUtilPct, peak = peakBufferPct) => {
    setError("");
    try {
      const result = await apiFetch(`/api/migration/projects/${projectId}/node-sizing?max_util_pct=${util}&peak_buffer_pct=${peak}`);
      setSizingResult(result.sizing || null);
      if (result.live_cluster) setLiveCluster(result.live_cluster);
    } catch (e: any) { setError(e.message); }
  };

  const setProfile = async (name: string) => {
    setError("");
    try {
      await apiFetch(`/api/migration/projects/${projectId}/overcommit-profile`, {
        method: "PATCH",
        body: JSON.stringify({ overcommit_profile_name: name }),
      });
      setActiveProfile(name);
      const quotaResp = await apiFetch(`/api/migration/projects/${projectId}/quota-requirements`).catch(() => null);
      const quota = quotaResp?.quota;
      if (quota) setQuotaResult(quota);
      setMsg("Overcommit profile updated.");
      setTimeout(() => setMsg(""), 3000);
    } catch (e: any) { setError(e.message); }
  };

  const saveInventory = async () => {
    // Legacy: no longer used — inventory is read live from PCD
  };

  const addNodeProfile = async () => {
    setError("");
    try {
      await apiFetch(`/api/migration/projects/${projectId}/node-profiles`, {
        method: "POST",
        body: JSON.stringify(npForm),
      });
      setShowNewProfile(false);
      load();
    } catch (e: any) { setError(e.message); }
  };

  const deleteNodeProfile = async (id: number) => {
    setError("");
    try {
      await apiFetch(`/api/migration/projects/${projectId}/node-profiles/${id}`, { method: "DELETE" });
      setNodeProfiles(prev => prev.filter(p => p.id !== id));
    } catch (e: any) { setError(e.message); }
  };

  const setDefaultProfile = async (np: NodeProfile) => {
    setError("");
    try {
      await apiFetch(`/api/migration/projects/${projectId}/node-profiles`, {
        method: "POST",
        body: JSON.stringify({ ...np, is_default: true }),
      });
      load();
    } catch { load(); }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  React.useEffect(() => { load(); }, [projectId]);

  const utilColor = (pct: number) =>
    pct <= 70 ? "#16a34a" : pct <= 85 ? "#d97706" : "#dc2626";

  return (
    <div>
      {error && <div style={alertError}>{error}</div>}
      {msg && <div style={alertSuccess}>{msg}</div>}
      {loading && <div style={{ textAlign: "center", padding: 32, color: "#6b7280" }}>Loading…</div>}

      {/* ---- Phase 2C: Overcommit Profile ---- */}
      <div style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>⚖️ Overcommit Profile</h3>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {profiles.map(p => (
            <div key={p.profile_name}
              onClick={() => setProfile(p.profile_name)}
              style={{
                padding: "12px 16px", borderRadius: 8, cursor: "pointer", minWidth: 180,
                border: `2px solid ${activeProfile === p.profile_name ? "#3b82f6" : "var(--border, #e5e7eb)"}`,
                background: activeProfile === p.profile_name ? "#eff6ff" : "var(--card-bg, #fff)",
              }}>
              <div style={{ fontWeight: 700 }}>{p.display_name}</div>
              <div style={{ fontSize: "0.78rem", color: "#6b7280", marginTop: 4 }}>{p.description}</div>
              <div style={{ fontSize: "0.78rem", marginTop: 6 }}>
                CPU {p.cpu_ratio}:1 · RAM {p.ram_ratio}:1 · Disk ×{p.disk_snapshot_factor}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ---- Phase 2C: Quota Table ---- */}
      {quotaResult && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>📊 Quota Requirements ({typeof quotaResult.profile === 'object' ? quotaResult.profile.profile_name : quotaResult.profile})</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 16 }}>
            <div style={{ ...sectionStyle, textAlign: "center", margin: 0 }}>
              <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>vCPU needed</div>
              <div style={{ fontSize: "1.4rem", fontWeight: 700 }}>{quotaResult.totals_recommended.vcpu.toLocaleString()}</div>
              <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>of {quotaResult.totals_allocated.vcpu.toLocaleString()} allocated</div>
            </div>
            <div style={{ ...sectionStyle, textAlign: "center", margin: 0 }}>
              <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>PCD Quota (GB)</div>
              <div style={{ fontSize: "1.4rem", fontWeight: 700 }}>{quotaResult.totals_recommended.ram_gb.toFixed(0)}</div>
              <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>vCloud alloc: {quotaResult.totals_allocated.ram_gb.toFixed(0)} GB</div>
              {(quotaResult.totals_allocated.ram_used_gb ?? 0) > 0 && (
                <div style={{ fontSize: "0.75rem", color: "#d97706" }}>actual used: {(quotaResult.totals_allocated.ram_used_gb ?? 0).toFixed(0)} GB</div>
              )}
            </div>
            <div style={{ ...sectionStyle, textAlign: "center", margin: 0 }}>
              <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>Disk needed (TB)</div>
              <div style={{ fontSize: "1.4rem", fontWeight: 700 }}>{quotaResult.totals_recommended.disk_tb.toFixed(2)}</div>
              <div style={{ fontSize: "0.75rem", color: "#9ca3af" }}>of {quotaResult.totals_allocated.disk_tb.toFixed(2)} TB allocated</div>
            </div>
          </div>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Tenant</th>
                <th style={thStyle}>vCPU Alloc</th>
                <th style={thStyle}>PCD vCPU Quota</th>
                <th style={thStyle}>RAM Alloc (GB)</th>
                <th style={thStyle}>RAM Used (GB)</th>
                <th style={thStyle}>PCD RAM Quota (GB)</th>
                <th style={thStyle}>Disk Alloc (TB)</th>
                <th style={thStyle}>PCD Disk Quota (TB)</th>
              </tr>
            </thead>
            <tbody>
              {quotaResult.per_tenant.map((pt, i) => (
                <tr key={`${pt.tenant_name}-${(pt as any).org_vdc || i}`} style={{ borderBottom: "1px solid var(--border, #e5e7eb)" }}>
                  <td style={tdStyle}><strong>{pt.tenant_name}</strong></td>
                  <td style={tdStyle}>{pt.vcpu_alloc ?? pt.vcpu_allocated ?? 0}</td>
                  <td style={tdStyle}>{pt.vcpu_recommended ?? 0}</td>
                  <td style={tdStyle}>{((pt.ram_gb_alloc ?? pt.ram_gb_allocated) ?? 0).toFixed(0)}</td>
                  <td style={{ ...tdStyle, color: (pt.ram_used_gb ?? 0) > (pt.ram_gb_alloc ?? pt.ram_gb_allocated ?? 0) ? "#dc2626" : "inherit" }}>
                    {(pt.ram_used_gb ?? 0) > 0 ? (pt.ram_used_gb as number).toFixed(0) : "—"}
                  </td>
                  <td style={tdStyle}>{(pt.ram_gb_recommended ?? 0).toFixed(0)}</td>
                  <td style={tdStyle}>{((pt.disk_gb_alloc ?? 0) / 1024).toFixed(3)}</td>
                  <td style={tdStyle}>{((pt.disk_gb_recommended ?? pt.disk_tb_recommended ?? 0) / (pt.disk_gb_recommended ? 1024 : 1)).toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ---- Phase 2D: Node Profiles ---- */}
      <div style={sectionStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>🖥️ PCD Node Profiles</h3>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={autoDetectNodeProfile} disabled={autoDetecting} style={btnSecondary}>
              {autoDetecting ? "⏳ Detecting…" : "🔍 Auto-Detect from PCD"}
            </button>
            <button onClick={() => setShowNewProfile(!showNewProfile)} style={btnSecondary}>+ New Profile</button>
          </div>
        </div>
        {showNewProfile && (
          <div style={{ ...sectionStyle, marginBottom: 12, background: "#f8fafc" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 8 }}>
              <div>
                <label style={labelStyle}>Profile Name</label>
                <input style={inputStyle} value={npForm.profile_name}
                  onChange={e => setNpForm(p => ({ ...p, profile_name: e.target.value }))} />
              </div>
              <div>
                <label style={labelStyle}>CPU Cores</label>
                <input type="number" style={inputStyle} value={npForm.cpu_cores}
                  onChange={e => setNpForm(p => ({ ...p, cpu_cores: +e.target.value }))} />
              </div>
              <div>
                <label style={labelStyle}>CPU Threads</label>
                <input type="number" style={inputStyle} value={npForm.cpu_threads}
                  onChange={e => setNpForm(p => ({ ...p, cpu_threads: +e.target.value }))} />
              </div>
              <div>
                <label style={labelStyle}>RAM (GB)</label>
                <input type="number" style={inputStyle} value={npForm.ram_gb}
                  onChange={e => setNpForm(p => ({ ...p, ram_gb: +e.target.value }))} />
              </div>
              <div>
                <label style={labelStyle}>Storage (TB)</label>
                <input type="number" style={inputStyle} value={npForm.storage_tb}
                  onChange={e => setNpForm(p => ({ ...p, storage_tb: +e.target.value }))} />
              </div>
              <div>
                <label style={labelStyle}>Max CPU util %</label>
                <input type="number" style={inputStyle} value={npForm.max_cpu_util_pct}
                  onChange={e => setNpForm(p => ({ ...p, max_cpu_util_pct: +e.target.value }))} />
              </div>
              <div>
                <label style={labelStyle}>Max RAM util %</label>
                <input type="number" style={inputStyle} value={npForm.max_ram_util_pct}
                  onChange={e => setNpForm(p => ({ ...p, max_ram_util_pct: +e.target.value }))} />
              </div>
              <div>
                <label style={labelStyle}>Max Disk util %</label>
                <input type="number" style={inputStyle} value={npForm.max_disk_util_pct}
                  onChange={e => setNpForm(p => ({ ...p, max_disk_util_pct: +e.target.value }))} />
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <label style={{ fontSize: "0.85rem" }}>
                <input type="checkbox" checked={npForm.is_default}
                  onChange={e => setNpForm(p => ({ ...p, is_default: e.target.checked }))}
                  style={{ marginRight: 6 }} />
                Set as default
              </label>
              <button onClick={addNodeProfile} style={btnPrimary}>Save Profile</button>
              <button onClick={() => setShowNewProfile(false)} style={btnSecondary}>Cancel</button>
            </div>
          </div>
        )}
        {nodeProfiles.length === 0 ? (
          <p style={{ color: "#6b7280", textAlign: "center" }}>No node profiles yet. Add one above to enable sizing calculations.</p>
        ) : (
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Profile</th>
                <th style={thStyle}>Cores</th>
                <th style={thStyle}>Threads</th>
                <th style={thStyle}>RAM GB</th>
                <th style={thStyle}>Storage TB</th>
                <th style={thStyle}>CPU%</th>
                <th style={thStyle}>RAM%</th>
                <th style={thStyle}>Disk%</th>
                <th style={thStyle}>Default</th>
                <th style={thStyle}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {nodeProfiles.map(p => (
                <tr key={p.id} style={{ borderBottom: "1px solid var(--border, #e5e7eb)" }}>
                  <td style={tdStyle}><strong>{p.profile_name}</strong></td>
                  <td style={tdStyle}>{p.cpu_cores}</td>
                  <td style={tdStyle}>{p.cpu_threads}</td>
                  <td style={tdStyle}>{p.ram_gb}</td>
                  <td style={tdStyle}>{p.storage_tb}</td>
                  <td style={tdStyle}>{p.max_cpu_util_pct}%</td>
                  <td style={tdStyle}>{p.max_ram_util_pct}%</td>
                  <td style={tdStyle}>{p.max_disk_util_pct}%</td>
                  <td style={tdStyle}>{p.is_default ? "⭐" : <button onClick={() => setDefaultProfile(p)} style={btnSmall}>Set</button>}</td>
                  <td style={tdStyle}>
                    <button onClick={() => deleteNodeProfile(p.id)}
                      style={{ ...btnSmall, color: "#dc2626" }} title="Delete">🗑</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ---- Phase 2D: Node Sizing ---- */}
      <div style={sectionStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0 }}>📐 Node Sizing</h3>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <label style={{ fontSize: "0.82rem", color: "#6b7280", whiteSpace: "nowrap" }}>Max utilisation %</label>
              <input
                type="number" min={50} max={95} step={5}
                value={maxUtilPct}
                onChange={e => setMaxUtilPct(+e.target.value)}
                style={{ ...inputStyle, width: 60, textAlign: "center" }}
              />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <label style={{ fontSize: "0.82rem", color: "#6b7280", whiteSpace: "nowrap" }}>Peak buffer %</label>
              <input
                type="number" min={0} max={50} step={5}
                value={peakBufferPct}
                onChange={e => setPeakBufferPct(+e.target.value)}
                style={{ ...inputStyle, width: 60, textAlign: "center" }}
              />
            </div>
            <button onClick={() => computeSizing(maxUtilPct, peakBufferPct)} style={btnPrimary}>
              🔄 Recalculate
            </button>
          </div>
        </div>
        <div style={{ fontSize: "0.78rem", color: "#6b7280", marginBottom: 16, lineHeight: 1.5 }}>
          <strong>{maxUtilPct}% max utilisation</strong> is your HA strategy — it ensures nodes can absorb a failure without overloading.
          An additional <strong>{peakBufferPct}% peak buffer</strong> is added on top of migration demand to handle burst traffic.
        </div>

        {/* Live PCD cluster read-only facts */}
        {liveCluster && liveCluster.node_count > 0 && (
          <div style={{ ...sectionStyle, margin: "0 0 16px", background: "#f0fdf4", border: "1px solid #bbf7d0" }}>
            <strong style={{ color: "#15803d", fontSize: "0.9rem" }}>🖥️ Live PCD Cluster (from inventory DB)</strong>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 10, marginTop: 10 }}>
              {[
                { label: "Nodes",        val: liveCluster.node_count },
                { label: "Total vCPU",   val: liveCluster.total_vcpus },
                { label: "Total RAM",    val: `${liveCluster.total_ram_gb} GB` },
                { label: "vCPU in use",  val: liveCluster.vcpus_used },
                { label: "RAM in use",   val: `${liveCluster.ram_gb_used} GB` },
                { label: "Disk alloc",   val: `${liveCluster.disk_tb_used} TB` },
              ].map(d => (
                <div key={d.label} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: "0.7rem", color: "#6b7280" }}>{d.label}</div>
                  <div style={{ fontSize: "1rem", fontWeight: 700, color: "#15803d" }}>{d.val}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {sizingResult ? (
          <div>
            {/* ── Migration Delivery Summary ── */}
            {(() => {
              const vcpuPerNode  = sizingResult.vcpu_per_node  || 0;
              const ramPerNode   = sizingResult.ram_per_node   || 0;
              const nodesTotal   = sizingResult.nodes_total    || 0;
              const maxUtil      = sizingResult.max_util_pct   || 70;
              const newTotalVcpu = nodesTotal * vcpuPerNode;
              const newTotalRam  = nodesTotal * ramPerNode;
              const newSafeVcpu  = newTotalVcpu * (maxUtil / 100);
              const newSafeRam   = newTotalRam  * (maxUtil / 100);
              const demandVcpu   = sizingResult.demand_vcpu    ?? 0;
              const demandRam    = sizingResult.demand_ram     ?? 0;
              const postCpuPct   = sizingResult.post_cpu_pct   ?? 0;
              const postRamPct   = sizingResult.post_ram_pct   ?? 0;
              const peakPct      = sizingResult.peak_buffer_pct ?? 0;
              const quotaVcpu    = quotaResult?.totals_recommended?.vcpu ?? null;
              const quotaRamGb   = quotaResult?.totals_recommended?.ram_gb ?? null;
              const quotaDiskTb  = quotaResult?.totals_recommended?.disk_tb ?? sizingResult.disk_tb_required ?? null;

              const pctBar = (used: number, total: number, cap: number) => {
                if (!total || !isFinite(total)) return <div style={{ height: 8 }} />;
                const usedPct  = Math.min((used  / total) * 100, 100);
                const capPct   = Math.min((cap   / total) * 100, 100);
                const col = usedPct <= capPct * 0.85 ? "#16a34a" : usedPct <= capPct ? "#d97706" : "#dc2626";
                return (
                  <div style={{ position: "relative", background: "#e5e7eb", borderRadius: 999, height: 8, overflow: "hidden", marginTop: 4 }}>
                    {/* cap marker */}
                    <div style={{ position: "absolute", left: `${capPct}%`, top: 0, bottom: 0, width: 2, background: "#9ca3af", zIndex: 1 }} title={`${cap.toFixed(0)} (${sizingResult.max_util_pct}% cap)`} />
                    {/* used fill */}
                    <div style={{ width: `${usedPct}%`, height: "100%", background: col, borderRadius: 999 }} />
                  </div>
                );
              };

              return (
                <div style={{ ...sectionStyle, margin: "0 0 16px", background: "#f8fafc", border: "1px solid #e2e8f0" }}>
                  <div style={{ fontWeight: 700, fontSize: "0.95rem", marginBottom: 14, color: "#1e293b" }}>
                    🗂️ Migration Capacity Summary
                  </div>

                  {/* Headline deliverables */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 16 }}>
                    <div style={{
                      textAlign: "center", padding: "12px 8px", borderRadius: 8,
                      background: sizingResult.nodes_to_add > 0 ? "#fff7ed" : "#f0fdf4",
                      border: `1px solid ${sizingResult.nodes_to_add > 0 ? "#fed7aa" : "#bbf7d0"}`,
                    }}>
                      <div style={{ fontSize: "0.72rem", color: "#6b7280", marginBottom: 2 }}>HW nodes to provision</div>
                      <div style={{ fontSize: "1.8rem", fontWeight: 900, color: sizingResult.nodes_to_add > 0 ? "#d97706" : "#16a34a", lineHeight: 1 }}>
                        {sizingResult.nodes_to_add > 0 ? `+${sizingResult.nodes_to_add}` : "None"}
                      </div>
                      <div style={{ fontSize: "0.72rem", color: "#6b7280", marginTop: 3 }}>
                        {sizingResult.nodes_to_add > 0
                          ? `${sizingResult.node_count_current} existing → ${sizingResult.nodes_total} total`
                          : `${sizingResult.nodes_total} current nodes sufficient`}
                      </div>
                    </div>
                    <div style={{ textAlign: "center", padding: "12px 8px", borderRadius: 8, background: "#eff6ff", border: "1px solid #bfdbfe" }}>
                      <div style={{ fontSize: "0.72rem", color: "#6b7280", marginBottom: 2 }}>Cinder storage to provision</div>
                      <div style={{ fontSize: "1.8rem", fontWeight: 900, color: "#3b82f6", lineHeight: 1 }}>
                        {quotaDiskTb != null ? `${quotaDiskTb.toFixed(1)} TB` : "—"}
                      </div>
                      <div style={{ fontSize: "0.72rem", color: "#6b7280", marginTop: 3 }}>Ceph/SAN — independent of HW nodes</div>
                    </div>
                    <div style={{ textAlign: "center", padding: "12px 8px", borderRadius: 8, background: "#f5f3ff", border: "1px solid #ddd6fe" }}>
                      <div style={{ fontSize: "0.72rem", color: "#6b7280", marginBottom: 2 }}>Binding constraint</div>
                      <div style={{ fontSize: "1.4rem", fontWeight: 800, color: "#7c3aed", lineHeight: 1, textTransform: "uppercase" }}>
                        {sizingResult.binding_dimension}
                      </div>
                      <div style={{ fontSize: "0.72rem", color: "#6b7280", marginTop: 3 }}>
                        post-migration: CPU {postCpuPct.toFixed(1)}% · RAM {postRamPct.toFixed(1)}%
                      </div>
                    </div>
                  </div>

                  {/* Resource table: quota vs HW demand vs HW capacity */}
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.83rem" }}>
                    <thead>
                      <tr style={{ background: "#f1f5f9" }}>
                        <th style={{ ...thStyle, textAlign: "left", width: "10%" }}>Resource</th>
                        <th style={{ ...thStyle, textAlign: "right", width: "20%" }}>
                          <span title="OpenStack quota to configure for tenants in PCD">Tenant Quota (PCD) ℹ️</span>
                        </th>
                        <th style={{ ...thStyle, textAlign: "right", width: "22%" }}>
                          <span title={
                            sizingResult.sizing_basis === "actual_performance"
                              ? `Based on ACTUAL CPU/RAM utilisation from RVtools performance data. ` +
                                `${sizingResult.vm_powered_on_count ?? 0} powered-on VMs with ${sizingResult.perf_coverage_pct ?? 0}% perf coverage. ` +
                                `Actual running: ${sizingResult.vm_vcpu_actual ?? 0} vCPU, ${sizingResult.vm_ram_gb_actual ?? 0} GB RAM (of ${sizingResult.vm_vcpu_alloc ?? 0} vCPU / ${sizingResult.vm_ram_gb_alloc ?? 0} GB allocated). ` +
                                `Demand = actual × (1 + ${peakPct}% peak buffer).`
                              : sizingResult.sizing_basis === "allocation"
                              ? `Based on configured vCPU allocation ÷ overcommit ratio (no sufficient performance data). ` +
                                `${sizingResult.vm_powered_on_count ?? 0} powered-on VMs: ${sizingResult.vm_vcpu_alloc ?? 0} vCPU allocated ÷ overcommit + ${peakPct}% peak buffer.`
                              : `Based on tenant quota totals + ${peakPct}% peak buffer.`
                          }>HW Demand (+{peakPct}% peak) ℹ️</span>
                        </th>
                        <th style={{ ...thStyle, textAlign: "right", width: "22%" }}>
                          <span title={`Usable capacity of ${nodesTotal} nodes at ${maxUtil}% utilisation cap`}>HW Usable ({maxUtil}% cap) ℹ️</span>
                        </th>
                        <th style={{ ...thStyle, textAlign: "right", width: "14%" }}>Surplus</th>
                        <th style={{ ...thStyle, width: "12%" }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {/* vCPU row */}
                      <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                        <td style={{ ...tdStyle, fontWeight: 600 }}>vCPU</td>
                        <td style={{ ...tdStyle, textAlign: "right" }}>
                          {quotaVcpu != null ? <><strong>{quotaVcpu.toLocaleString()}</strong> cores</> : <span style={{ color: "#9ca3af" }}>—</span>}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right" }}>
                          <strong>{demandVcpu.toFixed(0)}</strong> cores
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: "#15803d", fontWeight: 600 }}>
                          {newSafeVcpu.toFixed(0)} cores
                          <div style={{ fontSize: "0.72rem", color: "#9ca3af", fontWeight: 400 }}>
                            {newTotalVcpu.toFixed(0)} total × {maxUtil}%
                          </div>
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: newSafeVcpu - demandVcpu >= 0 ? "#16a34a" : "#dc2626", fontWeight: 600 }}>
                          {newSafeVcpu - demandVcpu >= 0 ? "+" : ""}
                          {(newSafeVcpu - demandVcpu).toFixed(0)}
                        </td>
                        <td style={tdStyle}>
                          {pctBar(demandVcpu, newTotalVcpu, newSafeVcpu)}
                        </td>
                      </tr>
                      {/* RAM row */}
                      <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                        <td style={{ ...tdStyle, fontWeight: 600 }}>RAM</td>
                        <td style={{ ...tdStyle, textAlign: "right" }}>
                          {quotaRamGb != null ? <><strong>{quotaRamGb.toFixed(0)}</strong> GB</> : <span style={{ color: "#9ca3af" }}>—</span>}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right" }}>
                          <strong>{demandRam.toFixed(0)}</strong> GB
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: "#15803d", fontWeight: 600 }}>
                          {newSafeRam.toFixed(0)} GB
                          <div style={{ fontSize: "0.72rem", color: "#9ca3af", fontWeight: 400 }}>
                            {newTotalRam.toFixed(0)} GB total × {maxUtil}%
                          </div>
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: newSafeRam - demandRam >= 0 ? "#16a34a" : "#dc2626", fontWeight: 600 }}>
                          {newSafeRam - demandRam >= 0 ? "+" : ""}
                          {(newSafeRam - demandRam).toFixed(0)} GB
                        </td>
                        <td style={tdStyle}>
                          {pctBar(demandRam, newTotalRam, newSafeRam)}
                        </td>
                      </tr>
                      {/* Storage row */}
                      <tr>
                        <td style={{ ...tdStyle, fontWeight: 600 }}>Storage</td>
                        <td style={{ ...tdStyle, textAlign: "right" }}>
                          {quotaDiskTb != null ? <><strong>{quotaDiskTb.toFixed(2)}</strong> TB</> : <span style={{ color: "#9ca3af" }}>—</span>}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right" }}>
                          {sizingResult.disk_tb_required != null
                            ? <><strong>{sizingResult.disk_tb_required.toFixed(2)}</strong> TB</>
                            : <span style={{ color: "#9ca3af" }}>—</span>}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: "#3b82f6" }}>
                          Provision separately
                          <div style={{ fontSize: "0.72rem", color: "#9ca3af" }}>Ceph / SAN / NFS</div>
                        </td>
                        <td style={{ ...tdStyle, textAlign: "right", color: "#6b7280" }}>—</td>
                        <td style={tdStyle}></td>
                      </tr>
                    </tbody>
                  </table>
                  {/* Sizing basis badge */}
                  <div style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    fontSize: "0.71rem", marginTop: 10, padding: "3px 10px",
                    borderRadius: 99, border: "1px solid",
                    background: sizingResult.sizing_basis === "actual_performance" ? "#f0fdf4" : sizingResult.sizing_basis === "allocation" ? "#fefce8" : "#f1f5f9",
                    borderColor: sizingResult.sizing_basis === "actual_performance" ? "#86efac" : sizingResult.sizing_basis === "allocation" ? "#fde68a" : "#e2e8f0",
                    color: sizingResult.sizing_basis === "actual_performance" ? "#15803d" : sizingResult.sizing_basis === "allocation" ? "#92400e" : "#475569",
                  }}>
                    <span>{sizingResult.sizing_basis === "actual_performance" ? "📊" : sizingResult.sizing_basis === "allocation" ? "⚠️" : "ℹ️"}</span>
                    {sizingResult.sizing_basis === "actual_performance" && (
                      <>Demand based on <strong>actual VM performance data</strong> · {sizingResult.vm_powered_on_count ?? 0} powered-on VMs · {sizingResult.perf_coverage_pct ?? 0}% perf coverage · {sizingResult.vm_vcpu_actual ?? 0} vCPU running of {sizingResult.vm_vcpu_alloc ?? 0} allocated · {sizingResult.vm_ram_gb_actual ?? 0} GB active of {sizingResult.vm_ram_gb_alloc ?? 0} GB allocated</>    
                    )}
                    {sizingResult.sizing_basis === "allocation" && (
                      <>Demand based on <strong>vCPU allocation ÷ overcommit</strong> — no performance data available · {sizingResult.vm_powered_on_count ?? 0} powered-on VMs · {sizingResult.perf_coverage_pct ?? 0}% perf coverage</>
                    )}
                    {(sizingResult.sizing_basis === "quota" || !sizingResult.sizing_basis) && (
                      <>Demand based on <strong>tenant quota</strong> — no RVtools VM data imported yet</>
                    )}
                  </div>
                  <div style={{ fontSize: "0.72rem", color: "#9ca3af", marginTop: 6 }}>
                    ℹ️ <em>Tenant Quota</em> = OpenStack quota to set per tenant in PCD.&nbsp;
                    <em>HW Demand</em> = physical cores/RAM the cluster must supply ({sizingResult.sizing_basis === "actual_performance" ? `actual utilisation × (1+${peakPct}% peak)` : `allocation ÷ overcommit × (1+${peakPct}% peak)`}).&nbsp;
                    <em>HW Usable</em> = safe capacity of the final {nodesTotal}-node cluster at the {maxUtil}% HA cap.
                  </div>
                </div>
              );
            })()}

            {/* Result headline */}
            <div style={{
              ...sectionStyle, margin: "0 0 16px",
              background: sizingResult.nodes_to_add > 0 ? "#fff7ed" : "#f0fdf4",
              border: `1px solid ${sizingResult.nodes_to_add > 0 ? "#fed7aa" : "#bbf7d0"}`,
              textAlign: "center",
            }}>
              {sizingResult.nodes_to_add > 0 ? (
                <>
                  <div style={{ fontSize: "0.85rem", color: "#92400e", marginBottom: 4 }}>Nodes to add</div>
                  <div style={{ fontSize: "3rem", fontWeight: 900, color: "#d97706", lineHeight: 1 }}>
                    +{sizingResult.nodes_to_add}
                  </div>
                  <div style={{ fontSize: "0.8rem", color: "#92400e", marginTop: 4 }}>
                    Total cluster: {sizingResult.nodes_total} nodes · binding dimension: <strong>{sizingResult.binding_dimension}</strong>
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#16a34a" }}>✅ Current cluster is sufficient</div>
                  <div style={{ fontSize: "0.85rem", color: "#15803d", marginTop: 4 }}>
                    {sizingResult.nodes_total} existing nodes can absorb the full migration demand with headroom to spare.
                  </div>
                </>
              )}
            </div>

            {/* Post-migration utilisation */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              {[
                { label: "Post-migration CPU util", pct: sizingResult.post_cpu_pct ?? 0 },
                { label: "Post-migration RAM util", pct: sizingResult.post_ram_pct ?? 0 },
              ].map(({ label, pct }) => (
                <div key={label} style={{ ...sectionStyle, margin: 0 }}>
                  <div style={{ fontSize: "0.8rem", color: "#6b7280", marginBottom: 6 }}>{label}</div>
                  <div style={{ background: "#e5e7eb", borderRadius: 999, height: 10, overflow: "hidden" }}>
                    <div style={{
                      width: `${Math.min(pct, 100).toFixed(1)}%`,
                      height: "100%",
                      background: utilColor(pct),
                      borderRadius: 999,
                      transition: "width 0.4s",
                    }} />
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
                    <span style={{ fontSize: "0.78rem", fontWeight: 700, color: utilColor(pct) }}>{pct.toFixed(1)}%</span>
                    <span style={{ fontSize: "0.72rem", color: "#9ca3af" }}>target ≤ {sizingResult.max_util_pct}%</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Step-by-step calculation */}
            {sizingResult.steps && sizingResult.steps.length > 0 && (
              <div style={{ ...sectionStyle, margin: "0 0 12px", background: "#f8fafc" }}>
                <div style={{ fontWeight: 600, fontSize: "0.85rem", marginBottom: 8, color: "#374151" }}>📋 Calculation breakdown</div>
                <ol style={{ margin: 0, paddingLeft: 20 }}>
                  {sizingResult.steps.map((s, i) => (
                    <li key={i} style={{ fontSize: "0.83rem", color: "#374151", marginBottom: 3, lineHeight: 1.5 }}>{s}</li>
                  ))}
                </ol>
              </div>
            )}

            {/* Disk storage note */}
            {sizingResult.disk_tb_required != null && (
              <div style={{ ...sectionStyle, margin: "0 0 12px", background: "#eff6ff", border: "1px solid #bfdbfe" }}>
                <div style={{ fontSize: "0.85rem", color: "#1e40af" }}>
                  💾 <strong>Cinder storage needed: {sizingResult.disk_tb_required.toFixed(2)} TB</strong>
                  <span style={{ color: "#6b7280", marginLeft: 8, fontSize: "0.78rem" }}>— provision separately via your storage backend</span>
                </div>
              </div>
            )}

            {/* Warnings */}
            {sizingResult.warnings && sizingResult.warnings.length > 0 && (
              <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 8, padding: 12 }}>
                <strong style={{ color: "#92400e" }}>⚠️ Warnings</strong>
                <ul style={{ margin: "6px 0 0 0", paddingLeft: 20 }}>
                  {sizingResult.warnings.map((w, i) => (
                    <li key={i} style={{ fontSize: "0.85rem", color: "#92400e" }}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          !loading && (
            <div style={{ color: "#6b7280", textAlign: "center", padding: 24 }}>
              No sizing result yet. Add a node profile above and click <strong>Recalculate</strong>.
            </div>
          )
        )}
      </div>
    </div>
  );
}

/* ================================================================== */
/*  PCD Readiness View  (Phase 2E — Gap Analysis)                    */
/* ================================================================== */

interface PcdGap {
  id: number;
  gap_type: string;
  resource_name: string;
  tenant_name: string | null;
  severity: string;
  resolution: string;
  resolved: boolean;
  details: Record<string, any>;
}

function PcdReadinessView({ projectId }: { projectId: number }) {
  const [pcdUrl, setPcdUrl] = useState("");
  const [pcdRegion, setPcdRegion] = useState("region-one");
  const [readinessScore, setReadinessScore] = useState<number | null>(null);
  const [gaps, setGaps] = useState<PcdGap[]>([]);
  const [running, setRunning] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [sizingData, setSizingData] = useState<any>(null);
  const [quotaSummary, setQuotaSummary] = useState<any>(null);
  const [capacityError, setCapacityError] = useState("");

  const loadGaps = async () => {
    try {
      const g = await apiFetch(`/api/migration/projects/${projectId}/pcd-gaps?resolved=false`);
      setGaps(g.gaps || []);
      if (g.readiness_score != null) setReadinessScore(Number(g.readiness_score));
    } catch { /* silent */ }
  };

  const loadCapacity = async () => {
    setCapacityError("");
    try {
      const qr = await apiFetch(`/api/migration/projects/${projectId}/quota-requirements`).catch(() => null);
      if (qr?.quota) setQuotaSummary(qr.quota.totals_recommended);
      const sr = await apiFetch(`/api/migration/projects/${projectId}/node-sizing`).catch(() => null);
      if (sr?.sizing) {
        // Enrich sizing with live cluster data so node count reflects actual inventory
        const lr = await apiFetch(`/api/migration/projects/${projectId}/pcd-live-inventory`).catch(() => null);
        setSizingData(lr?.live?.node_count ? { ...sr.sizing, _live: lr.live } : sr.sizing);
      }
    } catch (e: any) { setCapacityError(e.message); }
  };

  const loadProject = async () => {
    try {
      const resp = await apiFetch(`/api/migration/projects/${projectId}`);
      const p = resp.project || resp;
      if (p.pcd_auth_url) setPcdUrl(p.pcd_auth_url);
      if (p.pcd_region) setPcdRegion(p.pcd_region || "region-one");
      if (p.pcd_readiness_score != null) setReadinessScore(Number(p.pcd_readiness_score));
    } catch { /* silent */ }
  };

  React.useEffect(() => {
    loadProject();
    loadGaps();
    loadCapacity();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const saveSettings = async () => {
    setSavingSettings(true);
    setError("");
    try {
      await apiFetch(`/api/migration/projects/${projectId}/pcd-settings`, {
        method: "PATCH",
        body: JSON.stringify({ pcd_auth_url: pcdUrl.trim() || null, pcd_region: pcdRegion.trim() || "region-one" }),
      });
      setMsg("PCD settings saved.");
      setTimeout(() => setMsg(""), 3000);
    } catch (e: any) { setError(e.message); }
    setSavingSettings(false);
  };

  const runAnalysis = async () => {
    setRunning(true);
    setError("");
    try {
      const result = await apiFetch(`/api/migration/projects/${projectId}/pcd-gap-analysis`, { method: "POST" });
      if (result.readiness_score != null) setReadinessScore(Number(result.readiness_score));
      await loadGaps();
      setMsg(`Gap analysis complete. Found ${(result.gap_counts?.total ?? (result.gaps || []).length)} gaps (${result.gap_counts?.critical ?? 0} critical).`);
      setTimeout(() => setMsg(""), 5000);
    } catch (e: any) { setError(e.message); }
    setRunning(false);
  };

  const resolveGap = async (gapId: number) => {
    try {
      await apiFetch(`/api/migration/projects/${projectId}/pcd-gaps/${gapId}/resolve`, { method: "PATCH" });
      await loadGaps();
    } catch (e: any) { setError(e.message); }
  };

  const downloadGapReport = async (fmt: "xlsx" | "pdf") => {
    try {
      const token = getToken();
      const res = await fetch(
        `${API_BASE}/api/migration/projects/${projectId}/export-gaps-report.${fmt}`,
        { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } }
      );
      if (!res.ok) { setError(`Download failed: ${res.status}`); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `pcd-readiness-gaps.${fmt}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: any) { setError(e.message); }
  };

  const unresolvedGaps = gaps.filter(g => !g.resolved);
  const resolvedGaps = gaps.filter(g => g.resolved);

  const scoreColor = (score: number) =>
    score >= 80 ? "#16a34a" : score >= 50 ? "#d97706" : "#dc2626";
  const utilColor = (pct: number) => pct > 85 ? "#dc2626" : pct > 70 ? "#d97706" : "#16a34a";

  const severityStyle = (sev: string): React.CSSProperties =>
    sev === "critical" ? { background: "#fee2e2", color: "#dc2626" } :
    sev === "warning" ? { background: "#fffbeb", color: "#d97706" } :
                        { background: "#f3f4f6", color: "#374151" };

  return (
    <div>
      {error && <div style={alertError}>{error}</div>}
      {msg && <div style={alertSuccess}>{msg}</div>}

      {/* PCD Connection info */}
      <div style={{ ...sectionStyle, background: "#f0fdf4", border: "1px solid #bbf7d0" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <strong style={{ color: "#15803d" }}>🔌 PCD Connection</strong>
            <span style={{ marginLeft: 12, fontSize: "0.85rem", color: "#6b7280" }}>
              Using global PF9 credentials from server config (.env). Gap analysis connects to your PCD environment automatically.
            </span>
          </div>
          {pcdUrl && (
            <span style={{ fontSize: "0.78rem", color: "#6b7280", fontFamily: "monospace" }}>{pcdUrl}</span>
          )}
        </div>
      </div>

      {/* ── Capacity Assessment ── */}
      <div style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>📀 Capacity Assessment</h3>
        {capacityError && (
          <div style={{ color: "#6b7280", fontSize: "0.85rem", marginBottom: 8 }}>
            {capacityError.includes("No node profile") ?
              <span>⚠️ No PCD node profile configured. Add one in the <strong>⚖️ Capacity</strong> tab to enable capacity assessment.</span> :
              <span>Could not load capacity data: {capacityError}</span>}
          </div>
        )}
        {!sizingData && !capacityError && (
          <p style={{ color: "#6b7280", fontSize: "0.85rem" }}>No capacity data yet. Add a node profile in the ⚖️ Capacity tab and run the assessment.</p>
        )}
        {quotaSummary && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#374151", marginBottom: 8 }}>Migration Requires (recommended PCD quotas)</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
              <div style={{ ...sectionStyle, textAlign: "center", margin: 0, padding: "10px 8px" }}>
                <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>vCPU</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 700 }}>{quotaSummary.vcpu?.toLocaleString() ?? "—"}</div>
              </div>
              <div style={{ ...sectionStyle, textAlign: "center", margin: 0, padding: "10px 8px" }}>
                <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>RAM (GB)</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 700 }}>{Number(quotaSummary.ram_gb ?? 0).toFixed(0)}</div>
              </div>
              <div style={{ ...sectionStyle, textAlign: "center", margin: 0, padding: "10px 8px" }}>
                <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>Disk (TB)</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 700 }}>{Number(quotaSummary.disk_tb ?? 0).toFixed(2)}</div>
              </div>
            </div>
          </div>
        )}
        {sizingData && (() => {
          const s = sizingData;
          const p = s.post_migration_utilisation || s.post_migration_utilization || {};
          const np = s.node_profile || {};
          const needMore = s.nodes_additional_required > 0;
          return (
            <div>
              <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#374151", marginBottom: 8 }}>
                PCD Node Profile: <code style={{ fontWeight: 400 }}>{np.profile_name || "—"}</code>
                <span style={{ marginLeft: 12, color: "#6b7280", fontWeight: 400 }}>
                  {np.cpu_threads || (np.cpu_cores * 2)} threads · {np.ram_gb} GB RAM · {np.storage_tb} TB storage per node
                </span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 12 }}>
                <div style={{ ...sectionStyle, textAlign: "center", margin: 0, padding: "12px 8px",
                  borderLeft: `4px solid ${needMore ? "#d97706" : "#16a34a"}` }}>
                  <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>Nodes Rec. (incl. HA)</div>
                  <div style={{ fontSize: "1.8rem", fontWeight: 800, color: "#3b82f6" }}>{s.nodes_recommended}</div>
                  <div style={{ fontSize: "0.72rem", color: "#9ca3af" }}>{s.ha_policy} — {s.ha_spares} spare{s.ha_spares !== 1 ? "s" : ""}</div>
                </div>
                <div style={{ ...sectionStyle, textAlign: "center", margin: 0, padding: "12px 8px" }}>
                  <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>Currently Deployed</div>
                  <div style={{ fontSize: "1.8rem", fontWeight: 800 }}>
                    {s._live?.node_count ?? s.existing_nodes}
                  </div>
                  <div style={{ fontSize: "0.72rem", color: "#9ca3af" }}>
                    {s._live ? "from inventory DB" : "from manual entry"}
                  </div>
                  {s._live && s._live.node_count !== s.existing_nodes && (
                    <div style={{ fontSize: "0.68rem", color: "#d97706" }}>
                      ⚠️ inventory set to {s.existing_nodes}
                    </div>
                  )}
                </div>
                <div style={{ ...sectionStyle, textAlign: "center", margin: 0, padding: "12px 8px",
                  background: needMore ? "#fffbeb" : "#f0fdf4", border: `1px solid ${needMore ? "#fde68a" : "#bbf7d0"}` }}>
                  <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>Additional Needed</div>
                  <div style={{ fontSize: "1.8rem", fontWeight: 800,
                    color: needMore ? "#d97706" : "#16a34a" }}>
                    {needMore ? `+${s.nodes_additional_required}` : "✔ 0"}
                  </div>
                  <div style={{ fontSize: "0.72rem", color: "#9ca3af" }}>
                    {needMore ? "new HW nodes required" : "sufficient capacity"}
                  </div>
                </div>
                <div style={{ ...sectionStyle, margin: 0, padding: "12px 8px" }}>
                  <div style={{ fontSize: "0.75rem", color: "#6b7280", marginBottom: 6 }}>Post-migration utilisation (compute)</div>
                  {[{label:"CPU", pct: p.cpu_pct},{label:"RAM", pct: p.ram_pct}].map(d => (
                    <div key={d.label} style={{ display:"flex", justifyContent:"space-between", marginBottom: 2 }}>
                      <span style={{ fontSize: "0.78rem" }}>{d.label}</span>
                      <span style={{ fontSize: "0.78rem", fontWeight: 600, color: utilColor(d.pct ?? 0) }}>
                        {d.pct != null ? `${Number(d.pct).toFixed(1)}%` : "—"}
                      </span>
                    </div>
                  ))}
                  {s.disk_tb_required != null && (
                    <div style={{ marginTop: 8, paddingTop: 6, borderTop: "1px solid var(--border, #e5e7eb)" }}>
                      <div style={{ fontSize: "0.7rem", color: "#6b7280" }}>Cinder storage needed</div>
                      <div style={{ fontWeight: 700, color: "#3b82f6" }}>{Number(s.disk_tb_required).toFixed(2)} TB</div>
                      <div style={{ fontSize: "0.66rem", color: "#9ca3af" }}>provision via storage backend</div>
                    </div>
                  )}
                  <div style={{ fontSize: "0.7rem", color: "#9ca3af", marginTop: 4 }}>
                    binding: <strong>{s.binding_dimension}</strong>
                  </div>
                </div>
              </div>
              {s.nodes_by_dimension && (
                <div style={{ fontSize: "0.8rem", color: "#6b7280", marginBottom: 8 }}>
                  Nodes by dimension — CPU: {s.nodes_by_dimension.cpu} · RAM: {s.nodes_by_dimension.ram}
                </div>
              )}
              {s.warnings?.length > 0 && (
                <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 6, padding: "10px 14px" }}>
                  <strong style={{ color: "#92400e", fontSize: "0.85rem" }}>⚠️ Capacity Warnings</strong>
                  <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                    {s.warnings.map((w: string, i: number) => (
                      <li key={i} style={{ fontSize: "0.82rem", color: "#92400e" }}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          );
        })()}
      </div>

      {/* Readiness Score + Run Button */}
      <div style={{ display: "flex", gap: 16, marginBottom: 16, alignItems: "stretch", flexWrap: "wrap" }}>
        {readinessScore != null && (
          <div style={{
            ...sectionStyle, margin: 0, textAlign: "center", minWidth: 160,
            borderLeft: `4px solid ${scoreColor(readinessScore)}`,
          }}>
            <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>Readiness Score</div>
            <div style={{
              fontSize: "2.5rem", fontWeight: 800,
              color: scoreColor(readinessScore),
            }}>{readinessScore.toFixed(1)}<span style={{ fontSize: "1rem" }}>/100</span></div>
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, justifyContent: "center" }}>
          <button onClick={runAnalysis} disabled={running} style={{ ...btnPrimary, fontSize: "1rem", padding: "12px 24px" }}>
            {running ? "⏳ Analysing…" : "🔍 Run Gap Analysis"}
          </button>
          <span style={{ fontSize: "0.8rem", color: "#6b7280", textAlign: "center" }}>
            Connects to PCD and checks flavors, networks, images, tenant mapping
          </span>
        </div>
        {!running && gaps.length > 0 && (
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ ...pillStyle, background: "#fee2e2", color: "#dc2626", fontSize: "0.9rem", padding: "6px 14px" }}>
              {gaps.filter(g => g.severity === "critical" && !g.resolved).length} critical
            </span>
            <span style={{ ...pillStyle, background: "#fffbeb", color: "#d97706", fontSize: "0.9rem", padding: "6px 14px" }}>
              {gaps.filter(g => g.severity === "warning" && !g.resolved).length} warnings
            </span>
            <span style={{ ...pillStyle, background: "#dcfce7", color: "#16a34a", fontSize: "0.9rem", padding: "6px 14px" }}>
              {resolvedGaps.length} resolved
            </span>
          </div>
        )}
      </div>

      {/* Gaps Table */}
      {gaps.length > 0 && (
        <div style={sectionStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <h3 style={{ margin: 0 }}>📋 Gaps ({unresolvedGaps.length} open)</h3>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={() => downloadGapReport("xlsx")}
                style={{ ...btnSecondary, fontSize: "0.83rem" }}>📥 Excel Report</button>
              <button onClick={() => downloadGapReport("pdf")}
                style={{ ...btnSecondary, fontSize: "0.83rem" }}>📑 PDF Report</button>
            </div>
          </div>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Type</th>
                <th style={thStyle}>Resource</th>
                <th style={thStyle}>Tenant</th>
                <th style={thStyle}>Severity</th>
                <th style={thStyle}>Why / Details</th>
                <th style={thStyle}>Resolution</th>
                <th style={thStyle}>Status</th>
              </tr>
            </thead>
            <tbody>
              {gaps.map((g, gi) => {
                const detailKeys = Object.keys(g.details || {}).filter(k => k !== "vms");
                return (
                  <tr key={g.id ?? `gap-${gi}`} style={{
                    borderBottom: "1px solid var(--border, #e5e7eb)",
                    opacity: g.resolved ? 0.5 : 1,
                  }}>
                    <td style={tdStyle}>
                      <span style={{ ...pillStyle, background: "#f3f4f6", color: "#374151" }}>
                        {g.gap_type.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td style={tdStyle}><code style={{ fontSize: "0.8rem" }}>{g.resource_name}</code></td>
                    <td style={tdStyle}>{g.tenant_name || <span style={{ color: "#9ca3af" }}>—</span>}</td>
                    <td style={tdStyle}>
                      <span style={{ ...pillStyle, ...severityStyle(g.severity) }}>
                        {g.severity}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, maxWidth: 260 }}>
                      {detailKeys.length > 0 ? (
                        <div style={{ fontSize: "0.78rem" }}>
                          {detailKeys.map((k, ki) => (
                            <div key={`${k}-${ki}`} style={{ display: "flex", gap: 4, marginBottom: 2 }}>
                              <span style={{ color: "#9ca3af", minWidth: 80, flexShrink: 0 }}>{k.replace(/_/g, " ")}:</span>
                              <span style={{ fontWeight: 600, color: "#374151", wordBreak: "break-all" }}>
                                {k === "ram_mb"
                                  ? `${Math.round(Number(g.details[k]) / 1024)} GB`
                                  : String(g.details[k])}
                              </span>
                            </div>
                          ))}
                          {g.details?.vms?.length > 0 && (
                            <details style={{ marginTop: 4 }}>
                              <summary style={{ cursor: "pointer", color: "#6b7280", fontSize: "0.75rem" }}>
                                {g.details.vms.length} affected VM{g.details.vms.length !== 1 ? "s" : ""}
                              </summary>
                              <div style={{ marginTop: 4, maxHeight: 100, overflowY: "auto" }}>
                                {g.details.vms.map((v: string, i: number) => (
                                  <div key={i} style={{ fontSize: "0.72rem", color: "#374151" }}>{v}</div>
                                ))}
                              </div>
                            </details>
                          )}
                        </div>
                      ) : (
                        <span style={{ color: "#9ca3af", fontSize: "0.78rem" }}>—</span>
                      )}
                    </td>
                    <td style={{ ...tdStyle, maxWidth: 280, fontSize: "0.82rem" }}>{g.resolution}</td>
                    <td style={tdStyle}>
                      {g.resolved ? (
                        <span style={{ ...pillStyle, background: "#dcfce7", color: "#16a34a" }}>✓ Resolved</span>
                      ) : (
                        <button onClick={() => resolveGap(g.id)}
                          style={{ ...btnSmall, background: "#16a34a", color: "#fff", fontSize: "0.78rem" }}>
                          Mark Resolved
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!running && gaps.length === 0 && (
        <div style={{ ...sectionStyle, textAlign: "center", color: "#6b7280", padding: 40 }}>
          No gaps found yet. Click "Run Gap Analysis" to check PCD readiness.
        </div>
      )}

      {/* Data Enrichment Sections */}
      <div style={{ marginTop: 24 }}>
        <h3 style={{ margin: "0 0 6px", fontSize: "1rem", color: "#374151" }}>📋 Pre-Migration Data Enrichment</h3>
        <p style={{ margin: "0 0 16px", color: "#6b7280", fontSize: "0.85rem" }}>
          Confirm flavor mappings and OS image requirements before migration execution.
        </p>
        <div style={{ ...sectionStyle, marginBottom: 16 }}>
          <FlavorStagingView projectId={projectId} />
        </div>
        <div style={sectionStyle}>
          <ImageRequirementsView projectId={projectId} />
        </div>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  Tiny Components                                                    */
/* ================================================================== */

function StatCard({ label, value }: { label: string; value: any }) {
  const display = value != null && value !== "" && !Number.isNaN(Number(value))
    ? Number(value).toLocaleString()
    : "—";
  return (
    <div style={{
      padding: 14, borderRadius: 8, textAlign: "center",
      background: "var(--card-bg, #f9fafb)", border: "1px solid var(--pf9-border)",
    }}>
      <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--color-text-primary)" }}>{display}</div>
      <div style={{ fontSize: "0.8rem", color: "var(--pf9-text-secondary)" }}>{label}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function osIcon(family: string): string {
  if (!family) return "❓";
  const f = family.toLowerCase();
  if (f.includes("linux") || f.includes("ubuntu") || f.includes("centos") || f.includes("rhel") || f.includes("debian")) return "🐧";
  if (f.includes("windows")) return "🪟";
  if (f.includes("freebsd") || f.includes("bsd")) return "😈";
  return "💻";
}

function riskPillColor(level: string): React.CSSProperties {
  if (level === "GREEN") return { background: "#dcfce7", color: "#16a34a" };
  if (level === "YELLOW") return { background: "#fef9c3", color: "#a16207" };
  return { background: "#fee2e2", color: "#dc2626" };
}

function modePillColor(mode: string): React.CSSProperties {
  if (mode === "warm_eligible") return { background: "#dcfce7", color: "#16a34a" };
  if (mode === "warm_risky") return { background: "#fef9c3", color: "#a16207" };
  return { background: "#fee2e2", color: "#dc2626" };
}

/* ================================================================== */
/*  Phase 4B — PreparePcdView                                        */
/* ================================================================== */

const TASK_TYPE_LABELS: Record<string, string> = {
  create_domain:  "🏛 Create Domain",
  create_project: "📁 Create Project",
  set_quotas:     "⚖️ Set Quotas",
  create_network: "🌐 Create Network",
  create_subnet:  "🔗 Create Subnet",
  create_flavor:  "🧊 Create Flavor",
  create_user:    "👤 Create User",
  assign_role:    "🔑 Assign Role",
};

function statusBadge(status: string): React.ReactNode {
  const styles: Record<string, React.CSSProperties> = {
    pending:  { background: "var(--pf9-bg-muted)",    color: "var(--pf9-text-secondary)", padding: "2px 8px", borderRadius: 10, fontSize: "0.75rem", fontWeight: 600 },
    running:  { background: "#dbeafe",                color: "#1d4ed8",                  padding: "2px 8px", borderRadius: 10, fontSize: "0.75rem", fontWeight: 600 },
    done:     { background: "var(--pf9-safe-bg)",     color: "var(--pf9-safe-text)",     padding: "2px 8px", borderRadius: 10, fontSize: "0.75rem", fontWeight: 600 },
    failed:   { background: "var(--pf9-danger-bg)",   color: "var(--pf9-danger-text)",   padding: "2px 8px", borderRadius: 10, fontSize: "0.75rem", fontWeight: 600 },
    skipped:  { background: "var(--pf9-warning-bg)",  color: "var(--pf9-warning-text)",  padding: "2px 8px", borderRadius: 10, fontSize: "0.75rem", fontWeight: 600 },
  };
  const icons: Record<string, string> = { pending: "⏳", running: "🔄", done: "✅", failed: "❌", skipped: "⏭" };
  return <span style={styles[status] || styles.pending}>{icons[status] || "•"} {status}</span>;
}

function PreparePcdView({ projectId }: { projectId: number }) {
  const [readiness, setReadiness] = useState<any>(null);
  const [tasks, setTasks]         = useState<any[]>([]);
  const [counts, setCounts]       = useState<Record<string, number>>({});
  const [loading, setLoading]     = useState(false);
  const [generating, setGenerating] = useState(false);
  const [running, setRunning]     = useState(false);
  const [expandedError, setExpandedError] = useState<number | null>(null);
  const [msg, setMsg]             = useState("");

  const loadReadiness = async () => {
    try {
      const r = await apiFetch<any>(`/api/migration/projects/${projectId}/prep-readiness`);
      setReadiness(r);
    } catch { /* ignore */ }
  };

  const loadTasks = async () => {
    setLoading(true);
    try {
      const r = await apiFetch<{ tasks: any[]; counts: Record<string, number> }>(`/api/migration/projects/${projectId}/prep-tasks`);
      setTasks(r.tasks || []);
      setCounts(r.counts || {});
    } finally { setLoading(false); }
  };

  React.useEffect(() => {
    loadReadiness();
    loadTasks();
  }, [projectId]);

  // Auto-refresh while tasks are running
  React.useEffect(() => {
    if (!readiness) return;
    if ((readiness.tasks_running || 0) === 0) return;
    const t = setTimeout(() => { loadReadiness(); loadTasks(); }, 3000);
    return () => clearTimeout(t);
  }, [readiness]);

  const generatePlan = async () => {
    setGenerating(true); setMsg("");
    try {
      const r = await apiFetch<any>(`/api/migration/projects/${projectId}/prepare`, { method: "POST" });
      setMsg(`✅ Generated ${r.tasks_generated} tasks`);
      loadReadiness(); loadTasks();
    } catch (e: any) {
      setMsg(`❌ ${e.message || "Failed to generate"}`);
    } finally { setGenerating(false); }
  };

  const runAll = async () => {
    setRunning(true); setMsg("");
    try {
      const r = await apiFetch<any>(`/api/migration/projects/${projectId}/prepare/run`, { method: "POST" });
      setMsg(`Done: ${r.done} created · ${r.skipped} skipped · ${r.failed} failed`);
      loadReadiness(); loadTasks();
    } catch (e: any) {
      setMsg(`❌ ${e.message || "Failed"}`);
    } finally { setRunning(false); }
  };

  const executeTask = async (taskId: number) => {
    setMsg("");
    try {
      await apiFetch<any>(`/api/migration/projects/${projectId}/prep-tasks/${taskId}/execute`, { method: "POST" });
      loadReadiness(); loadTasks();
    } catch (e: any) { setMsg(`❌ Task ${taskId}: ${e.message}`); }
  };

  const rollbackTask = async (taskId: number) => {
    if (!confirm("Rollback this task? This will delete the created PCD resource.")) return;
    setMsg("");
    try {
      const r = await apiFetch<any>(`/api/migration/projects/${projectId}/prep-tasks/${taskId}/rollback`, { method: "POST" });
      setMsg(`↩ ${r.message}`);
      loadReadiness(); loadTasks();
    } catch (e: any) { setMsg(`❌ ${e.message}`); }
  };

  const hasPending = tasks.some(t => t.status === "pending" || t.status === "failed");
  const allDone    = tasks.length > 0 && tasks.every(t => t.status === "done");

  return (
    <div>
      {/* Readiness panel */}
      <div style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Phase 4A Readiness Check</h3>
        {readiness ? (
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10, marginBottom: 16 }}>
              {(readiness.items || []).map((item: any) => (
                <div key={item.key} style={{
                  padding: 12, borderRadius: 6,
                  background: item.ready ? "var(--pf9-safe-bg)"    : "var(--pf9-danger-bg)",
                  border:     `1px solid ${item.ready ? "var(--pf9-safe-border)" : "var(--pf9-danger-border)"}`,
                }}>
                  <div style={{ fontWeight: 600, marginBottom: 4, color: item.ready ? "var(--pf9-safe-text)" : "var(--pf9-danger-text)" }}>
                    {item.ready ? "✅" : "❌"} {item.label}
                  </div>
                  <div style={{ fontSize: "0.8rem", color: "var(--pf9-text-secondary)" }}>{item.message}</div>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <button onClick={generatePlan} disabled={generating}
                style={{ ...btnPrimary, opacity: generating ? 0.6 : 1 }}>
                {generating ? "Generating…" : "🔄 Generate Plan"}
              </button>
              {hasPending && (
                <button onClick={runAll} disabled={running}
                  style={{ ...btnPrimary, background: running ? "#6b7280" : "#10b981", opacity: running ? 0.7 : 1 }}>
                  {running ? "Running…" : "▶ Run All"}
                </button>
              )}
              {tasks.length > 0 && (
                <span style={{ fontSize: "0.85rem", color: "var(--pf9-text-secondary)" }}>
                  {counts.done || 0} done · {counts.failed || 0} failed · {counts.pending || 0} pending · {counts.running || 0} running
                </span>
              )}
              {allDone && <span style={{ color: "var(--pf9-safe-text)", fontWeight: 600 }}>🎉 All tasks complete — ready for vJailbreak handoff</span>}
            </div>
            {msg && <div style={{ marginTop: 10, padding: "8px 12px", borderRadius: 6,
              background: msg.startsWith("❌") ? "var(--pf9-danger-bg)" : "var(--pf9-safe-bg)",
              color: msg.startsWith("❌") ? "var(--pf9-danger-text)" : "var(--pf9-safe-text)",
              border: `1px solid ${msg.startsWith("❌") ? "var(--pf9-danger-border)" : "var(--pf9-safe-border)"}`,
              fontSize: "0.85rem" }}>{msg}</div>}
          </div>
        ) : <div style={{ color: "var(--pf9-text-secondary)" }}>Loading…</div>}
      </div>

      {/* Task table */}
      {tasks.length > 0 && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0, marginBottom: 12 }}>Provisioning Tasks</h3>
          {loading && <div style={{ color: "var(--pf9-text-secondary)", marginBottom: 8 }}>Refreshing…</div>}
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>#</th>
                <th style={thStyle}>Type</th>
                <th style={thStyle}>Task</th>
                <th style={thStyle}>Tenant</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Resource ID</th>
                <th style={thStyle}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t, i) => (
                <React.Fragment key={t.id}>
                  <tr style={{ borderBottom: "1px solid var(--pf9-border)", background: t.status === "failed" ? "var(--pf9-danger-bg)" : undefined }}>
                    <td style={tdStyle}><span style={{ color: "var(--pf9-text-secondary)", fontSize: "0.75rem" }}>{i + 1}</span></td>
                    <td style={tdStyle}><span style={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>{TASK_TYPE_LABELS[t.task_type] || t.task_type}</span></td>
                    <td style={tdStyle}><span style={{ fontSize: "0.85rem" }}>{t.task_name}</span></td>
                    <td style={tdStyle}><span style={{ fontSize: "0.8rem", color: "var(--pf9-text-secondary)" }}>{t.tenant_name || "—"}</span></td>
                    <td style={tdStyle}>{statusBadge(t.status)}</td>
                    <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.75rem", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {t.resource_id ? <span title={t.resource_id}>{t.resource_id.slice(0, 24)}…</span> : "—"}
                    </td>
                    <td style={tdStyle}>
                      <div style={{ display: "flex", gap: 4 }}>
                        {(t.status === "pending" || t.status === "failed") && (
                          <button onClick={() => executeTask(t.id)}
                            style={{ ...btnPrimary, padding: "3px 8px", fontSize: "0.75rem" }}>▶ Run</button>
                        )}
                        {t.status === "done" && ["create_domain","create_project","create_network","create_flavor","create_user"].includes(t.task_type) && (
                          <button onClick={() => rollbackTask(t.id)}
                            style={{ ...btnSecondary, padding: "3px 8px", fontSize: "0.75rem", color: "var(--pf9-danger-text)" }}>↩</button>
                        )}
                        {t.error_message && (
                          <button onClick={() => setExpandedError(expandedError === t.id ? null : t.id)}
                            style={{ ...btnSecondary, padding: "3px 8px", fontSize: "0.75rem" }}>ℹ</button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {expandedError === t.id && t.error_message && (
                    <tr>
                      <td colSpan={7} style={{ padding: "6px 12px", background: "var(--pf9-danger-bg)" }}>
                        <code style={{ fontSize: "0.8rem", color: "var(--pf9-danger-text)" }}>{t.error_message}</code>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tasks.length === 0 && readiness && (
        <div style={{ ...sectionStyle, textAlign: "center", color: "var(--pf9-text-secondary)", padding: 40 }}>
          No tasks yet. Click "🔄 Generate Plan" to build the provisioning task list.
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  Phase 4A — FlavorStagingView  (4A.2)                             */
/* ================================================================== */

function FlavorStagingView({ projectId }: { projectId: number }) {
  const [flavors, setFlavors] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState<number | null>(null);
  const [showFR, setShowFR] = useState(false);
  const [frFind, setFrFind] = useState("");
  const [frReplace, setFrReplace] = useState("");
  const [frPreview, setFrPreview] = useState<any[] | null>(null);
  const [frLoading, setFrLoading] = useState(false);
  const [frApplied, setFrApplied] = useState(false);
  const [confirmingAll, setConfirmingAll] = useState(false);
  const [matchingPCD, setMatchingPCD] = useState(false);
  const [matchResult, setMatchResult] = useState<{ matched: number; unmatched: number; gaps_resolved: number; error?: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await apiFetch<{ flavors: any[] }>(`/api/migration/projects/${projectId}/flavor-staging`);
      setFlavors(r.flavors ?? []);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const r = await apiFetch<{ inserted: number; updated: number }>(`/api/migration/projects/${projectId}/flavor-staging/refresh`, { method: "POST" });
      await load();
      alert(`✓ Flavor staging refreshed: ${r.inserted} inserted, ${r.updated} updated.`);
    } catch (e: any) { setError(e.message); }
    finally { setRefreshing(false); }
  };

  const saveFlavor = async (id: number, fields: Record<string, any>) => {
    setSaving(id);
    try {
      await apiFetch(`/api/migration/flavor-staging/${id}`, { method: "PATCH", body: JSON.stringify(fields) });
      setEditing(prev => { const n = { ...prev }; delete n[id]; return n; });
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setSaving(null); }
  };

  const runFR = async (apply: boolean) => {
    if (!frFind.trim()) return;
    setFrLoading(true);
    setFrApplied(false);
    try {
      const r = await apiFetch<{ preview?: any[]; affected_count?: number }>(
        `/api/migration/projects/${projectId}/flavor-staging/bulk-rename`,
        { method: "POST", body: JSON.stringify({ find: frFind, replace: frReplace, preview_only: !apply }) }
      );
      if (apply) { setFrApplied(true); setFrPreview(null); await load(); }
      else { setFrPreview(r.preview ?? []); }
    } catch (e: any) { setError(e.message); }
    finally { setFrLoading(false); }
  };

  const confirmAll = async () => {
    const targets = flavors.filter(f => !f.skip && !f.confirmed);
    if (!targets.length) return;
    setConfirmingAll(true);
    setError("");
    try {
      await Promise.all(targets.map(f =>
        apiFetch(`/api/migration/flavor-staging/${f.id}`, {
          method: "PATCH", body: JSON.stringify({ confirmed: true })
        })
      ));
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setConfirmingAll(false); }
  };

  const matchFromPcd = async () => {
    setMatchingPCD(true);
    setMatchResult(null);
    setError("");
    try {
      const r = await apiFetch<{ matched: number; unmatched: number; gaps_resolved: number; pcd_connected: boolean; error?: string }>(
        `/api/migration/projects/${projectId}/flavor-staging/match-from-pcd`,
        { method: "POST" }
      );
      setMatchResult({ matched: r.matched, unmatched: r.unmatched, gaps_resolved: r.gaps_resolved ?? 0, error: r.error });
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setMatchingPCD(false); }
  };

  const readyCount = flavors.filter(f => f.confirmed && !f.skip).length;
  const totalCount = flavors.filter(f => !f.skip).length;

  if (loading) return <div style={{ color: "#6b7280", padding: 12, fontSize: "0.85rem" }}>Loading flavor staging...</div>;

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div>
          <h4 style={{ margin: 0, fontSize: "0.95rem" }}>🍦 Flavor Staging</h4>
          <p style={{ margin: "3px 0 0", color: "#6b7280", fontSize: "0.8rem" }}>
            Map each VM shape to a PCD flavor. Refresh to sync from VM inventory.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{
            padding: "4px 10px", borderRadius: 6, fontSize: "0.78rem", fontWeight: 600,
            background: readyCount === totalCount && totalCount > 0 ? "#dcfce7" : "#fff7ed",
            color: readyCount === totalCount && totalCount > 0 ? "#15803d" : "#9a3412",
            border: `1px solid ${readyCount === totalCount && totalCount > 0 ? "#86efac" : "#fdba74"}`,
          }}>
            {readyCount}/{totalCount} confirmed
          </span>
          <button onClick={() => { setShowFR(!showFR); setFrPreview(null); setFrApplied(false); }}
            style={{ ...btnSecondary, fontSize: "0.8rem", padding: "4px 10px",
              background: showFR ? "#eff6ff" : undefined }}>
            🔍 F&amp;R
          </button>
          <button onClick={matchFromPcd} disabled={matchingPCD}
            style={{ ...btnSecondary, fontSize: "0.8rem", padding: "4px 10px",
              background: "#0ea5e9", color: "#fff", opacity: matchingPCD ? 0.7 : 1 }}>
            {matchingPCD ? "⏳ Matching..." : "🔗 Match PCD"}
          </button>
          <button
            onClick={confirmAll}
            disabled={confirmingAll || flavors.filter(f => !f.skip && !f.confirmed).length === 0}
            style={{ ...btnSecondary, fontSize: "0.8rem", padding: "4px 10px",
              background: "#16a34a", color: "#fff", opacity: confirmingAll ? 0.7 : 1 }}>
            {confirmingAll ? "⏳ Confirming..." : "✓ Confirm All"}
          </button>
          <button onClick={refresh} disabled={refreshing}
            style={{ ...btnSecondary, fontSize: "0.8rem", padding: "4px 10px" }}>
            {refreshing ? "⏳..." : "🔄 Refresh from VMs"}
          </button>
        </div>
      </div>
      {matchResult && (
        <div style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 6, fontSize: "0.82rem",
          background: matchResult.error ? "#fef2f2" : "#f0fdf4",
          border: `1px solid ${matchResult.error ? "#fca5a5" : "#86efac"}`,
          color: matchResult.error ? "#dc2626" : "#15803d",
          display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>
            {matchResult.error
              ? `⚠️ PCD match failed: ${matchResult.error}`
              : `🔗 PCD match complete — ${matchResult.matched} matched (✓ exists — Phase 4B will reuse), ${matchResult.unmatched} unmatched (✓ new — Phase 4B will create)${matchResult.gaps_resolved > 0 ? ` · ${matchResult.gaps_resolved} flavor gap${matchResult.gaps_resolved !== 1 ? "s" : ""} auto-resolved` : ""}`
            }
          </span>
          <button onClick={() => setMatchResult(null)}
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1rem", lineHeight: 1 }}>×</button>
        </div>
      )}
      {showFR && (
        <div style={{ marginBottom: 12, padding: 12, background: "#eff6ff",
          border: "1px solid #bfdbfe", borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 8, color: "#1e40af", fontSize: "0.85rem" }}>
            🔍 Find &amp; Replace — Target Flavor Name
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
            <div>
              <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 2 }}>Find</label>
              <input value={frFind} onChange={e => { setFrFind(e.target.value); setFrPreview(null); }}
                placeholder="e.g. m1.small" style={{ ...inputStyle, padding: "4px 8px", fontSize: "0.82rem", width: 160 }} />
            </div>
            <div>
              <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 2 }}>Replace with</label>
              <input value={frReplace} onChange={e => { setFrReplace(e.target.value); setFrPreview(null); }}
                placeholder="leave empty to strip" style={{ ...inputStyle, padding: "4px 8px", fontSize: "0.82rem", width: 180 }} />
            </div>
            <button onClick={() => runFR(false)} disabled={frLoading || !frFind.trim()}
              style={{ ...btnSecondary, fontSize: "0.8rem", padding: "4px 10px" }}>
              {frLoading && !frApplied ? "⏳..." : "👁 Preview"}
            </button>
          </div>
          {frApplied && <div style={{ color: "#15803d", fontSize: "0.82rem", marginTop: 6, fontWeight: 500 }}>✓ Applied!</div>}
          {frPreview !== null && frPreview.length === 0 && (
            <div style={{ color: "#6b7280", fontSize: "0.82rem", marginTop: 6 }}>No matches found.</div>
          )}
          {frPreview !== null && frPreview.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: "0.78rem", color: "#374151", marginBottom: 4 }}>
                {frPreview.length} flavor{frPreview.length !== 1 ? "s" : ""} will be affected.
              </div>
              <div style={{ overflowX: "auto", maxHeight: 180, overflowY: "auto", marginBottom: 8 }}>
                <table style={{ ...tableStyle, fontSize: "0.78rem" }}>
                  <thead><tr>
                    <th style={thStyle}>Shape</th>
                    <th style={thStyle}>Before</th>
                    <th style={thStyle}>After</th>
                  </tr></thead>
                  <tbody>
                    {frPreview.map((row: any) => (
                      <tr key={row.id} style={{ borderBottom: "1px solid #e5e7eb" }}>
                        <td style={{ ...tdStyle, fontFamily: "monospace" }}>{row.source_shape}</td>
                        <td style={{ ...tdStyle, color: "#dc2626" }}>{row.old_value}</td>
                        <td style={{ ...tdStyle, color: "#16a34a" }}>{row.new_value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button onClick={() => runFR(true)} disabled={frLoading}
                style={{ ...btnPrimary, fontSize: "0.82rem", padding: "5px 12px" }}>
                {frLoading ? "⏳..." : `✅ Apply to ${frPreview.length} flavor${frPreview.length !== 1 ? "s" : ""}`}
              </button>
            </div>
          )}
        </div>
      )}
      {error && <div style={{ ...alertError, fontSize: "0.82rem", marginBottom: 8 }}>{error}</div>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ ...tableStyle, fontSize: "0.82rem" }}>
          <thead>
            <tr>
              <th style={thStyle}>VM Shape (Source)</th>
              <th style={{ ...thStyle, width: 55, textAlign: "center" }}>VMs</th>
              <th style={thStyle}>Target PCD Flavor Name</th>
              <th style={{ ...thStyle, width: 100 }}>PCD Flavor ID</th>
              <th style={{ ...thStyle, width: 75, textAlign: "center" }}>Skip</th>
              <th style={{ ...thStyle, width: 90, textAlign: "center" }}>Status</th>
              <th style={{ ...thStyle, width: 80 }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {flavors.map(f => {
              const editName = editing[f.id];
              const current = editName !== undefined ? editName : (f.target_flavor_name || "");
              const isDirty = editName !== undefined && editName !== (f.target_flavor_name || "");
              return (
                <tr key={f.id} style={{ borderBottom: "1px solid #e5e7eb",
                  background: f.skip ? "#f9fafb" : f.confirmed ? undefined : "#fffbeb",
                  opacity: f.skip ? 0.6 : 1 }}>
                  <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.78rem" }}>{f.source_shape}</td>
                  <td style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>{f.vm_count ?? 0}</td>
                  <td style={tdStyle}>
                    {!f.skip && (
                      <input value={current}
                        onChange={e => setEditing(prev => ({ ...prev, [f.id]: e.target.value }))}
                        placeholder="e.g. m1.medium"
                        style={{ ...inputStyle, padding: "3px 6px", fontSize: "0.8rem", width: "100%",
                          background: isDirty ? "#eff6ff" : undefined }}
                        onKeyDown={e => { if (e.key === "Enter") saveFlavor(f.id, { target_flavor_name: current, confirmed: !isDirty }); }}
                      />
                    )}
                  </td>
                  <td style={{ ...tdStyle, fontSize: "0.72rem", color: f.pcd_flavor_id ? "#0369a1" : "#6b7280", fontFamily: "monospace" }}>
                    {f.pcd_flavor_id
                      ? <span title={f.pcd_flavor_id}>🔗 {f.pcd_flavor_id.slice(0, 8)}…</span>
                      : "—"}
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    <input type="checkbox" checked={!!f.skip}
                      onChange={e => saveFlavor(f.id, { skip: e.target.checked, confirmed: false })} />
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    {f.skip
                      ? <span style={{ ...pillStyle, background: "#f3f4f6", color: "#6b7280", fontSize: "0.7rem" }}>skip</span>
                      : f.pcd_flavor_id && f.confirmed
                        ? <span style={{ ...pillStyle, background: "#e0f2fe", color: "#0369a1", fontSize: "0.7rem" }}>✓ exists</span>
                        : f.confirmed
                          ? <span style={{ ...pillStyle, background: "#dcfce7", color: "#15803d", fontSize: "0.7rem" }}>✓ new</span>
                          : <span style={{ ...pillStyle, background: "#fff7ed", color: "#ea580c", fontSize: "0.7rem" }}>pending</span>
                    }
                  </td>
                  <td style={tdStyle}>
                    {!f.skip && (
                      <button
                        onClick={() => saveFlavor(f.id, { target_flavor_name: current, confirmed: true })}
                        disabled={saving === f.id}
                        style={{ ...btnSmall, background: isDirty ? "#2563eb" : "#16a34a", color: "#fff", fontSize: "0.72rem" }}>
                        {saving === f.id ? "..." : isDirty ? "Save" : "✓"}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {flavors.length === 0 && (
              <tr><td colSpan={7} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
                No flavor staging data. Click "Refresh from VMs" to populate.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  Phase 4A — ImageRequirementsView  (4A.3)                         */
/* ================================================================== */

function ImageRequirementsView({ projectId }: { projectId: number }) {
  const [images, setImages] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Record<number, { glance_image_name?: string; glance_image_id?: string; notes?: string }>>({});
  const [saving, setSaving] = useState<number | null>(null);
  const [confirmingAll, setConfirmingAll] = useState(false);
  const [showFR, setShowFR] = useState(false);
  const [frFind, setFrFind] = useState("");
  const [frReplace, setFrReplace] = useState("");
  const [frPreview, setFrPreview] = useState<any[] | null>(null);
  const [frApplying, setFrApplying] = useState(false);
  const [frApplied, setFrApplied] = useState(false);
  const [matchingPCD, setMatchingPCD] = useState(false);
  const [matchResult, setMatchResult] = useState<{ matched: number; unmatched: number; gaps_resolved: number; error?: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await apiFetch<{ images: any[] }>(`/api/migration/projects/${projectId}/image-requirements`);
      setImages(r.images ?? []);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const r = await apiFetch<{ inserted: number; updated: number }>(`/api/migration/projects/${projectId}/image-requirements/refresh`, { method: "POST" });
      await load();
      alert(`✓ Image requirements refreshed: ${r.inserted} inserted, ${r.updated} updated.`);
    } catch (e: any) { setError(e.message); }
    finally { setRefreshing(false); }
  };

  const saveImage = async (id: number, fields: Record<string, any>) => {
    setSaving(id);
    try {
      await apiFetch(`/api/migration/image-requirements/${id}`, { method: "PATCH", body: JSON.stringify(fields) });
      setEditing(prev => { const n = { ...prev }; delete n[id]; return n; });
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setSaving(null); }
  };

  const confirmAll = async () => {
    const targets = images.filter(i => !i.confirmed);
    if (!targets.length) return;
    setConfirmingAll(true);
    setError("");
    try {
      await Promise.all(targets.map(img =>
        apiFetch(`/api/migration/image-requirements/${img.id}`, {
          method: "PATCH", body: JSON.stringify({ confirmed: true })
        })
      ));
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setConfirmingAll(false); }
  };

  const previewFR = () => {
    if (!frFind.trim()) return;
    const result = images
      .filter(i => (i.glance_image_name || "").includes(frFind))
      .map(i => ({
        id: i.id,
        os_family: i.os_family,
        old_value: i.glance_image_name || "",
        new_value: (i.glance_image_name || "").split(frFind).join(frReplace),
      }));
    setFrPreview(result);
    setFrApplied(false);
  };

  const applyFR = async () => {
    if (!frPreview || !frPreview.length) return;
    setFrApplying(true);
    setError("");
    try {
      await Promise.all(frPreview.map(row =>
        apiFetch(`/api/migration/image-requirements/${row.id}`, {
          method: "PATCH", body: JSON.stringify({ glance_image_name: row.new_value })
        })
      ));
      setFrApplied(true);
      setFrPreview(null);
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setFrApplying(false); }
  };

  const matchFromPcd = async () => {
    setMatchingPCD(true);
    setMatchResult(null);
    setError("");
    try {
      const r = await apiFetch<{ matched: number; unmatched: number; gaps_resolved: number; pcd_connected: boolean; error?: string }>(
        `/api/migration/projects/${projectId}/image-requirements/match-from-pcd`,
        { method: "POST" }
      );
      if (!r.pcd_connected) { setError(r.error || "Could not connect to PCD"); return; }
      setMatchResult({ matched: r.matched, unmatched: r.unmatched, gaps_resolved: r.gaps_resolved ?? 0, error: r.error });
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setMatchingPCD(false); }
  };

  const readyCount = images.filter(i => i.confirmed).length;

  if (loading) return <div style={{ color: "#6b7280", padding: 12, fontSize: "0.85rem" }}>Loading image requirements...</div>;

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div>
          <h4 style={{ margin: 0, fontSize: "0.95rem" }}>🖼 Image Requirements</h4>
          <p style={{ margin: "3px 0 0", color: "#6b7280", fontSize: "0.8rem" }}>
            Confirm Glance image for each OS family found in the VM inventory.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{
            padding: "4px 10px", borderRadius: 6, fontSize: "0.78rem", fontWeight: 600,
            background: readyCount === images.length && images.length > 0 ? "#dcfce7" : "#fff7ed",
            color: readyCount === images.length && images.length > 0 ? "#15803d" : "#9a3412",
            border: `1px solid ${readyCount === images.length && images.length > 0 ? "#86efac" : "#fdba74"}`,
          }}>
            {readyCount}/{images.length} confirmed
          </span>
          <button onClick={() => { setShowFR(!showFR); setFrPreview(null); setFrApplied(false); }}
            style={{ ...btnSecondary, fontSize: "0.8rem", padding: "4px 10px",
              background: showFR ? "#eff6ff" : undefined }}>
            🔍 F&amp;R
          </button>
          <button onClick={matchFromPcd} disabled={matchingPCD}
            style={{ ...btnSecondary, fontSize: "0.8rem", padding: "4px 10px",
              background: "#0ea5e9", color: "#fff", opacity: matchingPCD ? 0.7 : 1 }}>
            {matchingPCD ? "⏳ Matching..." : "🔗 Match PCD"}
          </button>
          <button
            onClick={confirmAll}
            disabled={confirmingAll || images.filter(i => !i.confirmed).length === 0}
            style={{ ...btnSecondary, fontSize: "0.8rem", padding: "4px 10px",
              background: "#16a34a", color: "#fff", opacity: confirmingAll ? 0.7 : 1 }}>
            {confirmingAll ? "⏳ Confirming..." : "✓ Confirm All"}
          </button>
          <button onClick={refresh} disabled={refreshing}
            style={{ ...btnSecondary, fontSize: "0.8rem", padding: "4px 10px" }}>
            {refreshing ? "⏳..." : "🔄 Refresh from VMs"}
          </button>
        </div>
      </div>
      {matchResult && (
        <div style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 6, fontSize: "0.82rem",
          background: matchResult.error ? "#fef2f2" : "#f0fdf4",
          border: `1px solid ${matchResult.error ? "#fca5a5" : "#86efac"}`,
          color: matchResult.error ? "#dc2626" : "#15803d",
          display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>
            {matchResult.error
              ? `⚠️ PCD match failed: ${matchResult.error}`
              : `🔗 PCD match complete — ${matchResult.matched} matched (✓ exists), ${matchResult.unmatched} unmatched (set manually)${matchResult.gaps_resolved > 0 ? ` · ${matchResult.gaps_resolved} image gap${matchResult.gaps_resolved !== 1 ? "s" : ""} auto-resolved` : ""}`
            }
          </span>
          <button onClick={() => setMatchResult(null)}
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1rem", lineHeight: 1 }}>×</button>
        </div>
      )}
      {showFR && (
        <div style={{ marginBottom: 12, padding: 12, background: "#eff6ff",
          border: "1px solid #bfdbfe", borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 8, color: "#1e40af", fontSize: "0.85rem" }}>
            🔍 Find &amp; Replace — Glance Image Name
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
            <div>
              <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 2 }}>Find</label>
              <input value={frFind} onChange={e => { setFrFind(e.target.value); setFrPreview(null); setFrApplied(false); }}
                placeholder="e.g. ubuntu" style={{ ...inputStyle, padding: "4px 8px", fontSize: "0.82rem", width: 160 }} />
            </div>
            <div>
              <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 2 }}>Replace with</label>
              <input value={frReplace} onChange={e => { setFrReplace(e.target.value); setFrPreview(null); }}
                placeholder="leave empty to strip" style={{ ...inputStyle, padding: "4px 8px", fontSize: "0.82rem", width: 180 }} />
            </div>
            <button onClick={previewFR} disabled={!frFind.trim()}
              style={{ ...btnSecondary, fontSize: "0.8rem", padding: "4px 10px" }}>
              👁 Preview
            </button>
          </div>
          {frApplied && <div style={{ color: "#15803d", fontSize: "0.82rem", marginTop: 6, fontWeight: 500 }}>✓ Applied!</div>}
          {frPreview !== null && frPreview.length === 0 && (
            <div style={{ color: "#6b7280", fontSize: "0.82rem", marginTop: 6 }}>No matches found.</div>
          )}
          {frPreview !== null && frPreview.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: "0.78rem", color: "#374151", marginBottom: 4 }}>
                {frPreview.length} image name{frPreview.length !== 1 ? "s" : ""} will be affected.
              </div>
              <div style={{ overflowX: "auto", maxHeight: 180, overflowY: "auto", marginBottom: 8 }}>
                <table style={{ ...tableStyle, fontSize: "0.78rem" }}>
                  <thead><tr>
                    <th style={thStyle}>OS Family</th>
                    <th style={thStyle}>Before</th>
                    <th style={thStyle}>After</th>
                  </tr></thead>
                  <tbody>
                    {frPreview.map(row => (
                      <tr key={row.id} style={{ borderBottom: "1px solid #e5e7eb" }}>
                        <td style={{ ...tdStyle, fontFamily: "monospace" }}>{row.os_family}</td>
                        <td style={{ ...tdStyle, color: "#dc2626" }}>{row.old_value}</td>
                        <td style={{ ...tdStyle, color: "#16a34a" }}>{row.new_value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button onClick={applyFR} disabled={frApplying}
                style={{ ...btnPrimary, fontSize: "0.82rem", padding: "5px 12px" }}>
                {frApplying ? "⏳..." : `✅ Apply to ${frPreview.length} image${frPreview.length !== 1 ? "s" : ""}`}
              </button>
            </div>
          )}
        </div>
      )}
      {error && <div style={{ ...alertError, fontSize: "0.82rem", marginBottom: 8 }}>{error}</div>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ ...tableStyle, fontSize: "0.82rem" }}>
          <thead>
            <tr>
              <th style={thStyle}>OS Family</th>
              <th style={thStyle}>Version Hint</th>
              <th style={{ ...thStyle, width: 55, textAlign: "center" }}>VMs</th>
              <th style={thStyle}>Glance Image Name</th>
              <th style={{ ...thStyle, width: 130 }}>Glance Image ID</th>
              <th style={{ ...thStyle, width: 90, textAlign: "center" }}>Status</th>
              <th style={{ ...thStyle, width: 80 }}>Action</th>
            </tr>
          </thead>
          <tbody>
            {images.map(img => {
              const ed = editing[img.id] ?? {};
              const nameVal = ed.glance_image_name !== undefined ? ed.glance_image_name : (img.glance_image_name || "");
              const idVal = ed.glance_image_id !== undefined ? ed.glance_image_id : (img.glance_image_id || "");
              const isDirty = (ed.glance_image_name !== undefined && ed.glance_image_name !== (img.glance_image_name || ""))
                           || (ed.glance_image_id !== undefined && ed.glance_image_id !== (img.glance_image_id || ""));
              return (
                <tr key={img.id} style={{ borderBottom: "1px solid #e5e7eb",
                  background: img.confirmed ? undefined : "#fffbeb" }}>
                  <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.8rem" }}>{img.os_family || "unknown"}</td>
                  <td style={{ ...tdStyle, color: "#6b7280", fontSize: "0.78rem" }}>{img.os_version_hint || "—"}</td>
                  <td style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>{img.vm_count ?? 0}</td>
                  <td style={tdStyle}>
                    <input value={nameVal}
                      onChange={e => setEditing(prev => ({ ...prev, [img.id]: { ...(prev[img.id] ?? {}), glance_image_name: e.target.value } }))}
                      placeholder="e.g. ubuntu-22.04-cloud"
                      style={{ ...inputStyle, padding: "3px 6px", fontSize: "0.8rem", width: "100%",
                        background: (ed.glance_image_name !== undefined && ed.glance_image_name !== (img.glance_image_name || "")) ? "#eff6ff" : undefined }}
                    />
                  </td>
                  <td style={tdStyle}>
                    <input value={idVal}
                      onChange={e => setEditing(prev => ({ ...prev, [img.id]: { ...(prev[img.id] ?? {}), glance_image_id: e.target.value } }))}
                      placeholder="UUID or leave blank"
                      style={{ ...inputStyle, padding: "3px 6px", fontSize: "0.78rem", width: "100%", fontFamily: "monospace",
                        background: (ed.glance_image_id !== undefined && ed.glance_image_id !== (img.glance_image_id || "")) ? "#eff6ff" : undefined }}
                    />
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    {img.confirmed && img.glance_image_id
                      ? <span style={{ ...pillStyle, background: "#e0f2fe", color: "#0369a1", fontSize: "0.7rem" }}>✓ exists</span>
                      : img.confirmed
                        ? <span style={{ ...pillStyle, background: "#dcfce7", color: "#15803d", fontSize: "0.7rem" }}>✓ new</span>
                        : <span style={{ ...pillStyle, background: "#fff7ed", color: "#ea580c", fontSize: "0.7rem" }}>pending</span>}
                  </td>
                  <td style={tdStyle}>
                    <button
                      onClick={() => saveImage(img.id, { glance_image_name: nameVal, glance_image_id: idVal || null, confirmed: true })}
                      disabled={saving === img.id}
                      style={{ ...btnSmall, background: isDirty ? "#2563eb" : "#16a34a", color: "#fff", fontSize: "0.72rem" }}>
                      {saving === img.id ? "..." : isDirty ? "Save" : "✓"}
                    </button>
                  </td>
                </tr>
              );
            })}
            {images.length === 0 && (
              <tr><td colSpan={7} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
                No image requirements. Click "Refresh from VMs" to populate.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  Phase 4A — TenantUsersView  (4A.4)                               */
/* ================================================================== */

function TenantUsersView({ projectId }: { projectId: number }) {
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState<number | null>(null);
  const [editRow, setEditRow] = useState<Record<number, any>>({});
  const [showAdd, setShowAdd] = useState(false);
  const [newUser, setNewUser] = useState({ tenant_id: 0, username: "", email: "", role: "member", notes: "" });

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const r = await apiFetch<{ users: any[]; tenant_count: number; confirmed_tenant_count: number }>(
        `/api/migration/projects/${projectId}/tenant-users`);
      setUsers(r.users ?? []);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const seed = async () => {
    if (!window.confirm("Auto-create service accounts for all tenants in this project?")) return;
    setSeeding(true);
    try {
      const r = await apiFetch<{ created: number; skipped: number }>(
        `/api/migration/projects/${projectId}/tenant-users/seed-service-accounts`, { method: "POST" });
      await load();
      alert(`✓ Seeded ${r.created} service account(s). ${r.skipped} already existed.`);
    } catch (e: any) { setError(e.message); }
    finally { setSeeding(false); }
  };

  const saveEdit = async (id: number) => {
    setSaving(id);
    try {
      await apiFetch(`/api/migration/tenant-users/${id}`, { method: "PATCH", body: JSON.stringify(editRow[id]) });
      setEditRow(prev => { const n = { ...prev }; delete n[id]; return n; });
      await load();
    } catch (e: any) { setError(e.message); }
    finally { setSaving(null); }
  };

  const deleteUser = async (id: number) => {
    if (!window.confirm("Delete this user definition?")) return;
    try {
      await apiFetch(`/api/migration/tenant-users/${id}`, { method: "DELETE" });
      await load();
    } catch (e: any) { setError(e.message); }
  };

  const addUser = async () => {
    if (!newUser.tenant_id || !newUser.username.trim()) {
      alert("Tenant ID and username are required."); return;
    }
    try {
      await apiFetch(`/api/migration/projects/${projectId}/tenant-users`, {
        method: "POST", body: JSON.stringify({ ...newUser, user_type: "tenant_owner" })
      });
      setNewUser({ tenant_id: 0, username: "", email: "", role: "member", notes: "" });
      setShowAdd(false);
      await load();
    } catch (e: any) { setError(e.message); }
  };

  // Group users by tenant_id
  const grouped = users.reduce((acc: Record<number, any[]>, u) => {
    const tid = u.tenant_id ?? 0;
    if (!acc[tid]) acc[tid] = [];
    acc[tid].push(u);
    return acc;
  }, {});
  const tenantIds = Object.keys(grouped).map(Number).sort((a, b) => a - b);

  const confirmedTenants = tenantIds.filter(tid =>
    grouped[tid].every((u: any) => u.confirmed)
  ).length;

  if (loading) return <div style={{ color: "#6b7280", padding: 16 }}>Loading tenant users...</div>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
        <div>
          <h3 style={{ margin: 0 }}>👤 Per-Tenant User Definitions</h3>
          <p style={{ margin: "4px 0 0", color: "#6b7280", fontSize: "0.85rem" }}>
            Define service accounts and tenant owner accounts to be created in PCD.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {tenantIds.length > 0 && (
            <span style={{
              padding: "4px 10px", borderRadius: 6, fontSize: "0.78rem", fontWeight: 600,
              background: confirmedTenants === tenantIds.length ? "#dcfce7" : "#fff7ed",
              color: confirmedTenants === tenantIds.length ? "#15803d" : "#9a3412",
              border: `1px solid ${confirmedTenants === tenantIds.length ? "#86efac" : "#fdba74"}`,
            }}>
              {confirmedTenants}/{tenantIds.length} tenants confirmed
            </span>
          )}
          <button onClick={seed} disabled={seeding}
            style={{ ...btnSecondary, background: "#f0fdf4", color: "#15803d", border: "1px solid #86efac" }}>
            {seeding ? "⏳ Seeding..." : "🤖 Seed Service Accounts"}
          </button>
          <button onClick={() => setShowAdd(!showAdd)}
            style={{ ...btnSecondary, background: showAdd ? "#eff6ff" : undefined }}>
            ➕ Add Owner
          </button>
          <button onClick={load} style={btnSecondary}>🔄 Refresh</button>
        </div>
      </div>

      {showAdd && (
        <div style={{ marginBottom: 14, padding: 14, background: "#f0fdf4",
          border: "1px solid #86efac", borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 8, color: "#15803d", fontSize: "0.88rem" }}>
            ➕ Add Tenant Owner Account
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 8, marginBottom: 10 }}>
            <div>
              <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 2 }}>Tenant ID *</label>
              <input type="number" value={newUser.tenant_id || ""} onChange={e => setNewUser(p => ({ ...p, tenant_id: +e.target.value }))}
                style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }} placeholder="numeric tenant ID" />
            </div>
            <div>
              <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 2 }}>Username *</label>
              <input value={newUser.username} onChange={e => setNewUser(p => ({ ...p, username: e.target.value }))}
                style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }} placeholder="e.g. admin@tenant.com" />
            </div>
            <div>
              <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 2 }}>Email</label>
              <input value={newUser.email} onChange={e => setNewUser(p => ({ ...p, email: e.target.value }))}
                style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }} placeholder="email@example.com" />
            </div>
            <div>
              <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 2 }}>Role</label>
              <select value={newUser.role} onChange={e => setNewUser(p => ({ ...p, role: e.target.value }))}
                style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }}>
                <option value="admin">admin</option>
                <option value="member">member</option>
                <option value="reader">reader</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: "0.75rem", color: "#374151", display: "block", marginBottom: 2 }}>Notes</label>
              <input value={newUser.notes} onChange={e => setNewUser(p => ({ ...p, notes: e.target.value }))}
                style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.82rem", width: "100%" }} placeholder="optional notes" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={addUser} style={{ ...btnSmall, background: "#16a34a", color: "#fff", padding: "6px 14px" }}>✓ Add</button>
            <button onClick={() => setShowAdd(false)} style={{ ...btnSmall, background: "#e5e7eb", color: "#374151", padding: "6px 14px" }}>Cancel</button>
          </div>
        </div>
      )}

      {error && <div style={{ ...alertError, marginBottom: 10 }}>{error}</div>}

      {tenantIds.length === 0 ? (
        <div style={{ color: "#6b7280", textAlign: "center", padding: "24px 0", fontSize: "0.88rem" }}>
          No user definitions yet. Click "Seed Service Accounts" to auto-create migration service accounts.
        </div>
      ) : (
        tenantIds.map(tid => {
          const tenantUsers = grouped[tid];
          const tenantName = tenantUsers[0]?.tenant_name ?? `Tenant #${tid}`;
          const allConfirmed = tenantUsers.every((u: any) => u.confirmed);
          return (
            <div key={tid} style={{ marginBottom: 14, border: "1px solid var(--border, #e5e7eb)",
              borderRadius: 8, overflow: "hidden" }}>
              <div style={{ padding: "8px 14px", background: allConfirmed ? "#f0fdf4" : "#f9fafb",
                borderBottom: "1px solid var(--border, #e5e7eb)",
                display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <strong style={{ fontSize: "0.88rem" }}>{tenantName}</strong>
                  <span style={{ marginLeft: 8, color: "#6b7280", fontSize: "0.78rem" }}>
                    {tenantUsers.length} user{tenantUsers.length !== 1 ? "s" : ""}
                  </span>
                </div>
                {allConfirmed
                  ? <span style={{ ...pillStyle, background: "#dcfce7", color: "#15803d", fontSize: "0.72rem" }}>✓ confirmed</span>
                  : <span style={{ ...pillStyle, background: "#fff7ed", color: "#ea580c", fontSize: "0.72rem" }}>pending</span>
                }
              </div>
              <table style={{ ...tableStyle, fontSize: "0.8rem" }}>
                <thead>
                  <tr>
                    <th style={{ ...thStyle, fontSize: "0.75rem" }}>Type</th>
                    <th style={{ ...thStyle, fontSize: "0.75rem" }}>Username</th>
                    <th style={{ ...thStyle, fontSize: "0.75rem" }}>Email</th>
                    <th style={{ ...thStyle, fontSize: "0.75rem" }}>Role</th>
                    <th style={{ ...thStyle, fontSize: "0.75rem" }}>Temp Password</th>
                    <th style={{ ...thStyle, fontSize: "0.75rem", width: 80, textAlign: "center" }}>Status</th>
                    <th style={{ ...thStyle, fontSize: "0.75rem", width: 120 }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {tenantUsers.map((u: any) => {
                    const ed = editRow[u.id];
                    const isEditing = !!ed;
                    return (
                      <tr key={u.id} style={{ borderBottom: "1px solid #e5e7eb" }}>
                        <td style={tdStyle}>
                          <span style={{ ...pillStyle, fontSize: "0.68rem",
                            background: u.user_type === "service_account" ? "#eff6ff" : "#faf5ff",
                            color: u.user_type === "service_account" ? "#1d4ed8" : "#7c3aed" }}>
                            {u.user_type === "service_account" ? "🤖 svc" : "👤 owner"}
                          </span>
                        </td>
                        <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.78rem" }}>
                          {isEditing
                            ? <input value={ed.username ?? u.username} onChange={e => setEditRow(p => ({ ...p, [u.id]: { ...p[u.id], username: e.target.value } }))}
                                style={{ ...inputStyle, padding: "2px 5px", fontSize: "0.78rem", width: 140 }} />
                            : u.username}
                        </td>
                        <td style={{ ...tdStyle, fontSize: "0.78rem", color: "#374151" }}>
                          {isEditing
                            ? <input value={ed.email ?? u.email ?? ""} onChange={e => setEditRow(p => ({ ...p, [u.id]: { ...p[u.id], email: e.target.value } }))}
                                style={{ ...inputStyle, padding: "2px 5px", fontSize: "0.78rem", width: 160 }} />
                            : (u.email || "—")}
                        </td>
                        <td style={{ ...tdStyle, fontSize: "0.78rem" }}>
                          {isEditing
                            ? (
                              <select value={ed.role ?? u.role ?? "member"} onChange={e => setEditRow(p => ({ ...p, [u.id]: { ...p[u.id], role: e.target.value } }))}
                                style={{ ...inputStyle, padding: "2px 5px", fontSize: "0.78rem" }}>
                                <option value="admin">admin</option>
                                <option value="member">member</option>
                                <option value="reader">reader</option>
                              </select>
                            )
                            : (u.role || "member")}
                        </td>
                        <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.75rem", color: "#6b7280" }}>
                          {u.temp_password
                            ? <span title="Generated temp password (store securely)">{u.temp_password}</span>
                            : "—"}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "center" }}>
                          {u.confirmed
                            ? <span style={{ ...pillStyle, background: "#dcfce7", color: "#15803d", fontSize: "0.7rem" }}>✓</span>
                            : <span style={{ ...pillStyle, background: "#fff7ed", color: "#ea580c", fontSize: "0.7rem" }}>pending</span>}
                        </td>
                        <td style={tdStyle}>
                          {isEditing ? (
                            <div style={{ display: "flex", gap: 4 }}>
                              <button onClick={() => saveEdit(u.id)} disabled={saving === u.id}
                                style={{ ...btnSmall, background: "#2563eb", color: "#fff", fontSize: "0.7rem" }}>
                                {saving === u.id ? "..." : "Save"}
                              </button>
                              <button onClick={() => setEditRow(p => { const n = { ...p }; delete n[u.id]; return n; })}
                                style={{ ...btnSmall, background: "#e5e7eb", color: "#374151", fontSize: "0.7rem" }}>✕</button>
                            </div>
                          ) : (
                            <div style={{ display: "flex", gap: 4 }}>
                              <button onClick={() => setEditRow(p => ({ ...p, [u.id]: { username: u.username, email: u.email ?? "", role: u.role ?? "member" } }))}
                                style={{ ...btnSmall, background: "#f3f4f6", color: "#374151", fontSize: "0.7rem" }}>✏️</button>
                              <button
                                onClick={() => apiFetch(`/api/migration/tenant-users/${u.id}`, { method: "PATCH", body: JSON.stringify({ confirmed: true }) }).then(load)}
                                style={{ ...btnSmall, background: "#f0fdf4", color: "#16a34a", fontSize: "0.7rem" }}
                                title="Mark as confirmed">✓</button>
                              {u.user_type !== "service_account" && (
                                <button onClick={() => deleteUser(u.id)}
                                  style={{ ...btnSmall, background: "#fef2f2", color: "#dc2626", fontSize: "0.7rem" }}
                                  title="Delete">🗑</button>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          );
        })
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Styles                                                             */
/* ------------------------------------------------------------------ */

const sectionStyle: React.CSSProperties = {
  background: "var(--card-bg, #fff)", border: "1px solid var(--border, #e5e7eb)",
  borderRadius: 8, padding: 20, marginBottom: 16,
};

const labelStyle: React.CSSProperties = {
  display: "block", marginBottom: 4, fontWeight: 600, fontSize: "0.85rem",
};

const inputStyle: React.CSSProperties = {
  padding: "6px 10px", borderRadius: 6,
  border: "1px solid var(--border, #d1d5db)", fontSize: "0.85rem",
  boxSizing: "border-box" as const,
};

const tableStyle: React.CSSProperties = {
  width: "100%", borderCollapse: "collapse", fontSize: "0.85rem",
};

const thStyle: React.CSSProperties = {
  textAlign: "left", padding: "8px 10px", fontWeight: 600,
  borderBottom: "2px solid var(--border, #e5e7eb)", cursor: "pointer",
  whiteSpace: "nowrap", fontSize: "0.8rem",
};

const tdStyle: React.CSSProperties = {
  padding: "6px 10px", verticalAlign: "top",
};

const pillStyle: React.CSSProperties = {
  padding: "2px 8px", borderRadius: 12, fontSize: "0.75rem", fontWeight: 600,
  whiteSpace: "nowrap",
};

const subTabStyle: React.CSSProperties = {
  padding: "8px 16px", border: "none", borderBottom: "2px solid transparent",
  background: "transparent", cursor: "pointer", fontWeight: 500,
};

const subTabActive: React.CSSProperties = {
  borderBottom: "2px solid #3b82f6", color: "#3b82f6",
};

const btnPrimary: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 6, border: "none",
  background: "#3b82f6", color: "#fff", cursor: "pointer", fontWeight: 600,
};

const btnSecondary: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 6, border: "1px solid var(--border, #d1d5db)",
  background: "transparent", cursor: "pointer",
};

const btnDanger: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 6, border: "none",
  background: "#ef4444", color: "#fff", cursor: "pointer", fontWeight: 600,
};

const btnApprove: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 6, border: "none",
  background: "#22c55e", color: "#fff", cursor: "pointer", fontWeight: 600,
};

const btnSmall: React.CSSProperties = {
  padding: "4px 12px", borderRadius: 4, border: "1px solid var(--border, #d1d5db)",
  background: "transparent", cursor: "pointer", fontSize: "0.85rem",
};

const alertError: React.CSSProperties = {
  background: "#fef2f2", color: "#dc2626", padding: "8px 12px",
  borderRadius: 6, marginBottom: 12, border: "1px solid #fecaca",
};

const alertSuccess: React.CSSProperties = {
  background: "#f0fdf4", color: "#16a34a", padding: "8px 12px",
  borderRadius: 6, marginBottom: 12, border: "1px solid #bbf7d0",
};

const thStyleSm: React.CSSProperties = {
  textAlign: "left", padding: "4px 8px", fontWeight: 600,
  borderBottom: "1px solid var(--border, #e5e7eb)", fontSize: "0.75rem",
  whiteSpace: "nowrap",
};

const tdStyleSm: React.CSSProperties = {
  padding: "3px 8px", verticalAlign: "top", fontSize: "0.8rem",
};
