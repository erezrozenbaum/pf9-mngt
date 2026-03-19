# Platform9 Management System - Deployment Guide

**Version**: 2.5
**Last Updated**: March 16, 2026  
**Status**: Production Ready  
**Deployment Platform**: Docker Compose (Windows, Linux, macOS)  
**Alternative**: See [KUBERNETES_MIGRATION_GUIDE.md](KUBERNETES_MIGRATION_GUIDE.md) for the Kubernetes design plan (not yet implemented)

---

## Table of Contents

1. [Quick Start (5 Minutes)](#quick-start-5-minutes)
2. [Deployment Architectures](#deployment-architectures)
3. [System Requirements](#system-requirements)
4. [Pre-Deployment Checklist](#pre-deployment-checklist)
5. [Detailed Installation](#detailed-installation)
6. [Environment Configuration](#environment-configuration)
7. [First-Time Setup](#first-time-setup)
8. [Verification & Testing](#verification--testing)
9. [Post-Deployment Operations](#post-deployment-operations)
10. [Common Issues & Troubleshooting](#common-issues--troubleshooting)
11. [Backup & Recovery](#backup--recovery)
12. [Upgrade, Rollback & Migration](#upgrade-rollback--migration)
13. [Production Hardening](#production-hardening)

---

## Quick Start (5 Minutes)

For the impatient developer:

```bash
# 1. Clone repository
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt

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

### Demo Mode Quick Start (No Platform9 Required)

Want to evaluate the portal without a live Platform9 cluster? Use **Demo Mode**:

```powershell
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt

# Option A — Let the deployment wizard guide you (choose "2 – Demo Mode"):
.\deployment.ps1

# Option B — Manual setup:
cp .env.example .env
# Set DEMO_MODE=true in .env, fill in database/LDAP/admin passwords
docker-compose up -d --build
pip install psycopg2-binary
python seed_demo_data.py --db-host localhost --db-port 5432 --db-name pf9_mgmt --db-user pf9 --db-pass <your-password>
docker-compose restart pf9_api
```

Demo mode pre-populates: 3 domains, 7 projects, 5 hypervisors, 35 VMs, ~50 volumes, ~100 snapshots, networks, subnets, users with RBAC, snapshot policies, compliance reports, drift events, metering pricing, runbooks, and activity log entries. A static metrics cache provides host + VM metrics without real collection.

---

## Deployment Architectures

Choose the topology that fits your environment.

### Option A — Single Host (Default, Recommended for Most Teams)

All core containers run on one host (14 always-on + `pf9_scheduler_worker` + optional `pf9_backup_worker` via `COMPOSE_PROFILES=backup`). nginx handles TLS termination. This is the current tested topology.

```text
                    Internet / VPN
                         │
                    ┌────┴────┐
                    │  nginx  │  :443 (TLS), :80 (redirect)
                    └────┬────┘
              ┌──────────┴───────────┐
         ┌────┴────┐           ┌─────┴─────┐
         │ pf9_api │           │  pf9_ui   │
         │  :8000  │           │   :5173   │
         └────┬────┘           └───────────┘
    ┌─────────┼──────────┬──────────┐
  pf9_db   pf9_ldap  pf9_redis  pf9_monitoring
 (internal) (internal) (internal)   (:8001)
    │
  Workers (snapshot, backup*, metering, search, notifications, scheduler)
  (* backup_worker only when COMPOSE_PROFILES=backup)
```

**When to use:** Single-tenant self-hosted deployments, evaluation, up to ~50 concurrent users.

**Ports exposed to host:**

| Port | Service | Exposed in Dev | Exposed in Production |
|------|---------|---------------|----------------------|
| 443 | nginx (HTTPS) | ✅ | ✅ |
| 80 | nginx (HTTP → redirect) | ✅ | ✅ |
| 8000 | API (direct) | ✅ | ❌ close before go-live |
| 5173 | UI (direct) | ✅ | ❌ close before go-live |
| 8001 | Monitoring (direct) | ✅ | ❌ close before go-live |
| 8080 | pgAdmin (dev only) | `--profile dev` | ❌ never |
| 8081 | phpLDAPadmin (dev only) | `--profile dev` | ❌ never |

> In production: close ports 8000, 5173, and 8001 on the host firewall. All traffic goes through nginx on 443.

---

### Option B — Separate DB Host

For teams that want the database on a separate, backed-up machine:

1. Run PostgreSQL on the dedicated host
2. Set `POSTGRES_HOST=<db-host-ip>` in `.env`
3. Remove the `pf9_db` service from your compose run: `docker-compose up -d --scale pf9_db=0`
4. Ensure `pg_hba.conf` on the DB host allows the app host's IP

**When to use:** When you already have a managed PostgreSQL instance or need data isolation.

---

### Option C — External LDAP / Active Directory

To use your corporate LDAP or Active Directory instead of the bundled OpenLDAP:

1. Set in `.env`:
   ```bash
   LDAP_URL=ldap://your-ad-server.company.com:389
   LDAP_BASE_DN=dc=company,dc=com
   LDAP_BIND_DN=cn=svc-pf9,ou=service-accounts,dc=company,dc=com
   LDAP_BIND_PASSWORD=<service-account-password>
   LDAP_USER_DN=ou=users,dc=company,dc=com
   ```
2. Remove or comment out the `pf9_ldap` and `phpldapadmin` services
3. Users must exist in AD/LDAP to authenticate; roles are still managed in the pf9-mngt database

**When to use:** Enterprise environments with existing Active Directory.

---

### TLS Configuration (nginx)

The bundled nginx container handles TLS termination. In production, replace the self-signed certificates with your own:

```bash
# Place your certificates on the host:
mkdir -p secrets/
cp your-cert.crt secrets/nginx-cert.crt
cp your-cert.key secrets/nginx-cert.key
```

The `docker-compose.yml` mounts `./secrets/` into the nginx container. The nginx configuration at `nginx/nginx.conf` expects:

```nginx
ssl_certificate     /etc/nginx/certs/nginx-cert.crt;
ssl_certificate_key /etc/nginx/certs/nginx-cert.key;
ssl_protocols       TLSv1.2 TLSv1.3;
ssl_ciphers         HIGH:!aNULL:!MD5;
```

For free certificates, use Let's Encrypt with Certbot on the host, then mount the certificate paths into the container volumes.

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
| SMTP (outbound) | 25/587 | SMTP/TLS | Outbound to mail server |

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
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt

# SSH (if you have SSH key configured)
git clone git@github.com:erezrozenbaum/pf9-mngt.git
cd pf9-mngt

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

# Expected output (default profile — pgAdmin and phpLDAPadmin excluded):
# NAME                      STATUS             PORTS
# pf9_nginx                 Up (healthy)       0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
# pf9_api                   Up (healthy)       0.0.0.0:8000->8000/tcp
# pf9_ui                    Up (healthy)       0.0.0.0:5173->5173/tcp
# pf9_monitoring            Up (healthy)       0.0.0.0:8001->8001/tcp
# pf9_db                    Up                 5432/tcp  (internal only, not host-exposed)
# pf9_ldap                  Up                 389/tcp   (internal only, not host-exposed)
# pf9_redis                 Up                 6379/tcp  (internal only)
# pf9_scheduler_worker      Up                 (runs host_metrics_collector + pf9_rvtools)
# pf9_notification_worker   Up                 (background worker, no port)
# pf9_metering_worker       Up                 (background worker, no port)
#
# With COMPOSE_PROFILES=backup also shows:
# pf9_backup_worker         Up                 (background worker, no port)
#
# To also start dev tools (pgAdmin + phpLDAPadmin):
#   docker compose --profile dev up -d
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
PF9_REGION_NAME=region-one           # Default OpenStack region name (see note below)

# Optional - Platform9 API Rate Limiter
# Prevents overwhelming the Platform9 API under heavy provisioning/migration load
PF9_RATE_LIMIT_ENABLED=false         # Set to true to enable token-bucket rate limiting
PF9_API_RATE_LIMIT=10                # Max requests per second (default 10)
```

> **Multi-Region Note**: `PF9_REGION_NAME` defines the *default* region for the initial setup. On first startup, `PF9_AUTH_URL` + `PF9_REGION_NAME` are automatically seeded into the `pf9_control_planes` and `pf9_regions` tables as the `default` entries. Additional control planes and regions can be added via the admin API/UI after deployment — no env-var changes or restarts needed. See [Admin Guide § 13](ADMIN_GUIDE.md) for details.

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

# Container Health Alerting
# The monitoring service watches all Docker containers via the Unix socket.
# When a container exits with a non-zero code or becomes (unhealthy), an
# email alert is sent to the address configured in Admin → Container Alerts.
WATCHDOG_INTERVAL=60      # How often to poll Docker Engine (seconds, default: 60)
WATCHDOG_COOLDOWN=1800    # Minimum seconds between repeat alerts per container (default: 1800)
# SMTP must also be configured (see Email Notification Configuration below)
# The Docker socket is mounted read-only: /var/run/docker.sock:/var/run/docker.sock:ro
# On Linux, ensure the monitoring container has access to the Docker socket group
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

#### Email Notification Configuration

```bash
# Enable email notifications (disabled by default)
SMTP_ENABLED=false

# SMTP server settings
SMTP_HOST=mail.example.com
SMTP_PORT=25                  # 25 for plain, 587 for STARTTLS, 465 for SSL
SMTP_USE_TLS=false            # Set to true for TLS-enabled servers

# SMTP authentication (leave empty for unauthenticated relay)
SMTP_USERNAME=
SMTP_PASSWORD=

# From address for notification emails
SMTP_FROM_ADDRESS=pf9-mgmt@pf9mgmt.local

# Worker behavior
NOTIFICATION_POLL_INTERVAL_SECONDS=120    # How often to check for new events
NOTIFICATION_DIGEST_ENABLED=true          # Enable daily digest emails
NOTIFICATION_DIGEST_HOUR_UTC=8            # Hour (UTC) to send daily digest
NOTIFICATION_LOOKBACK_SECONDS=300         # How far back to look for events each poll
HEALTH_ALERT_THRESHOLD=50                 # Tenant health score below this triggers alert
```

> **Note**: The notification worker runs as a separate container (`pf9_notification_worker`). When `SMTP_ENABLED=false`, the worker starts but does not send emails. Users can still configure preferences via the UI.

#### Slack / Teams Webhook Notifications (E3)

To receive notifications in Slack or Microsoft Teams, set one or both of the following variables in the `pf9_api` service environment:

```bash
# Slack Incoming Webhook URL
# Create one at: Slack app settings → Incoming Webhooks → Add New Webhook
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...

# Microsoft Teams Incoming Webhook URL
# Create one at: Teams channel → Connectors → Incoming Webhook → Configure
TEAMS_WEBHOOK_URL=https://<tenant>.webhook.office.com/webhookb2/...
```

When set, the `POST /notifications/test-webhook` endpoint can be used to verify connectivity. These variables are never exposed via the API — only whether the channel is configured or not is visible to users (`GET /notifications/webhook-config`).

#### vJailbreak Agent Integration (E1)

To enable wave execution via a vJailbreak agent:

```bash
# Base URL of the vJailbreak REST API (no trailing slash)
VJAILBREAK_API_URL=https://vjailbreak.example.com
```

When not set, `POST /api/migration/projects/{id}/waves/{wave_id}/execute` returns HTTP 503 with a human-readable configuration message. When set, the request is forwarded to `{VJAILBREAK_API_URL}/api/v1/migrations`.



#### Database Backup Configuration

Backup is opt-in via Docker Compose profiles. Set `COMPOSE_PROFILES=backup` to start
the `pf9_backup_worker` container and mount the NFS volume.

```bash
# Enable the backup worker (adds pf9_backup_worker + NFS volume to the stack)
COMPOSE_PROFILES=backup

# How often (seconds) the worker polls for pending manual/restore jobs (default: 30)
BACKUP_JOB_POLL_INTERVAL=30

# How often (seconds) the worker checks the schedule to fire automatic backups (default: 3600)
BACKUP_POLL_INTERVAL=3600

# NFS server IP address
NFS_BACKUP_SERVER=<your-nfs-server-ip>

# Exported path on the NFS server
NFS_BACKUP_DEVICE=/pf9-nfs

# NFS protocol version — use 3 for Docker Desktop (v4 not supported in lightweight kernel)
NFS_VERSION=3
```

> **Note**: The backup worker (`pf9_backup_worker`) is based on PostgreSQL 16 (`pg_dump`/`pg_restore` + `ldapsearch`/`ldapadd`) and writes compressed backups to the NFS mount at `/backups` inside the container. Configure schedule, retention, and LDAP backup via the 💾 Backup tab in the UI. See [BACKUP_GUIDE.md](BACKUP_GUIDE.md) for full setup and troubleshooting.

#### Metering Configuration

```bash
# Enable/disable operational metering
METERING_ENABLED=true

# Collection interval in minutes (default: 15)
METERING_POLL_INTERVAL=15

# Data retention in days (default: 90)
METERING_RETENTION_DAYS=90
```

> **Note**: The metering worker runs as a separate container (`pf9_metering_worker`). It collects resource usage, snapshot, restore, API usage, and efficiency metrics from the monitoring service, API, and database. vCPU data is resolved from the flavors table. Configure cost model via the unified multi-category pricing system (flavors auto-synced from system, storage/snapshot/restore/volume/network pricing with hourly + monthly rates). Toggle metering via the 📊 Metering tab in the UI (superadmin only). When `METERING_ENABLED=false`, the worker starts but does not collect data.

#### Optional Advanced Configuration

```bash
# CORS Origins (restrict cross-origin requests)
CORS_ORIGINS=http://localhost:5173,https://pf9-mgmt.company.com

# Database Connection Pool (per worker process)
DB_POOL_MIN_CONN=2            # Minimum connections per worker (default: 2)
DB_POOL_MAX_CONN=10           # Maximum connections per worker (default: 10)
# With 4 Gunicorn workers: max 40 total connections (PostgreSQL default max: 100)

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

#### VM Provisioning Service User (`provisionsrv`)

The VM provisioning service user enables creating volumes and virtual machines in the correct tenant project with a properly-scoped OpenStack token. Unlike `snapshotsrv`, this user is a **native Keystone user (NOT in LDAP)** — it is completely invisible to tenant customers in the management UI.

**One-time setup:**

```bash
# Step 1 — Add the user credentials to .env
PROVISION_SERVICE_USER_EMAIL=provisionsrv@yourdomain.com
PROVISION_SERVICE_USER_DOMAIN=Default

# Generate Fernet encryption key
PROVISION_PASSWORD_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Encrypt the user's password
PROVISION_USER_PASSWORD_ENCRYPTED=$(python3 -c "
from cryptography.fernet import Fernet
print(Fernet(b'<YOUR_KEY>').encrypt(b'<PROVISIONSRV_PASSWORD>').decode())
")

# Step 2 — Create the user in Platform9 Keystone (run after deploying containers)
docker exec pf9_api python3 /app/setup_provision_user.py
```

**How It Works:**
1. Before every provisioning execution, `ensure_provisioner_in_project()` idempotently grants `member` role to `provisionsrv` in the target tenant project
2. `get_provisioner_client()` authenticates as `provisionsrv` scoped to that project → Keystone returns a project-scoped token
3. All Nova/Neutron/Cinder API calls use this scoped token → resources are created in (and visible within) the correct tenant project
4. Role assignments are cached in-process — no repeated Keystone calls per VM within a batch

**Windows Image Glance Properties (v1.44.2):**  
When a Windows OS is detected, the admin client automatically patches the Glance image before creating the boot volume:
```
os_type        = windows
hw_disk_bus    = scsi
hw_scsi_model  = virtio-scsi
hw_firmware_type = bios
```
This ensures Nova creates the VM with the correct virtual hardware regardless of how the image was originally uploaded. The patch is idempotent — re-running on an already-patched image is safe.

> **Note**: The `provisionsrv` user must **not** be an LDAP-managed user (do not add it in OpenLDAP). Keeping it Keystone-native ensures it never appears in tenant-facing user lists or is accidentally included in exports.

#### Platform9 DU Super-Admin Fallback (`PF9_OS_ADMIN_*`) — Optional

Certain operations — such as deleting provider/external networks whose owning project has been removed from Keystone — require a Platform9 DU-level administrator token that is outside the scope of a regular `admin`-role OpenStack user. You can supply these credentials as a fallback:

```bash
# Optional — Platform9 DU super-admin credentials
# Required only for operations that normal admin/service tokens cannot perform
# (e.g. deleting provider external networks left behind after tenant removal)
PF9_OS_ADMIN_USER=admin@yourdomain.com
PF9_OS_ADMIN_PASSWORD=your-du-admin-password
PF9_OS_ADMIN_PROJECT=admin          # The DU admin project name (usually 'admin' or 'service')
PF9_OS_ADMIN_DOMAIN=Default
```

**How it is used:**
- `get_privileged_token()` tries this fallback when `provisionsrv`'s role-grant fails with Keystone 404 (e.g. the target project was already deleted)
- The credentials are never stored; a short-lived token is obtained per-request
- Leave all four vars empty to disable the fallback (default behaviour is unchanged)

**Finding the right credentials:** The DU super-admin is the account used to initially provision the Platform9 region. Contact the person who set up the region or your Platform9 account team. You can verify the credentials work with:

```powershell
docker exec pf9_api python3 -c "
import requests, os
base = os.environ['PLATFORM9_URL']
body = {'auth':{'identity':{'methods':['password'],'password':{'user':{'name':'YOUR_ADMIN_EMAIL','domain':{'name':'Default'},'password':'YOUR_ADMIN_PW'}}},'scope':{'project':{'name':'admin','domain':{'name':'Default'}}}}}
r = requests.post(base+'/keystone/v3/auth/tokens', json=body, timeout=15)
print(r.status_code)  # 201 = success
"
```

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
| **Notification Worker** | (no web UI) | N/A | Check: `docker logs pf9_notification_worker` |
| **Backup Worker** | (no web UI) | N/A | Check: `docker logs pf9_backup_worker` |

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

# 6. Notification Worker
echo -e "\n6. Testing Notification Worker..."
NOTIF_STATUS=$(docker inspect --format '{{.State.Status}}' pf9_notification_worker 2>/dev/null)
if [ "$NOTIF_STATUS" = "running" ]; then
    echo "✓ Notification worker is running"
else
    echo "⚠ Notification worker status: $NOTIF_STATUS (non-critical)"
fi

# 7. LDAP
echo -e "\n7. Testing LDAP..."
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
# For production (pulls pre-built images from ghcr.io; set PF9_IMAGE_TAG in .env first):
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# For dev/local builds:
# docker-compose pull && docker-compose up -d

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
userPassword: REDACTED_PASSWORD
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

### Automated Backups (Recommended)

The platform includes a built-in **Backup Worker** container (`pf9_backup_worker`) that
automates database **and** LDAP backups to NFS storage.

**Enable it:**
1. Set `COMPOSE_PROFILES=backup` in `.env`
2. Set `NFS_BACKUP_SERVER`, `NFS_BACKUP_DEVICE`, `NFS_VERSION=3` in `.env`
3. Run `./startup.ps1` — the worker starts automatically, NFS is pre-flight checked

**Configure via the UI:**
1. Go to 💾 **Backup & Restore** → **Settings**
2. Toggle **Automated Backups** on, set schedule (daily/weekly) and UTC time
3. Optionally enable **LDAP Scheduled Backup** to export directory entries as `.ldif.gz`
4. Set **Retention Policy** (max count + max age in days)

**Manual trigger:**
Click **🚀 Database Backup** or **📁 LDAP Backup** on the **Status** sub-tab.

**Restore:**
On the **History** sub-tab, click ♻️ Restore on any completed database backup (superadmin only).

See [BACKUP_GUIDE.md](BACKUP_GUIDE.md) for full NFS setup, Docker network configuration, and troubleshooting.

### Manual Ad-Hoc Backup

```bash
# Database dump (runs inside the db container)
docker exec pf9_db pg_dump -U ${POSTGRES_USER} ${POSTGRES_DB} | gzip > pf9_mgmt_$(date +%Y%m%d_%H%M%S).sql.gz

# LDAP export
docker exec pf9_ldap slapcat | gzip > pf9_ldap_$(date +%Y%m%d_%H%M%S).ldif.gz

# .env backup (keep secure, never commit)
cp .env .env.backup.$(date +%Y%m%d)
```

### Recovery Procedure

```bash
# 1. Stop services
docker-compose down

# 2. Restore database
docker-compose up -d db
Start-Sleep 15
Get-Content pf9_mgmt_YYYYMMDD_HHMMSS.sql.gz | docker exec -i pf9_db sh -c "gunzip | psql -U ${POSTGRES_USER} ${POSTGRES_DB}"

# 3. Restore LDAP (if needed)
docker-compose up -d ldap
Start-Sleep 10
Get-Content pf9_ldap_YYYYMMDD_HHMMSS.ldif.gz | docker exec -i pf9_ldap sh -c "gunzip | slapadd -F /etc/ldap/slapd.d"

# 4. Restart all services
./startup.ps1

# OR use the UI: Backup & Restore → History → ♻️ Restore (superadmin only)
```

---

## Upgrade, Rollback & Migration

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

# 5. Get the new images
# Production — update PF9_IMAGE_TAG in .env to the new version, then pull:
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
# Dev/local — rebuild from source:
# docker-compose build

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

# 4. Apply notifications migration (v1.11+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_notifications.sql

# 5. Apply LDAP backup + MFA migration (v1.14+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_ldap_backup_mfa.sql

# 6. Apply metering migration (v1.15+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_metering.sql

# 7. Apply departments & navigation visibility migration (v1.18+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_departments_navigation.sql

# 8. Apply runbooks migration (v1.21+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_runbooks.sql

# 9. Apply new runbooks migration (v1.25+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_new_runbooks.sql

# 10. Apply snapshot quota batching migration (v1.26+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_snapshot_quota_batching.sql

# 11. Apply migration planner (v1.28+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_migration_planner.sql

# 12. Apply migration schedule columns (v1.28.1+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_migration_schedule.sql

# 13. Apply migration planner usage metrics (v1.29+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_migration_usage.sql

# 14. Apply migration network infrastructure summary (v1.30+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_migration_networks.sql

# 15. Apply vCPU/memory usage percentages (v1.30+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_vm_usage_metrics.sql

# 16. Apply Phase 2 scoping, target mapping, overcommit profiles, gap analysis (v1.31+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_phase2_scoping.sql

# 17. Apply Phase 2.10 cohorts, VM status/mode, tenant priority, dependencies, network mappings (v1.31+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_cohorts_and_foundations.sql

# 18. Apply target name pre-seeding + confirmed flags (v1.31.1+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_target_preseeding.sql

# 19. Apply cohort schedule fields + VLAN backfill (v1.31.2+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_cohort_fixes.sql

# 20. Apply target domain description column (v1.31.7+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_descriptions.sql

# 21. Apply Phase 3 wave planning tables (v1.34.0+)
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_wave_planning.sql

# 22. Apply multi-network provisioning columns (v1.34.2+)
# Adds networks_config + networks_created JSONB to provisioning_jobs
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_provisioning_networks.sql

# 23. Apply Phase 4 data enrichment (v1.35.0+)
# Subnet detail columns, flavor_staging, image_requirements, tenant_users tables
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_phase4_preparation.sql

# 24. Apply PCD Approval Workflow tables (v1.36.2+)
# prep_approval_status/by/at columns on migration_projects + migration_prep_approvals table
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_prep_approval.sql

# 25. Apply Bulk Customer Onboarding tables (v1.38.0+)
# onboarding_batches + child tables for customers, projects, networks, users
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_onboarding_runbook.sql

# 26. Apply Onboarding v1.38.1 schema updates
# Additional columns for onboarding workflows and LDAP provisioning support
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_onboarding_v1381.sql

# 27. Apply Phase 5.0 Tech Fix Time tables (v1.42.0+)
# tech_fix_minutes_override on migration_vms + migration_fix_settings table
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_tech_fix.sql

# 28. Apply narrative fields for Migration Plan PDF/UI (v1.44.0+)
# Adds executive_summary + technical_notes TEXT columns to migration_projects
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_narrative_fields.sql

# 29. Apply runbook dept visibility + B1/B2/B3/C/C2 runbooks (v1.52.0+)
# Adds runbook_dept_visibility table; seeds runbooks 15-24:
#   15: org_usage_report, 16: quota_adjustment (B1)
#   17: vm_rightsizing, 18: capacity_forecast (B2)
#   19: disaster_recovery_drill, 20: tenant_offboarding (B3 — v1.56.0)
#   21: security_group_hardening, 22: network_isolation_audit,
#   23: image_lifecycle_audit (Phase C — v1.57.0)
#   24: hypervisor_maintenance_evacuate (Phase C2 — v1.57.0)
# with approval policies and dept visibility rows. Fully idempotent.
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_runbooks_dept_visibility.sql

# 30. Apply Support Ticket System tables (v1.58.0+)
# Creates 5 tables: support_tickets, ticket_comments, ticket_sla_policies,
# ticket_email_templates, ticket_sequence
# Seeds 17 SLA policies, 6 HTML email templates, RBAC rows, and
# the "Operations & Support" nav group with Tickets + My Queue items.
# Changes sort_order of the group to 9 (avoids conflict with migration_planning=8).
docker exec -i pf9_db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} < db/migrate_support_tickets.sql

# 31. Verify schema
docker-compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "\dt"
```

> **Note**: All migration scripts are idempotent (use `IF NOT EXISTS` / `ON CONFLICT DO NOTHING`). Safe to re-run.

---

### Rollback Procedure

Use this procedure if an upgrade causes issues and you need to revert to the previous version.

#### Step 1 — Stop the broken services

```bash
docker-compose down
```

#### Step 2 — Restore the database from backup

```bash
# Identify the backup taken before upgrade
ls -lt ./backups/     # or check the Backup tab in the UI

# Restore (replaces current database)
docker-compose up -d pf9_db
sleep 15
# Drop and recreate the database
docker-compose exec pf9_db psql -U ${POSTGRES_USER} -c "DROP DATABASE ${POSTGRES_DB};"
docker-compose exec pf9_db psql -U ${POSTGRES_USER} -c "CREATE DATABASE ${POSTGRES_DB};"
# Restore from backup
docker-compose exec -T pf9_db psql -U ${POSTGRES_USER} ${POSTGRES_DB} < ./backups/<backup-file>.sql
# Or for .sql.gz:
guzip -c ./backups/<backup-file>.sql.gz | docker-compose exec -T pf9_db psql -U ${POSTGRES_USER} ${POSTGRES_DB}
```

#### Step 3 — Check out the previous code version

```bash
# Find the previous tag
git log --oneline -10

# Check out the previous version
git checkout v1.44.1   # replace with your previous version tag
```

#### Step 4 — Rebuild and restart

```bash
docker-compose build
docker-compose up -d
```

#### Step 5 — Verify the rollback

```bash
curl http://localhost:8000/health
docker-compose ps
```

> **Important:** After rollback, database migrations from the failed upgrade will be present in the schema. They are additive and idempotent, so this is safe — the old code will ignore unknown columns. If this causes issues, restore the database from the pre-upgrade backup (Step 2).

---

## Ops Copilot Setup

The Ops Copilot is a three-tier AI assistant built into the portal. It works out of the box with no additional setup — the **built-in** tier uses pattern-matching intent detection powered by live SQL queries. For free-form questions, you can optionally connect a local or external LLM.

### Tier 1: Built-in (Default — Zero Setup)

Copilot works immediately after deployment. The built-in engine matches 40+ intent patterns (inventory counts, VM power states, capacity metrics, error VMs, drift events, networking, role assignments, etc.) and runs live SQL queries to answer. No API keys, no external services.

**Scoping**: Add "on tenant X", "for project X", or "on host Y" to any question to filter results. Examples:
- *"How many powered on VMs on tenant <your-tenant>?"*
- *"List VMs on host compute-01"*
- *"Quota for project engineering"*

**Help & Discovery**: Click ❓ in the Copilot header or "How to ask" in the footer to see all 40+ available questions organized into 8 categories with usage tips.

### Tier 2: Ollama (Local LLM)

For free-form questions using a local LLM that keeps all data on your network:

1. **Install Ollama** on the Docker host (or any reachable server):
   ```bash
   curl -fsSL https://ollama.ai/install.sh | sh
   ollama pull llama3
   ```

2. **Configure** in `.env`:
   ```dotenv
   COPILOT_BACKEND=ollama
   COPILOT_OLLAMA_URL=http://localhost:11434
   COPILOT_OLLAMA_MODEL=llama3
   ```
   > **Note**: Inside Docker, use `http://host.docker.internal:11434` to reach the host machine's Ollama. The `docker-compose.yml` already defaults to this.

3. **Or switch at runtime** via the UI: Click the ⚙️ gear icon in the Copilot panel → select "Ollama" → enter the URL → Save.

### Tier 3: External LLM (OpenAI / Anthropic)

For the most capable free-form answers using cloud LLMs:

1. **Configure** in `.env`:
   ```dotenv
   # For OpenAI:
   COPILOT_BACKEND=openai
   COPILOT_OPENAI_API_KEY=sk-...
   COPILOT_OPENAI_MODEL=gpt-4o-mini

   # For Anthropic:
   COPILOT_BACKEND=anthropic
   COPILOT_ANTHROPIC_API_KEY=sk-ant-...
   COPILOT_ANTHROPIC_MODEL=claude-sonnet-4-20250514
   ```

2. **Redaction** (recommended): `COPILOT_REDACT_SENSITIVE=true` (default) masks IPs, emails, and hostnames before sending infrastructure context to the external LLM.

3. **Or switch at runtime** via the UI Settings panel (admin only).

### Switching Backends at Runtime

Admins can switch backends without restarting:

1. Open the Copilot panel — click the labeled "🤖 Ask Copilot" pill button (bottom-right) or press `Ctrl+K`
2. Click the ⚙️ gear icon in the panel header
3. Select the desired backend
4. Enter any required configuration (URL, API key, model)
5. Click "Test Connection" to verify
6. Click "Save"

The setting is stored in the database (`copilot_config` table) and takes effect immediately.

### Security Notes

- **Built-in**: No data leaves your network. Read-only SQL queries.
- **Ollama**: No data leaves your network (assuming Ollama runs locally).
- **External LLM**: Infrastructure context is sent to the LLM provider. Enable `COPILOT_REDACT_SENSITIVE=true` to mask IPs/emails/hostnames. API keys are stored in the `copilot_config` database table.
- All Copilot endpoints require authentication via the standard RBAC middleware.
- Settings changes (backend, keys) are admin-only.

---

## Production Hardening

### Pre-Production Checklist

- [ ] All default passwords changed
- [ ] JWT secret regenerated (min 64 chars) and set as `JWT_SECRET_KEY` in `.env` (or Docker Secret)
- [ ] LDAP admin password secured
- [ ] SSL/TLS certificates installed (nginx reverse proxy)
- [ ] Firewall rules configured — only ports 80/443 exposed externally
- [ ] PostgreSQL port 5432 NOT exposed to host
- [ ] OpenLDAP port 389 NOT exposed to host
- [ ] pgAdmin and phpLDAPadmin disabled or restricted to localhost
- [ ] UI running production nginx build (not Vite dev server)
- [ ] API Gunicorn workers set to 4 for production load
- [ ] Healthchecks verified (pf9_api, pf9_ui, pf9_monitoring, ldap)
- [ ] Backups automated and tested
- [ ] Debug endpoints removed or gated
- [ ] Monitoring & alerting configured
- [ ] Access control policies documented
- [ ] Incident response plan created
- [ ] Docker Secrets configured (or `.env` permissions locked to `600`)
- [ ] Container log rotation verified (already set in `docker-compose.yml`)
- [ ] OpenLDAP image version pinned (already `osixia/openldap:1.5.0` in compose)

---

### Critical: Dev vs Production Docker Differences

The default `docker-compose.yml` is optimized for developer convenience. Before running in production, the following changes **must** be made:

#### 1. Disable dev-only services

pgAdmin and phpLDAPadmin are development tools. They should not be exposed in production:

```yaml
# In docker-compose.prod.yml (override file)
services:
  pgadmin:
    profiles: ["dev"]        # Only starts when: docker-compose --profile dev up

  phpldapadmin:
    profiles: ["dev"]
```

Or simply do not start them: `docker-compose up -d` without those services listed.

#### 2. Remove exposed database and LDAP ports

PostgreSQL and OpenLDAP ports are bound to the host in the default compose file. In production, these services are only needed by containers on the internal Docker network:

```yaml
# docker-compose.prod.yml
services:
  db:
    ports: []               # Remove "5432:5432" — internal only

  ldap:
    ports: []               # Remove "389:389" and "636:636" — internal only
```

#### 3. Use a production nginx build for the UI

For production deployments, build the UI as optimized static assets served by nginx rather than using the development server. Create `pf9-ui/Dockerfile.prod`:

```dockerfile
# pf9-ui/Dockerfile.prod — production build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

And a minimal `pf9-ui/nginx.conf`:
```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
    location /api/ {
        proxy_pass http://pf9_api:8000/;
    }
}
```

#### 4. Increase API workers for production

The current Gunicorn configuration uses 2 workers (reduced from 4 to resolve stuck-query issues at the time). For production with concurrent users, 4 workers is appropriate:

```yaml
# docker-compose.prod.yml
services:
  pf9_api:
    command: >
      gunicorn main:app
      -w 4
      -k uvicorn.workers.UvicornWorker
      --bind 0.0.0.0:8000
      --timeout 300
      --graceful-timeout 60
      --max-requests 1000
      --max-requests-jitter 50
```

`--max-requests 1000` recycles each worker after 1000 requests, preventing memory creep from long-running processes.

#### 5. Healthchecks (already configured)

`docker-compose.yml` already defines healthchecks for `pf9_api`, `pf9_ui`, `pf9_monitoring`, and `pf9_ldap`. No changes needed here.

To verify they are passing:

```bash
docker-compose ps
# STATUS column should show "Up (healthy)" for pf9_api, pf9_ui, pf9_monitoring, pf9_ldap
# If a service shows "Up (unhealthy)", inspect it:
docker inspect pf9_api | jq '.[0].State.Health'
```

#### 6. Add an nginx reverse proxy for HTTPS

Both the UI (port 5173) and API (port 8000) run over plain HTTP. In production, all traffic must go through HTTPS:

```yaml
# docker-compose.prod.yml
services:
  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/certs:/etc/nginx/certs:ro
    depends_on:
      - pf9_api
      - pf9_ui
    restart: unless-stopped
```

See [SECURITY.md](SECURITY.md) for the nginx TLS configuration.

#### 7. Use a production override file

Combine all changes into a single `docker-compose.prod.yml` and deploy with:

```bash
# Pull pre-built service images from ghcr.io (set PF9_IMAGE_TAG=v1.70.0 in .env to pin a version)
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull

# Start the stack
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The production overlay sets `image:` overrides for all nine custom services pointing to `ghcr.io/erezrozenbaum/pf9-mngt-<service>:${PF9_IMAGE_TAG:-latest}`. Set `PF9_IMAGE_TAG` in `.env` to pin a specific release and avoid accidental upgrades. Leave it unset (or set to `latest`) to always pull the most recent published image.

This keeps the base compose file intact for development while applying all production overrides cleanly.

#### 8. Docker Secrets (recommended for production credentials)

Environment variables are visible in `docker inspect` output, process listings, and tools that dump env at startup. Docker Secrets mount credentials as files inside the container and are never exposed in docker inspect.

The application reads secrets via `api/secret_helper.py`: it checks `/run/secrets/<name>` first and falls back to the environment variable if the file is absent or empty. This means **dev keeps working with `.env` unchanged** — you only need to populate the secret files on production hosts.

**Secret files and their env-var equivalents:**

| Secret file | Environment variable | Used by |
|---|---|---|
| `secrets/db_password` | `POSTGRES_PASSWORD` / `PF9_DB_PASSWORD` | Database connection |
| `secrets/ldap_admin_password` | `LDAP_ADMIN_PASSWORD` | LDAP admin operations |
| `secrets/pf9_password` | `PF9_PASSWORD` | Platform9 API authentication |
| `secrets/jwt_secret` | `JWT_SECRET_KEY` | JWT token signing |

**Production setup:**

```bash
# Populate the secret files (never commit these values)
echo -n "$(openssl rand -base64 32)" > secrets/db_password
echo -n "your-ldap-admin-password"  > secrets/ldap_admin_password
echo -n "your-pf9-service-password" > secrets/pf9_password
echo -n "$(openssl rand -base64 64)" > secrets/jwt_secret

# Lock permissions
chmod 600 secrets/db_password secrets/ldap_admin_password secrets/pf9_password secrets/jwt_secret
```

The `secrets/` directory ships with empty placeholder files. `.gitignore` excludes all secret files but tracks `secrets/README.md`. See [secrets/README.md](../secrets/README.md) for the full reference.

---

### Security Hardening

See [SECURITY.md](SECURITY.md) and [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md) for full recommendations.

```bash
# Key actions:
# 1. Populate secrets/ files (see Docker Secrets section above) OR set chmod 600 .env
# 2. Enable LDAP over TLS (LDAPS port 636) or use stunnel
# 3. Rate-limit /auth/login endpoint (slowapi is already imported)
# 4. Remove or gate debug endpoints in api/main.py (/simple-test, /test-users-db)
# 5. Ensure backups volume is encrypted at rest
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
- [GitHub Issues](https://github.com/erezrozenbaum/pf9-mngt/issues) - Bug reports & feature requests

---

**Last Updated**: March 16, 2026  
**Maintained By**: Erez Rozenbaum & Community Contributors  
**License**: MIT
