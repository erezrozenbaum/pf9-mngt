import os
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from prometheus_client import PrometheusClient
from models import VMMetrics, HostMetrics, MetricsResponse

@asynccontextmanager
async def _lifespan(app: FastAPI):
    await startup_event()
    yield
    await shutdown_event()

app = FastAPI(title="PF9 Monitoring Service", version="1.0.0", lifespan=_lifespan)

LOG_FILE = os.getenv("LOG_FILE", "")

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "context"):
            log_record["context"] = record.context
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

logger = logging.getLogger("pf9_monitoring")
logger.setLevel(logging.INFO)
logger.handlers.clear()

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(JsonFormatter())
logger.addHandler(stream_handler)

if LOG_FILE:
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

@app.middleware("http")
async def monitoring_access_log(request: Request, call_next):
    start_time = time.time()
    request_id = str(uuid.uuid4())
    response = await call_next(request)
    duration_ms = round((time.time() - start_time) * 1000, 2)

    logger.info(
        f"{request.method} {request.url.path} {response.status_code} {duration_ms}ms",
        extra={
            "context": {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "ip_address": request.client.host if request.client else None,
            }
        }
    )

    response.headers["X-Request-Id"] = request_id
    return response

# Security configuration
_PROD_MODE = os.getenv("APP_ENV", "").lower() == "production"

# Production: only the nginx TLS proxy origin is valid.
# Development: Vite dev server is also allowed.
ALLOWED_ORIGINS = [
    "https://localhost",   # nginx TLS proxy (production + dev)
    "http://localhost",    # nginx HTTP (port 80)
]
if not _PROD_MODE:
    ALLOWED_ORIGINS += [
        "http://localhost:5173",   # Vite dev server
        "http://localhost:3000",   # Alt dev port
    ]
_extra_origin = os.getenv("PF9_ALLOWED_ORIGIN", os.getenv("PF9_ALLOWED_ORIGINS", ""))
for _extra in _extra_origin.split(","):
    _extra = _extra.strip()
    if _extra and _extra not in ALLOWED_ORIGINS:
        ALLOWED_ORIGINS.append(_extra)
ALLOWED_ORIGINS = [origin for origin in ALLOWED_ORIGINS if origin]

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Secure CORS for UI integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Global Prometheus client.
# Initialise with an explicit empty list when PF9_HOSTS is unset so that
# auto-discovery in startup_event can set the real hosts before collection
# starts.  A module-level split(",") on an empty string produces [""] which
# causes scrape attempts against an empty hostname — guarded here.
_pf9_hosts_env_init = os.getenv("PF9_HOSTS", "").strip()
_initial_hosts: list = (
    [h.strip() for h in _pf9_hosts_env_init.split(",") if h.strip()]
    if _pf9_hosts_env_init
    else []
)
prometheus_client = PrometheusClient(
    hosts=_initial_hosts,
    cache_ttl=int(os.getenv("METRICS_CACHE_TTL", "60"))
)

async def _discover_hosts_with_retry(max_attempts: int = 5, delay_s: float = 5.0) -> list:
    """Attempt to fetch Prometheus targets from the admin API with retries.

    Returns the list of host IPs discovered, or [] if all attempts fail.
    In Kubernetes the admin API pod may not be ready when the monitoring pod
    starts; retrying avoids a permanent empty-host situation.
    """
    import asyncio
    import httpx as _httpx
    _api_url = os.getenv("API_BASE_URL", "http://pf9-api:8000")
    _secret = os.getenv("INTERNAL_SERVICE_SECRET", "")
    for attempt in range(1, max_attempts + 1):
        try:
            _r = _httpx.get(
                f"{_api_url}/internal/prometheus-targets",
                headers={"X-Internal-Secret": _secret},
                timeout=5.0,
            )
            if _r.status_code == 200:
                _targets = _r.json().get("targets", [])
                if _targets:
                    _ips = [t.split(":")[0] for t in _targets if t]
                    logger.info(
                        "Auto-discovered hypervisor hosts from admin API (attempt %d)",
                        attempt,
                        extra={"context": {"hosts": _ips, "count": len(_ips)}},
                    )
                    return _ips
                else:
                    logger.info(
                        "Admin API returned no Prometheus targets yet (attempt %d/%d)",
                        attempt, max_attempts,
                    )
            else:
                logger.warning("Admin API /internal/prometheus-targets → HTTP %d (attempt %d)", _r.status_code, attempt)
        except Exception as _e:
            logger.warning(
                "Could not reach admin API for host discovery (attempt %d/%d): %s",
                attempt, max_attempts, _e,
            )
        if attempt < max_attempts:
            await asyncio.sleep(delay_s)
    logger.warning("Host auto-discovery failed after %d attempts — monitoring will start with no hosts", max_attempts)
    return []

async def startup_event():
    """Initialize the application"""
    from container_watchdog import start_watchdog
    start_watchdog()
    logger.info("PF9 Monitoring Service started", extra={"context": {"cache": "/tmp/cache/metrics_cache.json"}})  # nosec B108
    
    # Ensure we have a cache file with some default data if none exists
    import os
    os.makedirs("/tmp/cache", exist_ok=True)  # nosec B108 — container-internal volume /tmp/cache
    if not os.path.exists("/tmp/cache/metrics_cache.json"):  # nosec B108
        default_cache = {
            "vms": [],
            "hosts": [],
            "alerts": [],
            "summary": {"total_vms": 0, "total_hosts": 0, "last_update": None},
            "timestamp": None
        }
        try:
            with open("/tmp/cache/metrics_cache.json", "w") as f:  # nosec B108
                json.dump(default_cache, f)
            logger.info("Created default cache file", extra={"context": {"path": "/tmp/cache/metrics_cache.json"}})  # nosec B108
        except Exception as e:
            logger.error("Could not create cache file", extra={"context": {"error": str(e)}})

    # Start background metrics collection from PF9 host Prometheus endpoints.
    # If PF9_HOSTS is not configured, attempt to discover hypervisor IPs from
    # the admin API's /internal/prometheus-targets endpoint (with retries so
    # a K8s startup race between pods does not permanently disable collection).
    pf9_hosts_env = os.getenv("PF9_HOSTS", "").strip()
    if not pf9_hosts_env:
        _discovered = await _discover_hosts_with_retry(max_attempts=5, delay_s=5.0)
        if _discovered:
            prometheus_client.hosts = _discovered
    await prometheus_client.start_collection()

async def shutdown_event():
    """Stop background metrics collection gracefully."""
    await prometheus_client.stop_collection()

# Helper functions
def load_cache_data() -> Dict[str, Any]:
    """Load metrics from cache file"""
    try:
        with open("/tmp/cache/metrics_cache.json", "r") as f:  # nosec B108
            return json.load(f)
    except FileNotFoundError:
        return {
            "vms": [],
            "hosts": [],
            "alerts": [],
            "summary": {"total_vms": 0, "total_hosts": 0, "last_update": None},
            "timestamp": None
        }
    except Exception as e:
        logger.error("Error loading cache", extra={"context": {"error": str(e)}})
        return {
            "vms": [],
            "hosts": [],
            "alerts": [],
            "summary": {"total_vms": 0, "total_hosts": 0, "last_update": None},
            "timestamp": None
        }

# API endpoints
@app.get("/")
@limiter.limit("60/minute")
async def read_root(request: Request):
    return {"service": "PF9 Monitoring", "status": "running", "version": "1.0.0"}

@app.get("/health")
@limiter.limit("60/minute")
async def health_check(request: Request):
    """Health check endpoint"""
    logger.info("Health check", extra={"context": {"path": "/health"}})
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/auto-setup")
async def auto_setup():
    """
    Automatically triggers monitoring setup when needed
    Called when UI detects empty monitoring data
    """
    try:
        # Check if auto-setup is needed
        setup_needed = os.path.exists("/tmp/need_monitoring_setup")  # nosec B108
        cache_data = load_cache_data()
        hosts_count = len(cache_data.get("hosts", []))
        
        if setup_needed or hosts_count == 0:
            # Return instructions for host-side setup
            return {
                "status": "setup_needed",
                "message": "Please run: .\\fix_monitoring.ps1",
                "hosts_detected": hosts_count,
                "setup_file_exists": setup_needed
            }
        else:
            return {
                "status": "ready", 
                "message": "Monitoring is properly configured",
                "hosts_detected": hosts_count
            }
            
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/metrics/vms")
async def get_vm_metrics(
    tenant: Optional[str] = Query(None, description="Filter by tenant"),
    project: Optional[str] = Query(None, description="Filter by project"),
    limit: Optional[int] = Query(100, description="Limit number of results")
):
    """Get VM resource metrics"""
    try:
        cache_data = load_cache_data()
        vms = cache_data.get("vms", [])
        
        # Apply filters if provided
        if tenant:
            vms = [vm for vm in vms if vm.get("tenant") == tenant]
        if project:
            vms = [vm for vm in vms if vm.get("project") == project]
        
        # Apply limit
        vms = vms[:limit] if limit else vms
        
        return {"data": vms, "timestamp": cache_data.get("timestamp")}
    except Exception as e:
        logger.error("Error fetching VM metrics", extra={"context": {"error": str(e)}})
        raise HTTPException(status_code=500, detail=f"Error fetching VM metrics: {str(e)}")

@app.get("/metrics/hosts")
async def get_host_metrics(
    limit: Optional[int] = Query(100, description="Limit number of results")
):
    """Get host resource metrics"""
    try:
        cache_data = load_cache_data()
        hosts = cache_data.get("hosts", [])
        
        # Apply limit
        hosts = hosts[:limit] if limit else hosts
        
        return {"data": hosts, "timestamp": cache_data.get("timestamp")}
    except Exception as e:
        logger.error("Error fetching host metrics", extra={"context": {"error": str(e)}})
        raise HTTPException(status_code=500, detail=f"Error fetching host metrics: {str(e)}")

@app.get("/metrics/alerts")
async def get_alerts():
    """Get current alerts"""
    try:
        cache_data = load_cache_data()
        return {"alerts": cache_data.get("alerts", [])}
    except Exception as e:
        logger.error("Error fetching alerts", extra={"context": {"error": str(e)}})
        raise HTTPException(status_code=500, detail=f"Error fetching alerts: {str(e)}")

@app.get("/metrics/summary")
async def get_metrics_summary():
    """Get summary of all metrics"""
    try:
        cache_data = load_cache_data()
        return cache_data.get("summary", {
            "total_vms": 0,
            "total_hosts": 0,
            "last_update": None,
            "vm_stats": {},
            "host_stats": {}
        })
    except Exception as e:
        logger.error("Error fetching summary", extra={"context": {"error": str(e)}})
        raise HTTPException(status_code=500, detail=f"Error fetching summary: {str(e)}")

@app.get("/metrics", response_model=MetricsResponse)
async def get_all_metrics(
    tenant: Optional[str] = Query(None),
    project: Optional[str] = Query(None),
    vm_limit: Optional[int] = Query(50),
    host_limit: Optional[int] = Query(20)
):
    """Get all metrics in one response"""
    try:
        cache_data = load_cache_data()
        
        vms = cache_data.get("vms", [])
        hosts = cache_data.get("hosts", [])
        
        # Apply filters
        if tenant:
            vms = [vm for vm in vms if vm.get("tenant") == tenant]
        if project:
            vms = [vm for vm in vms if vm.get("project") == project]
        
        # Apply limits
        vms = vms[:vm_limit] if vm_limit else vms
        hosts = hosts[:host_limit] if host_limit else hosts
        
        return {
            "vms": vms,
            "hosts": hosts,
            "alerts": cache_data.get("alerts", []),
            "summary": cache_data.get("summary", {}),
            "timestamp": cache_data.get("timestamp")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching metrics: {str(e)}")

# Administrative endpoints
@app.post("/metrics/refresh")
async def refresh_metrics():
    """Trigger metrics refresh (cache reload)"""
    try:
        cache_data = load_cache_data()
        return {
            "status": "refreshed",
            "timestamp": datetime.utcnow().isoformat(),
            "hosts_count": len(cache_data.get("hosts", [])),
            "vms_count": len(cache_data.get("vms", []))
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error refreshing metrics: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)  # nosec B104 — monitoring container must bind all interfaces