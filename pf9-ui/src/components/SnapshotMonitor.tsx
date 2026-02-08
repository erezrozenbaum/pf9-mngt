/**
 * Snapshot Monitor Component
 * 
 * Displays snapshot run history, statistics, and logs
 */

import React, { useEffect, useState } from 'react';
import '../styles/SnapshotMonitor.css';

interface SnapshotRun {
  id: number;
  run_type: string;
  started_at: string;
  finished_at?: string;
  status: string;
  total_volumes: number;
  snapshots_created: number;
  snapshots_deleted: number;
  snapshots_failed: number;
  volumes_skipped: number;
  dry_run: boolean;
  triggered_by?: string;
  trigger_source: string;
  execution_host?: string;
  error_summary?: string;
}

interface SnapshotRunsResponse {
  page: number;
  page_size: number;
  total: number;
  items: SnapshotRun[];
}

const SnapshotMonitor: React.FC = () => {
  const [runs, setRuns] = useState<SnapshotRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [pageSize] = useState(20);
  
  // Filters
  const [runType, setRunType] = useState('');
  const [status, setStatus] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  
  // Expanded row state
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const token = localStorage.getItem('auth_token');

  const loadRuns = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set('page', String(page));
      params.set('page_size', String(pageSize));
      if (runType) params.set('run_type', runType);
      if (status) params.set('status', status);
      if (startDate) params.set('start_date', startDate);
      if (endDate) params.set('end_date', endDate);

      const res = await fetch(`/api/snapshot-runs?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) throw new Error('Failed to load snapshot runs');
      const data: SnapshotRunsResponse = await res.json();
      setRuns(data.items || []);
      setTotalPages(Math.ceil(data.total / pageSize));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load snapshot runs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRuns();
  }, [page, runType, status, startDate, endDate]);

  const toggleRow = (id: number) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedRows(newExpanded);
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  const getDuration = (run: SnapshotRun) => {
    if (!run.finished_at) {
      if (run.status?.toLowerCase() === 'pending') return 'Pending...';
      if (run.status?.toLowerCase() === 'queued') return 'Queued...';
      return 'Running...';
    }
    const start = new Date(run.started_at).getTime();
    const end = new Date(run.finished_at).getTime();
    const seconds = Math.floor((end - start) / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
  };

  const getStatusClass = (status: string) => {
    switch (status.toLowerCase()) {
      case 'success':
      case 'completed':
        return 'status-success';
      case 'partial':
        return 'status-warning';
      case 'failed':
      case 'error':
        return 'status-error';
      case 'running':
        return 'status-running';
      case 'skipped':
        return 'status-skipped';
      case 'pending':
      case 'queued':
        return 'status-pending';
      default:
        return '';
    }
  };

  const resetFilters = () => {
    setRunType('');
    setStatus('');
    setStartDate('');
    setEndDate('');
    setPage(1);
  };

  return (
    <div className="snapshot-monitor">
      <div className="monitor-header">
        <h2>Snapshot Run Monitor</h2>
        <button onClick={loadRuns} className="btn-refresh">
          🔄 Refresh
        </button>
      </div>

      <div className="monitor-filters">
        <div className="filter-group">
          <label>
            Run Type
            <select value={runType} onChange={e => { setRunType(e.target.value); setPage(1); }}>
              <option value="">All Types</option>
              <option value="daily_5">daily_5</option>
              <option value="monthly_1st">monthly_1st</option>
              <option value="monthly_15th">monthly_15th</option>
            </select>
          </label>

          <label>
            Status
            <select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}>
              <option value="">All Status</option>
              <option value="success">Success</option>
              <option value="partial">Partial</option>
              <option value="failed">Failed</option>
              <option value="running">Running</option>
              <option value="pending">Pending</option>
              <option value="skipped">Skipped</option>
            </select>
          </label>

          <label>
            Start Date
            <input
              type="datetime-local"
              value={startDate}
              onChange={e => { setStartDate(e.target.value); setPage(1); }}
            />
          </label>

          <label>
            End Date
            <input
              type="datetime-local"
              value={endDate}
              onChange={e => { setEndDate(e.target.value); setPage(1); }}
            />
          </label>

          <button onClick={resetFilters} className="btn-reset">
            Clear Filters
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="loader">Loading...</div>
      ) : (
        <>
          <div className="table-container">
            <table className="monitor-table">
              <thead>
                <tr>
                  <th></th>
                  <th>Run ID</th>
                  <th>Type</th>
                  <th>Started</th>
                  <th>Duration</th>
                  <th>Status</th>
                  <th>Volumes</th>
                  <th>Created</th>
                  <th>Deleted</th>
                  <th>Failed</th>
                  <th>Skipped</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(run => (
                  <React.Fragment key={run.id}>
                    <tr className={getStatusClass(run.status)} onClick={() => toggleRow(run.id)}>
                      <td className="expand-cell">
                        {expandedRows.has(run.id) ? '▼' : '▶'}
                      </td>
                      <td>{run.id}</td>
                      <td>
                        {run.run_type}
                        {run.dry_run && <span className="badge-dry-run">DRY RUN</span>}
                      </td>
                      <td>{formatDate(run.started_at)}</td>
                      <td>{getDuration(run)}</td>
                      <td>
                        <span className={`status-badge ${getStatusClass(run.status)}`}>
                          {run.status}
                        </span>
                      </td>
                      <td>{run.total_volumes}</td>
                      <td className="success-text">{run.snapshots_created}</td>
                      <td className="warning-text">{run.snapshots_deleted}</td>
                      <td className="error-text">{run.snapshots_failed}</td>
                      <td className="skipped-text">{run.volumes_skipped}</td>
                    </tr>
                    {expandedRows.has(run.id) && (
                      <tr className="expanded-row">
                        <td colSpan={11}>
                          <div className="run-details">
                            <div className="detail-section">
                              <h4>Run Details</h4>
                              <div className="detail-grid">
                                <div className="detail-item">
                                  <strong>Finished:</strong> {formatDate(run.finished_at)}
                                </div>
                                <div className="detail-item">
                                  <strong>Triggered By:</strong> {run.triggered_by || 'System'}
                                </div>
                                <div className="detail-item">
                                  <strong>Trigger Source:</strong> {run.trigger_source}
                                </div>
                                <div className="detail-item">
                                  <strong>Execution Host:</strong> {run.execution_host || 'N/A'}
                                </div>
                              </div>
                            </div>
                            {run.error_summary && (
                              <div className="detail-section">
                                <h4>Error Summary</h4>
                                <pre className="error-summary">{run.error_summary}</pre>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="btn-page"
            >
              ← Previous
            </button>
            <span className="page-info">
              Page {page} of {totalPages} ({runs.length} runs)
            </span>
            <button
              onClick={() => setPage(p => p + 1)}
              disabled={page >= totalPages}
              className="btn-page"
            >
              Next →
            </button>
          </div>
        </>
      )}
    </div>
  );
};

export default SnapshotMonitor;
