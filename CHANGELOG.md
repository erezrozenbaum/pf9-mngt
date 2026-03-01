# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

### Fixed — Migration Planner Phase 4A Hotfixes

- **Route ordering 405 on `/network-mappings/readiness`** — FastAPI was matching `PATCH /{mapping_id}` before `GET /readiness` because the static segment `/readiness` was registered after the parameterized route. Moved `get_network_mappings_readiness` to before the `PATCH`/`DELETE` handlers so static paths take precedence.
- **`GROUP BY` error on subnet-enriched network mappings** — `GET /projects/{id}/network-mappings` used an explicit `GROUP BY` column list that omitted the new Phase 4A columns (`network_kind`, `cidr`, `gateway_ip`, etc.), causing a Postgres error. Replaced with `GROUP BY m.id` (valid because `id` is the primary key — covers all columns via functional dependency).
- **`dns_nameservers` type mismatch on save** — UI state held DNS nameservers as a comma-separated string but the API expects `List[str]`. `saveSubnetDetails` now splits the string into an array before PATCH.
- **Section heading** — "Phase 4A — Data Enrichment" heading in PCD Readiness tab renamed to "Pre-Migration Data Enrichment" to remove internal phase numbering from the operator-facing UI.
- **Network Map Kind column** — Replaced read-only pill with an inline `<select>` dropdown. Selecting Physical / L2 / Virtual now immediately PATCHes the mapping and refreshes the row; no need to open the full Subnet Details panel just to set the kind.

---

## [1.35.0] - 2026-03-01

### Added — Migration Planner Phase 4A: Data Enrichment

- **4A.1 — Network Subnet Details** — The Network Map tab now supports per-network subnet configuration:
  - New columns on `migration_network_mappings`: `network_kind` (physical_managed / physical_l2 / virtual), `cidr`, `gateway_ip`, `dns_nameservers TEXT[]`, `allocation_pool_start`, `allocation_pool_end`, `dhcp_enabled`, `is_external`, `subnet_details_confirmed`
  - New API: `GET /projects/{id}/network-mappings/readiness` — returns confirmed count, missing count, external count, ready status
  - Network Map table now shows a **Kind** pill (Physical / L2 / Virtual) per row
  - Confirmed rows show a **⚙️ Subnet** expand button; external rows show "skip (ext)"; confirmed subnets show "✓ subnet ready"
  - Expandable inline subnet panel per row: network_kind dropdown, CIDR, gateway IP, DNS nameservers, allocation pool start/end, DHCP enabled and Is External checkboxes, Save/Cancel actions
  - Toolbar now shows **🌐 Subnet Details: X/Y** readiness counter
- **4A.2 — Flavor Staging** — New `migration_flavor_staging` table and `FlavorStagingView` component in the PCD Readiness tab:
  - `POST /projects/{id}/flavor-staging/refresh` — queries distinct VM shapes from `migration_vms` and upserts into staging table
  - `GET /projects/{id}/flavor-staging` — returns flavors with ready_count summary
  - `PATCH /flavor-staging/{id}` — edit target_flavor_name, confirmed, skip; supports marking existing flavor by ID
  - `POST /projects/{id}/flavor-staging/bulk-rename` — find-and-replace across `target_flavor_name` with preview mode
  - UI: shape + VM count table, inline name edit, skip checkbox, per-row confirm button, F&R panel, confirmed/total badge
- **4A.3 — Image Requirements** — New `migration_image_requirements` table and `ImageRequirementsView` component:
  - `POST /projects/{id}/image-requirements/refresh` — queries distinct `os_family` from `migration_vms`, upserts with most-common version hint
  - `GET /projects/{id}/image-requirements` — list
  - `PATCH /image-requirements/{id}` — set `glance_image_id`, `glance_image_name`, `confirmed`
  - UI: OS family + version hint + VM count table, inline Glance name and UUID inputs, confirm button, ready badge
- **4A.4 — Per-Tenant User Definitions** — New `migration_tenant_users` table, `TenantUsersView` component, and "👤 Users" tab:
  - `POST /projects/{id}/tenant-users/seed-service-accounts` — auto-creates one `service_account` entry per tenant with `svc-mig-{slug}` username and a 20-char random `temp_password`
  - `GET /projects/{id}/tenant-users` — grouped-by-tenant listing with confirmed_tenant_count
  - `POST /projects/{id}/tenant-users` — create a `tenant_owner` record
  - `PATCH /tenant-users/{id}` — edit username / email / role / confirmed
  - `DELETE /tenant-users/{id}` — remove owner record (service accounts cannot be deleted)
  - UI: Users tab, tenant-grouped table with type badge (🤖 svc / 👤 owner), inline edit, ✓ confirm button, seed-service-accounts action, confirmed-tenants counter

### Infrastructure
- **`db/migrate_phase4_preparation.sql`** — Idempotent migration file for all Phase 4A schema additions (subnet columns, flavor_staging, image_requirements, tenant_users tables). Auto-applied on startup; also registered in `deployment.ps1`.
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
