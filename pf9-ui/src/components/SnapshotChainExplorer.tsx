/**
 * SnapshotChainExplorer — visualises snapshot lineage trees for volumes.
 *
 * Features:
 *  - Volume ID search → fetch full chain summary
 *  - Expandable tree view of base → incremental relationships
 *  - Per-volume chain policy editor (max depth + auto-rebase toggle)
 *  - Badge showing chain depth and status per node
 */
import React, { useState } from "react";
import { apiFetch } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChainNode {
  snapshot_id: string;
  snapshot_name?: string | null;
  volume_id: string;
  volume_name?: string | null;
  project_id: string;
  chain_depth: number;
  parent_snapshot_id?: string | null;
  chain_root_snapshot_id?: string | null;
  status: string;
  size_gb?: number | null;
  created_at?: string | null;
  deleted_at?: string | null;
  children?: ChainNode[];
}

interface ChainSummary {
  volume_id: string;
  volume_name?: string | null;
  total_snapshots: number;
  base_snapshots: number;
  max_chain_depth: number;
  total_size_gb?: number | null;
  chains: ChainNode[];
}

interface ChainPolicy {
  project_id: string;
  volume_id: string;
  max_chain_depth: number;
  auto_rebase: boolean;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const NODE_STATUS_COLORS: Record<string, string> = {
  available: "#22c55e",
  pending: "#f59e0b",
  error: "#ef4444",
  deleted: "#6b7280",
};

const ChainNodeRow: React.FC<{ node: ChainNode; depth?: number }> = ({
  node,
  depth = 0,
}) => {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = (node.children ?? []).length > 0;
  const statusColor = NODE_STATUS_COLORS[node.status] ?? "#94a3b8";
  const indent = depth * 24;

  return (
    <div style={{ marginLeft: indent }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 8px",
          borderLeft: depth > 0 ? `2px solid ${statusColor}33` : "none",
          marginBottom: 2,
          borderRadius: 4,
          background: depth === 0 ? "rgba(255,255,255,0.04)" : "transparent",
        }}
      >
        {hasChildren && (
          <button
            onClick={() => setExpanded((p) => !p)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "#94a3b8",
              fontSize: "0.8rem",
              padding: "0 2px",
              lineHeight: 1,
            }}
          >
            {expanded ? "▼" : "▶"}
          </button>
        )}
        {!hasChildren && <span style={{ width: 18 }} />}

        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: statusColor,
            flexShrink: 0,
          }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <span style={{ fontWeight: depth === 0 ? 600 : 400, fontSize: "0.82rem" }}>
            {node.snapshot_name ?? node.snapshot_id.slice(0, 16) + "…"}
          </span>
          <span style={{ fontSize: "0.72rem", color: "#94a3b8", marginLeft: 8 }}>
            {node.snapshot_id}
          </span>
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0, alignItems: "center" }}>
          <span
            style={{
              fontSize: "0.7rem",
              padding: "1px 6px",
              borderRadius: 10,
              background: "rgba(100,116,139,0.2)",
              color: "#cbd5e1",
            }}
          >
            depth {node.chain_depth}
          </span>
          {node.size_gb != null && (
            <span style={{ fontSize: "0.72rem", color: "#64748b" }}>
              {node.size_gb} GB
            </span>
          )}
          <span
            style={{
              fontSize: "0.7rem",
              padding: "1px 6px",
              borderRadius: 10,
              background: `${statusColor}22`,
              color: statusColor,
            }}
          >
            {node.status}
          </span>
          {node.created_at && (
            <span style={{ fontSize: "0.68rem", color: "#475569" }}>
              {new Date(node.created_at).toLocaleDateString()}
            </span>
          )}
        </div>
      </div>
      {expanded &&
        (node.children ?? []).map((child) => (
          <ChainNodeRow key={child.snapshot_id} node={child} depth={depth + 1} />
        ))}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Policy editor
// ---------------------------------------------------------------------------

const PolicyEditor: React.FC<{
  projectId: string;
  volumeId: string;
  initial?: ChainPolicy | null;
  onSaved: (p: ChainPolicy) => void;
}> = ({ projectId, volumeId, initial, onSaved }) => {
  const [maxDepth, setMaxDepth] = useState(initial?.max_chain_depth ?? 5);
  const [autoRebase, setAutoRebase] = useState(initial?.auto_rebase ?? true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const save = async () => {
    setSaving(true);
    setMsg("");
    try {
      const updated = await apiFetch<ChainPolicy>(
        `/api/projects/${projectId}/chain-policies/${volumeId}`,
        { method: "PUT", body: JSON.stringify({ max_chain_depth: maxDepth, auto_rebase: autoRebase }) }
      );
      onSaved(updated);
      setMsg("✅ Policy saved");
      setTimeout(() => setMsg(""), 3000);
    } catch (e: any) {
      setMsg(`⚠️ ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        marginTop: 12,
        padding: "12px 16px",
        background: "rgba(255,255,255,0.03)",
        borderRadius: 8,
        border: "1px solid rgba(255,255,255,0.08)",
      }}
    >
      <h4 style={{ margin: "0 0 10px", fontSize: "0.84rem" }}>⚙️ Chain Policy</h4>
      {msg && (
        <div
          style={{
            marginBottom: 10,
            padding: "6px 10px",
            borderRadius: 6,
            background: msg.startsWith("✅") ? "#dcfce7" : "#fee2e2",
            color: msg.startsWith("✅") ? "#166534" : "#991b1b",
            fontSize: "0.8rem",
          }}
        >
          {msg}
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <label style={{ fontSize: "0.82rem" }}>
          Max chain depth:
          <input
            type="number"
            min={1}
            max={50}
            value={maxDepth}
            onChange={(e) => setMaxDepth(Number(e.target.value))}
            style={{
              marginLeft: 8,
              width: 60,
              padding: "3px 6px",
              borderRadius: 4,
              border: "1px solid #475569",
              background: "#1e293b",
              color: "#e2e8f0",
            }}
          />
        </label>
        <label style={{ fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 6 }}>
          <input
            type="checkbox"
            checked={autoRebase}
            onChange={(e) => setAutoRebase(e.target.checked)}
          />
          Auto-rebase when depth exceeded
        </label>
        <button
          onClick={save}
          disabled={saving}
          style={{
            padding: "5px 14px",
            background: "#2563eb",
            color: "white",
            border: "none",
            borderRadius: 4,
            cursor: saving ? "wait" : "pointer",
            fontSize: "0.8rem",
          }}
        >
          {saving ? "Saving…" : "💾 Save Policy"}
        </button>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const SnapshotChainExplorer: React.FC = () => {
  const [volumeId, setVolumeId] = useState("");
  const [searching, setSearching] = useState(false);
  const [summary, setSummary] = useState<ChainSummary | null>(null);
  const [policy, setPolicy] = useState<ChainPolicy | null>(null);
  const [error, setError] = useState("");

  const search = async () => {
    if (!volumeId.trim()) return;
    setSearching(true);
    setError("");
    setSummary(null);
    setPolicy(null);
    try {
      const data = await apiFetch<ChainSummary>(`/api/volumes/${volumeId.trim()}/chains`);
      setSummary(data);
      // Try loading the chain policy if we know the project
      if (data.chains.length > 0) {
        const pid = data.chains[0].project_id;
        try {
          const policies = await apiFetch<ChainPolicy[]>(
            `/api/projects/${pid}/chain-policies`
          );
          const p = policies.find((x) => x.volume_id === data.volume_id);
          setPolicy(p ?? null);
        } catch {
          /* optional */
        }
      }
    } catch (e: any) {
      setError(e.message ?? "Failed to load chains");
    } finally {
      setSearching(false);
    }
  };

  const projectId = summary?.chains?.[0]?.project_id ?? "";

  return (
    <div style={{ padding: "24px 32px", maxWidth: 960 }}>
      <h2 style={{ margin: "0 0 8px", fontSize: "1.25rem" }}>🔗 Snapshot Chain Explorer</h2>
      <p style={{ color: "#94a3b8", fontSize: "0.85rem", margin: "0 0 20px" }}>
        Visualise the full lineage of snapshots for a volume — base snapshots and their
        incremental descendants.
      </p>

      {/* Search bar */}
      <div style={{ display: "flex", gap: 12, marginBottom: 24 }}>
        <input
          type="text"
          placeholder="Enter volume ID…"
          value={volumeId}
          onChange={(e) => setVolumeId(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
          style={{
            flex: 1,
            padding: "9px 14px",
            borderRadius: 6,
            border: "1px solid #334155",
            background: "#1e293b",
            color: "#e2e8f0",
            fontSize: "0.9rem",
          }}
        />
        <button
          onClick={search}
          disabled={searching}
          style={{
            padding: "9px 20px",
            background: "#2563eb",
            color: "white",
            border: "none",
            borderRadius: 6,
            cursor: searching ? "wait" : "pointer",
            fontWeight: 600,
          }}
        >
          {searching ? "Searching…" : "🔍 Load Chains"}
        </button>
      </div>

      {error && (
        <div
          style={{
            padding: "12px 16px",
            borderRadius: 8,
            background: "#fee2e2",
            color: "#991b1b",
            marginBottom: 20,
          }}
        >
          ⚠️ {error}
        </div>
      )}

      {summary && (
        <>
          {/* Summary stats */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
              gap: 12,
              marginBottom: 20,
            }}
          >
            {[
              { label: "Total Snapshots", value: summary.total_snapshots },
              { label: "Base Snapshots", value: summary.base_snapshots },
              { label: "Max Chain Depth", value: summary.max_chain_depth },
              {
                label: "Total Size",
                value: summary.total_size_gb != null ? `${summary.total_size_gb} GB` : "—",
              },
            ].map(({ label, value }) => (
              <div
                key={label}
                style={{
                  padding: "12px 16px",
                  background: "rgba(255,255,255,0.04)",
                  borderRadius: 8,
                  border: "1px solid rgba(255,255,255,0.08)",
                }}
              >
                <div style={{ fontSize: "0.72rem", color: "#64748b", marginBottom: 4 }}>
                  {label}
                </div>
                <div style={{ fontSize: "1.3rem", fontWeight: 700 }}>{value}</div>
              </div>
            ))}
          </div>

          {/* Chain trees */}
          <div
            style={{
              background: "rgba(255,255,255,0.02)",
              border: "1px solid rgba(255,255,255,0.06)",
              borderRadius: 8,
              padding: "12px 16px",
              marginBottom: 20,
            }}
          >
            <h3 style={{ margin: "0 0 12px", fontSize: "0.92rem", color: "#cbd5e1" }}>
              Chain trees for volume{" "}
              <code style={{ fontSize: "0.8rem", color: "#94a3b8" }}>{summary.volume_id}</code>
              {summary.volume_name && (
                <span style={{ fontWeight: 400, marginLeft: 6 }}>({summary.volume_name})</span>
              )}
            </h3>
            {summary.chains.length === 0 ? (
              <p style={{ color: "#64748b", fontSize: "0.82rem" }}>No chains found.</p>
            ) : (
              summary.chains.map((rootNode) => (
                <ChainNodeRow key={rootNode.snapshot_id} node={rootNode} depth={0} />
              ))
            )}
          </div>

          {/* Policy editor */}
          {projectId && (
            <PolicyEditor
              projectId={projectId}
              volumeId={summary.volume_id}
              initial={policy}
              onSaved={setPolicy}
            />
          )}
        </>
      )}
    </div>
  );
};

export default SnapshotChainExplorer;
