/**
 * Snapshot Policy Manager Component
 * 
 * Manages creation, editing, and deletion of snapshot policy sets
 * and assignments with comprehensive UI controls
 */

import React, { useState, useEffect } from 'react';
import type { FC } from 'react';

interface PolicySet {
  id: number;
  name: string;
  description?: string;
  is_global: boolean;
  tenant_id?: string;
  tenant_name?: string;
  policies: string[];
  retention_map: Record<string, number>;
  priority: number;
  is_active: boolean;
  created_at: string;
  created_by: string;
  updated_at: string;
  updated_by: string;
}

interface SnapshotAssignment {
  id: number;
  volume_id: string;
  volume_name: string;
  tenant_id: string;
  tenant_name: string;
  project_id: string;
  project_name: string;
  vm_id?: string;
  vm_name?: string;
  policy_set_id?: number;
  auto_snapshot: boolean;
  policies: string[];
  retention_map: Record<string, number>;
  assignment_source: string;
  created_at: string;
  updated_at: string;
}

interface SnapshotRun {
  id: number;
  run_type: string;
  started_at: string;
  finished_at?: string;
  status: string;
  total_volumes: number;
  snapshots_created: number;
  snapshots_deleted: number;
  snapshots_failed: number;
  volumes_skipped: number;
  dry_run: boolean;
  triggered_by: string;
  trigger_source: string;
}

const SnapshotPolicyManager: FC = () => {
  const [activeTab, setActiveTab] = useState<'policies' | 'assignments' | 'runs'>('policies');
  const [policySets, setPolicySets] = useState<PolicySet[]>([]);
  const [assignments, setAssignments] = useState<SnapshotAssignment[]>([]);
  const [runs, setRuns] = useState<SnapshotRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreatePolicy, setShowCreatePolicy] = useState(false);
  const [editingPolicy, setEditingPolicy] = useState<PolicySet | null>(null);

  const token = localStorage.getItem('auth_token');

  useEffect(() => {
    loadData();
  }, [activeTab]);

  const loadData = async () => {
    setLoading(true);
    setError(null);

    try {
      const headers = { Authorization: `Bearer ${token}` };

      switch (activeTab) {
        case 'policies':
          const policiesRes = await fetch('/api/snapshot/policy-sets', { headers });
          if (!policiesRes.ok) throw new Error('Failed to load policy sets');
          const policiesData = await policiesRes.json();
          setPolicySets(policiesData.policy_sets || []);
          break;

        case 'assignments':
          const assignmentsRes = await fetch('/api/snapshot/assignments', { headers });
          if (!assignmentsRes.ok) throw new Error('Failed to load assignments');
          const assignmentsData = await assignmentsRes.json();
          setAssignments(assignmentsData.assignments || []);
          break;

        case 'runs':
          const runsRes = await fetch('/api/snapshot/runs', { headers });
          if (!runsRes.ok) throw new Error('Failed to load snapshot runs');
          const runsData = await runsRes.json();
          setRuns(runsData.runs || []);
          break;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const handleDeletePolicy = async (policyId: number) => {
    if (!window.confirm('Are you sure you want to delete this policy?')) return;

    try {
      const res = await fetch(`/api/snapshot/policy-sets/${policyId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) throw new Error('Failed to delete policy');
      setPolicySets(policySets.filter((p: PolicySet) => p.id !== policyId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete policy');
    }
  };

  const handleDeleteAssignment = async (volumeId: string) => {
    if (!window.confirm('Are you sure you want to delete this assignment?')) return;

    try {
      const res = await fetch(`/api/snapshot/assignments/${volumeId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) throw new Error('Failed to delete assignment');
      setAssignments(assignments.filter((a: SnapshotAssignment) => a.volume_id !== volumeId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete assignment');
    }
  };

  return (
    <div className="snapshot-policy-manager">
      <h1>Snapshot Management</h1>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="tabs">
        <button
          className={`tab-btn ${activeTab === 'policies' ? 'active' : ''}`}
          onClick={() => setActiveTab('policies')}
        >
          Policy Sets
        </button>
        <button
          className={`tab-btn ${activeTab === 'assignments' ? 'active' : ''}`}
          onClick={() => setActiveTab('assignments')}
        >
          Volume Assignments
        </button>
        <button
          className={`tab-btn ${activeTab === 'runs' ? 'active' : ''}`}
          onClick={() => setActiveTab('runs')}
        >
          Execution Runs
        </button>
      </div>

      <div className="tab-content">
        {activeTab === 'policies' && (
          <div className="policy-sets-section">
            <div className="section-header">
              <h2>Snapshot Policy Sets</h2>
              <button
                className="btn btn-primary"
                onClick={() => {
                  setShowCreatePolicy(true);
                  setEditingPolicy(null);
                }}
              >
                + New Policy
              </button>
            </div>

            {showCreatePolicy && (
              <PolicyForm
                policy={editingPolicy}
                onSave={() => {
                  setShowCreatePolicy(false);
                  loadData();
                }}
                onCancel={() => setShowCreatePolicy(false)}
                token={token}
              />
            )}

            {loading ? (
              <div className="loader">Loading...</div>
            ) : (
              <div className="policy-list">
                {policySets.length === 0 ? (
                  <p className="empty-message">No policy sets found</p>
                ) : (
                  policySets.map((policy: PolicySet) => (
                    <div key={policy.id} className="policy-card">
                      <div className="policy-header">
                        <h3>{policy.name}</h3>
                        <span className={`badge ${policy.is_global ? 'global' : 'tenant'}`}>
                          {policy.is_global ? 'Global' : `Tenant: ${policy.tenant_name}`}
                        </span>
                        {!policy.is_active && <span className="badge inactive">Inactive</span>}
                      </div>
                      {policy.description && <p>{policy.description}</p>}
                      <div className="policy-details">
                        <div>
                          <strong>Policies:</strong> {policy.policies.join(', ')}
                        </div>
                        <div>
                          <strong>Priority:</strong> {policy.priority}
                        </div>
                        <div>
                          <strong>Retention:</strong>
                          <ul>
                            {Object.entries(policy.retention_map).map(([policy, days]) => (
                              <li key={policy}>
                                {policy}: {days} days
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>
                      <div className="policy-actions">
                        <button className="btn btn-sm btn-secondary">Edit</button>
                        <button
                          className="btn btn-sm btn-danger"
                          onClick={() => handleDeletePolicy(policy.id)}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        )}

        {activeTab === 'assignments' && (
          <div className="assignments-section">
            <h2>Volume Assignments</h2>

            {loading ? (
              <div className="loader">Loading...</div>
            ) : (
              <div className="table-container">
                <table className="assignments-table">
                  <thead>
                    <tr>
                      <th>Volume</th>
                      <th>Tenant</th>
                      <th>Project</th>
                      <th>VM</th>
                      <th>Policies</th>
                      <th>Auto Snapshot</th>
                      <th>Source</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {assignments.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="empty-cell">
                          No assignments found
                        </td>
                      </tr>
                    ) : (
                      assignments.map(assignment => (
                        <tr key={assignment.volume_id}>
                          <td>
                            <strong>{assignment.volume_name}</strong>
                            <br />
                            <small>{assignment.volume_id}</small>
                          </td>
                          <td>{assignment.tenant_name}</td>
                          <td>{assignment.project_name}</td>
                          <td>{assignment.vm_name || '—'}</td>
                          <td>{assignment.policies.join(', ')}</td>
                          <td>
                            <span className={`badge ${assignment.auto_snapshot ? 'enabled' : 'disabled'}`}>
                              {assignment.auto_snapshot ? 'Yes' : 'No'}
                            </span>
                          </td>
                          <td>{assignment.assignment_source}</td>
                          <td>
                            <button
                              className="btn btn-sm btn-danger"
                              onClick={() => handleDeleteAssignment(assignment.volume_id)}
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {activeTab === 'runs' && (
          <div className="runs-section">
            <h2>Snapshot Execution Runs</h2>

            {loading ? (
              <div className="loader">Loading...</div>
            ) : (
              <div className="table-container">
                <table className="runs-table">
                  <thead>
                    <tr>
                      <th>Run ID</th>
                      <th>Policy</th>
                      <th>Started</th>
                      <th>Finished</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Deleted</th>
                      <th>Failed</th>
                      <th>Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.length === 0 ? (
                      <tr>
                        <td colSpan={9} className="empty-cell">
                          No runs found
                        </td>
                      </tr>
                    ) : (
                      runs.map(run => (
                        <tr key={run.id}>
                          <td>#{run.id}</td>
                          <td>{run.run_type}</td>
                          <td>{new Date(run.started_at).toLocaleString()}</td>
                          <td>
                            {run.finished_at
                              ? new Date(run.finished_at).toLocaleString()
                              : '—'}
                          </td>
                          <td>
                            <span
                              className={`badge status-${run.status}`}
                            >
                              {run.status}
                            </span>
                          </td>
                          <td>{run.snapshots_created}</td>
                          <td>{run.snapshots_deleted}</td>
                          <td>{run.snapshots_failed}</td>
                          <td>
                            {run.dry_run && <span className="badge">Dry Run</span>}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

interface PolicyFormProps {
  policy: PolicySet | null;
  onSave: () => void;
  onCancel: () => void;
  token: string | null;
}

const PolicyForm: React.FC<PolicyFormProps> = ({ policy, onSave, onCancel, token }) => {
  const [formData, setFormData] = useState<Partial<PolicySet>>(
    policy || {
      name: '',
      description: '',
      is_global: true,
      policies: [],
      retention_map: {},
      priority: 0,
      is_active: true,
    }
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const method = policy ? 'PATCH' : 'POST';
    const url = policy
      ? `/api/snapshot/policy-sets/${policy.id}`
      : '/api/snapshot/policy-sets';

    try {
      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(formData),
      });

      if (!res.ok) throw new Error('Failed to save policy');
      onSave();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to save policy');
    }
  };

  return (
    <form className="policy-form" onSubmit={handleSubmit}>
      <div className="form-group">
        <label>Policy Name *</label>
        <input
          type="text"
          value={formData.name || ''}
          onChange={e => setFormData({ ...formData, name: e.target.value })}
          required
        />
      </div>

      <div className="form-group">
        <label>Description</label>
        <textarea
          value={formData.description || ''}
          onChange={e => setFormData({ ...formData, description: e.target.value })}
        />
      </div>

      <div className="form-group">
        <label>
          <input
            type="checkbox"
            checked={formData.is_global || false}
            onChange={e => setFormData({ ...formData, is_global: e.target.checked })}
          />
          Global Policy (applies to all tenants)
        </label>
      </div>

      <div className="form-actions">
        <button type="submit" className="btn btn-primary">
          {policy ? 'Update' : 'Create'}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
};

export default SnapshotPolicyManager;
