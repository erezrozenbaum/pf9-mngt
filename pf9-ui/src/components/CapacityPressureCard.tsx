import React from 'react';

interface TopTenant {
  tenant_id: string;
  tenant_name: string;
  vm_count?: number;
  volume_count?: number;
  volume_gb?: number;
}

interface CapacityData {
  summary: {
    active_vms: number;
    total_vms: number;
  };
  top_by_vms: TopTenant[];
  top_by_storage: TopTenant[];
  timestamp: string;
}

interface Props {
  data: CapacityData;
}

export const CapacityPressureCard: React.FC<Props> = ({ data }) => {
  return (
    <div className="capacity-pressure-card card">
      <h2>📈 Capacity Pressure</h2>

      <div className="capacity-summary">
        <div className="capacity-stat">
          <div className="capacity-label">Active VMs</div>
          <div className="capacity-value">{data.summary.active_vms}</div>
        </div>
        <div className="capacity-stat">
          <div className="capacity-label">Total VMs</div>
          <div className="capacity-value">{data.summary.total_vms}</div>
        </div>
      </div>

      <div className="capacity-grid">
        <div className="capacity-table">
          <h3>Top Tenants by VMs</h3>
          {data.top_by_vms.length === 0 ? (
            <div className="empty-state">No VM distribution data.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Tenant</th>
                  <th>VMs</th>
                  <th>Volumes</th>
                </tr>
              </thead>
              <tbody>
                {data.top_by_vms.map((tenant) => (
                  <tr key={tenant.tenant_id}>
                    <td>{tenant.tenant_name}</td>
                    <td>{tenant.vm_count ?? 0}</td>
                    <td>{tenant.volume_count ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="capacity-table">
          <h3>Top Tenants by Storage</h3>
          {data.top_by_storage.length === 0 ? (
            <div className="empty-state">No storage distribution data.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Tenant</th>
                  <th>Volumes</th>
                  <th>GB</th>
                </tr>
              </thead>
              <tbody>
                {data.top_by_storage.map((tenant) => (
                  <tr key={tenant.tenant_id}>
                    <td>{tenant.tenant_name}</td>
                    <td>{tenant.volume_count ?? 0}</td>
                    <td>{tenant.volume_gb ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};
