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
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from psycopg2.extras import RealDictCursor

from copilot_llm import ask_llm

logger = logging.getLogger("pf9.smart_queries")

_LLM_CLASSIFIER_TIMEOUT_SECONDS = 2.0
_LLM_CLASSIFIER_PROMPT = (
    "You are a classifier. "
    "Given a user question and available smart query templates, "
    "return ONLY one exact query_id from the provided list, or null. "
    "Return no prose, no explanation, no JSON."
)


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


def _get_copilot_runtime_config(conn) -> Dict[str, Any]:
    """
    Resolve Copilot runtime config used for LLM smart-query fallback.

    Environment values are defaults and may be overridden by copilot_config.
    """
    cfg: Dict[str, Any] = {
        "enabled": os.getenv("COPILOT_ENABLED", "false").lower() in ("true", "1", "yes"),
        "backend": os.getenv("COPILOT_BACKEND", "builtin"),
        "ollama_url": os.getenv("COPILOT_OLLAMA_URL", "http://localhost:11434"),
        "ollama_model": os.getenv("COPILOT_OLLAMA_MODEL", "llama3"),
        "openai_api_key": os.getenv("COPILOT_OPENAI_API_KEY", ""),
        "openai_model": os.getenv("COPILOT_OPENAI_MODEL", "gpt-4o-mini"),
        "anthropic_api_key": os.getenv("COPILOT_ANTHROPIC_API_KEY", ""),
        "anthropic_model": os.getenv("COPILOT_ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
    }

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT backend, ollama_url, ollama_model,
                       openai_api_key, openai_model,
                       anthropic_api_key, anthropic_model
                FROM copilot_config
                WHERE id = 1
            """)
            row = cur.fetchone()
            if row:
                # Prefer runtime DB settings when present.
                for key in (
                    "backend", "ollama_url", "ollama_model",
                    "openai_api_key", "openai_model",
                    "anthropic_api_key", "anthropic_model",
                ):
                    if row.get(key) is not None:
                        cfg[key] = row.get(key)
    except Exception:
        # copilot_config might not exist in minimal/test setups.
        pass

    return cfg


def _llm_classify_query(
    question: str,
    smart_queries: List[SmartQuery],
    conn,
) -> Optional[str]:
    """
    Classify unmatched smart query text via LLM.

    Returns a query_id from `smart_queries`, or None when classification is
    unavailable/invalid/timed out.
    """
    cfg = _get_copilot_runtime_config(conn)
    if not cfg.get("enabled", False):
        return None

    backend = str(cfg.get("backend") or "builtin").strip().lower()
    if backend in ("", "builtin"):
        return None
    if backend == "openai" and not str(cfg.get("openai_api_key") or "").strip():
        return None
    if backend == "anthropic" and not str(cfg.get("anthropic_api_key") or "").strip():
        return None

    candidates = [
        {"id": sq.id, "description": sq.description or sq.title}
        for sq in smart_queries
    ]
    candidate_ids = {c["id"] for c in candidates}

    query_index = "\n".join(f"- {c['id']}: {c['description']}" for c in candidates)
    classifier_question = (
        f"Question: {question}\n\n"
        f"Available query templates:\n{query_index}\n\n"
        "Return only one query_id or null."
    )

    try:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(
                ask_llm,
                backend,
                classifier_question,
                "",
                _LLM_CLASSIFIER_PROMPT,
                ollama_url=str(cfg.get("ollama_url") or "http://localhost:11434"),
                ollama_model=str(cfg.get("ollama_model") or "llama3"),
                openai_api_key=str(cfg.get("openai_api_key") or ""),
                openai_model=str(cfg.get("openai_model") or "gpt-4o-mini"),
                anthropic_api_key=str(cfg.get("anthropic_api_key") or ""),
                anthropic_model=str(cfg.get("anthropic_model") or "claude-sonnet-4-20250514"),
            )
            answer, backend_used, _tokens, _ext = fut.result(timeout=_LLM_CLASSIFIER_TIMEOUT_SECONDS)

        raw = (answer or "").strip().strip('"').strip("'")
        if not raw:
            return None
        lowered = raw.lower()
        if lowered in ("null", "none", "no_match", "no match"):
            return None

        if raw in candidate_ids:
            logger.info("smart_query_llm_hit backend=%s query_id=%s", backend_used, raw)
            return raw

        # Tolerate slight LLM verbosity by extracting the first valid ID token.
        for token in re.findall(r"[A-Za-z0-9_\-]+", raw):
            if token in candidate_ids:
                logger.info("smart_query_llm_hit backend=%s query_id=%s", backend_used, token)
                return token

        return None
    except Exception as exc:
        logger.debug("Smart query LLM classify failed: %s", exc, exc_info=True)
        return None


def _extract_params(match: re.Match, sq: SmartQuery) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for key in sq.param_keys:
        val = match.group(key)
        if val:
            params[key] = f"%{val.strip()}%"
    return params


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



# ┌──────────────────────────────────────────────────────────┐
# │  27. RUNNING / ACTIVE VMs                                │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="running_vms",
    title="Running / Active VMs",
    pattern=re.compile(
        r"\b(?:running|active|on|powered.?on|live)\b.*\b(?:vm|vms|server|servers|instance|instances)\b"
        r"|\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:running|active|on|powered.?on|live)\b"
        r"|\bhow\s+many\b.*\b(?:running|active|on|powered.?on)\b",
        re.I,
    ),
    sql="""
        SELECT s.name, p.name AS project, d.name AS domain,
               s.status, s.vm_state, s.hypervisor_hostname AS host, s.created_at
        FROM servers s
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE s.status = 'ACTIVE'
          AND (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY s.name
    """,
    formatter=_fmt_table(
        "Running / Active VMs",
        lambda rows, _: f"{len(rows):,} VM(s) currently running",
        [
            {"key": "name",    "label": "VM Name"},
            {"key": "project", "label": "Project"},
            {"key": "domain",  "label": "Domain"},
            {"key": "host",    "label": "Hypervisor"},
            {"key": "created_at", "label": "Created"},
        ],
    ),
    description="Lists all running / ACTIVE VMs",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  28. VMs IN A SPECIFIC PROJECT                           │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="vms_in_project",
    title="VMs in Project",
    pattern=re.compile(
        r"\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:in|of|belonging\s+to)\s+(?:project\s+|tenant\s+)?(?P<tenant>[A-Za-z0-9_. -]{2,40})",
        re.I,
    ),
    sql="""
        SELECT s.name, s.status, s.vm_state,
               s.hypervisor_hostname AS host, s.created_at
        FROM servers s
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE lower(p.name) LIKE lower(%(tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY s.name
    """,
    formatter=_fmt_table(
        "VMs in Project",
        lambda rows, p: (
            f"{len(rows):,} VM(s) in project \"{p.get('tenant','?')}\""
            if rows else f"No VMs found in project \"{p.get('tenant','?')}\""
        ),
        [
            {"key": "name",   "label": "VM Name"},
            {"key": "status", "label": "Status"},
            {"key": "vm_state","label":"State"},
            {"key": "host",   "label": "Hypervisor"},
            {"key": "created_at", "label": "Created"},
        ],
    ),
    description="List VMs belonging to a specific project/tenant",
    category="infrastructure",
    param_keys=["tenant"],
))


# ┌──────────────────────────────────────────────────────────┐
# │  29. DOWN / OFFLINE HYPERVISORS                          │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="down_hypervisors",
    title="Down / Offline Hypervisors",
    pattern=re.compile(
        r"\b(?:down|offline|failed|unreachable|dead)\b.*\b(?:hypervisor|hypervisors|host|hosts|compute|node|nodes)\b"
        r"|\b(?:hypervisor|hypervisors|host|hosts|compute|node)\b.*\b(?:down|offline|failed|unreachable|dead)\b",
        re.I,
    ),
    sql="""
        SELECT hostname, hypervisor_type, state, status, vcpus,
               memory_mb, local_gb, last_seen_at
        FROM hypervisors
        WHERE state != 'up' OR status != 'enabled'
        ORDER BY hostname
    """,
    formatter=_fmt_table(
        "Down / Offline Hypervisors",
        lambda rows, _: (
            f"{len(rows)} hypervisor(s) not healthy" if rows else "All hypervisors are up ✅"
        ),
        [
            {"key": "hostname",       "label": "Host"},
            {"key": "state",          "label": "State"},
            {"key": "status",         "label": "Status"},
            {"key": "hypervisor_type","label": "Type"},
            {"key": "last_seen_at",   "label": "Last Seen"},
        ],
    ),
    description="Hypervisors that are down, disabled, or offline",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  30. TOTAL PLATFORM CAPACITY (CPU / RAM / DISK)          │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="total_capacity",
    title="Total Platform Capacity",
    pattern=re.compile(
        r"\b(?:total|overall|aggregate|combined)\b.*\b(?:capacity|cpu|vcpu|ram|memory|storage|disk|resources)\b"
        r"|\b(?:how\s+much)\b.*\b(?:capacity|cpu|vcpu|ram|memory|storage|disk)\b"
        r"|\b(?:cpu|vcpu|ram|memory|storage|disk)\b.*\b(?:capacity|total|available|how\s+much)\b",
        re.I,
    ),
    sql="""
        SELECT
            count(*) AS hypervisors,
            sum(vcpus) AS total_vcpus,
            sum(memory_mb) AS total_ram_mb,
            sum(local_gb) AS total_disk_gb,
            sum(vcpus) FILTER (WHERE state='up' AND status='enabled') AS available_vcpus,
            sum(memory_mb) FILTER (WHERE state='up' AND status='enabled') AS available_ram_mb
        FROM hypervisors
    """,
    formatter=_fmt_kv(
        "Total Platform Capacity",
        lambda row, _: (
            f"{row.get('total_vcpus',0):,} vCPUs · "
            f"{(row.get('total_ram_mb') or 0)//1024:,} GB RAM · "
            f"{row.get('total_disk_gb',0):,} GB disk · "
            f"{row.get('hypervisors',0)} hypervisors"
        ),
    ),
    description="Aggregate CPU, RAM and disk capacity across all hypervisors",
    category="capacity",
))


# ┌──────────────────────────────────────────────────────────┐
# │  31. LARGEST VMs (by flavour spec)                       │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="largest_vms",
    title="Largest VMs",
    pattern=re.compile(
        r"\b(?:largest|biggest|most\s+resource|heavy|fat|top)\b.*\b(?:vm|vms|server|servers|instance|instances)\b"
        r"|\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:largest|biggest|most\s+resource|heavy|top)\b",
        re.I,
    ),
    sql="""
        SELECT s.name, p.name AS project,
               f.name AS flavor, f.vcpus, f.ram_mb, f.disk_gb,
               s.status, s.hypervisor_hostname AS host
        FROM servers s
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        LEFT JOIN flavors f ON f.id = s.flavor_id
        WHERE f.vcpus IS NOT NULL
          AND (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY f.vcpus DESC, f.ram_mb DESC
        LIMIT 25
    """,
    formatter=_fmt_table(
        "Largest VMs (by vCPUs)",
        lambda rows, _: f"Top {len(rows)} VMs by vCPU count",
        [
            {"key": "name",    "label": "VM"},
            {"key": "flavor",  "label": "Flavor"},
            {"key": "vcpus",   "label": "vCPUs"},
            {"key": "ram_mb",  "label": "RAM (MB)"},
            {"key": "disk_gb", "label": "Disk (GB)"},
            {"key": "project", "label": "Project"},
            {"key": "status",  "label": "Status"},
        ],
    ),
    description="Top 25 VMs sorted by CPU size",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  32. OLDEST VMs                                          │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="oldest_vms",
    title="Oldest VMs",
    pattern=re.compile(
        r"\b(?:oldest|longest\s+running|longest.?lived|veteran)\b.*\b(?:vm|vms|server|servers|instance|instances)\b"
        r"|\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:oldest|longest\s+running|created\s+first)\b",
        re.I,
    ),
    sql="""
        SELECT s.name, p.name AS project, s.status,
               s.created_at, s.hypervisor_hostname AS host
        FROM servers s
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE s.created_at IS NOT NULL
          AND (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY s.created_at ASC
        LIMIT 25
    """,
    formatter=_fmt_table(
        "Oldest VMs",
        lambda rows, _: f"Top {len(rows)} oldest VMs",
        [
            {"key": "name",       "label": "VM"},
            {"key": "project",    "label": "Project"},
            {"key": "status",     "label": "Status"},
            {"key": "created_at", "label": "Created"},
            {"key": "host",       "label": "Hypervisor"},
        ],
    ),
    description="VMs sorted by creation date (oldest first)",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  33. NEWEST / RECENTLY CREATED VMs                       │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="newest_vms",
    title="Recently Created VMs",
    pattern=re.compile(
        r"\b(?:newest|latest|recent|last\s+created|new)\b.*\b(?:vm|vms|server|servers|instance|instances)\b"
        r"|\b(?:vm|vms|server|servers|instance|instances)\b.*\b(?:newest|latest|recently\s+created|created\s+recently)\b",
        re.I,
    ),
    sql="""
        SELECT s.name, p.name AS project, s.status,
               s.created_at, s.hypervisor_hostname AS host
        FROM servers s
        LEFT JOIN projects p ON p.id = s.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE s.created_at IS NOT NULL
          AND (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY s.created_at DESC
        LIMIT 25
    """,
    formatter=_fmt_table(
        "Recently Created VMs",
        lambda rows, _: f"Last {len(rows)} created VMs",
        [
            {"key": "name",       "label": "VM"},
            {"key": "project",    "label": "Project"},
            {"key": "status",     "label": "Status"},
            {"key": "created_at", "label": "Created"},
            {"key": "host",       "label": "Hypervisor"},
        ],
    ),
    description="Most recently created VMs",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  34. USER LIST                                           │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="user_list",
    title="User List",
    pattern=re.compile(
        r"\b(?:user|users)\b.*\b(?:list|all|overview|summary)\b"
        r"|\b(?:list|show|all)\b.*\b(?:user|users)\b"
        r"|\bhow\s+many\b.*\b(?:user|users)\b",
        re.I,
    ),
    sql="""
        SELECT u.username, u.email, u.full_name,
               u.enabled, u.default_project, u.created_at,
               (SELECT string_agg(DISTINCT role, ', ') FROM user_roles WHERE username = u.username) AS roles
        FROM ldap_users u
        WHERE (%(scope_tenant)s IS NULL OR u.default_project = %(scope_tenant)s)
        ORDER BY u.username
        LIMIT 100
    """,
    formatter=_fmt_table(
        "User List",
        lambda rows, _: f"{len(rows)} user(s) (top 100)",
        [
            {"key": "username",        "label": "Username"},
            {"key": "email",           "label": "Email"},
            {"key": "full_name",       "label": "Full Name"},
            {"key": "roles",           "label": "Roles"},
            {"key": "enabled",         "label": "Enabled"},
            {"key": "default_project", "label": "Default Project"},
        ],
    ),
    description="All users with roles and status",
    category="security",
))


# ┌──────────────────────────────────────────────────────────┐
# │  35. UNASSIGNED / FREE FLOATING IPs                      │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="free_floating_ips",
    title="Free / Unassigned Floating IPs",
    pattern=re.compile(
        r"\b(?:unassigned|free|unused|idle|available)\b.*\b(?:floating.?ip|fip|public.?ip|external.?ip)\b"
        r"|\b(?:floating.?ip|fip|public.?ip)\b.*\b(?:unassigned|free|unused|idle|available|not\s+used)\b",
        re.I,
    ),
    sql="""
        SELECT floating_ip, p.name AS project, last_seen_at
        FROM floating_ips f
        LEFT JOIN projects p ON p.id = f.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE f.port_id IS NULL
          AND (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY f.floating_ip
    """,
    formatter=_fmt_table(
        "Free / Unassigned Floating IPs",
        lambda rows, _: (
            f"{len(rows)} floating IP(s) not attached to any port"
            if rows else "All floating IPs are assigned ✅"
        ),
        [
            {"key": "floating_ip",  "label": "Floating IP"},
            {"key": "project",      "label": "Project"},
            {"key": "last_seen_at", "label": "Last Seen"},
        ],
    ),
    description="Floating IPs not associated with any port/VM",
    category="operations",
))


# ┌──────────────────────────────────────────────────────────┐
# │  36. BACKUP HISTORY / STATUS                             │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="backup_history",
    title="Backup History",
    pattern=re.compile(
        r"\b(?:backup|backups)\b.*\b(?:history|status|recent|latest|last|list|overview)\b"
        r"|\b(?:recent|latest|last)\b.*\b(?:backup|backups)\b",
        re.I,
    ),
    sql="""
         SELECT bh.backup_type,
             bh.status,
             bh.started_at,
             bh.completed_at AS finished_at,
             ROUND(COALESCE(bh.file_size_bytes, 0) / 1048576.0, 2) AS file_size_mb,
             bh.error_message
        FROM backup_history bh
        ORDER BY bh.started_at DESC
        LIMIT 20
    """,
    formatter=_fmt_table(
        "Backup History (latest 20)",
        lambda rows, _: (
            f"{sum(1 for r in rows if r.get('status')=='success'):,} succeeded, "
            f"{sum(1 for r in rows if r.get('status')!='success'):,} failed"
            if rows else "No backup records found"
        ),
        [
            {"key": "backup_type",   "label": "Type"},
            {"key": "status",        "label": "Status"},
            {"key": "started_at",    "label": "Started"},
            {"key": "finished_at",   "label": "Finished"},
            {"key": "file_size_mb",  "label": "Size (MB)"},
            {"key": "error_message", "label": "Error"},
        ],
    ),
    description="Recent database backup jobs and their outcomes",
    category="operations",
))


# ┌──────────────────────────────────────────────────────────┐
# │  37. SNAPSHOT POLICIES                                   │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="snapshot_policies",
    title="Snapshot Policies",
    pattern=re.compile(
        r"\b(?:snapshot.?polic|snapshot.?rule|snapshot.?schedule|snapshot.?config)\b",
        re.I,
    ),
    sql="""
        SELECT name, description, is_global, is_active, priority,
               array_length(policies, 1) AS policy_count,
               created_by, updated_at
        FROM snapshot_policy_sets
        ORDER BY priority ASC, name
    """,
    formatter=_fmt_table(
        "Snapshot Policies",
        lambda rows, _: (
            f"{len(rows)} policy set(s), "
            f"{sum(1 for r in rows if r.get('is_active')):,} active"
        ),
        [
            {"key": "name",         "label": "Name"},
            {"key": "is_global",    "label": "Global"},
            {"key": "is_active",    "label": "Active"},
            {"key": "priority",     "label": "Priority"},
            {"key": "policy_count", "label": "Policies"},
            {"key": "created_by",   "label": "Created By"},
        ],
    ),
    description="All snapshot policy sets with status",
    category="operations",
))


# ┌──────────────────────────────────────────────────────────┐
# │  38. TOP RESOURCE CONSUMERS (by VM count)                │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="top_consumers",
    title="Top Resource Consumers",
    pattern=re.compile(
        r"\b(?:top|biggest|largest|most)\b.*\b(?:consumer|consumers|user|users|project|tenant)\b.*\b(?:resource|cpu|ram|vm|vms)\b"
        r"|\b(?:resource|cpu|ram|vm|vms)\b.*\b(?:consumer|consumers|user|users|by\s+project|by\s+tenant)\b",
        re.I,
    ),
    sql="""
        SELECT p.name AS project, d.name AS domain,
               count(s.id) AS vm_count,
               COALESCE(sum(f.vcpus), 0) AS total_vcpus,
               COALESCE(sum(f.ram_mb), 0) AS total_ram_mb,
               COALESCE(sum(f.disk_gb), 0) AS total_disk_gb
        FROM projects p
        LEFT JOIN domains d ON d.id = p.domain_id
        LEFT JOIN servers s ON s.project_id = p.id
        LEFT JOIN flavors f ON f.id = s.flavor_id
        WHERE (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        GROUP BY p.name, d.name
        HAVING count(s.id) > 0
        ORDER BY total_vcpus DESC, vm_count DESC
        LIMIT 25
    """,
    formatter=_fmt_table(
        "Top Resource Consumers",
        lambda rows, _: f"Top {len(rows)} projects by resource usage",
        [
            {"key": "project",      "label": "Project"},
            {"key": "domain",       "label": "Domain"},
            {"key": "vm_count",     "label": "VMs"},
            {"key": "total_vcpus",  "label": "Total vCPUs"},
            {"key": "total_ram_mb", "label": "Total RAM (MB)"},
            {"key": "total_disk_gb","label": "Total Disk (GB)"},
        ],
    ),
    description="Projects ranked by compute resource consumption",
    category="quota",
))


# ┌──────────────────────────────────────────────────────────┐
# │  39. VOLUME COUNT                                        │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="volume_count",
    title="Total Volume Count",
    pattern=re.compile(
        r"\bhow\s+many\b.*\b(?:volume|volumes|disk|disks)\b"
        r"|\b(?:count|total|number)\s+(?:of\s+)?(?:volume|volumes|disk|disks)\b",
        re.I,
    ),
    sql="""
        SELECT count(*) AS count,
               COALESCE(sum(size_gb), 0) AS total_gb
        FROM volumes v
        LEFT JOIN projects p ON p.id = v.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
    """,
    formatter=lambda rows, params: {
        "card_type": "number",
        "title": "Total Volumes",
        "value": _clean_rows(rows)[0].get("count", 0) if rows else 0,
        "unit": "volumes",
        "summary": (
            f"{_clean_rows(rows)[0].get('count', 0):,} volumes, "
            f"{_clean_rows(rows)[0].get('total_gb', 0):,} GB total"
        ) if rows else "0 volumes",
    },
    description="Count of all volumes and total storage",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  40. HYPERVISOR COUNT                                    │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="hypervisor_count",
    title="Total Hypervisor Count",
    pattern=re.compile(
        r"\bhow\s+many\b.*\b(?:hypervisor|hypervisors|host|hosts|compute.?node|compute.?nodes)\b"
        r"|\b(?:count|total|number)\s+(?:of\s+)?(?:hypervisor|hypervisors|host|hosts|compute.?node)\b",
        re.I,
    ),
    sql="""
        SELECT count(*) AS count,
               count(*) FILTER (WHERE state='up' AND status='enabled') AS healthy
        FROM hypervisors
    """,
    formatter=lambda rows, params: {
        "card_type": "number",
        "title": "Total Hypervisors",
        "value": _clean_rows(rows)[0].get("count", 0) if rows else 0,
        "unit": "hypervisors",
        "summary": (
            f"{_clean_rows(rows)[0].get('count', 0):,} hypervisors, "
            f"{_clean_rows(rows)[0].get('healthy', 0):,} healthy"
        ) if rows else "0 hypervisors",
    },
    description="Count of hypervisors and healthy subset",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  41. LARGE / THICK VOLUMES                               │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="large_volumes",
    title="Largest Volumes",
    pattern=re.compile(
        r"\b(?:largest|biggest|large|fat|heavy|top)\b.*\b(?:volume|volumes|disk|disks|storage)\b"
        r"|\b(?:volume|volumes|disk)\b.*\b(?:largest|biggest|large|top|most\s+space)\b",
        re.I,
    ),
    sql="""
        SELECT v.name, v.size_gb, v.status, v.volume_type,
               p.name AS project, v.created_at
        FROM volumes v
        LEFT JOIN projects p ON p.id = v.project_id
        LEFT JOIN domains d ON d.id = p.domain_id
        WHERE v.size_gb IS NOT NULL
          AND (%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR d.name = %(scope_domain)s)
        ORDER BY v.size_gb DESC
        LIMIT 25
    """,
    formatter=_fmt_table(
        "Largest Volumes",
        lambda rows, _: f"Top {len(rows)} volumes by size",
        [
            {"key": "name",        "label": "Volume"},
            {"key": "size_gb",     "label": "Size (GB)"},
            {"key": "status",      "label": "Status"},
            {"key": "volume_type", "label": "Type"},
            {"key": "project",     "label": "Project"},
            {"key": "created_at",  "label": "Created"},
        ],
    ),
    description="Largest volumes by disk size",
    category="infrastructure",
))


# ┌──────────────────────────────────────────────────────────┐
# │  42. METERING / USAGE SUMMARY                            │
# └──────────────────────────────────────────────────────────┘
_register(SmartQuery(
    id="metering_summary",
    title="Metering / Usage Summary",
    pattern=re.compile(
        r"\b(?:metering|billing|chargeback|usage\.?summary|resource.?usage)\b"
        r"|\b(?:show|get)\b.*\b(?:usage|metering|billing|chargeback)\b",
        re.I,
    ),
    sql="""
        WITH latest AS (
            SELECT DISTINCT ON (project_id)
                project_name, domain,
                vcpus_used, ram_used_mb, instances_used,
                volumes_used, storage_used_gb, collected_at
            FROM metering_quotas
            ORDER BY project_id, collected_at DESC
        )
        SELECT project_name, domain, instances_used, vcpus_used,
               ram_used_mb, volumes_used, storage_used_gb, collected_at
        FROM latest
        WHERE (%(scope_tenant)s IS NULL OR project_name = %(scope_tenant)s)
          AND (%(scope_domain)s IS NULL OR domain = %(scope_domain)s)
        ORDER BY instances_used DESC
        LIMIT 50
    """,
    formatter=_fmt_table(
        "Resource Usage Summary",
        lambda rows, _: (
            f"{len(rows)} project(s) · "
            f"{sum(r.get('instances_used',0) for r in rows):,} VMs · "
            f"{sum(r.get('vcpus_used',0) for r in rows):,} vCPUs"
            if rows else "No metering data collected yet"
        ),
        [
            {"key": "project_name",    "label": "Project"},
            {"key": "domain",          "label": "Domain"},
            {"key": "instances_used",  "label": "VMs"},
            {"key": "vcpus_used",      "label": "vCPUs"},
            {"key": "ram_used_mb",     "label": "RAM (MB)"},
            {"key": "volumes_used",    "label": "Volumes"},
            {"key": "storage_used_gb", "label": "Storage (GB)"},
            {"key": "collected_at",    "label": "As Of"},
        ],
    ),
    description="Per-project resource usage from metering data",
    category="quota",
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
    matched_sq: Optional[SmartQuery] = None
    match_obj: Optional[re.Match] = None
    matched_via = "regex"

    for sq in SMART_QUERIES:
        m = sq.pattern.search(question)
        if m:
            matched_sq = sq
            match_obj = m
            break

    if matched_sq is None:
        llm_query_id = _llm_classify_query(question, SMART_QUERIES, conn)
        if llm_query_id:
            matched_sq = next((sq for sq in SMART_QUERIES if sq.id == llm_query_id), None)
            matched_via = "llm"

    if matched_sq is None:
        return None

    params = _extract_params(match_obj, matched_sq) if match_obj else {}

    # Inject scope params (always present — NULL = no filter)
    params["scope_tenant"] = scope_tenant or None
    params["scope_domain"] = scope_domain or None

    logger.info(
        "Smart query matched: %s (id=%s, via=%s, params=%s)",
        matched_sq.title,
        matched_sq.id,
        matched_via,
        params,
    )

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(matched_sq.sql, params)
            rows = [dict(r) for r in cur.fetchall()]

        result = matched_sq.formatter(rows, {k: v.strip('%') if isinstance(v, str) else v for k, v in params.items()})
        result["query_id"] = matched_sq.id
        result["query_title"] = matched_sq.title
        result["description"] = matched_sq.description
        result["category"] = matched_sq.category
        result["matched"] = True
        result["matched_via"] = matched_via
        return result

    except Exception as exc:
        logger.error("Smart query %s failed: %s", matched_sq.id, exc, exc_info=True)
        return {
            "matched": True,
            "query_id": matched_sq.id,
            "query_title": matched_sq.title,
            "card_type": "error",
            "summary": f"Query failed: {exc}",
            "error": str(exc),
            "matched_via": matched_via,
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
