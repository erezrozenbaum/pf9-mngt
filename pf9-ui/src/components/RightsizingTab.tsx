/*
 * RightsizingTab.tsx — Workload Right-Sizing & Cost Waste Detection
 * ===================================================================
 * Displays VM rightsizing recommendations for admins.
 * Shows idle and over-provisioned VMs with estimated monthly savings,
 * and allows dismiss / snooze actions.
 *
 * v2.6.0
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
  currency: string;
  status: string;
  computed_at: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function classificationBadge(c: string) {
  const map: Record<string, string> = {
    idle: "badge-error",
    over_provisioned: "badge-warning",
    right_sized: "badge-success",
    under_provisioned: "badge-info",
  };
  const cls = map[c] ?? "badge-neutral";
  return (
    <span className={`status-badge ${cls}`} style={{ textTransform: "capitalize" }}>
      {c.replace(/_/g, " ")}
    </span>
  );
}

function formatRam(mb: number | null): string {
  if (mb === null) return "—";
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
}

function formatSavings(usd: number | null, currency: string): string {
  if (!usd || usd <= 0) return "—";
  return `${currency} ${usd.toFixed(0)}/mo`;
}

function formatPct(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${Number(v).toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Summary cards
// ---------------------------------------------------------------------------

interface SummaryProps {
  summary: RightsizingSummary | null;
}

function SummaryCards({ summary }: SummaryProps) {
  if (!summary) return null;
  const cur = summary.currency;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: "1rem",
        marginBottom: "1.5rem",
      }}
    >
      <div className="metric-card">
        <div className="metric-label">Open Recommendations</div>
        <div className="metric-value">{summary.total_open}</div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Idle VMs</div>
        <div className="metric-value" style={{ color: "var(--color-error)" }}>
          {summary.idle_count}
        </div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Over-Provisioned VMs</div>
        <div className="metric-value" style={{ color: "var(--color-warning)" }}>
          {summary.over_provisioned_count}
        </div>
      </div>
      <div className="metric-card">
        <div className="metric-label">Est. Monthly Savings</div>
        <div className="metric-value" style={{ color: "var(--color-success)" }}>
          {summary.total_estimated_savings_usd > 0
            ? `${cur} ${summary.total_estimated_savings_usd.toFixed(0)}`
            : "—"}
        </div>
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterClass, setFilterClass] = useState<string>("");
  const [filterProject, setFilterProject] = useState<string>("");
  const [actionPending, setActionPending] = useState<number | null>(null);

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
    try {
      await apiFetch(`/api/rightsizing/recommendations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus }),
      });
      setRecs((prev) => prev.filter((r) => r.id !== id));
      if (summary) {
        setSummary((s) =>
          s
            ? {
                ...s,
                total_open: Math.max(0, s.total_open - 1),
                idle_count:
                  recs.find((r) => r.id === id)?.classification === "idle"
                    ? Math.max(0, s.idle_count - 1)
                    : s.idle_count,
                over_provisioned_count:
                  recs.find((r) => r.id === id)?.classification === "over_provisioned"
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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
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
      <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem", flexWrap: "wrap" }}>
        <div>
          <label style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
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
          <label style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
            Project
          </label>
          <input
            className="form-input"
            placeholder="Filter by project…"
            value={filterProject}
            onChange={(e) => setFilterProject(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && loadData()}
          />
        </div>
        <div style={{ alignSelf: "flex-end" }}>
          <button className="btn btn-primary" onClick={loadData}>
            Apply
          </button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div style={{ padding: "2rem", textAlign: "center", color: "var(--color-text-muted)" }}>
          Loading recommendations…
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
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>VM</th>
                <th>Project</th>
                <th>Region</th>
                <th>Classification</th>
                <th>Current Flavor</th>
                <th>Recommended</th>
                <th>CPU p95 (7d)</th>
                <th>RAM p95 (7d)</th>
                <th>Est. Savings</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {recs.map((r) => (
                <tr key={r.id}>
                  <td>
                    <div style={{ fontWeight: 500 }}>{r.vm_name || r.vm_id}</div>
                    <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                      {r.vm_id}
                    </div>
                  </td>
                  <td>{r.project_name || "—"}</td>
                  <td>{r.region_id || "default"}</td>
                  <td>{classificationBadge(r.classification)}</td>
                  <td>
                    {r.current_flavor ? (
                      <span>
                        {r.current_flavor}
                        <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                          {r.current_vcpus} vCPU · {formatRam(r.current_ram_mb)}
                        </div>
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>
                    {r.recommended_flavor ? (
                      <span style={{ color: "var(--color-success)", fontWeight: 500 }}>
                        {r.recommended_flavor}
                        <div style={{ fontSize: "0.75rem" }}>
                          {r.recommended_vcpus} vCPU · {formatRam(r.recommended_ram_mb)}
                        </div>
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{formatPct(r.cpu_p95_7d)}</td>
                  <td>{formatPct(r.ram_p95_7d)}</td>
                  <td>
                    <span
                      style={{
                        color:
                          r.estimated_monthly_savings_usd && r.estimated_monthly_savings_usd > 0
                            ? "var(--color-success)"
                            : undefined,
                        fontWeight: r.estimated_monthly_savings_usd ? 600 : undefined,
                      }}
                    >
                      {formatSavings(r.estimated_monthly_savings_usd, r.currency)}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <button
                        className="btn btn-sm btn-secondary"
                        disabled={actionPending === r.id}
                        onClick={() => handleAction(r.id, "snoozed")}
                        title="Snooze for now"
                      >
                        Snooze
                      </button>
                      <button
                        className="btn btn-sm btn-danger"
                        disabled={actionPending === r.id}
                        onClick={() => handleAction(r.id, "dismissed")}
                        title="Dismiss permanently"
                      >
                        Dismiss
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
