/*
 * IntelligenceSettingsPanel.tsx
 * ==============================
 * Admin settings panel for the Operational Intelligence subsystem.
 *
 * Sections:
 *   1. Labor Rates — per-insight-type hours saved + rate per hour (editable table)
 *   2. PSA Webhook Configuration — add / edit / delete / test-fire outbound webhooks
 *   3. Contract Entitlements — CSV import for msp_contract_entitlements
 *
 * Accessible from: InsightsTab (Settings tab — admin/superadmin only)
 */
import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LaborRate {
  insight_type: string;
  hours_saved:  number;
  rate_per_hour:number;
  description:  string | null;
}

interface PsaConfig {
  id:            number;
  psa_name:      string;
  webhook_url:   string;
  min_severity:  string;
  insight_types: string[];
  region_ids:    string[];
  enabled:       boolean;
  created_at:    string;
}

// ---------------------------------------------------------------------------
// Sub-component: Labor Rates table
// ---------------------------------------------------------------------------

function LaborRatesSection() {
  const [rates, setRates]     = useState<LaborRate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");
  const [editingType, setEditingType] = useState<string | null>(null);
  const [editHours, setEditHours]     = useState("");
  const [editRate,  setEditRate]      = useState("");
  const [editDesc,  setEditDesc]      = useState("");
  const [saving,    setSaving]        = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch<{ rates: LaborRate[] }>("/api/intelligence/qbr/labor-rates");
      setRates(data.rates);
    } catch (e: any) {
      setError(e.message || "Failed to load labor rates");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function startEdit(r: LaborRate) {
    setEditingType(r.insight_type);
    setEditHours(String(r.hours_saved));
    setEditRate(String(r.rate_per_hour));
    setEditDesc(r.description || "");
  }

  function cancelEdit() {
    setEditingType(null);
  }

  async function saveRate() {
    if (!editingType) return;
    setSaving(true);
    try {
      await apiFetch(`/api/intelligence/qbr/labor-rates/${encodeURIComponent(editingType)}`, {
        method: "PUT",
        body: JSON.stringify({
          hours_saved:   parseFloat(editHours) || 0,
          rate_per_hour: parseFloat(editRate)  || 0,
          description:   editDesc || null,
        }),
      });
      setEditingType(null);
      await load();
    } catch (e: any) {
      setError(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="intel-settings-section">
      <h3 className="intel-settings-section-title">Labor Rates</h3>
      <p className="intel-settings-section-hint">
        Per-insight-type hours saved and billed rate. These values drive the ROI figures
        in the Business Review PDF.
      </p>
      {error && <div className="intel-settings-error">{error}</div>}
      {loading ? (
        <div className="intel-settings-loading">Loading…</div>
      ) : (
        <table className="intel-settings-table">
          <thead>
            <tr>
              <th>Insight Type</th>
              <th>Hours Saved</th>
              <th>Rate / hr ($)</th>
              <th>Description</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rates.map((r) =>
              editingType === r.insight_type ? (
                <tr key={r.insight_type} className="intel-settings-row-editing">
                  <td><strong>{r.insight_type}</strong></td>
                  <td>
                    <input
                      type="number" min="0" max="999" step="0.25"
                      className="intel-settings-input"
                      value={editHours}
                      onChange={(e) => setEditHours(e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number" min="0" max="99999" step="1"
                      className="intel-settings-input"
                      value={editRate}
                      onChange={(e) => setEditRate(e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="text" maxLength={200}
                      className="intel-settings-input intel-settings-input-wide"
                      value={editDesc}
                      onChange={(e) => setEditDesc(e.target.value)}
                    />
                  </td>
                  <td className="intel-settings-actions">
                    <button className="btn-sm primary" onClick={saveRate} disabled={saving}>
                      {saving ? "Saving…" : "Save"}
                    </button>
                    <button className="btn-sm" onClick={cancelEdit}>Cancel</button>
                  </td>
                </tr>
              ) : (
                <tr key={r.insight_type}>
                  <td>{r.insight_type}</td>
                  <td>{r.hours_saved.toFixed(2)}</td>
                  <td>${r.rate_per_hour.toFixed(2)}</td>
                  <td className="intel-settings-desc">{r.description || "—"}</td>
                  <td>
                    <button className="btn-sm" onClick={() => startEdit(r)}>Edit</button>
                  </td>
                </tr>
              )
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: PSA Webhook Configuration
// ---------------------------------------------------------------------------

const EMPTY_PSA: Omit<PsaConfig, "id" | "created_at"> & { auth_header: string } = {
  psa_name:      "",
  webhook_url:   "",
  auth_header:   "",
  min_severity:  "high",
  insight_types: [],
  region_ids:    [],
  enabled:       true,
};

function PsaSection() {
  const [configs,    setConfigs]    = useState<PsaConfig[]>([]);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState("");
  const [form,       setForm]       = useState<typeof EMPTY_PSA | null>(null);
  const [editId,     setEditId]     = useState<number | null>(null);
  const [saving,     setSaving]     = useState(false);
  const [testStatus, setTestStatus] = useState<Record<number, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch<{ configs: PsaConfig[] }>("/api/psa/configs");
      setConfigs(data.configs);
    } catch (e: any) {
      setError(e.message || "Failed to load PSA configs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function openNew() {
    setEditId(null);
    setForm({ ...EMPTY_PSA });
  }

  function openEdit(cfg: PsaConfig) {
    setEditId(cfg.id);
    setForm({
      psa_name:      cfg.psa_name,
      webhook_url:   cfg.webhook_url,
      auth_header:   "",     // never pre-fill — require re-entry on edit
      min_severity:  cfg.min_severity,
      insight_types: cfg.insight_types,
      region_ids:    cfg.region_ids,
      enabled:       cfg.enabled,
    });
  }

  function closeForm() {
    setForm(null);
    setEditId(null);
    setError("");
  }

  async function saveConfig() {
    if (!form) return;
    if (!form.psa_name || !form.webhook_url || !form.auth_header) {
      setError("Name, URL, and auth header are required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (editId !== null) {
        await apiFetch(`/api/psa/configs/${editId}`, {
          method: "PUT",
          body: JSON.stringify(form),
        });
      } else {
        await apiFetch("/api/psa/configs", {
          method: "POST",
          body: JSON.stringify(form),
        });
      }
      closeForm();
      await load();
    } catch (e: any) {
      setError(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function deleteConfig(id: number) {
    if (!window.confirm("Delete this PSA webhook configuration?")) return;
    try {
      await apiFetch(`/api/psa/configs/${id}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      setError(e.message || "Delete failed");
    }
  }

  async function testFire(id: number) {
    setTestStatus((s) => ({ ...s, [id]: "firing…" }));
    try {
      const r = await apiFetch<{ success: boolean; http_status: number | null }>(
        `/api/psa/configs/${id}/test-fire`,
        { method: "POST" },
      );
      setTestStatus((s) => ({
        ...s,
        [id]: r.success
          ? `✅ OK (HTTP ${r.http_status})`
          : `❌ Failed (HTTP ${r.http_status ?? "??"})`,
      }));
    } catch (e: any) {
      setTestStatus((s) => ({ ...s, [id]: `❌ ${e.message}` }));
    }
  }

  return (
    <div className="intel-settings-section">
      <h3 className="intel-settings-section-title">PSA Webhook Configuration</h3>
      <p className="intel-settings-section-hint">
        Configure outbound webhooks that fire when a high or critical insight is detected.
        The auth header is encrypted at rest.
      </p>
      {error && <div className="intel-settings-error">{error}</div>}

      <button className="btn-sm primary" style={{ marginBottom: "0.75rem" }} onClick={openNew}>
        + Add Webhook
      </button>

      {loading ? (
        <div className="intel-settings-loading">Loading…</div>
      ) : configs.length === 0 ? (
        <div className="intel-settings-empty">No webhooks configured.</div>
      ) : (
        <table className="intel-settings-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>URL</th>
              <th>Min Severity</th>
              <th>Enabled</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {configs.map((cfg) => (
              <tr key={cfg.id}>
                <td>{cfg.psa_name}</td>
                <td className="intel-settings-url">{cfg.webhook_url}</td>
                <td>{cfg.min_severity}</td>
                <td>{cfg.enabled ? "✅" : "⛔"}</td>
                <td className="intel-settings-actions">
                  <button className="btn-sm" onClick={() => openEdit(cfg)}>Edit</button>
                  <button className="btn-sm danger" onClick={() => deleteConfig(cfg.id)}>Delete</button>
                  <button className="btn-sm" onClick={() => testFire(cfg.id)}>Test</button>
                  {testStatus[cfg.id] && (
                    <span className="intel-settings-test-result">{testStatus[cfg.id]}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {form !== null && (
        <div className="intel-settings-modal-overlay" onClick={closeForm}>
          <div className="intel-settings-modal" onClick={(e) => e.stopPropagation()}>
            <h4>{editId !== null ? "Edit Webhook" : "New Webhook"}</h4>
            {error && <div className="intel-settings-error">{error}</div>}
            <label>Name<br />
              <input className="intel-settings-input intel-settings-input-wide"
                value={form.psa_name}
                onChange={(e) => setForm({ ...form, psa_name: e.target.value })}
                maxLength={120}
              />
            </label>
            <label>Webhook URL<br />
              <input className="intel-settings-input intel-settings-input-wide"
                type="url" value={form.webhook_url}
                onChange={(e) => setForm({ ...form, webhook_url: e.target.value })}
                maxLength={2048}
                placeholder="https://hooks.example.com/…"
              />
            </label>
            <label>
              Auth Header <span className="intel-settings-hint-inline">
                {editId !== null ? "(re-enter to update)" : "e.g. Bearer token123 or X-Token: mytoken"}
              </span><br />
              <input className="intel-settings-input intel-settings-input-wide"
                type="password" value={form.auth_header}
                onChange={(e) => setForm({ ...form, auth_header: e.target.value })}
                maxLength={2048}
                autoComplete="new-password"
              />
            </label>
            <label>Min Severity<br />
              <select className="intel-settings-select"
                value={form.min_severity}
                onChange={(e) => setForm({ ...form, min_severity: e.target.value })}
              >
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="critical">critical</option>
              </select>
            </label>
            <label>
              <input type="checkbox" checked={form.enabled}
                onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
              {" "}Enabled
            </label>
            <div className="intel-settings-modal-actions">
              <button className="btn-sm primary" onClick={saveConfig} disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </button>
              <button className="btn-sm" onClick={closeForm}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Contract Entitlements CSV import
// ---------------------------------------------------------------------------

const CSV_TEMPLATE_HEADER = "tenant_id,sku_name,resource,contracted,region_id,billing_id,effective_from";
const CSV_TEMPLATE_EXAMPLE = [
  "proj-acme,Enterprise Bundle,vcpu,40,,CUST-0042,2026-01-01",
  "proj-acme,Enterprise Bundle,ram_gb,160,,CUST-0042,2026-01-01",
  "proj-acme,Enterprise Bundle,storage_gb,2000,,CUST-0042,2026-01-01",
  "proj-initech,Standard,vcpu,20,us-east,CUST-0099,2026-01-01",
].join("\n");

function downloadCsvTemplate() {
  const content = `${CSV_TEMPLATE_HEADER}\n${CSV_TEMPLATE_EXAMPLE}\n`;
  const blob = new Blob([content], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = "contract_entitlements_template.csv";
  a.click();
  URL.revokeObjectURL(url);
}

function EntitlementsSection() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [status,  setStatus]  = useState("");
  const [error,   setError]   = useState("");
  const [uploading, setUploading] = useState(false);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.endsWith(".csv")) {
      setError("Please upload a CSV file (.csv)");
      return;
    }
    setUploading(true);
    setError("");
    setStatus("");
    try {
      const text = await file.text();
      const rows = text.trim().split("\n").slice(1); // skip header
      let ok = 0;
      let fail = 0;
      for (const line of rows) {
        const cols = line.split(",").map((c) => c.trim().replace(/^"|"$/g, ""));
        // CSV columns: tenant_id, sku_name, resource, contracted, region_id, billing_id, effective_from
        if (cols.length < 4) { fail++; continue; }
        const [tenant_id, sku_name, resource, contracted, region_id, billing_id, effective_from] = cols;
        try {
          await apiFetch("/api/psa/entitlements", {
            method: "POST",
            body: JSON.stringify({
              tenant_id,
              sku_name:       sku_name || "",
              resource,
              contracted:     parseInt(contracted, 10),
              region_id:      region_id || null,
              billing_id:     billing_id || null,
              effective_from: effective_from || new Date().toISOString().slice(0, 10),
            }),
          });
          ok++;
        } catch {
          fail++;
        }
      }
      setStatus(`Imported ${ok} row(s)${fail > 0 ? `, ${fail} failed` : ""}.`);
    } catch (e: any) {
      setError(e.message || "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="intel-settings-section">
      <h3 className="intel-settings-section-title">Contract Entitlements</h3>

      {/* What are contract entitlements? */}
      <div className="intel-settings-explainer">
        <p>
          <strong>What is this?</strong> Contract entitlements record what each tenant is
          contractually paying for — their purchased vCPUs, RAM, storage, and floating IPs.
          This is separate from the platform quota (what the system <em>allows</em> them to use).
        </p>
        <p>
          <strong>Why configure it?</strong> The{" "}
          <strong>Revenue Leakage engine</strong> compares the tenant's actual usage against
          their contracted limits every 15 minutes. It generates two types of insights:
        </p>
        <ul className="intel-settings-explainer-list">
          <li>
            <span className="sev-badge sev-medium">medium</span>{" "}
            <strong>Over-consumption</strong> — tenant is using more than their contracted limit
            (upsell signal: charge them for the overage or upgrade their tier)
          </li>
          <li>
            <span className="sev-badge sev-high">high</span>{" "}
            <strong>Ghost resources</strong> — tenant has active resources but no billing contract
            on record (billing gap: you are providing service with no contract)
          </li>
        </ul>
        <p style={{ marginTop: "0.5rem" }}>
          <strong>Incremental adoption:</strong> Configure your largest clients first.
          Tenants without any entitlement rows are skipped by the engine until you add them.
          A <code>region_id</code> of blank/empty means the entitlement applies globally
          across all regions; add per-region rows only when a client's contract differs by region.
        </p>
      </div>

      {/* Column reference */}
      <div className="intel-settings-csv-spec">
        <strong>CSV column reference:</strong>
        <table className="intel-settings-table intel-settings-table-compact">
          <thead>
            <tr><th>Column</th><th>Required</th><th>Values / Notes</th></tr>
          </thead>
          <tbody>
            <tr><td><code>tenant_id</code></td><td>✔</td><td>Project ID (e.g. <code>proj-acme</code>)</td></tr>
            <tr><td><code>sku_name</code></td><td>✔</td><td>Contract name shown in QBR (e.g. <em>Enterprise Bundle</em>)</td></tr>
            <tr><td><code>resource</code></td><td>✔</td><td><code>vcpu</code> · <code>ram_gb</code> · <code>storage_gb</code> · <code>floating_ip</code></td></tr>
            <tr><td><code>contracted</code></td><td>✔</td><td>Integer — units contracted (e.g. <code>40</code> vCPUs)</td></tr>
            <tr><td><code>region_id</code></td><td>—</td><td>Leave blank for global; set to region ID for per-region override</td></tr>
            <tr><td><code>billing_id</code></td><td>—</td><td>External billing/CRM reference (shown in leakage insights)</td></tr>
            <tr><td><code>effective_from</code></td><td>—</td><td>YYYY-MM-DD (defaults to today)</td></tr>
          </tbody>
        </table>
      </div>

      <div className="intel-settings-upload-row">
        <button className="btn-sm" onClick={downloadCsvTemplate} title="Download a pre-filled CSV template">
          ⬇ Download template
        </button>
        <label className="btn-sm primary intel-settings-upload-label" style={{ cursor: "pointer" }}>
          {uploading ? "Importing…" : "⬆ Import CSV"}
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            onChange={handleUpload}
            disabled={uploading}
            style={{ display: "none" }}
          />
        </label>
      </div>
      {status && <div className="intel-settings-success" style={{ marginTop: "0.5rem" }}>{status}</div>}
      {error  && <div className="intel-settings-error"  style={{ marginTop: "0.5rem" }}>{error}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface IntelligenceSettingsPanelProps {
  userRole?: string;
}

type SettingsTab = "rates" | "psa" | "entitlements";

export default function IntelligenceSettingsPanel({ userRole }: IntelligenceSettingsPanelProps) {
  const isAdmin = userRole === "admin" || userRole === "superadmin";
  const [tab, setTab] = useState<SettingsTab>("rates");

  if (!isAdmin) {
    return (
      <div className="intel-settings-panel">
        <div className="intel-settings-unauthorized">
          Settings are only accessible to administrators.
        </div>
      </div>
    );
  }

  return (
    <div className="intel-settings-panel">
      <h2 className="intel-settings-title">⚙️ Intelligence Settings</h2>

      <div className="intel-settings-tabs">
        {(
          [
            { id: "rates" as const,        label: "💰 Labor Rates" },
            { id: "psa" as const,          label: "🔗 PSA Webhooks" },
            { id: "entitlements" as const, label: "📄 Contract Entitlements" },
          ] as { id: SettingsTab; label: string }[]
        ).map((t) => (
          <button
            key={t.id}
            className={`intel-settings-tab${tab === t.id ? " active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "rates"        && <LaborRatesSection />}
      {tab === "psa"          && <PsaSection />}
      {tab === "entitlements" && <EntitlementsSection />}
    </div>
  );
}
