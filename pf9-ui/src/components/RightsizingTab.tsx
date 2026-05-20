/*
 * RightsizingTab.tsx — Workload Right-Sizing & Cost Waste Detection
 * ===================================================================
 * Displays VM rightsizing recommendations for admins.
 * Card-based layout with billing impact (current vs recommended monthly cost).
 *
 * v2.3.0
 */
import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RightsizingSummary {
  total_open: number;
  idle_count: number;
  over_provisioned_count: number;
  total_estimated_savings_usd: number;
  currency: string;
}

interface Recommendation {
  id: number;
  vm_id: string;
  vm_name: string | null;
  project_name: string | null;
  region_id: string | null;
  domain: string | null;
  classification: string;
  current_flavor: string | null;
  current_vcpus: number | null;
  current_ram_mb: number | null;
  recommended_flavor: string | null;
  recommended_vcpus: number | null;
  recommended_ram_mb: number | null;
  cpu_p95_7d: number | null;
  ram_p95_7d: number | null;
  cpu_avg_7d: number | null;
  ram_avg_7d: number | null;
  estimated_monthly_savings_usd: number | null;
  current_monthly_cost: number | null;
  recommended_monthly_cost: number | null;
  currency: string;
  status: string;
  computed_at: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRam(mb: number | null): string {
  if (mb === null) return "—";
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
}

function formatCost(amount: number | null, currency: string): string {
  if (amount === null || amount === undefined) return "—";
  return `${currency} ${amount.toFixed(0)}/mo`;
}

function formatPct(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${Number(v).toFixed(1)}%`;
}

function classColor(c: string): string {
  if (c === "idle") return "var(--color-error)";
  if (c === "over_provisioned") return "var(--color-warning)";
  if (c === "under_provisioned") return "var(--color-info, #3b82f6)";
  return "var(--color-success)";
}

function classLabel(c: string): string {
  return c.replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

// ---------------------------------------------------------------------------
// Summary cards
// ---------------------------------------------------------------------------

function SummaryCards({ summary }: { summary: RightsizingSummary | null }) {
  if (!summary) return null;
  const cur = summary.currency;
  const items = [
    {
      label: "Open Recommendations",
      value: String(summary.total_open),
      color: summary.total_open > 0 ? "var(--color-warning)" : "var(--color-success)",
    },
    {
      label: "Idle VMs",
      value: String(summary.idle_count),
      color: summary.idle_count > 0 ? "var(--color-error)" : "var(--color-text)",
    },
    {
      label: "Over-Provisioned VMs",
      value: String(summary.over_provisioned_count),
      color: summary.over_provisioned_count > 0 ? "var(--color-warning)" : "var(--color-text)",
    },
    {
      label: "Est. Monthly Savings",
      value:
        summary.total_estimated_savings_usd > 0
          ? `${cur} ${summary.total_estimated_savings_usd.toFixed(0)}`
          : "—",
      color:
        summary.total_estimated_savings_usd > 0 ? "var(--color-success)" : "var(--color-text)",
    },
  ];
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: "1rem",
        marginBottom: "1.5rem",
      }}
    >
      {items.map(({ label, value, color }) => (
        <div key={label} className="metric-card">
          <div className="metric-label">{label}</div>
          <div className="metric-value" style={{ color }}>
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recommendation card
// ---------------------------------------------------------------------------

function RecCard({
  r,
  pending,
  onAction,
}: {
  r: Recommendation;
  pending: number | null;
  onAction: (id: number, action: "dismissed" | "snoozed") => void;
}) {
  const hasCost = r.current_monthly_cost != null && r.recommended_monthly_cost != null;
  const savings = r.estimated_monthly_savings_usd;

  return (
    <div
      className="card"
      style={{
        padding: "1rem 1.25rem",
        borderRadius: "8px",
        background: "var(--color-surface)",
        borderLeft: `4px solid ${classColor(r.classification)}`,
        display: "flex",
        gap: "1.25rem",
        alignItems: "flex-start",
        flexWrap: "wrap",
      }}
    >
      {/* VM identity */}
      <div style={{ flex: "1 1 200px" }}>
        <div style={{ fontWeight: 600, fontSize: "0.95rem", color: "var(--color-text)" }}>
          {r.vm_name || r.vm_id}
        </div>
        <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "0.1rem" }}>
          {[r.project_name, r.region_id || "default", r.domain]
            .filter(Boolean)
            .join(" · ")}
        </div>
        <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)", marginTop: "0.05rem" }}>
          {r.vm_id}
        </div>
        <span
          style={{
            display: "inline-block",
            marginTop: "0.35rem",
            fontSize: "0.73rem",
            fontWeight: 600,
            color: classColor(r.classification),
            background: `${classColor(r.classification)}18`,
            borderRadius: "4px",
            padding: "0.1rem 0.45rem",
          }}
        >
          {classLabel(r.classification)}
        </span>
      </div>

      {/* Utilisation */}
      <div style={{ flex: "0 0 130px" }}>
        <div
          style={{
            fontSize: "0.72rem",
            color: "var(--color-text-muted)",
            marginBottom: "0.3rem",
            fontWeight: 500,
          }}
        >
          Utilisation (p95 · 7d)
        </div>
        <div style={{ fontSize: "0.85rem" }}>
          CPU: <strong>{formatPct(r.cpu_p95_7d)}</strong>
        </div>
        <div style={{ fontSize: "0.85rem" }}>
          RAM: <strong>{formatPct(r.ram_p95_7d)}</strong>
        </div>
        {r.cpu_avg_7d != null && (
          <div
            style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "0.2rem" }}
          >
            avg CPU {formatPct(r.cpu_avg_7d)} · avg RAM {formatPct(r.ram_avg_7d)}
          </div>
        )}
      </div>

      {/* Flavor change */}
      <div style={{ flex: "0 0 230px" }}>
        <div
          style={{
            fontSize: "0.72rem",
            color: "var(--color-text-muted)",
            marginBottom: "0.3rem",
            fontWeight: 500,
          }}
        >
          Flavor
        </div>
        <div style={{ fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
          {r.current_flavor || "—"}
          {r.current_vcpus != null && (
            <span style={{ fontSize: "0.75rem" }}>
              {" "}
              ({r.current_vcpus} vCPU · {formatRam(r.current_ram_mb)})
            </span>
          )}
        </div>
        {r.recommended_flavor && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.35rem",
              marginTop: "0.2rem",
            }}
          >
            <span style={{ fontSize: "0.78rem", color: "var(--color-text-muted)" }}>→</span>
            <span
              style={{ fontSize: "0.85rem", color: "var(--color-success)", fontWeight: 600 }}
            >
              {r.recommended_flavor}
              {r.recommended_vcpus != null && (
                <span style={{ fontWeight: 400, fontSize: "0.75rem" }}>
                  {" "}
                  ({r.recommended_vcpus} vCPU · {formatRam(r.recommended_ram_mb)})
                </span>
              )}
            </span>
          </div>
        )}
      </div>

      {/* Billing impact */}
      <div style={{ flex: "0 0 210px" }}>
        <div
          style={{
            fontSize: "0.72rem",
            color: "var(--color-text-muted)",
            marginBottom: "0.3rem",
            fontWeight: 500,
          }}
        >
          Monthly Cost Impact
        </div>
        {hasCost ? (
          <>
            <div
              style={{
                fontSize: "0.82rem",
                display: "flex",
                justifyContent: "space-between",
              }}
            >
              <span style={{ color: "var(--color-text-muted)" }}>Current</span>
              <span style={{ fontWeight: 600 }}>
                {formatCost(r.current_monthly_cost, r.currency)}
              </span>
            </div>
            <div
              style={{
                fontSize: "0.82rem",
                display: "flex",
                justifyContent: "space-between",
                marginTop: "0.15rem",
              }}
            >
              <span style={{ color: "var(--color-text-muted)" }}>Recommended</span>
              <span style={{ fontWeight: 600, color: "var(--color-success)" }}>
                {formatCost(r.recommended_monthly_cost, r.currency)}
              </span>
            </div>
            {savings != null && savings > 0 && (
              <div
                style={{
                  marginTop: "0.35rem",
                  paddingTop: "0.3rem",
                  borderTop: "1px solid var(--color-border, #e5e7eb)",
                  fontSize: "0.85rem",
                  fontWeight: 700,
                  color: "var(--color-success)",
                  display: "flex",
                  justifyContent: "space-between",
                }}
              >
                <span>Save</span>
                <span>{formatCost(savings, r.currency)}</span>
              </div>
            )}
          </>
        ) : savings != null && savings > 0 ? (
          <div
            style={{ fontSize: "0.95rem", fontWeight: 700, color: "var(--color-success)" }}
          >
            Save {formatCost(savings, r.currency)}
          </div>
        ) : (
          <div style={{ fontSize: "0.82rem", color: "var(--color-text-muted)" }}>—</div>
        )}
      </div>

      {/* Actions */}
      <div
        style={{
          flex: "0 0 auto",
          display: "flex",
          flexDirection: "column",
          gap: "0.4rem",
          justifyContent: "center",
          marginLeft: "auto",
        }}
      >
        <button
          className="btn btn-sm btn-secondary"
          disabled={pending === r.id}
          onClick={() => onAction(r.id, "snoozed")}
          style={{ minWidth: "90px" }}
        >
          Snooze
        </button>
        <button
          className="btn btn-sm btn-danger"
          disabled={pending === r.id}
          onClick={() => onAction(r.id, "dismissed")}
          style={{ minWidth: "90px" }}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  regionFilter?: string;
}

export default function RightsizingTab({ regionFilter }: Props) {
  const [summary, setSummary] = useState<RightsizingSummary | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [projectOptions, setProjectOptions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterClass, setFilterClass] = useState<string>("");
  const [filterProject, setFilterProject] = useState<string>("");
  const [actionPending, setActionPending] = useState<number | null>(null);

  // Load project dropdown once on mount
  useEffect(() => {
    apiFetch<string[]>("/api/rightsizing/projects")
      .then(setProjectOptions)
      .catch(() => {/* non-critical */});
  }, []);

  const buildQuery = useCallback(() => {
    const p: Record<string, string> = {};
    if (regionFilter) p.region = regionFilter;
    if (filterClass) p.classification = filterClass;
    if (filterProject) p.project = filterProject;
    return new URLSearchParams(p).toString();
  }, [regionFilter, filterClass, filterProject]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const regionQ = regionFilter ? `?region=${encodeURIComponent(regionFilter)}` : "";
      const [sumData, recsData] = await Promise.all([
        apiFetch<RightsizingSummary>(`/api/rightsizing/summary${regionQ}`),
        apiFetch<Recommendation[]>(`/api/rightsizing/recommendations?${buildQuery()}`),
      ]);
      setSummary(sumData);
      setRecs(recsData);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load rightsizing data");
    } finally {
      setLoading(false);
    }
  }, [regionFilter, buildQuery]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleAction = async (id: number, newStatus: "dismissed" | "snoozed") => {
    setActionPending(id);
    const dismissed = recs.find((r) => r.id === id);
    try {
      await apiFetch(`/api/rightsizing/recommendations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus }),
      });
      setRecs((prev) => prev.filter((r) => r.id !== id));
      if (summary && dismissed) {
        setSummary((s) =>
          s
            ? {
                ...s,
                total_open: Math.max(0, s.total_open - 1),
                idle_count:
                  dismissed.classification === "idle"
                    ? Math.max(0, s.idle_count - 1)
                    : s.idle_count,
                over_provisioned_count:
                  dismissed.classification === "over_provisioned"
                    ? Math.max(0, s.over_provisioned_count - 1)
                    : s.over_provisioned_count,
              }
            : s
        );
      }
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Action failed");
    } finally {
      setActionPending(null);
    }
  };

  return (
    <div className="tab-content">
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1rem",
          flexWrap: "wrap",
          gap: "0.5rem",
        }}
      >
        <h2 style={{ margin: 0 }}>Right-Sizing &amp; Cost Waste</h2>
        <button className="btn btn-secondary" onClick={loadData} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="alert alert-error" style={{ marginBottom: "1rem" }}>
          {error}
        </div>
      )}

      <SummaryCards summary={summary} />

      {/* Filters */}
      <div
        style={{
          display: "flex",
          gap: "1rem",
          marginBottom: "1.25rem",
          flexWrap: "wrap",
          alignItems: "flex-end",
        }}
      >
        <div>
          <label
            style={{
              display: "block",
              fontSize: "0.78rem",
              color: "var(--color-text-muted)",
              marginBottom: "0.2rem",
            }}
          >
            Classification
          </label>
          <select
            className="form-select"
            value={filterClass}
            onChange={(e) => setFilterClass(e.target.value)}
          >
            <option value="">All</option>
            <option value="idle">Idle</option>
            <option value="over_provisioned">Over-Provisioned</option>
          </select>
        </div>
        <div>
          <label
            style={{
              display: "block",
              fontSize: "0.78rem",
              color: "var(--color-text-muted)",
              marginBottom: "0.2rem",
            }}
          >
            Project
          </label>
          <select
            className="form-select"
            value={filterProject}
            onChange={(e) => setFilterProject(e.target.value)}
          >
            <option value="">All projects</option>
            {projectOptions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <button
          className="btn btn-primary"
          onClick={loadData}
          style={{ alignSelf: "flex-end" }}
        >
          Apply
        </button>
      </div>

      {/* Cards */}
      {loading ? (
        <div style={{ display: "grid", gap: "0.75rem" }}>
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="card skeleton"
              style={{
                height: "100px",
                borderRadius: "8px",
                background: "var(--color-surface)",
              }}
            />
          ))}
        </div>
      ) : recs.length === 0 ? (
        <div
          style={{
            padding: "3rem",
            textAlign: "center",
            color: "var(--color-text-muted)",
            background: "var(--color-surface)",
            borderRadius: "8px",
          }}
        >
          <div style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>✅</div>
          <div style={{ fontWeight: 600 }}>No open recommendations</div>
          <div style={{ fontSize: "0.875rem", marginTop: "0.25rem" }}>
            All VMs appear to be right-sized or recommendations have been dismissed.
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gap: "0.75rem" }}>
          {recs.map((r) => (
            <RecCard key={r.id} r={r} pending={actionPending} onAction={handleAction} />
          ))}
        </div>
      )}
    </div>
  );
}
