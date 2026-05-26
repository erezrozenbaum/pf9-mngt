"""
CLEA — Closed-Loop Event Automation
=====================================
Policy table that maps operational event types to runbooks.

When an operational event matches a CLEA policy the system either:
  • auto-runs the linked runbook (approval_mode = "auto"), or
  • creates a pending-approval entry (approval_mode = "single_approval").

Routes
------
GET    /api/admin/clea/policies              list policies        (admin+)
POST   /api/admin/clea/policies              create policy        (superadmin)
PUT    /api/admin/clea/policies/{id}         update policy        (superadmin)
DELETE /api/admin/clea/policies/{id}         delete policy        (superadmin)
PATCH  /api/admin/clea/policies/{id}/toggle  toggle enabled       (superadmin)
GET    /api/admin/clea/executions            list executions      (admin+)
POST   /api/admin/clea/executions/{id}/approve  approve pending   (superadmin)
POST   /api/admin/clea/executions/{id}/reject   reject pending    (superadmin)

Internal
--------
evaluate_clea_policies(event_id, event_type, metadata)
    Called by event_bus._write_event() after a successful INSERT.
    Runs in the event-bus background thread — never blocks the request path.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from auth import require_permission
from db_pool import get_connection

router = APIRouter(prefix="/api/admin/clea", tags=["clea"])
logger = logging.getLogger("pf9.clea")

_VALID_APPROVAL_MODES = {"auto", "single_approval", "disabled"}

# ---------------------------------------------------------------------------
# Condition expression schema
# ---------------------------------------------------------------------------

#: Supported top-level keys and the operators allowed for each.
_CONDITION_SCHEMA: dict[str, dict] = {
    "severity":    {"operators": ["eq", "neq", "in"],            "description": "Event/insight severity (critical|high|medium|low)"},
    "entity_type": {"operators": ["eq", "neq", "in"],            "description": "Entity type (vm|volume|project|host|…)"},
    "entity_id":   {"operators": ["eq", "neq", "in"],            "description": "Entity UUID"},
    "project_id":  {"operators": ["eq", "neq", "in"],            "description": "OpenStack project UUID"},
    "region_id":   {"operators": ["eq", "neq", "in"],            "description": "Region identifier"},
    "category":    {"operators": ["eq", "neq", "in"],            "description": "Event category string"},
    # metadata.* dot-paths support an extra 'contains' operator
    "__metadata_dot_path__": {
        "operators": ["eq", "neq", "in", "contains"],
        "description": "Dot-path into event metadata (e.g. metadata.runway_days)",
    },
}

_TOP_LEVEL_KEYS: frozenset[str] = frozenset(_CONDITION_SCHEMA.keys()) - {"__metadata_dot_path__"}
_ALL_OPS: frozenset[str] = frozenset({"eq", "neq", "in", "contains"})


def _validate_condition_expr(expr: dict) -> list[str]:
    """Return a list of validation error strings. Empty list = valid."""
    if not isinstance(expr, dict):
        return ["condition_expr must be a JSON object"]
    errors: list[str] = []
    for key, value in expr.items():
        if key in _TOP_LEVEL_KEYS:
            allowed_ops = set(_CONDITION_SCHEMA[key]["operators"])
        elif isinstance(key, str) and key.startswith("metadata.") and len(key) > 9:
            allowed_ops = set(_CONDITION_SCHEMA["__metadata_dot_path__"]["operators"])
        else:
            errors.append(
                f"Unknown condition key '{key}'. "
                f"Supported: {sorted(_TOP_LEVEL_KEYS)} and metadata.* dot-paths"
            )
            continue

        if isinstance(value, dict):
            op = value.get("op")
            val = value.get("value")
            if op is None:
                errors.append(f"Key '{key}': dict value must have an 'op' field")
                continue
            if op not in _ALL_OPS:
                errors.append(f"Key '{key}': unknown operator '{op}'. Supported: {sorted(_ALL_OPS)}")
                continue
            if op not in allowed_ops:
                errors.append(
                    f"Key '{key}': operator '{op}' not allowed for this key. "
                    f"Allowed: {sorted(allowed_ops)}"
                )
                continue
            if op == "in" and not isinstance(val, list):
                errors.append(f"Key '{key}': operator 'in' requires value to be a list")
            if op == "contains" and not isinstance(val, str):
                errors.append(f"Key '{key}': operator 'contains' requires value to be a string")
        # else: shorthand scalar = implicit "eq" — always allowed

    return errors


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CleaPolicyCreate(BaseModel):
    event_type: str
    condition_expr: dict = {}
    runbook_name: str
    approval_mode: str = "single_approval"
    enabled: bool = True


class CleaPolicyUpdate(BaseModel):
    event_type: Optional[str] = None
    condition_expr: Optional[dict] = None
    runbook_name: Optional[str] = None
    approval_mode: Optional[str] = None
    enabled: Optional[bool] = None


# ---------------------------------------------------------------------------
# Condition schema (public to any clea reader)
# ---------------------------------------------------------------------------

@router.get("/condition-schema")
async def get_condition_schema(
    _: Any = Depends(require_permission("clea", "read")),
):
    """Return the supported condition keys, their allowed operators, and descriptions."""
    schema = {}
    for key, meta in _CONDITION_SCHEMA.items():
        if key == "__metadata_dot_path__":
            schema["metadata.*"] = meta
        else:
            schema[key] = meta
    return {"schema": schema, "example": {
        "severity": {"op": "in", "value": ["critical", "high"]},
        "metadata.project_id": {"op": "eq", "value": "<project-uuid>"},
    }}


# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------

@router.get("/policies")
async def list_policies(
    _: Any = Depends(require_permission("clea", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM clea_policies ORDER BY id")
            return [dict(r) for r in cur.fetchall()]


@router.post("/policies", status_code=201)
async def create_policy(
    body: CleaPolicyCreate,
    current_user: Any = Depends(require_permission("clea", "write")),
):
    if body.approval_mode not in _VALID_APPROVAL_MODES:
        raise HTTPException(400, f"approval_mode must be one of {sorted(_VALID_APPROVAL_MODES)}")

    if body.condition_expr:
        errs = _validate_condition_expr(body.condition_expr)
        if errs:
            raise HTTPException(422, {"detail": "Invalid condition_expr", "errors": errs})

    username = _get_username(current_user)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT 1 FROM runbooks WHERE name = %s AND enabled = true",
                (body.runbook_name,),
            )
            if not cur.fetchone():
                raise HTTPException(400, f"Runbook '{body.runbook_name}' not found or disabled")

            cur.execute(
                """
                INSERT INTO clea_policies
                    (event_type, condition_expr, runbook_name, approval_mode, enabled, created_by)
                VALUES (%s, %s::jsonb, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    body.event_type,
                    json.dumps(body.condition_expr),
                    body.runbook_name,
                    body.approval_mode,
                    body.enabled,
                    username,
                ),
            )
            return dict(cur.fetchone())


@router.put("/policies/{policy_id}")
async def update_policy(
    policy_id: int,
    body: CleaPolicyUpdate,
    _: Any = Depends(require_permission("clea", "write")),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    if "approval_mode" in updates and updates["approval_mode"] not in _VALID_APPROVAL_MODES:
        raise HTTPException(400, f"approval_mode must be one of {sorted(_VALID_APPROVAL_MODES)}")

    if "condition_expr" in updates and updates["condition_expr"]:
        errs = _validate_condition_expr(updates["condition_expr"])
        if errs:
            raise HTTPException(422, {"detail": "Invalid condition_expr", "errors": errs})

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM clea_policies WHERE id = %s", (policy_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Policy not found")

            if "runbook_name" in updates:
                cur.execute(
                    "SELECT 1 FROM runbooks WHERE name = %s AND enabled = true",
                    (updates["runbook_name"],),
                )
                if not cur.fetchone():
                    raise HTTPException(400, f"Runbook '{updates['runbook_name']}' not found or disabled")

            set_parts: list[str] = []
            vals: list[Any] = []
            for field, val in updates.items():
                if field == "condition_expr":
                    set_parts.append(f"{field} = %s::jsonb")
                    vals.append(json.dumps(val))
                else:
                    set_parts.append(f"{field} = %s")
                    vals.append(val)
            set_parts.append("updated_at = now()")
            vals.append(policy_id)

            cur.execute(
                f"UPDATE clea_policies SET {', '.join(set_parts)} WHERE id = %s RETURNING *",  # nosec B608 — column names from Pydantic model, values parameterized
                vals,
            )
            return dict(cur.fetchone())


@router.patch("/policies/{policy_id}/toggle")
async def toggle_policy(
    policy_id: int,
    _: Any = Depends(require_permission("clea", "write")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE clea_policies
                SET enabled = NOT enabled, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (policy_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Policy not found")
            return dict(row)


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: int,
    _: Any = Depends(require_permission("clea", "write")),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM clea_policies WHERE id = %s", (policy_id,))
            if cur.rowcount == 0:
                raise HTTPException(404, "Policy not found")


# ---------------------------------------------------------------------------
# Execution log
# ---------------------------------------------------------------------------

@router.get("/executions")
async def list_executions(
    limit: int = Query(default=50, ge=1, le=200),
    _: Any = Depends(require_permission("clea", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    ce.*,
                    cp.event_type,
                    cp.runbook_name,
                    cp.approval_mode
                FROM clea_executions ce
                JOIN clea_policies cp ON ce.policy_id = cp.id
                ORDER BY ce.triggered_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


@router.post("/executions/{exec_id}/approve")
async def approve_clea_execution(
    exec_id: int,
    current_user: Any = Depends(require_permission("clea", "write")),
):
    username = _get_username(current_user)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ce.*, cp.runbook_name
                FROM clea_executions ce
                JOIN clea_policies cp ON ce.policy_id = cp.id
                WHERE ce.id = %s
                """,
                (exec_id,),
            )
            rec = cur.fetchone()
            if not rec:
                raise HTTPException(404, "CLEA execution not found")
            if rec["approval_status"] != "pending":
                raise HTTPException(409, f"Execution is '{rec['approval_status']}', not pending")

            cur.execute(
                """
                UPDATE clea_executions
                SET approval_status = 'approved', approved_by = %s, approved_at = now()
                WHERE id = %s
                """,
                (username, exec_id),
            )

    # Trigger runbook outside the DB transaction
    _trigger_runbook_for_clea(exec_id, rec["runbook_name"], username)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM clea_executions WHERE id = %s", (exec_id,))
            return dict(cur.fetchone())


@router.post("/executions/{exec_id}/reject")
async def reject_clea_execution(
    exec_id: int,
    current_user: Any = Depends(require_permission("clea", "write")),
):
    username = _get_username(current_user)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT 1 FROM clea_executions WHERE id = %s AND approval_status = 'pending'",
                (exec_id,),
            )
            if not cur.fetchone():
                raise HTTPException(404, "Pending CLEA execution not found")

            cur.execute(
                """
                UPDATE clea_executions
                SET approval_status = 'rejected', approved_by = %s, approved_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (username, exec_id),
            )
            return dict(cur.fetchone())


# ---------------------------------------------------------------------------
# Internal: policy evaluation  (called from event_bus.py)
# ---------------------------------------------------------------------------

def evaluate_clea_policies(
    event_id: Optional[int],
    event_type: str,
    metadata: dict,
) -> None:
    """
    Match policies against the just-emitted event and either auto-trigger
    the linked runbook or create a pending-approval record.

    Always safe to call — all exceptions are caught and logged at DEBUG.
    Designed to run in the event-bus background thread.
    """
    try:
        _do_evaluate(event_id, event_type, metadata)
    except Exception:
        logger.debug("clea: evaluation error for %r", event_type, exc_info=True)


def _do_evaluate(event_id: Optional[int], event_type: str, metadata: dict) -> None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM clea_policies
                WHERE event_type = %s
                  AND enabled = true
                  AND approval_mode != 'disabled'
                """,
                (event_type,),
            )
            policies = cur.fetchall()

    for policy in policies:
        try:
            _process_policy(dict(policy), event_id, metadata)
        except Exception:
            logger.debug(
                "clea: failed to process policy %s for %r",
                policy["id"],
                event_type,
                exc_info=True,
            )


def _condition_matches(condition_expr: dict, metadata: dict) -> bool:
    """
    Match condition_expr against event metadata.

    Supports:
      - Shorthand: {"severity": "critical"} → implicit eq
      - Full: {"severity": {"op": "eq", "value": "critical"}}
      - Operators: eq, neq, in (list), contains (substring)
      - metadata.* dot-path keys: {"metadata.runway_days": {"op": "eq", "value": 3}}
    Empty condition_expr = match all.
    """
    if not condition_expr:
        return True
    for key, expected in condition_expr.items():
        # Resolve actual value from metadata
        if isinstance(key, str) and key.startswith("metadata."):
            dot_key = key[len("metadata."):]
            actual = metadata.get(dot_key)
        else:
            actual = metadata.get(key)

        # Parse operator and target value
        if isinstance(expected, dict):
            op = expected.get("op", "eq")
            target = expected.get("value")
        else:
            op = "eq"
            target = expected

        # Apply operator
        if op == "eq":
            if actual != target:
                return False
        elif op == "neq":
            if actual == target:
                return False
        elif op == "in":
            if not isinstance(target, list) or actual not in target:
                return False
        elif op == "contains":
            if not isinstance(actual, str) or not isinstance(target, str) or target not in actual:
                return False
        else:
            # Unknown operator — fail safe
            return False
    return True


def _process_policy(policy: dict, event_id: Optional[int], metadata: dict) -> None:
    condition = policy.get("condition_expr") or {}
    if not _condition_matches(condition, metadata):
        return

    initial_status = "approved" if policy["approval_mode"] == "auto" else "pending"

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO clea_executions (policy_id, event_id, approval_status)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (policy["id"], event_id, initial_status),
            )
            exec_id = cur.fetchone()["id"]

    if policy["approval_mode"] == "auto":
        _trigger_runbook_for_clea(exec_id, policy["runbook_name"], "clea-auto")


def _trigger_runbook_for_clea(exec_id: int, runbook_name: str, actor: str) -> None:
    """Create a runbook execution record and run the engine. Updates clea_executions on completion."""
    try:
        from runbook_routes import _execute_runbook  # lazy — avoids circular import at module load

        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO runbook_executions
                        (runbook_name, status, dry_run, parameters, triggered_by)
                    VALUES (%s, 'approved', true, %s, %s)
                    RETURNING execution_id
                    """,
                    (runbook_name, json.dumps({}), actor),
                )
                rb_exec_id = cur.fetchone()["execution_id"]

                cur.execute(
                    """
                    UPDATE clea_executions
                    SET execution_id = %s, approval_status = 'executed'
                    WHERE id = %s
                    """,
                    (rb_exec_id, exec_id),
                )

        # Run the engine (already in a background thread when called from event_bus)
        _execute_runbook(rb_exec_id, runbook_name, {}, True, actor)

    except Exception:
        logger.warning(
            "clea: failed to trigger runbook %r for exec %s",
            runbook_name,
            exec_id,
            exc_info=True,
        )
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE clea_executions SET result = %s::jsonb WHERE id = %s",
                        (json.dumps({"error": "trigger failed"}), exec_id),
                    )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_username(user: Any) -> str:
    if isinstance(user, dict):
        return user.get("username", "unknown")
    return getattr(user, "username", str(user))
