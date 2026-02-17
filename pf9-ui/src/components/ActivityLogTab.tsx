import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";

/* ===================================================================
   ActivityLogTab
   ===================================================================
   Central activity log for all provisioning & domain management
   actions: create, delete, disable, enable, provision.
   
   Shows a paginated, filterable table with action details,
   actor, resource info, result status, and timestamp.
*/

interface ActivityEntry {
  id: number;
  timestamp: string;
  actor: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  resource_name: string | null;
  domain_id: string | null;
  domain_name: string | null;
  details: Record<string, any>;
  ip_address: string | null;
  result: string;
  error_message: string | null;
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("auth_token");
  return token
    ? { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }
    : { "Content-Type": "application/json" };
}

const ACTIONS = ["provision", "delete", "disable", "enable"];
const RESOURCE_TYPES = ["domain", "tenant", "server", "volume", "network", "router", "floating_ip", "security_group", "user", "project"];
const RESULTS = ["success", "failure"];

const ActivityLogTab: React.FC = () => {
  const [logs, setLogs] = useState<ActivityEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [actionFilter, setActionFilter] = useState("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [resultFilter, setResultFilter] = useState("");

  // Pagination
  const [page, setPage] = useState(0);
  const limit = 30;

  // Expanded detail row
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      params.set("offset", String(page * limit));
      if (actionFilter) params.set("action", actionFilter);
      if (resourceTypeFilter) params.set("resource_type", resourceTypeFilter);
      if (actorFilter) params.set("actor", actorFilter);
      if (resultFilter) params.set("result", resultFilter);

      const res = await fetch(`${API_BASE}/api/provisioning/activity-log?${params}`, {
        headers: authHeaders(),
      });
      if (!res.ok) {
        if (res.status === 403) throw new Error("Access denied. Admin permissions required.");
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      setLogs(data.logs || []);
      setTotal(data.total || 0);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [page, actionFilter, resourceTypeFilter, actorFilter, resultFilter]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  // Auto-refresh every 10s
  useEffect(() => {
    const interval = setInterval(fetchLogs, 10000);
    return () => clearInterval(interval);
  }, [fetchLogs]);

  const totalPages = Math.ceil(total / limit);

  const actionIcon = (action: string) => {
    switch (action) {
      case "provision": return "🚀";
      case "delete": return "🗑️";
      case "disable": return "⏸️";
      case "enable": return "▶️";
      default: return "📝";
    }
  };

  const resultBadge = (result: string) => {
    const isSuccess = result === "success";
    return (
      <span style={{
        padding: "2px 10px", borderRadius: 12, fontSize: 11, fontWeight: 600,
        background: isSuccess ? "#c6f6d5" : "#fed7d7",
        color: isSuccess ? "#276749" : "#9b2c2c",
      }}>
        {isSuccess ? "✅ Success" : "❌ Failed"}
      </span>
    );
  };

  const actionBadge = (action: string) => {
    const colorMap: Record<string, { bg: string; color: string }> = {
      provision: { bg: "#c6f6d5", color: "#276749" },
      delete: { bg: "#fed7d7", color: "#9b2c2c" },
      disable: { bg: "#fef3c7", color: "#92400e" },
      enable: { bg: "#dbeafe", color: "#1e40af" },
    };
    const c = colorMap[action] || { bg: "#e2e8f0", color: "#4a5568" };
    return (
      <span style={{
        padding: "2px 10px", borderRadius: 12, fontSize: 11, fontWeight: 600,
        background: c.bg, color: c.color,
      }}>
        {actionIcon(action)} {action}
      </span>
    );
  };

  return (
    <div style={{ padding: "0 8px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div>
          <h3 style={{ margin: 0, color: "var(--pf9-text, #1a365d)" }}>📋 Activity Log</h3>
          <p style={{ margin: "4px 0 0 0", fontSize: 12, color: "#718096" }}>
            Central audit trail for all provisioning and domain management actions
          </p>
        </div>
        <button onClick={fetchLogs} style={{
          padding: "6px 16px", borderRadius: 6, border: "1px solid var(--pf9-border, #e2e8f0)",
          background: "var(--pf9-bg-card, #fff)", cursor: "pointer", fontSize: 13,
          color: "var(--pf9-text, #2d3748)",
        }}>🔄 Refresh</button>
      </div>

      {/* Filters */}
      <div style={{
        display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16, padding: 12,
        background: "var(--pf9-bg-card, #f7fafc)", borderRadius: 8,
        border: "1px solid var(--pf9-border, #e2e8f0)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#718096" }}>Action:</label>
          <select value={actionFilter} onChange={(e) => { setActionFilter(e.target.value); setPage(0); }}
            style={{ padding: "4px 8px", borderRadius: 4, fontSize: 12, border: "1px solid #e2e8f0" }}>
            <option value="">All</option>
            {ACTIONS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#718096" }}>Resource:</label>
          <select value={resourceTypeFilter} onChange={(e) => { setResourceTypeFilter(e.target.value); setPage(0); }}
            style={{ padding: "4px 8px", borderRadius: 4, fontSize: 12, border: "1px solid #e2e8f0" }}>
            <option value="">All</option>
            {RESOURCE_TYPES.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#718096" }}>Actor:</label>
          <input
            type="text" value={actorFilter}
            onChange={(e) => { setActorFilter(e.target.value); setPage(0); }}
            placeholder="Filter by user..."
            style={{ padding: "4px 8px", borderRadius: 4, fontSize: 12, border: "1px solid #e2e8f0", width: 120 }}
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "#718096" }}>Result:</label>
          <select value={resultFilter} onChange={(e) => { setResultFilter(e.target.value); setPage(0); }}
            style={{ padding: "4px 8px", borderRadius: 4, fontSize: 12, border: "1px solid #e2e8f0" }}>
            <option value="">All</option>
            {RESULTS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        {(actionFilter || resourceTypeFilter || actorFilter || resultFilter) && (
          <button onClick={() => { setActionFilter(""); setResourceTypeFilter(""); setActorFilter(""); setResultFilter(""); setPage(0); }}
            style={{ padding: "4px 12px", borderRadius: 4, border: "none", background: "#e2e8f0", cursor: "pointer", fontSize: 12 }}>
            Clear Filters
          </button>
        )}
      </div>

      {error && (
        <div style={{
          padding: 12, borderRadius: 6, background: "#fff5f5", border: "1px solid #fed7d7",
          color: "#c53030", fontSize: 13, marginBottom: 16,
        }}>
          ⚠️ {error}
        </div>
      )}

      {loading && logs.length === 0 ? (
        <div style={{ textAlign: "center", padding: 40, color: "#a0aec0" }}>Loading activity log...</div>
      ) : logs.length === 0 ? (
        <div style={{ textAlign: "center", padding: 40, color: "#a0aec0" }}>
          No activity log entries found. Actions from provisioning and domain management will appear here.
        </div>
      ) : (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "var(--pf9-bg-header, #edf2f7)", textAlign: "left" }}>
                  <th style={thStyle}>Timestamp</th>
                  <th style={thStyle}>Actor</th>
                  <th style={thStyle}>Action</th>
                  <th style={thStyle}>Resource</th>
                  <th style={thStyle}>Name</th>
                  <th style={thStyle}>Domain</th>
                  <th style={thStyle}>Result</th>
                  <th style={thStyle}>IP</th>
                  <th style={thStyle}></th>
                </tr>
              </thead>
              <tbody>
                {logs.map((entry) => (
                  <React.Fragment key={entry.id}>
                    <tr style={{
                      borderBottom: "1px solid var(--pf9-border, #e2e8f0)",
                      background: entry.result === "failure" ? "#fff5f520" : "transparent",
                    }}>
                      <td style={tdStyle}>
                        <span style={{ fontSize: 12 }}>
                          {new Date(entry.timestamp).toLocaleString()}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        <span style={{ fontWeight: 600 }}>{entry.actor}</span>
                      </td>
                      <td style={tdStyle}>{actionBadge(entry.action)}</td>
                      <td style={tdStyle}>
                        <span style={{
                          padding: "1px 8px", borderRadius: 4, fontSize: 11,
                          background: "#edf2f7", color: "#4a5568",
                        }}>
                          {entry.resource_type}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        {entry.resource_name || "—"}
                        {entry.resource_id && (
                          <div style={{ fontSize: 10, color: "#cbd5e0", fontFamily: "monospace" }}>
                            {entry.resource_id.substring(0, 12)}
                          </div>
                        )}
                      </td>
                      <td style={tdStyle}>
                        <span style={{ fontSize: 12 }}>{entry.domain_name || "—"}</span>
                      </td>
                      <td style={tdStyle}>{resultBadge(entry.result)}</td>
                      <td style={tdStyle}>
                        <span style={{ fontSize: 11, color: "#a0aec0", fontFamily: "monospace" }}>
                          {entry.ip_address || "—"}
                        </span>
                      </td>
                      <td style={tdStyle}>
                        <button
                          onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                          style={{
                            background: "none", border: "none", cursor: "pointer", fontSize: 14,
                            color: "var(--pf9-text-secondary, #718096)",
                          }}
                          title="Show details"
                        >
                          {expandedId === entry.id ? "▲" : "▼"}
                        </button>
                      </td>
                    </tr>
                    {expandedId === entry.id && (
                      <tr>
                        <td colSpan={9} style={{ padding: "8px 16px", background: "var(--pf9-bg-card, #f7fafc)" }}>
                          <div style={{ fontSize: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                            {entry.resource_id && (
                              <div><strong>Resource ID:</strong> <code style={{ fontSize: 11 }}>{entry.resource_id}</code></div>
                            )}
                            {entry.domain_id && (
                              <div><strong>Domain ID:</strong> <code style={{ fontSize: 11 }}>{entry.domain_id}</code></div>
                            )}
                            {entry.error_message && (
                              <div style={{ gridColumn: "1 / -1", color: "#c53030" }}>
                                <strong>Error:</strong> {entry.error_message}
                              </div>
                            )}
                            {entry.details && Object.keys(entry.details).length > 0 && (
                              <div style={{ gridColumn: "1 / -1" }}>
                                <strong>Details:</strong>
                                <pre style={{
                                  background: "#1a202c", color: "#e2e8f0", padding: 8, borderRadius: 4,
                                  fontSize: 11, overflow: "auto", maxHeight: 200, marginTop: 4,
                                }}>
                                  {JSON.stringify(entry.details, null, 2)}
                                </pre>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            marginTop: 12, padding: "8px 0",
          }}>
            <span style={{ fontSize: 12, color: "#718096" }}>
              Showing {page * limit + 1}–{Math.min((page + 1) * limit, total)} of {total} entries
            </span>
            <div style={{ display: "flex", gap: 4 }}>
              <button
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
                style={{
                  padding: "4px 12px", borderRadius: 4, fontSize: 12,
                  border: "1px solid #e2e8f0", background: page === 0 ? "#edf2f7" : "#fff",
                  cursor: page === 0 ? "default" : "pointer",
                }}
              >
                ← Prev
              </button>
              <span style={{ padding: "4px 8px", fontSize: 12, color: "#718096" }}>
                Page {page + 1} / {totalPages || 1}
              </span>
              <button
                onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                disabled={page >= totalPages - 1}
                style={{
                  padding: "4px 12px", borderRadius: 4, fontSize: 12,
                  border: "1px solid #e2e8f0", background: page >= totalPages - 1 ? "#edf2f7" : "#fff",
                  cursor: page >= totalPages - 1 ? "default" : "pointer",
                }}
              >
                Next →
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const thStyle: React.CSSProperties = {
  padding: "10px 12px", fontWeight: 600, borderBottom: "2px solid var(--pf9-border, #e2e8f0)",
  fontSize: 12,
};
const tdStyle: React.CSSProperties = { padding: "8px 12px" };

export default ActivityLogTab;
