"""
secret_helper.py — Docker Secrets / environment-variable reader.

Priority order for each secret:
  1. Docker secret file at /run/secrets/<name>  (production with `secrets:` in compose)
  2. Environment variable <ENV_VAR>             (development / backwards-compat)
  3. Provided default value (or empty string)

Usage:
    from secret_helper import read_secret

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
            if value:
                return value
        except OSError as exc:
            logger.warning("Could not read secret file %s: %s", secret_path, exc)

    if env_var:
        value = os.getenv(env_var, "")
        if value:
            return value

    return default
