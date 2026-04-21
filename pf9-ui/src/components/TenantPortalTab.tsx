/**
 * TenantPortalTab.tsx — Admin management tab for the Tenant Portal feature.
 *
 * Four sub-tabs:
 *   1. Access Management — grant/revoke portal access; toggle MFA requirement
 *   2. Branding           — upsert logo, colours, support links for a CP
 *   3. Active Sessions    — view and force-terminate user sessions
 *   4. Audit Log          — paginated read-only event history
 *
 * All calls go to /api/admin/tenant-portal/* and require admin/superadmin role.
 */

import React, { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ControlPlane {
  id: string;
  name: string;
}

interface Project {
  id: string;
  name: string;
  member_count: number;
  portal_enabled_count: number;
}

interface KsUser {
  keystone_user_id: string;
  name: string | null;
  email: string | null;
  enabled: boolean | null;
  mfa_required: boolean | null;
}

interface AccessRow {
  id: number;
  keystone_user_id: string;
  user_name: string | null;
  control_plane_id: string;
  tenant_name: string | null;
  enabled: boolean;
  mfa_required: boolean;
  portal_role: string;
  notes: string | null;
  granted_by: string | null;
  granted_at: string | null;
  revoked_by: string | null;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
}

interface Session {
  keystone_user_id: string;
  session_key: string;
  created_at: string | null;
}

interface AuditEntry {
  id: number;
  keystone_user_id: string;
  control_plane_id: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  project_id: string | null;
  region_id: string | null;
  ip_address: string | null;
  success: boolean;
  detail: string | null;
  created_at: string;
}

interface BrandingRow {
  control_plane_id: string;
  company_name: string;
  logo_url: string | null;
  favicon_url: string | null;
  primary_color: string;
  accent_color: string;
  support_email: string | null;
  support_url: string | null;
  welcome_message: string | null;
  footer_text: string | null;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  userRole?: string;
}

// ---------------------------------------------------------------------------
// Local helpers
// ---------------------------------------------------------------------------

function fmt(v: string | null | undefined): string {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleString();
  } catch {
    return v;
  }
}

function StatusBadge({ ok }: { ok: boolean }) {
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: 10,
        fontSize: "0.72rem",
        fontWeight: 600,
        background: ok ? "#22c55e22" : "#ef444422",
        color: ok ? "#22c55e" : "#ef4444",
        border: `1px solid ${ok ? "#22c55e66" : "#ef444466"}`,
      }}
    >
      {ok ? "Enabled" : "Revoked"}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const TenantPortalTab: React.FC<Props> = ({ userRole }) => {
  const isAdmin = userRole === "admin" || userRole === "superadmin";

  const [subTab, setSubTab] = useState<"access" | "branding" | "sessions" | "audit">("access");

  // ── Shared state ──
  const [cpId, setCpId] = useState<string>("");
  const [controlPlanes, setControlPlanes] = useState<ControlPlane[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [success, setSuccess] = useState<string>("");

  const clearMessages = () => { setError(""); setSuccess(""); };

  // ── Access tab ──
  const [accessRows, setAccessRows] = useState<AccessRow[]>([]);

  // Grant-access wizard state
  const [showGrantForm, setShowGrantForm] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [projectUsers, setProjectUsers] = useState<KsUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [selectedUserIds, setSelectedUserIds] = useState<Set<string>>(new Set());
  const [grantMfa, setGrantMfa] = useState(false);
  const [grantNotes, setGrantNotes] = useState("");
  const [grantLoading, setGrantLoading] = useState(false);

  // ── Branding tab ──
  const [branding, setBranding] = useState<Partial<BrandingRow>>({
    company_name: "Cloud Portal",
    primary_color: "#1A73E8",
    accent_color: "#F29900",
  });
  // '' = global CP-level branding; a project id = per-tenant override
  const [brandingProjectId, setBrandingProjectId] = useState<string>("");
  const [brandingProjects, setBrandingProjects] = useState<Project[]>([]);

  // ── Sessions tab ──
  const [sessions, setSessions] = useState<Session[]>([]);

  // ── Audit tab ──
  const [auditRows, setAuditRows] = useState<AuditEntry[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditOffset, setAuditOffset] = useState(0);
  const AUDIT_LIMIT = 50;

  // ---------------------------------------------------------------------------
  // Data fetchers
  // ---------------------------------------------------------------------------

  // Load control planes on mount
  useEffect(() => {
    apiFetch<ControlPlane[]>("/api/admin/tenant-portal/control-planes")
      .then((data) => {
        setControlPlanes(data);
        if (data.length === 1) setCpId(data[0].id);   // auto-select when only one exists
      })
      .catch(() => {/* silent — CP list is best-effort */});
  }, []);

  const fetchAccess = useCallback(async () => {
    if (!cpId.trim()) return;
    setLoading(true); clearMessages();
    try {
      const data = await apiFetch<AccessRow[]>(`/api/admin/tenant-portal/access/${encodeURIComponent(cpId)}`);
      setAccessRows(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [cpId]);

  const openGrantForm = async () => {
    if (!cpId.trim()) return;
    clearMessages();
    setShowGrantForm(true);
    setSelectedProject(null);
    setProjectUsers([]);
    setSelectedUserIds(new Set());
    setGrantMfa(false);
    setGrantNotes("");
    setProjectsLoading(true);
    try {
      const data = await apiFetch<Project[]>(`/api/admin/tenant-portal/projects/${encodeURIComponent(cpId)}`);
      setProjects(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setProjectsLoading(false);
    }
  };

  const selectProject = async (project: Project) => {
    setSelectedProject(project);
    setSelectedUserIds(new Set());
    setProjectUsers([]);
    setUsersLoading(true);
    try {
      const data = await apiFetch<KsUser[]>(
        `/api/admin/tenant-portal/users/${encodeURIComponent(cpId)}?project_id=${encodeURIComponent(project.id)}`
      );
      setProjectUsers(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setUsersLoading(false);
    }
  };

  const fetchBranding = useCallback(async () => {
    if (!cpId.trim()) return;
    setLoading(true); clearMessages();
    try {
      const qs = brandingProjectId ? `?project_id=${encodeURIComponent(brandingProjectId)}` : "";
      const data = await apiFetch<BrandingRow>(`/api/admin/tenant-portal/branding/${encodeURIComponent(cpId)}${qs}`);
      setBranding(data);
    } catch (e: any) {
      if (e.message?.includes("404") || e.message === "branding_not_found") {
        // No row yet — keep defaults
        setBranding({ company_name: "Cloud Portal", primary_color: "#1A73E8", accent_color: "#F29900" });
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }, [cpId, brandingProjectId]);

  const fetchSessions = useCallback(async () => {
    if (!cpId.trim()) return;
    setLoading(true); clearMessages();
    try {
      const data = await apiFetch<Session[]>(`/api/admin/tenant-portal/sessions/${encodeURIComponent(cpId)}`);
      setSessions(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [cpId]);

  const fetchAudit = useCallback(async (offset = 0) => {
    if (!cpId.trim()) return;
    setLoading(true); clearMessages();
    try {
      const data = await apiFetch<{ total: number; items: AuditEntry[] }>(
        `/api/admin/tenant-portal/audit/${encodeURIComponent(cpId)}?limit=${AUDIT_LIMIT}&offset=${offset}`
      );
      setAuditRows(data.items);
      setAuditTotal(data.total);
      setAuditOffset(offset);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [cpId]);

  // Reload when CP changes
  useEffect(() => {
    if (!cpId.trim()) return;
    if (subTab === "access")   fetchAccess();
    if (subTab === "branding") {
      // Load project list for the branding scope selector
      apiFetch<Project[]>(`/api/admin/tenant-portal/projects/${encodeURIComponent(cpId)}`)
        .then((data) => setBrandingProjects(data))
        .catch(() => setBrandingProjects([]));
      fetchBranding();
    }
    if (subTab === "sessions") fetchSessions();
    if (subTab === "audit")    fetchAudit(0);
  }, [cpId, subTab]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reload branding when the project scope selector changes
  useEffect(() => {
    if (subTab === "branding" && cpId.trim()) fetchBranding();
  }, [brandingProjectId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  const handleToggleAccess = async (row: AccessRow) => {
    clearMessages();
    try {
      await apiFetch(`/api/admin/tenant-portal/access`, {
        method: "PUT",
        body: JSON.stringify({
          keystone_user_id: row.keystone_user_id,
          control_plane_id: row.control_plane_id,
          enabled: !row.enabled,
          mfa_required: row.mfa_required,
          notes: row.notes,
        }),
      });
      setSuccess(`Access ${!row.enabled ? "enabled" : "revoked"} for ${row.keystone_user_id}`);
      await fetchAccess();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleToggleMFA = async (row: AccessRow) => {
    clearMessages();
    try {
      await apiFetch(`/api/admin/tenant-portal/access`, {
        method: "PUT",
        body: JSON.stringify({
          keystone_user_id: row.keystone_user_id,
          control_plane_id: row.control_plane_id,
          enabled: row.enabled,
          mfa_required: !row.mfa_required,
          notes: row.notes,
        }),
      });
      setSuccess(`MFA requirement ${!row.mfa_required ? "enabled" : "disabled"} for ${row.keystone_user_id}`);
      await fetchAccess();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleResetMFA = async (keystoneUserId: string) => {
    if (!window.confirm(`Reset MFA enrollment for user ${keystoneUserId}? They will need to re-enroll.`)) return;
    clearMessages();
    try {
      await apiFetch(
        `/api/admin/tenant-portal/mfa/${encodeURIComponent(cpId)}/${encodeURIComponent(keystoneUserId)}`,
        { method: "DELETE" }
      );
      setSuccess(`MFA enrollment reset for ${keystoneUserId}`);
      await fetchAccess();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleGrantAccess = async () => {
    if (!cpId.trim())                  { setError("Select a Control Plane first"); return; }
    if (!selectedProject)              { setError("Select a tenant first"); return; }
    if (selectedUserIds.size === 0)    { setError("Select at least one user"); return; }
    clearMessages();
    setGrantLoading(true);
    try {
      const users = projectUsers
        .filter((u) => selectedUserIds.has(u.keystone_user_id))
        .map((u) => ({ keystone_user_id: u.keystone_user_id, user_name: u.name || u.email || null }));

      const result = await apiFetch<{ succeeded: number; total: number }>(`/api/admin/tenant-portal/access/batch`, {
        method: "PUT",
        body: JSON.stringify({
          control_plane_id: cpId.trim(),
          tenant_name: selectedProject.name,
          users,
          enabled: true,
          mfa_required: grantMfa,
          notes: grantNotes.trim() || null,
        }),
      });
      setSuccess(`Access granted for ${result.succeeded} of ${result.total} user(s) in ${selectedProject.name}`);
      setShowGrantForm(false);
      await fetchAccess();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGrantLoading(false);
    }
  };

  const handleTogglePortalRole = async (row: AccessRow) => {
    clearMessages();
    const newRole = row.portal_role === "observer" ? "manager" : "observer";
    try {
      await apiFetch(`/api/admin/tenant-portal/access`, {
        method: "PUT",
        body: JSON.stringify({
          keystone_user_id: row.keystone_user_id,
          control_plane_id: row.control_plane_id,
          enabled: row.enabled,
          mfa_required: row.mfa_required,
          portal_role: newRole,
          notes: row.notes,
        }),
      });
      setSuccess(`Portal role changed to ${newRole} for ${row.user_name || row.keystone_user_id}`);
      await fetchAccess();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleUpsertBranding = async () => {
    if (!cpId.trim()) { setError("Enter a Control Plane ID first"); return; }
    clearMessages();
    setLoading(true);
    try {
      const qs = brandingProjectId ? `?project_id=${encodeURIComponent(brandingProjectId)}` : "";
      await apiFetch(`/api/admin/tenant-portal/branding/${encodeURIComponent(cpId)}${qs}`, {
        method: "PUT",
        body: JSON.stringify(branding),
      });
      setSuccess("Branding saved successfully");
      await fetchBranding();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleLogoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!cpId.trim()) { setError("Select a Control Plane first"); return; }
    clearMessages();
    setLoading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const qs = brandingProjectId ? `?project_id=${encodeURIComponent(brandingProjectId)}` : "";
      const result = await apiFetch<{ logo_url: string }>(
        `/api/admin/tenant-portal/branding/${encodeURIComponent(cpId)}/logo${qs}`,
        { method: "POST", body: form },
      );
      setBranding((b) => ({ ...b, logo_url: result.logo_url }));
      setSuccess("Logo uploaded successfully");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
      e.target.value = "";
    }
  };

  const handleKillSession = async (keystoneUserId: string) => {
    if (!window.confirm(`Terminate all sessions for ${keystoneUserId}?`)) return;
    clearMessages();
    try {
      await apiFetch(
        `/api/admin/tenant-portal/sessions/${encodeURIComponent(cpId)}/${encodeURIComponent(keystoneUserId)}`,
        { method: "DELETE" }
      );
      setSuccess(`Sessions terminated for ${keystoneUserId}`);
      await fetchSessions();
    } catch (e: any) {
      setError(e.message);
    }
  };

  // ---------------------------------------------------------------------------
  // Guard
  // ---------------------------------------------------------------------------

  if (!isAdmin) {
    return (
      <div style={{ padding: "2rem", color: "var(--pf9-text-muted)" }}>
        Admin or superadmin role required to manage Tenant Portal settings.
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const subTabs = [
    { key: "access",   label: "Access Management" },
    { key: "branding", label: "Branding" },
    { key: "sessions", label: "Active Sessions" },
    { key: "audit",    label: "Audit Log" },
  ] as const;

  return (
    <div className="pf9-tab-content" style={{ padding: "1rem" }}>
      <h2 style={{ marginBottom: "0.75rem" }}>Tenant Portal Management</h2>

      {/* CP selector */}
      <div style={{ marginBottom: "1rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <label style={{ fontWeight: 600, whiteSpace: "nowrap" }}>Control Plane:</label>
        {controlPlanes.length > 0 ? (
          <select
            value={cpId}
            onChange={(e) => setCpId(e.target.value)}
            style={{ padding: "0.35rem 0.6rem", borderRadius: 6, border: "1px solid var(--pf9-border)", minWidth: 220 }}
          >
            {controlPlanes.length > 1 && <option value="">— select —</option>}
            {controlPlanes.map((cp) => (
              <option key={cp.id} value={cp.id}>{cp.name} ({cp.id})</option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            placeholder="e.g. default"
            value={cpId}
            onChange={(e) => setCpId(e.target.value)}
            style={{ padding: "0.35rem 0.6rem", borderRadius: 6, border: "1px solid var(--pf9-border)", minWidth: 220 }}
          />
        )}
      </div>

      {/* Sub-tab bar */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", borderBottom: "2px solid var(--pf9-border)", paddingBottom: "0.4rem" }}>
        {subTabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setSubTab(t.key)}
            className={subTab === t.key ? "pf9-tab pf9-tab-active" : "pf9-tab"}
            style={{ fontSize: "0.85rem" }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Messages */}
      {error   && <div className="pf9-error-banner"   style={{ marginBottom: "0.75rem" }}>{error}</div>}
      {success && <div className="pf9-success-banner" style={{ marginBottom: "0.75rem" }}>{success}</div>}

      {/* ── ACCESS TAB ── */}
      {subTab === "access" && (
        <div>
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
            <button className="pf9-btn" onClick={fetchAccess} disabled={loading || !cpId.trim()}>
              {loading ? "Loading…" : "Load Access List"}
            </button>
            <button
              className="pf9-btn"
              style={{ background: "#2563eb", color: "#fff", opacity: cpId.trim() ? 1 : 0.45, cursor: cpId.trim() ? "pointer" : "not-allowed" }}
              onClick={() => { if (!cpId.trim()) return; showGrantForm ? setShowGrantForm(false) : openGrantForm(); }}
            >
              {showGrantForm ? "✕ Cancel" : "+ Grant Access"}
            </button>
          </div>

          {/* ── Grant-access wizard ── */}
          {showGrantForm && (
            <div style={{ border: "1px solid var(--pf9-border)", borderRadius: 8, padding: "1.25rem", marginBottom: "1.25rem", maxWidth: 720, background: "var(--pf9-surface-2, #f9fafb)" }}>
              <h4 style={{ margin: "0 0 1rem" }}>Grant Portal Access</h4>

              {/* Step 1: Pick tenant */}
              <div style={{ marginBottom: "1rem" }}>
                <div style={{ fontWeight: 600, fontSize: "0.85rem", marginBottom: "0.4rem" }}>
                  Step 1 — Select a tenant / organisation
                </div>
                {projectsLoading ? (
                  <p style={{ color: "var(--pf9-text-muted)", fontSize: "0.85rem" }}>Loading tenants…</p>
                ) : projects.length === 0 ? (
                  <p style={{ color: "var(--pf9-text-muted)", fontSize: "0.85rem" }}>No tenants found for this control plane.</p>
                ) : (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                    {projects.map((p) => (
                      <button
                        key={p.id}
                        onClick={() => selectProject(p)}
                        style={{
                          padding: "0.35rem 0.75rem",
                          borderRadius: 20,
                          border: `2px solid ${selectedProject?.id === p.id ? "#2563eb" : "var(--pf9-border)"}`,
                          background: selectedProject?.id === p.id ? "#2563eb" : "transparent",
                          color: selectedProject?.id === p.id ? "#fff" : "inherit",
                          cursor: "pointer",
                          fontSize: "0.85rem",
                          fontWeight: 500,
                        }}
                      >
                        {p.name}
                        <span style={{ marginLeft: "0.4rem", opacity: 0.7, fontSize: "0.75rem" }}>
                          {p.portal_enabled_count}/{p.member_count} enabled
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Step 2: Pick users */}
              {selectedProject && (
                <div style={{ marginBottom: "1rem" }}>
                  <div style={{ fontWeight: 600, fontSize: "0.85rem", marginBottom: "0.4rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>Step 2 — Select users from <em>{selectedProject.name}</em></span>
                    {projectUsers.length > 0 && (
                      <button
                        style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem", cursor: "pointer", borderRadius: 4, border: "1px solid var(--pf9-border)" }}
                        onClick={() => {
                          if (selectedUserIds.size === projectUsers.length) {
                            setSelectedUserIds(new Set());
                          } else {
                            setSelectedUserIds(new Set(projectUsers.map((u) => u.keystone_user_id)));
                          }
                        }}
                      >
                        {selectedUserIds.size === projectUsers.length ? "Deselect all" : "Select all"}
                      </button>
                    )}
                  </div>
                  {usersLoading ? (
                    <p style={{ color: "var(--pf9-text-muted)", fontSize: "0.85rem" }}>Loading users…</p>
                  ) : projectUsers.length === 0 ? (
                    <p style={{ color: "var(--pf9-text-muted)", fontSize: "0.85rem" }}>No users found in this tenant.</p>
                  ) : (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.4rem" }}>
                      {projectUsers.map((u) => {
                        const checked = selectedUserIds.has(u.keystone_user_id);
                        return (
                          <label
                            key={u.keystone_user_id}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: "0.5rem",
                              padding: "0.4rem 0.6rem",
                              borderRadius: 6,
                              border: `1px solid ${checked ? "#2563eb" : "var(--pf9-border)"}`,
                              background: checked ? "#2563eb11" : "transparent",
                              cursor: "pointer",
                              fontSize: "0.85rem",
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => {
                                setSelectedUserIds((prev) => {
                                  const next = new Set(prev);
                                  if (checked) next.delete(u.keystone_user_id);
                                  else next.add(u.keystone_user_id);
                                  return next;
                                });
                              }}
                            />
                            <span>
                              <div style={{ fontWeight: 600 }}>{u.name || u.email || "Unknown"}</div>
                              {u.email && u.name && <div style={{ fontSize: "0.75rem", opacity: 0.65 }}>{u.email}</div>}
                              {u.enabled !== null && u.enabled === false && (
                                <span style={{ fontSize: "0.7rem", color: "#ef4444" }}>portal access revoked</span>
                              )}
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Step 3: Options */}
              {selectedProject && projectUsers.length > 0 && (
                <div style={{ marginBottom: "1rem", display: "flex", gap: "1.5rem", alignItems: "flex-start", flexWrap: "wrap" }}>
                  <div style={{ fontWeight: 600, fontSize: "0.85rem", width: "100%", marginBottom: "0.2rem" }}>Step 3 — Options</div>
                  <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.85rem", cursor: "pointer" }}>
                    <input type="checkbox" checked={grantMfa} onChange={(e) => setGrantMfa(e.target.checked)} />
                    <span>Require MFA for selected users</span>
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.85rem", flexGrow: 1, maxWidth: 300 }}>
                    <span>Internal note (optional)</span>
                    <input
                      type="text"
                      placeholder="e.g. Requested by ticket #123"
                      value={grantNotes}
                      onChange={(e) => setGrantNotes(e.target.value)}
                      style={{ padding: "0.35rem 0.6rem", borderRadius: 6, border: "1px solid var(--pf9-border)" }}
                    />
                  </label>
                </div>
              )}

              {/* Actions */}
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button
                  className="pf9-btn"
                  style={{ background: "#2563eb", color: "#fff", opacity: (!selectedProject || selectedUserIds.size === 0 || grantLoading) ? 0.45 : 1 }}
                  onClick={handleGrantAccess}
                  disabled={!selectedProject || selectedUserIds.size === 0 || grantLoading}
                >
                  {grantLoading ? "Granting…" : `Grant Access${selectedUserIds.size > 0 ? ` (${selectedUserIds.size} user${selectedUserIds.size > 1 ? "s" : ""})` : ""}`}
                </button>
                <button className="pf9-btn" onClick={() => setShowGrantForm(false)}>Cancel</button>
              </div>
            </div>
          )}

          {accessRows.length === 0 && !loading && (
            <p style={{ color: "var(--pf9-text-muted)" }}>
              {cpId.trim() ? "No access rows found." : "Select a Control Plane above and click Load."}
            </p>
          )}
          {accessRows.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table className="pf9-table">
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Tenant / Org</th>
                    <th>Status</th>
                    <th>Role</th>
                    <th>MFA Required</th>
                    <th>Granted By</th>
                    <th>Updated</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {accessRows.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.user_name && (
                          <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>{row.user_name}</div>
                        )}
                        <div style={{ fontFamily: "monospace", fontSize: "0.75rem", color: "var(--pf9-text-muted)" }}>
                          {row.keystone_user_id}
                        </div>
                      </td>
                      <td>{row.tenant_name ?? <span style={{ color: "var(--pf9-text-muted)" }}>{row.control_plane_id}</span>}</td>
                      <td><StatusBadge ok={row.enabled} /></td>
                      <td>
                        <span style={{
                          padding: "0.15rem 0.5rem", borderRadius: 10, fontSize: "0.75rem", fontWeight: 600,
                          background: row.portal_role === "observer" ? "#fef9c3" : "#dcfce7",
                          color: row.portal_role === "observer" ? "#854d0e" : "#166534",
                          border: `1px solid ${row.portal_role === "observer" ? "#fde68a" : "#86efac"}`
                        }}>
                          {row.portal_role || "manager"}
                        </span>
                      </td>
                      <td>{row.mfa_required ? "✅ Yes" : "—"}</td>
                      <td>{row.granted_by ?? "—"}</td>
                      <td style={{ fontSize: "0.8rem" }}>{fmt(row.updated_at)}</td>
                      <td>
                        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                          <button
                            className="pf9-btn pf9-btn-sm"
                            onClick={() => handleToggleAccess(row)}
                            title={row.enabled ? "Revoke access" : "Grant access"}
                          >
                            {row.enabled ? "Revoke" : "Enable"}
                          </button>
                          <button
                            className="pf9-btn pf9-btn-sm"
                            onClick={() => handleTogglePortalRole(row)}
                            title={row.portal_role === "observer" ? "Promote to Manager" : "Demote to Observer"}
                          >
                            {row.portal_role === "observer" ? "→ Manager" : "→ Observer"}
                          </button>
                          <button
                            className="pf9-btn pf9-btn-sm"
                            onClick={() => handleToggleMFA(row)}
                            title={row.mfa_required ? "Disable MFA requirement" : "Enable MFA requirement"}
                          >
                            {row.mfa_required ? "Disable MFA" : "Require MFA"}
                          </button>
                          <button
                            className="pf9-btn pf9-btn-sm pf9-btn-danger"
                            onClick={() => handleResetMFA(row.keystone_user_id)}
                            title="Delete MFA enrollment — user must re-enroll"
                          >
                            Reset MFA
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── BRANDING TAB ── */}
      {subTab === "branding" && (
        <div style={{ maxWidth: 620 }}>
          {/* Tenant scope selector */}
          <div style={{ marginBottom: "1rem" }}>
            <label style={{ fontWeight: 600, fontSize: "0.85rem", display: "block", marginBottom: "0.35rem" }}>
              Branding scope — applies to:
            </label>
            <select
              value={brandingProjectId}
              onChange={(e) => { setBrandingProjectId(e.target.value); }}
              style={{ padding: "0.35rem 0.6rem", borderRadius: 6, border: "1px solid var(--pf9-border)", minWidth: 280 }}
            >
              <option value="">🌐 Global (all tenants — default)</option>
              {brandingProjects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <span style={{ marginLeft: "0.75rem", fontSize: "0.78rem", color: "var(--pf9-text-muted)" }}>
              {brandingProjectId
                ? "Per-tenant override — displayed only for this org"
                : "Shown to all tenants unless a per-tenant override exists"}
            </span>
          </div>

          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            <button className="pf9-btn" onClick={fetchBranding} disabled={loading || !cpId.trim()}>
              Load Current Branding
            </button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem 1.25rem" }}>
            {(
              [
                { key: "company_name",   label: "Company Name",    type: "text" },
                { key: "favicon_url",    label: "Favicon URL",      type: "url"  },
                { key: "primary_color",  label: "Primary Colour",   type: "text", placeholder: "#1A73E8" },
                { key: "accent_color",   label: "Accent Colour",    type: "text", placeholder: "#F29900" },
                { key: "support_email",  label: "Support Email",    type: "email" },
                { key: "support_url",    label: "Support URL",      type: "url"  },
              ] as { key: keyof BrandingRow; label: string; type: string; placeholder?: string }[]
            ).map(({ key, label, type, placeholder }) => (
              <label key={key} style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.85rem" }}>
                <span style={{ fontWeight: 600 }}>{label}</span>
                <input
                  type={type}
                  placeholder={placeholder ?? ""}
                  value={(branding[key] as string) ?? ""}
                  onChange={(e) => setBranding((b) => ({ ...b, [key]: e.target.value || null }))}
                  style={{ padding: "0.35rem 0.6rem", borderRadius: 6, border: "1px solid var(--pf9-border)" }}
                />
              </label>
            ))}
          </div>

          {/* ── Company Logo — URL field + upload button + preview ── */}
          <div style={{ marginTop: "0.75rem", fontSize: "0.85rem" }}>
            <span style={{ fontWeight: 600, display: "block", marginBottom: 4 }}>Company Logo</span>
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
              <input
                type="url"
                placeholder="https://example.com/logo.png"
                value={branding.logo_url ?? ""}
                onChange={(e) => setBranding((b) => ({ ...b, logo_url: e.target.value || null }))}
                style={{ flex: 1, minWidth: 220, padding: "0.35rem 0.6rem", borderRadius: 6, border: "1px solid var(--pf9-border)" }}
              />
              <label
                style={{
                  cursor: loading ? "not-allowed" : "pointer",
                  padding: "0.35rem 0.75rem",
                  borderRadius: 6,
                  background: "var(--pf9-accent, #1A73E8)",
                  color: "#fff",
                  fontSize: "0.82rem",
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                  opacity: loading ? 0.6 : 1,
                }}
              >
                Upload Image
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                  style={{ display: "none" }}
                  disabled={loading || !cpId.trim()}
                  onChange={handleLogoUpload}
                />
              </label>
            </div>
            {branding.logo_url && (
              <div style={{ marginTop: "0.5rem" }}>
                <img
                  src={branding.logo_url}
                  alt="Logo preview"
                  style={{ maxHeight: 56, maxWidth: 240, objectFit: "contain", border: "1px solid var(--pf9-border)", borderRadius: 4, background: "#fff", padding: 4 }}
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
              </div>
            )}
            <span style={{ fontSize: "0.75rem", color: "var(--pf9-text-muted)" }}>
              PNG, JPEG, GIF, WebP or SVG · max 512 KB · each tenant org can have its own logo
            </span>
          </div>

          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.85rem", marginTop: "0.75rem" }}>
            <span style={{ fontWeight: 600 }}>Welcome Message</span>
            <textarea
              rows={3}
              value={branding.welcome_message ?? ""}
              onChange={(e) => setBranding((b) => ({ ...b, welcome_message: e.target.value || null }))}
              style={{ padding: "0.35rem 0.6rem", borderRadius: 6, border: "1px solid var(--pf9-border)", resize: "vertical" }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.85rem", marginTop: "0.75rem" }}>
            <span style={{ fontWeight: 600 }}>Footer Text</span>
            <textarea
              rows={2}
              value={branding.footer_text ?? ""}
              onChange={(e) => setBranding((b) => ({ ...b, footer_text: e.target.value || null }))}
              style={{ padding: "0.35rem 0.6rem", borderRadius: 6, border: "1px solid var(--pf9-border)", resize: "vertical" }}
            />
          </label>

          <button
            className="pf9-btn"
            style={{ marginTop: "1rem" }}
            onClick={handleUpsertBranding}
            disabled={loading || !cpId.trim()}
          >
            {loading ? "Saving…" : "Save Branding"}
          </button>
        </div>
      )}

      {/* ── SESSIONS TAB ── */}
      {subTab === "sessions" && (
        <div>
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            <button className="pf9-btn" onClick={fetchSessions} disabled={loading || !cpId.trim()}>
              {loading ? "Loading…" : "Refresh Sessions"}
            </button>
          </div>
          {sessions.length === 0 && !loading && (
            <p style={{ color: "var(--pf9-text-muted)" }}>
              {cpId.trim() ? "No active sessions." : "Select a Control Plane above and click Refresh."}
            </p>
          )}
          {sessions.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table className="pf9-table">
                <thead>
                  <tr>
                    <th>Keystone User ID</th>
                    <th>Session Key (prefix)</th>
                    <th>Created At</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s, idx) => (
                    <tr key={idx}>
                      <td style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>{s.keystone_user_id}</td>
                      <td style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>
                        {s.session_key ? s.session_key.slice(0, 12) + "…" : "—"}
                      </td>
                      <td style={{ fontSize: "0.8rem" }}>{fmt(s.created_at)}</td>
                      <td>
                        <button
                          className="pf9-btn pf9-btn-sm pf9-btn-danger"
                          onClick={() => handleKillSession(s.keystone_user_id)}
                          title="Force-terminate all sessions for this user"
                        >
                          Kill Session
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── AUDIT TAB ── */}
      {subTab === "audit" && (
        <div>
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            <button className="pf9-btn" onClick={() => fetchAudit(0)} disabled={loading || !cpId.trim()}>
              {loading ? "Loading…" : "Refresh Audit Log"}
            </button>
          </div>
          {auditRows.length === 0 && !loading && (
            <p style={{ color: "var(--pf9-text-muted)" }}>
              {cpId.trim() ? "No audit entries found." : "Select a Control Plane above and click Refresh."}
            </p>
          )}
          {auditRows.length > 0 && (
            <>
              <p style={{ fontSize: "0.8rem", color: "var(--pf9-text-muted)", marginBottom: "0.5rem" }}>
                Showing {auditOffset + 1}–{Math.min(auditOffset + auditRows.length, auditTotal)} of {auditTotal} entries
              </p>
              <div style={{ overflowX: "auto" }}>
                <table className="pf9-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>User</th>
                      <th>Action</th>
                      <th>Resource</th>
                      <th>OK</th>
                      <th>IP</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditRows.map((e) => (
                      <tr key={e.id}>
                        <td style={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>{fmt(e.created_at)}</td>
                        <td style={{ fontFamily: "monospace", fontSize: "0.76rem" }}>{e.keystone_user_id}</td>
                        <td style={{ fontSize: "0.82rem" }}>{e.action}</td>
                        <td style={{ fontSize: "0.8rem" }}>
                          {[e.resource_type, e.resource_id].filter(Boolean).join(" / ") || "—"}
                        </td>
                        <td>{e.success ? "✅" : "❌"}</td>
                        <td style={{ fontFamily: "monospace", fontSize: "0.78rem" }}>{e.ip_address ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
                <button
                  className="pf9-btn pf9-btn-sm"
                  disabled={auditOffset === 0 || loading}
                  onClick={() => fetchAudit(Math.max(0, auditOffset - AUDIT_LIMIT))}
                >
                  ← Previous
                </button>
                <button
                  className="pf9-btn pf9-btn-sm"
                  disabled={auditOffset + AUDIT_LIMIT >= auditTotal || loading}
                  onClick={() => fetchAudit(auditOffset + AUDIT_LIMIT)}
                >
                  Next →
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default TenantPortalTab;
