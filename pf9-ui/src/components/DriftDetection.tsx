/**
 * Drift Detection Tab
 *
 * Surfaces field-level drift events emitted by the inventory sync engine
 * and lets operators acknowledge, filter, search, export and manage drift rules.
 *
 * Three sub-views (tabs inside the tab):
 *   1) Summary – card KPIs + 7-day trend
 *   2) Events  – filterable, paginated, selectable table + detail side-panel
 *   3) Rules   – toggle enable/disable, change severity
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE } from "../config";
import "../styles/DriftDetection.css";

// ─── Types ───────────────────────────────────────────────────────────────────

interface DriftSummary {
  totals: {
    total: number;
    unacknowledged: number;
    acknowledged: number;
    critical_open: number;
    warning_open: number;
    info_open: number;
  };
  by_severity: { severity: string; count: number }[];
  by_resource_type: { resource_type: string; count: number }[];
  trend_7d: { day: string; count: number }[];
}

interface DriftEvent {
  id: number;
  rule_id: number;
  resource_type: string;
  resource_id: string;
  resource_name: string;
  project_id: string | null;
  project_name: string | null;
  domain_id: string | null;
  domain_name: string | null;
  severity: string;
  field_changed: string;
  old_value: string | null;
  new_value: string | null;
  description: string;
  detected_at: string;
  acknowledged: boolean;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  acknowledge_note: string | null;
  rule_description?: string;
}

interface EventsResponse {
  events: DriftEvent[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

interface DriftRule {
  id: number;
  resource_type: string;
  field_name: string;
  severity: string;
  description: string;
  enabled: boolean;
  open_events: number;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getToken(): string | null {
  return localStorage.getItem("auth_token");
}

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(opts?.body ? { "Content-Type": "application/json" } : {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers: { ...headers, ...(opts?.headers || {}) } });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function fmtDateShort(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB") + " " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function truncate(s: string | null, max = 40): string {
  if (!s) return "—";
  return s.length > max ? s.slice(0, max) + "…" : s;
}

// ─── Resource type display labels ────────────────────────────────────────────
const RESOURCE_LABELS: Record<string, string> = {
  servers: "Servers",
  volumes: "Volumes",
  networks: "Networks",
  subnets: "Subnets",
  ports: "Ports",
  floating_ips: "Floating IPs",
  security_groups: "Security Groups",
  snapshots: "Snapshots",
  routers: "Routers",
};

// ═════════════════════════════════════════════════════════════════════════════
// Component
// ═════════════════════════════════════════════════════════════════════════════

interface DriftDetectionProps {
  selectedDomain?: string;   // "__ALL__" or a domain id
  selectedTenant?: string;   // "__ALL__" or a tenant/project id
}

export default function DriftDetection({ selectedDomain, selectedTenant }: DriftDetectionProps) {
  // ── Sub-tab state ──
  const [subTab, setSubTab] = useState<"events" | "rules">("events");

  // ── Summary ──
  const [summary, setSummary] = useState<DriftSummary | null>(null);

  // ── Events ──
  const [events, setEvents] = useState<DriftEvent[]>([]);
  const [eventsTotal, setEventsTotal] = useState(0);
  const [eventsPage, setEventsPage] = useState(1);
  const [eventsTotalPages, setEventsTotalPages] = useState(1);
  const [eventsLoading, setEventsLoading] = useState(false);

  // ── Filters ──
  const [filterResource, setFilterResource] = useState("");
  const [filterSeverity, setFilterSeverity] = useState("");
  const [filterAck, setFilterAck] = useState("");
  const [filterSearch, setFilterSearch] = useState("");
  const [filterDays, setFilterDays] = useState(30);
  const [sortBy, setSortBy] = useState("detected_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // ── Selection for bulk actions ──
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // ── Detail panel ──
  const [detailEvent, setDetailEvent] = useState<DriftEvent | null>(null);
  const [ackNote, setAckNote] = useState("");
  const [ackLoading, setAckLoading] = useState(false);

  // ── Rules ──
  const [rules, setRules] = useState<DriftRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(false);

  // ── Errors ──
  const [error, setError] = useState("");

  // ── Auto-refresh ──
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Derived global filters ──
  const globalDomain = selectedDomain && selectedDomain !== "__ALL__" ? selectedDomain : "";
  const globalProject = selectedTenant && selectedTenant !== "__ALL__" ? selectedTenant : "";

  // ════════════════════════════════════════════════════════════════════════
  // Data Fetching
  // ════════════════════════════════════════════════════════════════════════

  const fetchSummary = useCallback(async () => {
    try {
      const sp = new URLSearchParams();
      if (globalDomain) sp.set("domain_id", globalDomain);
      if (globalProject) sp.set("project_id", globalProject);
      const qs = sp.toString();
      const data = await apiFetch<DriftSummary>(`/drift/summary${qs ? "?" + qs : ""}`);
      setSummary(data);
    } catch (e: any) {
      console.error("Drift summary error:", e);
    }
  }, [globalDomain, globalProject]);

  const fetchEvents = useCallback(async (page = 1) => {
    setEventsLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", "50");
      params.set("sort_by", sortBy);
      params.set("sort_dir", sortDir);
      params.set("days", String(filterDays));
      if (globalDomain) params.set("domain_id", globalDomain);
      if (globalProject) params.set("project_id", globalProject);
      if (filterResource) params.set("resource_type", filterResource);
      if (filterSeverity) params.set("severity", filterSeverity);
      if (filterAck === "yes") params.set("acknowledged", "true");
      if (filterAck === "no") params.set("acknowledged", "false");
      if (filterSearch.trim()) params.set("search", filterSearch.trim());
      const data = await apiFetch<EventsResponse>(`/drift/events?${params}`);
      setEvents(data.events);
      setEventsTotal(data.total);
      setEventsPage(data.page);
      setEventsTotalPages(data.total_pages);
      setSelected(new Set());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setEventsLoading(false);
    }
  }, [sortBy, sortDir, filterResource, filterSeverity, filterAck, filterSearch, filterDays, globalDomain, globalProject]);

  const fetchRules = useCallback(async () => {
    setRulesLoading(true);
    try {
      const data = await apiFetch<{ rules: DriftRule[]; total: number }>("/drift/rules");
      setRules(data.rules);
    } catch (e: any) {
      console.error("Drift rules error:", e);
    } finally {
      setRulesLoading(false);
    }
  }, []);

  // Initial + auto-refresh
  useEffect(() => {
    fetchSummary();
    fetchEvents(1);
    fetchRules();
    intervalRef.current = setInterval(() => {
      fetchSummary();
      fetchEvents(eventsPage);
    }, 60_000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-fetch events when filters/sort change
  useEffect(() => {
    fetchEvents(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortBy, sortDir, filterResource, filterSeverity, filterAck, filterDays]);

  // Re-fetch when global domain/tenant selection changes
  useEffect(() => {
    fetchSummary();
    fetchEvents(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [globalDomain, globalProject]);

  // ════════════════════════════════════════════════════════════════════════
  // Actions
  // ════════════════════════════════════════════════════════════════════════

  async function acknowledgeOne(eventId: number) {
    setAckLoading(true);
    try {
      await apiFetch(`/drift/events/${eventId}/acknowledge`, {
        method: "PUT",
        body: JSON.stringify({ note: ackNote }),
      });
      setDetailEvent(null);
      setAckNote("");
      fetchEvents(eventsPage);
      fetchSummary();
    } catch (e: any) {
      alert("Acknowledge failed: " + e.message);
    } finally {
      setAckLoading(false);
    }
  }

  async function bulkAcknowledge() {
    if (selected.size === 0) return;
    if (!confirm(`Acknowledge ${selected.size} selected event(s)?`)) return;
    try {
      await apiFetch("/drift/events/bulk-acknowledge", {
        method: "PUT",
        body: JSON.stringify({ event_ids: Array.from(selected), note: "Bulk acknowledge" }),
      });
      setSelected(new Set());
      fetchEvents(eventsPage);
      fetchSummary();
    } catch (e: any) {
      alert("Bulk acknowledge failed: " + e.message);
    }
  }

  async function toggleRule(ruleId: number, enabled: boolean) {
    try {
      await apiFetch(`/drift/rules/${ruleId}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      setRules((prev) => prev.map((r) => (r.id === ruleId ? { ...r, enabled } : r)));
    } catch (e: any) {
      alert("Update rule failed: " + e.message);
    }
  }

  async function changeRuleSeverity(ruleId: number, severity: string) {
    try {
      await apiFetch(`/drift/rules/${ruleId}`, {
        method: "PUT",
        body: JSON.stringify({ severity }),
      });
      setRules((prev) => prev.map((r) => (r.id === ruleId ? { ...r, severity } : r)));
    } catch (e: any) {
      alert("Update severity failed: " + e.message);
    }
  }

  // ── CSV Export ──
  function exportCSV() {
    if (events.length === 0) return;
    const headers = [
      "ID", "Detected At", "Severity", "Resource Type", "Resource Name",
      "Field Changed", "Old Value", "New Value", "Description",
      "Acknowledged", "Acknowledged By", "Note",
    ];
    const rows = events.map((e) => [
      e.id, e.detected_at, e.severity, e.resource_type, e.resource_name,
      e.field_changed, e.old_value ?? "", e.new_value ?? "", e.description,
      e.acknowledged ? "Yes" : "No", e.acknowledged_by ?? "", e.acknowledge_note ?? "",
    ]);
    const csv = [headers, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `drift_events_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── Sort handler ──
  function handleSort(col: string) {
    if (sortBy === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortDir("desc");
    }
  }

  function sortIndicator(col: string) {
    if (sortBy !== col) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

  // ── Selection helpers ──
  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }
  function toggleSelectAll() {
    const unack = events.filter((e) => !e.acknowledged);
    if (selected.size === unack.length && unack.length > 0) {
      setSelected(new Set());
    } else {
      setSelected(new Set(unack.map((e) => e.id)));
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  // Render
  // ════════════════════════════════════════════════════════════════════════

  const trendMax = summary ? Math.max(...summary.trend_7d.map((d) => d.count), 1) : 1;

  return (
    <div className="drift-container">
      <h2>🔍 Drift Detection</h2>

      {/* ── Loading state ── */}
      {!summary && (
        <div className="drift-loading">Loading drift summary…</div>
      )}

      {/* ── Summary Cards ── */}
      {summary && (
        <>
          {/* ── All-clear banner when zero events ── */}
          {summary.totals.total === 0 && (
            <div className="drift-all-clear">
              <div className="drift-all-clear-icon">✅</div>
              <div className="drift-all-clear-text">
                <strong>No Configuration Drift Detected</strong>
                <p>
                  Your environment is stable. The drift engine compares resource fields (flavor, status, network, volume attachments, etc.)
                  across inventory syncs and will flag any unexpected changes here automatically.
                </p>
                <p style={{ fontSize: ".8rem", color: "var(--text-secondary, #64748b)", marginTop: 4 }}>
                  {rules.length > 0 ? `${rules.length} drift rules active` : "Loading rules…"} · Inventory syncs run every ~60 seconds
                </p>
              </div>
            </div>
          )}

          <div className="drift-summary-row">
            <div className="drift-summary-card">
              <div className="card-value">{summary.totals.total}</div>
              <div className="card-label">Total Events</div>
            </div>
            <div className="drift-summary-card">
              <div className="card-value">{summary.totals.unacknowledged}</div>
              <div className="card-label">Unacknowledged</div>
            </div>
            <div className="drift-summary-card critical">
              <div className="card-value">{summary.totals.critical_open}</div>
              <div className="card-label">Critical Open</div>
            </div>
            <div className="drift-summary-card warning">
              <div className="card-value">{summary.totals.warning_open}</div>
              <div className="card-label">Warning Open</div>
            </div>
            <div className="drift-summary-card info">
              <div className="card-value">{summary.totals.info_open}</div>
              <div className="card-label">Info Open</div>
            </div>
            <div className="drift-summary-card">
              <div className="card-value">{summary.totals.acknowledged}</div>
              <div className="card-label">Acknowledged</div>
            </div>
          </div>

          {/* ── 7-day Trend ── */}
          {summary.trend_7d.length > 0 && (
            <>
              <div style={{ fontSize: ".85rem", fontWeight: 600, marginBottom: 4, color: "var(--text-secondary, #64748b)" }}>
                7-Day Drift Trend
              </div>
              <div className="drift-trend">
                {summary.trend_7d.map((d) => (
                  <div
                    key={d.day}
                    className="drift-trend-bar"
                    style={{ height: `${Math.max((d.count / trendMax) * 100, 6)}%` }}
                    data-tip={`${d.day}: ${d.count}`}
                    title={`${d.day}: ${d.count}`}
                  />
                ))}
              </div>
              <div className="drift-trend-labels">
                <span>{summary.trend_7d[0]?.day}</span>
                <span>{summary.trend_7d[summary.trend_7d.length - 1]?.day}</span>
              </div>
            </>
          )}

          {/* ── By Resource Type ── */}
          {summary.by_resource_type.length > 0 && (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 20, marginTop: 8 }}>
              {summary.by_resource_type.map((r) => (
                <span
                  key={r.resource_type}
                  style={{
                    padding: "4px 12px", borderRadius: 20, fontSize: ".78rem", fontWeight: 600,
                    background: "var(--card-bg, #f1f5f9)", border: "1px solid var(--border-color, #e2e8f0)",
                    color: "var(--text-primary, #334155)", cursor: "pointer",
                  }}
                  onClick={() => { setFilterResource(r.resource_type); }}
                  title={`Filter by ${r.resource_type}`}
                >
                  {RESOURCE_LABELS[r.resource_type] || r.resource_type}: {r.count}
                </span>
              ))}
            </div>
          )}
        </>
      )}

      {/* ── Sub-tabs ── */}
      <div className="drift-tabs">
        <button className={`drift-tab-btn ${subTab === "events" ? "active" : ""}`} onClick={() => setSubTab("events")}>
          Events {eventsTotal > 0 && `(${eventsTotal})`}
        </button>
        <button className={`drift-tab-btn ${subTab === "rules" ? "active" : ""}`} onClick={() => { setSubTab("rules"); fetchRules(); }}>
          Rules ({rules.length})
        </button>
      </div>

      {/* ════════════════ EVENTS TAB ════════════════ */}
      {subTab === "events" && (
        <>
          {/* Toolbar */}
          <div className="drift-toolbar">
            <select value={filterResource} onChange={(e) => setFilterResource(e.target.value)}>
              <option value="">All Resources</option>
              {Object.entries(RESOURCE_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
            <select value={filterSeverity} onChange={(e) => setFilterSeverity(e.target.value)}>
              <option value="">All Severities</option>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
            <select value={filterAck} onChange={(e) => setFilterAck(e.target.value)}>
              <option value="">All Status</option>
              <option value="no">Open</option>
              <option value="yes">Acknowledged</option>
            </select>
            <select value={filterDays} onChange={(e) => setFilterDays(Number(e.target.value))}>
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
              <option value={365}>Last year</option>
            </select>
            <input
              type="text"
              placeholder="Search events…"
              value={filterSearch}
              onChange={(e) => setFilterSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && fetchEvents(1)}
              style={{ minWidth: 180 }}
            />
            <button className="drift-btn secondary" onClick={() => fetchEvents(1)}>🔄 Refresh</button>
            <button className="drift-btn secondary" onClick={exportCSV} disabled={events.length === 0}>📥 CSV</button>
            {selected.size > 0 && (
              <button className="drift-btn primary" onClick={bulkAcknowledge}>
                ✓ Acknowledge ({selected.size})
              </button>
            )}
          </div>

          {/* Error */}
          {error && <div className="drift-error">⚠ {error}</div>}

          {/* Loading */}
          {eventsLoading && <div className="drift-loading">Loading drift events…</div>}

          {/* Table */}
          {!eventsLoading && events.length === 0 && !error && (
            <div className="drift-empty">No drift events found for the selected filters.</div>
          )}
          {!eventsLoading && events.length > 0 && (
            <div className="drift-table-wrap">
              <table className="drift-table">
                <thead>
                  <tr>
                    <th style={{ width: 40 }}>
                      <input
                        type="checkbox"
                        checked={selected.size > 0 && selected.size === events.filter((e) => !e.acknowledged).length}
                        onChange={toggleSelectAll}
                      />
                    </th>
                    <th onClick={() => handleSort("detected_at")}>Detected{sortIndicator("detected_at")}</th>
                    <th onClick={() => handleSort("severity")}>Severity{sortIndicator("severity")}</th>
                    <th onClick={() => handleSort("resource_type")}>Resource{sortIndicator("resource_type")}</th>
                    <th onClick={() => handleSort("resource_name")}>Name{sortIndicator("resource_name")}</th>
                    <th onClick={() => handleSort("field_changed")}>Field{sortIndicator("field_changed")}</th>
                    <th>Change</th>
                    <th onClick={() => handleSort("acknowledged")}>Status{sortIndicator("acknowledged")}</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((ev) => (
                    <tr key={ev.id} className={ev.acknowledged ? "ack-row" : ""}>
                      <td>
                        {!ev.acknowledged && (
                          <input
                            type="checkbox"
                            checked={selected.has(ev.id)}
                            onChange={() => toggleSelect(ev.id)}
                          />
                        )}
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>{fmtDateShort(ev.detected_at)}</td>
                      <td><span className={`drift-severity ${ev.severity}`}>{ev.severity}</span></td>
                      <td>{RESOURCE_LABELS[ev.resource_type] || ev.resource_type}</td>
                      <td title={ev.resource_name}>{truncate(ev.resource_name, 28)}</td>
                      <td><code style={{ fontSize: ".8rem" }}>{ev.field_changed}</code></td>
                      <td>
                        <span className="drift-change">
                          <span className="old">{truncate(ev.old_value, 20)}</span>
                          <span className="arrow">→</span>
                          <span className="new">{truncate(ev.new_value, 20)}</span>
                        </span>
                      </td>
                      <td>
                        {ev.acknowledged ? (
                          <span style={{ color: "#22c55e", fontWeight: 600, fontSize: ".8rem" }}>✓ Ack</span>
                        ) : (
                          <span style={{ color: "#f59e0b", fontWeight: 600, fontSize: ".8rem" }}>● Open</span>
                        )}
                      </td>
                      <td>
                        <button
                          className="drift-btn secondary"
                          style={{ padding: "4px 10px", fontSize: ".78rem" }}
                          onClick={() => { setDetailEvent(ev); setAckNote(""); }}
                        >
                          Details
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          {eventsTotalPages > 1 && (
            <div className="drift-pagination">
              <span>
                Page {eventsPage} of {eventsTotalPages} · {eventsTotal} events
              </span>
              <div style={{ display: "flex", gap: 6 }}>
                <button disabled={eventsPage <= 1} onClick={() => fetchEvents(eventsPage - 1)}>← Prev</button>
                <button disabled={eventsPage >= eventsTotalPages} onClick={() => fetchEvents(eventsPage + 1)}>Next →</button>
              </div>
            </div>
          )}
        </>
      )}

      {/* ════════════════ RULES TAB ════════════════ */}
      {subTab === "rules" && (
        <>
          {rulesLoading && <div className="drift-loading">Loading rules…</div>}
          {!rulesLoading && rules.length === 0 && <div className="drift-empty">No drift rules configured.</div>}
          {!rulesLoading && rules.length > 0 && (
            <div className="drift-table-wrap">
              <table className="drift-rules-table">
                <thead>
                  <tr>
                    <th>Enabled</th>
                    <th>Resource Type</th>
                    <th>Field</th>
                    <th>Severity</th>
                    <th>Description</th>
                    <th>Open Events</th>
                  </tr>
                </thead>
                <tbody>
                  {rules.map((r) => (
                    <tr key={r.id} style={{ opacity: r.enabled ? 1 : 0.5 }}>
                      <td>
                        <label className="drift-toggle">
                          <input
                            type="checkbox"
                            checked={r.enabled}
                            onChange={(e) => toggleRule(r.id, e.target.checked)}
                          />
                          <span className="slider" />
                        </label>
                      </td>
                      <td>{RESOURCE_LABELS[r.resource_type] || r.resource_type}</td>
                      <td><code style={{ fontSize: ".82rem" }}>{r.field_name}</code></td>
                      <td>
                        <select
                          className="drift-sev-select"
                          value={r.severity}
                          onChange={(e) => changeRuleSeverity(r.id, e.target.value)}
                        >
                          <option value="critical">Critical</option>
                          <option value="warning">Warning</option>
                          <option value="info">Info</option>
                        </select>
                      </td>
                      <td>{r.description}</td>
                      <td style={{ textAlign: "center", fontWeight: 600 }}>
                        {r.open_events > 0 ? (
                          <span style={{ color: "#ef4444" }}>{r.open_events}</span>
                        ) : (
                          <span style={{ color: "#94a3b8" }}>0</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ════════════════ DETAIL SIDE-PANEL ════════════════ */}
      {detailEvent && (
        <div className="drift-detail-overlay" onClick={() => setDetailEvent(null)}>
          <div className="drift-detail-panel" onClick={(e) => e.stopPropagation()}>
            <h3>Drift Event #{detailEvent.id}</h3>
            <div className="drift-detail-row">
              <span className="label">Severity</span>
              <span className="value"><span className={`drift-severity ${detailEvent.severity}`}>{detailEvent.severity}</span></span>
            </div>
            <div className="drift-detail-row">
              <span className="label">Resource Type</span>
              <span className="value">{RESOURCE_LABELS[detailEvent.resource_type] || detailEvent.resource_type}</span>
            </div>
            <div className="drift-detail-row">
              <span className="label">Resource</span>
              <span className="value">{detailEvent.resource_name} <span style={{ opacity: .5, fontSize: ".75rem" }}>({detailEvent.resource_id})</span></span>
            </div>
            {detailEvent.project_name && (
              <div className="drift-detail-row">
                <span className="label">Project</span>
                <span className="value">{detailEvent.project_name}</span>
              </div>
            )}
            {detailEvent.domain_name && (
              <div className="drift-detail-row">
                <span className="label">Domain</span>
                <span className="value">{detailEvent.domain_name}</span>
              </div>
            )}
            <div className="drift-detail-row">
              <span className="label">Field Changed</span>
              <span className="value"><code>{detailEvent.field_changed}</code></span>
            </div>
            <div className="drift-detail-row">
              <span className="label">Old Value</span>
              <span className="value drift-change"><span className="old">{detailEvent.old_value ?? "—"}</span></span>
            </div>
            <div className="drift-detail-row">
              <span className="label">New Value</span>
              <span className="value drift-change"><span className="new">{detailEvent.new_value ?? "—"}</span></span>
            </div>
            <div className="drift-detail-row">
              <span className="label">Description</span>
              <span className="value">{detailEvent.description}</span>
            </div>
            {detailEvent.rule_description && detailEvent.rule_description !== detailEvent.description && (
              <div className="drift-detail-row">
                <span className="label">Rule</span>
                <span className="value">{detailEvent.rule_description}</span>
              </div>
            )}
            <div className="drift-detail-row">
              <span className="label">Detected At</span>
              <span className="value">{fmtDate(detailEvent.detected_at)}</span>
            </div>
            <div className="drift-detail-row">
              <span className="label">Status</span>
              <span className="value">
                {detailEvent.acknowledged ? (
                  <>
                    <span style={{ color: "#22c55e", fontWeight: 600 }}>Acknowledged</span>
                    {detailEvent.acknowledged_by && <> by {detailEvent.acknowledged_by}</>}
                    {detailEvent.acknowledged_at && <> at {fmtDate(detailEvent.acknowledged_at)}</>}
                    {detailEvent.acknowledge_note && <div style={{ marginTop: 4, fontStyle: "italic" }}>{detailEvent.acknowledge_note}</div>}
                  </>
                ) : (
                  <span style={{ color: "#f59e0b", fontWeight: 600 }}>Open</span>
                )}
              </span>
            </div>

            {/* Acknowledge form */}
            {!detailEvent.acknowledged && (
              <>
                <input
                  className="drift-ack-input"
                  placeholder="Acknowledge note (optional)…"
                  value={ackNote}
                  onChange={(e) => setAckNote(e.target.value)}
                />
                <button
                  className="drift-btn primary"
                  style={{ width: "100%" }}
                  disabled={ackLoading}
                  onClick={() => acknowledgeOne(detailEvent.id)}
                >
                  {ackLoading ? "Acknowledging…" : "✓ Acknowledge"}
                </button>
              </>
            )}

            <button
              className="drift-btn secondary"
              style={{ width: "100%", marginTop: 10 }}
              onClick={() => setDetailEvent(null)}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
