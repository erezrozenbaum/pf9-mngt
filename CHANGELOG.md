# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 2026-03-01

### Added
- **Snapshot Restore Audit Tab** (`SnapshotRestoreAudit.tsx`) — full audit trail UI for restore operations
  - Searchable, filterable, paginated table of all restore jobs
  - Expandable rows with step-level drill-down (volume, network, security group actions)
  - Status / mode / date-range filters
  - Duration calculation and color-coded status badges (completed / failed / running / pending)
  - CSV export of filtered audit data
  - Auto-refresh while jobs are running
  - Full dark-mode support (`SnapshotRestoreAudit.css`)
- **MONITORING_BASE config** — `config.ts` now exports `MONITORING_BASE` (via `VITE_MONITORING_BASE` env var, default `http://localhost:8001`) alongside `API_BASE`
- **PF9_HOST_MAP environment variable** — maps host IPs to friendly hostnames for monitoring display (e.g. `10.0.1.10:host-01,10.0.1.11:host-02`)

### Fixed
- **Monitoring — VM network data showing N/A** — zero-valued `network_rx_bytes` / `network_tx_bytes` were treated as falsy in UI; fixed truthy checks to use explicit `!= null` comparisons
- **Monitoring — VM IPs showing N/A** — enhanced `/monitoring/vm-metrics` endpoint to parse OpenStack `addresses` JSON for real VM IP addresses
- **Monitoring — storage data incorrect** — fixed field mapping `storage_allocated_gb` → `storage_total_gb` in VM metrics endpoint
- **Monitoring — host network data missing** — broadened network device filter in collector to capture all physical interfaces
- **Monitoring — hostnames displayed as raw IPs** — added `_build_hostname_map()` to host metrics collector; resolves hostnames via `PF9_HOST_MAP` env var, PF9 API fallback, or reverse DNS
- **Monitoring — cache not syncing to container** — Docker single-file bind mount on Windows doesn't reliably propagate file rewrites; switched to directory mount (`./monitoring/cache:/tmp/cache`)

### Enhanced
- **Host metrics collector** — added `.env` manual parser fallback (no `python-dotenv` dependency required), hostname resolution pipeline (PF9_HOST_MAP → API → rDNS), updated cache output path to `monitoring/cache/metrics_cache.json`
- **Monitoring service** — reads cache from `/tmp/cache/metrics_cache.json`, creates cache directory on startup
- **monitoring/entrypoint.sh** — creates `/tmp/cache` directory, updated cache path references
- **docker-compose.yml** — monitoring service uses directory mount; removed stale API file-mount for `metrics_cache.json`
- **.env.example** — added `PF9_HOST_MAP` and `VITE_MONITORING_BASE` variable documentation

### Security
- **Anonymised production IPs** in `host_metrics_collector.py` code comment — replaced real infrastructure IPs/hostnames with `10.0.1.10:host-01` examples

## [1.3.0] - 2026-02-15

### Added
- **VM Host Utilization** — Servers table now displays per-host CPU, RAM, and disk utilization alongside each VM
  - Mini progress bars with color coding: green (<65%), amber (65–85%), red (>85%)
  - Hover tooltips show exact used/total values (e.g., "36/48 vCPUs allocated on host-04")
  - Hypervisor hostname column shows which physical host each VM runs on
  - Data sourced from `hypervisors` table joined on `OS-EXT-SRV-ATTR:hypervisor_hostname`
- **DB-backed monitoring endpoints** — three new API endpoints (`/monitoring/host-metrics`, `/monitoring/vm-metrics`, `/monitoring/summary`) source data from the `hypervisors` table when the external monitoring service returns empty results
- **Monitoring UI fallback** — Monitoring tab now tries the monitoring service first, falls back to DB-backed endpoints automatically
- **Restore RBAC permissions** — `restore:read`, `restore:write`, `restore:admin` entries added to both API and UI permission fallbacks, and to `MAIN_UI_RESOURCES` whitelist
- **Full RBAC permission seed** — init.sql now seeds `monitoring`, `history`, `audit` permissions for all four roles; existing DBs can be updated via the included migration INSERT
- **LDAP_BASE_DN** exposed as explicit environment variable in LDAP container for healthcheck reliability

### Fixed
- **VM Disk (GB) showing 0** for boot-from-volume VMs — now calculates actual disk from `SUM(attached_volumes.size_gb)` when flavor disk is 0
- **Volume auto_snapshot always "Disabled"** — removed hardcoded sample-data override in UI that matched volume names; now displays real metadata from API
- **LDAP container unhealthy** — docker-compose healthcheck used unescaped `$` variables (consumed by compose substitution); fixed with `$$` escaping and added `LDAP_BASE_DN` to container environment
- **Monitoring container unhealthy** — healthcheck used `curl` which is not installed in the Python-slim image; replaced with `python -c "import urllib.request; ..."`
- **Snapshot Restore "Feature Disabled"** — `RESTORE_ENABLED` was missing from `.env`; added to `.env` and `.env.example`
- **LDAP_ADMIN_DN warning** during `docker-compose up` — resolved by `$$` escaping in healthcheck (same fix as LDAP unhealthy)
- **Permissions tab showing only restore entries** — DB volume persisted from before init.sql had comprehensive seed data; added 85 missing permission rows

### Security
- **Removed default password fallback `"admin"`** in deployment.ps1 — now fails loudly if `DEFAULT_ADMIN_PASSWORD` is unset
- **Removed hardcoded demo user passwords** (`viewer123`/`operator123`) in setup_ldap.ps1 — now reads from `VIEWER_PASSWORD`/`OPERATOR_PASSWORD` env vars, or generates random passwords if unset
- **Removed credential exposure in README.md** — pgAdmin credentials now reference `.env` configuration
- **pgAdmin default password removed** — docker-compose now requires `PGADMIN_PASSWORD` to be set (fails at startup if missing)
- **Masked LDAP admin password** in setup_ldap.ps1 console output
- **Fixed wrong LDAP base DN** (`dc=platform9,dc=local`) hardcoded in deployment.ps1 — now uses `LDAP_BASE_DN` env var
- **Centralised API_BASE URL** — all 6 UI source files now import from `src/config.ts` using `VITE_API_BASE` env var (defaults to `http://localhost:8000`)
- **SSH host key verification** — replaced `paramiko.AutoAddPolicy()` with `WarningPolicy` + known_hosts file support
- **Removed hardcoded `C:\Reports\Platform9`** paths — docker-compose.yml uses `PF9_REPORTS_DIR` env var, Python code uses cross-platform `~/Reports/Platform9` default
- **Doc placeholder passwords** replaced with obviously invalid `<GENERATE: openssl ...>` tokens
- **Anonymised internal hostname** (`cloud-kvm04` → `host-04`) in CHANGELOG.md

### Enhanced
- **Servers API response** — now returns `hypervisor_hostname`, `host_vcpus_used/total`, `host_ram_used_mb/total_mb`, `host_disk_used_gb/total_gb`, `host_running_vms`, and `disk_gb` (actual disk from volumes)
- **Servers UI table** — expanded from 10 to 14 columns: added Host, Host CPU, Host RAM, Host Disk utilization bars
- **deployment.ps1** — `.env.template` now includes `LDAP_BASE_DN`, `DEFAULT_ADMIN_USER`, `DEFAULT_ADMIN_PASSWORD`, `RESTORE_ENABLED`
- **Documentation updates**: API_REFERENCE.md (servers response schema), ARCHITECTURE.md, ADMIN_GUIDE.md (LDAP Base DN docs), DEPLOYMENT_GUIDE.md (LDAP DN vars, healthcheck scripts, .env template), SECURITY_CHECKLIST.md (LDAP_BASE_DN checklist item), .env.example (restore section)

## [1.2.0] - 2026-02-26

### Added
- **Snapshot Restore Feature** — full restore-from-snapshot capability for boot-from-volume VMs
  - **API module** (`api/restore_management.py`): RestoreOpenStackClient, RestorePlanner, RestoreExecutor with 8 REST endpoints
  - **Database schema**: `restore_jobs` and `restore_job_steps` tables with JSONB plan/result storage, unique partial index for concurrency guard, heartbeat tracking
  - **RBAC**: 4 permission rows for `restore` resource (viewer=read, operator=read, admin=write, superadmin=admin)
  - **React Wizard** (`SnapshotRestoreWizard.tsx`): 3-screen guided restore flow (Select VM → Configure → Execute/Progress)
  - **NEW mode**: Create restored VM alongside the existing one (side-by-side)
  - **REPLACE mode**: Delete existing VM then recreate from snapshot (superadmin-only, requires destructive confirmation string)
  - **IP strategies**: NEW_IPS (default), TRY_SAME_IPS (best-effort), SAME_IPS_OR_FAIL (strict)
  - **Cross-tenant restore**: Uses same service user mechanism as snapshot system
  - **Dry-run mode**: Plan and validate without executing (RESTORE_DRY_RUN env var)
  - **Volume cleanup on failure**: Optional cleanup of orphaned volumes (RESTORE_CLEANUP_VOLUMES env var)
  - **Stale job recovery**: PENDING/RUNNING jobs automatically marked INTERRUPTED on API startup
  - **Real-time progress**: Per-step status updates via polling endpoint with heartbeat monitoring
  - **Restore feature toggle**: Disabled by default, enable via RESTORE_ENABLED env var
  - **UI tab**: New "Restore" tab in main navigation (visible when feature is enabled)

### Enhanced
- **deployment.ps1**: Interactive wizard now prompts for RESTORE_ENABLED, RESTORE_DRY_RUN, and RESTORE_CLEANUP_VOLUMES settings
- **docker-compose.yml**: Added RESTORE_ENABLED, RESTORE_DRY_RUN, RESTORE_CLEANUP_VOLUMES environment variables to pf9_api service
- **Documentation**: New RESTORE_GUIDE.md, updated API_REFERENCE.md, ARCHITECTURE.md, ADMIN_GUIDE.md, SECURITY.md, DEPLOYMENT_GUIDE.md, QUICK_REFERENCE.md, README.md

### Fixed
- **Removed unused imports** in restore_management.py (status, Request, List, bare psycopg2)
- **Removed redundant field_validators** — `pattern=` on Pydantic Field already enforces the same regex, `@field_validator` was a no-op duplicate

## [1.1.0] - 2026-02-12

### Added
- **History tab — deletion record viewing** — clicking "View Details" on a deletion record now queries `deletions_history` and shows the deletion event timeline, original resource type, reason, last-seen timestamp, and raw state snapshot; previously returned HTTP 500 "Invalid resource type: deletion"
- **History tab — advanced filtering** — filter recent changes by resource type, project, domain, and free-text search (matches name, ID, or description); "Clear Filters" button appears when any filter is active; count shows "X of Y" when filtered
- **History tab — sortable columns** — click Time, Type, Resource, Project, Domain, or Change Description headers to sort ascending/descending with ▲/▼ indicators
- **Dashboard — data freshness banner** — prominent banner at the top of the Landing Dashboard showing when the last inventory collection ran, how long it took, and a color-coded age indicator (green = fresh < 1h, yellow = 1–2h, red = stale > 2h); helps users understand how current the displayed data is

### Enhanced
- **Dashboard — last-run API uses database** — `/dashboard/rvtools-last-run` endpoint now queries the `inventory_runs` table (source of truth) instead of searching for Excel files on disk which didn't exist in the container; returns timestamp, source, duration, and run ID
- **Snapshot Compliance Report** — major UI and API improvements
  - Volumes grouped by policy with collapsible sections and per-policy compliance percentage
  - API queries volumes table directly (source of truth) instead of stale compliance_details
  - Removed duplicate `/snapshot/compliance` endpoint from main.py that served stale data
  - Full name resolution: volume → `volumes.name`, project → `projects.name`, tenant → `domains.name`, VM → `servers.name`
  - Each volume × policy is a separate row (e.g. 11 volumes × 3 policies = 33 rows)
  - Retention days per policy from volume metadata (`retention_daily_5`, `retention_monthly_1st`, etc.)
  - Snapshot count and last-snapshot timestamp are now strictly per-policy (joins `snapshot_records` with `snapshots` on `snapshot_id`)
  - Policies that haven't run yet (e.g. `monthly_1st` before the 1st) correctly show 0 snapshots and "—" for last snapshot
  - Non-compliant rows highlighted with subtle red background
  - Added CSV export button with all compliance data including snapshot count
  - Tenant/Project filter dropdowns send IDs (not names) for proper server-side filtering
  - Compliance report generator (`p9_snapshot_compliance_report.py`) now writes per-policy rows with resolved names
  - **Sortable column headers** per policy group table (click to sort asc/desc on any column)
  - **Volume ID and VM ID columns** added to compliance table for unique identification
  - **Per-policy snapshot counts from OpenStack metadata** — queries `snapshots.raw_json->'metadata'` directly (`created_by`, `policy`) instead of unreliable `snapshot_records` JOIN
  - **Separate Manual Snapshots section** — manual (non-automated) snapshots shown in their own table below compliance, with snapshot name/ID, volume, project, tenant, size, status, and created date; clear note that manual snapshots are never touched by automation
  - **Pending status for unscheduled policies** — policies that have never run (e.g. `monthly_15th`, `monthly_1st`) now show "Pending" (grey badge) instead of "Missing" (red), and are excluded from the non-compliant count; summary cards show Compliant / Non-Compliant / Pending separately

### Fixed
- **Snapshot Compliance showed NaN, missing names, and no per-policy breakdown**
  - Root cause: duplicate endpoint in `main.py` read from stale `compliance_details` table
  - Compliance_details had concatenated policy names, literal "NaN" for unnamed volumes, no tenant/VM data
  - Fixed by removing duplicate and querying volumes table with JOINs to projects, domains, servers
- **`SnapshotPolicySetCreate` model missing `tenant_name` field** — the create endpoint wrote `tenant_name` to the DB but the Pydantic model lacked the field, causing runtime errors
- **Compliance report showed wrong snapshot counts and last-snapshot for monthly policies**
  - Snapshot count was volume-level (all policies combined) instead of per-policy — `daily_5` could show 8 snapshots even with retention=5
  - Last-snapshot timestamp fell back to volume-level (any policy), so `monthly_15th`/`monthly_1st` showed the `daily_5` timestamp instead of "—"
  - Fixed by querying `snapshots.raw_json->'metadata'` directly for `created_by=p9_auto_snapshots` and `policy=<name>`, eliminating dependency on incomplete `snapshot_records` table
- **Snapshot retention off-by-one: count = retention + 1 after each cycle**
  - Root cause: `cleanup_old_snapshots_for_volume()` ran BEFORE creating the new snapshot, so it trimmed to `retention` then a new one was added → `retention + 1`
  - Fixed by moving cleanup to AFTER the snapshot is created in `process_volume()`, so the new snapshot is included in the count and the oldest excess one is deleted
- **Daily dedup: prevent duplicate snapshots on same-day reruns**
  - Running `p9_auto_snapshots.py` multiple times in one day would create multiple snapshots consuming retention slots, reducing the actual days of recovery coverage
  - Added `_has_snapshot_today()` check — before creating, verifies no snapshot with matching `created_by` + `policy` metadata exists for the current UTC date; if one exists the volume is skipped with status `SKIPPED`
  - `daily_5` now guarantees exactly 1 snapshot per day per volume, keeping 5 calendar days of recovery points
- **History tab "View History" error for deletion records**
  - Clicking "View History" on a deletion record returned HTTP 500: `Invalid resource type: deletion`
  - Root cause: `v_comprehensive_changes` emits `resource_type='deletion'` but the `/history/resource/{type}/{id}` endpoint's `table_mapping` only contained standard resource types
  - Fixed by adding dedicated `deletion` handling in all three history endpoints (`/history/resource`, `/history/compare`, `/history/details`) — queries `deletions_history` directly and returns standardized history format with original resource type, reason, and raw state snapshot

## [1.0.0] - 2026-02-12

### Added
- **Landing Dashboard** with 14 real-time analytics endpoints and auto-refresh
  - Health summary, snapshot SLA compliance, capacity trends
  - Tenant risk scoring, host utilization, VM hotspots
  - Coverage risk, compliance drift, change compliance
  - Recent activity widget, capacity pressure analysis
- **17+ React UI components** with dark/light theme support
  - `LandingDashboard`, `HealthSummaryCard`, `SnapshotSLAWidget`
  - `TenantRiskScoreCard`, `TenantRiskHeatmapCard`, `HostUtilizationCard`
  - `CapacityTrendsCard`, `CapacityPressureCard`, `CoverageRiskCard`
  - `ComplianceDriftCard`, `ChangeComplianceCard`, `RecentActivityWidget`
  - `SnapshotMonitor`, `SnapshotPolicyManager`, `SnapshotAuditTrail`
  - `SnapshotComplianceReport`, `SystemLogsTab`, `APIMetricsTab`
  - `ThemeToggle`, `UserManagement`
- **Snapshot automation system** with policy-based scheduling
  - `snapshot_scheduler.py` — cron-style snapshot orchestration
  - `p9_auto_snapshots.py` — automated snapshot creation per policy
  - `p9_snapshot_policy_assign.py` — policy-to-volume assignment engine
  - `p9_snapshot_compliance_report.py` — SLA compliance reporting
  - `snapshot_policy_rules.json` — configurable policy definitions
- **Cross-tenant snapshot service user** (`snapshot_service_user.py`)
  - Dedicated service account for multi-tenant snapshot operations
  - Fernet-encrypted password storage support
  - Automatic role assignment per target project
  - Dual-session architecture (admin session + project-scoped session)
- **LDAP authentication** with RBAC (viewers, operators, admins, superadmins)
  - JWT access + refresh token authentication
  - Group-based role enforcement across all API endpoints
  - User management (create/delete/list) via LDAP admin operations
- **Database integration layer** (`db_writer.py`)
  - Automated inventory collection pipeline (PF9 API → PostgreSQL)
  - 22+ database tables with FK constraints and history tracking
- **Host metrics collector** (`host_metrics_collector.py`)
  - Collects hypervisor and VM metrics from PF9 hosts
  - Scheduled collection via Windows Task Scheduler
  - Shared metrics cache for monitoring service
- **Monitoring service** with Prometheus-compatible metrics endpoint
- **Interactive deployment wizard** (`deployment.ps1`)
  - Prompts for all customer-specific configuration
  - Auto-generates LDAP base DN from domain name
  - Fernet key generation for encrypted passwords
  - Auto-generates JWT secret keys
- **Comprehensive documentation**
  - `README.md` — Project overview, quick start, architecture
  - `DEPLOYMENT_GUIDE.md` — Step-by-step deployment instructions
  - `ADMIN_GUIDE.md` — Day-to-day administration reference
  - `ARCHITECTURE.md` — System design and component interaction
  - `SECURITY.md` — Security model, authentication, encryption
  - `SECURITY_CHECKLIST.md` — Pre-production security audit checklist
  - `SNAPSHOT_AUTOMATION.md` — Snapshot system design and configuration
  - `SNAPSHOT_SERVICE_USER.md` — Service user setup and troubleshooting
  - `API_REFERENCE.md` — Complete API endpoint documentation
  - `QUICK_REFERENCE.md` — Common commands and URLs cheat sheet
  - `KUBERNETES_MIGRATION_GUIDE.md` — Future K8s migration planning
  - `CONTRIBUTING.md` — Contribution guidelines
- **Docker Compose** orchestration for all services (API, UI, DB, LDAP, monitoring, snapshots)
- **Release automation** — `release.ps1` script and GitHub Action for version tagging

### Security
- Removed all customer-specific data from git-tracked files
  - No hardcoded domain names, passwords, IPs, or encryption keys in source
  - All sensitive values read from environment variables (`.env` file)
  - `.env` properly gitignored; `.env.example` provides template
- LDAP admin password passed via environment variable (not hardcoded)
- Snapshot service user password supports Fernet encryption at rest
- JWT secret auto-generated during deployment

[unreleased]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/erezrozenbaum/pf9-mngt/releases/tag/v1.0.0
