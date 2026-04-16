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
  return tenantFetch<DashboardData>("/tenant/dashboard");
}

// ---------------------------------------------------------------------------
// Events
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
  return tenantFetch<TenantEvent[]>("/tenant/events");
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
  return tenantFetch<Vm[]>(`/tenant/vms${q}`);
}

export async function apiVm(vmId: string): Promise<Vm> {
  return tenantFetch<Vm>(`/tenant/vms/${encodeURIComponent(vmId)}`);
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
  return tenantFetch<Volume[]>(`/tenant/volumes${q}`);
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
  return tenantFetch<Snapshot[]>(`/tenant/snapshots${qs}`);
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
  return tenantFetch<SnapshotRecord[]>("/tenant/snapshot-history");
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
  return tenantFetch<ComplianceRow[]>("/tenant/compliance");
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

export async function apiMetricsVms(): Promise<VmMetrics[]> {
  return tenantFetch<VmMetrics[]>("/tenant/metrics/vms");
}

export async function apiMetricsVm(vmId: string): Promise<VmMetrics> {
  return tenantFetch<VmMetrics>(`/tenant/metrics/vms/${encodeURIComponent(vmId)}`);
}

export async function apiAvailability(): Promise<AvailabilityRow[]> {
  return tenantFetch<AvailabilityRow[]>("/tenant/metrics/availability");
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
  status: string;
}

export interface RestoreJob {
  job_id: string;
  vm_id: string;
  vm_name: string;
  snapshot_id: string;
  new_vm_name: string;
  status: string;
  progress_pct: number;
  created_at: string;
  updated_at: string;
  region_display_name: string;
  error_message: string | null;
}

export async function apiRestorePoints(vmId: string): Promise<RestorePoint[]> {
  return tenantFetch<RestorePoint[]>(
    `/tenant/vms/${encodeURIComponent(vmId)}/restore-points`,
  );
}

export async function apiRestorePlan(body: {
  vm_id: string;
  snapshot_id: string;
  region_id: string;
  new_vm_name?: string;
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
  return tenantFetch<RestoreJob[]>(`/tenant/restore/jobs${q}`);
}

export async function apiRestoreJob(jobId: string): Promise<RestoreJob> {
  return tenantFetch<RestoreJob>(
    `/tenant/restore/jobs/${encodeURIComponent(jobId)}`,
  );
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

export async function apiRunbooks(): Promise<Runbook[]> {
  return tenantFetch<Runbook[]>("/tenant/runbooks");
}

export async function apiRunbook(name: string): Promise<Runbook> {
  return tenantFetch<Runbook>(`/tenant/runbooks/${encodeURIComponent(name)}`);
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
  return tenantFetch<ActivityRow[]>(`/tenant/events${qs}`);
}
