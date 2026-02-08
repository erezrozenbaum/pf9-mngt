# Platform9 Management System - Administrator Guide

## Recent Major Enhancements (February 2026)

### Landing Dashboard (v1.1 - NEW ✨✨✨)
- **14 Real-Time Analytics Endpoints**: Comprehensive operational intelligence dashboard
  - **Health Summary**: System-wide metrics (VMs, volumes, networks, alerts, CPU/memory utilization)
  - **Snapshot SLA Compliance**: Tenant-level snapshot policy compliance tracking with violation details
  - **Host Utilization**: Top N hosts by CPU/memory with critical threshold alerts (>85%)
  - **Recent Activity**: 24-hour activity timeline (VM creation, deletions, user logins)
  - **Coverage Risks**: Unprotected volume analysis with risk scoring and GB-at-risk calculations
  - **Capacity Pressure**: Storage/compute quota warnings (>75% storage, >80% compute)
  - **VM Hotspots**: Top resource consumers sorted by CPU, memory, or disk usage
  - **Tenant Risk Scores**: Multi-factor risk assessment (compliance, utilization, drift)
  - **Compliance Drift**: 7-day policy compliance trending with deterioration alerts
  - **Capacity Trends**: 7-day growth forecasting with projected exhaustion dates
  - **Trendlines**: 30-day infrastructure growth patterns (VMs, volumes, snapshots)
  - **Change Compliance**: Post-change snapshot verification within configurable windows
  - **Tenant Risk Heatmap**: Multi-dimensional risk matrix with interactive filtering
  - **Tenant Summary**: Quick tenant overview with VM/volume/network/user counts
- **17+ React Dashboard Components**: Advanced analytics cards with auto-refresh (30s intervals)
- **Dark/Light Mode Support**: Full theme compatibility with glassmorphic card design
- **Responsive Design**: Mobile-first layout with adaptive breakpoints (1440px, 1024px, 640px)
- **Auto-Refresh**: Real-time updates every 30 seconds with manual refresh capability
- **RBAC Integration**: Dashboard access requires "dashboard:read" permission

### Database Integration & Bug Fixes (v1.1)
- **db_writer.py Module**: Complete database integration layer (690+ lines)
  - 20+ upsert functions for all resource types (domains, projects, servers, volumes, networks, etc.)
  - Foreign key validation preventing constraint violations
  - SHA256-based change detection for history tracking
  - Savepoint-based transaction recovery for partial failure isolation
- **Fixed API Server Crash**: Corrected IndentationError in snapshot_management.py (lines 27-38)
- **Fixed Foreign Key Violations**: Enhanced validation logic for users, networks, ports, routers, floating_IPs
- **Fixed Integer Field Handling**: safe_int() helper to convert empty strings to NULL
- **Enhanced Snapshots History**: Added project_name, tenant_name, domain_name, domain_id columns
- **Transaction Isolation**: Intermediate commits prevent cascading failures in user management
- **Production Validation**: Successfully processes 107 users, 123 role assignments with zero violations

### Production-Ready Features
- **Startup Config Validation**: Comprehensive environment variable validation on API startup with color-coded results
- **API Performance Metrics**: Public `/metrics` + authenticated `/api/metrics` for UI (p50/p95/p99 latencies, request tracking)
- **Structured Logging**: JSON + colored console logs, plus authenticated `/api/logs` endpoint for UI
- **Admin UI Tabs**: New **API Metrics** and **System Logs** tabs (Admin/Superadmin only)
- **Auto Metrics Collection**: Dual-redundancy collection (background process + scheduled task) with automatic startup

### Enterprise Authentication & Authorization
- **LDAP Integration**: Production OpenLDAP authentication (dc=ccc,dc=co,dc=il)
- **Role-Based Access Control**: 4-tier permission system (Viewer, Operator, Admin, Superadmin)
- **JWT Token Management**: Secure 480-minute sessions with Bearer authentication
- **RBAC Middleware**: Automatic permission enforcement on all resource endpoints
- **Audit Logging**: Complete auth event tracking with 90-day retention
- **User Management**: LDAP user creation, role assignment, and permissions
- **Role-Based UI**: Dynamic tab visibility based on user permissions

### Complete Infrastructure Parity
- **Ports & Floating IPs**: Added comprehensive network port and floating IP tracking with full RVTools parity
- **Enhanced Change Attribution**: Fixed timestamp attribution to show actual infrastructure change times instead of RVtools scan times  
- **Improved Deletion Detection**: Prevents duplicate deletion records across multiple data collection cycles
- **Comprehensive Audit Dashboard**: Added storage summaries, network distribution, flavor analytics, and change velocity metrics
- **Resource History API**: Standardized history endpoints for all resource types with proper data transformation

### Database Schema Overview (22+ Tables)

#### Authentication & Authorization (3 tables)
- **user_roles**: User-to-role mappings with active status tracking
- **role_permissions**: Resource-level permission matrix (role → resource → action)
- **auth_audit_log**: Authentication event logging (login, logout, permission denied) with 90-day retention
- **user_sessions**: JWT session tracking with IP address and user agent

#### Core Identity & Organization (3 tables)
- **domains**: OpenStack domains with JSONB metadata and foreign key relationships
- **projects**: Projects/tenants with domain associations and comprehensive metadata
- **users**: User accounts with domain associations, role tracking, and activity timestamps

#### Compute Infrastructure (4 tables)
- **hypervisors**: Physical compute nodes with resource utilization and status tracking
- **servers**: Virtual machines with complete lifecycle, flavor associations, and project relationships
- **flavors**: VM templates with detailed resource specifications and public/private visibility
- **images**: OS and application images with format details and visibility controls

#### Storage Infrastructure (3 tables)
- **volumes**: Block storage volumes with attachment details, metadata policies, and snapshot tracking
- **snapshots**: Volume snapshots with policy compliance, retention tracking, and size information
- **volume_types**: Storage classes with performance tiers and backend specifications

#### Network Infrastructure (7 tables)
- **networks**: Virtual networks with tenant isolation, shared/external flags, and project associations
- **subnets**: IP subnets with CIDR notation, gateway configuration, and network relationships
- **ports**: Network interface ports with MAC addresses, IP assignments, and device attachments
- **routers**: Virtual routers with external connectivity and project relationships
- **floating_ips**: Public IP addresses with assignment tracking and router associations
- **security_groups**: Firewall rule sets with project associations and rule collections
- **security_group_rules**: Individual firewall rules with protocol, port, and direction specifications

#### Audit & Historical Tracking (2+ base tables + individual history tables)
- **deletions_history**: Comprehensive deletion tracking for all resource types with attribution
- **inventory_runs**: Data collection metadata with timing, source, and status tracking
- **v_comprehensive_changes** (View): Unified change tracking with accurate temporal attribution
- **{resource}_history** tables: Individual history tracking for each resource type with change hash detection

#### Performance Optimizations & Advanced Features
- **RBAC Middleware**: HTTP middleware enforces permissions before request processing
- **Composite Indexes**: Multi-column indexes on (domain_id, project_id, last_seen_at) for efficient filtering
- **JSONB GIN Indexes**: Fast metadata searches and complex attribute queries
- **Foreign Key Constraints**: Complete referential integrity across all resource relationships
- **Timestamp Precision**: Millisecond-accurate change attribution (infrastructure time vs. scan time)
- **Historical Partitioning**: Time-based organization for efficient historical queries

---

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture & Components](#architecture--components)
3. [Authentication & Authorization](#authentication--authorization)
4. [Real-Time Monitoring System](#real-time-monitoring-system)
5. [Production Features](#production-features)
   - [Startup Configuration Validation](#1-startup-configuration-validation-)
   - [API Performance Metrics](#2-api-performance-metrics-)
   - [Structured Logging](#3-structured-logging-centralized-logging-foundation-)
   - [Automated Metrics Collection](#4-automated-metrics-collection-)
6. [Core Components Deep Dive](#core-components-deep-dive)
7. [Installation & Deployment](#installation--deployment)
8. [Security Considerations](#security-considerations)
9. [Database Management](#database-management)
10. [API Operations](#api-operations)
11. [UI Management](#ui-management)
12. [Data Collection & Reporting](#data-collection--reporting)
13. [Monitoring & Troubleshooting](#monitoring--troubleshooting)
14. [Maintenance & Updates](#maintenance--updates)
15. [Code Quality Issues](#code-quality-issues)
16. [Recommended Improvements](#recommended-improvements)

---

## System Overview

The Platform9 Management System is a comprehensive OpenStack infrastructure management portal with enterprise LDAP authentication and role-based access control. Designed specifically for Platform9 environments, it provides secure multi-tenant resource administration, real-time inventory, automated snapshot management, and compliance reporting.

### Core Capabilities
- **Enterprise Authentication**: LDAP integration with JWT token management
- **Role-Based Access Control**: 4-tier permission system with automatic enforcement
- **Audit & Compliance**: 90-day authentication event tracking and permission logging
- **Comprehensive Inventory Management**: Real-time tracking of VMs, volumes, snapshots, networks, subnets, ports, floating IPs, hypervisors, flavors, and images
- **Automated Snapshot Management**: Policy-driven snapshot creation with configurable retention periods
- **Compliance Reporting**: Detailed compliance reports with policy adherence tracking
- **Multi-Tenant Resource Administration**: Domain and project-level filtering with role-based permissions
- **Complete RVTools Parity**: Full infrastructure visibility including ports and floating IP tracking
- **Enhanced Change Tracking**: Accurate timestamp attribution showing actual infrastructure change times
- **Comprehensive Audit Dashboard**: Storage summaries, network distribution, flavor analytics, and change velocity metrics
- **REST API**: Full programmatic access with RBAC enforcement and comprehensive resource history endpoints
- **Real-time Dashboard**: React-based web interface with role-based tab visibility

### Key Features
- **User Management**: LDAP user creation, role assignment, and permission management
- **Permission Matrix**: Granular resource-level permissions (read/write/admin)
- **Role-Based UI**: Admin panel visible only to admin/superadmin users
- **Multi-Policy Snapshot Support**: Volume-level metadata-driven snapshot policies
- **Historical Data Tracking**: Complete audit trail with delta reporting
- **Customer Data Masking**: Privacy-compliant data exports
- **Administrative Functions**: Create/delete flavors and networks (permission-controlled)
- **Database-Driven Architecture**: PostgreSQL persistence with full relational integrity
- **Container-Native Deployment**: Docker Compose orchestration with LDAP server

## Authentication & Authorization

### LDAP Integration

The system uses OpenLDAP for enterprise user authentication:
- **LDAP Server**: Port 389
- **Base DN**: dc=ccc,dc=co,dc=il
- **User DN**: ou=users,dc=ccc,dc=co,dc=il
- **Admin Password**: Configured via LDAP_ADMIN_PASSWORD environment variable

> **Note:** As of February 2026, running `deployment.ps1` will always ensure:
> - The admin user (from `.env`: `DEFAULT_ADMIN_USER`/`DEFAULT_ADMIN_PASSWORD`) is created in LDAP and in the `user_roles` table as `superadmin`.
> - The `superadmin` role always has a wildcard permission (`*`) in `role_permissions`.
> - You do **not** need to manually create the admin user or fix permissions in the database—this is enforced automatically on every deployment.
> - If you change the admin username/email in `.env`, simply re-run `deployment.ps1` and the system will update LDAP and database roles/permissions accordingly.

Manual LDAP or database admin setup is no longer required for initial deployment or admin recovery.

### Role Hierarchy
1. **Viewer**: Read-only access to all resources
2. **Operator**: Read + limited write (networks, flavors)
3. **Admin**: Full operational access except user management
4. **Superadmin**: Complete system access including user management

### Permission Enforcement
- **Middleware-Based**: RBAC middleware checks permissions before processing requests
- **Token-Based**: JWT Bearer tokens with username and role claims
- **Resource-Level**: Permissions checked against role_permissions table
- **Audit Trail**: All permission denials logged to auth_audit_log

### User Management Operations

- Create LDAP users via Admin panel or API (superadmin only)
- Assign roles: viewer, operator, admin, superadmin
- Track authentication events: login, logout, failed_login
- Monitor user activity via System Audit tab (90-day retention)

> **Admin/Superadmin Setup Automation:**
> The admin user and superadmin permissions are always enforced by `deployment.ps1` using `.env` values. Manual admin user/role/permission setup is not required and will be automatically corrected on each deployment.

## Real-Time Monitoring System

### Architecture Overview
The monitoring system operates in a **hybrid host-container model**:
- **Host-side Collection**: [host_metrics_collector.py](../host_metrics_collector.py) runs on Windows host
- **Container Service**: [monitoring/main.py](../monitoring/main.py) serves cached data via FastAPI
- **Cache-based Storage**: JSON cache file ensures data persistence across container restarts
- **UI Integration**: Real-time monitoring tab in main UI with auto-refresh

### Host Metrics Collection (✅ Working)
**Prometheus node_exporter integration** (port 9388):
```python
# From host_metrics_collector.py
async def collect_host_metrics(self, session, host):
    async with session.get(f"http://{host}:9388/metrics", timeout=10) as response:
        if response.status == 200:
            text = await response.text()
            return self.parse_host_metrics(text, host)
```

**Automated Collection Methods** (Dual Approach):

1. **Background Process** (Primary):
   - **Auto-start**: Launched automatically by [startup.ps1](../startup.ps1) after services start
   - **Process Type**: Continuous Python process running in hidden window
   - **Collection Loop**: Runs continuously with configurable intervals
   - **Logs**: Output written to `metrics_collector.log`
   - **Process Management**: Old collectors auto-terminated before new start
   - **Status Check**: PID displayed on successful startup
   - **Fallback**: Manual start with `python host_metrics_collector.py`

2. **Windows Task Scheduler** (Backup/Redundancy):
   - **Frequency**: Every 30 minutes
   - **Purpose**: Ensures collection continues if background process stops
   - **Setup**: Automated by [startup.ps1](../startup.ps1)
   - **Task Name**: "PF9 Metrics Collection"
   - **Remove**: Run `.\startup.ps1 -StopOnly` to clean up

**Storage & Persistence**:
- **Cache**: Persistent storage in `metrics_cache.json` (workspace root)
- **Docker Mount**: Cache file accessible to monitoring container
- **Survives**: Container restarts, system reboots (with scheduled task)
- **Status**: ✅ **Working reliably with dual collection**

### VM Metrics Collection (❌ Requires PF9 Engineering)
**Libvirt exporter integration** (port 9177):
```python
async def collect_vm_metrics(self, session, host):
    async with session.get(f"http://{host}:9177/metrics", timeout=10) as response:
        # Currently returns libvirt_up=0 (connection failed)
```

**Current Status**: 
- **Issue**: Libvirt exporters cannot connect to libvirtd daemon
- **Impact**: Individual VM resource metrics unavailable
- **Workaround**: Host-level aggregated metrics still provide value
- **Support Ticket**: See [PF9_ENGINEERING_REQUEST.txt](../PF9_ENGINEERING_REQUEST.txt)

### Monitoring Service API

**FastAPI Endpoints** ([monitoring/main.py](../monitoring/main.py)):
```python
@app.get("/health")
async def health_check()  # Service health status

@app.get("/auto-setup") 
async def auto_setup()    # Automatic monitoring setup detection

@app.get("/metrics/hosts")
async def get_host_metrics()  # Host resource data

@app.get("/metrics/vms") 
async def get_vm_metrics()    # VM resource data (when available)
```

**Cache Data Structure**:
```json
{
  "hosts": [
    {
      "hostname": "203.0.113.10",
      "cpu_usage": 45.2,
      "memory_usage": 67.8,
      "disk_usage": 23.1,
      "timestamp": "2026-02-02T10:30:00Z"
    }
  ],
  "vms": [],  // Empty until libvirt issue resolved
  "summary": {
    "total_hosts": 4,
    "total_vms": 0,
    "last_update": "2026-02-02T10:30:00Z"
  },
  "timestamp": "2026-02-02T10:30:00Z"
}
```

### Integration with Main UI

**React Component Integration** ([pf9-ui/src/App.tsx](../pf9-ui/src/App.tsx)):
- **Monitoring Tab**: Dedicated real-time monitoring view
- **Auto-refresh**: Configurable refresh intervals
- **Host Status Cards**: Visual representation of host health
- **Resource Charts**: CPU, memory, storage utilization graphs
- **Alert Indicators**: Visual alerts for resource thresholds

### Configuration & Setup

**Automatic Setup** (Recommended):
```powershell
# Complete setup including monitoring
.\startup.ps1

# Verify monitoring setup
schtasks /query /tn "PF9 Metrics Collection"
```

**Manual Setup**:
```powershell
# Create scheduled task for metrics collection
schtasks /create /tn "PF9 Metrics Collection" /tr "python C:\pf9-mngt\host_metrics_collector.py" /sc minute /mo 30 /ru SYSTEM

# Run collection manually
python host_metrics_collector.py

# Check cache output
Get-Content metrics_cache.json | ConvertFrom-Json
```

### Troubleshooting Monitoring

**Common Issues**:
1. **Empty monitoring data**:
   ```powershell
   # Check if scheduled task is running
   schtasks /query /tn "PF9 Metrics Collection" /fo list
   
   # Run collection manually to test
   python host_metrics_collector.py
   
   # Verify cache file creation
   ls metrics_cache.json
   ```

2. **Host connection timeouts**:
   ```powershell
   # Test node_exporter accessibility
   curl http://172.17.95.2:9388/metrics
   
   # Check network connectivity
   Test-NetConnection 172.17.95.2 -Port 9388
   ```

3. **Monitoring service errors**:
   ```bash
   # Check monitoring container logs
   docker-compose logs pf9_monitoring
   
   # Verify cache file is mounted
   docker-compose exec pf9_monitoring ls -la /tmp/metrics_cache.json
   ```

**Performance Optimization**:
- **Cache TTL**: Configurable via `METRICS_CACHE_TTL` (default: 60 seconds)
- **Collection Frequency**: Adjustable via Task Scheduler (default: 30 minutes)
- **Host Timeout**: 10-second timeout per host for reliability

### Container Services
1. **pf9_db** - PostgreSQL 16 database with 19+ tables and comprehensive schemas
2. **pf9_pgadmin** - Database administration (optional for production)
3. **pf9_api** - FastAPI backend with 25+ REST endpoints and administrative operations
4. **pf9_ui** - React 19.2 frontend with TypeScript, Vite build system, and modern UI components
5. **pf9_monitoring** - Real-time metrics service with cache-based storage and auto-refresh capabilities

### Data Flow & Architecture
1. **Collection Phase**: 
   - [pf9_rvtools.py](../pf9_rvtools.py): Comprehensive OpenStack resource discovery (19+ types)
   - [host_metrics_collector.py](../host_metrics_collector.py): Real-time host metrics via Prometheus node_exporter
   - Automated via Windows Task Scheduler every 30 minutes

2. **Storage Layer**: 
   - PostgreSQL 16 with normalized relational schema
   - Historical tracking with audit trails
   - Efficient indexing for performance

3. **API Layer**: 
   - FastAPI with OpenAPI documentation at `/docs`
   - Administrative endpoints for create/delete operations
   - Filtered, paginated data access with proper error handling

4. **Frontend Layer**: 
   - React 19.2 with TypeScript for type safety
   - Vite for fast development and optimized builds
   - Real-time data refresh with auto-updating components
5. **Export**: RVTools-compatible XLSX/CSV generation
6. **Automation**: Snapshot policies execute on schedule
7. **Monitoring**: Real-time metrics from PF9 hosts via Prometheus exporters

---

## Core Components Deep Dive

### Database Schema (19+ Tables)
```sql
-- Core Identity
domains, projects, hypervisors

-- Compute Resources  
servers, flavors, images

-- Storage Resources
volumes, snapshots

-- Network Resources
networks, subnets, ports, floating_ips, routers

-- Change Tracking & Audit
*_history tables for all resource types
deletions_history table
v_comprehensive_changes view
networks, subnets, ports, routers, floating_ips

-- Operational Tables
inventory_runs  -- Audit trail for data collection
```

### API Endpoints (40+ Routes)
**Core Resource Endpoints** (19+ Resource Types):
- `GET /domains` - Domain/tenant hierarchy management
- `GET /tenants` - Project listings with domain relationships
- `GET /servers` - VM inventory with comprehensive filtering
- `GET /volumes` - Storage inventory with metadata and snapshot policies
- `GET /snapshots` - Snapshot listings with policy compliance
- `GET /networks` - Network topology and tenant isolation
- `GET /subnets` - Subnet details with CIDR and gateway information
- `GET /ports` - Port configurations with MAC addresses and IP assignments
- `GET /floatingips` - Floating IP allocations and assignments
- `GET /flavors` - Compute flavors and resource specifications
- `GET /images` - OS and application images
- `GET /hypervisors` - Physical compute node inventory

**Identity & User Management Endpoints**:
- `GET /users` - Multi-domain user collection and filtering
- `GET /users/{user_id}` - Detailed user information with role assignments
- `GET /roles` - Role definitions and permissions
- `GET /role-assignments` - User role assignment tracking
- `GET /user-activity-summary` - User activity analytics

**Historical Analysis & Audit Endpoints**:
- `GET /history/recent-changes` - Recent infrastructure changes
- `GET /history/most-changed` - Most frequently changed resources
- `GET /history/by-timeframe` - Changes by time period
- `GET /history/resource/{type}/{id}` - Resource-specific history timeline
- `GET /audit/compliance-report` - Comprehensive compliance analysis
- `GET /audit/change-patterns` - Change pattern and velocity analysis
- `GET /audit/resource-timeline/{type}` - Resource type timeline analysis

**Administrative Endpoints**:
- `POST /admin/flavors` - Create compute flavors
- `DELETE /admin/flavors/{id}` - Remove flavors
- `POST /admin/networks` - Create networks
- `DELETE /admin/networks/{id}` - Remove networks
- `POST /admin/user-access-log` - Log user access activity

**Volume Management Endpoints**:
- `GET /volumes/{volume_id}/metadata` - Volume metadata inspection
- `GET /volumes/metadata/bulk` - Bulk metadata operations
- `GET /volumes-with-metadata` - Volumes with snapshot policy display

**System Health & Testing Endpoints**:
- `GET /health` - Service health check
- `GET /simple-test` - Basic functionality verification
- `GET /test-history-endpoints` - History functionality verification

**Specialized Data Endpoints**:
- `GET /tenants/summary` - Tenant resource summaries

### Python Scripts (8 Core Scripts)
1. **pf9_rvtools.py** - Main inventory collection (542 lines)
2. **snapshots/p9_auto_snapshots.py** - Automated snapshot management (754 lines)
3. **snapshots/p9_snapshot_compliance_report.py** - Compliance reporting (749 lines)
4. **snapshots/p9_snapshot_policy_assign.py** - Policy management (454 lines)
5. **p9_common.py** - Shared utilities and API clients (376 lines)
6. **db_writer.py** - Database operations (1113 lines)
7. **test_db_write.py** - Database testing utilities
8. **api/pf9_control.py** - Platform9 API client

---

## Installation & Deployment

### Prerequisites
- Docker Engine 20.10+ and Docker Compose 2.0+
- 8GB+ RAM (recommended for production)
- 50GB+ disk space (database growth)
- Network access to Platform9 cluster APIs
- Valid Platform9 service account credentials

### Quick Start

#### Option 1: Complete Automation (Recommended)
```powershell
# Clone repository
git clone <repository-url>
cd pf9-mngt

# Configure credentials (one-time setup)
cp .env.template .env
# Edit .env with your Platform9 credentials

# Complete automated setup
.\startup.ps1

# This automatically:
# - Starts all Docker services (DB, API, UI, Monitoring) 
# - Collects initial metrics from PF9 hosts
# - Sets up scheduled metrics collection (every 2 minutes)
# - Verifies all services are operational
# - Zero manual intervention required after .env setup

# To stop everything
.\startup.ps1 -StopOnly
```

#### Option 2: Manual Docker Setup
```bash
git clone <repository-url>
cd pf9-mngt

# Create secure environment configuration
cp docker-compose.yml.example docker-compose.yml
```

#### 2. Security Setup (CRITICAL)
```bash
# Generate secure passwords
DB_PASSWORD=$(openssl rand -base64 32)
ADMIN_PASSWORD=$(openssl rand -base64 16)

# Create secure docker-compose.yml
sed -i "s/pf9_password_change_me/$DB_PASSWORD/g" docker-compose.yml
sed -i "s/admin123/$ADMIN_PASSWORD/g" docker-compose.yml

# Remove hardcoded Platform9 credentials - MUST BE DONE
sed -i '/PF9_USERNAME:/d' docker-compose.yml
sed -i '/PF9_PASSWORD:/d' docker-compose.yml

# Add environment file
cat > .env << EOF
PF9_USERNAME=service-account@example.com
PF9_PASSWORD=your-secure-password
PF9_AUTH_URL=https://your-pf9-cluster.com/keystone/v3
PF9_PROJECT_NAME=service
PF9_REGION_NAME=region-one

# Database Configuration (for Docker)
POSTGRES_USER=pf9
POSTGRES_PASSWORD=generate-secure-password
POSTGRES_DB=pf9_mgmt

# Monitoring Configuration (NEW)
PF9_HOSTS=203.0.113.10,203.0.113.11,203.0.113.12,203.0.113.13
METRICS_CACHE_TTL=60
EOF
chmod 600 .env
```

#### 3. Deploy Services
```bash
# Start all services
docker-compose up -d

# Verify deployment
docker-compose ps
docker-compose logs -f pf9_api  # Check for errors
```

#### 4. Initial Data Collection
```bash
# Scripts can run outside Docker and automatically load .env file
# Database connection is optional - script will continue if DB unavailable

# Run first inventory collection
python pf9_rvtools.py

# If Docker services are running, verify data in database
docker exec -it pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM servers;"

# Check generated reports
dir "C:\Reports\Platform9\*.xlsx"
```

#### 5. Access Interfaces
- **Management UI**: http://localhost:5173 (Primary interface with monitoring tab)
- **API Documentation**: http://localhost:8000/docs (OpenStack API gateway)
- **Monitoring API**: http://localhost:8001 (Real-time metrics service)
- **Database Admin**: http://localhost:8080 (pgAdmin - optional)
- **Health Check**: http://localhost:8000/health (Main API health)
- **Monitoring Health**: http://localhost:8001/health (Monitoring service health)
- **Reports**: Generated in `C:\Reports\Platform9\` (works standalone)

### Standalone Script Execution

Python scripts can run independently without Docker services:

```bash
# Scripts automatically load .env file and continue without database
cd C:\pf9-mngt
python pf9_rvtools.py                    # Inventory collection
python snapshots/p9_auto_snapshots.py     # Snapshot automation
python snapshots/p9_snapshot_compliance_report.py  # Compliance reporting
```

**Features when running standalone**:
- ✅ Platform9 API access and data collection
- ✅ Excel/CSV report generation
- ✅ Automatic .env file loading
- ❌ No database storage (optional)
- ❌ No web UI access

---

## Production Features

### 1. Startup Configuration Validation ✅

**Implementation**: [api/config_validator.py](../api/config_validator.py)

Comprehensive environment variable validation that runs **before** the FastAPI application starts, ensuring all required configuration is present and valid.

**Features**:
- ✅ Validates 12+ required environment variables (DB, LDAP, JWT, PF9 credentials)
- ✅ Checks port number ranges (1-65535)
- ✅ Validates URL formats (http/https)
- ✅ Enforces JWT secret minimum length (32 characters)
- ✅ Validates token expiration range (1 minute to 1 week)
- ✅ Color-coded validation results (green ✓ / red ✗)
- ✅ **Exits with error** if validation fails (prevents startup with bad config)

**Validated Configuration**:
```python
# Required Variables
PF9_DB_HOST, PF9_DB_PORT, PF9_DB_NAME
PF9_DB_USER, PF9_DB_PASSWORD
PF9_AUTH_URL, PF9_USERNAME, PF9_PASSWORD
LDAP_SERVER, LDAP_PORT, LDAP_BASE_DN
JWT_SECRET_KEY

# Optional (with defaults)
PF9_USER_DOMAIN (Default)
PF9_PROJECT_NAME (service)
JWT_ALGORITHM (HS256)
JWT_ACCESS_TOKEN_EXPIRE_MINUTES (480)
```

**Startup Output Example**:
```
======= Configuration Validation Results =======
✓ PF9_DB_HOST: postgres
✓ PF9_DB_PORT: 5432 (valid port)
✓ PF9_AUTH_URL: https://pf9.example.com (valid URL)
✓ JWT_SECRET_KEY: ******** (32+ chars)
⚠ Using default for PF9_USER_DOMAIN=Default
✅ Configuration validation PASSED
```

**Error Handling**:
If validation fails, the API container exits with code 1 and displays detailed errors:
```
✗ Missing required env var: PF9_DB_PASSWORD
✗ Invalid port: PF9_DB_PORT=99999 (must be 1-65535)
✗ Invalid URL format: PF9_AUTH_URL=invalid-url
❌ Configuration validation FAILED
Exiting...
```

---

### 2. API Performance Metrics ✅

**Implementation**: [api/performance_metrics.py](../api/performance_metrics.py)

Real-time performance monitoring with FastAPI middleware that tracks every API request and provides detailed metrics via a public endpoint.

**Features**:
- ✅ In-memory metrics storage (configurable, default 1000 requests)
- ✅ Per-endpoint request counting and timing
- ✅ Status code distribution tracking
- ✅ Slow request detection (>1 second threshold)
- ✅ Error request tracking (4xx, 5xx)
- ✅ Latency percentiles (avg, min, max, p50, p95, p99)
- ✅ Requests per second calculation
- ✅ Uptime tracking
- ✅ **No authentication required** on `/metrics` endpoint

**Metrics Endpoints**:
- **Public** (for Prometheus/Grafana): `GET http://localhost:8000/metrics`
- **Authenticated UI**: `GET http://localhost:8000/api/metrics`

**RBAC Requirement**:
- `api_metrics:read` (granted to Admin/Superadmin)

**Response Structure**:
```json
{
  "uptime_seconds": 3600.45,
  "total_requests": 1523,
  "requests_per_second": 0.42,
  "status_codes": {
    "200": 1450,
    "401": 12,
    "404": 5,
    "500": 2
  },
  "top_endpoints": [
    {
      "endpoint": "/servers",
      "count": 450,
      "avg_duration": 0.125,
      "min_duration": 0.045,
      "max_duration": 0.850,
      "p50": 0.110,
      "p95": 0.320,
      "p99": 0.650
    }
  ],
  "slow_endpoints": [
    {
      "endpoint": "/volumes/history",
      "avg_duration": 1.245,
      "count": 15
    }
  ],
  "recent_slow_requests": [
    {
      "endpoint": "/snapshots",
      "duration": 2.341,
      "timestamp": "2026-02-05T10:23:45.123Z",
      "status_code": 200
    }
  ],
  "recent_errors": [
    {
      "endpoint": "/auth/login",
      "status_code": 401,
      "timestamp": "2026-02-05T10:20:12.456Z",
      "duration": 0.089
    }
  ]
}
```

**Response Headers**:
All API responses include:
```
X-Process-Time: 0.123  # Request duration in seconds
```

**Integration**:
```python
# api/main.py
from api.performance_metrics import PerformanceMetrics, PerformanceMiddleware

performance_metrics = PerformanceMetrics()
app.add_middleware(PerformanceMiddleware, metrics=performance_metrics)

@app.get("/metrics")
async def get_metrics():
    return performance_metrics.get_stats()

@app.get("/api/metrics")
async def get_api_metrics_authenticated():
  # Requires auth + api_metrics:read
  return performance_metrics.get_stats()
```

**Use Cases**:
- Monitor API response times in production
- Identify slow endpoints needing optimization
- Track error rates and patterns
- Capacity planning (requests/second trends)
- SLA compliance monitoring

---

### 3. Structured Logging (Centralized Logging Foundation) ✅

**Implementation**: [api/structured_logging.py](../api/structured_logging.py)

Production-grade logging with JSON formatting for log aggregation tools (ELK, Loki, Datadog) and colored console output for development.

**Features**:
- ✅ **Dual formatters**: JSON (production) + Colored Console (development)
- ✅ **Context-rich logs**: user, endpoint, status_code, duration_ms, ip_address
- ✅ **Exception tracking**: Full stack traces with structured data
- ✅ **Configurable output**: Console, file, or both
- ✅ **Log levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- ✅ **Noise reduction**: Quiets uvicorn and asyncio loggers
- ✅ **Compatible with**: ELK Stack, Grafana Loki, Splunk, Datadog

**Configuration** (Environment Variables):
```bash
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR, CRITICAL
JSON_LOGS=true              # true=JSON, false=colored console
LOG_FILE=/var/log/pf9.log  # Optional file output
```

**System Logs Endpoint**:
- **Authenticated UI**: `GET http://localhost:8000/api/logs`
- **Query Params**: `limit`, `level`, `source`, `log_file`
- **Log Sources**: `pf9_api`, `pf9_monitoring` (use `log_file=all` to aggregate)
- **RBAC Requirement**: `system_logs:read` (Admin/Superadmin only)

**JSON Log Format** (Production):
```json
{
  "timestamp": "2026-02-05T10:23:45.123Z",
  "level": "INFO",
  "logger": "pf9_api",
  "message": "Request completed",
  "context": {
    "user": "admin",
    "endpoint": "/servers",
    "method": "GET",
    "status_code": 200,
    "duration_ms": 125.4,
    "ip_address": "172.17.0.1"
  }
}
```

**Colored Console Format** (Development):
```
[2026-02-05 10:23:45] INFO pf9_api | Request completed
  user=admin endpoint=/servers status_code=200 duration_ms=125.4
```

**Error Logging Example**:
```json
{
  "timestamp": "2026-02-05T10:25:12.456Z",
  "level": "ERROR",
  "logger": "pf9_api",
  "message": "Database connection failed",
  "exception": "psycopg2.OperationalError: connection refused",
  "stack_trace": "Traceback (most recent call last)...",
  "context": {
    "endpoint": "/volumes",
    "user": "operator1"
  }
}
```

**Integration**:
```python
# api/main.py
from api.structured_logging import setup_logging

logger = setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    json_logs=os.getenv("JSON_LOGS", "false").lower() == "true",
    log_file=os.getenv("LOG_FILE")
)

# Usage in code
logger.info("Server started", extra={"context": {"port": 8000}})
logger.error("Auth failed", extra={"context": {"user": username, "ip": client_ip}})
```

**Log Aggregation Ready**:
- **ELK Stack**: Direct JSON ingestion via Filebeat
- **Grafana Loki**: LogQL queries on JSON fields
- **Datadog**: Automatic attribute parsing
- **Splunk**: JSON sourcetype recognition

**Benefits**:
- ✅ Searchable structured logs (query by user, endpoint, status)
- ✅ Metrics from logs (request duration histograms)
- ✅ Alerting on error patterns
- ✅ Distributed tracing correlation (add request_id)
- ✅ Compliance audit trails

---

### 4. Automated Metrics Collection ✅

**Implementation**: [startup.ps1](../startup.ps1) + [host_metrics_collector.py](../host_metrics_collector.py)

Dual-redundancy approach for continuous infrastructure metrics collection with automatic startup and scheduled backup.

See [Real-Time Monitoring System](#real-time-monitoring-system) section for full details.

**Quick Summary**:
- **Primary**: Background Python process (auto-start on system launch)
- **Backup**: Windows Task Scheduler (every 30 minutes)
- **Cache**: `metrics_cache.json` (persistent across restarts)
- **Status**: ✅ Production-ready with automatic recovery

---

## Security Considerations

### ✅ **SECURITY STATUS: SIGNIFICANTLY IMPROVED**

Credential security has been successfully implemented using environment variables and `.env` file configuration.

#### ✅ **RESOLVED: Credential Security**
**Status**: **SECURE** - Environment variable configuration implemented

**Current Implementation**:
- All credentials now loaded via `os.getenv()` in Python scripts
- Docker Compose uses `${VAR}` environment variable substitution
- `.env.template` provides secure setup instructions
- `.gitignore` prevents credential files from being committed
- Scripts auto-load `.env` file when running outside Docker

**Security Features**:
```python
# Secure configuration in p9_common.py
CFG = {
    "USERNAME": os.getenv("PF9_USERNAME", ""),
    "PASSWORD": os.getenv("PF9_PASSWORD", ""),
    "KEYSTONE_URL": os.getenv("PF9_AUTH_URL", ""),
    # No hardcoded credentials
}
```

#### 🟡 **REMAINING MEDIUM RISK: CORS Configuration**
**Location**: [api/main.py:29](api/main.py#L29)
```python
# STILL NEEDS FIXING
allow_origins=["*"]  # Should be restricted
```

**Recommended Fix**:
```python
allow_origins=[
    "http://localhost:5173",  # Development
    "https://pf9-mgmt.company.com",  # Production
    os.getenv("ALLOWED_ORIGINS", "").split(",")
]
```

#### 🟡 **REMAINING MEDIUM RISK: Administrative Endpoints**
**Status**: No authentication on admin functions

**Vulnerable Endpoints**: [api/main.py:1041-1124](api/main.py#L1041-L1124)
- `POST /admin/flavors` - Create compute flavors
- `DELETE /admin/flavors/{id}` - Delete flavors  
- `POST /admin/networks` - Create networks
- `DELETE /admin/networks/{id}` - Delete networks

**Recommended**: Implement API key or JWT authentication for admin endpoints.
PF9_DB_HOST=db
PF9_DB_PORT=5432
PF9_DB_NAME=pf9_mgmt
PF9_DB_USER=pf9
PF9_DB_PASSWORD=<secure-password>
```

#### Platform9 Authentication
```bash
PF9_AUTH_URL=https://your-cluster.com/keystone/v3
PF9_USERNAME=<service-account>
PF9_PASSWORD=<secure-password>
PF9_USER_DOMAIN=Default
PF9_PROJECT_NAME=service
PF9_PROJECT_DOMAIN=Default
PF9_REGION_NAME=region-one
```

### Configuration Files

#### API Configuration (`api/main.py`)
- Database connection settings
- CORS policy configuration
- Authentication timeouts
- Pagination limits

#### UI Configuration (`pf9-ui/vite.config.ts`)
- API proxy settings
- Development server configuration
- Build optimization settings

---

## Database Management

### Schema Overview
The system uses PostgreSQL with the following key tables:
- `domains` - OpenStack domains/organizations
- `projects` - Tenant/project information
- `servers` - Virtual machine inventory
- `volumes` - Block storage volumes
- `snapshots` - Volume snapshots
- `networks` - Network infrastructure
- `ports` - Network port assignments
- `hypervisors` - Physical compute nodes
- `inventory_runs` - Data collection audit trail

### Database Operations

#### Access Database
```bash
# Via pgAdmin (recommended)
# http://localhost:8080

# Direct connection
docker exec -it pf9_db psql -U pf9 -d pf9_mgmt
```

#### Backup Operations
```bash
# Create backup
docker exec pf9_db pg_dump -U pf9 pf9_mgmt > backup_$(date +%Y%m%d).sql

# Restore backup
docker exec -i pf9_db psql -U pf9 pf9_mgmt < backup_file.sql
```

#### Performance Monitoring
```sql
-- Check table sizes
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Check recent inventory runs
SELECT * FROM inventory_runs ORDER BY started_at DESC LIMIT 10;
```

---

## API Operations

### Core Endpoints

#### Data Retrieval
```http
GET /domains                 # Domain/organization list
GET /tenants                 # Project/tenant list  
GET /servers                 # Virtual machine inventory
GET /volumes                 # Block storage volumes
GET /snapshots               # Volume snapshots
GET /networks                # Network infrastructure
GET /subnets                 # Network subnets
```

#### Administrative Functions
```http
POST /admin/flavors          # Create VM flavors
DELETE /admin/flavors/{id}   # Delete VM flavors
POST /admin/networks         # Create networks
DELETE /admin/networks/{id}  # Delete networks
```

#### Query Parameters
All list endpoints support:
- `page` - Page number (default: 1)
- `page_size` - Items per page (max: 500)
- `sort_by` - Sort field
- `sort_dir` - Sort direction (asc/desc)
- `domain_name` - Filter by domain
- `tenant_id` - Filter by tenant

### API Usage Examples

#### Retrieve Server List
```bash
curl "http://localhost:8000/servers?page=1&page_size=50&sort_by=vm_name"
```

#### Create Flavor
```bash
curl -X POST "http://localhost:8000/admin/flavors" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "m1.medium",
    "vcpus": 2,
    "ram_mb": 4096,
    "disk_gb": 40,
    "is_public": true
  }'
```

### Rate Limiting & Performance
- No explicit rate limiting implemented (⚠️ Security Issue)
- Pagination enforced with max 500 items per page
- Database queries use indexed columns for performance
- Connection pooling via psycopg2

---

## UI Management

### Interface Overview
The React-based UI provides:
- **Multi-tab interface** (VMs, Snapshots, Networks, Subnets, Volumes)
- **Advanced filtering** by domain, tenant, status
- **Sorting and pagination** for large datasets
- **CSV export functionality** for all data types
- **Detailed view panels** for selected items
- **Admin Panel** for system administration (accessible only to Admin/Superadmin users)

### Admin Panel (System Administration)

The Admin Panel provides comprehensive system administration capabilities accessible via the Admin icon in the main navigation. Only users with Admin or Superadmin roles can access this panel.

#### Admin Panel Tabs

##### 1. LDAP Users Tab
Manage local LDAP user accounts for accessing the management system:
- **View all LDAP users** with usernames, email addresses, and current roles
- **Create new users** with role assignment (Superadmin only)
- **Edit user roles** - Reassign roles (admin, operator, viewer) to users
- **Delete users** - Remove user accounts from the system (Superadmin only)
- **User status tracking** - See which users are active or inactive

**Current Users**: The system includes 7 LDAP users (admin, erez, itay, ili, yaronso, itayh, yaronm) with role distributions:
- Superadmin: 5 users
- Admin: 0 users  
- Operator: 1 user
- Viewer: 1 user

##### 2. Roles Tab
View the system's role hierarchy and user distribution:
- **Superadmin**: Full system access including user management (5 users)
- **Admin**: Administrative access for resource operations (0 users)
- **Operator**: Operational access with limited write permissions (1 user)
- **Viewer**: Read-only access to all resources (1 user)

Shows real-time user count for each role automatically updated from LDAP authentication data.

##### 3. Permissions Tab
View the Permission Matrix showing resource-level access control:
- **Resource list**: servers, volumes, snapshots, networks, subnets, ports, floatingips, domains, projects, flavors, images, hypervisors, users, monitoring, history, audit
- **Actions**: read, write, admin (actions vary by resource)
- **Role permissions**: Visual matrix showing which roles have access to each resource action
- **Read-only display**: Current implementation shows permissions for reference

**Permission Matrix Features**:
- Only displays actual permissions from the database (no empty combinations)
- High-contrast checkboxes visible in dark mode
- Organized by resource name and action type
- Clear role headers showing permission assignments

**Resource Permissions Examples**:
- `servers/read`: viewer, operator, admin, superadmin ✓
- `servers/admin`: admin, superadmin ✓
- `users/admin`: superadmin only ✓
- `volumes/read`: viewer, operator, admin, superadmin ✓

##### 4. System Audit Tab
Monitor authentication events and system access:
- **Login events** - Track successful logins with user, timestamp, and IP address
- **Failed login attempts** - Security monitoring for unauthorized access attempts
- **User management events** - Track user creation, deletion, and role changes
- **Filter options** - Filter by username, action, date range
- **90-day retention** - Audit logs maintained for compliance purposes

**Audit Events Tracked**:
- login / failed_login
- user_created / user_deleted
- role_changed
- logout

### Admin Panel Authentication
- **Access Control**: Admin panel is only visible to users with Admin or Superadmin roles
- **LDAP-based**: All users authenticate against the OpenLDAP server
- **Session management**: JWT tokens valid for 480 minutes (8 hours)
- **Audit logging**: All admin operations logged to auth_audit_log

### UI Configuration

#### Development Mode
```bash
cd pf9-ui
npm install
npm run dev  # Starts on http://localhost:5173
```

#### Production Build
```bash
cd pf9-ui
npm run build
npm run preview
```

### User Interface Features

#### Filtering Options
- Domain (Organization) selection
- Tenant (Project) filtering
- Status-based filtering
- Search functionality
- Date range filtering (where applicable)

#### Export Capabilities
- CSV export for all data types
- Real-time data export
- Formatted data with proper escaping
- Custom filename generation

---

## Data Collection & Reporting

### RVTools-style Reporting
The `pf9_rvtools.py` script provides comprehensive infrastructure reporting:

```bash
# Run inventory collection
python pf9_rvtools.py

# Options
python pf9_rvtools.py --mask-customer-data  # Anonymize sensitive data
python pf9_rvtools.py --debug               # Verbose logging
```

### Generated Reports
- **Excel workbook** with multiple sheets
- **CSV files** for each data type
- **Delta tracking** showing changes since last run
- **Summary statistics** with trend information

### Report Contents
1. **Summary** - High-level statistics and changes
2. **Domains** - Organization/domain information
3. **Projects** - Tenant/project details
4. **Servers** - Virtual machine inventory
5. **Volumes** - Block storage information
6. **Snapshots** - Volume snapshot details
7. **Networks** - Network infrastructure
8. **Hypervisors** - Physical host information
9. **Flavors** - VM template definitions
10. **Users** - User management and role assignments across all domains

### User Management Features
- **Multi-domain user collection**: Comprehensive user visibility across all 28 OpenStack domains
- **Role assignment tracking**: Monitors 100+ role assignments with automatic fallback methods
- **Activity monitoring**: Tracks user last seen timestamps and account status
- **Domain context**: Clear domain association for each user account
- **Role inference**: Intelligent role assignment when direct API collection fails
- **Real-time updates**: User data refreshed during each inventory collection

#### User Data Collected
- User identity (name, email, ID)
- Domain associations and project memberships
- Role assignments (admin, member, service roles)
- Account status (enabled/disabled)
- Activity timestamps (last seen, creation dates when available)
- User descriptions and display names

### Data Masking
For customer-safe reports, use the `--mask-customer-data` flag:
- Replaces sensitive names with hashes
- Preserves data relationships
- Maintains statistical accuracy

---

## Monitoring & Troubleshooting

### Real-Time Infrastructure Monitoring

#### Monitoring System Architecture
The Platform9 Management System now includes a comprehensive real-time monitoring solution:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Real-Time Monitoring Platform                    │
├────────────┬────────────┬────────────┬────────────┬───────────────┤
│ Host       │ Metrics    │ Cache      │Monitoring  │  Dashboard    │
│Collection  │Prometheus  │Storage     │   API      │     UI        │
│   Script   │Endpoints   │(JSON)      │(FastAPI)   │(React Tab)    │
├────────────┼────────────┼────────────┼────────────┼───────────────┤
│•Background │•node_export│•Persistent │•REST API   │•Live Metrics  │
│•Scheduled  │•port 9388  │•Mount Cache│•Port 8001  │•Auto-refresh  │
│•Multi-host │•CPU/Memory │•Docker Vol │•/metrics/* │•Summary Cards │
│•Automated  │•Storage    │•JSON Format│•Health     │•Host Tables   │
└────────────┴────────────┴────────────┴────────────┴───────────────┘
```

#### Key Components

1. **Host Metrics Collector** (`host_metrics_collector.py`)
   - Collects metrics from PF9 compute nodes every 2 minutes
   - Connects directly to node_exporter on port 9388
   - Processes CPU, memory, and storage utilization data
   - Stores data in persistent JSON cache file

2. **Monitoring API Service** (`monitoring/main.py`)
   - FastAPI service running on port 8001
   - Serves cached metrics via REST endpoints
   - Provides summary statistics and health checks
   - Independent from main API to prevent performance impact

3. **Background Automation** (`startup.ps1`)
   - Complete setup automation with zero manual intervention
   - Creates Windows scheduled task for metrics collection
   - Verifies all services and dependencies
   - Single-command startup and teardown

4. **Dashboard Integration** (React UI Monitoring Tab)
   - Real-time metrics display with auto-refresh
   - Color-coded utilization indicators
   - Manual refresh capability for immediate updates
   - Summary cards showing total hosts and average utilization

#### Configuration

**Environment Variables** (add to .env):
```bash
# Monitoring Configuration
PF9_HOSTS=203.0.113.10,203.0.113.11,203.0.113.12,203.0.113.13
METRICS_CACHE_TTL=60
```

**PF9 Host Requirements**:
- node_exporter running on port 9388 (standard Platform9 deployment)
- Network connectivity from management server to compute nodes
- No additional configuration required on PF9 hosts

#### Monitoring Operations

**Complete Automation**:
```powershell
# One-command setup
.\startup.ps1

# Stop all services
.\startup.ps1 -StopOnly
```

**Manual Operations**:
```bash
# Manual metrics collection (for testing)
python host_metrics_collector.py --once

# Check monitoring service health
curl http://localhost:8001/health

# Get real-time host metrics
curl http://localhost:8001/metrics/hosts

# Get summary statistics
curl http://localhost:8001/metrics/summary

# Verify scheduled task
schtasks /query /tn "PF9 Metrics Collection"
```

**Troubleshooting Monitoring**:
```bash
# Check if PF9 hosts are accessible
curl http://203.0.113.10:9388/metrics | head -20

# Check monitoring service logs
docker logs pf9_monitoring

# Verify cache file is updating
ls -la metrics_cache.json
cat metrics_cache.json | head -50

# Check Windows scheduled task status
schtasks /query /tn "PF9 Metrics Collection" /v
```

### Health Checks

#### Service Health
```bash
# API health
curl http://localhost:8000/health

# Database connectivity
docker exec pf9_db pg_isready -U pf9

# UI accessibility
curl -I http://localhost:5173
```

#### Container Status
```bash
# Check all containers
docker-compose ps

# View container logs
docker-compose logs pf9_api
docker-compose logs pf9_ui
docker-compose logs pf9_db
```

### Common Issues

#### Authentication Failures
**Symptoms**: API returns 401/403 errors
**Causes**: 
- Invalid Platform9 credentials
- Expired authentication tokens
- Network connectivity issues

**Solutions**:
```bash
# Verify credentials
docker-compose logs pf9_api | grep -i auth

# Test Platform9 connectivity
curl -k https://your-platform9-cluster.com/keystone/v3
```

#### Database Connection Issues
**Symptoms**: API returns 500 errors, database timeouts
**Solutions**:
```bash
# Restart database
docker-compose restart pf9_db

# Check database logs
docker-compose logs pf9_db

# Verify database connectivity
docker exec pf9_api psql -h db -U pf9 -d pf9_mgmt -c "SELECT 1;"
```

#### Memory Issues
**Symptoms**: Container restarts, OOM kills
**Solutions**:
```bash
# Check resource usage
docker stats

# Increase memory limits in docker-compose.yml
services:
  pf9_api:
    deploy:
      resources:
        limits:
          memory: 2G
```

### Log Analysis

#### API Logs
```bash
# Real-time monitoring
docker-compose logs -f pf9_api

# Error filtering
docker-compose logs pf9_api | grep ERROR
```

#### Database Logs
```bash
# PostgreSQL logs
docker-compose logs pf9_db

# Query performance
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT * FROM pg_stat_activity;"
```

---

## Maintenance & Updates

### Regular Maintenance Tasks

#### Daily Tasks
- Monitor container health
- Check disk space usage
- Review error logs

#### Weekly Tasks
- Database backup
- Performance review
- Security update check

#### Monthly Tasks
- Full system backup
- Certificate renewal (if applicable)
- Capacity planning review

### Update Procedures

#### Application Updates
```bash
# Pull latest changes
git pull origin main

# Rebuild containers
docker-compose build --no-cache

# Restart services
docker-compose down
docker-compose up -d
```

#### Database Updates
```bash
# Create backup before updates
docker exec pf9_db pg_dump -U pf9 pf9_mgmt > pre-update-backup.sql

# Apply schema changes (if any)
docker exec -i pf9_db psql -U pf9 pf9_mgmt < schema-updates.sql
```

### Backup Strategy

#### Automated Backup Script
```bash
#!/bin/bash
# daily-backup.sh
DATE=$(date +%Y%m%d)
BACKUP_DIR="/backups/pf9-mgmt"

mkdir -p $BACKUP_DIR

# Database backup
docker exec pf9_db pg_dump -U pf9 pf9_mgmt | gzip > $BACKUP_DIR/db-$DATE.sql.gz

# Volume backup
docker run --rm -v pf9-mngt_pgdata:/data -v $BACKUP_DIR:/backup alpine tar czf /backup/volumes-$DATE.tar.gz /data

# Cleanup old backups (keep 30 days)
find $BACKUP_DIR -name "*.gz" -mtime +30 -delete
```

---

## Code Quality Issues

### Critical Security Issues

#### 1. Credential Exposure
- **Location**: `docker-compose.yml`, `p9_common.py`
- **Issue**: Hardcoded production credentials
- **Risk**: HIGH - Complete infrastructure access
- **Fix**: Use environment variables and secrets management

#### 2. SQL Injection Risk
- **Location**: `api/main.py` various query functions
- **Issue**: Some dynamic SQL construction
- **Risk**: MEDIUM - Data exposure
- **Fix**: Use parameterized queries consistently

#### 3. CORS Configuration
- **Location**: `api/main.py`
- **Issue**: `allow_origins=["*"]` too permissive
- **Risk**: MEDIUM - Cross-origin attacks
- **Fix**: Restrict to specific domains

### Code Duplication Issues

#### 1. Configuration Management
- **Files**: `p9_common.py`, `docker-compose.yml`
- **Issue**: Hardcoded configuration values in multiple locations
- **Impact**: Maintenance overhead, security risk
- **Fix**: Centralize configuration with environment variables

#### 2. UI Component Duplication
- **Files**: Multiple versions in `src/arch/` directories
- **Issue**: Same components with slight variations
- **Impact**: Maintenance complexity
- **Fix**: Create reusable component library

### Performance Issues

#### 1. Database Connections
- **Issue**: New connection per request
- **Impact**: Poor scalability
- **Fix**: Implement connection pooling

#### 2. Inefficient Queries
- **Issue**: Some queries lack proper indexing
- **Impact**: Slow response times with large datasets
- **Fix**: Add database indexes on commonly filtered columns

### Documentation Issues

#### 1. Missing API Documentation
- **Issue**: No comprehensive API documentation
- **Impact**: Developer experience, integration difficulty
- **Fix**: Complete OpenAPI/Swagger documentation

#### 2. Deployment Documentation
- **Issue**: Basic deployment instructions only
- **Impact**: Production deployment challenges
- **Fix**: Comprehensive deployment guide with security considerations

---

## Recommended Improvements

### Security Enhancements

#### 1. Implement Proper Secret Management
```yaml
# docker-compose.yml with secrets
services:
  pf9_api:
    environment:
      PF9_PASSWORD_FILE: /run/secrets/pf9_password
    secrets:
      - pf9_password

secrets:
  pf9_password:
    file: ./secrets/pf9_password.txt
```

#### 2. Add Authentication & Authorization
```python
# Implement JWT-based authentication
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer

security = HTTPBearer()

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Implement authentication logic
    pass
```

#### 3. Input Validation Enhancement
```python
# Add comprehensive input validation
from pydantic import validator, Field

class ServerFilter(BaseModel):
    domain_name: Optional[str] = Field(None, regex=r'^[a-zA-Z0-9_-]+$')
    tenant_id: Optional[str] = Field(None, regex=r'^[a-f0-9-]{36}$')
```

### Performance Improvements

#### 1. Database Optimization
```sql
-- Add recommended indexes
CREATE INDEX CONCURRENTLY idx_servers_domain_tenant ON servers(domain_name, tenant_name);
CREATE INDEX CONCURRENTLY idx_servers_status ON servers(status);
CREATE INDEX CONCURRENTLY idx_volumes_project_id ON volumes(project_id);
CREATE INDEX CONCURRENTLY idx_networks_shared_external ON networks(is_shared, is_external);
```

#### 2. API Caching
```python
# Implement Redis caching
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache

@app.get("/domains")
@cache(expire=300)  # 5-minute cache
async def get_domains():
    pass
```

#### 3. Connection Pooling
```python
# Implement proper connection pooling
from psycopg2 import pool

db_pool = pool.ThreadedConnectionPool(
    minconn=1,
    maxconn=20,
    host=os.getenv("PF9_DB_HOST"),
    port=os.getenv("PF9_DB_PORT"),
    database=os.getenv("PF9_DB_NAME"),
    user=os.getenv("PF9_DB_USER"),
    password=os.getenv("PF9_DB_PASSWORD")
)
```

### Monitoring & Observability

#### 1. Application Metrics
```python
# Add Prometheus metrics
from prometheus_client import Counter, Histogram, generate_latest

REQUEST_COUNT = Counter('api_requests_total', 'Total API requests', ['method', 'endpoint'])
REQUEST_DURATION = Histogram('api_request_duration_seconds', 'API request duration')
```

#### 2. Health Checks Enhancement
```python
@app.get("/health/detailed")
async def detailed_health():
    return {
        "status": "ok",
        "database": await check_database_health(),
        "platform9": await check_platform9_connectivity(),
        "timestamp": datetime.utcnow().isoformat()
    }
```

#### 3. Structured Logging
```python
import structlog

logger = structlog.get_logger()

@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    
    logger.info(
        "api_request",
        method=request.method,
        url=str(request.url),
        status_code=response.status_code,
        duration=time.time() - start_time
    )
    return response
```

### Development Workflow Improvements

#### 1. Automated Testing
```python
# Add comprehensive test suite
import pytest
from fastapi.testclient import TestClient

def test_server_list():
    response = client.get("/servers")
    assert response.status_code == 200
    assert "items" in response.json()
```

#### 2. CI/CD Pipeline
```yaml
# .github/workflows/ci.yml
name: CI/CD
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run tests
        run: |
          docker-compose -f docker-compose.test.yml up --abort-on-container-exit
      - name: Security scan
        run: |
          docker run --rm -v $(pwd):/app securecodewarrior/docker-scout /app
```

#### 3. Code Quality Tools
```yaml
# Add pre-commit hooks
repos:
  - repo: https://github.com/psf/black
    rev: 22.3.0
    hooks:
      - id: black
  - repo: https://github.com/pycqa/flake8
    rev: 4.0.1
    hooks:
      - id: flake8
  - repo: https://github.com/pycqa/bandit
    rev: 1.7.4
    hooks:
      - id: bandit
```

---

## Conclusion

The Platform9 Management System provides valuable infrastructure visibility and management capabilities. However, several critical security and architectural improvements are needed before production deployment:

### Immediate Actions Required:
1. **Remove hardcoded credentials** from all configuration files
2. **Implement proper secret management**
3. **Restrict CORS policy** to specific origins
4. **Add authentication and authorization**
5. **Implement comprehensive input validation**

### Medium-term Improvements:
1. **Database optimization** with proper indexing
2. **Connection pooling** implementation
3. **Comprehensive monitoring** and alerting
4. **Automated testing** and CI/CD pipeline
5. **Code consolidation** to eliminate duplication

### Long-term Enhancements:
1. **Multi-cluster support** for complex environments
2. **Role-based access control** for different user types
3. **Advanced reporting** with business intelligence features
4. **Mobile-responsive interface** improvements
5. **Integration capabilities** with other management tools

This system has strong foundational architecture but requires security hardening and operational improvements before production use.