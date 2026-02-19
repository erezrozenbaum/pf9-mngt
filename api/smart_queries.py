"""
Smart Query Templates — Ops-Assistant Inline Answers
=====================================================
Matches natural-language questions to parameterised SQL queries
and returns structured answer cards rendered directly in the search UI.

This module is **additive** — it does NOT modify the existing search or
intent detection.  The API exposes a single new endpoint that the UI
calls in parallel with FTS + intent detection.

Architecture
------------
  1. User types a question, e.g. "how many VMs are powered off?"
  2. Each `SmartQuery` entry's regex is tested against the question.
  3. First match wins → its SQL is executed with extracted parameters.
  4. A `formatter` function shapes the rows into a response card.

Query categories
----------------
  • Infrastructure   – VM counts / lists, volumes, images, networks
  • Capacity         – hypervisor usage, headroom
  • Quota            – tenant quota vs used
  • Security / RBAC  – role assignments, security groups
  • Operations       – drift events, activity log, snapshots
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from psycopg2.extras import RealDictCursor

logger = logging.getLogger("pf9.smart_queries")


# ── Types ────────────────────────────────────────────────────

@dataclass
class SmartQuery:
    """A single query template."""
    id: str
    title: str
    pattern: re.Pattern
    sql: str
    formatter: Callable[[List[Dict], Dict[str, Any]], Dict[str, Any]]
    description: str = ""
    category: str = "general"
    # Named groups captured from the regex are passed as SQL params
    param_keys: List[str] = field(default_factory=list)


# ── Formatters ───────────────────────────────────────────────
# Each formatter receives (rows, params) and returns a dict with:
#   title, summary, columns, rows, chart_hint (optional)

def _fmt_table(title: str, summary_fn: Callable, columns: List[Dict]):
    """Factory for simple table formatters."""
    def _inner(rows: List[Dict], params: Dict[str, Any]) -> Dict[str, Any]:
        clean = _clean_rows(rows)
        return {
            "card_type": "table",
            "title": title,
            "summary": summary_fn(clean, params),
            "columns": columns,
            "rows": clean,
            "total": len(clean),
        }
    return _inner


def _fmt_kv(title: str, summary_fn: Callable):
    """Factory for key-value card formatters (single-row results)."""
    def _inner(rows: List[Dict], params: Dict[str, Any]) -> Dict[str, Any]:
        clean = _clean_rows(rows)
        row = clean[0] if clean else {}
        return {
            "card_type": "kv",
            "title": title,
            "summary": summary_fn(row, params),
            "data": row,
        }
    return _inner


def _fmt_number(title: str, key: str = "count", unit: str = ""):
    """Formatter for single-number answers."""
    def _inner(rows: List[Dict], params: Dict[str, Any]) -> Dict[str, Any]:
        clean = _clean_rows(rows)
        val = clean[0].get(key, 0) if clean else 0
        return {
            "card_type": "number",
            "title": title,
            "value": val,
            "unit": unit,
            "summary": f"{val:,} {unit}".strip(),
        }
    return _inner


def _clean_rows(rows: List[Dict]) -> List[Dict]:
    """Make DB rows JSON-safe."""
    out = []
    for r in rows:
        cleaned = {}
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                cleaned[k] = v.isoformat()
            elif hasattr(v, "as_tuple"):
                cleaned[k] = float(v)
            elif v is None:
                cleaned[k] = None
            else:
                cleaned[k] = v
        out.append(cleaned)
    return out


# ── Query registry ───────────────────────────────────────────

SMART_QUERIES: List[SmartQuery] = []


def _register(sq: SmartQuery):
    SMART_QUERIES.append(sq)
    return sq


# ┌──────────────────────────────────────────────────────────┐
# │  1. VM STATUS SUMMARY                                    │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="vm_status_summary",
    title="VM Status Summary",
    pattern=re.compile(
        r"\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:status|state|summary|overview|breakdown)\b"
        r"|\b(?:status|state|summary|overview)\b.*\b(?:vm|vms|server|servers|instance|instances)\b",
        re.I,
    ),
    sql="""
        SELECT status, vm_state, count(*) as count
        FROM servers s
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        GROUP BY status, vm_state
        ORDER BY count DESC
    """,
    formatter=_fmt_table(
        "VM Status Summary",
        lambda rows, _: f"{sum(r.get('count',0) for r in rows):,} VMs across {len(rows)} status combinations",
        [
            {"key": "status", "label": "Status"},
            {"key": "vm_state", "label": "VM State"},
            {"key": "count", "label": "Count"},
        ],
    ),
    description="Breakdown of all VMs by status and vm_state",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  2. POWERED OFF / SHUTOFF VMs                            │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="powered_off_vms",
    title="Powered-Off VMs",
    pattern=re.compile(
        r"\b(?:powered?\s*off|shut\s*off|stopped|inactive)\b.*\b(?:vm|vms|server|servers|instance|instances)\b"
        r"|\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:powered?\s*off|shut\s*off|stopped|inactive)\b",
        re.I,
    ),
    sql="""
        SELECT s.name, s.status, s.vm_state, p.name AS project,
               s.hypervisor_hostname AS host, s.created_at
        FROM servers s
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE (s.status IN ('SHUTOFF','SUSPENDED','PAUSED')
           OR s.vm_state IN ('stopped','suspended','paused'))
          AND (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY s.name
    """,
    formatter=_fmt_table(
        "Powered-Off / Stopped VMs",
        lambda rows, _: f"{len(rows)} VM(s) currently not running",
        [
            {"key": "name", "label": "VM Name"},
            {"key": "status", "label": "Status"},
            {"key": "project", "label": "Project"},
            {"key": "host", "label": "Hypervisor"},
            {"key": "created_at", "label": "Created"},
        ],
    ),
    description="Lists VMs that are powered off, suspended, or paused",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  3. ERROR VMs                                            │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="error_vms",
    title="VMs in Error State",
    pattern=re.compile(
        r"\b(?:error|failed|fault|broken)\b.*\b(?:vm|vms|server|servers|instance|instances)\b"
        r"|\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:error|failed|fault|broken)\b",
        re.I,
    ),
    sql="""
        SELECT s.name, s.status, s.vm_state, p.name AS project,
               s.hypervisor_hostname AS host, s.created_at
        FROM servers s
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE (s.status = 'ERROR' OR s.vm_state = 'error')
          AND (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY s.name
    """,
    formatter=_fmt_table(
        "VMs in Error State",
        lambda rows, _: f"{len(rows)} VM(s) in ERROR state" if rows else "No VMs in error state ✅",
        [
            {"key": "name", "label": "VM Name"},
            {"key": "status", "label": "Status"},
            {"key": "project", "label": "Project"},
            {"key": "host", "label": "Hypervisor"},
            {"key": "created_at", "label": "Created"},
        ],
    ),
    description="Lists VMs in ERROR or failed state",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  4. VM COUNT                                             │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="vm_count",
    title="Total VM Count",
    pattern=re.compile(
        r"\bhow\s+many\b.*\b(?:vm|vms|server|servers|instance|instances)\b"
        r"|\b(?:count|total|number)\s+(?:of\s+)?(?:vm|vms|server|servers|instance|instances)\b",
        re.I,
    ),
    sql="""
        SELECT count(*) AS count
        FROM servers s
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
    """,
    formatter=_fmt_number("Total VMs", "count", "VMs"),
    description="Count of all VMs in the platform",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  5. VMs PER PROJECT / TENANT                             │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="vms_per_project",
    title="VMs per Project",
    pattern=re.compile(
        r"\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:per|by|each|every)\s+(?:project|tenant|org)\b"
        r"|\b(?:project|tenant|org)\b.*\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:count|how\s+many)\b",
        re.I,
    ),
    sql="""
        SELECT p.name AS project, d.name AS domain, count(s.id) AS vm_count
        FROM projects p
        LEFT JOIN domains d ON d.id = p.domain_id
        LEFT JOIN servers s ON s.project_id = p.id
        WHERE (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        GROUP BY p.name, d.name
        HAVING count(s.id) > 0
        ORDER BY vm_count DESC
    """,
    formatter=_fmt_table(
        "VMs per Project",
        lambda rows, _: f"{len(rows)} project(s) with VMs, {sum(r.get('vm_count',0) for r in rows):,} total",
        [
            {"key": "project", "label": "Project"},
            {"key": "domain", "label": "Domain"},
            {"key": "vm_count", "label": "VM Count"},
        ],
    ),
    description="Number of VMs in each project/tenant",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  6. HYPERVISOR CAPACITY                                  │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="hypervisor_capacity",
    title="Hypervisor Capacity",
    pattern=re.compile(
        r"\b(?:hypervisor|host|compute)\b.*\b(?:capacity|usage|utilization|load|headroom|free|available)\b"
        r"|\b(?:capacity|usage|utilization|load|headroom)\b.*\b(?:hypervisor|host|compute)\b",
        re.I,
    ),
    sql="""
        SELECT hostname, hypervisor_type, state, status,
               vcpus, memory_mb, local_gb,
               (SELECT count(*) FROM servers s WHERE s.hypervisor_hostname = h.hostname) AS vm_count
        FROM hypervisors h
        ORDER BY hostname
    """,
    formatter=_fmt_table(
        "Hypervisor Capacity",
        lambda rows, _: (
            f"{len(rows)} hypervisor(s) — "
            f"{sum(r.get('vcpus',0) for r in rows):,} vCPUs, "
            f"{sum(r.get('memory_mb',0) for r in rows)//1024:,} GB RAM, "
            f"{sum(r.get('local_gb',0) for r in rows):,} GB storage"
        ),
        [
            {"key": "hostname", "label": "Hostname"},
            {"key": "state", "label": "State"},
            {"key": "vcpus", "label": "vCPUs"},
            {"key": "memory_mb", "label": "RAM (MB)"},
            {"key": "local_gb", "label": "Disk (GB)"},
            {"key": "vm_count", "label": "VMs"},
        ],
    ),
    description="Hypervisor resource capacity and current load",
    category="capacity",
))


# ┌──────────────────────────────────────────────────────────┐
# │  7. QUOTA FOR SPECIFIC TENANT (before generic quota)     │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="quota_for_tenant",
    title="Resource Usage for Tenant",
    pattern=re.compile(
        r"\b(?:quota|quotas|usage|limits?|resources?)\b.*\b(?:for|of|in)\s+(?P<tenant>[A-Za-z0-9_. -]{2,40})",
        re.I,
    ),
    sql="""
        WITH latest AS (
            SELECT DISTINCT ON (project_id)
                project_name, domain,
                vcpus_used, ram_used_mb, instances_used,
                volumes_used, storage_used_gb, snapshots_used,
                floating_ips_used, networks_used, ports_used,
                security_groups_used,
                collected_at
            FROM metering_quotas
            ORDER BY project_id, collected_at DESC
        ),
        live AS (
            SELECT p.name AS project_name, d.name AS domain,
                   (SELECT COALESCE(SUM(f.vcpus),0) FROM servers s LEFT JOIN flavors f ON f.id = s.flavor_id WHERE s.project_id = p.id) AS vcpus_used,
                   (SELECT COALESCE(SUM(f.ram_mb),0) FROM servers s LEFT JOIN flavors f ON f.id = s.flavor_id WHERE s.project_id = p.id) AS ram_used_mb,
                   (SELECT count(*) FROM servers WHERE project_id = p.id) AS instances_used,
                   (SELECT count(*) FROM volumes WHERE project_id = p.id) AS volumes_used,
                   (SELECT COALESCE(SUM(size_gb),0) FROM volumes WHERE project_id = p.id) AS storage_used_gb,
                   (SELECT count(*) FROM snapshots WHERE project_id = p.id) AS snapshots_used,
                   (SELECT count(*) FROM floating_ips WHERE project_id = p.id) AS floating_ips_used,
                   (SELECT count(*) FROM networks WHERE project_id = p.id) AS networks_used,
                   (SELECT count(*) FROM ports WHERE project_id = p.id) AS ports_used,
                   (SELECT count(*) FROM security_groups WHERE project_id = p.id) AS security_groups_used,
                   now() AS collected_at
            FROM projects p
            LEFT JOIN domains d ON d.id = p.domain_id
        ),
        combined AS (
            SELECT * FROM latest WHERE EXISTS (SELECT 1 FROM latest)
            UNION ALL
            SELECT * FROM live WHERE NOT EXISTS (SELECT 1 FROM latest)
        )
        SELECT * FROM combined
        WHERE (lower(project_name) LIKE lower(%(tenant)s)
           OR lower(domain) LIKE lower(%(tenant)s))
          AND (%(scope_tenant)s IS NULL OR project_name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR domain = %(scope_domain)s)
        ORDER BY project_name
    """,
    formatter=_fmt_table(
        "Resource Usage for Tenant",
        lambda rows, p: (
            f"Resource usage for \"{p.get('tenant','?')}\" — {len(rows)} project(s), "
            f"{sum(r.get('instances_used',0) for r in rows):,} VMs, "
            f"{sum(r.get('vcpus_used',0) for r in rows):,} vCPUs"
            if rows else f"No projects found matching \"{p.get('tenant','?')}\""
        ),
        [
            {"key": "project_name", "label": "Project"},
            {"key": "domain", "label": "Domain"},
            {"key": "instances_used", "label": "VMs"},
            {"key": "vcpus_used", "label": "vCPUs"},
            {"key": "ram_used_mb", "label": "RAM (MB)"},
            {"key": "volumes_used", "label": "Volumes"},
            {"key": "storage_used_gb", "label": "Storage (GB)"},
            {"key": "floating_ips_used", "label": "Floating IPs"},
        ],
    ),
    description="Resource usage for a specific tenant/project/domain",
    category="quota",
    param_keys=["tenant"],
))


# ┌──────────────────────────────────────────────────────────┐
# │  8. QUOTA USAGE (all tenants)                            │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="quota_usage_all",
    title="Resource Usage Overview",
    pattern=re.compile(
        r"\b(?:quota|quotas)\b.*\b(?:usage|used|overview|all|summary)\b"
        r"|\b(?:usage|utilization)\b.*\b(?:quota|quotas|all|overview)\b",
        re.I,
    ),
    sql="""
        WITH latest AS (
            SELECT DISTINCT ON (project_id)
                project_name, domain,
                vcpus_used, ram_used_mb, instances_used,
                volumes_used, storage_used_gb
            FROM metering_quotas
            ORDER BY project_id, collected_at DESC
        ),
        live AS (
            SELECT p.name AS project_name, d.name AS domain,
                   (SELECT COALESCE(SUM(f.vcpus),0) FROM servers s LEFT JOIN flavors f ON f.id = s.flavor_id WHERE s.project_id = p.id) AS vcpus_used,
                   (SELECT COALESCE(SUM(f.ram_mb),0) FROM servers s LEFT JOIN flavors f ON f.id = s.flavor_id WHERE s.project_id = p.id) AS ram_used_mb,
                   (SELECT count(*) FROM servers WHERE project_id = p.id) AS instances_used,
                   (SELECT count(*) FROM volumes WHERE project_id = p.id) AS volumes_used,
                   (SELECT COALESCE(SUM(size_gb),0) FROM volumes WHERE project_id = p.id) AS storage_used_gb
            FROM projects p
            LEFT JOIN domains d ON d.id = p.domain_id
        ),
        combined AS (
            SELECT * FROM latest WHERE EXISTS (SELECT 1 FROM latest)
            UNION ALL
            SELECT * FROM live WHERE NOT EXISTS (SELECT 1 FROM latest)
        )
        SELECT * FROM combined
        WHERE (instances_used > 0 OR volumes_used > 0)
          AND (%(scope_tenant)s IS NULL OR project_name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR domain = %(scope_domain)s)
        ORDER BY instances_used DESC, project_name
    """,
    formatter=_fmt_table(
        "Resource Usage Overview",
        lambda rows, _: (
            f"{len(rows)} project(s) with resources — "
            f"{sum(r.get('instances_used',0) for r in rows):,} VMs, "
            f"{sum(r.get('vcpus_used',0) for r in rows):,} vCPUs, "
            f"{sum(r.get('volumes_used',0) for r in rows):,} volumes"
            if rows else "No projects with active resources"
        ),
        [
            {"key": "project_name", "label": "Project"},
            {"key": "domain", "label": "Domain"},
            {"key": "instances_used", "label": "VMs"},
            {"key": "vcpus_used", "label": "vCPUs"},
            {"key": "ram_used_mb", "label": "RAM (MB)"},
            {"key": "volumes_used", "label": "Volumes"},
            {"key": "storage_used_gb", "label": "Storage (GB)"},
        ],
    ),
    description="Resource usage across all tenants",
    category="quota",
))


# ┌──────────────────────────────────────────────────────────┐
# │  9. VOLUME SUMMARY                                      │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="volume_summary",
    title="Volume Summary",
    pattern=re.compile(
        r"\b(?:volume|volumes|storage|disk)\b.*\b(?:summary|overview|list|all|status)\b"
        r"|\b(?:all|list|show)\b.*\b(?:volume|volumes)\b",
        re.I,
    ),
    sql="""
        SELECT v.name, v.status, v.size_gb, v.volume_type, v.bootable,
               p.name AS project, v.created_at
        FROM volumes v
        LEFT JOIN projects p ON p.id = v.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY v.name
    """,
    formatter=_fmt_table(
        "Volume Summary",
        lambda rows, _: (
            f"{len(rows)} volume(s), {sum(r.get('size_gb',0) for r in rows):,} GB total"
        ),
        [
            {"key": "name", "label": "Name"},
            {"key": "status", "label": "Status"},
            {"key": "size_gb", "label": "Size (GB)"},
            {"key": "volume_type", "label": "Type"},
            {"key": "project", "label": "Project"},
            {"key": "bootable", "label": "Bootable"},
        ],
    ),
    description="Overview of all volumes with status & size",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  10. UNATTACHED / ORPHAN VOLUMES                        │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="orphan_volumes",
    title="Orphan Volumes",
    pattern=re.compile(
        r"\b(?:orphan|unattached|detached|unused|available)\b.*\b(?:volume|volumes|disk|storage)\b"
        r"|\b(?:volume|volumes|disk)\b.*\b(?:orphan|unattached|detached|unused|available)\b",
        re.I,
    ),
    sql="""
        SELECT v.name, v.size_gb, v.volume_type, p.name AS project, v.created_at
        FROM volumes v
        LEFT JOIN projects p ON p.id = v.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE v.status = 'available'
          AND (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY v.size_gb DESC
    """,
    formatter=_fmt_table(
        "Unattached / Orphan Volumes",
        lambda rows, _: (
            f"{len(rows)} unattached volume(s), {sum(r.get('size_gb',0) for r in rows):,} GB wasted"
            if rows else "No orphan volumes found ✅"
        ),
        [
            {"key": "name", "label": "Name"},
            {"key": "size_gb", "label": "Size (GB)"},
            {"key": "volume_type", "label": "Type"},
            {"key": "project", "label": "Project"},
            {"key": "created_at", "label": "Created"},
        ],
    ),
    description="Volumes not attached to any VM (available status)",
    category="operations",
))


# ┌──────────────────────────────────────────────────────────┐
# │  11. ROLES FOR SPECIFIC USER (before generic role_assignments) │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="roles_for_user",
    title="Roles for User",
    pattern=re.compile(
        r"\b(?:roles?|permissions?|access)\b.*\b(?:for|of)\s+(?:user\s+)?(?P<user>[A-Za-z0-9_.@-]{2,60})",
        re.I,
    ),
    sql="""
        SELECT user_name, role_name, project_name, domain_name, inherited
        FROM role_assignments
        WHERE lower(user_name) LIKE lower(%(user)s)
          AND (%(scope_tenant)s IS NULL OR project_name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR domain_name = %(scope_domain)s)
        ORDER BY domain_name, project_name
    """,
    formatter=_fmt_table(
        "Roles for User",
        lambda rows, p: (
            f"{len(rows)} role(s) for \"{p.get('user','?')}\""
            if rows else f"No roles found for \"{p.get('user','?')}\""
        ),
        [
            {"key": "role_name", "label": "Role"},
            {"key": "project_name", "label": "Project"},
            {"key": "domain_name", "label": "Domain"},
            {"key": "inherited", "label": "Inherited"},
        ],
    ),
    description="Show all roles for a specific user",
    category="security",
    param_keys=["user"],
))


# ┌──────────────────────────────────────────────────────────┐
# │  12. ROLE ASSIGNMENTS (generic)                         │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="role_assignments",
    title="Role Assignments",
    pattern=re.compile(
        r"\b(?:role|roles)\b.*\b(?:assignment|assignments|mapping|who\s+has|users?)\b"
        r"|\bwho\s+has\s+(?:access|role|admin)\b"
        r"|\b(?:rbac|access)\b.*\b(?:overview|summary|list|audit)\b",
        re.I,
    ),
    sql="""
        SELECT user_name, role_name, project_name, domain_name, inherited
        FROM role_assignments
        WHERE user_name IS NOT NULL AND user_name != ''
          AND (%(scope_tenant)s IS NULL OR project_name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR domain_name = %(scope_domain)s)
        ORDER BY domain_name, project_name, user_name
        LIMIT 100
    """,
    formatter=_fmt_table(
        "Role Assignments",
        lambda rows, _: f"{len(rows)} role assignment(s) (top 100)",
        [
            {"key": "user_name", "label": "User"},
            {"key": "role_name", "label": "Role"},
            {"key": "project_name", "label": "Project"},
            {"key": "domain_name", "label": "Domain"},
            {"key": "inherited", "label": "Inherited"},
        ],
    ),
    description="User-to-role assignment overview",
    category="security",
))


# ┌──────────────────────────────────────────────────────────┐
# │  13. PROJECT / TENANT COUNT                             │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="project_count",
    title="Project Count",
    pattern=re.compile(
        r"\bhow\s+many\b.*\b(?:project|projects|tenant|tenants)\b"
        r"|\b(?:count|total|number)\s+(?:of\s+)?(?:project|projects|tenant|tenants)\b",
        re.I,
    ),
    sql="""
        SELECT count(*) AS count
        FROM projects p
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
    """,
    formatter=_fmt_number("Total Projects", "count", "projects"),
    description="Count of all projects/tenants",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  14. DOMAIN OVERVIEW                                    │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="domain_overview",
    title="Domain Overview",
    pattern=re.compile(
        r"\b(?:domain|domains)\b.*\b(?:overview|summary|list|all|count)\b"
        r"|\b(?:all|list|show)\b.*\b(?:domain|domains)\b"
        r"|\bhow\s+many\b.*\b(?:domain|domains)\b",
        re.I,
    ),
    sql="""
        SELECT d.name AS domain,
               (SELECT count(*) FROM projects p WHERE p.domain_id = d.id) AS projects,
               (SELECT count(*) FROM role_assignments ra WHERE ra.domain_id = d.id) AS role_assignments
        FROM domains d
        ORDER BY d.name
    """,
    formatter=_fmt_table(
        "Domain Overview",
        lambda rows, _: f"{len(rows)} domain(s), {sum(r.get('projects',0) for r in rows):,} total projects",
        [
            {"key": "domain", "label": "Domain"},
            {"key": "projects", "label": "Projects"},
            {"key": "role_assignments", "label": "Role Assignments"},
        ],
    ),
    description="All domains with project and role counts",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  15. NETWORK OVERVIEW                                   │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="network_overview",
    title="Network Overview",
    pattern=re.compile(
        r"\b(?:network|networks)\b.*\b(?:overview|summary|list|all|topology)\b"
        r"|\b(?:all|list|show)\b.*\b(?:network|networks)\b"
        r"|\bhow\s+many\b.*\b(?:network|networks)\b",
        re.I,
    ),
    sql="""
        SELECT n.name, n.is_shared, n.is_external,
               p.name AS project,
               (SELECT count(*) FROM subnets sub WHERE sub.network_id = n.id) AS subnet_count,
               (SELECT count(*) FROM ports pt WHERE pt.network_id = n.id) AS port_count
        FROM networks n
        LEFT JOIN projects p ON p.id = n.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY n.name
    """,
    formatter=_fmt_table(
        "Network Overview",
        lambda rows, _: f"{len(rows)} network(s), {sum(r.get('subnet_count',0) for r in rows):,} subnets",
        [
            {"key": "name", "label": "Network"},
            {"key": "project", "label": "Project"},
            {"key": "is_shared", "label": "Shared"},
            {"key": "is_external", "label": "External"},
            {"key": "subnet_count", "label": "Subnets"},
            {"key": "port_count", "label": "Ports"},
        ],
    ),
    description="Networks with subnet and port counts",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  16. FLOATING IPs                                       │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="floating_ip_overview",
    title="Floating IPs",
    pattern=re.compile(
        r"\b(?:floating|float)\b.*\b(?:ip|ips)\b"
        r"|\bfip|fips\b"
        r"|\b(?:public|external)\b.*\bip\b.*\b(?:list|all|overview|summary)\b",
        re.I,
    ),
    sql="""
        SELECT floating_ip, fixed_ip, status,
               p.name AS project, port_id
        FROM floating_ips f
        LEFT JOIN projects p ON p.id = f.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY floating_ip
    """,
    formatter=_fmt_table(
        "Floating IPs",
        lambda rows, _: (
            f"{len(rows)} floating IP(s), "
            f"{sum(1 for r in rows if r.get('status')=='ACTIVE'):,} active"
            if rows else "No floating IPs found"
        ),
        [
            {"key": "floating_ip", "label": "Floating IP"},
            {"key": "fixed_ip", "label": "Fixed IP"},
            {"key": "status", "label": "Status"},
            {"key": "project", "label": "Project"},
        ],
    ),
    description="Floating IP list with status",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  17. IMAGE OVERVIEW                                     │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="image_overview",
    title="Images Overview",
    pattern=re.compile(
        r"\b(?:image|images|glance)\b.*\b(?:overview|summary|list|all|status)\b"
        r"|\b(?:all|list|show)\b.*\b(?:image|images)\b"
        r"|\bhow\s+many\b.*\b(?:image|images)\b",
        re.I,
    ),
    sql="""
        SELECT name, status, visibility,
               ROUND(size_bytes / 1073741824.0, 2) AS size_gb,
               disk_format, created_at
        FROM images
        ORDER BY name
    """,
    formatter=_fmt_table(
        "Images Overview",
        lambda rows, _: f"{len(rows)} image(s), {sum(r.get('size_gb',0) or 0 for r in rows):.1f} GB total",
        [
            {"key": "name", "label": "Name"},
            {"key": "status", "label": "Status"},
            {"key": "visibility", "label": "Visibility"},
            {"key": "size_gb", "label": "Size (GB)"},
            {"key": "disk_format", "label": "Format"},
            {"key": "created_at", "label": "Created"},
        ],
    ),
    description="All Glance images with size and status",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  18. SNAPSHOT OVERVIEW                                  │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="snapshot_overview",
    title="Snapshot Overview",
    pattern=re.compile(
        r"\b(?:snapshot|snapshots)\b.*\b(?:overview|summary|list|all|status|compliance)\b"
        r"|\b(?:all|list|show)\b.*\b(?:snapshot|snapshots)\b"
        r"|\bhow\s+many\b.*\b(?:snapshot|snapshots)\b",
        re.I,
    ),
    sql="""
        SELECT name, status, size_gb, project_name, domain_name, created_at
        FROM snapshots
        WHERE (%(scope_tenant)s IS NULL OR project_name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR domain_name = %(scope_domain)s)
        ORDER BY created_at DESC
        LIMIT 50
    """,
    formatter=_fmt_table(
        "Snapshot Overview",
        lambda rows, _: f"{len(rows)} snapshot(s) (latest 50)",
        [
            {"key": "name", "label": "Name"},
            {"key": "status", "label": "Status"},
            {"key": "size_gb", "label": "Size (GB)"},
            {"key": "project_name", "label": "Project"},
            {"key": "created_at", "label": "Created"},
        ],
    ),
    description="Recent snapshots with status and size",
    category="operations",
))


# ┌──────────────────────────────────────────────────────────┐
# │  19. DRIFT EVENTS                                      │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="drift_summary",
    title="Drift Events Summary",
    pattern=re.compile(
        r"\b(?:drift|config.?drift)\b.*\b(?:event|events|summary|recent|latest|overview)\b"
        r"|\b(?:recent|latest)\b.*\b(?:drift)\b",
        re.I,
    ),
    sql="""
        SELECT severity, count(*) AS count,
               count(*) FILTER (WHERE NOT acknowledged) AS unacknowledged
        FROM drift_events
        GROUP BY severity
        ORDER BY
            CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                          WHEN 'medium' THEN 3 ELSE 4 END
    """,
    formatter=_fmt_table(
        "Drift Events by Severity",
        lambda rows, _: (
            f"{sum(r.get('count',0) for r in rows):,} drift event(s), "
            f"{sum(r.get('unacknowledged',0) for r in rows):,} unacknowledged"
            if rows else "No drift events detected ✅"
        ),
        [
            {"key": "severity", "label": "Severity"},
            {"key": "count", "label": "Total"},
            {"key": "unacknowledged", "label": "Unacknowledged"},
        ],
    ),
    description="Drift events grouped by severity with unacknowledged counts",
    category="operations",
))


# ┌──────────────────────────────────────────────────────────┐
# │  20. RECENT ACTIVITY (last 24h)                         │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="recent_activity",
    title="Recent Activity",
    pattern=re.compile(
        r"\b(?:recent|latest|last)\b.*\b(?:activity|action|actions|changes|events|log)\b"
        r"|\bwhat\s+(?:happened|changed)\b",
        re.I,
    ),
    sql="""
        SELECT timestamp, actor, action, resource_type, resource_name, result
        FROM activity_log
        ORDER BY timestamp DESC
        LIMIT 25
    """,
    formatter=_fmt_table(
        "Recent Activity (latest 25)",
        lambda rows, _: f"{len(rows)} recent action(s)",
        [
            {"key": "timestamp", "label": "When"},
            {"key": "actor", "label": "Who"},
            {"key": "action", "label": "Action"},
            {"key": "resource_type", "label": "Resource Type"},
            {"key": "resource_name", "label": "Resource"},
            {"key": "result", "label": "Result"},
        ],
    ),
    description="Most recent platform activity and changes",
    category="operations",
))


# ┌──────────────────────────────────────────────────────────┐
# │  21. FLAVOR USAGE                                       │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="flavor_usage",
    title="Flavor Usage",
    pattern=re.compile(
        r"\b(?:flavor|flavors|instance.?type)\b.*\b(?:usage|used|popular|list|all|overview)\b"
        r"|\b(?:all|list|show|which|what)\b.*\b(?:flavor|flavors|instance.?type)\b",
        re.I,
    ),
    sql="""
        SELECT f.name AS flavor, f.vcpus, f.ram_mb, f.disk_gb,
               count(s.id) AS vm_count
        FROM flavors f
        LEFT JOIN servers s ON s.flavor_id = f.id
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        GROUP BY f.id, f.name, f.vcpus, f.ram_mb, f.disk_gb
        ORDER BY vm_count DESC, f.name
    """,
    formatter=_fmt_table(
        "Flavor Usage",
        lambda rows, _: (
            f"{len(rows)} flavor(s), "
            f"{sum(r.get('vm_count',0) for r in rows):,} VM(s) using them"
        ),
        [
            {"key": "flavor", "label": "Flavor"},
            {"key": "vcpus", "label": "vCPUs"},
            {"key": "ram_mb", "label": "RAM (MB)"},
            {"key": "disk_gb", "label": "Disk (GB)"},
            {"key": "vm_count", "label": "VMs Using"},
        ],
    ),
    description="Flavor definitions and how many VMs use each",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  22. SECURITY GROUPS                                    │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="security_group_overview",
    title="Security Groups",
    pattern=re.compile(
        r"\b(?:security.?group|sg)\b.*\b(?:overview|summary|list|all|audit|count)\b"
        r"|\b(?:all|list|show)\b.*\b(?:security.?group|sg)\b"
        r"|\bhow\s+many\b.*\b(?:security.?group|sg)\b",
        re.I,
    ),
    sql="""
        SELECT name, description, project_name, domain_name, tenant_name
        FROM security_groups
        WHERE (%(scope_tenant)s IS NULL OR project_name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR domain_name = %(scope_domain)s)
        ORDER BY domain_name, project_name, name
    """,
    formatter=_fmt_table(
        "Security Groups",
        lambda rows, _: f"{len(rows)} security group(s)",
        [
            {"key": "name", "label": "Name"},
            {"key": "description", "label": "Description"},
            {"key": "project_name", "label": "Project"},
            {"key": "domain_name", "label": "Domain"},
        ],
    ),
    description="All security groups with project/domain",
    category="security",
))


# ┌──────────────────────────────────────────────────────────┐
# │  23. ROUTER OVERVIEW                                    │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="router_overview",
    title="Router Overview",
    pattern=re.compile(
        r"\b(?:router|routers)\b.*\b(?:overview|summary|list|all)\b"
        r"|\b(?:all|list|show)\b.*\b(?:router|routers)\b"
        r"|\bhow\s+many\b.*\b(?:router|routers)\b",
        re.I,
    ),
    sql="""
        SELECT r.name, p.name AS project,
               n.name AS external_network
        FROM routers r
        LEFT JOIN projects p ON p.id = r.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        LEFT JOIN networks n ON n.id = r.external_net_id
        WHERE (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY r.name
    """,
    formatter=_fmt_table(
        "Router Overview",
        lambda rows, _: f"{len(rows)} router(s)",
        [
            {"key": "name", "label": "Router"},
            {"key": "project", "label": "Project"},
            {"key": "external_network", "label": "External Network"},
        ],
    ),
    description="All routers with project and external network",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  24. RESOURCE EFFICIENCY                                │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="efficiency_overview",
    title="Resource Efficiency",
    pattern=re.compile(
        r"\b(?:efficiency|efficient|inefficient|idle|waste|wasted|underutilized)\b.*\b(?:vm|vms|resource|resources|overview|summary)\b"
        r"|\b(?:vm|vms|resource|resources)\b.*\b(?:efficiency|idle|waste|underutilized)\b",
        re.I,
    ),
    sql="""
        SELECT vm_name, project_name, domain,
               cpu_efficiency, ram_efficiency, storage_efficiency,
               overall_score, classification, recommendation
        FROM metering_efficiency
        WHERE (%(scope_tenant)s IS NULL OR project_name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR domain = %(scope_domain)s)
        ORDER BY overall_score ASC
        LIMIT 25
    """,
    formatter=_fmt_table(
        "Resource Efficiency (Bottom 25)",
        lambda rows, _: (
            f"{len(rows)} VM(s) analysed, "
            f"{sum(1 for r in rows if r.get('classification') in ('idle','underutilized')):,} idle/underutilized"
            if rows else "No efficiency data collected yet"
        ),
        [
            {"key": "vm_name", "label": "VM"},
            {"key": "project_name", "label": "Project"},
            {"key": "overall_score", "label": "Score"},
            {"key": "classification", "label": "Class"},
            {"key": "recommendation", "label": "Recommendation"},
        ],
    ),
    description="Least efficient VMs by CPU/RAM/storage utilization",
    category="operations",
))


# ┌──────────────────────────────────────────────────────────┐
# │  25. VMs ON A SPECIFIC HYPERVISOR                       │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="vms_on_host",
    title="VMs on Hypervisor",
    pattern=re.compile(
        r"\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:on|running\s+on|hosted\s+on)\s+(?:host\s+|hypervisor\s+)?(?P<host>[A-Za-z0-9_.-]{2,60})",
        re.I,
    ),
    sql="""
        SELECT s.name, s.status, s.vm_state, p.name AS project, s.created_at
        FROM servers s
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE lower(s.hypervisor_hostname) LIKE lower(%(host)s)
          AND (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY s.name
    """,
    formatter=_fmt_table(
        "VMs on Hypervisor",
        lambda rows, p: (
            f"{len(rows)} VM(s) on \"{p.get('host','?')}\""
            if rows else f"No VMs found on \"{p.get('host','?')}\""
        ),
        [
            {"key": "name", "label": "VM Name"},
            {"key": "status", "label": "Status"},
            {"key": "vm_state", "label": "State"},
            {"key": "project", "label": "Project"},
            {"key": "created_at", "label": "Created"},
        ],
    ),
    description="List VMs running on a specific hypervisor host",
    category="infrastructure",
    param_keys=["host"],
))


# ┌──────────────────────────────────────────────────────────┐
# │  26. PLATFORM OVERVIEW / DASHBOARD                      │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="platform_overview",
    title="Platform Overview",
    pattern=re.compile(
        r"\b(?:platform|environment|cloud)\b.*\b(?:overview|summary|dashboard|stats|status)\b"
        r"|\b(?:give|show|tell)\b.*\b(?:overview|summary|everything|dashboard)\b"
        r"|\bhow\s+(?:big|large|much)\b.*\b(?:platform|environment|cloud|infrastructure)\b",
        re.I,
    ),
    sql="""
        SELECT
            (SELECT count(*) FROM servers) AS vms,
            (SELECT count(*) FROM hypervisors) AS hypervisors,
            (SELECT count(*) FROM volumes) AS volumes,
            (SELECT count(*) FROM networks) AS networks,
            (SELECT count(*) FROM projects) AS projects,
            (SELECT count(*) FROM domains) AS domains,
            (SELECT count(*) FROM images) AS images,
            (SELECT count(*) FROM routers) AS routers,
            (SELECT count(*) FROM floating_ips) AS floating_ips,
            (SELECT count(*) FROM security_groups) AS security_groups,
            (SELECT count(*) FROM role_assignments) AS role_assignments,
            (SELECT count(*) FROM snapshots) AS snapshots
    """,
    formatter=_fmt_kv(
        "Platform Overview",
        lambda row, _: (
            f"{row.get('vms',0):,} VMs · "
            f"{row.get('hypervisors',0):,} hypervisors · "
            f"{row.get('volumes',0):,} volumes · "
            f"{row.get('networks',0):,} networks · "
            f"{row.get('projects',0):,} projects · "
            f"{row.get('domains',0):,} domains"
        ),
    ),
    description="High-level resource counts across the entire platform",
    category="general",
))


# ── Execution engine ─────────────────────────────────────────

def execute_smart_query(
    question: str,
    conn,
    scope_tenant: Optional[str] = None,
    scope_domain: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Try each registered SmartQuery pattern against the question.
    First match wins — its SQL is executed and the formatter shapes
    the response.

    *scope_tenant* / *scope_domain* — optional project/domain filters.
    When provided the query SQL is expected to honour them via
    ``(%(scope_tenant)s IS NULL OR …)`` conditions.  Queries that do
    not reference these params simply ignore them (dict-style params).

    Returns None if no pattern matches.
    """
    for sq in SMART_QUERIES:
        m = sq.pattern.search(question)
        if not m:
            continue

        # Extract named groups as SQL params
        params: Dict[str, Any] = {}
        for key in sq.param_keys:
            val = m.group(key)
            if val:
                # Wrap in % for LIKE matching
                params[key] = f"%{val.strip()}%"

        # Inject scope params (always present — NULL = no filter)
        params["scope_tenant"] = scope_tenant or None
        params["scope_domain"] = scope_domain or None

        logger.info("Smart query matched: %s (id=%s, params=%s)", sq.title, sq.id, params)

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sq.sql, params)
                rows = [dict(r) for r in cur.fetchall()]

            result = sq.formatter(rows, {k: v.strip('%') if isinstance(v, str) else v for k, v in params.items()})
            result["query_id"] = sq.id
            result["query_title"] = sq.title
            result["description"] = sq.description
            result["category"] = sq.category
            result["matched"] = True
            return result

        except Exception as exc:
            logger.error("Smart query %s failed: %s", sq.id, exc, exc_info=True)
            return {
                "matched": True,
                "query_id": sq.id,
                "query_title": sq.title,
                "card_type": "error",
                "summary": f"Query failed: {exc}",
                "error": str(exc),
            }

    return None


def list_smart_queries() -> List[Dict[str, str]]:
    """Return metadata about all registered smart queries (for help/docs)."""
    return [
        {
            "id": sq.id,
            "title": sq.title,
            "description": sq.description,
            "category": sq.category,
            "example_pattern": sq.pattern.pattern[:100],
        }
        for sq in SMART_QUERIES
    ]
