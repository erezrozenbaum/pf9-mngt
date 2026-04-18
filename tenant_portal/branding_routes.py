"""
branding_routes.py — Public branding endpoint for the tenant portal.

GET /tenant/branding
  Returns branding configuration (logo, colours, welcome text) for the
  control plane this pod serves. This endpoint is intentionally
  unauthenticated — the SPA calls it before the login screen renders
  so it can display the customer's logo and colour scheme.

No sensitive data is returned. The row is cached in-process for 60 s to
reduce DB round-trips on the login page.
"""

import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from psycopg2.extras import RealDictCursor

from db_pool import get_tenant_connection

logger = logging.getLogger("tenant_portal.branding")

router = APIRouter(tags=["branding"])

# ---------------------------------------------------------------------------
# Control-plane identity (set per-pod via env)
# ---------------------------------------------------------------------------
_CP_ID: str = os.getenv("TENANT_PORTAL_CONTROL_PLANE_ID", "default")

# ---------------------------------------------------------------------------
# Safe defaults — returned when no row exists or DB is unavailable
# ---------------------------------------------------------------------------
_DEFAULTS: Dict[str, Any] = {
    "company_name": "Cloud Portal",
    "logo_url": None,
    "favicon_url": None,
    "primary_color": "#1A73E8",
    "accent_color": "#F29900",
    "support_email": None,
    "support_url": None,
    "welcome_message": None,
    "footer_text": None,
}

# ---------------------------------------------------------------------------
# Simple in-process cache (avoids a DB hit on every page load)
# ---------------------------------------------------------------------------
_CACHE: Dict[str, Any] = {}
_CACHE_TTL = 60  # seconds


def _get_cached_branding(cache_key: str) -> Dict[str, Any] | None:
    entry = _CACHE.get(cache_key)
    if entry and time.monotonic() - entry["ts"] < _CACHE_TTL:
        return entry["data"]
    return None


def _set_cached_branding(cache_key: str, data: Dict[str, Any]) -> None:
    _CACHE[cache_key] = {"data": data, "ts": time.monotonic()}


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/tenant/branding",
    summary="Public branding config for this control plane (unauthenticated)",
    response_description="Branding fields: company name, logo/favicon URLs, colours, support links, text.",
)
async def get_branding(
    project_id: Optional[str] = Query(
        default=None,
        description="Keystone project UUID for per-tenant branding. "
                    "If omitted or not found, falls back to the CP-level default.",
    ),
) -> Dict[str, Any]:
    """
    Return the branding configuration for the control plane this pod serves.

    Called by the tenant-ui SPA on every page load (before login) to apply
    the customer's logo, colours and welcome text. Falls back gracefully:
      1. Per-tenant row (control_plane_id, project_id) if project_id given
      2. Global CP row  (control_plane_id, '')
      3. Hard-coded defaults if DB is unavailable or no row configured
    """
    cache_key = f"branding:{project_id or ''}"
    cached = _get_cached_branding(cache_key)
    if cached is not None:
        return cached

    try:
        with get_tenant_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                row = None
                # Try per-tenant row first when project_id supplied
                if project_id:
                    cur.execute(
                        "SELECT company_name, logo_url, favicon_url, primary_color, "
                        "accent_color, support_email, support_url, "
                        "welcome_message, footer_text "
                        "FROM tenant_portal_branding "
                        "WHERE control_plane_id = %s AND project_id = %s",
                        [_CP_ID, project_id],
                    )
                    row = cur.fetchone()
                # Fall back to global CP-level row
                if row is None:
                    cur.execute(
                        "SELECT company_name, logo_url, favicon_url, primary_color, "
                        "accent_color, support_email, support_url, "
                        "welcome_message, footer_text "
                        "FROM tenant_portal_branding "
                        "WHERE control_plane_id = %s AND project_id = ''",
                        [_CP_ID],
                    )
                    row = cur.fetchone()

        if row:
            data = dict(row)
        else:
            logger.info("No branding row for CP %s — returning defaults", _CP_ID)
            data = dict(_DEFAULTS)

        _set_cached_branding(cache_key, data)
        return data

    except Exception as exc:
        logger.warning("Branding DB read failed (%s) — returning defaults", exc)
        return dict(_DEFAULTS)
