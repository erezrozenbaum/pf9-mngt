import { useEffect, useState } from "react";
import { apiVms, apiVolumes, apiMetricsVm, type Vm, type Volume, type VmMetrics } from "../lib/api";

// ── Helpers ─────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "active" || s === "running") return <span className="badge badge-green">Running</span>;
  if (s === "stopped" || s === "shutoff") return <span className="badge badge-grey">Stopped</span>;
  if (s === "error")   return <span className="badge badge-red">Error</span>;
  return <span className="badge badge-amber">{status}</span>;
}

function ComplianceBadge({ pct }: { pct: number | null }) {
  if (pct === null) return <span className="badge badge-grey">—</span>;
  if (pct >= 90) return <span className="badge badge-green">{pct.toFixed(0)}%</span>;
  if (pct >= 70) return <span className="badge badge-amber">{pct.toFixed(0)}%</span>;
  return <span className="badge badge-red">{pct.toFixed(0)}%</span>;
}

function MetricBar({ label, value }: { label: string; value: number | null }) {
  if (value === null) {
    return (
      <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)", marginBottom: ".4rem" }}>
        {label}: —
      </div>
    );
  }
  const color =
    value >= 90 ? "var(--color-error)" :
    value >= 70 ? "var(--color-warning)" :
    "var(--brand-primary)";
  return (
    <div style={{ marginBottom: ".5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: ".75rem", marginBottom: ".2rem" }}>
        <span style={{ color: "var(--color-text-secondary)" }}>{label}</span>
        <span style={{ fontWeight: 600, color }}>{value.toFixed(0)}%</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${value}%`, background: color }} />
      </div>
    </div>
  );
}

// ── VM Detail side-panel ────────────────────────────────────────────────────

function VmDetailPanel({ vm, onClose }: { vm: Vm; onClose: () => void }) {
  const [metrics, setMetrics] = useState<VmMetrics | null>(null);

  useEffect(() => {
    let active = true;
    apiMetricsVm(vm.vm_id)
      .then((m) => { if (active) setMetrics(m); })
      .catch(() => {});
    return () => { active = false; };
  }, [vm.vm_id]);

  const fmt = (ts: string | null) => ts ? new Date(ts).toLocaleString() : "Never";

  return (
    <>
      <div className="side-panel-overlay" onClick={onClose} />
      <aside className="side-panel" aria-label="VM details">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
          <h2 style={{ fontSize: "1.125rem", fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {vm.vm_name}
          </h2>
          <button className="btn btn-secondary" onClick={onClose} aria-label="Close" style={{ padding: ".35rem .65rem", flexShrink: 0 }}>
            ✕
          </button>
        </div>

        <dl style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".75rem 1rem", marginBottom: "1.25rem" }}>
          {([
            ["Region",        vm.region_display_name],
            ["Status",        null],
            ["vCPUs",         String(vm.vcpus)],
            ["RAM",           `${(vm.ram_mb / 1024).toFixed(0)} GB`],
            ["Last Snapshot", fmt(vm.last_snapshot_ts)],
            ["Coverage",      vm.compliance_pct !== null ? `${vm.compliance_pct.toFixed(0)}%` : "—"],
          ] as Array<[string, string | null]>).map(([k, v]) => (
            <div key={k}>
              <dt style={{ fontSize: ".7rem", fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".04em" }}>{k}</dt>
              <dd style={{ fontSize: ".875rem", fontWeight: 500 }}>
                {k === "Status" ? <StatusBadge status={vm.status} /> : v}
              </dd>
            </div>
          ))}
        </dl>

        {vm.ip_addresses.length > 0 && (
          <div style={{ marginBottom: "1.25rem" }}>
            <div style={{ fontSize: ".7rem", fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: ".04em", marginBottom: ".35rem" }}>
              IP Addresses
            </div>
            {vm.ip_addresses.map((ip) => (
              <div key={ip} style={{ fontFamily: "monospace", fontSize: ".8rem" }}>{ip}</div>
            ))}
          </div>
        )}

        {metrics && (
          <div>
            <div className="section-title">Current Usage</div>
            <MetricBar label="CPU"     value={metrics.cpu_pct} />
            <MetricBar label="RAM"     value={metrics.ram_pct} />
            <MetricBar label="Storage" value={metrics.storage_pct} />
            {metrics.storage_used_gb !== null && metrics.storage_total_gb !== null && (
              <div style={{ fontSize: ".75rem", color: "var(--color-text-secondary)" }}>
                {metrics.storage_used_gb.toFixed(1)} GB / {metrics.storage_total_gb.toFixed(1)} GB
              </div>
            )}
            {metrics.last_updated && (
              <div style={{ fontSize: ".7rem", color: "var(--color-text-secondary)", marginTop: ".5rem" }}>
                Updated: {new Date(metrics.last_updated).toLocaleTimeString()}
              </div>
            )}
          </div>
        )}
      </aside>
    </>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface Props {
  regionFilter: string;
}

export function Infrastructure({ regionFilter }: Props) {
  const [tab, setTab] = useState<"vms" | "volumes">("vms");
  const [vms, setVms] = useState<Vm[]>([]);
  const [volumes, setVolumes] = useState<Volume[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedVm, setSelectedVm] = useState<Vm | null>(null);
  const [statusFilter, setStatusFilter] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([apiVms(), apiVolumes()])
      .then(([v, vols]) => {
        if (!active) return;
        setVms(v);
        setVolumes(vols);
      })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  // Client-side region filter
  const filteredVms = vms
    .filter((v) => !regionFilter || v.region_display_name === regionFilter)
    .filter((v) => !statusFilter || v.status.toLowerCase().includes(statusFilter.toLowerCase()));

  const filteredVolumes = volumes
    .filter((v) => !regionFilter || v.region_display_name === regionFilter);

  const fmtDate = (ts: string | null) => ts ? new Date(ts).toLocaleDateString() : "—";

  return (
    <div>
      <div className="tabs">
        <button className={`tab-btn${tab === "vms" ? " active" : ""}`} onClick={() => setTab("vms")}>
          VMs ({filteredVms.length})
        </button>
        <button className={`tab-btn${tab === "volumes" ? " active" : ""}`} onClick={() => setTab("volumes")}>
          Volumes ({filteredVolumes.length})
        </button>
      </div>

      {loading && <div className="empty-state"><span className="loading-spinner" /></div>}
      {error && <div className="error-banner">{error}</div>}

      {/* ── VMs tab ── */}
      {!loading && !error && tab === "vms" && (
        <>
          <div className="filter-bar">
            <select className="select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              <option value="running">Running</option>
              <option value="stopped">Stopped</option>
              <option value="error">Error</option>
            </select>
            <span style={{ fontSize: ".8rem", color: "var(--color-text-secondary)" }}>
              {filteredVms.length} VMs
            </span>
          </div>
          {filteredVms.length === 0 ? (
            <div className="empty-state">No VMs found.</div>
          ) : (
            <div className="card table-wrap" style={{ padding: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Region</th>
                    <th>Status</th>
                    <th>vCPUs</th>
                    <th>RAM</th>
                    <th>Last Snapshot</th>
                    <th>Coverage</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredVms.map((vm) => (
                    <tr key={vm.vm_id} onClick={() => setSelectedVm(vm)} style={{ cursor: "pointer" }}>
                      <td style={{ fontWeight: 500 }}>{vm.vm_name}</td>
                      <td>{vm.region_display_name}</td>
                      <td><StatusBadge status={vm.status} /></td>
                      <td>{vm.vcpus}</td>
                      <td>{(vm.ram_mb / 1024).toFixed(0)} GB</td>
                      <td>{fmtDate(vm.last_snapshot_ts)}</td>
                      <td><ComplianceBadge pct={vm.compliance_pct} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ── Volumes tab ── */}
      {!loading && !error && tab === "volumes" && (
        <>
          {filteredVolumes.length === 0 ? (
            <div className="empty-state">No volumes found.</div>
          ) : (
            <div className="card table-wrap" style={{ padding: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Attached To</th>
                    <th>Size</th>
                    <th>Region</th>
                    <th>Status</th>
                    <th>Last Snapshot</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredVolumes.map((vol) => (
                    <tr key={vol.volume_id}>
                      <td style={{ fontWeight: 500 }}>{vol.volume_name}</td>
                      <td>
                        {vol.attached_vm_name ?? (
                          <span style={{ color: "var(--color-text-secondary)" }}>—</span>
                        )}
                      </td>
                      <td>{vol.size_gb} GB</td>
                      <td>{vol.region_display_name}</td>
                      <td><StatusBadge status={vol.status} /></td>
                      <td>{fmtDate(vol.last_snapshot_ts)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {selectedVm && (
        <VmDetailPanel vm={selectedVm} onClose={() => setSelectedVm(null)} />
      )}
    </div>
  );
}
