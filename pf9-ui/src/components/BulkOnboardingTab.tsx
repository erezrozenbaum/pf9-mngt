import React, { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE } from "../config";
import "../styles/BulkOnboardingTab.css";

/* =========================================================================
   BulkOnboardingTab — Bulk Customer Onboarding Workflow
   =========================================================================
   Steps: Upload → Validate → Dry Run → Approve → Execute
   Execution is hard-locked until: approval_status=='approved' AND
   status=='dry_run_passed'
*/

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface OnboardingBatch {
  id: number;
  batch_id: string;
  batch_name: string;
  uploaded_by: string;
  status: string;
  approval_status: string;
  approved_by: string | null;
  approved_at: string | null;
  rejection_comment: string | null;
  total_customers: number;
  total_projects: number;
  total_networks: number;
  total_users: number;
  validation_errors: ValidationError[];
  dry_run_result: DryRunResult | null;
  execution_result: Record<string, any> | null;
  created_at: string;
  updated_at: string;
}

interface ValidationError {
  sheet: string;
  row: number;
  field: string;
  message: string;
}

interface DryRunItem {
  resource_type: string;
  name: string;
  action: "create" | "skip";
  reason: string;
}

interface DryRunResult {
  summary: {
    total_would_create: number;
    total_would_skip: number;
    conflicts: Array<{ resource_type: string; name: string; reason: string }>;
  };
  items: DryRunItem[];
  error?: string;
}

interface BatchDetail extends OnboardingBatch {
  customers: ResourceRow[];
  projects: ResourceRow[];
  networks: ResourceRow[];
  users: ResourceRow[];
}

interface ResourceRow {
  id: number;
  status: string;
  error_msg: string | null;
  [key: string]: any;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getToken(): string | null {
  return localStorage.getItem("auth_token");
}

async function apiFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(opts?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return iso!; }
}

function statusBadge(status: string): React.ReactNode {
  const map: Record<string, string> = {
    validating: "ob-badge yellow",
    validated: "ob-badge green",
    invalid: "ob-badge red",
    pending_approval: "ob-badge yellow",
    approved: "ob-badge green",
    rejected: "ob-badge red",
    dry_run_pending: "ob-badge yellow",
    dry_run_passed: "ob-badge green",
    dry_run_failed: "ob-badge red",
    executing: "ob-badge blue",
    complete: "ob-badge green",
    partially_failed: "ob-badge orange",
    not_submitted: "ob-badge grey",
    created: "ob-badge green",
    skipped: "ob-badge grey",
    failed: "ob-badge red",
    pending: "ob-badge yellow",
  };
  return <span className={map[status] || "ob-badge grey"}>{status.replace(/_/g, " ")}</span>;
}

const STEPS = ["Upload", "Validate", "Dry Run", "Approve", "Execute", "Done"];

function currentStep(batch: OnboardingBatch): number {
  const s = batch.status;
  const a = batch.approval_status;
  if (s === "complete") return 5;
  if (s === "executing" || s === "partially_failed") return 4;
  if (s === "dry_run_passed" && a === "approved") return 4;
  if (a === "approved" || a === "rejected") return 3;
  if (a === "pending_approval") return 3;
  if (s === "dry_run_passed" || s === "dry_run_failed" || s === "dry_run_pending") return 2;
  if (s === "validated" || s === "invalid") return 1;
  return 0;
}

// ---------------------------------------------------------------------------
// StepBar
// ---------------------------------------------------------------------------
function StepBar({ step }: { step: number }) {
  return (
    <div className="ob-stepbar">
      {STEPS.map((label, i) => (
        <React.Fragment key={i}>
          <div className={`ob-step ${i < step ? "done" : i === step ? "active" : ""}`}>
            <div className="ob-step-circle">{i < step ? "✓" : i + 1}</div>
            <div className="ob-step-label">{label}</div>
          </div>
          {i < STEPS.length - 1 && (
            <div className={`ob-step-line ${i < step ? "done" : ""}`} />
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------
interface Props {
  onBack?: () => void;
}

export default function BulkOnboardingTab({ onBack }: Props) {
  const [batches, setBatches] = useState<OnboardingBatch[]>([]);
  const [selected, setSelected] = useState<BatchDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: string } | null>(null);
  const [view, setView] = useState<"list" | "detail" | "upload">("list");

  // Upload form state
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Decision modal
  const [decisionBatch, setDecisionBatch] = useState<OnboardingBatch | null>(null);
  const [decision, setDecision] = useState<"approve" | "reject">("approve");
  const [decisionComment, setDecisionComment] = useState("");
  const [deciding, setDeciding] = useState(false);

  // Polling
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const showToast = useCallback((msg: string, type = "info") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 5000);
  }, []);

  const fetchBatches = useCallback(async () => {
    try {
      const data = await apiFetch<OnboardingBatch[]>("/api/onboarding/batches");
      setBatches(data);
    } catch (err: any) {
      showToast(`Failed to load batches: ${err.message}`, "error");
    }
  }, [showToast]);

  const fetchDetail = useCallback(async (batchId: string, quiet = false) => {
    try {
      const data = await apiFetch<BatchDetail>(`/api/onboarding/batches/${batchId}`);
      setSelected(data);
      if (!quiet) setView("detail");
    } catch (err: any) {
      showToast(`Failed to load batch: ${err.message}`, "error");
    }
  }, [showToast]);

  useEffect(() => {
    fetchBatches();
  }, [fetchBatches]);

  // Poll active batch
  useEffect(() => {
    if (selected && (selected.status === "executing" || selected.status === "dry_run_pending")) {
      pollRef.current = setInterval(() => fetchDetail(selected.batch_id, true), 3000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [selected, fetchDetail]);

  // ── Template download ──────────────────────────────────────────────────
  const downloadTemplate = async () => {
    const token = getToken();
    const res = await fetch(`${API_BASE}/api/onboarding/template`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) { showToast("Failed to download template", "error"); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "onboarding_template.xlsx";
    a.click();
    URL.revokeObjectURL(url);
  };

  // ── Upload ─────────────────────────────────────────────────────────────
  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) { showToast("Please select an Excel file", "error"); return; }
    setUploading(true);
    try {
      const token = getToken();
      const form = new FormData();
      form.append("file", uploadFile);
      const url = `${API_BASE}/api/onboarding/upload?batch_name=${encodeURIComponent(uploadName || uploadFile.name)}`;
      const res = await fetch(url, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`${res.status}: ${txt}`);
      }
      const data = await res.json();
      showToast(
        data.validation_errors?.length
          ? `Batch created with ${data.validation_errors.length} validation error(s)`
          : "Batch created and validated successfully ✓",
        data.validation_errors?.length ? "warning" : "success",
      );
      await fetchBatches();
      await fetchDetail(data.batch_id);
      setUploadFile(null);
      setUploadName("");
    } catch (err: any) {
      showToast(`Upload failed: ${err.message}`, "error");
    } finally {
      setUploading(false);
    }
  };

  // ── Dry-run ────────────────────────────────────────────────────────────
  const handleDryRun = async (batchId: string) => {
    setLoading(true);
    try {
      await apiFetch(`/api/onboarding/batches/${batchId}/dry-run`, { method: "POST", body: "{}" });
      showToast("Dry-run started…", "info");
      await fetchDetail(batchId, true);
    } catch (err: any) {
      showToast(`Dry-run failed: ${err.message}`, "error");
    } finally {
      setLoading(false);
    }
  };

  // ── Submit for approval ────────────────────────────────────────────────
  const handleSubmit = async (batchId: string) => {
    try {
      await apiFetch(`/api/onboarding/batches/${batchId}/submit`, { method: "POST", body: "{}" });
      showToast("Submitted for approval", "success");
      await fetchDetail(batchId, true);
      await fetchBatches();
    } catch (err: any) {
      showToast(`Submit failed: ${err.message}`, "error");
    }
  };

  // ── Decision ───────────────────────────────────────────────────────────
  const handleDecision = async () => {
    if (!decisionBatch) return;
    setDeciding(true);
    try {
      await apiFetch(`/api/onboarding/batches/${decisionBatch.batch_id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, comment: decisionComment }),
      });
      showToast(`Batch ${decision}d`, "success");
      setDecisionBatch(null);
      setDecisionComment("");
      await fetchBatches();
      if (selected?.batch_id === decisionBatch.batch_id) await fetchDetail(decisionBatch.batch_id, true);
    } catch (err: any) {
      showToast(`Decision failed: ${err.message}`, "error");
    } finally {
      setDeciding(false);
    }
  };

  // ── Execute ────────────────────────────────────────────────────────────
  const handleExecute = async (batchId: string) => {
    if (!window.confirm("This will create all domains, projects, networks, and users in PCD. Continue?")) return;
    try {
      await apiFetch(`/api/onboarding/batches/${batchId}/execute`, { method: "POST", body: "{}" });
      showToast("Execution started — polling for status…", "info");
      await fetchDetail(batchId, true);
    } catch (err: any) {
      showToast(`Execute failed: ${err.message}`, "error");
    }
  };

  // ── Delete ────────────────────────────────────────────────────────────
  const handleDelete = async (batchId: string, batchName: string) => {
    if (!window.confirm(`Delete batch '${batchName}'? This cannot be undone.`)) return;
    try {
      await fetch(`${API_BASE}/api/onboarding/batches/${batchId}`, {
        method: "DELETE",
        headers: getToken() ? { Authorization: `Bearer ${getToken()!}` } : {},
      });
      showToast("Batch deleted", "info");
      if (selected?.batch_id === batchId) { setSelected(null); setView("list"); }
      await fetchBatches();
    } catch (err: any) {
      showToast(`Delete failed: ${err.message}`, "error");
    }
  };

  // ── Render helpers ────────────────────────────────────────────────────

  const canExecute = (b: OnboardingBatch) =>
    b.approval_status === "approved" && b.status === "dry_run_passed";

  const canDryRun = (b: OnboardingBatch) =>
    ["validated", "dry_run_failed", "dry_run_passed"].includes(b.status);

  const canSubmit = (b: OnboardingBatch) =>
    b.status !== "invalid" &&
    b.status !== "executing" &&
    b.status !== "complete" &&
    b.approval_status === "not_submitted";

  // ── Dry-run results panel ──────────────────────────────────────────────
  const renderDryRunResult = (result: DryRunResult) => {
    if (result.error) {
      return <div className="ob-alert error">PCD connection error: {result.error}</div>;
    }
    const { summary, items } = result;
    const creates = items.filter((i) => i.action === "create");
    const skips = items.filter((i) => i.action === "skip");
    return (
      <div className="ob-dryrun">
        <div className="ob-dryrun-summary">
          <div className="ob-dryrun-stat green">
            <strong>{summary.total_would_create}</strong>
            <span>Would Create</span>
          </div>
          <div className="ob-dryrun-stat orange">
            <strong>{summary.total_would_skip}</strong>
            <span>Already Exist (conflicts)</span>
          </div>
        </div>
        {summary.conflicts.length > 0 && (
          <div className="ob-alert warning">
            <strong>⚠ {summary.conflicts.length} conflict(s) must be resolved before execution:</strong>
            <ul>
              {summary.conflicts.map((c, i) => (
                <li key={i}><code>{c.resource_type}: {c.name}</code> — {c.reason}</li>
              ))}
            </ul>
          </div>
        )}
        {creates.length > 0 && (
          <details open>
            <summary className="ob-detail-summary">✅ Resources to Create ({creates.length})</summary>
            <table className="ob-table small">
              <thead><tr><th>Type</th><th>Name</th></tr></thead>
              <tbody>
                {creates.map((r, i) => (
                  <tr key={i}><td><span className="ob-type-badge">{r.resource_type}</span></td><td>{r.name}</td></tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
        {skips.length > 0 && (
          <details>
            <summary className="ob-detail-summary">⚠ Resources that Already Exist ({skips.length})</summary>
            <table className="ob-table small">
              <thead><tr><th>Type</th><th>Name</th><th>Reason</th></tr></thead>
              <tbody>
                {skips.map((r, i) => (
                  <tr key={i}>
                    <td><span className="ob-type-badge">{r.resource_type}</span></td>
                    <td>{r.name}</td>
                    <td className="ob-text-muted">{r.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </div>
    );
  };

  // ── Execution results panel ────────────────────────────────────────────
  const renderItemsTable = (
    title: string,
    rows: ResourceRow[],
    keyField: string,
    extraFields: string[],
  ) => {
    if (!rows || rows.length === 0) return null;
    return (
      <details>
        <summary className="ob-detail-summary">{title} ({rows.length})</summary>
        <table className="ob-table small">
          <thead>
            <tr>
              <th>Status</th>
              <th>{keyField}</th>
              {extraFields.map((f) => <th key={f}>{f}</th>)}
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{statusBadge(row.status)}</td>
                <td>{row[keyField]}</td>
                {extraFields.map((f) => <td key={f}>{String(row[f] ?? "—")}</td>)}
                <td className="ob-text-muted">{row.error_msg || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    );
  };

  // ── DETAIL VIEW ────────────────────────────────────────────────────────
  const renderDetail = () => {
    if (!selected) return null;
    const b = selected;
    const step = currentStep(b);
    const executing = b.status === "executing" || b.status === "dry_run_pending";

    return (
      <div className="ob-detail">
        <div className="ob-detail-topbar">
          <button className="ob-btn-back" onClick={() => { setView("list"); setSelected(null); }}>
            ← Back to Batches
          </button>
          <h3 className="ob-detail-title">
            📋 {b.batch_name}
            <span className="ob-detail-id">({b.batch_id.slice(0, 8)}…)</span>
          </h3>
          <div className="ob-detail-badges">
            {statusBadge(b.status)}
            {b.approval_status !== "not_submitted" && statusBadge(b.approval_status)}
          </div>
        </div>

        <StepBar step={step} />

        {/* Meta */}
        <div className="ob-meta-row">
          <span>Uploaded by <strong>{b.uploaded_by}</strong> on {fmtDate(b.created_at)}</span>
          <span>Customers: <strong>{b.total_customers}</strong></span>
          <span>Projects: <strong>{b.total_projects}</strong></span>
          <span>Networks: <strong>{b.total_networks}</strong></span>
          <span>Users: <strong>{b.total_users}</strong></span>
        </div>

        {/* Validation errors */}
        {b.validation_errors && b.validation_errors.length > 0 && (
          <details open className="ob-section">
            <summary className="ob-detail-summary ob-text-red">
              ❌ Validation Errors ({b.validation_errors.length})
            </summary>
            <table className="ob-table small">
              <thead><tr><th>Sheet</th><th>Row</th><th>Field</th><th>Message</th></tr></thead>
              <tbody>
                {b.validation_errors.map((e, i) => (
                  <tr key={i}>
                    <td>{e.sheet}</td>
                    <td>{e.row}</td>
                    <td><code>{e.field}</code></td>
                    <td>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}

        {/* Approval banner */}
        {b.approval_status === "pending_approval" && (
          <div className="ob-alert info">
            ⏳ Awaiting admin approval. Submitted by {b.uploaded_by}.
            <button className="ob-btn primary small ml" onClick={() => { setDecisionBatch(b); setDecision("approve"); }}>
              Approve / Reject
            </button>
          </div>
        )}
        {b.approval_status === "approved" && (
          <div className="ob-alert success">
            ✅ Approved by <strong>{b.approved_by}</strong> on {fmtDate(b.approved_at)}.
          </div>
        )}
        {b.approval_status === "rejected" && (
          <div className="ob-alert error">
            ❌ Rejected by <strong>{b.approved_by}</strong>.
            {b.rejection_comment && <span> Reason: {b.rejection_comment}</span>}
          </div>
        )}

        {/* Dry-run result */}
        {b.dry_run_result && (
          <div className="ob-section">
            <h4>🧪 Dry-Run Result</h4>
            {renderDryRunResult(b.dry_run_result)}
          </div>
        )}

        {/* Execution polling indicator */}
        {executing && (
          <div className="ob-alert info">
            <span className="ob-spinner-inline" /> {b.status === "dry_run_pending" ? "Running dry-run…" : "Executing…"} Polling every 3s.
          </div>
        )}

        {/* Execution result summary */}
        {b.execution_result && !executing && (
          <div className="ob-section">
            <h4>📊 Execution Result</h4>
            <div className="ob-meta-row">
              {b.execution_result.failed_items !== undefined && (
                <span>Failed items: <strong className={b.execution_result.failed_items > 0 ? "ob-text-red" : "ob-text-green"}>
                  {b.execution_result.failed_items}
                </strong></span>
              )}
              {b.execution_result.completed_by && <span>By: <strong>{b.execution_result.completed_by}</strong></span>}
              {b.execution_result.completed_at && <span>At: {fmtDate(b.execution_result.completed_at)}</span>}
              {b.execution_result.error && <span className="ob-text-red">Error: {b.execution_result.error}</span>}
            </div>
          </div>
        )}

        {/* Item tables */}
        <div className="ob-section">
          <h4>📦 Resource Details</h4>
          {renderItemsTable("Customers / Domains", selected.customers, "domain_name", ["display_name", "contact_email", "pcd_domain_id"])}
          {renderItemsTable("Projects", selected.projects, "project_name", ["domain_name", "quota_vcpu", "pcd_project_id"])}
          {renderItemsTable("Networks", selected.networks, "network_name", ["domain_name", "project_name", "cidr", "pcd_network_id"])}
          {renderItemsTable("Users", selected.users, "username", ["domain_name", "project_name", "role", "email", "pcd_user_id"])}
        </div>

        {/* Action bar */}
        <div className="ob-action-bar">
          {canDryRun(b) && (
            <button className="ob-btn secondary" disabled={loading || executing} onClick={() => handleDryRun(b.batch_id)}>
              🧪 Run Dry-Run
            </button>
          )}
          {canSubmit(b) && (
            <button className="ob-btn primary" disabled={executing} onClick={() => handleSubmit(b.batch_id)}>
              📨 Submit for Approval
            </button>
          )}
          {b.approval_status === "pending_approval" && (
            <button className="ob-btn primary" onClick={() => { setDecisionBatch(b); setDecision("approve"); }}>
              ⚖ Approve / Reject
            </button>
          )}
          {canExecute(b) && (
            <button className="ob-btn execute" disabled={executing} onClick={() => handleExecute(b.batch_id)}>
              🚀 Execute Onboarding
            </button>
          )}
          {!canExecute(b) && b.approval_status !== "pending_approval" && b.status !== "executing" && (
            <span className="ob-lock-hint">
              {b.approval_status !== "approved" ? "🔒 Execution locked — approval required" :
               b.status !== "dry_run_passed" ? "🔒 Execution locked — dry-run must pass first" : ""}
            </span>
          )}
          <button
            className="ob-btn danger small"
            disabled={executing}
            onClick={() => handleDelete(b.batch_id, b.batch_name)}
          >
            🗑 Delete
          </button>
        </div>
      </div>
    );
  };

  // ── UPLOAD VIEW ─────────────────────────────────────────────────────────
  const renderUpload = () => (
    <div className="ob-upload-panel">
      <div className="ob-detail-topbar">
        <button className="ob-btn-back" onClick={() => setView("list")}>← Back to Batches</button>
        <h3>📤 Upload Onboarding Batch</h3>
      </div>
      <div className="ob-upload-steps-hint">
        <div className="ob-hint-step">1. Download the template below</div>
        <div className="ob-hint-step">2. Fill in customers, projects, networks, and users sheets</div>
        <div className="ob-hint-step">3. Upload the filled file</div>
        <div className="ob-hint-step">4. Review validation, run dry-run, get approval, execute</div>
      </div>
      <button className="ob-btn secondary" onClick={downloadTemplate}>
        ⬇ Download Excel Template
      </button>
      <hr className="ob-divider" />
      <form className="ob-upload-form" onSubmit={handleUpload}>
        <label className="ob-label">Batch Name (optional)</label>
        <input
          className="ob-input"
          type="text"
          placeholder="e.g. Q2-2025 Customer Onboarding"
          value={uploadName}
          onChange={(e) => setUploadName(e.target.value)}
        />
        <label className="ob-label">Excel File <span className="ob-required">*</span></label>
        <div
          className="ob-dropzone"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files[0];
            if (f) setUploadFile(f);
          }}
        >
          {uploadFile ? (
            <span>📄 {uploadFile.name} ({(uploadFile.size / 1024).toFixed(1)} KB)</span>
          ) : (
            <span>Click to select or drag & drop an .xlsx file here</span>
          )}
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls"
          style={{ display: "none" }}
          onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
        />
        <button className="ob-btn primary" type="submit" disabled={uploading || !uploadFile}>
          {uploading ? "Uploading…" : "📤 Upload & Validate"}
        </button>
      </form>
    </div>
  );

  // ── LIST VIEW ──────────────────────────────────────────────────────────
  const renderList = () => (
    <div className="ob-list-panel">
      <div className="ob-list-header">
        <div>
          <h3>📋 Onboarding Batches</h3>
          <p className="ob-subtitle">Bulk-create customers, projects, networks and users from a filled Excel template.</p>
        </div>
        <div className="ob-list-actions">
          <button className="ob-btn secondary" onClick={downloadTemplate}>⬇ Template</button>
          <button className="ob-btn primary" onClick={() => setView("upload")}>+ New Batch</button>
        </div>
      </div>

      {batches.length === 0 ? (
        <div className="ob-empty">
          <div className="ob-empty-icon">📭</div>
          <p>No onboarding batches yet.</p>
          <button className="ob-btn primary" onClick={() => setView("upload")}>Upload Your First Batch</button>
        </div>
      ) : (
        <table className="ob-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Approval</th>
              <th>Customers</th>
              <th>Projects</th>
              <th>Networks</th>
              <th>Users</th>
              <th>Uploaded By</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.batch_id} className="ob-table-row">
                <td>
                  <button className="ob-link" onClick={() => fetchDetail(b.batch_id)}>
                    {b.batch_name}
                  </button>
                </td>
                <td>{statusBadge(b.status)}</td>
                <td>{statusBadge(b.approval_status)}</td>
                <td>{b.total_customers}</td>
                <td>{b.total_projects}</td>
                <td>{b.total_networks}</td>
                <td>{b.total_users}</td>
                <td>{b.uploaded_by}</td>
                <td>{fmtDate(b.created_at)}</td>
                <td>
                  <div className="ob-row-actions">
                    <button className="ob-btn-icon" title="View" onClick={() => fetchDetail(b.batch_id)}>🔍</button>
                    {b.approval_status === "pending_approval" && (
                      <button className="ob-btn-icon" title="Approve/Reject"
                        onClick={() => { setDecisionBatch(b); setDecision("approve"); }}>⚖</button>
                    )}
                    <button className="ob-btn-icon danger" title="Delete"
                      disabled={b.status === "executing"}
                      onClick={() => handleDelete(b.batch_id, b.batch_name)}>🗑</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );

  // ┌── DECISION MODAL ────────────────────────────────────────────────────┐
  const renderDecisionModal = () => {
    if (!decisionBatch) return null;
    return (
      <div className="ob-modal-overlay" onClick={() => setDecisionBatch(null)}>
        <div className="ob-modal" onClick={(e) => e.stopPropagation()}>
          <h3>⚖ Approval Decision</h3>
          <p>Batch: <strong>{decisionBatch.batch_name}</strong></p>
          <div className="ob-radio-group">
            <label>
              <input type="radio" name="decision" value="approve" checked={decision === "approve"}
                onChange={() => setDecision("approve")} /> ✅ Approve
            </label>
            <label>
              <input type="radio" name="decision" value="reject" checked={decision === "reject"}
                onChange={() => setDecision("reject")} /> ❌ Reject
            </label>
          </div>
          <label className="ob-label">Comment (optional)</label>
          <textarea
            className="ob-textarea"
            rows={3}
            value={decisionComment}
            onChange={(e) => setDecisionComment(e.target.value)}
            placeholder="Add a note for the submitter…"
          />
          <div className="ob-modal-actions">
            <button className="ob-btn secondary" onClick={() => setDecisionBatch(null)} disabled={deciding}>Cancel</button>
            <button
              className={`ob-btn ${decision === "approve" ? "primary" : "danger"}`}
              onClick={handleDecision}
              disabled={deciding}
            >
              {deciding ? "Saving…" : decision === "approve" ? "✅ Approve" : "❌ Reject"}
            </button>
          </div>
        </div>
      </div>
    );
  };

  // ── Main render ────────────────────────────────────────────────────────
  return (
    <div className="ob-container">
      {/* Back to Runbooks header */}
      <div className="ob-topbar">
        {onBack && (
          <button className="ob-btn-back" onClick={onBack}>← Back to Runbooks</button>
        )}
        <h2>📦 Bulk Customer Onboarding</h2>
      </div>

      {/* Toast */}
      {toast && (
        <div className={`ob-toast ${toast.type}`}>{toast.msg}</div>
      )}

      {/* Content */}
      {view === "list" && renderList()}
      {view === "upload" && renderUpload()}
      {view === "detail" && selected && renderDetail()}

      {/* Decision modal */}
      {renderDecisionModal()}
    </div>
  );
}
