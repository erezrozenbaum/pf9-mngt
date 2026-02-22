import React, { useState } from 'react';

interface TenantCompliance {
  tenant_id: string;
  tenant_name: string;
  compliant_count: number;
  warning_count: number;
  critical_count: number;
  total_volumes: number;
  compliance_percentage: number;
  warnings: Array<{
    volume_id: string;
    volume_name: string;
    warning: string;
  }>;
}

interface SLAData {
  compliance_data: TenantCompliance[];
  summary: {
    total_volumes: number;
    total_compliant: number;
    total_warning: number;
    total_critical: number;
    overall_compliance_percentage: number;
  };
  timestamp: string;
}

interface Props {
  data: SLAData;
  onNavigate?: (tab: string) => void;
}

export const SnapshotSLAWidget: React.FC<Props> = ({ data, onNavigate }) => {
  const [expandedTenant, setExpandedTenant] = useState<string | null>(null);

  const getComplianceColor = (percentage: number): string => {
    if (percentage === 100) return '#10b981'; // green
    if (percentage >= 90) return '#f59e0b'; // amber
    return '#ef4444'; // red
  };

  const getComplianceStatus = (percentage: number): string => {
    if (percentage === 100) return '✅ Compliant';
    if (percentage >= 90) return '⚠️ Warning';
    return '❌ Critical';
  };

  return (
    <div className="snapshot-sla-widget card">
      <h2>📸 Snapshot SLA Compliance</h2>

      {/* Overall Summary */}
      <div className="sla-summary">
        <div className="summary-stat">
          <div className="summary-label">Overall Compliance</div>
          <div
            className="summary-percentage"
            style={{ color: getComplianceColor(data.summary.overall_compliance_percentage) }}
          >
            {data.summary.overall_compliance_percentage}%
          </div>
        </div>
        <div className="summary-stat">
          <div className="summary-label">Compliant</div>
          <div className="summary-value" style={{ color: '#10b981' }}>
            {data.summary.total_compliant}/{data.summary.total_volumes}
          </div>
        </div>
        <div className="summary-stat">
          <div className="summary-label">Warnings</div>
          <div className="summary-value" style={{ color: '#f59e0b' }}>
            {data.summary.total_warning}
          </div>
        </div>
        <div className="summary-stat">
          <div className="summary-label">Critical</div>
          <div className="summary-value" style={{ color: '#ef4444' }}>
            {data.summary.total_critical}
          </div>
        </div>
      </div>

      {/* Tenant Breakdown */}
      <div className="sla-tenant-list">
        <h3>By Tenant</h3>
        <table className="sla-table">
          <thead>
            <tr>
              <th>Tenant</th>
              <th>Volumes</th>
              <th>Status</th>
              <th>Compliance</th>
            </tr>
          </thead>
          <tbody>
            {data.compliance_data.map((tenant) => (
              <React.Fragment key={tenant.tenant_id}>
                <tr
                  className={`sla-row ${
                    tenant.compliance_percentage === 100
                      ? 'compliant'
                      : tenant.compliance_percentage >= 90
                        ? 'warning'
                        : 'critical'
                  }`}
                  onClick={() =>
                    setExpandedTenant(
                      expandedTenant === tenant.tenant_id ? null : tenant.tenant_id
                    )
                  }
                  style={{ cursor: 'pointer' }}
                >
                  <td className="tenant-name">
                    <span className="expand-icon">
                      {expandedTenant === tenant.tenant_id ? '▼' : '▶'}
                    </span>
                    {tenant.tenant_name}
                  </td>
                  <td>{tenant.total_volumes}</td>
                  <td>{getComplianceStatus(tenant.compliance_percentage)}</td>
                  <td>
                    <div className="compliance-bar">
                      <div
                        className="compliance-fill"
                        style={{
                          width: `${tenant.compliance_percentage}%`,
                          backgroundColor: getComplianceColor(tenant.compliance_percentage),
                        }}
                      />
                    </div>
                    <span className="percentage-text">{tenant.compliance_percentage}%</span>
                  </td>
                </tr>

                {/* Expanded Details */}
                {expandedTenant === tenant.tenant_id && tenant.warnings.length > 0 && (
                  <tr className="sla-details">
                    <td colSpan={4}>
                      <div className="warning-list">
                        <h4>⚠️ Compliance Issues:</h4>
                        {tenant.warnings.map((warning, idx) => (
                          <div key={idx} className="warning-item">
                            <span className="volume-name">{warning.volume_name}</span>
                            <span className="warning-text">{warning.warning}</span>
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="sla-tips">
        <p>💡 Click a tenant row to view compliance details</p>
        {onNavigate && (
          <button
            className="sla-configure-link"
            onClick={() => onNavigate('snapshot-policies')}
          >
            ⚙ Configure Snapshot Policies &amp; Retention
          </button>
        )}
      </div>
    </div>
  );
};
