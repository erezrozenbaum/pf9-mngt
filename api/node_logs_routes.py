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

# Log source: "ssh" | "resmgr" | "hostagent" | "disabled"
_LOG_SOURCE = os.getenv("NODE_LOG_SOURCE", "resmgr").lower()

# Cache TTL for log responses (seconds)
_CACHE_TTL = int(os.getenv("NODE_LOG_CACHE_TTL_S", "300"))

# Direct hostagent port (only used when NODE_LOG_SOURCE=hostagent)
_HOSTAGENT_PORT = int(os.getenv("HOSTAGENT_PORT", "9080"))

# PF9 DU base URL (resmgr lives at {DU_URL}/resmgr)
_DU_URL = os.getenv("PF9_AUTH_URL", "").replace("/keystone/v3", "").replace("/keystone", "").rstrip("/")

# SSH credentials (NODE_LOG_SOURCE=ssh)
_SSH_USER = os.getenv("PF9_SSH_USER", "cloud-kvm")
_SSH_KEY_PATH = os.getenv("PF9_SSH_KEY_PATH", "")
_SSH_PASSWORD = os.getenv("PF9_SSH_PASSWORD", "")
_SSH_PORT = int(os.getenv("PF9_SSH_PORT", "22"))

# Component → /var/log/pf9/ file mapping (SSH source)
_COMPONENT_LOG_FILES: dict[str, str] = {
    "pf9-hostagent":  "/var/log/pf9/hostagent.log",
    "du-agent":       "/var/log/pf9/ostackhost.log",
    "pf9-comms":      "/var/log/pf9/comms/",          # directory — latest file resolved at runtime
    "pf9-kube":       "/var/log/pf9/pf9-kube.log",
    "cindervolume":   "/var/log/pf9/cindervolume-base.log",
    "glance":         "/var/log/pf9/glance-api.log",
}

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
    Fetch node diagnostics from the Platform9 resmgr host record and return
    them as structured log-line dicts.

    The resmgr API does not expose a raw log endpoint; instead we pull:
      GET {DU_URL}/resmgr/v1/hosts/{host_id}
    and synthesise log-style entries from the available diagnostic data:
      - Host status (responding, OS, role_status)
      - Resource usage (CPU %, memory %, disk %)
      - CPU load averages
      - Per-role convergence status
      - Network interfaces

    Returns a list of log-line dicts: {ts, level, component, message}.
    """
    import time as _time

    if not _DU_URL:
        raise ValueError("PF9_AUTH_URL not configured — cannot determine DU base URL")

    token = _get_pf9_token()
    if not token:
        raise ValueError("No PF9 auth token available")

    url = f"{_DU_URL}/resmgr/v1/hosts/{host_id}"
    req = urllib.request.Request(
        url,
        headers={"X-Auth-Token": token, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 — URL constructed from DU_URL env var, not user input
        host = json.loads(resp.read())

    now_ts = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    entries: list[dict] = []

    def _entry(level: str, comp: str, msg: str) -> dict:
        return {"ts": now_ts, "level": level, "component": comp, "message": msg}

    # ── Host status ──────────────────────────────────────────────────────────
    info = host.get("info", {})
    responding = info.get("responding", "?")
    role_status = host.get("role_status", "?")
    os_info = info.get("os_info", "")
    level_status = "INFO" if str(role_status).lower() == "ok" else "WARNING"
    entries.append(_entry(level_status, "pf9-hostagent",
                          f"Host status: responding={responding}  role_status={role_status}  OS={os_info}"))

    message = host.get("message", "")
    if message:
        entries.append(_entry("WARNING", "pf9-hostagent", f"Host message: {message}"))

    # ── Resource usage ────────────────────────────────────────────────────────
    ru = host.get("extensions", {}).get("resource_usage", {}).get("data", {})
    if ru:
        cpu_pct = ru.get("cpu", {}).get("percent", "?")
        mem_pct = ru.get("memory", {}).get("percent", "?")
        disk_pct = ru.get("disk", {}).get("percent", "?")
        mem_avail_gb = round(ru.get("memory", {}).get("available", 0) / 1024**3, 1)
        disk_total_gb = round(ru.get("disk", {}).get("total", 0) / 1024**3, 1)
        disk_used_gb = round(ru.get("disk", {}).get("used", 0) / 1024**3, 1)
        entries.append(_entry("INFO", "pf9-hostagent",
                              f"Resource usage — CPU: {cpu_pct}%  "
                              f"Memory: {mem_pct}% ({mem_avail_gb} GB free)  "
                              f"Disk: {disk_pct}% ({disk_used_gb}/{disk_total_gb} GB)"))

    # ── CPU stats ─────────────────────────────────────────────────────────────
    cpu_stats = host.get("extensions", {}).get("cpu_stats", {}).get("data", {})
    if cpu_stats:
        load = cpu_stats.get("load_average", "?")
        entries.append(_entry("INFO", "pf9-hostagent", f"Load average: {load}"))

    cpu_info = info.get("cpu_info", {})
    if cpu_info:
        sockets = cpu_info.get("cpu_sockets", "?")
        cores = cpu_info.get("cpu_cores", "?")
        threads = cpu_info.get("cpu_threads", {}).get("total", "?")
        model = cpu_info.get("cpu_model", {})
        model_name = model.get("model_name", "").strip() if isinstance(model, dict) else ""
        entries.append(_entry("INFO", "pf9-hostagent",
                              f"CPU: {sockets} socket(s)  {cores} cores  {threads} threads"
                              + (f"  model={model_name}" if model_name else "")))

    # ── Role convergence status ───────────────────────────────────────────────
    rsd = host.get("roles_status_details", {})
    roles_list = host.get("roles", [])
    for role in sorted(roles_list):
        status = rsd.get(role, "unknown")
        lvl = "INFO" if status in ("applied", "ok") else "WARNING"
        entries.append(_entry(lvl, "pf9-comms", f"Role {role}: {status}"))

    # ── Network interfaces ────────────────────────────────────────────────────
    interfaces = host.get("extensions", {}).get("interfaces", {})
    iface_list = (interfaces.get("data") or interfaces) if isinstance(interfaces, dict) else []
    if isinstance(iface_list, list):
        for iface in iface_list[:8]:
            name = iface.get("name", iface.get("if_name", "?"))
            ip = iface.get("ip", iface.get("ip_address", ""))
            mac = iface.get("mac", "")
            state = iface.get("state", iface.get("link_state", ""))
            entries.append(_entry("INFO", "du-agent",
                                  f"Interface {name}: ip={ip or '-'}  mac={mac or '-'}  state={state or '-'}"))

    # Honour the `lines` limit
    return entries[-lines:]


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
    with urllib.request.urlopen(req, timeout=8) as resp:  # nosec B310 — URL constructed from node_ip (internal KVM node), not user input
        body = json.loads(resp.read())

    if isinstance(body, list):
        return body
    if isinstance(body, dict) and "lines" in body:
        return body["lines"]
    if isinstance(body, dict) and "log" in body:
        return _parse_raw_log(body["log"], component)
    return _parse_raw_log(str(body), component)


# ---------------------------------------------------------------------------
# Log fetching — SSH source
# ---------------------------------------------------------------------------

def _fetch_via_ssh(node_ip: str, component: str, lines: int) -> list[dict]:
    """
    Fetch log lines by SSHing to the node and tailing the relevant
    /var/log/pf9/ file.

    Credentials (in order of preference):
      1. PF9_SSH_KEY_PATH  — path to a private key file mounted in the pod
      2. PF9_SSH_PASSWORD  — password for PF9_SSH_USER (from pf9-ssh-credentials secret)

    Component → log file mapping is defined in _COMPONENT_LOG_FILES.
    Unknown components are tried as /var/log/pf9/{component}.log.
    """
    import paramiko  # installed in api/requirements.txt

    if not _SSH_USER:
        raise ValueError("PF9_SSH_USER is not configured")
    if not _SSH_KEY_PATH and not _SSH_PASSWORD:
        raise ValueError(
            "No SSH credentials configured — set PF9_SSH_KEY_PATH or "
            "PF9_SSH_PASSWORD (via pf9-ssh-credentials K8s secret)"
        )
    if not node_ip:
        raise ValueError("Node has no ip_address in the hypervisor inventory")

    # Validate component against whitelist to prevent shell injection (CWE-78)
    if component not in _COMPONENT_LOG_FILES:
        raise ValueError(
            f"Unknown log component '{component}'. "
            f"Allowed: {list(_COMPONENT_LOG_FILES.keys())}"
        )
    # Clamp lines to a safe integer range
    lines = max(1, min(int(lines), 5000))

    log_path = _COMPONENT_LOG_FILES.get(component, f"/var/log/pf9/{component}.log")

    client = paramiko.SSHClient()
    # WarningPolicy logs unknown host keys but does not auto-accept them silently.
    # For production, populate known_hosts with node fingerprints and use RejectPolicy.
    client.set_missing_host_key_policy(paramiko.WarningPolicy())  # nosec B507 — WarningPolicy; production hardening: use RejectPolicy with known_hosts

    connect_kwargs: dict = {
        "hostname": node_ip,
        "port": _SSH_PORT,
        "username": _SSH_USER,
        "timeout": 15,
        "look_for_keys": False,
        "allow_agent": False,
    }
    if _SSH_KEY_PATH:
        connect_kwargs["key_filename"] = _SSH_KEY_PATH
    else:
        connect_kwargs["password"] = _SSH_PASSWORD

    client.connect(**connect_kwargs)
    try:
        if log_path.endswith("/"):
            # Directory (e.g. comms/) — tail the most recently modified file
            cmd = (
                f"latest=$(sudo ls -1t {log_path}*.log 2>/dev/null | head -1); "
                f"[ -n \"$latest\" ] && sudo tail -n {lines} \"$latest\" "
                f"|| echo 'NO_LOG_FILES_FOUND:{log_path}'"
            )
        else:
            cmd = (
                f"[ -f {log_path} ] && sudo tail -n {lines} {log_path} "
                f"|| echo 'LOG_FILE_NOT_FOUND:{log_path}'"
            )
        _, stdout, _ = client.exec_command(cmd, timeout=15)  # nosec B601 — component validated against _COMPONENT_LOG_FILES whitelist above; lines clamped to int
        output = stdout.read().decode("utf-8", errors="replace")
    finally:
        client.close()

    if output.startswith(("LOG_FILE_NOT_FOUND:", "NO_LOG_FILES_FOUND:")):
        raise ValueError(f"Log file not found on node {node_ip}: {log_path}")

    return _parse_raw_log(output, component)


# ---------------------------------------------------------------------------
# Log parsing (raw text → structured lines)
# ---------------------------------------------------------------------------

def _parse_raw_log(raw: str, component: str) -> list[dict]:
    """
    Parse a plain-text log into structured lines.

    Accepts:
      PF9 Python logging format:
        2026-05-25 12:51:04,654 - session.py INFO - message
      ISO/syslog format:
        2026-05-25T10:30:00.000Z INFO pf9-hostagent: message
    or just plain lines.
    """
    import re
    results: list[dict] = []
    # PF9 hostagent format: TIMESTAMP - module.py LEVEL - message
    _PF9_RE = re.compile(
        r'^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)'
        r'\s+-\s+\S+\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+-\s+(?P<rest>.+)$'
    )
    # Generic ISO/syslog format: TIMESTAMP LEVEL message
    _ISO_RE = re.compile(
        r'^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?)'
        r'\s+(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\s+(?P<rest>.+)$'
    )
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _PF9_RE.match(line) or _ISO_RE.match(line)
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
                        hostname                          AS name,
                        raw_json->>'host_ip'              AS ip_address,
                        raw_json->'service'->>'host'      AS resmgr_id,
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
        "log_source_configured": _LOG_SOURCE != "disabled" and (
            _LOG_SOURCE == "ssh" and bool(_SSH_USER and (_SSH_KEY_PATH or _SSH_PASSWORD))
            or _LOG_SOURCE == "hostagent"
            or (_LOG_SOURCE == "resmgr" and bool(_DU_URL))
        ),
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
        if _LOG_SOURCE == "ssh":
            ip = node.get("ip_address")
            if not ip:
                raise ValueError(f"Node '{node_id}' has no ip_address in inventory")
            log_lines = _fetch_via_ssh(ip, component, lines)
        elif _LOG_SOURCE == "resmgr":
            # Use the PF9 resmgr UUID (raw_json->service->host); fall back to DB id
            resmgr_host_id = node.get("resmgr_id") or str(node["id"])
            log_lines = _fetch_via_resmgr(resmgr_host_id, component, lines)
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
