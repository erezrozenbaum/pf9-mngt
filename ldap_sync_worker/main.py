"""
ldap_sync_worker/main.py — External LDAP / AD Identity Federation Sync Engine

Runs as a long-lived container.  Responsibilities:
  1. On startup: run all enabled LDAP sync configs once immediately.
  2. Enter a polling loop; re-run each config when its sync_interval_minutes has elapsed,
     or when last_sync_at is NULL (manual trigger from the API).
  3. For each config run:
     a. Acquire a pg_try_advisory_lock(config_id) — skip if already locked.
     b. Fetch users from the external LDAP.
     c. Create/update users in the internal OpenLDAP.
     d. Deactivate users that are no longer in the external directory.
     e. Invalidate active sessions for deactivated users.
     f. Write a row to ldap_sync_log.
  4. After 3 consecutive failures for a config, write a system notification.

Security notes:
  - Bind passwords are decrypted via Fernet(SHA-256(ldap_sync_key secret)).
  - SSRF: RFC-1918 / loopback ranges are rejected unless allow_private_network=TRUE.
  - user_search_filter is stored pre-validated by the API; we escape user-supplied
    attribute values with ldap.filter.escape_filter_chars before any search.
  - superadmin role can never be granted by external group mappings (CHECK constraint).
"""

import base64
import hashlib
import ipaddress
import json
import logging
import os
import signal
import socket
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import ldap
import ldap.filter
import ldap.modlist
import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Configuration from environment / Docker secrets
# ---------------------------------------------------------------------------

def _read_secret(name: str, env_var: str, default: str = "") -> str:
    """Priority: /run/secrets/<name> → env var → default."""
    path = f"/run/secrets/{name}"
    if os.path.isfile(path):
        try:
            with open(path, "r") as fh:
                val = fh.read().strip()
            if val:
                return val
        except OSError:
            pass
    return os.getenv(env_var, default)


DB_HOST   = os.getenv("PF9_DB_HOST", "db")
DB_PORT   = int(os.getenv("PF9_DB_PORT", "5432"))
DB_NAME   = os.getenv("PF9_DB_NAME", "pf9_mgmt")
DB_USER   = os.getenv("PF9_DB_USER", "pf9")
# Secret file takes priority; fall back to explicit env vars matching the other workers
DB_PASS   = _read_secret("db_password", "PF9_DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD", "")

INT_LDAP_SERVER = os.getenv("LDAP_SERVER", "ldap")
INT_LDAP_PORT   = int(os.getenv("LDAP_PORT", "389"))
INT_LDAP_BASE_DN = os.getenv("LDAP_BASE_DN", "dc=pf9mgmt,dc=local")
INT_LDAP_USER_DN = os.getenv("LDAP_USER_DN", "ou=users,dc=pf9mgmt,dc=local")
INT_LDAP_ADMIN_PASS = _read_secret("ldap_admin_password", "LDAP_ADMIN_PASSWORD")

LDAP_SYNC_KEY = _read_secret("ldap_sync_key", "LDAP_SYNC_KEY")

# How often to check for configs that need a sync (inner loop interval in seconds)
POLL_INTERVAL = int(os.getenv("LDAP_SYNC_POLL_INTERVAL", "30"))
# Number of consecutive failures before a notification is sent
FAILURE_THRESHOLD = 3

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ldap-sync-worker] %(levelname)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ldap-sync")

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_running = True


def _handle_signal(signum, _frame):
    global _running
    log.info("Received signal %s — shutting down ...", signum)
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Fernet decryption (duplicated here to keep worker self-contained; no shared
# volume mount with the API container is required)
# ---------------------------------------------------------------------------

def _fernet_decrypt(stored: str) -> str:
    """Decrypt a 'fernet:<ciphertext>' value using the ldap_sync_key secret."""
    if not LDAP_SYNC_KEY:
        log.error("ldap_sync_key secret is not set — cannot decrypt bind passwords")
        return ""
    if not stored.startswith("fernet:"):
        log.error("Stored value is missing 'fernet:' prefix")
        return ""
    try:
        from cryptography.fernet import Fernet, InvalidToken
        key = base64.urlsafe_b64encode(hashlib.sha256(LDAP_SYNC_KEY.encode()).digest())
        return Fernet(key).decrypt(stored[7:].encode()).decode()
    except Exception as exc:
        log.error("Fernet decryption failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------
_BLOCKED_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _host_allowed(host: str, allow_private_network: bool) -> bool:
    if allow_private_network:
        return True
    try:
        addr = ipaddress.ip_address(socket.getaddrinfo(host, None)[0][4][0])
        return not any(addr in r for r in _BLOCKED_RANGES)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_db() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASS,
        connect_timeout=10,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _fetch_enabled_configs(conn) -> List[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, host, port, bind_dn, bind_password_enc,
                   base_dn, user_search_filter,
                   user_attr_uid, user_attr_mail, user_attr_fullname,
                   use_tls, use_starttls, verify_tls_cert, ca_cert_pem,
                   mfa_delegated, allow_private_network,
                   sync_interval_minutes, last_sync_at
            FROM ldap_sync_config
            WHERE is_enabled = TRUE
            ORDER BY id
            """
        )
        return [dict(r) for r in cur.fetchall()]


def _needs_sync(cfg: dict) -> bool:
    """Return True if this config is due for a sync."""
    if cfg["last_sync_at"] is None:
        return True  # never synced or manually reset (manual trigger)
    elapsed_seconds = (datetime.now(timezone.utc) - cfg["last_sync_at"]).total_seconds()
    return elapsed_seconds >= cfg["sync_interval_minutes"] * 60


def _fetch_group_mappings(conn, config_id: int) -> Dict[str, str]:
    """Return {external_group_dn: pf9_role} for this config."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT external_group_dn, pf9_role FROM ldap_sync_group_mappings "
            "WHERE config_id = %s",
            (config_id,),
        )
        return {r["external_group_dn"]: r["pf9_role"] for r in cur.fetchall()}


def _invalidate_sessions(conn, username: str) -> None:
    """Mark all active sessions for *username* as expired."""
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE user_sessions SET expires_at = %s "
            "WHERE username = %s AND expires_at > %s",
            (now, username, now),
        )


# ---------------------------------------------------------------------------
# Internal LDAP helpers
# ---------------------------------------------------------------------------

def _internal_ldap_conn() -> ldap.ldapobject.LDAPObject:
    uri = f"ldap://{INT_LDAP_SERVER}:{INT_LDAP_PORT}"
    conn = ldap.initialize(uri)
    conn.protocol_version = ldap.VERSION3
    conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
    conn.set_option(ldap.OPT_REFERRALS, 0)
    admin_dn = f"cn=admin,{INT_LDAP_BASE_DN}"
    conn.simple_bind_s(admin_dn, INT_LDAP_ADMIN_PASS)
    return conn


def _user_exists_internal(conn_int: ldap.ldapobject.LDAPObject, uid: str) -> bool:
    safe = ldap.filter.escape_filter_chars(uid)
    results = conn_int.search_s(
        INT_LDAP_USER_DN, ldap.SCOPE_SUBTREE, f"(uid={safe})", ["dn"],
    )
    return bool(results)


def _add_user_internal(conn_int: ldap.ldapobject.LDAPObject,
                       uid: str, mail: str, cn: str) -> None:
    """Add a skeleton LDAP entry — no userPassword attribute (passthrough auth)."""
    dn = f"uid={ldap.dn.escape_dn_chars(uid)},{INT_LDAP_USER_DN}"
    attrs = {
        "objectClass": [b"top", b"person", b"inetOrgPerson"],
        "uid": [uid.encode()],
        "cn": [(cn or uid).encode()],
        "sn": [(uid).encode()],
    }
    if mail:
        attrs["mail"] = [mail.encode()]
    conn_int.add_s(dn, ldap.modlist.addModlist(attrs))


def _update_user_internal(conn_int: ldap.ldapobject.LDAPObject,
                           uid: str, mail: str, cn: str) -> None:
    """Update mail and cn on an existing internal LDAP user entry."""
    safe = ldap.filter.escape_filter_chars(uid)
    results = conn_int.search_s(
        INT_LDAP_USER_DN, ldap.SCOPE_SUBTREE, f"(uid={safe})", ["cn", "mail"],
    )
    if not results:
        return
    dn, old_attrs = results[0]
    new_attrs = dict(old_attrs)
    if cn:
        new_attrs["cn"] = [cn.encode()]
    if mail:
        new_attrs["mail"] = [mail.encode()]
    mods = ldap.modlist.modifyModlist(old_attrs, new_attrs)
    if mods:
        conn_int.modify_s(dn, mods)


# ---------------------------------------------------------------------------
# External LDAP helpers
# ---------------------------------------------------------------------------

def _open_external_conn(cfg: dict) -> ldap.ldapobject.LDAPObject:
    scheme = "ldaps" if cfg.get("use_tls") and not cfg.get("use_starttls") else "ldap"
    uri = f"{scheme}://{cfg['host']}:{cfg['port']}"
    conn = ldap.initialize(uri)
    conn.protocol_version = ldap.VERSION3
    conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
    conn.set_option(ldap.OPT_REFERRALS, 0)
    if not cfg.get("verify_tls_cert", True):
        conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
        conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    if cfg.get("use_starttls"):
        conn.start_tls_s()
    return conn


def _attr(attrs: dict, key: str) -> str:
    vals = attrs.get(key, [])
    if vals:
        v = vals[0]
        return v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)
    return ""


def _determine_role(attrs: dict, group_mappings: Dict[str, str]) -> Optional[str]:
    """Map external group memberships to a pf9 role.  Returns the highest role found."""
    if not group_mappings:
        return None
    priority = {"viewer": 1, "operator": 2, "admin": 3}
    member_of_raw = attrs.get("memberOf", [])
    member_of = [
        g.decode("utf-8", errors="replace") if isinstance(g, bytes) else g
        for g in member_of_raw
    ]
    best_role = None
    best_priority = 0
    for group_dn in member_of:
        role = group_mappings.get(group_dn)
        if role and priority.get(role, 0) > best_priority:
            best_role = role
            best_priority = priority[role]
    return best_role


# ---------------------------------------------------------------------------
# Core sync algorithm
# ---------------------------------------------------------------------------

def _run_sync(db_conn, config_id: int) -> None:
    """Run a full sync for a single config.  Uses pg_try_advisory_lock to prevent
    concurrent runs (e.g. scheduled + manual trigger arriving simultaneously)."""

    # Acquire advisory lock — skip if another process is already syncing this config
    with db_conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (config_id,))
        acquired = cur.fetchone()["pg_try_advisory_lock"]
    if not acquired:
        log.info("[config=%d] Advisory lock held by another process — skipping", config_id)
        return

    started_at = datetime.now(timezone.utc)
    log_id = None
    try:
        _run_sync_inner(db_conn, config_id, started_at)
    finally:
        with db_conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (config_id,))
        db_conn.commit()


def _run_sync_inner(db_conn, config_id: int, started_at: datetime) -> None:
    # Insert a running log row
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT name, host, port, bind_dn, bind_password_enc, base_dn, "
            "       user_search_filter, user_attr_uid, user_attr_mail, user_attr_fullname, "
            "       use_tls, use_starttls, verify_tls_cert, ca_cert_pem, "
            "       allow_private_network "
            "FROM ldap_sync_config WHERE id = %s",
            (config_id,),
        )
        cfg = dict(cur.fetchone())

    config_name = cfg["name"]
    log.info("[config=%d] Starting sync for '%s'", config_id, config_name)

    # Insert log row for this run
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ldap_sync_log (config_id, config_name, started_at) "
            "VALUES (%s, %s, %s) RETURNING id",
            (config_id, config_name, started_at),
        )
        log_id = cur.fetchone()["id"]
    db_conn.commit()

    status = "failed"
    error_msg = None
    users_found = users_created = users_updated = users_deactivated = 0
    details: List[dict] = []

    try:
        if not _host_allowed(cfg["host"], cfg.get("allow_private_network", False)):
            raise ValueError(
                f"Host {cfg['host']} is in a private/loopback range. "
                "Set allow_private_network=TRUE to permit."
            )

        svc_password = _fernet_decrypt(cfg["bind_password_enc"])
        if not svc_password:
            raise RuntimeError("Cannot decrypt external LDAP bind password")

        group_mappings = _fetch_group_mappings(db_conn, config_id)

        # Open external LDAP connection
        ext_conn = _open_external_conn(cfg)
        ext_conn.simple_bind_s(cfg["bind_dn"], svc_password)

        search_attrs = [
            cfg["user_attr_uid"], cfg["user_attr_mail"], cfg["user_attr_fullname"],
            "memberOf",
        ]
        results = ext_conn.search_s(
            cfg["base_dn"], ldap.SCOPE_SUBTREE, cfg["user_search_filter"], search_attrs,
        )
        ext_conn.unbind_s()

        users_found = len(results)
        log.info("[config=%d] Found %d users in external directory", config_id, users_found)

        # Open internal LDAP connection
        int_conn = _internal_ldap_conn()

        seen_uids = set()
        for dn, attrs in results:
            uid  = _attr(attrs, cfg["user_attr_uid"])
            mail = _attr(attrs, cfg["user_attr_mail"])
            cn   = _attr(attrs, cfg["user_attr_fullname"])
            if not uid:
                continue
            seen_uids.add(uid)

            role = _determine_role(attrs, group_mappings)

            entry_result = {"uid": uid, "action": None, "error": None}
            try:
                if _user_exists_internal(int_conn, uid):
                    _update_user_internal(int_conn, uid, mail, cn)
                    entry_result["action"] = "updated"
                    # Only update DB role if not locally overridden
                    if role:
                        with db_conn.cursor() as cur:
                            cur.execute(
                                "UPDATE user_roles SET role = %s, last_modified = NOW() "
                                "WHERE username = %s AND sync_config_id = %s "
                                "AND locally_overridden = FALSE",
                                (role, uid, config_id),
                            )
                    users_updated += 1
                else:
                    _add_user_internal(int_conn, uid, mail, cn)
                    effective_role = role or "viewer"
                    with db_conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO user_roles
                                (username, role, sync_source, sync_config_id,
                                 locally_overridden, granted_by, is_active)
                            VALUES (%s, %s, 'external_ldap', %s, FALSE, 'ldap_sync', TRUE)
                            ON CONFLICT (username) DO UPDATE SET
                                role = EXCLUDED.role,
                                sync_source = 'external_ldap',
                                sync_config_id = EXCLUDED.sync_config_id,
                                is_active = TRUE
                            """,
                            (uid, effective_role, config_id),
                        )
                    entry_result["action"] = "created"
                    users_created += 1
            except Exception as exc:
                entry_result["error"] = str(exc)
                log.warning("[config=%d] Error processing user '%s': %s", config_id, uid, exc)

            details.append(entry_result)

        int_conn.unbind_s()

        # Deactivate users previously synced from this config who are no longer returned
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT username FROM user_roles "
                "WHERE sync_config_id = %s AND is_active = TRUE",
                (config_id,),
            )
            active_synced = [r["username"] for r in cur.fetchall()]

        for uid in active_synced:
            if uid not in seen_uids:
                with db_conn.cursor() as cur:
                    cur.execute(
                        "UPDATE user_roles SET is_active = FALSE WHERE username = %s "
                        "AND sync_config_id = %s",
                        (uid, config_id),
                    )
                _invalidate_sessions(db_conn, uid)
                users_deactivated += 1
                details.append({"uid": uid, "action": "deactivated", "error": None})
                log.info("[config=%d] Deactivated user '%s' (no longer in external directory)", config_id, uid)

        any_errors = any(d["error"] for d in details)
        status = "partial" if any_errors else "success"

    except Exception as exc:
        error_msg = str(exc)
        log.error("[config=%d] Sync failed: %s", config_id, exc)

    finished_at = datetime.now(timezone.utc)

    # Update log row
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE ldap_sync_log SET finished_at=%s, status=%s, users_found=%s, "
            "users_created=%s, users_updated=%s, users_deactivated=%s, "
            "error_message=%s, details=%s WHERE id=%s",
            (finished_at, status, users_found, users_created, users_updated,
             users_deactivated, error_msg,
             psycopg2.extras.Json(details) if details else None,
             log_id),
        )
        cur.execute(
            "UPDATE ldap_sync_config SET last_sync_at=%s, last_sync_status=%s, "
            "last_sync_users_found=%s WHERE id=%s",
            (finished_at, status, users_found, config_id),
        )
    db_conn.commit()

    # Consecutive failure notification
    if status == "failed":
        _check_consecutive_failures(db_conn, config_id, config_name)
    else:
        log.info(
            "[config=%d] Sync complete: %s — created=%d updated=%d deactivated=%d",
            config_id, status, users_created, users_updated, users_deactivated,
        )


def _check_consecutive_failures(conn, config_id: int, config_name: str) -> None:
    """Send a system notification if the last FAILURE_THRESHOLD runs all failed."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM ldap_sync_log WHERE config_id = %s "
            "ORDER BY started_at DESC LIMIT %s",
            (config_id, FAILURE_THRESHOLD),
        )
        rows = cur.fetchall()
    if len(rows) < FAILURE_THRESHOLD:
        return
    if all(r["status"] == "failed" for r in rows):
        log.warning(
            "[config=%d] '%s' has failed %d times in a row — sending notification",
            config_id, config_name, FAILURE_THRESHOLD,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO notifications (type, title, message, severity, created_at)
                    VALUES ('ldap_sync_failure', %s, %s, 'critical', NOW())
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        f"LDAP Sync Failing: {config_name}",
                        f"LDAP sync config '{config_name}' (id={config_id}) has failed "
                        f"{FAILURE_THRESHOLD} times consecutively. Check the sync logs.",
                    ),
                )
            conn.commit()
        except Exception as exc:
            log.error("Could not insert failure notification: %s", exc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("LDAP Sync Worker starting")
    log.info("DB: %s@%s:%d/%s  |  Internal LDAP: %s:%d",
             DB_USER, DB_HOST, DB_PORT, DB_NAME, INT_LDAP_SERVER, INT_LDAP_PORT)

    if not LDAP_SYNC_KEY:
        log.error("ldap_sync_key secret is not set. Worker cannot decrypt bind passwords.")
        sys.exit(1)

    # ── Startup: run all enabled configs once immediately ──────────────────
    log.info("Running initial sync for all enabled configs ...")
    try:
        conn = _get_db()
        configs = _fetch_enabled_configs(conn)
        for cfg in configs:
            try:
                _run_sync(conn, cfg["id"])
            except Exception as exc:
                log.error("[config=%d] Startup sync error: %s", cfg["id"], exc)
        conn.close()
    except Exception as exc:
        log.error("Could not complete startup sync: %s", exc)

    log.info("Entering sync loop (poll interval: %d s)", POLL_INTERVAL)

    # ── Schedule loop ──────────────────────────────────────────────────────
    while _running:
        try:
            conn = _get_db()
            configs = _fetch_enabled_configs(conn)
            for cfg in configs:
                if not _running:
                    break
                if _needs_sync(cfg):
                    log.info("[config=%d] '%s' is due for sync", cfg["id"], cfg["name"])
                    try:
                        _run_sync(conn, cfg["id"])
                    except Exception as exc:
                        log.error("[config=%d] Sync error: %s", cfg["id"], exc)
            conn.close()
        except Exception as exc:
            log.error("Sync loop iteration error: %s", exc)

        # Sleep in small increments so SIGTERM is handled promptly
        for _ in range(POLL_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    log.info("LDAP Sync Worker stopped")


if __name__ == "__main__":
    main()
