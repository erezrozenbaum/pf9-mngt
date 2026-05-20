/*
 * CostOptimization.tsx — Workload Right-Sizing & Cost Waste Detection
 * ====================================================================
 * Tenant-facing view of rightsizing recommendations for their own VMs.
 * Shows idle and over-provisioned VMs with before/after billing impact.
 * Tenants can request a resize, snooze, or dismiss recommendations.
 *
 * v2.3.0
 */
import { useEffect, useState, useCallback } from "react";
import {
  apiRightsizingSummary,
  apiRightsizingRecommendations,
  apiRightsizingUpdate,
  apiRightsizingRequestChange,
  type RightsizingSummary,
  type RightsizingRecommendation,
} from "../lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function classLabel(c: string): string {
  return c.replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function classColor(c: string): string {
  if (c === "idle") return "var(--color-error)";
  if (c === "over_provisioned") return "var(--color-warning)";
  return "var(--color-text)";
}

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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CostOptimization() {
  const [summary, setSummary] = useState<RightsizingSummary | null>(null);
  const [recs, setRecs] = useState<RightsizingRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<number | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);
  const [requestSent, setRequestSent] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const statusFilter = showDismissed ? "dismissed" : undefined;
      const [sum, list] = await Promise.all([
        apiRightsizingSummary(),
        apiRightsizingRecommendations(statusFilter),
      ]);
      setSummary(sum);
      setRecs(list);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load recommendations");
    } finally {
      setLoading(false);
    }
  }, [showDismissed]);

  useEffect(() => {
    load();
  }, [load]);

  const handleAction = async (id: number, action: "snoozed" | "dismissed") => {
    setPending(id);
    try {
      await apiRightsizingUpdate(id, action);
      setRecs((prev) => prev.filter((r) => r.id !== id));
      setSummary((s) =>
        s ? { ...s, total_open: Math.max(0, s.total_open - 1) } : s,
      );
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Action failed");
    } finally {
      setPending(null);
    }
  };

  const handleRequestChange = async (id: number) => {
    setPending(id);
    try {
      await apiRightsizingRequestChange(id);
      setRequestSent((prev) => new Set(prev).add(id));
      setRecs((prev) => prev.filter((r) => r.id !== id));
      setSummary((s) =>
        s ? { ...s, total_open: Math.max(0, s.total_open - 1) } : s,
      );
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to submit request");
    } finally {
      setPending(null);
    }
  };

  const totalSavings = summary?.total_estimated_savings_usd ?? 0;
  const currency = summary?.currency ?? "USD";

  return (
    <div style={{ padding: "1.5rem", maxWidth: "1200px" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: "1.5rem",
          flexWrap: "wrap",
          gap: "1rem",
        }}
      >
        <div>
          <h1
            style={{
              margin: 0,
              fontSize: "1.5rem",
              fontWeight: 700,
              color: "var(--color-text)",
            }}
          >
            Cost Optimisation
          </h1>
          <p
            style={{
              margin: "0.25rem 0 0",
              fontSize: "0.875rem",
              color: "var(--color-text-secondary)",
            }}
          >
            Rightsizing recommendations for your VMs based on 7-day utilisation data.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.85rem", color: "var(--color-text-secondary)", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={showDismissed}
              onChange={(e) => setShowDismissed(e.target.checked)}
            />
            Show dismissed
          </label>
          <button
            className="btn btn-secondary"
            onClick={load}
            disabled={loading}
            style={{ fontSize: "0.85rem" }}
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div
          className="alert"
          style={{
            background: "var(--color-error-bg, #fee2e2)",
            color: "var(--color-error, #dc2626)",
            padding: "0.75rem 1rem",
            borderRadius: "6px",
            marginBottom: "1rem",
            fontSize: "0.875rem",
          }}
        >
          {error}
        </div>
      )}

      {/* Summary strip */}
      {summary && !showDismissed && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            gap: "1rem",
            marginBottom: "1.5rem",
          }}
        >
          {[
            {
              label: "Open Findings",
              value: String(summary.total_open),
              color: summary.total_open > 0 ? "var(--color-warning)" : "var(--color-success)",
            },
            {
              label: "Idle VMs",
              value: String(summary.idle_count),
              color: summary.idle_count > 0 ? "var(--color-error)" : "var(--color-text)",
            },
            {
              label: "Over-Provisioned",
              value: String(summary.over_provisioned_count),
              color: summary.over_provisioned_count > 0 ? "var(--color-warning)" : "var(--color-text)",
            },
            {
              label: "Est. Savings",
              value: totalSavings > 0 ? `${currency} ${totalSavings.toFixed(0)}/mo` : "—",
              color: totalSavings > 0 ? "var(--color-success)" : "var(--color-text)",
            },
          ].map(({ label, value, color }) => (
            <div
              key={label}
              className="card"
              style={{
                padding: "1rem 1.25rem",
                borderRadius: "8px",
                background: "var(--color-surface)",
              }}
            >
              <div style={{ fontSize: "0.75rem", color: "var(--color-text-secondary)", marginBottom: "0.25rem" }}>
                {label}
              </div>
              <div style={{ fontSize: "1.4rem", fontWeight: 700, color }}>
                {value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Recommendations list */}
      {loading ? (
        <div
          style={{
            display: "grid",
            gap: "0.75rem",
          }}
        >
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="card skeleton"
              style={{ height: "110px", borderRadius: "8px", background: "var(--color-surface)" }}
            />
          ))}
        </div>
      ) : recs.length === 0 ? (
        <div
          style={{
            textAlign: "center",
            padding: "4rem 2rem",
            background: "var(--color-surface)",
            borderRadius: "10px",
          }}
        >
          <div style={{ fontSize: "3rem", marginBottom: "0.5rem" }}>
            {showDismissed ? "📋" : "✅"}
          </div>
          <div style={{ fontWeight: 600, fontSize: "1.05rem", color: "var(--color-text)" }}>
            {showDismissed ? "No dismissed recommendations" : "All your VMs are well-sized"}
          </div>
          <div
            style={{
              fontSize: "0.875rem",
              color: "var(--color-text-secondary)",
              marginTop: "0.25rem",
            }}
          >
            {showDismissed
              ? "You haven't dismissed any recommendations yet."
              : "No idle or over-provisioned VMs detected in the last 7 days."}
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gap: "0.75rem" }}>
          {requestSent.size > 0 && (
            <div
              style={{
                background: "var(--color-success-bg, #dcfce7)",
                color: "var(--color-success, #16a34a)",
                padding: "0.75rem 1rem",
                borderRadius: "6px",
                fontSize: "0.875rem",
              }}
            >
              Your resize request has been submitted. A member of our team will contact you shortly.
            </div>
          )}
          {recs.map((r) => {
            const hasCost =
              r.current_monthly_cost != null && r.recommended_monthly_cost != null;
            const savings = r.estimated_monthly_savings_usd;
            return (
              <div
                key={r.id}
                className="card"
                style={{
                  padding: "1rem 1.25rem",
                  borderRadius: "8px",
                  background: "var(--color-surface)",
                  borderLeft: `4px solid ${classColor(r.classification)}`,
                  display: "flex",
                  gap: "1rem",
                  alignItems: "flex-start",
                  flexWrap: "wrap",
                }}
              >
                {/* VM info */}
                <div style={{ flex: "1 1 190px" }}>
                  <div style={{ fontWeight: 600, fontSize: "0.95rem", color: "var(--color-text)" }}>
                    {r.vm_name || r.vm_id}
                  </div>
                  <div
                    style={{
                      fontSize: "0.75rem",
                      color: "var(--color-text-secondary)",
                      marginTop: "0.1rem",
                    }}
                  >
                    {[r.project_name, r.region_id].filter(Boolean).join(" · ")}
                  </div>
                  <span
                    style={{
                      display: "inline-block",
                      marginTop: "0.35rem",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      color: classColor(r.classification),
                      background: `${classColor(r.classification)}18`,
                      borderRadius: "4px",
                      padding: "0.1rem 0.5rem",
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
                      color: "var(--color-text-secondary)",
                      marginBottom: "0.3rem",
                      fontWeight: 500,
                    }}
                  >
                    Utilisation (p95 7d)
                  </div>
                  <div style={{ fontSize: "0.85rem" }}>
                    CPU: <strong>{formatPct(r.cpu_p95_7d)}</strong>
                  </div>
                  <div style={{ fontSize: "0.85rem" }}>
                    RAM: <strong>{formatPct(r.ram_p95_7d)}</strong>
                  </div>
                </div>

                {/* Flavor change */}
                <div style={{ flex: "0 0 210px" }}>
                  <div
                    style={{
                      fontSize: "0.72rem",
                      color: "var(--color-text-secondary)",
                      marginBottom: "0.3rem",
                      fontWeight: 500,
                    }}
                  >
                    Flavor
                  </div>
                  <div style={{ fontSize: "0.85rem", color: "var(--color-text-secondary)" }}>
                    {r.current_flavor || "—"}
                    {r.current_vcpus != null && (
                      <span style={{ fontSize: "0.75rem" }}>
                        {" "}({r.current_vcpus} vCPU · {formatRam(r.current_ram_mb)})
                      </span>
                    )}
                  </div>
                  {r.recommended_flavor && (
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.3rem",
                        marginTop: "0.2rem",
                      }}
                    >
                      <span style={{ fontSize: "0.78rem", color: "var(--color-text-secondary)" }}>
                        →
                      </span>
                      <span
                        style={{
                          fontSize: "0.85rem",
                          color: "var(--color-success)",
                          fontWeight: 600,
                        }}
                      >
                        {r.recommended_flavor}
                        {r.recommended_vcpus != null && (
                          <span style={{ fontWeight: 400, fontSize: "0.75rem" }}>
                            {" "}({r.recommended_vcpus} vCPU · {formatRam(r.recommended_ram_mb)})
                          </span>
                        )}
                      </span>
                    </div>
                  )}
                </div>

                {/* Billing impact */}
                <div style={{ flex: "0 0 195px" }}>
                  <div
                    style={{
                      fontSize: "0.72rem",
                      color: "var(--color-text-secondary)",
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
                        <span style={{ color: "var(--color-text-secondary)" }}>Current</span>
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
                        <span style={{ color: "var(--color-text-secondary)" }}>
                          Recommended
                        </span>
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
                      style={{
                        fontSize: "1rem",
                        fontWeight: 700,
                        color: "var(--color-success)",
                      }}
                    >
                      Save {formatCost(savings, r.currency)}
                    </div>
                  ) : (
                    <div style={{ fontSize: "0.82rem", color: "var(--color-text-secondary)" }}>
                      —
                    </div>
                  )}
                </div>

                {/* Actions — only show for open/snoozed */}
                {r.status !== "dismissed" && (
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
                      className="btn btn-sm btn-primary"
                      disabled={pending === r.id}
                      onClick={() => handleRequestChange(r.id)}
                      style={{ fontSize: "0.8rem", minWidth: "110px" }}
                    >
                      Request Resize
                    </button>
                    <button
                      className="btn btn-sm btn-secondary"
                      disabled={pending === r.id}
                      onClick={() => handleAction(r.id, "snoozed")}
                      style={{ fontSize: "0.8rem", minWidth: "110px" }}
                    >
                      Snooze
                    </button>
                    <button
                      className="btn btn-sm btn-ghost"
                      disabled={pending === r.id}
                      onClick={() => handleAction(r.id, "dismissed")}
                      style={{
                        fontSize: "0.8rem",
                        minWidth: "110px",
                        color: "var(--color-text-secondary)",
                      }}
                    >
                      Dismiss
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
