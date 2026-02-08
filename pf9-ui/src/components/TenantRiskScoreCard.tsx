import React from 'react';

interface TenantRisk {
  tenant_id: string;
  tenant_name: string;
  total_volumes: number;
  coverage_percent: number;
  volumes_without_snapshots: number;
  stale_snapshot_volumes: number;
  risk_score: number;
  risk_level: 'low' | 'medium' | 'high';
}

interface RiskData {
  tenants: TenantRisk[];
  timestamp: string;
}

interface Props {
  data: RiskData;
}

const riskColor = (level: TenantRisk['risk_level']) => {
  if (level === 'high') return '#ef4444';
  if (level === 'medium') return '#f59e0b';
  return '#10b981';
};

export const TenantRiskScoreCard: React.FC<Props> = ({ data }) => {
  return (
    <div className="tenant-risk-card card">
      <h2>⚠️ Tenant Risk Scores</h2>

      {data.tenants.length === 0 ? (
        <div className="empty-state">No tenant risk data available.</div>
      ) : (
        <table className="tenant-risk-table">
          <thead>
            <tr>
              <th>Tenant</th>
              <th>Coverage</th>
              <th>No Snapshots</th>
              <th>Stale</th>
              <th>Risk</th>
            </tr>
          </thead>
          <tbody>
            {data.tenants.map((tenant) => (
              <tr key={tenant.tenant_id}>
                <td>{tenant.tenant_name}</td>
                <td>{tenant.coverage_percent}%</td>
                <td>{tenant.volumes_without_snapshots}</td>
                <td>{tenant.stale_snapshot_volumes}</td>
                <td>
                  <span className="risk-badge" style={{ color: riskColor(tenant.risk_level) }}>
                    {tenant.risk_score} ({tenant.risk_level})
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};
