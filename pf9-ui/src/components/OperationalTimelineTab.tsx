/*
 * OperationalTimelineTab.tsx — Operational Event Timeline
 * ========================================================
 * Three modes:
 *   • Tenant   — full event chain for a selected domain
 *   • Resource — events for a specific entity (type + id)
 *   • Global   — rolling cross-region, cross-tenant feed (admin+)
 *
 * v1.96.3
 */
import React, { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../lib/api";
import "../styles/OperationalTimelineTab.css";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TimelineEvent {
  id: number;
  event_id: string;
  occurred_at: string;
  event_type: string;
  category: string;
  severity: string;
  title: string;
  description?: string;
  entity_type: string;
  entity_id: string;
  entity_name?: string;
  domain_id?: string;
  domain_name?: string;
  project_id?: string;
  project_name?: string;
  region_id: string;
  source: string;
  actor: string;
  metadata: Record<string, unknown>;
  visibility: string;
}

interface TimelineResponse {
  events: TimelineEvent[];
  total: number;
  has_more: boolean;
}

interface TimelineStats {
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
  total: number;
}

interface Domain {
  domain_id: string;
  domain_name: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CATEGORY_META: Record<string, { icon: string; color: string; label: string }> = {
  monitoring:   { icon: "📊", color: "#f97316", label: "Monitoring" },
  provisioning: { icon: "🚀", color: "#2563eb", label: "Provisioning" },
  backup:       { icon: "💾", color: "#16a34a", label: "Backup" },
  snapshot:     { icon: "📸", color: "#0d9488", label: "Snapshot" },
  sla:          { icon: "📋", color: "#dc2626", label: "SLA" },
  billing:      { icon: "💰", color: "#7c3aed", label: "Billing" },
  security:     { icon: "🔒", color: "#991b1b", label: "Security" },
  ticket:       { icon: "🎫", color: "#0ea5e9", label: "Ticket" },
  intelligence: { icon: "🧠", color: "#4f46e5", label: "Intelligence" },
  runbook:      { icon: "📘", color: "#475569", label: "Runbook" },
  system:       { icon: "⚙️", color: "#6b7280", label: "System" },
};

const SEVERITY_META: Record<string, { color: string; label: string }> = {
  info:     { color: "#6b7280", label: "Info" },
  warning:  { color: "#d97706", label: "Warning" },
  critical: { color: "#dc2626", label: "Critical" },
};

const TIME_RANGES = [
  { label: "2h",  value: "2h",  hours: 2 },
  { label: "6h",  value: "6h",  hours: 6 },
  { label: "24h", value: "24h", hours: 24 },
  { label: "7d",  value: "7d",  hours: 168 },
  { label: "30d", value: "30d", hours: 720 },
];

const ALL_CATEGORIES = Object.keys(CATEGORY_META);
const LIMIT = 100;

type Mode = "tenant" | "resource" | "global";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

function fmtTs(iso: string): string {
  return new Date(iso).toLocaleString();
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  userRole: string;
  /** Optional: pre-select a mode when opened from another component */
  initialMode?: Mode;
  initialDomainId?: string;
  initialEntityType?: string;
  initialEntityId?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const OperationalTimelineTab: React.FC<Props> = ({
  userRole,
  initialMode,
  initialDomainId,
  initialEntityType,
  initialEntityId,
}) => {
  const isAdmin = ["admin", "superadmin"].includes(userRole);
  const isTechnical = ["technical", "admin", "superadmin"].includes(userRole);

  // ── Mode & filter state ──────────────────────────────────────────────────
  const [mode, setMode] = useState<Mode>(initialMode ?? "tenant");
  const [timeRange, setTimeRange] = useState("24h");
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [severity, setSeverity] = useState("");
  const [search, setSearch] = useState("");

  // Tenant mode
  const [domains, setDomains] = useState<Domain[]>([]);
  const [domainId, setDomainId] = useState(initialDomainId ?? "");

  // Resource mode
  const [entityType, setEntityType] = useState(initialEntityType ?? "vm");
  const [entityId, setEntityId] = useState(initialEntityId ?? "");
  const [entityIdInput, setEntityIdInput] = useState(initialEntityId ?? "");

  // Data state
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [stats, setStats] = useState<TimelineStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Expand/collapse per event id
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  // ── Domain list ──────────────────────────────────────────────────────────
  useEffect(() => {
    apiFetch<{ items: Domain[] }>("/domains")
      .then(r => setDomains(r.items ?? []))
      .catch(() => { /* non-fatal */ });
  }, []);

  // ── Build query params ───────────────────────────────────────────────────
  const buildParams = useCallback((offsetVal: number): URLSearchParams => {
    const hours = TIME_RANGES.find(r => r.value === timeRange)?.hours ?? 24;
    const from = new Date(Date.now() - hours * 3_600_000).toISOString();
    const p = new URLSearchParams({ from, limit: String(LIMIT), offset: String(offsetVal) });
    if (mode === "tenant" && domainId) p.set("domain_id", domainId);
    if (mode === "resource" && entityId) {
      p.set("entity_type", entityType);
      p.set("entity_id", entityId);
    }
    if (selectedCategories.length > 0) p.set("category", selectedCategories.join(","));
    if (severity) p.set("severity", severity);
    return p;
  }, [mode, timeRange, domainId, entityType, entityId, selectedCategories, severity]);

  // ── Initial load ─────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    if (mode === "tenant" && !domainId) { setEvents([]); setStats(null); setTotal(0); return; }
    if (mode === "resource" && !entityId) { setEvents([]); setStats(null); setTotal(0); return; }

    setLoading(true);
    setError(null);
    try {
      const params = buildParams(0);
      const [tlResp, stResp] = await Promise.all([
        apiFetch<TimelineResponse>(`/api/timeline?${params}`),
        apiFetch<TimelineStats>(`/api/timeline/stats?${params}`),
      ]);
      setEvents(tlResp.events);
      setTotal(tlResp.total);
      setHasMore(tlResp.has_more);
      setStats(stResp);
      setOffset(tlResp.events.length);
    } catch (e: any) {
      setError(e.message ?? "Failed to load timeline");
    } finally {
      setLoading(false);
    }
  }, [buildParams, mode, domainId, entityId]);

  useEffect(() => { load(); }, [load]);

  // ── Load more ────────────────────────────────────────────────────────────
  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const resp = await apiFetch<TimelineResponse>(`/api/timeline?${buildParams(offset)}`);
      setEvents(prev => [...prev, ...resp.events]);
      setHasMore(resp.has_more);
      setOffset(prev => prev + resp.events.length);
    } catch {
      /* silent */
    } finally {
      setLoadingMore(false);
    }
  };

  // ── Handlers ─────────────────────────────────────────────────────────────
  const toggleCategory = (cat: string) => {
    setSelectedCategories(prev =>
      prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]
    );
  };

  const toggleExpand = (id: number) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const switchMode = (m: Mode) => {
    setMode(m);
    setEvents([]);
    setStats(null);
    setTotal(0);
    setExpanded(new Set());
  };

  // ── Visible categories (hide restricted ones by role) ────────────────────
  const visibleCategories = ALL_CATEGORIES.filter(cat => {
    if (cat === "security") return isAdmin;
    if (cat === "billing") return isTechnical;
    return true;
  });

  // ── Client-side text filter ──────────────────────────────────────────────
  const filteredEvents = search.trim()
    ? events.filter(e =>
        e.title.toLowerCase().includes(search.toLowerCase()) ||
        (e.description ?? "").toLowerCase().includes(search.toLowerCase())
      )
    : events;

  const needsContext = (mode === "tenant" && !domainId) || (mode === "resource" && !entityId);

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="otl-root">

      {/* Header */}
      <div className="otl-header">
        <div className="otl-header-left">
          <h2 className="otl-title">Operational Event Timeline</h2>
          <p className="otl-subtitle">
            Unified history of infrastructure events across your environment
          </p>
        </div>
      </div>

      {/* Mode switcher */}
      <div className="otl-mode-bar">
        {(["tenant", "resource", "global"] as Mode[]).map(m => (
          <button
            key={m}
            className={`otl-mode-btn${mode === m ? " active" : ""}`}
            onClick={() => switchMode(m)}
          >
            {m === "tenant" ? "🏢 Tenant" : m === "resource" ? "📦 Resource" : "🌐 Global"}
          </button>
        ))}
        {stats != null && (
          <span className="otl-total-badge">
            {stats.total.toLocaleString()} event{stats.total !== 1 ? "s" : ""} in window
          </span>
        )}
      </div>

      {/* Tenant context selector */}
      {mode === "tenant" && (
        <div className="otl-context-bar">
          <label className="otl-label">Tenant (domain)</label>
          <select
            className="otl-select"
            value={domainId}
            onChange={e => { setDomainId(e.target.value); setEvents([]); setStats(null); }}
          >
            <option value="">— select a tenant —</option>
            {domains.map(d => (
              <option key={d.domain_id} value={d.domain_id}>{d.domain_name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Resource context selector */}
      {mode === "resource" && (
        <div className="otl-context-bar">
          <label className="otl-label">Entity type</label>
          <select
            className="otl-select"
            value={entityType}
            onChange={e => { setEntityType(e.target.value); }}
            style={{ minWidth: 120 }}
          >
            {["vm", "volume", "network", "tenant", "host", "snapshot", "backup", "ticket", "user"].map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <label className="otl-label">Entity ID / name</label>
          <input
            className="otl-input"
            placeholder="UUID or name"
            value={entityIdInput}
            onChange={e => setEntityIdInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter") { setEntityId(entityIdInput); setEvents([]); setStats(null); }
            }}
          />
          <button
            className="otl-btn otl-btn-primary"
            onClick={() => { setEntityId(entityIdInput); setEvents([]); setStats(null); }}
          >
            Search
          </button>
        </div>
      )}

      {/* Filter bar */}
      <div className="otl-filter-bar">
        <div className="otl-filter-group">
          <span className="otl-filter-label">Range</span>
          {TIME_RANGES.map(r => (
            <button
              key={r.value}
              className={`otl-range-btn${timeRange === r.value ? " active" : ""}`}
              onClick={() => setTimeRange(r.value)}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className="otl-filter-group">
          <span className="otl-filter-label">Severity</span>
          <select
            className="otl-select-sm"
            value={severity}
            onChange={e => setSeverity(e.target.value)}
          >
            <option value="">All</option>
            <option value="warning">Warning+</option>
            <option value="critical">Critical only</option>
          </select>
        </div>
        <div className="otl-filter-group otl-filter-search">
          <input
            className="otl-input"
            placeholder="Search events…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Category chips */}
      <div className="otl-category-bar">
        <span className="otl-filter-label">Categories</span>
        <button
          className={`otl-cat-chip${selectedCategories.length === 0 ? " active" : ""}`}
          onClick={() => setSelectedCategories([])}
        >
          All
        </button>
        {visibleCategories.map(cat => {
          const m = CATEGORY_META[cat];
          const active = selectedCategories.includes(cat);
          return (
            <button
              key={cat}
              className={`otl-cat-chip${active ? " active" : ""}`}
              style={active ? { borderColor: m.color, background: m.color + "22", color: m.color } : {}}
              onClick={() => toggleCategory(cat)}
            >
              {m.icon} {m.label}
            </button>
          );
        })}
      </div>

      {/* Stats strip */}
      {stats != null && stats.total > 0 && (
        <div className="otl-stats-strip">
          {(["critical", "warning", "info"] as const).map(sev => {
            const count = stats.by_severity[sev] ?? 0;
            if (!count) return null;
            return (
              <span key={sev} className="otl-stat-pill" style={{ borderColor: SEVERITY_META[sev].color }}>
                <span style={{ color: SEVERITY_META[sev].color }}>{SEVERITY_META[sev].label}</span>
                {" "}{count}
              </span>
            );
          })}
          <span className="otl-stat-sep">|</span>
          {Object.entries(stats.by_category)
            .filter(([, v]) => v > 0)
            .sort(([, a], [, b]) => b - a)
            .slice(0, 7)
            .map(([cat, count]) => (
              <span key={cat} className="otl-stat-pill">
                {CATEGORY_META[cat]?.icon ?? "◦"} {count}
              </span>
            ))
          }
        </div>
      )}

      {/* Content */}
      <div className="otl-content">

        {loading && (
          <div className="otl-loading">
            <div className="otl-spinner" />
            <span>Loading events…</span>
          </div>
        )}

        {!loading && error && (
          <div className="otl-error">
            <span>⚠️ {error}</span>
            <button className="otl-btn otl-btn-secondary" onClick={load}>Retry</button>
          </div>
        )}

        {!loading && !error && mode === "tenant" && !domainId && (
          <div className="otl-empty">
            <div className="otl-empty-icon">🏢</div>
            <p>Select a tenant above to view its event timeline.</p>
          </div>
        )}

        {!loading && !error && mode === "resource" && !entityId && (
          <div className="otl-empty">
            <div className="otl-empty-icon">📦</div>
            <p>Enter an entity type and ID above, then click Search.</p>
          </div>
        )}

        {!loading && !error && !needsContext && filteredEvents.length === 0 && (
          <div className="otl-empty">
            <div className="otl-empty-icon">🕐</div>
            <p>No events in this time range. Try expanding the window or changing filters.</p>
          </div>
        )}

        {/* Timeline */}
        {filteredEvents.length > 0 && (
          <div className="otl-timeline">
            {filteredEvents.map(ev => {
              const catMeta = CATEGORY_META[ev.category] ?? { icon: "◦", color: "#888", label: ev.category };
              const sevMeta = SEVERITY_META[ev.severity] ?? { color: "#888", label: ev.severity };
              const isExpanded = expanded.has(ev.id);
              const hasDetail = !!(ev.description || Object.keys(ev.metadata ?? {}).length > 0);

              return (
                <div key={ev.id} className={`otl-event otl-event-${ev.severity}`}>
                  <div className="otl-event-stripe" style={{ background: catMeta.color }} />
                  <div className="otl-event-icon" title={catMeta.label}>{catMeta.icon}</div>
                  <div className="otl-event-body">
                    <div className="otl-event-header">
                      <span className="otl-event-title" title={ev.title}>{ev.title}</span>
                      <span
                        className="otl-sev-badge"
                        style={{
                          background: sevMeta.color + "22",
                          color: sevMeta.color,
                          borderColor: sevMeta.color,
                        }}
                      >
                        {sevMeta.label}
                      </span>
                    </div>
                    <div className="otl-event-meta">
                      <span className="otl-event-time" title={fmtTs(ev.occurred_at)}>
                        {timeAgo(ev.occurred_at)}
                      </span>
                      {ev.entity_name && (
                        <span className="otl-entity-chip">{ev.entity_type}: {ev.entity_name}</span>
                      )}
                      {ev.domain_name && mode !== "tenant" && (
                        <span className="otl-domain-chip">{ev.domain_name}</span>
                      )}
                      {ev.project_name && (
                        <span className="otl-project-chip">{ev.project_name}</span>
                      )}
                      <span className="otl-source-chip">{ev.source}</span>
                      {ev.actor && ev.actor !== "system" && (
                        <span className="otl-actor-chip">by {ev.actor}</span>
                      )}
                    </div>
                    {hasDetail && (
                      <button className="otl-expand-btn" onClick={() => toggleExpand(ev.id)}>
                        {isExpanded ? "▼ Hide details" : "▶ Show details"}
                      </button>
                    )}
                    {isExpanded && (
                      <div className="otl-event-detail">
                        {ev.description && (
                          <p className="otl-description">{ev.description}</p>
                        )}
                        {Object.keys(ev.metadata ?? {}).length > 0 && (
                          <pre className="otl-metadata">
                            {JSON.stringify(ev.metadata, null, 2)}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Load more */}
        {hasMore && !loading && (
          <div className="otl-load-more">
            <button
              className="otl-btn otl-btn-secondary"
              onClick={loadMore}
              disabled={loadingMore}
            >
              {loadingMore
                ? "Loading…"
                : `Load more (showing ${filteredEvents.length} of ${total.toLocaleString()})`
              }
            </button>
          </div>
        )}

      </div>
    </div>
  );
};

export default OperationalTimelineTab;
