"""
Snapshot Management API Endpoints
Handles snapshot policy sets, assignments, exclusions, runs, and records
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field, validator
from fastapi import HTTPException, status, Depends
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import logging
import os

from auth import require_permission, get_current_user, User
from db_pool import get_connection

logger = logging.getLogger("snapshot_management")


# ============================================================================
# Pydantic Models
# ============================================================================

class SnapshotPolicySetCreate(BaseModel):
    """Request model for creating a snapshot policy set"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    is_global: bool = False
    tenant_id: Optional[str] = None
    tenant_name: Optional[str] = None
    policies: List[str] = Field(..., min_items=1)  # ["daily_5", "weekly_4"]
    retention_map: Dict[str, int] = Field(..., min_items=1)  # {"daily_5": 5}
    priority: int = Field(default=0, ge=0, le=1000)
    
    @validator('policies')
    def validate_policies(cls, v):
        if not v:
            raise ValueError("At least one policy must be specified")
        return v
    
    @validator('retention_map')
    def validate_retention_map(cls, v, values):
        if 'policies' in values:
            for policy in values['policies']:
                if policy not in v:
                    raise ValueError(f"retention_map must include all policies. Missing: {policy}")
        return v


class SnapshotPolicySetUpdate(BaseModel):
    """Request model for updating a snapshot policy set"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    policies: Optional[List[str]] = None
    retention_map: Optional[Dict[str, int]] = None
    priority: Optional[int] = Field(None, ge=0, le=1000)
    is_active: Optional[bool] = None


class SnapshotAssignmentCreate(BaseModel):
    """Request model for creating a snapshot assignment"""
    volume_id: str
    volume_name: Optional[str] = None
    tenant_id: str
    tenant_name: Optional[str] = None
    project_id: str
    project_name: Optional[str] = None
    vm_id: Optional[str] = None
    vm_name: Optional[str] = None
    policy_set_id: Optional[int] = None
    auto_snapshot: bool = True
    policies: List[str] = Field(..., min_items=1)
    retention_map: Dict[str, int] = Field(..., min_items=1)
    assignment_source: str = Field(default="manual")
    matched_rules: Optional[Dict] = None


class SnapshotAssignmentUpdate(BaseModel):
    """Request model for updating a snapshot assignment"""
    auto_snapshot: Optional[bool] = None
    policies: Optional[List[str]] = None
    retention_map: Optional[Dict[str, int]] = None
    policy_set_id: Optional[int] = None


class SnapshotExclusionCreate(BaseModel):
    """Request model for creating a snapshot exclusion"""
    volume_id: str
    volume_name: Optional[str] = None
    tenant_id: Optional[str] = None
    tenant_name: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    exclusion_reason: Optional[str] = None
    exclusion_source: str = Field(default="manual")
    expires_at: Optional[datetime] = None


class SnapshotRunCreate(BaseModel):
    """Request model for creating/starting a snapshot run"""
    run_type: str  # "daily_5", "weekly_4", "monthly_1st", "manual"
    dry_run: bool = False
    trigger_source: str = Field(default="manual")
    execution_host: Optional[str] = None


class SnapshotRecordCreate(BaseModel):
    """Request model for creating a snapshot record"""
    snapshot_run_id: int
    action: str  # "created", "deleted", "failed", "skipped"
    snapshot_id: Optional[str] = None
    snapshot_name: Optional[str] = None
    volume_id: str
    volume_name: Optional[str] = None
    tenant_id: str
    tenant_name: Optional[str] = None
    project_id: str
    project_name: Optional[str] = None
    vm_id: Optional[str] = None
    vm_name: Optional[str] = None
    policy_name: Optional[str] = None
    size_gb: Optional[int] = None
    retention_days: Optional[int] = None
    status: str = Field(default="pending")
    error_message: Optional[str] = None
    openstack_created_at: Optional[datetime] = None
    raw_snapshot_json: Optional[Dict] = None


# ============================================================================
# Helper Functions
# ============================================================================

def _parse_policy_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    normalized = str(value).replace(";", ",")
    return [p.strip() for p in normalized.split(",") if p.strip()]


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_compliance_from_volumes(
    cur: RealDictCursor,
    days: int,
    tenant_id: Optional[str],
    project_id: Optional[str],
    policy_filter: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Build compliance rows directly from the volumes table metadata.
    This is the primary compliance data source — volumes with auto_snapshot=true
    are the authoritative list.  Each volume × policy is a separate row.

    Name resolution:
      - volume name  → volumes.name
      - project name → projects.name  (via volumes.project_id)
      - tenant/domain name → domains.name (via projects.domain_id)
      - VM name      → servers.name  (via volumes.raw_json→attachments→server_id)

    Retention per policy is read from volume metadata keys like
    "retention_daily_5", "retention_monthly_1st", etc.

    Last-snapshot timestamps and snapshot counts are derived directly from
    the snapshots table using OpenStack metadata (created_by, policy) stored
    in each snapshot's raw_json.  This is more reliable than snapshot_records
    which may have gaps.

    Manual snapshots (those without created_by=p9_auto_snapshots metadata)
    are counted separately and are never touched by automation.

    This means policies that have never run (e.g. monthly_1st before the
    1st of the month) will correctly show 0 snapshots and no last-snapshot
    timestamp.
    """

    # ---- per-policy stats: directly from snapshot metadata -----------------
    # The snapshots table raw_json->'metadata' has 'created_by' and 'policy'
    # set by p9_auto_snapshots.  This is the authoritative source.
    cur.execute(
        """
        SELECT s.volume_id,
               s.raw_json->'metadata'->>'policy' AS policy_name,
               COUNT(*)        AS snapshot_count,
               MAX(s.created_at) AS last_snapshot_at
        FROM snapshots s
        WHERE s.status IN ('available', 'in-use')
          AND s.raw_json->'metadata'->>'created_by' = 'p9_auto_snapshots'
          AND s.raw_json->'metadata'->>'policy' IS NOT NULL
        GROUP BY s.volume_id, s.raw_json->'metadata'->>'policy'
        """
    )
    policy_stats = {
        (row["volume_id"], row["policy_name"]): {
            "snapshot_count":   row["snapshot_count"],
            "last_snapshot_at": row["last_snapshot_at"],
        }
        for row in cur.fetchall()
    }

    # ---- volumes with auto_snapshot metadata, enriched with names ----------
    cur.execute(
        """
        SELECT
            v.id              AS volume_id,
            v.name            AS volume_name,
            v.project_id,
            v.volume_type,
            proj.name         AS project_name,
            proj.domain_id    AS tenant_id,
            dom.name          AS tenant_name,
            v.raw_json->'attachments'->0->>'server_id' AS vm_id,
            srv.name          AS vm_name,
            v.raw_json->'metadata' AS metadata
        FROM volumes v
        LEFT JOIN projects proj ON proj.id = v.project_id
        LEFT JOIN domains  dom  ON dom.id  = proj.domain_id
        LEFT JOIN servers  srv  ON srv.id  = v.raw_json->'attachments'->0->>'server_id'
        WHERE v.raw_json->'metadata'->>'auto_snapshot'
                  IN ('true', 'True', '1', 'yes')
          AND v.raw_json->'metadata'->>'snapshot_policies' IS NOT NULL
        """
    )
    rows = cur.fetchall()
    now = datetime.now(timezone.utc)
    compliance_rows: List[Dict[str, Any]] = []

    # Determine which policies have EVER produced at least one snapshot.
    # If a policy has zero snapshots across ALL volumes, it hasn't had its
    # first scheduled run yet → volumes should show "Pending" not "Missing".
    policies_that_have_run = set()
    for (_, pname) in policy_stats:
        policies_that_have_run.add(pname)

    for row in rows:
        row_project_id = row.get("project_id")
        row_tenant_id = row.get("tenant_id")

        if tenant_id and row_tenant_id != tenant_id:
            continue
        if project_id and row_project_id != project_id:
            continue

        metadata = row.get("metadata") or {}
        policies = _parse_policy_list(metadata.get("snapshot_policies"))
        vol_id = row["volume_id"]

        for policy_name in policies:
            if policy_filter and policy_name != policy_filter:
                continue

            retention = _safe_int(metadata.get(f"retention_{policy_name}")) or 0

            # Strictly per-policy: from snapshot metadata directly
            pstat = policy_stats.get((vol_id, policy_name), {})
            last_snapshot_at = pstat.get("last_snapshot_at")
            policy_snap_count = pstat.get("snapshot_count", 0)

            # Determine compliance status:
            #  - "compliant": has a snapshot within the time window
            #  - "missing":  policy has run before but this volume is overdue
            #  - "pending":  policy has NEVER run for ANY volume yet
            if last_snapshot_at and last_snapshot_at >= (now - timedelta(days=days)):
                comp_status = "compliant"
                compliant = True
            elif policy_name not in policies_that_have_run:
                comp_status = "pending"
                compliant = False
            else:
                comp_status = "missing"
                compliant = False

            vol_name = row.get("volume_name")
            compliance_rows.append({
                "volume_id":        vol_id,
                "volume_name":      vol_name if vol_name else vol_id,
                "volume_type":      row.get("volume_type") or "",
                "tenant_id":        row_tenant_id or "",
                "tenant_name":      row.get("tenant_name") or row_tenant_id or "",
                "project_id":       row_project_id or "",
                "project_name":     row.get("project_name") or row_project_id or "",
                "vm_id":            row.get("vm_id") or "",
                "vm_name":          row.get("vm_name") or row.get("vm_id") or "",
                "policy_name":      policy_name,
                "retention_days":   retention,
                "snapshot_count":   policy_snap_count,
                "last_snapshot_at": last_snapshot_at,
                "compliant":        compliant,
                "status":           comp_status,
            })

    # Sort: pending last, then non-compliant, then compliant
    status_order = {"missing": 0, "compliant": 1, "pending": 2}
    min_time = datetime.min.replace(tzinfo=timezone.utc)
    compliance_rows.sort(
        key=lambda r: (status_order.get(r.get("status"), 0),
                       r.get("last_snapshot_at") or min_time),
        reverse=False,
    )
    return compliance_rows


# ============================================================================
# API Endpoint Functions
# ============================================================================

def setup_snapshot_routes(app, get_db_connection):
    """
    Setup all snapshot management routes
    
    Args:
        app: FastAPI application instance
        get_db_connection: Function to get database connection
    """
    
    # ========================================================================
    # Snapshot Policy Sets
    # ========================================================================
    
    @app.get("/snapshot/policy-sets")
    async def get_policy_sets(
        is_global: Optional[bool] = None,
        tenant_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_policy_sets", "read"))
    ):
        """Get all snapshot policy sets with optional filtering"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                query = """
                    SELECT id, name, description, is_global, tenant_id, tenant_name,
                           policies, retention_map, priority, is_active,
                           created_at, created_by, updated_at, updated_by
                    FROM snapshot_policy_sets
                    WHERE 1=1
                """
                params = []

                if is_global is not None:
                    query += " AND is_global = %s"
                    params.append(is_global)

                if tenant_id is not None:
                    query += " AND tenant_id = %s"
                    params.append(tenant_id)

                if is_active is not None:
                    query += " AND is_active = %s"
                    params.append(is_active)

                query += " ORDER BY priority DESC, created_at DESC"

                cur.execute(query, params)
                results = cur.fetchall()

                return {"policy_sets": results, "count": len(results)}

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve policy sets: {str(e)}"
            )
    
    @app.post("/snapshot/policy-sets", status_code=status.HTTP_201_CREATED)
    async def create_policy_set(
        policy_set: SnapshotPolicySetCreate,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_policy_sets", "write"))
    ):
        """Create a new snapshot policy set"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute("""
                    INSERT INTO snapshot_policy_sets 
                    (name, description, is_global, tenant_id, tenant_name, policies, 
                     retention_map, priority, created_by, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                    RETURNING id, name, description, is_global, tenant_id, tenant_name,
                              policies, retention_map, priority, is_active, created_at
                """, (
                    policy_set.name,
                    policy_set.description,
                    policy_set.is_global,
                    policy_set.tenant_id,
                    policy_set.tenant_name,
                    json.dumps(policy_set.policies),
                    json.dumps(policy_set.retention_map),
                    policy_set.priority,
                    current_user.username,
                    current_user.username
                ))

                result = cur.fetchone()

                return result

        except psycopg2.IntegrityError as e:
            if "unique_global_policy_name" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Policy set with name '{policy_set.name}' already exists for this tenant"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Database integrity error: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create policy set: {str(e)}"
            )
    
    @app.get("/snapshot/policy-sets/{policy_set_id}")
    async def get_policy_set(
        policy_set_id: int,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_policy_sets", "read"))
    ):
        """Get a specific snapshot policy set by ID"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute("""
                    SELECT id, name, description, is_global, tenant_id, tenant_name,
                           policies, retention_map, priority, is_active,
                           created_at, created_by, updated_at, updated_by
                    FROM snapshot_policy_sets
                    WHERE id = %s
                """, (policy_set_id,))

                result = cur.fetchone()

                if not result:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Policy set {policy_set_id} not found"
                    )

                return result

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve policy set: {str(e)}"
            )
    
    @app.patch("/snapshot/policy-sets/{policy_set_id}")
    async def update_policy_set(
        policy_set_id: int,
        updates: SnapshotPolicySetUpdate,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_policy_sets", "write"))
    ):
        """Update an existing snapshot policy set"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Build dynamic UPDATE query
                update_fields = []
                params = []

                if updates.name is not None:
                    update_fields.append("name = %s")
                    params.append(updates.name)
                if updates.description is not None:
                    update_fields.append("description = %s")
                    params.append(updates.description)
                if updates.policies is not None:
                    update_fields.append("policies = %s::jsonb")
                    params.append(json.dumps(updates.policies))
                if updates.retention_map is not None:
                    update_fields.append("retention_map = %s::jsonb")
                    params.append(json.dumps(updates.retention_map))
                if updates.priority is not None:
                    update_fields.append("priority = %s")
                    params.append(updates.priority)
                if updates.is_active is not None:
                    update_fields.append("is_active = %s")
                    params.append(updates.is_active)

                if not update_fields:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No fields to update"
                    )

                update_fields.append("updated_by = %s")
                params.append(current_user.username)
                update_fields.append("updated_at = now()")

                params.append(policy_set_id)

                query = f"""
                    UPDATE snapshot_policy_sets
                    SET {', '.join(update_fields)}
                    WHERE id = %s
                    RETURNING id, name, description, is_global, tenant_id, tenant_name,
                              policies, retention_map, priority, is_active,
                              created_at, updated_at, updated_by
                """

                cur.execute(query, params)
                result = cur.fetchone()

                if not result:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Policy set {policy_set_id} not found"
                    )

                return result

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update policy set: {str(e)}"
            )
    
    @app.delete("/snapshot/policy-sets/{policy_set_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_policy_set(
        policy_set_id: int,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_policy_sets", "admin"))
    ):
        """Delete a snapshot policy set"""
        try:
            with get_connection() as conn:
                cur = conn.cursor()

                cur.execute("DELETE FROM snapshot_policy_sets WHERE id = %s", (policy_set_id,))

                if cur.rowcount == 0:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Policy set {policy_set_id} not found"
                    )

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete policy set: {str(e)}"
            )
    
    # ========================================================================
    # Snapshot Assignments
    # ========================================================================
    
    @app.get("/snapshot/assignments")
    async def get_assignments(
        volume_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
        vm_id: Optional[str] = None,
        auto_snapshot: Optional[bool] = None,
        limit: int = 1000,
        offset: int = 0,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_assignments", "read"))
    ):
        """Get snapshot assignments with optional filtering"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                query = """
                    SELECT id, volume_id, volume_name, tenant_id, tenant_name,
                           project_id, project_name, vm_id, vm_name, policy_set_id,
                           auto_snapshot, policies, retention_map, assignment_source,
                           matched_rules, created_at, created_by, updated_at, updated_by,
                           last_verified_at
                    FROM snapshot_assignments
                    WHERE 1=1
                """
                params = []

                if volume_id:
                    query += " AND volume_id = %s"
                    params.append(volume_id)
                if tenant_id:
                    query += " AND tenant_id = %s"
                    params.append(tenant_id)
                if project_id:
                    query += " AND project_id = %s"
                    params.append(project_id)
                if vm_id:
                    query += " AND vm_id = %s"
                    params.append(vm_id)
                if auto_snapshot is not None:
                    query += " AND auto_snapshot = %s"
                    params.append(auto_snapshot)

                query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cur.execute(query, params)
                results = cur.fetchall()

                return {"assignments": results, "count": len(results), "limit": limit, "offset": offset}

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve assignments: {str(e)}"
            )
    
    @app.post("/snapshot/assignments", status_code=status.HTTP_201_CREATED)
    async def create_assignment(
        assignment: SnapshotAssignmentCreate,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_assignments", "write"))
    ):
        """Create a new snapshot assignment for a volume"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute("""
                    INSERT INTO snapshot_assignments
                    (volume_id, volume_name, tenant_id, tenant_name, project_id, project_name,
                     vm_id, vm_name, policy_set_id, auto_snapshot, policies, retention_map,
                     assignment_source, matched_rules, created_by, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s, %s)
                    RETURNING id, volume_id, volume_name, tenant_id, tenant_name, project_id,
                              project_name, vm_id, vm_name, policy_set_id, auto_snapshot,
                              policies, retention_map, assignment_source, created_at
                """, (
                    assignment.volume_id, assignment.volume_name,
                    assignment.tenant_id, assignment.tenant_name,
                    assignment.project_id, assignment.project_name,
                    assignment.vm_id, assignment.vm_name,
                    assignment.policy_set_id, assignment.auto_snapshot,
                    json.dumps(assignment.policies),
                    json.dumps(assignment.retention_map),
                    assignment.assignment_source,
                    json.dumps(assignment.matched_rules) if assignment.matched_rules else None,
                    current_user.username, current_user.username
                ))

                result = cur.fetchone()

                return result

        except psycopg2.IntegrityError as e:
            if "unique_volume_assignment" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Assignment already exists for volume {assignment.volume_id}"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Database integrity error: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create assignment: {str(e)}"
            )
    
    @app.get("/snapshot/assignments/{volume_id}")
    async def get_assignment(
        volume_id: str,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_assignments", "read"))
    ):
        """Get snapshot assignment for a specific volume"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute("""
                    SELECT id, volume_id, volume_name, tenant_id, tenant_name,
                           project_id, project_name, vm_id, vm_name, policy_set_id,
                           auto_snapshot, policies, retention_map, assignment_source,
                           matched_rules, created_at, created_by, updated_at, updated_by,
                           last_verified_at
                    FROM snapshot_assignments
                    WHERE volume_id = %s
                """, (volume_id,))

                result = cur.fetchone()

                if not result:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No assignment found for volume {volume_id}"
                    )

                return result

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve assignment: {str(e)}"
            )
    
    @app.patch("/snapshot/assignments/{volume_id}")
    async def update_assignment(
        volume_id: str,
        updates: SnapshotAssignmentUpdate,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_assignments", "write"))
    ):
        """Update an existing snapshot assignment"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                update_fields = []
                params = []

                if updates.auto_snapshot is not None:
                    update_fields.append("auto_snapshot = %s")
                    params.append(updates.auto_snapshot)
                if updates.policies is not None:
                    update_fields.append("policies = %s::jsonb")
                    params.append(json.dumps(updates.policies))
                if updates.retention_map is not None:
                    update_fields.append("retention_map = %s::jsonb")
                    params.append(json.dumps(updates.retention_map))
                if updates.policy_set_id is not None:
                    update_fields.append("policy_set_id = %s")
                    params.append(updates.policy_set_id)

                if not update_fields:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No fields to update"
                    )

                update_fields.append("updated_by = %s")
                params.append(current_user.username)
                update_fields.append("updated_at = now()")

                params.append(volume_id)

                query = f"""
                    UPDATE snapshot_assignments
                    SET {', '.join(update_fields)}
                    WHERE volume_id = %s
                    RETURNING id, volume_id, volume_name, tenant_id, tenant_name,
                              project_id, project_name, vm_id, vm_name, policy_set_id,
                              auto_snapshot, policies, retention_map, updated_at, updated_by
                """

                cur.execute(query, params)
                result = cur.fetchone()

                if not result:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No assignment found for volume {volume_id}"
                    )

                return result

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update assignment: {str(e)}"
            )
    
    @app.delete("/snapshot/assignments/{volume_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_assignment(
        volume_id: str,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_assignments", "write"))
    ):
        """Delete a snapshot assignment"""
        try:
            with get_connection() as conn:
                cur = conn.cursor()

                cur.execute("DELETE FROM snapshot_assignments WHERE volume_id = %s", (volume_id,))

                if cur.rowcount == 0:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No assignment found for volume {volume_id}"
                    )

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete assignment: {str(e)}"
            )
    
    # ========================================================================
    # Snapshot Exclusions
    # ========================================================================
    
    @app.get("/snapshot/exclusions")
    async def get_exclusions(
        volume_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        include_expired: bool = False,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_exclusions", "read"))
    ):
        """Get snapshot exclusions with optional filtering"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                query = """
                    SELECT id, volume_id, volume_name, tenant_id, tenant_name,
                           project_id, project_name, exclusion_reason, exclusion_source,
                           created_at, created_by, expires_at
                    FROM snapshot_exclusions
                    WHERE 1=1
                """
                params = []

                if volume_id:
                    query += " AND volume_id = %s"
                    params.append(volume_id)
                if tenant_id:
                    query += " AND tenant_id = %s"
                    params.append(tenant_id)
                if not include_expired:
                    query += " AND (expires_at IS NULL OR expires_at > now())"

                query += " ORDER BY created_at DESC"

                cur.execute(query, params)
                results = cur.fetchall()

                return {"exclusions": results, "count": len(results)}

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve exclusions: {str(e)}"
            )
    
    @app.post("/snapshot/exclusions", status_code=status.HTTP_201_CREATED)
    async def create_exclusion(
        exclusion: SnapshotExclusionCreate,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_exclusions", "write"))
    ):
        """Create a new snapshot exclusion for a volume"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute("""
                    INSERT INTO snapshot_exclusions
                    (volume_id, volume_name, tenant_id, tenant_name, project_id, project_name,
                     exclusion_reason, exclusion_source, created_by, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, volume_id, volume_name, tenant_id, tenant_name,
                              project_id, project_name, exclusion_reason, exclusion_source,
                              created_at, created_by, expires_at
                """, (
                    exclusion.volume_id, exclusion.volume_name,
                    exclusion.tenant_id, exclusion.tenant_name,
                    exclusion.project_id, exclusion.project_name,
                    exclusion.exclusion_reason, exclusion.exclusion_source,
                    current_user.username, exclusion.expires_at
                ))

                result = cur.fetchone()

                return result

        except psycopg2.IntegrityError as e:
            if "unique_volume_exclusion" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Exclusion already exists for volume {exclusion.volume_id}"
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Database integrity error: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create exclusion: {str(e)}"
            )
    
    @app.delete("/snapshot/exclusions/{volume_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_exclusion(
        volume_id: str,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_exclusions", "write"))
    ):
        """Delete a snapshot exclusion"""
        try:
            with get_connection() as conn:
                cur = conn.cursor()

                cur.execute("DELETE FROM snapshot_exclusions WHERE volume_id = %s", (volume_id,))

                if cur.rowcount == 0:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"No exclusion found for volume {volume_id}"
                    )

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete exclusion: {str(e)}"
            )
    
    # ========================================================================
    # Snapshot Runs
    # ========================================================================
    
    @app.get("/snapshot/runs")
    async def get_runs(
        run_type: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_runs", "read"))
    ):
        """Get snapshot runs with optional filtering"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                query = """
                    SELECT id, run_type, started_at, finished_at, status, total_volumes,
                           snapshots_created, snapshots_deleted, snapshots_failed,
                           volumes_skipped, dry_run, triggered_by, trigger_source,
                           execution_host, error_summary, created_at
                    FROM snapshot_runs
                    WHERE 1=1
                """
                params = []

                if run_type:
                    query += " AND run_type = %s"
                    params.append(run_type)
                if status_filter:
                    query += " AND status = %s"
                    params.append(status_filter)

                query += " ORDER BY started_at DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cur.execute(query, params)
                results = cur.fetchall()

                return {"runs": results, "count": len(results), "limit": limit, "offset": offset}

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve snapshot runs: {str(e)}"
            )
    
    @app.post("/snapshot/runs", status_code=status.HTTP_201_CREATED)
    async def create_run(
        run: SnapshotRunCreate,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_runs", "write"))
    ):
        """Create/start a new snapshot run"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute("""
                    INSERT INTO snapshot_runs
                    (run_type, dry_run, triggered_by, trigger_source, execution_host, status)
                    VALUES (%s, %s, %s, %s, %s, 'running')
                    RETURNING id, run_type, started_at, status, dry_run, triggered_by,
                              trigger_source, execution_host, created_at
                """, (
                    run.run_type, run.dry_run, current_user.username,
                    run.trigger_source, run.execution_host
                ))

                result = cur.fetchone()

                return result

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create snapshot run: {str(e)}"
            )
    
    @app.get("/snapshot/runs/{run_id}")
    async def get_run(
        run_id: int,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_runs", "read"))
    ):
        """Get a specific snapshot run with details"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute("""
                    SELECT id, run_type, started_at, finished_at, status, total_volumes,
                           snapshots_created, snapshots_deleted, snapshots_failed,
                           volumes_skipped, dry_run, triggered_by, trigger_source,
                           execution_host, error_summary, raw_logs, created_at
                    FROM snapshot_runs
                    WHERE id = %s
                """, (run_id,))

                result = cur.fetchone()

                if not result:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Snapshot run {run_id} not found"
                    )

                # Get related snapshot records
                cur.execute("""
                    SELECT id, action, snapshot_id, snapshot_name, volume_id, volume_name,
                           tenant_name, project_name, vm_name, policy_name, size_gb,
                           status, error_message, created_at
                    FROM snapshot_records
                    WHERE snapshot_run_id = %s
                    ORDER BY created_at DESC
                """, (run_id,))

                records = cur.fetchall()
                result['records'] = records

                return result

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve snapshot run: {str(e)}"
            )
    
    @app.patch("/snapshot/runs/{run_id}")
    async def update_run(
        run_id: int,
        status_update: str,
        total_volumes: Optional[int] = None,
        snapshots_created: Optional[int] = None,
        snapshots_deleted: Optional[int] = None,
        snapshots_failed: Optional[int] = None,
        volumes_skipped: Optional[int] = None,
        error_summary: Optional[str] = None,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_runs", "write"))
    ):
        """Update a snapshot run (typically to mark as completed/failed)"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                update_fields = ["status = %s"]
                params = [status_update]

                if status_update in ['completed', 'failed', 'partial']:
                    update_fields.append("finished_at = now()")

                if total_volumes is not None:
                    update_fields.append("total_volumes = %s")
                    params.append(total_volumes)
                if snapshots_created is not None:
                    update_fields.append("snapshots_created = %s")
                    params.append(snapshots_created)
                if snapshots_deleted is not None:
                    update_fields.append("snapshots_deleted = %s")
                    params.append(snapshots_deleted)
                if snapshots_failed is not None:
                    update_fields.append("snapshots_failed = %s")
                    params.append(snapshots_failed)
                if volumes_skipped is not None:
                    update_fields.append("volumes_skipped = %s")
                    params.append(volumes_skipped)
                if error_summary is not None:
                    update_fields.append("error_summary = %s")
                    params.append(error_summary)

                params.append(run_id)

                query = f"""
                    UPDATE snapshot_runs
                    SET {', '.join(update_fields)}
                    WHERE id = %s
                    RETURNING id, run_type, started_at, finished_at, status,
                              total_volumes, snapshots_created, snapshots_deleted,
                              snapshots_failed, volumes_skipped
                """

                cur.execute(query, params)
                result = cur.fetchone()

                if not result:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Snapshot run {run_id} not found"
                    )

                return result

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update snapshot run: {str(e)}"
            )
    
    # ========================================================================
    # Snapshot Records
    # ========================================================================
    
    @app.get("/snapshot/records")
    async def get_records(
        snapshot_run_id: Optional[int] = None,
        volume_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_records", "read"))
    ):
        """Get snapshot records with optional filtering"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                query = """
                    SELECT id, snapshot_run_id, action, snapshot_id, snapshot_name,
                           volume_id, volume_name, tenant_id, tenant_name, project_id,
                           project_name, vm_id, vm_name, policy_name, size_gb,
                           created_at, deleted_at, retention_days, status, error_message,
                           openstack_created_at
                    FROM snapshot_records
                    WHERE 1=1
                """
                params = []

                if snapshot_run_id:
                    query += " AND snapshot_run_id = %s"
                    params.append(snapshot_run_id)
                if volume_id:
                    query += " AND volume_id = %s"
                    params.append(volume_id)
                if tenant_id:
                    query += " AND tenant_id = %s"
                    params.append(tenant_id)
                if action:
                    query += " AND action = %s"
                    params.append(action)

                query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cur.execute(query, params)
                results = cur.fetchall()

                return {"records": results, "count": len(results), "limit": limit, "offset": offset}

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve snapshot records: {str(e)}"
            )
    
    @app.post("/snapshot/records", status_code=status.HTTP_201_CREATED)
    async def create_record(
        record: SnapshotRecordCreate,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_records", "write"))
    ):
        """Create a new snapshot record"""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute("""
                    INSERT INTO snapshot_records
                    (snapshot_run_id, action, snapshot_id, snapshot_name, volume_id,
                     volume_name, tenant_id, tenant_name, project_id, project_name,
                     vm_id, vm_name, policy_name, size_gb, retention_days, status,
                     error_message, openstack_created_at, raw_snapshot_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id, snapshot_run_id, action, snapshot_id, snapshot_name,
                              volume_id, volume_name, tenant_name, project_name, vm_name,
                              policy_name, size_gb, status, created_at
                """, (
                    record.snapshot_run_id, record.action, record.snapshot_id,
                    record.snapshot_name, record.volume_id, record.volume_name,
                    record.tenant_id, record.tenant_name, record.project_id,
                    record.project_name, record.vm_id, record.vm_name,
                    record.policy_name, record.size_gb, record.retention_days,
                    record.status, record.error_message, record.openstack_created_at,
                    json.dumps(record.raw_snapshot_json) if record.raw_snapshot_json else None
                ))

                result = cur.fetchone()

                return result

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create snapshot record: {str(e)}"
            )

    # ========================================================================
    # Snapshot Compliance Report
    # ========================================================================

    @app.get("/snapshot/compliance")
    async def get_snapshot_compliance(
        days: int = 2,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
        policy: Optional[str] = None,
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshot_records", "read"))
    ):
        """Get snapshot compliance status per volume+policy.

        Builds compliance rows directly from volumes table metadata,
        enriched with project/domain/server names via JOINs and
        snapshot counts/timestamps from snapshot metadata.

        Also returns a separate manual_snapshots list for snapshots
        not created by automation (no created_by=p9_auto_snapshots
        metadata).  These are never touched by retention / cleanup.
        """
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                rows = _build_compliance_from_volumes(
                    cur, days, tenant_id, project_id, policy
                )

                # ---- manual snapshots detail -----------------------------------
                cur.execute(
                    """
                    SELECT s.id            AS snapshot_id,
                           s.name          AS snapshot_name,
                           s.volume_id,
                           v.name          AS volume_name,
                           s.project_id,
                           proj.name       AS project_name,
                           proj.domain_id  AS tenant_id,
                           dom.name        AS tenant_name,
                           s.size_gb,
                           s.status,
                           s.created_at
                    FROM snapshots s
                    LEFT JOIN volumes  v    ON v.id    = s.volume_id
                    LEFT JOIN projects proj ON proj.id = s.project_id
                    LEFT JOIN domains  dom  ON dom.id  = proj.domain_id
                    WHERE s.status IN ('available', 'in-use')
                      AND (s.raw_json->'metadata'->>'created_by' IS NULL
                           OR s.raw_json->'metadata'->>'created_by'
                                  != 'p9_auto_snapshots')
                    ORDER BY s.created_at DESC
                    """
                )
                manual_snapshots = []
                for r in cur.fetchall():
                    manual_snapshots.append({
                        "snapshot_id":   r["snapshot_id"],
                        "snapshot_name": r["snapshot_name"] or r["snapshot_id"],
                        "volume_id":     r["volume_id"] or "",
                        "volume_name":   r["volume_name"] or r["volume_id"] or "",
                        "project_id":    r["project_id"] or "",
                        "project_name":  r["project_name"] or r["project_id"] or "",
                        "tenant_id":     r["tenant_id"] or "",
                        "tenant_name":   r["tenant_name"] or r["tenant_id"] or "",
                        "size_gb":       r["size_gb"],
                        "status":        r["status"],
                        "created_at":    r["created_at"],
                    })

                compliant_count = sum(1 for r in rows if r.get("status") == "compliant")
                noncompliant_count = sum(1 for r in rows if r.get("status") == "missing")
                pending_count = sum(1 for r in rows if r.get("status") == "pending")

                return {
                    "rows": rows,
                    "count": len(rows),
                    "summary": {
                        "compliant": compliant_count,
                        "noncompliant": noncompliant_count,
                        "pending": pending_count,
                        "days": days,
                    },
                    "manual_snapshots": manual_snapshots,
                }

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve compliance report: {str(e)}"
            )

    # ========================================================================
    # On-Demand Snapshot Pipeline  ("Sync & Snapshot Now")
    # ========================================================================

    @app.post("/snapshot/run-now", status_code=status.HTTP_202_ACCEPTED)
    async def run_snapshot_now(
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshots", "admin"))
    ):
        """
        Trigger the full snapshot pipeline on demand.
        Writes a 'pending' row to snapshot_on_demand_runs which the
        snapshot_worker picks up on its next polling cycle (≤ 10 s).
        Returns immediately with a job ID; poll GET /snapshot/run-now/status.
        """
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Reject if a run is already pending or running
                cur.execute("""
                    SELECT job_id FROM snapshot_on_demand_runs
                    WHERE status IN ('pending', 'running')
                    ORDER BY created_at DESC LIMIT 1
                """)
                active = cur.fetchone()
                if active:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="An on-demand snapshot pipeline is already pending or running."
                    )

                import uuid
                job_id = str(uuid.uuid4())

                initial_steps = json.dumps([
                    {"key": "policy_assign", "label": "Policy Assignment", "status": "pending"},
                    {"key": "rvtools_pre", "label": "Inventory Sync (pre-snapshot)", "status": "pending"},
                    {"key": "auto_snapshots", "label": "Auto Snapshots", "status": "pending"},
                    {"key": "rvtools_post", "label": "Inventory Sync (post-snapshot)", "status": "pending"},
                ])

                cur.execute("""
                    INSERT INTO snapshot_on_demand_runs
                        (job_id, status, triggered_by, steps)
                    VALUES (%s, 'pending', %s, %s)
                    RETURNING job_id
                """, (job_id, current_user.username, initial_steps))

                return {
                    "job_id": job_id,
                    "status": "pending",
                    "message": "Snapshot pipeline queued. The worker will pick it up within 10 seconds. Poll /snapshot/run-now/status for progress.",
                }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to queue on-demand snapshot run: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to queue on-demand snapshot run: {str(e)}"
            )

    @app.get("/snapshot/run-now/status")
    async def get_run_now_status(
        current_user: User = Depends(get_current_user),
        _has_permission: bool = Depends(require_permission("snapshots", "read"))
    ):
        """Get the status of the most recent on-demand snapshot pipeline run."""
        try:
            with get_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute("""
                    SELECT job_id, status, triggered_by, started_at, finished_at,
                           steps, error, created_at
                    FROM snapshot_on_demand_runs
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                row = cur.fetchone()

                if not row:
                    return {"status": "idle", "message": "No on-demand run has been triggered yet."}

                return {
                    "job_id": str(row["job_id"]),
                    "status": row["status"],
                    "triggered_by": row["triggered_by"],
                    "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                    "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
                    "steps": row["steps"] if isinstance(row["steps"], list) else json.loads(row["steps"]) if row["steps"] else [],
                    "error": row["error"],
                }

        except Exception as e:
            logger.error(f"Failed to get on-demand status: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get on-demand status: {str(e)}"
            )
