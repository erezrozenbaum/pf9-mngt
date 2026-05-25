/**
 * NodeLogsTab — Platform9 Hypervisor Node Log Viewer (v2.12.0)
 *
 * Displays recent log lines from Platform9 hypervisor nodes.
 * Fetches from GET /api/admin/nodes and GET /api/admin/nodes/{id}/logs.
 *
 * Features:
 * - Node selector (dropdown populated from /api/admin/nodes)
 * - Component selector (pf9-hostagent, pf9-comms, du-agent, pf9-kube)
 * - Log line count selector (50 / 200 / 500 / 1000)
 * - Auto-refresh toggle (30 s)
 * - Filter bar (keyword search, level filter)
 * - Copy-to-clipboard
 * - "Refresh" button with cache-bypass
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiFetch } from '../lib/api';
import '../styles/NodeLogsTab.css';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NodeInfo {
  id: string;
  name: string;
  ip_address: string | null;
  state: string | null;
  status: string | null;
  region_id: string | null;
}

interface LogLine {
  ts: string | null;
  level: string;
  component: string;
  message: string;
}

interface NodeLogsResponse {
  node_id: string;
  node_name: string;
  node_ip: string | null;
  component: string;
  source: string;
  log_lines: LogLine[];
  total_lines: number;
  fetch_ms: number;
  fetched_at: string | null;
  error: string | null;
  from_cache: boolean;
}

interface NodesResponse {
  nodes: NodeInfo[];
  log_source: string;
  log_source_configured: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const LEVEL_COLORS: Record<string, string> = {
  ERROR:   'var(--color-error)',
  WARNING: 'var(--color-warning)',
  WARN:    'var(--color-warning)',
  DEBUG:   'var(--color-text-muted)',
  INFO:    'var(--color-text-primary)',
};

const COMPONENTS = ['pf9-hostagent', 'pf9-comms', 'du-agent', 'pf9-kube'];
const LINE_COUNT_OPTIONS = [50, 200, 500, 1000];

function levelColor(level: string): string {
  return LEVEL_COLORS[level?.toUpperCase()] ?? 'var(--color-text-primary)';
}

function stateColor(state: string | null): string {
  if (state === 'active') return 'var(--color-success)';
  if (state === 'error' || state === 'failed') return 'var(--color-error)';
  if (state === 'building' || state === 'converging') return 'var(--color-warning)';
  return 'var(--color-text-muted)';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function NodeLogsTab() {
  const [nodes, setNodes]           = useState<NodeInfo[]>([]);
  const [logSource, setLogSource]   = useState<string>('');
  const [configured, setConfigured] = useState<boolean>(false);

  const [selectedNode, setSelectedNode]       = useState<string>('');
  const [selectedComp, setSelectedComp]       = useState<string>('pf9-hostagent');
  const [lineCount, setLineCount]             = useState<number>(200);
  const [filter, setFilter]                   = useState<string>('');
  const [levelFilter, setLevelFilter]         = useState<string>('');
  const [autoRefresh, setAutoRefresh]         = useState<boolean>(false);

  const [logs, setLogs]             = useState<LogLine[]>([]);
  const [meta, setMeta]             = useState<Omit<NodeLogsResponse, 'log_lines'> | null>(null);
  const [loading, setLoading]       = useState<boolean>(false);
  const [error, setError]           = useState<string | null>(null);

  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Fetch node list ──
  useEffect(() => {
    apiFetch<NodesResponse>('/api/admin/nodes')
      .then(data => {
        setNodes(data.nodes);
        setLogSource(data.log_source);
        setConfigured(data.log_source_configured);
        if (data.nodes.length > 0) setSelectedNode(data.nodes[0].id);
      })
      .catch(() => setError('Failed to load node list'));
  }, []);

  // ── Fetch logs ──
  const fetchLogs = useCallback(async (bypass: boolean = false) => {
    if (!selectedNode) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        component: selectedComp,
        lines: String(lineCount),
        ...(bypass ? { refresh: 'true' } : {}),
      });
      const data = await apiFetch<NodeLogsResponse>(
        `/api/admin/nodes/${encodeURIComponent(selectedNode)}/logs?${params}`
      );
      setLogs(data.log_lines);
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { log_lines: _ll, ...metaOnly } = data;
      setMeta(metaOnly);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to fetch logs');
    } finally {
      setLoading(false);
    }
  }, [selectedNode, selectedComp, lineCount]);

  // Re-fetch when node / component / line count changes
  useEffect(() => {
    if (selectedNode) fetchLogs();
  }, [selectedNode, selectedComp, lineCount, fetchLogs]);

  // Auto-refresh
  useEffect(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    if (autoRefresh && selectedNode) {
      refreshTimer.current = setTimeout(() => fetchLogs(), 30_000);
    }
    return () => { if (refreshTimer.current) clearTimeout(refreshTimer.current); };
  }, [autoRefresh, logs, fetchLogs, selectedNode]);

  // ── Filtered lines ──
  const filteredLogs = logs.filter(line => {
    const matchesLevel = !levelFilter || line.level?.toUpperCase() === levelFilter;
    const matchesText  = !filter || line.message.toLowerCase().includes(filter.toLowerCase());
    return matchesLevel && matchesText;
  });

  // ── Copy to clipboard ──
  const handleCopy = () => {
    const text = filteredLogs.map(l => `[${l.ts ?? '---'}] [${l.level}] ${l.message}`).join('\n');
    navigator.clipboard.writeText(text).catch(() => {});
  };

  // ── Render ──
  return (
    <div className="node-logs-container">
      <div className="node-logs-header">
        <h2>Platform9 Node Logs</h2>
        <p className="node-logs-subtitle">
          Recent system log lines from hypervisor nodes.&nbsp;
          Source: <strong>{logSource || '—'}</strong>
          {!configured && logSource !== 'disabled' && (
            <span className="node-logs-badge node-logs-badge--warn">not configured</span>
          )}
          {logSource === 'disabled' && (
            <span className="node-logs-badge node-logs-badge--warn">
              disabled — set NODE_LOG_SOURCE in env
            </span>
          )}
        </p>
      </div>

      {/* ── Controls ── */}
      <div className="node-logs-controls">
        {/* Node selector */}
        <div className="node-logs-control-group">
          <label>Node</label>
          <select value={selectedNode} onChange={e => setSelectedNode(e.target.value)}>
            {nodes.length === 0 && <option value="">No nodes found</option>}
            {nodes.map(n => (
              <option key={n.id} value={n.id}>
                {n.name || n.id}
                {n.state ? ` (${n.state})` : ''}
              </option>
            ))}
          </select>
        </div>

        {/* Component selector */}
        <div className="node-logs-control-group">
          <label>Component</label>
          <select value={selectedComp} onChange={e => setSelectedComp(e.target.value)}>
            {COMPONENTS.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        {/* Line count */}
        <div className="node-logs-control-group">
          <label>Lines</label>
          <select value={lineCount} onChange={e => setLineCount(Number(e.target.value))}>
            {LINE_COUNT_OPTIONS.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>

        {/* Level filter */}
        <div className="node-logs-control-group">
          <label>Level</label>
          <select value={levelFilter} onChange={e => setLevelFilter(e.target.value)}>
            <option value="">All</option>
            <option value="ERROR">ERROR</option>
            <option value="WARNING">WARNING</option>
            <option value="INFO">INFO</option>
            <option value="DEBUG">DEBUG</option>
          </select>
        </div>

        {/* Keyword filter */}
        <div className="node-logs-control-group node-logs-control-group--wide">
          <label>Filter</label>
          <input
            type="text"
            placeholder="keyword search…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
        </div>

        {/* Actions */}
        <div className="node-logs-actions">
          <button className="btn btn--sm btn--primary" onClick={() => fetchLogs(true)} disabled={loading || !selectedNode}>
            {loading ? 'Loading…' : '↺ Refresh'}
          </button>
          <button className="btn btn--sm btn--secondary" onClick={handleCopy} disabled={filteredLogs.length === 0}>
            Copy
          </button>
          <label className="node-logs-toggle">
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
            &nbsp;Auto (30 s)
          </label>
        </div>
      </div>

      {/* ── Node status bar ── */}
      {nodes.length > 0 && selectedNode && (
        <div className="node-logs-node-bar">
          {nodes.filter(n => n.id === selectedNode).map(n => (
            <div key={n.id} className="node-logs-node-info">
              <span className="node-logs-node-dot" style={{ background: stateColor(n.state) }} />
              <span><strong>{n.name || n.id}</strong></span>
              {n.ip_address && <span className="node-logs-node-ip">{n.ip_address}</span>}
              {n.state && <span className="node-logs-node-state" style={{ color: stateColor(n.state) }}>{n.state}</span>}
              {n.region_id && <span className="node-logs-node-region">{n.region_id}</span>}
            </div>
          ))}
          {meta && (
            <div className="node-logs-meta">
              {filteredLogs.length}/{meta.total_lines ?? logs.length} lines
              {meta.from_cache && <span className="node-logs-badge">cached</span>}
              {meta.fetch_ms != null && <span className="node-logs-badge">{meta.fetch_ms} ms</span>}
              {meta.fetched_at && <span className="node-logs-badge">{new Date(meta.fetched_at).toLocaleTimeString()}</span>}
            </div>
          )}
        </div>
      )}

      {/* ── Error banner ── */}
      {(error || meta?.error) && (
        <div className="node-logs-error">
          ⚠ {error || meta?.error}
        </div>
      )}

      {/* ── Log source disabled message ── */}
      {logSource === 'disabled' && !loading && (
        <div className="node-logs-disabled">
          <h3>Node log fetching is disabled</h3>
          <p>
            Set <code>NODE_LOG_SOURCE=resmgr</code> (uses PF9 DU API) or{' '}
            <code>NODE_LOG_SOURCE=hostagent</code> (direct hostagent port 9080)
            in your environment to enable this feature.
          </p>
          <p>See <strong>Admin › System Settings</strong> or <code>.env.example</code> for details.</p>
        </div>
      )}

      {/* ── Log lines ── */}
      {logSource !== 'disabled' && (
        <div className="node-logs-output">
          {loading && <div className="node-logs-loading">Fetching logs…</div>}
          {!loading && filteredLogs.length === 0 && !error && (
            <div className="node-logs-empty">No log lines match the current filter.</div>
          )}
          {filteredLogs.map((line, i) => (
            <div key={i} className="node-logs-line">
              <span className="node-logs-ts">{line.ts ? new Date(line.ts).toLocaleTimeString('en-GB', { hour12: false }) : '—'}</span>
              <span className="node-logs-level" style={{ color: levelColor(line.level) }}>{(line.level || 'INFO').padEnd(7)}</span>
              <span className="node-logs-msg">{line.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
