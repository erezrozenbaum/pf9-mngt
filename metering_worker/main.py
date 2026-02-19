"""
PF9 Metering Worker
====================
Long-lived container that periodically collects operational metering data
from the monitoring service, the PF9 API, and the database, then persists
aggregated records into the metering_* tables.

Data sources
------------
- **Monitoring service** (http://pf9_monitoring:8001/metrics)
    → per-VM CPU, RAM, disk, network usage
- **PF9 API** (http://pf9_api:8000/api/performance/stats)
    → API call counts, latency, error rates
- **PostgreSQL** (direct connection)
    → snapshots, restores, quotas from existing tables

Collection cadence is governed by `metering_config.collection_interval_min`
(default 15 min).  Retention pruning runs after each collection cycle.
"""

import datetime
import json
import logging
import os
import signal
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "pf9_mgmt")
DB_USER = os.getenv("DB_USER", "pf9")
DB_PASS = os.getenv("DB_PASS", "pf9pass")
MONITORING_URL = os.getenv("MONITORING_URL", "http://pf9_monitoring:8001")
API_URL = os.getenv("API_URL", "http://pf9_api:8000")
POLL_INTERVAL = int(os.getenv("METERING_POLL_INTERVAL", "60"))  # seconds

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [metering-worker] %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("metering")

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown = False

def _handle_signal(signum, _frame):
    global _shutdown
    log.info("Received signal %s – shutting down gracefully", signum)
    _shutdown = True

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )


def load_config(conn) -> Dict[str, Any]:
    """Read the single-row metering_config."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM metering_config WHERE id = 1")
        row = cur.fetchone()
        return dict(row) if row else {"enabled": False, "collection_interval_min": 15, "retention_days": 90}


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def collect_resource_metrics(conn) -> int:
    """
    Fetch per-VM metrics from the monitoring service and insert into
    metering_resources.  Looks up vcpus from the flavors table when
    the monitoring service does not provide them.
    """
    try:
        resp = requests.get(f"{MONITORING_URL}/metrics/vms", params={"limit": 5000}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        vms: List[Dict] = data.get("data", [])
    except Exception as exc:
        log.warning("Could not fetch VM metrics from monitoring: %s", exc)
        return 0

    if not vms:
        return 0

    # Build a flavor → vcpus lookup from the DB
    flavor_vcpus: Dict[str, int] = {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, vcpus FROM flavors WHERE vcpus IS NOT NULL AND vcpus > 0")
            for fname, fvcpus in cur.fetchall():
                flavor_vcpus[fname] = fvcpus
    except Exception:
        pass  # flavors table may not exist

    now = datetime.datetime.now(datetime.timezone.utc)
    rows = []
    for vm in vms:
        # Try monitoring data first, fall back to flavor lookup
        vcpus = vm.get("vcpus") or vm.get("vcpus_allocated")
        if not vcpus:
            flavor_name = vm.get("flavor", "")
            vcpus = flavor_vcpus.get(flavor_name)

        rows.append((
            now,
            vm.get("vm_id", ""),
            vm.get("vm_name"),
            vm.get("vm_ip"),
            vm.get("project_name"),
            vm.get("domain"),
            vm.get("host"),
            vm.get("flavor"),
            vcpus,
            vm.get("ram_mb") or vm.get("memory_total_mb"),
            vm.get("disk_gb") or vm.get("storage_total_gb"),
            # actual usage from PCD
            vm.get("cpu_usage_percent"),
            vm.get("memory_usage_mb") or vm.get("ram_usage_mb"),
            vm.get("memory_usage_percent") or vm.get("ram_usage_percent"),
            vm.get("storage_used_gb") or vm.get("disk_used_gb"),
            vm.get("storage_usage_percent") or vm.get("disk_usage_percent"),
            vm.get("network_rx_bytes"),
            vm.get("network_tx_bytes"),
            vm.get("storage_read_bytes"),
            vm.get("storage_write_bytes"),
        ))

    insert_sql = """
        INSERT INTO metering_resources (
            collected_at, vm_id, vm_name, vm_ip, project_name, domain, host, flavor,
            vcpus_allocated, ram_allocated_mb, disk_allocated_gb,
            cpu_usage_percent, ram_usage_mb, ram_usage_percent,
            disk_used_gb, disk_usage_percent,
            network_rx_bytes, network_tx_bytes,
            storage_read_bytes, storage_write_bytes
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s
        )
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, insert_sql, rows, page_size=200)
    conn.commit()
    return len(rows)


def collect_snapshot_metrics(conn) -> int:
    """
    Read current snapshot data from the database and insert metering records.
    Uses the snapshots table directly (has project_name, domain_name columns)
    and optionally joins compliance_details for compliance info.
    """
    select_sql = """
        SELECT s.id AS snapshot_id, s.name AS snapshot_name,
               s.volume_id, '' AS volume_name,
               COALESCE(s.project_name, s.tenant_name, '') AS project_name,
               COALESCE(s.domain_name, '') AS domain,
               COALESCE(s.size_gb, 0) AS size_gb,
               s.status, s.created_at,
               cd.policy_name, cd.is_compliant
        FROM snapshots s
        LEFT JOIN LATERAL (
            SELECT policy_name, is_compliant
            FROM compliance_details
            WHERE volume_id = s.volume_id
            ORDER BY created_at DESC LIMIT 1
        ) cd ON TRUE
        WHERE s.status IS NULL OR s.status != 'deleted'
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    rows_inserted = 0

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        try:
            cur.execute(select_sql)
        except psycopg2.errors.UndefinedTable as e:
            conn.rollback()
            # Retry without compliance join
            log.info("compliance_details table not found (%s) – trying snapshots only", e)
            try:
                cur.execute("""
                    SELECT s.id AS snapshot_id, s.name AS snapshot_name,
                           s.volume_id, '' AS volume_name,
                           COALESCE(s.project_name, s.tenant_name, '') AS project_name,
                           COALESCE(s.domain_name, '') AS domain,
                           COALESCE(s.size_gb, 0) AS size_gb,
                           s.status, s.created_at,
                           NULL AS policy_name, NULL AS is_compliant
                    FROM snapshots s
                    WHERE s.status IS NULL OR s.status != 'deleted'
                """)
            except Exception:
                conn.rollback()
                log.info("snapshots table not found – skipping snapshot metering")
                return 0
        except Exception as exc:
            conn.rollback()
            log.warning("Could not query snapshots: %s", exc)
            return 0

        snapshots = cur.fetchall()

    insert_sql = """
        INSERT INTO metering_snapshots (
            collected_at, snapshot_id, snapshot_name, volume_id, volume_name,
            project_name, domain, size_gb, status, policy_name, is_compliant, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    batch = []
    for s in snapshots:
        batch.append((
            now,
            s["snapshot_id"], s["snapshot_name"],
            s["volume_id"], s["volume_name"],
            s["project_name"], s["domain"],
            s.get("size_gb"), s.get("status"),
            s.get("policy_name"), s.get("is_compliant"),
            s.get("created_at"),
        ))

    if batch:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, insert_sql, batch, page_size=200)
        conn.commit()
        rows_inserted = len(batch)
    return rows_inserted


def collect_restore_metrics(conn) -> int:
    """
    Read recent restore operations from restore_jobs and persist metering records.
    Only collects restores not yet metered (by comparing initiated_at).
    """
    select_sql = """
        SELECT rj.id::text AS restore_id,
               rj.restore_point_id AS snapshot_id,
               rj.restore_point_name AS snapshot_name,
               rj.vm_id AS target_server_id,
               rj.vm_name AS target_server_name,
               COALESCE(rj.project_name, '') AS project_name,
               '' AS domain,
               rj.status,
               EXTRACT(EPOCH FROM (COALESCE(rj.finished_at, now()) - rj.started_at))::integer AS duration_seconds,
               rj.created_by AS initiated_by,
               rj.created_at AS initiated_at
        FROM restore_jobs rj
        WHERE rj.created_at > (
            SELECT COALESCE(MAX(initiated_at), '1970-01-01'::timestamptz)
            FROM metering_restores
        )
        ORDER BY rj.created_at
    """
    now = datetime.datetime.now(datetime.timezone.utc)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        try:
            cur.execute(select_sql)
        except psycopg2.errors.UndefinedTable:
            conn.rollback()
            log.info("restore_jobs table not found – skipping restore metering")
            return 0
        except Exception as exc:
            conn.rollback()
            log.warning("Could not query restore_jobs: %s", exc)
            return 0
        restores = cur.fetchall()

    if not restores:
        return 0

    insert_sql = """
        INSERT INTO metering_restores (
            collected_at, restore_id, snapshot_id, snapshot_name,
            target_server_id, target_server_name,
            project_name, domain, status, duration_seconds,
            initiated_by, initiated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    batch = []
    for r in restores:
        batch.append((
            now,
            str(r.get("restore_id", "")),
            r.get("snapshot_id"), r.get("snapshot_name"),
            r.get("target_server_id"), r.get("target_server_name"),
            r.get("project_name"), r.get("domain"),
            r.get("status"), r.get("duration_seconds"),
            r.get("initiated_by"), r.get("initiated_at"),
        ))

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, insert_sql, batch, page_size=200)
    conn.commit()
    return len(batch)


def collect_api_usage(conn) -> int:
    """
    Pull API performance stats from the PF9 API /metrics endpoint.
    The /metrics endpoint is public (no auth needed) and returns
    endpoint_stats as a list of objects.
    """
    try:
        resp = requests.get(f"{API_URL}/metrics", timeout=15)
        resp.raise_for_status()
        stats = resp.json()
    except Exception as exc:
        log.warning("Could not fetch API performance stats from /metrics: %s", exc)
        return 0

    now = datetime.datetime.now(datetime.timezone.utc)
    interval_start = now - datetime.timedelta(minutes=15)
    # endpoint_stats is a list of objects: [{"endpoint": "GET /api/xx", "count": N, ...}]
    endpoint_stats = stats.get("endpoint_stats", [])
    if isinstance(endpoint_stats, dict):
        # backward compat if format changes
        endpoint_stats = [{"endpoint": k, **v} for k, v in endpoint_stats.items()]

    if not endpoint_stats:
        return 0

    # Compute total error count from status_codes if available
    status_codes = stats.get("status_codes", {})
    total_errors_4xx = sum(v for k, v in status_codes.items() if str(k).startswith("4"))
    total_errors_5xx = sum(v for k, v in status_codes.items() if str(k).startswith("5"))

    insert_sql = """
        INSERT INTO metering_api_usage (
            collected_at, interval_start, interval_end,
            endpoint, method, total_calls, error_count,
            avg_latency_ms, p95_latency_ms, p99_latency_ms
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    batch = []
    for est in endpoint_stats:
        endpoint_key = est.get("endpoint", "")
        parts = endpoint_key.split(" ", 1)
        method = parts[0] if len(parts) > 1 else "GET"
        path = parts[1] if len(parts) > 1 else endpoint_key

        batch.append((
            now, interval_start, now,
            path, method,
            est.get("count", 0),
            0,  # per-endpoint error count not available
            round((est.get("avg_duration", 0) or 0) * 1000, 2),
            round((est.get("p95", 0) or 0) * 1000, 2) if est.get("p95") else None,
            round((est.get("p99", 0) or 0) * 1000, 2) if est.get("p99") else None,
        ))

    if batch:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, insert_sql, batch, page_size=200)
        conn.commit()
    return len(batch)


def collect_efficiency_scores(conn) -> int:
    """
    Compute per-VM efficiency scores from the latest metering_resources row.
    Efficiency = actual_usage / allocated * 100, weighted average across CPU/RAM/Disk.
    """
    # Get the latest resource record per VM
    select_sql = """
        SELECT DISTINCT ON (vm_id)
            vm_id, vm_name, project_name, domain,
            vcpus_allocated, ram_allocated_mb, disk_allocated_gb,
            cpu_usage_percent, ram_usage_percent, disk_usage_percent
        FROM metering_resources
        ORDER BY vm_id, collected_at DESC
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(select_sql)
        rows = cur.fetchall()

    if not rows:
        return 0

    now = datetime.datetime.now(datetime.timezone.utc)
    # Weights for overall score
    W_CPU, W_RAM, W_DISK = 0.40, 0.35, 0.25
    batch = []

    for r in rows:
        cpu_eff = float(r["cpu_usage_percent"]) if r.get("cpu_usage_percent") is not None else None
        ram_eff = float(r["ram_usage_percent"]) if r.get("ram_usage_percent") is not None else None
        disk_eff = float(r["disk_usage_percent"]) if r.get("disk_usage_percent") is not None else None

        # Compute weighted overall (skip None components)
        components = []
        if cpu_eff is not None:
            components.append((cpu_eff, W_CPU))
        if ram_eff is not None:
            components.append((ram_eff, W_RAM))
        if disk_eff is not None:
            components.append((disk_eff, W_DISK))

        if not components:
            continue

        total_weight = sum(w for _, w in components)
        overall = sum(v * w for v, w in components) / total_weight if total_weight else 0

        # Classification
        if overall >= 75:
            classification = "excellent"
            recommendation = "Well-utilised – no action needed."
        elif overall >= 50:
            classification = "good"
            recommendation = "Reasonable utilisation."
        elif overall >= 25:
            classification = "fair"
            recommendation = "Consider right-sizing – some resources underutilised."
        elif overall >= 5:
            classification = "poor"
            recommendation = "Significantly over-provisioned – right-size or consolidate."
        else:
            classification = "idle"
            recommendation = "VM appears idle – evaluate for decommissioning."

        batch.append((
            now,
            r["vm_id"], r.get("vm_name"), r.get("project_name"), r.get("domain"),
            round(cpu_eff, 2) if cpu_eff is not None else None,
            round(ram_eff, 2) if ram_eff is not None else None,
            round(disk_eff, 2) if disk_eff is not None else None,
            round(overall, 2),
            classification,
            recommendation,
        ))

    insert_sql = """
        INSERT INTO metering_efficiency (
            collected_at, vm_id, vm_name, project_name, domain,
            cpu_efficiency, ram_efficiency, storage_efficiency,
            overall_score, classification, recommendation
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, insert_sql, batch, page_size=200)
    conn.commit()
    return len(batch)


# ---------------------------------------------------------------------------
# Quota / usage collection  (computed from inventory tables)
# ---------------------------------------------------------------------------
def collect_quota_usage(conn) -> int:
    """
    Compute per-project resource usage from the live inventory tables
    (servers, volumes, snapshots, floating_ips, networks, ports, security_groups)
    and insert into metering_quotas.

    Quota limits are set to NULL because we don't have access to the
    OpenStack quota API — but the usage columns are real, giving the
    smart-query layer useful data to answer "quota for <tenant>" questions.
    """
    sql = """
        SELECT
            p.id          AS project_id,
            p.name        AS project_name,
            d.name        AS domain,
            -- Compute: vCPUs, RAM, instances
            COALESCE(comp.vcpus_used, 0)         AS vcpus_used,
            COALESCE(comp.ram_used_mb, 0)         AS ram_used_mb,
            COALESCE(comp.instances_used, 0)      AS instances_used,
            -- Storage: volumes
            COALESCE(vol.volumes_used, 0)         AS volumes_used,
            COALESCE(vol.storage_used_gb, 0)      AS storage_used_gb,
            -- Snapshots
            COALESCE(snap.snapshots_used, 0)      AS snapshots_used,
            -- Networking
            COALESCE(fip.floating_ips_used, 0)    AS floating_ips_used,
            COALESCE(net.networks_used, 0)        AS networks_used,
            COALESCE(pt.ports_used, 0)            AS ports_used,
            COALESCE(sg.security_groups_used, 0)  AS security_groups_used
        FROM projects p
        LEFT JOIN domains d ON d.id = p.domain_id
        -- Compute usage (join flavors for vCPUs / RAM)
        LEFT JOIN LATERAL (
            SELECT count(*)                                       AS instances_used,
                   COALESCE(SUM(f.vcpus), 0)                      AS vcpus_used,
                   COALESCE(SUM(f.ram_mb), 0)                     AS ram_used_mb
            FROM servers s
            LEFT JOIN flavors f ON f.id = s.flavor_id
            WHERE s.project_id = p.id
        ) comp ON true
        -- Volume usage
        LEFT JOIN LATERAL (
            SELECT count(*)                        AS volumes_used,
                   COALESCE(SUM(size_gb), 0)       AS storage_used_gb
            FROM volumes WHERE project_id = p.id
        ) vol ON true
        -- Snapshot usage
        LEFT JOIN LATERAL (
            SELECT count(*) AS snapshots_used
            FROM snapshots WHERE project_id = p.id
        ) snap ON true
        -- Floating IPs
        LEFT JOIN LATERAL (
            SELECT count(*) AS floating_ips_used
            FROM floating_ips WHERE project_id = p.id
        ) fip ON true
        -- Networks
        LEFT JOIN LATERAL (
            SELECT count(*) AS networks_used
            FROM networks WHERE project_id = p.id
        ) net ON true
        -- Ports
        LEFT JOIN LATERAL (
            SELECT count(*) AS ports_used
            FROM ports WHERE project_id = p.id
        ) pt ON true
        -- Security Groups
        LEFT JOIN LATERAL (
            SELECT count(*) AS security_groups_used
            FROM security_groups WHERE project_id = p.id
        ) sg ON true
        ORDER BY d.name, p.name
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    if not rows:
        return 0

    now = datetime.datetime.now(datetime.timezone.utc)
    batch = []
    for r in rows:
        batch.append((
            now,
            r["project_id"], r.get("project_name"), r.get("domain"),
            None, r["vcpus_used"],          # vcpus_quota (unknown), vcpus_used
            None, r["ram_used_mb"],          # ram_quota_mb, ram_used_mb
            None, r["instances_used"],       # instances_quota, instances_used
            None, r["volumes_used"],         # volumes_quota, volumes_used
            None, r["storage_used_gb"],      # storage_quota_gb, storage_used_gb
            None, r["snapshots_used"],       # snapshots_quota, snapshots_used
            None, r["floating_ips_used"],    # floating_ips_quota, floating_ips_used
            None, r["networks_used"],        # networks_quota, networks_used
            None, r["ports_used"],           # ports_quota, ports_used
            None, r["security_groups_used"], # security_groups_quota, security_groups_used
        ))

    insert_sql = """
        INSERT INTO metering_quotas (
            collected_at, project_id, project_name, domain,
            vcpus_quota, vcpus_used,
            ram_quota_mb, ram_used_mb,
            instances_quota, instances_used,
            volumes_quota, volumes_used,
            storage_quota_gb, storage_used_gb,
            snapshots_quota, snapshots_used,
            floating_ips_quota, floating_ips_used,
            networks_quota, networks_used,
            ports_quota, ports_used,
            security_groups_quota, security_groups_used
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, insert_sql, batch, page_size=200)
    conn.commit()
    return len(batch)


# ---------------------------------------------------------------------------
# Retention pruning
# ---------------------------------------------------------------------------
METERING_TABLES = [
    "metering_resources",
    "metering_snapshots",
    "metering_restores",
    "metering_api_usage",
    "metering_quotas",
    "metering_efficiency",
]


def prune_old_records(conn, retention_days: int):
    """Delete metering rows older than retention_days."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=retention_days)
    with conn.cursor() as cur:
        for table in METERING_TABLES:
            try:
                cur.execute(f"DELETE FROM {table} WHERE collected_at < %s", (cutoff,))
                deleted = cur.rowcount
                if deleted:
                    log.info("Pruned %d rows from %s (older than %d days)", deleted, table, retention_days)
            except Exception as exc:
                log.warning("Error pruning %s: %s", table, exc)
                conn.rollback()
    conn.commit()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run_collection_cycle():
    """Execute one full metering collection cycle."""
    conn = None
    try:
        conn = get_conn()
        cfg = load_config(conn)

        if not cfg.get("enabled", True):
            log.info("Metering is disabled – skipping collection")
            return

        retention_days = cfg.get("retention_days", 90)

        log.info("=== Metering collection cycle start ===")

        n = collect_resource_metrics(conn)
        log.info("Resources: %d VM records collected", n)

        n = collect_snapshot_metrics(conn)
        log.info("Snapshots: %d records collected", n)

        n = collect_restore_metrics(conn)
        log.info("Restores:  %d records collected", n)

        n = collect_api_usage(conn)
        log.info("API usage: %d endpoint records collected", n)

        n = collect_efficiency_scores(conn)
        log.info("Efficiency: %d VM scores computed", n)

        n = collect_quota_usage(conn)
        log.info("Quotas:    %d project usage records collected", n)

        prune_old_records(conn, retention_days)

        log.info("=== Metering collection cycle complete ===")

    except Exception as exc:
        log.error("Collection cycle failed: %s\n%s", exc, traceback.format_exc())
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def main():
    log.info("PF9 Metering Worker starting (poll every %ds)", POLL_INTERVAL)

    # Run an initial migration check
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM metering_config WHERE id = 1")
            if cur.fetchone():
                log.info("metering_config table verified")
        conn.close()
    except Exception as exc:
        log.error("Cannot reach metering_config – ensure migrate_metering.sql has been applied: %s", exc)
        # Don't exit – the table may appear later after migration

    # Determine actual interval from config
    try:
        conn = get_conn()
        cfg = load_config(conn)
        interval_min = cfg.get("collection_interval_min", 15)
        conn.close()
    except Exception:
        interval_min = 15

    effective_interval = max(interval_min * 60, POLL_INTERVAL)
    log.info("Effective collection interval: %d seconds (%d min)", effective_interval, effective_interval // 60)

    last_run = 0.0
    while not _shutdown:
        now = time.time()
        if now - last_run >= effective_interval:
            run_collection_cycle()
            last_run = time.time()
        time.sleep(min(30, effective_interval))  # wake up every 30s to check shutdown


if __name__ == "__main__":
    main()
