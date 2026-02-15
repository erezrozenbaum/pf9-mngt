#!/usr/bin/env python3
"""
p9_auto_snapshots.py

Automatic Cinder volume snapshots for Platform9/OpenStack.

Snapshot behavior is driven entirely by **volume metadata**.

Recommended model (multi-policy, per-volume):

  auto_snapshot          = "true" / "yes" / "1"  (string, case-insensitive)

  snapshot_policies      = "daily_5,monthly_1st,monthly_15th"

  retention_daily_5      = "5"   # keep last 5 daily snapshots (≈5 days)
  retention_monthly_1st  = "1"   # keep last 1 snapshot taken under monthly_1st
  retention_monthly_15th = "1"   # keep last 1 snapshot taken under monthly_15th

Legacy model (still supported):

  snapshot_policy        = "daily" / "weekly" / "monthly" / ...
  retention              = "7"    # keep last N snapshots created by this tool

-----------------------
Usage examples
-----------------------

Dry-run, no changes:

  python snapshots/p9_auto_snapshots.py --policy daily_5 --dry-run

Real run, once per day, max 200 new snapshots:

  python snapshots/p9_auto_snapshots.py --policy daily_5 --max-new 200

Monthly policies (script is day-aware):

  python snapshots/p9_auto_snapshots.py --policy monthly_1st
  python snapshots/p9_auto_snapshots.py --policy monthly_15th

Scheduling (Windows Task Scheduler):

  - Schedule **once per day**:
      02:00 → daily_5
      02:10 → monthly_1st
      02:20 → monthly_15th

  - The script will **only do work** for:
      daily_5          → every day
      monthly_1st      → only when day == 1
      monthly_15th     → only when day == 15

Run report (per execution):

  python snapshots/p9_auto_snapshots.py --policy daily_5 --report-xlsx

This will write snapshot_run_<policy>_<timestamp>.xlsx in the chosen report directory.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import json
import socket
from datetime import datetime, timezone
from collections import defaultdict

import pandas as pd
import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from p9_common import (
    CFG,
    ERRORS,
    log_error,
    now_utc_str,
    get_session_best_scope,
    get_service_user_session,
    cinder_volumes_all,
    cinder_list_snapshots_for_volume,
    cinder_create_snapshot,
    cinder_delete_snapshot,
    list_domains_all,
    list_projects_all,
    nova_servers_all,
    get_project_scoped_session,
)

try:
    from snapshot_service_user import (
        ensure_service_user,
        get_service_user_password,
        SERVICE_USER_EMAIL,
    )
except ImportError:
    print("[WARNING] snapshot_service_user module not available; service user management disabled")
    ensure_service_user = None
    SERVICE_USER_EMAIL = None

# Database constants
ENABLE_DB = os.getenv("ENABLE_DB", "true").lower() in ("true", "yes", "1")
DB_HOST = os.getenv("PF9_DB_HOST", "localhost")
DB_PORT = int(os.getenv("PF9_DB_PORT", "5432"))
DB_NAME = os.getenv("PF9_DB_NAME", os.getenv("POSTGRES_DB", "pf9_mgmt"))
DB_USER = os.getenv("PF9_DB_USER", os.getenv("POSTGRES_USER", "pf9"))
DB_PASSWORD = os.getenv("PF9_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))


# ============================================================================
# Database Helpers
# ============================================================================

def get_db_connection():
    """Connect to PostgreSQL database for snapshot logging."""
    try:
        return psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
    except Exception as e:
        print(f"[DB] Connection failed: {e}")
        return None


def start_snapshot_run(conn, run_type: str, dry_run: bool, trigger_source: str = "manual"):
    """Create snapshot_runs record and return run_id."""
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO snapshot_runs 
                (run_type, dry_run, triggered_by, trigger_source, execution_host, status)
                VALUES (%s, %s, %s, %s, %s, 'running')
                RETURNING id, started_at
                """,
                (run_type, dry_run, "system", trigger_source, socket.gethostname())
            )
            run_id, started_at = cur.fetchone()
        conn.commit()
        return run_id
    except Exception as e:
        print(f"[DB] Error starting snapshot run: {e}")
        return None


def finish_snapshot_run(conn, run_id: int, status: str, total_volumes: int, 
                       snapshots_created: int, snapshots_deleted: int, 
                       snapshots_failed: int, volumes_skipped: int, 
                       error_summary: str = None):
    """Update snapshot_runs with completion status and stats."""
    if not conn or not run_id:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE snapshot_runs
                SET finished_at = now(),
                    status = %s,
                    total_volumes = %s,
                    snapshots_created = %s,
                    snapshots_deleted = %s,
                    snapshots_failed = %s,
                    volumes_skipped = %s,
                    error_summary = %s
                WHERE id = %s
                """,
                (status, total_volumes, snapshots_created, snapshots_deleted,
                 snapshots_failed, volumes_skipped, error_summary, run_id)
            )
        conn.commit()
    except Exception as e:
        print(f"[DB] Error finishing snapshot run: {e}")


def create_snapshot_record(conn, run_id: int, action: str, snapshot_id: str, 
                          snapshot_name: str, volume_id: str, volume_name: str,
                          tenant_id: str, tenant_name: str, project_id: str,
                          project_name: str, vm_id: str, vm_name: str,
                          policy_name: str, size_gb: int, retention_days: int,
                          status: str, error_message: str = None, 
                          openstack_created_at: datetime = None,
                          raw_snapshot_json: dict = None):
    """Create snapshot_records entry for audit trail."""
    if not conn or not run_id:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO snapshot_records
                (snapshot_run_id, action, snapshot_id, snapshot_name, volume_id,
                 volume_name, tenant_id, tenant_name, project_id, project_name,
                 vm_id, vm_name, policy_name, size_gb, retention_days, status,
                 error_message, openstack_created_at, raw_snapshot_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (run_id, action, snapshot_id, snapshot_name, volume_id,
                 volume_name, tenant_id, tenant_name, project_id, project_name,
                 vm_id, vm_name, policy_name, size_gb, retention_days, status,
                 error_message, openstack_created_at, Json(raw_snapshot_json) if raw_snapshot_json else None)
            )
        conn.commit()
    except Exception as e:
        print(f"[DB] Error creating snapshot record: {e}")




# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


def _parse_int(value, default: int) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def _sanitize_name_part(s: str) -> str:
    """
    Make a safe piece for snapshot name:
      - strip
      - spaces -> '_'
      - other weird chars -> '-'
      - truncate to 40 chars
    """
    if s is None:
        return ""
    s = str(s).strip()
    if not s:
        return ""
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^A-Za-z0-9_.-]", "-", s)
    return s[:40]


def _volume_policies_for(volume) -> list[str]:
    """
    Return a list of policy names configured for this volume, in lowercase.

    Supports:
      - NEW: metadata.snapshot_policies = "policy1,policy2"
      - LEGACY: metadata.snapshot_policy = "policy"
    """
    meta = volume.get("metadata") or {}

    policies: list[str] = []

    # New multi-policy field
    multi = meta.get("snapshot_policies")
    if isinstance(multi, str) and multi.strip():
        for p in multi.split(","):
            p = p.strip()
            if p:
                policies.append(p.lower())
    elif isinstance(multi, (list, tuple)):
        for p in multi:
            s = str(p).strip()
            if s:
                policies.append(s.lower())

    # Legacy single-policy fallback
    if not policies:
        single = meta.get("snapshot_policy")
        if single:
            policies.append(str(single).strip().lower())

    return policies


def select_volumes_for_policy(volumes, policy_name: str):
    """
    Filter volumes that should be processed for the given policy.

    Criteria:
      - metadata.auto_snapshot == "true"/"yes"/"1" (case-insensitive)
      - metadata.snapshot_policies contains policy_name
        OR legacy metadata.snapshot_policy == policy_name
      - status is not deleting/error, etc.
    """
    selected = []
    target = policy_name.lower()

    for v in volumes:
        meta = v.get("metadata") or {}
        auto_flag = str(meta.get("auto_snapshot", "")).lower()
        status = str(v.get("status") or "").lower()

        if auto_flag not in ("true", "yes", "1"):
            continue
        if status in ("error", "deleting"):
            continue

        policies = _volume_policies_for(v)
        if target not in policies:
            continue

        selected.append(v)

    return selected


def build_snapshot_name(volume, policy_name: str, server_name: str | None = None, tenant_name: str | None = None) -> str:
    """
    Name pattern:

      auto-<tenant>-<policy>-<serverName>-<volumeName>-<YYYYMMDD-HHMMSS>

    serverName part is omitted if there's no attached server.
    tenant part is included if provided.
    """
    vol_label = _sanitize_name_part(volume.get("name") or volume.get("id"))
    srv_label = _sanitize_name_part(server_name) if server_name else ""
    tenant_label = _sanitize_name_part(tenant_name) if tenant_name else ""

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    if tenant_label:
        if srv_label:
            base = f"{tenant_label}-{policy_name}-{srv_label}-{vol_label}"
        else:
            base = f"{tenant_label}-{policy_name}-{vol_label}"
    else:
        if srv_label:
            base = f"{policy_name}-{srv_label}-{vol_label}"
        else:
            base = f"{policy_name}-{vol_label}"

    return f"auto-{base}-{ts}"


def _retention_for_volume_and_policy(
    volume,
    policy_name: str,
    default: int = 7,
) -> int:
    """
    Determine the retention value for a given volume + policy.

    Priority:
      1) retention_<policy_name>
      2) snapshot_retention_<policy_name>
      3) retention
      4) default (7)
    """
    meta = volume.get("metadata") or {}
    key1 = f"retention_{policy_name}"
    key2 = f"snapshot_retention_{policy_name}"

    raw = (
        meta.get(key1)
        or meta.get(key2)
        or meta.get("retention")
        or default
    )
    return _parse_int(raw, default)


def _has_snapshot_today(
    session,
    admin_project_id: str,
    volume,
    policy_name: str,
) -> bool:
    """
    Return True if this volume already has an automated snapshot for today
    (UTC date) under the given policy.  This prevents duplicate snapshots
    when the script is run multiple times in the same day.
    """
    vol_id = volume["id"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        snaps = cinder_list_snapshots_for_volume(session, admin_project_id, vol_id)
    except Exception:
        # If listing fails, err on the side of creating (don't skip).
        return False

    for s in snaps:
        smeta = s.get("metadata") or {}
        if smeta.get("created_by") != "p9_auto_snapshots":
            continue
        if smeta.get("policy") != policy_name:
            continue
        created = s.get("created_at") or ""
        if created.startswith(today):
            return True
    return False


def cleanup_old_snapshots_for_volume(
    session,
    admin_project_id: str,
    volume,
    policy_name: str,
    dry_run: bool,
):
    """
    Deletes old snapshots created by this tool for the given volume,
    based on per-policy retention metadata (fallback: 7).

    NOTE:
      - We always use the admin/service project id for listing & deleting.
      - cinder_snapshots_all() in p9_common uses all_tenants=1, so
        we see all tenants' snapshots.
    """
    retention = _retention_for_volume_and_policy(volume, policy_name, default=7)
    vol_id = volume["id"]

    try:
        snaps = cinder_list_snapshots_for_volume(session, admin_project_id, vol_id)
    except Exception as e:
        msg = f"Failed to list snapshots for volume {vol_id}: {type(e).__name__}: {e}"
        print("    WARNING:", msg)
        log_error("auto_snapshots/list", msg)
        return []

    # keep only snapshots created by this tool + matching policy
    ours = []
    for s in snaps:
        smeta = s.get("metadata") or {}
        if smeta.get("created_by") != "p9_auto_snapshots":
            continue
        if smeta.get("policy") != policy_name:
            continue
        ours.append(s)

    if len(ours) <= retention:
        return []

    ours_sorted = sorted(
        ours,
        key=lambda s: s.get("created_at") or "",
        reverse=True,
    )
    to_delete = ours_sorted[retention:]

    deleted_ids: list[str] = []
    for s in to_delete:
        sid = s["id"]
        sname = s.get("name") or sid
        print(f"    Cleanup: delete old snapshot {sid} ({sname}) for volume {vol_id}")
        if dry_run:
            continue
        err = cinder_delete_snapshot(session, admin_project_id, sid)
        if err:
            msg = f"Failed to delete snapshot {sid}: {err}"
            print("      ERROR:", msg)
            log_error("auto_snapshots/delete", msg)
        else:
            deleted_ids.append(sid)

    return deleted_ids


def process_volume(
    admin_session,
    admin_project_id: str,
    volume,
    policy_name: str,
    dry_run: bool,
    primary_server_name: str | None = None,
    tenant_name: str | None = None,
    create_session=None,
    create_project_id: str | None = None,
):
    """
    Create one snapshot for this volume and clean old ones.
    Returns (created_snapshot_id or None, created_snapshot_project_id,
             deleted_ids, error_message_or_None, snap_name).

    We:
      - List & delete snapshots via admin_session + admin_project_id
        (these must match — token scope == URL project_id).
      - Create snapshot via create_session + create_project_id so the
        snapshot lands in the volume's tenant.  When no service-user
        session is available the caller falls back to admin_session +
        admin_project_id (snapshots will land in the service domain).
    """
    # Default create_session / create_project_id to admin if not supplied
    if create_session is None:
        create_session = admin_session
    if create_project_id is None:
        create_project_id = admin_project_id

    vol_id = volume["id"]
    vol_name = volume.get("name") or vol_id
    volume_project_id = (
        volume.get("os-vol-tenant-attr:tenant_id")
        or volume.get("project_id")
        or "UNKNOWN"
    )

    print(f"  Volume {vol_id} ({vol_name}), project={volume_project_id}")

    # --- dedup: skip if a snapshot already exists today for this policy ---
    if not dry_run and _has_snapshot_today(
        admin_session, admin_project_id, volume, policy_name
    ):
        print(f"    SKIP: snapshot already exists today for policy {policy_name}")
        return None, volume_project_id, [], None, None

    snap_name = build_snapshot_name(volume, policy_name, primary_server_name, tenant_name)
    snap_desc = f"Auto snapshot ({policy_name}) created by p9_auto_snapshots"

    print(f"    Create snapshot: {snap_name}")
    if dry_run:
        # In dry-run, still preview the cleanup
        deleted_ids = cleanup_old_snapshots_for_volume(
            admin_session,
            admin_project_id,
            volume,
            policy_name,
            dry_run=True,
        )
        return None, None, deleted_ids, None, snap_name

    # --- create snapshot (service-user session → correct tenant) ---
    try:
        snap = cinder_create_snapshot(
            create_session,
            create_project_id,   # MUST match create_session token scope
            volume_id=vol_id,
            name=snap_name,
            description=snap_desc,
            metadata={
                "created_by": "p9_auto_snapshots",
                "policy": policy_name,
                "original_project_id": volume_project_id,
                "original_volume_id": vol_id,
            },
            force=True,
        )
        sid = snap.get("id")

        # Try multiple fields to find the project ID
        snapshot_created_in_project = (
            snap.get("os-extended-snapshot-attributes:project_id") or
            snap.get("os-vol-tenant-attr:tenant_id") or
            snap.get("project_id") or
            snap.get("tenant_id") or
            create_project_id
        )
        print(
            f"      OK, snapshot id={sid} created in project={snapshot_created_in_project}"
        )

        # --- cleanup AFTER create so the new snapshot is counted ---
        deleted_ids = cleanup_old_snapshots_for_volume(
            admin_session,
            admin_project_id,
            volume,
            policy_name,
            dry_run=False,
        )

        return sid, snapshot_created_in_project, deleted_ids, None, snap_name
    except Exception as e:
        msg = f"Failed to create snapshot for volume {vol_id}: {type(e).__name__}: {e}"
        print("      ERROR:", msg)
        log_error("auto_snapshots/create", msg)
        return None, volume_project_id, [], msg, snap_name


def _build_metadata_maps(session):
    """
    Fetch domains, projects and servers and build helper maps so the
    run report can include tenant name, domain name and attached VMs.
    """
    domains = list_domains_all(session)
    projects = list_projects_all(session)
    servers = nova_servers_all(session)

    domain_name_by_id = {d.get("id"): d.get("name") for d in (domains or [])}
    project_name_by_id = {p.get("id"): p.get("name") for p in (projects or [])}
    project_domain_by_id = {}
    for p in projects or []:
        pid = p.get("id")
        did = p.get("domain_id") or (p.get("domain") or {}).get("id")
        if pid and did:
            project_domain_by_id[pid] = did

    # volume_id -> server names / ids / ips
    vol_to_srv_names = defaultdict(list)
    vol_to_srv_ids = defaultdict(list)
    vol_to_srv_ips = defaultdict(list)

    for srv in servers or []:
        sid = srv.get("id")
        sname = srv.get("name")
        attachments = srv.get("os-extended-volumes:volumes_attached") or []
        addresses = srv.get("addresses") or {}

        ips = []
        for net_name, addr_list in addresses.items():
            for a in addr_list or []:
                addr = a.get("addr")
                if addr:
                    ips.append(addr)

        for att in attachments:
            vid = att.get("id") or att.get("volumeId") or att.get("volume_id")
            if not vid:
                continue
            if sname and sname not in vol_to_srv_names[vid]:
                vol_to_srv_names[vid].append(sname)
            if sid and sid not in vol_to_srv_ids[vid]:
                vol_to_srv_ids[vid].append(sid)
            for ip in ips:
                if ip not in vol_to_srv_ips[vid]:
                    vol_to_srv_ips[vid].append(ip)

    return (
        domain_name_by_id,
        project_name_by_id,
        project_domain_by_id,
        vol_to_srv_names,
        vol_to_srv_ids,
        vol_to_srv_ips,
    )


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Automatic volume snapshot tool for Platform9/OpenStack (Cinder)."
    )
    parser.add_argument(
        "--policy",
        default="daily_5",
        help=(
            "Snapshot policy name to process (matches volume metadata "
            "snapshot_policies / snapshot_policy). "
            "Examples: daily_5, monthly_1st, monthly_15th."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not create/delete anything, just print actions.",
    )
    parser.add_argument(
        "--max-new",
        type=int,
        default=200,
        help="Maximum number of NEW snapshots to create in this run (default: 200).",
    )
    parser.add_argument(
        "--max-size-gb",
        type=int,
        default=None,
        help="Skip volumes larger than this size in GB (Platform9 API limitation workaround). Default: no limit.",
    )
    parser.add_argument(
        "--report-xlsx",
        action="store_true",
        help="Write a per-run Excel report with summary and per-volume actions.",
    )
    parser.add_argument(
        "--report-dir",
        default=None,
        help=(
            "Directory to store run reports. "
            "Defaults to CFG['OUTPUT_DIR'] or C:\\Reports\\Platform9."
        ),
    )

    args = parser.parse_args()

    policy_name = args.policy
    dry_run = args.dry_run
    max_new = args.max_new
    max_size_gb = args.max_size_gb
    report_xlsx = args.report_xlsx
    report_dir = args.report_dir or CFG.get("OUTPUT_DIR", os.path.join(os.path.expanduser("~"), "Reports", "Platform9"))

    ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%SZ")
    report_path = os.path.join(
        report_dir,
        f"snapshot_run_{policy_name}_{ts_utc}.xlsx",
    )

    # Initialize database connection and start run tracking
    db_conn = None
    run_id = None
    if ENABLE_DB:
        try:
            db_conn = get_db_connection()
            if db_conn:
                run_id = start_snapshot_run(db_conn, policy_name, dry_run)
                print(f"[DB] Snapshot run started with ID: {run_id}")
        except Exception as e:
            print(f"[DB] Failed to initialize database: {e}")
            db_conn = None

    # Day-of-month gating for monthly policies
    today = datetime.now()
    if policy_name == "monthly_1st" and today.day != 1:
        print(
            f"[SKIP] Policy 'monthly_1st' but today is {today.strftime('%Y-%m-%d')}; "
            "nothing to do."
        )
        print(f"  Finished at (UTC): {now_utc_str()}")
        if db_conn and run_id:
            finish_snapshot_run(db_conn, run_id, "skipped", 0, 0, 0, 0, 0,
                              "Skipped due to day-of-month gating")
            db_conn.close()
        if report_xlsx:
            os.makedirs(report_dir, exist_ok=True)
            summary = {
                "policy": policy_name,
                "dry_run": dry_run,
                "run_timestamp_utc": now_utc_str(),
                "total_volumes_processed": 0,
                "new_snapshots": 0,
                "snapshots_deleted": 0,
                "errors": len(ERRORS),
                "note": "Skipped due to day-of-month gating",
            }
            with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
                pd.DataFrame([summary]).to_excel(
                    writer, sheet_name="Summary", index=False
                )
                pd.DataFrame().to_excel(
                    writer, sheet_name="Actions", index=False
                )
            print(f"  Run report written: {report_path}")
        return
    if policy_name == "monthly_15th" and today.day != 15:
        print(
            f"[SKIP] Policy 'monthly_15th' but today is {today.strftime('%Y-%m-%d')}; "
            "nothing to do."
        )
        print(f"  Finished at (UTC): {now_utc_str()}")
        if db_conn and run_id:
            finish_snapshot_run(db_conn, run_id, "skipped", 0, 0, 0, 0, 0,
                              "Skipped due to day-of-month gating")
            db_conn.close()
        if report_xlsx:
            os.makedirs(report_dir, exist_ok=True)
            summary = {
                "policy": policy_name,
                "dry_run": dry_run,
                "run_timestamp_utc": now_utc_str(),
                "total_volumes_processed": 0,
                "new_snapshots": 0,
                "snapshots_deleted": 0,
                "errors": len(ERRORS),
                "note": "Skipped due to day-of-month gating",
            }
            with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
                pd.DataFrame([summary]).to_excel(
                    writer, sheet_name="Summary", index=False
                )
                pd.DataFrame().to_excel(
                    writer, sheet_name="Actions", index=False
                )
            print(f"  Run report written: {report_path}")
        return

    print(f"[1/4] Auth (Keystone)...")
    session, token, body, scope_mode, sys_scope_error = get_session_best_scope()
    token_info = body.get("token", {})
    scoped_project = token_info.get("project", {})

    print(f"      Auth scope: {scope_mode}")
    if sys_scope_error:
        print(f"      SYSTEM scope failed earlier: {sys_scope_error}")
    if scope_mode == "project":
        print(
            f"      Project scope: {scoped_project.get('name')} "
            f"({scoped_project.get('id')})"
        )

    admin_project_id = scoped_project.get("id")
    if not admin_project_id:
        raise RuntimeError(
            "No scoped project_id from Keystone token. "
            "Make sure PROJECT_NAME/PROJECT_DOMAIN are set in CFG."
        )

    print(f"[2/4] Fetching volumes (all tenants via admin project {admin_project_id})...")
    try:
        volumes = cinder_volumes_all(session, admin_project_id)
    except Exception as e:
        raise SystemExit(
            f"Failed to list volumes from Cinder: {type(e).__name__}: {e}"
        )

    print(f"      Total volumes: {len(volumes)}")

    # Extra metadata maps for richer report (tenant/domain/VM/IP)
    (
        domain_name_by_id,
        project_name_by_id,
        project_domain_by_id,
        vol_to_srv_names,
        vol_to_srv_ids,
        vol_to_srv_ips,
    ) = _build_metadata_maps(session)

    # Filter by policy + metadata flags
    selected = select_volumes_for_policy(volumes, policy_name)
    print(
        f"[3/4] Volumes matching policy '{policy_name}' and auto_snapshot=true: "
        f"{len(selected)}"
    )
    if not selected:
        print("      Nothing to do.")
        print(f"  Finished at (UTC): {now_utc_str()}")

        if report_xlsx:
            os.makedirs(report_dir, exist_ok=True)
            summary = {
                "policy": policy_name,
                "dry_run": dry_run,
                "run_timestamp_utc": now_utc_str(),
                "total_volumes_processed": 0,
                "new_snapshots": 0,
                "snapshots_deleted": 0,
                "errors": len(ERRORS),
                "note": "No volumes matched policy/auto_snapshot=true",
            }
            with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
                pd.DataFrame([summary]).to_excel(
                    writer, sheet_name="Summary", index=False
                )
                pd.DataFrame().to_excel(
                    writer, sheet_name="Actions", index=False
                )
            print(f"  Run report written: {report_path}")
        return

    created_count = 0
    deleted_total = 0
    skipped_count = 0
    run_rows = []

    print(
        f"[4/4] Processing volumes (max new snapshots this run: {max_new}, "
        f"dry_run={dry_run})"
    )

    # Group volumes by project to use project-scoped service user sessions
    volumes_by_project = defaultdict(list)
    for v in selected:
        volume_project_id = (
            v.get("os-vol-tenant-attr:tenant_id")
            or v.get("project_id")
            or "UNKNOWN"
        )
        volumes_by_project[volume_project_id].append(v)
    
    print(f"      Volumes distributed across {len(volumes_by_project)} projects")
    
    # Process each project
    for project_idx, (vol_project_id, project_volumes) in enumerate(volumes_by_project.items(), start=1):
        project_name = project_name_by_id.get(vol_project_id, vol_project_id)
        print(f"\n=== Project {project_idx}/{len(volumes_by_project)}: {project_name} ({vol_project_id}) ===")
        print(f"    Volumes in this project: {len(project_volumes)}")
        
        # -----------------------------------------------------------------
        # Determine which session to use for CREATING snapshots
        #   create_session + create_project_id  →  snapshot lands here
        # Admin session is always used for listing / cleanup (all_tenants)
        # -----------------------------------------------------------------
        create_session = None
        create_project_id = None

        if vol_project_id != "UNKNOWN" and vol_project_id != admin_project_id and ensure_service_user:
            try:
                print(f"    Ensuring service user has admin role on project...")
                ensure_service_user(session, CFG["KEYSTONE_URL"], vol_project_id)
                
                # Get project-scoped session for service user
                print(f"    Authenticating as service user for this project...")
                service_password = get_service_user_password()
                svc_sess, svc_tok = get_service_user_session(
                    vol_project_id, 
                    SERVICE_USER_EMAIL, 
                    service_password,
                    user_domain="default"
                )
                
                if svc_sess:
                    create_session = svc_sess
                    create_project_id = vol_project_id
                    print(f"    ✓ Using service user session for project {project_name}")
                else:
                    print(f"    ⚠ Service user authentication failed")
                    print(f"    Falling back to admin session (snapshots will be in service domain)")
            except Exception as e:
                print(f"    ⚠ Could not use service user for project {project_name}: {e}")
                print(f"    Falling back to admin session (snapshots will be in service domain)")

        elif vol_project_id == admin_project_id:
            # Volume is already in the admin/service project – use admin session directly
            create_session = session
            create_project_id = admin_project_id
            print(f"    Using admin session (service domain project)")

        # Final fallback: admin session + admin_project_id
        if create_session is None:
            create_session = session
            create_project_id = admin_project_id
            if vol_project_id != admin_project_id:
                print(f"    ⚠ Falling back to admin session – snapshots will land in service domain")
    
        # Process volumes in this project
        for vol_idx, v in enumerate(project_volumes, start=1):
            if not dry_run and created_count >= max_new:
                print(
                    f"Reached max-new limit ({max_new}); skipping remaining volumes."
                )
                break

            print(f"\n  Volume [{vol_idx}/{len(project_volumes)}]")

            vol_id = v["id"]
            vol_name = v.get("name") or vol_id
            vol_size_gb = v.get("size", 0)
            volume_project_id = vol_project_id
            meta = v.get("metadata") or {}
            
            # Get tenant/domain info needed for all paths
            tenant_name = project_name_by_id.get(volume_project_id, "")
            domain_id = project_domain_by_id.get(volume_project_id, "")
            domain_name = domain_name_by_id.get(domain_id, "")
            
            # Check volume size limit (Platform9 API 413 workaround)
            if max_size_gb and vol_size_gb > max_size_gb:
                print(f"  Volume {vol_name} ({vol_id}), size={vol_size_gb}GB")
                print(f"  [SKIP] Volume size ({vol_size_gb}GB) exceeds limit ({max_size_gb}GB)")
                print(f"         Skipping due to Platform9 API limitation (413 Request Entity Too Large)")
                skipped_count += 1
                
                # Log to database as skipped
                if db_conn and run_id:
                    create_snapshot_record(
                        db_conn, run_id, "skipped", None, "", vol_id, vol_name,
                        volume_project_id, tenant_name, volume_project_id, tenant_name,
                        None, None, policy_name, vol_size_gb, 0,
                        "SKIPPED", f"Volume size ({vol_size_gb}GB) exceeds limit ({max_size_gb}GB) - Platform9 API limitation", 
                        raw_snapshot_json=v
                    )
                
                # Add to run_rows for reporting
                run_rows.append({
                    "timestamp_utc": now_utc_str(),
                    "policy": policy_name,
                    "dry_run": dry_run,
                    "project_id": volume_project_id,
                    "tenant_name": tenant_name,
                    "domain_id": domain_id,
                    "domain_name": domain_name,
                    "volume_id": vol_id,
                    "volume_name": vol_name,
                    "volume_size_gb": vol_size_gb,
                    "volume_status": v.get("status"),
                    "auto_snapshot": "N/A",
                    "configured_policies": "N/A",
                    "retention_for_policy": 0,
                    "attached_servers": "",
                    "attached_server_ids": "",
                    "attached_ips": "",
                    "primary_server_name": "",
                    "created_snapshot_id": "",
                    "created_snapshot_project_id": "",
                    "deleted_snapshot_ids": "",
                    "deleted_snapshots_count": 0,
                    "status": "SKIPPED",
                    "note": f"Volume size ({vol_size_gb}GB) exceeds limit ({max_size_gb}GB)",
                })
                
                continue
            
            auto_flag = str(meta.get("auto_snapshot", "")).lower() in ("true", "yes", "1")
            configured_policies = ",".join(_volume_policies_for(v))
            retention = _retention_for_volume_and_policy(v, policy_name, default=7)

            attached_server_names_list = vol_to_srv_names.get(vol_id, [])
            attached_server_names = ", ".join(attached_server_names_list)
            attached_server_ids = ", ".join(vol_to_srv_ids.get(vol_id, []))
            attached_ips = ", ".join(vol_to_srv_ips.get(vol_id, []))

            primary_server_name = attached_server_names_list[0] if attached_server_names_list else None

            sid, sid_project, deleted_ids, err_msg, snap_name = process_volume(
                admin_session=session,                # Admin for listing / cleanup
                admin_project_id=admin_project_id,    # MUST match admin token scope
                volume=v,
                policy_name=policy_name,
                dry_run=dry_run,
                primary_server_name=primary_server_name,
                tenant_name=tenant_name,
                create_session=create_session,         # Service-user (or admin fallback)
                create_project_id=create_project_id,   # Matches create_session scope
            )
            if sid:
                created_count += 1
            deleted_total += len(deleted_ids)

            if dry_run:
                status = "DRY_RUN"
                note = "Dry run; no changes applied"
            elif err_msg:
                status = "ERROR"
                note = err_msg
            elif sid:
                status = "OK"
                note = "Snapshot created"
            elif snap_name is None:
                status = "SKIPPED"
                note = "Already has a snapshot today for this policy"
            else:
                status = "OK"
                note = "No snapshot created"

            # Log to database if enabled
            if db_conn and run_id:
                action = "created" if sid else ("skipped" if not err_msg else "failed")
                create_snapshot_record(
                    db_conn, run_id, action, sid, snap_name or "", vol_id, vol_name,
                    volume_project_id, tenant_name, volume_project_id, tenant_name,
                attached_server_ids.split(", ")[0] if attached_server_ids else None,
                primary_server_name, policy_name, v.get("size"), retention,
                status, err_msg, raw_snapshot_json=v
            )

            run_rows.append(
                {
                    "timestamp_utc": now_utc_str(),
                    "policy": policy_name,
                    "dry_run": dry_run,
                    "project_id": volume_project_id,
                    "tenant_name": tenant_name,
                    "domain_id": domain_id,
                    "domain_name": domain_name,
                    "volume_id": vol_id,
                    "volume_name": vol_name,
                    "volume_size_gb": v.get("size"),
                    "volume_status": v.get("status"),
                    "auto_snapshot": auto_flag,
                    "configured_policies": configured_policies,
                    "retention_for_policy": retention,
                    "attached_servers": attached_server_names,
                    "attached_server_ids": attached_server_ids,
                    "attached_ips": attached_ips,
                    "primary_server_name": primary_server_name or "",
                    "created_snapshot_id": sid or "",
                    "created_snapshot_project_id": sid_project or "",
                    "deleted_snapshot_ids": ",".join(deleted_ids),
                    "deleted_snapshots_count": len(deleted_ids),
                    "status": status,
                    "note": note,
                }
            )

    print("\nSummary:")
    print(f"  Policy:            {policy_name}")
    print(f"  Dry run:           {dry_run}")
    print(f"  New snapshots:     {created_count}")
    print(f"  Snapshots deleted: {deleted_total}")
    print(f"  Errors logged:     {len(ERRORS)}")
    print(f"  Finished at (UTC): {now_utc_str()}")

    # Finalize database run tracking
    if db_conn and run_id:
        final_status = "completed" if not ERRORS else "partial"
        if dry_run:
            final_status = "dry_run_completed"
        error_summary = "; ".join([f"{e.get('area', 'unknown')}: {e.get('msg', 'no message')}" for e in ERRORS]) if ERRORS else None
        finish_snapshot_run(
            db_conn, run_id, final_status, len(run_rows), created_count,
            deleted_total, len([r for r in run_rows if r["status"] == "ERROR"]),
            skipped_count,  # Use the actual skipped_count variable
            error_summary
        )
        db_conn.close()
        print(f"[DB] Snapshot run {run_id} finalized with status: {final_status}")

    if report_xlsx:
        os.makedirs(report_dir, exist_ok=True)
        summary = {
            "policy": policy_name,
            "dry_run": dry_run,
            "run_timestamp_utc": now_utc_str(),
            "total_volumes_processed": len(run_rows),
            "new_snapshots": created_count,
            "snapshots_deleted": deleted_total,
            "errors": len([r for r in run_rows if r["status"] == "ERROR"]),
        }
        with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
            pd.DataFrame([summary]).to_excel(
                writer, sheet_name="Summary", index=False
            )
            pd.DataFrame(run_rows).to_excel(
                writer, sheet_name="Actions", index=False
            )
        print(f"Run report written: {report_path}")


if __name__ == "__main__":
    main()
