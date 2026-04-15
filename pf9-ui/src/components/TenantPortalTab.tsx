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

interface AccessRow {
  id: number;
  keystone_user_id: string;
  control_plane_id: string;
  enabled: boolean;
  mfa_required: boolean;
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [success, setSuccess] = useState<string>("");

  const clearMessages = () => { setError(""); setSuccess(""); };

  // ── Access tab ──
  const [accessRows, setAccessRows] = useState<AccessRow[]>([]);

  // ── Branding tab ──
  const [branding, setBranding] = useState<Partial<BrandingRow>>({
    company_name: "Cloud Portal",
    primary_color: "#1A73E8",
    accent_color: "#F29900",
  });

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

  const fetchBranding = useCallback(async () => {
    if (!cpId.trim()) return;
    setLoading(true); clearMessages();
    try {
      const data = await apiFetch<BrandingRow>(`/api/admin/tenant-portal/branding/${encodeURIComponent(cpId)}`);
      setBranding(data);
    } catch (e: any) {
      if (e.message?.includes("404")) {
        // No row yet — keep defaults
        setBranding({ company_name: "Cloud Portal", primary_color: "#1A73E8", accent_color: "#F29900" });
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }, [cpId]);

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
    if (subTab === "branding") fetchBranding();
    if (subTab === "sessions") fetchSessions();
    if (subTab === "audit")    fetchAudit(0);
  }, [cpId, subTab]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const handleUpsertBranding = async () => {
    if (!cpId.trim()) { setError("Enter a Control Plane ID first"); return; }
    clearMessages();
    setLoading(true);
    try {
      await apiFetch(`/api/admin/tenant-portal/branding/${encodeURIComponent(cpId)}`, {
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

      {/* CP ID input */}
      <div style={{ marginBottom: "1rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <label style={{ fontWeight: 600, whiteSpace: "nowrap" }}>Control Plane ID:</label>
        <input
          type="text"
          placeholder="e.g. pf9-prod"
          value={cpId}
          onChange={(e) => setCpId(e.target.value)}
          style={{ padding: "0.35rem 0.6rem", borderRadius: 6, border: "1px solid var(--pf9-border)", minWidth: 220 }}
        />
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
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            <button className="pf9-btn" onClick={fetchAccess} disabled={loading || !cpId.trim()}>
              {loading ? "Loading…" : "Load Access List"}
            </button>
          </div>
          {accessRows.length === 0 && !loading && (
            <p style={{ color: "var(--pf9-text-muted)" }}>
              {cpId.trim() ? "No access rows found." : "Enter a Control Plane ID and click Load."}
            </p>
          )}
          {accessRows.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table className="pf9-table">
                <thead>
                  <tr>
                    <th>Keystone User ID</th>
                    <th>Status</th>
                    <th>MFA Required</th>
                    <th>Granted By</th>
                    <th>Updated</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {accessRows.map((row) => (
                    <tr key={row.id}>
                      <td style={{ fontFamily: "monospace", fontSize: "0.8rem" }}>{row.keystone_user_id}</td>
                      <td><StatusBadge ok={row.enabled} /></td>
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
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            <button className="pf9-btn" onClick={fetchBranding} disabled={loading || !cpId.trim()}>
              Load Current Branding
            </button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem 1.25rem" }}>
            {(
              [
                { key: "company_name",   label: "Company Name",    type: "text" },
                { key: "logo_url",       label: "Logo URL",         type: "url"  },
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
              {cpId.trim() ? "No active sessions." : "Enter a Control Plane ID and click Refresh."}
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
              {cpId.trim() ? "No audit entries found." : "Enter a Control Plane ID and click Refresh."}
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
