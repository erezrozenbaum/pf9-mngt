import React from 'react';
import { AreaChart, Area, ResponsiveContainer, Tooltip } from 'recharts';

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

interface TrendPoint {
  snapshot_date: string;
  total_vms: number;
  running_vms: number;
  total_hosts: number;
  critical_count: number;
}

interface Props {
  data: HealthData;
  trendData?: TrendPoint[];
}

export const HealthSummaryCard: React.FC<Props> = ({ data, trendData = [] }) => {
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

      {/* 7-day trend sparkline */}
      {trendData.length > 1 && (
        <div className="health-trend-sparkline">
          <div className="sparkline-label">Running VMs — 7 day trend</div>
          <ResponsiveContainer width="100%" height={48}>
            <AreaChart data={trendData} margin={{ top: 2, right: 4, left: 4, bottom: 2 }}>
              <defs>
                <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--color-primary)" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="var(--color-primary)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="running_vms"
                stroke="var(--color-primary)"
                strokeWidth={1.5}
                fill="url(#sparkGrad)"
                dot={false}
                isAnimationActive={false}
              />
              <Tooltip
                contentStyle={{ background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)', borderRadius: 6, fontSize: 11 }}
                labelFormatter={(label) => new Date(String(label)).toLocaleDateString()}
                formatter={(val) => [val, 'Running VMs']}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

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
