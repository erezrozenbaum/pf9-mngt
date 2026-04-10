/**
 * ClusterManagement.tsx — Admin panel for managing Platform9 control planes and regions.
 *
 * Superadmin-only. Surfaces the full CRUD backed by cluster_routes.py:
 *   - List / add / edit / delete control planes
 *   - Test connection → discover regions from Keystone catalog
 *   - Register / enable-disable / set-default / trigger-sync regions
 *   - View per-region sync status history
 *
 * All API calls require the superadmin role (enforced on the backend too).
 */

import React, { useCallback, useEffect, useState } from "react";
import { apiFetch } from '../lib/api';
import { useClusterContext } from "./ClusterContext";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ControlPlane {
  id: string;
  name: string;
  auth_url: string;
  username: string;
  user_domain?: string;
  project_name?: string;
  project_domain?: string;
  login_url?: string | null;
  display_color?: string | null;
  is_enabled?: boolean;
  is_default?: boolean;
  region_count?: number;
  created_at?: string;
}

interface Region {
  id: string;
  control_plane_id: string;
  region_name: string;
  display_name: string;
  is_default?: boolean;
  is_enabled?: boolean;
  health_status?: string | null;
  priority?: number;
  sync_interval_minutes?: number;
  latency_threshold_ms?: number;
  last_sync_at?: string | null;
}

interface DiscoveredRegion {
  region_name: string;
  services: string[];
  nova_endpoint?: string;
  neutron_endpoint?: string;
}

interface TestResult {
  connected: boolean;
  keystone_version?: string;
  discovered_regions?: DiscoveredRegion[];
  already_registered?: string[];
  error?: string | null;
}

interface SyncStatus {
  region_id: string;
  recent: {
    id: number;
    sync_type: string;
    started_at: string;
    finished_at?: string;
    duration_ms?: number;
    resource_count?: number;
    error_count?: number;
    status: string;
  }[];
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------
// Health badge
// ---------------------------------------------------------------------------

function HealthBadge({ status }: { status?: string | null }) {
  const map: Record<string, { label: string; color: string }> = {
    healthy: { label: "Healthy", color: "#22c55e" },
    degraded: { label: "Degraded", color: "#f59e0b" },
    unreachable: { label: "Unreachable", color: "#ef4444" },
    auth_failed: { label: "Auth Failed", color: "#ef4444" },
    unknown: { label: "Unknown", color: "#6b7280" },
  };
  const s = status ?? "unknown";
  const { label, color } = map[s] ?? map.unknown;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: "10px",
        fontSize: "0.73rem",
        fontWeight: 600,
        background: `${color}22`,
        color,
        border: `1px solid ${color}66`,
      }}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

function fmt(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString();
}

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  userRole?: string;
}

export default function ClusterManagement({ userRole }: Props) {
  const { reload: reloadContext } = useClusterContext();

  // Guard — backend enforces this too
  if (userRole !== "superadmin") {
    return (
      <div style={{ padding: "40px", textAlign: "center", color: "#e57373" }}>
        <h3>Access Denied</h3>
        <p>This page requires the superadmin role.</p>
      </div>
    );
  }

  return <ClusterManagementInner reloadContext={reloadContext} />;
}

// Inner component — only renders when superadmin is confirmed
function ClusterManagementInner({
  reloadContext,
}: {
  reloadContext: () => void;
}) {
  const [controlPlanes, setControlPlanes] = useState<ControlPlane[]>([]);
  const [expandedCpId, setExpandedCpId] = useState<string | null>(null);
  const [cpRegions, setCpRegions] = useState<Record<string, Region[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Add Control Plane form
  const [showAddCp, setShowAddCp] = useState(false);
  const [cpForm, setCpForm] = useState({
    id: "",
    name: "",
    auth_url: "",
    username: "",
    password: "",
    user_domain: "Default",
    project_name: "service",
    project_domain: "Default",
    login_url: "",
    display_color: "#6366f1",
  });
  const [savingCp, setSavingCp] = useState(false);

  // Test connection
  const [testResult, setTestResult] = useState<Record<string, TestResult>>({});
  const [testing, setTesting] = useState<string | null>(null);

  // Add Region form (cpId → form data)
  const [showAddRegion, setShowAddRegion] = useState<string | null>(null);
  const [regionForm, setRegionForm] = useState({
    region_name: "",
    display_name: "",
    sync_interval_minutes: 30,
    priority: 100,
    is_default: false,
  });
  const [savingRegion, setSavingRegion] = useState(false);

  // Sync status
  const [syncStatus, setSyncStatus] = useState<Record<string, SyncStatus>>({});
  const [showSync, setShowSync] = useState<string | null>(null);

  // Auto-clear messages
  useEffect(() => {
    if (success) {
      const t = setTimeout(() => setSuccess(""), 5000);
      return () => clearTimeout(t);
    }
  }, [success]);
  useEffect(() => {
    if (error) {
      const t = setTimeout(() => setError(""), 8000);
      return () => clearTimeout(t);
    }
  }, [error]);

  // ---------------------------------------------------------------------------
  // Load
  // ---------------------------------------------------------------------------

  const loadControlPlanes = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch<ControlPlane[]>("/admin/control-planes");
      setControlPlanes(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRegions = useCallback(async (cpId: string) => {
    try {
      const data = await apiFetch<Region[]>(
        `/admin/control-planes/${encodeURIComponent(cpId)}/regions`
      );
      setCpRegions((prev) => ({ ...prev, [cpId]: data }));
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    loadControlPlanes();
  }, [loadControlPlanes]);

  // Auto-load regions for expanded CP
  useEffect(() => {
    if (expandedCpId) {
      loadRegions(expandedCpId);
    }
  }, [expandedCpId, loadRegions]);

  // ---------------------------------------------------------------------------
  // Control Plane actions
  // ---------------------------------------------------------------------------

  const handleAddCp = async () => {
    if (!cpForm.id || !cpForm.name || !cpForm.auth_url || !cpForm.username || !cpForm.password) {
      setError("ID, Name, Auth URL, Username, and Password are required.");
      return;
    }
    setSavingCp(true);
    setError("");
    try {
      await apiFetch("/admin/control-planes", {
        method: "POST",
        body: JSON.stringify({
          ...cpForm,
          login_url: cpForm.login_url || null,
          tags: {},
        }),
      });
      setSuccess(`Control plane '${cpForm.name}' added.`);
      setShowAddCp(false);
      setCpForm({
        id: "", name: "", auth_url: "", username: "", password: "",
        user_domain: "Default", project_name: "service", project_domain: "Default",
        login_url: "", display_color: "#6366f1",
      });
      await loadControlPlanes();
      reloadContext();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSavingCp(false);
    }
  };

  const handleDeleteCp = async (cp: ControlPlane) => {
    if (!confirm(`Delete control plane '${cp.name}'? All associated regions must be removed first.`)) return;
    setError("");
    try {
      await apiFetch(`/admin/control-planes/${encodeURIComponent(cp.id)}`, { method: "DELETE" });
      setSuccess(`Control plane '${cp.name}' deleted.`);
      setExpandedCpId(null);
      await loadControlPlanes();
      reloadContext();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleTestCp = async (cpId: string) => {
    setTesting(cpId);
    try {
      const result = await apiFetch<TestResult>(
        `/admin/control-planes/${encodeURIComponent(cpId)}/test`,
        { method: "POST", body: "null" }
      );
      setTestResult((prev) => ({ ...prev, [cpId]: result }));
    } catch (e: any) {
      setTestResult((prev) => ({
        ...prev,
        [cpId]: { connected: false, error: e.message },
      }));
    } finally {
      setTesting(null);
    }
  };

  // ---------------------------------------------------------------------------
  // Region actions
  // ---------------------------------------------------------------------------

  const handleAddRegion = async (cpId: string) => {
    if (!regionForm.region_name || !regionForm.display_name) {
      setError("Region name and display name are required.");
      return;
    }
    setSavingRegion(true);
    setError("");
    try {
      await apiFetch(`/admin/control-planes/${encodeURIComponent(cpId)}/regions`, {
        method: "POST",
        body: JSON.stringify(regionForm),
      });
      setSuccess(`Region '${regionForm.display_name}' registered.`);
      setShowAddRegion(null);
      setRegionForm({ region_name: "", display_name: "", sync_interval_minutes: 30, priority: 100, is_default: false });
      await loadRegions(cpId);
      reloadContext();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSavingRegion(false);
    }
  };

  const handleToggleRegion = async (cpId: string, region: Region) => {
    setError("");
    try {
      await apiFetch(
        `/admin/control-planes/${encodeURIComponent(cpId)}/regions/${encodeURIComponent(region.id)}/enable`,
        { method: "PUT", body: JSON.stringify({ is_enabled: !region.is_enabled }) }
      );
      setSuccess(`Region '${region.display_name}' ${region.is_enabled ? "disabled" : "enabled"}.`);
      await loadRegions(cpId);
      reloadContext();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleSetDefault = async (cpId: string, region: Region) => {
    if (region.is_default) return;
    setError("");
    try {
      await apiFetch(
        `/admin/control-planes/${encodeURIComponent(cpId)}/regions/${encodeURIComponent(region.id)}/set-default`,
        { method: "POST", body: "null" }
      );
      setSuccess(`Region '${region.display_name}' set as default.`);
      await loadRegions(cpId);
      reloadContext();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleTriggerSync = async (cpId: string, region: Region) => {
    setError("");
    try {
      await apiFetch(
        `/admin/control-planes/${encodeURIComponent(cpId)}/regions/${encodeURIComponent(region.id)}/sync`,
        { method: "POST", body: "null" }
      );
      setSuccess(`Sync triggered for '${region.display_name}'.`);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleViewSync = async (cpId: string, region: Region) => {
    const key = `${cpId}:${region.id}`;
    if (showSync === key) { setShowSync(null); return; }
    try {
      const data = await apiFetch<SyncStatus>(
        `/admin/control-planes/${encodeURIComponent(cpId)}/regions/${encodeURIComponent(region.id)}/sync-status`
      );
      setSyncStatus((prev) => ({ ...prev, [key]: data }));
      setShowSync(key);
    } catch (e: any) {
      setError(e.message);
    }
  };

  // ---------------------------------------------------------------------------
  // Pre-fill region form from discovered region
  // ---------------------------------------------------------------------------

  const prefillRegionFromDiscovery = (dr: DiscoveredRegion) => {
    setRegionForm({
      region_name: dr.region_name,
      display_name: dr.region_name,
      sync_interval_minutes: 30,
      priority: 100,
      is_default: false,
    });
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const panelStyle: React.CSSProperties = {
    background: "var(--color-surface, #1e1e2e)",
    border: "1px solid var(--color-border, #333)",
    borderRadius: "10px",
    padding: "20px",
    marginBottom: "16px",
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "7px 10px",
    borderRadius: "6px",
    border: "1px solid var(--color-border, #444)",
    background: "var(--color-input, #2a2a3e)",
    color: "var(--color-text, #e0e0e0)",
    fontSize: "0.88rem",
    boxSizing: "border-box",
  };

  const btnStyle: React.CSSProperties = {
    padding: "6px 14px",
    borderRadius: "6px",
    border: "none",
    cursor: "pointer",
    fontSize: "0.85rem",
    fontWeight: 600,
  };

  return (
    <div style={{ maxWidth: "1100px", margin: "0 auto", padding: "24px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "20px" }}>
        <h2 style={{ margin: 0, fontSize: "1.3rem" }}>🌐 Cluster Management</h2>
        <span style={{ fontSize: "0.8rem", color: "#6b7280" }}>Superadmin only</span>
        <button
          style={{ ...btnStyle, background: "#6366f1", color: "white", marginLeft: "auto" }}
          onClick={loadControlPlanes}
        >
          ↻ Refresh
        </button>
        <button
          style={{ ...btnStyle, background: "#22c55e", color: "white" }}
          onClick={() => setShowAddCp((v) => !v)}
        >
          {showAddCp ? "✕ Cancel" : "+ Add Control Plane"}
        </button>
      </div>

      {error && (
        <div style={{ background: "#7f1d1d", color: "#fca5a5", padding: "10px 14px", borderRadius: "6px", marginBottom: "12px", fontSize: "0.88rem" }}>
          ⚠ {error}
        </div>
      )}
      {success && (
        <div style={{ background: "#14532d", color: "#86efac", padding: "10px 14px", borderRadius: "6px", marginBottom: "12px", fontSize: "0.88rem" }}>
          ✓ {success}
        </div>
      )}

      {/* ── Add Control Plane Form ── */}
      {showAddCp && (
        <div style={{ ...panelStyle, border: "1px solid #6366f1" }}>
          <h3 style={{ margin: "0 0 16px", fontSize: "1rem" }}>➕ New Control Plane</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
            {[
              { label: "ID (slug, e.g. corp-pf9)", key: "id" },
              { label: "Display Name", key: "name" },
              { label: "Auth URL (Keystone)", key: "auth_url" },
              { label: "Username", key: "username" },
              { label: "Password", key: "password", type: "password" },
              { label: "User Domain", key: "user_domain" },
              { label: "Project Name", key: "project_name" },
              { label: "Project Domain", key: "project_domain" },
              { label: "Login URL (optional)", key: "login_url" },
            ].map(({ label, key, type }) => (
              <label key={key} style={{ fontSize: "0.83rem", color: "var(--color-text-secondary, #aaa)" }}>
                {label}
                <input
                  type={type || "text"}
                  style={{ ...inputStyle, marginTop: "4px" }}
                  value={(cpForm as any)[key] ?? ""}
                  onChange={(e) => setCpForm((f) => ({ ...f, [key]: e.target.value }))}
                />
              </label>
            ))}
            <label style={{ fontSize: "0.83rem", color: "var(--color-text-secondary, #aaa)" }}>
              Color (hex)
              <div style={{ display: "flex", gap: "8px", marginTop: "4px", alignItems: "center" }}>
                <input type="color" value={cpForm.display_color} onChange={(e) => setCpForm((f) => ({ ...f, display_color: e.target.value }))} style={{ width: "40px", height: "32px", padding: "2px", borderRadius: "4px", border: "none", cursor: "pointer" }} />
                <input type="text" style={{ ...inputStyle, flex: 1 }} value={cpForm.display_color} onChange={(e) => setCpForm((f) => ({ ...f, display_color: e.target.value }))} />
              </div>
            </label>
          </div>
          <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
            <button
              style={{ ...btnStyle, background: "#22c55e", color: "white" }}
              onClick={handleAddCp}
              disabled={savingCp}
            >
              {savingCp ? "Saving…" : "💾 Save Control Plane"}
            </button>
            <button style={{ ...btnStyle, background: "#374151", color: "#e0e0e0" }} onClick={() => setShowAddCp(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ── Control Planes List ── */}
      {loading ? (
        <div style={{ color: "#6b7280", padding: "24px 0" }}>Loading…</div>
      ) : controlPlanes.length === 0 ? (
        <div style={{ ...panelStyle, color: "#6b7280", textAlign: "center", padding: "40px" }}>
          No control planes configured. Click <strong>+ Add Control Plane</strong> to get started.
        </div>
      ) : (
        controlPlanes.map((cp) => (
          <div key={cp.id} style={panelStyle}>
            {/* CP header */}
            <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "8px" }}>
              <span
                style={{
                  display: "inline-block",
                  width: "12px",
                  height: "12px",
                  borderRadius: "50%",
                  background: cp.display_color ?? "#6366f1",
                  flexShrink: 0,
                }}
              />
              <strong style={{ fontSize: "1rem" }}>{cp.name}</strong>
              <span style={{ fontSize: "0.78rem", color: "#6b7280" }}>({cp.id})</span>
              {cp.is_default && (
                <span style={{ fontSize: "0.72rem", background: "#1d4ed8", color: "#bfdbfe", padding: "1px 7px", borderRadius: "8px" }}>default</span>
              )}
              {!cp.is_enabled && (
                <span style={{ fontSize: "0.72rem", background: "#374151", color: "#9ca3af", padding: "1px 7px", borderRadius: "8px" }}>disabled</span>
              )}
              <span style={{ fontSize: "0.8rem", color: "#6b7280", marginLeft: "4px" }}>
                {cp.region_count ?? 0} region{cp.region_count !== 1 ? "s" : ""}
              </span>
              <div style={{ marginLeft: "auto", display: "flex", gap: "8px" }}>
                <button
                  style={{ ...btnStyle, background: testing === cp.id ? "#374151" : "#0891b2", color: "white", fontSize: "0.8rem", padding: "4px 10px" }}
                  onClick={() => handleTestCp(cp.id)}
                  disabled={testing === cp.id}
                  title="Test Keystone connection"
                >
                  {testing === cp.id ? "Testing…" : "🔌 Test"}
                </button>
                <button
                  style={{ ...btnStyle, background: expandedCpId === cp.id ? "#4b5563" : "#374151", color: "#e0e0e0", fontSize: "0.8rem", padding: "4px 10px" }}
                  onClick={() => setExpandedCpId((v) => (v === cp.id ? null : cp.id))}
                >
                  {expandedCpId === cp.id ? "▲ Hide Regions" : "▼ Regions"}
                </button>
                <button
                  style={{ ...btnStyle, background: "#7f1d1d", color: "#fca5a5", fontSize: "0.8rem", padding: "4px 10px" }}
                  onClick={() => handleDeleteCp(cp)}
                  title="Delete (must remove all regions first)"
                >
                  🗑
                </button>
              </div>
            </div>
            <div style={{ fontSize: "0.8rem", color: "#6b7280" }}>
              Auth URL: <code style={{ background: "rgba(255,255,255,0.05)", padding: "1px 5px", borderRadius: "3px" }}>{cp.auth_url}</code>
            </div>

            {/* Test result */}
            {testResult[cp.id] && (
              <div
                style={{
                  marginTop: "12px",
                  padding: "12px",
                  borderRadius: "6px",
                  background: testResult[cp.id].connected ? "#14532d22" : "#7f1d1d22",
                  border: `1px solid ${testResult[cp.id].connected ? "#22c55e44" : "#ef444444"}`,
                  fontSize: "0.83rem",
                }}
              >
                {testResult[cp.id].connected ? (
                  <>
                    <div style={{ color: "#22c55e", fontWeight: 600, marginBottom: "8px" }}>
                      ✓ Connected — Keystone {testResult[cp.id].keystone_version}
                    </div>
                    {(testResult[cp.id].discovered_regions ?? []).length > 0 && (
                      <div>
                        <strong style={{ color: "#e0e0e0" }}>Discovered regions:</strong>
                        <div style={{ marginTop: "6px", display: "flex", flexWrap: "wrap", gap: "8px" }}>
                          {testResult[cp.id].discovered_regions!.map((dr) => {
                            const alreadyRegistered = testResult[cp.id].already_registered?.includes(dr.region_name);
                            return (
                              <div
                                key={dr.region_name}
                                style={{
                                  background: "rgba(255,255,255,0.05)",
                                  border: "1px solid #333",
                                  borderRadius: "6px",
                                  padding: "6px 10px",
                                  minWidth: "160px",
                                }}
                              >
                                <div style={{ fontWeight: 600, color: "#e0e0e0" }}>{dr.region_name}</div>
                                <div style={{ color: "#6b7280", fontSize: "0.75rem" }}>{dr.services?.join(", ")}</div>
                                {alreadyRegistered ? (
                                  <span style={{ fontSize: "0.72rem", color: "#22c55e" }}>✓ Registered</span>
                                ) : (
                                  <button
                                    style={{ ...btnStyle, background: "#6366f1", color: "white", fontSize: "0.72rem", padding: "2px 8px", marginTop: "4px" }}
                                    onClick={() => {
                                      prefillRegionFromDiscovery(dr);
                                      setShowAddRegion(cp.id);
                                      setExpandedCpId(cp.id);
                                    }}
                                  >
                                    + Register
                                  </button>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <span style={{ color: "#ef4444" }}>✗ Connection failed: {testResult[cp.id].error}</span>
                )}
              </div>
            )}

            {/* Regions (expanded) */}
            {expandedCpId === cp.id && (
              <div style={{ marginTop: "16px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "10px" }}>
                  <strong style={{ fontSize: "0.9rem" }}>Regions</strong>
                  <button
                    style={{ ...btnStyle, background: "#6366f1", color: "white", fontSize: "0.8rem", padding: "3px 10px" }}
                    onClick={() => {
                      setRegionForm({ region_name: "", display_name: "", sync_interval_minutes: 30, priority: 100, is_default: false });
                      setShowAddRegion(cp.id);
                    }}
                  >
                    + Add Region
                  </button>
                  <button
                    style={{ ...btnStyle, background: "#374151", color: "#e0e0e0", fontSize: "0.75rem", padding: "3px 10px" }}
                    onClick={() => loadRegions(cp.id)}
                  >
                    ↻
                  </button>
                </div>

                {/* Add Region Form */}
                {showAddRegion === cp.id && (
                  <div style={{ background: "rgba(99,102,241,0.08)", border: "1px solid #6366f1", borderRadius: "8px", padding: "14px", marginBottom: "12px" }}>
                    <h4 style={{ margin: "0 0 12px", fontSize: "0.9rem" }}>Register Region</h4>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                      <label style={{ fontSize: "0.8rem", color: "#9ca3af" }}>
                        Region Name (OpenStack)
                        <input style={{ ...inputStyle, marginTop: "3px" }} value={regionForm.region_name} onChange={(e) => setRegionForm((f) => ({ ...f, region_name: e.target.value }))} placeholder="region-one" />
                      </label>
                      <label style={{ fontSize: "0.8rem", color: "#9ca3af" }}>
                        Display Name
                        <input style={{ ...inputStyle, marginTop: "3px" }} value={regionForm.display_name} onChange={(e) => setRegionForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="US East" />
                      </label>
                      <label style={{ fontSize: "0.8rem", color: "#9ca3af" }}>
                        Sync Interval (minutes)
                        <input type="number" min={1} max={1440} style={{ ...inputStyle, marginTop: "3px" }} value={regionForm.sync_interval_minutes} onChange={(e) => setRegionForm((f) => ({ ...f, sync_interval_minutes: Number(e.target.value) }))} />
                      </label>
                      <label style={{ fontSize: "0.8rem", color: "#9ca3af" }}>
                        Priority (lower = first)
                        <input type="number" min={1} max={9999} style={{ ...inputStyle, marginTop: "3px" }} value={regionForm.priority} onChange={(e) => setRegionForm((f) => ({ ...f, priority: Number(e.target.value) }))} />
                      </label>
                    </div>
                    <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.8rem", color: "#9ca3af", marginTop: "10px" }}>
                      <input type="checkbox" checked={regionForm.is_default} onChange={(e) => setRegionForm((f) => ({ ...f, is_default: e.target.checked }))} />
                      Set as default region (used when no region_id is specified)
                    </label>
                    <div style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
                      <button
                        style={{ ...btnStyle, background: "#22c55e", color: "white" }}
                        onClick={() => handleAddRegion(cp.id)}
                        disabled={savingRegion}
                      >
                        {savingRegion ? "Saving…" : "💾 Register"}
                      </button>
                      <button style={{ ...btnStyle, background: "#374151", color: "#e0e0e0" }} onClick={() => setShowAddRegion(null)}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}

                {/* Regions table */}
                {(cpRegions[cp.id] ?? []).length === 0 ? (
                  <p style={{ color: "#6b7280", fontSize: "0.85rem" }}>No regions registered. Click <strong>+ Add Region</strong> or <strong>🔌 Test</strong> to discover regions from the catalog.</p>
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.83rem" }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid #333" }}>
                          {["Region", "Status", "Last Sync", "Sync Interval", "Priority", "Actions"].map((h) => (
                            <th key={h} style={{ textAlign: "left", padding: "6px 10px", color: "#6b7280", fontWeight: 600 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(cpRegions[cp.id] ?? []).map((r) => {
                          const syncKey = `${cp.id}:${r.id}`;
                          return (
                            <React.Fragment key={r.id}>
                              <tr style={{ borderBottom: "1px solid #2a2a3a" }}>
                                <td style={{ padding: "8px 10px" }}>
                                  <div style={{ fontWeight: 600 }}>{r.display_name}</div>
                                  <div style={{ color: "#6b7280", fontSize: "0.75rem" }}>{r.region_name}</div>
                                  {r.is_default && <span style={{ fontSize: "0.7rem", background: "#1d4ed8", color: "#bfdbfe", padding: "1px 5px", borderRadius: "6px" }}>default</span>}
                                </td>
                                <td style={{ padding: "8px 10px" }}>
                                  <HealthBadge status={r.health_status} />
                                  {!r.is_enabled && <div style={{ fontSize: "0.72rem", color: "#6b7280", marginTop: "2px" }}>disabled</div>}
                                </td>
                                <td style={{ padding: "8px 10px", color: "#9ca3af" }}>{fmt(r.last_sync_at)}</td>
                                <td style={{ padding: "8px 10px", color: "#9ca3af" }}>{r.sync_interval_minutes}m</td>
                                <td style={{ padding: "8px 10px", color: "#9ca3af" }}>{r.priority}</td>
                                <td style={{ padding: "8px 10px" }}>
                                  <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                                    <button
                                      style={{ ...btnStyle, background: r.is_enabled ? "#374151" : "#166534", color: r.is_enabled ? "#9ca3af" : "#86efac", fontSize: "0.75rem", padding: "3px 8px" }}
                                      onClick={() => handleToggleRegion(cp.id, r)}
                                      title={r.is_enabled ? "Disable region" : "Enable region"}
                                    >
                                      {r.is_enabled ? "Disable" : "Enable"}
                                    </button>
                                    {!r.is_default && (
                                      <button
                                        style={{ ...btnStyle, background: "#1e3a5f", color: "#93c5fd", fontSize: "0.75rem", padding: "3px 8px" }}
                                        onClick={() => handleSetDefault(cp.id, r)}
                                        title="Set as default region"
                                      >
                                        ★ Default
                                      </button>
                                    )}
                                    <button
                                      style={{ ...btnStyle, background: "#1a3344", color: "#67e8f9", fontSize: "0.75rem", padding: "3px 8px" }}
                                      onClick={() => handleTriggerSync(cp.id, r)}
                                      title="Trigger immediate inventory sync"
                                    >
                                      ⟳ Sync
                                    </button>
                                    <button
                                      style={{ ...btnStyle, background: showSync === syncKey ? "#4b5563" : "#1f2937", color: "#d1d5db", fontSize: "0.75rem", padding: "3px 8px" }}
                                      onClick={() => handleViewSync(cp.id, r)}
                                      title="View sync history"
                                    >
                                      📋 Log
                                    </button>
                                  </div>
                                </td>
                              </tr>
                              {/* Sync status inline */}
                              {showSync === syncKey && syncStatus[syncKey] && (
                                <tr>
                                  <td colSpan={6} style={{ padding: "0 10px 12px" }}>
                                    <div style={{ background: "#111827", borderRadius: "6px", padding: "12px", fontSize: "0.78rem" }}>
                                      <strong style={{ color: "#9ca3af" }}>Recent Sync History</strong>
                                      <table style={{ width: "100%", marginTop: "8px", borderCollapse: "collapse" }}>
                                        <thead>
                                          <tr style={{ color: "#6b7280" }}>
                                            {["Type", "Started", "Duration", "Resources", "Errors", "Status"].map((h) => (
                                              <th key={h} style={{ textAlign: "left", padding: "3px 8px" }}>{h}</th>
                                            ))}
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {syncStatus[syncKey].recent.map((s) => (
                                            <tr key={s.id} style={{ borderTop: "1px solid #1f2937" }}>
                                              <td style={{ padding: "3px 8px", color: "#9ca3af" }}>{s.sync_type}</td>
                                              <td style={{ padding: "3px 8px", color: "#9ca3af" }}>{fmt(s.started_at)}</td>
                                              <td style={{ padding: "3px 8px", color: "#9ca3af" }}>{fmtMs(s.duration_ms)}</td>
                                              <td style={{ padding: "3px 8px", color: "#9ca3af" }}>{s.resource_count ?? "—"}</td>
                                              <td style={{ padding: "3px 8px", color: s.error_count ? "#f87171" : "#9ca3af" }}>{s.error_count ?? 0}</td>
                                              <td style={{ padding: "3px 8px" }}>
                                                <HealthBadge status={s.status === "success" ? "healthy" : s.status === "partial" ? "degraded" : "unreachable"} />
                                              </td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                  </td>
                                </tr>
                              )}
                            </React.Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
