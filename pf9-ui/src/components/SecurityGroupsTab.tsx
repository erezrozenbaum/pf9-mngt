import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SecurityGroup {
  security_group_id: string;
  security_group_name: string;
  description: string | null;
  project_id: string | null;
  project_name: string | null;
  tenant_name: string | null;
  domain_id: string | null;
  domain_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  last_seen_at: string | null;
  attached_vm_count: number;
  attached_network_count: number;
  ingress_rule_count: number;
  egress_rule_count: number;
}

interface SecurityGroupRule {
  rule_id: string;
  security_group_id: string;
  security_group_name?: string;
  direction: string;
  ethertype: string;
  protocol: string | null;
  port_range_min: number | null;
  port_range_max: number | null;
  remote_ip_prefix: string | null;
  remote_group_id: string | null;
  remote_group_name: string | null;
  description: string | null;
  rule_summary: string | null;
}

interface AttachedVM {
  vm_id: string;
  vm_name: string;
  vm_status: string;
  network_id: string;
  network_name: string;
}

interface AttachedNetwork {
  network_id: string;
  network_name: string;
  is_shared: boolean;
  is_external: boolean;
}

interface SecurityGroupDetail extends SecurityGroup {
  rules: SecurityGroupRule[];
  attached_vms: AttachedVM[];
  attached_networks: AttachedNetwork[];
}

interface PagedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

interface Project {
  tenant_id: string;
  tenant_name: string;
  domain_name: string;
}

interface SecurityGroupsTabProps {
  token: string;
  isAdmin: boolean;
  projects: Project[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const SecurityGroupsTab: React.FC<SecurityGroupsTabProps> = ({ token, isAdmin, projects }) => {
  // List state
  const [securityGroups, setSecurityGroups] = useState<SecurityGroup[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [sortBy, setSortBy] = useState("security_group_name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [filterDomain, setFilterDomain] = useState("");
  const [filterTenant, setFilterTenant] = useState("");
  const [filterName, setFilterName] = useState("");
  const [loading, setLoading] = useState(false);

  // Detail state
  const [selectedSg, setSelectedSg] = useState<SecurityGroupDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Create security group form
  const [showCreateSg, setShowCreateSg] = useState(false);
  const [newSgName, setNewSgName] = useState("");
  const [newSgDescription, setNewSgDescription] = useState("");
  const [newSgProjectId, setNewSgProjectId] = useState("");
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState("");

  // Create rule form
  const [showCreateRule, setShowCreateRule] = useState(false);
  const [newRuleDirection, setNewRuleDirection] = useState<"ingress" | "egress">("ingress");
  const [newRuleProtocol, setNewRuleProtocol] = useState("");
  const [newRulePortMin, setNewRulePortMin] = useState("");
  const [newRulePortMax, setNewRulePortMax] = useState("");
  const [newRuleRemoteIp, setNewRuleRemoteIp] = useState("");
  const [newRuleEthertype, setNewRuleEthertype] = useState("IPv4");
  const [newRuleDescription, setNewRuleDescription] = useState("");
  const [ruleCreateLoading, setRuleCreateLoading] = useState(false);
  const [ruleCreateError, setRuleCreateError] = useState("");

  // Error/success
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  // Admin credentials
  const [adminUser, setAdminUser] = useState("");
  const [adminPass, setAdminPass] = useState("");

  // ---------------------------------------------------------------------------
  // Fetch list
  // ---------------------------------------------------------------------------
  const fetchSecurityGroups = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        sort_by: sortBy,
        sort_dir: sortDir,
      });
      if (filterDomain) params.set("domain_name", filterDomain);
      if (filterTenant) params.set("tenant_name", filterTenant);
      if (filterName) params.set("name", filterName);

      const res = await fetch(`${API_BASE}/security-groups?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: PagedResponse<SecurityGroup> = await res.json();
      setSecurityGroups(data.items);
      setTotal(data.total);
    } catch (e: any) {
      setError(e.message || "Failed to fetch security groups");
    } finally {
      setLoading(false);
    }
  }, [token, page, pageSize, sortBy, sortDir, filterDomain, filterTenant, filterName]);

  useEffect(() => {
    fetchSecurityGroups();
  }, [fetchSecurityGroups]);

  // ---------------------------------------------------------------------------
  // Fetch detail
  // ---------------------------------------------------------------------------
  const fetchDetail = async (sgId: string) => {
    setDetailLoading(true);
    try {
      const res = await fetch(`${API_BASE}/security-groups/${sgId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: SecurityGroupDetail = await res.json();
      setSelectedSg(data);
    } catch (e: any) {
      setError(e.message || "Failed to fetch security group detail");
    } finally {
      setDetailLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Create security group
  // ---------------------------------------------------------------------------
  const handleCreateSg = async () => {
    if (!newSgName.trim()) {
      setCreateError("Name is required");
      return;
    }
    if (!adminUser || !adminPass) {
      setCreateError("Admin credentials are required");
      return;
    }
    setCreateLoading(true);
    setCreateError("");
    try {
      const body: any = { name: newSgName.trim(), description: newSgDescription.trim() };
      if (newSgProjectId) body.project_id = newSgProjectId;

      const res = await fetch(`${API_BASE}/admin/security-groups`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Basic ${btoa(`${adminUser}:${adminPass}`)}`,
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      setSuccessMsg(`Security group "${newSgName}" created successfully`);
      setShowCreateSg(false);
      setNewSgName("");
      setNewSgDescription("");
      setNewSgProjectId("");
      fetchSecurityGroups();
      setTimeout(() => setSuccessMsg(""), 5000);
    } catch (e: any) {
      setCreateError(e.message || "Failed to create security group");
    } finally {
      setCreateLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Delete security group
  // ---------------------------------------------------------------------------
  const handleDeleteSg = async (sgId: string, sgName: string) => {
    if (!adminUser || !adminPass) {
      setError("Enter admin credentials to delete security groups");
      return;
    }
    if (!confirm(`Are you sure you want to delete security group "${sgName}" (${sgId})?`)) return;

    try {
      const res = await fetch(`${API_BASE}/admin/security-groups/${sgId}`, {
        method: "DELETE",
        headers: {
          Authorization: `Basic ${btoa(`${adminUser}:${adminPass}`)}`,
        },
      });
      if (!res.ok && res.status !== 204) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      setSuccessMsg(`Security group "${sgName}" deleted`);
      if (selectedSg?.security_group_id === sgId) setSelectedSg(null);
      fetchSecurityGroups();
      setTimeout(() => setSuccessMsg(""), 5000);
    } catch (e: any) {
      setError(e.message || "Failed to delete security group");
    }
  };

  // ---------------------------------------------------------------------------
  // Create rule
  // ---------------------------------------------------------------------------
  const handleCreateRule = async () => {
    if (!selectedSg) return;
    if (!adminUser || !adminPass) {
      setRuleCreateError("Admin credentials are required");
      return;
    }
    setRuleCreateLoading(true);
    setRuleCreateError("");
    try {
      const body: any = {
        security_group_id: selectedSg.security_group_id,
        direction: newRuleDirection,
        ethertype: newRuleEthertype,
      };
      if (newRuleProtocol) body.protocol = newRuleProtocol;
      if (newRulePortMin) body.port_range_min = parseInt(newRulePortMin);
      if (newRulePortMax) body.port_range_max = parseInt(newRulePortMax);
      if (newRuleRemoteIp) body.remote_ip_prefix = newRuleRemoteIp;
      if (newRuleDescription) body.description = newRuleDescription;

      const res = await fetch(`${API_BASE}/admin/security-group-rules`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Basic ${btoa(`${adminUser}:${adminPass}`)}`,
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      setSuccessMsg("Rule created successfully");
      setShowCreateRule(false);
      resetRuleForm();
      // Refresh detail
      fetchDetail(selectedSg.security_group_id);
      fetchSecurityGroups();
      setTimeout(() => setSuccessMsg(""), 5000);
    } catch (e: any) {
      setRuleCreateError(e.message || "Failed to create rule");
    } finally {
      setRuleCreateLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Delete rule
  // ---------------------------------------------------------------------------
  const handleDeleteRule = async (ruleId: string) => {
    if (!adminUser || !adminPass) {
      setError("Enter admin credentials to delete rules");
      return;
    }
    if (!confirm(`Delete rule ${ruleId}?`)) return;
    try {
      const res = await fetch(`${API_BASE}/admin/security-group-rules/${ruleId}`, {
        method: "DELETE",
        headers: {
          Authorization: `Basic ${btoa(`${adminUser}:${adminPass}`)}`,
        },
      });
      if (!res.ok && res.status !== 204) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      setSuccessMsg("Rule deleted");
      if (selectedSg) fetchDetail(selectedSg.security_group_id);
      fetchSecurityGroups();
      setTimeout(() => setSuccessMsg(""), 5000);
    } catch (e: any) {
      setError(e.message || "Failed to delete rule");
    }
  };

  const resetRuleForm = () => {
    setNewRuleDirection("ingress");
    setNewRuleProtocol("");
    setNewRulePortMin("");
    setNewRulePortMax("");
    setNewRuleRemoteIp("");
    setNewRuleEthertype("IPv4");
    setNewRuleDescription("");
  };

  // ---------------------------------------------------------------------------
  // Rule template presets
  // ---------------------------------------------------------------------------
  const RULE_TEMPLATES: {
    label: string;
    icon: string;
    direction: "ingress" | "egress";
    protocol: string;
    portMin: string;
    portMax: string;
    remoteIp: string;
    description: string;
  }[] = [
    { label: "SSH", icon: "🔑", direction: "ingress", protocol: "tcp", portMin: "22", portMax: "22", remoteIp: "0.0.0.0/0", description: "Allow SSH" },
    { label: "HTTP", icon: "🌐", direction: "ingress", protocol: "tcp", portMin: "80", portMax: "80", remoteIp: "0.0.0.0/0", description: "Allow HTTP" },
    { label: "HTTPS", icon: "🔒", direction: "ingress", protocol: "tcp", portMin: "443", portMax: "443", remoteIp: "0.0.0.0/0", description: "Allow HTTPS" },
    { label: "RDP", icon: "🖥️", direction: "ingress", protocol: "tcp", portMin: "3389", portMax: "3389", remoteIp: "0.0.0.0/0", description: "Allow RDP" },
    { label: "ICMP", icon: "📡", direction: "ingress", protocol: "icmp", portMin: "", portMax: "", remoteIp: "0.0.0.0/0", description: "Allow ICMP (Ping)" },
    { label: "DNS", icon: "📋", direction: "egress", protocol: "udp", portMin: "53", portMax: "53", remoteIp: "0.0.0.0/0", description: "Allow DNS outbound" },
  ];

  const applyRuleTemplate = (tpl: typeof RULE_TEMPLATES[number]) => {
    setNewRuleDirection(tpl.direction);
    setNewRuleProtocol(tpl.protocol);
    setNewRulePortMin(tpl.portMin);
    setNewRulePortMax(tpl.portMax);
    setNewRuleRemoteIp(tpl.remoteIp);
    setNewRuleEthertype("IPv4");
    setNewRuleDescription(tpl.description);
    setShowCreateRule(true);
  };

  const formatDate = (d: string | null) => (d ? new Date(d).toLocaleString() : "—");

  const formatPortRange = (rule: SecurityGroupRule) => {
    if (!rule.protocol) return "Any";
    if (rule.protocol === "icmp") return "ICMP";
    if (rule.port_range_min === null && rule.port_range_max === null) return "Any";
    if (rule.port_range_min === rule.port_range_max) return String(rule.port_range_min);
    return `${rule.port_range_min ?? "*"}-${rule.port_range_max ?? "*"}`;
  };

  // ---------------------------------------------------------------------------
  // Export filtered list to CSV  (now includes per-rule details)
  // ---------------------------------------------------------------------------
  const handleExportCsv = async () => {
    // Fetch all rules so we can expand one row per rule in the CSV
    const sgRulesMap: Record<string, SecurityGroupRule[]> = {};
    try {
      const rulesResp = await fetch(
        `${API_BASE}/security-group-rules?page_size=5000`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (rulesResp.ok) {
        const rulesData = await rulesResp.json();
        for (const r of rulesData.items || []) {
          if (!sgRulesMap[r.security_group_id]) sgRulesMap[r.security_group_id] = [];
          sgRulesMap[r.security_group_id].push(r);
        }
      }
    } catch { /* fall back to export without rules */ }

    const headers = [
      "Security Group Name", "ID", "Description", "Domain", "Tenant", "Project Name",
      "Project ID", "VMs", "Networks", "Ingress Rules", "Egress Rules", "Last Seen",
      "Rule Direction", "Rule Summary", "Protocol", "Port Min", "Port Max",
      "Remote IP", "Remote SG", "Rule Description",
    ];

    const rows: string[][] = [];
    for (const sg of securityGroups) {
      const rules = sgRulesMap[sg.security_group_id] || [];
      if (rules.length === 0) {
        rows.push([
          sg.security_group_name, sg.security_group_id, sg.description ?? "",
          sg.domain_name ?? "", sg.tenant_name ?? sg.project_name ?? "",
          sg.project_name ?? "", sg.project_id ?? "",
          String(sg.attached_vm_count), String(sg.attached_network_count),
          String(sg.ingress_rule_count), String(sg.egress_rule_count),
          sg.last_seen_at ?? "",
          "", "", "", "", "", "", "", "",
        ]);
      } else {
        for (const r of rules) {
          rows.push([
            sg.security_group_name, sg.security_group_id, sg.description ?? "",
            sg.domain_name ?? "", sg.tenant_name ?? sg.project_name ?? "",
            sg.project_name ?? "", sg.project_id ?? "",
            String(sg.attached_vm_count), String(sg.attached_network_count),
            String(sg.ingress_rule_count), String(sg.egress_rule_count),
            sg.last_seen_at ?? "",
            r.direction, r.rule_summary ?? "",
            r.protocol ?? "Any",
            r.port_range_min != null ? String(r.port_range_min) : "",
            r.port_range_max != null ? String(r.port_range_max) : "",
            r.remote_ip_prefix ?? "",
            r.remote_group_name ?? r.remote_group_id ?? "",
            r.description ?? "",
          ]);
        }
      }
    }

    const csvContent = [headers, ...rows]
      .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
      .join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `security_groups_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div style={{ display: "flex", gap: "20px", height: "100%" }}>
      {/* Left: Security Groups List */}
      <div style={{ flex: 2, overflow: "auto" }}>
        {/* Messages */}
        {error && (
          <div style={{ background: "#fee2e2", color: "#991b1b", padding: "10px", borderRadius: "6px", marginBottom: "12px" }}>
            {error}
            <button onClick={() => setError("")} style={{ marginLeft: "10px", background: "none", border: "none", cursor: "pointer" }}>✕</button>
          </div>
        )}
        {successMsg && (
          <div style={{ background: "#dcfce7", color: "#166534", padding: "10px", borderRadius: "6px", marginBottom: "12px" }}>
            {successMsg}
          </div>
        )}

        {/* Admin credentials + Actions */}
        {isAdmin && (
          <div style={{ display: "flex", gap: "10px", alignItems: "center", marginBottom: "12px", flexWrap: "wrap" }}>
            <input
              type="text"
              placeholder="Admin user"
              value={adminUser}
              onChange={(e) => setAdminUser(e.target.value)}
              style={{ padding: "6px 10px", borderRadius: "4px", border: "1px solid var(--color-border)", width: "120px" }}
            />
            <input
              type="password"
              placeholder="Admin pass"
              value={adminPass}
              onChange={(e) => setAdminPass(e.target.value)}
              style={{ padding: "6px 10px", borderRadius: "4px", border: "1px solid var(--color-border)", width: "120px" }}
            />
            <button
              onClick={() => setShowCreateSg(!showCreateSg)}
              style={{
                padding: "6px 14px",
                background: "#2563eb",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              + Create Security Group
            </button>
          </div>
        )}

        {/* Create Security Group Form */}
        {showCreateSg && (
          <div style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: "8px",
            padding: "16px",
            marginBottom: "16px",
          }}>
            <h3 style={{ marginTop: 0 }}>Create Security Group</h3>
            {createError && (
              <div style={{ color: "#dc2626", marginBottom: "8px" }}>{createError}</div>
            )}
            <div style={{ display: "grid", gap: "10px", gridTemplateColumns: "1fr 1fr" }}>
              <div>
                <label style={{ fontWeight: 600, fontSize: "13px" }}>Name *</label>
                <input
                  type="text"
                  value={newSgName}
                  onChange={(e) => setNewSgName(e.target.value)}
                  placeholder="my-security-group"
                  style={{ width: "100%", padding: "6px 10px", borderRadius: "4px", border: "1px solid var(--color-border)" }}
                />
              </div>
              <div>
                <label style={{ fontWeight: 600, fontSize: "13px" }}>Project (Tenant)</label>
                <select
                  value={newSgProjectId}
                  onChange={(e) => setNewSgProjectId(e.target.value)}
                  style={{ width: "100%", padding: "6px 10px", borderRadius: "4px", border: "1px solid var(--color-border)" }}
                >
                  <option value="">-- Default (service project) --</option>
                  {projects.map((p) => (
                    <option key={p.tenant_id} value={p.tenant_id}>
                      {p.tenant_name} ({p.domain_name})
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <label style={{ fontWeight: 600, fontSize: "13px" }}>Description</label>
                <input
                  type="text"
                  value={newSgDescription}
                  onChange={(e) => setNewSgDescription(e.target.value)}
                  placeholder="Optional description"
                  style={{ width: "100%", padding: "6px 10px", borderRadius: "4px", border: "1px solid var(--color-border)" }}
                />
              </div>
            </div>
            <div style={{ marginTop: "12px", display: "flex", gap: "8px" }}>
              <button
                onClick={handleCreateSg}
                disabled={createLoading}
                style={{
                  padding: "6px 16px",
                  background: "#16a34a",
                  color: "white",
                  border: "none",
                  borderRadius: "4px",
                  cursor: createLoading ? "wait" : "pointer",
                }}
              >
                {createLoading ? "Creating..." : "Create"}
              </button>
              <button
                onClick={() => { setShowCreateSg(false); setCreateError(""); }}
                style={{ padding: "6px 16px", background: "#6b7280", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Filters */}
        <div style={{ display: "flex", gap: "10px", marginBottom: "12px", flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="text"
            placeholder="Filter by name..."
            value={filterName}
            onChange={(e) => { setFilterName(e.target.value); setPage(1); }}
            style={{ padding: "6px 10px", borderRadius: "4px", border: "1px solid var(--color-border)", width: "180px" }}
          />
          <input
            type="text"
            placeholder="Filter by domain..."
            value={filterDomain}
            onChange={(e) => { setFilterDomain(e.target.value); setPage(1); }}
            style={{ padding: "6px 10px", borderRadius: "4px", border: "1px solid var(--color-border)", width: "150px" }}
          />
          <input
            type="text"
            placeholder="Filter by tenant..."
            value={filterTenant}
            onChange={(e) => { setFilterTenant(e.target.value); setPage(1); }}
            style={{ padding: "6px 10px", borderRadius: "4px", border: "1px solid var(--color-border)", width: "150px" }}
          />
          <label style={{ fontSize: "13px" }}>
            Sort
            <select value={sortBy} onChange={(e) => { setSortBy(e.target.value); setPage(1); }} style={{ marginLeft: "4px" }}>
              <option value="security_group_name">Name</option>
              <option value="domain_name">Domain</option>
              <option value="project_name">Project</option>
              <option value="attached_vm_count">VMs</option>
              <option value="ingress_rule_count">Ingress</option>
              <option value="egress_rule_count">Egress</option>
              <option value="last_seen_at">Last seen</option>
            </select>
          </label>
          <select value={sortDir} onChange={(e) => setSortDir(e.target.value as "asc" | "desc")}>
            <option value="asc">Asc</option>
            <option value="desc">Desc</option>
          </select>
          <span style={{ fontSize: "13px", color: "var(--color-text-secondary)" }}>
            {total} security group{total !== 1 ? "s" : ""}
          </span>
          {securityGroups.length > 0 && (
            <button
              onClick={handleExportCsv}
              title="Export current filtered list to CSV"
              style={{
                padding: "5px 12px",
                background: "#059669",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "12px",
                fontWeight: 600,
              }}
            >
              ⬇ Export CSV
            </button>
          )}
        </div>

        {/* Table */}
        {loading ? (
          <div style={{ textAlign: "center", padding: "40px" }}>Loading...</div>
        ) : (
          <table className="pf9-table">
            <thead>
              <tr>
                <th>Security Group</th>
                <th>Domain</th>
                <th>Tenant / Project</th>
                <th>VMs</th>
                <th>Networks</th>
                <th style={{ textAlign: "center" }}>Ingress</th>
                <th style={{ textAlign: "center" }}>Egress</th>
                <th>Last Seen</th>
                {isAdmin && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {securityGroups.length === 0 ? (
                <tr>
                  <td colSpan={isAdmin ? 9 : 8} className="pf9-empty">No security groups found.</td>
                </tr>
              ) : (
                securityGroups.map((sg) => (
                  <tr
                    key={sg.security_group_id}
                    className={selectedSg?.security_group_id === sg.security_group_id ? "pf9-row-selected" : ""}
                    onClick={() => fetchDetail(sg.security_group_id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>
                      <div className="pf9-cell-title">{sg.security_group_name}</div>
                      <div className="pf9-cell-subtle">{sg.security_group_id}</div>
                    </td>
                    <td>{sg.domain_name || "—"}</td>
                    <td>
                      <div>{sg.tenant_name || sg.project_name || "—"}</div>
                      {sg.project_id && <div className="pf9-cell-subtle">{sg.project_id}</div>}
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <span className={sg.attached_vm_count > 0 ? "pf9-badge-success" : "pf9-badge-default"}>
                        {sg.attached_vm_count}
                      </span>
                    </td>
                    <td style={{ textAlign: "center" }}>{sg.attached_network_count}</td>
                    <td style={{ textAlign: "center" }}>
                      <span style={{
                        background: sg.ingress_rule_count > 0 ? "#dbeafe" : "#f3f4f6",
                        color: sg.ingress_rule_count > 0 ? "#1d4ed8" : "#6b7280",
                        padding: "2px 8px",
                        borderRadius: "10px",
                        fontSize: "12px",
                        fontWeight: 600,
                      }}>
                        {sg.ingress_rule_count}
                      </span>
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <span style={{
                        background: sg.egress_rule_count > 0 ? "#fef3c7" : "#f3f4f6",
                        color: sg.egress_rule_count > 0 ? "#92400e" : "#6b7280",
                        padding: "2px 8px",
                        borderRadius: "10px",
                        fontSize: "12px",
                        fontWeight: 600,
                      }}>
                        {sg.egress_rule_count}
                      </span>
                    </td>
                    <td>{formatDate(sg.last_seen_at)}</td>
                    {isAdmin && (
                      <td>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteSg(sg.security_group_id, sg.security_group_name); }}
                          style={{
                            padding: "3px 8px",
                            background: "#ef4444",
                            color: "white",
                            border: "none",
                            borderRadius: "4px",
                            cursor: "pointer",
                            fontSize: "11px",
                          }}
                          title="Delete security group"
                        >
                          Delete
                        </button>
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display: "flex", justifyContent: "center", gap: "8px", marginTop: "12px", alignItems: "center" }}>
            <button disabled={page <= 1} onClick={() => setPage(page - 1)} style={{ padding: "4px 10px" }}>
              ← Prev
            </button>
            <span style={{ fontSize: "13px" }}>
              Page {page} of {totalPages} ({total} total)
            </span>
            <button disabled={page >= totalPages} onClick={() => setPage(page + 1)} style={{ padding: "4px 10px" }}>
              Next →
            </button>
          </div>
        )}
      </div>

      {/* Right: Detail Panel */}
      <div style={{ flex: 1, minWidth: "350px", overflow: "auto" }}>
        {detailLoading && (
          <div style={{ textAlign: "center", padding: "40px" }}>Loading details...</div>
        )}

        {!detailLoading && !selectedSg && (
          <div style={{ textAlign: "center", padding: "40px", color: "var(--color-text-secondary)" }}>
            <p>Click a security group to see details, rules, attached VMs, and networks.</p>
          </div>
        )}

        {!detailLoading && selectedSg && (
          <div>
            <h2 style={{ marginTop: 0 }}>{selectedSg.security_group_name}</h2>
            <div style={{ fontSize: "13px", color: "var(--color-text-secondary)", marginBottom: "16px" }}>
              {selectedSg.security_group_id}
            </div>

            {selectedSg.description && (
              <p style={{ fontStyle: "italic", color: "var(--color-text-secondary)" }}>{selectedSg.description}</p>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "20px" }}>
              <div><strong>Domain:</strong> {selectedSg.domain_name || "—"}</div>
              <div><strong>Tenant:</strong> {selectedSg.tenant_name || "—"}</div>
              <div><strong>Project:</strong> {selectedSg.project_name || "—"}</div>
              <div><strong>Project ID:</strong> <span style={{ fontSize: "11px" }}>{selectedSg.project_id || "—"}</span></div>
              <div><strong>Created:</strong> {formatDate(selectedSg.created_at)}</div>
              <div><strong>Last seen:</strong> {formatDate(selectedSg.last_seen_at)}</div>
            </div>

            {/* Rules Section */}
            <div style={{ borderTop: "1px solid var(--color-border)", paddingTop: "16px", marginBottom: "16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                <h3 style={{ margin: 0 }}>
                  Rules ({selectedSg.rules.length})
                </h3>
                {isAdmin && (
                  <button
                    onClick={() => setShowCreateRule(!showCreateRule)}
                    style={{
                      padding: "4px 10px",
                      background: "#2563eb",
                      color: "white",
                      border: "none",
                      borderRadius: "4px",
                      cursor: "pointer",
                      fontSize: "12px",
                    }}
                  >
                    + Add Rule
                  </button>
                )}
              </div>

              {/* Rule Template Presets */}
              {isAdmin && (
                <div style={{ marginBottom: "10px" }}>
                  <div style={{ fontSize: "11px", color: "var(--color-text-secondary)", marginBottom: "4px" }}>Quick templates:</div>
                  <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                    {RULE_TEMPLATES.map((tpl) => (
                      <button
                        key={tpl.label}
                        onClick={() => applyRuleTemplate(tpl)}
                        title={`${tpl.description} (${tpl.direction} ${tpl.protocol}${tpl.portMin ? ` port ${tpl.portMin}` : ""})`}
                        style={{
                          padding: "3px 8px",
                          background: "var(--color-surface)",
                          border: "1px solid var(--color-border)",
                          borderRadius: "4px",
                          cursor: "pointer",
                          fontSize: "11px",
                          fontWeight: 500,
                          display: "flex",
                          alignItems: "center",
                          gap: "3px",
                        }}
                      >
                        <span>{tpl.icon}</span> {tpl.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Create Rule Form */}
              {showCreateRule && (
                <div style={{
                  background: "var(--color-background)",
                  border: "1px solid var(--color-border)",
                  borderRadius: "6px",
                  padding: "12px",
                  marginBottom: "12px",
                }}>
                  {ruleCreateError && (
                    <div style={{ color: "#dc2626", marginBottom: "8px", fontSize: "12px" }}>{ruleCreateError}</div>
                  )}
                  <div style={{ display: "grid", gap: "8px", gridTemplateColumns: "1fr 1fr" }}>
                    <div>
                      <label style={{ fontSize: "12px", fontWeight: 600 }}>Direction *</label>
                      <select
                        value={newRuleDirection}
                        onChange={(e) => setNewRuleDirection(e.target.value as "ingress" | "egress")}
                        style={{ width: "100%", padding: "4px" }}
                      >
                        <option value="ingress">Ingress (Inbound)</option>
                        <option value="egress">Egress (Outbound)</option>
                      </select>
                    </div>
                    <div>
                      <label style={{ fontSize: "12px", fontWeight: 600 }}>Ether Type</label>
                      <select
                        value={newRuleEthertype}
                        onChange={(e) => setNewRuleEthertype(e.target.value)}
                        style={{ width: "100%", padding: "4px" }}
                      >
                        <option value="IPv4">IPv4</option>
                        <option value="IPv6">IPv6</option>
                      </select>
                    </div>
                    <div>
                      <label style={{ fontSize: "12px", fontWeight: 600 }}>Protocol</label>
                      <select
                        value={newRuleProtocol}
                        onChange={(e) => setNewRuleProtocol(e.target.value)}
                        style={{ width: "100%", padding: "4px" }}
                      >
                        <option value="">Any</option>
                        <option value="tcp">TCP</option>
                        <option value="udp">UDP</option>
                        <option value="icmp">ICMP</option>
                      </select>
                    </div>
                    <div>
                      <label style={{ fontSize: "12px", fontWeight: 600 }}>Remote IP Prefix</label>
                      <input
                        type="text"
                        value={newRuleRemoteIp}
                        onChange={(e) => setNewRuleRemoteIp(e.target.value)}
                        placeholder="0.0.0.0/0"
                        style={{ width: "100%", padding: "4px", border: "1px solid var(--color-border)", borderRadius: "4px" }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: "12px", fontWeight: 600 }}>Port Min</label>
                      <input
                        type="number"
                        value={newRulePortMin}
                        onChange={(e) => setNewRulePortMin(e.target.value)}
                        placeholder="e.g. 22"
                        style={{ width: "100%", padding: "4px", border: "1px solid var(--color-border)", borderRadius: "4px" }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: "12px", fontWeight: 600 }}>Port Max</label>
                      <input
                        type="number"
                        value={newRulePortMax}
                        onChange={(e) => setNewRulePortMax(e.target.value)}
                        placeholder="e.g. 22"
                        style={{ width: "100%", padding: "4px", border: "1px solid var(--color-border)", borderRadius: "4px" }}
                      />
                    </div>
                    <div style={{ gridColumn: "1 / -1" }}>
                      <label style={{ fontSize: "12px", fontWeight: 600 }}>Description</label>
                      <input
                        type="text"
                        value={newRuleDescription}
                        onChange={(e) => setNewRuleDescription(e.target.value)}
                        placeholder="Optional"
                        style={{ width: "100%", padding: "4px", border: "1px solid var(--color-border)", borderRadius: "4px" }}
                      />
                    </div>
                  </div>
                  <div style={{ marginTop: "8px", display: "flex", gap: "6px" }}>
                    <button
                      onClick={handleCreateRule}
                      disabled={ruleCreateLoading}
                      style={{ padding: "4px 12px", background: "#16a34a", color: "white", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "12px" }}
                    >
                      {ruleCreateLoading ? "Creating..." : "Add Rule"}
                    </button>
                    <button
                      onClick={() => { setShowCreateRule(false); setRuleCreateError(""); resetRuleForm(); }}
                      style={{ padding: "4px 12px", background: "#6b7280", color: "white", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "12px" }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {/* Ingress Rules */}
              {selectedSg.rules.filter((r) => r.direction === "ingress").length > 0 && (
                <div style={{ marginBottom: "12px" }}>
                  <h4 style={{ color: "#1d4ed8", margin: "0 0 6px 0", fontSize: "13px" }}>
                    ↓ Ingress ({selectedSg.rules.filter((r) => r.direction === "ingress").length})
                  </h4>
                  <table style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
                        <th style={{ textAlign: "left", padding: "4px" }}>Rule</th>
                        <th style={{ textAlign: "left", padding: "4px" }}>Protocol</th>
                        <th style={{ textAlign: "left", padding: "4px" }}>Port(s)</th>
                        <th style={{ textAlign: "left", padding: "4px" }}>Source</th>
                        {isAdmin && <th style={{ padding: "4px" }}></th>}
                      </tr>
                    </thead>
                    <tbody>
                      {selectedSg.rules
                        .filter((r) => r.direction === "ingress")
                        .map((rule) => (
                          <tr key={rule.rule_id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                            <td style={{ padding: "4px" }}>
                              <div style={{ fontWeight: 600 }}>{rule.rule_summary || "—"}</div>
                              {rule.description && (
                                <div style={{ fontSize: "10px", color: "var(--color-text-secondary)", fontStyle: "italic" }}>{rule.description}</div>
                              )}
                            </td>
                            <td style={{ padding: "4px" }}>{rule.protocol || "Any"}</td>
                            <td style={{ padding: "4px" }}>{formatPortRange(rule)}</td>
                            <td style={{ padding: "4px" }}>{rule.remote_ip_prefix || rule.remote_group_name || rule.remote_group_id || "Any"}</td>
                            {isAdmin && (
                              <td style={{ padding: "4px", textAlign: "center" }}>
                                <button
                                  onClick={() => handleDeleteRule(rule.rule_id)}
                                  style={{ background: "#ef4444", color: "white", border: "none", borderRadius: "3px", padding: "2px 6px", cursor: "pointer", fontSize: "10px" }}
                                >
                                  ✕
                                </button>
                              </td>
                            )}
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Egress Rules */}
              {selectedSg.rules.filter((r) => r.direction === "egress").length > 0 && (
                <div style={{ marginBottom: "12px" }}>
                  <h4 style={{ color: "#92400e", margin: "0 0 6px 0", fontSize: "13px" }}>
                    ↑ Egress ({selectedSg.rules.filter((r) => r.direction === "egress").length})
                  </h4>
                  <table style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
                        <th style={{ textAlign: "left", padding: "4px" }}>Rule</th>
                        <th style={{ textAlign: "left", padding: "4px" }}>Protocol</th>
                        <th style={{ textAlign: "left", padding: "4px" }}>Port(s)</th>
                        <th style={{ textAlign: "left", padding: "4px" }}>Destination</th>
                        {isAdmin && <th style={{ padding: "4px" }}></th>}
                      </tr>
                    </thead>
                    <tbody>
                      {selectedSg.rules
                        .filter((r) => r.direction === "egress")
                        .map((rule) => (
                          <tr key={rule.rule_id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                            <td style={{ padding: "4px" }}>
                              <div style={{ fontWeight: 600 }}>{rule.rule_summary || "—"}</div>
                              {rule.description && (
                                <div style={{ fontSize: "10px", color: "var(--color-text-secondary)", fontStyle: "italic" }}>{rule.description}</div>
                              )}
                            </td>
                            <td style={{ padding: "4px" }}>{rule.protocol || "Any"}</td>
                            <td style={{ padding: "4px" }}>{formatPortRange(rule)}</td>
                            <td style={{ padding: "4px" }}>{rule.remote_ip_prefix || rule.remote_group_name || rule.remote_group_id || "Any"}</td>
                            {isAdmin && (
                              <td style={{ padding: "4px", textAlign: "center" }}>
                                <button
                                  onClick={() => handleDeleteRule(rule.rule_id)}
                                  style={{ background: "#ef4444", color: "white", border: "none", borderRadius: "3px", padding: "2px 6px", cursor: "pointer", fontSize: "10px" }}
                                >
                                  ✕
                                </button>
                              </td>
                            )}
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}

              {selectedSg.rules.length === 0 && (
                <div style={{ color: "var(--color-text-secondary)", fontSize: "13px", fontStyle: "italic" }}>
                  No rules defined.
                </div>
              )}
            </div>

            {/* Attached VMs */}
            <div style={{ borderTop: "1px solid var(--color-border)", paddingTop: "16px", marginBottom: "16px" }}>
              <h3 style={{ margin: "0 0 8px 0" }}>
                Attached VMs ({selectedSg.attached_vms.length})
              </h3>
              {selectedSg.attached_vms.length > 0 ? (
                <table style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
                      <th style={{ textAlign: "left", padding: "4px" }}>VM</th>
                      <th style={{ textAlign: "left", padding: "4px" }}>Status</th>
                      <th style={{ textAlign: "left", padding: "4px" }}>Network</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedSg.attached_vms.map((vm) => (
                      <tr key={`${vm.vm_id}-${vm.network_id}`} style={{ borderBottom: "1px solid var(--color-border)" }}>
                        <td style={{ padding: "4px" }}>
                          <div style={{ fontWeight: 600 }}>{vm.vm_name}</div>
                          <div style={{ fontSize: "10px", color: "var(--color-text-secondary)" }}>{vm.vm_id}</div>
                        </td>
                        <td style={{ padding: "4px" }}>
                          <span className={vm.vm_status === "ACTIVE" ? "pf9-badge-success" : "pf9-badge-default"}>
                            {vm.vm_status}
                          </span>
                        </td>
                        <td style={{ padding: "4px" }}>{vm.network_name || vm.network_id}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={{ color: "var(--color-text-secondary)", fontSize: "13px", fontStyle: "italic" }}>
                  No VMs attached.
                </div>
              )}
            </div>

            {/* Attached Networks */}
            <div style={{ borderTop: "1px solid var(--color-border)", paddingTop: "16px" }}>
              <h3 style={{ margin: "0 0 8px 0" }}>
                Attached Networks ({selectedSg.attached_networks.length})
              </h3>
              {selectedSg.attached_networks.length > 0 ? (
                <table style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
                      <th style={{ textAlign: "left", padding: "4px" }}>Network</th>
                      <th style={{ textAlign: "left", padding: "4px" }}>Shared</th>
                      <th style={{ textAlign: "left", padding: "4px" }}>External</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedSg.attached_networks.map((net) => (
                      <tr key={net.network_id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                        <td style={{ padding: "4px" }}>
                          <div style={{ fontWeight: 600 }}>{net.network_name}</div>
                          <div style={{ fontSize: "10px", color: "var(--color-text-secondary)" }}>{net.network_id}</div>
                        </td>
                        <td style={{ padding: "4px" }}>{net.is_shared ? "Yes" : "No"}</td>
                        <td style={{ padding: "4px" }}>{net.is_external ? "Yes" : "No"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div style={{ color: "var(--color-text-secondary)", fontSize: "13px", fontStyle: "italic" }}>
                  No networks found.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default SecurityGroupsTab;
