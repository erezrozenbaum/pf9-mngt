import React, { useState, useEffect } from 'react';
import '../styles/APIMetricsTab.css';

interface Endpoint {
  endpoint: string;
  count: number;
  avg_duration?: number;
  min_duration?: number;
  max_duration?: number;
  p50?: number;
  p95?: number;
  p99?: number;
  avg_ms?: number;
}

interface SlowRequest {
  endpoint?: string;
  method?: string;
  path?: string;
  duration?: number;
  duration_ms?: number;
  timestamp: string;
  status_code?: number;
  status?: number;
}

interface ErrorRequest {
  endpoint?: string;
  method?: string;
  path?: string;
  status_code?: number;
  status?: number;
  timestamp: string;
  duration?: number;
  duration_ms?: number;
}

interface Metrics {
  uptime_seconds: number;
  total_requests: number;
  requests_per_second: number;
  status_codes: Record<string, number>;
  top_endpoints: Endpoint[];
  slow_endpoints: Endpoint[];
  recent_slow_requests: SlowRequest[];
  recent_errors: ErrorRequest[];
}

export const APIMetricsTab: React.FC = () => {
  const API_BASE = 'http://localhost:8000';
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const token = localStorage.getItem('auth_token');
        const response = await fetch(`${API_BASE}/api/metrics`, {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        setMetrics(data);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch metrics');
      } finally {
        setLoading(false);
      }
    };

    fetchMetrics();

    if (autoRefresh) {
      const interval = setInterval(fetchMetrics, 5000); // Refresh every 5 seconds
      return () => clearInterval(interval);
    }
  }, [autoRefresh]);

  const formatDurationSeconds = (seconds?: number) => {
    if (seconds === undefined || seconds === null || Number.isNaN(seconds)) return '—';
    if (seconds < 0.001) return `${(seconds * 1000000).toFixed(0)}µs`;
    if (seconds < 1) return `${(seconds * 1000).toFixed(2)}ms`;
    return `${seconds.toFixed(2)}s`;
  };

  const formatDurationMs = (ms?: number) => {
    if (ms === undefined || ms === null || Number.isNaN(ms)) return '—';
    if (ms < 1) return `${(ms * 1000).toFixed(0)}µs`;
    if (ms < 1000) return `${ms.toFixed(2)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  };

  const getEndpointLabel = (entry: { endpoint?: string; method?: string; path?: string }) => {
    if (entry.endpoint) return entry.endpoint;
    if (entry.method && entry.path) return `${entry.method} ${entry.path}`;
    return '—';
  };

  const getStatusCode = (entry: { status_code?: number; status?: number }) => {
    return entry.status_code ?? entry.status ?? 0;
  };

  const formatUptime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${hours}h ${minutes}m ${secs}s`;
  };

  if (loading) {
    return <div className="api-metrics-container">Loading metrics...</div>;
  }

  if (error) {
    return (
      <div className="api-metrics-container">
        <div className="api-metrics-error">
          <strong>Error:</strong> {error}
        </div>
      </div>
    );
  }

  if (!metrics) {
    return <div className="api-metrics-container">No metrics available</div>;
  }

  const statusEntries = Object.entries(metrics.status_codes as Record<string, number>);

  const successCount = statusEntries
    .filter(([code]) => code.startsWith('2'))
    .reduce((sum, [, count]) => sum + count, 0);

  const errorCount = statusEntries
    .filter(([code]) => code.startsWith('4') || code.startsWith('5'))
    .reduce((sum, [, count]) => sum + count, 0);

  return (
    <div className="api-metrics-container">
      <div className="api-metrics-header">
        <h2>API Performance Metrics</h2>
        <label className="api-metrics-refresh-label">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          Auto-refresh (5s)
        </label>
      </div>

      {/* Summary Stats */}
      <div className="api-metrics-summary-grid">
        <div className="api-metrics-summary-card">
          <div className="api-metrics-label">Uptime</div>
          <div className="api-metrics-value">{formatUptime(metrics.uptime_seconds)}</div>
        </div>
        <div className="api-metrics-summary-card">
          <div className="api-metrics-label">Total Requests</div>
          <div className="api-metrics-value">{metrics.total_requests.toLocaleString()}</div>
        </div>
        <div className="api-metrics-summary-card">
          <div className="api-metrics-label">Requests/Second</div>
          <div className="api-metrics-value">{metrics.requests_per_second.toFixed(2)}</div>
        </div>
        <div className="api-metrics-summary-card">
          <div className="api-metrics-label">Success Rate</div>
          <div className="api-metrics-value">
            {metrics.total_requests > 0
              ? ((successCount / metrics.total_requests) * 100).toFixed(1)
              : '0'}
            %
          </div>
        </div>
        <div className="api-metrics-summary-card">
          <div className="api-metrics-label">Successful</div>
          <div className="api-metrics-value-green">{successCount.toLocaleString()}</div>
        </div>
        <div className="api-metrics-summary-card">
          <div className="api-metrics-label">Errors</div>
          <div className="api-metrics-value-red">{errorCount.toLocaleString()}</div>
        </div>
      </div>

      {/* Status Codes */}
      <div className="api-metrics-section">
        <h3>Status Code Distribution</h3>
        <div className="api-metrics-status-grid">
          {statusEntries
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([code, count]) => (
              <div key={code} className="api-metrics-status-item">
                <span className="api-metrics-status-code">{code}:</span>
                <span className="api-metrics-status-count">{count.toLocaleString()}</span>
              </div>
            ))}
        </div>
      </div>

      {/* Top Endpoints */}
      {metrics.top_endpoints.length > 0 && (
        <div className="api-metrics-section">
          <h3>Top Endpoints by Request Count</h3>
          <table className="api-metrics-table">
            <thead>
              <tr>
                <th>Endpoint</th>
                <th>Count</th>
                <th>Avg Duration</th>
                <th>Min Duration</th>
                <th>Max Duration</th>
                <th>p50</th>
                <th>p95</th>
                <th>p99</th>
              </tr>
            </thead>
            <tbody>
              {metrics.top_endpoints.map((ep) => (
                <tr key={ep.endpoint}>
                  <td className="api-metrics-endpoint">{ep.endpoint}</td>
                  <td>{ep.count.toLocaleString()}</td>
                  <td>{formatDurationSeconds(ep.avg_duration)}</td>
                  <td>{formatDurationSeconds(ep.min_duration)}</td>
                  <td>{formatDurationSeconds(ep.max_duration)}</td>
                  <td>{formatDurationSeconds(ep.p50)}</td>
                  <td>{formatDurationSeconds(ep.p95)}</td>
                  <td>{formatDurationSeconds(ep.p99)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Slow Endpoints */}
      {metrics.slow_endpoints.length > 0 && (
        <div className="api-metrics-section">
          <h3>Slow Endpoints (avg &gt; 1s)</h3>
          <table className="api-metrics-table">
            <thead>
              <tr>
                <th>Endpoint</th>
                <th>Avg Duration</th>
                <th>Request Count</th>
              </tr>
            </thead>
            <tbody>
              {metrics.slow_endpoints.map((ep) => (
                <tr key={ep.endpoint} className="api-metrics-slow-row">
                  <td className="api-metrics-endpoint">{ep.endpoint}</td>
                  <td className="api-metrics-duration">
                    {ep.avg_duration !== undefined
                      ? formatDurationSeconds(ep.avg_duration)
                      : formatDurationMs(ep.avg_ms)}
                  </td>
                  <td>{ep.count ? ep.count.toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Recent Slow Requests */}
      {metrics.recent_slow_requests.length > 0 && (
        <div className="api-metrics-section">
          <h3>Recent Slow Requests (&gt;1s)</h3>
          <table className="api-metrics-table">
            <thead>
              <tr>
                <th>Endpoint</th>
                <th>Duration</th>
                <th>Status</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {metrics.recent_slow_requests.map((req, idx) => (
                <tr key={idx}>
                  <td className="api-metrics-endpoint">{getEndpointLabel(req)}</td>
                  <td className="api-metrics-duration">
                    {req.duration !== undefined
                      ? formatDurationSeconds(req.duration)
                      : formatDurationMs(req.duration_ms)}
                  </td>
                  <td>{getStatusCode(req)}</td>
                  <td>{new Date(req.timestamp).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Recent Errors */}
      {metrics.recent_errors.length > 0 && (
        <div className="api-metrics-section">
          <h3>Recent Errors</h3>
          <table className="api-metrics-table">
            <thead>
              <tr>
                <th>Endpoint</th>
                <th>Status Code</th>
                <th>Duration</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {metrics.recent_errors.map((err, idx) => (
                <tr key={idx} className="api-metrics-error-row">
                  <td className="api-metrics-endpoint">{getEndpointLabel(err)}</td>
                  <td>{getStatusCode(err)}</td>
                  <td className="api-metrics-duration">
                    {err.duration !== undefined
                      ? formatDurationSeconds(err.duration)
                      : formatDurationMs(err.duration_ms)}
                  </td>
                  <td>{new Date(err.timestamp).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
