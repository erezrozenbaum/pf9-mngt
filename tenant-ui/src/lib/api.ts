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
  const isGet = !opts.method || opts.method.toUpperCase() === 'GET';
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    // X-Requested-With defeats simple form-based CSRF for all mutating requests (M6).
    ...(!isGet ? { 'X-Requested-With': 'XMLHttpRequest' } : {}),
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

export async function apiBranding(projectId?: string): Promise<Branding> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return tenantFetch<Branding>(`/tenant/branding${qs}`);
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
  disk_gb: number;
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
    disk_gb:             Number(r.disk_gb ?? 0),
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
    disk_gb:             Number(r.disk_gb ?? 0),
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
  error_message: string | null;
}

/** Raw snapshot history records for charting (status = OK | ERROR | SKIPPED) */
export async function apiSnapshotHistoryRaw(limit = 500): Promise<Array<{ created_at: string; status: string }>> {
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/snapshot-history?limit=${limit}`);
  const list = (Array.isArray(raw) ? raw : ((raw.records ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => ({
    created_at: String(r.created_at ?? r.run_date ?? ""),
    status:     String(r.status ?? "").toUpperCase(),
  }));
}

export async function apiSnapshotHistory(
  vmId?: string,
  fromDate?: string,
  toDate?: string,
  limit?: number,
): Promise<SnapshotRecord[]> {
  const q = new URLSearchParams();
  if (vmId)     q.set("vm_id",     vmId);
  if (fromDate) q.set("from_date", fromDate);
  if (toDate)   q.set("to_date",   toDate);
  if (limit)    q.set("limit",     String(limit));
  const qs = q.toString() ? `?${q.toString()}` : "";
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/snapshot-history${qs}`);
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
      error_message:       (r.error_message ?? null) as string | null,
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
  return list.map((r) => {
    const pct = typeof r.coverage_pct === "number" ? r.coverage_pct : 0;
    const isCompliant = Boolean(r.is_compliant);
    const status = isCompliant ? "covered" : pct >= 50 ? "partial" : "uncovered";
    return {
      vm_id:               String(r.vm_id ?? ""),
      vm_name:             String(r.vm_name ?? ""),
      region_display_name: String(r.region_display_name ?? r.region_id ?? ""),
      coverage_pct:        pct,
      current_streak:      typeof r.current_streak === "number" ? r.current_streak : 0,
      last_snapshot_ts:    (r.last_snapshot_ts ?? r.last_success_at ?? null) as string | null,
      status,
    };
  });
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
  ram_total_mb: number | null;
  vcpus: number | null;
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
    ram_total_mb:     (r.ram_total_mb ?? r.memory_total_mb ?? null) as number | null,
    vcpus:            (r.vcpus ?? null) as number | null,
    iops_read:        (r.iops_read   ?? null) as number | null,
    iops_write:       (r.iops_write  ?? null) as number | null,
    network_rx_mb:    (r.network_rx_mb  ?? r.network_rx_mbps  ?? null) as number | null,
    network_tx_mb:    (r.network_tx_mb  ?? r.network_tx_mbps  ?? null) as number | null,
    last_updated:     (r.last_updated ?? null) as string | null,
  };
}

export async function apiMetricsVms(): Promise<{ vms: VmMetrics[]; cacheAvailable: boolean; monitoringSource: string | null }> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/metrics/vms");
  const list = (Array.isArray(raw) ? raw : ((raw.vms ?? []) as unknown[])) as Record<string, unknown>[];
  return {
    vms: list.map(_normaliseMetrics),
    cacheAvailable: raw.cache_available !== false,
    monitoringSource: (raw.monitoring_source ?? null) as string | null,
  };
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
// Chargeback
// ---------------------------------------------------------------------------

export interface ChargebackVm {
  vm_id: string;
  vm_name: string;
  project_name: string;
  vcpus: number;
  ram_gb: number;
  disk_gb: number;
  flavor: string;
  cost_per_hour: number;
  compute_cost: number;
  storage_cost: number;
  snapshot_cost: number;
  snapshot_gb: number;
  snapshot_count: number;
  network_cost: number;
  estimated_cost: number;
  pricing_basis: string;
  last_metering: string | null;
}

export interface ChargebackSummary {
  currency: string;
  period_hours: number;
  period_label: string;
  vms: ChargebackVm[];
  total_estimated_cost: number;
  total_vms: number;
  cost_breakdown: {
    compute: number;
    storage: number;
    snapshots: number;
    network: number;
  };
  disclaimer: string;
  pricing_basis_note: string;
  timestamp: string;
}

export async function apiChargeback(hours = 720, currency?: string): Promise<ChargebackSummary> {
  const qs = `?hours=${hours}${currency ? `&currency=${encodeURIComponent(currency)}` : ""}`;
  return tenantFetch<ChargebackSummary>(`/tenant/metering/chargeback${qs}`);
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

export interface RestorePlanNetworkEntry {
  network_id: string | null;
  network_name: string | null;
  original_fixed_ip: string | null;
  will_request_fixed_ip: boolean;
  requested_ip: string | null;
  note: string;
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
  network_plan?: RestorePlanNetworkEntry[];
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
  result: { new_vm_id?: string; new_ips?: string[] } | null;
  restore_point_name: string | null;
}

function _normaliseJob(r: Record<string, unknown>): RestoreJob {
  const rawResult = r.result as Record<string, unknown> | null | undefined;
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
    result:              rawResult ? { new_vm_id: String(rawResult.new_vm_id ?? "") || undefined, new_ips: Array.isArray(rawResult.new_ips) ? rawResult.new_ips as string[] : [] } : null,
    restore_point_name:  (r.restore_point_name ?? null) as string | null,
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
  pre_restore_snapshot?: boolean;
  ip_strategy?: "NEW_IPS" | "TRY_SAME_IPS" | "MANUAL_IP";
  manual_ips?: Record<string, string>;
  network_override_id?: string;
  security_group_ids?: string[];
  cleanup_old_storage?: boolean;
  delete_source_snapshot?: boolean;
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

export interface AvailableSubnet {
  subnet_id: string;
  subnet_name: string;
  cidr: string;
  gateway_ip: string | null;
  available_ips: string[];
  available_count: number;
}

export interface AvailableIpsResponse {
  network_id: string;
  subnets: AvailableSubnet[];
}

export async function apiRestoreAvailableIps(networkId: string): Promise<AvailableIpsResponse> {
  return tenantFetch<AvailableIpsResponse>(
    `/tenant/restore/networks/${encodeURIComponent(networkId)}/available-ips`,
  );
}

export async function apiRestoreSendEmail(
  jobId: string,
  email: string,
): Promise<{ message: string }> {
  return tenantFetch(
    `/tenant/restore/jobs/${encodeURIComponent(jobId)}/send-summary-email`,
    { method: "POST", body: JSON.stringify({ email }) },
  );
}

// ---------------------------------------------------------------------------
// Inventory status
// ---------------------------------------------------------------------------

export interface InventoryStatus {
  last_sync_at: string | null;
  minutes_ago: number | null;
  duration_seconds: number | null;
}

export async function apiInventoryStatus(): Promise<InventoryStatus> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/inventory-status");
  return {
    last_sync_at:      (raw.last_sync_at      ?? null) as string | null,
    minutes_ago:       typeof raw.minutes_ago       === "number" ? raw.minutes_ago       : null,
    duration_seconds:  typeof raw.duration_seconds  === "number" ? raw.duration_seconds  : null,
  };
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
  supports_dry_run: boolean;
  parameters_schema: Record<string, unknown> | null;
  updated_at: string;
}

function _normaliseRunbook(r: Record<string, unknown>): Runbook {
  return {
    name:              String(r.name ?? ""),
    display_name:      String(r.display_name ?? r.name ?? ""),
    description:       String(r.description ?? ""),
    category:          String(r.category ?? "general"),
    risk_level:        String(r.risk_level ?? "low"),
    steps:             Array.isArray(r.steps) ? r.steps as string[] : [],
    prerequisites:     (r.prerequisites    ?? null) as string | null,
    expected_outcome:  (r.expected_outcome ?? null) as string | null,
    supports_dry_run:  Boolean(r.supports_dry_run ?? false),
    parameters_schema: (r.parameters_schema ?? null) as Record<string, unknown> | null,
    updated_at:        String(r.updated_at ?? ""),
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

export interface RunbookExecution {
  execution_id: string;
  runbook_name: string;
  display_name: string;
  status: string;
  dry_run: boolean;
  parameters: Record<string, unknown>;
  result: Record<string, unknown> | null;
  triggered_by: string;
  triggered_at: string;
  completed_at: string | null;
  error_message: string | null;
  risk_level: string;
  items_found: number;
  items_actioned: number;
}

export async function apiExecuteRunbook(
  name: string,
  params: Record<string, unknown> = {},
  dryRun = false,
): Promise<RunbookExecution> {
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/runbooks/${encodeURIComponent(name)}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parameters: params, dry_run: dryRun }),
  });
  // Normalise to ensure all required string fields are present
  return {
    execution_id:  String(raw.execution_id ?? ""),
    runbook_name:  String(raw.runbook_name ?? name),
    display_name:  String(raw.display_name ?? raw.runbook_name ?? name),
    status:        String(raw.status ?? "executing"),
    dry_run:       Boolean(raw.dry_run ?? dryRun),
    parameters:    (raw.parameters ?? params) as Record<string, unknown>,
    result:        (raw.result ?? null) as Record<string, unknown> | null,
    triggered_by:  String(raw.triggered_by ?? ""),
    triggered_at:  String(raw.triggered_at ?? new Date().toISOString()),
    completed_at:  (raw.completed_at ?? null) as string | null,
    error_message: (raw.error_message ?? null) as string | null,
    risk_level:    String(raw.risk_level ?? "low"),
    items_found:   Number(raw.items_found ?? 0),
    items_actioned: Number(raw.items_actioned ?? 0),
  };
}

export async function apiRunbookExecutions(): Promise<RunbookExecution[]> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/runbook-executions");
  const list = (Array.isArray(raw) ? raw : ((raw.executions ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((e) => ({
    execution_id:  String(e.execution_id ?? ""),
    runbook_name:  String(e.runbook_name ?? ""),
    display_name:  String(e.display_name ?? e.runbook_name ?? ""),
    status:        String(e.status ?? ""),
    dry_run:       Boolean(e.dry_run),
    parameters:    (e.parameters ?? {}) as Record<string, unknown>,
    result:        (e.result ?? null) as Record<string, unknown> | null,
    triggered_by:  String(e.triggered_by ?? ""),
    triggered_at:  String(e.triggered_at ?? ""),
    completed_at:  (e.completed_at ?? null) as string | null,
    error_message: (e.error_message ?? null) as string | null,
    risk_level:    String(e.risk_level ?? "low"),
    items_found:   Number(e.items_found ?? 0),
    items_actioned: Number(e.items_actioned ?? 0),
  }));
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
  username: string | null;
  keystone_user_id: string | null;
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
    username:      (e.username ?? null) as string | null,
    keystone_user_id: (e.keystone_user_id ?? null) as string | null,
  }));
}

// ---------------------------------------------------------------------------
// Security groups (for restore configuration)
// ---------------------------------------------------------------------------

export interface SecurityGroup {
  id: string;
  name: string;
  description: string;
  project_id: string;
}

export async function apiSecurityGroups(): Promise<SecurityGroup[]> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/security-groups");
  const list = (Array.isArray(raw) ? raw : ((raw.security_groups ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => ({
    id:          String(r.id ?? ""),
    name:        String(r.name ?? ""),
    description: String(r.description ?? ""),
    project_id:  String(r.project_id ?? ""),
  }));
}

// ---------------------------------------------------------------------------
// Sync and snapshot now
// ---------------------------------------------------------------------------

export async function apiSyncAndSnapshot(): Promise<{ message: string; status: string }> {
  return tenantFetch("/tenant/sync-and-snapshot", { method: "POST" });
}

// ---------------------------------------------------------------------------
// Tenant reports
// ---------------------------------------------------------------------------

export interface TenantReport {
  name: string;
  display_name: string;
  description: string;
  category: string;
  download_url: string | null;
}

export async function apiTenantReports(): Promise<TenantReport[]> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/reports");
  const list = (Array.isArray(raw) ? raw : ((raw.reports ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => ({
    name:         String(r.name ?? ""),
    display_name: String(r.display_name ?? r.name ?? ""),
    description:  String(r.description ?? ""),
    category:     String(r.category ?? "general"),
    download_url: (r.download_url ?? null) as string | null,
  }));
}

export async function apiDownloadTenantReport(reportName: string, params?: { from_date?: string; to_date?: string }): Promise<Blob> {
  const q = new URLSearchParams();
  if (params?.from_date) q.set("from_date", params.from_date);
  if (params?.to_date) q.set("to_date", params.to_date);
  const qs = q.toString() ? `?${q.toString()}` : "";
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`/tenant/reports/${encodeURIComponent(reportName)}/download${qs}`, { headers });
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  return res.blob();
}

// ---------------------------------------------------------------------------
// Quota usage
// ---------------------------------------------------------------------------

export interface QuotaItem {
  limit: number;
  used: number;
}

export interface QuotaData {
  totals: {
    compute: {
      instances: QuotaItem;
      cores: QuotaItem;
      ram_mb: QuotaItem;
    };
    storage: {
      volumes: QuotaItem;
      gigabytes: QuotaItem;
      snapshots: QuotaItem;
    };
  };
  projects: Array<{
    project_id: string;
    compute: { instances: QuotaItem; cores: QuotaItem; ram_mb: QuotaItem };
    storage: { volumes: QuotaItem; gigabytes: QuotaItem; snapshots: QuotaItem };
  }>;
}

export async function apiQuota(): Promise<QuotaData> {
  return tenantFetch<QuotaData>("/tenant/quota");
}

// ---------------------------------------------------------------------------
// Networks
// ---------------------------------------------------------------------------

export interface Subnet {
  id: string;
  name: string;
  cidr: string;
  gateway_ip: string;
  enable_dhcp: boolean | null;
  region_id: string;
}

export interface Network {
  id: string;
  name: string;
  status: string;
  admin_state_up: boolean | null;
  is_shared: boolean | null;
  is_external: boolean | null;
  project_id: string;
  region_id: string;
  subnets: Subnet[];
}

export async function apiNetworks(): Promise<Network[]> {
  const raw = await tenantFetch<Record<string, unknown>>("/tenant/networks");
  const list = (Array.isArray(raw) ? raw : ((raw.networks ?? []) as unknown[])) as Record<string, unknown>[];
  return list.map((r) => ({
    id: String(r.id ?? ""),
    name: String(r.name ?? ""),
    status: String(r.status ?? ""),
    admin_state_up: (r.admin_state_up ?? null) as boolean | null,
    is_shared: (r.is_shared ?? null) as boolean | null,
    is_external: (r.is_external ?? null) as boolean | null,
    project_id: String(r.project_id ?? ""),
    region_id: String(r.region_id ?? ""),
    subnets: ((r.subnets ?? []) as Record<string, unknown>[]).map((s) => ({
      id: String(s.id ?? ""),
      name: String(s.name ?? ""),
      cidr: String(s.cidr ?? ""),
      gateway_ip: String(s.gateway_ip ?? ""),
      enable_dhcp: (s.enable_dhcp ?? null) as boolean | null,
      region_id: String(s.region_id ?? ""),
    })),
  }));
}

export interface UsedIpEntry {
  vm_id: string;
  vm_name: string;
  ips: string[];
}

export async function apiNetworkUsedIps(networkId: string): Promise<UsedIpEntry[]> {
  const raw = await tenantFetch<Record<string, unknown>>(`/tenant/networks/${encodeURIComponent(networkId)}/used-ips`);
  return ((raw.used ?? []) as Record<string, unknown>[]).map((r) => ({
    vm_id: String(r.vm_id ?? ""),
    vm_name: String(r.vm_name ?? ""),
    ips: ((r.ips ?? []) as unknown[]).map(String),
  }));
}

// ---------------------------------------------------------------------------
// Security Group detail + rule management
// ---------------------------------------------------------------------------

export interface SgRule {
  id: string;
  direction: string;
  ethertype: string;
  protocol: string;
  port_range_min: number | null;
  port_range_max: number | null;
  remote_ip_prefix: string;
  remote_group_id: string;
  description: string;
}

export interface SgDetail {
  id: string;
  name: string;
  description: string;
  project_id: string;
  rules: SgRule[];
}

export async function apiSecurityGroupDetail(sgId: string): Promise<SgDetail> {
  return tenantFetch<SgDetail>(`/tenant/security-groups/${encodeURIComponent(sgId)}`);
}

export interface AddRuleRequest {
  direction: "ingress" | "egress";
  ethertype?: string;
  protocol?: string | null;
  port_range_min?: number | null;
  port_range_max?: number | null;
  remote_ip_prefix?: string | null;
  remote_group_id?: string | null;
  description?: string;
}

export async function apiAddSgRule(sgId: string, rule: AddRuleRequest): Promise<SgRule> {
  return tenantFetch<SgRule>(`/tenant/security-groups/${encodeURIComponent(sgId)}/rules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rule),
  });
}

export async function apiDeleteSgRule(sgId: string, ruleId: string): Promise<void> {
  await tenantFetch<void>(`/tenant/security-groups/${encodeURIComponent(sgId)}/rules/${encodeURIComponent(ruleId)}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Resource dependency graph
// ---------------------------------------------------------------------------

export interface GraphNode { id: string; name: string; project_id: string; }
export interface GraphVmNode extends GraphNode { status: string; }
export interface GraphSubnetNode { id: string; name: string; network_id: string; cidr: string; }
export interface GraphVolumeNode { id: string; name: string; server_id: string; size_gb: number; }

export interface ResourceGraph {
  nodes: {
    vms: GraphVmNode[];
    networks: GraphNode[];
    subnets: GraphSubnetNode[];
    security_groups: GraphNode[];
    volumes: GraphVolumeNode[];
  };
  edges: {
    vm_network: Array<{ vm_id: string; network_id: string }>;
    network_subnet: Array<{ network_id: string; subnet_id: string }>;
    vm_sg: Array<{ vm_id: string; sg_id: string }>;
    vm_volume: Array<{ vm_id: string; volume_id: string }>;
  };
}

export async function apiResourceGraph(): Promise<ResourceGraph> {
  return tenantFetch<ResourceGraph>("/tenant/resource-graph");
}

// ---------------------------------------------------------------------------
// VM Provisioning
// ---------------------------------------------------------------------------

export interface FlavorOption { id: string; name: string; vcpus: number; ram_mb: number; disk_gb: number | null; }
export interface ImageOption  { id: string; name: string; os_distro: string; status: string; }
export interface NetworkOption { id: string; name: string; is_shared: boolean | null; subnets?: Array<{ id: string; name: string; cidr: string }>; }
export interface SgOption { id: string; name: string; }

export interface ProvisionResources {
  flavors: FlavorOption[];
  images: ImageOption[];
  networks: NetworkOption[];
  security_groups: SgOption[];
}

export async function apiProvisionResources(): Promise<ProvisionResources> {
  return tenantFetch<ProvisionResources>("/tenant/provision/resources");
}

export interface ProvisionVmRequest {
  name: string;
  flavor_id: string;
  image_id: string;
  network_id: string;
  security_group_ids?: string[];
  user_data?: string;
  fixed_ip?: string;
  count?: number;
}

export async function apiProvisionVm(body: ProvisionVmRequest): Promise<{ created: Array<{ id: string; name: string; status: string }>; count: number }> {
  return tenantFetch("/tenant/vms", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

