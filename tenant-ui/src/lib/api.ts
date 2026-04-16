/**
 * api.ts — Tenant portal API client.
 *
 * All API calls go through `tenantFetch<T>()`.
 * The JWT Bearer token is stored in sessionStorage (cleared on tab close).
 * Credentials never appear in localStorage.
 */

const BASE = ""; // relative — nginx/vite-proxy forwards /tenant/* correctly

// ---------------------------------------------------------------------------
// Token storage (sessionStorage — not localStorage, cleared on tab close)
// ---------------------------------------------------------------------------

const TOKEN_KEY = "tenant_token";
const EXPIRES_KEY = "tenant_token_expires_at";

export function getToken(): string | null {
  const token = sessionStorage.getItem(TOKEN_KEY);
  const exp = sessionStorage.getItem(EXPIRES_KEY);
  if (!token || !exp) return null;
  return new Date(exp).getTime() > Date.now() ? token : null;
}

export function setToken(token: string, expiresIn: number): void {
  const exp = new Date(Date.now() + expiresIn * 1000).toISOString();
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(EXPIRES_KEY, exp);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(EXPIRES_KEY);
}

// ---------------------------------------------------------------------------
// Core fetch helper
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function tenantFetch<T>(
  path: string,
  opts: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}${path}`, { ...opts, headers });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = String(body.detail);
    } catch {
      // ignore parse errors
    }
    throw new ApiError(res.status, detail);
  }

  // 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Auth endpoints
// ---------------------------------------------------------------------------

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  requires_mfa: boolean;
  preauth_token: string | null;
}

export interface MeResponse {
  username: string;
  keystone_user_id: string;
  projects: Array<{ id: string; name: string }>;
  regions: string[];
}

export async function apiLogin(username: string, password: string, domain: string): Promise<LoginResponse> {
  return tenantFetch<LoginResponse>("/tenant/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password, domain }),
  });
}

export async function apiLogout(): Promise<void> {
  try {
    await tenantFetch<void>("/tenant/auth/logout", { method: "POST" });
  } finally {
    clearToken();
  }
}

export async function apiMe(): Promise<MeResponse> {
  return tenantFetch<MeResponse>("/tenant/auth/me");
}

export async function apiMfaEmailSend(preauthToken: string): Promise<{ message: string }> {
  return tenantFetch("/tenant/auth/mfa/email-send", {
    method: "POST",
    body: JSON.stringify({ preauth_token: preauthToken }),
  });
}

export async function apiMfaVerify(
  preauthToken: string,
  code: string,
): Promise<LoginResponse> {
  return tenantFetch("/tenant/auth/mfa/verify", {
    method: "POST",
    body: JSON.stringify({ preauth_token: preauthToken, code }),
  });
}

// ---------------------------------------------------------------------------
// Branding (public — no auth required)
// ---------------------------------------------------------------------------

export interface Branding {
  company_name: string;
  logo_url: string | null;
  favicon_url: string | null;
  primary_color: string;
  accent_color: string;
  support_email: string | null;
  support_url: string | null;
  welcome_message: string | null;
  footer_text: string | null;
}

export async function apiBranding(): Promise<Branding> {
  return tenantFetch<Branding>("/tenant/branding");
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export interface DashboardData {
  total_vms: number;
  vms_running: number;
  vms_stopped: number;
  vms_error: number;
  compliance_pct: number;
  last_snapshot_hours_ago: number | null;
  active_restores: number;
  failed_snapshots_24h: number;
  regions: Array<{
    region_display_name: string;
    vm_count: number;
    compliance_pct: number;
    last_snapshot_ts: string | null;
  }>;
}

export async function apiDashboard(): Promise<DashboardData> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/dashboard");
  const byStatus = ((raw.vms as Record<string, unknown>)?.by_status ?? {}) as Record<string, number>;
  const snap = (raw.snapshot_coverage ?? {}) as Record<string, number>;
  return {
    total_vms:               Number((raw.vms as Record<string, unknown>)?.total ?? 0),
    vms_running:             byStatus["ACTIVE"]  ?? byStatus["active"]  ?? 0,
    vms_stopped:             byStatus["SHUTOFF"] ?? byStatus["stopped"] ?? 0,
    vms_error:               byStatus["ERROR"]   ?? byStatus["error"]   ?? 0,
    compliance_pct:          snap.coverage_pct_7d ?? 0,
    last_snapshot_hours_ago: null,
    active_restores:         Number(raw.active_restore_jobs ?? 0),
    failed_snapshots_24h:    0,
    regions:                 [],
  };
}

// ---------------------------------------------------------------------------
// Events (recent)
// ---------------------------------------------------------------------------

export interface TenantEvent {
  timestamp: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  success: boolean;
  details: Record<string, unknown> | null;
}

export async function apiEvents(): Promise<TenantEvent[]> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/events");
  const list = (Array.isArray(raw) ? raw : ((raw.events ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((e) => ({
    timestamp:     String(e.timestamp     ?? e.occurred_at ?? ""),
    action:        String(e.action        ?? e.event_type  ?? ""),
    resource_type: (e.resource_type ?? null) as string | null,
    resource_id:   (e.resource_id   ?? null) as string | null,
    success:       Boolean(e.success ?? true),
    details:       (e.details ?? null) as Record<string, unknown> | null,
  }));
}

// ---------------------------------------------------------------------------
// VMs
// ---------------------------------------------------------------------------

export interface Vm {
  vm_id: string;
  vm_name: string;
  status: string;
  vcpus: number;
  ram_mb: number;
  project_id: string;
  region_id: string;
  region_display_name: string;
  last_snapshot_ts: string | null;
  compliance_pct: number | null;
  ip_addresses: string[];
}

export async function apiVms(regionId?: string): Promise<Vm[]> {
  const q = regionId ? `?region_id=${encodeURIComponent(regionId)}` : "";
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/vms${q}`);
  const list = (Array.isArray(raw) ? raw : ((raw.vms ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => ({
    vm_id:               String(r.id ?? r.vm_id ?? ""),
    vm_name:             String(r.name ?? r.vm_name ?? ""),
    status:              String(r.status ?? ""),
    vcpus:               Number(r.vcpus ?? 0),
    ram_mb:              Number(r.ram_mb ?? 0),
    project_id:          String(r.project_id ?? ""),
    region_id:           String(r.region_id ?? ""),
    region_display_name: String(r.region_display_name ?? r.region_id ?? ""),
    last_snapshot_ts:    (r.last_snapshot_ts ?? r.last_snapshot_at ?? null) as string | null,
    compliance_pct:      typeof r.compliance_pct === "number" ? r.compliance_pct : null,
    ip_addresses:        Array.isArray(r.ip_addresses) ? r.ip_addresses as string[] : [],
  }));
}

export async function apiVm(vmId: string): Promise<Vm> {
  const r = await tenantFetch<Record<string, unknown>>(`/tenant/vms/${encodeURIComponent(vmId)}`);
  return {
    vm_id:               String(r.id ?? r.vm_id ?? ""),
    vm_name:             String(r.name ?? r.vm_name ?? ""),
    status:              String(r.status ?? ""),
    vcpus:               Number(r.vcpus ?? 0),
    ram_mb:              Number(r.ram_mb ?? 0),
    project_id:          String(r.project_id ?? ""),
    region_id:           String(r.region_id ?? ""),
    region_display_name: String(r.region_display_name ?? r.region_id ?? ""),
    last_snapshot_ts:    (r.last_snapshot_ts ?? r.last_snapshot_at ?? null) as string | null,
    compliance_pct:      typeof r.compliance_pct === "number" ? r.compliance_pct : null,
    ip_addresses:        Array.isArray(r.ip_addresses) ? r.ip_addresses as string[] : [],
  };
}

// ---------------------------------------------------------------------------
// Volumes
// ---------------------------------------------------------------------------

export interface Volume {
  volume_id: string;
  volume_name: string;
  size_gb: number;
  status: string;
  volume_type: string | null;
  attached_vm_id: string | null;
  attached_vm_name: string | null;
  region_display_name: string;
  last_snapshot_ts: string | null;
}

export async function apiVolumes(regionId?: string): Promise<Volume[]> {
  const q = regionId ? `?region_id=${encodeURIComponent(regionId)}` : "";
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/volumes${q}`);
  const list = (Array.isArray(raw) ? raw : ((raw.volumes ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => ({
    volume_id:           String(r.id ?? r.volume_id ?? ""),
    volume_name:         String(r.name ?? r.volume_name ?? ""),
    size_gb:             Number(r.size_gb ?? 0),
    status:              String(r.status ?? ""),
    volume_type:         (r.volume_type ?? null) as string | null,
    attached_vm_id:      (r.server_id ?? r.attached_vm_id ?? null) as string | null,
    attached_vm_name:    (r.attached_vm_name ?? null) as string | null,
    region_display_name: String(r.region_display_name ?? r.region_id ?? ""),
    last_snapshot_ts:    (r.last_snapshot_ts ?? null) as string | null,
  }));
}

// ---------------------------------------------------------------------------
// Snapshots
// ---------------------------------------------------------------------------

export interface Snapshot {
  snapshot_id: string;
  snapshot_name: string;
  vm_id: string;
  vm_name: string;
  status: string;
  created_at: string;
  size_gb: number | null;
  region_display_name: string;
}

export async function apiSnapshots(params?: {
  vm_id?: string;
  region_id?: string;
  status?: string;
  from_date?: string;
  to_date?: string;
}): Promise<Snapshot[]> {
  const q = new URLSearchParams();
  if (params?.vm_id) q.set("vm_id", params.vm_id);
  if (params?.region_id) q.set("region_id", params.region_id);
  if (params?.status) q.set("status", params.status);
  if (params?.from_date) q.set("from_date", params.from_date);
  if (params?.to_date) q.set("to_date", params.to_date);
  const qs = q.toString() ? `?${q.toString()}` : "";
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/snapshots${qs}`);
  const list = (Array.isArray(raw) ? raw : ((raw.snapshots ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => ({
    snapshot_id:         String(r.id ?? r.snapshot_id ?? ""),
    snapshot_name:       String(r.name ?? r.snapshot_name ?? ""),
    vm_id:               String(r.vm_id ?? ""),
    vm_name:             String(r.vm_name ?? ""),
    status:              String(r.status ?? ""),
    created_at:          String(r.created_at ?? ""),
    size_gb:             typeof r.size_gb === "number" ? r.size_gb : null,
    region_display_name: String(r.region_display_name ?? r.region_id ?? ""),
  }));
}

// ---------------------------------------------------------------------------
// Snapshot history
// ---------------------------------------------------------------------------

export interface SnapshotRecord {
  record_id: string;
  vm_id: string;
  vm_name: string;
  run_date: string;
  status: string;
  region_display_name: string;
}

export async function apiSnapshotHistory(): Promise<SnapshotRecord[]> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/snapshot-history");
  const list = (Array.isArray(raw) ? raw : ((raw.records ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => {
    const rawStatus = String(r.status ?? "").toUpperCase();
    // Normalise backend status values (OK/ERROR/SKIPPED/DRY_RUN) to the
    // canonical values expected by the calendar component ("success"/"failed")
    let status: string;
    if (rawStatus === "OK") status = "success";
    else if (rawStatus === "ERROR") status = "failed";
    else status = rawStatus.toLowerCase();
    return {
      record_id:           String(r.id ?? r.record_id ?? ""),
      vm_id:               String(r.vm_id ?? ""),
      vm_name:             String(r.vm_name ?? ""),
      run_date:            String(r.run_date ?? r.created_at ?? ""),
      status,
      region_display_name: String(r.region_display_name ?? r.region_id ?? ""),
    };
  });
}

// ---------------------------------------------------------------------------
// Compliance
// ---------------------------------------------------------------------------

export interface ComplianceRow {
  vm_id: string;
  vm_name: string;
  region_display_name: string;
  coverage_pct: number;
  current_streak: number;
  last_snapshot_ts: string | null;
  status: string;
}

export async function apiCompliance(): Promise<ComplianceRow[]> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/compliance");
  const list = (Array.isArray(raw) ? raw : ((raw.vms ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => ({
    vm_id:               String(r.vm_id ?? ""),
    vm_name:             String(r.vm_name ?? ""),
    region_display_name: String(r.region_display_name ?? r.region_id ?? ""),
    coverage_pct:        typeof r.coverage_pct === "number" ? r.coverage_pct : 0,
    current_streak:      typeof r.current_streak === "number" ? r.current_streak : 0,
    last_snapshot_ts:    (r.last_snapshot_ts ?? r.last_success_at ?? null) as string | null,
    status:              r.is_compliant ? "compliant" : "non_compliant",
  }));
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

export interface VmMetrics {
  vm_id: string;
  vm_name: string;
  cpu_pct: number | null;
  ram_pct: number | null;
  storage_pct: number | null;
  storage_used_gb: number | null;
  storage_total_gb: number | null;
  iops_read: number | null;
  iops_write: number | null;
  network_rx_mb: number | null;
  network_tx_mb: number | null;
  last_updated: string | null;
}

export interface AvailabilityRow {
  vm_id: string;
  vm_name: string;
  region_display_name: string;
  uptime_7d_pct: number | null;
  uptime_30d_pct: number | null;
  last_seen: string | null;
  status: string;
}

function _normaliseMetrics(r: Record<string, unknown>): VmMetrics {
  return {
    vm_id:            String(r.vm_id ?? ""),
    vm_name:          String(r.vm_name ?? ""),
    cpu_pct:          (r.cpu_pct         ?? r.cpu_usage_percent         ?? null) as number | null,
    ram_pct:          (r.ram_pct         ?? r.memory_usage_percent       ?? null) as number | null,
    storage_pct:      (r.storage_pct     ?? r.storage_usage_percent      ?? null) as number | null,
    storage_used_gb:  (r.storage_used_gb  ?? null) as number | null,
    storage_total_gb: (r.storage_total_gb ?? null) as number | null,
    iops_read:        (r.iops_read   ?? null) as number | null,
    iops_write:       (r.iops_write  ?? null) as number | null,
    network_rx_mb:    (r.network_rx_mb  ?? r.network_rx_mbps  ?? null) as number | null,
    network_tx_mb:    (r.network_tx_mb  ?? r.network_tx_mbps  ?? null) as number | null,
    last_updated:     (r.last_updated ?? null) as string | null,
  };
}

export async function apiMetricsVms(): Promise<VmMetrics[]> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/metrics/vms");
  const list = (Array.isArray(raw) ? raw : ((raw.vms ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map(_normaliseMetrics);
}

export async function apiMetricsVm(vmId: string): Promise<VmMetrics> {
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/metrics/vms/${encodeURIComponent(vmId)}`);
  return _normaliseMetrics(raw);
}

export async function apiAvailability(): Promise<AvailabilityRow[]> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/metrics/availability");
  const list = (Array.isArray(raw) ? raw : ((raw.availability ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => ({
    vm_id:               String(r.vm_id ?? ""),
    vm_name:             String(r.vm_name ?? ""),
    region_display_name: String(r.region_display_name ?? ""),
    uptime_7d_pct:       typeof r.uptime_7d_pct  === "number" ? r.uptime_7d_pct  : null,
    uptime_30d_pct:      typeof r.uptime_30d_pct === "number" ? r.uptime_30d_pct : null,
    last_seen:           (r.last_seen ?? null) as string | null,
    status:              String(r.status ?? "ACTIVE"),
  }));
}

// ---------------------------------------------------------------------------
// Restore center
// ---------------------------------------------------------------------------

export interface RestorePoint {
  snapshot_id: string;
  snapshot_name: string;
  created_at: string;
  status: string;
  size_gb: number | null;
}

export interface RestorePlan {
  plan_id: string;
  vm_id: string;
  snapshot_id: string;
  region_id: string;
  new_vm_name: string;
  mode: string;
  safety_snapshot: boolean;
  status: string;
}

export interface RestoreJob {
  job_id: string;
  vm_id: string;
  vm_name: string;
  snapshot_id: string;
  new_vm_name: string;
  mode: string;
  status: string;
  progress_pct: number;
  created_at: string;
  updated_at: string;
  region_display_name: string;
  error_message: string | null;
  failure_reason: string | null;
}

function _normaliseJob(r: Record<string, unknown>): RestoreJob {
  return {
    job_id:              String(r.job_id ?? r.id ?? ""),
    vm_id:               String(r.vm_id ?? ""),
    vm_name:             String(r.vm_name ?? ""),
    snapshot_id:         String(r.snapshot_id ?? ""),
    new_vm_name:         String(r.new_vm_name ?? r.requested_name ?? ""),
    mode:                String(r.mode ?? "NEW"),
    status:              String(r.status ?? ""),
    progress_pct:        typeof r.progress_pct === "number" ? r.progress_pct : 0,
    created_at:          String(r.created_at ?? ""),
    updated_at:          String(r.updated_at ?? r.finished_at ?? r.started_at ?? r.created_at ?? ""),
    region_display_name: String(r.region_display_name ?? ""),
    error_message:       (r.error_message ?? r.failure_reason ?? null) as string | null,
    failure_reason:      (r.failure_reason ?? null) as string | null,
  };
}

export async function apiRestorePoints(vmId: string): Promise<RestorePoint[]> {
  const raw = await tenantFetch<Record<string, unknown>>(
    `/tenant/vms/${encodeURIComponent(vmId)}/restore-points`,
  );
  const list = (Array.isArray(raw) ? raw : ((raw.restore_points ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => ({
    snapshot_id:   String(r.id ?? r.snapshot_id ?? ""),
    snapshot_name: String(r.name ?? r.snapshot_name ?? ""),
    created_at:    String(r.created_at ?? ""),
    status:        String(r.status ?? ""),
    size_gb:       typeof r.size_gb === "number" ? r.size_gb : null,
  }));
}

export async function apiRestorePlan(body: {
  vm_id: string;
  snapshot_id: string;
  region_id: string;
  new_vm_name?: string;
  mode?: "NEW" | "REPLACE";
}): Promise<RestorePlan> {
  return tenantFetch<RestorePlan>("/tenant/restore/plan", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function apiRestoreExecute(planId: string): Promise<RestoreJob> {
  return tenantFetch<RestoreJob>("/tenant/restore/execute", {
    method: "POST",
    body: JSON.stringify({ plan_id: planId }),
  });
}

export async function apiRestoreJobs(status?: string): Promise<RestoreJob[]> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/restore/jobs${q}`);
  const list = (Array.isArray(raw) ? raw : ((raw.jobs ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map(_normaliseJob);
}

export async function apiRestoreJob(jobId: string): Promise<RestoreJob> {
  const raw = await tenantFetch<Record<string, unknown>>(
    `/tenant/restore/jobs/${encodeURIComponent(jobId)}`,
  );
  return _normaliseJob(raw);
}

export async function apiRestoreCancel(jobId: string): Promise<{ message: string }> {
  return tenantFetch(`/tenant/restore/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}

// ---------------------------------------------------------------------------
// Runbooks
// ---------------------------------------------------------------------------

export interface Runbook {
  name: string;
  display_name: string;
  description: string;
  category: string;
  risk_level: string;
  steps: string[];
  prerequisites: string | null;
  expected_outcome: string | null;
  updated_at: string;
}

function _normaliseRunbook(r: Record<string, unknown>): Runbook {
  return {
    name:             String(r.name ?? ""),
    display_name:     String(r.display_name ?? r.name ?? ""),
    description:      String(r.description ?? ""),
    category:         String(r.category ?? "general"),
    risk_level:       String(r.risk_level ?? "low"),
    steps:            Array.isArray(r.steps) ? r.steps as string[] : [],
    prerequisites:    (r.prerequisites    ?? null) as string | null,
    expected_outcome: (r.expected_outcome ?? null) as string | null,
    updated_at:       String(r.updated_at ?? ""),
  };
}

export async function apiRunbooks(): Promise<Runbook[]> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/runbooks");
  const list = (Array.isArray(raw) ? raw : ((raw.runbooks ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map(_normaliseRunbook);
}

export async function apiRunbook(name: string): Promise<Runbook> {
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/runbooks/${encodeURIComponent(name)}`);
  return _normaliseRunbook(raw);
}

// ---------------------------------------------------------------------------
// Activity log
// ---------------------------------------------------------------------------

export interface ActivityRow {
  id: number;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  project_id: string | null;
  region_id: string | null;
  ip_address: string | null;
  timestamp: string;
  success: boolean;
  details: Record<string, unknown> | null;
}

export async function apiActivity(params?: {
  from_date?: string;
  to_date?: string;
  action?: string;
}): Promise<ActivityRow[]> {
  const q = new URLSearchParams();
  if (params?.from_date) q.set("from_date", params.from_date);
  if (params?.to_date) q.set("to_date", params.to_date);
  if (params?.action) q.set("action", params.action);
  const qs = q.toString() ? `?${q.toString()}` : "";
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/events${qs}`);
  const list = (Array.isArray(raw) ? raw : ((raw.events ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((e) => ({
    id:            Number(e.id ?? e.event_id ?? 0),
    action:        String(e.action     ?? e.event_type  ?? ""),
    resource_type: (e.resource_type ?? null) as string | null,
    resource_id:   (e.resource_id   ?? null) as string | null,
    project_id:    (e.project_id    ?? null) as string | null,
    region_id:     (e.region_id     ?? null) as string | null,
    ip_address:    (e.ip_address    ?? null) as string | null,
    timestamp:     String(e.timestamp ?? e.occurred_at ?? ""),
    success:       Boolean(e.success ?? true),
    details:       (e.details ?? null) as Record<string, unknown> | null,
  }));
}
