import React from 'react';

interface ChangeComplianceData {
  summary: {
    new_vms: number;
    snapshots_created: number;
    deleted_resources: number;
    new_users: number;
  };
  hours_lookback: number;
  timestamp: string;
}

interface Props {
  data: ChangeComplianceData;
}

export const ChangeComplianceCard: React.FC<Props> = ({ data }) => {
  return (
    <div className="change-compliance-card card">
      <h2>✅ Change & Compliance</h2>

      <div className="change-summary">
        <div className="change-item">
          <div className="change-label">New VMs</div>
          <div className="change-value">{data.summary.new_vms}</div>
        </div>
        <div className="change-item">
          <div className="change-label">Snapshots Created</div>
          <div className="change-value">{data.summary.snapshots_created}</div>
        </div>
        <div className="change-item">
          <div className="change-label">Deleted Resources</div>
          <div className="change-value">{data.summary.deleted_resources}</div>
        </div>
        <div className="change-item">
          <div className="change-label">New Users</div>
          <div className="change-value">{data.summary.new_users}</div>
        </div>
      </div>

      <div className="change-meta">
        Last {data.hours_lookback} hours • Updated {new Date(data.timestamp).toLocaleTimeString()}
      </div>
    </div>
  );
};
