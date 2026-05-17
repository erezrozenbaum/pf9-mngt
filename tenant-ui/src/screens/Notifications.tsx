import React, { useCallback, useEffect, useState } from "react";
import {
  apiNotifDelete,
  apiNotifHistory,
  apiNotifPreferences,
  apiNotifUpsert,
  apiNotifWebhookTest,
  type NotifChannel,
  type NotifHistoryRow,
  type NotifPref,
} from "../lib/api";

// ---------------------------------------------------------------------------
// Event type metadata
// ---------------------------------------------------------------------------

const EVENT_TYPES: { key: string; label: string; description: string }[] = [
  { key: "snapshot_completed", label: "Snapshot Completed", description: "A snapshot was created successfully." },
  { key: "snapshot_failed",    label: "Snapshot Failed",    description: "A snapshot creation failed." },
  { key: "restore_completed",  label: "Restore Completed",  description: "A VM restore completed." },
  { key: "restore_failed",     label: "Restore Failed",     description: "A VM restore failed." },
  { key: "quota_at_80pct",     label: "Quota at 80%",       description: "A resource quota reached 80% usage." },
  { key: "quota_at_95pct",     label: "Quota at 95%",       description: "A resource quota reached 95% usage." },
  { key: "vm_provisioned",     label: "VM Provisioned",     description: "A VM was provisioned successfully." },
  { key: "vm_provision_failed",label: "VM Provision Failed",description: "A VM provisioning request failed." },
  { key: "billing_invoice_ready", label: "Invoice Ready",   description: "A billing invoice is available." },
];

const CHANNELS: { key: NotifChannel; label: string }[] = [
  { key: "email",   label: "Email" },
  { key: "webhook", label: "Webhook" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type PrefKey = `${string}::${NotifChannel}`;

function prefKey(event_type: string, channel: NotifChannel): PrefKey {
  return `${event_type}::${channel}` as PrefKey;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Notifications() {
  const [tab, setTab] = useState<"prefs" | "history">("prefs");

  // Preferences state: map of "event_type::channel" → pref
  const [prefMap, setPrefMap] = useState<Map<PrefKey, NotifPref>>(new Map());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  // Webhook test state per channel row
  const [testState, setTestState] = useState<Map<PrefKey, { loading: boolean; result: string | null }>>(new Map());

  // History
  const [history, setHistory] = useState<NotifHistoryRow[]>([]);
  const [histLoading, setHistLoading] = useState(false);
  const [histError, setHistError] = useState<string | null>(null);

  // Load preferences
  const loadPrefs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const prefs = await apiNotifPreferences();
      const map = new Map<PrefKey, NotifPref>();
      prefs.forEach((p) => map.set(prefKey(p.event_type, p.channel), p));
      setPrefMap(map);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load notification preferences");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPrefs();
  }, [loadPrefs]);

  const loadHistory = useCallback(async () => {
    setHistLoading(true);
    setHistError(null);
    try {
      setHistory(await apiNotifHistory());
    } catch (e: unknown) {
      setHistError(e instanceof Error ? e.message : "Failed to load notification history");
    } finally {
      setHistLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "history") loadHistory();
  }, [tab, loadHistory]);

  // Toggle enabled state locally
  const toggleEnabled = (event_type: string, channel: NotifChannel) => {
    const key = prefKey(event_type, channel);
    setPrefMap((prev) => {
      const next = new Map(prev);
      const existing = next.get(key);
      if (existing) {
        next.set(key, { ...existing, enabled: !existing.enabled });
      } else {
        next.set(key, { event_type, channel, endpoint: "", enabled: true });
      }
      return next;
    });
  };

  // Update endpoint
  const setEndpoint = (event_type: string, channel: NotifChannel, endpoint: string) => {
    const key = prefKey(event_type, channel);
    setPrefMap((prev) => {
      const next = new Map(prev);
      const existing = next.get(key) ?? { event_type, channel, endpoint: "", enabled: true };
      next.set(key, { ...existing, endpoint });
      return next;
    });
  };

  // Save all
  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSaveMsg(null);
    const toSave: NotifPref[] = [];
    prefMap.forEach((p) => {
      if (p.endpoint.trim()) toSave.push(p);
    });
    if (toSave.length === 0) {
      setSaving(false);
      setSaveMsg("No preferences with endpoints to save.");
      return;
    }
    try {
      const { updated } = await apiNotifUpsert(toSave);
      setSaveMsg(`Saved ${updated} preference(s).`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save preferences");
    } finally {
      setSaving(false);
    }
  };

  // Delete one subscription
  const handleDelete = async (event_type: string, channel: NotifChannel) => {
    const key = prefKey(event_type, channel);
    try {
      await apiNotifDelete(event_type, channel);
      setPrefMap((prev) => {
        const next = new Map(prev);
        next.delete(key);
        return next;
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to delete preference");
    }
  };

  // Test webhook
  const handleWebhookTest = async (event_type: string, channel: NotifChannel) => {
    const key = prefKey(event_type, channel);
    const pref = prefMap.get(key);
    if (!pref?.endpoint) return;
    setTestState((prev) => {
      const next = new Map(prev);
      next.set(key, { loading: true, result: null });
      return next;
    });
    try {
      const { ok, status } = await apiNotifWebhookTest(pref.endpoint);
      setTestState((prev) => {
        const next = new Map(prev);
        next.set(key, { loading: false, result: ok ? `✅ HTTP ${status}` : `⚠️ HTTP ${status}` });
        return next;
      });
    } catch (e: unknown) {
      setTestState((prev) => {
        const next = new Map(prev);
        next.set(key, { loading: false, result: `❌ ${e instanceof Error ? e.message : "Error"}` });
        return next;
      });
    }
  };

  return (
    <div style={{ padding: "var(--space-6, 24px)" }}>
      <h2 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "var(--space-4, 16px)", color: "var(--color-text)" }}>
        Notification Settings
      </h2>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 24, borderBottom: "1px solid var(--color-border)" }}>
        {(["prefs", "history"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: "8px 16px",
              background: "none",
              border: "none",
              borderBottom: tab === t ? "2px solid var(--color-primary, #667eea)" : "2px solid transparent",
              color: tab === t ? "var(--color-primary, #667eea)" : "var(--color-text-muted)",
              fontWeight: tab === t ? 600 : 400,
              cursor: "pointer",
              fontSize: "0.9rem",
            }}
          >
            {t === "prefs" ? "Subscriptions" : "History"}
          </button>
        ))}
      </div>

      {tab === "prefs" && (
        <>
          {loading && <p style={{ color: "var(--color-text-muted)" }}>Loading…</p>}
          {error && (
            <div style={{ background: "#fee", color: "#c00", padding: "10px 14px", borderRadius: 6, marginBottom: 16, fontSize: "0.875rem" }}>
              {error}
            </div>
          )}
          {saveMsg && (
            <div style={{ background: "#efe", color: "#060", padding: "10px 14px", borderRadius: 6, marginBottom: 16, fontSize: "0.875rem" }}>
              {saveMsg}
            </div>
          )}

          {!loading && (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
                <thead>
                  <tr style={{ background: "var(--color-surface-alt, #f8f9fa)" }}>
                    <th style={thStyle}>Event</th>
                    {CHANNELS.map((ch) => (
                      <th key={ch.key} style={thStyle} colSpan={3}>{ch.label}</th>
                    ))}
                  </tr>
                  <tr style={{ background: "var(--color-surface-alt, #f8f9fa)", fontSize: "0.78rem", color: "var(--color-text-muted)" }}>
                    <th style={thStyle} />
                    {CHANNELS.map((ch) => (
                      <React.Fragment key={ch.key}>
                        <th style={thStyle}>Enable</th>
                        <th style={thStyle}>Endpoint</th>
                        <th style={thStyle} />
                      </React.Fragment>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {EVENT_TYPES.map((evt) => (
                    <tr key={evt.key} style={{ borderBottom: "1px solid var(--color-border)" }}>
                      <td style={{ ...tdStyle, maxWidth: 200 }}>
                        <span style={{ fontWeight: 500 }}>{evt.label}</span>
                        <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>{evt.description}</div>
                      </td>
                      {CHANNELS.map((ch) => {
                        const key = prefKey(evt.key, ch.key);
                        const pref = prefMap.get(key);
                        const ts = testState.get(key);
                        return (
                          <React.Fragment key={ch.key}>
                            {/* Enable toggle */}
                            <td style={{ ...tdStyle, textAlign: "center", width: 60 }}>
                              <input
                                type="checkbox"
                                checked={!!pref?.enabled}
                                onChange={() => toggleEnabled(evt.key, ch.key)}
                              />
                            </td>
                            {/* Endpoint input */}
                            <td style={{ ...tdStyle, minWidth: 200 }}>
                              <input
                                type={ch.key === "email" ? "email" : "url"}
                                placeholder={ch.key === "email" ? "alerts@example.com" : "https://hooks.example.com/…"}
                                value={pref?.endpoint ?? ""}
                                onChange={(e) => setEndpoint(evt.key, ch.key, e.target.value)}
                                style={inputStyle}
                                disabled={!pref?.enabled}
                              />
                              {ts && (
                                <div style={{ fontSize: "0.75rem", marginTop: 2, color: ts.result?.startsWith("✅") ? "#060" : "#c00" }}>
                                  {ts.result}
                                </div>
                              )}
                            </td>
                            {/* Actions */}
                            <td style={{ ...tdStyle, width: 90 }}>
                              {ch.key === "webhook" && pref?.endpoint && (
                                <button
                                  onClick={() => handleWebhookTest(evt.key, ch.key)}
                                  disabled={ts?.loading}
                                  style={btnStyle}
                                  title="Send test POST"
                                >
                                  {ts?.loading ? "…" : "Test"}
                                </button>
                              )}
                              {pref?.id !== undefined && (
                                <button
                                  onClick={() => handleDelete(evt.key, ch.key)}
                                  style={{ ...btnStyle, marginLeft: 4, color: "#c00" }}
                                  title="Remove this subscription"
                                >
                                  ✕
                                </button>
                              )}
                            </td>
                          </React.Fragment>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
            <button
              onClick={handleSave}
              disabled={saving || loading}
              style={{
                background: "var(--color-primary, #667eea)",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                padding: "8px 20px",
                fontWeight: 600,
                cursor: saving ? "not-allowed" : "pointer",
                opacity: saving ? 0.7 : 1,
              }}
            >
              {saving ? "Saving…" : "Save Preferences"}
            </button>
          </div>
        </>
      )}

      {tab === "history" && (
        <>
          {histLoading && <p style={{ color: "var(--color-text-muted)" }}>Loading…</p>}
          {histError && (
            <div style={{ background: "#fee", color: "#c00", padding: "10px 14px", borderRadius: 6, marginBottom: 16, fontSize: "0.875rem" }}>
              {histError}
            </div>
          )}
          {!histLoading && history.length === 0 && (
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>No notifications sent yet.</p>
          )}
          {!histLoading && history.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
              <thead>
                <tr style={{ background: "var(--color-surface-alt, #f8f9fa)" }}>
                  <th style={thStyle}>Event</th>
                  <th style={thStyle}>Subject</th>
                  <th style={thStyle}>Status</th>
                  <th style={thStyle}>Sent At</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                    <td style={tdStyle}>{row.event_type}</td>
                    <td style={tdStyle}>{row.subject}</td>
                    <td style={tdStyle}>
                      <span style={{
                        padding: "2px 8px",
                        borderRadius: 4,
                        background: row.delivery_status === "sent" ? "#d4edda" : row.delivery_status === "failed" ? "#f8d7da" : "#e2e3e5",
                        color: row.delivery_status === "sent" ? "#155724" : row.delivery_status === "failed" ? "#721c24" : "#383d41",
                        fontSize: "0.75rem",
                      }}>
                        {row.delivery_status}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, color: "var(--color-text-muted)", fontSize: "0.8rem" }}>
                      {row.sent_at ? new Date(row.sent_at).toLocaleString() : row.created_at ? new Date(row.created_at).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Micro styles
// ---------------------------------------------------------------------------

const thStyle: React.CSSProperties = {
  padding: "8px 12px",
  textAlign: "left",
  fontWeight: 600,
  borderBottom: "1px solid var(--color-border)",
  color: "var(--color-text)",
};

const tdStyle: React.CSSProperties = {
  padding: "8px 12px",
  verticalAlign: "middle",
  color: "var(--color-text)",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "5px 8px",
  border: "1px solid var(--color-border)",
  borderRadius: 4,
  background: "var(--color-surface)",
  color: "var(--color-text)",
  fontSize: "0.82rem",
};

const btnStyle: React.CSSProperties = {
  padding: "3px 10px",
  border: "1px solid var(--color-border)",
  borderRadius: 4,
  background: "var(--color-surface)",
  color: "var(--color-text)",
  cursor: "pointer",
  fontSize: "0.8rem",
};
