"""
api/cache.py — Simple Redis-backed TTL cache for expensive Platform9 API calls.

Design goals:
- Transparent: callers don't change; cache miss falls through to the real call.
- Safe: any Redis failure falls back to a direct call — never raises.
- Configurable: TTL and enable/disable controlled by env vars.

Usage:
    from cache import cached

    class Pf9Client:
        @cached(ttl=60, key_prefix="pf9:servers")
        def list_servers(self, ...):
            ...
"""

import hashlib
import json
import logging
import os
from functools import wraps

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DEFAULT_TTL = int(os.getenv("CACHE_TTL_SECONDS", "60"))
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"

_client = None


def _get_client():
    """Return a live Redis client, or None if unavailable."""
    global _client
    if not CACHE_ENABLED:
        return None
    if _client is not None:
        return _client
    try:
        import redis  # imported lazily so missing package doesn't break startup

        c = redis.from_url(
            REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        c.ping()
        _client = c
        logger.info("Redis cache connected at %s", REDIS_URL)
    except Exception as exc:
        logger.warning("Redis cache unavailable (%s) — running without cache", exc)
        _client = None
    return _client


def cached(ttl: int = DEFAULT_TTL, key_prefix: str = ""):
    """
    Decorator: cache the return value of a method in Redis.

    - Key is derived from ``key_prefix`` (or the qualified function name) plus
      a hash of the positional arguments *after* ``self``.
    - Falls back to a direct call on any Redis error.
    - Instance-method safe: ``self`` is excluded from the cache key.
    """

    def decorator(fn):
        prefix = key_prefix or fn.__qualname__

        @wraps(fn)
        def wrapper(*args, **kwargs):
            client = _get_client()
            if client is None:
                return fn(*args, **kwargs)

            # Build cache key: prefix + hash of (positional args[1:] + kwargs)
            try:
                key_data = json.dumps(
                    {"a": list(args[1:]), "k": kwargs}, sort_keys=True, default=str
                )
                key_hash = hashlib.md5(key_data.encode()).hexdigest()
                cache_key = f"{prefix}:{key_hash}"
            except Exception:
                return fn(*args, **kwargs)

            # Try cache read
            try:
                raw = client.get(cache_key)
                if raw is not None:
                    return json.loads(raw)
            except Exception as exc:
                logger.debug("Cache read error for %s: %s", cache_key, exc)

            # Cache miss — call through and store result
            result = fn(*args, **kwargs)
            try:
                client.setex(cache_key, ttl, json.dumps(result, default=str))
            except Exception as exc:
                logger.debug("Cache write error for %s: %s", cache_key, exc)

            return result

        # Allow callers to bypass/invalidate manually
        def invalidate(*args, **kwargs):
            client = _get_client()
            if client is None:
                return
            try:
                key_data = json.dumps(
                    {"a": list(args), "k": kwargs}, sort_keys=True, default=str
                )
                key_hash = hashlib.md5(key_data.encode()).hexdigest()
                client.delete(f"{prefix}:{key_hash}")
            except Exception as exc:
                logger.debug("Cache invalidation error for %s:%s: %s", prefix, key_hash, exc)

        wrapper.invalidate = invalidate
        return wrapper

    return decorator
