import { useEffect, useState } from "react";
import { apiDashboard, apiEvents, type DashboardData, type TenantEvent } from "../lib/api";

function formatHoursAgo(hours: number | null): string {
  if (hours === null) return "Never";
  if (hours < 1) return "< 1h ago";
  if (hours < 24) return `${Math.round(hours)}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

function actionLabel(action: string): string {
  return action
    .replace(/^tenant_/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function dotColor(ev: TenantEvent): string {
  if (!ev.success) return "var(--color-error)";
  if (ev.action.includes("restore")) return "var(--brand-primary)";
  if (ev.action.includes("snapshot")) return "var(--color-success)";
  return "var(--color-info)";
}

interface Props {
  regionFilter: string;
}

export function Dashboard({ regionFilter }: Props) {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [events, setEvents] = useState<TenantEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([apiDashboard(), apiEvents()])
      .then(([d, e]) => {
        if (!active) return;
        setDashboard(d);
        setEvents(e.slice(0, 20));
      })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  if (loading) return <div className="empty-state"><span className="loading-spinner" /></div>;
  if (error)   return <div className="error-banner">{error}</div>;
  if (!dashboard) return null;

  const regions = regionFilter
    ? dashboard.regions.filter((r) => r.region_display_name === regionFilter)
    : dashboard.regions;

  const compColor =
    dashboard.compliance_pct >= 90 ? "var(--color-success)" :
    dashboard.compliance_pct >= 70 ? "var(--color-warning)" :
    "var(--color-error)";

  return (
    <div>
      {/* ── Stats cards ── */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">VMs</div>
          <div className="stat-value">{dashboard.total_vms}</div>
          <div className="stat-sub">
            <span style={{ color: "var(--color-success)" }}>{dashboard.vms_running} running</span>
            {dashboard.vms_stopped > 0 && (
              <span style={{ color: "var(--color-text-secondary)", marginLeft: "8px" }}>{dashboard.vms_stopped} stopped</span>
            )}
            {dashboard.vms_error > 0 && (
              <span style={{ color: "var(--color-error)", marginLeft: "8px" }}>{dashboard.vms_error} error</span>
            )}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Snapshot Coverage</div>
          <div className="stat-value" style={{ color: compColor }}>
            {dashboard.compliance_pct.toFixed(0)}%
          </div>
          <div className="stat-sub">Last: {formatHoursAgo(dashboard.last_snapshot_hours_ago)}</div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Active Restores</div>
          <div className="stat-value">{dashboard.active_restores}</div>
          <div className="stat-sub">In progress</div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Issues (24h)</div>
          <div className="stat-value" style={{
            color: dashboard.failed_snapshots_24h > 0 ? "var(--color-error)" : "var(--color-success)",
          }}>
            {dashboard.failed_snapshots_24h}
          </div>
          <div className="stat-sub">Failed snapshots</div>
        </div>
      </div>

      {/* ── Coverage by region ── */}
      {regions.length > 0 && (
        <div style={{ marginBottom: "1.5rem" }}>
          <div className="section-title">Coverage by Region</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: ".75rem" }}>
            {regions.map((r) => {
              const pct = r.compliance_pct;
              const c =
                pct >= 90 ? "var(--color-success)" :
                pct >= 70 ? "var(--color-warning)" :
                "var(--color-error)";
              return (
                <div key={r.region_display_name} className="card" style={{ padding: "1rem" }}>
                  <div style={{ fontWeight: 600, fontSize: ".875rem", marginBottom: ".35rem" }}>
                    {r.region_display_name}
                  </div>
                  <div style={{ fontSize: ".8rem", color: "var(--color-text-secondary)", marginBottom: ".5rem" }}>
                    {r.vm_count} VM{r.vm_count !== 1 ? "s" : ""}
                  </div>
                  <div className="progress-track" style={{ marginBottom: ".3rem" }}>
                    <div className="progress-fill" style={{ width: `${pct}%`, background: c }} />
                  </div>
                  <div style={{ fontSize: ".75rem", color: c, fontWeight: 600 }}>{pct.toFixed(0)}% coverage</div>
                  {r.last_snapshot_ts && (
                    <div style={{ fontSize: ".7rem", color: "var(--color-text-secondary)", marginTop: ".25rem" }}>
                      Last: {formatTs(r.last_snapshot_ts)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Event timeline ── */}
      <div className="section-title">Last 24 Hours</div>
      {events.length === 0 ? (
        <div className="card empty-state" style={{ padding: "1.5rem" }}>
          No recent activity. Your environment is quiet.
        </div>
      ) : (
        <div className="card">
          <div className="timeline">
            {events.map((ev, i) => (
              <div key={`${ev.timestamp}-${i}`} className="timeline-item">
                <div className="timeline-dot" style={{ background: dotColor(ev) }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: ".875rem",
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "1rem",
                    flexWrap: "wrap",
                  }}>
                    <span>
                      {actionLabel(ev.action)}
                      {ev.resource_id && (
                        <span style={{ color: "var(--color-text-secondary)", marginLeft: ".4rem" }}>
                          · {ev.resource_id.slice(0, 12)}
                        </span>
                      )}
                    </span>
                    <span style={{ color: "var(--color-text-secondary)", fontSize: ".8rem", flexShrink: 0 }}>
                      {formatTs(ev.timestamp)}
                    </span>
                  </div>
                  {!ev.success && (
                    <div style={{ fontSize: ".75rem", color: "var(--color-error)", marginTop: ".1rem" }}>Failed</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
