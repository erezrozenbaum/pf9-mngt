"""
Docs Viewer API Routes  —  v1.83.12
=====================================
Serves markdown files from the /docs directory with department-level
visibility control.

Endpoints:
  GET  /api/docs/                       – list available doc files (filtered by dept)
  GET  /api/docs/content/{filename}     – serve raw markdown content of a file
  GET  /api/docs/admin/visibility       – admin: get all visibility settings
  PUT  /api/docs/admin/visibility       – admin: set dept visibility for a file

RBAC:
  - All authenticated users can list/read docs filtered by their department.
  - admin / superadmin see all docs and can manage visibility.
  - Empty doc_page_visibility = all docs open to all departments.
"""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth import require_authentication, get_current_user, User, has_permission
from db_pool import get_connection

logger = logging.getLogger("pf9.docs")

router = APIRouter(prefix="/api/docs", tags=["docs"])

# Resolved path to the docs directory (one level above the api/ package)
_DOCS_DIR = Path(__file__).resolve().parent / "docs"

# Regex for safe filename validation — prevents path traversal
_SAFE_FILENAME_RE = re.compile(r"^[\w\-\.]+\.md$")

# ---------------------------------------------------------------------------
# Category mapping based on filename prefix/keywords
# ---------------------------------------------------------------------------
_CATEGORY_MAP: Dict[str, str] = {
    "ADMIN":       "Administration",
    "DEPLOYMENT":  "Deployment",
    "QUICK":       "Quick Reference",
    "ARCHITECT":   "Architecture",
    "RUNBOOK":     "Runbooks",
    "SECURITY":    "Security",
    "AUDIT":       "Audit & Compliance",
    "MIGRATION":    "Migration",
    "API":         "API",
    "UPGRADE":     "Upgrade",
    "KUBERNETES":  "Kubernetes",
    "LDAP":        "LDAP / Identity",
    "CHANGE":      "Change Log",
    "CONTRIBUTING":"Contributing",
}

def _categorise(filename: str) -> str:
    upper = filename.upper()
    for prefix, category in _CATEGORY_MAP.items():
        if prefix in upper:
            return category
    return "General"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_doc_files() -> List[str]:
    """Return sorted list of .md filenames in the docs directory."""
    if not _DOCS_DIR.exists():
        return []
    return sorted(
        f.name
        for f in _DOCS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() == ".md"
    )


def _user_dept_id(user: User) -> Optional[int]:
    """Extract dept_id from the user object (stored as attribute or extra field)."""
    return getattr(user, "dept_id", None)


def _is_admin(user: User) -> bool:
    return user.role in ("admin", "superadmin")


def _visible_filenames_for_user(user: User) -> List[str]:
    """
    Return filenames visible to *user*.  admin/superadmin see everything.
    Everyone else: if no visibility rows exist for a file → visible to all.
    If rows exist → only visible to listed depts.
    """
    all_files = _list_doc_files()
    if _is_admin(user):
        return all_files

    dept_id = _user_dept_id(user)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get all restricted filenames and which depts can see them
            cur.execute(
                "SELECT filename, dept_id FROM doc_page_visibility"
            )
            rows = cur.fetchall()

    # Group by filename
    restricted: Dict[str, List[int]] = {}
    for row in rows:
        restricted.setdefault(row["filename"], []).append(row["dept_id"])

    visible: List[str] = []
    for fname in all_files:
        if fname not in restricted:
            # No restriction — visible to all
            visible.append(fname)
        elif dept_id and dept_id in restricted[fname]:
            # User's dept is explicitly allowed
            visible.append(fname)

    return visible


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DocEntry(BaseModel):
    filename: str
    category: str
    title: str            # derived from first H1 or filename


class DocVisibilityItem(BaseModel):
    filename: str
    dept_ids: List[int]   # empty list = visible to all


class SetVisibilityRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=200)
    dept_ids: List[int]   # pass empty list to make globally visible


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[DocEntry])
async def list_docs(current_user: User = Depends(get_current_user)):
    """List all doc files visible to the current user."""
    filenames = _visible_filenames_for_user(current_user)
    entries: List[DocEntry] = []
    for fname in filenames:
        # Derive a human-readable title from the first H1 line if present
        title = fname.replace("_", " ").replace("-", " ").replace(".md", "")
        try:
            fpath = _DOCS_DIR / fname
            with fpath.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
        except OSError:
            pass
        entries.append(DocEntry(
            filename=fname,
            category=_categorise(fname),
            title=title,
        ))
    return entries


@router.get("/content/{filename}")
async def get_doc_content(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """Return raw markdown content of a single doc file."""
    # Strict filename validation to prevent path traversal
    if not _SAFE_FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    visible = _visible_filenames_for_user(current_user)
    if filename not in visible:
        raise HTTPException(status_code=403, detail="Access denied or file not found")

    fpath = _DOCS_DIR / filename
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        content = fpath.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.error("Failed to read doc file %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail="Could not read file")

    return {"filename": filename, "content": content}


@router.get("/admin/visibility", response_model=List[DocVisibilityItem])
async def get_visibility_settings(current_user: User = Depends(get_current_user)):
    """Admin: return visibility settings for every doc file."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    all_files = _list_doc_files()
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT filename, dept_id FROM doc_page_visibility ORDER BY filename")
            rows = cur.fetchall()

    restricted: Dict[str, List[int]] = {}
    for row in rows:
        restricted.setdefault(row["filename"], []).append(row["dept_id"])

    return [
        DocVisibilityItem(filename=f, dept_ids=restricted.get(f, []))
        for f in all_files
    ]


@router.put("/admin/visibility")
async def set_visibility(
    body: SetVisibilityRequest,
    current_user: User = Depends(get_current_user),
):
    """Admin: set department visibility for a specific doc file.

    Pass an empty dept_ids list to make the file visible to all departments.
    """
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    if not _SAFE_FILENAME_RE.match(body.filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Confirmed file exists on disk (prevents storing phantom entries)
    fpath = _DOCS_DIR / body.filename
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="File not found in docs directory")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Replace all rows for this filename atomically
            cur.execute(
                "DELETE FROM doc_page_visibility WHERE filename = %s",
                (body.filename,),
            )
            if body.dept_ids:
                for dept_id in body.dept_ids:
                    cur.execute(
                        "INSERT INTO doc_page_visibility (filename, dept_id) VALUES (%s, %s) "
                        "ON CONFLICT (filename, dept_id) DO NOTHING",
                        (body.filename, dept_id),
                    )
        conn.commit()

    return {"ok": True, "filename": body.filename, "dept_ids": body.dept_ids}
