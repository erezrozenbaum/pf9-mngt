import React, { useState, useEffect, useCallback } from 'react';
import '../styles/PlatformHealthTab.css';
import { apiFetch } from '../lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ComponentStatus {
  status: 'ok' | 'error' | 'unavailable';
  latency_ms?: number;
  error?: string;
  min_conn?: number;
  max_conn?: number;
}

interface WorkerStatus {
  worker: string;
  status: string;
  last_run_at?: string | null;
  details?: Record<string, unknown>;
  error?: string;
}

interface HealthResponse {
  overall: 'healthy' | 'degraded';
  checked_at: string;
  components: {
    database: ComponentStatus;
    redis: ComponentStatus;
    db_pool: ComponentStatus & { min_conn?: number; max_conn?: number };
  };
  workers: WorkerStatus[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusBadge(status: string) {
  const cls =
    status === 'ok' || status === 'healthy' || status === 'success' || status === 'completed'
      ? 'ph-badge ph-badge--ok'
      : status === 'never_run' || status === 'unavailable' || status === 'not_initialized'
      ? 'ph-badge ph-badge--warn'
      : 'ph-badge ph-badge--err';
  return <span className={cls}>{status}</span>;
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 2) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function workerLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  userRole: string;
}

const PlatformHealthTab: React.FC<Props> = ({ userRole: _userRole }) => {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchHealth = useCallback(async () => {
    try {
      const result = await apiFetch<HealthResponse>('/api/admin/platform/health');
      setData(result);
      setLastRefresh(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch platform health');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(fetchHealth, 30_000);
    return () => clearInterval(id);
  }, [autoRefresh, fetchHealth]);

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="ph-loading">
        <div className="ph-spinner" />
        <span>Checking platform health…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="ph-error">
        <span className="ph-error__icon">⚠️</span>
        <span>{error}</span>
        <button className="ph-btn" onClick={fetchHealth}>Retry</button>
      </div>
    );
  }

  if (!data) return null;

  const overallOk = data.overall === 'healthy';

  return (
    <div className="ph-root">
      {/* ── Header ── */}
      <div className="ph-header">
        <div className="ph-header__left">
          <h2 className="ph-title">Platform Health</h2>
          <span className={`ph-overall ${overallOk ? 'ph-overall--ok' : 'ph-overall--degraded'}`}>
            {overallOk ? '✅ All systems operational' : '⚠️ Degraded'}
          </span>
        </div>
        <div className="ph-header__right">
          {lastRefresh && (
            <span className="ph-timestamp">
              Last checked: {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <label className="ph-toggle">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto-refresh (30s)
          </label>
          <button className="ph-btn" onClick={fetchHealth}>
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* ── Components grid ── */}
      <section className="ph-section">
        <h3 className="ph-section__title">Infrastructure Components</h3>
        <div className="ph-grid">

          {/* Database */}
          <div className={`ph-card ${data.components.database.status === 'ok' ? '' : 'ph-card--warn'}`}>
            <div className="ph-card__header">
              <span className="ph-card__icon">🗄️</span>
              <span className="ph-card__name">Database</span>
              {statusBadge(data.components.database.status)}
            </div>
            <div className="ph-card__body">
              {data.components.database.latency_ms !== undefined && (
                <div className="ph-metric">
                  <span className="ph-metric__label">Round-trip latency</span>
                  <span className="ph-metric__value">{data.components.database.latency_ms} ms</span>
                </div>
              )}
              {data.components.database.error && (
                <div className="ph-metric ph-metric--error">
                  <span className="ph-metric__label">Error</span>
                  <span className="ph-metric__value">{data.components.database.error}</span>
                </div>
              )}
            </div>
          </div>

          {/* Redis */}
          <div className={`ph-card ${data.components.redis.status === 'ok' ? '' : 'ph-card--warn'}`}>
            <div className="ph-card__header">
              <span className="ph-card__icon">⚡</span>
              <span className="ph-card__name">Redis Cache</span>
              {statusBadge(data.components.redis.status)}
            </div>
            <div className="ph-card__body">
              {data.components.redis.latency_ms !== undefined && (
                <div className="ph-metric">
                  <span className="ph-metric__label">Round-trip latency</span>
                  <span className="ph-metric__value">{data.components.redis.latency_ms} ms</span>
                </div>
              )}
              {data.components.redis.error && (
                <div className="ph-metric ph-metric--error">
                  <span className="ph-metric__label">Error</span>
                  <span className="ph-metric__value">{data.components.redis.error}</span>
                </div>
              )}
            </div>
          </div>

          {/* Connection Pool */}
          <div className={`ph-card ${data.components.db_pool.status === 'ok' ? '' : 'ph-card--warn'}`}>
            <div className="ph-card__header">
              <span className="ph-card__icon">🔌</span>
              <span className="ph-card__name">DB Connection Pool</span>
              {statusBadge(data.components.db_pool.status)}
            </div>
            <div className="ph-card__body">
              {data.components.db_pool.min_conn !== undefined && (
                <div className="ph-metric">
                  <span className="ph-metric__label">Min connections</span>
                  <span className="ph-metric__value">{data.components.db_pool.min_conn}</span>
                </div>
              )}
              {data.components.db_pool.max_conn !== undefined && (
                <div className="ph-metric">
                  <span className="ph-metric__label">Max connections</span>
                  <span className="ph-metric__value">{data.components.db_pool.max_conn}</span>
                </div>
              )}
              {data.components.db_pool.error && (
                <div className="ph-metric ph-metric--error">
                  <span className="ph-metric__label">Error</span>
                  <span className="ph-metric__value">{data.components.db_pool.error}</span>
                </div>
              )}
            </div>
          </div>

        </div>
      </section>

      {/* ── Workers ── */}
      <section className="ph-section">
        <h3 className="ph-section__title">Background Workers</h3>
        <table className="ph-table">
          <thead>
            <tr>
              <th>Worker</th>
              <th>Status</th>
              <th>Last Run</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {data.workers.map((w) => (
              <tr key={w.worker} className={w.status === 'failed' || w.status === 'query_error' ? 'ph-row--warn' : ''}>
                <td className="ph-worker-name">{workerLabel(w.worker)}</td>
                <td>{statusBadge(w.status)}</td>
                <td className="ph-timestamp-cell">
                  {w.last_run_at ? (
                    <span title={w.last_run_at}>{relativeTime(w.last_run_at)}</span>
                  ) : '—'}
                </td>
                <td className="ph-details-cell">
                  {w.details
                    ? Object.entries(w.details)
                        .filter(([, v]) => v !== null && v !== undefined)
                        .map(([k, v]) => (
                          <span key={k} className="ph-detail-pill">
                            {k.replace(/_/g, ' ')}: {String(v)}
                          </span>
                        ))
                    : w.error
                    ? <span className="ph-detail-error">{w.error}</span>
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <p className="ph-footer">
        Data as of {new Date(data.checked_at).toLocaleString()}
      </p>
    </div>
  );
};

export default PlatformHealthTab;
