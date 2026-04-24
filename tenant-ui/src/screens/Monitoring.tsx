import { useEffect, useState } from "react";
import { apiAvailability, apiMetricsVms, type AvailabilityRow, type VmMetrics } from "../lib/api";

// ── Helpers ─────────────────────────────────────────────────────────────────

function uptimeColor(pct: number | null): string {
  if (pct === null) return "var(--color-text-secondary)";
  if (pct >= 99)   return "var(--color-success)";
  if (pct >= 90)   return "var(--color-warning)";
  return "var(--color-error)";
}

function MetricItem({ label, value, unit = "%", alloc }: { label: string; value: number | null; unit?: string; alloc?: string }) {
  const display = value !== null ? `${value.toFixed(unit === "%" ? 0 : 1)}${unit}` : (alloc ?? "—");
  const barPct   = (value !== null && unit === "%") ? Math.min(value, 100) : null;
  const dimmed   = value === null;
  const color    = barPct !== null
    ? (barPct >= 90 ? "var(--color-error)" : barPct >= 70 ? "var(--color-warning)" : "var(--brand-primary)")
    : "var(--brand-primary)";

  return (
    <div style={{ paddingBottom: ".5rem", borderBottom: "1px solid var(--color-border)", marginBottom: ".5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: ".8125rem", marginBottom: barPct !== null ? ".2rem" : 0 }}>
        <span style={{ color: "var(--color-text-secondary)" }}>{label}</span>
        <span style={{ fontWeight: 600, color: dimmed ? "var(--color-text-secondary)" : (barPct !== null ? color : "var(--color-text)") }}>{display}</span>
      </div>
      {barPct !== null && (
        <div className="progress-track" style={{ height: "5px" }}>
          <div className="progress-fill" style={{ width: `${barPct}%`, background: color }} />
        </div>
      )}
    </div>
  );
}

function VmMetricsCard({ m }: { m: VmMetrics }) {
  const ramGb = m.ram_total_mb != null ? `${(m.ram_total_mb / 1024).toFixed(0)} GB` : undefined;
  const diskGb = m.storage_total_gb != null ? `${m.storage_total_gb} GB` : undefined;
  const cpuAlloc = m.vcpus != null ? `${m.vcpus} vCPU` : undefined;
  return (
    <div className="card" style={{ padding: "1rem" }}>
      <div style={{ fontWeight: 600, fontSize: ".9rem", marginBottom: ".75rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {m.vm_name}
      </div>
      <MetricItem label="CPU"           value={m.cpu_pct} alloc={cpuAlloc} />
      <MetricItem label="RAM"           value={m.ram_pct} alloc={ramGb} />
      <MetricItem label="Storage"       value={m.storage_pct} alloc={diskGb} />
      {(m.iops_read !== null || m.iops_write !== null) && (
        <MetricItem
          label="IOPS (r+w)"
          value={(m.iops_read ?? 0) + (m.iops_write ?? 0)}
          unit=""
        />
      )}
      {m.last_updated && (
        <div style={{ fontSize: ".7rem", color: "var(--color-text-secondary)", marginTop: ".25rem" }}>
          Updated: {new Date(m.last_updated).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface Props {
  regionFilter: string;
}

export function Monitoring({ regionFilter }: Props) {
  const [availability, setAvailability] = useState<AvailabilityRow[]>([]);
  const [metrics, setMetrics] = useState<VmMetrics[]>([]);
  const [cacheAvailable, setCacheAvailable] = useState(true);
  const [monitoringSource, setMonitoringSource] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"availability" | "usage">("availability");

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([apiAvailability(), apiMetricsVms()])
      .then(([a, m]) => {
        if (!active) return;
        setAvailability(a);
        setMetrics(m.vms);
        setCacheAvailable(m.cacheAvailable);
        setMonitoringSource(m.monitoringSource);
      })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  if (loading) return <div className="empty-state"><span className="loading-spinner" /></div>;
  if (error)   return <div className="error-banner">{error}</div>;

  const filteredAvail = regionFilter
    ? availability.filter((a) => a.region_display_name === regionFilter)
    : availability;

  const filteredMetrics = regionFilter
    ? metrics.filter((m) => {
        // metrics don't carry region_display_name; cross-reference with availability
        const match = availability.find((a) => a.vm_id === m.vm_id);
        return match ? match.region_display_name === regionFilter : true;
      })
    : metrics;

  return (
    <div>
      <div className="tabs">
        <button className={`tab-btn${tab === "availability" ? " active" : ""}`} onClick={() => setTab("availability")}>
          Availability
        </button>
        <button className={`tab-btn${tab === "usage" ? " active" : ""}`} onClick={() => setTab("usage")}>
          Current Usage
        </button>
      </div>

      {/* ── Availability tab ── */}
      {tab === "availability" && (
        <div className="card table-wrap" style={{ padding: 0 }}>
          {filteredAvail.length === 0 ? (
            <div className="empty-state">No availability data.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>VM</th>
                  <th>Region</th>
                  <th>7d Uptime</th>
                  <th>30d Uptime</th>
                  <th>Status</th>
                  <th>Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {filteredAvail.map((a) => (
                  <tr key={a.vm_id}>
                    <td style={{ fontWeight: 500 }}>{a.vm_name}</td>
                    <td>{a.region_display_name}</td>
                    <td>
                      {a.uptime_7d_pct !== null
                        ? <span style={{ fontWeight: 600, color: uptimeColor(a.uptime_7d_pct) }}>{a.uptime_7d_pct.toFixed(1)}%</span>
                        : "—"}
                    </td>
                    <td>
                      {a.uptime_30d_pct !== null
                        ? <span style={{ fontWeight: 600, color: uptimeColor(a.uptime_30d_pct) }}>{a.uptime_30d_pct.toFixed(1)}%</span>
                        : "—"}
                    </td>
                    <td>
                      {a.status === "up"
                        ? <span className="badge badge-green">Up</span>
                        : a.status === "down"
                        ? <span className="badge badge-red">Down</span>
                        : <span className="badge badge-grey">{a.status}</span>}
                    </td>
                    <td>{a.last_seen ? new Date(a.last_seen).toLocaleString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Usage tab ── */}
      {tab === "usage" && (
        filteredMetrics.length === 0 ? (
          <div className="empty-state">
            {!cacheAvailable
              ? "Monitoring service is unreachable. Check that the pf9-monitoring pod is running."
              : "No metrics collected yet. Ensure PF9_HOSTS is configured and the monitoring service can reach the hypervisor nodes."}
          </div>
        ) : (
          <>
            {monitoringSource === "gnocchi" && (
              <div style={{ margin: ".75rem 0", padding: ".6rem 1rem", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "6px", fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
                ✅ Showing <strong>live Platform9 telemetry</strong> (Gnocchi/Ceilometer). CPU&nbsp;%, memory MB, IOPS, and network throughput are real-time values from the OpenStack compute agent.
              </div>
            )}
            {monitoringSource === "allocation" && (
              <div style={{ margin: ".75rem 0", padding: ".6rem 1rem", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "6px", fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
                ℹ️ Showing <strong>allocation-based usage</strong> (vCPU / RAM share of hypervisor capacity; disk from flavor). Live CPU &amp; RAM usage requires Prometheus node-exporter on the hypervisor nodes.
              </div>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "1rem" }}>
              {filteredMetrics.map((m) => <VmMetricsCard key={m.vm_id} m={m} />)}
            </div>
          </>
        )
      )}
    </div>
  );
}
