/**
 * OpsSearch — Global search tab for the PF9 Management Portal.
 *
 * Features:
 *   v1  – Full-text search (tsvector + ts_rank_cd)
 *   v2  – "Show Similar" per result (pg_trgm similarity)
 *   v2.5 – Intent detection: recognises quota / capacity / drift …
 *          queries and suggests the matching report endpoint.
 *   v3  – Smart Query Templates: matches natural-language questions
 *          to parameterised SQL and shows live answer cards inline.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "../config";

/* ── API helper ─────────────────────────────────────────────── */

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

/* ── Types ──────────────────────────────────────────────────── */

interface SearchDoc {
  doc_id: string;
  doc_type: string;
  resource_id: string;
  resource_name: string;
  tenant_name: string;
  domain_name: string;
  title: string;
  headline: string;
  ts: string;
  rank: number;
  metadata: Record<string, unknown>;
}

interface SearchResult {
  query: string;
  total: number;
  limit: number;
  offset: number;
  results: SearchDoc[];
}

interface IntentMatch {
  report: string;
  label: string;
  description: string;
  endpoint: string;
  matched_keyword: string;
  confidence: string;
}

interface IntentResult {
  query: string;
  intents: IntentMatch[];
  tenant_hint: string | null;
  has_intent: boolean;
  fallback_search: boolean;
}

interface SimilarDoc {
  doc_id: string;
  doc_type: string;
  title: string;
  resource_name: string;
  combined_similarity: number;
}

interface IndexerStat {
  doc_type: string;
  last_run_at: string | null;
  last_run_duration_ms: number | null;
  actual_count: number;
}

interface StatsResult {
  total_documents: number;
  doc_types: IndexerStat[];
}

/* ── Smart Query types (v3) ─────────────────────────────────── */

interface SmartQueryColumn {
  key: string;
  label: string;
}

interface SmartQueryResult {
  matched: boolean;
  query?: string;
  query_id?: string;
  query_title?: string;
  card_type?: "table" | "kv" | "number" | "error";
  title?: string;
  summary?: string;
  description?: string;
  category?: string;
  columns?: SmartQueryColumn[];
  rows?: Record<string, unknown>[];
  data?: Record<string, unknown>;
  value?: number;
  unit?: string;
  total?: number;
  error?: string;
}

/* ── Constants ──────────────────────────────────────────────── */

const DOC_TYPE_LABELS: Record<string, string> = {
  vm: "VM",
  volume: "Volume",
  snapshot: "Snapshot",
  hypervisor: "Hypervisor",
  network: "Network",
  subnet: "Subnet",
  floating_ip: "Floating IP",
  port: "Port",
  security_group: "Security Group",
  domain: "Domain",
  project: "Project",
  user: "User",
  flavor: "Flavor",
  image: "Image",
  router: "Router",
  role: "Role",
  role_assignment: "Role Assignment",
  group: "Group",
  snapshot_policy: "Snapshot Policy",
  activity: "Activity",
  audit: "Auth Audit",
  drift_event: "Drift Event",
  snapshot_run: "Snapshot Run",
  snapshot_record: "Snapshot Record",
  restore_job: "Restore Job",
  backup: "Backup",
  notification: "Notification",
  provisioning: "Provisioning",
  deletion: "Deletion",
};

const DOC_TYPE_COLORS: Record<string, string> = {
  vm: "#3b82f6",
  volume: "#8b5cf6",
  snapshot: "#06b6d4",
  hypervisor: "#f59e0b",
  network: "#10b981",
  subnet: "#14b8a6",
  floating_ip: "#ec4899",
  port: "#6366f1",
  security_group: "#ef4444",
  domain: "#0d9488",
  project: "#7c3aed",
  user: "#0891b2",
  flavor: "#d97706",
  image: "#059669",
  router: "#4f46e5",
  role: "#be185d",
  role_assignment: "#9333ea",
  group: "#1d4ed8",
  snapshot_policy: "#0369a1",
  activity: "#64748b",
  audit: "#78716c",
  drift_event: "#f97316",
  snapshot_run: "#0ea5e9",
  snapshot_record: "#22d3ee",
  restore_job: "#a855f7",
  backup: "#84cc16",
  notification: "#eab308",
  provisioning: "#2563eb",
  deletion: "#dc2626",
};

/* ── Metadata display helpers ───────────────────────────────── */

const METADATA_LABELS: Record<string, string> = {
  project_count: "Projects",
  user_count: "Users",
  vm_count: "VMs",
  role_count: "Roles",
  member_count: "Members",
  volume_count: "Volumes",
  network_count: "Networks",
  fip_count: "Floating IPs",
  subnet_count: "Subnets",
  port_count: "Ports",
  rule_count: "Rules",
  snapshot_count: "Snapshots",
  enabled: "Status",
  is_shared: "Shared",
  is_external: "External",
  is_public: "Public",
  is_global: "Global",
  is_active: "Active",
  vcpus: "vCPUs",
  ram_mb: "RAM",
  disk_gb: "Disk",
  local_gb: "Local Disk",
  memory_mb: "RAM",
  size_gb: "Size",
  size_mb: "Size",
  hypervisor: "Host",
  hypervisor_type: "Type",
  volume_type: "Type",
  disk_format: "Format",
  visibility: "Visibility",
  device_owner: "Device",
  mac_address: "MAC",
  cidr: "CIDR",
  gateway_ip: "Gateway",
  floating_ip: "External IP",
  fixed_ip: "Internal IP",
  domain: "Domain",
  project: "Project",
  network: "Network",
  flavor: "Flavor",
  roles: "Roles",
  email: "Email",
  default_project: "Default Project",
  last_login: "Last Login",
  role_name: "Role",
  inherited: "Inherited",
  priority: "Priority",
  bootable: "Bootable",
  protected: "Protected",
  projects: "Projects",
  status: "Status",
  vm_state: "State",
};

function formatMetaValue(key: string, value: unknown): string {
  if (typeof value === "boolean") {
    // Named boolean labels
    if (key === "enabled") return value ? "✅ Enabled" : "❌ Disabled";
    if (key === "bootable" || key === "protected" || key === "inherited")
      return value ? "Yes" : "No";
    return value ? "Yes" : "No";
  }
  if (key === "ram_mb" || key === "memory_mb")
    return `${Number(value).toLocaleString()} MB`;
  if (key === "disk_gb" || key === "local_gb" || key === "size_gb")
    return `${value} GB`;
  if (key === "size_mb") return `${Number(value).toLocaleString()} MB`;
  if (typeof value === "number") return value.toLocaleString();
  if (key === "last_login" && typeof value === "string")
    return new Date(value).toLocaleDateString();
  return String(value);
}

/* ── Prop types ─────────────────────────────────────────────── */

interface Props {
  isAdmin?: boolean;
  /** Called by the parent when the user wants to navigate to a report tab */
  onNavigateToReport?: (slug: string) => void;
}

/* ── Component ──────────────────────────────────────────────── */

export default function OpsSearch({ isAdmin, onNavigateToReport }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult | null>(null);
  const [intents, setIntents] = useState<IntentResult | null>(null);
  const [smartResult, setSmartResult] = useState<SmartQueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [stats, setStats] = useState<StatsResult | null>(null);
  const [showStats, setShowStats] = useState(false);
  const [similarFor, setSimilarFor] = useState<string | null>(null);
  const [similarDocs, setSimilarDocs] = useState<SimilarDoc[]>([]);
  const [similarLoading, setSimilarLoading] = useState(false);
  const [page, setPage] = useState(0);
  const [showHelp, setShowHelp] = useState(false);

  /* ── Scope filters (domain / tenant) ────────────────────── */
  const [scopeDomain, setScopeDomain] = useState("");
  const [scopeTenant, setScopeTenant] = useState("");
  const [domainOptions, setDomainOptions] = useState<{ domain_id: string; domain_name: string }[]>([]);
  const [tenantOptions, setTenantOptions] = useState<{ tenant_id: string; tenant_name: string; domain_name: string }[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);
  const LIMIT = 25;

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Load domain & tenant options for scope filters
  useEffect(() => {
    (async () => {
      try {
        const [dRes, tRes] = await Promise.all([
          apiFetch<{ items: { domain_id: string; domain_name: string }[] }>("/domains"),
          apiFetch<{ items: { tenant_id: string; tenant_name: string; domain_name: string }[] }>("/tenants"),
        ]);
        setDomainOptions(dRes.items);
        setTenantOptions(tRes.items);
      } catch { /* non-critical */ }
    })();
  }, []);

  // Filter tenants by selected domain
  const filteredTenants = scopeDomain
    ? tenantOptions.filter((t) => t.domain_name === scopeDomain)
    : tenantOptions;

  // Clear all results and return to start
  const clearResults = () => {
    setQuery("");
    setResults(null);
    setIntents(null);
    setSmartResult(null);
    setError("");
    setSimilarFor(null);
    setSimilarDocs([]);
    setPage(0);
    inputRef.current?.focus();
  };

  /* ── Search handler ─────────────────────────────────────── */

  const doSearch = useCallback(
    async (q: string, offset = 0) => {
      if (!q.trim()) return;
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams({ q: q.trim(), limit: String(LIMIT), offset: String(offset) });
        if (selectedTypes.length > 0) params.set("types", selectedTypes.join(","));

        // Fire FTS + intent detection + smart query in parallel
        const smartParams = new URLSearchParams({ q: q.trim() });
        if (scopeTenant) smartParams.set("scope_tenant", scopeTenant);
        if (scopeDomain) smartParams.set("scope_domain", scopeDomain);

        const [searchRes, intentRes, smartRes] = await Promise.all([
          apiFetch<SearchResult>(`/api/search?${params}`),
          apiFetch<IntentResult>(`/api/search/intent?q=${encodeURIComponent(q.trim())}`),
          apiFetch<SmartQueryResult>(`/api/search/smart?${smartParams}`),
        ]);

        setResults(searchRes);
        setIntents(intentRes);
        setSmartResult(smartRes.matched ? smartRes : null);
        setPage(offset / LIMIT);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    },
    [selectedTypes, scopeTenant, scopeDomain],
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    doSearch(query, 0);
  };

  /* ── Similarity handler ─────────────────────────────────── */

  const loadSimilar = async (docId: string) => {
    if (similarFor === docId) {
      setSimilarFor(null);
      setSimilarDocs([]);
      return;
    }
    setSimilarFor(docId);
    setSimilarLoading(true);
    try {
      const res = await apiFetch<{ similar: SimilarDoc[] }>(`/api/search/similar/${docId}`);
      setSimilarDocs(res.similar);
    } catch {
      setSimilarDocs([]);
    } finally {
      setSimilarLoading(false);
    }
  };

  /* ── Stats loader ───────────────────────────────────────── */

  const loadStats = async () => {
    if (showStats) {
      setShowStats(false);
      return;
    }
    try {
      const s = await apiFetch<StatsResult>("/api/search/stats");
      setStats(s);
      setShowStats(true);
    } catch (e: any) {
      setError(e.message);
    }
  };

  /* ── Reindex trigger ────────────────────────────────────── */

  const triggerReindex = async () => {
    try {
      await apiFetch("/api/search/reindex", { method: "POST" });
      setError("");
      alert("Re-index triggered. Documents will refresh within a few minutes.");
    } catch (e: any) {
      setError(e.message);
    }
  };

  /* ── Toggle type filter ─────────────────────────────────── */

  const toggleType = (t: string) => {
    setSelectedTypes((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t],
    );
  };

  /* ── Smart Query example chips ──────────────────────────── */

  /**
   * Each query can be a plain string (runs immediately) or an object with
   * `template` + `placeholder` — clicking fills the search bar and lets
   * the user complete it (e.g., type a tenant name).
   * If a scope tenant/domain is selected it auto-fills the placeholder.
   */
  interface ChipDef {
    label: string;
    /** If set, this is a template needing user input (the {placeholder} part) */
    template?: string;
  }

  const chip = (label: string): ChipDef => ({ label });
  const chipT = (label: string, template: string): ChipDef => ({ label, template });

  const SMART_EXAMPLES: { category: string; icon: string; queries: ChipDef[] }[] = [
    {
      category: "Infrastructure",
      icon: "🖥️",
      queries: [
        chip("How many VMs?"),
        chip("Show powered off VMs"),
        chip("VMs in error state"),
        chip("Hypervisor capacity"),
        chip("Show all flavors"),
        chipT("VMs on host …", "VMs on host "),
        chip("Image overview"),
      ],
    },
    {
      category: "Projects & Quotas",
      icon: "📁",
      queries: [
        chipT("Quota for …", "Quota for "),
        chip("Quota usage overview"),
        chip("VMs per project"),
        chip("How many projects?"),
        chip("Domain overview"),
      ],
    },
    {
      category: "Storage",
      icon: "💾",
      queries: [
        chip("Volume summary"),
        chip("Orphan volumes"),
        chip("Snapshot overview"),
      ],
    },
    {
      category: "Networking",
      icon: "🌐",
      queries: [
        chip("Network overview"),
        chip("Floating IP overview"),
        chip("Router overview"),
      ],
    },
    {
      category: "Security & Access",
      icon: "🔐",
      queries: [
        chipT("Roles for …", "Roles for "),
        chip("All role assignments"),
        chip("Security group overview"),
      ],
    },
    {
      category: "Operations",
      icon: "📊",
      queries: [
        chip("Recent activity"),
        chip("Drift summary"),
        chip("Efficiency overview"),
        chip("Platform overview"),
      ],
    },
  ];

  /** Handle chip click — for templates, fill the bar (+ scope) and focus; for plain queries, run. */
  const runExampleQuery = (c: ChipDef) => {
    if (c.template) {
      // If scope tenant is selected, auto-fill; otherwise let user type
      const fill = scopeTenant || scopeDomain || "";
      const q = c.template + fill;
      setQuery(q);
      setShowHelp(false);
      if (fill) {
        doSearch(q, 0);
      } else {
        // Focus the input so user can complete the query
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    } else {
      setQuery(c.label);
      setShowHelp(false);
      doSearch(c.label, 0);
    }
  };

  /* ── Pagination ─────────────────────────────────────────── */

  const totalPages = results ? Math.ceil(results.total / LIMIT) : 0;

  const goPage = (p: number) => {
    doSearch(query, p * LIMIT);
  };

  /* ── Render ─────────────────────────────────────────────── */

  return (
    <div style={{ padding: "24px", maxWidth: 1100, margin: "0 auto" }}>
      {/* ── Search form ──────────────────────────────────── */}
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search VMs, volumes, IPs, audit events, drift, snapshots…  or ask: quota for projectX"
          style={{
            flex: 1,
            padding: "10px 14px",
            fontSize: "1rem",
            borderRadius: 6,
            border: "1px solid var(--border-color, #cbd5e1)",
            background: "var(--input-bg, #fff)",
            color: "var(--text-color, #1e293b)",
          }}
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          style={{
            padding: "10px 20px",
            fontSize: "1rem",
            borderRadius: 6,
            border: "none",
            background: "#3b82f6",
            color: "#fff",
            cursor: "pointer",
            opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? "Searching…" : "🔍 Search"}
        </button>
        <button
          type="button"
          onClick={() => setShowHelp((v) => !v)}
          title="What can I ask?"
          style={{
            padding: "10px 12px",
            borderRadius: 6,
            border: showHelp ? "1px solid #22c55e" : "1px solid var(--border-color, #cbd5e1)",
            background: showHelp ? "var(--pf9-safe-bg, #dcfce7)" : "var(--card-bg, #f8fafc)",
            cursor: "pointer",
            fontSize: "0.85rem",
          }}
        >
          🤖
        </button>
        <button
          type="button"
          onClick={loadStats}
          title="Indexer stats"
          style={{
            padding: "10px 12px",
            borderRadius: 6,
            border: "1px solid var(--border-color, #cbd5e1)",
            background: "var(--card-bg, #f8fafc)",
            cursor: "pointer",
            fontSize: "0.85rem",
          }}
        >
          📊
        </button>
        {isAdmin && (
          <button
            type="button"
            onClick={triggerReindex}
            title="Trigger full re-index (admin)"
            style={{
              padding: "10px 12px",
              borderRadius: 6,
              border: "1px solid #f59e0b",
              background: "#fef3c7",
              cursor: "pointer",
              fontSize: "0.85rem",
            }}
          >
            🔄
          </button>
        )}
      </form>

      {/* ── Type filters ─────────────────────────────────── */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
        {Object.entries(DOC_TYPE_LABELS).map(([key, label]) => (
          <button
            key={key}
            onClick={() => toggleType(key)}
            style={{
              padding: "3px 10px",
              fontSize: "0.78rem",
              borderRadius: 12,
              border: `1px solid ${DOC_TYPE_COLORS[key] || "#94a3b8"}`,
              background: selectedTypes.includes(key)
                ? DOC_TYPE_COLORS[key] || "#94a3b8"
                : "transparent",
              color: selectedTypes.includes(key) ? "#fff" : DOC_TYPE_COLORS[key] || "#94a3b8",
              cursor: "pointer",
              transition: "all 0.15s",
            }}
          >
            {label}
          </button>
        ))}
        {selectedTypes.length > 0 && (
          <button
            onClick={() => setSelectedTypes([])}
            style={{
              padding: "3px 10px",
              fontSize: "0.78rem",
              borderRadius: 12,
              border: "1px solid #94a3b8",
              background: "transparent",
              color: "#94a3b8",
              cursor: "pointer",
            }}
          >
            ✕ Clear
          </button>
        )}
      </div>

      {/* ── Scope filters (domain / tenant) ──────────────── */}
      <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.78rem", color: "var(--pf9-text-secondary)", fontWeight: 600 }}>Scope:</span>
        <select
          value={scopeDomain}
          onChange={(e) => {
            setScopeDomain(e.target.value);
            setScopeTenant(""); // reset tenant when domain changes
          }}
          style={{
            padding: "4px 10px",
            fontSize: "0.82rem",
            borderRadius: 6,
            border: "1px solid var(--border-color, #cbd5e1)",
            background: "var(--input-bg, #fff)",
            color: "var(--text-color, #1e293b)",
            minWidth: 140,
          }}
        >
          <option value="">All Domains</option>
          {domainOptions.map((d) => (
            <option key={d.domain_id} value={d.domain_name}>{d.domain_name}</option>
          ))}
        </select>
        <select
          value={scopeTenant}
          onChange={(e) => setScopeTenant(e.target.value)}
          style={{
            padding: "4px 10px",
            fontSize: "0.82rem",
            borderRadius: 6,
            border: "1px solid var(--border-color, #cbd5e1)",
            background: "var(--input-bg, #fff)",
            color: "var(--text-color, #1e293b)",
            minWidth: 160,
          }}
        >
          <option value="">All Tenants</option>
          {filteredTenants.map((t) => (
            <option key={t.tenant_id} value={t.tenant_name}>
              {t.tenant_name}{!scopeDomain ? ` (${t.domain_name})` : ""}
            </option>
          ))}
        </select>
        {(scopeDomain || scopeTenant) && (
          <button
            onClick={() => { setScopeDomain(""); setScopeTenant(""); }}
            style={{
              padding: "3px 10px",
              fontSize: "0.78rem",
              borderRadius: 12,
              border: "1px solid #94a3b8",
              background: "transparent",
              color: "#94a3b8",
              cursor: "pointer",
            }}
          >
            ✕ Clear scope
          </button>
        )}
        {(scopeDomain || scopeTenant) && (
          <span style={{ fontSize: "0.72rem", color: "var(--pf9-text-secondary)", fontStyle: "italic" }}>
            Scope auto-fills tenant-specific questions (e.g. "Quota for …")
          </span>
        )}
      </div>

      {/* ── Smart Query Help Panel ───────────────────────── */}
      {showHelp && (
        <div
          style={{
            padding: 16,
            background: "var(--card-bg, #f0fdf4)",
            border: "1px solid var(--color-success, #86efac)",
            borderRadius: 8,
            marginBottom: 16,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: "1.1rem" }}>🤖</span>
            <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "var(--color-success, #15803d)" }}>
              Ask Me Anything — Example Questions
            </span>
            <span style={{ fontSize: "0.78rem", color: "var(--pf9-text-secondary)", marginLeft: 4 }}>
              Click any chip to run it — chips with "…" let you choose the target
            </span>
            <button
              onClick={() => setShowHelp(false)}
              style={{
                marginLeft: "auto",
                padding: "2px 8px",
                borderRadius: 4,
                border: "1px solid var(--pf9-border)",
                background: "transparent",
                fontSize: "0.8rem",
                cursor: "pointer",
                color: "var(--pf9-text-secondary)",
              }}
            >
              ✕
            </button>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
            {SMART_EXAMPLES.map((cat) => (
              <div key={cat.category}>
                <div style={{ fontWeight: 600, fontSize: "0.82rem", color: "var(--pf9-text)", marginBottom: 6 }}>
                  {cat.icon} {cat.category}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                  {cat.queries.map((c) => (
                    <button
                      key={c.label}
                      onClick={() => runExampleQuery(c)}
                      style={{
                        padding: "4px 10px",
                        fontSize: "0.76rem",
                        borderRadius: 14,
                        border: c.template ? "1px dashed var(--color-success, #86efac)" : "1px solid var(--color-success, #86efac)",
                        background: "var(--color-surface, #fff)",
                        color: "var(--color-success, #15803d)",
                        cursor: "pointer",
                        transition: "all 0.15s",
                        whiteSpace: "nowrap",
                      }}
                      onMouseEnter={(e) => {
                        (e.target as HTMLButtonElement).style.background = "var(--pf9-safe-bg)";
                        (e.target as HTMLButtonElement).style.borderColor = "#22c55e";
                      }}
                      onMouseLeave={(e) => {
                        (e.target as HTMLButtonElement).style.background = "var(--color-surface, #fff)";
                        (e.target as HTMLButtonElement).style.borderColor = "var(--color-success, #86efac)";
                      }}
                      title={c.template ? "Click to fill — complete with a name" : "Click to run"}
                    >
                      {c.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: "0.72rem", color: "var(--pf9-text-muted)", marginTop: 10, fontStyle: "italic" }}>
            💡 You can also type your own question naturally — the system matches patterns, not exact wording.
          </div>
        </div>
      )}

      {error && (
        <div style={{ padding: 12, background: "var(--pf9-danger-bg)", color: "var(--pf9-danger-text)", borderRadius: 6, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* ── Intent suggestions (v2.5) ────────────────────── */}
      {intents && intents.has_intent && (
        <div
          style={{
            padding: 14,
            background: "var(--card-bg, #eff6ff)",
            border: "1px solid var(--pf9-info-border, #93c5fd)",
            borderRadius: 8,
            marginBottom: 16,
          }}
        >
          <div style={{ fontWeight: 600, fontSize: "0.9rem", marginBottom: 8, color: "var(--pf9-info-text, #1d4ed8)" }}>
            💡 Smart Suggestions
            {intents.tenant_hint && (
              <span style={{ fontWeight: 400, marginLeft: 8, fontSize: "0.82rem", color: "var(--pf9-text-secondary)" }}>
                (tenant hint: <strong>{intents.tenant_hint}</strong>)
              </span>
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {intents.intents.map((intent) => (
              <button
                key={intent.report}
                onClick={() => onNavigateToReport?.(intent.report)}
                style={{
                  padding: "8px 14px",
                  borderRadius: 6,
                  border: "1px solid var(--pf9-info-border, #3b82f6)",
                  background: "var(--pf9-info-bg, #dbeafe)",
                  color: "var(--pf9-info-text, #1e40af)",
                  cursor: "pointer",
                  fontSize: "0.85rem",
                  textAlign: "left",
                }}
                title={intent.description}
              >
                📊 {intent.label}
                <span
                  style={{
                    display: "block",
                    fontSize: "0.72rem",
                    color: "var(--pf9-text-secondary)",
                    marginTop: 2,
                  }}
                >
                  {intent.description}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Smart Query Answer Card (v3) ─────────────────── */}
      {smartResult && smartResult.matched && (
        <div
          style={{
            padding: 16,
            background: "var(--card-bg, #f0fdf4)",
            border: "1px solid var(--color-success, #86efac)",
            borderRadius: 8,
            marginBottom: 16,
          }}
        >
          {/* Header */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: "1.15rem" }}>🤖</span>
            <span style={{ fontWeight: 700, fontSize: "0.95rem", color: "var(--color-success, #15803d)" }}>
              {smartResult.title || smartResult.query_title}
            </span>
            {smartResult.category && (
              <span
                style={{
                  fontSize: "0.7rem",
                  padding: "2px 8px",
                  borderRadius: 10,
                  background: "var(--pf9-safe-bg)",
                  color: "var(--pf9-safe-text)",
                  fontWeight: 500,
                }}
              >
                {smartResult.category}
              </span>
            )}
            <button
              onClick={clearResults}
              title="Clear and ask another question"
              style={{
                marginLeft: "auto",
                padding: "3px 10px",
                fontSize: "0.76rem",
                borderRadius: 12,
                border: "1px solid var(--color-success, #86efac)",
                background: "var(--color-surface, #fff)",
                color: "var(--color-success, #15803d)",
                cursor: "pointer",
              }}
            >
              ✕ New Question
            </button>
          </div>

          {/* Summary */}
          {smartResult.summary && (
            <div style={{ fontSize: "0.88rem", color: "var(--pf9-text)", marginBottom: 10, fontWeight: 500 }}>
              {smartResult.summary}
            </div>
          )}

          {/* Error card */}
          {smartResult.card_type === "error" && (
            <div style={{ padding: 10, background: "var(--pf9-danger-bg)", color: "var(--pf9-danger-text)", borderRadius: 6, fontSize: "0.82rem" }}>
              ⚠️ {smartResult.error || "Query failed"}
            </div>
          )}

          {/* Number card */}
          {smartResult.card_type === "number" && (
            <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--color-success)", textAlign: "center", padding: "8px 0" }}>
              {typeof smartResult.value === "number" ? smartResult.value.toLocaleString() : smartResult.value}
              {smartResult.unit && (
                <span style={{ fontSize: "1rem", fontWeight: 400, marginLeft: 6, color: "var(--pf9-text-secondary)" }}>
                  {smartResult.unit}
                </span>
              )}
            </div>
          )}

          {/* KV card */}
          {smartResult.card_type === "kv" && smartResult.data && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
              {Object.entries(smartResult.data).map(([k, v]) => (
                <div
                  key={k}
                  style={{
                    padding: "8px 14px",
                    background: "var(--color-surface, #fff)",
                    border: "1px solid var(--pf9-border)",
                    borderRadius: 6,
                    textAlign: "center",
                    minWidth: 90,
                  }}
                >
                  <div style={{ fontSize: "1.3rem", fontWeight: 700, color: "var(--color-text-primary, #111827)" }}>
                    {typeof v === "number" ? v.toLocaleString() : String(v ?? "—")}
                  </div>
                  <div style={{ fontSize: "0.72rem", color: "var(--pf9-text-secondary)", textTransform: "capitalize" }}>
                    {k.replace(/_/g, " ")}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Table card */}
          {smartResult.card_type === "table" && smartResult.columns && smartResult.rows && (
            <div style={{ overflowX: "auto", maxHeight: 320 }}>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: "0.82rem",
                }}
              >
                <thead>
                  <tr>
                    {smartResult.columns.map((col) => (
                      <th
                        key={col.key}
                        style={{
                          textAlign: "left",
                          padding: "6px 10px",
                          borderBottom: "2px solid var(--color-success, #86efac)",
                          color: "var(--color-success, #15803d)",
                          fontWeight: 600,
                          whiteSpace: "nowrap",
                          position: "sticky",
                          top: 0,
                          background: "var(--card-bg, #f0fdf4)",
                        }}
                      >
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {smartResult.rows.length === 0 ? (
                    <tr>
                      <td
                        colSpan={smartResult.columns.length}
                        style={{ padding: 16, textAlign: "center", color: "var(--pf9-text-secondary)" }}
                      >
                        No data found
                      </td>
                    </tr>
                  ) : (
                    smartResult.rows.map((row, idx) => (
                      <tr
                        key={idx}
                        style={{ background: idx % 2 === 0 ? "transparent" : "var(--color-table-row-even, rgba(255,255,255,0.6))" }}
                      >
                        {smartResult.columns!.map((col) => {
                          const val = row[col.key];
                          const display =
                            val === null || val === undefined
                              ? "—"
                              : typeof val === "boolean"
                              ? val ? "Yes" : "No"
                              : typeof val === "number"
                              ? val.toLocaleString()
                              : String(val);
                          return (
                            <td
                              key={col.key}
                              style={{
                                padding: "5px 10px",
                                borderBottom: "1px solid var(--pf9-border)",
                                color: "var(--pf9-text)",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {display}
                            </td>
                          );
                        })}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
              {(smartResult.total ?? 0) > 0 && (
                <div style={{ fontSize: "0.72rem", color: "var(--pf9-text-secondary)", marginTop: 6, textAlign: "right" }}>
                  {smartResult.total} row(s)
                </div>
              )}
            </div>
          )}

          {/* Description footer */}
          {smartResult.description && (
            <div style={{ fontSize: "0.72rem", color: "var(--pf9-text-muted)", marginTop: 8, fontStyle: "italic" }}>
              {smartResult.description}
            </div>
          )}
        </div>
      )}

      {/* ── Indexer stats panel ───────────────────────────── */}
      {showStats && stats && (
        <div
          style={{
            padding: 14,
            background: "var(--card-bg, #f8fafc)",
            border: "1px solid var(--border-color, #e2e8f0)",
            borderRadius: 8,
            marginBottom: 16,
            fontSize: "0.82rem",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            Indexer Status — {stats.total_documents.toLocaleString()} total documents
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 6 }}>
            {stats.doc_types.map((dt) => (
              <div
                key={dt.doc_type}
                style={{
                  padding: "6px 10px",
                  borderRadius: 4,
                  background: "var(--bg-color, #fff)",
                  border: "1px solid var(--border-color, #e2e8f0)",
                }}
              >
                <strong style={{ color: DOC_TYPE_COLORS[dt.doc_type] || "#64748b" }}>
                  {DOC_TYPE_LABELS[dt.doc_type] || dt.doc_type}
                </strong>
                <span style={{ float: "right", color: "var(--pf9-text-secondary)" }}>{dt.actual_count}</span>
                {dt.last_run_at && (
                  <div style={{ fontSize: "0.72rem", color: "#94a3b8" }}>
                    Last run: {new Date(dt.last_run_at).toLocaleString()} ({dt.last_run_duration_ms}ms)
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Results ──────────────────────────────────────── */}
      {results && (
        <div>
          <div style={{ display: "flex", alignItems: "center", fontSize: "0.85rem", color: "var(--pf9-text-secondary)", marginBottom: 12 }}>
            <span>
              {results.total.toLocaleString()} result{results.total !== 1 ? "s" : ""} for{" "}
              <strong>"{results.query}"</strong>
              {totalPages > 1 && (
                <span style={{ marginLeft: 8 }}>
                  (page {page + 1} of {totalPages})
                </span>
              )}
            </span>
            <button
              onClick={clearResults}
              title="Clear and ask another question"
              style={{
                marginLeft: "auto",
                padding: "3px 10px",
                fontSize: "0.76rem",
                borderRadius: 12,
                border: "1px solid var(--pf9-border)",
                background: "var(--card-bg, #f8fafc)",
                color: "var(--pf9-text-secondary)",
                cursor: "pointer",
              }}
            >
              ✕ New Question
            </button>
          </div>

          {results.results.map((doc) => (
            <div
              key={doc.doc_id}
              style={{
                padding: 14,
                marginBottom: 10,
                borderRadius: 8,
                border: "1px solid var(--border-color, #e2e8f0)",
                background: "var(--card-bg, #fff)",
              }}
            >
              {/* Header row */}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span
                  style={{
                    padding: "2px 8px",
                    borderRadius: 10,
                    fontSize: "0.7rem",
                    fontWeight: 600,
                    background: DOC_TYPE_COLORS[doc.doc_type] || "#94a3b8",
                    color: "#fff",
                  }}
                >
                  {DOC_TYPE_LABELS[doc.doc_type] || doc.doc_type}
                </span>
                <span style={{ fontWeight: 600, fontSize: "0.95rem", color: "var(--text-color, #1e293b)" }}>
                  {doc.title}
                </span>
                <span style={{ marginLeft: "auto", fontSize: "0.75rem", color: "#94a3b8" }}>
                  {doc.ts ? new Date(doc.ts).toLocaleString() : ""}
                </span>
              </div>

              {/* Headline snippet (HTML from ts_headline) */}
              {doc.headline && (
                <div
                  style={{ fontSize: "0.85rem", color: "#475569", marginBottom: 6, lineHeight: 1.5 }}
                  dangerouslySetInnerHTML={{ __html: doc.headline }}
                />
              )}

              {/* Structured metadata cards */}
              {doc.metadata && Object.keys(doc.metadata).length > 0 && (
                <div style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 6,
                  marginBottom: 8,
                  marginTop: 4,
                }}>
                  {Object.entries(doc.metadata)
                    .filter(([, v]) => v !== null && v !== undefined && v !== "")
                    .map(([key, value]) => (
                      <span
                        key={key}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          padding: "2px 8px",
                          borderRadius: 6,
                          fontSize: "0.73rem",
                          background: "var(--bg-color, #f1f5f9)",
                          border: "1px solid var(--border-color, #e2e8f0)",
                          color: "var(--text-color, #334155)",
                        }}
                      >
                        <span style={{ fontWeight: 600, color: "#64748b" }}>
                          {METADATA_LABELS[key] || key.replace(/_/g, " ")}:
                        </span>
                        <span>{formatMetaValue(key, value)}</span>
                      </span>
                    ))}
                </div>
              )}

              {/* Meta row */}
              <div style={{ display: "flex", gap: 12, fontSize: "0.78rem", color: "#94a3b8" }}>
                {doc.tenant_name && <span>Tenant: {doc.tenant_name}</span>}
                {doc.domain_name && <span>Domain: {doc.domain_name}</span>}
                {doc.resource_id && <span>ID: {doc.resource_id.slice(0, 12)}…</span>}
                <button
                  onClick={() => loadSimilar(doc.doc_id)}
                  style={{
                    marginLeft: "auto",
                    padding: "2px 8px",
                    fontSize: "0.74rem",
                    borderRadius: 4,
                    border: "1px solid #cbd5e1",
                    background: similarFor === doc.doc_id ? "#e0e7ff" : "transparent",
                    color: "#6366f1",
                    cursor: "pointer",
                  }}
                >
                  {similarFor === doc.doc_id ? "Hide Similar" : "Show Similar"}
                </button>
              </div>

              {/* Similar docs (v2) */}
              {similarFor === doc.doc_id && (
                <div
                  style={{
                    marginTop: 8,
                    padding: 10,
                    background: "var(--bg-color, #f1f5f9)",
                    borderRadius: 6,
                    fontSize: "0.82rem",
                  }}
                >
                  {similarLoading ? (
                    <span style={{ color: "#94a3b8" }}>Loading similar…</span>
                  ) : similarDocs.length === 0 ? (
                    <span style={{ color: "#94a3b8" }}>No similar documents found</span>
                  ) : (
                    similarDocs.map((s) => (
                      <div
                        key={s.doc_id}
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                          padding: "4px 0",
                          borderBottom: "1px solid var(--border-color, #e2e8f0)",
                        }}
                      >
                        <span
                          style={{
                            padding: "1px 6px",
                            borderRadius: 8,
                            fontSize: "0.68rem",
                            background: DOC_TYPE_COLORS[s.doc_type] || "#94a3b8",
                            color: "#fff",
                          }}
                        >
                          {DOC_TYPE_LABELS[s.doc_type] || s.doc_type}
                        </span>
                        <span>{s.title}</span>
                        <span
                          style={{
                            marginLeft: "auto",
                            fontSize: "0.72rem",
                            color: "#22c55e",
                            fontWeight: 600,
                          }}
                        >
                          {(s.combined_similarity * 100).toFixed(0)}% match
                        </span>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          ))}

          {/* ── Pagination ───────────────────────────────── */}
          {totalPages > 1 && (
            <div style={{ display: "flex", justifyContent: "center", gap: 6, marginTop: 16 }}>
              <button
                disabled={page === 0}
                onClick={() => goPage(page - 1)}
                style={{ padding: "6px 12px", borderRadius: 4, border: "1px solid #cbd5e1", cursor: "pointer" }}
              >
                ← Prev
              </button>
              {Array.from({ length: Math.min(totalPages, 10) }, (_, i) => {
                const p = page < 5 ? i : page - 4 + i;
                if (p >= totalPages) return null;
                return (
                  <button
                    key={p}
                    onClick={() => goPage(p)}
                    style={{
                      padding: "6px 10px",
                      borderRadius: 4,
                      border: "1px solid #cbd5e1",
                      background: p === page ? "#3b82f6" : "transparent",
                      color: p === page ? "#fff" : "inherit",
                      cursor: "pointer",
                    }}
                  >
                    {p + 1}
                  </button>
                );
              })}
              <button
                disabled={page >= totalPages - 1}
                onClick={() => goPage(page + 1)}
                style={{ padding: "6px 12px", borderRadius: 4, border: "1px solid #cbd5e1", cursor: "pointer" }}
              >
                Next →
              </button>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!results && !loading && !error && (
        <div style={{ textAlign: "center", padding: 40, color: "#94a3b8" }}>
          <div style={{ fontSize: "2.5rem", marginBottom: 12 }}>🔍</div>
          <div style={{ fontSize: "1.1rem", fontWeight: 500 }}>Ops Assistant</div>
          <div style={{ fontSize: "0.85rem", marginTop: 4 }}>
            Search across all resources, events, and audit logs — or ask operational questions.
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "center", marginTop: 16 }}>
            {[
              chip("How many VMs?"),
              chipT("Quota for …", "Quota for "),
              chip("Volume summary"),
              chip("Platform overview"),
              chip("Drift summary"),
              chipT("Roles for …", "Roles for "),
            ].map((c) => (
              <button
                key={c.label}
                onClick={() => runExampleQuery(c)}
                style={{
                  padding: "5px 12px",
                  fontSize: "0.8rem",
                  borderRadius: 14,
                  border: c.template ? "1px dashed var(--color-success, #86efac)" : "1px solid var(--color-success, #86efac)",
                  background: "var(--pf9-safe-bg, #f0fdf4)",
                  color: "var(--color-success, #15803d)",
                  cursor: "pointer",
                  transition: "all 0.15s",
                }}
                onMouseEnter={(e) => {
                  (e.target as HTMLButtonElement).style.background = "var(--pf9-safe-border, #dcfce7)";
                }}
                onMouseLeave={(e) => {
                  (e.target as HTMLButtonElement).style.background = "var(--pf9-safe-bg, #f0fdf4)";
                }}
              >
                🤖 {c.label}
              </button>
            ))}
          </div>
          <div style={{ fontSize: "0.78rem", marginTop: 10, color: "var(--pf9-text-muted)" }}>
            Click the <strong style={{ color: "#22c55e" }}>🤖</strong> button above for all available questions.
            {" "}Use the <strong>Scope</strong> dropdowns to focus on a specific domain or tenant.
          </div>
        </div>
      )}
    </div>
  );
}
