"""
Node Logs API  (v2.12.0)

Surfaces Platform9 system logs from hypervisor nodes through this platform.

Architecture
------------
Log source is selected by the ``NODE_LOG_SOURCE`` env var:

  ``resmgr``      (default) — fetches logs via the PF9 DU resmgr API:
                  ``GET {DU_URL}/resmgr/v1/hosts/{host_id}/log``
                  Requires a valid PF9 auth token (re-uses the Pf9Client
                  token from the cluster registry).

  ``hostagent``   — queries the pf9-hostagent REST API running on each node:
                  ``GET http://{node_ip}:9080/v1/logs?component={comp}&lines=200``
                  Requires direct network access from the API pod to nodes.

  ``disabled``    — returns a ``source_unavailable`` placeholder (useful in
                  Docker Compose / local dev where nodes are not accessible).

Responses are cached in Redis for ``NODE_LOG_CACHE_TTL_S`` seconds
(default 300 / 5 min) to avoid hammering the PF9 API on every page load.

Routes
------
GET /api/admin/nodes                       — list nodes with status
GET /api/admin/nodes/{node_id}/logs        — last N log lines for one node
GET /api/admin/nodes/{node_id}/logs/components — available log components

RBAC: ``monitoring:read`` (admin, superadmin, operator).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.parse
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from auth import require_permission
from db_pool import get_connection

logger = logging.getLogger("pf9.node_logs")

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Log source: "resmgr" | "hostagent" | "disabled"
_LOG_SOURCE = os.getenv("NODE_LOG_SOURCE", "resmgr").lower()

# Cache TTL for log responses (seconds)
_CACHE_TTL = int(os.getenv("NODE_LOG_CACHE_TTL_S", "300"))

# Direct hostagent port (only used when NODE_LOG_SOURCE=hostagent)
_HOSTAGENT_PORT = int(os.getenv("HOSTAGENT_PORT", "9080"))

# PF9 DU base URL (resmgr lives at {DU_URL}/resmgr)
_DU_URL = os.getenv("PF9_AUTH_URL", "").replace("/keystone/v3", "").replace("/keystone", "").rstrip("/")

# Log components available on PF9 nodes
_DEFAULT_COMPONENTS = ["pf9-hostagent", "pf9-comms", "du-agent", "pf9-kube"]

# ---------------------------------------------------------------------------
# Redis cache helpers
# ---------------------------------------------------------------------------

def _cache_get(key: str) -> Optional[Any]:
    try:
        from cache import _get_client as _redis
        rc = _redis()
        if rc is None:
            return None
        val = rc.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


def _cache_set(key: str, value: Any, ttl: int) -> None:
    try:
        from cache import _get_client as _redis
        rc = _redis()
        if rc is not None:
            rc.setex(key, ttl, json.dumps(value))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Log fetching — resmgr source
# ---------------------------------------------------------------------------

def _fetch_via_resmgr(host_id: str, component: str, lines: int) -> list[dict]:
    """
    Fetch recent log lines from the Platform9 resmgr API.

    Endpoint: GET {DU_URL}/resmgr/v1/hosts/{host_id}/log
    Query params: component, lines

    Returns a list of log-line dicts: {ts, level, component, message}.
    """
    if not _DU_URL:
        raise ValueError("PF9_AUTH_URL not configured — cannot determine DU base URL")

    # Retrieve a PF9 auth token from the cluster registry / environment
    token = _get_pf9_token()
    if not token:
        raise ValueError("No PF9 auth token available")

    params = urllib.parse.urlencode({"component": component, "lines": lines})
    url = f"{_DU_URL}/resmgr/v1/hosts/{host_id}/log?{params}"

    req = urllib.request.Request(
        url,
        headers={
            "X-Auth-Token": token,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())

    # resmgr returns {"log": "...raw text..."} or {"lines": [...]}
    if isinstance(body, dict) and "log" in body:
        return _parse_raw_log(body["log"], component)
    if isinstance(body, dict) and "lines" in body:
        return body["lines"]
    # Fallback: treat whole body as raw text
    return _parse_raw_log(str(body), component)


def _get_pf9_token() -> Optional[str]:
    """
    Retrieve a live PF9 auth token from the cluster registry DB or env.
    Falls back to creating a fresh token via Pf9Client if needed.
    """
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT auth_token, token_expires_at
                    FROM   cluster_registry
                    WHERE  status = 'active'
                      AND  auth_token IS NOT NULL
                      AND  token_expires_at > now() + interval '5 minutes'
                    ORDER BY last_sync_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row:
                    return row["auth_token"]
    except Exception as exc:
        logger.debug("node_logs: failed to fetch token from cluster_registry: %s", exc)

    # Fallback: get token via Pf9Client.from_env()
    try:
        from pf9_control import Pf9Client
        client = Pf9Client.from_env()
        client.authenticate()
        return client.token
    except Exception as exc:
        logger.debug("node_logs: Pf9Client.from_env() failed: %s", exc)

    return None


# ---------------------------------------------------------------------------
# Log fetching — hostagent direct source
# ---------------------------------------------------------------------------

def _fetch_via_hostagent(node_ip: str, component: str, lines: int) -> list[dict]:
    """
    Fetch log lines directly from the pf9-hostagent REST API on each node.

    Endpoint: GET http://{node_ip}:{HOSTAGENT_PORT}/v1/logs
    Query params: component, lines
    """
    params = urllib.parse.urlencode({"component": component, "lines": lines})
    url = f"http://{node_ip}:{_HOSTAGENT_PORT}/v1/logs?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        body = json.loads(resp.read())

    if isinstance(body, list):
        return body
    if isinstance(body, dict) and "lines" in body:
        return body["lines"]
    if isinstance(body, dict) and "log" in body:
        return _parse_raw_log(body["log"], component)
    return _parse_raw_log(str(body), component)


# ---------------------------------------------------------------------------
# Log parsing (raw text → structured lines)
# ---------------------------------------------------------------------------

def _parse_raw_log(raw: str, component: str) -> list[dict]:
    """
    Parse a plain-text log into structured lines.

    Accepts syslog-style lines:
      2026-05-25T10:30:00.000Z INFO pf9-hostagent: message here
    or just plain lines.
    """
    import re
    results: list[dict] = []
    _ISO_RE = re.compile(
        r'^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)'
        r'\s+(?P<level>\w+)\s+(?P<rest>.+)$'
    )
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _ISO_RE.match(line)
        if m:
            results.append({
                "ts": m.group("ts"),
                "level": m.group("level").upper(),
                "component": component,
                "message": m.group("rest"),
            })
        else:
            results.append({"ts": None, "level": "INFO", "component": component, "message": line})
    return results[-500:]  # Return at most last 500 lines


# ---------------------------------------------------------------------------
# Node list helper
# ---------------------------------------------------------------------------

def _get_nodes() -> list[dict]:
    """Return hypervisor nodes with id, name, ip_address, and status from DB."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        hostname                     AS name,
                        raw_json->>'host_ip'         AS ip_address,
                        state,
                        status,
                        region_id
                    FROM hypervisors
                    ORDER BY hostname
                    """
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("node_logs: failed to list nodes: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/nodes")
def list_nodes(
    _user=Depends(require_permission("monitoring", "read")),
):
    """
    List all Platform9 hypervisor nodes with their current state.

    Returns id, name, ip_address, state, status, region_id per node.
    """
    nodes = _get_nodes()
    return {
        "nodes": nodes,
        "log_source": _LOG_SOURCE,
        "log_source_configured": _LOG_SOURCE != "disabled" and bool(_DU_URL or _LOG_SOURCE == "hostagent"),
    }


@router.get("/nodes/{node_id}/logs/components")
def list_log_components(
    node_id: str,
    _user=Depends(require_permission("monitoring", "read")),
):
    """Return the list of available log component names for a node."""
    return {"components": _DEFAULT_COMPONENTS}


@router.get("/nodes/{node_id}/logs")
def get_node_logs(
    node_id: str,
    component: str = Query(default="pf9-hostagent", description="Log component name"),
    lines: int = Query(default=200, ge=10, le=1000, description="Number of log lines to return"),
    refresh: bool = Query(default=False, description="Bypass cache and force fresh fetch"),
    _user=Depends(require_permission("monitoring", "read")),
):
    """
    Return recent log lines from a Platform9 hypervisor node.

    Log source is configured by the ``NODE_LOG_SOURCE`` environment variable.
    Results are cached in Redis for ``NODE_LOG_CACHE_TTL_S`` seconds (default 300).

    Set ``?refresh=true`` to bypass the cache and force a live fetch.

    Response fields per line:
      - ``ts``         — ISO-8601 timestamp or null
      - ``level``      — severity (INFO / WARNING / ERROR / DEBUG)
      - ``component``  — log component name
      - ``message``    — log line text
    """
    cache_key = f"pf9:node_logs:{node_id}:{component}:{lines}"

    # Cache hit (unless caller wants a forced refresh)
    if not refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return {**cached, "from_cache": True}

    # Resolve node record
    nodes = _get_nodes()
    node = next((n for n in nodes if n["id"] == node_id or n["name"] == node_id), None)
    if not node:
        raise HTTPException(404, f"Node '{node_id}' not found in hypervisor inventory")

    # Source: disabled
    if _LOG_SOURCE == "disabled":
        result = {
            "node_id": node_id,
            "node_name": node.get("name"),
            "component": component,
            "source": "disabled",
            "log_lines": [],
            "message": (
                "Node log fetching is disabled. "
                "Set NODE_LOG_SOURCE=resmgr or NODE_LOG_SOURCE=hostagent "
                "to enable. See docs/ADMIN_GUIDE.md § Node Logs."
            ),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        return {**result, "from_cache": False}

    # Source: resmgr or hostagent
    log_lines: list[dict] = []
    error_msg: Optional[str] = None
    fetch_start = time.monotonic()

    try:
        if _LOG_SOURCE == "resmgr":
            log_lines = _fetch_via_resmgr(node["id"], component, lines)
        elif _LOG_SOURCE == "hostagent":
            ip = node.get("ip_address")
            if not ip:
                raise ValueError(f"Node '{node_id}' has no ip_address in inventory")
            log_lines = _fetch_via_hostagent(ip, component, lines)
        else:
            raise ValueError(f"Unknown NODE_LOG_SOURCE: {_LOG_SOURCE!r}")
    except Exception as exc:
        error_msg = str(exc)
        logger.warning("node_logs: failed to fetch logs for node=%s component=%s: %s", node_id, component, exc)

    fetch_ms = round((time.monotonic() - fetch_start) * 1000)

    result = {
        "node_id": node_id,
        "node_name": node.get("name"),
        "node_ip": node.get("ip_address"),
        "component": component,
        "source": _LOG_SOURCE,
        "log_lines": log_lines[-lines:],   # enforce requested limit
        "total_lines": len(log_lines),
        "fetch_ms": fetch_ms,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "error": error_msg,
    }

    # Only cache successful responses
    if not error_msg:
        _cache_set(cache_key, result, _CACHE_TTL)

    return {**result, "from_cache": False}
