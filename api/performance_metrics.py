"""
Performance monitoring middleware for FastAPI.
Tracks request duration, status codes, and endpoint usage.

When Redis is reachable (REDIS_URL env var), all counters are stored in shared
Redis hashes/lists so every Gunicorn worker contributes to the same totals.
Falls back transparently to thread-safe in-memory storage when Redis is down.

Redis key layout (namespace ``pf9:metrics``):
  req_count     HASH   endpoint  → total request count      (HINCRBY)
  status_codes  HASH   status    → count                    (HINCRBY)
  dur_sum       HASH   endpoint  → cumulative seconds        (HINCRBYFLOAT)
  recent        LIST   JSON request objects, newest-first    (LPUSH/LTRIM)
  slow          LIST   JSON request objects for >1 s reqs   (LPUSH/LTRIM)
  errors        LIST   JSON request objects for 4xx/5xx     (LPUSH/LTRIM)
  start_time    STRING ISO-8601 startup timestamp            (SET NX)
"""
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_redis_client = None
_redis_lock = threading.Lock()


def _get_redis():
    """Return a live Redis client, or None if Redis is unavailable."""
    global _redis_client
    with _redis_lock:
        if _redis_client is not None:
            try:
                _redis_client.ping()
                return _redis_client
            except Exception:
                logger.warning("Redis metrics connection lost — reconnecting")
                _redis_client = None
        try:
            import redis  # lazy import

            c = redis.from_url(
                _REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            c.ping()
            _redis_client = c
            logger.info("Redis metrics connected at %s", _REDIS_URL)
        except Exception as exc:
            logger.debug("Redis metrics unavailable (%s) — using in-memory fallback", exc)
            _redis_client = None
        return _redis_client


class PerformanceMetrics:
    """
    Performance metrics storage.

    Writes go to Redis when available (shared across all Gunicorn workers).
    Falls back to thread-safe in-memory storage transparently.
    """

    _NS = "pf9:metrics"

    def __init__(self, max_history: int = 1000):
        self._max_history = max_history
        # In-memory fallback structures
        self._lock = threading.Lock()
        self.request_count = defaultdict(int)
        self.request_duration = defaultdict(lambda: deque(maxlen=100))
        self.status_codes = defaultdict(int)
        self.recent_requests = deque(maxlen=max_history)
        self.slow_requests = deque(maxlen=100)
        self.error_requests = deque(maxlen=100)
        self.start_time = datetime.now()
        self._start_iso = self.start_time.isoformat()

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def record_request(self, method: str, path: str, status_code: int, duration: float, user: str = None):
        """Record a request — Redis-first with in-memory fallback."""
        endpoint = f"{method} {path}"
        request_info = {
            "timestamp": datetime.now().isoformat(),
            "method": method,
            "path": path,
            "status": status_code,
            "duration_ms": round(duration * 1000, 2),
            "user": user,
        }
        rj = json.dumps(request_info)
        r = _get_redis()
        if r is not None:
            try:
                pipe = r.pipeline()
                pipe.hincrby(f"{self._NS}:req_count", endpoint, 1)
                pipe.hincrby(f"{self._NS}:status_codes", str(status_code), 1)
                pipe.hincrbyfloat(f"{self._NS}:dur_sum", endpoint, duration)
                pipe.lpush(f"{self._NS}:recent", rj)
                pipe.ltrim(f"{self._NS}:recent", 0, self._max_history - 1)
                if duration > 1.0:
                    pipe.lpush(f"{self._NS}:slow", rj)
                    pipe.ltrim(f"{self._NS}:slow", 0, 99)
                if status_code >= 400:
                    pipe.lpush(f"{self._NS}:errors", rj)
                    pipe.ltrim(f"{self._NS}:errors", 0, 99)
                pipe.set(f"{self._NS}:start_time", self._start_iso, nx=True)
                pipe.execute()
                return
            except Exception as exc:
                logger.warning("Redis metrics write failed (%s) — using in-memory fallback", exc)

        # In-memory fallback
        with self._lock:
            self.request_count[endpoint] += 1
            self.status_codes[status_code] += 1
            self.request_duration[endpoint].append(duration)
            self.recent_requests.append(request_info)
            if duration > 1.0:
                self.slow_requests.append(request_info)
            if status_code >= 400:
                self.error_requests.append(request_info)

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def get_stats(self):
        """Return statistics summary — Redis-first with in-memory fallback."""
        r = _get_redis()
        if r is not None:
            try:
                return self._get_stats_redis(r)
            except Exception as exc:
                logger.warning("Redis metrics read failed (%s) — using in-memory fallback", exc)
        return self._get_stats_memory()

    def _get_stats_redis(self, r):  # noqa: C901
        ns = self._NS
        req_count_raw = r.hgetall(f"{ns}:req_count")
        status_raw = r.hgetall(f"{ns}:status_codes")
        dur_sum_raw = r.hgetall(f"{ns}:dur_sum")
        recent_raw = r.lrange(f"{ns}:recent", 0, self._max_history - 1)
        slow_raw = r.lrange(f"{ns}:slow", 0, 99)
        error_raw = r.lrange(f"{ns}:errors", 0, 99)
        start_iso = r.get(f"{ns}:start_time")

        request_count_snap = {k: int(v) for k, v in req_count_raw.items()}
        status_codes_snap = {int(k): int(v) for k, v in status_raw.items()}
        dur_sum_snap = {k: float(v) for k, v in dur_sum_raw.items()}
        recent = [json.loads(x) for x in recent_raw]
        slow_snap = [json.loads(x) for x in slow_raw]
        error_snap = [json.loads(x) for x in error_raw]

        st = datetime.fromisoformat(start_iso) if start_iso else self.start_time
        uptime = (datetime.now() - st).total_seconds()

        # Build per-endpoint duration stats.  Use the recent list for
        # percentile computation (approximate, but sufficient).
        ep_dur_map: dict = defaultdict(list)
        for item in recent:
            ep = f"{item['method']} {item['path']}"
            ep_dur_map[ep].append(item["duration_ms"] / 1000.0)

        duration_stats = {}
        for endpoint, count in request_count_snap.items():
            if count == 0:
                continue
            total = dur_sum_snap.get(endpoint, 0.0)
            avg = total / count
            durations = sorted(ep_dur_map.get(endpoint, []))
            n = len(durations)
            p50 = durations[n // 2] if n else None
            p95 = durations[int(n * 0.95)] if n > 20 else None
            p99 = durations[int(n * 0.99)] if n > 100 else None
            duration_stats[endpoint] = {
                "count": count,
                "avg_duration": round(avg, 4),
                "min_duration": round(durations[0], 4) if durations else None,
                "max_duration": round(durations[-1], 4) if durations else None,
                "p50": round(p50, 4) if p50 is not None else None,
                "p95": round(p95, 4) if p95 is not None else None,
                "p99": round(p99, 4) if p99 is not None else None,
            }

        return self._build_response(
            request_count_snap, status_codes_snap, duration_stats,
            slow_snap, error_snap, uptime,
        )

    def _get_stats_memory(self):
        with self._lock:
            uptime = (datetime.now() - self.start_time).total_seconds()
            request_count_snap = dict(self.request_count)
            status_codes_snap = dict(self.status_codes)
            duration_snap = {k: list(v) for k, v in self.request_duration.items()}
            slow_snap = list(self.slow_requests)
            error_snap = list(self.error_requests)

        duration_stats = {}
        for endpoint, durations in duration_snap.items():
            if not durations:
                continue
            sorted_d = sorted(durations)
            n = len(sorted_d)
            avg = sum(sorted_d) / n
            p50 = sorted_d[n // 2]
            p95 = sorted_d[int(n * 0.95)] if n > 20 else None
            p99 = sorted_d[int(n * 0.99)] if n > 100 else None
            duration_stats[endpoint] = {
                "count": n,
                "avg_duration": round(avg, 4),
                "min_duration": round(sorted_d[0], 4),
                "max_duration": round(sorted_d[-1], 4),
                "p50": round(p50, 4),
                "p95": round(p95, 4) if p95 is not None else None,
                "p99": round(p99, 4) if p99 is not None else None,
            }

        return self._build_response(
            request_count_snap, status_codes_snap, duration_stats,
            slow_snap, error_snap, uptime,
        )

    @staticmethod
    def _build_response(request_count_snap, status_codes_snap, duration_stats, slow_snap, error_snap, uptime):
        total_requests = sum(request_count_snap.values())
        slow_endpoints = sorted(
            [(ep, s) for ep, s in duration_stats.items() if s["avg_duration"] > 1.0],
            key=lambda x: x[1]["avg_duration"],
            reverse=True,
        )[:10]
        all_endpoints = sorted(request_count_snap.items(), key=lambda x: x[1], reverse=True)
        top_endpoints = all_endpoints[:10]

        return {
            "uptime_seconds": round(uptime, 2),
            "total_requests": total_requests,
            "requests_per_second": round(total_requests / uptime if uptime > 0 else 0, 2),
            "status_codes": status_codes_snap,
            "top_endpoints": [
                {"endpoint": ep, "count": cnt, **duration_stats.get(ep, {})}
                for ep, cnt in top_endpoints
            ],
            "endpoint_stats": [
                {"endpoint": ep, "count": cnt, **duration_stats.get(ep, {})}
                for ep, cnt in all_endpoints
            ],
            "slow_endpoints": [
                {"endpoint": ep, "avg_duration": s["avg_duration"], "count": s["count"]}
                for ep, s in slow_endpoints
            ],
            "recent_slow_requests": [
                {k: v for k, v in rr.items() if k != "user"} for rr in slow_snap[-10:]
            ],
            "recent_errors": [
                {k: v for k, v in rr.items() if k != "user"} for rr in error_snap[-10:]
            ],
        }

    def get_endpoint_stats(self, method: str, path: str):
        """Get stats for a specific endpoint."""
        endpoint = f"{method} {path}"
        r = _get_redis()
        if r is not None:
            try:
                count = int(r.hget(f"{self._NS}:req_count", endpoint) or 0)
                if count == 0:
                    return None
                total_dur = float(r.hget(f"{self._NS}:dur_sum", endpoint) or 0)
                avg = total_dur / count
                recent_raw = r.lrange(f"{self._NS}:recent", 0, self._max_history - 1)
                durations = sorted([
                    json.loads(x)["duration_ms"] / 1000.0
                    for x in recent_raw
                    if f"{json.loads(x)['method']} {json.loads(x)['path']}" == endpoint
                ])
                n = len(durations)
                return {
                    "endpoint": endpoint,
                    "request_count": count,
                    "avg_duration_ms": round(avg * 1000, 2),
                    "min_duration_ms": round(durations[0] * 1000, 2) if durations else None,
                    "max_duration_ms": round(durations[-1] * 1000, 2) if durations else None,
                    "p50_duration_ms": round(durations[n // 2] * 1000, 2) if n else None,
                    "p95_duration_ms": round(durations[int(n * 0.95)] * 1000, 2) if n > 20 else None,
                    "p99_duration_ms": round(durations[int(n * 0.99)] * 1000, 2) if n > 100 else None,
                }
            except Exception as exc:
                logger.warning("Redis endpoint stats read failed (%s)", exc)

        # In-memory fallback
        with self._lock:
            durations = list(self.request_duration.get(endpoint, []))
            count = self.request_count[endpoint]

        if not durations:
            return None
        sorted_d = sorted(durations)
        n = len(sorted_d)
        return {
            "endpoint": endpoint,
            "request_count": count,
            "avg_duration_ms": round(sum(durations) / n * 1000, 2),
            "min_duration_ms": round(min(durations) * 1000, 2),
            "max_duration_ms": round(max(durations) * 1000, 2),
            "p50_duration_ms": round(sorted_d[n // 2] * 1000, 2),
            "p95_duration_ms": round(sorted_d[int(n * 0.95)] * 1000, 2) if n > 20 else None,
            "p99_duration_ms": round(sorted_d[int(n * 0.99)] * 1000, 2) if n > 100 else None,
        }


class PerformanceMiddleware(BaseHTTPMiddleware):
    """Middleware to track API performance"""

    def __init__(self, app, metrics: PerformanceMetrics):
        super().__init__(app)
        self.metrics = metrics

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip metrics endpoint to avoid recursion
        if request.url.path == "/metrics":
            return await call_next(request)

        start_time = time.time()

        user = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            user = "authenticated"

        response = await call_next(request)
        duration = time.time() - start_time

        self.metrics.record_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration=duration,
            user=user,
        )

        response.headers["X-Process-Time"] = f"{duration:.4f}"
        return response
