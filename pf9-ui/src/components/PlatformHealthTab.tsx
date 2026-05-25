import React, { useState, useEffect, useCallback, useRef } from 'react';
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

type Series = [number, number][]; // [timestamp, value]

interface PodMetric {
  pod: string;
  short_name: string;
  cpu_series: Series;
  ram_series: Series;
}

interface PvcMetric {
  name: string;
  used_bytes: number;
  capacity_bytes: number;
  pct: number;
}

interface MetricsResponse {
  prometheus_available: boolean;
  namespace?: string;
  pods: PodMetric[];
  pvcs: PvcMetric[];
  http_rps_series: Series;
}

// ---------------------------------------------------------------------------
// Sparkline canvas component
// ---------------------------------------------------------------------------

interface SparklineProps {
  series: Series;
  color: string;
  width?: number;
  height?: number;
  unit?: string; // for tooltip
}

const Sparkline: React.FC<SparklineProps> = ({ series, color, width = 160, height = 40 }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || series.length < 2) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Canvas API cannot resolve CSS variables — resolve at draw time
    let resolvedColor = color;
    if (color.startsWith('var(')) {
      const m = color.match(/var\((--[\w-]+)(?:,\s*([^)]+))?\)/);
      if (m) {
        const computed = getComputedStyle(document.documentElement)
          .getPropertyValue(m[1]).trim();
        resolvedColor = computed || m[2]?.trim() || '#3b82f6';
      }
    }

    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, width, height);

    const values = series.map(([, v]) => v);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const pad = 3;

    const toX = (i: number) => pad + (i / (series.length - 1)) * (width - pad * 2);
    const toY = (v: number) => (height - pad) - ((v - min) / range) * (height - pad * 2);

    // Fill area
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, resolvedColor + '40');
    gradient.addColorStop(1, resolvedColor + '08');
    ctx.beginPath();
    ctx.moveTo(toX(0), height);
    series.forEach(([, v], i) => ctx.lineTo(toX(i), toY(v)));
    ctx.lineTo(toX(series.length - 1), height);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Line
    ctx.beginPath();
    series.forEach(([, v], i) => {
      if (i === 0) ctx.moveTo(toX(i), toY(v));
      else ctx.lineTo(toX(i), toY(v));
    });
    ctx.strokeStyle = resolvedColor;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = 'round';
    ctx.stroke();

    // Latest value dot
    const last = series[series.length - 1];
    ctx.beginPath();
    ctx.arc(toX(series.length - 1), toY(last[1]), 2.5, 0, Math.PI * 2);
    ctx.fillStyle = resolvedColor;
    ctx.fill();
  }, [series, color, width, height]);

  if (series.length < 2) {
    return <div style={{ width, height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)', fontSize: '0.7rem' }}>no data</div>;
  }
  return <canvas ref={canvasRef} style={{ display: 'block' }} />;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusBadge(status: string) {
  const cls =
    status === 'ok' || status === 'healthy' || status === 'success' || status === 'completed'
      ? 'ph-badge ph-badge--ok'
      : status === 'never_run' || status === 'unavailable' || status === 'not_initialized' || status === 'skipped'
      ? 'ph-badge ph-badge--warn'
      : 'ph-badge ph-badge--err';
  return <span className={cls}>{status.replace(/_/g, ' ')}</span>;
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
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function lastVal(series: Series): number {
  return series.length ? series[series.length - 1][1] : 0;
}

function componentColor(status: string): string {
  if (status === 'ok') return 'var(--color-success)';
  if (status === 'error') return 'var(--color-error)';
  return 'var(--color-warning)';
}

// ---------------------------------------------------------------------------
// KPI tiles  (same pattern as Right-Sizing SummaryCards)
// ---------------------------------------------------------------------------

function SummaryTiles({ data }: { data: HealthResponse }) {
  const componentCount = 3;
  const componentOk = [data.components.database, data.components.redis, data.components.db_pool]
    .filter((c) => c.status === 'ok').length;
  const workerOk = data.workers.filter(
    (w) => !['failed', 'error', 'query_error'].includes(w.status),
  ).length;
  const workerCount = data.workers.length;
  const dbMs = data.components.database.latency_ms;
  const redisMs = data.components.redis.latency_ms;

  const tiles = [
    {
      label: 'Components',
      value: `${componentOk} / ${componentCount}`,
      color: componentOk === componentCount ? 'var(--color-success)' : 'var(--color-error)',
    },
    {
      label: 'Workers',
      value: `${workerOk} / ${workerCount}`,
      color: workerOk === workerCount ? 'var(--color-success)' : 'var(--color-warning)',
    },
    {
      label: 'DB Latency',
      value: dbMs != null ? `${dbMs} ms` : '—',
      color: dbMs == null ? 'var(--color-text-muted)' : dbMs < 5 ? 'var(--color-success)' : dbMs < 20 ? 'var(--color-warning)' : 'var(--color-error)',
    },
    {
      label: 'Redis Latency',
      value: redisMs != null ? `${redisMs} ms` : '—',
      color: redisMs == null ? 'var(--color-text-muted)' : redisMs < 5 ? 'var(--color-success)' : redisMs < 20 ? 'var(--color-warning)' : 'var(--color-error)',
    },
  ];

  return (
    <div className="ph-summary-tiles">
      {tiles.map(({ label, value, color }) => (
        <div key={label} className="metric-card">
          <div className="metric-label">{label}</div>
          <div className="metric-value" style={{ color }}>{value}</div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component card (infrastructure)
// ---------------------------------------------------------------------------

function ComponentCard({ icon, name, data }: { icon: string; name: string; data: ComponentStatus }) {
  const color = componentColor(data.status);
  return (
    <div className="card" style={{ borderLeft: `4px solid ${color}`, padding: '1rem 1.25rem', borderRadius: '8px', background: 'var(--color-surface)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.6rem' }}>
        <span style={{ fontSize: '1.15rem' }}>{icon}</span>
        <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{name}</span>
        <span className="ph-badge" style={{ marginLeft: 'auto', background: `${color}20`, color, border: `1px solid ${color}40` }}>{data.status}</span>
      </div>
      {data.latency_ms !== undefined && (
        <div className="ph-metric"><span className="ph-metric__label">Round-trip latency</span><span className="ph-metric__value" style={{ color }}>{data.latency_ms} ms</span></div>
      )}
      {data.min_conn !== undefined && (
        <div className="ph-metric"><span className="ph-metric__label">Min connections</span><span className="ph-metric__value">{data.min_conn}</span></div>
      )}
      {data.max_conn !== undefined && (
        <div className="ph-metric"><span className="ph-metric__label">Max connections</span><span className="ph-metric__value">{data.max_conn}</span></div>
      )}
      {data.error && (
        <div className="ph-metric ph-metric--error"><span className="ph-metric__label">Error</span><span className="ph-metric__value">{data.error}</span></div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pod metrics card
// ---------------------------------------------------------------------------

function PodCard({ pod }: { pod: PodMetric }) {
  const cpuCores = lastVal(pod.cpu_series);
  const ramBytes = lastVal(pod.ram_series);
  const cpuColor = cpuCores > 0.8 ? 'var(--color-error)' : cpuCores > 0.4 ? 'var(--color-warning)' : 'var(--color-info, #3b82f6)';
  const ramColor = 'var(--color-info, #3b82f6)';

  return (
    <div className="card ph-pod-card">
      <div className="ph-pod-card__name" title={pod.pod}>{pod.short_name}</div>
      <div className="ph-pod-card__metrics">
        <div className="ph-pod-metric">
          <div className="ph-pod-metric__label">
            CPU <span style={{ color: cpuColor, fontWeight: 600 }}>{cpuCores < 0.001 ? '<1m' : cpuCores < 1 ? `${(cpuCores * 1000).toFixed(0)}m` : `${cpuCores.toFixed(2)}`} cores</span>
          </div>
          <Sparkline series={pod.cpu_series} color={cpuColor} width={150} height={38} />
        </div>
        <div className="ph-pod-metric">
          <div className="ph-pod-metric__label">
            RAM <span style={{ color: ramColor, fontWeight: 600 }}>{fmtBytes(ramBytes)}</span>
          </div>
          <Sparkline series={pod.ram_series} color={ramColor} width={150} height={38} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PVC usage bar
// ---------------------------------------------------------------------------

function PvcBar({ pvc }: { pvc: PvcMetric }) {
  const color = pvc.pct > 90 ? 'var(--color-error)' : pvc.pct > 75 ? 'var(--color-warning)' : 'var(--color-success)';
  return (
    <div className="ph-pvc-row">
      <div className="ph-pvc-name" title={pvc.name}>{pvc.name}</div>
      <div className="ph-pvc-bar-wrap">
        <div className="ph-pvc-bar-fill" style={{ width: `${pvc.pct}%`, background: color }} />
      </div>
      <div className="ph-pvc-pct" style={{ color }}>{pvc.pct}%</div>
      <div className="ph-pvc-size">{fmtBytes(pvc.used_bytes)} / {fmtBytes(pvc.capacity_bytes)}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  userRole: string;
}

const PlatformHealthTab: React.FC<Props> = ({ userRole: _userRole }) => {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchAll = useCallback(async () => {
    try {
      const [health, met] = await Promise.all([
        apiFetch<HealthResponse>('/api/admin/platform/health'),
        apiFetch<MetricsResponse>('/api/admin/platform/metrics').catch(() => null),
      ]);
      setData(health);
      setMetrics(met);
      setLastRefresh(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch platform health');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(fetchAll, 30_000);
    return () => clearInterval(id);
  }, [autoRefresh, fetchAll]);

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
        <button className="ph-btn" onClick={fetchAll}>Retry</button>
      </div>
    );
  }

  if (!data) return null;

  const overallOk = data.overall === 'healthy';
  const hasPodMetrics = metrics?.prometheus_available && (metrics.pods?.length ?? 0) > 0;
  const hasPvcs = metrics?.prometheus_available && (metrics.pvcs?.length ?? 0) > 0;

  return (
    <div className="ph-root">
      {/* ── Page header ── */}
      <div className="ph-header">
        <div className="ph-header__left">
          <h2 className="ph-title">Platform Health</h2>
          <span className={`ph-overall ${overallOk ? 'ph-overall--ok' : 'ph-overall--degraded'}`}>
            {overallOk ? '✅ All systems operational' : '⚠️ Degraded'}
          </span>
        </div>
        <div className="ph-header__right">
          {lastRefresh && (
            <span className="ph-timestamp">Last checked: {lastRefresh.toLocaleTimeString()}</span>
          )}
          <label className="ph-toggle">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            Auto-refresh (30s)
          </label>
          <button className="ph-btn" onClick={fetchAll}>↻ Refresh</button>
        </div>
      </div>

      {/* ── KPI summary tiles ── */}
      <SummaryTiles data={data} />

      {/* ── Infrastructure components ── */}
      <section className="ph-section">
        <h3 className="ph-section__title">Infrastructure Components</h3>
        <div className="ph-grid">
          <ComponentCard icon="🗄️" name="Database" data={data.components.database} />
          <ComponentCard icon="⚡" name="Redis Cache" data={data.components.redis} />
          <ComponentCard icon="🔌" name="DB Connection Pool" data={data.components.db_pool} />
        </div>
      </section>

      {/* ── Background workers ── */}
      <section className="ph-section">
        <h3 className="ph-section__title">Background Workers</h3>
        <div className="ph-worker-list">
          {data.workers.map((w) => {
            const isOk = !['failed', 'error', 'query_error'].includes(w.status);
            const workerColor = isOk ? 'var(--color-success)' : 'var(--color-error)';
            return (
              <div key={w.worker} className="card" style={{ borderLeft: `4px solid ${workerColor}`, padding: '0.85rem 1.25rem', borderRadius: '8px', background: 'var(--color-surface)', display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
                <div style={{ flex: '0 0 190px' }}>
                  <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>{workerLabel(w.worker)}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginTop: '0.1rem' }}>
                    {w.last_run_at ? <span title={w.last_run_at}>{relativeTime(w.last_run_at)}</span> : 'never run'}
                  </div>
                </div>
                <div>{statusBadge(w.status)}</div>
                <div style={{ flex: 1, display: 'flex', flexWrap: 'wrap', gap: '0.4rem', justifyContent: 'flex-end' }}>
                  {w.details
                    ? Object.entries(w.details)
                        .filter(([, v]) => v !== null && v !== undefined)
                        .map(([k, v]) => (
                          <span key={k} className="ph-detail-pill">{k.replace(/_/g, ' ')}: {String(v)}</span>
                        ))
                    : w.error
                    ? <span className="ph-detail-error">{w.error}</span>
                    : null}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Pod metrics (Prometheus) ── */}
      {metrics && !metrics.prometheus_available && (
        <section className="ph-section">
          <h3 className="ph-section__title">Pod Metrics</h3>
          <div className="ph-prometheus-unavailable">
            <span>📊</span>
            <span>Prometheus not reachable — pod metrics are only available in the Kubernetes environment.</span>
          </div>
        </section>
      )}

      {hasPodMetrics && (
        <section className="ph-section">
          <h3 className="ph-section__title">Pod Metrics <span className="ph-section__sub">CPU &amp; RAM · last 1h · {metrics!.namespace}</span></h3>
          <div className="ph-pod-grid">
            {metrics!.pods.map((pod) => (
              <PodCard key={pod.pod} pod={pod} />
            ))}
          </div>
        </section>
      )}

      {/* ── HTTP request rate ── */}
      {metrics?.prometheus_available && (metrics.http_rps_series?.length ?? 0) > 1 && (
        <section className="ph-section">
          <h3 className="ph-section__title">Network Receive Rate <span className="ph-section__sub">packets/s · last 1h · {metrics.namespace}</span></h3>
          <div className="card" style={{ padding: '1rem 1.25rem', borderRadius: '8px', background: 'var(--color-surface)' }}>
            <Sparkline series={metrics.http_rps_series} color="var(--color-info, #3b82f6)" width={700} height={60} />
          </div>
        </section>
      )}

      {/* ── PVC usage ── */}
      {hasPvcs && (
        <section className="ph-section">
          <h3 className="ph-section__title">PVC Storage Usage</h3>
          <div className="card" style={{ padding: '1rem 1.25rem', borderRadius: '8px', background: 'var(--color-surface)' }}>
            {metrics!.pvcs.map((pvc) => (
              <PvcBar key={pvc.name} pvc={pvc} />
            ))}
          </div>
        </section>
      )}

      <p className="ph-footer">Data as of {new Date(data.checked_at).toLocaleString()}</p>
    </div>
  );
};

export default PlatformHealthTab;
