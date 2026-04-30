import React from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts';

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
  isDark?: boolean; // retained for backward compat, unused
}

const getBarFill = (value: number | null) => {
  if (value === null) return 'var(--color-border)';
  if (value > 85) return 'var(--color-error)';
  if (value > 70) return 'var(--color-warning)';
  return 'var(--color-success)';
};

export const HostUtilizationCard: React.FC<Props> = ({ data }) => {

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
        <ResponsiveContainer width="100%" height={data.hosts.length * 36 + 32}>
          <BarChart
            data={data.hosts.map(h => ({
              name: (h.host_display_name ?? h.hostname).slice(0, 20),
              CPU: h.cpu_utilization_percent ?? 0,
              Memory: h.memory_utilization_percent ?? 0,
              isCritical: h.is_critical,
            }))}
            layout="vertical"
            margin={{ top: 4, right: 40, left: 8, bottom: 0 }}
            barSize={6}
            barGap={2}
          >
            <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: 'var(--color-text-secondary)' }} tickFormatter={v => `${v}%`} />
            <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: 'var(--color-text-secondary)' }} width={130} />
            <Tooltip
              contentStyle={{ background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)', borderRadius: 6, fontSize: 11 }}
              formatter={(val, name) => [`${Number(val)}%`, String(name)]}  
            />
            <Legend iconSize={8} wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="CPU" radius={[0, 4, 4, 0]}>
              {data.hosts.map((host, idx) => (
                <Cell key={idx} fill={getBarFill(host.cpu_utilization_percent)} />
              ))}
            </Bar>
            <Bar dataKey="Memory" radius={[0, 4, 4, 0]}>
              {data.hosts.map((host, idx) => (
                <Cell key={idx} fill={getBarFill(host.memory_utilization_percent)} opacity={0.7} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}

      <div className="host-legend">
        <span className="legend-item">
          <span className="status-indicator" style={{ backgroundColor: 'var(--color-success)' }} />
          Normal (&lt;70%)
        </span>
        <span className="legend-item">
          <span className="status-indicator" style={{ backgroundColor: 'var(--color-warning)' }} />
          Warning (70–85%)
        </span>
        <span className="legend-item">
          <span className="status-indicator" style={{ backgroundColor: 'var(--color-error)' }} />
          Critical (&gt;85%)
        </span>
      </div>
    </div>
  );
};
