/**
 * Notification Settings Tab
 *
 * Lets users manage their email notification preferences — subscribe to
 * event types (drift, snapshot failures, compliance violations, health drops),
 * configure severity thresholds and delivery mode (immediate vs. digest),
 * view notification history, send test emails, and see SMTP status.
 *
 * Three sub-views:
 *   1) Preferences – toggle subscriptions per event type
 *   2) History     – paginated log of sent notifications
 *   3) Settings    – SMTP status, test email, admin stats
 */

import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";
import "../styles/NotificationSettings.css";

// ─── Types ───────────────────────────────────────────────────────────────────

interface NotificationPreference {
  id: number | null;
  username: string;
  email: string;
  event_type: string;
  severity_min: string;
  delivery_mode: string;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

interface NotificationLogEntry {
  id: number;
  username: string;
  email: string;
  event_type: string;
  event_id: string | null;
  subject: string;
  body_preview: string | null;
  delivery_status: string;
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
}

interface SmtpStatus {
  smtp_enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_use_tls: boolean;
  smtp_from_address: string;
  smtp_from_name: string;
  smtp_username_configured: boolean;
}

interface NotificationStats {
  stats: {
    total_sent: number;
    delivered: number;
    failed: number;
    digest_queued: number;
    unique_users: number;
    last_24h: number;
    last_7d: number;
  };
  by_event_type_7d: { event_type: string; count: number }[];
  subscribers: {
    total_subscribers: number;
    active_subscribers: number;
  };
}

// ─── Constants ───────────────────────────────────────────────────────────────

const EVENT_TYPE_META: Record<string, { label: string; icon: string; description: string }> = {
  drift_critical:       { label: "Critical Drift",         icon: "🔴", description: "Unacknowledged critical-severity drift events" },
  drift_warning:        { label: "Drift Warning",          icon: "🟡", description: "Unacknowledged warning-severity drift events" },
  drift_info:           { label: "Drift Info",             icon: "ℹ️",  description: "Informational drift events" },
  snapshot_failure:     { label: "Snapshot Failure",       icon: "📸", description: "Failed or partial snapshot pipeline runs" },
  compliance_violation: { label: "Compliance Violation",   icon: "⚠️",  description: "Non-compliant volumes exceeding SLA" },
  health_score_drop:    { label: "Health Score Drop",      icon: "🏥", description: "Tenant health score below threshold" },
};

const SEVERITY_OPTIONS = ["info", "warning", "critical"];
const DELIVERY_OPTIONS = ["immediate", "digest"];

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

// ─── Component ───────────────────────────────────────────────────────────────

interface Props {
  isAdmin?: boolean;
}

const NotificationSettings: React.FC<Props> = ({ isAdmin }) => {
  const [subTab, setSubTab] = useState<"preferences" | "history" | "settings">("preferences");

  // Preferences state
  const [preferences, setPreferences] = useState<NotificationPreference[]>([]);
  const [availableTypes, setAvailableTypes] = useState<string[]>([]);
  const [userEmail, setUserEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [prefMsg, setPrefMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  // History state
  const [history, setHistory] = useState<NotificationLogEntry[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(0);
  const [historyFilter, setHistoryFilter] = useState<string>("");
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Settings state
  const [smtpStatus, setSmtpStatus] = useState<SmtpStatus | null>(null);
  const [testEmail, setTestEmail] = useState("");
  const [testMsg, setTestMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [sendingTest, setSendingTest] = useState(false);
  const [stats, setStats] = useState<NotificationStats | null>(null);

  const PAGE_SIZE = 25;

  // ─── Load preferences ──────────────────────────────────────────────────────
  const loadPreferences = useCallback(async () => {
    try {
      const data = await apiFetch<{
        preferences: NotificationPreference[];
        available_event_types: string[];
      }>("/notifications/preferences");
      setPreferences(data.preferences);
      setAvailableTypes(data.available_event_types);
      if (data.preferences.length > 0 && !userEmail) {
        setUserEmail(data.preferences[0].email);
      }
    } catch (e: any) {
      console.error("Failed to load preferences:", e);
    }
  }, [userEmail]);

  // ─── Load history ──────────────────────────────────────────────────────────
  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      let path = `/notifications/history?limit=${PAGE_SIZE}&offset=${historyPage * PAGE_SIZE}`;
      if (historyFilter) path += `&event_type=${historyFilter}`;
      const data = await apiFetch<{
        history: NotificationLogEntry[];
        total: number;
      }>(path);
      setHistory(data.history);
      setHistoryTotal(data.total);
    } catch (e: any) {
      console.error("Failed to load history:", e);
    } finally {
      setLoadingHistory(false);
    }
  }, [historyPage, historyFilter]);

  // ─── Load settings ─────────────────────────────────────────────────────────
  const loadSettings = useCallback(async () => {
    try {
      const smtp = await apiFetch<SmtpStatus>("/notifications/smtp-status");
      setSmtpStatus(smtp);
    } catch (e: any) {
      console.error("Failed to load SMTP status:", e);
    }
    if (isAdmin) {
      try {
        const s = await apiFetch<NotificationStats>("/notifications/admin/stats");
        setStats(s);
      } catch {
        // non-admin users won't have access — that's fine
      }
    }
  }, [isAdmin]);

  useEffect(() => { loadPreferences(); }, [loadPreferences]);
  useEffect(() => { if (subTab === "history") loadHistory(); }, [subTab, loadHistory]);
  useEffect(() => { if (subTab === "settings") loadSettings(); }, [subTab, loadSettings]);

  // ─── Save preferences ──────────────────────────────────────────────────────
  const savePreferences = async () => {
    if (!userEmail.trim()) {
      setPrefMsg({ type: "err", text: "Please enter your email address" });
      return;
    }
    setSaving(true);
    setPrefMsg(null);
    try {
      const payload = availableTypes.map((et) => {
        const existing = preferences.find((p) => p.event_type === et);
        return {
          event_type: et,
          email: userEmail.trim(),
          severity_min: existing?.severity_min || "warning",
          delivery_mode: existing?.delivery_mode || "immediate",
          enabled: existing?.enabled ?? false,
        };
      });
      await apiFetch("/notifications/preferences", {
        method: "PUT",
        body: JSON.stringify({ preferences: payload }),
      });
      setPrefMsg({ type: "ok", text: "Preferences saved!" });
      loadPreferences();
    } catch (e: any) {
      setPrefMsg({ type: "err", text: e.message });
    } finally {
      setSaving(false);
    }
  };

  // ─── Toggle a preference ───────────────────────────────────────────────────
  const togglePref = (eventType: string) => {
    setPreferences((prev) => {
      const existing = prev.find((p) => p.event_type === eventType);
      if (existing) {
        return prev.map((p) =>
          p.event_type === eventType ? { ...p, enabled: !p.enabled } : p
        );
      }
      return [
        ...prev,
        {
          id: null,
          username: "",
          email: userEmail,
          event_type: eventType,
          severity_min: "warning",
          delivery_mode: "immediate",
          enabled: true,
          created_at: null,
          updated_at: null,
        },
      ];
    });
  };

  const updatePrefField = (eventType: string, field: string, value: string) => {
    setPreferences((prev) =>
      prev.map((p) => (p.event_type === eventType ? { ...p, [field]: value } : p))
    );
  };

  // ─── Test email ────────────────────────────────────────────────────────────
  const handleTestEmail = async () => {
    if (!testEmail.trim()) return;
    setSendingTest(true);
    setTestMsg(null);
    try {
      const data = await apiFetch<{ message: string }>("/notifications/test-email", {
        method: "POST",
        body: JSON.stringify({ to_email: testEmail.trim() }),
      });
      setTestMsg({ type: "ok", text: data.message });
    } catch (e: any) {
      setTestMsg({ type: "err", text: e.message });
    } finally {
      setSendingTest(false);
    }
  };

  // ─── Render: Sub-tab navigation ────────────────────────────────────────────
  return (
    <div className="notif-container">
      <div className="notif-header">
        <h2>🔔 Notification Settings</h2>
        <p className="notif-subtitle">
          Configure email alerts for drift events, snapshot failures, compliance violations, and health score changes.
        </p>
      </div>

      <div className="notif-subtabs">
        {(["preferences", "history", "settings"] as const).map((t) => (
          <button
            key={t}
            className={`notif-subtab ${subTab === t ? "active" : ""}`}
            onClick={() => setSubTab(t)}
          >
            {t === "preferences" && "📋 Preferences"}
            {t === "history" && "📜 History"}
            {t === "settings" && "⚙️ Settings"}
          </button>
        ))}
      </div>

      {/* ─── Preferences Sub-tab ──────────────────────────────────────────── */}
      {subTab === "preferences" && (
        <div className="notif-section">
          <div className="notif-email-row">
            <label>Notification Email:</label>
            <input
              type="email"
              className="notif-input"
              placeholder="you@example.com"
              value={userEmail}
              onChange={(e) => setUserEmail(e.target.value)}
            />
          </div>

          <div className="notif-pref-grid">
            {availableTypes.map((et) => {
              const meta = EVENT_TYPE_META[et] || { label: et, icon: "🔔", description: "" };
              const pref = preferences.find((p) => p.event_type === et);
              const enabled = pref?.enabled ?? false;

              return (
                <div key={et} className={`notif-pref-card ${enabled ? "enabled" : "disabled"}`}>
                  <div className="notif-pref-top">
                    <span className="notif-pref-icon">{meta.icon}</span>
                    <div className="notif-pref-info">
                      <div className="notif-pref-label">{meta.label}</div>
                      <div className="notif-pref-desc">{meta.description}</div>
                    </div>
                    <label className="notif-toggle">
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={() => togglePref(et)}
                      />
                      <span className="notif-toggle-slider" />
                    </label>
                  </div>

                  {enabled && (
                    <div className="notif-pref-options">
                      <div className="notif-pref-option">
                        <span>Min Severity:</span>
                        <select
                          value={pref?.severity_min || "warning"}
                          onChange={(e) => updatePrefField(et, "severity_min", e.target.value)}
                        >
                          {SEVERITY_OPTIONS.map((s) => (
                            <option key={s} value={s}>{s}</option>
                          ))}
                        </select>
                      </div>
                      <div className="notif-pref-option">
                        <span>Delivery:</span>
                        <select
                          value={pref?.delivery_mode || "immediate"}
                          onChange={(e) => updatePrefField(et, "delivery_mode", e.target.value)}
                        >
                          {DELIVERY_OPTIONS.map((d) => (
                            <option key={d} value={d}>{d}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="notif-save-row">
            <button className="notif-btn-primary" onClick={savePreferences} disabled={saving}>
              {saving ? "Saving…" : "💾 Save Preferences"}
            </button>
            {prefMsg && (
              <span className={`notif-msg ${prefMsg.type}`}>{prefMsg.text}</span>
            )}
          </div>
        </div>
      )}

      {/* ─── History Sub-tab ──────────────────────────────────────────────── */}
      {subTab === "history" && (
        <div className="notif-section">
          <div className="notif-history-controls">
            <select
              value={historyFilter}
              onChange={(e) => { setHistoryFilter(e.target.value); setHistoryPage(0); }}
              className="notif-select"
            >
              <option value="">All Event Types</option>
              {Object.entries(EVENT_TYPE_META).map(([key, meta]) => (
                <option key={key} value={key}>{meta.icon} {meta.label}</option>
              ))}
            </select>
            <span className="notif-history-count">
              {historyTotal} notification{historyTotal !== 1 ? "s" : ""}
            </span>
          </div>

          {loadingHistory ? (
            <div className="notif-loading">Loading…</div>
          ) : history.length === 0 ? (
            <div className="notif-empty">
              <p>📭 No notifications yet</p>
              <p className="notif-empty-hint">
                Notifications will appear here once you enable subscriptions and events are detected.
              </p>
            </div>
          ) : (
            <>
              <table className="notif-table">
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Type</th>
                    <th>Subject</th>
                    <th>Sent</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((entry) => (
                    <tr key={entry.id}>
                      <td>
                        <span className={`notif-status-badge ${entry.delivery_status}`}>
                          {entry.delivery_status === "sent" && "✅"}
                          {entry.delivery_status === "failed" && "❌"}
                          {entry.delivery_status === "digest_queued" && "📬"}
                          {entry.delivery_status === "pending" && "⏳"}
                          {" "}{entry.delivery_status}
                        </span>
                      </td>
                      <td>
                        <span className="notif-type-badge">
                          {EVENT_TYPE_META[entry.event_type]?.icon || "🔔"}{" "}
                          {EVENT_TYPE_META[entry.event_type]?.label || entry.event_type}
                        </span>
                      </td>
                      <td className="notif-subject-cell" title={entry.subject}>
                        {entry.subject}
                        {entry.error_message && (
                          <div className="notif-error-hint">{entry.error_message}</div>
                        )}
                      </td>
                      <td className="notif-date-cell">
                        {entry.sent_at
                          ? new Date(entry.sent_at).toLocaleString()
                          : new Date(entry.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="notif-pagination">
                <button
                  disabled={historyPage === 0}
                  onClick={() => setHistoryPage((p) => p - 1)}
                >← Prev</button>
                <span>
                  Page {historyPage + 1} of {Math.max(1, Math.ceil(historyTotal / PAGE_SIZE))}
                </span>
                <button
                  disabled={(historyPage + 1) * PAGE_SIZE >= historyTotal}
                  onClick={() => setHistoryPage((p) => p + 1)}
                >Next →</button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ─── Settings Sub-tab ─────────────────────────────────────────────── */}
      {subTab === "settings" && (
        <div className="notif-section">
          {/* SMTP Status */}
          <div className="notif-card">
            <h3>📧 SMTP Configuration</h3>
            {smtpStatus ? (
              <div className="notif-smtp-grid">
                <div className="notif-smtp-row">
                  <span className="notif-smtp-label">Status</span>
                  <span className={`notif-smtp-value ${smtpStatus.smtp_enabled ? "enabled" : "disabled"}`}>
                    {smtpStatus.smtp_enabled ? "✅ Enabled" : "❌ Disabled"}
                  </span>
                </div>
                {smtpStatus.smtp_enabled && (
                  <>
                    <div className="notif-smtp-row">
                      <span className="notif-smtp-label">Host</span>
                      <span className="notif-smtp-value">{smtpStatus.smtp_host}:{smtpStatus.smtp_port}</span>
                    </div>
                    <div className="notif-smtp-row">
                      <span className="notif-smtp-label">TLS</span>
                      <span className="notif-smtp-value">{smtpStatus.smtp_use_tls ? "Yes" : "No"}</span>
                    </div>
                    <div className="notif-smtp-row">
                      <span className="notif-smtp-label">From</span>
                      <span className="notif-smtp-value">{smtpStatus.smtp_from_name} &lt;{smtpStatus.smtp_from_address}&gt;</span>
                    </div>
                    <div className="notif-smtp-row">
                      <span className="notif-smtp-label">Auth</span>
                      <span className="notif-smtp-value">{smtpStatus.smtp_username_configured ? "Configured" : "None"}</span>
                    </div>
                  </>
                )}
              </div>
            ) : (
              <p className="notif-loading">Loading SMTP status…</p>
            )}
          </div>

          {/* Test Email */}
          <div className="notif-card">
            <h3>🧪 Send Test Email</h3>
            <div className="notif-test-row">
              <input
                type="email"
                className="notif-input"
                placeholder="recipient@example.com"
                value={testEmail}
                onChange={(e) => setTestEmail(e.target.value)}
              />
              <button
                className="notif-btn-primary"
                onClick={handleTestEmail}
                disabled={sendingTest || !testEmail.trim()}
              >
                {sendingTest ? "Sending…" : "Send Test"}
              </button>
            </div>
            {testMsg && (
              <div className={`notif-msg ${testMsg.type}`}>{testMsg.text}</div>
            )}
          </div>

          {/* Admin Stats */}
          {isAdmin && stats && (
            <div className="notif-card">
              <h3>📊 Notification System Stats</h3>
              <div className="notif-stats-grid">
                <div className="notif-stat">
                  <div className="notif-stat-value">{stats.stats.delivered}</div>
                  <div className="notif-stat-label">Delivered</div>
                </div>
                <div className="notif-stat">
                  <div className="notif-stat-value notif-stat-fail">{stats.stats.failed}</div>
                  <div className="notif-stat-label">Failed</div>
                </div>
                <div className="notif-stat">
                  <div className="notif-stat-value">{stats.stats.last_24h}</div>
                  <div className="notif-stat-label">Last 24h</div>
                </div>
                <div className="notif-stat">
                  <div className="notif-stat-value">{stats.stats.last_7d}</div>
                  <div className="notif-stat-label">Last 7 days</div>
                </div>
                <div className="notif-stat">
                  <div className="notif-stat-value">{stats.subscribers.active_subscribers}</div>
                  <div className="notif-stat-label">Active Subscribers</div>
                </div>
                <div className="notif-stat">
                  <div className="notif-stat-value">{stats.stats.digest_queued}</div>
                  <div className="notif-stat-label">Digest Queued</div>
                </div>
              </div>

              {stats.by_event_type_7d.length > 0 && (
                <div className="notif-type-breakdown">
                  <h4>Last 7 Days by Event Type</h4>
                  {stats.by_event_type_7d.map((item) => (
                    <div key={item.event_type} className="notif-type-bar-row">
                      <span className="notif-type-bar-label">
                        {EVENT_TYPE_META[item.event_type]?.icon || "🔔"}{" "}
                        {EVENT_TYPE_META[item.event_type]?.label || item.event_type}
                      </span>
                      <div className="notif-type-bar-track">
                        <div
                          className="notif-type-bar-fill"
                          style={{
                            width: `${Math.min(100, (item.count / Math.max(...stats.by_event_type_7d.map((x) => x.count))) * 100)}%`,
                          }}
                        />
                      </div>
                      <span className="notif-type-bar-count">{item.count}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default NotificationSettings;
