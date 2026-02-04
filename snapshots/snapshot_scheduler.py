#!/usr/bin/env python3
"""
Snapshot Scheduler

Runs:
  1) Policy assignment (metadata tagging) on interval
  2) Auto snapshot runs for active policies on interval

Environment:
  SNAPSHOT_SCHEDULER_ENABLED=true|false
  POLICY_ASSIGN_INTERVAL_MINUTES=60
  AUTO_SNAPSHOT_INTERVAL_MINUTES=60
  POLICY_ASSIGN_CONFIG=/app/snapshots/snapshot_policy_rules.json
  POLICY_ASSIGN_MERGE_EXISTING=true|false
  POLICY_ASSIGN_DRY_RUN=true|false
  AUTO_SNAPSHOT_MAX_NEW=200
  AUTO_SNAPSHOT_DRY_RUN=true|false
"""

import os
import time
import json
import subprocess
from datetime import datetime, timezone
from typing import List

import psycopg2

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
AUTO_SNAPSHOT_MAX_NEW = os.getenv("AUTO_SNAPSHOT_MAX_NEW")
AUTO_SNAPSHOT_DRY_RUN = os.getenv("AUTO_SNAPSHOT_DRY_RUN", "false").lower() in ("true", "1", "yes")


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


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


def run_policy_assign():
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

    log("Running policy assignment...")
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"Policy assignment failed: {result.stderr.strip() or result.stdout.strip()}")
    else:
        log("Policy assignment completed.")


def run_auto_snapshots():
    policies = fetch_active_policies()
    if not policies:
        log("No active policies found. Skipping auto snapshots.")
        return

    for policy in policies:
        args = [
            "python",
            "snapshots/p9_auto_snapshots.py",
            "--policy",
            policy,
        ]
        if AUTO_SNAPSHOT_MAX_NEW:
            args += ["--max-new", str(AUTO_SNAPSHOT_MAX_NEW)]
        if AUTO_SNAPSHOT_DRY_RUN:
            args.append("--dry-run")

        log(f"Running auto snapshots for policy: {policy}")
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            log(f"Auto snapshots failed for {policy}: {result.stderr.strip() or result.stdout.strip()}")
        else:
            log(f"Auto snapshots completed for {policy}.")


def main():
    if not SCHEDULER_ENABLED:
        log("Snapshot scheduler disabled. Exiting.")
        return

    next_policy_assign = 0
    next_auto_snapshots = 0

    while True:
        now = time.time()
        if now >= next_policy_assign:
            run_policy_assign()
            next_policy_assign = now + POLICY_ASSIGN_INTERVAL_MINUTES * 60

        if now >= next_auto_snapshots:
            run_auto_snapshots()
            next_auto_snapshots = now + AUTO_SNAPSHOT_INTERVAL_MINUTES * 60

        time.sleep(10)


if __name__ == "__main__":
    main()
