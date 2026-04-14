"""
redis_client.py — Redis connection singleton for the tenant portal.

Key namespace conventions (tenant portal owns the `tenant:` prefix):
  tenant:session:<sha256_of_jwt>      TTL = TENANT_TOKEN_EXPIRE_MINUTES
  tenant:ratelimit:<user_id>:<group>:<minute_bucket>   TTL = 60 s
  tenant:mfa_fail:<user_id>           TTL = 3600 s
  tenant:allowed:<cp_id>:<user_id>    TTL = 300 s  (allowlist cache)
  tenant:blocked:<cp_id>:<user_id>    (no TTL — admin-set blocklist)
"""

import os
import logging

import redis

from secret_helper import read_secret

logger = logging.getLogger("tenant_portal.redis")

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        host = os.getenv("REDIS_HOST", "redis")
        port = int(os.getenv("REDIS_PORT", "6379"))
        db = int(os.getenv("TENANT_REDIS_DB", "0"))
        password = read_secret("redis_password", env_var="REDIS_PASSWORD") or None
        _redis_client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
        )
        logger.info("Tenant portal Redis client initialised (%s:%d db=%d)", host, port, db)
    return _redis_client
