"""
Authentication and Authorization Module for PF9 Management API

This module provides:
- LDAP authentication
- JWT token management
- Role-based access control
- Permission checking
"""

import os
import hmac
import logging
import ldap
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from functools import wraps

logger = logging.getLogger(__name__)

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from secret_helper import read_secret

from db_pool import get_connection

# Configuration from environment
ENABLE_AUTHENTICATION = os.getenv("ENABLE_AUTHENTICATION", "true").lower() == "true"
LDAP_SERVER = os.getenv("LDAP_SERVER", "localhost")
LDAP_PORT = int(os.getenv("LDAP_PORT", "389"))
LDAP_BASE_DN = os.getenv("LDAP_BASE_DN", "dc=pf9mgmt,dc=local")
LDAP_USER_DN = os.getenv("LDAP_USER_DN", "ou=users,dc=pf9mgmt,dc=local")

_jwt_env = read_secret("jwt_secret", env_var="JWT_SECRET_KEY")
if not _jwt_env:
    _jwt_env = secrets.token_urlsafe(48)
    logger.warning(
        "JWT_SECRET_KEY not set — generated a random ephemeral key. "
        "Sessions will be invalidated on every restart. Set JWT_SECRET_KEY in .env."
    )
JWT_SECRET_KEY = _jwt_env
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

DEFAULT_ADMIN_USER = os.getenv("DEFAULT_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "")

# Security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# Pydantic models
class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user: Optional["User"] = None

class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None

class User(BaseModel):
    username: str
    role: str
    is_active: bool = True

class LoginRequest(BaseModel):
    username: str
    password: str

class UserRole(BaseModel):
    username: str
    role: str

# Database connection helper
def get_auth_db_conn():
    """Get database connection for authentication operations.
    DEPRECATED: prefer `with get_connection() as conn:` from db_pool.
    Kept for backward compat — returns a pooled connection.
    """
    from db_pool import get_pool
    return get_pool().getconn()

# LDAP Authentication
class LDAPAuthenticator:
    def __init__(self):
        self.server = f"ldap://{LDAP_SERVER}:{LDAP_PORT}"
        self.base_dn = LDAP_BASE_DN
        self.user_dn = LDAP_USER_DN

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate user against LDAP"""
        try:
            # Special case for default admin during setup (only if password is configured)
            if DEFAULT_ADMIN_PASSWORD and username == DEFAULT_ADMIN_USER and hmac.compare_digest(password, DEFAULT_ADMIN_PASSWORD):
                return True
                
            # Connect to LDAP server
            
            # Construct user DN - try both cn and uid formats
            user_dn_cn = f"cn={username},{self.user_dn}"
            user_dn_uid = f"uid={username},{self.user_dn}"
            
            # Try cn format first (our setup)
            try:
                logger.debug("[AUTH] Trying CN format: %s", user_dn_cn)
                conn = ldap.initialize(self.server)
                conn.protocol_version = ldap.VERSION3
                conn.set_option(ldap.OPT_REFERRALS, 0)
                conn.simple_bind_s(user_dn_cn, password)
                conn.unbind_s()
                logger.debug("[AUTH] CN format successful for %s", username)
                return True
            except ldap.INVALID_CREDENTIALS as e:
                logger.debug("[AUTH] CN format failed: %s", e)
                # Try uid format as fallback with a fresh connection
                try:
                    logger.debug("[AUTH] Trying UID format: %s", user_dn_uid)
                    conn = ldap.initialize(self.server)
                    conn.protocol_version = ldap.VERSION3
                    conn.set_option(ldap.OPT_REFERRALS, 0)
                    conn.simple_bind_s(user_dn_uid, password)
                    conn.unbind_s()
                    logger.debug("[AUTH] UID format successful for %s", username)
                    return True
                except ldap.INVALID_CREDENTIALS as e2:
                    logger.debug("[AUTH] UID format also failed: %s", e2)
                    return False

        except ldap.INVALID_CREDENTIALS:
            logger.warning("[AUTH] Invalid credentials for %s", username)
            return False
        except ldap.LDAPError as e:
            logger.error("[AUTH] LDAP error for %s: %s", username, e)
            return False
        except Exception as e:
            logger.error("[AUTH] Unexpected error for %s: %s", username, e)
            return False

    def get_user_info(self, username: str) -> Dict[str, Any]:
        """Get user information from LDAP"""
        conn = None
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            
            # Search for user — escape username to prevent LDAP injection
            safe_username = ldap.filter.escape_filter_chars(username)
            search_filter = f"(uid={safe_username})"
            attrs = ['uid', 'cn', 'mail', 'memberOf']
            
            result = conn.search_s(self.user_dn, ldap.SCOPE_SUBTREE, search_filter, attrs)
            
            if result:
                dn, attrs = result[0]
                return {
                    'username': attrs.get('uid', [username.encode()])[0].decode(),
                    'name': attrs.get('cn', [username.encode()])[0].decode(),
                    'email': attrs.get('mail', [b''])[0].decode(),
                    'groups': [g.decode() for g in attrs.get('memberOf', [])]
                }
                
        except Exception as e:
            logger.error("Error getting user info for %s: %s", username, e)
        finally:
            if conn is not None:
                try:
                    conn.unbind_s()
                except Exception:
                    pass

        return {'username': username, 'name': username, 'email': '', 'groups': []}

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users from LDAP"""
        conn = None
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            
            # Bind as admin first
            admin_dn = f"cn=admin,{self.base_dn}"
            admin_password = read_secret("ldap_admin_password", env_var="LDAP_ADMIN_PASSWORD")
            conn.simple_bind_s(admin_dn, admin_password)
            
            # Search for all users
            search_filter = "(objectclass=person)"
            attrs = ['uid', 'cn', 'mail', 'sn', 'givenName']
            
            results = conn.search_s(self.user_dn, ldap.SCOPE_SUBTREE, search_filter, attrs)
            
            users = []
            for dn, attrs in results:
                if 'uid' in attrs:  # Ensure it's a user entry
                    users.append({
                        'id': attrs.get('uid', [b''])[0].decode(),
                        'username': attrs.get('uid', [b''])[0].decode(),
                        'name': attrs.get('cn', [b''])[0].decode(),
                        'email': attrs.get('mail', [b''])[0].decode(),
                        'firstName': attrs.get('givenName', [b''])[0].decode() if 'givenName' in attrs else '',
                        'lastName': attrs.get('sn', [b''])[0].decode() if 'sn' in attrs else ''
                    })
            
            return users
            
        except Exception as e:
            logger.error("Error getting all LDAP users: %s", e)
            return []
        finally:
            if conn is not None:
                try:
                    conn.unbind_s()
                except Exception:
                    pass

    def create_user(self, username: str, email: str, password: str, full_name: str = None) -> bool:
        """Create a new user in LDAP"""
        conn = None
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            
            # Bind as admin
            admin_dn = f"cn=admin,{self.base_dn}"
            admin_password = read_secret("ldap_admin_password", env_var="LDAP_ADMIN_PASSWORD")
            conn.simple_bind_s(admin_dn, admin_password)
            
            # Prepare user entry
            if not full_name:
                full_name = username
                
            # Split full name into first and last name
            name_parts = full_name.split(' ', 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else first_name
            
            user_dn = f"cn={username},{self.user_dn}"
            # Hash the password with SSHA before writing to LDAP
            # (same algorithm used by change_password)
            import base64
            salt = secrets.token_bytes(4)
            # SSHA is the LDAP wire format; not used as a cryptographic security primitive
            h = hashlib.sha1(password.encode('utf-8') + salt, usedforsecurity=False)  # nosec B324
            hashed_password = '{SSHA}' + base64.b64encode(h.digest() + salt).decode()
            user_attrs = [
                ('objectclass', [b'person', b'inetOrgPerson']),
                ('cn', [username.encode()]),
                ('sn', [last_name.encode()]),
                ('uid', [username.encode()]),
                ('mail', [email.encode()]),
                ('userPassword', [hashed_password.encode('utf-8')]),
                ('description', [b'Created via management system'])
            ]
            
            if first_name != last_name:
                user_attrs.append(('givenName', [first_name.encode()]))
            
            conn.add_s(user_dn, user_attrs)
            logger.info("User %s created successfully in LDAP", username)
            return True

        except Exception as e:
            logger.error("Error creating user %s in LDAP: %s", username, e)
            return False
        finally:
            if conn is not None:
                try:
                    conn.unbind_s()
                except Exception:
                    pass

    def delete_user(self, username: str) -> bool:
        """Delete a user from LDAP"""
        conn = None
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            
            # Bind as admin
            admin_dn = f"cn=admin,{self.base_dn}"
            admin_password = read_secret("ldap_admin_password", env_var="LDAP_ADMIN_PASSWORD")
            conn.simple_bind_s(admin_dn, admin_password)
            
            # Delete user
            user_dn = f"cn={username},{self.user_dn}"
            conn.delete_s(user_dn)
            logger.info("User %s deleted successfully from LDAP", username)
            return True

        except Exception as e:
            logger.error("Error deleting user %s from LDAP: %s", username, e)
            return False
        finally:
            if conn is not None:
                try:
                    conn.unbind_s()
                except Exception:
                    pass

    def change_password(self, username: str, new_password: str) -> bool:
        """Reset a user's LDAP password (admin operation using SSHA hash)."""
        import base64
        conn = None
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            admin_dn = f"cn=admin,{self.base_dn}"
            conn.simple_bind_s(admin_dn, read_secret("ldap_admin_password", env_var="LDAP_ADMIN_PASSWORD"))
            salt = secrets.token_bytes(4)
            # SSHA is the LDAP wire format; not used as a cryptographic security primitive
            h = hashlib.sha1(new_password.encode('utf-8') + salt, usedforsecurity=False)  # nosec B324
            hashed = '{SSHA}' + base64.b64encode(h.digest() + salt).decode()
            user_dn = f"cn={username},{self.user_dn}"
            conn.modify_s(user_dn, [(ldap.MOD_REPLACE, 'userPassword', [hashed.encode('utf-8')])])
            logger.info("Password changed for user %s", username)
            return True
        except Exception as e:
            logger.error("Error changing password for %s: %s", username, e)
            return False
        finally:
            if conn is not None:
                try:
                    conn.unbind_s()
                except Exception:
                    pass

# JWT Token Management
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[TokenData]:
    """Verify JWT token and confirm the session has not been revoked (e.g. after logout)"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None:
            return None
        # Check the session is still active in the DB (catches post-logout token reuse)
        try:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM user_sessions "
                        "WHERE token_hash = %s AND is_active = true AND expires_at > NOW()",
                        (token_hash,),
                    )
                    if cur.fetchone() is None:
                        return None
        except Exception:
            # DB unavailable — fall back to JWT-only validation; revocation cannot
            # be enforced but the JWT signature and expiry still hold.
            pass
        return TokenData(username=username, role=role)
    except JWTError:
        return None

# User Management
def get_user_role(username: str) -> Optional[str]:
    """Get user role from database"""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT role FROM user_roles 
                    WHERE username = %s AND is_active = true
                """, (username,))
                result = cur.fetchone()
                if result:
                    return result['role']
                
                # If no role found, assign default role for known admin
                if username == DEFAULT_ADMIN_USER:
                    return "superadmin"
                
                # Default role for new users
                return "viewer"
            
    except Exception as e:
        logger.error("Error getting user role for %s: %s", username, e)
        return "viewer"

def set_user_role(username: str, role: str, granted_by: str = "system") -> bool:
    """Set user role in database"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Check if user already exists
                cur.execute("SELECT id FROM user_roles WHERE username = %s", (username,))
                existing = cur.fetchone()
                
                if existing:
                    # Update existing role
                    cur.execute("""
                        UPDATE user_roles 
                        SET role = %s, granted_by = %s, is_active = true
                        WHERE username = %s
                    """, (role, granted_by, username))
                else:
                    # Insert new role
                    cur.execute("""
                        INSERT INTO user_roles (username, role, granted_by, granted_at, is_active)
                        VALUES (%s, %s, %s, now(), true)
                    """, (username, role, granted_by))
            # auto-commit via context manager
            return True
    except Exception as e:
        logger.error("Error setting user role for %s: %s", username, e)
        return False

def has_permission(username: str, resource: str, permission: str) -> bool:
    """Check if user has permission for resource"""
    if not ENABLE_AUTHENTICATION:
        return True
        
    role = get_user_role(username)
    if not role:
        return False
        
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Check for specific action (read, write, admin)
                # write implies read, admin implies both read and write
                if permission == 'read':
                    action_clause = "action IN ('read', 'write', 'admin')"
                elif permission == 'write':
                    action_clause = "action IN ('write', 'admin')"
                else:
                    action_clause = "(action = %s OR action = 'admin')"
                
                if permission in ('read', 'write'):
                    cur.execute(f"""
                        SELECT 1 FROM role_permissions 
                        WHERE role = %s AND resource = %s 
                        AND {action_clause}
                    """, (role, resource))
                else:
                    cur.execute("""
                        SELECT 1 FROM role_permissions 
                        WHERE role = %s AND resource = %s 
                        AND (action = %s OR action = 'admin')
                    """, (role, resource, permission))
                result = cur.fetchone()
                if result:
                    return True
                
                # Also check for wildcard resource
                if permission in ('read', 'write'):
                    cur.execute(f"""
                        SELECT 1 FROM role_permissions 
                        WHERE role = %s AND resource = '*'
                        AND {action_clause}
                    """, (role,))
                else:
                    cur.execute("""
                        SELECT 1 FROM role_permissions 
                        WHERE role = %s AND resource = '*'
                        AND (action = %s OR action = 'admin')
                    """, (role, permission))
                return cur.fetchone() is not None
    except Exception as e:
        logger.error("Error checking permissions for %s/%s/%s: %s", username, resource, permission, e)
        return False

# Session Management
def create_user_session(username: str, role: str, token: str, ip_address: str = None, user_agent: str = None):
    """Create user session record"""
    try:
        with get_connection() as conn:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            expires_at = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
            
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_sessions (username, role, token_hash, expires_at, ip_address, user_agent)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (username, role, token_hash, expires_at, ip_address, user_agent))
    except Exception as e:
        logger.error("Error creating session for %s: %s", username, e)

def invalidate_user_session(token: str):
    """Invalidate user session"""
    try:
        with get_connection() as conn:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE user_sessions SET is_active = false 
                    WHERE token_hash = %s
                """, (token_hash,))
    except Exception as e:
        logger.error("Error invalidating session: %s", e)

def log_auth_event(username: str, action: str, success: bool = True, ip_address: str = None, 
                   user_agent: str = None, resource: str = None, endpoint: str = None, details: dict = None):
    """Log authentication/authorization events"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO auth_audit_log (username, action, success, ip_address, user_agent, 
                                               resource, endpoint, details)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (username, action, success, ip_address, user_agent, resource, endpoint, details))
    except Exception as e:
        logger.error("Error logging auth event for %s/%s: %s", username, action, e)

# FastAPI Dependencies
ldap_auth = LDAPAuthenticator()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[User]:
    """Get current authenticated user"""
    if not ENABLE_AUTHENTICATION:
        # Return default admin user when authentication is disabled
        return User(username="admin", role="superadmin")
        
    if not credentials:
        return None
        
    token_data = verify_token(credentials.credentials)
    if not token_data:
        return None
        
    role = get_user_role(token_data.username)
    return User(username=token_data.username, role=role)

async def require_authentication(user: User = Depends(get_current_user)) -> User:
    """Require authenticated user"""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def require_permission(resource: str, permission: str):
    """FastAPI dependency to require specific permission"""
    async def dependency(
        current_user: User = Depends(get_current_user),
        request: Request = None
    ) -> dict:
        user = current_user

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )

        if not has_permission(user.username, resource, permission):
            log_auth_event(
                user.username, "permission_denied", False,
                request.client.host if request and request.client else None,
                request.headers.get('user-agent') if request else None,
                resource, request.url.path if request else None
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions for {resource}:{permission}"
            )

        return user.model_dump()

    return dependency

# Initialize default admin user on startup
def initialize_default_admin():
    """Initialize default admin user if it doesn't exist"""
    try:
        if ENABLE_AUTHENTICATION and DEFAULT_ADMIN_USER and DEFAULT_ADMIN_PASSWORD:
            set_user_role(DEFAULT_ADMIN_USER, "superadmin", "system")
            logger.info("Default admin user '%s' initialized", DEFAULT_ADMIN_USER)
    except Exception as e:
        logger.error("Error initializing default admin: %s", e)


# ---------------------------------------------------------------------------
# Phase 6: Region-scoped RBAC helpers
# ---------------------------------------------------------------------------

def get_user_accessible_regions(username: str) -> Optional[List[str]]:
    """
    Return the list of region IDs this user is scoped to, or None for global access.

    user_roles.region_id is NULL for global admins (existing behaviour).
    When non-NULL, the user may only access that specific region.
    Returning None means "no restriction" so all callers preserve the existing
    single-region default behaviour without any code change.
    """
    if not ENABLE_AUTHENTICATION:
        return None  # auth disabled — global access
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT region_id FROM user_roles WHERE username = %s AND is_active = TRUE",
                    (username,),
                )
                row = cur.fetchone()
                if not row or row[0] is None:
                    return None  # global access
                return [row[0]]
    except Exception as e:
        logger.error("Error checking region restriction for %s: %s", username, e)
        return None  # fail open — global access on error


def get_effective_region_filter(username: str, requested_region_id: Optional[str]) -> Optional[str]:
    """
    Resolve the region_id to use for DB / API filtering.

    Rules:
    - User has no region restriction (NULL)  + caller passes region_id  → use requested
    - User has no region restriction         + caller passes nothing      → None (all regions)
    - User is region-scoped                  + caller passes matching id  → return user's region
    - User is region-scoped                  + caller passes nothing      → return user's region
    - User is region-scoped                  + caller passes different id → 403

    This is the single entry-point for every Phase 6 endpoint that accepts ?region_id=.
    Enforcing region RBAC here (rather than in middleware) keeps the logic co-located
    with the parameter that enables it and satisfies the OWASP A01 requirement stated
    in MULTICLUSTER_PLAN Phase 6.
    """
    allowed = get_user_accessible_regions(username)
    if allowed is None:
        # Global access — respect whatever the caller passed (may be None)
        return requested_region_id
    # User is region-scoped
    user_region = allowed[0]
    if requested_region_id and requested_region_id != user_region:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: you are not authorised for region '{requested_region_id}'",
        )
    return user_region