# Platform9 Management System - Security Guide

## 🛡️ Security Status Overview

**Last Updated**: March 2026
**Security Level**: � **HIGH** — Active hardening in place; production-ready with TLS, RBAC, injection mitigations, session revocation, and Docker secrets support.

### ✅ **Implemented Security Features**

1. **LDAP Authentication**: Enterprise OpenLDAP integration with configurable directory structure
2. **Role-Based Access Control (RBAC)**: 5-tier permission system (Viewer, Operator, Admin, Superadmin, Technical) with middleware enforcement
3. **JWT Token Management**: Secure Bearer token authentication with 480-minute sessions
4. **Session Revocation**: All sessions tracked in `user_sessions` table; logout immediately invalidates the token server-side (Phase B4)
5. **Permission Enforcement**: Automatic resource-level permission checks on all endpoints
6. **Audit Logging**: Complete authentication and authorization event tracking (90-day retention)
7. **User Management**: LDAP user creation, role assignment, and permission management
8. **Docker Secrets Support**: Critical credentials (DB password, LDAP password, PF9 password, JWT key) read from `/run/secrets/` files in production with env-var fallback for dev (Phase J5)
9. **SQL Injection Prevention**: Parameterized queries throughout codebase
10. **LDAP Injection Prevention**: All LDAP filter values escaped with `ldap.filter.escape_filter_chars()` (Phase A3)
11. **Command Injection Prevention**: All SSH commands use `shlex.quote()` + allowlist validation (Phase A4)
12. **XSS Prevention**: DOMPurify applied to all user-generated HTML rendered in the UI (Phase B1)
13. **Git Security**: Credentials excluded from version control via .gitignore; `secrets/` directory gitignored with exception for README
14. **Type Safety**: TypeScript usage in UI prevents certain classes of vulnerabilities
15. **Multi-Factor Authentication (MFA)**: TOTP-based 2FA with Google Authenticator, backup recovery codes, and two-step JWT challenge flow
16. **CORS Hardening**: `allow_origins` derived from `ALLOWED_ORIGINS` env var; wildcard `*` removed (Phase B3)
17. **Webhook HMAC Verification**: Incoming webhook payloads validated with HMAC-SHA256 signature (Phase E3)
18. **Backup Integrity**: HMAC-SHA256 checksums stored and verified for backup archives (Phase E5)
19. **LDAP File Descriptor Safety**: All LDAP connection methods use `try/finally` to guarantee `conn.unbind_s()` on both success and exception paths (Phase M2.3)
20. **Multi-Cluster SSRF Protection**: `pf9_control_planes.allow_private_network` defaults to `FALSE`; all control-plane URLs validated against RFC-1918/loopback blocklists before any outbound connection. Only superadmin can override per record.
21. **Region-Scoped Cache Isolation**: Redis cache keys include `region_id` segment (`pf9:{resource}:{region_id}:{hash}`) preventing cross-region data exposure in multi-cluster deployments.
22. **Password-in-DB Prevention**: Control-plane credentials in `pf9_control_planes.password_enc` are stored as `env:{sha256[:16]}` hash markers; the actual credential is always read from a Docker secret or env var at runtime — never persisted in plaintext.

---

## 🔐 Authentication & Authorization

### LDAP Configuration


The system uses OpenLDAP for enterprise user authentication:

> **Note:** As of February 2026, running `deployment.ps1` will always ensure:
> - The admin user (from `.env`: `DEFAULT_ADMIN_USER`/`DEFAULT_ADMIN_PASSWORD`) is created in LDAP and in the `user_roles` table as `superadmin`.
> - The `superadmin` role always has a wildcard permission (`*`) in `role_permissions`.
> - You do **not** need to manually create the admin user or fix permissions in the database—this is enforced automatically on every deployment.
> - If you change the admin username/email in `.env`, simply re-run `deployment.ps1` and the system will update LDAP and database roles/permissions accordingly.

Manual LDAP or database admin setup is no longer required for initial deployment or admin recovery.

```bash
# LDAP Server Settings (configured in docker-compose.yml)
LDAP_SERVER=ldap
LDAP_PORT=389
LDAP_BASE_DN=dc=company,dc=local
LDAP_USER_DN=ou=users,dc=company,dc=local
LDAP_ADMIN_PASSWORD=${LDAP_ADMIN_PASSWORD}  # Set in .env file
```

**Note**: All user passwords must be set securely via environment variables or LDAP admin panel. Never use default passwords in production.

### JWT Token Management

```bash
# JWT Settings (add to .env)
JWT_SECRET_KEY=<GENERATE: openssl rand -base64 64>  # ⚠️ REQUIRED — do not use a placeholder
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=480  # 8 hours
ENABLE_AUTHENTICATION=true
```

**Token Features**:
- 480-minute (8 hour) expiration
- Bearer token format
- Includes username and role claims
- Tracked in `user_sessions` table with IP and user agent

### Multi-Factor Authentication (MFA)

**TOTP-Based Two-Factor Authentication** (v1.14+):
- Compatible with Google Authenticator, Authy, and any TOTP app (RFC 6238)
- Self-service enrollment via QR code scan or manual secret key entry
- Two-step JWT challenge flow:
  1. User authenticates with LDAP credentials
  2. If MFA enabled: API returns short-lived `mfa_token` (5-minute TTL)
  3. Client submits TOTP code with `mfa_token` → receives full session JWT
- 8 one-time backup recovery codes (SHA-256 hashed, consumed on use)
- MFA secrets stored in `user_mfa` database table

**API Endpoints**:
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/mfa/setup` | POST | Generate TOTP secret + QR code |
| `/auth/mfa/verify-setup` | POST | Confirm enrollment, returns backup codes |
| `/auth/mfa/verify` | POST | Login MFA challenge verification |
| `/auth/mfa/disable` | POST | Disable MFA (requires TOTP code) |
| `/auth/mfa/status` | GET | Current user's MFA status |
| `/auth/mfa/users` | GET | Admin: all users' MFA enrollment |

**Security Recommendations**:
- Enforce MFA for admin and superadmin accounts
- Store backup codes securely (encrypted vault or printed hardcopy)
- Rotate TOTP secrets periodically by disabling and re-enrolling

### Role-Based Access Control (RBAC)

#### Role Hierarchy

| Role | Access Level | Capabilities | UI Access |
|------|-------------|--------------|-----------|
| **Viewer** | Read-only | View all resources | No Admin tab, only System Audit |
| **Operator** | Read + Limited Write | View all, modify networks/flavors | No Admin tab |
| **Admin** | Full Operational | Manage servers/volumes/snapshots, departments, navigation | Full Admin panel |
| **Superadmin** | Complete System | All operations including user management | Full Admin panel with all tabs |
| **Technical** | Read + Provisioning | Read all, create tenants/orgs, NO delete | Limited Admin access |

#### Permission Matrix

| Resource | Viewer | Operator | Admin | Superadmin | Technical |
|----------|--------|----------|-------|------------|----------|
| Servers | read | read | admin | admin | read |
| Volumes | read | read | admin | admin | read |
| Snapshots | read | read | admin | admin | read |
| Networks | read | write | write | admin | write |
| Subnets | read | read | write | admin | read |
| Ports | read | read | read | admin | read |
| Floating IPs | read | read | write | admin | read |
| Security Groups | read | read | write | admin | read |
| Security Group Rules | read | read | write | admin | read |
| Flavors | read | write | write | admin | write |
| Images | read | read | read | admin | read |
| Users | - | - | - | admin | - |
| Domains | read | read | read | admin | read |
| Projects | read | read | read | admin | read |
| Restore | read | read | write | admin | read |
| Settings/Branding | - | - | admin | admin | read |
| Notifications | read, write | read, write | admin | admin | read, write |
| Departments | read | read | admin | admin | read |
| Navigation | read | read | admin | admin | read |
| Search | read | read | admin | admin | read |
| Runbooks | read | read, write | admin | admin | read |

### Public (Unauthenticated) Endpoints

The following paths bypass RBAC middleware and do not require a Bearer token:

| Path | Purpose |
|------|---------|
| `/auth/login` | User authentication |
| `/health` | API health check |
| `/settings/branding` (GET only) | Login page branding data (needed before user logs in) |
| `/static/*` | Uploaded logos and static assets |

### RBAC Middleware Operation

The system automatically enforces permissions on all API endpoints:

1. **Token Validation**: Verifies Bearer token from Authorization header
2. **User Identification**: Extracts username from JWT token payload
3. **Role Resolution**: Looks up user's role from `user_roles` table
4. **Resource Mapping**: Maps URL path to permission resource (e.g., `/servers` → `servers`)
5. **Permission Check**: Queries `role_permissions` table for required action (read/write/admin)
6. **Enforcement**: Returns 403 Forbidden if permission denied, logs event to `auth_audit_log`

### Restore-Specific Security Controls

The snapshot restore feature includes additional security safeguards:

- **Feature Toggle**: Restore is disabled by default (`RESTORE_ENABLED=false`). All endpoints return 404 when disabled.
- **REPLACE Mode Restriction**: Destructive restore (deleting the original VM) requires **superadmin** role (`restore:admin`).
- **Destructive Confirmation**: REPLACE mode requires the caller to send `confirm_destructive: "DELETE AND RESTORE <vm_name>"` — an exact string match prevents accidental destructive operations.
- **Concurrency Guard**: A unique partial index prevents two simultaneous restores of the same VM.
- **Dry-Run Mode**: Operators can validate restore plans without executing them (`RESTORE_DRY_RUN=true`).
- **Cross-Tenant Access**: Uses the same service user scoping as snapshot creation — the service user must have admin role on the target project.

See [RESTORE_GUIDE.md](RESTORE_GUIDE.md) for full restore documentation.

---

## 🚀 Authentication API Usage

### Login

```bash
# Login via API
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-secure-password"}'

# Response includes JWT token
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer",
  "expires_in": 28800,
  "user": {
    "username": "admin",
    "role": "superadmin",
    "is_active": true
  }
}
```

### Using JWT Token

```bash
# Include Bearer token in Authorization header
curl -X GET http://localhost:8000/servers \
  -H "Authorization: Bearer eyJhbGc..."

# Permission denied for unauthorized operations
curl -X POST http://localhost:8000/servers \
  -H "Authorization: Bearer <viewer-token>" \
  -H "Content-Type: application/json"
# Returns: 403 Forbidden - Insufficient permissions
```

### User Management (Superadmin Only)

```bash
# Create new LDAP user
curl -X POST http://localhost:8000/auth/users \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"username":"newuser","email":"user@company.com","password":"REDACTED_PASSWORD","role":"viewer"}'

# Update user role
curl -X POST http://localhost:8000/auth/users/newuser/role \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"role":"operator"}'

# Delete user
curl -X DELETE http://localhost:8000/auth/users/newuser \
  -H "Authorization: Bearer <admin-token>"
```

### Logout

```bash
# Logout (invalidates session and records audit event)
curl -X POST http://localhost:8000/auth/logout \
  -H "Authorization: Bearer <your-token>"
```

---

## 📊 Audit Logging

### Audit Events Tracked

The system logs all authentication and authorization events to `auth_audit_log` table:

- `login` - Successful authentication
- `logout` - User logout
- `failed_login` - Failed authentication attempt
- `user_created` - New user created in LDAP
- `user_deleted` - User removed from LDAP
- `role_changed` - User role modified
- `permission_denied` - Access attempt blocked by RBAC (includes resource and endpoint)

### Audit Log Retrieval

```bash
# Get audit logs (authenticated users only)
curl -X GET "http://localhost:8000/auth/audit?username=admin&days=7" \
  -H "Authorization: Bearer <your-token>"

# Filter by action
curl -X GET "http://localhost:8000/auth/audit?action=permission_denied&days=30" \
  -H "Authorization: Bearer <your-token>"
```

### Audit Log Retention

- **Retention Period**: 90 days (automatic cleanup)
- **Stored Data**: timestamp, username, action, IP address, user agent, status, details (JSON)
- **Access**: Via Admin panel → System Audit tab or API endpoint `/auth/audit`

---

## 🔧 Production Security Configuration

### Option A: Docker Secrets (Recommended for Production)

Sensitive credentials are read from files under `./secrets/` (mounted into the container
at `/run/secrets/<name>`). See [secrets/README.md](../secrets/README.md) for the full
mapping. The API falls back to environment variables when the file is empty, so dev
environments still work with just a `.env` file.

```bash
# Production setup
printf 'your-db-password'       > secrets/db_password
printf 'your-ldap-admin-pass'   > secrets/ldap_admin_password
printf 'your-pf9-api-password'  > secrets/pf9_password
python -c "import secrets; print(secrets.token_urlsafe(48), end='')" > secrets/jwt_secret

# Verify — secrets/ is gitignored except README
git status secrets/
```

### Option B: Environment Variables (Dev / Legacy)

Create `.env` file with secure configuration:

```bash
# Database Configuration
POSTGRES_USER=pf9_admin
POSTGRES_PASSWORD=<USE: openssl rand -base64 32>
POSTGRES_DB=pf9_mgmt

# Platform9 Service Account
PF9_USERNAME=service-automation@company.com  # Use service account, not personal
PF9_PASSWORD=<secure-service-password>
PF9_AUTH_URL=https://your-pf9-cluster.platform9.com/keystone/v3
PF9_USER_DOMAIN=Default
PF9_PROJECT_NAME=service
PF9_PROJECT_DOMAIN=Default
PF9_REGION_NAME=region-one

# JWT Configuration
JWT_SECRET_KEY=<USE: openssl rand -base64 64>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=480
ENABLE_AUTHENTICATION=true

# LDAP Configuration
LDAP_ORGANISATION=Your Organization Name
LDAP_DOMAIN=your-domain.com
LDAP_ADMIN_PASSWORD=<secure-ldap-password>
LDAP_CONFIG_PASSWORD=<secure-config-password>

# Security Settings
PF9_ALLOWED_ORIGIN=https://pf9-mgmt.company.com  # Your production domain
CORS_ORIGINS=http://localhost:5173,https://pf9-mgmt.company.com

# Database Admin (pgAdmin)
PGADMIN_EMAIL=admin@company.com
PGADMIN_PASSWORD=<secure-admin-password>
```

### CORS Policy Fix (Recommended)

**Current Issue**: Both [api/main.py](../api/main.py#L29) and [monitoring/main.py](../monitoring/main.py#L16) use `allow_origins=["*"]`

**Recommended Fix**:

```python
# api/main.py and monitoring/main.py
import os

allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Restricted origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"]
)
```

### HTTPS Enforcement (Production Required)

Use a reverse proxy (nginx/Apache) for SSL/TLS termination:

```nginx
# /etc/nginx/sites-available/pf9-mgmt
server {
    listen 443 ssl http2;
    server_name pf9-mgmt.company.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";
    
    # API Backend
    location /api/ {
        proxy_pass http://localhost:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # Monitoring Service
    location /monitoring/ {
        proxy_pass http://localhost:8001/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    # Frontend UI
    location / {
        proxy_pass http://localhost:5173/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name pf9-mgmt.company.com;
    return 301 https://$server_name$request_uri;
}
```

---

## 🚨 Security Hardening Recommendations

### Priority 1: Critical (Production Checklist)

1. **Change Default Passwords** (required before first deploy)
  - [ ] Set secure `LDAP_ADMIN_PASSWORD` in `.env` file (or `secrets/ldap_admin_password`)
   - [ ] Change all default user passwords
   - [x] Generate secure `JWT_SECRET_KEY` — reads from `secrets/jwt_secret` with env-var fallback
   - [ ] Use strong `POSTGRES_PASSWORD` (32+ characters)

2. **Restrict CORS Policy** ✅ *(Phase B3)*
   - [x] `allow_origins` derived from `ALLOWED_ORIGINS` env var — wildcard `*` removed
   - [x] `TrustedHostMiddleware` added to reject requests with unexpected Host headers

3. **Implement HTTPS** ✅ *(Phase C)*
   - [x] nginx reverse proxy deployed — see `nginx/` directory
   - [x] HTTP→HTTPS redirect on port 80
   - [x] HSTS, X-Frame-Options, X-Content-Type-Options headers added
   - [x] All API/UI/monitoring ports closed in `docker-compose.prod.yml` — only nginx 80/443 exposed (Phase M2.2)
   - [ ] Replace `nginx/certs/server.crt` / `server.key` with a real CA-signed certificate for production

4. **Docker Secrets** ✅ *(Phase J5)*
   - [x] `api/secret_helper.py` reads from `/run/secrets/` with env-var fallback
   - [x] DB password, LDAP admin password, PF9 password, JWT key all use `read_secret()`
   - [x] `secrets/` directory gitignored; placeholder files included so Docker starts without errors

### Priority 2: High (Recommended)

4. **Rate Limiting**
   ```bash
   # Install slowapi
   pip install slowapi
   ```
   ```python
   # api/main.py
   from slowapi import Limiter, _rate_limit_exceeded_handler
   from slowapi.util import get_remote_address
   from slowapi.errors import RateLimitExceeded
   
   limiter = Limiter(key_func=get_remote_address)
   app.state.limiter = limiter
   app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
   
   @app.get("/servers")
   @limiter.limit("100/minute")
   async def servers(request: Request, ...):
       pass
   ```

5. **Input Validation Enhancement**
   ```python
   from pydantic import BaseModel, Field, validator
   
   class ServerQuery(BaseModel):
       page: int = Field(ge=1, le=1000, default=1)
       page_size: int = Field(ge=1, le=100, default=50)  # Reduced from 500
       sort_by: Optional[str] = Field(regex="^[a-zA-Z_]+$")
       
       @validator('sort_by')
       def validate_sort_field(cls, v):
           allowed = ['vm_name', 'status', 'created_at', 'domain_name']
           if v and v not in allowed:
               raise ValueError(f'Invalid sort field. Allowed: {allowed}')
           return v
   ```

6. **Database SSL/TLS**
   ```yaml
   # docker-compose.yml
   services:
     db:
       command: |
         postgres 
           -c ssl=on 
           -c ssl_cert_file=/var/lib/postgresql/server.crt
           -c ssl_key_file=/var/lib/postgresql/server.key
       volumes:
         - ./secrets/postgres-ssl:/var/lib/postgresql/:ro
   ```

### Priority 3: Medium (Security Enhancements)

7. **Security Headers**
   ```python
   @app.middleware("http")
   async def add_security_headers(request, call_next):
       response = await call_next(request)
       response.headers["X-Content-Type-Options"] = "nosniff"
       response.headers["X-Frame-Options"] = "DENY"
       response.headers["X-XSS-Protection"] = "1; mode=block"
       response.headers["Content-Security-Policy"] = "default-src 'self'"
       return response
   ```

8. **Database Connection Limits**
   ```yaml
   db:
     command: postgres -c max_connections=20
   ```

9. **Container Resource Limits** ✅ *(deployed in Phase C)*
   All services have `deploy.resources.limits` in `docker-compose.yml`:
   `pf9_api` (1.5 CPU / 1 GiB), `db` (1.0 CPU / 1 GiB), workers (0.5 CPU / 256 MiB), `nginx` (0.5 CPU / 128 MiB), `redis` (0.3 CPU / 192 MiB).

---

## 🧪 Security Testing

### Automated Security Scanning

```bash
# Container vulnerability scanning
docker scout cves pf9-mngt_pf9_api

# Python security linting
pip install bandit
bandit -r api/ -f json -o security-report.json

# Dependency vulnerability check
pip install safety
safety check -r api/requirements.txt

# Secret scanning (prevent credential commits)
git-secrets --scan-history
```

### Manual Security Testing

```bash
# Test RBAC enforcement (should return 403 for viewer role)
curl -X POST http://localhost:8000/servers \
  -H "Authorization: Bearer <viewer-token>" \
  -H "Content-Type: application/json"

# Test CORS policy
curl -H "Origin: http://malicious-site.com" \
  -H "Access-Control-Request-Method: GET" \
  -X OPTIONS http://localhost:8000/servers

# Test rate limiting (if implemented)
for i in {1..150}; do curl http://localhost:8000/servers; done

# Monitor authentication failures
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"wrong-password"}'
```

### Security Monitoring

```bash
# Monitor API activity
docker logs pf9_api 2>&1 | grep -E "(POST|DELETE|PUT)" | tail -50

# Check authentication events
docker logs pf9_api 2>&1 | grep -E "(login|logout|failed_login)"

# Database active connections
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "
  SELECT application_name, client_addr, state, query_start 
  FROM pg_stat_activity WHERE state = 'active';"

# Review audit log for permission denials
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "
  SELECT * FROM auth_audit_log 
  WHERE action = 'permission_denied' 
  ORDER BY timestamp DESC LIMIT 20;"
```

---

## � Snapshot Service User Security

### Overview

A dedicated service user (configured via `SNAPSHOT_SERVICE_USER_EMAIL`) is used for cross-tenant snapshot operations. This user is granted admin role on each tenant project to create snapshots in the correct project scope.

### Security Model

| Aspect | Detail |
|--------|--------|
| **User** | Configured via `SNAPSHOT_SERVICE_USER_EMAIL` (pre-created in Platform9) |
| **Role** | `admin` per-project (minimum required for snapshot creation) |
| **Scope** | Project-scoped tokens (not domain-scoped) |
| **Password** | Stored encrypted (Fernet) or plaintext in `.env` |
| **Role Assignment** | Automatic via Keystone API, cached per-run |
| **Disable Switch** | `SNAPSHOT_SERVICE_USER_DISABLED=true` |

### Password Storage

Two options for storing the service user password:

1. **Plaintext** (`SNAPSHOT_SERVICE_USER_PASSWORD`) — Simpler, acceptable if `.env` is properly protected
2. **Fernet Encrypted** (`SNAPSHOT_PASSWORD_KEY` + `SNAPSHOT_USER_PASSWORD_ENCRYPTED`) — Industry-standard symmetric encryption

**Recommendations**:
- Use Fernet encryption in production environments
- Protect `.env` with restricted file permissions (`chmod 600` / `icacls`)
- Rotate password periodically and update both Platform9 and `.env`

### Audit & Monitoring

Monitor for snapshot service user activity:

```bash
# Check service user role assignments
docker logs pf9_snapshot_worker 2>&1 | grep "SERVICE_USER"

# Review role grants in Keystone
openstack role assignment list --user $SNAPSHOT_SERVICE_USER_EMAIL
```

### Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Password exposure | Fernet encryption + `.env` file permissions |
| Excessive privileges | Admin role assigned per-project only (not domain-wide) |
| Stale role assignments | Role cache cleared on each snapshot scheduler run |
| Service disruption | Graceful fallback to admin session if service user fails |

See [Snapshot Service User Guide](SNAPSHOT_SERVICE_USER.md) for full details.

---

## �🔒 Data Protection

### Sensitive Information Handling

**Excluded from Git** (via .gitignore):
- `.env` - All credentials
- `secrets/` - Password files
- `*.log` - Log files may contain sensitive data
- `.venv/` - Virtual environment
- `p9_rvtools_state.json` - Runtime state
- `metrics_cache.json` - Cached metrics

**Included in Git** (safe for version control):
- `.env.template` - Template without credentials
- `snapshots/snapshot_policy_rules.json` - Policy configuration
- `package.json`, `tsconfig.json` - Build configuration

### Customer Data Masking

The `pf9_rvtools.py` script supports customer data masking for exports:

```bash
# Export with customer data masking enabled
python pf9_rvtools.py --mask-customer-data
```

Masks:
- VM names: Partial masking (first 3 chars visible)
- IP addresses: Randomized last octet
- Volume names: Generic naming
- Snapshot names: Pattern-based masking

---

## 📋 Security Checklist

### Before Production Deployment

- [ ] Update all default passwords (LDAP, PostgreSQL, JWT secret)
- [ ] Configure snapshot service user password (encrypted recommended)
- [ ] Verify snapshot service user exists in Platform9 (email from `SNAPSHOT_SERVICE_USER_EMAIL`)
- [ ] Restrict CORS to production domain only
- [x] Configure HTTPS with valid SSL/TLS certificates *(nginx deployed; swap dev cert for CA-signed cert in prod)*
- [ ] Implement rate limiting on API endpoints
- [ ] Enable database SSL/TLS connections
- [ ] Add security headers to all responses
- [x] Configure resource limits on containers *(deploy.resources.limits on all services)*
- [ ] Set up centralized logging and monitoring
- [ ] Create backup and disaster recovery procedures
- [ ] Document incident response procedures
- [ ] Conduct penetration testing
- [ ] Review and update firewall rules

### Ongoing Security Maintenance

- [ ] Rotate JWT secret keys every 90 days
- [ ] Review audit logs weekly
- [ ] Update dependencies monthly (security patches)
- [ ] Scan containers for vulnerabilities weekly
- [ ] Review user access permissions quarterly
- [ ] Update security documentation as changes occur
- [ ] Conduct security training for administrators

---

## 🌐 Multi-Cluster Security Controls

### SSRF Protection

`pf9_control_planes.allow_private_network` is `BOOLEAN NOT NULL DEFAULT FALSE`. This field is the per-record SSRF guard for control plane registrations.

| `allow_private_network` | Effect |
|---|---|
| `FALSE` (default) | `auth_url` and all URLs in cross-region task payloads **will be** validated against RFC-1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) and loopback (127.0.0.0/8, ::1) blocklists before any HTTP connection |
| `TRUE` | Private-network connections permitted for this control plane — required for on-premises PF9 with a private IP |

> **Implementation note (v1.73.0 — Phase 1):** The schema column and default are in place. Runtime URL validation at the API write layer is enforced when the Cluster Registry API ships (Phase 3). In Phase 1 there is no API to register control planes — `auth_url` is sourced exclusively from the operator-supplied `PF9_AUTH_URL` environment variable, so no user-controlled SSRF vector exists.

Only a **superadmin** can set `allow_private_network = TRUE`. The flag is per-record, never global.

Verify your deployment has no unintended overrides:
```sql
SELECT id, auth_url, allow_private_network
FROM pf9_control_planes
WHERE allow_private_network = TRUE;
-- Should return zero rows for cloud-hosted deployments
```

### Credential Storage

Passwords for control planes in `pf9_control_planes.password_enc` use the format `env:{sha256_prefix}` — a hash marker that tells the runtime to read the actual credential from the `PF9_PASSWORD` Docker secret or env var. **Plaintext passwords are never written to the database.**

Verify this holds on any deployment:
```sql
SELECT id, left(password_enc, 4) AS prefix FROM pf9_control_planes;
-- All rows should show prefix = 'env:'
```

Full AES-256-GCM encryption of stored credentials (for multi-cluster records that use different passwords) is planned for a future release. The `env:` marker system ensures all current deployments are safe in the interim.

### Cache Isolation

Redis cache keys include a `region_id` segment: `pf9:{resource}:{region_id}:{md5(args)}`. Data from different regions is stored under distinct key namespaces — no cross-region data exposure in shared-Redis multi-cluster deployments. Deployments with a single region use `region_id=default` and are unaffected by this change.

---

## 🚨 Incident Response

### If Credentials Are Compromised

1. **Immediately disable the compromised account**
   - Platform9: Disable service account
   - LDAP: Disable affected user(s)
   - Database: Revoke access

2. **Generate new credentials**
   ```bash
   # Generate new JWT secret
   openssl rand -base64 64
   
   # Generate new database password
   openssl rand -base64 32
   ```

3. **Update all configurations**
   - Update `.env` file
   - Restart all services: `docker-compose down && .\startup.ps1`

4. **Review audit logs**
   ```sql
   SELECT * FROM auth_audit_log 
   WHERE username = '<compromised-user>' 
   ORDER BY timestamp DESC;
   ```

5. **Notify security team and stakeholders**

### Security Event Monitoring

**High-priority events to monitor**:
- Multiple failed login attempts (brute force)
- Permission denied events (unauthorized access attempts)
- User creation/deletion (account management)
- Administrative operations (flavor/network changes)
- Database connection failures
- Unusual API request patterns

---

## 📞 Security Contacts

- **Internal Security Team**: security@company.com
- **Platform9 Support**: support@platform9.com
- **Infrastructure Team**: infra@company.com

---

## 📚 Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security Guide](https://fastapi.tiangolo.com/tutorial/security/)
- [PostgreSQL Security Best Practices](https://www.postgresql.org/docs/current/security.html)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)

---

**Last Review**: February 4, 2026  
**Next Review**: May 4, 2026 (Quarterly)
