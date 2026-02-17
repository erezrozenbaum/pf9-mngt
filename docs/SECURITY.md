# Platform9 Management System - Security Guide

## 🛡️ Security Status Overview

**Last Updated**: February 4, 2026  
**Security Level**: 🟡 **MEDIUM** - RBAC implemented, additional hardening recommended

### ✅ **Implemented Security Features**

1. **LDAP Authentication**: Enterprise OpenLDAP integration with configurable directory structure
2. **Role-Based Access Control (RBAC)**: 4-tier permission system with middleware enforcement
3. **JWT Token Management**: Secure Bearer token authentication with 480-minute sessions
4. **Permission Enforcement**: Automatic resource-level permission checks on all endpoints
5. **Audit Logging**: Complete authentication and authorization event tracking (90-day retention)
6. **User Management**: LDAP user creation, role assignment, and permission management
7. **Environment-Based Configuration**: Credentials properly externalized to `.env` file
8. **SQL Injection Prevention**: Parameterized queries throughout codebase
9. **Git Security**: Credentials excluded from version control via .gitignore
10. **Type Safety**: TypeScript usage in UI prevents certain classes of vulnerabilities
11. **Multi-Factor Authentication (MFA)**: TOTP-based 2FA with Google Authenticator, backup recovery codes, and two-step JWT challenge flow

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
| **Admin** | Full Operational | Manage servers/volumes/snapshots, modify networks/flavors | Full Admin panel |
| **Superadmin** | Complete System | All operations including user management | Full Admin panel with all tabs |

#### Permission Matrix

| Resource | Viewer | Operator | Admin | Superadmin |
|----------|--------|----------|-------|------------|
| Servers | read | read | admin | admin |
| Volumes | read | read | admin | admin |
| Snapshots | read | read | admin | admin |
| Networks | read | write | write | admin |
| Subnets | read | read | write | admin |
| Ports | read | read | read | admin |
| Floating IPs | read | read | write | admin |
| Security Groups | read | read | write | admin |
| Security Group Rules | read | read | write | admin |
| Flavors | read | write | write | admin |
| Images | read | read | read | admin |
| Users | - | - | - | admin |
| Domains | read | read | read | admin |
| Projects | read | read | read | admin |
| Restore | read | read | write | admin |
| Settings/Branding | - | - | admin | admin |
| Notifications | read, write | read, write | admin | admin |

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
  -d '{"username":"newuser","email":"user@company.com","password":"password123","role":"viewer"}'

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

### Required Environment Variables

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

### Priority 1: Critical (Fix Before Production)

1. **Change Default Passwords**
  - [ ] Set secure `LDAP_ADMIN_PASSWORD` in `.env` file
   - [ ] Change all default user passwords
   - [ ] Generate secure `JWT_SECRET_KEY` (64+ characters)
   - [ ] Use strong `POSTGRES_PASSWORD` (32+ characters)

2. **Restrict CORS Policy**
   - [ ] Replace `allow_origins=["*"]` with specific domains
   - [ ] Set `CORS_ORIGINS` environment variable
   - [ ] Test with production domain

3. **Implement HTTPS**
   - [ ] Obtain SSL/TLS certificates
   - [ ] Configure nginx/Apache reverse proxy
   - [ ] Redirect all HTTP traffic to HTTPS
   - [ ] Add HSTS headers

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

9. **Container Resource Limits**
   ```yaml
   services:
     pf9_api:
       deploy:
         resources:
           limits:
             memory: 512M
             cpus: '0.5'
   ```

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
- [ ] Configure HTTPS with valid SSL/TLS certificates
- [ ] Implement rate limiting on API endpoints
- [ ] Enable database SSL/TLS connections
- [ ] Add security headers to all responses
- [ ] Configure resource limits on containers
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
