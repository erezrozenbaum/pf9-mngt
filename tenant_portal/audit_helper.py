"""
audit_helper.py — Persistent audit-log helper for the tenant portal.

Every tenant action that reads or mutates data must produce a row in
tenant_action_log — the permanent compliance trail required by Phase 7b.

Usage:
    with get_tenant_connection() as conn:
        with conn.cursor() as cur:
            inject_rls_vars(cur, ctx)
            # ... main query ...
            log_action(cur, ctx, "tenant_view_vms")
            # conn.commit() happens automatically on context-manager exit

Design notes:
  - log_action() is synchronous and uses the SAME cursor/connection as
    the data query so both are committed atomically.
  - Errors in log_action() are silently swallowed so that a log-write
    failure never blocks a legitimate user action.  The error IS logged
    at WARNING level for operator visibility.
  - For endpoints that do NOT have an active cursor (e.g. routes that
    return early before touching the DB), call log_action_bare() which
    opens its own connection and cursor.
"""

import logging
from typing import Any, Dict, Optional

from psycopg2.extras import Json

from tenant_context import TenantContext

logger = logging.getLogger("tenant_portal.audit")


def log_action(
    cur,
    ctx: TenantContext,
    action: str,
    *,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    project_id: Optional[str] = None,
    region_id: Optional[str] = None,
    success: bool = True,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert one audit row using an existing cursor.

    The cursor must already be inside an open transaction; the INSERT will
    be committed together with whatever the caller commits.  Silently
    ignores all errors so a failed log write never breaks user flows.
    """
    try:
        cur.execute(
            """
            INSERT INTO tenant_action_log
                (keystone_user_id, username, control_plane_id, action,
                 resource_type, resource_id, project_id, region_id,
                 ip_address, success, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::inet, %s, %s)
            """,
            (
                ctx.keystone_user_id,
                ctx.username,
                ctx.control_plane_id,
                action,
                resource_type,
                str(resource_id) if resource_id else None,
                project_id,
                region_id,
                ctx.ip_address,
                success,
                Json(details) if details is not None else None,
            ),
        )
    except Exception as exc:
        logger.warning(
            "Failed to write audit log [action=%s user=%s]: %s",
            action,
            ctx.keystone_user_id,
            exc,
        )


def log_action_bare(
    ctx: TenantContext,
    action: str,
    *,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    project_id: Optional[str] = None,
    region_id: Optional[str] = None,
    success: bool = True,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert one audit row opening its own DB connection.

    Use this when no DB cursor is open at the call site (e.g. early-exit
    error paths).  Silently ignores all errors.
    """
    try:
        from db_pool import get_tenant_connection
        from middleware import inject_rls_vars

        with get_tenant_connection() as conn:
            with conn.cursor() as cur:
                inject_rls_vars(cur, ctx)
                log_action(
                    cur,
                    ctx,
                    action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    project_id=project_id,
                    region_id=region_id,
                    success=success,
                    details=details,
                )
    except Exception as exc:
        logger.warning(
            "Failed to write bare audit log [action=%s user=%s]: %s",
            action,
            ctx.keystone_user_id,
            exc,
        )
