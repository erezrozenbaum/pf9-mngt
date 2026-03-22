#!/usr/bin/env python3
"""
Snapshot Scheduler

Runs:
  1) Policy assignment (metadata tagging) on interval
  2) Auto snapshot runs for active policies on interval

Environment:
  SNAPSHOT_SCHEDULER_ENABLED=true|false
  POLICY_ASSIGN_INTERVAL_MINUTES=60 (default: once per hour)
  AUTO_SNAPSHOT_INTERVAL_MINUTES=60 (default: once per hour)
  POLICY_ASSIGN_CONFIG=/app/snapshots/snapshot_policy_rules.json
  POLICY_ASSIGN_MERGE_EXISTING=true|false
  POLICY_ASSIGN_DRY_RUN=true|false
  AUTO_SNAPSHOT_MAX_NEW=200
  AUTO_SNAPSHOT_MAX_SIZE_GB=260 (volumes larger than this are skipped)
  AUTO_SNAPSHOT_BATCH_SIZE=20 (volumes per batch, keeps all tenant volumes together)
  AUTO_SNAPSHOT_BATCH_DELAY=5.0 (seconds between batches for API rate limiting)
  AUTO_SNAPSHOT_DRY_RUN=true|false
  RVTOOLS_INTEGRATION_ENABLED=true|false (default: true)
  COMPLIANCE_REPORT_ENABLED=true|false (default: true)
  COMPLIANCE_REPORT_INTERVAL_MINUTES=1440 (default: once per day)
  COMPLIANCE_REPORT_SLA_DAYS=2 (default: 2 days for compliance check)
"""

import os
import time
import json
import subprocess
import logging
import sys
from datetime import datetime, timezone
from typing import List
from logging.handlers import RotatingFileHandler

import psycopg2
from psycopg2.extras import Json

# Configure logging
LOG_DIR = os.getenv("LOG_DIR", "/app/logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Setup logger with both file and console output
logger = logging.getLogger("snapshot_scheduler")
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('[%(asctime)s UTC] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
console_formatter.converter = time.gmtime  # Use UTC
console_handler.setFormatter(console_formatter)

# File handler with rotation (10MB max, keep 5 files)
log_file = os.path.join(LOG_DIR, "snapshot_worker.log")
file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter(
    '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
file_formatter.converter = time.gmtime  # Use UTC
file_handler.setFormatter(file_formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

DB_HOST = os.getenv("PF9_DB_HOST", "localhost")
DB_PORT = int(os.getenv("PF9_DB_PORT", "5432"))
DB_NAME = os.getenv("PF9_DB_NAME", os.getenv("POSTGRES_DB", "pf9_mgmt"))
DB_USER = os.getenv("PF9_DB_USER", os.getenv("POSTGRES_USER", "pf9"))
DB_PASSWORD = os.getenv("PF9_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))

SCHEDULER_ENABLED = os.getenv("SNAPSHOT_SCHEDULER_ENABLED", "true").lower() in ("true", "1", "yes")
POLICY_ASSIGN_INTERVAL_MINUTES = int(os.getenv("POLICY_ASSIGN_INTERVAL_MINUTES", "60"))
AUTO_SNAPSHOT_INTERVAL_MINUTES = int(os.getenv("AUTO_SNAPSHOT_INTERVAL_MINUTES", "60"))
POLICY_ASSIGN_CONFIG = os.getenv("POLICY_ASSIGN_CONFIG", "/app/snapshots/snapshot_policy_rules.json")
POLICY_ASSIGN_MERGE = os.getenv("POLICY_ASSIGN_MERGE_EXISTING", "true").lower() in ("true", "1", "yes")
POLICY_ASSIGN_DRY_RUN = os.getenv("POLICY_ASSIGN_DRY_RUN", "false").lower() in ("true", "1", "yes")
POLICY_ASSIGN_SYNC_POLICY_SETS = os.getenv("POLICY_ASSIGN_SYNC_POLICY_SETS", "true").lower() in ("true", "1", "yes")
AUTO_SNAPSHOT_MAX_NEW = os.getenv("AUTO_SNAPSHOT_MAX_NEW")
AUTO_SNAPSHOT_MAX_SIZE_GB = os.getenv("AUTO_SNAPSHOT_MAX_SIZE_GB", "260")
AUTO_SNAPSHOT_DRY_RUN = os.getenv("AUTO_SNAPSHOT_DRY_RUN", "false").lower() in ("true", "1", "yes")
AUTO_SNAPSHOT_BATCH_SIZE = os.getenv("AUTO_SNAPSHOT_BATCH_SIZE", "20")
AUTO_SNAPSHOT_BATCH_DELAY = os.getenv("AUTO_SNAPSHOT_BATCH_DELAY", "5.0")
RVTOOLS_INTEGRATION_ENABLED = os.getenv("RVTOOLS_INTEGRATION_ENABLED", "true").lower() in ("true", "1", "yes")
COMPLIANCE_REPORT_ENABLED = os.getenv("COMPLIANCE_REPORT_ENABLED", "true").lower() in ("true", "1", "yes")
COMPLIANCE_REPORT_INTERVAL_MINUTES = int(os.getenv("COMPLIANCE_REPORT_INTERVAL_MINUTES", "1440"))
COMPLIANCE_REPORT_SLA_DAYS = int(os.getenv("COMPLIANCE_REPORT_SLA_DAYS", "2"))
MAX_PARALLEL_REGIONS = int(os.getenv("MAX_PARALLEL_REGIONS", "3"))
REGION_REQUEST_TIMEOUT_SEC = int(os.getenv("REGION_REQUEST_TIMEOUT_SEC", "30"))


def _decrypt_password(password_enc: str) -> str:
    """Resolve a control_plane.password_enc value to plaintext."""
    if not password_enc:
        return os.getenv("PF9_PASSWORD", "")
    if password_enc.startswith("env:"):
        return os.getenv("PF9_PASSWORD", "")
    if password_enc.startswith("fernet:"):
        try:
            import base64 as _b64
            import hashlib as _hl
            from cryptography.fernet import Fernet
            secret = os.getenv("JWT_SECRET", "") or os.getenv("JWT_SECRET_KEY", "")
            if not secret:
                log("[WARN] JWT_SECRET not set – cannot decrypt region password")
                return os.getenv("PF9_PASSWORD", "")
            key = _b64.urlsafe_b64encode(_hl.sha256(secret.encode()).digest())
            return Fernet(key).decrypt(password_enc[7:].encode()).decode()
        except Exception as exc:
            log(f"[WARN] Failed to decrypt region password: {exc}")
            return os.getenv("PF9_PASSWORD", "")
    return password_enc  # plaintext fallback


def _get_snap_db_conn():
    """Open a direct psycopg2 connection for region loading."""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def load_enabled_regions() -> List[dict]:
    """Return enabled regions with decrypted credentials.
    Returns empty list (single-region env-var mode) on any error."""
    try:
        conn = _get_snap_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.region_name,
                       cp.auth_url, cp.username, cp.password_enc,
                       cp.user_domain, cp.project_name, cp.project_domain
                FROM pf9_regions r
                JOIN pf9_control_planes cp ON cp.id = r.control_plane_id
                WHERE r.is_enabled = TRUE AND cp.is_enabled = TRUE
                ORDER BY r.priority ASC, r.id ASC
            """)
            rows = cur.fetchall()
        conn.close()
    except Exception as exc:
        log(f"Could not load regions from DB ({exc}) – using env-var single region")
        return []

    regions = []
    for row in rows:
        region_id, region_name, auth_url, username, password_enc, \
            user_domain, project_name, project_domain = row
        regions.append({
            "region_id": region_id,
            "region_name": region_name,
            "auth_url": auth_url,
            "username": username,
            "password": _decrypt_password(password_enc),
            "user_domain": user_domain,
            "project_name": project_name,
            "project_domain": project_domain,
        })
    return regions


def _region_env(region: dict) -> dict:
    """Build a subprocess environment dict with per-region PF9 credentials."""
    env = os.environ.copy()
    env["PF9_AUTH_URL"] = region["auth_url"]
    env["PF9_USERNAME"] = region["username"]
    env["PF9_PASSWORD"] = region["password"]
    env["PF9_USER_DOMAIN"] = region["user_domain"]
    env["PF9_PROJECT_NAME"] = region["project_name"]
    env["PF9_PROJECT_DOMAIN"] = region["project_domain"]
    env["PF9_REGION_ID"] = region["region_id"]
    return env


def log(msg: str) -> None:
    logger.info(msg)


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def load_rules() -> List[dict]:
    try:
        with open(POLICY_ASSIGN_CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            log(f"Loaded {len(data)} rule(s) from {POLICY_ASSIGN_CONFIG}")
            return data
        return []
    except Exception as e:
        log(f"Failed to load rules from {POLICY_ASSIGN_CONFIG}: {e}")
        return []


def sync_policy_sets_from_rules():
    """Create/update snapshot_policy_sets based on rules file."""
    rules = load_rules()
    if not rules:
        return

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            for rule in rules:
                policies = rule.get("policies") or []
                if not policies:
                    continue

                retention = rule.get("retention") or {}
                if not retention:
                    retention = {p: 7 for p in policies}

                match = rule.get("match") or {}
                tenant_name = None
                is_global = True
                if isinstance(match.get("tenant_name"), str):
                    tenant_name = match.get("tenant_name")
                    is_global = False

                name = rule.get("name") or "policy-set"
                description = rule.get("description")
                priority = int(rule.get("priority", 0))

                cur.execute(
                    """
                    INSERT INTO snapshot_policy_sets
                        (name, description, is_global, tenant_id, tenant_name,
                         policies, retention_map, priority, is_active,
                         created_by, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s)
                    ON CONFLICT (name, tenant_id) DO UPDATE SET
                        description = EXCLUDED.description,
                        is_global = EXCLUDED.is_global,
                        tenant_name = EXCLUDED.tenant_name,
                        policies = EXCLUDED.policies,
                        retention_map = EXCLUDED.retention_map,
                        priority = EXCLUDED.priority,
                        is_active = true,
                        updated_at = now(),
                        updated_by = EXCLUDED.updated_by
                    """,
                    (
                        name,
                        description,
                        is_global,
                        None,
                        tenant_name,
                        Json(policies),
                        Json(retention),
                        priority,
                        "scheduler",
                        "scheduler",
                    ),
                )
        conn.commit()
        conn.close()
        log("Policy sets synced from rules.")
    except Exception as e:
        log(f"Failed to sync policy sets: {e}")


def fetch_active_policies() -> List[str]:
    """Get distinct policy names from active policy sets."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT jsonb_array_elements_text(policies) AS policy
                FROM snapshot_policy_sets
                WHERE is_active = true
                """
            )
            policies = [row[0] for row in cur.fetchall()]
        conn.close()
        return sorted(set(policies))
    except Exception as e:
        log(f"Error loading policies: {e}")
        return []


def run_policy_assign(region: dict | None = None):
    if POLICY_ASSIGN_SYNC_POLICY_SETS:
        sync_policy_sets_from_rules()
    args = [
        "python",
        "snapshots/p9_snapshot_policy_assign.py",
        "--config",
        POLICY_ASSIGN_CONFIG,
    ]
    if POLICY_ASSIGN_MERGE:
        args.append("--merge-existing")
    if POLICY_ASSIGN_DRY_RUN:
        args.append("--dry-run")
    if region:
        args += ["--region-id", region["region_id"]]

    label = f" [{region['region_id']}]" if region else ""
    log(f"Running policy assignment{label}...")
    run_kwargs = {"text": True}
    if region:
        run_kwargs["env"] = _region_env(region)
    result = subprocess.run(args, **run_kwargs)
    if result.returncode != 0:
        log(f"Policy assignment{label} failed with return code {result.returncode}")
    else:
        log(f"Policy assignment{label} completed.")


def run_rvtools(region: dict | None = None):
    """Run RVTools to sync inventory from Platform9 to database."""
    if not RVTOOLS_INTEGRATION_ENABLED:
        log("RVTools integration disabled. Skipping.")
        return

    label = f" [{region['region_id']}]" if region else ""
    log(f"Running RVTools inventory sync{label}...")
    run_kwargs = {"text": True}
    if region:
        run_kwargs["env"] = _region_env(region)
    result = subprocess.run(["python", "pf9_rvtools.py"], **run_kwargs)
    if result.returncode != 0:
        log(f"RVTools sync{label} failed with return code {result.returncode}")
    else:
        log(f"RVTools sync{label} completed.")


def run_auto_snapshots(region: dict | None = None):
    policies = fetch_active_policies()
    if not policies:
        log("No active policies found. Skipping auto snapshots.")
        return

    label = f" [{region['region_id']}]" if region else ""
    for policy in policies:
        args = [
            "python",
            "snapshots/p9_auto_snapshots.py",
            "--policy",
            policy,
        ]
        if region:
            args += ["--region-id", region["region_id"]]
        if AUTO_SNAPSHOT_MAX_NEW:
            args += ["--max-new", str(AUTO_SNAPSHOT_MAX_NEW)]
        if AUTO_SNAPSHOT_MAX_SIZE_GB:
            args += ["--max-size-gb", str(AUTO_SNAPSHOT_MAX_SIZE_GB)]
        if AUTO_SNAPSHOT_BATCH_SIZE:
            args += ["--batch-size", str(AUTO_SNAPSHOT_BATCH_SIZE)]
        if AUTO_SNAPSHOT_BATCH_DELAY:
            args += ["--batch-delay", str(AUTO_SNAPSHOT_BATCH_DELAY)]
        if AUTO_SNAPSHOT_DRY_RUN:
            args.append("--dry-run")

        log(f"Running auto snapshots for policy: {policy}{label}")
        run_kwargs = {"text": True}
        if region:
            run_kwargs["env"] = _region_env(region)
        result = subprocess.run(args, **run_kwargs)
        if result.returncode != 0:
            log(f"Auto snapshots failed for {policy}{label} with return code {result.returncode}")
        else:
            log(f"Auto snapshots completed for {policy}{label}.")


def run_compliance_report(region: dict | None = None):
    """Run snapshot compliance report generation."""
    if not COMPLIANCE_REPORT_ENABLED:
        log("Compliance report generation disabled. Skipping.")
        return

    label = f" [{region['region_id']}]" if region else ""
    log(f"Running snapshot compliance report generation{label}...")
    args = [
        "python",
        "snapshots/p9_snapshot_compliance_report.py",
        "--sla-days",
        str(COMPLIANCE_REPORT_SLA_DAYS),
    ]
    if region:
        args += ["--region-id", region["region_id"]]

    run_kwargs = {"text": True}
    if region:
        run_kwargs["env"] = _region_env(region)
    result = subprocess.run(args, **run_kwargs)
    if result.returncode != 0:
        log(f"Compliance report generation{label} failed with return code {result.returncode}")
    else:
        log(f"Compliance report generation{label} completed.")


# =========================================================================
# On-Demand Pipeline  (triggered by the API via snapshot_on_demand_runs)
# =========================================================================

def _update_on_demand_step(conn, run_id, step_key, step_status, error=None):
    """Update a single step inside the steps JSONB column."""
    finished = datetime.now(timezone.utc).isoformat() if step_status in ("completed", "failed") else None
    started = datetime.now(timezone.utc).isoformat() if step_status == "running" else None

    # Build a JSONB update: find the matching step by key and patch it
    if step_status == "running":
        sql = """
            UPDATE snapshot_on_demand_runs
            SET steps = (
                SELECT jsonb_agg(
                    CASE WHEN elem->>'key' = %s
                         THEN elem || jsonb_build_object('status', %s, 'started_at', %s)
                         ELSE elem
                    END
                ) FROM jsonb_array_elements(steps) AS elem
            )
            WHERE id = %s
        """
        params = (step_key, step_status, started, run_id)
    elif step_status == "completed":
        sql = """
            UPDATE snapshot_on_demand_runs
            SET steps = (
                SELECT jsonb_agg(
                    CASE WHEN elem->>'key' = %s
                         THEN elem || jsonb_build_object('status', %s, 'finished_at', %s)
                         ELSE elem
                    END
                ) FROM jsonb_array_elements(steps) AS elem
            )
            WHERE id = %s
        """
        params = (step_key, step_status, finished, run_id)
    else:  # failed
        sql = """
            UPDATE snapshot_on_demand_runs
            SET steps = (
                SELECT jsonb_agg(
                    CASE WHEN elem->>'key' = %s
                         THEN elem || jsonb_build_object('status', %s, 'finished_at', %s, 'error', %s)
                         ELSE elem
                    END
                ) FROM jsonb_array_elements(steps) AS elem
            )
            WHERE id = %s
        """
        params = (step_key, step_status, finished, error or "", run_id)

    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def check_on_demand_trigger():
    """Check the DB for a pending on-demand run and execute it if found."""
    try:
        conn = get_db_connection()
    except Exception as e:
        log(f"On-demand check: DB connection failed: {e}")
        return

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, job_id FROM snapshot_on_demand_runs
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """)
            row = cur.fetchone()
            if not row:
                conn.close()
                return

            run_id, job_id = row[0], row[1]

            # Mark as running
            cur.execute("""
                UPDATE snapshot_on_demand_runs
                SET status = 'running', started_at = now()
                WHERE id = %s
            """, (run_id,))
            conn.commit()

        log(f"On-demand pipeline started (job_id={job_id})")

        pipeline_steps = [
            ("policy_assign", "Policy Assignment"),
            ("rvtools_pre", "Inventory Sync (pre-snapshot)"),
            ("auto_snapshots", "Auto Snapshots"),
            ("rvtools_post", "Inventory Sync (post-snapshot)"),
        ]

        for step_key, step_label in pipeline_steps:
            _update_on_demand_step(conn, run_id, step_key, "running")
            log(f"On-demand step '{step_label}' running...")

            try:
                if step_key == "policy_assign":
                    run_policy_assign()
                elif step_key in ("rvtools_pre", "rvtools_post"):
                    run_rvtools()
                elif step_key == "auto_snapshots":
                    run_auto_snapshots()

                _update_on_demand_step(conn, run_id, step_key, "completed")
                log(f"On-demand step '{step_label}' completed.")

            except Exception as exc:
                err_msg = str(exc)
                log(f"On-demand step '{step_label}' failed: {err_msg}")
                _update_on_demand_step(conn, run_id, step_key, "failed", err_msg)

                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE snapshot_on_demand_runs
                        SET status = 'failed', finished_at = now(), error = %s
                        WHERE id = %s
                    """, (err_msg, run_id))
                    conn.commit()
                conn.close()
                return

        # All steps completed
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE snapshot_on_demand_runs
                SET status = 'completed', finished_at = now()
                WHERE id = %s
            """, (run_id,))
            conn.commit()
        conn.close()
        log(f"On-demand pipeline completed (job_id={job_id})")

    except Exception as e:
        log(f"On-demand pipeline error: {e}")
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE snapshot_on_demand_runs
                    SET status = 'failed', finished_at = now(), error = %s
                    WHERE id = %s AND status = 'running'
                """, (str(e), run_id))
                conn.commit()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def main():
    if not SCHEDULER_ENABLED:
        log("Snapshot scheduler disabled. Exiting.")
        return

    log("Snapshot scheduler starting...")

    # Give a 60-second startup grace period before the first scheduled run so
    # that on-demand triggers raised immediately after a restart are picked up
    # within one polling cycle (≤ 10 s) rather than waiting for the full
    # policy-assign + rvtools + auto-snapshot sequence to finish first.
    _startup_grace = time.time() + 60
    next_policy_assign = _startup_grace
    next_auto_snapshots = _startup_grace
    next_compliance_report = _startup_grace

    while True:
        # On-demand triggers checked FIRST so they are never blocked by
        # long-running scheduled tasks during the same loop iteration.
        check_on_demand_trigger()

        now = time.time()

        # Load enabled regions (empty list = single env-var region mode)
        regions = load_enabled_regions()
        region_list = regions if regions else [None]  # None = use env-var credentials

        if now >= next_policy_assign:
            for region in region_list:
                run_policy_assign(region)
            next_policy_assign = now + POLICY_ASSIGN_INTERVAL_MINUTES * 60

        if now >= next_auto_snapshots:
            for region in region_list:
                # Run RVTools BEFORE snapshots to get fresh inventory
                run_rvtools(region)
                # Run snapshot creation
                run_auto_snapshots(region)
                # Run RVTools AFTER snapshots to capture new snapshots in DB
                run_rvtools(region)
            next_auto_snapshots = now + AUTO_SNAPSHOT_INTERVAL_MINUTES * 60

        if now >= next_compliance_report:
            for region in region_list:
                run_compliance_report(region)
    main()