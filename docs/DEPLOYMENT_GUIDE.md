# Platform9 Management System - Deployment Guide

**Version**: 2.1  
**Last Updated**: February 2026  
**Status**: Production Ready  
**Deployment Platform**: Docker Compose (Windows, Linux, macOS)  
**Alternative**: See [KUBERNETES_MIGRATION_GUIDE.md](KUBERNETES_MIGRATION_GUIDE.md) for Kubernetes deployment

---

## Table of Contents

1. [Quick Start (5 Minutes)](#quick-start-5-minutes)
2. [System Requirements](#system-requirements)
3. [Pre-Deployment Checklist](#pre-deployment-checklist)
4. [Detailed Installation](#detailed-installation)
5. [Environment Configuration](#environment-configuration)
6. [First-Time Setup](#first-time-setup)
7. [Verification & Testing](#verification--testing)
8. [Post-Deployment Operations](#post-deployment-operations)
9. [Common Issues & Troubleshooting](#common-issues--troubleshooting)
10. [Backup & Recovery](#backup--recovery)
11. [Upgrade & Migration](#upgrade--migration)
12. [Production Hardening](#production-hardening)

---

## Quick Start (5 Minutes)

For the impatient developer:

```bash
# 1. Clone repository
git clone https://github.com/yourusername/pf9-management.git
cd pf9-management

# 2. Create minimal .env file
cat > .env << 'EOF'
POSTGRES_USER=pf9admin
POSTGRES_PASSWORD=$(openssl rand -base64 32)
POSTGRES_DB=pf9_mgmt
JWT_SECRET_KEY=$(openssl rand -base64 64)
LDAP_ADMIN_PASSWORD=$(openssl rand -base64 16)
LDAP_CONFIG_PASSWORD=$(openssl rand -base64 16)
LDAP_READONLY_PASSWORD=$(openssl rand -base64 16)
PF9_AUTH_URL=https://your-pf9-cluster.platform9.com/keystone/v3
PF9_USERNAME=service-automation@company.com
PF9_PASSWORD=your-service-password
EOF

# 3. Start all services
docker-compose up -d

# Windows automated deployment (includes validation, admin user/role/permission automation, and health checks)
# .\deployment.ps1

# 4. Wait for services to be ready
docker-compose ps

# 5. Access the system
# UI: http://localhost:5173
# API: http://localhost:8000
# Monitoring: http://localhost:8001
# pgAdmin: http://localhost:8080
# LDAP Admin: http://localhost:8081
```

> ⚠️ This quick start uses default/weak configurations. **Do NOT use in production**. See [Production Hardening](#production-hardening).

---

## System Requirements

### Hardware Requirements

| Component | Minimum | Recommended | Production |
|-----------|---------|-------------|-----------|
| **CPU** | 2 cores | 4 cores | 8 cores |
| **RAM** | 4 GB | 8 GB | 16 GB |
| **Disk** | 20 GB SSD | 50 GB SSD | 100+ GB SSD |
| **Network** | 100 Mbps | 1 Gbps | 1 Gbps+ |

### Software Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| **Docker** | 20.10+ | [Install Docker](https://docs.docker.com/get-docker/) |
| **Docker Compose** | 2.0+ | Included with Docker Desktop |
| **Python** | 3.9+ | Required for host scripts (optional) |
| **Git** | 2.30+ | For repository cloning |
| **Node.js** | 18+ | Only needed if building UI from source |

### Network Requirements

| Service | Port | Protocol | Access Required |
|---------|------|----------|-----------------|
| UI Frontend | 5173 | HTTP | Internal/External |
| API Backend | 8000 | HTTP | Internal/External |
| Monitoring | 8001 | HTTP | Internal/External |
| Database | 5432 | PostgreSQL | Internal only |
| pgAdmin | 8080 | HTTP | Internal only |
| LDAP | 389 | LDAP | Internal only |
| LDAP SSL | 636 | LDAP+TLS | Internal only |
| LDAP Admin UI | 8081 | HTTP | Internal only |

### Disk Space Breakdown

```
Application:          ~2 GB (UI, API, Monitoring containers)
PostgreSQL Image:     ~200 MB
Database Data:        ~1-10 GB (depends on infrastructure scale)
Volumes (Metadata):   ~500 MB
Cache & Temp:         ~1 GB
Margin (20%):         ~3 GB
Total Minimum:        ~20 GB
Total Recommended:    ~50-100 GB
```

### Port Availability

Ensure these ports are not in use:

```bash
# Check port availability (Linux/macOS)
lsof -i :5173 :8000 :8001 :5432 :8080 :389 :636 :8081

# Check port availability (Windows PowerShell)
netstat -ano | findstr ":5173 :8000 :8001 :5432 :8080 :389 :636 :8081"
```

---

## Pre-Deployment Checklist

### System Preparation

- [ ] Verify Docker is installed: `docker --version`
- [ ] Verify Docker Compose: `docker-compose --version`
- [ ] Check disk space: `df -h` (need 20+ GB free)
- [ ] Check available RAM: `free -h` (recommend 8+ GB)
- [ ] Verify all required ports are available
- [ ] Internet connectivity verified
- [ ] DNS resolution working: `ping platform9.com`

### Access & Credentials

- [ ] Platform9 credentials obtained (service account or user)
- [ ] Platform9 cluster URL confirmed
- [ ] SSH access to PF9 hosts verified (if using host metrics)
- [ ] Network connectivity to PF9 hosts confirmed
- [ ] LDAP domain/organization name decided
- [ ] Admin email address for LDAP

### Repository Setup

- [ ] Git installed: `git --version`
- [ ] SSH keys configured (if using SSH clone): `ssh -T git@github.com`
- [ ] Repository cloned and accessible
- [ ] Git LFS installed (if needed): `git lfs --version`

### Configuration

- [ ] `.env.template` file reviewed
- [ ] All required environment variables identified
- [ ] Passwords generated (use secure methods)
- [ ] IP addresses/hostnames of PF9 hosts gathered
- [ ] LDAP domain structure planned
- [ ] Backup location decided

---

## Detailed Installation

### Step 1: Clone Repository

```bash
# HTTPS (no SSH key needed)
git clone https://github.com/yourusername/pf9-management.git
cd pf9-management

# SSH (if you have SSH key configured)
git clone git@github.com:yourusername/pf9-management.git
cd pf9-management

# Verify structure
ls -la
# Expected output:
# -rw-r--r-- docker-compose.yml
# -rw-r--r-- startup.ps1
# drwxr-xr-x api/
# drwxr-xr-x pf9-ui/
# drwxr-xr-x monitoring/
# drwxr-xr-x db/
# drwxr-xr-x docs/
```

### Step 2: Install Prerequisites

#### Windows

```powershell
# Check Docker installation
docker --version
docker-compose --version

# If Docker is not installed, download from:
# https://www.docker.com/products/docker-desktop

# Verify WSL2 backend is enabled
wsl --list --verbose
# Should show Ubuntu or similar with VERSION 2
```

#### Linux

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
sudo apt-get install docker-compose-plugin

# Add user to docker group (avoid sudo)
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
docker-compose --version
```

#### macOS

```bash
# Install Docker Desktop for Mac
# https://www.docker.com/products/docker-desktop

# Or use Homebrew
brew install --cask docker
brew install docker-compose

# Verify
docker --version
docker-compose --version
```

### Step 3: Create Environment File

```bash
# Copy template
cp .env.template .env

# Edit with your values
nano .env  # or: code .env (for VS Code)
```

See [Environment Configuration](#environment-configuration) for detailed explanations.

### Step 4: Build Container Images

```bash
# Build all images (takes 5-10 minutes first time)
docker-compose build

# View build progress
docker-compose build --progress=plain

# Expected output:
# [+] Building 45.3s (XX/XX)
#  => [api base] ...
#  => [ui base] ...
#  => [monitoring base] ...
```

### Step 5: Start Services

```bash
# Start all services in background
docker-compose up -d

# Watch startup progress (Ctrl+C to exit)
docker-compose logs -f

# Check status
docker-compose ps

# Expected output:
# NAME            STATUS           PORTS
# pf9_db          Up (healthy)     0.0.0.0:5432->5432/tcp
# pf9_ldap        Up (healthy)     0.0.0.0:389->389/tcp
# pf9_api         Up (healthy)     0.0.0.0:8000->8000/tcp
# pf9_ui          Up (healthy)     0.0.0.0:5173->5173/tcp
# pf9_monitoring  Up (healthy)     0.0.0.0:8001->8001/tcp
# pf9_pgadmin     Up (healthy)     0.0.0.0:8080->80/tcp
# phpldapadmin    Up (healthy)     0.0.0.0:8081->80/tcp
```

### Step 6: Verify Database Initialization

```bash
# Check if database was initialized
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "\dt"

# Expected: List of tables (domains, projects, servers, volumes, etc.)

# If tables are empty, manually run init:
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/init.sql
```

---

## Environment Configuration

### Environment File (.env)

Create a `.env` file in the project root with these variables:

#### Database Configuration

```bash
# PostgreSQL Connection
POSTGRES_USER=pf9admin              # Database username
POSTGRES_PASSWORD=<secure-pwd>      # Min 32 chars, special chars recommended
POSTGRES_DB=pf9_mgmt                # Database name (can be custom)

# pgAdmin (Database Admin UI)
PGADMIN_EMAIL=admin@company.com     # Email for pgAdmin login
PGADMIN_PASSWORD=<secure-pwd>       # Min 16 chars
```

**Generating Secure Passwords**:
```bash
# macOS/Linux
openssl rand -base64 32    # Database password (32+ chars)
openssl rand -base64 16    # LDAP passwords (16+ chars)
openssl rand -base64 64    # JWT secret (64+ chars)

# Windows PowerShell
$bytes = New-Object Byte[] 32
$rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
$rng.GetBytes($bytes)
[Convert]::ToBase64String($bytes)
```

#### Platform9 / OpenStack Configuration

```bash
# Platform9 Controller Connection
PF9_AUTH_URL=https://pf9-controller.company.com/keystone/v3
# URL to your Platform9 controller, must include /keystone/v3

PF9_USERNAME=service-automation@company.com
# Service account username (recommended over personal account)

PF9_PASSWORD=<secure-service-password>
# Service account password

# Optional - Platform9 Project/Domain Settings
PF9_USER_DOMAIN=Default              # User domain in Platform9
PF9_PROJECT_NAME=service             # Project for service account
PF9_PROJECT_DOMAIN=Default           # Project domain
PF9_REGION_NAME=region-one           # Region name
```

**Finding Your Platform9 URL**:
1. Log into Platform9 UI
2. Sidebar → Account Settings → Region Information
3. Copy the Management Plane URL
4. Append `/keystone/v3`

#### LDAP Configuration

```bash
# LDAP Organization
LDAP_ORGANISATION=Your Company Name
# Display name for LDAP directory

LDAP_DOMAIN=company.local
# Domain name for LDAP DN (e.g., dc=company,dc=local)
# Use lowercase and avoid special characters

# LDAP Directory Structure (auto-generated by deployment.ps1 from LDAP_DOMAIN)
LDAP_BASE_DN=dc=company,dc=local
LDAP_USER_DN=ou=users,dc=company,dc=local
LDAP_GROUP_DN=ou=groups,dc=company,dc=local
# These must be set in .env — required for API auth and LDAP container healthcheck

# LDAP Admin Account (for directory management)
LDAP_ADMIN_PASSWORD=<secure-pwd>
# Password for cn=admin DN

LDAP_CONFIG_PASSWORD=<secure-pwd>
# Password for cn=config administrative access

# LDAP Read-Only Account
LDAP_READONLY_USER=true
# Create read-only user for queries

LDAP_READONLY_PASSWORD=<secure-pwd>
# Password for read-only account

# LDAP Ports
LDAP_PORT=389                        # Standard LDAP port
LDAP_SSL_PORT=636                    # LDAP over SSL/TLS
LDAP_ADMIN_PORT=8081                 # phpLDAPadmin web UI
```

**LDAP DN Structure** (auto-generated):
```
Base DN: dc=company,dc=local
Users: ou=users,dc=company,dc=local
Groups: ou=groups,dc=company,dc=local
Admin: cn=admin,dc=company,dc=local
```

#### JWT & Authentication

```bash
# JWT Secret Key (CRITICAL - keep secure and unique per deployment)
JWT_SECRET_KEY=<generated-64-char-key>
# Generate: openssl rand -base64 64
# NEVER share or commit this value

JWT_ALGORITHM=HS256                  # HMAC SHA256 (default, recommended)
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=480  # 8 hours
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30     # 30 days

# Authentication Control
ENABLE_AUTHENTICATION=true            # Enable LDAP authentication (true/false)
DEFAULT_ADMIN_USER=admin              # Default admin username
DEFAULT_ADMIN_PASSWORD=<secure-pwd>   # Default admin password (min 16 chars)
```

#### Monitoring Configuration

```bash
# Metrics Collection
PF9_HOSTS=10.0.1.10,10.0.1.11,10.0.1.12
# Comma-separated list of PF9 host IP addresses
# These are the hosts that run node_exporter and libvirt_exporter
# Format: 10.0.1.10,10.0.1.11,10.0.1.12

# Map host IPs to friendly hostnames for monitoring display (optional)
# PF9_HOST_MAP=10.0.1.10:host-01,10.0.1.11:host-02,10.0.1.12:host-03
# If unset, the collector will try the PF9 API or reverse DNS

METRICS_CACHE_TTL=60
# Cache time-to-live in seconds (default: 60)
# Metrics are cached for this duration
```

#### UI Configuration (Optional)

```bash
# Override API and monitoring service URLs for non-localhost deployments
# VITE_API_BASE=http://localhost:8000
# VITE_MONITORING_BASE=http://localhost:8001
```

**Finding PF9 Host IPs**:
1. Log into Platform9 UI
2. Sidebar → Infrastructure → Hosts
3. Note the IP addresses of your hosts

#### Snapshot Restore Configuration

```bash
# Enable the restore feature (disabled by default)
RESTORE_ENABLED=false
# Set to true to enable restore endpoints and UI tab

# Dry-run mode (plans only, no execution)
RESTORE_DRY_RUN=false
# When true, restore plans are created but never executed — jobs are marked DRY_RUN

# Volume cleanup on failure
RESTORE_CLEANUP_VOLUMES=false
# When true, volumes created during a failed restore are automatically deleted
# When false (default), orphaned volumes are left for manual inspection
```

> **Note**: Restore uses the same service user as the snapshot system (`SNAPSHOT_SERVICE_USER_EMAIL`, `SNAPSHOT_SERVICE_USER_PASSWORD`). Ensure the service user is configured if you plan to restore VMs across tenants.

See [RESTORE_GUIDE.md](RESTORE_GUIDE.md) for full feature documentation.

#### Optional Advanced Configuration

```bash
# CORS Origins (restrict cross-origin requests)
CORS_ORIGINS=http://localhost:5173,https://pf9-mgmt.company.com

# Database Connection Tuning
POSTGRES_INITDB_ARGS="-c max_connections=200 -c shared_buffers=256MB"

# Logging Level
LOG_LEVEL=INFO
# Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

# Structured Logging (JSON) for file output
JSON_LOGS=true
# true=JSON format, false=colored console

# Log File Location (inside containers)
LOG_FILE=/app/logs/pf9_api.log
# Logs are written to ./logs on the host via Docker volume
# Monitoring logs: /app/logs/pf9_monitoring.log
```

#### Snapshot Service User (Cross-Tenant Snapshots)

The snapshot service user enables creating snapshots in the correct tenant project (instead of the service domain). The user must **pre-exist in Platform9** — the system only manages role assignments.

```bash
# Service user identity
SNAPSHOT_SERVICE_USER_EMAIL=<your-snapshot-user@your-domain.com>
# The email address of the service user in Platform9 Keystone
# This user must already exist — the system does NOT create it

# Password Option A: Plaintext (simpler)
SNAPSHOT_SERVICE_USER_PASSWORD=<service-user-password>

# Password Option B: Fernet Encrypted (more secure)
SNAPSHOT_PASSWORD_KEY=<Fernet-encryption-key>
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

SNAPSHOT_USER_PASSWORD_ENCRYPTED=<encrypted-password>
# Generate: python -c "from cryptography.fernet import Fernet; f=Fernet(b'<key>'); print(f.encrypt(b'<password>').decode())"

# Optional: Disable service user (snapshots fall back to service domain)
SNAPSHOT_SERVICE_USER_DISABLED=false
```

**How It Works:**
1. Admin session lists volumes across all tenants (`all_tenants=1`)
2. For each tenant project with volumes, `ensure_service_user()` assigns admin role to the service user
3. System authenticates as service user scoped to that project
4. Snapshot is created in the correct tenant project

See [Snapshot Service User Guide](SNAPSHOT_SERVICE_USER.md) for full setup details.

### Environment File Security

**⚠️ CRITICAL SECURITY NOTICE**:

```bash
# 1. NEVER commit .env to version control
# Verify in .gitignore:
cat .gitignore | grep ".env"

# 2. Restrict file permissions
chmod 600 .env
# Only owner can read (rwx------)

# 3. Use .env.template for examples
# Keep .env.template with placeholder values:
cat > .env.template << 'EOF'
POSTGRES_USER=pf9admin
POSTGRES_PASSWORD=<GENERATE: openssl rand -base64 32>
POSTGRES_DB=pf9_mgmt
JWT_SECRET_KEY=<GENERATE: openssl rand -base64 64>
LDAP_ADMIN_PASSWORD=<GENERATE: openssl rand -base64 32>
LDAP_DOMAIN=company.local
LDAP_BASE_DN=dc=company,dc=local
PF9_AUTH_URL=https://your-pf9-cluster.platform9.com/keystone/v3
PF9_USERNAME=service@company.com
PF9_PASSWORD=<YOUR_SERVICE_PASSWORD>
DEFAULT_ADMIN_USER=admin
DEFAULT_ADMIN_PASSWORD=<GENERATE: openssl rand -base64 32>
RESTORE_ENABLED=false
EOF

# 4. Communicate .env securely (use encrypted channels)
# - Avoid email
# - Use 1Password, Vault, or similar
# - Use shared secrets management tools

# 5. Rotate sensitive values periodically
# Re-generate and update:
# - JWT_SECRET_KEY (every 90 days)
# - Database passwords (every 6 months)
# - LDAP passwords (every 6 months)
# - Platform9 service account (every year)
```

---

## First-Time Setup

### Access the Applications

After `docker-compose up -d` and services are healthy:

| Service | URL | Default Credentials | Purpose |
|---------|-----|-------------------|---------|
| **UI** | http://localhost:5173 | LDAP user | Management dashboard |
| **API Docs** | http://localhost:8000/docs | None (authenticated) | API documentation |
| **Monitoring** | http://localhost:8001/health | None | Health status |
| **pgAdmin** | http://localhost:8080 | $PGADMIN_EMAIL / $PGADMIN_PASSWORD | Database management |
| **LDAP Admin** | http://localhost:8081 | cn=admin / $LDAP_ADMIN_PASSWORD | LDAP user management |

### Admin User and Superadmin Permissions Are Automated

> **Note:** As of February 2026, running `deployment.ps1` will always ensure:
> - The admin user (from `.env`: `DEFAULT_ADMIN_USER`/`DEFAULT_ADMIN_PASSWORD`) is created in LDAP and in the `user_roles` table as `superadmin`.
> - The `superadmin` role always has a wildcard permission (`*`) in `role_permissions`.
> - You do **not** need to manually create the admin user or fix permissions in the database—this is enforced automatically on every deployment.

If you change the admin username/email in `.env`, simply re-run `deployment.ps1` and the system will update LDAP and database roles/permissions accordingly.

You can still use phpLDAPadmin (http://localhost:8081) for advanced LDAP management, but initial admin setup is now fully automated.

### Verify Connectivity

```bash
# 1. Test API connectivity
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy","version":"2026.02"}

# 2. Test Database
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "SELECT version();"

# 3. Test LDAP
docker-compose exec ldap ldapwhoami -x -D "cn=admin,dc=company,dc=local" -w ${LDAP_ADMIN_PASSWORD}

# 4. Test UI (in browser)
# Navigate to http://localhost:5173
# You should see the Landing Dashboard (default view, v1.1 feature)
# Shows real-time health metrics, compliance status, and 14 analytics cards
# Will prompt for login with LDAP credentials

# 5. Test Platform9 Connection
docker-compose logs pf9_api | grep -i "platform9\|openstack\|auth"
# Should show successful authentication attempts
```

### Configure Platform9 Connection

The system will auto-connect to Platform9 on startup. To verify:

```bash
# Check API logs for Platform9 connection
docker-compose logs pf9_api | tail -50

# Expected:
# INFO: Successfully authenticated to Platform9 at https://pf9-...
# INFO: Discovering infrastructure resources...
# INFO: Found X hypervisors, Y servers, Z volumes, ...

# If connection fails:
# - Verify PF9_AUTH_URL is correct
# - Verify PF9_USERNAME and PF9_PASSWORD are valid
# - Check network connectivity: curl https://your-pf9-url/keystone/v3
# - Verify firewall allows outbound HTTPS
```

---

## Verification & Testing

### Health Check Script

```bash
#!/bin/bash
# save as: health-check.sh
# run: bash health-check.sh

echo "=== Platform9 Management System Health Check ==="

# 1. Docker Services
echo -e "\n1. Checking Docker Services..."
docker-compose ps
STATUS=$(docker-compose ps -q | wc -l)
echo "✓ $STATUS services running"

# 2. API Endpoint
echo -e "\n2. Testing API Endpoint..."
API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health)
if [ "$API_STATUS" -eq 200 ]; then
    echo "✓ API is healthy (HTTP $API_STATUS)"
else
    echo "✗ API returned HTTP $API_STATUS"
fi

# 3. Database
echo -e "\n3. Testing Database..."
DB_TEST=$(docker-compose exec -T db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "SELECT COUNT(*) FROM information_schema.tables;" 2>/dev/null)
if [ ! -z "$DB_TEST" ]; then
    echo "✓ Database is accessible"
else
    echo "✗ Database connection failed"
fi

# 4. UI Frontend
echo -e "\n4. Testing UI Frontend..."
UI_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/)
if [ "$UI_STATUS" -eq 200 ]; then
    echo "✓ UI is accessible (HTTP $UI_STATUS)"
else
    echo "✗ UI returned HTTP $UI_STATUS"
fi

# 5. Monitoring Service
echo -e "\n5. Testing Monitoring Service..."
MON_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/health)
if [ "$MON_STATUS" -eq 200 ]; then
    echo "✓ Monitoring is healthy (HTTP $MON_STATUS)"
else
    echo "✗ Monitoring returned HTTP $MON_STATUS"
fi

# 6. LDAP
echo -e "\n6. Testing LDAP..."
LDAP_TEST=$(docker-compose exec -T ldap ldapsearch -x -H ldap://localhost \
  -D "cn=admin,${LDAP_BASE_DN}" -w "${LDAP_ADMIN_PASSWORD}" \
  -b "${LDAP_BASE_DN}" -s base 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "✓ LDAP is accessible"
else
    echo "✗ LDAP connection failed"
fi

# 7. Network Connectivity
echo -e "\n7. Testing Network Connectivity..."
ping -c 1 $(echo ${PF9_AUTH_URL} | sed 's|https://||' | sed 's|/.*||') > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Network to PF9 Controller is reachable"
else
    echo "✗ Cannot reach PF9 Controller"
fi

echo -e "\n=== Health Check Complete ==="
```

### Functional Testing

```bash
# 1. Test API Authentication
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-password"}'

# 2. Test Infrastructure Queries
curl http://localhost:8000/servers \
  -H "Authorization: Bearer <jwt-token>"

# 3. Test Platform9 Sync
curl http://localhost:8000/sync \
  -H "Authorization: Bearer <jwt-token>"

# 4. Test API Metrics & Logs (Admin/Superadmin)
curl http://localhost:8000/api/metrics \
  -H "Authorization: Bearer <jwt-token>"

curl "http://localhost:8000/api/logs?limit=50&log_file=all" \
  -H "Authorization: Bearer <jwt-token>"

# 5. Browser Testing
# Navigate to http://localhost:5173
# - Login with LDAP user
# - Verify dashboard loads
# - Check infrastructure tables populate
# - Verify monitoring metrics appear
# - Verify API Metrics and System Logs tabs (admin only)
```

### Performance Testing

```bash
# 1. Check container resource usage
docker stats

# 2. Database query performance
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} \
  -c "EXPLAIN ANALYZE SELECT * FROM servers LIMIT 100;"

# 3. API response time
time curl http://localhost:8000/servers \
  -H "Authorization: Bearer <token>" \
  > /dev/null

# 4. Memory usage
docker-compose exec pf9_api ps aux | grep python
```

---

## Post-Deployment Operations

### Daily Operations

#### Monitoring

```bash
# Check service health
docker-compose ps

# View logs
docker-compose logs --tail=50 -f

# Check database size
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} \
  -c "SELECT pg_size_pretty(pg_database_size('${POSTGRES_DB}'));"
```

#### Common Tasks

```bash
# Restart a service
docker-compose restart pf9_api

# View specific service logs
docker-compose logs pf9_api --tail=100

# Update infrastructure data
docker-compose exec pf9_api curl -X POST http://localhost:8000/sync

# Check LDAP users
docker-compose exec ldap ldapsearch -x -D "cn=admin,dc=company,dc=local" \
  -w ${LDAP_ADMIN_PASSWORD} -b "ou=users,dc=company,dc=local"
```

### Scheduled Maintenance

```bash
# Weekly: Clean up old logs
docker system prune -f
docker volume prune -f

# Weekly: Database maintenance
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "VACUUM ANALYZE;"

# Monthly: Update container images
docker-compose pull
docker-compose up -d

# Quarterly: Review and rotate credentials
# See: Environment Configuration → Rotating Secrets
```

### Stopping & Restarting

```bash
# Stop all services (preserves data)
docker-compose down

# Stop and remove volumes (DELETE DATA!)
docker-compose down -v

# Restart all services
docker-compose up -d

# Graceful shutdown with time for cleanup
docker-compose down --timeout 30
```

---

## Common Issues & Troubleshooting

### Issue 1: Services Won't Start

**Symptoms**: `docker-compose up -d` fails or services exit immediately

**Diagnosis**:
```bash
# Check service logs
docker-compose logs

# Check specific service
docker-compose logs pf9_api
```

**Solutions**:

| Error | Cause | Fix |
|-------|-------|-----|
| `docker: command not found` | Docker not installed | Install Docker (see Prerequisites) |
| `port already in use` | Port conflict | `docker-compose down` and check `netstat` |
| `ERROR: Service ... failed to build` | Build error | `docker-compose build --progress=plain` for details |
| `cannot connect to docker daemon` | Docker not running | Start Docker or check permissions |

### Issue 2: Database Connection Failed

**Symptoms**: API shows `SQLSTATE[28P01] authentication failed`

**Diagnosis**:
```bash
# Test database directly
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB}

# Check database logs
docker-compose logs db
```

**Solutions**:

```bash
# 1. Verify credentials in .env
grep POSTGRES_ .env

# 2. Reinitialize database
docker-compose down -v  # WARNING: Deletes data
docker-compose up -d db
docker-compose exec db psql -U ${POSTGRES_USER} < db/init.sql

# 3. Check database is healthy
docker-compose exec db pg_isready
```

### Issue 3: LDAP Authentication Fails

**Symptoms**: Cannot login; "Invalid credentials" error

**Diagnosis**:
```bash
# Test LDAP connection
docker-compose exec ldap ldapwhoami -x -D "cn=admin,dc=company,dc=local" \
  -w ${LDAP_ADMIN_PASSWORD}

# Check LDAP logs
docker-compose logs ldap
```

**Solutions**:

```bash
# 1. Verify LDAP is running
docker-compose ps ldap

# 2. Check LDAP admin password
# If forgotten, recreate container:
docker-compose down ldap
docker-compose up -d ldap

# 3. Create test user
docker-compose exec ldap ldapadd -x -D "cn=admin,dc=company,dc=local" \
  -w ${LDAP_ADMIN_PASSWORD} << 'EOF'
dn: uid=testuser,ou=users,dc=company,dc=local
objectClass: inetOrgPerson
uid: testuser
cn: Test User
sn: User
userPassword: password123
EOF
```

### Issue 4: Platform9 Connection Fails

**Symptoms**: API logs show `401 Unauthorized` from Platform9

**Diagnosis**:
```bash
# Test connectivity
curl -i ${PF9_AUTH_URL}/auth/tokens \
  -H "Content-Type: application/json" \
  -d '{"auth":{"identity":{"methods":["password"],"password":{"user":{"name":"'${PF9_USERNAME}'","domain":{"name":"'${PF9_USER_DOMAIN}'"},"password":"'${PF9_PASSWORD}'"}}}}}'

# Check logs
docker-compose logs pf9_api | grep -i "platform9\|keystone\|unauthorized"
```

**Solutions**:

```bash
# 1. Verify credentials
echo "URL: ${PF9_AUTH_URL}"
echo "Username: ${PF9_USERNAME}"
echo "Domain: ${PF9_USER_DOMAIN}"

# 2. Test credentials manually (without container)
# Use Postman or curl to verify authentication works

# 3. Check network connectivity
ping $(echo ${PF9_AUTH_URL} | sed 's|https://||' | sed 's|/.*||')

# 4. Verify firewall allows HTTPS outbound
# Contact network admin if blocked

# 5. Check clock skew (tokens have timestamp validation)
# Ensure system time is synchronized: ntptime or similar
```

### Issue 5: High Disk Usage

**Symptoms**: Disk full errors; services crash

**Diagnosis**:
```bash
# Check disk usage
df -h /

# Check Docker disk usage
docker system df

# Check database size
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} \
  -c "SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC;"
```

**Solutions**:

```bash
# 1. Clean up old data
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} \
  -c "DELETE FROM deletions_history WHERE timestamp < NOW() - INTERVAL '90 days';"

# 2. Vacuum database
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "VACUUM FULL;"

# 3. Clean Docker images/containers
docker system prune -a
docker volume prune

# 4. Increase storage (if on cloud)
# - AWS: Expand EBS volume
# - Azure: Expand managed disk
# - GCP: Expand persistent disk
```

### Issue 6: Slow Performance

**Symptoms**: UI is sluggish; API responses take >1000ms

**Diagnosis**:
```bash
# Check container resource usage
docker stats

# Check database connection count
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} \
  -c "SELECT count(*) FROM pg_stat_activity;"

# Check slow queries
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} \
  -c "SELECT query, calls, total_time, mean_time FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;"
```

**Solutions**:

```bash
# 1. Increase resource allocation
# Edit docker-compose.yml:
# services:
#   pf9_api:
#     deploy:
#       resources:
#         limits:
#           cpus: '2'
#           memory: 2G

# 2. Add database indexes (if not present)
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "\d servers"

# 3. Reduce monitoring collection frequency
# In .env: METRICS_CACHE_TTL=300 (5 minutes instead of 60s)

# 4. Scale horizontally
# Deploy multiple API containers with load balancer
```

### Getting Help

**Debugging steps**:
1. Collect logs: `docker-compose logs > debug.log`
2. Run health check: `bash health-check.sh > health.txt`
3. System info: `docker version > system.txt`
4. Error from logs (last 50 lines)
5. Reproduce error with exact steps

**File a GitHub issue with**:
- Error messages (full logs)
- System information (OS, Docker version)
- Steps to reproduce
- Environment (prod/dev, cloud/on-prem)

---

## Backup & Recovery

### Backup Strategy

```bash
# Full backup script
#!/bin/bash
BACKUP_DIR="/backups/pf9-management"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/pf9-backup-$DATE.tar.gz"

mkdir -p $BACKUP_DIR

# 1. Database dump
docker-compose exec -T db pg_dump -U ${POSTGRES_USER} ${POSTGRES_DB} > /tmp/pf9_db.sql

# 2. LDAP backup
docker-compose exec -T ldap slapcat > /tmp/pf9_ldap.ldif

# 3. Configuration
cp .env /tmp/pf9_env_backup.txt  # Keep secure!

# 4. Create archive
tar -czf $BACKUP_FILE \
  /tmp/pf9_db.sql \
  /tmp/pf9_ldap.ldif \
  /tmp/pf9_env_backup.txt

# 5. Upload to remote storage
# aws s3 cp $BACKUP_FILE s3://your-backup-bucket/
# gsutil cp $BACKUP_FILE gs://your-backup-bucket/

# 6. Cleanup
rm /tmp/pf9_*.{sql,ldif,txt}

echo "Backup completed: $BACKUP_FILE"
```

### Backup Scheduling

```bash
# cron job (Linux/macOS) - runs daily at 2 AM
0 2 * * * /path/to/backup.sh >> /var/log/pf9-backup.log 2>&1

# Windows Task Scheduler
# Use backup-win.ps1 (modify startup.ps1 for reference)
```

### Recovery Procedure

```bash
# 1. Extract backup
mkdir -p /tmp/restore
tar -xzf /backups/pf9-management/pf9-backup-YYYYMMDD_HHMMSS.tar.gz -C /tmp/restore/

# 2. Stop services
docker-compose down

# 3. Restore database
docker-compose up -d db
sleep 30  # Wait for DB to be ready
docker-compose exec -T db psql -U ${POSTGRES_USER} ${POSTGRES_DB} < /tmp/restore/pf9_db.sql

# 4. Restore LDAP (if needed)
docker-compose up -d ldap
sleep 30
docker-compose exec -T ldap slapadd -F /etc/ldap/slapd.d -l /tmp/restore/pf9_ldap.ldif

# 5. Verify restoration
docker-compose ps
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "SELECT COUNT(*) FROM servers;"

# 6. Restart all services
docker-compose up -d

# 7. Cleanup
rm -rf /tmp/restore
```

---

## Upgrade & Migration

### Upgrading the System

```bash
# 1. Backup current system
bash backup.sh

# 2. Pull latest code
git pull origin main

# 3. Review changelog
cat CHANGELOG.md

# 4. Stop current services
docker-compose down

# 5. Rebuild images
docker-compose build

# 6. Run migrations (if any)
docker-compose up -d db
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/init.sql

# 7. Start services
docker-compose up -d

# 8. Verify
docker-compose ps
docker-compose logs --tail=50
```

### Database Migrations

If schema changes are needed:

```bash
# 1. Review migration files
ls -la db/migrate_*.sql

# 2. Apply migrations (example: security groups — v1.7)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_security_groups.sql

# 3. Apply restore tables migration (v1.2+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_restore_tables.sql

# 4. Verify schema
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "\dt"
```

> **Note**: All migration scripts are idempotent (use `IF NOT EXISTS` / `ON CONFLICT DO NOTHING`). Safe to re-run.

---

## Production Hardening

### Pre-Production Checklist

- [ ] All default passwords changed
- [ ] JWT secret regenerated (min 64 chars)
- [ ] LDAP admin password secured
- [ ] SSL/TLS certificates installed
- [ ] Firewall rules configured
- [ ] Network isolation verified
- [ ] Backups automated and tested
- [ ] Monitoring & alerting configured
- [ ] Access control policies documented
- [ ] Incident response plan created

### Security Hardening

See [SECURITY.md](SECURITY.md) for detailed recommendations.

**Quick hardening checklist**:

```bash
# 1. Enable HTTPS
# Install reverse proxy (nginx)
# Configure SSL certificates
# Update CORS_ORIGINS

# 2. Restrict LDAP access
# Firewall port 389 to internal only
# Disable anonymous binds

# 3. Database security
# Restrict port 5432 to internal only
# Enable SSL connections
# Regular backups to offline storage

# 4. API security
# Implement rate limiting
# Add request logging
# Enable audit trail

# 5. Monitoring
# Set up Prometheus/Grafana
# Configure alerts for failures
# Log centralization (ELK/Loki)
```

---

## Summary

### Deployment Checklist

- [x] System requirements verified
- [x] Docker installed and configured
- [x] Repository cloned
- [x] Environment file (.env) created securely
- [x] Services built and started
- [x] Database initialized
- [x] LDAP users configured
- [x] Platform9 connection verified
- [x] Health checks passed
- [x] Backup strategy implemented
- [x] Security hardening applied
- [x] Documentation read and understood

### Next Steps

1. **First Data Collection**: System will sync Platform9 infrastructure on first run (5-10 min)
2. **User Management**: Create LDAP users and assign RBAC roles
3. **Monitoring**: Configure Prometheus/Grafana for ongoing monitoring
4. **Automation**: Set up snapshot policies and scheduled tasks
5. **Scaling**: Plan for production scale (multiple API instances, DB replication, etc.)

### Additional Resources

- [ARCHITECTURE.md](ARCHITECTURE.md) - System design details
- [ADMIN_GUIDE.md](ADMIN_GUIDE.md) - Operational administration
- [SECURITY.md](SECURITY.md) - Security configuration & hardening
- [KUBERNETES_MIGRATION_GUIDE.md](KUBERNETES_MIGRATION_GUIDE.md) - Kubernetes deployment
- [API Documentation](http://localhost:8000/docs) - Interactive API docs
- [GitHub Issues](https://github.com/yourusername/pf9-management/issues) - Bug reports & feature requests

---

**Last Updated**: February 2026  
**Maintained By**: Erez Rozenbaum & Community Contributors  
**License**: MIT
