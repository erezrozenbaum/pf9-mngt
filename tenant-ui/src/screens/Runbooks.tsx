import { useEffect, useState } from "react";
import { apiRunbooks, apiRunbook, type Runbook } from "../lib/api";

// ── Helpers ─────────────────────────────────────────────────────────────────

function RiskBadge({ level }: { level: string }) {
  const l = level.toLowerCase();
  if (l === "low")    return <span className="badge badge-green">Low risk</span>;
  if (l === "medium") return <span className="badge badge-amber">Medium risk</span>;
  if (l === "high")   return <span className="badge badge-red">High risk</span>;
  return <span className="badge badge-grey">{level}</span>;
}

function categoryIcon(cat: string): string {
  const c = cat.toLowerCase();
  if (c.includes("trouble"))  return "🔍";
  if (c.includes("recovery")) return "🔄";
  if (c.includes("restore"))  return "📋";
  if (c.includes("incident")) return "⚠️";
  return "📖";
}

// ── Main component ───────────────────────────────────────────────────────────

export function Runbooks() {
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Runbook | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState("");

  useEffect(() => {
    let active = true;
    apiRunbooks()
      .then((r) => { if (active) setRunbooks(r); })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const openDetail = async (rb: Runbook) => {
    setDetailLoading(true);
    try {
      setSelected(await apiRunbook(rb.name));
    } catch {
      setSelected(rb);          // fall back to list data
    } finally {
      setDetailLoading(false);
    }
  };

  if (loading) return <div className="empty-state"><span className="loading-spinner" /></div>;
  if (error)   return <div className="error-banner">{error}</div>;

  const categories = [...new Set(runbooks.map((r) => r.category))].sort();
  const filtered   = categoryFilter ? runbooks.filter((r) => r.category === categoryFilter) : runbooks;

  return (
    <div>
      <div className="filter-bar">
        <select className="select" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <span style={{ fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
          {filtered.length} runbook{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">No runbooks available for your environment yet.</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "1rem" }}>
          {filtered.map((rb) => (
            <div
              key={rb.name}
              className="card"
              style={{ cursor: "pointer", display: "flex", flexDirection: "column", gap: ".5rem" }}
              onClick={() => openDetail(rb)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") openDetail(rb); }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: ".5rem" }}>
                <span style={{ fontSize: "1.15rem" }} aria-hidden="true">{categoryIcon(rb.category)}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: ".9rem", marginBottom: ".15rem" }}>{rb.display_name}</div>
                  <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>{rb.category}</div>
                </div>
                <RiskBadge level={rb.risk_level} />
              </div>
              <div style={{ fontSize: ".8125rem", color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                {rb.description}
              </div>
              <div style={{ fontSize: ".7rem", color: "var(--color-text-secondary)", marginTop: "auto" }}>
                Updated: {new Date(rb.updated_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Detail side panel ── */}
      {(selected !== null || detailLoading) && (
        <>
          <div className="side-panel-overlay" onClick={() => { if (!detailLoading) setSelected(null); }} />
          <aside className="side-panel" aria-label="Runbook detail">
            {detailLoading ? (
              <div className="empty-state"><span className="loading-spinner" /></div>
            ) : selected && (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: ".75rem", marginBottom: "1.25rem" }}>
                  <div style={{ flex: 1 }}>
                    <h2 style={{ fontSize: "1.125rem", fontWeight: 700 }}>{selected.display_name}</h2>
                    <div style={{ display: "flex", gap: ".5rem", marginTop: ".4rem", flexWrap: "wrap" }}>
                      <span className="badge badge-blue">{selected.category}</span>
                      <RiskBadge level={selected.risk_level} />
                    </div>
                  </div>
                  <button
                    className="btn btn-secondary"
                    onClick={() => setSelected(null)}
                    aria-label="Close"
                    style={{ padding: ".35rem .65rem", flexShrink: 0 }}
                  >
                    ✕
                  </button>
                </div>

                <p style={{ fontSize: ".875rem", color: "var(--color-text-secondary)", marginBottom: "1.25rem", lineHeight: 1.6 }}>
                  {selected.description}
                </p>

                {selected.prerequisites && (
                  <div style={{ marginBottom: "1.25rem" }}>
                    <div className="section-title">Prerequisites</div>
                    <p style={{ fontSize: ".875rem", lineHeight: 1.6 }}>{selected.prerequisites}</p>
                  </div>
                )}

                <div style={{ marginBottom: "1.25rem" }}>
                  <div className="section-title">Steps</div>
                  <ol style={{ paddingLeft: "1.25rem", display: "flex", flexDirection: "column", gap: ".6rem" }}>
                    {selected.steps.map((step, i) => (
                      <li key={i} style={{ fontSize: ".875rem", lineHeight: 1.6 }}>{step}</li>
                    ))}
                  </ol>
                </div>

                {selected.expected_outcome && (
                  <div style={{ background: "var(--color-surface-elevated)", borderRadius: "var(--radius-sm)", padding: ".75rem", marginBottom: "1rem" }}>
                    <div style={{ fontSize: ".8125rem", fontWeight: 600, marginBottom: ".25rem" }}>Expected outcome</div>
                    <p style={{ fontSize: ".875rem", color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
                      {selected.expected_outcome}
                    </p>
                  </div>
                )}

                <div className="info-banner">
                  These runbooks are for reference only. Contact your support team to execute operational procedures.
                </div>
              </>
            )}
          </aside>
        </>
      )}
    </div>
  );
}
