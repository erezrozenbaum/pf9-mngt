"""
shared/secret_helper.py — Docker Secrets / environment-variable reader.

Single source of truth shared by all pf9-mngt services.

Priority order for each secret:
  1. Docker secret file at /run/secrets/<name>  (production with `secrets:` in compose)
  2. Environment variable <ENV_VAR>             (development / backwards-compat)
  3. Provided default value (or empty string)

Usage:
    from shared.secret_helper import read_secret

    password = read_secret("db_password", env_var="PF9_DB_PASSWORD")
    jwt_key  = read_secret("jwt_secret",  env_var="JWT_SECRET_KEY")
"""

import os
import logging

logger = logging.getLogger(__name__)

_SECRETS_DIR = os.getenv("SECRETS_DIR", "/run/secrets")


def read_secret(name: str, env_var: str = None, default: str = "") -> str:
    """
    Read a secret value from Docker secrets or fall back to an env var.

    Args:
        name:    Docker secret name (file under /run/secrets/).
        env_var: Environment variable name to fall back to.
        default: Final fallback if neither source provides a value.

    Returns:
        The secret value as a stripped string, never None.
    """
    secret_path = os.path.join(_SECRETS_DIR, name)
    if os.path.isfile(secret_path):
        try:
            with open(secret_path, "r", encoding="utf-8") as fh:
                value = fh.read().strip()
        except OSError as exc:
            logger.warning("Could not read secret file %s: %s", secret_path, exc)
            value = ""

        if value:
            # Only enforce the permission check when the file carries actual secret
            # material.  Empty placeholder files (used in local dev Docker Compose
            # where bind-mounts appear as 0o777) are intentionally ignored — the
            # caller will fall through to the env-var fallback below.
            file_mode = os.stat(secret_path).st_mode & 0o777
            if file_mode & 0o022:  # write bits set for group or others
                raise PermissionError(
                    f"Secret file {secret_path} has insecure permissions ({oct(file_mode)}). "
                    "Remove write access from group and others: chmod 0600."
                )
            if file_mode & 0o044:  # read-only for group/others (e.g. Docker 0444)
                logger.warning(
                    "Secret file %s is world-readable (%o). "
                    "For better security, restrict to owner-only (chmod 0600).",
                    secret_path, file_mode,
                )
            return value

    if env_var:
        value = os.getenv(env_var, "")
        if value:
            return value

    return default
