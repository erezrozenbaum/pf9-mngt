/**
 * MeteringTab – Operational Resource Metering
 *
 * Eight sub-tabs:
 *   1) Overview     – MSP executive dashboard with totals
 *   2) Resources    – per-VM CPU / RAM / Disk / Network usage (sortable)
 *   3) Snapshots    – snapshot storage metering
 *   4) Restores     – restore operation metering
 *   5) API Usage    – API call volume & latency
 *   6) Efficiency   – per-VM efficiency scores
 *   7) Pricing      – flavor / storage cost configuration
 *   8) Export       – CSV download for all categories + chargeback
 */

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { API_BASE } from "../config";
import { useClusterContext } from "./ClusterContext";

// ─── Helpers ─────────────────────────────────────────────────────────────────

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
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error ${res.status}`);
  }
  return res.json();
}

function fmtNum(v: number | null | undefined, decimals = 1): string {
  if (v == null) return "—";
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${Number(v).toFixed(1)}%`;
}

function fmtBytes(bytes: number | null | undefined): string {
  if (bytes == null || bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

function fmtDate(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString();
}

function fmtDuration(sec: number | null | undefined): string {
  if (sec == null) return "—";
  if (sec < 60) return `${Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m ${s}s`;
}

// ─── Types ───────────────────────────────────────────────────────────────────

type SubTab = "overview" | "resources" | "snapshots" | "restores" | "api_usage" | "efficiency" | "pricing" | "chargeback" | "growth" | "export";

interface MeteringConfig {
  enabled: boolean;
  collection_interval_min: number;
  retention_days: number;
  cost_per_vcpu_hour: number;
  cost_per_gb_ram_hour: number;
  cost_per_gb_storage_month: number;
  cost_per_snapshot_gb_month: number;
  cost_per_api_call: number;
  cost_currency: string;
  updated_at: string | null;
}

interface OverviewData {
  total_vms_metered: number;
  resources: {
    total_vcpus: number;
    total_ram_mb: number;
    total_disk_gb: number;
    avg_cpu_usage: number;
    avg_ram_usage: number;
    avg_disk_usage: number;
  };
  snapshots: {
    total_snapshots: number;
    total_snapshot_gb: number;
    compliant_count: number;
    non_compliant_count: number;
  };
  restores: {
    total_restores: number;
    successful: number;
    failed: number;
    avg_duration_sec: number;
  };
  api_usage: {
    total_api_calls: number;
    total_api_errors: number;
    avg_api_latency_ms: number;
  };
  efficiency: {
    avg_efficiency: number;
    excellent_count: number;
    good_count: number;
    fair_count: number;
    poor_count: number;
    idle_count: number;
  };
}

interface ResourceRow {
  id: number;
  collected_at: string;
  vm_id: string;
  vm_name: string | null;
  vm_ip: string | null;
  project_name: string | null;
  domain: string | null;
  host: string | null;
  flavor: string | null;
  vcpus_allocated: number | null;
  ram_allocated_mb: number | null;
  disk_allocated_gb: number | null;
  cpu_usage_percent: number | null;
  ram_usage_mb: number | null;
  ram_usage_percent: number | null;
  disk_used_gb: number | null;
  disk_usage_percent: number | null;
  network_rx_bytes: number | null;
  network_tx_bytes: number | null;
  storage_read_bytes: number | null;
  storage_write_bytes: number | null;
  project_id?: string | null;
}

interface SnapshotRow {
  id: number;
  collected_at: string;
  snapshot_id: string;
  snapshot_name: string | null;
  volume_id: string | null;
  volume_name: string | null;
  project_name: string | null;
  domain: string | null;
  size_gb: number | null;
  status: string | null;
  policy_name: string | null;
  is_compliant: boolean | null;
  created_at: string | null;
}

interface RestoreRow {
  id: number;
  collected_at: string;
  restore_id: string | null;
  snapshot_id: string | null;
  snapshot_name: string | null;
  target_server_id: string | null;
  target_server_name: string | null;
  project_name: string | null;
  domain: string | null;
  status: string | null;
  duration_seconds: number | null;
  initiated_by: string | null;
  initiated_at: string | null;
}

interface ApiUsageRow {
  id: number;
  collected_at: string;
  interval_start: string;
  interval_end: string;
  endpoint: string;
  method: string;
  total_calls: number;
  error_count: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
}

interface EfficiencyRow {
  id: number;
  collected_at: string;
  vm_id: string;
  vm_name: string | null;
  project_name: string | null;
  domain: string | null;
  cpu_efficiency: number | null;
  ram_efficiency: number | null;
  storage_efficiency: number | null;
  overall_score: number | null;
  classification: string | null;
  recommendation: string | null;
}

interface FlavorPrice {
  id: number;
  category: string;
  item_name: string;
  unit: string;
  cost_per_hour: number;
  cost_per_month: number;
  currency: string;
  notes: string | null;
  vcpus: number | null;
  ram_gb: number | null;
  disk_gb: number | null;
  disk_cost_per_gb: number | null;
  auto_populated: boolean;
}

interface PricingItem {
  id?: number;
  category: string;
  item_name: string;
  unit: string;
  cost_per_hour: number;
  cost_per_month: number;
  currency: string;
  notes: string;
  vcpus?: number;
  ram_gb?: number;
  disk_gb?: number;
  disk_cost_per_gb?: number;
}

interface FiltersData {
  projects: string[];
  domains: string[];
  flavors: { name: string; vcpus: number; ram_mb: number; disk_gb: number }[];
}

// ─── Shared Styles ───────────────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  marginLeft: 6,
  padding: "6px 10px",
  borderRadius: 6,
  border: "1px solid var(--color-border, #ddd)",
  background: "var(--color-surface, #fff)",
  color: "var(--color-text-primary, #212121)",
  fontSize: "0.85em",
};

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: "pointer",
};

const btnPrimary: React.CSSProperties = {
  padding: "6px 16px",
  borderRadius: 6,
  border: "none",
  background: "var(--color-primary, #1976D2)",
  color: "#fff",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: "0.85em",
};

const btnOutline: React.CSSProperties = {
  padding: "6px 16px",
  borderRadius: 6,
  border: "1px solid var(--color-border, #ddd)",
  background: "transparent",
  color: "var(--color-text-primary, #212121)",
  cursor: "pointer",
  fontWeight: 500,
  fontSize: "0.85em",
};

const cardStyle: React.CSSProperties = {
  padding: "14px 18px",
  background: "var(--color-surface, #fff)",
  borderRadius: 8,
  border: "1px solid var(--color-border, #e0e0e0)",
  boxShadow: "var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.08))",
};

// ─── Sortable header helper ─────────────────────────────────────────────────

type SortDir = "asc" | "desc";

function SortHeader({
  label,
  field,
  sortField,
  sortDir,
  onSort,
}: {
  label: string;
  field: string;
  sortField: string;
  sortDir: SortDir;
  onSort: (f: string) => void;
}) {
  const active = sortField === field;
  return (
    <th
      onClick={() => onSort(field)}
      style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}
    >
      {label}{" "}
      <span style={{ opacity: active ? 1 : 0.3, fontSize: "0.8em" }}>
        {active ? (sortDir === "asc" ? "▲" : "▼") : "⇅"}
      </span>
    </th>
  );
}

function sortRows<T>(rows: T[], field: string, dir: SortDir): T[] {
  return [...rows].sort((a, b) => {
    const va = (a as any)[field];
    const vb = (b as any)[field];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === "string") return dir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
    return dir === "asc" ? va - vb : vb - va;
  });
}

// ─── Component ───────────────────────────────────────────────────────────────

interface MeteringTabProps {
  isAdmin: boolean;
}

const SUB_TABS: { id: SubTab; label: string }[] = [
  { id: "overview", label: "📊 Overview" },
  { id: "resources", label: "🖥 Resources" },
  { id: "snapshots", label: "📸 Snapshots" },
  { id: "restores", label: "🔅 Restores" },
  { id: "api_usage", label: "🔌 API Usage" },
  { id: "efficiency", label: "⚡ Efficiency" },
  { id: "pricing", label: "💰 Pricing" },
  { id: "chargeback", label: "🧾 Chargeback" },
  { id: "growth", label: "📈 Tenant Growth" },
  { id: "export", label: "📥 Export" },
];

const CURRENCIES = ["USD", "EUR", "GBP", "ILS", "JPY", "CAD", "AUD", "CHF", "INR"];

export default function MeteringTab({ isAdmin: _isAdmin }: MeteringTabProps) {
  const { selectedRegionId } = useClusterContext();
  const [subTab, setSubTab] = useState<SubTab>("overview");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [projectFilter, setProjectFilter] = useState("");
  const [domainFilter, setDomainFilter] = useState("");
  const [hoursFilter, setHoursFilter] = useState(24);

  // Data states
  const [config, setConfig] = useState<MeteringConfig | null>(null);
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [resources, setResources] = useState<ResourceRow[]>([]);
  const [snapshots, setSnapshots] = useState<SnapshotRow[]>([]);
  const [restores, setRestores] = useState<RestoreRow[]>([]);
  const [apiUsage, setApiUsage] = useState<ApiUsageRow[]>([]);
  const [efficiency, setEfficiency] = useState<EfficiencyRow[]>([]);
  const [pricingItems, setPricingItems] = useState<FlavorPrice[]>([]);
  const [filtersData, setFiltersData] = useState<FiltersData | null>(null);

  // Sort state
  const [sortField, setSortField] = useState("collected_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Export currency override
  const [exportCurrency, setExportCurrency] = useState("");

  // Chargeback summary
  const [chargebackData, setChargebackData] = useState<any | null>(null);
  const [chargebackCurrency, setChargebackCurrency] = useState("USD");
  const [chargebackHours, setChargebackHours] = useState(720);

  // Tenant growth
  const [growthData, setGrowthData] = useState<any | null>(null);
  const [growthMonths, setGrowthMonths] = useState(6);

  // Email export
  const [emailTo, setEmailTo] = useState("");
  const [emailFormat, setEmailFormat] = useState("excel");
  const [emailSending, setEmailSending] = useState(false);
  const [emailMsg, setEmailMsg] = useState<string | null>(null);

  // Flavor pricing edit
  const [editingPricing, setEditingPricing] = useState<Partial<PricingItem> | null>(null);
  const [pricingCategoryFilter, setPricingCategoryFilter] = useState<string>("all");
  const [pricingSearchQuery, setPricingSearchQuery] = useState("");
  const [pricingSortField, setPricingSortField] = useState<string>("category");
  const [pricingSortDir, setPricingSortDir] = useState<"asc" | "desc">("asc");

  // Inquiry ticket creation
  const [inquiryFor, setInquiryFor] = useState<{project_id:string; project_name:string; vm_name:string} | null>(null);
  const [inquiryCreating, setInquiryCreating] = useState(false);
  const [inquiryDepts, setInquiryDepts] = useState<{id:number; name:string}[]>([]);
  const [inquiryDeptId, setInquiryDeptId] = useState<number>(0);
  const [inquiryTitle, setInquiryTitle] = useState("");
  const [inquiryNote, setInquiryNote] = useState("");

  const handleSort = useCallback((field: string) => {
    setSortDir((prev) => (sortField === field ? (prev === "asc" ? "desc" : "asc") : "desc"));
    setSortField(field);
  }, [sortField]);

  // ─── Fetch helpers ─────────────────────────────────────────────────────

  const buildQuery = useCallback(() => {
    const params = new URLSearchParams();
    if (projectFilter) params.set("project", projectFilter);
    if (domainFilter) params.set("domain", domainFilter);
    params.set("hours", String(hoursFilter));
    if (selectedRegionId) params.set("region_id", selectedRegionId);
    return params.toString();
  }, [projectFilter, domainFilter, hoursFilter, selectedRegionId]);

  const loadConfig = useCallback(async () => {
    try {
      const data = await apiFetch<MeteringConfig>("/api/metering/config");
      setConfig(data);
      if (!exportCurrency) setExportCurrency(data.cost_currency || "USD");
    } catch {
      // Config may not be available yet
    }
  }, [exportCurrency]);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams();
      if (projectFilter) q.set("project", projectFilter);
      if (domainFilter) q.set("domain", domainFilter);
      if (selectedRegionId) q.set("region_id", selectedRegionId);
      const data = await apiFetch<OverviewData>(`/api/metering/overview?${q}`);
      setOverview(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [projectFilter, domainFilter]);

  const loadResources = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ data: ResourceRow[] }>(`/api/metering/resources?${buildQuery()}`);
      setResources(data.data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [buildQuery]);

  const loadSnapshots = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ data: SnapshotRow[] }>(`/api/metering/snapshots?${buildQuery()}`);
      setSnapshots(data.data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [buildQuery]);

  const loadRestores = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ data: RestoreRow[] }>(`/api/metering/restores?${buildQuery()}`);
      setRestores(data.data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [buildQuery]);

  const loadApiUsage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("hours", String(hoursFilter));
      const data = await apiFetch<{ data: ApiUsageRow[] }>(`/api/metering/api-usage?${params}`);
      setApiUsage(data.data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [hoursFilter]);

  const loadEfficiency = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ data: EfficiencyRow[] }>(`/api/metering/efficiency?${buildQuery()}`);
      setEfficiency(data.data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [buildQuery]);

  const loadPricing = useCallback(async () => {
    try {
      const data = await apiFetch<FlavorPrice[]>("/api/metering/pricing");
      setPricingItems(data);
    } catch {
      // endpoint may not exist yet
    }
  }, []);

  const loadChargebackSummary = useCallback(async (currency: string, hours: number) => {
    try {
      setLoading(true);
      const params = new URLSearchParams({ currency, hours: String(hours) });
      if (domainFilter) params.set("domain", domainFilter);
      const data = await apiFetch<any>(`/api/metering/chargeback-summary?${params}`);
      setChargebackData(data);
    } catch (err: any) {
      setError(err.message || "Failed to load chargeback summary");
    } finally {
      setLoading(false);
    }
  }, [domainFilter]);

  const loadGrowth = useCallback(async (months: number) => {
    try {
      setLoading(true);
      const params = new URLSearchParams({ months: String(months) });
      if (domainFilter) params.set("domain", domainFilter);
      const data = await apiFetch<any>(`/api/metering/tenant-growth?${params}`);
      setGrowthData(data);
    } catch (err: any) {
      setError(err.message || "Failed to load tenant growth");
    } finally {
      setLoading(false);
    }
  }, [domainFilter]);

  const loadFilters = useCallback(async () => {
    try {
      const data = await apiFetch<FiltersData>("/api/metering/filters");
      setFiltersData(data);
    } catch {
      // filters endpoint may not exist yet
    }
  }, []);

  // ─── Load data on tab change ───────────────────────────────────────────

  useEffect(() => {
    loadConfig();
    loadFilters();
  }, [loadConfig, loadFilters]);

  useEffect(() => {
    if (subTab === "overview") loadOverview();
    else if (subTab === "resources") loadResources();
    else if (subTab === "snapshots") loadSnapshots();
    else if (subTab === "restores") loadRestores();
    else if (subTab === "api_usage") loadApiUsage();
    else if (subTab === "efficiency") loadEfficiency();
    else if (subTab === "pricing") loadPricing();
    else if (subTab === "chargeback") loadChargebackSummary(chargebackCurrency, chargebackHours);
    else if (subTab === "growth") loadGrowth(growthMonths);
  }, [subTab, loadOverview, loadResources, loadSnapshots, loadRestores, loadApiUsage, loadEfficiency, loadPricing, loadChargebackSummary, loadGrowth, chargebackCurrency, chargebackHours, growthMonths]);

  // ─── Sorted data ──────────────────────────────────────────────────────

  const sortedResources = useMemo(() => sortRows(resources, sortField, sortDir), [resources, sortField, sortDir]);
  const sortedSnapshots = useMemo(() => sortRows(snapshots, sortField, sortDir), [snapshots, sortField, sortDir]);
  const sortedRestores = useMemo(() => sortRows(restores, sortField, sortDir), [restores, sortField, sortDir]);
  const sortedApiUsage = useMemo(() => sortRows(apiUsage, sortField, sortDir), [apiUsage, sortField, sortDir]);
  const sortedEfficiency = useMemo(() => sortRows(efficiency, sortField, sortDir), [efficiency, sortField, sortDir]);

  // ─── Export handler ────────────────────────────────────────────────────

  const triggerExport = async (type: string) => {
    const token = getToken();
    const params = new URLSearchParams();
    if (projectFilter) params.set("project", projectFilter);
    if (domainFilter) params.set("domain", domainFilter);
    params.set("hours", String(hoursFilter));
    if ((type === "chargeback" || type === "chargeback-excel" || type === "chargeback-pdf") && exportCurrency) {
      params.set("currency", exportCurrency);
    }

    try {
      const res = await fetch(`${API_BASE}/api/metering/export/${type}?${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const disposition = res.headers.get("content-disposition") || "";
      const match = disposition.match(/filename="?(.+?)"?$/);
      a.download = match ? match[1] : `metering_${type}.csv`;
      a.href = url;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      alert(`Export error: ${e.message}`);
    }
  };

  // ─── Flavor pricing save ──────────────────────────────────────────────

  const savePricingItem = async () => {
    if (!editingPricing) return;
    try {
      if (editingPricing.id) {
        await apiFetch(`/api/metering/pricing/${editingPricing.id}`, {
          method: "PUT",
          body: JSON.stringify(editingPricing),
        });
      } else {
        await apiFetch("/api/metering/pricing", {
          method: "POST",
          body: JSON.stringify(editingPricing),
        });
      }
      setEditingPricing(null);
      loadPricing();
    } catch (e: any) {
      alert(`Save error: ${e.message}`);
    }
  };

  const deletePricingItem = async (id: number) => {
    if (!confirm("Delete this pricing entry?")) return;
    try {
      await apiFetch(`/api/metering/pricing/${id}`, { method: "DELETE" });
      loadPricing();
    } catch (e: any) {
      alert(`Delete error: ${e.message}`);
    }
  };

  const syncFlavors = async () => {
    try {
      const res = await apiFetch<{ detail: string; inserted: number }>("/api/metering/pricing/sync-flavors", {
        method: "POST",
      });
      alert(res.detail);
      loadPricing();
    } catch (e: any) {
      alert(`Sync error: ${e.message}`);
    }
  };

  // ─── Classification badge ─────────────────────────────────────────────

  const classificationBadge = (cls: string | null) => {
    const colors: Record<string, string> = {
      excellent: "#22c55e",
      good: "#84cc16",
      fair: "#eab308",
      poor: "#f97316",
      idle: "#ef4444",
    };
    const bg = colors[cls || ""] || "#6b7280";
    return (
      <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: 4, color: "#fff", fontSize: "0.8em", fontWeight: 600, background: bg, textTransform: "capitalize" }}>
        {cls || "—"}
      </span>
    );
  };

  // ─── Refresh for current tab ──────────────────────────────────────────

  const refreshTab = () => {
    if (subTab === "overview") loadOverview();
    else if (subTab === "resources") loadResources();
    else if (subTab === "snapshots") loadSnapshots();
    else if (subTab === "restores") loadRestores();
    else if (subTab === "api_usage") loadApiUsage();
    else if (subTab === "efficiency") loadEfficiency();
    else if (subTab === "pricing") loadPricing();
    else if (subTab === "chargeback") loadChargebackSummary(chargebackCurrency, chargebackHours);
    else if (subTab === "growth") loadGrowth(growthMonths);
  };

  // ─── Filter bar (shared) ──────────────────────────────────────────────

  const filterBar = (showHours = true, showRefresh = true) => (
    <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
      <label style={{ fontSize: "0.85em", color: "var(--color-text-primary, #212121)", display: "flex", alignItems: "center", gap: 4 }}>
        Tenant / Project:
        <select value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)} style={{ ...selectStyle, width: 180 }}>
          <option value="">All projects</option>
          {filtersData?.projects.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </label>
      <label style={{ fontSize: "0.85em", color: "var(--color-text-primary, #212121)", display: "flex", alignItems: "center", gap: 4 }}>
        Domain:
        <select value={domainFilter} onChange={(e) => setDomainFilter(e.target.value)} style={{ ...selectStyle, width: 180 }}>
          <option value="">All domains</option>
          {filtersData?.domains.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </label>
      {showHours && (
        <label style={{ fontSize: "0.85em", color: "var(--color-text-primary, #212121)", display: "flex", alignItems: "center", gap: 4 }}>
          Lookback:
          <select value={hoursFilter} onChange={(e) => setHoursFilter(Number(e.target.value))} style={selectStyle}>
            <option value={1}>1 Hour</option>
            <option value={6}>6 Hours</option>
            <option value={24}>24 Hours</option>
            <option value={72}>3 Days</option>
            <option value={168}>7 Days</option>
            <option value={720}>30 Days</option>
            <option value={2160}>90 Days</option>
          </select>
        </label>
      )}
      {showRefresh && (
        <button onClick={refreshTab} style={btnPrimary}>
          🔄 Refresh
        </button>
      )}
    </div>
  );

  // ─── Render ────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: "0 16px 24px" }}>
      {/* Sub-tab bar */}
      <div style={{ display: "flex", gap: 4, borderBottom: "2px solid var(--color-border, #e0e0e0)", marginBottom: 16, flexWrap: "wrap" }}>
        {SUB_TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => { setSubTab(t.id); setSortField("collected_at"); setSortDir("desc"); }}
            style={{
              padding: "8px 16px",
              background: subTab === t.id ? "var(--color-primary, #1976D2)" : "transparent",
              color: subTab === t.id ? "#fff" : "var(--color-text-primary, #555)",
              border: "none",
              borderBottom: subTab === t.id ? "2px solid var(--color-primary, #1976D2)" : "2px solid transparent",
              cursor: "pointer",
              fontWeight: subTab === t.id ? 600 : 400,
              borderRadius: "6px 6px 0 0",
              fontSize: "0.9em",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <div style={{ color: "#d32f2f", padding: "10px 14px", background: "var(--color-surface, #fff)", borderRadius: 6, marginBottom: 12, border: "1px solid #ef5350" }}>
          ⚠️ {error}
        </div>
      )}

      {loading && <div style={{ padding: 20, textAlign: "center", color: "var(--color-text-secondary, #666)" }}>Loading…</div>}

      {/* ═══════════════════════════ OVERVIEW ═══════════════════════════ */}
      {subTab === "overview" && !loading && overview && (
        <div>
          {filterBar(false)}

          {/* Resources row */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12, marginBottom: 20 }}>
            <SummaryCard title="VMs Metered" value={overview.total_vms_metered} />
            <SummaryCard title="Total vCPUs" value={overview.resources.total_vcpus} />
            <SummaryCard title="Total RAM" value={`${fmtNum(overview.resources.total_ram_mb / 1024, 1)} GB`} />
            <SummaryCard title="Total Disk" value={`${fmtNum(overview.resources.total_disk_gb)} GB`} />
            <SummaryCard title="Avg CPU Usage" value={fmtPct(overview.resources.avg_cpu_usage)} />
            <SummaryCard title="Avg RAM Usage" value={fmtPct(overview.resources.avg_ram_usage)} />
          </div>

          {/* Snapshots row */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12, marginBottom: 20 }}>
            <SummaryCard title="Snapshots" value={overview.snapshots.total_snapshots} />
            <SummaryCard title="Snapshot Storage" value={`${fmtNum(overview.snapshots.total_snapshot_gb)} GB`} />
            <SummaryCard title="Compliant" value={overview.snapshots.compliant_count} color="#4CAF50" />
            <SummaryCard title="Non-Compliant" value={overview.snapshots.non_compliant_count} color="#F44336" />
          </div>

          {/* Restores row */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12, marginBottom: 20 }}>
            <SummaryCard title="Restores (7d)" value={overview.restores.total_restores} />
            <SummaryCard title="Successful" value={overview.restores.successful} color="#4CAF50" />
            <SummaryCard title="Failed" value={overview.restores.failed} color="#F44336" />
            <SummaryCard title="Avg Duration" value={fmtDuration(overview.restores.avg_duration_sec)} />
          </div>

          {/* API row */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12, marginBottom: 20 }}>
            <SummaryCard title="API Calls (24h)" value={overview.api_usage.total_api_calls} />
            <SummaryCard title="API Errors" value={overview.api_usage.total_api_errors} color={overview.api_usage.total_api_errors > 0 ? "#FF9800" : undefined} />
            <SummaryCard title="Avg Latency" value={`${fmtNum(overview.api_usage.avg_api_latency_ms)} ms`} />
          </div>

          {/* Efficiency row */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
            <SummaryCard title="Avg Efficiency" value={fmtPct(overview.efficiency.avg_efficiency)} />
            <SummaryCard title="Excellent" value={overview.efficiency.excellent_count} color="#4CAF50" />
            <SummaryCard title="Good" value={overview.efficiency.good_count} color="#8BC34A" />
            <SummaryCard title="Fair" value={overview.efficiency.fair_count} color="#FFC107" />
            <SummaryCard title="Poor" value={overview.efficiency.poor_count} color="#FF9800" />
            <SummaryCard title="Idle" value={overview.efficiency.idle_count} color="#F44336" />
          </div>

          {/* Config summary */}
          {config && (
            <div style={{ marginTop: 24, ...cardStyle }}>
              <h3 style={{ margin: "0 0 10px", fontSize: "1em", color: "var(--color-text-primary, #212121)" }}>Metering Configuration</h3>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8, fontSize: "0.85em", color: "var(--color-text-primary, #212121)" }}>
                <div><strong>Status:</strong> {config.enabled ? "✅ Enabled" : "❌ Disabled"}</div>
                <div><strong>Collection Interval:</strong> {config.collection_interval_min} min</div>
                <div><strong>Data Retention:</strong> {config.retention_days} days</div>
                <div><strong>Currency:</strong> {config.cost_currency}</div>
                <div><strong>vCPU Cost/Hour:</strong> {config.cost_per_vcpu_hour}</div>
                <div><strong>RAM Cost/GB·Hour:</strong> {config.cost_per_gb_ram_hour}</div>
                <div><strong>Storage Cost/GB·Month:</strong> {config.cost_per_gb_storage_month}</div>
                <div><strong>Snapshot Cost/GB·Month:</strong> {config.cost_per_snapshot_gb_month}</div>
                <div><strong>API Call Cost:</strong> {config.cost_per_api_call}</div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ═══════════════════════════ RESOURCES ═══════════════════════════ */}
      {subTab === "resources" && !loading && (
        <div>
          {filterBar()}
          <div style={{ overflowX: "auto" }}>
            <div style={{ marginBottom: 8, fontSize: "0.85em", color: "var(--color-text-secondary, #666)" }}>{resources.length} records</div>
            <table className="pf9-table" style={{ width: "100%", fontSize: "0.82em" }}>
              <thead>
                <tr>
                  <SortHeader label="Collected" field="collected_at" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="VM Name" field="vm_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="VM IP" field="vm_ip" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <th>VM ID</th>
                  <SortHeader label="Tenant / Project" field="project_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Domain" field="domain" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Host" field="host" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Flavor" field="flavor" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="vCPUs" field="vcpus_allocated" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="RAM (MB)" field="ram_allocated_mb" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Disk (GB)" field="disk_allocated_gb" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="CPU %" field="cpu_usage_percent" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="RAM %" field="ram_usage_percent" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Disk %" field="disk_usage_percent" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Net RX" field="network_rx_bytes" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Net TX" field="network_tx_bytes" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <th style={{width:40}}></th>
                </tr>
              </thead>
              <tbody>
                {sortedResources.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtDate(r.collected_at)}</td>
                    <td title={r.vm_id}>{r.vm_name || "—"}</td>
                    <td style={{ fontFamily: "monospace", fontSize: "0.9em" }}>{r.vm_ip || "—"}</td>
                    <td style={{ fontSize: "0.8em", opacity: 0.6 }}>{r.vm_id?.slice(0, 8)}…</td>
                    <td>{r.project_name || "—"}</td>
                    <td>{r.domain || "—"}</td>
                    <td>{r.host || "—"}</td>
                    <td>{r.flavor || "—"}</td>
                    <td>{r.vcpus_allocated ?? "—"}</td>
                    <td>{fmtNum(r.ram_allocated_mb, 0)}</td>
                    <td>{fmtNum(r.disk_allocated_gb, 0)}</td>
                    <td>{fmtPct(r.cpu_usage_percent)}</td>
                    <td>{fmtPct(r.ram_usage_percent)}</td>
                    <td>{fmtPct(r.disk_usage_percent)}</td>
                    <td>{fmtBytes(r.network_rx_bytes)}</td>
                    <td>{fmtBytes(r.network_tx_bytes)}</td>
                    <td style={{textAlign:"center"}}>
                      <button
                        title={`Open inquiry ticket for ${r.project_name || r.vm_name}`}
                        style={{background:"none",border:"none",cursor:"pointer",fontSize:"1.1em",padding:"2px 4px",borderRadius:4}}
                        onClick={() => {
                          setInquiryFor({project_id: r.project_id||'', project_name: r.project_name||'', vm_name: r.vm_name||''});
                          setInquiryTitle(`Inquiry: ${r.project_name || r.vm_name}`);
                          setInquiryNote('');
                          setInquiryDeptId(0);
                          if (inquiryDepts.length === 0) {
                            apiFetch<{departments:{id:number;name:string}[]}>("/api/departments")
                              .then(d => setInquiryDepts(d.departments || []))
                              .catch(() => {});
                          }
                        }}
                      >📋</button>
                    </td>
                  </tr>
                ))}
                {resources.length === 0 && (
                  <tr><td colSpan={17} style={{ textAlign: "center", padding: 24, color: "var(--color-text-secondary, #999)" }}>No resource metering data yet. The metering worker collects data every 15 minutes.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ═══════════════════════════ SNAPSHOTS ═══════════════════════════ */}
      {subTab === "snapshots" && !loading && (
        <div>
          {filterBar()}
          <div style={{ overflowX: "auto" }}>
            <div style={{ marginBottom: 8, fontSize: "0.85em", color: "var(--color-text-secondary, #666)" }}>{snapshots.length} records</div>
            <table className="pf9-table" style={{ width: "100%", fontSize: "0.82em" }}>
              <thead>
                <tr>
                  <SortHeader label="Collected" field="collected_at" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Snapshot Name" field="snapshot_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <th>Snapshot ID</th>
                  <SortHeader label="Volume Name" field="volume_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Tenant" field="project_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Domain" field="domain" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Size (GB)" field="size_gb" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Status" field="status" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <th>Policy</th>
                  <SortHeader label="Compliant" field="is_compliant" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Created" field="created_at" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                </tr>
              </thead>
              <tbody>
                {sortedSnapshots.map((s) => (
                  <tr key={s.id}>
                    <td>{fmtDate(s.collected_at)}</td>
                    <td>{s.snapshot_name || "—"}</td>
                    <td style={{ fontSize: "0.8em", opacity: 0.6 }}>{s.snapshot_id?.slice(0, 8)}…</td>
                    <td>{s.volume_name || "—"}</td>
                    <td>{s.project_name || "—"}</td>
                    <td>{s.domain || "—"}</td>
                    <td>{fmtNum(s.size_gb, 0)}</td>
                    <td>{s.status || "—"}</td>
                    <td>{s.policy_name || "—"}</td>
                    <td>{s.is_compliant == null ? "—" : s.is_compliant ? "✅" : "❌"}</td>
                    <td>{fmtDate(s.created_at)}</td>
                  </tr>
                ))}
                {snapshots.length === 0 && (
                  <tr><td colSpan={11} style={{ textAlign: "center", padding: 24, color: "var(--color-text-secondary, #999)" }}>No snapshot metering data yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ═══════════════════════════ RESTORES ═══════════════════════════ */}
      {subTab === "restores" && !loading && (
        <div>
          {filterBar()}
          <div style={{ overflowX: "auto" }}>
            <div style={{ marginBottom: 8, fontSize: "0.85em", color: "var(--color-text-secondary, #666)" }}>{restores.length} records</div>
            <table className="pf9-table" style={{ width: "100%", fontSize: "0.82em" }}>
              <thead>
                <tr>
                  <SortHeader label="Collected" field="collected_at" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <th>Restore ID</th>
                  <SortHeader label="Snapshot" field="snapshot_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Target Server" field="target_server_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Tenant" field="project_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Domain" field="domain" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Status" field="status" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Duration" field="duration_seconds" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Initiated By" field="initiated_by" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Initiated At" field="initiated_at" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                </tr>
              </thead>
              <tbody>
                {sortedRestores.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtDate(r.collected_at)}</td>
                    <td style={{ fontSize: "0.8em", opacity: 0.6 }}>{r.restore_id?.slice(0, 8) ?? "—"}</td>
                    <td>{r.snapshot_name || "—"}</td>
                    <td>{r.target_server_name || "—"}</td>
                    <td>{r.project_name || "—"}</td>
                    <td>{r.domain || "—"}</td>
                    <td>
                      <span style={{ color: r.status === "completed" || r.status === "COMPLETED" ? "#4CAF50" : r.status === "failed" || r.status === "FAILED" ? "#F44336" : "#FF9800", fontWeight: 600 }}>
                        {r.status || "—"}
                      </span>
                    </td>
                    <td>{fmtDuration(r.duration_seconds)}</td>
                    <td>{r.initiated_by || "—"}</td>
                    <td>{fmtDate(r.initiated_at)}</td>
                  </tr>
                ))}
                {restores.length === 0 && (
                  <tr><td colSpan={10} style={{ textAlign: "center", padding: 24, color: "var(--color-text-secondary, #999)" }}>No restore metering data yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ═══════════════════════════ API USAGE ═══════════════════════════ */}
      {subTab === "api_usage" && !loading && (
        <div>
          {filterBar()}
          <div style={{ overflowX: "auto" }}>
            <div style={{ marginBottom: 8, fontSize: "0.85em", color: "var(--color-text-secondary, #666)" }}>{apiUsage.length} records</div>
            <table className="pf9-table" style={{ width: "100%", fontSize: "0.82em" }}>
              <thead>
                <tr>
                  <SortHeader label="Collected" field="collected_at" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Method" field="method" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Endpoint" field="endpoint" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Calls" field="total_calls" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Errors" field="error_count" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Avg (ms)" field="avg_latency_ms" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="P95 (ms)" field="p95_latency_ms" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="P99 (ms)" field="p99_latency_ms" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <th>Interval</th>
                </tr>
              </thead>
              <tbody>
                {sortedApiUsage.map((a) => (
                  <tr key={a.id}>
                    <td>{fmtDate(a.collected_at)}</td>
                    <td>
                      <span style={{ padding: "2px 6px", borderRadius: 3, fontWeight: 600, fontSize: "0.8em", background: a.method === "GET" ? "#1976D2" : a.method === "POST" ? "#388E3C" : a.method === "PUT" ? "#F57C00" : a.method === "DELETE" ? "#D32F2F" : "#616161", color: "#fff" }}>
                        {a.method}
                      </span>
                    </td>
                    <td style={{ fontFamily: "monospace", fontSize: "0.85em" }}>{a.endpoint}</td>
                    <td>{a.total_calls}</td>
                    <td style={{ color: a.error_count > 0 ? "#D32F2F" : undefined }}>{a.error_count}</td>
                    <td>{fmtNum(a.avg_latency_ms)}</td>
                    <td>{fmtNum(a.p95_latency_ms)}</td>
                    <td>{fmtNum(a.p99_latency_ms)}</td>
                    <td style={{ fontSize: "0.8em" }}>{fmtDate(a.interval_start)} – {fmtDate(a.interval_end)}</td>
                  </tr>
                ))}
                {apiUsage.length === 0 && (
                  <tr><td colSpan={9} style={{ textAlign: "center", padding: 24, color: "var(--color-text-secondary, #999)" }}>No API usage metering data yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ═══════════════════════════ EFFICIENCY ═══════════════════════════ */}
      {subTab === "efficiency" && !loading && (
        <div>
          {filterBar()}
          <div style={{ overflowX: "auto" }}>
            <div style={{ marginBottom: 8, fontSize: "0.85em", color: "var(--color-text-secondary, #666)" }}>{efficiency.length} records</div>
            <table className="pf9-table" style={{ width: "100%", fontSize: "0.82em" }}>
              <thead>
                <tr>
                  <SortHeader label="Collected" field="collected_at" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="VM Name" field="vm_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <th>VM ID</th>
                  <SortHeader label="Tenant" field="project_name" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Domain" field="domain" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="CPU Eff %" field="cpu_efficiency" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="RAM Eff %" field="ram_efficiency" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Stor Eff %" field="storage_efficiency" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Overall" field="overall_score" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <SortHeader label="Class" field="classification" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
                  <th>Recommendation</th>
                </tr>
              </thead>
              <tbody>
                {sortedEfficiency.map((e) => (
                  <tr key={e.id}>
                    <td>{fmtDate(e.collected_at)}</td>
                    <td title={e.vm_id}>{e.vm_name || "—"}</td>
                    <td style={{ fontSize: "0.8em", opacity: 0.6 }}>{e.vm_id?.slice(0, 8)}…</td>
                    <td>{e.project_name || "—"}</td>
                    <td>{e.domain || "—"}</td>
                    <td>{fmtPct(e.cpu_efficiency)}</td>
                    <td>{fmtPct(e.ram_efficiency)}</td>
                    <td>{fmtPct(e.storage_efficiency)}</td>
                    <td style={{ fontWeight: 700 }}>{fmtPct(e.overall_score)}</td>
                    <td>{classificationBadge(e.classification)}</td>
                    <td style={{ maxWidth: 280, fontSize: "0.85em" }}>{e.recommendation || "—"}</td>
                  </tr>
                ))}
                {efficiency.length === 0 && (
                  <tr><td colSpan={11} style={{ textAlign: "center", padding: 24, color: "var(--color-text-secondary, #999)" }}>No efficiency data yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ═══════════════════════════ PRICING ═══════════════════════════ */}
      {subTab === "pricing" && !loading && (
        <div>
          <p style={{ fontSize: "0.9em", color: "var(--color-text-secondary, #666)", margin: "0 0 16px" }}>
            Configure pricing across all resource categories for accurate chargeback cost estimation.
            Use <strong>Sync Flavors</strong> to auto-populate from your OpenStack flavors.
            Set per-hour and/or monthly rates — the system will use whichever is configured.
          </p>

          {/* Action buttons */}
          <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
            <button onClick={syncFlavors} style={{ ...btnPrimary, background: "#388E3C" }}>
              🔄 Sync Flavors from System
            </button>
            <button onClick={() => setEditingPricing({
              category: "storage_gb",
              item_name: "",
              unit: "per GB/month",
              cost_per_hour: 0,
              cost_per_month: 0,
              currency: config?.cost_currency || "USD",
              notes: "",
            })} style={btnPrimary}>
              ➕ Add Pricing Entry
            </button>

            {/* Category filter */}
            <label style={{ fontSize: "0.85em", color: "var(--color-text-primary, #212121)", display: "flex", alignItems: "center", gap: 4, marginLeft: "auto" }}>
              Category:
              <select value={pricingCategoryFilter} onChange={(e) => setPricingCategoryFilter(e.target.value)} style={selectStyle}>
                <option value="all">All Categories</option>
                <option value="flavor">Flavors (Compute)</option>
                <option value="storage_gb">Storage (per GB)</option>
                <option value="snapshot_gb">Snapshots (per GB)</option>
                <option value="snapshot_op">Snapshots (per op)</option>
                <option value="restore">Restores (per op)</option>
                <option value="volume">Volumes</option>
                <option value="network">Networks</option>
                <option value="public_ip">Public IP</option>
                <option value="custom">Custom (other)</option>
              </select>
            </label>
          </div>

          {/* Search bar */}
          <div style={{ display: "flex", gap: 10, marginBottom: 12, alignItems: "center" }}>
            <span style={{ fontSize: "0.85em" }}>🔍</span>
            <input
              type="text"
              placeholder="Search by name, category, unit, notes..."
              value={pricingSearchQuery}
              onChange={(e) => setPricingSearchQuery(e.target.value)}
              style={{ ...inputStyle, minWidth: 300 }}
            />
            {pricingSearchQuery && (
              <button onClick={() => setPricingSearchQuery("")} style={{ ...btnOutline, padding: "2px 8px", fontSize: "0.8em" }}>✕ Clear</button>
            )}
            <span style={{ marginLeft: "auto", fontSize: "0.8em", color: "var(--color-text-secondary, #999)" }}>
              {pricingItems
                .filter((p) => pricingCategoryFilter === "all" || p.category === pricingCategoryFilter)
                .filter((p) => {
                  if (!pricingSearchQuery) return true;
                  const q = pricingSearchQuery.toLowerCase();
                  return p.item_name.toLowerCase().includes(q) || p.category.toLowerCase().includes(q) || (p.unit || "").toLowerCase().includes(q) || (p.notes || "").toLowerCase().includes(q);
                }).length} of {pricingItems.length} entries
            </span>
          </div>

          {/* Editor modal */}
          {editingPricing && (
            <div style={{ margin: "16px 0", ...cardStyle, maxWidth: 700 }}>
              <h4 style={{ margin: "0 0 12px", color: "var(--color-text-primary, #212121)" }}>{editingPricing.id ? "Edit" : "New"} Pricing Entry</h4>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)" }}>
                  Category
                  <select value={editingPricing.category || "custom"} onChange={(e) => setEditingPricing({ ...editingPricing, category: e.target.value })} style={{ ...selectStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }}>
                    <option value="flavor">Flavor (Compute)</option>
                    <option value="storage_gb">Storage (per GB)</option>
                    <option value="snapshot_gb">Snapshot (per GB)</option>
                    <option value="snapshot_op">Snapshot (per operation)</option>
                    <option value="restore">Restore (per operation)</option>
                    <option value="volume">Volume</option>
                    <option value="network">Network</option>
                    <option value="public_ip">Public IP</option>
                    <option value="custom">Custom (other)</option>
                  </select>
                  {editingPricing.category === "custom" && (
                    <span style={{ fontSize: "0.75em", color: "var(--color-text-secondary, #999)", display: "block", marginTop: 2 }}>
                      For items not covered by built-in categories. Use a unique name to avoid overlap.
                    </span>
                  )}
                </label>
                <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)" }}>
                  Item Name
                  <input type="text" value={editingPricing.item_name || ""} onChange={(e) => setEditingPricing({ ...editingPricing, item_name: e.target.value })} style={{ ...inputStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }} placeholder="e.g. m1.large, 1GB Storage" />
                </label>
                <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)" }}>
                  Unit
                  <input type="text" value={editingPricing.unit || "per hour"} onChange={(e) => setEditingPricing({ ...editingPricing, unit: e.target.value })} style={{ ...inputStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }} />
                </label>
                <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)" }}>
                  Cost / Hour
                  <input type="number" min={0} step={0.001} value={editingPricing.cost_per_hour || 0} onChange={(e) => setEditingPricing({ ...editingPricing, cost_per_hour: Number(e.target.value) })} style={{ ...inputStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }} />
                </label>
                <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)" }}>
                  Cost / Month
                  <input type="number" min={0} step={0.01} value={editingPricing.cost_per_month || 0} onChange={(e) => setEditingPricing({ ...editingPricing, cost_per_month: Number(e.target.value) })} style={{ ...inputStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }} />
                </label>
                <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)" }}>
                  Currency
                  <select value={editingPricing.currency || "USD"} onChange={(e) => setEditingPricing({ ...editingPricing, currency: e.target.value })} style={{ ...selectStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }}>
                    {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>
                {editingPricing.category === "flavor" && (
                  <>
                    <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)" }}>
                      vCPUs
                      <input type="number" min={0} value={editingPricing.vcpus || 0} onChange={(e) => setEditingPricing({ ...editingPricing, vcpus: Number(e.target.value) })} style={{ ...inputStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }} />
                    </label>
                    <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)" }}>
                      RAM (GB)
                      <input type="number" min={0} step={0.5} value={editingPricing.ram_gb || 0} onChange={(e) => setEditingPricing({ ...editingPricing, ram_gb: Number(e.target.value) })} style={{ ...inputStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }} />
                    </label>
                    <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)" }}>
                      Disk (GB)
                      <input type="number" min={0} value={editingPricing.disk_gb || 0} onChange={(e) => setEditingPricing({ ...editingPricing, disk_gb: Number(e.target.value) })} style={{ ...inputStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }} />
                    </label>
                    {(editingPricing.disk_gb || 0) > 0 && (
                      <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)" }}>
                        Disk Price / GB / Month
                        <input type="number" min={0} step={0.01} value={editingPricing.disk_cost_per_gb || 0} onChange={(e) => setEditingPricing({ ...editingPricing, disk_cost_per_gb: Number(e.target.value) })} style={{ ...inputStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }} />
                        <span style={{ fontSize: "0.75em", color: "var(--color-text-secondary, #999)" }}>Ephemeral disk cost per GB per month</span>
                      </label>
                    )}
                  </>
                )}
                <label style={{ fontSize: "0.85em", color: "var(--color-text-primary)", gridColumn: "1 / -1" }}>
                  Notes (optional)
                  <input type="text" value={editingPricing.notes || ""} onChange={(e) => setEditingPricing({ ...editingPricing, notes: e.target.value })} style={{ ...inputStyle, width: "100%", marginLeft: 0, display: "block", marginTop: 4 }} />
                </label>
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <button onClick={savePricingItem} style={btnPrimary}>💾 Save</button>
                <button onClick={() => setEditingPricing(null)} style={btnOutline}>Cancel</button>
              </div>
            </div>
          )}

          {/* Pricing table */}
          <div style={{ overflowX: "auto", marginTop: 16 }}>
            <table className="pf9-table" style={{ width: "100%", fontSize: "0.85em" }}>
              <thead>
                <tr>
                  {[
                    { key: "category", label: "Category" },
                    { key: "item_name", label: "Item Name" },
                    { key: "unit", label: "Unit" },
                    { key: "specs", label: "Specs", sortable: false },
                    { key: "cost_per_hour", label: "Cost / Hour" },
                    { key: "cost_per_month", label: "Cost / Month" },
                    { key: "currency", label: "Currency" },
                    { key: "notes", label: "Notes" },
                    { key: "actions", label: "Actions", sortable: false },
                  ].map((col) => (
                    <th
                      key={col.key}
                      onClick={col.sortable !== false ? () => {
                        if (pricingSortField === col.key) {
                          setPricingSortDir(pricingSortDir === "asc" ? "desc" : "asc");
                        } else {
                          setPricingSortField(col.key);
                          setPricingSortDir("asc");
                        }
                      } : undefined}
                      style={{ cursor: col.sortable !== false ? "pointer" : "default", userSelect: "none", whiteSpace: "nowrap" }}
                    >
                      {col.label}
                      {col.sortable !== false && pricingSortField === col.key && (
                        <span style={{ marginLeft: 4 }}>{pricingSortDir === "asc" ? "▲" : "▼"}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pricingItems
                  .filter((p) => pricingCategoryFilter === "all" || p.category === pricingCategoryFilter)
                  .filter((p) => {
                    if (!pricingSearchQuery) return true;
                    const q = pricingSearchQuery.toLowerCase();
                    return p.item_name.toLowerCase().includes(q) || p.category.toLowerCase().includes(q) || (p.unit || "").toLowerCase().includes(q) || (p.notes || "").toLowerCase().includes(q);
                  })
                  .sort((a, b) => {
                    const field = pricingSortField as keyof PricingItem;
                    const av = a[field] ?? "";
                    const bv = b[field] ?? "";
                    const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
                    return pricingSortDir === "asc" ? cmp : -cmp;
                  })
                  .map((fp) => (
                  <tr key={fp.id}>
                    <td>
                      <span style={{
                        display: "inline-block",
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: "0.8em",
                        fontWeight: 600,
                        color: "#fff",
                        background:
                          fp.category === "flavor" ? "#1976D2" :
                          fp.category === "storage_gb" ? "#7B1FA2" :
                          fp.category === "snapshot_gb" ? "#00796B" :
                          fp.category === "snapshot_op" ? "#009688" :
                          fp.category === "restore" ? "#E64A19" :
                          fp.category === "volume" ? "#455A64" :
                          fp.category === "network" ? "#F57C00" :
                          fp.category === "public_ip" ? "#5C6BC0" :
                          "#616161",
                        textTransform: "capitalize",
                      }}>
                        {fp.category.replace("_gb", "").replace("_op", "").replace("_ip", " IP").replace("_", " ")}
                      </span>
                    </td>
                    <td style={{ fontWeight: 600 }}>{fp.item_name}</td>
                    <td style={{ fontSize: "0.85em", opacity: 0.7 }}>{fp.unit}</td>
                    <td style={{ fontSize: "0.82em" }}>
                      {fp.category === "flavor" && fp.vcpus != null ? (
                        <span>
                          {fp.vcpus} vCPU · {fp.ram_gb} GB RAM · {fp.disk_gb} GB Disk
                          {fp.disk_cost_per_gb ? <span style={{ marginLeft: 4, color: "#7B1FA2", fontWeight: 600 }}>(₪{fp.disk_cost_per_gb}/GB)</span> : null}
                        </span>
                      ) : "—"}
                    </td>
                    <td style={{ fontFamily: "monospace" }}>{(fp.cost_per_hour || 0).toFixed(4)}</td>
                    <td style={{ fontFamily: "monospace" }}>{(fp.cost_per_month || 0).toFixed(2)}</td>
                    <td>{fp.currency}</td>
                    <td style={{ fontSize: "0.85em", opacity: 0.7 }}>{fp.notes || "—"}</td>
                    <td>
                      <button onClick={() => setEditingPricing({
                        id: fp.id,
                        category: fp.category,
                        item_name: fp.item_name,
                        unit: fp.unit,
                        cost_per_hour: fp.cost_per_hour || 0,
                        cost_per_month: fp.cost_per_month || 0,
                        currency: fp.currency,
                        notes: fp.notes || "",
                        vcpus: fp.vcpus || undefined,
                        ram_gb: fp.ram_gb || undefined,
                        disk_gb: fp.disk_gb || undefined,
                        disk_cost_per_gb: fp.disk_cost_per_gb || undefined,
                      })} style={{ ...btnOutline, padding: "2px 10px", fontSize: "0.8em", marginRight: 4 }}>✏️</button>
                      <button onClick={() => deletePricingItem(fp.id)} style={{ ...btnOutline, padding: "2px 10px", fontSize: "0.8em", color: "#D32F2F", borderColor: "#D32F2F" }}>🗑</button>
                    </td>
                  </tr>
                ))}
                {pricingItems
                  .filter((p) => pricingCategoryFilter === "all" || p.category === pricingCategoryFilter)
                  .filter((p) => {
                    if (!pricingSearchQuery) return true;
                    const q = pricingSearchQuery.toLowerCase();
                    return p.item_name.toLowerCase().includes(q) || p.category.toLowerCase().includes(q) || (p.unit || "").toLowerCase().includes(q) || (p.notes || "").toLowerCase().includes(q);
                  }).length === 0 && (
                  <tr><td colSpan={9} style={{ textAlign: "center", padding: 24, color: "var(--color-text-secondary, #999)" }}>
                    {pricingSearchQuery ? "No entries match your search." : "No pricing configured yet. Click Sync Flavors from System to auto-populate flavor pricing, or add entries manually."}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Quick-add cards for common categories */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12, marginTop: 20 }}>
            {[
              { cat: "storage_gb", label: "Storage (per GB)", unit: "per GB/month", icon: "💾", desc: "Price per GB of block storage" },
              { cat: "snapshot_gb", label: "Snapshot Storage (per GB)", unit: "per GB/month", icon: "📸", desc: "Price per GB of snapshot storage" },
              { cat: "snapshot_op", label: "Snapshot Operation", unit: "per operation", icon: "📷", desc: "Price per snapshot creation" },
              { cat: "restore", label: "Restore Operation", unit: "per operation", icon: "🔄", desc: "Price per restore operation" },
              { cat: "volume", label: "Volume", unit: "per volume/month", icon: "📦", desc: "Base price per volume" },
              { cat: "network", label: "Network", unit: "per network/month", icon: "🌐", desc: "Base price per network" },
              { cat: "public_ip", label: "Public IP", unit: "per IP/month", icon: "🌍", desc: "Price per public/floating IP" },
            ].filter((c) => !pricingItems.some((p) => p.category === c.cat)).map((c) => (
              <div key={c.cat} style={{ ...cardStyle, cursor: "pointer", transition: "border-color 0.2s" }}
                onClick={() => setEditingPricing({
                  category: c.cat,
                  item_name: c.label,
                  unit: c.unit,
                  cost_per_hour: 0,
                  cost_per_month: 0,
                  currency: config?.cost_currency || "USD",
                  notes: "",
                })}>
                <div style={{ fontSize: "1.3em", marginBottom: 4 }}>{c.icon}</div>
                <div style={{ fontWeight: 600, fontSize: "0.9em", color: "var(--color-text-primary, #212121)" }}>{c.label}</div>
                <div style={{ fontSize: "0.8em", color: "var(--color-text-secondary, #666)" }}>{c.desc}</div>
                <div style={{ fontSize: "0.75em", color: "var(--color-primary, #1976D2)", marginTop: 6 }}>+ Click to add pricing</div>
              </div>
            ))}
          </div>

          {/* Pricing notes */}
          <div style={{ marginTop: 16, ...cardStyle, fontSize: "0.83em", color: "var(--color-text-secondary, #666)" }}>
            <strong>💡 How pricing works:</strong> When generating chargeback reports, the system:
            <ul style={{ margin: "6px 0 0", paddingLeft: 20 }}>
              <li><strong>Compute (Flavors):</strong> Matches each VM's flavor against the pricing table. Unmatched VMs use fallback vCPU/RAM rates from Metering Config.</li>
              <li><strong>Ephemeral Disk:</strong> If a flavor has a disk price per GB, the ephemeral disk cost is added to the compute cost.</li>
              <li><strong>Storage:</strong> Calculates cost based on total disk GB × storage rate per GB.</li>
              <li><strong>Snapshot Storage:</strong> Costs based on total snapshot GB × snapshot rate per GB.</li>
              <li><strong>Snapshot Operations:</strong> Per-operation charge for each snapshot creation.</li>
              <li><strong>Restores:</strong> Per-operation charge for each restore job.</li>
              <li><strong>Volumes:</strong> Actual volume count from inventory × per-volume monthly rate.</li>
              <li><strong>Networks:</strong> Actual network count from inventory × per-network monthly rate. Subnets and routers also counted.</li>
              <li><strong>Public IPs:</strong> Actual floating IP count from inventory × per-IP monthly rate.</li>
              <li><strong>Currency:</strong> Taken from pricing configuration. Can be overridden in the Export tab.</li>
              <li><strong>Monthly ↔ Hourly:</strong> If only monthly rate is set, system divides by 730 hours for hourly cost (and vice versa).</li>
            </ul>
          </div>
        </div>
      )}

      {/* ═══════════════════════════ CHARGEBACK SUMMARY ═══════════════════════════ */}
      {subTab === "chargeback" && (
        <div>
          <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 20, flexWrap: "wrap" }}>
            <label style={{ fontSize: "0.85em", display: "flex", alignItems: "center", gap: 4 }}>
              Currency:
              <select value={chargebackCurrency} onChange={e => { setChargebackCurrency(e.target.value); loadChargebackSummary(e.target.value, chargebackHours); }} style={selectStyle}>
                {CURRENCIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label style={{ fontSize: "0.85em", display: "flex", alignItems: "center", gap: 4 }}>
              Period:
              <select value={chargebackHours} onChange={e => { setChargebackHours(Number(e.target.value)); loadChargebackSummary(chargebackCurrency, Number(e.target.value)); }} style={selectStyle}>
                <option value={168}>Last 7 days</option>
                <option value={720}>Last 30 days</option>
                <option value={2160}>Last 90 days</option>
                <option value={8760}>Last 12 months</option>
              </select>
            </label>
            <button onClick={() => loadChargebackSummary(chargebackCurrency, chargebackHours)} style={{ padding: "4px 12px", borderRadius: 4, border: "1px solid #ccc", cursor: "pointer", fontSize: "0.85em" }}>
              🔄 Refresh
            </button>
          </div>

          {loading && <div style={{ padding: 20 }}>Loading chargeback summary…</div>}
          {!loading && chargebackData && (
            <>
              <div style={{ marginBottom: 12, padding: "8px 14px", background: "var(--color-surface-elevated, #f9fafb)", borderRadius: 8, display: "inline-block" }}>
                <strong>Total estimated cost:</strong>&nbsp;
                <span style={{ fontSize: "1.2em", fontWeight: 700, color: "#1d4ed8" }}>
                  {chargebackData.total_cost?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {chargebackData.currency}
                </span>
                &nbsp;<span style={{ color: "#888", fontSize: "0.8em" }}>({chargebackHours / 24} days)</span>
              </div>
              <table className="pf9-table" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>Project / Tenant</th>
                    <th>VMs</th>
                    <th>Total vCPUs</th>
                    <th>Total RAM (GB)</th>
                    <th>Estimated Cost ({chargebackData.currency})</th>
                  </tr>
                </thead>
                <tbody>
                  {chargebackData.tenants?.length === 0 && (
                    <tr><td colSpan={6} style={{ textAlign: "center", padding: 20 }}>No data available for this period.</td></tr>
                  )}
                  {chargebackData.tenants?.map((t: any, i: number) => (
                    <tr key={i}>
                      <td>{t.domain}</td>
                      <td>{t.project_name}</td>
                      <td>{t.vm_count}</td>
                      <td>{t.total_vcpus}</td>
                      <td>{t.total_ram_gb.toFixed(1)}</td>
                      <td style={{ fontWeight: 600 }}>{t.estimated_cost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {!loading && !chargebackData && (
            <div style={{ padding: 20, color: "#888" }}>No chargeback data loaded. Click refresh.</div>
          )}
        </div>
      )}

      {/* ═══════════════════════════ TENANT GROWTH ═══════════════════════════ */}
      {subTab === "growth" && (
        <div>
          <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 20, flexWrap: "wrap" }}>
            <label style={{ fontSize: "0.85em", display: "flex", alignItems: "center", gap: 4 }}>
              Look back:
              <select value={growthMonths} onChange={e => { setGrowthMonths(Number(e.target.value)); loadGrowth(Number(e.target.value)); }} style={selectStyle}>
                <option value={3}>3 months</option>
                <option value={6}>6 months</option>
                <option value={12}>12 months</option>
                <option value={24}>24 months</option>
              </select>
            </label>
            <button onClick={() => loadGrowth(growthMonths)} style={{ padding: "4px 12px", borderRadius: 4, border: "1px solid #ccc", cursor: "pointer", fontSize: "0.85em" }}>
              🔄 Refresh
            </button>
          </div>

          {loading && <div style={{ padding: 20 }}>Loading tenant growth data…</div>}
          {!loading && growthData && growthData.months?.length > 0 && (
            <table className="pf9-table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>Tenant (Domain/Project)</th>
                  {growthData.months.map((m: string) => <th key={m}>{m}</th>)}
                </tr>
              </thead>
              <tbody>
                {growthData.series?.length === 0 && (
                  <tr><td colSpan={growthData.months.length + 1} style={{ textAlign: "center", padding: 20 }}>No data available.</td></tr>
                )}
                {growthData.series?.map((s: any, i: number) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 500 }}>{s.tenant}</td>
                    {s.data.map((count: number, j: number) => (
                      <td key={j} style={{ textAlign: "center", color: count === 0 ? "#aaa" : undefined }}>{count}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!loading && (!growthData || growthData.months?.length === 0) && (
            <div style={{ padding: 20, color: "#888" }}>No growth data loaded. Click refresh.</div>
          )}
        </div>
      )}

      {/* ═══════════════════════════ EXPORT ═══════════════════════════ */}
      {subTab === "export" && (
        <div>
          {filterBar(true, false)}

          {/* Currency selector for chargeback */}
          <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 20, flexWrap: "wrap" }}>
            <label style={{ fontSize: "0.85em", color: "var(--color-text-primary, #212121)", display: "flex", alignItems: "center", gap: 4 }}>
              Chargeback Currency:
              <select value={exportCurrency} onChange={(e) => setExportCurrency(e.target.value)} style={selectStyle}>
                {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
            <ExportCard title="Resource Metering" description="Per-VM CPU, RAM, disk, and network usage data" onExport={() => triggerExport("resources")} />
            <ExportCard title="Snapshot Metering" description="Snapshot storage, compliance, and policy data" onExport={() => triggerExport("snapshots")} />
            <ExportCard title="Restore Metering" description="Restore operations, duration, and success rates" onExport={() => triggerExport("restores")} />
            <ExportCard title="API Usage" description="API call volume, latency, and error rates" onExport={() => triggerExport("api-usage")} />
            <ExportCard title="Efficiency Scores" description="Per-VM efficiency classification and recommendations" onExport={() => triggerExport("efficiency")} />
            <ExportCard
              title="Chargeback CSV (per tenant)"
              description={`Per-tenant cost aggregation (${exportCurrency || "auto"}) — VMs, volumes, snapshots, networks, floating IPs`}
              onExport={() => triggerExport("chargeback")}
              highlight
            />
            <ExportCard
              title="Chargeback Excel (row per VM)"
              description="One row per VM with a Summary sheet — ideal for detailed cost review"
              onExport={() => triggerExport("chargeback-excel")}
              highlight
            />
            <ExportCard
              title="Chargeback PDF"
              description="Printable tenant summary report with styled cost table"
              onExport={() => triggerExport("chargeback-pdf")}
            />
          </div>

          {/* Email export */}
          <div style={{ marginTop: 24, ...cardStyle }}>
            <h4 style={{ margin: "0 0 12px", fontSize: "0.95em", fontWeight: 600 }}>📧 Send Report by Email</h4>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <input
                type="email"
                placeholder="Recipient email"
                value={emailTo}
                onChange={e => setEmailTo(e.target.value)}
                style={{ padding: "6px 10px", border: "1px solid var(--color-border,#ddd)", borderRadius: 6, minWidth: 220, fontSize: "0.85em" }}
              />
              <select value={emailFormat} onChange={e => setEmailFormat(e.target.value)} style={selectStyle}>
                <option value="excel">Excel (row per VM)</option>
                <option value="pdf">PDF Summary</option>
                <option value="csv">CSV</option>
              </select>
              <button
                disabled={emailSending || !emailTo}
                onClick={async () => {
                  setEmailSending(true);
                  setEmailMsg(null);
                  const token = localStorage.getItem("auth_token");
                  try {
                    const res = await fetch(`${API_BASE}/api/metering/export/send-email`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                      body: JSON.stringify({
                        to_email: emailTo,
                        format: emailFormat,
                        project: projectFilter || null,
                        domain: domainFilter || null,
                        hours: hoursFilter,
                        currency: exportCurrency || null,
                      }),
                    });
                    const data = await res.json();
                    if (res.ok) {
                      setEmailMsg(`✅ ${data.message}`);
                    } else {
                      setEmailMsg(`⚠️ ${data.detail || "Failed to send"}`);
                    }
                  } catch (e: any) {
                    setEmailMsg(`⚠️ ${e.message}`);
                  } finally {
                    setEmailSending(false);
                  }
                }}
                style={{ padding: "6px 16px", background: "#1D4ED8", color: "#fff", borderRadius: 6, border: "none", cursor: "pointer", fontSize: "0.85em", opacity: emailSending ? 0.7 : 1 }}
              >
                {emailSending ? "Sending…" : "📨 Send"}
              </button>
            </div>
            {emailMsg && (
              <div style={{ marginTop: 8, fontSize: "0.85em", color: emailMsg.startsWith("✅") ? "#166534" : "#991B1B", padding: "6px 10px", background: emailMsg.startsWith("✅") ? "#DCFCE7" : "#FEE2E2", borderRadius: 6 }}>
                {emailMsg}
              </div>
            )}
          </div>

          <div style={{ marginTop: 20, ...cardStyle, fontSize: "0.83em", color: "var(--color-text-secondary, #666)" }}>
            <strong>ℹ️ Export Notes:</strong> All exports honour the Tenant / Project and Domain filters above.
            CSV columns use user-friendly headers. Raw IDs are included alongside display names for cross-referencing.
            The Chargeback Report uses per-flavor pricing when configured; otherwise fallback rates from Metering Configuration apply.
            Volumes, networks, subnets, routers, and floating IPs are counted from actual inventory — not approximated.
            Currency is taken from the pricing configuration; override with the dropdown above.
          </div>
        </div>
      )}

      {/* Open Inquiry modal */}
      {inquiryFor && (
        <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,0.45)",zIndex:1000,display:"flex",alignItems:"center",justifyContent:"center"}}
          onClick={() => setInquiryFor(null)}>
          <div style={{background:"var(--color-surface,#fff)",borderRadius:10,padding:24,minWidth:380,maxWidth:480,boxShadow:"0 8px 32px rgba(0,0,0,0.24)"}}
            onClick={e => e.stopPropagation()}>
            <h3 style={{margin:"0 0 16px"}}>📋 Open Inquiry Ticket</h3>
            <p style={{fontSize:"0.88em",opacity:0.7,margin:"0 0 14px"}}>
              Project: <strong>{inquiryFor.project_name}</strong> &nbsp;·&nbsp; VM: <strong>{inquiryFor.vm_name || "—"}</strong>
            </p>
            <label style={{display:"block",marginBottom:10}}>
              <span style={{fontSize:"0.85em",fontWeight:500}}>Title *</span>
              <input style={{display:"block",width:"100%",marginTop:4,padding:"6px 8px",border:"1px solid var(--color-border,#ddd)",borderRadius:6}}
                value={inquiryTitle} onChange={e => setInquiryTitle(e.target.value)} />
            </label>
            <label style={{display:"block",marginBottom:10}}>
              <span style={{fontSize:"0.85em",fontWeight:500}}>Assign to Team *</span>
              <select style={{display:"block",width:"100%",marginTop:4,padding:"6px 8px",border:"1px solid var(--color-border,#ddd)",borderRadius:6}}
                value={inquiryDeptId} onChange={e => setInquiryDeptId(Number(e.target.value))}>
                <option value={0}>Select team…</option>
                {inquiryDepts.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </label>
            <label style={{display:"block",marginBottom:16}}>
              <span style={{fontSize:"0.85em",fontWeight:500}}>Notes</span>
              <textarea rows={3} style={{display:"block",width:"100%",marginTop:4,padding:"6px 8px",border:"1px solid var(--color-border,#ddd)",borderRadius:6,resize:"vertical"}}
                value={inquiryNote} onChange={e => setInquiryNote(e.target.value)} />
            </label>
            <div style={{display:"flex",gap:8,justifyContent:"flex-end"}}>
              <button style={{padding:"6px 16px",borderRadius:6,border:"1px solid var(--color-border,#ddd)",background:"none",cursor:"pointer"}}
                onClick={() => setInquiryFor(null)}>Cancel</button>
              <button
                disabled={inquiryCreating || !inquiryTitle.trim() || !inquiryDeptId}
                style={{padding:"6px 16px",borderRadius:6,border:"none",background:"#2563eb",color:"#fff",cursor:"pointer",fontWeight:600}}
                onClick={async () => {
                  setInquiryCreating(true);
                  try {
                    await apiFetch("/api/tickets/_auto", {
                      method: "POST",
                      body: JSON.stringify({
                        title: inquiryTitle,
                        description: inquiryNote || `Inquiry from Metering tab for project ${inquiryFor.project_name} / VM ${inquiryFor.vm_name}`,
                        ticket_type: "service_request",
                        priority: "normal",
                        to_dept_id: inquiryDeptId,
                        project_id: inquiryFor.project_id,
                        project_name: inquiryFor.project_name,
                        auto_source: "metering_inquiry",
                        auto_source_id: `${inquiryFor.project_id}_${Date.now()}`,
                      }),
                    });
                    setInquiryFor(null);
                  } catch (e: any) {
                    alert(`Failed to create ticket: ${e.message}`);
                  } finally {
                    setInquiryCreating(false);
                  }
                }}
              >{inquiryCreating ? "Creating…" : "Create Ticket"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function SummaryCard({ title, value, color }: { title: string; value: string | number; color?: string }) {
  return (
    <div style={{ padding: "14px 18px", background: "var(--color-surface, #fff)", borderRadius: 8, border: "1px solid var(--color-border, #e0e0e0)", boxShadow: "var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.08))" }}>
      <div style={{ fontSize: "0.78em", color: "var(--color-text-secondary, #666)", marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: "1.4em", fontWeight: 700, color: color || "var(--color-text-primary, #212121)" }}>
        {value}
      </div>
    </div>
  );
}

function ExportCard({
  title,
  description,
  onExport,
  highlight,
}: {
  title: string;
  description: string;
  onExport: () => void;
  highlight?: boolean;
}) {
  return (
    <div
      style={{
        padding: 20,
        background: highlight ? "var(--color-surface-elevated, #F5F7FA)" : "var(--color-surface, #fff)",
        borderRadius: 8,
        border: `2px solid ${highlight ? "var(--color-primary, #1976D2)" : "var(--color-border, #e0e0e0)"}`,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        boxShadow: "var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.08))",
      }}
    >
      <div style={{ fontWeight: 600, fontSize: "1.05em", color: "var(--color-text-primary, #212121)" }}>{title}</div>
      <div style={{ fontSize: "0.83em", color: "var(--color-text-secondary, #666)", flex: 1 }}>{description}</div>
      <button
        onClick={onExport}
        style={{
          marginTop: 4,
          padding: "8px 16px",
          borderRadius: 6,
          border: "none",
          background: highlight ? "var(--color-primary, #1976D2)" : "var(--color-primary, #1976D2)",
          color: "#fff",
          cursor: "pointer",
          fontWeight: 600,
          fontSize: "0.85em",
        }}
      >
        📥 Download CSV
      </button>
    </div>
  );
}
