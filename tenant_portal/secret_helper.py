"""
secret_helper.py — Docker Secrets / environment-variable reader.

Priority order:
  1. Docker secret file at /run/secrets/<name>
  2. Environment variable <ENV_VAR>
  3. Provided default (or empty string)
"""

import os
import stat
import logging

logger = logging.getLogger(__name__)

_SECRETS_DIR = os.getenv("SECRETS_DIR", "/run/secrets")


def read_secret(name: str, env_var: str = None, default: str = "") -> str:
    secret_path = os.path.join(_SECRETS_DIR, name)
    if os.path.isfile(secret_path):
        file_mode = os.stat(secret_path).st_mode & 0o777
        if file_mode & 0o077:
            logger.warning(
                "Secret file %s has insecure permissions (%o). Expected 0600 or 0400.",
                secret_path,
                file_mode,
            )
        try:
            with open(secret_path, "r", encoding="utf-8") as fh:
                value = fh.read().strip()
            if value:
                return value
        except OSError as exc:
            logger.error("Cannot read secret file %s: %s", secret_path, exc)

    if env_var:
        value = os.getenv(env_var, "").strip()
        if value:
            return value

    return default
