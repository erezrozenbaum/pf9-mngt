"""
VM Provisioning Service User
=============================

Manages the `provisionsrv` hidden Keystone service account used to create VMs
in tenant projects with a correctly-scoped token.

Why this exists
---------------
OpenStack resolves every resource lookup (Security Groups, Networks, Cinder
volumes) against the **project scope baked into the auth token**.  The main
service account (configured via `PF9_USERNAME` env var) is scoped to the `service` project, so
using its token to provision resources into `ORG1` fails with "SG not found",
"network not found", or Cinder 400 Malformed URL.

Solution (mirrors snapshots/snapshot_service_user.py)
------------------------------------------------------
`provisionsrv` is a native Keystone user (NOT in LDAP → invisible to tenant
customer UI).  At dry-run time the system idempotently grants it `_member_`
role in the target project.  At execution time it authenticates as `provisionsrv`
scoped to the target project, getting a properly-scoped token that resolves all
resource lookups correctly.

Environment variables
---------------------
  PROVISION_SERVICE_USER_EMAIL       e.g. provisionsrv@yourdomain.com
  PROVISION_SERVICE_USER_DOMAIN      Keystone domain name (default: Default)
  PROVISION_PASSWORD_KEY             Fernet key for decrypting the password
  PROVISION_USER_PASSWORD_ENCRYPTED  Fernet-encrypted password ciphertext
"""

import os
import logging
from typing import Optional

import requests
from cryptography.fernet import Fernet

log = logging.getLogger(__name__)

SERVICE_USER_EMAIL: str = os.getenv("PROVISION_SERVICE_USER_EMAIL", "")
SERVICE_USER_DOMAIN: str = os.getenv("PROVISION_SERVICE_USER_DOMAIN", "Default")

# In-process caches — reset per container restart
_cached_user_id: Optional[str] = None
_role_cache: dict = {}  # project_id → True


def reset_cache() -> None:
    """Clear all in-process caches (call after password rotation or test teardown)."""
    global _cached_user_id, _role_cache
    _cached_user_id = None
    _role_cache = {}


def get_provision_user_password() -> str:
    """Return the provisionsrv plaintext password (Fernet-decrypted from env)."""
    key = os.getenv("PROVISION_PASSWORD_KEY", "")
    enc = os.getenv("PROVISION_USER_PASSWORD_ENCRYPTED", "")
    if key and enc:
        try:
            return Fernet(key.encode()).decrypt(enc.encode()).decode()
        except Exception as exc:
            raise RuntimeError(
                f"Failed to decrypt PROVISION_USER_PASSWORD_ENCRYPTED: {exc}"
            ) from exc
    raise RuntimeError(
        "PROVISION_PASSWORD_KEY and PROVISION_USER_PASSWORD_ENCRYPTED must be set in .env"
    )


def _find_user_id(
    session: requests.Session, keystone_url: str, token: str
) -> Optional[str]:
    """Look up provisionsrv user ID in Keystone (result cached in-process)."""
    global _cached_user_id
    if _cached_user_id:
        return _cached_user_id
    r = session.get(
        f"{keystone_url}/users",
        headers={"X-Auth-Token": token},
        params={"name": SERVICE_USER_EMAIL},
    )
    r.raise_for_status()
    users = r.json().get("users", [])
    if users:
        _cached_user_id = users[0]["id"]
        log.debug("provisionsrv user_id resolved: %s", _cached_user_id)
        return _cached_user_id
    return None


def _find_role_id(
    session: requests.Session, keystone_url: str, token: str, role_name: str
) -> Optional[str]:
    """Return the Keystone UUID for a role by name."""
    r = session.get(
        f"{keystone_url}/roles",
        headers={"X-Auth-Token": token},
        params={"name": role_name},
    )
    r.raise_for_status()
    roles = r.json().get("roles", [])
    return roles[0]["id"] if roles else None


def _has_role_on_project(
    session: requests.Session,
    keystone_url: str,
    token: str,
    user_id: str,
    project_id: str,
    role_id: str,
) -> bool:
    """Return True if provisionsrv already has role_id on project_id."""
    r = session.head(
        f"{keystone_url}/projects/{project_id}/users/{user_id}/roles/{role_id}",
        headers={"X-Auth-Token": token},
    )
    return r.status_code == 204


def ensure_provisioner_in_project(admin_client, project_id: str) -> None:
    """
    Idempotently ensure provisionsrv has `_member_` (or `member`) role in
    the given project.  Uses the admin client's token + Keystone endpoint.

    Safe to call multiple times — role is only assigned once; subsequent calls
    are no-ops due to the in-process cache.

    Raises RuntimeError if the provisionsrv user cannot be found in Keystone
    (i.e. setup has not been run yet).
    """
    global _role_cache  # noqa: F824
    if project_id in _role_cache:
        return  # already verified this run

    if not SERVICE_USER_EMAIL:
        raise RuntimeError(
            "PROVISION_SERVICE_USER_EMAIL is not set in .env — "
            "run the provision user setup script first"
        )

    admin_client.authenticate()
    session = admin_client.session
    keystone_url = admin_client.keystone_endpoint
    token = admin_client.token

    user_id = _find_user_id(session, keystone_url, token)
    if not user_id:
        raise RuntimeError(
            f"VM provisioning service user '{SERVICE_USER_EMAIL}' not found in Keystone. "
            "Run setup_provision_user.py to create it first."
        )

    # Try _member_ first (Platform9 default), fall back to member (vanilla Keystone)
    for role_name in ("_member_", "member"):
        role_id = _find_role_id(session, keystone_url, token, role_name)
        if not role_id:
            continue
        if not _has_role_on_project(session, keystone_url, token, user_id, project_id, role_id):
            log.info(
                "Granting '%s' role to provisionsrv on project %s", role_name, project_id
            )
            r = session.put(
                f"{keystone_url}/projects/{project_id}/users/{user_id}/roles/{role_id}",
                headers={"X-Auth-Token": token},
            )
            r.raise_for_status()
        else:
            log.debug(
                "provisionsrv already has '%s' on project %s — skipping", role_name, project_id
            )
        _role_cache[project_id] = True
        return

    raise RuntimeError(
        "Neither '_member_' nor 'member' role found in Keystone — "
        "check Platform9 role configuration"
    )


def get_provisioner_client(
    project_id: str,
    project_name: str,
    project_domain: str,
    auth_url: str,
):
    """
    Return a fully-authenticated Pf9Client instance scoped to project_name/project_domain,
    authenticated as provisionsrv.

    The returned client has a genuine Keystone token scoped to the target project,
    so all Nova/Neutron/Cinder resource lookups resolve within that project context.
    """
    # Late import to avoid circular dependency (pf9_control imports nothing from here)
    from pf9_control import Pf9Client

    password = get_provision_user_password()

    client = Pf9Client.__new__(Pf9Client)
    client.auth_url = auth_url
    client.username = SERVICE_USER_EMAIL
    client.password = password
    client.user_domain = SERVICE_USER_DOMAIN
    client.project_name = project_name
    client.project_domain = project_domain
    client.region_name = os.getenv("PF9_REGION_NAME", "region-one")
    client.region_id = os.getenv("PF9_REGION_ID", "default")
    client.session = requests.Session()
    client.token = None
    client._token_expires_at = None
    client.project_id = project_id
    client.nova_endpoint = None
    client.neutron_endpoint = None
    client.cinder_endpoint = None
    client.keystone_endpoint = None
    client.glance_endpoint = None

    # Rate-limiter attributes (must mirror Pf9Client.__init__ so _throttle() works)
    client._rl_enabled = os.getenv("PF9_RATE_LIMIT_ENABLED", "false").lower() in ("1", "true", "yes")
    _rate = float(os.getenv("PF9_API_RATE_LIMIT", "10"))
    client._rl_rate = max(0.1, _rate)
    client._rl_tokens = client._rl_rate
    client._rl_last = __import__("time").monotonic()
    client._rl_lock = __import__("threading").Lock()

    # authenticate() does the real Keystone password auth + endpoint discovery
    client.authenticate()
    # Override project_id with the pre-resolved UUID (authenticate() may resolve it again
    # but we want the one we already resolved so it's consistent)
    client.project_id = project_id

    return client
