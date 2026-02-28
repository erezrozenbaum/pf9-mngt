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
import math
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

    # --- vPartition sheet ---
    "part_vm_name":     ["VM", "Name", "VM Name"],
    "part_disk":        ["Disk", "Disk#", "Disk Number"],
    "part_partition":   ["Partition", "Partition#"],
    "part_capacity_mb": ["Capacity MB", "Capacity MiB", "Capacity (MB)", "Size MB"],
    "part_consumed_mb": ["Consumed MB", "Consumed MiB", "Consumed (MB)", "Free MB"],
    "part_free_space_mb": ["Free Space MB", "Free Space", "Free MB", "Free (MB)"],
    "part_free_pct":    ["Free %", "Free%", "% Free"],

    # --- vCPU sheet ---
    "cpu_vm_name":      ["VM", "Name", "VM Name"],
    "cpu_usage_percent": ["Usage %", "CPU Usage %", "CPU Usage", "Usage", "% Usage"],
    "cpu_usage":        ["Usage %", "CPU Usage %", "CPU Usage", "Usage", "% Usage"],
    "cpu_demand_mhz":   ["Demand MHz", "CPU Demand MHz", "Demand (MHz)", "CPU Demand"],
    "demand_mhz":       ["Demand MHz", "CPU Demand MHz", "Demand (MHz)", "CPU Demand"],

    # --- vMemory sheet ---
    "mem_vm_name":      ["VM", "Name", "VM Name"],
    "mem_usage_percent": ["Usage %", "Memory Usage %", "Mem Usage %", "Memory Usage", "Usage"],
    "memory_usage":     ["Usage %", "Memory Usage %", "Mem Usage %", "Memory Usage", "Usage"],
    "usage_percent":    ["Usage %", "Memory Usage %", "Mem Usage %", "Memory Usage", "Usage"],
    "mem_usage_mb":     ["Usage MB", "Memory Usage MB", "Mem Usage MB", "Usage (MB)"],
    "memory_usage_mb":  ["Usage MB", "Memory Usage MB", "Mem Usage MB", "Usage (MB)"],
    "usage_mb":         ["Usage MB", "Memory Usage MB", "Mem Usage MB", "Usage (MB)"],

    # --- vNetwork sheet ---
    "net_vm_name":      ["VM", "Name", "VM Name"],
    "net_network_name": ["Network", "Network Name", "Portgroup", "Port Group"],
    "net_vlan_id":      ["VLAN", "VLAN ID", "Vlan", "VLAN#"],
    "net_subnet":       ["Subnet", "IP Subnet", "Network Address"],
    "net_gateway":      ["Gateway", "Default Gateway", "Gateway IP"],
    "net_dns_servers":  ["DNS", "DNS Servers", "Name Servers"],
    "net_ip_range":     ["IP Range", "Address Range", "DHCP Range"],
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
        # vPartition columns (no part_ prefix)
        "part_capacity_mb", "part_consumed_mb", "part_free_space_mb", "part_free_pct",
        # vCPU columns (alternative names without cpu_ prefix)
        "cpu_usage", "demand_mhz",
        # vMemory columns (alternative names without mem_ prefix)
        "memory_usage", "usage_percent", "memory_usage_mb", "usage_mb",
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


def extract_os_version(guest_os: str, guest_os_tools: str = "") -> str:
    """
    Return the best available OS version string for display.

    Prefers VMware Tools OS detection (more accurate) over config-based.
    Falls back to config-based if tools string is empty.
    Returns empty string if both are empty.

    Examples:
      - "Microsoft Windows Server 2019 (64-bit)"
      - "Red Hat Enterprise Linux 8 (64-bit)"
      - "Ubuntu Linux (64-bit)"
    """
    # VMware Tools provides the most accurate OS identification
    tools = (guest_os_tools or "").strip()
    config = (guest_os or "").strip()

    if tools and tools.lower() not in ("", "unknown", "other", "other (32-bit)", "other (64-bit)"):
        return tools
    if config and config.lower() not in ("", "unknown"):
        return config
    return ""


# =====================================================================
# 3b.  Network Classification Helpers
# =====================================================================

import re as _re

_VLAN_PATTERN = _re.compile(r'[_\-\s]?vlan[_\-\s]?(\d+)', _re.IGNORECASE)
_NSXT_PATTERNS = [
    "nsx-t", "nsxt", "nsx_t", "overlay", "geneve", "segment",
    "t0-", "t1-", "tier-0", "tier-1", "ls-",
]
_ISOLATED_PATTERNS = ["isolated", "internal-only", "no-uplink", "air-gap"]


def extract_vlan_id(network_name: str) -> Optional[int]:
    """Extract VLAN ID from a network/portgroup name like 'Tenant_vlan_3567'."""
    m = _VLAN_PATTERN.search(network_name or "")
    return int(m.group(1)) if m else None


def classify_network_type(network_name: str) -> str:
    """
    Classify a network based on naming conventions:
      - 'vlan_based'  — external VLAN-backed portgroup
      - 'nsx_t'       — NSX-T overlay segment (not supported on PCD)
      - 'isolated'    — isolated / internal-only network
      - 'standard'    — standard vSwitch / unclassified
    """
    name_lower = (network_name or "").lower()
    if any(p in name_lower for p in _NSXT_PATTERNS):
        return "nsx_t"
    if any(p in name_lower for p in _ISOLATED_PATTERNS):
        return "isolated"
    if _VLAN_PATTERN.search(name_lower):
        return "vlan_based"
    return "standard"

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
    # Prefer in_use_gb (from vPartition, most accurate), fallback to in_use_mb/1024 (vInfo)
    in_use_gb = float(vm.get("in_use_gb", 0) or 0)
    if in_use_gb <= 0:
        in_use_gb = float(vm.get("in_use_mb", 0) or 0) / 1024
    if in_use_gb <= 0:
        in_use_gb = total_disk_gb  # Fallback if no in_use data

    # Effective bandwidth: Mbps → GB/h (with real-world factors)
    # bottleneck_mbps is in Megabits/s
    # Conversion: Mbps / 8 = MB/s, then MB/s * 3600/1024 = GB/h
    if bottleneck_mbps <= 0:
        bottleneck_mbps = 1000  # Fallback 1 Gbps

    # Raw theoretical throughput
    raw_gb_per_hour = (bottleneck_mbps / 8) * 3600 / 1024  # Correct conversion

    # Real-world factors: compression, deduplication, incremental efficiency
    # Based on user feedback: 50GB in 20min, 1TB in 80min with 1Gbps source
    # This suggests effective transfer is 5-10% of raw VM size due to:
    # - VMware compression and deduplication
    # - Warm migration pre-sync (95% data already transferred)
    # - Change block tracking efficiency
    compression_and_incremental_factor = 0.05  # 5% of raw data transferred in practice
    gb_per_hour = raw_gb_per_hour  # Keep raw for cold migration calculations

    mode = str(vm.get("migration_mode", "warm_eligible") or "warm_eligible")

    # ── Warm migration ──
    # Phase 1: Full live pre-copy of all in_use blocks while VM is running.
    # The entire in_use_gb must be transferred; no data-size reduction.
    # Real-world bandwidth utilization: 45-65% of raw due to random I/O,
    # protocol overhead, VMware CBT scanning, and storage write latency.
    bw_efficiency = 0.65 if in_use_gb > 1000 else 0.55 if in_use_gb > 100 else 0.45
    effective_gb_per_hour = raw_gb_per_hour * bw_efficiency
    copy_hours = in_use_gb / effective_gb_per_hour if effective_gb_per_hour > 0 else 0
    
    # Cutover overhead (vJailbreak + driver + rebuild + restarts)
    # Based on user experience: minimum 20-25 minutes regardless of size
    if in_use_gb <= 50:
        cutover_overhead_hours = 0.3  # 18 min
    elif in_use_gb <= 200:
        cutover_overhead_hours = 0.37 # 22 min  
    elif in_use_gb <= 1000:
        cutover_overhead_hours = 0.47 # 28 min
    else:
        cutover_overhead_hours = 0.58 # 35 min
    
    warm_phase1 = copy_hours
    daily_delta_gb = in_use_gb * (daily_change_rate_pct / 100)
    warm_incremental = daily_delta_gb / effective_gb_per_hour if effective_gb_per_hour > 0 else 0
    warm_cutover = cutover_overhead_hours

    # ── Cold migration ──
    # Must transfer full provisioned disk at raw bandwidth.
    # Entire copy is offline. After copy, same boot/connect cutover applies.
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
        cold_downtime_hours=round(cold_total + warm_cutover, 2),
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

    # Build cohort metadata lookup from tenants list
    tenant_cohort: Dict[str, Any] = {}
    for t in tenants:
        tenant_cohort[t.get("tenant_name", "")] = {
            "cohort_name":  t.get("cohort_name"),
            "cohort_order": t.get("cohort_order"),
        }

    # Sort by cohort_order first (uncohorted last), then tenant, priority, disk size desc
    vm_estimates.sort(key=lambda v: (
        tenant_cohort.get(v.get("tenant_name", ""), {}).get("cohort_order") or 9999,
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
            "cohort_name":  t.get("cohort_name"),
            "cohort_order": t.get("cohort_order"),
            "vm_count": 0,
            "total_vcpu": 0,
            "total_ram_mb": 0,
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
                "cohort_name":  tenant_cohort.get(tname, {}).get("cohort_name"),
                "cohort_order": tenant_cohort.get(tname, {}).get("cohort_order"),
                "vm_count": 0,
                "total_vcpu": 0,
                "total_ram_mb": 0,
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
        tp["total_vcpu"] += int(v.get("cpu_count") or 0)
        tp["total_ram_mb"] += int(v.get("ram_mb") or 0)
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
            "os_version": v.get("os_version", ""),
            "power_state": v.get("power_state"),
            "migration_mode": mode,
            "risk_category": risk_cat,
            "risk_score": v.get("risk_score"),
            "disk_count": v.get("disk_count", 0),
            "nic_count": v.get("nic_count", 0),
            "network_name": v.get("network_name", ""),
            "primary_ip": v.get("primary_ip"),
            "warm_phase1_hours": est.warm_phase1_hours,
            "warm_cutover_hours": est.warm_cutover_hours,
            "warm_downtime_hours": est.warm_downtime_hours,
            "cold_total_hours": est.cold_total_hours,
            "cold_downtime_hours": est.cold_downtime_hours,
            "effective_hours": round(effective_hours, 2),
        })

    # Build daily schedule — process cohorts sequentially, each cohort starts on a fresh day
    # Group VMs by cohort (already sorted by cohort_order → tenant → priority → disk)
    from itertools import groupby as _groupby

    def _vm_cohort_key(v: Dict) -> tuple:
        tc = tenant_cohort.get(v.get("tenant_name", ""), {})
        return (tc.get("cohort_order") or 9999, tc.get("cohort_name") or "Uncohorted")

    daily_schedule: List[Dict[str, Any]] = []
    cohort_schedule_summary: List[Dict[str, Any]] = []
    day_number = 0

    for (cohort_order, cohort_name), cohort_vms_iter in _groupby(vm_estimates, key=_vm_cohort_key):
        cohort_vms = list(cohort_vms_iter)
        cohort_start_day = day_number + 1
        vm_idx = 0

        while vm_idx < len(cohort_vms):
            day_number += 1
            day_vms: List[Dict[str, Any]] = []
            day_hours_used = 0.0

            while vm_idx < len(cohort_vms) and len(day_vms) < total_concurrent:
                v = cohort_vms[vm_idx]
                est = v["_estimate"]
                eff_h = est.warm_total_hours if "cold" not in est.mode else est.cold_total_hours
                if day_hours_used + eff_h > working_hours * total_concurrent and day_vms:
                    break
                day_vms.append({
                    "vm_name": v.get("vm_name"),
                    "tenant_name": v.get("tenant_name"),
                    "cohort_name": cohort_name,
                    "cohort_order": cohort_order if cohort_order != 9999 else None,
                    "mode": est.mode,
                    "disk_gb": round(est.total_disk_gb, 2),
                    "estimated_hours": round(eff_h, 2),
                })
                day_hours_used += eff_h
                vm_idx += 1

            daily_schedule.append({
                "day": day_number,
                "cohort_name": cohort_name,
                "cohort_order": cohort_order if cohort_order != 9999 else None,
                "cohorts": [cohort_name],
                "vm_count": len(day_vms),
                "vms": day_vms,
                "total_estimated_hours": round(day_hours_used, 2),
            })

        cohort_schedule_summary.append({
            "cohort_order": cohort_order if cohort_order != 9999 else None,
            "cohort_name": cohort_name,
            "start_day": cohort_start_day,
            "end_day": day_number,
            "duration_days": day_number - cohort_start_day + 1,
            "vm_count": len(cohort_vms),
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
        # Sort tenant plans by cohort_order (uncohorted last), then vm_count desc
        "tenant_plans": sorted(
            tenant_map.values(),
            key=lambda t: (
                t.get("cohort_order") or 9999,
                -(t["vm_count"]),
            ),
        ),
        "daily_schedule": daily_schedule,
        "cohort_schedule_summary": cohort_schedule_summary,
    }

def summarize_rvtools_stats(
    vinfo_count: int,
    vdisk_count: int,
    vnic_count: int,
    vhost_count: int,
    vcluster_count: int,
    vsnapshot_count: int,
    vpartition_count: int = 0,
    vcpu_count: int = 0,
    vmemory_count: int = 0,
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
        "vPartition": vpartition_count,
    }
    if vcpu_count:
        result["vCPU"] = vcpu_count
    if vmemory_count:
        result["vMemory"] = vmemory_count
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


# =====================================================================
# Phase 2C — Quota & Overcommit Modeling
# =====================================================================

OVERCOMMIT_PRESETS: Dict[str, Dict[str, float]] = {
    "aggressive":   {"cpu_ratio": 8.0, "ram_ratio": 2.0, "disk_snapshot_factor": 1.3},
    "balanced":     {"cpu_ratio": 4.0, "ram_ratio": 1.5, "disk_snapshot_factor": 1.5},
    "conservative": {"cpu_ratio": 2.0, "ram_ratio": 1.0, "disk_snapshot_factor": 2.0},
}


def compute_quota_requirements(
    tenants: List[Dict[str, Any]],
    overcommit_profile: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Per-tenant and aggregate quota requirements using an overcommit profile.

    Args:
        tenants:            List of migration_tenants rows (from DB). Only rows where
                            include_in_plan == True are processed.
        overcommit_profile: Dict with cpu_ratio, ram_ratio, disk_snapshot_factor.

    Returns:
        {
          "profile": {...},
          "totals_allocated": {vcpu, ram_gb, disk_tb},
          "totals_recommended": {vcpu, ram_gb, disk_tb},
          "per_tenant": [{tenant_name, vcpu_alloc, ram_gb_alloc, disk_gb_alloc,
                          vcpu_recommended, ram_gb_recommended, disk_gb_recommended,
                          overcommit_warnings: [...]}, ...]
        }
    """
    cpu_ratio  = float(overcommit_profile.get("cpu_ratio", 4.0))
    ram_ratio  = float(overcommit_profile.get("ram_ratio", 1.5))
    disk_factor = float(overcommit_profile.get("disk_snapshot_factor", 1.5))

    per_tenant = []
    total_vcpu_alloc = total_ram_gb_alloc = total_disk_gb_alloc = 0.0
    total_vcpu_rec   = total_ram_gb_rec   = total_disk_gb_rec   = 0.0
    total_ram_gb_used = 0.0

    for t in tenants:
        if not t.get("include_in_plan", True):
            continue

        vcpu      = int(t.get("total_vcpu", 0) or 0)
        ram_mb    = int(t.get("total_ram_mb", 0) or 0)
        disk_gb   = float(t.get("total_disk_gb", 0) or 0)
        in_use_gb = float(t.get("total_in_use_gb", 0) or 0)

        ram_gb = ram_mb / 1024.0

        # Recommended = allocated ÷ overcommit ratio (what PCD quota to set)
        vcpu_rec   = max(1, round(vcpu / cpu_ratio))
        ram_gb_rec = round(ram_gb / ram_ratio, 1)
        disk_gb_rec = round(disk_gb * disk_factor, 1)

        warnings: List[str] = []
        if cpu_ratio >= 6.0 and vcpu > 200:
            warnings.append(f"High CPU density ({cpu_ratio}:1) with {vcpu} vCPUs — monitor for contention")
        if ram_ratio >= 1.8:
            warnings.append(f"RAM overcommit {ram_ratio}:1 — ensure workloads are not memory-intensive")
        if disk_gb_rec > 50_000:
            warnings.append(f"Recommended disk quota {disk_gb_rec/1024:.1f} TB — verify PCD storage capacity")

        ram_used_gb = round(float(t.get("ram_used_gb", 0) or 0), 1)

        per_tenant.append({
            "tenant_name":           t.get("tenant_name", ""),
            "target_domain_name":    t.get("target_domain_name") or t.get("target_domain") or "",
            "target_project_name":   t.get("target_project_name") or t.get("target_project") or "",
            "vcpu_alloc":            vcpu,
            "ram_gb_alloc":          round(ram_gb, 1),
            "ram_used_gb":           ram_used_gb,
            "disk_gb_alloc":         round(disk_gb, 1),
            "in_use_gb":             round(in_use_gb, 1),
            "vcpu_recommended":      vcpu_rec,
            "ram_gb_recommended":    ram_gb_rec,
            "disk_gb_recommended":   disk_gb_rec,
            "overcommit_warnings":   warnings,
        })

        total_vcpu_alloc  += vcpu;      total_vcpu_rec  += vcpu_rec
        total_ram_gb_alloc += ram_gb;   total_ram_gb_rec += ram_gb_rec
        total_disk_gb_alloc += disk_gb; total_disk_gb_rec += disk_gb_rec
        total_ram_gb_used  += ram_used_gb

    return {
        "profile":            overcommit_profile,
        "totals_allocated":   {"vcpu": int(total_vcpu_alloc), "ram_gb": round(total_ram_gb_alloc, 1), "ram_used_gb": round(total_ram_gb_used, 1), "disk_tb": round(total_disk_gb_alloc / 1024, 2)},
        "totals_recommended": {"vcpu": int(total_vcpu_rec),   "ram_gb": round(total_ram_gb_rec, 1),   "disk_tb": round(total_disk_gb_rec / 1024, 2)},
        "per_tenant":         per_tenant,
    }


# =====================================================================
# Phase 2D — PCD Hardware Node Sizing
# =====================================================================

def compute_node_sizing(
    totals: Dict[str, Any],             # totals_recommended from compute_quota_requirements
    node_profile: Dict[str, Any],       # migration_pcd_node_profiles row
    existing_inventory: Optional[Dict[str, Any]] = None,  # migration_pcd_node_inventory row (legacy)
    live_cluster: Optional[Dict[str, Any]] = None,        # live data from get_pcd_live_inventory
    max_util_pct: float = 70.0,         # hard ceiling – HA headroom lives inside this
    peak_buffer_pct: float = 15.0,      # extra headroom for traffic spikes
) -> Dict[str, Any]:
    """
    Calculate how many additional PCD compute nodes are needed to absorb the
    migration workload, given the cluster's current state.

    Key principles
    ──────────────
    • The max_util_pct (default 70 %) IS the HA strategy.  At 70 % utilisation
      the cluster can absorb a node failure without guest impact — we do NOT add
      separate "HA spare" nodes on top.
    • If live_cluster data is provided it takes precedence over node_profile
      dimensions, so per-node capacity is derived from the real hardware.
    • peak_buffer_pct adds a future-growth / spike buffer to the migration
      workload before checking whether it fits into available headroom.
    """
    import math

    # ── Per-node capacity ─────────────────────────────────────────────
    # Prefer live cluster data (actual measurement) over node profile (estimate).
    if live_cluster and live_cluster.get("node_count", 0) > 0:
        node_count_current  = int(live_cluster["node_count"])
        cluster_vcpu_total  = int(live_cluster.get("total_vcpus", 0))
        cluster_ram_total   = float(live_cluster.get("total_ram_gb", 0.0))
        # Derive per-node capacity from actual cluster (handles mixed or non-standard nodes)
        vcpu_per_node = cluster_vcpu_total / node_count_current if node_count_current else \
                        int(node_profile.get("cpu_threads", node_profile.get("cpu_cores", 48) * 2))
        ram_per_node  = cluster_ram_total  / node_count_current if node_count_current else \
                        float(node_profile.get("ram_gb", 384.0))
        already_used_vcpu = int(live_cluster.get("vcpus_used", 0))
        already_used_ram  = float(live_cluster.get("ram_gb_used", 0.0))
    else:
        node_count_current  = int(existing_inventory.get("current_nodes", 0)) if existing_inventory else 0
        vcpu_per_node = int(node_profile.get("cpu_threads", node_profile.get("cpu_cores", 48) * 2))
        ram_per_node  = float(node_profile.get("ram_gb", 384.0))
        cluster_vcpu_total  = node_count_current * vcpu_per_node
        cluster_ram_total   = node_count_current * ram_per_node
        already_used_vcpu = int(existing_inventory.get("current_vcpu_used", 0)) if existing_inventory else 0
        already_used_ram  = float(existing_inventory.get("current_ram_gb_used", 0.0)) if existing_inventory else 0.0

    util_frac   = max_util_pct / 100.0
    peak_frac   = 1.0 + peak_buffer_pct / 100.0

    # ── Safe capacity of the CURRENT cluster ─────────────────────────
    safe_vcpu_current = cluster_vcpu_total * util_frac
    safe_ram_current  = cluster_ram_total  * util_frac

    # ── Available headroom (safe capacity minus what is already running)
    headroom_vcpu = max(0.0, safe_vcpu_current - already_used_vcpu)
    headroom_ram  = max(0.0, safe_ram_current  - already_used_ram)

    # ── Migration workload with peak buffer ───────────────────────────
    req_vcpu  = int(totals.get("vcpu", 0))
    req_ram   = float(totals.get("ram_gb", 0.0))
    req_disk  = float(totals.get("disk_tb", 0.0))

    demand_vcpu = req_vcpu  * peak_frac
    demand_ram  = req_ram   * peak_frac

    # ── Deficit = how much workload the current cluster CANNOT absorb ─
    deficit_vcpu = max(0.0, demand_vcpu - headroom_vcpu)
    deficit_ram  = max(0.0, demand_ram  - headroom_ram)

    # ── Additional nodes to cover the deficit ─────────────────────────
    # Each new node provides vcpu_per_node * util_frac usable vCPU / RAM
    eff_vcpu_per_new_node = vcpu_per_node * util_frac
    eff_ram_per_new_node  = ram_per_node  * util_frac

    nodes_for_vcpu = math.ceil(deficit_vcpu / eff_vcpu_per_new_node) if eff_vcpu_per_new_node > 0 else 0
    nodes_for_ram  = math.ceil(deficit_ram  / eff_ram_per_new_node)  if eff_ram_per_new_node  > 0 else 0

    nodes_to_add      = max(nodes_for_vcpu, nodes_for_ram)
    binding_dimension = "cpu" if nodes_for_vcpu >= nodes_for_ram else "ram"

    nodes_total      = node_count_current + nodes_to_add
    total_vcpu_final = nodes_total * vcpu_per_node
    total_ram_final  = nodes_total * ram_per_node

    # ── Post-migration utilisation ─────────────────────────────────────
    total_demand_vcpu = already_used_vcpu + demand_vcpu
    total_demand_ram  = already_used_ram  + demand_ram
    post_cpu_pct = round(total_demand_vcpu / total_vcpu_final * 100, 1) if total_vcpu_final > 0 else 0.0
    post_ram_pct = round(total_demand_ram  / total_ram_final  * 100, 1) if total_ram_final  > 0 else 0.0

    disk_tb_required = round(req_disk, 3)

    # ── Explanation steps for UI display ──────────────────────────────
    steps = [
        f"Cluster capacity ({node_count_current} nodes): {cluster_vcpu_total} vCPU | {cluster_ram_total:.0f} GB RAM",
        f"Safe limit ({max_util_pct:.0f}% utilisation target): {safe_vcpu_current:.0f} vCPU | {safe_ram_current:.0f} GB",
        f"Currently in use: {already_used_vcpu} vCPU | {already_used_ram:.0f} GB",
        f"Available headroom: {headroom_vcpu:.0f} vCPU | {headroom_ram:.0f} GB",
        f"Migration workload (×{peak_frac:.2f} peak buffer): {demand_vcpu:.0f} vCPU | {demand_ram:.0f} GB",
        f"Deficit: {deficit_vcpu:.0f} vCPU | {deficit_ram:.0f} GB  →  add {nodes_to_add} node(s) (binding: {binding_dimension})",
        f"Post-migration utilisation: CPU {post_cpu_pct}% | RAM {post_ram_pct}%  (target ≤ {max_util_pct:.0f}%)",
    ]

    warnings: List[str] = []
    if post_cpu_pct > max_util_pct:
        warnings.append(f"Post-migration CPU utilisation {post_cpu_pct}% exceeds {max_util_pct:.0f}% target")
    if post_ram_pct > max_util_pct:
        warnings.append(f"Post-migration RAM utilisation {post_ram_pct}% exceeds {max_util_pct:.0f}% target")
    if disk_tb_required > 0:
        warnings.append(f"Cinder storage required: {disk_tb_required} TB — provision independently (Ceph/SAN/NFS)")

    return {
        # Current cluster facts
        "node_count_current":   node_count_current,
        "cluster_vcpu_total":   cluster_vcpu_total,
        "cluster_ram_total":    round(cluster_ram_total, 1),
        "vcpu_per_node":        round(vcpu_per_node, 1),
        "ram_per_node":         round(ram_per_node, 1),
        # Policy
        "max_util_pct":         max_util_pct,
        "peak_buffer_pct":      peak_buffer_pct,
        # Headroom
        "safe_vcpu":            round(safe_vcpu_current, 0),
        "safe_ram":             round(safe_ram_current, 1),
        "already_used_vcpu":    already_used_vcpu,
        "already_used_ram":     round(already_used_ram, 1),
        "headroom_vcpu":        round(headroom_vcpu, 0),
        "headroom_ram":         round(headroom_ram, 1),
        # Migration demand
        "demand_vcpu":          round(demand_vcpu, 0),
        "demand_ram":           round(demand_ram, 1),
        "deficit_vcpu":         round(deficit_vcpu, 0),
        "deficit_ram":          round(deficit_ram, 1),
        # Result
        "nodes_to_add":         nodes_to_add,
        "nodes_total":          nodes_total,
        "binding_dimension":    binding_dimension,
        "post_cpu_pct":         post_cpu_pct,
        "post_ram_pct":         post_ram_pct,
        "disk_tb_required":     disk_tb_required,
        "steps":                steps,
        "warnings":             warnings,
        # Legacy aliases kept for backwards-compat with any other consumers
        "nodes_recommended":             nodes_total,
        "nodes_additional_required":     nodes_to_add,
        "existing_nodes":                node_count_current,
        "ha_spares":                     0,
        "ha_policy":                     f"70% utilisation cap (HA embedded)",
        "post_migration_utilisation":    {"cpu_pct": post_cpu_pct, "ram_pct": post_ram_pct},
    }


# =====================================================================
# Phase 2E — PCD Readiness Gap Analysis
# =====================================================================

def analyze_pcd_gaps(
    tenants: List[Dict[str, Any]],
    pcd_flavors: List[Dict[str, Any]],
    pcd_networks: List[Dict[str, Any]],
    pcd_images: List[Dict[str, Any]],
    vmware_vms: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Compare what VMware VMs need vs what PCD already has and return a list of gaps.

    Args:
        tenants:       migration_tenants rows (include_in_plan=True only).
        pcd_flavors:   list of Nova flavor dicts from PCD/OpenStack.
        pcd_networks:  list of Neutron network dicts.
        pcd_images:    list of Glance image dicts.
        vmware_vms:    migration_vms rows.

    Returns:
        List of gap dicts: {gap_type, resource_name, tenant_name, severity, details, resolution}
    """
    gaps: List[Dict[str, Any]] = []
    included_tenant_names = {
        t["tenant_name"] for t in tenants if t.get("include_in_plan", True)
    }

    # ── Flavors: find (vcpu, ram_mb) combos with no matching PCD flavor ─────
    needed_shapes: Dict[tuple, List[str]] = {}
    for vm in vmware_vms:
        if vm.get("tenant_name") not in included_tenant_names:
            continue
        key = (int(vm.get("cpu_count") or 0), int(vm.get("ram_mb") or 0))
        if key not in needed_shapes:
            needed_shapes[key] = []
        needed_shapes[key].append(vm["vm_name"])

    pcd_flavor_shapes = set()
    for f in pcd_flavors:
        pcd_flavor_shapes.add((int(f.get("vcpus") or 0), int(f.get("ram") or 0)))

    for (vcpu, ram_mb), vms_list in needed_shapes.items():
        if vcpu == 0 and ram_mb == 0:
            continue
        # Find nearest existing flavor
        matched = any(
            abs(fvcpu - vcpu) <= 1 and abs(fram_mb - ram_mb) / max(ram_mb, 1) < 0.1
            for fvcpu, fram_mb in pcd_flavor_shapes
        )
        if not matched:
            gaps.append({
                "gap_type":     "flavor",
                "resource_name": f"{vcpu}vCPU-{ram_mb // 1024}GB",
                "tenant_name":  None,
                "severity":     "warning",
                "details":      {"vcpu": vcpu, "ram_mb": ram_mb, "vm_count": len(vms_list), "example_vms": vms_list[:3]},
                "resolution":   f"Create flavor with {vcpu} vCPUs, {ram_mb} MB RAM in PCD",
            })

    # ── Networks: source VM networks not present in PCD ──────────────────────
    pcd_network_names = {n.get("name", "").lower() for n in pcd_networks}
    needed_networks: Dict[str, set] = {}
    for vm in vmware_vms:
        if vm.get("tenant_name") not in included_tenant_names:
            continue
        net = vm.get("network_name", "")
        if not net:
            continue
        if net not in needed_networks:
            needed_networks[net] = set()
        needed_networks[net].add(vm.get("tenant_name"))

    for net_name, tenants_using in needed_networks.items():
        if net_name.lower() not in pcd_network_names:
            gaps.append({
                "gap_type":     "network",
                "resource_name": net_name,
                "tenant_name":  None,
                "severity":     "critical" if len(tenants_using) > 1 else "warning",
                "details":      {"vm_count": sum(1 for vm in vmware_vms if vm.get("network_name") == net_name),
                                 "tenants": list(tenants_using)},
                "resolution":   f"Create or map network '{net_name}' in PCD",
            })

    # ── Images: OS families needed ───────────────────────────────────────────
    pcd_image_names_lower = {i.get("name", "").lower() for i in pcd_images}
    needed_os: Dict[str, int] = {}
    for vm in vmware_vms:
        if vm.get("tenant_name") not in included_tenant_names:
            continue
        os_fam = vm.get("os_family", "other") or "other"
        needed_os[os_fam] = needed_os.get(os_fam, 0) + 1

    # Check if there's at least one image per OS family needed
    for os_fam, count in needed_os.items():
        if os_fam == "other":
            continue
        has_image = any(os_fam in name for name in pcd_image_names_lower)
        if not has_image:
            gaps.append({
                "gap_type":     "image",
                "resource_name": f"{os_fam}-base-image",
                "tenant_name":  None,
                "severity":     "warning",
                "details":      {"os_family": os_fam, "vm_count": count},
                "resolution":   f"Upload or register a {os_fam} cloud image in PCD Glance",
            })

    # ── Tenant mapping gaps: tenants with no target domain/project set ───────
    for t in tenants:
        if not t.get("include_in_plan", True):
            continue
        domain = t.get("target_domain_name") or t.get("target_domain") or ""
        project = t.get("target_project_name") or t.get("target_project") or ""
        if not domain or not project:
            gaps.append({
                "gap_type":     "mapping",
                "resource_name": t["tenant_name"],
                "tenant_name":  t["tenant_name"],
                "severity":     "warning",
                "details":      {"has_domain": bool(domain), "has_project": bool(project)},
                "resolution":   "Set target_domain_name and target_project_name in tenant mapping",
            })

    return gaps


# =====================================================================
# 9.  Phase 3.0 — Tenant Ease Score & Auto-Assign Cohorts
# =====================================================================

# Default weights — must sum to 100
DEFAULT_EASE_WEIGHTS: Dict[str, float] = {
    "disk":      20.0,   # total used disk GB (bigger = harder)
    "risk":      25.0,   # average risk score (higher = harder)
    "os":        20.0,   # unsupported OS rate (1 - support_rate)
    "vm_count":  15.0,   # number of VMs in tenant
    "networks":  10.0,   # distinct source networks
    "deps":       5.0,   # cross-tenant VM dependencies
    "cold":       3.0,   # fraction of VMs classified cold
    "unconf":     2.0,   # fraction of target/network mappings unconfirmed
}


def _norm(value: float, max_val: float) -> float:
    """Normalise a value to 0–1.  Returns 0 if max_val is 0."""
    if max_val <= 0:
        return 0.0
    return min(value / max_val, 1.0)


def compute_tenant_ease_scores(
    tenants: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Compute a 0–100 ease score for each tenant.

    Lower score  ⟹  easier (migrate first: small, low-risk, fully-supported).
    Higher score ⟹  harder (save for later: large, risky, unsupported OS).

    Each input tenant dict should contain:
        tenant_id, tenant_name
        vm_count               (int)
        total_used_gb          (float)   — sum(in_use_gb) across VMs
        avg_risk_score         (float)   — average risk score 0–100
        os_support_rate        (float)   — fraction 0–1 of VMs with supported OS
        distinct_network_count (int)
        cross_tenant_dep_count (int)     — dependency edges pointing outside this tenant
        cold_vm_count          (int)     — VMs classified cold
        unconfirmed_count      (int)     — unconfirmed target+network mappings
        total_vm_or_mapping    (int)     — denominator for unconfirmed_ratio
    """
    w = dict(DEFAULT_EASE_WEIGHTS)
    if weights:
        w.update(weights)
    # Normalise weights so they sum to 100
    total_w = sum(w.values()) or 100.0
    w = {k: v / total_w * 100 for k, v in w.items()}

    # --- Compute per-dimension maxima across all tenants (for normalisation) ---
    # float() cast is required: DB may return decimal.Decimal for aggregated columns
    max_used_gb    = float(max((float(t.get("total_used_gb", 0) or 0) for t in tenants), default=1))
    max_vm_count   = float(max((int(t.get("vm_count", 0)        or 0) for t in tenants), default=1))
    max_networks   = float(max((int(t.get("distinct_network_count", 0) or 0) for t in tenants), default=1))
    max_deps       = float(max((int(t.get("cross_tenant_dep_count", 0) or 0) for t in tenants), default=1))

    results = []
    for t in tenants:
        used_gb    = float(t.get("total_used_gb", 0) or 0)
        vm_count   = int(t.get("vm_count", 0)        or 0)
        cold_cnt   = int(t.get("cold_vm_count", 0)   or 0)
        avg_risk   = float(t.get("avg_risk_score", 0) or 0)
        os_rate    = float(t.get("os_support_rate", 1) or 1)
        net_cnt    = int(t.get("distinct_network_count", 0) or 0)
        dep_cnt    = int(t.get("cross_tenant_dep_count", 0) or 0)
        unconf     = int(t.get("unconfirmed_count", 0) or 0)
        denom      = int(t.get("total_vm_or_mapping", max(vm_count, 1)) or max(vm_count, 1))

        cold_ratio  = cold_cnt / vm_count  if vm_count  > 0 else 0.0
        unconf_ratio = unconf / denom      if denom     > 0 else 0.0

        dims = {
            "disk":     _norm(used_gb, max_used_gb)    * w["disk"],
            "risk":     _norm(avg_risk, 100)           * w["risk"],
            "os":       (1.0 - os_rate)                * w["os"],
            "vm_count": _norm(vm_count, max_vm_count)  * w["vm_count"],
            "networks": _norm(net_cnt, max_networks)   * w["networks"],
            "deps":     _norm(dep_cnt, max_deps)       * w["deps"],
            "cold":     cold_ratio                     * w["cold"],
            "unconf":   unconf_ratio                   * w["unconf"],
        }
        score = sum(dims.values())

        results.append({
            "tenant_id":     t.get("tenant_id") or t.get("id"),
            "tenant_name":   t.get("tenant_name", ""),
            "ease_score":    round(score, 1),
            "ease_label":    "Easy" if score < 30 else ("Medium" if score < 60 else "Hard"),
            "vm_count":      vm_count,
            "total_used_gb": round(used_gb, 1),
            "avg_risk_score": round(avg_risk, 1),
            "os_support_rate": round(os_rate, 3),
            "distinct_network_count": net_cnt,
            "cross_tenant_dep_count": dep_cnt,
            "cold_vm_ratio": round(cold_ratio, 3),
            "unconfirmed_ratio": round(unconf_ratio, 3),
            "dimension_scores": {k: round(v, 2) for k, v in dims.items()},
            "dimension_weights": {k: round(w[k], 1) for k in w},
        })

    return sorted(results, key=lambda x: x["ease_score"])


def auto_assign_cohorts(
    tenants: List[Dict[str, Any]],          # rows with ease_score, vm_count, total_used_gb, avg_risk_score, os_family_counts
    existing_cohorts: List[Dict[str, Any]], # [{id, name, cohort_order, vm_count, total_used_gb}]
    strategy: str = "easiest_first",
    num_cohorts: int = 3,
    guardrails: Optional[Dict[str, Any]] = None,
    ease_weights: Optional[Dict[str, float]] = None,
    cohort_profiles: Optional[List[Dict[str, Any]]] = None,  # [{name, max_vms}] — ramp mode
) -> Dict[str, Any]:
    """
    Propose a tenant → cohort assignment.

    Strategies
    ----------
    easiest_first  : sort by ease_score ASC, fill cohorts in order respecting guardrails
    riskiest_last  : high-risk tenants always go into the last cohort; rest by ease_score
    pilot_bulk     : top-N easiest → "🧪 Pilot" cohort; rest → "🚀 Main" cohort
    balanced_load  : greedy bin-pack by total_used_gb to minimise max-cohort GB
    os_first       : Linux tenants before Windows tenants, then by ease_score
    by_priority    : sort by migration_priority ASC (lower = earlier), ties broken by ease_score

    Returns a dict with:
        assignments    : [{tenant_id, tenant_name, cohort_slot (1-based)}]
        cohort_summaries : [{slot, tenant_count, vm_count, total_used_gb, avg_ease_score, est_hours}]
        warnings       : [str]   (guardrail violations or dependency warnings)
        new_cohort_names : [str] if strategy created implicit cohort names
    """
    guardrails = guardrails or {}
    max_vms    = guardrails.get("max_vms_per_cohort", 9999)
    max_gb     = guardrails.get("max_disk_tb_per_cohort", 9999) * 1024  # convert TB → GB
    max_risk   = guardrails.get("max_avg_risk", 100)
    min_os_rt  = guardrails.get("min_os_support_rate", 0.0)

    # Compute ease scores if not already present
    scored = compute_tenant_ease_scores(tenants, ease_weights)
    by_id  = {t["tenant_id"]: t for t in scored}

    warnings: List[str] = []

    # ---- Ramp Profile mode (per-cohort VM caps) ----
    if cohort_profiles:
        num_cohorts = len(cohort_profiles)
        scored = compute_tenant_ease_scores(tenants, ease_weights)
        by_id  = {t["tenant_id"]: t for t in scored}

        # Build ordering based on chosen strategy
        if strategy == "os_first":
            def _osk(t: Dict) -> int:
                f = (t.get("os_family") or "other").lower()
                return 0 if f == "linux" else (1 if f == "windows" else 2)
            ordering: List[Dict] = sorted(scored, key=lambda x: (_osk(x), x["ease_score"]))
        elif strategy == "riskiest_last":
            rth = (guardrails or {}).get("risk_threshold", 70)
            high = sorted([t for t in scored if t["avg_risk_score"] >= rth], key=lambda x: x["ease_score"])
            safe = sorted([t for t in scored if t["avg_risk_score"] <  rth], key=lambda x: x["ease_score"])
            ordering = safe + high
        elif strategy == "by_priority":
            ordering = sorted(
                scored,
                key=lambda x: (
                    next((t.get("migration_priority") or 999 for t in tenants
                          if (t.get("tenant_id") or t.get("id")) == x["tenant_id"]), 999),
                    x["ease_score"]
                )
            )
        elif strategy == "balanced_load":
            ordering = sorted(scored, key=lambda x: x["total_used_gb"], reverse=True)
        else:  # easiest_first, pilot_bulk, unknown
            ordering = sorted(scored, key=lambda x: x["ease_score"])

        slots: Dict[int, int] = {}
        profile_vm_counts = [0] * num_cohorts

        # ---- pilot_bulk in ramp mode: first pilot_size easiest → slot 1, rest fill slots 2..N ----
        if strategy == "pilot_bulk":
            pilot_size_val = (guardrails or {}).get("pilot_size", 5)
            pilot   = ordering[:pilot_size_val]
            rest    = ordering[pilot_size_val:]
            for t in pilot:
                slots[t["tenant_id"]] = 1
                profile_vm_counts[0] += t["vm_count"]
            cur_wave = 1  # start from slot index 1 (= wave slot 2)
            for t in rest:
                for _ in range(max(num_cohorts - 1, 1)):
                    # per-profile cap takes priority, else fall back to guardrail max_vms
                    cap = cohort_profiles[cur_wave].get("max_vms") or max_vms
                    if profile_vm_counts[cur_wave] + t["vm_count"] <= cap:
                        break
                    if cur_wave < num_cohorts - 1:
                        cur_wave += 1
                        warnings.append(
                            f"Wave {cur_wave} guardrail hit — overflow tenant '{t['tenant_name']}' placed in next wave"
                        )
                slots[t["tenant_id"]] = cur_wave + 1
                profile_vm_counts[cur_wave] += t["vm_count"]
        else:
            for t in ordering:
                placed = False
                for slot_idx, profile in enumerate(cohort_profiles):
                    # per-profile cap takes priority, else fall back to guardrail max_vms
                    cap = profile.get("max_vms") or max_vms
                    if profile_vm_counts[slot_idx] + t["vm_count"] <= cap:
                        slots[t["tenant_id"]] = slot_idx + 1
                        profile_vm_counts[slot_idx] += t["vm_count"]
                        placed = True
                        break
                if not placed:
                    slots[t["tenant_id"]] = num_cohorts
                    warnings.append(
                        f"Tenant \u2018{t['tenant_name']}\u2019 overflowed all cohort caps \u2014 placed in last cohort"
                    )

        names = [p.get("name") or f"Cohort {i+1}" for i, p in enumerate(cohort_profiles)]
        return _format_auto_assign_result(scored, slots, num_cohorts, names, by_id, warnings)

    # ---- Strategy: pilot + waves (N cohorts) ----
    if strategy == "pilot_bulk":
        pilot_size = guardrails.get("pilot_size", 5)
        sorted_easy = sorted(scored, key=lambda x: x["ease_score"])
        pilot     = sorted_easy[:pilot_size]
        remaining = sorted_easy[pilot_size:]

        slots: Dict[int, int] = {t["tenant_id"]: 1 for t in pilot}

        # Distribute remaining tenants across wave slots (2..num_cohorts)
        n_wave_slots = max(num_cohorts - 1, 1)
        wave_vms  = [0]   * n_wave_slots
        wave_gb   = [0.0] * n_wave_slots
        cur_wave  = 0
        for t in remaining:
            for _ in range(n_wave_slots):
                v = wave_vms[cur_wave] + t["vm_count"]
                g = wave_gb[cur_wave]  + t["total_used_gb"]
                if v <= max_vms and g <= max_gb:
                    break
                cur_wave = min(cur_wave + 1, n_wave_slots - 1)
                warnings.append(f"Cohort {cur_wave + 1} guardrail hit — overflow tenant '{t['tenant_name']}' placed in next wave")
            slots[t["tenant_id"]] = cur_wave + 2  # slot 2 = Wave 1, etc.
            wave_vms[cur_wave] += t["vm_count"]
            wave_gb[cur_wave]  += t["total_used_gb"]

        # Auto-name: Pilot / Wave 1 / Wave 2 / ... / Main
        if num_cohorts == 2:
            names = ["🧪 Pilot", "🚀 Main"]
        else:
            names = ["🧪 Pilot"] + [f"🔄 Wave {i}" for i in range(1, num_cohorts - 1)] + ["🚀 Main"]

        return _format_auto_assign_result(scored, slots, num_cohorts, names, by_id, warnings)

    # ---- Strategy: riskiest_last ----
    if strategy == "riskiest_last":
        risk_threshold = guardrails.get("risk_threshold", 70)
        high_risk = [t for t in scored if t["avg_risk_score"] >= risk_threshold]
        safe      = [t for t in scored if t["avg_risk_score"] <  risk_threshold]
        # safe fill slots 1..num_cohorts-1, high_risk always slot num_cohorts
        safe_sorted = sorted(safe, key=lambda x: x["ease_score"])
        slots: Dict[int, int] = {}
        inner_n = max(num_cohorts - 1, 1)
        buckets = [[] for _ in range(inner_n)]
        for i, t in enumerate(safe_sorted):
            buckets[i % inner_n].append(t)
        for slot_idx, bucket in enumerate(buckets, start=1):
            for t in bucket:
                slots[t["tenant_id"]] = slot_idx
        for t in high_risk:
            slots[t["tenant_id"]] = num_cohorts
        return _format_auto_assign_result(scored, slots, num_cohorts, [], by_id, warnings)

    # ---- Strategy: balanced_load (minimise max cohort GB) ----
    if strategy == "balanced_load":
        # Greedy: always add next-largest tenant to the lightest cohort
        sorted_by_gb = sorted(scored, key=lambda x: x["total_used_gb"], reverse=True)
        cohort_gb  = [0.0] * num_cohorts
        cohort_vms = [0]   * num_cohorts
        slots = {}
        for t in sorted_by_gb:
            # pick cohort with least GB that still has room
            candidates = [
                i for i in range(num_cohorts)
                if cohort_vms[i] + t["vm_count"] <= max_vms
                and cohort_gb[i] + t["total_used_gb"] <= max_gb
            ]
            if not candidates:
                candidates = range(num_cohorts)
                warnings.append(f"Guardrail exceeded for tenant '{t['tenant_name']}' — placed in closest cohort")
            pick = min(candidates, key=lambda i: cohort_gb[i])
            slots[t["tenant_id"]] = pick + 1
            cohort_gb[pick]  += t["total_used_gb"]
            cohort_vms[pick] += t["vm_count"]
        return _format_auto_assign_result(scored, slots, num_cohorts, [], by_id, warnings)

    # ---- Strategy: os_first ----
    if strategy == "os_first":
        def os_key(t: Dict) -> int:
            family = (t.get("os_family") or "other").lower()
            return 0 if family == "linux" else (1 if family == "windows" else 2)
        sorted_os = sorted(scored, key=lambda x: (os_key(x), x["ease_score"]))
        slots = {}
        bucket_size = max(1, math.ceil(len(sorted_os) / num_cohorts))
        for i, t in enumerate(sorted_os):
            slots[t["tenant_id"]] = min(i // bucket_size + 1, num_cohorts)
        return _format_auto_assign_result(scored, slots, num_cohorts, [], by_id, warnings)

    # ---- Strategy: by_priority ----
    if strategy == "by_priority":
        sorted_p = sorted(tenants, key=lambda x: (x.get("migration_priority") or 999, by_id.get(x.get("tenant_id") or x.get("id"), {}).get("ease_score", 50)))
        slots = {}
        bucket_size = max(1, math.ceil(len(sorted_p) / num_cohorts))
        for i, t in enumerate(sorted_p):
            tid = t.get("tenant_id") or t.get("id")
            slots[tid] = min(i // bucket_size + 1, num_cohorts)
        return _format_auto_assign_result(scored, slots, num_cohorts, [], by_id, warnings)

    # ---- Default: easiest_first ----
    sorted_easy = sorted(scored, key=lambda x: x["ease_score"])
    slots = {}
    cohort_vms = [0]   * num_cohorts
    cohort_gb  = [0.0] * num_cohorts
    current_slot = 0
    for t in sorted_easy:
        # Advance slot if guardrails would be violated
        for _ in range(num_cohorts):
            v  = cohort_vms[current_slot] + t["vm_count"]
            g  = cohort_gb[current_slot]  + t["total_used_gb"]
            ar = (cohort_gb[current_slot] / max(cohort_vms[current_slot], 1)) if cohort_vms[current_slot] > 0 else t["avg_risk_score"]
            if v <= max_vms and g <= max_gb:
                break
            current_slot = min(current_slot + 1, num_cohorts - 1)
            warnings.append(f"Cohort {current_slot} guardrail hit — overflow tenant '{t['tenant_name']}' placed in next cohort")

        # Additional per-cohort risk / OS guardrail warning (informational only)
        if t["avg_risk_score"] > max_risk:
            warnings.append(f"Tenant '{t['tenant_name']}' has avg risk {t['avg_risk_score']:.0f} (threshold {max_risk})")
        if t["os_support_rate"] < min_os_rt:
            warnings.append(f"Tenant '{t['tenant_name']}' OS support {t['os_support_rate']*100:.0f}% < minimum {min_os_rt*100:.0f}%")

        slots[t["tenant_id"]] = current_slot + 1
        cohort_vms[current_slot] += t["vm_count"]
        cohort_gb[current_slot]  += t["total_used_gb"]

    return _format_auto_assign_result(scored, slots, num_cohorts, [], by_id, warnings)


def _format_auto_assign_result(
    scored: List[Dict[str, Any]],
    slots: Dict[int, int],
    num_cohorts: int,
    names: List[str],
    by_id: Dict[int, Dict[str, Any]],
    warnings: List[str],
) -> Dict[str, Any]:
    """Format the auto-assign output into a consistent response shape."""
    assignments = []
    for t in scored:
        tid  = t["tenant_id"]
        slot = slots.get(tid, num_cohorts)
        assignments.append({
            "tenant_id":   tid,
            "tenant_name": t["tenant_name"],
            "cohort_slot": slot,
            "ease_score":  t["ease_score"],
            "ease_label":  t["ease_label"],
        })
    assignments.sort(key=lambda x: (x["cohort_slot"], x["ease_score"]))

    # Build per-cohort summary
    cohort_map: Dict[int, List[Dict]] = {}
    for a in assignments:
        cohort_map.setdefault(a["cohort_slot"], []).append(a)

    summaries = []
    for slot in range(1, num_cohorts + 1):
        members = cohort_map.get(slot, [])
        t_data  = [by_id.get(m["tenant_id"], {}) for m in members]
        vm_cnt  = sum(td.get("vm_count", 0) or 0     for td in t_data)
        used_gb = sum(td.get("total_used_gb", 0) or 0 for td in t_data)
        avg_ease = (sum(m["ease_score"] for m in members) / len(members)
                    if members else 0)
        avg_risk = (sum(td.get("avg_risk_score", 0) or 0 for td in t_data) / len(t_data)
                    if t_data else 0)
        summaries.append({
            "slot":           slot,
            "name":           names[slot - 1] if slot - 1 < len(names) else f"Cohort {slot}",
            "tenant_count":   len(members),
            "vm_count":       vm_cnt,
            "total_disk_gb":  round(used_gb, 1),
            "avg_ease_score": round(avg_ease, 1),
            "avg_risk":       round(avg_risk, 1),
        })

    return {
        "strategy":        "auto_assign",
        "num_cohorts":     num_cohorts,
        "assignments":     assignments,
        "cohort_summaries": summaries,
        "cohort_names":    names or [f"Cohort {i+1}" for i in range(num_cohorts)],
        "warnings":        list(dict.fromkeys(warnings)),  # deduplicate
    }


# =====================================================================
# 11.  Wave Planning Engine  (Phase 3)
# =====================================================================

WAVE_STRATEGIES = ("by_tenant", "by_risk", "pilot_first", "by_priority", "balanced")

PREFLIGHT_CHECKS = [
    # (check_name, label, severity)
    ("network_mapped",      "All VM networks mapped to PCD",       "blocker"),
    ("target_project_set",  "Target PCD project/domain confirmed", "blocker"),
    ("vms_assessed",        "All VMs have risk & mode set",        "warning"),
    ("no_critical_gaps",    "No unresolved critical PCD gaps",     "blocker"),
    ("agent_reachable",     "Migration agent connectivity",        "warning"),
    ("snapshot_baseline",   "Pre-migration snapshot taken",        "info"),
]


def build_wave_plan(
    vms: List[Dict[str, Any]],
    tenants: List[Dict[str, Any]],
    dependencies: List[Dict[str, Any]],     # [{vm_id, depends_on_vm_id}]
    strategy: str = "pilot_first",
    max_vms_per_wave: int = 30,
    pilot_vm_count: int = 5,
    wave_name_prefix: str = "Wave",
) -> Dict[str, Any]:
    """
    Build a wave plan from a set of powered-on, in-scope VM records.

    Strategies
    ----------
    pilot_first  : Wave 0 = N lowest-risk, smallest VMs; rest fill subsequent waves.
    by_tenant    : One wave per tenant, sorted by tenant migration_priority.
    by_risk      : Green VMs → Wave 1, Yellow → Wave 2, Red → Wave 3.
    by_priority  : Fill waves sequentially respecting tenant migration_priority ordering.
    balanced     : Minimise variance in total_disk_gb across waves.

    Returns
    -------
    dict with keys: waves, strategy, warnings, unassigned_vm_ids
    """
    strategy = strategy if strategy in WAVE_STRATEGIES else "pilot_first"
    warnings: List[str] = []

    # --- Build tenant lookup -----------------------------------------------
    tenant_by_name: Dict[str, Dict] = {t["tenant_name"]: t for t in tenants}

    # --- Filter to powered-on, in-scope VMs only ---------------------------
    candidate_vms = [
        v for v in vms
        if (v.get("power_state") or "").lower() in ("poweredon", "powered_on", "on")
        and v.get("migration_status") not in ("migrated", "skipped")
    ]
    if not candidate_vms:
        candidate_vms = [v for v in vms
                         if v.get("migration_status") not in ("migrated", "skipped")]
    if not candidate_vms:
        return {"waves": [], "strategy": strategy,
                "warnings": ["No eligible VMs found"], "unassigned_vm_ids": []}

    # --- Dependency graph: vm_id → set of vm_ids it depends on ------------
    dep_graph: Dict[int, set] = {}
    for d in dependencies:
        src = d.get("vm_id")
        dep = d.get("depends_on_vm_id")
        if src and dep:
            dep_graph.setdefault(src, set()).add(dep)
    all_ids = {v["id"] for v in candidate_vms if v.get("id")}

    def _risk_order(v: Dict) -> int:
        """Lower = safer"""
        rc = (v.get("risk_classification") or "GREEN").upper()
        return {"GREEN": 0, "YELLOW": 1, "RED": 2}.get(rc, 1)

    def _vm_disk(v: Dict) -> float:
        used = v.get("in_use_gb") or v.get("total_disk_gb") or 0
        return float(used)

    def _tenant_priority(v: Dict) -> int:
        t = tenant_by_name.get(v.get("tenant_name") or "", {})
        return t.get("migration_priority") or 999

    # -----------------------------------------------------------------------
    #  Strategy implementations
    # -----------------------------------------------------------------------
    waves_spec: List[Dict[str, Any]] = []   # [{name, wave_type, vm_ids}]

    if strategy == "pilot_first":
        # Sort by risk asc, then disk asc → take first N as pilot
        sorted_vms = sorted(candidate_vms, key=lambda v: (_risk_order(v), _vm_disk(v)))
        pilot_ids = [v["id"] for v in sorted_vms[:pilot_vm_count] if v.get("id")]
        rest = [v for v in sorted_vms[pilot_vm_count:] if v.get("id")]
        # Pilot wave name uses the prefix so each cohort's pilot is identifiable
        waves_spec.append({"name": f"🧪 {wave_name_prefix}", "wave_type": "pilot", "vm_ids": pilot_ids})
        # Fill regular waves — counter starts at 1 (independent of the pilot slot)
        for n, chunk_start in enumerate(range(0, len(rest), max_vms_per_wave), 1):
            chunk = rest[chunk_start:chunk_start + max_vms_per_wave]
            waves_spec.append({
                "name": f"{wave_name_prefix} {n}",
                "wave_type": "regular",
                "vm_ids": [v["id"] for v in chunk],
            })

    elif strategy == "by_tenant":
        # One wave per tenant, sorted by tenant priority then ease score
        tenant_groups: Dict[str, List[Dict]] = {}
        for v in candidate_vms:
            tname = v.get("tenant_name") or "Unassigned"
            tenant_groups.setdefault(tname, []).append(v)
        # Sort tenants by priority
        ordered_tenants = sorted(
            tenant_groups.keys(),
            key=lambda t: (tenant_by_name.get(t, {}).get("migration_priority") or 999, t)
        )
        for i, tname in enumerate(ordered_tenants, 1):
            tvms = sorted(tenant_groups[tname], key=lambda v: (_risk_order(v), _vm_disk(v)))
            # Split tenant if too large
            for chunk_start in range(0, len(tvms), max_vms_per_wave):
                chunk = tvms[chunk_start:chunk_start + max_vms_per_wave]
                suffix = f" (part {chunk_start // max_vms_per_wave + 1})" if len(tvms) > max_vms_per_wave else ""
                waves_spec.append({
                    "name": f"{wave_name_prefix} {len(waves_spec) + 1} — {tname}{suffix}",
                    "wave_type": "regular",
                    "vm_ids": [v["id"] for v in chunk if v.get("id")],
                })

    elif strategy == "by_risk":
        # Green → Wave 1, Yellow → Wave 2, Red → Wave 3+
        buckets = {"GREEN": [], "YELLOW": [], "RED": []}
        for v in candidate_vms:
            rc = (v.get("risk_classification") or "GREEN").upper()
            buckets.get(rc, buckets["RED"]).append(v)
        for band, label in [("GREEN", "🟢 Low Risk"), ("YELLOW", "🟡 Medium Risk"), ("RED", "🔴 High Risk")]:
            bvms = sorted(buckets[band], key=lambda v: (_vm_disk(v), _tenant_priority(v)))
            for chunk_start in range(0, len(bvms), max_vms_per_wave):
                chunk = bvms[chunk_start:chunk_start + max_vms_per_wave]
                suffix = f" pt{chunk_start // max_vms_per_wave + 1}" if len(bvms) > max_vms_per_wave else ""
                waves_spec.append({
                    "name": f"{wave_name_prefix} {len(waves_spec) + 1} — {label}{suffix}",
                    "wave_type": "regular",
                    "vm_ids": [v["id"] for v in chunk if v.get("id")],
                })

    elif strategy == "by_priority":
        # All VMs sorted by (tenant_priority, risk, disk), chunked into waves
        sorted_vms = sorted(candidate_vms, key=lambda v: (_tenant_priority(v), _risk_order(v), _vm_disk(v)))
        for chunk_start in range(0, len(sorted_vms), max_vms_per_wave):
            chunk = sorted_vms[chunk_start:chunk_start + max_vms_per_wave]
            waves_spec.append({
                "name": f"{wave_name_prefix} {len(waves_spec) + 1}",
                "wave_type": "regular",
                "vm_ids": [v["id"] for v in chunk if v.get("id")],
            })

    elif strategy == "balanced":
        # Distribute VMs to minimise variance in total_disk_gb per wave
        num_waves = max(1, math.ceil(len(candidate_vms) / max_vms_per_wave))
        wave_disks = [0.0] * num_waves
        wave_vms: List[List[int]] = [[] for _ in range(num_waves)]
        sorted_vms = sorted(candidate_vms, key=lambda v: -_vm_disk(v))  # largest first
        for v in sorted_vms:
            if not v.get("id"):
                continue
            # Assign to wave with least disk so far
            idx = min(range(num_waves), key=lambda i: (len(wave_vms[i]) >= max_vms_per_wave, wave_disks[i]))
            wave_vms[idx].append(v["id"])
            wave_disks[idx] += _vm_disk(v)
        for i, vids in enumerate(wave_vms, 1):
            if vids:
                waves_spec.append({
                    "name": f"{wave_name_prefix} {i}",
                    "wave_type": "regular",
                    "vm_ids": vids,
                })

    # -----------------------------------------------------------------------
    #  Dependency check — flag cross-wave dependency violations
    # -----------------------------------------------------------------------
    vm_to_wave: Dict[int, int] = {}
    for wi, w in enumerate(waves_spec):
        for vid in w["vm_ids"]:
            vm_to_wave[vid] = wi

    for vid, deps in dep_graph.items():
        my_wave = vm_to_wave.get(vid)
        if my_wave is None:
            continue
        for dep_id in deps:
            dep_wave = vm_to_wave.get(dep_id)
            if dep_wave is not None and dep_wave >= my_wave:
                warnings.append(
                    f"VM id={vid} is in Wave {my_wave + 1} but depends on VM id={dep_id} "
                    f"which is in Wave {dep_wave + 1} — dependency may not be satisfied."
                )

    # -----------------------------------------------------------------------
    #  Build final wave dicts with statistics
    # -----------------------------------------------------------------------
    vm_by_id: Dict[int, Dict] = {v["id"]: v for v in candidate_vms if v.get("id")}
    waves_out = []
    assigned_ids: set = set()
    for wave_number, ws in enumerate(waves_spec, 1):
        vids = ws["vm_ids"]
        wave_vms_data = [vm_by_id[vid] for vid in vids if vid in vm_by_id]
        risk_dist: Dict[str, int] = {"GREEN": 0, "YELLOW": 0, "RED": 0}
        tenant_names: set = set()
        total_disk = 0.0
        for v in wave_vms_data:
            rc = (v.get("risk_classification") or "GREEN").upper()
            risk_dist[rc] = risk_dist.get(rc, 0) + 1
            tenant_names.add(v.get("tenant_name") or "?")
            total_disk += _vm_disk(v)
        assigned_ids.update(vids)
        waves_out.append({
            "wave_number":      wave_number,
            "name":             ws["name"],
            "wave_type":        ws.get("wave_type", "regular"),
            "status":           "planned",
            "vm_ids":           vids,
            "vm_count":         len(vids),
            "tenant_names":     sorted(tenant_names),
            "risk_distribution": risk_dist,
            "total_disk_gb":    round(total_disk, 1),
        })

    unassigned = [v["id"] for v in candidate_vms
                  if v.get("id") and v["id"] not in assigned_ids]
    if unassigned:
        warnings.append(f"{len(unassigned)} VMs could not be assigned to any wave.")

    return {
        "waves":             waves_out,
        "strategy":          strategy,
        "warnings":          list(dict.fromkeys(warnings)),
        "unassigned_vm_ids": unassigned,
        "preflight_checks":  [{"check_name": c[0], "check_label": c[1],
                               "severity": c[2]} for c in PREFLIGHT_CHECKS],
    }

