import React from 'react';

interface HotspotVm {
  vm_id: string;
  vm_name: string;
  vm_ip?: string | null;
  project_name?: string | null;
  domain?: string | null;
  host?: string | null;
  cpu_usage_percent?: number | null;
  memory_usage_percent?: number | null;
  memory_usage_mb?: number | null;
  memory_total_mb?: number | null;
  storage_usage_percent?: number | null;
  storage_used_gb?: number | null;
  storage_total_gb?: number | null;
  timestamp?: string | null;
}

interface VmHotspotsData {
  vms: HotspotVm[];
  sort_by: string;
  timestamp: string;
}

interface Props {
  cpuData: VmHotspotsData;
  memoryData: VmHotspotsData;
  storageData: VmHotspotsData;
}

const renderUsage = (value?: number | null) => (value == null ? 'N/A' : `${value}%`);

const formatCapacityPair = (
  used?: number | null,
  total?: number | null,
  options?: { sourceUnit: 'gb' | 'mb'; decimals?: number }
) => {
  if (used == null || total == null || total === 0) {
    return null;
  }

  const sourceUnit = options?.sourceUnit ?? 'gb';
  const decimals = options?.decimals ?? 1;

  const usedValue = Number(used);
  const totalValue = Number(total);
  if (!Number.isFinite(usedValue) || !Number.isFinite(totalValue) || totalValue === 0) {
    return null;
  }

  const divisor = sourceUnit === 'mb' ? 1024 : 1;
  const usedGb = usedValue / divisor;
  const totalGb = totalValue / divisor;

  const format = (value: number) => {
    const fixed = value.toFixed(decimals);
    return decimals > 0 ? fixed.replace(/\.0+$/, '.0') : fixed;
  };

  return `${format(usedGb)} GB / ${format(totalGb)} GB`;
};

export const VMHotspotsCard: React.FC<Props> = ({ cpuData, memoryData, storageData }) => {
  return (
    <div className="vm-hotspots-card card">
      <h2>🔥 VM Hotspots</h2>

      <div className="vm-hotspots-grid">
        <div className="vm-hotspots-section">
          <h3>CPU</h3>
          {cpuData.vms.length === 0 ? (
            <div className="empty-state">No CPU metrics available.</div>
          ) : (
            <ul>
              {cpuData.vms.map((vm) => (
                <li key={vm.vm_id}>
                  <div className="vm-primary">
                    <div className="vm-identity">
                      <span className="vm-name">{vm.vm_name}</span>
                      <span className="vm-meta">{vm.project_name ?? 'Unknown'}</span>
                    </div>
                    <span className="vm-metric">{renderUsage(vm.cpu_usage_percent)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="vm-hotspots-section">
          <h3>Memory</h3>
          {memoryData.vms.length === 0 ? (
            <div className="empty-state">No memory metrics available.</div>
          ) : (
            <ul>
              {memoryData.vms.map((vm) => {
                const memoryAllocation = formatCapacityPair(vm.memory_usage_mb, vm.memory_total_mb, {
                  sourceUnit: 'mb',
                });

                return (
                  <li key={vm.vm_id}>
                    <div className="vm-primary">
                      <div className="vm-identity">
                        <span className="vm-name">{vm.vm_name}</span>
                        <span className="vm-meta">{vm.project_name ?? 'Unknown'}</span>
                      </div>
                      <span className="vm-metric">{renderUsage(vm.memory_usage_percent)}</span>
                    </div>
                    {memoryAllocation && (
                      <div className="vm-submetric">Usage: {memoryAllocation}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="vm-hotspots-section">
          <h3>Storage</h3>
          {storageData.vms.length === 0 ? (
            <div className="empty-state">No storage metrics available.</div>
          ) : (
            <ul>
              {storageData.vms.map((vm) => {
                const storageAllocation = formatCapacityPair(vm.storage_used_gb, vm.storage_total_gb, {
                  sourceUnit: 'gb',
                });

                return (
                  <li key={vm.vm_id}>
                    <div className="vm-primary">
                      <div className="vm-identity">
                        <span className="vm-name">{vm.vm_name}</span>
                        <span className="vm-meta">{vm.project_name ?? 'Unknown'}</span>
                      </div>
                      <span className="vm-metric">{renderUsage(vm.storage_usage_percent)}</span>
                    </div>
                    {storageAllocation && (
                      <div className="vm-submetric">Usage: {storageAllocation}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
};
