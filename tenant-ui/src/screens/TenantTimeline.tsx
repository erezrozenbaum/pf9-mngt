/**
 * TenantTimeline.tsx — Operational Event Timeline for tenant portal
 *
 * Shows a domain-scoped, read-only history of operational events.
 * domain_id is enforced server-side from the JWT — tenants can only
 * see their own events.
 */
import { useState, useEffect, useCallback } from "react";
import { tenantFetch } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface TimelineEvent {
  id: number;
  occurred_at: string;
  category: string;
  severity: string;
  summary: string;
  entity_type?: string;
  entity_id?: string;
  entity_name?: string;
  metadata?: Record<string, unknown>;
  ticket_id?: number;
  source_table?: string;
}

interface TimelineResponse {
  events: TimelineEvent[];
  total: number;
  limit: number;
  offset: number;
}

interface StatsResponse {
  total: number;
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const TIME_RANGES = [
  { label: "2h",  hours: 2 },
  { label: "6h",  hours: 6 },
  { label: "24h", hours: 24 },
  { label: "7d",  hours: 168 },
  { label: "30d", hours: 720 },
];

const CATEGORIES = [
  { key: "all",          label: "All" },
  { key: "monitoring",   label: "📊 Monitoring" },
  { key: "provisioning", label: "⚙ Provisioning" },
  { key: "snapshot",     label: "📸 Snapshot" },
  { key: "backup",       label: "💾 Backup" },
  { key: "sla",          label: "📋 SLA" },
  { key: "ticket",       label: "🎫 Ticket" },
  { key: "intelligence", label: "🧠 Intelligence" },
];

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#dc2626",
  high:     "#ea580c",
  medium:   "#d97706",
  low:      "#16a34a",
  info:     "#2563eb",
};

const LIMIT = 25;

function fmt(iso: string): string {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function TenantTimeline() {
  const [events, setEvents]           = useState<TimelineEvent[]>([]);
  const [total, setTotal]             = useState(0);
  const [offset, setOffset]           = useState(0);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState<string | null>(null);
  const [stats, setStats]             = useState<StatsResponse | null>(null);

  // Filters
  const [timeRange, setTimeRange]     = useState(2);   // index into TIME_RANGES
  const [category, setCategory]       = useState("all");
  const [severity, setSeverity]       = useState("");
  const [search, setSearch]           = useState("");
  const [searchInput, setSearchInput] = useState("");

  // Detail expand
  const [expanded, setExpanded]       = useState<Set<number>>(new Set());

  const buildParams = useCallback((off: number): URLSearchParams => {
    const hours = TIME_RANGES[timeRange].hours;
    const from = new Date(Date.now() - hours * 3_600_000).toISOString();
    const p = new URLSearchParams({ from, limit: String(LIMIT), offset: String(off) });
    if (category && category !== "all") p.set("category", category);
    if (severity) p.set("severity", severity);
    if (search)   p.set("search", search);
    return p;
  }, [timeRange, category, severity, search]);

  const load = useCallback(async (off: number) => {
    setLoading(true);
    setError(null);
    try {
      const params = buildParams(off);
      const data = await tenantFetch<TimelineResponse>(`/tenant/timeline?${params}`);
      if (off === 0) {
        setEvents(data.events);
      } else {
        setEvents(prev => [...prev, ...data.events]);
      }
      setTotal(data.total);
      setOffset(off);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load timeline");
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  const loadStats = useCallback(async () => {
    try {
      const hours = TIME_RANGES[timeRange].hours;
      const from = new Date(Date.now() - hours * 3_600_000).toISOString();
      const data = await tenantFetch<StatsResponse>(`/tenant/timeline/stats?from=${encodeURIComponent(from)}`);
      setStats(data);
    } catch {
      setStats(null);
    }
  }, [timeRange]);

  useEffect(() => {
    load(0);
    loadStats();
  }, [load, loadStats]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearch(searchInput.trim());
  };

  const toggleExpand = (id: number) => {
    setExpanded(prev => {
      const s = new Set(prev);
      s.has(id) ? s.delete(id) : s.add(id);
      return s;
    });
  };

  return (
    <div style={{ maxWidth: 960, margin: "0 auto" }}>
      {/* ── Stats strip ── */}
      {stats && stats.total > 0 && (
        <div style={{
          display: "flex", gap: "1rem", flexWrap: "wrap",
          background: "var(--color-surface, #f9fafb)",
          border: "1px solid var(--color-border, #e5e7eb)",
          borderRadius: 8, padding: "0.6rem 1rem", marginBottom: "1rem",
          fontSize: "0.78rem",
        }}>
          <span style={{ fontWeight: 600 }}>{stats.total} events</span>
          {Object.entries(stats.by_severity).map(([sev, cnt]) => (
            <span key={sev} style={{ color: SEVERITY_COLORS[sev] ?? "#6b7280" }}>
              {sev}: <strong>{cnt}</strong>
            </span>
          ))}
        </div>
      )}

      {/* ── Filter bar ── */}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem", alignItems: "center" }}>
        {/* Time range */}
        <div style={{ display: "flex", gap: "2px" }}>
          {TIME_RANGES.map((r, i) => (
            <button key={r.label}
              className={`btn${i === timeRange ? " btn-primary" : " btn-outline"}`}
              style={{ fontSize: "0.78rem", padding: "0.2rem 0.55rem" }}
              onClick={() => setTimeRange(i)}
            >{r.label}</button>
          ))}
        </div>

        {/* Severity */}
        <select className="select" style={{ fontSize: "0.78rem", padding: "0.2rem 0.4rem" }}
          value={severity} onChange={e => setSeverity(e.target.value)}>
          <option value="">All severities</option>
          {["critical","high","medium","low","info"].map(s => (
            <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>

        {/* Search */}
        <form onSubmit={handleSearch} style={{ display: "flex", gap: "0.3rem" }}>
          <input
            className="input"
            style={{ fontSize: "0.78rem", padding: "0.2rem 0.5rem", width: 180 }}
            placeholder="Search events…"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
          />
          <button type="submit" className="btn btn-outline"
            style={{ fontSize: "0.78rem", padding: "0.2rem 0.5rem" }}>Go</button>
          {search && (
            <button type="button" className="btn btn-outline"
              style={{ fontSize: "0.78rem", padding: "0.2rem 0.5rem" }}
              onClick={() => { setSearch(""); setSearchInput(""); }}>✕</button>
          )}
        </form>
      </div>

      {/* ── Category chips ── */}
      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        {CATEGORIES.map(c => (
          <button key={c.key}
            onClick={() => setCategory(c.key)}
            style={{
              fontSize: "0.75rem", padding: "0.2rem 0.65rem", borderRadius: 20,
              border: `1px solid ${category === c.key ? "#2563eb" : "var(--color-border, #d1d5db)"}`,
              background: category === c.key ? "#eff6ff" : "transparent",
              color: category === c.key ? "#1d4ed8" : "inherit",
              cursor: "pointer",
            }}
          >{c.label}</button>
        ))}
      </div>

      {/* ── Event list ── */}
      {error && (
        <div style={{ background: "#fee2e2", color: "#991b1b", padding: "0.75rem 1rem", borderRadius: 6, marginBottom: "1rem" }}>
          {error}
        </div>
      )}

      {loading && events.length === 0 && (
        <div style={{ textAlign: "center", padding: "3rem", color: "var(--color-muted, #9ca3af)" }}>
          Loading…
        </div>
      )}

      {!loading && events.length === 0 && !error && (
        <div style={{ textAlign: "center", padding: "3rem", color: "var(--color-muted, #9ca3af)" }}>
          No events found for the selected filters.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
        {events.map(ev => {
          const isOpen = expanded.has(ev.id);
          const color = SEVERITY_COLORS[ev.severity] ?? "#6b7280";
          return (
            <div key={ev.id} style={{
              borderLeft: `4px solid ${color}`,
              background: "var(--color-surface, #fff)",
              border: `1px solid var(--color-border, #e5e7eb)`,
              borderLeftColor: color,
              borderRadius: 6,
              padding: "0.65rem 0.9rem",
              cursor: "pointer",
            }} onClick={() => toggleExpand(ev.id)}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                <span style={{
                  fontSize: "0.68rem", fontWeight: 700, textTransform: "uppercase",
                  color, background: `${color}18`, padding: "0.1rem 0.4rem", borderRadius: 4,
                }}>{ev.severity}</span>
                <span style={{ fontSize: "0.72rem", color: "var(--color-muted, #6b7280)" }}>{ev.category}</span>
                <span style={{ flex: 1, fontSize: "0.85rem", fontWeight: 500 }}>{ev.summary}</span>
                {ev.entity_name && (
                  <span style={{
                    fontSize: "0.72rem", background: "var(--color-bg, #f3f4f6)",
                    padding: "0.1rem 0.45rem", borderRadius: 4,
                    color: "var(--color-muted, #6b7280)",
                  }}>{ev.entity_type}: {ev.entity_name}</span>
                )}
                <span style={{ fontSize: "0.72rem", color: "var(--color-muted, #9ca3af)", whiteSpace: "nowrap" }}>
                  {fmt(ev.occurred_at)}
                </span>
                <span style={{ color: "var(--color-muted, #9ca3af)", fontSize: "0.75rem" }}>
                  {isOpen ? "▲" : "▼"}
                </span>
              </div>

              {isOpen && (
                <div style={{ marginTop: "0.6rem", paddingTop: "0.6rem", borderTop: "1px solid var(--color-border, #e5e7eb)" }}>
                  <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "0.2rem 0.75rem", fontSize: "0.78rem", margin: 0 }}>
                    {ev.entity_type && <><dt style={{ color: "var(--color-muted)" }}>Entity</dt><dd style={{ margin: 0 }}>{ev.entity_type}{ev.entity_id ? ` · ${ev.entity_id}` : ""}</dd></>}
                    {ev.ticket_id   && <><dt style={{ color: "var(--color-muted)" }}>Ticket</dt><dd style={{ margin: 0 }}>#{ev.ticket_id}</dd></>}
                    {ev.source_table && <><dt style={{ color: "var(--color-muted)" }}>Source</dt><dd style={{ margin: 0 }}>{ev.source_table}</dd></>}
                  </dl>
                  {ev.metadata && Object.keys(ev.metadata).length > 0 && (
                    <pre style={{
                      marginTop: "0.5rem", fontSize: "0.72rem",
                      background: "var(--color-bg, #f9fafb)",
                      padding: "0.5rem", borderRadius: 4,
                      overflowX: "auto", whiteSpace: "pre-wrap",
                    }}>{JSON.stringify(ev.metadata, null, 2)}</pre>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Load more ── */}
      {events.length < total && (
        <div style={{ textAlign: "center", marginTop: "1rem" }}>
          <button className="btn btn-outline"
            disabled={loading}
            onClick={() => load(offset + LIMIT)}
          >
            {loading ? "Loading…" : `Load more (${events.length} / ${total})`}
          </button>
        </div>
      )}
    </div>
  );
}
