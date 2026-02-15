import React, { useState, useEffect } from 'react';
import '../styles/SystemLogsTab.css';
import { API_BASE } from '../config';

interface LogEntry {
  timestamp?: string;
  level?: string;
  logger?: string;
  message?: string;
  context?: Record<string, any>;
  exception?: string;
  stack_trace?: string;
  raw?: string;
  source_file?: string;
}

interface LogsResponse {
  logs: LogEntry[];
  total: number;
  log_file: string;
  available_files?: string[];
  read_errors?: { file: string; error: string }[];
  timestamp: string;
}

export const SystemLogsTab: React.FC = () => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [logFile, setLogFile] = useState<string>('');
  const [availableFiles, setAvailableFiles] = useState<string[]>([]);
  const [logFileFilter, setLogFileFilter] = useState<string>('all');
  const [readErrors, setReadErrors] = useState<{ file: string; error: string }[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [filter, setFilter] = useState<{ level?: string; source?: string }>({});
  const [limit, setLimit] = useState(100);

  useEffect(() => {
    const fetchLogs = async () => {
      try {
        const token = localStorage.getItem('auth_token');
        const params = new URLSearchParams();
        params.append('limit', limit.toString());
        if (filter.level) params.append('level', filter.level);
        if (filter.source) params.append('source', filter.source);
        if (logFileFilter) params.append('log_file', logFileFilter);

        const response = await fetch(`${API_BASE}/api/logs?${params}`, {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });

        if (!response.ok) {
          if (response.status === 403) {
            throw new Error('Access denied. Only admins can view system logs.');
          }
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data: LogsResponse = await response.json();
        setLogs(data.logs);
        setLogFile(data.log_file);
        setAvailableFiles(data.available_files || []);
        setReadErrors(data.read_errors || []);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch logs');
      } finally {
        setLoading(false);
      }
    };

    fetchLogs();

    if (autoRefresh) {
      const interval = setInterval(fetchLogs, 5000); // Refresh every 5 seconds
      return () => clearInterval(interval);
    }
  }, [autoRefresh, filter, limit, logFileFilter]);

  const handleFilterChange = (key: string, value: string) => {
    setFilter((prev) => ({
      ...prev,
      [key]: value || undefined,
    }));
  };

  const logLevelColor = (level?: string) => {
    switch (level?.toUpperCase()) {
      case 'DEBUG':
        return '#888';
      case 'INFO':
        return '#0066cc';
      case 'WARNING':
        return '#ff9900';
      case 'ERROR':
        return '#cc0000';
      case 'CRITICAL':
        return '#990000';
      default:
        return '#333';
    }
  };

  const getUniqueLevels = () => {
    const levels = new Set<string>();
    logs.forEach((log) => {
      if (log.level) levels.add(log.level);
    });
    return Array.from(levels).sort();
  };

  const getUniqueSources = () => {
    const sources = new Set<string>();
    logs.forEach((log) => {
      if (log.logger) sources.add(log.logger);
    });
    return Array.from(sources).sort();
  };

  if (loading) {
    return <div className="system-logs-container">Loading logs...</div>;
  }

  if (error) {
    return (
      <div className="system-logs-container">
        <div className="system-logs-error">
          <strong>Error:</strong> {error}
        </div>
      </div>
    );
  }

  return (
    <div className="system-logs-container">
      <div className="system-logs-header">
        <h2>System Logs</h2>
        <p className="system-logs-log-file">Log File: {logFile}</p>
      </div>

      {/* Controls */}
      <div className="system-logs-controls">
        <div className="system-logs-control-group">
          <label>
            Limit:
            <input
              type="number"
              min="1"
              max="1000"
              value={limit}
              onChange={(e) => setLimit(Math.max(1, Math.min(1000, parseInt(e.target.value) || 100)))}
              className="system-logs-number-input"
            />
          </label>
        </div>

        <div className="system-logs-control-group">
          <label>
            Level:
            <select
              value={filter.level || ''}
              onChange={(e) => handleFilterChange('level', e.target.value)}
              className="system-logs-select"
            >
              <option value="">All Levels</option>
              {getUniqueLevels().map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="system-logs-control-group">
          <label>
            Source:
            <select
              value={filter.source || ''}
              onChange={(e) => handleFilterChange('source', e.target.value)}
              className="system-logs-select"
            >
              <option value="">All Sources</option>
              {getUniqueSources().map((source) => (
                <option key={source} value={source}>
                  {source}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="system-logs-control-group">
          <label>
            Log File:
            <select
              value={logFileFilter}
              onChange={(e) => setLogFileFilter(e.target.value)}
              className="system-logs-select"
            >
              <option value="all">All</option>
              {availableFiles.map((file) => (
                <option key={file} value={file}>
                  {file}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="system-logs-refresh-label">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
          />
          Auto-refresh (5s)
        </label>
      </div>

      {readErrors.length > 0 && (
        <div className="system-logs-error">
          <strong>Log read issues:</strong>
          <ul>
            {readErrors.map((err) => (
              <li key={err.file}>
                {err.file}: {err.error}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Logs Table */}
      <div className="system-logs-logs-container">
        <table className="system-logs-table">
          <thead>
            <tr>
              <th className="system-logs-timestamp">Timestamp</th>
              <th className="system-logs-level">Level</th>
              <th className="system-logs-source">Source</th>
              <th className="system-logs-file">File</th>
              <th className="system-logs-message">Message</th>
            </tr>
          </thead>
          <tbody>
            {logs.length > 0 ? (
              logs.map((log, idx) => (
                <tr key={idx} className="system-logs-log-row">
                  <td className="system-logs-timestamp">
                    {log.timestamp
                      ? new Date(log.timestamp).toLocaleString()
                      : 'N/A'}
                  </td>
                  <td className="system-logs-level">
                    <span
                      className="system-logs-badge"
                      style={{ color: logLevelColor(log.level) }}
                    >
                      {log.level || 'INFO'}
                    </span>
                  </td>
                  <td className="system-logs-source">{log.logger || 'system'}</td>
                  <td className="system-logs-file">{log.source_file || 'pf9_api'}</td>
                  <td className="system-logs-message">
                    <div>
                      <strong>{log.message || log.raw || 'N/A'}</strong>

                      {log.context && Object.keys(log.context).length > 0 && (
                        <div className="system-logs-inline-context">
                          {log.context.method && log.context.path && (
                            <span className="system-logs-chip">
                              {log.context.method} {log.context.path}
                            </span>
                          )}
                          {typeof log.context.status_code !== 'undefined' && (
                            <span className="system-logs-chip">
                              status {log.context.status_code}
                            </span>
                          )}
                          {typeof log.context.duration_ms !== 'undefined' && (
                            <span className="system-logs-chip">
                              {log.context.duration_ms}ms
                            </span>
                          )}
                          {log.context.user && (
                            <span className="system-logs-chip">
                              user {log.context.user}
                            </span>
                          )}
                          {log.context.ip_address && (
                            <span className="system-logs-chip">
                              ip {log.context.ip_address}
                            </span>
                          )}
                          {log.context.request_id && (
                            <span className="system-logs-chip">
                              req {log.context.request_id.slice(0, 8)}
                            </span>
                          )}
                        </div>
                      )}

                      {log.context && Object.keys(log.context).length > 0 && (
                        <details className="system-logs-details">
                          <summary>Context</summary>
                          <pre className="system-logs-context-pre">
                            {JSON.stringify(log.context, null, 2)}
                          </pre>
                        </details>
                      )}

                      {log.exception && (
                        <details className="system-logs-details">
                          <summary>Exception</summary>
                          <div className="system-logs-exception">{log.exception}</div>
                          {log.stack_trace && (
                            <pre className="system-logs-stack-trace">{log.stack_trace}</pre>
                          )}
                        </details>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={4} className="system-logs-no-logs">
                  No logs found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="system-logs-footer">
        <p>Showing {logs.length} logs</p>
      </div>
    </div>
  );
};
