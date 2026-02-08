import React from 'react';

interface HealthData {
  total_tenants: number;
  total_vms: number;
  running_vms: number;
  total_volumes: number;
  total_networks: number;
  total_hosts: number;
  total_snapshots: number;
  snapshots_last_24h: number;
  volumes_without_snapshots: number;
  metrics_host_count: number;
  metrics_last_update: string | null;
  avg_cpu_utilization: number;
  avg_memory_utilization: number;
  alerts_count: number;
  critical_count: number;
  warnings_count: number;
  timestamp: string;
}

interface Props {
  data: HealthData;
}

export const HealthSummaryCard: React.FC<Props> = ({ data }) => {
  const getStatusIcon = (metric: number, thresholds: { warning: number; critical: number }): string => {
    if (metric >= thresholds.critical) return '🔴';
    if (metric >= thresholds.warning) return '🟡';
    return '🟢';
  };

  const cpuStatus = getStatusIcon(data.avg_cpu_utilization, { warning: 70, critical: 85 });
  const memStatus = getStatusIcon(data.avg_memory_utilization, { warning: 70, critical: 85 });

  return (
    <div className="health-summary-card card">
      <h2>📊 System Health</h2>
      
      <div className="health-grid">
        {/* Tenants */}
        <div className="health-item">
          <div className="health-label">Tenants</div>
          <div className="health-value">{data.total_tenants}</div>
          <div className="health-sublabel">Active</div>
        </div>

        {/* VMs */}
        <div className="health-item">
          <div className="health-label">Virtual Machines</div>
          <div className="health-value">{data.running_vms}/{data.total_vms}</div>
          <div className="health-sublabel">Running/Total</div>
        </div>

        {/* Volumes */}
        <div className="health-item">
          <div className="health-label">Storage Volumes</div>
          <div className="health-value">{data.total_volumes}</div>
          <div className="health-sublabel">Total</div>
        </div>

        {/* Networks */}
        <div className="health-item">
          <div className="health-label">Networks</div>
          <div className="health-value">{data.total_networks}</div>
          <div className="health-sublabel">Total</div>
        </div>
      </div>

      {/* Utilization Metrics */}
      <div className="utilization-section">
        <h3>Resource Utilization (Cluster Average)</h3>
        
        <div className="metric-row">
          <span className="metric-label">{cpuStatus} CPU</span>
          <div className="metric-bar">
            <div
              className="metric-fill cpu-fill"
              style={{ width: `${Math.min(data.avg_cpu_utilization, 100)}%` }}
            />
          </div>
          <span className="metric-value">{data.avg_cpu_utilization}%</span>
        </div>

        <div className="metric-row">
          <span className="metric-label">{memStatus} Memory</span>
          <div className="metric-bar">
            <div
              className="metric-fill memory-fill"
              style={{ width: `${Math.min(data.avg_memory_utilization, 100)}%` }}
            />
          </div>
          <span className="metric-value">{data.avg_memory_utilization}%</span>
        </div>
      </div>

      {/* Alerts Summary */}
      {(data.critical_count > 0 || data.warnings_count > 0) && (
        <div className="alerts-section">
          <h3>⚠️ Alerts</h3>
          {data.critical_count > 0 && (
            <div className="alert-item critical">
              🔴 <strong>{data.critical_count}</strong> Critical
            </div>
          )}
          {data.warnings_count > 0 && (
            <div className="alert-item warning">
              🟡 <strong>{data.warnings_count}</strong> Warnings
            </div>
          )}
        </div>
      )}

      {data.critical_count === 0 && data.warnings_count === 0 && (
        <div className="status-good">
          ✅ All systems nominal
        </div>
      )}

      <div className="insights-section">
        <h3>Operational Highlights</h3>
        <div className="insights-grid">
          <div className="insight-item">
            <div className="insight-label">Hosts</div>
            <div className="insight-value">{data.total_hosts}</div>
          </div>
          <div className="insight-item">
            <div className="insight-label">Snapshots (24h)</div>
            <div className="insight-value">{data.snapshots_last_24h}</div>
          </div>
          <div className="insight-item">
            <div className="insight-label">Volumes Without Snapshots</div>
            <div className="insight-value">{data.volumes_without_snapshots}</div>
          </div>
          <div className="insight-item">
            <div className="insight-label">Metrics Hosts</div>
            <div className="insight-value">{data.metrics_host_count}</div>
          </div>
        </div>
        {data.metrics_last_update && (
          <div className="insight-meta">
            Metrics last updated: {new Date(data.metrics_last_update).toLocaleString()}
          </div>
        )}
      </div>
    </div>
  );
};
