# Platform9 Management System - Quick Reference

## System Overview (February 2026)

### Comprehensive OpenStack Management Platform
The Platform9 Management System is a enterprise-grade infrastructure management solution providing:

#### Complete Resource Coverage (19+ Resource Types)
- **Compute**: Virtual Machines (Servers), Hypervisors, Flavors, Images
- **Storage**: Volumes, Snapshots, Volume Types, Bootable Volumes  
- **Network**: Networks, Subnets, Ports, Routers, Floating IPs, Security Groups & Rules
- **Identity**: Domains, Projects/Tenants, Users with comprehensive role management (100+ users across 28 domains)

#### Advanced User & Role Management
- **Multi-Domain User Collection**: Complete user visibility across all 28 domains (20 with active users)
- **Role Assignment Tracking**: Comprehensive role assignments with admin, member, and service roles
- **Activity Monitoring**: User last-seen timestamps, account status, and authentication tracking
- **Role Inference System**: Intelligent role assignment detection when API access is limited

#### Modern React UI Features (17 Comprehensive Tabs)
- **Dashboard Tab** (NEW ✨): Landing Dashboard with 14 real-time analytics endpoints
  - Health Summary, Snapshot SLA Compliance, Host Utilization, Recent Activity
  - Coverage Risks, Capacity Pressure, VM Hotspots, Tenant Risk Scores
  - Compliance Drift, Capacity Trends, Trendlines, Change Compliance
  - Tenant Risk Heatmap, Tenant Summary
  - Auto-refresh every 30 seconds, Dark/Light mode support
- **Infrastructure Tabs**: Servers, Volumes, Snapshots, Networks, Subnets, Ports, Floating IPs
- **Platform Tabs**: Domains, Projects, Flavors, Images, Hypervisors
- **Management Tabs**: Users (with role assignments), History (change tracking), Audit (compliance), Monitoring (real-time metrics)
- **History Tab Features**:
  - Filter by resource type, project, domain, and free-text search (name/ID/description)
  - Sortable columns: Time, Type, Resource, Project, Domain, Description (▲/▼)
  - Deletion record viewing with original resource type, reason, and raw state snapshot
  - Most frequently changed resources with direct history navigation
  - Configurable timeframe: 1 hour, 24 hours, 3 days, 1 week
- **Admin Tabs**: API Metrics, System Logs (Admin/Superadmin only)
- **Enhanced Capabilities**: Advanced filtering, sorting, pagination across all tabs with real-time data refresh

#### Advanced Snapshot Management
- **Cross-Tenant Snapshots**: Snapshots created in correct tenant projects via dedicated service user
- **Automated Snapshot Creation**: Policy-driven with daily/monthly schedules
- **Metadata-Driven Policies**: Volume-level configuration via OpenStack metadata
- **Multi-Policy Support**: Volumes support multiple concurrent policies (daily_5, monthly_1st, monthly_15th)
- **Compliance Monitoring**: SLA tracking and policy adherence reporting with tenant/domain aggregation
- **Policy Assignment Rules**: JSON-driven automatic assignment based on volume properties
- **Service User**: Configurable via `SNAPSHOT_SERVICE_USER_EMAIL` with per-project admin role assignment

#### Real-Time Infrastructure Monitoring
- **Host Metrics**: CPU, Memory, Storage from PF9 compute nodes via node_exporter (port 9388) ✅
- **VM Metrics**: Individual VM resource tracking via libvirt_exporter (port 9177) ❌ *[Requires PF9 Engineering]*
- **Automated Collection**: Windows Task Scheduler every 30 minutes
- **Cache-Based Storage**: Persistent metrics with container restart survival
- **Integrated Dashboard**: Real-time monitoring tab with auto-refresh in React UI

#### API Observability Endpoints
- **Public Metrics**: `GET http://localhost:8000/metrics` (Prometheus/Grafana)
- **Authenticated Metrics (UI)**: `GET http://localhost:8000/api/metrics`
- **Authenticated Logs (UI)**: `GET http://localhost:8000/api/logs`
  - Query params: `limit`, `level`, `source`, `log_file`
  - Log sources: `pf9_api`, `pf9_monitoring` (use `log_file=all` to aggregate)
- **RBAC**: `api_metrics:read`, `system_logs:read` (Admin/Superadmin)

#### Enterprise Features
- **Single-Command Deployment**: Complete automation via `startup.ps1` or `deployment.ps1`
- **Hybrid Architecture**: Scripts work standalone or with full web services
- **RVTools Compatibility**: Excel/CSV exports with delta tracking and customer data masking
- **Modern React UI**: TypeScript-based with Vite build system and theme support
- **REST API**: FastAPI with OpenAPI docs + dedicated monitoring service
- **Database Integration**: PostgreSQL 16 with 19+ tables for historical tracking
- **Administrative Operations**: Create/delete flavors and networks directly from UI

---

## Initial Setup (Required)

### Environment Configuration
```bash
# 1. Copy template and configure credentials  
cp .env.template .env

# 2. Edit .env with your actual credentials (CRITICAL: NO QUOTES around values)
# CORRECT format:
PF9_USERNAME=your-service-account@company.com
PF9_PASSWORD=your-secure-password
PF9_AUTH_URL=https://your-cluster.platform9.com/keystone/v3
PF9_USER_DOMAIN=Default
PF9_PROJECT_NAME=service
PF9_PROJECT_DOMAIN=Default
PF9_REGION_NAME=region-one

# Database credentials (for Docker services)
POSTGRES_USER=pf9
POSTGRES_PASSWORD=change-this-secure-password
POSTGRES_DB=pf9_mgmt
```

### Complete Platform Deployment
```powershell
# Clone repository
git clone <repository-url>
cd pf9-mngt

# Configure .env file (see above)

# One-command complete setup
.\startup.ps1

# Verify services are running
docker-compose ps

# Access services:
# - Main UI: http://localhost:5173
# - API + Docs: http://localhost:8000/docs  
# - Monitoring API: http://localhost:8001
# - Database Admin: http://localhost:8080
```

---

## Core Operations

### Infrastructure Discovery & Export
```bash
# Full RVTools-style export (Excel + CSV)
python pf9_rvtools.py

# Export with customer data masking
python pf9_rvtools.py --mask-customer-data

# Database mode (stores in PostgreSQL)
PF9_ENABLE_DB=1 python pf9_rvtools.py

# Output files:
# - Platform9_RVTools_2026-02-02T10-30-00Z.xlsx
# - CSV_exports/
```

### Snapshot Management
```bash
# Automatic policy assignment based on rules
python snapshots/p9_snapshot_policy_assign.py

# Run automated snapshots (respects metadata policies)
# Uses service user for cross-tenant snapshot creation
python snapshots/p9_auto_snapshots.py

# Dry-run mode (safe testing)
python snapshots/p9_auto_snapshots.py --dry-run

# Generate comprehensive compliance report
python snapshots/p9_snapshot_compliance_report.py

# Input: Platform9_RVTools_*.xlsx
# Output: Platform9_Snapshot_Compliance_Report_*.xlsx
```

### Snapshot Service User
```bash
# Verify service user password configuration
python -c "from snapshots.snapshot_service_user import get_service_user_password, SERVICE_USER_EMAIL; pw=get_service_user_password(); print(f'{SERVICE_USER_EMAIL}: OK (len={len(pw)})')"

# Check service user activity in snapshot worker logs
docker logs pf9_snapshot_worker 2>&1 | grep "SERVICE_USER"

# Disable cross-tenant mode (fall back to admin session)
# Set in .env: SNAPSHOT_SERVICE_USER_DISABLED=true
```

### Real-Time Monitoring
```powershell
# Setup automated collection (Windows Task Scheduler)
.\startup.ps1  # Includes monitoring setup

# Manual metrics collection
python host_metrics_collector.py

# Check scheduled task
schtasks /query /tn "PF9 Metrics Collection"

# View cached metrics
Get-Content metrics_cache.json | ConvertFrom-Json
```

---

## API Operations

### Service Health & Status
```bash
# Main API health
curl http://localhost:8000/health

# Monitoring service health  
curl http://localhost:8001/health

# API documentation
open http://localhost:8000/docs
```

### Resource Queries
```bash
# List all domains
curl http://localhost:8000/domains

# List projects/tenants
curl http://localhost:8000/tenants

# Get users with role information
curl http://localhost:8000/users

# Get specific user details
curl http://localhost:8000/users/{user_id}

# List users with filtering and pagination
curl "http://localhost:8000/users?page=1&page_size=20&sort_by=name&domain_id=default"

# Get volumes with metadata
curl http://localhost:8000/volumes-with-metadata

# Paginated servers with filtering
curl "http://localhost:8000/servers?tenant_filter=production&limit=50&offset=0"
```

### Administrative Operations
```bash
# Create new flavor
curl -X POST http://localhost:8000/flavors \
  -H "Content-Type: application/json" \
  -d '{"name":"m1.custom","vcpus":2,"ram":4096,"disk":40}'

# Delete flavor
curl -X DELETE http://localhost:8000/flavors/flavor-id-here

# Create network
curl -X POST http://localhost:8000/networks \
  -H "Content-Type: application/json" \
  -d '{"name":"custom-network","tenant_id":"tenant-id"}'

# Delete network
curl -X DELETE http://localhost:8000/networks/network-id-here
```

### Monitoring Data
```bash
# Get host metrics
curl http://localhost:8001/metrics/hosts

# Get VM metrics (when libvirt is fixed)
curl http://localhost:8001/metrics/vms

# Trigger auto-setup check
curl http://localhost:8001/auto-setup
```

# INCORRECT format (don't use):
# PF9_USERNAME="your-service-account@company.com"

# 3. Verify .env file is ignored by git
git status  # Should not show .env file
```

### Standalone Script Execution (No Docker Required)
```bash
# Scripts automatically load .env and work independently
cd C:\pf9-mngt

# Data collection (generates Excel reports)
python pf9_rvtools.py

# Snapshot automation
python snapshots/p9_auto_snapshots.py --policy daily_5 --dry-run

# Compliance reporting
python snapshots/p9_snapshot_compliance_report.py --input latest_export.xlsx
```

### Windows Task Scheduler Setup
```
Program/script: C:\Python313\python.exe
Add arguments: C:\pf9-mngt\pf9_rvtools.py
Start in: C:\pf9-mngt
```

### Complete One-Command Setup (Recommended)
```powershell
# 1. Configure environment (one-time setup)
cp .env.template .env
# Edit .env with your Platform9 credentials

# 2. Single command startup (includes monitoring automation)
.\startup.ps1

# System will automatically:
# - Collect initial metrics from PF9 hosts
# - Setup scheduled metrics collection (every 2 minutes)
# - Start all Docker services (DB, API, UI, Monitoring)
# - Verify all services are running
```

### Alternative: Manual Docker Setup
```powershell
# Traditional Docker setup
docker-compose up -d

# Note: Requires manual metrics collection:
python host_metrics_collector.py --once
```

### Stop Everything
```powershell
.\startup.ps1 -StopOnly
# Stops all services and removes scheduled tasks
```

### Docker Environment Variables
**Docker Compose automatically loads `.env` file** - no additional steps needed.

**To restart and pick up new environment variables**:
```bash
# Stop services
docker-compose down

# Start with new environment (automatically reads .env)
docker-compose up -d

# Verify environment variables are loaded
docker exec pf9_api printenv | grep PF9_
```

## Service URLs
- **Management UI**: http://localhost:5173 (Primary interface)
- **API Backend**: http://localhost:8000  
- **API Documentation**: http://localhost:8000/docs (OpenStack API gateway)
- **Monitoring API**: http://localhost:8001 (Real-time metrics service)
- **pgAdmin**: http://localhost:8080
- **Database Direct**: localhost:5432

## Essential Commands

### Service Management
```bash
# Start all services
docker-compose up -d

# Stop all services  
docker-compose down

# Restart specific service
docker-compose restart pf9_api

# View real-time logs
docker-compose logs -f pf9_api

# Check service status
docker-compose ps

# Rebuild services after code changes
docker-compose build pf9_api pf9_ui
docker-compose up -d
```

### Health Checks & Monitoring
```bash
# API health check
curl http://localhost:8000/health

# Database connectivity
docker exec pf9_db pg_isready -U pf9

# Container resource usage
docker stats --no-stream

# Check API endpoints
curl -s http://localhost:8000/docs | grep -o '"paths".*' | head -20

# Test database connection from API
curl "http://localhost:8000/domains"
```

### Database Operations
```bash
# Access database shell
docker exec -it pf9_db psql -U pf9 -d pf9_mgmt

# Quick database statistics
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "
  SELECT schemaname,tablename,n_tup_ins,n_tup_upd,n_tup_del 
  FROM pg_stat_user_tables ORDER BY n_tup_ins DESC;"

# Check inventory run history
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "
  SELECT id,status,source,started_at,finished_at,notes 
  FROM inventory_runs ORDER BY started_at DESC LIMIT 10;"

# Database backup with compression
docker exec pf9_db pg_dump -U pf9 pf9_mgmt | gzip > "backup_$(date +%Y%m%d_%H%M).sql.gz"

# Restore database
zcat backup_file.sql.gz | docker exec -i pf9_db psql -U pf9 pf9_mgmt
```

### Data Collection Scripts
```bash
# Full inventory collection (RVTools export)
python pf9_rvtools.py

# Inventory with customer data masking
python pf9_rvtools.py --mask-customer-data

# Inventory with debug output
python pf9_rvtools.py --debug

# Export to specific directory
python pf9_rvtools.py --output-dir /custom/path

# Dry run (no database writes)
python pf9_rvtools.py --dry-run
```

### Snapshot Automation
```bash
# Run daily snapshots (dry run first)
python snapshots/p9_auto_snapshots.py --policy daily_5 --dry-run

# Execute daily snapshots (max 200 new)
python snapshots/p9_auto_snapshots.py --policy daily_5 --max-new 200

# Monthly snapshots (1st of month)
python snapshots/p9_auto_snapshots.py --policy monthly_1st

# Monthly snapshots (15th of month)
python snapshots/p9_auto_snapshots.py --policy monthly_15th

# Check snapshot policies on volumes
python snapshots/p9_snapshot_policy_assign.py --config snapshots/snapshot_policy_rules.json --dry-run

# Apply snapshot policies
python snapshots/p9_snapshot_policy_assign.py --config snapshots/snapshot_policy_rules.json
```

### Compliance Reporting
```bash
# Generate compliance report from latest RVTools export
python p9_snapshot_compliance_report.py \
  --input /path/to/pf9_rvtools_export.xlsx \
  --output compliance_report.xlsx

# Compliance report with custom SLA days
python p9_snapshot_compliance_report.py \
  --input export.xlsx --output report.xlsx --sla-days 3
```

### Real-Time Monitoring
```bash
# Manual metrics collection (for testing)
python host_metrics_collector.py --once

# Continuous collection (automated via startup.ps1)
python host_metrics_collector.py

# Check host metrics via API
curl http://localhost:8001/metrics/hosts

# Get monitoring summary
curl http://localhost:8001/metrics/summary

# Verify PF9 host connectivity
curl http://203.0.113.10:9388/metrics
curl http://203.0.113.11:9388/metrics

# Check scheduled metrics task
schtasks /query /tn "PF9 Metrics Collection"
```

## Common Issues & Solutions

### API Returns 500 Errors
```bash
# Check API logs
docker-compose logs pf9_api | tail -50

# Restart API service
docker-compose restart pf9_api

# Check database connectivity
docker exec pf9_api psql -h db -U pf9 -d pf9_mgmt -c "SELECT 1;"
```

### UI Not Loading
```bash
# Check UI container
docker-compose logs pf9_ui

# Restart UI service
docker-compose restart pf9_ui

# Check proxy configuration
curl -I http://localhost:5173/api/health
```

### Database Connection Issues
```bash
# Restart database
docker-compose restart pf9_db

# Check database logs
docker-compose logs pf9_db

# Verify database is running
docker exec pf9_db pg_isready
```

### Platform9 Authentication Errors
```bash
# Check API logs for auth errors
docker-compose logs pf9_api | grep -i auth

# Test Platform9 connectivity
curl -k https://your-platform9-cluster.com/keystone/v3

# Verify environment variables
docker-compose config
```

### Monitoring Service Issues
```bash
# Check monitoring service logs
docker-compose logs pf9_monitoring

# Restart monitoring service
docker-compose restart pf9_monitoring

# Test monitoring API health
curl http://localhost:8001/health

# Check metrics collection manually
python host_metrics_collector.py --once

# Verify scheduled task is running
schtasks /query /tn "PF9 Metrics Collection" /v

# Check if PF9 hosts are accessible
curl http://203.0.113.10:9388/metrics | head -20
```

### Data Synchronization Issues
```bash
# Force data sync (removes old records)
python pf9_rvtools.py

# Clean up old snapshots specifically
python cleanup_snapshots.py

# Check database record counts
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM snapshots;"
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM servers;"

# Verify metrics cache file exists
ls -la metrics_cache.json
cat metrics_cache.json | head -50
```

## Security Quick Checks

### ⚠️ Critical Security Issues
```bash
# Check for hardcoded credentials
grep -r "password.*=" . --exclude-dir=.git

# Verify CORS configuration
curl -H "Origin: http://malicious-site.com" -X OPTIONS http://localhost:8000/servers

# Check for SQL injection vulnerabilities
grep -r "SELECT.*%" api/ --include="*.py"
```

## API Quick Reference

### Common Endpoints
```bash
# Get server list
curl "http://localhost:8000/servers?page=1&page_size=10"

# Get domain list
curl "http://localhost:8000/domains"

# Get tenant list  
curl "http://localhost:8000/tenants"

# Create flavor (admin)
curl -X POST "http://localhost:8000/admin/flavors" \
  -H "Content-Type: application/json" \
  -d '{"name":"test","vcpus":1,"ram_mb":1024,"disk_gb":10}'

# Monitoring API endpoints
curl "http://localhost:8001/metrics/hosts"       # Host resource metrics
curl "http://localhost:8001/metrics/summary"     # Summary statistics
curl "http://localhost:8001/metrics/vms"         # VM metrics (future)
curl "http://localhost:8001/metrics/alerts"      # Active alerts (future)
```

### Query Parameters
- `page` - Page number (default: 1)
- `page_size` - Items per page (max: 500)
- `sort_by` - Sort field name
- `sort_dir` - asc/desc (default: asc)
- `domain_name` - Filter by domain
- `tenant_id` - Filter by tenant ID

## Monitoring Commands

### Resource Usage
```bash
# Container resource usage
docker stats --no-stream

# Disk usage
docker system df

# Database size
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "
  SELECT pg_size_pretty(pg_database_size('pf9_mgmt'));"
```

### Performance Monitoring
```bash
# Database connections
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "
  SELECT count(*) FROM pg_stat_activity;"

# Slow queries
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "
  SELECT query, mean_time FROM pg_stat_statements 
  ORDER BY mean_time DESC LIMIT 10;"
```

## Backup & Recovery

### Quick Backup
```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)

# Database backup
docker exec pf9_db pg_dump -U pf9 pf9_mgmt | gzip > "backup_${DATE}.sql.gz"

# Volume backup  
docker run --rm \
  -v pf9-mngt_pgdata:/data \
  -v $(pwd):/backup alpine \
  tar czf /backup/volumes_${DATE}.tar.gz /data
```

### Quick Recovery
```bash
# Restore database (stop services first)
docker-compose down
docker-compose up -d pf9_db
sleep 10

# Restore from backup
gunzip -c backup_YYYYMMDD_HHMMSS.sql.gz | \
  docker exec -i pf9_db psql -U pf9 -d pf9_mgmt

# Start all services
docker-compose up -d
```

## Configuration Files

### Key Configuration Locations
- [`docker-compose.yml`](../docker-compose.yml) - Service orchestration with monitoring
- [`api/main.py`](../api/main.py) - API configuration
- [`pf9-ui/vite.config.ts`](../pf9-ui/vite.config.ts) - UI configuration
- [`db/init.sql`](../db/init.sql) - Database schema
- [`p9_common.py`](../p9_common.py) - Platform9 connection settings
- [`startup.ps1`](../startup.ps1) - Complete automation and service management
- [`deployment.ps1`](../deployment.ps1) - Deployment automation with validation and health checks
- [`host_metrics_collector.py`](../host_metrics_collector.py) - Real-time metrics collection
- [`cleanup_snapshots.py`](../cleanup_snapshots.py) - Database cleanup utilities

### New Monitoring Components
- [`monitoring/main.py`](../monitoring/main.py) - FastAPI monitoring service
- [`monitoring/models.py`](../monitoring/models.py) - Pydantic data models
- [`monitoring/prometheus_client.py`](../monitoring/prometheus_client.py) - Prometheus integration
- [`monitoring/Dockerfile`](../monitoring/Dockerfile) - Containerization
- [`metrics_cache.json`](../metrics_cache.json) - Real-time metrics storage

### Environment Variables
```bash
# Database
PF9_DB_HOST=db
PF9_DB_PORT=5432
PF9_DB_NAME=pf9_mgmt
PF9_DB_USER=pf9
PF9_DB_PASSWORD=<password>

# Platform9
PF9_AUTH_URL=https://your-cluster.com/keystone/v3
PF9_USERNAME=<service-account>
PF9_PASSWORD=<password>
PF9_PROJECT_NAME=service
PF9_REGION_NAME=region-one

# Monitoring Configuration (NEW)
PF9_HOSTS=203.0.113.10,203.0.113.11,203.0.113.12,203.0.113.13
METRICS_CACHE_TTL=60
```

## Emergency Procedures

### Service Down Emergency
1. Check all container status: `docker-compose ps`
2. Check available resources: `docker stats`
3. Check logs for errors: `docker-compose logs`
4. Restart affected services: `docker-compose restart <service>`
5. If issues persist: `docker-compose down && docker-compose up -d`

### Data Loss Emergency
1. Stop all services immediately: `docker-compose down`
2. Assess damage scope
3. Restore from latest backup
4. Verify data integrity
5. Restart services: `docker-compose up -d`

### Security Incident
1. Isolate affected systems: `docker-compose down`
2. Preserve logs: `docker-compose logs > incident_logs.txt`
3. Change all credentials

---

## User Management Features

### Overview
The Platform9 Management System includes comprehensive user management capabilities with multi-domain support.

### Key Statistics
- **100+ users** collected across **multiple active domains**
- **100+ role assignments** tracked with automatic fallback methods
- **Multi-domain authentication** ensures complete user visibility
- **Role inference system** provides intelligent role assignment when API access is limited

### User Data Collected
- **Identity**: User name, email, internal ID
- **Domain context**: Associated Keystone domain and domain name
- **Account status**: Enabled/disabled state
- **Role assignments**: Admin, member, service roles
- **Activity tracking**: Last seen timestamps
- **Project memberships**: Default project associations
- **Metadata**: User descriptions and display names

### API Endpoints
```bash
# List all users with pagination
GET /users?page=1&page_size=20&sort_by=name&sort_dir=asc

# Filter by domain
GET /users?domain_id=default

# Filter by account status
GET /users?enabled=true

# Get specific user
GET /users/{user_id}
```

### Technical Implementation
- **Domain-scoped collection**: Iterates through all domains to collect users
- **Role assignment fallback**: Multiple API methods ensure role collection
- **Change detection**: Tracks user modifications over time
- **Real-time updates**: User data refreshed during each inventory run
4. Notify security team
5. Rebuild from clean state if needed

## Support Contacts

- **Documentation**: [ADMIN_GUIDE.md](ADMIN_GUIDE.md)
- **Security Issues**: [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md)
- **API Documentation**: http://localhost:8000/docs
- **Platform9 Support**: Your Platform9 support portal