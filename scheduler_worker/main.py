"""
PF9 Scheduler Worker
====================
Replaces Windows Task Scheduler for two previously host-run scripts:

  1. host_metrics_collector.py  – collects host / VM metrics on a fixed interval
  2. pf9_rvtools.py              – runs a full OpenStack inventory on a daily schedule

All scheduling is configured via environment variables (see below).

Environment variables
---------------------
METRICS_ENABLED              true | false          (default: true)
METRICS_INTERVAL_SECONDS     int                   (default: 60)
METRICS_CACHE_PATH           path                  (default: /tmp/cache/metrics_cache.json)

RVTOOLS_ENABLED              true | false          (default: true)
RVTOOLS_SCHEDULE_TIME        HH:MM  (UTC)          (default: 03:00)
RVTOOLS_RUN_ON_START         true | false          (default: false)

DEMO_MODE                    true | false          (default: false)
  When true, live metrics collection is skipped (mirrors the upstream script's flag).

All PF9_* / PF9_DB_* env vars are forwarded to the scripts unchanged.
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time as _time_module
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests as _requests_mod

# ---------------------------------------------------------------------------
# Worker observability — Redis metrics (B10.1)
# ---------------------------------------------------------------------------
_REDIS_HOST = os.getenv("REDIS_HOST", "redis")
_REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
_REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
_WORKER_NAME = "scheduler_worker"
_worker_runs_total   = 0
_worker_errors_total = 0

def _report_worker_metrics(duration_s: float, had_error: bool, frequency_s: int) -> None:
    global _worker_runs_total, _worker_errors_total
    _worker_runs_total += 1
    if had_error:
        _worker_errors_total += 1
    try:
        import redis as _redis
        r = _redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, password=_REDIS_PASSWORD, socket_connect_timeout=2)
        r.hset(f"pf9:worker:{_WORKER_NAME}", mapping={
            "runs_total":          _worker_runs_total,
            "errors_total":        _worker_errors_total,
            "last_run_ts":         _time_module.time(),
            "last_run_duration_s": round(duration_s, 2),
            "frequency_s":         frequency_s,
            "label":               _WORKER_NAME,
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() in ("true", "1", "yes")
METRICS_INTERVAL = int(os.getenv("METRICS_INTERVAL_SECONDS", "60"))
METRICS_CACHE_PATH = os.getenv("METRICS_CACHE_PATH", "/tmp/cache/metrics_cache.json")

RVTOOLS_ENABLED = os.getenv("RVTOOLS_ENABLED", "true").lower() in ("true", "1", "yes")
RVTOOLS_INTERVAL_MINUTES = int(os.getenv("RVTOOLS_INTERVAL_MINUTES", "0"))  # 0 = use RVTOOLS_SCHEDULE_TIME
RVTOOLS_SCHEDULE_TIME = os.getenv("RVTOOLS_SCHEDULE_TIME", "03:00")         # HH:MM UTC, used when interval=0
RVTOOLS_RUN_ON_START = os.getenv("RVTOOLS_RUN_ON_START", "false").lower() in ("true", "1", "yes")
RVTOOLS_RETENTION_DAYS = int(os.getenv("RVTOOLS_RETENTION_DAYS", "30"))      # xlsx files older than this are deleted

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
MAX_PARALLEL_REGIONS = int(os.getenv("MAX_PARALLEL_REGIONS", "3"))
REGION_REQUEST_TIMEOUT_SEC = int(os.getenv("REGION_REQUEST_TIMEOUT_SEC", "30"))
RVTOOLS_TIMEOUT_SEC = int(os.getenv("PF9_RVTOOLS_TIMEOUT_SEC", "7200"))  # M10: configurable RVTools script timeout

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [scheduler-worker] %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("scheduler-worker")

_ALIVE_FILE = "/tmp/alive"


def _touch_alive() -> None:
    """Write a heartbeat file so Kubernetes liveness probes can detect stalled workers."""
    try:
        import time as _time
        with open(_ALIVE_FILE, "w") as fh:
            fh.write(str(_time.time()))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_running = True
_shutdown_event: asyncio.Event


def _handle_signal(signum, _frame):
    global _running
    log.info("Received signal %s – shutting down …", signum)
    _running = False
    try:
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(_shutdown_event.set)
    except Exception:
        pass


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Multi-region helpers
# ---------------------------------------------------------------------------

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
                log.warning("JWT_SECRET not set – cannot decrypt region password")
                return os.getenv("PF9_PASSWORD", "")
            key = _b64.urlsafe_b64encode(_hl.sha256(secret.encode()).digest())
            return Fernet(key).decrypt(password_enc[7:].encode()).decode()
        except Exception as exc:
            log.warning("Failed to decrypt region password: %s", exc)
            return os.getenv("PF9_PASSWORD", "")
    return password_enc  # plaintext fallback (legacy)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=1, max=10),
    reraise=True,
)
def _get_db_conn():
    import psycopg2  # local import – psycopg2 may not be installed in all envs
    return psycopg2.connect(
        host=os.getenv("PF9_DB_HOST", "db"),
        port=int(os.getenv("PF9_DB_PORT", "5432")),
        dbname=os.getenv("PF9_DB_NAME", os.getenv("POSTGRES_DB", "pf9_mgmt")),
        user=os.getenv("PF9_DB_USER", os.getenv("POSTGRES_USER", "pf9")),
        password=os.getenv("PF9_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "")),
        connect_timeout=10,
    )


# ---------------------------------------------------------------------------
# Circuit breaker (H15) — prevents cascading failures during DB outages
# ---------------------------------------------------------------------------
_cb_failure_count = 0
_cb_circuit_open_until = 0.0


def _get_db_conn_with_cb():
    """Wrap _get_db_conn() with a circuit breaker: after 3 consecutive failures,
    back off 60 seconds to prevent log storms during prolonged DB outages."""
    global _cb_failure_count, _cb_circuit_open_until
    if _time_module.time() < _cb_circuit_open_until:
        raise RuntimeError("Circuit open -- DB unavailable, skipping job")
    try:
        conn = _get_db_conn()
        _cb_failure_count = 0
        return conn
    except Exception:
        _cb_failure_count += 1
        if _cb_failure_count >= 3:
            _cb_circuit_open_until = _time_module.time() + 60  # back off 60s
            log.warning(
                "DB circuit breaker OPEN -- will retry in 60s (failure_count=%d)",
                _cb_failure_count,
            )
        raise


def load_enabled_regions() -> list:
    """Return enabled regions with decrypted credentials from the DB.
    Falls back to an empty list (single-region env-var mode) on any error."""
    try:
        conn = _get_db_conn_with_cb()
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
        log.warning("Could not load regions from DB (%s) – using env-var single region", exc)
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


# ---------------------------------------------------------------------------
# Metrics collection loop
# ---------------------------------------------------------------------------
async def metrics_loop() -> None:
    """Collect host / VM metrics from PF9 nodes on a fixed cadence.

    When multiple regions are configured in pf9_regions, one HostMetricsCollector
    is created per region so that each region's hypervisor hosts are polled
    independently.  Falls back to the legacy single-collector (env-var) mode
    when the DB has no region rows.
    """
    if DEMO_MODE:
        log.info("DEMO_MODE=true – live metrics collection is disabled.")
        return

    log.info(
        "Metrics loop starting  (interval=%d s, cache=%s)",
        METRICS_INTERVAL,
        METRICS_CACHE_PATH,
    )

    try:
        from host_metrics_collector import HostMetricsCollector
    except ImportError as exc:
        log.error("Cannot import HostMetricsCollector: %s – metrics loop disabled.", exc)
        return

    # Ensure the cache directory exists inside the container
    cache_dir = os.path.dirname(METRICS_CACHE_PATH)
    os.makedirs(cache_dir, exist_ok=True)

    def _make_collector(region_id: str = "") -> "HostMetricsCollector":
        c = HostMetricsCollector(region_id=region_id)
        rid_suffix = f"_{region_id}" if region_id else ""
        c.cache_file = os.path.join(cache_dir, f"metrics_cache{rid_suffix}.json")
        c._cpu_state_file = os.path.join(cache_dir, f"cpu_state{rid_suffix}.json")
        return c

    def _write_sync_metric(region_id: str, started_at, finished_at, error: bool):
        """Write a cluster_sync_metrics row for this metrics run."""
        if not region_id:
            return
        try:
            import psycopg2 as _pg2
            conn = _get_db_conn()
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO cluster_sync_metrics
                           (region_id, sync_type, started_at, finished_at,
                            duration_ms, resource_count, error_count, status)
                       VALUES (%s, 'host_metrics', %s, %s, %s, 0, %s, %s)""",
                    (region_id, started_at, finished_at, duration_ms,
                     1 if error else 0, "error" if error else "success"),
                )
            conn.commit()
            conn.close()
        except Exception as exc:
            log.debug("Could not write host_metrics sync metric: %s", exc)

    # Build initial collector map from regions
    regions = load_enabled_regions()
    if regions:
        collectors = {r["region_id"]: _make_collector(r["region_id"]) for r in regions}
        log.info("Metrics loop: %d region(s) configured", len(regions))
    else:
        # Single-region / env-var fallback
        collectors = {"": _make_collector()}
        log.info("Metrics loop: single-region (env-var) mode")

    consecutive_errors: dict = {rid: 0 for rid in collectors}

    while _running:
        for region_id, collector in list(collectors.items()):
            errs = consecutive_errors.get(region_id, 0)
            if errs >= 5:
                log.warning(
                    "Region %s: 5 consecutive failures – backing off; reset next cycle.",
                    region_id or "default",
                )
                consecutive_errors[region_id] = 0
                continue

            started_at = datetime.now(timezone.utc)
            try:
                await collector.run_once()
                consecutive_errors[region_id] = 0
                _write_sync_metric(region_id, started_at, datetime.now(timezone.utc), error=False)
            except Exception as exc:
                consecutive_errors[region_id] = errs + 1
                log.error(
                    "Region %s: metrics collection error (run %d): %s",
                    region_id or "default", errs + 1, exc,
                )
                _write_sync_metric(region_id, started_at, datetime.now(timezone.utc), error=True)

        # Sleep in 1-second ticks so SIGTERM is handled promptly
        _touch_alive()  # heartbeat — liveness probe checks /tmp/alive mtime
        for _ in range(METRICS_INTERVAL):
            if not _running:
                break
            await asyncio.sleep(1)

    log.info("Metrics loop stopped.")


# ---------------------------------------------------------------------------
# RVTools inventory loop
# ---------------------------------------------------------------------------
def _next_scheduled_run(schedule_hhmm: str) -> datetime:
    """Return the next UTC datetime when RVTools should fire."""
    hh, mm = schedule_hhmm.split(":")
    now = datetime.now(timezone.utc)
    target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _run_rvtools_sync(region: dict | None = None) -> None:
    """Run pf9_rvtools.py as an isolated subprocess.

    When *region* is provided the subprocess receives per-region credentials
    via its environment, enabling multi-region inventory collection.
    """
    script = os.path.join(os.path.dirname(__file__), "pf9_rvtools.py")

    # Per-run log file: /app/logs/rvtools_YYYYMMDD_HHMMSS[_region].log
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    region_suffix = f"_{region['region_id']}" if region else ""
    log_path = os.path.join(log_dir, f"rvtools_{ts}{region_suffix}.log")

    # Build environment: start with the current process env and overlay
    # region-specific credentials when running in multi-region mode.
    env = os.environ.copy()
    if region:
        env["PF9_AUTH_URL"] = region["auth_url"]
        env["PF9_USERNAME"] = region["username"]
        env["PF9_PASSWORD"] = region["password"]
        env["PF9_USER_DOMAIN"] = region["user_domain"]
        env["PF9_PROJECT_NAME"] = region["project_name"]
        env["PF9_PROJECT_DOMAIN"] = region["project_domain"]
        env["PF9_REGION_ID"] = region["region_id"]
        env["PF9_HOSTS"] = ""  # hosts are loaded from DB per-region

    log.info("RVTools: writing run log to %s", log_path)
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write(f"# RVTools run started at {datetime.now(timezone.utc).isoformat()}\n")
        lf.write(f"# Script: {script}\n")
        if region:
            lf.write(f"# Region: {region['region_id']} ({region['region_name']})\n")
        lf.write("\n")
        result = subprocess.run(
            [sys.executable, script],
            timeout=RVTOOLS_TIMEOUT_SEC,  # configurable via PF9_RVTOOLS_TIMEOUT_SEC (default 7200s)
            stdout=lf,
            stderr=subprocess.STDOUT,
            env=env,
        )
        lf.write(f"\n\n# Exit code: {result.returncode}\n")
        lf.write(f"# Run finished at {datetime.now(timezone.utc).isoformat()}\n")

    if result.returncode != 0:
        raise RuntimeError(
            f"pf9_rvtools.py exited with return code {result.returncode} — see {log_path}"
        )
    log.info("RVTools: run log saved to %s", log_path)


async def rvtools_loop(executor: ThreadPoolExecutor) -> None:
    """Run the RVTools inventory at the configured schedule.

    Supports both single-region (env-var credentials) and multi-region
    (credentials loaded from pf9_regions DB table) modes.

    Two scheduling modes (RVTOOLS_INTERVAL_MINUTES takes priority):
      Interval mode  – RVTOOLS_INTERVAL_MINUTES > 0  → run every N minutes.
      Schedule mode  – RVTOOLS_INTERVAL_MINUTES = 0  → run once daily at RVTOOLS_SCHEDULE_TIME.
    """
    loop = asyncio.get_event_loop()

    if RVTOOLS_RUN_ON_START:
        log.info("RVTools: RVTOOLS_RUN_ON_START=true – running immediately …")
        try:
            await _run_rvtools_for_all_regions(executor, loop)
            log.info("RVTools: startup run completed.")
        except Exception as exc:
            log.error("RVTools: startup run failed: %s", exc)

    while _running:
        if RVTOOLS_INTERVAL_MINUTES > 0:
            # ── Interval mode ──────────────────────────────────────────────────
            log.info("RVTools: next run in %d minute(s)", RVTOOLS_INTERVAL_MINUTES)
            for _ in range(RVTOOLS_INTERVAL_MINUTES * 60):
                if not _running:
                    break
                await asyncio.sleep(1)
        else:
            # ── Schedule mode (daily at fixed UTC time) ────────────────────────
            next_run = _next_scheduled_run(RVTOOLS_SCHEDULE_TIME)
            delay = (next_run - datetime.now(timezone.utc)).total_seconds()
            log.info(
                "RVTools: next run at %s UTC (in %.0f s / %.1f h)",
                next_run.strftime("%Y-%m-%d %H:%M"),
                delay,
                delay / 3600,
            )
            while _running:
                remaining = (next_run - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(60.0, remaining))

        if not _running:
            break

        log.info("RVTools: starting inventory run …")
        try:
            await _run_rvtools_for_all_regions(executor, loop)
            log.info("RVTools: inventory run completed.")
        except Exception as exc:
            log.error("RVTools: inventory run failed: %s", exc)

        # In schedule mode: brief pause so we don't re-trigger in the same minute.
        # In interval mode: the per-second sleep above already provides the gap.
        if RVTOOLS_INTERVAL_MINUTES == 0:
            await asyncio.sleep(70)

    log.info("RVTools loop stopped.")


def _snapshot_health_daily() -> None:
    """Upsert today's aggregate health counts into dashboard_health_snapshots.

    Runs once per RVTools cycle (daily or on interval) so the health-trend
    endpoint always has fresh data for the last 7 days of sparklines.
    Silently skips if the table does not exist yet (first deploy before migration).
    """
    try:
        conn = _get_db_conn_with_cb()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM servers")
                total_vms = (cur.fetchone() or [0])[0]

                cur.execute("SELECT COUNT(*) FROM servers WHERE status = 'ACTIVE'")
                running_vms = (cur.fetchone() or [0])[0]

                cur.execute("SELECT COUNT(*) FROM hypervisors")
                total_hosts = (cur.fetchone() or [0])[0]

                # Count critical alerts: hosts in error state or hypervisors with 0 VMs
                cur.execute(
                    "SELECT COUNT(*) FROM hypervisors WHERE state = 'down' OR status = 'disabled'"
                )
                critical_count = (cur.fetchone() or [0])[0]

                cur.execute(
                    """
                    INSERT INTO dashboard_health_snapshots
                        (snapshot_date, total_vms, running_vms, total_hosts, critical_count)
                    VALUES (CURRENT_DATE, %s, %s, %s, %s)
                    ON CONFLICT (snapshot_date) DO UPDATE SET
                        total_vms      = EXCLUDED.total_vms,
                        running_vms    = EXCLUDED.running_vms,
                        total_hosts    = EXCLUDED.total_hosts,
                        critical_count = EXCLUDED.critical_count,
                        recorded_at    = now()
                    """,
                    (total_vms, running_vms, total_hosts, critical_count),
                )
            conn.commit()
            log.info(
                "Health snapshot: vms=%d running=%d hosts=%d critical=%d",
                total_vms, running_vms, total_hosts, critical_count,
            )
        finally:
            conn.close()
    except Exception as exc:
        log.warning("Health snapshot: skipped — %s", exc)


def _cleanup_old_reports() -> None:
    """Delete xlsx files in PF9_OUTPUT_DIR older than RVTOOLS_RETENTION_DAYS."""
    import time as _time
    output_dir = os.getenv("PF9_OUTPUT_DIR", "/mnt/reports")
    if not os.path.isdir(output_dir):
        return
    if RVTOOLS_RETENTION_DAYS <= 0:
        return  # retention disabled
    cutoff = _time.time() - RVTOOLS_RETENTION_DAYS * 86400
    for fname in os.listdir(output_dir):
        if not fname.endswith(".xlsx"):
            continue
        fpath = os.path.join(output_dir, fname)
        try:
            if os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                log.info("RVTools: removed expired report %s (older than %d days)", fname, RVTOOLS_RETENTION_DAYS)
        except OSError as exc:
            log.warning("RVTools: could not remove %s: %s", fname, exc)


def _cleanup_expired_tokens() -> None:
    """L8: Purge expired password reset tokens from the DB.

    Runs once per RVTools cycle (~daily or per RVTOOLS_INTERVAL_MINUTES).
    Safe to skip on DB outage — old tokens just remain until next run.
    """
    try:
        conn = _get_db_conn_with_cb()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM password_reset_tokens WHERE expires_at < NOW()")
                deleted = cur.rowcount
            conn.commit()
            if deleted:
                log.info("Maintenance: purged %d expired password reset token(s)", deleted)
        finally:
            conn.close()
    except Exception as exc:
        log.warning("Maintenance: failed to purge expired tokens: %s", exc)


def _timeout_stale_restore_jobs() -> None:
    """Auto-fail restore jobs that have been stuck in PLANNED or RUNNING too long.

    Thresholds (tunable via env vars):
      RESTORE_PLANNED_TIMEOUT_H  — hours before a PLANNED job is auto-failed (default 2)
      RESTORE_RUNNING_TIMEOUT_H  — hours before a RUNNING job is auto-failed (default 6)

    PLANNED jobs that are never executed are a sign of a client crash or abandoned
    workflow.  RUNNING jobs that exceed the timeout indicate a stuck executor.
    """
    planned_h = int(os.getenv("RESTORE_PLANNED_TIMEOUT_H", "2"))
    running_h = int(os.getenv("RESTORE_RUNNING_TIMEOUT_H", "6"))
    try:
        conn = _get_db_conn_with_cb()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE restore_jobs
                          SET status = 'FAILED',
                              finished_at = NOW(),
                              failure_reason = 'Auto-failed by scheduler: job exceeded timeout'
                        WHERE (
                              status = 'PLANNED'
                              AND created_at < NOW() - make_interval(hours => %s)
                            ) OR (
                              status IN ('RUNNING', 'PENDING')
                              AND started_at < NOW() - make_interval(hours => %s)
                            )""",
                    (planned_h, running_h),
                )
                timed_out = cur.rowcount
            conn.commit()
            if timed_out:
                log.warning(
                    "Maintenance: timed out %d stale restore job(s) "
                    "(PLANNED > %dh or RUNNING > %dh)",
                    timed_out, planned_h, running_h,
                )
        finally:
            conn.close()
    except Exception as exc:
        log.warning("Maintenance: failed to timeout stale restore jobs: %s", exc)


async def _run_rvtools_for_all_regions(
    executor: ThreadPoolExecutor,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Run rvtools for every enabled region, up to MAX_PARALLEL_REGIONS concurrently.

    Falls back to a single env-var-based run when no regions are configured in the DB.
    """
    regions = await loop.run_in_executor(executor, load_enabled_regions)
    if not regions:
        log.info("RVTools: no regions in DB – running with env-var credentials")
        await loop.run_in_executor(executor, _run_rvtools_sync, None)
    else:
        log.info("RVTools: running across %d region(s) (max parallel: %d)", len(regions), MAX_PARALLEL_REGIONS)
        sem = asyncio.Semaphore(MAX_PARALLEL_REGIONS)

        async def _one_region(region: dict) -> None:
            async with sem:
                rname = region["region_name"]
                log.info("RVTools: [%s] starting", rname)
                try:
                    await loop.run_in_executor(executor, _run_rvtools_sync, region)
                    log.info("RVTools: [%s] completed", rname)
                except Exception as exc:
                    log.error("RVTools: [%s] failed: %s", rname, exc)

        await asyncio.gather(*[_one_region(r) for r in regions])

    # Purge xlsx files that exceed the retention window
    await loop.run_in_executor(executor, _cleanup_old_reports)
    # L8: Purge expired password reset tokens
    await loop.run_in_executor(executor, _cleanup_expired_tokens)
    # Auto-fail PLANNED / RUNNING restore jobs that have exceeded their timeout
    await loop.run_in_executor(executor, _timeout_stale_restore_jobs)
    # Capture daily health snapshot for dashboard sparklines
    await loop.run_in_executor(executor, _snapshot_health_daily)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def async_main() -> None:
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    async def _heartbeat_loop() -> None:
        """Report scheduler worker liveness to Redis once per METRICS_INTERVAL."""
        _hb_runs = 0
        while _running:
            _t0 = _time_module.time()
            _hb_runs += 1
            _report_worker_metrics(0.0, False, METRICS_INTERVAL)
            for _ in range(METRICS_INTERVAL):
                if not _running:
                    break
                await asyncio.sleep(1)

    if RVTOOLS_INTERVAL_MINUTES > 0:
        rvtools_mode = f"every {RVTOOLS_INTERVAL_MINUTES} minute(s)"
    else:
        rvtools_mode = f"daily at {RVTOOLS_SCHEDULE_TIME} UTC"

    log.info("PF9 Scheduler Worker starting")
    log.info(
        "  Metrics : %s  (every %d s \u2192 %s)",
        "ENABLED" if METRICS_ENABLED else "DISABLED",
        METRICS_INTERVAL,
        METRICS_CACHE_PATH,
    )
    log.info(
        "  RVTools : %s  (%s%s)",
        "ENABLED" if RVTOOLS_ENABLED else "DISABLED",
        rvtools_mode,
        ", also on startup" if RVTOOLS_RUN_ON_START else "",
    )
    if DEMO_MODE:
        log.info("  DEMO_MODE=true – metrics collection suppressed")

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rvtools")
    tasks = []

    try:
        if METRICS_ENABLED:
            tasks.append(asyncio.create_task(metrics_loop(), name="metrics"))
        if RVTOOLS_ENABLED:
            tasks.append(asyncio.create_task(rvtools_loop(executor), name="rvtools"))
        tasks.append(asyncio.create_task(_heartbeat_loop(), name="heartbeat"))

        if not tasks:
            log.warning(
                "All tasks are disabled. "
                "Set METRICS_ENABLED=true or RVTOOLS_ENABLED=true."
            )
            while _running:
                await asyncio.sleep(10)
            return

        await asyncio.gather(*tasks)
    finally:
        # Explicitly cancel any still-running tasks so run_in_executor threads
        # are interrupted and do not become orphans on the next restart.
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        executor.shutdown(wait=True)
        log.info("PF9 Scheduler Worker stopped.")


if __name__ == "__main__":
    asyncio.run(async_main())
