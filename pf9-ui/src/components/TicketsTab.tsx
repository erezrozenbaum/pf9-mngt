import React, { useState, useEffect, useCallback } from "react";
import { API_BASE } from "../config";
import "../styles/TicketsTab.css";

/* ===================================================================
   TicketsTab  — Support Ticket System  (Phase T1 + T2, v1.58.0)
   ===================================================================
   Views:
     • List — filterable table of all visible tickets
     • My Queue — tickets assigned to current user
     • Detail modal — full ticket + comment thread + action buttons
     • Create modal
     • Admin sub-panel: SLA policies + email templates
*/

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Ticket {
  id: number;
  ticket_ref: string;
  title: string;
  description: string;
  ticket_type: string;
  status: string;
  priority: string;
  to_dept_id: number;
  to_dept_name: string;
  from_dept_name?: string;
  assigned_to?: string;
  opened_by: string;
  customer_name?: string;
  customer_email?: string;
  auto_notify_customer: boolean;
  resource_type?: string;
  resource_id?: string;
  resource_name?: string;
  project_id?: string;
  project_name?: string;
  requires_approval: boolean;
  approved_by?: string;
  approved_at?: string;
  rejected_by?: string;
  rejected_at?: string;
  sla_response_hours?: number;
  sla_resolve_hours?: number;
  sla_response_at?: string;
  sla_resolve_at?: string;
  sla_response_breached: boolean;
  sla_resolve_breached: boolean;
  first_response_at?: string;
  resolved_by?: string;
  resolved_at?: string;
  resolution_note?: string;
  escalation_count: number;
  created_at: string;
  updated_at: string;
  closed_at?: string;
  linked_execution_id?: string;
}

interface TicketComment {
  id: number;
  ticket_id: number;
  author: string;
  body: string;
  is_internal: boolean;
  comment_type: string;
  metadata: Record<string, any>;
  created_at: string;
}

interface SLAPolicy {
  id: number;
  to_dept_id: number;
  to_dept_name: string;
  ticket_type: string;
  priority: string;
  response_sla_hours: number;
  resolution_sla_hours: number;
  auto_escalate_on_breach: boolean;
  escalate_to_dept_id?: number;
  escalate_dept_name?: string;
}

interface EmailTemplate {
  id: number;
  template_name: string;
  subject: string;
  html_body: string;
}

interface Department { id: number; name: string }

interface TicketStats {
  by_status:   Record<string, number>;
  by_priority: Record<string, number>;
  sla_breached: number;
  open: number;
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
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function age(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3600000);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const PRIORITY_COLORS: Record<string, string> = {
  critical: "#dc2626", high: "#ea580c", normal: "#2563eb", low: "#6b7280",
};

const STATUS_LABELS: Record<string, string> = {
  open: "Open", assigned: "Assigned", in_progress: "In Progress",
  waiting_customer: "Waiting", pending_approval: "Pending Approval",
  resolved: "Resolved", closed: "Closed",
};

const TYPE_ICONS: Record<string, string> = {
  incident: "🔴", service_request: "📋", change_request: "🔄",
  inquiry: "💬", escalation: "🔺", auto_incident: "⚠️", auto_change_request: "🤖",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function TicketsTab({
  userRole = "",
  myQueueMode = false,
}: {
  userRole?: string;
  myQueueMode?: boolean;
}) {
  const isAdmin = userRole === "admin" || userRole === "superadmin";
  const canWrite = !["viewer"].includes(userRole);   // viewer can write too (policy grants it)

  // --- List state ---
  const [tickets, setTickets]     = useState<Ticket[]>([]);
  const [total, setTotal]         = useState(0);
  const [loading, setLoading]     = useState(false);
  const [page, setPage]           = useState(0);
  const PAGE_SIZE                 = 25;

  // Filters
  const [fStatus, setFStatus]   = useState("");
  const [fPriority, setFPriority] = useState("");
  const [fType, setFType]       = useState("");
  const [fSearch, setFSearch]   = useState("");
  const [fDept, setFDept]       = useState<number | "">("");

  // --- Stats ---
  const [stats, setStats] = useState<TicketStats | null>(null);

  // --- Detail view ---
  const [detail, setDetail]       = useState<Ticket | null>(null);
  const [comments, setComments]   = useState<TicketComment[]>([]);
  const [commentText, setCommentText] = useState("");
  const [isInternal, setIsInternal]   = useState(false);
  const [postingComment, setPostingComment] = useState(false);

  // Action forms (single field per action — opened as needed)
  const [actionModal, setActionModal] = useState<null | {
    type: "assign" | "escalate" | "resolve" | "reopen" | "approve" | "reject" |
          "close" | "email_customer" | "trigger_runbook";
    value: string;
    deptId?: number;
    template?: string;
    dryRun?: boolean;
    extra?: string;
  }>(null);

  // --- Create modal ---
  const [showCreate, setShowCreate] = useState(false);
  const [newTicket, setNewTicket] = useState({
    title: "", description: "", ticket_type: "service_request",
    priority: "normal", to_dept_id: 0,
    customer_name: "", customer_email: "", auto_notify_customer: false,
    requires_approval: false,
  });
  const [creating, setCreating] = useState(false);

  // --- Departments (for dropdowns) ---
  const [depts, setDepts] = useState<Department[]>([]);

  // --- Admin panels ---
  const [showAdmin, setShowAdmin]   = useState(false);
  const [adminTab, setAdminTab]     = useState<"sla" | "templates">("sla");
  const [slaPolicy, setSlaPolicy]   = useState<SLAPolicy[]>([]);
  const [emailTpl, setEmailTpl]     = useState<EmailTemplate[]>([]);
  const [editTpl, setEditTpl]       = useState<EmailTemplate | null>(null);

  // --- Toast ---
  const [toast, setToast] = useState<{ msg: string; type: string } | null>(null);

  const showToast = useCallback((msg: string, type = "info") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  }, []);

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------
  const loadDepts = useCallback(async () => {
    try {
      const data = await apiFetch<{ departments: Department[] }>("/api/navigation/departments");
      setDepts(data.departments || []);
    } catch {
      // fallback — depts list not critical
    }
  }, []);

  const loadStats = useCallback(async () => {
    try {
      const data = await apiFetch<TicketStats>("/api/tickets/stats");
      setStats(data);
    } catch { /* non-critical */ }
  }, []);

  const loadTickets = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (myQueueMode) {
        p.set("limit", String(PAGE_SIZE));
        p.set("offset", String(page * PAGE_SIZE));
        const data = await apiFetch<{ tickets: Ticket[]; total: number }>(
          `/api/tickets/my-queue?${p}`
        );
        setTickets(data.tickets);
        setTotal(data.total);
      } else {
        if (fStatus)   p.set("status", fStatus);
        if (fPriority) p.set("priority", fPriority);
        if (fType)     p.set("ticket_type", fType);
        if (fSearch)   p.set("search", fSearch);
        if (fDept)     p.set("to_dept_id", String(fDept));
        p.set("limit", String(PAGE_SIZE));
        p.set("offset", String(page * PAGE_SIZE));
        const data = await apiFetch<{ tickets: Ticket[]; total: number }>(
          `/api/tickets?${p}`
        );
        setTickets(data.tickets);
        setTotal(data.total);
      }
    } catch (e: any) {
      showToast(`Failed to load tickets: ${e.message}`, "error");
    } finally {
      setLoading(false);
    }
  }, [myQueueMode, fStatus, fPriority, fType, fSearch, fDept, page, showToast]);

  const loadComments = useCallback(async (tId: number) => {
    try {
      const data = await apiFetch<{ comments: TicketComment[] }>(
        `/api/tickets/${tId}/comments`
      );
      setComments(data.comments);
    } catch { setComments([]); }
  }, []);

  useEffect(() => { loadDepts(); }, [loadDepts]);
  useEffect(() => { loadTickets(); loadStats(); }, [loadTickets, loadStats]);

  const openDetail = useCallback(async (t: Ticket) => {
    setDetail(t);
    setCommentText("");
    setIsInternal(false);
    await loadComments(t.id);
  }, [loadComments]);

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------
  async function submitAction() {
    if (!detail || !actionModal) return;
    const tid = detail.id;
    try {
      let updated: Ticket;
      switch (actionModal.type) {
        case "assign":
          updated = await apiFetch<Ticket>(`/api/tickets/${tid}/assign`, {
            method: "POST",
            body: JSON.stringify({ assigned_to: actionModal.value }),
          });
          break;
        case "escalate":
          updated = await apiFetch<Ticket>(`/api/tickets/${tid}/escalate`, {
            method: "POST",
            body: JSON.stringify({ to_dept_id: actionModal.deptId, reason: actionModal.value }),
          });
          break;
        case "approve":
          updated = await apiFetch<Ticket>(`/api/tickets/${tid}/approve`, {
            method: "POST",
            body: JSON.stringify({ note: actionModal.value }),
          });
          break;
        case "reject":
          updated = await apiFetch<Ticket>(`/api/tickets/${tid}/reject`, {
            method: "POST",
            body: JSON.stringify({ note: actionModal.value }),
          });
          break;
        case "resolve":
          updated = await apiFetch<Ticket>(`/api/tickets/${tid}/resolve`, {
            method: "POST",
            body: JSON.stringify({ resolution_note: actionModal.value }),
          });
          break;
        case "reopen":
          updated = await apiFetch<Ticket>(`/api/tickets/${tid}/reopen`, {
            method: "POST",
            body: JSON.stringify({ reason: actionModal.value }),
          });
          break;
        case "close":
          updated = await apiFetch<Ticket>(`/api/tickets/${tid}/close`, {
            method: "POST",
          });
          break;
        case "email_customer":
          await apiFetch(`/api/tickets/${tid}/email-customer`, {
            method: "POST",
            body: JSON.stringify({ template_name: actionModal.template || "ticket_created" }),
          });
          showToast("Email sent to customer", "success");
          setActionModal(null);
          return;
        case "trigger_runbook":
          await apiFetch(`/api/tickets/${tid}/trigger-runbook`, {
            method: "POST",
            body: JSON.stringify({ runbook_name: actionModal.value, dry_run: actionModal.dryRun ?? true }),
          });
          showToast("Runbook triggered", "success");
          setActionModal(null);
          return;
        default:
          return;
      }
      setDetail(updated);
      setActionModal(null);
      showToast("Action completed", "success");
      await loadComments(tid);
      loadTickets();
      loadStats();
    } catch (e: any) {
      showToast(`Action failed: ${e.message}`, "error");
    }
  }

  async function postComment() {
    if (!detail || !commentText.trim()) return;
    setPostingComment(true);
    try {
      await apiFetch(`/api/tickets/${detail.id}/comments`, {
        method: "POST",
        body: JSON.stringify({ body: commentText, is_internal: isInternal }),
      });
      setCommentText("");
      await loadComments(detail.id);
    } catch (e: any) {
      showToast(`Comment failed: ${e.message}`, "error");
    } finally {
      setPostingComment(false);
    }
  }

  async function createTicket() {
    if (!newTicket.title.trim() || !newTicket.to_dept_id) {
      showToast("Title and destination department are required", "error");
      return;
    }
    setCreating(true);
    try {
      await apiFetch<Ticket>("/api/tickets", {
        method: "POST",
        body: JSON.stringify(newTicket),
      });
      setShowCreate(false);
      setNewTicket({
        title: "", description: "", ticket_type: "service_request",
        priority: "normal", to_dept_id: 0,
        customer_name: "", customer_email: "", auto_notify_customer: false,
        requires_approval: false,
      });
      showToast("Ticket created", "success");
      loadTickets();
      loadStats();
    } catch (e: any) {
      showToast(`Create failed: ${e.message}`, "error");
    } finally {
      setCreating(false);
    }
  }

  // Admin
  const loadSLAPolicies = useCallback(async () => {
    try {
      const data = await apiFetch<{ policies: SLAPolicy[] }>("/api/tickets/sla-policies");
      setSlaPolicy(data.policies);
    } catch { /* */ }
  }, []);

  const loadTemplates = useCallback(async () => {
    try {
      const data = await apiFetch<{ templates: EmailTemplate[] }>("/api/tickets/email-templates");
      setEmailTpl(data.templates);
    } catch { /* */ }
  }, []);

  useEffect(() => {
    if (showAdmin) {
      loadSLAPolicies();
      loadTemplates();
    }
  }, [showAdmin, loadSLAPolicies, loadTemplates]);

  async function saveTemplate() {
    if (!editTpl) return;
    try {
      await apiFetch(`/api/tickets/email-templates/${editTpl.template_name}`, {
        method: "PUT",
        body: JSON.stringify({ subject: editTpl.subject, html_body: editTpl.html_body }),
      });
      setEditTpl(null);
      showToast("Template saved", "success");
      loadTemplates();
    } catch (e: any) {
      showToast(`Save failed: ${e.message}`, "error");
    }
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------
  function PriorityBadge({ p }: { p: string }) {
    return (
      <span className="tt-priority-badge" style={{ backgroundColor: PRIORITY_COLORS[p] || "#6b7280" }}>
        {p.toUpperCase()}
      </span>
    );
  }

  function StatusBadge({ s }: { s: string }) {
    return <span className={`tt-status-badge tt-status-${s}`}>{STATUS_LABELS[s] || s}</span>;
  }

  function SLAWarning({ ticket }: { ticket: Ticket }) {
    if (ticket.sla_resolve_breached) return <span className="tt-sla-breach" title="Resolve SLA breached">⚠️ SLA!</span>;
    if (ticket.sla_response_breached) return <span className="tt-sla-warn" title="Response SLA breached">🕐 SLA</span>;
    if (ticket.sla_resolve_at) {
      const left = new Date(ticket.sla_resolve_at).getTime() - Date.now();
      if (left > 0 && left < 3600000) return <span className="tt-sla-warn" title="Resolve SLA < 1h">⏰</span>;
    }
    return null;
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div className="tt-root">
      {/* Toast */}
      {toast && (
        <div className={`tt-toast tt-toast-${toast.type}`}>{toast.msg}</div>
      )}

      {/* Header */}
      <div className="tt-header">
        <div className="tt-header-left">
          <h2>{myQueueMode ? "📥 My Queue" : "🎫 Support Tickets"}</h2>
          {stats && (
            <div className="tt-stats-bar">
              <span className="tt-stat">Open: <strong>{stats.open}</strong></span>
              {stats.sla_breached > 0 && (
                <span className="tt-stat tt-stat-breach">SLA Breach: <strong>{stats.sla_breached}</strong></span>
              )}
              {Object.entries(stats.by_priority).map(([k, v]) => v > 0 && (
                <span key={k} className="tt-stat" style={{ color: PRIORITY_COLORS[k] }}>
                  {k}: <strong>{v}</strong>
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="tt-header-right">
          {canWrite && (
            <button className="tt-btn tt-btn-primary" onClick={() => setShowCreate(true)}>
              + New Ticket
            </button>
          )}
          {isAdmin && (
            <button className="tt-btn tt-btn-secondary" onClick={() => setShowAdmin(!showAdmin)}>
              ⚙ Admin
            </button>
          )}
        </div>
      </div>

      {/* Admin Panel */}
      {isAdmin && showAdmin && (
        <AdminPanel
          adminTab={adminTab}
          setAdminTab={setAdminTab}
          slaPolicy={slaPolicy}
          emailTpl={emailTpl}
          editTpl={editTpl}
          setEditTpl={setEditTpl}
          saveTemplate={saveTemplate}
          depts={depts}
          showToast={showToast}
          reload={() => { loadSLAPolicies(); loadTemplates(); }}
        />
      )}

      {/* Filters (list mode only) */}
      {!myQueueMode && (
        <div className="tt-filters">
          <input
            className="tt-filter-input"
            placeholder="Search ref / title…"
            value={fSearch}
            onChange={e => { setFSearch(e.target.value); setPage(0); }}
          />
          <select className="tt-filter-select" value={fStatus}
            onChange={e => { setFStatus(e.target.value); setPage(0); }}>
            <option value="">All statuses</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) =>
              <option key={k} value={k}>{v}</option>)}
          </select>
          <select className="tt-filter-select" value={fPriority}
            onChange={e => { setFPriority(e.target.value); setPage(0); }}>
            <option value="">All priorities</option>
            {["critical","high","normal","low"].map(p =>
              <option key={p} value={p}>{p.charAt(0).toUpperCase()+p.slice(1)}</option>)}
          </select>
          <select className="tt-filter-select" value={fType}
            onChange={e => { setFType(e.target.value); setPage(0); }}>
            <option value="">All types</option>
            {Object.keys(TYPE_ICONS).map(t =>
              <option key={t} value={t}>{TYPE_ICONS[t]} {t.replace(/_/g," ")}</option>)}
          </select>
          <select className="tt-filter-select" value={fDept}
            onChange={e => { setFDept(e.target.value ? Number(e.target.value) : ""); setPage(0); }}>
            <option value="">All departments</option>
            {depts.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="tt-loading">Loading tickets…</div>
      ) : tickets.length === 0 ? (
        <div className="tt-empty">
          {myQueueMode ? "No tickets assigned to you." : "No tickets found."}
        </div>
      ) : (
        <>
          <table className="tt-table">
            <thead>
              <tr>
                <th>Ref</th>
                <th>Type</th>
                <th>Title</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Team</th>
                <th>Assigned to</th>
                <th>Age</th>
                <th>SLA</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map(t => (
                <tr key={t.id} className="tt-row" onClick={() => openDetail(t)}>
                  <td className="tt-ref">{t.ticket_ref}</td>
                  <td title={t.ticket_type}>{TYPE_ICONS[t.ticket_type] || "📋"}</td>
                  <td className="tt-title-cell">
                    {t.title}
                    {t.requires_approval && t.status === "pending_approval"
                      && <span className="tt-badge-approval">Needs Approval</span>}
                  </td>
                  <td><PriorityBadge p={t.priority} /></td>
                  <td><StatusBadge s={t.status} /></td>
                  <td>{t.to_dept_name || "—"}</td>
                  <td>{t.assigned_to || <span className="tt-unassigned">Unassigned</span>}</td>
                  <td className="tt-age">{age(t.created_at)}</td>
                  <td><SLAWarning ticket={t} /></td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Pagination */}
          <div className="tt-pagination">
            <button disabled={page === 0} className="tt-btn tt-btn-sm"
              onClick={() => setPage(p => p - 1)}>← Prev</button>
            <span>{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}</span>
            <button disabled={(page + 1) * PAGE_SIZE >= total} className="tt-btn tt-btn-sm"
              onClick={() => setPage(p => p + 1)}>Next →</button>
          </div>
        </>
      )}

      {/* Create modal */}
      {showCreate && (
        <div className="tt-modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="tt-modal" onClick={e => e.stopPropagation()}>
            <div className="tt-modal-header">
              <h3>Create New Ticket</h3>
              <button className="tt-modal-close" onClick={() => setShowCreate(false)}>✕</button>
            </div>
            <div className="tt-modal-body">
              <label>Title *
                <input value={newTicket.title}
                  onChange={e => setNewTicket(n => ({...n, title: e.target.value}))} />
              </label>
              <label>Description
                <textarea rows={3} value={newTicket.description}
                  onChange={e => setNewTicket(n => ({...n, description: e.target.value}))} />
              </label>
              <div className="tt-form-row">
                <label>Type
                  <select value={newTicket.ticket_type}
                    onChange={e => setNewTicket(n => ({...n, ticket_type: e.target.value}))}>
                    {Object.keys(TYPE_ICONS).filter(t => !t.startsWith("auto")).map(t =>
                      <option key={t} value={t}>{TYPE_ICONS[t]} {t.replace(/_/g," ")}</option>)}
                  </select>
                </label>
                <label>Priority
                  <select value={newTicket.priority}
                    onChange={e => setNewTicket(n => ({...n, priority: e.target.value}))}>
                    {["critical","high","normal","low"].map(p =>
                      <option key={p} value={p}>{p}</option>)}
                  </select>
                </label>
              </div>
              <label>Assign to team *
                <select value={newTicket.to_dept_id || ""}
                  onChange={e => setNewTicket(n => ({...n, to_dept_id: Number(e.target.value)}))}>
                  <option value="">Select team…</option>
                  {depts.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </label>
              <label>Customer Name
                <input value={newTicket.customer_name}
                  onChange={e => setNewTicket(n => ({...n, customer_name: e.target.value}))} />
              </label>
              <label>Customer Email
                <input type="email" value={newTicket.customer_email}
                  onChange={e => setNewTicket(n => ({...n, customer_email: e.target.value}))} />
              </label>
              <label className="tt-checkbox-label">
                <input type="checkbox" checked={newTicket.auto_notify_customer}
                  onChange={e => setNewTicket(n => ({...n, auto_notify_customer: e.target.checked}))} />
                Auto-notify customer by email
              </label>
              <label className="tt-checkbox-label">
                <input type="checkbox" checked={newTicket.requires_approval}
                  onChange={e => setNewTicket(n => ({...n, requires_approval: e.target.checked}))} />
                Requires approval before work begins
              </label>
            </div>
            <div className="tt-modal-footer">
              <button className="tt-btn tt-btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
              <button className="tt-btn tt-btn-primary" disabled={creating} onClick={createTicket}>
                {creating ? "Creating…" : "Create Ticket"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Detail view */}
      {detail && (
        <div className="tt-modal-overlay" onClick={() => setDetail(null)}>
          <div className="tt-modal tt-detail-modal" onClick={e => e.stopPropagation()}>
            <div className="tt-modal-header">
              <div className="tt-detail-title-row">
                <span className="tt-detail-ref">{detail.ticket_ref}</span>
                <StatusBadge s={detail.status} />
                <PriorityBadge p={detail.priority} />
                <SLAWarning ticket={detail} />
                {detail.escalation_count > 0 &&
                  <span className="tt-badge-escalated">Escalated ×{detail.escalation_count}</span>}
              </div>
              <button className="tt-modal-close" onClick={() => setDetail(null)}>✕</button>
            </div>

            <div className="tt-detail-body">
              {/* Left: ticket info */}
              <div className="tt-detail-info">
                <h3>{detail.title}</h3>
                {detail.description && <p className="tt-desc">{detail.description}</p>}

                <dl className="tt-dl">
                  <dt>Type</dt>       <dd>{TYPE_ICONS[detail.ticket_type]} {detail.ticket_type.replace(/_/g," ")}</dd>
                  <dt>Team</dt>       <dd>{detail.to_dept_name}</dd>
                  <dt>Assigned to</dt><dd>{detail.assigned_to || <em>Unassigned</em>}</dd>
                  <dt>Opened by</dt>  <dd>{detail.opened_by}</dd>
                  <dt>Created</dt>    <dd>{fmt(detail.created_at)}</dd>
                  {detail.resolved_at && <><dt>Resolved</dt><dd>{fmt(detail.resolved_at)}</dd></>}
                  {detail.sla_resolve_at && <>
                    <dt>SLA deadline</dt>
                    <dd className={detail.sla_resolve_breached ? "tt-breach-text" : ""}>
                      {fmt(detail.sla_resolve_at)}
                    </dd>
                  </>}
                  {detail.customer_name && <><dt>Customer</dt><dd>{detail.customer_name} {detail.customer_email && `<${detail.customer_email}>`}</dd></>}
                  {detail.resource_name && <><dt>Resource</dt><dd>{detail.resource_type}: {detail.resource_name}</dd></>}
                  {detail.project_name && <><dt>Project</dt><dd>{detail.project_name}</dd></>}
                  {detail.resolution_note && <><dt>Resolution</dt><dd>{detail.resolution_note}</dd></>}
                  {detail.approved_by && <><dt>Approved by</dt><dd>{detail.approved_by} at {fmt(detail.approved_at)}</dd></>}
                  {detail.rejected_by && <><dt>Rejected by</dt><dd>{detail.rejected_by} at {fmt(detail.rejected_at)}</dd></>}
                </dl>

                {/* Action buttons */}
                {canWrite && (
                  <div className="tt-actions">
                    {!["resolved","closed"].includes(detail.status) && detail.status !== "pending_approval" && (
                      <button className="tt-btn tt-btn-sm" onClick={() =>
                        setActionModal({ type:"assign", value:"" })}>
                        Assign
                      </button>
                    )}
                    {!["resolved","closed","pending_approval"].includes(detail.status) && (
                      <button className="tt-btn tt-btn-sm" onClick={() =>
                        setActionModal({ type:"escalate", value:"", deptId:0 })}>
                        Escalate
                      </button>
                    )}
                    {detail.status === "pending_approval" && (
                      <>
                        <button className="tt-btn tt-btn-sm tt-btn-success" onClick={() =>
                          setActionModal({ type:"approve", value:"" })}>Approve</button>
                        <button className="tt-btn tt-btn-sm tt-btn-danger" onClick={() =>
                          setActionModal({ type:"reject", value:"" })}>Reject</button>
                      </>
                    )}
                    {!["resolved","closed","pending_approval"].includes(detail.status) && (
                      <button className="tt-btn tt-btn-sm tt-btn-success" onClick={() =>
                        setActionModal({ type:"resolve", value:"" })}>Resolve</button>
                    )}
                    {["resolved","closed"].includes(detail.status) && (
                      <button className="tt-btn tt-btn-sm" onClick={() =>
                        setActionModal({ type:"reopen", value:"" })}>Reopen</button>
                    )}
                    {detail.status !== "closed" && (
                      <button className="tt-btn tt-btn-sm tt-btn-danger" onClick={() =>
                        setActionModal({ type:"close", value:"" })}>Close</button>
                    )}
                    {/* T2 actions */}
                    {detail.customer_email && (
                      <button className="tt-btn tt-btn-sm tt-btn-outline" onClick={() =>
                        setActionModal({ type:"email_customer", value:"", template:"ticket_created" })}>
                        📧 Email Customer
                      </button>
                    )}
                    <button className="tt-btn tt-btn-sm tt-btn-outline" onClick={() =>
                      setActionModal({ type:"trigger_runbook", value:"", dryRun:true })}>
                      ▶ Run Runbook
                    </button>
                  </div>
                )}
              </div>

              {/* Right: comment thread */}
              <div className="tt-comment-panel">
                <h4>Activity</h4>
                <div className="tt-comments">
                  {comments.length === 0 && <p className="tt-no-comments">No activity yet.</p>}
                  {comments.map(c => (
                    <div key={c.id} className={`tt-comment ${c.is_internal ? "tt-comment-internal" : ""}`}>
                      <div className="tt-comment-meta">
                        <span className="tt-comment-author">{c.author}</span>
                        <span className="tt-comment-type">{c.comment_type !== "comment" ? ` · ${c.comment_type.replace(/_/g," ")}` : ""}</span>
                        <span className="tt-comment-time">{fmt(c.created_at)}</span>
                        {c.is_internal && <span className="tt-internal-tag">Internal</span>}
                      </div>
                      <p className="tt-comment-body">{c.body}</p>
                    </div>
                  ))}
                </div>

                {canWrite && (
                  <div className="tt-comment-form">
                    <textarea
                      rows={3}
                      placeholder="Add a comment…"
                      value={commentText}
                      onChange={e => setCommentText(e.target.value)}
                    />
                    <div className="tt-comment-form-row">
                      {userRole !== "viewer" && (
                        <label className="tt-checkbox-label">
                          <input type="checkbox" checked={isInternal}
                            onChange={e => setIsInternal(e.target.checked)} />
                          Internal note
                        </label>
                      )}
                      <button className="tt-btn tt-btn-primary tt-btn-sm"
                        disabled={postingComment || !commentText.trim()}
                        onClick={postComment}>
                        {postingComment ? "Posting…" : "Post"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Action modals */}
      {actionModal && detail && (
        <div className="tt-modal-overlay" onClick={() => setActionModal(null)}>
          <div className="tt-modal tt-action-modal" onClick={e => e.stopPropagation()}>
            <div className="tt-modal-header">
              <h3>{actionModal.type.replace(/_/g," ").replace(/\b\w/g, c => c.toUpperCase())}: {detail.ticket_ref}</h3>
              <button className="tt-modal-close" onClick={() => setActionModal(null)}>✕</button>
            </div>
            <div className="tt-modal-body">
              {actionModal.type === "assign" && (
                <label>Assign to (username)
                  <input value={actionModal.value}
                    onChange={e => setActionModal(a => a && ({...a, value: e.target.value}))} />
                </label>
              )}
              {actionModal.type === "escalate" && (
                <>
                  <label>Escalate to team
                    <select value={actionModal.deptId || ""}
                      onChange={e => setActionModal(a => a && ({...a, deptId: Number(e.target.value)}))}>
                      <option value="">Select team…</option>
                      {depts.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                    </select>
                  </label>
                  <label>Reason
                    <input value={actionModal.value}
                      onChange={e => setActionModal(a => a && ({...a, value: e.target.value}))} />
                  </label>
                </>
              )}
              {["approve","reject","resolve","reopen"].includes(actionModal.type) && (
                <label>{actionModal.type === "resolve" ? "Resolution note" : "Note (optional)"}
                  <textarea rows={3} value={actionModal.value}
                    onChange={e => setActionModal(a => a && ({...a, value: e.target.value}))} />
                </label>
              )}
              {actionModal.type === "close" && (
                <p>Are you sure you want to close ticket <strong>{detail.ticket_ref}</strong>?</p>
              )}
              {actionModal.type === "email_customer" && (
                <label>Template
                  <select value={actionModal.template || "ticket_created"}
                    onChange={e => setActionModal(a => a && ({...a, template: e.target.value}))}>
                    {emailTpl.map(t => <option key={t.id} value={t.template_name}>{t.template_name}</option>)}
                    {emailTpl.length === 0 && (
                      ["ticket_created","ticket_resolved","ticket_assigned","ticket_escalated",
                       "ticket_pending_approval","ticket_sla_breach"].map(n =>
                        <option key={n} value={n}>{n}</option>)
                    )}
                  </select>
                </label>
              )}
              {actionModal.type === "trigger_runbook" && (
                <>
                  <label>Runbook name
                    <input value={actionModal.value}
                      onChange={e => setActionModal(a => a && ({...a, value: e.target.value}))} />
                  </label>
                  <label className="tt-checkbox-label">
                    <input type="checkbox" checked={actionModal.dryRun ?? true}
                      onChange={e => setActionModal(a => a && ({...a, dryRun: e.target.checked}))} />
                    Dry run
                  </label>
                </>
              )}
            </div>
            <div className="tt-modal-footer">
              <button className="tt-btn tt-btn-secondary" onClick={() => setActionModal(null)}>Cancel</button>
              <button className={`tt-btn ${actionModal.type === "reject" || actionModal.type === "close" ? "tt-btn-danger" : "tt-btn-primary"}`}
                onClick={submitAction}>
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Admin Panel sub-component
// ---------------------------------------------------------------------------
function AdminPanel({
  adminTab, setAdminTab,
  slaPolicy, emailTpl,
  editTpl, setEditTpl, saveTemplate,
  depts, showToast, reload,
}: {
  adminTab: "sla" | "templates";
  setAdminTab: (v: "sla" | "templates") => void;
  slaPolicy: SLAPolicy[];
  emailTpl: EmailTemplate[];
  editTpl: EmailTemplate | null;
  setEditTpl: (t: EmailTemplate | null) => void;
  saveTemplate: () => void;
  depts: Department[];
  showToast: (msg: string, type?: string) => void;
  reload: () => void;
}) {
  return (
    <div className="tt-admin-panel">
      <div className="tt-admin-tabs">
        <button className={`tt-admin-tab ${adminTab === "sla" ? "active" : ""}`}
          onClick={() => setAdminTab("sla")}>SLA Policies</button>
        <button className={`tt-admin-tab ${adminTab === "templates" ? "active" : ""}`}
          onClick={() => setAdminTab("templates")}>Email Templates</button>
      </div>

      {adminTab === "sla" && (
        <div className="tt-admin-content">
          <table className="tt-table tt-table-sm">
            <thead>
              <tr>
                <th>Team</th><th>Type</th><th>Priority</th>
                <th>Response&nbsp;(h)</th><th>Resolve&nbsp;(h)</th>
                <th>Auto-escalate</th><th>Escalate to</th>
              </tr>
            </thead>
            <tbody>
              {slaPolicy.map(p => (
                <tr key={p.id}>
                  <td>{p.to_dept_name}</td>
                  <td>{p.ticket_type}</td>
                  <td><span style={{ color: ({ critical:"#dc2626", high:"#ea580c", normal:"#2563eb", low:"#6b7280" } as any)[p.priority] }}>{p.priority}</span></td>
                  <td>{p.response_sla_hours}</td>
                  <td>{p.resolution_sla_hours}</td>
                  <td>{p.auto_escalate_on_breach ? "✅" : "—"}</td>
                  <td>{p.escalate_dept_name || "—"}</td>
                </tr>
              ))}
              {slaPolicy.length === 0 && (
                <tr><td colSpan={7} className="tt-empty">No SLA policies configured</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {adminTab === "templates" && (
        <div className="tt-admin-content">
          {editTpl ? (
            <div className="tt-template-editor">
              <h4>Edit: {editTpl.template_name}</h4>
              <label>Subject
                <input value={editTpl.subject}
                  onChange={e => setEditTpl({...editTpl, subject: e.target.value})} />
              </label>
              <label>HTML Body
                <textarea rows={10} value={editTpl.html_body}
                  onChange={e => setEditTpl({...editTpl, html_body: e.target.value})} />
              </label>
              <p className="tt-hint">Available placeholders depend on template context — e.g. &#123;&#123;ticket_ref&#125;&#125;, &#123;&#123;title&#125;&#125;, &#123;&#123;priority&#125;&#125;, &#123;&#123;customer_name&#125;&#125;</p>
              <div className="tt-template-editor-actions">
                <button className="tt-btn tt-btn-secondary" onClick={() => setEditTpl(null)}>Cancel</button>
                <button className="tt-btn tt-btn-primary" onClick={saveTemplate}>Save Template</button>
              </div>
            </div>
          ) : (
            <table className="tt-table tt-table-sm">
              <thead>
                <tr><th>Name</th><th>Subject</th><th></th></tr>
              </thead>
              <tbody>
                {emailTpl.map(t => (
                  <tr key={t.id}>
                    <td><code>{t.template_name}</code></td>
                    <td>{t.subject}</td>
                    <td><button className="tt-btn tt-btn-sm" onClick={() => setEditTpl(t)}>Edit</button></td>
                  </tr>
                ))}
                {emailTpl.length === 0 && (
                  <tr><td colSpan={3} className="tt-empty">No templates loaded</td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
