"""
Navigation & Department Management API Routes
===============================================
Endpoints for the 3-layer visibility model:
  - Departments CRUD
  - Nav groups / items catalog
  - Department ↔ visibility mapping
  - Per-user visibility overrides
  - /auth/me extended response with navigation

RBAC:
  - viewer / operator / technical → read own navigation
  - admin / superadmin           → full CRUD on departments, catalog, visibility
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth import require_permission, require_authentication, get_current_user, User, has_permission, log_auth_event
from db_pool import get_connection

logger = logging.getLogger("pf9.navigation")

router = APIRouter(prefix="/api", tags=["navigation"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    sort_order: int = 0

class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None

class NavGroupCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=150)
    icon: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0
    is_default: bool = False

class NavGroupUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=150)
    icon: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None

class NavItemCreate(BaseModel):
    nav_group_id: int
    key: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=150)
    icon: Optional[str] = None
    route: str = Field(..., min_length=1, max_length=255)
    resource_key: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0

class NavItemUpdate(BaseModel):
    nav_group_id: Optional[int] = None
    label: Optional[str] = Field(None, min_length=1, max_length=150)
    icon: Optional[str] = None
    route: Optional[str] = None
    resource_key: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    is_action: Optional[bool] = None

class DepartmentVisibilityUpdate(BaseModel):
    """Set the complete visibility for a department."""
    nav_group_ids: List[int]
    nav_item_ids: List[int]

class UserNavOverrideCreate(BaseModel):
    username: str
    nav_item_id: int
    override_type: str = Field(..., pattern="^(grant|deny)$")
    reason: Optional[str] = None

class UserDepartmentUpdate(BaseModel):
    department_id: Optional[int] = None


# =====================================================================
# DEPARTMENTS CRUD
# =====================================================================

@router.get("/departments")
async def list_departments(
    request: Request,
    current_user: User = Depends(require_authentication),
):
    """List all departments."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, description, is_active, sort_order, created_at, updated_at
                FROM departments
                ORDER BY sort_order, name
            """)
            return cur.fetchall()


@router.post("/departments", status_code=201)
async def create_department(
    body: DepartmentCreate,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("departments", "admin")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO departments (name, description, sort_order)
                VALUES (%s, %s, %s)
                RETURNING id, name, description, is_active, sort_order, created_at, updated_at
            """, (body.name, body.description, body.sort_order))
            dept = cur.fetchone()
            # Auto-grant all nav groups + items to the new department (backward compat)
            cur.execute("""
                INSERT INTO department_nav_groups (department_id, nav_group_id)
                SELECT %s, id FROM nav_groups
                ON CONFLICT DO NOTHING
            """, (dept["id"],))
            cur.execute("""
                INSERT INTO department_nav_items (department_id, nav_item_id)
                SELECT %s, id FROM nav_items
                ON CONFLICT DO NOTHING
            """, (dept["id"],))
    log_auth_event(current_user.username, "department_created", True,
                   request.client.host if request.client else None,
                   details={"department": dept["name"]})
    return dept


@router.put("/departments/{dept_id}")
async def update_department(
    dept_id: int,
    body: DepartmentUpdate,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("departments", "admin")),
):
    fields, values = [], []
    for attr in ("name", "description", "sort_order", "is_active"):
        val = getattr(body, attr, None)
        if val is not None:
            fields.append(f"{attr} = %s")
            values.append(val)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields.append("updated_at = now()")
    values.append(dept_id)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                UPDATE departments SET {', '.join(fields)}
                WHERE id = %s
                RETURNING id, name, description, is_active, sort_order, created_at, updated_at
            """, values)
            dept = cur.fetchone()
            if not dept:
                raise HTTPException(404, "Department not found")
    return dept


@router.delete("/departments/{dept_id}")
async def delete_department(
    dept_id: int,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("departments", "admin")),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Don't delete if users are assigned
            cur.execute("SELECT COUNT(*) FROM user_roles WHERE department_id = %s", (dept_id,))
            cnt = cur.fetchone()[0]
            if cnt > 0:
                raise HTTPException(400, f"Cannot delete: {cnt} user(s) still assigned to this department")
            cur.execute("DELETE FROM departments WHERE id = %s", (dept_id,))
            if cur.rowcount == 0:
                raise HTTPException(404, "Department not found")
    return {"message": "Department deleted"}


# =====================================================================
# NAV GROUPS CRUD
# =====================================================================

@router.get("/nav/groups")
async def list_nav_groups(
    request: Request,
    current_user: User = Depends(require_authentication),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, key, label, icon, description, sort_order, is_active, is_default, created_at, updated_at
                FROM nav_groups
                ORDER BY sort_order, label
            """)
            return cur.fetchall()


@router.post("/nav/groups", status_code=201)
async def create_nav_group(
    body: NavGroupCreate,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("navigation", "admin")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # If setting as default, clear any existing default first
            if body.is_default:
                cur.execute("UPDATE nav_groups SET is_default = false WHERE is_default = true")
            cur.execute("""
                INSERT INTO nav_groups (key, label, icon, description, sort_order, is_default)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, key, label, icon, description, sort_order, is_active, is_default, created_at, updated_at
            """, (body.key, body.label, body.icon, body.description, body.sort_order, body.is_default))
            return cur.fetchone()


@router.put("/nav/groups/{group_id}")
async def update_nav_group(
    group_id: int,
    body: NavGroupUpdate,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("navigation", "admin")),
):
    fields, values = [], []
    for attr in ("label", "icon", "description", "sort_order", "is_active", "is_default"):
        val = getattr(body, attr, None)
        if val is not None:
            fields.append(f"{attr} = %s")
            values.append(val)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields.append("updated_at = now()")
    values.append(group_id)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # If setting as default, clear any existing default first
            if body.is_default:
                cur.execute("UPDATE nav_groups SET is_default = false WHERE is_default = true AND id != %s", (group_id,))
            cur.execute(f"""
                UPDATE nav_groups SET {', '.join(fields)}
                WHERE id = %s
                RETURNING id, key, label, icon, description, sort_order, is_active, is_default, created_at, updated_at
            """, values)
            grp = cur.fetchone()
            if not grp:
                raise HTTPException(404, "Nav group not found")
    return grp


@router.delete("/nav/groups/{group_id}")
async def delete_nav_group(
    group_id: int,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("navigation", "admin")),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM nav_groups WHERE id = %s", (group_id,))
            if cur.rowcount == 0:
                raise HTTPException(404, "Nav group not found")
    return {"message": "Nav group deleted"}


# =====================================================================
# NAV ITEMS CRUD
# =====================================================================

@router.get("/nav/items")
async def list_nav_items(
    request: Request,
    current_user: User = Depends(require_authentication),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT ni.id, ni.nav_group_id, ni.key, ni.label, ni.icon,
                       ni.route, ni.resource_key, ni.description, ni.sort_order,
                       ni.is_active, ni.is_action, ni.created_at, ni.updated_at,
                       ng.key AS group_key, ng.label AS group_label
                FROM nav_items ni
                JOIN nav_groups ng ON ng.id = ni.nav_group_id
                ORDER BY ng.sort_order, ni.sort_order, ni.label
            """)
            return cur.fetchall()


@router.post("/nav/items", status_code=201)
async def create_nav_item(
    body: NavItemCreate,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("navigation", "admin")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, description, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, nav_group_id, key, label, icon, route, resource_key, description, sort_order,
                          is_active, created_at, updated_at
            """, (body.nav_group_id, body.key, body.label, body.icon, body.route,
                  body.resource_key, body.description, body.sort_order))
            item = cur.fetchone()
            # Auto-add to all departments
            cur.execute("""
                INSERT INTO department_nav_items (department_id, nav_item_id)
                SELECT id, %s FROM departments
                ON CONFLICT DO NOTHING
            """, (item["id"],))
    return item


@router.put("/nav/items/{item_id}")
async def update_nav_item(
    item_id: int,
    body: NavItemUpdate,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("navigation", "admin")),
):
    fields, values = [], []
    for attr in ("nav_group_id", "label", "icon", "route", "resource_key", "description", "sort_order", "is_active", "is_action"):
        val = getattr(body, attr, None)
        if val is not None:
            fields.append(f"{attr} = %s")
            values.append(val)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields.append("updated_at = now()")
    values.append(item_id)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                UPDATE nav_items SET {', '.join(fields)}
                WHERE id = %s
                RETURNING id, nav_group_id, key, label, icon, route, resource_key, description,
                          sort_order, is_active, is_action, created_at, updated_at
            """, values)
            item = cur.fetchone()
            if not item:
                raise HTTPException(404, "Nav item not found")
    return item


@router.delete("/nav/items/{item_id}")
async def delete_nav_item(
    item_id: int,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("navigation", "admin")),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM nav_items WHERE id = %s", (item_id,))
            if cur.rowcount == 0:
                raise HTTPException(404, "Nav item not found")
    return {"message": "Nav item deleted"}


# =====================================================================
# DEPARTMENT VISIBILITY
# =====================================================================

@router.get("/departments/{dept_id}/visibility")
async def get_department_visibility(
    dept_id: int,
    request: Request,
    current_user: User = Depends(require_authentication),
):
    """Get the nav groups and nav items visible to a department."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM departments WHERE id = %s", (dept_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Department not found")
            cur.execute("""
                SELECT ng.id, ng.key, ng.label, ng.icon, ng.sort_order
                FROM department_nav_groups dng
                JOIN nav_groups ng ON ng.id = dng.nav_group_id
                WHERE dng.department_id = %s AND ng.is_active = true
                ORDER BY ng.sort_order
            """, (dept_id,))
            groups = cur.fetchall()
            cur.execute("""
                SELECT ni.id, ni.key, ni.label, ni.icon, ni.nav_group_id, ni.route, ni.resource_key, ni.is_action, ni.sort_order
                FROM department_nav_items dni
                JOIN nav_items ni ON ni.id = dni.nav_item_id
                WHERE dni.department_id = %s AND ni.is_active = true
                ORDER BY ni.sort_order
            """, (dept_id,))
            items = cur.fetchall()
    return {"nav_groups": groups, "nav_items": items}


@router.put("/departments/{dept_id}/visibility")
async def set_department_visibility(
    dept_id: int,
    body: DepartmentVisibilityUpdate,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("departments", "admin")),
):
    """Replace the full visibility set for a department."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM departments WHERE id = %s", (dept_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Department not found")
            # Replace groups
            cur.execute("DELETE FROM department_nav_groups WHERE department_id = %s", (dept_id,))
            for gid in body.nav_group_ids:
                cur.execute("""
                    INSERT INTO department_nav_groups (department_id, nav_group_id)
                    VALUES (%s, %s) ON CONFLICT DO NOTHING
                """, (dept_id, gid))
            # Replace items
            cur.execute("DELETE FROM department_nav_items WHERE department_id = %s", (dept_id,))
            for iid in body.nav_item_ids:
                cur.execute("""
                    INSERT INTO department_nav_items (department_id, nav_item_id)
                    VALUES (%s, %s) ON CONFLICT DO NOTHING
                """, (dept_id, iid))
    log_auth_event(current_user.username, "visibility_updated", True,
                   request.client.host if request.client else None,
                   details={"department_id": dept_id,
                            "group_count": len(body.nav_group_ids),
                            "item_count": len(body.nav_item_ids)})
    return {"message": "Visibility updated"}


# =====================================================================
# PER-USER VISIBILITY OVERRIDES
# =====================================================================

@router.get("/nav/overrides/{username}")
async def get_user_overrides(
    username: str,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("navigation", "admin")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT uno.id, uno.username, uno.nav_item_id, uno.override_type,
                       uno.reason, uno.created_by, uno.created_at,
                       ni.key AS nav_item_key, ni.label AS nav_item_label
                FROM user_nav_overrides uno
                JOIN nav_items ni ON ni.id = uno.nav_item_id
                WHERE uno.username = %s
                ORDER BY ni.key
            """, (username,))
            return cur.fetchall()


@router.post("/nav/overrides", status_code=201)
async def create_user_override(
    body: UserNavOverrideCreate,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("navigation", "admin")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO user_nav_overrides (username, nav_item_id, override_type, reason, created_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (username, nav_item_id)
                DO UPDATE SET override_type = EXCLUDED.override_type,
                              reason = EXCLUDED.reason,
                              created_by = EXCLUDED.created_by,
                              created_at = now()
                RETURNING id, username, nav_item_id, override_type, reason, created_by, created_at
            """, (body.username, body.nav_item_id, body.override_type, body.reason, current_user.username))
            return cur.fetchone()


@router.delete("/nav/overrides/{override_id}")
async def delete_user_override(
    override_id: int,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("navigation", "admin")),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_nav_overrides WHERE id = %s", (override_id,))
            if cur.rowcount == 0:
                raise HTTPException(404, "Override not found")
    return {"message": "Override deleted"}


# =====================================================================
# USER ↔ DEPARTMENT ASSIGNMENT
# =====================================================================

@router.put("/auth/users/{username}/department")
async def set_user_department(
    username: str,
    body: UserDepartmentUpdate,
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("departments", "admin")),
):
    """Assign a user to a department (or remove with null)."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if body.department_id is not None:
                cur.execute("SELECT 1 FROM departments WHERE id = %s", (body.department_id,))
                if not cur.fetchone():
                    raise HTTPException(404, "Department not found")
            cur.execute("""
                UPDATE user_roles SET department_id = %s, last_modified = now()
                WHERE username = %s
                RETURNING username, role, department_id
            """, (body.department_id, username))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "User role record not found")
    log_auth_event(current_user.username, "department_assigned", True,
                   request.client.host if request.client else None,
                   details={"target_user": username, "department_id": body.department_id})
    return row


# =====================================================================
# EXTENDED /auth/me — returns profile + navigation + permissions
# =====================================================================

def get_user_navigation(username: str, role: str, department_id: Optional[int]) -> Dict[str, Any]:
    """
    Compute the effective navigation for a user:
    1. Start with department visibility (groups + items)
    2. Apply per-user overrides (grant / deny)
    3. Return structured nav tree
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if department_id:
                # Get department-visible groups
                cur.execute("""
                    SELECT ng.id, ng.key, ng.label, ng.icon, ng.description, ng.sort_order, ng.is_default
                    FROM department_nav_groups dng
                    JOIN nav_groups ng ON ng.id = dng.nav_group_id
                    WHERE dng.department_id = %s AND ng.is_active = true
                    ORDER BY ng.sort_order
                """, (department_id,))
                groups = cur.fetchall()

                # Get department-visible items
                cur.execute("""
                    SELECT ni.id, ni.nav_group_id, ni.key, ni.label, ni.icon,
                           ni.route, ni.resource_key, ni.is_action, ni.sort_order
                    FROM department_nav_items dni
                    JOIN nav_items ni ON ni.id = dni.nav_item_id
                    WHERE dni.department_id = %s AND ni.is_active = true
                    ORDER BY ni.sort_order
                """, (department_id,))
                items = cur.fetchall()
            else:
                # No department → show everything (backward compat for unassigned users)
                cur.execute("""
                    SELECT id, key, label, icon, description, sort_order, is_default
                    FROM nav_groups WHERE is_active = true ORDER BY sort_order
                """)
                groups = cur.fetchall()
                cur.execute("""
                    SELECT id, nav_group_id, key, label, icon, route, resource_key, is_action, sort_order
                    FROM nav_items WHERE is_active = true ORDER BY sort_order
                """)
                items = cur.fetchall()

            # Apply per-user overrides
            cur.execute("""
                SELECT nav_item_id, override_type
                FROM user_nav_overrides
                WHERE username = %s
            """, (username,))
            overrides = {row["nav_item_id"]: row["override_type"] for row in cur.fetchall()}

            # Build item set
            visible_item_ids = {item["id"] for item in items}

            # Apply overrides
            for item_id, override_type in overrides.items():
                if override_type == "grant":
                    visible_item_ids.add(item_id)
                elif override_type == "deny":
                    visible_item_ids.discard(item_id)

            # If grants added items not in the current list, fetch them
            granted_missing = visible_item_ids - {item["id"] for item in items}
            if granted_missing:
                placeholders = ",".join(["%s"] * len(granted_missing))
                cur.execute(f"""
                    SELECT id, nav_group_id, key, label, icon, route, resource_key, sort_order
                    FROM nav_items WHERE id IN ({placeholders}) AND is_active = true
                """, list(granted_missing))
                items.extend(cur.fetchall())

            # Filter items
            final_items = [i for i in items if i["id"] in visible_item_ids]

            # Ensure groups for granted items are included
            group_ids = {g["id"] for g in groups}
            needed_group_ids = {i["nav_group_id"] for i in final_items} - group_ids
            if needed_group_ids:
                placeholders = ",".join(["%s"] * len(needed_group_ids))
                cur.execute(f"""
                    SELECT id, key, label, icon, description, sort_order, is_default
                    FROM nav_groups WHERE id IN ({placeholders}) AND is_active = true
                """, list(needed_group_ids))
                groups.extend(cur.fetchall())

            # Get user permissions
            cur.execute("""
                SELECT resource, action FROM role_permissions WHERE role = %s
            """, (role,))
            permissions = [{"resource": r["resource"], "action": r["action"]} for r in cur.fetchall()]

    # Build nav tree
    group_map = {}
    for g in groups:
        group_map[g["id"]] = {
            "id": g["id"],
            "key": g["key"],
            "label": g["label"],
            "icon": g.get("icon"),
            "sort_order": g["sort_order"],
            "is_default": g.get("is_default", False),
            "items": [],
        }

    for item in sorted(final_items, key=lambda x: x["sort_order"]):
        gid = item["nav_group_id"]
        if gid in group_map:
            group_map[gid]["items"].append({
                "id": item["id"],
                "key": item["key"],
                "label": item["label"],
                "icon": item.get("icon"),
                "route": item["route"],
                "resource_key": item.get("resource_key"),
                "sort_order": item["sort_order"],
                "is_action": item.get("is_action", False),
            })

    nav_tree = sorted(group_map.values(), key=lambda x: x["sort_order"])

    return {
        "nav": nav_tree,
        "permissions": permissions,
    }


@router.get("/auth/me/navigation")
async def get_my_navigation(
    request: Request,
    current_user: User = Depends(require_authentication),
):
    """
    Extended auth/me: returns user profile, department, navigation tree, and permissions.
    This is the single-call payload the frontend uses after login.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT ur.department_id, d.name AS department_name
                FROM user_roles ur
                LEFT JOIN departments d ON d.id = ur.department_id
                WHERE ur.username = %s AND ur.is_active = true
            """, (current_user.username,))
            row = cur.fetchone()
            department_id = row["department_id"] if row else None
            department_name = row["department_name"] if row else None

    nav_data = get_user_navigation(current_user.username, current_user.role, department_id)

    return {
        "user": {
            "username": current_user.username,
            "role": current_user.role,
            "department_id": department_id,
            "department_name": department_name,
        },
        "nav": nav_data["nav"],
        "permissions": nav_data["permissions"],
    }


# =====================================================================
# BULK VISIBILITY MATRIX (for admin UI)
# =====================================================================

@router.get("/departments/visibility/matrix")
async def get_visibility_matrix(
    request: Request,
    current_user: User = Depends(require_authentication),
    _perm: bool = Depends(require_permission("departments", "admin")),
):
    """
    Returns the complete matrix of department × nav group/item visibility.
    Used by the admin UI to render the checkbox editor.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, name, is_active, sort_order FROM departments ORDER BY sort_order, name")
            departments = cur.fetchall()

            cur.execute("""
                SELECT id, key, label, icon, sort_order, is_active, is_default
                FROM nav_groups ORDER BY sort_order
            """)
            groups = cur.fetchall()

            cur.execute("""
                SELECT id, nav_group_id, key, label, sort_order, is_active
                FROM nav_items ORDER BY sort_order
            """)
            items = cur.fetchall()

            cur.execute("SELECT department_id, nav_group_id FROM department_nav_groups")
            group_links = cur.fetchall()

            cur.execute("SELECT department_id, nav_item_id FROM department_nav_items")
            item_links = cur.fetchall()

    # Build sets for fast lookup
    group_link_set = {(r["department_id"], r["nav_group_id"]) for r in group_links}
    item_link_set = {(r["department_id"], r["nav_item_id"]) for r in item_links}

    return {
        "departments": departments,
        "nav_groups": groups,
        "nav_items": items,
        "department_group_visibility": [
            {"department_id": d, "nav_group_id": g} for d, g in group_link_set
        ],
        "department_item_visibility": [
            {"department_id": d, "nav_item_id": i} for d, i in item_link_set
        ],
    }
