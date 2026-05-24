import React, { useState, useEffect, useCallback } from 'react';
import '../styles/CleaPoliciesTab.css';
import { apiFetch } from '../lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CleaPolicy {
  id: number;
  event_type: string;
  condition_expr: Record<string, unknown>;
  runbook_name: string;
  approval_mode: 'auto' | 'single_approval' | 'disabled';
  enabled: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

interface CleaExecution {
  id: number;
  policy_id: number;
  event_id: number | null;
  triggered_at: string;
  approval_status: 'pending' | 'approved' | 'rejected' | 'skipped' | 'executed';
  approved_by: string | null;
  approved_at: string | null;
  execution_id: string | null;
  result: Record<string, unknown> | null;
  event_type?: string;
  runbook_name?: string;
  approval_mode?: string;
}

interface PolicyFormState {
  event_type: string;
  condition_expr: string;
  runbook_name: string;
  approval_mode: 'auto' | 'single_approval' | 'disabled';
  enabled: boolean;
}

interface Props {
  userRole?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const CleaPoliciesTab: React.FC<Props> = ({ userRole }) => {
  const isSuperadmin = userRole === 'superadmin';

  const [activeTab, setActiveTab] = useState<'policies' | 'executions'>('policies');

  // Policies state
  const [policies, setPolicies] = useState<CleaPolicy[]>([]);
  const [policiesLoading, setPoliciesLoading] = useState(true);
  const [policiesError, setPoliciesError] = useState<string | null>(null);

  // Executions state
  const [executions, setExecutions] = useState<CleaExecution[]>([]);
  const [execLoading, setExecLoading] = useState(false);
  const [execError, setExecError] = useState<string | null>(null);

  // Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [editingPolicy, setEditingPolicy] = useState<CleaPolicy | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSaving, setFormSaving] = useState(false);
  const [form, setForm] = useState<PolicyFormState>({
    event_type: '',
    condition_expr: '{}',
    runbook_name: '',
    approval_mode: 'single_approval',
    enabled: true,
  });

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  const loadPolicies = useCallback(async () => {
    setPoliciesLoading(true);
    setPoliciesError(null);
    try {
      const data = await apiFetch<CleaPolicy[]>('/api/admin/clea/policies');
      setPolicies(data);
    } catch (e: unknown) {
      setPoliciesError(e instanceof Error ? e.message : 'Failed to load policies');
    } finally {
      setPoliciesLoading(false);
    }
  }, []);

  const loadExecutions = useCallback(async () => {
    setExecLoading(true);
    setExecError(null);
    try {
      const data = await apiFetch<CleaExecution[]>('/api/admin/clea/executions?limit=100');
      setExecutions(data);
    } catch (e: unknown) {
      setExecError(e instanceof Error ? e.message : 'Failed to load executions');
    } finally {
      setExecLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPolicies();
  }, [loadPolicies]);

  useEffect(() => {
    if (activeTab === 'executions') {
      loadExecutions();
    }
  }, [activeTab, loadExecutions]);

  // ---------------------------------------------------------------------------
  // Modal helpers
  // ---------------------------------------------------------------------------

  const openCreateModal = () => {
    setEditingPolicy(null);
    setForm({ event_type: '', condition_expr: '{}', runbook_name: '', approval_mode: 'single_approval', enabled: true });
    setFormError(null);
    setModalOpen(true);
  };

  const openEditModal = (p: CleaPolicy) => {
    setEditingPolicy(p);
    setForm({
      event_type: p.event_type,
      condition_expr: JSON.stringify(p.condition_expr, null, 2),
      runbook_name: p.runbook_name,
      approval_mode: p.approval_mode,
      enabled: p.enabled,
    });
    setFormError(null);
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setEditingPolicy(null);
    setFormError(null);
  };

  const handleFormChange = (field: keyof PolicyFormState, value: string | boolean) => {
    setForm(prev => ({ ...prev, [field]: value }));
  };

  const handleSave = async () => {
    setFormError(null);

    let parsedCondition: Record<string, unknown>;
    try {
      parsedCondition = JSON.parse(form.condition_expr);
    } catch {
      setFormError('Condition expression must be valid JSON (e.g. {} or {"key":"value"})');
      return;
    }

    if (!form.event_type.trim()) {
      setFormError('Event type is required');
      return;
    }
    if (!form.runbook_name.trim()) {
      setFormError('Runbook name is required');
      return;
    }

    setFormSaving(true);
    try {
      const payload = {
        event_type: form.event_type.trim(),
        condition_expr: parsedCondition,
        runbook_name: form.runbook_name.trim(),
        approval_mode: form.approval_mode,
        enabled: form.enabled,
      };

      if (editingPolicy) {
        await apiFetch(`/api/admin/clea/policies/${editingPolicy.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        await apiFetch('/api/admin/clea/policies', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }

      closeModal();
      loadPolicies();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setFormSaving(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Policy actions
  // ---------------------------------------------------------------------------

  const handleToggle = async (p: CleaPolicy) => {
    try {
      await apiFetch(`/api/admin/clea/policies/${p.id}/toggle`, { method: 'PATCH' });
      loadPolicies();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Toggle failed');
    }
  };

  const handleDelete = async (p: CleaPolicy) => {
    if (!confirm(`Delete policy for "${p.event_type}" → ${p.runbook_name}?`)) return;
    try {
      await apiFetch(`/api/admin/clea/policies/${p.id}`, { method: 'DELETE' });
      loadPolicies();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Delete failed');
    }
  };

  // ---------------------------------------------------------------------------
  // Execution actions
  // ---------------------------------------------------------------------------

  const handleApprove = async (ex: CleaExecution) => {
    try {
      await apiFetch(`/api/admin/clea/executions/${ex.id}/approve`, { method: 'POST' });
      loadExecutions();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Approve failed');
    }
  };

  const handleReject = async (ex: CleaExecution) => {
    if (!confirm('Reject this CLEA execution?')) return;
    try {
      await apiFetch(`/api/admin/clea/executions/${ex.id}/reject`, { method: 'POST' });
      loadExecutions();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Reject failed');
    }
  };

  // ---------------------------------------------------------------------------
  // Badge helpers
  // ---------------------------------------------------------------------------

  const approvalModeBadge = (mode: string) => {
    if (mode === 'auto') return <span className="clea-badge clea-badge--auto">auto</span>;
    if (mode === 'single_approval') return <span className="clea-badge clea-badge--single">approval</span>;
    return <span className="clea-badge clea-badge--disabled">disabled</span>;
  };

  const statusBadge = (s: string) => {
    const cls = `clea-badge clea-badge--${s === 'executed' ? 'executed' : s === 'pending' ? 'pending' : s === 'approved' ? 'approved' : s === 'rejected' ? 'rejected' : 'skipped'}`;
    return <span className={cls}>{s}</span>;
  };

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="clea-root">
      {/* Header */}
      <div className="clea-header">
        <div>
          <h2>⚡ Automation (CLEA)</h2>
          <p className="clea-header__subtitle">
            Closed-Loop Event Automation — map operational events to runbooks for automatic or approval-gated responses.
          </p>
        </div>
        {isSuperadmin && activeTab === 'policies' && (
          <div className="clea-header__actions">
            <button className="clea-btn clea-btn--primary" onClick={openCreateModal}>
              + New Policy
            </button>
            <button className="clea-btn clea-btn--secondary" onClick={loadPolicies}>
              ↺ Refresh
            </button>
          </div>
        )}
        {activeTab === 'executions' && (
          <div className="clea-header__actions">
            <button className="clea-btn clea-btn--secondary" onClick={loadExecutions}>
              ↺ Refresh
            </button>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="clea-tabs">
        <button
          className={`clea-tab-btn${activeTab === 'policies' ? ' active' : ''}`}
          onClick={() => setActiveTab('policies')}
        >
          Policies
        </button>
        <button
          className={`clea-tab-btn${activeTab === 'executions' ? ' active' : ''}`}
          onClick={() => setActiveTab('executions')}
        >
          Execution Log
        </button>
      </div>

      {/* Policies tab */}
      {activeTab === 'policies' && (
        <>
          {policiesLoading && (
            <div className="clea-loading">
              <div className="clea-spinner" />
              Loading policies…
            </div>
          )}
          {policiesError && <div className="clea-error">⚠ {policiesError}</div>}
          {!policiesLoading && !policiesError && (
            policies.length === 0 ? (
              <div className="clea-empty">
                No automation policies defined.{isSuperadmin ? ' Click "+ New Policy" to create one.' : ''}
              </div>
            ) : (
              <div className="clea-table-wrap">
                <table className="clea-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Event Type</th>
                      <th>Condition</th>
                      <th>Runbook</th>
                      <th>Mode</th>
                      <th>Status</th>
                      {isSuperadmin && <th>Actions</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {policies.map(p => (
                      <tr key={p.id}>
                        <td>{p.id}</td>
                        <td><code>{p.event_type}</code></td>
                        <td>
                          <code style={{ fontSize: '0.7rem' }}>
                            {Object.keys(p.condition_expr).length === 0
                              ? '(any)'
                              : JSON.stringify(p.condition_expr)}
                          </code>
                        </td>
                        <td>{p.runbook_name}</td>
                        <td>{approvalModeBadge(p.approval_mode)}</td>
                        <td>
                          <span className={`clea-badge ${p.enabled ? 'clea-badge--enabled' : 'clea-badge--off'}`}>
                            {p.enabled ? 'enabled' : 'disabled'}
                          </span>
                        </td>
                        {isSuperadmin && (
                          <td>
                            <div className="clea-row-actions">
                              <button className="clea-btn clea-btn--secondary" onClick={() => openEditModal(p)}>
                                Edit
                              </button>
                              <button className="clea-btn clea-btn--secondary" onClick={() => handleToggle(p)}>
                                {p.enabled ? 'Disable' : 'Enable'}
                              </button>
                              <button className="clea-btn clea-btn--danger" onClick={() => handleDelete(p)}>
                                Delete
                              </button>
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </>
      )}

      {/* Executions tab */}
      {activeTab === 'executions' && (
        <>
          {execLoading && (
            <div className="clea-loading">
              <div className="clea-spinner" />
              Loading executions…
            </div>
          )}
          {execError && <div className="clea-error">⚠ {execError}</div>}
          {!execLoading && !execError && (
            executions.length === 0 ? (
              <div className="clea-empty">No CLEA executions recorded yet.</div>
            ) : (
              <div className="clea-table-wrap">
                <table className="clea-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Triggered</th>
                      <th>Event Type</th>
                      <th>Runbook</th>
                      <th>Mode</th>
                      <th>Status</th>
                      <th>Approved By</th>
                      {isSuperadmin && <th>Actions</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {executions.map(ex => (
                      <tr key={ex.id}>
                        <td>{ex.id}</td>
                        <td>{fmtDate(ex.triggered_at)}</td>
                        <td><code>{ex.event_type ?? `policy #${ex.policy_id}`}</code></td>
                        <td>{ex.runbook_name ?? '—'}</td>
                        <td>{ex.approval_mode ? approvalModeBadge(ex.approval_mode) : '—'}</td>
                        <td>{statusBadge(ex.approval_status)}</td>
                        <td>{ex.approved_by ?? '—'}</td>
                        {isSuperadmin && (
                          <td>
                            {ex.approval_status === 'pending' ? (
                              <div className="clea-row-actions">
                                <button className="clea-btn clea-btn--success" onClick={() => handleApprove(ex)}>
                                  Approve
                                </button>
                                <button className="clea-btn clea-btn--danger" onClick={() => handleReject(ex)}>
                                  Reject
                                </button>
                              </div>
                            ) : '—'}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </>
      )}

      {/* Create / Edit Modal */}
      {modalOpen && (
        <div className="clea-modal-overlay" onClick={closeModal}>
          <div className="clea-modal" onClick={e => e.stopPropagation()}>
            <h3>{editingPolicy ? 'Edit Policy' : 'New Automation Policy'}</h3>

            {formError && <div className="clea-error-msg">{formError}</div>}

            <div className="clea-form-row">
              <label>Event Type</label>
              <input
                type="text"
                placeholder="e.g. drift.resource_orphaned"
                value={form.event_type}
                onChange={e => handleFormChange('event_type', e.target.value)}
              />
              <p className="clea-form-hint">Dot-separated event type emitted by the system (e.g. vm.provisioned).</p>
            </div>

            <div className="clea-form-row">
              <label>Condition (JSON)</label>
              <textarea
                value={form.condition_expr}
                onChange={e => handleFormChange('condition_expr', e.target.value)}
                placeholder='{}'
              />
              <p className="clea-form-hint">
                Empty object <code>{'{}'}</code> matches all events of this type.
                Add key-value pairs to filter by event metadata (e.g. <code>{"{ \"severity\": \"critical\" }"}</code>).
              </p>
            </div>

            <div className="clea-form-row">
              <label>Runbook Name</label>
              <input
                type="text"
                placeholder="e.g. orphan_resource_cleanup"
                value={form.runbook_name}
                onChange={e => handleFormChange('runbook_name', e.target.value)}
              />
            </div>

            <div className="clea-form-row">
              <label>Approval Mode</label>
              <select
                value={form.approval_mode}
                onChange={e => handleFormChange('approval_mode', e.target.value)}
              >
                <option value="single_approval">Single Approval (requires manual approve)</option>
                <option value="auto">Auto (runs immediately)</option>
                <option value="disabled">Disabled (policy inactive)</option>
              </select>
            </div>

            <div className="clea-form-row">
              <label>
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={e => handleFormChange('enabled', e.target.checked)}
                  style={{ marginRight: '0.5rem' }}
                />
                Enabled
              </label>
            </div>

            <div className="clea-modal-actions">
              <button className="clea-btn clea-btn--secondary" onClick={closeModal} disabled={formSaving}>
                Cancel
              </button>
              <button className="clea-btn clea-btn--primary" onClick={handleSave} disabled={formSaving}>
                {formSaving ? 'Saving…' : editingPolicy ? 'Save Changes' : 'Create Policy'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CleaPoliciesTab;
