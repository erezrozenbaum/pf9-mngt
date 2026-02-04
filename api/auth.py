"""
Authentication and Authorization Module for PF9 Management API

This module provides:
- LDAP authentication
- JWT token management
- Role-based access control
- Permission checking
"""

import os
import ldap
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

# Configuration from environment
ENABLE_AUTHENTICATION = os.getenv("ENABLE_AUTHENTICATION", "true").lower() == "true"
LDAP_SERVER = os.getenv("LDAP_SERVER", "localhost")
LDAP_PORT = int(os.getenv("LDAP_PORT", "389"))
LDAP_BASE_DN = os.getenv("LDAP_BASE_DN", "dc=pf9mgmt,dc=local")
LDAP_USER_DN = os.getenv("LDAP_USER_DN", "ou=users,dc=pf9mgmt,dc=local")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-this")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

DEFAULT_ADMIN_USER = os.getenv("DEFAULT_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin")

# Security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# Pydantic models
class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None
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
    """Get database connection for authentication operations"""
    return psycopg2.connect(
        host=os.getenv("PF9_DB_HOST", "localhost"),
        port=int(os.getenv("PF9_DB_PORT", "5432")),
        dbname=os.getenv("PF9_DB_NAME", "pf9_mgmt"),
        user=os.getenv("PF9_DB_USER", "pf9"),
        password=os.getenv("PF9_DB_PASSWORD", "pf9_password_change_me"),
    )

# LDAP Authentication
class LDAPAuthenticator:
    def __init__(self):
        self.server = f"ldap://{LDAP_SERVER}:{LDAP_PORT}"
        self.base_dn = LDAP_BASE_DN
        self.user_dn = LDAP_USER_DN

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate user against LDAP"""
        try:
            # Special case for default admin during setup
            if username == DEFAULT_ADMIN_USER and password == DEFAULT_ADMIN_PASSWORD:
                return True
                
            # Connect to LDAP server
            
            # Construct user DN - try both cn and uid formats
            user_dn_cn = f"cn={username},{self.user_dn}"
            user_dn_uid = f"uid={username},{self.user_dn}"
            
            # Try cn format first (our setup)
            try:
                conn = ldap.initialize(self.server)
                conn.protocol_version = ldap.VERSION3
                conn.set_option(ldap.OPT_REFERRALS, 0)
                conn.simple_bind_s(user_dn_cn, password)
                conn.unbind_s()
                return True
            except ldap.INVALID_CREDENTIALS:
                # Try uid format as fallback with a fresh connection
                try:
                    conn = ldap.initialize(self.server)
                    conn.protocol_version = ldap.VERSION3
                    conn.set_option(ldap.OPT_REFERRALS, 0)
                    conn.simple_bind_s(user_dn_uid, password)
                    conn.unbind_s()
                    return True
                except ldap.INVALID_CREDENTIALS:
                    return False
            
        except ldap.INVALID_CREDENTIALS:
            return False
        except ldap.LDAPError as e:
            print(f"LDAP Error: {e}")
            return False
        except Exception as e:
            print(f"Authentication Error: {e}")
            return False

    def get_user_info(self, username: str) -> Dict[str, Any]:
        """Get user information from LDAP"""
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            
            # Search for user
            search_filter = f"(uid={username})"
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
            print(f"Error getting user info: {e}")
            
        return {'username': username, 'name': username, 'email': '', 'groups': []}

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users from LDAP"""
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            
            # Bind as admin first
            admin_dn = f"cn=admin,{self.base_dn}"
            admin_password = os.getenv('LDAP_ADMIN_PASSWORD', 'r#1kajun')
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
            
            conn.unbind_s()
            return users
            
        except Exception as e:
            print(f"Error getting all users: {e}")
            return []

    def create_user(self, username: str, email: str, password: str, full_name: str = None) -> bool:
        """Create a new user in LDAP"""
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            
            # Bind as admin
            admin_dn = f"cn=admin,{self.base_dn}"
            admin_password = os.getenv('LDAP_ADMIN_PASSWORD', 'r#1kajun')
            conn.simple_bind_s(admin_dn, admin_password)
            
            # Prepare user entry
            if not full_name:
                full_name = username
                
            # Split full name into first and last name
            name_parts = full_name.split(' ', 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else first_name
            
            user_dn = f"cn={username},{self.user_dn}"
            user_attrs = [
                ('objectclass', [b'person', b'inetOrgPerson']),
                ('cn', [username.encode()]),
                ('sn', [last_name.encode()]),
                ('uid', [username.encode()]),
                ('mail', [email.encode()]),
                ('userPassword', [password.encode()]),
                ('description', [b'Created via management system'])
            ]
            
            if first_name != last_name:
                user_attrs.append(('givenName', [first_name.encode()]))
            
            conn.add_s(user_dn, user_attrs)
            conn.unbind_s()
            
            print(f"User {username} created successfully in LDAP")
            return True
            
        except Exception as e:
            print(f"Error creating user {username}: {e}")
            return False

    def delete_user(self, username: str) -> bool:
        """Delete a user from LDAP"""
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            
            # Bind as admin
            admin_dn = f"cn=admin,{self.base_dn}"
            admin_password = os.getenv('LDAP_ADMIN_PASSWORD', 'r#1kajun')
            conn.simple_bind_s(admin_dn, admin_password)
            
            # Delete user
            user_dn = f"cn={username},{self.user_dn}"
            conn.delete_s(user_dn)
            conn.unbind_s()
            
            print(f"User {username} deleted successfully from LDAP")
            return True
            
        except Exception as e:
            print(f"Error deleting user {username}: {e}")
            return False

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
    """Verify and decode JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None:
            return None
        token_data = TokenData(username=username, role=role)
        return token_data
    except JWTError:
        return None

# User Management
def get_user_role(username: str) -> Optional[str]:
    """Get user role from database"""
    try:
        conn = get_auth_db_conn()
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
        print(f"Error getting user role: {e}")
        return "viewer"

def set_user_role(username: str, role: str, granted_by: str = "system") -> bool:
    """Set user role in database"""
    try:
        conn = get_auth_db_conn()
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
            
            conn.commit()
            return True
    except Exception as e:
        print(f"Error setting user role: {e}")
        return False

def has_permission(username: str, resource: str, permission: str) -> bool:
    """Check if user has permission for resource"""
    if not ENABLE_AUTHENTICATION:
        return True
        
    role = get_user_role(username)
    if not role:
        return False
        
    try:
        conn = get_auth_db_conn()
        with conn.cursor() as cur:
            # Check for specific action (read, write, admin)
            cur.execute("""
                SELECT 1 FROM role_permissions 
                WHERE role = %s AND resource = %s 
                AND (action = %s OR action = 'admin')
            """, (role, resource, permission))
            result = cur.fetchone()
            if result:
                return True
            
            # Also check for wildcard resource
            cur.execute("""
                SELECT 1 FROM role_permissions 
                WHERE role = %s AND resource = '*'
                AND (action = %s OR action = 'admin')
            """, (role, permission))
            return cur.fetchone() is not None
    except Exception as e:
        print(f"Error checking permissions: {e}")
        return False

# Session Management
def create_user_session(username: str, role: str, token: str, ip_address: str = None, user_agent: str = None):
    """Create user session record"""
    try:
        conn = get_auth_db_conn()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_sessions (username, token_hash, expires_at, ip_address, user_agent)
                VALUES (%s, %s, %s, %s, %s)
            """, (username, token_hash, expires_at, ip_address, user_agent))
            conn.commit()
    except Exception as e:
        print(f"Error creating session: {e}")

def invalidate_user_session(token: str):
    """Invalidate user session"""
    try:
        conn = get_auth_db_conn()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE user_sessions SET is_active = false 
                WHERE token_hash = %s
            """, (token_hash,))
            conn.commit()
    except Exception as e:
        print(f"Error invalidating session: {e}")

def log_auth_event(username: str, action: str, success: bool = True, ip_address: str = None, 
                   user_agent: str = None, resource: str = None, endpoint: str = None, details: dict = None):
    """Log authentication/authorization events"""
    try:
        conn = get_auth_db_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO auth_audit_log (username, action, success, ip_address, user_agent, 
                                           resource, endpoint, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (username, action, success, ip_address, user_agent, resource, endpoint, details))
            conn.commit()
    except Exception as e:
        print(f"Error logging auth event: {e}")

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
    ) -> bool:
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

        return True

    return dependency

# Initialize default admin user on startup
def initialize_default_admin():
    """Initialize default admin user if it doesn't exist"""
    try:
        if ENABLE_AUTHENTICATION and DEFAULT_ADMIN_USER and DEFAULT_ADMIN_PASSWORD:
            set_user_role(DEFAULT_ADMIN_USER, "superadmin", "system")
            print(f"Default admin user '{DEFAULT_ADMIN_USER}' initialized")
    except Exception as e:
        print(f"Error initializing default admin: {e}")