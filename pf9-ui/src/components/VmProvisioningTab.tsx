/**
 * VM Provisioning Tab — Runbook 2 (v1.39.0)
 *
 * Multi-step form:
 *   Step 1 — Domain + Project + Quota overview
 *   Step 2 — VM rows (image, flavor, volume GB, network, SGs, IP, hostname)
 *   Step 3 — OS credentials + cloud-init preview
 *   Step 4 — Review + batch name + submit
 *
 * Batch list view (existing batches) with dry-run / approve / execute actions.
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch, authHeaders } from '../lib/api';
import { API_BASE } from '../config';
import "../styles/VmProvisioningTab.css";

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

interface PfImage {
  id: string;
  name: string;
  status: string;
  size?: number;          // Glance file size (bytes) — NOT the disk requirement
  min_disk?: number;     // Minimum disk size in GB required to boot this image
  virtual_size?: number; // Virtual disk size in bytes
  disk_format?: string;
  os_type?: string;
  os_distro?: string;
  _detected_os?: string;
}

interface PfFlavor {
  id: string;
  name: string;
  vcpus: number;
  ram: number;
  disk: number;
  "OS-FLV-EXT-DATA:ephemeral"?: number;
}

interface PfNetwork {
  id: string;
  name: string;
}

interface PfSecurityGroup {
  id: string;
  name: string;
}

interface QuotaEntry { limit: number; in_use: number; }
interface QuotaUsage {
  compute?: { [key: string]: number | QuotaEntry };
  storage?: { [key: string]: number | QuotaEntry };
}

interface Resources {
  images: PfImage[];
  flavors: PfFlavor[];
  networks: PfNetwork[];
  security_groups: PfSecurityGroup[];
  project_id: string;
}

interface VmRow {
  id: string;                 // local key (not DB id)
  expanded: boolean;
  vmNameSuffix: string;
  count: number;
  selectedImageId: string;
  selectedFlavorId: string;
  volumeGb: number;
  selectedNetworkId: string;
  selectedSGs: string[];      // SG names
  useStaticIp: boolean;
  fixedIp: string;
  availableIps: string[];
  hostname: string;
  osUsername: string;
  osPassword: string;
  extraCloudInit: string;
  showExtra: boolean;
  osType: string;             // auto from image
  deleteOnTermination: boolean;
  sgDropdownOpen: boolean;
  image?: { _detected_os?: string; name?: string } | null;
}

interface Batch {
  id: number;
  name: string;
  status: string;
  approval_status: string;
  require_approval: boolean;
  created_by: string;
  domain_name: string;
  project_name: string;
  created_at: string;
  vms?: BatchVm[];
  dry_run_results?: DryRunResults;
}

interface BatchVm {
  id: number;
  vm_name_suffix: string;
  count: number;
  status: string;
  error_msg?: string;
  pcd_server_ids?: string[];
  assigned_ips?: string[];
  console_log?: string;
}

interface DryRunResults {
  per_vm?: {
    vm_id: number;
    vm_name_suffix: string;
    count: number;
    checks: { check: string; status: string; detail: string }[];
  }[];
  quota?: { resource: string; needed: number; free: number; status: string }[];
}

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function tenantSlug(domain: string) {
  return domain.toLowerCase().replace(/[^a-z0-9-]/g, "-").replace(/-{2,}/g, "-").replace(/^-|-$/g, "") || "tenant";
}

function vmNovaName(domain: string, suffix: string, index?: number, count?: number) {
  const slug = tenantSlug(domain);
  const cleanSuffix = suffix.toLowerCase().replace(/[^a-z0-9-]/g, "-").replace(/^-|-$/g, "");
  let base = `${slug}_vm_${cleanSuffix}`;
  if (count && count > 1 && index !== undefined) {
    const pad = count > 99 ? 3 : 2;
    base += `-${String(index).padStart(pad, "0")}`;
  }
  return base;
}

function fmtMb(mb: number) {
  if (mb >= 1024) return `${(mb / 1024).toFixed(0)} GB`;
  return `${mb} MB`;
}

function fmtBytes(b?: number) {
  if (!b) return "—";
  const g = b / 1073741824;
  return g > 0.1 ? `${g.toFixed(1)} GB` : `${(b / 1048576).toFixed(0)} MB`;
}

function osIcon(img: PfImage) {
  const t = ((img.os_type || "") + (img.os_distro || "") + img.name).toLowerCase();
  if (t.includes("windows") || t.includes("win")) return "🪟";
  if (t.includes("ubuntu")) return "🟠";
  if (t.includes("centos") || t.includes("rhel") || t.includes("rocky")) return "🎩";
  if (t.includes("debian")) return "🌀";
  return "🐧";
}

function quotaFree(entry?: number | QuotaEntry): { used: number; limit: number } {
  if (!entry) return { used: 0, limit: 9999 };
  if (typeof entry === "number") return { used: 0, limit: entry };
  return { used: entry.in_use ?? 0, limit: entry.limit ?? 9999 };
}

// ── Auth helpers ─────────────────────────────────────────────

function newVmRow(): VmRow {
  return {
    id: Math.random().toString(36).slice(2),
    expanded: true,
    vmNameSuffix: "",
    count: 1,
    selectedImageId: "",
    selectedFlavorId: "",
    volumeGb: 20,
    selectedNetworkId: "",
    selectedSGs: [],
    useStaticIp: false,
    fixedIp: "",
    availableIps: [],
    hostname: "",
    osUsername: "ubuntu",
    osPassword: "",
    extraCloudInit: "",
    showExtra: false,
    osType: "linux",
    deleteOnTermination: true,
    sgDropdownOpen: false,
  };
}

const STEPS = [
  "Domain & Project",
  "VM Configuration",
  "OS Credentials",
  "Review & Submit",
];

// ──────────────────────────────────────────────────────────────────────────────
// Props
// ──────────────────────────────────────────────────────────────────────────────
interface Props {
  onBack: () => void;
}

// ──────────────────────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────────────────────
const VmProvisioningTab: React.FC<Props> = ({ onBack }) => {
  // ── view mode ─────────────────────────────────────────────────
  const [mode, setMode] = useState<"batches" | "create">("batches");

  // ── batch list ────────────────────────────────────────────────
  const [batches, setBatches] = useState<Batch[]>([]);
  const [batchesLoading, setBatchesLoading] = useState(false);
  const [_selectedBatch, setSelectedBatch] = useState<Batch | null>(null);
  const [_dryRunRunning, setDryRunRunning] = useState(false);
  const [_execRunning, setExecRunning] = useState(false);
  const [batchMsg, setBatchMsg] = useState<{ type: string; text: string } | null>(null);
  // per-batch action busy state & inline expand
  const [actionBusy, setActionBusy] = useState<Record<number, string>>({});
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [batchLogs, setBatchLogs] = useState<Record<number, any[]>>({});

  async function loadBatchLogs(batchId: number) {
    try {
      // apiFetch already returns parsed JSON — do NOT call .json() again
      const data = await apiFetch<any[]>(`/api/vm-provisioning/batches/${batchId}/logs`);
      setBatchLogs((p) => ({ ...p, [batchId]: Array.isArray(data) ? data : [] }));
    } catch {
      // silently ignore
    }
  }

  // ── new batch form ────────────────────────────────────────────
  const [step, setStep] = useState(1);
  const [domain, setDomain] = useState("");
  const [project, setProject] = useState("");
  const [requireApproval, setRequireApproval] = useState(true);
  const [batchName, setBatchName] = useState("");
  const [resources, setResources] = useState<Resources | null>(null);
  const [resLoading, setResLoading] = useState(false);
  const [resError, setResError] = useState("");
  const [quotaUsage, setQuotaUsage] = useState<QuotaUsage | null>(null);
  const [vmRows, setVmRows] = useState<VmRow[]>([newVmRow()]);
  const [formMsg, setFormMsg] = useState<{ type: string; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // ── Excel import ───────────────────────────────────────────────
  const [excelImportOpen, setExcelImportOpen] = useState(false);
  const [excelVms, setExcelVms] = useState<any[] | null>(null);
  const [excelErrors, setExcelErrors] = useState<string[]>([]);
  const [excelUploading, setExcelUploading] = useState(false);
  const [excelBatchName, setExcelBatchName] = useState("");
  const [excelSubmitting, setExcelSubmitting] = useState(false);
  const [excelMsg, setExcelMsg] = useState<{ type: string; text: string } | null>(null);
  const excelInputRef = useRef<HTMLInputElement>(null);

  // ── domains / project picker (step 1) ────────────────────────
  interface DomainEntry { id: string; name: string; projects: { id: string; name: string }[] }
  const [domainsData, setDomainsData] = useState<DomainEntry[]>([]);
  const [domainsLoading, setDomainsLoading] = useState(false);
  const [domainSearch, setDomainSearch] = useState("");
  const [projectSearch, setProjectSearch] = useState("");
  const [domainDropOpen, setDomainDropOpen] = useState(false);
  const [projectDropOpen, setProjectDropOpen] = useState(false);
  const domainDropRef = useRef<HTMLDivElement>(null);
  const projectDropRef = useRef<HTMLDivElement>(null)

  // ──────────────────────────────────────────────────────────────
  // Fetch batches
  // ──────────────────────────────────────────────────────────────
  const fetchBatches = useCallback(async () => {
    setBatchesLoading(true);
    try {
      const data = await apiFetch<Batch[]>("/api/vm-provisioning/batches");
      setBatches(data);
    } catch (e: any) {
      console.error(e);
    } finally {
      setBatchesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBatches();
  }, [fetchBatches]);

  // Load domains+projects list for Step 1 picker
  useEffect(() => {
    setDomainsLoading(true);
    apiFetch<DomainEntry[]>("/api/vm-provisioning/domains")
      .then((data) => setDomainsData(data))
      .catch((e) => console.error("Failed to load domains", e))
      .finally(() => setDomainsLoading(false));
  }, []);

  // Close dropdowns when clicking outside
  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (domainDropRef.current && !domainDropRef.current.contains(e.target as Node)) setDomainDropOpen(false);
      if (projectDropRef.current && !projectDropRef.current.contains(e.target as Node)) setProjectDropOpen(false);
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);


  // Refs so the interval callback always reads the latest values without stale closures
  const batchesRef = useRef(batches);
  const expandedIdsRef = useRef(expandedIds);
  useEffect(() => { batchesRef.current = batches; }, [batches]);
  useEffect(() => { expandedIdsRef.current = expandedIds; }, [expandedIds]);

  useEffect(() => {
    const id = setInterval(() => {
      const executing = batchesRef.current.filter((b) => b.status === "executing");
      if (executing.length === 0) return;
      // Refresh the full batch list (metadata + status)
      fetchBatches();
      // For any expanded executing batch, also refresh VM details + logs
      executing
        .filter((b) => expandedIdsRef.current.has(b.id))
        .forEach((b) => { refreshBatch(b.id); loadBatchLogs(b.id); });
    }, 5000);
    return () => clearInterval(id);
  // fetchBatches is stable (useCallback with [] deps); refreshBatch/loadBatchLogs are plain functions
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ──────────────────────────────────────────────────────────────
  // Fetch resources (step 1 → 2 transition)
  // ──────────────────────────────────────────────────────────────
  const fetchResources = useCallback(async () => {
    if (!domain.trim() || !project.trim()) return;
    setResLoading(true);
    setResError("");
    try {
      const [resData, qData] = await Promise.all([
        apiFetch<Resources>(`/api/vm-provisioning/resources?domain_name=${encodeURIComponent(domain)}&project_name=${encodeURIComponent(project)}`),
        apiFetch<QuotaUsage>(`/api/vm-provisioning/quota?domain_name=${encodeURIComponent(domain)}&project_name=${encodeURIComponent(project)}`),
      ]);
      setResources(resData);
      setQuotaUsage(qData);
    } catch (e: any) {
      setResError(e.message || "Failed to load resources");
    } finally {
      setResLoading(false);
    }
  }, [domain, project]);

  // ──────────────────────────────────────────────────────────────
  // Fetch available IPs for a network
  // ──────────────────────────────────────────────────────────────
  const fetchAvailableIps = useCallback(async (networkId: string, rowIdx: number) => {
    if (!networkId) return;
    try {
      const data = await apiFetch<{ available_ips: string[] }>(
        `/api/vm-provisioning/available-ips?domain_name=${encodeURIComponent(domain)}&project_name=${encodeURIComponent(project)}&network_id=${encodeURIComponent(networkId)}`,
      );
      setVmRows((prev) => prev.map((row, i) =>
        i === rowIdx ? { ...row, availableIps: data.available_ips || [] } : row,
      ));
    } catch (_) { /* network not ready */ }
  }, [domain, project]);

  // ──────────────────────────────────────────────────────────────
  // Quota tally (live as VM rows change)
  // ──────────────────────────────────────────────────────────────
  function computeNeeds() {
    if (!resources) return { vcpu: 0, ram: 0, inst: 0, vol: 0, gb: 0 };
    let vcpu = 0, ram = 0, inst = 0, vol = 0, gb = 0;
    for (const row of vmRows) {
      const fl = resources.flavors.find((f) => f.id === row.selectedFlavorId);
      const cnt = row.count || 1;
      if (fl) { vcpu += fl.vcpus * cnt; ram += fl.ram * cnt; }
      inst += cnt;
      vol += cnt;
      gb += (row.volumeGb || 20) * cnt;
    }
    return { vcpu, ram, inst, vol, gb };
  }

  // ──────────────────────────────────────────────────────────────
  // Per-VM cloud-init / PowerShell preview builder
  // ──────────────────────────────────────────────────────────────
  function buildVmInitPreview(row: VmRow): string {
    if (!row.osUsername) return "";
    const hn = `${tenantSlug(domain)}-vm-${row.vmNameSuffix || "vm"}`;
    const isWin = row.osType === "windows"
      || (row.image?._detected_os === "windows")
      || row.image?.name?.toLowerCase().includes("win");
    if (isWin) {
      const isBuiltinAdmin = row.osUsername?.trim().toLowerCase() === "administrator";
      const userCmds = isBuiltinAdmin
        ? `net user Administrator "${row.osPassword || "<password>"}"\nnet user Administrator /active:yes\nwmic useraccount where "name='Administrator'" set PasswordExpires=False`
        : `net user Administrator /active:yes\nnet user "${row.osUsername}" "${row.osPassword || "<password>"}" /add /y\nnet localgroup Administrators "${row.osUsername}" /add\nwmic useraccount where "name='${row.osUsername}'" set PasswordExpires=False`;
      return `#ps1_sysnative\n# cloudbase-init userdata — executed on first boot\n${userCmds}${row.extraCloudInit ? `\n\n${row.extraCloudInit}` : ""}`;
    }
    return `#cloud-config\nhostname: ${hn}\nusers:\n  - name: ${row.osUsername}\n    sudo: ALL=(ALL) NOPASSWD:ALL\n    shell: /bin/bash\n    lock_passwd: false\n    passwd: "<hashed>"${row.osPassword ? ` # ✓ password set (${row.osPassword.length} chars)` : " # ⚠ no password"}\nssh_pwauth: true\nchpasswd:\n  expire: false${row.extraCloudInit ? `\n\n# -- extra --\n${row.extraCloudInit}` : ""}`;
  }

  // ──────────────────────────────────────────────────────────────
  // VM row helpers
  // ──────────────────────────────────────────────────────────────
  function updateRow(idx: number, patch: Partial<VmRow>) {
    setVmRows((prev) => prev.map((r, i) => i === idx ? { ...r, ...patch } : r));
  }

  function selectImage(idx: number, imgId: string) {
    const img = resources?.images.find((i) => i.id === imgId);
    // Detect Windows from _detected_os (API) OR image name as fallback
    const nameHint = ((img?.name || "") + (img?.os_type || "") + (img?.os_distro || "")).toLowerCase();
    const isWinByName = nameHint.includes("windows") || nameHint.includes("win");
    const osType = img ? (img._detected_os === "windows" || isWinByName ? "windows" : "linux") : "linux";
    const defUser = osType === "windows" ? "Administrator" : "ubuntu";
    const prevRow = vmRows[idx];
    // Replace username only if it still matches the previous OS default (not user-customized)
    const prevDefault = prevRow.osType === "windows" ? "Administrator" : "ubuntu";
    const shouldUpdateUser = prevRow.osUsername === prevDefault || prevRow.osUsername === "";
    // Auto-set volumeGb to at least image min_disk so user sees the correct required size
    const imgMinDisk = img?.min_disk || 0;
    const imgVirtualGb = img?.virtual_size ? Math.ceil(img.virtual_size / 1073741824) : 0;
    const minVolumeGb = Math.max(imgMinDisk, imgVirtualGb, 10);
    const newVolumeGb = Math.max(prevRow.volumeGb, minVolumeGb);
    updateRow(idx, {
      selectedImageId: imgId,
      osType,
      osUsername: shouldUpdateUser ? defUser : prevRow.osUsername,
      volumeGb: newVolumeGb,
    });
  }

  function selectNetwork(idx: number, netId: string) {
    updateRow(idx, { selectedNetworkId: netId, fixedIp: "", availableIps: [] });
    if (netId) fetchAvailableIps(netId, idx);
  }

  function toggleSG(idx: number, sgName: string) {
    const row = vmRows[idx];
    const has = row.selectedSGs.includes(sgName);
    const next = has ? row.selectedSGs.filter((s) => s !== sgName) : [...row.selectedSGs, sgName];
    updateRow(idx, { selectedSGs: next });
  }

  // ──────────────────────────────────────────────────────────────
  // Submit batch
  // ──────────────────────────────────────────────────────────────
  async function handleSubmit() {
    setSubmitting(true);
    setFormMsg(null);
    try {
      const payload = {
        name: batchName || `VM Provision — ${domain}/${project} — ${new Date().toLocaleDateString()}`,
        domain_name: domain,
        project_name: project,
        require_approval: requireApproval,
        vms: vmRows.map((row) => {
          const img = resources?.images.find((i) => i.id === row.selectedImageId);
          const fl  = resources?.flavors.find((f) => f.id === row.selectedFlavorId);
          const net = resources?.networks.find((n) => n.id === row.selectedNetworkId);
          return {
            vm_name_suffix: row.vmNameSuffix,
            count: row.count,
            image_name: img?.name,
            image_id: row.selectedImageId,
            flavor_name: fl?.name,
            flavor_id: row.selectedFlavorId,
            volume_gb: row.volumeGb,
            network_name: net?.name,
            network_id: row.selectedNetworkId,
            security_groups: row.selectedSGs,
            fixed_ip: row.useStaticIp ? row.fixedIp : null,
            hostname: row.hostname || null,
            os_username: row.osUsername,
            os_password: row.osPassword,
            extra_cloudinit: row.extraCloudInit || null,
            os_type: row.osType,
            delete_on_termination: row.deleteOnTermination,
          };
        }),
      };

      const data = await apiFetch<{ batch_id: number }>("/api/vm-provisioning/batches", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setFormMsg({ type: "success", text: `Batch #${data.batch_id} created. Switching to batch list.` });
      await fetchBatches();
      setTimeout(() => { setMode("batches"); resetForm(); }, 1500);
    } catch (e: any) {
      setFormMsg({ type: "error", text: e.message });
    } finally {
      setSubmitting(false);
    }
  }

  function resetForm() {
    setStep(1); setDomain(""); setProject(""); setBatchName("");
    setVmRows([newVmRow()]); setResources(null); setQuotaUsage(null);
    setFormMsg(null); setResError("");
  }

  // ──────────────────────────────────────────────────────────────
  // Batch actions
  // ──────────────────────────────────────────────────────────────
  async function dryRun(batchId: number) {
    setDryRunRunning(true); setBatchMsg(null);
    setActionBusy((p) => ({ ...p, [batchId]: "dryrun" }));
    try {
      const data = await apiFetch<{ status: string }>(`/api/vm-provisioning/batches/${batchId}/dry-run`, {
        method: "POST",
      });
      setBatchMsg({ type: data.status === "dry_run_passed" ? "success" : "error", text: `Dry-run: ${data.status}` });
      await refreshBatch(batchId);
      setExpandedIds((p) => new Set([...Array.from(p), batchId]));
    } catch (e: any) {
      setBatchMsg({ type: "error", text: e.message });
    } finally {
      setDryRunRunning(false);
      setActionBusy((p) => { const n = { ...p }; delete n[batchId]; return n; });
    }
  }

  async function submitBatch(batchId: number) {
    setBatchMsg(null);
    setActionBusy((p) => ({ ...p, [batchId]: "submit" }));
    try {
      await apiFetch(`/api/vm-provisioning/batches/${batchId}/submit`, { method: "POST" });
      setBatchMsg({ type: "info", text: "Submitted for approval" });
      await fetchBatches();
    } catch (e: any) {
      setBatchMsg({ type: "error", text: e.message });
    } finally {
      setActionBusy((p) => { const n = { ...p }; delete n[batchId]; return n; });
    }
  }

  async function decideBatch(batchId: number, decision: "approve" | "reject") {
    setBatchMsg(null);
    setActionBusy((p) => ({ ...p, [batchId]: decision }));
    try {
      await apiFetch(`/api/vm-provisioning/batches/${batchId}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      setBatchMsg({ type: decision === "approve" ? "success" : "warn", text: `Batch ${decision}d` });
      await fetchBatches();
    } catch (e: any) {
      setBatchMsg({ type: "error", text: e.message });
    } finally {
      setActionBusy((p) => { const n = { ...p }; delete n[batchId]; return n; });
    }
  }

  async function executeBatch(batchId: number) {
    setExecRunning(true); setBatchMsg(null);
    setActionBusy((p) => ({ ...p, [batchId]: "execute" }));
    try {
      await apiFetch(`/api/vm-provisioning/batches/${batchId}/execute`, { method: "POST" });
      setBatchMsg({ type: "info", text: "Execution started. Polling for status…" });
      await fetchBatches();
      setExpandedIds((p) => new Set([...Array.from(p), batchId]));
      setTimeout(() => loadBatchLogs(batchId), 2000); // load logs after thread starts
    } catch (e: any) {
      setBatchMsg({ type: "error", text: e.message });
    } finally {
      setExecRunning(false);
      setActionBusy((p) => { const n = { ...p }; delete n[batchId]; return n; });
    }
  }

  async function reExecuteBatch(batchId: number) {
    setBatchMsg(null);
    setActionBusy((p) => ({ ...p, [batchId]: "reexec" }));
    try {
      await apiFetch(`/api/vm-provisioning/batches/${batchId}/re-execute`, { method: "POST" });
      setBatchMsg({ type: "info", text: "Re-execution started — retrying failed VMs…" });
      await fetchBatches();
      setExpandedIds((p) => new Set([...Array.from(p), batchId]));
      setTimeout(() => loadBatchLogs(batchId), 2000);
    } catch (e: any) {
      setBatchMsg({ type: "error", text: e.message });
    } finally {
      setActionBusy((p) => { const n = { ...p }; delete n[batchId]; return n; });
    }
  }

  async function resetBatch(batchId: number) {
    if (!window.confirm("Force-reset this batch to Failed? The execution thread will be abandoned and you can Re-run after.")) return;
    setBatchMsg(null);
    setActionBusy((p) => ({ ...p, [batchId]: "reset" }));
    try {
      await apiFetch(`/api/vm-provisioning/batches/${batchId}/reset`, { method: "POST" });
      setBatchMsg({ type: "info", text: "Batch reset to failed — click 🔁 Re-run to retry." });
      await fetchBatches();
    } catch (e: any) {
      setBatchMsg({ type: "error", text: e.message });
    } finally {
      setActionBusy((p) => { const n = { ...p }; delete n[batchId]; return n; });
    }
  }

  async function deleteBatch(batchId: number) {
    if (!window.confirm("Delete this batch? This cannot be undone.")) return;
    setBatchMsg(null);
    try {
      await apiFetch(`/api/vm-provisioning/batches/${batchId}`, { method: "DELETE" });
      setSelectedBatch(null);
      await fetchBatches();
    } catch (e: any) {
      setBatchMsg({ type: "error", text: e.message });
    }
  }

  async function refreshBatch(batchId: number) {
    try {
      const data = await apiFetch<Batch>(`/api/vm-provisioning/batches/${batchId}`);
      setSelectedBatch(data);
      setBatches((prev) => prev.map((b) => (b.id === batchId ? data : b)));
      loadBatchLogs(batchId);
    } catch (_) {}
  }

  // ──────────────────────────────────────────────────────────────
  // Step validation
  // ──────────────────────────────────────────────────────────────
  function step2Valid() {
    if (!vmRows.every((r) => r.vmNameSuffix && r.selectedImageId && r.selectedFlavorId && r.selectedNetworkId && r.volumeGb >= 1)) return false;
    if (!vmRows.every((r) => /^[a-z0-9][a-z0-9-]*$/.test(r.vmNameSuffix.toLowerCase()) && r.vmNameSuffix.length <= 30)) return false;
    const staticIps = vmRows.filter((r) => r.useStaticIp && r.fixedIp).map((r) => r.fixedIp);
    return new Set(staticIps).size === staticIps.length;
  }
  function step3Valid() { return vmRows.every((r) => r.osUsername && r.osPassword.length >= 8); }

  // ──────────────────────────────────────────────────────────────
  // Quota bar rendering
  // ──────────────────────────────────────────────────────────────
  const needs = computeNeeds();
  function QuotaBar({ label, needed, entry }: { label: string; needed: number; entry?: number | QuotaEntry }) {
    const { used, limit } = quotaFree(entry);
    const afterUse = used + needed;
    const pct = limit === 9999 ? 0 : Math.min(100, Math.round((afterUse / limit) * 100));
    return (
      <div className="vmp-quota-item">
        <div className="vmp-quota-label">{label}</div>
        <div className="vmp-quota-bar-wrap">
          <div className="vmp-quota-bar" style={{ width: `${pct}%` }} />
        </div>
        <div className="vmp-quota-nums">
          {needed > 0 ? `+${needed} | ` : ""}{used} / {limit === 9999 ? "∞" : limit} used
        </div>
      </div>
    );
  }

  // ──────────────────────────────────────────────────────────────
  // Badge
  // ──────────────────────────────────────────────────────────────
  function Badge({ status }: { status: string }) {
    const labels: Record<string, string> = {
      complete: "Complete", executing: "Executing", failed: "Failed",
      validated: "Validated", pending_approval: "Pending Approval",
      approved: "Approved", rejected: "Rejected",
      dry_run_passed: "Dry-run ✓", dry_run_failed: "Dry-run ✗",
      partially_failed: "Partial Fail",
    };
    return <span className={`vmp-badge ${status}`}>{labels[status] || status}</span>;
  }

  // ──────────────────────────────────────────────────────────────
  // Render helpers
  // ──────────────────────────────────────────────────────────────
  function renderStepper() {
    return (
      <div className="vmp-stepper">
        {STEPS.map((label, i) => {
          const num = i + 1;
          const cls = num < step ? "done" : num === step ? "active" : "";
          return (
            <React.Fragment key={num}>
              <div className={`vmp-step ${cls}`}>
                <div className="vmp-step-num">{num < step ? "✓" : num}</div>
                <div className="vmp-step-label">{label}</div>
              </div>
              {i < STEPS.length - 1 && <div className="vmp-step-sep" />}
            </React.Fragment>
          );
        })}
      </div>
    );
  }

  function renderAlert(msg: { type: string; text: string } | null) {
    if (!msg) return null;
    return <div className={`vmp-alert ${msg.type}`}>{msg.text}</div>;
  }

  // ── Step 1: Domain + Project ───────────────────────────────────
  function renderStep1() {
    const selectedDomainEntry = domainsData.find((d) => d.name === domain);
    const projectsForDomain = selectedDomainEntry?.projects || [];

    const filteredDomains = domainsData.filter((d) =>
      d.name.toLowerCase().includes(domainSearch.toLowerCase())
    );
    const filteredProjects = projectsForDomain.filter((p) =>
      p.name.toLowerCase().includes(projectSearch.toLowerCase())
    );

    return (
      <div className="vmp-card">
        <div className="vmp-card-title">
          Step 1 — Domain &amp; Project
          {domainsLoading && <span className="vmp-spinner" style={{ marginLeft: 10 }} />}
        </div>

        <div className="vmp-form-grid">
          {/* Domain picker */}
          <div className="vmp-field">
            <label className="vmp-label">Keystone Domain <span className="req">*</span></label>
            <div className="vmp-search-drop" ref={domainDropRef}>
              <div
                className={`vmp-search-drop-trigger${domainDropOpen ? " open" : ""}`}
                onClick={() => { setDomainDropOpen((v) => !v); setDomainSearch(""); }}
              >
                {domain
                  ? <span>{domain}</span>
                  : <span className="placeholder">{domainsLoading ? "Loading domains…" : "Select domain…"}</span>
                }
                <span className="arrow">▼</span>
              </div>

              {domainDropOpen && (
                <div className="vmp-search-drop-panel">
                  <div className="vmp-search-drop-search">
                    <input
                      autoFocus
                      type="text"
                      placeholder="Search domains…"
                      value={domainSearch}
                      onChange={(e) => setDomainSearch(e.target.value)}
                    />
                  </div>
                  <div className="vmp-search-drop-list">
                    {domainsLoading && domainsData.length === 0
                      ? <div className="vmp-search-drop-loading"><span className="vmp-spinner" /> Loading domains…</div>
                      : filteredDomains.length === 0
                      ? <div className="vmp-search-drop-empty">No domains matching "{domainSearch}"</div>
                      : filteredDomains.map((d) => (
                          <div
                            key={d.id}
                            className={`vmp-search-drop-option${domain === d.name ? " selected" : ""}`}
                            onClick={() => {
                              setDomain(d.name);
                              setProject("");
                              setResources(null);
                              setDomainDropOpen(false);
                              setProjectSearch("");
                            }}
                          >
                            {domain === d.name && <span className="opt-check">✓</span>}
                            <span>{d.name}</span>
                            <span style={{ marginLeft: "auto", color: "#475569", fontSize: "0.74rem" }}>
                              {d.projects.length} projects
                            </span>
                          </div>
                        ))
                    }
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Project picker */}
          <div className="vmp-field">
            <label className="vmp-label">Project <span className="req">*</span></label>
            <div className="vmp-search-drop" ref={projectDropRef}>
              <div
                className={`vmp-search-drop-trigger${!domain ? " disabled" : ""}${projectDropOpen ? " open" : ""}`}
                onClick={() => {
                  if (!domain) return;
                  setProjectDropOpen((v) => !v);
                  setProjectSearch("");
                }}
                style={!domain ? { opacity: 0.4, cursor: "not-allowed" } : {}}
              >
                {project
                  ? <span>{project}</span>
                  : <span className="placeholder">{!domain ? "Select domain first" : "Select project…"}</span>
                }
                <span className="arrow">▼</span>
              </div>

              {projectDropOpen && domain && (
                <div className="vmp-search-drop-panel">
                  <div className="vmp-search-drop-search">
                    <input
                      autoFocus
                      type="text"
                      placeholder="Search projects…"
                      value={projectSearch}
                      onChange={(e) => setProjectSearch(e.target.value)}
                    />
                  </div>
                  <div className="vmp-search-drop-list">
                    {filteredProjects.length === 0
                      ? <div className="vmp-search-drop-empty">No projects found</div>
                      : filteredProjects.map((p) => (
                          <div
                            key={p.id}
                            className={`vmp-search-drop-option${project === p.name ? " selected" : ""}`}
                            onClick={() => {
                              setProject(p.name);
                              setResources(null);
                              setProjectDropOpen(false);
                            }}
                          >
                            {project === p.name && <span className="opt-check">✓</span>}
                            <span>{p.name}</span>
                          </div>
                        ))
                    }
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          <button className="vmp-btn primary" disabled={!domain.trim() || !project.trim() || resLoading}
            onClick={fetchResources}>
            {resLoading ? <><span className="vmp-spinner" /> Loading resources…</> : "🔍 Load Resources"}
          </button>
        </div>

        {resError && <div className="vmp-alert error" style={{ marginTop: 12 }}>{resError}</div>}

        {resources && (
          <>
            <div className="vmp-alert success" style={{ marginTop: 12 }}>
              ✅ Loaded {resources.images.length} images · {resources.flavors.length} diskless flavors ·{" "}
              {resources.networks.length} networks · {resources.security_groups.length} security groups
            </div>

            {quotaUsage && (
              <div style={{ marginTop: 16 }}>
                <div className="vmp-card-title">Quota Overview</div>
                <div className="vmp-quota-panel">
                  <QuotaBar label="vCPUs"      needed={needs.vcpu} entry={quotaUsage.compute?.cores} />
                  <QuotaBar label="RAM"         needed={needs.ram}  entry={quotaUsage.compute?.ram} />
                  <QuotaBar label="Instances"   needed={needs.inst} entry={quotaUsage.compute?.instances} />
                  <QuotaBar label="Volumes"     needed={needs.vol}  entry={quotaUsage.storage?.volumes} />
                  <QuotaBar label="Volume GB"   needed={needs.gb}   entry={quotaUsage.storage?.gigabytes} />
                </div>
              </div>
            )}

            <div style={{ marginTop: 16 }}>
              <div className="vmp-toggle-row">
                <label className="vmp-toggle-switch">
                  <input type="checkbox" checked={requireApproval}
                    onChange={(e) => setRequireApproval(e.target.checked)} />
                  <span className="vmp-toggle-slider" />
                </label>
                <span className="vmp-toggle-label">Require approval before execution (recommended)</span>
              </div>
            </div>

            <div className="vmp-actions" style={{ marginTop: 20 }}>
              <button className="vmp-btn primary" onClick={() => setStep(2)}>
                Next: Configure VMs →
              </button>
            </div>
          </>
        )}
      </div>
    );
  }


  function renderVmRow(row: VmRow, idx: number) {
    const imgs = resources?.images || [];
    const flavors = resources?.flavors || [];
    const networks = resources?.networks || [];
    const sgs = resources?.security_groups || [];
    const previewName = row.vmNameSuffix
      ? vmNovaName(domain, row.vmNameSuffix, row.count > 1 ? 1 : undefined, row.count)
      : `${tenantSlug(domain)}_vm_…`;

    return (
      <div className="vmp-vm-row" key={row.id}>
        <div className="vmp-vm-row-header" onClick={() => updateRow(idx, { expanded: !row.expanded })}>
          <span style={{ fontSize: "0.9rem" }}>{row.expanded ? "▾" : "▸"}</span>
          <span className="vmp-vm-row-title">VM Row {idx + 1}</span>
          {row.vmNameSuffix && <span className="vmp-vm-row-preview">{previewName}{row.count > 1 ? ` (+${row.count - 1})` : ""}</span>}
          {vmRows.length > 1 && (
            <button className="vmp-remove-btn" onClick={(e) => { e.stopPropagation(); setVmRows((p) => p.filter((_, i) => i !== idx)); }}>
              Remove
            </button>
          )}
        </div>

        {row.expanded && (
          <div className="vmp-vm-row-body">
            {/* Basic info */}
            <div className="vmp-form-grid" style={{ marginBottom: 16 }}>
              <div className="vmp-field">
                <label className="vmp-label">VM Name Suffix <span className="req">*</span></label>
                <input className="vmp-input" placeholder="web" value={row.vmNameSuffix}
                  onChange={(e) => updateRow(idx, { vmNameSuffix: e.target.value.toLowerCase() })} />
                <div className="vmp-name-preview">{previewName}</div>
              </div>
              <div className="vmp-field">
                <label className="vmp-label">Count (1–20)</label>
                <input className="vmp-input" type="number" min={1} max={20} value={row.count}
                  onChange={(e) => updateRow(idx, { count: Math.min(20, Math.max(1, +e.target.value)) })} />
              </div>
              <div className="vmp-field">
                <label className="vmp-label">Boot Volume (GB) <span className="req">*</span></label>
                <input className="vmp-input" type="number" min={1} max={2048} value={row.volumeGb}
                  onChange={(e) => updateRow(idx, { volumeGb: Math.max(1, +e.target.value) })} />
              </div>
              <div className="vmp-field" style={{ justifyContent: "flex-end" }}>
                <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer", userSelect: "none" }}>
                  <input type="checkbox" checked={row.deleteOnTermination}
                    onChange={(e) => updateRow(idx, { deleteOnTermination: e.target.checked })} />
                  <span>Delete boot volume on VM deletion</span>
                </label>
              </div>
              <div className="vmp-field">
                <label className="vmp-label">Hostname Override</label>
                <input className="vmp-input" placeholder="auto" value={row.hostname}
                  onChange={(e) => updateRow(idx, { hostname: e.target.value })} />
              </div>
            </div>

            {/* Image selector */}
            <div className="vmp-field" style={{ marginBottom: 14 }}>
              <label className="vmp-label">Image <span className="req">*</span></label>
              <div className="vmp-image-grid">
                {imgs.map((img) => (
                  <div key={img.id} className={`vmp-image-card ${row.selectedImageId === img.id ? "selected" : ""}`}
                    onClick={() => selectImage(idx, img.id)}>
                    <div className="img-icon">{osIcon(img)}</div>
                    <div className="img-name">{img.name}</div>
                    <div className="img-meta">
                      {(() => {
                        const minD = img.min_disk && img.min_disk > 0 ? img.min_disk : 0;
                        const virtGb = img.virtual_size ? Math.ceil(img.virtual_size / 1073741824) : 0;
                        const diskGb = Math.max(minD, virtGb);
                        return diskGb > 0
                          ? <span title="Minimum disk size required to boot this image">💾 {diskGb} GB</span>
                          : <span title="Glance file size (virtual size unknown)">{fmtBytes(img.size)}</span>;
                      })()}
                    </div>
                  </div>
                ))}
                {imgs.length === 0 && <div style={{ color: "#64748b", fontSize: "0.8rem" }}>No images available</div>}
              </div>
            </div>

            {/* Flavor table */}
            <div className="vmp-field" style={{ marginBottom: 14 }}>
              <label className="vmp-label">Flavor (disk=0) <span className="req">*</span></label>
              <div className="vmp-flavor-wrap">
                <table className="vmp-flavor-table">
                  <thead><tr>
                    <th>Name</th><th>vCPU</th><th>RAM</th>
                  </tr></thead>
                  <tbody>
                    {flavors.map((fl) => (
                      <tr key={fl.id} className={row.selectedFlavorId === fl.id ? "selected" : ""}
                        onClick={() => updateRow(idx, { selectedFlavorId: fl.id })}>
                        <td>{fl.name}</td>
                        <td>{fl.vcpus}</td>
                        <td>{fmtMb(fl.ram)}</td>
                      </tr>
                    ))}
                    {flavors.length === 0 && <tr><td colSpan={3} style={{ textAlign: "center", color: "#64748b" }}>No disk=0 flavors</td></tr>}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Network + SG */}
            <div className="vmp-form-grid" style={{ marginBottom: 14 }}>
              <div className="vmp-field">
                <label className="vmp-label">Network <span className="req">*</span></label>
                <select className="vmp-select" value={row.selectedNetworkId}
                  onChange={(e) => selectNetwork(idx, e.target.value)}>
                  <option value="">— select network —</option>
                  {networks.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
                </select>
              </div>

              <div className="vmp-field">
                <label className="vmp-label">Security Groups</label>
                <div className="vmp-sg-wrap" onClick={() => updateRow(idx, { sgDropdownOpen: !row.sgDropdownOpen })}>
                  {row.selectedSGs.length === 0 && (
                    <span style={{ color: "var(--text-muted, #64748b)", fontSize: "0.8rem", padding: "4px 6px" }}>
                      Click to add security groups…
                    </span>
                  )}
                  {row.selectedSGs.map((sg) => (
                    <span key={sg} className="vmp-sg-chip">
                      {sg}
                      <span className="del" onClick={(e) => { e.stopPropagation(); toggleSG(idx, sg); }}>×</span>
                    </span>
                  ))}
                </div>
                {row.sgDropdownOpen && (
                  <div className="vmp-sg-dropdown">
                    {sgs.map((sg) => (
                      <div key={sg.id} className={`vmp-sg-option ${row.selectedSGs.includes(sg.name) ? "selected" : ""}`}
                        onClick={(e) => { e.stopPropagation(); toggleSG(idx, sg.name); }}>
                        {row.selectedSGs.includes(sg.name) ? "✓ " : ""}{sg.name}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Static IP */}
            <div className="vmp-field" style={{ marginBottom: 14 }}>
              <div className="vmp-toggle-row">
                <label className="vmp-toggle-switch">
                  <input type="checkbox" checked={row.useStaticIp}
                    onChange={(e) => updateRow(idx, { useStaticIp: e.target.checked })} />
                  <span className="vmp-toggle-slider" />
                </label>
                <span className="vmp-toggle-label">Use static IP</span>
              </div>
              {row.useStaticIp && (() => {
                const usedByOthers = vmRows
                  .filter((r, i) => i !== idx && r.useStaticIp && r.fixedIp)
                  .map((r) => r.fixedIp);
                const isDup = Boolean(row.fixedIp && usedByOthers.includes(row.fixedIp));
                const filteredIps = row.availableIps.filter((ip) => !usedByOthers.includes(ip));
                return (
                  <div style={{ marginTop: 8 }}>
                    <input className="vmp-input" placeholder="e.g. 10.0.0.20" value={row.fixedIp}
                      onChange={(e) => updateRow(idx, { fixedIp: e.target.value })}
                      style={{ fontFamily: "monospace", borderColor: isDup ? "#e53e3e" : undefined }} />
                    {isDup && (
                      <div style={{ fontSize: "0.78rem", color: "#e53e3e", marginTop: 3 }}>
                        ⚠ This IP is already assigned to another VM row
                      </div>
                    )}
                    {filteredIps.length > 0 && (
                      <div className="vmp-ip-list">
                        {filteredIps.map((ip) => (
                          <div key={ip} className={`vmp-ip-option ${row.fixedIp === ip ? "selected" : ""}`}
                            onClick={() => updateRow(idx, { fixedIp: ip })}>
                            {ip}
                          </div>
                        ))}
                      </div>
                    )}
                    {row.availableIps.length > filteredIps.length && (
                      <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: 4 }}>
                        {row.availableIps.length - filteredIps.length} IP(s) hidden — already used by other VM rows
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          </div>
        )}
      </div>
    );
  }

  function renderStep2() {
    return (
      <div className="vmp-card">
        <div className="vmp-card-title">Step 2 — VM Configuration</div>

        {/* Quota tally */}
        {quotaUsage && (
          <div className="vmp-quota-panel" style={{ marginBottom: 16 }}>
            <QuotaBar label="vCPUs"    needed={needs.vcpu} entry={quotaUsage.compute?.cores} />
            <QuotaBar label="RAM"      needed={needs.ram}  entry={quotaUsage.compute?.ram} />
            <QuotaBar label="Instances" needed={needs.inst} entry={quotaUsage.compute?.instances} />
            <QuotaBar label="Volumes"  needed={needs.vol}  entry={quotaUsage.storage?.volumes} />
            <QuotaBar label="Vol GB"   needed={needs.gb}   entry={quotaUsage.storage?.gigabytes} />
          </div>
        )}

        {vmRows.map((row, idx) => renderVmRow(row, idx))}

        <button className="vmp-btn add" onClick={() => setVmRows((p) => [...p, newVmRow()])}>
          + Add VM Row
        </button>

        <div className="vmp-actions" style={{ marginTop: 20 }}>
          <button className="vmp-btn ghost" onClick={() => setStep(1)}>← Back</button>
          <button className="vmp-btn primary" disabled={!step2Valid()}
            onClick={() => setStep(3)}>
            Next: OS Credentials →
          </button>
        </div>
      </div>
    );
  }

  // ── Step 3: OS Credentials ─────────────────────────────────────
  function renderStep3() {
    return (
      <div className="vmp-card">
        <div className="vmp-card-title">Step 3 — OS Credentials</div>

        {vmRows.map((row, idx) => {
          const preview = buildVmInitPreview(row);
          const isWin = row.osType === "windows";
          return (
            <div key={row.id} style={{ marginBottom: 24, paddingBottom: 20, borderBottom: "1px solid rgba(255,255,255,.08)" }}>
              {/* VM row header */}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <span style={{ fontSize: "1rem" }}>{isWin ? "🪟" : "🐧"}</span>
                <span style={{ fontSize: "0.82rem", fontFamily: "monospace", color: "#64748b" }}>
                  {vmNovaName(domain, row.vmNameSuffix, row.count > 1 ? 1 : undefined, row.count)}
                  {row.count > 1 ? ` … ×${row.count}` : ""}
                </span>
                <span style={{ fontSize: "0.72rem", color: isWin ? "#60a5fa" : "#86efac", background: "rgba(0,0,0,.25)", padding: "2px 6px", borderRadius: 4 }}>
                  {isWin ? "Windows" : "Linux"}
                </span>
              </div>

              {/* Windows OOBE notice */}
              {isWin && (
                <div style={{
                  display: "flex", gap: 10, alignItems: "flex-start",
                  background: "rgba(251,191,36,.08)", border: "1px solid rgba(251,191,36,.35)",
                  borderRadius: 6, padding: "10px 14px", marginBottom: 14,
                  fontSize: "0.82rem", color: "#fbbf24", lineHeight: 1.55,
                }}>
                  <span style={{ fontSize: "1.1rem", flexShrink: 0 }}>⚠️</span>
                  <span>
                    <strong>Windows OOBE notice:</strong> On first boot this VM will show the Windows
                    setup wizard (language, region, keyboard). You can choose any password there —
                    cloudbase-init will then run the script below and <em>replace</em> that password
                    with the one set in <strong>OS Password</strong> and create the account
                    <strong> {row.osUsername || "…"}</strong>. After that reboot you can log in with
                    the credentials configured here.
                  </span>
                </div>
              )}

              <div className="vmp-form-grid">
                <div className="vmp-field">
                  <label className="vmp-label">OS Username <span className="req">*</span></label>
                  <input className="vmp-input" value={row.osUsername}
                    placeholder={isWin ? "Administrator" : "ubuntu"}
                    onChange={(e) => updateRow(idx, { osUsername: e.target.value })} />
                </div>
                <div className="vmp-field">
                  <label className="vmp-label">{isWin ? "OS Password (applied post-OOBE)" : "OS Password"} <span className="req">*</span></label>
                  <input className="vmp-input" type="password" placeholder="min 6 chars"
                    value={row.osPassword}
                    onChange={(e) => updateRow(idx, { osPassword: e.target.value })} />
                  {row.osPassword.length > 0 && row.osPassword.length < 6 && (
                    <div style={{ fontSize: "0.78rem", color: "#e53e3e", marginTop: 3 }}>
                      Password too short ({row.osPassword.length}/6 chars minimum)
                    </div>
                  )}
                  {row.osPassword.length >= 6 && (
                    <div style={{ fontSize: "0.78rem", color: "#38a169", marginTop: 3 }}>
                      ✓ Password set ({row.osPassword.length} chars)
                    </div>
                  )}
                </div>
                <div className="vmp-field span2">
                  <button className="vmp-collapsible-btn"
                    onClick={() => updateRow(idx, { showExtra: !row.showExtra })}>
                    {row.showExtra ? "▾" : "▸"} {isWin ? "Additional PowerShell commands (optional)" : "Additional cloud-init YAML (optional)"}
                  </button>
                  {row.showExtra && (
                    <textarea className="vmp-textarea" rows={4}
                      placeholder={isWin
                        ? "e.g. Install-WindowsFeature -Name Web-Server"
                        : "e.g. packages:\n  - nginx\n  - htop"}
                      value={row.extraCloudInit}
                      onChange={(e) => updateRow(idx, { extraCloudInit: e.target.value })} />
                  )}
                </div>
              </div>
              {/* Per-VM init script preview */}
              {preview && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: "0.75rem", color: "#64748b", marginBottom: 4 }}>
                    {isWin ? "🪟 PowerShell userdata preview" : "🐧 cloud-init preview"}
                  </div>
                  <pre className="vmp-cloudinit-preview" style={{ margin: 0 }}>{preview}</pre>
                </div>
              )}
            </div>
          );
        })}

        <div className="vmp-actions" style={{ marginTop: 20 }}>
          <button className="vmp-btn ghost" onClick={() => setStep(2)}>← Back</button>
          <button className="vmp-btn primary" disabled={!step3Valid()}
            onClick={() => setStep(4)}>
            Next: Review →
          </button>
        </div>
      </div>
    );
  }

  // ── Step 4: Review & Submit ────────────────────────────────────
  function renderStep4() {
    const totalVMs = vmRows.reduce((s, r) => s + r.count, 0);
    return (
      <div className="vmp-card">
        <div className="vmp-card-title">Step 4 — Review &amp; Submit</div>

        <div className="vmp-form-grid" style={{ marginBottom: 16 }}>
          <div className="vmp-field span2">
            <label className="vmp-label">Batch Name</label>
            <input className="vmp-input" placeholder="e.g. Phase-2 web servers"
              value={batchName}
              onChange={(e) => setBatchName(e.target.value)} />
          </div>
        </div>

        <div className="vmp-alert info" style={{ marginBottom: 14 }}>
          <strong>Summary</strong>: provision <strong>{totalVMs}</strong> VM{totalVMs !== 1 ? "s" : ""} in{" "}
          <strong>{domain} / {project}</strong> &nbsp;·&nbsp;
          {requireApproval ? "⚠️ Approval required before execution" : "No approval required"}
        </div>

        <table className="vmp-table" style={{ marginBottom: 16 }}>
          <thead><tr>
            <th>Name Pattern</th><th>Count</th><th>Image</th><th>Flavor</th><th>Vol GB</th><th>Network</th>
          </tr></thead>
          <tbody>
            {vmRows.map((row) => {
              const img = resources?.images.find((x) => x.id === row.selectedImageId);
              const fl  = resources?.flavors.find((x) => x.id === row.selectedFlavorId);
              const net = resources?.networks.find((x) => x.id === row.selectedNetworkId);
              return (
                <tr key={row.id}>
                  <td className="mono">{vmNovaName(domain, row.vmNameSuffix)}</td>
                  <td>{row.count}</td>
                  <td>{img?.name || "—"}</td>
                  <td>{fl?.name || "—"}</td>
                  <td>{row.volumeGb}</td>
                  <td>{net?.name || "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {renderAlert(formMsg)}

        <div className="vmp-actions">
          <button className="vmp-btn ghost" onClick={() => setStep(3)}>← Back</button>
          <button className="vmp-btn success" disabled={submitting}
            onClick={handleSubmit}>
            {submitting ? <><span className="vmp-spinner" /> Submitting…</> : "✅ Create Batch"}
          </button>
        </div>
      </div>
    );
  }

  // ── Excel helpers ──────────────────────────────────────────────
  async function downloadTemplate() {
    const res = await fetch(`${API_BASE}/api/vm-provisioning/template`, {
      headers: authHeaders(),
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "vm_provisioning_template.xlsx"; a.click();
    URL.revokeObjectURL(url);
  }

  async function handleExcelUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setExcelUploading(true); setExcelErrors([]); setExcelVms(null); setExcelMsg(null);
    try {
      const fd = new FormData(); fd.append("file", f);
      const data = await apiFetch<{ status: string; vms: any[]; errors: string[]; row_count: number }>(
        "/api/vm-provisioning/upload", { method: "POST", body: fd },
      );
      if (data.status === "invalid") {
        setExcelErrors(data.errors);
      } else {
        setExcelVms(data.vms);
        setExcelBatchName(`Import — ${f.name.replace(/\.xlsx$/i, "")}`);
      }
      setExcelImportOpen(true);
    } catch (err: any) {
      setExcelErrors([err.message]); setExcelImportOpen(true);
    } finally {
      setExcelUploading(false); e.target.value = "";
    }
  }

  async function submitExcelBatch() {
    if (!excelVms?.length) return;
    setExcelSubmitting(true); setExcelMsg(null);
    try {
      const firstVm = excelVms[0];
      const payload = {
        name: excelBatchName || "Excel Import",
        domain_name: firstVm.domain_name,
        project_name: firstVm.project_name,
        require_approval: true,
        vms: excelVms.map((v) => ({
          vm_name_suffix: v.vm_name_suffix,
          count: v.count,
          image_name: v.image_name,
          flavor_name: v.flavor_name,
          volume_gb: v.volume_gb || 20,
          network_name: v.network_name,
          security_groups: v.security_groups || [],
          fixed_ip: v.fixed_ip || null,
          hostname: v.hostname || null,
          os_username: v.os_username,
          os_password: v.os_password,
          extra_cloudinit: v.extra_cloudinit || null,
        })),
      };
      const data = await apiFetch<{ batch_id: number }>("/api/vm-provisioning/batches", {
        method: "POST", body: JSON.stringify(payload),
      });
      setExcelMsg({ type: "success", text: `✅ Batch #${data.batch_id} created from Excel!` });
      await fetchBatches();
      setTimeout(() => { setExcelImportOpen(false); setExcelVms(null); }, 2000);
    } catch (err: any) {
      setExcelMsg({ type: "error", text: err.message });
    } finally {
      setExcelSubmitting(false);
    }
  }

  // ── Batch list ─────────────────────────────────────────────────
  function renderBatchList() {
    function toggleExpand(id: number) {
      setExpandedIds((prev) => {
        const next = new Set(Array.from(prev));
        next.has(id) ? next.delete(id) : next.add(id);
        return next;
      });
      loadBatchLogs(id); // refresh logs whenever panel opens/closes
    }

    function BatchActions({ b }: { b: Batch }) {
      const busy = actionBusy[b.id];
      const canDryRun = ["validated", "dry_run_passed", "dry_run_failed"].includes(b.status);
      const canSubmit = false; // approval_status starts as pending_approval from creation — Submit is redundant
      const needsApproval = b.require_approval && b.approval_status === "pending_approval"
        && !["executing", "complete", "failed", "partially_failed"].includes(b.status);
      const canExecute = ["validated", "dry_run_passed", "dry_run_failed"].includes(b.status) &&
        (!b.require_approval || b.approval_status === "approved");
      const canReExecute = ["failed", "partially_failed"].includes(b.status) &&
        (!b.require_approval || b.approval_status === "approved");
      const isExecuting = b.status === "executing";

      return (
        <div className="vmp-batch-actions">
          {isExecuting && (
            <span className="vmp-badge executing" style={{ fontSize: "0.72rem" }}>
              <span className="vmp-spinner" style={{ width: 10, height: 10, marginRight: 4 }} /> Running…
            </span>
          )}
          {isExecuting && (
            <button className="vmp-btn danger sm" title="Force-reset stuck execution"
              disabled={!!busy}
              onClick={() => resetBatch(b.id)}>
              {busy === "reset" ? <><span className="vmp-spinner" /> …</> : "⚠ Reset"}
            </button>
          )}
          {canDryRun && (
            <button className="vmp-btn primary sm" disabled={!!busy}
              title="Dry-run: validate quota headroom and resolve image/flavor/network names without creating any resources"
              onClick={() => dryRun(b.id)}>
              {busy === "dryrun" ? <><span className="vmp-spinner" /> …</> : "🧪 Dry-run"}
            </button>
          )}
          {canSubmit && (
            <button className="vmp-btn ghost sm" disabled={!!busy}
              onClick={() => submitBatch(b.id)}>
              {busy === "submit" ? <><span className="vmp-spinner" /> …</> : "📤 Submit"}
            </button>
          )}
          {needsApproval && (
            <>
              <button className="vmp-btn success sm" disabled={!!busy}
                title="Approve this batch so it can be executed"
                onClick={() => decideBatch(b.id, "approve")}>
                {busy === "approve" ? <><span className="vmp-spinner" /> …</> : "✅ Approve"}
              </button>
              <button className="vmp-btn danger sm" disabled={!!busy}
                title="Reject this batch — it will not be executed"
                onClick={() => decideBatch(b.id, "reject")}>
                ❌ Reject
              </button>
            </>
          )}
          {canExecute && (
            <button className="vmp-btn success sm" disabled={!!busy}
              title="Execute: create boot volumes and provision all VMs in this batch"
              onClick={() => executeBatch(b.id)}>
              {busy === "execute" ? <><span className="vmp-spinner" /> …</> : "▶ Execute"}
            </button>
          )}
          {canReExecute && (
            <button className="vmp-btn warn sm" disabled={!!busy}
              title="Re-run: retry failed VMs only — already-completed VMs are skipped"
              onClick={() => reExecuteBatch(b.id)}>
              {busy === "reexec" ? <><span className="vmp-spinner" /> …</> : "🔁 Re-run"}
            </button>
          )}
          <button className="vmp-btn ghost sm" title="Refresh status" onClick={() => refreshBatch(b.id)}>🔄</button>
          {b.status !== "executing" && (
            <button className="vmp-btn danger sm" title="Delete this batch" onClick={() => deleteBatch(b.id)}>🗑</button>
          )}
          <button className="vmp-btn ghost sm"
            title={expandedIds.has(b.id) ? "Collapse details" : "Expand details — view VM status, dry-run results, and execution logs"}
            onClick={() => toggleExpand(b.id)}
            style={{ minWidth: 32, fontWeight: 700 }}>
            {expandedIds.has(b.id) ? "▲" : "▼"}
          </button>
        </div>
      );
    }

    function BatchDetail({ b }: { b: Batch }) {
      const detail = batches.find((x) => x.id === b.id) ?? b;
      return (
        <div className="vmp-batch-detail">
          {/* Meta row */}
          <div className="vmp-batch-detail-meta">
            <span>🗂 {detail.domain_name} / {detail.project_name}</span>
            <span>👤 {detail.created_by}</span>
            <span>🕒 {new Date(detail.created_at).toLocaleString()}</span>
            {detail.require_approval && detail.approval_status !== "approved"
              ? <span style={{ color: "#f59e0b" }}>⚠️ Pending approval</span>
              : null}
          </div>

          {/* VM rows */}
          {detail.vms && detail.vms.length > 0 && (
            <div className="vmp-batch-vm-list">
              <div className="vmp-batch-detail-section">VM Execution Status</div>
              {detail.vms.map((vm) => {
                const icon = vm.status === "complete" ? "✅"
                  : vm.status === "failed" ? "❌"
                  : vm.status === "executing" || vm.status === "pending" ? "⏳"
                  : "⬜";
                return (
                  <div key={vm.id} className={`vmp-batch-vm-row ${vm.status}`}>
                    <span className="vmp-batch-vm-icon">{icon}</span>
                    <span className="vmp-batch-vm-name mono">{vm.vm_name_suffix}</span>
                    <span className="vmp-batch-vm-count">×{vm.count}</span>
                    <Badge status={vm.status} />
                    {vm.assigned_ips && vm.assigned_ips.length > 0 && (
                      <span className="vmp-batch-vm-ips mono">{vm.assigned_ips.join(", ")}</span>
                    )}
                    {vm.pcd_server_ids && vm.pcd_server_ids.length > 0 && (
                      <span className="vmp-batch-vm-ids mono"
                        title={vm.pcd_server_ids.join(", ")}
                        style={{ fontSize: "0.7rem", color: "#64748b", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {vm.pcd_server_ids[0].slice(0, 8)}…
                      </span>
                    )}
                    {vm.error_msg && (
                      <span className="vmp-batch-vm-err">⚠ {vm.error_msg}</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Dry-run results */}
          {detail.dry_run_results && (
            <div className="vmp-dryrun-section" style={{ marginTop: 12 }}>
              <div className="vmp-batch-detail-section">Dry-run Results</div>
              {detail.dry_run_results.quota && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginBottom: 4 }}>Quota Headroom</div>
                  {detail.dry_run_results.quota.map((q) => (
                    <div key={q.resource} className="vmp-check-row">
                      <span className="vmp-check-icon">{q.status === "ok" ? "✅" : "❌"}</span>
                      <span className="vmp-check-name">{q.resource}</span>
                      <span className={`vmp-check-detail ${q.status !== "ok" ? "err" : ""}`}>
                        need {q.needed}, free {q.free}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {detail.dry_run_results.per_vm?.map((vm) => (
                <div key={vm.vm_id} style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginBottom: 3, fontFamily: "monospace" }}>
                    {vm.vm_name_suffix} ×{vm.count}
                  </div>
                  {vm.checks.map((ck, ci) => (
                    <div key={ci} className="vmp-check-row">
                      <span className="vmp-check-icon">
                        {ck.status === "ok" ? "✅" : ck.status === "warning" ? "⚠️" : "❌"}
                      </span>
                      <span className="vmp-check-name">{ck.check}</span>
                      <span className={`vmp-check-detail ${ck.status === "error" ? "err" : ck.status === "warning" ? "warn" : ""}`}>
                        {ck.detail}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* Execution Logs */}
          {(() => {
            const logs = batchLogs[b.id];
            if (!logs || logs.length === 0) return null;
            return (
              <div style={{ marginTop: 12 }}>
                <div className="vmp-batch-detail-section">Execution Logs</div>
                <div style={{
                  background: "#0f172a", borderRadius: 6, padding: "8px 12px",
                  maxHeight: 220, overflowY: "auto", fontFamily: "monospace",
                  fontSize: "0.72rem", color: "#94a3b8",
                }}>
                  {logs.map((l: any) => (
                    <div key={l.id} style={{ marginBottom: 3, lineHeight: 1.5 }}>
                      <span style={{ color: "#475569", marginRight: 8 }}>
                        {new Date(l.created_at).toLocaleTimeString()}
                      </span>
                      <span style={{
                        color: l.action.includes("fail") || l.action.includes("error") ? "#f87171"
                          : l.action.includes("ready") || l.action.includes("complete") || l.action.includes("created") ? "#4ade80"
                          : "#94a3b8",
                        marginRight: 6,
                      }}>
                        [{l.action}]
                      </span>
                      {typeof l.details === "object" && l.details !== null
                        ? (l.details.message ?? JSON.stringify(l.details))
                        : String(l.details ?? "")}
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}
        </div>
      );
    }

    return (
      <div>
        {/* Hidden Excel file input */}
        <input ref={excelInputRef} type="file" accept=".xlsx" style={{ display: "none" }}
          onChange={handleExcelUpload} />

        {/* Excel import panel */}
        {excelImportOpen && (
          <div className="vmp-card" style={{ marginBottom: 20 }}>
            <div className="vmp-card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>📊 Import from Excel</span>
              <button className="vmp-modal-close" onClick={() => { setExcelImportOpen(false); setExcelVms(null); setExcelErrors([]); setExcelMsg(null); }}>×</button>
            </div>
            {excelErrors.length > 0 && (
              <div className="vmp-alert error">
                <strong>Validation errors ({excelErrors.length}):</strong>
                <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
                  {excelErrors.map((e, i) => <li key={i} style={{ fontSize: "0.82rem" }}>{e}</li>)}
                </ul>
              </div>
            )}
            {excelVms && excelVms.length > 0 && (
              <>
                <div className="vmp-alert success">
                  ✅ Parsed <strong>{excelVms.length}</strong> VM row{excelVms.length !== 1 ? "s" : ""} —
                  Domain: <strong>{excelVms[0].domain_name}</strong> / Project: <strong>{excelVms[0].project_name}</strong>
                </div>
                <div className="vmp-table-wrap" style={{ marginTop: 10, maxHeight: 240, overflowY: "auto" }}>
                  <table className="vmp-table">
                    <thead><tr><th>Suffix</th><th>Count</th><th>Image</th><th>Flavor</th><th>Vol GB</th><th>Network</th><th>User</th></tr></thead>
                    <tbody>
                      {excelVms.map((v, i) => (
                        <tr key={i}>
                          <td className="mono">{v.vm_name_suffix}</td><td>{v.count}</td>
                          <td>{v.image_name}</td><td>{v.flavor_name}</td>
                          <td>{v.volume_gb}</td><td>{v.network_name}</td>
                          <td className="mono">{v.os_username}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="vmp-form-grid" style={{ marginTop: 14 }}>
                  <div className="vmp-field span2">
                    <label className="vmp-label">Batch Name</label>
                    <input className="vmp-input" value={excelBatchName}
                      onChange={(e) => setExcelBatchName(e.target.value)} />
                  </div>
                </div>
                {renderAlert(excelMsg)}
                <div className="vmp-actions" style={{ marginTop: 12 }}>
                  <button className="vmp-btn success" disabled={excelSubmitting} onClick={submitExcelBatch}>
                    {excelSubmitting ? <><span className="vmp-spinner" /> Creating…</> : "✅ Create Batch from Excel"}
                  </button>
                </div>
              </>
            )}
            {!excelVms && excelErrors.length === 0 && renderAlert(excelMsg)}
          </div>
        )}

        {renderAlert(batchMsg)}

        {batchesLoading && batches.length === 0 && (
          <div className="vmp-empty"><span className="vmp-spinner" /> Loading batches…</div>
        )}
        {!batchesLoading && batches.length === 0 && (
          <div className="vmp-empty">No provisioning batches yet. Click "New Batch" to get started.</div>
        )}

        <div className="vmp-batch-list">
          {batches.map((b) => (
            <div key={b.id} className={`vmp-batch-card ${b.status}`}>
              <div className="vmp-batch-card-header">
                <span className="vmp-batch-id mono">#{b.id}</span>
                <span className="vmp-batch-name">{b.name}</span>
                <div className="vmp-batch-badges">
                  <Badge status={b.status} />
                  {b.approval_status !== b.status && <Badge status={b.approval_status} />}
                </div>
                <BatchActions b={b} />
              </div>
              {expandedIds.has(b.id) && <BatchDetail b={b} />}
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Main render ────────────────────────────────────────────────
  return (
    <div className="vmp-container">
      {/* Back bar */}
      <div className="vmp-back-bar">
        <button className="vmp-back-btn" onClick={onBack}>← Runbooks</button>
        <span className="vmp-back-title">☁️ VM Provisioning</span>
        <span className="vmp-back-sub">Runbook 2 · Boot-from-volume · cloud-init</span>
      </div>

      {/* Mode tabs */}
      <div className="vmp-mode-tabs" style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 6 }}>
        <button className={`vmp-mode-tab ${mode === "batches" ? "active" : ""}`}
          onClick={() => setMode("batches")}>
          📋 Batch History
        </button>
        <button className={`vmp-mode-tab ${mode === "create" ? "active" : ""}`}
          onClick={() => { setMode("create"); resetForm(); }}>
          ➕ New Batch
        </button>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button className="vmp-btn ghost sm" onClick={downloadTemplate} title="Download Excel bulk-upload template">
            📥 Template
          </button>
          <button className="vmp-btn ghost sm" disabled={excelUploading}
            onClick={() => excelInputRef.current?.click()}
            title="Import VMs from filled Excel template">
            {excelUploading ? <><span className="vmp-spinner" /> Uploading…</> : "📤 Import Excel"}
          </button>
        </div>
      </div>

      {/* Batch list view */}
      {mode === "batches" && renderBatchList()}

      {/* Create form */}
      {mode === "create" && (
        <>
          {renderStepper()}
          {step === 1 && renderStep1()}
          {step === 2 && renderStep2()}
          {step === 3 && renderStep3()}
          {step === 4 && renderStep4()}
        </>
      )}
    </div>
  );
};

export default VmProvisioningTab;
