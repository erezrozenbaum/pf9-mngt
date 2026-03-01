/**
 * ResourceManagementTab – System Resource Provisioning Tool
 * Manage users, flavors, networks, routers, floating IPs, volumes,
 * security groups, images, and quotas across tenants.
 */

import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";

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
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DomainOption { id: string; name: string; }
interface ProjectOption { id: string; name: string; domain_id: string; domain_name: string; }
interface ExtNetOption { id: string; name: string; }

type ResourceSection = "users" | "flavors" | "networks" | "routers" | "floating_ips" | "volumes" | "security_groups" | "images" | "quotas" | "audit_log";

interface Props { isAdmin?: boolean; }

const SECTIONS: { id: ResourceSection; label: string; icon: string }[] = [
  { id: "users", label: "Users", icon: "👤" },
  { id: "flavors", label: "Flavors", icon: "🍦" },
  { id: "networks", label: "Networks", icon: "🌐" },
  { id: "routers", label: "Routers", icon: "🔀" },
  { id: "floating_ips", label: "Floating IPs", icon: "🌊" },
  { id: "volumes", label: "Volumes", icon: "💾" },
  { id: "security_groups", label: "Security Groups", icon: "🔒" },
  { id: "images", label: "Images", icon: "📀" },
  { id: "quotas", label: "Quotas", icon: "📏" },
  { id: "audit_log", label: "Audit Log", icon: "📋" },
];

const ROLE_LABELS: Record<string, string> = {
  admin: "Administrator",
  member: "Self-service User",
  reader: "Read Only User",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ResourceManagementTab({ isAdmin }: Props) {
  const [activeSection, setActiveSection] = useState<ResourceSection>("users");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [data, setData] = useState<any[]>([]);

  // Context dropdowns
  const [domains, setDomains] = useState<DomainOption[]>([]);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [extNetworks, setExtNetworks] = useState<ExtNetOption[]>([]);
  const [filterDomainId, setFilterDomainId] = useState("");
  const [filterProjectId, setFilterProjectId] = useState("");

  // Create forms state
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [creating, setCreating] = useState(false);

  // User form
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newUserRole, setNewUserRole] = useState("member");
  const [newUserDomain, setNewUserDomain] = useState("");
  const [newUserProject, setNewUserProject] = useState("");

  // Flavor form
  const [newFlavorName, setNewFlavorName] = useState("");
  const [newFlavorVcpus, setNewFlavorVcpus] = useState(1);
  const [newFlavorRam, setNewFlavorRam] = useState(1024);
  const [newFlavorDisk, setNewFlavorDisk] = useState(10);
  const [newFlavorPublic, setNewFlavorPublic] = useState(true);

  // Network form
  const [newNetName, setNewNetName] = useState("");
  const [newNetProject, setNewNetProject] = useState("");
  const [newNetShared, setNewNetShared] = useState(false);
  const [newNetExternal, setNewNetExternal] = useState(false);
  const [newNetSubnetCidr, setNewNetSubnetCidr] = useState("");
  const [newNetEnableDhcp, setNewNetEnableDhcp] = useState(true);
  const [newNetKind, setNewNetKind] = useState<"virtual" | "physical_managed" | "physical_l2">("virtual");
  const [newNetType, setNewNetType] = useState("vlan");   // vlan | flat
  const [newNetPhysNet, setNewNetPhysNet] = useState("physnet1");
  const [newNetVlanId, setNewNetVlanId] = useState("");

  // Router form
  const [newRouterName, setNewRouterName] = useState("");
  const [newRouterProject, setNewRouterProject] = useState("");
  const [newRouterExtNet, setNewRouterExtNet] = useState("");

  // Floating IP form
  const [newFipNetwork, setNewFipNetwork] = useState("");
  const [newFipProject, setNewFipProject] = useState("");

  // Volume form
  const [newVolName, setNewVolName] = useState("");
  const [newVolSize, setNewVolSize] = useState(10);
  const [newVolProject, setNewVolProject] = useState("");

  // Security Group form
  const [newSgName, setNewSgName] = useState("");
  const [newSgDesc, setNewSgDesc] = useState("");
  const [newSgProject, setNewSgProject] = useState("");

  // Quotas form
  const [quotaProjectId, setQuotaProjectId] = useState("");
  const [quotaData, setQuotaData] = useState<any>(null);
  const [quotaEdits, setQuotaEdits] = useState<Record<string, number>>({});

  // Confirm delete
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string; name: string; type: string } | null>(null);

  // Audit log state
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [auditDays, setAuditDays] = useState(7);
  const [auditLoading, setAuditLoading] = useState(false);

  // Load context
  useEffect(() => {
    apiFetch<{ data: DomainOption[] }>("/api/resources/context/domains")
      .then((r) => setDomains(r.data))
      .catch(() => {});
    apiFetch<{ data: ProjectOption[] }>("/api/resources/context/projects")
      .then((r) => setProjects(r.data))
      .catch(() => {});
    apiFetch<{ data: ExtNetOption[] }>("/api/resources/context/external-networks")
      .then((r) => setExtNetworks(r.data))
      .catch(() => {});
  }, []);

  // Load data when section or filters change
  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    setData([]);
    try {
      const params = new URLSearchParams();
      if (filterProjectId) params.set("project_id", filterProjectId);
      else if (filterDomainId) params.set("domain_id", filterDomainId);
      const qs = params.toString() ? `?${params.toString()}` : "";

      const sectionEndpoints: Record<ResourceSection, string> = {
        users: "/api/resources/users",
        flavors: "/api/resources/flavors",
        networks: "/api/resources/networks",
        routers: "/api/resources/routers",
        floating_ips: "/api/resources/floating-ips",
        volumes: "/api/resources/volumes",
        security_groups: "/api/resources/security-groups",
        images: "/api/resources/images",
        quotas: "", // handled separately
        audit_log: "", // handled separately
      };

      if (activeSection === "quotas") {
        setData([]);
        setLoading(false);
        return;
      }

      if (activeSection === "audit_log") {
        setData([]);
        setLoading(false);
        loadAuditLog();
        return;
      }

      const endpoint = sectionEndpoints[activeSection];
      if (endpoint) {
        const result = await apiFetch<{ data: any[]; count: number }>(`${endpoint}${qs}`);
        setData(result.data);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [activeSection, filterDomainId, filterProjectId]);

  // Load audit log data from activity-log-export report
  const loadAuditLog = useCallback(async () => {
    setAuditLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("days", String(auditDays));
      const result = await apiFetch<{ data: any[]; count: number }>(
        `/api/reports/activity-log-export?${params.toString()}`
      );
      // Filter to resource management resource types
      const resourceTypes = new Set(["user", "flavor", "network", "router", "floating_ip", "volume", "security_group", "quotas"]);
      const filtered = (result.data || []).filter((row: any) => resourceTypes.has(row.resource_type));
      setAuditLogs(filtered);
    } catch (e: any) {
      setAuditLogs([]);
      setError(e.message);
    } finally {
      setAuditLoading(false);
    }
  }, [auditDays]);

  useEffect(() => {
    loadData();
    setShowCreateForm(false);
  }, [loadData]);

  // Auto-clear messages
  useEffect(() => {
    if (success) {
      const t = setTimeout(() => setSuccess(""), 5000);
      return () => clearTimeout(t);
    }
  }, [success]);

  // Load quotas
  const loadQuotas = useCallback(async () => {
    if (!quotaProjectId) return;
    setLoading(true);
    try {
      const result = await apiFetch<any>(`/api/resources/quotas/${quotaProjectId}`);
      setQuotaData(result);
      setQuotaEdits({});
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [quotaProjectId]);

  // Create handlers
  const handleCreate = async () => {
    setCreating(true);
    setError("");
    try {
      switch (activeSection) {
        case "users":
          await apiFetch("/api/resources/users", {
            method: "POST",
            body: JSON.stringify({
              username: newUsername,
              password: newPassword,
              email: newEmail,
              role: newUserRole,
              project_id: newUserProject,
              domain_id: newUserDomain,
            }),
          });
          setSuccess(`User '${newUsername}' created successfully`);
          setNewUsername(""); setNewPassword(""); setNewEmail("");
          break;

        case "flavors":
          await apiFetch("/api/resources/flavors", {
            method: "POST",
            body: JSON.stringify({
              name: newFlavorName,
              vcpus: newFlavorVcpus,
              ram_mb: newFlavorRam,
              disk_gb: newFlavorDisk,
              is_public: newFlavorPublic,
            }),
          });
          setSuccess(`Flavor '${newFlavorName}' created successfully`);
          setNewFlavorName("");
          break;

        case "networks": {
          const isPhysical = newNetKind !== "virtual";
          const body: Record<string, unknown> = {
            name: newNetName,
            project_id: newNetProject,
            shared: newNetShared,
            external: newNetKind === "physical_managed",
            enable_dhcp: newNetEnableDhcp,
          };
          if (isPhysical) {
            body.network_type = newNetType;
            body.physical_network = newNetPhysNet;
            if (newNetVlanId) body.segmentation_id = parseInt(newNetVlanId);
          }
          // Physical L2 doesn't get a subnet; others respect the CIDR field
          if (newNetKind !== "physical_l2" && newNetSubnetCidr)
            body.subnet_cidr = newNetSubnetCidr;
          await apiFetch("/api/resources/networks", { method: "POST", body: JSON.stringify(body) });
          setSuccess(`Network '${newNetName}' created successfully`);
          setNewNetName(""); setNewNetSubnetCidr(""); setNewNetVlanId("");
          break;
        }

        case "routers":
          await apiFetch("/api/resources/routers", {
            method: "POST",
            body: JSON.stringify({
              name: newRouterName,
              project_id: newRouterProject,
              external_network_id: newRouterExtNet || undefined,
            }),
          });
          setSuccess(`Router '${newRouterName}' created successfully`);
          setNewRouterName("");
          break;

        case "floating_ips":
          await apiFetch("/api/resources/floating-ips", {
            method: "POST",
            body: JSON.stringify({
              floating_network_id: newFipNetwork,
              project_id: newFipProject,
            }),
          });
          setSuccess("Floating IP allocated successfully");
          break;

        case "volumes":
          await apiFetch("/api/resources/volumes", {
            method: "POST",
            body: JSON.stringify({
              name: newVolName,
              size_gb: newVolSize,
              project_id: newVolProject,
            }),
          });
          setSuccess(`Volume '${newVolName}' created successfully`);
          setNewVolName("");
          break;

        case "security_groups":
          await apiFetch("/api/resources/security-groups", {
            method: "POST",
            body: JSON.stringify({
              name: newSgName,
              description: newSgDesc,
              project_id: newSgProject || undefined,
            }),
          });
          setSuccess(`Security group '${newSgName}' created successfully`);
          setNewSgName(""); setNewSgDesc("");
          break;
      }
      setShowCreateForm(false);
      loadData();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCreating(false);
    }
  };

  // Delete handler
  const handleDelete = async (id: string, type: string) => {
    setError("");
    try {
      const endpointMap: Record<string, string> = {
        user: "/api/resources/users",
        flavor: "/api/resources/flavors",
        network: "/api/resources/networks",
        router: "/api/resources/routers",
        floating_ip: "/api/resources/floating-ips",
        volume: "/api/resources/volumes",
        security_group: "/api/resources/security-groups",
      };
      const base = endpointMap[type];
      if (!base) throw new Error("Unknown resource type");
      await apiFetch(`${base}/${id}`, { method: "DELETE" });
      setSuccess(`${type.replace("_", " ")} deleted successfully`);
      setDeleteConfirm(null);
      loadData();
    } catch (e: any) {
      setError(e.message);
      setDeleteConfirm(null);
    }
  };

  // Update quotas handler
  const handleUpdateQuotas = async () => {
    if (!quotaProjectId || Object.keys(quotaEdits).length === 0) return;
    setCreating(true);
    setError("");
    try {
      await apiFetch("/api/resources/quotas", {
        method: "PUT",
        body: JSON.stringify({ project_id: quotaProjectId, ...quotaEdits }),
      });
      setSuccess("Quotas updated successfully");
      loadQuotas();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCreating(false);
    }
  };

  // -----------------------------------------------------------------------
  // Styles
  // -----------------------------------------------------------------------
  const containerStyle: React.CSSProperties = { display: "flex", minHeight: "600px" };
  const sidebarStyle: React.CSSProperties = {
    width: "200px",
    borderRight: "1px solid var(--pf9-border, #d1d5db)",
    padding: "12px 0",
    flexShrink: 0,
  };
  const navItemStyle = (active: boolean): React.CSSProperties => ({
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "10px 16px",
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: active ? 600 : 400,
    color: active ? "#3b82f6" : "var(--pf9-text, #111827)",
    background: active ? "var(--pf9-hover, #dbeafe)" : "transparent",
    borderLeft: active ? "3px solid #3b82f6" : "3px solid transparent",
    transition: "all 0.15s",
  });
  const mainStyle: React.CSSProperties = { flex: 1, padding: "20px 24px", overflow: "auto" };
  const headerStyle: React.CSSProperties = {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    marginBottom: "16px", flexWrap: "wrap", gap: "10px",
  };
  const btnStyle = (variant: string, small = false): React.CSSProperties => ({
    padding: small ? "4px 12px" : "8px 18px",
    borderRadius: "6px",
    border: variant === "outline" ? "1px solid var(--pf9-border, #d1d5db)" : "none",
    fontWeight: 600, fontSize: small ? "12px" : "13px", cursor: "pointer",
    color: variant === "danger" ? "#fff" : variant === "outline" ? "var(--pf9-text, #111827)" : "#fff",
    background: variant === "primary" ? "#3b82f6" : variant === "danger" ? "#ef4444" : variant === "success" ? "#10b981" : "transparent",
  });
  const selectStyle: React.CSSProperties = {
    padding: "6px 10px", borderRadius: "6px",
    border: "1px solid var(--pf9-border, #d1d5db)",
    background: "var(--pf9-input-bg, #ffffff)",
    color: "var(--pf9-text, #111827)", fontSize: "13px",
  };
  const inputStyle: React.CSSProperties = { ...selectStyle, minWidth: "180px" };
  const formGroupStyle: React.CSSProperties = {
    display: "flex", flexDirection: "column", gap: "4px",
  };
  const formRowStyle: React.CSSProperties = {
    display: "flex", gap: "12px", flexWrap: "wrap", marginBottom: "12px", alignItems: "flex-end",
  };
  const labelStyle: React.CSSProperties = { fontSize: "12px", fontWeight: 600, color: "var(--pf9-text-secondary, #9ca3af)" };
  const tableContainerStyle: React.CSSProperties = {
    overflowX: "auto", borderRadius: "8px",
    border: "1px solid var(--pf9-border, #d1d5db)",
  };
  const thStyle: React.CSSProperties = {
    padding: "8px 12px", textAlign: "left", fontSize: "12px", fontWeight: 600,
    color: "var(--pf9-text-secondary, #6b7280)",
    background: "var(--pf9-header-bg, #f3f4f6)",
    borderBottom: "1px solid var(--pf9-border, #d1d5db)", whiteSpace: "nowrap",
  };
  const tdStyle: React.CSSProperties = {
    padding: "6px 12px", fontSize: "13px", color: "var(--pf9-text, #111827)",
    borderBottom: "1px solid var(--pf9-border, #d1d5db)", whiteSpace: "nowrap",
  };
  const formPanelStyle: React.CSSProperties = {
    padding: "16px", borderRadius: "10px",
    border: "1px solid var(--pf9-border, #d1d5db)",
    background: "var(--pf9-card-bg, #ffffff)", marginBottom: "16px",
  };
  const statusBadge = (color: string): React.CSSProperties => ({
    display: "inline-block", padding: "2px 8px", borderRadius: "10px",
    background: `${color}25`, color, fontSize: "11px", fontWeight: 600,
  });
  const msgStyle = (type: string): React.CSSProperties => ({
    padding: "10px 16px", borderRadius: "8px",
    background: type === "error" ? "#991b1b33" : "#065f4633",
    color: type === "error" ? "#ef4444" : "#10b981",
    marginBottom: "12px", fontSize: "13px",
  });

  // Filter projects by domain
  const filteredProjects = filterDomainId
    ? projects.filter((p) => p.domain_id === filterDomainId)
    : projects;

  // -----------------------------------------------------------------------
  // Create Forms
  // -----------------------------------------------------------------------
  const renderCreateForm = () => {
    switch (activeSection) {
      case "users":
        return (
          <div style={formPanelStyle}>
            <h4 style={{ margin: "0 0 12px", fontSize: "14px" }}>➕ Add User to Tenant</h4>
            <div style={formRowStyle}>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Domain *</span>
                <select value={newUserDomain} onChange={(e) => setNewUserDomain(e.target.value)} style={selectStyle}>
                  <option value="">Select domain</option>
                  {domains.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Tenant / Project *</span>
                <select value={newUserProject} onChange={(e) => setNewUserProject(e.target.value)} style={selectStyle}>
                  <option value="">Select tenant</option>
                  {(newUserDomain ? projects.filter(p => p.domain_id === newUserDomain) : projects).map((p) =>
                    <option key={p.id} value={p.id}>{p.name} ({p.domain_name})</option>
                  )}
                </select>
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Username *</span>
                <input value={newUsername} onChange={(e) => setNewUsername(e.target.value)} style={inputStyle} placeholder="e.g. john.doe" />
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Password *</span>
                <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} style={inputStyle} placeholder="Min 6 chars" />
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Email</span>
                <input value={newEmail} onChange={(e) => setNewEmail(e.target.value)} style={inputStyle} placeholder="user@example.com" />
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Role *</span>
                <select value={newUserRole} onChange={(e) => setNewUserRole(e.target.value)} style={selectStyle}>
                  <option value="member">{ROLE_LABELS.member}</option>
                  <option value="admin">{ROLE_LABELS.admin}</option>
                  <option value="reader">{ROLE_LABELS.reader}</option>
                </select>
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button style={btnStyle("primary")} onClick={handleCreate} disabled={creating || !newUsername || !newPassword || !newUserProject || !newUserDomain}>
                {creating ? "Creating..." : "Create User"}
              </button>
              <button style={btnStyle("outline")} onClick={() => setShowCreateForm(false)}>Cancel</button>
            </div>
          </div>
        );

      case "flavors":
        return (
          <div style={formPanelStyle}>
            <h4 style={{ margin: "0 0 12px", fontSize: "14px" }}>➕ Create Flavor</h4>
            <div style={formRowStyle}>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Name *</span>
                <input value={newFlavorName} onChange={(e) => setNewFlavorName(e.target.value)} style={inputStyle} placeholder="e.g. m1.small" />
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>vCPUs *</span>
                <input type="number" value={newFlavorVcpus} min={1} max={128} onChange={(e) => setNewFlavorVcpus(parseInt(e.target.value) || 1)} style={{ ...inputStyle, width: "80px" }} />
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>RAM (MB) *</span>
                <input type="number" value={newFlavorRam} min={128} max={131072} onChange={(e) => setNewFlavorRam(parseInt(e.target.value) || 1024)} style={{ ...inputStyle, width: "100px" }} />
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Disk (GB) *</span>
                <input type="number" value={newFlavorDisk} min={0} max={2048} onChange={(e) => setNewFlavorDisk(parseInt(e.target.value) || 0)} style={{ ...inputStyle, width: "80px" }} />
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Public</span>
                <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
                  <input type="checkbox" checked={newFlavorPublic} onChange={(e) => setNewFlavorPublic(e.target.checked)} />
                  {newFlavorPublic ? "Yes" : "No"}
                </label>
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button style={btnStyle("primary")} onClick={handleCreate} disabled={creating || !newFlavorName}>
                {creating ? "Creating..." : "Create Flavor"}
              </button>
              <button style={btnStyle("outline")} onClick={() => setShowCreateForm(false)}>Cancel</button>
            </div>
          </div>
        );

      case "networks":
        return (
          <div style={formPanelStyle}>
            <h4 style={{ margin: "0 0 12px", fontSize: "14px" }}>➕ Create Network</h4>
            {/* Kind selector */}
            <div style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
              {(["virtual", "physical_managed", "physical_l2"] as const).map((k) => (
                <button key={k} onClick={() => setNewNetKind(k)}
                  style={{
                    ...btnStyle(newNetKind === k ? "primary" : "outline"),
                    fontSize: "12px", padding: "5px 10px",
                  }}>
                  {k === "virtual" ? "☁️ Virtual" : k === "physical_managed" ? "🔌 Physical Managed" : "🔗 Physical L2 (Beta)"}
                </button>
              ))}
            </div>
            <div style={formRowStyle}>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Tenant *</span>
                <select value={newNetProject} onChange={(e) => setNewNetProject(e.target.value)} style={selectStyle}>
                  <option value="">Select tenant</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.domain_name})</option>)}
                </select>
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Name *</span>
                <input value={newNetName} onChange={(e) => setNewNetName(e.target.value)} style={inputStyle} placeholder="e.g. internal-net" />
              </div>
              {/* Provider fields — only for physical kinds */}
              {newNetKind !== "virtual" && (
                <>
                  <div style={formGroupStyle}>
                    <span style={labelStyle}>Physical Network</span>
                    <input value={newNetPhysNet} onChange={(e) => setNewNetPhysNet(e.target.value)} style={inputStyle} placeholder="physnet1" />
                  </div>
                  <div style={formGroupStyle}>
                    <span style={labelStyle}>Provider Type</span>
                    <select value={newNetType} onChange={(e) => setNewNetType(e.target.value)} style={selectStyle}>
                      <option value="vlan">VLAN</option>
                      <option value="flat">Flat</option>
                    </select>
                  </div>
                  {newNetType === "vlan" && (
                    <div style={formGroupStyle}>
                      <span style={labelStyle}>VLAN ID</span>
                      <input type="number" value={newNetVlanId} onChange={(e) => setNewNetVlanId(e.target.value)} style={inputStyle} placeholder="e.g. 100" />
                    </div>
                  )}
                </>
              )}
              {/* Subnet CIDR — not for L2 */}
              {newNetKind !== "physical_l2" && (
                <div style={formGroupStyle}>
                  <span style={labelStyle}>Subnet CIDR</span>
                  <input value={newNetSubnetCidr} onChange={(e) => setNewNetSubnetCidr(e.target.value)} style={inputStyle} placeholder="e.g. 10.0.0.0/24" />
                </div>
              )}
              <div style={formGroupStyle}>
                <span style={labelStyle}>Options</span>
                <div style={{ display: "flex", gap: "12px", fontSize: "13px" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                    <input type="checkbox" checked={newNetShared} onChange={(e) => setNewNetShared(e.target.checked)} /> Shared
                  </label>
                  {newNetKind !== "physical_l2" && (
                    <label style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                      <input type="checkbox" checked={newNetEnableDhcp} onChange={(e) => setNewNetEnableDhcp(e.target.checked)} /> DHCP
                    </label>
                  )}
                </div>
              </div>
            </div>
            {newNetKind === "physical_managed" && (
              <p style={{ margin: "0 0 10px", fontSize: "12px", color: "#718096" }}>⚠️ Physical Managed network will be marked external and shared with the tenant project.</p>
            )}
            {newNetKind === "physical_l2" && (
              <p style={{ margin: "0 0 10px", fontSize: "12px", color: "#718096" }}>ℹ️ Layer 2 network — no subnet or DHCP will be provisioned.</p>
            )}
            <div style={{ display: "flex", gap: "8px" }}>
              <button style={btnStyle("primary")} onClick={handleCreate} disabled={creating || !newNetName || !newNetProject}>
                {creating ? "Creating..." : "Create Network"}
              </button>
              <button style={btnStyle("outline")} onClick={() => setShowCreateForm(false)}>Cancel</button>
            </div>
          </div>
        );

      case "routers":
        return (
          <div style={formPanelStyle}>
            <h4 style={{ margin: "0 0 12px", fontSize: "14px" }}>➕ Create Router</h4>
            <div style={formRowStyle}>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Tenant *</span>
                <select value={newRouterProject} onChange={(e) => setNewRouterProject(e.target.value)} style={selectStyle}>
                  <option value="">Select tenant</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.domain_name})</option>)}
                </select>
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Name *</span>
                <input value={newRouterName} onChange={(e) => setNewRouterName(e.target.value)} style={inputStyle} placeholder="e.g. external-router" />
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>External Network</span>
                <select value={newRouterExtNet} onChange={(e) => setNewRouterExtNet(e.target.value)} style={selectStyle}>
                  <option value="">None (internal only)</option>
                  {extNetworks.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
                </select>
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button style={btnStyle("primary")} onClick={handleCreate} disabled={creating || !newRouterName || !newRouterProject}>
                {creating ? "Creating..." : "Create Router"}
              </button>
              <button style={btnStyle("outline")} onClick={() => setShowCreateForm(false)}>Cancel</button>
            </div>
          </div>
        );

      case "floating_ips":
        return (
          <div style={formPanelStyle}>
            <h4 style={{ margin: "0 0 12px", fontSize: "14px" }}>➕ Allocate Floating IP</h4>
            <div style={formRowStyle}>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Tenant *</span>
                <select value={newFipProject} onChange={(e) => setNewFipProject(e.target.value)} style={selectStyle}>
                  <option value="">Select tenant</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.domain_name})</option>)}
                </select>
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>External Network *</span>
                <select value={newFipNetwork} onChange={(e) => setNewFipNetwork(e.target.value)} style={selectStyle}>
                  <option value="">Select network</option>
                  {extNetworks.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
                </select>
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button style={btnStyle("primary")} onClick={handleCreate} disabled={creating || !newFipNetwork || !newFipProject}>
                {creating ? "Allocating..." : "Allocate IP"}
              </button>
              <button style={btnStyle("outline")} onClick={() => setShowCreateForm(false)}>Cancel</button>
            </div>
          </div>
        );

      case "volumes":
        return (
          <div style={formPanelStyle}>
            <h4 style={{ margin: "0 0 12px", fontSize: "14px" }}>➕ Create Volume</h4>
            <div style={formRowStyle}>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Tenant *</span>
                <select value={newVolProject} onChange={(e) => setNewVolProject(e.target.value)} style={selectStyle}>
                  <option value="">Select tenant</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.domain_name})</option>)}
                </select>
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Name *</span>
                <input value={newVolName} onChange={(e) => setNewVolName(e.target.value)} style={inputStyle} placeholder="e.g. data-vol-01" />
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Size (GB) *</span>
                <input type="number" value={newVolSize} min={1} max={16384} onChange={(e) => setNewVolSize(parseInt(e.target.value) || 10)} style={{ ...inputStyle, width: "80px" }} />
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button style={btnStyle("primary")} onClick={handleCreate} disabled={creating || !newVolName || !newVolProject}>
                {creating ? "Creating..." : "Create Volume"}
              </button>
              <button style={btnStyle("outline")} onClick={() => setShowCreateForm(false)}>Cancel</button>
            </div>
          </div>
        );

      case "security_groups":
        return (
          <div style={formPanelStyle}>
            <h4 style={{ margin: "0 0 12px", fontSize: "14px" }}>➕ Create Security Group</h4>
            <div style={formRowStyle}>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Tenant</span>
                <select value={newSgProject} onChange={(e) => setNewSgProject(e.target.value)} style={selectStyle}>
                  <option value="">Default (admin project)</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.domain_name})</option>)}
                </select>
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Name *</span>
                <input value={newSgName} onChange={(e) => setNewSgName(e.target.value)} style={inputStyle} placeholder="e.g. web-servers" />
              </div>
              <div style={formGroupStyle}>
                <span style={labelStyle}>Description</span>
                <input value={newSgDesc} onChange={(e) => setNewSgDesc(e.target.value)} style={inputStyle} placeholder="Optional description" />
              </div>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button style={btnStyle("primary")} onClick={handleCreate} disabled={creating || !newSgName}>
                {creating ? "Creating..." : "Create Security Group"}
              </button>
              <button style={btnStyle("outline")} onClick={() => setShowCreateForm(false)}>Cancel</button>
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  // -----------------------------------------------------------------------
  // Data Tables
  // -----------------------------------------------------------------------
  const renderTable = () => {
    if (activeSection === "quotas") return renderQuotas();
    if (activeSection === "audit_log") return renderAuditLog();
    if (loading) return <div style={{ textAlign: "center", padding: "40px", color: "var(--pf9-text-secondary)" }}>Loading...</div>;
    if (data.length === 0) return <div style={{ textAlign: "center", padding: "40px", color: "var(--pf9-text-secondary)" }}>No {activeSection.replace("_", " ")} found{filterProjectId ? " for this tenant" : ""}.</div>;

    switch (activeSection) {
      case "users": return renderUsersTable();
      case "flavors": return renderFlavorsTable();
      case "networks": return renderNetworksTable();
      case "routers": return renderRoutersTable();
      case "floating_ips": return renderFipsTable();
      case "volumes": return renderVolumesTable();
      case "security_groups": return renderSgsTable();
      case "images": return renderImagesTable();
      default: return null;
    }
  };

  const actionColor = (action: string) => {
    if (action.startsWith("create") || action === "allocate") return "#10b981";
    if (action.startsWith("delete") || action === "release") return "#ef4444";
    if (action.startsWith("update") || action.includes("interface") || action === "assign_role") return "#f59e0b";
    return "#6b7280";
  };

  const renderAuditLog = () => (
    <div>
      <div style={{ display: "flex", gap: "12px", alignItems: "center", marginBottom: "16px" }}>
        <label style={labelStyle}>Time Range:</label>
        <select value={auditDays} onChange={(e) => setAuditDays(Number(e.target.value))} style={selectStyle}>
          <option value={1}>Last 24 hours</option>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
        <button style={btnStyle("primary", true)} onClick={loadAuditLog}>
          🔄 Refresh
        </button>
        <span style={{ fontSize: "12px", color: "var(--pf9-text-secondary, #9ca3af)" }}>
          {auditLogs.length} entries
        </span>
      </div>
      {auditLoading ? (
        <div style={{ textAlign: "center", padding: "40px", color: "var(--pf9-text-secondary)" }}>Loading audit log...</div>
      ) : auditLogs.length === 0 ? (
        <div style={{ textAlign: "center", padding: "40px", color: "var(--pf9-text-secondary)" }}>No resource management activity found.</div>
      ) : (
        <div style={tableContainerStyle}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Timestamp</th>
                <th style={thStyle}>Actor</th>
                <th style={thStyle}>Action</th>
                <th style={thStyle}>Resource Type</th>
                <th style={thStyle}>Resource Name</th>
                <th style={thStyle}>Resource ID</th>
                <th style={thStyle}>Domain</th>
                <th style={thStyle}>IP Address</th>
                <th style={thStyle}>Result</th>
              </tr>
            </thead>
            <tbody>
              {auditLogs.map((log: any, i: number) => (
                <tr key={i} style={i % 2 === 1 ? { background: "var(--pf9-row-alt, transparent)" } : undefined}>
                  <td style={tdStyle}>{log.timestamp ? new Date(log.timestamp).toLocaleString() : ""}</td>
                  <td style={tdStyle}><strong>{log.actor}</strong></td>
                  <td style={tdStyle}>
                    <span style={{ ...statusBadge(actionColor(log.action || "")), textTransform: "uppercase", letterSpacing: "0.5px" }}>
                      {(log.action || "").replace(/_/g, " ")}
                    </span>
                  </td>
                  <td style={tdStyle}>{(log.resource_type || "").replace(/_/g, " ")}</td>
                  <td style={tdStyle}>{log.resource_name || "—"}</td>
                  <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: "11px" }}>
                    {log.resource_id ? `${log.resource_id.substring(0, 8)}...` : "—"}
                  </td>
                  <td style={tdStyle}>{log.domain_name || "—"}</td>
                  <td style={tdStyle}>{log.ip_address || "—"}</td>
                  <td style={tdStyle}>
                    <span style={statusBadge(log.result === "success" ? "#10b981" : "#ef4444")}>
                      {log.result}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  const renderUsersTable = () => (
    <div style={tableContainerStyle}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Username</th><th style={thStyle}>Email</th><th style={thStyle}>Domain</th>
            <th style={thStyle}>Enabled</th><th style={thStyle}>Description</th><th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((u: any) => (
            <tr key={u.id}>
              <td style={tdStyle}><strong>{u.name}</strong><br /><span style={{ fontSize: "10px", color: "#6b7280" }}>{u.id}</span></td>
              <td style={tdStyle}>{u.email || "—"}</td>
              <td style={tdStyle}>{u.domain_name}</td>
              <td style={tdStyle}>{u.enabled ? <span style={statusBadge("#10b981")}>Active</span> : <span style={statusBadge("#ef4444")}>Disabled</span>}</td>
              <td style={tdStyle}>{u.description || "—"}</td>
              <td style={tdStyle}>
                {isAdmin && (
                  <button style={btnStyle("danger", true)} onClick={() => setDeleteConfirm({ id: u.id, name: u.name, type: "user" })}>
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderFlavorsTable = () => (
    <div style={tableContainerStyle}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Name</th><th style={thStyle}>vCPUs</th><th style={thStyle}>RAM</th>
            <th style={thStyle}>Disk</th><th style={thStyle}>Public</th><th style={thStyle}>Instances</th><th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((f: any) => (
            <tr key={f.id}>
              <td style={tdStyle}><strong>{f.name}</strong><br /><span style={{ fontSize: "10px", color: "#6b7280" }}>{f.id}</span></td>
              <td style={tdStyle}>{f.vcpus}</td>
              <td style={tdStyle}>{f.ram_mb >= 1024 ? `${(f.ram_mb / 1024).toFixed(1)} GB` : `${f.ram_mb} MB`}</td>
              <td style={tdStyle}>{f.disk_gb} GB</td>
              <td style={tdStyle}>{f.is_public ? "✅" : "❌"}</td>
              <td style={tdStyle}><span style={statusBadge(f.instance_count > 0 ? "#3b82f6" : "#6b7280")}>{f.instance_count}</span></td>
              <td style={tdStyle}>
                {isAdmin && (
                  <button style={btnStyle("danger", true)} onClick={() => setDeleteConfirm({ id: f.id, name: f.name, type: "flavor" })}>
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderNetworksTable = () => (
    <div style={tableContainerStyle}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Name</th><th style={thStyle}>Tenant</th><th style={thStyle}>Status</th>
            <th style={thStyle}>Shared</th><th style={thStyle}>External</th><th style={thStyle}>Subnets</th><th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((n: any) => (
            <tr key={n.id}>
              <td style={tdStyle}><strong>{n.name}</strong><br /><span style={{ fontSize: "10px", color: "#6b7280" }}>{n.id}</span></td>
              <td style={tdStyle}>{n.project_name || n.project_id}</td>
              <td style={tdStyle}><span style={statusBadge(n.status === "ACTIVE" ? "#10b981" : "#f59e0b")}>{n.status}</span></td>
              <td style={tdStyle}>{n.shared ? "✅" : "—"}</td>
              <td style={tdStyle}>{n.external ? "🌐" : "—"}</td>
              <td style={tdStyle}>
                {n.subnets?.map((s: any) => (
                  <div key={s.id} style={{ fontSize: "11px" }}>{s.name}: {s.cidr}</div>
                ))}
                {(!n.subnets || n.subnets.length === 0) && "—"}
              </td>
              <td style={tdStyle}>
                {isAdmin && (
                  <button style={btnStyle("danger", true)} onClick={() => setDeleteConfirm({ id: n.id, name: n.name, type: "network" })}>
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderRoutersTable = () => (
    <div style={tableContainerStyle}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Name</th><th style={thStyle}>Tenant</th><th style={thStyle}>Status</th>
            <th style={thStyle}>External GW</th><th style={thStyle}>Admin State</th><th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r: any) => (
            <tr key={r.id}>
              <td style={tdStyle}><strong>{r.name}</strong><br /><span style={{ fontSize: "10px", color: "#6b7280" }}>{r.id}</span></td>
              <td style={tdStyle}>{r.project_name || r.project_id}</td>
              <td style={tdStyle}><span style={statusBadge(r.status === "ACTIVE" ? "#10b981" : "#f59e0b")}>{r.status}</span></td>
              <td style={tdStyle}>{r.external_gateway ? `🌐 ${r.external_network_id?.slice(0, 8)}...` : "—"}</td>
              <td style={tdStyle}>{r.admin_state_up ? "Up" : "Down"}</td>
              <td style={tdStyle}>
                {isAdmin && (
                  <button style={btnStyle("danger", true)} onClick={() => setDeleteConfirm({ id: r.id, name: r.name, type: "router" })}>
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderFipsTable = () => (
    <div style={tableContainerStyle}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Floating IP</th><th style={thStyle}>Fixed IP</th><th style={thStyle}>Tenant</th>
            <th style={thStyle}>Status</th><th style={thStyle}>Associated</th><th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((f: any) => (
            <tr key={f.id}>
              <td style={tdStyle}><strong>{f.floating_ip_address}</strong><br /><span style={{ fontSize: "10px", color: "#6b7280" }}>{f.id}</span></td>
              <td style={tdStyle}>{f.fixed_ip_address || "—"}</td>
              <td style={tdStyle}>{f.project_name || f.project_id}</td>
              <td style={tdStyle}><span style={statusBadge(f.status === "ACTIVE" ? "#10b981" : "#f59e0b")}>{f.status}</span></td>
              <td style={tdStyle}>{f.associated ? "🔗 Yes" : <span style={{ color: "#f59e0b" }}>⚠ Unused</span>}</td>
              <td style={tdStyle}>
                {isAdmin && (
                  <button style={btnStyle("danger", true)} onClick={() => setDeleteConfirm({ id: f.id, name: f.floating_ip_address, type: "floating_ip" })}>
                    Release
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderVolumesTable = () => (
    <div style={tableContainerStyle}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Name</th><th style={thStyle}>Size</th><th style={thStyle}>Tenant</th>
            <th style={thStyle}>Status</th><th style={thStyle}>Type</th><th style={thStyle}>Attached</th><th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((v: any) => (
            <tr key={v.id}>
              <td style={tdStyle}><strong>{v.name || "(unnamed)"}</strong><br /><span style={{ fontSize: "10px", color: "#6b7280" }}>{v.id}</span></td>
              <td style={tdStyle}>{v.size_gb} GB</td>
              <td style={tdStyle}>{v.project_name || v.project_id}</td>
              <td style={tdStyle}><span style={statusBadge(v.status === "available" ? "#10b981" : v.status === "in-use" ? "#3b82f6" : "#f59e0b")}>{v.status}</span></td>
              <td style={tdStyle}>{v.volume_type || "—"}</td>
              <td style={tdStyle}>{v.attached_to ? `🔗 ${v.attached_to.slice(0, 8)}...` : <span style={{ color: "#f59e0b" }}>Unattached</span>}</td>
              <td style={tdStyle}>
                {isAdmin && (
                  <button style={btnStyle("danger", true)} onClick={() => setDeleteConfirm({ id: v.id, name: v.name || v.id, type: "volume" })}>
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderSgsTable = () => (
    <div style={tableContainerStyle}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Name</th><th style={thStyle}>Tenant</th><th style={thStyle}>Description</th>
            <th style={thStyle}>Rules</th><th style={thStyle}>Ingress</th><th style={thStyle}>Egress</th><th style={thStyle}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((sg: any) => (
            <tr key={sg.id}>
              <td style={tdStyle}><strong>{sg.name}</strong><br /><span style={{ fontSize: "10px", color: "#6b7280" }}>{sg.id}</span></td>
              <td style={tdStyle}>{sg.project_name || sg.project_id}</td>
              <td style={tdStyle}>{sg.description || "—"}</td>
              <td style={tdStyle}><span style={statusBadge("#3b82f6")}>{sg.rule_count}</span></td>
              <td style={tdStyle}>{sg.ingress_rules}</td>
              <td style={tdStyle}>{sg.egress_rules}</td>
              <td style={tdStyle}>
                {isAdmin && sg.name !== "default" && (
                  <button style={btnStyle("danger", true)} onClick={() => setDeleteConfirm({ id: sg.id, name: sg.name, type: "security_group" })}>
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderImagesTable = () => (
    <div style={tableContainerStyle}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Name</th><th style={thStyle}>Status</th><th style={thStyle}>Visibility</th>
            <th style={thStyle}>Size</th><th style={thStyle}>Format</th><th style={thStyle}>Min Disk</th><th style={thStyle}>Created</th>
          </tr>
        </thead>
        <tbody>
          {data.map((img: any) => (
            <tr key={img.id}>
              <td style={tdStyle}><strong>{img.name}</strong><br /><span style={{ fontSize: "10px", color: "#6b7280" }}>{img.id}</span></td>
              <td style={tdStyle}><span style={statusBadge(img.status === "active" ? "#10b981" : "#f59e0b")}>{img.status}</span></td>
              <td style={tdStyle}><span style={statusBadge(img.visibility === "public" ? "#3b82f6" : "#6b7280")}>{img.visibility}</span></td>
              <td style={tdStyle}>{img.size_mb > 1024 ? `${(img.size_mb / 1024).toFixed(1)} GB` : `${img.size_mb} MB`}</td>
              <td style={tdStyle}>{img.disk_format}</td>
              <td style={tdStyle}>{img.min_disk_gb} GB</td>
              <td style={tdStyle}>{img.created_at ? new Date(img.created_at).toLocaleDateString() : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  // -----------------------------------------------------------------------
  // Quotas section
  // -----------------------------------------------------------------------
  const renderQuotas = () => {
    const quotaFields = [
      { category: "Compute", items: [
        { key: "cores", label: "vCPUs", path: "compute" },
        { key: "ram", label: "RAM (MB)", path: "compute" },
        { key: "instances", label: "Instances", path: "compute" },
      ]},
      { category: "Network", items: [
        { key: "network", label: "Networks", path: "network" },
        { key: "subnet", label: "Subnets", path: "network" },
        { key: "router", label: "Routers", path: "network" },
        { key: "port", label: "Ports", path: "network" },
        { key: "floatingip", label: "Floating IPs", path: "network" },
        { key: "security_group", label: "Security Groups", path: "network" },
        { key: "security_group_rule", label: "SG Rules", path: "network" },
      ]},
      { category: "Storage", items: [
        { key: "gigabytes", label: "Storage (GB)", path: "storage" },
        { key: "volumes", label: "Volumes", path: "storage" },
        { key: "snapshots", label: "Snapshots", path: "storage" },
      ]},
    ];

    return (
      <div>
        <div style={{ display: "flex", gap: "12px", marginBottom: "16px", alignItems: "flex-end" }}>
          <div style={formGroupStyle}>
            <span style={labelStyle}>Select Tenant</span>
            <select value={quotaProjectId} onChange={(e) => { setQuotaProjectId(e.target.value); setQuotaData(null); }} style={selectStyle}>
              <option value="">Select a tenant...</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.domain_name})</option>)}
            </select>
          </div>
          <button style={btnStyle("primary")} onClick={loadQuotas} disabled={!quotaProjectId || loading}>
            {loading ? "Loading..." : "Load Quotas"}
          </button>
          {quotaData && Object.keys(quotaEdits).length > 0 && (
            <button style={btnStyle("success")} onClick={handleUpdateQuotas} disabled={creating}>
              {creating ? "Saving..." : `Save Changes (${Object.keys(quotaEdits).length})`}
            </button>
          )}
        </div>

        {quotaData && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "16px" }}>
            {quotaFields.map((cat) => (
              <div key={cat.category} style={formPanelStyle}>
                <h4 style={{ margin: "0 0 12px", fontSize: "14px" }}>{cat.category} Quotas</h4>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={{ ...thStyle, padding: "4px 8px" }}>Resource</th>
                      <th style={{ ...thStyle, padding: "4px 8px" }}>Current</th>
                      <th style={{ ...thStyle, padding: "4px 8px" }}>New Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cat.items.map((item) => {
                      const qPath = quotaData[item.path] || {};
                      const current = qPath[item.key] ?? "—";
                      return (
                        <tr key={item.key}>
                          <td style={{ ...tdStyle, padding: "4px 8px", fontSize: "12px" }}>{item.label}</td>
                          <td style={{ ...tdStyle, padding: "4px 8px", fontSize: "12px" }}>{current === -1 ? "Unlimited" : current}</td>
                          <td style={{ ...tdStyle, padding: "4px 8px" }}>
                            {isAdmin ? (
                              <input
                                type="number"
                                min={-1}
                                placeholder={String(current)}
                                value={quotaEdits[item.key] ?? ""}
                                onChange={(e) => {
                                  const val = e.target.value;
                                  if (val === "") {
                                    const next = { ...quotaEdits };
                                    delete next[item.key];
                                    setQuotaEdits(next);
                                  } else {
                                    setQuotaEdits({ ...quotaEdits, [item.key]: parseInt(val) });
                                  }
                                }}
                                style={{ ...inputStyle, width: "80px", padding: "2px 6px", fontSize: "12px" }}
                              />
                            ) : (
                              <span style={{ fontSize: "11px", color: "#6b7280" }}>Read-only</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}

        {!quotaData && !loading && (
          <div style={{ textAlign: "center", padding: "40px", color: "var(--pf9-text-secondary)" }}>
            Select a tenant and click "Load Quotas" to view and edit quota settings.
          </div>
        )}
      </div>
    );
  };

  // -----------------------------------------------------------------------
  // Main render
  // -----------------------------------------------------------------------
  const canCreate = activeSection !== "images" && activeSection !== "quotas" && activeSection !== "audit_log";

  return (
    <div style={containerStyle}>
      {/* Sidebar */}
      <div style={sidebarStyle}>
        <div style={{ padding: "8px 16px 16px", borderBottom: "1px solid var(--pf9-border, #d1d5db)", marginBottom: "8px" }}>
          <h3 style={{ margin: 0, fontSize: "15px" }}>🔧 Resources</h3>
          <p style={{ margin: "4px 0 0", fontSize: "11px", color: "var(--pf9-text-secondary, #9ca3af)" }}>
            Manage & provision
          </p>
        </div>
        {SECTIONS.map((s) => (
          <div
            key={s.id}
            style={navItemStyle(activeSection === s.id)}
            onClick={() => { setActiveSection(s.id); setShowCreateForm(false); setDeleteConfirm(null); }}
          >
            <span>{s.icon}</span> {s.label}
          </div>
        ))}
      </div>

      {/* Main content */}
      <div style={mainStyle}>
        {/* Header */}
        <div style={headerStyle}>
          <div>
            <h2 style={{ margin: 0, fontSize: "20px" }}>
              {SECTIONS.find(s => s.id === activeSection)?.icon}{" "}
              {SECTIONS.find(s => s.id === activeSection)?.label}
            </h2>
            <p style={{ margin: "2px 0 0", fontSize: "12px", color: "var(--pf9-text-secondary, #9ca3af)" }}>
              {data.length} items{filterProjectId ? " (filtered)" : ""}
            </p>
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            {activeSection !== "quotas" && (
              <>
                <select value={filterDomainId} onChange={(e) => { setFilterDomainId(e.target.value); setFilterProjectId(""); }} style={selectStyle}>
                  <option value="">All Domains</option>
                  {domains.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
                <select value={filterProjectId} onChange={(e) => setFilterProjectId(e.target.value)} style={selectStyle}>
                  <option value="">All Tenants</option>
                  {filteredProjects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </>
            )}
            {canCreate && isAdmin && (
              <button
                style={btnStyle("primary")}
                onClick={() => setShowCreateForm(!showCreateForm)}
              >
                {showCreateForm ? "✕ Cancel" : "➕ Create"}
              </button>
            )}
          </div>
        </div>

        {/* Messages */}
        {error && <div style={msgStyle("error")}>{error}</div>}
        {success && <div style={msgStyle("success")}>{success}</div>}

        {/* Create form */}
        {showCreateForm && renderCreateForm()}

        {/* Delete confirmation */}
        {deleteConfirm && (
          <div style={{
            ...formPanelStyle,
            border: "2px solid #ef4444",
            background: "#991b1b22",
          }}>
            <h4 style={{ margin: "0 0 8px", fontSize: "14px", color: "#ef4444" }}>⚠ Confirm Delete</h4>
            <p style={{ margin: "0 0 12px", fontSize: "13px" }}>
              Are you sure you want to delete <strong>{deleteConfirm.name}</strong> ({deleteConfirm.type.replace("_", " ")})?
              This action cannot be undone.
            </p>
            <div style={{ display: "flex", gap: "8px" }}>
              <button style={btnStyle("danger")} onClick={() => handleDelete(deleteConfirm.id, deleteConfirm.type)}>
                Yes, Delete
              </button>
              <button style={btnStyle("outline")} onClick={() => setDeleteConfirm(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Data table */}
        {renderTable()}
      </div>
    </div>
  );
}
