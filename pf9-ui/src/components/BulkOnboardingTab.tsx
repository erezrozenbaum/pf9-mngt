import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch, authHeaders } from '../lib/api';
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
  execution_log: Array<{ ts: string; level: string; msg: string }>;
  rerun_count: number;
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

function getCurrentUser(): { username: string; role: string } | null {
  try {
    const raw = localStorage.getItem("auth_user");
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function isAdminUser(): boolean {
  const u = getCurrentUser();
  return u?.role === "admin" || u?.role === "superadmin";
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
  if (s === "complete") return 6;   // past last index → all steps green
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
  const [notifSending, setNotifSending] = useState(false);
  const [notifSent, setNotifSent] = useState(false);
  const [selectedNotifIds, setSelectedNotifIds] = useState<Set<number> | null>(null);
  const [extraRecipients, setExtraRecipients] = useState("");
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

  // Poll active batch — also poll during pending_approval so Execute appears automatically when admin approves
  useEffect(() => {
    const needsPoll = selected && (
      selected.status === "executing" ||
      selected.status === "dry_run_pending" ||
      selected.approval_status === "pending_approval"
    );
    if (needsPoll) {
      pollRef.current = setInterval(() => fetchDetail(selected!.batch_id, true), 5000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [selected, fetchDetail]);

  // ── Send welcome notifications ────────────────────────────────────────
  const handleSendNotifications = async (
    batchId: string,
    userIds: number[],
    extras: string,
  ) => {
    const extraList = extras.split(/[,\n]/).map(s => s.trim()).filter(Boolean);
    const total = userIds.length + extraList.length;
    if (total === 0) { showToast("Select at least one recipient.", "error"); return; }
    if (!window.confirm(`Send welcome emails to ${total} recipient(s)?`)) return;
    setNotifSending(true);
    try {
      const body = JSON.stringify({ user_ids: userIds, extra_recipients: extraList });
      const res: any = await apiFetch(`/api/onboarding/batches/${batchId}/send-notifications`, { method: "POST", body });
      const sent = res.sent ?? 0;
      const skipped = res.skipped ?? 0;
      showToast(`✅ Welcome emails sent: ${sent} delivered, ${skipped} skipped.`, "success");
      setNotifSent(true);
    } catch (err: any) {
      showToast(`Failed to send notifications: ${err.message}`, "error");
    } finally {
      setNotifSending(false);
    }
  };

  // ── Rerun failed items ───────────────────────────────────────────────
  const handleRerun = async (batchId: string) => {
    if (!window.confirm("This will reset all failed items and rerun execution. Already-created items are skipped. Continue?")) return;
    try {
      await apiFetch(`/api/onboarding/batches/${batchId}/rerun`, { method: "POST", body: "{}" });
      showToast("🔄 Rerun started — polling for status…", "info");
      await fetchDetail(batchId, true);
      await fetchBatches();
    } catch (err: any) {
      showToast(`Rerun failed: ${err.message}`, "error");
    }
  };

  // ── Template download ──────────────────────────────────────────────────
  const downloadTemplate = async () => {
    const res = await fetch(`/api/onboarding/template`, {
      headers: authHeaders(),
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
      const form = new FormData();
      form.append("file", uploadFile);
      const data = await apiFetch<any>(`/api/onboarding/upload?batch_name=${encodeURIComponent(uploadName || uploadFile.name)}`, {
        method: "POST",
        body: form,
      });
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
      await apiFetch(`/api/onboarding/batches/${batchId}`, {
        method: "DELETE",
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
    fieldLabels: Record<string, string> = {},
  ) => {
    if (!rows || rows.length === 0) return null;
    const label = (f: string) => fieldLabels[f] ?? f.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    return (
      <details open>
        <summary className="ob-detail-summary">{title} ({rows.length})</summary>
        <div className="ob-table-wrap">
          <table className="ob-table small">
            <thead>
              <tr>
                <th>Status</th>
                <th>{label(keyField)}</th>
                {extraFields.map((f) => <th key={f}>{label(f)}</th>)}
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr className="ob-table-row" key={row.id}>
                  <td>{statusBadge(row.status)}</td>
                  <td>{row[keyField]}</td>
                  {extraFields.map((f) => <td key={f}>{String(row[f] ?? "—")}</td>)}
                  <td className="ob-text-muted">{row.error_msg || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
              {b.rerun_count > 0 && <span className="ob-badge yellow">Rerun #{b.rerun_count}</span>}
            </div>
          </div>
        )}

        {/* Completion summary */}
        {b.execution_result && !executing && (b.status === "complete" || b.status === "partially_failed") && (
          <div className="ob-section">
            <h4>🎉 Completion Summary</h4>
            <div className="ob-summary-cards">
              {([
                { label: "Domains",  rows: b.customers ?? [] },
                { label: "Projects", rows: b.projects ?? [] },
                { label: "Networks", rows: b.networks ?? [] },
                { label: "Users",    rows: b.users ?? [] },
              ] as { label: string; rows: ResourceRow[] }[]).map(({ label, rows }) => {
                const created = rows.filter(r => r.status === "created").length;
                const failed  = rows.filter(r => r.status === "failed").length;
                return (
                  <div key={label} className={`ob-summary-card ${failed > 0 ? "partial" : "success"}`}>
                    <div className="ob-summary-card-count">{created}</div>
                    <div className="ob-summary-card-label">{label} Created</div>
                    {failed > 0 && <div className="ob-summary-card-failed">⚠ {failed} failed</div>}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Execution log */}
        {b.execution_log && b.execution_log.length > 0 && (
          <details className="ob-section ob-log-details" open={b.status === "complete" || b.status === "partially_failed"}>
            <summary className="ob-log-summary">📋 Execution Log ({b.execution_log.length} entries)</summary>
            <div className="ob-log-body">
              {b.execution_log.map((entry, i) => (
                <div key={i} className={`ob-log-line ob-log-${entry.level}`}>
                  <span className="ob-log-ts">{new Date(entry.ts).toLocaleTimeString()}</span>
                  <span className="ob-log-msg">{entry.msg}</span>
                </div>
              ))}
            </div>
          </details>
        )}

        {/* Welcome notifications panel */}
        {(b.status === "complete" || b.status === "partially_failed") && selected && (() => {
          const allNotifUsers = selected.users.filter(u => u.status === "created");
          const usersWithEmail = allNotifUsers.filter(u => u.email);
          if (allNotifUsers.length === 0) return null;

          // Initialise selection on first render for this batch
          const initIds = new Set(usersWithEmail.map((u: ResourceRow) => u.id as number));
          const currentSelected: Set<number> = selectedNotifIds === null
            ? initIds
            : selectedNotifIds;

          const toggleUser = (id: number) => {
            setNotifSent(false);
            setSelectedNotifIds(prev => {
              const base = prev === null ? initIds : prev;
              const next = new Set(base);
              next.has(id) ? next.delete(id) : next.add(id);
              return next;
            });
          };
          const selectAll  = () => { setNotifSent(false); setSelectedNotifIds(new Set(initIds)); };
          const selectNone = () => { setNotifSent(false); setSelectedNotifIds(new Set()); };
          const selectedList = usersWithEmail.filter(u => currentSelected.has(u.id as number));
          const extraList = extraRecipients.split(/[,\n]/).map((s: string) => s.trim()).filter(Boolean);
          const totalRecipients = selectedList.length + extraList.length;

          return (
            <div className="ob-section">
              <h4>📧 Welcome Notifications</h4>
              <p className="ob-text-muted" style={{marginBottom:'0.6rem'}}>
                Select which users receive a welcome email with their credentials, and optionally add extra recipients (e.g. managers or CC addresses).
              </p>

              <details className="ob-notif-preview">
                <summary className="ob-detail-summary">📄 Email Template Preview</summary>
                <div className="ob-notif-preview-body">
                  <div className="ob-notif-meta"><strong>Subject:</strong> Welcome to Platform9 — Your Account is Ready</div>
                  <div className="ob-notif-meta"><strong>From:</strong> Platform9 Management &lt;noreply@platform9.com&gt;</div>
                  <div className="ob-notif-meta"><strong>To:</strong> Selected users / extra recipients</div>
                  <hr className="ob-divider" />
                  <p>Dear <em>[Username]</em>,</p>
                  <p>Your Platform9 cloud account has been created and is ready to use. Please find your credentials below:</p>
                  <table className="ob-notif-creds">
                    <tbody>
                      <tr><td>Username</td><td><strong>[username]</strong></td></tr>
                      <tr><td>Temporary Password</td><td><strong>[temp_password]</strong> — please change on first login</td></tr>
                      <tr><td>Domain</td><td>[domain_name]</td></tr>
                      <tr><td>Project</td><td>[project_name]</td></tr>
                      <tr><td>Role</td><td>[role]</td></tr>
                    </tbody>
                  </table>
                  <p style={{marginTop:'1rem',fontSize:'0.85rem',color:'#94a3b8'}}>
                    Extra recipients not linked to a specific user receive a general onboarding summary instead of individual credentials.
                  </p>
                </div>
              </details>

              {/* User selection table */}
              <div className="ob-notif-select-header">
                <span className="ob-text-muted" style={{fontSize:'0.82rem'}}>
                  {currentSelected.size} of {usersWithEmail.length} user(s) selected
                </span>
                <button className="ob-btn-link" onClick={selectAll}>Select All</button>
                <button className="ob-btn-link" onClick={selectNone}>Select None</button>
              </div>
              <div className="ob-table-wrap">
                <table className="ob-table small">
                  <thead>
                    <tr>
                      <th style={{width:32}}></th>
                      <th>Username</th><th>Email</th><th>Domain</th><th>Project</th><th>Role</th>
                    </tr>
                  </thead>
                  <tbody>
                    {allNotifUsers.map((u: ResourceRow) => {
                      const hasEmail = Boolean(u.email);
                      const checked = hasEmail && currentSelected.has(u.id as number);
                      return (
                        <tr key={u.id} className={checked ? "" : "ob-row-dim"}>
                          <td>
                            {hasEmail
                              ? <input type="checkbox" checked={checked} onChange={() => toggleUser(u.id as number)} />
                              : <span title="No email address" style={{color:'#475569',fontSize:'0.75rem'}}>—</span>}
                          </td>
                          <td>{u.username}</td>
                          <td>{u.email || <span className="ob-text-muted">no email</span>}</td>
                          <td>{u.domain_name}</td>
                          <td>{u.project_name}</td>
                          <td>{u.role}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Extra recipients */}
              <div className="ob-notif-extra">
                <label className="ob-label">Additional Recipients (optional)</label>
                <textarea
                  className="ob-input ob-notif-extra-input"
                  rows={3}
                  placeholder={"manager@example.com, cto@company.org\n(one per line or comma-separated)"}
                  value={extraRecipients}
                  onChange={e => { setExtraRecipients(e.target.value); setNotifSent(false); }}
                />
                {extraList.length > 0 && (
                  <p className="ob-text-muted" style={{fontSize:'0.8rem',marginTop:'0.3rem'}}>
                    {extraList.length} extra recipient(s) — will receive a general onboarding summary (not individual credentials)
                  </p>
                )}
              </div>

              <div className="ob-notif-send-row">
                {notifSent ? (
                  <>
                    <span style={{color:'#16a34a', fontWeight:600, fontSize:'0.9rem'}}>✅ Emails sent</span>
                    <button
                      className="ob-btn secondary"
                      disabled={notifSending || totalRecipients === 0}
                      onClick={() => { setNotifSent(false); }}
                    >
                      🔁 Resend
                    </button>
                  </>
                ) : (
                  <button
                    className="ob-btn primary"
                    disabled={notifSending || totalRecipients === 0}
                    onClick={() => handleSendNotifications(
                      b.batch_id,
                      selectedList.map((u: ResourceRow) => u.id as number),
                      extraRecipients,
                    )}
                  >
                    {notifSending ? "⏳ Sending…" : `📤 Send Welcome Emails (${totalRecipients} recipient${totalRecipients !== 1 ? "s" : ""})`}
                  </button>
                )}
                <span className="ob-text-muted" style={{fontSize:'0.8rem'}}>
                  Actions are logged in Admin Tools → System Logs → Activity
                </span>
              </div>
            </div>
          );
        })()}

        {/* Item tables */}
        <div className="ob-section">
          <h4>📦 Resource Details</h4>
          {renderItemsTable("Customers / Domains", selected.customers, "domain_name",
            ["display_name", "contact_email", "pcd_domain_id"],
            { domain_name: "Domain", display_name: "Display Name", contact_email: "Contact Email", pcd_domain_id: "OS Domain ID" })}
          {renderItemsTable("Projects", selected.projects, "project_name",
            ["domain_name", "subscription_id", "quota_vcpu", "quota_ram_mb", "quota_instances", "quota_disk_gb",
             "quota_networks", "quota_subnets", "quota_routers", "quota_volumes", "quota_snapshots", "pcd_project_id"],
            { project_name: "Project", domain_name: "Domain", subscription_id: "Sub ID",
              quota_vcpu: "vCPU", quota_ram_mb: "RAM (MB)", quota_instances: "Instances", quota_disk_gb: "Disk GB",
              quota_networks: "Networks", quota_subnets: "Subnets", quota_routers: "Routers",
              quota_volumes: "Volumes", quota_snapshots: "Snapshots", pcd_project_id: "OS Project ID" })}
          {renderItemsTable("Networks", selected.networks, "network_name",
            ["domain_name", "project_name", "network_kind", "cidr", "vlan_id", "pcd_network_id"],
            { network_name: "Network", domain_name: "Domain", project_name: "Project",
              network_kind: "Kind", cidr: "CIDR", vlan_id: "VLAN", pcd_network_id: "OS Network ID" })}
          {renderItemsTable("Users", selected.users, "username",
            ["domain_name", "project_name", "role", "email", "pcd_user_id"],
            { username: "Username", domain_name: "Domain", project_name: "Project",
              role: "Role", email: "Email", pcd_user_id: "OS User ID" })}
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
          {b.approval_status === "pending_approval" && isAdminUser() && (
            <button className="ob-btn primary" onClick={() => { setDecisionBatch(b); setDecision("approve"); }}>
              ⚖ Approve / Reject
            </button>
          )}
          {b.approval_status === "pending_approval" && !isAdminUser() && (
            <span className="ob-lock-hint ob-waiting">
              <span className="ob-spinner-inline" /> Waiting for admin approval…
            </span>
          )}
          {canExecute(b) && (
            <button className="ob-btn execute" disabled={executing} onClick={() => handleExecute(b.batch_id)}>
              🚀 Execute Onboarding
            </button>
          )}
          {b.status === "partially_failed" && b.approval_status === "approved" && (
            <button className="ob-btn secondary" disabled={executing} onClick={() => handleRerun(b.batch_id)}>
              🔄 Rerun Failed Items
            </button>
          )}
          {!canExecute(b) && b.approval_status !== "pending_approval" && b.status !== "executing" && b.status !== "partially_failed" && (
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
        ↓ Download Excel Template
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
          <button className="ob-btn secondary" onClick={downloadTemplate}>↓ Template</button>
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
                    {b.approval_status === "pending_approval" && isAdminUser() && (
                      <button className="ob-btn primary small"
                        onClick={() => { setDecisionBatch(b); setDecision("approve"); }}>⚖ Approve</button>
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
