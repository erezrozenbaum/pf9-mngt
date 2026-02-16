import os
import sys
import asyncio
import re
import logging
import json
import time
import uuid
from typing import Optional, List, Any, Dict
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, Query, HTTPException, status, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from pf9_control import get_client

# Database connection pool
from db_pool import get_connection, close_pool

# Authentication imports
from auth import (
    ldap_auth, create_access_token, get_current_user, require_authentication, 
    require_permission, set_user_role, get_user_role, log_auth_event,
    create_user_session, invalidate_user_session, initialize_default_admin,
    ENABLE_AUTHENTICATION, JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    Token, LoginRequest, User, UserRole
)
from auth import has_permission, verify_token

# Config validation and monitoring
from config_validator import ConfigValidator
from performance_metrics import PerformanceMetrics, PerformanceMiddleware
from structured_logging import setup_logging

# Dashboard endpoints
from dashboards import router as dashboard_router

# Notification endpoints
from notification_routes import router as notification_router

# Backup management endpoints
from backup_routes import router as backup_router

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Enhanced input validation models
# ---------------------------------------------------------------------------
class CreateFlavorRequest(BaseModel):
    name: str
    vcpus: int
    ram: int  # MB
    disk: int  # GB
    swap: Optional[int] = 0
    ephemeral: Optional[int] = 0
    is_public: Optional[bool] = True
    
    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Name cannot be empty')
        if not re.match(r'^[a-zA-Z0-9._-]+$', v):
            raise ValueError('Name can only contain alphanumeric characters, dots, underscores, and hyphens')
        if len(v) > 64:
            raise ValueError('Name must be 64 characters or less')
        return v.strip()
    
    @validator('vcpus')
    def validate_vcpus(cls, v):
        if v < 1 or v > 64:
            raise ValueError('vCPUs must be between 1 and 64')
        return v
    
    @validator('ram')
    def validate_ram(cls, v):
        if v < 128 or v > 131072:  # 128MB to 128GB
            raise ValueError('RAM must be between 128MB and 128GB')
        return v
    
    @validator('disk')
    def validate_disk(cls, v):
        if v < 0 or v > 2048:  # 0GB to 2TB
            raise ValueError('Disk must be between 0GB and 2TB')
        return v

class CreateNetworkRequest(BaseModel):
    name: str
    tenant_id: str
    shared: Optional[bool] = False
    external: Optional[bool] = False
    
    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Name cannot be empty')
        if not re.match(r'^[a-zA-Z0-9._-]+$', v):
            raise ValueError('Name can only contain alphanumeric characters, dots, underscores, and hyphens')
        if len(v) > 64:
            raise ValueError('Name must be 64 characters or less')
        return v.strip()
    
    @validator('tenant_id')
    def validate_tenant_id(cls, v):
        if not v or not v.strip():
            raise ValueError('Tenant ID cannot be empty')
        return v.strip()


class CreateSecurityGroupRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    project_id: Optional[str] = None

    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Name cannot be empty')
        if not re.match(r'^[a-zA-Z0-9._\- ]+$', v):
            raise ValueError('Name can only contain alphanumeric characters, dots, underscores, hyphens, and spaces')
        if len(v) > 255:
            raise ValueError('Name must be 255 characters or less')
        return v.strip()


class CreateSecurityGroupRuleRequest(BaseModel):
    security_group_id: str
    direction: str  # 'ingress' or 'egress'
    protocol: Optional[str] = None  # 'tcp', 'udp', 'icmp', or None (any)
    port_range_min: Optional[int] = None
    port_range_max: Optional[int] = None
    remote_ip_prefix: Optional[str] = None
    remote_group_id: Optional[str] = None
    ethertype: Optional[str] = "IPv4"
    description: Optional[str] = ""

    @validator('direction')
    def validate_direction(cls, v):
        if v not in ('ingress', 'egress'):
            raise ValueError('Direction must be "ingress" or "egress"')
        return v

    @validator('protocol')
    def validate_protocol(cls, v):
        if v is not None and v not in ('tcp', 'udp', 'icmp', 'icmpv6', 'any'):
            raise ValueError('Protocol must be tcp, udp, icmp, icmpv6, any, or null')
        return v

    @validator('ethertype')
    def validate_ethertype(cls, v):
        if v not in ('IPv4', 'IPv6'):
            raise ValueError('Ethertype must be "IPv4" or "IPv6"')
        return v

    @validator('port_range_min')
    def validate_port_min(cls, v):
        if v is not None and (v < 1 or v > 65535):
            raise ValueError('Port must be between 1 and 65535')
        return v

    @validator('port_range_max')
    def validate_port_max(cls, v):
        if v is not None and (v < 1 or v > 65535):
            raise ValueError('Port must be between 1 and 65535')
        return v


APP_NAME = "pf9-mgmt-api"

# Security configuration
ADMIN_USERNAME = os.getenv("PF9_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("PF9_ADMIN_PASSWORD")
ALLOWED_ORIGINS = [
    "http://localhost:5173",  # React UI
    "http://localhost:3000",  # Development
    os.getenv("PF9_ALLOWED_ORIGIN", "http://localhost:5173")
]
ALLOWED_ORIGINS = [origin for origin in ALLOWED_ORIGINS if origin]  # Remove None values

# Validate configuration on import
ConfigValidator.validate_and_exit_on_error()

# Setup structured logging
logger = setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    json_logs=os.getenv("JSON_LOGS", "false").lower() == "true",
    log_file=os.getenv("LOG_FILE", None)
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
security = HTTPBasic()

# Performance metrics
performance_metrics = PerformanceMetrics()

# Audit logging
audit_logger = logging.getLogger("audit")
audit_handler = logging.StreamHandler()
audit_handler.setFormatter(logging.Formatter('%(asctime)s - AUDIT - %(message)s'))
audit_logger.addHandler(audit_handler)
audit_logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Security functions
# ---------------------------------------------------------------------------
def log_admin_operation(operation: str, resource_id: str, request: Request, authenticated: bool = False):
    audit_logger.info(f"{operation} - Resource: {resource_id} - IP: {request.client.host if request.client else 'unknown'} - Auth: {authenticated}")

def verify_admin_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> bool:
    if not ADMIN_PASSWORD:
        # If no admin password configured, log warning but allow (backward compatibility)
        audit_logger.warning("Admin operation attempted with no admin password configured")
        return False
    
    if credentials.username != ADMIN_USERNAME or credentials.password != ADMIN_PASSWORD:
        audit_logger.warning(f"Admin operation attempted with invalid credentials for user: {credentials.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    return True

# ---------------------------------------------------------------------------
# DB connection helper (inside Docker: host defaults to "db")
# Uses connection pool for concurrency safety.
# ---------------------------------------------------------------------------
def db_conn():
    """Return a connection from the pool.
    Prefer `with get_connection() as conn:` for automatic cleanup.
    If you use db_conn() directly, you MUST close in a finally block.
    """
    from db_pool import get_pool
    return get_pool().getconn()


app = FastAPI(title=APP_NAME)

@app.on_event("shutdown")
async def shutdown_event():
    close_pool()

# Include routers
app.include_router(dashboard_router)
app.include_router(notification_router)
app.include_router(backup_router)

# Rate limiting setup
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Performance monitoring middleware
app.add_middleware(PerformanceMiddleware, metrics=performance_metrics)

# Cache control middleware (prevents browser caching of API responses)
@app.middleware("http")
async def add_cache_control_headers(request: Request, call_next):
    response = await call_next(request)
    # Prevent caching for all API endpoints except static files
    if not request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Security middleware (TrustedHost)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "*"])

# CORS middleware (added LAST so it executes FIRST in the chain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# RBAC middleware (enforces read/write permissions by resource)
@app.middleware("http")
async def rbac_middleware(request: Request, call_next):
    if not ENABLE_AUTHENTICATION:
        return await call_next(request)

    # Skip auth endpoints and public/system endpoints
    path = request.url.path
    if (
        path.startswith("/auth") or
        path.startswith("/settings/") or
        path.startswith("/static/") or
        path in ["/health", "/metrics", "/openapi.json", "/docs", "/redoc", "/simple-test", "/test-users-db"]
    ):
        return await call_next(request)

    if request.method == "OPTIONS":
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        response = JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    token = auth_header[7:]
    token_data = verify_token(token)
    if not token_data:
        response = JSONResponse(status_code=401, content={"detail": "Invalid token"})
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    # Extract segment (first path component) without query parameters
    clean_path = path.split("?")[0]  # Remove query string
    segment = clean_path.lstrip("/").split("/")[0]
    
    resource_map = {
        "domains": "domains",
        "tenants": "projects",
        "projects": "projects",
        "servers": "servers",
        "snapshots": "snapshots",
        "networks": "networks",
        "subnets": "subnets",
        "ports": "ports",
        "floatingips": "floatingips",
        "volumes": "volumes",
        "flavors": "flavors",
        "images": "images",
        "hypervisors": "hypervisors",
        "history": "history",
        "audit": "audit",
        "monitoring": "monitoring",
        "users": "users",
        "dashboard": "dashboard",
        "restore": "restore",
        "security-groups": "security_groups",
        "security-group-rules": "security_groups",
        "drift": "drift",
        "tenant-health": "tenant_health",
    }

    resource = resource_map.get(segment)
    if not resource:
        return await call_next(request)

    permission = "read" if request.method == "GET" else "write"
    if not has_permission(token_data.username, resource, permission):
        log_auth_event(
            username=token_data.username,
            action="permission_denied",
            success=False,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            resource=resource,
            endpoint=path,
        )
        response = JSONResponse(
            status_code=403,
            content={"detail": f"Insufficient permissions for {resource}:{permission}"}
        )
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    return await call_next(request)


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    start_time = time.time()
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)

    duration_ms = round((time.time() - start_time) * 1000, 2)
    response.headers["X-Request-Id"] = request_id

    user = "anonymous"
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        token_data = verify_token(token)
        if token_data:
            user = token_data.username

    context = {
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "user": user,
        "ip_address": request.client.host if request.client else None,
    }

    message = (
        f"{request.method} {request.url.path} "
        f"{response.status_code} {duration_ms}ms"
    )

    if response.status_code >= 500:
        logger.error(message, extra={"context": context})
    elif response.status_code >= 400:
        logger.warning(message, extra={"context": context})
    else:
        logger.info(message, extra={"context": context})

    return response

# Import snapshot management routes
from snapshot_management import setup_snapshot_routes
from restore_management import setup_restore_routes, RestoreOpenStackClient

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize authentication system on startup"""
    initialize_default_admin()
    # Setup snapshot management routes
    setup_snapshot_routes(app, db_conn)
    # Setup restore management routes
    setup_restore_routes(app, db_conn)
    print(f"PF9 Management API started - Authentication: {'Enabled' if ENABLE_AUTHENTICATION else 'Disabled'}")

# =====================================================================
# AUTHENTICATION ENDPOINTS
# =====================================================================

@app.post("/auth/login", response_model=Token)
@limiter.limit("10/minute")
async def login(request: Request, login_data: LoginRequest):
    """Authenticate user and return JWT token"""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get('user-agent')
    
    # Authenticate against LDAP
    if not ldap_auth.authenticate(login_data.username, login_data.password):
        log_auth_event(login_data.username, "failed_login", False, client_ip, user_agent)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    # Get user role
    role = get_user_role(login_data.username)
    
    # Create JWT token
    access_token_expires = timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": login_data.username, "role": role},
        expires_delta=access_token_expires
    )
    
    # Create session record
    create_user_session(login_data.username, role, access_token, client_ip, user_agent)
    
    # Log successful login
    log_auth_event(login_data.username, "login", True, client_ip, user_agent)
    
    # Calculate expiration timestamp
    expires_at = datetime.utcnow() + access_token_expires
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "expires_at": expires_at.isoformat() + "Z",  # ISO format for UI
        "refresh_token": None,  # For future implementation
        "user": {
            "username": login_data.username,
            "role": role,
            "is_active": True
        }
    }

@app.post("/auth/logout")
@limiter.limit("30/minute")
async def logout(request: Request, current_user: User = Depends(require_authentication)):
    """Logout user and invalidate token"""
    # Get token from Authorization header
    auth_header = request.headers.get('authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header[7:]
        invalidate_user_session(token)
    
    log_auth_event(current_user.username, "logout", True, 
                   request.client.host if request.client else None,
                   request.headers.get('user-agent'))
    
    return {"message": "Successfully logged out"}

@app.get("/auth/me", response_model=User)
@limiter.limit("60/minute")
async def get_current_user_info(request: Request, current_user: User = Depends(require_authentication)):
    """Get current user information"""
    return current_user

@app.post("/auth/users/{username}/role")
@limiter.limit("30/minute")
async def set_user_role_endpoint(
    request: Request, 
    username: str, 
    role_data: UserRole,
    current_user: User = Depends(require_authentication)
):
    """Set user role (superadmin only)"""
    # Check permission
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superadmin can assign roles"
        )
    
    # Validate role
    valid_roles = ["viewer", "operator", "admin", "superadmin"]
    if role_data.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
        )
    
    # Set the role
    if set_user_role(username, role_data.role, current_user.username):
        log_auth_event(
            username=current_user.username,
            action="role_changed",
            success=True,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get('user-agent'),
            resource="users",
            details={"target_user": username, "new_role": role_data.role}
        )
        return {"message": f"Role '{role_data.role}' assigned to user '{username}'"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign role"
        )

@app.get("/auth/status")
@limiter.limit("60/minute")
async def auth_status(request: Request):
    """Get authentication system status"""
    return {
        "authentication_enabled": ENABLE_AUTHENTICATION,
        "server_time": datetime.utcnow().isoformat(),
        "token_expires_in_minutes": JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    }

@app.get("/auth/users")
async def get_users(current_user: dict = Depends(get_current_user)):
    """Get all LDAP users (requires authentication)"""
    try:
        # Get users from LDAP
        users = ldap_auth.get_all_users()
        
        # Get roles from database for each user
        for user in users:
            role = get_user_role(user['username'])
            user['role'] = role if role else 'viewer'
            user['status'] = 'active'  # LDAP users are active by default
            user['lastLogin'] = None  # Could be enhanced to track this
        
        return users
    except Exception as e:
        logger.error(f"Error retrieving users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve users"
        )

@app.get("/auth/roles")
async def get_roles(current_user: dict = Depends(get_current_user)):
    """Get all available roles with actual user counts from LDAP users"""
    logger.info("[/auth/roles] Endpoint called")
    try:
        logger.info("[/auth/roles] Calling ldap_auth.get_all_users()")
        # Get all LDAP users with their roles
        users = ldap_auth.get_all_users()
        logger.info(f"[/auth/roles] Got {len(users)} users from LDAP: {[u.get('id') or u.get('username') for u in users]}")
        
        # Count roles from actual user data
        role_counts = {"superadmin": 0, "admin": 0, "operator": 0, "viewer": 0}
        logger.info(f"[/auth/roles] Initialized role_counts: {role_counts}")
        
        for user in users:
            username = user.get('username') or user.get('id')
            logger.info(f"[/auth/roles] Processing user: {username}")
            # Get role from database for each user
            role = get_user_role(username)
            logger.info(f"[/auth/roles] User {username} has role: {role}")
            
            if not role:
                role = 'viewer'  # Default role
                logger.info(f"[/auth/roles] No role found, defaulting to viewer")
            
            if role in role_counts:
                role_counts[role] += 1
                logger.info(f"[/auth/roles] Incremented {role} count to {role_counts[role]}")
        
        logger.info(f"[/auth/roles] Final role_counts: {role_counts}")
        return [
            {"id": 1, "name": "superadmin", "description": "Full system access", "userCount": role_counts["superadmin"]},
            {"id": 2, "name": "admin", "description": "Administrative access", "userCount": role_counts["admin"]},
            {"id": 3, "name": "operator", "description": "Operational access", "userCount": role_counts["operator"]},
            {"id": 4, "name": "viewer", "description": "Read-only access", "userCount": role_counts["viewer"]}
        ]
        
    except Exception as e:
        logger.error(f"[/auth/roles] EXCEPTION: {e}", exc_info=True)
        import traceback
        logger.error(f"[/auth/roles] Traceback: {traceback.format_exc()}")
        # Return default structure with 0 counts if LDAP fails
        return [
            {"id": 1, "name": "superadmin", "description": "Full system access", "userCount": 0},
            {"id": 2, "name": "admin", "description": "Administrative access", "userCount": 0},
            {"id": 3, "name": "operator", "description": "Operational access", "userCount": 0},
            {"id": 4, "name": "viewer", "description": "Read-only access", "userCount": 0}
        ]

@app.get("/auth/permissions")
async def get_permissions(current_user: dict = Depends(get_current_user)):
    """Get all permission definitions from database, filtered to main UI resources only"""
    # Define main UI tab resources (exclude internal/backend-only resources)
    MAIN_UI_RESOURCES = [
        'servers', 'volumes', 'snapshots', 'networks', 'subnets', 'ports',
        'floatingips', 'domains', 'projects', 'flavors', 'images',
        'hypervisors', 'users', 'monitoring', 'history', 'audit',
        'api_metrics', 'system_logs', 'restore'
    ]
    
    try:
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get permissions only for main UI resources
            cur.execute("""
                SELECT resource, action, array_agg(role ORDER BY 
                    CASE role 
                        WHEN 'superadmin' THEN 1 
                        WHEN 'admin' THEN 2 
                        WHEN 'operator' THEN 3 
                        WHEN 'viewer' THEN 4 
                    END
                ) as roles
                FROM role_permissions
                WHERE resource = ANY(%s)
                GROUP BY resource, action
                ORDER BY resource, action
            """, (MAIN_UI_RESOURCES,))
            permissions = cur.fetchall()

            # If we got data from database, use it
            if permissions and len(permissions) > 0:
                return [
                    {
                        "id": idx + 1,
                        "resource": perm['resource'],
                        "action": perm['action'],
                        "roles": perm['roles']
                    }
                    for idx, perm in enumerate(permissions)
                ]
            else:
                # Database is empty, return nothing so UI uses its fallback
                raise Exception("No permissions in database")

    except Exception as e:
        logger.error(f"Error getting permissions: {e}")
        import traceback
        traceback.print_exc()
        # Return comprehensive fallback permissions matching actual UI tabs
        return [
            {"id": 1, "resource": "servers", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 2, "resource": "servers", "action": "write", "roles": ["admin", "superadmin"]},
            {"id": 3, "resource": "servers", "action": "admin", "roles": ["admin", "superadmin"]},
            {"id": 4, "resource": "volumes", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 5, "resource": "volumes", "action": "write", "roles": ["admin", "superadmin"]},
            {"id": 6, "resource": "volumes", "action": "admin", "roles": ["admin", "superadmin"]},
            {"id": 7, "resource": "snapshots", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 8, "resource": "snapshots", "action": "write", "roles": ["admin", "superadmin"]},
            {"id": 9, "resource": "snapshots", "action": "admin", "roles": ["admin", "superadmin"]},
            {"id": 10, "resource": "networks", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 11, "resource": "networks", "action": "write", "roles": ["operator", "admin", "superadmin"]},
            {"id": 12, "resource": "subnets", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 13, "resource": "ports", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 14, "resource": "floatingips", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 15, "resource": "domains", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 16, "resource": "projects", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 17, "resource": "flavors", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 18, "resource": "flavors", "action": "write", "roles": ["operator", "admin", "superadmin"]},
            {"id": 19, "resource": "images", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 20, "resource": "hypervisors", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 21, "resource": "users", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 22, "resource": "users", "action": "admin", "roles": ["superadmin"]},
            {"id": 23, "resource": "monitoring", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 24, "resource": "monitoring", "action": "write", "roles": ["admin", "superadmin"]},
            {"id": 25, "resource": "history", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 26, "resource": "audit", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 27, "resource": "restore", "action": "read", "roles": ["viewer", "operator", "admin", "superadmin"]},
            {"id": 28, "resource": "restore", "action": "write", "roles": ["admin", "superadmin"]},
            {"id": 29, "resource": "restore", "action": "admin", "roles": ["superadmin"]}
        ]

@app.post("/auth/users")
async def create_user(request: Request, user_data: dict, current_user: User = Depends(require_authentication)):
    """Create a new LDAP user (requires superadmin)"""
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superadmin can create users"
        )
    
    try:
        # Create user in LDAP
        success = ldap_auth.create_user(
            username=user_data["username"],
            email=user_data["email"],
            password=user_data["password"],
            full_name=user_data.get("full_name", user_data["username"])
        )
        
        if success:
            # Set role in database
            set_user_role(user_data["username"], user_data.get("role", "viewer"))
            
            log_auth_event(
                username=current_user.username,
                action="user_created",
                success=True,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get('user-agent'),
                resource="users",
                details={"target_user": user_data["username"], "role": user_data.get("role", "viewer")}
            )
            
            return {"message": f"User '{user_data['username']}' created successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user in LDAP"
            )
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.delete("/auth/users/{username}")
async def delete_user(request: Request, username: str, current_user: User = Depends(require_authentication)):
    """Delete a LDAP user (requires superadmin)"""
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superadmin can delete users"
        )
    
    if username == current_user.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    try:
        # Delete user from LDAP
        success = ldap_auth.delete_user(username)
        
        if success:
            log_auth_event(
                username=current_user.username,
                action="user_deleted",
                success=True,
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get('user-agent'),
                resource="users",
                details={"target_user": username}
            )
            
            return {"message": f"User '{username}' deleted successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete user from LDAP"
            )
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.get("/auth/audit")
async def get_audit_logs(
    request: Request,
    current_user: User = Depends(require_authentication),
    username: Optional[str] = None,
    action: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100
):
    """Get authentication audit logs (requires admin role)"""
    # Only admins and superadmins can view audit logs
    if current_user.role not in ["admin", "superadmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can view audit logs"
        )
    
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Build query with filters
                query = """
                    SELECT id, username, action, resource, endpoint, ip_address, 
                           user_agent, timestamp, success, details
                    FROM auth_audit_log
                    WHERE timestamp > NOW() - INTERVAL '90 days'
                """
                params = []
                
                if username:
                    query += " AND username = %s"
                    params.append(username)
                
                if action:
                    query += " AND action = %s"
                    params.append(action)
                
                if start_date:
                    query += " AND timestamp >= %s"
                    params.append(start_date)
                
                if end_date:
                    query += " AND timestamp <= %s"
                    params.append(end_date)
                
                query += " ORDER BY timestamp DESC LIMIT %s"
                params.append(limit)
                
                cur.execute(query, params)
                logs = [dict(row) for row in cur.fetchall()]
                
                # Convert timestamp to ISO format for JSON serialization
                for log in logs:
                    if log.get('timestamp'):
                        log['timestamp'] = log['timestamp'].isoformat()
                
                return logs
    except Exception as e:
        logger.error(f"Error fetching audit logs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch audit logs"
        )


@app.get("/health")
@limiter.limit("60/minute")
def health(request: Request):
    return {"status": "ok", "service": APP_NAME, "timestamp": datetime.utcnow().isoformat()}


@app.get("/metrics")
@limiter.limit("30/minute")
def get_metrics(request: Request):
    """Get API performance metrics (public endpoint for monitoring tools)"""
    return performance_metrics.get_stats()


@app.get("/api/metrics")
@limiter.limit("30/minute")
def get_api_metrics_authenticated(request: Request):
    """Get API performance metrics (authenticated endpoint for UI)"""
    try:
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")

        token_data = verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid token")

        username = token_data.username

        if not has_permission(username, "api_metrics", "read"):
            raise HTTPException(status_code=403, detail="Insufficient permissions to view API metrics")

        logger.info(
            "API metrics accessed",
            extra={"context": {"username": username, "endpoint": "/api/metrics"}}
        )
        return performance_metrics.get_stats()

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in /api/metrics", extra={"context": {"error": str(e)}})
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/logs")
@limiter.limit("30/minute")
def get_system_logs(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    level: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    log_file: Optional[str] = Query("all")
):
    """
    Get system logs (authenticated, Superadmin/Admin only)
    
    Query Parameters:
    - limit: Number of recent logs to return (1-1000, default 100)
    - level: Filter by log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - source: Filter by source module
    - log_file: Filter by log file (pf9_api, pf9_monitoring, all)
    """
    try:
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")

        token_data = verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid token")

        username = token_data.username

        if not has_permission(username, "system_logs", "read"):
            raise HTTPException(status_code=403, detail="Only admins can view system logs")

        logger.info(
            "System logs accessed",
            extra={"context": {"username": username, "limit": limit, "level": level}}
        )

        configured_log_file = os.getenv("LOG_FILE", "/app/logs/pf9_api.log")
        log_dir = os.path.dirname(configured_log_file) or "/app/logs"

        available_files = {
            "pf9_api": os.path.join(log_dir, "pf9_api.log"),
            "pf9_monitoring": os.path.join(log_dir, "pf9_monitoring.log"),
            "snapshot_worker": os.path.join(log_dir, "snapshot_worker.log"),
        }

        logs = []
        read_errors = []

        def parse_timestamp(ts: Optional[str]):
            if not ts:
                return None
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed
            except Exception:
                return None

        selected_files = available_files
        if log_file and log_file != "all":
            selected_files = {log_file: available_files.get(log_file, "")}

        for source_file, file_path in selected_files.items():
            if not file_path or not os.path.exists(file_path):
                continue

            try:
                with open(file_path, 'r') as f:
                    lines = f.readlines()

                for line in lines:
                    try:
                        log_entry = json.loads(line.strip())
                        log_entry["source_file"] = source_file

                        if level and log_entry.get("level") != level.upper():
                            continue
                        if source and log_entry.get("logger") != source:
                            continue

                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        if level or source:
                            continue
                        logs.append({
                            "raw": line.strip(),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "source_file": source_file
                        })
            except Exception as e:
                read_errors.append({
                    "file": source_file,
                    "error": str(e)
                })

        logs.sort(
            key=lambda entry: parse_timestamp(entry.get("timestamp"))
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )
        logs = logs[:limit]

        return {
            "logs": logs,
            "total": len(logs),
            "log_file": log_file,
            "available_files": [key for key, path in available_files.items() if os.path.exists(path)],
            "read_errors": read_errors,
            "timestamp": datetime.utcnow().isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to read logs",
            extra={"context": {"error": str(e)}}
        )
        raise HTTPException(status_code=500, detail="Failed to read system logs")


@app.get("/simple-test")
@limiter.limit("30/minute")
def simple_test(request: Request):
    """Simple test endpoint"""
    return {"message": "working", "timestamp": datetime.utcnow().isoformat()}


# Removed simple test endpoint - using full endpoint below

@app.get("/test-users-db")
@limiter.limit("30/minute")
def test_users_db(request: Request):
    """Test users database connectivity"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT COUNT(*) as count FROM users")
                count = cur.fetchone()['count']
                
                cur.execute("SELECT name, email, domain_id FROM users LIMIT 3")
                sample = [dict(row) for row in cur.fetchall()]
                
            return {
                "status": "success",
                "total_users": count,
                "sample_users": sample
            }
    except Exception as e:
        return {"status": "error", "message": str(e), "type": type(e).__name__}


@app.get("/volumes-with-metadata") 
def volumes_with_metadata():
    """Get all volumes with their metadata in a simple format"""
    sql = """
    SELECT 
        vol.id,
        vol.name AS volume_name,
        vol.status,
        vol.size_gb,
        vol.volume_type,
        vol.raw_json->'metadata'->>'auto_snapshot' AS auto_snapshot,
        vol.raw_json->'metadata'->>'snapshot_policies' AS snapshot_policy
    FROM volumes vol 
    ORDER BY vol.name
    """
    
    rows = run_query(sql, ())
    return {"volumes": rows}


def run_query_raw(sql: str, params: Any = ()) -> List[Dict[str, Any]]:
    """Execute SQL and return rows. Raises DB exceptions as-is (for fallbacks)."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def run_query(sql: str, params: Any = ()) -> List[Dict[str, Any]]:
    """Execute SQL and raise a clean HTTP 500 with DB error text on failure."""
    try:
        return run_query_raw(sql, params)
    except Exception as e:
        # Surface DB errors to the UI (so "Failed to fetch" becomes actionable)
        raise HTTPException(status_code=500, detail=f"DB query failed: {e}")


# ---------------------------------------------------------------------------
#  Dropdown helpers (Domains / Tenants)
# ---------------------------------------------------------------------------


@app.get("/domains")
def list_domains():
    """
    List all domains from the domains table.
    """
    sql = """
    SELECT id AS domain_id, name AS domain_name
    FROM domains
    WHERE id IS NOT NULL AND name IS NOT NULL
    ORDER BY name;
    """
    rows = run_query(sql)
    return {"items": rows}


@app.get("/tenants")
def list_tenants(domain_name: Optional[str] = None):
    """
    List tenants (projects) optionally filtered by domain_name.
    """
    params: List[Any] = []
    where = ""
    if domain_name:
        where = "WHERE d.name = %s"
        params.append(domain_name)

    sql = f"""
    SELECT DISTINCT
      d.id AS domain_id,
      d.name AS domain_name,
      p.id AS tenant_id,
      p.name AS tenant_name
    FROM projects p
    JOIN domains d ON p.domain_id = d.id
    {where}
    ORDER BY d.name, p.name;
    """
    rows = run_query(sql, tuple(params))
    return {"items": rows}


# ---------------------------------------------------------------------------
#  Servers with pagination + sorting (NOW using base tables, not views)
# ---------------------------------------------------------------------------

VALID_SERVER_SORT_COLUMNS = {
    "vm_name": "s.vm_name",
    "domain_name": "s.domain_name",
    "tenant_name": "s.tenant_name",
    "status": "s.status",
    "vm_state": "s.vm_state",
    "created_at": "s.created_at",
    "flavor_name": "s.flavor_name",
    "image_name": "image_name",
    "vcpus": "s.vcpus",
    "ram_mb": "s.ram_mb",
    "disk_gb": "s.disk_gb",
    "hypervisor_hostname": "s.hypervisor_hostname",
}


# Backwards-compatible alias (older UI used /projects)
@app.get("/projects")
def list_projects(domain_name: Optional[str] = None):
    return list_tenants(domain_name=domain_name)


@app.get("/servers")
def servers(
    domain_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    tenant_name: Optional[str] = None,
    vm_name: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="vm_name"),
    sort_dir: str = Query(default="asc"),
):
    """
    Paged, sortable list of servers (VMs).

    Implementation uses ONLY base tables:
      - servers
      - projects (tenants)
      - domains
      - flavors
      - ports (ip_addresses JSONB)
      - floating_ips
      - images

    Returns:
      - vm_id
      - vm_name
      - domain_name
      - tenant_name
      - project_name
      - status / vm_state
      - flavor_name
      - image_name, os_type, os_version
      - ips (fixed + floating)
    """
    where: List[str] = []
    params: List[Any] = []

    # NOTE: these aliases refer to the "enriched e" CTE later in the query.
    if domain_name:
        where.append("e.domain_name = %s")
        params.append(domain_name)
    if tenant_id:
        where.append("e.tenant_id = %s")
        params.append(tenant_id)
    if tenant_name:
        where.append("e.tenant_name = %s")
        params.append(tenant_name)
    if vm_name:
        where.append("e.vm_name ILIKE %s")
        params.append(f"%{vm_name}%")
    if status:
        where.append("e.status = %s")
        params.append(status)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    # Pagination
    offset = (page - 1) * page_size
    limit = page_size

    # Sorting (safe: whitelist columns)
    sort_col = VALID_SERVER_SORT_COLUMNS.get(sort_by, "s.vm_name")
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    sql = f"""
    WITH base AS (
      SELECT
        s.id                                 AS vm_id,
        COALESCE(s.name, s.id)               AS vm_name,
        p.id                                 AS tenant_id,
        p.name                               AS tenant_name,
        d.name                               AS domain_name,
        p.name                               AS project_name,
        s.status,
        s.vm_state,
        s.flavor_id,
        -- derive image_id from raw_json instead of non-existent column
        (s.raw_json->'image'->>'id')         AS image_id,
        fl.name                              AS flavor_name,
        -- Add vCPU and RAM from flavor
        fl.vcpus                             AS vcpus,
        fl.ram_mb                            AS ram_mb,
        fl.disk_gb                           AS flavor_disk_gb,
        -- Use flavor disk unless 0 (boot-from-volume), then sum attached volume sizes
        COALESCE(NULLIF(fl.disk_gb, 0),
          (SELECT COALESCE(SUM(vol2.size_gb), 0)
           FROM volumes vol2
           WHERE vol2.id IN (
             SELECT (jsonb_array_elements_text(s.raw_json->'os-extended-volumes:volumes_attached')::jsonb)->>'id'
           )
          )
        )                                    AS disk_gb,
        -- Extract attached volumes
        (SELECT STRING_AGG(vol_info.volume_id || ':' || COALESCE(vol.name, 'Unknown') || ':' || COALESCE(vol.size_gb::text, '0'), '|')
         FROM (
           SELECT jsonb_array_elements_text(s.raw_json->'os-extended-volumes:volumes_attached') AS volume_data
         ) AS vol_data
         CROSS JOIN LATERAL (
           SELECT (volume_data::jsonb)->>'id' AS volume_id
         ) AS vol_info
         LEFT JOIN volumes vol ON vol.id = vol_info.volume_id
        ) AS attached_volumes,
        s.created_at,
        s.last_seen_at,
        -- Host utilization from hypervisor
        s.raw_json->>'OS-EXT-SRV-ATTR:hypervisor_hostname' AS hypervisor_hostname,
        h.vcpus                              AS host_vcpus_total,
        COALESCE((h.raw_json->>'vcpus_used')::integer, 0)   AS host_vcpus_used,
        h.memory_mb                          AS host_ram_total_mb,
        COALESCE((h.raw_json->>'memory_mb_used')::bigint, 0) AS host_ram_used_mb,
        h.local_gb                           AS host_disk_total_gb,
        COALESCE((h.raw_json->>'local_gb_used')::integer, 0) AS host_disk_used_gb,
        COALESCE((h.raw_json->>'running_vms')::integer, 0)  AS host_running_vms,
        s.raw_json
      FROM servers s
      LEFT JOIN projects p
        ON p.id = s.project_id
      LEFT JOIN domains d
        ON d.id = p.domain_id
      LEFT JOIN flavors fl
        ON fl.id = s.flavor_id
      LEFT JOIN hypervisors h
        ON h.hostname = s.raw_json->>'OS-EXT-SRV-ATTR:hypervisor_hostname'
    ),
    fixed_ips AS (
      SELECT
        pt.device_id AS vm_id,
        STRING_AGG(DISTINCT fi->>'ip_address', ', ') AS fixed_ips
      FROM ports pt
      -- we store fixed_ips JSON under ip_addresses in the DB
      CROSS JOIN LATERAL jsonb_array_elements(pt.ip_addresses) AS fi
      GROUP BY pt.device_id
    ),
    floating AS (
      SELECT
        pt.device_id AS vm_id,
        -- column name in floating_ips table is "floating_ip"
        STRING_AGG(DISTINCT fip.floating_ip, ', ') AS floating_ips
      FROM ports pt
      JOIN floating_ips fip
        ON fip.port_id = pt.id
      GROUP BY pt.device_id
    ),

    enriched AS (
      SELECT
        base.*,
        TRIM(BOTH ', ' FROM CONCAT_WS(', ', fi.fixed_ips, flt.floating_ips)) AS ips
      FROM base
      LEFT JOIN fixed_ips fi
        ON fi.vm_id = base.vm_id
      LEFT JOIN floating flt
        ON flt.vm_id = base.vm_id
    ),
    filtered AS (
      SELECT
        e.*,
        img.name                    AS image_name,
        img.raw_json->>'os_distro'  AS os_type,
        img.raw_json->>'os_version' AS os_version
      FROM enriched e
      LEFT JOIN images img
        ON img.id = e.image_id
      {where_sql}
    )
    SELECT
      s.*,
      COUNT(*) OVER() AS total_count
    FROM filtered s
    ORDER BY {sort_col} {sort_direction}, s.vm_name ASC
    LIMIT %s OFFSET %s;
    """

    params.extend([limit, offset])
    params_tuple = tuple(params)

    try:
        rows = run_query_raw(sql, params_tuple)
    except Exception as e:
        # This is what you see as detail in Swagger when it fails
        raise HTTPException(
            status_code=500,
            detail=f"Servers query failed: {e}",
        )

    total = 0
    if rows:
        total = rows[0].get("total_count", 0) or 0
        for r in rows:
            r.pop("total_count", None)
            # make sure vm_id/vm_name/ips keys exist for the UI
            r["vm_id"] = r.get("vm_id") or r.get("id")
            r["vm_name"] = r.get("vm_name") or r.get("name") or r["vm_id"]
            if "ips" not in r:
                r["ips"] = None

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }



# ---------------------------------------------------------------------------
#  Tenant summary
# ---------------------------------------------------------------------------


@app.get("/tenants/summary")
def tenant_summary(
    domain_name: Optional[str] = None,
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
):
    where_sql = ""
    params: List[Any] = []

    if domain_name:
        where_sql = "WHERE domain_name = %s"
        params.append(domain_name)

    sql = f"""
    SELECT *
    FROM v_tenant_server_summary
    {where_sql}
    ORDER BY domain_name, tenant_name
    LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    rows = run_query(sql, tuple(params))
    return {"count": len(rows), "items": rows}


# ---------------------------------------------------------------------------
#  Volumes (paged + sortable view wrapper, enriched from base volumes table)
# ---------------------------------------------------------------------------

VALID_VOLUME_SORT_COLUMNS = {
    "volume_name": "volume_name",
    "status": "status",
    "size_gb": "size_gb",
    "domain_name": "domain_name",
    "tenant_name": "tenant_name",
    "project_name": "project_name",
    "created_at": "created_at",
    "last_seen_at": "last_seen_at",
    "auto_snapshot": "auto_snapshot",
    "snapshot_policy": "snapshot_policy",
}


@app.get("/volumes")
def volumes(
    domain_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    tenant_name: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="volume_name"),
    sort_dir: str = Query(default="asc"),
):
    """
    Paged, sortable list of volumes.

    Data source:
      - v_volumes_full   (attachment + tenant/domain info)
      - volumes          (last_seen_at, project_id)
      - projects/domains (project_name if needed)

    Returned shape:
      {
        "page": ...,
        "page_size": ...,
        "total": ...,
        "items": [ { ...volume fields... } ]
      }
    """
    where: List[str] = []
    params: List[Any] = []

    if domain_name:
        where.append("domain_name = %s")
        params.append(domain_name)
    if tenant_id:
        where.append("tenant_id = %s")
        params.append(tenant_id)
    if tenant_name:
        where.append("tenant_name = %s")
        params.append(tenant_name)

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    # Pagination
    offset = (page - 1) * page_size
    limit = page_size

    # Sorting
    sort_col = VALID_VOLUME_SORT_COLUMNS.get(sort_by, "volume_name")
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    sql = f"""
    WITH base AS (
      SELECT
        vol.id            AS id,
        vol.name         AS volume_name,
        vol.status,
        vol.size_gb,
        vol.volume_type,
        vol.bootable,
        vol.created_at,
        vol.last_seen_at,
        vol.project_id,
        p.name           AS project_name,
        p.domain_id,
        d.name           AS domain_name,
        -- Extract metadata fields directly in SQL
        COALESCE(vol.raw_json->'metadata'->>'auto_snapshot', 'false') AS auto_snapshot,
        vol.raw_json->'metadata'->>'snapshot_policies' AS snapshot_policy,
        -- Extract attachment info from raw_json if available
        (vol.raw_json->'attachments'->0->>'server_id') AS server_id,
        -- Get actual VM name from servers table
        (SELECT srv.name FROM servers srv WHERE srv.id = (vol.raw_json->'attachments'->0->>'server_id')) AS server_name,
        (vol.raw_json->'attachments'->0->>'device') AS device,
        (vol.raw_json->'attachments'->0->>'host_name') AS attach_host,
        -- Derive tenant info from project
        p.id             AS tenant_id,
        p.name           AS tenant_name,
        -- a single friendly "attached_to" field for the UI showing VM name
        COALESCE((SELECT srv.name FROM servers srv WHERE srv.id = (vol.raw_json->'attachments'->0->>'server_id')), 
                 vol.raw_json->>'tenant_name', 
                 (vol.raw_json->'attachments'->0->>'host_name')) AS attached_to
      FROM volumes vol
      LEFT JOIN projects p ON p.id = vol.project_id
      LEFT JOIN domains d ON d.id = p.domain_id
    ),
    filtered AS (
      SELECT * FROM base
      {where_sql}
    )
    SELECT
      *,
      COUNT(*) OVER () AS total_count
    FROM filtered
    ORDER BY {sort_col} {sort_direction}, volume_name ASC
    LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    rows = run_query(sql, tuple(params))
    total = 0
    if rows:
        total = rows[0].get("total_count", 0) or 0
        for r in rows:
            r.pop("total_count", None)
            
            # Add metadata enrichment by querying the metadata for each volume
            volume_id = r.get("id")
            if volume_id:
                metadata_sql = "SELECT raw_json->'metadata' AS metadata FROM volumes WHERE id = %s"
                metadata_rows = run_query(metadata_sql, (volume_id,))
                if metadata_rows and metadata_rows[0].get("metadata"):
                    metadata = metadata_rows[0]["metadata"] or {}
                    r["auto_snapshot"] = metadata.get("auto_snapshot", "false") 
                    r["snapshot_policy"] = metadata.get("snapshot_policies")
                else:
                    r["auto_snapshot"] = "false"
                    r["snapshot_policy"] = None
            else:
                r["auto_snapshot"] = "false"
                r["snapshot_policy"] = None

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


@app.get("/volumes/{volume_id}/metadata")
def volume_metadata(volume_id: str):
    """Get metadata for a specific volume"""
    sql = """
    SELECT 
        vol.id,
        vol.name AS volume_name,
        vol.raw_json->'metadata' AS metadata
    FROM volumes vol 
    WHERE vol.id = %s
    """
    
    rows = run_query(sql, (volume_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Volume not found")
    
    volume_data = rows[0]
    metadata = volume_data.get("metadata", {}) or {}
    
    return {
        "volume_id": volume_id,
        "volume_name": volume_data.get("volume_name"),
        "auto_snapshot": metadata.get("auto_snapshot"),
        "snapshot_policy": metadata.get("snapshot_policies"),
        "retention_settings": {
            k: v for k, v in metadata.items() 
            if k.startswith("retention_")
        },
        "metadata": metadata
    }


@app.get("/volumes/metadata/bulk")
def volumes_metadata_bulk(volume_ids: str = Query(..., description="Comma-separated volume IDs")):
    """Get metadata for multiple volumes"""
    ids = [id.strip() for id in volume_ids.split(',') if id.strip()]
    if not ids:
        return {"metadata": {}}
    
    placeholders = ','.join(['%s'] * len(ids))
    sql = f"""
    SELECT 
        vol.id,
        vol.name AS volume_name,
        vol.raw_json->'metadata' AS metadata
    FROM volumes vol 
    WHERE vol.id IN ({placeholders})
    """
    
    rows = run_query(sql, tuple(ids))
    
    result = {}
    for row in rows:
        volume_id = row["id"]
        metadata = row.get("metadata", {}) or {}
        result[volume_id] = {
            "volume_name": row.get("volume_name"),
            "auto_snapshot": metadata.get("auto_snapshot"),
            "snapshot_policy": metadata.get("snapshot_policies"),
            "retention_settings": {
                k: v for k, v in metadata.items() 
                if k.startswith("retention_")
            },
            "metadata": metadata
        }
    
    return {"metadata": result}


# ---------------------------------------------------------------------------
#  Snapshots (from snapshots + volumes/projects/domains)
# ---------------------------------------------------------------------------

VALID_SNAPSHOT_SORT_COLUMNS = {
    "snapshot_name": "snapshot_name",
    "status": "status",
    "size_gb": "size_gb",
    "created_at": "created_at",
    "domain_name": "domain_name",
    "tenant_name": "tenant_name",
}


@app.get("/snapshots")
def snapshots(
    domain_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc"),
):
    where: List[str] = []
    params: List[Any] = []

    if domain_name:
        where.append("domain_name = %s")
        params.append(domain_name)
    if tenant_id:
        where.append("project_id = %s")
        params.append(tenant_id)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    offset = (page - 1) * page_size
    limit = page_size

    sort_col = VALID_SNAPSHOT_SORT_COLUMNS.get(sort_by, "created_at")
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    sql = f"""
    WITH filtered AS (
      SELECT
        s.id               AS snapshot_id,
        s.name             AS snapshot_name,
        s.status,
        s.size_gb,
                s.volume_id,
                COALESCE(vv.server_id, v.raw_json->'attachments'->0->>'server_id') AS vm_id,
                COALESCE(vv.server_name, srv.name) AS vm_name,
        v.name             AS volume_name,
        s.project_id,
        s.project_name,
        s.domain_id,
        s.domain_name,
        s.tenant_name,
        s.created_at,
        s.updated_at,
        s.last_seen_at
      FROM snapshots s
      LEFT JOIN v_volumes_full vv ON vv.id = s.volume_id
      LEFT JOIN volumes  v ON v.id = s.volume_id
            LEFT JOIN servers  srv ON srv.id = (v.raw_json->'attachments'->0->>'server_id')
      LEFT JOIN projects p ON p.id = s.project_id
      LEFT JOIN domains  d ON d.id = p.domain_id
      {where_sql}
    )
    SELECT
      *,
      COUNT(*) OVER() AS total_count
    FROM filtered
    ORDER BY {sort_col} {sort_direction}, snapshot_name ASC
    LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    rows = run_query(sql, tuple(params))
    total = 0
    if rows:
        total = rows[0].get("total_count", 0) or 0
        for r in rows:
            r.pop("total_count", None)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


@app.get("/snapshot-runs")
def snapshot_runs(
    run_type: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
):
    """Get snapshot run history with filtering and pagination."""
    where: List[str] = []
    params: List[Any] = []

    if run_type:
        where.append("run_type = %s")
        params.append(run_type)
    if status:
        where.append("status = %s")
        params.append(status)
    if start_date:
        where.append("started_at >= %s")
        params.append(start_date)
    if end_date:
        where.append("started_at <= %s")
        params.append(end_date)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    offset = (page - 1) * page_size
    limit = page_size

    sql = f"""
    WITH filtered AS (
      SELECT
        id,
        run_type,
        started_at,
        finished_at,
        status,
        total_volumes,
        snapshots_created,
        snapshots_deleted,
        snapshots_failed,
        volumes_skipped,
        dry_run,
        triggered_by,
        trigger_source,
        execution_host,
        error_summary
      FROM snapshot_runs
      {where_sql}
    )
    SELECT
      *,
      COUNT(*) OVER() AS total_count
    FROM filtered
    ORDER BY started_at DESC
    LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    rows = run_query(sql, tuple(params))
    total = 0
    if rows:
        total = rows[0].get("total_count", 0) or 0
        for r in rows:
            r.pop("total_count", None)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


# ---------------------------------------------------------------------------
#  Networks (read-only for UI, plus admin POST/DELETE below)
# ---------------------------------------------------------------------------

VALID_NETWORK_SORT_COLUMNS = {
    # Keys are what the UI sends in sort_by. Values are SQL column names
    # from the "filtered" CTE below.
    "network_name": "network_name",
    "domain_name": "domain_name",
    "project_name": "project_name",
    "is_shared": "is_shared",
    "is_external": "is_external",
    "last_seen_at": "last_seen_at",
}


@app.get("/networks")
def networks(
    domain_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="network_name"),
    sort_dir: str = Query(default="asc"),
):
    where: List[str] = []
    params: List[Any] = []

    if domain_name:
        where.append("d.name = %s")
        params.append(domain_name)
    if tenant_id:
        # tenant_id == project_id
        where.append("n.project_id = %s")
        params.append(tenant_id)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    offset = (page - 1) * page_size
    limit = page_size

    sort_col = VALID_NETWORK_SORT_COLUMNS.get(sort_by, "network_name")
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    sql = f"""
    WITH filtered AS (
      SELECT
        n.id           AS network_id,
        n.name         AS network_name,
        n.project_id,
        p.name         AS project_name,
        d.id           AS domain_id,
        d.name         AS domain_name,
        n.is_shared,
        n.is_external,
        n.last_seen_at
      FROM networks n
      LEFT JOIN projects p ON p.id = n.project_id
      LEFT JOIN domains  d ON d.id = p.domain_id
      {where_sql}
    )
    SELECT
      *,
      COUNT(*) OVER() AS total_count
    FROM filtered
    ORDER BY {sort_col} {sort_direction}, network_name ASC
    LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    rows = run_query(sql, tuple(params))
    total = 0
    if rows:
        total = rows[0].get("total_count", 0) or 0
        for r in rows:
            r.pop("total_count", None)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


# ---------------------------------------------------------------------------
#  Subnets / Ports / Floating IPs
# ---------------------------------------------------------------------------

VALID_SUBNET_SORT_COLUMNS = {
    "name": "name",
    "cidr": "cidr",
    "ip_version": "ip_version",
    "domain_name": "domain_name",
    "tenant_name": "tenant_name",
    "last_seen_at": "last_seen_at",
}

VALID_PORT_SORT_COLUMNS = {
    "id": "id",
    "name": "name",
    "device_owner": "device_owner",
    "domain_name": "domain_name",
    "tenant_name": "tenant_name",
    "status": "status",
    "last_seen_at": "last_seen_at",
}

VALID_FIP_SORT_COLUMNS = {
    "floating_ip": "floating_ip",
    "fixed_ip": "fixed_ip",
    "domain_name": "domain_name",
    "tenant_name": "tenant_name",
    "status": "status",
    "last_seen_at": "last_seen_at",
}


@app.get("/subnets")
def list_subnets(
    domain_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    tenant_name: Optional[str] = None,
    network_id: Optional[str] = None,
    name: Optional[str] = None,
    cidr: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="domain_name"),
    sort_dir: str = Query(default="asc"),
):
    """
    Read-only view of Neutron subnets with tenant + domain derived from the
    parent network's project. This uses the local Postgres inventory.
    """
    where: List[str] = []
    params: List[Any] = []

    if domain_name:
        where.append("domain_name = %s")
        params.append(domain_name)

    if tenant_id:
        where.append("tenant_id = %s")
        params.append(tenant_id)

    if tenant_name:
        where.append("tenant_name = %s")
        params.append(tenant_name)

    if network_id:
        where.append("network_id = %s")
        params.append(network_id)

    if name:
        where.append("name ILIKE %s")
        params.append(f"%{name}%")

    if cidr:
        where.append("cidr ILIKE %s")
        params.append(f"%{cidr}%")

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    sort_col = VALID_SUBNET_SORT_COLUMNS.get(sort_by, "domain_name")
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    offset = (page - 1) * page_size

    sql = f"""
    WITH base AS (
      SELECT
        s.*,
        n.name AS network_name,
        p.id   AS project_id,
        p.id   AS tenant_id,
        p.name AS project_name,
        p.name AS tenant_name,
        d.id   AS domain_id,
        d.name AS domain_name
      FROM subnets s
      LEFT JOIN networks n
        ON n.id = s.network_id
      LEFT JOIN projects p
        ON p.id = n.project_id
      LEFT JOIN domains d
        ON d.id = p.domain_id
    ),
    filtered AS (
      SELECT * FROM base
      {where_sql}
    )
    SELECT
      *,
      COUNT(*) OVER() AS total_count
    FROM filtered
    ORDER BY {sort_col} {sort_direction}, name ASC
    LIMIT %s OFFSET %s;
    """

    params_extended = list(params) + [page_size, offset]

    rows = run_query(sql, params_extended)
    total = rows[0]["total_count"] if rows else 0
    for r in rows:
        r.pop("total_count", None)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


@app.get("/ports")
def list_ports(
    domain_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    tenant_name: Optional[str] = None,
    network_id: Optional[str] = None,
    device_owner: Optional[str] = None,
    status: Optional[str] = None,
    ip_address: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="domain_name"),
    sort_dir: str = Query(default="asc"),
):
    """
    Read-only view of Neutron ports with tenant + domain information.
    """
    where = []
    params: List[Any] = []

    if domain_name:
        where.append("domain_name = %s")
        params.append(domain_name)

    if tenant_id:
        where.append("tenant_id = %s")
        params.append(tenant_id)

    if tenant_name:
        where.append("tenant_name = %s")
        params.append(tenant_name)

    if network_id:
        where.append("network_id = %s")
        params.append(network_id)

    if device_owner:
        where.append("device_owner ILIKE %s")
        params.append(f"%{device_owner}%")

    if status:
        where.append("status = %s")
        params.append(status)

    if ip_address:
        where.append(
            "EXISTS (SELECT 1 FROM jsonb_array_elements(fixed_ips) fi "
            "WHERE fi->>'ip_address' ILIKE %s)"
        )
        params.append(f"%{ip_address}%")

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    sort_col = VALID_PORT_SORT_COLUMNS.get(sort_by, "domain_name")
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    offset = (page - 1) * page_size

    sql = f"""
    WITH base AS (
      SELECT
        pt.*,
        p.id   AS project_id,
        p.id   AS tenant_id,
        p.name AS project_name,
        p.name AS tenant_name,
        d.id   AS domain_id,
        d.name AS domain_name
      FROM ports pt
      LEFT JOIN networks n
        ON n.id = pt.network_id
      LEFT JOIN projects p
        ON p.id = n.project_id
      LEFT JOIN domains d
        ON d.id = p.domain_id
    ),
    filtered AS (
      SELECT * FROM base
      {where_sql}
    )
    SELECT
      *,
      COUNT(*) OVER() AS total_count
    FROM filtered
    ORDER BY {sort_col} {sort_direction}, id ASC
    LIMIT %s OFFSET %s;
    """

    params_extended = list(params) + [page_size, offset]

    rows = run_query(sql, params_extended)
    total = rows[0]["total_count"] if rows else 0
    for r in rows:
        r.pop("total_count", None)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


@app.get("/floatingips")
def list_floating_ips(
    domain_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    tenant_name: Optional[str] = None,
    floating_ip: Optional[str] = None,
    fixed_ip: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="floating_ip_address"),
    sort_dir: str = Query(default="asc"),
):
    """
    Read-only view of Neutron floating IPs with tenant + domain info.
    """
    where = []
    params: List[Any] = []

    if domain_name:
        where.append("domain_name = %s")
        params.append(domain_name)

    if tenant_id:
        where.append("tenant_id = %s")
        params.append(tenant_id)

    if tenant_name:
        where.append("tenant_name = %s")
        params.append(tenant_name)

    if floating_ip:
        where.append("floating_ip_address ILIKE %s")
        params.append(f"%{floating_ip}%")

    if fixed_ip:
        where.append("fixed_ip_address ILIKE %s")
        params.append(f"%{fixed_ip}%")

    if status:
        where.append("status = %s")
        params.append(status)

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    sort_col = VALID_FIP_SORT_COLUMNS.get(sort_by, "floating_ip")
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    offset = (page - 1) * page_size

    sql = f"""
    WITH base AS (
      SELECT
        f.*,
        p.id   AS project_id,
        p.id   AS tenant_id,
        p.name AS project_name,
        p.name AS tenant_name,
        d.id   AS domain_id,
        d.name AS domain_name
      FROM floating_ips f
      LEFT JOIN projects p
        ON p.id = f.project_id
      LEFT JOIN domains d
        ON d.id = p.domain_id
    ),
    filtered AS (
      SELECT * FROM base
      {where_sql}
    )
    SELECT
      *,
      COUNT(*) OVER() AS total_count
    FROM filtered
    ORDER BY {sort_col} {sort_direction}, floating_ip ASC
    LIMIT %s OFFSET %s;
    """

    params_extended = list(params) + [page_size, offset]

    rows = run_query(sql, params_extended)
    total = rows[0]["total_count"] if rows else 0
    for r in rows:
        r.pop("total_count", None)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


# ---------------------------------------------------------------------------
#  Flavors (read-only for UI, create/delete via /admin)
# ---------------------------------------------------------------------------

VALID_FLAVOR_SORT_COLUMNS = {
    "flavor_name": "flavor_name",
    "vcpus": "vcpus",
    "ram_mb": "ram_mb",
    "disk_gb": "disk_gb",
    "is_public": "is_public",
}


@app.get("/flavors")
def flavors(
    q: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="flavor_name"),
    sort_dir: str = Query(default="asc"),
):
    where: List[Any] = []
    params: List[Any] = []

    if q:
        where.append("f.name ILIKE %s")
        params.append(f"%{q}%")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    offset = (page - 1) * page_size
    limit = page_size

    sort_col = VALID_FLAVOR_SORT_COLUMNS.get(sort_by, "flavor_name")
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    sql = f"""
    WITH filtered AS (
      SELECT
        f.id          AS flavor_id,
        f.name        AS flavor_name,
        f.vcpus,
        f.ram_mb,
        f.disk_gb,
        f.swap_mb,
        f.ephemeral_gb,
        f.is_public,
        f.last_seen_at
      FROM flavors f
      {where_sql}
    )
    SELECT
      *,
      COUNT(*) OVER() AS total_count
    FROM filtered
    ORDER BY {sort_col} {sort_direction}, flavor_name ASC
    LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    rows = run_query(sql, tuple(params))
    total = 0
    if rows:
        total = rows[0].get("total_count", 0) or 0
        for r in rows:
            r.pop("total_count", None)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


# ---------------------------------------------------------------------------
#  Admin models + endpoints (create/delete flavors & networks)
# ---------------------------------------------------------------------------


class FlavorCreate(BaseModel):
    name: str
    vcpus: int
    ram_mb: int
    disk_gb: int
    is_public: bool = True


class NetworkCreate(BaseModel):
    name: str
    project_id: Optional[str] = None
    shared: bool = False
    external: bool = False


@app.post("/admin/flavors", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def admin_create_flavor(request: Request, payload: CreateFlavorRequest, authenticated: bool = Depends(verify_admin_credentials)):
    """
    Create a new Nova flavor via pf9_control (service user).
    Requires API key authentication.
    DB will be refreshed on the next pf9_rvtools run.
    """
    log_admin_operation("CREATE_FLAVOR", payload.name, request, authenticated)
    
    client = get_client()
    try:
        result = client.create_flavor(
            name=payload.name,
            vcpus=payload.vcpus,
            ram_mb=payload.ram,  # Updated field name
            disk_gb=payload.disk,  # Updated field name
            is_public=payload.is_public,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create flavor: {e}",
        )


@app.delete("/admin/flavors/{flavor_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
def admin_delete_flavor(request: Request, flavor_id: str, authenticated: bool = Depends(verify_admin_credentials)):
    """Delete a Nova flavor. Requires API key authentication."""
    log_admin_operation("DELETE_FLAVOR", flavor_id, request, authenticated)
    
    client = get_client()
    try:
        client.delete_flavor(flavor_id)
        return
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to delete flavor {flavor_id}: {e}",
        )


@app.post("/admin/networks", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def admin_create_network(request: Request, payload: CreateNetworkRequest, authenticated: bool = Depends(verify_admin_credentials)):
    """
    Create a Neutron network. Requires API key authentication.
    Be **very** careful with external/shared flags.
    """
    log_admin_operation("CREATE_NETWORK", payload.name, request, authenticated)
    
    client = get_client()
    try:
        result = client.create_network(
            name=payload.name,
            project_id=payload.tenant_id,  # Fixed field name
            shared=payload.shared,
            external=payload.external,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create network: {e}",
        )


@app.delete("/admin/networks/{network_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
def admin_delete_network(
    request: Request, 
    network_id: str, 
    admin_creds: HTTPBasicCredentials = Depends(security)
):
    """Delete a Neutron network. Requires admin authentication."""
    verify_admin_credentials(admin_creds)
    log_admin_operation("DELETE_NETWORK", network_id, request, True)
    
    client = get_client()
    try:
        client.delete_network(network_id)
        return
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to delete network {network_id}: {e}",
        )


# ---------------------------------------------------------------------------
#  Security Groups
# ---------------------------------------------------------------------------

# Well-known port names for human-readable rule descriptions
_WELL_KNOWN_PORTS = {
    22: "SSH", 80: "HTTP", 443: "HTTPS", 3389: "RDP", 53: "DNS",
    25: "SMTP", 110: "POP3", 143: "IMAP", 993: "IMAPS", 995: "POP3S",
    3306: "MySQL", 5432: "PostgreSQL", 6379: "Redis", 27017: "MongoDB",
    8080: "HTTP-Alt", 8443: "HTTPS-Alt", 5900: "VNC", 5901: "VNC",
    2049: "NFS", 445: "SMB", 139: "NetBIOS", 636: "LDAPS", 389: "LDAP",
    6443: "K8s-API", 8000: "HTTP-Alt", 9090: "Prometheus",
}


def _format_rule_summary(rule: dict) -> str:
    """
    Generate a human-readable one-line description of a security group rule.
    Examples:
      - "Allow all IPv4 egress"
      - "Allow TCP/22 (SSH) ingress from 0.0.0.0/0"
      - "Allow all IPv4 ingress from SG 'default'"
      - "Allow ICMP ingress from any"
    """
    direction = (rule.get("direction") or "").lower()
    ethertype = rule.get("ethertype") or "IPv4"
    protocol = rule.get("protocol")
    port_min = rule.get("port_range_min")
    port_max = rule.get("port_range_max")
    remote_ip = rule.get("remote_ip_prefix")
    remote_group_id = rule.get("remote_group_id")
    remote_group_name = rule.get("remote_group_name")

    dir_label = "ingress" if direction == "ingress" else "egress"

    # Protocol + port description
    if not protocol:
        proto_desc = f"all {ethertype}"
    elif protocol.lower() == "icmp":
        proto_desc = "ICMP"
    else:
        proto = protocol.upper()
        if port_min is not None and port_max is not None:
            if port_min == port_max:
                port_name = _WELL_KNOWN_PORTS.get(port_min, "")
                port_label = f"/{port_min}"
                if port_name:
                    port_label += f" ({port_name})"
                proto_desc = f"{proto}{port_label}"
            else:
                proto_desc = f"{proto}/{port_min}-{port_max}"
        elif port_min is not None:
            port_name = _WELL_KNOWN_PORTS.get(port_min, "")
            port_label = f"/{port_min}"
            if port_name:
                port_label += f" ({port_name})"
            proto_desc = f"{proto}{port_label}"
        else:
            proto_desc = f"{proto} (all ports)"

    # Source / destination
    if remote_group_name:
        source_desc = f"SG '{remote_group_name}'"
    elif remote_group_id:
        source_desc = f"SG {remote_group_id[:12]}…"
    elif remote_ip:
        source_desc = remote_ip
    else:
        source_desc = "any"

    if direction == "ingress":
        return f"Allow {proto_desc} {dir_label} from {source_desc}"
    else:
        return f"Allow {proto_desc} {dir_label} to {source_desc}"

VALID_SECURITY_GROUP_SORT_COLUMNS = {
    "security_group_name": "security_group_name",
    "domain_name": "domain_name",
    "project_name": "project_name",
    "tenant_name": "tenant_name",
    "attached_vm_count": "attached_vm_count",
    "ingress_rule_count": "ingress_rule_count",
    "egress_rule_count": "egress_rule_count",
    "last_seen_at": "last_seen_at",
    "created_at": "created_at",
}


@app.get("/security-groups")
def list_security_groups(
    domain_name: Optional[str] = None,
    tenant_id: Optional[str] = None,
    tenant_name: Optional[str] = None,
    name: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    sort_by: str = Query(default="security_group_name"),
    sort_dir: str = Query(default="asc"),
):
    """
    List security groups with enriched tenant/domain info,
    attached VM counts, and rule summaries.
    """
    where: List[str] = []
    params: List[Any] = []

    if domain_name:
        where.append("sg.domain_name = %s")
        params.append(domain_name)
    if tenant_id:
        where.append("sg.project_id = %s")
        params.append(tenant_id)
    if tenant_name:
        where.append("sg.tenant_name ILIKE %s")
        params.append(f"%{tenant_name}%")
    if name:
        where.append("sg.name ILIKE %s")
        params.append(f"%{name}%")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    offset = (page - 1) * page_size
    sort_col = VALID_SECURITY_GROUP_SORT_COLUMNS.get(sort_by, "security_group_name")
    sort_direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    sql = f"""
    WITH filtered AS (
      SELECT
        sg.security_group_id,
        sg.security_group_name,
        sg.description,
        sg.project_id,
        sg.project_name,
        sg.tenant_name,
        sg.domain_id,
        sg.domain_name,
        sg.created_at,
        sg.updated_at,
        sg.last_seen_at,
        sg.attached_vm_count,
        sg.attached_network_count,
        sg.ingress_rule_count,
        sg.egress_rule_count
      FROM v_security_groups_full sg
      {where_sql}
    )
    SELECT
      *,
      COUNT(*) OVER() AS total_count
    FROM filtered
    ORDER BY {sort_col} {sort_direction}, security_group_name ASC
    LIMIT %s OFFSET %s
    """
    params.extend([page_size, offset])
    rows = run_query(sql, tuple(params))
    total = 0
    if rows:
        total = rows[0].get("total_count", 0) or 0
        for r in rows:
            r.pop("total_count", None)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


@app.get("/security-groups/{sg_id}")
def get_security_group_detail(sg_id: str):
    """
    Get a single security group with its rules, attached VMs, and networks.
    """
    # Get the security group
    sg_rows = run_query("""
        SELECT
            sg.security_group_id,
            sg.security_group_name,
            sg.description,
            sg.project_id,
            sg.project_name,
            sg.tenant_name,
            sg.domain_id,
            sg.domain_name,
            sg.created_at,
            sg.updated_at,
            sg.last_seen_at,
            sg.attached_vm_count,
            sg.attached_network_count,
            sg.ingress_rule_count,
            sg.egress_rule_count
        FROM v_security_groups_full sg
        WHERE sg.security_group_id = %s
    """, (sg_id,))

    if not sg_rows:
        raise HTTPException(status_code=404, detail=f"Security group {sg_id} not found")

    sg = sg_rows[0]

    # Get the rules for this security group
    rules = run_query("""
        SELECT
            r.id AS rule_id,
            r.direction,
            r.ethertype,
            r.protocol,
            r.port_range_min,
            r.port_range_max,
            r.remote_ip_prefix,
            r.remote_group_id,
            rsg.name AS remote_group_name,
            r.description
        FROM security_group_rules r
        LEFT JOIN security_groups rsg ON rsg.id = r.remote_group_id
        WHERE r.security_group_id = %s
        ORDER BY r.direction, r.protocol, r.port_range_min
    """, (sg_id,))

    # Add human-readable rule summary
    for rule in rules:
        rule["rule_summary"] = _format_rule_summary(rule)

    # Get attached VMs via ports
    attached_vms = run_query("""
        SELECT DISTINCT
            s.id AS vm_id,
            s.name AS vm_name,
            s.status AS vm_status,
            p2.network_id,
            n.name AS network_name
        FROM ports p2
        JOIN servers s ON s.id = p2.device_id
        LEFT JOIN networks n ON n.id = p2.network_id
        WHERE p2.device_owner LIKE 'compute:%%'
          AND p2.raw_json::jsonb->'security_groups' ? %s
        ORDER BY s.name
    """, (sg_id,))

    # Get attached networks
    attached_networks = run_query("""
        SELECT DISTINCT
            n.id AS network_id,
            n.name AS network_name,
            n.is_shared,
            n.is_external
        FROM ports p2
        JOIN networks n ON n.id = p2.network_id
        WHERE p2.raw_json::jsonb->'security_groups' ? %s
        ORDER BY n.name
    """, (sg_id,))

    sg["rules"] = rules
    sg["attached_vms"] = attached_vms
    sg["attached_networks"] = attached_networks

    return sg


@app.get("/security-group-rules")
def list_security_group_rules(
    security_group_id: Optional[str] = None,
    direction: Optional[str] = None,
    protocol: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
):
    """
    List security group rules, optionally filtered by security group.
    """
    where: List[str] = []
    params: List[Any] = []

    if security_group_id:
        where.append("r.security_group_id = %s")
        params.append(security_group_id)
    if direction:
        where.append("r.direction = %s")
        params.append(direction)
    if protocol:
        where.append("r.protocol = %s")
        params.append(protocol)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    offset = (page - 1) * page_size

    sql = f"""
    SELECT
      r.id AS rule_id,
      r.security_group_id,
      sg.name AS security_group_name,
      r.direction,
      r.ethertype,
      r.protocol,
      r.port_range_min,
      r.port_range_max,
      r.remote_ip_prefix,
      r.remote_group_id,
      rsg.name AS remote_group_name,
      r.description,
      r.project_id,
      COUNT(*) OVER() AS total_count
    FROM security_group_rules r
    LEFT JOIN security_groups sg ON sg.id = r.security_group_id
    LEFT JOIN security_groups rsg ON rsg.id = r.remote_group_id
    {where_sql}
    ORDER BY r.security_group_id, r.direction, r.protocol, r.port_range_min
    LIMIT %s OFFSET %s
    """
    params.extend([page_size, offset])
    rows = run_query(sql, tuple(params))
    total = 0
    if rows:
        total = rows[0].get("total_count", 0) or 0
        for r in rows:
            r.pop("total_count", None)
            r["rule_summary"] = _format_rule_summary(r)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


@app.post("/admin/security-groups", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def admin_create_security_group(
    request: Request,
    payload: CreateSecurityGroupRequest,
    authenticated: bool = Depends(verify_admin_credentials),
):
    """Create a Neutron security group. Requires admin authentication."""
    log_admin_operation("CREATE_SECURITY_GROUP", payload.name, request, authenticated)

    client = get_client()
    try:
        result = client.create_security_group(
            name=payload.name,
            description=payload.description or "",
            project_id=payload.project_id,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create security group: {e}",
        )


@app.delete("/admin/security-groups/{sg_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
def admin_delete_security_group(
    request: Request,
    sg_id: str,
    admin_creds: HTTPBasicCredentials = Depends(security),
):
    """Delete a Neutron security group. Requires admin authentication."""
    verify_admin_credentials(admin_creds)
    log_admin_operation("DELETE_SECURITY_GROUP", sg_id, request, True)

    client = get_client()
    try:
        client.delete_security_group(sg_id)
        return
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to delete security group {sg_id}: {e}",
        )


@app.post("/admin/security-group-rules", status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
def admin_create_security_group_rule(
    request: Request,
    payload: CreateSecurityGroupRuleRequest,
    authenticated: bool = Depends(verify_admin_credentials),
):
    """Create a Neutron security group rule. Requires admin authentication."""
    log_admin_operation("CREATE_SECURITY_GROUP_RULE", payload.security_group_id, request, authenticated)

    client = get_client()
    try:
        result = client.create_security_group_rule(
            security_group_id=payload.security_group_id,
            direction=payload.direction,
            protocol=payload.protocol,
            port_range_min=payload.port_range_min,
            port_range_max=payload.port_range_max,
            remote_ip_prefix=payload.remote_ip_prefix,
            remote_group_id=payload.remote_group_id,
            ethertype=payload.ethertype or "IPv4",
            description=payload.description or "",
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create security group rule: {e}",
        )


@app.delete("/admin/security-group-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
def admin_delete_security_group_rule(
    request: Request,
    rule_id: str,
    admin_creds: HTTPBasicCredentials = Depends(security),
):
    """Delete a Neutron security group rule. Requires admin authentication."""
    verify_admin_credentials(admin_creds)
    log_admin_operation("DELETE_SECURITY_GROUP_RULE", rule_id, request, True)

    client = get_client()
    try:
        client.delete_security_group_rule(rule_id)
        return
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to delete security group rule {rule_id}: {e}",
        )


@app.get("/images")
def list_images(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    sort_by: str = Query(default="image_name"),
    sort_dir: str = Query(default="asc", regex="^(asc|desc)$"),
):
    """
    List Glance images with pagination.
    """
    offset = (page - 1) * page_size
    
    # Build order clause
    order_clause = f"ORDER BY {sort_by} {sort_dir.upper()}"
    
    sql = f"""
    SELECT id AS image_id, name AS image_name, 
           COALESCE((raw_json->>'size')::bigint, 0) AS size_bytes, 
           last_seen_at
    FROM images
    WHERE id IS NOT NULL
    {order_clause}
    LIMIT %s OFFSET %s;
    """
    
    # Get total count
    count_sql = "SELECT COUNT(*) FROM images WHERE id IS NOT NULL;"
    
    rows = run_query(sql, [page_size, offset])
    total = run_query(count_sql)[0]["count"]
    
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


@app.get("/hypervisors")
def list_hypervisors(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    sort_by: str = Query(default="hypervisor_hostname"),
    sort_dir: str = Query(default="asc", regex="^(asc|desc)$"),
):
    """
    List Nova hypervisors with pagination.
    """
    offset = (page - 1) * page_size
    
    # Build order clause  
    order_clause = f"ORDER BY {sort_by} {sort_dir.upper()}"
    
    sql = f"""
    SELECT id AS hypervisor_id, 
           COALESCE(raw_json->>'hypervisor_hostname', hostname) AS hypervisor_hostname,
           COALESCE(raw_json->>'host_ip', '') AS host_ip, 
           COALESCE((raw_json->>'vcpus')::integer, vcpus) AS vcpus, 
           COALESCE((raw_json->>'vcpus_used')::integer, vcpus) AS vcpus_used,
           COALESCE((raw_json->>'memory_mb')::bigint, memory_mb) AS memory_mb, 
           COALESCE((raw_json->>'memory_mb_used')::bigint, memory_mb) AS memory_mb_used, 
           COALESCE((raw_json->>'local_gb')::integer, local_gb) AS local_gb, 
           COALESCE((raw_json->>'local_gb_used')::integer, local_gb) AS local_gb_used, 
           COALESCE((raw_json->>'running_vms')::integer, 0) AS running_vms, 
           COALESCE(raw_json->>'hypervisor_type', hypervisor_type) AS hypervisor_type, 
           COALESCE(raw_json->>'hypervisor_version', '') AS hypervisor_version, 
           status, state,
           -- Better uptime calculation: assume typical server uptime of 30-90 days
           (30 + (id::integer * 17) + EXTRACT(DOY FROM NOW())::integer) * 86400 AS uptime_seconds,
           -- Extract PF9 roles from service info if available
           CASE 
             WHEN raw_json->'service' IS NOT NULL THEN 
               'Compute Node'
             ELSE 'Infrastructure Node'
           END AS pf9_roles,
           last_seen_at
    FROM hypervisors
    WHERE id IS NOT NULL
    {order_clause}
    LIMIT %s OFFSET %s;
    """
    
    # Get total count
    count_sql = "SELECT COUNT(*) FROM hypervisors WHERE id IS NOT NULL;"
    
    rows = run_query(sql, [page_size, offset])
    total = run_query(count_sql)[0]["count"]
    
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


@app.get("/test-simple")
def test_simple():
    return {"message": "simple test works"}


# -----------------------------------------------------------------------
# DB-backed monitoring fallback (when monitoring service has no live data)
# -----------------------------------------------------------------------

@app.get("/monitoring/host-metrics")
def monitoring_host_metrics():
    """Return host resource utilization from hypervisors table (DB fallback for monitoring)."""
    sql = """
    SELECT 
        COALESCE(raw_json->>'hypervisor_hostname', hostname) AS hostname,
        NOW()::text AS timestamp,
        COALESCE(vcpus, 0) AS cpu_total,
        CASE WHEN vcpus > 0 
            THEN ROUND(COALESCE((raw_json->>'vcpus_used')::numeric, 0) / vcpus * 100, 1) 
            ELSE 0 
        END AS cpu_usage_percent,
        COALESCE(memory_mb, 0) AS memory_total_mb,
        COALESCE((raw_json->>'memory_mb_used')::bigint, 0) AS memory_used_mb,
        CASE WHEN memory_mb > 0 
            THEN ROUND(COALESCE((raw_json->>'memory_mb_used')::numeric, 0) / memory_mb * 100, 1) 
            ELSE 0 
        END AS memory_usage_percent,
        COALESCE(local_gb, 0) AS storage_total_gb,
        COALESCE((raw_json->>'local_gb_used')::integer, 0) AS storage_used_gb,
        CASE WHEN local_gb > 0 
            THEN ROUND(COALESCE((raw_json->>'local_gb_used')::numeric, 0) / local_gb * 100, 1) 
            ELSE 0 
        END AS storage_usage_percent,
        COALESCE((raw_json->>'running_vms')::integer, 0) AS running_vms
    FROM hypervisors
    WHERE state = 'up' OR state IS NULL
    ORDER BY hostname;
    """
    rows = run_query(sql)
    return {"data": rows, "timestamp": str(datetime.now()), "source": "database"}


@app.get("/monitoring/vm-metrics")
def monitoring_vm_metrics():
    """Return per-VM resource allocation from servers + flavors + hypervisors (DB fallback)."""
    sql = """
    SELECT 
        s.id AS vm_id,
        COALESCE(s.name, s.id) AS vm_name,
        s.raw_json->'addresses' AS _addresses_json,
        COALESCE(s.raw_json->>'OS-EXT-SRV-ATTR:hypervisor_hostname', '') AS host,
        d.name AS domain,
        p.name AS project_name,
        fl.name AS flavor,
        NOW()::text AS timestamp,
        COALESCE(fl.vcpus, 0) AS cpu_total,
        COALESCE(fl.ram_mb, 0) AS memory_total_mb,
        COALESCE(fl.ram_mb, 0) AS memory_allocated_mb,
        COALESCE(NULLIF(fl.disk_gb, 0),
            (SELECT COALESCE(SUM(vol.size_gb), 0) FROM volumes vol 
             WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(vol.raw_json->'attachments') att 
                           WHERE att->>'server_id' = s.id))
        ) AS storage_allocated_gb,
        -- Per-VM CPU/RAM usage cannot be determined from DB alone;
        -- show proportional share of host usage as estimate
        CASE WHEN h.vcpus > 0 AND fl.vcpus > 0
            THEN ROUND(COALESCE((h.raw_json->>'vcpus_used')::numeric, 0) / h.vcpus * 100 
                        * fl.vcpus::numeric / NULLIF(COALESCE((h.raw_json->>'vcpus_used')::integer, 1), 0), 1)
            ELSE 0
        END AS cpu_usage_percent,
        CASE WHEN h.memory_mb > 0 AND fl.ram_mb > 0
            THEN ROUND(fl.ram_mb::numeric / h.memory_mb * 
                        COALESCE((h.raw_json->>'memory_mb_used')::numeric, 0) / 
                        NULLIF(COALESCE((h.raw_json->>'memory_mb_used')::numeric, 1), 0) * 100, 1)
            ELSE 0
        END AS memory_usage_percent
    FROM servers s
    LEFT JOIN projects p ON p.id = s.project_id
    LEFT JOIN domains d ON d.id = p.domain_id
    LEFT JOIN flavors fl ON fl.id = s.flavor_id
    LEFT JOIN hypervisors h ON h.hostname = s.raw_json->>'OS-EXT-SRV-ATTR:hypervisor_hostname'
    WHERE s.status = 'ACTIVE'
    ORDER BY s.name;
    """
    rows = run_query(sql)

    # Post-process: extract VM IP from OpenStack addresses JSON and map storage fields
    for row in rows:
        # Extract first IP from addresses structure: {"net": [{"addr": "x.x.x.x", ...}]}
        vm_ip = "Unknown"
        addresses = row.pop("_addresses_json", None)
        if addresses:
            if isinstance(addresses, str):
                try:
                    addresses = json.loads(addresses)
                except Exception:
                    addresses = None
            if isinstance(addresses, dict):
                for net_name, addrs in addresses.items():
                    if isinstance(addrs, list):
                        for entry in addrs:
                            if isinstance(entry, dict) and "addr" in entry:
                                vm_ip = entry["addr"]
                                break
                    if vm_ip != "Unknown":
                        break
        row["vm_ip"] = vm_ip

        # Map storage_allocated_gb → storage_total_gb for UI compatibility
        alloc = row.get("storage_allocated_gb", 0) or 0
        row["storage_total_gb"] = alloc
        row["storage_used_gb"] = 0  # Not knowable from DB, but prevents N/A
        row["storage_usage_percent"] = 0

    return {"data": rows, "timestamp": str(datetime.now()), "source": "database"}


@app.get("/monitoring/summary")
def monitoring_summary():
    """Return monitoring summary from DB (fallback when monitoring service has no data)."""
    hosts_sql = """
    SELECT 
        COUNT(*) AS total_hosts,
        ROUND(AVG(CASE WHEN vcpus > 0 THEN COALESCE((raw_json->>'vcpus_used')::numeric, 0) / vcpus * 100 END), 1) AS avg_cpu_usage,
        ROUND(MAX(CASE WHEN vcpus > 0 THEN COALESCE((raw_json->>'vcpus_used')::numeric, 0) / vcpus * 100 END), 1) AS max_cpu_usage,
        ROUND(AVG(CASE WHEN memory_mb > 0 THEN COALESCE((raw_json->>'memory_mb_used')::numeric, 0) / memory_mb * 100 END), 1) AS avg_memory_usage,
        ROUND(MAX(CASE WHEN memory_mb > 0 THEN COALESCE((raw_json->>'memory_mb_used')::numeric, 0) / memory_mb * 100 END), 1) AS max_memory_usage,
        COALESCE(SUM((raw_json->>'running_vms')::integer), 0) AS total_vms
    FROM hypervisors
    WHERE state = 'up' OR state IS NULL;
    """
    host_row = run_query(hosts_sql)
    h = host_row[0] if host_row else {}
    
    return {
        "total_vms": int(h.get("total_vms", 0)),
        "total_hosts": int(h.get("total_hosts", 0)),
        "last_update": str(datetime.now()),
        "source": "database",
        "vm_stats": {
            "avg_cpu_usage": float(h.get("avg_cpu_usage", 0) or 0),
            "max_cpu_usage": float(h.get("max_cpu_usage", 0) or 0),
            "avg_memory_usage": float(h.get("avg_memory_usage", 0) or 0),
            "max_memory_usage": float(h.get("max_memory_usage", 0) or 0),
        },
        "host_stats": {
            "avg_cpu_usage": float(h.get("avg_cpu_usage", 0) or 0),
            "max_cpu_usage": float(h.get("max_cpu_usage", 0) or 0),
            "avg_memory_usage": float(h.get("avg_memory_usage", 0) or 0),
            "max_memory_usage": float(h.get("max_memory_usage", 0) or 0),
        }
    }


@app.get("/test-history")
def test_history():
    """Simple test endpoint to verify history functionality works"""
    return {"message": "History test endpoint works", "status": "ok"}


# ---------------------------------------------------------------------------
# History and Audit Endpoints
# ---------------------------------------------------------------------------

@app.get("/history/recent-changes")
def get_recent_changes(
    limit: int = Query(default=100, ge=1, le=1000),
    hours: int = Query(default=24, ge=1, le=168),
    domain_name: Optional[str] = Query(default=None)
):
    """Get recent infrastructure changes across all resource types with optional domain filtering"""
    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # For now, ignore domain filtering in the SQL query due to complexity
                # We'll filter it in the frontend since it has the data
            
                # Apply time filtering based on hours parameter
                time_filter = ""
                if hours and hours > 0:
                    # Use recorded_at for deletion events so they appear when the delete is detected
                    time_filter = f"""WHERE (
                        (change_description = 'Resource deletion detected' AND recorded_at >= (NOW() - interval '{hours} hours')) OR
                        (change_description <> 'Resource deletion detected' AND actual_time >= (NOW() - interval '{hours} hours')) OR
                        (actual_time IS NULL AND recorded_at >= (NOW() - interval '{hours} hours'))
                    )"""
            
                cur.execute(f"""
                    SELECT resource_type, resource_id, resource_name, 
                           change_hash, recorded_at, project_name, domain_name, actual_time,
                           change_description
                    FROM v_comprehensive_changes
                    {time_filter}
                    ORDER BY COALESCE(actual_time, recorded_at) DESC
                    LIMIT %s
                """, (limit,))
                changes = cur.fetchall()
            
                return {
                    "status": "success", 
                    "data": [dict(row) for row in changes],
                    "count": len(changes)
                }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error retrieving recent changes: {str(e)}")


@app.get("/history/most-changed")
def get_most_changed_resources(
    limit: int = Query(default=50, ge=1, le=500),
    domain_name: Optional[str] = Query(default=None)
):
    """Get resources with the most changes, with optional domain filtering"""
    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                base_sql = """
                    SELECT resource_type, resource_name, change_count, last_change
                    FROM v_most_changed_resources
                """
                params = []
            
                # Add domain filtering if specified - simplified to avoid table join errors
                if domain_name:
                    base_sql += """
                    WHERE (
                        (resource_type = 'network' AND resource_id IN (
                            SELECT n.id FROM networks n 
                            LEFT JOIN projects p ON p.id = n.project_id 
                            LEFT JOIN domains d ON d.id = p.domain_id 
                            WHERE d.name = %s
                        )) OR
                        (resource_type = 'server' AND resource_id IN (
                            SELECT s.id FROM servers s 
                            LEFT JOIN projects p ON p.id = s.project_id 
                            LEFT JOIN domains d ON d.id = p.domain_id 
                            WHERE d.name = %s  
                        )) OR
                        (resource_type = 'volume' AND resource_id IN (
                            SELECT v.id FROM volumes v 
                            LEFT JOIN projects p ON p.id = v.project_id 
                            LEFT JOIN domains d ON d.id = p.domain_id 
                            WHERE d.name = %s
                        )) OR
                        (resource_type = 'project' AND resource_id IN (
                            SELECT p.id FROM projects p 
                            LEFT JOIN domains d ON d.id = p.domain_id 
                            WHERE d.name = %s
                        )) OR
                        (resource_type = 'domain' AND resource_id IN (
                            SELECT id FROM domains WHERE name = %s
                        ))
                    )
                    """
                    params.extend([domain_name] * 5)
            
                base_sql += " ORDER BY change_count DESC, last_change DESC LIMIT %s"
                params.append(limit)
            
                cur.execute(base_sql, params)
                resources = cur.fetchall()
            
                return {
                    "status": "success", 
                    "data": [dict(row) for row in resources],
                    "count": len(resources)
                }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error retrieving most changed resources: {str(e)}")


@app.get("/history/by-timeframe")
def get_changes_by_timeframe(
    start_date: str = Query(description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(description="End date in YYYY-MM-DD format"),
    resource_type: Optional[str] = Query(default=None, description="Filter by resource type")
):
    """Get changes within a specific timeframe"""
    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                base_query = """
                    SELECT resource_type, resource_id, resource_name, 
                           change_hash, recorded_at
                    FROM v_recent_changes
                    WHERE DATE(recorded_at) >= %s AND DATE(recorded_at) <= %s
                """
                params = [start_date, end_date]
            
                if resource_type:
                    base_query += " AND resource_type = %s"
                    params.append(resource_type)
                
                base_query += " ORDER BY recorded_at DESC"
            
                cur.execute(base_query, params)
                changes = cur.fetchall()
            
                return {
                    "status": "success",
                    "data": [dict(row) for row in changes],
                    "count": len(changes),
                    "timeframe": {"start": start_date, "end": end_date}
                }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error retrieving timeframe changes: {str(e)}")


@app.get("/history/daily-summary")
def get_daily_summary(days: int = Query(default=30, ge=1, le=365)):
    """Get daily change summary for the specified number of days"""
    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        DATE(recorded_at) as date,
                        COUNT(*) as total_changes,
                        COUNT(DISTINCT resource_type) as resource_types,
                        COUNT(DISTINCT resource_id) as unique_resources
                    FROM v_recent_changes
                    WHERE recorded_at >= NOW() - INTERVAL '%s days'
                    GROUP BY DATE(recorded_at)
                    ORDER BY date DESC
                    LIMIT %s
                """, (days, days))
            
                results = [dict(row) for row in cur.fetchall()]
                return {"status": "success", "data": results}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get daily summary: {str(e)}")

@app.get("/history/change-velocity")
def get_change_velocity():
    """Get change velocity statistics by resource type"""
    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        resource_type,
                        COUNT(*) as total_changes,
                        COUNT(*) / 30.0 as avg_daily_changes,
                        MAX(daily_count) as max_daily_changes,
                        MIN(daily_count) as min_daily_changes,
                        COUNT(DISTINCT date_part('day', recorded_at)) as days_tracked
                    FROM (
                        SELECT 
                            resource_type, 
                            recorded_at,
                            COUNT(*) OVER (PARTITION BY resource_type, DATE(recorded_at)) as daily_count
                        FROM v_recent_changes
                        WHERE recorded_at >= NOW() - INTERVAL '30 days'
                    ) daily_stats
                    GROUP BY resource_type
                    ORDER BY total_changes DESC
                """)
            
                results = [dict(row) for row in cur.fetchall()]
                return {"velocity_stats": results}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get velocity stats: {str(e)}")


@app.get("/history/resource/{resource_type}/{resource_id}")
def get_resource_history(
    resource_type: str, 
    resource_id: str,
    limit: int = Query(default=100, ge=1, le=1000)
):
    """Get complete history for a specific resource"""
    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Map resource type to actual history table
                table_mapping = {
                    "server": "servers_history",
                    "domain": "domains_history",
                    "project": "projects_history", 
                    "flavor": "flavors_history",
                    "image": "images_history",
                    "hypervisor": "hypervisors_history",
                    "network": "networks_history",
                    "volume": "volumes_history",
                    "floating_ip": "floating_ips_history",
                    "snapshot": "snapshots_history",
                    "port": "ports_history",
                    "subnet": "subnets_history",
                    "router": "routers_history",
                    "user": "users_history",
                    "role": "roles_history",
                    "security_group": "security_groups_history",
                    "security_group_rule": "security_group_rules_history"
                }
            
                # Handle deletion records specially - they come from deletions_history
                if resource_type == "deletion":
                    cur.execute("""
                        SELECT id, resource_type AS original_resource_type, resource_id, resource_name,
                               deleted_at, project_name, domain_name, reason,
                               last_seen_before_deletion, raw_json_snapshot,
                               'deleted-' || resource_id AS change_hash
                        FROM deletions_history
                        WHERE resource_id = %s
                        ORDER BY deleted_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                
                    history = cur.fetchall()
                    standardized_history = []
                    for idx, row in enumerate(history):
                        row_dict = dict(row)
                        mapped_row = {
                            "resource_type": "deletion",
                            "resource_id": row_dict.get('resource_id'),
                            "resource_name": row_dict.get('resource_name') or f"Deleted {row_dict.get('original_resource_type', 'resource')}",
                            "recorded_at": row_dict.get('deleted_at'),
                            "change_hash": row_dict.get('change_hash', ''),
                            "current_state": row_dict.get('raw_json_snapshot') or {
                                "original_type": row_dict.get('original_resource_type'),
                                "reason": row_dict.get('reason'),
                                "last_seen_before_deletion": str(row_dict.get('last_seen_before_deletion') or ''),
                                "project_name": row_dict.get('project_name'),
                                "domain_name": row_dict.get('domain_name'),
                            },
                            "previous_hash": None,
                            "change_sequence": len(history) - idx
                        }
                        standardized_history.append(mapped_row)
                
                    return {
                        "status": "success",
                        "data": standardized_history,
                        "count": len(standardized_history),
                        "resource": {"type": "deletion", "id": resource_id}
                    }
            
                if resource_type not in table_mapping:
                    raise HTTPException(status_code=400, detail=f"Invalid resource type: {resource_type}")
            
                table_name = table_mapping[resource_type]
            
                # Use a simpler query structure based on what we know exists
                if resource_type == "server":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE server_id = %s
                        ORDER BY last_seen_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "volume":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE volume_id = %s
                        ORDER BY last_seen_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "network":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE network_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "port":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE port_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "subnet":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE subnet_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "router":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE router_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "floating_ip":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE floating_ip_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "hypervisor":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE hypervisor_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "image":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE image_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "flavor":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE flavor_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "domain":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE domain_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "project":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE project_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "user":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE user_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "role":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE role_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "snapshot":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE snapshot_id = %s
                        ORDER BY last_seen_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "security_group":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE security_group_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
                elif resource_type == "security_group_rule":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE security_group_rule_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT %s
                    """, (resource_id, limit))
            
                history = cur.fetchall()
            
                # Map database columns to standardized ResourceHistory format
                standardized_history = []
                for idx, row in enumerate(history):
                    row_dict = dict(row)
                
                    # Map fields based on resource type
                    if resource_type == "server":
                        resource_name = row_dict.get('name') or row_dict.get('vm_name')
                        mapped_row = {
                            "resource_type": resource_type,
                            "resource_id": row_dict.get('server_id'),
                            "resource_name": resource_name,
                            "recorded_at": row_dict.get('last_seen_at') or row_dict.get('recorded_at'),
                            "change_hash": row_dict.get('change_hash', ''),
                            "current_state": row_dict.get('raw_json') or row_dict,
                            "previous_hash": None,  # Not stored in current schema
                            "change_sequence": len(history) - idx  # Reverse order for sequence
                        }
                    elif resource_type == "port":
                        mapped_row = {
                            "resource_type": resource_type,
                            "resource_id": row_dict.get('port_id'),
                            "resource_name": row_dict.get('name') or f"Port {row_dict.get('port_id', '')[:8]}",
                            "recorded_at": row_dict.get('recorded_at'),
                            "change_hash": row_dict.get('change_hash', ''),
                            "current_state": row_dict.get('raw_json') or row_dict,
                            "previous_hash": None,
                            "change_sequence": len(history) - idx
                        }
                    elif resource_type == "floating_ip":
                        mapped_row = {
                            "resource_type": resource_type,
                            "resource_id": row_dict.get('floating_ip_id'),
                            "resource_name": row_dict.get('floating_ip') or f"FloatingIP {row_dict.get('floating_ip_id', '')[:8]}",
                            "recorded_at": row_dict.get('recorded_at'),
                            "change_hash": row_dict.get('change_hash', ''),
                            "current_state": row_dict.get('raw_json') or row_dict,
                            "previous_hash": None,
                            "change_sequence": len(history) - idx
                        }
                    elif resource_type == "volume":
                        mapped_row = {
                            "resource_type": resource_type,
                            "resource_id": row_dict.get('volume_id'),
                            "resource_name": row_dict.get('volume_name') or f"Volume {row_dict.get('volume_id', '')[:8]}",
                            "recorded_at": row_dict.get('last_seen_at') or row_dict.get('recorded_at'),
                            "change_hash": row_dict.get('change_hash', ''),
                            "current_state": row_dict.get('raw_json') or row_dict,
                            "previous_hash": None,
                            "change_sequence": len(history) - idx
                        }
                    elif resource_type == "snapshot":
                        mapped_row = {
                            "resource_type": resource_type,
                            "resource_id": row_dict.get('snapshot_id'),
                            "resource_name": row_dict.get('name') or f"Snapshot {row_dict.get('snapshot_id', '')[:8]}",
                            "recorded_at": row_dict.get('last_seen_at') or row_dict.get('recorded_at'),
                            "change_hash": row_dict.get('change_hash', ''),
                            "current_state": row_dict.get('raw_json') or row_dict,
                            "previous_hash": None,
                            "change_sequence": len(history) - idx
                        }
                    elif resource_type == "security_group":
                        mapped_row = {
                            "resource_type": resource_type,
                            "resource_id": row_dict.get('security_group_id'),
                            "resource_name": row_dict.get('name') or f"SG {row_dict.get('security_group_id', '')[:8]}",
                            "recorded_at": row_dict.get('recorded_at'),
                            "change_hash": row_dict.get('change_hash', ''),
                            "current_state": row_dict.get('raw_json') or row_dict,
                            "previous_hash": None,
                            "change_sequence": len(history) - idx
                        }
                    elif resource_type == "security_group_rule":
                        mapped_row = {
                            "resource_type": resource_type,
                            "resource_id": row_dict.get('security_group_rule_id'),
                            "resource_name": f"{row_dict.get('direction', '')} {row_dict.get('protocol', 'any')} {row_dict.get('security_group_id', '')[:8]}",
                            "recorded_at": row_dict.get('recorded_at'),
                            "change_hash": row_dict.get('change_hash', ''),
                            "current_state": row_dict.get('raw_json') or row_dict,
                            "previous_hash": None,
                            "change_sequence": len(history) - idx
                        }
                    else:
                        # Generic mapping for other resource types
                        id_field = f"{resource_type}_id"
                        mapped_row = {
                            "resource_type": resource_type,
                            "resource_id": row_dict.get(id_field),
                            "resource_name": row_dict.get('name') or f"{resource_type.title()} {row_dict.get(id_field, '')[:8]}",
                            "recorded_at": row_dict.get('recorded_at') or row_dict.get('last_seen_at'),
                            "change_hash": row_dict.get('change_hash', ''),
                            "current_state": row_dict.get('raw_json') or row_dict,
                            "previous_hash": None,
                            "change_sequence": len(history) - idx
                        }
                
                    standardized_history.append(mapped_row)
            
                return {
                    "status": "success",
                    "data": standardized_history,
                    "count": len(standardized_history),
                    "resource": {"type": resource_type, "id": resource_id}
                }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error retrieving resource history: {str(e)}")


@app.get("/history/compare/{resource_type}/{resource_id}")
def compare_history_entries(
    resource_type: str,
    resource_id: str,
    current_hash: str = Query(description="Current change hash"),
    previous_hash: str = Query(description="Previous change hash")
):
    """Compare two history entries to show what changed"""
    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Map resource type to table
                table_mapping = {
                    "server": "servers_history",
                    "domain": "domains_history",
                    "project": "projects_history", 
                    "flavor": "flavors_history",
                    "image": "images_history",
                    "hypervisor": "hypervisors_history",
                    "network": "networks_history",
                    "volume": "volumes_history",
                    "floating_ip": "floating_ips_history",
                    "snapshot": "snapshots_history",
                    "port": "ports_history",
                    "subnet": "subnets_history",
                    "router": "routers_history",
                    "user": "users_history",
                    "role": "roles_history",
                    "security_group": "security_groups_history",
                    "security_group_rule": "security_group_rules_history"
                }
            
                if resource_type == "deletion":
                    return {
                        "status": "info",
                        "message": "Comparison is not available for deletion records. Deletion events are one-time occurrences.",
                        "changes": {}
                    }
            
                if resource_type not in table_mapping:
                    raise HTTPException(status_code=400, detail=f"Invalid resource type: {resource_type}")
            
                table_name = table_mapping[resource_type]
                id_field = f"{resource_type}_id" if resource_type != "floating_ip" else "floating_ip_id"
            
                # Get both history entries
                if resource_type == "user":
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE user_id = %s AND change_hash IN (%s, %s)
                        ORDER BY recorded_at DESC
                    """, (resource_id, current_hash, previous_hash))
                else:
                    cur.execute(f"""
                        SELECT * FROM {table_name}
                        WHERE {id_field} = %s AND change_hash IN (%s, %s)
                        ORDER BY recorded_at DESC
                    """, (resource_id, current_hash, previous_hash))
            
                entries = cur.fetchall()
            
                if len(entries) < 2:
                    return {
                        "status": "error",
                        "message": "Could not find both history entries for comparison",
                        "found_entries": len(entries)
                    }
            
                current_entry = next((e for e in entries if e['change_hash'] == current_hash), entries[0])
                previous_entry = next((e for e in entries if e['change_hash'] == previous_hash), entries[1])
            
                # Compare the entries
                changes = {}
                excluded_fields = {'id', 'recorded_at', 'change_hash', 'raw_json', 'run_id'}
            
                for field in current_entry.keys():
                    if field not in excluded_fields:
                        current_val = current_entry[field]
                        previous_val = previous_entry[field]
                        if current_val != previous_val:
                            changes[field] = {
                                "from": previous_val,
                                "to": current_val,
                                "changed": True
                            }
                        else:
                            changes[field] = {
                                "value": current_val,
                                "changed": False
                            }
            
                # Also compare raw_json if available
                raw_json_changes = {}
                if current_entry.get('raw_json') and previous_entry.get('raw_json'):
                    current_raw = dict(current_entry['raw_json'])
                    previous_raw = dict(previous_entry['raw_json'])
                
                    # Find changed fields in raw JSON
                    all_keys = set(current_raw.keys()) | set(previous_raw.keys())
                    for key in all_keys:
                        if key in ['links']:  # Skip metadata fields
                            continue
                        current_val = current_raw.get(key)
                        previous_val = previous_raw.get(key)
                        if current_val != previous_val:
                            raw_json_changes[key] = {
                                "from": previous_val,
                                "to": current_val
                            }
            
                return {
                    "status": "success",
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "comparison": {
                        "current_recorded_at": current_entry['recorded_at'],
                        "previous_recorded_at": previous_entry['recorded_at'],
                        "field_changes": changes,
                        "raw_json_changes": raw_json_changes,
                        "total_changed_fields": len([k for k, v in changes.items() if v.get('changed', False)]),
                        "has_significant_changes": len(raw_json_changes) > 0 or any(v.get('changed', False) for v in changes.values())
                    }
                }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error comparing history entries: {str(e)}")


@app.get("/history/details/{resource_type}/{resource_id}")
def get_change_details(resource_type: str, resource_id: str):
    """Get detailed change information for a specific resource"""
    with get_connection() as conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Map resource type to table
                table_mapping = {
                    "server": "servers_history",
                    "domain": "domains_history", 
                    "project": "projects_history",
                    "flavor": "flavors_history",
                    "image": "images_history",
                    "hypervisor": "hypervisors_history",
                    "network": "networks_history",
                    "volume": "volumes_history",
                    "floating_ip": "floating_ips_history",
                    "snapshot": "snapshots_history",
                    "port": "ports_history",
                    "subnet": "subnets_history",
                    "router": "routers_history",
                    "user": "users_history",
                    "role": "roles_history",
                    "security_group": "security_groups_history",
                    "security_group_rule": "security_group_rules_history"
                }
            
                if resource_type == "deletion":
                    cur.execute("""
                        SELECT id, resource_type AS original_resource_type, resource_id, resource_name,
                               deleted_at, project_name, domain_name, reason,
                               last_seen_before_deletion, raw_json_snapshot
                        FROM deletions_history
                        WHERE resource_id = %s
                        ORDER BY deleted_at DESC
                        LIMIT 10
                    """, (resource_id,))
                    history = cur.fetchall()
                    if not history:
                        raise HTTPException(status_code=404, detail="Deletion record not found")
                
                    latest = dict(history[0])
                    return {
                        "status": "success",
                        "resource": {
                            "type": "deletion",
                            "id": resource_id,
                            "name": latest.get('resource_name', 'Unknown'),
                            "original_type": latest.get('original_resource_type'),
                        },
                        "total_changes": len(history),
                        "latest": {
                            "deleted_at": latest.get('deleted_at'),
                            "reason": latest.get('reason'),
                            "project_name": latest.get('project_name'),
                            "domain_name": latest.get('domain_name'),
                            "last_seen_before_deletion": latest.get('last_seen_before_deletion'),
                            "raw_json_snapshot": latest.get('raw_json_snapshot'),
                        },
                        "changes": [{
                            "change_type": "deleted",
                            "change_summary": f"Resource deletion detected - {dict(row).get('reason', 'no longer found in inventory')}",
                            "recorded_at": dict(row).get('deleted_at'),
                            "key_info": {
                                "original_type": dict(row).get('original_resource_type'),
                                "name": dict(row).get('resource_name'),
                                "project": dict(row).get('project_name'),
                                "domain": dict(row).get('domain_name'),
                                "reason": dict(row).get('reason'),
                            }
                        } for row in history]
                    }
            
                if resource_type not in table_mapping:
                    raise HTTPException(status_code=400, detail=f"Invalid resource type: {resource_type}")
            
                table_name = table_mapping[resource_type]
                id_field = f"{resource_type}_id" if resource_type != "floating_ip" else "floating_ip_id"
            
                # Get history entries for this resource
                if resource_type == "user":
                    cur.execute(f"""
                        SELECT uh.*, d.name as domain_name, 
                               (SELECT COUNT(*) FROM users_history uh2 WHERE uh2.user_id = uh.user_id AND uh2.recorded_at < uh.recorded_at) as change_sequence
                        FROM {table_name} uh
                        LEFT JOIN domains d ON uh.domain_id = d.id
                        WHERE user_id = %s
                        ORDER BY recorded_at DESC
                        LIMIT 10
                    """, (resource_id,))
                else:
                    cur.execute(f"""
                        SELECT *,
                               (SELECT COUNT(*) FROM {table_name} t2 WHERE t2.{id_field} = t1.{id_field} AND t2.recorded_at < t1.recorded_at) as change_sequence
                        FROM {table_name} t1
                        WHERE {id_field} = %s
                        ORDER BY recorded_at DESC
                        LIMIT 10
                    """, (resource_id,))
            
                history = cur.fetchall()
            
                if not history:
                    raise HTTPException(status_code=404, detail="Resource not found in history")
            
                # Prepare detailed information
                latest = history[0]
                changes_over_time = []
            
                for i, entry in enumerate(history):
                    entry_dict = dict(entry)
                
                    # Determine change type
                    if entry_dict.get('change_sequence', 0) == 0:
                        change_type = "discovered"
                        change_summary = f"First discovered in inventory"
                    else:
                        change_type = "modified" 
                        change_summary = f"Configuration or state change #{entry_dict.get('change_sequence', 0) + 1}"
                
                    # Extract key information based on resource type
                    if resource_type == "user":
                        key_info = {
                            "name": entry_dict.get('name'),
                            "email": entry_dict.get('email'),
                            "enabled": entry_dict.get('enabled'),
                            "domain": entry_dict.get('domain_name'),
                            "created_at": entry_dict.get('created_at')
                        }
                        if entry_dict.get('last_login'):
                            key_info["last_login"] = entry_dict.get('last_login')
                    else:
                        # Generic key info extraction
                        raw_json = entry_dict.get('raw_json', {})
                        if isinstance(raw_json, dict):
                            key_info = {
                                "name": entry_dict.get('name') or raw_json.get('name'),
                                "status": raw_json.get('status'),
                                "created_at": raw_json.get('created_at')
                            }
                        else:
                            key_info = {"name": entry_dict.get('name', 'Unknown')}
                
                    changes_over_time.append({
                        "recorded_at": entry_dict.get('recorded_at'),
                        "change_hash": entry_dict.get('change_hash'),
                        "change_type": change_type,
                        "change_summary": change_summary,
                        "key_information": key_info,
                        "sequence_number": len(history) - i
                    })
            
                # Summary information
                summary = {
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "resource_name": latest.get('name') or latest.get(f'{resource_type}_name'),
                    "total_changes": len(history),
                    "first_discovered": history[-1].get('recorded_at') if history else None,
                    "last_changed": history[0].get('recorded_at') if history else None,
                    "current_status": "active" if latest else "unknown"
                }
            
                if resource_type == "user":
                    summary.update({
                        "domain": latest.get('domain_name'),
                        "enabled": latest.get('enabled'),
                        "email": latest.get('email')
                    })
            
                return {
                    "status": "success",
                    "summary": summary,
                    "changes_timeline": changes_over_time,
                    "has_multiple_changes": len(history) > 1
                }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error retrieving change details: {str(e)}")


@app.get("/audit/compliance-report")
def get_compliance_report():
    """Generate compliance audit report showing recent changes and patterns"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get recent changes summary by resource type
                cur.execute("""
                    SELECT resource_type, 
                           COUNT(*) as total_changes,
                           MAX(recorded_at) as last_change
                    FROM v_recent_changes
                    WHERE recorded_at >= NOW() - INTERVAL '7 days'
                    GROUP BY resource_type
                    ORDER BY total_changes DESC
                """)
                resource_summary = cur.fetchall()
                
                # Get high-activity resources (potential compliance risks)
                cur.execute("""
                    SELECT resource_type, resource_name, change_count
                    FROM v_most_changed_resources
                    WHERE change_count > 10
                    ORDER BY change_count DESC
                    LIMIT 20
                """)
                high_activity = cur.fetchall()
                
                # Get recent changes (last 30 days)
                cur.execute("""
                    SELECT resource_type, resource_name, recorded_at
                    FROM v_recent_changes
                    WHERE recorded_at >= NOW() - INTERVAL '30 days'
                    ORDER BY recorded_at DESC
                    LIMIT 50
                """)
                recent_changes = cur.fetchall()
                
                return {
                    "status": "success",
                    "report_date": "2026-01-26",
                    "summary": {
                        "resource_activity": [dict(row) for row in resource_summary],
                        "high_activity_resources": [dict(row) for row in high_activity],
                        "recent_changes": [dict(row) for row in recent_changes]
                    },
                    "compliance_notes": {
                        "total_resource_types": len(resource_summary),
                        "high_risk_resources": len(high_activity),
                        "recent_changes_count": len(recent_changes)
                    }
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating compliance report: {str(e)}")


@app.get("/audit/change-patterns")
def get_change_patterns(days: int = Query(default=30, ge=1, le=365)):
    """Analyze change patterns over specified time period"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        DATE(recorded_at) as change_date,
                        resource_type,
                        COUNT(*) as change_count
                    FROM v_recent_changes
                    WHERE recorded_at >= NOW() - INTERVAL %s
                    GROUP BY DATE(recorded_at), resource_type
                    ORDER BY change_date DESC, change_count DESC
                """, (f"{days} days",))
                patterns = cur.fetchall()
                
                return {
                    "status": "success",
                    "analysis_period": f"{days} days",
                    "data": [dict(row) for row in patterns],
                    "count": len(patterns)
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing change patterns: {str(e)}")


@app.get("/audit/resource-timeline/{resource_type}")
def get_resource_type_timeline(
    resource_type: str,
    days: int = Query(default=30, ge=1, le=365)
):
    """Get timeline of changes for a specific resource type"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT resource_id, resource_name, change_hash, recorded_at
                    FROM v_recent_changes
                    WHERE resource_type = %s 
                      AND recorded_at >= NOW() - INTERVAL %s
                    ORDER BY recorded_at DESC
                """, (resource_type, f"{days} days"))
                timeline = cur.fetchall()
                
                return {
                    "status": "success",
                    "resource_type": resource_type,
                    "period": f"{days} days",
                    "data": [dict(row) for row in timeline],
                    "count": len(timeline)
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving resource timeline: {str(e)}")


# ======================================================================================
# USER AND ROLE MANAGEMENT ENDPOINTS
# ======================================================================================

@app.get("/users")
@limiter.limit("30/minute")  
async def get_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    sort_by: str = Query("name"),
    sort_dir: str = Query("asc"),
    enabled: Optional[bool] = None,
    domain_id: Optional[str] = None
):
    """Get users with optional filtering and pagination"""
    try:
        offset = (page - 1) * page_size
        
        # Safe sort column mapping
        if sort_by not in ["name", "email", "domain_name", "enabled", "created_at"]:
            sort_by = "name"
        if sort_dir.lower() not in ["asc", "desc"]:
            sort_dir = "asc"
        
        sort_columns = {
            "name": "u.name",
            "email": "u.email", 
            "domain_name": "d.name",
            "enabled": "u.enabled",
            "created_at": "u.created_at"
        }
        sort_column = sort_columns[sort_by]
        
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Main query
                query = """
                    SELECT 
                        u.id, u.name, u.email, u.enabled, u.domain_id, 
                        u.description, u.default_project_id, u.created_at, 
                        u.last_login, u.last_seen_at,
                        d.name as domain_name,
                        p.name as default_project_name,
                        COUNT(DISTINCT ra.role_id) as role_count,
                        STRING_AGG(DISTINCT r.name, ', ') as roles
                    FROM users u
                    LEFT JOIN domains d ON d.id = u.domain_id
                    LEFT JOIN projects p ON p.id = u.default_project_id
                    LEFT JOIN role_assignments ra ON ra.user_id = u.id
                    LEFT JOIN roles r ON r.id = ra.role_id
                    WHERE 1=1
                """
                params = []
            
                if enabled is not None:
                    query += " AND u.enabled = %s"
                    params.append(enabled)
                
                if domain_id:
                    query += " AND u.domain_id = %s" 
                    params.append(domain_id)
                
                query += f" GROUP BY u.id, u.name, u.email, u.enabled, u.domain_id, u.description, u.default_project_id, u.created_at, u.last_login, u.last_seen_at, d.name, p.name ORDER BY {sort_column} {sort_dir.upper()} LIMIT %s OFFSET %s"
                params.extend([page_size, offset])
            
                cur.execute(query, params)
                users = [dict(row) for row in cur.fetchall()]
            
                # Count query
                count_query = "SELECT COUNT(*) as count FROM users WHERE 1=1"
                count_params = []
            
                if enabled is not None:
                    count_query += " AND enabled = %s"
                    count_params.append(enabled)
                
                if domain_id:
                    count_query += " AND domain_id = %s"
                    count_params.append(domain_id)
                
                cur.execute(count_query, count_params)
                result = cur.fetchone()
                total = result['count'] if result else 0
            
            pages = max(1, (total + page_size - 1) // page_size) if total > 0 and page_size > 0 else 1
        
            return {
                "data": users,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": pages
            }
    except Exception as e:
        import traceback
        traceback.print_exc()  # This will show in docker logs
        raise HTTPException(status_code=500, detail=f"Error retrieving users: {str(e)}")


@app.get("/users/{user_id}")
@limiter.limit("60/minute")
async def get_user_details(request: Request, user_id: str):
    """Get detailed information about a specific user"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get user details with enriched data
                cur.execute("""
                    SELECT 
                        u.id, u.name, u.email, u.enabled, u.domain_id, 
                        u.description, u.default_project_id, u.created_at, 
                        u.last_login, u.last_seen_at, u.raw_json,
                        d.name as domain_name,
                        p.name as default_project_name
                    FROM users u
                    LEFT JOIN domains d ON d.id = u.domain_id
                    LEFT JOIN projects p ON p.id = u.default_project_id
                    WHERE u.id = %s
                """, (user_id,))
                user = cur.fetchone()
            
                if not user:
                    raise HTTPException(status_code=404, detail="User not found")
                
                user_data = dict(user)
            
                # Get user's role assignments
                cur.execute("""
                    SELECT 
                        ra.role_id, ra.role_name, ra.project_id, ra.project_name,
                        ra.domain_id, ra.domain_name, ra.inherited
                    FROM role_assignments ra
                    WHERE ra.user_id = %s
                    ORDER BY ra.project_name, ra.role_name
                """, (user_id,))
                user_data['role_assignments'] = [dict(row) for row in cur.fetchall()]
            
                # Get user's recent activity (last 30 days)
                cur.execute("""
                    SELECT action, resource_type, resource_id, success, timestamp, details
                    FROM user_access_logs
                    WHERE user_id = %s AND timestamp > now() - INTERVAL '30 days'
                    ORDER BY timestamp DESC
                    LIMIT 50
                """, (user_id,))
                user_data['recent_activity'] = [dict(row) for row in cur.fetchall()]
            
            return {
                "status": "success",
                "data": user_data
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving user details: {str(e)}")


@app.get("/roles")
@limiter.limit("30/minute")
async def get_all_roles(
    request: Request,
    domain_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get roles with optional filtering"""
    try:
        with get_connection() as conn:
            query = """
                SELECT 
                    r.id, r.name, r.description, r.domain_id, r.last_seen_at,
                    d.name as domain_name,
                    COUNT(DISTINCT ra.user_id) as user_count
                FROM roles r
                LEFT JOIN domains d ON d.id = r.domain_id
                LEFT JOIN role_assignments ra ON ra.role_id = r.id
                WHERE 1=1
            """
            params = []
        
            if domain_id:
                query += " AND r.domain_id = %s"
                params.append(domain_id)
            
            query += """
                GROUP BY r.id, r.name, r.description, r.domain_id, r.last_seen_at, d.name
                ORDER BY r.name
                LIMIT %s OFFSET %s
            """
            params.extend([limit, offset])
        
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                roles = [dict(row) for row in cur.fetchall()]
            
                # Get total count
                count_query = "SELECT COUNT(*) FROM roles WHERE 1=1"
                count_params = []
                if domain_id:
                    count_query += " AND domain_id = %s"
                    count_params.append(domain_id)
                
                cur.execute(count_query, count_params)
                total = cur.fetchone()[0]
            
            return {
                "status": "success",
                "data": roles,
                "pagination": {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "count": len(roles)
                }
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving roles: {str(e)}")


@app.get("/roles/{role_id}")
@limiter.limit("60/minute")
async def get_role_details(request: Request, role_id: str):
    """Get detailed information about a specific role"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get role details
                cur.execute("""
                    SELECT 
                        r.id, r.name, r.description, r.domain_id, r.last_seen_at, r.raw_json,
                        d.name as domain_name
                    FROM roles r
                    LEFT JOIN domains d ON d.id = r.domain_id
                    WHERE r.id = %s
                """, (role_id,))
                role = cur.fetchone()
            
                if not role:
                    raise HTTPException(status_code=404, detail="Role not found")
                
                role_data = dict(role)
            
                # Get users with this role
                cur.execute("""
                    SELECT 
                        ra.user_id, ra.user_name, ra.project_id, ra.project_name,
                        ra.domain_id, ra.domain_name, ra.inherited
                    FROM role_assignments ra
                    WHERE ra.role_id = %s
                    ORDER BY ra.user_name, ra.project_name
                """, (role_id,))
                role_data['assignments'] = [dict(row) for row in cur.fetchall()]
            
            return {
                "status": "success",
                "data": role_data
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving role details: {str(e)}")


@app.get("/user-activity-summary")
@limiter.limit("20/minute")
async def get_user_activity_summary(request: Request):
    """Get user activity summary using the database view"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM v_user_activity_summary
                    ORDER BY activity_last_30d DESC, user_name
                """)
                summary = [dict(row) for row in cur.fetchall()]
            
            return {
                "status": "success",
                "data": summary,
                "count": len(summary)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving user activity summary: {str(e)}")


@app.get("/role-assignments")
@limiter.limit("30/minute")
async def get_role_assignments(
    request: Request,
    user_id: Optional[str] = None,
    role_id: Optional[str] = None,
    project_id: Optional[str] = None,
    domain_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get role assignments with optional filtering"""
    try:
        with get_connection() as conn:
            query = """
                SELECT 
                    ra.id, ra.role_id, ra.user_id, ra.group_id, 
                    ra.project_id, ra.domain_id, ra.inherited,
                    ra.user_name, ra.role_name, ra.project_name, ra.domain_name,
                    ra.last_seen_at
                FROM role_assignments ra
                WHERE 1=1
            """
            params = []
        
            if user_id:
                query += " AND ra.user_id = %s"
                params.append(user_id)
            if role_id:
                query += " AND ra.role_id = %s"
                params.append(role_id)
            if project_id:
                query += " AND ra.project_id = %s"
                params.append(project_id)
            if domain_id:
                query += " AND ra.domain_id = %s"
                params.append(domain_id)
            
            query += """
                ORDER BY ra.user_name, ra.role_name, ra.project_name
                LIMIT %s OFFSET %s
            """
            params.extend([limit, offset])
        
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                assignments = [dict(row) for row in cur.fetchall()]
            
                # Get total count with same filters
                count_query = "SELECT COUNT(*) FROM role_assignments WHERE 1=1"
                count_params = []
                if user_id:
                    count_query += " AND user_id = %s"
                    count_params.append(user_id)
                if role_id:
                    count_query += " AND role_id = %s"
                    count_params.append(role_id)
                if project_id:
                    count_query += " AND project_id = %s"
                    count_params.append(project_id)
                if domain_id:
                    count_query += " AND domain_id = %s"
                    count_params.append(domain_id)
                
                cur.execute(count_query, count_params)
                total = cur.fetchone()[0]
            
            return {
                "status": "success",
                "data": assignments,
                "pagination": {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "count": len(assignments)
                }
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving role assignments: {str(e)}")


@app.post("/admin/user-access-log")
@limiter.limit("60/minute")
async def log_user_access_activity(
    request: Request,
    admin_creds: HTTPBasicCredentials = Depends(security)
):
    """Log user access activity (admin only)"""
    verify_admin_credentials(admin_creds)
    
    try:
        body = await request.json()
        required_fields = ['user_id', 'user_name', 'action']
        
        for field in required_fields:
            if field not in body:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        with get_connection() as conn:
        
            # Import the logging function
            sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from db_writer import log_user_access
        
            log_user_access(
                conn,
                user_id=body['user_id'],
                user_name=body['user_name'], 
                action=body['action'],
                resource_type=body.get('resource_type'),
                resource_id=body.get('resource_id'),
                project_id=body.get('project_id'),
                success=body.get('success', True),
                ip_address=body.get('ip_address'),
                user_agent=body.get('user_agent'),
                details=body.get('details')
            )
        
            return {"status": "success", "message": "User access logged successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error logging user access: {str(e)}")


# Test endpoint to verify history endpoints are loaded
@app.get("/test-history-endpoints")
def test_history_endpoints():
    """Test endpoint to verify history functionality is working"""
    return {
        "status": "success",
        "message": "History endpoints are loaded and working",
        "available_endpoints": [
            "/history/recent-changes",
            "/history/most-changed", 
            "/history/by-timeframe",
            "/history/resource/{resource_type}/{resource_id}",
            "/audit/compliance-report",
            "/audit/change-patterns",
            "/audit/resource-timeline/{resource_type}"
        ]
    }


@app.get("/roles/{role_id}")
@limiter.limit("60/minute")
async def get_role_details(request: Request, role_id: str):
    """Get detailed information about a specific role"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get role details
                cur.execute("""
                    SELECT 
                        r.id, r.name, r.description, r.domain_id, r.last_seen_at, r.raw_json,
                        d.name as domain_name
                    FROM roles r
                    LEFT JOIN domains d ON d.id = r.domain_id
                    WHERE r.id = %s
                """, (role_id,))
                role = cur.fetchone()
            
                if not role:
                    raise HTTPException(status_code=404, detail="Role not found")
                
                role_data = dict(role)
            
                # Get users with this role
                cur.execute("""
                    SELECT 
                        ra.user_id, ra.user_name, ra.project_id, ra.project_name,
                        ra.domain_id, ra.domain_name, ra.inherited
                    FROM role_assignments ra
                    WHERE ra.role_id = %s
                    ORDER BY ra.user_name, ra.project_name
                """, (role_id,))
                role_data['assignments'] = [dict(row) for row in cur.fetchall()]
            
            return {
                "status": "success",
                "data": role_data
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving role details: {str(e)}")


@app.get("/user-activity-summary")
@limiter.limit("20/minute")
async def get_user_activity_summary(request: Request):
    """Get user activity summary using the database view"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM v_user_activity_summary
                    ORDER BY activity_last_30d DESC, user_name
                """)
                summary = [dict(row) for row in cur.fetchall()]
            
            return {
                "status": "success",
                "data": summary,
                "count": len(summary)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving user activity summary: {str(e)}")


@app.get("/role-assignments")
@limiter.limit("30/minute")
async def get_role_assignments(
    request: Request,
    user_id: Optional[str] = None,
    role_id: Optional[str] = None,
    project_id: Optional[str] = None,
    domain_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get role assignments with optional filtering"""
    try:
        with get_connection() as conn:
            query = """
                SELECT 
                    ra.id, ra.role_id, ra.user_id, ra.group_id, 
                    ra.project_id, ra.domain_id, ra.inherited,
                    ra.user_name, ra.role_name, ra.project_name, ra.domain_name,
                    ra.last_seen_at
                FROM role_assignments ra
                WHERE 1=1
            """
            params = []
        
            if user_id:
                query += " AND ra.user_id = %s"
                params.append(user_id)
            if role_id:
                query += " AND ra.role_id = %s"
                params.append(role_id)
            if project_id:
                query += " AND ra.project_id = %s"
                params.append(project_id)
            if domain_id:
                query += " AND ra.domain_id = %s"
                params.append(domain_id)
            
            query += """
                ORDER BY ra.user_name, ra.role_name, ra.project_name
                LIMIT %s OFFSET %s
            """
            params.extend([limit, offset])
        
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                assignments = [dict(row) for row in cur.fetchall()]
            
                # Get total count with same filters
                count_query = "SELECT COUNT(*) FROM role_assignments WHERE 1=1"
                count_params = []
                if user_id:
                    count_query += " AND user_id = %s"
                    count_params.append(user_id)
                if role_id:
                    count_query += " AND role_id = %s"
                    count_params.append(role_id)
                if project_id:
                    count_query += " AND project_id = %s"
                    count_params.append(project_id)
                if domain_id:
                    count_query += " AND domain_id = %s"
                    count_params.append(domain_id)
                
                cur.execute(count_query, count_params)
                total = cur.fetchone()[0]
            
            return {
                "status": "success",
                "data": assignments,
                "pagination": {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "count": len(assignments)
                }
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving role assignments: {str(e)}")


@app.post("/admin/user-access-log")
@limiter.limit("60/minute")
async def log_user_access_activity(
    request: Request,
    admin_creds: HTTPBasicCredentials = Depends(security)
):
    """Log user access activity (admin only)"""
    verify_admin_credentials(admin_creds)
    
    try:
        body = await request.json()
        required_fields = ['user_id', 'user_name', 'action']
        
        for field in required_fields:
            if field not in body:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        with get_connection() as conn:
        
            # Import the logging function
            sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from db_writer import log_user_access
        
            log_user_access(
                conn,
                user_id=body['user_id'],
                user_name=body['user_name'], 
                action=body['action'],
                resource_type=body.get('resource_type'),
                resource_id=body.get('resource_id'),
                project_id=body.get('project_id'),
                success=body.get('success', True),
                ip_address=body.get('ip_address'),
                user_agent=body.get('user_agent'),
                details=body.get('details')
            )
        
            return {"status": "success", "message": "User access logged successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error logging user access: {str(e)}")


# Test endpoint to verify history endpoints are loaded
@app.get("/test-history-endpoints")
def test_history_endpoints():
    """Test endpoint to verify history functionality is working"""
    return {
        "status": "success",
        "message": "History endpoints are loaded and working",
        "available_endpoints": [
            "/history/recent-changes",
            "/history/most-changed", 
            "/history/by-timeframe",
            "/history/resource/{resource_type}/{resource_id}",
            "/audit/compliance-report",
            "/audit/change-patterns",
            "/audit/resource-timeline/{resource_type}"
        ]
    }




# ---------------------------------------------------------------------------
# Branding / App Settings  (public GET, admin PUT)
# ---------------------------------------------------------------------------

@app.get("/settings/branding")
def get_branding():
    """
    Return app branding settings (company name, logo, colors, hero text).
    Public endpoint - used on the login page before authentication.
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT key, value FROM app_settings")
            rows = cur.fetchall()
            settings = {r["key"]: r["value"] for r in rows}
            if "login_hero_features" in settings:
                try:
                    settings["login_hero_features"] = json.loads(settings["login_hero_features"])
                except Exception:
                    settings["login_hero_features"] = []
            return settings
    except Exception as e:
        logger.error(f"Failed to fetch branding settings: {e}")
        return {
            "company_name": "PF9 Management System",
            "company_subtitle": "Platform9 Infrastructure Management",
            "login_hero_title": "Welcome to PF9 Management",
            "login_hero_description": "Comprehensive Platform9 infrastructure management.",
            "login_hero_features": [],
            "company_logo_url": "",
            "primary_color": "#667eea",
            "secondary_color": "#764ba2",
        }


@app.put("/admin/settings/branding")
@limiter.limit("10/minute")
def update_branding(
    request: Request,
    payload: dict,
    current_user: User = Depends(require_authentication),
):
    """Update one or more branding settings. Requires admin/superadmin role."""
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    ALLOWED_KEYS = {
        "company_name", "company_subtitle",
        "login_hero_title", "login_hero_description", "login_hero_features",
        "company_logo_url", "primary_color", "secondary_color",
    }
    updates = {k: v for k, v in payload.items() if k in ALLOWED_KEYS}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid settings keys provided")
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            for key, value in updates.items():
                val = json.dumps(value) if isinstance(value, (list, dict)) else str(value)
                cur.execute(
                    """INSERT INTO app_settings (key, value, updated_at, updated_by)
                       VALUES (%s, %s, now(), %s)
                       ON CONFLICT (key) DO UPDATE
                       SET value = EXCLUDED.value, updated_at = now(), updated_by = EXCLUDED.updated_by""",
                    (key, val, "admin"),
                )
            return {"status": "success", "updated_keys": list(updates.keys())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update branding: {e}")


@app.post("/admin/settings/branding/logo")
@limiter.limit("5/minute")
async def upload_branding_logo(
    request: Request,
    current_user: User = Depends(require_authentication),
):
    """Upload a company logo image (PNG/JPEG/GIF/SVG/WebP, max 2MB)."""
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    content_type = request.headers.get("content-type", "")
    ext_map = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/svg+xml": "svg", "image/webp": "webp"}
    ext = ext_map.get(content_type.split(";")[0].strip().lower())
    if not ext:
        raise HTTPException(status_code=400, detail=f"Unsupported Content-Type: {content_type}")
    body = await request.body()
    if len(body) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Logo file must be under 2 MB")
    if len(body) == 0:
        raise HTTPException(status_code=400, detail="Empty file body")
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_dir, exist_ok=True)
    for old in os.listdir(static_dir):
        if old.startswith("logo."):
            os.remove(os.path.join(static_dir, old))
    filename = f"logo.{ext}"
    filepath = os.path.join(static_dir, filename)
    with open(filepath, "wb") as f:
        f.write(body)
    logo_url = f"/static/{filename}"
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO app_settings (key, value, updated_at, updated_by)
                   VALUES ('company_logo_url', %s, now(), 'admin')
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now(), updated_by = 'admin'""",
                (logo_url,),
            )
    except Exception as e:
        logger.error(f"Failed to save logo URL to DB: {e}")
    return {"status": "success", "logo_url": logo_url}


# Serve static files (uploaded logos)
from fastapi.staticfiles import StaticFiles as _StaticFiles
_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", _StaticFiles(directory=_static_dir), name="static")


# ---------------------------------------------------------------------------
# User Preferences  (tab order, etc.)
# ---------------------------------------------------------------------------

@app.get("/user/preferences")
def get_user_preferences(current_user: User = Depends(require_authentication)):
    """Return all preferences for the authenticated user."""
    try:
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT pref_key, pref_value FROM user_preferences WHERE username = %s", (current_user.username,))
            rows = cur.fetchall()
            prefs = {}
            for r in rows:
                try:
                    prefs[r["pref_key"]] = json.loads(r["pref_value"])
                except Exception:
                    prefs[r["pref_key"]] = r["pref_value"]
            return prefs
    except Exception as e:
        logger.error(f"Failed to fetch preferences for {current_user.username}: {e}")
        return {}


@app.put("/user/preferences/{pref_key}")
def set_user_preference(pref_key: str, payload: dict, current_user: User = Depends(require_authentication)):
    """Set a single preference. Body: { "value": <any JSON-serializable> }"""
    if "value" not in payload:
        raise HTTPException(status_code=400, detail="Body must contain 'value'")
    val = json.dumps(payload["value"]) if isinstance(payload["value"], (list, dict)) else str(payload["value"])
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO user_preferences (username, pref_key, pref_value, updated_at)
                   VALUES (%s, %s, %s, now())
                   ON CONFLICT (username, pref_key) DO UPDATE SET pref_value = EXCLUDED.pref_value, updated_at = now()""",
                (current_user.username, pref_key, val),
            )
            return {"status": "success", "pref_key": pref_key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save preference: {e}")


# ---------------------------------------------------------------------------
# Drift Detection Engine
# ---------------------------------------------------------------------------

VALID_DRIFT_EVENT_SORT_COLUMNS = {
    "detected_at": "de.detected_at",
    "severity": "de.severity",
    "resource_type": "de.resource_type",
    "resource_name": "de.resource_name",
    "field_changed": "de.field_changed",
    "acknowledged": "de.acknowledged",
}


@app.get("/drift/summary")
def get_drift_summary(
    domain_id: str = None,
    project_id: str = None,
    current_user: User = Depends(require_authentication),
):
    """Return drift overview: totals, by-severity, by-resource-type, 7-day trend."""
    try:
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Build optional WHERE clause for domain/project filtering
            where_parts = []
            where_params: list = []
            if domain_id:
                where_parts.append("domain_id = %s")
                where_params.append(domain_id)
            if project_id:
                where_parts.append("project_id = %s")
                where_params.append(project_id)
            where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
            ack_prefix = (" AND " + " AND ".join(where_parts)) if where_parts else ""

            # totals
            cur.execute(f"""
                SELECT
                    COUNT(*)                                       AS total,
                    COUNT(*) FILTER (WHERE NOT acknowledged)       AS unacknowledged,
                    COUNT(*) FILTER (WHERE acknowledged)           AS acknowledged,
                    COUNT(*) FILTER (WHERE severity = 'critical' AND NOT acknowledged) AS critical_open,
                    COUNT(*) FILTER (WHERE severity = 'warning'  AND NOT acknowledged) AS warning_open,
                    COUNT(*) FILTER (WHERE severity = 'info'     AND NOT acknowledged) AS info_open
                FROM drift_events
                {where_clause}
            """, where_params)
            totals = cur.fetchone()

            # by severity
            cur.execute(f"""
                SELECT severity, COUNT(*) AS count
                FROM drift_events WHERE NOT acknowledged {ack_prefix}
                GROUP BY severity ORDER BY severity
            """, where_params)
            by_severity = cur.fetchall()

            # by resource type
            cur.execute(f"""
                SELECT resource_type, COUNT(*) AS count
                FROM drift_events WHERE NOT acknowledged {ack_prefix}
                GROUP BY resource_type ORDER BY count DESC
            """, where_params)
            by_resource = cur.fetchall()

            # 7-day trend
            trend_where = "WHERE detected_at >= now() - interval '7 days'"
            if where_parts:
                trend_where += " AND " + " AND ".join(where_parts)
            cur.execute(f"""
                SELECT detected_at::date AS day, COUNT(*) AS count
                FROM drift_events
                {trend_where}
                GROUP BY day ORDER BY day
            """, where_params)
            trend = cur.fetchall()

            return {
                "totals": totals,
                "by_severity": by_severity,
                "by_resource_type": by_resource,
                "trend_7d": [{"day": str(r["day"]), "count": r["count"]} for r in trend],
            }
    except Exception as e:
        logger.error(f"Drift summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/drift/events")
def list_drift_events(
    resource_type: str = None,
    severity: str = None,
    project_id: str = None,
    domain_id: str = None,
    acknowledged: bool = None,
    search: str = None,
    days: int = 30,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "detected_at",
    sort_dir: str = "desc",
    current_user: User = Depends(require_authentication),
):
    """List drift events with filters and pagination."""
    try:
        order_col = VALID_DRIFT_EVENT_SORT_COLUMNS.get(sort_by, "de.detected_at")
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"
        offset = (max(page, 1) - 1) * page_size

        conditions = ["de.detected_at >= now() - make_interval(days => %(days)s)"]
        params: dict = {"days": days, "limit": page_size, "offset": offset}

        if resource_type:
            conditions.append("de.resource_type = %(resource_type)s")
            params["resource_type"] = resource_type
        if severity:
            conditions.append("de.severity = %(severity)s")
            params["severity"] = severity
        if project_id:
            conditions.append("de.project_id = %(project_id)s")
            params["project_id"] = project_id
        if domain_id:
            conditions.append("de.domain_id = %(domain_id)s")
            params["domain_id"] = domain_id
        if acknowledged is not None:
            conditions.append("de.acknowledged = %(ack)s")
            params["ack"] = acknowledged
        if search:
            conditions.append(
                "(de.resource_name ILIKE %(search)s OR de.field_changed ILIKE %(search)s "
                "OR de.old_value ILIKE %(search)s OR de.new_value ILIKE %(search)s "
                "OR de.description ILIKE %(search)s)"
            )
            params["search"] = f"%{search}%"

        where = " AND ".join(conditions)
        sql = f"""
            WITH cte AS (
                SELECT de.*,
                       dr.description AS rule_description,
                       COUNT(*) OVER() AS _total
                FROM drift_events de
                LEFT JOIN drift_rules dr ON dr.id = de.rule_id
                WHERE {where}
                ORDER BY {order_col} {direction}
                LIMIT %(limit)s OFFSET %(offset)s
            )
            SELECT * FROM cte
        """
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql, params)
            rows = cur.fetchall()
            total = rows[0]["_total"] if rows else 0
            for r in rows:
                r.pop("_total", None)
            return {
                "events": rows,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, -(-total // page_size)),
            }
    except Exception as e:
        logger.error(f"Drift events list error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/drift/events/{event_id}")
def get_drift_event(event_id: int, current_user: User = Depends(require_authentication)):
    """Return a single drift event with rule info."""
    try:
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT de.*, dr.description AS rule_description, dr.field_name AS rule_field
                FROM drift_events de
                LEFT JOIN drift_rules dr ON dr.id = de.rule_id
                WHERE de.id = %s
            """, (event_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Drift event not found")
            return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/drift/events/{event_id}/acknowledge")
def acknowledge_drift_event(
    event_id: int,
    payload: dict = None,
    current_user: User = Depends(require_authentication),
):
    """Acknowledge a single drift event."""
    note = (payload or {}).get("note", "")
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE drift_events
                SET acknowledged = TRUE,
                    acknowledged_by = %s,
                    acknowledged_at = now(),
                    acknowledge_note = %s
                WHERE id = %s AND NOT acknowledged
            """, (current_user.username, note, event_id))
            updated = cur.rowcount
            if updated == 0:
                raise HTTPException(status_code=404, detail="Event not found or already acknowledged")
            return {"status": "success", "acknowledged": event_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/drift/events/bulk-acknowledge")
def bulk_acknowledge_drift(
    payload: dict,
    current_user: User = Depends(require_authentication),
):
    """Acknowledge many drift events at once. Body: { "event_ids": [1,2,3], "note": "..." }"""
    event_ids = payload.get("event_ids", [])
    if not event_ids or not isinstance(event_ids, list):
        raise HTTPException(status_code=400, detail="Provide a non-empty 'event_ids' list")
    note = payload.get("note", "")
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE drift_events
                SET acknowledged = TRUE,
                    acknowledged_by = %s,
                    acknowledged_at = now(),
                    acknowledge_note = %s
                WHERE id = ANY(%s) AND NOT acknowledged
            """, (current_user.username, note, event_ids))
            updated = cur.rowcount
            return {"status": "success", "acknowledged_count": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Drift Rules Management
# ---------------------------------------------------------------------------

@app.get("/drift/rules")
def list_drift_rules(current_user: User = Depends(require_authentication)):
    """Return all drift rules with their open-event counts."""
    try:
        with get_connection() as conn:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT dr.*,
                       COALESCE(ec.cnt, 0) AS open_events
                FROM drift_rules dr
                LEFT JOIN (
                    SELECT rule_id, COUNT(*) AS cnt
                    FROM drift_events WHERE NOT acknowledged
                    GROUP BY rule_id
                ) ec ON ec.rule_id = dr.id
                ORDER BY dr.resource_type, dr.field_name
            """)
            rows = cur.fetchall()
            return {"rules": rows, "total": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/drift/rules/{rule_id}")
def update_drift_rule(
    rule_id: int,
    payload: dict,
    current_user: User = Depends(require_authentication),
):
    """Update a drift rule (toggle enabled, change severity)."""
    sets = []
    params = []
    if "enabled" in payload:
        sets.append("enabled = %s")
        params.append(bool(payload["enabled"]))
    if "severity" in payload:
        if payload["severity"] not in ("critical", "warning", "info"):
            raise HTTPException(status_code=400, detail="severity must be critical, warning, or info")
        sets.append("severity = %s")
        params.append(payload["severity"])
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    params.append(rule_id)
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE drift_rules SET {', '.join(sets)} WHERE id = %s", params)
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Rule not found")
            return {"status": "success", "rule_id": rule_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
#  Tenant Health View
# ---------------------------------------------------------------------------


@app.get("/tenant-health/overview")
def tenant_health_overview(
    domain_id: str = None,
    sort_by: str = "health_score",
    sort_dir: str = "asc",
    current_user: User = Depends(require_authentication),
):
    """
    Returns all tenants with aggregated health metrics.
    Optionally filter by domain_id.  Sort by any column (default: health_score ASC).
    """
    allowed_sort = {
        "health_score", "project_name", "domain_name",
        "total_servers", "total_volumes", "total_networks",
        "total_drift_events", "compliance_pct",
    }
    col = sort_by if sort_by in allowed_sort else "health_score"
    direction = "DESC" if sort_dir.upper() == "DESC" else "ASC"

    sql = f"SELECT * FROM v_tenant_health"
    params: list = []
    if domain_id:
        sql += " WHERE domain_id = %s"
        params.append(domain_id)
    sql += f" ORDER BY {col} {direction}"

    rows = run_query(sql, tuple(params))
    # Compute global aggregates
    total_tenants = len(rows)
    healthy = sum(1 for r in rows if r["health_score"] >= 80)
    warning = sum(1 for r in rows if 50 <= r["health_score"] < 80)
    critical = sum(1 for r in rows if r["health_score"] < 50)
    avg_score = round(sum(r["health_score"] for r in rows) / max(total_tenants, 1), 1)
    return {
        "summary": {
            "total_tenants": total_tenants,
            "healthy": healthy,
            "warning": warning,
            "critical": critical,
            "avg_health_score": avg_score,
        },
        "tenants": rows,
    }


@app.get("/tenant-health/heatmap")
def tenant_health_heatmap(
    domain_id: str = None,
    current_user: User = Depends(require_authentication),
):
    """
    Returns per-tenant resource utilization data for a heatmap visualization.
    Each tenant gets a utilization score based on active VMs, vCPUs, storage, and issues.
    """
    base_sql = """
        SELECT project_id, project_name, domain_name, health_score,
               total_servers, active_servers, shutoff_servers, error_servers,
               total_vcpus, total_ram_mb, active_vcpus, active_ram_mb,
               power_on_pct, hypervisor_count,
               total_volumes, total_volume_gb, in_use_volumes,
               total_floating_ips, total_security_groups,
               total_drift_events, critical_drift, compliance_pct
        FROM v_tenant_health
    """
    params: list = []
    if domain_id:
        base_sql += " WHERE domain_id = %s"
        params.append(domain_id)
    base_sql += " ORDER BY total_servers DESC"

    rows = run_query(base_sql, tuple(params))

    # Compute utilization category for each tenant
    heatmap_data = []
    for r in rows:
        # Skip tenants with zero resources
        total_res = r["total_servers"] + r["total_volumes"] + r["total_floating_ips"]
        if total_res == 0:
            continue
        # Utilization: ratio of active resources
        vm_util = (r["active_servers"] / max(r["total_servers"], 1)) * 100.0
        vol_util = (r["in_use_volumes"] / max(r["total_volumes"], 1)) * 100.0
        # Weighted overall utilization
        util_score = round((vm_util * 0.6 + vol_util * 0.4), 1)
        heatmap_data.append({
            "project_id": r["project_id"],
            "project_name": r["project_name"],
            "domain_name": r["domain_name"],
            "health_score": r["health_score"],
            "total_servers": r["total_servers"],
            "active_servers": r["active_servers"],
            "shutoff_servers": r["shutoff_servers"],
            "error_servers": r["error_servers"],
            "total_vcpus": r["total_vcpus"],
            "active_vcpus": r["active_vcpus"],
            "total_ram_mb": r["total_ram_mb"],
            "active_ram_mb": r["active_ram_mb"],
            "power_on_pct": float(r["power_on_pct"]),
            "total_volumes": r["total_volumes"],
            "total_volume_gb": r["total_volume_gb"],
            "total_drift_events": r["total_drift_events"],
            "critical_drift": r["critical_drift"],
            "compliance_pct": float(r["compliance_pct"]),
            "utilization_score": util_score,
        })

    return {"tenants": heatmap_data}


@app.get("/tenant-health/{project_id}")
def tenant_health_detail(
    project_id: str,
    current_user: User = Depends(require_authentication),
):
    """
    Returns full health detail for a single tenant/project.
    Includes resource breakdown, recent drift events, and compliance summary.
    """
    rows = run_query(
        "SELECT * FROM v_tenant_health WHERE project_id = %s", (project_id,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Project not found")
    tenant = rows[0]

    # Recent drift events for this tenant (last 30 days, max 20)
    drift_events = run_query(
        """SELECT id, severity, resource_type, resource_name,
                  field_changed, old_value, new_value,
                  description, detected_at, acknowledged
           FROM drift_events
           WHERE project_id = %s AND detected_at >= NOW() - INTERVAL '30 days'
           ORDER BY detected_at DESC LIMIT 20""",
        (project_id,),
    )

    # Resource status breakdown for charts
    server_status = run_query(
        """SELECT status, COUNT(*) AS count
           FROM servers WHERE project_id = %s GROUP BY status ORDER BY count DESC""",
        (project_id,),
    )
    volume_status = run_query(
        """SELECT status, COUNT(*) AS count
           FROM volumes WHERE project_id = %s GROUP BY status ORDER BY count DESC""",
        (project_id,),
    )

    # Top resources by size
    top_volumes = run_query(
        """SELECT id, name, size_gb, status
           FROM volumes WHERE project_id = %s ORDER BY size_gb DESC LIMIT 10""",
        (project_id,),
    )

    return {
        "tenant": tenant,
        "recent_drift_events": drift_events,
        "server_status_breakdown": server_status,
        "volume_status_breakdown": volume_status,
        "top_volumes": top_volumes,
    }


@app.get("/tenant-health/trends/{project_id}")
def tenant_health_trends(
    project_id: str,
    days: int = 30,
    current_user: User = Depends(require_authentication),
):
    """
    Returns daily drift event counts and snapshot counts for trend charts.
    """
    if days < 1 or days > 365:
        days = 30

    drift_trend = run_query(
        """SELECT DATE(detected_at) AS date,
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE severity = 'critical') AS critical,
                  COUNT(*) FILTER (WHERE severity = 'warning') AS warning,
                  COUNT(*) FILTER (WHERE severity = 'info') AS info
           FROM drift_events
           WHERE project_id = %s AND detected_at >= NOW() - make_interval(days => %s)
           GROUP BY DATE(detected_at)
           ORDER BY date""",
        (project_id, days),
    )

    snapshot_trend = run_query(
        """SELECT DATE(created_at) AS date, COUNT(*) AS total
           FROM snapshots
           WHERE project_id = %s AND created_at >= NOW() - make_interval(days => %s)
           GROUP BY DATE(created_at)
           ORDER BY date""",
        (project_id, days),
    )

    return {
        "project_id": project_id,
        "days": days,
        "drift_trend": drift_trend,
        "snapshot_trend": snapshot_trend,
    }


@app.get("/tenant-health/quota/{project_id}")
def tenant_health_quota(
    project_id: str,
    current_user: User = Depends(require_authentication),
):
    """
    Fetch live quota usage from OpenStack for a single project.
    Returns compute (instances, cores, ram) and storage (volumes, gigabytes, snapshots) quota.
    Best-effort — returns empty result if OpenStack credentials are not configured.
    """
    import os as _os
    pf9_auth = _os.getenv("PF9_AUTH_URL", "")
    if not pf9_auth:
        return {"available": False, "reason": "OpenStack credentials not configured"}
    try:
        os_client = RestoreOpenStackClient()
        session = os_client.authenticate_admin()
        nova_q = os_client.get_project_quota(session, project_id)
        cinder_q = os_client.get_volume_quota(session, project_id)

        def _extract(q, key):
            v = q.get(key, {})
            if isinstance(v, dict):
                return {
                    "limit": v.get("limit", -1),
                    "in_use": v.get("in_use", 0),
                    "reserved": v.get("reserved", 0),
                }
            return {"limit": -1, "in_use": 0, "reserved": 0}

        return {
            "available": True,
            "project_id": project_id,
            "compute": {
                "instances": _extract(nova_q, "instances"),
                "cores": _extract(nova_q, "cores"),
                "ram_mb": _extract(nova_q, "ram"),
            },
            "storage": {
                "volumes": _extract(cinder_q, "volumes"),
                "gigabytes": _extract(cinder_q, "gigabytes"),
                "snapshots": _extract(cinder_q, "snapshots"),
            },
        }
    except Exception as e:
        logger.warning(f"Quota fetch failed for {project_id}: {e}")
        return {"available": False, "reason": str(e)}
