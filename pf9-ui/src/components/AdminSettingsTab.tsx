/**
 * AdminSettingsTab — System configuration panel (v2.12.0)
 *
 * Provides admin-level visibility and control over system configuration:
 * - Multi-region HA: view status, enable/disable, configure read replica URL
 * - Node Logs: view configured source, test connectivity
 * - SSE: live event stream status
 *
 * NOTE: These settings require backend environment variable changes to
 * take permanent effect. The UI allows admins to see current runtime
 * configuration and trigger test calls. Persistent changes require
 * updating values.prod.yaml in the private deploy repo.
 */

import React, { useState, useEffect } from 'react';
import { apiFetch } from '../lib/api';
import '../styles/AdminSettingsTab.css';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SystemConfig {
  multi_region_enabled: boolean;
  db_read_replica_url_set: boolean;   // true if env var is non-empty (value hidden)
  node_log_source: string;
  node_log_configured: boolean;
  node_log_cache_ttl_s: number;
  redis_available: boolean;
  prometheus_available: boolean;
  prometheus_url_set: boolean;
  sse_enabled: boolean;
  version: string;
}

interface SaveResult {
  ok: boolean;
  message: string;
}

// ---------------------------------------------------------------------------
// Section component
// ---------------------------------------------------------------------------

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="admin-settings-section">
      <h3 className="admin-settings-section__title">{title}</h3>
      <div className="admin-settings-section__body">{children}</div>
    </section>
  );
}

function StatusPill({ ok, trueLabel = 'Enabled', falseLabel = 'Disabled' }: { ok: boolean; trueLabel?: string; falseLabel?: string }) {
  return (
    <span className={`admin-settings-pill ${ok ? 'admin-settings-pill--ok' : 'admin-settings-pill--off'}`}>
      {ok ? trueLabel : falseLabel}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AdminSettingsTab() {
  const [config, setConfig]     = useState<SystemConfig | null>(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [saved, setSaved]       = useState<SaveResult | null>(null);

  // Multi-region form state
  const [mrEnabled, setMrEnabled]           = useState(false);
  const [mrReplicaUrl, setMrReplicaUrl]     = useState('');
  const [mrSaving, setMrSaving]             = useState(false);

  useEffect(() => {
    apiFetch<SystemConfig>('/api/admin/system/config')
      .then(data => {
        setConfig(data);
        setMrEnabled(data.multi_region_enabled);
        // We never pre-fill the URL (secret) — leave blank unless user types
      })
      .catch(() => setError('Failed to load system configuration'))
      .finally(() => setLoading(false));
  }, []);

  const handleSaveMultiRegion = async () => {
    setMrSaving(true);
    setSaved(null);
    try {
      await apiFetch('/api/admin/system/config/multi-region', {
        method: 'POST',
        body: JSON.stringify({
          enabled: mrEnabled,
          db_read_replica_url: mrReplicaUrl || undefined,
        }),
      });
      setSaved({ ok: true, message: 'Configuration saved. Restart the API pod to apply changes.' });
      // Reload config
      const fresh = await apiFetch<SystemConfig>('/api/admin/system/config');
      setConfig(fresh);
      setMrEnabled(fresh.multi_region_enabled);
    } catch (err: unknown) {
      setSaved({ ok: false, message: err instanceof Error ? err.message : 'Save failed' });
    } finally {
      setMrSaving(false);
    }
  };

  if (loading) return <div className="admin-settings-loading">Loading configuration…</div>;
  if (error)   return <div className="admin-settings-error">⚠ {error}</div>;
  if (!config) return null;

  return (
    <div className="admin-settings-container">
      <div className="admin-settings-header">
        <h2>System Settings</h2>
        <p className="admin-settings-subtitle">
          Runtime configuration for Platform9 Management Portal — v{config.version}
        </p>
        <p className="admin-settings-note">
          ⚠ Persistent changes require updating <code>values.prod.yaml</code> in the private deploy
          repository and re-syncing ArgoCD. The controls below apply a runtime override only.
        </p>
      </div>

      {saved && (
        <div className={`admin-settings-banner ${saved.ok ? 'admin-settings-banner--ok' : 'admin-settings-banner--err'}`}>
          {saved.message}
        </div>
      )}

      {/* ── Infrastructure status ── */}
      <SettingsSection title="Infrastructure Status">
        <div className="admin-settings-grid">
          <div className="admin-settings-item">
            <span className="admin-settings-label">Redis</span>
            <StatusPill ok={config.redis_available} trueLabel="Connected" falseLabel="Unavailable" />
          </div>
          <div className="admin-settings-item">
            <span className="admin-settings-label">Prometheus</span>
            <StatusPill ok={config.prometheus_available} trueLabel="Reachable" falseLabel="Not reachable" />
          </div>
          <div className="admin-settings-item">
            <span className="admin-settings-label">SSE event stream</span>
            <StatusPill ok={config.sse_enabled} trueLabel="Active" falseLabel="Inactive" />
          </div>
        </div>
      </SettingsSection>

      {/* ── Multi-region HA ── */}
      <SettingsSection title="Multi-Region HA — Read Replica Routing">
        <p className="admin-settings-desc">
          When enabled, read-heavy queries route to a PostgreSQL read replica via
          <code>get_read_connection()</code>. Falls back to the primary pool on error.
          Requires <code>DB_READ_REPLICA_URL</code> to be set.
        </p>

        <div className="admin-settings-form">
          <div className="admin-settings-form-row">
            <label className="admin-settings-form-label">Enable multi-region routing</label>
            <div className="admin-settings-toggle-row">
              <label className="admin-settings-toggle">
                <input
                  type="checkbox"
                  checked={mrEnabled}
                  onChange={e => setMrEnabled(e.target.checked)}
                />
                <span className="admin-settings-toggle__slider" />
              </label>
              <StatusPill ok={config.multi_region_enabled} trueLabel="Currently ON" falseLabel="Currently OFF" />
            </div>
          </div>

          <div className="admin-settings-form-row">
            <label className="admin-settings-form-label">
              Read replica URL
              <span className="admin-settings-form-hint">
                {config.db_read_replica_url_set ? '(currently set — leave blank to keep)' : '(not set)'}
              </span>
            </label>
            <input
              type="password"
              className="admin-settings-input"
              placeholder={config.db_read_replica_url_set
                ? 'postgresql://*** (leave blank to keep existing)'
                : 'postgresql://user:pass@replica-host:5432/pf9_mgmt'}
              value={mrReplicaUrl}
              onChange={e => setMrReplicaUrl(e.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="admin-settings-form-actions">
            <button
              className="btn btn--primary"
              onClick={handleSaveMultiRegion}
              disabled={mrSaving}
            >
              {mrSaving ? 'Saving…' : 'Save Multi-Region Settings'}
            </button>
            <span className="admin-settings-note--inline">
              Changes take effect after API pod restart.
            </span>
          </div>
        </div>
      </SettingsSection>

      {/* ── Node Logs ── */}
      <SettingsSection title="PF9 Node Logs">
        <div className="admin-settings-grid">
          <div className="admin-settings-item">
            <span className="admin-settings-label">Log source</span>
            <code className="admin-settings-code">{config.node_log_source}</code>
          </div>
          <div className="admin-settings-item">
            <span className="admin-settings-label">Configured</span>
            <StatusPill ok={config.node_log_configured} trueLabel="Yes" falseLabel="No" />
          </div>
          <div className="admin-settings-item">
            <span className="admin-settings-label">Cache TTL</span>
            <code className="admin-settings-code">{config.node_log_cache_ttl_s} s</code>
          </div>
        </div>
        <p className="admin-settings-desc">
          Set <code>NODE_LOG_SOURCE=resmgr</code> (PF9 DU API) or <code>NODE_LOG_SOURCE=hostagent</code>
          (direct hostagent port 9080) in your environment. Currently: <strong>{config.node_log_source}</strong>.
          View live logs in the <strong>📋 Node Logs</strong> tab.
        </p>
      </SettingsSection>

    </div>
  );
}
