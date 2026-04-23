import { useEffect, useState } from "react";
import {
  apiVms, apiVolumes, apiMetricsVm, apiNetworks, apiSecurityGroups,
  apiSecurityGroupDetail, apiAddSgRule, apiDeleteSgRule, apiResourceGraph,
  type Vm, type Volume, type VmMetrics, type Network, type SecurityGroup,
  type SgDetail, type SgRule, type ResourceGraph, type AddRuleRequest,
} from "../lib/api";

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
            ["Disk",          vm.disk_gb > 0 ? `${vm.disk_gb} GB` : "—"],
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
  const [tab, setTab] = useState<"vms" | "volumes" | "networks" | "security_groups" | "graph">("vms");
  const [vms, setVms] = useState<Vm[]>([]);
  const [volumes, setVolumes] = useState<Volume[]>([]);
  const [networks, setNetworks] = useState<Network[]>([]);
  const [sgs, setSgs] = useState<SecurityGroup[]>([]);
  const [sgDetail, setSgDetail] = useState<SgDetail | null>(null);
  const [sgLoading, setSgLoading] = useState(false);
  const [graph, setGraph] = useState<ResourceGraph | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedVm, setSelectedVm] = useState<Vm | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  // SG rule add form
  const [addRuleOpen, setAddRuleOpen] = useState(false);
  const [ruleForm, setRuleForm] = useState<AddRuleRequest>({ direction: "ingress" });
  const [ruleError, setRuleError] = useState<string | null>(null);
  const [ruleSaving, setRuleSaving] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([apiVms(), apiVolumes(), apiNetworks(), apiSecurityGroups()])
      .then(([v, vols, nets, sgList]) => {
        if (!active) return;
        setVms(v);
        setVolumes(vols);
        setNetworks(nets);
        setSgs(sgList);
      })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "Failed to load"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  // Load SG detail when a SG is selected
  const openSg = (sg: SecurityGroup) => {
    setSgDetail(null);
    setSgLoading(true);
    setAddRuleOpen(false);
    setRuleForm({ direction: "ingress" });
    setRuleError(null);
    apiSecurityGroupDetail(sg.id)
      .then(setSgDetail)
      .catch(() => setSgDetail({ id: sg.id, name: sg.name, description: sg.description, project_id: sg.project_id, rules: [] }))
      .finally(() => setSgLoading(false));
  };

  // Load graph on tab switch
  useEffect(() => {
    if (tab !== "graph") return;
    if (graph) return;
    setGraphLoading(true);
    apiResourceGraph()
      .then(setGraph)
      .catch(() => {})
      .finally(() => setGraphLoading(false));
  }, [tab]);

  const handleAddRule = async () => {
    if (!sgDetail) return;
    setRuleSaving(true);
    setRuleError(null);
    try {
      const newRule = await apiAddSgRule(sgDetail.id, ruleForm);
      setSgDetail((d) => d ? { ...d, rules: [...d.rules, newRule as unknown as SgRule] } : d);
      setAddRuleOpen(false);
      setRuleForm({ direction: "ingress" });
    } catch (e: unknown) {
      setRuleError(e instanceof Error ? e.message : "Failed to add rule");
    } finally {
      setRuleSaving(false);
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    if (!sgDetail) return;
    if (!confirm("Delete this rule?")) return;
    try {
      await apiDeleteSgRule(sgDetail.id, ruleId);
      setSgDetail((d) => d ? { ...d, rules: d.rules.filter((r) => r.id !== ruleId) } : d);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to delete rule");
    }
  };

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
        <button className={`tab-btn${tab === "networks" ? " active" : ""}`} onClick={() => setTab("networks")}>
          Networks ({networks.length})
        </button>
        <button className={`tab-btn${tab === "security_groups" ? " active" : ""}`} onClick={() => { setTab("security_groups"); setSgDetail(null); }}>
          Security Groups ({sgs.length})
        </button>
        <button className={`tab-btn${tab === "graph" ? " active" : ""}`} onClick={() => setTab("graph")}>
          🕸 Dependency Graph
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
              <option value="active">Running</option>
              <option value="shutoff">Stopped</option>
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
                    <th>Disk</th>
                    <th>IPs</th>
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
                      <td>{vm.disk_gb > 0 ? `${vm.disk_gb} GB` : "—"}</td>
                      <td style={{ fontFamily: "monospace", fontSize: ".8rem" }}>
                        {vm.ip_addresses.length > 0 ? vm.ip_addresses.join(", ") : "—"}
                      </td>
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

      {/* ── Networks tab ── */}
      {!loading && !error && tab === "networks" && (
        <>
          {networks.length === 0 ? (
            <div className="empty-state">No networks found.</div>
          ) : (
            <div className="card table-wrap" style={{ padding: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Subnets</th>
                    <th>CIDR(s)</th>
                    <th>Shared</th>
                    <th>External</th>
                  </tr>
                </thead>
                <tbody>
                  {networks.map((net) => (
                    <tr key={net.id}>
                      <td style={{ fontWeight: 500 }}>{net.name || <em style={{ color: "var(--color-text-secondary)" }}>unnamed</em>}</td>
                      <td>
                        <span className={`badge ${net.status?.toLowerCase() === "active" ? "badge-green" : "badge-amber"}`}>
                          {net.status || "—"}
                        </span>
                      </td>
                      <td>{net.subnets.length}</td>
                      <td style={{ fontFamily: "monospace", fontSize: ".8rem" }}>
                        {net.subnets.length === 0 ? "—" : net.subnets.map((s) => s.cidr).join(", ")}
                      </td>
                      <td>{net.is_shared ? "✓" : "—"}</td>
                      <td>{net.is_external ? "✓" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ── Security Groups tab ── */}
      {!loading && !error && tab === "security_groups" && (
        <div style={{ display: "grid", gridTemplateColumns: sgDetail ? "1fr 2fr" : "1fr", gap: "1rem", alignItems: "start" }}>
          {/* SG list */}
          <div className="card table-wrap" style={{ padding: 0 }}>
            <table>
              <thead>
                <tr><th>Name</th><th>Description</th></tr>
              </thead>
              <tbody>
                {sgs.length === 0 && (
                  <tr><td colSpan={2}><div className="empty-state" style={{ padding: "1rem" }}>No security groups.</div></td></tr>
                )}
                {sgs.map((sg) => (
                  <tr key={sg.id}
                    onClick={() => openSg(sg)}
                    style={{ cursor: "pointer", background: sgDetail?.id === sg.id ? "var(--color-surface-raised)" : undefined }}>
                    <td style={{ fontWeight: 500 }}>{sg.name}</td>
                    <td style={{ fontSize: ".8rem", color: "var(--color-text-secondary)" }}>{sg.description || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* SG detail panel */}
          {sgDetail && (
            <div className="card" style={{ minWidth: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
                <h3 style={{ margin: 0, fontSize: "1rem", fontWeight: 600 }}>{sgDetail.name}</h3>
                <div style={{ display: "flex", gap: ".5rem" }}>
                  <button className="btn btn-sm" onClick={() => setAddRuleOpen((o) => !o)}>
                    {addRuleOpen ? "Cancel" : "+ Add Rule"}
                  </button>
                  <button className="btn btn-sm btn-ghost" onClick={() => setSgDetail(null)}>✕</button>
                </div>
              </div>

              {sgLoading && <div style={{ textAlign: "center", padding: "1rem" }}><span className="loading-spinner" /></div>}

              {/* Add rule form */}
              {addRuleOpen && (
                <div style={{ background: "var(--color-surface-raised)", borderRadius: ".5rem", padding: "1rem", marginBottom: "1rem" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: ".5rem", marginBottom: ".5rem" }}>
                    <label style={{ fontSize: ".8rem", fontWeight: 600 }}>Direction
                      <select className="select" value={ruleForm.direction}
                        onChange={(e) => setRuleForm((f) => ({ ...f, direction: e.target.value as "ingress" | "egress" }))}>
                        <option value="ingress">Ingress (inbound)</option>
                        <option value="egress">Egress (outbound)</option>
                      </select>
                    </label>
                    <label style={{ fontSize: ".8rem", fontWeight: 600 }}>Protocol
                      <select className="select" value={ruleForm.protocol ?? ""}
                        onChange={(e) => setRuleForm((f) => ({ ...f, protocol: e.target.value || null }))}>
                        <option value="">Any</option>
                        <option value="tcp">TCP</option>
                        <option value="udp">UDP</option>
                        <option value="icmp">ICMP</option>
                      </select>
                    </label>
                    <label style={{ fontSize: ".8rem", fontWeight: 600 }}>Port Min
                      <input className="input" type="number" min={1} max={65535} placeholder="e.g. 80"
                        value={ruleForm.port_range_min ?? ""}
                        onChange={(e) => setRuleForm((f) => ({ ...f, port_range_min: e.target.value ? Number(e.target.value) : null }))} />
                    </label>
                    <label style={{ fontSize: ".8rem", fontWeight: 600 }}>Port Max
                      <input className="input" type="number" min={1} max={65535} placeholder="e.g. 80"
                        value={ruleForm.port_range_max ?? ""}
                        onChange={(e) => setRuleForm((f) => ({ ...f, port_range_max: e.target.value ? Number(e.target.value) : null }))} />
                    </label>
                    <label style={{ fontSize: ".8rem", fontWeight: 600, gridColumn: "1 / -1" }}>Remote IP / CIDR
                      <input className="input" type="text" placeholder="e.g. 0.0.0.0/0"
                        value={ruleForm.remote_ip_prefix ?? ""}
                        onChange={(e) => setRuleForm((f) => ({ ...f, remote_ip_prefix: e.target.value || null }))} />
                    </label>
                  </div>
                  {ruleError && <div className="error-banner" style={{ marginBottom: ".5rem" }}>{ruleError}</div>}
                  <button className="btn btn-primary btn-sm" onClick={handleAddRule} disabled={ruleSaving}>
                    {ruleSaving ? "Saving…" : "Add Rule"}
                  </button>
                </div>
              )}

              {/* Rules table */}
              {!sgLoading && (
                <div style={{ overflowX: "auto" }}>
                  {sgDetail.rules.length === 0 ? (
                    <div style={{ color: "var(--color-text-secondary)", fontSize: ".85rem", padding: ".5rem 0" }}>No rules defined.</div>
                  ) : (
                    <table>
                      <thead>
                        <tr>
                          <th>Dir</th><th>Proto</th><th>Ports</th><th>Remote IP</th><th>Description</th><th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {sgDetail.rules.map((rule) => (
                          <tr key={rule.id}>
                            <td><span className={`badge ${rule.direction === "ingress" ? "badge-green" : "badge-amber"}`}>{rule.direction}</span></td>
                            <td style={{ fontFamily: "monospace", fontSize: ".8rem" }}>{rule.protocol || "any"}</td>
                            <td style={{ fontFamily: "monospace", fontSize: ".8rem" }}>
                              {rule.port_range_min != null && rule.port_range_max != null
                                ? rule.port_range_min === rule.port_range_max
                                  ? String(rule.port_range_min)
                                  : `${rule.port_range_min}–${rule.port_range_max}`
                                : "all"}
                            </td>
                            <td style={{ fontFamily: "monospace", fontSize: ".8rem" }}>{rule.remote_ip_prefix || rule.remote_group_id || "0.0.0.0/0"}</td>
                            <td style={{ fontSize: ".8rem", color: "var(--color-text-secondary)" }}>{rule.description || "—"}</td>
                            <td>
                              <button className="btn btn-ghost btn-sm" style={{ color: "var(--color-error)", padding: "0 .5rem" }}
                                onClick={() => handleDeleteRule(rule.id)} title="Delete rule">✕</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Dependency Graph tab ── */}
      {!loading && !error && tab === "graph" && (
        <div className="card">
          {graphLoading && <div className="empty-state"><span className="loading-spinner" /></div>}
          {!graphLoading && !graph && <div className="empty-state">No graph data available.</div>}
          {!graphLoading && graph && <DependencyGraphView graph={graph} />}
        </div>
      )}
    </div>
  );
}

// ── Dependency Graph SVG component ─────────────────────────────────────────

type NodeType = "vm" | "net" | "subnet" | "sg" | "vol";
interface PosEntry { x: number; y: number; label: string; type: NodeType; sub?: string }

const GRAPH_COLORS: Record<NodeType, string> = {
  vm:     "#4f7cf7",
  net:    "#2db47d",
  subnet: "#1aaa72",
  sg:     "#f5a623",
  vol:    "#9b59b6",
};

const GRAPH_LABELS: Record<NodeType, string> = {
  vm:     "VM",
  net:    "Network",
  subnet: "Subnet",
  sg:     "Security Group",
  vol:    "Volume",
};

const GRAPH_ABBR: Record<NodeType, string> = {
  vm: "VM", net: "NET", subnet: "SUB", sg: "SG", vol: "VOL",
};

function DependencyGraphView({ graph }: { graph: ResourceGraph }) {
  const { nodes, edges } = graph;
  const allVms     = nodes.vms     ?? [];
  const allNets    = nodes.networks ?? [];
  const allSubnets = nodes.subnets  ?? [];
  const allSgs     = nodes.security_groups ?? [];
  const allVols    = nodes.volumes  ?? [];

  if (allVms.length === 0 && allNets.length === 0 && allSgs.length === 0) {
    return <div className="empty-state">No resources to display.</div>;
  }

  const R = 18;         // node circle radius
  const xStep = 160;    // column spacing
  const yStep = 76;
  const yStart = 60;

  // Layout columns (left→right): Subnets | Networks | VMs | SGs | Volumes
  const xSub = 90;
  const xNet = xSub + xStep;
  const xVm  = xNet + xStep + 20;
  const xSg  = xVm  + xStep + 20;
  const xVol = xSg  + xStep;

  const W = xVol + 90;

  // Position each node
  const posMap: Record<string, PosEntry> = {};
  allVms.forEach((v, i)     => { posMap[v.id] = { x: xVm,  y: yStart + i * yStep, label: v.name || v.id.slice(0,8), type: "vm" }; });
  allNets.forEach((n, i)    => { posMap[n.id] = { x: xNet, y: yStart + i * yStep, label: n.name || n.id.slice(0,8), type: "net" }; });
  allSubnets.forEach((s, i) => { posMap[s.id] = { x: xSub, y: yStart + i * yStep, label: s.name || s.cidr || s.id.slice(0,8), type: "subnet", sub: s.cidr }; });
  allSgs.forEach((s, i)     => { posMap[s.id] = { x: xSg,  y: yStart + i * yStep, label: s.name || s.id.slice(0,8), type: "sg" }; });
  allVols.forEach((v, i)    => { posMap[v.id] = { x: xVol, y: yStart + i * yStep, label: v.name || v.id.slice(0,8), type: "vol", sub: v.size_gb ? `${v.size_gb}GB` : "" }; });

  const maxRows = Math.max(allVms.length, allNets.length, allSubnets.length, allSgs.length, allVols.length, 1);
  const H = Math.max(380, (maxRows + 1) * yStep + 60);

  // Column headers
  const colHeaders = [
    { x: xSub, label: "SUBNETS",         show: allSubnets.length > 0 },
    { x: xNet, label: "NETWORKS",         show: allNets.length > 0 },
    { x: xVm,  label: "VMs",             show: true },
    { x: xSg,  label: "SECURITY GROUPS", show: allSgs.length > 0 },
    { x: xVol, label: "VOLUMES",         show: allVols.length > 0 },
  ];

  return (
    <div>
      {/* Legend */}
      <div style={{ display: "flex", gap: "1.25rem", marginBottom: ".75rem", flexWrap: "wrap" }}>
        {(["net", "subnet", "vm", "sg", "vol"] as NodeType[]).map((t) => (
          <div key={t} style={{ display: "flex", alignItems: "center", gap: ".35rem", fontSize: ".78rem" }}>
            <svg width={12} height={12}><circle cx={6} cy={6} r={5} fill={GRAPH_COLORS[t]} opacity={0.9} /></svg>
            <span style={{ color: "var(--color-text-secondary)" }}>{GRAPH_LABELS[t]}</span>
          </div>
        ))}
      </div>

      <div style={{ overflowX: "auto" }}>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ fontFamily: "inherit", maxWidth: "100%" }}>
          {/* Column headers */}
          {colHeaders.filter((c) => c.show).map(({ x, label }) => (
            <text key={label} x={x} y={22} textAnchor="middle" fontSize={9} fontWeight={700}
              fill="var(--color-text-secondary)" letterSpacing={0.6}>{label}</text>
          ))}

          {/* Edges: subnet → network */}
          {(edges.network_subnet ?? []).map((e, i) => {
            const sub = posMap[e.subnet_id]; const net = posMap[e.network_id];
            if (!sub || !net) return null;
            return <line key={`sn${i}`} x1={sub.x + R} y1={sub.y} x2={net.x - R} y2={net.y}
              stroke={GRAPH_COLORS.subnet} strokeWidth={1.2} strokeOpacity={0.35} strokeDasharray="3 3" />;
          })}

          {/* Edges: vm → network */}
          {(edges.vm_network ?? []).map((e, i) => {
            const vm = posMap[e.vm_id]; const net = posMap[e.network_id];
            if (!vm || !net) return null;
            return <line key={`vn${i}`} x1={net.x + R} y1={net.y} x2={vm.x - R} y2={vm.y}
              stroke={GRAPH_COLORS.net} strokeWidth={1.5} strokeOpacity={0.4} strokeDasharray="4 3" />;
          })}

          {/* Edges: vm → sg */}
          {(edges.vm_sg ?? []).map((e, i) => {
            const vm = posMap[e.vm_id]; const sg = posMap[e.sg_id];
            if (!vm || !sg) return null;
            return <line key={`vs${i}`} x1={vm.x + R} y1={vm.y} x2={sg.x - R} y2={sg.y}
              stroke={GRAPH_COLORS.sg} strokeWidth={1.5} strokeOpacity={0.4} strokeDasharray="4 3" />;
          })}

          {/* Edges: vm → volume */}
          {(edges.vm_volume ?? []).map((e, i) => {
            const vm = posMap[e.vm_id]; const vol = posMap[e.volume_id];
            if (!vm || !vol) return null;
            return <line key={`vv${i}`} x1={vm.x + R} y1={vm.y} x2={vol.x - R} y2={vol.y}
              stroke={GRAPH_COLORS.vol} strokeWidth={1.2} strokeOpacity={0.35} strokeDasharray="4 3" />;
          })}

          {/* Nodes */}
          {Object.values(posMap).map((n, idx) => (
            <g key={`${n.type}-${idx}`} transform={`translate(${n.x},${n.y})`}>
              <circle r={R} fill={GRAPH_COLORS[n.type]} opacity={0.88} />
              <text y={4} textAnchor="middle" fontSize={8} fill="white" fontWeight={700}>
                {GRAPH_ABBR[n.type]}
              </text>
              <text y={R + 14} textAnchor="middle" fontSize={9.5} fill="var(--color-text-primary)">
                {n.label.length > 13 ? n.label.slice(0, 12) + "…" : n.label}
              </text>
              {n.sub && (
                <text y={R + 25} textAnchor="middle" fontSize={8} fill="var(--color-text-secondary)">
                  {n.sub}
                </text>
              )}
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}
