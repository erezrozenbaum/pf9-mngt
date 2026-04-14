"""
db_pool.py — PostgreSQL connection pool for the tenant portal service.

Connects as `tenant_portal_role` (minimal-privilege DB user).
Every connection obtained via get_tenant_connection() will be in
autocommit=False mode; callers are responsible for commit/rollback.

The tenant portal MUST call:
    cur.execute(
        "SET LOCAL app.tenant_project_ids = %s; "
        "SET LOCAL app.tenant_region_ids   = %s;",
        (project_ids_csv, region_ids_csv),
    )
at the start of every transaction so RLS policies evaluate correctly.
"""

import os
import logging
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool

from secret_helper import read_secret

logger = logging.getLogger("tenant_portal.db_pool")

_pool: pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()

POOL_MIN_CONN = int(os.getenv("DB_POOL_MIN_CONN", "1"))
POOL_MAX_CONN = int(os.getenv("DB_POOL_MAX_CONN", "5"))


def _db_params() -> dict:
    return dict(
        host=os.getenv("PF9_DB_HOST", "db"),
        port=int(os.getenv("PF9_DB_PORT", "5432")),
        dbname=os.getenv("PF9_DB_NAME", "pf9_mgmt"),
        user=os.getenv("TENANT_DB_USER", "tenant_portal_role"),
        password=read_secret("tenant_portal_db_password", env_var="TENANT_DB_PASSWORD"),
        connect_timeout=10,
        options="-c search_path=public",
    )


def init_pool(minconn: int = None, maxconn: int = None):
    global _pool
    if minconn is None:
        minconn = POOL_MIN_CONN
    if maxconn is None:
        maxconn = POOL_MAX_CONN

    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pool.ThreadedConnectionPool(minconn, maxconn, **_db_params())
                logger.info("Tenant portal DB pool initialised (min=%d max=%d)", minconn, maxconn)


@contextmanager
def get_tenant_connection():
    """
    Yield a psycopg2 connection from the tenant_portal_role pool.

    The caller MUST set app.tenant_project_ids and app.tenant_region_ids
    using SET LOCAL at the start of the transaction before any data query.
    On success the transaction is committed; on exception it is rolled back
    and the exception re-raised.
    """
    init_pool()
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
