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
  target_display_name: string | null;
  // Phase 2.10
  migration_priority?: number;
  cohort_id?: number | null;
  cohort_name?: string | null;
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

type SubView = "dashboard" | "vms" | "tenants" | "cohorts" | "networks" | "netmap" | "risk" | "plan" | "capacity" | "readiness";

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
          { id: "networks" as SubView, label: "🌐 Networks" },
          { id: "netmap" as SubView, label: "🔌 Network Map" },
          { id: "capacity" as SubView, label: "⚖️ Capacity" },
          { id: "readiness" as SubView, label: "🎯 PCD Readiness" },
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
              {tenants.map((t, i) => <option key={t.tenant_id ?? t.tenant_name ?? i} value={t.tenant_name}>{t.tenant_name}</option>)}
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
        <CohortsView projectId={pid} tenants={tenants} onRefreshTenants={() => { loadTenants(); loadStats(); }} />
      )}

      {/* ---- Networks ---- */}
      {subView === "networks" && (
        <NetworksView networks={networks} projectId={pid} onRefresh={loadNetworks} />
      )}

      {/* ---- Network Map ---- */}
      {subView === "netmap" && (
        <NetworkMappingView projectId={pid} />
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

      {/* ---- Migration Plan ---- */}
      {subView === "plan" && (
        <MigrationPlanView projectId={pid} projectName={project.name} />
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
                background: mode === "warm_eligible" ? "#f0fdf4" :
                             mode === "warm_risky" ? "#fffbeb" : "#fef2f2",
                border: `1px solid ${mode === "warm_eligible" ? "#bbf7d0" :
                                    mode === "warm_risky" ? "#fcd34d" : "#fecaca"}`,
              }}>
                <div style={{ fontSize: "1.4rem", fontWeight: 700 }}>{count as number}</div>
                <div style={{ fontSize: "0.85rem", color: "#6b7280" }}>{(mode as string).replace(/_/g, " ")}</div>
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
                padding: 10, borderRadius: 6, border: "1px solid var(--border, #e5e7eb)",
              }}>
                <div style={{ fontWeight: 600 }}>{t.tenant_name}</div>
                <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>
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
  const [editPriority, setEditPriority] = useState<number>(999);
  const [editSaving, setEditSaving] = useState(false);

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
              <th style={thStyle}>Target Project</th>
              <th style={thStyle}>Display Name</th>
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
                        <input value={editProject} onChange={e => setEditProject(e.target.value)}
                          style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem" }}
                          placeholder="e.g. acme-prod"
                          onKeyDown={e => { if (e.key === "Escape") cancelEdit(); }} />
                      </td>
                      <td style={tdStyle}>
                        <input value={editDisplayName} onChange={e => setEditDisplayName(e.target.value)}
                          style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem" }}
                          placeholder="e.g. ACME Production"
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
                        <td colSpan={13} style={{ ...tdStyle, paddingTop: 4, paddingBottom: 8 }}>
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
                  <td style={{ ...tdStyle, fontSize: "0.8rem" }}>{t.target_domain_name || <span style={{ color: "#9ca3af" }}>—</span>}</td>
                  <td style={{ ...tdStyle, fontSize: "0.8rem" }}>{t.target_project_name || <span style={{ color: "#9ca3af" }}>—</span>}</td>
                  <td style={{ ...tdStyle, fontSize: "0.8rem" }}>{t.target_display_name || <span style={{ color: "#9ca3af" }}>—</span>}</td>
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
              <tr><td colSpan={15} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
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
  const [editId, setEditId] = useState<number | null>(null);
  const [editFields, setEditFields] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const startEdit = (n: NetworkSummary) => {
    setEditId(n.id);
    setEditFields({
      subnet: n.subnet || "",
      gateway: n.gateway || "",
      dns_servers: n.dns_servers || "",
      ip_range: n.ip_range || "",
      pcd_target: n.pcd_target || "",
      notes: n.notes || "",
      network_type: n.network_type || "standard",
    });
  };

  const cancelEdit = () => { setEditId(null); setEditFields({}); };

  const saveEdit = async () => {
    if (!editId) return;
    setSaving(true);
    setError("");
    try {
      await apiFetch(`/api/migration/projects/${projectId}/networks/${editId}`, {
        method: "PATCH",
        body: JSON.stringify(editFields),
      });
      cancelEdit();
      onRefresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

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
        (n.network_type || "").toLowerCase().includes(netSearch.toLowerCase()) ||
        (n.subnet || "").includes(netSearch) ||
        (n.pcd_target || "").toLowerCase().includes(netSearch.toLowerCase())
      )
    : networks;

  return (
    <div>
      <p style={{ color: "#6b7280", fontSize: "0.85rem", marginBottom: 8 }}>
        Network infrastructure extracted from RVTools. VLAN IDs and types are auto-detected from naming patterns.
        Click ✏️ to manually add subnet, gateway, DNS, and PCD target mapping.
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <input
          placeholder="Search networks, tenants, type, subnet…"
          value={netSearch}
          onChange={e => setNetSearch(e.target.value)}
          style={{ ...inputStyle, maxWidth: 320 }}
        />
        {netSearch && (
          <button onClick={() => setNetSearch("")} style={btnSmall}>✕ Clear</button>
        )}
        <span style={{ fontSize: "0.8rem", color: "#6b7280" }}>{filteredNetworks.length} / {networks.length} networks</span>
      </div>
      {error && <div style={alertError}>{error}</div>}

      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Network Name</th>
            <th style={thStyle}>VLAN ID</th>
            <th style={thStyle}>Type</th>
            <th style={thStyle}>VMs</th>
            <th style={thStyle}>Tenants</th>
            <th style={thStyle}>Subnet</th>
            <th style={thStyle}>Gateway</th>
            <th style={thStyle}>DNS</th>
            <th style={thStyle}>IP Range</th>
            <th style={thStyle}>PCD Target</th>
            <th style={thStyle}>Notes</th>
            <th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {filteredNetworks.map(n => (
            <tr key={n.id} style={{ borderBottom: "1px solid var(--border, #e5e7eb)" }}>
              {editId === n.id ? (
                <>
                  <td style={tdStyle}><strong>{n.network_name}</strong></td>
                  <td style={tdStyle}>{n.vlan_id ?? "—"}</td>
                  <td style={tdStyle}>
                    <select value={editFields.network_type} onChange={e => setEditFields(f => ({ ...f, network_type: e.target.value }))}
                      style={{ ...inputStyle, padding: "3px 6px", fontSize: "0.8rem" }}>
                      <option value="standard">Standard</option>
                      <option value="vlan_based">VLAN-based</option>
                      <option value="nsx_t">NSX-T</option>
                      <option value="isolated">Isolated</option>
                    </select>
                  </td>
                  <td style={tdStyle}>{n.vm_count}</td>
                  <td style={tdStyle}>{n.tenant_names || "—"}</td>
                  <td style={tdStyle}>
                    <input value={editFields.subnet} onChange={e => setEditFields(f => ({ ...f, subnet: e.target.value }))}
                      style={{ ...inputStyle, padding: "3px 6px", fontSize: "0.8rem", width: 120 }} placeholder="10.0.0.0/24" />
                  </td>
                  <td style={tdStyle}>
                    <input value={editFields.gateway} onChange={e => setEditFields(f => ({ ...f, gateway: e.target.value }))}
                      style={{ ...inputStyle, padding: "3px 6px", fontSize: "0.8rem", width: 110 }} placeholder="10.0.0.1" />
                  </td>
                  <td style={tdStyle}>
                    <input value={editFields.dns_servers} onChange={e => setEditFields(f => ({ ...f, dns_servers: e.target.value }))}
                      style={{ ...inputStyle, padding: "3px 6px", fontSize: "0.8rem", width: 140 }} placeholder="8.8.8.8, 8.8.4.4" />
                  </td>
                  <td style={tdStyle}>
                    <input value={editFields.ip_range} onChange={e => setEditFields(f => ({ ...f, ip_range: e.target.value }))}
                      style={{ ...inputStyle, padding: "3px 6px", fontSize: "0.8rem", width: 150 }} placeholder="10.0.0.10-10.0.0.254" />
                  </td>
                  <td style={tdStyle}>
                    <input value={editFields.pcd_target} onChange={e => setEditFields(f => ({ ...f, pcd_target: e.target.value }))}
                      style={{ ...inputStyle, padding: "3px 6px", fontSize: "0.8rem", width: 120 }} placeholder="PCD network" />
                  </td>
                  <td style={tdStyle}>
                    <input value={editFields.notes} onChange={e => setEditFields(f => ({ ...f, notes: e.target.value }))}
                      style={{ ...inputStyle, padding: "3px 6px", fontSize: "0.8rem", width: 120 }} placeholder="Notes" />
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 4 }}>
                      <button onClick={saveEdit} disabled={saving}
                        style={{ ...btnSmall, background: "#16a34a", color: "#fff" }}>
                        {saving ? "..." : "✓"}
                      </button>
                      <button onClick={cancelEdit} style={{ ...btnSmall, background: "#e5e7eb" }}>✕</button>
                    </div>
                  </td>
                </>
              ) : (
                <>
                  <td style={tdStyle}><strong>{n.network_name}</strong></td>
                  <td style={{ ...tdStyle, fontFamily: "monospace" }}>{n.vlan_id ?? "—"}</td>
                  <td style={tdStyle}>
                    <span style={{ ...pillStyle, ...typeColor(n.network_type) }}>{n.network_type.replace(/_/g, " ")}</span>
                  </td>
                  <td style={tdStyle}>{n.vm_count}</td>
                  <td style={{ ...tdStyle, fontSize: "0.8rem", color: "#6b7280" }}>
                    {n.tenant_names ? n.tenant_names.split(', ').map((tenant, i, arr) => (
                      <span key={tenant}>
                        {tenant}{i < arr.length - 1 ? ', ' : ''}
                      </span>
                    )) : "—"}
                  </td>
                  <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.8rem" }}>{n.subnet || "—"}</td>
                  <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.8rem" }}>{n.gateway || "—"}</td>
                  <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.8rem" }}>{n.dns_servers || "—"}</td>
                  <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "0.8rem" }}>{n.ip_range || "—"}</td>
                  <td style={{ ...tdStyle, fontSize: "0.8rem" }}>{n.pcd_target || "—"}</td>
                  <td style={{ ...tdStyle, fontSize: "0.8rem", color: "#6b7280" }}>{n.notes || "—"}</td>
                  <td style={tdStyle}>
                    <button onClick={() => startEdit(n)} style={btnSmall} title="Edit network details">✏️</button>
                  </td>
                </>
              )}
            </tr>
          ))}
          {networks.length === 0 && (
            <tr><td colSpan={12} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
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
  const [unmappedCount, setUnmappedCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState<number | null>(null);
  const [editValues, setEditValues] = useState<Record<number, string>>({});
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ mappings: any[]; unmapped_count: number }>(
        `/api/migration/projects/${projectId}/network-mappings`
      );
      setMappings(data.mappings);
      setUnmappedCount(data.unmapped_count);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const saveMapping = async (id: number) => {
    setSaving(id);
    try {
      await apiFetch(`/api/migration/projects/${projectId}/network-mappings/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ target_network_name: editValues[id] || null }),
      });
      setEditValues(prev => { const n = { ...prev }; delete n[id]; return n; });
      load();
    } catch (e: any) { setError(e.message); }
    finally { setSaving(null); }
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
        <button onClick={load} style={btnSecondary}>🔄 Refresh</button>
      </div>
      {unmappedCount > 0 && (
        <div style={{ marginBottom: 12, padding: "8px 14px", background: "#fff7ed",
          borderRadius: 6, border: "1px solid #fdba74", color: "#9a3412", fontSize: "0.85rem" }}>
          ⚠️ {unmappedCount} network{unmappedCount !== 1 ? "s" : ""} not yet mapped to a PCD target.
          Wave planning requires all used networks to be mapped.
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
              <th style={{ ...thStyle, width: 80 }}>Status</th>
              <th style={{ ...thStyle, width: 70 }}>Save</th>
            </tr>
          </thead>
          <tbody>
            {mappings.map(m => {
              const editVal = editValues[m.id];
              const current = editVal !== undefined ? editVal : (m.target_network_name || "");
              const isDirty = editVal !== undefined && editVal !== (m.target_network_name || "");
              return (
                <tr key={m.id} style={{ borderBottom: "1px solid var(--border, #e5e7eb)" }}>
                  <td style={tdStyle}>
                    <strong style={{ fontFamily: "monospace", fontSize: "0.85rem" }}>{m.source_network_name}</strong>
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>{m.vm_count ?? 0}</td>
                  <td style={tdStyle}>
                    <input
                      value={current}
                      onChange={e => setEditValues(prev => ({ ...prev, [m.id]: e.target.value }))}
                      placeholder="Enter PCD network name..."
                      style={{ ...inputStyle, padding: "4px 8px", fontSize: "0.85rem",
                        background: isDirty ? "#eff6ff" : undefined }}
                      onKeyDown={e => { if (e.key === "Enter") saveMapping(m.id); }}
                    />
                  </td>
                  <td style={{ ...tdStyle, color: "#6b7280", fontSize: "0.8rem" }}>{m.vlan_id ?? "—"}</td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    {m.target_network_name
                      ? <span style={{ ...pillStyle, background: "#dcfce7", color: "#15803d", fontSize: "0.72rem" }}>✓ mapped</span>
                      : <span style={{ ...pillStyle, background: "#fff7ed", color: "#ea580c", fontSize: "0.72rem" }}>⚠ unmapped</span>}
                  </td>
                  <td style={tdStyle}>
                    <button
                      onClick={() => saveMapping(m.id)}
                      disabled={saving === m.id || !isDirty}
                      style={{ ...btnSmall, background: isDirty ? "#2563eb" : "#e5e7eb",
                        color: isDirty ? "#fff" : "#9ca3af" }}>
                      {saving === m.id ? "..." : "Save"}
                    </button>
                  </td>
                </tr>
              );
            })}
            {mappings.length === 0 && (
              <tr><td colSpan={6} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
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
  tenant_count: number;
  vm_count: number;
  total_vcpu: number;
  total_ram_gb: number;
}

function CohortsView({ projectId, tenants, onRefreshTenants }: {
  projectId: number; tenants: Tenant[]; onRefreshTenants: () => void
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
  const [creating, setCreating] = useState(false);
  const [selectedCohort, setSelectedCohort] = useState<number | null>(null);
  const [selectedTenants, setSelectedTenants] = useState<Set<number>>(new Set());
  const [assigning, setAssigning] = useState(false);
  const [autoStrategy, setAutoStrategy] = useState("priority");
  const [autoAssigning, setAutoAssigning] = useState(false);

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
        }),
      });
      setNewName(""); setNewOrder(cohorts.length + 1); setNewOwner("");
      setNewStart(""); setNewEnd(""); setNewDependsOn("");
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

  const autoAssign = async () => {
    if (!confirm(`Auto-assign all unassigned tenants to cohorts using "${autoStrategy}" strategy?`)) return;
    setAutoAssigning(true);
    try {
      await apiFetch(`/api/migration/projects/${projectId}/cohorts/auto-assign?strategy=${autoStrategy}`, {
        method: "POST",
      });
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
          <select value={autoStrategy} onChange={e => setAutoStrategy(e.target.value)} style={{ ...inputStyle, maxWidth: 160, fontSize: "0.82rem" }}>
            <option value="priority">By Priority</option>
            <option value="risk">By Risk (low-risk first)</option>
            <option value="equal_split">Equal Split</option>
          </select>
          <button onClick={autoAssign} disabled={autoAssigning || cohorts.length === 0}
            style={btnSecondary} title="Auto-assign all unassigned tenants">
            {autoAssigning ? "..." : "⚡ Auto-Assign"}
          </button>
          <button onClick={() => setShowCreate(!showCreate)} style={btnPrimary}>+ New Cohort</button>
        </div>
      </div>
      {error && <div style={alertError}>{error}</div>}

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
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 12, fontSize: "0.82rem" }}>
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
                {(c.scheduled_start || c.scheduled_end) && (
                  <div style={{ fontSize: "0.78rem", color: "#6b7280", marginBottom: 8 }}>
                    📅 {c.scheduled_start || "?"} → {c.scheduled_end || "?"}
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

      {/* Per-tenant plans */}
      <div style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Per-Tenant Assessment</h3>
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
            {plan.tenant_plans.map((tp: any) => (
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
                    <td colSpan={15} style={{ padding: "4px 16px 12px 40px", background: "var(--card-bg, #f9fafb)" }}>
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
                                  // Warm: Phase 1 copy (live). Cold: full offline copy = the copy phase too.
                                  const h = v.migration_mode !== "cold_required"
                                    ? Number(v.warm_phase1_hours)
                                    : Number(v.cold_total_hours);
                                  return h < 0.017 ? "<1min" : h < 1 ? `${Math.round(h * 60)}min` : `${h.toFixed(2)}h`;
                                })()} 
                              </td>
                              <td style={tdStyleSm}>
                                {(() => {
                                  // Warm: cutover only. Cold: boot/connect phase (same estimate as warm cutover)
                                  const h = Number(v.warm_cutover_hours);
                                  return h < 1 ? `${Math.round(h * 60)}min` : `${h.toFixed(2)}h`;
                                })()}
                              </td>
                              <td style={tdStyleSm}>
                                <strong>
                                  {(() => {
                                    // Warm: downtime = cutover only (copy phase is live)
                                    // Cold: downtime = full copy (VM is off throughout)
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
          </tbody>
        </table>
      </div>

      {/* Daily schedule */}
      {plan.daily_schedule?.length > 0 && (
        <div style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>Daily Migration Schedule (Estimated)</h3>
          <p style={{ color: "#6b7280", fontSize: "0.85rem", marginBottom: 12 }}>
            VMs ordered by tenant → priority → disk size. Each day fills up to {ps.total_concurrent_slots} concurrent slots.
          </p>
          <div style={{ maxHeight: 400, overflowY: "auto" }}>
            <table style={{ ...tableStyle, fontSize: "0.8rem" }}>
              <thead>
                <tr>
                  <th style={thStyleSm}>Day</th>
                  <th style={thStyleSm}>VMs</th>
                  <th style={thStyleSm}>VM Names</th>
                  <th style={thStyleSm}>Est. Hours</th>
                </tr>
              </thead>
              <tbody>
                {plan.daily_schedule.map((day: any) => (
                  <tr key={day.day} style={{ borderBottom: "1px solid #e5e7eb" }}>
                    <td style={tdStyleSm}><strong>Day {day.day}</strong></td>
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
                            <div style={{ 
                              fontSize: "0.7rem", fontWeight: 600, color: "#4f46e5", 
                              marginBottom: 2
                            }}>
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
                ))}
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
      const g = await apiFetch(`/api/migration/projects/${projectId}/pcd-gaps`);
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
      setGaps(result.gaps || []);
      if (result.readiness_score != null) setReadinessScore(Number(result.readiness_score));
      setMsg(`Gap analysis complete. Found ${(result.gaps || []).length} gaps.`);
      setTimeout(() => setMsg(""), 5000);
    } catch (e: any) { setError(e.message); }
    setRunning(false);
  };

  const resolveGap = async (gapId: number) => {
    try {
      await apiFetch(`/api/migration/projects/${projectId}/pcd-gaps/${gapId}/resolve`, { method: "PATCH" });
      setGaps(prev => prev.map(g => g.id === gapId ? { ...g, resolved: true } : g));
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
              {gaps.map(g => {
                const detailKeys = Object.keys(g.details || {}).filter(k => k !== "vms");
                return (
                  <tr key={g.id} style={{
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
                          {detailKeys.map(k => (
                            <div key={k} style={{ display: "flex", gap: 4, marginBottom: 2 }}>
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
      background: "var(--card-bg, #f9fafb)", border: "1px solid var(--border, #e5e7eb)",
    }}>
      <div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{display}</div>
      <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>{label}</div>
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
