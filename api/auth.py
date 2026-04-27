"""
Authentication and Authorization Module for PF9 Management API

This module provides:
- LDAP authentication
- JWT token management
- Role-based access control
- Permission checking
"""

import ipaddress
import os
import socket
import hmac
import logging
import ldap
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
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
from request_helpers import get_request_ip

# Configuration from environment
ENABLE_AUTHENTICATION = os.getenv("ENABLE_AUTHENTICATION", "true").lower() == "true"
LDAP_SERVER = os.getenv("LDAP_SERVER", "localhost")
LDAP_PORT = int(os.getenv("LDAP_PORT", "389"))
LDAP_BASE_DN = os.getenv("LDAP_BASE_DN", "dc=pf9mgmt,dc=local")
LDAP_USER_DN = os.getenv("LDAP_USER_DN", "ou=users,dc=pf9mgmt,dc=local")
LDAP_GROUP_DN = os.getenv("LDAP_GROUP_DN", "ou=groups,dc=pf9mgmt,dc=local")

_jwt_env = read_secret("jwt_secret", env_var="JWT_SECRET_KEY")
if not _jwt_env:
    if os.getenv("PRODUCTION_MODE", "").lower() in ("true", "1", "yes"):
        raise RuntimeError(
            "PRODUCTION_MODE is enabled but JWT_SECRET_KEY is not configured. "
            "Set the jwt_secret Docker secret or JWT_SECRET_KEY environment variable "
            "before starting the API service."
        )
    _jwt_env = secrets.token_urlsafe(48)
    logger.warning(
        "JWT_SECRET_KEY not set — generated a random ephemeral key. "
        "Sessions will be invalidated on every restart. Set JWT_SECRET_KEY in .env."
    )
JWT_SECRET_KEY = _jwt_env
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))

# Redis client for fast jti-based token revocation (H11)
_revocation_client = None


def _get_revocation_client():
    """Return a Redis client for the jti revocation set, or None if unavailable."""
    global _revocation_client
    if _revocation_client is not None:
        try:
            _revocation_client.ping()
            return _revocation_client
        except Exception:
            _revocation_client = None
    try:
        import redis as _redis_lib
        _redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        c = _redis_lib.from_url(
            _redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        c.ping()
        _revocation_client = c
    except Exception as _exc:
        logger.debug("Redis revocation client unavailable: %s", _exc)
        _revocation_client = None
    return _revocation_client


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

# SSRF guard — private/loopback ranges blocked for external LDAP connections
_BLOCKED_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

# LDAP Authentication
class LDAPAuthenticator:
    def __init__(self):
        self.server = f"ldap://{LDAP_SERVER}:{LDAP_PORT}"
        self.base_dn = LDAP_BASE_DN
        self.user_dn = LDAP_USER_DN

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate user against LDAP.

        For users with sync_source='external_ldap' the credential is validated
        against their originating directory (passthrough auth).  All other users
        authenticate against the internal OpenLDAP instance unchanged.
        """
        try:
            # Special case for default admin during setup (only if password is configured)
            if DEFAULT_ADMIN_PASSWORD and username == DEFAULT_ADMIN_USER and hmac.compare_digest(password, DEFAULT_ADMIN_PASSWORD):
                return True

            # ── External LDAP passthrough ───────────────────────────────────
            # One DB round-trip (JOIN) per external-user login.  Local users pay
            # zero extra cost because the query returns nothing for them.
            try:
                with get_connection() as _conn:
                    with _conn.cursor(cursor_factory=RealDictCursor) as _cur:
                        _cur.execute(
                            """
                            SELECT lsc.host, lsc.port, lsc.use_tls, lsc.use_starttls,
                                   lsc.verify_tls_cert, lsc.ca_cert_pem,
                                   lsc.bind_password_enc, lsc.bind_dn,
                                   lsc.base_dn, lsc.user_attr_uid, lsc.id AS config_id
                            FROM user_roles ur
                            JOIN ldap_sync_config lsc
                                ON lsc.id = ur.sync_config_id AND lsc.is_enabled = TRUE
                            WHERE ur.username = %s AND ur.sync_source = 'external_ldap'
                            """,
                            (username,),
                        )
                        _ext_cfg = _cur.fetchone()

                if _ext_cfg:
                    return self._bind_external_ldap(dict(_ext_cfg), username, password)
            except Exception as _exc:
                # DB lookup failure must not silently fall through to internal — raise 503.
                logger.error("[AUTH] External LDAP config lookup failed for %s: %s", username, _exc)
                raise HTTPException(
                    status_code=503,
                    detail="Authentication service temporarily unavailable",
                )
            # ── End external passthrough ────────────────────────────────────

            # Connect to LDAP server
            
            # Construct user DN - try both cn and uid formats
            _safe_un = ldap.dn.escape_dn_chars(username)
            user_dn_cn = f"cn={_safe_un},{self.user_dn}"
            user_dn_uid = f"uid={_safe_un},{self.user_dn}"
            
            # Try cn format first (our setup) — guaranteed unbind via finally
            conn = None
            _cn_ok = False
            try:
                logger.debug("[AUTH] Trying CN format: %s", user_dn_cn)
                conn = ldap.initialize(self.server)
                conn.protocol_version = ldap.VERSION3
                conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
                conn.set_option(ldap.OPT_REFERRALS, 0)
                conn.simple_bind_s(user_dn_cn, password)
                logger.debug("[AUTH] CN format successful for %s", username)
                _cn_ok = True
            except ldap.INVALID_CREDENTIALS as e:
                logger.debug("[AUTH] CN format failed: %s", e)
            finally:
                if conn is not None:
                    try:
                        conn.unbind_s()
                    except Exception:
                        pass
                    conn = None

            if _cn_ok:
                return True

            # Try uid format as fallback — guaranteed unbind via finally
            conn = None
            try:
                logger.debug("[AUTH] Trying UID format: %s", user_dn_uid)
                conn = ldap.initialize(self.server)
                conn.protocol_version = ldap.VERSION3
                conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
                conn.set_option(ldap.OPT_REFERRALS, 0)
                conn.simple_bind_s(user_dn_uid, password)
                logger.debug("[AUTH] UID format successful for %s", username)
                return True
            except ldap.INVALID_CREDENTIALS as e2:
                logger.debug("[AUTH] UID format also failed: %s", e2)
                return False
            finally:
                if conn is not None:
                    try:
                        conn.unbind_s()
                    except Exception:
                        pass

        except ldap.INVALID_CREDENTIALS:
            logger.warning("[AUTH] Invalid credentials for %s", username)
            return False
        except ldap.LDAPError as e:
            logger.error("[AUTH] LDAP error for %s: %s", username, e)
            return False
        except Exception as e:
            logger.error("[AUTH] Unexpected error for %s: %s", username, e)
            return False

    def _bind_external_ldap(self, cfg: Dict[str, Any], username: str, password: str) -> bool:
        """Authenticate *username* against an external LDAP/AD directory.

        Called only when user_roles.sync_source = 'external_ldap'.

        Returns True on success, False on INVALID_CREDENTIALS.
        Raises HTTP 503 on connectivity failure, timeout, or decryption error.
        """
        from crypto_helper import fernet_decrypt as _fernet_decrypt

        config_id = cfg.get("config_id", "unknown")

        # SSRF guard — re-validate host at connection time (defence-in-depth;
        # the host was checked at config-save time but the DB record could have
        # been modified directly.  RFC-1918 / loopback are blocked unless the
        # operator explicitly set allow_private_network = true on this config.)
        if not cfg.get("allow_private_network", False):
            try:
                addr_str = socket.getaddrinfo(cfg["host"], None)[0][4][0]
                addr = ipaddress.ip_address(addr_str)
                for _blocked in _BLOCKED_RANGES:
                    if addr in _blocked:
                        logger.error(
                            "[AUTH] SSRF guard blocked connection to private host %s (%s) "
                            "for config %s", cfg["host"], addr_str, config_id
                        )
                        raise HTTPException(
                            status_code=503,
                            detail="Authentication service configuration error",
                        )
            except socket.gaierror:
                logger.error("[AUTH] Cannot resolve external LDAP host '%s'", cfg["host"])
                raise HTTPException(
                    status_code=503, detail="Authentication service unavailable"
                )

        # Decrypt service-account bind password
        svc_password = _fernet_decrypt(
            cfg["bind_password_enc"],
            secret_name="ldap_sync_key",
            env_var="LDAP_SYNC_KEY",
            context=f"config_id={config_id}",
        )
        if not svc_password:
            logger.error("[AUTH] Cannot decrypt external LDAP password for config %s", config_id)
            raise HTTPException(status_code=503, detail="Authentication service configuration error")

        scheme = "ldaps" if cfg.get("use_tls") and not cfg.get("use_starttls") else "ldap"
        uri = f"{scheme}://{cfg['host']}:{cfg['port']}"

        try:
            conn = ldap.initialize(uri)
            conn.protocol_version = ldap.VERSION3
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
            conn.set_option(ldap.OPT_REFERRALS, 0)

            if not cfg.get("verify_tls_cert", True):
                logger.warning(
                    "[AUTH] TLS certificate validation DISABLED for external LDAP host %s "
                    "(config %s) -- connections are vulnerable to MITM attacks. "
                    "Set verify_tls_cert=true in the LDAP sync config to enforce certificate validation.",
                    cfg["host"], config_id,
                )
                conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
                conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
            if cfg.get("use_starttls"):
                conn.start_tls_s()

            # Service-account bind to locate the user's full DN — guaranteed unbind
            try:
                conn.simple_bind_s(cfg["bind_dn"], svc_password)

                uid_attr = cfg.get("user_attr_uid", "sAMAccountName")
                safe_uid = ldap.filter.escape_filter_chars(username)
                results = conn.search_s(
                    cfg["base_dn"], ldap.SCOPE_SUBTREE,
                    f"({uid_attr}={safe_uid})", ["dn"],
                )
            finally:
                try:
                    conn.unbind_s()
                except Exception:
                    pass

            if not results:
                logger.warning("[AUTH] External LDAP: user '%s' not found in config %s", username, config_id)
                return False

            user_dn = results[0][0]

            # End-user simple bind — validates the supplied password
            user_conn = ldap.initialize(uri)
            user_conn.protocol_version = ldap.VERSION3
            user_conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
            user_conn.set_option(ldap.OPT_REFERRALS, 0)
            if not cfg.get("verify_tls_cert", True):
                logger.warning(
                    "[AUTH] TLS certificate validation DISABLED for end-user bind to external LDAP host %s "
                    "(config %s) -- connections are vulnerable to MITM attacks.",
                    cfg["host"], config_id,
                )
                user_conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
                user_conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
            if cfg.get("use_starttls"):
                user_conn.start_tls_s()

            try:
                user_conn.simple_bind_s(user_dn, password)
                logger.debug("[AUTH] External LDAP auth successful for %s (config %s)", username, config_id)
                return True
            finally:
                try:
                    user_conn.unbind_s()
                except Exception:
                    pass

        except ldap.INVALID_CREDENTIALS:
            logger.warning("[AUTH] External LDAP invalid credentials for %s (config %s)", username, config_id)
            return False
        except (ldap.SERVER_DOWN, ldap.TIMEOUT) as exc:
            logger.error("[AUTH] External LDAP unreachable for config %s: %s", config_id, exc)
            raise HTTPException(status_code=503, detail="External authentication server is unreachable")
        except ldap.LDAPError as exc:
            logger.error("[AUTH] External LDAP error for %s (config %s): %s", username, config_id, exc)
            raise HTTPException(status_code=503, detail="External authentication server error")

    def get_user_info(self, username: str) -> Dict[str, Any]:
        """Get user information from LDAP"""
        conn = None
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
            
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

    def ensure_ldap_structure(self) -> None:
        """Idempotent bootstrap: create ou=users, ou=groups and the default admin
        app-user in LDAP if they are absent.  Called once at API startup so that
        a fresh K8s deployment (where the LDAP StatefulSet starts with an empty
        directory) is self-healing without manual ldapadd commands.
        """
        conn = None
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
            ldap_admin_dn = f"cn=admin,{self.base_dn}"
            ldap_admin_password = read_secret("ldap_admin_password", env_var="LDAP_ADMIN_PASSWORD")
            conn.simple_bind_s(ldap_admin_dn, ldap_admin_password)

            # Create ou=users if missing
            for ou_dn, ou_name in [(LDAP_USER_DN, b'users'), (LDAP_GROUP_DN, b'groups')]:
                try:
                    conn.add_s(ou_dn, [
                        ('objectclass', [b'organizationalUnit']),
                        ('ou', [ou_name]),
                    ])
                    logger.info("[LDAP] Created OU: %s", ou_dn)
                except ldap.ALREADY_EXISTS:
                    pass
                except Exception as e:
                    logger.warning("[LDAP] Could not create OU %s: %s", ou_dn, e)

            # Create the default admin app-user in LDAP if not present
            if DEFAULT_ADMIN_USER and DEFAULT_ADMIN_PASSWORD:
                admin_user_dn = f"cn={ldap.dn.escape_dn_chars(DEFAULT_ADMIN_USER)},{self.user_dn}"
                try:
                    import base64 as _b64
                    _salt = secrets.token_bytes(4)
                    _h = hashlib.sha1(
                        DEFAULT_ADMIN_PASSWORD.encode('utf-8') + _salt,
                        usedforsecurity=False,  # nosec B324
                    )
                    _hpw = '{SSHA}' + _b64.b64encode(_h.digest() + _salt).decode()
                    conn.add_s(admin_user_dn, [
                        ('objectclass', [b'person', b'inetOrgPerson']),
                        ('cn', [DEFAULT_ADMIN_USER.encode()]),
                        ('sn', [DEFAULT_ADMIN_USER.encode()]),
                        ('uid', [DEFAULT_ADMIN_USER.encode()]),
                        ('mail', [f'{DEFAULT_ADMIN_USER}@local'.encode()]),
                        ('userPassword', [_hpw.encode('utf-8')]),
                        ('description', [b'Default admin (auto-created at startup)']),
                    ])
                    logger.info("[LDAP] Created default admin user: %s", admin_user_dn)
                except ldap.ALREADY_EXISTS:
                    pass
                except Exception as e:
                    logger.warning("[LDAP] Could not create admin user in LDAP: %s", e)
        except Exception as e:
            logger.warning("[LDAP] ensure_ldap_structure failed (non-fatal): %s", e)
        finally:
            if conn is not None:
                try:
                    conn.unbind_s()
                except Exception:
                    pass

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get all users from LDAP"""
        conn = None
        try:
            conn = ldap.initialize(self.server)
            conn.protocol_version = ldap.VERSION3
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
            
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

            # The DEFAULT_ADMIN_USER authenticates via env-var bypass (no LDAP entry
            # required for login) but must still appear in the user list. Inject if absent.
            if DEFAULT_ADMIN_USER and not any(u['username'] == DEFAULT_ADMIN_USER for u in users):
                users.append({
                    'id': DEFAULT_ADMIN_USER,
                    'username': DEFAULT_ADMIN_USER,
                    'name': DEFAULT_ADMIN_USER,
                    'email': f'{DEFAULT_ADMIN_USER}@local',
                    'firstName': '',
                    'lastName': '',
                })

            return users
            
        except Exception as e:
            logger.error("Error getting all LDAP users: %s", e)
            # Still return the bypass admin so the UI is never completely empty
            if DEFAULT_ADMIN_USER:
                return [{
                    'id': DEFAULT_ADMIN_USER,
                    'username': DEFAULT_ADMIN_USER,
                    'name': DEFAULT_ADMIN_USER,
                    'email': f'{DEFAULT_ADMIN_USER}@local',
                    'firstName': '',
                    'lastName': '',
                }]
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
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
            
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
            
            user_dn = f"cn={ldap.dn.escape_dn_chars(username)},{self.user_dn}"
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
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
            
            # Bind as admin
            admin_dn = f"cn=admin,{self.base_dn}"
            admin_password = read_secret("ldap_admin_password", env_var="LDAP_ADMIN_PASSWORD")
            conn.simple_bind_s(admin_dn, admin_password)
            
            # Delete user
            user_dn = f"cn={ldap.dn.escape_dn_chars(username)},{self.user_dn}"
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
            conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
            admin_dn = f"cn=admin,{self.base_dn}"
            conn.simple_bind_s(admin_dn, read_secret("ldap_admin_password", env_var="LDAP_ADMIN_PASSWORD"))
            salt = secrets.token_bytes(4)
            # SSHA is the LDAP wire format; not used as a cryptographic security primitive
            h = hashlib.sha1(new_password.encode('utf-8') + salt, usedforsecurity=False)  # nosec B324
            hashed = '{SSHA}' + base64.b64encode(h.digest() + salt).decode()
            user_dn = f"cn={ldap.dn.escape_dn_chars(username)},{self.user_dn}"
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
    """Create JWT access token with a unique jti for revocation tracking."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": secrets.token_urlsafe(16),  # unique ID for per-token revocation
    })
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[TokenData]:
    """Verify JWT token and confirm the session has not been revoked (e.g. after logout).

    Revocation order:
      1. Redis jti blocklist (fast, O(1)) — populated on logout for tokens with jti.
      2. DB user_sessions table — fallback for tokens without jti and extra assurance.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None:
            return None
        # Fast path: Redis jti revocation check
        jti = payload.get("jti")
        if jti:
            try:
                rc = _get_revocation_client()
                if rc is not None and rc.exists(f"pf9:revoked:{jti}"):
                    return None
            except Exception:
                pass  # Redis unavailable — fall through to DB check
        # DB session check (catches post-logout reuse; always runs as defence-in-depth)
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
            # DB unavailable — JWT signature + expiry + Redis check still apply.
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
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
            
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_sessions (username, role, token_hash, expires_at, ip_address, user_agent)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (username, role, token_hash, expires_at, ip_address, user_agent))
    except Exception as e:
        logger.error("Error creating session for %s: %s", username, e)

def invalidate_user_session(token: str):
    """Invalidate user session in DB and add jti to Redis revocation list."""
    try:
        with get_connection() as conn:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE user_sessions SET is_active = false
                    WHERE token_hash = %s
                """, (token_hash,))
    except Exception as e:
        logger.error("Error invalidating session in DB: %s", e)
    # Also add jti to Redis revocation list for fast rejection on subsequent requests
    try:
        payload = jwt.decode(
            token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM],
            options={"verify_exp": False},
        )
        jti = payload.get("jti")
        exp = payload.get("exp", 0)
        if jti:
            remaining = max(int(exp - datetime.now(timezone.utc).timestamp()), 0)
            if remaining > 0:
                rc = _get_revocation_client()
                if rc is not None:
                    rc.setex(f"pf9:revoked:{jti}", remaining, "1")
    except Exception as exc:
        logger.debug("Could not add jti to Redis revocation list: %s", exc)

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

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Optional[User]:
    """Get current authenticated user.

    Checks httpOnly cookie first (browser clients), then falls back to
    Authorization: Bearer header (CI tests, external API consumers).
    """
    if not ENABLE_AUTHENTICATION:
        # Return default admin user when authentication is disabled
        return User(username="admin", role="superadmin")

    # 1. Try httpOnly cookie (browser path)
    token = request.cookies.get("access_token")

    # 2. Fall back to Bearer header (CI / external / legacy path)
    if not token and credentials:
        token = credentials.credentials

    if not token:
        return None

    token_data = verify_token(token)
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
                get_request_ip(request) if request else None,
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
    """Initialize default admin user if it doesn't exist.

    Also bootstraps the LDAP directory (ou=users, ou=groups, admin app-user)
    so that a fresh K8s deployment is self-healing without manual ldapadd.
    """
    try:
        if ENABLE_AUTHENTICATION and DEFAULT_ADMIN_USER and DEFAULT_ADMIN_PASSWORD:
            # Ensure LDAP OUs and admin LDAP user exist (idempotent, non-fatal)
            try:
                ldap_auth.ensure_ldap_structure()
            except Exception as e:
                logger.warning("ensure_ldap_structure failed at startup: %s", e)

            # Always force-set to superadmin — ensures role is correct even if a
            # previous DB row was created with the wrong role (e.g. "viewer") during
            # an earlier startup where DEFAULT_ADMIN_PASSWORD was not yet injected.
            set_user_role(DEFAULT_ADMIN_USER, "superadmin", "system")
            logger.info("Default admin user '%s' initialized as superadmin", DEFAULT_ADMIN_USER)
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
