import requests

# List all users in a tenant/project using Keystone API
def list_users_in_project(keystone_url: str, token: str, project_id: str) -> list:
    """
    Fetch all users for a given project from Keystone, including hidden/service users.
    Returns a list of user dicts.
    """
    url = f"{keystone_url.rstrip('/')}/projects/{project_id}/users"
    headers = {"X-Auth-Token": token}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json().get("users", [])
    except Exception as e:
        print(f"[ERROR] Failed to list users in project {project_id}: {e}")
        return []
"""
snapshot_service_user.py
Service user credential management for Platform9 snapshot automation.
"""

import os
from typing import Dict, Optional

import json
import os
from typing import Dict, Optional
from datetime import datetime, timedelta

# Service user email (should match Keystone user)
SERVICE_USER_EMAIL = os.getenv("SERVICE_USER_EMAIL", "snapshot@ccc.co.il")

# Default service user password
SERVICE_USER_PASSWORD = os.getenv("SERVICE_USER_PASSWORD", "changeme")

# Per-tenant service user passwords (from env or file)
SERVICE_USER_PASSWORDS: Dict[str, str] = {}


# Optional: Load per-tenant passwords from a JSON file
SERVICE_USER_PASSWORDS_FILE = os.getenv("SERVICE_USER_PASSWORDS_FILE", "service_user_passwords.json")
if os.path.exists(SERVICE_USER_PASSWORDS_FILE):
    try:
        with open(SERVICE_USER_PASSWORDS_FILE, "r") as f:
            SERVICE_USER_PASSWORDS = json.load(f)
    except Exception as e:
        print(f"[WARNING] Failed to load per-tenant service user passwords: {e}")

def assign_admin_role_to_service_user(keystone_url: str, token: str, project_id: str, user_id: str, admin_role_id: str) -> bool:
    """
    Assign the admin role to the service user in the specified project using Keystone API.
    Returns True if assignment succeeded or already present, False otherwise.
    """
    url = f"{keystone_url.rstrip('/')}/projects/{project_id}/users/{user_id}/roles/{admin_role_id}"
    headers = {"X-Auth-Token": token}
    try:
        resp = requests.put(url, headers=headers, timeout=30)
        if resp.status_code in (200, 204):
            print(f"[INFO] Admin role assigned to user {user_id} in project {project_id}")
            return True
        elif resp.status_code == 409:
            print(f"[INFO] Admin role already assigned to user {user_id} in project {project_id}")
            return True
        else:
            print(f"[ERROR] Failed to assign admin role: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"[ERROR] Exception assigning admin role: {e}")
        return False

def automate_admin_role_assignment(keystone_url: str, token: str, service_user_email: str):
    """
    For each project, ensure the service user has the admin role. Assign if missing.
    """
    # List all projects
    projects_url = f"{keystone_url.rstrip('/')}/projects"
    projects_resp = requests.get(projects_url, headers={"X-Auth-Token": token}, timeout=30)
    projects_resp.raise_for_status()
    projects = projects_resp.json().get("projects", [])

    # List all roles
    roles_url = f"{keystone_url.rstrip('/')}/roles"
    roles_resp = requests.get(roles_url, headers={"X-Auth-Token": token}, timeout=30)
    roles_resp.raise_for_status()
    roles = roles_resp.json().get("roles", [])
    admin_role = next((r for r in roles if r["name"].lower() == "admin"), None)
    if not admin_role:
        print("[ERROR] Admin role not found in Keystone roles.")
        return
    admin_role_id = admin_role["id"]

    # List all users
    users_url = f"{keystone_url.rstrip('/')}/users"
    users_resp = requests.get(users_url, headers={"X-Auth-Token": token}, timeout=30)
    users_resp.raise_for_status()
    users = users_resp.json().get("users", [])
    service_user = next((u for u in users if u.get("email", "") == service_user_email or u.get("name", "") == service_user_email), None)
    if not service_user:
        print(f"[ERROR] Service user {service_user_email} not found.")
        return
    service_user_id = service_user["id"]

    for project in projects:
        project_id = project["id"]
        # Check if admin role is already assigned
        role_assign_url = f"{keystone_url.rstrip('/')}/role_assignments?user.id={service_user_id}&project.id={project_id}&role.id={admin_role_id}"
        role_assign_resp = requests.get(role_assign_url, headers={"X-Auth-Token": token}, timeout=30)
        role_assign_resp.raise_for_status()
        assignments = role_assign_resp.json().get("role_assignments", [])
        if assignments:
            print(f"[INFO] Service user already has admin role in project {project_id}")
            continue
        # Assign admin role
        assign_admin_role_to_service_user(keystone_url, token, project_id, service_user_id, admin_role_id)

def get_service_user_password(tenant_id: Optional[str] = None) -> str:
    """
    Return the service user password for a given tenant.
    If tenant_id is not specified or not found, return the default password.
    """
    if tenant_id and tenant_id in SERVICE_USER_PASSWORDS:
        return SERVICE_USER_PASSWORDS[tenant_id]
    return SERVICE_USER_PASSWORD

def ensure_service_user(tenant_id: Optional[str] = None) -> bool:
    """
    Ensure service user exists for the tenant (project_id).
    If not, create it and assign admin role. Returns True if user exists/created and has admin role.
    """
    import requests
    from p9_common import CFG
    keystone_url = CFG["KEYSTONE_URL"]
    admin_username = CFG["USERNAME"]
    admin_password = CFG["PASSWORD"]
    user_domain = CFG["USER_DOMAIN"]
    # Get admin token
    session = requests.Session()
    auth_url = keystone_url.rstrip("/") + "/auth/tokens"
    payload = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": admin_username,
                        "domain": {"name": user_domain},
                        "password": admin_password,
                    }
                },
            },
            "scope": {"project": {"id": tenant_id}}
        }
    }
    try:
        resp = session.post(auth_url, json=payload, timeout=30)
        resp.raise_for_status()
        admin_token = resp.headers["X-Subject-Token"]
    except Exception as e:
        print(f"[ERROR] Could not get admin token for tenant {tenant_id}: {e}")
        return False

    # Check if user exists in this tenant
    users_url = keystone_url.rstrip("/") + "/users"
    try:
        users_resp = session.get(users_url, headers={"X-Auth-Token": admin_token}, timeout=30)
        users_resp.raise_for_status()
        users = users_resp.json().get("users", [])
        service_user = next((u for u in users if u.get("email", "") == SERVICE_USER_EMAIL or u.get("name", "") == SERVICE_USER_EMAIL), None)
    except Exception as e:
        print(f"[ERROR] Could not list users in tenant {tenant_id}: {e}")
        return False

    if not service_user:
        # Create the user
        create_url = keystone_url.rstrip("/") + "/users"
        user_data = {
            "user": {
                "name": SERVICE_USER_EMAIL,
                "email": SERVICE_USER_EMAIL,
                "password": get_service_user_password(tenant_id),
                "domain_id": "default",
                "default_project_id": tenant_id,
                "enabled": True
            }
        }
        try:
            create_resp = session.post(create_url, headers={"X-Auth-Token": admin_token}, json=user_data, timeout=30)
            create_resp.raise_for_status()
            service_user = create_resp.json().get("user")
            print(f"[INFO] Created service user {SERVICE_USER_EMAIL} in tenant {tenant_id}")
        except Exception as e:
            print(f"[ERROR] Could not create service user in tenant {tenant_id}: {e}")
            return False
    else:
        print(f"[INFO] Service user {SERVICE_USER_EMAIL} already exists in tenant {tenant_id}")

    # Ensure admin role
    # Get admin role id
    roles_url = keystone_url.rstrip("/") + "/roles"
    try:
        roles_resp = session.get(roles_url, headers={"X-Auth-Token": admin_token}, timeout=30)
        roles_resp.raise_for_status()
        roles = roles_resp.json().get("roles", [])
        admin_role = next((r for r in roles if r["name"].lower() == "admin"), None)
        if not admin_role:
            print(f"[ERROR] Admin role not found in Keystone roles.")
            return False
        admin_role_id = admin_role["id"]
    except Exception as e:
        print(f"[ERROR] Could not get roles for tenant {tenant_id}: {e}")
        return False

    # Check if admin role is already assigned
    role_assign_url = keystone_url.rstrip("/") + f"/role_assignments?user.id={service_user['id']}&project.id={tenant_id}&role.id={admin_role_id}"
    try:
        role_assign_resp = session.get(role_assign_url, headers={"X-Auth-Token": admin_token}, timeout=30)
        role_assign_resp.raise_for_status()
        assignments = role_assign_resp.json().get("role_assignments", [])
        if assignments:
            print(f"[INFO] Service user already has admin role in tenant {tenant_id}")
            return True
    except Exception as e:
        print(f"[ERROR] Could not check admin role assignment in tenant {tenant_id}: {e}")
        return False

    # Assign admin role
    assign_url = keystone_url.rstrip("/") + f"/projects/{tenant_id}/users/{service_user['id']}/roles/{admin_role_id}"
    try:
        assign_resp = session.put(assign_url, headers={"X-Auth-Token": admin_token}, timeout=30)
        if assign_resp.status_code in (200, 204):
            print(f"[INFO] Assigned admin role to service user in tenant {tenant_id}")
            return True
        else:
            print(f"[ERROR] Failed to assign admin role: {assign_resp.status_code} {assign_resp.text}")
            return False
    except Exception as e:
        print(f"[ERROR] Could not assign admin role in tenant {tenant_id}: {e}")
        return False

def is_password_expired(password_last_changed: Optional[str], max_age_days: int = 90) -> bool:
    """
    Check if the password is expired based on last changed date.
    password_last_changed: ISO date string
    max_age_days: maximum allowed age in days
    """
    if not password_last_changed:
        return False
    try:
        last_changed = datetime.fromisoformat(password_last_changed)
        return datetime.utcnow() - last_changed > timedelta(days=max_age_days)
    except Exception:
        return False
