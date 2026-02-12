/**
 * Snapshot Compliance Report Component
 * Groups volumes by policy with per-policy compliance summaries
 * Sortable columns per policy group table
 */

import React, { useEffect, useMemo, useState, useCallback } from 'react';
import '../styles/SnapshotComplianceReport.css';

interface ComplianceRow {
  volume_id: string;
  volume_name: string;
  tenant_id: string;
  tenant_name: string;
  project_id: string;
  project_name: string;
  vm_id?: string;
  vm_name?: string;
  policy_name: string;
  retention_days: number;
  snapshot_count: number;
  last_snapshot_at?: string;
  compliant: boolean;
  status: 'compliant' | 'missing' | 'pending';
}

interface ManualSnapshot {
  snapshot_id: string;
  snapshot_name: string;
  volume_id: string;
  volume_name: string;
  project_id: string;
  project_name: string;
  tenant_id: string;
  tenant_name: string;
  size_gb: number | null;
  status: string;
  created_at: string;
}

interface ComplianceResponse {
  rows: ComplianceRow[];
  count: number;
  summary: {
    compliant: number;
    noncompliant: number;
    pending: number;
    days: number;
  };
  manual_snapshots: ManualSnapshot[];
}

type SortKey = 'compliant' | 'volume_name' | 'volume_id' | 'vm_name' | 'vm_id' | 'tenant_name' | 'project_name' | 'retention_days' | 'snapshot_count' | 'last_snapshot_at';
type SortDir = 'asc' | 'desc';

interface SortState {
  key: SortKey;
  dir: SortDir;
}

function compareCells(a: ComplianceRow, b: ComplianceRow, key: SortKey, dir: SortDir): number {
  let av: string | number | boolean;
  let bv: string | number | boolean;

  switch (key) {
    case 'compliant':
      av = a.compliant ? 1 : 0;
      bv = b.compliant ? 1 : 0;
      break;
    case 'retention_days':
    case 'snapshot_count':
      av = a[key] ?? 0;
      bv = b[key] ?? 0;
      break;
    case 'last_snapshot_at':
      av = a.last_snapshot_at || '';
      bv = b.last_snapshot_at || '';
      break;
    default:
      av = (a[key] || '').toString().toLowerCase();
      bv = (b[key] || '').toString().toLowerCase();
  }

  let cmp = 0;
  if (av < bv) cmp = -1;
  else if (av > bv) cmp = 1;
  return dir === 'desc' ? -cmp : cmp;
}

const SnapshotComplianceReport: React.FC = () => {
  const [rows, setRows] = useState<ComplianceRow[]>([]);
  const [manualSnapshots, setManualSnapshots] = useState<ManualSnapshot[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(2);
  const [tenant, setTenant] = useState('');
  const [project, setProject] = useState('');
  const [policy, setPolicy] = useState('');
  const [summary, setSummary] = useState<ComplianceResponse['summary'] | null>(null);
  const [collapsedPolicies, setCollapsedPolicies] = useState<Set<string>>(new Set());
  // Per-policy sort state
  const [sortByPolicy, setSortByPolicy] = useState<Record<string, SortState>>({});

  const token = localStorage.getItem('auth_token');

  const tenants = useMemo(
    () => {
      const map = new Map<string, string>();
      rows.forEach(r => { if (r.tenant_id && r.tenant_name) map.set(r.tenant_id, r.tenant_name); });
      return Array.from(map.entries()).sort(([, a], [, b]) => a.localeCompare(b));
    },
    [rows]
  );
  const projects = useMemo(
    () => {
      const map = new Map<string, string>();
      rows.forEach(r => { if (r.project_id && r.project_name) map.set(r.project_id, r.project_name); });
      return Array.from(map.entries()).sort(([, a], [, b]) => a.localeCompare(b));
    },
    [rows]
  );
  const policies = useMemo(
    () => Array.from(new Set(rows.map(r => r.policy_name).filter(Boolean))).sort(),
    [rows]
  );

  // Group rows by policy_name
  const groupedByPolicy = useMemo(() => {
    const groups: Record<string, ComplianceRow[]> = {};
    for (const row of rows) {
      const key = row.policy_name || 'Unknown Policy';
      if (!groups[key]) groups[key] = [];
      groups[key].push(row);
    }
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [rows]);

  const togglePolicy = (policyName: string) => {
    setCollapsedPolicies(prev => {
      const next = new Set(prev);
      if (next.has(policyName)) next.delete(policyName);
      else next.add(policyName);
      return next;
    });
  };

  const handleSort = useCallback((policyName: string, key: SortKey) => {
    setSortByPolicy(prev => {
      const current = prev[policyName];
      let dir: SortDir = 'asc';
      if (current && current.key === key) {
        dir = current.dir === 'asc' ? 'desc' : 'asc';
      }
      return { ...prev, [policyName]: { key, dir } };
    });
  }, []);

  const sortedPolicyRows = useCallback((policyName: string, policyRows: ComplianceRow[]): ComplianceRow[] => {
    const sort = sortByPolicy[policyName];
    if (!sort) return policyRows;
    return [...policyRows].sort((a, b) => compareCells(a, b, sort.key, sort.dir));
  }, [sortByPolicy]);

  const sortIndicator = (policyName: string, key: SortKey): string => {
    const sort = sortByPolicy[policyName];
    if (!sort || sort.key !== key) return '';
    return sort.dir === 'asc' ? ' ▲' : ' ▼';
  };

  const loadCompliance = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set('days', String(days));
      if (tenant) params.set('tenant_id', tenant);
      if (project) params.set('project_id', project);
      if (policy) params.set('policy', policy);

      const res = await fetch(`/api/snapshot/compliance?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) throw new Error('Failed to load compliance report');
      const data: ComplianceResponse = await res.json();
      setRows(data.rows || []);
      setSummary(data.summary || null);
      setManualSnapshots(data.manual_snapshots || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load compliance report');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCompliance();
  }, [days, tenant, project, policy]);

  const exportCSV = () => {
    if (rows.length === 0) return;
    const headers = ['Status', 'Volume', 'Volume ID', 'VM', 'VM ID', 'Tenant', 'Project', 'Policy', 'Retention (days)', 'Snapshots', 'Last Snapshot'];
    const csvRows = rows.map(r => [
      r.status === 'compliant' ? 'Compliant' : r.status === 'pending' ? 'Pending' : 'Missing',
      r.volume_name,
      r.volume_id,
      r.vm_name || '',
      r.vm_id || '',
      r.tenant_name,
      r.project_name,
      r.policy_name,
      String(r.retention_days ?? ''),
      String(r.snapshot_count ?? 0),
      r.last_snapshot_at ? new Date(r.last_snapshot_at).toLocaleString() : '',
    ].map(v => `"${(v || '').replace(/"/g, '""')}"`).join(','));
    const csv = [headers.join(','), ...csvRows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `snapshot_compliance_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns: { label: string; key: SortKey; }[] = [
    { label: 'Status',          key: 'compliant' },
    { label: 'Volume',          key: 'volume_name' },
    { label: 'Volume ID',       key: 'volume_id' },
    { label: 'VM',              key: 'vm_name' },
    { label: 'VM ID',           key: 'vm_id' },
    { label: 'Tenant',          key: 'tenant_name' },
    { label: 'Project',         key: 'project_name' },
    { label: 'Retention (days)', key: 'retention_days' },
    { label: 'Snapshots',       key: 'snapshot_count' },
    { label: 'Last Snapshot',   key: 'last_snapshot_at' },
  ];

  return (
    <div className="snapshot-compliance">
      <div className="compliance-header">
        <div className="compliance-title-row">
          <h2>Snapshot Compliance</h2>
          <button className="btn-export" onClick={exportCSV} disabled={rows.length === 0}>
            Export CSV ({rows.length})
          </button>
        </div>
        <div className="compliance-filters">
          <label>
            Days
            <input
              type="number"
              min={1}
              max={365}
              value={days}
              onChange={e => setDays(Number(e.target.value))}
            />
          </label>
          <label>
            Tenant
            <select value={tenant} onChange={e => setTenant(e.target.value)}>
              <option value="">All Tenants</option>
              {tenants.map(([id, name]) => (
                <option key={id} value={id}>{name}</option>
              ))}
            </select>
          </label>
          <label>
            Project
            <select value={project} onChange={e => setProject(e.target.value)}>
              <option value="">All Projects</option>
              {projects.map(([id, name]) => (
                <option key={id} value={id}>{name}</option>
              ))}
            </select>
          </label>
          <label>
            Policy
            <select value={policy} onChange={e => setPolicy(e.target.value)}>
              <option value="">All Policies</option>
              {policies.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {summary && (
        <div className="compliance-summary">
          <div className="summary-card ok">Compliant: {summary.compliant}</div>
          <div className="summary-card warn">Non‑Compliant: {summary.noncompliant}</div>          {summary.pending > 0 && (
            <div className="summary-card pending">Pending: {summary.pending}</div>
          )}          <div className="summary-card">Window: {summary.days} days</div>
          <div className="summary-card">Policies: {policies.length}</div>
        </div>
      )}

      {error && <div className="alert alert-error">{error}</div>}
      {loading ? (
        <div className="loader">Loading...</div>
      ) : (
        <>
        <div className="policy-groups">
          {groupedByPolicy.length === 0 ? (
            <div className="empty-state">No compliance data available</div>
          ) : (
            groupedByPolicy.map(([policyName, policyRows]) => {
              const sorted = sortedPolicyRows(policyName, policyRows);
              const compliant = policyRows.filter(r => r.compliant).length;
              const total = policyRows.length;
              const isCollapsed = collapsedPolicies.has(policyName);
              const pct = total > 0 ? Math.round((compliant / total) * 100) : 0;

              return (
                <div key={policyName} className="policy-group">
                  <div className="policy-group-header" onClick={() => togglePolicy(policyName)}>
                    <span className="policy-toggle">{isCollapsed ? '▶' : '▼'}</span>
                    <span className="policy-group-name">{policyName}</span>
                    <span className="policy-group-stats">
                      <span className={`policy-pct ${pct === 100 ? 'pct-ok' : pct >= 50 ? 'pct-warn' : 'pct-bad'}`}>
                        {pct}%
                      </span>
                      <span className="policy-counts">
                        {compliant}/{total} compliant
                      </span>
                    </span>
                  </div>
                  {!isCollapsed && (
                    <div className="table-container">
                      <table className="compliance-table">
                        <thead>
                          <tr>
                            {columns.map(col => (
                              <th
                                key={col.key}
                                className="sortable-th"
                                onClick={() => handleSort(policyName, col.key)}
                              >
                                {col.label}{sortIndicator(policyName, col.key)}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {sorted.map((r, idx) => (
                            <tr key={`${r.volume_id}-${idx}`} className={r.status === 'missing' ? 'row-missing' : r.status === 'pending' ? 'row-pending' : ''}>
                              <td>
                                <span className={`badge ${r.status === 'compliant' ? 'enabled' : r.status === 'pending' ? 'badge-pending' : 'inactive'}`}>
                                  {r.status === 'compliant' ? 'Compliant' : r.status === 'pending' ? 'Pending' : 'Missing'}
                                </span>
                              </td>
                              <td title={r.volume_id}>{r.volume_name}</td>
                              <td className="cell-id" title={r.volume_id}>{r.volume_id}</td>
                              <td title={r.vm_id || ''}>{r.vm_name || '—'}</td>
                              <td className="cell-id" title={r.vm_id || ''}>{r.vm_id || '—'}</td>
                              <td title={r.tenant_id}>{r.tenant_name}</td>
                              <td title={r.project_id}>{r.project_name}</td>
                              <td>{r.retention_days}</td>
                              <td>{r.snapshot_count}</td>
                              <td>{r.last_snapshot_at ? new Date(r.last_snapshot_at).toLocaleString() : '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
        {manualSnapshots.length > 0 && (
          <div className="manual-snapshots-section">
            <div className="manual-snapshots-header">
              <h3>Manual Snapshots</h3>
              <span className="manual-snapshots-note">
                These snapshots were created outside of automation.
                They are <em>never</em> deleted, modified, or counted toward retention / compliance.
              </span>
            </div>
            <div className="table-container">
              <table className="compliance-table manual-table">
                <thead>
                  <tr>
                    <th>Snapshot Name</th>
                    <th>Snapshot ID</th>
                    <th>Volume</th>
                    <th>Project</th>
                    <th>Tenant</th>
                    <th>Size (GB)</th>
                    <th>Status</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {manualSnapshots.map(ms => (
                    <tr key={ms.snapshot_id}>
                      <td title={ms.snapshot_id}>{ms.snapshot_name}</td>
                      <td className="cell-id" title={ms.snapshot_id}>{ms.snapshot_id}</td>
                      <td title={ms.volume_id}>{ms.volume_name}</td>
                      <td title={ms.project_id}>{ms.project_name}</td>
                      <td title={ms.tenant_id}>{ms.tenant_name}</td>
                      <td>{ms.size_gb ?? '—'}</td>
                      <td>
                        <span className={`badge ${ms.status === 'available' ? 'enabled' : 'inactive'}`}>
                          {ms.status}
                        </span>
                      </td>
                      <td>{ms.created_at ? new Date(ms.created_at).toLocaleString() : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        </>
      )}
    </div>
  );
};

export default SnapshotComplianceReport;
