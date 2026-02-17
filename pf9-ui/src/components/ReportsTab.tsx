/**
 * ReportsTab – Comprehensive Reporting System
 * Browse report catalog, configure parameters, preview data, and export to CSV.
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

interface ReportDef {
  id: string;
  name: string;
  description: string;
  category: string;
  parameters: string[];
}

interface DomainOption {
  id: string;
  name: string;
}
interface ProjectOption {
  id: string;
  name: string;
  domain_id: string;
  domain_name: string;
}

interface Props {
  isAdmin?: boolean;
}

const CATEGORY_COLORS: Record<string, string> = {
  capacity: "#3b82f6",
  inventory: "#8b5cf6",
  compliance: "#10b981",
  billing: "#f59e0b",
  security: "#ef4444",
  optimization: "#06b6d4",
  audit: "#6366f1",
};

const CATEGORY_ICONS: Record<string, string> = {
  capacity: "📊",
  inventory: "📋",
  compliance: "✅",
  billing: "💰",
  security: "🔒",
  optimization: "⚡",
  audit: "📝",
};

export default function ReportsTab({ isAdmin }: Props) {
  const [catalog, setCatalog] = useState<ReportDef[]>([]);
  const [selectedReport, setSelectedReport] = useState<ReportDef | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [reportData, setReportData] = useState<any[] | null>(null);
  const [exporting, setExporting] = useState(false);

  // Filter params
  const [filterCategory, setFilterCategory] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // Report parameters
  const [domainId, setDomainId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [hours, setHours] = useState(720);
  const [days, setDays] = useState(30);
  const [action, setAction] = useState("");
  const [resourceType, setResourceType] = useState("");

  // Dropdowns
  const [domains, setDomains] = useState<DomainOption[]>([]);
  const [projects, setProjects] = useState<ProjectOption[]>([]);

  // Load catalog
  useEffect(() => {
    apiFetch<{ reports: ReportDef[] }>("/api/reports/catalog")
      .then((r) => setCatalog(r.reports))
      .catch((e) => setError(e.message));

    // Load domains for filters
    apiFetch<{ data: DomainOption[] }>("/api/resources/context/domains")
      .then((r) => setDomains(r.data))
      .catch(() => {});

    apiFetch<{ data: ProjectOption[] }>("/api/resources/context/projects")
      .then((r) => setProjects(r.data))
      .catch(() => {});
  }, []);

  const categories = Array.from(new Set(catalog.map((r) => r.category)));

  const filteredCatalog = catalog.filter((r) => {
    if (filterCategory && r.category !== filterCategory) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        r.name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const runReport = useCallback(async () => {
    if (!selectedReport) return;
    setLoading(true);
    setError("");
    setReportData(null);
    try {
      const params = new URLSearchParams();
      params.set("format", "json");
      if (selectedReport.parameters.includes("domain_id") && domainId) {
        params.set("domain_id", domainId);
      }
      if (selectedReport.parameters.includes("project_id") && projectId) {
        params.set("project_id", projectId);
      }
      if (selectedReport.parameters.includes("hours")) {
        params.set("hours", hours.toString());
      }
      if (selectedReport.parameters.includes("days")) {
        params.set("days", days.toString());
      }
      if (selectedReport.parameters.includes("action") && action) {
        params.set("action", action);
      }
      if (selectedReport.parameters.includes("resource_type") && resourceType) {
        params.set("resource_type", resourceType);
      }
      const data = await apiFetch<{ data: any[]; count: number }>(
        `/api/reports/${selectedReport.id}?${params.toString()}`
      );
      setReportData(data.data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [selectedReport, domainId, projectId, hours, days, action, resourceType]);

  const exportCSV = useCallback(async () => {
    if (!selectedReport) return;
    setExporting(true);
    try {
      const params = new URLSearchParams();
      params.set("format", "csv");
      if (selectedReport.parameters.includes("domain_id") && domainId) {
        params.set("domain_id", domainId);
      }
      if (selectedReport.parameters.includes("project_id") && projectId) {
        params.set("project_id", projectId);
      }
      if (selectedReport.parameters.includes("hours")) {
        params.set("hours", hours.toString());
      }
      if (selectedReport.parameters.includes("days")) {
        params.set("days", days.toString());
      }
      if (selectedReport.parameters.includes("action") && action) {
        params.set("action", action);
      }
      if (selectedReport.parameters.includes("resource_type") && resourceType) {
        params.set("resource_type", resourceType);
      }

      const token = getToken();
      const res = await fetch(
        `${API_BASE}/api/reports/${selectedReport.id}?${params.toString()}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} }
      );
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${selectedReport.id}_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setExporting(false);
    }
  }, [selectedReport, domainId, projectId, hours, days, action, resourceType]);

  // -----------------------------------------------------------------------
  // Styles
  // -----------------------------------------------------------------------
  const containerStyle: React.CSSProperties = {
    padding: "24px",
    maxWidth: "1400px",
    margin: "0 auto",
  };
  const headerStyle: React.CSSProperties = {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "20px",
    flexWrap: "wrap",
    gap: "12px",
  };
  const searchStyle: React.CSSProperties = {
    padding: "8px 14px",
    borderRadius: "6px",
    border: "1px solid var(--pf9-border, #374151)",
    background: "var(--pf9-input-bg, #1f2937)",
    color: "var(--pf9-text, #e5e7eb)",
    fontSize: "14px",
    width: "240px",
  };
  const filterBarStyle: React.CSSProperties = {
    display: "flex",
    gap: "8px",
    flexWrap: "wrap",
    marginBottom: "16px",
  };
  const chipStyle = (active: boolean, color: string): React.CSSProperties => ({
    padding: "4px 12px",
    borderRadius: "16px",
    border: `1px solid ${active ? color : "var(--pf9-border, #374151)"}`,
    background: active ? `${color}22` : "transparent",
    color: active ? color : "var(--pf9-text-secondary, #9ca3af)",
    cursor: "pointer",
    fontSize: "12px",
    fontWeight: active ? 600 : 400,
    transition: "all 0.2s",
  });
  const gridStyle: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
    gap: "16px",
    marginBottom: "24px",
  };
  const cardStyle = (selected: boolean): React.CSSProperties => ({
    padding: "16px",
    borderRadius: "10px",
    border: `2px solid ${selected ? "#3b82f6" : "var(--pf9-border, #374151)"}`,
    background: selected
      ? "var(--pf9-hover, #1e3a5f)"
      : "var(--pf9-card-bg, #111827)",
    cursor: "pointer",
    transition: "all 0.2s",
  });
  const badgeStyle = (color: string): React.CSSProperties => ({
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: "10px",
    background: `${color}30`,
    color,
    fontSize: "11px",
    fontWeight: 600,
    textTransform: "uppercase" as const,
  });
  const sectionStyle: React.CSSProperties = {
    padding: "20px",
    borderRadius: "10px",
    border: "1px solid var(--pf9-border, #374151)",
    background: "var(--pf9-card-bg, #111827)",
    marginBottom: "20px",
  };
  const btnStyle = (variant: string): React.CSSProperties => ({
    padding: "8px 20px",
    borderRadius: "6px",
    border: "none",
    fontWeight: 600,
    fontSize: "14px",
    cursor: "pointer",
    color: "#fff",
    background:
      variant === "primary"
        ? "#3b82f6"
        : variant === "success"
        ? "#10b981"
        : "#6b7280",
    opacity: loading || exporting ? 0.6 : 1,
  });
  const selectStyle: React.CSSProperties = {
    padding: "6px 10px",
    borderRadius: "6px",
    border: "1px solid var(--pf9-border, #374151)",
    background: "var(--pf9-input-bg, #1f2937)",
    color: "var(--pf9-text, #e5e7eb)",
    fontSize: "13px",
  };
  const inputStyle: React.CSSProperties = {
    ...selectStyle,
    width: "100px",
  };
  const tableContainerStyle: React.CSSProperties = {
    overflowX: "auto",
    maxHeight: "500px",
    overflowY: "auto",
    borderRadius: "8px",
    border: "1px solid var(--pf9-border, #374151)",
  };
  const thStyle: React.CSSProperties = {
    padding: "8px 12px",
    textAlign: "left",
    fontSize: "12px",
    fontWeight: 600,
    color: "var(--pf9-text-secondary, #9ca3af)",
    background: "var(--pf9-header-bg, #1f2937)",
    borderBottom: "1px solid var(--pf9-border, #374151)",
    whiteSpace: "nowrap",
    position: "sticky",
    top: 0,
    zIndex: 1,
  };
  const tdStyle: React.CSSProperties = {
    padding: "6px 12px",
    fontSize: "13px",
    borderBottom: "1px solid var(--pf9-border, #374151)",
    whiteSpace: "nowrap",
    maxWidth: "300px",
    overflow: "hidden",
    textOverflow: "ellipsis",
  };

  return (
    <div style={containerStyle}>
      {/* Header */}
      <div style={headerStyle}>
        <div>
          <h2 style={{ margin: 0, fontSize: "22px" }}>📊 Reports</h2>
          <p style={{ margin: "4px 0 0", color: "var(--pf9-text-secondary, #9ca3af)", fontSize: "13px" }}>
            {catalog.length} reports available &middot; Preview data and export to CSV
          </p>
        </div>
        <input
          type="text"
          placeholder="Search reports..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={searchStyle}
        />
      </div>

      {/* Category filters */}
      <div style={filterBarStyle}>
        <span
          style={chipStyle(!filterCategory, "#6b7280")}
          onClick={() => setFilterCategory("")}
        >
          All ({catalog.length})
        </span>
        {categories.map((cat) => (
          <span
            key={cat}
            style={chipStyle(filterCategory === cat, CATEGORY_COLORS[cat] || "#6b7280")}
            onClick={() => setFilterCategory(filterCategory === cat ? "" : cat)}
          >
            {CATEGORY_ICONS[cat] || "📄"} {cat} (
            {catalog.filter((r) => r.category === cat).length})
          </span>
        ))}
      </div>

      {error && (
        <div
          style={{
            padding: "10px 16px",
            borderRadius: "8px",
            background: "#991b1b33",
            color: "#ef4444",
            marginBottom: "16px",
            fontSize: "13px",
          }}
        >
          {error}
        </div>
      )}

      {/* Report Catalog Grid */}
      <div style={gridStyle}>
        {filteredCatalog.map((r) => (
          <div
            key={r.id}
            style={cardStyle(selectedReport?.id === r.id)}
            onClick={() => {
              setSelectedReport(r);
              setReportData(null);
              setError("");
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
              <h3 style={{ margin: 0, fontSize: "15px", fontWeight: 600 }}>{r.name}</h3>
              <span style={badgeStyle(CATEGORY_COLORS[r.category] || "#6b7280")}>
                {r.category}
              </span>
            </div>
            <p style={{ margin: 0, fontSize: "12px", color: "var(--pf9-text-secondary, #9ca3af)", lineHeight: 1.5 }}>
              {r.description}
            </p>
          </div>
        ))}
      </div>

      {/* Selected Report - Parameters & Run */}
      {selectedReport && (
        <div style={sectionStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", flexWrap: "wrap", gap: "12px" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "17px" }}>
                {CATEGORY_ICONS[selectedReport.category]} {selectedReport.name}
              </h3>
              <p style={{ margin: "4px 0 0", fontSize: "12px", color: "var(--pf9-text-secondary, #9ca3af)" }}>
                {selectedReport.description}
              </p>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button
                style={btnStyle("primary")}
                onClick={runReport}
                disabled={loading}
              >
                {loading ? "Running..." : "▶ Run Report"}
              </button>
              <button
                style={btnStyle("success")}
                onClick={exportCSV}
                disabled={exporting || loading}
              >
                {exporting ? "Exporting..." : "📥 Export CSV"}
              </button>
            </div>
          </div>

          {/* Parameters */}
          {selectedReport.parameters.length > 0 && (
            <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", marginBottom: "16px", padding: "12px", borderRadius: "8px", background: "var(--pf9-input-bg, #1f2937)" }}>
              {selectedReport.parameters.includes("domain_id") && (
                <label style={{ fontSize: "13px" }}>
                  Domain:{" "}
                  <select
                    value={domainId}
                    onChange={(e) => setDomainId(e.target.value)}
                    style={selectStyle}
                  >
                    <option value="">All Domains</option>
                    {domains.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {selectedReport.parameters.includes("project_id") && (
                <label style={{ fontSize: "13px" }}>
                  Tenant:{" "}
                  <select
                    value={projectId}
                    onChange={(e) => setProjectId(e.target.value)}
                    style={selectStyle}
                  >
                    <option value="">All Tenants</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({p.domain_name})
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {selectedReport.parameters.includes("hours") && (
                <label style={{ fontSize: "13px" }}>
                  Hours:{" "}
                  <input
                    type="number"
                    value={hours}
                    min={1}
                    max={8760}
                    onChange={(e) => setHours(parseInt(e.target.value) || 720)}
                    style={inputStyle}
                  />
                </label>
              )}
              {selectedReport.parameters.includes("days") && (
                <label style={{ fontSize: "13px" }}>
                  Days:{" "}
                  <input
                    type="number"
                    value={days}
                    min={1}
                    max={365}
                    onChange={(e) => setDays(parseInt(e.target.value) || 30)}
                    style={inputStyle}
                  />
                </label>
              )}
              {selectedReport.parameters.includes("action") && (
                <label style={{ fontSize: "13px" }}>
                  Action:{" "}
                  <select
                    value={action}
                    onChange={(e) => setAction(e.target.value)}
                    style={selectStyle}
                  >
                    <option value="">All</option>
                    <option value="create">Create</option>
                    <option value="delete">Delete</option>
                    <option value="update">Update</option>
                    <option value="assign_role">Assign Role</option>
                    <option value="provision">Provision</option>
                  </select>
                </label>
              )}
              {selectedReport.parameters.includes("resource_type") && (
                <label style={{ fontSize: "13px" }}>
                  Resource:{" "}
                  <select
                    value={resourceType}
                    onChange={(e) => setResourceType(e.target.value)}
                    style={selectStyle}
                  >
                    <option value="">All</option>
                    <option value="domain">Domain</option>
                    <option value="project">Project</option>
                    <option value="user">User</option>
                    <option value="server">Server</option>
                    <option value="volume">Volume</option>
                    <option value="network">Network</option>
                    <option value="router">Router</option>
                    <option value="security_group">Security Group</option>
                    <option value="flavor">Flavor</option>
                    <option value="floating_ip">Floating IP</option>
                  </select>
                </label>
              )}
            </div>
          )}

          {/* Results table */}
          {reportData && reportData.length > 0 && (
            <div>
              <div style={{ marginBottom: "8px", fontSize: "13px", color: "var(--pf9-text-secondary, #9ca3af)" }}>
                {reportData.length} rows returned
              </div>
              <div style={tableContainerStyle}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {Object.keys(reportData[0]).map((key) => (
                        <th key={key} style={thStyle}>
                          {key}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {reportData.map((row, i) => (
                      <tr
                        key={i}
                        style={{
                          background:
                            i % 2 === 0
                              ? "transparent"
                              : "var(--pf9-row-alt, #1f293710)",
                        }}
                      >
                        {Object.values(row).map((val: any, j) => (
                          <td key={j} style={tdStyle} title={String(val ?? "")}>
                            {val === null || val === undefined
                              ? "—"
                              : typeof val === "boolean"
                              ? val
                                ? "✅"
                                : "❌"
                              : String(val)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {reportData && reportData.length === 0 && (
            <div
              style={{
                textAlign: "center",
                padding: "40px",
                color: "var(--pf9-text-secondary, #9ca3af)",
              }}
            >
              No data found for the selected parameters.
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!selectedReport && filteredCatalog.length === 0 && (
        <div
          style={{
            textAlign: "center",
            padding: "60px",
            color: "var(--pf9-text-secondary, #9ca3af)",
          }}
        >
          No reports match your search.
        </div>
      )}
    </div>
  );
}
