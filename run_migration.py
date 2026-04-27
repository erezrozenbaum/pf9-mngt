"""Database schema migration runner.

Applies each db/migrate_*.sql file exactly once, tracked in the
schema_migrations table.  Already-applied files are skipped, making every
deploy fully idempotent.

Uses psql (subprocess) to execute SQL files — handles dollar-quoting,
PL/pgSQL blocks, and any SQL syntax that plain Python string-splitting cannot.

Compatible with:
  - Docker Compose  (docker exec pf9_api python run_migration.py)
  - Kubernetes      (db-migrate Job using the API image)

Pre-migration backup
--------------------
When PRE_MIGRATION_BACKUP=true (default: false) and there are pending
migrations, a pg_dump snapshot is written to the directory defined by
PF9_BACKUP_PATH (default: /mnt/backups) before any migration runs.  The
filename is ``pre_migration_<timestamp>.sql.gz``.  A backup failure emits a
warning and allows migrations to proceed — it never blocks deployment.
"""
import glob
import os
import subprocess
import sys
from datetime import datetime, timezone

import psycopg2

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Pre-migration backup ──────────────────────────────────────────────────────

def _pre_migration_backup() -> None:
    """Take a pg_dump snapshot before applying pending migrations.

    Gated by PRE_MIGRATION_BACKUP=true.  Failure warns and continues.
    """
    if os.getenv("PRE_MIGRATION_BACKUP", "false").lower() != "true":
        return

    backup_dir = os.getenv("PF9_BACKUP_PATH", "/mnt/backups")
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filepath = os.path.join(backup_dir, f"pre_migration_{ts}.sql.gz")

    env = os.environ.copy()
    env["PGPASSWORD"] = os.environ["PF9_DB_PASSWORD"]

    try:
        pg_dump = subprocess.Popen(
            [
                "pg_dump",
                "-h", os.environ["PF9_DB_HOST"],
                "-p", os.environ.get("PF9_DB_PORT", "5432"),
                "-U", os.environ["PF9_DB_USER"],
                "-d", os.environ["PF9_DB_NAME"],
                "--no-password",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        gzip_proc = subprocess.Popen(
            ["gzip", "-c"],
            stdin=pg_dump.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        pg_dump.stdout.close()
        gz_out, gz_err = gzip_proc.communicate(timeout=300)
        pg_dump.wait(timeout=10)

        if pg_dump.returncode != 0 or gzip_proc.returncode != 0:
            print(f"WARNING: pre-migration backup failed (pg_dump rc={pg_dump.returncode})")
            return

        with open(filepath, "wb") as fh:
            fh.write(gz_out)
        os.chmod(filepath, 0o600)
        print(f"Pre-migration backup written: {filepath}")
    except Exception as exc:
        print(f"WARNING: pre-migration backup skipped: {exc}")




def _connect():
    return psycopg2.connect(
        host=os.environ["PF9_DB_HOST"],
        port=int(os.environ.get("PF9_DB_PORT", 5432)),
        dbname=os.environ["PF9_DB_NAME"],
        user=os.environ["PF9_DB_USER"],
        password=os.environ["PF9_DB_PASSWORD"],
    )


def _ensure_tracking(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   TEXT        PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    conn.commit()


def _is_applied(conn, filename):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM schema_migrations WHERE filename = %s", (filename,)
        )
        return cur.fetchone() is not None


def _mark_applied(conn, filename):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING",
            (filename,),
        )
    conn.commit()


# ── psql runner ───────────────────────────────────────────────────────────────

def _run_psql(filepath):
    """Execute a SQL file via psql subprocess.

    psql handles dollar-quoting, PL/pgSQL blocks, and every SQL construct
    correctly — something Python string-splitting cannot do.  We do NOT set
    ON_ERROR_STOP so that IF NOT EXISTS guards silently skip already-present
    objects without aborting the file.

    Returns (returncode, stdout, stderr).
    """
    env = os.environ.copy()
    env["PGPASSWORD"] = os.environ["PF9_DB_PASSWORD"]
    result = subprocess.run(
        [
            "psql",
            "-h", os.environ["PF9_DB_HOST"],
            "-p", os.environ.get("PF9_DB_PORT", "5432"),
            "-U", os.environ["PF9_DB_USER"],
            "-d", os.environ["PF9_DB_NAME"],
            "-f", filepath,
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    conn = _connect()
    _ensure_tracking(conn)

    files = sorted(glob.glob(os.path.join(BASE_DIR, "db", "migrate_*.sql")))
    if not files:
        print("No migration files found — nothing to do.")
        conn.close()
        sys.exit(0)

    pending = [f for f in files if not _is_applied(conn, os.path.basename(f))]
    if pending:
        _pre_migration_backup()

    total = applied = skipped = failed = 0
    for filepath in files:
        name = os.path.basename(filepath)
        total += 1

        if _is_applied(conn, name):
            print(f"SKIP  {name}  (already applied)")
            skipped += 1
            continue

        print(f"APPLY {name} ...")
        returncode, stdout, stderr = _run_psql(filepath)

        for line in stderr.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(x in line for x in ("already exists", "duplicate", "skipping")):
                print(f"      note: {line}")
            else:
                print(f"      WARN: {line}")

        if returncode != 0:
            print(f"      FAIL  psql exited {returncode}")
            failed += 1
        else:
            _mark_applied(conn, name)
            print(f"      OK")
            applied += 1

    conn.close()
    print(
        f"\nDone — total: {total}  applied: {applied}"
        f"  skipped: {skipped}  failed: {failed}"
    )
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
