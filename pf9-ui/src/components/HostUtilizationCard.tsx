import React from 'react';

interface Host {
  hostname: string;
  host_display_name?: string;
  cpu_utilization_percent: number | null;
  memory_utilization_percent: number | null;
  vm_count: number;
  is_critical: boolean;
  capacity_vcpus?: number | null;
  capacity_memory_mb?: number | null;
}

interface HostsData {
  hosts: Host[];
  sort_by: string;
  timestamp: string;
  metrics_status?: {
    source: "metrics_cache" | "inventory";
    host_count: number;
    last_updated: string | null;
  };
}

interface Props {
  data: HostsData;
}

export const HostUtilizationCard: React.FC<Props> = ({ data }) => {
  const getUtilizationColor = (percent: number | null): string => {
    if (percent === null) return '#94a3b8';
    if (percent > 85) return '#f87171'; // red (softened)
    if (percent > 70) return '#f59e0b'; // amber
    return '#10b981'; // green
  };

  return (
    <div className="host-utilization-card card">
      <h2>🖥️ Top Hosts by Usage</h2>

      {data.metrics_status && (
        <div className="metrics-status">
          <span className="status-label">Source:</span>
          <span className="status-value">
            {data.metrics_status.source === "metrics_cache" ? "Monitoring" : "Inventory"}
          </span>
          <span className="status-divider">•</span>
          <span className="status-label">Hosts:</span>
          <span className="status-value">{data.metrics_status.host_count}</span>
          {data.metrics_status.last_updated && (
            <>
              <span className="status-divider">•</span>
              <span className="status-label">Updated:</span>
              <span className="status-value">
                {new Date(data.metrics_status.last_updated).toLocaleString()}
              </span>
            </>
          )}
        </div>
      )}

      {data.hosts.length === 0 ? (
        <div className="empty-state">
          <p>No host metrics available. Ensure monitoring service is running.</p>
        </div>
      ) : (
        <div className="hosts-list">
          {data.hosts.map((host, idx) => (
            <div
              key={host.hostname}
              className={`host-item ${host.is_critical ? 'critical' : ''}`}
            >
              <div className="host-header">
                <div className="host-rank">#{idx + 1}</div>
                <div className="host-name">
                  {host.host_display_name ?? host.hostname}
                  {host.host_display_name && host.host_display_name !== host.hostname && (
                    <span className="host-hostname">{host.hostname}</span>
                  )}
                  {host.is_critical && <span className="critical-badge">⚠️ HIGH</span>}
                </div>
                <div className="host-vm-count">
                  {host.vm_count} VMs
                  {host.capacity_vcpus != null && host.capacity_memory_mb != null && (
                    <span className="host-capacity">
                      • {host.capacity_vcpus} vCPU • {Math.round(host.capacity_memory_mb / 1024)} GB RAM
                    </span>
                  )}
                </div>
              </div>

              <div className="host-metrics">
                <div className="metric-item">
                  <div className="metric-label">CPU</div>
                  <div className="metric-bar">
                    <div
                      className="metric-fill"
                      style={{
                          width: `${Math.min(host.cpu_utilization_percent ?? 0, 100)}%`,
                          backgroundColor: getUtilizationColor(host.cpu_utilization_percent),
                      }}
                    />
                  </div>
                  <span className="metric-percent">
                    {host.cpu_utilization_percent === null ? 'N/A' : `${host.cpu_utilization_percent}%`}
                  </span>
                </div>

                <div className="metric-item">
                  <div className="metric-label">Memory</div>
                  <div className="metric-bar">
                    <div
                      className="metric-fill"
                      style={{
                          width: `${Math.min(host.memory_utilization_percent ?? 0, 100)}%`,
                          backgroundColor: getUtilizationColor(host.memory_utilization_percent),
                      }}
                    />
                  </div>
                  <span className="metric-percent">
                    {host.memory_utilization_percent === null ? 'N/A' : `${host.memory_utilization_percent}%`}
                  </span>
                </div>
              </div>

              {host.is_critical && (
                <div className="critical-warning">
                  ⚠️ Resource utilization is high. Consider workload rebalancing.
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="host-legend">
        <span className="legend-item">
          <span className="status-indicator" style={{ backgroundColor: '#10b981' }} />
          Normal (&lt;70%)
        </span>
        <span className="legend-item">
          <span className="status-indicator" style={{ backgroundColor: '#f59e0b' }} />
          Warning (70-85%)
        </span>
        <span className="legend-item">
          <span className="status-indicator" style={{ backgroundColor: '#f87171' }} />
          Critical (&gt;85%)
        </span>
      </div>
    </div>
  );
};
