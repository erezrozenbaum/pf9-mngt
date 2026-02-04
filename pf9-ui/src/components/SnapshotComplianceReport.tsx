/**
 * Snapshot Compliance Report Component
 */

import React, { useEffect, useMemo, useState } from 'react';
import '../styles/SnapshotComplianceReport.css';

interface ComplianceRow {
  volume_id: string;
  volume_name?: string;
  tenant_id: string;
  tenant_name?: string;
  project_id: string;
  project_name?: string;
  vm_id?: string;
  vm_name?: string;
  policy_name: string;
  retention_days?: number;
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

  const token = localStorage.getItem('auth_token');

  const tenants = useMemo(
    () => Array.from(new Set(rows.map(r => r.tenant_name || r.tenant_id).filter(Boolean))),
    [rows]
  );
  const projects = useMemo(
    () => Array.from(new Set(rows.map(r => r.project_name || r.project_id).filter(Boolean))),
    [rows]
  );
  const policies = useMemo(
    () => Array.from(new Set(rows.map(r => r.policy_name).filter(Boolean))),
    [rows]
  );

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

  return (
    <div className="snapshot-compliance">
      <div className="compliance-header">
        <h2>Snapshot Compliance</h2>
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
        </div>
      )}

      {error && <div className="alert alert-error">{error}</div>}
      {loading ? (
        <div className="loader">Loading...</div>
      ) : (
        <div className="table-container">
          <table className="compliance-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Volume</th>
                <th>Policy</th>
                <th>Last Snapshot</th>
                <th>Tenant</th>
                <th>Project</th>
                <th>VM</th>
                <th>Retention (days)</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="empty-cell">No compliance data</td>
                </tr>
              ) : (
                rows.map((r, idx) => (
                  <tr key={`${r.volume_id}-${r.policy_name}-${idx}`}>
                    <td>
                      <span className={`badge ${r.compliant ? 'enabled' : 'inactive'}`}>
                        {r.compliant ? 'Compliant' : 'Missing'}
                      </span>
                    </td>
                    <td>{r.volume_name || r.volume_id}</td>
                    <td>{r.policy_name}</td>
                    <td>{r.last_snapshot_at ? new Date(r.last_snapshot_at).toLocaleString() : '—'}</td>
                    <td>{r.tenant_name || r.tenant_id}</td>
                    <td>{r.project_name || r.project_id}</td>
                    <td>{r.vm_name || r.vm_id || '—'}</td>
                    <td>{r.retention_days ?? '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default SnapshotComplianceReport;
