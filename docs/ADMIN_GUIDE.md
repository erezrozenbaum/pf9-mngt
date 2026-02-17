# Platform9 Management System - Administrator Guide

## Recent Major Enhancements

### Operational Metering (v1.15 + v1.15.1 Pricing Overhaul ✨)
- **📊 Metering Tab**: Comprehensive operational resource metering with 8 sub-tabs (Overview, Resources, Snapshots, Restores, API Usage, Efficiency, **Pricing**, Export)
- **Metering Worker**: `pf9_metering_worker` container collects resource, snapshot, restore, API usage, and efficiency metrics on a configurable interval (default 15 minutes). vCPU data resolved from flavors table
- **Resource Metering**: Per-VM tracking of vCPUs, RAM, disk allocation + actual usage (CPU%, RAM%, disk%), network I/O — deduplicated to latest record per VM
- **Snapshot Metering**: Snapshot count, total size, policy compliance tracking per collection cycle
- **Restore Metering**: Restore operation tracking (status, duration, mode, data transferred)
- **API Usage Metering**: Endpoint-level call counts, error rates, avg/p95/p99 latency
- **Efficiency Scoring**: Per-VM efficiency scores with classification (excellent/good/fair/poor/idle) based on CPU, RAM, disk utilization
- **Chargeback Export**: CSV export with per-tenant cost aggregation across all pricing categories: compute (flavor-based), storage per GB, snapshot per GB, restore per operation, volume, network — with TOTAL cost column
- **Multi-Category Pricing**: Unified pricing system with 7 categories (flavor, storage_gb, snapshot_gb, restore, volume, network, custom) — auto-populate flavors from system, set hourly + monthly rates
- **Filter Dropdowns**: Project and domain filters use dropdown selects populated from actual data via `/api/metering/filters`
- **6 CSV Exports**: Resources, snapshots, restores, API usage, efficiency, and chargeback reports
- **RBAC**: Admin = `metering:read`, Superadmin = `metering:read` + `metering:write` (config + pricing changes)
- **20 API Endpoints**: Config (GET/PUT), filters, overview, resources, snapshots, restores, api-usage, efficiency, pricing CRUD (5), sync-flavors + 6 export routes
- **DB Migration**: `db/migrate_metering.sql` — 8 tables (`metering_config`, `metering_resources`, `metering_snapshots`, `metering_restores`, `metering_api_usage`, `metering_quotas`, `metering_efficiency`, `metering_pricing`)

### LDAP Backup & MFA (v1.14 - NEW ✨)
- **📁 LDAP Backup**: Automated LDAP directory backups via `ldapsearch` → gzip LDIF export alongside existing database backups
  - Separate scheduling and retention for LDAP vs database targets
  - "Database Backup" and "LDAP Backup" trigger buttons in Backup tab
  - Target filter on backup history, LDAP-specific settings card
  - `backup_worker` container now includes `ldap-utils` for LDAP backup/restore
- **🔐 Multi-Factor Authentication (MFA)**: TOTP-based 2FA with Google Authenticator
  - Self-service MFA enrollment: scan QR code, verify with first TOTP code
  - 8 one-time backup recovery codes for account recovery
  - Two-step login: LDAP credentials → MFA code → full session JWT
  - "🔐 MFA" button in header for all users, admin can view all users' MFA status
  - API endpoints: `/auth/mfa/setup`, `/auth/mfa/verify-setup`, `/auth/mfa/verify`, `/auth/mfa/disable`, `/auth/mfa/status`, `/auth/mfa/users`
  - Dependencies: `pyotp` (TOTP), `qrcode[pil]` (QR generation)
  - DB Migration: `db/migrate_ldap_backup_mfa.sql` (new `user_mfa` table, LDAP columns in backup tables)

### Database Backup & Restore (v1.13 - NEW ✨)
- **💾 Backup Tab**: Automated database backup management with scheduling, retention, and one-click restore
- **Backup Worker**: New `pf9_backup_worker` container runs `pg_dump` on a daily/weekly schedule or on-demand
- **Backup Settings**: Enable/disable automation, set schedule type (manual/daily/weekly), UTC time, retention count & days, NFS path
- **Backup History**: Paginated list of all backup/restore jobs with status badges, file size, duration, and action buttons
- **One-Click Restore**: Restore the database from any completed backup (superadmin only) via confirmation dialog
- **Retention Enforcement**: Automatically deletes old backups beyond the configured count or age
- **RBAC**: `backup:read`/`backup:write` for Admin, `backup:admin` for Superadmin
- **DB Migration**: `db/migrate_backup.sql` for existing databases (2 new tables: `backup_config`, `backup_history`)
- **Docker**: New `backup_worker` service in `docker-compose.yml` with PostgreSQL 16 image, NFS volume mount
- **Env Vars**: `NFS_BACKUP_PATH`, `BACKUP_VOLUME`, `BACKUP_POLL_INTERVAL`

### Multi-User Concurrency (v1.12 - NEW ✨)
- **Gunicorn + 4 Workers**: API now runs 4 parallel uvicorn worker processes via Gunicorn for 10+ concurrent users
- **Database Connection Pool**: Centralized `ThreadedConnectionPool` (db_pool.py) replaces per-request connections — min 2, max 10 per worker
- **Thread-Safe Metrics**: `PerformanceMetrics` class now uses `threading.Lock` for safe concurrent access
- **97 Connection Leaks Fixed**: All endpoint handlers converted to `with get_connection() as conn:` context manager
- **Configurable Pool**: `DB_POOL_MIN_CONN` / `DB_POOL_MAX_CONN` env vars for tuning

### Email Notifications (v1.11)
- **🔔 Notifications Tab**: Per-user email notification preferences, delivery history, and admin SMTP settings
- **Event Types**: Drift alerts, snapshot failures, compliance violations, and tenant health score drops
- **Notification Worker**: Background container (`pf9_notification_worker`) polls DB every 120s for new events
- **Daily Digest**: Configurable daily summary email aggregating all events from the past 24 hours
- **SMTP Support**: Both authenticated and unauthenticated SMTP relay, optional TLS
- **HTML Templates**: 6 Jinja2 templates (drift, snapshot, compliance, health, digest, generic)
- **7 API Endpoints**: SMTP status, preferences CRUD, delivery history, test email, admin stats
- **RBAC**: `notifications:read`/`notifications:write` for all roles, `notifications:admin` for Admin/Superadmin
- **DB Migration**: `db/migrate_notifications.sql` for existing databases (4 new tables)
- **UI Features**: 3 sub-tabs (Preferences, History, Settings), test email button, dark mode support

### Tenant Health View (v1.10 - NEW ✨)
- **🏥 Tenant Health Tab**: Per-project health scoring with 0–100 health score, summary cards, sortable/searchable tenant table, and click-to-expand detail panels
- **Database View**: `v_tenant_health` SQL view aggregating per-project health metrics from all resource tables
- **Health Score**: Starts at 100 with deductions for error VMs/volumes/snapshots, low compliance, and critical/warning drift events
- **3 API Endpoints**: Overview (all tenants, filterable/sortable), detail (single tenant with resource breakdown), trends (daily drift/snapshot counts for charts)
- **RBAC**: `tenant_health:read` for all roles, `tenant_health:admin` for Admin/Superadmin
- **UI Features**: Summary cards, sortable table, detail panel with status bars, volume table, drift timeline, CSV export, domain/tenant filter integration, dark mode
- **DB Migration**: `db/migrate_tenant_health.sql` for existing databases (idempotent — safe to re-run)

### Drift Detection Engine (v1.9 - NEW ✨)
- **🔍 Drift Detection Tab**: Dedicated UI tab for viewing, filtering, and managing infrastructure drift events
- **24 Built-In Rules**: Monitors field-level changes across 8 resource types during inventory sync
  - **Servers**: flavor_id, status, vm_state, hypervisor_hostname
  - **Volumes**: status, size, volume_type, server_id
  - **Networks**: admin_state_up, shared
  - **Subnets**: gateway_ip, cidr, enable_dhcp
  - **Ports**: device_id, mac_address, status
  - **Floating IPs**: port_id, router_id, status
  - **Security Groups**: description
  - **Snapshots**: status, size
- **Detection Hook**: Integrated into `db_writer.py` — automatically detects field changes during each inventory sync cycle
- **Database Tables**: `drift_rules` (24 built-in rules) and `drift_events` (detected changes)
- **7 API Endpoints**: Summary, event listing, event detail, acknowledge, bulk acknowledge, rules list, rule toggle
- **RBAC**: `drift:read` for all roles, `drift:write` (acknowledge/toggle rules) for Operator and above
- **Domain/Tenant Filtering**: Events respect the caller's domain and tenant scope
- **CSV Export**: Export filtered drift events to CSV from the tab toolbar
- **Bulk Acknowledge**: Select and acknowledge multiple events in one action
- **Rules Management Panel**: Enable/disable individual detection rules from the UI
- **DB Migration**: `db/migrate_drift_detection.sql` for existing databases (idempotent — safe to re-run)

### Branding & Login Customization (v1.8 - NEW ✨)
- **White-Label Login Page**: Two-column layout with branded hero panel (title, description, feature highlights, stats)
- **Admin Branding Tab**: "🎨 Branding & Login Page Settings" in Admin Panel — company name, subtitle, colors, logo upload, hero content
- **Color Customization**: Primary and secondary color pickers with live gradient preview
- **Logo Upload**: Supports PNG, JPEG, GIF, SVG, WebP (max 2 MB) with instant preview and removal
- **Feature Highlights**: Configurable checklist shown on the login hero panel (add/remove items)
- **Tab Drag-and-Drop**: Users can reorder tabs via drag-and-drop; order persists per-user (localStorage + backend)
- **User Preferences API**: Per-user settings (tab order, etc.) stored in `user_preferences` table
- **Dark Mode Fixes**: Comprehensive dark mode fixes across login page, branding settings, restore audit buttons, and snapshot policy buttons

### Security Groups Management (v1.7 - NEW ✨)
- **Full CRUD**: Create, view, and delete security groups and firewall rules from the UI
- **🔒 Security Groups Tab**: Dedicated tab with list/detail layout, filter/sort/pagination, color-coded ingress/egress rule badges
- **Detail Panel**: Shows all rules (ingress/egress), attached VMs, and attached networks
- **Admin Operations**: Create security groups with project picker, add/delete individual rules (direction, protocol, ports, remote prefix)
- **Rule Template Presets**: One-click quick-add buttons for common firewall rules — SSH, HTTP, HTTPS, RDP, ICMP, DNS
- **Export CSV**: Export current filtered security groups list to CSV from the tab toolbar
- **Restore Integration**: Security group multi-select picker in restore wizard; "default" SG auto-selected; selected SGs attached to restored VM ports
- **API Endpoints**: 7 new endpoints (list, detail, rules list, CRUD for groups and rules)
- **DB Migration**: `db/migrate_security_groups.sql` for existing databases (idempotent — safe to re-run)

### Monitoring & Restore Audit (v1.4 - NEW ✨)
- **Restore Audit Tab**: Full audit trail for restore operations with search, filters, pagination, step-level drill-down, CSV export
- **Monitoring hostname resolution**: Hosts displayed by friendly name via `PF9_HOST_MAP` env var (API/DNS fallback)
- **Monitoring data fixes**: VM IPs, storage metrics, network rx/tx bytes now display correctly
- **Docker cache directory mount**: Replaced single-file bind mount with `./monitoring/cache:/tmp/cache` for reliable Windows sync
- **MONITORING_BASE config**: UI supports `VITE_MONITORING_BASE` for monitoring service URL override

### Snapshot Restore (v1.2 - NEW ✨✨✨)
- **Full VM Restore from Snapshot**: Restore boot-from-volume VMs from Cinder snapshots
  - **NEW mode**: Create restored VM alongside existing (side-by-side, non-destructive)
  - **REPLACE mode**: Delete existing VM and recreate from snapshot (superadmin-only, destructive)
  - **IP strategies**: NEW_IPS (DHCP), TRY_SAME_IPS (best-effort), SAME_IPS_OR_FAIL (strict)
  - **3-Screen UI Wizard**: Select VM → Configure Restore → Execute/Progress with real-time updates
  - **8 API Endpoints**: Plan, execute, cancel, list jobs, get config, browse snapshots
  - **RBAC**: Viewer/Operator=read, Admin=write (NEW mode), Superadmin=admin (REPLACE mode)
  - **Cross-Tenant**: Uses same service user mechanism as snapshot system
  - **Safety Features**: Dry-run mode, destructive confirmation string, stale job recovery, volume cleanup option
  - **Feature Toggle**: Disabled by default — set `RESTORE_ENABLED=true` to activate
- See [RESTORE_GUIDE.md](RESTORE_GUIDE.md) for full documentation

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
- **LDAP Integration**: Production OpenLDAP authentication (configured via `LDAP_DOMAIN` env var)
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

### Database Schema Overview (29+ Tables)

#### Authentication & Authorization (3 tables)
- **user_roles**: User-to-role mappings with active status tracking
- **role_permissions**: Resource-level permission matrix (role → resource → action)
- **auth_audit_log**: Authentication event logging (login, logout, permission denied) with 90-day retention
- **user_sessions**: JWT session tracking with IP address and user agent
- **app_settings**: Key/value store for application-wide settings (branding colors, company name, hero content)
- **user_preferences**: Per-user preferences (tab order, UI settings) with JSONB value column

#### Core Identity & Organization (3 tables)
- **domains**: OpenStack domains with JSONB metadata and foreign key relationships
- **projects**: Projects/tenants with domain associations and comprehensive metadata
- **users**: User accounts with domain associations, role tracking, and activity timestamps

#### Compute Infrastructure (4 tables)
- **hypervisors**: Physical compute nodes with resource utilization and status tracking
- **servers**: Virtual machines with complete lifecycle, flavor associations, project relationships, actual disk size (from attached volumes for boot-from-volume VMs), and per-host CPU/RAM/disk utilization from hypervisors
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

#### Drift Detection (2 tables)
- **drift_rules**: 24 built-in detection rules covering 8 resource types, with enabled/disabled toggle per rule
- **drift_events**: Detected field-level changes with resource context, severity, old/new values, and acknowledgement tracking

#### Tenant Health (1 view)
- **v_tenant_health** (View): Aggregates per-project health metrics from all resource tables — server/volume/snapshot/network counts, compliance percentage, drift events, and computed health score (0–100)

#### Notifications (4 tables)
- **notification_channels**: Available notification delivery channels (email, webhook, etc.)
- **notification_preferences**: Per-user, per-event-type subscription settings with severity filtering and delivery mode
- **notification_log**: Complete delivery history with status tracking, error messages, and retry counts
- **notification_digests**: Daily digest tracking to prevent duplicate sends

#### Metering (7 tables)
- **metering_config**: Single-row global settings (enabled, interval, retention, cost model per resource type)
- **metering_resources**: Periodic per-VM resource snapshots (vCPUs, RAM, disk allocation + actual usage, network I/O)
- **metering_snapshots**: Snapshot metering records (size, policy, compliance status per collection cycle)
- **metering_restores**: Restore operation metering (status, duration, mode, data transferred)
- **metering_api_usage**: API endpoint usage tracking (total calls, error count, avg/p95/p99 latency)
- **metering_quotas**: Per-project resource quota tracking (allocated vs. used for vCPUs, RAM, storage)
- **metering_efficiency**: Per-VM efficiency scores with classification (excellent/good/fair/poor/idle)

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
5. [Drift Detection](#drift-detection)
6. [Tenant Health Monitoring](#tenant-health-monitoring)
7. [Production Features](#production-features)
   - [Startup Configuration Validation](#1-startup-configuration-validation-)
   - [API Performance Metrics](#2-api-performance-metrics-)
   - [Structured Logging](#3-structured-logging-centralized-logging-foundation-)
   - [Automated Metrics Collection](#4-automated-metrics-collection-)
8. [Core Components Deep Dive](#core-components-deep-dive)
9. [Installation & Deployment](#installation--deployment)
10. [Security Considerations](#security-considerations)
11. [Database Management](#database-management)
12. [API Operations](#api-operations)
13. [UI Management](#ui-management)
14. [Data Collection & Reporting](#data-collection--reporting)
15. [Monitoring & Troubleshooting](#monitoring--troubleshooting)
16. [Maintenance & Updates](#maintenance--updates)
17. [Code Quality Issues](#code-quality-issues)
18. [Recommended Improvements](#recommended-improvements)

---

## System Overview

The Platform9 Management System is a comprehensive OpenStack infrastructure management portal with enterprise LDAP authentication and role-based access control. Designed specifically for Platform9 environments, it provides secure multi-tenant resource administration, real-time inventory, automated snapshot management, and compliance reporting.

### Core Capabilities
- **Enterprise Authentication**: LDAP integration with JWT token management
- **Role-Based Access Control**: 4-tier permission system with automatic enforcement
- **Audit & Compliance**: 90-day authentication event tracking and permission logging
- **Comprehensive Inventory Management**: Real-time tracking of VMs, volumes, snapshots, networks, subnets, ports, floating IPs, security groups, security group rules, hypervisors, flavors, and images
- **Automated Snapshot Management**: Policy-driven snapshot creation with cross-tenant support via dedicated service user, configurable retention periods, and hourly scheduling (default 60 min)
- **On-Demand Snapshot Pipeline**: "Sync & Snapshot Now" UI button and `POST /snapshot/run-now` API for immediate policy assignment and snapshot creation
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
- **Administrative Functions**: Create/delete flavors, networks, and security groups (permission-controlled)
- **Database-Driven Architecture**: PostgreSQL persistence with full relational integrity
- **Container-Native Deployment**: Docker Compose orchestration with LDAP server

## Authentication & Authorization

### LDAP Integration

The system uses OpenLDAP for enterprise user authentication:
- **LDAP Server**: Port 389
- **Base DN**: Set explicitly via `LDAP_BASE_DN` env var, or derived from `LDAP_DOMAIN` by `deployment.ps1` (e.g., `dc=company,dc=com`)
- **User DN**: `ou=users,<LDAP_BASE_DN>` (set via `LDAP_USER_DN`)
- **Group DN**: `ou=groups,<LDAP_BASE_DN>` (set via `LDAP_GROUP_DN`)
- **Admin DN**: `cn=admin,<LDAP_BASE_DN>` (auto-composed in docker-compose.yml)
- **Admin Password**: Configured via `LDAP_ADMIN_PASSWORD` environment variable

> **Important:** `LDAP_BASE_DN` must be set in `.env` for the LDAP container healthcheck to work. The `deployment.ps1` wizard auto-generates this from `LDAP_DOMAIN`.

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
- **Cache**: Persistent storage in `monitoring/cache/metrics_cache.json`
- **Docker Mount**: Directory mount `./monitoring/cache:/tmp/cache` syncs cache to monitoring container
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
Get-Content monitoring\cache\metrics_cache.json | ConvertFrom-Json
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
   ls monitoring\cache\metrics_cache.json
   ```

2. **Host connection timeouts**:
   ```powershell
   # Test node_exporter accessibility
   curl http://<PF9_HOST_IP>:9388/metrics
   
   # Check network connectivity
   Test-NetConnection <PF9_HOST_IP> -Port 9388
   ```

3. **Monitoring service errors**:
   ```bash
   # Check monitoring container logs
   docker-compose logs pf9_monitoring
   
   # Verify cache file is mounted
   docker-compose exec pf9_monitoring ls -la /tmp/cache/metrics_cache.json
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
- `GET /history/recent-changes` - Recent infrastructure changes (filterable by hours, limit)
- `GET /history/most-changed` - Most frequently changed resources
- `GET /history/by-timeframe` - Changes by time period
- `GET /history/resource/{type}/{id}` - Resource-specific history timeline (supports `deletion` type — queries `deletions_history` with original resource type, reason, and raw state)
- `GET /history/compare/{type}/{id}` - Compare two history snapshots (requires `current_hash` and `previous_hash` query params)
- `GET /history/details/{type}/{id}` - Detailed change information with change sequencing
- `GET /audit/compliance-report` - Comprehensive compliance analysis
- `GET /audit/change-patterns` - Change pattern and velocity analysis
- `GET /audit/resource-timeline/{type}` - Resource type timeline analysis

**History Tab UI Features**:
- Filter recent changes by resource type, project, domain, and free-text search (name/ID/description)
- Sortable column headers: Time, Type, Resource, Project, Domain, Change Description (ascending/descending)
- Deletion records surfaced with 🗑 badge; "View Details" shows deletion timeline from `deletions_history`
- "Most Frequently Changed Resources" section with direct history navigation
- Configurable timeframe: 1 hour, 24 hours, 3 days, 1 week

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

### Python Scripts (9 Core Scripts)
1. **pf9_rvtools.py** - Main inventory collection (542 lines)
2. **snapshots/p9_auto_snapshots.py** - Automated snapshot management with cross-tenant support (1068 lines)
3. **snapshots/snapshot_service_user.py** - Service user management for cross-tenant snapshots (266 lines)
4. **snapshots/p9_snapshot_compliance_report.py** - Compliance reporting (749 lines)
5. **snapshots/p9_snapshot_policy_assign.py** - Policy management (454 lines)
6. **p9_common.py** - Shared utilities and API clients (893 lines)
7. **db_writer.py** - Database operations (1113 lines)
8. **test_db_write.py** - Database testing utilities
9. **api/pf9_control.py** - Platform9 API client

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
# PF9_HOST_MAP=203.0.113.10:host-01,203.0.113.11:host-02
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
python snapshots/p9_auto_snapshots.py     # Snapshot automation (uses service user for cross-tenant)
python snapshots/p9_snapshot_compliance_report.py  # Compliance reporting
```

**Features when running standalone**:
- ✅ Platform9 API access and data collection
- ✅ Excel/CSV report generation
- ✅ Automatic .env file loading
- ✅ Cross-tenant snapshots via service user (configured via `SNAPSHOT_SERVICE_USER_EMAIL`)
- ❌ No database storage (optional)
- ❌ No web UI access

---

## Drift Detection

### Overview
The Drift Detection Engine (v1.9) automatically monitors infrastructure field-level changes during each inventory sync cycle. When `db_writer.py` upserts a resource and detects that a monitored field has changed, it creates a drift event in the `drift_events` table based on the matching rule in `drift_rules`.

### How It Works
1. **Detection Hook**: During each inventory sync, `db_writer.py` compares incoming resource data against the current database state
2. **Rule Matching**: If a monitored field has changed, the system checks `drift_rules` for an enabled rule matching the resource type and field
3. **Event Creation**: A `drift_event` record is created with the old value, new value, severity, and resource context (domain, tenant)
4. **UI Notification**: The "🔍 Drift Detection" tab displays events with filtering, sorting, and acknowledgement controls

### Database Tables
- **`drift_rules`**: 24 built-in rules covering 8 resource types. Each rule specifies the resource type, field name, severity, and enabled status
- **`drift_events`**: Stores detected changes with `resource_type`, `resource_id`, `resource_name`, `field_name`, `old_value`, `new_value`, `severity`, `detected_at`, `acknowledged`, `acknowledged_by`, `acknowledged_at`, `domain_name`, `tenant_name`

**Migration**: Run `db/migrate_drift_detection.sql` on existing databases. The migration is idempotent — safe to re-run.

### Viewing Drift Events
1. Navigate to the **🔍 Drift Detection** tab in the UI
2. Use filters to narrow by resource type, severity, acknowledgement status, domain, or tenant
3. Use the search box for free-text search across resource name/ID
4. Click an event row to view full detail (old/new values, rule info, timestamps)

### Acknowledging Drift
- **Single**: Click the acknowledge button on any event row or detail view
- **Bulk**: Select multiple events via checkboxes, then click "Acknowledge Selected"
- Acknowledged events record the user and timestamp, and can be filtered out of the default view

### Managing Rules
1. Open the **Rules Management** panel in the Drift Detection tab
2. Toggle individual rules on/off to control which field changes generate events
3. Rules cover 8 resource types with 24 fields total:

| Resource Type | Monitored Fields |
|---------------|-----------------|
| Server | flavor_id, status, vm_state, hypervisor_hostname |
| Volume | status, size, volume_type, server_id |
| Network | admin_state_up, shared |
| Subnet | gateway_ip, cidr, enable_dhcp |
| Port | device_id, mac_address, status |
| Floating IP | port_id, router_id, status |
| Security Group | description |
| Snapshot | status, size |

### Exporting Drift Data
Click **Export CSV** in the tab toolbar to download the current filtered view of drift events. The export respects all active filters (resource type, severity, domain, tenant, acknowledged status).

### RBAC Permissions
| Permission | Roles | Description |
|------------|-------|-------------|
| `drift:read` | Viewer, Operator, Admin, Superadmin | View drift events, summary, and rules |
| `drift:write` | Operator, Admin, Superadmin | Acknowledge events, enable/disable rules |

---

## Tenant Health Monitoring

### Overview
The Tenant Health feature (v1.10) provides a consolidated view of per-project health across your entire OpenStack environment. A database view (`v_tenant_health`) aggregates metrics from all resource tables into a single health score (0–100) per tenant, displayed in the **🏥 Tenant Health** UI tab.

### How Health Scores Work
Each tenant starts with a score of **100**. Deductions are applied for:
- **Error VMs/Volumes/Snapshots**: Resources in error state reduce the score
- **Low Compliance**: Snapshot compliance percentage below threshold causes deductions
- **Critical/Warning Drift**: Recent drift events of critical or warning severity reduce the score

**Health Status Thresholds**:
| Status | Score Range | Color |
|--------|-------------|-------|
| Healthy | 80–100 | Green |
| Warning | 50–79 | Yellow/Orange |
| Critical | 0–49 | Red |

### Database View
The `v_tenant_health` SQL view aggregates per-project health metrics from all resource tables:
- Server counts (total, active, error)
- Volume counts (total, in-use, error)
- Snapshot counts and compliance percentage
- Network counts
- Drift event counts (total, critical, warning)
- Computed health score with deductions

**Migration**: Run `db/migrate_tenant_health.sql` on existing databases. The migration is idempotent — safe to re-run.

### Using the Tenant Health Tab
1. Navigate to the **🏥 Tenant Health** tab in the UI
2. **Summary Cards**: View aggregate counts of healthy, warning, and critical tenants plus average health score
3. **Tenant Table**: Sortable and searchable table of all tenants with health scores
   - Sort by: health score, project name, domain name, total servers, total volumes, total networks, total drift events, compliance percentage
   - Filter by domain using the domain filter dropdown
   - Search by tenant or domain name
4. **Detail Panel**: Click any tenant row to open a detail panel showing:
   - Resource status bars (VMs, volumes, snapshots by status)
   - Top volumes table
   - Recent drift event timeline
5. **CSV Export**: Export the current filtered tenant health data to CSV
6. **Dark Mode**: Full dark mode support with theme-aware styling

### RBAC Permissions
| Permission | Roles | Description |
|------------|-------|-------------|
| `tenant_health:read` | Viewer, Operator, Admin, Superadmin | View tenant health overview, detail, and trends |
| `tenant_health:admin` | Admin, Superadmin | Administrative access to tenant health data |

### API Endpoints
```python
GET  /tenant-health/overview              # All tenants with health scores (filterable, sortable)
GET  /tenant-health/{project_id}          # Full detail for one tenant
GET  /tenant-health/trends/{project_id}   # Daily drift/snapshot trend counts for charts
```

### Troubleshooting

**No tenant health data appearing**:
```bash
# Verify the v_tenant_health view exists
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM v_tenant_health;"

# If missing, run the migration
docker exec -i pf9_db psql -U pf9 -d pf9_mgmt < db/migrate_tenant_health.sql

# Verify projects table is populated (v_tenant_health depends on it)
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM projects;"
```

**Health scores all showing 100**:
```bash
# Check if resource data is populated
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM servers;"
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM volumes;"

# Run an inventory sync to populate data
python pf9_rvtools.py
```

**Health scores seem incorrect**:
```bash
# Inspect raw view data for a specific tenant
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c \
  "SELECT project_name, health_score, total_servers, error_servers, compliance_pct, total_drift_events FROM v_tenant_health ORDER BY health_score ASC LIMIT 10;"
```

### API Endpoints
```python
GET  /drift/summary                    # Aggregate drift overview
GET  /drift/events                     # List drift events (filtered/paginated)
GET  /drift/events/{id}                # Single drift event detail
PUT  /drift/events/{id}/acknowledge    # Acknowledge single event
PUT  /drift/events/bulk-acknowledge    # Bulk acknowledge events
GET  /drift/rules                      # List 24 built-in rules
PUT  /drift/rules/{rule_id}            # Enable/disable a rule
```

### Troubleshooting

**No drift events appearing**:
```bash
# Verify drift_rules table is populated
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM drift_rules;"
# Should return 24

# Check if rules are enabled
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT resource_type, field_name, enabled FROM drift_rules;"

# Verify detection hook is active — run an inventory sync
python pf9_rvtools.py

# Check for drift events after sync
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c "SELECT COUNT(*) FROM drift_events;"
```

**Too many drift events**:
```bash
# Disable noisy rules via API
curl -X PUT http://localhost:8000/drift/rules/<rule_id> \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'

# Or disable directly in database
docker exec pf9_db psql -U pf9 -d pf9_mgmt -c \
  "UPDATE drift_rules SET enabled = false WHERE rule_name = 'Server Migration Detected';"
```

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
- **Cache**: `monitoring/cache/metrics_cache.json` (persistent across restarts)
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

##### 5. Branding Tab (NEW ✨)
Customize the application’s login page and company identity:
- **Company Name & Subtitle** — Displayed on the login page header
- **Primary & Secondary Colors** — Color pickers with hex input; used for login page gradient and UI accents
- **Logo Upload** — Upload a company logo (PNG, JPEG, GIF, SVG, WebP; max 2 MB) with instant preview
- **Login Hero Title & Description** — Customizable hero panel text on the right side of the login page
- **Feature Highlights** — Add/remove checklist items displayed with checkmarks on the login hero panel
- **Live Preview** — Gradient preview bar shows the current primary→secondary color combination
- **Persistence** — All settings stored in the `app_settings` database table and take effect immediately for new visitors
- **RBAC** — Only Admin and Superadmin users can access this tab

### Notifications Tab
The Notifications tab allows users to manage email alert preferences:
- **Preferences Sub-Tab** — Toggle notifications for each event type (drift, snapshots, compliance, health), set minimum severity level, choose delivery mode (immediate or digest)
- **History Sub-Tab** — Paginated log of all sent notifications with status (sent/failed/pending), timestamps, and event details
- **Settings Sub-Tab** (Admin only) — SMTP connection status, notification delivery statistics, and test email button
- **RBAC** — All authenticated users can manage their own preferences; admin statistics require Admin/Superadmin role

### Tab Drag-and-Drop Reordering
Users can customize the order of navigation tabs:
- **Drag-and-Drop** — Click and drag any tab to reorder; visual drop indicator shows placement
- **Persistence** — Tab order saved to `localStorage` and synced to backend (`user_preferences` table) per user
- **Reset** — Click the "↩" button to restore the default 27-tab order
- **Data-Driven** — All tabs defined in `DEFAULT_TAB_ORDER` array with id, label, icon, category, RBAC permission, and feature-toggle metadata

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
# Map host IPs to friendly hostnames for monitoring display
# PF9_HOST_MAP=203.0.113.10:host-01,203.0.113.11:host-02
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
ls -la monitoring/cache/metrics_cache.json
cat monitoring/cache/metrics_cache.json | head -50

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