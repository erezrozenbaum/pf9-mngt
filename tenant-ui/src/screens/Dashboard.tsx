import { useEffect, useState, useMemo } from "react";
import {
  apiDashboard, apiEvents, apiSnapshotHistoryRaw, apiQuota,
  type DashboardData, type TenantEvent, type QuotaData,
} from "../lib/api";
import { BarChart, DonutChart, QuotaBar, type BarDay } from "../components/Charts";

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

function isSkipped(ev: TenantEvent): boolean {
  return !ev.success && (ev.details as Record<string, unknown> | null)?.status === "SKIPPED";
}

function dotColor(ev: TenantEvent): string {
  if (isSkipped(ev)) return "var(--color-warning)";
  if (!ev.success) return "var(--color-error)";
  if (ev.action.includes("restore")) return "var(--brand-primary)";
  if (ev.action.includes("snapshot")) return "var(--color-success)";
  return "var(--color-info)";
}

// Build last-N-days bar data from snapshot history records
function buildBarData(records: Array<{ created_at: string; status: string }>, days = 14): BarDay[] {
  const map = new Map<string, { success: number; fail: number }>();
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const key = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    map.set(key, { success: 0, fail: 0 });
  }
  for (const r of records) {
    try {
      const d = new Date(r.created_at);
      const key = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
      if (!map.has(key)) continue;
      const entry = map.get(key)!;
      if (r.status === "OK") entry.success++;
      else if (r.status === "ERROR") entry.fail++;
    } catch { /* skip */ }
  }
  return Array.from(map.entries()).map(([label, v]) => ({ label, ...v }));
}

interface Props {
  regionFilter: string;
}

export function Dashboard({ regionFilter }: Props) {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [events, setEvents] = useState<TenantEvent[]>([]);
  const [snapHistory, setSnapHistory] = useState<Array<{ created_at: string; status: string }>>([]);
  const [quota, setQuota] = useState<QuotaData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    // Load quota in parallel but non-blocking (quota failure shouldn't break dashboard)
    apiQuota().then((q) => { if (active) setQuota(q); }).catch(() => {});
    Promise.all([
      apiDashboard(),
      apiEvents(),
      apiSnapshotHistoryRaw(500),
    ])
      .then(([d, e, h]) => {
        if (!active) return;
        setDashboard(d);
        setEvents(e.slice(0, 20));
        setSnapHistory(h);
      })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const barData = useMemo(() => buildBarData(snapHistory, 14), [snapHistory]);

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

  // VM status donut slices
  const vmSlices = [
    { label: "Running",  value: dashboard.vms_running,  color: "var(--color-success)" },
    { label: "Stopped",  value: dashboard.vms_stopped,  color: "var(--color-text-secondary)" },
    { label: "Error",    value: dashboard.vms_error,    color: "var(--color-error)" },
    { label: "Other",    value: Math.max(0, dashboard.total_vms - dashboard.vms_running - dashboard.vms_stopped - dashboard.vms_error), color: "var(--color-info)" },
  ].filter((s) => s.value > 0);

  const hasBarData = barData.some((d) => d.success + d.fail > 0);

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

      {/* ── Charts row ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>

        {/* Snapshot trend bar chart */}
        {hasBarData && (
          <div className="card" style={{ padding: "1rem" }}>
            <div style={{ fontWeight: 600, fontSize: ".875rem", marginBottom: ".5rem" }}>Snapshot Activity (14d)</div>
            <BarChart data={barData} height={90} />
            <div style={{ display: "flex", gap: "1rem", marginTop: ".5rem", fontSize: ".75rem" }}>
              <span><span style={{ color: "var(--color-success)" }}>■</span> Success</span>
              <span><span style={{ color: "var(--color-error)" }}>■</span> Failed</span>
            </div>
          </div>
        )}

        {/* VM status donut */}
        {vmSlices.length > 0 && (
          <div className="card" style={{ padding: "1rem", display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
            <div style={{ fontWeight: 600, fontSize: ".875rem", marginBottom: ".5rem" }}>VM Status</div>
            <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
              <DonutChart
                slices={vmSlices}
                size={90}
                thickness={16}
                centerLabel={String(dashboard.total_vms)}
                centerSub="VMs"
              />
              <div style={{ fontSize: ".8rem", display: "flex", flexDirection: "column", gap: ".35rem" }}>
                {vmSlices.map((s) => (
                  <span key={s.label} style={{ display: "flex", alignItems: "center", gap: ".35rem" }}>
                    <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: s.color, flexShrink: 0 }} />
                    {s.value} {s.label}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Quota usage */}
        {quota && (
          <div className="card" style={{ padding: "1rem" }}>
            <div style={{ fontWeight: 600, fontSize: ".875rem", marginBottom: ".75rem" }}>Quota Usage</div>
            <QuotaBar label="Instances"  used={quota.totals.compute.instances.used}  limit={quota.totals.compute.instances.limit} />
            <QuotaBar label="vCPUs"      used={quota.totals.compute.cores.used}      limit={quota.totals.compute.cores.limit} />
            <QuotaBar label="RAM"        used={quota.totals.compute.ram_mb.used}     limit={quota.totals.compute.ram_mb.limit} unit="MB" />
            <QuotaBar label="Volumes"    used={quota.totals.storage.volumes.used}    limit={quota.totals.storage.volumes.limit} />
            <QuotaBar label="Storage"    used={quota.totals.storage.gigabytes.used}  limit={quota.totals.storage.gigabytes.limit} unit="GB" />
            <QuotaBar label="Snapshots"  used={quota.totals.storage.snapshots.used}  limit={quota.totals.storage.snapshots.limit} />
          </div>
        )}
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
                    isSkipped(ev)
                      ? <div style={{ fontSize: ".75rem", color: "var(--color-warning)", marginTop: ".1rem" }}>Skipped</div>
                      : <div style={{ fontSize: ".75rem", color: "var(--color-error)", marginTop: ".1rem" }}>Failed</div>
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
