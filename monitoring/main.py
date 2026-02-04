import os
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from prometheus_client import PrometheusClient
from models import VMMetrics, HostMetrics, MetricsResponse

app = FastAPI(title="PF9 Monitoring Service", version="1.0.0")

# Security configuration
ALLOWED_ORIGINS = [
    "http://localhost:5173",  # React UI
    "http://localhost:3000",  # Development
    os.getenv("PF9_ALLOWED_ORIGIN", "http://localhost:5173")
]
ALLOWED_ORIGINS = [origin for origin in ALLOWED_ORIGINS if origin]

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security middleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "*"])

# Secure CORS for UI integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Global Prometheus client
prometheus_client = PrometheusClient(
    hosts=os.getenv("PF9_HOSTS", "localhost").split(","),
    cache_ttl=int(os.getenv("METRICS_CACHE_TTL", "60"))
)

@app.on_event("startup")
async def startup_event():
    """Initialize the application"""
    print("PF9 Monitoring Service started")
    print("Reading metrics from host-collected cache file at /tmp/metrics_cache.json")
    
    # Ensure we have a cache file with some default data if none exists
    import os
    if not os.path.exists("/tmp/metrics_cache.json"):
        default_cache = {
            "vms": [],
            "hosts": [],
            "alerts": [],
            "summary": {"total_vms": 0, "total_hosts": 0, "last_update": None},
            "timestamp": None
        }
        try:
            with open("/tmp/metrics_cache.json", "w") as f:
                json.dump(default_cache, f)
            print("Created default cache file")
        except Exception as e:
            print(f"Could not create cache file: {e}")

# Helper functions
def load_cache_data() -> Dict[str, Any]:
    """Load metrics from cache file"""
    try:
        with open("/tmp/metrics_cache.json", "r") as f:
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
        print(f"Error loading cache: {e}")
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
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/auto-setup")
async def auto_setup():
    """
    Automatically triggers monitoring setup when needed
    Called when UI detects empty monitoring data
    """
    try:
        # Check if auto-setup is needed
        setup_needed = os.path.exists("/tmp/need_monitoring_setup")
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
        raise HTTPException(status_code=500, detail=f"Error fetching host metrics: {str(e)}")

@app.get("/metrics/alerts")
async def get_alerts():
    """Get current alerts"""
    try:
        cache_data = load_cache_data()
        return {"alerts": cache_data.get("alerts", [])}
    except Exception as e:
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
    uvicorn.run(app, host="0.0.0.0", port=8001)