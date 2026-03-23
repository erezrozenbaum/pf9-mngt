import React, { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../config';

// ─── Types ────────────────────────────────────────────────────────────────────

interface AuthUser { username: string; email: string; role: string; }

interface LdapConfig {
  id: number;
  name: string;
  host: string;
  port: number;
  use_tls: boolean;
  use_starttls: boolean;
  verify_tls_cert: boolean;
  ca_cert_pem: string | null;
  bind_dn: string;
  bind_password: null;           // always null from GET — write-only
  base_dn: string;
  user_search_filter: string;
  user_attr_uid: string;
  user_attr_mail: string;
  user_attr_fullname: string;
  mfa_delegated: boolean;
  allow_private_network: boolean;
  is_enabled: boolean;
  sync_interval_minutes: number;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_users_found: number | null;
  group_mappings?: GroupMapping[];
}

interface GroupMapping {
  id?: number;
  external_group_dn: string;
  pf9_role: string;
}

interface SyncLog {
  id: number;
  config_name: string | null;
  started_at: string;
  finished_at: string | null;
  status: string;
  users_found: number;
  users_created: number;
  users_updated: number;
  users_deactivated: number;
  error_message: string | null;
}

interface TestResult {
  connected: boolean;
  bind_success: boolean;
  users_found: number;
  sample_users: { uid: string; mail: string; cn: string }[];
  error: string | null;
}

interface PreviewUser {
  uid: string;
  mail: string;
  cn: string;
  action: string;
  pf9_role: string | null;
}

interface PreviewResult {
  total: number;
  to_create: number;
  to_update: number;
  to_deactivate: number;
  users: PreviewUser[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getToken(): string | null {
  return localStorage.getItem('auth_token');
}

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || `API error ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch { return iso as string; }
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string | null }) {
  const cls =
    status === 'success' ? 'bg-green-100 text-green-800' :
    status === 'partial' ? 'bg-yellow-100 text-yellow-800' :
    status === 'failed'  ? 'bg-red-100 text-red-800' :
                           'bg-gray-100 text-gray-600';
  return (
    <span className={`px-2 py-0.5 text-xs rounded-full ${cls}`}>
      {status ?? 'never run'}
    </span>
  );
}

// ─── Form defaults ────────────────────────────────────────────────────────────

const EMPTY_FORM = {
  name: '',
  host: '',
  port: 389,
  use_tls: false,
  use_starttls: false,
  verify_tls_cert: true,
  ca_cert_pem: '',
  bind_dn: '',
  bind_password: '',
  base_dn: '',
  user_search_filter: '(objectClass=person)',
  user_attr_uid: 'uid',
  user_attr_mail: 'mail',
  user_attr_fullname: 'cn',
  mfa_delegated: false,
  allow_private_network: false,
  is_enabled: true,
  sync_interval_minutes: 60,
};

const ASSIGNABLE_ROLES = ['viewer', 'operator', 'technical', 'admin'];

// ─── Main component ───────────────────────────────────────────────────────────

const LdapSyncSettings: React.FC<{ user?: AuthUser | null }> = () => {
  const [configs, setConfigs]           = useState<LdapConfig[]>([]);
  const [loading, setLoading]           = useState(false);
  const [msg, setMsg]                   = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  // Modal state
  const [showModal, setShowModal]       = useState(false);
  const [isEditing, setIsEditing]       = useState(false);
  const [editingId, setEditingId]       = useState<number | null>(null);
  const [form, setForm]                 = useState({ ...EMPTY_FORM });
  const [groupMappings, setGroupMappings] = useState<GroupMapping[]>([]);
  const [saving, setSaving]             = useState(false);

  // Delete confirm
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);

  // Detail pane
  const [detailId, setDetailId]         = useState<number | null>(null);
  const [detailTab, setDetailTab]       = useState<'test' | 'preview' | 'logs'>('test');

  // Test
  const [testResult, setTestResult]     = useState<TestResult | null>(null);
  const [testLoading, setTestLoading]   = useState(false);

  // Preview
  const [previewResult, setPreviewResult] = useState<PreviewResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Sync now
  const [syncingId, setSyncingId]       = useState<number | null>(null);

  // Logs
  const [logs, setLogs]                 = useState<SyncLog[]>([]);
  const [logsLoading, setLogsLoading]   = useState(false);
  const [expandedLogId, setExpandedLogId] = useState<number | null>(null);

  // ── Load configs ──────────────────────────────────────────────────────────

  const loadConfigs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch<LdapConfig[]>('/admin/ldap-sync/configs');
      setConfigs(data);
    } catch (e: unknown) {
      setMsg({ type: 'err', text: (e as Error).message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadConfigs(); }, [loadConfigs]);

  // ── Open create modal ─────────────────────────────────────────────────────

  function openCreate() {
    setIsEditing(false);
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
    setGroupMappings([]);
    setShowModal(true);
  }

  // ── Open edit modal ───────────────────────────────────────────────────────

  async function openEdit(cfg: LdapConfig) {
    setIsEditing(true);
    setEditingId(cfg.id);
    setForm({
      name: cfg.name,
      host: cfg.host,
      port: cfg.port,
      use_tls: cfg.use_tls,
      use_starttls: cfg.use_starttls,
      verify_tls_cert: cfg.verify_tls_cert,
      ca_cert_pem: cfg.ca_cert_pem ?? '',
      bind_dn: cfg.bind_dn,
      bind_password: '',             // never pre-filled; blank = keep existing
      base_dn: cfg.base_dn,
      user_search_filter: cfg.user_search_filter,
      user_attr_uid: cfg.user_attr_uid,
      user_attr_mail: cfg.user_attr_mail,
      user_attr_fullname: cfg.user_attr_fullname,
      mfa_delegated: cfg.mfa_delegated,
      allow_private_network: cfg.allow_private_network,
      is_enabled: cfg.is_enabled,
      sync_interval_minutes: cfg.sync_interval_minutes,
    });
    // Load group mappings via single-config endpoint
    try {
      const detail = await apiFetch<LdapConfig>(`/admin/ldap-sync/configs/${cfg.id}`);
      setGroupMappings(detail.group_mappings ?? []);
    } catch {
      setGroupMappings([]);
    }
    setShowModal(true);
  }

  // ── Save (create or update) ───────────────────────────────────────────────

  async function handleSave() {
    setSaving(true);
    setMsg(null);
    try {
      const body: Record<string, unknown> = { ...form, group_mappings: groupMappings };
      // Omit bind_password on edit if blank — server keeps the existing encrypted value
      if (isEditing && body['bind_password'] === '') {
        delete body['bind_password'];
      }
      if (isEditing && editingId !== null) {
        await apiFetch(`/admin/ldap-sync/configs/${editingId}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        });
        setMsg({ type: 'ok', text: 'Config updated.' });
      } else {
        await apiFetch('/admin/ldap-sync/configs', {
          method: 'POST',
          body: JSON.stringify(body),
        });
        setMsg({ type: 'ok', text: 'Config created.' });
      }
      setShowModal(false);
      await loadConfigs();
    } catch (e: unknown) {
      setMsg({ type: 'err', text: (e as Error).message });
    } finally {
      setSaving(false);
    }
  }

  // ── Delete ────────────────────────────────────────────────────────────────

  async function handleDelete(id: number) {
    try {
      await apiFetch(`/admin/ldap-sync/configs/${id}`, { method: 'DELETE' });
      setMsg({ type: 'ok', text: 'Config deleted. Synced users have been deactivated.' });
      setDeleteConfirm(null);
      if (detailId === id) setDetailId(null);
      await loadConfigs();
    } catch (e: unknown) {
      setMsg({ type: 'err', text: (e as Error).message });
      setDeleteConfirm(null);
    }
  }

  // ── Test connection ───────────────────────────────────────────────────────

  async function handleTest(id: number) {
    setDetailId(id);
    setDetailTab('test');
    setTestResult(null);
    setTestLoading(true);
    try {
      const r = await apiFetch<TestResult>(`/admin/ldap-sync/configs/${id}/test`, { method: 'POST' });
      setTestResult(r);
    } catch (e: unknown) {
      setTestResult({ connected: false, bind_success: false, users_found: 0, sample_users: [], error: (e as Error).message });
    } finally {
      setTestLoading(false);
    }
  }

  // ── Preview sync ──────────────────────────────────────────────────────────

  async function handlePreview(id: number) {
    setDetailId(id);
    setDetailTab('preview');
    setPreviewResult(null);
    setPreviewLoading(true);
    try {
      const r = await apiFetch<PreviewResult>(`/admin/ldap-sync/configs/${id}/preview`, { method: 'POST' });
      setPreviewResult(r);
    } catch (e: unknown) {
      setMsg({ type: 'err', text: (e as Error).message });
    } finally {
      setPreviewLoading(false);
    }
  }

  // ── Sync now ──────────────────────────────────────────────────────────────

  async function handleSync(id: number) {
    setSyncingId(id);
    try {
      await apiFetch(`/admin/ldap-sync/configs/${id}/sync`, { method: 'POST' });
      setMsg({ type: 'ok', text: 'Sync triggered. Check the Logs panel for results.' });
      await loadConfigs();
    } catch (e: unknown) {
      setMsg({ type: 'err', text: (e as Error).message });
    } finally {
      setSyncingId(null);
    }
  }

  // ── View logs ─────────────────────────────────────────────────────────────

  async function handleLogs(id: number) {
    setDetailId(id);
    setDetailTab('logs');
    setLogs([]);
    setExpandedLogId(null);
    setLogsLoading(true);
    try {
      const r = await apiFetch<{ items: SyncLog[] }>(`/admin/ldap-sync/configs/${id}/logs?limit=20`);
      setLogs(r.items ?? []);
    } catch (e: unknown) {
      setMsg({ type: 'err', text: (e as Error).message });
    } finally {
      setLogsLoading(false);
    }
  }

  // ── Form field helper ─────────────────────────────────────────────────────

  function setField<K extends keyof typeof EMPTY_FORM>(key: K, value: (typeof EMPTY_FORM)[K]) {
    setForm(f => ({ ...f, [key]: value }));
  }

  const detailConfig = configs.find(c => c.id === detailId);
  const canSave = form.name.trim() !== '' && form.host.trim() !== '' &&
                  form.base_dn.trim() !== '' && form.bind_dn.trim() !== '' &&
                  (!isEditing ? form.bind_password !== '' : true);

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">External LDAP / Active Directory Sync</h3>
          <p className="text-sm text-gray-500 mt-0.5">
            Sync users from an external LDAP server or Active Directory into this platform.
            Synced users authenticate against their source directory.
          </p>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm whitespace-nowrap"
        >
          ➕ Add Config
        </button>
      </div>

      {/* Message banner */}
      {msg && (
        <div className={`px-4 py-3 rounded text-sm flex items-center justify-between ${
          msg.type === 'ok'
            ? 'bg-green-50 text-green-800 border border-green-200'
            : 'bg-red-50 text-red-800 border border-red-200'
        }`}>
          <span>{msg.text}</span>
          <button onClick={() => setMsg(null)} className="ml-4 text-xs underline opacity-70 hover:opacity-100">
            Dismiss
          </button>
        </div>
      )}

      {/* Config list */}
      {loading ? (
        <div className="text-sm text-gray-500 py-8 text-center">Loading…</div>
      ) : configs.length === 0 ? (
        <div className="text-center py-14 text-gray-400 border-2 border-dashed rounded-lg">
          <div className="text-5xl mb-3">🔄</div>
          <div className="font-medium text-gray-600">No LDAP sync configurations yet</div>
          <div className="text-sm mt-1">
            Click <strong>Add Config</strong> to connect an external Active Directory or LDAP server.
          </div>
        </div>
      ) : (
        <div className="bg-white rounded-lg border overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-700 text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Name</th>
                <th className="px-4 py-3 text-left font-medium">Host : Port</th>
                <th className="px-4 py-3 text-left font-medium">Protocol</th>
                <th className="px-4 py-3 text-left font-medium">Enabled</th>
                <th className="px-4 py-3 text-left font-medium">Last Sync</th>
                <th className="px-4 py-3 text-left font-medium">Interval</th>
                <th className="px-4 py-3 text-left font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {configs.map(cfg => (
                <tr
                  key={cfg.id}
                  className={`hover:bg-gray-50 ${detailId === cfg.id ? 'bg-blue-50' : ''}`}
                >
                  <td className="px-4 py-3 font-medium text-gray-900">{cfg.name}</td>
                  <td className="px-4 py-3 text-gray-600 font-mono text-xs">{cfg.host}:{cfg.port}</td>
                  <td className="px-4 py-3">
                    {cfg.use_tls
                      ? <span className="px-2 py-0.5 bg-green-100 text-green-800 text-xs rounded">TLS</span>
                      : cfg.use_starttls
                        ? <span className="px-2 py-0.5 bg-blue-100 text-blue-800 text-xs rounded">STARTTLS</span>
                        : <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded">Plain</span>
                    }
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 text-xs rounded-full ${
                      cfg.is_enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-500'
                    }`}>
                      {cfg.is_enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="space-y-0.5">
                      <StatusBadge status={cfg.last_sync_status} />
                      {cfg.last_sync_at && (
                        <div className="text-xs text-gray-400">{fmtDate(cfg.last_sync_at)}</div>
                      )}
                      {cfg.last_sync_users_found != null && (
                        <div className="text-xs text-gray-400">{cfg.last_sync_users_found} users</div>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{cfg.sync_interval_minutes} min</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <button
                        title="Edit config"
                        onClick={() => openEdit(cfg)}
                        className="text-blue-600 hover:text-blue-900"
                      >✏️</button>
                      <button
                        title="Test connection"
                        onClick={() => handleTest(cfg.id)}
                        className="text-purple-600 hover:text-purple-900"
                      >🔌</button>
                      <button
                        title="Preview sync (dry-run)"
                        onClick={() => handlePreview(cfg.id)}
                        className="text-indigo-600 hover:text-indigo-900"
                      >👁️</button>
                      <button
                        title="Sync now"
                        onClick={() => handleSync(cfg.id)}
                        disabled={syncingId === cfg.id}
                        className="text-green-600 hover:text-green-900 disabled:opacity-40"
                      >
                        {syncingId === cfg.id ? '⏳' : '▶️'}
                      </button>
                      <button
                        title="View sync logs"
                        onClick={() => handleLogs(cfg.id)}
                        className="text-gray-600 hover:text-gray-900"
                      >📋</button>
                      <button
                        title="Delete config"
                        onClick={() => setDeleteConfirm(cfg.id)}
                        className="text-red-600 hover:text-red-900"
                      >🗑️</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail pane — test / preview / logs */}
      {detailId !== null && detailConfig && (
        <div className="border rounded-lg bg-white overflow-hidden">
          {/* Sub-tab bar */}
          <div className="flex items-center justify-between px-4 py-2 border-b bg-gray-50">
            <div className="flex gap-1">
              {(['test', 'preview', 'logs'] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setDetailTab(t)}
                  className={`text-sm px-3 py-1.5 rounded transition-colors ${
                    detailTab === t
                      ? 'bg-blue-100 text-blue-700 font-medium'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                  }`}
                >
                  {t === 'test' ? '🔌 Test Connection'
                   : t === 'preview' ? '👁️ Preview Sync'
                   : '📋 Sync Logs'}
                </button>
              ))}
              <span className="text-xs text-gray-400 self-center ml-2">— {detailConfig.name}</span>
            </div>
            <button
              onClick={() => setDetailId(null)}
              className="text-gray-400 hover:text-gray-700 text-xl leading-none px-1"
            >×</button>
          </div>

          {/* Test tab */}
          {detailTab === 'test' && (
            <div className="p-4">
              {testLoading && (
                <div className="text-sm text-gray-500 py-6 text-center">Testing connection…</div>
              )}
              {!testLoading && !testResult && (
                <div className="text-gray-400 text-sm py-6 text-center">
                  Click 🔌 on a config row to test its connection.
                </div>
              )}
              {!testLoading && testResult && (
                <div className="space-y-4">
                  <div className="flex flex-wrap gap-2 text-sm">
                    <span className={`px-3 py-1 rounded-full ${
                      testResult.connected ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                    }`}>
                      {testResult.connected ? '✓ Connected' : '✗ Not connected'}
                    </span>
                    <span className={`px-3 py-1 rounded-full ${
                      testResult.bind_success ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                    }`}>
                      {testResult.bind_success ? '✓ Bind successful' : '✗ Bind failed'}
                    </span>
                    {testResult.bind_success && (
                      <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full">
                        {testResult.users_found} user{testResult.users_found !== 1 ? 's' : ''} found
                      </span>
                    )}
                  </div>
                  {testResult.error && (
                    <div className="bg-red-50 border border-red-200 px-3 py-2 rounded text-sm text-red-800 font-mono whitespace-pre-wrap">
                      {testResult.error}
                    </div>
                  )}
                  {testResult.sample_users.length > 0 && (
                    <div>
                      <div className="text-xs text-gray-500 font-semibold uppercase tracking-wide mb-2">
                        Sample users (up to 5)
                      </div>
                      <table className="w-full text-xs border rounded">
                        <thead className="bg-gray-50">
                          <tr>
                            <th className="px-3 py-2 text-left font-medium">UID</th>
                            <th className="px-3 py-2 text-left font-medium">Email</th>
                            <th className="px-3 py-2 text-left font-medium">Display Name</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {testResult.sample_users.map((u, i) => (
                            <tr key={i} className="hover:bg-gray-50">
                              <td className="px-3 py-2 font-mono">{u.uid}</td>
                              <td className="px-3 py-2">{u.mail}</td>
                              <td className="px-3 py-2">{u.cn}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Preview tab */}
          {detailTab === 'preview' && (
            <div className="p-4">
              {previewLoading && (
                <div className="text-sm text-gray-500 py-6 text-center">Running preview (dry-run)…</div>
              )}
              {!previewLoading && !previewResult && (
                <div className="text-gray-400 text-sm py-6 text-center">
                  Click 👁️ on a config row to preview what would be synced.
                </div>
              )}
              {!previewLoading && previewResult && (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2 text-sm">
                    <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full">
                      {previewResult.total} total
                    </span>
                    <span className="px-3 py-1 bg-green-100 text-green-800 rounded-full">
                      +{previewResult.to_create} create
                    </span>
                    <span className="px-3 py-1 bg-yellow-100 text-yellow-800 rounded-full">
                      ~{previewResult.to_update} update
                    </span>
                    <span className="px-3 py-1 bg-red-100 text-red-800 rounded-full">
                      -{previewResult.to_deactivate} deactivate
                    </span>
                  </div>
                  {previewResult.users.length > 0 && (
                    <table className="w-full text-xs border rounded">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-3 py-2 text-left font-medium">UID</th>
                          <th className="px-3 py-2 text-left font-medium">Email</th>
                          <th className="px-3 py-2 text-left font-medium">Name</th>
                          <th className="px-3 py-2 text-left font-medium">Action</th>
                          <th className="px-3 py-2 text-left font-medium">Assigned Role</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {previewResult.users.map((u, i) => (
                          <tr key={i} className="hover:bg-gray-50">
                            <td className="px-3 py-2 font-mono">{u.uid}</td>
                            <td className="px-3 py-2">{u.mail}</td>
                            <td className="px-3 py-2">{u.cn}</td>
                            <td className="px-3 py-2">
                              <span className={`px-2 py-0.5 rounded text-xs ${
                                u.action === 'create'     ? 'bg-green-100 text-green-800' :
                                u.action === 'update'     ? 'bg-yellow-100 text-yellow-800' :
                                u.action === 'deactivate' ? 'bg-red-100 text-red-800' :
                                'bg-gray-100 text-gray-600'
                              }`}>
                                {u.action}
                              </span>
                            </td>
                            <td className="px-3 py-2">{u.pf9_role ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Logs tab */}
          {detailTab === 'logs' && (
            <div className="p-4">
              {logsLoading && (
                <div className="text-sm text-gray-500 py-6 text-center">Loading logs…</div>
              )}
              {!logsLoading && logs.length === 0 && (
                <div className="text-gray-400 text-sm py-6 text-center">
                  No sync runs recorded yet for this config.
                </div>
              )}
              {!logsLoading && logs.length > 0 && (
                <table className="w-full text-xs border rounded">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Started</th>
                      <th className="px-3 py-2 text-left font-medium">Duration</th>
                      <th className="px-3 py-2 text-left font-medium">Status</th>
                      <th className="px-3 py-2 text-left font-medium">Found</th>
                      <th className="px-3 py-2 text-left font-medium text-green-700">Created</th>
                      <th className="px-3 py-2 text-left font-medium text-yellow-700">Updated</th>
                      <th className="px-3 py-2 text-left font-medium text-red-700">Deactivated</th>
                      <th className="px-3 py-2 text-left font-medium">Error</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {logs.map(log => {
                      const dur = log.finished_at && log.started_at
                        ? `${Math.round((new Date(log.finished_at).getTime() - new Date(log.started_at).getTime()) / 1000)}s`
                        : '—';
                      const isExpanded = expandedLogId === log.id;
                      return (
                        <React.Fragment key={log.id}>
                          <tr
                            className="hover:bg-gray-50 cursor-pointer"
                            onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                          >
                            <td className="px-3 py-2">{fmtDate(log.started_at)}</td>
                            <td className="px-3 py-2">{dur}</td>
                            <td className="px-3 py-2"><StatusBadge status={log.status} /></td>
                            <td className="px-3 py-2">{log.users_found}</td>
                            <td className="px-3 py-2 text-green-700">+{log.users_created}</td>
                            <td className="px-3 py-2 text-yellow-700">~{log.users_updated}</td>
                            <td className="px-3 py-2 text-red-700">-{log.users_deactivated}</td>
                            <td className="px-3 py-2 text-red-700 max-w-xs truncate">
                              {log.error_message ?? '—'}
                            </td>
                          </tr>
                          {isExpanded && log.error_message && (
                            <tr>
                              <td colSpan={8} className="px-4 py-3 bg-red-50 border-t border-red-100">
                                <pre className="text-xs text-red-800 whitespace-pre-wrap font-mono">
                                  {log.error_message}
                                </pre>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Delete confirmation modal ──────────────────────────────────────── */}
      {deleteConfirm !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-sm mx-4">
            <h3 className="text-lg font-semibold mb-3 text-red-700">Delete Sync Config?</h3>
            <p className="text-sm text-gray-600 mb-5">
              All users synced from this config will be <strong>deactivated immediately</strong> and
              their active sessions revoked. This cannot be undone.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 text-sm border rounded hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded hover:bg-red-700"
              >
                Delete Config
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Create / Edit modal ────────────────────────────────────────────── */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-start justify-center z-50 overflow-y-auto py-8">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl mx-4 my-auto">
            {/* Modal header */}
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h2 className="text-lg font-semibold text-gray-900">
                {isEditing ? 'Edit LDAP Sync Config' : 'New LDAP Sync Config'}
              </h2>
              <button
                onClick={() => setShowModal(false)}
                className="text-gray-400 hover:text-gray-700 text-2xl leading-none"
              >×</button>
            </div>

            {/* Modal body */}
            <div className="px-6 py-5 space-y-6 overflow-y-auto" style={{ maxHeight: '70vh' }}>

              {/* Name + enabled */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">Config Name *</label>
                  <input
                    value={form.name}
                    onChange={e => setField('name', e.target.value)}
                    placeholder="e.g. Corp Active Directory"
                    className="w-full px-3 py-2 border rounded text-sm"
                  />
                </div>
                <div className="flex items-center gap-3 pt-6">
                  <input
                    type="checkbox" id="ldap_is_enabled"
                    checked={form.is_enabled}
                    onChange={e => setField('is_enabled', e.target.checked)}
                    className="w-4 h-4"
                  />
                  <label htmlFor="ldap_is_enabled" className="text-sm text-gray-700 cursor-pointer">
                    Enabled (auto-sync on schedule)
                  </label>
                </div>
              </div>

              {/* Connection */}
              <section>
                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 border-b pb-1">
                  Connection
                </h4>
                <div className="grid grid-cols-3 gap-4 mb-4">
                  <div className="col-span-2">
                    <label className="block text-xs font-medium text-gray-700 mb-1">LDAP Host *</label>
                    <input
                      value={form.host}
                      onChange={e => setField('host', e.target.value)}
                      placeholder="ldap.corp.com"
                      className="w-full px-3 py-2 border rounded text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Port *</label>
                    <input
                      type="number" min={1} max={65535}
                      value={form.port}
                      onChange={e => setField('port', Number(e.target.value))}
                      className="w-full px-3 py-2 border rounded text-sm"
                    />
                  </div>
                </div>
                <div className="flex flex-wrap gap-5 mb-3">
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox" checked={form.use_tls}
                      onChange={e => {
                        setField('use_tls', e.target.checked);
                        if (e.target.checked) setField('use_starttls', false);
                      }}
                    />
                    Use TLS (LDAPS, typically port 636)
                  </label>
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox" checked={form.use_starttls}
                      onChange={e => {
                        setField('use_starttls', e.target.checked);
                        if (e.target.checked) setField('use_tls', false);
                      }}
                    />
                    Use STARTTLS (upgrade plain connection)
                  </label>
                  <label className={`flex items-center gap-2 text-sm cursor-pointer ${
                    !form.use_tls && !form.use_starttls ? 'opacity-40' : ''
                  }`}>
                    <input
                      type="checkbox" checked={form.verify_tls_cert}
                      disabled={!form.use_tls && !form.use_starttls}
                      onChange={e => setField('verify_tls_cert', e.target.checked)}
                    />
                    Verify TLS certificate
                  </label>
                </div>
                {(form.use_tls || form.use_starttls) && (
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      CA Certificate PEM (optional — paste if using a self-signed or private CA)
                    </label>
                    <textarea
                      value={form.ca_cert_pem}
                      onChange={e => setField('ca_cert_pem', e.target.value)}
                      rows={5}
                      className="w-full px-3 py-2 border rounded text-xs font-mono"
                      placeholder={"-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"}
                    />
                  </div>
                )}
              </section>

              {/* Service account */}
              <section>
                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 border-b pb-1">
                  Service Account
                </h4>
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Bind DN *</label>
                    <input
                      value={form.bind_dn}
                      onChange={e => setField('bind_dn', e.target.value)}
                      placeholder="cn=svc-pf9,ou=service,dc=corp,dc=com"
                      className="w-full px-3 py-2 border rounded text-sm font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      Bind Password {isEditing ? <span className="font-normal text-gray-400">(leave blank to keep current)</span> : '*'}
                    </label>
                    <input
                      type="password"
                      value={form.bind_password}
                      onChange={e => setField('bind_password', e.target.value)}
                      placeholder={isEditing ? '••••••••' : 'Enter password'}
                      className="w-full px-3 py-2 border rounded text-sm"
                    />
                  </div>
                </div>
              </section>

              {/* User search */}
              <section>
                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 border-b pb-1">
                  User Search
                </h4>
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Base DN *</label>
                    <input
                      value={form.base_dn}
                      onChange={e => setField('base_dn', e.target.value)}
                      placeholder="ou=users,dc=corp,dc=com"
                      className="w-full px-3 py-2 border rounded text-sm font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">User Search Filter</label>
                    <input
                      value={form.user_search_filter}
                      onChange={e => setField('user_search_filter', e.target.value)}
                      className="w-full px-3 py-2 border rounded text-sm font-mono"
                    />
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">UID attribute</label>
                      <input
                        value={form.user_attr_uid}
                        onChange={e => setField('user_attr_uid', e.target.value)}
                        className="w-full px-3 py-2 border rounded text-sm font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">Email attribute</label>
                      <input
                        value={form.user_attr_mail}
                        onChange={e => setField('user_attr_mail', e.target.value)}
                        className="w-full px-3 py-2 border rounded text-sm font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-1">Display name attribute</label>
                      <input
                        value={form.user_attr_fullname}
                        onChange={e => setField('user_attr_fullname', e.target.value)}
                        className="w-full px-3 py-2 border rounded text-sm font-mono"
                      />
                    </div>
                  </div>
                </div>
              </section>

              {/* Group → Role mappings */}
              <section>
                <div className="flex items-center justify-between mb-3 border-b pb-1">
                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Group → Role Mappings
                  </h4>
                  <button
                    type="button"
                    onClick={() => setGroupMappings(m => [...m, { external_group_dn: '', pf9_role: 'viewer' }])}
                    className="text-xs px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded"
                  >
                    ➕ Add Row
                  </button>
                </div>
                {groupMappings.length === 0 ? (
                  <p className="text-xs text-gray-400 italic">
                    No mappings defined — all synced users receive the <code>viewer</code> role.
                    Add rows to assign roles based on external group membership.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {groupMappings.map((m, i) => (
                      <div key={i} className="flex gap-2 items-center">
                        <input
                          value={m.external_group_dn}
                          onChange={e => {
                            const updated = [...groupMappings];
                            updated[i] = { ...updated[i], external_group_dn: e.target.value };
                            setGroupMappings(updated);
                          }}
                          placeholder="cn=pf9-admins,ou=groups,dc=corp,dc=com"
                          className="flex-1 px-2 py-1.5 border rounded text-xs font-mono"
                        />
                        <select
                          value={m.pf9_role}
                          onChange={e => {
                            const updated = [...groupMappings];
                            updated[i] = { ...updated[i], pf9_role: e.target.value };
                            setGroupMappings(updated);
                          }}
                          className="px-2 py-1.5 border rounded text-xs"
                        >
                          {ASSIGNABLE_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                        </select>
                        <button
                          type="button"
                          onClick={() => setGroupMappings(m => m.filter((_, j) => j !== i))}
                          className="text-red-500 hover:text-red-700 px-1"
                          title="Remove row"
                        >✕</button>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {/* Schedule & options */}
              <section>
                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 border-b pb-1">
                  Schedule & Options
                </h4>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Sync Interval</label>
                    <select
                      value={form.sync_interval_minutes}
                      onChange={e => setField('sync_interval_minutes', Number(e.target.value))}
                      className="w-full px-3 py-2 border rounded text-sm"
                    >
                      <option value={15}>Every 15 minutes</option>
                      <option value={30}>Every 30 minutes</option>
                      <option value={60}>Every hour</option>
                      <option value={120}>Every 2 hours</option>
                      <option value={360}>Every 6 hours</option>
                      <option value={720}>Every 12 hours</option>
                      <option value={1440}>Once a day</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                      <input
                        type="checkbox" checked={form.mfa_delegated}
                        onChange={e => setField('mfa_delegated', e.target.checked)}
                        className="w-4 h-4"
                      />
                      MFA delegated to external IdP
                    </label>
                    <p className="text-xs text-gray-400 pl-6">
                      If enabled, system TOTP is skipped for users from this source.
                    </p>
                  </div>
                </div>

                {/* Private network warning */}
                <div>
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox" checked={form.allow_private_network}
                      onChange={e => setField('allow_private_network', e.target.checked)}
                      className="w-4 h-4"
                    />
                    Allow private / internal network addresses (RFC-1918, loopback)
                  </label>
                  {form.allow_private_network && (
                    <div className="mt-2 flex gap-2 px-3 py-2 bg-amber-50 border border-amber-300 rounded text-xs text-amber-800">
                      <span className="shrink-0">⚠️</span>
                      <span>
                        <strong>Security warning:</strong> This allows connecting to internal network
                        addresses (10.x, 172.16–31.x, 192.168.x, loopback). Only enable when your LDAP
                        server is legitimately hosted internally and this is intentional.
                      </span>
                    </div>
                  )}
                </div>
              </section>

            </div>

            {/* Modal footer */}
            <div className="flex justify-end gap-3 px-6 py-4 border-t bg-gray-50">
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 text-sm border rounded hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !canSave}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {saving ? 'Saving…' : isEditing ? 'Update Config' : 'Create Config'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};

export default LdapSyncSettings;
