#!/usr/bin/env python3
"""
snapshot_service_user.py

Manages the dedicated snapshot service user for cross-tenant snapshot operations.

The service user (configured via SNAPSHOT_SERVICE_USER_EMAIL) is used to create snapshots in
each tenant's project scope, rather than in the service domain.

Flow:
  1. Admin session checks if the service user exists in Keystone
  2. For each target project, ensures the user has admin role
  3. Authenticates as the service user scoped to the target project
  4. Uses that project-scoped session for snapshot create/list/delete

Environment variables:
  SNAPSHOT_SERVICE_USER_EMAIL    - Service user email (required, no default)
  SNAPSHOT_SERVICE_USER_PASSWORD - Plaintext password (preferred for simplicity)
  SNAPSHOT_PASSWORD_KEY          - Fernet key for encrypted password
  SNAPSHOT_USER_PASSWORD_ENCRYPTED - Encrypted password
  SNAPSHOT_SERVICE_USER_DOMAIN   - User domain ID (default: "default")
  SNAPSHOT_SERVICE_USER_DISABLED - Set to "true" to disable (default: false)
"""

from __future__ import annotations

import os
import secrets
import string
from typing import Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SERVICE_USER_EMAIL = os.getenv("SNAPSHOT_SERVICE_USER_EMAIL", "")
SERVICE_USER_DOMAIN = os.getenv("SNAPSHOT_SERVICE_USER_DOMAIN", "default")
SERVICE_USER_DISABLED = os.getenv("SNAPSHOT_SERVICE_USER_DISABLED", "false").lower() in ("true", "1", "yes")

# Cache: project_id -> True (role already verified this run)
_role_cache: dict[str, bool] = {}

# Cache: user_id once found
_cached_user_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------

def get_service_user_password() -> str:
    """
    Retrieve the service user password from environment.

    Tries in order:
      1. SNAPSHOT_SERVICE_USER_PASSWORD (plaintext)
      2. SNAPSHOT_USER_PASSWORD_ENCRYPTED + SNAPSHOT_PASSWORD_KEY (Fernet)

    Raises RuntimeError if no password is available.
    """
    # 1. Plain password
    plain = os.getenv("SNAPSHOT_SERVICE_USER_PASSWORD")
    if plain:
        return plain

    # 2. Encrypted password
    encrypted = os.getenv("SNAPSHOT_USER_PASSWORD_ENCRYPTED")
    key = os.getenv("SNAPSHOT_PASSWORD_KEY")

    if encrypted and key:
        try:
            from cryptography.fernet import Fernet
            f = Fernet(key.encode() if isinstance(key, str) else key)
            return f.decrypt(encrypted.encode() if isinstance(encrypted, str) else encrypted).decode()
        except ImportError:
            # cryptography not installed, try base64 decode as fallback
            print("[SERVICE_USER] cryptography package not installed; cannot decrypt password")
        except Exception as e:
            print(f"[SERVICE_USER] Failed to decrypt password: {e}")

    raise RuntimeError(
        "No snapshot service user password found. "
        "Set SNAPSHOT_SERVICE_USER_PASSWORD or both "
        "SNAPSHOT_PASSWORD_KEY and SNAPSHOT_USER_PASSWORD_ENCRYPTED in .env"
    )


# ---------------------------------------------------------------------------
# Keystone helpers
# ---------------------------------------------------------------------------

def _keystone_get(session: requests.Session, url: str, timeout: int = 60):
    """GET from Keystone, return JSON dict."""
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _find_user_id(session: requests.Session, keystone_url: str, email: str) -> Optional[str]:
    """Find the Keystone user ID for the given email/name."""
    global _cached_user_id
    if _cached_user_id:
        return _cached_user_id

    url = f"{keystone_url}/users?name={email}"
    try:
        data = _keystone_get(session, url)
        users = data.get("users", [])
        if users:
            _cached_user_id = users[0]["id"]
            return _cached_user_id
    except Exception as e:
        print(f"[SERVICE_USER] Failed to search for user {email}: {e}")

    # Also try searching by domain_id
    try:
        url = f"{keystone_url}/users?domain_id={SERVICE_USER_DOMAIN}&name={email}"
        data = _keystone_get(session, url)
        users = data.get("users", [])
        if users:
            _cached_user_id = users[0]["id"]
            return _cached_user_id
    except Exception:
        pass

    return None


def _find_role_id(session: requests.Session, keystone_url: str, role_name: str) -> Optional[str]:
    """Find a Keystone role ID by name."""
    url = f"{keystone_url}/roles?name={role_name}"
    try:
        data = _keystone_get(session, url)
        roles = data.get("roles", [])
        if roles:
            return roles[0]["id"]
    except Exception as e:
        print(f"[SERVICE_USER] Failed to find role '{role_name}': {e}")
    return None


def _has_role_on_project(
    session: requests.Session,
    keystone_url: str,
    user_id: str,
    project_id: str,
    role_id: str,
) -> bool:
    """Check if a user already has a specific role on a project."""
    url = f"{keystone_url}/projects/{project_id}/users/{user_id}/roles/{role_id}"
    try:
        resp = session.head(url, timeout=30)
        # 204 = role exists, 404 = not assigned
        return resp.status_code == 204
    except Exception:
        return False


def _assign_role_to_project(
    session: requests.Session,
    keystone_url: str,
    user_id: str,
    project_id: str,
    role_id: str,
) -> bool:
    """Assign a role to a user on a project. Returns True on success."""
    url = f"{keystone_url}/projects/{project_id}/users/{user_id}/roles/{role_id}"
    try:
        resp = session.put(url, timeout=30)
        if resp.status_code in (200, 201, 204):
            return True
        else:
            print(f"[SERVICE_USER] Role assignment returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"[SERVICE_USER] Failed to assign role: {e}")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_service_user(
    admin_session: requests.Session,
    keystone_url: str,
    project_id: str,
) -> None:
    """
    Ensure the snapshot service user exists and has admin role on the
    given project.

    Args:
        admin_session: An authenticated admin session (service-scoped)
        keystone_url:  Keystone v3 URL (e.g. https://.../keystone/v3)
        project_id:    The target project to grant access to

    Raises:
        RuntimeError if the user cannot be found or the role cannot be assigned.
    """
    if SERVICE_USER_DISABLED:
        print(f"    [SERVICE_USER] Disabled via SNAPSHOT_SERVICE_USER_DISABLED")
        return

    keystone_url = keystone_url.rstrip("/")

    # Skip if we already verified this project in this process run
    if project_id in _role_cache:
        return

    # 1. Find the service user
    user_id = _find_user_id(admin_session, keystone_url, SERVICE_USER_EMAIL)
    if not user_id:
        raise RuntimeError(
            f"Service user '{SERVICE_USER_EMAIL}' not found in Keystone. "
            f"Please create the user in Platform9 first, then set its password "
            f"in SNAPSHOT_SERVICE_USER_PASSWORD or encrypt it with "
            f"SNAPSHOT_PASSWORD_KEY / SNAPSHOT_USER_PASSWORD_ENCRYPTED."
        )

    # 2. Find the admin role
    admin_role_id = _find_role_id(admin_session, keystone_url, "admin")
    if not admin_role_id:
        raise RuntimeError("'admin' role not found in Keystone")

    # 3. Check / assign role
    if _has_role_on_project(admin_session, keystone_url, user_id, project_id, admin_role_id):
        print(f"    [SERVICE_USER] {SERVICE_USER_EMAIL} already has admin role on project {project_id}")
    else:
        print(f"    [SERVICE_USER] Granting admin role to {SERVICE_USER_EMAIL} on project {project_id}")
        ok = _assign_role_to_project(admin_session, keystone_url, user_id, project_id, admin_role_id)
        if not ok:
            raise RuntimeError(
                f"Failed to assign admin role to {SERVICE_USER_EMAIL} on project {project_id}"
            )
        print(f"    [SERVICE_USER] ✓ Admin role granted")

    _role_cache[project_id] = True


def reset_cache() -> None:
    """Clear the per-run role verification cache."""
    global _cached_user_id
    _role_cache.clear()
    _cached_user_id = None


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"[TEST] Service user email: {SERVICE_USER_EMAIL}")
    print(f"[TEST] Service user domain: {SERVICE_USER_DOMAIN}")
    print(f"[TEST] Disabled: {SERVICE_USER_DISABLED}")

    try:
        pw = get_service_user_password()
        print(f"[TEST] Password retrieved (length: {len(pw)})")
    except RuntimeError as e:
        print(f"[TEST] Password not available: {e}")

    print("[TEST] Module ready for use")
