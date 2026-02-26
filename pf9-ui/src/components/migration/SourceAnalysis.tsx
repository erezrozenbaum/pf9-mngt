/**
 * SourceAnalysis — Post-upload view showing VM inventory, tenant assignment,
 *                  risk/complexity scoring, migration mode classification,
 *                  and assessment controls.
 */

import React, { useState, useEffect, useCallback } from "react";
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
    throw new Error(err.detail || `API error ${res.status}`);
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
  migration_mode: string | null;
  estimated_minutes: number | null;
  cpu_usage_percent: number | null;
  memory_usage_percent: number | null;
  cpu_demand_mhz: number | null;
  memory_usage_mb: number | null;
}

interface Tenant {
  tenant_id: number;
  tenant_name: string;
  org_vdc: string | null;
  detection_method: string;
  vm_count: number;
  total_vcpu: number;
  total_ram_mb: number;
  total_disk_gb: number;
  total_in_use_gb: number;
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

type SubView = "dashboard" | "vms" | "tenants" | "networks" | "risk" | "plan";

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
  const [vmDisks, setVmDisks] = useState<any[]>([]);
  const [vmNics, setVmNics] = useState<any[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);

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

  const toggleVmExpand = (vmName: string) => {
    if (expandedVm === vmName) {
      setExpandedVm(null);
    } else {
      setExpandedVm(vmName);
      loadVmDetails(vmName);
    }
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
            <button onClick={clearRvtoolsData} disabled={loading}
              style={{ ...btnDanger, background: "#9333ea" }}>
              🗑️ Clear RVTools Data
            </button>
          )}
        </div>
      </div>

      {error && <div style={alertError}>{error}</div>}

      {/* Sub-nav */}
      <div style={{ display: "flex", gap: 4, marginBottom: 16, borderBottom: "2px solid var(--border, #e5e7eb)" }}>
        {([
          { id: "dashboard" as SubView, label: "📊 Dashboard" },
          { id: "vms" as SubView, label: "🖥️ VMs" },
          { id: "tenants" as SubView, label: "🏢 Tenants" },
          { id: "networks" as SubView, label: "🌐 Networks" },
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
              {tenants.map(t => <option key={t.tenant_id} value={t.tenant_name}>{t.tenant_name}</option>)}
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
                    { key: "primary_ip", label: "IP" },
                  ].map(col => (
                    <th key={col.key} style={thStyle} onClick={() => {
                      if (vmSort === col.key) setVmOrder(o => o === "asc" ? "desc" : "asc");
                      else { setVmSort(col.key); setVmOrder("asc"); }
                    }}>
                      {col.label} {vmSort === col.key ? (vmOrder === "asc" ? "▲" : "▼") : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {vms.map(vm => (
                  <React.Fragment key={vm.vm_id}>
                    <tr style={{ borderBottom: "1px solid var(--border, #e5e7eb)", cursor: "pointer" }}
                        onClick={() => toggleVmExpand(vm.vm_name)}>
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
                          <span style={{ color: Number(vm.memory_usage_percent) > 80 ? "#dc2626" : Number(vm.memory_usage_percent) > 60 ? "#f59e0b" : "#10b981" }}>
                            {Number(vm.memory_usage_percent).toFixed(1)}%
                          </span>
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
                            {vm.migration_mode.replace(/_/g, " ")}
                          </span>
                        ) : "—"}
                      </td>
                      <td style={tdStyle}>
                        <span style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>{vm.primary_ip || "—"}</span>
                      </td>
                    </tr>
                    {/* ── Expanded detail row ── */}
                    {expandedVm === vm.vm_name && (
                      <tr>
                        <td colSpan={16} style={{ padding: "8px 16px 12px 40px", background: "var(--card-bg, #f9fafb)" }}>
                          {detailLoading ? (
                            <span style={{ color: "#6b7280" }}>Loading details...</span>
                          ) : (
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
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
                {vms.length === 0 && (
                  <tr><td colSpan={16} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
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

      {/* ---- Networks ---- */}
      {subView === "networks" && (
        <NetworksView networks={networks} projectId={pid} onRefresh={loadNetworks} />
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
              <div key={t.tenant_id || t.tenant_name || idx} style={{
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
/*  Tenants View                                                      */
/* ================================================================== */

function TenantsView({ tenants, projectId, onRefresh }: {
  tenants: Tenant[]; projectId: number; onRefresh: () => void
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newMethod, setNewMethod] = useState("vm_name_prefix");
  const [newPattern, setNewPattern] = useState("");
  const [error, setError] = useState("");

  /* ---- Inline editing state ---- */
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editOrgVdc, setEditOrgVdc] = useState("");
  const [editSaving, setEditSaving] = useState(false);

  const startEdit = (t: Tenant) => {
    setEditId(t.tenant_id);
    setEditName(t.tenant_name);
    setEditOrgVdc(t.org_vdc || "");
  };

  const cancelEdit = () => {
    setEditId(null);
    setEditName("");
    setEditOrgVdc("");
  };

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

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button onClick={() => setShowAdd(!showAdd)} style={btnSecondary}>+ Add Tenant Rule</button>
        <button onClick={rerun} style={btnSecondary}>🔄 Re-run Detection</button>
      </div>
      {error && <div style={alertError}>{error}</div>}

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

      <table style={tableStyle}>
        <thead>
          <tr>
            <th style={thStyle}>Tenant</th>
            <th style={thStyle}>OrgVDC</th>
            <th style={thStyle}>Method</th>
            <th style={thStyle}>VMs</th>
            <th style={thStyle}>vCPUs</th>
            <th style={thStyle}>RAM (GB)</th>
            <th style={thStyle}>Alloc (GB)</th>
            <th style={thStyle}>Used (GB)</th>
            <th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {tenants.map(t => (
            <tr key={t.tenant_id} style={{ borderBottom: "1px solid var(--border, #e5e7eb)" }}>
              {editId === t.tenant_id ? (
                <>
                  <td style={tdStyle}>
                    <input value={editName} onChange={e => setEditName(e.target.value)}
                      style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem" }}
                      onKeyDown={e => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") cancelEdit(); }} />
                  </td>
                  <td style={tdStyle}>
                    <input value={editOrgVdc} onChange={e => setEditOrgVdc(e.target.value)}
                      style={{ ...inputStyle, padding: "4px 6px", fontSize: "0.85rem" }}
                      placeholder="(optional)"
                      onKeyDown={e => { if (e.key === "Enter") saveEdit(); if (e.key === "Escape") cancelEdit(); }} />
                  </td>
                  <td style={tdStyle}>{t.detection_method.replace(/_/g, " ")}</td>
                  <td style={tdStyle}>{t.vm_count}</td>
                  <td style={tdStyle}>{t.total_vcpu || 0}</td>
                  <td style={tdStyle}>{t.total_ram_mb ? (t.total_ram_mb / 1024).toFixed(0) : "0"}</td>
                  <td style={tdStyle}>{t.total_disk_gb ? Number(t.total_disk_gb).toFixed(1) : "0.0"}</td>
                  <td style={tdStyle}>{t.total_in_use_gb ? Number(t.total_in_use_gb).toFixed(1) : "0.0"}</td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 4 }}>
                      <button onClick={saveEdit} disabled={editSaving}
                        style={{ ...btnSmall, background: "#16a34a", color: "#fff" }}
                        title="Save">
                        {editSaving ? "..." : "✓"}
                      </button>
                      <button onClick={cancelEdit} style={{ ...btnSmall, background: "#e5e7eb" }}
                        title="Cancel">✕</button>
                    </div>
                  </td>
                </>
              ) : (
                <>
                  <td style={tdStyle}><strong>{t.tenant_name}</strong></td>
                  <td style={{ ...tdStyle, fontSize: "0.8rem", color: "#6b7280" }}>{t.org_vdc || "—"}</td>
                  <td style={tdStyle}>{t.detection_method.replace(/_/g, " ")}</td>
                  <td style={tdStyle}>{t.vm_count}</td>
                  <td style={tdStyle}>{t.total_vcpu || 0}</td>
                  <td style={tdStyle}>{t.total_ram_mb ? (t.total_ram_mb / 1024).toFixed(0) : "0"}</td>
                  <td style={tdStyle}>{t.total_disk_gb ? Number(t.total_disk_gb).toFixed(1) : "0.0"}</td>
                  <td style={tdStyle}>{t.total_in_use_gb ? Number(t.total_in_use_gb).toFixed(1) : "0.0"}</td>
                  <td style={tdStyle}>
                    <button onClick={() => startEdit(t)} style={btnSmall} title="Edit tenant name">✏️</button>
                  </td>
                </>
              )}
            </tr>
          ))}
          {tenants.length === 0 && (
            <tr><td colSpan={9} style={{ ...tdStyle, textAlign: "center", color: "#6b7280" }}>
              No tenants detected. Add rules above or run assessment.
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/* ================================================================== */
/*  Networks View                                                     */
/* ================================================================== */

function NetworksView({ networks, projectId, onRefresh }: {
  networks: NetworkSummary[]; projectId: number; onRefresh: () => void
}) {
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

  return (
    <div>
      <p style={{ color: "#6b7280", fontSize: "0.85rem", marginBottom: 12 }}>
        Network infrastructure extracted from RVTools. VLAN IDs and types are auto-detected from naming patterns.
        Click ✏️ to manually add subnet, gateway, DNS, and PCD target mapping.
      </p>
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
          {networks.map(n => (
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

  const downloadXlsx = () => {
    const url = `/api/migration/projects/${projectId}/export-report.xlsx`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `migration-plan-${projectName.replace(/\s+/g, "_")}.xlsx`;
    a.click();
  };

  const downloadPdf = () => {
    const url = `/api/migration/projects/${projectId}/export-report.pdf`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `migration-plan-${projectName.replace(/\s+/g, "_")}.pdf`;
    a.click();
  };

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
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
          <StatCard label="Total VMs" value={ps.total_vms} />
          <StatCard label="Total Disk (TB)" value={ps.total_disk_tb} />
          <StatCard label="Warm Eligible" value={ps.warm_eligible} />
          <StatCard label="Cold Required" value={ps.cold_required} />
          <StatCard label="Tenants" value={ps.total_tenants} />
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
              <th style={thStyle}>Phase1 (h)</th>
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
                            <th style={thStyleSm}>Warm Phase1</th>
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
                                {v.migration_mode !== "cold_required" ? (() => {
                                  const h = Number(v.warm_phase1_hours);
                                  return h < 0.017 ? "<1min" : h < 1 ? `${Math.round(h * 60)}min` : `${h.toFixed(2)}h`;
                                })() : "—"}
                              </td>
                              <td style={tdStyleSm}>
                                {v.migration_mode !== "cold_required" ? (() => {
                                  const h = Number(v.warm_cutover_hours);
                                  return h < 1 ? `${Math.round(h * 60)}min` : `${h.toFixed(2)}h`;
                                })() : (() => {
                                  const h = Number(v.cold_total_hours);
                                  return h < 1 ? `${Math.round(h * 60)}min` : `${h.toFixed(2)}h`;
                                })()}
                              </td>
                              <td style={tdStyleSm}>
                                <strong>
                                  {(() => {
                                    const h = v.migration_mode !== "cold_required"
                                      ? Number(v.warm_phase1_hours) + Number(v.warm_cutover_hours)
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
  borderBottomColor: "#3b82f6", color: "#3b82f6",
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
