import React from 'react';

interface CoverageSummary {
  total_volumes: number;
  total_snapshots: number;
  snapshots_last_24h: number;
  volumes_without_snapshots: number;
  volumes_with_stale_snapshots: number;
  coverage_percent: number;
  snapshot_density: number;
}

interface LowestCoverageTenant {
  tenant_name: string;
  total_volumes: number;
  covered_volumes?: number;
  snapshot_count: number;
  snapshot_density?: number;
  coverage_percent: number;
}

interface CoverageData {
  summary: CoverageSummary;
  lowest_coverage_tenants: LowestCoverageTenant[];
  timestamp: string;
}

interface Props {
  data: CoverageData;
}

export const CoverageRiskCard: React.FC<Props> = ({ data }) => {
  return (
    <div className="coverage-risk-card card">
      <h2>🛡️ Snapshot Coverage Risks</h2>

      <div className="coverage-summary">
        <div className="coverage-stat">
          <div className="coverage-label">Coverage</div>
          <div className="coverage-value">{data.summary.coverage_percent}%</div>
        </div>
        <div className="coverage-stat">
          <div className="coverage-label">Snapshots / Volume</div>
          <div className="coverage-value">{data.summary.snapshot_density}</div>
        </div>
        <div className="coverage-stat">
          <div className="coverage-label">Snapshots (24h)</div>
          <div className="coverage-value">{data.summary.snapshots_last_24h}</div>
        </div>
        <div className="coverage-stat">
          <div className="coverage-label">No Snapshots</div>
          <div className="coverage-value">{data.summary.volumes_without_snapshots}</div>
        </div>
        <div className="coverage-stat">
          <div className="coverage-label">Stale (7d)</div>
          <div className="coverage-value">{data.summary.volumes_with_stale_snapshots}</div>
        </div>
      </div>

      <div className="coverage-table">
        <h3>Lowest Coverage Tenants</h3>
        {data.lowest_coverage_tenants.length === 0 ? (
          <div className="empty-state">No tenant coverage data available.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Tenant</th>
                <th>Volumes</th>
                <th>Covered</th>
                <th>Snapshots</th>
                <th>Snap/Vol</th>
                <th>Coverage</th>
              </tr>
            </thead>
            <tbody>
              {data.lowest_coverage_tenants.map((tenant) => (
                <tr key={tenant.tenant_name}>
                  <td>{tenant.tenant_name}</td>
                  <td>{tenant.total_volumes}</td>
                  <td>{tenant.covered_volumes ?? 0}</td>
                  <td>{tenant.snapshot_count}</td>
                  <td>{tenant.snapshot_density ?? 0}</td>
                  <td>{tenant.coverage_percent}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
