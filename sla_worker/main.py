"""
PF9 SLA Compliance Worker
==========================
Nightly worker that computes monthly SLA KPIs per tenant and writes them into
sla_compliance_monthly.  When a tenant is at-risk or already breaching, the
worker upserts an operational_insights row so the breach surfaces in the insight
feed and (in Phase 4) the PSA webhook.

Data sources
------------
- v_tenant_health          → uptime proxy (active_servers / total_servers)
- restore_jobs             → RTO (worst single restore duration this month)
- snapshots                → RPO (max gap between consecutive snapshots per VM)
- support_tickets          → MTTA (first_response_at - created_at avg)
                             MTTR (resolved_at - created_at avg)
- sla_commitments          → thresholds per tenant

KPIs are written to sla_compliance_monthly and at-risk/breach insights are
written to operational_insights (type='sla_risk').

Run cadence
-----------
Configurable via SLA_POLL_INTERVAL (seconds). Default: 14400 (4 h).
Full monthly recompute runs every cycle; it is cheap (aggregations on small tables).
"""

import datetime
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ---------------------------------------------------------------------------
# Worker observability — Redis metrics
# ---------------------------------------------------------------------------
_REDIS_HOST  = os.getenv("REDIS_HOST", "redis")
_REDIS_PORT  = int(os.getenv("REDIS_PORT", "6379"))
_REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
_WORKER_NAME = "sla_worker"
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
            "last_run_ts":         time.time(),
            "last_run_duration_s": round(duration_s, 2),
            "frequency_s":         frequency_s,
            "label":               _WORKER_NAME,
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------
def _read_secret(name: str, env_var: str, default: str = "") -> str:
    path = f"/run/secrets/{name}"
    if os.path.isfile(path):
        try:
            with open(path) as fh:
                val = fh.read().strip()
            if val:
                return val
        except OSError:
            pass
    return os.getenv(env_var, default)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_HOST       = os.getenv("DB_HOST", "db")
DB_PORT       = os.getenv("DB_PORT", "5432")
DB_NAME       = os.getenv("DB_NAME", "pf9_mgmt")
DB_USER       = os.getenv("DB_USER", "pf9")
DB_PASS       = _read_secret("db_password", "DB_PASS") or os.getenv("POSTGRES_PASSWORD", "")
POLL_INTERVAL = int(os.getenv("SLA_POLL_INTERVAL", "14400"))  # seconds

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sla-worker] %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("sla")

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    log.info("Signal %s received — shutting down", signum)
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(psycopg2.OperationalError),
    reraise=True,
)
def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )


# ---------------------------------------------------------------------------
# KPI computation helpers
# ---------------------------------------------------------------------------

def _compute_uptime_pct(conn, project_id: str, month_start: datetime.date,
                         month_end: datetime.date) -> Optional[float]:
    """
    Uptime proxy: active_servers / total_servers from v_tenant_health.
    Phase 0 limitation — in future phases, health snapshots stored over time
    will enable proper time-weighted uptime calculation.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT active_servers, total_servers
                FROM v_tenant_health
                WHERE project_id = %s
            """, (project_id,))
            row = cur.fetchone()
        if not row or not row[1]:
            return None
        active, total = row
        return round(float(active) / float(total) * 100, 3)
    except Exception as exc:
        log.debug("uptime query failed for %s: %s", project_id, exc)
        return None


def _compute_rto_worst(conn, project_id: str, month_start: datetime.date,
                        month_end: datetime.date) -> Optional[float]:
    """Worst single completed restore duration (hours) for the month."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT MAX(EXTRACT(EPOCH FROM (finished_at - started_at)) / 3600.0)
                FROM restore_jobs
                WHERE project_id = %s
                  AND status = 'SUCCEEDED'
                  AND started_at >= %s
                  AND started_at <  %s
                  AND finished_at IS NOT NULL
                  AND started_at  IS NOT NULL
            """, (project_id, month_start, month_end))
            row = cur.fetchone()
        val = row[0] if row else None
        return round(float(val), 2) if val is not None else None
    except Exception as exc:
        log.debug("rto query failed for %s: %s", project_id, exc)
        return None


def _compute_rpo_worst(conn, project_id: str, month_start: datetime.date,
                        month_end: datetime.date) -> Optional[float]:
    """
    Worst RPO (hours): maximum gap between consecutive completed snapshots
    across all VMs in the project, within the month.
    """
    try:
        with conn.cursor() as cur:
            # Find all successful snapshots for volumes belonging to VMs in this project,
            # ordered by volume + time. Compute inter-snapshot gap per volume.
            cur.execute("""
                WITH ordered AS (
                    SELECT
                        s.volume_id,
                        s.created_at,
                        LAG(s.created_at) OVER (
                            PARTITION BY s.volume_id ORDER BY s.created_at
                        ) AS prev_snap
                    FROM snapshots s
                    WHERE s.project_id = %s
                      AND s.status IN ('available', 'active')
                      AND s.created_at >= %s
                      AND s.created_at <  %s
                )
                SELECT MAX(EXTRACT(EPOCH FROM (created_at - prev_snap)) / 3600.0)
                FROM ordered
                WHERE prev_snap IS NOT NULL
            """, (project_id, month_start, month_end))
            row = cur.fetchone()
        val = row[0] if row else None
        return round(float(val), 2) if val is not None else None
    except Exception as exc:
        log.debug("rpo query failed for %s: %s", project_id, exc)
        return None


def _compute_mtta(conn, project_id: str, month_start: datetime.date,
                   month_end: datetime.date) -> Optional[float]:
    """Average time-to-first-response (hours) for tickets in the month."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT AVG(EXTRACT(EPOCH FROM (first_response_at - created_at)) / 3600.0)
                FROM support_tickets
                WHERE project_id = %s
                  AND created_at >= %s
                  AND created_at <  %s
                  AND first_response_at IS NOT NULL
            """, (project_id, month_start, month_end))
            row = cur.fetchone()
        val = row[0] if row else None
        return round(float(val), 2) if val is not None else None
    except Exception as exc:
        log.debug("mtta query failed for %s: %s", project_id, exc)
        return None


def _compute_mttr(conn, project_id: str, month_start: datetime.date,
                   month_end: datetime.date) -> Optional[float]:
    """Average time-to-resolve (hours) for tickets closed in the month."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600.0)
                FROM support_tickets
                WHERE project_id = %s
                  AND created_at >= %s
                  AND created_at <  %s
                  AND resolved_at IS NOT NULL
                  AND status IN ('resolved', 'closed')
            """, (project_id, month_start, month_end))
            row = cur.fetchone()
        val = row[0] if row else None
        return round(float(val), 2) if val is not None else None
    except Exception as exc:
        log.debug("mttr query failed for %s: %s", project_id, exc)
        return None


def _compute_backup_success_pct(conn, project_id: str, month_start: datetime.date,
                                  month_end: datetime.date) -> Optional[float]:
    """Percentage of snapshots that completed successfully in the month."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('available','active')) AS good,
                    COUNT(*) AS total
                FROM snapshots
                WHERE project_id = %s
                  AND created_at >= %s
                  AND created_at <  %s
            """, (project_id, month_start, month_end))
            row = cur.fetchone()
        if not row or not row[1]:
            return None
        good, total = row
        return round(float(good) / float(total) * 100, 2)
    except Exception as exc:
        log.debug("backup_success query failed for %s: %s", project_id, exc)
        return None


# ---------------------------------------------------------------------------
# Breach detection
# ---------------------------------------------------------------------------

def _detect_breaches(kpis: Dict[str, Any], commitment: Dict[str, Any],
                      days_in_month: int, today: datetime.date,
                      month_start: datetime.date) -> tuple[list, list]:
    """
    Returns (breach_fields, at_risk_fields).
    at_risk = within 10 % of threshold AND >= 5 days remaining in the month.
    """
    breach: list[str] = []
    at_risk: list[str] = []

    days_remaining = (
        datetime.date(month_start.year + (month_start.month // 12),
                      (month_start.month % 12) + 1, 1) - today
    ).days if today.day < days_in_month else 0

    def _check(field: str, actual, limit, higher_is_worse: bool = True):
        if actual is None or limit is None:
            return
        if higher_is_worse:
            if actual > limit:
                breach.append(field)
            elif days_remaining >= 5 and actual > limit * 0.9:
                at_risk.append(field)
        else:
            # lower actual is worse (uptime_pct: actual must be >= limit)
            if actual < limit:
                breach.append(field)
            elif days_remaining >= 5 and actual < limit * 1.001:
                # within ~0.1 percentage points below commitment
                at_risk.append(field)

    _check("uptime_pct",   kpis.get("uptime_actual_pct"), commitment.get("uptime_pct"),
           higher_is_worse=False)
    _check("rto",          kpis.get("rto_worst_hours"),   commitment.get("rto_hours"))
    _check("rpo",          kpis.get("rpo_worst_hours"),   commitment.get("rpo_hours"))
    _check("mtta",         kpis.get("mtta_avg_hours"),    commitment.get("mtta_hours"))
    _check("mttr",         kpis.get("mttr_avg_hours"),    commitment.get("mttr_hours"))

    return breach, at_risk


# ---------------------------------------------------------------------------
# Insight upsert
# ---------------------------------------------------------------------------

def _upsert_sla_insight(conn, project_id: str, project_name: str,
                         breach_fields: list, at_risk_fields: list,
                         month: datetime.date) -> None:
    if not breach_fields and not at_risk_fields:
        return
    severity = "critical" if breach_fields else "high"
    fields_desc = ", ".join(breach_fields or at_risk_fields)
    verb = "breaching" if breach_fields else "at risk of breaching"
    title = f"SLA {verb}: {project_name} — {fields_desc} ({month.strftime('%B %Y')})"
    message = (
        f"Tenant {project_name!r} is {verb} SLA commitments for {fields_desc} "
        f"in {month.strftime('%B %Y')}. "
        + ("Immediate attention required." if breach_fields else
           "Proactive action recommended before month-end.")
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO operational_insights
                    (type, severity, entity_type, entity_id, entity_name,
                     title, message, metadata, status, detected_at, last_seen_at)
                VALUES
                    ('sla_risk', %s, 'tenant', %s, %s, %s, %s,
                     %s::jsonb, 'open', NOW(), NOW())
                ON CONFLICT (type, entity_type, entity_id)
                    WHERE status IN ('open','acknowledged','snoozed')
                DO UPDATE SET
                    severity     = EXCLUDED.severity,
                    title        = EXCLUDED.title,
                    message      = EXCLUDED.message,
                    metadata     = EXCLUDED.metadata,
                    last_seen_at = NOW()
            """, (
                severity, project_id, project_name, title, message,
                psycopg2.extras.Json({
                    "breach_fields":   breach_fields,
                    "at_risk_fields":  at_risk_fields,
                    "month":           month.isoformat(),
                }),
            ))
        conn.commit()
    except Exception as exc:
        log.warning("Could not upsert sla_risk insight for %s: %s", project_id, exc)
        try:
            conn.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Core: process one tenant for one month
# ---------------------------------------------------------------------------

def _process_tenant_month(conn, project_id: str, project_name: str,
                            commitment: Dict[str, Any], today: datetime.date) -> None:
    month_start = today.replace(day=1)
    # First day of next month
    if month_start.month == 12:
        month_end = datetime.date(month_start.year + 1, 1, 1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)
    days_in_month = (month_end - month_start).days

    kpis = {
        "uptime_actual_pct": _compute_uptime_pct(conn, project_id, month_start, month_end),
        "rto_worst_hours":   _compute_rto_worst(conn, project_id, month_start, month_end),
        "rpo_worst_hours":   _compute_rpo_worst(conn, project_id, month_start, month_end),
        "mtta_avg_hours":    _compute_mtta(conn, project_id, month_start, month_end),
        "mttr_avg_hours":    _compute_mttr(conn, project_id, month_start, month_end),
        "backup_success_pct": _compute_backup_success_pct(conn, project_id, month_start, month_end),
    }

    breach_fields, at_risk_fields = _detect_breaches(
        kpis, commitment, days_in_month, today, month_start
    )

    # Write/update monthly rollup
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sla_compliance_monthly
                    (tenant_id, month, region_id,
                     uptime_actual_pct, rto_worst_hours, rpo_worst_hours,
                     mtta_avg_hours, mttr_avg_hours, backup_success_pct,
                     breach_fields, at_risk_fields, computed_at)
                VALUES
                    (%s, %s, '',
                     %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, month, region_id)
                DO UPDATE SET
                    uptime_actual_pct = EXCLUDED.uptime_actual_pct,
                    rto_worst_hours   = EXCLUDED.rto_worst_hours,
                    rpo_worst_hours   = EXCLUDED.rpo_worst_hours,
                    mtta_avg_hours    = EXCLUDED.mtta_avg_hours,
                    mttr_avg_hours    = EXCLUDED.mttr_avg_hours,
                    backup_success_pct= EXCLUDED.backup_success_pct,
                    breach_fields     = EXCLUDED.breach_fields,
                    at_risk_fields    = EXCLUDED.at_risk_fields,
                    computed_at       = NOW()
            """, (
                project_id, month_start,
                kpis["uptime_actual_pct"],
                kpis["rto_worst_hours"],
                kpis["rpo_worst_hours"],
                kpis["mtta_avg_hours"],
                kpis["mttr_avg_hours"],
                kpis["backup_success_pct"],
                breach_fields,
                at_risk_fields,
            ))
        conn.commit()
    except Exception as exc:
        log.warning("Could not write sla_compliance_monthly for %s: %s", project_id, exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return

    _upsert_sla_insight(conn, project_id, project_name,
                         breach_fields, at_risk_fields, month_start)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_once(conn) -> None:
    today = datetime.date.today()
    # Load all tenants that have an active SLA commitment
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT sc.tenant_id,
                   p.name AS project_name,
                   sc.tier,
                   sc.uptime_pct,
                   sc.rto_hours,
                   sc.rpo_hours,
                   sc.mtta_hours,
                   sc.mttr_hours,
                   sc.backup_freq_hours
            FROM sla_commitments sc
            JOIN projects p ON p.id = sc.tenant_id
            WHERE sc.effective_to IS NULL
        """)
        rows = cur.fetchall()

    log.info("Processing SLA compliance for %d tenant(s)", len(rows))
    for row in rows:
        project_id   = row["tenant_id"]
        project_name = row["project_name"] or project_id
        commitment   = dict(row)
        try:
            _process_tenant_month(conn, project_id, project_name, commitment, today)
        except Exception as exc:
            log.warning("Error processing tenant %s: %s", project_id, exc)


def main():
    log.info("SLA Compliance Worker starting (poll interval: %ds)", POLL_INTERVAL)
    # Wait for DB to be ready on cold start
    time.sleep(10)

    while not _shutdown:
        conn = None
        t0 = time.time()
        had_error = False
        try:
            conn = get_conn()
            run_once(conn)
            # Liveness probe
            with open("/tmp/alive", "w") as fh:
                fh.write(str(time.time()))
        except Exception as exc:
            had_error = True
            log.error("SLA worker cycle failed: %s", exc)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        duration = time.time() - t0
        _report_worker_metrics(duration, had_error, POLL_INTERVAL)
        log.info("Cycle complete in %.1fs — sleeping %ds", duration, POLL_INTERVAL)

        # Sleep in small chunks so SIGTERM is handled promptly
        slept = 0
        while not _shutdown and slept < POLL_INTERVAL:
            time.sleep(min(5, POLL_INTERVAL - slept))
            slept += 5

    log.info("SLA worker stopped")


if __name__ == "__main__":
    main()
