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

# LDAP configuration for backup
LDAP_HOST = os.getenv("LDAP_HOST", "pf9_ldap")
LDAP_PORT = os.getenv("LDAP_PORT", "389")
LDAP_BASE_DN = os.getenv("LDAP_BASE_DN", "dc=pf9mgmt,dc=local")
LDAP_ADMIN_DN = os.getenv("LDAP_ADMIN_DN", f"cn=admin,{os.getenv('LDAP_BASE_DN', 'dc=pf9mgmt,dc=local')}")
LDAP_ADMIN_PASSWORD = os.getenv("LDAP_ADMIN_PASSWORD", "")

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


def _fetch_pending_ldap_jobs(conn):
    """Return list of pending LDAP backup/restore jobs."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM backup_history WHERE status = 'pending' AND backup_target = 'ldap' ORDER BY created_at"
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


def _update_config_last_backup(conn, target="database"):
    if target == "ldap":
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backup_config SET last_ldap_backup_at = now(), updated_at = now()"
            )
    else:
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
        _update_config_last_backup(conn, "database")
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

def _enforce_retention(conn, target="database"):
    """Delete old backup files according to retention policy."""
    cfg = _fetch_config(conn)
    if not cfg:
        return

    if target == "ldap":
        retention_count = cfg.get("ldap_retention_count", 7)
        retention_days = cfg.get("ldap_retention_days", 30)
    else:
        retention_count = cfg["retention_count"]
        retention_days = cfg["retention_days"]

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Completed backups ordered newest-first, filtered by target
        cur.execute(
            "SELECT id, file_path, created_at FROM backup_history "
            "WHERE status = 'completed' AND backup_target = %s ORDER BY created_at DESC",
            (target,),
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
                log.info("Retention (%s): removed %s", target, fpath)
            except OSError as e:
                log.warning("Retention (%s): could not remove %s: %s", target, fpath, e)
        # Mark row
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backup_history SET status = 'deleted' WHERE id = %s",
                (row["id"],),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# LDAP backup / restore
# ---------------------------------------------------------------------------

def _run_ldap_backup(conn, job_id: int, backup_type: str = "manual", initiated_by: str = "system"):
    """Export all LDAP entries via ldapsearch and save as compressed LDIF."""
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    ldap_dir = os.path.join(NFS_BACKUP_PATH, "ldap")
    os.makedirs(ldap_dir, exist_ok=True)
    filename = f"pf9_ldap_{stamp}.ldif.gz"
    filepath = os.path.join(ldap_dir, filename)

    log.info("Starting LDAP backup job %s  →  %s", job_id, filepath)
    _update_job(conn, job_id, status="running", started_at=datetime.datetime.utcnow())

    start = time.time()
    try:
        # ldapsearch exports all entries under base DN
        ldap_uri = f"ldap://{LDAP_HOST}:{LDAP_PORT}"
        search_cmd = [
            "ldapsearch", "-x",
            "-H", ldap_uri,
            "-D", LDAP_ADMIN_DN,
            "-w", LDAP_ADMIN_PASSWORD,
            "-b", LDAP_BASE_DN,
            "-LLL",                   # plain LDIF, no comments
        ]

        with open(filepath, "wb") as outf:
            search = subprocess.Popen(search_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            gzip_proc = subprocess.Popen(["gzip"], stdin=search.stdout, stdout=outf, stderr=subprocess.PIPE)
            search.stdout.close()
            _, gzip_err = gzip_proc.communicate(timeout=600)
            search.wait(timeout=10)

        if search.returncode != 0:
            stderr_out = search.stderr.read().decode("utf-8", "replace")[:500] if search.stderr else ""
            raise RuntimeError(f"ldapsearch rc={search.returncode}: {stderr_out}")
        if gzip_proc.returncode != 0:
            raise RuntimeError(f"gzip rc={gzip_proc.returncode}")

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
        _update_config_last_backup(conn, "ldap")
        log.info("LDAP backup job %s completed – %s bytes in %.1f s", job_id, size, duration)
        return True

    except Exception as exc:
        duration = time.time() - start
        log.error("LDAP backup job %s failed: %s", job_id, exc)
        _update_job(
            conn, job_id,
            status="failed",
            error_message=str(exc)[:2000],
            duration_seconds=round(duration, 2),
            completed_at=datetime.datetime.utcnow(),
        )
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except OSError:
            pass
        return False


def _run_ldap_restore(conn, job_id: int, source_path: str):
    """Restore LDAP entries from a compressed LDIF backup."""
    log.info("Starting LDAP restore job %s from %s", job_id, source_path)

    if not os.path.isfile(source_path):
        _update_job(conn, job_id, status="failed", error_message="Source LDIF file not found",
                     completed_at=datetime.datetime.utcnow())
        return False

    _update_job(conn, job_id, status="running", started_at=datetime.datetime.utcnow())

    start = time.time()
    try:
        ldap_uri = f"ldap://{LDAP_HOST}:{LDAP_PORT}"

        # Step 1: gunzip the LDIF
        gunzip = subprocess.Popen(["gunzip", "-c", source_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Step 2: ldapadd (use -c to continue on errors for entries that already exist)
        ldapadd = subprocess.Popen(
            [
                "ldapadd", "-x", "-c",
                "-H", ldap_uri,
                "-D", LDAP_ADMIN_DN,
                "-w", LDAP_ADMIN_PASSWORD,
            ],
            stdin=gunzip.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        gunzip.stdout.close()
        add_out, add_err = ldapadd.communicate(timeout=600)
        gunzip.wait(timeout=10)

        duration = time.time() - start

        # ldapadd with -c may return non-zero if some entries already exist;
        # that's acceptable.  Only truly fatal errors (connection refused etc.) matter.
        if ldapadd.returncode != 0:
            err_text = add_err.decode("utf-8", "replace")[:1000]
            # If every single entry failed it's a real error
            if "Can't contact LDAP server" in err_text or "Invalid credentials" in err_text:
                raise RuntimeError(f"ldapadd rc={ldapadd.returncode}: {err_text}")
            log.warning("LDAP restore had partial errors (expected for existing entries): %s", err_text[:300])

        _update_job(
            conn, job_id,
            status="completed",
            duration_seconds=round(duration, 2),
            completed_at=datetime.datetime.utcnow(),
        )
        log.info("LDAP restore job %s completed in %.1f s", job_id, duration)
        return True

    except Exception as exc:
        duration = time.time() - start
        log.error("LDAP restore job %s failed: %s", job_id, exc)
        _update_job(
            conn, job_id,
            status="failed",
            error_message=str(exc)[:2000],
            duration_seconds=round(duration, 2),
            completed_at=datetime.datetime.utcnow(),
        )
        return False


# ---------------------------------------------------------------------------
# Scheduler helpers
# ---------------------------------------------------------------------------

def _should_run_scheduled(cfg, target="database"):
    """Return True if a scheduled backup should fire now (checked each POLL_INTERVAL)."""
    if not cfg:
        return False

    if target == "ldap":
        if not cfg.get("ldap_backup_enabled"):
            return False
        # LDAP follows the same schedule type/time as DB when enabled
    else:
        if not cfg["enabled"]:
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
    last_key = "last_ldap_backup_at" if target == "ldap" else "last_backup_at"
    last = cfg.get(last_key)
    if last:
        last_naive = last.replace(tzinfo=None) if last.tzinfo else last
        if last_naive.date() == now.date():
            return False

    return True


def _create_scheduled_job(conn, target="database"):
    """Insert a pending job row for the scheduler."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO backup_history (status, backup_type, backup_target, initiated_by) "
            "VALUES ('pending', 'scheduled', %s, 'scheduler') RETURNING id",
            (target,),
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

            # 1. Process any pending DATABASE manual / restore jobs
            pending = _fetch_pending_jobs(conn)
            for job in pending:
                target = job.get("backup_target", "database")
                jtype = job.get("backup_type", "manual")
                if target == "ldap":
                    # Handled separately below
                    continue
                if jtype == "restore":
                    _run_restore(conn, job["id"], job.get("file_path", ""))
                else:
                    _run_backup(conn, job["id"], jtype, job.get("initiated_by", "manual"))
                _enforce_retention(conn, "database")

            # 2. Process any pending LDAP backup / restore jobs
            pending_ldap = _fetch_pending_ldap_jobs(conn)
            for job in pending_ldap:
                jtype = job.get("backup_type", "manual")
                if jtype == "restore":
                    _run_ldap_restore(conn, job["id"], job.get("file_path", ""))
                else:
                    _run_ldap_backup(conn, job["id"], jtype, job.get("initiated_by", "manual"))
                _enforce_retention(conn, "ldap")

            # 3. Check scheduled backups
            cfg = _fetch_config(conn)

            # Database scheduled backup
            if _should_run_scheduled(cfg, "database"):
                job_id = _create_scheduled_job(conn, "database")
                _run_backup(conn, job_id, "scheduled", "scheduler")
                _enforce_retention(conn, "database")

            # LDAP scheduled backup
            if _should_run_scheduled(cfg, "ldap"):
                job_id = _create_scheduled_job(conn, "ldap")
                _run_ldap_backup(conn, job_id, "scheduled", "scheduler")
                _enforce_retention(conn, "ldap")

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
