"""
Migration Engine  —  Pure logic for VMware → PCD migration planning
====================================================================
All functions are pure (data in → result out). No HTTP, no DB access.
Designed for testability and config-driven behaviour.

Responsibilities:
  • RVTools XLSX column normalization & fuzzy matching
  • Tenant detection heuristics
  • Risk / complexity scoring
  • Warm vs cold classification
  • Bandwidth & downtime estimation (Phase 3 — stubs here)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("migration_engine")

# =====================================================================
# 1.  RVTools Column Normalization
# =====================================================================

# Canonical column names we want  →  list of aliases that RVTools versions use
COLUMN_ALIASES: Dict[str, List[str]] = {
    # --- vInfo sheet ---
    "vm_name":          ["VM", "Name", "VM Name"],
    "power_state":      ["Powerstate", "Power State", "Power state"],
    "template":         ["Template"],
    "guest_os":         ["OS according to the configuration file", "Config OS", "OS Config", "OS"],
    "guest_os_tools":   ["OS according to the VMware Tools", "OS Tools", "Tools OS"],
    "folder_path":      ["Folder", "Folder Path", "VM Folder"],
    "resource_pool":    ["Resource pool", "Resource Pool", "ResourcePool"],
    "vapp_name":        ["vApp", "vApp name", "vApp Name"],
    "annotation":       ["Annotation", "Notes", "Description"],
    "cpu_count":        ["CPUs", "Num CPUs", "Num CPU", "vCPUs", "# CPUs"],
    "ram_mb":           ["Memory", "Memory MB", "Mem MB", "RAM", "RAM MB"],
    "host_name":        ["Host", "ESX Host", "Host Name"],
    "cluster":          ["Cluster", "Cluster Name"],
    "datacenter":       ["Datacenter", "DC", "Datacenter Name"],
    "vm_uuid":          ["VM UUID", "UUID", "VM Id"],
    "firmware":         ["Firmware", "Boot Type"],
    "change_tracking":  ["CBT", "Change Block Tracking", "Changed Block Tracking"],
    "connection_state": ["Connection State", "ConnectionState"],
    "dns_name":         ["DNS Name", "DNS", "Guest Hostname"],
    "primary_ip":       ["Primary IP Address", "IP Address", "Primary IP", "IP", "Guest IP"],
    "provisioned_mb":   ["Provisioned MB", "Provisioned MiB", "Provisioned (MB)"],
    "in_use_mb":        ["In Use MB", "In Use MiB", "In Use (MB)"],

    # --- vDisk sheet ---
    "disk_vm_name":     ["VM", "Name", "VM Name"],
    "disk_label":       ["Disk", "Disk Label", "Label"],
    "disk_path":        ["Path", "Disk Path", "Disk File"],
    "capacity_mb":      ["Capacity MB", "Capacity MiB", "Capacity (MB)", "Size MB", "Disk Size MB"],
    "thin":             ["Thin", "Thin Provisioned", "Thin provisioned"],
    "eagerly_scrub":    ["Eagerly Scrub", "EagerlyScrub"],
    "datastore":        ["Datastore"],

    # --- vNIC sheet ---
    "nic_vm_name":      ["VM", "Name", "VM Name"],
    "nic_label":        ["Network Adapter", "NIC", "Adapter", "NIC Label"],
    "adapter_type":     ["Adapter Type", "Type"],
    "network_name":     ["Network", "Network Name", "Portgroup"],
    "nic_connected":    ["Connected", "Is Connected"],
    "mac_address":      ["Mac Address", "MAC", "MAC Address"],
    "ip_address":       ["IP Address", "IP", "IP Addresses"],

    # --- vHost sheet ---
    "host_host_name":   ["Host", "Name", "Host Name"],
    "host_cluster":     ["Cluster", "Cluster Name"],
    "host_datacenter":  ["Datacenter", "DC"],
    "host_cpu_model":   ["CPU Model", "Processor Type"],
    "host_cpu_count":   ["# CPU", "Num CPU", "CPU Sockets", "# Sockets"],
    "host_cpu_cores":   ["# Cores", "Cores per CPU", "Cores", "CPU Cores"],
    "host_cpu_threads":   ["# Threads", "Threads"],
    "host_ram_mb":      ["Memory", "Memory MB", "Mem MB", "ESX Memory"],
    "host_nic_count":   ["# NICs", "NICs", "Num NICs"],
    "host_nic_speed":   ["Speed", "NIC Speed", "Max Speed", "Speed (Mb)"],
    "host_esx_version": ["ESX Version", "ESXi Version", "Version"],

    # --- vCluster sheet ---
    "cluster_name_col": ["Cluster", "Name", "Cluster Name"],
    "cluster_datacenter": ["Datacenter", "DC"],
    "cluster_host_count": ["NumHosts", "# Hosts", "Hosts", "Num Hosts"],
    "cluster_total_cpu":  ["Total CPU", "Total CPU MHz", "Total CPU (MHz)"],
    "cluster_total_ram":  ["Total Memory", "Total Memory MB", "Total Mem"],
    "cluster_ha":         ["HA Enabled", "HA enabled", "HA"],
    "cluster_drs":        ["DRS Enabled", "DRS enabled", "DRS"],

    # --- vSnapshot sheet ---
    "snap_vm_name":     ["VM", "Name", "VM Name"],
    "snap_name":        ["Snapshot Name", "Name", "Snapshot"],
    "snap_description": ["Description"],
    "snap_created":     ["Date / time", "Date/Time", "Created", "Date", "Created Date"],
    "snap_size_mb":     ["Size MB", "Size MiB", "Size (MB)", "Size"],
    "snap_is_current":  ["Current", "IsCurrent"],
}


def _normalize_header(header: str) -> str:
    """Strip whitespace, lowercase, collapse multi-spaces."""
    return re.sub(r"\s+", " ", header.strip()).lower()


def build_column_map(sheet_headers: List[str], prefix: str = "") -> Dict[str, int]:
    """
    Given a list of actual Excel column headers, return a mapping from
    canonical name → column index.  Uses fuzzy matching via COLUMN_ALIASES.

    ``prefix`` can be used to scope alias lookups (e.g. "disk_", "nic_", "host_").
    """
    norm_headers = [_normalize_header(h) for h in sheet_headers]
    result: Dict[str, int] = {}

    # Columns allowed even when they don't start with the given prefix.
    # Grouped by the sheet where they appear.
    _ALWAYS_ALLOW = {
        # vInfo common columns
        "vm_name", "power_state", "template", "guest_os", "guest_os_tools",
        "folder_path", "resource_pool", "vapp_name", "annotation",
        "cpu_count", "ram_mb", "host_name", "cluster", "datacenter",
        "vm_uuid", "firmware", "change_tracking", "connection_state",
        "dns_name", "primary_ip", "provisioned_mb", "in_use_mb",
        "datastore",
        # vDisk columns (no disk_ prefix)
        "capacity_mb", "thin", "eagerly_scrub",
        # vNIC columns (no nic_ prefix)
        "adapter_type", "network_name", "mac_address", "ip_address",
    }

    for canonical, aliases in COLUMN_ALIASES.items():
        # Only use aliases relevant to the prefix scope
        if prefix and not canonical.startswith(prefix) and canonical not in _ALWAYS_ALLOW:
            continue

        for alias in aliases:
            norm_alias = _normalize_header(alias)
            for idx, norm_h in enumerate(norm_headers):
                if norm_h == norm_alias:
                    result[canonical] = idx
                    break
            if canonical in result:
                break

    return result


def extract_row(row_values: list, col_map: Dict[str, int]) -> Dict[str, Any]:
    """
    Extract a dict of canonical-name → cell-value from a single Excel row.
    """
    out: Dict[str, Any] = {}
    for canonical, idx in col_map.items():
        if idx < len(row_values):
            val = row_values[idx]
            # openpyxl may return None for empty cells
            out[canonical] = val if val is not None else ""
        else:
            out[canonical] = ""
    return out


# =====================================================================
# 2.  Tenant Detection
# =====================================================================

@dataclass
class TenantAssignment:
    tenant_name: str
    org_vdc: Optional[str] = None
    app_group: Optional[str] = None
    detection_method: str = "unassigned"


def detect_tenant_folder(vm: Dict[str, Any], depth: int = 2) -> Optional[str]:
    """
    Extract tenant from folder path.
    E.g. "/DatacenterX/vm/TenantA/Production" at depth=2 → "TenantA"
    """
    folder = str(vm.get("folder_path", "")).strip().strip("/")
    if not folder:
        return None
    parts = [p for p in folder.split("/") if p and p.lower() != "vm"]
    # Skip the datacenter (index 0), tenant is at depth-1
    target_idx = depth - 1
    if len(parts) > target_idx:
        return parts[target_idx]
    return None


def detect_tenant_resource_pool(vm: Dict[str, Any]) -> Optional[str]:
    """
    Extract the last meaningful segment from the resource pool path.
    E.g. '/Datacenter1/vCloud1_Pvdc1/Resources/OrgName_vDC_123 (uuid)' → 'OrgName_vDC_123'
    """
    rp = str(vm.get("resource_pool", "")).strip().strip("/")
    if not rp:
        return None
    parts = [p for p in rp.split("/") if p and p.lower() not in ("resources", "")]
    if parts:
        return _strip_uuid_suffix(parts[-1])
    return None


def detect_tenant_vapp(vm: Dict[str, Any]) -> Optional[str]:
    vapp = str(vm.get("vapp_name", "")).strip()
    return vapp if vapp else None


def _strip_uuid_suffix(segment: str) -> str:
    """Remove trailing UUID in parentheses from a folder segment.

    E.g.  'shaal_aviv (a1b3000a-80a6-42eb-a04d-393c54e009d2)' → 'shaal_aviv'
    """
    return re.sub(r"\s*\([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\)\s*$",
                  "", segment, flags=re.IGNORECASE).strip()


_VDC_PATTERN = re.compile(r"^(.+?)[-_]vdc[-_](\d+)", re.IGNORECASE)
_UUID_PARENS = re.compile(r"\s*\([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\)\s*$",
                          re.IGNORECASE)


def detect_tenant_vcd_folder(vm: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """
    Detect VMware Cloud Director Org + OrgVDC from folder structure
    and/or resource pool path.

    Typical folder paths:
      /Datacenter1/vCD-Node1/OrgName (uuid)/OrgName-VDC-NNNNNN (uuid)/…
    Typical resource pool paths:
      /Datacenter1/PvdcName/Resources/OrgName_vDC_NNNNNN (uuid)

    Strategy:
      1. Look for a path segment matching ``*[-_]VDC[-_]<number>``
         in folder_path, then in resource_pool.
         The text before the VDC separator is the Org (tenant) name.
      2. If no VDC segment is found, look for segments with UUID suffixes
         (a strong vCD indicator) and use the first as the Org name.

    Returns ``(org_name, org_vdc)`` if detected, else ``None``.
    """
    def _scan_parts_for_vdc(parts: List[str]) -> Optional[Tuple[str, str]]:
        """Look for a VDC-pattern segment in a list of path parts."""
        for part in parts:
            cleaned = _strip_uuid_suffix(part)
            m = _VDC_PATTERN.match(cleaned)
            if m:
                org_name = m.group(1).strip()
                org_vdc = cleaned  # e.g. "shaal_aviv-VDC-1326124"
                return (org_name, org_vdc)
        return None

    # ── Try folder_path first ──
    folder = str(vm.get("folder_path", "")).strip().strip("/")
    folder_parts = [p for p in folder.split("/") if p] if folder else []

    result = _scan_parts_for_vdc(folder_parts)
    if result:
        return result

    # ── Try resource_pool ──
    rp = str(vm.get("resource_pool", "")).strip().strip("/")
    rp_parts = [p for p in rp.split("/") if p and p.lower() != "resources"] if rp else []

    result = _scan_parts_for_vdc(rp_parts)
    if result:
        return result

    # ── Strategy 2: UUID-bearing segments (vCD managed) ──
    skip_lower = {"vm", "discovered virtual machine", "resources"}
    uuid_segments: List[str] = []
    for part in folder_parts:
        if _UUID_PARENS.search(part):
            cleaned = _UUID_PARENS.sub("", part).strip()
            if cleaned.lower() not in skip_lower:
                uuid_segments.append(cleaned)

    if len(uuid_segments) >= 2:
        return (uuid_segments[0], uuid_segments[1])
    if len(uuid_segments) == 1:
        return (uuid_segments[0], None)

    return None


def detect_tenant_vm_name(vm: Dict[str, Any], separator: str = "-", prefix_parts: int = 1) -> Optional[str]:
    name = str(vm.get("vm_name", "")).strip()
    if not name:
        return None
    parts = name.split(separator)
    if len(parts) > prefix_parts:
        return separator.join(parts[:prefix_parts])
    return None


def detect_tenant_annotation(vm: Dict[str, Any], field_name: str = "Tenant") -> Optional[str]:
    """
    If RVTools annotation contains a key=value pair for the tenant field.
    E.g. annotation="Tenant: Acme Corp; Env: Prod" → "Acme Corp"
    """
    ann = str(vm.get("annotation", "")).strip()
    if not ann:
        return None
    # Try key: value pattern
    pattern = re.compile(rf"{re.escape(field_name)}\s*[:=]\s*(.+?)(?:[;\n]|$)", re.IGNORECASE)
    m = pattern.search(ann)
    if m:
        return m.group(1).strip()
    return None


def detect_tenant_cluster(vm: Dict[str, Any]) -> Optional[str]:
    """
    Use the VM's ESXi cluster as the tenant name.
    Good fallback for non-vCD environments where clusters are organized per customer.
    """
    cluster = str(vm.get("cluster", "")).strip()
    if cluster and cluster.lower() not in ("", "none", "n/a"):
        return cluster
    return None


def assign_tenant(vm: Dict[str, Any], detection_config: Dict[str, Any]) -> TenantAssignment:
    """
    Apply tenant detection methods in priority order.
    Returns the first match.
    """
    methods = detection_config.get("methods", [])
    fallback = detection_config.get("fallback_tenant", "Unassigned")

    for method_cfg in methods:
        if not method_cfg.get("enabled", True):
            continue
        method = method_cfg.get("method", "")
        tenant = None

        if method == "folder_path":
            depth = method_cfg.get("depth", 2)
            tenant = detect_tenant_folder(vm, depth)
        elif method == "resource_pool":
            tenant = detect_tenant_resource_pool(vm)
        elif method == "vapp_name":
            tenant = detect_tenant_vapp(vm)
        elif method == "vcd_folder":
            # Cloud Director: detect Org from folder structure
            vcd_result = detect_tenant_vcd_folder(vm)
            if vcd_result:
                org_name, org_vdc_name = vcd_result
                app_group = detect_tenant_vapp(vm) or detect_tenant_vm_name(vm, "-", 2)
                return TenantAssignment(
                    tenant_name=org_name,
                    org_vdc=org_vdc_name,
                    app_group=app_group,
                    detection_method="vcd_folder",
                )
        elif method == "vm_name_prefix":
            sep = method_cfg.get("separator", "-")
            parts = method_cfg.get("prefix_parts", 1)
            tenant = detect_tenant_vm_name(vm, sep, parts)
        elif method == "annotation_field":
            fname = method_cfg.get("field_name", "Tenant")
            tenant = detect_tenant_annotation(vm, fname)
        elif method == "cluster":
            tenant = detect_tenant_cluster(vm)

        if tenant:
            # Determine app group (vApp if available, else name prefix)
            app_group = detect_tenant_vapp(vm) or detect_tenant_vm_name(vm, "-", 2)
            # Determine OrgVDC
            orgvdc_cfg = detection_config.get("orgvdc_detection", {})
            org_vdc = None
            if orgvdc_cfg.get("use_resource_pool"):
                org_vdc = detect_tenant_resource_pool(vm)
            if not org_vdc and orgvdc_cfg.get("use_folder_depth3"):
                org_vdc = detect_tenant_folder(vm, 3)

            return TenantAssignment(
                tenant_name=tenant,
                org_vdc=org_vdc,
                app_group=app_group,
                detection_method=method,
            )

    return TenantAssignment(tenant_name=fallback, detection_method="fallback")


def detect_tenants_batch(vms: List[Dict[str, Any]], detection_config: Dict[str, Any]) -> List[TenantAssignment]:
    """Assign tenants for a list of VMs."""
    return [assign_tenant(vm, detection_config) for vm in vms]


# =====================================================================
# 3.  OS Family Classification
# =====================================================================

def classify_os_family(guest_os: str, guest_os_tools: str = "") -> str:
    """Classify into windows | linux | other based on OS strings."""
    combined = f"{guest_os} {guest_os_tools}".lower()
    if any(w in combined for w in ("windows", "win32", "win64", "microsoft")):
        return "windows"
    if any(w in combined for w in (
        "linux", "ubuntu", "debian", "centos", "rhel", "red hat", "suse",
        "sles", "oracle linux", "amazon linux", "alma", "rocky", "fedora",
        "coreos", "photon", "arch",
    )):
        return "linux"
    return "other"


# =====================================================================
# 4.  Risk & Complexity Scoring
# =====================================================================

@dataclass
class RiskResult:
    score: float = 0.0
    category: str = "GREEN"   # GREEN | YELLOW | RED
    reasons: List[str] = field(default_factory=list)


def _match_any(value: str, patterns: List[str]) -> bool:
    """Case-insensitive substring match against a list of patterns."""
    val_lower = value.lower()
    return any(p.lower() in val_lower for p in patterns)


def compute_risk(vm: Dict[str, Any], rules: Dict[str, Any]) -> RiskResult:
    """
    Compute risk score for a single VM based on configurable rules.

    ``vm`` should have canonical keys (vm_name, guest_os, total_disk_gb,
    disk_count, snapshot_count, snapshot_oldest_days, nic_count, ram_mb, etc.).

    ``rules`` is the JSONB from migration_risk_config.rules.
    """
    score = 0.0
    reasons: List[str] = []
    weights = rules.get("risk_weights", {})

    os_str = f"{vm.get('guest_os', '')} {vm.get('guest_os_tools', '')}".strip()
    vm_name = str(vm.get("vm_name", ""))

    # --- OS support ---
    if _match_any(os_str, rules.get("os_unsupported", [])):
        w = weights.get("os_unsupported", 30)
        score += w
        reasons.append(f"Unsupported OS detected: {os_str} (+{w})")

    elif _match_any(os_str, rules.get("os_deprecated", [])):
        w = weights.get("os_deprecated", 15)
        score += w
        reasons.append(f"Deprecated OS detected: {os_str} (+{w})")

    # --- Cold-required OS ---
    if _match_any(os_str, rules.get("os_cold_required", [])):
        w = weights.get("cold_required_os", 20)
        score += w
        reasons.append(f"OS requires cold migration: {os_str} (+{w})")

    # --- Disk size ---
    total_disk_gb = float(vm.get("total_disk_gb", 0) or 0)
    very_large = rules.get("disk_very_large_threshold_gb", 5000)
    large = rules.get("disk_large_threshold_gb", 2000)
    if total_disk_gb >= very_large:
        w = weights.get("disk_very_large", 25)
        score += w
        reasons.append(f"Very large total disk: {total_disk_gb:.0f} GB (>= {very_large} GB) (+{w})")
    elif total_disk_gb >= large:
        w = weights.get("disk_large", 10)
        score += w
        reasons.append(f"Large total disk: {total_disk_gb:.0f} GB (>= {large} GB) (+{w})")

    # --- Disk count ---
    disk_count = int(vm.get("disk_count", 0) or 0)
    if disk_count >= rules.get("disk_count_high", 8):
        w = weights.get("disk_count_high", 10)
        score += w
        reasons.append(f"High disk count: {disk_count} (+{w})")

    # --- Snapshots ---
    snap_count = int(vm.get("snapshot_count", 0) or 0)
    snap_oldest = int(vm.get("snapshot_oldest_days", 0) or 0)
    if snap_count >= rules.get("snapshot_depth_critical", 5):
        w = weights.get("snapshot_critical", 20)
        score += w
        reasons.append(f"Critical snapshot depth: {snap_count} snapshots (+{w})")
    elif snap_count >= rules.get("snapshot_depth_warning", 3):
        w = weights.get("snapshot_warning", 8)
        score += w
        reasons.append(f"Multiple snapshots: {snap_count} (+{w})")

    if snap_oldest > rules.get("snapshot_age_warning_days", 30):
        w = weights.get("snapshot_old", 5)
        score += w
        reasons.append(f"Old snapshot: {snap_oldest} days (+{w})")

    # --- Multi-NIC ---
    nic_count = int(vm.get("nic_count", 0) or 0)
    if nic_count >= rules.get("multi_nic_threshold", 3):
        w = weights.get("multi_nic", 10)
        score += w
        reasons.append(f"Multi-NIC complexity: {nic_count} NICs (+{w})")

    # --- High I/O heuristic ---
    ram_mb = int(vm.get("ram_mb", 0) or 0)
    high_ram_gb = rules.get("high_ram_threshold_gb", 64)
    db_patterns = rules.get("db_name_patterns", [])
    is_high_io = False

    if ram_mb >= high_ram_gb * 1024:
        is_high_io = True
    if disk_count >= rules.get("high_disk_count_threshold", 6):
        is_high_io = True
    if _match_any(vm_name, db_patterns):
        is_high_io = True

    if is_high_io:
        w = weights.get("high_io_heuristic", 15)
        score += w
        io_hints = []
        if ram_mb >= high_ram_gb * 1024:
            io_hints.append(f"RAM {ram_mb}MB >= {high_ram_gb}GB")
        if disk_count >= rules.get("high_disk_count_threshold", 6):
            io_hints.append(f"{disk_count} disks")
        if _match_any(vm_name, db_patterns):
            io_hints.append("DB-like name pattern")
        reasons.append(f"High I/O workload heuristic: {', '.join(io_hints)} (+{w})")

    # --- Clamp to 0-100 ---
    score = min(100.0, max(0.0, score))

    # --- Category ---
    thresholds = rules.get("category_thresholds", {})
    green_max = thresholds.get("green_max", 20)
    yellow_max = thresholds.get("yellow_max", 50)

    if score <= green_max:
        category = "GREEN"
    elif score <= yellow_max:
        category = "YELLOW"
    else:
        category = "RED"

    return RiskResult(score=score, category=category, reasons=reasons)


# =====================================================================
# 5.  Warm / Cold Classification
# =====================================================================

@dataclass
class MigrationModeResult:
    mode: str = "warm_eligible"   # warm_eligible | warm_risky | cold_required
    reasons: List[str] = field(default_factory=list)


def classify_migration_mode(vm: Dict[str, Any], rules: Dict[str, Any]) -> MigrationModeResult:
    """
    Determine whether a VM can do warm (two-phase) migration.

    Returns cold_required if:
      - OS is in cold-required list
      - VM is powered off or suspended
      - CBT not enabled and OS doesn't support it

    Returns warm_risky if:
      - OS is in warm-risky list
      - Very large disk (long pre-copy)
      - High snapshot depth

    Otherwise warm_eligible.
    """
    reasons: List[str] = []
    os_str = f"{vm.get('guest_os', '')} {vm.get('guest_os_tools', '')}".strip()
    power = str(vm.get("power_state", "")).lower()

    # Cold required checks
    if _match_any(os_str, rules.get("os_cold_required", [])):
        reasons.append(f"OS requires cold migration: {os_str}")
        return MigrationModeResult(mode="cold_required", reasons=reasons)

    if power in ("poweredoff", "powered off", "suspended"):
        reasons.append(f"VM is {power} — cold migration only")
        return MigrationModeResult(mode="cold_required", reasons=reasons)

    # Check CBT
    cbt = vm.get("change_tracking")
    if isinstance(cbt, str):
        cbt = cbt.lower() in ("true", "yes", "1", "enabled")
    if cbt is False or cbt == "":
        reasons.append("CBT (Changed Block Tracking) not enabled — warm migration less efficient")

    # Warm risky checks
    risky = False
    if _match_any(os_str, rules.get("os_warm_risky", [])):
        reasons.append(f"OS has limited warm migration support: {os_str}")
        risky = True

    total_disk_gb = float(vm.get("total_disk_gb", 0) or 0)
    very_large = rules.get("disk_very_large_threshold_gb", 5000)
    if total_disk_gb >= very_large:
        reasons.append(f"Very large disk ({total_disk_gb:.0f} GB) — long pre-copy phase")
        risky = True

    snap_count = int(vm.get("snapshot_count", 0) or 0)
    if snap_count >= rules.get("snapshot_depth_critical", 5):
        reasons.append(f"Deep snapshot chain ({snap_count}) — consolidate before warm migration")
        risky = True

    if risky:
        return MigrationModeResult(mode="warm_risky", reasons=reasons)

    if not reasons:
        reasons.append("VM is eligible for warm (two-phase) migration")
    return MigrationModeResult(mode="warm_eligible", reasons=reasons)


# =====================================================================
# 6.  Bandwidth & Downtime Estimation (Phase 3 stubs with core logic)
# =====================================================================

@dataclass
class BandwidthModel:
    """Computed effective bandwidth for a migration project topology."""
    source_effective_mbps: float = 0.0
    link_effective_mbps: float = float("inf")   # inf = local, no link constraint
    agent_effective_mbps: float = 0.0
    storage_effective_mbps: float = 0.0
    bottleneck: str = ""
    bottleneck_mbps: float = 0.0


def compute_bandwidth_model(project_settings: Dict[str, Any]) -> BandwidthModel:
    """
    Compute the effective bandwidth constraints based on project topology settings.
    All speeds normalized to MB/s for migration calculations.
    
    project_settings should contain the topology fields from migration_projects.
    """
    def gbps_to_mbps(gbps: float) -> float:
        return gbps * 1000.0

    def apply_pct(mbps: float, pct: float) -> float:
        return mbps * (pct / 100.0)

    topology = project_settings.get("topology_type", "local")

    # Source host effective bandwidth
    src_nic = float(project_settings.get("source_nic_speed_gbps", 10))
    src_pct = float(project_settings.get("source_usable_pct", 40))
    source_eff = apply_pct(gbps_to_mbps(src_nic), src_pct)

    # Transport link
    link_eff = float("inf")
    if topology == "cross_site_dedicated":
        link_gbps = float(project_settings.get("link_speed_gbps", 1) or 1)
        link_pct = float(project_settings.get("link_usable_pct", 60))
        link_eff = apply_pct(gbps_to_mbps(link_gbps), link_pct)
    elif topology == "cross_site_internet":
        src_up = float(project_settings.get("source_upload_mbps", 100) or 100)
        dst_down = float(project_settings.get("dest_download_mbps", 100) or 100)
        raw_link = min(src_up, dst_down)
        link_pct = float(project_settings.get("link_usable_pct", 50))
        # Apply latency penalty
        rtt_cat = project_settings.get("rtt_category", "lt5")
        latency_penalty = {
            "lt5": 1.0,
            "5-20": 0.90,
            "20-50": 0.75,
            "50-100": 0.55,
            "gt100": 0.35,
        }.get(rtt_cat, 0.75)
        link_eff = apply_pct(raw_link, link_pct) * latency_penalty

    # Agent ingest bandwidth (total across all agents)
    agent_count = int(project_settings.get("agent_count", 2))
    agent_nic_gbps = float(project_settings.get("agent_nic_speed_gbps", 10))
    agent_pct = float(project_settings.get("agent_nic_usable_pct", 70))
    agent_eff = agent_count * apply_pct(gbps_to_mbps(agent_nic_gbps), agent_pct)

    # PCD storage write throughput
    # The user enters MB/s (megabytes per second); convert to Mbps for
    # consistent comparison with NIC speeds (which are already in Mbps).
    storage_mbs = float(project_settings.get("pcd_storage_write_mbps", 500) or 500)
    storage_eff = storage_mbs * 8.0  # 1 MB/s = 8 Mbps

    # Determine bottleneck
    constraints = {
        "source_host_nic": source_eff,
        "transport_link": link_eff,
        "agent_ingest": agent_eff,
        "pcd_storage": storage_eff,
    }
    bottleneck_name = min(constraints, key=constraints.get)  # type: ignore
    bottleneck_val = constraints[bottleneck_name]

    return BandwidthModel(
        source_effective_mbps=source_eff,
        link_effective_mbps=link_eff if link_eff != float("inf") else 0.0,
        agent_effective_mbps=agent_eff,
        storage_effective_mbps=storage_eff,
        bottleneck=bottleneck_name,
        bottleneck_mbps=bottleneck_val if bottleneck_val != float("inf") else 0.0,
    )


@dataclass
class AgentRecommendation:
    """Recommended vJailbreak agent sizing."""
    recommended_count: int = 2
    vcpu_per_agent: int = 10
    ram_gb_per_agent: float = 7.0
    disk_gb_per_agent: float = 500.0
    max_concurrent_vms: int = 10
    reasoning: List[str] = field(default_factory=list)


def recommend_agent_sizing(
    vm_count: int,
    largest_disk_gb: float,
    top5_disk_sizes_gb: List[float],
    project_settings: Dict[str, Any],
    total_disk_gb: float = 0.0,
) -> AgentRecommendation:
    """
    Recommend vJailbreak agent count and sizing based on workload profile
    AND the project migration schedule.
    """
    concurrent_per_agent = int(project_settings.get("agent_concurrent_vms", 5))
    vcpu_per_slot = int(project_settings.get("agent_vcpu_per_slot", 2))
    ram_base = float(project_settings.get("agent_ram_base_gb", 2))
    ram_per_slot = float(project_settings.get("agent_ram_per_slot_gb", 1))
    buffer_factor = float(project_settings.get("agent_disk_buffer_factor", 1.2))

    # Migration schedule
    duration_days = int(project_settings.get("migration_duration_days", 0) or 0)
    working_hours = float(project_settings.get("working_hours_per_day", 8) or 8)
    working_days_week = int(project_settings.get("working_days_per_week", 5) or 5)
    target_vms_day = int(project_settings.get("target_vms_per_day", 0) or 0)

    # ------ Derive recommended agent count from schedule ------
    reasoning: List[str] = []

    if target_vms_day > 0:
        # User specified target VMs/day → derive agents needed
        # Each agent can handle concurrent_per_agent VMs at a time.
        # Assume average VM takes ~2 hours (will be refined in Phase 3).
        slots_per_day = working_hours / 2.0  # cycles per day per slot
        vms_per_agent_per_day = concurrent_per_agent * slots_per_day
        recommended = max(2, int((target_vms_day + vms_per_agent_per_day - 1) / vms_per_agent_per_day))
        reasoning.append(f"Target: {target_vms_day} VMs/day → ~{vms_per_agent_per_day:.0f} VMs/agent/day → {recommended} agents")

    elif duration_days > 0:
        # User specified project duration → derive agents needed
        # Compute effective working days
        total_weeks = duration_days / 7.0
        effective_days = total_weeks * working_days_week
        if effective_days < 1:
            effective_days = 1
        vms_per_day_needed = vm_count / effective_days
        # Each agent handles concurrent_per_agent VMs at a time;
        # assume average ~2h per VM cycle within working_hours
        slots_per_day = working_hours / 2.0
        vms_per_agent_per_day = concurrent_per_agent * slots_per_day
        recommended = max(2, int((vms_per_day_needed + vms_per_agent_per_day - 1) / vms_per_agent_per_day))
        reasoning.append(
            f"{vm_count} VMs in {duration_days} days "
            f"({working_days_week}d/wk × {working_hours}h/d = {effective_days:.0f} effective days)"
        )
        reasoning.append(f"Need {vms_per_day_needed:.1f} VMs/day → {recommended} agents")
    else:
        # Fallback: heuristic based on VM count
        recommended = max(2, (vm_count + concurrent_per_agent * 4 - 1) // (concurrent_per_agent * 4))
        reasoning.append(f"{vm_count} VMs total, {concurrent_per_agent} concurrent per agent")

    # Per-agent sizing
    vcpu = vcpu_per_slot * concurrent_per_agent
    ram = ram_base + ram_per_slot * concurrent_per_agent

    # Disk: enough for concurrent largest disks + buffer
    if top5_disk_sizes_gb:
        concurrent_disk = sum(sorted(top5_disk_sizes_gb, reverse=True)[:concurrent_per_agent])
    else:
        concurrent_disk = largest_disk_gb * concurrent_per_agent
    disk = concurrent_disk * buffer_factor

    reasoning.append(f"Recommended {recommended} agents = {recommended * concurrent_per_agent} concurrent slots")
    reasoning.append(f"Per agent: {vcpu} vCPU, {ram:.0f} GB RAM, {disk:.0f} GB disk")

    if duration_days > 0:
        effective_days = (duration_days / 7.0) * working_days_week
        slots_per_day = working_hours / 2.0
        daily_capacity = recommended * concurrent_per_agent * slots_per_day
        est_days = vm_count / daily_capacity if daily_capacity > 0 else 999
        reasoning.append(
            f"Estimated completion: ~{est_days:.0f} working days "
            f"({daily_capacity:.0f} VMs/day capacity)"
        )

    return AgentRecommendation(
        recommended_count=recommended,
        vcpu_per_agent=vcpu,
        ram_gb_per_agent=ram,
        disk_gb_per_agent=disk,
        max_concurrent_vms=recommended * concurrent_per_agent,
        reasoning=reasoning,
    )


# =====================================================================
# 7.  Per-VM Migration Time Estimation
# =====================================================================

@dataclass
class VMTimeEstimate:
    """Estimated migration timing for a single VM."""
    total_disk_gb: float = 0.0
    in_use_gb: float = 0.0
    effective_mbps: float = 0.0
    # Warm migration (two-phase)
    warm_phase1_hours: float = 0.0        # Initial full copy (runs while VM is up)
    warm_incremental_hours: float = 0.0   # Daily change sync (runs while VM is up)
    warm_cutover_hours: float = 0.0       # Final delta + switchover (downtime)
    warm_total_hours: float = 0.0
    warm_downtime_hours: float = 0.0
    # Cold migration
    cold_total_hours: float = 0.0         # Full offline copy
    cold_downtime_hours: float = 0.0      # = cold_total_hours (everything offline)
    mode: str = "warm_eligible"


def estimate_vm_time(
    vm: Dict[str, Any],
    bottleneck_mbps: float,
    daily_change_rate_pct: float = 5.0,
) -> VMTimeEstimate:
    """
    Estimate migration time for a single VM.

    Warm migration (vJailbreak two-phase):
      Phase 1: Full copy of in_use data at effective bandwidth (VM stays up)
      Incremental: Daily delta sync = in_use × daily_change_rate (VM stays up)
      Cutover: Final delta + switchover.  Downtime = cutover time only.

    Cold migration:
      Full copy of total provisioned data while VM is off.  Downtime = total copy time.
    """
    total_disk_gb = float(vm.get("total_disk_gb", 0) or 0)
    in_use_gb = float(vm.get("in_use_mb", 0) or 0) / 1024
    if in_use_gb <= 0:
        in_use_gb = total_disk_gb  # Fallback if no in_use data

    # Effective bandwidth: Mbps → GB/h
    # bottleneck_mbps is in Megabits/s.  1 Mbps = 0.000125 GB/s = 0.45 GB/h
    if bottleneck_mbps <= 0:
        bottleneck_mbps = 1000  # Fallback 1 Gbps

    gb_per_hour = (bottleneck_mbps / 8) * 3.6  # Mbps → MB/s → GB/h

    mode = str(vm.get("migration_mode", "warm_eligible") or "warm_eligible")

    # ── Warm migration ──
    warm_phase1 = in_use_gb / gb_per_hour if gb_per_hour > 0 else 0
    daily_delta_gb = in_use_gb * (daily_change_rate_pct / 100)
    warm_incremental = daily_delta_gb / gb_per_hour if gb_per_hour > 0 else 0
    # Cutover: last delta (~half-day of changes) + 15 min switchover
    cutover_delta_gb = daily_delta_gb * 0.5
    warm_cutover = (cutover_delta_gb / gb_per_hour + 0.25) if gb_per_hour > 0 else 0.25

    # ── Cold migration ──
    cold_total = total_disk_gb / gb_per_hour if gb_per_hour > 0 else 0

    return VMTimeEstimate(
        total_disk_gb=total_disk_gb,
        in_use_gb=round(in_use_gb, 2),
        effective_mbps=bottleneck_mbps,
        warm_phase1_hours=round(warm_phase1, 2),
        warm_incremental_hours=round(warm_incremental, 2),
        warm_cutover_hours=round(warm_cutover, 2),
        warm_total_hours=round(warm_phase1 + warm_cutover, 2),
        warm_downtime_hours=round(warm_cutover, 2),
        cold_total_hours=round(cold_total, 2),
        cold_downtime_hours=round(cold_total, 2),
        mode=mode,
    )


def generate_migration_plan(
    vms: List[Dict[str, Any]],
    tenants: List[Dict[str, Any]],
    project_settings: Dict[str, Any],
    bottleneck_mbps: float,
) -> Dict[str, Any]:
    """
    Generate a comprehensive migration plan document structure.

    Returns a dict containing:
      - project_summary: Overall project metrics
      - tenant_plans: Per-tenant breakdown with VM lists, daily schedule,
                      warm/cold counts, estimated times
      - daily_schedule: Day-by-day migration schedule across all tenants
    """
    daily_change_rate = float(project_settings.get("daily_change_rate_pct", 5) or 5)
    duration_days = int(project_settings.get("migration_duration_days", 30) or 30)
    working_hours = float(project_settings.get("working_hours_per_day", 8) or 8)
    working_days_week = int(project_settings.get("working_days_per_week", 5) or 5)
    agent_count = int(project_settings.get("agent_count", 2) or 2)
    concurrent_per_agent = int(project_settings.get("agent_concurrent_vms", 5) or 5)

    total_concurrent = agent_count * concurrent_per_agent
    total_weeks = duration_days / 7.0
    effective_days = max(1, total_weeks * working_days_week)

    # Estimate time for each VM
    vm_estimates = []
    for vm in vms:
        if vm.get("exclude_from_migration"):
            continue
        est = estimate_vm_time(vm, bottleneck_mbps, daily_change_rate)
        vm_estimates.append({**vm, "_estimate": est})

    # Sort by tenant, then priority, then disk size descending
    vm_estimates.sort(key=lambda v: (
        v.get("tenant_name") or "zzz",
        v.get("priority", 50),
        -(float(v.get("total_disk_gb", 0) or 0)),
    ))

    # Build per-tenant plans
    tenant_map: Dict[str, Dict[str, Any]] = {}
    for t in tenants:
        tname = t.get("tenant_name", "Unassigned")
        tenant_map[tname] = {
            "tenant_name": tname,
            "org_vdc": t.get("org_vdc"),
            "vm_count": 0,
            "total_disk_gb": 0.0,
            "total_in_use_gb": 0.0,
            "warm_count": 0,
            "cold_count": 0,
            "warm_risky_count": 0,
            "total_warm_phase1_hours": 0.0,
            "total_warm_cutover_hours": 0.0,
            "total_cold_hours": 0.0,
            "total_downtime_hours": 0.0,
            "risk_distribution": {"GREEN": 0, "YELLOW": 0, "RED": 0},
            "vms": [],
        }

    for v in vm_estimates:
        tname = v.get("tenant_name") or "Unassigned"
        if tname not in tenant_map:
            tenant_map[tname] = {
                "tenant_name": tname,
                "org_vdc": v.get("org_vdc"),
                "vm_count": 0,
                "total_disk_gb": 0.0,
                "total_in_use_gb": 0.0,
                "warm_count": 0,
                "cold_count": 0,
                "warm_risky_count": 0,
                "total_warm_phase1_hours": 0.0,
                "total_warm_cutover_hours": 0.0,
                "total_cold_hours": 0.0,
                "total_downtime_hours": 0.0,
                "risk_distribution": {"GREEN": 0, "YELLOW": 0, "RED": 0},
                "vms": [],
            }
        tp = tenant_map[tname]
        est = v["_estimate"]
        mode = est.mode

        tp["vm_count"] += 1
        tp["total_disk_gb"] += est.total_disk_gb
        tp["total_in_use_gb"] += est.in_use_gb

        if "cold" in mode:
            tp["cold_count"] += 1
            tp["total_cold_hours"] += est.cold_total_hours
            tp["total_downtime_hours"] += est.cold_downtime_hours
            effective_hours = est.cold_total_hours
        else:
            if "risky" in mode:
                tp["warm_risky_count"] += 1
            else:
                tp["warm_count"] += 1
            tp["total_warm_phase1_hours"] += est.warm_phase1_hours
            tp["total_warm_cutover_hours"] += est.warm_cutover_hours
            tp["total_downtime_hours"] += est.warm_cutover_hours
            effective_hours = est.warm_total_hours

        risk_cat = v.get("risk_category", "GREEN") or "GREEN"
        if risk_cat in tp["risk_distribution"]:
            tp["risk_distribution"][risk_cat] += 1

        tp["vms"].append({
            "vm_name": v.get("vm_name"),
            "cpu_count": v.get("cpu_count"),
            "ram_mb": v.get("ram_mb"),
            "total_disk_gb": round(est.total_disk_gb, 2),
            "in_use_gb": round(est.in_use_gb, 2),
            "os_family": v.get("os_family"),
            "power_state": v.get("power_state"),
            "migration_mode": mode,
            "risk_category": risk_cat,
            "risk_score": v.get("risk_score"),
            "disk_count": v.get("disk_count", 0),
            "nic_count": v.get("nic_count", 0),
            "primary_ip": v.get("primary_ip"),
            "warm_phase1_hours": est.warm_phase1_hours,
            "warm_cutover_hours": est.warm_cutover_hours,
            "warm_downtime_hours": est.warm_downtime_hours,
            "cold_total_hours": est.cold_total_hours,
            "cold_downtime_hours": est.cold_downtime_hours,
            "effective_hours": round(effective_hours, 2),
        })

    # Build daily schedule
    remaining_vms = list(vm_estimates)  # all VMs to schedule
    daily_schedule: List[Dict[str, Any]] = []
    day_number = 0
    vm_idx = 0

    while vm_idx < len(remaining_vms) and day_number < effective_days:
        day_number += 1
        # How many VMs can we process today?
        # Estimate: each VM slot takes effective_hours/working_hours of a day
        day_vms: List[Dict[str, Any]] = []
        day_hours_used = 0.0

        while vm_idx < len(remaining_vms) and len(day_vms) < total_concurrent:
            v = remaining_vms[vm_idx]
            est = v["_estimate"]
            eff_h = est.warm_total_hours if "cold" not in est.mode else est.cold_total_hours
            if day_hours_used + eff_h > working_hours * total_concurrent and day_vms:
                break
            day_vms.append({
                "vm_name": v.get("vm_name"),
                "tenant_name": v.get("tenant_name"),
                "mode": est.mode,
                "disk_gb": round(est.total_disk_gb, 2),
                "estimated_hours": round(eff_h, 2),
            })
            day_hours_used += eff_h
            vm_idx += 1

        daily_schedule.append({
            "day": day_number,
            "vm_count": len(day_vms),
            "vms": day_vms,
            "total_estimated_hours": round(day_hours_used, 2),
        })

    # Totals
    total_vms = len(vm_estimates)
    total_disk = sum(v["_estimate"].total_disk_gb for v in vm_estimates)
    total_warm = sum(1 for v in vm_estimates if "cold" not in v["_estimate"].mode)
    total_cold = sum(1 for v in vm_estimates if "cold" in v["_estimate"].mode)
    total_downtime_h = sum(
        v["_estimate"].warm_cutover_hours if "cold" not in v["_estimate"].mode
        else v["_estimate"].cold_downtime_hours
        for v in vm_estimates
    )

    # Round tenant floats
    for tp in tenant_map.values():
        for k in (
            "total_disk_gb", "total_in_use_gb",
            "total_warm_phase1_hours", "total_warm_cutover_hours",
            "total_cold_hours", "total_downtime_hours",
        ):
            tp[k] = round(tp[k], 2)

    return {
        "project_summary": {
            "total_vms": total_vms,
            "total_disk_tb": round(total_disk / 1024, 2),
            "warm_eligible": total_warm,
            "cold_required": total_cold,
            "total_tenants": len(tenant_map),
            "project_duration_days": duration_days,
            "effective_working_days": round(effective_days, 1),
            "agent_count": agent_count,
            "total_concurrent_slots": total_concurrent,
            "bottleneck_mbps": round(bottleneck_mbps, 1),
            "estimated_schedule_days": day_number,
            "total_downtime_hours": round(total_downtime_h, 2),
        },
        "tenant_plans": sorted(tenant_map.values(), key=lambda t: -(t["vm_count"])),
        "daily_schedule": daily_schedule,
    }

def summarize_rvtools_stats(
    vinfo_count: int,
    vdisk_count: int,
    vnic_count: int,
    vhost_count: int,
    vcluster_count: int,
    vsnapshot_count: int,
    power_state_counts: Optional[Dict[str, int]] = None,
    os_family_counts: Optional[Dict[str, int]] = None,
    tenant_count: int = 0,
    vcd_detected: bool = False,
    template_count: int = 0,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "vInfo": vinfo_count,
        "vDisk": vdisk_count,
        "vNIC": vnic_count,
        "vHost": vhost_count,
        "vCluster": vcluster_count,
        "vSnapshot": vsnapshot_count,
    }
    if power_state_counts:
        result["power_states"] = power_state_counts
    if os_family_counts:
        result["os_families"] = os_family_counts
    if tenant_count:
        result["tenants"] = tenant_count
    if vcd_detected:
        result["vcd_detected"] = True
    if template_count:
        result["templates"] = template_count
    return result
