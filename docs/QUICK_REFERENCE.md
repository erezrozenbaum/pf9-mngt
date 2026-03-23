# Platform9 Management System - Quick Reference

## System Overview (March 2026)

### Comprehensive OpenStack Management Platform
The Platform9 Management System is a enterprise-grade infrastructure management solution providing:

#### Complete Resource Coverage (29 Resource Types)
- **Compute**: Virtual Machines (Servers), Hypervisors, Flavors, Images
- **Storage**: Volumes, Snapshots, Volume Types, Bootable Volumes  
- **Network**: Networks, Subnets, Ports, Routers, Floating IPs, Security Groups & Rules
- **Identity**: Domains, Projects/Tenants, Users with comprehensive role management (100+ users across 28 domains)

#### Advanced User & Role Management
- **Multi-Domain User Collection**: Complete user visibility across all 28 domains (20 with active users)
- **Role Assignment Tracking**: Comprehensive role assignments with admin, member, and service roles
- **Activity Monitoring**: User last-seen timestamps, account status, and authentication tracking
- **Role Inference System**: Intelligent role assignment detection when API access is limited

#### Modern React UI Features (30+ Comprehensive Tabs)
- **Dashboard Tab** (NEW ✨): Landing Dashboard with 14 real-time analytics endpoints
  - Health Summary, Snapshot SLA Compliance, Host Utilization, Recent Activity
  - Coverage Risks, Capacity Pressure, VM Hotspots, Tenant Risk Scores
  - Compliance Drift, Capacity Trends, Trendlines, Change Compliance
  - Tenant Risk Heatmap, Tenant Summary
  - Auto-refresh every 30 seconds, Dark/Light mode support
- **Tenant Health Tab** (v1.10 - NEW ✨):
  - "🏥 Tenant Health" tab with per-project health scoring, compute stats, and monitoring
  - Health score 0–100 per tenant with deductions for error resources, low compliance, drift events
  - Database: `v_tenant_health` SQL view with compute stats (vCPUs, RAM, disk, power-on %, hypervisor count)
  - Summary cards + compute summary row (Total VMs, vCPUs, RAM, Power-On Rate)
  - Table view: sortable tenant table with inline power state mini-bars, vCPU/RAM columns
  - Heatmap view: visual tile-based utilization map (size = VM count, color = utilization score)
  - Click-to-expand detail panel: compute resources, VM power state breakdown, volume status, quota vs usage bars, top volumes, drift timeline
  - 5 API endpoints: overview, heatmap, detail, trends, live quota
  - CSV export, domain/tenant filter integration, full dark mode support
  - RBAC: `tenant_health:read` (all roles), `tenant_health:admin` (Admin/Superadmin)
- **Notifications Tab** (v1.11 - NEW ✨):
  - "🔔 Notifications" tab with per-user email notification preferences, delivery history, and admin settings
  - Event types: drift alerts, snapshot failures, compliance violations, health score drops
  - 3 sub-tabs: Preferences (toggle event types, severity filtering), History (delivery log), Settings (SMTP status, test email)
  - Notification worker container polls DB every 120s, sends immediate emails and daily digests
  - RBAC: `notifications:read`/`notifications:write` (all roles), `notifications:admin` (Admin/Superadmin)
- **Drift Detection Tab** (v1.9 - NEW ✨):
  - "🔍 Drift Detection" tab with real-time infrastructure drift event monitoring
  - 24 built-in rules across 8 resource types (servers, volumes, networks, subnets, ports, floating IPs, security groups, snapshots)
  - Detection hook in `db_writer.py` fires during each inventory sync
  - Filter by resource type, severity, domain, tenant, acknowledgement status
  - Single & bulk acknowledge, CSV export, rules management panel
  - RBAC: `drift:read` (all roles), `drift:write` (Operator+)
- **Branding & Login Customization** (v1.8 - NEW ✨):
  - White-label login page with two-column layout (login form + branded hero panel)
  - Admin Panel “Branding” tab for company name, subtitle, colors, logo, hero content, feature highlights
  - Logo upload (PNG/JPEG/GIF/SVG/WebP, max 2 MB)
  - Live gradient preview, immediate effect for new visitors
- **Tab Drag-and-Drop** (v1.8 - NEW ✨):
  - Reorder navigation tabs via drag-and-drop with visual drop indicator
  - Per-user persistence (localStorage + `user_preferences` backend table)
  - Reset button ("↩") to restore default 28-tab order
- **Dark Mode Enhancements** (v1.8):
  - Comprehensive dark mode fixes across login page, branding settings, restore audit, and snapshot policy
  - CSS variable aliasing system ensuring all component styles resolve correctly in both themes
- **Infrastructure Tabs**: Servers, Volumes, Snapshots, Networks, Security Groups, Subnets, Ports, Floating IPs
- **Platform Tabs**: Domains, Projects, Flavors, Images, Hypervisors
- **Management Tabs**: Users (with role assignments), History (change tracking), Audit (compliance), Monitoring (real-time metrics), Restore Audit (restore job history)
- **History Tab Features**:
  - Filter by resource type, project, domain, and free-text search (name/ID/description)
  - Sortable columns: Time, Type, Resource, Project, Domain, Description (▲/▼)
  - Deletion record viewing with original resource type, reason, and raw state snapshot
  - Most frequently changed resources with direct history navigation
  - Configurable timeframe: 1 hour, 24 hours, 3 days, 1 week
- **Admin Tabs**: API Metrics, System Logs (Admin/Superadmin only)
- **Metering Tab** (v1.15 + v1.15.1 Pricing ✨):
  - "📊 Metering" tab with 8 sub-tabs: Overview, Resources, Snapshots, Restores, API Usage, Efficiency, **Pricing**, Export
  - Per-VM resource tracking (vCPUs, RAM, disk allocation + actual usage, network I/O) — deduplicated to latest per VM
  - Snapshot and restore operation metering with compliance tracking
  - API usage tracking (call counts, error rates, latency percentiles)
  - VM efficiency scoring with classification (excellent/good/fair/poor/idle)
  - **Multi-category pricing**: Flavor (auto-synced from system), storage/GB, snapshot/GB, restore, volume, network — hourly + monthly rates
  - **Filter dropdowns**: Project/domain selectors populated from actual tenant data
  - Chargeback export with per-category cost breakdown (compute, storage, snapshot, restore, volume, network, TOTAL)
  - RBAC: `metering:read` (Admin/Superadmin), `metering:write` (Superadmin)
- **Enhanced Capabilities**: Advanced filtering, sorting, pagination across all tabs with real-time data refresh
- **Runbooks Tab** (v1.21 → v1.57):
  - "📋 Runbooks" tab with policy-as-code catalogue and one-click execution
  - 24 built-in engines across 5 categories:
    - **VM**: Stuck VM Remediation, VM Health Quick Fix, Snapshot Before Escalation, Password Reset + Console Access, **VM Rightsizing** *(v1.55)*, **DR Drill** *(v1.56)*, **Hypervisor Maintenance Evacuate** *(v1.57)*
    - **Security**: Security Group Audit, Security & Compliance Audit, **Security Group Hardening** *(v1.57)*, **Network Isolation Audit** *(v1.57)*, **Image Lifecycle Audit** *(v1.57)*
    - **Quota**: Quota Threshold Check, Upgrade Opportunity Detector, Snapshot Quota Forecast, **Quota Adjustment** *(v1.53)*
    - **General**: Orphan Resource Cleanup, Diagnostics Bundle, Monthly Executive Snapshot, Cost Leakage Report, VM Provisioning, **Org Usage Report** *(v1.53)*, **Capacity Forecast** *(v1.55)*
    - **Provisioning**: **Tenant Offboarding** *(v1.56)*
  - Schema-driven parameter forms with dry-run toggle and risk-level badges
  - Approval workflow: per-runbook policies with role-based trigger→approver mappings (high-risk runbooks require admin approval)
  - 3 Admin sub-tabs in User Management: Runbook Executions (audit trail), Runbook Approvals (pending queue), Runbook Policies (governance rules)
  - RBAC: `runbooks:read` (Viewer+), `runbooks:write` (Operator+), `runbooks:admin` (Admin/Superadmin)
  - **Lookup endpoints**: `GET /api/runbooks/lookup/vms`, `/lookup/projects`, `/lookup/hypervisors` *(v1.57)*
- **Runbook Dept Visibility** (v1.52.0):
  - Admin-only checkbox grid (runbooks × departments); absence of rows = visible to all
  - `GET /api/runbooks/visibility` — full matrix (admin+)
  - `PUT /api/runbooks/visibility/{runbook_name}` — replace dept list for runbook (admin+)
  - Non-admin users only see runbooks their department is permitted to view
- **External Integrations** (v1.52.0):
  - Register billing gates, CRM, and webhooks; `auth_credential` Fernet-encrypted at rest
  - `GET /api/integrations` — list all (admin+)
  - `GET /api/integrations/{name}` — get single (admin+)
  - `POST /api/integrations` — create (superadmin)
  - `PUT /api/integrations/{name}` — update (superadmin)
  - `DELETE /api/integrations/{name}` — delete (superadmin)
  - `POST /api/integrations/{name}/test` — fire test request + persist `last_test_status`
- **Support Tickets Tab** (v1.58.0 — NEW ✨):
  - Full ticket lifecycle: create, assign, escalate, approve/reject, resolve, reopen, close
  - Ticket types: service_request, incident, change_request, inquiry, escalation
  - Human-readable refs: `TKT-YYYY-NNNNN` (per-year auto-increment)
  - SLA tracking: response + resolution deadlines, breach/warning indicators in list and detail
  - Comment thread: internal notes (hidden from viewers) and external activity log
  - Admin sub-panel: SLA policy table (team × type × priority) + HTML email template editor
  - RBAC: viewer/operator/technical → read+write; admin/superadmin → admin
  - 35+ API endpoints at `/api/tickets`
- **My Queue Tab** (v1.58.0 — NEW ✨):
  - Priority-sorted ticket queue scoped to the current user's department
  - Pre-filtered view (open/in-progress tickets assigned to or from current user's team)
  - `GET /api/tickets/my-queue` — returns tickets sorted by priority then SLA urgency
- **Auto-Ticket Triggers** (v1.59.0 — NEW ✨):
  - **Drift → Incident**: critical/warning drift events automatically open `auto_incident` tickets; idempotent dedup on `auto_source_id="drift:{type}:{id}:{field}"` prevents duplicates
  - **Health Score Drop → Incident**: graph `health_score < 40` triggers auto-incident to Engineering (host) or Tier2 Support (VM); fires on every graph query, dedup prevents flood
  - **Delete Impact → Change Request Gate**: `POST /api/graph/request-delete` — creates `auto_change_request` ticket with `auto_blocked=true`; returns `{status, ticket_id, ticket_ref, created, message}`
  - **Runbook Failure → Incident**: failed runbook executions automatically open an incident ticket linked to the `execution_id`; `auto_source="runbook_failure"`
  - **Migration Wave Complete → Service Request**: wave completion triggers a service-request ticket for documentation and sign-off; `auto_source="migration"`, `auto_source_id="wave:{wave_id}"`
  - **UI buttons**: "🎫 Create Incident Ticket" in Drift Detection side-panel; "🚨 Report Incident" in Tenant Health detail panel (score < 60, red for < 40, amber for 40–59); "🎫 Request Delete Approval" in Graph delete-impact panel
  - All auto-tickets: idempotent (`auto_source` + `auto_source_id` unique dedup), routed by severity, never block primary operations on failure
- **Analytics & Polish — T4** (v1.60.0 — NEW ✨):
  - `GET /api/tickets/analytics?days=30` — resolution time by dept, SLA breach rate by dept, top openers, daily volume trend (admin-only)
  - `GET /api/tickets/stats` now returns `resolved_today` + `opened_today`; stats bar suppresses priority breakdown when a status filter is active
  - `POST /api/tickets/bulk-action` — `close_stale` (stale_days threshold), `reassign` (assigned_to username), `export_csv` (attachment); checkbox multi-select + bulk toolbar in TicketsTab
  - `GET /api/tickets/team-members/{dept_id}` — active users in a department; Create Ticket modal shows optional "Assign to user" dropdown; `assigned_to` stored at creation with status `assigned`
  - Opener confirmation email: `ticket_created` template sent to the internal opener's email address (SMTP enabled, `users.name` lookup)
  - `GET /api/navigation/departments` fixed to return `{departments: [...]}` — resolves empty teams in Create Ticket modal and dept filter
  - LandingDashboard: ticket KPI widget (Open / SLA Breached / Resolved Today / Opened Today)
  - MeteringTab: 📋 Open Inquiry button per resource row; RunbooksTab: 📎 Ticket button per execution row
- **Security & Auth Hardening** (v1.78.0 — NEW ✨): LDAP DN injection closed (`ldap.dn.escape_dn_chars()` on all 4 DN-construction sites); LDAP network timeout (5 s) on all 7 `ldap.initialize()` call sites; `verify_admin_credentials` raises HTTP 503 when unconfigured (was silently bypassing auth) + `hmac.compare_digest()` to prevent timing attacks; `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` in all auth paths; `rbac_middleware` caches `TokenData` in `request.state` (eliminates double `verify_token()` DB call per request); `SMTP_PASSWORD` now resolved via `read_secret()` consistent with all other credentials
- **Migration Planner Region Normalization** (v1.77.0): `migration_projects.target_region_id` + `source_region_id` FK columns to `pf9_regions`; `pcd-gap-analysis` uses ClusterRegistry client when `target_region_id` is set (no global config mutation, falls back to ad-hoc creds when NULL); `PcdSettingsRequest` accepts new fields; `GET /admin/control-planes/cluster-tasks` superadmin endpoint surfaces pending cluster_tasks with `processor_status: NOT_IMPLEMENTED`; `migrate_phase8_migration_norm.sql` + `idx_cluster_tasks_pending` index; Phase 8 startup guard in `main.py`
- **Multi-Region Management UI** (v1.76.0): `ClusterContext` React context + `RegionSelector` nav dropdown (≥2 regions, superadmin-only, grouped by CP with health dots) + `ClusterManagement` admin panel (CP add/delete/test/discover, region enable/disable/set-default/sync/log); per-region `?region_id=` filtering injected into `MeteringTab`, `ResourceManagementTab`, `ReportsTab`, `LandingDashboard`; `migrate_phase7_nav.sql` adds `cluster_management` nav item; startup guard in `main.py`
- **Multi-Region API Filtering** (v1.75.0): optional `?region_id=` on all 7 API modules (metering, dashboards, reports, resource_management, provisioning, vm_provisioning, search); RBAC enforcement via `get_effective_region_filter()`; live-API calls routed to correct region registry client; DB endpoints apply `WHERE region_id = %s`; `search_ranked` updated with backward-compatible 9th `filter_region` param; `search_documents.region_id` column + index added
- **Metering Worker Crash Fix** (v1.74.6): Phase 5B migration guard hardened to require all 6 target `region_id` columns before skipping; `security_groups.region_id` column + index added to `init.sql` / `migrate_multicluster.sql`; fixes metering_worker crash on `collect_quota_usage` LATERAL subquery
- **Full Per-Region Worker Loops** (v1.74.5): metering_worker all-collector multi-region loop with `region_id`-tagged rows; `HostMetricsCollector` optional `region_id` constructor arg; scheduler per-region `HostMetricsCollector` instances; `migrate_metering_region.sql` adds `region_id` + indexes to all metering tables and `backup_history`
- **Multi-Region Worker Support** (v1.74.2): `p9_common.py` asyncio semaphore fan-out; scheduler/metering/snapshot workers iterate all enabled regions; `snapshot_runs.region_id` column tags runs to source region; host metrics collector multi-region loop; `MAX_PARALLEL_REGIONS` / `REGION_REQUEST_TIMEOUT_SEC` env vars; advisory-lock startup migration (prevents gunicorn worker deadlock on restart); SQL migration parser regression fixed (semicolons in comments)
- **SAST Security Fixes & CI Gate Correction** (v1.74.1): Bandit HIGH-only gate flags corrected (`-ll -ii` → `-lll -iii`); `hashlib.sha1/md5` and `requests verify=False` annotated with `usedforsecurity=False` / `nosec`; zero HIGH findings
- **Control Plane & Region Management API** (v1.74.0): 14 superadmin-only REST endpoints for multi-cluster admin (`/admin/control-planes`, `/admin/control-planes/{id}/regions`); Fernet credential encryption; live Keystone connectivity test; SSRF protection; registry hot-reload; 25 new unit tests
- **System Metadata Routing Fix** (v1.72.5 — NEW ✨): `/system-metadata-summary` and `/export` added to nginx routing and Vite proxy; fixes System Metadata tab empty under Inventory
- **snapshot-worker Build Context Fix** (v1.72.4): Release build context aligned with docker-compose
- **snapshot-worker Build Fix** (v1.72.3): Fixed Dockerfile COPY paths
- **Release Pipeline Fix** (v1.72.2): All 10 service images now built and published
- **Maintenance & Hardening** (v1.72.1): Internal API hardening
- **Migration Planner Restored & Production Startup Fixes** (v1.72.0):
  - **Migration Planner restored** — `migration_routes.py`, `migration_engine.py`, `MigrationPlannerTab.tsx`, `ProjectSetup.tsx`, `SourceAnalysis.tsx` re-added; `.gitignore` exclusion block removed so CI builds include them
  - **`startup_prod.ps1` fixed** — `up -d --build` → `pull` + `up -d`; stops local rebuilds overwriting `ghcr.io` images on production start
  - **nginx `/tenants` routing** — `location = /tenants` rewrite to `/api/tenants` added; fixes 404 on Migration Planner Projects page
  - **API migration router** — `migration_router` registered in `main.py`; `GET /tenants` alias route added
- **Dependency Security Patches & Quality Fixes** (v1.71.0):
  - **Webhook URL validation** — `SLACK_WEBHOOK_URL`/`TEAMS_WEBHOOK_URL` validated at startup; non-`https` or empty-host URLs rejected
  - **CSV export quoting** — all CSV downloads use `QUOTE_ALL`; prevents column corruption in Excel on fields with commas or newlines
  - **Ticket approval note max length** — `ApproveRejectRequest.note` capped at 5,000 characters (HTTP 422 on violation)
  - **Python CVE upgrades** — `fastapi`, `requests`, `python-ldap`, `python-jose`, `python-multipart` upgraded to resolve 13 CVEs
  - **npm transitive CVEs** — `flatted`, `minimatch`, `rollup` forced to patched versions via `package.json` overrides
  - **Release pipeline** — Docker images now built/pushed before GitHub Release is created
  - **CI audit tooling** — `pip-audit --severity` replaced; `npm audit` fix corrected
- **Performance, Security & Code Quality** (v1.70.0):
  - **Report pagination** — `tenant-quota-usage` and `domain-overview` endpoints accept `page`/`page_size`; project slice applied before per-project quota API calls; JSON includes `total`/`page`/`page_size`; CSV unaffected
  - **Upload row cap** — bulk onboarding Excel rejects any sheet > 2,000 rows with HTTP 400
  - **Dependency version bounds** — `httpx`, `redis`, `Jinja2`, `openpyxl`, `reportlab`, `openai`, `anthropic` pinned with `<N.0.0` upper bounds
  - **Copilot markdown** — `renderMarkdown()` replaced with `marked.parse()` + `DOMPurify.sanitize()` (marked v14)
  - **CI dependency audit** — `dependency-audit` job: `pip-audit` (critical=fail) + `npm audit --audit-level=high`; integration tests gated on it
- **Bug Fixes Sprint** (v1.69.0):
  - **Performance metrics `IndexError`** — `get_endpoint_stats()` returns `{}` on empty histogram; prevents crash on cold-start endpoints
  - **Phase 4A `migration_flavor_staging` table** — `startup_event()` applies `migrate_phase4_preparation.sql` idempotently; no more 500 on fresh deployments
  - **ISO timestamp `Z`-suffix parse error** — `host_metrics_collector.py` strips `Z` before `fromisoformat()`; fixes `ValueError` on Python < 3.11
  - **Scheduler worker task leak on SIGTERM** — `finally` block cancels and awaits all asyncio tasks before executor shutdown
  - **Metering worker duplicate rows** — `pg_try_advisory_lock(8765432)` at cycle start; replicas skip when another holds the lock
  - **Backup worker silent `pg_dump` failure** — size < 1 KB check after `pg_dump` exits; corrupt output raises `RuntimeError` and triggers cleanup
  - **SLA daemon task leak on shutdown** — `_sla_task` module variable; `shutdown_event()` cancels and awaits it cleanly
- **Security Hardening Sprint** (v1.68.0):
  - **OpsSearch XSS fix** — `dangerouslySetInnerHTML` on search headline sanitized via `DOMPurify.sanitize()` with `ALLOWED_TAGS: ["mark"]`; eliminates stored XSS via search index
  - **SMTP TLS enforcement** — `api/smtp_helper.py` and `notifications/main.py` now set `ctx.check_hostname = True` + `ctx.verify_mode = ssl.CERT_REQUIRED`; prevents silent acceptance of invalid certificates
  - **LDAP `create_user` SSHA hash** — `create_user()` now hashes password with `{SSHA}` before storing in OpenLDAP (was plaintext `userPassword`)
  - **LDAP backup password exposure** — `_run_ldap_backup/restore()` uses `-y <tempfile>` instead of `-w <password>`; password no longer visible in `ps aux`
  - **Password complexity policy** — `AddUserRequest` min length 6→8; uppercase + digit + special char required; HTTP 422 with descriptive message
  - **Rate limit on password reset** — `POST /auth/users/{username}/password` limited to 5 requests/minute
  - **Secret file permission warning** — `read_secret()` warns when secret file has group/other readable bits set (checks `0o077`)
  - **Backup worker distributed lock** — `pg_try_advisory_lock(9876543)` wraps scheduled-backup check; prevents duplicate runs in multi-replica deployments
  - **VM OS password lifecycle** — `os_password` wiped from DB after successful provisioning; minimum length raised 6 → 8 characters
  - **docker-compose.yml fail-fast guards** — `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_DB`, `JWT_SECRET_KEY`, `LDAP_ADMIN_PASSWORD` use `${VAR:?ERROR:...}` syntax; startup blocked if any secret is empty
- **Wave Approval Gates, VM Dependency Auto-Import & Maintenance Window Scheduling** (v1.67.0 — NEW ✨):
  - **Wave Approval Gates** — each migration wave now requires explicit approval before advancing to pre-checks-passed; operators request approval (triggers notifications); admins approve or reject inline with a comment; approval status badge (⏳ pending / ✅ approved / ❌ rejected); "Pass Checks" button locked until approved
  - **VM Dependency Auto-Import** — detects implicit VM dependencies from RDM disk sharing (confidence 0.95) and shared-datastore co-location (confidence 0.70); dry-run preview before committing; source badges (💽 RDM / 🗄 DS); auto-imports managed independently from manually entered dependencies
  - **Maintenance Window Scheduling** — recurring per-project windows (day-of-week, start/end time, timezone, cross-midnight); Auto-Build Waves stamps `scheduled_start`/`scheduled_end` from next available slot; preview strip shows next 8 upcoming calendar bands
  - **New DB table**: `maintenance_windows`; new columns: `migration_waves.approval_status/approved_by/approved_at/approval_comment`, `migration_vm_dependencies.dep_source/confidence`, `migration_projects.use_maintenance_windows`
  - **New endpoints (10)**: wave approve/reject/request-approval, maintenance window CRUD, dependency auto-import dry-run/commit — all `401`-gated
  - **Requires one-time DB migration**: `docker exec -i pf9_db psql -U $POSTGRES_USER -d $POSTGRES_DB < db/migrate_wave_approvals.sql`
- **CI/CD Pipeline Hardening & Input Validation Fixes** (v1.66.3):
  - **`release.yml` branch ref fix** — checkout uses `${{ github.event.workflow_run.head_branch }}` instead of hardcoded `master`
  - **`release.yml` CHANGELOG regex tightened** — version extraction requires closing `]` in header pattern, prevents malformed headers producing wrong version strings
  - **Redis healthcheck** — `docker-compose.yml` `redis` service has a Docker healthcheck (`redis-cli ping`); dependent services wait until Redis is confirmed reachable
  - **DB connection timeout** — `_db_params()` in `p9_common.py` passes `connect_timeout=10` to psycopg2; prevents indefinite hang when DB is unreachable
  - **`VMReassignRequest.vm_ids` length guard** — `Field(max_length=1000)` rejects oversized payloads with HTTP 422
  - **`CreateTenantRequest.detection_method` typed** — `Optional[Literal[...]]` returns HTTP 422 for unrecognised values instead of silently storing invalid data
  - **Cluster exclusion sentinel parameterised** — sentinel changed to `f'Cluster exclusion: {cluster_name}'` for precise per-cluster reversibility
- **Cluster-Level Scoping & Unassigned VM Surface** (v1.66.2 — UPDATED ✅):
  - **Cluster exclusion toggle** — click any cluster pill in the Tenants tab to exclude/re-include a VMware cluster from wave planning; excluded clusters display as red strikethrough pills; VMs on excluded clusters show a `⊘` badge on the VMs tab Cluster column
  - **Cascade to tenants (vSphere)** — excluding a cluster automatically sets `include_in_plan=false` on all tenants whose `org_vdc` matches the cluster name; Networks and Cohorts tabs immediately reflect the exclusion; re-including cascades back only for auto-excluded tenants (sentinel = `'Cluster excluded from plan'`)
  - **Manual VM reassignment** — checkboxes on VMs tab + "Move to Tenant…" modal; `PATCH /vms/reassign` body `{vm_ids, tenant_name, create_if_missing}`; `manually_assigned=true` VMs are never overwritten by re-detection; empty `vm_ids` allowed when `create_if_missing=true`
  - **Empty tenant creation (vSphere)** — `POST /api/migration/projects/{id}/tenants` body `{tenant_name, detection_method?, pattern_value?}`; "Add Tenant Rule" form only requires tenant name — detection rule is optional
  - **Unassigned VM group** — synthetic ⚠️ `(Unassigned)` row appended to Tenants tab when VMs exist without a tenant; cluster pills are interactive for direct exclusion before re-detection
  - **New endpoints**: `PATCH /api/migration/projects/{id}/clusters/scope`, `POST /api/migration/projects/{id}/tenants`, `PATCH /api/migration/projects/{id}/vms/reassign`; VM list response extended with `cluster_in_scope: bool`
  - **Requires one-time DB migration**: `docker exec -i pf9_db psql -U $POSTGRES_USER -d $POSTGRES_DB < db/migrate_cluster_scoping.sql`
- **VMware Cluster Column in Migration Planner** (v1.66.1):
  - **Tenants tab** — new Clusters column + All Clusters filter dropdown; shows every VMware cluster hosting that tenant's VMs; filter scopes the tenants list to one cluster
  - **VMs tab** — new Cluster column per VM row (alongside Tenant); cluster data now also loaded when switching to the Tenants sub-tab
  - No DB migration required — `cluster` was already stored per-VM from the `vInfo` RVTools sheet
- **Container Alerting, Full CI Pipeline & Docker Image Publishing** (v1.66.0):
  - **Container restart alerting** — monitoring watchdog polls Docker socket every 60 s; emails alert address on crash/unhealthy; recovery notification on return to healthy; configurable via `PUT /admin/settings/container-alert` (superadmin) / `GET /settings/container-alert` (public); Admin panel UI tab
  - **Full integration test pipeline** — GitHub Actions now spins up the full Docker Compose stack and runs `pytest tests/` against live endpoints on every push; seed check verifies CI admin login; 38 tests in suite
  - **Docker images on ghcr.io** — all 9 service images auto-built for `linux/amd64` + `linux/arm64` and pushed to `ghcr.io/erezrozenbaum/pf9-mngt-<service>` on each release; pin via `PF9_IMAGE_TAG` in `.env`
- **Production Healthcheck Fix & Automated Test Suite** (v1.65.4):
  - **`pf9_ui` healthcheck fixed** — Alpine `localhost` resolves to `::1` (IPv6); nginx binds IPv4 only; changed to `http://127.0.0.1:80` — container now reports `(healthy)` in production
  - **Automated test suite** — `tests/test_health.py` and `tests/test_auth.py` added; JWT unit tests run in CI on every push/PR; integration tests for login/logout/token revocation run with credentials
- **Snapshot Worker Startup Performance Fix** (v1.65.3):
  - **"Sync & Snapshot Now" no longer slow after restart** — on-demand trigger check moved to top of scheduler loop; 60-second startup grace period prevents the full scheduled pipeline (policy-assign + RVTools + auto-snapshot) from blocking the first on-demand run after a container restart
- **Snapshot Restore Bug Fix & Code Cleanup** (v1.65.2):
  - **"Sync & Snapshot Now" fixed** — the button now correctly reaches the API; missing `/api` prefix on `run-now` fetch calls caused a 405 (nginx forwarded to the React UI instead of the backend)
  - **Dead code removed** — 3 unauthenticated probe endpoints removed; duplicate route block removed; last `print()` replaced with `logger.info()`; dead `db_conn` parameter plumbing removed from snapshot/restore setup
  - **Redundant commits cleaned up** — 6 leftover `conn.commit()` calls removed from `integration_routes.py` and `runbook_routes.py`
- **Production & Dev Stack Fixes** (v1.65.1):
  - **Login from any IP** — `config.ts` defaults changed to `""` (relative paths); `Dockerfile.prod` build-arg names corrected so `VITE_API_BASE`/`VITE_MONITORING_BASE` are no longer always `undefined`
  - **nginx prod routing rewrite** — `nginx/nginx.prod.conf` fully rewritten: `pf9_monitoring` upstream added, `^~ /metrics/` beats regex, `/restore/` and `/static/` locations added, `Host: localhost` proxy header fixes TrustedHostMiddleware 400
  - **Admin Tools blank pages** — `UserManagement.tsx` now unwraps the `departments` array correctly (was storing whole response object, causing `.map()` crash)
  - **Vite dev proxy rewrite** — `vite.config.ts` now proxies all API and monitoring paths matching nginx; `VITE_MONITORING_TARGET` added to `docker-compose.yml`
  - **Prod/dev image conflict** — `docker-compose.prod.yml` previously had `image: pf9-mngt-pf9_ui-prod`; now all services use `ghcr.io/erezrozenbaum/pf9-mngt-<service>:${PF9_IMAGE_TAG:-latest}` so prod images are always pre-built and versioned
- **CI Pipeline + CORS + DB Indexes** (v1.65.0):
  - **GitHub Actions CI** — `.github/workflows/ci.yml`: Python syntax check + flake8 + `docker compose config` validation on every push/PR
  - **CORS production mode** — set `APP_ENV=production` to restrict `ALLOWED_ORIGINS` to nginx proxy only; dev origins excluded automatically
  - **DB performance indexes** — `db/migrate_indexes.sql`: 8 indexes on `inventory_runs`, `activity_log`, `snapshots`, `migration_vms`, `tickets`, `runbook_executions`; applied on API startup
- **Production Hardening** (v1.64.0):
  - **Docker Secrets** — DB, LDAP, SMTP, and JWT credentials moved from env vars to Docker Secrets; `docker-compose.prod.yml` wires them automatically
  - **LDAP FD leak fix** — `auth.py` LDAP methods (`get_all_users`, `create_user`, `delete_user`, `change_password`) now close connections in `finally` blocks
  - **Log rotation** — `RotatingFileHandler` added to all workers (10 MB × 5 backups); no more unbounded log files
  - **nginx prod config** — `nginx/nginx.prod.conf` targets `pf9_ui:80` (Dockerfile.prod); dev `nginx.conf` unchanged (Vite :5173)
  - **Port hardening** — `docker-compose.prod.yml` suppresses `pf9_api:8000`, `pf9_ui:5173`, `pf9_monitoring:8001` host ports; all traffic via TLS nginx
  - **CORS fix** — `https://localhost` added to `ALLOWED_ORIGINS` in API and monitoring services
  - **`startup_prod.ps1`** — production startup script with Secrets pre-flight check and port-isolation verification
- **RVTools Exports Browser** (v1.63.0):
  - "📁 RVTools Exports" sub-tab inside the Reports tab — visible to all roles (inherits `reports:read`)
  - **File list table**: filename, date (UTC), size in MB, ⬇ Download — sorted newest-first; authenticated blob download
  - **Run History table**: started, finished, duration, status badge (green=success/blue=running/red=failed), source, notes; last 100 `inventory_runs` rows by default
  - **API endpoints**: `GET /api/reports/rvtools/files`, `GET /api/reports/rvtools/files/{filename}`, `GET /api/reports/rvtools/runs?limit=50` (all require `reports:read`)
  - **Scheduler logging**: each `pf9_rvtools.py` run writes stdout+stderr to `/app/logs/rvtools_YYYYMMDD_HHMMSSZ.log` inside the container
- **Migration Planner PDF Fixes** (v1.63.0):
  - `Fix(h)` and `Downtime(h)` columns added to both the Plan PDF daily schedule (11 cols) and Summary PDF daily schedule (15 cols)
  - Power State column added to Plan PDF daily schedule (`On`/`Off`/`Susp`); VM Name, Tenant, OS now word-wrap correctly in cells
  - KPI `total_downtime_hours` corrected — no longer overridden by cutover-only value; now includes fix hours + migration downtime
  - `NameError: name 's_cell' is not defined` (500 on PDF download) fixed
  - `.gitignore` updated: `reports/` and `/reports/` patterns added to protect hourly RVTools exports from commits
- **Migration Planner — Per-Day Schedule Breakdown + Throughput Cap Fix** (v1.44.0):
  - **Engine rewrite** (`migration_engine.py`): replaced per-slot hour packing with a real GB/day throughput ceiling — `effective_gbph = (bottleneck_mbps/8) × 3600/1024 × 0.55`; `max_gb_per_day = effective_gbph × working_hours`
  - `wall_clock_hours` now `day_transfer_gb / effective_gbph` (was `day_hours_used / total_concurrent` — badly under-counted)
  - `over_capacity: true` flag on any day where `wall_clock_hours > working_hours_per_day`
  - New `transfer_gb` field per daily schedule entry; `effective_gbph` and `max_gb_per_day` exposed in `project_summary`
  - **`GET /migration-summary` rewrite** (`migration_routes.py`): runs same engine as export-plan; tenant query includes cohort JOIN (fixes alignment where all days showed "Uncohorted"); VM query uses `SELECT v.*`
  - New `per_day[]` array in summary response: day, cohort_name, tenant_count, vm_count, total_gb, wall_clock_hours, total_agent_hours, cold_count, warm_count, risk_green/yellow/red, over_capacity
  - New `total_provisioned_gb` KPI field in summary response
  - **UI**: "Migration Days" KPI card; "In-Use Data (TB)" with provisioned subtitle; per-day table between KPI strip and OS breakdown; over-capacity rows in red + ⚠️; Migration Plan daily schedule shows ⚠️ indicator on over-capacity days; project summary footer shows daily throughput cap
- **Cloud Dependency Graph — Health Scores, Blast Radius & Delete Safety** (v1.51.0):
  - **Three modes** via `?mode=topology|blast_radius|delete_impact`
  - **Blast Radius** (`?mode=blast_radius`): BFS following "serves" edges; `blast_radius.summary` → `vms_impacted`, `tenants_impacted`, `floating_ips_stranded`, `volumes_at_risk`; impacted nodes highlighted red + animated edges; others dimmed
  - **Delete Impact** (`?mode=delete_impact`): cascade/stranded analysis per resource type; returns `safe_to_delete`, `blockers[]`, `cascade_node_ids[]`, `stranded_node_ids[]` — network (subnets/ports cascade; VMs with no fallback network stranded), volume (snapshots cascade), tenant (everything cascades), VM (FIPs stranded), SG (blocked if VMs use it)
  - **Health Score** per node (0–100): VM (−30 error, −10 power_off, −15 snap_missing, −8 snap_stale, −15 drift), Volume (−30 error, −5 orphan, −20 snap_missing, −10 snap_stale), Host (−20 CPU>80%, −8 CPU>60%, −20 RAM>80%, −8 RAM>60%)
  - **Orphan detection**: volumes (available, unattached), FIPs (no port_id), SGs (not in use, not 'default'), snapshots (parent volume gone) — surfaced in `orphan_summary`
  - **3-state snapshot coverage**: `snapshot_protected` (< 7 days), `snapshot_stale` (≥ 7 days), `snapshot_missing` (none)
  - **Capacity pressure**: `healthy` / `warning` / `critical` from host CPU/RAM; nodes tinted accordingly
  - **Graph-level summary**: `graph_health_score`, `tenant_summary` (vms_critical, vms_degraded, vms_missing_snapshot, vms_with_drift), `top_issues[]`, `orphan_summary`
  - **UI — Mode toggle**: 3-way pill in toolbar (Topology / 💥 Blast Radius / 🗑 Delete Impact)
  - **UI — Tenant Health Panel**: shown above canvas in Topology mode when root is a tenant
  - **UI — Sidebar**: health score badge, snapshot coverage (✅/⚠️/❌), capacity ring, quick-action buttons when score < 60
- **Cloud Dependency Graph — Backend API + UI + Node Actions** (v1.47.0):
  - `GET /api/graph?root_type=<type>&root_id=<id>&depth=1-3` — BFS graph from any resource; returns `nodes[]`, `edges[]`, `node_count`, `edge_count`, `truncated`
  - 12 node types: `vm`, `volume`, `snapshot`, `network`, `subnet`, `port`, `fip`, `sg`, `tenant`, `host`, `image`, `domain`
  - 15 edge traversals including VM→SG via `ports.raw_json` JSONB; badges: `no_snapshot`, `drift`, `error_state`, `power_off`, `restore_source`
  - 150-node hard cap; optional `domain` filter param; RBAC `resources:read`
  - **UI**: full-screen `DependencyGraph.tsx` drawer (ReactFlow + dagre); depth pills; type filter checkboxes; dark node sidebar; "🔍 Explore from here" re-root + "← Back" history
  - **Entry points**: "🕸️ View Dependencies" on Servers, Volumes, Snapshots, Networks, Projects detail panels
  - **Node actions**: "🔗 Open in tab" (navigate + pre-select), "📸 Create Snapshot" (volumes), "🚀 View in Migration Planner" (VMs/tenants)
- **Migration Planner Phase 4D — Tenant User Bulk Ops & vJailbreak CRD Push** (v1.46.0):
  - **Tenant Users UX overhaul**: filter bar (type / status / role / search), checkbox multi-select, bulk confirm, set-role, delete via `/bulk-action`
  - **"👤 Seed Tenant Owners"** button — bulk-creates one `admin@<domain>` owner per tenant (idempotent); uses `target_domain_name` if set, else `tenant_name`
  - **Bulk Find & Replace** panel — regex replace on `username`, `email`, or `role` across all tenant users; `preview` mode returns diffs without writing
  - **"✓ Confirm All"** button — marks all unconfirmed users confirmed in one call
  - **🚀 vJailbreak Push sub-tab**: configure API URL + namespace + bearer token (per-project, token masked); dry-run preview (would_create / would_skip per CRD type); push `OpenstackCreds`, `VMwareCreds`, `NetworkMappings` CRDs to a live Kubernetes cluster; task log table with done/skipped/failed pill badges + clear button
  - 10 new API endpoints: `seed-tenant-owners`, `bulk-replace`, `confirm-all`, `bulk-action`, `vjailbreak-push-settings` (GET/PATCH), `vjailbreak-push/dry-run`, `vjailbreak-push`, `vjailbreak-push-tasks` (GET/DELETE)
  - DB: `migration_projects.vjb_api_url / vjb_namespace / vjb_bearer_token`; new `migration_vjailbreak_push_tasks` table
  - `.env.example`: `VJB_API_URL`, `VJB_NAMESPACE`, `VJB_BEARER_TOKEN` (stored per-project in DB; env vars serve as defaults)
- **Migration Planner Phase 5.0 — Tech Fix Time & Migration Summary** (v1.42.0):
  - New **Migration Summary** tab: executive KPIs (total VMs, total fix hours, migrated count, at-risk count), OS breakdown, cohort breakdown
  - **Tech Fix Time model**: weighted per-VM fix time engine (`compute_vm_fix_time`) using base rate, risk multipliers, snapshot/NIC/disk penalties, and OS-specific rates
  - **Fix Settings card**: per-project tunable weights and OS rates stored in `migration_fix_settings` table; global override option
  - **Per-VM Fix Override**: expandable ⏱ card in VM expanded row — lock any VM to a custom fix time (bypasses model)
  - 4 API endpoints: `GET/PATCH /fix-settings`, `PATCH /vms/{id}/fix-override`, `GET /migration-summary`
  - DB migrations: `migration_vms.tech_fix_minutes_override INTEGER`; new `migration_fix_settings` table
- **VM Provisioning — Runbook 2** (v1.39.0):
  - "☁️ VM Provisioning" card in Runbooks tab — 4-step form: domain/project → VM rows → OS credentials + cloud-init preview → review + submit
  - Tenant-scoped auth via `provisionsrv` Keystone service account (not in LDAP); run `setup_provision_user.py` once after deploy
  - Windows: cloudbase-init `#ps1_sysnative` + Nova `adminPass`; dry-run emits `windows_cloudinit` + `windows_glance_property` warnings
  - **Auto Glance patch** (v1.44.2): execution automatically sets `os_type=windows`, `hw_disk_bus=scsi`, `hw_scsi_model=virtio-scsi`, `hw_firmware_type=bios` on the image before creating the boot volume
  - Admin Tools → "🖥️ VM Provisioning" sub-tab: full batch history + expandable per-VM table + dark-terminal activity timeline
  - Rich completion email: VM table with image/flavor/OS/GB/error columns + execution timeline section
  - 15 API endpoints at `/api/vm-provisioning/*`; 2 auto-migrated DB tables; 5 notification event types
  - RBAC: inherited from runbook framework; approve/reject admin-only
- **Bulk Customer Onboarding** (v1.38.0, patched v1.38.1):
  - "📦 Bulk Customer Onboarding" card in Runbooks tab opens a dedicated multi-step workflow
  - Upload a four-sheet Excel workbook (`customers`, `projects`, `networks`, `users`) → validate → dry-run → approve → execute against PCD
  - Dry-run gate: execution hard-locked until dry-run reports zero conflicts
  - Live-polling execution view with per-item status (domain / project / network / user rows)
  - 9 API endpoints at `/api/onboarding/*`; 5 new DB tables; 5 new notification event types
  - RBAC: `onboarding:create`, `onboarding:read`, `onboarding:approve`, `onboarding:execute`

#### Advanced Snapshot Management
- **Cross-Tenant Snapshots**: Snapshots created in correct tenant projects via dedicated service user
- **Automated Snapshot Creation**: Policy-driven with hourly scheduling (default 60 min, configurable)
- **On-Demand Snapshot Pipeline**: "Sync & Snapshot Now" button on Restore tab + `POST /api/snapshot/run-now` API
- **Metadata-Driven Policies**: Volume-level configuration via OpenStack metadata
- **Multi-Policy Support**: Volumes support multiple concurrent policies (daily_5, monthly_1st, monthly_15th)
- **Compliance Monitoring**: SLA tracking and policy adherence reporting with tenant/domain aggregation
- **Policy Assignment Rules**: JSON-driven automatic assignment based on volume properties
- **Service User**: Configurable via `SNAPSHOT_SERVICE_USER_EMAIL` with per-project admin role assignment

#### Snapshot Restore (v1.2 - NEW)
- **VM Restore from Snapshot**: Restore boot-from-volume VMs from Cinder volume snapshots
- **NEW Mode**: Side-by-side restore (keeps original VM)
- **REPLACE Mode**: Destructive restore (superadmin only, deletes original VM)
- **IP Strategies**: NEW_IPS, TRY_SAME_IPS, SAME_IPS_OR_FAIL
- **UI Wizard**: 3-screen guided restore (Select VM → Configure → Execute/Progress)
- **Safety**: Dry-run mode, destructive confirmation, stale job recovery, volume cleanup
- **Feature Toggle**: Disabled by default (`RESTORE_ENABLED=true` to activate)
- **RBAC**: Admin for NEW mode, Superadmin for REPLACE mode

#### Real-Time Infrastructure Monitoring
- **Host Metrics**: CPU, Memory, Storage from PF9 compute nodes via node_exporter (port 9388) ✅
- **VM Metrics**: Individual VM resource tracking via libvirt_exporter (port 9177) ❌ *[Requires PF9 Engineering]*
- **Hostname Resolution**: Friendly host names via `PF9_HOST_MAP` env var (API/DNS fallback)
- **Automated Collection**: Windows Task Scheduler every 30 minutes
- **Cache-Based Storage**: Persistent directory-mounted cache (`monitoring/cache/`) with container restart survival
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
- **Database Integration**: PostgreSQL 16 with 53+ tables for historical tracking + metering + departments/navigation + runbooks + onboarding
- **Drift Detection**: Automated field-level change monitoring with 24 rules across 8 resource types
- **Administrative Operations**: Create/delete flavors and networks directly from UI

---

## Initial Setup (Required)

### Environment Configuration
```bash
# 1. Copy template and configure credentials  
cp .env.template .env

# 2. Edit .env with your actual credentials (CRITICAL: NO QUOTES around values)
# CORRECT format:
PF9_USERNAME=your-service-account@example.com
PF9_PASSWORD=your-secure-password
PF9_AUTH_URL=https://your-cluster.platform9.com/keystone/v3
PF9_USER_DOMAIN=Default
PF9_PROJECT_NAME=service
PF9_PROJECT_DOMAIN=Default
PF9_REGION_NAME=region-one

# Database credentials (for Docker services)
POSTGRES_USER=pf9
POSTGRES_PASSWORD=<GENERATE: openssl rand -base64 32>
POSTGRES_DB=pf9_mgmt
```

### Complete Platform Deployment
```powershell
# Clone repository
git clone <repository-url>
cd pf9-mngt

# Configure .env file (see above)

# One-command complete setup (dev / local)
.\startup.ps1

# Verify services are running
docker-compose ps

# Access services:
# - Main UI: http://localhost:5173
# - API + Docs: http://localhost:8000/docs  
# - Monitoring API: http://localhost:8001
# - Database Admin: http://localhost:8080
```

```powershell
# Production deployment — uses pre-built images from ghcr.io
# 1. Set PF9_IMAGE_TAG=<version> in .env (e.g. PF9_IMAGE_TAG=v1.66.0), or leave as 'latest'
# 2. Pull images
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
# 3. Start stack
.\startup_prod.ps1
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

### Snapshot Restore (v1.2)
```bash
# Enable restore feature (add to .env)
RESTORE_ENABLED=true
RESTORE_DRY_RUN=false           # Set true to test without executing
RESTORE_CLEANUP_VOLUMES=false   # Set true to auto-delete failed restore volumes

# Restart API to pick up changes
docker-compose restart pf9_api

# Check restore config
curl -H "Authorization: Bearer <token>" http://localhost:8000/restore/config

# List available snapshots for a tenant
curl -H "Authorization: Bearer <token>" "http://localhost:8000/restore/snapshots?tenant_name=production"

# Get restore points for a specific VM
curl -H "Authorization: Bearer <token>" "http://localhost:8000/restore/vm/<vm_id>/restore-points?project_id=<project_id>"

# Create a restore plan (NEW mode)
curl -X POST http://localhost:8000/restore/plan \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"<proj_id>","vm_id":"<vm_id>","restore_point_id":"<snap_id>","mode":"NEW"}'

# Execute the plan
curl -X POST http://localhost:8000/restore/execute \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"plan_id":"<job_uuid>"}'

# Check job status
curl -H "Authorization: Bearer <token>" http://localhost:8000/restore/jobs/<job_id>

# Cancel a running restore
curl -X POST http://localhost:8000/restore/cancel/<job_id> \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Testing"}'
```

### Real-Time Monitoring
```powershell
# Check scheduler worker (runs metrics + RVTools automatically)
docker logs pf9_scheduler_worker --tail 20

# Manual metrics collection
docker exec pf9_scheduler_worker python host_metrics_collector.py --once

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
# PF9_USERNAME="your-service-account@example.com"

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

### Windows Task Scheduler
```powershell
# Metrics collection (auto-created by startup.ps1)
# Every 30 minutes — "PF9 Metrics Collection"

# Inventory collection (create manually)
schtasks /create /tn "PF9 RVTools Collection" /tr "python C:\pf9-mngt\pf9_rvtools.py" /sc daily /st 02:00
```

### Complete One-Command Setup (Recommended)
```powershell
# 1. Configure environment (one-time setup)
cp .env.template .env
# Edit .env with your Platform9 credentials

# 2. Single command startup (includes monitoring automation)
.\startup.ps1

# System will automatically:
# - Start pf9_scheduler_worker (metrics + inventory collection)
# - Start all Docker services (DB, API, UI, Monitoring)
# - Pre-flight NFS check if COMPOSE_PROFILES=backup
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

**Connection Pool Tuning** (optional):
```bash
DB_POOL_MIN_CONN=2    # Min connections per worker (default: 2)
DB_POOL_MAX_CONN=10   # Max connections per worker (default: 10)
# Total max = 4 workers × 10 = 40 connections (PostgreSQL default max: 100)
```

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
- **API Backend**: http://localhost:8000 (4 Gunicorn workers, connection pooling)
- **API Documentation**: http://localhost:8000/docs (OpenStack API gateway)
- **Monitoring API**: http://localhost:8001 (Real-time metrics service)
- **pgAdmin**: http://localhost:8080
- **Database Direct**: localhost:5432
- **Notification Worker**: (no web UI — check logs: `docker logs pf9_notification_worker`)
- **Metering Worker**: (no web UI — check logs: `docker logs pf9_metering_worker`)

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

# Drift Detection endpoints
curl -H "Authorization: Bearer <token>" "http://localhost:8000/drift/summary"      # Drift overview
curl -H "Authorization: Bearer <token>" "http://localhost:8000/drift/events"       # List drift events
curl -H "Authorization: Bearer <token>" "http://localhost:8000/drift/events/1"     # Event detail
curl -X PUT -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  "http://localhost:8000/drift/events/1/acknowledge"                                # Acknowledge event
curl -X PUT -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"event_ids":[1,2,3]}' "http://localhost:8000/drift/events/bulk-acknowledge"  # Bulk acknowledge
curl -H "Authorization: Bearer <token>" "http://localhost:8000/drift/rules"        # List rules
curl -X PUT -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"enabled":false}' "http://localhost:8000/drift/rules/4"                     # Disable a rule

# Tenant Health endpoints (5 endpoints)
curl -H "Authorization: Bearer <token>" "http://localhost:8000/tenant-health/overview"                # All tenants with health scores + compute stats
curl -H "Authorization: Bearer <token>" "http://localhost:8000/tenant-health/overview?domain_id=default&sort_by=health_score&sort_dir=asc"  # Filtered & sorted
curl -H "Authorization: Bearer <token>" "http://localhost:8000/tenant-health/heatmap"                 # Utilization heatmap data
curl -H "Authorization: Bearer <token>" "http://localhost:8000/tenant-health/<project_id>"            # Full tenant detail (vCPUs, RAM, power state)
curl -H "Authorization: Bearer <token>" "http://localhost:8000/tenant-health/trends/<project_id>?days=30"  # Trend data for charts
curl -H "Authorization: Bearer <token>" "http://localhost:8000/tenant-health/quota/<project_id>"      # Live OpenStack quota vs usage

# Notification endpoints
curl -H "Authorization: Bearer <token>" "http://localhost:8000/notifications/smtp-status"             # SMTP connection status
curl -H "Authorization: Bearer <token>" "http://localhost:8000/notifications/preferences"              # List user notification preferences
curl -X PUT -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"event_type":"drift_critical","email":"user@example.com","enabled":true,"severity_min":"warning","delivery_mode":"immediate"}' "http://localhost:8000/notifications/preferences"  # Create/update preference
curl -H "Authorization: Bearer <token>" "http://localhost:8000/notifications/history?limit=50"         # Delivery history
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"recipient":"admin@example.com"}' "http://localhost:8000/notifications/test-email"  # Send test email (admin only)
curl -H "Authorization: Bearer <token>" "http://localhost:8000/notifications/admin/stats"              # Admin delivery statistics

# Metering endpoints (v1.15 + v1.15.1 - Admin/Superadmin)
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/config"                    # Metering configuration
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/filters"                   # Filter dropdown data (projects, domains, flavors)
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/overview"                  # High-level metering dashboard
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/resources?hours=24"        # Per-VM resource metering (deduplicated)
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/snapshots?hours=24"        # Snapshot metering records
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/restores?hours=168"        # Restore operation metering
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/api-usage?hours=24"        # API usage metering
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/efficiency?hours=24"       # VM efficiency scores (deduplicated)
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/pricing"                   # Multi-category pricing list
curl -X POST -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/pricing/sync-flavors"  # Auto-import flavors from system
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/export/resources"          # CSV export: resources
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/export/snapshots"          # CSV export: snapshots
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/export/restores"           # CSV export: restores
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/export/api-usage"          # CSV export: API usage
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/export/efficiency"         # CSV export: efficiency
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/metering/export/chargeback"         # CSV export: chargeback report

# Runbook Dept Visibility endpoints (v1.52.0 - admin+)
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/runbooks/visibility"                # Full runbook×dept matrix
curl -X PUT -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"dept_ids":[1,2]}' "http://localhost:8000/api/runbooks/visibility/security_compliance_audit"   # Update dept list for runbook

# External Integrations endpoints (v1.52.0)
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/integrations"                      # List all integrations (admin+)
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/integrations/billing"              # Get single integration (admin+)
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"name":"billing","integration_type":"billing_gate","base_url":"https://billing.internal/v1/authorize","auth_type":"bearer","auth_credential":"<token>","enabled":true}' \
  "http://localhost:8000/api/integrations"                                                             # Create integration (superadmin)
curl -X PUT -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"enabled":false}' "http://localhost:8000/api/integrations/billing"                             # Update integration (superadmin)
curl -X DELETE -H "Authorization: Bearer <token>" "http://localhost:8000/api/integrations/billing"   # Delete integration (superadmin)
curl -X POST -H "Authorization: Bearer <token>" "http://localhost:8000/api/integrations/billing/test" # Test connectivity + persist status
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
- [`monitoring/container_watchdog.py`](../monitoring/container_watchdog.py) - Container health watchdog (alerts on crash/unhealthy)
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

# Monitoring Configuration
PF9_HOSTS=203.0.113.10,203.0.113.11,203.0.113.12,203.0.113.13
METRICS_CACHE_TTL=60
WATCHDOG_INTERVAL=60      # Docker container poll interval (seconds)
WATCHDOG_COOLDOWN=1800    # Min seconds between repeat alerts per container

# Email Notification Configuration (v1.11)
SMTP_ENABLED=true
SMTP_HOST=smtp.example.com
SMTP_PORT=25
SMTP_USE_TLS=false
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_ADDRESS=pf9-mgmt@pf9mgmt.local
NOTIFICATION_POLL_INTERVAL_SECONDS=120
NOTIFICATION_DIGEST_ENABLED=true
NOTIFICATION_DIGEST_HOUR_UTC=8
HEALTH_ALERT_THRESHOLD=50

# Metering Configuration (v1.15)
METERING_ENABLED=true
METERING_POLL_INTERVAL=15          # Collection interval in minutes
METERING_RETENTION_DAYS=90         # Data retention period
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