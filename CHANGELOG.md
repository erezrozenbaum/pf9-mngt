# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.83.17] - 2026-04-01

### Fixed
- **UI — Dashboard horizontal padding double-stack**: `LandingDashboard.css` previously set `padding: 2rem 2.5rem` on `.landing-dashboard`, which combined with the `0 20px` padding added by the new `.pf9-page-content` wrapper (introduced in v1.83.15) to produce ~60 px of left/right whitespace instead of the intended 20 px. Fixed by removing horizontal padding from `.landing-dashboard` (`padding: 2rem 0`) so the wrapper exclusively owns the horizontal gutter. The mobile breakpoint was corrected from `1rem` to `1rem 0` for the same reason. Background colour hardcodes replaced with `var(--color-background)` so light/dark themes apply correctly.

### Added
- **Docs — API Reference (Copilot / OpenAI section)**: Added comprehensive Copilot API documentation covering all seven endpoints: `POST /api/copilot/ask` (multi-backend: OpenAI, Anthropic, Ollama), `GET /api/copilot/suggestions`, `GET /api/copilot/history`, `POST /api/copilot/feedback`, `GET /api/copilot/config`, `PUT /api/copilot/config`, and `POST /api/copilot/test-connection`. Includes full request/response schemas and backend configuration notes.
- **Docs — DB Schema reference (`docs/DB_SCHEMA.md`)**: New document providing a comprehensive reference for the PostgreSQL schema — all 30+ tables (core resources, history tables, operational features) with column definitions, indexes, and the history-table pattern. Covers: domains, projects, users, servers, volumes, snapshots, networks, ports, floating IPs, flavors, images, routers, subnets, snapshot policies, snapshot jobs, user sessions, copilot config/history, drift rules/events, and the `v_volumes_full` enriched view.

## [1.83.16] - 2026-03-31

### Fixed
- **UI Layout**: Fixed sidebar alignment issue - removed problematic `box-shadow: 2px 0 8px rgba(0,0,0,0.06)` from `.pf9-sidebar` that was causing visual misalignment between sidebar border and main header content. Header and content now align perfectly with clean border edge.

## [1.83.15] - 2026-03-31

### Fixed
- **Docs Viewer — docs still empty in Kubernetes (wrong path resolution in `docs_routes.py`)**: `_DOCS_DIR` was computed as `Path(__file__).resolve().parent.parent / "docs"`. Inside the container, `docs_routes.py` lives at `/app/docs_routes.py` (placed there by `COPY api/ ./`), so `.parent.parent` resolves to `/` (the filesystem root) — making the code look for docs at `/docs` instead of `/app/docs`. The Dockerfile `COPY docs/ ./docs/` (added in v1.83.14) and the docker-compose volume mount both target `/app/docs`, so no docs were ever found in either environment. Fixed by removing the extra `.parent`: `_DOCS_DIR = Path(__file__).resolve().parent / "docs"` → `/app/docs` ✓.

### Changed
- **UI — layout structure fix (Pass 1)**: Removed the negative-margin hack on `.pf9-header` (`margin: 0 -20px`) that was causing a 1px misalignment between the sidebar border and the header. The `.pf9-page-body` no longer owns horizontal padding; instead a new `.pf9-page-content` wrapper (direct sibling of the sticky header) holds the `0 20px` padding for all page content. Header is now `position: sticky; top: 0; z-index: 10` — remains pinned as content scrolls.
- **UI — palette calibration (Pass 2)**: Corrected sidebar background tokens in both themes. Light: `--color-sidebar-bg` changed from `#EBF2FB` (saturated blue, from a different palette lineage) to `#EEF1F5` (neutral cool-gray, same family as `--color-background: #F8F9FA`). Dark: `--color-background` deepened from `#0F1419` to `#0D1117`; `--color-sidebar-bg` set to explicit `#161B22` instead of `var(--color-surface)` — establishes a clear three-level elevation: page canvas (`#0D1117`) → sidebar (`#161B22`) → cards/surfaces (`#1A1D23`).

## [1.83.14] - 2026-03-31

### Fixed
- **Docs Viewer — docs not visible in container (missing `/app/docs`)**: The `docs/` directory was never present inside the API container. Fixed by:
  1. Adding `COPY docs/ ./docs/` to `api/Dockerfile` so all `.md` files are baked into the image at build time (no NFS, no PVC, no ConfigMap required).
  2. Adding `./docs:/app/docs:ro` volume mount in `docker-compose.yml` so local dev reflects file changes without a rebuild.
  3. Creating `.dockerignore` to exclude `docs/images/` (PNG assets) and other non-API files from the build context, keeping the image lean.

## [1.83.13] - 2026-03-31

### Fixed
- **DocsTab.tsx — TypeScript build errors (TS6133)**: Removed unused `React` import (not required with the project's JSX transform) and removed unused `userRole` destructuring in the `DocsTab` component function signature. The prop remains declared in `DocsTabProps` for API compatibility; the component gates visibility using `isAdmin` only.

## [1.83.12] - 2026-03-31

### Fixed
- **VM Provisioning — Linux password not applied in Kubernetes (cloud-init userdata never executed)**: Nova server creates did not include `config_drive: true`. In Kubernetes/Platform9 deployments the Nova metadata service (`169.254.169.254`) is proxied by the Neutron DHCP agent; when that agent is absent or the VM has a static IP and the network is not yet fully initialised, cloud-init times out waiting for the metadata endpoint and runs with **no userdata** — the provisioned password, hostname, and sudo rules are never applied and the VM falls back to the image's default locked account. Fixed by adding `"config_drive": True` to the Nova server create body so cloud-init reads userdata from a local ISO attached at boot, with zero network dependency. This matches the behaviour cloud-init used in the local Docker environment (NoCloud datasource, reads from local disk).

### Added
- **Runbooks — Reset VM Password**: New built-in runbook `password_reset_console` (category: VM, risk: medium). Lets operators pick a VM from a live dropdown (grouped by project/tenant), enter a new password, and reset it via the Nova `changePassword` API. Optionally retrieves a noVNC/SPICE console URL so the operator can log in immediately. Works on Linux VMs with cloud-init and Windows VMs with cloudbase-init. Operators require admin approval; admins and superadmins execute immediately. The runbook is seeded on container startup and into the SQL migration for fresh deploys.
- **Docs Viewer tab**: New "📚 Docs" tab under the Technical Tools nav group. Left sidebar lists all `/docs/*.md` files grouped by category (Administration, Deployment, Architecture, etc.) with live search. Right panel renders full markdown (headings, tables, code blocks, blockquotes) and exposes a download button. Admin/superadmin sub-tab provides per-file department visibility control: select which departments can see each file, or leave unrestricted for everyone. Database: `doc_page_visibility(filename, dept_id)` — empty = globally visible. Migration: `db/migrate_docs.sql`. API: `GET /api/docs/`, `GET /api/docs/content/{filename}`, `GET/PUT /api/docs/admin/visibility`.

### Changed
- **`db/init.sql` — `password_reset_console` schema**: corrected parameter key from `server_id` to `vm_id` (matches `x-lookup` convention used by all VM runbooks); `risk_level` corrected from `high` to `medium`; `display_name` shortened to `Reset VM Password`. Approval policy for `admin` role corrected from `single_approval` to `auto_approve` (consistent with all other admin policies).
- **`db/init.sql` — nav_items**: Docs nav item (key `docs`, sort_order 3) added to `technical_tools` group alongside Backup and Runbooks.

## [1.83.11] - 2026-03-31

### Fixed
- **VM Provisioning — Linux password wrong on login (cloud-init chpasswd regression)**: `chpasswd.list` was passing the pre-hashed `$6$…` SHA-512 string as the list entry. `chpasswd` requires the `-e` flag to accept pre-hashed passwords; without it the hash string is set as the literal plaintext password. On cloud-init < 21.2 the `-e` flag is NOT added automatically even when a `$6$` prefix is detected. Fixed: `chpasswd.list` now uses the plain-text password (cloud-init hashes it internally); the `users[].passwd` field retains the SHA-512 hash for the initial user creation step, giving correct behaviour on all cloud-init versions.
- **VM Provisioning — Windows static IP not applied after sysprep**: The PowerShell static-IP block was conditioned on `gateway_ip` being non-empty. When the Neutron subnet has `gateway_ip: null` (e.g. isolated networks), `gateway_ip` was stored as `""` which is falsy — the entire block was skipped and Windows fell back to DHCP. Fixed: the block now fires whenever `fixed_ip` is set; the `-DefaultGateway` parameter is omitted only when `gateway_ip` is empty instead of aborting the whole configuration.

## [1.83.10] - 2026-04-01

### Fixed
- **VM Provisioning — Linux console password not applied**: cloud-init's `users[].passwd` field only sets the password when creating a new user. For cloud images that already include a default user (e.g. `ubuntu` on Ubuntu images), the user already exists so the password was silently ignored — leaving the account with no usable console password. Fixed `_build_cloudinit_linux` to also include a `chpasswd.list` block with the hashed password; the `chpasswd` module runs unconditionally in cloud-init and resets the password for both new and existing users.
- **VM Provisioning — Batches without approval requirement stuck as "pending_approval"**: When creating a batch with `require_approval: false`, the DB `INSERT` always set `approval_status = 'pending_approval'`, so the Execute button never appeared and the batch could not be run. Fixed to set `approval_status = 'approved'` immediately when `require_approval` is `False`.
- **VM Provisioning — Windows VM gets APIPA address instead of provisioned fixed IP**: When a `fixed_ip` was specified, Neutron reserved the port but Windows still relied on DHCP to learn its address — falling back to APIPA (169.254.x.x) if the Neutron DHCP agent was unreachable. `_build_cloudinit_windows` now accepts an optional `static_ip_config` dict (computed by querying the Neutron subnet when `fixed_ip` is set) and injects a PowerShell block into the cloudbase-init userdata that waits for the vNIC to come up and then applies the static IP/prefix/gateway/DNS via `New-NetIPAddress`, bypassing DHCP entirely.
- **VM Provisioning — Missing tooltips on batch action buttons**: Dry-run, Execute, Approve, Reject buttons in the batch actions bar lacked `title` attributes, so hovering showed nothing. Tooltips added to all action buttons (Dry-run, Execute, Approve, Reject, Re-run, Refresh, Delete, Expand/Collapse, Reset).

## [1.83.9] - 2026-03-31

### Fixed
- **VM Provisioning — 400 "Malformed request url" on boot volume create (root cause fix)**: v1.83.7 switched volume creation to use `admin_client` (service-project-scoped token) with an ORG1 project_id URL rewrite to avoid a Glance image-not-visible error. Platform9 Cinder strictly enforces that the auth token's project scope matches the URL project_id, so the cross-project URL rewrite produced `400 Malformed request url` regardless of URL construction. Root-cause fix: (1) before creating the boot volume, `admin_client.ensure_image_accessible(image_id)` promotes the image from `private` to `community` Glance visibility so any project-scoped token can reference it via `imageRef`; (2) boot volume creation is restored to `project_client.create_boot_volume()` (provisionsrv, ORG1-scoped token) — token scope now matches the Cinder URL's project_id, eliminating the 400.

## [1.83.8] - 2026-03-31

### Fixed
- **VM Provisioning — 400 "Malformed request url" on boot volume create (Kubernetes)**: `create_boot_volume`, `delete_volume`, and `cleanup_project_resources` all used `self.cinder_endpoint.rsplit("/", 1)[0]` to obtain the Cinder v3 base URL, assuming the catalog endpoint always ends with `/{project_id}`. In Docker/Platform9 DU environments the catalog includes the project_id suffix so the strip is correct. In Kubernetes deployments the Cinder catalog endpoint is `…/cinder/v3` (no suffix), so `rsplit` stripped `v3` instead — producing a malformed URL (`…/cinder/{project_id}/volumes`) that Cinder rejected with `400 Bad Request — Malformed request url`. Added `_cinder_base()` helper to `Pf9Client` that uses a regex to strip a trailing UUID segment only when present, leaving the URL unchanged when no project_id suffix exists. All three call-sites updated to use `_cinder_base()`.

## [1.83.7] - 2026-03-30

### Fixed
- **Customer Provisioning — 403 on Neutron subnet/security-group creation**: Platform9 Neutron enforces `network_owner` policy: the admin client's token is scoped to the `service` project, so passing `tenant_id` in the request body is insufficient — authorization fails 403 when the token scope doesn't match the target project. After creating the new project, `_run_provisioning` now calls `ensure_provisioner_in_project` then `scoped_for_project` to obtain a `provisionsrv` client scoped to the new tenant project. Subnet creation, security-group creation, and security-group rule creation all use this project-scoped `neutron_client`; provider-network creation and all Keystone/quota operations continue to use the admin `client`.
- **VM Provisioning — 400 "Invalid image identifier" on boot volume create**: `project_client.create_boot_volume()` used the provisionsrv token scoped to the tenant project. When Cinder internally called Glance to resolve the `imageRef`, the image was in the admin/service project and not visible to the tenant scope → `400 Bad Request`. Fixed by adding an optional `project_id` parameter to `create_boot_volume`: when supplied, the Cinder URL is rewritten to target the tenant project's API path while retaining the caller's (admin) auth token, which can access all Glance images. `_execute_batch_thread` now calls `admin_client.create_boot_volume(project_id=project_id)` instead of `project_client.create_boot_volume()`.

- **Notification Settings — "Send Test Email" falsely reports SMTP disabled**: `send_test_email` endpoint checked the module-level `SMTP_ENABLED` constant (frozen at container start from the `SMTP_ENABLED` env var). On Kubernetes the env var is unset/false, but SMTP was configured at runtime via the Settings UI (stored in `system_settings` DB). Changed the guard to call `get_smtp_config()` — the same DB-first helper already used by `send_email()` and `get_smtp_settings()` — so the check reflects the live configuration.
- **Admin Tools → System Config — SMTP card shows Disabled when configured at runtime**: `GET /admin/system-config` built the SMTP section from the same frozen env-var constants. Changed to `get_smtp_config()` so the card reflects DB-stored settings configured via the Notification Settings UI, matching the Notification Settings page.


### Fixed
- **VM Provisioning — 500 on batch create**: `vm_provisioning_batches` table is created lazily on first API call by `_ensure_tables()`, which lacked the `region_id` column added in v1.83.3's multi-cluster migration. Added `ALTER TABLE vm_provisioning_batches ADD COLUMN IF NOT EXISTS region_id TEXT` to `_ensure_tables()` so the column is applied idempotently on every pod restart.
- **VM Provisioning — DB schema for existing deployments**: `db/migrate_multicluster.sql`'s DO-block guard skipped the `region_id` ALTER on environments where the table was created *after* that migration ran. Created `db/migrate_v1_83_6.sql` so `run_migration.py` (Docker and Kubernetes) applies the column to those environments on next deploy.
- **DB init.sql — unguarded ALTER**: `init.sql` contained a bare `ALTER TABLE vm_provisioning_batches ADD COLUMN IF NOT EXISTS region_id` without an existence check. On a fresh Docker install the table doesn't exist yet (created lazily), causing the PostgreSQL init script to fail. Wrapped in a `DO $$ IF EXISTS ... END $$` guard matching the pattern used in `migrate_multicluster.sql`.
- **Customer Provisioning — 403 on subnet creation**: `_run_provisioning` called `get_client()` which always returns the default-region client. When `req.region_id` targets a non-default PF9 region, the default-region service token was used against that region's Neutron endpoint, causing `403 Forbidden`. Changed to `get_region_client(req.region_id)` which selects the correctly-scoped client for the target region (falls back to default when `region_id` is `None`).

## [1.83.5] - 2026-03-30

### Fixed
- **Metering — SQL column names**: Fixed three endpoints (`chargeback-summary`, `export/chargeback-excel`, `tenant-growth`) that referenced non-existent columns (`vcpus`, `ram_mb`, `flavor`). Correct column names are `vcpus_allocated`, `ram_allocated_mb`, `flavor` (from `metering_resources`).
- **Metering — interval parameterization**: Fixed psycopg2 interval syntax in `chargeback-summary` and `tenant-growth` from `interval '%s hours'` (invalid) to `(%s * interval '1 hour')` / `(%s * interval '1 month')`.
- **Metering — compliant count always 0**: `COUNT(*) FILTER (WHERE is_compliant = true)` returns 0 when `is_compliant IS NULL` (snapshot has no compliance policy assigned). Changed to `IS TRUE`/`IS FALSE` and added `unknown_count` for snapshots with no policy; UI now shows a grey "No Policy" card when applicable.
- **Users — inventory tab empty**: `GET /api/auth/users` response used key `"data"` but the frontend `PagedResponse<User>` type expects `"items"`. Changed response key to `"items"`.
- **VM Provisioning — password validation mismatch**: Frontend validated minimum password length at 12 characters while backend requires only 8. Aligned frontend to `>= 8`; also tightened VM name suffix regex to `^[a-z0-9][a-z0-9-]*$`.
- **Metering export — wrong button label**: `ExportCard` always showed "Download CSV" regardless of the selected export format. Label is now dynamic: "Download PDF", "Download Excel", or "Download CSV".
- **Drift detection — deletions not detected**: `db_writer.py` never flagged resources that disappeared from OpenStack. Added deletion detection: load all existing IDs before upsert, compute the diff, emit `drift_event` records and auto-tickets for each deleted resource.
- **SMTP — no runtime config override**: SMTP settings were baked into environment variables at container start. Added `get_smtp_config()` helper that checks `system_settings` DB table first. New `POST /api/notifications/smtp-config` endpoint and Admin → Notification Settings UI form to update SMTP config at runtime without restart.
- **Dependency graph — missing resource types**: "View Dependencies" button was absent for Subnets, Ports, Floating IPs, and Security Groups. Added inline buttons/columns for all four resource types wired to `setGraphTarget`.
- **Admin — Roles tab cannot assign users**: Roles tab showed a static list with no action. Added an "➕ Assign User" inline form per role that calls `POST /api/auth/users/{username}/role`.
- **UI — dark mode nav active item invisible**: `.pf9-nav-group-active` used a hardcoded `rgba(25,118,210,0.07)` that was near-invisible on the dark sidebar background. Added proper dark-mode CSS overrides for active nav items, hover states, and tab highlights.
- **Snapshot monitor — stuck at 0%**: When a run starts with `total_volumes=0` or no batches yet, the progress bar showed a static "0%" label. Now displays an animated indeterminate bar with "Starting…" label until real progress data is available.
- **Customer provisioning — 500 on submit**: `dns_nameservers` from `NetworkConfig` is a `List[str]` but the legacy field builder called `.split(",")` on it (valid only for strings), raising `AttributeError` before the job INSERT, resulting in an uncaught HTTP 500. Fixed to use the list directly.

## [1.83.4] - 2026-03-30

### Fixed
- **CI — frontend-typecheck**: Resolved all 200+ TypeScript errors caught by the `tsc -b` CI job across 14 source files (`App.tsx`, `UserManagement.tsx`, `VmProvisioningTab.tsx`, `RunbooksTab.tsx`, `TicketsTab.tsx`, `MeteringTab.tsx`, `MigrationPlannerTab.tsx`, `ResourceManagementTab.tsx`, `CustomerProvisioningTab.tsx`, `GroupedNavBar.tsx`, `DriftDetection.tsx`, `TenantHealthView.tsx`, `SnapshotRestoreWizard.tsx`, `graph/DependencyGraph.tsx`, `migration/ProjectSetup.tsx`, `migration/SourceAnalysis.tsx`). Root causes: untyped `useState([])` arrays inferred as `never[]`, missing optional fields on `Server`/`Snapshot`/`Subnet`/`Hypervisor` types, `PagedResponse<User>.data` should be `.items`, unused local variables and parameters, and implicit `any` in event handlers.

## [1.83.3] - 2026-03-30

### Added
- **Metering — Chargeback per-tenant tab**: New `🧾 Chargeback` sub-tab in Metering shows per-tenant cost breakdown (vCPUs, RAM, estimated cost) with currency and billing-period selectors. Backed by new `GET /api/metering/chargeback-summary` endpoint.
- **Metering — Tenant Growth tab**: New `📈 Tenant Growth` sub-tab shows month-over-month VM count changes per tenant as a pivot table. Backed by new `GET /api/metering/tenant-growth` endpoint.
- **Metering — Excel export (row per VM)**: `GET /api/metering/export/chargeback-excel` generates a two-sheet workbook: "VM Details" (one row per VM with flavor, vCPUs, RAM, hours, cost) and "Tenant Summary".
- **Metering — PDF export**: `GET /api/metering/export/chargeback-pdf` generates a landscape A4 PDF of the chargeback summary using reportlab.
- **Metering — Email export**: `POST /api/metering/export/send-email` emails the chargeback report (Excel/PDF/CSV) as an attachment via the configured SMTP server.
- **Domains — Dependency graph**: Clicking a domain in the Domains inventory tab now shows a Domain Details panel with a `🕸️ View Dependencies` button that opens the dependency graph scoped to that domain.
- **Users — Dependency graph**: Clicking a user row in the Users inventory tab shows a User Details panel with a `🕸️ View Domain Dependencies` button.
- **Admin — Department rename**: Department rows in Admin → Departments now have inline edit support (✏️ Edit → name/description/sort-order inputs → 💾 Save / ✖ Cancel).
- **LDAP — Custom role mapping**: The Group → PF9 Role input in LDAP Sync Settings now accepts any freeform role name in addition to the preset suggestions (viewer, operator, technical, admin).

### Fixed
- **API — Swagger UI inaccessible at `/api/docs` in K8s**: FastAPI's built-in Swagger, ReDoc, and OpenAPI schema endpoints were served at `/docs`, `/redoc`, and `/openapi.json` respectively, while all application routes live under `/api/...`. In K8s (no path-rewriting ingress) requests to `/api/docs` reached the auth middleware as `/api/docs`, which was not in the bypass list and returned 401 "Not authenticated". Fixed by changing `docs_url`, `redoc_url`, and `openapi_url` to `/api/docs`, `/api/redoc`, and `/api/openapi.json` in the FastAPI app constructor, and updating the middleware bypass list to match.
- **Dashboard — CPU/Memory widgets showing 0% in K8s**: `_calculate_metrics_summary` crashed with `AttributeError` when the metrics cache file was absent (K8s pod restarts). All `metrics_data.get(...)` accesses are now guarded behind `if metrics_data:`, and the DB fallback (hypervisors table) runs correctly.
- **Dashboard — VM Hotspot empty in K8s**: `get_vm_hotspots` had no fallback when the metrics cache was unavailable. Added a DB fallback that JOINs `servers`, `projects`, `domains`, `flavors`, and `hypervisors` to compute allocation-based CPU and memory percentages.
- **Snapshot monitor — progress bar stuck at 0%**: `get_active_run_progress` now dynamically computes `progress_pct` from `(snapshots_created + snapshots_failed + volumes_skipped) / total_volumes` when the stored value is 0 or None.
- **UI — Resource History panel bleeding into all inventory tabs**: Added `activeTab === "history"` guard so the Resource History results panel only renders when the History tab is active.
- **UI — Navigation sidebar not reflecting admin changes**: Added a `useEffect` that calls `refreshNavigation()` whenever the user leaves the Admin tab, ensuring department/nav renames are immediately visible in the sidebar.

## [1.83.2] - 2026-03-29

### Fixed
- **UI — Resource History bleeding into Migration Planner**: `migration_planner` and `cluster_management` added to the `hideDetailsPanel` list. The persistent history state no longer renders on unrelated pages.
- **API — Dashboard CPU/Memory 0% and Metrics Hosts 0**: `_calculate_metrics_summary` now falls back to the `hypervisors` table (`vcpus_used`, `memory_mb_used`) when the metrics cache is empty (e.g. in K8s where the monitoring service runs in a separate pod and writes to a different filesystem).
- **API — Top Hosts all N/A**: The inventory fallback path in `get_top_hosts_utilization` now computes `cpu_utilization_percent` and `memory_utilization_percent` directly from `hypervisors.raw_json->vcpus_used / vcpus` instead of returning `null`. Results are sorted by the requested metric.
- **API — VM Storage shows 0% instead of N/A**: `storage_used_gb` and `storage_usage_percent` in the `/monitoring/vm-metrics` DB fallback are now `null` (previously hard-coded `0`), so the UI correctly displays N/A rather than a misleading 0%.
- **DB writer — Drift auto-ticket creation**: `_auto_ticket_for_drift` now resolves the target department dynamically. If the preferred department ("Engineering" / "Tier2 Support") does not exist — as on a fresh K8s install — it falls back to the first available department so the ticket is always created.
- **Metering worker — 0 VMs metered**: Added a third fallback to `collect_resource_metrics`: if both the monitoring service and the API HTTP endpoint are unreachable, the worker queries the `servers`/`flavors`/`hypervisors` tables directly (same logic as `/monitoring/vm-metrics`). This ensures VM records flow into `metering_resources` and `metering_efficiency` even in K8s environments where inter-pod HTTP calls may fail.

## [1.83.1] - 2026-03-29

### Fixed
- **UI — sidebar collapse**: All nav groups (including the default `is_default` group) can now be toggled closed by clicking their header again. Previously the default group was permanently pinned open.
- **UI — light mode sidebar**: Sidebar now uses a distinct blue-tinted background (`#EBF2FB` / `--color-sidebar-bg`) and a matching expanded-items tint (`#F4F8FE`), visually separating it from the white page body. Dark mode is unchanged.
- **API — `/monitoring/vm-metrics` fallback formula**: The `cpu_usage_percent` / `memory_usage_percent` expressions previously returned `NULL` when OpenStack reported `vcpus_used = 0` (division by zero via `NULLIF`), silently causing `collect_efficiency_scores` to skip all VMs and record 0% efficiency. Replaced with a simpler VM-allocation-share formula (`fl.vcpus / h.vcpus × 100`) that always returns a non-NULL estimate when flavor and hypervisor data are available.
- **DB writer — history tracking silent failures**: `_upsert_with_history` now logs a `WARNING` message (visible in pod/container logs) when a history insert is skipped due to a missing column or table, guiding operators to the required migration file.
- **API**: Added missing `inventory` resource rows to `role_permissions` for all roles; `GET /system-metadata-summary` was returning 403 for all users including superadmin.
- **UI**: Moved Copilot FAB and Dependency Graph drawer outside the `pf9-app` scroll container — fixes FAB stretching full-width and graph drawer opening at bottom of page instead of full-screen overlay.

## [1.83.0] - 2026-03-29

### Changed
- **UI: navigation migrated from horizontal two-row bar to vertical collapsible sidebar** (`pf9-ui/src/components/GroupedNavBar.tsx`, `pf9-ui/src/App.tsx`, `pf9-ui/src/App.css`)
  — The top two-row navigation (group pills row + tab items row) has been replaced with a
  fixed 240 px left sidebar. Group headers are collapsible accordion sections; tab items
  appear as indented rows beneath the active group. All existing RBAC visibility rules,
  department controls, `is_action` accent styling, and drag-to-reorder behaviour are fully
  preserved — only the rendering axis changed (horizontal → vertical).
  The main content area (`pf9-page-body`) now occupies the remaining viewport width.

### Added
- **Architecture diagram in README** — ASCII block replaced with `docs/images/Architecture.png`,
  a full system-boundary diagram showing ingress, API, background workers, and external Platform9
  integration.

---

## [1.82.33] - 2026-03-29

### Fixed
- **monitoring: remove `TrustedHostMiddleware` blocking Kubernetes kubelet health probes** (`monitoring/main.py`)
  — The middleware added in v1.82.32 rejected requests from kubelet node IPs,
  causing `/health` to return 400 Bad Request on every readiness probe and putting the
  monitoring pod into a restart loop. The monitoring service is internal-only behind the nginx
  ingress; host validation for external traffic is already handled by nginx. Removed the
  middleware entirely.

---

## [1.82.32] - 2026-03-29

### Fixed
- **API startup/shutdown: deprecated `@app.on_event` replaced with lifespan** (`api/main.py`, `monitoring/main.py`)
  — FastAPI deprecated `@app.on_event("startup"/"shutdown")` in v0.93+. Both apps now use the
  recommended `@asynccontextmanager` lifespan context manager, eliminating deprecation warnings
  on every startup.
- **Pydantic v2: all `@validator` decorators upgraded to `@field_validator`** (`api/main.py`,
  `api/notification_routes.py`, `api/provisioning_routes.py`, `api/migration_routes.py`,
  `api/resource_management.py`, `api/snapshot_management.py`, `api/ticket_routes.py`)
  — The project uses Pydantic `==2.9.2` but retained v1 compatibility shims. All models now
  use the native v2 `@field_validator` / `@model_validator` API, removing deprecation warnings
  and aligning with Pydantic v2 semantics. `validate_retention_map` in
  `snapshot_management.py` updated to use `ValidationInfo`.
- **LDAP sync rate limiter: Redis-backed sliding window** (`api/ldap_sync_routes.py`)
  — The previous in-memory `_rate_store` dict was per-process: with multiple gunicorn workers
  or K8s pods the effective limit was `N × 10 req/min`. Rate-limit state is now stored in
  Redis using a sorted-set sliding window; falls back to the per-process dict when Redis is
  unavailable, preserving Docker Compose dev behaviour.
- **Dashboard queries: fragile `region_filter.replace()` removed** (`api/dashboards.py`)
  — Five SQL COUNT queries built the `WHERE` clause from a bare string replace on an `AND`
  prefix. Replaced with explicit `region_where` / `region_and` variables, making each query
  safe under any future refactor.
- **Docker Compose: `snapshot_worker` and `scheduler_worker` now use Docker secrets** (`docker-compose.yml`)
  — Both workers received `PF9_PASSWORD`, `PF9_DB_PASSWORD`, and `JWT_SECRET_KEY` as plain
  environment variables (visible in `docker inspect`). They now mount the `pf9_password`,
  `db_password`, and `jwt_secret` secret files already defined in the `secrets:` block, matching
  the pattern used by `ldap_sync_worker` and `pf9_api`.
- **`get_auth_db_conn()` raises `RuntimeError`** (`api/auth.py`)
  — The deprecated helper silently leaked pooled connections when called. It now raises
  `RuntimeError` to surface any remaining callers immediately.
- **`migration_engine.py` docstring mojibake fixed** (`api/migration_engine.py`)
  — Module docstring contained `Γאפ` / `Γזע` / `Γאó` garbled from a Windows-1252 / UTF-8
  encoding mismatch. Replaced with correct ASCII punctuation.
- **Config validator: Docker secret files accepted for credential vars** (`api/config_validator.py`)
  — The startup validator raised a false-alarm error for `PF9_DB_PASSWORD`, `PF9_PASSWORD`,
  and `JWT_SECRET_KEY` when those values were supplied via Docker secrets (file under
  `/run/secrets/`) rather than environment variables. A `_var_is_set()` helper now checks
  both sources, removing the false-alarm without altering validation for genuinely missing creds.
- **`monitoring/main.py`: `TrustedHostMiddleware` wildcard removed** (`monitoring/main.py`)
  — `allowed_hosts=["localhost", "127.0.0.1", "*"]` negated the middleware. Replaced with an
  explicit list of Docker Compose (`pf9_monitoring`, `pf9_api`) and Kubernetes (`pf9-monitoring`,
  `pf9-api`) service name variants.

### Notes
- `/api-metrics` reports per-worker counters. In a multi-worker gunicorn or multi-pod K8s
  deployment each worker/pod shows its own slice of traffic — there is no cross-process
  aggregation. See ADMIN_GUIDE.md for details.

## [1.82.31] - 2026-03-27

### Fixed
- **Monitoring: Avg VM CPU / Avg VM Memory always show 0%** (`monitoring/prometheus_client.py`)
  — The metrics-cache payload written to disk had no `vm_stats` key; the frontend reads
  `vm_stats.avg_cpu` and `vm_stats.avg_memory`. The cache write now computes per-collection
  averages and maxima for both VMs and hosts and stores them in the summary under the field
  names the UI expects (`avg_cpu` / `avg_memory`).
- **Monitoring: VM Storage always shows 0%** (`monitoring/prometheus_client.py`)
  — `storage_usage_percent` is a Pydantic `@property` rather than a model `Field`; calling
  `vm.dict()` omitted it from the serialised cache. Each VM dict is now patched with the
  computed property value before writing.
- **Metering: collects every 15 minutes instead of 60 seconds** (`metering_worker/main.py`)
  — `effective_interval = max(interval_min * 60, POLL_INTERVAL)` caused the DB default of
  15 min to override the `METERING_POLL_INTERVAL=60` env-var. Changed to
  `effective_interval = POLL_INTERVAL` so the Helm-controlled env var governs the cadence;
  `collection_interval_min` is now treated as a display-only admin setting.
- **API /monitoring/summary returns wrong field names** (`api/main.py`)
  — DB-fallback endpoint returned `avg_cpu_usage` / `avg_memory_usage` but the UI and the
  monitoring-service payload both use `avg_cpu` / `avg_memory`. Renamed to match.
- **TypeScript `MetricsSummary` type inconsistency** (`pf9-ui/src/App.tsx`)
  — `MetricsSummary.vm_stats` declared `avg_cpu_usage` / `avg_memory_usage` while the
  render code read `avg_cpu` / `avg_memory`. Updated the type to match the render code and
  the backend payload.

## [1.82.30] - 2026-03-26

### Fixed
- **Metering: VMs Metered always shows 0** (`metering_worker/main.py`)
  — The monitoring service's prometheus-client collects metrics by scraping hypervisor endpoints
  on the IPs listed in `PF9_HOSTS`. When `PF9_HOSTS` is empty (default Helm value), the service
  returns an empty VM list and the metering worker recorded 0 VM rows on every cycle. Added a
  fallback: when `MONITORING_URL/metrics/vms` returns 0 VMs the worker now calls the API's
  DB-backed `/monitoring/vm-metrics` endpoint which is always populated from the `servers`,
  `flavors`, and `hypervisors` inventory tables. Extended field mapping to cover the API response
  shape (`cpu_total` → vcpus, `memory_allocated_mb` → ram, `storage_allocated_gb` → disk).

## [1.82.29] - 2026-03-26

### Fixed
- **Metering: project/domain filter dropdowns empty** (`api/metering_routes.py`)
  — `get_metering_filters` only returned values present in `metering_resources`; on a fresh
  deployment that table is empty so both dropdowns showed nothing. Now merges the `projects` and
  `domains` tables so filter options are immediately populated from the identity inventory.
- **Prometheus UI redirects to SPA `/query` instead of opening Prometheus** (`k8s/monitoring/prometheus-values.yaml`)
  — `externalUrl` and `routePrefix` were absent from `prometheusSpec`; Prometheus generated an
  absolute redirect to `/graph` which bypassed nginx and landed on the React SPA. Added
  `externalUrl: "https://pf9-mngt.ccc.co.il/prometheus"` and `routePrefix: "/"` to both
  `prometheusSpec` and `alertmanagerSpec`. **Requires** `helm upgrade kube-prometheus-stack
  prometheus-community/kube-prometheus-stack -n monitoring -f k8s/monitoring/prometheus-values.yaml`
  on the cluster.
- **Inventory: Projects and Domains tabs missing** (`db/migrate_nav_inventory_domains_projects.sql`)
  — Nav items for `domains` and `projects` were in the `customer_onboarding` group; moved to
  `inventory` so they appear under Inventory in the sidebar. Migration runs automatically on next
  API pod restart.

## [1.82.28] - 2026-03-26

### Fixed
- **API: TrustedHostMiddleware rejects internal K8s pod-to-pod requests with 400** (`api/main.py`)
  — `_trusted_hosts` only listed `pf9_api`/`pf9_ui` (Docker Compose underscore names). Kubernetes
  service names use dashes (`pf9-api`, `pf9-ui`), so all intra-cluster requests (metering-worker
  → API `/metrics`) were rejected with `400 Bad Request`. Added the dash-form names for `api`,
  `ui`, and `monitoring` to the hardcoded seed set so both environments work without wildcards.
- **Monitoring: PrometheusClient collection loop never started** (`monitoring/main.py`)
  — `startup_event` created the `PrometheusClient` instance but never called `start_collection()`,
  so the libvirt/node-exporter scraping background task never ran. Added
  `await prometheus_client.start_collection()` at the end of startup and a matching
  `shutdown_event` that calls `stop_collection()` for clean task cancellation.
- **Monitoring: collected VM/host metrics not persisted to disk cache** (`monitoring/prometheus_client.py`)
  — After each collection cycle `_collect_all_metrics` only updated the in-memory `vm_cache` /
  `host_cache` dicts; the API endpoints (`/metrics/vms`, `/metrics/hosts`) read solely from
  `/tmp/cache/metrics_cache.json`, so collected data was never served. Now writes an atomic
  JSON snapshot (via temp-file + `os.replace`) to that path after every successful cycle.

## [1.82.27] - 2026-03-26

### Fixed
- **CI: `sed` regex misses single-quoted per-service tag overrides** (`.github/workflows/release.yml`)
  — The `update-values` job used `"?` in the sed pattern, which only matches double-quote
  characters. Per-service tag overrides written with single quotes (e.g. `tag: 'v1.82.21'`) or
  with no quotes were not being cleared, leaving `pf9-api` and `pf9-snapshot-worker` stuck on
  `v1.82.21` across multiple deployments. Updated the pattern to `["']*` so it handles
  unquoted, double-quoted, and single-quoted values, and relaxed the post-colon whitespace
  to `[[:space:]]*` for robustness.

## [1.82.26] - 2026-03-26

### Fixed
- **CI: YAML syntax error in `release.yml` crashing Release workflow** (`.github/workflows/release.yml`)
  — A Python3 heredoc (`<<'PYEOF'`) inside a YAML `run: |` block triggered the GitHub Actions
  YAML parser's merge-key handler, producing *"You have an error in your yaml on line 245"*.
  Release runs #96 and #97 failed immediately without executing any jobs. Fixed by replacing the
  heredoc with a single `sed -E` one-liner that clears versioned per-service tag overrides.

## [1.82.25] - 2026-03-26

### Fixed
- **CI: per-service tag overrides blocking api/snapshot-worker rollouts** (`.github/workflows/release.yml`)
  — The `update-values` job only patched `global.imageTag` via `sed`, leaving any hardcoded
  per-service `tag:` overrides (e.g. `api.image.tag: v1.82.21`) untouched in the deploy repo's
  `values.prod.yaml`. Those overrides shadow `global.imageTag`, causing specific services to stay
  on old images after a release (observed: `pf9-api` and `pf9-snapshot-worker` stuck at v1.82.21
  while all other workers updated to v1.82.24). The job now also clears all versioned per-service
  tag overrides with a Python regex pass, ensuring every service falls back to `global.imageTag`.

## [1.82.24] - 2026-03-26

### Security
- **Upgrade picomatch 4.0.3 → 4.0.4** (`pf9-ui/package-lock.json`) — Resolves two high-severity
  ReDoS vulnerabilities: GHSA-c2c7-rcms-vvq1 (Repos vulnerability via extglob quantifiers) and
  GHSA-3y7f-55p6-f55q (Method Injection in POSIX Character Classes). Detected by CI `npm audit`.

## [1.82.23] - 2026-03-26

### Fixed
- **Session restore on page reload** (`pf9-ui/src/App.tsx`) — The on-mount session-check
  `useEffect` validated the stored token for expiry but never called `setIsAuthenticated(true)`
  for valid sessions. Every page refresh forced a re-login and caused all data-loading effects
  to fire without a Bearer token, resulting in 401 responses from the API for `/domains`,
  `/tenants`, `/os-distribution`, and every other protected endpoint.
- **401 on `/domains` / `/tenants` / `/os-distribution` before login** (`pf9-ui/src/App.tsx`)
  — `loadDomains` and `loadTenants` effects had no authentication guard and fired on component
  mount (before login). Auth tokens were absent at that point, so the backend returned 401.
  Both effects now guard on `isAuthenticated` and are re-run when it becomes `true`.
- **`/metrics/vms`, `/metrics/hosts`, `/metrics/summary`, `/metrics/alerts` returning 404**
  (`k8s/helm/pf9-mngt/templates/ingress.yaml`) — The K8s ingress had `metrics` in both the
  `/metrics/.*` → `pf9-monitoring` rule AND the broad pf9-api regex. NGINX Ingress selects the
  rule whose path pattern is longest (highest specificity), so the API rule won and FastAPI
  returned 404 for all sub-paths. Removed `metrics` from the pf9-api regex; `/metrics/.*` now
  routes exclusively to `pf9-monitoring`. The bare `/metrics` Prometheus endpoint is only
  scraped cluster-internally via `ServiceMonitor` and does not need ingress exposure.
- **Logo not persisting across pod restarts in Kubernetes** (`api/main.py`) — The logo upload
  endpoint wrote the file to `/app/static/` (ephemeral container storage) and stored only the
  `/static/<filename>` URL in the DB. After a pod restart the file was gone but the URL
  remained, causing an endless 404.  The upload endpoint now also saves the raw bytes as
  `base64` in `app_settings` (keys `company_logo_data` and `company_logo_mime`). The
  `GET /settings/branding` endpoint detects a missing static file and returns a `data:` URL
  built from the stored base64 instead, so the logo survives pod restarts without any PVC.
  **Action required after deploy**: re-upload your logo once via Admin Tools → Branding to
  populate the new DB keys; subsequent pod restarts will then serve it automatically.
- **Default Landing Tab not visible in Visibility settings**
  (`pf9-ui/src/components/UserManagement.tsx`) — The per-department Default Landing Tab
  dropdown was only available on the Departments tab, not on the Visibility tab where admins
  spend most of their time. It is now inline in the Visibility section header row for each
  department, showing only the nav items that are currently checked visible for that
  department.

## [1.82.22] - 2026-03-25

### Security
- **Service user emails removed from `values.yaml`** — `SNAPSHOT_SERVICE_USER_EMAIL` and
  `PROVISION_SERVICE_USER_EMAIL` were stored in `values.yaml` (even as empty strings, the field
  was a prompt to fill in a real value). Both are now sourced exclusively from sealed secrets:
  `pf9-snapshot-creds` (key `service-user-email`) and `pf9-provision-creds` (key
  `service-user-email`). The Helm templates (`api/deployment.yaml`,
  `workers/snapshot-worker.yaml`) mount the value via `secretKeyRef` with `optional: true`.
  Storing real email addresses in `values.yaml` would have exposed your organisation's
  identity in public repository history.

### Fixed
- **Snapshot / provisioning wrong tenant bug** — When `SNAPSHOT_SERVICE_USER_EMAIL` or
  `PROVISION_SERVICE_USER_EMAIL` were empty, `ensure_service_user("")` silently raised a
  `RuntimeError` (Keystone returns an empty list for `GET /users?name=`), which was caught by
  a bare `except Exception` block that printed "Falling back to admin session". The fallback
  set `project_id` to the service user's own tenant instead of the VM's actual tenant, so
  every Cinder snapshot and every provisioned volume landed in the wrong project. Moving the
  emails into sealed secrets (always non-empty) fixes the root cause.

### Added
- **Monitoring ingress** (`k8s/monitoring/prometheus-values.yaml`) — Prometheus, AlertManager,
  and Grafana are now reachable through the existing nginx-ingress controller on path prefixes:
  `/prometheus`, `/alertmanager`, and `/grafana` respectively. No new DNS record required — the
  same hostname as the main app is reused. Grafana service changed from `NodePort 30300` to
  `ClusterIP`; `GF_SERVER_ROOT_URL` and `GF_SERVER_SERVE_FROM_SUB_PATH` are set automatically.

### Changed
- **`docs/KUBERNETES_GUIDE.md` → v4.0** — Full rewrite based on real deployment experience.
  Reorganised into 15 ordered sections: cluster pre-checks (storage class, NFS gotchas) →
  add-ons → DNS → credential generation → namespace → all secrets (including both service-user
  email secrets with explanations) → Helm install → DB migration → first LDAP admin → verify →
  optional monitoring stack with ArgoCD + Day-2 operations → common issues. Version status
  updated to `Production Ready (v1.82.22)`.
- **`docs/DEPLOYMENT_GUIDE.md`** — K8s callout notes added to the Snapshot Service User and
  VM Provisioning Service User sections, directing K8s deployers to use sealed secrets instead
  of `values.yaml`. Migration section updated to use `run_migration.py` as the primary method.
- **`docs/LINUX_DEPLOYMENT_GUIDE.md` → v1.1** — Migration section updated: the manual `for f
  in db/migrate_*.sql` loop replaced with `docker exec pf9_api python3 run_migration.py` as
  the recommended approach. Cross-reference to `KUBERNETES_GUIDE.md` added at the top.
- **`README.md`** — "Kubernetes Deployment" feature status updated from `⬜ Planned` to
  `✅ Production` (Helm + ArgoCD + Sealed Secrets). Maturity statement updated to 16 of 17
  tracked features production-grade.
- **`k8s/sealed-secrets/README.md`** — `--from-literal=service-user-email=<CHANGE_ME>` added
  to both `pf9-snapshot-creds` and `pf9-provision-creds` kubeseal command blocks. The
  generated `*.yaml` sealed manifests themselves are gitignored — they are cluster-specific
  and belong in your private deploy repo, not here.

---

## [1.82.21] - 2026-03-25

### Fixed
- **Grafana CrashLoopBackOff on NFS** — `k8s/monitoring/prometheus-values.yaml`: disabled `initChownData` init container. The NFS provisioner exposes a read-only `.snapshot` directory inside the volume; Grafana's default `busybox` init container runs `chown -R 472:472 /var/lib/grafana` which hits `.snapshot` and exits with code 1. Disabled the init container — NFS already creates the directory with correct ownership.

---

## [1.82.20] - 2026-03-25

### Fixed
- **ArgoCD: StatefulSet OutOfSync noise** — `k8s/argocd/application.yaml` now includes `ignoreDifferences` for `StatefulSet /spec/volumeClaimTemplates`. Kubernetes treats `volumeClaimTemplates` as immutable after creation, so any change to `storageClass` in Helm values causes a permanent OutOfSync indicator in ArgoCD even after a successful sync. The running PVCs are unaffected.

---

## [1.82.19] - 2026-03-25

### Fixed
- **K8s: all PVCs stuck in Pending** — `values.yaml` had `storageClass: standard` for all five persistent volumes (PostgreSQL, LDAP data, LDAP config, backup-worker, and reports). The cluster's default storage class is `nfs-pf9`; `standard` does not exist, so every PVC created by Helm was permanently unbound. Updated all five `storageClass` values to `nfs-pf9`.

### Added
- **Phase 4 Observability** — `k8s/monitoring/prometheus-values.yaml` and `k8s/monitoring/loki-values.yaml` added. Prometheus + Grafana + AlertManager (via `kube-prometheus-stack`) and Loki + Promtail (via `loki-stack`) sized for the 3-node × 4 CPU / 8 GB cluster. Custom AlertManager rules included: `PodCrashLoopBackOff`, `PodNotReady`, `PVCAlmostFull`, `PVCFull`, `API5xxHighRate`, `NodeMemoryHighUsage`.

---

## [1.82.18] - 2026-03-25

### Fixed
- **K8s: RVTools Excel files not downloadable** — Root cause: `scheduler-worker` mounted an `emptyDir` (pod-local ephemeral storage) for `/mnt/reports`, so generated `.xlsx` files were invisible to the API pod. The API pod had no reports volume mount at all. Fixed by:
  - Adding `k8s/helm/pf9-mngt/templates/reports-pvc.yaml` — new `PersistentVolumeClaim` (`pf9-reports`, `ReadWriteMany`).
  - Updating `templates/api/deployment.yaml` to mount the PVC at `/mnt/reports`.
  - Updating `templates/workers/scheduler-worker.yaml` to reference the PVC instead of `emptyDir`.
  - Both mounts use a Helm conditional: `{{- if .Values.reports.persistence.enabled }}` so the PVC is opt-in; falls back to `emptyDir` when disabled.

### Added
- **RVTools file retention / rotation** (`scheduler_worker/main.py`, `api/reports.py`, `values.yaml`, `scheduler-worker.yaml`):
  - New `RVTOOLS_RETENTION_DAYS` env var (default: `30`). After each inventory run the scheduler deletes `.xlsx` files older than the configured window.
  - New `GET /api/reports/rvtools/retention` — returns current retention setting.
  - New `PUT /api/reports/rvtools/retention` — updates retention (admin/superadmin only); persisted to `system_settings` table.
  - UI: Reports → RVTools Exports tab now shows a **File Retention** input card (admin-only) to view and update the retention window.
- **Per-department default landing tab** (`api/navigation_routes.py`, `pf9-ui/src/components/UserManagement.tsx`):
  - `departments` table gains `default_nav_item_key TEXT` column (added via migration).
  - `GET /api/departments` now returns `default_nav_item_key`.
  - `POST /api/departments` and `PUT /api/departments/{id}` accept `default_nav_item_key`.
  - `GET /api/auth/me/navigation` response now includes `"default_tab"` — the nav item key the frontend should navigate to on login.
  - Admin Tools → Departments tab: each row gains a **Default Landing Tab** dropdown. The add-department form also includes the dropdown.
- **`db/migrate_v1_82_18.sql`** — idempotent migration that:
  - Creates `system_settings` table and seeds `rvtools_retention_days = 30`.
  - Adds `departments.default_nav_item_key` column.
  - Re-inserts all nav groups and nav items with `ON CONFLICT DO NOTHING`  so existing K8s clusters that were deployed before a nav item was added automatically pick up the missing items.
  - Back-fills `department_nav_groups` and `department_nav_items` for any newly inserted items.

### config
- `values.yaml`: added `reports.persistence` block (`enabled: true`, `storageClass: standard`, `size: 10Gi`) and `workers.schedulerWorker.rvtoolsRetentionDays: "30"`. Change `storageClass` to `nfs-client` if an NFS dynamic provisioner is installed on the cluster.

---

## [1.82.17] - 2026-03-25

### Fixed
- **`api/auth.py`** — `LDAPAuthenticator.ensure_ldap_structure()`: new idempotent startup method that creates `ou=users` and `ou=groups` OUs and the default admin app-user in LDAP if they are absent. In a fresh K8s deployment the LDAP StatefulSet starts with an empty directory and no OUs, so every `create_user()` call was silently failing with `NO_SUCH_OBJECT` and the user list was always empty.
- **`api/auth.py`** — `initialize_default_admin()` now calls `ensure_ldap_structure()` at startup so the LDAP directory is bootstrapped automatically without any manual `ldapadd` intervention.
- **`api/auth.py`** — `get_all_users()` now injects `DEFAULT_ADMIN_USER` into the returned list if the user is not present in LDAP (the bypass-admin can always log in via env-var but had no LDAP entry, making them invisible in the Users tab).

### Added
- **`api/main.py`** — `GET /admin/system-config` endpoint: returns a read-only health snapshot of LDAP (live bind + user count), PF9 regions (auth URL + username, no passwords), SMTP (enabled/host/port/flags), last 3 inventory runs and live table row counts. Requires admin or superadmin role.
- **`pf9-ui`** — Admin Tools → **System Config** tab (`⚙️`, superadmin-only): shows LDAP health card, PF9 Region card, SMTP card, and Inventory card with resource counts. Displays a Setup Wizard banner when LDAP is unreachable or only the default admin exists.

---

## [1.82.16] - 2026-03-24

### Fixed
- **`db_writer.py`** — Critical: `_upsert_with_history()` called `conn.rollback()` in the history-tracking exception handler, which silently wiped the just-inserted main rows (servers, volumes, networks, hypervisors) before the caller's `conn.commit()` could save them. Replaced `conn.rollback()` with a PostgreSQL `SAVEPOINT`/`ROLLBACK TO SAVEPOINT` so only the history writes are undone, never the main upsert. This is why all inventory runs reported `success` with non-zero counts but tables always showed 0 rows.

---

## [1.82.15] - 2026-03-24

### Fixed
- **`pf9_rvtools.py`** — Critical: derived network tables (subnets, ports, routers, floating IPs, security groups) could still FK-violate and roll back the entire core inventory. Fixed by committing servers/volumes/networks first, then writing each derived table in an isolated loop with individual commit/rollback. No single derived-table failure can now affect committed core data.
- **`db_writer.py`** — `upsert_subnets` now filters orphaned subnets whose `network_id` is not present in the `networks` table (same pattern as `upsert_snapshots` in v1.82.14).

---

## [1.82.14] - 2026-03-24

### Fixed
- **`pf9_rvtools.py`** — Critical: `upsert_snapshots` FK violation was rolling back the entire core inventory transaction (servers, volumes, networks, hypervisors all lost). Fixed by committing core inventory first, then running snapshots in a separate isolated try/except transaction.
- **`db_writer.py`** — `upsert_snapshots` now filters out orphaned snapshots whose parent `volume_id` is not present in the `volumes` table (deleted in OpenStack), preventing FK constraint violations.
- **`pf9_rvtools.py`** — `STATE_FILE` path changed from a bare relative filename (`p9_rvtools_state.json`) to `$PF9_OUTPUT_DIR/p9_rvtools_state.json` so the state file is written to a writable mounted volume instead of the read-only image layer.

---

## [1.82.13] - 2026-03-24

### Fixed
- **`db/init.sql`** — Fixed `v_recent_changes` subquery: added explicit `AS` column aliases on the first UNION ALL branch (`s.id AS resource_id`, `p.name AS project_name`, etc.). PostgreSQL derives column names from the first branch only; without aliases the outer SELECT could not reference `resource_id`, `project_name`, `domain_id` by name, causing `ERROR: column does not exist`.
- **`db/migrate_fix_recent_changes_view.sql`** — Same alias fix applied to the migration file.

---

## [1.82.12] - 2026-03-24

### Fixed
- **`db/init.sql`** — Fixed `v_recent_changes` view: wrapped the UNION ALL in a subquery and added `COALESCE(modified_at, created_at, deleted_at) AS recorded_at` to the outer SELECT. Multiple queries in `main.py` (`/history/daily-summary`, `/history/change-velocity`, etc.) filter and sort directly against `v_recent_changes` using `recorded_at`, causing HTTP 500 on Change Management and Customer Onboarding pages.
- **`db/init.sql`** — Simplified `v_most_changed_resources` to reference `recorded_at` directly from the updated `v_recent_changes` (no longer needs the redundant `COALESCE` expression).
- **`db/migrate_fix_recent_changes_view.sql`** — New migration: drops `v_most_changed_resources`, recreates `v_recent_changes` with `recorded_at`, recreates `v_most_changed_resources`. Required for existing clusters.

---

## [1.82.11] - 2026-03-24

### Fixed
- **`db/init.sql`** — Fixed `v_most_changed_resources` view definition: removed reference to non-existent column `recorded_at`. The source view `v_recent_changes` exposes `created_at`, `modified_at`, and `deleted_at`; replaced `recorded_at` with `COALESCE(modified_at, created_at, deleted_at)` which correctly represents the most recent change timestamp for each resource type.
- **`db/migrate_fix_most_changed_view.sql`** — New migration that applies the corrected `v_most_changed_resources` view to existing databases. Change Management UI page was returning 500 due to this missing view.

---

## [1.82.10] - 2026-03-24

### Fixed
- **`db/migrate_cohort_fixes.sql`** — Wrapped `UPDATE migration_tenants ... WHERE target_confirmed = false` in a `DO $$ BEGIN IF EXISTS` guard. `migrate_cohort_fixes.sql` sorts alphabetically before `migrate_target_preseeding.sql` (which adds the `target_confirmed` column), causing an `ERROR: column does not exist` on fresh installs. Guard skips the UPDATE safely when the column is not yet present; `migrate_target_preseeding.sql` handles backfill when it runs next.
- **`db/migrate_multicluster.sql`** — Wrapped `ALTER TABLE vm_provisioning_batches ADD COLUMN region_id` in a `DO $$ BEGIN IF EXISTS` guard. `vm_provisioning_batches` is created lazily at runtime by `vm_provisioning_routes.py` (not by any migration file), so the bare `ALTER TABLE` always fails on fresh installs. Guard skips it safely; the API startup code handles the `region_id` column when the table first exists.
- **`db/migrate_00_migration_planner.sql`** — Restored file deleted at v1.69.0. Contains the base `CREATE TABLE` definitions for all `migration_*` tables (`migration_projects`, `migration_vms`, `migration_tenants`, `migration_clusters`, etc.). Without this file the entire Migration Planner feature was broken on any fresh install.
- **`api/migration_routes.py`** — Updated `_ensure_tables()` path reference from `migrate_migration_planner.sql` → `migrate_00_migration_planner.sql` (renamed so it sorts before all dependent files that `ALTER` its tables).
- **`nginx/nginx.prod.conf`** — Fixed upstream for `pf9_ui` from port `80` to `8080`. Production UI nginx (`Dockerfile.prod`) serves on `8080`; the wrong port caused 502 Bad Gateway on fresh Docker production installs.
- **`docker-compose.prod.yml`** — Fixed `pf9_ui` healthcheck from `http://127.0.0.1:80` → `http://127.0.0.1:8080` to match the actual UI port.

---

## [1.82.9] - 2026-03-24

### Fixed
- **`run_migration.py`** — Complete rewrite. The previous implementation split the concatenated migration SQL on `;`, shattering `DO $$ BEGIN...END $$` PL/pgSQL blocks into unparseable fragments. Tables that depend on those blocks (e.g. `migration_projects`, `migration_cohorts`) were never created, silently breaking the Migration Planner on Kubernetes. New implementation: (1) uses `psql -f` subprocess — psql handles dollar-quoting, PL/pgSQL, and any SQL construct correctly; (2) adds a `schema_migrations` tracking table so each migration file is applied exactly once across all future deploys; (3) iterates individual `db/migrate_*.sql` files instead of a single concatenated blob.
- **`api/Dockerfile`** — Added `postgresql-client` to `apt-get install` so the `psql` binary is available inside the API container (and therefore the `db-migrate` Kubernetes Job). Removed the `RUN ... xargs cat > run_migration_sql.sql` step — no longer needed.

---

## [1.82.8] - 2026-03-24

### Fixed
- **`k8s/helm/pf9-mngt/values.yaml`** — Scheduler worker had incorrect default env vars that prevented RVTools inventory from ever running. `rvtoolsIntervalMinutes` was `"0"` (daily-only mode, no interval) and `rvtoolsRunOnStart` was `"false"` — both override the `.env` file values in Kubernetes. Fixed defaults to `rvtoolsIntervalMinutes: "60"` (run every 60 minutes) and `rvtoolsRunOnStart: "true"` (run immediately on pod start). Result: scheduler worker now syncs OpenStack inventory on startup and every 60 minutes as intended.

---

## [1.82.7] - 2026-03-24

### Fixed
- **`k8s/helm/pf9-mngt/templates/ingress.yaml`** — Kubernetes ingress was only
  routing `/api`, `/auth`, and `/health` to the FastAPI backend. The React UI
  makes direct calls to dozens of other paths (`/dashboard/`, `/os-distribution`,
  `/domains`, `/tenants`, `/snapshots`, `/servers`, `/volumes`, `/monitoring/`,
  etc.) that the Docker Compose nginx proxies to the API but the ingress was
  sending to the UI nginx instead — returning `index.html` (HTML) for every API
  call, causing `SyntaxError: Unexpected token '<'` in the browser. Fixed by
  adding `nginx.ingress.kubernetes.io/use-regex: "true"` and a single regex
  path rule that matches all FastAPI path prefixes (mirroring `nginx.prod.conf`
  exactly). Added `/metrics/.*` → monitoring service routing.
- **`api/auth.py`** — `initialize_default_admin()` was a no-op if a `user_roles`
  row for the admin user already existed with role `viewer` (written by an
  earlier startup before `DEFAULT_ADMIN_PASSWORD` was injected). Changed to
  always force-update the role to `superadmin` on every startup when
  `DEFAULT_ADMIN_PASSWORD` is set, ensuring the admin always has full access.

---

## [1.82.6] - 2026-03-24

### Fixed
- **`api/main.py`** — The `DEFAULT_ADMIN_USER` emergency bypass account was
  exempt from LDAP but still hit the MFA check, which queries the `user_mfa`
  table. In a fresh Kubernetes cluster (or when the database is not yet fully
  migrated), that query throws an exception; the fail-closed handler returned
  503 "MFA service temporarily unavailable" even though the password was
  correct. Added `_is_local_admin` guard so the MFA block is skipped entirely
  for the local admin bypass account.
- **`k8s/helm/pf9-mngt/templates/api/deployment.yaml`** — Added three missing
  environment variables that were required for a functional Kubernetes
  deployment:
  - `APP_ENV=production` (hardcoded) — enables `TrustedHostMiddleware` to
    accept external hostnames.
  - `PF9_ALLOWED_ORIGINS` — derived from `ingress.host` (or overridden via
    `api.allowedOrigins`); prevents "Invalid host header" 400 errors on login.
  - `DEFAULT_ADMIN_PASSWORD` — read from the `pf9-admin-credentials` Kubernetes
    Secret; without it the local admin bypass silently skipped and all logins
    fell through to LDAP.
- **`k8s/helm/pf9-mngt/values.yaml`** — Added `api.allowedOrigins: ""`
  (override for `PF9_ALLOWED_ORIGINS`) and
  `secrets.adminCredentials: pf9-admin-credentials` (new Secret reference).
- **`k8s/helm/pf9-mngt/templates/ingress.yaml`** — TLS block and cert-manager
  annotation are now guarded by `{{- if and .Values.ingress.tls.enabled
  .Values.ingress.host }}` so the chart renders a valid Ingress even when
  `ingress.host` is left empty (IP-only access).

---

## [1.82.5] - 2026-03-24

### Fixed
- **`k8s/helm/pf9-mngt/templates/api/deployment.yaml`** — Kubernetes `httpGet`
  liveness and readiness probes send the pod IP as the `Host` header. Starlette's
  `TrustedHostMiddleware` only permits `localhost`, `127.0.0.1`, `pf9_api`, and
  `pf9_ui`, so every probe returned **400** and the pod restarted in a loop. Fixed
  by adding `httpHeaders: [{name: Host, value: localhost}]` to both probes so the
  middleware receives a trusted host name instead of the pod IP.

---

## [1.82.4] - 2026-03-23

### Fixed
- **`api/Dockerfile`** — After adding `USER 1000`, the named Docker volume
  `app_logs` (mounted at `/app/logs`) was initialised as root-owned because
  `/app/logs` did not exist in the image. `logging.FileHandler` in
  `structured_logging.py` was called at module load time and failed immediately
  with `PermissionError`, crashing every gunicorn worker before the health-check
  endpoint could respond. Fix: added `RUN mkdir -p /app/logs /app/static` before
  the `chown` step so Docker initialises the named volume from the image layer
  (owned by UID 1000) and the process can write its log file on startup.

---

## [1.82.3] - 2026-03-23

### Fixed
- **`api/Dockerfile`** — Running as UID 1000 (`runAsNonRoot: true`) but `/app` was
  owned by root, causing `PermissionError: '/app/static'` on every gunicorn worker
  startup. Added `RUN chown -R 1000:1000 /app` and `USER 1000` after all `COPY`
  statements so the runtime user can write `/app/static` (logo uploads) and other
  runtime paths.
- **`pf9-ui/Dockerfile.prod`** — nginx `listen 80` requires `CAP_NET_BIND_SERVICE`
  which is not available when the pod runs as UID 1000 (`runAsNonRoot: true`).
  Changed to `listen 8080` and `EXPOSE 8080`.
- **`k8s/helm/pf9-mngt/templates/ui/deployment.yaml`** — `containerPort` and both
  probe ports were still set to `5173` (Vite dev server); the production image uses
  nginx on `8080`. Updated all three to `8080`.
- **`k8s/helm/pf9-mngt/templates/ui/service.yaml`** — `targetPort` was `5173`;
  updated to `8080`.
- **`k8s/helm/pf9-mngt/values.yaml`** — `ui.service.port` was `5173`; updated to
  `8080`.

---

## [1.82.2] - 2026-03-23

### Fixed
- **`api/Dockerfile`** — `run_migration.py` and all `db/migrate_*.sql` files were not
  copied into the image, causing the `db-migrate` Kubernetes Job to fail immediately
  with `FileNotFoundError`. Added `COPY run_migration.py ./` and a `RUN` step that
  concatenates all `db/migrate_*.sql` files into `/app/run_migration_sql.sql` at
  build time.
- **`k8s/helm/pf9-mngt/templates/workers/ldap-sync-worker.yaml`** — injected
  `LDAP_SYNC_KEY` env var from the `pf9-ldap-secrets` secret (`sync-key` key);
  worker was exiting on startup without it.
- **`k8s/helm/pf9-mngt/templates/api/deployment.yaml`** — injected `LDAP_SYNC_KEY`
  env var (optional) for LDAP federation decrypt path in auth.py.
- **`k8s/helm/pf9-mngt/templates/ui/deployment.yaml`** — added `emptyDir` volumes
  for `/var/cache/nginx` and `/var/run`; nginx non-root UID 1000 cannot create
  these directories in the read-only container filesystem.
- **`k8s/helm/pf9-mngt/templates/workers/scheduler-worker.yaml`** — added `emptyDir`
  volume at `/app/monitoring`; `host_metrics_collector.py` writes a cache file to
  a relative `monitoring/` path that does not exist in the container filesystem.

---

## [1.82.1] - 2026-03-25

### Fixed
- **CI `update-values` job** (`release.yml`) — `actions/checkout@v4` failed with
  `Error: Input required and not supplied: token` when the `RELEASE_PAT` repository
  secret was not configured. Changed `token: ${{ secrets.RELEASE_PAT }}` to
  `token: ${{ secrets.RELEASE_PAT || github.token }}`. The job now falls back to the
  built-in `github.token` (which already has `contents: write` permission via the
  job's `permissions:` block) when no PAT is supplied, making the first-run
  experience zero-config.

---

## [1.82.0] - 2026-03-24

### Added — Kubernetes Production Support

#### Helm Chart (`k8s/helm/pf9-mngt/`)
- **`Chart.yaml`** — appVersion 1.82.0, kubeVersion `>=1.28.0-0`
- **`values.yaml`** — full default configuration for all 14 services; all sensitive values reference pre-existing Kubernetes Secrets by name (`secrets:` section) — no credentials are stored in the chart itself
- **`values.prod.yaml`** — CI-managed override file; contains only image tags; auto-updated by the new `update-values` CI job on each release
- **`templates/_helpers.tpl`** — chart-wide naming helpers (`pf9mngt.name`, `pf9mngt.fullname`, `pf9mngt.labels`, `pf9mngt.selectorLabels`, `pf9mngt.appImage`)
- **`templates/namespace.yaml`** — creates the `pf9-mngt` namespace when `namespace.create: true`
- **API** (`templates/api/`) — Deployment + ClusterIP Service; all env vars wired from `values.yaml` and `secretKeyRef` references; liveness + readiness probes on `/health`; `PRODUCTION_MODE: "true"` always set (JWT startup guard active)
- **UI** (`templates/ui/`) — Deployment + ClusterIP Service; liveness + readiness probes on `/`
- **PostgreSQL** (`templates/db/`) — StatefulSet (stable identity + persistent storage) + headless Service; `volumeClaimTemplate` with configurable `storageClass` and size
- **Redis** (`templates/redis/`) — Deployment + ClusterIP Service; `maxmemory` and `allkeys-lru` policy configured via chart values
- **OpenLDAP** (`templates/ldap/`) — StatefulSet + headless Service; two `volumeClaimTemplates` (data + config); LDAP never exposed outside cluster (ClusterIP headless only)
- **Monitoring** (`templates/monitoring/`) — Deployment + ClusterIP Service; Docker socket dependency removed (not applicable in Kubernetes)
- **Workers** (`templates/workers/`) — seven single-replica Deployments: `backup-worker` (with optional PVC for backup storage), `ldap-sync-worker`, `metering-worker`, `notification-worker`, `scheduler-worker`, `search-worker`, `snapshot-worker`; all workers inherit `/tmp/alive` liveness probe pattern from v1.81.0
- **Ingress** (`templates/ingress.yaml`) — nginx-ingress + cert-manager; routes `/api` + `/auth` + `/health` to the API service and `/` to the UI; TLS via Let's Encrypt (`cert-manager.io/cluster-issuer` annotation); fully configurable host, TLS secret name, and body-size limit
- **DB migrate job** (`templates/jobs/db-migrate.yaml`) — Helm `pre-install` / `pre-upgrade` hook that runs `run_migration.py` in an API container before any Deployment rollout; `hook-delete-policy: hook-succeeded` keeps the cluster clean; `activeDeadlineSeconds: 300` prevents indefinite hangs

#### ArgoCD GitOps (`k8s/argocd/`)
- **`application.yaml`** — ArgoCD `Application` manifest; sources `k8s/helm/pf9-mngt/` from `master`, applies `values.yaml` + `values.prod.yaml`; `automated.prune: true` + `automated.selfHeal: true`; `CreateNamespace=true` + `ServerSideApply=true` sync options; 5-retry backoff

#### Sealed Secrets (`k8s/sealed-secrets/`)
- **`README.md`** — complete operator guide for Bitnami Sealed Secrets; copy-paste `kubeseal` commands for all nine Kubernetes Secrets the chart references (`pf9-db-credentials`, `pf9-jwt-secret`, `pf9-ldap-secrets`, `pf9-smtp-secrets`, `pf9-pf9-credentials`, `pf9-snapshot-creds`, `pf9-provision-creds`, `pf9-ssh-credentials`, `pf9-copilot-secrets`); rotation instructions

#### CI/CD (`release.yml`)
- **`helm-package` job** — runs after `publish-images`; installs Helm 3.14, logs into GHCR OCI registry, packages the chart with the release version, pushes to `oci://ghcr.io/<owner>/helm`
- **`update-values` job** — runs after `helm-package`; patches `global.imageTag` in `values.prod.yaml` using `sed`, commits the change as `ci: update image tags to vX.Y.Z [skip ci]` and pushes to `master` (requires `RELEASE_PAT` repository secret); ArgoCD detects the commit and auto-syncs the cluster
- **`release` job** now depends on `helm-package` and `update-values` (in addition to the existing `publish-images`) so a GitHub Release is only created once the full pipeline — Docker images + Helm chart + values update — succeeds

### Security
- All pod specs set `securityContext.runAsNonRoot: true` and `runAsUser: 1000`
- LDAP service exposed as headless `ClusterIP` only — never reachable from outside the cluster
- All secret references use `secretKeyRef` with `optional: true` where the secret may not be configured (snapshot creds, provision creds, SSH, copilot API keys, SMTP); required secrets (DB password, JWT key, LDAP admin password) have no `optional` flag so missing secrets fail fast at pod startup

## [1.81.0] - 2026-03-23

### Security — Hardening & Pre-Kubernetes Fixes

#### API
- **Production JWT guard** (`api/auth.py`) — when `PRODUCTION_MODE=true` is set and no `jwt_secret` Docker secret or `JWT_SECRET_KEY` environment variable is configured, the API now exits at startup with a clear `RuntimeError` instead of silently generating an ephemeral key that would invalidate all sessions on every pod restart
- **SSRF re-validation in external LDAP auth passthrough** (`api/auth.py`) — `_bind_external_ldap()` now re-validates the LDAP host against RFC-1918, loopback, and ULA address ranges at connection time (defence-in-depth; the host is already checked at config-save time, but this prevents exploitation via direct database modification)
- **Backup config explicit column allowlist** (`api/backup_routes.py`) — the `PUT /api/backup/config` endpoint now validates that every Pydantic-derived column name appears in an explicit `_ALLOWED_COLUMNS` set before constructing the `UPDATE` statement, preventing any hypothetical future code path from reaching SQL with unexpected column names

#### Workers — Credential Hardening
- **Eliminated hardcoded default database passwords** in `backup_worker`, `metering_worker`, and `search_worker`: all three now use a `_read_secret()` helper (same pattern already in `ldap_sync_worker`) that reads from Docker secret file `/run/secrets/db_password` first, then falls back to the `DB_PASS` environment variable and finally `POSTGRES_PASSWORD` — the `"pf9pass"` fallback has been removed

#### Workers — Kubernetes Liveness Probes
- **Heartbeat file** (`/tmp/alive`) added to all long-lived workers: `backup_worker`, `metering_worker`, `search_worker`, `scheduler_worker`, `notification_worker` — each worker touches this file on every main-loop iteration so that a stalled worker (live process but stuck in a blocking call) is detected
- **Healthchecks** added to `docker-compose.yml` for all five workers — each checks that `/tmp/alive` was updated within a worker-appropriate window:
  - `backup_worker` — 180 s window (3× the 30 s job-poll interval)
  - `metering_worker` — 300 s window
  - `scheduler_worker` — 300 s window
  - `notification_worker` — 600 s window
  - `search_worker` — 900 s window (3× the 300 s index interval)

### Added
- **`_plans/KUBERNETES_PLAN.md`** — full technical roadmap for adding Kubernetes production support: monorepo strategy, Helm chart directory structure, ArgoCD GitOps flow, Sealed Secrets approach, CI/CD pipeline additions, HPA plan, MSP value-add table, and a per-phase checklist

## [1.80.0] - 2026-03-25

### Added — External LDAP Sync UI

#### New component: `LdapSyncSettings` (`pf9-ui`)
- Full management UI for external LDAP / Active Directory sync configurations, accessible from **Admin → User Management → External LDAP Sync** (superadmin-only tab)
- **Config list table** — shows all configs with host:port, TLS mode, enabled state, last sync status badge (success / partial / failed / never run), last sync time, user count, and sync interval
- **Create / Edit modal** — covers all backend fields: connection (host, port, TLS / STARTTLS / plain, CA cert PEM), service account (bind DN, bind password — write-only on edit), user search (base DN, filter, UID/email/fullname attributes), group→role mapping rows, schedule (interval dropdown), MFA delegation toggle, and private-network warning banner
- **Group → Role Mapping editor** — dynamic add/remove rows mapping external group DNs to platform roles (viewer / operator / technical / admin); `superadmin` is not offered (matching server-side constraint)
- **🔌 Test Connection panel** — fires `POST /admin/ldap-sync/configs/{id}/test` and displays connect / bind success badges, user count, and a sample user table
- **👁️ Preview Sync panel** — fires `POST /admin/ldap-sync/configs/{id}/preview` and displays create / update / deactivate counts plus a per-user action table
- **▶️ Sync Now button** — fires `POST /admin/ldap-sync/configs/{id}/sync` with loading state
- **📋 Sync Logs panel** — fetches last 20 sync runs via `GET /admin/ldap-sync/configs/{id}/logs`; each row shows started time, duration, status, counts, error; click any row to expand full error message
- **🗑️ Delete confirmation modal** — warns that synced users will be deactivated and sessions revoked before confirming
- Bind password is never pre-filled on edit (write-only by design); blank submission preserves existing encrypted value
- `allow_private_network` flag shows a visible ⚠️ security warning banner when enabled

#### New documentation
- `docs/LDAP_SYNC_GUIDE.md` — comprehensive operator guide covering requirements, step-by-step config, group mapping, TLS setup, testing, manual sync, logs, MFA delegation, private network flag, authentication flow, deactivation behaviour, security architecture, and troubleshooting

## [1.79.0] - 2026-03-24

### Added — External LDAP / AD Identity Federation

#### New service: `ldap_sync_worker`
- Background worker that periodically syncs users from one or more external LDAP / Active Directory servers into the pf9-mngt identity store and role mappings
- Configurable per-source poll interval (default 30 s), with `pg_try_advisory_lock` preventing concurrent sync runs for the same config
- After 3 consecutive sync failures a notification row is written to alert operators
- Graceful SIGTERM / SIGINT shutdown between poll cycles

#### New API: `POST/GET/PUT/DELETE /admin/ldap-sync/configs` and related endpoints
- Full CRUD management of external LDAP / AD connection configs: host, port, TLS, StartTLS, CA cert, bind credentials (Fernet-encrypted at rest), base DN, user attribute, sync interval, group-to-role mappings
- **`POST /admin/ldap-sync/configs/{id}/test`** — live connectivity and service-account bind test with per-step diagnostics
- **`POST /admin/ldap-sync/configs/{id}/preview`** — dry-run that returns the first 50 matching users and their derived roles without writing to the DB
- **`POST /admin/ldap-sync/configs/{id}/sync`** — manual sync trigger (resets `last_sync_at` so the worker picks it up immediately)
- **`GET /admin/ldap-sync/configs/{id}/logs`** — paginated sync log history with outcome, counts, and duration
- All endpoints superadmin-only; `/test` and `/preview` rate-limited to 10 requests/minute per user

#### Credential passthrough for externally-synced users
- `auth.py` — `authenticate()` now checks whether the authenticating user was synced from an external LDAP source; if so, their password is verified directly against their origin LDAP server (no local password stored), via a new `_bind_external_ldap()` helper
- Complete LDAP connection lifecycle: TLS / StartTLS / plaintext, configurable CA cert, service-account search-bind to resolve the user DN, end-user simple bind for password verification
- On successful passthrough bind the existing JWT / session flow continues unchanged

#### Group-to-role mapping
- External LDAP group membership is mapped to pf9-mngt roles (`viewer`, `operator`, `admin`, `technical`) via the `ldap_sync_group_mappings` table; `superadmin` cannot be assigned via sync (DB-level CHECK constraint)
- Multiple groups can map to the same role; the highest role wins when a user belongs to multiple mapped groups
- Users removed from all mapped groups during a sync cycle are deactivated and their active sessions are revoked

#### SSRF protection
- `ldap_sync_routes.py` validates that the configured LDAP host does not resolve to RFC-1918, loopback, link-local, or ULA address ranges before opening any connection
- Same blocklist as the existing cluster registry SSRF guard

#### Shared Fernet encryption helper
- **`api/crypto_helper.py`** — new module providing `fernet_encrypt()` / `fernet_decrypt()` with `fernet:<ciphertext>` storage convention; `cluster_registry.py` `_fernet_decrypt` refactored to delegate here (no behaviour change)
- LDAP bind passwords are encrypted with a dedicated `ldap_sync_key` Docker secret (separate from `jwt_secret`)

#### Database schema
- **`db/migrate_ldap_sync.sql`** — new idempotent migration; adds `ldap_sync_config`, `ldap_sync_group_mappings`, `ldap_sync_log` tables; adds `sync_source`, `sync_config_id`, `locally_overridden` columns to `user_roles`; adds partial index on synced-user rows; inserts `('superadmin', 'ldap-sync', 'admin')` RBAC row

#### Infrastructure
- **`ldap_sync_worker/`** — new Docker service (`python:3.11-slim`, `python-ldap`, `psycopg2-binary`, `cryptography`)
- **`docker-compose.yml`** — `ldap_sync_worker` service added with `db_password`, `ldap_admin_password`, `ldap_sync_key` secrets; `ldap_sync_key` secret file referenced
- **`docker-compose.prod.yml`** — `ldap_sync_worker` image reference added
- **`deployment.ps1`** — `ldap_sync_key` generation step added (32-byte cryptographic random, written to `secrets/ldap_sync_key`)
- **`startup_prod.ps1`** — `secrets/ldap_sync_key` added to preflight secret-files check

---

## [1.78.0] - 2026-03-23

### Security — Authentication & Middleware Hardening

#### `api/auth.py` — LDAP injection prevention
- **DN injection closed** — `authenticate()`, `create_user()`, `delete_user()`, and `change_password()` now call `ldap.dn.escape_dn_chars(username)` before interpolating the username into any DN string (e.g. `cn={username},{user_dn}`). Prevents crafted usernames such as `admin,dc=evil,dc=com` from rewriting the bind target.
- **LDAP network timeout** — all 7 `ldap.initialize()` call sites now call `conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)` immediately after setting `OPT_REFERRALS`. Under an LDAP outage, auth operations now fail fast (≤ 5 s) instead of stalling gunicorn worker threads for minutes.

#### `api/auth.py` — timezone-aware datetimes
- `create_access_token()` — `exp` and `iat` JWT claims now use `datetime.now(timezone.utc)` instead of the deprecated `datetime.utcnow()`. Removes `DeprecationWarning` on Python 3.12+ and ensures claims are always timezone-aware.
- `create_user_session()` — `expires_at` written to the `user_sessions.expires_at TIMESTAMPTZ` column is now timezone-aware, consistent with the PostgreSQL column type.

#### `api/main.py` — `verify_admin_credentials` security fixes
- **Unconfigured-password guard removed** — when `PF9_ADMIN_PASSWORD` is not set, the function previously logged a warning and returned `False`, silently granting access to every admin endpoint. It now raises `HTTP 503 Service Unavailable` (`"Admin authentication not configured"`), requiring the operator to explicitly provision the credential before admin routes are accessible.
- **Timing-safe comparison** — `credentials.username != ADMIN_USERNAME or credentials.password != ADMIN_PASSWORD` replaced with two `hmac.compare_digest()` calls. Prevents timing-based credential enumeration attacks from a remote attacker measuring response latency.
- `hmac` added to top-level imports in `main.py`.

#### `api/main.py` — middleware token-verification deduplication
- `rbac_middleware` stores the validated `TokenData` object in `request.state.token_data` after a successful `verify_token()` call.
- `access_log_middleware` now reads `request.state.token_data` via `getattr(request.state, "token_data", None)` instead of calling `verify_token()` a second time. Eliminates one round-trip DB query (`user_sessions` lookup) per authenticated HTTP request.

#### `api/main.py` — timezone-aware datetimes in `/auth/login`
- `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` in both the MFA-pending token response and the normal login response's `expires_at` field. Consistent with the fixes to `auth.py` above.

#### `api/smtp_helper.py` — Docker-secrets-aware SMTP password
- `SMTP_PASSWORD` was the only credential in the project still read exclusively via `os.getenv("SMTP_PASSWORD", "")`. It now uses `read_secret("smtp_password", env_var="SMTP_PASSWORD", default="")` — checks `/run/secrets/smtp_password` first, falls back to the env var. Consistent with how every other credential is resolved and enables zero-secret-in-env-var deployment.

---

## [1.77.0] - 2026-03-22

### Added — Migration Planner Region Normalization

#### `migration_projects` — source and target region FKs
- **`migration_projects.source_region_id`** *(new column, nullable)* — FK to `pf9_regions.id`; records the PCD source region for cross-region migration projects. NULL for VMware-to-PCD migrations (the common case).
- **`migration_projects.target_region_id`** *(new column, nullable)* — FK to `pf9_regions.id`; when set, `pcd-gap-analysis` uses the ClusterRegistry client for that region (registered credentials + capabilities JSONB) instead of temporarily patching the global `p9_common.CFG`. Falls back to ad-hoc `pcd_auth_url`/`pcd_username` credentials when `target_region_id` is NULL (full backward compatibility with all existing projects).
- **`PATCH /api/migration/projects/{id}/pcd-settings`** — now accepts `source_region_id` and `target_region_id` fields to link a project to a registered region.

#### `pcd-gap-analysis` enhancement
- When `project.target_region_id` is set, `POST /api/migration/projects/{id}/pcd-gap-analysis` now retrieves flavors, networks, and images via `get_registry().get_region(target_region_id)` — no global `p9_common.CFG` mutation, no config restore block required.
- If the registered region client is unavailable, the endpoint falls back to the ad-hoc credential path and logs a warning — no silent failure.

#### Cluster task visibility
- **`GET /admin/control-planes/cluster-tasks`** *(new)* — superadmin-only endpoint that returns pending/in-progress `cluster_tasks` rows with `"processor_status": "NOT_IMPLEMENTED"`. The cross-region replication processor (image_copy, volume_transfer, backup_restore) is deferred until a second region is available for end-to-end testing. This endpoint surfaces queued tasks rather than silently ignoring them.

#### Database migration
- **`db/migrate_phase8_migration_norm.sql`** *(new)* — adds `source_region_id` and `target_region_id` FK columns to `migration_projects`; creates selective indexes on both columns; adds `idx_cluster_tasks_pending` partial index on `cluster_tasks`.
- **`api/main.py`** — Phase 8 startup migration guard added: checks `migration_projects.target_region_id` column existence in `information_schema.columns` before applying `migrate_phase8_migration_norm.sql`.

---

## [1.76.0] - 2026-03-22

### Added — Multi-Region Management UI

#### Region selector and cluster management panel
- **`ClusterContext.tsx`** *(new)* — React context providing `selectedRegionId`, `regionParam()`, `controlPlanes`, `regions`, and `reload` to all child components. Data is loaded from `/admin/control-planes` and per-CP `/regions` on mount; only runs for `superadmin` users; fails silently for others.
- **`RegionSelector.tsx`** *(new)* — Compact dropdown in the top navigation bar. Rendered only when `regions.length ≥ 2` and the user is a superadmin. Options are grouped by control plane with health-state colour indicators (green/yellow/red/grey). Selecting a region sets the global `selectedRegionId` context value; "All Regions" resets it to `null`.
- **`ClusterManagement.tsx`** *(new)* — Superadmin-only admin panel accessible via the **Cluster Mgmt** tab. Features: list / add / delete / test control planes; test-connection result shows discovered regions with one-click **Register**; regions table with enable/disable toggle, set-default, trigger-sync, and view-sync-log actions.
- **`App.tsx`** — Imports and wires all three new components: `ClusterContextProvider` wraps the full authenticated shell; `RegionSelector` is placed before the theme toggle in the header; `cluster_management` added to `ActiveTab` type and `DEFAULT_TAB_ORDER`.

#### Per-region filtering in all major views
- **`MeteringTab.tsx`** — `buildQuery()` and `loadOverview()` callbacks now append `region_id` to query params when a region is selected; `selectedRegionId` added to both `useCallback` dependency arrays.
- **`ResourceManagementTab.tsx`** — `loadData()` appends `region_id` to resource-list query params; `selectedRegionId` added to dependency array.
- **`ReportsTab.tsx`** — `runReport()` appends `region_id` to the report fetch URL; `selectedRegionId` added to dependency array.
- **`LandingDashboard.tsx`** — `fetchDashboardData()` appends `?region_id=` to the `/dashboard/health-summary` URL; `selectedRegionId` added to the `useEffect` dependency array so the dashboard auto-refreshes on region change.

#### Database migration
- **`db/migrate_phase7_nav.sql`** *(new)* — Adds a `cluster_management` row to `nav_items` inside the `admin_tools` group (`ON CONFLICT DO NOTHING`).
- **`db/init.sql`** — `cluster_management` nav item added to the Admin Tools INSERT block for fresh installs.
- **`api/main.py`** — Startup migration guard added: checks `nav_items.key = 'cluster_management'` existence before applying `migrate_phase7_nav.sql`.

---

## [1.75.0] - 2026-03-22

### Added — Multi-Region API Filtering with RBAC Enforcement

#### Optional `?region_id=` query parameter on all API modules
- All major API modules now accept an optional `region_id` query parameter to scope responses to a specific PF9 region.
- **`api/auth.py`** — `get_user_accessible_regions(username)` and `get_effective_region_filter(username, region_id)` helper functions added. Region-scoped users are automatically constrained to their assigned region; requests to an unassigned region raise `HTTP 403`. Global users may query any region.
- **`api/metering_routes.py`** — 5 endpoints updated: `/resources`, `/snapshots`, `/restores`, `/efficiency`, `/overview`.
- **`api/dashboards.py`** — `/health-summary` updated with per-region DB count filters.
- **`api/reports.py`** — 14 report endpoints updated. Live-API reports route to the correct region registry client; DB-only reports apply `WHERE region_id = %s`. Helper `_report_client_and_region()` added.
- **`api/resource_management.py`** — 12 GET endpoints updated: users, flavors, networks, routers, floating-ips, volumes, security-groups, images, quotas, context/domains, context/projects, context/external-networks. Helper `_res_client()` added.
- **`api/provisioning_routes.py`** — `ProvisionRequest` model gains `region_id` field; INSERT writes it to `provisioning_jobs`; `GET /logs` filters by region.
- **`api/vm_provisioning_routes.py`** — `CreateBatchRequest` model gains `region_id`; INSERT writes it to `vm_provisioning_batches`; `GET /batches`, `/domains`, `/resources`, `/quota`, `/available-ips` all region-aware.
- **`api/search.py`** — Main search endpoint passes `region_id` as the 9th argument to the `search_ranked` PostgreSQL function; COUNT query also filtered.
- **`api/main.py`** — Startup migration guard added: checks `search_documents.region_id` existence before applying `migrate_phase6_api.sql`.

#### Database migration
- **`db/migrate_phase6_api.sql`** *(new)* — Adds `region_id TEXT REFERENCES pf9_regions(id)` to `search_documents`; creates `idx_search_documents_region_id` index; updates `search_ranked` PostgreSQL function with backward-compatible 9th parameter `filter_region` (defaults to `NULL` = no filter).

---

## [1.74.6] - 2026-03-22

### Fixed — Metering Worker Crash on First Post-Upgrade Cycle

#### `api/main.py` — Phase 5B startup guard
- The Phase 5B migration guard checked only `metering_resources.region_id` to decide whether to skip `migrate_metering_region.sql`. Because a CI pipeline had previously applied only the first two `ALTER TABLE` statements (`metering_resources`, `metering_efficiency`), the guard fired a false-positive "already present" on production restart and skipped the rest of the migration — leaving `metering_snapshots`, `metering_restores`, `metering_quotas`, and `backup_history` without `region_id`.
- Fixed: guard now counts how many of the six target tables have `region_id`. The migration is only skipped when **all six** columns are present (`COUNT(*) = 6`). Any partial state triggers a re-run, and `ADD COLUMN IF NOT EXISTS` makes every statement genuinely idempotent.

#### `db/init.sql` + `db/migrate_multicluster.sql` — `security_groups.region_id` omission
- `security_groups` was added to the schema after the multi-region `region_id` sweep and was never included in either the `init.sql` `ALTER TABLE` block or `migrate_multicluster.sql`. The `collect_quota_usage` function in `metering_worker` issued a `LATERAL` subquery referencing `security_groups.region_id`, which crashed with `column "region_id" does not exist`.
- Fixed: `ALTER TABLE security_groups ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id)` and `CREATE INDEX IF NOT EXISTS idx_security_groups_region` added to both SQL files. Applied directly to the running DB.

---

## [1.74.5] - 2026-03-22

### Added — Multi-Region Worker Support

#### `metering_worker/main.py`
- Added `_decrypt_password()` and `load_enabled_regions()` helpers (same pattern as `scheduler_worker`).
- All collector functions now accept a `region_id` parameter: `collect_resource_metrics`, `collect_snapshot_metrics`, `collect_restore_metrics`, `collect_quota_usage`, `collect_efficiency_scores`.
- `collect_resource_metrics` passes `region_id` as a query param to the monitoring service API.
- `collect_snapshot_metrics` and `collect_quota_usage` filter inventory tables by `region_id` so cross-region data is never mixed.
- `collect_efficiency_scores` reads `metering_resources WHERE region_id = %s` so efficiency scores are region-scoped.
- All INSERT statements now write `region_id` into the metering tables.
- `run_collection_cycle()` iterates over all enabled regions, calling each collector per region and writing a `cluster_sync_metrics` row per region. Falls back to single default-region mode when no regions are in the DB.
- `collect_api_usage` remains global (one call per cycle, not per region).

#### `host_metrics_collector.py`
- `HostMetricsCollector.__init__` now accepts an optional `region_id: str = ""` argument. When provided, the constructor uses it directly instead of reading `PF9_REGION_ID` from the environment. Backward-compatible: existing callers that pass no argument continue to work via `os.getenv("PF9_REGION_ID", "")` fallback.

#### `scheduler_worker/main.py` — `metrics_loop()`
- Replaced single global `HostMetricsCollector` with a per-region collector map loaded from `load_enabled_regions()`.
- Each region gets its own `metrics_cache_{region_id}.json` and `cpu_state_{region_id}.json` so CPU delta calculations are independent.
- Falls back to single-collector env-var mode when no region rows exist.
- After every successful (or failed) `run_once()`, writes a `cluster_sync_metrics` row with `sync_type='host_metrics'`.

#### `snapshots/p9_snapshot_policy_assign.py`
- Updated `--region-id` help text to document that it scopes the run to region-specific OpenStack credentials (already overlaid in the environment by `snapshot_scheduler.py`).
- `region_label` is now threaded through all four progress `print` statements and the final summary, so multi-region log output is clearly attributed to a specific region.

#### `backup_worker/main.py`
- `_create_scheduled_job()` now accepts an optional `region_id: str = None` and writes it to the new `backup_history.region_id` column. Infrastructure-level (scheduled) backups store `NULL`; region-triggered manual jobs can carry the originating region ID for audit trail purposes.

#### `db/migrate_metering_region.sql` *(new)*
- Adds `region_id TEXT` column (nullable) to `metering_resources`, `metering_snapshots`, `metering_restores`, `metering_quotas`, `metering_efficiency`, and `backup_history`.
- Creates region-scoped descending indexes on each metering table for query performance.
- Applied automatically at API startup via `api/main.py` (idempotent — skipped only when all six target columns are confirmed present; see v1.74.6 for the guard hardening).

---

## [1.74.4] - 2026-03-22

### Fixed — Search Worker VM Indexing & Reports OS Info

#### `search_worker/main.py` + `api/reports.py`
- `LEFT JOIN images i ON s.image_id = i.image_id` referenced a non-existent column — the `images` table primary key is `id`, not `image_id`. The search worker logged `column i.image_id does not exist` on every 5-minute indexing cycle, causing VM records to never be indexed; the reports endpoint silently returned empty OS info for all VMs.
- Fixed: changed join condition to `s.image_id = i.id` in both files.

---

## [1.74.3] - 2026-03-22

### Fixed — Blank-UI-on-Restart: DDL Lock Storm

#### `api/main.py` — `startup_event()`
- `ALTER TABLE … ADD COLUMN IF NOT EXISTS` acquires `ACCESS EXCLUSIVE` on the target table even when the column already exists. With 4 gunicorn workers restarting simultaneously, all four ran the multi-cluster and phase-5 DDL blocks concurrently; the first winner held the lock while all API reads on `servers`, `hypervisors`, `volumes`, etc. queued behind it — causing every UI page to show blank/loading until the lock cleared (often 30–60 s, sometimes indefinitely if an idle-in-transaction connection held a conflicting lock first)
- Fixed: both migration blocks now check first whether the schema is already present (`information_schema.tables` for `pf9_regions`, `information_schema.columns` for `snapshot_runs.region_id`) and skip the entire DDL block if it is — no `ALTER TABLE` issued on a healthy restart, zero ACCESS EXCLUSIVE locks, pages load instantly
- Seed call (`_seed_default_cluster`) is exempt from the guard and always runs — it uses `ON CONFLICT DO NOTHING` and acquires no table-level locks

### Fixed — Snapshot Worker Crash Loop (exit code 0)

#### `snapshots/snapshot_scheduler.py`
- **Missing module entry point** — `main()` was called unconditionally at module level *inside* the function body's indented block (an indentation error introduced during the multi-region refactor), causing the script to call itself recursively on import and exit immediately with code 0. The `pf9_snapshot_worker` container was `Restarting (0)` with empty logs and no output — exit code 0 masked the crash.
  Fixed: added `if __name__ == "__main__": main()` guard at module level and removed the misplaced call.
- **`next_compliance_report` never advanced** — missing `next_compliance_report = now + COMPLIANCE_REPORT_INTERVAL_MINUTES * 60` after the compliance report block meant the report ran on *every* loop iteration instead of once per day.
- **Missing `time.sleep(10)`** — scheduler loop spun continuously at 100% CPU; added 10-second sleep at end of each iteration.

### Fixed — PostgreSQL Idle-in-Transaction Sessions Blocking Restarts

#### `docker-compose.yml`
- Added `idle_in_transaction_session_timeout=30000` (30 s) and `statement_timeout=120000` (2 min) to the PostgreSQL `command:` block. A connection left idle-in-transaction (e.g. from a previous crashed worker) holds row/table locks that block incoming DDL — previously this required manual `pg_terminate_backend()` to unblock. These timeouts ensure stale transactions are automatically terminated within 30 s, making restarts self-healing.
- Setting applied live to the running instance via `ALTER SYSTEM SET … + pg_reload_conf()` (no DB restart required).

---

## [1.74.2] - 2026-03-22

### Added — Multi-Region Worker Support

#### Thread-safe endpoint management (`p9_common.py`)
- Endpoint variables (`NOVA_ENDPOINT`, `NEUTRON_ENDPOINT`, `CINDER_ENDPOINT`, `GLANCE_ENDPOINT`) now stored in **per-thread local storage** (`threading.local`) in addition to module-level globals — enables safe parallel region processing without cross-region data corruption
- Four new accessor functions: `_ep_nova()`, `_ep_neutron()`, `_ep_cinder()`, `_ep_glance()` — internal callers prefer these; module-level globals still updated for backward compatibility with late-binding imports

#### Scheduler worker multi-region loop (`scheduler_worker/main.py`)
- `load_enabled_regions()` — queries `pf9_regions JOIN pf9_control_planes` for all enabled regions
- `_run_rvtools_sync(region)` — accepts optional region dict; overlays per-region credentials as subprocess env vars
- `_run_rvtools_for_all_regions()` — concurrent region processing bounded by `asyncio.Semaphore(MAX_PARALLEL_REGIONS)`
- `_decrypt_password()` — handles `env:`, `fernet:`, and plaintext password prefixes
- New env vars: `MAX_PARALLEL_REGIONS` (default `3`), `REGION_REQUEST_TIMEOUT_SEC` (default `30`)

#### Metering worker sync tracking (`metering_worker/main.py`)
- `record_metering_sync()` — writes per-cycle metrics (resource count, error count, duration) to `cluster_sync_metrics` table after each collection cycle
- `load_default_region_id()` — resolves default region for tagging metering records

#### Snapshot worker multi-region delegation (`snapshots/snapshot_scheduler.py`)
- All four run functions (`run_policy_assign`, `run_rvtools`, `run_auto_snapshots`, `run_compliance_report`) now accept a `region` dict and pass per-region credentials + `--region-id` to sub-scripts via subprocess `env=` override
- `load_enabled_regions()`, `_region_env(region)` helpers added

#### Snapshot scripts region tagging (`snapshots/p9_auto_snapshots.py`, `p9_snapshot_policy_assign.py`)
- `--region-id` CLI argument added to both scripts
- `snapshot_runs.region_id` and `snapshot_records.region_id` populated when `--region-id` is provided
- `start_snapshot_run()` and `create_snapshot_record()` accept optional `region_id` parameter

#### Host metrics region-aware host discovery (`host_metrics_collector.py`)
- `_load_hosts_from_db(region_id)` static method — queries `hypervisors WHERE region_id = %s AND status = 'enabled'` for management IPs
- Constructor checks `PF9_REGION_ID` env var; uses DB host list when set, falls back to `PF9_HOSTS`

#### Database schema (`db/migrate_phase5_workers.sql`)
- `snapshot_runs.region_id TEXT REFERENCES pf9_regions(id)` — tags each snapshot run with its source region
- `idx_snapshot_runs_region_id` index added

### Fixed — SQL Migration Parser Regression

#### `db/migrate_multicluster.sql`
- Four `--` comment lines contained semicolons (`;`) which caused Python's `split(";")` migration parser to fragment the `CREATE TABLE pf9_regions` statement, silently skipping the entire multi-cluster schema migration on every API restart — API was logging `Multi-cluster schema migration skipped: syntax error at end of input`
- Fixed by replacing inline semicolons in comment lines with equivalent phrasing using parentheses/em-dashes; API now logs `Multi-cluster schema migration applied` on startup

### Fixed — Startup DDL Deadlock (Advisory Lock)

#### `api/main.py` — `startup_event()`
- With 4 gunicorn workers restarting simultaneously, all workers attempted DDL migrations concurrently, causing `relation`-level PostgreSQL lock contention and indefinite `pg_stat_activity` lock waits
- Fixed: `pg_try_advisory_lock(19740322)` acquired before migrations — only the first worker that wins the lock runs all migrations; the rest skip immediately (all migrations are idempotent, so this is safe)

### Fixed — Performance Index Migration Column Names

#### `db/migrate_indexes.sql`
- Wrong column/table names caused `column "user_id" does not exist` warning on every API restart: `activity_log.user_id` → `actor`, `activity_log.created_at` → `timestamp`, table `tickets` → `support_tickets`, `tickets.department_id` → `to_dept_id`, `tickets.due_date` → `sla_resolve_at`, `runbook_executions.runbook_id` → `runbook_name`

---

## [1.74.1] - 2026-03-21

### Fixed — SAST Security Findings & CI Gate Correction

#### CI / `.github/workflows/ci.yml`
- **Bandit HIGH-only gate flags corrected** — changed `-ll -ii` (Medium+ severity) to `-lll -iii` (HIGH severity + HIGH confidence only); the incorrect flags were causing 259 Medium-severity findings to block every push on both `dev` and `master`

#### `api/auth.py`
- `hashlib.sha1` calls for LDAP `{SSHA}` password hashing annotated with `usedforsecurity=False` and `# nosec B324` — SSHA is the LDAP wire format required by RFC 2307; it is not used as a cryptographic security primitive (B324 HIGH/HIGH)

#### `api/cache.py`
- `hashlib.md5` calls for Redis cache-key sharding annotated with `usedforsecurity=False` and `# nosec B324` — MD5 is used only for generating short deterministic cache keys, not for any authentication or integrity purpose (B324 HIGH/HIGH)

#### `host_metrics_collector.py`
- `requests.get(verify=False)` for internal PF9 host-metrics endpoint annotated with `# nosec B501` — on-premises Platform9 DU hosts use self-signed TLS certificates by design; the connection is internal and not user-controlled (B501 HIGH/HIGH)

#### `seed_demo_data.py`
- `hashlib.md5` call in `change_hash()` annotated with `usedforsecurity=False` and `# nosec B324` — MD5 is used only for change-detection fingerprinting on demo seed data, not for security (B324 HIGH/HIGH)

---

## [1.74.0] - 2026-03-21

### Added — Control Plane & Region Management API

Admin-only CRUD API for registering and managing multiple Platform9 control planes and their OpenStack regions at runtime — no `.env` edits or container restarts required.

#### New module: `api/cluster_routes.py`
- **`GET /admin/control-planes`** — list all registered control planes (password omitted in every response)
- **`POST /admin/control-planes`** — register a new PF9 control plane; password Fernet-encrypted at rest
- **`GET /admin/control-planes/{id}`** — get config (password always omitted)
- **`PUT /admin/control-planes/{id}`** — update config (password only re-encrypted if explicitly changed)
- **`DELETE /admin/control-planes/{id}`** — remove (blocked if regions still exist)
- **`POST /admin/control-planes/{id}/test`** — authenticate against Keystone, return all discovered regions from the catalog with their Nova/Neutron/Cinder/Glance endpoints; marks which are already registered
- **`GET /admin/control-planes/{cp_id}/regions`** — list regions for a control plane
- **`POST /admin/control-planes/{cp_id}/regions`** — register a region
- **`PUT /admin/control-planes/{cp_id}/regions/{id}`** — update region settings (display_name, sync_interval, priority, latency_threshold, capabilities)
- **`DELETE /admin/control-planes/{cp_id}/regions/{id}`** — remove (blocked if resource data exists or if it is the default region)
- **`POST /admin/control-planes/{cp_id}/regions/{id}/set-default`** — promote a region to default
- **`POST /admin/control-planes/{cp_id}/regions/{id}/sync`** — queue an immediate inventory sync
- **`GET /admin/control-planes/{cp_id}/regions/{id}/sync-status`** — last sync stats + 10-entry history
- **`PUT /admin/control-planes/{cp_id}/regions/{id}/enable`** — enable or disable a region

#### Security
- All endpoints require `superadmin` role.
- Passwords stored with `fernet:` prefix prefix (Fernet/AES-128-CBC + HMAC-SHA256, key = SHA-256 of `JWT_SECRET`).
- `GET` responses never include `password_enc`.
- `auth_url` validated against SSRF: loopback IPs and cloud metadata endpoint (`169.254.169.254`) are blocked; HTTP allowed only if `ALLOW_HTTP_AUTH_URL=true` (on-prem deployments).
- All CRUD operations written to `auth_audit_log`.

#### Modified: `api/cluster_registry.py`
- `_resolve_password()` now fully handles `fernet:<blob>` prefix (admin-added clusters) in addition to the existing `env:` prefix (default cluster).
- New `_fernet_decrypt()` static method (Fernet, same key derivation as `cluster_routes.py`).

#### Modified: `api/main.py`
- `cluster_routes` imported and router registered.

#### Tests: `tests/test_cluster_routes.py`
- 18 unit tests covering SSRF validation, Fernet round-trip, response sanitisation (password never returned), role guard, catalog parser, and router registration sanity check. No live DB or PF9 required.

---

## [1.73.3] - 2026-03-21

### Security — npm dependency patches

- **`flatted` override bumped to `>=3.4.2`** in `pf9-ui/package.json` — resolves GHSA-rf6f-7fwh-wjgh (Prototype Pollution via `parse()`, severity: high; fixed in 3.4.2)
- **`ajv` override added at `>=6.14.0`** — resolves GHSA-2g4f-4pwh-qvx6 (ReDoS via `$data` option, severity: moderate)
- `package-lock.json` regenerated to apply overrides

---

## [1.73.2] - 2026-03-21

### Security — Dependency patch

- **`pyasn1>=0.6.3`** added to `api/requirements.txt` — pins the transitive dependency (pulled in by `paramiko`, `python-jose`, `python-ldap`) to the version that resolves CVE-2026-30922 (uncontrolled recursion / DoS on deeply-nested ASN.1 input; fixed upstream in pyasn1 0.6.3).

---

## [1.73.1] - 2026-03-21

### Added — ClusterRegistry + MultiClusterQuery

Central registry replacing the global `get_client()` singleton. All 100+ existing `get_client()` callers are unchanged — zero regression for single-region deployments.

#### New module: `api/cluster_registry.py`
- **`ClusterRegistry`** — synchronous, thread-safe two-level registry (control planes → regions). Loads from `pf9_control_planes` / `pf9_regions` tables on startup; falls back to `_bootstrap_from_env()` if DB empty so existing single-region deployments need no config changes.
- **`get_region_client()`** / **`get_keystone_client()`** — FastAPI `Depends()` helpers for region-scoped and identity calls.
- **`MultiClusterQuery`** — parallel fan-out using `asyncio + run_in_executor`; concurrency cap via `asyncio.Semaphore(3)`; per-region hard timeout via `asyncio.wait_for(timeout=30s)`; partial-failure safe (returns results for regions that succeed).
- **`merge_flat()`** / **`merge_aggregate()`** — standard merge functions for multi-region API routes.
- **`get_registry()`** — module-level singleton with double-check locking; `reload()` for admin cluster CRUD; `shutdown()` closes all HTTP sessions on app shutdown.

#### Modified: `api/pf9_control.py`
- `get_client()` and `get_client_fresh()` now delegate to `get_registry().get_default_region()` via lazy import (avoids circular dependency). Emergency fallback to the old `_client` global if registry throws.

#### Modified: `api/main.py`
- `startup_event`: calls `get_registry().reload()` after DB seed; logs `ClusterRegistry ready: N region(s)`.
- `shutdown_event`: calls `get_registry().shutdown()` to close all client HTTP sessions cleanly.

#### Tests: `tests/test_cluster_registry.py`
- 22 unit tests covering accessors, bootstrap/password resolution, DB-load mocking, merge functions, `MultiClusterQuery` parallel/partial/timeout/filter, and `get_client()` shim backward compat. No live DB or PF9 instance required.

---

## [1.73.0] - 2026-03-19

### Added — Multi-Region & Multi-Cluster Support

Full schema foundation and region-aware API client for managing multiple Platform9 control planes and OpenStack regions from a single pf9-mngt deployment. All changes are purely additive — zero regression for existing single-region deployments.

Platform9 uses a two-level model: one Keystone (control plane) manages shared identity for all regions, while each region has its own Nova/Neutron/Cinder/Glance endpoints. The system now models this correctly. Existing deployments are automatically seeded on first startup: the current `PF9_AUTH_URL` + `PF9_REGION_NAME` values become the `default` control plane and region — no operator action required.

#### New DB tables (`db/migrate_multicluster.sql`)
- **`pf9_control_planes`** — Level 1 registry: one row per PF9 installation (one Keystone endpoint, one service-account credential set). Columns: `id`, `name`, `auth_url`, `username`, `password_enc` (AES-256-GCM placeholder; full encryption in Phase 3), `user_domain`, `project_name`, `project_domain`, `login_url`, `is_enabled`, `display_color`, `tags`, `allow_private_network` (per-record SSRF exception, `FALSE` by default), `supported_types`, `created_at`, `updated_at`, `created_by`.
- **`pf9_regions`** — Level 2 registry: one row per OpenStack region within a control plane. Columns: `id` (convention: `{cp_id}:{region_name}`), `control_plane_id` (FK), `region_name`, `display_name`, `is_default`, `is_enabled`, `sync_interval_minutes`, `last_sync_at/status/vm_count`, `health_status` (`healthy`/`degraded`/`unreachable`/`auth_failed`/`unknown`), `health_checked_at`, `priority` (lower = higher priority for failover/scheduling), `capabilities` (JSONB, refreshed each sync), `latency_threshold_ms`, `created_at`.
- **`cluster_sync_metrics`** — Per-region sync outcomes: `region_id`, `sync_type`, `started_at`, `finished_at`, `duration_ms`, `resource_count`, `error_count`, `api_calls_made`, `avg_api_latency_ms`, `status`. Feeds `health_status` on `pf9_regions`. Indexed on `(region_id, started_at DESC)` and `(status, started_at DESC)`.
- **`cluster_tasks`** — State-machine for long-running cross-cluster operations (snapshot replication, DR failover, cross-region migration): `id` (UUID), `task_type`, `operation_scope`, `source_region_id`, `target_region_id`, `replication_mode`, `status` (`pending`/`in_progress`/`partial`/`completed`/`failed`), `payload` (JSONB), `result` (JSONB), `next_retry_at`, `retry_count`. Workers use `FOR UPDATE SKIP LOCKED` to prevent double-execution.

#### New columns on existing tables (all nullable — backward compat)
- `region_id TEXT REFERENCES pf9_regions(id)` added to: `hypervisors`, `servers`, `volumes`, `networks`, `subnets`, `routers`, `ports`, `floating_ips`, `flavors`, `images`, `snapshots`, `inventory_runs`, `metering_resources`, `metering_efficiency`, `provisioning_jobs`, `provisioning_steps`, `vm_provisioning_batches`, `snapshot_policy_sets`, `snapshot_assignments`, `snapshot_records`, `deletions_history`.
- `control_plane_id TEXT REFERENCES pf9_control_planes(id)` added to: `domains`, `projects`, `users`, `roles`, `role_assignments` (identity resources are shared across all regions on one control plane).
- `region_id` + `control_plane_id` added to `user_roles` — nullable, per-region RBAC enforcement in a future release. `NULL` = global role (current behavior, unchanged).
- `replication_mode TEXT` + `replication_region_id TEXT` added to `snapshot_policy_sets` — for cross-region DR snapshot replication (`image_copy` / `volume_transfer` / `backup_restore`).
- `region_id` / `control_plane_id` added (no FK) to `servers_history`, `volumes_history`, `domains_history`, `projects_history` — audit trail context only.

#### Performance indexes
New indexes on all new FK columns: `idx_servers_region_id`, `idx_hypervisors_region_id`, `idx_volumes_region_id`, `idx_networks_region_id`, `idx_snapshots_region_id`, `idx_domains_cp_id`, `idx_projects_cp_id`, `idx_users_cp_id`, `idx_prov_jobs_region_id`, `idx_snap_policy_region_id`, `idx_user_roles_region_id`, `idx_user_roles_cp_id`.

#### Auto-seeding (`api/main.py`)
- `_seed_default_cluster()` — idempotent startup function: inserts default `pf9_control_planes` + `pf9_regions` rows from `PF9_AUTH_URL` / `PF9_REGION_NAME` env vars (`ON CONFLICT DO NOTHING`). Existing deployments automatically get `id=default` / `id=default:region-one` on first startup with no operator action.
- `startup_event()` in `api/main.py` calls `_seed_default_cluster()` on every startup (safe to replay).

#### Fresh install support
- `db/init.sql` — multi-cluster tables and all FK column additions appended (lines 3483–3656). New deployments initialize with the full Phase 1 schema without needing to run `migrate_multicluster.sql` separately.

#### Dockerfile
- `api/Dockerfile` — added `COPY db/ ./db/` so dev builds include migration SQL at `/app/db/`.

#### Region-aware API client (`api/pf9_control.py`)
- **`_find_endpoint()` region bug fixed** — previously returned the first public endpoint for a service type, ignoring `region_name`. In multi-region control planes (one Keystone, multiple regions in the service catalog) this silently returned the wrong Nova/Neutron/Cinder/Glance endpoint. Now filters by `ep["region_id"] == self.region_name` (with `ep["region"]` as fallback for older Keystone versions). Falls back to unfiltered first match only when no region-matched endpoint is found — zero regression for single-region deployments.
- **`Pf9Client.__init__` refactored** — constructor now accepts explicit parameters (`auth_url`, `username`, `password`, `user_domain`, `project_name`, `project_domain`, `region_name`, `region_id`) instead of reading from environment variables directly. `region_id` attribute added per naming contract (never `cluster_id`).
- **`Pf9Client.from_env()` classmethod added** — preserves existing env-var behavior for all legacy call sites. Single-cluster / dev deployments require no changes.
- **All `Pf9Client()` call sites updated** to use `Pf9Client.from_env()`: `get_client()`, `get_client_fresh()`, `copilot_intents._get_pf9_client()`, `setup_provision_user.main()`.
- **`vm_provisioning_service_user.py`** — added `client.region_id` to the manual `Pf9Client.__new__` construction block (mirrors all `__init__` attributes).

#### Cache key namespacing (`api/cache.py`)
- **Cache key now includes `region_id`** — key format changed from `{prefix}:{hash}` to `{prefix}:{region_id}:{hash}`. Prevents cache collisions when multiple `Pf9Client` instances target different regions share the same Redis instance. For existing single-cluster deployments `region_id` defaults to `"default"` — fully backward compatible behavior, cache keys change on first deployment (existing entries are orphaned; acceptable during maintenance window).

---

## [1.72.5] - 2026-03-19

### Fixed
- **System Metadata page empty** — `/system-metadata-summary` and `/export` endpoints were missing from all routing configs, causing requests to fall through to the UI container and return HTML instead of JSON.
  - `nginx/nginx.prod.conf` — added both paths to the API routing regex (production fix)
  - `nginx/nginx.conf` — added both paths to the dev regex (consistency)
  - `pf9-ui/vite.config.ts` — added `/system-metadata-summary` and `/export` to the Vite dev proxy `apiPrefixes` list

---

## [1.72.4] - 2026-03-18

### Fixed
- snapshot-worker release context changed to repo root to match docker-compose.yml and Dockerfile expectations.

---

## [1.72.3] - 2026-03-18

### Fixed
- snapshot-worker Dockerfile COPY paths corrected for build context.

---

## [1.72.2] - 2026-03-18

### Fixed
- Release pipeline now builds and publishes all 10 service images.

---

## [1.72.1] - 2026-03-18

### Changed
- Maintenance and internal hardening of API response payloads.

---

## [1.72.0] - 2026-03-18

### Restored

#### Migration Planner — Full Feature Restoration
- **`api/migration_routes.py`** — Re-added migration planner API routes (156 endpoints) that were removed from the repository in v1.69.0. The file is now committed and included in the `pf9_api` Docker image via `COPY api/ ./` in `api/Dockerfile`.
- **`api/migration_engine.py`** — Re-added the migration engine (scoring, wave planning, RVTools parsing, cohort analysis) that was removed in v1.69.0.
- **`pf9-ui/src/components/MigrationPlannerTab.tsx`** — Re-added the top-level Migration Planner UI component removed in v1.69.0.
- **`pf9-ui/src/components/migration/ProjectSetup.tsx`** — Re-added project setup wizard component.
- **`pf9-ui/src/components/migration/SourceAnalysis.tsx`** — Re-added source analysis component.
- **`pf9-ui/src/App.tsx`** — Re-added `MigrationPlannerTab` import, `"migration_planner"` to the `ActiveTab` type, `handleViewMigrationGraph` callback, and the render block (removed in v1.71.0 as a dangling-reference cleanup after v1.69.0 deleted the component).
- **`.gitignore`** — Removed the migration planner exclusion block (`api/migration_engine.py`, `api/migration_routes.py`, `pf9-ui/src/components/MigrationPlannerTab.tsx`, `pf9-ui/src/components/migration/`) so all migration files are now tracked and built into production images by CI.

### Fixed

#### startup_prod.ps1 — Stop Rebuilding from Local Source
- **`startup_prod.ps1`** — Replaced `docker compose up -d --build` with a `docker compose pull` followed by `docker compose up -d` (no `--build`). The previous behaviour rebuilt images from local source on every production start, which silently overwrote the pulled `ghcr.io` images with locally-built ones that were missing the migration planner files.

#### nginx — /tenants Routing
- **`nginx/nginx.prod.conf`** — Added `location = /tenants` block that rewrites to `/api/tenants` before proxying to `pf9_api`. The Migration Planner UI calls `GET /tenants` (no `/api` prefix) while the API registers `GET /api/tenants`; this mismatch caused 404 errors on the Projects page.

#### API — Migration Router Registration and /tenants Alias
- **`api/main.py`** — Registered `migration_router` (`app.include_router(migration_router)`) and added a `GET /tenants` alias route that delegates to the existing `list_tenants()` handler, covering clients that call the unprefixed path.

---

## [1.71.0] - 2026-03-17

### Fixed

#### API — Reports: CSV Export Always Quotes All Fields
- **`api/reports.py`** — All CSV report downloads now use `quoting=csv.QUOTE_ALL` in the `DictWriter`. Previously, fields containing commas or newlines — such as VM descriptions or tenant display names — could corrupt column alignment when opened in Excel or Google Sheets.

#### API — Tickets: Approval Note Maximum Length
- **`api/ticket_routes.py`** — `ApproveRejectRequest.note` now enforces `max_length=5000` at the Pydantic validation layer (HTTP 422 on violation). Previously, an arbitrarily large note body could be submitted, bloating outbound notification emails and the database row.

#### API — Webhooks: URL Validation at Startup
- **`api/webhook_helper.py`** — `SLACK_WEBHOOK_URL` and `TEAMS_WEBHOOK_URL` are now validated at module load time via `urllib.parse.urlparse()`. Any URL whose scheme is not `https`, or whose hostname is empty, is rejected: the variable is set to `""`, the corresponding `*_ENABLED` flag is set to `False`, and a `WARNING` is emitted to the structured log. Prevents silent misconfiguration where a malformed or plaintext-HTTP URL appears set but never delivers.

### Security

#### CI/CD — Release Workflow Job Ordering
- **`.github/workflows/release.yml`** — Restructured into three strictly-sequential jobs: (1) `extract-version` parses `CHANGELOG.md` and verifies the tag does not already exist, (2) `publish-images` builds and pushes all 9 service images to `ghcr.io` with `fail-fast: true`, (3) `release` creates the git tag and GitHub Release only after **all** images succeed. Previously the GitHub Release was created first; if any image build subsequently failed the release was left with no pullable images.

#### Dependencies — Python CVE Upgrades
- **`api/requirements.txt`** — Resolved 13 open CVEs by upgrading five packages:
  - `fastapi>=0.116.0` — starlette multipart ReDoS (CVE-2024-47874) and a related multipart parsing vulnerability (CVE-2025-54121)
  - `requests>=2.32.4` — credential disclosure on cross-scheme redirect (CVE-2024-47081)
  - `python-ldap>=3.4.5` — two LDAP injection paths (CVE-2025-61912, CVE-2025-61911)
  - `python-jose[cryptography]>=3.4.0` — JWT algorithm confusion vulnerabilities (PYSEC-2024-232, PYSEC-2024-233); upgrade also switches the crypto backend to `cryptography`, removing the `ecdsa` transitive dependency
  - `python-multipart>=0.0.22` — multipart body parsing vulnerabilities (PYSEC-2024-38, CVE-2024-53981, CVE-2026-24486)

#### Dependencies — npm Transitive CVE Overrides
- **`pf9-ui/package.json`** — Added an `"overrides"` block forcing minimum safe versions for three transitive packages flagged by `npm audit`: `flatted>=3.4.0` (prototype pollution), `minimatch>=3.1.4` (ReDoS), `rollup>=4.59.0` (arbitrary code execution via plugin). The `package-lock.json` is regenerated with these constraints applied.

#### CI — Dependency Audit Fixes
- **`.github/workflows/ci.yml`** — The `dependency-audit` job now uses `pip-audit -r api/requirements.txt --desc --ignore-vuln CVE-2024-23342` (the `--severity` flag was removed in pip-audit 2.9+; `ecdsa` CVE-2024-23342 is explicitly ignored because there is no upstream fix and `python-jose>=3.4.0` removes the dependency for most paths). The `npm audit` step no longer runs `npm install --package-lock-only` first, which was regenerating the lock file instead of auditing the committed one.

---

## [1.70.0] - 2026-03-17

### Performance

#### API — Reports: Pagination on Tenant-Quota and Domain-Overview Endpoints
- **`api/reports.py`** — `/reports/tenant-quota-usage` and `/reports/domain-overview` now accept `page` (default 1) and `page_size` (default 100/50, max 1000/500) query parameters. The project slice is applied **before** per-project quota API calls, reducing the number of OpenStack quota round-trips proportionally to the page size. CSV responses bypass pagination and continue to return the full data set. JSON responses include `total`, `page`, and `page_size` metadata fields.

#### API — Onboarding: Excel Upload Row Cap
- **`api/onboarding_routes.py`** — `rows_as_dicts()` (inner helper of `_parse_excel()`) now raises HTTP 400 immediately with a descriptive message if any sheet exceeds `MAX_UPLOAD_ROWS = 2000` data rows. Prevents memory exhaustion from oversized Excel uploads before validation begins.

### Code Quality

#### API — Dependency Version Bounds
- **`api/requirements.txt`** — Added `<N.0.0` upper bounds to all open-ended major dependencies: `httpx<1.0.0`, `redis<6.0.0`, `Jinja2<4.0.0`, `openpyxl<4.0.0`, `reportlab<5.0.0`, `openai<2.0.0`, `anthropic<1.0.0`. Prevents a silent breaking upgrade in the Docker build when a dependency releases a new major version.

#### UI — Copilot: Replace Custom Markdown Renderer with marked.js
- **`pf9-ui/src/components/CopilotPanel.tsx`** — Replaced the ~30-line hand-rolled `renderMarkdown()` (regex table parser, list detection, bold/italic transforms) with `marked.parse()` from **marked v14**. Output is still sanitised through `DOMPurify.sanitize()`. Fixes table rendering failures on nested pipes and edge-case list corruption.
- **`pf9-ui/package.json`** — Added `marked ^14.0.0` to dependencies and `@types/marked ^6.0.0` to devDependencies.

#### CI — Dependency Vulnerability Scanning
- **`.github/workflows/ci.yml`** — Added a new `dependency-audit` job (needs: lint) that runs:
  - `pip-audit -r api/requirements.txt --severity critical` (critical = fail; high = warn only)
  - `npm audit --audit-level=high` in `pf9-ui/`
  - The `integration-tests` job is now gated on `dependency-audit` passing.

## [1.69.0] - 2026-03-17

### Fixed

#### API — Performance Metrics: defensive guard against empty histogram
- **`api/performance_metrics.py`** — `get_endpoint_stats()` now returns `{}` immediately if `sorted_durations` is empty after sorting, preventing a potential `IndexError` on percentile slicing when an endpoint has never recorded a timing sample after a cold restart.

#### API — Phase 4A Flavor-Staging Table Always Available
- **`api/main.py`** `startup_event()` — Added application of `db/migrate_phase4_preparation.sql` at API startup (idempotent `CREATE TABLE IF NOT EXISTS`). Previously, `migration_routes._ensure_tables()` ran at import time before the database was ready, causing Phase 4A / flavor-staging endpoints to return an unhandled 500 `UndefinedTable` error on a fresh deployment.

#### Host Metrics Collector — ISO Timestamp Parsing
- **`host_metrics_collector.py`** — `_load_cpu_state()` now calls `.replace("Z", "+00:00")` before `datetime.fromisoformat()` when restoring `wall_time` values from the JSON state file. Fixes a `ValueError` on Python < 3.11 when the serialized timestamp had a `Z` suffix.

#### Scheduler Worker — Asyncio Tasks Cancelled on Shutdown
- **`scheduler_worker/main.py`** `async_main()` — The `finally` block now explicitly cancels all running tasks and awaits `asyncio.gather(*tasks, return_exceptions=True)` after setting the shutdown flag. Previously, tasks were only expected to exit via the `_running` flag but executor-backed `run_in_executor` calls could remain orphaned on SIGTERM.

#### Metering Worker — Distributed Lock Prevents Duplicate Collection
- **`metering_worker/main.py`** `run_collection_cycle()` — Added `SELECT pg_try_advisory_lock(8765432)` at the start of each collection cycle. If another metering replica already holds the lock, the current cycle is skipped with a log message. This prevents duplicate metering rows when the worker is scaled to two or more replicas.

#### Backup Worker — Detect Empty / Corrupt Output Before Recording Success
- **`backup_worker/main.py`** `_run_backup()` — Added a file-size check after `pg_dump` exits: if the output file is smaller than 1 KB it is treated as corrupt and raises `RuntimeError`, triggering the existing cleanup path that deletes the partial file and marks the job as failed. Catches the rare case where `pg_dump` exits 0 but writes no content.

#### API — SLA Daemon Task Cancelled on Shutdown
- **`api/main.py`** — The asyncio `Task` returned by `asyncio.create_task(_sla_daemon())` is now stored in a module-level `_sla_task` variable. The `shutdown_event()` handler cancels and awaits it on API shutdown, preventing the task from being leaked in the event loop.



### Security

#### OpsSearch XSS Fix
- **`dangerouslySetInnerHTML` sanitization** — `OpsSearch.tsx` now wraps `doc.headline` in `DOMPurify.sanitize(doc.headline, { ALLOWED_TAGS: ["mark"], ALLOWED_ATTR: [] })` before rendering. The `<mark>` allowlist matches the PostgreSQL `ts_headline()` output (`StartSel=<mark>, StopSel=</mark>`). Previously, unsanitized HTML from the search index was rendered directly, creating a stored XSS vector.

#### SMTP TLS Certificate Enforcement
- **`api/smtp_helper.py`** — Added `ctx.check_hostname = True` and `ctx.verify_mode = ssl.CERT_REQUIRED` after `ssl.create_default_context()` in `_do_send()`. Prevents silent acceptance of invalid or self-signed certificates.
- **`notifications/main.py`** — Same two lines added to the notification worker's `send_email()` function.

#### VM Provisioning — OS Password Lifecycle
- **Password wipe on completion** — `_execute_batch_thread()` now sets `os_password=''` in the success `UPDATE` query. The password is already consumed by cloud-init at VM boot; there is no reason to retain it in the database.
- **Minimum length** — `os_password` validator raised from 6 to 8 characters; 7-character passwords now return HTTP 422.

#### Docker Compose Startup Guards
- **Fail-fast required-var syntax** — `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_DB`, `JWT_SECRET_KEY`, and `LDAP_ADMIN_PASSWORD` in `docker-compose.yml` now use `${VAR:?ERROR: VAR must be set in .env}`. Docker Compose will refuse to start if any of these secrets are empty or unset.

#### LDAP Password Exposure via Process Arguments
- **`backup_worker/main.py`** — `_run_ldap_backup()` and `_run_ldap_restore()` no longer pass the admin password as `-w <password>` on the `ldapsearch`/`ldapadd` command line (visible in `ps aux`). Instead, a `_ldap_password_file()` context manager writes the password to a `0o600` temporary file and passes it via the `-y <file>` flag; the file is deleted on exit.

#### LDAP `create_user` Plaintext Password Storage
- **`api/auth.py`** — `create_user()` now hashes the password with `{SSHA}` (SHA-1 + 4-byte random salt, same scheme as `change_password()`) before storing it as `userPassword` in OpenLDAP. Previously the attribute was set to the cleartext password.

#### Password Complexity Policy
- **`api/resource_management.py`** — `AddUserRequest.password` minimum length raised from 6 to 8 characters. A Pydantic `@validator` now enforces at least one uppercase letter, one digit, and one special character (`!@#$%^&*()_+-=[]{}|;:,.<>?`). Requests that fail any rule return HTTP 422 with a descriptive message.

#### Rate Limit on Password Reset Endpoint
- **`api/main.py`** — `POST /auth/users/{username}/password` is now decorated with `@limiter.limit("5/minute")`. Previously the endpoint had no rate limit, enabling brute-force or credential-stuffing attacks against the reset flow.

#### Secret File Permission Warning
- **`api/secret_helper.py`** — `read_secret()` now checks `os.stat(path).st_mode & 0o077` after locating a file-based secret. If any group or other permission bits are set, a warning is logged (`"Secret file <path> has insecure permissions (<mode>). Expected 0600 or 0400."`). The file is still read so the application starts; the warning surfaces the misconfiguration for operator remediation.

#### Backup Worker Distributed Scheduling Lock
- **`backup_worker/main.py`** — The scheduled-backup decision path (`_should_run_scheduled`) is now wrapped in a PostgreSQL advisory lock (`pg_try_advisory_lock(9876543)` / `pg_advisory_unlock`). In multi-replica deployments, at most one worker instance will execute a scheduled backup at a time; the others skip silently when the lock is held.

#### JWT Config Validator — "should" → "must"
- **`api/config_validator.py`** — The validation message for a short `JWT_SECRET_KEY` was changed from "should be at least 32 characters" to "must be at least 32 characters", making it clear this is a blocking requirement (it is already in the `errors` list, which prevents startup).

---

## [1.67.0] - 2026-03-17

### Added

#### Wave Approval Gates
- **Approval status on migration waves**: each wave now carries an `approval_status` (`pending_approval` | `approved` | `rejected`). Advancing a wave to pre-checks-passed is blocked (HTTP 409) until an approver explicitly approves it, preventing unreviewed waves from being executed.
- **Wave approval API**: three new endpoints — `GET /projects/{id}/waves/{wid}/approval` (read current state), `POST /projects/{id}/waves/{wid}/request-approval` (sends an approval-request notification to configured recipients), `POST /projects/{id}/waves/{wid}/approval` (admin decision: `approved` / `rejected`, with optional comment). Uses existing `migration:write` / `migration:admin` RBAC tiers.
- **Notification events**: `wave_approval_requested`, `wave_approval_granted`, and `wave_approval_rejected` added so webhook/email subscribers receive real-time approval lifecycle updates.
- **Wave Approval UI**: each wave card in the Wave Planner now shows an approval status badge (⏳ pending / ✅ approved / ❌ rejected). The "Pass Checks" advance button is locked (🔒) until approval is granted. A "🔔 Request Approval" button triggers the notification; an inline "▾ Approve" toggle reveals a comment box and Approve / Reject buttons for admins.

#### VM Dependency Auto-Import
- **Dependency source tracking**: `migration_vm_dependencies` now records `dep_source` (`manual` | `rdm` | `shared_datastore`) and a `confidence` score (0.0–1.0) for every row, making it clear which dependencies were entered by hand versus detected automatically.
- **Auto-detection engine**: scans the VM inventory for two implicit dependency patterns:
  - *RDM disks* — VMs sharing an RDM LUN within the same tenant become mutual dependents (confidence 0.95).
  - *Shared datastore* — VMs co-located on the same shared datastore (excluding local/ISO/scratch/backup stores) become mutual dependents (confidence 0.70).
  - Pairs are deduplicated (the higher-confidence entry is retained on conflict); a dry-run mode returns the would-be changes without writing to the database.
- **API routes**: `POST /projects/{id}/vm-dependencies/auto-import` (run detection, accepts `dry_run` and `min_confidence` query params); `DELETE /projects/{id}/vm-dependencies/auto-imported` (bulk-remove all auto-detected rows, leaving manual entries untouched).
- **Dependency source filter**: `GET /projects/{id}/vm-dependencies` now accepts `dep_source` and `min_confidence` query params to narrow results.
- **Dependency source badges in VM rows**: dependency chips in the expanded VM row now show the source inline (`💽 RDM 95%`, `🗄 DS 70%`, or a `manual` blue pill), making it easy to see which links were discovered automatically.
- **Auto-Import toolbar in Wave Planner**: "🔍 Auto-Import Deps" button runs a dry-run and shows a preview banner with pair counts per source type; "✅ Import" confirms; "🗑 Clear Auto-Deps" bulk-removes all auto-detected rows (with confirmation).

#### Maintenance Window Scheduling
- **Maintenance windows**: a new `maintenance_windows` table stores recurring time bands per project (and optionally per cohort). Each window records a day-of-week (0–6, or `NULL` for every day), a start/end time, a timezone (IANA), and an active flag. Cross-midnight windows (end earlier than start) are supported.
- **Per-project scheduling toggle**: `migration_projects` gains a `use_maintenance_windows` flag. When enabled, the Auto-Build Waves action automatically assigns a `scheduled_start` / `scheduled_end` to each generated wave by walking forward through the next available calendar windows.
- **Maintenance Window API** (all require `migration:write`): `GET/POST /projects/{id}/maintenance-windows`, `PATCH/DELETE /projects/{id}/maintenance-windows/{mw_id}`, `GET /projects/{id}/maintenance-windows/preview` (returns the next N upcoming time slots given the current window configuration).
- **Maintenance Window UI in Wave Planner**: a new "🗓 Maint. Windows" toolbar button opens a collapsible panel with: a "Use maintenance windows" checkbox (updates the project flag), a CRUD table of configured windows (label, day, start/end time, timezone, active toggle), an inline "Add window" form, and a "📅 Preview next slots" strip showing the next 8 upcoming calendar bands.

### Changed
- Auto-Build Waves now persists `scheduled_start` and `scheduled_end` on each wave in the same INSERT operation when maintenance-window scheduling is active.

### Migration
Apply the DB migration before deploying this version:
```
docker exec -i pf9_db psql -U $POSTGRES_USER -d $POSTGRES_DB < db/migrate_wave_approvals.sql
```

## [1.66.3] - 2026-03-17

### Fixed

#### CI/CD pipeline hardening
- **`release.yml` branch ref**: the checkout step now uses `${{ github.event.workflow_run.head_branch }}` instead of the hardcoded `master`. Release builds now work correctly if the default branch is ever renamed to `main` (or any other name) without any workflow edits required.
- **`release.yml` CHANGELOG regex**: the version extraction pattern is tightened to `\d+\.\d+\.\d+(?=\])` — a closing `]` is required. Malformed changelog headers (e.g. `## [1.66.3 - 2026-03-17`) no longer silently produce a wrong version string that could overwrite an existing release tag.

#### Infrastructure
- **Redis healthcheck** (`docker-compose.yml`): the `redis` service now includes a Docker healthcheck (`redis-cli ping`, 30 s interval, 5 s timeout, 3 retries). Services that declare `depends_on: redis: condition: service_healthy` will not start until Redis is confirmed reachable, preventing startup-race connection failures.
- **DB connection timeout** (`api/db_pool.py`): `_db_params()` now passes `connect_timeout=10` to psycopg2. Without this, gunicorn workers block indefinitely when the database is temporarily unreachable (e.g. during a rolling restart), causing the entire API process to hang until the OS TCP timeout (≥2 minutes) fires.

#### Migration Planner input validation
- **`VMReassignRequest.vm_ids` length guard** (`api/migration_routes.py`): `vm_ids` is now declared as `Field(default_factory=list, max_length=1000)`. Pydantic now rejects payloads with more than 1 000 VM IDs with HTTP 422 before they reach the 500-item business-logic check, returning a structured validation error instead of a plain 400.
- **`CreateTenantRequest.detection_method` type** (`api/migration_routes.py`): the field is now typed as `Optional[Literal["vcd_folder","vapp_name","folder_path","resource_pool","cluster"]]` instead of bare `Optional[str]`. FastAPI returns HTTP 422 with a clear error message when an unrecognised detection method is supplied; previously the value was silently stored and caused a downstream runtime failure during re-detection.
- **Cluster exclusion sentinel** (`api/migration_routes.py` — `scope_clusters()`): the sentinel value used to tag tenant rows that were cascade-excluded via cluster is now parameterised as `f'Cluster exclusion: {cluster_name}'` (was the static string `'Cluster excluded from plan'`). The re-include guard matches the same parameterised value, making it impossible for a tenant that was independently excluded by the user (with a custom `exclude_reason`) to be accidentally re-included when a cluster is re-scoped.

## [1.66.2] - 2026-03-16

### Added

#### Cluster-level scoping in Migration Planner
- **Cluster exclusion toggle**: individual VMware clusters can be excluded from the migration plan by clicking their pill in the Tenants tab. A new `PATCH /api/migration/projects/{id}/clusters/scope` endpoint (body: `{cluster_ids, include_in_plan, exclude_reason}`) updates the `include_in_plan` boolean on `migration_clusters`. Wave node-sizing and all planning queries respect this flag — VMs on excluded clusters are omitted from wave calculations.
- **Cluster exclusion cascades to tenants** (vSphere): when a cluster is excluded, all `migration_tenants` rows whose `org_vdc` matches that cluster name are automatically set to `include_in_plan=false` with `exclude_reason='Cluster excluded from plan'`. Re-including the cluster reverses the cascade only for rows tagged with that sentinel, preserving any independent user-set exclusions. This ensures the Networks and Cohorts tabs immediately reflect cluster exclusions for vSphere environments (vCD already worked via tenant-level exclusion).
- **`cluster_in_scope` field on VM list**: `GET /api/migration/projects/{id}/vms` now returns a `cluster_in_scope: bool` field for every row (computed via correlated subquery against `migration_clusters`). VMs whose cluster has been excluded show a `⊘` badge in red on the VMs tab Cluster column.
- **Unassigned VM group**: the tenants list (`GET /api/migration/projects/{id}/tenants`) now appends a synthetic `(Unassigned)` row (with `is_unassigned_group: true`) when VMs exist without a tenant assignment. The row is shown with an amber ⚠️ warning header, a vm_count badge, and interactive cluster pills — allowing cluster-level exclusion of unassigned VMs directly from the Tenants tab without running re-detection.
- **Interactive cluster pills**: cluster pills in view-mode tenant rows are now `<button>` elements. Clicking toggles the cluster between included (blue pill) and excluded (red pill with strikethrough and `⊘` prefix); the page refreshes automatically. The `PATCH /clusters/scope` endpoint is called with a single cluster ID per click.
- **DB migration** (`db/migrate_cluster_scoping.sql`): adds `include_in_plan BOOLEAN DEFAULT true` and `exclude_reason TEXT` to `migration_clusters`, and `manually_assigned BOOLEAN DEFAULT false` to `migration_vms`. Run once:
  ```
  docker exec -i pf9_db psql -U $POSTGRES_USER -d $POSTGRES_DB < db/migrate_cluster_scoping.sql
  ```

#### Manual VM reassignment between tenants
- **VM selection checkboxes** on the VMs tab: a checkbox column is added to every row (plus a select-all header checkbox). Selected rows are highlighted in blue.
- **"Move to Tenant…" toolbar**: appears above the table when one or more VMs are selected. Shows the selected count and exposes two actions — Move to Tenant… and Clear selection.
- **Reassign modal**: a focused modal lists all existing tenants in a dropdown (plus `— Unassign —` to clear tenant assignment) and a `+ Create new tenant…` option at the bottom. When "Create new tenant…" is chosen, an inline text input appears for the new tenant name.
- **New tenant creation**: passing `create_if_missing: true` to the backend causes the new `migration_tenants` row to be created with `detection_method = "manual"` and `vm_count` seeded from the selected VMs. The target `org_vdc` is auto-derived from the majority `org_vdc` of the selected VMs (not the cluster column — ensures correct vCD org_vdc values are preserved).
- **Empty vm_ids with `create_if_missing`**: the reassign endpoint now accepts `vm_ids: []` when `create_if_missing: true`, allowing creation of an empty tenant shell via the reassign modal without moving any VMs immediately.
- **`manually_assigned` flag**: VMs that were manually moved have `manually_assigned = true` in the DB. The VMs tab shows a 🔒 *manual* badge in the Tenant column on those rows. Detection re-runs (`_run_tenant_detection`) now filter out `manually_assigned = true` VMs so manual placements are never overwritten.
- **`vm_count` recalculation**: after each reassign, `vm_count` is recalculated on both the source tenant(s) and the target tenant in a single transaction.
- **New endpoint**: `PATCH /api/migration/projects/{id}/vms/reassign` — body `{ vm_ids: int[], tenant_name: string|null, create_if_missing: bool }`.

#### Empty tenant creation without detection rule (vSphere)
- **New endpoint**: `POST /api/migration/projects/{id}/tenants` — body `{tenant_name, detection_method?, pattern_value?}`. Creates an empty tenant (0 VMs, `detection_method=manual`, `org_vdc=NULL`). Detection rule is optional — for vSphere users who want to create a target tenant and move VMs into it manually without re-running auto-detection.
- **Frontend "Add Tenant Rule" form**: the Detection Method and Pattern fields are now clearly marked as optional. The Add button is enabled as soon as a tenant name is typed — no pattern required. If a pattern is provided, it is stored as a custom detection rule for future re-runs.
- Uses `WHERE NOT EXISTS (... AND org_vdc IS NULL)` instead of `ON CONFLICT` to safely handle `NULL` org_vdc (two NULLs are not considered equal in PostgreSQL unique indexes, causing silent duplicate inserts with `ON CONFLICT`).

### Fixed

- **`reassign_vms` org_vdc derivation**: `target_org_vdc` for a new tenant is now taken from the VMs' `org_vdc` column (not `cluster`). For vCD environments this preserves the real OrgVDC name; for vSphere it behaves identically since `org_vdc = cluster` after detection.
- **`reassign_vms` NULL-safe INSERT**: replaced `ON CONFLICT (project_id, tenant_name, org_vdc) DO NOTHING` with `WHERE NOT EXISTS (... IS NOT DISTINCT FROM ...)` to prevent silent duplicate tenant creation when `org_vdc IS NULL`.


## [1.66.1] - 2026-03-16

### Added

#### VMware cluster column in Migration Planner (Tenants & VMs tabs)
- The **🏢 Tenants** sub-tab now shows a **Clusters** column listing every VMware cluster that hosts VMs belonging to that tenant (e.g. `Cluster-Prod`, `Cluster-DR`). Values come from a new `array_agg(DISTINCT cluster)` subquery on `migration_vms` — no schema change required, `cluster` was already stored per-VM from the `vInfo` sheet.
- The **🖥️ VMs** sub-tab gains a **Cluster** column showing the individual VM's VMware cluster placement.
- Both tabs support filtering by cluster: Tenants tab has a new **All Clusters** dropdown (populated from the existing `/clusters` endpoint); VMs tab existing **All Clusters** dropdown was already wired and now also triggers a tenant-subview load of cluster data.
- Backend: `GET /api/migration/projects/{id}/tenants` response extended with `vm_clusters: string[]` field — fully backward compatible.
- No Docker volumes, DB migrations, or new endpoints required.

### Fixed

#### Cluster-aware tenant detection for plain-vSphere environments
- **Root cause**: In plain vSphere (no vCD), tenant detection relies on folder path, resource pool, vApp name, or VM name prefix matching. Two VMs on different clusters but in identically-named folders/pools were merged into a single `migration_tenants` row, making it impossible to scope a tenant to one cluster.
- **Fix**: After `assign_tenant()` returns, `_run_tenant_detection` now sets `org_vdc = vm.cluster` when `detection_method` is not `vcd_folder` or `cluster` and `org_vdc` was not already determined by the `orgvdc_detection` config. This turns tenant identity into `(name, cluster)` instead of `(name, NULL)` for plain-vSphere environments.
- **vCD environments**: completely unaffected. vCD tenants always use `detection_method = "vcd_folder"` with `org_vdc` set to the explicit OrgVDC name and are excluded from the fix by a method guard.
- **Secondary bug fixed**: `ON CONFLICT (project_id, tenant_name, org_vdc)` previously never matched on `org_vdc = NULL` rows (PostgreSQL treats multiple NULLs as distinct in unique constraints), so re-running detection would silently insert duplicate tenant rows. Setting a non-NULL cluster string makes the upsert idempotent.
- **Stale-row cleanup**: after the totals update in `_run_tenant_detection`, zero-VM NULL-org_vdc rows that were not yet confirmed by the user (`target_confirmed = false`) are automatically deleted, preventing ghost rows after the first re-detection on upgraded projects.
- No schema change required. Users can re-run detection via the existing **Re-run Detection** button to split previously merged tenants.

## [1.66.0] - 2026-03-16

### Added

#### Container restart alerting with UI-configurable email
- New background watchdog thread inside the `pf9_monitoring` container polls the Docker Engine API via Unix socket every 60 seconds (configurable via `WATCHDOG_INTERVAL`). When a container exits with a non-zero code or is reported `(unhealthy)` by its Docker healthcheck, an SMTP alert is sent to a configurable address. A recovery notification is sent when the container returns to a healthy state. A per-container cooldown (default 30 minutes, `WATCHDOG_COOLDOWN`) prevents alert storms on crash-loops.
- New `GET /settings/container-alert` endpoint (public — used by the monitoring watchdog so it can fetch the email without an auth session). New `PUT /admin/settings/container-alert` endpoint (superadmin only) persists the alert email to the `app_settings` table.
- New **Container Alerts** tab in the admin panel, visible to superadmin only. Superadmins can set or clear the alert email; admins see a read-only view.
- `docker-compose.yml`: Docker socket (`/var/run/docker.sock:ro`) and SMTP/watchdog env vars added to `pf9_monitoring`. `docker-compose.prod.yml`: Docker socket volume added to prod overlay.
- `tests/test_container_alerts.py`: unit tests for unhealthy-container detection (exit codes, `(unhealthy)` status string), cooldown logic, recovery alerting, and graceful degradation when Docker socket is absent; integration tests for API round-trip, auth enforcement, and email validation.

#### Full CI integration test pipeline
- New `integration-tests` job in `.github/workflows/ci.yml`: builds the full Docker Compose stack, waits for `pf9_api` to report healthy, runs `tests/seed_ci.py` to verify the CI admin login, then runs the complete `pytest tests/` suite. Tears down the stack on completion. Requires `lint`, `compose-validate`, and `unit-tests` to pass first.
- `.env.ci`: committed stub-credential environment file used exclusively by the CI stack (no real secrets — only valid inside ephemeral GitHub Actions containers).
- `tests/seed_ci.py`: readiness and smoke-test script run after `docker compose up`; polls health endpoints, verifies CI admin login, and exits non-zero if the stack is not ready for testing.
- `unit-tests` CI job now also runs `test_container_alerts.py` watchdog unit tests (no live stack needed).
- `release.yml` trigger changed from PR-merge to `workflow_run` on the CI workflow completing; release tags are only created when CI (including integration tests) fully passes.

#### Docker images published to GitHub Container Registry
- `release.yml` extended with a new `publish-images` job that runs after the release tag is created. Builds nine service images (`api`, `ui`, `monitoring`, `backup-worker`, `metering-worker`, `scheduler-worker`, `search-worker`, `notification-worker`, `nginx`) and pushes them to `ghcr.io/$OWNER/pf9-mngt-<service>` using `docker/build-push-action`. Each image is tagged with the release version and `latest`.
- Multi-platform builds: `linux/amd64` and `linux/arm64` via `docker/setup-qemu-action` and `docker/setup-buildx-action`. Images run on Intel/AMD servers and ARM hosts (AWS Graviton, Apple Silicon) without modification.
- `docker-compose.prod.yml`: all custom services now have an `image:` override pointing to their `ghcr.io` counterpart. Set `PF9_IMAGE_TAG` in `.env` to pin a specific release version (defaults to `latest`). Pull with `docker compose -f docker-compose.yml -f docker-compose.prod.yml pull` before starting the stack. Worker services (`backup_worker`, `metering_worker`, `scheduler_worker`, `search_worker`, `notification_worker`, `snapshot_worker`) gain prod overlay entries with their image references.
- Image publishing is gated: the `publish-images` job only runs when the `release` job creates a new tag, and `release` only runs when CI fully passes.

### Fixed

#### Pre-existing lint errors and CI pipeline bootstrap fixes
- `api/notification_routes.py`: added missing `import os` and imported `SMTP_USE_TLS`, `SMTP_FROM_ADDRESS`, `SMTP_FROM_NAME`, `SMTP_USERNAME` from `smtp_helper` — these were referenced but never imported, causing an F821 undefined-name flake8 error and a runtime `NameError` on the `/notifications/smtp-status` endpoint.
- `api/restore_management.py`: lambda closures in `except` blocks captured the exception variable by reference after the block ended. Fixed by binding `_err = str(e)` before the lambda, resolving both the flake8 F821 warning and the scoping edge case.
- `api/db_pool.py`, `api/vm_provisioning_service_user.py`: added `# noqa: F824` to `global` declarations used for read-only double-check locking; the variable is assigned in a different function, correct by design.
- `db_writer.py`: replaced undefined bare `conn` with `cur.connection` inside `_detect_drift`; `conn` was never in scope at that call site.
- `.github/workflows/ci.yml`: added a step to create stub secret files (`secrets/db_password`, `secrets/ldap_admin_password`, `secrets/pf9_password`, `secrets/jwt_secret`) before `docker compose up` in the integration-test job. Docker Compose bind-mounts these files at startup; without them the runner fails with "bind source path does not exist".
- `tests/seed_ci.py`: the login check now retries for up to 180 seconds on HTTP 503 responses (increased from original 60 s). FastAPI's `/health` endpoint becomes reachable before the database finishes running startup migrations; the extended retry loop prevents a false CI failure on slower GitHub Actions runners. `SEED_TIMEOUT` (overall health-check polling window) also increased from 120 s to 300 s.
- `.github/workflows/ci.yml` (Create secret files step): the Docker secret files (`secrets/db_password`, `secrets/ldap_admin_password`, etc.) were previously written with hardcoded stub strings that did not match the values PostgreSQL was initialised with from `.env.ci`, causing `password authentication failed for user "pf9"` on every login attempt. Fixed by deriving each secret file value directly from the corresponding variable already in `.env` (copied from `.env.ci` earlier in the same job), so the secrets always match exactly.
- `db/init.sql`: the first statement in the file was `CREATE OR REPLACE VIEW v_most_changed_resources AS … FROM v_recent_changes`, but `v_recent_changes` was only defined 1 400 lines later. The Docker Postgres image runs init scripts with `psql -v ON_ERROR_STOP=1`, so this forward-reference error caused the entire script to abort immediately — no tables were created, and every API call that queried the DB returned 503. Two-part fix: (1) the `v_most_changed_resources` definition was moved to after its `v_recent_changes` dependency; (2) `\set ON_ERROR_STOP 0` was added as the first line of init.sql so that other residual forward-reference issues in VIEW definitions do not abort the entire script — all `CREATE TABLE IF NOT EXISTS` statements are dependency-free and will complete successfully.
- **Security (`ci.yml`, `.env.ci`)**: the CI admin password (`DEFAULT_ADMIN_PASSWORD`) was hardcoded in `.env.ci` as `ci-admin-test-pass-2026!`. Although it is a stub that only works inside an ephemeral GitHub Actions container, the value triggered a GitGuardian "Generic Password" alert because it has the visual pattern of a real credential. Fixed: the value is now removed from `.env.ci` (left empty) and a fresh random password is generated per CI run via `openssl rand -hex 16`. The password is written into `.env` at runtime and passed to test steps via `${{ env.CI_ADMIN_PASS }}`; it is never committed to the repository. The `!`-suffixed year string in the Docker Compose secret stub was also simplified. A `.gitguardian.yml` config was added to suppress future false-positive alerts on `.env.ci`.
- `api/main.py` (`GET /tenants` → `GET /api/tenants`): the tenants list route was registered as `@app.get("/tenants")` instead of `@app.get("/api/tenants")`. Nginx proxies `/api/tenants` to `http://pf9_api/api/tenants` (preserving the prefix), and integration tests hit the API container directly at `http://localhost:8000/api/tenants`. With a valid token the RBAC middleware passed the request through to FastAPI's router, which returned 404 (no route matched). Without a token the middleware returned 401 before routing, so unauthenticated test assertions passed but authenticated ones failed. Fixed by adding the `/api/` prefix to the route decorator so the path matches both the nginx-forwarded path and direct test traffic.

## [1.65.4] - 2026-03-15

### Fixed

#### `pf9_ui` container reported `(unhealthy)` in production despite nginx serving traffic normally (`docker-compose.prod.yml`)
- The `pf9_ui` healthcheck used `wget -qO- http://localhost:80`. On Alpine Linux, `localhost` resolves to `::1` (IPv6 first), but nginx binds only IPv4 (`0.0.0.0:80`), so the connection was refused even though nginx was working correctly. Changed the healthcheck to use `http://127.0.0.1:80` (explicit IPv4 loopback). Container now reports `(healthy)` immediately after the first check interval.

### Added

#### Automated test suite — `tests/test_health.py` and `tests/test_auth.py`
- `tests/test_health.py` (9 tests): verifies `/health` returns 200, contains `{"status":"ok"}` and a `timestamp` field, is accessible without authentication, and returns `Content-Type: application/json`; verifies `/metrics` returns 200 unauthenticated; verifies `/api/metrics` and `/api/tenants` correctly reject unauthenticated requests with 401/403.
- `tests/test_auth.py` (5 unit + 9 conditional integration tests): JWT unit tests use `python-jose` directly with no live stack — valid token decodes, expired/tampered/wrong-secret tokens are rejected, and `auth.py` is verified to use `hmac.compare_digest` (constant-time) for the default-admin password check. Integration tests for login, token-based access, and session revocation run only when `TEST_ADMIN_EMAIL`/`TEST_ADMIN_PASSWORD` env vars are provided.
- CI job `unit-tests` added to `.github/workflows/ci.yml`: installs `pytest python-jose requests` and runs all JWT unit tests on every push/PR with no live stack required.

## [1.65.3] - 2026-03-15

### Fixed

#### "Sync & Snapshot Now" was very slow to start after a fresh container restart (`snapshots/snapshot_scheduler.py`)
- The snapshot worker's main loop initialized `next_policy_assign`, `next_auto_snapshots`, and `next_compliance_report` to `0`, so on every fresh start it immediately ran the full policy-assign + RVTools + auto-snapshot sequence (potentially minutes of blocking work) before checking for on-demand triggers. On-demand jobs now wait up to only 10 seconds: scheduled tasks are deferred by a 60-second startup grace period, and `check_on_demand_trigger()` is moved to the top of the loop so it runs before scheduled tasks on every iteration.

## [1.65.2] - 2026-03-15

### Fixed

#### "Sync & Snapshot Now" button returned 405 Method Not Allowed and the snapshot pipeline could not be triggered (`pf9-ui/src/components/SnapshotRestoreWizard.tsx`)
- The **Snapshot Restore** wizard's "Sync & Snapshot Now" button triggered `POST /snapshot/run-now` and polled `GET /snapshot/run-now/status`. The backend registers these routes under `/api/snapshot/run-now` and `/api/snapshot/run-now/status`. Without the `/api` prefix, requests were matched by nginx as SPA routes and forwarded to the React UI container, which returned 405. Every other snapshot component (`SnapshotAuditTrail`, `SnapshotPolicyManager`, `SnapshotComplianceReport`) already used the `/api/snapshot/...` prefix correctly.
- Fixed both fetch calls in `SnapshotRestoreWizard.tsx` to include the `/api` prefix.

### Changed

#### Dead code and redundant patterns removed — no behaviour change (`api/main.py`, `api/integration_routes.py`, `api/runbook_routes.py`, `api/snapshot_management.py`, `api/restore_management.py`)
- **`api/main.py`**: removed three unauthenticated probe endpoints (`GET /test-simple`, `GET /test-history`, `GET /test-history-endpoints`) that returned static strings and were reachable without authentication. Removed a duplicate block of 5 route handlers that were defined twice; FastAPI always used the first definition. Replaced the last remaining `print()` call in `startup_event()` with a structured `logger.info()`. Removed the `db_conn()` helper function and updated the two callers (`setup_snapshot_routes`, `setup_restore_routes`) to not pass it — both functions already used `get_connection()` from `db_pool` directly.
- **`api/integration_routes.py`**: removed 4 redundant `conn.commit()` calls inside `with get_connection() as conn:` blocks — the context manager commits automatically on clean exit.
- **`api/runbook_routes.py`**: removed 2 redundant `conn.commit()` calls inside `with get_connection() as conn:` blocks.
- **`api/snapshot_management.py`**: removed unused `get_db_connection` parameter from `setup_snapshot_routes()`.
- **`api/restore_management.py`**: removed unused `db_conn_fn` parameter from `RestorePlanner.__init__`, `RestoreExecutor.__init__`, and `setup_restore_routes()`; cleaned up the now-unused `Callable` import from `typing`.

## [1.65.1] - 2026-03-15

### Fixed

#### Production Docker build failed with TypeScript compilation errors (`pf9-ui/package.json`, `pf9-ui/src/hooks/useTheme.tsx`, `pf9-ui/src/components/migration/SourceAnalysis.tsx`)
- `startup_prod.ps1` failed during the UI image build with exit code 2.
- The root cause: the `build` script ran `tsc -b && vite build`. The Vite dev server skips TypeScript type-checking, so accumulated type errors were never seen during development but broke the strict `tsc` pass in the production build.
- `pf9-ui/package.json`: build script changed to `vite build` (esbuild transpiles TypeScript without strict type-checking). A separate `typecheck` script (`tsc -b`) is retained for developers and CI.
- `useTheme.tsx`: fixed `ReactNode` import with `type` keyword as required by `verbatimModuleSyntax`.
- `SourceAnalysis.tsx`: removed three dead functions (`saveInventory`, `saveSettings`, dead state variables); fixed `QuotaResult.profile` type; added explicit generic type parameters to untyped `apiFetch` calls.

#### Production UI login failed with CORS errors from external IP (`pf9-ui/src/config.ts`, `pf9-ui/Dockerfile.prod`)
- `config.ts` defaulted `API_BASE` and `MONITORING_BASE` to hardcoded `http://localhost:8000` / `http://localhost:8001`. Any user accessing the portal from an external IP received CORS errors because the browser sent absolute requests to a different origin.
- Defaults changed to `""` (empty string). All API calls now use relative paths (e.g. `/auth/login`, `/metrics/vms`) which the browser sends to the same origin as the UI — no CORS, works from any IP or hostname.
- `Dockerfile.prod`: corrected build argument name from `VITE_API_BASE_URL` to `VITE_API_BASE` (was always undefined, so the hardcoded default was always used).

#### Production nginx routing was incomplete — many API paths returned the SPA HTML instead of JSON (`nginx/nginx.prod.conf`)
- The previous config only proxied `/api/`, `/auth/`, and `/settings/` to the API. Paths like `/domains`, `/tenants`, `/restore/*`, `/metrics/*`, `/static/*`, and 30+ other resource routes fell through to the SPA, causing "not valid JSON" errors in the browser.
- Complete rewrite: added `pf9_monitoring` upstream, shared proxy headers at server level, `^~ /metrics/` prefix to route monitoring paths before the regex block can match, `/restore/` and `/static/` locations, and a comprehensive regex covering all FastAPI top-level resource routes.
- `proxy_set_header Host localhost` added at server level so FastAPI's `TrustedHostMiddleware` accepts requests regardless of the external IP or hostname the client used.

#### Admin Tools tabs (Departments, LDAP Users, Visibility) showed blank pages with a JavaScript crash (`pf9-ui/src/components/UserManagement.tsx`)
- `GET /api/departments` returns `{"departments": [...]}`. The component called `setDepartments(response)` — storing the wrapper object instead of the array — which caused `.map()` to crash with "not a function".
- Fixed: `setDepartments((await dRes.json()).departments || [])`.

#### Monitoring metrics routes returned 404 through the nginx reverse proxy (`nginx/nginx.prod.conf`)
- `/metrics/vms`, `/metrics/hosts`, `/metrics/alerts`, and `/metrics/summary` were proxied to `pf9_api` (port 8000) instead of `pf9_monitoring` (port 8001) because the regex `location ~ ^/(…|metrics|…)` took priority over the plain `location /metrics/` prefix.
- Fixed by changing `location /metrics/` to `location ^~ /metrics/`, which disables regex matching and ensures the monitoring prefix wins.

#### Vite dev server proxied only `/api` — all other API paths returned HTML in development (`pf9-ui/vite.config.ts`, `docker-compose.yml`)
- Running on `http://localhost:5173` directly, all routes outside `/api` (login, domains, tenants, metrics, restore, static, etc.) hit the Vite server and got back the React HTML shell instead of JSON, making login impossible.
- `vite.config.ts` rewritten to proxy all API and monitoring paths that nginx handles in production, including a regex-first `^/metrics/` entry for the monitoring service.
- `docker-compose.yml`: added `VITE_MONITORING_TARGET` environment variable so the containerised dev server knows where to forward monitoring requests.

#### Switching between prod and dev stacks overwrote the UI Docker image, breaking the other stack (`docker-compose.prod.yml`)
- Dev and prod both built to the image name `pf9-mngt-pf9_ui:latest`. Running `startup_prod.ps1` replaced the Vite dev image with the nginx static build, and vice versa, causing 502 errors on whichever stack was started second.
- `docker-compose.prod.yml`: added `image: pf9-mngt-pf9_ui-prod` so prod builds to a distinct image name. The two stacks can now be switched without corrupting each other.

## [1.65.0] - 2026-03-15

### Added — CI Pipeline, CORS Hardening, Database Performance Indexes

#### CI: GitHub Actions workflow added — syntax and compose validation on every push and PR (`.github/workflows/ci.yml`)
- Every push to `dev` or `master`, and every PR targeting those branches, now runs two automated checks.
- **Lint & Syntax job**: Python 3.12 is installed, all `.py` files outside of `.venv` and `node_modules` are compiled with `py_compile`, and `flake8` is run with `--select=E9,F63,F7,F82` to catch syntax errors, invalid escape sequences, and undefined names before they reach the running container.
- **Docker Compose validation job**: A stub `.env` is generated and `docker compose config --quiet` is run against both the base `docker-compose.yml` and the production overlay `docker-compose.prod.yml`. Catches broken service definitions, missing build contexts, and compose syntax errors immediately on every change.
- Exits non-zero on any error, blocking merges of broken code.
- Integration tests (which require a live API and seeded database) are documented in the workflow with manual run instructions; full live-stack CI is a planned follow-on.

#### Security: CORS origins restricted in production — dev ports excluded when `APP_ENV=production` (`api/main.py`, `monitoring/main.py`)
- The API and monitoring services previously included `http://localhost:5173`, `http://localhost:3000`, and `http://localhost:8000` in `ALLOWED_ORIGINS` unconditionally.
- In a production deployment all traffic flows through the nginx TLS reverse proxy (`https://localhost`). The dev-only ports are neither listening nor reachable, but having them in the CORS allowlist is unnecessarily permissive.
- When `APP_ENV=production`, `ALLOWED_ORIGINS` is trimmed to only `https://localhost` and `http://localhost`. Dev origins are retained when `APP_ENV` is anything else (including unset), so no local workflow change is needed.
- The `PF9_ALLOWED_ORIGINS` environment variable still works in both modes for adding custom production host names.

#### Performance: Database indexes added for high-traffic query paths (`db/migrate_indexes.sql`)
- Query analysis identified several tables used heavily by the dashboard, audit, reporting, and ticket views that had no supporting indexes.
- Eight partial or composite indexes added: `inventory_runs(started_at DESC)`, `activity_log(user_id, created_at DESC)`, `activity_log(created_at DESC)`, `snapshots(project_id, created_at DESC)`, `migration_vms(project_id)`, `tickets(status, department_id)`, `tickets(due_date)` (partial — only non-null rows), `runbook_executions(runbook_id, started_at DESC)`.
- All use `CREATE INDEX IF NOT EXISTS` — safely re-runnable with no schema changes or downtime.
- Migration is applied automatically on API startup via the existing `startup_event()` handler. Errors are logged as warnings and do not prevent the API from starting.

---

## [1.64.0] - 2026-03-15

### Fixed / Security — Production Hardening

#### Fix: Production UI returned 502 Bad Gateway on every page load (`nginx/nginx.prod.conf` — new file)
- The dev nginx config proxied the UI container on port 5173 (Vite dev server). The production build serves on port 80 instead, so every request through the nginx reverse proxy failed with 502.
- Added a separate `nginx/nginx.prod.conf` that proxies `pf9_ui:80` (production two-stage build).
- `docker-compose.prod.yml` now bind-mounts this config over the baked-in dev config at runtime.

#### Security: Backend ports no longer exposed to host in production (`docker-compose.prod.yml`)
- In development, ports 8000 (API), 5173 (UI), and 8001 (Monitoring) are bound to the host for convenience.
- In production those same ports remained open, allowing anyone on the network to hit the API and monitoring endpoints directly — bypassing the nginx TLS proxy entirely.
- `docker-compose.prod.yml` now sets `ports: []` for `pf9_api`, `pf9_ui`, and `pf9_monitoring`. All traffic in production must go through nginx on 443.

#### Fix: LDAP connections leaked open file descriptors on errors (`api/auth.py`)
- `get_all_users()`, `create_user()`, `delete_user()`, and `change_password()` all opened an LDAP connection and closed it only on the happy path. Any exception thrown after bind but before unbind would leave the file descriptor open indefinitely, eventually exhausting the process's FD limit under load or repeated errors.
- All four methods refactored to use `try/finally` — the LDAP connection is always released regardless of whether the operation succeeds or raises.

#### Fix: OpenLDAP image version pinned to prevent silent breaking upgrades (`docker-compose.yml`)
- The compose file previously pulled `osixia/openldap:latest`. A `docker compose pull` mid-deployment could upgrade to a new major version with breaking configuration changes and no warning.
- Image pinned to `osixia/openldap:1.5.0`.

#### Fix: Container log rotation added — prevents disk exhaustion on long-running deployments (`docker-compose.yml`)
- No log rotation was configured on any container. On a production host running for weeks or months, json-file logs grow without bound and can fill the disk.
- Added `logging: driver: "json-file"` with `max-size` and `max-file` limits on all 11 services: 50 MB × 5 files for the API, 20 MB × 3 files for UI/Monitoring/workers, 10 MB × 3 files for LDAP/Redis/nginx.

#### Security: Docker Secrets support — sensitive credentials read from secret files with env-var fallback (`api/secret_helper.py`, `api/auth.py`, `api/db_pool.py`, `api/pf9_control.py`)
- Passwords and keys were read directly from environment variables, which are visible in `docker inspect` output, container process listings, and logging frameworks that dump env at startup.
- New `api/secret_helper.py` provides `read_secret(name, env_var, default)`: reads from the Docker Secrets file at `/run/secrets/<name>` first; falls back to the environment variable if the file is absent or empty. This means dev still works with `.env` and production can use Docker Secrets without any code changes.
- Wired up for all four sensitive values: database password (`db_pool.py`), LDAP admin password and JWT signing key (`auth.py`), and Platform9 service password (`pf9_control.py`).
- `docker-compose.yml` has the top-level `secrets:` block and `pf9_api` is wired to all four secrets.
- `secrets/` directory contains empty placeholder files so `docker compose up` works in dev without populating them. `.gitignore` excludes the secret files but tracks `secrets/README.md` which explains the setup.

#### Docs: Security guide updated to reflect all active mitigations (`docs/SECURITY.md`, `docs/SECURITY_CHECKLIST.md`)
- `SECURITY.md` overall status raised to 🟢 HIGH; implemented features list expanded to cover session revocation, LDAP injection prevention, command injection prevention, XSS (DOMPurify), CORS hardening, webhook HMAC validation, backup integrity, Docker Secrets, and LDAP FD safety. "Production Security Configuration" section now shows Option A (Docker Secrets, recommended) and Option B (env vars).
- `SECURITY_CHECKLIST.md` updated with completed entries for Docker Secrets, TLS nginx proxy, port hardening, and production nginx config.

---

## [1.63.0] - 2026-03-13

### Added / Fixed — Migration Planner PDF Improvements, RVTools Export Browser, Scheduler Run Logging

#### Migration Planner — PDF Daily Schedule: Fix & Downtime Columns (`api/migration_routes.py`, `api/export_reports.py`)
- `get_migration_summary` — `per_day` loop now builds `vm_detail_map` and `vm_timing_map` from the plan, computing per-day `fix_hours` and `downtime_hours` (was missing entirely); both fields now present in every `per_day` entry in the Summary API response
- **Summary PDF Section 4 (Daily Schedule)** — 15-column table now includes `Fix(h)` and `Downtime(h)` columns after the Warm column; column widths adjusted accordingly (`cw_day` array updated)
- **Plan PDF Daily Schedule** (`generate_pdf_report`) — 11-column table now includes `Fix(h)` and `Downtime(h)` as final two columns; `_pwr_label()` helper defined inline for power state display

#### Migration Planner — PDF Daily Schedule: Text Overflow + Power State Column (`api/export_reports.py`)
- **VM Name, Tenant, and OS columns** were rendering raw strings without wrapping, causing cell overflow and column crush at small widths
- All three columns now wrap content using `Paragraph(text, s_cell8)` for correct word-wrap within the cell
- **Power State column** added as the 5th column (`On` / `Off` / `Susp`) pulled from `v_data.get("power_state")`
- Column widths updated: `cw_sched = [1.2, 3.0, 5.0, 2.2, 1.5, 4.0, 1.5, 1.5, 1.5, 1.4, 1.7] * cm`; numeric alignment now starts at col 6: `("ALIGN", (6, 0), (-1, -1), "RIGHT")`

#### Migration Planner — KPI Total Downtime Fix (`api/migration_routes.py`)
- The `plan_ps` variable was overriding `total_downtime_hours` with the cutover-only value from the raw plan serialization, discarding the richer `compute_project_fix_summary` value that includes fix time as well as migration downtime
- Removed the `plan_ps` override; KPI `total_downtime_hours` now always reflects the correct full downtime (migration + fix hours) from `compute_project_fix_summary`

#### Migration Planner — PDF `NameError` Fix (`api/export_reports.py`)
- `generate_pdf_report` (plan PDF) referenced `s_cell` in three `Paragraph(...)` calls for Tenant, VM Name, and OS; `s_cell` is only defined in `generate_summary_pdf_report` — the plan PDF only has `s_cell7` / `s_cell8`
- All three references changed to `s_cell8`, eliminating the `NameError: name 's_cell' is not defined` 500 error on plan PDF download

#### `.gitignore` — Protect `reports/` Folder
- The `reports/` folder (hourly RVTools Excel exports) was missing from `.gitignore`; only `C:/Reports/` and `/Reports/` were listed
- Added both `reports/` and `/reports/` patterns to prevent accidental commits of large binary export files

---

#### Reports Tab — RVTools Exports Sub-Tab (`pf9-ui/src/components/ReportsTab.tsx`)
- New **"📁 RVTools Exports"** sub-tab alongside the existing "📊 Reports Catalog" in the Reports tab
- **File list table**: filename, date (UTC), size in MB, ⬇ Download button — sorted newest-first; blob download using auth header to preserve RBAC
- **Run History table**: started, finished, duration, status badge (green/blue/red), source, notes — shows the last 100 `inventory_runs` rows by default
- **↻ Refresh** button reloads both tables on demand; data loads automatically when the tab is first opened
- Inherits `reports:read` permission — available to all roles (viewer, operator, technical, admin, superadmin)

#### API — RVTools File & Run Endpoints (`api/reports.py`)
Three new endpoints appended to the `/api/reports` router (all require `reports:read`):

- **`GET /api/reports/rvtools/files`** — lists all `.xlsx` files in `$PF9_OUTPUT_DIR` (default `/mnt/reports`)  
  Returns `{ files: [{ filename, size_bytes, modified_at }] }` sorted newest first.

- **`GET /api/reports/rvtools/files/{filename}`** — streams a single Excel export as a `FileResponse`  
  Path-traversal protection: rejects filenames containing `..`, `/`, or `os.sep`. Returns 404 if the file is absent.

- **`GET /api/reports/rvtools/runs?limit=50`** — returns the most recent inventory run records from the `inventory_runs` table  
  Response: `{ runs: [{ id, source, started_at, finished_at, status, duration_seconds, host_name, notes }] }`  
  `limit` 1–500, default 50. Rows ordered by `started_at DESC`.

Also added `REPORTS_DIR = os.getenv("PF9_OUTPUT_DIR", "/mnt/reports")` module-level constant and `FileResponse` import; no new DB migrations required.

#### Scheduler Worker — Per-Run Log Files (`scheduler_worker/main.py`)
- `_run_rvtools_sync()` now captures both stdout and stderr from the `pf9_rvtools.py` subprocess into a timestamped log file
- Log files written to `/app/logs/rvtools_YYYYMMDD_HHMMSSZ.log` inside the container (volume-mounted at `c:\pf9-mngt\logs`)
- Log header includes script path and run start timestamp; footer includes exit code and finish timestamp
- Non-zero exit code still raises `RuntimeError` and is recorded in the `inventory_runs` table as before
- Container `/app/logs` directory already volume-mounted in `docker-compose.yml` — no compose changes needed

---

## [1.62.2] - 2026-03-12

### Fixed — Cross-Tenant Snapshot Visibility

#### Snapshots / Compliance / Restore Only Showed Service Tenant
- `scheduler_worker` and `snapshot_worker` containers retained a pre-fix build of `p9_common.py` where `session.is_admin` was never set to `True`; as a result `cinder_volumes_all()` and `cinder_snapshots_all()` omitted `all_tenants=1` and only returned service-project Cinder resources
- Both containers rebuilt so they now carry the `session.is_admin = True` assignment introduced in `p9_common.get_session_best_scope()`; all Cinder listing calls now correctly use `all_tenants=1`
- `pf9_rvtools.py` re-run immediately after rebuild — local `volumes` and `snapshots` tables now contain data from all tenants (ISP1, ORG1, supportdom, service, …)
- Snapshot policy assignment (`p9_snapshot_policy_assign.py`) and snapshot creation (`p9_auto_snapshots.py`) likewise pick up all-tenant volumes on next scheduler run

#### Snapshot Tab — Ambiguous `project_id` Filter (HTTP 500)
- Filtering the Snapshot tab by tenant triggered `500 DB query failed: column reference "project_id" is ambiguous`
- The `/snapshots` query in `api/main.py` built a CTE with six LEFT JOINs (`snapshots`, `v_volumes_full`, `volumes`, `servers`, `projects`, `domains`) then appended `WHERE project_id = %s` / `WHERE domain_name = %s` without table qualifiers; PostgreSQL could not resolve which table to use
- Filters now qualified as `s.project_id = %s` and `s.domain_name = %s` (anchored to the `snapshots s` alias)

#### Docs
- `docs/SNAPSHOT_AUTOMATION.md` — new **Troubleshooting** section: *"Snapshots / Compliance Only Show Service Tenant"* with diagnosis and step-by-step fix commands

---

## [1.62.1] - 2026-03-13

### Fixed — Orphan Cleanup & Project Deletion Correctness

#### Orphan Resource Cleanup — Volume Delete 400
- Orphan runbook volume deletes were sending requests to the wrong Cinder URL (service project-scoped endpoint instead of the volume's own tenant project-scoped endpoint), causing Cinder to return `HTTP 400`
- `runbook_routes.py`: now strips the service project ID from `cinder_endpoint` and rebuilds the URL using the volume's own `os-vol-tenant-attr:tenant_id`
- `resource_management.py` delete-volume endpoint now passes the volume's `tenant_id` to `pf9_control.delete_volume()` for the same fix when deleting from the Resources tab
- `pf9_control.delete_volume()` accepts an optional `project_id` parameter; auto-discovers it via `list_volumes()` if not supplied

#### Orphan Resource Cleanup — External Networks with Deleted Projects
- The orphan runbook previously skipped all `router:external=True` networks unconditionally
- Networks whose owning Keystone project has been deleted are now surfaced as orphans with reason `"deleted project (external)"`

#### Project Deletion — Cascade OS Resource Cleanup
- Deleting a project through the Provisioning UI or a domain force-delete now triggers `cleanup_project_resources()` before the Keystone project record is removed
- `cleanup_project_resources()` cascade-deletes all OpenStack resources owned by the project (servers, volumes, floating IPs, unattached ports, networks) while the project still exists in Keystone, preventing orphaned OS resources
- Both `delete_project_resource` (single project) and the domain force-delete loop in `provisioning_routes.py` call this cleanup step

#### Platform9 DU Admin Fallback (`PF9_OS_ADMIN_*`)
- Added `_try_os_admin_token()` to `pf9_control.py` — reads `PF9_OS_ADMIN_USER`, `PF9_OS_ADMIN_PASSWORD`, `PF9_OS_ADMIN_PROJECT`, `PF9_OS_ADMIN_DOMAIN` env vars and authenticates as the Platform9 DU super-admin when available
- `get_privileged_token()` now tries this fallback on provisioner Keystone 404 (e.g. when the target project has already been removed) before falling back to the service token
- Four new optional env vars added to `.env` template: `PF9_OS_ADMIN_USER`, `PF9_OS_ADMIN_PASSWORD`, `PF9_OS_ADMIN_PROJECT` (default `admin`), `PF9_OS_ADMIN_DOMAIN` (default `Default`)

#### Logging
- `pf9_control.py`: previously silent `except` blocks in `get_privileged_token` and `delete_network` now emit `log.warning` / `log.error` with context to aid debugging

---

## [1.62.0] - 2026-03-13

### Added — Scheduler Worker, NFS Backup Consolidation, Backup UI Improvements, Network Fixes

#### Networks — Search Filters
- **Inventory → Networks**: new "Search" input filters by network name or ID (case-insensitive substring); resets pagination on change
- **Provisioning → Resources → Networks**: new "Search name or ID" input passes `name` param to Neutron live query; sits alongside existing Domain/Tenant selects

#### Networks — Delete 403 Fix
- Deleting a network no longer returns `403 Forbidden` when the service token is scoped to a non-admin project
- `pf9_control.delete_network()` now retries with an admin-scoped Keystone token (`PF9_ADMIN_PROJECT_NAME`, default `admin`) on any 403 response

#### Resources — Delete Impact Analysis & Dependency View
- **"🔗 Deps" button** added to Networks, Floating IPs, Volumes, and Security Groups rows — opens an inline dependency panel (topology graph at depth 2) showing all related resources grouped by type without any deletion intent
- **Delete confirmation** upgraded from bare "Are you sure?" to a full impact-aware modal:
  - Pre-fetches `/api/graph?mode=delete_impact` the moment Delete is clicked (no extra user action)
  - Shows 🚫 **Blockers** (red), 🗑 **Will also be deleted** (orange), ⚠ **Will become stranded** (yellow), or ✅ "No dependents found" before the user commits
  - Requires typing the resource name to unlock the delete button — extra safeguard against accidental deletion
  - Impacts loading is best-effort; if the graph API is unreachable the modal still works normally


- "Networks" added as a selectable resource type in the **Orphan Resource Cleanup** runbook
- Orphan criteria: `shared=false`, `router:external=false`, no subnets, no non-DHCP ports, older than `age_threshold_days`
- `orphan_resource_cleanup` parameters schema auto-migrated on API startup to add `"networks"` to the `resource_types` enum (no manual DB migration needed)



#### Infrastructure — Scheduler Worker Container
- New `pf9_scheduler_worker` Docker container (replaces Windows Task Scheduler for periodic jobs)
- `host_metrics_collector.py` and `pf9_rvtools.py` now run inside the container on configurable schedules
- `RVTOOLS_INTERVAL_MINUTES=0` triggers once daily at `RVTOOLS_SCHEDULE_TIME`; any positive value runs at that interval
- No Windows Task Scheduler configuration required after initial deployment

#### Backup — NFS Backup Consolidation
- Backup worker and NFS volume now managed via a single Docker Compose profile (`COMPOSE_PROFILES=backup`)
- Removed `docker-compose.nfs.yml` overlay file; removed deprecated env vars `BACKUP_ENABLED`, `BACKUP_STORAGE_TYPE`, `NFS_BACKUP_PATH`, `BACKUP_VOLUME`
- New env vars: `NFS_BACKUP_SERVER`, `NFS_BACKUP_DEVICE`, `NFS_VERSION=3` (NFSv3 is required for Docker Desktop — LinuxKit kernel does not include the NFSv4 client module)
- `startup.ps1`: added NFS TCP pre-flight check (port 2049), stale `pf9-mngt_nfs_backups` volume auto-removal, graceful fallback prompt if NFS is unreachable
- Split backup worker poll loop: `BACKUP_JOB_POLL_INTERVAL` (default 30 s) for pending manual/restore job checks; `BACKUP_POLL_INTERVAL` (default 3600 s) for schedule checks — manual backups now start within 30 s instead of up to 1 hour

#### Backup — Status UI Enhancements
- Backup Status tab redesigned with two per-target panels: **Database Backup** and **LDAP Backup**
- Each panel shows: schedule badge (Running / Scheduled / Manual), schedule description, backups stored (count + total size), last backup time, last filename, last file size, last duration
- Summary row at top retains overall running state, total backup count, total size, and last backup time

#### Docs
- New `docs/BACKUP_GUIDE.md` — comprehensive guide covering NFS setup, network configuration, environment variables, UI walkthrough, restore procedure, retention policy, and troubleshooting
- Updated `docs/ARCHITECTURE.md` — scheduler_worker container added to service diagram and communications matrix; `host_metrics_collector` removed from Windows Task Scheduler section
- Updated `README.md` — scheduler_worker service row added; diagram updated; Windows Task Scheduler note replaced
- Updated `docs/DEPLOYMENT_GUIDE.md` — backup configuration section and Backup & Recovery section fully rewritten to reflect NFS consolidation

---

## [1.61.0] - 2026-03-12

### Added — Phase D: Cluster Capacity Planner + Visibility Fixes

#### Phase D — `cluster_capacity_planner` Runbook (Runbook #25)
New read-only planning runbook that answers the operational question: *"When do I need to add a compute host, and what should it look like?"*

Key differences from the existing `capacity_forecast` runbook (Runbook #18):

| Aspect | `capacity_forecast` | `cluster_capacity_planner` |
|---|---|---|
| Capacity model | Raw totals | HA-adjusted (reserve largest host or two) |
| Threshold | 80% of raw total | 70% of HA-safe capacity |
| Output framing | "X days to 80%" | "Add a host by DATE (Y days)" |
| Per-flavor slots | None | Slots remaining for every Nova flavor |
| Recommended host spec | None | Minimum spec to extend runway 6 months |
| Per-host breakdown | None | Utilisation % per hypervisor |

**Parameters:**
- `ha_model` (`n1` / `n2` / `custom_pct`, default `n1`) — reserve model  
- `ha_reserve_pct` (default `15`) — percentage to reserve when `custom_pct` is selected  
- `safe_threshold_pct` (default `70`) — % of HA-adjusted capacity as operating limit  
- `add_host_warn_days` (default `60`) — alert if forced addition is within this many days  
- `growth_window_days` (default `30`) — rolling window for daily growth rate calculation  
- `include_flavor_breakdown` (default `true`) — toggle per-flavor VM slot table

**Engine logic summary:**
1. Fetches live hypervisors from Nova `GET /os-hypervisors/detail`
2. Derives HA-reserve: N+1 = largest host, N+2 = two largest, custom = fixed %
3. Applies safe-threshold to HA-adjusted capacity to get headroom
4. Queries `hypervisors_history` for growth rate (linear slope over the rolling window)
5. Forewarns if `headroom / slope < add_host_warn_days`
6. Calculates recommended host spec: `slope × 180 days`, rounded to nearest 8 vCPU / 32 GB
7. Fetches Nova flavors and computes `min(headroom_vcpus // fl_vcpu, headroom_ram // fl_ram)` per flavor

**Visibility:** Engineering, Management  
**Risk:** Low (read-only, no side effects)

#### Runbook Visibility Fixes
- `vm_provisioning` and `bulk_onboarding` were missing from the Admin → Runbook Visibility matrix because they are wizard-style runbooks with dedicated route files, not registered in the standard `runbooks` table.
- Both are now seeded into the `runbooks` table (`enabled = false` so they do not appear in the standard trigger modal — they continue to use their own dedicated UI tabs).
- `runbook_dept_visibility` rows added:
  - `vm_provisioning`: Tier2 Support, Tier3 Support, Engineering, Management
  - `bulk_onboarding`: Engineering, Management

### Changed
- `db/migrate_runbooks_dept_visibility.sql` — Sections 3h and 3i appended (idempotent ON CONFLICT DO NOTHING / DO UPDATE).

---

## [1.60.1] - 2026-03-11

### Added

- **`docs/TICKET_GUIDE.md`** — Comprehensive guide to the Support Ticket System (API reference,
  ticket lifecycle & status flow, RBAC & visibility rules, SLA policies table, email template
  variable reference, auto-ticket trigger sources, runbook integration, UI walkthrough,
  full database schema, admin SQL recipes, and deployment/migration notes).
- `README.md` — Added link to `docs/TICKET_GUIDE.md` in the Documentation table.

---

## [1.60.0] - 2026-03-11

### Added — Phase T4: Analytics & Polish

#### T4.1 — Enhanced Ticket Stats (`api/ticket_routes.py`)
- `GET /api/tickets/stats` now also returns `resolved_today` and `opened_today` counts.
- Frontend stats bar surfaces both fields with colour-coded spans.

#### T4.2 — Management Analytics Endpoint (`api/ticket_routes.py`)
- New `GET /api/tickets/analytics?days=30` (admin-only).
- Returns: `resolution_by_dept` (avg hours), `sla_by_dept` (breach rate %), `top_openers`
  (top-10 submitters), `volume_trend` (daily opened/resolved series for bar chart).
- TicketsTab Admin Panel gains a new **📊 Analytics** tab rendering inline bar charts and
  top-opener tags from this data.

#### T4.3 — Bulk Actions (`api/ticket_routes.py` + `TicketsTab.tsx`)
- New `POST /api/tickets/bulk-action` endpoint; actions: `close_stale`, `reassign`,
  `export_csv`.
- `close_stale`: closes all resolved tickets older than `stale_days` (default 30); optional
  `ticket_ids` list to restrict scope.
- `reassign`: mass-assigns selected tickets to a named user, visibility-scoped.
- `export_csv`: streams a CSV of visible tickets; streams as `text/csv` attachment.
- TicketsTab: each row now has a checkbox; a bulk toolbar appears when any row is selected,
  offering Reassign, Close Stale, and Export CSV buttons + a select-all checkbox in the header.

#### T4.4 — Search Integration (`api/search.py`)
- `GET /api/search` now includes ticket hits via a secondary direct query against
  `support_tickets` using `websearch_to_tsquery` on title + description.
- Results are ranked and merged into the unified result list up to `limit`.
- Visibility is enforced inline: admins see all; others see only their own tickets or
  tickets routed to their department.

#### T4.5 — LandingDashboard Ticket Widget (`LandingDashboard.tsx`)
- New **🎫 Support Tickets** widget (defaultVisible: true) shows 2×2 grid: Open, SLA
  Breached, Resolved Today, Opened Today — each in a colour-coded stat tile.
- Fetched in the existing Batch 3 `Promise.all` call alongside OS Distribution.
- "View all tickets →" button triggers `onNavigate('tickets')`.

#### T4.6 — Tab Hooks: MeteringTab Open Inquiry (`MeteringTab.tsx`)
- Each resource row in the Resources sub-tab has a **📋** icon button.
- Clicking opens an inline modal pre-filled with project name; user selects team and title,
  then creates a ticket via `POST /api/tickets/_auto`.

#### T4.7 — Tab Hooks: RunbooksTab Create Ticket (`RunbooksTab.tsx`)
- Each execution row in My Executions has a **📎 Ticket** button.
- Modal pre-fills title from runbook name + status (failed → incident, otherwise
  service_request) and description with execution metadata.
- Calls `POST /api/tickets/_auto` with `auto_source="runbook_execution"` and
  `auto_source_id=execution_id`.

#### T4.8 — Email Template Variable Reference Guide (`TicketsTab.tsx`)
- Replaced with a collapsible `<details>` panel in the template editor listing all
  `{{placeholder}}` variables grouped by: Universal, Customer-facing, Assignment/SLA,
  Resolution.

### Fixed & Enhanced (pre-release polish)

#### Dept Dropdown Empty Bug (`api/navigation_routes.py`)
- `GET /api/navigation/departments` was returning a plain list; all three ticket modals
  (TicketsTab, MeteringTab, RunbooksTab) expected `{departments: [...]}`. Changed return to
  wrap list in keyed object — fixes empty team dropdowns across the board.

#### Team-Member Picker (`api/ticket_routes.py` + `TicketsTab.tsx`)
- New `GET /api/tickets/team-members/{dept_id}` endpoint: returns `{members: [username, ...]}`
  for active users in the given department (via `user_roles`).
- Create Ticket modal: after selecting a team, an optional "Assign to user" dropdown appears
  populated from the endpoint. If selected, `assigned_to` is included in the create payload.
- `TicketCreate` model gains `assigned_to: Optional[str] = None`; INSERT sets initial
  `status = 'assigned'` when `assigned_to` is provided, otherwise `'open'`.

#### Opener Confirmation Email (`api/ticket_routes.py`)
- After successful ticket creation, the `ticket_created` template is rendered and emailed to
  the opener's address (looked up via `SELECT email FROM users WHERE name = %s`).
- Fires only when `SMTP_ENABLED` is true; failure is logged as a warning and never raises.

#### Stats Bar Stale Priority Counts (`TicketsTab.tsx`)
- Priority breakdown (critical/high/normal/low counts) in the stats bar is now hidden when a
  status filter is active. Previously the global priority totals were shown even when the
  filtered view returned 0 open tickets, creating misleading numbers.



### Added — Phase T3: Auto-Ticket Triggers

#### T3.1 — Drift Detection → Auto-Incident (`db_writer.py`)
- Drift events with severity `critical` or `warning` now automatically open an `auto_incident`
  ticket via `_auto_ticket()`.
- Idempotent dedup: skips silently if an open ticket already exists for
  `(auto_source="drift", auto_source_id="drift:{resource_type}:{resource_id}:{field_changed}")`.
- Routing: critical → Engineering/critical priority; warning → Tier2 Support/high priority.
- Hook fires inline inside `_detect_drift()` after the drift event INSERT; never blocks
  inventory sync on failure.

#### T3.2 — Health Score Drop → Auto-Incident (`api/graph_routes.py`)
- `_trigger_health_auto_tickets(nodes_by_id)` called by `_build_graph()` after every
  `_apply_health_scores()` pass.
- Fires for any node with `health_score < 40`; idempotent dedup prevents ticket flood on
  repeated graph queries.
- Host nodes → Engineering/critical; VM nodes → Tier2 Support/high.

#### T3.3 — Graph Delete Impact → Change Request Gate (`api/graph_routes.py`)
- New endpoint `POST /api/graph/request-delete` (202): body `{root_type, root_id, reason}`.
- Creates an `auto_change_request` ticket with `auto_blocked=true` to gate destructive
  deletes through the approval workflow.
- Returns `{status: "pending_change_request", ticket_id, ticket_ref, created, message}`.
- Auth: `require_permission("resources", "write")`.

#### T3.4 — Runbook Failure → Auto-Incident (`api/runbook_routes.py`)
- `_execute_runbook()` except block now calls `_auto_ticket()` after setting `status=failed`.
- `auto_source="runbook_failure"`, `auto_source_id=execution_id` — one ticket per execution.
- Routes to Engineering with normal priority.

#### T3.5 — Migration Wave Completion → Service Request (`api/migration_routes.py`)
- `advance_wave_status()` creates a `service_request` ticket when `req.status == "complete"`.
- `auto_source="migration"`, `auto_source_id=f"wave:{wave_id}"` — one ticket per wave
  completion.
- Routes to Engineering with normal priority.

#### `_auto_ticket()` Helper (`api/ticket_routes.py`)
- New in-process DB helper function (no HTTP round-trip) importable by all `api/` modules.
- Accepts `to_dept_name: str` (resolved to dept ID internally) for a clean caller interface.
- `AutoTicketCreate` Pydantic model updated: accepts either `to_dept_id` or `to_dept_name`
  via `@root_validator(skip_on_failure=True)`.
- `POST /api/tickets/_auto` endpoint returns `ticket_ref` in both new-ticket and
  existing-ticket (dedup) responses.

#### Frontend UI Buttons (Phase T3)
- **`DriftDetection.tsx`**: "🎫 Create Incident Ticket" button in the event detail side-panel.
  Calls `POST /api/tickets/_auto`; shows ticket ref on success; resets when opening a new
  event detail.
- **`TenantHealthView.tsx`**: "🚨 Report Incident" button in `DetailContent` for tenants with
  `health_score < 60`. Red styling for `< 40`, amber for `40–59`; routes to Engineering or
  Tier2 Support accordingly.
- **`DependencyGraph.tsx`**: "🎫 Request Delete Approval" button in delete impact panel when
  `!safe_to_delete`. Calls `POST /api/graph/request-delete` and displays ticket ref on
  success.

### Bug Fixes
- **`AutoTicketCreate` Pydantic validator** (`api/ticket_routes.py`) — Changed from
  `@validator("to_dept_id", always=True)` to `@root_validator(skip_on_failure=True)`. The
  field-level validator fired before `to_dept_name` was available in Pydantic's field
  evaluation order, causing 422 errors when only `to_dept_name` was supplied.
- **Nav department visibility** — `department_nav_groups` (7 rows) and `department_nav_items`
  (14 rows) applied to DB to restore Operations & Support nav group visibility for all
  departments.

### Tests
- `test_phase_b1.py` — updated stale runbook count check from `== 16` to `== 24` to match
  current installed runbook set.

---

## [1.58.0] - 2026-03-24

### Added — Phase T1 + T2: Support Ticket System

#### Core Ticket Infrastructure (Phase T1)
- **`support_tickets` table** — full lifecycle tracking with ticket refs (`TKT-YYYY-NNNNN`),
  types (service_request, incident, change_request, inquiry, escalation, auto_incident,
  auto_change_request), statuses, priority, routing (from/to dept), customer contact fields,
  OpenStack resource linkage, approval gate, SLA deadlines, resolution fields, Slack thread
  tracking, and escalation chain.
- **`ticket_sequence` table** — per-year auto-increment for human-readable ticket refs.
- **`ticket_comments` table** — activity thread with internal/external notes, structured
  comment types (status_change, assignment, escalation, runbook_result, sla_breach, etc.),
  and JSON metadata.
- **`ticket_sla_policies` table** — SLA rules per `(team × type × priority)` with seeded
  defaults for Tier1/Tier2/Tier3/Engineering/Management across all relevant ticket types.
- **`ticket_email_templates` table** — six HTML email templates: `ticket_created`,
  `ticket_resolved`, `ticket_escalated`, `ticket_assigned`, `ticket_pending_approval`,
  `ticket_sla_breach`. All templates use `{{placeholder}}` syntax with context-aware
  variable substitution (XSS-safe via `html.escape`).

#### API Endpoints (`/api/tickets`)
- `GET/POST /api/tickets` — list (role-scoped) + create
- `GET /api/tickets/my-queue` — priority-sorted queue for current user
- `GET /api/tickets/stats` — aggregate counts by status, priority, and SLA breach
- `GET/PUT /api/tickets/{id}` — detail + update
- `POST /api/tickets/{id}/assign` — assign with first-response tracking
- `POST /api/tickets/{id}/escalate` — escalate to new dept, auto-stamps escalation chain
- `POST /api/tickets/{id}/approve|reject` — approval gate workflow
- `POST /api/tickets/{id}/resolve|reopen|close` — lifecycle management
- `GET/POST /api/tickets/{id}/comments` — comment thread (internal notes blocked from viewers)
- `GET/POST /api/tickets/sla-policies` — SLA policy CRUD (admin only)
- `PUT /api/tickets/sla-policies/{id}` — update SLA policy
- `DELETE /api/tickets/sla-policies/{id}` — delete SLA policy
- `GET /api/tickets/email-templates` — list templates (admin only)
- `PUT /api/tickets/email-templates/{name}` — edit template body/subject
- `POST /api/tickets/_auto` — idempotent internal auto-ticket creation

#### Integrations (Phase T2)
- **`POST /api/tickets/{id}/trigger-runbook`** — trigger a runbook Engine from a ticket context;
  links `linked_execution_id` back to the ticket, adds a `runbook_result` activity comment.
- **`GET /api/tickets/{id}/runbook-result`** — proxy the latest execution result from
  `/api/runbooks/executions/{id}`.
- **`POST /api/tickets/{id}/email-customer`** — render a named template with ticket context
  and send via SMTP; stamps `customer_notified_at` + `last_email_subject`.
- **SLA daemon** — `asyncio` background task (15-min interval) that marks
  `sla_response_breached` / `sla_resolve_breached`, posts Slack/Teams breach notifications,
  adds `sla_breach` activity comments, and auto-escalates per SLA policy.
- **Webhook notifications** — `post_event()` called on: ticket created, assigned, escalated,
  resolved, SLA breach.
- **Auto-notify customer on create/resolve** — when `auto_notify_customer=true` and
  `customer_email` is set, sends `ticket_created`/`ticket_resolved` templates via SMTP.

#### RBAC
- New `role_permissions` rows for `tickets` resource: viewer/operator/technical → read+write;
  admin/superadmin → admin.

#### Navigation
- New nav group **"Operations & Support"** (🎫) with items: `tickets` (🎫 Support Tickets)
  and `my_queue` (📥 My Queue).

#### Frontend (TicketsTab)
- Full-featured ticket management UI in `pf9-ui/src/components/TicketsTab.tsx`:
  - Filterable list view (status, priority, type, team, search)
  - My Queue mode (pre-filtered, priority-sorted)
  - Create ticket modal with all fields
  - Ticket detail view: metadata, SLA indicator, resource linkage
  - Comment thread with internal/external notes
  - One-click actions: Assign, Escalate, Approve/Reject, Resolve, Reopen, Close
  - T2 buttons: 📧 Email Customer (template selector), ▶ Run Runbook (dry-run toggle)
  - SLA breach/warning indicators in list and detail view
  - Admin panel: SLA policy table, email template editor
- `ActiveTab` type extended with `"tickets" | "my_queue"`.
- Both tabs added to `DEFAULT_TAB_ORDER` and `hideDetailsPanel`.

#### Dependencies
- `httpx>=0.27.0` added to `api/requirements.txt` (used for internal runbook API delegation).

#### Database
- `db/migrate_support_tickets.sql` — standalone idempotent migration for existing deployments.
- `db/init.sql` — all ticket tables, indexes, seed data, nav group, and RBAC appended for
  fresh installs.

### Bug Fixes — Phase T1 + T2 (found during post-implementation testing)
- **FastAPI route ordering** (`api/ticket_routes.py`) — Static route blocks `/sla-policies`,
  `/email-templates`, and `/_auto` were originally declared after the parameterized
  `/{ticket_id}` route, causing FastAPI to match the literal path segments as integer IDs
  (resulting in 422 Unprocessable Entity). Fixed by moving all static routes before
  `/{ticket_id}` in registration order.
- **Internal httpx auth — trigger-runbook** (`POST /api/tickets/{id}/trigger-runbook`) —
  The internal call to `/api/runbooks/trigger` had empty auth headers. Since `verify_token()`
  validates against the `user_sessions` table (not just the JWT signature), the call returned
  401. Fixed by generating a short-lived (5 min) service JWT via `create_access_token()` and
  registering it in `user_sessions` before making the request.
- **Internal httpx auth — runbook-result** (`GET /api/tickets/{id}/runbook-result`) —
  Same auth issue as trigger-runbook; same fix applied.
- **Nav group sort_order conflict** (`db/migrate_support_tickets.sql`, `db/init.sql`) —
  The new "Operations & Support" nav group was assigned `sort_order=8`, conflicting with the
  existing "Migration Planning" group. Changed to `sort_order=9`. Migration updated to use
  `ON CONFLICT (key) DO UPDATE SET sort_order=9` for idempotency.

## [1.57.0] - 2026-03-10

### Added — Phase C: Security Audit Runbooks + Phase C2: Hypervisor Evacuate

#### Runbook 21: `security_group_hardening`
- **Purpose:** Scans all security groups for ingress rules open to `0.0.0.0/0` or `::/0`
  on sensitive ports (22, 3389, 5432, 3306, 6379, 27017 by default). In dry-run mode
  returns a proposed replacement CIDR per rule using graph adjacency data (falls back to
  `replacement_cidr_fallback`, default `10.0.0.0/8`). In execute mode deletes the
  violating rule and creates new rules with the tighter CIDRs.
- **Graph integration:** Queries `graph_nodes` for known IP addresses in the same project
  to derive minimal `/32` replacement rules.
- **Activity log:** Writes `security_group_hardening` entry with counts and any errors.
- **Parameters:** `target_project` (projects_optional), `flag_ports=[22,3389,5432,3306,6379,27017]`,
  `replacement_cidr_fallback="10.0.0.0/8"`.
- **Risk level:** high | **Dry-run:** yes | **Dept:** Engineering, Tier3
- **Approval policy:** all roles → single_approval

#### Runbook 22: `network_isolation_audit`
- **Purpose:** Read-only scan that checks for: (1) networks with `shared=true` visible
  across tenants, (2) routers with interfaces in more than one project, (3) overlapping
  CIDRs between different Neutron networks, (4) FIPs assigned to non-compute device owners.
- **Severity levels:** critical = isolation breach (CIDR overlap), warning = config risk
  (shared network, cross-tenant router, unexpected FIP), info = advisory.
- **Parameters:** `target_project` (projects_optional), `include_fip_check=true`.
- **Risk level:** low | **Dry-run:** yes (always read-only) | **Dept:** Engineering, Tier3
- **Approval policy:** all roles → auto_approve

#### Runbook 23: `image_lifecycle_audit`
- **Purpose:** Scores Glance private images by: age vs `max_age_days` (default 365),
  EOL OS detection (CentOS 6/7, Ubuntu 14/16, Windows 2008/2012, RHEL 6, Debian 8),
  FIP exposure of running VMs using the image, and orphan status (not used by any VM).
  Risk score 0-100 maps to: low/medium/high/critical.
- **Cross-references:** `GET /servers/detail` for in-use images, `GET /floatingips` for
  FIP exposure, `GET /ports` per server for port-to-FIP mapping.
- **Parameters:** `target_project` (projects_optional), `max_age_days=365`,
  `include_unused=true`.
- **Risk level:** low | **Dry-run:** yes (always read-only) | **Dept:** Engineering, Management
- **Approval policy:** all roles → auto_approve

#### Runbook 24: `hypervisor_maintenance_evacuate` (Phase C2)
- **Purpose:** Drains all VMs from a target compute hypervisor before scheduled maintenance.
  Queries graph for dependency depth to migrate leaf VMs first. Attempts live migration
  per VM; falls back to cold migrate (with graceful stop) on failure.
  Optionally disables `nova-compute` service after a clean drain.
- **Lookup endpoint:** `GET /api/runbooks/lookup/hypervisors` — lists all hypervisors
  with hostname, state, status, vCPU usage, and running VM count.
- **Parameters:** `hypervisor_hostname` (required, x-lookup: hypervisors),
  `migration_strategy=live_first|cold_only|live_only`, `graceful_stop_fallback=true`,
  `disable_host_after_drain=true`, `max_concurrent_migrations=3`.
- **Risk level:** high | **Dry-run:** yes (shows migration plan + order, no changes)
- **Dept:** Engineering only
- **Approval policy:** all roles → single_approval

### Added — Lookup Endpoint
- `GET /api/runbooks/lookup/hypervisors` — returns compute hypervisors list for
  trigger-modal dropdowns (`id`, `hostname`, `state`, `status`, `vcpus_used`, `vcpus`,
  `running_vms`).

---

## [1.56.0] - 2026-03-10

### Added — Phase B3: Action Runbooks — DR Drill + Tenant Offboarding

#### Runbook 19: `disaster_recovery_drill`
- **Purpose:** Clone VMs tagged `dr_candidate` into an ephemeral isolated Neutron network,
  verify each VM boots within the timeout window, then automatically tear down all drill
  resources (DR VMs + network + subnet) — regardless of success or failure.
- **Billing gate:** Pre-checks Nova quota headroom for N additional instances before
  creating any resources. Calls `_call_billing_gate()` if configured.
- **Boot verification:** Polls Nova for `ACTIVE` status per VM within `boot_timeout_minutes`
  (default 10). Records per-VM boot_time_seconds in the drill report.
- **Teardown:** Always runs after the drill (sequential: delete DR VMs → wait for 404 →
  delete subnet → delete network). Skippable on failure via `skip_teardown_on_failure=true`
  for post-failure debugging.
- **Activity log:** Writes a `dr_drill` entry to `activity_log` with VM counts and teardown status.
- **Parameters:** `target_project` (projects_optional), `server_ids` (vms_multi),
  `tag_filter=dr_candidate`, `boot_timeout_minutes=10`, `max_vms=10`,
  `network_cidr=192.168.99.0/24`, `skip_teardown_on_failure=false`.
- **Risk level:** medium | **Dry-run:** yes (shows candidates + quota, creates nothing)
- **Dept visibility:** Engineering only
- **Approval policy:** all roles → single_approval

#### Runbook 20: `tenant_offboarding`
- **Purpose:** Full customer exit workflow — 10 sequential steps with safety confirmation.
  Requires `confirm_project_name` to exactly match the real Keystone project name;
  any mismatch returns HTTP 400 immediately (prevents accidental offboarding).
- **Steps:**
  1. Verify `confirm_project_name` matches Keystone — abort if mismatch
  2. Run `org_usage_report` sub-engine for final report
  3. Release all floating IPs from project
  4. Stop all running VMs gracefully (`os-stop`)
  5. Delete all unattached ports
  6. Disable project in Keystone (`PATCH /projects/{id}` `{enabled: false}`)
  7. Tag all VMs with `offboarding_date` + `retention_until` metadata
  8. Call CRM integration via `_call_billing_gate()` if configured
  9. Email final usage report HTML to `customer_email` via `smtp_helper`
  10. Log change-request ticket stub (skipped until T1 ticket system is live)
- **Activity log:** Writes detailed `tenant_offboarding` entry.
- **Risk level:** critical | **Dry-run:** yes (full plan preview, no changes)
- **Dept visibility:** Management (trigger), Engineering (approve + execute)
- **Approval policy:** all roles → single_approval (superadmin approval required in practice)

#### DB Changes
- `db/migrate_runbooks_dept_visibility.sql` — section 3e: two new runbook INSERTs,
  six new approval policy rows, dept visibility seeds for Engineering/Management.
- `db/init.sql` — same changes for fresh-install parity.

## [1.55.0] - 2026-03-10

### Added — Phase B2: Action Runbooks — VM Rightsizing + Capacity Forecast

#### Runbook 17: `vm_rightsizing`
- **Purpose:** Identifies over-provisioned VMs by analysing `metering_resources` CPU/RAM
  usage over a configurable window (default 14 days), then suggests — or automatically
  executes — a downsize to a cheaper Nova flavor.
- **Analysis:** Computes average and peak CPU % + RAM % per VM; applies a 25 % vCPU safety
  headroom and 50 % RAM headroom over peak actual usage; skips VMs that are already at minimum
  safe size.
- **Flavor selection:** Iterates the full Nova flavor catalog (including private flavors),
  prices each via `metering_pricing.category='flavor'` (falling back to per-vCPU + per-GB-RAM
  formula), and selects the cheapest option that satisfies headroom requirements without
  upsizing both dimensions simultaneously.
- **Dry-run:** Returns `candidates[]` with current/suggested flavor, savings_per_month,
  peak_cpu_pct, peak_ram_mb, data_points; and `skipped[]` with skip reason. No Nova changes.
- **Execute mode:** Pre-snapshot (if `require_snapshot_first=true`) → stop → resize →
  confirmResize → start. Full API progress written to `result.execution[]`.
- **Parameters:** `target_project` (projects_optional), `server_ids` (vms_multi), 
  `analysis_days=14`, `cpu_idle_pct=15`, `ram_idle_pct=30`, `min_savings_per_month=5`,
  `require_snapshot_first=true`.
- **Risk level:** high | **Dry-run:** yes | **Dept visibility:** Engineering, Tier3, Management
- **Approval policy:** operator → single_approval; admin → single_approval; superadmin → auto_approve

#### Runbook 18: `capacity_forecast`
- **Purpose:** Reads `hypervisors_history` to trend weekly aggregate vCPU + RAM usage across
  the entire cluster, performs numpy-free linear regression, and projects days until 80 % 
  capacity is reached (configurable via `capacity_warn_pct`).
- **Output:** `trend[]` (weekly data points), `capacity{}` (totals), `current_utilisation{}`,
  `forecast{}` (days_to_vcpu_warn, days_to_ram_warn), `alerts[]` (populated when breach is
  within `warn_days_threshold`), optional ticket stub logging.
- **Graceful degradation:** Returns `"insufficient_data"` status with ≤1 data week; requires
  ≥3 unique weeks for regression to be meaningful.
- **Risk level:** low | **Read-only:** yes | **Dept visibility:** Engineering, Tier3, Management
- **Approval policy:** auto_approve for all roles

#### UI Enhancement: `vms_multi` multi-select lookup
- `RunbooksTab.tsx` now renders `x-lookup: vms_multi` schema fields as a `<select multiple>`
  control, enabling users to scope a rightsizing run to specific VMs.
- Lookup type normalisation strips both `_optional` and `_multi` suffixes before calling
  `/lookup/{type}` so existing infrastructure is reused without extra API routes.

#### Bug Fix: `ram_usage_mb` is allocated, not actual
- `metering_resources.ram_usage_mb` stores the allocated RAM (equals `ram_allocated_mb`),
  not actual used RAM. The `vm_rightsizing` engine was using `MAX(ram_usage_mb)` as peak RAM,
  which inflated the minimum required RAM to `allocated × 1.5` — making downsizing impossible
  for any VM. Fixed to use `MAX(ram_usage_percent) × ram_allocated_mb / 100` for actual peak RAM.

#### DB Changes
- `db/migrate_runbooks_dept_visibility.sql` — section 3d: two new runbook INSERTs, six new
  approval policy rows, visibility seeds for Engineering/Tier3/Management (fully idempotent).
- `db/init.sql` — same changes for fresh-install parity.

## [1.53.0] - 2026-03-10

### Added — Phase B1: Action Runbooks — Quota Adjustment + Org Usage Report

#### Runbook 15: `quota_adjustment`
- **Purpose:** Operators/TierX actually SET quota for a project. Core building block for
  the ticket system's quota-increase workflow.
- **Scope:** Nova (vCPUs, RAM, instances), Neutron (networks), Cinder (volumes, gigabytes)
- **Dry-run support:** Returns a before/after diff and cost estimate without making any API calls.
- **Billing gate integration:** When `require_billing_approval=true` and a `billing_gate`
  integration is configured, calls `_call_billing_gate()` before applying changes. If the gate
  rejects, the engine returns `{billing_rejected: true, reason}` and stops. If no integration is
  configured the gate is silently skipped.
- **Audit log:** Every actual run writes to `activity_log` with full before/after diff,
  `charge_id`, reason, actor, and project name.
- **Risk level:** high | **Dry-run:** yes | **Dept visibility:** Tier2, Tier3, Engineering, Management
- **Approval policy:** operator → single_approval; admin/superadmin → auto_approve

#### Runbook 16: `org_usage_report`
- **Purpose:** Complete read-only usage + cost report for a single org/project, formatted
  ready to email directly to the customer.
- **Scope:** Nova quota+usage (cores, RAM, instances), per-server breakdown (active/stopped),
  Neutron quota (network, floatingip, router, port, security_group), Cinder quota+usage
  (volumes, gigabytes, snapshots), floating IP list, snapshot list.
- **Cost estimate:** Driven by `_load_metering_pricing()` — computes compute, block storage,
  snapshot, and floating IP costs for the configured `period_days`.
- **Pre-rendered HTML body:** `result.html_body` — full HTML table with utilisation bars
  suitable for email. Planned integration with `email-customer` endpoint (ticket workflow).
- **Risk level:** low | **Read-only:** yes | **Dept visibility:** Sales, Tier2, Tier3, Engineering, Management
- **Approval policy:** auto_approve for all roles

#### Bug Fixes
- **`trigger_runbook` role detection** — `current_user` is a `dict` (returned by
  `require_permission()`); was using `hasattr(user, "role")` which always returned False for
  dicts, causing all trigger requests to default to the `operator` approval policy regardless
  of the authenticated user's actual role. Fixed with dict-safe lookup.

#### DB Changes
- `db/migrate_runbooks_dept_visibility.sql` — two new `INSERT INTO runbooks` rows, six new
  approval policy rows, and nine new visibility seed rows appended (fully idempotent).
- `db/init.sql` — same changes to keep fresh-install schema in sync.

## [1.52.0] - 2026-03-10

### Added — Phase A: Runbook Department Visibility + External Integrations Framework

#### Runbook Department Visibility
- **Server-side dept filter on `GET /api/runbooks`** — non-admin users now receive only the
  runbooks their department is allowed to see. Superadmin/admin bypass the filter and see all.
- **New `runbook_dept_visibility` table** — join table `(runbook_name, dept_id)` controlling
  which departments can see each runbook. Absence of rows = visible to all depts.
- **Seed data** — all 14 existing runbooks pre-seeded with correct dept mappings (Engineering,
  Tier1–3 Support, Sales, Management as appropriate per runbook sensitivity).
- **Admin visibility grid in RunbooksTab** — new collapsible "Runbook Dept Visibility" section
  (admin/superadmin only) with a live checkbox matrix. Toggling and saving updates visibility
  per runbook instantly via `PUT /api/runbooks/visibility/{name}`.
- **New API endpoints:**
  - `GET /api/runbooks/visibility` — full visibility matrix (admin+)
  - `PUT /api/runbooks/visibility/{runbook_name}` — replace dept list for a runbook (admin+)

#### External Integrations Framework
- **New `external_integrations` table** — stores billing gate, CRM, and generic webhook
  integrations. `auth_credential` is Fernet-encrypted at rest (key = SHA-256 of `JWT_SECRET`).
- **New `api/integration_routes.py`** — full CRUD + test API:
  - `GET /api/integrations` — list (admin+)
  - `GET /api/integrations/{name}` — get one (admin+)
  - `POST /api/integrations` — create (superadmin)
  - `PUT /api/integrations/{name}` — update (superadmin)
  - `DELETE /api/integrations/{name}` — delete (superadmin)
  - `POST /api/integrations/{name}/test` — fire test request, persist `last_test_status`
- **`_call_billing_gate()` helper in `runbook_routes.py`** — shared utility for upcoming
  action runbooks to pre-authorize quota changes; returns `{skipped: True}` if no active
  billing integration is configured (never blocks on missing optional config).
- **Integrations admin panel in RunbooksTab** — new collapsible "External Integrations" section
  (admin/superadmin) with table of integrations, per-row 🧪 Test button, and create/edit/delete
  form for superadmin.

#### DB Migrations
- `db/migrate_runbooks_dept_visibility.sql` — idempotent migration for existing installs
- `db/init.sql` — both tables + seeds added at bottom for fresh installs

### [1.51.0] - 2026-03-10

### Added — Graph: Health Scores, Orphan Detection, Blast Radius & Delete Safety

Major enhancement of the Dependency Graph drawer (accessible via **🕸 View Dependencies** on
any resource row in the Servers, Volumes, Networks, Snapshots, and Projects tabs).

#### `api/graph_routes.py`

**Three-state snapshot coverage** — per-node `snapshot_coverage` field replaces the old binary
`no_snapshot` badge with three states: `protected` (latest snapshot < 7 days), `stale`
(latest snapshot ≥ 7 days old), or `missing` (no snapshot exists). Corresponding badges
`snapshot_protected`, `snapshot_stale`, `snapshot_missing` replace the old `no_snapshot` badge.

**Orphan detection** — graph summary now reports orphaned resources that are wasting capacity:
- Volumes with `status='available'` and no attached VM
- Floating IPs with no `port_id`
- Security groups not referenced by any port and not named 'default'
- Snapshots whose parent volume no longer exists

**Health Score engine** — every node now carries a `health_score` (0–100):
- VM: deductions for `error_state` (−30), `power_off` (−10), `snapshot_missing` (−15),
  `snapshot_stale` (−8), `drift` (−15)
- Volume: deductions for `error_state` (−30), orphan (−5), `snapshot_missing` (−20),
  `snapshot_stale` (−10)
- Host: deductions for CPU >80 % (−20), CPU >60 % (−8), RAM >80 % (−20), RAM >60 % (−8)

**Capacity pressure** (`healthy` / `warning` / `critical`) derived from host CPU and RAM utilisation.

**Graph-level summary** — `graph_health_score`, `tenant_summary` (critical / degraded / snapshot-missing / drift VM counts), `top_issues` list, and full `orphan_summary` returned alongside nodes/edges.

**Blast Radius mode** (`?mode=blast_radius`) — BFS following outgoing "serves" edges from the
root node; returns `blast_radius.impact_node_ids` and a summary (`vms_impacted`, `tenants_impacted`,
`floating_ips_stranded`, `volumes_at_risk`).

**Delete Impact mode** (`?mode=delete_impact`) — resource-type-aware cascade/stranded analysis:
- Network: subnets/ports cascade; VMs with no other network become stranded
- Volume: snapshots cascade
- Tenant: all owned resources cascade (always reported as unsafe)
- VM: FIPs become stranded; volumes are detached (not deleted) so they appear as orphans
- Security Group: blocked by OpenStack if any VM is using it (reported as a `blocker`)

Returns `delete_impact.safe_to_delete`, `blockers`, `cascade_node_ids`, `stranded_node_ids`, and a summary.

#### `pf9-ui/src/components/graph/DependencyGraph.tsx`

**Mode toggle toolbar** — three-way pill (Topology / 💥 Blast Radius / 🗑 Delete Impact) added
to the graph toolbar. Active blast/delete mode is highlighted with a dark-red accent.

**Health score circles** — small coloured badge (green ≥ 80, amber ≥ 60, red < 60) shown on
each node in the top-right corner.

**Capacity pressure tinting** — host/hypervisor nodes are tinted green / amber / red based on
their `capacity_pressure` value.

**Node dimming in Blast Radius mode** — nodes outside the impact path are dimmed to 35 % opacity;
nodes in the blast path are highlighted in red; edges on the impact path are animated.

**Delete Impact overlays** — cascade nodes highlighted in orange, stranded nodes in purple;
non-affected nodes dimmed. FIP stranding edge shown with dashed animated stroke.

**Summary panels** — two inline panels rendered between toolbar and graph canvas:
- *Blast Radius*: red banner listing impacted VMs, tenants, FIPs, and volumes-at-risk
- *Delete Impact*: green "Safe to delete" or dark-red warning with blockers, cascade count,
  and stranded VM/FIP counts

**Tenant Health Panel** — shown above the canvas in Topology mode; displays overall environment
health score, critical/degraded VM counts, orphan counts, and an expandable top-issues list.

**Enhanced sidebar** — right-click/select a node to see:
- Health Score with coloured badge
- Snapshot Coverage (✅ Protected / ⚠️ Stale / ❌ None)
- Capacity (for hosts): coloured healthy/warning/critical ring
- Suggested quick-action buttons when `health_score < 60`:
  `📸 Create Snapshot` (volume with missing/stale snapshot), `🔍 View Drift Events` (drift badge),
  `📋 View Logs` (error_state badge)

---

## [1.50.0] - 2026-03-10

### Security — Hardening & Code Quality (Phase J)

Addressed outstanding security findings from the Phase J internal audit. No new features;
all changes are security fixes or code-quality improvements with no user-visible behaviour
changes.

#### `api/auth.py`
- **Timing-safe admin password check** — `password == DEFAULT_ADMIN_PASSWORD` replaced with
  `hmac.compare_digest()` to eliminate timing-oracle vulnerability on the local admin fallback path.
- **LDAP connection leak fixed** — `get_user_info()` now unconditionally calls `conn.unbind_s()`
  in a `try/finally` block; previously the connection was only closed on the exception path, leaking
  one LDAP handle per successful authentication.
- **`print()` removed** — `initialize_default_admin()` used bare `print()` for startup diagnostics;
  replaced with `logger.info` / `logger.error`.

#### `api/log_collector.py`
- **Command injection patched** — `get_log_range()` interpolated the caller-supplied `start_time`
  value directly into an SSH `grep` command via an f-string. Now validates the value against a
  strict `YYYY-MM-DD` regex before use and wraps it with `shlex.quote()`.
- **Null `log_path` guard** — added early return when `log_path` is `None` before issuing the
  SSH command.
- **`print()` removed** — four bare `print()` calls (startup, connect success/failure) replaced
  with `logger.debug` / `logger.error`.

#### `api/vm_provisioning_routes.py`
- **Removed `_db()` / `_release()` helpers** — private wrapper functions that obscured the
  connection lifecycle were removed; `_execute_batch_thread()` now calls `get_pool().getconn()`
  and `get_pool().putconn()` directly in a `try/finally` block, consistent with the `db_pool`
  context-manager pattern used everywhere else.

#### `api/graph_routes.py`
- **Host node graph fix** — `_is_valid_id()` rejected integer IDs (e.g. `root_id=8`) because
  the fallback regex required a minimum of 4 characters. Added an explicit `^\d+$` branch so
  `hypervisors.id` integer PKs pass validation; `GET /api/graph?root_type=host&root_id=<n>`
  now returns 200 instead of 400.

#### `api/main.py`
- **Host Disk % always 0% fixed (VM inventory + Hypervisors tab)** — Nova's `local_gb_used`
  is 0 for all PF9 hosts because instances are volume-backed (Cinder) and Nova never allocates
  ephemeral disk. Three query sites were affected: the server list CTE (`host_disk_used_gb`),
  the monitoring host-metrics query (`storage_used_gb` / `storage_usage_percent`), and the
  `GET /hypervisors` endpoint (`local_gb_used`). All three now derive used disk from
  `local_gb - disk_available_least` (the actual remaining headroom reported by the hypervisor
  agent), falling back to `local_gb_used` only when `disk_available_least` is absent. Disk
  values now show realistic numbers (e.g. 34 GB / 35%, 81 GB / 84%, 25 GB / 26%) instead of 0.

---

## [1.49.0] - 2026-03-09

### Fixed — Drift Detection: Enriched Event Context (UUIDs → Friendly Names)

Addressed the core usability problem where drift events displayed raw UUIDs with no
context — making it impossible to identify which VM, tenant, or resource was affected
without cross-referencing elsewhere.

#### Backend: `api/main.py`
- **`GET /drift/events`** and **`GET /drift/events/{event_id}`** — SQL rewritten to resolve
  friendly names at query time:
  - `resource_name`: live-looks up the actual name from `servers`, `volumes`, `networks`,
    or `snapshots` when the stored value is NULL or an empty string (common for unnamed volumes);
    falls back to UUID only when no name exists anywhere.
  - `project_name` / `domain_name`: JOINed from `projects` / `domains` tables — events
    now always carry tenant name even when the inventory sync did not include it at write time.
  - `old_value_label` / `new_value_label` (new response fields): resolves UUID reference
    fields to friendly names — `server_id` → VM name, `flavor_id` → flavor name,
    `network_id` → network name, `image_id` → image name. Raw UUID still returned for
    copy/reference.
  - `NULLIF(..., '')` wrapping on all CASE name lookups so empty-string names correctly
    fall through to the UUID fallback (root cause: unnamed volumes have `name = ''` in DB,
    not NULL).

#### Backend: `notifications/main.py`
- `collect_drift_events()` SQL updated with identical enrichment — resolved resource name,
  tenant/domain JOIN, `old_value_label` / `new_value_label` lookups, `NULLIF` guards.
- `summary` string now includes tenant name:
  `"Drift detected on volumes 'vol-name' (tenant: service): server_id changed"`.
- Notification payload `old_value` / `new_value` carry the friendly name; original UUID
  preserved in `old_value_raw` / `new_value_raw`.

#### Email template: `notifications/templates/drift_alert.html`
- **Tenant / Project** row moved above Field Changed and always rendered.
- **Domain** row added (was previously missing entirely).
- **Resource Name** shows friendly name with UUID dimmed below when they differ.
- **Change row** shows resolved name with raw UUID as small subtext.

#### Frontend: `pf9-ui/src/components/DriftDetection.tsx`
- `DriftEvent` interface extended with `old_value_label` and `new_value_label` fields.
- **Detail panel**: Resource row shows `(unnamed) <UUID>` for volumes with no assigned name,
  or name + UUID dimmed below when a name exists. Tenant / Project (renamed from "Project")
  and Domain rows always shown when IDs are present (were silently hidden when names were NULL).
  Old/New Value rows display the resolved friendly name with raw UUID as subtext.
- **List table**: Change column uses resolved label; Name column tooltip shows both
  name and UUID.
- **CSV export**: adds "Tenant / Project" and "Domain" columns; old/new value columns
  include resolved name with UUID in parentheses.

---

## [1.48.0] - 2026-03-09

### Added — Cloud Dependency Graph: VMware-Side Migration Graph (Phase 4)

> Phase 4 was redesigned from a PCD overlay to a VMware-side graph built from RVTools import data,
> since VMs don't exist on PCD yet during the planning phase.

#### New endpoint: `api/migration_routes.py`
- **`GET /api/migration/projects/{project_id}/graph?tenant_id=`** — builds a dependency graph
  from RVTools import data (`migration_vms`, `migration_vm_nics`, `migration_vm_disks`,
  `migration_networks`, `migration_tenants`) — not from OpenStack/PCD.
- Returns `{ root, nodes, edges, truncated }` in the same format as `/api/graph`.
- **Node types**: `tenant` (Org-vDC root), `vm`, `network` (portgroup/VLAN), `disk`, cross-tenant `tenant`.
- **VM nodes** include multi-line status: IP · migration status / vCPU · RAM / CPU% · MEM% usage.
- **Disk nodes** include: allocated GB · used GB (%) / thin|thick · datastore.
- **Migration overlay** on VM nodes: `complete` → confirmed (green), `in_progress/validating/pre_checks_passed` → pending (amber), `failed/cancelled` → missing (red), `not_started` → no ring.
- **Cross-tenant nodes**: other tenants sharing the same portgroup appear as extra tenant nodes hanging off network nodes; edge label shows VM count.
- **150-node hard cap** — sets `truncated: true` when hit.

#### Modified: `pf9-ui/src/components/graph/DependencyGraph.tsx`
- **New prop**: `graphUrl?: string` — when set, fetches that URL directly instead of `/api/graph`; bypasses all PCD graph logic.
- Node subtitle div now uses `whiteSpace: pre-wrap` + `lineHeight: 1.4` to render multi-line status fields.
- Depth pills hidden when `graphUrl` is set.
- "Explore from here" button hidden when `graphUrl` is set.
- All three action buttons (`Open in tab`, `Create Snapshot`, `View in Migration Planner`) suppressed when `graphUrl` is set — PCD resource IDs don't exist during planning.
- **Migration legend** shown when either `migrationProjectId != null` OR `graphUrl != null`; labels remapped for VMware context: confirmed → "complete", pending → "in progress", missing → "failed".
- Added `disk` node type: color `#d97706` (amber), icon 🖴, included in `ALL_NODE_TYPES`.

#### Modified: `pf9-ui/src/App.tsx`
- `graphTarget` type extended: `graphUrl?: string`.
- **`handleViewMigrationGraph(label, graphUrl)`** — simplified; sets `graphTarget` directly with the migration graph URL; no OpenStack project lookup needed.
- `<DependencyGraph graphUrl={graphTarget.graphUrl} />` passed through.

#### Modified: `pf9-ui/src/components/MigrationPlannerTab.tsx`
- `onViewTenantGraph` prop signature simplified to `(label: string, graphUrl: string) => void`.

#### Modified: `pf9-ui/src/components/migration/SourceAnalysis.tsx`
- `onViewTenantGraph` signature updated to match.
- **`TenantsView`**: 🕸️ button calls `onViewTenantGraph(t.tenant_name, '/api/migration/projects/${projectId}/graph?tenant_id=${t.id}')`.
- **`CohortsView`**: same pattern for tenant rows inside expanded cohorts.

---

### Added — Cloud Dependency Graph: Node Actions (Phase 3)

#### Modified: `pf9-ui/src/components/graph/DependencyGraph.tsx`
- **Node action buttons** added to the existing node detail sidebar (visible on click):
  - **"🔗 Open in {tab} tab"** — navigates to the resource's native tab (Servers, Volumes, Snapshots, Networks, Subnets, Ports, Floating IPs, Security Groups, Projects, Hypervisors, Images, Domains) and pre-selects that exact resource; closes the graph drawer automatically.
  - **"📸 Create Snapshot"** (volume nodes only) — navigates to the Snapshots tab and shows a guided prompt directing the user to the Create Snapshot button.
  - **"🚀 View in Migration Planner"** (VM and tenant nodes only) — navigates directly to the Migration Planner tab.
- New optional props: `onNavigate?: (tab, resourceId, resourceType) => void` and `onCreateSnapshot?: (volumeId, volumeName) => void` — both passed from App.tsx; buttons are hidden when the callbacks are not provided.
- `NODE_TYPE_TO_TAB` map (12 entries) converts node type strings to `ActiveTab` IDs.

#### Modified: `pf9-ui/src/App.tsx`
- `handleGraphNavigate` callback: switches tab via `setActiveTab`, looks up the full resource object in already-loaded in-memory arrays (`servers`, `volumes`, `snapshots`, `networks`, `images`, `hypervisors`, `projects`) and calls the matching `setSelected*` setter so the detail panel opens automatically; then closes the graph drawer.
- `handleGraphCreateSnapshot` callback: navigates to Snapshots tab, closes drawer, and shows an `alert()` after 200 ms guiding the user.
- Both callbacks passed to `<DependencyGraph onNavigate={...} onCreateSnapshot={...} />`.

---

### Added — Cloud Dependency Graph: Backend API + UI Panel (Phase 1 & 2)

#### New file: `api/graph_routes.py`
- **`GET /api/graph`** — BFS dependency graph builder starting from any supported resource type (`vm`, `volume`, `network`, `tenant`, `snapshot`, `security_group`, `floating_ip`, `subnet`, `port`, `host`, `image`, `domain`).
- **Query params**: `root_type` (required), `root_id` (required), `depth` 1–3 (default 2), `domain` (optional domain-filter).
- **12 node types** fully supported with per-type DB fetchers and expansion logic.
- **15 edge traversals** including the tricky VM→SecurityGroup path (reads `ports.raw_json->'security_groups'` JSONB array — no join table needed).
- **Badge computation** on every node — `no_snapshot` (volumes with no snapshots), `drift` (unacknowledged drift events), `error_state` (status=ERROR), `power_off` (VM SHUTOFF), `restore_source` (snapshot used as a restore point).
- **150-node hard cap** — BFS stops and sets `truncated: true` to prevent hairball graphs.
- **Domain filter** — optional `domain` query param restricts tenant/project expansion to a specific domain; useful for MSP multi-tenant environments.
- **Registered** in `api/main.py` via `app.include_router(graph_router)`.
- **RBAC**: `resources:read` (Viewer and above).
- **Tested**: `depth=2` from a real VM returns 24 nodes and 38 edges.

#### New file: `pf9-ui/src/components/graph/DependencyGraph.tsx`
- Full-screen drawer panel built on **ReactFlow** with **dagre** hierarchical (`TB`) auto-layout.
- **12 color-coded node types** — each with a distinct color, emoji icon, subtype label and status line.
- **Badge strips** on nodes for `drift`, `no_snapshot`, `error_state`, `power_off`, `restore_source`.
- **Depth pills** (1 / 2 / 3) — change depth and re-fetch live.
- **Type filter checkboxes** — hide/show any of the 12 node types; `port` and `subnet` hidden by default to reduce noise.
- **Node detail sidebar** — click any node to see Type, Status, full UUID, and badges. Sidebar has a forced dark background so values are always readable regardless of app theme.
- **🔍 Explore from here** — click any non-root node's "Explore from here" button to re-root the graph at that node (e.g. click a Network to see all its subnets, VMs, tenants).
- **← Back navigation** — breadcrumb history stack; Back button appears when you have drilled down.
- **Mobile fallback** — viewport < 768 px shows a plain table list instead of the canvas.
- **Truncation warning** — banner shown when the 150-node cap is hit.

#### Modified: `pf9-ui/src/App.tsx`
- **"🕸️ View Dependencies"** button added to the detail panels of: Servers, Snapshots, Networks, Volumes.
- `graphTarget` state drives the full-screen graph drawer overlay rendered at the bottom of the component tree.
- Import of `DependencyGraph` + `GraphRootType` type.

#### New file: `pf9-ui/src/vite-env.d.ts`
- TypeScript `declare module` stubs for `reactflow/dist/style.css` and `reactflow/dist/base.css` — satisfies `noUncheckedSideEffectImports` without disabling the rule.

#### Modified: `pf9-ui/src/App.css`
- Graph drawer styles: `.graph-drawer-backdrop`, `.graph-drawer`, `.graph-drawer-header`, `.graph-controls-bar`, `.graph-pill`, `.graph-pill-active`, `.graph-action-btn`, `.graph-type-chip`, `.graph-node-sidebar`, `.graph-view-deps-btn`, overlay loading/error states.

---

## [1.46.0] - 2026-03-10

### Added — Migration Planner Phase 4D: vJailbreak Push + Users UX Overhaul

#### DB Migration (`db/migrate_phase4d.sql`)
- **`migration_projects` table** — three new columns: `vjb_api_url TEXT`, `vjb_namespace TEXT DEFAULT 'migration'`, `vjb_bearer_token TEXT` for per-project vJailbreak Kubernetes CRD API config.
- **`migration_vjailbreak_push_tasks` table** — task log for each CRD push operation: `project_id`, `cohort_id`, `tenant_name`, `resource_type`, `resource_name`, `status` (pending/done/skipped/failed), `error_message`, `pushed_by`, `pushed_at`.

#### Backend API (`api/migration_routes.py`)
- **`POST /projects/{id}/tenant-users/seed-tenant-owners`** — bulk-seeds one `tenant_owner` record per tenant (`admin@<domain_slug>` using `target_domain_name` if set, else `tenant_name`); skips tenants that already have a `tenant_owner` row.
- **`POST /projects/{id}/tenant-users/confirm-all`** — marks all unconfirmed user rows as `confirmed=true`; returns `{updated: N}`.
- **`POST /projects/{id}/tenant-users/bulk-replace`** — find-and-replace on `username`, `email`, or `role` fields across all tenant users for a project; supports `preview: true` (dry-run returns match count + sample diffs without writing).
- **`POST /projects/{id}/tenant-users/bulk-action`** — mass `confirm`, `set_role`, or `delete` on a list of `user_ids`; delete restricted to `tenant_owner` type.
- **`GET /PATCH /projects/{id}/vjailbreak-push-settings`** — read/update `vjb_api_url`, `vjb_namespace`, `vjb_bearer_token` per project; token masked in GET response.
- **`POST /projects/{id}/vjailbreak-push/dry-run`** — connects to vJailbreak K8s CRD API (Bearer token), lists existing `openstackcreds`/`networkmappings`/`vmwarecreds` CRDs, returns `{would_create, would_skip_existing, openstackcreds[], networkmappings[], vmwarecreds?}` — no writes.
- **`POST /projects/{id}/vjailbreak-push`** — idempotent push: creates `openstackcreds` CRD per tenant (skips by name if already exists), one `networkmappings` CRD for the project, optional `vmwarecreds` CRD (vCenter password accepted in request body and **never** stored to DB); logs each resource to `migration_vjailbreak_push_tasks`.
- **`GET /projects/{id}/vjailbreak-push-tasks`** — task log with done/skipped/failed summary counts.
- **`DELETE /projects/{id}/vjailbreak-push-tasks`** — clears task log (does NOT touch vJailbreak).
- **Internal helpers**: `_k8s_name()` slugifier, `_vjb_k8s_request()` Bearer-token HTTP client, `_build_openstackcreds_crd()`, `_build_networkmapping_crd()`, `_build_vmwarecreds_crd()`.

#### Frontend UI (`pf9-ui/src/components/migration/SourceAnalysis.tsx`)
- **`TenantUsersView` overhaul**:
  - Filter bar: type (all / service_account / tenant_owner), status (all / confirmed / pending), role (all/admin/member/reader), search across username/email/tenant name; "Clear" resets all filters.
  - Bulk Find & Replace panel: field selector (username/email/role), find/replace text, case-sensitive toggle, preview mode, apply button — calls `/bulk-replace` API.
  - Checkbox column + bulk action toolbar: select individual rows or select-all; bulk confirm, set-role (with inline dropdown), delete — calls `/bulk-action` API.
  - **"👤 Seed Tenant Owners"** button — calls `/seed-tenant-owners` to batch-create `admin@<domain>` owner for every tenant in one click.
  - **"✓ Confirm All"** button — calls `/confirm-all` to confirm all rows at once.
  - "Add Owner" form upgraded: tenant-name dropdown auto-fills `username` as `admin@<domain>` on selection (instead of raw numeric Tenant ID input).
  - Parallel fetch of users + tenants on mount for the dropdown.
  - Inline per-row ✓ (confirm) and ✏️ (edit) actions preserved.
- **`VJailbreakPushView` (new component)**: collapsible ⚙️ Connection Settings panel (URL/namespace/token save), collapsible 🖥️ VMware Credentials panel (not persisted), 🔍 Dry Run button + results preview (tables of would_create vs would_skip), 🚀 Push button with confirmation dialog + result summary, 📋 Push Task Log table with per-status pill badges, refresh, and clear.
- **`"vjb"` sub-tab** added to sub-nav ("🚀 vJailbreak Push") and `SubView` union type, wired to `VJailbreakPushView`.

#### Configuration
- **`.env.example`** — added `VJB_API_URL`, `VJB_NAMESPACE`, `VJB_BEARER_TOKEN` documentation block.
- **`deployment.ps1`** — added `migrate_phase4d.sql` to provisioning migration sequence.

---

## [1.45.5] - 2026-03-08

### Fixed

- **`pf9_rvtools.py` — DB connection error on host**: PostgreSQL port 5432 was not exposed from Docker to the host, causing `psycopg2.OperationalError` on every run (with noisy multi-line traceback). Exposed port `5432:5432` in `docker-compose.yml` and removed spurious `traceback.print_exc()` from the graceful-failure handler so the error message is clean if the DB is ever unreachable.

## [1.45.4] - 2026-03-09

### Fixed

- **VM Provisioning — auto-refresh (live progress)**: `loadBatchLogs` was calling `.json()` on the already-parsed return value of `apiFetch<T>`, causing a silent `TypeError` that was caught by the surrounding `catch {}`. Logs never updated during execution. Fixed by removing the erroneous `.json()` call (`apiFetch` already returns parsed JSON).
- **VM Provisioning — polling killed itself on every update**: The polling `useEffect` listed `batches` in its dependency array; every time `fetchBatches()` ran and updated state, the cleanup function fired and killed the interval, which was then re-created with a stale closure over the old `batches`/`expandedIds`. Rewrote to use `batchesRef`/`expandedIdsRef` refs so the interval is created once on mount and always reads the latest state.
- **VM Provisioning — completion emails never sent**: `execute_batch` and `re_execute_batch` hardcoded `operator_email = None`, so the perfectly-functional email logic in `_execute_batch_thread` was never triggered. Both endpoints now look up the operator's email via `ldap_auth.get_user_info(user.username)` and pass it to the background thread.

### Added

- **VM Provisioning History in Runbooks tab**: Added a collapsible **"☁️ VM Provisioning History"** section to the `RunbooksTab` main page, directly below "My Executions". Shows a live table of all provisioning batches (ID, name, domain/project, status badge, approval status, created-by, date) with a one-click **"▶ Open Provisioning"** button. Loads automatically on page mount and has a manual 🔄 refresh. Surfaces provisioning history without requiring navigation into the full Provisioning runbook.
- **VM Provisioning — in-app notification bell**: `_execute_batch_thread` now calls `_fire_notification` from `provisioning_routes` on completion/failure, firing a `vm_provisioning_completed` or `vm_provisioning_failed` event to all users who have subscribed to those event types in the Notification Preferences panel. This is independent of the operator email and works for any admin who wants to monitor all provisioning activity.

## [1.45.3] - 2026-03-08

### Added

- VM auto-provisioning runbook: per-VM **"Delete boot volume on VM deletion"** toggle (`delete_on_termination`). Each VM row now has a checkbox (default: checked / true) that controls whether the attached boot volume is automatically deleted when the VM is destroyed in Nova. Previously this was always hardcoded to `true`.
  - `api/pf9_control.py`: `create_server_bfv()` accepts new `delete_on_termination: bool = True` parameter passed through to Cinder `block_device_mapping_v2`
  - `api/vm_provisioning_routes.py`: `VmRowRequest` model gains `delete_on_termination: bool = True`; DB schema adds `delete_on_termination BOOLEAN NOT NULL DEFAULT TRUE`; Excel template and upload parser both support the new column; `create_server_bfv` call forwards the value
  - `pf9-ui/src/components/VmProvisioningTab.tsx`: `VmRow` interface, `newVmRow()`, payload builder, and per-VM form all updated; checkbox renders below the Boot Volume (GB) field

## [1.45.2] - 2026-03-08

### Fixed

- `api/main.py`: raised `project-quotas` endpoint `page_size` cap from 500 to 5000 so all quota rows can be fetched in a single pass
- `pf9-ui/src/App.tsx`: Quotas tab now fetches all pages of `/project-quotas` (parallel requests) so all projects appear instead of only the first ~17

## [1.45.1] - 2026-03-08

### Fixed

- `api/auth.py`: replaced `print()` calls with structured `logger` calls so JWT warnings appear in the structured log pipeline instead of stdout
- `api/cache.py`: replaced bare `pass` in exception handlers with `logger.warning(...)` so cache misses and serialisation errors are observable

### Added

- `docker-compose.prod.yml`: production overrides file — PostgreSQL, LDAP, and Redis ports not bound to host; API runs 4 Gunicorn workers with `--max-requests` recycling; rate-limiter enabled by default; UI built from `Dockerfile.prod` (nginx, not Vite dev server)
- `.env.example`: updated with new env vars added since v1.39.0 (notification worker, VM provisioning service user, backup integrity, SMTP options A/B) and improved inline documentation

### Documentation

- `README.md`: added "What pf9-mngt Is / Is Not" sections; moved System Architecture to top with 14-container table and ASCII diagram; added Feature Status Matrix (16 features); added Project Status section; fixed K8s badge and deployment note; updated footer version to 1.45.0
- `docs/KUBERNETES_MIGRATION_GUIDE.md`: renamed to "Kubernetes Design and Migration Plan"; added prominent ⚠️ "Status: Design Target Only — Not Yet Implemented" warning block at the top
- `docs/DEPLOYMENT_GUIDE.md`: added Deployment Architectures section (Options A single-host, B separate DB, C external LDAP/AD + TLS configuration); added Rollback Procedure; fixed all placeholder `yourusername/pf9-management` URLs; corrected healthcheck claim; updated version to 2.3
- `docs/ADMIN_GUIDE.md`: added 12 task-based operational sections (System Startup, Health, User Admin, Roles, Snapshots, Restore, Migration, Monitoring, Notifications, Backup, Audit, Troubleshooting) + Quick Reference table at the top; moved 641-line release notes block to "Appendix: Feature History by Version"

## [1.45.0] - 2026-03-08

### Features — Phase E

#### E1 — vJailbreak execution backend (`api/migration_routes.py`)
- New `GET /api/migration/projects/{project_id}/vjailbreak-status` — reports whether the vJailbreak agent is configured and reachable. Returns `not_configured`, `connected`, or `unreachable` JSON.
- New `POST /api/migration/projects/{project_id}/waves/{wave_id}/execute` — forwards a wave execution request to the vJailbreak REST API. Returns `503` with a clear human-readable message when `VJAILBREAK_API_URL` is not set. Proxies `dry_run` flag and `notes` to the agent. Always logs an activity entry regardless of agent availability. Admin/superadmin RBAC (inherits `admin` action on `migration` resource).

#### E3 — Slack / Microsoft Teams webhook notifications (`api/webhook_helper.py`, `api/notification_routes.py`)
- New `api/webhook_helper.py` module: reads `SLACK_WEBHOOK_URL` and `TEAMS_WEBHOOK_URL` from environment. Exports `SLACK_ENABLED`, `TEAMS_ENABLED`, `send_slack()`, `send_teams()`, and `post_event()`. Slack uses Block Kit JSON; Teams uses the MessageCard schema.
- New `GET /notifications/webhook-config` — returns `{slack_enabled, teams_enabled, any_enabled}` (no secrets exposed). Requires `notifications:read`.
- New `POST /notifications/test-webhook` — sends a test message to Slack, Teams, or both. Body: `{channel: "slack"|"teams"|"all"}`. Requires `notifications:write`.
- New `db/migrate_webhook_channels.sql` — seeds `slack` and `teams` placeholder rows in `notification_channels` (requires `WHERE NOT EXISTS` guard, idempotent).
- `db/init.sql` updated to seed all three channel types on fresh install.

#### E5 — Backup integrity validation (`backup_worker/main.py`, `db/migrate_backup_integrity.sql`)
- New `integrity_status` (`pending`/`valid`/`invalid`/`skipped`), `integrity_checked_at`, and `integrity_notes` columns added to `backup_history` via `db/migrate_backup_integrity.sql`.
- New `_validate_backup(conn, job_id, filepath)` function: runs `gunzip -t` to verify gzip integrity, then peeks the first 4 KiB and confirms the decompressed content looks like a pg_dump SQL script. Writes result back to `backup_history` and commits.
- Called automatically from `_run_backup()` on every successful backup before the worker yields.

#### E6 — Inventory versioning (`api/main.py`, `db/migrate_inventory_versions.sql`)
- New `inventory_snapshots` table: `id SERIAL`, `collected_at TIMESTAMPTZ`, `snapshot JSONB` (servers, projects, volumes, counts). Index on `collected_at DESC`. 90-day automatic retention.
- Snapshot captured at end of every `refresh_inventory` call.
- New `GET /api/inventory/snapshots` — lists recent snapshots (newest first), `limit` param (1–500, default 50).
- New `GET /api/inventory/diff` — takes `from_ts` / `to_ts` ISO-8601 params, finds nearest snapshots and returns a structured diff (added/removed/changed servers with status/flavor/hypervisor deltas, added/removed projects, added/removed volumes, resource count table).
- `db/migrate_inventory_versions.sql` + `db/init.sql` updated.

#### E7 — Inventory diff in drift detector (`check_drift.py`)
- Extended `check_drift.py` with an `=== INVENTORY CHANGE SUMMARY (last 7 days) ===` section.
- Fetches the most recent snapshot and the nearest snapshot ≥7 days ago. Diffs servers (added/removed/changed with field-level deltas, up to 5 examples each), projects (added/removed), volumes (added/removed), and a resource count table showing before → after with delta.
- Handles edge cases: no snapshots, only one snapshot (prints counts only with a note).



### Technical Debt — Phase D cleanup (`api/`)

#### D1 — Replace `_db()`/`_release()` with connection-pool context manager (`api/vm_provisioning_routes.py`)
- All API route handlers converted from `_db()`/`_release()` manual connection management to `with get_connection() as conn:`. Connections are now returned to the pool automatically even on exception.
- `_ensure_tables()` likewise converted.
- `_execute_batch_thread` (background thread) retains `_db()`/`_release()` intentionally — it holds a single long-lived connection across hundreds of lines of Platform9 API work.
- `dry_run` split into two separate `with get_connection()` blocks (read-only pre-flight, then status-write after Platform9 processing) to free the connection during the long computation window.

#### D2 — Remove deprecated `get_db_connection()` helpers (`api/dashboards.py`, `api/notification_routes.py`)
- Removed local `get_db_connection()` shim functions that pre-dated the connection pool. All DB access now uses `db_pool.get_connection`.

#### D3 — Remove redundant `conn.commit()` inside context-manager blocks
- Removed ~110 redundant `conn.commit()` calls across `mfa_routes.py`, `runbook_routes.py`, `search.py`, `backup_routes.py`, `metering_routes.py`, `main.py`, `migration_routes.py`, and `provisioning_routes.py`. The `db_pool.get_connection()` context manager already commits automatically on clean exit.
- Six `conn.commit()` calls in `vm_provisioning_routes.py` (inside `_log_activity` and `_execute_batch_thread`) are retained — these use manual connection management intentionally.

#### D4 — Fix unbounded `request_duration` memory growth (`api/performance_metrics.py`)
- `request_duration` defaultdict factory changed from `list` → `deque(maxlen=100)`. Removed dead manual guard code. Each endpoint now retains only the last 100 latency samples, preventing unbounded memory growth under sustained load.

#### D5 — Centralise SMTP configuration (`api/smtp_helper.py`)
- New `api/smtp_helper.py` module: single source of truth for all SMTP environment variables (`SMTP_ENABLED`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS`, `SMTP_FROM_NAME`).
- Exports `send_email(to_addrs, subject, html_body, *, raise_on_error=False)` and `send_raw(msg, to_addrs)`.
- Removed duplicate SMTP import blocks and 8-constant env-var patterns from `notification_routes.py`, `provisioning_routes.py`, `vm_provisioning_routes.py`, and `onboarding_routes.py`.

#### D6 — Remove unused Python packages (`api/requirements.txt`)
- Removed `asyncpg==0.29.0` (no async DB driver needed — psycopg2 is used) and `pydantic-settings==2.6.1` (settings loaded via `os.getenv` directly).

#### D7 — Delete stale backup file (`pf9-ui/src/components/`)
- Deleted `MeteringTab.tsx.bak`. `.gitignore` already covers `*.bak`.

#### D9 — Token-bucket rate limiter for Platform9 API calls (`api/pf9_control.py`)
- Added thread-safe token-bucket rate limiter to `Pf9Client`. Gated by `PF9_RATE_LIMIT_ENABLED=true` (default off). Rate configurable via `PF9_API_RATE_LIMIT` (requests/second, default 10). The `_throttle()` method is called in `_headers()`, which is the single chokepoint for all authenticated API calls.

---

## [1.44.5] - 2026-03-08

### Infrastructure — Phase C production hardening (`docker-compose.yml`, `api/`, `nginx/`, `pf9-ui/`)

#### C1 — Production UI Dockerfile (`pf9-ui/Dockerfile.prod`)
- Added two-stage build: `node:20-alpine` runs `npm ci && npm run build`, then `nginx:1.27-alpine` serves the static `dist/` output with an SPA fallback (`try_files $uri $uri/ /index.html`). Eliminates the Vite dev server in production.

#### C2 — nginx TLS termination layer (`nginx/`)
- New `nginx/` directory with `Dockerfile`, `nginx.conf`, and `generate_certs.ps1`. The `pf9_nginx` service terminates HTTPS on ports 80/443, redirects HTTP→HTTPS, and reverse-proxies `/api/`, `/auth/`, `/settings/`, `/health`, and other API paths to `pf9_api:8000`; all other requests proxy to `pf9_ui:5173`.
- Security headers added: `Strict-Transport-Security`, `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff`.
- Self-signed 4096-bit RSA dev certs generated via `nginx/generate_certs.ps1`; `nginx/certs/*.key` and `nginx/certs/*.crt` added to `.gitignore`.

#### C3 — PostgreSQL port no longer exposed to host (`docker-compose.yml`)
- Removed `ports: "5432:5432"` from the `db` service. Database is accessible only via the internal Docker network (`pf9_db:5432`).

#### C4 — LDAP ports no longer exposed to host (`docker-compose.yml`)
- Removed `ports: "389:389"` and `"636:636"` from the `ldap` service. LDAP accessible internally only.

#### C5 — Healthchecks on `pf9_api` and `pf9_ui` (`docker-compose.yml`)
- `pf9_api`: `python -c "urllib.request.urlopen('http://localhost:8000/health')"`, interval 30 s, 3 retries, start_period 40 s.
- `pf9_ui`: `wget -q -O /dev/null http://127.0.0.1:5173` (explicit IPv4 — Alpine's `localhost` resolves to `::1`), interval 30 s, start_period 60 s.

#### C6 — pgAdmin and phpLDAPadmin gated behind `dev` profile (`docker-compose.yml`)
- Both services now have `profiles: ["dev"]`. They start only with `docker compose --profile dev up`; absent from the default production stack.

#### C7 — Gunicorn scaled to 4 workers + memory recycling (`api/Dockerfile`)
- `CMD` updated: `-w 4` (was `-w 2`), `--max-requests 1000 --max-requests-jitter 100` added to prevent gradual memory growth.

#### C8 — Resource limits on all services (`docker-compose.yml`)
- `deploy.resources.limits` added to every service: `pf9_api` (1.5 CPU / 1 GiB), `db` (1.0 CPU / 1 GiB), `snapshot_worker` (1.0 CPU / 768 MiB), `pf9_ui` (0.5 CPU / 512 MiB), workers/ldap/monitoring (0.5 CPU / 256 MiB), `nginx` (0.5 CPU / 128 MiB), `redis` (0.3 CPU / 192 MiB).

#### C9 — Redis caching for hot OpenStack API calls (`docker-compose.yml`, `api/`)
- New `pf9_redis` service: `redis:7-alpine`, 128 MiB `maxmemory`, `allkeys-lru` eviction, persistence disabled.
- New `api/cache.py`: `@cached(ttl, key_prefix)` decorator uses lazy Redis connection; falls back to direct call on any Redis error — API boots and works without Redis.
- Added `redis>=5.0.0` to `api/requirements.txt`.
- Applied `@cached` to 7 methods in `api/pf9_control.py`: `list_servers` (60 s), `list_flavors` (300 s), `list_domains` (120 s), `list_projects` / `list_volumes` / `get_compute_quotas` / `get_network_quotas` (60 s each).

---

## [1.44.4] - 2026-03-08

### Security — Phase B security hardening (`api/auth.py`, `api/main.py`, `pf9-ui/src/components/CopilotPanel.tsx`)

#### Security Fix — XSS via `dangerouslySetInnerHTML` in Copilot chat (`pf9-ui/src/components/CopilotPanel.tsx`)
- Bot messages were rendered via `dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }}` with no sanitization. If the backend returned HTML/script content in a message, it would execute in the user's browser.
- Added `dompurify ^3.2.0` (and `@types/dompurify ^3.0.0`) as a dependency. The call site is now `DOMPurify.sanitize(renderMarkdown(m.text))` — all generated HTML is stripped of any unsafe tags/attributes before insertion.

#### Security Fix — CORS wildcard on RBAC 403 responses (`api/main.py`)
- The `rbac_middleware` 403 response set `Access-Control-Allow-Origin: *` alongside `Access-Control-Allow-Credentials: true`, which is an invalid combination (browsers reject credentials with wildcard), and also unnecessarily broad.
- Changed to the same validated-origin pattern already used for 401 responses: origin is checked against `ALLOWED_ORIGINS` and set explicitly, or omitted if not recognised.

#### Security Fix — TrustedHostMiddleware wildcard removed (`api/main.py`)
- `allowed_hosts` included `"*"`, making the middleware a no-op.
- Now derived from `ALLOWED_ORIGINS`: scheme is stripped and port is dropped to extract bare hostnames (`localhost`, `127.0.0.1`, plus any production host from `PF9_ALLOWED_ORIGINS`). Wildcard entry removed entirely.

#### Security Fix — JWT revocation enforced on logout (`api/auth.py`)
- `verify_token()` only validated the JWT signature and expiry; tokens remained accepted after logout because the `user_sessions` table was never consulted.
- Now performs a DB lookup after signature validation: `SELECT 1 FROM user_sessions WHERE token_hash = %s AND is_active = true AND expires_at > NOW()`. Returns `None` (→ 401) if the session is not found or has been marked inactive. Falls back to JWT-only validation if the DB is temporarily unavailable.

#### Security Fix — CORS `allow_headers` / `expose_headers` narrowed from `"*"` (`api/main.py`)
- Replaced wildcard with explicit lists: `allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"]`, `expose_headers=["Content-Type", "X-Request-ID"]`.

#### Cleanup — Removed dead refresh-token configuration (`api/auth.py`, `api/main.py`, `docker-compose.yml`)
- The `Token` Pydantic model had a `refresh_token: Optional[str] = None` field that was always `None` in responses and unused by the UI.
- Both login response dicts in `main.py` returned `"refresh_token": None`. Removed.
- `docker-compose.yml` defined `JWT_REFRESH_TOKEN_EXPIRE_DAYS` which was never read by the application. Removed.

---

## [1.44.3] - 2026-03-08

### Security — Phase A critical security & bug fixes (`api/auth.py`, `api/log_collector.py`, `api/main.py`, `api/onboarding_routes.py`)

#### Security Fix — LDAP injection in `get_user_info()` (`api/auth.py`)
- The `username` value passed to `ldap.search_s()` was embedded directly into the filter string `(uid=<username>)`. An attacker with control over the username field could craft a payload such as `*)(uid=*)(|(uid=` to bypass the filter and retrieve arbitrary LDAP objects.
- Fixed by wrapping `username` with `ldap.filter.escape_filter_chars()` before constructing the search filter.

#### Security Fix — Command injection in `search_logs()` (`api/log_collector.py`)
- `search_term` was interpolated directly into a shell command executed over SSH (`sudo grep … <search_term>`). Shell metacharacters (`$()`, `` ` ``, `;`, `|`, etc.) would have been interpreted by the remote shell.
- Fixed by: (1) validating `search_term` against a strict allowlist regex (`^[\w\s./:@_-]{1,200}$`) — rejects on mismatch with HTTP 400; (2) switching `grep` to `-F` (fixed-string) mode; (3) wrapping the term with `shlex.quote()`.

#### Security Fix — MFA fails-open (`api/main.py`)
- An unhandled exception during the MFA verification step (e.g. DB timeout) caused the login flow to silently continue and issue a JWT as if MFA had passed.
- Fixed: the `except Exception` block now logs at ERROR level and raises `HTTPException(status_code=503)` instead of proceeding.

#### Bug Fix — Debug endpoints expose internal data (`api/main.py`)
- `GET /simple-test` returned `{"message": "working"}` with no authentication required.
- `GET /test-users-db` returned a user count and 3 sample rows including plaintext email addresses — also unauthenticated.
- Both endpoints removed entirely.

#### Bug Fix — `NameError` crash in log collector (`api/log_collector.py`)
- `list_available_logs()` and `search_logs()` both referenced the undefined variable `host` in their return dicts; the correct local variable is `ssh_host`. This caused an unhandled `NameError` on every call.
- Fixed: both return dicts now use `"host": ssh_host`.

#### Bug Fix — Destructive `DROP COLUMN` in startup migration (`api/onboarding_routes.py`)
- `_ensure_tables()` contained `ALTER TABLE onboarding_customers DROP COLUMN IF EXISTS department_tag` which ran on every application restart, silently deleting in-use data.
- Fix: the `DROP COLUMN` statement was removed. An `ADD COLUMN IF NOT EXISTS department_tag TEXT` was added to `_ALTER_SQL` to restore the column on existing installs where it had already been dropped.

#### Code Quality — Removed unreachable dead code (`api/auth.py`)
- A second `except Exception as e: print(f"Authentication Error: {e}")` block in `LDAPAuthenticator.authenticate()` could never be reached (the first handler in the same try/except covered the same exception type). Removed.

---

## [1.44.2] - 2026-03-06

### Fixed — Windows VM auto-provisioning: Glance image properties not set (`api/vm_provisioning_routes.py`)

#### Bug Fix — Windows VMs boot with wrong virtual hardware (wrong disk bus / missing SCSI model / wrong firmware)
- Windows VMs provisioned via Runbook 2 failed to boot reliably because the Glance image was missing the required hardware-property metadata (`os_type`, `hw_disk_bus`, `hw_scsi_model`, `hw_firmware_type`). Nova and Cinder used default values (IDE bus, SeaBIOS) which are incompatible with most Windows cloud images.
- The execution thread now calls `admin_client.update_image_properties()` immediately after detecting `os_type == "windows"` and **before** the Cinder boot volume is created. This performs a Glance v2 JSON-Patch on the image, setting:
  - `os_type = windows`
  - `hw_disk_bus = scsi`
  - `hw_scsi_model = virtio-scsi`
  - `hw_firmware_type = bios`
- The patch runs once per image per batch execution; subsequent provisioning runs are idempotent (Glance `add` op is safe when the property already exists with the same value).
- If the Glance PATCH fails (e.g. insufficient permissions), a `image_patch_warning` entry is written to `activity_log` and provisioning continues — the failure is non-fatal so that partially-configured environments are not blocked.

---

## [1.44.1] - 2026-03-05

### Fixed — Migration Summary Excel/PDF export errors (`api/export_reports.py`, `pf9-ui`)

#### Bug Fix — `AttributeError: 'str' object has no attribute 'get'` in export generators (`api/export_reports.py`)
- `per_os_breakdown` returned by `compute_project_fix_summary()` is a **dict** keyed by OS family name (e.g. `{"windows": {...}, "linux": {...}}`), not a list. The `generate_summary_excel_report()` and `generate_summary_pdf_report()` functions were iterating it as a list, which yielded the string keys instead of the value dicts, causing an `AttributeError` and a 500 on every export request.
- Fixed both generators to use `.items()` (with a fallback for any future list-format callers).

#### Bug Fix — "Failed to fetch" / 401 on export buttons (`pf9-ui/src/components/migration/SourceAnalysis.tsx`)
- Export Excel and Export PDF buttons were implemented as `<a href download>` anchor tags, which perform a plain browser GET with no `Authorization` header, resulting in a 401 from the API.
- Replaced both anchors with `<button onClick>` handlers that call a new `downloadSummaryBlob()` helper — uses `fetch()` with `Authorization: Bearer <token>` (same pattern as `downloadAuthBlob` used by the Migration Plan export buttons), then triggers the file download via a blob URL.

---

## [1.44.0] - 2026-03-07

### Added — Migration Summary per-day breakdown + engine throughput cap fix (`api/migration_engine.py`, `api/migration_routes.py`, `pf9-ui`)

#### Engine — Real Throughput Model (`api/migration_engine.py`)
- **Replaced time-slot packing with a GB/day throughput cap** — the previous scheduling loop used `Σ(per-VM hours) / agent_slots` against `working_hours_per_day * total_concurrent` as the daily limit. This allowed 15 VMs to each "consume" the full 4 000 Mbps bottleneck independently, yielding days that would have required 10× the available bandwidth. The new model treats the shared pipe correctly:
  - `AVG_BW_EFFICIENCY = 0.55` — realistic utilisation factor accounting for TCP overhead, I/O burst gaps, and agent coordination.
  - `effective_gbph = (bottleneck_mbps / 8) × 3600 / 1024 × AVG_BW_EFFICIENCY` — effective GB per agent-hour for the entire pipe.
  - `max_gb_per_day = effective_gbph × working_hours_per_day` — hard daily data-transfer ceiling (e.g. ~7 742 GB/day at 4 000 Mbps, 8-hour shift).
  - Day packing now breaks when `day_transfer_gb + vm_transfer_gb > max_gb_per_day`.
- **Corrected `wall_clock_hours`** — was `day_hours_used / total_concurrent` (under-counted); now `day_transfer_gb / effective_gbph` (actual time to drain the day's data through the bottleneck pipe).
- **New `over_capacity` flag** — set to `true` on any daily schedule entry where `wall_clock_hours > working_hours_per_day`. UI highlights these rows in red with a ⚠️ indicator.
- **New `transfer_gb` field** on each daily schedule entry — total data-copy payload for that day (in-use GB for warm, provisioned GB for cold).
- **Exposed `effective_gbph` and `max_gb_per_day` in `project_summary`** — visible in the Migration Plan project summary card and the Migration Summary daily table footer.

#### API — `GET /projects/{id}/migration-summary` rewrite (`api/migration_routes.py`)
- **Full rewrite** of `get_migration_summary()` to match the export-plan endpoint's data model exactly:
  - Calls `_get_project()` and `compute_bandwidth_model()` for consistent settings resolution.
  - **Tenant query now includes cohort JOIN**: `SELECT t.*, c.name AS cohort_name, c.cohort_order FROM migration_tenants t LEFT JOIN migration_cohorts c ON c.id = t.cohort_id` — fixes the alignment bug where all days showed "Uncohorted" in the summary.
  - **VM query uses `SELECT v.*`** instead of a specific column list, preventing missing-column crashes when new VM fields are added.
- **New `per_day[]` array** in the response — one row per schedule day, including: `day`, `cohort_name`, `tenant_count`, `vm_count`, `total_gb` (in-use), `wall_clock_hours`, `total_agent_hours`, `cold_count`, `warm_count`, `risk_green`, `risk_yellow`, `risk_red`, `over_capacity`.
- **New `total_provisioned_gb`** KPI field — total provisioned (raw-disk) GB across all in-scope VMs, shown alongside `total_in_use_gb` so engineers understand thin-provisioning headroom.

#### UI — Migration Summary tab (`pf9-ui/src/components/migration/SourceAnalysis.tsx`)
- **New "Migration Days" KPI card** (blue) in the executive KPI strip.
- **"Total Data" card** relabelled to **"In-Use Data (TB)"** with a subtitle showing the provisioned total (`X GB used / Y.YY TB provisioned`).
- **Per-day schedule table** between the KPI strip and OS breakdown: columns Day, Cohort/Wave, Tenants, VMs, Storage GB (in-use), Wall-clock (h), Agent Total (h), ❄️ Cold, 🔥 Warm, 🟢/🟡/🔴 risk counts; totals row at bottom. Over-capacity days highlighted in red with ⚠️ prefixed to the wall-clock value.
- **Migration Plan — project summary footer** now shows *"Daily throughput cap: X.X TB/day (N GB)"* derived from `project_summary.max_gb_per_day`.
- **Migration Plan — daily schedule rows** show wall-clock time in red with *"⚠️ exceeds Xh"* sub-label when `day.over_capacity = true`.
- **📊 Export Excel / 📑 Export PDF buttons** added to the Migration Summary tab header — download a pre-formatted workbook (4 sheets: KPI, Daily Schedule, OS Breakdown, Cohort Breakdown) or a portrait PDF with KPI table, daily schedule, OS/cohort breakdowns, and methodology notes.

#### Backend — Migration Summary Export (`api/export_reports.py`, `api/migration_routes.py`)
- **`generate_summary_excel_report(summary, project_name)`** — 4-sheet `.xlsx`: Summary KPIs, Daily Schedule (with red over-capacity row fill), OS Breakdown, Cohort Breakdown.
- **`generate_summary_pdf_report(summary, project_name)`** — A4 portrait PDF: KPI table, daily schedule table (repeated header), OS and cohort breakdowns, methodology section.
- **`GET /api/migration/projects/{id}/export-summary.xlsx`** — streams the Excel file as `migration-summary-{project}.xlsx`.
- **`GET /api/migration/projects/{id}/export-summary.pdf`** — streams the PDF as `migration-summary-{project}.pdf`.

---

## [1.43.0] - 2026-03-06

### Fixed — Wave Planner crash + risk column + wave capacity warning (`pf9-ui/src/components/migration/SourceAnalysis.tsx`)

#### Bug Fixes
- **Crash: `v.in_use_gb?.toFixed is not a function`** — PostgreSQL `NUMERIC` columns returned by the API serialize as JSON strings; `?.toFixed()` is not available on strings. Fixed by wrapping with `Number(v.in_use_gb).toFixed(1)` so the conversion happens before calling `.toFixed()`. Eliminates the uncaught `TypeError` that crashed the entire Wave Planner view when a wave was expanded.
- **Wrong risk colour / always amber** — VM rows in the expanded wave table were reading `v.risk_classification` but the field is named `risk_category` (matching the DB column and API response). Renamed all three references; risk dots (🟢/🟡/🔴) and colours now reflect actual risk tier.

#### Feature
- **Wave daily-capacity warning** (`WavePlannerView`) — each wave card now shows:
  - `💾 X.X GB` — total used-disk across all VMs in the wave (summed from the pre-loaded `wave.vms[]` array, always available in the list response).
  - `⚠️ Exceeds 1-day capacity (Y.Y GB/day)` in red — displayed when the wave's disk total exceeds the project's effective daily transfer capacity. The capacity is derived from the same bandwidth model used by the migration engine: bottleneck of source NIC, WAN link, agent ingest, and PCD storage write throughput (all converted to Mbps), then translated to GB/working-day using `project.working_hours_per_day`. Hovering the badge shows the exact capacity figure.

---

## [1.42.0] - 2026-03-05

### Added — Migration Planner Phase 5.0: Tech Fix Time & Migration Summary (`api/migration_engine.py`, `api/migration_routes.py`, `pf9-ui`)

#### Fix Time Estimation Engine
- **`compute_vm_fix_time()`** (`migration_engine.py`) — per-VM post-migration fix time model: sums weighted risk-factor scores (Windows OS, extra volumes, extra NICs, cold migration, risk tier, snapshots, cross-tenant dependencies, unknown OS) plus a base cutover window (default 30 min); multiplied by OS-family fix rate (Windows 50%, Linux 20%, Other 40%) to produce expected intervention time in minutes.
- **`compute_project_fix_summary()`** — project-level rollup: sums per-VM fix time across all in-scope VMs; groups by OS family and by cohort; computes data-copy time from bottleneck bandwidth; builds a methodology block explaining all three calculations.
- **`DEFAULT_FIX_WEIGHTS`** — 10 configurable weight factors (all in minutes); exposed via the Fix Settings API.
- **`migration_fix_settings` table** — per-project row storing 10 weight factors + 3 OS fix rates + optional global rate override; auto-created with defaults on first `GET /fix-settings` access.
- **`migration_vms.tech_fix_minutes_override INTEGER DEFAULT NULL`** — operator can lock any individual VM to a specific fix time, bypassing the model entirely.

#### Fix Settings & Summary API (`api/migration_routes.py`)
- **`GET /projects/{id}/fix-settings`** — returns current weights + rates (auto-creates defaults on first call).
- **`PATCH /projects/{id}/fix-settings`** — partial updates to any weight or fix rate; `null` resets a field to its default.
- **`PATCH /projects/{id}/vms/{vm_id}/fix-override`** — set or clear `tech_fix_minutes_override`; `null` clears the override and re-enables model calculation.
- **`GET /projects/{id}/migration-summary`** — full executive summary: KPI totals (VM count, data TB, data-copy hours, fix hours, total downtime hours); OS-family breakdown; per-cohort breakdown (vm_count, data_gb, copy_h, fix_h, downtime_h); bandwidth model parameters; methodology accordion text.
- All 4 routes use the shared `_get_fix_settings()` helper and the `with _get_conn() as conn:` pattern.

#### Migration Summary Tab (UI)
- **`MigrationSummaryView`** component added to `SourceAnalysis.tsx` — accessible as the **"📊 Summary"** sub-tab.
- **Executive KPI strip**: Total VMs in scope, Total Data (TB), Estimated Data-Copy Time, Estimated Fix Time, Total Downtime.
- **OS-family breakdown table**: per-OS row with VM count, fix rate %, data (GB), estimated fix time.
- **Per-cohort breakdown table**: one row per cohort with VM count, data (GB), copy time (h), fix time (h), and total downtime exposure.
- **Methodology accordion**: expandable section explaining data-copy time, per-VM fix score, expected fix time, and total downtime — suitable for management presentation.
- **Settings editor**: 10 weight sliders + 3 fix-rate percentage inputs + optional global override; **"💾 Save & Recalculate"** button writes to `PATCH /fix-settings` then re-fetches the summary.

#### VM Fix Time Override (UI)
- **VM table Fix column**: each row shows a `🔒 Xm` amber pill when an override is set, or `auto` in grey when the model is active; `fixOverrideLocal` React state updates the badge immediately after a save without a full reload.
- **"⏱ Fix Time Override" card** in the expanded VM row (alongside Mode Override and Migration Status panels): number input (blank = auto/model), **Save** button, **Clear** button (only when override is active). Uses `fixOverrideInput`, `fixOverrideSaving`, `fixOverrideLocal` state; calls `PATCH /vms/{id}/fix-override`.

#### Tenant Tab Filter Dropdowns (UI)
- Four new filter dropdowns in the Tenants sub-tab toolbar: **Scope** (All / In Scope / Out of Scope), **Ease** (All / Easy / Medium / Hard), **Cohort** (All / Unassigned / per-cohort name), **Network Type** (All / NSX-T / VLAN / Standard / Isolated).
- **Clear Filters** button appears when any filter is active.

#### DB Migration
- **`db/migrate_tech_fix.sql`** — `ALTER TABLE migration_vms ADD COLUMN IF NOT EXISTS tech_fix_minutes_override INTEGER DEFAULT NULL`; `CREATE TABLE IF NOT EXISTS migration_fix_settings (...)` with 10 weight columns, 3 OS-rate columns, and a global rate override. Applied to live DB.

### Added — Migration Planner: Reset Cohorts & Waves (`api/migration_routes.py`)
- **`DELETE /projects/{id}/cohorts`** — deletes ALL cohorts for a project in one call; NULLs `cohort_id` on every tenant row (even tenants that were previously excluded and therefore had stale assignments). Returns `cohorts_deleted` and `tenants_unassigned` counts. Requires `admin` permission.
- **`DELETE /projects/{id}/waves`** — deletes ALL waves for a project; removes all `migration_wave_vms` rows; resets `migration_status` back to `not_started` for any VM that was in `assigned` state. Returns `waves_deleted` and `vms_reset` counts. Requires `admin` permission.
- **🗑️ Reset All Cohorts button** added to the Cohorts tab toolbar (visible when cohorts exist). Calls `DELETE /cohorts`, confirms before executing, then reloads.
- **🗑️ Reset All Waves button** added to the Wave Planner toolbar (visible when waves exist). Calls `DELETE /waves`, confirms before executing, then reloads.
- Use these before re-running `auto-assign` / `auto-waves` whenever exclusions have changed, to guarantee a clean rebuild with no stale assignments from previous runs.

### Fixed — Migration Planner: Auto-Assign Cohort Preview Showing Wrong Disk Value (`api/migration_routes.py`, `api/migration_engine.py`, `pf9-ui`)
- **SQL fallback bug** — the `total_used_gb` tenant query used `ROUND(t.total_disk_gb / 1024.0, 2)` as the fallback when `in_use_gb` was not available. Since `total_disk_gb` is already in GB, dividing by 1024 produced TB-scale tiny numbers. Fixed: fallback chain is now `NULLIF(SUM(v.in_use_gb), 0)` → `t.total_in_use_gb` → `t.total_disk_gb` (provisioned, last resort). Both preview and apply queries updated. `t.total_in_use_gb` added to GROUP BY.
- **Misleading field name** — `_format_auto_assign_result` returned `total_disk_gb` in cohort summaries but the value was actually disk usage. Renamed to `total_used_gb` to match the source data.
- **Ambiguous UI label** — preview table column header "Disk (GB)" renamed to "Used (GB)" to make clear the value is actual disk usage from vPartition (`in_use_gb`), not provisioned allocation.

### Fixed — Migration Planner: Exclusion Filters Not Honoured in Capacity & Summary Endpoints (`api/migration_routes.py`)
- **`GET /projects/{id}/node-sizing`** (Capacity tab hardware sizing) — VM stats query had **no exclusion filters at all**: it aggregated vCPU, RAM, and disk across every VM in the project regardless of whether the org was excluded from the plan or whether individual VMs were marked `exclude_from_migration`. Fixed: query now joins `migration_tenants` and enforces `include_in_plan = true`, `exclude_from_migration = false`, and `template = false`.
- **`GET /projects/{id}/export-plan`** — correctly filtered tenant-level exclusions via `include_in_plan = true` but did **not** filter individual VMs excluded via the VM table checkbox. Fixed: added `AND NOT COALESCE(v.exclude_from_migration, false)` to the VM query.
- **`GET /projects/{id}/migration-summary`** — same gap: org-level exclusion was respected but individual VM exclusions were silently included in KPIs and breakdowns. Fixed: added `AND NOT COALESCE(vm.exclude_from_migration, false)` and `AND NOT COALESCE(vm.template, false)` to the VM query.
- No re-assessment required — these were all query-time filters; stored risk scores and time estimates are unaffected.

### Fixed — Migration Planner: Excluded Tenants Leaking Into Cohort & Readiness Endpoints (`api/migration_routes.py`)
- **`GET /projects/{id}/cohorts`** — cohort aggregate columns (`vm_count`, `total_vcpu`, `total_ram_gb`, `total_disk_gb`) were computed from ALL tenants assigned to each cohort including those with `include_in_plan = false`. Fixed: the `LEFT JOIN migration_tenants` now includes `AND COALESCE(t.include_in_plan, true) = true` so excluded tenants do not inflate cohort capacity totals.
- **`GET /projects/{id}/cohorts/{cohort_id}/summary`** — tenant list and VM status breakdown both included excluded tenants. Fixed: tenant query adds `AND COALESCE(include_in_plan, true) = true`; VM breakdown adds `AND NOT COALESCE(exclude_from_migration, false)` and `AND NOT COALESCE(template, false)`.
- **`GET /projects/{id}/cohorts/{cohort_id}/readiness-summary`** — readiness checks were run and counted for excluded tenants, inflating the "not ready" count and potentially blocking cohort proceed decisions. Fixed: query adds `AND COALESCE(include_in_plan, true) = true` so only in-scope tenants are evaluated.
- `auto_assign_cohorts` and `list_waves` were already correct.

### Fixed — Migration Planner: Excluded Tenants/VMs Leaking Into Networks & PCD Gap Analysis (`api/migration_routes.py`)
- **`GET /projects/{id}/networks`** — `tenant_names` and `tenant_count` fields aggregated tenant names from ALL VMs (including excluded tenants and individually excluded VMs). Fixed: added a `LEFT JOIN migration_tenants` with `COALESCE(t.include_in_plan, true) = true` and filters for `exclude_from_migration` and `template` on the VM join so only in-scope VMs contribute to the per-network tenant summary.
- **`GET /projects/{id}/network-mappings`** — `vm_count` per source network counted ALL powered-on VMs, including excluded ones. Fixed: the VM join now adds `NOT COALESCE(v.exclude_from_migration, false)`, `NOT COALESCE(v.template, false)`, and an `EXISTS` sub-check against `migration_tenants.include_in_plan` so only in-scope VMs are counted per mapping row.
- **`POST /projects/{id}/pcd-gap-analysis`** — the tenants query already filtered by `include_in_plan = true`, but the VMs query fetched ALL project VMs (no tenant-scope or individual-VM exclusion checks). Flavor/image/network gap analysis was therefore run against excluded VMs, producing phantom gaps. Fixed: VMs query now joins `migration_tenants` with `include_in_plan = true` and adds `NOT COALESCE(v.exclude_from_migration, false)` and `NOT COALESCE(v.template, false)`.
- `network-mappings/readiness`, `pcd-gaps`, and `pcd-gap-analysis` scoring were already correct (they operate on stored mapping/gap records).

## [1.41.0] - 2026-03-05

### Fixed — Migration Planner: Routed Network Type Classification (`api/migration_engine.py`)
- **`Routed_Net` now correctly classified as `nsx_t`** instead of `standard`. In VMware NSX-T, "Routed" networks are Tier-1 GENEVE overlay segments — they require NSX-T handling and cannot be directly mapped to standard vSwitch portgroups on PCD.
- Added `"routed"` and `"routed_net"` to `_NSXT_PATTERNS` so any network whose name contains "routed" is tagged as `nsx_t`.
- Added `"dlr-"` and `"esg-"` to `_NSXT_PATTERNS` for NSX-V Distributed/Edge Logical Router uplinks (also GENEVE-encapsulated, same migration implications).
- **`POST /projects/{project_id}/networks/reclassify`** — new endpoint that re-runs `_build_network_summary()` for a project, re-applying updated classification rules to all existing `migration_networks` rows without requiring a full RVTools re-upload.
- **"🔄 Reclassify Types" button** added to the Networks tab toolbar in the Migration Planner UI — calls the above endpoint and refreshes the network list.

### Added — Migration Planner: Tenants Page Decision Data (`api/migration_routes.py`, `pf9-ui`)
- **`GET /projects/{project_id}/tenants`** now returns 5 new fields per tenant alongside all existing allocation data:
  - `used_vcpu` — actual vCPU consumption (cpu_count × cpu_usage_percent / 100, summed over all tenant VMs)
  - `used_ram_gb` — actual RAM usage in GB (from `memory_usage_mb` column, or fallback to ram_mb × memory_usage_percent)
  - `used_disk_gb` — actual used disk in GB (from `in_use_gb`, sourced from RVTools vPartition)
  - `est_migration_hours` — estimated migration duration at 100 GB/h effective throughput (NULL if no usage data)
  - `network_type_counts` — JSON object `{nsx_t: N, vlan_based: M, standard: P, isolated: Q}` counting distinct networks reachable from this tenant's VMs
- **Tenants table** gains 5 new sortable/visible columns: **vCPU (used)**, **RAM GB (used)**, **Disk GB (used)**, **Est. Time**, and **Networks** (colored type pills with counts).
- **Ease score badge** now shows the label inline — e.g. `42 Medium` in amber — so the migration difficulty is readable at a glance without clicking into the breakdown popover.
- Existing allocated-resource columns renamed `vCPU (alloc)`, `RAM GB (alloc)`, `Disk GB (alloc)` to distinguish them from actual usage.



### Added — Image & Flavor Reports + LDAP Password Reset

#### Reports (`api/reports.py`, `api/search.py`)
- **`GET /reports/image-usage`** — *Image Usage by Tenant*: lists every Glance image with total/active/shutoff VM counts, owner tenant, size, visibility, disk format, and a comma-separated list of all tenants consuming the image. Boot-from-Volume instances are resolved via Cinder `volume_image_metadata` so BFV VMs are counted correctly. Sorted by usage descending. Supports `?format=csv`.
- **`GET /reports/flavor-by-tenant`** — *Flavor Usage by Tenant (Detail)*: one row per (flavor, tenant) pair showing instance count, active/shutoff split, vCPUs, RAM (MB), disk (GB), total vCPU footprint, and total RAM footprint. BFV servers are handled via a dual name+ID flavor lookup. `list_flavors()` uses `?is_public=None` to return all flavors (public, private, access-restricted). Flavors with zero VMs are included as their own rows so the full catalog is always visible. Optional `?domain_id=` filter. Supports `?format=csv`.
- Both reports added to `REPORT_CATALOG` and `_INTENT_PATTERNS` in `search.py` — natural-language queries such as *"image usage"* or *"flavor by tenant"* auto-surface the new reports from the search bar.
- Report catalog grows from 18 → 20 entries.

#### Admin Tools — LDAP Password Reset
- **`LDAPAuthenticator.change_password()`** (`api/auth.py`) — new admin method: binds as LDAP admin, computes SSHA hash (`hashlib.sha1` + 4-byte `secrets` salt), applies `MOD_REPLACE` on `userPassword`.
- **`POST /auth/users/{username}/password`** (`api/main.py`) — superadmin-only endpoint; validates minimum 8-character length, calls `change_password()`, writes a `password_reset` audit event to `activity_log`.
- **UserManagement.tsx** — 🔑 button added to every row in the Users table (between ✏️ and 🗑️). Clicking it expands an inline reset form (no modal) with a password input, error/success feedback, and Save / Cancel controls.

#### VM Provisioning — Smarter Windows Dry-Run Checks (`api/vm_provisioning_routes.py`)
- **`windows_glance_property` warning** now suppressed when Windows is already identifiable from the image name (e.g. `Win2019-cloudbase-qcow2-image`) — the warning only fires for ambiguous images that lack both a `os_type=windows` Glance property and a recognisable name.
- **`windows_cloudinit` warning** is no longer emitted unconditionally for all Windows VMs. It is now suppressed when the image name contains `"cloudbase"` or a `cloudbase_init` / `cloud_init_tool=cloudbase` Glance property is present — confirming cloudbase-init is already baked in. The warning still fires for generic Windows images with no cloudbase evidence.

#### VM Provisioning — Reliable Windows Boot-from-Volume (`api/vm_provisioning_routes.py`)
- **Volume wait extended from 5 → 20 minutes** (240 × 5 s polls). Large Windows images (e.g. 9.4 GB `Win2019-cloudbase-qcow2-image`) require significantly more time to copy from Glance into a Cinder volume than the previous 60 × 5 s timeout allowed. VMs that previously failed with a blank "No bootable device" disk now wait long enough for the copy to finish.
- **`bootable == "true"` check added** — Cinder sets `status: available` before the image-copy step fully completes; the `bootable` flag is only set to `"true"` once the volume is actually ready to boot. The provisioner now waits for *both* conditions before creating the Nova server, eliminating the race condition that caused SeaBIOS to report "No bootable device".
- **Windows volume size floor raised to 40 GB** — a fallback value of 10 GB is too small for Windows Server. When `virtual_size` is not populated in Glance the effective size is now clamped to a minimum of 40 GB for Windows OS type, preventing `ERROR creating volume: requested size too small`.
- **`imageRef` passed to Nova server create** — when using a pre-created Cinder volume (`source_type=volume`), Nova does not read Glance image properties for hardware configuration unless `imageRef` is also provided in the request. Adding `imageRef` allows Nova to pick up `hw_firmware_type`, `hw_machine_type`, and `hw_disk_bus` from the Glance image, enabling UEFI firmware for Windows Server 2019+ GPT images.
- **Auto-set UEFI on Windows images** — before creating the boot volume, if the selected image `os_type=windows` but is missing the `hw_firmware_type` Glance property, the provisioner automatically patches the image with `hw_firmware_type=uefi` and `hw_machine_type=q35` via the new `update_image_properties()` Glance v2 JSON-Patch method. The patch is logged as an `image_patched` activity event. A new `windows_uefi` warning is also shown in the dry-run report when this property is absent.

## [1.39.0] - 2026-03-03

### Added — Runbook 2: VM Provisioning (Boot-from-Volume)

Full guided VM provisioning workflow as Runbook 2: multi-step UI form with live PCD dropdowns,
Excel bulk upload, quota pre-check, dry-run gate, approval gate, background execution,
audit trail, and email notification on completion.

#### Backend (`api/`)
- **`vm_provisioning_routes.py`** (new) — FastAPI router at `/api/vm-provisioning`:
  - `GET /resources` — returns Glance images, disk=0 flavors, networks, SGs scoped to domain+project
  - `GET /quota` — Nova + Cinder quota with usage for the target project
  - `GET /available-ips` — computes free IPs from subnet allocation pools (cap 200)
  - `GET /template` — download Excel bulk provisioning template (openpyxl)
  - `POST /upload` — parse + validate Excel workbook, return structured row data
  - `POST /batches` — create provisioning batch (form or Excel-derived)
  - `GET /batches` — list all batches (latest 100)
  - `GET /batches/{id}` — batch detail with VM rows
  - `POST /batches/{id}/dry-run` — pre-flight: image/flavor/network/SG/name/cloud-init/quota checks
  - `POST /batches/{id}/submit` — submit for approval
  - `POST /batches/{id}/decision` — approve or reject
  - `POST /batches/{id}/execute` — background execution per VM row
  - `DELETE /batches/{id}` — delete batch (not while executing)
  - Background thread: Cinder volume create → poll `available` → Nova BFV boot → poll `ACTIVE` → console log → completion email
  - DB tables: `vm_provisioning_batches`, `vm_provisioning_vms` (inline SQL, no file dependency)
  - cloud-init auto-generated: Linux (`#cloud-config`, SHA-512 password hash) or Windows (cloudbase-init `#ps1_sysnative`)
  - Naming convention: `{tenant_slug}_vm_{suffix}`, hostname uses hyphen instead of underscore (RFC 1123)
- **`pf9_control.py`** — new methods: `list_images()`, `get_image()`, `list_diskless_flavors()`, `get_quota_usage()`, `list_available_ips()`, `create_boot_volume()`, `get_volume()`, `create_server_bfv()`, `get_server()`, `get_console_log()`, `scoped_for_project()`; Glance endpoint discovery added to `authenticate()`
- **`main.py`** — registered `vm_provisioning_router`
- **`notification_routes.py`** — added 5 new event types: `vm_provisioning_submitted`, `vm_provisioning_approved`, `vm_provisioning_rejected`, `vm_provisioning_completed`, `vm_provisioning_failed`

#### Frontend (`pf9-ui/`)
- **`VmProvisioningTab.tsx`** (new) — 4-step form:
  - Step 1: domain + project selection, resource loading, live quota overview panel
  - Step 2: VM rows — image card grid, disk=0 flavor table, volume GB, network dropdown, SG chip picker with dropdown, static IP toggle + available IP list
  - Step 3: per-row OS credentials (username + password) + collapsible cloud-init YAML override + preview
  - Step 4: review table + batch name + submit
  - Batch list view with dry-run / submit / approve / reject / execute / refresh / delete actions
  - Batch detail modal with dry-run check results and VM status table
  - Auto-poll for executing batches (6 s interval)
- **`VmProvisioningTab.css`** (new) — dark theme matching BulkOnboardingTab
- **`RunbooksTab.tsx`** — added ☁️ VM Provisioning card (blue border) + `showProvisioning` state + conditional render

### Fixed — VM Provisioning: Tenant-Scoped Auth (`provisionsrv`)

Root cause: the admin token was scoped to the `service` project; Nova/Neutron/Cinder resource lookups (SGs, networks, volumes) resolved against that scope instead of the target tenant, causing "not found" errors during execution.

Fix: introduced a dedicated `provisionsrv` Keystone service account (native Keystone user, NOT in LDAP — invisible to tenant UI) that authenticates with a real project-scoped token for each execution. Mirrors the `snapshotsrv` pattern.

#### New Files
- **`api/vm_provisioning_service_user.py`** — provisionsrv credential management + role assignment + scoped client factory:
  - `get_provision_user_password()` — Fernet-decrypts password from env
  - `ensure_provisioner_in_project(admin_client, project_id)` — idempotent `member` role grant (cached per process run)
  - `get_provisioner_client(project_id, …)` — returns a `Pf9Client` authenticated and scoped to the target project
- **`api/setup_provision_user.py`** — one-time Keystone user creation script: `docker exec pf9_api python3 /app/setup_provision_user.py`

#### Updated Files
- **`api/pf9_control.py`** `scoped_for_project()` — now calls `get_provisioner_client()` for real project-scoped Keystone auth instead of copying admin token
- **`api/pf9_control.py`** `create_boot_volume()` — removed `project_id` body injection (provisionsrv token scope ensures correct placement automatically)
- **`api/pf9_control.py`** `get_volume()` — removed `all_tenants=1` (provisionsrv token is already project-scoped)
- **`api/vm_provisioning_routes.py`** `_execute_batch_thread()` — `ensure_provisioner_in_project()` called before every execution (critical: Re-run bypasses dry-run, so this must run in the execute path)
- **`api/vm_provisioning_routes.py`** `dry_run()` — also calls `ensure_provisioner_in_project()` for early validation
- **`docker-compose.yml`** — added `PROVISION_SERVICE_USER_EMAIL`, `PROVISION_SERVICE_USER_DOMAIN`, `PROVISION_PASSWORD_KEY`, `PROVISION_USER_PASSWORD_ENCRYPTED` to `pf9_api` environment

#### New Environment Variables
| Variable | Description |
|---|---|
| `PROVISION_SERVICE_USER_EMAIL` | Keystone username for provisionsrv (e.g. `provisionsrv@example.com`) |
| `PROVISION_SERVICE_USER_DOMAIN` | Keystone domain (default `Default`) |
| `PROVISION_PASSWORD_KEY` | Fernet key for password decryption |
| `PROVISION_USER_PASSWORD_ENCRYPTED` | Fernet-encrypted provisionsrv password |

### Fixed — VM Provisioning: Windows Cloud-Init, Admin History, Rich Email (v1.39.0 patch)

#### Windows Cloud-Init (`api/vm_provisioning_routes.py`)
- **`_build_cloudinit_windows()`** rewritten: built-in `Administrator` account handled without `/add` (which silently fails on built-in accounts) — now uses `net user Administrator "{pwd}"` + `/active:yes` + PasswordExpires=False; custom user path unchanged (`/add` + Administrators group)
- **`create_server_bfv()` `admin_pass` parameter** (`api/pf9_control.py`): sets `body["server"]["adminPass"]` for cloudbase-init `SetUserPasswordPlugin` as belt-and-suspenders alongside user_data
- **Call site updated** in `_execute_batch_thread` to pass `admin_pass=vm["os_password"]` for Windows VMs
- **Dry-run** emits `windows_cloudinit` (warning) if image lacks `os_type=windows` Glance property and `windows_glance_property` (warning) for missing Glance property
- **`VmProvisioningTab.tsx` `buildVmInitPreview()`**: consolidated Windows detection into a single branch; now shows correct `#ps1_sysnative` script for Windows (built-in Admin vs custom user) and unchanged `#cloud-config` for Linux

#### Admin Tools — VM Provisioning History Tab (`pf9-ui/src/components/UserManagement.tsx`)
- New **"🖥️ VM Provisioning"** sub-tab in Admin Tools (between Runbook Executions and Runbook Approvals)
- Lists all batches: `#`, Batch Name, Domain/Project, Status badge (colour-coded), Approval Status, Created By, Date, ▼ View
- ▼ View toggle fetches `GET /api/vm-provisioning/batches/{id}` + `GET /api/vm-provisioning/batches/{id}/logs` and shows:
  - Per-VM table: Name, Status, IP(s), Image, Flavor, OS, GB, Error
  - Execution timeline: dark terminal panel with timestamps, action labels (green/red/blue), and message from `activity_log`
- Refresh button; loading indicator; row count badge

#### Completion Email Enhancement (`api/vm_provisioning_routes.py`)
- **`_build_completion_email(batch, vm_rows, activity_steps=None)`**: added `activity_steps` parameter
  - VM table gains columns: Image (truncated, `title` tooltip), Flavor, OS Type, Volume GB, Error (red, truncated)
  - Status cells use coloured badge spans (green/red/blue bg + text)
  - New **"Execution Timeline"** section below the VM table: dark `#0f172a` panel, monospaced font, timestamp + action label (colour-coded) + message per entry
  - Header sub-line now shows submitter + status in addition to VM count / domain / project
- **Call site in `_execute_batch_thread`**: now queries `activity_log` for both `vm_provisioning` and `vm_provisioning_vm` entries ordered by `created_at` and passes result as `activity_steps`

---

## [1.38.2] - 2026-03-02

### Fixed — Bulk Customer Onboarding: networks, email notifications, UX

- **Networks created as external/shared** — `is_external` defaulted to `True` in four places (`_ensure_tables()` schema, ALTER, parse-time default, execution call). Fixed to `False` everywhere. Existing bad DB rows reset. Tenant networks are now private to the project.
- **Excel template `is_external` default** — sample row changed from `true` to `false`; README sheet updated with a warning explaining that only admin-managed provider networks should be `true`.
- **`send-notifications` endpoint 500 + apparent CORS error** — `send_notifications()` was querying a non-existent table (`onboarding_domains`). Corrected to `onboarding_customers`. The 500 crash prevented CORS headers from being written, making it look like a CORS problem; CORS configuration was never the issue.
- **Select None not working in notifications panel** — `selectedNotifIds` used `Set<number>` where an empty `Set` and "uninitialized" were indistinguishable. Changed to `Set<number> | null` (`null` = all pre-checked, empty `Set` = explicitly none). Select None now correctly deselects all checkboxes.
- **Approval comment textarea invisible text** — `.ob-textarea` used `--bg-tertiary` (near-black `#0f172a`) instead of `--bg-secondary`. Fixed to `var(--input-bg, var(--bg-secondary, #1e293b))`; added `:focus` border rule and `::placeholder` colour.
- **Enhanced welcome email templates** — Personal emails now include a polished gradient header, a credentials table (username + amber-highlighted temp password), a per-project networks table, and a login-domain tip box. Admin summary emails now have per-domain → per-project sections listing networks and users (with temp passwords), plus an all-users summary table at the bottom.
- **Resend button for notifications** — After the first send, the Send button is replaced by a ✅ "Emails sent" indicator and a 🔁 Resend button. Clicking Resend re-enables the send flow.
- `api/pf9_control.py` — `create_provider_network()` `external` parameter default changed to `False`.

---

## [1.38.1] - 2026-03-02

### Fixed — Bulk Customer Onboarding polish & permissions

- **CORS / HTTP 500 on upload** — `require_permission()` was returning `True` (bool) instead of the user dict, causing the middleware to propagate a 500 before CORS headers were emitted. Fixed to return `user.model_dump()`.
- **Operator role blocked from all onboarding endpoints** — zero `role_permissions` rows existed for `resource='onboarding'`. Added: `admin/onboarding/admin`, `operator/onboarding/read+create+execute`, `technical/onboarding/read`, `viewer/onboarding/read`. Permissions added to both migration SQL files and seeded into the running DB.
- **Excel template network sheet** — `physical_l2` networks no longer list CIDR / gateway / DHCP / allocation-pool columns as required; `virtual` network kind sample row added; per-kind field-applicability matrix added to the README sheet.
- **Approve / Reject buttons shown to non-admin users** — buttons now gated by `isAdminUser()` (checks `localStorage` role); non-admins see a ⏳ "Waiting for admin approval…" amber indicator. Polling extended to cover `pending_approval` state (every 5 s) so the Execute button appears automatically once approved.
- **Onboarding table readability** — dark header (`#1a2840`), alternating row stripes, corrected cell text colour (`--text-primary` / `#cbd5e1`), all 12 quota columns now shown for projects, network table shows Kind / CIDR / VLAN columns, `pcd_*` columns renamed to human-readable "OS … ID" labels.
- **Copilot FAB overlap** — FAB (`position: fixed`) was obscuring page content beneath it. Increased `.pf9-root` bottom padding to 96 px; reduced FAB `z-index` to 9000 and set resting opacity to 0.82 (full opacity on hover).

---

## [1.38.0] - 2026-03-02

### New — Runbook 1: Bulk Customer Onboarding via Excel

- **`GET /api/onboarding/template`** — streams a styled four-sheet Excel workbook (`customers`, `projects`, `networks`, `users`) with sample rows and header formatting as the downloadable template operators fill in before uploading.
- **`POST /api/onboarding/upload`** — accepts a multipart Excel file upload, parses all four sheets, validates every row (required fields, FK integrity, CIDR format, email format, role values), persists a batch record with all child rows, and returns a validation summary. Sets `status='invalid'` if any errors are found; `status='validated'` otherwise.
- **`GET /api/onboarding/batches`** — lists all onboarding batches in reverse chronological order.
- **`GET /api/onboarding/batches/{id}`** — returns full batch detail including all customer, project, network, and user rows with per-item status.
- **`POST /api/onboarding/batches/{id}/dry-run`** — connects to PCD and checks which resources already exist (`would_create` vs `would_skip`). Sets `status='dry_run_passed'` if zero conflicts; `status='dry_run_failed'` otherwise. **Execution is hard-locked until dry_run_passed.**
- **`POST /api/onboarding/batches/{id}/submit`** — submits the batch for approval; sets `approval_status='pending_approval'` and fires `onboarding_submitted` notification.
- **`POST /api/onboarding/batches/{id}/decision`** *(requires `onboarding:approve`)* — approves or rejects the batch with an optional comment; fires `onboarding_approved` / `onboarding_rejected` notification.
- **`POST /api/onboarding/batches/{id}/execute`** — executes the batch against PCD. Requires `approval_status=='approved'` AND `status=='dry_run_passed'`; returns HTTP 400 otherwise (enforce gate). Runs in a background thread; creates domains → projects (with quota) → networks + subnets → users + role assignments sequentially with continue-and-report semantics. Per-item status written back to DB in real time. Sets batch to `complete` or `partially_failed` on finish; fires `onboarding_completed` / `onboarding_failed` notification.
- **`DELETE /api/onboarding/batches/{id}`** — deletes batch and all child rows (cascade); blocked if status is `executing`.
- **5 new notification event types** — `onboarding_submitted`, `onboarding_approved`, `onboarding_rejected`, `onboarding_completed`, `onboarding_failed` registered in `VALID_EVENT_TYPES`.
- **5 new DB tables** — `onboarding_batches`, `onboarding_customers`, `onboarding_projects`, `onboarding_networks`, `onboarding_users`; auto-migrated on API startup.
- **UI: `BulkOnboardingTab`** — full step-indicator workflow UI (Upload → Validate → Dry Run → Approve → Execute → Done). Accessible via a special card in the Runbooks tab. Features: drag-and-drop upload panel, template download, validation error table, dry-run result table (would-create / conflict breakdown), approval banner with inline Approve/Reject modal, live-polling execution view with per-item status tables, and final result summary.
- **Runbooks tab** — new ≪📦 Bulk Customer Onboarding≫ card navigates to `BulkOnboardingTab`.

---

## [1.37.0] - 2026-03-02

### New — vJailbreak Credential Bundle & Tenant Handoff Sheet

- **`GET /projects/{id}/export-vjailbreak-bundle`** — exports a project-wide JSON credential bundle formatted for vJailbreak consumption. Contains PCD auth URL, schema version, per-tenant mapping of: PCD project ID, service-account credentials (`username` / `password` / `pcd_user_id`), full user list with temporary passwords, network UUIDs (CIDR, gateway, VLAN), and wave sequence. Accepts optional `?cohort_id=` query parameter to restrict to a single cohort.
- **`GET /projects/{id}/cohorts/{cid}/export-vjailbreak-bundle`** — path-parameter cohort variant of the above; identical payload scoped to the specified cohort.
- **`GET /projects/{id}/export-handoff-sheet.pdf`** — generates and streams a CONFIDENTIAL A4 portrait PDF handoff document. One section per tenant: domain/project identity table, network mappings table (source name, target UUID, CIDR, gateway, VLAN), and users/credentials table highlighting service accounts. Confidentiality notice and footer ("CONFIDENTIAL · Platform9 Migration Handoff · {project name} · Page N") on every page.
- **Partial-bundle warnings** — both export endpoints emit structured `warnings[]` in the response if any tenants are missing service-account credentials or PCD project IDs, so callers know the bundle is incomplete before submitting to vJailbreak.
- **Activity logging** — all three endpoints write activity log entries (`export_vjailbreak_bundle` / `export_handoff_sheet`) for audit trail.
- **Notification events** — `vjailbreak_bundle_exported` and `handoff_sheet_exported` registered in `VALID_EVENT_TYPES`; both fire on successful export (bundle severity `warning` when warnings present, otherwise `info`; PDF always `warning` due to plaintext passwords).
- **UI: Export panel in Prepare PCD** — once all provisioning tasks are complete (`allDone === true`) a two-card export panel appears in the *Prepare PCD* tab: "📦 vJailbreak Credential Bundle" (downloads JSON) and "📄 Tenant Handoff Sheet" (downloads PDF with password warning), giving operators a single click to produce all migration handoff artifacts.

---

## [1.36.2] - 2026-03-01

### New — Approval Workflow, Dry Run & Audit Log

- **2-step approval gate** — `POST /projects/{id}/prepare` sets `prep_approval_status='pending_approval'` and fires a `prep_approval_requested` notification; `POST /prepare/run` now raises HTTP 403 if the plan has not been explicitly approved.
- **`GET /projects/{id}/prep-approval`** — returns current approval status (`pending_approval`, `approved`, `rejected`), who requested it, who approved/rejected, when, and full history list.
- **`POST /projects/{id}/prep-approval`** *(requires `migration:admin`)* — approves or rejects the pending plan; logs an activity entry; fires `prep_approval_granted` / `prep_approval_rejected` notification events.
- **`POST /projects/{id}/prepare/dry-run`** — simulates execution against live PCD without writing anything; classifies each pending task as `would_create`, `would_skip_existing`, or `would_execute` (for always-apply types like quotas/subnets), returning per-type and summary counts.
- **`GET /projects/{id}/prep-audit`** — returns the full audit trail for provisioning actions: approval history from `migration_prep_approvals`, activity log entries for `migration_prep_tasks` resource type, and execution history (all tasks with `executed_by` set).
- **`migration_prep_approvals` table** — new table storing each approval/rejection decision with `approver`, `decision`, `comment`, `created_at`; indexed on `(project_id, created_at DESC)`.
- **Four new notification event types** — `prep_approval_requested`, `prep_approval_granted`, `prep_approval_rejected`, `prep_tasks_completed` registered in `VALID_EVENT_TYPES`.
- **Bug fixes** — `_find_task_resource` now uses `->>` text extraction operator (PostgreSQL `json = json` comparison unsupported); rollback handler adds `conn.rollback()` before error-status update to recover from aborted transactions; `rollback_prep_task` for `create_project` wraps the optional `migration_tenants` update in try/except.
- **UI: approval banner** — `PreparePcdView` shows a contextual banner driven by `GET /prep-approval`: yellow (pending, with Approve/Reject inline), green (approved with approver + timestamp), red (rejected with comment + re-generate note), grey (no plan yet).
- **UI: gated Run All** — *▶ Run All* button only renders when `approval?.status === "approved"`; replaced by a disabled *🔒 Run All* otherwise.
- **UI: dry run panel** — *🧪 Dry Run* button fires `POST /prepare/dry-run` and shows a per-type breakdown table (total / would create / would skip / would execute). 
- **UI: audit log toggle** — *📋 Audit Log* button reveals three inline tables: Approval History, Activity Log, Execution History drawn from `GET /prep-audit`.

### Documentation
- **README** — version/date bumped to 1.36.2 / March 2026; architecture table worker count corrected to 2; Recent Updates section extended with full v1.35.0–v1.36.2 feature summaries (PCD Data Enrichment, Auto-Provisioning, Approval Workflow)
- **ARCHITECTURE.md** — worker count corrected in three places (2 default, 4 recommended for production); DB connection pool math updated accordingly
- **DEPLOYMENT_GUIDE.md** — version bumped to 2.2 / March 2026; migration steps added for `migrate_phase4_preparation.sql` and `migrate_prep_approval.sql`; Production Hardening section rewritten with concrete guidance: disable dev-only services (pgAdmin, phpLDAPadmin), remove exposed DB/LDAP ports, production nginx build, worker tuning, healthchecks, and HTTPS reverse proxy
- **SECURITY.md** — date updated; RBAC tier count corrected from 4 to 5 tiers
- **ADMIN_GUIDE.md / CONTRIBUTING.md** — dates and worker count updated

---

## [1.36.1] - 2026-03-01

### New — Provisioning Polish: Confirmation Modal, Execution Summary & Notifications

- **`GET /projects/{id}/prep-summary`** — returns a per-task-type breakdown of provisioning results: `created`, `skipped`, `failed`, `pending` counts plus overall totals and a `complete` boolean flag.
- **Run All confirmation modal** — clicking *▶ Run All* now opens an inline overlay listing the exact resource counts per type (e.g. "122 × 🏛 Create Domain, 122 × 📁 Create Project, …") with a destructive-action warning before firing the API call.
- **Provisioning Summary panel** — once all tasks reach `done` status the UI automatically loads and displays a full summary table (task type × created / skipped / failed) sourced from the new `prep-summary` endpoint.
- **Notification on run completion** — `POST /prepare/run` now fires a `prep_tasks_completed` notification event (severity `critical` if any tasks failed, `info` otherwise) via the existing `_fire_notification` infrastructure so subscribers can receive email/in-app alerts.
- **`prep_tasks_completed` event type** — registered in `VALID_EVENT_TYPES` in notification routes so administrators can subscribe to it from the Notifications preferences UI.

---

## [1.36.0] - 2026-03-01

### New — ⚙️ Prepare PCD (Auto-Provisioning)

- **`GET /projects/{id}/prep-readiness`** — pre-flight check returning readiness status for all four pre-migration data enrichment items (subnet details, flavor staging, image requirements, tenant users). Returns per-item totals, completion counts, and current task statistics.
- **`POST /projects/{id}/prepare`** — generates an ordered provisioning task plan: `create_domain` (1000s) → `create_project` (2000s) → `set_quotas` (3000s) → `create_network` (4000s) → `create_subnet` (5000s) → `create_flavor` (6000s) → `create_user` (7000s) → `assign_role` (8000s). Clears any previous pending/failed tasks before regenerating. Quota values derived from Phase 2C overcommit profile (cpu/ram/disk ratios).
- **`GET /projects/{id}/prep-tasks`** — lists all tasks ordered by `task_order` with per-status counts.
- **`POST /projects/{id}/prep-tasks/{task_id}/execute`** — executes a single pending or failed task against the PCD Keystone/Neutron/Nova APIs. Writes back PCD UUIDs to source tables (`target_network_id`, `pcd_flavor_id`, `pcd_user_id`, `temp_password`) on success.
- **`POST /projects/{id}/prepare/run`** — runs all pending/failed tasks in order; stops on first new failure to prevent cascading.
- **`POST /projects/{id}/prep-tasks/{task_id}/rollback`** — undoes a completed task by deleting the PCD resource. Supported types: `create_domain` (safety-checked — refuses if domain still contains projects), `create_project`, `create_network`, `create_flavor`, `create_user`. Resets task status back to `pending`.
- **`DELETE /projects/{id}/prep-tasks`** — clears all pending and failed tasks (for regenerating a fresh plan).
- **`⚙️ Prepare PCD` UI sub-tab** — Readiness grid (4 cards: subnets/flavors/images/users, green/red), *Generate Plan* and *Run All* buttons, task table with status badges, per-task *Run* / *Rollback* / inline error expansion. Auto-refreshes every 3 s while tasks are running. All colors use CSS variables (dark-mode compliant).

### Fixed

- `migration_overcommit_profiles` JOIN in task generation used wrong column `name` → corrected to `profile_name`.
- `pf9_control` import inside `_execute_one_task` used relative import syntax → corrected to absolute `from pf9_control import get_client`.

---

## [1.35.7] - 2026-03-01

### New — Network Map: Excel Template Export / Import

- **📥 Download Template** button — exports a styled XLSX with the full network map pre-filled: 2 grey read-only columns (Source Network, VMs) + 8 blue editable columns (VLAN ID, PCD Target, Subnet/CIDR, Gateway, DNS Servers, IP Range Start/End, Notes). Row 1 is an instruction banner; headers and data start at row 2. Freeze pane locks columns A–B while scrolling.
- **📤 Import Template** button — uploads a filled template and bulk-updates all editable fields. Flexible column detection (case-insensitive header matching). Match uses `LOWER(TRIM(...))` on both sides to tolerate whitespace/case drift. VLAN values are accepted as integer or float (e.g. `100.0` → `100`).
- **Formula detection** — if the uploaded file contains unevaluated formulas referencing external files (e.g. `=VLOOKUP(A3,vcd_networks.csv!...)`) openpyxl returns `None` for those cells. The importer now loads the workbook twice (once `data_only=True`, once raw) to detect formula strings and returns HTTP 422 with a clear fix instruction: *"select all blue columns → Copy → Paste Special → Values Only → Save → re-upload."*
- **Header row detection fix** — robustly locates the header row by scoring the first 5 rows: a row qualifies as the header only when it contains both a "source" cell AND at least one of "vlan/subnet/gateway/pcd/target/dns/note". This prevents the instruction banner row (which may mention "source") from being mistaken as the header.
- **Diagnostic response** — when all rows are skipped, the API response now includes a `diagnostics` object with breakdown: `skipped_empty_patch` vs `skipped_no_db_match`, sample source names from the file, and sample source names from the DB, so mismatches are immediately visible in the UI error banner.
- New API endpoints: `GET /network-mappings/export-template`, `POST /network-mappings/import-template`

### New — Network Map: Confirm Subnets button

- **✓ Confirm Subnets** toolbar button — bulk-sets `subnet_details_confirmed = true` for all rows that have a CIDR value, updating the `Subnet Details: X/Y` readiness counter in a single click.
- **Import auto-confirm** — when a template import provides a CIDR for a row, `subnet_details_confirmed` is automatically set to `true` at import time — no extra step needed.
- New API endpoint: `POST /network-mappings/confirm-subnets`

### Improved — Network Map: Subnet Details column shows CIDR inline

- **Confirmed rows** now show a green `✓ 10.0.0.0/24` clickable button instead of a generic "✓ subnet ready" pill — the actual CIDR is visible at a glance in the table.
- **Rows with CIDR but not yet confirmed** show an amber `⚠ 10.0.0.0/24` button — visible reminder to click confirm.
- **Hover tooltip** on both states shows full `CIDR | GW: x.x.x.x` details.

### Improved — Networks tab simplified to read-only discovery view

- Removed all subnet/gateway/DNS/PCD-target editing columns from the Networks tab — those fields belong in the Network Map tab which has the full subnet workflow.
- Networks tab now shows: Network Name, VLAN ID, Type, VMs, Tenants — pure discovery/inventory view.
- Added a note pointing users to the Network Map tab for all editing.

### Fixed — "none" network row in Network Map

- RVTools writes the literal string `"none"` when a VM NIC has no network assigned. These were being imported into the network map as a source network named `"none"` and generating spurious gaps.
- Fixed in three places: `_parse_vnic_sheet` now stores an empty string for `raw_net.lower() == "none"`; the auto-seed query filters `AND LOWER(vm.network_name) != 'none'`; and a DB cleanup statement deletes any existing `"none"` rows on list load.

### Fixed — Network gaps not auto-resolving when mappings are confirmed

- The gap analysis engine compared raw VMware source network names against PCD network names — they never match since PCD uses the mapped target names. Confirming a network mapping had no effect on gap status.
- Added network gap auto-resolve in both `run_pcd_gap_analysis` (post-insert) and `get_pcd_gaps` (on every panel load):
  - Resolves any `network` gap whose `resource_name` matches a confirmed row in `migration_network_mappings`.
  - If **all** network mappings are confirmed → resolves all remaining network gaps (catches edge cases / stale rows).

---

## [1.35.6] - 2026-03-01

### Fixed — `'tuple' object has no attribute 'get'` in Match PCD + Gap Analysis

- `p9_common.get_session_best_scope()` returns a 5-tuple `(session, token, body, scope_mode, None)`. Both `run_pcd_gap_analysis` and `flavor_staging_match_from_pcd` assigned the whole tuple to `session`, which was then passed to `nova_flavors(session)` → `paginate(session, ...)` → `session.get(url)` → crash.
- Fixed by unpacking: `session, *_ = p9_common.get_session_best_scope()` in both endpoints.

### Fixed — React key warning in PcdReadinessView gaps table

- `gaps.map(g => <tr key={g.id}>…)` — if a gap row has no `id` (e.g. freshly created before DB round-trip), `key=undefined` triggers a React duplicate-key warning. Changed to `gaps.map((g, gi) => <tr key={g.id ?? \`gap-${gi}\`}>…)` so every row always has a unique key.

---

## [1.35.5] - 2026-03-01

### Fixed — p9_common not found in API container

- **Root cause**: Docker build context for `pf9_api` was `./api/`, so `p9_common.py` (in the project root) was never copied into the image. Any endpoint that called `import p9_common` — including `GET /pcd-live-inventory`, `POST /pcd-gap-analysis`, and the new `POST /flavor-staging/match-from-pcd` — silently failed with `ModuleNotFoundError`.
- **Fix**: Changed `docker-compose.yml` build context from `./api` to `.` (project root) with `dockerfile: api/Dockerfile`. Updated `api/Dockerfile` to `COPY api/ ./` + `COPY p9_common.py ./`. `p9_common.py` is now available at `/app/p9_common.py` inside the container.

### Fixed — React key warning in PcdReadinessView gaps detail panel

- `detailKeys.map(k => <div key={k}>…)` used the detail-key string as the React key. If two detail entries happened to share a name (e.g. both named `"value"`), or a key was an empty string, React would emit a "unique key" warning attributed to `PcdReadinessView`. Changed to `detailKeys.map((k, ki) => <div key={\`${k}-${ki}\`}>…)` so keys are always unique.

---

## [1.35.4] - 2026-03-01

### New — Flavor Staging: Match from PCD

- **"🔗 Match PCD" toolbar button** — Queries the live PCD Nova API for all existing flavors and auto-matches staged flavor shapes by `(vcpus, ram_mb)`. On a match the row is updated with `pcd_flavor_id`, `target_flavor_name` (set to the PCD name), and `confirmed = true`. Unmatched rows are left unchanged — they will be created as new flavors during PCD provisioning.
- **Disambiguation scoring** — When PCD has multiple flavors with the same cpu+ram, the best candidate is chosen by longest common-prefix scoring against the current `target_flavor_name`.
- **Status pill differentiation** — Matched rows show a blue **"✓ exists"** pill (the flavor already exists on PCD); rows confirmed manually without a PCD match show a green **"✓ new"** pill (to be created); unconfirmed rows remain **"pending"**.
- **`pcd_flavor_id` cell** — Shows a truncated UUID with 🔗 prefix when the flavor is matched to PCD, otherwise "—".
- **Result banner** — After matching, a dismissible banner reports how many shapes matched and how many are unmatched.
- New API endpoint: `POST /api/migration/projects/{id}/flavor-staging/match-from-pcd`

### Fixed — Flavor Staging F&R: Apply was a no-op

- The Find & Replace "Apply" action was silently ignored because the UI sent `{ apply: true }` but the API model field is `preview_only: bool = True`. The UI now correctly sends `{ preview_only: false }` when applying, so the rename is actually persisted.

---

## [1.35.3] - 2026-03-01

### Improved — Subnet Details: DHCP allocation pool UX

- **DHCP checkbox moved before pool fields** — Operator now sets DHCP intent first; if DHCP is disabled, the pool section is hidden entirely (no unnecessary fields).
- **Conditional DHCP Allocation Pool section** — Pool Start / Pool End are only shown (in a dedicated blue-tinted panel) when "DHCP Enabled" is checked. This makes it clear the pool is the DHCP-assigned range, and IPs outside the pool but inside the CIDR are available for static assignment.
- **Auto-clear pool on DHCP disable** — Toggling DHCP off clears the pool fields in the UI and sends `null` allocation pool values to the API on save, so the DB is not left with stale pool data.
- **Hint text** — Pool panel includes: *"The pool is the DHCP-assigned range. IPs in the subnet outside this pool remain available for static assignment (servers, VIPs, etc.)."*

---

## [1.35.2] - 2026-03-01

### Fixed — Flavor Staging: boot-volume flavor model

- **Flavor de-duplication (conceptual fix)** — VCD flavors are boot-volume flavors (disk = 0 GB); the VM's boot disk is handled as a separate volume at migration time, not baked into the flavor definition. `refresh_flavor_staging` previously grouped VMs by `(cpu, ram, disk)`, creating a separate staging row for every unique disk size (e.g., `4vCPU-8GB-300GB` and `4vCPU-8GB-500GB` were treated as two flavors). It now groups by `(cpu, ram)` only, setting `disk_gb = 0`, which correctly collapses all VMs with the same CPU/RAM into a single flavor entry regardless of disk size. This typically reduces the flavor count substantially.
- **Stale row pruning on refresh** — When re-running Refresh from VMs, any old disk-based rows (from a pre-fix refresh) are now automatically deleted so the table reflects only the correct cpu+ram shapes.
- **`source_shape` format** — Changed from `"4vCPU-8GB-300GB"` to `"4vCPU-8GB"` to match the boot-volume model.

### Fixed — Image Requirements refresh (GroupingError)

- `POST /projects/{id}/image-requirements/refresh` raised `psycopg2.errors.GroupingError: subquery uses ungrouped column "v.os_family" from outer query`. Rewrote the query to compute `os_family / vm_count` in a derived table `fam`, then the scalar subquery for `os_version_hint` references `fam.os_family` (a proper grouped value) instead of the outer alias.

### Added — Confirm All + F&R for Image Requirements

- **✓ Confirm All** — Both Flavor Staging and Image Requirements now have a "✓ Confirm All" toolbar button that bulk-confirms all pending (non-skipped) rows in a single click.
- **Find & Replace for Image Requirements** — Image Requirements toolbar now includes a 🔍 F&R panel (matching Flavor Staging's UX). Client-side: filters rows by `glance_image_name`, previews before/after, then PATCHes each matching row.

---

## [1.35.1] - 2026-03-01

### Fixed — Pre-Migration Data Enrichment: Hotfixes

- **Route ordering 405 on `/network-mappings/readiness`** — FastAPI was matching `PATCH /{mapping_id}` before `GET /readiness` because the static segment `/readiness` was registered after the parameterized route. Moved `get_network_mappings_readiness` to before the `PATCH`/`DELETE` handlers so static paths take precedence.
- **`GROUP BY` error on subnet-enriched network mappings** — `GET /projects/{id}/network-mappings` used an explicit `GROUP BY` column list that omitted the new subnet enrichment columns (`network_kind`, `cidr`, `gateway_ip`, etc.), causing a Postgres error. Replaced with `GROUP BY m.id` (valid because `id` is the primary key — covers all columns via functional dependency).
- **`dns_nameservers` type mismatch on save** — UI state held DNS nameservers as a comma-separated string but the API expects `List[str]`. `saveSubnetDetails` now splits the string into an array before PATCH.
- **Section heading** — "PCD Data Enrichment" section heading in PCD Readiness tab is now labelled "Pre-Migration Data Enrichment".
- **Network Map Kind column** — Replaced read-only pill with an inline `<select>` dropdown. Selecting Physical / L2 / Virtual now immediately PATCHes the mapping and refreshes the row; no need to open the full Subnet Details panel just to set the kind.

---

## [1.35.0] - 2026-03-01

### Added — Pre-Migration Data Enrichment

- **Network Subnet Details** — The Network Map tab now supports per-network subnet configuration:
  - New columns on `migration_network_mappings`: `network_kind` (physical_managed / physical_l2 / virtual), `cidr`, `gateway_ip`, `dns_nameservers TEXT[]`, `allocation_pool_start`, `allocation_pool_end`, `dhcp_enabled`, `is_external`, `subnet_details_confirmed`
  - New API: `GET /projects/{id}/network-mappings/readiness` — returns confirmed count, missing count, external count, ready status
  - Network Map table now shows a **Kind** pill (Physical / L2 / Virtual) per row
  - Confirmed rows show a **⚙️ Subnet** expand button; external rows show "skip (ext)"; confirmed subnets show "✓ subnet ready"
  - Expandable inline subnet panel per row: network_kind dropdown, CIDR, gateway IP, DNS nameservers, allocation pool start/end, DHCP enabled and Is External checkboxes, Save/Cancel actions
  - Toolbar now shows **🌐 Subnet Details: X/Y** readiness counter
- **Flavor Staging** — New `migration_flavor_staging` table and `FlavorStagingView` component in the PCD Readiness tab:
  - `POST /projects/{id}/flavor-staging/refresh` — queries distinct VM shapes from `migration_vms` and upserts into staging table
  - `GET /projects/{id}/flavor-staging` — returns flavors with ready_count summary
  - `PATCH /flavor-staging/{id}` — edit target_flavor_name, confirmed, skip; supports marking existing flavor by ID
  - `POST /projects/{id}/flavor-staging/bulk-rename` — find-and-replace across `target_flavor_name` with preview mode
  - UI: shape + VM count table, inline name edit, skip checkbox, per-row confirm button, F&R panel, confirmed/total badge
- **Image Requirements** — New `migration_image_requirements` table and `ImageRequirementsView` component:
  - `POST /projects/{id}/image-requirements/refresh` — queries distinct `os_family` from `migration_vms`, upserts with most-common version hint
  - `GET /projects/{id}/image-requirements` — list
  - `PATCH /image-requirements/{id}` — set `glance_image_id`, `glance_image_name`, `confirmed`
  - UI: OS family + version hint + VM count table, inline Glance name and UUID inputs, confirm button, ready badge
- **Per-Tenant User Definitions** — New `migration_tenant_users` table, `TenantUsersView` component, and "👤 Users" tab:
  - `POST /projects/{id}/tenant-users/seed-service-accounts` — auto-creates one `service_account` entry per tenant with `svc-mig-{slug}` username and a 20-char random `temp_password`
  - `GET /projects/{id}/tenant-users` — grouped-by-tenant listing with confirmed_tenant_count
  - `POST /projects/{id}/tenant-users` — create a `tenant_owner` record
  - `PATCH /tenant-users/{id}` — edit username / email / role / confirmed
  - `DELETE /tenant-users/{id}` — remove owner record (service accounts cannot be deleted)
  - UI: Users tab, tenant-grouped table with type badge (🤖 svc / 👤 owner), inline edit, ✓ confirm button, seed-service-accounts action, confirmed-tenants counter

### Infrastructure
- **`db/migrate_phase4_preparation.sql`** — Idempotent migration file for all pre-migration data enrichment schema additions (subnet columns, flavor_staging, image_requirements, tenant_users tables). Auto-applied on startup; also registered in `deployment.ps1`.
- **`deployment.ps1`** — Added `migrate_phase4_preparation.sql` to `$provisioningMigrations` array.

---

## [1.34.2] - 2026-03-01

### Added
- **Multi-network provisioning DB persistence** — `provisioning_jobs` now stores the full network configuration and results:
  - New `networks_config JSONB` column: the complete list of `NetworkConfig` objects as submitted in the provision request (kind, vlan_id, subnet_cidr, physical_network, etc.)
  - New `networks_created JSONB` column: ordered list of networks actually created with their OpenStack IDs, kind, VLAN, subnet, and gateway — persisted on `completed` update for full audit trail
  - `db/migrate_provisioning_networks.sql` migration applied automatically on startup via `_ensure_tables()` column check
  - `db/init.sql` and `db/migrate_provisioning.sql` updated with both columns; legacy single-network columns retained for backward compatibility
- **Provisioning Tools → Networks: Physical Managed & Physical L2 create** — The Provisioning Tools Networks create form now supports three network kinds:
  - **☁️ Virtual** (existing behaviour — standard tenant network)
  - **🔌 Physical Managed** — provider network with `external=True`; requires Physical Network name and Provider Type (VLAN/Flat); optional VLAN ID; optional subnet
  - **🔗 Physical L2 (Beta)** — provider network with `external=False`; no subnet provisioned; note shown in UI
  - Kind selector toggles additional fields (physical network, provider type, VLAN ID) and removes subnet field for L2
  - Sends `network_type`, `physical_network`, `segmentation_id` to the existing `POST /api/resources/networks` endpoint (backend already supported these via `CreateNetworkRequest`)

### Fixed
- **VLAN ID naming bug** — Typing a multi-digit VLAN ID (e.g. "559") in Customer Provisioning now correctly derives the full name. Root cause: the `if (!net.name)` guard in the VLAN `onChange` handler blocked name updates after the first keypress because the name became non-empty. Fix: replaced two sequential `updateNetwork` calls with a single atomic `setForm` update that always derives the name from the current VLAN value
- **Network naming conventions** — All three provisioned network kinds now use `domain_name` as prefix and follow the correct convention:
  - Physical Managed → `<domain_name>_tenant_extnet_vlan_<id>` / `<domain_name>_tenant_extnet`
  - Physical L2 → `<domain_name>_tenant_L2net_vlan_<id>` / `<domain_name>_tenant_L2net`
  - Virtual → `<domain_name>_tenant_virtnet` / `<domain_name>_tenant_virtnet_<N>` (N = count for 2nd+)
  - `addNetwork()` now auto-names on creation; `makeNetworkEntry()` receives `domain_name` and current network list at call time
- **Welcome email: multi-network template** — The `customer_welcome.html` Network Configuration section now loops over `networks_created` list (replaces single-network variables):
  - Shows all networks with kind badge (Physical Managed / Physical L2 / Virtual), provider type, VLAN ID, physical network, subnet CIDR, gateway IP, DNS nameservers
  - Layer 2 networks display a "no subnet provisioned" note
  - Section header shows total network count with correct singular/plural
  - Password field was already correct; no change needed

### Changed
- `provisioning_routes.py` INSERT: saves `networks_config` (full request list as JSONB); populates legacy `network_name`/`vlan_id`/etc. columns from the first network entry for backward compatibility
- `provisioning_routes.py` UPDATE on complete: persists `networks_created` JSONB; legacy `network_id`/`subnet_id` populated from first created network
- `deriveNetworkName()` kept as legacy alias for backward-compat references; new `deriveNetName(kind, domainName, vlanId, virtIdx)` handles all three kinds

## [1.34.1] - 2026-02-28

### Fixed
- **Cohort-scoped wave building** — `auto_build_waves` now calls `build_wave_plan()` once per cohort (in `cohort_order` sequence) when multiple cohorts exist. Previously, all VMs from all cohorts were merged into a single pool and waves were built without cohort affinity. Each wave is now tagged with its source `cohort_id`. Unassigned VMs (not in any cohort) are handled as a final "Unassigned" group. Preview table shows a **Cohort** column and cohort count badge when multiple cohorts are present.
- **Wave naming clarity in `pilot_first` strategy** — Pilot wave name now uses the cohort name as prefix (e.g. `🧪 🚀 Main`) so each cohort's pilot is uniquely identifiable. Regular waves are numbered from 1 independently of the pilot slot (`🚀 Main 1`, `🚀 Main 2`, …).
- **`risk_category` column name** — VM SQL queries now use `v.risk_category AS risk_classification` consistently; previously referenced the non-existent column `v.risk_classification`.
- **`migration_wave_vms.vm_name` NOT NULL violation** — Both `auto_build_waves` and `assign_vms_to_wave` routes now build a `vm_name_map` before INSERT and pass `vm_name` in every row. ON CONFLICT uses the correct partial unique index `(project_id, vm_id) WHERE vm_id IS NOT NULL`.
- **`RealDictCursor.fetchone()[0]` TypeError** — The `COALESCE(MAX(wave_number),0)` scalar query now uses a plain `conn.cursor()` instead of `RealDictCursor` so `[0]` indexing works correctly.
- **`user.get()` AttributeError on Pydantic v2 `User` model** — All activity-log calls in wave routes replaced `user.get("username", "?")` with `getattr(user, "username", "?")`.
- **`"order"` column on `migration_cohorts`** — Cohort ordering query now uses the actual column name `cohort_order` instead of `"order"`.
- **Double emoji in cohort badges** — Cohort names already carry emoji; removed the extra hardcoded `📦` prefix from the preview table cohort column and wave card header badges.

## [1.34.0] - 2026-02-28

### Added
- **Phase 3 — Migration Wave Planning** — Full wave lifecycle from planning through completion, scoped within cohorts.
  - **`db/migrate_wave_planning.sql`** — Extends `migration_waves` (adds `cohort_id` FK, `status` with CHECK constraint, `wave_type`, `agent_slots_override`, `scheduled_start/end`, `owner_name`, `notes`, `started_at`, `completed_at`) and `migration_wave_vms` (adds `vm_id` FK with UNIQUE, `migration_order`, `assigned_at`, `wave_vm_status`). Creates new `migration_wave_preflights` table.
  - **`build_wave_plan()` engine** — Five auto-build strategies: `pilot_first` (safest VMs in Wave 0), `by_tenant` (one wave per tenant), `by_risk` (GREEN → YELLOW → RED), `by_priority` (tenant migration priority order), `balanced` (equal disk GB per wave). Dependency-graph cross-wave violation warnings. Returns wave plan with risk distribution, disk totals, and tenant lists.
  - **`PREFLIGHT_CHECKS` constant** — 6 pre-flight checks with severity levels (blocker/warning/info): network_mapped, target_project_set, vms_assessed, no_critical_gaps, agent_reachable, snapshot_baseline.
  - **11 new API routes** — `GET/POST /projects/{id}/waves`, `PATCH/DELETE /projects/{id}/waves/{wid}`, `POST .../assign-vms`, `DELETE .../vms/{vm_id}`, `POST .../advance`, `POST /auto-waves` (dry-run support), `GET/PATCH .../preflights/{check_name}`, `GET /migration-funnel`.
  - **Wave status lifecycle with transitions** — `planned → pre_checks_passed → executing → validating → complete / failed / cancelled` with `started_at`/`completed_at` timestamps.
  - **🌊 Wave Planner UI sub-tab** — Full `WavePlannerView` React component: VM migration funnel progress bar, cohort filter, auto-build panel (strategy picker with descriptions, max VMs/wave slider, pilot count, dry-run preview table + apply), wave cards with type/status badges, pre-flight checklist (pass/fail/skip per check), VM list table, advance-status buttons, delete (planned-only).

## [1.33.0] - 2026-02-28

### Added
- **Cohort-Sequential Daily Scheduler** — Daily migration schedule is now fully cohort-aware. The scheduler processes each cohort as a sequential block (using `itertools.groupby`) so cohorts never mix within a day. Each cohort starts on a fresh day and exhausts completely before the next cohort begins. Engine: `generate_migration_plan()` in `migration_engine.py`.
- **`cohort_schedule_summary` in export-plan response** — `GET /projects/{id}/export-plan` now returns a `cohort_schedule_summary` list: `[{cohort_name, start_day, end_day, duration_days, vm_count}]` for the Cohort Execution Plan table.
- **📦 Cohort Execution Plan table in Migration Plan tab** — New summary table displayed above the per-tenant breakdown, showing each cohort's start day, end day, duration, and VM count from `cohort_schedule_summary`.
- **Migration Plan: cohort-grouped tenant table** — The per-tenant assessment table is now grouped by cohort with `📦 Cohort N — Name` header rows and subtotal rows (tenants, VMs, hours) per cohort group.
- **Daily Schedule: cohort separator rows + Cohort(s) column** — Full-width `📦 Cohort Name` separator rows appear at cohort transitions in the daily schedule table. Each day row has a new "Cohort(s)" column.
- **What-If Estimator: two-model comparison** — The What-If estimator now shows two independent models side-by-side per cohort:
  - **BW Days** (bandwidth / transfer model) — formula: `effMbps = bw × 0.75; transferH = (diskGb × 1024 × 8) / (effMbps × 3600) × 1.14; cutoverH = tenants × 0.25 / agentSlots; bwDays = totalH / hoursPerDay`
  - **Sched. Days** (VM-slots model) — `schedDays = vm_count / effectiveVmsPerDay`; mirrors the backend scheduler exactly
- **What-If: project deadline check banner** — Green/red banner compares both BW Days and Sched. Days against the project's `migration_duration_days`; turns red if either model exceeds the configured duration.
- **Cohort card: expandable tenant list** — Each cohort card has a `▾ N Tenants` toggle that expands inline to show all assigned tenants with ease score badges and a **Move to…** cohort dropdown for immediate reassignment.

### Fixed
- **What-If formula: transferH 1000× too small** — `3_600_000` ms divisor corrected to `3_600` s; estimated transfer hours were 1000× underestimated before this fix.
- **`migration_cohorts` not deleted on Clear RVTools** — `DELETE /projects/{id}/rvtools` (Clear RVTools Data) now includes `migration_cohorts` in its table purge list. Ghost cohort shells no longer survive a data clear.
- **`migration_cohorts` not deleted on re-upload** — RVTools re-import now deletes `migration_cohorts` before re-ingesting data (clean slate). Previously cohort assignments silently persisted after re-upload.
- **export_migration_plan missing cohort context** — SQL now JOINs `migration_cohorts` to supply `cohort_name` and `cohort_order` per tenant; ORDER BY `cohort_order NULLS LAST, vm_count DESC`.

### Changed
- **What-If: bandwidth range extended to 100 Gbps** — Slider max raised from 10 Gbps to 100 Gbps; a free-form number input is added alongside the slider for direct value entry.
- **What-If: ⓘ tooltips on Bandwidth and Agent Slots** — Tooltip labels explain what each parameter controls (shared pipe vs parallelism).
- **`project` prop added to CohortsView** — Required to supply `migration_duration_days` to the deadline check banner.
- **`tenant_plans` sorted by cohort order** — `generate_migration_plan()` sorts `tenant_map.values()` by `(cohort_order or 9999, -vm_count)` so plans are output in cohort sequence.
- **VM sort key includes cohort** — VMs are sorted by `(cohort_order or 9999, tenant_name, priority, -disk_gb)` at the start of scheduling.

## [1.32.1] - 2026-02-28

### Changed
- **Smart Auto-Assign panel — Ramp Profile mode** — New **Uniform / Ramp Profile** toggle replaces the single "Target Cohorts N" field. Ramp mode lets you define named cohorts each with their own VM cap (e.g. 🧪 Pilot: 10 VMs → 🔄 Wave 1: 50 VMs → 🚀 Wave 2: unlimited). Four quick-presets: Pilot → Bulk, 3-Wave, 4-Wave, 5-Wave. Rows can be renamed, re-capped, added, or removed inline.
- **Strategy tooltips + descriptions** — Every field label now has an `ⓘ` tooltip. A plain-English description of the selected strategy appears directly below the dropdown so operators understand the distribution logic before previewing.
- **Unassigned pool bar** — A visual easy/medium/hard distribution bar shows the current unassigned tenant pool composition before any preview is run.
- **Preview table — Avg Ease column** — The post-preview cohort summary table now includes an Avg Ease column (colour-coded green/amber/red) alongside Tenants, VMs, Disk, and Avg Risk.
- **Apply locked until Preview** — Apply button is disabled and labelled "locked until Preview" until a preview has been run, preventing accidental commits.
- **Backend: `cohort_profiles` parameter** — `AutoAssignRequest` now accepts an optional `cohort_profiles: [{name, max_vms}]` list. When present, the engine uses per-cohort VM caps and the profile names for cohort creation. The `_format_auto_assign_result` helper now also returns `avg_risk` in each cohort summary row.

## [1.32.0] - 2026-02-28

### Added
- **Phase 3.0 — Smart Cohort Planning** — Full implementation of the Tenant Ease Score system and intelligent cohort auto-assignment.
  - **Tenant Ease Score engine** (`migration_engine.py`) — Computes an 8-dimension difficulty score per tenant: disk used, avg risk, unsupported OS ratio, VM count, network count, cross-tenant dependencies, cold-VM ratio, and unconfirmed network mappings. Each dimension is weighted (configurable) and normalised to 0–100 (lower = easier).
  - **6 Auto-Assign strategies** — `easiest_first`, `riskiest_last`, `pilot_bulk`, `balanced_load`, `os_first`, `by_priority`. Guardrails: max VMs/cohort, max disk TB, max avg risk %, min OS support %, pilot cohort size.
  - **`GET /api/migration/projects/{id}/tenant-ease-scores`** — Returns per-tenant ease score with dimension breakdown and label (Easy / Medium / Hard).
  - **`POST /api/migration/projects/{id}/cohorts/auto-assign`** — Runs the selected strategy with guardrails; supports `dry_run: true` preview before committing. Creates missing cohorts when `create_cohorts_if_missing: true`.
  - **Tenants tab — Ease column** — New sortable `Ease ↓` column with colour-coded badge (green/amber/red). Click opens a per-dimension breakdown popover.
  - **Cohorts tab — Smart Auto-Assign panel** — Collapsible panel with strategy picker, target cohort count, and 5 guardrail sliders. Preview button shows a per-cohort summary table before committing.
  - **Cohorts tab — Enhanced cohort cards** — Each card now shows `Avg Ease`, `Total Disk`, `Avg Risk`, and a mini difficulty distribution bar (easy/medium/hard breakdown).
  - **Cohorts tab — What-If Estimator** — Collapsible estimator with bandwidth (Mbps) and parallel agent slot sliders. Computes estimated migration hours and 8 h/day working days per cohort using member ease-score disk data.

## [1.31.11] - 2026-02-27

### Fixed
- **VLAN ID not editable in Networks tab** — The Networks tab edit row showed VLAN ID as static text (no input). Added a number input for VLAN ID to the edit row; `vlan_id` added to the API allowlist for `PATCH /networks/{id}` (was silently ignored).
- **VLAN ID not editable on unconfirmed Network Map rows** — The VLAN input only appeared when a row was already in local edit mode (via ✏️ Edit). Unconfirmed rows showing the orange Confirm button had a static VLAN column. Now the VLAN input is shown for all rows in the Network Map that are either in edit mode or unconfirmed, so it's always accessible before confirming.

## [1.31.10] - 2026-02-27

### Fixed
- **VLAN ID editable on network map rows** — The VLAN ID column was read-only with no way to manually fill in a missing value. Clicking **✏️ Edit** (or typing in the network name input) now also activates a number input for VLAN ID in the same row. The VLAN is included in the PATCH on Save/Confirm. Initialized to the current value so existing VLANs are not accidentally cleared.

## [1.31.9] - 2026-02-27

### Added
- **Domain Desc. auto-seeded from Domain Name** — When tenants are first seeded from RVTools data, `target_domain_description` is now pre-populated from `target_domain_name` (the tenant/org name), matching the same behaviour as Project Description. Operators can keep, edit, or clear it in the inline edit row.
- **Find & Replace extended to all 4 target fields** — The Tenants F&R panel now covers all four editable target fields: **Target Project Name**, **Project Description**, **Target Domain Name**, and **Domain Description** (previously only the first two were available). The API `bulk-replace-target` endpoint now accepts `target_display_name` and `target_domain_description` in addition to the existing name fields.

### Fixed
- **Network Map single-row edit restored** — The `✏️ Edit` button on confirmed network mapping rows no longer makes an API call to un-confirm the row. Clicking **✏️ Edit** now enters a purely local edit mode — the input field activates and **Save** + **✕ Cancel** buttons appear. The save writes the new value (with `confirmed=true`) only when the operator explicitly clicks Save. Also fixed a latent bug where clicking Confirm on an unedited unconfirmed row would send `null` as the target network name, clearing it.

## [1.31.8] - 2026-02-27

### Fixed
- **Network mappings not cleared on "Clear RVTools Data"** — The `DELETE /rvtools` endpoint ("Clear RVTools Data" button) was missing `migration_network_mappings` from its table purge list. Confirmed mappings silently survived a clear + re-upload, causing stale confirmed state to persist. Now included in the clear.

### Changed
- **Network Map re-edit UX** — Confirmed rows in the Network Map no longer show a useless greyed-out `✓` button that looks like a disabled status indicator. They now show an explicit **✏️ Edit** button that un-confirms the row (sets `confirmed=false`), making the orange **Confirm** button reappear so the operator can re-edit and re-confirm cleanly.

## [1.31.7] - 2026-02-27

### Fixed
- **Stale network mappings on re-upload** — When RVTools data was deleted and re-uploaded, network mappings (including confirmed ones) for networks that no longer exist in the new VM data were silently retained. On each upload, mappings for source networks not present in the new VM dataset are now deleted automatically.

### Added
- **Proj. Desc. auto-seeded from Project Name** — When tenants are first seeded from RVTools data, `target_display_name` (Project Description) is now pre-populated from `target_project_name` as a starting-point hint. Operators can keep, edit, or clear it.
- **Domain Description field** — PCD Domains have a description field just like Projects. Added `target_domain_description` column to `migration_tenants`. Exposed as "Domain Desc." column in the Tenants table (editable inline). DB migration: `db/migrate_descriptions.sql`. Columns and order: Target Domain → Domain Desc. → Target Project → Proj. Desc.

## [1.31.6] - 2026-02-27

### Added
- **Confirm All for tenant target names** — New ✓ Confirm All button in the Tenants tab toolbar. One-click marks all unconfirmed tenant target names (`target_confirmed=true`) after a confirmation prompt. Reports how many rows were affected. New API endpoint: `POST /projects/{id}/tenants/confirm-all`.
- **Confirm All for network mappings** — New ✓ Confirm All button in the Network Map tab toolbar. One-click marks all unconfirmed network mappings (`confirmed=true`) after a confirmation prompt. New API endpoint: `POST /projects/{id}/network-mappings/confirm-all`.

## [1.31.5] - 2026-02-27

### Added
- **Find & Replace for network target names** — New 🔍 Find & Replace panel in the Network Map tab toolbar. Allows mass-edit of `target_network_name` across all network mappings using the same literal-substring preview/apply pattern as the Tenants tab. Supports case-insensitive matching (default), an "Unconfirmed rows only" scope filter, and a scrollable preview table showing Source Network / Before / After before committing. After applying, changed rows are marked `confirmed=false` for operator review. New API endpoint: `POST /projects/{id}/network-mappings/bulk-replace`.

## [1.31.4] - 2026-02-27

### Fixed
- **Find & Replace `loadTenants` scope error** — `runFindReplace` inside `TenantsView` was calling `loadTenants()` which is defined in the parent component and not in scope. Fixed to call `onRefresh()` (the existing prop already wired to `loadTenants` + `loadStats`).

## [1.31.3] - 2026-02-27

### Added
- **Find & Replace for target names** — New 🔍 Find & Replace panel in the Tenants tab toolbar. Allows mass-edit of `target_project_name` (OrgVDC) or `target_domain_name` (Org) across all tenants using literal substring search and replace. Supports case-insensitive matching (default), an "Unconfirmed rows only" scope filter, and a Preview mode that shows the before/after for every affected row before committing. After applying, changed rows are marked `target_confirmed=false` so operators review the result. New API endpoint: `POST /projects/{id}/tenants/bulk-replace-target`.

## [1.31.2] - 2026-02-27

### Fixed
- **Cohorts tab 500 error** — `list_cohorts` and `get_cohort_summary` queries were referencing non-existent columns `allocated_vcpu`, `allocated_ram_gb`, `allocated_disk_gb` on `migration_tenants` and `migration_vms`. Fixed to use actual column names: `total_vcpu`, `total_ram_mb / 1024.0`, `total_disk_gb` (tenants) and `cpu_count`, `ram_mb / 1024.0` (VMs).
- **Target mapping logic** — Tenant detect-upsert now seeds `target_project_name = org_vdc` (the vCloud OrgVDC maps to a PCD Project), while `target_domain_name = tenant_name` (the vCloud Organization maps to a PCD Domain). Previously both were set to `tenant_name`. DB migration updated 120 existing rows. For non-vCloud tenants with no OrgVDC, both names fall back to `tenant_name`.
- **Duplicate React key warning** — VM filter tenant dropdown was using `t.tenant_name` as `key`, causing duplicate-key warnings when the same organization has multiple OrgVDC entries (e.g. `Autosoft2` × 4). Fixed to use `t.id` (unique DB PK).
- **VLAN ID auto-populated** — Network mappings `vlan_id` column is now set on INSERT (auto-seed) and on backfill for existing rows, by parsing the VLAN number from the source network name (e.g. `Amagon_vlan_3283` → 3283). 116 existing rows backfilled. Pattern: `[Vv][Ll][Aa][Nn][_-]?[0-9]+`.

### Added
- **Per-cohort schedule overrides** — `migration_cohorts` gains two new columns: `schedule_duration_days INTEGER` (planned working days for this cohort) and `target_vms_per_day INTEGER` (overrides the project-level VMs/day setting for wave planning). Both exposed in the Create Cohort form and displayed on cohort cards (⏱ N days · ⚡ N VMs/day). API models updated accordingly.

## [1.31.1] - 2026-02-27

### Fixed
- **Target name pre-seeding + confirmed flags** — Network mappings and tenant target names are now auto-seeded from the source name (best-guess default) rather than left blank. Both tables gain a `confirmed` flag: `migration_network_mappings.confirmed` and `migration_tenants.target_confirmed`. DB migration `db/migrate_target_preseeding.sql` adds the columns and pre-seeded 122 existing tenant rows with `target_domain_name = target_project_name = tenant_name, confirmed=false`.
- **Readiness checks updated** — `target_mapped` now returns `pending` (not `fail`) when names are auto-seeded but not yet confirmed; `network_mapped` returns `pending` (not `fail`) while unreviewed networks exist. This prevents false alarms before any operator action.
- **Unmapped → Unconfirmed rename** — `unmapped_count` response field on the network mappings endpoint renamed to `unconfirmed_count`; counts rows where `confirmed=false`. UI state, banner, and status column updated to match.
- **Network Map UI action button** — Shows **Confirm** (auto-seeded, unedited), **Save** (edited/dirty), or **✓** (confirmed and clean). Unconfirmed rows highlighted amber (`#fffbeb`) with ⚠️ badge. Clicking Save or Confirm sends `confirmed: true` to the API.
- **Tenant target review badges** — `target_domain_name` and `target_project_name` columns show an orange ⚠️ icon when `target_confirmed=false`; disappears after the operator saves the tenant row.
- **Tenant detect-upsert is non-destructive** — The `ON CONFLICT DO UPDATE` clause does **not** overwrite `target_domain_name`, `target_project_name`, or `target_confirmed`, so re-running tenant detection never loses operator edits.

## [1.31.0] - 2026-02-27

### Added
- **Migration Cohorts (Phase 2.10G)** ⭐ — Split large projects into independently planned, ordered workstreams. Each cohort has its own schedule, owner, dependency gate, and tenant/VM scope. Auto-assign strategies: by priority, by risk, or equal split. Full CRUD + tenant assignment panel + cohort summary rollup. New `🗃️ Cohorts` sub-tab in SourceAnalysis.
- **Source → PCD Network Mapping (Phase 2.10F)** — New `migration_network_mappings` table and `🔌 Network Map` sub-tab. Auto-seeds from distinct `network_name` values in VM data on load. Editable target network per source network with ⚠️ unmapped-count banner. `GET/POST/PATCH/DELETE /projects/{id}/network-mappings`.
- **VM Dependencies (Phase 2.10E)** — Annotate "VM A cannot start until VM B completes". Circular-dependency validation at API level. Shown as dependency badges in expanded VM row. `GET/POST/DELETE /projects/{id}/vm-dependencies`.
- **Per-VM Migration Status (Phase 2.10B)** — `migration_status` column on `migration_vms` (`not_started|assigned|in_progress|migrated|failed|skipped`). Colour-coded pill column in VM table. Single and bulk update endpoints. Status dropdown in expanded VM row.
- **Per-VM Migration Mode Override (Phase 2.10C)** — `migration_mode_override` column on `migration_vms` (`warm|cold|null`). Operator can force warm/cold regardless of engine classification. 🔒 icon on VM row when override is active. Override dropdown in expanded VM row. `PATCH /projects/{id}/vms/{vm_id}/mode-override`.
- **Tenant Migration Priority (Phase 2.10D)** — `migration_priority INTEGER DEFAULT 999` on `migration_tenants`. Editable number field in Tenants tab. Sortable priority column. Used by cohort auto-assign. `migration_priority` added to `PATCH /tenants/{id}` request model.
- **Per-Tenant Readiness Checks (Phase 2.10H)** — 5 auto-derived checks per tenant: `target_mapped`, `network_mapped`, `quota_sufficient`, `no_critical_gaps`, `vms_classified`. Results persisted to `migration_tenant_readiness` table. Readiness score button in Tenants tab. Cohort-level readiness summary endpoint.
- **DB Migration** — `db/migrate_cohorts_and_foundations.sql` (idempotent): 4 new tables (`migration_cohorts`, `migration_vm_dependencies`, `migration_network_mappings`, `migration_tenant_readiness`), 5 new columns on `migration_vms`, 2 new columns on `migration_tenants`, 12 indexes.
- **17 new API endpoints** added to `api/migration_routes.py` — VM status (×3), VM mode override (×1), VM dependencies (×3), network mappings (×4), cohorts (×7 incl. auto-assign + readiness summary), tenant readiness (×2). Total migration endpoints: 45+.

## [1.30.1] - 2026-02-27

### Changed
- **Node sizing uses actual VM performance data** — `GET /projects/{id}/node-sizing` now queries `cpu_usage_percent` and `memory_usage_percent` per VM (stored by the RVtools v1.28.3 parser) instead of `SUM(cpu_count) / overcommit_ratio`. Actual physical demand is `SUM(cpu_count × cpu_usage_percent/100)` — this is already physical scheduler load, so no overcommit division is applied. For the PoC cluster: 324 powered-on VMs, 100% performance data coverage, actual demand = **125 vCPU / 622 GB RAM** vs 1,371 vCPU / 4,616 GB allocated. Result: **+2 new nodes needed (6 total)** at 70% cap with 15% peak buffer vs the previous incorrect +9 (13 total).
- **Three-tier basis selection** — (1) `actual_performance` when ≥50% of powered-on VMs have `cpu_usage_percent`; (2) `allocation` fallback: allocation ÷ overcommit ratio; (3) `quota` last-resort when no RVtools VM data exists. Basis and perf coverage percentage are returned in the API response.

### Added
- **Sizing basis badge in Capacity tab** — Green pill "📊 Based on actual VM performance data · {N}% VM coverage · {actual} vCPU running of {alloc} allocated · {active} GB active of {alloc_gb} GB allocated" or amber pill "⚠️ Based on vCPU allocation ÷ overcommit (no performance data)" shown below the resource comparison table.
- **New fields on `SizingResult`** — `sizing_basis`, `perf_coverage_pct`, `vm_vcpu_alloc`, `vm_ram_gb_alloc`, `source_node_count` added to both backend response and TypeScript interface.
- **HW Demand tooltip and footnote** updated to conditionally explain the calculation basis (actual utilisation formula vs allocation ÷ overcommit formula).

## [1.30.0] - 2026-02-27

### Added
- **Auto-Detect PCD Node Profile** — New `GET /api/migration/projects/{id}/pcd-auto-detect-profile` endpoint queries the `hypervisors` inventory table to identify the dominant compute node type (most common vCPU + RAM configuration). Returns a ready-to-use node-profile suggestion with `cpu_cores`, `cpu_threads`, `ram_gb`, `storage_tb`. The Capacity tab now has a **🔍 Auto-Detect from PCD** button that fetches the dominant node type and pre-fills the new-profile form — no manual node spec entry needed for environments with inventory sync active.
- **Gap Analysis Action Report** — New `GET /api/migration/projects/{id}/export-gaps-report.xlsx` and `GET /api/migration/projects/{id}/export-gaps-report.pdf` endpoints generate a downloadable PCD Readiness action report. Excel: 3 sheets — Executive Summary (readiness score, gap counts by severity, gap-type breakdown), Action Items (unresolved gaps with step-by-step remediation instructions and effort estimate, sorted critical-first), All Gaps (full list including resolved). PDF: landscape A4 with colour-coded severity rows and the same structure. Download buttons appear in the PCD Readiness tab gaps section.
- **`generate_gaps_excel_report()`** and **`generate_gaps_pdf_report()`** added to `api/export_reports.py` (~250 lines).

### Fixed
- **PDF & Excel plan export broken** — `downloadXlsx()` and `downloadPdf()` in `MigrationPlanView` were using direct `<a href>` navigation which does not include the `Authorization: Bearer` token, causing the request to fail or redirect to a login/error page. Replaced both with a new `downloadAuthBlob()` helper that uses `fetch()` with the auth header → `Response.blob()` → `URL.createObjectURL()` → programmatic click. Downloads now work correctly for all authenticated sessions.
- **Risk breakdown hidden** — VM expanded detail row now shows an **⚠️ Risk Factors** section listing each rule that fired during risk assessment (e.g., "Large disk: 2400 GB (≥ 2000 GB) (+10)"). Data was already stored in `migration_vms.risk_reasons JSONB` and returned by `GET /vms` — only the UI display was missing. Added `risk_reasons?: string[]` to the `VM` TypeScript interface and rendered as a styled list below the disk/NIC tables in the expanded row.

## [1.29.7] - 2026-02-26

### Fixed
- **Node sizing incorrectly driven by Cinder disk** — The `compute_node_sizing` engine was computing `nodes_for_disk` and taking `max(nodes_for_cpu, nodes_for_ram, nodes_for_disk)`. Cinder block storage is independent infrastructure (Ceph, SAN, NFS) and has nothing to do with the number of compute (hypervisor) nodes. Node count is now driven by **vCPU and RAM only**. Disk is reported as a separate `disk_tb_required` figure with a note to provision via the storage backend. This is why the previous calculation was showing 21 nodes for a workload that only needs ~3–4 compute nodes for CPU/RAM. The UI now shows post-migration utilisation for CPU and RAM only, with Cinder storage requirement as a separate informational line.

## [1.29.6] - 2026-02-26

### Fixed
- **Node sizing ignores actual PCD cluster capacity** — New `GET /projects/{id}/pcd-live-inventory` backend route queries the `hypervisors` table (populated by pf9_rvtools.py) to return live node count, total vCPU/RAM, and currently committed resources from `servers` + `flavors` + `volumes` tables. The Capacity tab now shows a **Live PCD Cluster** panel auto-loaded from this real data, with a **📥 Sync to Inventory** button that pre-fills all four inventory fields (nodes, vCPU used, RAM used, disk used). The PCD Readiness capacity card shows whether the node count came from the inventory DB or a manual entry, and warns if they differ.
- **Save Inventory / Compute Sizing not updating results** — "Save Inventory" only sent `current_nodes` and did not re-trigger sizing, so the displayed result never changed after editing. `saveInventory` now sends all four fields (`current_nodes`, `current_vcpu_used`, `current_ram_gb_used`, `current_disk_tb_used`) and auto-calls `computeSizing` after a successful save. The two buttons are now **"💾 Save & Recompute"** and **"📐 Compute Only (no save)"** to make the flow obvious. The inventory load on mount now restores all four fields from the DB.
- **PCD Readiness gaps show no explanation** — The gaps table had only Type / Resource / Tenant / Severity / Resolution / Status. Added a **Why / Details** column that surfaces the key fields from each gap's `details` dict (e.g. `required vcpu: 32`, `vm count: 5`, `ram: 64 GB`, `network name: prod-vlan-42`) with an expandable list of affected VM names.
- **Inventory form missing used-resource fields** — The Node Sizing inventory form previously only had "Existing PCD nodes". It now exposes **vCPU already used**, **RAM already used (GB)**, and **Disk already used (TB)** so the engine can correctly deduct already-committed capacity before computing how many additional nodes are needed.

## [1.29.5] - 2026-02-26

### Fixed
- **Cold migration downtime calculation wrong** — `cold_downtime_hours` was equal to `cold_total_hours` (copy phase only). Cold migration keeps the VM fully offline for the entire disk copy **plus** the same boot/connect overhead as warm cutover (`warm_cutover`). Fixed: `cold_downtime_hours = cold_total + warm_cutover`.
- **Cold "Cutover/Cold" column showed `—`** — Cold migrations have the same boot/connect phase as warm (driver install, reboot, re-IP, smoke-test). The column now shows `warm_cutover_hours` for cold VMs instead of a dash.
- **PCD Readiness missing capacity section** — The PCD Readiness tab now shows a full **Capacity Assessment** panel: migration quota requirements (vCPU, RAM GB, Disk TB), PCD node profile used, nodes recommended (including HA policy N+1/N+2 and spares), existing deployed nodes, additional nodes needed (highlighted red/green), post-migration CPU/RAM/Disk utilisation %, binding dimension, and capacity warnings. Handles missing node profile gracefully with a prompt to configure one in the Capacity tab.

## [1.29.4] - 2026-02-26

### Fixed
- **Migration Plan shows excluded tenants** — `export-plan`, `export-report.xlsx`, and `export-report.pdf` routes were fetching all tenants and all VMs regardless of `include_in_plan`. All three routes now JOIN `migration_tenants` with `include_in_plan = true`, so excluded tenants and their VMs are completely omitted from the plan, the daily schedule, and all exports.
- **Project Summary excluded count** — Added `excluded_tenants` field to `project_summary`. The Migration Plan tab now shows a warning banner ("⚠️ N tenants excluded from this plan") and the Tenants stat card is relabelled "Tenants (incl.)".
- **Capacity tab requires manual sizing click** — The Capacity tab's `load()` now automatically calls `GET /node-sizing` on mount, so the node sizing result is populated from the DB without requiring the user to click "Compute Sizing".
- **PCD Readiness crash — `readinessScore.toFixed is not a function`** — PostgreSQL returns `NUMERIC` columns as strings via psycopg2; `readiness_score` was stored as a string and set directly into state. All three `setReadinessScore` calls now wrap with `Number()` to coerce to float.

## [1.29.3] - 2026-02-26

### Fixed
- **Bulk-scope 422 — route conflict** — `PATCH /tenants/{tenant_id}` was defined before `PATCH /tenants/bulk-scope`, so FastAPI/Starlette captured `"bulk-scope"` as a `tenant_id` path parameter and attempted to parse it as an integer → 422 `path.tenant_id: Input should be a valid integer`. Fixed by adding the `:int` Starlette path converter (`{tenant_id:int}`) so the parameterised route only matches integer segments, letting `bulk-scope` route correctly.
- **Capacity tab crash — overcommit profile object rendered as React child** — `compute_quota_requirements` returns `"profile": <full dict>`. The UI used `{quotaResult.profile}` in JSX and `setActiveProfile(quota.profile)` (setting state to an object), causing React to throw "Objects are not valid as a React child". Both usages now extract `profile.profile_name` when the value is an object.
- **Cold-required VMs show `—` for copy time** — The "Copy / Phase 1" column always showed a dash for cold-required VMs. For cold migrations the copy phase IS the full offline disk copy (`cold_total_hours`). Column now renders `cold_total_hours` for cold-required rows. The "Cutover / Cold" column correctly shows `—` for cold (no separate cutover step) and `warm_cutover_hours` for warm.

## [1.29.2] - 2026-02-26

### Fixed
- **Bulk-scope 422 error** — `selected` Set could contain `undefined` (for tenants loaded before the v1.29.1 `t.id` fix was applied). `JSON.stringify([undefined])` produces `[null]`, which Pydantic rejects for `List[int]`. Fixed: filter nulls from `tenant_ids` before the PATCH request. Also improved `apiFetch` error formatting to display Pydantic validation detail arrays as readable text instead of `[object Object]`.
- **Capacity tab crash — `toFixed` on undefined** — The engine returns `vcpu_alloc`, `ram_gb_alloc`, `disk_gb_alloc`, `disk_gb_recommended` but the UI read `vcpu_allocated`, `ram_gb_allocated`, `disk_tb_allocated`, `disk_tb_recommended` (field name mismatch). All four field names corrected; disk values from the engine are in GB and now converted to TB for display.
- **PCD Readiness — unnecessary connection settings form removed** — The gap analysis already falls back to global `.env` credentials (`PF9_AUTH_URL`, `PF9_USERNAME`, `PF9_PASSWORD`) when no project-level PCD URL is set. The settings form was confusing for single-cluster setups. Replaced with a simple status banner: “Using global PF9 credentials from server config (.env)”.

## [1.29.1] - 2026-02-26

### Fixed
- **Tenant checkbox selected all instead of one** — `Tenant` interface was mapped to `tenant_id` but the API returns `id` (the actual DB primary key). `tenant_id` was always `undefined`, causing `selected.has(undefined)` to behave incorrectly. All checkbox logic now uses `t.id`; the interface declares `id: number` with `tenant_id` as an optional alias.
- **Capacity tab showed blank page / `profiles.map is not a function`** — `CapacityPlanningView` was assigning full API response objects (`{status, profiles:[...]}`) directly to state. All Phase 2 API responses are now correctly unwrapped: `.profiles`, `.quota`, `.inventory.current_nodes`, `.sizing`.
- **`setProfile()` body field mismatch** — PATCH body was sending `{profile_name}` but the Pydantic model `UpdateOvercommitRequest` expects `{overcommit_profile_name}`. Corrected field name.
- **`setDefaultProfile()` called non-existent endpoint** — Was issuing `PATCH /node-profiles/{id}` which does not exist. Now correctly uses `POST /node-profiles` (upsert) with `is_default: true` on the full profile object.
- **PCD Readiness tab — blank on load** — `loadProject` was reading `p.pcd_auth_url` from the raw response but the endpoint returns `{status, project: {...}}`. Fixed to `resp.project`. `loadGaps` was similarly unwrapping `g` instead of `g.gaps` / `g.readiness_score`.
- **Duplicate React key warning (`Autosoft2`)** — All tenant `key` props were `undefined` because `t.tenant_id` was undefined; React deduplicated all rows to a single key. Fixed by using `t.id` as the unique key.
- **React Fragment key error on edit row** — The inline-edit reason `<tr>` had no `key`. Now uses an explicit `rowKey`-derived key.
- **`borderBottom` / `borderBottomColor` style conflict on sub-nav tabs** — `subTabStyle` declared `borderBottom: "2px solid transparent"` while `subTabActive` tried to override with `borderBottomColor`. CSS shorthand resets the color, so the active border never appeared. Fixed `subTabActive` to use `borderBottom: "2px solid #3b82f6"`.
- **Warm migration downtime was too high** — Downtime column was summing `warm_phase1_hours + warm_cutover_hours`. Phase 1 is a live copy with no downtime; only `warm_cutover_hours` (the incremental delta + switchover window) counts as actual downtime. Fixed.
- **Column header mislabelled** — "Warm Phase1" renamed to "Copy / Phase 1" to accurately describe the live-copy phase with no downtime.

## [1.29.0] - 2026-02-27

### Added
- **Migration Planner Phase 2: Tenant Scoping, Target Mapping & Capacity Planning**
  - **Phase 2A — Tenant Exclusion & Scoping**: per-tenant `include_in_plan` toggle; bulk-scope toolbar (select many, include/exclude); `exclude_reason` field shown inline when excluded; auto-exclude filter patterns (`GET/POST/DELETE /projects/{id}/tenant-filters`).
  - **Phase 2B — Target Mapping**: inline editing of `target_domain_name`, `target_project_name`, `target_display_name` per tenant in the Tenants view.
  - **Phase 2C — Quota & Overcommit Modeling**: three built-in overcommit presets (aggressive 8:1, balanced 4:1, conservative 2:1); quota requirements engine (`compute_quota_requirements()`) computes per-tenant and aggregate vCPU/RAM/disk needs; `GET /overcommit-profiles`, `PATCH /projects/{id}/overcommit-profile`, `GET /projects/{id}/quota-requirements`.
  - **Phase 2D — PCD Hardware Node Sizing**: node profile CRUD (`GET/POST/DELETE/PATCH /projects/{id}/node-profiles`); current-inventory tracking (`GET/PUT /projects/{id}/node-inventory`); HA-aware sizing engine (`compute_node_sizing()`) — N+1 ≤10 nodes, N+2 >10 nodes; `GET /projects/{id}/node-sizing` returns recommended node count, HA spares, binding dimension, and post-migration utilisation.
  - **Phase 2E — PCD Readiness & Gap Analysis**: PCD settings per project (`PATCH /projects/{id}/pcd-settings`); `analyze_pcd_gaps()` engine connects to PCD and checks missing flavors, networks, images, and unmapped tenants; gap table with severity (critical/warning/info) and "Mark Resolved" action (`PATCH /projects/{id}/pcd-gaps/{gid}/resolve`); readiness score (0-100).
  - **UI: ⚖️ Capacity tab** — overcommit profile cards, per-tenant quota table, node profile editor, node sizing result with utilisation gauges and HA warnings.
  - **UI: 🎯 PCD Readiness tab** — PCD connection form, one-click gap analysis, gap table with severity pills, "Mark Resolved" per row, readiness score badge.
  - **DB migration**: `db/migrate_phase2_scoping.sql` (6 new tables + columns on migration_tenants/migration_projects; idempotent).

## [1.28.3] - 2026-02-26

### Added
- **Excel report export** — New `GET /api/migration/projects/{id}/export-report.xlsx` endpoint returns a 4-sheet Excel workbook: Summary (project metadata + bandwidth model), Per-Tenant Assessment (one row per tenant, colour-coded), Daily Schedule (one row per VM per day, cold=red/risky=yellow), All VMs (full VM detail). Uses openpyxl with styled headers, alternating rows, freeze panes, and auto-filter.
- **PDF report export** — New `GET /api/migration/projects/{id}/export-report.pdf` endpoint returns a landscape A4 PDF with Project Summary table, Per-Tenant Assessment table, and Daily Schedule table. Built with reportlab; includes page footer with project name + page numbers.
- **Export buttons in UI** — Migration Plan tab now shows 5 action buttons: Refresh, Export JSON, Export CSV, **Export Excel** (blue), **Export PDF** (purple).
- **`export_reports.py`** — New backend module (~320 lines) containing `generate_excel_report()` and `generate_pdf_report()` functions.
- **reportlab dependency** — Added `reportlab>=4.0.0` to `api/requirements.txt`.

### Fixed
- **vCPU usage % was blank for all VMs** — RVTools vCPU sheet uses `overall` (MHz) and `cpus` columns instead of `% usage`. Parser now maps `overall` → `cpu_demand_mhz` and computes `cpu_usage_percent = min(demand / (cpus × 2400 MHz) × 100, 100)`.
- **vMemory usage % was blank for all VMs** — RVTools vMemory sheet uses `consumed` (MiB) and `size mib` columns. Parser now maps `consumed` → `memory_usage_mb` and computes `memory_usage_percent = consumed / size_mib × 100`.
- **Phase1 times all showing `<1min`** — `estimate_vm_time()` was multiplying `in_use_gb` by a 3–8% "compression factor" before dividing by bandwidth, giving nonsensical <1 min values for all VMs. Replaced with real-world bandwidth utilization (45–65% of raw throughput depending on VM size). Phase1 times now range ~3 min (40 GB) to ~1.5 h (1.4 TB).
- **"Clear RVTools Data" left 121 network rows** — `migration_networks` was missing from the delete loop in `clear_rvtools_data()`. Now included.
- **React key warning on tenant cards** — `key={t.tenant_id}` could be null; fallback to `t.tenant_name || idx`.

### Changed
- **MIGRATION_PLANNER_PHASES.md** — Phase 1.4 marked COMPLETE; Phase 1.5 (Report Export) added and marked COMPLETE.

## [1.28.2] - 2026-02-26

### Added
- **Expandable VM detail rows** — Click any VM row in the inventory table to expand and see per-disk and per-NIC detail tables. Disks show label, capacity (GB), thin-provisioned flag, and datastore. NICs show adapter type, network name, connection type, IP address, MAC address, and link-up status. Disk count column added to the main VM table.
- **Additional VM filters** — Three new filter dropdowns on the VM inventory: OS Family (windows/linux/other), Power State (poweredOn/poweredOff/suspended), and Cluster.
- **Migration Plan tab** — New "Migration Plan" sub-tab in Source Analysis with full migration plan generation:
  - **Project summary cards**: Total VMs, warm-eligible count, cold-required count, estimated total migration hours, project duration.
  - **Per-tenant assessment table**: Expandable rows showing each tenant's VM count, warm/cold split, aggregated phase-1 hours, cutover hours, total hours, and risk distribution (GREEN/YELLOW/RED counts).
  - **Per-VM time estimates**: Each VM row inside a tenant shows warm phase-1 time (no downtime, full in-use data copy), warm cutover time (downtime: final delta + 15 min switchover), and cold total time (full offline copy). Estimates driven by the project's bottleneck bandwidth.
  - **Daily migration schedule**: Calendar-style table showing which VMs are scheduled per day based on concurrent agent slots, with VM name pills.
  - **JSON & CSV export**: Download the full migration plan as JSON (complete structure) or CSV (flat VM-level rows with tenant, mode, phase-1 hours, cutover hours, downtime, scheduled day).
- **Per-VM time estimation engine** — New `estimate_vm_time()` function in `migration_engine.py` computes warm and cold migration durations per VM based on disk capacity, in-use data, and effective bottleneck bandwidth. Formula: `gb_per_hour = (bottleneck_mbps / 8) × 3.6`. Warm: phase-1 (full in-use copy, zero downtime) + incremental (daily delta) + cutover (half-day delta + 15 min switchover). Cold: full provisioned disk copy (all downtime).
- **Migration plan generator** — New `generate_migration_plan()` function builds per-tenant breakdowns with aggregated timing, risk distribution, and VM lists. Produces a daily schedule by filling concurrent agent slots day-by-day.
- **API: VM detail endpoint** — `GET /api/migration/projects/{id}/vms/{vm_name}/details` returns individual disk and NIC records for a specific VM.
- **API: Export plan endpoint** — `GET /api/migration/projects/{id}/export-plan` generates the full migration plan (project summary, per-tenant plans, daily schedule) using the project's bandwidth model.

### Changed
- **VM list API** — `GET /api/migration/projects/{id}/vms` now accepts `os_family` and `power_state` query parameters for server-side filtering.
- **SQL default detection config** — `migration_tenant_rules` default `detection_config` now includes `vcd_folder` as the first detection method and `cluster` as a fallback, ensuring new projects get the complete detection chain by default (previously required runtime injection).

## [1.28.1] - 2026-02-25

### Added
- **Live bandwidth constraint model** — Bandwidth cards now update instantly as you change any topology or agent field (NIC speed, usable %, storage MB/s, agent count). No save required — client-side `useMemo` mirrors the server-side engine. Shows "(live preview — save to persist)" when unsaved.
- **Migration Schedule section** — New "Migration Schedule" panel with 4 fields: Project Duration (days), Working Hours per Day, Working Days per Week, Target VMs per Day. Drives schedule-aware agent sizing recommendations.
- **Schedule-aware agent sizing** — The agent recommendation engine now factors in project timeline: computes effective working days from duration × (working days/week), derives VMs/day throughput need, and recommends appropriate agent count. Includes estimated completion time in reasoning output.
- **Cluster-based tenant detection** — New `cluster` detection method as fallback for non-vCD environments. Detection chain: vcd_folder → vapp_name → folder_path → resource_pool → cluster → Unassigned.
- **Inline tenant editing** — Each tenant row now has an edit (✏️) button. Click to edit tenant name and OrgVDC inline with keyboard support (Enter to save, Escape to cancel). Changes cascade to all associated VMs via the PATCH endpoint.

### Fixed
- **Tenant rename cascade bug** — The PATCH `/projects/{id}/tenants/{tid}` endpoint was reading the tenant name after the UPDATE (getting the new name), so the VM cascade WHERE clause never matched the old name. Now reads the old name first before updating.
- **DB migration file**: `db/migrate_migration_schedule.sql` adds 4 new columns to `migration_projects` (idempotent `ADD COLUMN IF NOT EXISTS`).

## [1.28.0] - 2026-02-25

### Added
- **Migration Intelligence & Execution Cockpit (Phase 1)** — New "Migration Planner" tab for planning and executing VMware → Platform9 PCD workload migrations via vJailbreak.
  - **15 database tables**: `migration_projects`, `migration_vms`, `migration_vm_disks`, `migration_vm_nics`, `migration_vm_snapshots`, `migration_tenants`, `migration_tenant_rules`, `migration_hosts`, `migration_clusters`, `migration_waves`, `migration_wave_vms`, `migration_risk_config`, `migration_target_gaps`, `migration_prep_tasks`, `migration_project_archives`
  - **Project lifecycle**: draft → assessment → planned → approved → preparing → ready → executing → completed/cancelled → archived. Approval gate prevents PCD writes until admin explicitly approves.
  - **RVTools XLSX import**: Upload RVTools exports and automatically parse 6 sheets (vInfo, vDisk, vNIC, vHost, vCluster, vSnapshot) with fuzzy column matching across RVTools version differences.
  - **Multi-tenant detection**: 5 detection methods (folder path, resource pool, vApp name, VM name prefix, annotation field) to auto-assign VMs to tenants.
  - **Risk scoring engine**: Configurable 0–100 risk score per VM (GREEN/YELLOW/RED) based on weighted factors (disk size, snapshot count, OS family, NIC count, etc.).
  - **Migration mode classification**: warm_eligible / warm_risky / cold_required based on OS, power state, disk count, and snapshot count.
  - **Bandwidth constraint model**: 4-constraint model (source host NIC → transport link → agent ingest → PCD storage write) with latency penalties. Identifies bottleneck automatically.
  - **3-tier topology selector**: Local (same DC), Cross-site dedicated (MPLS/dark fiber), Cross-site internet — each with configurable NIC speeds and usable % sliders.
  - **vJailbreak agent sizing**: Recommendations for agent count, vCPU, RAM, and disk based on workload profile. Agents deploy on PCD side pulling data from VMware.
  - **Three reset levels**: Re-import (replace source data), Reset assessment (clear computed scores), Reset plan (clear waves/tasks).
  - **Full RBAC**: `migration` resource with read/write/admin actions. viewer=read, operator=read, technical=read+write, admin=all, superadmin=all.
  - **Navigation integration**: "Migration Planning" nav group with department visibility for Engineering, Tier3 Support, Management, and Marketing.
  - **Frontend**: MigrationPlannerTab with 3 sub-views (Projects list, ProjectSetup, SourceAnalysis). ProjectSetup includes topology config, bandwidth sliders, agent profile, RVTools upload. SourceAnalysis includes VM inventory table with filters/sort/pagination, risk dashboard, tenant management, risk config editor.
  - **Backend**: `api/migration_engine.py` (pure logic, no HTTP/DB), `api/migration_routes.py` (25+ API endpoints)
  - **DB migration**: `db/migrate_migration_planner.sql` (idempotent, includes RBAC permissions, nav groups, department visibility)

## [1.27.0] - 2026-02-24

### Added
- **Environment Data Reset** — New "Data Reset" tab on the Admin panel (superadmin only) that lets platform administrators purge operational data for a fresh start without dropping tables or affecting Platform9 itself. Ideal for POC/demo environment refreshes.
  - **7 selectable categories**: Platform Inventory, Change History, Snapshot Operations, Logs & Audit, Metering Data, Search & Copilot, Provisioning & Runbook Ops
  - **Always preserved**: Local users & roles, departments, navigation, visibility, branding, MFA, permissions, snapshot policies, drift rules, runbook definitions, notification channels/preferences, copilot & metering config
  - Row counts per table displayed before confirmation; typed `RESET` confirmation required
  - Backend: `GET /admin/reset-data/categories` (preview with counts) and `POST /admin/reset-data` (execute purge)

## [1.26.1] - 2026-02-24

### Fixed
- **Snapshot batch progress not recording** — Fixed column name mismatches between the Python snapshot worker and the `snapshot_run_batches` DB schema (`snapshots_created` → `completed`, `snapshots_deleted` → removed, `volumes_skipped` → `skipped`, `errors` → `failed`, `completed_at` → `finished_at`). This caused the first batch-progress UPDATE to fail, which poisoned the PostgreSQL transaction and prevented all subsequent DB writes (run progress, run completion, notifications). Runs appeared stuck as "RUNNING" with 0% progress indefinitely.
- **Snapshot API batch queries** — Fixed `GET /snapshot/runs/{id}/progress` and `GET /snapshot/runs/active/progress` to SELECT the correct batch column names from `snapshot_run_batches`, preventing 500 errors when querying batch details.
- **DB error isolation** — Added `conn.rollback()` to all snapshot worker DB error handlers (`update_batch_progress`, `update_run_progress`, `finish_snapshot_run`, `record_quota_block`) so a single failed query no longer cascades and breaks subsequent database operations within the same connection.
- **Snapshot Quota Forecast runbook — `project_id` attribute error** — `Pf9Client` did not store `project_id` from the Keystone auth token response. The runbook engine referenced `client.project_id` which raised `AttributeError: 'Pf9Client' object has no attribute 'project_id'`. Fixed by extracting and storing `project_id` from the token scope during authentication, and removing a redundant fallback variable in the runbook engine.
- **Snapshot Quota Forecast — GB Used always 0** — The Cinder quota API call was missing the `?usage=true` query parameter, so only quota limits were returned (`in_use` defaulted to 0). Added the parameter to `/os-quota-sets/{project_id}?usage=true` so GB Used and Snapshots Used now report actual usage.
- **Snapshot run notifications not saving** — `send_run_completion_notification` and `send_quota_blocked_notification` were INSERTing into `notification_log` with wrong column names (the table uses an email-subscriber schema). Rewrote both functions to INSERT into `activity_log` instead, which has the correct schema for system-wide notifications (`actor, action, resource_type, resource_id, resource_name, details, result`). Added `conn.rollback()` to error handlers.
- **Admin panel — runbook execution results not visible** — The admin Runbooks tab showed execution results as collapsed raw JSON in a `<details>` block. Replaced with a structured results view: summary banner, sortable alerts table with severity-based row coloring, collapsible items/ok_projects/users/stuck_vms/orphans tables (auto-detected from result keys), and a "Raw JSON" fallback. Matches the friendly rendering already available in the user-facing Runbooks tab.

## [1.26.0] - 2026-02-24

### Added
- **Snapshot Quota-Aware Batching** — Snapshot automation now pre-checks Cinder quotas before snapshotting. Volumes that would exceed a tenant's gigabytes or snapshot count quota are flagged as `quota_blocked` and skipped instead of failing with HTTP 413 errors.
  - **Runtime quota pre-check**: Before processing each tenant's volumes, the system calls `cinder_quotas()` and compares available GB/snapshot-slots against the volumes queued for snapshot. Blocked volumes are recorded in a new `snapshot_quota_blocks` table with detail on the specific quota limit, usage, and shortfall.
  - **Tenant-grouped batching**: All volumes from the same tenant are kept in the same batch. Batches are capped at a configurable `--batch-size` (default 20 volumes) and separated by a configurable `--batch-delay` (default 5 seconds) to avoid Cinder API rate limiting with 500+ tenants.
  - **Batch progress tracking**: New `snapshot_run_batches` table records per-batch status, timing, and volume counts. The `snapshot_runs` table gains progress columns (`total_batches`, `completed_batches`, `current_batch`, `progress_pct`, `estimated_finish_at`, `quota_blocked`).
  - **Live progress API**: `GET /snapshot/runs/{id}/progress` returns batch-level detail and quota-blocked volumes. `GET /snapshot/runs/active/progress` returns the currently-running snapshot run's progress for UI polling.
  - **UI progress bar**: SnapshotMonitor now displays a real-time progress bar with batch indicators during active runs, including estimated completion time.
  - **Quota-blocked in compliance**: `GET /snapshot/compliance` now returns a `quota_blocked` status for volumes blocked by quota in the most recent run (last 48h). The compliance UI shows quota-blocked volumes with distinct orange styling and a separate summary count.
  - **Run completion notifications**: Snapshot runs now send a notification on completion summarizing created/deleted/skipped/quota-blocked/error counts, batch count, and duration. Quota-blocked volumes also trigger a separate `snapshot_quota_blocked` notification with per-tenant detail.
- **Snapshot Quota Forecast Runbook** (`snapshot_quota_forecast`, category: security, risk: low) — Proactive daily runbook that scans all projects with snapshot-enabled volumes and forecasts Cinder quota shortfalls before your next snapshot run. Flags projects where gigabytes or snapshot count quota is insufficient (with configurable safety margin). Auto-approve for all roles (read-only).
  - Parameters: `include_pending_policies` (default true), `safety_margin_pct` (default 10)
  - Result shows critical/warning alerts per project with exact shortfall amounts, plus a collapsible "OK Projects" list

### Changed
- **Snapshot Monitor table** — Added "Quota Blocked" and "Batches" columns to the run history table for v1.26.0 batch-aware runs.
- **Snapshot Excel reports** — Now include `quota_blocked`, `batches`, and `duration_seconds` fields in the Summary sheet.
- **deployment.ps1** — Added `db/migrate_snapshot_quota_batching.sql` to the migration pipeline.
- **docker-compose.yml** — Added `AUTO_SNAPSHOT_BATCH_SIZE` and `AUTO_SNAPSHOT_BATCH_DELAY` env vars to `snapshot_worker` service (defaults: 20, 5.0).
- **Runbook count** — 12 → 13 built-in runbooks (added `snapshot_quota_forecast`).

### Fixed
- **check_drift.py — Database credentials from env vars** — Replaced hardcoded database credentials with env-var lookup (`PF9_DB_PASSWORD` / `POSTGRES_PASSWORD`). Script now auto-loads `.env` file when run standalone on the host.

### Docs
- **ARCHITECTURE.md** — Snapshot Management table count 8 → 10; added `snapshot_run_batches` and `snapshot_quota_blocks` table descriptions.
- **SNAPSHOT_AUTOMATION.md** — Added 2 new tables to Database section; added 4 batching/quota feature checkmarks to Current Status; added `AUTO_SNAPSHOT_BATCH_SIZE`/`AUTO_SNAPSHOT_BATCH_DELAY` to Docker service example.
- **API_REFERENCE.md** — Documented `GET /snapshot/runs/{id}/progress` and `GET /snapshot/runs/active/progress` endpoints with response schemas; added `snapshot_quota_forecast` runbook trigger example.
- **DEPLOYMENT_GUIDE.md** — Added step 10 to migration pipeline: `db/migrate_snapshot_quota_batching.sql` (v1.26+).
- **ADMIN_GUIDE.md** — Updated runbook count 12 → 13; added Snapshot Quota Forecast to Quota category.
- **KUBERNETES_MIGRATION_GUIDE.md** — Added batching/quota features to snapshot worker description; added `AUTO_SNAPSHOT_BATCH_SIZE`/`AUTO_SNAPSHOT_BATCH_DELAY` to all three `snapshot-config` ConfigMap instances.

## [1.25.1] - 2026-02-23

### Added
- **User Last Login Report runbook** (`user_last_login`, category: security, risk: low) — Lists every active user with their last login time, last session activity, login IP address, total login count, and active sessions. Flags inactive users (configurable threshold, default 30 days) and accounts that have never logged in. Optional section shows recent failed login attempts. Auto-approve for all roles (read-only).
- **Runbook result export** — Every runbook execution result can now be exported:
  - **CSV** — Flattens result tables and summary data into a downloadable CSV file
  - **JSON** — Full structured result as a downloadable JSON file
  - **PDF** — Opens a print-friendly view of the result panel (browser print-to-PDF)

### Fixed
- **Currency now reads from Metering Pricing table (ILS)** — `_load_metering_pricing()` now prioritizes the `metering_pricing` table (per-flavor, per-resource pricing with real ILS data) over `metering_config`. Derives per-vCPU and per-GB-RAM costs from actual flavor pricing. Falls back to `metering_config` only if `metering_pricing` is empty.
- **Runbook pricing pulled from Metering configuration** — Upgrade Opportunity Detector, Monthly Executive Snapshot, and Cost Leakage Report no longer ask the user to manually enter pricing. All cost/currency values are now loaded from the `metering_config` table (Admin → Metering Settings). Falls back to sensible defaults ($15.18/vCPU/mo, $5.04/GB RAM/mo, $2/GB storage/mo) when metering pricing is not yet configured.
- **Security & Compliance Audit requires approval** — Changed from `auto_approve` to `single_approval` for operator and admin triggers. Only superadmin can auto-execute. Security audit results contain sensitive findings that should be reviewed by an admin before running.
- **Upgrade Opportunity Detector requires approval for operators** — Changed operator trigger from `auto_approve` to `single_approval`. Admin/superadmin remain auto-approve. Revenue-impacting analysis should be reviewed before operator access.
- **deployment.ps1 updated** — Added `db/migrate_new_runbooks.sql` to the migration pipeline so new deployments automatically get the 7 new runbooks.

## [1.25.0] - 2026-02-23

### Added
- **7 New Operational Runbooks** — Expanding the runbook catalogue from 5 to 12 built-in engines, all integrated with the existing approval workflow:
  - **VM Health Quick Fix** (`vm_health_quickfix`, category: vm, risk: medium) — Single-VM diagnostic that checks power state, hypervisor state, port bindings, volume attachments, network, security groups, and floating IPs. Optional auto-restart (soft/hard/guest_os) with ERROR-state reset. Supports dry-run.
  - **Snapshot Before Escalation** (`snapshot_before_escalation`, category: vm, risk: low) — Creates a tagged snapshot with metadata (reference ID, actor, timestamp) before escalating a ticket to Tier 2. Captures VM state summary and console log tail. Supports dry-run.
  - **Upgrade Opportunity Detector** (`upgrade_opportunity_detector`, category: quota, risk: low) — Scans all tenants for upsell signals: quota pressure (>80%), undersized flavors (<2 vCPU or <2 GB RAM), old images (>2 years), deprecated images. Revenue estimates pulled from Metering configuration.
  - **Monthly Executive Snapshot** (`monthly_executive_snapshot`, category: general, risk: low) — Database-driven executive report: tenant count, VM/volume/storage totals, compliance %, hypervisor capacity risk, revenue estimate, top-N risk tenants (scored by error VMs + missing snapshots), month-over-month deltas from history tables. Pricing pulled from Metering configuration.
  - **Cost Leakage Report** (`cost_leakage_report`, category: general, risk: low) — Identifies wasted spend: idle VMs (<5% CPU from metrics cache), long-SHUTOFF VMs (>30 days), detached volumes (>7 days), unused floating IPs, oversized VMs (<20% RAM). Dollar amounts per item with pricing from Metering configuration.
  - **Password Reset + Console Access** (`password_reset_console`, category: vm, risk: high) — Cloud-init validation, Nova password reset with auto-generation, VNC/SPICE console URL with configurable expiry. Full audit log to `activity_log` table. High-risk: requires admin approval for operator/admin triggers.
  - **Security & Compliance Audit** (`security_compliance_audit`, category: security, risk: low) — Extended security audit: 0.0.0.0/0 ingress rules, wide port ranges (0-65535), stale users (no activity in N days), unencrypted volumes. Severity-weighted scoring. Requires approval for operator/admin triggers.
- **Approval Policies for New Runbooks** — All 7 new runbooks have approval policies for operator, admin, and superadmin roles. `password_reset_console` and `security_compliance_audit` use `single_approval` for operator/admin triggers; `upgrade_opportunity_detector` uses `single_approval` for operator triggers; others use `auto_approve`.
- **UI Result Renderers** — Dedicated friendly result panels for each new runbook: diagnostic checklists, snapshot metadata tables, opportunity breakdowns, KPI grids with month-over-month deltas, cost leakage category tables, step-by-step password/console status, and severity-coded compliance tables.
- **New Migration File** — `db/migrate_new_runbooks.sql` for upgrading existing databases (idempotent `ON CONFLICT` inserts).

## [1.24.3] - 2026-02-23

### Fixed
- **Copilot — 11 SQL column mismatches** — Fixed all built-in intent queries that returned "query failed" due to wrong column names: `list_volumes` (`size` → `size_gb`), `list_networks` (added `is_shared`/`is_external`/`admin_state_up`), `list_floating_ips` (`floating_ip_address` → `floating_ip`, etc.), `list_routers` (joined projects, use `external_net_id`), `list_subnets` (removed non-existent `ip_version`), `recent_activity` (`username`/`created_at` → `actor`/`timestamp`), `recent_logins` (`created_at` → `timestamp`), `tenant_health` (updated to `total_servers`/`error_servers`/`active_servers`/`total_snapshots`), `recent_snapshots` (`size` → `size_gb`), `runbook_summary` (`is_active` → `enabled`).
- **Copilot — Input disappears after "See all available questions"** — Input area now renders for both chat and help views; added "← Back to chat" footer link in help view.
- **History — N/A in Resource, Project, Domain columns** — Rewrote `v_comprehensive_changes` SQL view to use `COALESCE(NULLIF(history.name,''), NULLIF(live.name,''), fallback)` so deleted resources and resources with empty-string names (common for ports, subnets, some volumes) still show a meaningful identifier. Ports fall back to `device_owner (mac_address)`, volumes to `volume_type (id-prefix)`, subnets to CIDR, floating IPs to the IP address, and deletions to `type (id-prefix)`. Resource name completeness went from ~65% to 100%.
- **History — No resource filter dropdown** — Added a "Resource" filter dropdown to the History page filters alongside Type, Project, Domain, and Search.
- **History — Deletion entries show actual resource type** — Deletion entries now display the actual resource type (e.g. "🗑 server", "🗑 snapshot") instead of generic "🗑 deletion".
- **Refresh Inventory — "Not authenticated" error** — Fixed `handleRefreshInventory` to use `Authorization: Bearer` token header instead of `credentials: 'include'` (cookie-based auth), matching the auth pattern used by all other API calls.

### Changed
- **Copilot — UI polish** — Widened panel from 440px to 520px; gradient user message bubbles with shadow; improved chip hover effects with lift animation; better table header styling; polished welcome screen; input focus glow ring; refined dark mode for input area, bot messages, and help categories.

## [1.24.2] - 2026-02-23

### Fixed
- **Dashboard cartesian product joins** — Fixed three dashboard widget queries (`health-summary`, `capacity-pressure`, `coverage-risks`) that produced incorrect inflated numbers due to cartesian joins between `servers` and `volumes` tables. Each now queries independently and merges results.
- **VM Hotspots CPU always showing 0%** — CPU delta calculations were in-memory only and lost on restart. Added persistent CPU state storage (`monitoring/cache/cpu_state.json`) so delta-based CPU utilization works across restarts and `--once` runs.
- **OS Distribution widget showing "Unknown" for all VMs** — Enhanced `_infer_os_from_image_name` with 20+ OS patterns and added VM name fallback. VMs now correctly show Windows, Ubuntu, CentOS, etc.
- **System Metadata showing 0 Running VMs** — Fixed `upsert_hypervisors` to include `running_vms` from Nova API; added ACTIVE server count fallback when hypervisor data is unavailable.
- **Download Full Inventory Excel crash** — Fixed `TypeError: Excel does not support timezones in datetimes` by stripping `tzinfo` before writing cells via openpyxl. Also fixed export query column mismatches for domains, projects, and snapshots.
- **Rvtools cleanup FK constraint errors** — Comprehensive FK clearing before project and domain deletion. Deletes child resources in correct order (security_group_rules → security_groups → snapshots → servers → volumes → floating_ips → ports → routers → subnets → networks) and clears `users.default_project_id`, `users.domain_id`, `projects.domain_id` before deleting stale projects/domains.
- **`datetime.utcnow()` deprecation warnings** — Replaced all `datetime.utcnow()` calls with `datetime.now(timezone.utc)` in `pf9_rvtools.py` and `host_metrics_collector.py`.
- **Stuck DB queries** — Killed 22 stuck database queries caused by the previous cartesian joins and reduced API workers from 4 to 2 with timeout increased from 120s to 300s to prevent future hangs.
- **History table missing columns** — Fixed `UndefinedColumn` errors for `volumes_history`, `networks_history`, `ports_history`, `subnets_history` by adding missing columns and making `_upsert_with_history` catch column errors gracefully.
- **Rvtools domain cleanup query** — Fixed cleanup query to filter by `table_schema = 'public'` to avoid pg_catalog false positives.

### Changed
- **Quota tab redesigned** — Replaced flat table with a grouped card layout showing Compute, Block Storage, and Network quotas per project with usage bars and color-coded percentage indicators.
- **System Metadata inline styles** — Replaced hardcoded colors with CSS variable references (`var(--color-text-secondary)`, `var(--color-border)`, `var(--color-surface-elevated)`) for proper dark mode support.
- **Dark mode improvements** — TenantRiskHeatmapCard increased opacity (0.18 → 0.35) with colored borders; HostUtilizationCard null-state color fix for dark mode; App.tsx bar tracks, text colors, and borders all converted from hardcoded hex to CSS variables.
- **API container tuning** — Reduced Gunicorn workers from 4 to 2, increased timeout from 120s to 300s, removed `--preload` flag to prevent shared-state issues.
- **Dashboard fetch batching** — Reduced landing dashboard API calls from 17 sequential to 3 parallel batches.

### Added
- **CPU state persistence** — New `_load_cpu_state()` / `_save_cpu_state()` methods in `host_metrics_collector.py` for delta calculations across restarts.
- **Database schema additions** — Added `running_vms`, `created_at` columns to `hypervisors` table; `min_disk`, `min_ram` to `images` table; `image_id`, `os_distro`, `os_version` to `servers` and `servers_history` tables; OS columns (`os_distro`, `os_version`, `os_type`) to `images` and `images_history` tables.
- **New migration files** — `fix_missing_columns.sql`, `migrate_metadata_tables.sql`, `migrate_os_columns.sql`, `migrate_os_tracking.sql` for upgrading existing databases.

## [1.24.1] - 2026-02-22

### Added
- **Live Quota Lookups in Copilot** — The Copilot now fetches **configured quota limits** directly from the Platform9 API (Nova, Cinder, Neutron) in real time, instead of only showing resource consumption from the local database.
  - **"quota of service tenant"** → `configured_quota` intent — calls `Pf9Client.get_compute_quotas()`, `get_storage_quotas()`, `get_network_quotas()` live. Displays Compute (Instances, Cores, RAM, Key Pairs), Block Storage (Volumes, Storage GB, Snapshots), and Network (Networks, Subnets, Routers, Floating IPs, Ports, Security Groups) limits. Values of `-1` display as "unlimited".
  - **"usage for service tenant"** → `resource_usage` intent — shows actual resource consumption from the local database (VMs, vCPUs, RAM, Volumes, Storage). Clearly labeled as consumption, not limits.
  - **"quota and usage for service"** → `quota_and_usage` intent — side-by-side comparison table showing configured limits vs current usage with percentage utilization and color-coded indicators (🟢 < 70%, 🟡 70-90%, 🔴 > 90%). Falls back to usage-only view when Platform9 API is unreachable.
  - **API Handler Framework** — New `api_handler` field on `IntentDef`/`IntentMatch` allows intents to call live APIs instead of only executing SQL queries. Fully integrated with the builtin, Ollama, and OpenAI/Anthropic pathways.
  - **Updated suggestion chips** — Tenant/Project category now includes "Quota for …", "Usage for …", and "Quota & Usage …" template chips.

## [1.24.0] - 2026-02-22

### Added
- **Ops Copilot** — Three-tier AI assistant for natural-language infrastructure queries, embedded directly in the UI.
  - **Tier 1 — Built-in Intent Engine** (zero setup, default): Pattern-matching engine with 40+ intents covering inventory counts, VM power states (powered on/off), capacity metrics, error VMs, down hosts, snapshot/drift/compliance summaries, metering, users, activity logs, runbooks, backups, notifications, security groups, networking (networks, subnets, routers, floating IPs), provisioning, role assignments, and full infrastructure overview. Answers powered by live SQL queries — no external services required.
  - **Tenant / Project / Host scoping**: Add "on tenant X", "for project X", or "on host Y" to any question — the engine dynamically injects SQL WHERE clauses to filter results. Example: *"how many powered on VMs on tenant <your-tenant>?"*
  - **Synonym expansion**: "powered on" → "active", "vm" → "vms", "tenant" → "project", etc. — questions are expanded with canonical forms before matching for higher accuracy.
  - **Tier 2 — Ollama (local LLM)**: Connect to a self-hosted Ollama instance for free-form questions. Infrastructure context is injected into the system prompt alongside intent query results for grounded answers. No data leaves your network.
  - **Tier 3 — External LLM (OpenAI / Anthropic)**: Use GPT-4o-mini, Claude, or other models. Sensitive data (IPs, emails, hostnames) automatically redacted before sending when `COPILOT_REDACT_SENSITIVE=true` (default).
  - **Labeled floating action button**: Prominent pill-shaped "🤖 Ask Copilot" button with gradient background and pulse animation on first visit. Collapses to a close icon when the panel is open. Much more visible than a plain icon button.
  - **Welcome screen**: First-open experience with greeting, example questions, and a "See all available questions" button that opens the help view.
  - **Help / Guide view**: Dedicated ❓ view with 8 categorized question groups (~40 chips), usage tips (scoping syntax, action words), and backend info. Accessible from the header or footer "How to ask" link.
  - **Categorized suggestion chips**: Organized into Infrastructure, VM Power State, Tenant/Project, Capacity, Storage & Snapshots, Networking, Security & Access, and Operations. Template chips (with "…") fill the input for completion; regular chips run immediately.
  - **Backend indicator**: Footer badge shows active backend (⚡ Built-in / 🧠 Ollama / ☁️ OpenAI/Anthropic).
  - **Settings panel**: Admin-only gear icon opens inline settings to switch backends, configure URLs/keys/models, edit the system prompt, toggle redaction, and test LLM connectivity — all without editing `.env`.
  - **Feedback system**: Thumbs up/down per answer, stored in `copilot_feedback` for quality tracking.
  - **Conversation history**: Persisted per user in `copilot_history` with automatic trimming (default: 200 entries).
  - **Fallback chain**: If the active LLM backend fails, Copilot automatically falls back to the built-in intent engine.
  - **Improved no-match response**: When no intent matches, users see a helpful message with example queries, scoping syntax, and a suggestion to enable an LLM backend.
  - **RBAC integration**: Copilot fully integrated with the permission system — `copilot` resource with `read`, `write`, and `admin` actions. Panel visibility gated by `copilot:read` permission. Superadmins can toggle Copilot access per role from Admin → Permissions. All roles granted `read` by default; `write`/`admin` restricted to admin and superadmin.
  - **Admin Permissions panel**: `copilot` appears as a toggleable resource in the User Management → Permissions matrix with description "Ops Copilot — AI assistant for infrastructure queries".
  - **Dark mode**: Full dark theme support for the floating panel, messages, chips, help view, welcome screen, and settings.
  - **Keyboard shortcut**: `Ctrl+K` toggles the Copilot panel from anywhere.
  - **New DB tables**: `copilot_history`, `copilot_feedback`, `copilot_config` (migration: `db/migrate_copilot.sql`).
  - **New backend files**: `api/copilot.py` (router), `api/copilot_intents.py` (intent engine), `api/copilot_llm.py` (LLM abstraction), `api/copilot_context.py` (context builder with redaction).
  - **New UI files**: `CopilotPanel.tsx`, `CopilotPanel.css`.
  - **Updated**: `.env.example`, `docker-compose.yml`, `deployment.ps1`, `seed_demo_data.py`, `api/requirements.txt`.

### Fixed
- **Copilot intent SQL column errors** — All intent queries referenced non-existent columns `s.host` and `s.flavor_name` on the `servers` table.  Fixed: `s.host` → `s.hypervisor_hostname AS host`, `s.flavor_name` → `f.name AS flavor_name` via `LEFT JOIN flavors f ON f.id = s.flavor_id` across ~10 intent queries (list VMs, powered on/off, VMs on tenant, VMs on host, error VMs).
- **Quota SQL error** — "quota of org1" failed with "column s.vcpus does not exist". Fixed: quota query now joins the `flavors` table (`LEFT JOIN flavors f ON f.id = s.flavor_id`) and uses `f.vcpus` / `f.ram_mb` instead of non-existent `s.vcpus` / `s.ram_mb`.
- **VMs-on-host WHERE clause** — `WHERE LOWER(s.host) LIKE %s` failed. Fixed: `WHERE LOWER(s.hypervisor_hostname) LIKE %s`.
- **Flavor list SQL** — `ram` and `disk` columns don't exist. Fixed: `ram_mb` and `disk_gb`.
- **Scope extraction failure for "org1"** — The regex treated "org" as a keyword prefix, so "quota of org1" extracted no scope and returned all 60 projects (LIMIT 30 cut off before ORG1). Added fallback pattern `(?:of|for)\s+<name>$` to catch bare name at end of question.
- **Reversed scope order** — "quota exists for service tenant" was not parsed because the word order (name before "tenant") wasn't handled. Added pattern for reversed order (`for <name> tenant/project`).
- **Wrong intent for quota queries** — "quota exists for service tenant" matched `vms_on_tenant` (boost 0.2) instead of `quota_for_project`. Fixed: boosted quota intent to 0.25, added more keywords ("quota exists", "quota of", "quota on"), and added regex pattern for `quota\s+exists`.
- **Help view empty** — Suggestion chips API returns `{suggestions: {categories, tips}}` but UI stored the outer envelope. Fixed: `setSuggestionsData(d?.suggestions || d)`.
- **RBAC middleware segment extraction** — For `/api/copilot/ask`, the middleware extracted segment `"api"` (not `"copilot"`) because it used `path.split("/")[0]`. Fixed: when `parts[0] == "api"`, use `parts[1]` as the resource segment.
- **Copilot permissions missing from API** — `MAIN_UI_RESOURCES` whitelist in `/auth/permissions` endpoint didn't include `copilot`, so the Admin Permissions panel never showed it. Fixed: added `copilot` to the whitelist.

## [1.23.0] - 2026-02-22

### Added
- **Demo Mode** — Run the full portal with pre-populated sample data, no Platform9 environment required. Ideal for evaluations, demos, and development.
  - New `DEMO_MODE=true` environment variable activates the mode across all components.
  - `seed_demo_data.py` populates PostgreSQL with 3 domains, 7 projects, 5 hypervisors, 7 flavors, 6 images, 35 VMs, ~50 volumes, ~100 snapshots, 8 networks, 8 subnets, 3 routers, 7 users with RBAC role assignments, security groups & rules, snapshot policies & assignments, compliance reports, drift rules & events, activity log entries, metering config with flavor pricing, backup config, and 5 runbooks with approval policies. All inserts use `ON CONFLICT DO NOTHING` for idempotency.
  - Static metrics cache generated automatically with realistic CPU/RAM/disk values for all demo hosts and VMs (no live scraping needed).
  - Deployment wizard (`deployment.ps1`) adds a "Production vs Demo" mode choice at the start—choosing Demo skips all Platform9 credential prompts, monitoring IPs, and snapshot service user configuration. The seed script runs automatically after Docker services are ready.
  - API exposes `GET /demo-mode` (public, no auth) returning `{"demo": true|false}` so the UI can detect the mode.
  - UI shows a sticky amber "DEMO" banner at the top of the page with dark-mode support when demo mode is active.
  - `host_metrics_collector.py` detects `DEMO_MODE=true` and exits gracefully instead of attempting live collection.
  - `startup.ps1` skips the background metrics collector and initial metrics fetch in demo mode.
  - Environment validation in `deployment.ps1` no longer requires `PF9_USERNAME`, `PF9_PASSWORD`, or `PF9_AUTH_URL` when in demo mode.

## [1.22.1] - 2026-02-22

### Fixed
- **VM CPU utilization completely wrong** — The VM Hotspots widget displayed wildly inaccurate CPU values (e.g. Forti_WAF 91.6%, 2019 at 100%) because the collector divided the cumulative `libvirt_domain_info_cpu_time_seconds_total` counter by a magic constant (`/ 10000`). Replaced with proper delta-based calculation using `libvirt_domain_vcpu_time_seconds_total` summed across all vCPUs, divided by wall-clock time × vCPU count. Values now reflect real instantaneous CPU usage (Forti_WAF → 18.7%, 2019 → 18.8%). Like the host CPU fix, requires two collection cycles after restart.
- **VM storage always showing 100% for raw-format disks** — Raw/thick-provisioned disks report `allocation == capacity == physicalsize` in libvirt, so the old code always computed 100% usage. Storage calculation now tracks per-device `capacity_bytes`, `allocation`, and `physicalsize_bytes` separately and detects raw disks (where all three are equal). For thin-provisioned (qcow2) disks, `allocation` correctly reflects actual usage.

## [1.22.0] - 2026-02-22

### Fixed
- **Host CPU utilization completely wrong** — The "Top Hosts by Usage" widget displayed wildly inaccurate CPU values (e.g. 100% when PF9 shows 4%). Root cause: the monitoring collector was using `node_load1 × 25` (1-minute load average) instead of actual CPU utilization. Replaced with proper delta-based `node_cpu_seconds_total` calculation — the same method used by PF9, Prometheus, and Grafana. CPU values now match the Platform9 Infrastructure → Cluster Hosts page. Requires two collection cycles (~2 minutes) after restart to produce accurate deltas.

### Changed
- **Dashboard dark mode overhaul** — Comprehensive rework of all dark mode colors across the Operations Dashboard:
  - Raised card backgrounds from `#1e1e2d` to `#1a1d2e` with stronger borders (`#2a2d42`) for better layer separation against the darkened page background (`#0d0f18`).
  - Inner surfaces (health items, SLA summary, activity items, host items, etc.) raised from `#16162a` to `#141729` for a clear 3-tier depth hierarchy.
  - Softened harsh reds throughout: VM Hotspots metric color `#ef4444` → `#e87461` (light) / `#f0a898` (dark); host critical bar fill `#ef4444` → `#f87171`; activity deleted action `#ef4444` → `#f87171`.
  - Added zebra striping (`rgba(255,255,255, 0.02)` on even rows) and hover highlights (`rgba(255,255,255, 0.04)`) to all 7 dark mode tables (SLA, coverage, capacity, tenant-risk, trendlines, capacity-trends, drift).
  - Heatmap tiles get a subtle blue-purple glow on hover instead of plain black shadow.
  - Widget chooser panel, toggle, header, footer, and reset button all updated to the new palette.
- **Host utilization card visual improvements** — Metric bars thickened from 10px to 12px with rounder corners (6px) and a translucent track (`rgba(255,255,255, 0.1)`) replacing the near-invisible `#4b5563`. Percentage values bumped to 0.8rem/700 weight with explicit bright color in dark mode. Metric labels now uppercase with letter-spacing. Critical badge gets a semi-transparent red background + border in dark mode. Host rank weight increased to 800 with brighter blue (`#93bbfc`) in dark mode.
- **Activity feed dark mode improvements** — CREATED/DELETED action badges now have a visible `rgba(255,255,255, 0.08)` background + subtle border in dark mode (pills instead of naked text). Footer text brightened from `#64748b` to `#8994a8`. Summary labels and timestamps brightened for readability.

### Added
- **Widget Chooser** — New "Customize" button on the dashboard toolbar opens a dropdown panel listing all 13 widgets with toggle switches. Visibility persists to `localStorage` (`pf9_dashboard_widgets`). "Reset to Defaults" button restores the original layout. Three widgets hidden by default: Compliance Drift, Trendlines, Capacity Trends.
- **SLA configuration link** — "Configure Snapshot Policies & Retention" button added to the Snapshot SLA widget tips section, navigating directly to the Snapshot Policies tab.

## [1.21.1] - 2026-02-19

### Changed
- **Runbook execution results now visible to operators** — "My Executions" section added to the Runbooks tab so users who trigger a runbook can immediately see their results without navigating to Admin.
- **Orphan Resource Cleanup defaults to all resource types** — Parameters schema now defaults to `["ports", "volumes", "floating_ips"]` instead of just `["ports"]`, making the full scope visible upfront.
- **Friendly result rendering** — Execution results now display tenant names, resource names, IP addresses, and volume details instead of raw UUIDs. All engines (Stuck VM, Orphan Cleanup, SG Audit, Quota Check) now resolve project IDs to human-readable project names via Keystone.

### Added
- **`GET /api/runbooks/executions/mine`** — New endpoint returning executions filtered to the current user (uses `runbooks:read` permission).
- **Approval notification events** — Two new notification event types: `runbook_approval_granted` and `runbook_approval_rejected`. Users who trigger a runbook receive email when their request is approved or rejected. Admins can subscribe to these events for visibility.
- **Execution result tables** — Friendly tabular rendering for all 5 runbook engines in the UI: Stuck VM table (name, status, tenant, host), Orphan Resources by type (ports/volumes/floating IPs with tenant names), Security Group violations, and Quota alerts.

## [1.21.0] - 2026-02-19

### Added
- **Policy-as-Code Runbooks framework** — New Runbooks feature providing operational automation with configurable approval workflows. Full-stack implementation: database tables, REST API, execution engine, and React UI.
- **5 built-in runbooks** — Stuck VM Remediation (detect + soft/hard reboot), Orphan Resource Cleanup (ports + volumes + floating IPs), Security Group Audit (overly permissive rules), Quota Threshold Check (per-project utilisation alerts), Diagnostics Bundle (hypervisors + services + resources + quotas).
- **Flexible approval policies** — Configurable per-runbook `trigger_role → approver_role` mapping with three approval modes: `auto_approve` (no human needed), `single_approval` (one approver), `multi_approval` (multiple approvers). Rate-limited auto-approve with configurable daily max and escalation timeout.
- **Runbooks catalogue tab** — Operator-facing tab in the Provisioning Tools nav group. Browse runbook cards with trigger actions and schema-driven parameter forms. Accessible to all roles (tier 1 operators, admins, superadmins).
- **Runbook governance in Admin panel** — Three new admin sub-tabs under Auth Management: Runbook Executions (filterable history table with detail panel), Runbook Approvals (pending queue with approve/reject/cancel), Runbook Policies (flexible team-to-team approval policy editor).
- **Dry-run as first-class concept** — All runbooks support scan-only mode. Trigger modal defaults to dry-run with clear visual distinction (blue vs red button) for live execution.
- **Execution audit trail** — Full lifecycle tracking: pending_approval → approved → executing → completed/failed. Every execution records trigger user, approver, timestamps, parameters, results, items found/actioned.
- **Runbook notification events** — Three new event types: `runbook_approval_requested`, `runbook_completed`, `runbook_failed`. Integrates with existing notification subscriber system.
- **Pluggable engine architecture** — `@register_engine` decorator pattern allows adding new runbook implementations with zero framework changes.

## [1.20.7] - 2026-02-19

### Added
- **Rich admin provisioning notification** — The `tenant_provisioned` email sent to admin subscribers now includes full provisioning inventory: job ID, domain/project with OpenStack IDs, created user (name, email, role, user ID), network details (name, ID, type, VLAN, subnet CIDR, gateway, DNS), security group (name, ID), and compute/network/storage quotas. Uses a new Jinja2 template (`notifications/templates/tenant_provisioned.html`) instead of the generic inline HTML layout.
- **Template-aware `_fire_notification()`** — The internal notification helper now accepts optional `template_name` and `template_vars` parameters. When a template is provided, it renders a Jinja2 template from `notifications/templates/`; otherwise it falls back to the existing inline HTML.

### Fixed
- **Security group rules blank in welcome email** — The customer-facing welcome email template referenced `rule.port` and `rule.remote_ip_prefix` but the Python code built dicts with `ports` and `cidr`. Fixed template field names to match.
- **Welcome email showed wrong network name** — The welcome email used the old fallback `{domain}-ext-net` instead of the actual derived network name from Step 8. Now uses the real `net_name` value.

## [1.20.6] - 2026-02-19

### Changed
- **External network naming convention** — During customer onboarding, the auto-generated external network name now follows `{tenant_base}_extnet_vlan_{vlanid}` instead of `{domain}-ext-net`. The tenant base is derived from the project name by stripping the `_subid_{id}` suffix (e.g. project `erez_tenant_subid_12454512` with VLAN 878 → network `erez_tenant_extnet_vlan_878`). When no VLAN ID is set, the name is `{tenant_base}_extnet`. The user can still override the name manually.
- **Network name auto-fill in UI** — The Network Name field now auto-fills when Domain Name, Subscription ID, or VLAN ID change, following the new naming convention. The placeholder and Review step also reflect the derived name.

## [1.20.5] - 2026-02-19

### Added
- **Scope-aware smart queries** — Domain and Tenant dropdown filters on the Ops Search bar now actually filter smart query results. 20 of 26 query templates inject conditional `WHERE` clauses (`scope_tenant`, `scope_domain`) so answers reflect only the selected project/domain. Infrastructure-level queries (hypervisors, images, drift, activity, domains, platform overview) remain unscoped.
- **Scope passed end-to-end** — Frontend sends `scope_tenant` / `scope_domain` query params to `GET /api/search/smart`; the API passes them to `execute_smart_query()`; each query's SQL uses `(%(scope_tenant)s IS NULL OR p.name = %(scope_tenant)s)` pattern so NULL = no filter.
- **Parameterised "Ask Me Anything" chips** — Template chips (dashed border) like "Quota for …" and "Roles for …" auto-fill the search bar with the scoped tenant name when a scope is selected, or prompt the user to type a target name.
- **"New Question" button** — Appears on both the smart answer card header and the FTS results bar. Clears all results and focuses the input for a fresh query.

### Fixed
- **Scope filters had no effect** — Selecting a domain/tenant in the scope dropdowns only affected template chip pre-fill but did not filter smart query SQL results. Now all scopable queries honour the selected scope.
- **Dark mode unreadable text** — All hardcoded light-mode colors (`#fff`, `#111827`, `#374151`, `#6b7280`, `#15803d`, etc.) in the smart query card, help panel, chips, intent suggestions, error bar, and empty state replaced with CSS variables (`var(--color-success)`, `var(--pf9-text)`, `var(--card-bg)`, `var(--pf9-border)`, etc.) that adapt to the dark theme.

## [1.20.4] - 2026-02-20

### Fixed
- **User indexer pointed at wrong table** — The Ops Search user indexer was querying the internal `user_roles` table (7 rows) instead of the Platform 9 Keystone `users` table (127 rows). Rewrote the user indexer to query `users` joined with `domains`, indexing name, email, domain, enabled status, and description.
- **Search missing from admin permissions UI** — The `search` resource was not listed in `MAIN_UI_RESOURCES` (API) or `resourceDescriptions` (UI), so admins could not assign Ops Search permissions through the Admin → Permissions panel. Added to both.
- **Stale deleted resources appearing in search** — The search indexer only added/updated documents but never removed them when the source resource was deleted. Added a `cleanup_stale_documents()` step that runs after each indexing cycle, removing search documents for 19 infrastructure doc types whose source row no longer exists. Event/log types (activity, audit, backups, etc.) are excluded since their source records are never deleted.
- **Quota smart query returning empty** — The `metering_quotas` table was always empty because no `collect_quota_usage()` function existed in the metering worker. Implemented the collector using LATERAL JOINs against `servers`, `volumes`, `snapshots`, `floating_ips`, `networks`, `ports`, and `security_groups` with flavor-based vCPU/RAM resolution. Data now populates automatically each metering cycle.
- **vCPUs and RAM always zero in quota data** — Servers store a `flavor_id` reference, not inline vCPUs/RAM. Updated both the metering collector and smart query live-fallback SQL to join through `flavors` for accurate vCPU and RAM figures.
- **Quota queries showed NULL quota columns** — Since Platform9 quota limits aren't available via API, the quota smart queries showed confusing NULL columns. Renamed templates to "Resource Usage" and stripped quota-limit columns, showing only actual usage (VMs, vCPUs, RAM, Volumes, Storage, Floating IPs). Both `quota_for_tenant` and `quota_usage_all` templates use `DISTINCT ON (project_id)` with metering data first, live-computed fallback second.

### Added
- **7 new search indexers** — Expanded search coverage from 22 to 29 document types. New indexers: `flavor`, `image`, `router`, `role`, `role_assignment`, `group`, `snapshot_policy`. Each includes domain/project attribution where applicable.
- **Doc-type labels & colors** — All 29 document types now have named pill labels and distinct colors in the search results UI.
- **Database seed updates** — `init.sql` and `migrate_search.sql` now seed `search_indexer_state` for all 29 doc types.
- **Smart Query Templates (v3)** — A new Ops-Assistant layer that matches natural-language questions (e.g., "how many VMs are powered off?", "quota for Org1", "show platform overview") to 26 parameterised SQL templates and returns structured answer cards (table, key-value, number) rendered inline above search results. Covers VM status, hypervisor capacity, quota usage, volumes, networks, images, snapshots, drift events, role assignments, resource efficiency, and more. New endpoints: `GET /api/search/smart`, `GET /api/search/smart/help`.
- **Quota/usage metering collector** — New `collect_quota_usage()` function in the metering worker computes per-project resource consumption (VMs, vCPUs, RAM, volumes, storage, snapshots, floating IPs, networks, ports, security groups) from live inventory tables and writes to `metering_quotas`.
- **Smart Query discoverability UI** — New 🤖 button on the search bar opens a categorised help panel with 26 clickable example question chips (Infrastructure, Projects & Quotas, Storage, Networking, Security & Access, Operations). Clicking a chip auto-fills the search bar and executes immediately. The empty state also shows quick-start chips and directs users to the full help panel.

### Improved
- **AI-quality search results** — All 29 indexers now produce natural-language body text with cross-reference counts (e.g., "Domain org1 containing 5 projects, 42 users, and 18 VMs") instead of raw field dumps. Structured metadata (key-value pairs) is rendered as labeled pill cards in the UI, giving operators instant operational context without navigating away.
- **Cross-reference enrichment** — Indexers for domains, projects, users, VMs, networks, flavors, hypervisors, security groups, and volumes now include SQL subqueries for related resource counts, member lists, and role assignments.
- **Metadata pill cards** — The search result cards now display structured metadata as compact, labeled badges (e.g., "VMs: 18", "Status: ✅ Enabled", "RAM: 4,096 MB") using a new `METADATA_LABELS` map and `formatMetaValue` formatter in the UI.

## [1.20.3] - 2026-02-20

### Fixed
- **Ops Search page appeared empty** — The `search` route was not in the `hideDetailsPanel` list in App.tsx, causing the details panel to render and squeeze the search UI to zero width. Added `search` (and `resource_management`) to the exclusion list.

## [1.20.2] - 2026-02-20

### Fixed
- **Ops Search tab invisible in navigation** — The `search` nav item was not registered in the `nav_items` database table, so it never appeared in the sidebar. Added the entry to `init.sql`, `migrate_search.sql`, and inserted into the live database.

## [1.20.1] - 2026-02-20

### Fixed
- **Ops Search missing from documentation & deployment scripts** — `init.sql`, `deployment.ps1`, `ADMIN_GUIDE.md`, `ARCHITECTURE.md`, Kubernetes Migration Guide, and Linux Deployment Guide were not updated for the search feature. All 6 files updated.

## [1.20.0] - 2026-02-20

### Added
- **Ops Assistant — Full-Text Search (v1)** — New `🔍 Ops Search` tab with PostgreSQL `tsvector` + `websearch_to_tsquery` full-text search across all 29 resource types. Relevance-ranked results with keyword-highlighted snippets, type/tenant/domain/date filtering, pagination, and per-doc-type pill filters.
- **Trigram Similarity (v2)** — "Show Similar" button on every search result uses `pg_trgm` extension to find related documents by title (60% weight) and body text (40% weight) similarity scoring.
- **Intent Detection (v2.5)** — Natural-language queries like *"quota for projectX"*, *"capacity"*, *"idle resources"*, or *"drift"* trigger Smart Suggestions that link directly to the matching report endpoint. Extracts tenant hints for pre-filtering.
- **Search Indexer Worker** — New `search_worker` Docker service that incrementally indexes 29 document types on a configurable interval (default: 5 min). Uses per-doc-type watermarks for efficient delta processing.
- **Database Migration** — `db/migrate_search.sql` adds `search_documents` table with 7 indexes (GIN tsvector, GIN trigram on title + body, composite lookups), auto-update tsvector trigger, `search_indexer_state` tracking table, `search_ranked()` and `search_similar()` SQL functions, and RBAC permission grants for all 4 roles.
- **Search API** — 5 new endpoints under `/api/search`: full-text search with pagination, similarity lookup, indexer stats, manual re-index trigger (admin), and intent detection.
- **Indexer Stats Dashboard** — In-tab panel showing per-doc-type document counts, last run time, and duration for operational visibility.

### Improved
- **Tab count** — 26 → 27 management tabs (added Ops Search).
- **Docker Compose** — Added `search_worker` service with configurable `SEARCH_INDEX_INTERVAL`.

## [1.19.9] - 2026-02-19

### Added
- **Linux Deployment Guide** — New `docs/LINUX_DEPLOYMENT_GUIDE.md` covering end-to-end Linux setup: Docker/Docker Compose installation (Ubuntu + RHEL), Python venv setup, cron equivalents for Task Scheduler, `startup.sh` script, systemd service unit, firewall/SELinux notes, and a quick-start TL;DR block.

### Improved
- **Kubernetes Migration Guide v2.0** — Comprehensive rewrite of `docs/KUBERNETES_MIGRATION_GUIDE.md` to cover all 11 services (was written for 6). Added complete Deployment manifests, ConfigMaps, Secrets, and PVCs for the 4 worker services (snapshot, backup, metering, notification). Updated Helm chart structure, values.yaml, network policies, and migration roadmap. Corrected CronJob section — only `host_metrics_collector.py` needs a CronJob; the other 4 are containerized workers (Deployments, not CronJobs).
- **README** — Added Linux Deployment Guide to documentation table and deployment flexibility section. Updated platform badge to show Windows | Linux | Kubernetes.

## [1.19.8] - 2026-02-19

### Improved
- **README polish** — Added plain-English one-liner description at the top for first-time visitors. Moved vibe-coding / AI-partnership paragraph from About the Creator up into the "Why This Exists" section where it fits the narrative. Updated commit count from 107 to 115.

## [1.19.7] - 2026-02-19

### Improved
- **README.md rewrite** — Complete restructure of the project README: added engineering evaluation narrative (3 engineering gaps), badges, architecture table, collapsible detail sections, leaner FAQ, cleaned up duplicate sections, and consolidated troubleshooting. Reduced from ~960 lines to ~650 lines with no loss of information.
- **ARCHITECTURE.md expansion** — Added 5 major new sections: trust boundaries & service communication matrix, full authentication flow (LDAP → JWT → MFA → RBAC) with Mermaid sequence diagrams, complete data model overview (44+ tables, ER diagram, current-state vs history pattern), restore flow sequence diagram with safety checks table, and 2 new Architecture Decision Records (Planner/Executor pattern, Dual-Table History pattern). Expanded from ~887 to ~1,485 lines.

### Fixed
- **Screenshot filenames** — Renamed image files to use dashes instead of spaces (`VMs inventory.png` → `VMs-inventory.png`, `History monitoring.png` → `History-monitoring.png`, `API Performance.png` → `API-Performance.png`). Fixed typo `Snapshot-rostore-audit.png` → `Snapshot-restore-audit.png`. Updated all references in README.md.

### Added
- **GitHub Sponsors & FUNDING.yml** — Created `.github/FUNDING.yml` to enable the Sponsor button on the repository.

## [1.19.6] - 2026-02-18

### Fixed
- **RBAC: operator role 403 on networks and flavors** — The `has_permission()` check treated `write` and `read` as independent actions, so operators who had `write` on networks/flavors could not perform `GET` (read) requests. Updated the permission logic so `write` implies `read` and `admin` implies both.
- **RBAC: operator/viewer missing `users` read permission** — The operator and viewer roles had no `users` resource permission, blocking access to the PF9 inventory Users tab (Keystone users). Added `users:read` for both roles.
- **RBAC: missing explicit `read` rows for write-only resources** — Added `read` rows for operator on `networks`, `flavors`, `snapshot_assignments`, and `snapshot_exclusions` in the DB seed to be consistent with the permission hierarchy.

### Added
- **`db/migrate_operator_permissions.sql`** — Migration script to add missing operator/viewer permissions to existing databases.

## [1.19.5] - 2026-02-18

### Fixed
- **Domain Overview: vCPU/RAM always zero** — Added flavor catalog lookup to resolve vCPU and RAM from flavor IDs, matching the fix applied to the Quota report in v1.19.4.
- **Snapshot Compliance: table does not exist** — Changed query from non-existent `snapshot_policy_assignments` to actual `snapshot_assignments` table; added Cinder volume snapshot counts and fixed `metering_snapshots` lookup to use `project_name`.
- **Metering Summary: "No data found"** — Domain filter was comparing `metering_resources.domain` (stores email domains) against OpenStack domain name. Rewrote to filter by `project_name IN (projects WHERE domain_id = ?)` and resolve actual domain names via project→domain join.
- **Resource Inventory: tenant dropdown not filtered by domain** — Frontend now filters the project dropdown to only show projects belonging to the selected domain, and resets the tenant selection when domain changes.
- **User & Role Audit: missing role column** — Added Keystone `role_assignments` API call (`list_role_assignments`) with scope resolution to show each user's role name and detailed assignments.
- **Capacity Planning: allocated = 0** — Added flavor catalog lookup to resolve allocated vCPU, RAM, and disk from flavor IDs (same root cause as Domain Overview).
- **Backup Status: table does not exist** — Rewrote from non-existent `backup_jobs` table to actual `backup_history` table with correct schema (backup_type, file_path, size_bytes, status, created_at).
- **Network Topology: external networks not detected** — External flag now checks both `router:external` and `is_external` fields in network response.
- **Cost Allocation: shows email domains instead of OpenStack domains** — Complete rewrite to aggregate costs by actual OpenStack domain name via project→domain join, replacing the incorrect grouping by email domain column.
- **Drift Detection: table does not exist** — Changed from non-existent `drift_detections` to actual `drift_events` table; remapped all column references (field_changed, old_value, new_value, description, acknowledged).

### Added
- **`list_role_assignments` client method** — New helper on the OpenStack control client to fetch Keystone role assignments with `include_names=true`, supporting user-level and full listing.

## [1.19.4] - 2026-02-18

### Fixed
- **Quota report: vCPU and RAM usage always zero** — Nova `/servers/detail` returns flavor as `{id}` without inline `vcpus`/`ram`. The report now fetches the full flavor catalog and resolves vCPU/RAM from it, so Used vCPUs and Used RAM are correctly populated.
- **Quota report: missing Used columns** — Added Used Networks, Used Floating IPs, Used Security Groups, and corresponding utilization-% columns that were previously absent.
- **Quota report: missing Snapshots** — Added Quota Snapshots, Used Snapshots, and Snapshot Util % columns (sourced from Cinder snapshots and storage quotas).

### Added
- **`list_volume_snapshots` client method** — New helper on the OpenStack control client to list Cinder volume snapshots across all tenants.

## [1.19.3] - 2026-02-18

### Added
- **Chargeback: actual resource counting** — Volume, network, subnet, router, and floating IP counts are now queried from real inventory tables (joined via projects + domains), replacing the previous per-VM approximation.
- **Chargeback: snapshot operation + public IP costs** — `snapshot_op` and `public_ip` pricing categories are now included in the chargeback total. Snapshot cost = storage GB cost + per-operation cost. Public IP cost = actual floating IP count × monthly rate.
- **Chargeback: ephemeral disk cost** — If a flavor has `disk_cost_per_gb` configured, the cost is added to compute cost in the report.
- **Chargeback: unified tenant set** — Report now includes tenants that have volumes, networks, or IPs but no VMs, ensuring all billable resources are captured.

### Changed
- **Chargeback currency from pricing** — Currency is now resolved from: query parameter → first pricing row → `metering_config.cost_currency` → `USD`. Previously hardcoded fallback to "USD".
- **Export card subtitle** — Changed from "Per-tenant cost aggregation in USD" to "according to pricing currency" with actual currency shown dynamically.
- **Export notes** — Updated to document that volumes, networks, and floating IPs are counted from actual inventory, not approximated.
- **Pricing documentation** — Updated "How pricing works" section to clarify volume/network/IP are counted from inventory.

### Fixed
- **Chargeback missing volumes** — Volumes were not actually counted; cost was approximated as `vm_count × rate`. Now uses real `COUNT(*)` from the `volumes` table.
- **Chargeback missing networks** — Networks, subnets, and routers were not counted. Now queries actual inventory with per-tenant breakdown.
- **Chargeback missing floating IPs** — Floating IPs were not counted at all. Now queries the `floating_ips` table and applies the `public_ip` monthly rate.
- **Chargeback CSV columns** — Added: Volumes, Volume GB, Networks, Subnets, Routers, Floating IPs, Public IP Cost columns.

## [1.19.2] - 2026-02-18

### Added
- **Manual Inventory Refresh** — Superadmin "🔄 Refresh Inventory" button on all inventory tabs. Calls `POST /admin/inventory/refresh` which fetches live OpenStack data for every resource type and deletes stale rows that no longer exist in Platform9. Returns per-resource summary.
- **Comprehensive stale-resource cleanup** — `cleanup_old_records()` (pf9_rvtools.py) now covers all 15 inventory tables: `security_group_rules`, `security_groups`, `snapshots`, `images`, `flavors`, `servers`, `volumes`, `floating_ips`, `ports`, `routers`, `subnets`, `networks`, `hypervisors`, `projects`, `domains`. Previously 6 tables (flavors, hypervisors, domains, projects, security_groups, security_group_rules) were missing.
- **Metering pricing auto-cleanup** — When stale flavors are removed, matching `metering_pricing` rows (category=flavor) are also purged.

### Fixed
- **Deleted flavors persisting in Inventory** — Flavors removed from Platform9 were never cleaned from the database, so they kept appearing in the Inventory Flavors tab.
- **Deleted resources persisting across all Inventory tabs** — Hypervisors, domains, projects, security groups, and security group rules that were deleted in Platform9 remained visible due to missing cleanup entries.
- **Metering sync-flavors one-way sync** — `POST /pricing/sync-flavors` now fetches live data from OpenStack and removes stale entries (previously only added, never removed).
- **Login page dark mode** — Hero container background changed to transparent to prevent visible rectangle against page background; removed radial glow overlay and left panel box-shadow in dark mode.

## [1.19.1] - 2026-02-18

### Added
- **Editable Permission Matrix** — Superadmin users can now click permission checkboxes to toggle role-resource-action grants in real time. Changes are persisted to the database immediately via `PUT /auth/permissions`. Non-superadmin users see a read-only matrix.

### Fixed
- **Permission checkboxes disabled** — Previously all permission checkboxes in the admin Permissions tab were hardcoded as disabled with no backend endpoint to update them. Now superadmin can toggle any permission.

### Security
- **CHANGELOG sanitized** — Removed real domain names, IPs, and org names that were inadvertently included in the v1.19.0 security section notes.

## [1.19.0] - 2026-02-18

### Added
- **Nav Item Active/Action toggles in Admin UI** — Navigation Catalog now shows `Active` and `Action` columns for each nav item. `Active` controls whether the item appears in navigation; `Action` controls orange accent color-coding. Both toggleable in edit mode.
- **Nav color-coding via `is_action` DB flag** — Replaced the broken `action_resources` approach (which colored all items orange) with a per-item `is_action` boolean in the `nav_items` table. 16 action/config items correctly marked.
- **Metering Pricing: sortable table** — All pricing columns (Category, Item Name, Unit, Cost/Hour, Cost/Month, Currency, Notes) are now clickable to sort ascending/descending.
- **Metering Pricing: search** — Search bar filters pricing entries by name, category, unit, or notes with live count.
- **Metering Pricing: Disk Price per GB** — New `disk_cost_per_gb` column for flavor pricing. Ephemeral VM flavors can have per-GB disk cost tracked and displayed.
- **Metering Pricing: Snapshot Operation category** — New `snapshot_op` pricing category for per-snapshot-creation charges.
- **Metering Pricing: Public IP category** — New `public_ip` pricing category for per-IP monthly charges.
- **Metering Pricing: duplicate prevention** — `UNIQUE(category, item_name)` constraint on the pricing table. Custom category validates cross-category overlap on creation.
- **RBAC middleware hardening** — Added 15+ missing resource mappings to the RBAC middleware (`snapshot-runs`, `volumes-with-metadata`, `roles`, `admin`/branding, `backup`, `metering`, `notifications`, `mfa`, `provisioning`, `api-metrics`, `system-logs`, etc.). Removed test endpoints from auth bypass list.

### Fixed
- **Nav colors all same** — Previously every nav item appeared with the same color because the `action_resources` approach checked system-wide permissions (every resource has write actions for admin). Now uses per-item `is_action` flag set in the database.
- **Category duplicates in pricing** — Added unique constraint and cross-category validation. Custom category renamed to "Custom (other)" with helper text.

### Security
- **Sanitized documentation** — Replaced real domain names, project names, and internal IPs in API_REFERENCE.md and QUICK_REFERENCE.md with RFC-reserved example values (`example.com`, `smtp.example.com`)
- **UI placeholder sanitization** — Replaced non-RFC domain in provisioning form placeholder with `example.com`

### Database
- New column: `nav_items.is_action BOOLEAN NOT NULL DEFAULT false`
- New column: `metering_pricing.disk_cost_per_gb NUMERIC(12,6) NOT NULL DEFAULT 0`
- New constraint: `UNIQUE(category, item_name)` on `metering_pricing`
- Updated migration files: `migrate_departments_navigation.sql`, `migrate_metering.sql`, `init.sql`

## [1.18.0] - 2026-02-18

### Added
- **3-Layer Authorization Model** — New department-based visibility layer on top of existing RBAC. Users now belong to a department, and departments control which navigation groups/items are visible in the UI. Roles still control what actions are allowed (security unchanged).
- **Departments** — CRUD for departments (Tier1 Support, Tier2 Support, Tier3 Support, Engineering, Sales, Marketing, Management). Each user assigned to exactly one department.
- **Navigation Catalog** — 7 top-level nav groups (Inventory, Snapshot Management, Change Management & Logs, Customer Onboarding, Metering & Reporting, Admin Tools, Technical Tools) with all existing tabs mapped as nav items. Admin-managed catalog stored in DB.
- **Department Visibility** — Checkbox matrix to control which nav groups and items are visible per department. Toggling a group toggles all items within it.
- **Per-User Visibility Overrides** — Optional grant/deny overrides per user per nav item, for edge cases where a user needs more or fewer items than their department allows.
- **Grouped Navigation Bar** — New 2-level frontend navigation: top-level group pills + tab items within the active group. Falls back to legacy flat tab bar if navigation data is not yet available.
- **`/auth/me/navigation` endpoint** — Single API call returns user profile (department, role), nav tree (groups → items), and permission list. This is the frontend's single source of truth after login.
- **Backend API endpoints** — Full CRUD for departments, nav groups, nav items, department visibility, user-department assignment, per-user overrides, and a bulk visibility matrix for the admin UI.
- **Admin UI tabs** — Three new sub-tabs under Admin → Authentication Management: Departments, Navigation Catalog, Department Visibility editor.
- **User table department column** — Users tab now shows a department dropdown to assign users directly.
- **Migration SQL** — `db/migrate_departments_navigation.sql` creates all new tables, seeds departments/groups/items, and grants all departments full visibility (backward compatible — nothing hidden until admin changes it).
- **Renamed "CCC Authentication Management"** — Now "Authentication Management" (white-label friendly).

### Database
- New tables: `departments`, `nav_groups`, `nav_items`, `department_nav_groups`, `department_nav_items`, `user_nav_overrides`
- New column: `user_roles.department_id` (FK to departments)
- New role_permissions: `departments:read/admin`, `navigation:read/admin` for all roles

## [1.17.1] - 2026-02-19

### Fixed
- **Light mode readability** — Fixed all CSS variable fallbacks in ReportsTab and ResourceManagementTab to use light-mode defaults (borders, backgrounds, text colors) so both tabs are readable in light mode
- **Flavor Usage report** — Now fetches full flavor catalog via `list_flavors()` to resolve flavor names, vCPUs, RAM, and disk instead of relying on incomplete server embed data that often only contains UUIDs
- **Admin permissions tab** — Expanded MAIN_UI_RESOURCES to 31 resources so the permissions management UI shows all tabs (reports, resources, metering, provisioning, notifications, backup, drift, tenant_health, security_groups, dashboard, mfa, branding)
- **VM Report disk showing 0 GB** — Volume-backed instances now correctly show storage via attached volumes; added "Volume Storage (GB)" and "Total Storage (GB)" columns

### Enhanced
- **Domain Overview report** — Complete rewrite with full quota aggregation across all projects per domain: vCPUs, RAM, instances, volumes, storage, networks, floating IPs with utilization percentages; added active/shutoff VM counts, network counts, and floating IP counts
- **VM Report (new)** — Added 16th report type: comprehensive VM details with name, status, power state, flavor specs, hypervisor, fixed/floating IPs, attached volumes, tenant/domain, availability zone, key pair, and image ID
- **VM Report quota context** — Added per-project quota vs usage columns: vCPU Quota/Used, RAM Quota/Used (MB), Storage Quota/Used (GB), Instance Quota/Count; pre-aggregates usage from all servers and volumes per project
- **Resource Management notifications** — All create, delete, update, and quota operations now fire notification events (`resource_created`, `resource_updated`, `resource_deleted`) through the notification system with email delivery for immediate subscribers
- **Resource Management audit log** — New "Audit Log" section in the Resource Management sidebar showing a filterable activity log (24h/7d/30d/90d) of all resource provisioning actions with actor, action type, resource details, IP address, and result status
- **New notification event types** — Added `resource_created`, `resource_updated`, and `report_exported` to the valid event types for subscription

### Added
- **Technical role** — New RBAC role between admin and operator: read access on all resources, write access on resources/provisioning/networks/flavors/snapshots, no delete or admin permissions. Ideal for technical users who can create tenants and manage resources but cannot perform destructive operations
- **Technical role migration** — `db/migrate_technical_role_permissions.sql` adds the technical role permissions and fills in missing permissions for all roles on newer UI tabs (reports, resources, metering, branding)

## [1.17.0] - 2026-02-19

### Added
- **Reports System** — Comprehensive reporting engine with 15 report types across 6 categories:
  - **Capacity**: Tenant Quota Usage, Capacity Planning
  - **Inventory**: Domain Overview, Resource Inventory, Flavor Usage
  - **Compliance**: Snapshot Compliance, Drift Summary
  - **Billing**: Metering Summary, Cost Allocation
  - **Security**: User & Role Audit, Security Group Audit
  - **Audit**: Activity Log Export, Backup Status, Network Topology, Idle Resources
  - Each report supports JSON preview and CSV export via `?format=csv` parameter
  - Report catalog endpoint (`GET /api/reports/catalog`) with categories and parameter schemas
  - RBAC-gated: `reports:read` permission for admin and superadmin roles
  - Frontend: ReportsTab with category filter chips, search bar, parameter configuration panel, data preview table, and CSV download

- **Resource Management Tool** — Full CRUD operations for 9 OpenStack resource types:
  - **Users**: List, create, delete with role assignment and last-user protection
  - **Flavors**: List, create, delete with in-use protection (shows instance count)
  - **Networks**: List, create (with optional subnet + DHCP), delete
  - **Routers**: List, create (with external gateway), delete, add/remove interfaces
  - **Floating IPs**: List, allocate from external network, release
  - **Volumes**: List, create, delete with attached-volume safety check
  - **Security Groups**: List, create, delete (default SG protected), add/remove rules
  - **Images**: List with status, visibility, size, and format metadata
  - **Quotas**: View and edit compute/network/storage quotas per tenant with live editing grid
  - Context helpers: domain, project, and external network dropdowns for filtering
  - Permission tiers: `resources:read` (viewer), `resources:write` (operator), `resources:admin` (admin)
  - Activity logging for all create/delete operations
  - Frontend: ResourceManagementTab with left sidebar navigation, domain/project filters, per-resource data tables, create forms with validation, and confirmation dialogs for deletions

- **Database Migration**: `migrate_reports_resources.sql` — RBAC permissions for reports and resources modules across all role tiers

### Changed
- **RBAC Resource Map**: Added `reports` and `resources` to the middleware resource map for permission checks
- **Navigation**: Two new admin-only tabs — "📊 Reports" and "🔧 Resources" — added to the tab bar

## [1.16.1] - 2026-02-17

### Fixed
- **Role Assignment — PF9 Compatibility**: Provisioning role dropdown now shows only PF9-compatible tenant roles with proper labels:
  - `member` → "Self-service User"
  - `admin` → "Administrator"
  - `reader` → "Read Only User"
  - Removed `service` role (not a PF9 tenant role — assigning it succeeded via Keystone API but PF9 UI showed no role attached)
  - `/api/provisioning/roles` endpoint now returns only PF9-compatible roles with human-readable `label` field
  - Fallback roles updated from `[member, admin, service]` to `[member, admin, reader]` with labels
- **Welcome Email Not Received**: User email now auto-enables the "Include created user email as recipient" checkbox when entering an email address during provisioning (previously required manual opt-in, causing emails to silently not send)
- **Default Security Group Deletion**: OpenStack auto-created "default" security groups (one per project, protected from deletion) now return a clear 502 error message explaining why deletion failed, instead of silently succeeding while the resource remains
- **Resource Deletion Email — Missing Context**: Deletion notification emails now include Domain name, Tenant/Project name, and "Performed By" (actor) fields. Previously only showed Event Type, Resource name, Severity, and Time

### Added
- **Domain Search / Filter**: Added search bar to Domain Management tab — filters domains by name, description, or ID with result count indicator and "Clear search" link
- **Domain Management — Activity / Audit Log Tab**: New "Activity Log" sub-tab within Domain Management showing a filterable, paginated audit trail of all domain management and resource operations
  - Filters: Action (delete/disable/enable/provision), Resource Type (9 types), Result (success/failure)
  - Columns: Time, Actor, Action (color-coded badge), Resource Type, Resource Name + ID, Domain, Result, IP Address
  - Pagination with 30 entries per page
- **Subnet DHCP & Allocation Pool**: Network provisioning step now includes:
  - DHCP enable/disable toggle (default: enabled)
  - Allocation Pool start/end IP fields for DHCP IP range configuration
  - Backend `create_subnet()` passes `allocation_pools` and `enable_dhcp` to Neutron API
  - Review step displays DHCP status and allocation pool range

### Changed
- **Delete API Endpoints**: All 8 resource deletion endpoints now accept `domain_name` and `project_name` query parameters for enriched audit logging and notification emails
- **Notification System**: `_fire_notification()` now accepts optional `domain_name`, `project_name`, and `actor` parameters for contextual email alerts

## [1.16.0] - 2026-02-18

### Added
- **Customer Provisioning System**: Full-stack tenant onboarding with a guided 5-step wizard
  - **Backend** (`api/provisioning_routes.py`): ~1750-line module with complete OpenStack resource lifecycle — domain, project, user, role, quota, network, subnet, security group creation via Keystone, Nova, Cinder, Neutron APIs
  - **5-Step Wizard UI** (`CustomerProvisioningTab.tsx`): Guided provisioning flow:
    1. **Domain & Project** — Create or reuse existing domains/projects with naming convention enforcement and existence checks
    2. **User & Role** — Create user with dynamically-fetched role dropdown from Keystone (filters internal roles)
    3. **Quotas** — Tabbed quota editor (Compute, Block Storage, Network) matching OpenStack Horizon layout with "Set Unlimited" toggles per field
    4. **Network & Security** — Physical network auto-discovery dropdown from Neutron, VLAN/flat/VXLAN type selector, CIDR/gateway/DNS, security group with custom port rules
    5. **Review & Provision** — Full summary with email opt-in, editable recipient list, customer welcome email template
  - **Database**: New `provisioning_jobs` and `provisioning_steps` tables (`db/migrate_provisioning.sql`) tracking every provisioning run with step-level progress, JSONB quota snapshots, and result IDs
  - **API Endpoints** (`api/provisioning_routes.py`): 12+ new endpoints —
    - `POST /api/provisioning/provision` — execute full provisioning workflow
    - `GET /api/provisioning/jobs` — list provisioning jobs with status
    - `GET /api/provisioning/jobs/{job_id}` — job detail with steps
    - `GET /api/provisioning/roles` — dynamic Keystone role list (filters internal roles like `load-balancer_*`, `heat_stack_*`)
    - `GET /api/provisioning/networks` — physical network discovery from Neutron
    - `GET /api/provisioning/domains` — domain listing with project/user counts
    - `GET /api/provisioning/domains/{id}/inspect` — full resource inspection (projects, users, servers, volumes, networks, routers, floating IPs, security groups)
    - `PUT /api/provisioning/domains/{id}/toggle` — enable/disable domain
    - `DELETE /api/provisioning/domains/{id}` — delete domain with typed "approve delete" confirmation
    - `DELETE /api/provisioning/resources/{type}/{id}` — 8 resource deletion endpoints (servers, volumes, networks, routers, floating_ips, security_groups, users, subnets)
  - **RBAC**: Separate permissions — `provisioning:admin`, `provisioning:tenant_disable`, `provisioning:tenant_delete`, `provisioning:resource_delete` (`db/migrate_tenant_permissions.sql`)
  - **Customer Welcome Email**: HTML template (`notifications/templates/customer_welcome.html`) sent on successful provisioning with email opt-in toggle and editable recipient list

- **Domain Management Tab** (`DomainManagementTab.tsx`): Dedicated domain lifecycle management
  - Domain list with status badges (enabled/disabled), project count, user count
  - **Resource Inspection Panel**: Side-by-side flex layout — compact 320px domain list (reduced columns when inspecting) + full-width inspection panel showing projects, users, servers, volumes, networks, routers, floating IPs, security groups per domain
  - Enable/disable toggle, delete with typed "approve delete" confirmation dialog
  - Full dark mode support with CSS variables

- **Central Activity Log**: Audit trail for all provisioning and domain management operations
  - **Database**: New `activity_log` table (`db/migrate_activity_log.sql`) with indexes on timestamp, actor, action, resource_type, domain_id, result
  - **API Endpoints**: `GET /api/activity-log` with filters (actor, action, resource_type, date range, search), pagination, and sorting
  - **UI** (`ActivityLogTab.tsx`): Filterable, paginated activity log viewer with action badges, result indicators, expandable detail rows
  - Events logged: provisioning (start/complete/fail), domain create/delete/toggle, resource deletion (all 8 types)

- **Notification Event Types**: 4 new notification event types — `resource_deleted`, `domain_deleted`, `domain_toggled`, `tenant_provisioned` — with labels and icons in NotificationSettings.tsx

### Fixed
- **Role Name Bug**: Fixed `ROLE_MAP` in provisioning backend — was mapping `"member"` → `"_member_"` and `"service"` → `"_member_"` (legacy OpenStack convention). PF9 Keystone uses direct role names (`member`, `admin`, `service`). Added case-insensitive role matching as safety net and improved error messages to list available roles on failure
- **Dynamic Role Dropdown**: Frontend role selector now fetches roles dynamically from `/api/provisioning/roles` instead of using a hardcoded list; falls back to hardcoded set if API is unavailable
- **Dark Mode — CSS Variable System**: Declared 25+ `--pf9-*` CSS variables in both `:root` (light) and `:root[data-theme="dark"]` blocks in `index.css`. Variables cover text, backgrounds, borders, badges, toggles, alerts (info/warning/danger/safe), headings, and accent colors. Previously these variables were referenced in inline styles but never declared — all fallbacks were light-mode colors
- **Dark Mode — Customer Provisioning Tab**: Replaced ~50 hardcoded hex color values with CSS variables for full dark mode support across wizard steps, quota editor, info/warning/danger boxes, status badges, toggle switches, buttons, and review panel
- **Dark Mode — Domain Management Tab**: Replaced ~60 hardcoded hex color values with CSS variables for domain list, status badges, action buttons, inspection panel, error boxes, and confirmation dialogs
- **Inspection Panel Layout**: Changed from overlay slide-out (which hid the domain list) to side-by-side flex layout with compact domain table (320px) and flexible inspection panel taking remaining space

### Changed
- **Provisioning Role Validator**: Relaxed from strict enum (`member`/`admin`/`service`) to accept any role name — validated against Keystone at provision time
- **Frontend `user_role` Type**: Changed from `"member" | "admin" | "service"` union to `string` to support dynamic role fetching

## [1.15.1] - 2026-02-17

### Fixed
- **Metering Resource Deduplication**: Resources and Efficiency tabs now use `DISTINCT ON (vm_id)` queries, returning only the latest record per VM instead of showing duplicate rows from each collection cycle (e.g. 12 unique VMs shown instead of 96+ duplicate rows)
- **Overview vCPU Count**: Fixed 0 vCPU display — monitoring service does not return vCPUs, so the metering worker now looks up vCPU counts from the `flavors` table by matching flavor name. Backfilled all existing metering data
- **Snapshot/Efficiency Overview Dedup**: Overview sub-queries for snapshots and efficiency now use `DISTINCT ON` subqueries with 24-hour window (was 1 hour) to avoid stale/missing data

### Added
- **Unified Multi-Category Pricing System**: Complete replacement of the flavor-only pricing with a comprehensive pricing model supporting 7 categories:
  - **Flavor (Compute)**: Auto-populated from OpenStack flavors with "Sync Flavors from System" button (imports all 38 flavors with vCPU/RAM/disk specs)
  - **Storage per GB**: Base storage pricing per gigabyte
  - **Snapshot per GB**: Snapshot storage pricing per gigabyte
  - **Restore per Operation**: Per-restore-job pricing
  - **Volume**: Base per-volume pricing
  - **Network**: Base per-network pricing
  - **Custom**: User-defined pricing entries
  - Each entry supports both **hourly** and **monthly** rates — the system auto-converts between them as needed (monthly ÷ 730 = hourly)
  - New database table `metering_pricing` with `UNIQUE (category, item_name)` constraint
  - New API endpoints: `GET/POST /api/metering/pricing`, `PUT/DELETE /api/metering/pricing/{id}`, `POST /api/metering/pricing/sync-flavors`
  - Legacy compatibility: `GET /api/metering/flavor-pricing` still works (returns flavor category only)
- **Filter Dropdowns**: Project and Domain filters across all metering tabs now use dropdown selects populated from actual data instead of free-text inputs
  - New `GET /api/metering/filters` endpoint returns projects (from metering data), domains, all tenants (from projects table), and flavors (from flavors table)
- **Enhanced Chargeback Export**: Chargeback CSV now includes per-tenant cost breakdown across all pricing categories:
  - Compute cost (flavor-based with fallback to vCPU/RAM rates)
  - Storage cost (per GB × disk allocation)
  - Snapshot cost (per GB × snapshot storage)
  - Restore cost (per operation count)
  - Volume and network costs
  - **TOTAL Cost** column aggregating all categories

### Changed
- **Pricing Tab UI**: Completely redesigned with category-based table, color-coded category badges, quick-add cards for common categories, category filter dropdown, and specs column showing vCPU/RAM/disk for flavor entries
- **DB Schema**: New `metering_pricing` table replaces `metering_flavor_pricing` for unified multi-category pricing (`db/migrate_metering.sql`)

## [1.15.0] - 2026-02-17

### Added
- **Operational Metering System (Phase 1 — Foundation)**: Full-stack metering infrastructure for resource usage, snapshots, restores, API usage, efficiency scoring, and chargeback export
  - **Database** (`db/migrate_metering.sql`): 7 new tables — `metering_config` (single-row global settings with cost model), `metering_resources` (per-VM CPU/RAM/disk/network snapshots), `metering_snapshots` (snapshot storage & compliance), `metering_restores` (restore operations & SLA), `metering_api_usage` (API call volume & latency), `metering_quotas` (per-project quota tracking), `metering_efficiency` (per-VM efficiency scores & classification). RBAC permissions: admin → `metering:read`, superadmin → `metering:read` + `metering:write`
  - **Metering Worker** (`metering_worker/`): New long-lived container that collects metering data on a configurable interval (default 15 min). Data sources: monitoring service (per-VM CPU/RAM/disk/network from PCD Prometheus exporter), database (snapshots, restores), API service (endpoint call counts, latency percentiles). Computes weighted efficiency scores (CPU 40% / RAM 35% / Disk 25%) with classifications: excellent / good / fair / poor / idle. Automatic retention pruning of old records
  - **API Endpoints** (`api/metering_routes.py`): 12 new endpoints —
    - `GET /api/metering/config` — current metering configuration & cost model
    - `PUT /api/metering/config` — update metering settings (superadmin only)
    - `GET /api/metering/overview` — MSP executive dashboard with aggregate totals across all metering categories
    - `GET /api/metering/resources` — per-VM resource usage with project/domain/hours filters
    - `GET /api/metering/snapshots` — snapshot metering with compliance data
    - `GET /api/metering/restores` — restore operation metering
    - `GET /api/metering/api-usage` — API call volume & latency per endpoint
    - `GET /api/metering/efficiency` — per-VM efficiency scores & recommendations
    - `GET /api/metering/export/resources` — CSV export of resource metering
    - `GET /api/metering/export/snapshots` — CSV export of snapshot metering
    - `GET /api/metering/export/restores` — CSV export of restore metering
    - `GET /api/metering/export/api-usage` — CSV export of API usage
    - `GET /api/metering/export/efficiency` — CSV export of efficiency scores
    - `GET /api/metering/export/chargeback` — per-tenant chargeback report with configurable cost model
  - **UI** (`pf9-ui/src/components/MeteringTab.tsx`): New "📊 Metering" top-level tab (admin only) with 7 sub-tabs:
    - **Overview** — MSP executive dashboard: summary cards for VMs metered, total vCPUs/RAM/disk, avg CPU/RAM usage, snapshot totals & compliance, restore stats, API call volume, efficiency distribution. Per-tenant/domain filtering. Configuration summary card
    - **Resources** — per-VM table: VM Name, VM ID, Tenant/Project, Domain, Host, Flavor, vCPUs Allocated, RAM Allocated, Disk Allocated, CPU/RAM/Disk usage percentages, Network RX/TX, Storage I/O. Human-readable byte formatting, tooltips with full IDs
    - **Snapshots** — snapshot table: Snapshot Name, Snapshot ID, Volume Name/ID, Tenant/Project, Domain, Size (GB), Status, Policy, Compliance badge, Created At
    - **Restores** — restore table: Restore ID, Snapshot Name/ID, Target Server Name/ID, Tenant/Project, Domain, Status (color-coded), Duration, Initiated By/At
    - **API Usage** — endpoint table: Method (color-coded badge), Endpoint, Total Calls, Errors, Avg/P95/P99 latency, Interval range
    - **Efficiency** — per-VM table: CPU/RAM/Storage efficiency, Overall Score, Classification badge (colour-coded: green→excellent through red→idle), Recommendation text
    - **Export** — download hub with 6 export cards: Resources, Snapshots, Restores, API Usage, Efficiency, Chargeback Report. All exports honour tenant/project/domain filters. CSV columns use user-friendly headers with raw IDs included
  - **Docker** (`docker-compose.yml`): New `metering_worker` service container with DB, monitoring, and API connectivity. Configurable poll interval via `METERING_POLL_INTERVAL` env var

## [1.14.1] - 2026-02-17

### Added
- **MFA Admin Tab**: New "🔐 MFA" tab in the Admin panel (UserManagement) showing MFA enrollment status for all users
  - Summary cards: total users, MFA enabled count, not enrolled count
  - Full user table with MFA status badges and enrollment dates
  - Info box explaining self-service enrollment flow via the header MFA button
  - Refresh button for live status updates

## [1.14.0] - 2026-02-16

### Added
- **LDAP Backup & Restore**: Extend the backup system to include full LDAP directory backups alongside database backups
  - **Database**: New columns in `backup_config` — `ldap_backup_enabled`, `ldap_retention_count`, `ldap_retention_days`, `last_ldap_backup_at`. New `backup_target` column in `backup_history` (`database` | `ldap`). Migration: `db/migrate_ldap_backup_mfa.sql`
  - **Backup Worker**: Generates LDAP backups via `ldapsearch` → gzip LDIF export. Restores via `gunzip | ldapadd -c`. Independent scheduling and retention enforcement for database and LDAP targets. Container Dockerfile now installs `ldap-utils`
  - **Docker**: `backup_worker` service now receives LDAP credentials (`LDAP_HOST`, `LDAP_PORT`, `LDAP_BASE_DN`, `LDAP_ADMIN_DN`, `LDAP_ADMIN_PASSWORD`) and depends on `ldap` service
  - **API**: `POST /api/backup/run` accepts `target` query param (`database` | `ldap`). `GET /api/backup/history` accepts `target_filter` param. Restore preserves `backup_target` from source backup
  - **UI**: BackupManagement tab now shows separate "Database Backup" / "LDAP Backup" trigger buttons, target filter on history, "Target" column in history table, and LDAP-specific settings card (enable toggle, retention count/days)

- **Multi-Factor Authentication (MFA)**: TOTP-based two-factor authentication with Google Authenticator support
  - **Database**: New `user_mfa` table (username, totp_secret, is_enabled, backup_codes, timestamps). MFA permissions added to admin/superadmin roles
  - **Backend** (`api/mfa_routes.py`): 6 new endpoints —
    - `POST /auth/mfa/setup` — generate TOTP secret + QR code (base64 PNG)
    - `POST /auth/mfa/verify-setup` — confirm enrollment with first TOTP code, returns 8 one-time backup codes
    - `POST /auth/mfa/verify` — login MFA challenge verification (exchanges `mfa_token` for full JWT)
    - `POST /auth/mfa/disable` — disable MFA (requires current TOTP code)
    - `GET /auth/mfa/status` — current user's MFA status
    - `GET /auth/mfa/users` — admin view of all users' MFA enrollment
  - **Login Flow**: Two-step JWT challenge — login returns short-lived `mfa_token` (5 min) when MFA is enabled, client verifies TOTP code, then receives full session JWT
  - **Backup Codes**: 8 one-time recovery codes stored as SHA-256 hashes, consumed on use
  - **UI Login**: MFA code input form with monospace 6-digit entry, "Back to Sign In" cancel flow
  - **MFASettings Component** (`MFASettings.tsx`): Self-service modal for MFA enrollment (QR code scan), setup verification, backup code display/copy, MFA disable with confirmation, and admin user list view
  - **Header Integration**: "🔐 MFA" button in app header opens MFA settings for any authenticated user
  - **Dependencies**: `pyotp==2.9.0` (TOTP), `qrcode[pil]==7.4.2` (QR generation)

## [1.13.0] - 2026-02-16

### Added
- **Database Backup & Restore System**: Full-stack automated database backup management with scheduling, retention enforcement, and one-click restore
  - **Database**: New `backup_config` table (single-row schedule configuration) and `backup_history` table (job log with status tracking). Migration script `db/migrate_backup.sql`. Status constraint includes `pending`, `running`, `completed`, `failed`, `deleted`. Backup type constraint includes `manual`, `scheduled`, `restore`. RBAC permissions: admin gets read/write, superadmin gets admin
  - **Backup Worker** (`backup_worker/`): New long-lived container service that polls `backup_config` every 30s, executes `pg_dump` compressed with gzip at scheduled times (daily/weekly) or for manual jobs. Writes to NFS-mounted backup directory. Enforces retention by count and age after each backup. Handles restore jobs via `gunzip | psql`. Graceful shutdown on SIGINT/SIGTERM
  - **API Endpoints** (`api/backup_routes.py`): 6 new endpoints —
    - `GET /api/backup/config` — current backup configuration
    - `PUT /api/backup/config` — update schedule, retention, NFS path
    - `POST /api/backup/run` — trigger manual backup (prevents duplicates)
    - `GET /api/backup/history` — paginated backup history with status filter
    - `GET /api/backup/status` — compact dashboard summary (running state, total count/size, last backup)
    - `POST /api/backup/restore/{id}` — queue restore from completed backup (superadmin only)
    - `DELETE /api/backup/{id}` — delete backup record and file (superadmin only)
  - **UI Tab** (`BackupManagement.tsx`): New "💾 Backup" tab with three sub-views:
    - **Status**: Dashboard cards (current state, total backups, total size, last backup time), last backup detail card, manual trigger button with duplicate prevention
    - **History**: Paginated table of all backup/restore jobs with status badges, file name, size, duration, initiated-by, and timestamps. Status filter dropdown. Restore and delete action buttons with confirmation dialogs
    - **Settings**: Schedule configuration (enable/disable toggle, schedule type selector, UTC time picker, day-of-week for weekly), retention policy (keep count + max days), NFS storage path. Save/reset with feedback messages. Current config info card
  - **Styling** (`BackupManagement.css`): Full CSS with status bar grid, form fields, toggle switches, table, badges, pagination, confirmation overlay dialog, and dark mode overrides
  - **Docker**: New `backup_worker` service in `docker-compose.yml` with `postgres:16` base image (includes pg_dump/pg_restore), Python venv, NFS volume mount, configurable poll interval
  - **Configuration**: New environment variables — `NFS_BACKUP_PATH` (default: `/backups`), `BACKUP_POLL_INTERVAL` (default: `30`), `BACKUP_VOLUME` (default: `./backups`)

### Fixed
- **Backup DB constraints**: `backup_type` CHECK constraint now includes `'restore'` and `status` CHECK includes `'deleted'` — previously the backup worker would fail when creating restore jobs or marking retention-deleted entries

## [1.12.0] - 2026-02-16

### Added
- **Multi-Worker Concurrency**: Switched from single uvicorn worker to gunicorn with 4 uvicorn workers for parallel request handling, supporting 10+ concurrent users
- **Database Connection Pool** (`api/db_pool.py`): Centralized `ThreadedConnectionPool` (min=2, max=10 per worker) replacing per-request `psycopg2.connect()` calls. Provides `get_connection()` context manager with auto-commit, auto-rollback, and auto-return-to-pool
- **Thread-Safe Performance Metrics**: Added `threading.Lock` to `PerformanceMetrics` class — all read/write operations now use lock-protected snapshots
- **Configurable Pool Sizing**: New env vars `DB_POOL_MIN_CONN` (default 2) and `DB_POOL_MAX_CONN` (default 10) for tuning per-worker pool size

### Fixed
- **Critical Connection Leaks in auth.py**: 6 functions (`get_user_role`, `set_user_role`, `has_permission`, `create_user_session`, `invalidate_user_session`, `log_auth_event`) never closed database connections — leaked 2+ connections per authenticated request
- **Connection Leaks in main.py**: 24 endpoints (`/audit/*`, `/history/*`, `/users`, `/roles`, `/role-assignments`, branding, drift) never called `conn.close()`; 13 more had `conn.close()` outside `try/finally` (leaked on exceptions)
- **Connection Leaks in dashboards.py**: 16 endpoints had `conn.close()` on happy path but no `finally` block
- **Connection Leaks in notification_routes.py**: 6 endpoints had same pattern
- **Connection Leaks in snapshot_management.py**: 22 endpoints — all converted to pool context manager
- **Connection Leaks in restore_management.py**: 16 endpoints — all converted to pool context manager
- **Total**: 97 connection leak sites fixed across 6 files

### Changed
- `api/Dockerfile`: CMD changed from `uvicorn main:app` to `gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --timeout 120`
- `api/requirements.txt`: Added `gunicorn==22.0.0`
- All DB connection functions (`db_conn()`, `get_auth_db_conn()`, `get_db_connection()`) now return connections from the shared pool
- All endpoint handlers now use `with get_connection() as conn:` context manager pattern

## [1.11.0] - 2026-02-16

### Added
- **Email Notifications System**: Full-stack email notification feature with per-user preferences, deduplication, and digest support
  - **Database**: New tables `notification_preferences` (per-user subscriptions by event type), `notification_log` (sent notification tracking with dedup keys), `notification_digests` (daily digest batching), `notification_channels` (SMTP config). Migration script `db/migrate_notifications.sql`. RBAC permissions added for all roles (viewer: read/write, operator: read/write, admin/superadmin: admin)
  - **Notification Worker** (`notifications/`): New microservice container that polls the database for triggerable events and dispatches emails via SMTP. Event collectors for 4 event sources:
    - **Drift events**: Unacknowledged critical/warning/info drift from `drift_events`
    - **Snapshot failures**: Failed or partial runs from `snapshot_runs`
    - **Compliance violations**: Non-compliant volumes from `compliance_details`
    - **Health score drops**: Tenants below configurable threshold from `v_tenant_health`
    - Deduplication via SHA-256 hash of (event_type + resource_id + event_id)
    - Immediate delivery for real-time alerts, daily digest mode for batched summaries
    - Auto-reconnects to database, auto-creates tables on startup
  - **Email Templates** (`notifications/templates/`): 6 Jinja2 HTML templates with responsive design — `drift_alert.html` (severity-colored badges, old→new value diff), `snapshot_failure.html` (created/failed stat cards), `compliance_alert.html` (status badges per volume), `health_alert.html` (score circle with contributing factors), `digest.html` (daily summary with critical/warning/info breakdown), `generic_alert.html` (fallback)
  - **API Endpoints** (`api/notification_routes.py`): 6 new endpoints —
    - `GET /notifications/smtp-status` — SMTP configuration status (no secrets exposed)
    - `GET /notifications/preferences` — current user's notification subscriptions
    - `PUT /notifications/preferences` — bulk upsert subscriptions (event type, severity threshold, delivery mode)
    - `DELETE /notifications/preferences/{event_type}` — remove a subscription
    - `GET /notifications/history` — paginated notification log with filters
    - `POST /notifications/test-email` — send test email to verify SMTP
    - `GET /notifications/admin/stats` — admin-only system-wide notification statistics
  - **UI Tab** (`NotificationSettings.tsx`): New "🔔 Notifications" tab with three sub-views:
    - **Preferences**: Card-based grid for each event type with toggle switches, min severity selector, delivery mode (immediate/digest), email input. Bulk save
    - **History**: Paginated table of sent notifications with status badges (✅ sent, ❌ failed, 📬 digest queued, ⏳ pending), event type filter, subject preview
    - **Settings**: SMTP status display, test email sender, admin stats dashboard with delivery counts, 7-day breakdown by event type with visual bars
    - Full dark mode support, CSS toggle switches, responsive grid layout
  - **Docker**: New `notification_worker` service in `docker-compose.yml`, SMTP env vars added to API service
  - **Configuration**: 11 new environment variables — `SMTP_ENABLED`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS`, `SMTP_FROM_NAME`, `NOTIFICATION_POLL_INTERVAL_SECONDS`, `NOTIFICATION_DIGEST_ENABLED`, `NOTIFICATION_DIGEST_HOUR_UTC`

## [1.10.1] - 2026-02-16

### Fixed
- **Dark Mode**: Comprehensive dark mode fix for Tenant Health View — all text elements (summary card values/labels, compute row values, table cells, detail panel headers/stats, heatmap labels, quota labels, power state labels, status legends, buttons) now have proper contrast on dark backgrounds
- **Quota Fallback**: When OpenStack quota API is unavailable, the detail panel now shows DB-based resource usage bars (Active VMs, Active vCPUs, Active RAM, Volumes In-Use, Volume Storage, Snapshots) with color-coded progress bars instead of just "Quota data unavailable"
- **Heatmap Filtering**: Search input now filters the heatmap view (not just the table view). Typing a tenant name filters heatmap tiles and shows "Filtered by" indicator

### Added
- `ResourceUsageBars` component — DB-driven usage visualization with `UsageBar` sub-component showing percentage-based progress bars with healthy/warning/critical color coding
- New CSS classes for resource usage bars (`.th-usage-grid`, `.th-usage-bar-track`, `.th-usage-bar-fill`, etc.) with full dark mode support

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

cd ..\### Fixed
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
- **Removed hardcoded demo user passwords** in setup_ldap.ps1 — now reads from `VIEWER_PASSWORD`/`OPERATOR_PASSWORD` env vars, or generates random passwords if unset
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

[unreleased]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.16.0...HEAD
[1.16.1]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.16.0...v1.16.1
[1.16.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.15.1...v1.16.0
[1.15.1]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.15.0...v1.15.1
[1.15.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.14.1...v1.15.0
[1.14.1]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.14.0...v1.14.1
[1.14.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.13.0...v1.14.0
[1.13.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.12.0...v1.13.0
[1.12.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.11.0...v1.12.0
[1.11.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.10.1...v1.11.0
[1.10.1]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.10.0...v1.10.1
[1.10.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.9.0...v1.10.0
[1.9.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.7.1...v1.8.0
[1.7.1]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.6.4...v1.7.0
[1.6.4]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.6.3...v1.6.4
[1.6.3]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.6.2...v1.6.3
[1.6.2]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.6.1...v1.6.2
[1.6.1]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/erezrozenbaum/pf9-mngt/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/erezrozenbaum/pf9-mngt/releases/tag/v1.0.0
