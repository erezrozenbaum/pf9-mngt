import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../lib/api';
import './GlobalHealthBar.css';

interface HealthSummary {
  total_vms: number;
  running_vms: number;
  total_hosts: number;
  critical_count: number;
  warnings_count: number;
  alerts_count: number;
}

export function GlobalHealthBar() {
  const [data, setData] = useState<HealthSummary | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const result = await apiFetch<HealthSummary>('/api/dashboard/health-summary');
      setData(result);
      setLastUpdate(new Date());
    } catch {
      // Silently fail — bar just shows last known state
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 30_000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  if (!data) return null;

  const isOk = data.critical_count === 0 && data.warnings_count === 0;
  const isCritical = data.critical_count > 0;
  const statusColor = isCritical ? 'var(--color-error)' : isOk ? 'var(--color-success)' : 'var(--color-warning)';
  const statusLabel = isCritical ? 'DEGRADED' : isOk ? 'LIVE' : 'WARN';
  const barClass = `global-health-bar${isCritical ? ' critical-pulse' : ''}`;

  const timeStr = lastUpdate
    ? lastUpdate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  return (
    <div className={barClass}>
      <div className="ghb-status">
        <span className="ghb-dot" style={{ background: statusColor }} />
        <span className="ghb-status-label" style={{ color: statusColor }}>{statusLabel}</span>
      </div>
      <div className="ghb-sep" />
      <div className="ghb-metric">
        <span className="ghb-metric-label">VMs</span>
        <span className="ghb-metric-value">{data.running_vms}<span className="ghb-metric-total">/{data.total_vms}</span></span>
      </div>
      <div className="ghb-sep" />
      <div className="ghb-metric">
        <span className="ghb-metric-label">Hosts</span>
        <span className="ghb-metric-value">{data.total_hosts}</span>
      </div>
      {data.critical_count > 0 && (
        <>
          <div className="ghb-sep" />
          <div className="ghb-metric ghb-metric-critical">
            <span className="ghb-metric-label">Critical</span>
            <span className="ghb-metric-value">{data.critical_count}</span>
          </div>
        </>
      )}
      {data.warnings_count > 0 && (
        <>
          <div className="ghb-sep" />
          <div className="ghb-metric ghb-metric-warn">
            <span className="ghb-metric-label">Warnings</span>
            <span className="ghb-metric-value">{data.warnings_count}</span>
          </div>
        </>
      )}
      <div className="ghb-spacer" />
      {timeStr && (
        <span className="ghb-sync-time">synced {timeStr}</span>
      )}
    </div>
  );
}
