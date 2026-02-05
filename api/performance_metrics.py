"""
Performance monitoring middleware for FastAPI
Tracks request duration, status codes, and endpoint usage
"""
import time
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict, deque
from datetime import datetime, timedelta
import json

class PerformanceMetrics:
    """In-memory performance metrics storage"""
    
    def __init__(self, max_history: int = 1000):
        self.request_count = defaultdict(int)
        self.request_duration = defaultdict(list)
        self.status_codes = defaultdict(int)
        self.recent_requests = deque(maxlen=max_history)
        self.slow_requests = deque(maxlen=100)  # Track slowest requests
        self.error_requests = deque(maxlen=100)  # Track errors
        self.start_time = datetime.now()
    
    def record_request(self, method: str, path: str, status_code: int, duration: float, user: str = None):
        """Record a request"""
        endpoint = f"{method} {path}"
        
        # Update counters
        self.request_count[endpoint] += 1
        self.status_codes[status_code] += 1
        
        # Track duration
        if endpoint not in self.request_duration:
            self.request_duration[endpoint] = deque(maxlen=100)
        self.request_duration[endpoint].append(duration)
        
        # Record in recent requests
        request_info = {
            "timestamp": datetime.now().isoformat(),
            "method": method,
            "path": path,
            "status": status_code,
            "duration_ms": round(duration * 1000, 2),
            "user": user
        }
        self.recent_requests.append(request_info)
        
        # Track slow requests (>1 second)
        if duration > 1.0:
            self.slow_requests.append(request_info)
        
        # Track errors (4xx, 5xx)
        if status_code >= 400:
            self.error_requests.append(request_info)
    
    def get_stats(self):
        """Get statistics summary"""
        total_requests = sum(self.request_count.values())
        uptime = (datetime.now() - self.start_time).total_seconds()
        
        # Calculate average durations
        avg_durations = {}
        for endpoint, durations in self.request_duration.items():
            if durations:
                avg_durations[endpoint] = round(sum(durations) / len(durations) * 1000, 2)
        
        # Top slow endpoints
        slow_endpoints = sorted(
            avg_durations.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Top used endpoints
        top_endpoints = sorted(
            self.request_count.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        return {
            "uptime_seconds": round(uptime, 2),
            "total_requests": total_requests,
            "requests_per_second": round(total_requests / uptime if uptime > 0 else 0, 2),
            "status_codes": dict(self.status_codes),
            "top_endpoints": [{"endpoint": ep, "count": cnt} for ep, cnt in top_endpoints],
            "slow_endpoints": [{"endpoint": ep, "avg_ms": ms} for ep, ms in slow_endpoints],
            "recent_slow_requests": list(self.slow_requests)[-10:],
            "recent_errors": list(self.error_requests)[-10:],
        }
    
    def get_endpoint_stats(self, method: str, path: str):
        """Get stats for specific endpoint"""
        endpoint = f"{method} {path}"
        durations = self.request_duration.get(endpoint, [])
        
        if not durations:
            return None
        
        sorted_durations = sorted(durations)
        return {
            "endpoint": endpoint,
            "request_count": self.request_count[endpoint],
            "avg_duration_ms": round(sum(durations) / len(durations) * 1000, 2),
            "min_duration_ms": round(min(durations) * 1000, 2),
            "max_duration_ms": round(max(durations) * 1000, 2),
            "p50_duration_ms": round(sorted_durations[len(sorted_durations) // 2] * 1000, 2),
            "p95_duration_ms": round(sorted_durations[int(len(sorted_durations) * 0.95)] * 1000, 2) if len(sorted_durations) > 20 else None,
            "p99_duration_ms": round(sorted_durations[int(len(sorted_durations) * 0.99)] * 1000, 2) if len(sorted_durations) > 100 else None,
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
        
        # Start timer
        start_time = time.time()
        
        # Extract user from auth header if present
        user = None
        try:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                # You could decode JWT here to get username
                user = "authenticated"
        except:
            pass
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Record metrics
        self.metrics.record_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration=duration,
            user=user
        )
        
        # Add performance header
        response.headers["X-Process-Time"] = f"{duration:.4f}"
        
        return response
