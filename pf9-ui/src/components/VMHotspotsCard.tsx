import React from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

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

const getBarColor = (value: number | null | undefined) => {
  if (value == null) return 'var(--color-border)';
  if (value > 85) return 'var(--color-error)';
  if (value > 70) return 'var(--color-warning)';
  return 'var(--color-primary)';
};

const truncate = (s: string, n: number) => s.length > n ? s.slice(0, n) + '…' : s;

const HotspotChart: React.FC<{ vms: HotspotVm[]; dataKey: 'cpu_usage_percent' | 'memory_usage_percent' | 'storage_usage_percent'; label: string }> = ({ vms, dataKey, label }) => {
  if (vms.length === 0) return <div className="empty-state">No {label.toLowerCase()} metrics available.</div>;
  const chartData = vms.slice(0, 8).map(vm => ({
    name: truncate(vm.vm_name, 18),
    value: vm[dataKey] ?? 0,
    vm,
  }));
  return (
    <ResponsiveContainer width="100%" height={chartData.length * 28 + 16}>
      <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 36, left: 4, bottom: 0 }} barSize={8}>
        <XAxis type="number" domain={[0, 100]} hide />
        <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: 'var(--color-text-secondary)' }} width={120} />
        <Tooltip
          contentStyle={{ background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)', borderRadius: 6, fontSize: 11 }}
          formatter={(val) => [`${Number(val)}%`, label]}
          labelFormatter={(lbl) => String(lbl)}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]}>
          {chartData.map((entry, idx) => (
            <Cell key={idx} fill={getBarColor(entry.value)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
};

export const VMHotspotsCard: React.FC<Props> = ({ cpuData, memoryData, storageData }) => {
  return (
    <div className="vm-hotspots-card card">
      <h2>🔥 VM Hotspots</h2>
      <div className="vm-hotspots-grid">
        <div className="vm-hotspots-section">
          <h3>CPU</h3>
          <HotspotChart vms={cpuData.vms} dataKey="cpu_usage_percent" label="CPU" />
        </div>
        <div className="vm-hotspots-section">
          <h3>Memory</h3>
          <HotspotChart vms={memoryData.vms} dataKey="memory_usage_percent" label="Memory" />
        </div>
        <div className="vm-hotspots-section">
          <h3>Storage</h3>
          <HotspotChart vms={storageData.vms} dataKey="storage_usage_percent" label="Storage" />
        </div>
      </div>
    </div>
  );
};
