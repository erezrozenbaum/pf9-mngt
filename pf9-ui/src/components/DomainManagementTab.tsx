import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";

/* ===================================================================
   DomainManagementTab
   ===================================================================
   Manage Keystone domains:
   - View all domains with resource counts (projects, users, VMs,
     volumes, networks, routers, floating IPs, security groups)
   - Inspect detailed domain contents
   - Delete individual resources (VMs, volumes, networks, etc.)
   - Enable / Disable a domain (requires tenant_disable permission)
   - Delete a domain (requires tenant_delete permission)
*/

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Domain {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  projects: number;
  users: number;
}

interface ProjectDetail {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  vm_count: number;
  volume_count: number;
  network_count: number;
  router_count: number;
  floating_ip_count: number;
  security_group_count: number;
}

interface ServerResource {
  id: string;
  name: string;
  status: string;
  flavor: string;
  addresses: string;
  project_id: string;
  project_name: string;
  created: string;
}

interface VolumeResource {
  id: string;
  name: string;
  status: string;
  size: number;
  volume_type: string;
  project_id: string;
  project_name: string;
  created_at: string;
}

interface NetworkResource {
  id: string;
  name: string;
  status: string;
  shared: boolean;
  external: boolean;
  subnets: string[];
  project_id: string;
  project_name: string;
}

interface RouterResource {
  id: string;
  name: string;
  status: string;
  external_gateway: boolean;
  project_id: string;
  project_name: string;
}

interface FloatingIpResource {
  id: string;
  floating_ip_address: string;
  fixed_ip_address: string;
  status: string;
  port_id: string;
  project_id: string;
  project_name: string;
}

interface SecurityGroupResource {
  id: string;
  name: string;
  description: string;
  rules_count: number;
  project_id: string;
  project_name: string;
}

interface UserResource {
  id: string;
  name: string;
  email: string;
}

interface DomainResourceDetail {
  domain: { id: string; name: string; enabled: boolean };
  projects: ProjectDetail[];
  users: UserResource[];
  servers: ServerResource[];
  volumes: VolumeResource[];
  networks: NetworkResource[];
  routers: RouterResource[];
  floating_ips: FloatingIpResource[];
  security_groups: SecurityGroupResource[];
  can_delete: boolean;
  summary: {
    total_projects: number;
    total_users: number;
    total_vms: number;
    total_volumes: number;
    total_networks: number;
    total_routers: number;
    total_floating_ips: number;
    total_security_groups: number;
  };
}

type ResourceTab = "projects" | "users" | "servers" | "volumes" | "networks" | "routers" | "floating_ips" | "security_groups";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("auth_token");
  return token
    ? { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

function statusColor(status: string): string {
  const s = status.toLowerCase();
  if (s === "active" || s === "in-use" || s === "available") return "#48bb78";
  if (s === "error" || s === "down") return "#fc8181";
  if (s === "build" || s === "creating") return "#4299e1";
  if (s === "shutoff" || s === "stopped") return "var(--pf9-text-muted)";
  return "#ed8936";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
interface Props {
  isAdmin: boolean;
}

const DomainManagementTab: React.FC<Props> = ({ isAdmin }) => {
  void isAdmin;
  const [domains, setDomains] = useState<Domain[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Inspection state
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [resourceDetail, setResourceDetail] = useState<DomainResourceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeResourceTab, setActiveResourceTab] = useState<ResourceTab>("projects");

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<Domain | null>(null);
  const [deleteForce, setDeleteForce] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirmInput, setDeleteConfirmInput] = useState("");

  // Toggle confirmation state
  const [toggleTarget, setToggleTarget] = useState<Domain | null>(null);
  const [toggleConfirmInput, setToggleConfirmInput] = useState("");

  // Toggle state
  const [toggling, setToggling] = useState<string | null>(null);

  // Resource deletion feedback
  const [deletingResource, setDeletingResource] = useState<string | null>(null);
  const [deleteMsg, setDeleteMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Resource delete confirmation modal
  const [resourceDeleteTarget, setResourceDeleteTarget] = useState<{ type: string; id: string; name: string } | null>(null);
  const [resourceDeleteInput, setResourceDeleteInput] = useState("");

  // ── Fetch domains ──
  const fetchDomains = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/provisioning/domains`, { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setDomains(data.domains || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDomains(); }, [fetchDomains]);

  // ── Inspect domain ──
  const inspectDomain = async (domainId: string) => {
    setInspecting(domainId);
    setDetailLoading(true);
    setResourceDetail(null);
    setActiveResourceTab("projects");
    setDeleteMsg(null);
    try {
      const res = await fetch(`${API_BASE}/api/provisioning/domains/${domainId}/resources`, { headers: authHeaders() });
      if (res.ok) setResourceDetail(await res.json());
    } catch (e) {
      console.error("Failed to inspect domain:", e);
    } finally {
      setDetailLoading(false);
    }
  };

  // ── Toggle domain (called after confirmation) ──
  const toggleDomain = async (domain: Domain) => {
    setToggling(domain.id);
    setToggleTarget(null);
    setToggleConfirmInput("");
    try {
      const res = await fetch(`${API_BASE}/api/provisioning/domains/${domain.id}/toggle`, {
        method: "PUT", headers: authHeaders(), body: JSON.stringify({ enabled: !domain.enabled }),
      });
      if (res.ok) {
        fetchDomains();
      } else {
        const data = await res.json();
        alert(data.detail || "Failed to toggle domain. You may lack 'tenant_disable' permission.");
      }
    } catch (e: any) {
      alert(e.message);
    } finally {
      setToggling(null);
    }
  };

  // ── Delete domain (called after typed confirmation) ──
  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const url = `${API_BASE}/api/provisioning/domains/${deleteTarget.id}${deleteForce ? "?force=true" : ""}`;
      const res = await fetch(url, { method: "DELETE", headers: authHeaders() });
      const data = await res.json();
      if (data.error) {
        alert(`Cannot delete: ${data.message}\nProjects: ${data.projects}, Users: ${data.users}`);
      } else if (data.detail) {
        alert(data.detail);
      } else {
        setDeleteTarget(null);
        setDeleteConfirmInput("");
        setInspecting(null);
        setResourceDetail(null);
        fetchDomains();
      }
    } catch (e: any) {
      alert(`Delete failed: ${e.message}`);
    } finally {
      setDeleting(false);
    }
  };

  // ── Open resource delete confirmation modal ──
  const promptDeleteResource = (resourceType: string, resourceId: string, resourceName: string) => {
    setResourceDeleteTarget({ type: resourceType, id: resourceId, name: resourceName });
    setResourceDeleteInput("");
  };

  // ── Delete individual resource (called after typed confirmation) ──
  const deleteResource = async (resourceType: string, resourceId: string, resourceName: string) => {
    setResourceDeleteTarget(null);
    setResourceDeleteInput("");
    setDeletingResource(resourceId);
    setDeleteMsg(null);
    try {
      const urlMap: Record<string, string> = {
        server: `/api/provisioning/resources/server/${resourceId}`,
        volume: `/api/provisioning/resources/volume/${resourceId}`,
        network: `/api/provisioning/resources/network/${resourceId}`,
        router: `/api/provisioning/resources/router/${resourceId}`,
        floating_ip: `/api/provisioning/resources/floating-ip/${resourceId}`,
        security_group: `/api/provisioning/resources/security-group/${resourceId}`,
        user: `/api/provisioning/resources/user/${resourceId}`,
        project: `/api/provisioning/resources/project/${resourceId}`,
      };
      const sep = urlMap[resourceType].includes("?") ? "&" : "?";
      const url = `${API_BASE}${urlMap[resourceType]}${sep}resource_name=${encodeURIComponent(resourceName)}`;
      const res = await fetch(url, { method: "DELETE", headers: authHeaders() });
      if (res.ok) {
        setDeleteMsg({ type: "success", text: `${resourceType} "${resourceName}" deleted successfully` });
        // Refresh the inspection
        if (inspecting) setTimeout(() => inspectDomain(inspecting), 500);
      } else {
        const data = await res.json();
        setDeleteMsg({ type: "error", text: data.detail || `Failed to delete ${resourceType}` });
      }
    } catch (e: any) {
      setDeleteMsg({ type: "error", text: `Failed to delete: ${e.message}` });
    } finally {
      setDeletingResource(null);
    }
  };

  // ====================
  // RENDER
  // ====================
  const rTab = (key: ResourceTab, label: string, count: number) => (
    <button
      key={key}
      onClick={() => setActiveResourceTab(key)}
      style={{
        padding: "6px 12px", borderRadius: 4, border: "1px solid var(--pf9-border)",
        background: activeResourceTab === key ? "#4299e1" : "var(--pf9-bg-card)",
        color: activeResourceTab === key ? "white" : "var(--pf9-text)",
        fontSize: 12, fontWeight: activeResourceTab === key ? 700 : 400, cursor: "pointer",
      }}
    >
      {label} ({count})
    </button>
  );

  const delBtn = (type: string, id: string, name: string) => (
    <button
      onClick={() => promptDeleteResource(type, id, name)}
      disabled={deletingResource === id}
      style={{
        padding: "2px 8px", borderRadius: 4, border: "none",
        background: deletingResource === id ? "var(--pf9-toggle-inactive)" : "var(--pf9-badge-disabled-bg)",
        color: "var(--pf9-badge-disabled-text)", cursor: deletingResource === id ? "wait" : "pointer",
        fontSize: 11, fontWeight: 600,
      }}
      title={`Delete ${type}`}
    >
      {deletingResource === id ? "⏳" : "🗑️"}
    </button>
  );

  return (
    <div style={{ padding: "0 8px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h3 style={{ margin: 0, color: "var(--pf9-text)" }}>🏢 Domain / Tenant Management</h3>
        <button onClick={fetchDomains} style={refreshBtn}>🔄 Refresh</button>
      </div>

      {error && <div style={errorBox}>⚠️ {error}</div>}

      {loading ? (
        <div style={{ textAlign: "center", padding: 40, color: "var(--pf9-text-muted)" }}>Loading domains...</div>
      ) : domains.length === 0 ? (
        <div style={{ textAlign: "center", padding: 40, color: "var(--pf9-text-muted)" }}>
          No customer domains found. Use the Provisioning tab to create one.
        </div>
      ) : (
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
          {/* Domain table */}
          <div style={{ flex: inspecting ? "0 0 320px" : "1 1 auto", overflowX: "auto", minWidth: 0 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: inspecting ? 12 : 13 }}>
              <thead>
                <tr style={{ background: "var(--pf9-bg-header)", textAlign: "left" }}>
                  <th style={thStyle}>Domain Name</th>
                  <th style={thStyle}>Status</th>
                  {!inspecting && <th style={thStyle}>Projects</th>}
                  {!inspecting && <th style={thStyle}>Users</th>}
                  <th style={thStyle}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {domains.map((domain) => (
                  <tr key={domain.id} style={{
                    borderBottom: "1px solid var(--pf9-border)",
                    background: inspecting === domain.id ? "var(--pf9-bg-selected)" : "transparent",
                    cursor: inspecting ? "pointer" : undefined,
                  }} onClick={inspecting ? () => inspectDomain(domain.id) : undefined}>
                    <td style={tdStyle}>
                      <strong>{domain.name}</strong>
                      {!inspecting && domain.description && <div style={{ fontSize: 11, color: "var(--pf9-text-muted)" }}>{domain.description}</div>}
                      {!inspecting && <div style={{ fontSize: 10, color: "var(--pf9-id-color)", fontFamily: "monospace" }}>{domain.id.substring(0, 12)}...</div>}
                    </td>
                    <td style={tdStyle}>
                      <span style={{
                        padding: "2px 10px", borderRadius: 12, fontSize: inspecting ? 11 : 12, fontWeight: 600,
                        background: domain.enabled ? "var(--pf9-badge-enabled-bg)" : "var(--pf9-badge-disabled-bg)",
                        color: domain.enabled ? "var(--pf9-safe-text)" : "var(--pf9-badge-disabled-text)",
                      }}>{domain.enabled ? "Enabled" : "Disabled"}</span>
                    </td>
                    {!inspecting && <td style={tdStyle}>{domain.projects}</td>}
                    {!inspecting && <td style={tdStyle}>{domain.users}</td>}
                    <td style={tdStyle}>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <button onClick={(e) => { e.stopPropagation(); inspectDomain(domain.id); }} style={actionBtn} title="Inspect domain resources">🔍</button>
                        {!inspecting && (<>
                        <button onClick={() => { setToggleTarget(domain); setToggleConfirmInput(""); }} disabled={toggling === domain.id}
                          style={{ ...actionBtn, background: domain.enabled ? "var(--pf9-warning-bg)" : "var(--pf9-badge-enabled-bg)" }}
                          title={domain.enabled ? "Disable domain (tenant_disable)" : "Enable domain (tenant_disable)"}>
                          {toggling === domain.id ? "⏳" : domain.enabled ? "⏸️" : "▶️"}
                        </button>
                        <button onClick={() => { setDeleteTarget(domain); setDeleteForce(false); setDeleteConfirmInput(""); }}
                          style={{ ...actionBtn, background: "var(--pf9-badge-disabled-bg)", color: "var(--pf9-badge-disabled-text)" }}
                          title="Delete domain (tenant_delete)">🗑️</button>
                        </>)}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Inspection panel — side panel */}
          {inspecting && (
            <div style={{
              flex: "1 1 auto", minWidth: 0,
              background: "var(--pf9-bg-card)", border: "1px solid var(--pf9-border)",
              borderRadius: 8, padding: 16, overflowY: "auto", maxHeight: "85vh",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <h4 style={{ margin: 0 }}>🔍 Domain Inspection</h4>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button onClick={() => inspecting && inspectDomain(inspecting)} style={{ ...actionBtn, fontSize: 12 }} title="Reload">🔄</button>
                  <button onClick={() => { setInspecting(null); setResourceDetail(null); }}
                    style={{ background: "none", border: "none", fontSize: 18, cursor: "pointer", color: "var(--pf9-text-secondary)" }}>✕</button>
                </div>
              </div>

              {detailLoading ? (
                <div style={{ textAlign: "center", padding: 20, color: "var(--pf9-text-muted)" }}>Scanning domain resources from OpenStack...</div>
              ) : resourceDetail ? (
                <div>
                  {/* Summary tiles */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6, marginBottom: 12 }}>
                    {[
                      { label: "Projects", val: resourceDetail.summary.total_projects, color: "#4299e1" },
                      { label: "Users", val: resourceDetail.summary.total_users, color: "#805ad5" },
                      { label: "VMs", val: resourceDetail.summary.total_vms, color: "var(--pf9-warning-text)" },
                      { label: "Volumes", val: resourceDetail.summary.total_volumes, color: "var(--pf9-success)" },
                      { label: "Networks", val: resourceDetail.summary.total_networks, color: "#3182ce" },
                      { label: "Routers", val: resourceDetail.summary.total_routers, color: "#d69e2e" },
                      { label: "Float IPs", val: resourceDetail.summary.total_floating_ips, color: "var(--pf9-danger-text)" },
                      { label: "Sec Groups", val: resourceDetail.summary.total_security_groups, color: "var(--pf9-text-secondary)" },
                    ].map((s) => (
                      <div key={s.label} style={{
                        textAlign: "center", padding: 8, borderRadius: 6,
                        background: "var(--pf9-bg-card)", border: "1px solid var(--pf9-border)",
                      }}>
                        <div style={{ fontSize: 20, fontWeight: 700, color: s.color }}>{s.val}</div>
                        <div style={{ fontSize: 10, color: "var(--pf9-text-secondary)" }}>{s.label}</div>
                      </div>
                    ))}
                  </div>

                  {/* Delete safety indicator */}
                  <div style={{
                    padding: 10, borderRadius: 6, marginBottom: 12, fontSize: 12,
                    background: resourceDetail.can_delete ? "var(--pf9-safe-bg)" : "var(--pf9-danger-bg)",
                    border: `1px solid ${resourceDetail.can_delete ? "var(--pf9-badge-enabled-bg)" : "var(--pf9-danger-border)"}`,
                  }}>
                    {resourceDetail.can_delete ? (
                      <span>✅ <strong>Safe to delete</strong> — No projects or users exist.</span>
                    ) : (
                      <span>⚠️ <strong>Cannot delete safely</strong> — Domain has active resources. Remove them first or use force-delete.</span>
                    )}
                  </div>

                  {/* Delete feedback */}
                  {deleteMsg && (
                    <div style={{
                      padding: 10, borderRadius: 6, marginBottom: 12, fontSize: 12,
                      background: deleteMsg.type === "success" ? "var(--pf9-safe-bg)" : "var(--pf9-danger-bg)",
                      border: `1px solid ${deleteMsg.type === "success" ? "var(--pf9-badge-enabled-bg)" : "var(--pf9-danger-border)"}`,
                      color: deleteMsg.type === "success" ? "var(--pf9-safe-text)" : "var(--pf9-danger-text)",
                    }}>
                      {deleteMsg.type === "success" ? "✅" : "❌"} {deleteMsg.text}
                    </div>
                  )}

                  {/* Resource tabs */}
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 12 }}>
                    {rTab("projects", "Projects", resourceDetail.summary.total_projects)}
                    {rTab("users", "Users", resourceDetail.summary.total_users)}
                    {rTab("servers", "VMs", resourceDetail.summary.total_vms)}
                    {rTab("volumes", "Volumes", resourceDetail.summary.total_volumes)}
                    {rTab("networks", "Networks", resourceDetail.summary.total_networks)}
                    {rTab("routers", "Routers", resourceDetail.summary.total_routers)}
                    {rTab("floating_ips", "Float IPs", resourceDetail.summary.total_floating_ips)}
                    {rTab("security_groups", "Sec Groups", resourceDetail.summary.total_security_groups)}
                  </div>

                  {/* Resource content */}
                  <div style={{ fontSize: 12 }}>

                    {/* Projects */}
                    {activeResourceTab === "projects" && (
                      resourceDetail.projects.length === 0 ? (
                        <div style={emptyMsg}>No projects in this domain</div>
                      ) : (
                        <table style={resTable}>
                          <thead>
                            <tr style={resHeader}>
                              <th style={resTh}>Name</th>
                              <th style={resTh}>Status</th>
                              <th style={resTh}>VMs</th>
                              <th style={resTh}>Vols</th>
                              <th style={resTh}>Nets</th>
                              <th style={resTh}>SGs</th>
                              <th style={resTh}></th>
                            </tr>
                          </thead>
                          <tbody>
                            {resourceDetail.projects.map((p) => (
                              <tr key={p.id} style={resRow}>
                                <td style={resTd}>
                                  <strong>{p.name}</strong>
                                  {p.description && <div style={{ color: "var(--pf9-text-muted)", fontSize: 10 }}>{p.description}</div>}
                                </td>
                                <td style={resTd}>
                                  <span style={{ color: p.enabled ? "#48bb78" : "#fc8181" }}>
                                    {p.enabled ? "Active" : "Disabled"}
                                  </span>
                                </td>
                                <td style={resTd}>{p.vm_count}</td>
                                <td style={resTd}>{p.volume_count}</td>
                                <td style={resTd}>{p.network_count}</td>
                                <td style={resTd}>{p.security_group_count}</td>
                                <td style={resTd}>{delBtn("project", p.id, p.name)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )
                    )}

                    {/* Users */}
                    {activeResourceTab === "users" && (
                      resourceDetail.users.length === 0 ? (
                        <div style={emptyMsg}>No users in this domain</div>
                      ) : (
                        <table style={resTable}>
                          <thead>
                            <tr style={resHeader}>
                              <th style={resTh}>Username</th>
                              <th style={resTh}>Email</th>
                              <th style={resTh}></th>
                            </tr>
                          </thead>
                          <tbody>
                            {resourceDetail.users.map((u) => (
                              <tr key={u.id} style={resRow}>
                                <td style={resTd}><strong>{u.name}</strong></td>
                                <td style={resTd}>{u.email || "—"}</td>
                                <td style={resTd}>{delBtn("user", u.id, u.name)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )
                    )}

                    {/* Servers */}
                    {activeResourceTab === "servers" && (
                      resourceDetail.servers.length === 0 ? (
                        <div style={emptyMsg}>No VMs in this domain</div>
                      ) : (
                        <table style={resTable}>
                          <thead>
                            <tr style={resHeader}>
                              <th style={resTh}>Name</th>
                              <th style={resTh}>Status</th>
                              <th style={resTh}>Flavor</th>
                              <th style={resTh}>Network</th>
                              <th style={resTh}>Project</th>
                              <th style={resTh}></th>
                            </tr>
                          </thead>
                          <tbody>
                            {resourceDetail.servers.map((s) => (
                              <tr key={s.id} style={resRow}>
                                <td style={resTd}>
                                  <strong>{s.name}</strong>
                                  <div style={{ color: "var(--pf9-id-color)", fontFamily: "monospace", fontSize: 10 }}>{s.id.substring(0, 12)}</div>
                                </td>
                                <td style={resTd}>
                                  <span style={{ padding: "1px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600,
                                    background: statusColor(s.status) + "22", color: statusColor(s.status) }}>
                                    {s.status}
                                  </span>
                                </td>
                                <td style={resTd}>{s.flavor}</td>
                                <td style={{ ...resTd, maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                                  title={s.addresses}>{s.addresses || "—"}</td>
                                <td style={resTd}>{s.project_name}</td>
                                <td style={resTd}>{delBtn("server", s.id, s.name)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )
                    )}

                    {/* Volumes */}
                    {activeResourceTab === "volumes" && (
                      resourceDetail.volumes.length === 0 ? (
                        <div style={emptyMsg}>No volumes in this domain</div>
                      ) : (
                        <table style={resTable}>
                          <thead>
                            <tr style={resHeader}>
                              <th style={resTh}>Name</th>
                              <th style={resTh}>Status</th>
                              <th style={resTh}>Size (GB)</th>
                              <th style={resTh}>Type</th>
                              <th style={resTh}>Project</th>
                              <th style={resTh}></th>
                            </tr>
                          </thead>
                          <tbody>
                            {resourceDetail.volumes.map((v) => (
                              <tr key={v.id} style={resRow}>
                                <td style={resTd}>
                                  <strong>{v.name || "(unnamed)"}</strong>
                                  <div style={{ color: "var(--pf9-id-color)", fontFamily: "monospace", fontSize: 10 }}>{v.id.substring(0, 12)}</div>
                                </td>
                                <td style={resTd}>
                                  <span style={{ padding: "1px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600,
                                    background: statusColor(v.status) + "22", color: statusColor(v.status) }}>
                                    {v.status}
                                  </span>
                                </td>
                                <td style={resTd}>{v.size}</td>
                                <td style={resTd}>{v.volume_type || "—"}</td>
                                <td style={resTd}>{v.project_name}</td>
                                <td style={resTd}>{delBtn("volume", v.id, v.name || v.id)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )
                    )}

                    {/* Networks */}
                    {activeResourceTab === "networks" && (
                      resourceDetail.networks.length === 0 ? (
                        <div style={emptyMsg}>No networks in this domain</div>
                      ) : (
                        <table style={resTable}>
                          <thead>
                            <tr style={resHeader}>
                              <th style={resTh}>Name</th>
                              <th style={resTh}>Status</th>
                              <th style={resTh}>Shared</th>
                              <th style={resTh}>External</th>
                              <th style={resTh}>Subnets</th>
                              <th style={resTh}>Project</th>
                              <th style={resTh}></th>
                            </tr>
                          </thead>
                          <tbody>
                            {resourceDetail.networks.map((n) => (
                              <tr key={n.id} style={resRow}>
                                <td style={resTd}>
                                  <strong>{n.name}</strong>
                                  <div style={{ color: "var(--pf9-id-color)", fontFamily: "monospace", fontSize: 10 }}>{n.id.substring(0, 12)}</div>
                                </td>
                                <td style={resTd}>
                                  <span style={{ padding: "1px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600,
                                    background: statusColor(n.status) + "22", color: statusColor(n.status) }}>
                                    {n.status}
                                  </span>
                                </td>
                                <td style={resTd}>{n.shared ? "Yes" : "No"}</td>
                                <td style={resTd}>{n.external ? "Yes" : "No"}</td>
                                <td style={resTd}>{n.subnets.length}</td>
                                <td style={resTd}>{n.project_name}</td>
                                <td style={resTd}>{delBtn("network", n.id, n.name)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )
                    )}

                    {/* Routers */}
                    {activeResourceTab === "routers" && (
                      resourceDetail.routers.length === 0 ? (
                        <div style={emptyMsg}>No routers in this domain</div>
                      ) : (
                        <table style={resTable}>
                          <thead>
                            <tr style={resHeader}>
                              <th style={resTh}>Name</th>
                              <th style={resTh}>Status</th>
                              <th style={resTh}>Ext Gateway</th>
                              <th style={resTh}>Project</th>
                              <th style={resTh}></th>
                            </tr>
                          </thead>
                          <tbody>
                            {resourceDetail.routers.map((r) => (
                              <tr key={r.id} style={resRow}>
                                <td style={resTd}>
                                  <strong>{r.name}</strong>
                                  <div style={{ color: "var(--pf9-id-color)", fontFamily: "monospace", fontSize: 10 }}>{r.id.substring(0, 12)}</div>
                                </td>
                                <td style={resTd}>
                                  <span style={{ padding: "1px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600,
                                    background: statusColor(r.status) + "22", color: statusColor(r.status) }}>
                                    {r.status}
                                  </span>
                                </td>
                                <td style={resTd}>{r.external_gateway ? "Yes" : "No"}</td>
                                <td style={resTd}>{r.project_name}</td>
                                <td style={resTd}>{delBtn("router", r.id, r.name)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )
                    )}

                    {/* Floating IPs */}
                    {activeResourceTab === "floating_ips" && (
                      resourceDetail.floating_ips.length === 0 ? (
                        <div style={emptyMsg}>No floating IPs in this domain</div>
                      ) : (
                        <table style={resTable}>
                          <thead>
                            <tr style={resHeader}>
                              <th style={resTh}>Floating IP</th>
                              <th style={resTh}>Fixed IP</th>
                              <th style={resTh}>Status</th>
                              <th style={resTh}>Project</th>
                              <th style={resTh}></th>
                            </tr>
                          </thead>
                          <tbody>
                            {resourceDetail.floating_ips.map((f) => (
                              <tr key={f.id} style={resRow}>
                                <td style={resTd}>
                                  <strong>{f.floating_ip_address}</strong>
                                  <div style={{ color: "var(--pf9-id-color)", fontFamily: "monospace", fontSize: 10 }}>{f.id.substring(0, 12)}</div>
                                </td>
                                <td style={resTd}>{f.fixed_ip_address || "—"}</td>
                                <td style={resTd}>
                                  <span style={{ padding: "1px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600,
                                    background: statusColor(f.status) + "22", color: statusColor(f.status) }}>
                                    {f.status}
                                  </span>
                                </td>
                                <td style={resTd}>{f.project_name}</td>
                                <td style={resTd}>{delBtn("floating_ip", f.id, f.floating_ip_address)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )
                    )}

                    {/* Security Groups */}
                    {activeResourceTab === "security_groups" && (
                      resourceDetail.security_groups.length === 0 ? (
                        <div style={emptyMsg}>No security groups in this domain</div>
                      ) : (
                        <table style={resTable}>
                          <thead>
                            <tr style={resHeader}>
                              <th style={resTh}>Name</th>
                              <th style={resTh}>Description</th>
                              <th style={resTh}>Rules</th>
                              <th style={resTh}>Project</th>
                              <th style={resTh}></th>
                            </tr>
                          </thead>
                          <tbody>
                            {resourceDetail.security_groups.map((sg) => (
                              <tr key={sg.id} style={resRow}>
                                <td style={resTd}>
                                  <strong>{sg.name}</strong>
                                  <div style={{ color: "var(--pf9-id-color)", fontFamily: "monospace", fontSize: 10 }}>{sg.id.substring(0, 12)}</div>
                                </td>
                                <td style={{ ...resTd, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                                  title={sg.description}>{sg.description || "—"}</td>
                                <td style={resTd}>{sg.rules_count}</td>
                                <td style={resTd}>{sg.project_name}</td>
                                <td style={resTd}>{delBtn("security_group", sg.id, sg.name)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )
                    )}
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>
      )}

      {/* ===== Toggle domain confirmation dialog ===== */}
      {toggleTarget && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
          background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center",
          justifyContent: "center", zIndex: 1000,
        }}>
          <div style={{
            background: "var(--pf9-bg-card)", borderRadius: 12, padding: 24,
            maxWidth: 480, width: "90%", boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
          }}>
            <h3 style={{ margin: "0 0 16px 0", color: toggleTarget.enabled ? "var(--pf9-warning-text)" : "var(--pf9-safe-text)" }}>
              {toggleTarget.enabled ? "⏸️ Disable Domain" : "▶️ Enable Domain"}
            </h3>
            <p style={{ fontSize: 14, color: "var(--pf9-text)" }}>
              Are you sure you want to <strong>{toggleTarget.enabled ? "disable" : "enable"}</strong> domain <strong>{toggleTarget.name}</strong>?
            </p>
            {toggleTarget.enabled && (
              <div style={{
                background: "var(--pf9-danger-bg)", border: "1px solid #fed7d7", borderRadius: 6,
                padding: 12, margin: "12px 0", fontSize: 13,
              }}>
                <strong>⚠️ Warning:</strong> Disabling a domain will prevent all users and projects within it from being accessed.
              </div>
            )}
            <p style={{ fontSize: 12, color: "var(--pf9-text-secondary)", margin: "12px 0 4px 0" }}>
              To confirm, type: <strong style={{ color: "var(--pf9-danger-text)", fontFamily: "monospace" }}>
                approve {toggleTarget.enabled ? "disable" : "enable"} {toggleTarget.name}
              </strong>
            </p>
            <input
              type="text"
              value={toggleConfirmInput}
              onChange={(e) => setToggleConfirmInput(e.target.value)}
              placeholder={`approve ${toggleTarget.enabled ? "disable" : "enable"} ${toggleTarget.name}`}
              style={{
                width: "100%", padding: "8px 12px", borderRadius: 6, fontSize: 13,
                border: "1px solid var(--pf9-border)",
                fontFamily: "monospace", boxSizing: "border-box",
              }}
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
              <button onClick={() => { setToggleTarget(null); setToggleConfirmInput(""); }} style={cancelBtn}>Cancel</button>
              <button
                onClick={() => toggleDomain(toggleTarget)}
                disabled={toggleConfirmInput !== `approve ${toggleTarget.enabled ? "disable" : "enable"} ${toggleTarget.name}`}
                style={{
                  padding: "8px 20px", borderRadius: 6, border: "none", fontWeight: 600, fontSize: 13,
                  background: toggleConfirmInput === `approve ${toggleTarget.enabled ? "disable" : "enable"} ${toggleTarget.name}`
                    ? (toggleTarget.enabled ? "var(--pf9-warning-text)" : "var(--pf9-success)") : "var(--pf9-toggle-inactive)",
                  color: "white", cursor: toggleConfirmInput === `approve ${toggleTarget.enabled ? "disable" : "enable"} ${toggleTarget.name}` ? "pointer" : "not-allowed",
                }}>
                {toggleTarget.enabled ? "Disable Domain" : "Enable Domain"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Resource delete confirmation dialog ===== */}
      {resourceDeleteTarget && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
          background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center",
          justifyContent: "center", zIndex: 1000,
        }}>
          <div style={{
            background: "var(--pf9-bg-card)", borderRadius: 12, padding: 24,
            maxWidth: 480, width: "90%", boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
          }}>
            <h3 style={{ margin: "0 0 16px 0", color: "var(--pf9-danger-text)" }}>🗑️ Delete {resourceDeleteTarget.type}</h3>
            <p style={{ fontSize: 14, color: "var(--pf9-text)" }}>
              Are you sure you want to delete {resourceDeleteTarget.type} <strong>"{resourceDeleteTarget.name}"</strong>?
            </p>
            <div style={{
              background: "var(--pf9-danger-bg)", border: "1px solid #fed7d7", borderRadius: 6,
              padding: 12, margin: "12px 0", fontSize: 13,
            }}>
              <strong>⚠️ Warning:</strong> This action cannot be undone. The resource will be permanently removed from OpenStack.
            </div>
            <p style={{ fontSize: 12, color: "var(--pf9-text-secondary)", margin: "12px 0 4px 0" }}>
              To confirm, type: <strong style={{ color: "var(--pf9-danger-text)", fontFamily: "monospace" }}>
                approve delete {resourceDeleteTarget.name}
              </strong>
            </p>
            <input
              type="text"
              value={resourceDeleteInput}
              onChange={(e) => setResourceDeleteInput(e.target.value)}
              placeholder={`approve delete ${resourceDeleteTarget.name}`}
              style={{
                width: "100%", padding: "8px 12px", borderRadius: 6, fontSize: 13,
                border: "1px solid var(--pf9-border)",
                fontFamily: "monospace", boxSizing: "border-box",
              }}
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
              <button onClick={() => { setResourceDeleteTarget(null); setResourceDeleteInput(""); }} style={cancelBtn}>Cancel</button>
              <button
                onClick={() => deleteResource(resourceDeleteTarget.type, resourceDeleteTarget.id, resourceDeleteTarget.name)}
                disabled={resourceDeleteInput !== `approve delete ${resourceDeleteTarget.name}`}
                style={{
                  padding: "8px 20px", borderRadius: 6, border: "none", fontWeight: 600, fontSize: 13,
                  background: resourceDeleteInput === `approve delete ${resourceDeleteTarget.name}` ? "var(--pf9-danger-text)" : "var(--pf9-toggle-inactive)",
                  color: "white", cursor: resourceDeleteInput === `approve delete ${resourceDeleteTarget.name}` ? "pointer" : "not-allowed",
                }}>
                Delete {resourceDeleteTarget.type}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Delete domain confirmation dialog ===== */}
      {deleteTarget && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
          background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center",
          justifyContent: "center", zIndex: 1000,
        }}>
          <div style={{
            background: "var(--pf9-bg-card)", borderRadius: 12, padding: 24,
            maxWidth: 480, width: "90%", boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
          }}>
            <h3 style={{ margin: "0 0 16px 0", color: "var(--pf9-danger-text)" }}>🗑️ Delete Domain</h3>
            <p style={{ fontSize: 14, color: "var(--pf9-text)" }}>
              Are you sure you want to delete domain <strong>{deleteTarget.name}</strong>?
            </p>
            <p style={{ fontSize: 12, color: "var(--pf9-text-secondary)" }}>
              This action requires the <strong>tenant_delete</strong> permission.
            </p>
            {(deleteTarget.projects > 0 || deleteTarget.users > 0) && (
              <div style={{
                background: "var(--pf9-danger-bg)", border: "1px solid #fed7d7", borderRadius: 6,
                padding: 12, margin: "12px 0", fontSize: 13,
              }}>
                <strong>⚠️ Warning:</strong> This domain contains {deleteTarget.projects} project(s)
                and {deleteTarget.users} user(s).
                <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, cursor: "pointer" }}>
                  <input type="checkbox" checked={deleteForce} onChange={(e) => setDeleteForce(e.target.checked)} />
                  <span>Force delete (will attempt to remove all child resources)</span>
                </label>
              </div>
            )}
            <p style={{ fontSize: 12, color: "var(--pf9-text-secondary)", margin: "12px 0 4px 0" }}>
              To confirm, type: <strong style={{ color: "var(--pf9-danger-text)", fontFamily: "monospace" }}>
                approve delete {deleteTarget.name}
              </strong>
            </p>
            <input
              type="text"
              value={deleteConfirmInput}
              onChange={(e) => setDeleteConfirmInput(e.target.value)}
              placeholder={`approve delete ${deleteTarget.name}`}
              style={{
                width: "100%", padding: "8px 12px", borderRadius: 6, fontSize: 13,
                border: "1px solid var(--pf9-border)",
                fontFamily: "monospace", boxSizing: "border-box",
              }}
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
              <button onClick={() => { setDeleteTarget(null); setDeleteConfirmInput(""); }} style={cancelBtn}>Cancel</button>
              <button onClick={handleDelete}
                disabled={deleting || deleteConfirmInput !== `approve delete ${deleteTarget.name}` || ((deleteTarget.projects > 0 || deleteTarget.users > 0) && !deleteForce)}
                style={{
                  padding: "8px 20px", borderRadius: 6, border: "none", fontWeight: 600, fontSize: 13,
                  background: (deleting || deleteConfirmInput !== `approve delete ${deleteTarget.name}` || ((deleteTarget.projects > 0 || deleteTarget.users > 0) && !deleteForce)) ? "var(--pf9-toggle-inactive)" : "var(--pf9-danger-text)",
                  color: "white", cursor: deleting ? "wait" : (deleteConfirmInput === `approve delete ${deleteTarget.name}` ? "pointer" : "not-allowed"),
                }}>
                {deleting ? "Deleting..." : "Delete Domain"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const thStyle: React.CSSProperties = {
  padding: "10px 12px", fontWeight: 600, borderBottom: "2px solid var(--pf9-border)",
};
const tdStyle: React.CSSProperties = { padding: "10px 12px" };
const actionBtn: React.CSSProperties = {
  padding: "4px 8px", borderRadius: 6, border: "1px solid var(--pf9-border)",
  background: "var(--pf9-bg-card)", cursor: "pointer", fontSize: 14,
};
const refreshBtn: React.CSSProperties = {
  padding: "6px 16px", borderRadius: 6, border: "1px solid var(--pf9-border)",
  background: "var(--pf9-bg-card)", cursor: "pointer", fontSize: 13, color: "var(--pf9-text)",
};
const errorBox: React.CSSProperties = {
  padding: 12, borderRadius: 6, background: "var(--pf9-danger-bg)", border: "1px solid var(--pf9-danger-border)",
  color: "var(--pf9-danger-text)", fontSize: 13, marginBottom: 16,
};
const cancelBtn: React.CSSProperties = {
  padding: "8px 20px", borderRadius: 6, border: "1px solid var(--pf9-border)",
  background: "var(--pf9-bg-card)", cursor: "pointer", fontSize: 13, color: "var(--pf9-text)",
};
const resTable: React.CSSProperties = { width: "100%", borderCollapse: "collapse" };
const resHeader: React.CSSProperties = { background: "var(--pf9-bg-header)", textAlign: "left" as const };
const resTh: React.CSSProperties = { padding: "6px 8px", fontWeight: 600, borderBottom: "1px solid var(--pf9-border)", fontSize: 11 };
const resTd: React.CSSProperties = { padding: "6px 8px", borderBottom: "1px solid var(--pf9-border)" };
const resRow: React.CSSProperties = {};
const emptyMsg: React.CSSProperties = { textAlign: "center", padding: 20, color: "var(--pf9-text-muted)", fontSize: 13 };

export default DomainManagementTab;
