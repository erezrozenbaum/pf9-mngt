# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.10.0] - 2026-02-16

### Added
- **Tenant Health View**: Per-tenant health scoring and resource monitoring dashboard
  - **Database**: New `v_tenant_health` SQL view that aggregates per-project metrics from servers, volumes, networks, subnets, ports, floating IPs, security groups, snapshots, drift events, and compliance data. Enhanced with compute stats: `total_vcpus`, `total_ram_mb`, `total_flavor_disk_gb`, `active_vcpus`, `active_ram_mb`, `hypervisor_count`, `power_on_pct` (joins servers → flavors for real resource allocation). Health score (0–100) computed from error resources, compliance gaps, and drift severity. Migration script `db/migrate_tenant_health.sql`
  - **API Endpoints**: 5 new endpoints —
    - `GET /tenant-health/overview` — all tenants with health scores, compute stats, resource counts, and summary aggregates (healthy/warning/critical counts, avg score). Filterable by `domain_id`, sortable by any metric column
    - `GET /tenant-health/heatmap` — per-tenant utilization heatmap data with weighted utilization scores (60% VM activity + 40% volume usage), filterable by domain
    - `GET /tenant-health/{project_id}` — full health detail for a single tenant including compute allocation (vCPUs, RAM, disk), resource status breakdown, top volumes by size, and recent drift events (last 30 days)
    - `GET /tenant-health/trends/{project_id}` — daily drift and snapshot trends for charts (configurable time range up to 365 days)
    - `GET /tenant-health/quota/{project_id}` — live OpenStack quota fetch (compute: instances, cores, RAM; storage: volumes, gigabytes, snapshots) with graceful fallback when credentials unavailable
  - **UI Tab** (`TenantHealthView.tsx`): New "🏥 Tenant Health" tab with:
    - Summary cards showing total tenants, healthy/warning/critical counts, and average health score
    - **Compute summary row**: Total VMs (with on/off breakdown), Total vCPUs, Total RAM, Power-On Rate
    - **Table view**: Sortable, searchable tenant table with health score badges, inline power state mini-bars, vCPU/RAM columns, volume and drift stats, compliance percentage
    - **Heatmap view**: Visual tile-based utilization map where tile size reflects VM count and color reflects utilization score (green = high, red = low). Toggle between Table and Heatmap views
    - Click-to-open **detail panel** with:
      - Score hero with health status, power-on rate, and hypervisor count
      - Resource summary grid: servers, vCPUs, RAM, flavor disk, volumes, networks, floating IPs, ports, security groups, snapshots, compliance
      - **VM Power State section**: Active/Shutoff/Error/Other cards with stacked percentage bar and legend
      - **Volume Status section**: In-use/Available/Error status bar
      - **Quota vs Usage section**: Live quota bars (Instances, vCPUs, RAM, Volumes, Gigabytes, Snapshots) with color-coded usage levels (green < 70%, yellow 70-90%, red > 90%). Graceful "unavailable" message when OpenStack credentials not configured
      - Top volumes table, drift activity timeline
    - Domain/tenant filter integration — auto-opens tenant detail when a specific tenant is selected globally
    - CSV export with all compute stats (vCPUs, RAM, power-on %, etc.)
    - Full dark mode support for all new sections (compute row, heatmap tiles, power state cards, quota bars)
  - **Health Score Formula**: Starts at 100, deductions for: error VMs (−10 each, max −20), shutoff VMs (−2 each, max −10), error volumes (−5 each, max −15), error snapshots (−5 each, max −10), low compliance (up to −20), critical drift (−5 each, max −15), warning drift (−2 each, max −10)
  - **RBAC**: `tenant_health` resource with read access for all roles, admin for admin/superadmin

### Fixed
- **Branding logo upload**: Fixed "Enter admin credentials first" error when uploading logos. Changed branding PUT/POST endpoints from HTTP Basic Auth to JWT Bearer auth, matching the token the UI already sends

## [1.9.0] - 2026-02-16

### Added
- **Drift Detection Engine**: Automated configuration drift detection that monitors infrastructure changes between inventory syncs
  - **Database**: New `drift_rules` table (24 built-in rules across servers, volumes, networks, subnets, ports, floating IPs, security groups, and snapshots) and `drift_events` table (stores detected changes with severity, old/new values, timestamps). Migration script `db/migrate_drift_detection.sql`
  - **Detection Hook** (`db_writer.py`): `_detect_drift()` function integrated into `_upsert_with_history()` — snapshots existing records before upsert and compares field-by-field against enabled drift rules. Automatically generates drift events when monitored fields change
  - **API Endpoints**: 7 new endpoints —
    - `GET /drift/summary` — aggregate counts by severity and resource type, filterable by domain/project
    - `GET /drift/events` — paginated event list with filters (severity, resource_type, status, search, date range, domain)
    - `GET /drift/events/{id}` — single event detail
    - `PUT /drift/events/{id}/acknowledge` — acknowledge an event with optional notes
    - `PUT /drift/events/bulk-acknowledge` — bulk acknowledge multiple events
    - `GET /drift/rules` — list all drift rules with enable/disable status
    - `PUT /drift/rules/{rule_id}` — toggle rule enabled/disabled or update severity
  - **UI Tab** (`DriftDetection.tsx`): New "🔍 Drift Detection" tab with:
    - Summary dashboard showing total events, critical/warning/info counts, resource type pie chart
    - Events table with severity badges, sortable columns, pagination, and multi-select checkboxes
    - Filters: severity, resource type, status, free-text search, date range
    - Event detail panel with old → new value comparison
    - Bulk and individual acknowledge actions
    - Rules management panel to enable/disable rules and adjust severities
    - CSV export of filtered events
    - Domain/tenant filter integration with the global filter bar
  - **RBAC**: `drift` resource mapped in permission middleware; read access for all roles, write (acknowledge/rule toggle) for operator and above
  - **Styling**: Full `DriftDetection.css` with dark mode support, severity color coding, responsive layout

## [1.8.0] - 2026-02-16

### Added
- **Branding & Login Page Customization**: Full white-label branding system for the login page and application identity
  - **Database**: New `app_settings` table (key/value store for branding config) and `user_preferences` table (per-user settings like tab order), with migration script `db/migrate_branding_tables.sql`
  - **API Endpoints**: `GET /settings/branding` (public, no auth), `PUT /settings/branding` (admin), `POST /settings/branding/logo` (admin, file upload), `GET /user-preferences` and `PUT /user-preferences` (authenticated)
  - **Admin Panel — Branding Tab**: New "🎨 Branding & Login Page Settings" tab in Admin Panel with fields for company name, subtitle, primary/secondary colors (with color pickers), logo upload (PNG/JPEG/GIF/SVG/WebP, max 2 MB), hero title, hero description, and feature highlights list (add/remove). Live gradient preview and immediate save
  - **Login Page Redesign**: Two-column layout — login form on the left, branded hero panel on the right with customizable title, description, feature checkmarks, and stats bar (24/7 Monitoring, 100% Audit Coverage, RBAC). Company logo and name displayed above the login form. Light mode uses gradient from branding colors; dark mode uses solid dark surface with subtle radial glow
  - **RBAC**: `/settings/` and `/static/` paths bypass authentication middleware so the login page can load branding before the user logs in
- **Tab Drag-and-Drop Reordering**: Users can drag-and-drop tabs to customize their preferred tab order
  - **Data-Driven Tabs**: All 27 tabs defined as a `DEFAULT_TAB_ORDER` array with id, label, icon, category, RBAC permission, and feature-toggle metadata
  - **HTML5 Drag-and-Drop**: Native drag events with visual drop indicator, grab cursor, and smooth transitions
  - **Persistence**: Tab order saved to `localStorage` and synced to backend via `PUT /user-preferences` (per-user)
  - **Reset Button**: "↩" button restores default tab order instantly

### Fixed
- **Dark Mode — Login Page**: Removed decorative circles that appeared as black blobs in dark mode; replaced with subtle radial glow. Hero text centered horizontally. Text opacity increased for better readability in dark mode
- **Dark Mode — Branding Settings Tab**: Labels and inputs now use `--color-text-primary` CSS variable (was using undefined `--color-text` with dark fallback `#333`). Feature highlight items get explicit text color
- **Dark Mode — Restore Audit Refresh Button**: Added `[data-theme="dark"]` CSS overrides for `.restore-audit-btn-secondary` — button now has proper dark surface background and white text instead of invisible dark-on-dark
- **Dark Mode — Snapshot Policy Buttons**: Added dark mode overrides for `.tab-btn`, `.btn-secondary`, `.btn-primary`, section backgrounds, and error alerts in `SnapshotPolicyManager.css`
- **Dark Mode — CSS Variable Aliasing**: Root cause fix — component CSS files used undefined shorthand variables (`--text-primary`, `--card-bg`, `--border-color`, `--primary-color`, `--secondary-color`, etc.) that didn't match the actual `--color-*` prefixed variables in `index.css`. Added proper alias definitions to both light and dark theme blocks so all component styles resolve correctly in both modes
- **`ActiveTab` TypeScript type**: Added missing `"ports"` and `"floatingips"` to the union type

## [1.7.1] - 2026-02-16

### Added
- **Security Groups — Human-Readable Rule Descriptions**: API now returns a `rule_summary` field for every security group rule (e.g., "Allow TCP/22 (SSH) ingress from 0.0.0.0/0"). `remote_group_id` UUIDs are resolved to actual security group names via `remote_group_name` field. Both the detail and list rule endpoints use a LEFT JOIN to resolve names. Well-known port mapping covers SSH, HTTP, HTTPS, RDP, DNS, MySQL, PostgreSQL, Redis, and more
- **Security Groups Tab — Improved Rule Tables**: Ingress/Egress rule tables now show a bold **Rule** column with the human-readable summary and optional description. "Remote" column renamed to Source/Destination and shows `remote_group_name` instead of raw UUIDs
- **Security Groups CSV Export — Per-Rule Detail Rows**: Export CSV now fetches all rules and produces one row per rule per security group, with columns for Rule Direction, Rule Summary, Protocol, Port Min/Max, Remote IP, Remote SG Name, and Rule Description. SGs with no rules still get one row
- **Restore — Post-Restore Storage Cleanup**: New `CLEANUP_OLD_STORAGE` step added to restore workflow. When enabled via `cleanup_old_storage` (delete orphaned original volume) and/or `delete_source_snapshot` (remove source snapshot after restore) flags on the plan request, these are automatically cleaned after a successful restore
- **Restore — Standalone Storage Cleanup Endpoint**: New `POST /restore/jobs/{job_id}/cleanup-storage` endpoint for cleaning up storage leftovers from already-completed REPLACE-mode restores. Supports `delete_old_volume` and `delete_source_snapshot` query parameters with safety checks (won't delete attached volumes)
- **Restore Wizard — Storage Cleanup UI**: Configure screen now shows "Post-Restore Storage Cleanup" options with checkboxes for old volume and source snapshot deletion. Success panel for REPLACE-mode restores shows three cleanup buttons: "Delete Old Volume", "Delete Source Snapshot", and "Delete Both"

## [1.7.0] - 2026-02-16

### Added
- **Security Groups — Full Stack Support**: Complete security groups and firewall rules management across every layer
  - **Database**: `security_groups` and `security_group_rules` tables with full history tracking (`*_history` tables), cascade-delete FK from rules to groups, `v_security_groups_full` aggregate view (attached VM/network counts, ingress/egress rule counts via ports)
  - **Data Collection** (`pf9_rvtools.py`): Collects `security-groups` and `security-group-rules` from Neutron API; enriches SGs with VM attachment info via ports; exports "SecurityGroups" and "SecurityGroupRules" sheets in Excel/CSV
  - **API Endpoints** (`api/main.py`): 7 new endpoints — `GET /security-groups` (paginated, filterable by domain/tenant/name), `GET /security-groups/{sg_id}` (detail with rules + attached VMs + networks), `GET /security-group-rules` (paginated), `POST /admin/security-groups`, `DELETE /admin/security-groups/{sg_id}`, `POST /admin/security-group-rules`, `DELETE /admin/security-group-rules/{rule_id}`
  - **API Client** (`api/pf9_control.py`): 6 new Neutron methods — `list_security_groups`, `get_security_group`, `create_security_group`, `delete_security_group`, `create_security_group_rule`, `delete_security_group_rule`
  - **UI Tab** (`SecurityGroupsTab.tsx`): New 🔒 Security Groups tab with list/detail layout, filter/sort/pagination, color-coded ingress/egress badges, create SG form (with project picker), delete SG, add rule form (direction/protocol/ports/remote), delete rule, attached VMs and networks in detail panel
  - **Restore Wizard**: Security group multi-select picker on Configure screen; `security_group_ids` passed through plan → `create_port()` during execution
  - **RBAC**: `security_groups` and `security_group_rules` mapped in resource permission system
  - **DB Migration Script** (`db/migrate_security_groups.sql`): Idempotent migration for existing databases — creates all 4 tables, indexes, the `v_security_groups_full` view, and inserts RBAC permissions
  - **Export CSV**: Export button on Security Groups tab exports current filtered list to CSV
  - **Rule Template Presets**: One-click quick-add buttons for common firewall rules (SSH, HTTP, HTTPS, RDP, ICMP, DNS) in the detail panel
  - **Default SG Auto-Selection**: Restore wizard auto-selects the "default" security group when a tenant is chosen, so users don't accidentally launch VMs without basic firewall rules

### Fixed
- **`neutron_list()` hyphenated resource names** (`p9_common.py`): URL path uses hyphens (`security-groups`) but Neutron JSON response uses underscores (`security_groups`); added `json_key = resource.replace("-", "_")` mapping — backward-compatible since existing resources don't have hyphens
- **Missing RBAC permissions for `security_groups`**: Added `security_groups` read/admin permissions for all roles (viewer, operator, admin, superadmin) in `init.sql` — without these, the RBAC middleware would return 403 on all security group endpoints
- **`security_group_rules_history` missing columns**: Added `created_at` and `updated_at` columns — without these, `_upsert_with_history()` failed with `UndefinedColumn` when collecting security group rules
- **History tab only showed 6 resource types**: Expanded `v_comprehensive_changes` view from 6 types (server, volume, snapshot, security_group, security_group_rule, deletion) to all 17 tracked resource types — added network, subnet, port, floating_ip, domain, project, flavor, image, hypervisor, user, role. All history tables now surface in the History tab with proper JOINs for resource names, project, and domain context
- **Restore fails at "Create network ports" in REPLACE mode with SAME_IPS_OR_FAIL**: When replacing a VM, old ports were not explicitly cleaned up — the IP addresses remained held by orphan ports after Nova VM deletion (race condition or externally-created ports). Added `CLEANUP_OLD_PORTS` step that explicitly deletes old ports by ID, scans for orphan ports attached to the deleted VM, and cleans orphan ports holding the target IPs. Also added retry logic (5 attempts × 3s) in the `CREATE_PORTS` step for transient IP release delays
- **Restore leaves orphaned volumes/ports on failure**: Added `/restore/jobs/{job_id}/cleanup` endpoint to clean up orphaned OpenStack resources (ports, optionally volumes) from a failed restore job. Added `/restore/jobs/{job_id}/retry` endpoint to resume a failed job from the failed step, reusing already-created resources (volumes, ports). Both endpoints exposed via recovery action buttons in the Restore Wizard UI

## [1.6.4] - 2026-02-15

### Fixed
- **413 "Request Entity Too Large" volumes now skipped instead of failed** — when Platform9 Cinder API rejects a snapshot with HTTP 413, the volume is recorded as `skipped` (not `failed`) and does not add to the ERRORS list, so snapshot runs show `completed` status instead of `partial` in the Snapshot Run Monitor
- Catches `requests.exceptions.HTTPError` with status 413 specifically in `process_volume()`, logs as `413_SKIPPED` with a clear message, and increments `skipped_count` instead of `failed_count`

## [1.6.3] - 2026-02-15

### Fixed
- **250GB volumes now snapshot correctly** — `AUTO_SNAPSHOT_MAX_SIZE_GB` docker-compose default was still 200GB even after code change; updated default to 260GB in both `docker-compose.yml` and `snapshot_scheduler.py`
- **Fixed `ActiveTab` TypeScript type** — added missing `"snapshot-policies"` and `"snapshot-audit"` to the `ActiveTab` union type in `App.tsx`

## [1.6.2] - 2026-02-15

### Changed
- **Manual IP selection now auto-loads available IPs** — when "Select IPs manually" is chosen, available IPs are fetched automatically from Neutron (no more "Load IPs" button click required)
- Removed misleading warning "restore will FAIL if any chosen IP is already in use" since the UI now only presents available (unused) IPs in the dropdown
- Manual IP selector shows a loading indicator while fetching and a clear message if no IPs are available on a network

## [1.6.1] - 2026-02-15

### Fixed
- **Manual snapshots not showing in restore wizard** — the restore-points endpoint only queried the local DB `snapshots` table (populated by scheduled sync), so manually created snapshots in Platform9/OpenStack were invisible until the next sync. Now also queries Cinder API directly, merges and deduplicates results, so all snapshots appear immediately

## [1.6.0] - 2026-02-15

### Added
- **Manual IP selection during restore** — new "Select IPs manually" option in IP Strategy dropdown; users can pick from available IPs per network or type a specific IP address
- **`GET /restore/networks/{network_id}/available-ips` API endpoint** — lists available (unused) IPs on a network's subnets by querying Neutron for subnet CIDRs and existing ports, returns up to 200 available IPs per subnet
- **`MANUAL_IP` ip_strategy** — `RestorePlanRequest` now accepts `MANUAL_IP` strategy with optional `manual_ips` dict mapping network IDs to desired IPs
- **Original VM configuration in Restore Audit Trail** — audit detail view now shows a dedicated "Original VM Configuration" section with flavor name, vCPUs, RAM, disk, status, and original IPs per network (from stored `plan_json`)

### Changed
- Restore wizard UI: IP Strategy dropdown now includes "Select IPs manually" option with a per-network IP selector
- Restore wizard: when MANUAL_IP is selected and a plan exists, users can click "Load IPs" to fetch available IPs from Neutron, or manually enter an IP address
- Restore audit: expanded detail grid with new "Original VM Configuration" section between Source and Result sections

## [1.5.1] - 2026-02-15

### Fixed
- **On-demand snapshot pipeline was failing** — the API container tried to execute snapshot scripts via `subprocess`, but those scripts only exist in the `snapshot_worker` container. Rearchitected to use database-based signaling: the API writes a `pending` row to the new `snapshot_on_demand_runs` table, and the snapshot worker picks it up on its next 10-second polling cycle
- **Snapshot restore 401 UNAUTHORIZED on cross-tenant operations** — the service user password is stored Fernet-encrypted (`SNAPSHOT_PASSWORD_KEY` + `SNAPSHOT_USER_PASSWORD_ENCRYPTED`), but the API container only checked the plaintext `SNAPSHOT_SERVICE_USER_PASSWORD` env var (which was empty). Added `_resolve_service_user_password()` to decrypt the password using the same Fernet logic the snapshot worker uses
- **docker-compose.yml** — added `SNAPSHOT_PASSWORD_KEY` and `SNAPSHOT_USER_PASSWORD_ENCRYPTED` env vars to the `pf9_api` container so the restore engine can decrypt the service user credentials

### Added
- **`snapshot_on_demand_runs` database table** — stores on-demand pipeline jobs with step-level JSONB progress, enabling cross-container communication between the API and snapshot worker
- **`check_on_demand_trigger()`** in `snapshot_scheduler.py` — checks for pending on-demand runs every 10 seconds in the main scheduler loop and executes the full pipeline with per-step progress updates

### Changed
- On-demand pipeline status now includes `pending` state (waiting for worker pickup) in addition to `running`, `completed`, and `failed`
- UI handles `pending` status with "Waiting for worker to pick up..." message and keeps polling until the worker starts execution

## [1.5.0] - 2026-02-15

### Changed
- **Snapshot scheduler default interval changed from daily to hourly** — `POLICY_ASSIGN_INTERVAL_MINUTES` and `AUTO_SNAPSHOT_INTERVAL_MINUTES` now default to `60` (was `1440`). Existing `_has_snapshot_today()` deduplication prevents duplicate snapshots; newly created VMs are now picked up within one hour instead of waiting up to 24 hours.

### Added
- **On-demand snapshot pipeline ("Sync & Snapshot Now")** — admins can trigger the full snapshot pipeline (policy assignment → inventory sync → auto snapshots → inventory sync) on demand without waiting for the next scheduled run
  - **API**: `POST /snapshot/run-now` (requires `snapshots:admin`) returns job ID; poll `GET /snapshot/run-now/status` for step-by-step progress
  - **UI**: "🔄 Sync & Snapshot Now" button on Delete & Restore → Screen 1, next to tenant selector; shows real-time step progress with color-coded status pills
  - Built-in concurrency guard — only one on-demand run at a time (409 Conflict if already running)
  - Auto-refreshes VM list after pipeline completes

## [1.4.1] - 2026-02-15

### Fixed
- **Snapshot Restore — cloud-init user_data preservation** — restored VMs now receive the original VM's cloud-init `user_data` (base64-encoded), preventing cloud-init from resetting credentials or configuration on first boot
  - During plan building, the original VM's `user_data` is fetched via Nova API (microversion 2.3+, `OS-EXT-SRV-ATTR:user_data`)
  - Stored in the plan's VM section and passed to `create_server` on restore execution
  - UI plan preview shows whether cloud-init data will be preserved (green ✅) or is missing (amber ⚠️)
  - Progress tracker shows preservation status after the CREATE_SERVER step completes

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

[unreleased]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.4.1...HEAD
[1.4.1]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/erezrozenbaum/pf9-mngt/releases/tag/v1.0.0
