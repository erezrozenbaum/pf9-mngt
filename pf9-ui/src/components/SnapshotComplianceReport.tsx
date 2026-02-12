/**
 * Snapshot Compliance Report Component
 * Groups volumes by policy with per-policy compliance summaries
 */

import React, { useEffect, useMemo, useState } from 'react';
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
  last_snapshot_at?: string;
  compliant: boolean;
}

interface ComplianceResponse {
  rows: ComplianceRow[];
  count: number;
  summary: {
    compliant: number;
    noncompliant: number;
    days: number;
  };
}

const SnapshotComplianceReport: React.FC = () => {
  const [rows, setRows] = useState<ComplianceRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(2);
  const [tenant, setTenant] = useState('');
  const [project, setProject] = useState('');
  const [policy, setPolicy] = useState('');
  const [summary, setSummary] = useState<ComplianceResponse['summary'] | null>(null);
  const [collapsedPolicies, setCollapsedPolicies] = useState<Set<string>>(new Set());

  const token = localStorage.getItem('auth_token');

  const tenants = useMemo(
    () => Array.from(new Set(rows.map(r => r.tenant_name).filter(Boolean))).sort(),
    [rows]
  );
  const projects = useMemo(
    () => Array.from(new Set(rows.map(r => r.project_name).filter(Boolean))).sort(),
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
    // Sort policies alphabetically
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
    const headers = ['Status', 'Volume', 'VM', 'Tenant', 'Project', 'Policy', 'Retention (days)', 'Last Snapshot'];
    const csvRows = rows.map(r => [
      r.compliant ? 'Compliant' : 'Missing',
      r.volume_name,
      r.vm_name || '',
      r.tenant_name,
      r.project_name,
      r.policy_name,
      String(r.retention_days ?? ''),
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
              {tenants.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>
          <label>
            Project
            <select value={project} onChange={e => setProject(e.target.value)}>
              <option value="">All Projects</option>
              {projects.map(p => (
                <option key={p} value={p}>{p}</option>
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
          <div className="summary-card warn">Non‑Compliant: {summary.noncompliant}</div>
          <div className="summary-card">Window: {summary.days} days</div>
          <div className="summary-card">Policies: {policies.length}</div>
        </div>
      )}

      {error && <div className="alert alert-error">{error}</div>}
      {loading ? (
        <div className="loader">Loading...</div>
      ) : (
        <div className="policy-groups">
          {groupedByPolicy.length === 0 ? (
            <div className="empty-state">No compliance data available</div>
          ) : (
            groupedByPolicy.map(([policyName, policyRows]) => {
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
                            <th>Status</th>
                            <th>Volume</th>
                            <th>VM</th>
                            <th>Tenant</th>
                            <th>Project</th>
                            <th>Retention (days)</th>
                            <th>Last Snapshot</th>
                          </tr>
                        </thead>
                        <tbody>
                          {policyRows.map((r, idx) => (
                            <tr key={`${r.volume_id}-${idx}`} className={r.compliant ? '' : 'row-missing'}>
                              <td>
                                <span className={`badge ${r.compliant ? 'enabled' : 'inactive'}`}>
                                  {r.compliant ? 'Compliant' : 'Missing'}
                                </span>
                              </td>
                              <td title={r.volume_id}>{r.volume_name}</td>
                              <td title={r.vm_id || ''}>{r.vm_name || '—'}</td>
                              <td title={r.tenant_id}>{r.tenant_name}</td>
                              <td title={r.project_id}>{r.project_name}</td>
                              <td>{r.retention_days}</td>
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
      )}
    </div>
  );
};

export default SnapshotComplianceReport;
