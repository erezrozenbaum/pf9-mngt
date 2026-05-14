#!/usr/bin/env python3
"""
migrate_copilot_keys.py — one-shot utility to Fernet-encrypt any plaintext
LLM API keys currently stored in the copilot_config table.

Run this script ONCE after deploying the encryption-aware version of the API
to back-fill existing rows.  Safe to run multiple times (already-encrypted
values are left unchanged).

Usage (from repo root, with the same env vars as the API):
    python3 migrate_copilot_keys.py [--dry-run]

Environment variables required (same as the API container):
    PF9_DB_HOST, PF9_DB_PORT, PF9_DB_NAME, PF9_DB_USER, PF9_DB_PASSWORD
    JWT_SECRET_KEY   (used as Fernet key derivation source)
"""
from __future__ import annotations

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# Minimal inline key derivation (mirrors crypto_helper._derive_key)
# ---------------------------------------------------------------------------
import base64
import hashlib


def _derive_fernet_key() -> bytes:
    raw = os.environ.get("JWT_SECRET_KEY", "")
    if not raw:
        sys.exit("ERROR: JWT_SECRET_KEY environment variable is not set.")
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())


def _encrypt(plaintext: str) -> str:
    from cryptography.fernet import Fernet
    ct = Fernet(_derive_fernet_key()).encrypt(plaintext.encode()).decode("ascii")
    return f"fernet:{ct}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Encrypt Copilot API keys in DB")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing to DB")
    args = parser.parse_args()

    import psycopg2
    conn = psycopg2.connect(
        host=os.environ["PF9_DB_HOST"],
        port=int(os.environ.get("PF9_DB_PORT", 5432)),
        dbname=os.environ["PF9_DB_NAME"],
        user=os.environ["PF9_DB_USER"],
        password=os.environ["PF9_DB_PASSWORD"],
    )
    cur = conn.cursor()

    cur.execute("SELECT id, openai_api_key, anthropic_api_key FROM copilot_config WHERE id = 1")
    row = cur.fetchone()
    if not row:
        print("No copilot_config row found — nothing to migrate.")
        conn.close()
        return

    _, openai_key, anthropic_key = row
    updates: dict[str, str] = {}

    for col, val in [("openai_api_key", openai_key), ("anthropic_api_key", anthropic_key)]:
        if val and not val.startswith("fernet:"):
            encrypted = _encrypt(val)
            print(f"{'[DRY RUN] ' if args.dry_run else ''}Encrypting {col}: "
                  f"{val[:4]}...{val[-4:]} → {encrypted[:20]}...")
            updates[col] = encrypted
        elif val and val.startswith("fernet:"):
            print(f"{col}: already encrypted — skipping.")
        else:
            print(f"{col}: empty — skipping.")

    if not updates:
        print("Nothing to encrypt.")
        conn.close()
        return

    if not args.dry_run:
        set_clauses = ", ".join(f"{k} = %s" for k in updates)
        cur.execute(
            f"UPDATE copilot_config SET {set_clauses} WHERE id = 1",
            list(updates.values()),
        )
        conn.commit()
        print(f"Done. {len(updates)} key(s) encrypted.")
    else:
        print(f"[DRY RUN] Would encrypt {len(updates)} key(s). No changes made.")

    conn.close()


if __name__ == "__main__":
    main()
