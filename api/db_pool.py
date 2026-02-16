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
    """Return database connection parameters from environment."""
    return dict(
        host=os.getenv("PF9_DB_HOST", "db"),
        port=int(os.getenv("PF9_DB_PORT", "5432")),
        dbname=os.getenv("PF9_DB_NAME", "pf9_mgmt"),
        user=os.getenv("PF9_DB_USER", "pf9"),
        password=os.getenv("PF9_DB_PASSWORD", ""),
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
    global _pool
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
