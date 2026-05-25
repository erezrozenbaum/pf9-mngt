"""
Centralized Database Connection Pool for PF9 Management API

Provides a thread-safe PostgreSQL connection pool using psycopg2.
All modules should use `get_connection()` context manager instead of
creating individual connections.

Usage:
    from db_pool import get_connection

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT ...")
            rows = cur.fetchall()
        # conn auto-commits on success, auto-rollbacks on exception
        # conn is returned to pool automatically
"""

import os
import logging
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool

from secret_helper import read_secret

logger = logging.getLogger("pf9.db_pool")

# ---------------------------------------------------------------------------
# Pool singleton with double-check locking
# ---------------------------------------------------------------------------
_pool = None
_pool_lock = threading.Lock()

# Pool sizing (per worker process)
POOL_MIN_CONN = int(os.getenv("DB_POOL_MIN_CONN", "2"))
POOL_MAX_CONN = int(os.getenv("DB_POOL_MAX_CONN", "10"))


def _db_params() -> dict:
    """Return database connection parameters from environment / Docker secrets."""
    return dict(
        host=os.getenv("PF9_DB_HOST", "db"),
        port=int(os.getenv("PF9_DB_PORT", "5432")),
        dbname=os.getenv("PF9_DB_NAME", "pf9_mgmt"),
        user=os.getenv("PF9_DB_USER", "pf9"),
        password=read_secret("db_password", env_var="PF9_DB_PASSWORD"),
        connect_timeout=10,
    )


def init_pool(minconn: int = None, maxconn: int = None):
    """
    Initialize the connection pool.  Called lazily on first `get_connection()`.
    Safe to call multiple times (idempotent via double-check lock).
    """
    global _pool
    if minconn is None:
        minconn = POOL_MIN_CONN
    if maxconn is None:
        maxconn = POOL_MAX_CONN

    params = _db_params()
    _pool = pool.ThreadedConnectionPool(minconn, maxconn, **params)
    logger.info(
        "Database connection pool initialized  min=%d  max=%d  host=%s  db=%s",
        minconn, maxconn, params["host"], params["dbname"],
    )


def get_pool() -> pool.ThreadedConnectionPool:
    """Return the pool singleton, creating it on first call."""
    global _pool  # noqa: F824
    if _pool is None:
        with _pool_lock:
            if _pool is None:          # double-check after acquiring lock
                init_pool()
    return _pool


@contextmanager
def get_connection():
    """
    Borrow a connection from the pool.

    * On normal exit  → ``COMMIT`` + return to pool
    * On exception    → ``ROLLBACK`` + return to pool + re-raise

    Usage::

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        p.putconn(conn)


def close_pool():
    """Shut down the pool (call on application exit)."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed")


# ---------------------------------------------------------------------------
# Read replica pool  (feature-flagged: ENABLE_MULTI_REGION=true)
# ---------------------------------------------------------------------------
# Set DB_READ_REPLICA_URL to a DSN like:
#   postgresql://user:pass@replica-host:5432/pf9_mgmt
#
# When enabled, read-heavy queries can use get_read_connection() which
# routes to the replica transparently, falling back to primary on error.

_ENABLE_MULTI_REGION: bool = os.getenv("ENABLE_MULTI_REGION", "false").lower() in ("1", "true", "yes")
_DB_READ_REPLICA_URL: str = os.getenv("DB_READ_REPLICA_URL", "")

_read_pool: pool.ThreadedConnectionPool | None = None
_read_pool_lock = threading.Lock()


def _init_read_pool() -> None:
    """Lazily create the read replica pool (no-op if feature-flag is off)."""
    global _read_pool
    if not _ENABLE_MULTI_REGION or not _DB_READ_REPLICA_URL:
        return
    if _read_pool is not None:
        return
    with _read_pool_lock:
        if _read_pool is not None:
            return
        try:
            import urllib.parse
            parsed = urllib.parse.urlparse(_DB_READ_REPLICA_URL)
            params = dict(
                host=parsed.hostname,
                port=parsed.port or 5432,
                dbname=(parsed.path or "/pf9_mgmt").lstrip("/"),
                user=parsed.username,
                password=parsed.password,
                connect_timeout=10,
            )
            _read_pool = pool.ThreadedConnectionPool(POOL_MIN_CONN, POOL_MAX_CONN, **params)
            logger.info(
                "Read replica pool initialised  min=%d  max=%d  host=%s",
                POOL_MIN_CONN, POOL_MAX_CONN, parsed.hostname,
            )
        except Exception as exc:
            logger.warning(
                "Read replica pool init failed: %s — read queries will use primary", exc
            )


@contextmanager
def get_read_connection():
    """
    Return a DB connection optimised for read-heavy queries.

    Routing behaviour
    -----------------
    * ``ENABLE_MULTI_REGION=true`` **and** ``DB_READ_REPLICA_URL`` set:
      uses the read replica pool.
    * Otherwise: falls back to the primary pool transparently.

    The yielded connection is auto-committed on clean exit and rolled back
    on exception, just like ``get_connection()``.

    Usage::

        from db_pool import get_read_connection

        with get_read_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT ...")
    """
    # Attempt to use replica if configured
    if _ENABLE_MULTI_REGION and _DB_READ_REPLICA_URL:
        if _read_pool is None:
            _init_read_pool()
        if _read_pool is not None:
            conn = _read_pool.getconn()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                _read_pool.putconn(conn)
            return

    # Fallback: use primary pool
    with get_connection() as conn:
        yield conn
