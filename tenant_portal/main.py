"""
main.py — Tenant portal FastAPI application entry point.

Mounts exclusively under /tenant/ (nginx forwards /tenant/ → this service,
port 8010). No admin routes exist in this process — blast-radius isolation.

CORS: Only subdomain origins matching the configured pattern are allowed.
      The admin origin is NOT in the allowed list.
"""

import logging
import os
import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from auth_routes import router as auth_router
from branding_routes import router as branding_router
from environment_routes import router as environment_router
from metrics_routes import router as metrics_router
from restore_routes import router as restore_router
from db_pool import init_pool
from rate_limiter import limiter
from redis_client import get_redis

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("tenant_portal")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PF9 Tenant Portal API",
    description=(
        "Self-service portal for Platform9 customers. "
        "All endpoints are scoped to the authenticated tenant's projects and regions."
    ),
    version="1.84.13",
    docs_url="/tenant/docs" if os.getenv("ENABLE_DOCS", "false").lower() == "true" else None,
    redoc_url=None,
    openapi_url="/tenant/openapi.json" if os.getenv("ENABLE_DOCS", "false").lower() == "true" else None,
)

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ---------------------------------------------------------------------------
# CORS — allow only tenant subdomain origins
# ---------------------------------------------------------------------------
_TENANT_ORIGIN_PATTERN = os.getenv(
    "TENANT_CORS_ORIGIN_PATTERN",
    r"^https://[a-z0-9-]+\.pf9-mngt\.ccc\.co\.il$",
)
_compiled_origin_re = re.compile(_TENANT_ORIGIN_PATTERN)


def _is_allowed_origin(origin: str) -> bool:
    return bool(_compiled_origin_re.match(origin))


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_TENANT_ORIGIN_PATTERN,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)

# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Error handlers — never expose stack traces to tenants
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    import uuid

    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    logger.exception("Unhandled error [request_id=%s]: %s", request_id, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "internal_error", "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    logger.info("Tenant portal starting up — initialising DB pool and Redis")
    try:
        init_pool()
        logger.info("DB pool ready")
    except Exception as exc:
        logger.warning(
            "DB pool failed to initialise at startup (%s). "
            "Configure TENANT_DB_PASSWORD to enable DB features.",
            exc,
        )
    # Verify Redis connectivity
    try:
        get_redis().ping()
        logger.info("Redis connection OK")
    except Exception as exc:
        logger.error("Redis connection failed on startup: %s", exc)

    cp_id = os.getenv("TENANT_PORTAL_CONTROL_PLANE_ID", "default")
    logger.info("Serving control plane: %s", cp_id)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Tenant portal shutting down")


# ---------------------------------------------------------------------------
# Health probe (used by Docker/K8s liveness + readiness checks)
# ---------------------------------------------------------------------------
@app.get("/tenant/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(branding_router)
app.include_router(environment_router)
app.include_router(metrics_router)
app.include_router(restore_router)
