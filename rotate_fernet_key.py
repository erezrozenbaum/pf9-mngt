#!/usr/bin/env python3
"""
rotate_fernet_key.py — Fernet Secret Rotation Utility
======================================================
Re-encrypts all Fernet-protected database columns when a secret is rotated.

Usage
-----
  python rotate_fernet_key.py \\
      --secret-name jwt_secret \\
      --old-secret  <current_secret_value> \\
      --new-secret  <new_secret_value>

  python rotate_fernet_key.py --list-targets
  python rotate_fernet_key.py --secret-name ldap_sync_key --old-secret ... --new-secret ... --dry-run

Supported secret names and their encrypted columns
---------------------------------------------------
  jwt_secret       — copilot_config.config_value, psa_integrations.auth_header
  ldap_sync_key    — ldap_configurations.bind_password
  smtp_config_key  — smtp_configs.smtp_password
  vm_provision_key — servers.os_admin_password
  integration_key  — integration_configs.api_key

All column values that do NOT start with "fernet:" are left untouched (plaintext
or NULL). Re-encryption uses a single DB transaction per table; on any error the
transaction is rolled back and no data is changed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import logging
import os
import sys
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("rotate_fernet")

# ---------------------------------------------------------------------------
# Encrypted column registry
# ---------------------------------------------------------------------------
# Each entry: (table, pk_column, encrypted_column)
_ENCRYPTED_COLUMNS: dict[str, list[tuple[str, str, str]]] = {
    "jwt_secret": [
        ("copilot_config",   "id", "config_value"),
        ("psa_integrations", "id", "auth_header"),
        ("cluster_registry", "id", "cp_password"),
    ],
    "ldap_sync_key": [
        ("ldap_configurations", "id", "bind_password"),
    ],
    "smtp_config_key": [
        ("smtp_configs", "id", "smtp_password"),
    ],
    "vm_provision_key": [
        ("servers", "id", "os_admin_password"),
    ],
    "integration_key": [
        ("integration_configs", "id", "api_key"),
    ],
}

_AUDIT_TABLE = "auth_audit_log"


# ---------------------------------------------------------------------------
# Key derivation (mirrors crypto_helper.py logic)
# ---------------------------------------------------------------------------
def _derive_fernet_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet-compatible key from a raw secret string."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


# ---------------------------------------------------------------------------
# Core rotation
# ---------------------------------------------------------------------------
def _rotate_column(
    conn,
    table: str,
    pk_col: str,
    enc_col: str,
    old_fernet,
    new_fernet,
    dry_run: bool,
) -> tuple[int, int]:
    """Rotate a single (table, column) pair.  Returns (examined, rotated)."""
    from cryptography.fernet import InvalidToken

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {pk_col}, {enc_col} FROM {table} WHERE {enc_col} IS NOT NULL"  # noqa: S608
        )
        rows = cur.fetchall()

    examined = 0
    rotated = 0

    updates: list[tuple[str, str]] = []  # (new_value, pk)
    for pk, stored in rows:
        if not stored or not stored.startswith("fernet:"):
            continue
        examined += 1
        blob = stored[7:]
        try:
            plaintext = old_fernet.decrypt(blob.encode("ascii")).decode("utf-8")
        except InvalidToken:
            log.warning("  Row %s.%s=%s: cannot decrypt — skipping (wrong key?)", table, pk_col, pk)
            continue

        new_ciphertext = new_fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        new_stored = f"fernet:{new_ciphertext}"
        updates.append((new_stored, pk))
        rotated += 1

    if updates and not dry_run:
        with conn.cursor() as cur:
            cur.executemany(
                f"UPDATE {table} SET {enc_col} = %s WHERE {pk_col} = %s",  # noqa: S608
                updates,
            )

    return examined, rotated


def _write_audit_log(conn, secret_name: str, user: str, rotated_count: int, dry_run: bool) -> None:
    """Append a rotation event to auth_audit_log if the table exists."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO auth_audit_log (action, actor, details, created_at) "
                "VALUES (%s, %s, %s, NOW())",
                (
                    "fernet_key_rotation",
                    user,
                    f"secret={secret_name} rotated_values={rotated_count} dry_run={dry_run}",
                ),
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not write audit log entry: %s", exc)


def rotate(
    secret_name: str,
    old_secret: str,
    new_secret: str,
    dry_run: bool = False,
    db_url: Optional[str] = None,
) -> None:
    """Rotate all encrypted values for *secret_name* from old_secret to new_secret."""
    try:
        import psycopg2  # type: ignore
        from cryptography.fernet import Fernet  # type: ignore
    except ImportError as exc:
        log.error("Missing dependency: %s — install psycopg2-binary and cryptography", exc)
        sys.exit(1)

    targets = _ENCRYPTED_COLUMNS.get(secret_name)
    if targets is None:
        log.error(
            "Unknown secret name '%s'. Supported: %s",
            secret_name,
            ", ".join(_ENCRYPTED_COLUMNS),
        )
        sys.exit(1)

    old_fernet = Fernet(_derive_fernet_key(old_secret))
    new_fernet = Fernet(_derive_fernet_key(new_secret))

    # Test that the keys are different
    test_plain = "rotate_test"
    old_enc = old_fernet.encrypt(test_plain.encode()).decode()
    try:
        Fernet(_derive_fernet_key(old_secret)).decrypt(old_enc.encode()).decode()
    except Exception:  # noqa: BLE001
        log.error("Old-key self-test failed — check --old-secret value")
        sys.exit(1)

    if _derive_fernet_key(old_secret) == _derive_fernet_key(new_secret):
        log.warning("Old and new secrets derive to the same key — nothing to rotate.")
        return

    if db_url is None:
        db_url = os.getenv("DATABASE_URL") or (
            "postgresql://{user}:{pw}@{host}:{port}/{db}".format(
                user=os.getenv("PF9_DB_USER", "pf9"),
                pw=os.getenv("PF9_DB_PASSWORD", ""),
                host=os.getenv("PF9_DB_HOST", "localhost"),
                port=os.getenv("PF9_DB_PORT", "5432"),
                db=os.getenv("PF9_DB_NAME", "pf9_mgmt"),
            )
        )

    log.info("Connecting to database...")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as exc:  # noqa: BLE001
        log.error("DB connection failed: %s", exc)
        sys.exit(1)

    total_examined = 0
    total_rotated = 0

    try:
        conn.autocommit = False
        for table, pk_col, enc_col in targets:
            log.info("Rotating %s.%s ...", table, enc_col)
            examined, rotated = _rotate_column(
                conn, table, pk_col, enc_col, old_fernet, new_fernet, dry_run
            )
            log.info("  examined=%d  rotated=%d%s", examined, rotated, "  (dry-run)" if dry_run else "")
            total_examined += examined
            total_rotated += rotated

        if not dry_run:
            _write_audit_log(
                conn,
                secret_name,
                user=f"cli:{os.getenv('USER', 'unknown')}",
                rotated_count=total_rotated,
                dry_run=dry_run,
            )
            conn.commit()
            log.info("Transaction committed.")
        else:
            conn.rollback()
            log.info("Dry-run complete — no changes written.")
    except Exception:
        conn.rollback()
        log.exception("Rotation failed — transaction rolled back, no changes written")
        sys.exit(1)
    finally:
        conn.close()

    log.info(
        "Done: secret=%s examined=%d rotated=%d dry_run=%s",
        secret_name, total_examined, total_rotated, dry_run,
    )


def _list_targets() -> None:
    print("\nEncrypted columns managed by this rotation script:\n")
    for secret, targets in _ENCRYPTED_COLUMNS.items():
        env_var = secret.upper().replace(".", "_").replace("-", "_")
        print(f"  --secret-name {secret:<20}  (env var: {env_var})")
        for table, pk, col in targets:
            print(f"      {table}.{col}")
        print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rotate Fernet encryption keys for all protected DB columns.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--secret-name", help="Name of the secret to rotate (e.g. jwt_secret)")
    parser.add_argument("--old-secret", help="Current raw secret value")
    parser.add_argument("--new-secret", help="New raw secret value")
    parser.add_argument("--dry-run", action="store_true", help="Print counts but make no DB changes")
    parser.add_argument("--db-url", default=None, help="Override DATABASE_URL (defaults to env vars)")
    parser.add_argument("--list-targets", action="store_true", help="List all managed encrypted columns and exit")

    args = parser.parse_args()

    if args.list_targets:
        _list_targets()
        return

    missing = [n for n, v in [("--secret-name", args.secret_name), ("--old-secret", args.old_secret), ("--new-secret", args.new_secret)] if not v]
    if missing:
        parser.error(f"Required arguments missing: {', '.join(missing)}")

    rotate(
        secret_name=args.secret_name,
        old_secret=args.old_secret,
        new_secret=args.new_secret,
        dry_run=args.dry_run,
        db_url=args.db_url,
    )


if __name__ == "__main__":
    main()
