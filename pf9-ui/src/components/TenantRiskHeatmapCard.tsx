import React from 'react';

interface HeatmapTenant {
  tenant_id: string;
  tenant_name: string;
  coverage_percent: number;
  volumes_without_snapshots: number;
  stale_snapshot_volumes: number;
  risk_score: number;
  risk_level: 'low' | 'medium' | 'high';
}

interface HeatmapData {
  tenants: HeatmapTenant[];
  timestamp: string;
}

interface Props {
  data: HeatmapData;
}

const riskColor = (level: HeatmapTenant['risk_level']) => {
  if (level === 'high') return 'rgba(239, 68, 68, 0.18)';
  if (level === 'medium') return 'rgba(245, 158, 11, 0.18)';
  return 'rgba(16, 185, 129, 0.18)';
};

export const TenantRiskHeatmapCard: React.FC<Props> = ({ data }) => {
  return (
    <div className="tenant-heatmap-card card">
      <h2>🧭 Tenant Risk Heatmap</h2>

      <div className="tenant-heatmap-grid">
        {data.tenants.length === 0 ? (
          <div className="empty-state">No risk data available.</div>
        ) : (
          data.tenants.map((tenant) => (
            <div
              key={tenant.tenant_id}
              className="tenant-heatmap-tile"
              style={{ background: riskColor(tenant.risk_level) }}
            >
              <div className="tenant-title">{tenant.tenant_name}</div>
              <div className="tenant-risk">Risk {tenant.risk_score}</div>
              <div className="tenant-meta">
                Coverage {tenant.coverage_percent}% • No Snap {tenant.volumes_without_snapshots} • Stale {tenant.stale_snapshot_volumes}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
