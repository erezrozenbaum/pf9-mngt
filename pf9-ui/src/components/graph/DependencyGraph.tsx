/**
 * DependencyGraph — Cloud Dependency Graph panel
 *
 * Renders a BFS node+edge graph from the /api/graph endpoint using
 * ReactFlow with dagre hierarchical layout.
 *
 * Props:
 *   rootType  — one of the API root_type values (vm, volume, network, etc.)
 *   rootId    — DB UUID of the starting resource
 *   rootLabel — display name shown in the panel header
 *   onClose   — called when the user closes the panel
 */

import React, { useCallback, useEffect, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
  MarkerType,
} from "reactflow";
import dagre from "@dagrejs/dagre";
import "reactflow/dist/style.css";
import { apiFetch } from '../../lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type GraphRootType =
  | "vm" | "volume" | "snapshot" | "network" | "subnet" | "port"
  | "floating_ip" | "security_group" | "tenant" | "host" | "image" | "domain";

interface ApiNode {
  id: string;
  db_id: string;
  type: string;
  label: string;
  status: string | null;
  badges: string[];
  health_score: number | null;
  capacity_pressure: "healthy" | "warning" | "critical" | null;
  snapshot_coverage: "protected" | "stale" | "missing" | null;
  extra?: Record<string, unknown>;
  migration_overlay?: { status: "confirmed" | "pending" | "missing" } | null;
}

interface ApiEdge {
  source: string;
  target: string;
  label: string;
}

interface OrphanSummary {
  volumes: number;
  fips: number;
  security_groups: number;
  snapshots: number;
}

interface TenantSummary {
  vms_critical: number;
  vms_degraded: number;
  vms_missing_snapshot: number;
  vms_with_drift: number;
}

interface BlastRadius {
  mode: string;
  summary: {
    vms_impacted: number;
    tenants_impacted: number;
    floating_ips_stranded: number;
    volumes_at_risk: number;
  };
  impact_node_ids: string[];
}

interface DeleteImpact {
  safe_to_delete: boolean;
  blockers: string[];
  cascade_node_ids: string[];
  stranded_node_ids: string[];
  summary: {
    cascade_count: number;
    stranded_vms: number;
    stranded_fips: number;
  };
}

interface GraphResponse {
  nodes: ApiNode[];
  edges: ApiEdge[];
  root: string;
  depth: number;
  node_count: number;
  edge_count: number;
  truncated: boolean;
  graph_health_score: number | null;
  orphan_summary: OrphanSummary | null;
  tenant_summary: TenantSummary | null;
  top_issues: Array<{ id: string; label: string; score: number; reasons: string[] }>;
  blast_radius?: BlastRadius;
  delete_impact?: DeleteImpact;
}

type GraphMode = "topology" | "blast_radius" | "delete_impact";

// ---------------------------------------------------------------------------
// Visual constants
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  vm:       "#0ea5e9",
  volume:   "#f59e0b",
  snapshot: "#10b981",
  network:  "#8b5cf6",
  subnet:   "#a78bfa",
  port:     "#c4b5fd",
  fip:      "#06b6d4",
  sg:       "#ef4444",
  tenant:   "#6366f1",
  host:     "#64748b",
  image:    "#ec4899",
  domain:   "#334155",
  disk:     "#d97706",
};

const NODE_ICONS: Record<string, string> = {
  vm:       "🖥️",
  volume:   "💾",
  snapshot: "📸",
  network:  "🌐",
  subnet:   "🔗",
  port:     "🔌",
  fip:      "🌊",
  sg:       "🔒",
  tenant:   "🏢",
  host:     "🏗️",
  image:    "📀",
  domain:   "🌍",
  disk:     "🖴️",
};

const BADGE_LABELS: Record<string, string> = {
  no_snapshot:        "No Snapshot",
  snapshot_missing:   "No Snapshot",
  snapshot_stale:     "Stale Snapshot",
  snapshot_protected: "Protected",
  drift:              "Drift",
  error_state:        "Error",
  power_off:          "Powered Off",
  restore_source:     "Restore Source",
  orphan:             "Orphan",
};

const BADGE_COLORS: Record<string, string> = {
  no_snapshot:        "#f59e0b",
  snapshot_missing:   "#ef4444",
  snapshot_stale:     "#f59e0b",
  snapshot_protected: "#10b981",
  drift:              "#ef4444",
  error_state:        "#dc2626",
  power_off:          "#94a3b8",
  restore_source:     "#06b6d4",
  orphan:             "#a855f7",
};

// Health score → ring color
function healthColor(score: number | null): string {
  if (score === null) return "";
  if (score >= 80) return "#10b981";
  if (score >= 60) return "#f59e0b";
  return "#ef4444";
}

// Capacity pressure → background tint
const CAPACITY_COLORS: Record<string, string> = {
  healthy:  "#10b98118",
  warning:  "#f59e0b18",
  critical: "#ef444418",
};

// Migration overlay status → ring color
const OVERLAY_COLORS: Record<string, string> = {
  confirmed: "#22c55e",
  pending:   "#f59e0b",
  missing:   "#ef4444",
};

const NODE_WIDTH  = 180;
const NODE_HEIGHT = 72;

// ---------------------------------------------------------------------------
// Dagre auto-layout
// ---------------------------------------------------------------------------

function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
  direction: "TB" | "LR" = "TB",
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, ranksep: 80, nodesep: 40 });

  nodes.forEach((n) => g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  const positioned = nodes.map((n) => {
    const { x, y } = g.node(n.id);
    return { ...n, position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 } };
  });

  return { nodes: positioned, edges };
}

// ---------------------------------------------------------------------------
// Custom node component
// ---------------------------------------------------------------------------

function ResourceNode({ data }: NodeProps) {
  const color    = NODE_COLORS[data.ntype] ?? "#64748b";
  const icon     = NODE_ICONS[data.ntype]  ?? "📦";
  const isRoot   = data.isRoot as boolean;
  const overlay  = data.migrationOverlay as { status: string } | null | undefined;
  const overlayColor  = overlay ? OVERLAY_COLORS[overlay.status] : undefined;
  const healthScore   = data.healthScore as number | null;
  const capPressure   = data.capacityPressure as string | null;
  const impactState   = data.impactState as "blast" | "cascade" | "stranded" | null;

  const hColor = healthColor(healthScore);

  // Border: root=gold, impact states, overlay, health score, then type color
  let borderColor = color;
  if (hColor && !isRoot && !overlayColor && !impactState) borderColor = hColor;
  if (overlayColor)     borderColor = overlayColor;
  if (impactState === "blast")    borderColor = "#ef4444";
  if (impactState === "cascade")  borderColor = "#ef4444";
  if (impactState === "stranded") borderColor = "#f97316";
  if (isRoot)           borderColor = "#facc15";

  // Background: capacity pressure tint or impact tint
  let bgColor = "var(--rf-node-bg, #1e293b)";
  if (capPressure && CAPACITY_COLORS[capPressure]) bgColor = CAPACITY_COLORS[capPressure];
  if (impactState === "blast")    bgColor = "#ef444415";
  if (impactState === "cascade")  bgColor = "#ef444420";
  if (impactState === "stranded") bgColor = "#f9731615";

  let boxShadow = isRoot ? `0 0 0 3px #facc1540` : "none";
  if (overlayColor)  boxShadow = `0 0 0 3px ${overlayColor}, 0 0 0 5px ${overlayColor}30`;
  if (impactState)   boxShadow = `0 0 0 2px ${borderColor}60`;

  return (
    <div
      style={{
        background: bgColor,
        border: `2px solid ${borderColor}`,
        borderRadius: 10,
        padding: "6px 10px",
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT,
        boxShadow,
        fontFamily: "inherit",
        fontSize: 12,
        opacity: data.dimmed ? 0.35 : 1,
        transition: "opacity 0.2s",
      }}
    >
      <Handle type="target" position={Position.Top}    style={{ background: color }} />
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
        <span style={{ fontSize: 18 }}>{icon}</span>
        <div style={{ flex: 1, overflow: "hidden" }}>
          <div
            style={{
              fontWeight: 600,
              color: "#f1f5f9",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              maxWidth: 118,
            }}
            title={data.label}
          >
            {data.label}
          </div>
          <div style={{ color: "#94a3b8", fontSize: 10, whiteSpace: "pre-wrap", lineHeight: 1.4 }}>
            {data.ntype}
            {data.status ? ` · ${data.status}` : ""}
          </div>
        </div>
        {healthScore !== null && (
          <div style={{
            width: 22, height: 22, borderRadius: "50%",
            background: `${healthColor(healthScore)}22`,
            border: `2px solid ${healthColor(healthScore)}`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 8, fontWeight: 700, color: healthColor(healthScore),
            flexShrink: 0,
          }}>
            {healthScore}
          </div>
        )}
      </div>
      {data.ip && (
        <div style={{ color: "#67e8f9", fontSize: 9, marginTop: 2, fontFamily: "monospace" }}>
          📍 {data.ip as string}
        </div>
      )}
      {data.badges && data.badges.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 3, marginTop: 4 }}>
          {(data.badges as string[]).map((b) => (
            <span
              key={b}
              style={{
                background: BADGE_COLORS[b] ?? "#64748b",
                color: "#fff",
                borderRadius: 4,
                padding: "1px 5px",
                fontSize: 9,
                fontWeight: 600,
                textTransform: "uppercase",
              }}
            >
              {BADGE_LABELS[b] ?? b}
            </span>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </div>
  );
}

const nodeTypes = { resource: ResourceNode };

// ---------------------------------------------------------------------------
// Tenant health panel
// ---------------------------------------------------------------------------

function TenantHealthPanel({ summary, graphHealthScore, topIssues, orphanSummary }: {
  summary: TenantSummary;
  graphHealthScore: number | null;
  topIssues: GraphResponse["top_issues"];
  orphanSummary: OrphanSummary | null;
}) {
  const hs = graphHealthScore;
  const hc = healthColor(hs);
  return (
    <div style={{
      background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8,
      padding: "8px 12px", margin: "6px 8px 0", fontSize: 11,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <span style={{ color: "#94a3b8", fontWeight: 600 }}>Environment Health</span>
        {hs !== null && (
          <span style={{
            background: `${hc}22`, border: `1px solid ${hc}`, borderRadius: 12,
            padding: "1px 8px", fontWeight: 700, color: hc, fontSize: 12,
          }}>{hs} / 100</span>
        )}
      </div>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", color: "#cbd5e1" }}>
        {summary.vms_critical > 0 && (
          <span style={{ color: "#ef4444" }}>🔴 {summary.vms_critical} critical VM{summary.vms_critical > 1 ? "s" : ""}</span>
        )}
        {summary.vms_degraded > 0 && (
          <span style={{ color: "#f59e0b" }}>🟡 {summary.vms_degraded} degraded VM{summary.vms_degraded > 1 ? "s" : ""}</span>
        )}
        {summary.vms_missing_snapshot > 0 && (
          <span>📸 {summary.vms_missing_snapshot} without snapshot</span>
        )}
        {summary.vms_with_drift > 0 && (
          <span>⚠️ {summary.vms_with_drift} drift event{summary.vms_with_drift > 1 ? "s" : ""}</span>
        )}
        {orphanSummary && Object.values(orphanSummary).some(v => v > 0) && (
          <span style={{ color: "#a855f7" }}>🟣 {Object.values(orphanSummary).reduce((a,b)=>a+b,0)} orphan resource{Object.values(orphanSummary).reduce((a,b)=>a+b,0) > 1 ? "s" : ""}</span>
        )}
      </div>
      {topIssues.length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ cursor: "pointer", color: "#94a3b8", fontSize: 10 }}>Top issues ({topIssues.length})</summary>
          <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 2 }}>
            {topIssues.slice(0, 5).map(i => (
              <div key={i.id} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{ color: healthColor(i.score), fontWeight: 600, fontSize: 10 }}>{i.score}</span>
                <span style={{ color: "#e2e8f0" }}>{i.label}</span>
                <span style={{ color: "#64748b", fontSize: 9 }}>{i.reasons.join(", ")}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// API fetch helper
// ---------------------------------------------------------------------------

async function fetchGraph(
  rootType: GraphRootType,
  rootId: string,
  depth: number,
  mode: GraphMode,
  migrationProjectId?: number,
): Promise<GraphResponse> {
  let url = `/api/graph?root_type=${encodeURIComponent(rootType)}&root_id=${encodeURIComponent(rootId)}&depth=${depth}&mode=${mode}`;
  if (migrationProjectId != null) url += `&migration_project_id=${migrationProjectId}`;
  return apiFetch<GraphResponse>(url);
}

// ---------------------------------------------------------------------------
// Convert API response → ReactFlow nodes/edges
// ---------------------------------------------------------------------------

function toFlowGraph(
  data: GraphResponse,
  hiddenTypes: Set<string>,
  mode: GraphMode,
): { nodes: Node[]; edges: Edge[] } {
  const visibleNodes = data.nodes.filter((n) => !hiddenTypes.has(n.type));
  const visibleIds   = new Set(visibleNodes.map((n) => n.id));

  // Pre-compute impact sets for visual overlay
  const blastImpactIds = new Set<string>(data.blast_radius?.impact_node_ids ?? []);
  const cascadeIds     = new Set<string>(data.delete_impact?.cascade_node_ids ?? []);
  const strandedIds    = new Set<string>(data.delete_impact?.stranded_node_ids ?? []);

  const rfNodes: Node[] = visibleNodes.map((n) => {
    let impactState: "blast" | "cascade" | "stranded" | null = null;
    let dimmed = false;
    if (mode === "blast_radius") {
      if (blastImpactIds.has(n.id)) impactState = "blast";
      else if (n.id !== data.root) dimmed = true;
    } else if (mode === "delete_impact") {
      if (cascadeIds.has(n.id))  impactState = "cascade";
      else if (strandedIds.has(n.id)) impactState = "stranded";
    }
    return {
      id:       n.id,
      type:     "resource",
      position: { x: 0, y: 0 },
      data: {
        label:            n.label,
        ntype:            n.type,
        status:           n.status,
        badges:           n.badges,
        db_id:            n.db_id,
        isRoot:           n.id === data.root,
        migrationOverlay: n.migration_overlay ?? null,
        healthScore:      n.health_score ?? null,
        capacityPressure: n.capacity_pressure ?? null,
        ip:               (n.extra as Record<string, unknown>)?.ip_address as string ?? null,
        impactState,
        dimmed,
      },
    };
  });

  const rfEdges: Edge[] = data.edges
    .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e) => {
      const inImpact = mode === "blast_radius"
        ? (blastImpactIds.has(e.source) && blastImpactIds.has(e.target))
        : mode === "delete_impact"
        ? (cascadeIds.has(e.target) || strandedIds.has(e.target))
        : false;
      return {
        id:           `${e.source}->${e.target}`,
        source:       e.source,
        target:       e.target,
        label:        e.label,
        animated:     inImpact,
        style:        { stroke: inImpact ? "#ef444480" : "#475569", strokeWidth: inImpact ? 2 : 1.5 },
        labelStyle:   { fill: "#94a3b8", fontSize: 9 },
        labelBgStyle: { fill: "#1e293b", fillOpacity: 0.85 },
        markerEnd:    { type: MarkerType.ArrowClosed, color: inImpact ? "#ef4444" : "#475569" },
      };
    });

  return applyDagreLayout(rfNodes, rfEdges);
}

// ---------------------------------------------------------------------------
// Available node type list (for the filter checkboxes)
// ---------------------------------------------------------------------------

const ALL_NODE_TYPES = [
  "vm", "disk", "volume", "snapshot", "network", "subnet",
  "port", "fip", "sg", "tenant", "host", "image", "domain",
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  rootType:  GraphRootType;
  rootId:    string;
  rootLabel: string;
  onClose:   () => void;
  /** Navigate to a tab and pre-select a resource. Called before closing the drawer. */
  onNavigate?: (tab: string, resourceId: string, resourceType: string) => void;
  /** Trigger "create snapshot" flow for a volume (opens snapshot dialog in Volumes tab). */
  onCreateSnapshot?: (volumeId: string, volumeName: string) => void;
  /** When set, overlays migration status (confirmed/pending/missing) on vm and tenant nodes. */
  migrationProjectId?: number;
  /**
   * When set, use this URL directly for graph fetching instead of building from
   * rootType/rootId. Enables VMware-side migration graphs from migration_routes.
   */
  graphUrl?: string;
}

// Map graph node type → App.tsx ActiveTab id
const NODE_TYPE_TO_TAB: Record<string, string> = {
  vm:       "servers",
  volume:   "volumes",
  snapshot: "snapshots",
  network:  "networks",
  subnet:   "subnets",
  port:     "ports",
  fip:      "floatingips",
  sg:       "security_groups",
  tenant:   "projects",
  host:     "hypervisors",
  image:    "images",
  domain:   "domains",
};

// Map short graph node type → API root_type value (only entries that differ)
const NODE_TYPE_TO_API_ROOT: Record<string, GraphRootType> = {
  sg:  "security_group",
  fip: "floating_ip",
};

export default function DependencyGraph({ rootType, rootId, rootLabel, onClose, onNavigate, onCreateSnapshot, migrationProjectId, graphUrl }: Props) {
  const [depth,       setDepth]       = useState(2);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set(["port", "subnet"]));
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState<string | null>(null);
  const [graphData,   setGraphData]   = useState<GraphResponse | null>(null);
  const [selectedNode, setSelectedNode] = useState<ApiNode | null>(null);
  const [isMobile,    setIsMobile]    = useState(false);
  const [mode,        setMode]        = useState<GraphMode>("topology");
  // Current root — can be changed by clicking "Explore from here" on any node
  const [currentRoot, setCurrentRoot] = useState({ type: rootType, id: rootId, label: rootLabel });
  const [rootHistory, setRootHistory] = useState<Array<{ type: string; id: string; label: string }>>([]);
  // T3.3 — Delete-gate ticket state
  const [deleteTicketLoading, setDeleteTicketLoading] = useState(false);
  const [deleteTicketResult,  setDeleteTicketResult]  = useState<{ ticket_ref: string; created: boolean } | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // Mobile detection
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  // Fetch graph data
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSelectedNode(null);
    try {
      let data: GraphResponse;
      if (graphUrl) {
        // VMware migration graph mode — fetch the pre-built URL directly
        data = await apiFetch<GraphResponse>(graphUrl);
      } else {
        data = await fetchGraph(currentRoot.type as GraphRootType, currentRoot.id, depth, mode, migrationProjectId);
      }
      setGraphData(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [graphUrl, currentRoot.type, currentRoot.id, depth, mode, migrationProjectId]);

  useEffect(() => { load(); }, [load]);

  // Re-layout when data or hidden types change
  useEffect(() => {
    if (!graphData) return;
    const { nodes: n, edges: e } = toFlowGraph(graphData, hiddenTypes, mode);
    setNodes(n);
    setEdges(e);
  }, [graphData, hiddenTypes, mode, setNodes, setEdges]);

  const toggleType = (t: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  };

  // Sync selectedNode from node click
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    if (!graphData) return;
    const found = graphData.nodes.find((n) => n.id === node.id) ?? null;
    setSelectedNode(found);
  }, [graphData]);

  // ---- Fallback mobile view (simple table) --------------------------------
  if (isMobile) {
    return (
      <div className="graph-drawer graph-drawer-mobile">
        <div className="graph-drawer-header">
          <span>🕸️ Dependencies: {rootLabel}</span>
          <button className="graph-close-btn" onClick={onClose}>✕</button>
        </div>
        {loading && <div className="graph-loading">Loading…</div>}
        {error   && <div className="graph-error">{error}</div>}
        {graphData && (
          <table className="pf9-table" style={{ margin: 0 }}>
            <thead><tr><th>Type</th><th>Name</th><th>Status</th><th>Badges</th></tr></thead>
            <tbody>
              {graphData.nodes.map((n) => (
                <tr key={n.id}>
                  <td>{NODE_ICONS[n.type] ?? "📦"} {n.type}</td>
                  <td>{n.label}</td>
                  <td>{n.status ?? "—"}</td>
                  <td>{n.badges.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  }

  // ---- Full desktop graph --------------------------------------------------
  // T3.3 — Request-delete ticket helper
  async function requestDeleteTicket() {
    setDeleteTicketLoading(true);
    setDeleteTicketResult(null);
    try {
      const data = await apiFetch<{ ticket_ref: string; created: boolean }>(`/api/graph/request-delete`, {
        method: "POST",
        body: JSON.stringify({ root_type: currentRoot.type, root_id: currentRoot.id }),
      });
      setDeleteTicketResult({ ticket_ref: data.ticket_ref, created: data.created });
    } catch (e: any) {
      alert("Could not create delete-request ticket: " + e.message);
    } finally {
      setDeleteTicketLoading(false);
    }
  }

  return (
    <div className="graph-drawer" style={{ position: "relative" }}>
      {/* Header */}
      <div className="graph-drawer-header">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 18 }}>🕸️</span>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {rootHistory.length > 0 && (
                <button
                  className="graph-action-btn"
                  style={{ fontSize: 11, padding: "1px 7px" }}
                  title="Back to previous root"
                  onClick={() => {
                    const prev = rootHistory[rootHistory.length - 1];
                    setRootHistory((h) => h.slice(0, -1));
                    setCurrentRoot(prev as typeof currentRoot);
                  }}
                >
                  ← Back
                </button>
              )}
              <span style={{ fontWeight: 600, color: "var(--color-text-primary, #f1f5f9)" }}>
                Dependencies: {currentRoot.label}
              </span>
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-secondary, #94a3b8)" }}>
              {graphUrl ? "VMware" : currentRoot.type} · {graphData ? `${graphData.node_count} nodes, ${graphData.edge_count} edges` : "loading…"}
              {graphData?.truncated && " ⚠️ truncated"}
            </div>
          </div>
        </div>
        <button className="graph-close-btn" onClick={onClose}>✕</button>
      </div>

      {/* Controls bar */}
      <div className="graph-controls-bar">
        {/* Mode toggle — hidden for VMware migration graphs */}
        {!graphUrl && (
          <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
            {(["topology", "blast_radius", "delete_impact"] as GraphMode[]).map((m) => {
              const labels: Record<GraphMode, string> = {
                topology:      "🕸 Topology",
                blast_radius:  "💥 Blast Radius",
                delete_impact: "🗑 Delete Impact",
              };
              return (
                <button
                  key={m}
                  className={`graph-pill ${mode === m ? "graph-pill-active" : ""}`}
                  style={mode === m && m !== "topology" ? { background: "#7f1d1d", borderColor: "#ef4444", color: "#fca5a5" } : {}}
                  onClick={() => setMode(m)}
                  title={m === "blast_radius" ? "Show what fails if this resource crashes" : m === "delete_impact" ? "Show what gets deleted or stranded if you delete this resource" : "Show topology"}
                >
                  {labels[m]}
                </button>
              );
            })}
          </div>
        )}

        {/* Depth pills — hidden for VMware migration graphs (depth not applicable) */}
        {!graphUrl && (
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ fontSize: 11, color: "var(--color-text-secondary, #94a3b8)" }}>Depth</span>
            {[1, 2, 3].map((d) => (
              <button
                key={d}
                className={`graph-pill ${depth === d ? "graph-pill-active" : ""}`}
                onClick={() => setDepth(d)}
              >
                {d}
              </button>
            ))}
          </div>
        )}

        {/* Refresh */}
        <button className="graph-action-btn" onClick={load} disabled={loading} title="Refresh">
          {loading ? "⏳" : "🔄"}
        </button>

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Migration overlay legend */}
        {(migrationProjectId != null || graphUrl != null) && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginRight: 8 }}>
            <span style={{ fontSize: 10, color: "#94a3b8" }}>Migration:</span>
            {(["confirmed", "pending", "missing"] as const).map((s) => {
              const label = graphUrl
                ? { confirmed: "complete", pending: "in progress", missing: "failed" }[s]
                : s;
              return (
                <span key={s} style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 10 }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: OVERLAY_COLORS[s], display: "inline-block" }} />
                  <span style={{ color: "#cbd5e1" }}>{label}</span>
                </span>
              );
            })}
          </div>
        )}

        {/* Type filter checkboxes */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {ALL_NODE_TYPES.map((t) => (
            <label key={t} className="graph-type-chip" title={`Toggle ${t} nodes`}>
              <input
                type="checkbox"
                checked={!hiddenTypes.has(t)}
                onChange={() => toggleType(t)}
              />
              {NODE_ICONS[t]} {t}
            </label>
          ))}
        </div>
      </div>

      {/* Tenant health panel — shown when tenant summary available, topology mode only */}
      {!graphUrl && mode === "topology" && graphData?.tenant_summary && (
        <TenantHealthPanel
          summary={graphData.tenant_summary}
          graphHealthScore={graphData.graph_health_score ?? null}
          topIssues={graphData.top_issues ?? []}
          orphanSummary={graphData.orphan_summary ?? null}
        />
      )}

      {/* Blast radius summary panel */}
      {mode === "blast_radius" && graphData?.blast_radius && (
        <div style={{
          background: "#450a0a", border: "1px solid #7f1d1d", borderRadius: 8,
          padding: "8px 12px", margin: "6px 8px 0", fontSize: 11, color: "#fca5a5",
        }}>
          <span style={{ fontWeight: 700, marginRight: 10 }}>💥 Failure Impact</span>
          <span>VMs: <b>{graphData.blast_radius.summary.vms_impacted}</b></span>
          <span style={{ margin: "0 8px" }}>Tenants: <b>{graphData.blast_radius.summary.tenants_impacted}</b></span>
          <span>Floating IPs stranded: <b>{graphData.blast_radius.summary.floating_ips_stranded}</b></span>
          <span style={{ marginLeft: 8 }}>Volumes at risk: <b>{graphData.blast_radius.summary.volumes_at_risk}</b></span>
        </div>
      )}

      {/* Delete impact summary panel */}
      {mode === "delete_impact" && graphData?.delete_impact && (
        <div style={{
          background: graphData.delete_impact.safe_to_delete ? "#052e16" : "#450a0a",
          border: `1px solid ${graphData.delete_impact.safe_to_delete ? "#166534" : "#7f1d1d"}`,
          borderRadius: 8, padding: "8px 12px", margin: "6px 8px 0", fontSize: 11,
          color: graphData.delete_impact.safe_to_delete ? "#86efac" : "#fca5a5",
        }}>
          {graphData.delete_impact.safe_to_delete
            ? <span>✅ Safe to delete — no cascade or stranded resources detected</span>
            : <>
                <span style={{ fontWeight: 700, marginRight: 10 }}>🗑 Delete Impact</span>
                {graphData.delete_impact.blockers.map((b, i) => (
                  <div key={i} style={{ color: "#fbbf24", marginBottom: 2 }}>❌ {b}</div>
                ))}
                {graphData.delete_impact.summary.cascade_count > 0 && (
                  <span style={{ marginRight: 8 }}>Cascade-deleted: <b>{graphData.delete_impact.summary.cascade_count}</b></span>
                )}
                {graphData.delete_impact.summary.stranded_vms > 0 && (
                  <span style={{ marginRight: 8, color: "#fb923c" }}>Stranded VMs: <b>{graphData.delete_impact.summary.stranded_vms}</b></span>
                )}
                {graphData.delete_impact.summary.stranded_fips > 0 && (
                  <span style={{ color: "#fb923c" }}>Stranded FIPs: <b>{graphData.delete_impact.summary.stranded_fips}</b></span>
                )}
                {/* T3.3 — Gate: request change-request ticket before deleting */}
                <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8 }}>
                  {!deleteTicketResult ? (
                    <button
                      style={{
                        background: "#7f1d1d", border: "1px solid #ef4444", borderRadius: 4,
                        color: "#fca5a5", padding: "3px 10px", fontSize: 11, cursor: "pointer",
                        opacity: deleteTicketLoading ? 0.6 : 1,
                      }}
                      disabled={deleteTicketLoading}
                      onClick={requestDeleteTicket}
                      title="Create a change-request ticket to gate this deletion through Engineering approval"
                    >
                      {deleteTicketLoading ? "Creating…" : "🎫 Request Delete Approval"}
                    </button>
                  ) : (
                    <span style={{ color: "#86efac", fontWeight: 600 }}>
                      {deleteTicketResult.created
                        ? `✓ Ticket ${deleteTicketResult.ticket_ref} created — awaiting Engineering approval`
                        : `ℹ️ Existing ticket ${deleteTicketResult.ticket_ref} covers this resource`}
                    </span>
                  )}
                </div>
              </>
          }
        </div>
      )}

      {/* Main content */}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* Graph canvas */}
        <div style={{ flex: 1, position: "relative" }}>
          {loading && (
            <div className="graph-overlay-loading">Loading graph…</div>
          )}
          {error && (
            <div className="graph-overlay-error">Error: {error}</div>
          )}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.2}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#334155" gap={24} />
            <Controls />
            <MiniMap
              nodeColor={(n) => NODE_COLORS[n.data?.ntype as string] ?? "#64748b"}
              nodeStrokeWidth={2}
              style={{ background: "#0f172a" }}
            />
          </ReactFlow>
        </div>

        {/* Node detail sidebar */}
        {selectedNode && (
          <div className="graph-node-sidebar" style={{ background: "#1e293b", color: "#f1f5f9" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <span style={{ fontWeight: 600, fontSize: 13, color: "#f1f5f9" }}>{NODE_ICONS[selectedNode.type]} {selectedNode.label}</span>
              <button
                style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 16 }}
                onClick={() => setSelectedNode(null)}
              >✕</button>
            </div>
            <table style={{ fontSize: 12, width: "100%", borderCollapse: "collapse" }}>
              <tbody>
                <SidebarRow label="Type"   value={selectedNode.type} />
                <SidebarRow label="Status" value={selectedNode.status ?? "—"} />
                {!!(selectedNode.extra?.ip_address) && (
                  <SidebarRow
                    label="IP Address"
                    value={
                      <span style={{ fontFamily: "monospace", color: "#67e8f9", fontSize: 11 }}>
                        {selectedNode.extra.ip_address as string}
                      </span>
                    }
                  />
                )}
                {selectedNode.health_score !== null && selectedNode.health_score !== undefined && (
                  <SidebarRow
                    label="Health"
                    value={
                      <span style={{
                        background: healthColor(selectedNode.health_score) + "22",
                        color: healthColor(selectedNode.health_score),
                        borderRadius: 4, padding: "1px 6px", fontWeight: 700, fontSize: 11,
                      }}>
                        {selectedNode.health_score} / 100
                      </span>
                    }
                  />
                )}
                {selectedNode.snapshot_coverage && (
                  <SidebarRow
                    label="Snapshots"
                    value={
                      <span style={{
                        color: selectedNode.snapshot_coverage === "protected" ? "#10b981"
                          : selectedNode.snapshot_coverage === "stale" ? "#f59e0b" : "#ef4444",
                        fontWeight: 600, fontSize: 11, textTransform: "capitalize",
                      }}>
                        {selectedNode.snapshot_coverage === "protected" ? "✅ Protected"
                          : selectedNode.snapshot_coverage === "stale" ? "⚠️ Stale"
                          : "❌ None"}
                      </span>
                    }
                  />
                )}
                {selectedNode.capacity_pressure && (
                  <SidebarRow
                    label="Capacity"
                    value={
                      <span style={{
                        color: selectedNode.capacity_pressure === "healthy" ? "#10b981"
                          : selectedNode.capacity_pressure === "warning" ? "#f59e0b" : "#ef4444",
                        fontWeight: 600, fontSize: 11, textTransform: "capitalize",
                      }}>
                        {selectedNode.capacity_pressure}
                      </span>
                    }
                  />
                )}
                {selectedNode.migration_overlay && (
                  <SidebarRow
                    label="Migration"
                    value={
                      <span style={{
                        background: OVERLAY_COLORS[selectedNode.migration_overlay.status] + "33",
                        color: OVERLAY_COLORS[selectedNode.migration_overlay.status],
                        borderRadius: 4, padding: "1px 6px", fontWeight: 600, fontSize: 10, textTransform: "capitalize",
                      }}>
                        {selectedNode.migration_overlay.status}
                      </span>
                    }
                  />
                )}
                <SidebarRow
                  label="ID"
                  value={
                    <span style={{ fontFamily: "monospace", fontSize: 10, wordBreak: "break-all", color: "#cbd5e1" }}>
                      {selectedNode.db_id}
                    </span>
                  }
                />
                {Array.isArray(selectedNode.badges) && selectedNode.badges.length > 0 && (
                  <SidebarRow
                    label="Badges"
                    value={
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                        {selectedNode.badges.map((b) => (
                          <span key={b} style={{
                            background: BADGE_COLORS[b] ?? "#64748b",
                            color: "#fff",
                            borderRadius: 4,
                            padding: "2px 6px",
                            fontSize: 10,
                            fontWeight: 600,
                          }}>
                            {BADGE_LABELS[b] ?? b}
                          </span>
                        ))}
                      </div>
                    }
                  />
                )}
              </tbody>
            </table>
            {/* Explore from here — only available for PCD graphs, not VMware migration graphs */}
            {!graphUrl && selectedNode.id !== graphData?.root && (
              <button
                className="graph-view-deps-btn"
                style={{ marginTop: 12, background: "#1d4ed8", borderColor: "#3b82f6", color: "#fff" }}
                onClick={() => {
                  setRootHistory((h) => [...h, currentRoot]);
                  const apiRootType = NODE_TYPE_TO_API_ROOT[selectedNode.type] ?? (selectedNode.type as GraphRootType);
                  setCurrentRoot({ type: apiRootType, id: selectedNode.db_id, label: selectedNode.label });
                  setSelectedNode(null);
                }}
              >
                🔍 Explore from here
              </button>
            )}
            {/* Suggested actions based on health score */}
            {!graphUrl && selectedNode.health_score !== null && selectedNode.health_score !== undefined && selectedNode.health_score < 60 && (() => {
              const actions: React.ReactNode[] = [];
              const b = selectedNode.badges;
              if ((b.includes("snapshot_missing") || b.includes("snapshot_stale")) && selectedNode.type === "volume" && onCreateSnapshot) {
                actions.push(
                  <button key="snap" className="graph-view-deps-btn" style={{ marginTop: 6, borderColor: "#10b981", color: "#10b981" }}
                    onClick={() => onCreateSnapshot(selectedNode.db_id, selectedNode.label)}>
                    📸 Create Snapshot
                  </button>
                );
              }
              if (b.includes("drift") && onNavigate) {
                actions.push(
                  <button key="drift" className="graph-view-deps-btn" style={{ marginTop: 6, borderColor: "#f59e0b", color: "#f59e0b" }}
                    onClick={() => onNavigate("drift", selectedNode.db_id, selectedNode.type)}>
                    🔍 View Drift Events
                  </button>
                );
              }
              if (b.includes("error_state") && onNavigate) {
                actions.push(
                  <button key="logs" className="graph-view-deps-btn" style={{ marginTop: 6, borderColor: "#ef4444", color: "#ef4444" }}
                    onClick={() => onNavigate("logs", selectedNode.db_id, selectedNode.type)}>
                    📋 View Logs
                  </button>
                );
              }
              return actions.length > 0 ? <>{actions}</> : null;
            })()}
            {/* —— Open in tab / Create Snapshot / View in Migration Planner —— */}
            {/* Hidden for VMware migration graphs — PCD resources don't exist yet */}
            {!graphUrl && NODE_TYPE_TO_TAB[selectedNode.type] && onNavigate && (
              <button
                className="graph-view-deps-btn"
                style={{ marginTop: 6 }}
                onClick={() => {
                  onNavigate(NODE_TYPE_TO_TAB[selectedNode.type], selectedNode.db_id, selectedNode.type);
                }}
              >
                🔗 Open in {NODE_TYPE_TO_TAB[selectedNode.type]} tab
              </button>
            )}
            {!graphUrl && selectedNode.type === "volume" && onCreateSnapshot && (
              <button
                className="graph-view-deps-btn"
                style={{ marginTop: 6, borderColor: "#10b981", color: "#10b981" }}
                onClick={() => {
                  onCreateSnapshot(selectedNode.db_id, selectedNode.label);
                }}
              >
                📸 Create Snapshot
              </button>
            )}

          </div>
        )}
      </div>
    </div>
  );
}

function SidebarRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <tr>
      <td style={{ color: "#94a3b8", paddingBottom: 6, paddingRight: 8, whiteSpace: "nowrap", verticalAlign: "top" }}>{label}</td>
      <td style={{ color: "#e2e8f0", paddingBottom: 6 }}>{value}</td>
    </tr>
  );
}
