"""
PF9 Intelligence Worker
========================
Periodic worker that runs the three insight engines (capacity, waste, risk) and
writes results into the operational_insights table.

Engines
-------
  capacity  — storage growth forecasting; fires when a project is on track to
              hit 90 % quota within the next 30 days.
  waste     — idle VMs, unattached volumes, aged snapshots without retention policy.
  risk      — snapshot coverage gaps, tenant health-score decline, unacknowledged
              critical drift events.

Run cadence
-----------
Configurable via INTELLIGENCE_INTERVAL_SECONDS (default: 900 = 15 min).
"""

import logging
import os
import signal
import sys
import time

import psycopg2
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from engines.capacity import CapacityEngine
from engines.waste import WasteEngine
from engines.risk import RiskEngine

# ---------------------------------------------------------------------------
# Worker observability — Redis metrics
# ---------------------------------------------------------------------------
_REDIS_HOST  = os.getenv("REDIS_HOST", "redis")
_REDIS_PORT  = int(os.getenv("REDIS_PORT", "6379"))
_WORKER_NAME = "intelligence_worker"
_worker_runs_total   = 0
_worker_errors_total = 0


def _report_worker_metrics(duration_s: float, had_error: bool, frequency_s: int) -> None:
    global _worker_runs_total, _worker_errors_total
    _worker_runs_total += 1
    if had_error:
        _worker_errors_total += 1
    try:
        import redis as _redis
        r = _redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, socket_connect_timeout=2)
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
# Secret helper
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
POLL_INTERVAL = int(os.getenv("INTELLIGENCE_INTERVAL_SECONDS", "900"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [intelligence-worker] %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("intelligence")

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
# DB connection
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
# Main loop
# ---------------------------------------------------------------------------

ENGINES = [CapacityEngine, WasteEngine, RiskEngine]


def run_once(conn) -> None:
    for engine_cls in ENGINES:
        engine = engine_cls(conn)
        try:
            engine.run()
        except Exception as exc:
            log.warning("Engine %s failed: %s", engine_cls.__name__, exc)
            try:
                conn.rollback()
            except Exception:
                pass


def main():
    log.info("Intelligence Worker starting (poll interval: %ds)", POLL_INTERVAL)
    time.sleep(15)  # allow DB to be ready on cold start

    while not _shutdown:
        conn = None
        t0 = time.time()
        had_error = False
        try:
            conn = get_conn()
            run_once(conn)
            with open("/tmp/alive", "w") as fh:
                fh.write(str(time.time()))
        except Exception as exc:
            had_error = True
            log.error("Intelligence worker cycle failed: %s", exc)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        duration = time.time() - t0
        _report_worker_metrics(duration, had_error, POLL_INTERVAL)
        log.info("Cycle complete in %.1fs — sleeping %ds", duration, POLL_INTERVAL)

        slept = 0
        while not _shutdown and slept < POLL_INTERVAL:
            time.sleep(min(5, POLL_INTERVAL - slept))
            slept += 5

    log.info("Intelligence worker stopped")


if __name__ == "__main__":
    main()
