"""
System Config API  (v2.12.0)

Exposes runtime configuration state to the admin UI.
Provides read and limited write access to feature-flagged settings.

Routes
------
GET  /api/admin/system/config                      — read current config
POST /api/admin/system/config/multi-region         — update multi-region settings

IMPORTANT: These endpoints show sanitised config (no secrets).
           The POST endpoint writes to Redis only (runtime override).
           Persistent changes require values.prod.yaml in the deploy repo.

RBAC: superadmin only (require_permission("admin", "write")).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_permission

logger = logging.getLogger("pf9.system_config")

router = APIRouter(prefix="/api/admin/system", tags=["admin"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VERSION = os.getenv("APP_VERSION", "2.12.0")


def _bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


def _redis_ping() -> bool:
    try:
        from cache import _get_client as _rc
        rc = _rc()
        return rc is not None and rc.ping()
    except Exception:
        return False


def _prometheus_ping() -> bool:
    prom_url = os.getenv("PROMETHEUS_URL", "")
    if not prom_url:
        return False
    try:
        import urllib.request
        with urllib.request.urlopen(f"{prom_url.rstrip('/')}/-/ready", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Config read
# ---------------------------------------------------------------------------

@router.get("/config")
def get_system_config(
    _user=Depends(require_permission("admin", "read")),
):
    """
    Return sanitised runtime configuration.

    Secret values (passwords, DSNs) are never returned — only boolean
    flags indicating whether they are set.
    """
    from db_pool import _ENABLE_MULTI_REGION, _DB_READ_REPLICA_URL

    # Check for runtime override in Redis
    multi_region_override = _get_runtime_override("multi_region_enabled")

    return {
        "version": _VERSION,
        # Multi-region HA
        "multi_region_enabled": (
            multi_region_override
            if multi_region_override is not None
            else _ENABLE_MULTI_REGION
        ),
        "db_read_replica_url_set": bool(_DB_READ_REPLICA_URL) or _redis_key_set("mr:replica_url"),
        # Node logs
        "node_log_source": os.getenv("NODE_LOG_SOURCE", "disabled"),
        "node_log_configured": os.getenv("NODE_LOG_SOURCE", "disabled") != "disabled",
        "node_log_cache_ttl_s": int(os.getenv("NODE_LOG_CACHE_TTL_S", "300")),
        # Redis / Prometheus
        "redis_available": _redis_ping(),
        "prometheus_available": _prometheus_ping(),
        "prometheus_url_set": bool(os.getenv("PROMETHEUS_URL", "")),
        # SSE
        "sse_enabled": True,  # Always enabled when API is running
    }


# ---------------------------------------------------------------------------
# Multi-region write
# ---------------------------------------------------------------------------

class MultiRegionPayload(BaseModel):
    enabled: bool
    db_read_replica_url: Optional[str] = None


@router.post("/config/multi-region")
def update_multi_region(
    payload: MultiRegionPayload,
    _user=Depends(require_permission("admin", "write")),
):
    """
    Update multi-region HA settings at runtime.

    Writes a runtime override to Redis so the next API request sees the
    new value without restarting.  The override is stored with a 24-hour
    TTL as a safety net (restart always takes the value from env/Helm).

    If db_read_replica_url is provided it is stored in Redis (not logged).
    This is a convenience — the secure path is always via values.prod.yaml.
    """
    _set_runtime_override("multi_region_enabled", payload.enabled)

    if payload.db_read_replica_url:
        _store_replica_url(payload.db_read_replica_url)

    # Attempt to reinitialise the read pool if enabling
    if payload.enabled and (payload.db_read_replica_url or _redis_key_set("mr:replica_url")):
        try:
            _reinit_read_pool(payload.db_read_replica_url or _get_replica_url_from_redis())
        except Exception as exc:
            logger.warning("system_config: failed to reinit read pool: %s", exc)
            return {
                "ok": False,
                "message": f"Settings saved but read pool init failed: {exc}. Check the URL and restart the API pod.",
            }

    return {
        "ok": True,
        "message": "Settings saved. Restart the API pod to make the change permanent via Helm values.",
    }


# ---------------------------------------------------------------------------
# Redis helpers for runtime overrides
# ---------------------------------------------------------------------------

_OVERRIDE_TTL = 86_400  # 24 hours


def _get_runtime_override(key: str):
    try:
        from cache import _get_client as _rc
        rc = _rc()
        if rc is None:
            return None
        val = rc.get(f"pf9:runtime_config:{key}")
        return json.loads(val) if val is not None else None
    except Exception:
        return None


def _set_runtime_override(key: str, value) -> None:
    try:
        from cache import _get_client as _rc
        rc = _rc()
        if rc is not None:
            rc.setex(f"pf9:runtime_config:{key}", _OVERRIDE_TTL, json.dumps(value))
    except Exception as exc:
        logger.debug("system_config: failed to set runtime override %s: %s", key, exc)


def _redis_key_set(key: str) -> bool:
    try:
        from cache import _get_client as _rc
        rc = _rc()
        return rc is not None and rc.exists(f"pf9:runtime_config:{key}") > 0
    except Exception:
        return False


def _store_replica_url(url: str) -> None:
    """Store replica URL in Redis (not in logs — treated as secret)."""
    try:
        from cache import _get_client as _rc
        rc = _rc()
        if rc is not None:
            rc.setex(f"pf9:runtime_config:mr:replica_url", _OVERRIDE_TTL, url)
    except Exception as exc:
        logger.debug("system_config: failed to store replica url: %s", exc)


def _get_replica_url_from_redis() -> Optional[str]:
    try:
        from cache import _get_client as _rc
        rc = _rc()
        if rc is None:
            return None
        val = rc.get("pf9:runtime_config:mr:replica_url")
        return val.decode() if val else None
    except Exception:
        return None


def _reinit_read_pool(replica_url: Optional[str]) -> None:
    """Attempt to hot-reinitialise the db_pool read replica pool."""
    if not replica_url:
        return
    import db_pool
    import os
    # Temporarily inject the URL so _init_read_pool() can use it
    os.environ["DB_READ_REPLICA_URL"] = replica_url
    os.environ["ENABLE_MULTI_REGION"] = "true"
    # Reset module-level flag and pool so _init_read_pool will run
    db_pool._ENABLE_MULTI_REGION = True
    db_pool._DB_READ_REPLICA_URL = replica_url
    db_pool._read_pool = None
    db_pool._init_read_pool()
