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
import { API_BASE } from "../../config";

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
  migration_overlay?: { status: "confirmed" | "pending" | "missing" } | null;
}

interface ApiEdge {
  source: string;
  target: string;
  label: string;
}

interface GraphResponse {
  nodes: ApiNode[];
  edges: ApiEdge[];
  root: string;
  depth: number;
  node_count: number;
  edge_count: number;
  truncated: boolean;
}

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
  no_snapshot:   "No Snapshot",
  drift:         "Drift",
  error_state:   "Error",
  power_off:     "Powered Off",
  restore_source: "Restore Source",
};

const BADGE_COLORS: Record<string, string> = {
  no_snapshot:   "#f59e0b",
  drift:         "#ef4444",
  error_state:   "#ef4444",
  power_off:     "#94a3b8",
  restore_source: "#06b6d4",
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
  const color   = NODE_COLORS[data.ntype] ?? "#64748b";
  const icon    = NODE_ICONS[data.ntype]  ?? "📦";
  const isRoot  = data.isRoot as boolean;
  const overlay = data.migrationOverlay as { status: string } | null | undefined;
  const overlayColor = overlay ? OVERLAY_COLORS[overlay.status] : undefined;

  // Base box shadow: root highlight + optional overlay ring
  let boxShadow = isRoot ? `0 0 0 3px #facc1540` : "none";
  if (overlayColor) {
    boxShadow = `0 0 0 3px ${overlayColor}, 0 0 0 5px ${overlayColor}30`;
  }

  return (
    <div
      style={{
        background: "var(--rf-node-bg, #1e293b)",
        border: `2px solid ${isRoot ? "#facc15" : overlayColor ?? color}`,
        borderRadius: 10,
        padding: "6px 10px",
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT,
        boxShadow,
        fontFamily: "inherit",
        fontSize: 12,
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
              maxWidth: 130,
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
      </div>
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
// API fetch helper
// ---------------------------------------------------------------------------

function getToken(): string | null {
  return localStorage.getItem("auth_token");
}

async function fetchGraph(
  rootType: GraphRootType,
  rootId: string,
  depth: number,
  migrationProjectId?: number,
): Promise<GraphResponse> {
  const token = getToken();
  let url = `${API_BASE}/api/graph?root_type=${encodeURIComponent(rootType)}&root_id=${encodeURIComponent(rootId)}&depth=${depth}`;
  if (migrationProjectId != null) url += `&migration_project_id=${migrationProjectId}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `API error ${res.status}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Convert API response → ReactFlow nodes/edges
// ---------------------------------------------------------------------------

function toFlowGraph(
  data: GraphResponse,
  hiddenTypes: Set<string>,
): { nodes: Node[]; edges: Edge[] } {
  const visibleNodes = data.nodes.filter((n) => !hiddenTypes.has(n.type));
  const visibleIds   = new Set(visibleNodes.map((n) => n.id));

  const rfNodes: Node[] = visibleNodes.map((n) => ({
    id:       n.id,
    type:     "resource",
    position: { x: 0, y: 0 },
    data: {
      label:           n.label,
      ntype:           n.type,
      status:          n.status,
      badges:          n.badges,
      db_id:           n.db_id,
      isRoot:          n.id === data.root,
      migrationOverlay: n.migration_overlay ?? null,
    },
  }));

  const rfEdges: Edge[] = data.edges
    .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e) => ({
      id:           `${e.source}->${e.target}`,
      source:       e.source,
      target:       e.target,
      label:        e.label,
      animated:     false,
      style:        { stroke: "#475569", strokeWidth: 1.5 },
      labelStyle:   { fill: "#94a3b8", fontSize: 9 },
      labelBgStyle: { fill: "#1e293b", fillOpacity: 0.85 },
      markerEnd:    { type: MarkerType.ArrowClosed, color: "#475569" },
    }));

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
  // Current root — can be changed by clicking "Explore from here" on any node
  const [currentRoot, setCurrentRoot] = useState({ type: rootType, id: rootId, label: rootLabel });
  const [rootHistory, setRootHistory] = useState<Array<{ type: string; id: string; label: string }>>([]);

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
        const token = getToken();
        const res = await fetch(`${API_BASE}${graphUrl}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error((err as {detail?: string}).detail ?? `API error ${res.status}`);
        }
        data = await res.json();
      } else {
        data = await fetchGraph(currentRoot.type as GraphRootType, currentRoot.id, depth, migrationProjectId);
      }
      setGraphData(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [graphUrl, currentRoot.type, currentRoot.id, depth, migrationProjectId]);

  useEffect(() => { load(); }, [load]);

  // Re-layout when data or hidden types change
  useEffect(() => {
    if (!graphData) return;
    const { nodes: n, edges: e } = toFlowGraph(graphData, hiddenTypes);
    setNodes(n);
    setEdges(e);
  }, [graphData, hiddenTypes, setNodes, setEdges]);

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
            {!graphUrl && (selectedNode.type === "vm" || selectedNode.type === "tenant") && onNavigate && (
              <button
                className="graph-view-deps-btn"
                style={{ marginTop: 6, borderColor: "#f59e0b", color: "#f59e0b" }}
                onClick={() => {
                  onNavigate("migration_planner", selectedNode.db_id, selectedNode.type);
                }}
              >
                🚀 View in Migration Planner
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
