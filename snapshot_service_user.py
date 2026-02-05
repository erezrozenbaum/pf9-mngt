#!/usr/bin/env python3
"""
Snapshot Service User Management

Manages a dedicated service user (snapshotsrv@ccc.co.il) that:
1. Is created automatically in each tenant
2. Has 'admin' role for snapshot operations (service role has insufficient permissions)
3. Uses an auto-generated, encrypted password stored in .env
4. Enables snapshots to be created in the correct tenant, not in service domain

This is a temporary workaround until Platform9 allows cross-tenant admin access.
When that capability becomes available, this user can be deleted and normal
admin session used instead.
"""

import os
import json
import secrets
import string
from typing import Optional, Dict, Any, List
from cryptography.fernet import Fernet
import requests

# Service user details
SERVICE_USER_EMAIL = "snapshotsrv@ccc.co.il"
SERVICE_USER_ROLE = "admin"  # Admin role required for snapshot operations
DEFAULT_DOMAIN = "Default"


def generate_secure_password(length: int = 32) -> str:
    """Generate a cryptographically secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password


def get_or_create_encryption_key() -> str:
    """
    Get encryption key from .env or create a new one.
    Key is stored as SNAPSHOT_PASSWORD_KEY in .env
    """
    from pathlib import Path
    env_file = Path(".env")
    
    key_env_var = "SNAPSHOT_PASSWORD_KEY"
    
    # Try to read existing key from .env
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                if line.startswith(key_env_var + "="):
                    key_str = line.split("=", 1)[1].strip()
                    try:
                        return key_str
                    except Exception:
                        pass
    
    # Generate new key
    new_key = Fernet.generate_key().decode()
    
    # Append to .env
    with open(env_file, "a") as f:
        f.write(f"\n# Auto-generated encryption key for service user password\n")
        f.write(f"{key_env_var}={new_key}\n")
    
    return new_key


def encrypt_password(password: str, key: str) -> str:
    """Encrypt password using Fernet."""
    f = Fernet(key.encode() if isinstance(key, str) else key)
    encrypted = f.encrypt(password.encode())
    return encrypted.decode()


def decrypt_password(encrypted: str, key: str) -> str:
    """Decrypt password using Fernet."""
    f = Fernet(key.encode() if isinstance(key, str) else key)
    decrypted = f.decrypt(encrypted.encode())
    return decrypted.decode()


def get_service_user_password() -> str:
    """
    Get the service user password from .env (encrypted).
    If not found, generate and encrypt a new one.
    """
    from pathlib import Path
    env_file = Path(".env")
    
    password_var = "SNAPSHOT_USER_PASSWORD_ENCRYPTED"
    
    # Try to read existing password from .env
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                if line.startswith(password_var + "="):
                    encrypted_pwd = line.split("=", 1)[1].strip()
                    key = get_or_create_encryption_key()
                    try:
                        return decrypt_password(encrypted_pwd, key)
                    except Exception as e:
                        print(f"[WARNING] Failed to decrypt password: {e}, generating new one")
                        break
    
    # Generate new password
    new_password = generate_secure_password()
    key = get_or_create_encryption_key()
    encrypted = encrypt_password(new_password, key)
    
    # Append to .env
    with open(env_file, "a") as f:
        f.write(f"\n# Auto-generated encrypted password for snapshot service user\n")
        f.write(f"# Email: {SERVICE_USER_EMAIL}\n")
        f.write(f"# Generated: {__import__('datetime').datetime.now().isoformat()}\n")
        f.write(f"{password_var}={encrypted}\n")
    
    print(f"[SNAPSHOT-USER] Generated new service user password (stored encrypted)")
    return new_password


def user_exists_in_domain(
    session: requests.Session,
    keystone_url: str,
    email: str,
    domain_id: str
) -> Optional[Dict[str, Any]]:
    """Check if user exists in a specific domain."""
    url = f"{keystone_url.rstrip('/')}/users"
    
    try:
        params = {"domain_id": domain_id}
        r = session.get(url, params=params, timeout=60)
        
        if r.status_code != 200:
            return None
        
        users = r.json().get("users", [])
        for user in users:
            if user.get("name") == email or user.get("email") == email:
                return user
        
        return None
    except Exception as e:
        print(f"[ERROR] Failed to check user in domain {domain_id}: {e}")
        return None


def create_user_in_domain(
    session: requests.Session,
    keystone_url: str,
    email: str,
    password: str,
    domain_id: str = "default"
) -> Optional[Dict[str, Any]]:
    """Create a new user in a specific domain."""
    url = f"{keystone_url.rstrip('/')}/users"
    
    payload = {
        "user": {
            "name": email,
            "email": email,
            "password": password,
            "enabled": True,
            "domain_id": domain_id,
            "description": "Auto-created snapshot service user (temporary until cross-tenant admin access available)"
        }
    }
    
    try:
        r = session.post(url, json=payload, timeout=60)
        
        if r.status_code in (201, 200):
            return r.json().get("user")
        else:
            print(f"[ERROR] Failed to create user: {r.status_code} - {r.text}")
            return None
    except Exception as e:
        print(f"[ERROR] Exception creating user: {e}")
        return None


def assign_role_to_user(
    session: requests.Session,
    keystone_url: str,
    user_id: str,
    role_name: str,
    project_id: str
) -> bool:
    """Assign a role to user for a specific project."""
    
    # First, get the role ID
    roles_url = f"{keystone_url.rstrip('/')}/roles"
    try:
        r = session.get(roles_url, params={"name": role_name}, timeout=60)
        if r.status_code != 200:
            print(f"[ERROR] Could not find role {role_name}")
            return False
        
        roles = r.json().get("roles", [])
        if not roles:
            print(f"[ERROR] Role {role_name} not found")
            return False
        
        role_id = roles[0]["id"]
    except Exception as e:
        print(f"[ERROR] Failed to get role ID: {e}")
        return False
    
    # Assign role
    url = f"{keystone_url.rstrip('/')}/projects/{project_id}/users/{user_id}/roles/{role_id}"
    
    try:
        r = session.put(url, timeout=60)
        
        if r.status_code in (200, 204):
            print(f"[SNAPSHOT-USER] Assigned '{role_name}' role to {SERVICE_USER_EMAIL} in project {project_id}")
            return True
        else:
            print(f"[ERROR] Failed to assign role: {r.status_code}")
            return False
    except Exception as e:
        print(f"[ERROR] Exception assigning role: {e}")
        return False


def ensure_service_user(
    session: requests.Session,
    keystone_url: str,
    project_id: str,
    domain_id: str = "default"
) -> Optional[Dict[str, Any]]:
    """
    Ensure snapshot service user exists in the given project.
    
    Steps:
    1. Check if user exists in default domain
    2. If not, create it with auto-generated password
    3. Assign 'admin' role to the project
    4. Return user info
    """
    
    print(f"[SNAPSHOT-USER] Ensuring service user exists for project {project_id}...")
    
    # Check if user exists in default domain (domain_id="default")
    existing_user = user_exists_in_domain(session, keystone_url, SERVICE_USER_EMAIL, domain_id)
    
    if existing_user:
        print(f"[SNAPSHOT-USER] Service user already exists (ID: {existing_user['id']})")
        user_id = existing_user['id']
    else:
        # Get password
        password = get_service_user_password()
        
        # Create user
        print(f"[SNAPSHOT-USER] Creating service user {SERVICE_USER_EMAIL}...")
        new_user = create_user_in_domain(session, keystone_url, SERVICE_USER_EMAIL, password, domain_id)
        
        if not new_user:
            print(f"[ERROR] Failed to create service user")
            return None
        
        print(f"[SNAPSHOT-USER] Service user created (ID: {new_user['id']})")
        user_id = new_user['id']
    
    # Assign role to project
    if not assign_role_to_user(session, keystone_url, user_id, SERVICE_USER_ROLE, project_id):
        print(f"[WARNING] Could not assign role (user may not have proper permissions)")
    
    return {"id": user_id, "email": SERVICE_USER_EMAIL, "name": SERVICE_USER_EMAIL}


def get_service_user_session(
    keystone_url: str,
    user_domain: str = DEFAULT_DOMAIN,
    verify_tls: bool = True
) -> Optional[requests.Session]:
    """
    Get an authenticated session for the service user.
    Uses the auto-generated password from .env.
    """
    from p9_common import get_session
    
    password = get_service_user_password()
    
    try:
        # Use existing get_session but with service user credentials
        session = get_session(
            username=SERVICE_USER_EMAIL,
            password=password,
            keystone_url=keystone_url,
            user_domain=user_domain,
            project_domain=DEFAULT_DOMAIN,
            project_name=None,  # Will be set per-project when needed
            verify_tls=verify_tls
        )
        
        print(f"[SNAPSHOT-USER] Authenticated as {SERVICE_USER_EMAIL}")
        return session
    except Exception as e:
        print(f"[ERROR] Failed to authenticate as service user: {e}")
        return None


if __name__ == "__main__":
    # Test the module
    print("[TEST] Snapshot Service User Management")
    print(f"[TEST] Service user email: {SERVICE_USER_EMAIL}")
    print(f"[TEST] Service role: {SERVICE_USER_ROLE}")
    
    # Generate password (will be encrypted and stored)
    pwd = get_service_user_password()
    print(f"[TEST] Password generated (length: {len(pwd)})")
    
    # Get encryption key
    key = get_or_create_encryption_key()
    print(f"[TEST] Encryption key ready")
    
    print("[TEST] Module ready for use")
