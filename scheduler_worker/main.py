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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

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

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [scheduler-worker] %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("scheduler-worker")

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
# Metrics collection loop
# ---------------------------------------------------------------------------
async def metrics_loop() -> None:
    """Collect host / VM metrics from PF9 nodes on a fixed cadence."""
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
    os.makedirs(os.path.dirname(METRICS_CACHE_PATH), exist_ok=True)

    collector = HostMetricsCollector()
    # Override the paths that __init__ set relative to the working directory
    collector.cache_file = METRICS_CACHE_PATH
    collector._cpu_state_file = os.path.join(
        os.path.dirname(METRICS_CACHE_PATH), "cpu_state.json"
    )

    consecutive_errors = 0
    while _running:
        try:
            await collector.run_once()
            consecutive_errors = 0
        except Exception as exc:
            consecutive_errors += 1
            log.error("Metrics collection error (run %d): %s", consecutive_errors, exc)
            if consecutive_errors >= 5:
                log.warning(
                    "5 consecutive failures – backing off 5 minutes before retrying."
                )
                await asyncio.sleep(300)
                consecutive_errors = 0
                continue

        # Sleep in 1-second ticks so SIGTERM is handled promptly
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


def _run_rvtools_sync() -> None:
    """Run pf9_rvtools.py as an isolated subprocess so global state is clean each time."""
    script = os.path.join(os.path.dirname(__file__), "pf9_rvtools.py")

    # Per-run log file: /app/logs/rvtools_YYYYMMDD_HHMMSS.log
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    log_path = os.path.join(log_dir, f"rvtools_{ts}.log")

    log.info("RVTools: writing run log to %s", log_path)
    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write(f"# RVTools run started at {datetime.now(timezone.utc).isoformat()}\n")
        lf.write(f"# Script: {script}\n\n")
        result = subprocess.run(
            [sys.executable, script],
            timeout=7200,  # 2-hour hard limit
            stdout=lf,
            stderr=subprocess.STDOUT,
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

    Two modes (RVTOOLS_INTERVAL_MINUTES takes priority over RVTOOLS_SCHEDULE_TIME):
      Interval mode  – RVTOOLS_INTERVAL_MINUTES > 0  → run every N minutes.
      Schedule mode  – RVTOOLS_INTERVAL_MINUTES = 0  → run once daily at RVTOOLS_SCHEDULE_TIME (HH:MM UTC).
    """
    loop = asyncio.get_event_loop()

    if RVTOOLS_RUN_ON_START:
        log.info("RVTools: RVTOOLS_RUN_ON_START=true – running immediately …")
        try:
            await loop.run_in_executor(executor, _run_rvtools_sync)
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
            await loop.run_in_executor(executor, _run_rvtools_sync)
            log.info("RVTools: inventory run completed.")
        except Exception as exc:
            log.error("RVTools: inventory run failed: %s", exc)

        # In schedule mode: brief pause so we don't re-trigger in the same minute.
        # In interval mode: the per-second sleep above already provides the gap.
        if RVTOOLS_INTERVAL_MINUTES == 0:
            await asyncio.sleep(70)

    log.info("RVTools loop stopped.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def async_main() -> None:
    global _shutdown_event
    _shutdown_event = asyncio.Event()

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
        executor.shutdown(wait=False)
        log.info("PF9 Scheduler Worker stopped.")


if __name__ == "__main__":
    asyncio.run(async_main())
