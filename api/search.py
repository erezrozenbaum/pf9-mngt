"""
Search & Ops-Assistant API Routes
=================================
Provides unified full-text search, trigram similarity, indexer stats,
and **intent detection** (v2.5) that routes recognized natural-language
patterns to existing report endpoints.

Endpoints
---------
  GET  /api/search           – Full-text search across all indexed docs
  GET  /api/search/similar/{doc_id} – Find documents similar to a given one
  GET  /api/search/stats     – Indexer health / status
  POST /api/search/reindex   – Trigger an immediate re-index (admin only)
  GET  /api/search/intent    – Detect intent & suggest/redirect to reports

RBAC: search:read for all read endpoints, search:admin for reindex.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from auth import require_permission, get_current_user, User
from db_pool import get_connection

logger = logging.getLogger("pf9.search")

router = APIRouter(prefix="/api/search", tags=["search"])


# ── helpers ──────────────────────────────────────────────────

def _clean(rows: List[Dict]) -> List[Dict]:
    """Make rows JSON-serializable."""
    for r in rows:
        for k in list(r.keys()):
            if hasattr(r[k], "isoformat"):
                r[k] = r[k].isoformat()
            elif hasattr(r[k], "as_tuple"):
                r[k] = float(r[k])
    return rows


# ── 1. Full-text search ─────────────────────────────────────

@router.get("")
async def search(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    types: Optional[str] = Query(None, description="Comma-separated doc types to filter"),
    tenant_id: Optional[str] = Query(None),
    domain_id: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from", description="ISO date lower bound"),
    to_date: Optional[str] = Query(None, alias="to", description="ISO date upper bound"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: User = Depends(require_permission("search", "read")),
):
    """
    Full-text search across all indexed resources, events, and logs.
    Uses PostgreSQL websearch_to_tsquery + ts_rank_cd for relevance ranking.
    Returns matching documents with a headline snippet.
    """
    type_array = [t.strip() for t in types.split(",") if t.strip()] if types else None

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM search_ranked(%s, %s, %s, %s, %s, %s, %s, %s)",
                (q, type_array, tenant_id, domain_id, from_date, to_date, limit, offset),
            )
            raw = cur.fetchall()
            # Combine headline fields for the UI
            results = []
            for r in raw:
                r["headline"] = " … ".join(filter(None, [
                    r.pop("headline_title", None),
                    r.pop("headline_body", None),
                ]))
                results.append(r)

            # Get total count (without limit/offset) for pagination
            cur.execute("""
                SELECT COUNT(*) AS total
                FROM search_documents
                WHERE body_tsv @@ websearch_to_tsquery('english', %s)
                  AND (%s IS NULL OR doc_type = ANY(%s))
                  AND (%s IS NULL OR tenant_id = %s)
                  AND (%s IS NULL OR domain_id = %s)
                  AND (%s IS NULL OR ts >= %s::timestamptz)
                  AND (%s IS NULL OR ts <= %s::timestamptz)
            """, (
                q,
                type_array, type_array,
                tenant_id, tenant_id,
                domain_id, domain_id,
                from_date, from_date,
                to_date, to_date,
            ))
            total = cur.fetchone()["total"]

    return {
        "query": q,
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": _clean(results),
    }


# ── 2. Similarity search ────────────────────────────────────

@router.get("/similar/{doc_id}")
async def find_similar(
    doc_id: str,
    threshold: float = Query(0.15, ge=0.0, le=1.0),
    limit: int = Query(10, ge=1, le=50),
    _user: User = Depends(require_permission("search", "read")),
):
    """
    Find documents similar to the given doc_id using pg_trgm
    trigram similarity on title + body_text.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verify doc exists
            cur.execute(
                "SELECT doc_id FROM search_documents WHERE doc_id = %s::uuid",
                (doc_id,),
            )
            if not cur.fetchone():
                raise HTTPException(404, f"Document {doc_id} not found")

            cur.execute(
                "SELECT * FROM search_similar(%s::uuid, %s, %s)",
                (doc_id, threshold, limit),
            )
            results = cur.fetchall()

    return {"doc_id": doc_id, "similar": _clean(results)}


# ── 3. Indexer stats ─────────────────────────────────────────

@router.get("/stats")
async def indexer_stats(
    _user: User = Depends(require_permission("search", "read")),
):
    """Return per-doc-type indexing status and document counts."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT s.doc_type,
                       s.last_indexed_at,
                       s.docs_count,
                       s.last_run_at,
                       s.last_run_duration_ms,
                       COALESCE(c.actual, 0) AS actual_count
                FROM search_indexer_state s
                LEFT JOIN (
                    SELECT doc_type, COUNT(*) AS actual
                    FROM search_documents
                    GROUP BY doc_type
                ) c ON s.doc_type = c.doc_type
                ORDER BY s.doc_type
            """)
            rows = cur.fetchall()

            cur.execute("SELECT COUNT(*) AS total FROM search_documents")
            total = cur.fetchone()["total"]

    return {
        "total_documents": total,
        "doc_types": _clean(rows),
    }


# ── 4. Manual re-index trigger ───────────────────────────────

@router.post("/reindex")
async def trigger_reindex(
    _user: User = Depends(require_permission("search", "admin")),
):
    """
    Reset all watermarks to epoch so the next indexer cycle
    re-indexes everything.  Admin only.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE search_indexer_state
                SET last_indexed_at = '1970-01-01T00:00:00Z',
                    docs_count = 0
            """)
        conn.commit()

    return {"status": "ok", "message": "All watermarks reset — full re-index will run on next cycle"}


# ── 5. Intent detection (v2.5) ───────────────────────────────

# Keyword → report-endpoint mapping.
# Each entry: (compiled_regex, report_slug, human_label, description)
_INTENT_PATTERNS = [
    # Quota / usage
    (re.compile(r"\b(quota|quotas|usage|limits?|tenant.?usage)\b", re.I),
     "tenant-quota-usage", "Tenant Quota vs Usage",
     "Shows vCPU, RAM, disk quotas and current usage per tenant"),

    # Domain overview
    (re.compile(r"\b(domain.?overview|domains?\s+summary|all\s+domains)\b", re.I),
     "domain-overview", "Domain Overview",
     "Lists all domains with project counts, user counts, and resource totals"),

    # Capacity / planning
    (re.compile(r"\b(capacity|capacity.?planning|headroom|overcommit|hypervisor.?capacity)\b", re.I),
     "capacity-planning", "Capacity Planning",
     "Hypervisor CPU/RAM/disk utilisation and remaining headroom"),

    # Snapshot compliance
    (re.compile(r"\b(snapshot.?compliance|unprotected|backup.?coverage|snapshot.?status)\b", re.I),
     "snapshot-compliance", "Snapshot Compliance",
     "Volumes with/without recent snapshots and SLA compliance"),

    # Drift
    (re.compile(r"\b(drift|config.?drift|drift.?detection|drift.?summary)\b", re.I),
     "drift-summary", "Drift Detection Summary",
     "Configuration drift events grouped by severity and resource"),

    # Idle / orphan
    (re.compile(r"\b(idle|orphan|unused|wasted|orphaned)\b", re.I),
     "idle-resources", "Idle / Orphaned Resources",
     "Volumes, floating IPs, and ports not attached to any instance"),

    # Backup
    (re.compile(r"\b(backup.?status|backup.?history|backups?)\b", re.I),
     "backup-status", "Backup Status",
     "Recent backup jobs with success/failure status"),

    # Metering
    (re.compile(r"\b(metering|billing|chargeback|resource.?metering)\b", re.I),
     "metering-summary", "Metering Summary",
     "Resource metering data for chargeback and billing"),

    # Inventory
    (re.compile(r"\b(inventory|resource.?inventory|all.?resources|resource.?list)\b", re.I),
     "resource-inventory", "Resource Inventory",
     "Complete inventory of VMs, volumes, networks, and images"),

    # Security groups
    (re.compile(r"\b(security.?group.?audit|security.?rules|sg\s+audit|firewall)\b", re.I),
     "security-group-audit", "Security Group Audit",
     "Security groups, rules, and potential misconfigurations"),

    # Flavor
    (re.compile(r"\b(flavor|flavors|instance.?type|flavor.?usage)\b", re.I),
     "flavor-usage", "Flavor Usage Matrix",
     "Which flavors are in use and by how many instances"),

    # User / role audit
    (re.compile(r"\b(user.?audit|role.?audit|who.?has.?access|user.?roles?|rbac)\b", re.I),
     "user-role-audit", "User & Role Audit",
     "Users with their assigned roles and last login times"),

    # Network topology
    (re.compile(r"\b(network.?topology|network.?map|subnets?\s+map|routers?\s+map)\b", re.I),
     "network-topology", "Network Topology",
     "Networks, subnets, routers, and port connectivity"),

    # Cost allocation
    (re.compile(r"\b(cost|cost.?allocation|spend|spending|budget)\b", re.I),
     "cost-allocation", "Cost Allocation by Domain",
     "Estimated cost allocation broken down by domain and project"),

    # Activity / change log
    (re.compile(r"\b(activity.?log|change.?log|audit.?log|who.?changed|recent.?changes)\b", re.I),
     "activity-log-export", "Activity / Change Log",
     "Recent actions performed by users across the platform"),

    # VM report
    (re.compile(r"\b(vm.?report|virtual.?machine.?report|server.?report|all.?vms)\b", re.I),
     "vm-report", "Virtual Machine Report",
     "Detailed listing of all VMs with status, hypervisor, and resources"),
]


def _detect_intent(query: str) -> List[Dict[str, Any]]:
    """
    Scan the query for keyword patterns and return matching
    report suggestions ordered by match position (earliest first).
    """
    matches = []
    seen = set()
    for pattern, slug, label, description in _INTENT_PATTERNS:
        m = pattern.search(query)
        if m and slug not in seen:
            seen.add(slug)
            matches.append({
                "report": slug,
                "label": label,
                "description": description,
                "endpoint": f"/api/reports/{slug}",
                "matched_keyword": m.group(0),
                "confidence": "high" if len(m.group(0)) > 4 else "medium",
            })
    return matches


def _extract_tenant_hint(query: str) -> Optional[str]:
    """
    Try to extract a tenant/project name from the query so the
    frontend can pre-fill the filter.
    """
    # Patterns like "quota for <tenant>", "capacity of <tenant>"
    m = re.search(
        r"\b(?:for|of|in|on|tenant|project)\s+['\"]?([A-Za-z0-9_. -]{2,40})['\"]?",
        query, re.I,
    )
    return m.group(1).strip() if m else None


@router.get("/intent")
async def detect_intent(
    q: str = Query(..., min_length=1, max_length=500, description="Natural-language query"),
    _user: User = Depends(require_permission("search", "read")),
):
    """
    Analyse a natural-language query and return:
      - **intents**: matching report endpoints the user likely wants
      - **tenant_hint**: extracted tenant/project name (if found)
      - **fallback**: whether a full-text search should also run

    The UI uses this to show "smart suggestions" above search results.
    """
    intents = _detect_intent(q)
    tenant_hint = _extract_tenant_hint(q)

    return {
        "query": q,
        "intents": intents,
        "tenant_hint": tenant_hint,
        "has_intent": len(intents) > 0,
        "fallback_search": True,  # always also run FTS
    }
