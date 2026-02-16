def cinder_list_snapshots_for_volume(session: requests.Session, project_id: str, volume_id: str):
    """
    List all snapshots for a specific volume in a given project.
    Uses cinder_snapshots_all and filters by volume_id.
    Ensures all_tenants=1 is only used for admin sessions.
    """
    all_snaps = cinder_snapshots_all(session, project_id)
    return [s for s in all_snaps if s.get("volume_id") == volume_id]
#!/usr/bin/env python3
"""
Common helpers for Platform9/OpenStack tools
(NO EMAIL SUPPORT)
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

# --------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------


CFG = {
    # Keystone (auth) endpoint – usually .../keystone/v3
    "KEYSTONE_URL": os.getenv("PF9_AUTH_URL", ""),
    # Region base URL (for older direct-URL usages; we now mostly use catalog)
    "REGION_URL": os.getenv("PF9_REGION_URL", ""),

    # Credentials – use env vars or edit the defaults below
    "USERNAME": os.getenv("PF9_USERNAME", ""),
    "PASSWORD": os.getenv("PF9_PASSWORD", ""),

    "USER_DOMAIN": os.getenv("PF9_USER_DOMAIN", "Default"),
    "PROJECT_DOMAIN": os.getenv("PF9_PROJECT_DOMAIN", "Default"),
    "PROJECT_NAME": os.getenv("PF9_PROJECT_NAME", "service"),

    "VERIFY_TLS": os.getenv("PF9_VERIFY_TLS", "true").lower()
    in ("1", "true", "yes"),

    "OUTPUT_DIR": os.getenv("PF9_OUTPUT_DIR", os.path.join(os.path.expanduser("~"), "Reports", "Platform9")),

    "REQUEST_TIMEOUT": int(os.getenv("PF9_REQUEST_TIMEOUT", "60")),
    "PAGE_LIMIT": int(os.getenv("PF9_PAGE_LIMIT", "500")),
    "GLANCE_LIMIT": int(os.getenv("PF9_GLANCE_LIMIT", "1000")),
}

ERRORS: List[Dict[str, Any]] = []

# Service endpoints discovered from Keystone catalog
NOVA_ENDPOINT: Optional[str] = None
NEUTRON_ENDPOINT: Optional[str] = None
CINDER_ENDPOINT: Optional[str] = None
GLANCE_ENDPOINT: Optional[str] = None


# --------------------------------------------------------------------
# General Helpers
# --------------------------------------------------------------------


def mask_value(val: Optional[str], label: str = "") -> str:
    """
    Helper to mask sensitive strings for logging/output.

    The `label` argument is optional and ignored; kept so callers can pass
    mask_value(x, "vm") etc. without causing TypeError.
    """
    if not val or len(val) < 6:
        return "********"
    return f"{val[:2]}********{val[-2:]}"


def log_error(area: str, msg: str) -> None:
    ERRORS.append(
        {
            "time_utc": now_utc_str(),
            "area": area,
            "msg": msg,
        }
    )


def log_info(area: str, msg: str) -> None:
    """Log informational message (print to console for now)"""
    print(f"[{area.upper()}] {msg}")


def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def ts_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


# --------------------------------------------------------------------
# HTTP / API Helpers
# --------------------------------------------------------------------


def _new_session() -> requests.Session:
    s = requests.Session()
    s.verify = CFG["VERIFY_TLS"]
    return s


def http_json(session: requests.Session, method: str, url: str, **kwargs) -> Dict[str, Any]:
    timeout = kwargs.pop("timeout", CFG["REQUEST_TIMEOUT"])
    resp = session.request(method, url, timeout=timeout, **kwargs)
    resp.raise_for_status()
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {}
        print(f"[DEBUG] HTTP {method} {url}")
        print(f"[DEBUG] Headers: {session.headers}")
        if 'json' in kwargs:
            print(f"[DEBUG] Payload: {kwargs['json']}")
        elif 'data' in kwargs:
            print(f"[DEBUG] Data: {kwargs['data']}")
        resp = session.request(method, url, timeout=timeout, **kwargs)
        print(f"[DEBUG] Response status: {resp.status_code}")
        print(f"[DEBUG] Response body: {resp.text[:1000]}")
        try:
            resp.raise_for_status()
        except Exception as e:
            print(f"[HTTP] {method} {url} failed: {e}")
            raise
        return resp.json()


def paginate(
    session: requests.Session,
    url: str,
    key: str,
    extra_params: Optional[Dict[str, Any]] = None,
    debug_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Generic helper for limit/marker style pagination.
    Assumes responses look like { key: [...], ... }.
    """
    out: List[Dict[str, Any]] = []
    marker: Optional[str] = None
    extra_params = dict(extra_params or {})
    while True:
        params: Dict[str, Any] = {"limit": CFG["PAGE_LIMIT"], **extra_params}
        if marker:
            params["marker"] = marker
        try:
            resp = session.get(url, params=params, timeout=CFG["REQUEST_TIMEOUT"])
            resp.raise_for_status()
        except requests.HTTPError as e:
            print(f"[ERROR] HTTPError during paginate: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"[ERROR] Response status: {e.response.status_code}")
                print(f"[ERROR] Response body: {e.response.text}")
            if debug_context:
                print(f"[ERROR] Debug context: {debug_context}")
            raise
        data = resp.json() if resp.content else {}
        items = data.get(key, [])
        out.extend(items)
        if len(items) < CFG["PAGE_LIMIT"]:
            break
        marker = items[-1].get("id")
    return out


# --------------------------------------------------------------------
# Keystone Auth + Catalog
# --------------------------------------------------------------------


def _extract_endpoints_from_catalog(catalog: List[Dict[str, Any]]) -> None:
    """
    Populate global NOVA_ENDPOINT / NEUTRON_ENDPOINT / CINDER_ENDPOINT / GLANCE_ENDPOINT
    from Keystone service catalog (public endpoints).
    """
    global NOVA_ENDPOINT, NEUTRON_ENDPOINT, CINDER_ENDPOINT, GLANCE_ENDPOINT

    def _find(service_type: str) -> Optional[str]:
        for svc in catalog:
            if svc.get("type") == service_type:
                for ep in svc.get("endpoints", []):
                    if ep.get("interface") == "public":
                        return ep["url"].rstrip("/")
        return None

    nova = _find("compute")
    if nova:
        NOVA_ENDPOINT = nova

    neutron = _find("network")
    if neutron:
        NEUTRON_ENDPOINT = neutron

    # Cinder can be volumev3, volumev2, or volume depending on cloud
    cinder = _find("volumev3") or _find("volumev2") or _find("volume")
    if cinder:
        CINDER_ENDPOINT = cinder

    glance = _find("image")
    if glance:
        GLANCE_ENDPOINT = glance


def get_domain_scoped_session(domain_name):
    """
    Authenticate with domain scope to see users within a specific domain.
    Used for cross-domain user collection.
    """
    session = _new_session()
    auth_url = CFG["KEYSTONE_URL"].rstrip("/") + "/auth/tokens"

    payload = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": CFG["USERNAME"],
                        "domain": {"name": CFG["USER_DOMAIN"]},
                        "password": CFG["PASSWORD"],
                    }
                },
            },
            "scope": {
                "domain": {"name": domain_name}
            },
        }
    }

    try:
        r = session.post(auth_url, json=payload, timeout=CFG["REQUEST_TIMEOUT"])
        r.raise_for_status()
        token = r.headers["X-Subject-Token"]
        session.headers.update({"X-Auth-Token": token})
        return session, token
    except Exception as e:
        log_error("keystone", f"Failed to authenticate with domain scope for {domain_name}: {e}")
        return None, None


def get_project_scoped_session(project_id):
    """
    Authenticate with project scope for a specific project.
    Returns (session, token) tuple or (None, None) on failure.
    """
    session = _new_session()
    auth_url = CFG["KEYSTONE_URL"].rstrip("/") + "/auth/tokens"

    payload = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": CFG["USERNAME"],
                        "domain": {"name": CFG["USER_DOMAIN"]},
                        "password": CFG["PASSWORD"],
                    }
                },
            },
            "scope": {
                "project": {"id": project_id}
            },
        }
    }

    try:
        r = session.post(auth_url, json=payload, timeout=CFG["REQUEST_TIMEOUT"])
        r.raise_for_status()
        token = r.headers["X-Subject-Token"]
        body = r.json()
        
        # Extract endpoints from catalog for this project scope
        catalog = body.get("token", {}).get("catalog", [])
        _extract_endpoints_from_catalog(catalog)
        
        session.headers.update({"X-Auth-Token": token})
        return session, token
    except Exception as e:
        log_error("keystone", f"Failed to authenticate with project scope for {project_id}: {e}")
        return None, None


def get_service_user_session(project_id, username, password, user_domain="default"):
    """
    Authenticate with project scope using custom credentials (for service user).
    
    Args:
        project_id: The project ID to scope to
        username: Service user email/username
        password: Service user password
        user_domain: Domain of the service user (default: "default")
    
    Returns:
        (session, token) tuple or (None, None) on failure
    """
    session = _new_session()
    auth_url = CFG["KEYSTONE_URL"].rstrip("/") + "/auth/tokens"

    payload = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": username,
                        "domain": {"id": user_domain},
                        "password": password,
                    }
                },
            },
            "scope": {
                "project": {"id": project_id}
            },
        }
    }

    try:
        r = session.post(auth_url, json=payload, timeout=CFG["REQUEST_TIMEOUT"])
        r.raise_for_status()
        token = r.headers["X-Subject-Token"]
        body = r.json()
        
        # Extract endpoints from catalog for this project scope
        catalog = body.get("token", {}).get("catalog", [])
        _extract_endpoints_from_catalog(catalog)
        
        session.headers.update({"X-Auth-Token": token})
        return session, token
    except Exception as e:
        log_error("keystone", f"Failed to authenticate as {username} for project {project_id}: {e}")
        return None, None


def get_session_best_scope():
    """
    Authenticate with Keystone and return:
      session, token, body, scope_mode, None

    Also populates global service endpoints from the catalog so the Nova/Neutron/
    Cinder/Glance helper functions can use them.
    """
    session = _new_session()
    auth_url = CFG["KEYSTONE_URL"].rstrip("/") + "/auth/tokens"

    payload = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": CFG["USERNAME"],
                        "domain": {"name": CFG["USER_DOMAIN"]},
                        "password": CFG["PASSWORD"],
                    }
                },
            },
            "scope": {
                "project": {
                    "name": CFG["PROJECT_NAME"],
                    "domain": {"name": CFG["PROJECT_DOMAIN"]},
                }
            },
        }
    }

    r = session.post(auth_url, json=payload, timeout=CFG["REQUEST_TIMEOUT"])
    r.raise_for_status()
    token = r.headers["X-Subject-Token"]
    body = r.json()

    # Discover endpoints from catalog
    catalog = body.get("token", {}).get("catalog", [])
    _extract_endpoints_from_catalog(catalog)

    session.headers.update({"X-Auth-Token": token})
    return session, token, body, "project", None


# --------------------------------------------------------------------
# Resource Listing Helpers (Keystone)
# --------------------------------------------------------------------


def list_domains_all(session: requests.Session):
    """Fetch all domains from Keystone."""
    url = CFG["KEYSTONE_URL"].rstrip("/") + "/domains"
    return paginate(session, url, "domains")


def list_projects_all(session: requests.Session):
    """Fetch all projects from Keystone."""
    url = CFG["KEYSTONE_URL"].rstrip("/") + "/projects"
    return paginate(session, url, "projects")


def list_users_all(session: requests.Session):
    """Fetch all users from Keystone."""
    url = CFG["KEYSTONE_URL"].rstrip("/") + "/users"
    return paginate(session, url, "users")


def list_users_all_domains(session: requests.Session):
    """
    Fetch users from all domains by iterating through each domain.
    This ensures we get users across all tenants, not just the current scope.
    
    The function works by:
    1. Getting list of all domains
    2. Querying users for each domain specifically using domain_id parameter
    3. Combining results and removing duplicates
    4. Adding domain context to user records
    """
    try:
        # Use the same approach as other Keystone functions
        keystone_base_url = CFG["KEYSTONE_URL"].rstrip("/")
        
        # First, get all domains
        domains_url = f"{keystone_base_url}/domains"
        domains_response = session.get(domains_url, timeout=CFG["REQUEST_TIMEOUT"])
        
        if domains_response.status_code != 200:
            log_error("keystone", f"Could not fetch domains (status {domains_response.status_code}), falling back to current scope")
            current_users = list_users_all(session)
            log_info("keystone", f"Fallback: found {len(current_users)} users in current scope")
            return current_users
            
        domains_data = domains_response.json()
        domains = domains_data.get('domains', [])
        enabled_domains = [d for d in domains if d.get('enabled', False)]
        
        log_info("keystone", f"Found {len(enabled_domains)} enabled domains, querying users from each")
        
        # Collect users from each domain
        all_users = {}  # Use dict to avoid duplicates by user ID
        domain_stats = {}
        accessible_domains = 0
        denied_domains = 0
        error_domains = 0
        
        for domain in enabled_domains:
            domain_name = domain['name']
            domain_id = domain['id']
            
            try:
                # Query users for this specific domain using domain_id parameter
                users_url = f"{keystone_base_url}/users?domain_id={domain_id}"
                users_response = session.get(users_url, timeout=CFG["REQUEST_TIMEOUT"])
                
                if users_response.status_code == 200:
                    users_data = users_response.json()
                    domain_users = users_data.get('users', [])
                    
                    # Add domain information to each user and store
                    for user in domain_users:
                        # Ensure domain context is included
                        user['domain_name'] = domain_name
                        user['domain_id'] = domain_id
                        # Use user ID as key to prevent duplicates
                        all_users[user['id']] = user
                    
                    domain_stats[domain_name] = len(domain_users)
                    accessible_domains += 1
                    
                elif users_response.status_code == 403:
                    # Access denied - common for domains we don't have permission to see
                    domain_stats[domain_name] = "ACCESS_DENIED"
                    denied_domains += 1
                    
                elif users_response.status_code == 404:
                    # Not found - domain might not exist or be accessible
                    domain_stats[domain_name] = "NOT_FOUND"
                    error_domains += 1
                    
                else:
                    # Other error
                    domain_stats[domain_name] = f"ERROR_{users_response.status_code}"
                    error_domains += 1
                    log_error("keystone", f"Domain {domain_name}: HTTP {users_response.status_code}")
                    
            except Exception as e:
                log_error("keystone", f"Exception querying domain {domain_name}: {str(e)}")
                domain_stats[domain_name] = "EXCEPTION"
                error_domains += 1
        
        # Convert back to list
        final_users = list(all_users.values())
        
        # Calculate summary statistics  
        domains_with_users = [d for d, c in domain_stats.items() if isinstance(c, int) and c > 0]
        total_users_found = sum(c for c in domain_stats.values() if isinstance(c, int))
        
        # Log comprehensive results
        log_info("keystone", f"Multi-domain user collection completed:")
        log_info("keystone", f"  - Total domains checked: {len(enabled_domains)}")
        log_info("keystone", f"  - Successfully accessed: {accessible_domains}")
        log_info("keystone", f"  - Access denied: {denied_domains}")  
        log_info("keystone", f"  - Errors/Not found: {error_domains}")
        log_info("keystone", f"  - Domains with users: {len(domains_with_users)}")
        log_info("keystone", f"  - Total unique users: {len(final_users)}")
        
        # Show top domains by user count
        if domains_with_users:
            sorted_domains = sorted([(d, c) for d, c in domain_stats.items() if isinstance(c, int) and c > 0], 
                                  key=lambda x: x[1], reverse=True)
            top_domains = sorted_domains[:5]
            log_info("keystone", f"  - Top domains by user count: {top_domains}")
        
        # Validation: compare with single-scope approach
        try:
            current_scope_users = list_users_all(session)
            # Try to get the token from session headers if present
            token = session.headers.get("X-Auth-Token") if hasattr(session, "headers") else None
            if len(final_users) > len(current_scope_users):
                if token:
                    session.headers.update({"X-Auth-Token": token})
                session.is_admin = True
            elif len(final_users) == len(current_scope_users):
                log_error("keystone", f"NOTICE: Multi-domain and single-scope both found {len(final_users)} users - may have cloud admin scope")
            else:
                log_error("keystone", f"WARNING: Multi-domain found fewer users ({len(final_users)}) than single-scope ({len(current_scope_users)})")
        except Exception as e:
            log_error("keystone", f"Could not compare with single-scope approach: {e}")
        
        return final_users
            
    except Exception as e:
        log_error("keystone", f"Error in list_users_all_domains: {str(e)}")
        # Fall back to regular user listing
        log_error("keystone", "Falling back to single-scope user collection")
        return list_users_all(session)


def get_all_users_multi_domain():
    """
    Convenience wrapper for list_users_all_domains that handles session creation.
    
    Returns:
        list: List of user dictionaries from all accessible domains
    """
    try:
        session, token, body, scope_mode, _ = get_session_best_scope()
        return list_users_all_domains(session)
    except Exception as e:
        log_error("keystone", f"Error in get_all_users_multi_domain: {str(e)}")
        return []


def list_roles_all(session: requests.Session):
    """Fetch all roles from Keystone."""
    url = CFG["KEYSTONE_URL"].rstrip("/") + "/roles"
    return paginate(session, url, "roles")


def list_role_assignments_all(session: requests.Session):
    """
    Fetch all role assignments from Keystone.
    Returns user-role-scope mappings with include_names=true for readability.
    """
    url = CFG["KEYSTONE_URL"].rstrip("/") + "/role_assignments"
    try:
        all_assignments = []
        
        # Try different approaches for role assignment collection
        approaches = [
            # Method 1: Standard approach with include_names
            {"include_names": "true", "limit": CFG["PAGE_LIMIT"]},
            # Method 2: Without include_names (simpler)
            {"limit": CFG["PAGE_LIMIT"]},
            # Method 3: Effective assignments only
            {"effective": "true", "limit": CFG["PAGE_LIMIT"]}
        ]
        
        for i, params in enumerate(approaches):
            try:
                print(f"[KEYSTONE] Trying role assignment method {i+1}...")
                resp = session.get(url, params=params, timeout=CFG["REQUEST_TIMEOUT"])
                resp.raise_for_status()
                data = resp.json() if resp.content else {}
                assignments = data.get("role_assignments", [])
                
                if assignments:
                    print(f"[KEYSTONE] Method {i+1} found {len(assignments)} role assignments")
                    all_assignments.extend(assignments)
                    
                    # Handle pagination via links (if present)
                    links = data.get("links", {})
                    next_url = links.get("next")
                    
                    while next_url and len(assignments) >= CFG["PAGE_LIMIT"]:
                        resp = session.get(next_url, timeout=CFG["REQUEST_TIMEOUT"])
                        resp.raise_for_status()
                        data = resp.json() if resp.content else {}
                        assignments = data.get("role_assignments", [])
                        all_assignments.extend(assignments)
                        
                        links = data.get("links", {})
                        next_url = links.get("next")
                        
                        if len(assignments) < CFG["PAGE_LIMIT"]:
                            break
                    break  # Success, exit the approach loop
                else:
                    print(f"[KEYSTONE] Method {i+1} returned no assignments")
            except Exception as e:
                print(f"[KEYSTONE] Method {i+1} failed: {e}")
                continue
                
        return all_assignments
    except Exception as e:
        log_error("keystone", f"Failed to fetch role assignments: {e}")
        return []


def infer_user_roles_from_data(users_data, projects_data, roles_data):
    """
    Infer basic role information from user data when role assignments cannot be collected.
    This provides fallback role information based on user properties and descriptions.
    """
    print("[KEYSTONE] Inferring roles from user data...")
    inferred_assignments = []
    
    # Create lookup maps
    projects_by_id = {p["id"]: p for p in projects_data}
    roles_by_name = {r["name"]: r for r in roles_data}
    
    for user in users_data:
        user_id = user["id"]
        user_name = user.get("name", "")
        description = user.get("description", "") or ""
        default_project_id = user.get("default_project_id")
        
        # Infer roles based on user characteristics
        inferred_roles = []
        
        # 1. Admin users (common patterns)
        if "admin" in user_name.lower() or "admin" in description.lower():
            inferred_roles.append("admin")
        
        # 2. Service users
        if ("service user" in description.lower() or 
            user_name.startswith(("nova", "neutron", "cinder", "glance", "keystone", "heat", "barbican", "designate", "cinder", "placement"))):
            inferred_roles.append("service")
            
        # 3. Regular users with project membership
        if default_project_id and not inferred_roles:
            project = projects_by_id.get(default_project_id)
            if project:
                project_name = project.get("name", "")
                # Infer member role for users with project access
                if project_name not in ["service", "admin"]:
                    inferred_roles.append("member")
                elif project_name == "admin":
                    inferred_roles.append("admin")
                    
        # 4. Default member role for enabled users
        if not inferred_roles and user.get("enabled", False):
            inferred_roles.append("member")
            
        # Create assignment records for each inferred role
        for role_name in inferred_roles:
            if role_name in roles_by_name:
                assignment = {
                    "user": {"id": user_id, "name": user_name},
                    "role": {"id": roles_by_name[role_name]["id"], "name": role_name},
                    "scope": {"project": {"id": default_project_id}} if default_project_id else {},
                    "inferred": True  # Mark as inferred
                }
                inferred_assignments.append(assignment)
    
    print(f"[KEYSTONE] Inferred {len(inferred_assignments)} role assignments for {len([u for u in users_data if any(a['user']['id'] == u['id'] for a in inferred_assignments)])} users")
    return inferred_assignments


def list_groups_all(session: requests.Session):
    """Fetch all groups from Keystone (optional - for group-based role assignments)."""
    url = CFG["KEYSTONE_URL"].rstrip("/") + "/groups"
    try:
        return paginate(session, url, "groups")
    except Exception as e:
        log_error("keystone", f"Failed to fetch groups: {e}")
        return []


# --------------------------------------------------------------------
# Nova helpers
# --------------------------------------------------------------------


def _require_nova():
    if not NOVA_ENDPOINT:
        raise RuntimeError(
            "NOVA_ENDPOINT not initialized – call get_session_best_scope() first"
        )


def nova_servers_all(session: requests.Session):
    """
    Fetch all Nova servers (all tenants, detailed).
    """
    _require_nova()
    url = f"{NOVA_ENDPOINT}/servers/detail"
    # all_tenants=1 requires appropriate role
    return paginate(session, url, "servers", extra_params={"all_tenants": "1"})


def nova_hypervisors_all(session: requests.Session):
    """
    Fetch all Nova hypervisors (compute hosts).
    """
    _require_nova()
    url = f"{NOVA_ENDPOINT}/os-hypervisors/detail"
    return paginate(session, url, "hypervisors")


def nova_flavors(session: requests.Session):
    """
    Fetch all Nova flavors (detailed).
    """
    _require_nova()
    url = f"{NOVA_ENDPOINT}/flavors/detail"
    return paginate(session, url, "flavors")


# --------------------------------------------------------------------
# Cinder helpers
# --------------------------------------------------------------------


def _require_cinder():
    if not CINDER_ENDPOINT:
        raise RuntimeError(
            "CINDER_ENDPOINT not initialized – call get_session_best_scope() first"
        )


def cinder_volumes_all(session: requests.Session, project_id: str):
    """
    Fetch Cinder volumes (all tenants, detailed).
    CINDER_ENDPOINT from catalog usually already includes /v3/{project_id}.
    """
    _require_cinder()
    # If endpoint already has /v3/<proj>, just append /volumes/detail
    url = f"{CINDER_ENDPOINT}/volumes/detail"
    # Only use all_tenants=1 if session is admin (token project == service project)
    extra_params = {"all_tenants": "1"} if getattr(session, "is_admin", False) else {}
    return paginate(session, url, "volumes", extra_params=extra_params)


def cinder_snapshots_all(session: requests.Session, project_id: str):
    """
    Fetch Cinder snapshots (all tenants, detailed).
    
    Note: When using project-scoped sessions, project_id should match
    the token scope. We reconstruct the URL with the provided project_id.
    """
    _require_cinder()
    # Reconstruct the URL with the correct project_id
    if CINDER_ENDPOINT:
        base_url = "/".join(CINDER_ENDPOINT.split("/")[:-1])  # Remove project_id
        url = f"{base_url}/{project_id}/snapshots/detail"
    else:
        raise RuntimeError("CINDER_ENDPOINT not initialized")
    # Only use all_tenants=1 if session is admin
    extra_params = {"all_tenants": "1"} if getattr(session, "is_admin", False) else {}
    return paginate(session, url, "snapshots", extra_params=extra_params)


def cinder_create_snapshot(
    session: requests.Session,
    project_id: str,
    volume_id: str,
    name: str = None,
    description: str = None,
    force: bool = True,
    metadata: dict = None,
):
    """
    Create a Cinder snapshot.
    
    Note: When using project-scoped sessions (e.g., service user auth),
    the project_id parameter is critical - it should match the project
    scope of the token in the session. We reconstruct the URL with the
    provided project_id to ensure it matches the token scope.
    
    Returns snapshot dict or raises exception on error.
    """
    _require_cinder()
    
    # Reconstruct the URL with the correct project_id
    # CINDER_ENDPOINT is like: https://api.example.com/cinder/v3/{admin_project_id}
    # We need to replace the project_id part with the actual project for this operation
    if CINDER_ENDPOINT:
        base_url = "/".join(CINDER_ENDPOINT.split("/")[:-1])  # Remove project_id
        url = f"{base_url}/{project_id}/snapshots"
    else:
        raise RuntimeError("CINDER_ENDPOINT not initialized")
    
    payload = {
        "snapshot": {
            "volume_id": volume_id,
            "force": force,
        }
    }
    if name:
        payload["snapshot"]["name"] = name
    if description:
        payload["snapshot"]["description"] = description
    if metadata:
        payload["snapshot"]["metadata"] = metadata

    data = http_json(session, "POST", url, json=payload)
    return data.get("snapshot", {})


def cinder_delete_snapshot(
    session: requests.Session, project_id: str, snapshot_id: str
):
    """
    Delete a Cinder snapshot.
    
    Note: When using project-scoped sessions, project_id should match
    the token scope. We reconstruct the URL with the provided project_id.
    Returns None on success, error string on failure.
    """
    _require_cinder()
    
    # Reconstruct the URL with the correct project_id
    if CINDER_ENDPOINT:
        base_url = "/".join(CINDER_ENDPOINT.split("/")[:-1])  # Remove project_id
        url = f"{base_url}/{project_id}/snapshots/{snapshot_id}"
    else:
        raise RuntimeError("CINDER_ENDPOINT not initialized")
    
    try:
        session.delete(url, timeout=CFG["REQUEST_TIMEOUT"])
        return None
    except Exception as e:
        return str(e)


# --------------------------------------------------------------------
# Glance helpers
# --------------------------------------------------------------------


def _require_glance():
    if not GLANCE_ENDPOINT:
        raise RuntimeError(
            "GLANCE_ENDPOINT not initialized – call get_session_best_scope() first"
        )


def glance_images(session: requests.Session):
    """
    Fetch Glance images (v2).
    """
    _require_glance()
    base = GLANCE_ENDPOINT.rstrip("/")
    # Handle both "https://...:9292" and "https://...:9292/v2"
    if not base.endswith("/v2"):
        base = base + "/v2"
    url = base + "/images"
    return paginate(session, url, "images")


# --------------------------------------------------------------------
# Neutron helpers
# --------------------------------------------------------------------


def _require_neutron():
    if not NEUTRON_ENDPOINT:
        raise RuntimeError(
            "NEUTRON_ENDPOINT not initialized – call get_session_best_scope() first"
        )


def neutron_list(session: requests.Session, resource: str):
    """
    Generic Neutron list helper.

    Example:
      neutron_list(session, "networks")         -> GET /v2.0/networks
      neutron_list(session, "ports")            -> GET /v2.0/ports
      neutron_list(session, "floatingips")      -> GET /v2.0/floatingips
      neutron_list(session, "security-groups")  -> GET /v2.0/security-groups
      neutron_list(session, "security-group-rules") -> GET /v2.0/security-group-rules
    """
    _require_neutron()
    url = f"{NEUTRON_ENDPOINT}/v2.0/{resource}"
    # Neutron uses hyphens in URLs but underscores in JSON response keys
    # e.g. "security-groups" -> {"security_groups": [...]}
    json_key = resource.replace("-", "_")
    return paginate(session, url, json_key)


# Integration: automate admin role assignment for service user

def ensure_admin_role_for_service_user():
    """
    Ensure snapshot@ccc.co.il has admin role in every tenant/project.
    Uses Keystone session and credentials from CFG.
    """
    try:
        from snapshots.snapshot_service_user import automate_admin_role_assignment, SERVICE_USER_EMAIL
    except ImportError:
        print("[ERROR] snapshot_service_user module not available; cannot automate admin role assignment.")
        return
    session, token, body, scope_mode, _ = get_session_best_scope()
    keystone_url = CFG["KEYSTONE_URL"]
    if not token or not keystone_url:
        print("[ERROR] Keystone session or URL not available.")
        return
    automate_admin_role_assignment(keystone_url, token, SERVICE_USER_EMAIL)
