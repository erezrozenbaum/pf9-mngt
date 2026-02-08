import React from 'react';

interface Change {
  resource_type: string;
  resource_id: string;
  resource_name: string;
  action: string;
  tenant_name: string | null;
  timestamp: string;
}

interface ActivityData {
  summary: {
    new_vms: number;
    deleted_volumes: number;
    new_users: number;
    total_changes: number;
  };
  changes: Change[];
  hours_lookback: number;
  timestamp: string;
}

interface Props {
  data: ActivityData;
}

const getActivityIcon = (resourceType: string, action: string): string => {
  const iconMap: Record<string, Record<string, string>> = {
    vm: { created: '✨', deleted: '🗑️' },
    volume: { created: '💾', deleted: '🗑️' },
    user: { created: '👤', deleted: '❌' },
    network: { created: '🌐', deleted: '🗑️' },
  };
  return iconMap[resourceType]?.[action] || '📝';
};

const getActivityColor = (action: string): string => {
  return action === 'created' ? '#10b981' : '#ef4444';
};

export const RecentActivityWidget: React.FC<Props> = ({ data }) => {
  const displayChanges = data.changes.slice(0, 10); // Show only first 10

  return (
    <div className="recent-activity-card card">
      <h2>📜 Recent Activity</h2>

      {/* Activity Summary */}
      <div className="activity-summary">
        <div className="summary-item">
          <span className="icon">✨</span>
          <span className="label">{data.summary.new_vms} VMs created</span>
        </div>
        <div className="summary-item">
          <span className="icon">🗑️</span>
          <span className="label">{data.summary.deleted_volumes} volumes deleted</span>
        </div>
        <div className="summary-item">
          <span className="icon">👤</span>
          <span className="label">{data.summary.new_users} new users</span>
        </div>
      </div>

      {/* Activity Timeline */}
      {displayChanges.length === 0 ? (
        <div className="empty-state">
          <p>No changes in the last {data.hours_lookback} hours</p>
        </div>
      ) : (
        <div className="activity-timeline">
          {displayChanges.map((change, idx) => (
            <div key={idx} className="activity-item">
              <div className="activity-icon">
                <span>{getActivityIcon(change.resource_type, change.action)}</span>
              </div>
              <div className="activity-content">
                <div className="activity-main">
                  <span className="resource-type">{change.resource_type}</span>
                  <span className="action-badge" style={{ color: getActivityColor(change.action) }}>
                    {change.action.toUpperCase()}
                  </span>
                </div>
                <div className="activity-name">{change.resource_name}</div>
                {change.tenant_name && (
                  <div className="activity-tenant">in {change.tenant_name}</div>
                )}
              </div>
              <div className="activity-time">
                {change.timestamp
                  ? new Date(change.timestamp).toLocaleTimeString([], {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })
                  : 'Unknown'}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="activity-footer">
        <p>Showing last {data.hours_lookback} hours. Total: {data.summary.total_changes} changes</p>
      </div>
    </div>
  );
};
