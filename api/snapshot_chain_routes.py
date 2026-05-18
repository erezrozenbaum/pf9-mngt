"""
Snapshot Chain Routes — v2.3.0

Endpoints for viewing and managing snapshot chains (base → incremental
sequences for block-storage volumes).

Chain terminology:
  base snapshot  — chain_depth=0, parent_snapshot_id=NULL
  incremental    — chain_depth>0, parent_snapshot_id points to the previous snapshot

Routes:
  GET  /api/snapshots/{snapshot_id}/chain
       Return the full lineage of a snapshot (its ancestors and direct children)

  GET  /api/volumes/{volume_id}/chains
       Return a summary of every chain for a given volume

  GET  /api/projects/{project_id}/chain-policies
       Return the snapshot chain policy for a project (max depth, auto-rebase)

  PUT  /api/projects/{project_id}/chain-policies/{volume_id}
       Upsert the chain policy for a specific (project, volume) pair
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from auth import require_permission, User
from db_pool import get_connection

logger = logging.getLogger("pf9.snapshot_chains")
router = APIRouter(prefix="/api", tags=["snapshot-chains"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SnapshotChainNode(BaseModel):
    snapshot_id: str
    snapshot_name: Optional[str]
    volume_id: str
    volume_name: Optional[str]
    project_id: str
    chain_depth: int
    chain_root_snapshot_id: Optional[str]
    parent_snapshot_id: Optional[str]
    status: str
    size_gb: Optional[int]
    created_at: Optional[str]
    deleted_at: Optional[str]
    children: List["SnapshotChainNode"] = Field(default_factory=list)


SnapshotChainNode.model_rebuild()


class SnapshotChainSummary(BaseModel):
    volume_id: str
    volume_name: Optional[str]
    total_snapshots: int
    base_snapshots: int
    max_chain_depth: int
    total_size_gb: Optional[int]
    chains: List[SnapshotChainNode]  # one entry per chain root


class ChainPolicyIn(BaseModel):
    max_chain_depth: int = Field(5, ge=1, le=50)
    auto_rebase: bool = True


class ChainPolicyOut(BaseModel):
    project_id: str
    volume_id: str
    max_chain_depth: int
    auto_rebase: bool
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _row_to_node(row: dict) -> SnapshotChainNode:
    return SnapshotChainNode(
        snapshot_id=row["snapshot_id"] or "",
        snapshot_name=row.get("snapshot_name"),
        volume_id=row["volume_id"],
        volume_name=row.get("volume_name"),
        project_id=row["project_id"],
        chain_depth=row.get("chain_depth", 0),
        chain_root_snapshot_id=row.get("chain_root_snapshot_id"),
        parent_snapshot_id=row.get("parent_snapshot_id"),
        status=row.get("status", "unknown"),
        size_gb=row.get("size_gb"),
        created_at=row["created_at"].isoformat() if row.get("created_at") else None,
        deleted_at=row["deleted_at"].isoformat() if row.get("deleted_at") else None,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/snapshots/{snapshot_id}/chain", response_model=SnapshotChainNode)
async def get_snapshot_chain(
    snapshot_id: str,
    current_user: User = Depends(require_permission("snapshots", "read")),
):
    """Return the full chain for a given snapshot — its ancestors and direct children."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Fetch the target snapshot
            cur.execute(
                "SELECT * FROM snapshot_records WHERE snapshot_id = %s",
                (snapshot_id,),
            )
            root_row = cur.fetchone()
            if not root_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Snapshot {snapshot_id!r} not found",
                )

            # Walk up to the true chain root
            chain_root_id = root_row.get("chain_root_snapshot_id") or snapshot_id
            if root_row.get("chain_depth", 0) == 0:
                chain_root_id = snapshot_id  # this IS the root

            # Fetch the entire chain (all members sharing the same root)
            cur.execute(
                """
                SELECT * FROM snapshot_records
                WHERE chain_root_snapshot_id = %s
                   OR snapshot_id = %s
                ORDER BY chain_depth ASC, created_at ASC
                """,
                (chain_root_id, chain_root_id),
            )
            rows = {r["snapshot_id"]: _row_to_node(r) for r in cur.fetchall()}

    # Build tree structure
    root_node: Optional[SnapshotChainNode] = None
    for sid, node in rows.items():
        if node.parent_snapshot_id and node.parent_snapshot_id in rows:
            rows[node.parent_snapshot_id].children.append(node)
        if node.chain_depth == 0:
            root_node = node

    if root_node is None:
        # Return the requested snapshot as-is (orphaned or base without chain info)
        root_node = rows.get(snapshot_id)
        if root_node is None:
            raise HTTPException(status_code=404, detail="Chain could not be assembled")

    return root_node


@router.get("/volumes/{volume_id}/chains", response_model=SnapshotChainSummary)
async def get_volume_chains(
    volume_id: str,
    current_user: User = Depends(require_permission("snapshots", "read")),
):
    """Return a summary of all snapshot chains for a volume."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM snapshot_records
                WHERE volume_id = %s AND status <> 'deleted'
                ORDER BY chain_depth ASC, created_at ASC
                """,
                (volume_id,),
            )
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No snapshots found for volume {volume_id!r}",
        )

    total_size = sum((r.get("size_gb") or 0) for r in rows)
    base_snapshots = sum(1 for r in rows if r.get("chain_depth", 0) == 0)
    max_depth = max((r.get("chain_depth") or 0) for r in rows)
    volume_name = rows[0].get("volume_name") if rows else None
    project_id = rows[0]["project_id"] if rows else ""

    # Build root nodes only (depth == 0 or no parent)
    node_map = {r["snapshot_id"]: _row_to_node(r) for r in rows if r.get("snapshot_id")}
    for node in node_map.values():
        if node.parent_snapshot_id and node.parent_snapshot_id in node_map:
            node_map[node.parent_snapshot_id].children.append(node)

    chain_roots = [n for n in node_map.values() if n.chain_depth == 0 or not n.parent_snapshot_id]

    return SnapshotChainSummary(
        volume_id=volume_id,
        volume_name=volume_name,
        total_snapshots=len(rows),
        base_snapshots=base_snapshots,
        max_chain_depth=max_depth,
        total_size_gb=total_size if total_size > 0 else None,
        chains=chain_roots,
    )


@router.get(
    "/projects/{project_id}/chain-policies",
    response_model=List[ChainPolicyOut],
)
async def list_chain_policies(
    project_id: str,
    current_user: User = Depends(require_permission("snapshots", "read")),
):
    """List all snapshot chain policies for a project."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM snapshot_chain_policies WHERE project_id = %s "
                "ORDER BY volume_id",
                (project_id,),
            )
            rows = cur.fetchall()
    return [
        ChainPolicyOut(
            project_id=r["project_id"],
            volume_id=r["volume_id"],
            max_chain_depth=r["max_chain_depth"],
            auto_rebase=r["auto_rebase"],
            created_at=r["created_at"].isoformat(),
            updated_at=r["updated_at"].isoformat(),
        )
        for r in rows
    ]


@router.put(
    "/projects/{project_id}/chain-policies/{volume_id}",
    response_model=ChainPolicyOut,
    status_code=status.HTTP_200_OK,
)
async def upsert_chain_policy(
    project_id: str,
    volume_id: str,
    body: ChainPolicyIn,
    current_user: User = Depends(require_permission("snapshots", "write")),
):
    """Create or update the snapshot chain policy for a (project, volume) pair."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO snapshot_chain_policies
                    (project_id, volume_id, max_chain_depth, auto_rebase, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (project_id, volume_id)
                DO UPDATE SET
                    max_chain_depth = EXCLUDED.max_chain_depth,
                    auto_rebase     = EXCLUDED.auto_rebase,
                    updated_at      = NOW()
                RETURNING *
                """,
                (project_id, volume_id, body.max_chain_depth, body.auto_rebase),
            )
            row = cur.fetchone()
        conn.commit()

    logger.info(
        "Chain policy upserted: project=%s volume=%s max_depth=%d by %s",
        project_id, volume_id, body.max_chain_depth, current_user.username,
    )
    return ChainPolicyOut(
        project_id=row["project_id"],
        volume_id=row["volume_id"],
        max_chain_depth=row["max_chain_depth"],
        auto_rebase=row["auto_rebase"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )
