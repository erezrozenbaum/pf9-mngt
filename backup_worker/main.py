"""
PF9 Database Backup Worker
==========================
Runs as a long-lived container.  Responsibilities:
  1.  Poll backup_config every 60 s to pick up schedule changes.
  2.  Execute pg_dump at the configured time (daily / weekly) or when a
      manual job row is inserted by the API (status = 'pending').
  3.  Write compressed SQL dumps to the NFS-mounted backup directory.
  4.  Enforce retention (by count and by age) after each successful backup.
  5.  Execute pg_restore when a restore job is requested.
"""

import datetime
import glob
import logging
import os
import signal
import subprocess
import sys
import time

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
BACKUP_ENABLED = os.getenv("BACKUP_ENABLED", "true").lower() in ("true", "1", "yes")
DB_HOST = os.getenv("DB_HOST", "pf9_db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "pf9_mgmt")
DB_USER = os.getenv("DB_USER", "pf9")
DB_PASS = os.getenv("DB_PASS", "pf9pass")
NFS_BACKUP_PATH = os.getenv("NFS_BACKUP_PATH", "/backups")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "3600"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [backup-worker] %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("backup-worker")

# Graceful shutdown
_running = True


def _handle_signal(signum, _frame):
    global _running
    log.info("Received signal %s – shutting down …", signum)
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )


def _fetch_config(conn):
    """Return the single-row backup_config as a dict, or None."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM backup_config ORDER BY id LIMIT 1")
        return cur.fetchone()


def _fetch_pending_jobs(conn):
    """Return list of pending manual/restore jobs."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM backup_history WHERE status = 'pending' ORDER BY created_at"
        )
        return cur.fetchall()


def _update_job(conn, job_id, **fields):
    parts = []
    vals = []
    for k, v in fields.items():
        parts.append(f"{k} = %s")
        vals.append(v)
    vals.append(job_id)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE backup_history SET {', '.join(parts)} WHERE id = %s",
            vals,
        )
    conn.commit()


def _update_config_last_backup(conn):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE backup_config SET last_backup_at = now(), updated_at = now()"
        )
    conn.commit()

# ---------------------------------------------------------------------------
# pg_dump / pg_restore wrappers
# ---------------------------------------------------------------------------

def _run_backup(conn, job_id: int, backup_type: str = "manual", initiated_by: str = "system"):
    """Execute pg_dump and record result in backup_history."""
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"pf9_mgmt_{stamp}.sql.gz"
    filepath = os.path.join(NFS_BACKUP_PATH, filename)

    log.info("Starting backup job %s  →  %s", job_id, filepath)

    _update_job(conn, job_id, status="running", started_at=datetime.datetime.utcnow())

    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASS

    start = time.time()
    try:
        # pg_dump piped through gzip
        dump_cmd = [
            "pg_dump",
            "-h", DB_HOST,
            "-p", DB_PORT,
            "-U", DB_USER,
            "-d", DB_NAME,
            "--no-owner",
            "--no-privileges",
        ]
        with open(filepath, "wb") as outf:
            dump = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            gzip = subprocess.Popen(["gzip"], stdin=dump.stdout, stdout=outf, stderr=subprocess.PIPE)
            dump.stdout.close()
            _, gzip_err = gzip.communicate(timeout=3600)
            dump.wait(timeout=10)

        if dump.returncode != 0 or gzip.returncode != 0:
            raise RuntimeError(
                f"pg_dump rc={dump.returncode}, gzip rc={gzip.returncode}"
            )

        duration = time.time() - start
        size = os.path.getsize(filepath)

        _update_job(
            conn, job_id,
            status="completed",
            file_name=filename,
            file_path=filepath,
            file_size_bytes=size,
            duration_seconds=round(duration, 2),
            completed_at=datetime.datetime.utcnow(),
        )
        _update_config_last_backup(conn)
        log.info("Backup job %s completed – %s bytes in %.1f s", job_id, size, duration)
        return True

    except Exception as exc:
        duration = time.time() - start
        log.error("Backup job %s failed: %s", job_id, exc)
        _update_job(
            conn, job_id,
            status="failed",
            error_message=str(exc)[:2000],
            duration_seconds=round(duration, 2),
            completed_at=datetime.datetime.utcnow(),
        )
        # Cleanup partial file
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except OSError:
            pass
        return False


def _run_restore(conn, job_id: int, source_path: str):
    """Restore a backup into the database."""
    log.info("Starting restore job %s from %s", job_id, source_path)

    if not os.path.isfile(source_path):
        _update_job(conn, job_id, status="failed", error_message="Source file not found",
                     completed_at=datetime.datetime.utcnow())
        return False

    _update_job(conn, job_id, status="running", started_at=datetime.datetime.utcnow())

    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASS

    start = time.time()
    try:
        # gunzip | psql
        gunzip = subprocess.Popen(["gunzip", "-c", source_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        psql = subprocess.Popen(
            ["psql", "-h", DB_HOST, "-p", DB_PORT, "-U", DB_USER, "-d", DB_NAME, "-v", "ON_ERROR_STOP=0"],
            stdin=gunzip.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        gunzip.stdout.close()
        psql_out, psql_err = psql.communicate(timeout=7200)
        gunzip.wait(timeout=10)

        duration = time.time() - start

        if psql.returncode != 0:
            raise RuntimeError(f"psql rc={psql.returncode}: {psql_err.decode('utf-8', 'replace')[:500]}")

        _update_job(
            conn, job_id,
            status="completed",
            duration_seconds=round(duration, 2),
            completed_at=datetime.datetime.utcnow(),
        )
        log.info("Restore job %s completed in %.1f s", job_id, duration)
        return True

    except Exception as exc:
        duration = time.time() - start
        log.error("Restore job %s failed: %s", job_id, exc)
        _update_job(
            conn, job_id,
            status="failed",
            error_message=str(exc)[:2000],
            duration_seconds=round(duration, 2),
            completed_at=datetime.datetime.utcnow(),
        )
        return False


# ---------------------------------------------------------------------------
# Retention enforcement
# ---------------------------------------------------------------------------

def _enforce_retention(conn):
    """Delete old backup files according to retention policy."""
    cfg = _fetch_config(conn)
    if not cfg:
        return

    retention_count = cfg["retention_count"]
    retention_days = cfg["retention_days"]
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Completed backups ordered newest-first
        cur.execute(
            "SELECT id, file_path, created_at FROM backup_history "
            "WHERE status = 'completed' ORDER BY created_at DESC"
        )
        rows = cur.fetchall()

    to_delete = []
    for idx, row in enumerate(rows):
        if idx >= retention_count or row["created_at"].replace(tzinfo=None) < cutoff:
            to_delete.append(row)

    for row in to_delete:
        fpath = row.get("file_path")
        if fpath and os.path.isfile(fpath):
            try:
                os.remove(fpath)
                log.info("Retention: removed %s", fpath)
            except OSError as e:
                log.warning("Retention: could not remove %s: %s", fpath, e)
        # Mark row
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backup_history SET status = 'deleted' WHERE id = %s",
                (row["id"],),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Scheduler helpers
# ---------------------------------------------------------------------------

def _should_run_scheduled(cfg):
    """Return True if a scheduled backup should fire now (checked each POLL_INTERVAL)."""
    if not cfg or not cfg["enabled"]:
        return False
    stype = cfg["schedule_type"]
    if stype == "manual":
        return False

    now = datetime.datetime.utcnow()
    hh, mm = (cfg.get("schedule_time_utc") or "02:00").split(":")
    target_hour, target_min = int(hh), int(mm)

    if now.hour != target_hour:
        return False
    if abs(now.minute - target_min) > (POLL_INTERVAL // 60 + 1):
        return False

    if stype == "weekly" and now.weekday() != cfg.get("schedule_day_of_week", 0):
        return False

    # Avoid duplicating: skip if a backup already completed/running today
    last = cfg.get("last_backup_at")
    if last:
        last_naive = last.replace(tzinfo=None) if last.tzinfo else last
        if last_naive.date() == now.date():
            return False

    return True


def _create_scheduled_job(conn):
    """Insert a pending job row for the scheduler."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO backup_history (status, backup_type, initiated_by) "
            "VALUES ('pending', 'scheduled', 'scheduler') RETURNING id"
        )
        job_id = cur.fetchone()[0]
    conn.commit()
    return job_id


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    if not BACKUP_ENABLED:
        log.info("Backup worker is DISABLED (BACKUP_ENABLED=false). Sleeping indefinitely.")
        while _running:
            time.sleep(60)
        return

    log.info("Backup worker starting  (poll every %d s, NFS → %s)", POLL_INTERVAL, NFS_BACKUP_PATH)

    # Ensure backup directory exists
    os.makedirs(NFS_BACKUP_PATH, exist_ok=True)

    while _running:
        conn = None
        try:
            conn = _get_conn()

            # 1. Process any pending manual / restore jobs
            pending = _fetch_pending_jobs(conn)
            for job in pending:
                jtype = job.get("backup_type", "manual")
                if jtype == "restore":
                    _run_restore(conn, job["id"], job.get("file_path", ""))
                else:
                    _run_backup(conn, job["id"], jtype, job.get("initiated_by", "manual"))
                _enforce_retention(conn)

            # 2. Check scheduled backup
            cfg = _fetch_config(conn)
            if _should_run_scheduled(cfg):
                job_id = _create_scheduled_job(conn)
                _run_backup(conn, job_id, "scheduled", "scheduler")
                _enforce_retention(conn)

        except Exception as exc:
            log.error("Worker loop error: %s", exc)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        # Sleep in small increments so SIGTERM is responsive
        for _ in range(POLL_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    log.info("Backup worker stopped.")


if __name__ == "__main__":
    main()
