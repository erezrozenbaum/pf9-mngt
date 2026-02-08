import React from 'react';

interface DriftTenant {
  tenant_id: string;
  tenant_name: string;
  total_volumes: number;
  volumes_without_snapshots: number;
  stale_snapshot_volumes: number;
  warning_volumes: number;
}

interface ComplianceDriftData {
  summary: {
    total_warning_volumes: number;
    total_stale_volumes: number;
    total_volumes_without_snapshots: number;
  };
  tenants: DriftTenant[];
  timestamp: string;
}

interface Props {
  data: ComplianceDriftData;
}

export const ComplianceDriftCard: React.FC<Props> = ({ data }) => {
  return (
    <div className="compliance-drift-card card">
      <h2>🧪 Compliance Drift Signals</h2>

      <div className="drift-summary">
        <div className="drift-stat">
          <div className="drift-label">Warning Volumes</div>
          <div className="drift-value">{data.summary.total_warning_volumes}</div>
        </div>
        <div className="drift-stat">
          <div className="drift-label">Stale Volumes</div>
          <div className="drift-value">{data.summary.total_stale_volumes}</div>
        </div>
        <div className="drift-stat">
          <div className="drift-label">No Snapshots</div>
          <div className="drift-value">{data.summary.total_volumes_without_snapshots}</div>
        </div>
      </div>

      <table className="drift-table">
        <thead>
          <tr>
            <th>Tenant</th>
            <th>Total Volumes</th>
            <th>No Snapshots</th>
            <th>Stale</th>
            <th>Warnings</th>
          </tr>
        </thead>
        <tbody>
          {data.tenants.map((tenant) => (
            <tr key={tenant.tenant_id}>
              <td>{tenant.tenant_name}</td>
              <td>{tenant.total_volumes}</td>
              <td>{tenant.volumes_without_snapshots}</td>
              <td>{tenant.stale_snapshot_volumes}</td>
              <td>{tenant.warning_volumes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
