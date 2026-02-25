/**
 * MigrationPlannerTab — VMware → PCD Migration Intelligence Cockpit
 *
 * Top-level container with internal sub-navigation:
 *   • Projects    — list/create/manage migration projects
 *   • Setup       — upload RVTools, configure topology & agents
 *   • Analysis    — VM inventory, tenants, risk & mode scoring
 *   • (Future: Readiness, Waves, Runbook — Phases 4-7)
 */

import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";
import ProjectSetup from "./migration/ProjectSetup";
import SourceAnalysis from "./migration/SourceAnalysis";

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
  // Don't set Content-Type for FormData
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

export interface MigrationProject {
  id: number;
  project_id: string;
  name: string;
  description: string;
  status: string;
  topology_type: string;
  source_nic_speed_gbps: number;
  source_usable_pct: number;
  link_speed_gbps: number | null;
  link_usable_pct: number;
  source_upload_mbps: number | null;
  dest_download_mbps: number | null;
  rtt_category: string | null;
  target_ingress_speed_gbps: number;
  target_usable_pct: number;
  pcd_storage_write_mbps: number;
  agent_count: number;
  agent_concurrent_vms: number;
  agent_nic_speed_gbps: number;
  agent_nic_usable_pct: number;
  migration_duration_days: number | null;
  working_hours_per_day: number | null;
  working_days_per_week: number | null;
  target_vms_per_day: number | null;
  rvtools_filename: string | null;
  rvtools_uploaded_at: string | null;
  rvtools_sheet_stats: Record<string, any>;
  created_by: string;
  created_at: string;
  updated_at: string;
  vm_count?: number;
  tenant_count?: number;
  // Detail fields
  risk_summary?: Record<string, number>;
  mode_summary?: Record<string, number>;
  totals?: Record<string, any>;
}

type SubView = "projects" | "setup" | "analysis";

interface Props {
  isAdmin?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Status badge colors                                                */
/* ------------------------------------------------------------------ */
const STATUS_COLORS: Record<string, string> = {
  draft: "#6b7280",
  assessment: "#3b82f6",
  planned: "#8b5cf6",
  approved: "#10b981",
  preparing: "#f59e0b",
  ready: "#22c55e",
  executing: "#ef4444",
  completed: "#16a34a",
  cancelled: "#9ca3af",
  archived: "#6b7280",
};

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function MigrationPlannerTab({ isAdmin }: Props) {
  const [subView, setSubView] = useState<SubView>("projects");
  const [projects, setProjects] = useState<MigrationProject[]>([]);
  const [selectedProject, setSelectedProject] = useState<MigrationProject | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  /* ---- Project list ---- */
  const loadProjects = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch<{ projects: MigrationProject[] }>("/api/migration/projects");
      setProjects(data.projects);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  /* ---- Select project and navigate ---- */
  const selectProject = useCallback(async (projectId: string, goTo: SubView = "setup") => {
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch<{ project: MigrationProject }>(`/api/migration/projects/${projectId}`);
      setSelectedProject(data.project);
      setSubView(goTo);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  /* ---- Create new project ---- */
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    setError("");
    try {
      const data = await apiFetch<{ project: MigrationProject }>("/api/migration/projects", {
        method: "POST",
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() }),
      });
      setShowCreate(false);
      setNewName("");
      setNewDesc("");
      await loadProjects();
      selectProject(data.project.project_id, "setup");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCreating(false);
    }
  };

  /* ---- Delete project ---- */
  const handleDelete = async (projectId: string, name: string) => {
    if (!confirm(`Delete migration project "${name}" and ALL associated data? This cannot be undone.`)) return;
    try {
      await apiFetch(`/api/migration/projects/${projectId}`, { method: "DELETE" });
      if (selectedProject?.project_id === projectId) {
        setSelectedProject(null);
        setSubView("projects");
      }
      loadProjects();
    } catch (e: any) {
      setError(e.message);
    }
  };

  /* ---- Archive project ---- */
  const handleArchive = async (projectId: string, name: string) => {
    if (!confirm(`Archive "${name}"? This saves a summary and purges all detailed data.`)) return;
    try {
      await apiFetch(`/api/migration/projects/${projectId}/archive`, { method: "POST" });
      if (selectedProject?.project_id === projectId) {
        setSelectedProject(null);
        setSubView("projects");
      }
      loadProjects();
    } catch (e: any) {
      setError(e.message);
    }
  };

  /* ================================================================ */
  /*  Render                                                          */
  /* ================================================================ */
  return (
    <div style={{ padding: "0 16px 16px 16px" }}>
      {/* Sub-navigation */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "center", flexWrap: "wrap" }}>
        <button
          onClick={() => { setSubView("projects"); setSelectedProject(null); }}
          style={subNavStyle(subView === "projects")}
        >
          📋 Projects
        </button>
        {selectedProject && (
          <>
            <span style={{ color: "#6b7280" }}>▸</span>
            <button onClick={() => setSubView("setup")} style={subNavStyle(subView === "setup")}>
              ⚙️ Setup
            </button>
            <button
              onClick={() => setSubView("analysis")}
              style={subNavStyle(subView === "analysis")}
              disabled={!selectedProject.rvtools_filename}
              title={!selectedProject.rvtools_filename ? "Upload RVTools first" : ""}
            >
              📊 Analysis
            </button>
            <span style={{ color: "#6b7280", fontSize: "0.85rem", marginLeft: 8 }}>
              <strong>{selectedProject.name}</strong>
              <span style={{
                marginLeft: 8, padding: "2px 8px", borderRadius: 12, fontSize: "0.75rem",
                color: "#fff", background: STATUS_COLORS[selectedProject.status] || "#6b7280"
              }}>
                {selectedProject.status}
              </span>
            </span>
          </>
        )}
      </div>

      {error && (
        <div style={{ background: "#fef2f2", color: "#dc2626", padding: "8px 12px", borderRadius: 6, marginBottom: 12, border: "1px solid #fecaca" }}>
          {error}
        </div>
      )}

      {/* ---- Projects list view ---- */}
      {subView === "projects" && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h2 style={{ margin: 0 }}>Migration Projects</h2>
            <button onClick={() => setShowCreate(true)} style={btnPrimary}>
              + New Project
            </button>
          </div>

          {/* Create dialog */}
          {showCreate && (
            <div style={{ background: "var(--card-bg, #f9fafb)", border: "1px solid var(--border, #e5e7eb)", borderRadius: 8, padding: 16, marginBottom: 16 }}>
              <h3 style={{ marginTop: 0 }}>New Migration Project</h3>
              <div style={{ marginBottom: 8 }}>
                <label style={labelStyle}>Project Name *</label>
                <input value={newName} onChange={e => setNewName(e.target.value)} style={inputStyle} placeholder="e.g. Acme Corp VMware Migration" />
              </div>
              <div style={{ marginBottom: 12 }}>
                <label style={labelStyle}>Description</label>
                <textarea value={newDesc} onChange={e => setNewDesc(e.target.value)} style={{ ...inputStyle, minHeight: 60 }} placeholder="Optional description..." />
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={handleCreate} disabled={creating || !newName.trim()} style={btnPrimary}>
                  {creating ? "Creating..." : "Create Project"}
                </button>
                <button onClick={() => setShowCreate(false)} style={btnSecondary}>Cancel</button>
              </div>
            </div>
          )}

          {loading && <p>Loading...</p>}

          {!loading && projects.length === 0 && (
            <div style={{ textAlign: "center", padding: 40, color: "#6b7280" }}>
              <p style={{ fontSize: "1.1rem" }}>No migration projects yet.</p>
              <p>Create a new project and upload an RVTools XLSX to get started.</p>
            </div>
          )}

          {/* Project cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 16 }}>
            {projects.map(p => (
              <div key={p.project_id} style={{
                background: "var(--card-bg, #fff)", border: "1px solid var(--border, #e5e7eb)",
                borderRadius: 8, padding: 16, cursor: "pointer",
                transition: "box-shadow 0.2s",
              }}
                onClick={() => selectProject(p.project_id, p.rvtools_filename ? "analysis" : "setup")}
                onMouseEnter={e => (e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.12)")}
                onMouseLeave={e => (e.currentTarget.style.boxShadow = "none")}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <h3 style={{ margin: "0 0 4px 0" }}>{p.name}</h3>
                    {p.description && <p style={{ margin: 0, fontSize: "0.85rem", color: "#6b7280" }}>{p.description}</p>}
                  </div>
                  <span style={{
                    padding: "2px 10px", borderRadius: 12, fontSize: "0.75rem", fontWeight: 600,
                    color: "#fff", background: STATUS_COLORS[p.status] || "#6b7280",
                  }}>
                    {p.status}
                  </span>
                </div>

                <div style={{ display: "flex", gap: 16, marginTop: 12, fontSize: "0.85rem", color: "#6b7280" }}>
                  {p.vm_count != null && <span>🖥️ {p.vm_count} VMs</span>}
                  {p.tenant_count != null && <span>🏢 {p.tenant_count} tenants</span>}
                  <span>📁 {p.rvtools_filename || "No upload"}</span>
                </div>

                <div style={{ display: "flex", gap: 8, marginTop: 12, fontSize: "0.8rem" }}>
                  <span>Topology: <strong>{p.topology_type.replace(/_/g, " ")}</strong></span>
                  <span>•</span>
                  <span>Agents: <strong>{p.agent_count}</strong></span>
                </div>

                <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
                  <button onClick={e => { e.stopPropagation(); handleArchive(p.project_id, p.name); }}
                    style={btnSmall} title="Archive">📦</button>
                  <button onClick={e => { e.stopPropagation(); handleDelete(p.project_id, p.name); }}
                    style={{ ...btnSmall, color: "#dc2626" }} title="Delete">🗑️</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ---- Setup view ---- */}
      {subView === "setup" && selectedProject && (
        <ProjectSetup
          project={selectedProject}
          onProjectUpdated={(p) => { setSelectedProject(p); loadProjects(); }}
          onNavigate={(view) => setSubView(view as SubView)}
        />
      )}

      {/* ---- Analysis view ---- */}
      {subView === "analysis" && selectedProject && (
        <SourceAnalysis
          project={selectedProject}
          onProjectUpdated={(p) => { setSelectedProject(p); loadProjects(); }}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Inline styles                                                      */
/* ------------------------------------------------------------------ */

function subNavStyle(active: boolean): React.CSSProperties {
  return {
    padding: "6px 14px", borderRadius: 6, border: "1px solid",
    borderColor: active ? "#3b82f6" : "var(--border, #d1d5db)",
    background: active ? "#3b82f6" : "transparent",
    color: active ? "#fff" : "inherit",
    cursor: "pointer", fontWeight: active ? 600 : 400, fontSize: "0.85rem",
  };
}

const btnPrimary: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 6, border: "none",
  background: "#3b82f6", color: "#fff", cursor: "pointer", fontWeight: 600,
};

const btnSecondary: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 6, border: "1px solid var(--border, #d1d5db)",
  background: "transparent", cursor: "pointer",
};

const btnSmall: React.CSSProperties = {
  padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border, #d1d5db)",
  background: "transparent", cursor: "pointer", fontSize: "0.8rem",
};

const labelStyle: React.CSSProperties = {
  display: "block", marginBottom: 4, fontWeight: 600, fontSize: "0.85rem",
};

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "8px 10px", borderRadius: 6,
  border: "1px solid var(--border, #d1d5db)", fontSize: "0.9rem",
  boxSizing: "border-box",
};
