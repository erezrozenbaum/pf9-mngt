"""
copilot_intents.py — Intent-matching engine for Ops Copilot (Tier 1: Built-in).

Each intent defines:
  • keywords / regex patterns to match against the user's question
  • a confidence-scored matcher
  • a SQL query builder that returns read-only SELECT statements
  • a human-readable answer formatter

Supports:
  • Tenant/project scoping: "… on tenant X", "… for project Y"
  • Host scoping: "… on host Z"
  • VM power-state filtering: powered on, powered off, active, shutoff
  • Fuzzy word matching: handles natural phrasing and word order

All queries are SELECT-only — no writes to production tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class IntentMatch:
    """Result of matching a user question to an intent."""
    intent_key: str
    confidence: float          # 0.0 – 1.0
    display_name: str
    sql: str
    params: tuple = ()
    formatter: Optional[Callable] = None   # rows → answer string
    api_handler: Optional[Callable] = None # question → answer (bypasses SQL)


@dataclass
class IntentDef:
    """Definition of a single intent pattern."""
    key: str
    display_name: str
    keywords: List[str]                # simple keyword hits
    patterns: List[str] = field(default_factory=list)  # regex patterns
    sql: str = ""
    param_extractor: Optional[Callable] = None  # question → tuple of SQL params
    formatter: Optional[Callable] = None
    boost: float = 0.0                 # extra confidence bonus
    # If True, the intent supports tenant/project scoping
    supports_scope: bool = False
    # Base SQL template — uses {scope_join} and {scope_where} placeholders
    sql_template: str = ""
    # If set, called instead of executing SQL (for live API calls)
    api_handler: Optional[Callable] = None


# ---------------------------------------------------------------------------
# Scope extraction helpers
# ---------------------------------------------------------------------------

_SCOPE_PATTERNS = [
    # "on tenant org1", "for tenant org1", "in tenant org1"
    r"(?:on|for|in|of)\s+(?:tenant|project|org)\s+['\"]?(\S+?)['\"]?\s*$",
    r"(?:on|for|in|of)\s+(?:tenant|project|org)\s+['\"]?(\S+?)['\"]?(?:\s|$)",
    r"(?:tenant|project|org)\s*[=:]\s*['\"]?(\S+?)['\"]?(?:\s|$)",
    r"(?:tenant|project)\s+['\"]?([a-zA-Z0-9_.-]+)['\"]?$",
    # Reversed: "for service tenant", "exists for myproject tenant"
    r"(?:on|for|in|of)\s+['\"]?([a-zA-Z0-9_.-]+)['\"]?\s+(?:tenant|project)",
    # Final fallback: "quota of org1", "of ISP2", "for service" (last word)
    r"(?:of|for)\s+['\"]?([a-zA-Z0-9_.-]+)['\"]?\s*$",
]

_HOST_PATTERNS = [
    r"(?:on|for|in)\s+host\s+['\"]?(\S+?)['\"]?\s*$",
    r"(?:on|for|in)\s+host\s+['\"]?(\S+?)['\"]?(?:\s|$)",
    r"host\s*[=:]\s*['\"]?(\S+?)['\"]?(?:\s|$)",
]


def _extract_scope(question: str) -> Optional[str]:
    """Extract tenant/project name from question."""
    q = question.lower().strip()
    for pat in _SCOPE_PATTERNS:
        m = re.search(pat, q)
        if m:
            return m.group(1)
    return None


def _extract_host(question: str) -> Optional[str]:
    """Extract host name from question."""
    q = question.lower().strip()
    for pat in _HOST_PATTERNS:
        m = re.search(pat, q)
        if m:
            return m.group(1)
    return None


def _strip_scope_from_question(question: str) -> str:
    """Remove scope qualifier from question for cleaner matching."""
    q = question
    for pat in _SCOPE_PATTERNS + _HOST_PATTERNS:
        q = re.sub(pat, "", q, flags=re.IGNORECASE)
    return q.strip()


# ---------------------------------------------------------------------------
# Answer formatters
# ---------------------------------------------------------------------------

def _fmt_count(rows, label="items"):
    if not rows:
        return f"No {label} found."
    cnt = rows[0].get("count", rows[0].get("cnt", len(rows)))
    return f"There are **{cnt}** {label}."


def _fmt_count_scoped(rows, label="items", scope=None):
    if not rows:
        return f"No {label} found."
    cnt = rows[0].get("count", rows[0].get("cnt", len(rows)))
    scope_text = f" on **{scope}**" if scope else ""
    return f"There are **{cnt}** {label}{scope_text}."


def _fmt_table(rows, columns=None, limit=25):
    """Format rows as a compact markdown table (up to `limit` rows)."""
    if not rows:
        return "No results found."
    cols = columns or list(rows[0].keys())
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = []
    for r in rows[:limit]:
        vals = []
        for c in cols:
            v = r.get(c, "")
            vals.append(str(v) if v is not None else "–")
        body.append("| " + " | ".join(vals) + " |")
    extra = f"\n\n*… and {len(rows) - limit} more rows.*" if len(rows) > limit else ""
    return f"{header}\n{sep}\n" + "\n".join(body) + extra


def _fmt_kv(rows, key_col="key", val_col="value"):
    if not rows:
        return "No data found."
    lines = [f"- **{r[key_col]}**: {r[val_col]}" for r in rows]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Live Platform9 Quota API helpers
# ---------------------------------------------------------------------------

import logging as _logging
_quota_log = _logging.getLogger("copilot.quota")


def _get_pf9_client():
    """Lazily instantiate a Pf9Client for quota lookups."""
    try:
        from pf9_control import Pf9Client
        return Pf9Client()
    except Exception as exc:
        _quota_log.warning("Cannot create Pf9Client: %s", exc)
        return None


def _fetch_configured_quota(question: str) -> str:
    """
    Fetch the configured quota limits from the live Platform9 API
    for the scoped project, or for all projects if no scope given.
    Returns a formatted markdown answer.
    """
    scope = _extract_scope(question)
    if not scope:
        return (
            "Please specify a tenant/project name.\n\n"
            "**Example:** *quota of service* or *configured quota for myproject*"
        )

    # Resolve project ID from DB
    try:
        from db_pool import get_connection
        from psycopg2.extras import RealDictCursor
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT id, name FROM projects WHERE LOWER(name) LIKE %s LIMIT 5",
                (f"%{scope}%",),
            )
            projects = cur.fetchall()
    except Exception as exc:
        return f"Failed to look up project: {exc}"

    if not projects:
        return f"No project matching **{scope}** found in the database."

    client = _get_pf9_client()
    if not client:
        return (
            "Platform9 API credentials are not configured.\n\n"
            "Set `PF9_AUTH_URL`, `PF9_USERNAME`, and `PF9_PASSWORD` environment variables "
            "to enable live quota lookups."
        )

    results = []
    for proj in projects:
        pid, pname = proj["id"], proj["name"]
        try:
            compute_q = client.get_compute_quotas(pid)
            storage_q = client.get_storage_quotas(pid)
            try:
                network_q = client.get_network_quotas(pid)
            except Exception:
                network_q = {}

            lines = [f"### 📋 Configured quota for **{pname}**\n"]

            def _qval(v):
                """Format a quota value: -1 → unlimited, None → –"""
                if v is None:
                    return "–"
                if isinstance(v, (int, float)) and v < 0:
                    return "unlimited"
                return str(v)

            lines.append("**Compute:**")
            lines.append(f"- Instances (VMs): **{_qval(compute_q.get('instances'))}**")
            lines.append(f"- Cores (vCPUs): **{_qval(compute_q.get('cores'))}**")
            ram = compute_q.get('ram')
            if isinstance(ram, (int, float)) and ram > 0:
                ram_gib = round(ram / 1024, 1)
                lines.append(f"- RAM: **{ram} MB** ({ram_gib} GiB)")
            else:
                lines.append(f"- RAM: **{_qval(ram)}**")
            lines.append(f"- Key Pairs: **{_qval(compute_q.get('key_pairs'))}**")

            if storage_q:
                lines.append("\n**Block Storage:**")
                lines.append(f"- Volumes: **{_qval(storage_q.get('volumes'))}**")
                gigs = storage_q.get('gigabytes')
                lines.append(f"- Storage: **{_qval(gigs)}{' GB' if isinstance(gigs, (int, float)) and gigs >= 0 else ''}**")
                lines.append(f"- Snapshots: **{_qval(storage_q.get('snapshots'))}**")

            if network_q:
                lines.append("\n**Network:**")
                lines.append(f"- Networks: **{_qval(network_q.get('network'))}**")
                lines.append(f"- Subnets: **{_qval(network_q.get('subnet'))}**")
                lines.append(f"- Routers: **{_qval(network_q.get('router'))}**")
                lines.append(f"- Floating IPs: **{_qval(network_q.get('floatingip'))}**")
                lines.append(f"- Ports: **{_qval(network_q.get('port'))}**")
                lines.append(f"- Security Groups: **{_qval(network_q.get('security_group'))}**")

            results.append("\n".join(lines))
        except Exception as exc:
            results.append(f"### ⚠️ **{pname}**\nFailed to fetch quota: {exc}")

    return "\n\n---\n\n".join(results)


def _fetch_quota_and_usage(question: str) -> str:
    """
    Fetch both configured quota limits (from Platform9 API) and actual
    resource usage (from our DB) for the scoped project.
    """
    scope = _extract_scope(question)
    if not scope:
        return (
            "Please specify a tenant/project name.\n\n"
            "**Example:** *quota and usage for service* or *quota vs usage for myproject*"
        )

    # Resolve project from DB and get usage
    try:
        from db_pool import get_connection
        from psycopg2.extras import RealDictCursor
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT id, name FROM projects WHERE LOWER(name) LIKE %s LIMIT 5",
                (f"%{scope}%",),
            )
            projects = cur.fetchall()
    except Exception as exc:
        return f"Failed to look up project: {exc}"

    if not projects:
        return f"No project matching **{scope}** found in the database."

    client = _get_pf9_client()

    results = []
    for proj in projects:
        pid, pname = proj["id"], proj["name"]

        # --- Fetch configured quotas from Platform9 API ---
        compute_q = storage_q = network_q = None
        api_available = False
        if client:
            try:
                compute_q = client.get_compute_quotas(pid)
                storage_q = client.get_storage_quotas(pid)
                try:
                    network_q = client.get_network_quotas(pid)
                except Exception:
                    pass
                api_available = True
            except Exception as exc:
                _quota_log.warning("Quota API call failed for %s: %s", pname, exc)

        # --- Fetch actual usage from DB ---
        try:
            from db_pool import get_connection as gc2
            from psycopg2.extras import RealDictCursor as RDC2
            with gc2() as conn:
                cur = conn.cursor(cursor_factory=RDC2)
                cur.execute("""
                    SELECT
                        (SELECT COUNT(*) FROM servers s WHERE s.project_id = %s) AS vms,
                        (SELECT COALESCE(SUM(f.vcpus), 0) FROM servers s
                         LEFT JOIN flavors f ON f.id = s.flavor_id
                         WHERE s.project_id = %s) AS vcpus,
                        (SELECT COALESCE(SUM(f.ram_mb), 0) FROM servers s
                         LEFT JOIN flavors f ON f.id = s.flavor_id
                         WHERE s.project_id = %s) AS ram_mb,
                        (SELECT COUNT(*) FROM volumes v WHERE v.project_id = %s) AS volumes,
                        (SELECT COALESCE(SUM(v.size_gb), 0) FROM volumes v
                         WHERE v.project_id = %s) AS storage_gb
                """, (pid, pid, pid, pid, pid))
                usage = cur.fetchone()
        except Exception:
            usage = None

        lines = [f"### 📊 Quota & usage for **{pname}**\n"]

        if api_available and compute_q:
            # Build comparison table
            lines.append("| Resource | Configured Limit | Current Usage | % Used |")
            lines.append("| --- | --- | --- | --- |")

            u_vms = usage["vms"] if usage else 0
            u_vcpus = usage["vcpus"] if usage else 0
            u_ram = usage["ram_mb"] if usage else 0
            u_vols = usage["volumes"] if usage else 0
            u_stor = usage["storage_gb"] if usage else 0

            q_instances = compute_q.get("instances", -1)
            q_cores = compute_q.get("cores", -1)
            q_ram = compute_q.get("ram", -1)
            q_vols = storage_q.get("volumes", -1) if storage_q else -1
            q_stor = storage_q.get("gigabytes", -1) if storage_q else -1

            def _pct(used, limit):
                if not limit or limit < 0:
                    return "–"
                p = round(used / limit * 100, 1)
                if p >= 90:
                    return f"🔴 {p}%"
                elif p >= 70:
                    return f"🟡 {p}%"
                return f"🟢 {p}%"

            def _limit_str(v):
                return "unlimited" if v == -1 else str(v)

            lines.append(f"| VMs (instances) | {_limit_str(q_instances)} | {u_vms} | {_pct(u_vms, q_instances)} |")
            lines.append(f"| Cores (vCPUs) | {_limit_str(q_cores)} | {u_vcpus} | {_pct(u_vcpus, q_cores)} |")
            q_ram_disp = f"{_limit_str(q_ram)} MB" if q_ram != -1 else "unlimited"
            lines.append(f"| RAM | {q_ram_disp} | {u_ram} MB | {_pct(u_ram, q_ram)} |")
            lines.append(f"| Volumes | {_limit_str(q_vols)} | {u_vols} | {_pct(u_vols, q_vols)} |")
            q_stor_disp = f"{_limit_str(q_stor)} GB" if q_stor != -1 else "unlimited"
            lines.append(f"| Storage | {q_stor_disp} | {u_stor} GB | {_pct(u_stor, q_stor)} |")

            if network_q:
                lines.append("")
                lines.append("**Network quota limits:** "
                             f"Networks={network_q.get('network', '–')}, "
                             f"Routers={network_q.get('router', '–')}, "
                             f"Floating IPs={network_q.get('floatingip', '–')}, "
                             f"Ports={network_q.get('port', '–')}, "
                             f"Security Groups={network_q.get('security_group', '–')}")
        else:
            # API not available — show usage only with note
            lines.append("⚠️ *Platform9 API not reachable — showing usage only (not configured limits).*\n")
            if usage:
                lines.append("| Resource | Current Usage |")
                lines.append("| --- | --- |")
                lines.append(f"| VMs | {usage['vms']} |")
                lines.append(f"| vCPUs | {usage['vcpus']} |")
                lines.append(f"| RAM | {usage['ram_mb']} MB |")
                lines.append(f"| Volumes | {usage['volumes']} |")
                lines.append(f"| Storage | {usage['storage_gb']} GB |")
            else:
                lines.append("No usage data available.")

        results.append("\n".join(lines))

    return "\n\n---\n\n".join(results)


# ---------------------------------------------------------------------------
# Intent definitions
# ---------------------------------------------------------------------------

INTENTS: List[IntentDef] = [
    # ── Inventory ──────────────────────────────────────────────────────
    IntentDef(
        key="count_vms",
        display_name="VM count",
        keywords=["how many vms", "how many servers", "how many instances",
                  "total vms", "total servers", "number of vms",
                  "count vms", "count servers", "vm count", "server count",
                  "how many virtual machines"],
        patterns=[r"how many (?:vms|servers|instances|virtual machines|vm)",
                  r"(?:count|total|number)\s+(?:of\s+)?(?:vms|servers|instances|vm)"],
        sql="SELECT COUNT(*) AS count FROM servers",
        formatter=lambda rows: _fmt_count(rows, "VMs / servers"),
        supports_scope=True,
        sql_template="""SELECT COUNT(*) AS count FROM servers s
                        LEFT JOIN projects p ON s.project_id = p.id
                        {scope_where}""",
    ),
    IntentDef(
        key="count_hosts",
        display_name="Host count",
        keywords=["how many hosts", "how many hypervisors", "total hosts",
                  "number of hosts", "host count", "hypervisor count"],
        patterns=[r"how many (?:hosts|hypervisors|nodes)"],
        sql="SELECT COUNT(*) AS count FROM hypervisors",
        formatter=lambda rows: _fmt_count(rows, "hypervisors / hosts"),
    ),
    IntentDef(
        key="count_volumes",
        display_name="Volume count",
        keywords=["how many volumes", "total volumes", "volume count",
                  "number of volumes", "count volumes", "disk count"],
        patterns=[r"how many (?:volumes|disks|block)"],
        sql="SELECT COUNT(*) AS count FROM volumes",
        formatter=lambda rows: _fmt_count(rows, "volumes"),
        supports_scope=True,
        sql_template="""SELECT COUNT(*) AS count FROM volumes v
                        LEFT JOIN projects p ON v.project_id = p.id
                        {scope_where}""",
    ),
    IntentDef(
        key="count_networks",
        display_name="Network count",
        keywords=["how many networks", "total networks", "network count"],
        patterns=[r"how many networks"],
        sql="SELECT COUNT(*) AS count FROM networks",
        formatter=lambda rows: _fmt_count(rows, "networks"),
    ),
    IntentDef(
        key="count_images",
        display_name="Image count",
        keywords=["how many images", "image count", "total images"],
        patterns=[r"how many images"],
        sql="SELECT COUNT(*) AS count FROM images",
        formatter=lambda rows: _fmt_count(rows, "images"),
    ),
    IntentDef(
        key="count_projects",
        display_name="Project count",
        keywords=["how many projects", "how many tenants", "project count",
                  "tenant count", "total tenants", "total projects"],
        patterns=[r"how many (?:projects|tenants)"],
        sql="SELECT COUNT(*) AS count FROM projects",
        formatter=lambda rows: _fmt_count(rows, "projects / tenants"),
    ),
    IntentDef(
        key="count_domains",
        display_name="Domain count",
        keywords=["how many domains", "domain count", "total domains"],
        sql="SELECT COUNT(*) AS count FROM domains",
        formatter=lambda rows: _fmt_count(rows, "domains"),
    ),

    # ── VM Power State ─────────────────────────────────────────────────
    IntentDef(
        key="powered_on_vms",
        display_name="Powered on VMs",
        keywords=["powered on", "active vms", "running vms", "powered on vms",
                  "vms that are on", "vms running", "active servers",
                  "online vms", "how many powered on", "how many active",
                  "how many running"],
        patterns=[r"(?:powered?\s*on|active|running)\s*(?:vms?|servers?|instances?)",
                  r"(?:vms?|servers?|instances?)\s+(?:powered?\s*on|active|running|that are (?:on|active|running))",
                  r"how many (?:powered?\s*on|active|running)\s*(?:vms?|servers?|instances?)?",
                  r"(?:show|list|display|count)\s+(?:powered?\s*on|active|running)\s+(?:vms?|servers?)"],
        sql="""SELECT COUNT(*) AS count FROM servers
               WHERE UPPER(status) = 'ACTIVE'""",
        formatter=lambda rows: _fmt_count(rows, "powered-on (active) VMs"),
        supports_scope=True,
        sql_template="""SELECT COUNT(*) AS count FROM servers s
                        LEFT JOIN projects p ON s.project_id = p.id
                        WHERE UPPER(s.status) = 'ACTIVE' {scope_and}""",
        boost=0.1,
    ),
    IntentDef(
        key="powered_off_vms",
        display_name="Powered off VMs",
        keywords=["powered off", "shutoff vms", "stopped vms", "powered off vms",
                  "vms that are off", "offline vms", "shut off",
                  "how many powered off", "how many stopped", "inactive vms"],
        patterns=[r"(?:powered?\s*off|shut\s*off|stopped|inactive)\s*(?:vms?|servers?|instances?)",
                  r"(?:vms?|servers?|instances?)\s+(?:powered?\s*off|shut\s*off|stopped|that are (?:off|stopped))",
                  r"how many (?:powered?\s*off|shut\s*off|stopped)\s*(?:vms?|servers?)?",
                  r"(?:show|list|display|count)\s+(?:powered?\s*off|shut\s*off|stopped)\s+(?:vms?|servers?)"],
        sql="""SELECT COUNT(*) AS count FROM servers
               WHERE UPPER(status) = 'SHUTOFF'""",
        formatter=lambda rows: _fmt_count(rows, "powered-off (shutoff) VMs"),
        supports_scope=True,
        sql_template="""SELECT COUNT(*) AS count FROM servers s
                        LEFT JOIN projects p ON s.project_id = p.id
                        WHERE UPPER(s.status) = 'SHUTOFF' {scope_and}""",
        boost=0.1,
    ),
    IntentDef(
        key="list_powered_on_vms",
        display_name="List powered on VMs",
        keywords=["show powered on vms", "list powered on", "list active vms",
                  "show running vms", "show active vms", "list running vms"],
        patterns=[r"(?:show|list|display)\s+(?:powered?\s*on|active|running)\s+(?:vms?|servers?)",
                  r"(?:show|list|display)\s+(?:vms?|servers?)\s+(?:powered?\s*on|active|running)"],
        sql="""SELECT s.name, s.status, p.name AS project, s.hypervisor_hostname AS host, f.name AS flavor_name
               FROM servers s
               LEFT JOIN projects p ON s.project_id = p.id
               LEFT JOIN flavors f ON f.id = s.flavor_id
               WHERE UPPER(s.status) = 'ACTIVE'
               ORDER BY s.name LIMIT 50""",
        formatter=lambda rows: (
            f"**{len(rows)}** active VM(s):\n\n" +
            _fmt_table(rows, ["name", "status", "project", "host", "flavor_name"])
            if rows else "No active VMs found."
        ),
        supports_scope=True,
        sql_template="""SELECT s.name, s.status, p.name AS project, s.hypervisor_hostname AS host, f.name AS flavor_name
                        FROM servers s
                        LEFT JOIN projects p ON s.project_id = p.id
                        LEFT JOIN flavors f ON f.id = s.flavor_id
                        WHERE UPPER(s.status) = 'ACTIVE' {scope_and}
                        ORDER BY s.name LIMIT 50""",
    ),
    IntentDef(
        key="list_powered_off_vms",
        display_name="List powered off VMs",
        keywords=["show powered off vms", "list powered off", "list shutoff vms",
                  "show stopped vms", "show shutoff vms", "list stopped vms"],
        patterns=[r"(?:show|list|display)\s+(?:powered?\s*off|shut\s*off|stopped)\s+(?:vms?|servers?)",
                  r"(?:show|list|display)\s+(?:vms?|servers?)\s+(?:powered?\s*off|shut\s*off|stopped)"],
        sql="""SELECT s.name, s.status, p.name AS project, s.hypervisor_hostname AS host, f.name AS flavor_name
               FROM servers s
               LEFT JOIN projects p ON s.project_id = p.id
               LEFT JOIN flavors f ON f.id = s.flavor_id
               WHERE UPPER(s.status) = 'SHUTOFF'
               ORDER BY s.name LIMIT 50""",
        formatter=lambda rows: (
            f"**{len(rows)}** powered-off VM(s):\n\n" +
            _fmt_table(rows, ["name", "status", "project", "host", "flavor_name"])
            if rows else "No powered-off VMs found."
        ),
        supports_scope=True,
        sql_template="""SELECT s.name, s.status, p.name AS project, s.hypervisor_hostname AS host, f.name AS flavor_name
                        FROM servers s
                        LEFT JOIN projects p ON s.project_id = p.id
                        LEFT JOIN flavors f ON f.id = s.flavor_id
                        WHERE UPPER(s.status) = 'SHUTOFF' {scope_and}
                        ORDER BY s.name LIMIT 50""",
    ),

    # ── Scoped VM Queries ──────────────────────────────────────────────
    IntentDef(
        key="vms_on_tenant",
        display_name="VMs on tenant",
        keywords=["vms on tenant", "vms in project", "vms for tenant",
                  "servers on tenant", "servers in project", "tenant vms",
                  "project vms", "vms for project"],
        patterns=[r"(?:vms?|servers?|instances?)\s+(?:on|in|for|of)\s+(?:tenant|project|org)\s+\S+",
                  r"(?:show|list|how many)\s+(?:vms?|servers?).+(?:tenant|project|org)"],
        sql="""SELECT s.name, s.status, s.vm_state, p.name AS project, s.hypervisor_hostname AS host, f.name AS flavor_name
               FROM servers s
               LEFT JOIN projects p ON s.project_id = p.id
               LEFT JOIN flavors f ON f.id = s.flavor_id
               ORDER BY s.name LIMIT 50""",
        formatter=lambda rows: (
            f"**{len(rows)}** VM(s) found:\n\n" +
            _fmt_table(rows, ["name", "status", "project", "host", "flavor_name"])
            if rows else "No VMs found for that tenant/project."
        ),
        supports_scope=True,
        sql_template="""SELECT s.name, s.status, s.vm_state, p.name AS project, s.hypervisor_hostname AS host, f.name AS flavor_name
                        FROM servers s
                        LEFT JOIN projects p ON s.project_id = p.id
                        LEFT JOIN flavors f ON f.id = s.flavor_id
                        WHERE 1=1 {scope_and}
                        ORDER BY s.name LIMIT 50""",
        boost=0.2,
    ),
    IntentDef(
        key="vms_on_host",
        display_name="VMs on host",
        keywords=["vms on host", "servers on host", "instances on host",
                  "what runs on host", "workloads on host"],
        patterns=[r"(?:vms?|servers?|instances?|workloads?)\s+(?:on|running on|hosted on)\s+host\s+\S+",
                  r"(?:show|list|what)\s+(?:runs?|is|vms?).+(?:on\s+host)"],
        sql="""SELECT s.name, s.status, p.name AS project, f.name AS flavor_name
               FROM servers s
               LEFT JOIN projects p ON s.project_id = p.id
               LEFT JOIN flavors f ON f.id = s.flavor_id
               ORDER BY s.name LIMIT 50""",
        formatter=lambda rows: (
            f"**{len(rows)}** VM(s) found:\n\n" +
            _fmt_table(rows, ["name", "status", "project", "flavor_name"])
            if rows else "No VMs found on that host."
        ),
        supports_scope=True,
        sql_template="""SELECT s.name, s.status, p.name AS project, f.name AS flavor_name
                        FROM servers s
                        LEFT JOIN projects p ON s.project_id = p.id
                        LEFT JOIN flavors f ON f.id = s.flavor_id
                        WHERE LOWER(s.hypervisor_hostname) LIKE %s
                        ORDER BY s.name LIMIT 50""",
        boost=0.2,
    ),
    IntentDef(
        key="configured_quota",
        display_name="Configured quota limits",
        keywords=["quota for", "quota of", "quota on", "project quota",
                  "tenant quota", "quota exists", "configured quota",
                  "quota limits", "quota config", "show quota",
                  "what is the quota", "get quota"],
        patterns=[r"quota\s+(?:for|of|on|exists)\s+(?:tenant|project|org)?\s*\S+",
                  r"(?:show|what|get)\s+quota",
                  r"configured\s+quota",
                  r"quota\s+(?:limit|config)",
                  r"quota\s+(?:for|of|on|exists)\b"],
        formatter=None,  # api_handler handles formatting
        api_handler=_fetch_configured_quota,
        supports_scope=True,
        boost=0.35,
    ),
    IntentDef(
        key="quota_and_usage",
        display_name="Quota limits vs actual usage",
        keywords=["quota and usage", "quota vs usage", "quota versus usage",
                  "quota with usage", "limits and usage", "configured and usage",
                  "quota compared", "quota comparison"],
        patterns=[r"quota\s+(?:and|vs\.?|versus|with|compared\s+to)\s+usage",
                  r"(?:limits?|quota)\s+(?:and|vs\.?|versus)\s+(?:usage|consumption)",
                  r"(?:configured|actual)\s+(?:and|vs\.?)\s+(?:usage|actual)"],
        formatter=None,
        api_handler=_fetch_quota_and_usage,
        supports_scope=True,
        boost=0.4,
    ),
    IntentDef(
        key="resource_usage",
        display_name="Resource usage by project",
        keywords=["usage for", "resource usage", "tenant usage", "project usage",
                  "actual usage", "current usage", "consumption",
                  "how much is used", "resources used"],
        patterns=[r"(?:resource|tenant|project|actual|current)\s+usage",
                  r"usage\s+(?:for|of|on)\s+(?:tenant|project)",
                  r"(?:show|what|get)\s+usage",
                  r"how much\s+(?:is|are)\s+used"],
        sql="""SELECT p.name AS project,
                      (SELECT COUNT(*) FROM servers s WHERE s.project_id = p.id) AS vms,
                      (SELECT COALESCE(SUM(f.vcpus), 0) FROM servers s
                       LEFT JOIN flavors f ON f.id = s.flavor_id
                       WHERE s.project_id = p.id) AS vcpus,
                      (SELECT COALESCE(SUM(f.ram_mb), 0) FROM servers s
                       LEFT JOIN flavors f ON f.id = s.flavor_id
                       WHERE s.project_id = p.id) AS ram_mb,
                      (SELECT COUNT(*) FROM volumes v WHERE v.project_id = p.id) AS volumes,
                      (SELECT COALESCE(SUM(v.size_gb), 0) FROM volumes v
                       WHERE v.project_id = p.id) AS storage_gb
               FROM projects p
               ORDER BY p.name LIMIT 30""",
        formatter=lambda rows: (
            "**Resource usage by project** (actual consumption from running VMs and volumes — not quota limits):\n\n" +
            _fmt_table(rows, ["project", "vms", "vcpus", "ram_mb", "volumes", "storage_gb"])
            if rows else "No project data available."
        ),
        supports_scope=True,
        sql_template="""SELECT p.name AS project,
                              (SELECT COUNT(*) FROM servers s WHERE s.project_id = p.id) AS vms,
                              (SELECT COALESCE(SUM(f.vcpus), 0) FROM servers s
                               LEFT JOIN flavors f ON f.id = s.flavor_id
                               WHERE s.project_id = p.id) AS vcpus,
                              (SELECT COALESCE(SUM(f.ram_mb), 0) FROM servers s
                               LEFT JOIN flavors f ON f.id = s.flavor_id
                               WHERE s.project_id = p.id) AS ram_mb,
                              (SELECT COUNT(*) FROM volumes v WHERE v.project_id = p.id) AS volumes,
                              (SELECT COALESCE(SUM(v.size_gb), 0) FROM volumes v
                               WHERE v.project_id = p.id) AS storage_gb
                       FROM projects p
                       {scope_where_project}
                       ORDER BY p.name LIMIT 30""",
        boost=0.15,
    ),

    # ── List resources ─────────────────────────────────────────────────
    IntentDef(
        key="list_vms",
        display_name="List VMs",
        keywords=["list vms", "list servers", "show vms", "show servers",
                  "all vms", "all servers", "show all instances"],
        patterns=[r"(?:list|show|display)\s+(?:all\s+)?(?:vms|servers|instances)"],
        sql="""SELECT s.name, s.status, p.name AS project, s.vm_state,
                      s.hypervisor_hostname AS host, f.name AS flavor_name
               FROM servers s
               LEFT JOIN projects p ON s.project_id = p.id
               LEFT JOIN flavors f ON f.id = s.flavor_id
               ORDER BY s.name LIMIT 50""",
        formatter=lambda rows: _fmt_table(rows, ["name", "status", "project", "host", "flavor_name"]),
        supports_scope=True,
        sql_template="""SELECT s.name, s.status, p.name AS project, s.vm_state,
                              s.hypervisor_hostname AS host, f.name AS flavor_name
                        FROM servers s
                        LEFT JOIN projects p ON s.project_id = p.id
                        LEFT JOIN flavors f ON f.id = s.flavor_id
                        WHERE 1=1 {scope_and}
                        ORDER BY s.name LIMIT 50""",
    ),
    IntentDef(
        key="list_hosts",
        display_name="List hosts",
        keywords=["list hosts", "list hypervisors", "show hosts",
                  "show hypervisors", "all hosts"],
        patterns=[r"(?:list|show|display)\s+(?:all\s+)?(?:hosts|hypervisors|nodes)"],
        sql="""SELECT hostname, state, status, vcpus, memory_mb, local_gb
               FROM hypervisors ORDER BY hostname LIMIT 50""",
        formatter=lambda rows: _fmt_table(rows, ["hostname", "state", "status", "vcpus", "memory_mb", "local_gb"]),
    ),
    IntentDef(
        key="list_volumes",
        display_name="List volumes",
        keywords=["list volumes", "show volumes", "all volumes"],
        patterns=[r"(?:list|show|display)\s+(?:all\s+)?volumes"],
        sql="""SELECT name, status, size, volume_type, bootable
               FROM volumes ORDER BY name LIMIT 50""",
        formatter=lambda rows: _fmt_table(rows, ["name", "status", "size", "volume_type", "bootable"]),
    ),
    IntentDef(
        key="list_networks",
        display_name="List networks",
        keywords=["list networks", "show networks", "all networks",
                  "network list", "network overview"],
        patterns=[r"(?:list|show|display|network)\s+(?:all\s+)?networks?(?:\s+overview)?"],
        sql="""SELECT name, status, provider_network_type, shared, admin_state_up
               FROM networks ORDER BY name LIMIT 50""",
        formatter=lambda rows: _fmt_table(rows, ["name", "status", "provider_network_type", "shared"]),
    ),
    IntentDef(
        key="list_floating_ips",
        display_name="Floating IP overview",
        keywords=["floating ips", "floating ip overview", "show floating ips",
                  "list floating ips", "floating ip list"],
        patterns=[r"floating\s*ips?",
                  r"(?:list|show|display)\s+floating"],
        sql="""SELECT floating_ip_address, status, fixed_ip_address,
                      floating_network_id
               FROM floating_ips ORDER BY floating_ip_address LIMIT 50""",
        formatter=lambda rows: (
            f"**{len(rows)}** floating IP(s):\n\n" +
            _fmt_table(rows, ["floating_ip_address", "status", "fixed_ip_address"])
            if rows else "No floating IPs found."
        ),
    ),
    IntentDef(
        key="list_subnets",
        display_name="Subnet overview",
        keywords=["subnets", "subnet overview", "list subnets", "show subnets"],
        patterns=[r"(?:list|show|display)?\s*subnets?(?:\s+overview)?"],
        sql="""SELECT name, cidr, gateway_ip, ip_version, enable_dhcp
               FROM subnets ORDER BY name LIMIT 50""",
        formatter=lambda rows: _fmt_table(rows, ["name", "cidr", "gateway_ip", "ip_version", "enable_dhcp"]),
    ),
    IntentDef(
        key="list_routers",
        display_name="Router overview",
        keywords=["routers", "router overview", "list routers", "show routers"],
        patterns=[r"(?:list|show|display)?\s*routers?(?:\s+overview)?"],
        sql="""SELECT name, status, admin_state_up, external_gateway_info
               FROM routers ORDER BY name LIMIT 50""",
        formatter=lambda rows: _fmt_table(rows, ["name", "status", "admin_state_up"]),
    ),
    IntentDef(
        key="list_flavors",
        display_name="List flavors",
        keywords=["list flavors", "show flavors", "all flavors", "flavor list",
                  "show all flavors", "available flavors"],
        patterns=[r"(?:list|show|display|all)\s+(?:all\s+)?flavors"],
        sql="""SELECT name, vcpus, ram_mb, disk_gb, is_public
               FROM flavors ORDER BY name LIMIT 50""",
        formatter=lambda rows: _fmt_table(rows, ["name", "vcpus", "ram_mb", "disk_gb", "is_public"]),
    ),

    # ── Capacity ───────────────────────────────────────────────────────
    IntentDef(
        key="capacity_cpu",
        display_name="CPU capacity",
        keywords=["cpu capacity", "cpu usage", "cpu utilization", "vcpu",
                  "total cpu", "available cpu", "free cpu",
                  "hypervisor capacity"],
        patterns=[r"(?:cpu|vcpu)\s+(?:capacity|usage|utiliz|available|free)",
                  r"hypervisor\s+capacity"],
        sql="""SELECT SUM(vcpus) AS total_vcpus,
                      SUM(COALESCE((raw_json->>'vcpus_used')::int, 0)) AS used_vcpus
               FROM hypervisors""",
        formatter=lambda rows: (
            f"**CPU capacity**: {rows[0]['used_vcpus'] or 0} used / {rows[0]['total_vcpus'] or 0} total vCPUs "
            f"({round((rows[0]['used_vcpus'] or 0) / max(rows[0]['total_vcpus'] or 1, 1) * 100, 1)}% utilization)"
            if rows and rows[0]['total_vcpus'] else "No hypervisor data available."
        ),
        boost=0.1,
    ),
    IntentDef(
        key="capacity_memory",
        display_name="Memory capacity",
        keywords=["memory capacity", "memory usage", "ram usage", "ram capacity",
                  "total memory", "available memory", "free memory", "total ram"],
        patterns=[r"(?:memory|ram)\s+(?:capacity|usage|utiliz|available|free)"],
        sql="""SELECT SUM(memory_mb) AS total_mb,
                      SUM(COALESCE((raw_json->>'memory_mb_used')::int, 0)) AS used_mb
               FROM hypervisors""",
        formatter=lambda rows: (
            f"**Memory capacity**: {round((rows[0]['used_mb'] or 0) / 1024, 1)} GB used / "
            f"{round((rows[0]['total_mb'] or 0) / 1024, 1)} GB total "
            f"({round((rows[0]['used_mb'] or 0) / max(rows[0]['total_mb'] or 1, 1) * 100, 1)}% utilization)"
            if rows and rows[0]['total_mb'] else "No hypervisor data available."
        ),
        boost=0.1,
    ),
    IntentDef(
        key="capacity_storage",
        display_name="Storage capacity",
        keywords=["storage capacity", "disk capacity", "storage usage",
                  "disk usage", "total storage", "available storage",
                  "free storage", "free disk"],
        patterns=[r"(?:storage|disk)\s+(?:capacity|usage|utiliz|available|free)"],
        sql="""SELECT SUM(local_gb) AS total_gb,
                      SUM(COALESCE((raw_json->>'local_gb_used')::int, 0)) AS used_gb
               FROM hypervisors""",
        formatter=lambda rows: (
            f"**Storage capacity**: {rows[0]['used_gb'] or 0} GB used / "
            f"{rows[0]['total_gb'] or 0} GB total "
            f"({round((rows[0]['used_gb'] or 0) / max(rows[0]['total_gb'] or 1, 1) * 100, 1)}% utilization)"
            if rows and rows[0]['total_gb'] else "No hypervisor data available."
        ),
        boost=0.1,
    ),

    # ── Status / Errors ────────────────────────────────────────────────
    IntentDef(
        key="error_vms",
        display_name="VMs in error",
        keywords=["error vms", "failed vms", "vms in error", "broken vms",
                  "error servers", "failed servers", "unhealthy vms",
                  "vms with errors", "problematic vms"],
        patterns=[r"(?:error|failed|broken|unhealthy|problematic)\s+(?:vms|servers|instances)",
                  r"(?:vms?|servers?)\s+(?:in\s+)?(?:error|failed|broken)",
                  r"(?:vms?|servers?)\s+with\s+errors?"],
        sql="""SELECT s.name, s.status, s.vm_state, p.name AS project, s.hypervisor_hostname AS host
               FROM servers s
               LEFT JOIN projects p ON s.project_id = p.id
               WHERE UPPER(s.status) IN ('ERROR','SHUTOFF','SUSPENDED','PAUSED')
               ORDER BY s.status, s.name LIMIT 50""",
        formatter=lambda rows: (
            f"Found **{len(rows)}** VMs in non-active state:\n\n" +
            _fmt_table(rows, ["name", "status", "vm_state", "project", "host"])
            if rows else "All VMs are in a healthy state. ✅"
        ),
        supports_scope=True,
        sql_template="""SELECT s.name, s.status, s.vm_state, p.name AS project, s.hypervisor_hostname AS host
                        FROM servers s
                        LEFT JOIN projects p ON s.project_id = p.id
                        WHERE UPPER(s.status) IN ('ERROR','SHUTOFF','SUSPENDED','PAUSED') {scope_and}
                        ORDER BY s.status, s.name LIMIT 50""",
    ),
    IntentDef(
        key="down_hosts",
        display_name="Down hosts",
        keywords=["down hosts", "offline hosts", "disabled hosts",
                  "failed hosts", "unhealthy hosts", "hosts down"],
        patterns=[r"(?:down|offline|disabled|failed|unhealthy)\s+hosts",
                  r"hosts?\s+(?:down|offline|disabled|failed)"],
        sql="""SELECT hostname, state, status, vcpus, memory_mb
               FROM hypervisors
               WHERE LOWER(state) != 'up' OR LOWER(status) != 'enabled'
               ORDER BY hostname""",
        formatter=lambda rows: (
            f"**{len(rows)}** host(s) are not fully operational:\n\n" +
            _fmt_table(rows, ["hostname", "state", "status", "vcpus", "memory_mb"])
            if rows else "All hosts are **up** and **enabled**. ✅"
        ),
    ),

    # ── Snapshots ──────────────────────────────────────────────────────
    IntentDef(
        key="snapshot_summary",
        display_name="Snapshot summary",
        keywords=["snapshot summary", "snapshot status", "snapshot overview",
                  "snapshots", "how many snapshots", "snapshot count"],
        patterns=[r"snapshot\s+(?:summary|status|overview|count)"],
        sql="""SELECT
                 (SELECT COUNT(*) FROM snapshots) AS total_snapshots,
                 (SELECT COUNT(*) FROM snapshot_policy_sets) AS policies,
                 (SELECT COUNT(*) FROM snapshot_runs WHERE status = 'completed') AS completed_runs,
                 (SELECT COUNT(*) FROM snapshot_runs WHERE status = 'failed') AS failed_runs""",
        formatter=lambda rows: (
            f"**Snapshot overview**:\n"
            f"- Total snapshots: {rows[0]['total_snapshots']}\n"
            f"- Policies defined: {rows[0]['policies']}\n"
            f"- Completed runs: {rows[0]['completed_runs']}\n"
            f"- Failed runs: {rows[0]['failed_runs']}"
            if rows else "No snapshot data available."
        ),
    ),
    IntentDef(
        key="recent_snapshots",
        display_name="Recent snapshots",
        keywords=["recent snapshots", "latest snapshots", "last snapshots"],
        patterns=[r"(?:recent|latest|last)\s+snapshots"],
        sql="""SELECT name, status, size, created_at
               FROM snapshots ORDER BY created_at DESC LIMIT 10""",
        formatter=lambda rows: _fmt_table(rows, ["name", "status", "size", "created_at"]),
    ),

    # ── Drift / Compliance ─────────────────────────────────────────────
    IntentDef(
        key="drift_summary",
        display_name="Drift summary",
        keywords=["drift summary", "drift events", "configuration drift",
                  "drift status", "drift overview", "drift detection"],
        patterns=[r"drift\s+(?:summary|status|overview|events|detection)"],
        sql="""SELECT
                 (SELECT COUNT(*) FROM drift_rules) AS total_rules,
                 (SELECT COUNT(*) FROM drift_rules WHERE enabled = true) AS enabled_rules,
                 (SELECT COUNT(*) FROM drift_events) AS total_events,
                 (SELECT COUNT(*) FROM drift_events WHERE severity = 'critical') AS critical_events""",
        formatter=lambda rows: (
            f"**Drift detection overview**:\n"
            f"- Rules defined: {rows[0]['total_rules']} ({rows[0]['enabled_rules']} enabled)\n"
            f"- Total drift events: {rows[0]['total_events']}\n"
            f"- Critical events: {rows[0]['critical_events']}"
            if rows else "No drift data available."
        ),
    ),
    IntentDef(
        key="compliance_summary",
        display_name="Compliance summary",
        keywords=["compliance summary", "compliance status", "compliance report",
                  "compliance overview"],
        patterns=[r"compliance\s+(?:summary|status|report|overview)"],
        sql="""SELECT type, scope, compliant_count, non_compliant_count,
                      total_checked, created_at
               FROM compliance_reports
               ORDER BY created_at DESC LIMIT 5""",
        formatter=lambda rows: (
            "**Latest compliance reports**:\n\n" +
            _fmt_table(rows, ["type", "scope", "compliant_count", "non_compliant_count", "total_checked"])
            if rows else "No compliance reports found."
        ),
    ),

    # ── Metering / Cost ────────────────────────────────────────────────
    IntentDef(
        key="metering_summary",
        display_name="Metering summary",
        keywords=["metering summary", "cost summary", "metering overview",
                  "billing summary", "chargeback"],
        patterns=[r"(?:metering|cost|billing|chargeback)\s+(?:summary|overview)"],
        sql="""SELECT
                 (SELECT COUNT(*) FROM metering_resources) AS metered_records,
                 (SELECT COUNT(DISTINCT server_id) FROM metering_resources) AS metered_vms,
                 (SELECT COUNT(*) FROM metering_flavor_pricing) AS pricing_rules""",
        formatter=lambda rows: (
            f"**Metering overview**:\n"
            f"- Metering records: {rows[0]['metered_records']}\n"
            f"- VMs with metering data: {rows[0]['metered_vms']}\n"
            f"- Flavor pricing rules: {rows[0]['pricing_rules']}"
            if rows else "No metering data available."
        ),
    ),

    # ── Users / RBAC ──────────────────────────────────────────────────
    IntentDef(
        key="user_summary",
        display_name="User summary",
        keywords=["user summary", "how many users", "user count",
                  "list users", "show users", "active users"],
        patterns=[r"(?:how many|count|list|show)\s+users"],
        sql="""SELECT u.username, u.email, u.role, u.is_active,
                      u.last_login_at
               FROM users u ORDER BY u.username LIMIT 30""",
        formatter=lambda rows: (
            f"**{len(rows)}** user(s):\n\n" +
            _fmt_table(rows, ["username", "email", "role", "is_active"])
            if rows else "No users found."
        ),
    ),
    IntentDef(
        key="role_assignments",
        display_name="Role assignments",
        keywords=["role assignments", "all role assignments", "rbac overview",
                  "who has access", "permissions overview"],
        patterns=[r"(?:all\s+)?role\s+assignments?",
                  r"(?:rbac|permissions?)\s+(?:overview|summary)"],
        sql="""SELECT u.username, u.role, u.is_active
               FROM users u ORDER BY u.role, u.username LIMIT 50""",
        formatter=lambda rows: (
            "**Role assignments**:\n\n" +
            _fmt_table(rows, ["username", "role", "is_active"])
            if rows else "No role assignment data."
        ),
    ),

    # ── Activity / Audit ──────────────────────────────────────────────
    IntentDef(
        key="recent_activity",
        display_name="Recent activity",
        keywords=["recent activity", "activity log", "audit log",
                  "latest activity", "what happened", "recent changes",
                  "recent events"],
        patterns=[r"(?:recent|latest|last)\s+(?:activity|changes|events|audit)"],
        sql="""SELECT username, action, resource_type, resource_name,
                      created_at
               FROM activity_log
               ORDER BY created_at DESC LIMIT 15""",
        formatter=lambda rows: (
            "**Recent activity**:\n\n" +
            _fmt_table(rows, ["username", "action", "resource_type", "resource_name", "created_at"])
            if rows else "No recent activity found."
        ),
    ),
    IntentDef(
        key="recent_logins",
        display_name="Recent logins",
        keywords=["recent logins", "login history", "who logged in",
                  "authentication log", "login attempts"],
        patterns=[r"(?:recent|latest|last)\s+logins|who\s+logged\s+in"],
        sql="""SELECT username, action, success, ip_address, created_at
               FROM auth_audit_log
               ORDER BY created_at DESC LIMIT 15""",
        formatter=lambda rows: (
            "**Recent login events**:\n\n" +
            _fmt_table(rows, ["username", "action", "success", "ip_address", "created_at"])
            if rows else "No login events found."
        ),
    ),

    # ── Runbooks ──────────────────────────────────────────────────────
    IntentDef(
        key="runbook_summary",
        display_name="Runbook summary",
        keywords=["runbook summary", "runbooks", "runbook status",
                  "how many runbooks", "list runbooks", "automation"],
        patterns=[r"(?:runbook|automation)\s+(?:summary|status|overview|list)"],
        sql="""SELECT
                 (SELECT COUNT(*) FROM runbooks) AS total_runbooks,
                 (SELECT COUNT(*) FROM runbooks WHERE is_active = true) AS active,
                 (SELECT COUNT(*) FROM runbook_executions) AS total_runs,
                 (SELECT COUNT(*) FROM runbook_executions WHERE status = 'failed') AS failed_runs""",
        formatter=lambda rows: (
            f"**Runbook overview**:\n"
            f"- Total runbooks: {rows[0]['total_runbooks']} ({rows[0]['active']} active)\n"
            f"- Total executions: {rows[0]['total_runs']}\n"
            f"- Failed executions: {rows[0]['failed_runs']}"
            if rows else "No runbook data available."
        ),
    ),

    # ── Health / Overview ─────────────────────────────────────────────
    IntentDef(
        key="tenant_health",
        display_name="Tenant health",
        keywords=["tenant health", "project health", "health overview",
                  "health status", "environment health"],
        patterns=[r"(?:tenant|project|environment)\s+health"],
        sql="""SELECT project_name, health_score, vm_count,
                      error_vm_count, snapshot_coverage_pct
               FROM v_tenant_health
               ORDER BY health_score ASC LIMIT 20""",
        formatter=lambda rows: (
            "**Tenant health** (lowest scores first):\n\n" +
            _fmt_table(rows, ["project_name", "health_score", "vm_count", "error_vm_count", "snapshot_coverage_pct"])
            if rows else "No tenant health data available."
        ),
    ),
    IntentDef(
        key="infrastructure_overview",
        display_name="Infrastructure overview",
        keywords=["infrastructure overview", "environment overview",
                  "infra summary", "overall status", "dashboard summary",
                  "give me an overview", "system overview", "what do i have",
                  "platform overview"],
        patterns=[r"(?:infrastructure|environment|infra|system|overall|platform)\s+(?:overview|summary|status)"],
        sql="""SELECT
                 (SELECT COUNT(*) FROM hypervisors) AS hosts,
                 (SELECT COUNT(*) FROM servers) AS vms,
                 (SELECT COUNT(*) FROM volumes) AS volumes,
                 (SELECT COUNT(*) FROM networks) AS networks,
                 (SELECT COUNT(*) FROM images) AS images,
                 (SELECT COUNT(*) FROM projects) AS projects,
                 (SELECT COUNT(*) FROM domains) AS domains,
                 (SELECT COUNT(*) FROM snapshots) AS snapshots,
                 (SELECT COUNT(*) FROM servers WHERE UPPER(status) = 'ERROR') AS error_vms,
                 (SELECT COUNT(*) FROM hypervisors WHERE LOWER(state) != 'up') AS down_hosts""",
        formatter=lambda rows: (
            f"**Infrastructure overview**:\n"
            f"- Domains: {rows[0]['domains']}  |  Projects: {rows[0]['projects']}\n"
            f"- Hosts: {rows[0]['hosts']}  |  VMs: {rows[0]['vms']} ({rows[0]['error_vms']} in error)\n"
            f"- Volumes: {rows[0]['volumes']}  |  Networks: {rows[0]['networks']}\n"
            f"- Images: {rows[0]['images']}  |  Snapshots: {rows[0]['snapshots']}\n"
            f"- Down hosts: {rows[0]['down_hosts']}"
            if rows else "No infrastructure data available."
        ),
        boost=0.15,
    ),

    # ── Backup ────────────────────────────────────────────────────────
    IntentDef(
        key="backup_status",
        display_name="Backup status",
        keywords=["backup status", "backup summary", "last backup",
                  "backup history", "backups"],
        patterns=[r"backup\s+(?:status|summary|history|overview)"],
        sql="""SELECT status, backup_type, file_size_bytes, started_at, completed_at
               FROM backup_history
               ORDER BY started_at DESC LIMIT 10""",
        formatter=lambda rows: (
            "**Recent backups**:\n\n" +
            _fmt_table(rows, ["status", "backup_type", "file_size_bytes", "started_at", "completed_at"])
            if rows else "No backup history found."
        ),
    ),

    # ── Notifications ─────────────────────────────────────────────────
    IntentDef(
        key="notification_summary",
        display_name="Notification summary",
        keywords=["notification summary", "notifications", "alert summary",
                  "how many notifications", "recent notifications"],
        patterns=[r"notification\s+(?:summary|status|overview)"],
        sql="""SELECT
                 (SELECT COUNT(*) FROM notification_channels) AS channels,
                 (SELECT COUNT(*) FROM notification_log) AS total_sent,
                 (SELECT COUNT(*) FROM notification_log WHERE sent_at > now() - interval '24 hours') AS last_24h""",
        formatter=lambda rows: (
            f"**Notification overview**:\n"
            f"- Configured channels: {rows[0]['channels']}\n"
            f"- Total notifications sent: {rows[0]['total_sent']}\n"
            f"- Last 24 hours: {rows[0]['last_24h']}"
            if rows else "No notification data available."
        ),
    ),

    # ── Security Groups ───────────────────────────────────────────────
    IntentDef(
        key="security_groups_summary",
        display_name="Security groups",
        keywords=["security groups", "firewall rules", "security rules",
                  "how many security groups", "list security groups",
                  "security group overview"],
        patterns=[r"security\s+group"],
        sql="""SELECT
                 (SELECT COUNT(*) FROM security_groups) AS total_groups,
                 (SELECT COUNT(*) FROM security_group_rules) AS total_rules""",
        formatter=lambda rows: (
            f"**Security groups**: {rows[0]['total_groups']} groups with {rows[0]['total_rules']} rules total."
            if rows else "No security group data available."
        ),
    ),

    # ── Provisioning ──────────────────────────────────────────────────
    IntentDef(
        key="provisioning_jobs",
        display_name="Provisioning jobs",
        keywords=["provisioning jobs", "provisioning status", "pending provisions",
                  "recent provisions", "provisioning summary"],
        patterns=[r"provisioning\s+(?:jobs|status|summary|overview)"],
        sql="""SELECT name, status, server_count, created_at
               FROM provisioning_jobs
               ORDER BY created_at DESC LIMIT 10""",
        formatter=lambda rows: (
            "**Recent provisioning jobs**:\n\n" +
            _fmt_table(rows, ["name", "status", "server_count", "created_at"])
            if rows else "No provisioning jobs found."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Matching engine
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


# Common synonyms for fuzzy matching
_SYNONYMS = {
    "vm": "vms",
    "server": "servers",
    "instance": "instances",
    "virtual machine": "vms",
    "hypervisor": "host",
    "node": "host",
    "tenant": "project",
    "org": "project",
    "organisation": "project",
    "organization": "project",
    "powered on": "active",
    "powered off": "shutoff",
    "power on": "active",
    "power off": "shutoff",
    "turned on": "active",
    "turned off": "shutoff",
    "running": "active",
    "stopped": "shutoff",
}


def _expand_synonyms(text: str) -> str:
    """Expand common synonyms to canonical form for better matching."""
    t = text
    for syn, canon in _SYNONYMS.items():
        t = t.replace(syn, f"{syn} {canon}")
    return t


def match_intent(question: str) -> Optional[IntentMatch]:
    """
    Score every intent against `question` and return the best match
    above the confidence threshold (0.35), or None.

    Supports tenant/project scoping: "how many VMs on tenant <name>"
     → will match count_vms intent with scoped SQL.
    """
    raw_q = _normalize(question)
    # Strip scope qualifiers for cleaner intent matching
    q_clean = _normalize(_strip_scope_from_question(question))
    # Also try with synonym expansion
    q_expanded = _expand_synonyms(q_clean)

    scope = _extract_scope(raw_q)
    host = _extract_host(raw_q)

    best: Optional[Tuple[float, IntentDef]] = None

    for intent in INTENTS:
        score = 0.0

        # Try matching against both clean and expanded versions
        for q in (q_clean, q_expanded, raw_q):
            # Keyword matching — partial keyword hit gives partial score
            kw_hits = sum(1 for kw in intent.keywords if kw in q)
            if kw_hits:
                kw_score = min(kw_hits / max(len(intent.keywords), 1) + 0.3, 0.95)
                score = max(score, kw_score)

            # Regex matching — a hit gives a strong score
            for pat in intent.patterns:
                if re.search(pat, q):
                    score = max(score, 0.85)
                    break

        # Word overlap scoring — catch natural language variations
        intent_words = set()
        for kw in intent.keywords:
            intent_words.update(kw.split())
        q_words = set(q_expanded.split())
        overlap = intent_words & q_words
        if len(overlap) >= 2:
            word_score = min(len(overlap) / max(len(intent_words), 1) * 0.6 + 0.25, 0.75)
            score = max(score, word_score)

        # Boost if the question mentions a scope and the intent supports it
        if (scope or host) and intent.supports_scope and score > 0.3:
            score = min(score + 0.15, 1.0)

        score += intent.boost
        score = min(score, 1.0)

        if score > 0.35 and (best is None or score > best[0]):
            best = (score, intent)

    if best is None:
        return None

    score, intent = best

    # Build scoped SQL if applicable
    final_sql = intent.sql
    final_params: tuple = ()

    if intent.supports_scope and (scope or host) and intent.sql_template:
        if host and intent.key == "vms_on_host":
            final_sql = intent.sql_template.replace("{scope_and}", "")
            final_params = (f"%{host}%",)
        elif scope:
            # Inject scope filter
            scope_and = f"AND LOWER(p.name) LIKE %s"
            scope_where = f"WHERE LOWER(p.name) LIKE %s"
            scope_where_project = f"WHERE LOWER(p.name) LIKE %s"
            final_sql = intent.sql_template \
                .replace("{scope_and}", scope_and) \
                .replace("{scope_where}", scope_where) \
                .replace("{scope_where_project}", scope_where_project)
            final_params = (f"%{scope}%",)
        else:
            # No scope, clean out placeholders
            final_sql = intent.sql_template \
                .replace("{scope_and}", "") \
                .replace("{scope_where}", "") \
                .replace("{scope_where_project}", "")

    # Build a scope-aware formatter
    original_formatter = intent.formatter
    if intent.api_handler:
        # API handler intents manage their own formatting and scoping
        final_formatter = original_formatter
    elif scope and intent.supports_scope:
        def scoped_formatter(rows, _scope=scope, _fmt=original_formatter):
            base = _fmt(rows) if _fmt else str(rows)
            return f"📌 *Filtered by tenant/project: **{_scope}***\n\n{base}"
        final_formatter = scoped_formatter
    elif host and intent.key == "vms_on_host":
        def host_formatter(rows, _host=host, _fmt=original_formatter):
            base = _fmt(rows) if _fmt else str(rows)
            return f"📌 *Filtered by host: **{_host}***\n\n{base}"
        final_formatter = host_formatter
    else:
        final_formatter = original_formatter

    return IntentMatch(
        intent_key=intent.key,
        confidence=round(score, 3),
        display_name=intent.display_name,
        sql=final_sql,
        params=intent.param_extractor(question) if intent.param_extractor else final_params,
        formatter=final_formatter,
        api_handler=intent.api_handler,
    )


def get_suggestion_chips() -> List[dict]:
    """
    Return a list of categorized quick-suggestion chips for the UI,
    plus help tips.
    """
    return {
        "categories": [
            {
                "name": "Infrastructure",
                "icon": "🖥️",
                "chips": [
                    {"label": "How many VMs?", "question": "How many VMs?"},
                    {"label": "List all hosts", "question": "List all hosts"},
                    {"label": "Infrastructure overview", "question": "Give me an infrastructure overview"},
                    {"label": "Image overview", "question": "How many images"},
                    {"label": "List flavors", "question": "Show all flavors"},
                ],
            },
            {
                "name": "VM Power State",
                "icon": "⚡",
                "chips": [
                    {"label": "Powered on VMs", "question": "How many powered on VMs?"},
                    {"label": "Powered off VMs", "question": "Show powered off VMs"},
                    {"label": "VMs in error", "question": "Show VMs in error state"},
                    {"label": "Down hosts", "question": "Are any hosts down?"},
                ],
            },
            {
                "name": "Tenant / Project",
                "icon": "📁",
                "chips": [
                    {"label": "VMs on tenant …", "question": "VMs on tenant ", "template": True},
                    {"label": "Quota for …", "question": "Quota of tenant ", "template": True},
                    {"label": "Usage for …", "question": "Usage for tenant ", "template": True},
                    {"label": "Quota & Usage …", "question": "Quota and usage for tenant ", "template": True},
                    {"label": "How many projects?", "question": "How many projects?"},
                ],
            },
            {
                "name": "Capacity",
                "icon": "📊",
                "chips": [
                    {"label": "CPU capacity", "question": "What is the current CPU capacity?"},
                    {"label": "Memory usage", "question": "Show memory usage"},
                    {"label": "Storage capacity", "question": "Show storage capacity"},
                ],
            },
            {
                "name": "Storage & Snapshots",
                "icon": "💾",
                "chips": [
                    {"label": "Volume summary", "question": "How many volumes?"},
                    {"label": "Snapshot overview", "question": "Snapshot summary"},
                    {"label": "Backup status", "question": "Show backup status"},
                ],
            },
            {
                "name": "Networking",
                "icon": "🌐",
                "chips": [
                    {"label": "Networks", "question": "List networks"},
                    {"label": "Floating IPs", "question": "Show floating IPs"},
                    {"label": "Subnets", "question": "Show subnets"},
                    {"label": "Routers", "question": "Show routers"},
                ],
            },
            {
                "name": "Security & Access",
                "icon": "🔐",
                "chips": [
                    {"label": "Security groups", "question": "Security group overview"},
                    {"label": "Users", "question": "List all users"},
                    {"label": "Role assignments", "question": "Show all role assignments"},
                    {"label": "Recent logins", "question": "Show recent logins"},
                ],
            },
            {
                "name": "Operations",
                "icon": "🛠️",
                "chips": [
                    {"label": "Recent activity", "question": "Show recent activity"},
                    {"label": "Drift summary", "question": "Show drift summary"},
                    {"label": "Tenant health", "question": "Show tenant health"},
                    {"label": "Runbooks", "question": "Show runbook summary"},
                    {"label": "Notifications", "question": "Show notification summary"},
                ],
            },
        ],
        "tips": [
            "Ask naturally: \"How many powered on VMs on tenant <your-tenant>?\"",
            "Scope by tenant: add \"on tenant <name>\" or \"for project <name>\"",
            "Scope by host: add \"on host <hostname>\"",
            "Use action words: show, list, count, how many",
            "Try: \"VMs in error\", \"CPU capacity\", \"drift summary\"",
            "Click any chip to run it instantly — chips with \"…\" need a name",
        ],
    }
