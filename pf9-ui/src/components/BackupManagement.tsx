/**
 * Backup Management Tab
 *
 * Database & LDAP backup/restore management UI.  Three sub-views:
 *   1) Status    – dashboard with current status, stats, and manual trigger
 *   2) History   – paginated list of all backup/restore jobs
 *   3) Settings  – backup schedule, retention, NFS path, LDAP backup config
 */

import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";
import "../styles/BackupManagement.css";

// ─── Types ───────────────────────────────────────────────────────────────────

interface BackupConfig {
  id: number;
  enabled: boolean;
  nfs_path: string;
  schedule_type: string;
  schedule_time_utc: string;
  schedule_day_of_week: number;
  retention_count: number;
  retention_days: number;
  last_backup_at: string | null;
  ldap_backup_enabled: boolean;
  ldap_retention_count: number;
  ldap_retention_days: number;
  last_ldap_backup_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface BackupHistoryItem {
  id: number;
  status: string;
  backup_type: string;
  backup_target: string;
  file_name: string | null;
  file_path: string | null;
  file_size_bytes: number | null;
  duration_seconds: number | null;
  initiated_by: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

interface BackupStatus {
  running: boolean;
  last_backup: BackupHistoryItem | null;
  next_scheduled: string | null;
  backup_count: number;
  total_size_bytes: number;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

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

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

function relativeTime(value: string | null | undefined): string {
  if (!value) return "Never";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const now = Date.now();
  const diff = now - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

// ─── Component ───────────────────────────────────────────────────────────────

interface Props {
  isAdmin?: boolean;
}

const BackupManagement: React.FC<Props> = ({ isAdmin }) => {
  const [subTab, setSubTab] = useState<"status" | "history" | "settings">("status");

  // Status state
  const [backupStatus, setBackupStatus] = useState<BackupStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [triggerMsg, setTriggerMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [triggering, setTriggering] = useState(false);

  // History state
  const [history, setHistory] = useState<BackupHistoryItem[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(0);
  const [historyFilter, setHistoryFilter] = useState<string>("");
  const [historyTargetFilter, setHistoryTargetFilter] = useState<string>("");
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Settings state
  const [config, setConfig] = useState<BackupConfig | null>(null);
  const [configDraft, setConfigDraft] = useState<Partial<BackupConfig>>({});
  const [savingConfig, setSavingConfig] = useState(false);
  const [configMsg, setConfigMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  // Confirm dialog
  const [confirmAction, setConfirmAction] = useState<{
    title: string;
    message: string;
    action: () => void;
    danger?: boolean;
  } | null>(null);

  const PAGE_SIZE = 25;

  // ─── Load status ────────────────────────────────────────────────────────────
  const loadStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const data = await apiFetch<BackupStatus>("/api/backup/status");
      setBackupStatus(data);
    } catch (e: any) {
      console.error("Failed to load backup status:", e);
    } finally {
      setStatusLoading(false);
    }
  }, []);

  // ─── Load history ──────────────────────────────────────────────────────────
  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(historyPage * PAGE_SIZE),
      });
      if (historyFilter) params.set("status_filter", historyFilter);
      if (historyTargetFilter) params.set("target_filter", historyTargetFilter);

      const data = await apiFetch<{
        items: BackupHistoryItem[];
        total: number;
      }>(`/api/backup/history?${params}`);
      setHistory(data.items);
      setHistoryTotal(data.total);
    } catch (e: any) {
      console.error("Failed to load backup history:", e);
    } finally {
      setLoadingHistory(false);
    }
  }, [historyPage, historyFilter, historyTargetFilter]);

  // ─── Load config ────────────────────────────────────────────────────────────
  const loadConfig = useCallback(async () => {
    try {
      const data = await apiFetch<BackupConfig>("/api/backup/config");
      setConfig(data);
      setConfigDraft({});
    } catch (e: any) {
      console.error("Failed to load backup config:", e);
    }
  }, []);

  // ─── Auto-refresh ──────────────────────────────────────────────────────────
  useEffect(() => {
    loadStatus();
    const interval = setInterval(loadStatus, 15_000);
    return () => clearInterval(interval);
  }, [loadStatus]);

  useEffect(() => {
    if (subTab === "history") loadHistory();
  }, [subTab, loadHistory]);

  useEffect(() => {
    if (subTab === "settings") loadConfig();
  }, [subTab, loadConfig]);

  // ─── Trigger manual backup ─────────────────────────────────────────────────
  const triggerBackup = async (target: "database" | "ldap" = "database") => {
    setTriggering(true);
    setTriggerMsg(null);
    try {
      await apiFetch(`/api/backup/run?target=${target}`, { method: "POST" });
      const label = target === "ldap" ? "LDAP" : "Database";
      setTriggerMsg({ type: "ok", text: `${label} backup job queued successfully` });
      setTimeout(loadStatus, 2000);
    } catch (e: any) {
      setTriggerMsg({ type: "err", text: e.message || "Failed to trigger backup" });
    } finally {
      setTriggering(false);
    }
  };

  // ─── Trigger restore ──────────────────────────────────────────────────────
  const triggerRestore = async (backupId: number) => {
    try {
      await apiFetch(`/api/backup/restore/${backupId}`, { method: "POST" });
      setTriggerMsg({ type: "ok", text: "Restore job queued — the database will be restored from this backup" });
      setConfirmAction(null);
      loadHistory();
      setTimeout(loadStatus, 2000);
    } catch (e: any) {
      setTriggerMsg({ type: "err", text: e.message || "Failed to trigger restore" });
      setConfirmAction(null);
    }
  };

  // ─── Delete backup ─────────────────────────────────────────────────────────
  const deleteBackup = async (backupId: number) => {
    try {
      await apiFetch(`/api/backup/${backupId}`, { method: "DELETE" });
      setTriggerMsg({ type: "ok", text: "Backup deleted" });
      setConfirmAction(null);
      loadHistory();
      loadStatus();
    } catch (e: any) {
      setTriggerMsg({ type: "err", text: e.message || "Failed to delete backup" });
      setConfirmAction(null);
    }
  };

  // ─── Save config ──────────────────────────────────────────────────────────
  const saveConfig = async () => {
    if (Object.keys(configDraft).length === 0) return;
    setSavingConfig(true);
    setConfigMsg(null);
    try {
      const updated = await apiFetch<BackupConfig>("/api/backup/config", {
        method: "PUT",
        body: JSON.stringify(configDraft),
      });
      setConfig(updated);
      setConfigDraft({});
      setConfigMsg({ type: "ok", text: "Configuration saved" });
    } catch (e: any) {
      setConfigMsg({ type: "err", text: e.message || "Failed to save config" });
    } finally {
      setSavingConfig(false);
    }
  };

  // Current effective config (config + draft overrides)
  const effective = config ? { ...config, ...configDraft } : null;

  const totalPages = Math.ceil(historyTotal / PAGE_SIZE);

  // ─── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="backup-container">
      <div className="backup-header">
        <h2>💾 Backup &amp; Restore</h2>
        <p>
          Manage scheduled and manual database &amp; LDAP backups, view history, and restore from
          previous backups.
        </p>
      </div>

      {/* Sub-tabs */}
      <div className="backup-subtabs">
        <button
          className={`backup-subtab ${subTab === "status" ? "active" : ""}`}
          onClick={() => setSubTab("status")}
        >
          📊 Status
        </button>
        <button
          className={`backup-subtab ${subTab === "history" ? "active" : ""}`}
          onClick={() => setSubTab("history")}
        >
          📋 History
        </button>
        <button
          className={`backup-subtab ${subTab === "settings" ? "active" : ""}`}
          onClick={() => setSubTab("settings")}
        >
          ⚙️ Settings
        </button>
      </div>

      {/* ═══════════ STATUS TAB ═══════════ */}
      {subTab === "status" && (
        <>
          {/* Status cards */}
          <div className="backup-status-bar">
            <div className="backup-stat">
              <div className="backup-stat-value">
                {statusLoading ? "…" : backupStatus?.running ? "🟢 Running" : "⏸ Idle"}
              </div>
              <div className="backup-stat-label">Current State</div>
            </div>
            <div className="backup-stat">
              <div className="backup-stat-value">
                {statusLoading ? "…" : backupStatus?.backup_count ?? 0}
              </div>
              <div className="backup-stat-label">Total Backups</div>
            </div>
            <div className="backup-stat">
              <div className="backup-stat-value">
                {statusLoading ? "…" : formatBytes(backupStatus?.total_size_bytes)}
              </div>
              <div className="backup-stat-label">Total Size</div>
            </div>
            <div className="backup-stat">
              <div className="backup-stat-value">
                {statusLoading
                  ? "…"
                  : relativeTime(backupStatus?.last_backup?.completed_at)}
              </div>
              <div className="backup-stat-label">Last Backup</div>
            </div>
          </div>

          {/* Last backup detail */}
          {backupStatus?.last_backup && (
            <div className="backup-card">
              <h3>Last Completed Backup</h3>
              <div className="backup-field-row">
                <div className="backup-field">
                  <label>File</label>
                  <div style={{ fontSize: "0.93rem" }}>
                    {backupStatus.last_backup.file_name || "—"}
                  </div>
                </div>
                <div className="backup-field">
                  <label>Size</label>
                  <div style={{ fontSize: "0.93rem" }}>
                    {formatBytes(backupStatus.last_backup.file_size_bytes)}
                  </div>
                </div>
                <div className="backup-field">
                  <label>Duration</label>
                  <div style={{ fontSize: "0.93rem" }}>
                    {formatDuration(backupStatus.last_backup.duration_seconds)}
                  </div>
                </div>
                <div className="backup-field">
                  <label>Completed</label>
                  <div style={{ fontSize: "0.93rem" }}>
                    {formatDate(backupStatus.last_backup.completed_at)}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Manual trigger */}
          <div className="backup-card">
            <h3>Manual Backup</h3>
            <p style={{ color: "var(--backup-text-secondary)", fontSize: "0.9rem", margin: "0 0 14px" }}>
              Trigger an immediate backup. The backup worker will execute the job
              and compress the output.
            </p>
            <div className="backup-save-row" style={{ gap: "10px" }}>
              <button
                className="backup-btn backup-btn-primary"
                disabled={triggering || backupStatus?.running}
                onClick={() => triggerBackup("database")}
              >
                {triggering ? "Queuing…" : backupStatus?.running ? "Backup Running…" : "🚀 Database Backup"}
              </button>
              <button
                className="backup-btn backup-btn-outline"
                disabled={triggering || backupStatus?.running}
                onClick={() => triggerBackup("ldap")}
                title="Export all LDAP entries (users, groups) as compressed LDIF"
              >
                {triggering ? "Queuing…" : "📁 LDAP Backup"}
              </button>
              {triggerMsg && (
                <span className={`backup-msg ${triggerMsg.type}`}>{triggerMsg.text}</span>
              )}
            </div>
          </div>
        </>
      )}

      {/* ═══════════ HISTORY TAB ═══════════ */}
      {subTab === "history" && (
        <>
          {/* Filter */}
          <div style={{ display: "flex", gap: "12px", marginBottom: "16px", alignItems: "center", flexWrap: "wrap" }}>
            <select
              value={historyFilter}
              onChange={(e) => {
                setHistoryFilter(e.target.value);
                setHistoryPage(0);
              }}
              style={{
                padding: "7px 12px",
                borderRadius: "6px",
                border: "1px solid var(--backup-border)",
                fontSize: "0.9rem",
                background: "var(--backup-surface)",
                color: "var(--backup-text-primary)",
              }}
            >
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="running">Running</option>
              <option value="pending">Pending</option>
              <option value="failed">Failed</option>
              <option value="deleted">Deleted</option>
            </select>
            <select
              value={historyTargetFilter}
              onChange={(e) => {
                setHistoryTargetFilter(e.target.value);
                setHistoryPage(0);
              }}
              style={{
                padding: "7px 12px",
                borderRadius: "6px",
                border: "1px solid var(--backup-border)",
                fontSize: "0.9rem",
                background: "var(--backup-surface)",
                color: "var(--backup-text-primary)",
              }}
            >
              <option value="">All targets</option>
              <option value="database">Database</option>
              <option value="ldap">LDAP</option>
            </select>
            <button className="backup-btn backup-btn-outline" onClick={loadHistory}>
              🔄 Refresh
            </button>
            {triggerMsg && (
              <span className={`backup-msg ${triggerMsg.type}`}>{triggerMsg.text}</span>
            )}
          </div>

          {loadingHistory ? (
            <div className="backup-empty">Loading…</div>
          ) : history.length === 0 ? (
            <div className="backup-empty">
              <div className="backup-empty-icon">📭</div>
              No backup records found
            </div>
          ) : (
            <>
              <div className="backup-table-wrap">
                <table className="backup-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Status</th>
                      <th>Target</th>
                      <th>Type</th>
                      <th>File</th>
                      <th>Size</th>
                      <th>Duration</th>
                      <th>Initiated By</th>
                      <th>Started</th>
                      <th>Completed</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((item) => (
                      <tr key={item.id}>
                        <td>{item.id}</td>
                        <td>
                          <span className={`backup-badge ${item.status}`}>
                            {item.status}
                          </span>
                        </td>
                        <td>
                          <span className={`backup-badge ${item.backup_target === "ldap" ? "ldap" : "database"}`}>
                            {item.backup_target === "ldap" ? "📁 LDAP" : "🗄️ DB"}
                          </span>
                        </td>
                        <td>
                          <span className={`backup-badge ${item.backup_type === "restore" ? "restore" : ""}`}>
                            {item.backup_type}
                          </span>
                        </td>
                        <td title={item.file_path || ""}>
                          {item.file_name || "—"}
                        </td>
                        <td>{formatBytes(item.file_size_bytes)}</td>
                        <td>{formatDuration(item.duration_seconds)}</td>
                        <td>{item.initiated_by || "—"}</td>
                        <td>{formatDate(item.started_at)}</td>
                        <td>{formatDate(item.completed_at)}</td>
                        <td>
                          <div style={{ display: "flex", gap: "6px" }}>
                            {item.status === "completed" && item.backup_type !== "restore" && isAdmin && (
                              <button
                                className="backup-btn backup-btn-outline"
                                style={{ padding: "4px 10px", fontSize: "0.8rem" }}
                                title="Restore from this backup"
                                onClick={() =>
                                  setConfirmAction({
                                    title: "Confirm Restore",
                                    message: `Restore the database from backup "${item.file_name}"? This will overwrite current data.`,
                                    action: () => triggerRestore(item.id),
                                    danger: true,
                                  })
                                }
                              >
                                ♻️ Restore
                              </button>
                            )}
                            {item.status === "completed" && isAdmin && (
                              <button
                                className="backup-btn backup-btn-danger"
                                style={{ padding: "4px 10px", fontSize: "0.8rem" }}
                                title="Delete this backup"
                                onClick={() =>
                                  setConfirmAction({
                                    title: "Delete Backup",
                                    message: `Permanently delete backup "${item.file_name}" and its file on disk?`,
                                    action: () => deleteBackup(item.id),
                                    danger: true,
                                  })
                                }
                              >
                                🗑️
                              </button>
                            )}
                            {item.status === "failed" && item.error_message && (
                              <span
                                title={item.error_message}
                                style={{ cursor: "help", fontSize: "0.85rem", color: "#ef4444" }}
                              >
                                ⚠️ Error
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="backup-pagination">
                  <button
                    className="backup-btn backup-btn-outline"
                    style={{ padding: "4px 12px" }}
                    disabled={historyPage === 0}
                    onClick={() => setHistoryPage((p) => p - 1)}
                  >
                    ← Prev
                  </button>
                  <span>
                    Page {historyPage + 1} of {totalPages}
                  </span>
                  <button
                    className="backup-btn backup-btn-outline"
                    style={{ padding: "4px 12px" }}
                    disabled={historyPage >= totalPages - 1}
                    onClick={() => setHistoryPage((p) => p + 1)}
                  >
                    Next →
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* ═══════════ SETTINGS TAB ═══════════ */}
      {subTab === "settings" && effective && (
        <>
          {/* Enable toggle */}
          <div className="backup-card">
            <h3>Backup Schedule</h3>

            <div className="backup-toggle-row">
              <span>Automated Backups</span>
              <label className="backup-switch">
                <input
                  type="checkbox"
                  checked={effective.enabled}
                  onChange={(e) =>
                    setConfigDraft((d) => ({ ...d, enabled: e.target.checked }))
                  }
                />
                <span className="backup-slider"></span>
              </label>
              <span style={{ color: "var(--backup-text-secondary)", fontSize: "0.85rem" }}>
                {effective.enabled ? "Enabled" : "Disabled"}
              </span>
            </div>

            <div className="backup-field-row">
              <div className="backup-field">
                <label>Schedule Type</label>
                <select
                  value={effective.schedule_type}
                  onChange={(e) =>
                    setConfigDraft((d) => ({ ...d, schedule_type: e.target.value }))
                  }
                >
                  <option value="manual">Manual Only</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
              </div>

              <div className="backup-field">
                <label>Time (UTC)</label>
                <input
                  type="time"
                  value={effective.schedule_time_utc}
                  onChange={(e) =>
                    setConfigDraft((d) => ({ ...d, schedule_time_utc: e.target.value }))
                  }
                />
                <div className="backup-field-hint">
                  Time of day (UTC) to run the scheduled backup
                </div>
              </div>
            </div>

            {effective.schedule_type === "weekly" && (
              <div className="backup-field">
                <label>Day of Week</label>
                <select
                  value={effective.schedule_day_of_week}
                  onChange={(e) =>
                    setConfigDraft((d) => ({
                      ...d,
                      schedule_day_of_week: Number(e.target.value),
                    }))
                  }
                >
                  {DAY_NAMES.map((name, i) => (
                    <option key={i} value={i}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* Retention */}
          <div className="backup-card">
            <h3>Retention Policy</h3>
            <div className="backup-field-row">
              <div className="backup-field">
                <label>Keep Last N Backups</label>
                <input
                  type="number"
                  min={1}
                  value={effective.retention_count}
                  onChange={(e) =>
                    setConfigDraft((d) => ({
                      ...d,
                      retention_count: Math.max(1, Number(e.target.value)),
                    }))
                  }
                />
                <div className="backup-field-hint">
                  Maximum number of completed backups to keep
                </div>
              </div>
              <div className="backup-field">
                <label>Retention Days</label>
                <input
                  type="number"
                  min={1}
                  value={effective.retention_days}
                  onChange={(e) =>
                    setConfigDraft((d) => ({
                      ...d,
                      retention_days: Math.max(1, Number(e.target.value)),
                    }))
                  }
                />
                <div className="backup-field-hint">
                  Delete backups older than this many days
                </div>
              </div>
            </div>
          </div>

          {/* NFS path */}
          <div className="backup-card">
            <h3>Storage</h3>
            <div className="backup-field">
              <label>NFS Backup Path</label>
              <input
                type="text"
                value={effective.nfs_path}
                onChange={(e) =>
                  setConfigDraft((d) => ({ ...d, nfs_path: e.target.value }))
                }
              />
              <div className="backup-field-hint">
                Mount point where backup files are written (must be writable by the backup worker)
              </div>
            </div>
          </div>

          {/* LDAP Backup */}
          <div className="backup-card">
            <h3>📁 LDAP Backup</h3>
            <p style={{ color: "var(--backup-text-secondary)", fontSize: "0.9rem", margin: "0 0 14px" }}>
              When enabled, the backup worker will also export all LDAP directory entries
              (users, groups, OUs) as compressed LDIF files on the same schedule as database backups.
            </p>

            <div className="backup-toggle-row">
              <span>LDAP Scheduled Backup</span>
              <label className="backup-switch">
                <input
                  type="checkbox"
                  checked={effective.ldap_backup_enabled ?? false}
                  onChange={(e) =>
                    setConfigDraft((d) => ({ ...d, ldap_backup_enabled: e.target.checked }))
                  }
                />
                <span className="backup-slider"></span>
              </label>
              <span style={{ color: "var(--backup-text-secondary)", fontSize: "0.85rem" }}>
                {effective.ldap_backup_enabled ? "Enabled" : "Disabled"}
              </span>
            </div>

            <div className="backup-field-row">
              <div className="backup-field">
                <label>Keep Last N LDAP Backups</label>
                <input
                  type="number"
                  min={1}
                  value={effective.ldap_retention_count ?? 7}
                  onChange={(e) =>
                    setConfigDraft((d) => ({
                      ...d,
                      ldap_retention_count: Math.max(1, Number(e.target.value)),
                    }))
                  }
                />
              </div>
              <div className="backup-field">
                <label>LDAP Retention Days</label>
                <input
                  type="number"
                  min={1}
                  value={effective.ldap_retention_days ?? 30}
                  onChange={(e) =>
                    setConfigDraft((d) => ({
                      ...d,
                      ldap_retention_days: Math.max(1, Number(e.target.value)),
                    }))
                  }
                />
              </div>
            </div>
          </div>

          {/* Save */}
          <div className="backup-save-row">
            <button
              className="backup-btn backup-btn-primary"
              disabled={savingConfig || Object.keys(configDraft).length === 0}
              onClick={saveConfig}
            >
              {savingConfig ? "Saving…" : "💾 Save Configuration"}
            </button>
            {Object.keys(configDraft).length > 0 && (
              <button
                className="backup-btn backup-btn-outline"
                onClick={() => setConfigDraft({})}
              >
                Reset
              </button>
            )}
            {configMsg && (
              <span className={`backup-msg ${configMsg.type}`}>{configMsg.text}</span>
            )}
          </div>

          {/* Info card */}
          {config && (
            <div className="backup-card" style={{ marginTop: "20px" }}>
              <h3>Current Configuration</h3>
              <div className="backup-field-row" style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr" }}>
                <div className="backup-field">
                  <label>Last Updated</label>
                  <div style={{ fontSize: "0.9rem" }}>{formatDate(config.updated_at)}</div>
                </div>
                <div className="backup-field">
                  <label>Last DB Backup</label>
                  <div style={{ fontSize: "0.9rem" }}>{formatDate(config.last_backup_at)}</div>
                </div>
                <div className="backup-field">
                  <label>Last LDAP Backup</label>
                  <div style={{ fontSize: "0.9rem" }}>{formatDate(config.last_ldap_backup_at)}</div>
                </div>
                <div className="backup-field">
                  <label>Config ID</label>
                  <div style={{ fontSize: "0.9rem" }}>{config.id}</div>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* Loading state for settings */}
      {subTab === "settings" && !effective && (
        <div className="backup-empty">Loading configuration…</div>
      )}

      {/* ═══════════ CONFIRM DIALOG ═══════════ */}
      {confirmAction && (
        <div className="backup-overlay" onClick={() => setConfirmAction(null)}>
          <div className="backup-dialog" onClick={(e) => e.stopPropagation()}>
            <h3>{confirmAction.title}</h3>
            <p>{confirmAction.message}</p>
            <div className="backup-dialog-actions">
              <button
                className="backup-btn backup-btn-outline"
                onClick={() => setConfirmAction(null)}
              >
                Cancel
              </button>
              <button
                className={`backup-btn ${confirmAction.danger ? "backup-btn-danger" : "backup-btn-primary"}`}
                onClick={confirmAction.action}
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default BackupManagement;
