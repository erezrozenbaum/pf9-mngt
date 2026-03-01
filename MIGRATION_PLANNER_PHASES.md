# Migration Planner — Phase Tracking

> **Auto-updated by Copilot after each completed step.**
> This file is in `.gitignore` — never committed.

---

## Phase 1: Foundation — Source Import & Assessment ✅ COMPLETE
**Status**: DONE (2026-02-25)

### Completed Steps
- [x] **DB schema** — `db/migrate_migration_planner.sql` (15 tables, idempotent)
- [x] **RBAC permissions** — `migration` resource in `init.sql` + live DB (viewer=read, operator=read, technical=read+write, admin=all, superadmin=all)
- [x] **Pure logic engine** — `api/migration_engine.py` (column fuzzy-match, tenant detection 6 methods incl. vCD + cluster, risk scoring 0–100, migration mode classification, bandwidth model 4-constraint, schedule-aware agent sizing)
- [x] **API routes** — `api/migration_routes.py` (25+ endpoints: CRUD projects, RVTools upload 6-sheet parser, VMs with filter/sort/page, tenants, hosts, clusters, stats, risk config, assessment, resets, approve gate, bandwidth, agent rec)
- [x] **Route registration** — `api/main.py` (import, include_router, resource_map)
- [x] **Top-level UI** — `pf9-ui/src/components/MigrationPlannerTab.tsx` (project list, create/delete, sub-nav)
- [x] **ProjectSetup UI** — `pf9-ui/src/components/migration/ProjectSetup.tsx` (topology selector, NIC sliders, agent profile, RVTools upload, bandwidth model display)
- [x] **SourceAnalysis UI** — `pf9-ui/src/components/migration/SourceAnalysis.tsx` (dashboard, VM table, tenants, risk config editor)
- [x] **App.tsx wiring** — Added `migration_planner` to ActiveTab, DEFAULT_TAB_ORDER, import, render block
- [x] **Live DB migration** — 15 tables created, RBAC rows inserted, nav group + item + department visibility
- [x] **Docker rebuild** — pf9_api + pf9_ui rebuilt and restarted, API healthy
- [x] **Navigation/Department visibility** — migration_planning group linked to Engineering, Tier3, Management, Marketing
- [x] **Documentation** — CHANGELOG v1.28.0, ARCHITECTURE.md, ADMIN_GUIDE.md, DEPLOYMENT_GUIDE.md, API_REFERENCE.md, deployment.ps1

### Files Created/Modified (Phase 1)
| File | Action |
|------|--------|
| `db/migrate_migration_planner.sql` | Created — 15 tables + RBAC + nav + dept visibility |
| `db/init.sql` | Modified — RBAC permission seeds |
| `api/migration_engine.py` | Created — pure logic module (~480 lines) |
| `api/migration_routes.py` | Created — API routes (~900+ lines) |
| `api/main.py` | Modified — router registration + resource_map |
| `pf9-ui/src/components/MigrationPlannerTab.tsx` | Created |
| `pf9-ui/src/components/migration/ProjectSetup.tsx` | Created |
| `pf9-ui/src/components/migration/SourceAnalysis.tsx` | Created |
| `pf9-ui/src/App.tsx` | Modified — tab wiring |
| `CHANGELOG.md` | Modified — v1.28.0 |
| `docs/ARCHITECTURE.md` | Modified — migration module + endpoints |
| `docs/ADMIN_GUIDE.md` | Modified — migration planner feature section |
| `docs/DEPLOYMENT_GUIDE.md` | Modified — migration SQL step |
| `docs/API_REFERENCE.md` | Modified — 25+ endpoint docs |
| `deployment.ps1` | Modified — migration SQL in array |

### Phase 1.1 Fixes & Enhancements (v1.28.1)
- [x] **Live bandwidth preview** — Client-side `useMemo` mirrors server engine; cards update instantly on field change
- [x] **Migration Schedule section** — 4 new fields: duration days, working hours/day, working days/week, target VMs/day
- [x] **Schedule-aware agent sizing** — Engine factors in timeline to compute optimal agent count with estimated completion
- [x] **Cluster-based tenant detection** — New `cluster` method as fallback for non-vCD environments
- [x] **Inline tenant editing** — Edit (✏️) button per tenant row, PATCH endpoint with cascading VM updates
- [x] **Tenant rename cascade fix** — PATCH endpoint now reads old name before updating
- [x] **DB migration** — `db/migrate_migration_schedule.sql` (4 schedule columns, idempotent)

| File | Action |
|------|--------|
| `db/migrate_migration_planner.sql` | Modified — added schedule columns to CREATE TABLE |
| `db/migrate_migration_schedule.sql` | Created — ALTER TABLE for existing installs |
| `api/migration_engine.py` | Modified — schedule-aware `recommend_agent_sizing()`, `detect_tenant_cluster()` |
| `api/migration_routes.py` | Modified — schedule fields in UpdateProjectRequest, cluster in detection config, PATCH tenant fix |
| `pf9-ui/src/components/MigrationPlannerTab.tsx` | Modified — 4 schedule fields in MigrationProject interface |
| `pf9-ui/src/components/migration/ProjectSetup.tsx` | Modified — live bandwidth `useMemo`, schedule UI section |
| `pf9-ui/src/components/migration/SourceAnalysis.tsx` | Modified — inline tenant editing |
| `deployment.ps1` | Modified — added migrate_migration_schedule.sql |
| `CHANGELOG.md` | Modified — v1.28.1 entry |
| `docs/API_REFERENCE.md` | Modified — schedule-aware agent sizing docs |
| `docs/ADMIN_GUIDE.md` | Modified — 6 detection methods, live bandwidth, schedule sizing |
| `docs/DEPLOYMENT_GUIDE.md` | Modified — schedule migration step |

### Phase 1.2 Bug Fixes & Data Quality (v1.28.1 hotfixes)
- [x] **Disk capacity always 0** — `build_column_map()` was dropping vDisk columns because the `prefix` allowlist filter did not account for disk-sheet canonical names (`capacity_gb`, `thin_provisioned`, `eagerly_scrub`, `disk_path`, `disk_label`, `datastore`). Fixed by adding disk/NIC/snapshot canonical keys to the prefix allowlist.
- [x] **Network name always empty** — Same root cause; NIC columns (`network_name`, `adapter_type`, `mac_address`, `ip_address`, `connected`) were being filtered out.
- [x] **Tenant detection wrong names** — `_VDC_PATTERN` regex only matched `_VDC_` (uppercase). Real VMware Cloud Director folders use mixed case (`_vDC_`). Broadened pattern to case-insensitive `_[vV][dD][cC]_`.
- [x] **Resource pool showing full path** — `detect_tenant_resource_pool()` was returning the entire path (`/DC/host/cluster/pool`). Fixed to extract only the last segment.
- [x] **Risk Config sub-tab empty** — Frontend was reading `riskConfig?.rules?.risk_weights` but the API returns `riskConfig.rules` directly (rules IS the weights). Fixed the path.
- [x] **vcd_folder missing from SQL default** — `migration_tenant_rules` default `detection_config` in the SQL file did not include `vcd_folder` method. It was only injected at runtime. Added `vcd_folder` as first method and `cluster` as fallback in the SQL default.

### Phase 1.3 VM Detail & Migration Plan (v1.28.2)
- [x] **Expandable VM detail rows** — Click any VM row to expand and see per-disk table (Label, Size GB, Thin, Datastore) and per-NIC table (Adapter, Network, Type, IP, MAC, Up) side by side. New API endpoint: `GET /projects/{id}/vms/{vm_name}/details`.
- [x] **Disk count column** — Main VM table now shows disk count per VM.
- [x] **VM filter: OS Family** — Dropdown filter for windows/linux/other. Server-side `os_family` query param on `GET /vms`.
- [x] **VM filter: Power State** — Dropdown filter for poweredOn/poweredOff/suspended. Server-side `power_state` query param.
- [x] **VM filter: Cluster** — Dropdown filter populated from project clusters.
- [x] **Per-VM time estimation engine** — New `estimate_vm_time()` in `migration_engine.py`. Computes warm (phase-1 full copy at zero downtime + cutover at brief downtime) and cold (full offline copy) hours using `gb_per_hour = (bottleneck_mbps / 8) × 3.6`.
- [x] **Migration plan generator** — New `generate_migration_plan()` builds per-tenant breakdowns (warm/cold counts, phase-1/cutover/total hours, risk distribution) and a daily schedule filling concurrent agent slots.
- [x] **Migration Plan sub-tab** — New "📋 Migration Plan" tab in SourceAnalysis with project summary cards, per-tenant assessment table (expandable with individual VM rows showing warm phase-1/cutover/downtime or cold total/downtime hours), and daily schedule with VM pills.
- [x] **JSON & CSV export** — Download full plan as JSON (complete nested structure) or CSV (flat VM-level rows with tenant, mode, timing, scheduled day).
- [x] **Export plan API** — `GET /projects/{id}/export-plan` fetches all VMs + tenants, computes bandwidth model, calls `generate_migration_plan()`.

| File | Action |
|------|--------|
| `api/migration_engine.py` | Modified — `VMTimeEstimate` dataclass, `estimate_vm_time()`, `generate_migration_plan()` (~200 lines added, now ~1100+ lines) |
| `api/migration_routes.py` | Modified — VM detail endpoint, export-plan endpoint, os_family/power_state filters on list_vms (now ~1900+ lines, 28 endpoints) |
| `pf9-ui/src/components/migration/SourceAnalysis.tsx` | Modified — expandable rows, 3 filters, MigrationPlanView component, compact table styles (~200+ lines added, now ~1200+ lines) |
| `db/migrate_migration_planner.sql` | Modified — `vcd_folder` + `cluster` in default detection_config |
| `CHANGELOG.md` | Modified — v1.28.2 entry |
| `docs/API_REFERENCE.md` | Modified — VM Detail, Export Plan endpoints, updated List VMs params |
| `docs/ADMIN_GUIDE.md` | Modified — expandable rows, plan tab, 28+ endpoints |

### Phase 1.4 Usage Metrics & Data Enrichment ✅ COMPLETE
**Status**: COMPLETE (v1.28.3)

### Completed Work
- [x] **DB migration** — `provisioned_mb`, `in_use_mb`, `in_use_gb`, `network_name`, `os_version` columns on `migration_vms` (via `migrate_migration_usage.sql` + `migrate_migration_networks.sql`).
- [x] **vPartition sheet parser** — `_parse_vpartition_sheet()` extracts per-partition used space per VM; `_update_vm_summaries()` aggregates into `in_use_gb`.
- [x] **OS version extraction** — `extract_os_version()` stores full OS string (e.g. "Microsoft Windows Server 2019 (64-bit)"). Displayed as "OS Version" column in VM table.
- [x] **Network name in VM table** — First NIC `network_name` aggregated into `migration_vms.network_name` by `_update_vm_summaries()`. Shown in VM table and CSV export.
- [x] **IP on all migration modes** — IP column shown for all VMs (warm and cold).
- [x] **Usage columns in UI** — "Used (GB)" and usage % in VM table, migration plan VM rows, and CSV export.

---

## Phase 2: Tenant Scoping, Target Mapping & Capacity Planning ✅ COMPLETE
**Status**: COMPLETE (v1.29.0, 2026-02-27)

> **Rationale**: Phases 2 and 3 are deliberate assessment/planning phases that must complete before any target provisioning (Phase 4). You need to know what's in scope, where it lands in PCD, and how many nodes you need *before* creating resources.

### 2A — Tenant Exclusion & Scoping
- [x] **DB columns** — `include_in_plan BOOLEAN DEFAULT true`, `exclude_reason TEXT` on `migration_tenants` ✅ implemented v1.29.x
- [x] **API** — PATCH tenant include/exclude + reason. All aggregation queries filter on `include_in_plan = true`. ✅ implemented v1.29.x
- [x] **UI** — "Tenant Scope" section with checkboxes per tenant, VM count, allocated/used resources, reason text field; bulk-scope toolbar
- [x] **Summary** — "X / Y tenants in scope" counter in toolbar
- [x] **Pattern-based auto-exclude** — `migration_tenant_filters` table with CRUD API (`GET/POST/DELETE /projects/{id}/tenant-filters`)

### 2B — Target Mapping (Source → PCD)
- [x] **DB columns** — `target_domain_name TEXT`, `target_project_name TEXT`, `target_display_name TEXT` on `migration_tenants`
- [x] **API** — PATCH tenant target mapping fields via UpdateTenantRequest
- [x] **UI** — Inline editing columns: Target Domain | Target Project | Target Display Name. Excluded tenants shown at reduced opacity.

### 2C — Quota & Overcommit Modeling (PCD Side)
- [x] **DB tables** — `migration_overcommit_profiles` seeded with 3 presets: Aggressive (8:1 CPU, 2:1 RAM, 1.3× disk), Balanced (4:1 CPU, 1.5:1 RAM, 1.5× disk), Conservative (2:1 CPU, 1:1 RAM, 2× disk).
- [x] **Quota calculation** — `compute_quota_requirements()` engine: per-included-tenant recommended quota with overcommit ratios + snapshot growth factor.
- [x] **UI** — ⚖️ Capacity tab: profile selector cards, per-tenant quota table (allocated vs recommended).

### 2D — PCD Hardware Node Sizing
- [x] **DB tables** — `migration_pcd_node_profiles` (per node spec), `migration_pcd_node_inventory` (current inventory per project).
- [x] **Sizing engine** — `compute_node_sizing()`: 70% utilization cap IS the HA strategy (no spare N+1/N+2 nodes added on top — headroom itself covers node failure). Returns recommended count, binding dimension, post-migration utilization.
- [x] **UI** — ⚖️ Capacity tab: node profile CRUD editor, existing inventory input, sizing result panel with utilization gauges and HA warnings.

### 2E — PCD Readiness & Gap Analysis
- [x] Connect to PCD via `p9_common` standalone functions (`get_session_best_scope`, `nova_flavors`, `neutron_list`, `glance_images`)
- [x] Fetch PCD flavors, networks, images
- [x] Gap analysis: missing flavor shapes, missing networks, missing OS images, unmapped tenants
- [x] Gap table: `migration_pcd_gaps` with gap_type, severity, resolution, resolved flag
- [x] PCD readiness score computed from gap severity
- [x] UI: 🎯 PCD Readiness tab — settings form, run analysis button, readiness score badge, gap table with "Mark Resolved"

### Phase 2 File Changes

| File | Action |
|------|--------|
| `db/migrate_phase2_scoping.sql` | **Created** — 6 new tables + Phase 2 columns on migration_tenants/migration_projects (idempotent) |
| `db/migrate_migration_planner.sql` | Modified — Phase 2 columns in migration_tenants/migration_projects CREATE TABLE for fresh installs |
| `api/migration_engine.py` | Modified — `OVERCOMMIT_PRESETS`, `compute_quota_requirements()`, `compute_node_sizing()`, `analyze_pcd_gaps()` (~270 lines added) |
| `api/migration_routes.py` | Modified — all Phase 2 endpoints (2A-2E, ~350 lines added); `UpdateTenantRequest` extended; Phase 2E PCD connection via p9_common |
| `pf9-ui/src/components/migration/SourceAnalysis.tsx` | Modified — `Tenant` interface extended; `TenantsView` with scope/bulk/target-mapping; new ⚖️ Capacity + 🎯 PCD Readiness sub-tabs; `CapacityPlanningView` + `PcdReadinessView` components |
| `deployment.ps1` | Modified — `migrate_phase2_scoping.sql` added to migration array |
| `CHANGELOG.md` | Modified — v1.29.0 entry |

### Phase 2 Bug Fixes (v1.29.1)
- [x] **Tenant `id` vs `tenant_id`** — `Tenant` interface now uses `id: number` (actual API-returned DB PK); all checkbox, selection, and edit logic updated
- [x] **Capacity tab blank / `.map is not a function`** — All Phase 2 API responses correctly unwrapped (`.profiles`, `.quota`, `.inventory.current_nodes`, `.sizing`); `setProfile()` body uses `overcommit_profile_name`; `setDefaultProfile()` uses POST upsert
- [x] **PCD Readiness blank on load** — `loadProject()` unwraps `resp.project`; `loadGaps()` unwraps `g.gaps` + `g.readiness_score`
- [x] **Duplicate React keys** — All tenant rows keyed by `t.id`; edit-row fragment given explicit key
- [x] **Sub-nav active border invisible** — `subTabActive` uses `borderBottom` shorthand instead of `borderBottomColor` (which CSS shorthand was overriding)
- [x] **Warm downtime over-counted** — Warm downtime = `warm_cutover_hours` only (phase-1 is a live copy, zero downtime)
- [x] **Column header** — "Warm Phase1" renamed to "Copy / Phase 1"

### Phase 2 Bug Fixes (v1.29.2)
- [x] **Bulk-scope 422 null filter** — `PATCH /tenants/bulk-scope` was passing `null` tenant IDs when selection was empty; added validation guard
- [x] **Pydantic apiFetch error format** — apiFetch now handles both `{detail: string}` and `{detail: [{loc, msg}]}` Pydantic error shapes
- [x] **Capacity field name mismatch** — Backend was returning `vcpu_alloc` / `ram_gb_alloc` but UI expected `vcpu_allocated` / `ram_gb_allocated`; added fallback aliases
- [x] **PCD Readiness info banner** — Added PCD connection info banner showing credentials source

### Phase 2 Bug Fixes (v1.29.3)
- [x] **Route ordering 422** — `PATCH /tenants/{tenant_id}` captured `"bulk-scope"` as int param; fixed with `:int` Starlette path converter
- [x] **Overcommit profile object as React child** — `compute_quota_requirements` returns `profile: <dict>`; UI used `{quotaResult.profile}` raw in JSX → crash. Fixed to extract `profile.profile_name`
- [x] **Cold copy column showed `—`** — Cold migration total time (`cold_total_hours`) was not being rendered; column now shows correct time for cold VMs

### Phase 2 Bug Fixes (v1.29.4)
- [x] **Migration Plan export included excluded tenants** — All three export routes (`export-plan`, `export-report.xlsx`, `export-report.pdf`) were fetching ALL tenants/VMs regardless of `include_in_plan`. Fixed with `JOIN migration_tenants WHERE include_in_plan = true`
- [x] **Project Summary excluded count** — Added `excluded_tenants` field + warning banner "⚠️ N tenants excluded from this plan"
- [x] **Capacity tab auto-sizing on mount** — `load()` now auto-calls `/node-sizing` on mount so result is populated without clicking "Compute Sizing"
- [x] **PCD Readiness `readinessScore.toFixed` crash** — PostgreSQL NUMERIC → Python Decimal → JSON string; `setReadinessScore` now wraps with `Number()` to coerce

### Phase 2 Bug Fixes (v1.29.5)
- [x] **Cold downtime calculation wrong** — `cold_downtime_hours` was `cold_total` only (copy phase). Fixed to `cold_total + warm_cutover` — cold keeps VM offline for full copy + boot/connect overhead
- [x] **Cold "Cutover/Cold" column showed `—`** — Cold migrations have the same boot/connect phase; column now always shows `warm_cutover_hours`
- [x] **PCD Readiness missing capacity section** — `PcdReadinessView` now loads `/quota-requirements` + `/node-sizing` on mount; shows migration quota needs, nodes recommended (with HA), existing nodes, additional needed, post-migration CPU/RAM util, binding dimension, warnings, and Cinder storage requirement

### Phase 2 Bug Fixes (v1.29.6)
- [x] **Node sizing ignores actual PCD cluster capacity** — New `GET /projects/{id}/pcd-live-inventory` backend route queries `hypervisors` + `servers` + `flavors` + `volumes` tables for live node count, vCPU/RAM totals, and already-committed resources. Capacity tab shows green "Live PCD Cluster" panel with "📥 Sync to Inventory" button
- [x] **Save Inventory / Compute Sizing broken** — Form only had `current_nodes`; now has `current_nodes`, `current_vcpu_used`, `current_ram_gb_used`; Save now POSTs all fields and auto-calls Compute Sizing. Buttons renamed "💾 Save & Recompute" / "📐 Compute Only"
- [x] **PCD Readiness gaps show no explanation** — Added "Why / Details" column to gaps table showing key `details` dict fields (required vcpu, vm count, ram, network name) with collapsible affected VM list
- [x] **Inventory form missing used-resource fields** — Capacity tab inventory form now has vCPU used and RAM used inputs alongside node count

### Phase 2 Bug Fixes (v1.29.7)
- [x] **Node sizing driven by Cinder disk** — `compute_node_sizing()` was computing `nodes_for_disk` and taking `max(cpu, ram, disk)`. Cinder block storage is independent infrastructure — node count only driven by vCPU + RAM. Fixed: `nodes_additional = max(nodes_for_cpu, nodes_for_ram)`. Disk now reported as `disk_tb_required` separate from compute sizing. UI shows Cinder storage requirement as informational line "provision via storage backend"

---

## Phase 2.8 — Pre-Phase 3 Polish ✅ COMPLETE
**Status**: COMPLETE (v1.30.0, 2026-02-27)

> Enhancements and fixes identified after Phase 2 review, required before proceeding to Phase 3 wave planning.

### 2.8A — Export Download Fix (Auth-Aware)
- [x] **PDF & Excel export broken** — `downloadXlsx` / `downloadPdf` in `MigrationPlanView` used direct `<a>` element navigation which omits the `Authorization: Bearer` header. Replaced with `downloadAuthBlob()` helper: `fetch()` with auth header → blob → `URL.createObjectURL()` → anchored download. Both buttons now correctly download the file.

### 2.8B — Gap Analysis Action Report
- [x] **Downloadable PCD Readiness report** — New `GET /projects/{id}/export-gaps-report.xlsx` and `GET /projects/{id}/export-gaps-report.pdf` endpoints. Excel: 3 sheets — Executive Summary (score, gap counts, quota, sizing), Action Items (unresolved gaps with effort estimate), All Gaps. PDF: landscape A4 with severity colour-coded tables. Download buttons added to PCD Readiness tab gaps section.
- [x] **`generate_gaps_excel_report()`** and **`generate_gaps_pdf_report()`** in `export_reports.py`.

### 2.8C — Auto-Detect PCD Node Profile from DB
- [x] **Manual node profile entry removed as primary path** — New `GET /projects/{id}/pcd-auto-detect-profile` queries the `hypervisors` inventory table to identify dominant node type (most common vCPU + RAM configuration). Returns suggested profile with `cpu_cores`, `cpu_threads`, `ram_gb`, `storage_tb`, node count.
- [x] **"🔍 Auto-Detect from PCD" button** in Capacity tab node profiles section: one click fetches dominant node type and pre-fills the new-profile form. Manual entry remains available as a fallback for environments without inventory sync.

### 2.8D — Risk Breakdown per VM
- [x] **`risk_reasons` already stored** in `migration_vms.risk_reasons JSONB` (populated by `compute_risk()` during assessment). Added `risk_reasons?: string[]` to TypeScript `VM` interface.
- [x] **Risk factors display** — Expanded VM detail row now shows a "⚠️ Risk Factors" section listing each rule that fired with its score contribution (e.g. "Large disk: 2400 GB (≥ 2000 GB) (+10)").

### 2.8E — Plan Approval Gate (already present, confirmed)
- [x] **"✅ Approve for Migration" button** already present in SourceAnalysis.tsx toolbar. Project status column (`approved_by`, `approved_at`) already tracked in DB. No additional work required.

### Phase 2.8 File Changes

| File | Action |
|------|--------|
| `api/export_reports.py` | Modified — `generate_gaps_excel_report()` + `generate_gaps_pdf_report()` added (~200 lines) |
| `api/migration_routes.py` | Modified — 3 new routes: `pcd-auto-detect-profile`, `export-gaps-report.xlsx`, `export-gaps-report.pdf`; updated import |
| `pf9-ui/src/components/migration/SourceAnalysis.tsx` | Modified — `downloadAuthBlob()` helper; fixed `downloadXlsx`/`downloadPdf`; `risk_reasons` in VM interface + expanded row; auto-detect button + handler in CapacityPlanningView; gap download buttons in PcdReadinessView |
| `CHANGELOG.md` | Modified — v1.30.0 entry |

---

## Phase 2.9 — Performance-Based Node Sizing ✅ COMPLETE
**Status**: COMPLETE (v1.30.1, 2026-02-27)

> Enhancement to Phase 2D: replace allocation ÷ overcommit estimate with actual VM CPU/RAM utilisation from RVtools performance data.

### Problem
Node sizing was computing physical demand as `SUM(cpu_count) / overcommit_ratio` — treating every configured vCPU as if it ran at 100% of its allocation. For the PoC cluster (1,371 vCPU allocated across 324 VMs), this gave a demand of ~343 vCPU → 13 new nodes needed. But vSphere was only running at 50% on those same 13 nodes, and we have the actual per-VM utilisation in DB.

### Root Cause
RVtools `vCPU` sheet gives `cpu_usage_percent` (v1.28.3 already parses this). The correct physical demand is:
```
actual_vcpu = SUM(cpu_count × cpu_usage_percent / 100)   ← already physical, no overcommit division
actual_ram  = SUM(ram_mb × memory_usage_percent / 100) / 1024
```
`cpu_usage_percent` reflects real scheduler pressure on the host — dividing again by overcommit would double-penalise.

### Changes
- [x] **New VM footprint query** in `get_node_sizing()` — single query fetches perf fields (`actual_vcpu_used`, `actual_ram_gb`, `vms_with_cpu_perf`) **and** allocation fallback (`vm_vcpu_alloc`, `vm_ram_gb_alloc`) + `source_node_count` in one pass.
- [x] **Three-tier basis selection**:
  - `actual_performance` — when ≥50% of powered-on VMs have `cpu_usage_percent` data (most accurate)
  - `allocation` — fallback: SUM(cpu_count) ÷ overcommit ratio (no perf data)
  - `quota` — last resort: tenant quota totals (no RVtools data at all)
- [x] **Metadata returned** — `sizing_basis`, `perf_coverage_pct`, `vm_vcpu_actual`, `vm_ram_gb_actual`, `vm_vcpu_alloc`, `vm_ram_gb_alloc`, `source_node_count` added to sizing response.
- [x] **UI: `SizingResult` interface extended** — new optional fields for all metadata.
- [x] **UI: Sizing basis badge** — green pill "📊 Based on actual VM performance data · 100% VM coverage · 125 vCPU running of 1371 allocated · 622 GB active of 4616 GB allocated" or amber pill "⚠️ Based on vCPU allocation ÷ overcommit (no performance data)" shown below the resource table.
- [x] **UI: HW Demand column tooltip** — conditional text explains the basis used (actual utilisation vs allocation vs quota).
- [x] **UI: HW Demand footnote** — shows formula used (actual utilisation × (1+peak%) vs allocation ÷ overcommit × (1+peak%)).

### Verified Numbers (PoC cluster, project 9440b8cb)
| Metric | Old (allocation ÷ overcommit) | New (actual performance) |
|--------|------------------------------|-------------------------|
| vCPU demand (before peak) | 343 vCPU | **125 vCPU** |
| RAM demand (before peak) | 4,616 GB | **622 GB** |
| Demand + 15% peak | 394 vCPU / 5,309 GB | **144 vCPU / 716 GB** |
| PCD nodes to add | +9 (13 total) | **+2 (6 total)** |
| Post-migration CPU util | ~55% | **~45%** ✅ |
| Perf coverage | — | **100% (324/324 VMs)** |

### Phase 2.9 File Changes

| File | Action |
|------|--------|
| `api/migration_routes.py` | Modified — `get_node_sizing()`: new VM footprint query + three-tier basis selection + metadata fields |
| `pf9-ui/src/components/migration/SourceAnalysis.tsx` | Modified — `SizingResult` interface + sizing basis badge + updated tooltip + updated footnote formula |
| `CHANGELOG.md` | Modified — v1.30.1 entry |

---

## Phase 2.10 — Pre-Phase 3 Foundations ✅ COMPLETE
**Status**: COMPLETE (v1.31.0 foundations + v1.31.1 pre-seeding fix)

> All items below are required inputs for Phase 3 wave planning. Building waves without these foundations produces a plan with no execution state, no dependency ordering, and no way to split large projects into manageable workstreams.

---

### 2.10A — Fix Phase 2A Tracking (2 unchecked items already implemented)
The Phase 2A section has two items marked `[ ]` that are definitively implemented (bulk-scope, export filtering, v1.29.2–v1.29.4 bug fixes all depend on them). Mark correct.
- [x] Mark `include_in_plan DB columns` as ✅ in tracking
- [x] Mark `PATCH include/exclude API` as ✅ in tracking

---

### 2.10B — Per-VM Migration Status
Phase 3 assigns VMs to waves. Without a status column, the wave planner has no way to know which VMs are already assigned, already migrated, or should be skipped.

**DB**: `migration_status VARCHAR DEFAULT 'not_started'` on `migration_vms`
Values: `not_started` | `assigned` | `in_progress` | `migrated` | `failed` | `skipped`

**API**: `PATCH /projects/{id}/vms/{vm_id}/status` — update single VM status with optional `status_note`
**Bulk API**: `PATCH /projects/{id}/vms/bulk-status` — update many VMs at once (for marking skipped/migrated out-of-band)
**UI**: Status pill column in VM table (colour-coded); filter by status; bulk-status from VM table toolbar

---

### 2.10C — Per-VM Migration Mode Override
The engine auto-classifies warm/cold based on risk score. Operators always know some VMs better than the model: "force warm on this one even though risk is high" or "always cold this DB VM regardless".

**DB**: `migration_mode_override VARCHAR NULL` on `migration_vms` — `NULL` = use engine classification; `'warm'` or `'cold'` = forced
**API**: `PATCH /projects/{id}/vms/{vm_id}/mode-override` with `{ override: 'warm' | 'cold' | null }`
**UI**: Small override toggle in VM expanded row (🔓 Override button → warm/cold/auto selector); VM table shows lock icon 🔒 when override active

---

### 2.10D — Tenant Migration Priority
Tenants are in/out of scope but have no ordering. Phase 3 wave planning needs to know which tenants go in cohort 1 vs cohort 3. A simple integer is enough.

**DB**: `migration_priority INTEGER DEFAULT 999` on `migration_tenants` (lower = earlier)
**API**: `PATCH /tenants/{id}` already exists — add `migration_priority` to `UpdateTenantRequest`
**UI**: Priority column in Tenants tab — editable number field; sort tenants by priority; visual indicator for unset (showing 999 as "—")

---

### 2.10E — VM Dependency Annotation
Wave planning breaks app stacks if a web-tier VM migrates before its database. Operators need to annotate "VM A cannot start until VM B is migrated". Even manual annotation is enough — no auto-detection required.

**DB**: `migration_vm_dependencies` table
```sql
CREATE TABLE migration_vm_dependencies (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL,
    vm_id INTEGER NOT NULL REFERENCES migration_vms(id),
    depends_on_vm_id INTEGER NOT NULL REFERENCES migration_vms(id),
    dependency_type VARCHAR DEFAULT 'must_complete_before',  -- extensible
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```
**API**: `GET/POST/DELETE /projects/{id}/vm-dependencies`
**UI**: In VM expanded row — "➕ Add Dependency" button opens a VM search picker; shows dependency list as `→ [VM name]` badges; circular dependency validation

---

### 2.10F — Source Network → PCD Network Mapping
Phase 2B maps tenant → PCD project. But cutover requires knowing which source VMware network each VM NIC should connect to on PCD. We have `network_name` per VM already; PCD networks come from gap analysis.

**DB**: `migration_network_mappings` table
```sql
CREATE TABLE migration_network_mappings (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_network_name TEXT NOT NULL,
    target_network_name TEXT NOT NULL,
    target_network_id TEXT,          -- PCD UUID if known
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, source_network_name)
);
```
**API**: `GET/POST/DELETE/PATCH /projects/{id}/network-mappings`
Auto-populate: on load, extract all distinct `network_name` values from `migration_vms` (powered-on, in-scope tenants) and create unmapped entries. User fills in the PCD target.
**UI**: New "🔌 Network Map" sub-tab in SourceAnalysis — table of source networks with editable target network field; unmapped networks shown with ⚠️ warning; shows VM count per source network

---

### 2.10G — Migration Cohorts (Sub-Plans within a Project) ⭐ KEY FEATURE
The headline feature. Allows splitting 130 tenants / 400 VMs into independent, ordered planning groups (cohorts), each with its own schedule, team, and wave plan — all under one project with unified source inventory and aggregate reporting.

**Architecture**:
```
migration_projects (1)
    └── migration_cohorts (many)       ← NEW
            └── migration_tenants (many, one cohort per tenant)
                    └── migration_waves (many, within one cohort — Phase 3)
                            └── migration_wave_vms (many — Phase 3)
```

**DB**:
```sql
CREATE TABLE migration_cohorts (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES migration_projects(project_id),
    name TEXT NOT NULL,
    description TEXT,
    cohort_order INTEGER DEFAULT 999,    -- execution sequence (1 = first)
    status VARCHAR DEFAULT 'planning',   -- planning|ready|executing|complete|paused
    scheduled_start DATE,
    scheduled_end DATE,
    owner_name TEXT,                     -- team/person responsible
    depends_on_cohort_id INTEGER REFERENCES migration_cohorts(id),  -- gates: must complete before this starts
    overcommit_profile_override TEXT,    -- optional: override project profile for this cohort
    agent_slots_override INTEGER,        -- optional: different concurrency for this cohort
    notes TEXT,
    approved_at TIMESTAMPTZ,
    approved_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

`migration_tenants`: add `cohort_id INTEGER REFERENCES migration_cohorts(id)` — NULL = unassigned

**API**:
- `GET /projects/{id}/cohorts` — list cohorts with per-cohort VM count, tenant count, status
- `POST /projects/{id}/cohorts` — create cohort
- `PATCH /projects/{id}/cohorts/{cid}` — update name/dates/owner/order/deps
- `DELETE /projects/{id}/cohorts/{cid}` — delete (must be empty)
- `POST /projects/{id}/cohorts/{cid}/assign-tenants` — assign tenant IDs to cohort `{ tenant_ids: [1,2,3] }`
- `GET /projects/{id}/cohorts/{cid}/summary` — rollup: tenant count, VM count, total vCPU/RAM/disk, estimated migration hours, status breakdown

**UI**:
- New **"🗃️ Cohorts"** sub-tab in SourceAnalysis (between Tenants and Capacity)
- **Cohort list panel** (left): ordered cards showing cohort name, dates, owner, tenant count, VM count, status badge, dependency arrow (e.g. "after Cohort 1")
- **Assignment panel** (right): tenant list with checkboxes + "Assign to Selected Cohort" button; unassigned tenants shown with ⚠️
- **Quick-assign flows**:
  - "Auto-assign by Risk" — high-risk tenants → last cohort, low-risk → first
  - "Auto-assign by Priority" — uses `migration_priority` from 2.10D
  - "Assign All Unassigned → New Cohort" — bulk convenience
- **Cohort summary cards**: inline VM count, allocated vCPU/RAM, estimated window hours
- **Gantt preview** (simple): horizontal bars showing cohort dates on a timeline, dependency arrows between them
- **Dependency gate lock**: cohorts with `depends_on_cohort_id` show 🔒 when predecessor not complete
- **Cohorts remain optional**: if user creates no cohorts, all existing functionality works unchanged. The Wave Planner (Phase 3) treats the full project as a single implicit cohort.

---

### 2.10H — Per-Tenant Readiness Checklist
The project-level "✅ Approve" button exists but there's no per-tenant readiness verification before waves start. The checklist auto-populates based on what's configured and what gaps exist.

**DB**: `migration_tenant_readiness` table
```sql
CREATE TABLE migration_tenant_readiness (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES migration_tenants(id),
    check_name TEXT NOT NULL,          -- 'target_mapped', 'network_mapped', 'quota_set', etc.
    check_status VARCHAR DEFAULT 'pending',  -- pending|pass|fail|skipped
    checked_at TIMESTAMPTZ,
    notes TEXT
);
```

Checks auto-derived (computed, not manually set):
- `target_mapped` — `target_domain_name IS NOT NULL`
- `network_mapped` — all VM networks for this tenant have an entry in `migration_network_mappings`
- `quota_sufficient` — tenant quota ≤ cohort/project capacity
- `no_critical_gaps` — no unresolved critical PCD gaps affecting this tenant's VMs
- `vms_classified` — all powered-on VMs have a migration mode (warm/cold/override)

**API**: `GET /projects/{id}/tenants/{tid}/readiness` + `GET /projects/{id}/cohorts/{cid}/readiness-summary`
**UI**: Readiness column in Tenants tab (🟢/🟡/🔴 per tenant); expandable to show which checks passed/failed; cohort-level readiness score in cohort cards

---

### Phase 2.10 DB Migration
Single file: `db/migrate_cohorts_and_foundations.sql` — idempotent `ALTER TABLE` + `CREATE TABLE IF NOT EXISTS` for all items above.

### Phase 2.10 Summary Table

| Item | DB | API | UI | Blocker for Ph3? |
|------|----|-----|-----|-----------------|
| 2.10A Fix tracking | — | — | — | No |
| 2.10B VM status | `migration_vms.migration_status` | PATCH vm status + bulk | Status pill + filter | **Yes** |
| 2.10C Mode override | `migration_vms.migration_mode_override` | PATCH vm mode-override | Override toggle in expanded row | No |
| 2.10D Tenant priority | `migration_tenants.migration_priority` | existing PATCH | Priority column (editable) | No |
| 2.10E VM dependencies | `migration_vm_dependencies` table | GET/POST/DELETE | Dependency badges in expanded row | No |
| 2.10F Network mapping | `migration_network_mappings` table | GET/POST/PATCH/DELETE | 🔌 Network Map sub-tab | **Yes** |
| 2.10G Cohorts | `migration_cohorts` + cohort_id FK | Full CRUD + assign + summary | 🗃️ Cohorts sub-tab + Gantt preview | **Yes** |
| 2.10H Tenant readiness | `migration_tenant_readiness` table | GET readiness | 🟢/🟡/🔴 in Tenants tab | No |

### Phase 2.10.1 — Target Name Pre-seeding Fix (v1.31.1)
- [x] **DB** — `db/migrate_target_preseeding.sql`: adds `confirmed BOOLEAN DEFAULT false` to `migration_network_mappings`, `target_confirmed BOOLEAN DEFAULT false` to `migration_tenants`; pre-seeded 122 existing tenant rows with `target_domain_name = target_project_name = tenant_name, target_confirmed=false`; marks existing network rows that already have a target name as `confirmed=true`.
- [x] **API** — Network auto-seed now inserts `target_network_name = source_network_name, confirmed=false` (was blank). Tenant detect-upsert pre-seeds names on INSERT only — `ON CONFLICT DO UPDATE` never overwrites operator edits. `unmapped_count` → `unconfirmed_count`. `_compute_tenant_readiness()`: `target_mapped` returns `pending` when seeded-but-unconfirmed; `network_mapped` returns `pending` while unreviewed networks exist (not `fail`).
- [x] **UI** — Unconfirmed rows highlighted amber (#fffbeb); ⚠️ badge on `target_domain_name` / `target_project_name`; Network Map action button: **Confirm** (unconfirmed+clean) / **Save** (edited) / **✓** (confirmed). Saving sets `confirmed=true`; `confirmed=false` auto-seeded rows show ⚠️ review status.

### Phase 2.10.3 — Bulk Find & Replace for Tenant Target Names (v1.31.3 + v1.31.4)
- [x] **API** — `POST /projects/{id}/tenants/bulk-replace-target` — find-and-replace across `target_domain_name` or `target_project_name`. Literal substring, case-insensitive default, preview mode (dry-run), `unconfirmed_only` flag. Affected rows set to `target_confirmed=false`. Fixed scope bug in v1.31.4 (`loadTenants` not in scope → changed to `onRefresh()` prop).
- [x] **UI** — "🔍 Find & Replace" button in Tenants tab toolbar opens a collapsible panel: field picker, Find/Replace inputs, case-sensitive + unconfirmed-only checkboxes, Preview button (shows diff table), Apply button. After apply calls `onRefresh()`.

### Phase 2.10.4 — Bulk Find & Replace for Network Mappings (v1.31.5)
- [x] **API** — `POST /projects/{id}/network-mappings/bulk-replace` — same find/replace logic over `target_network_name`. Preview + apply modes, sets `confirmed=false` on affected rows.
- [x] **UI** — 🔍 Find & Replace panel added to Network Map tab toolbar with identical UX to Tenants tab.

### Phase 2.10.5 — Confirm All (v1.31.6)
- [x] **API** — `POST /projects/{id}/tenants/confirm-all` — sets `target_confirmed=true` for all unconfirmed tenant rows. `POST /projects/{id}/network-mappings/confirm-all` — sets `confirmed=true` for all unconfirmed network mappings. Both return `{ affected_count }`.
- [x] **UI** — "✓ Confirm All" green button in both Tenants and Network Map toolbars. Shows confirmation dialog, runs endpoint, refreshes. Count of affected rows shown in toast/inline feedback.

### Phase 2.10.6 — Domain/Project Descriptions + Stale Network Fix (v1.31.7)
- [x] **DB** — `db/migrate_descriptions.sql`: `ALTER TABLE migration_tenants ADD COLUMN IF NOT EXISTS target_domain_description TEXT`.
- [x] **API** — `target_domain_description` added to `UpdateTenantRequest` and `GET /tenants` response. `target_display_name` (project description) and `target_domain_description` seeded from project/domain name on upsert. Stale network mappings deleted after re-upload: any mapping whose `source_network_name` is not present in the new VM dataset is purged.
- [x] **UI** — Tenants table gains two new columns: **Domain Desc.** (editable, maps to `target_domain_description`) and **Proj. Desc.** (editable, maps to `target_display_name`). Column order: Target Domain → Domain Desc. → Target Project → Proj. Desc. Edit row exposes all four inputs.

### Phase 2.10.7 — Clear RVTools Fix + Network Map Edit Improvements (v1.31.8)
- [x] **API** — `DELETE /projects/{id}/rvtools` ("Clear RVTools Data") was missing `migration_network_mappings` from its table purge list; confirmed mappings silently survived clear+re-upload. Fixed.
- [x] **UI** — Confirmed network map rows now show **✏️ Edit** button. Clicking makes an API call to un-confirm the row (`PATCH confirmed=false`) so the orange Confirm button reappears for re-editing.

### Phase 2.10.8 — Domain Desc Seeding + F&R All Fields + Network Map Local Edit (v1.31.9)
- [x] **API** — `target_domain_description` now seeded from `tenant_name` on upsert (same pattern as project desc ← project name). Allowed fields for `bulk-replace-target` extended to all 4: `target_domain_name`, `target_domain_description`, `target_project_name`, `target_display_name`.
- [x] **UI** — F&R field picker now has 4 options (Target Project Name, Project Description, Target Domain Name, Domain Description). Network Map **✏️ Edit** no longer makes an API call — entering edit mode is purely local. Save/Confirm writes the new value; Cancel discards without touching the server. Fixed latent bug where Confirm on an unedited row sent `null` as target network name.

### Phase 2.10.9 — Editable VLAN ID on Network Map (v1.31.10)
- [x] **API** — `PATCH /network-mappings/{id}` already accepted `vlan_id`; no change needed.
- [x] **UI** — VLAN ID column switches to a number input when a row enters edit mode (via ✏️ Edit or by typing in the network name). Pre-filled with current value. Included in the PATCH payload on Save/Confirm. Blank = `null` (clears the VLAN).

### Phase 2.10.10 — VLAN ID edit fully accessible (v1.31.11)
- [x] **API** — Added `vlan_id` to the allowlist for `PATCH /networks/{id}` (Networks tab) — was silently ignored before.
- [x] **UI (Networks tab)** — Edit row now includes a VLAN ID number input (was static text). Sends `vlan_id` as integer; blank sends `null`.
- [x] **UI (Network Map)** — VLAN input now visible for ALL unconfirmed rows (not just rows already in local edit mode). Operators can correct VLAN before clicking Confirm.

---

## Phase 3.0 — Smart Cohort Planning ✅ COMPLETE (v1.32.0 / v1.32.1)
**Status**: COMPLETE (2026-02-28)

> **Goal**: Help the operator decide *which tenants go in which cohort* using data already in the DB. The classic strategy is: start with the easiest tenants (few VMs, small disk, low risk, supported OS) to validate the toolchain, then tackle harder ones as confidence grows.

### 3.0A — Tenant Ease Score Engine

A composite score (0–100, lower = easier to migrate first) computed per tenant from data already in `migration_vms`:

| Dimension | Signal | Weight rationale |
|-----------|--------|-----------------|
| **VM count** | Fewer VMs → easier | More VMs = more blast radius if something goes wrong |
| **Total used disk (GB)** | Less data → faster | Directly drives migration time |
| **Average risk score** | Lower → safer | Already computed by risk engine |
| **OS support rate** | % VMs with a confirmed supported/mapped OS | Unsupported OS = manual intervention risk |
| **Distinct network count** | Fewer networks → simpler cutover | Each NIC needs a confirmed mapping |
| **Cross-tenant dependency count** | Fewer `migration_vm_dependencies` rows pointing outside this tenant → safer | Split app stacks are the #1 cause of failed cutovers |
| **Warm/cold ratio** | More warm VMs → easier | Cold = full VM offline, higher business impact |
| **Unconfirmed mappings** | 0 unconfirmed target/network → ready | Unconfirmed = operator hasn't reviewed it yet |

**Formula (engine)**:
```
ease_score = (
  w_vmcount   × norm(vm_count)            +   # 0=1VM, 100=max VMs in project
  w_disk      × norm(total_used_gb)       +   # 0=0GB, 100=max disk
  w_risk      × norm(avg_risk_score)      +   # already 0–100
  w_os        × (1 - os_support_rate)     +   # 0=all supported, 100=none supported
  w_networks  × norm(distinct_networks)   +   # 0=1 network, 100=max
  w_deps      × norm(cross_tenant_deps)   +   # 0=no deps, 100=max deps
  w_cold      × cold_vm_ratio             +   # 0=all warm, 100=all cold
  w_unconf    × unconfirmed_ratio             # 0=all confirmed, 100=none confirmed
)
```

Default weights: `vm_count=15, disk=20, risk=25, os=20, networks=10, deps=5, cold=3, unconf=2` (sum=100). Exposed as configurable sliders in UI so operators can reweight for their environment (e.g. a storage-heavy migration → raise disk weight).

**API**: `GET /projects/{id}/tenant-ease-scores` — returns per-tenant ease score + breakdown of each dimension's contribution. Also accepts `?weights=...` override for preview.

**DB**: No new table — purely computed at request time from existing data.

---

### 3.0B — Auto-Assign Cohorts by Ease Score

**Strategies** (selectable in UI):

| Strategy | Logic |
|----------|-------|
| **Easiest first** | Sort tenants by `ease_score ASC`, fill cohorts sequentially up to cap |
| **Riskiest last** | Sort by `avg_risk_score DESC` → always last cohort; remain by ease |
| **Pilot + bulk** | Auto-create "🧪 Pilot" (top-5 easiest) + "🚀 Main" (all others) → validates toolchain before committing |
| **Balanced load** | Minimize variance in `SUM(total_used_gb)` per cohort — each cohort takes roughly equal wall-clock time |
| **OS-first** | Group by OS family: Linux cohort → Windows cohort (avoids mixed-OS troubleshooting) |
| **By priority** | Uses `migration_priority` from 2.10D (operator-set) — ignores ease score |

**Guardrails** (configurable, applied before strategy runs):
- Max VMs per cohort (e.g. 50)
- Max total disk per cohort (e.g. 20 TB)
- Max avg risk score per cohort (e.g. 60 — prevents high-risk tenants slipping into pilot)
- Min OS support rate per cohort (e.g. 80% — ensures each cohort is mostly supported OSes)

**API**: `POST /projects/{id}/cohorts/auto-assign`
```json
{
  "strategy": "easiest_first",
  "num_cohorts": 4,
  "guardrails": {
    "max_vms_per_cohort": 50,
    "max_disk_tb_per_cohort": 20,
    "max_avg_risk": 60,
    "min_os_support_rate": 0.8
  },
  "ease_weights": { "disk": 30, "risk": 30, ... },
  "dry_run": true
}
```
Returns proposed assignment (tenant → cohort) with per-cohort summary stats. `dry_run=true` returns preview without committing to DB.

---

### 3.0C — Cohort Summary Cards (enhanced)

Each cohort card in the UI shows computed stats from the ease/time engine:

- **VM count** + **tenant count**
- **Total used disk (TB)**
- **⏱ Estimated migration time** — `SUM(vm_used_gb) / bottleneck_gbph` factored by agent slot count for this cohort. Shown as "~2.5 days @ 3 agents"
- **Avg ease score** (green/amber/red band)
- **Risk distribution** pill — e.g. `🟢 12 🟡 5 🔴 1`
- **OS mix** — e.g. `Win: 65% | Linux: 30% | Other: 5%`
- **Readiness** — `✅ 14 ready  ⚠️ 3 unconfirmed  ❌ 1 critical gap`
- **⚠️ Cross-cohort dependency warnings** — if any VM in this cohort depends on a VM in a later cohort

---

### 3.0D — Cohort Comparison View

Side-by-side table of all cohorts showing the metrics from 3.0C. Makes it obvious if one cohort is massively overloaded. Columns sortable. "Rebalance" button triggers `auto-assign` with `balanced_load` strategy and previews the change before committing.

---

### 3.0E — Ease Score Explainer in Tenant Row

In the Tenants sub-tab, add an **Ease Score** column (colour-coded 0–100 badge). Clicking it opens a tooltip/popover showing the breakdown:
```
Ease Score: 23 (Easy ✅)
  Disk:         4 / 20  (12 GB used — small)
  Risk:         8 / 25  (avg risk 31 — low)
  OS support:   0 / 20  (100% supported)
  VM count:     2 / 15  (2 VMs — small)
  Networks:     3 / 10  (1 network)
  Dependencies: 0 / 5   (none)
  Warm ratio:   1 / 3   (all warm)
  Confirmed:    0 / 2   (all confirmed)
```
This lets operators understand *why* a tenant scored high without reading raw numbers.

---

### 3.0F — What-If Live Time Recalculation

When an operator manually moves a tenant from one cohort to another (or uses the assignment panel), the time estimate on **both** affected cohort cards recalculates instantly — no save/reload required.

**How it works (client-side only, no extra API calls):**
- Each tenant already has `total_used_gb` and `ease_score` in memory from the `GET /tenant-ease-scores` response
- Cohort estimated time = `SUM(tenant.total_used_gb) / bottleneck_gbph / agent_slots` — pure arithmetic
- When the assignment changes locally (before Save), recalculate affected cohort totals in React state and re-render immediately
- The "💾 Save Assignment" button commits to the API; until then it's a live preview

**Additional what-if controls:**
- **Agent slots slider** on each cohort card — dragging it instantly recalculates the time estimate ("2 agents → 4 agents = 3.5 days → 1.8 days")
- **Bandwidth override** input — what if the migration link is only 500 Mbps instead of the project default? Updates all cohort time estimates simultaneously
- **"Reset to Saved"** button — discards local what-if changes and reverts to last committed assignment

The agent slots slider and bandwidth override are **Low effort** and independently deliverable. Drag-and-drop tenant card reassignment is **High effort** and optional; the assignment panel (checkbox + move button) covers the same workflow.

---

### 3.0 Summary Table

| Item | DB | API | UI | Effort |
|------|----|-----|-----|--------|
| **3.0A** Tenant Ease Score engine | None | GET tenant-ease-scores | Ease column + breakdown popover in Tenants tab | ✅ Done |
| **3.0B** Auto-assign with strategies + guardrails | None | POST cohorts/auto-assign (dry_run) | Strategy picker + guardrail inputs + preview diff | ✅ Done |
| **3.0C** Enhanced cohort cards (time, risk, OS, readiness, dep warnings) | None | Included in GET cohorts | Rich stat cards | ✅ Done |
| **3.0D** Cohort comparison view + rebalance | None | Reuse GET cohorts | Side-by-side table + rebalance button | ✅ Done |
| **3.0E** Ease score explainer popover | None | Included in ease-scores | Per-dimension breakdown popover | ✅ Done |
| **3.0F** What-if agent slots + bandwidth sliders (live recalc) | None | None (client-side math) | Live time update on cohort cards | ✅ Done |
| **3.0F** Drag-and-drop tenant reassignment | None | None (uses existing assign-tenants) | Drag tenant card between cohort columns | High |

### Phase 3.0 File Changes (completed)

| File | Action |
|------|--------|
| `api/migration_engine.py` | Added `compute_tenant_ease_score()`, `auto_assign_cohorts()` with 6 strategies + guardrails + ramp-profile mode (~250 lines added) |
| `api/migration_routes.py` | Added `GET /tenant-ease-scores`, `POST /cohorts/auto-assign`; extended `AutoAssignRequest` with `cohort_profiles` + `avg_risk` in summary |
| `pf9-ui/src/components/migration/SourceAnalysis.tsx` | Ease score column + breakdown popover in Tenants tab; strategy picker, guardrail sliders, ramp-profile mode, preview diff table, what-if estimator in Cohorts tab; enhanced cohort cards (Avg Ease, Total Disk, Avg Risk, difficulty distribution bar) |
| `CHANGELOG.md` | v1.32.0 + v1.32.1 entries |

---

## Phase 3.0.1 — Cohort-Aligned Scheduling & Migration Plan Enhancements ✅ COMPLETE (v1.33.0)
**Status**: COMPLETE (2026-02-28)

> Post-3.0 enhancements that make cohort boundaries visible and enforced throughout: cohort-sequential daily scheduling, two-model What-If estimator, expandable tenant list with reassignment, and comprehensive migration plan cohort grouping.

### 3.0.1A — What-If Estimator: Two-Model Comparison
- [x] **Formula fix** — `3_600_000` divisor corrected to `3_600`; transfer hours were 1000× too small before
- [x] **Bandwidth: 100 Gbps support** — slider range extended from 10 Gbps to 100 Gbps; free-form number input added alongside slider for direct value entry
- [x] **Tooltips** — ⓘ tooltips added to Bandwidth and Parallel Agent Slots labels explaining what each parameter controls
- [x] **Two-model table** — Each cohort row now shows two independent estimates side-by-side:
  - **BW Days** (bandwidth/transfer model): `effMbps = bw × 0.75; transferH = (diskGb × 1024 × 8) / (effMbps × 3600) × 1.14; cutoverH = tenants × 0.25 / agentSlots; totalH = transferH + cutoverH; bwDays = totalH / workHoursPerDay`
  - **Sched. Days** (VM-slots model): `schedDays = vm_count / effectiveVmsPerDay` — mirrors the backend scheduler exactly
- [x] **Project deadline banner** — Green/red banner comparing both BW Days and Sched. Days against `project.migration_duration_days`; turns red if either model exceeds the configured project duration
- [x] **`project` prop passed to CohortsView** — Required to supply `migration_duration_days` to the deadline check

### 3.0.1B — Cohort Card Expandable Tenant List + Reassignment
- [x] **Expandable tenant list** — Each cohort card has a `▾ N Tenants` toggle button that expands inline to show all tenants assigned to that cohort
- [x] **Tenant row detail** — Expanded list shows: tenant name | ease score colour-coded badge
- [x] **Move to… dropdown** — Each tenant row has a `Select cohort…` dropdown listing all other cohorts; selecting one immediately calls `POST /projects/{id}/cohorts/{targetId}/assign-tenants` and reloads cohorts + tenants
- [x] **State management** — `expandedCohort: number | null` and `reassigning: Record<number, boolean>` states track UI

### 3.0.1C — Migration Plan Cohort Grouping
- [x] **Tenant plans grouped by cohort** — The per-tenant assessment table in the Migration Plan tab is grouped by cohort; each group opens with a `📦 Cohort N — Cohort Name` header row and closes with a subtotal row (tenants, VMs, hours)
- [x] **Cohort Execution Plan summary table** — New `📦 Cohort Execution Plan` table shown above the per-tenant table; columns: Cohort | Start Day | End Day | Duration (days) | VMs. Data sourced from `plan.cohort_schedule_summary` returned by the API

### 3.0.1D — Cohort-Sequential Daily Scheduler (Backend)
- [x] **Root cause fixed** — The daily scheduler was a flat loop over all VMs, so cohorts mixed within days. A VM from Cohort 2 could land on the same day as a VM from Cohort 1 whenever slots remained
- [x] **Cohort-sequential rewrite** — Scheduler now uses `itertools.groupby` on `(cohort_order, cohort_name)` to process cohorts one at a time; each cohort exhausts completely before the next cohort starts, and each new cohort block is forced to start on a fresh day
- [x] **`cohort_schedule_summary` in API response** — `generate_migration_plan()` now returns a `cohort_schedule_summary` list: `[{cohort_name, start_day, end_day, duration_days, vm_count}]`; exposed in `GET /export-plan` response
- [x] **`tenant_plans` sorted by cohort** — `tenant_map.values()` now sorted by `(cohort_order or 9999, -vm_count)` instead of `-vm_count` alone
- [x] **VM sort key** — VMs sorted by `(cohort_order or 9999, tenant_name, priority, -disk_gb)` at the top of the scheduler loop
- [x] **Day entries carry cohort metadata** — Each day entry in `daily_schedule` carries `cohort_name` and `cohort_order` for the cohort block being processed that day
- [x] **`export-plan` JOIN** — `GET /projects/{id}/export-plan` SQL now JOINs `migration_cohorts` to add `cohort_name` + `cohort_order` per tenant; ORDER BY `cohort_order NULLS LAST, vm_count DESC`

### 3.0.1E — Daily Schedule Cohort Separator Rows (UI)
- [x] **Cohort transition rows** — The daily schedule table renders a full-width `📦 Cohort Name` separator row at the start of each cohort block using `React.Fragment`
- [x] **Cohort(s) column** — Each day row in the daily schedule shows a "Cohort(s)" column indicating which cohort is being processed
- [x] **Cohort header in daily schedule** — The cohort separator rows span all columns and use a distinct background colour to visually frame each cohort's days

### 3.0.1F — Clean Slate on Clear / Re-Upload
- [x] **`migration_cohorts` deleted on Clear RVTools** — `DELETE /projects/{id}/rvtools` now includes `migration_cohorts` in its table purge list; cohort shells no longer survive a data clear
- [x] **`migration_cohorts` deleted on Re-Upload** — The RVTools re-import path also deletes `migration_cohorts` before re-ingesting VM/tenant data; every upload is a full clean slate with no ghost cohort references

### Phase 3.0.1 File Changes

| File | Action |
|------|--------|
| `api/migration_engine.py` | Rewrote daily scheduler to cohort-sequential using `itertools.groupby`; added `cohort_schedule_summary` to `generate_migration_plan()` return; updated VM sort key + tenant_plans sort |
| `api/migration_routes.py` | `export_migration_plan`: JOIN `migration_cohorts`, ORDER BY `cohort_order`; `clear_rvtools_data`: added `migration_cohorts` to delete list; upload re-import: added `migration_cohorts` to delete list |
| `pf9-ui/src/components/migration/SourceAnalysis.tsx` | CohortsView: `project` prop, What-If two-model table (BW Days + Sched. Days), deadline banner, 100Gbps slider + freeform input, tooltips, expandable tenant list + reassignment; MigrationPlanView: Cohort Execution Plan table, cohort-grouped tenant table, cohort separator rows in daily schedule |
| `CHANGELOG.md` | v1.33.0 entry |
| `README.md` | Version badge → v1.33.0 |



## Phase 3: Migration Wave Planning ✅ COMPLETE (v1.34.0)
**Status**: COMPLETE — released 2026-02-28

> **Rationale**: Wave planning is scoped within a cohort (or the full project if no cohorts defined). Uses tenant scoping, VM status, dependency graph, and network mappings to build ordered, gate-controlled migration waves.

### Completed Work

- [x] `db/migrate_wave_planning.sql` — ALTER TABLE `migration_waves` (added `cohort_id` FK, `status` CHECK, `wave_type`, `agent_slots_override`, `scheduled_start/end` DATE, `owner_name`, `notes`, `started_at`, `completed_at`). ALTER TABLE `migration_wave_vms` (added `vm_id` BIGINT FK with UNIQUE, `migration_order`, `assigned_at`, `wave_vm_status`). CREATE `migration_wave_preflights` table. Applied to live DB.
- [x] `build_wave_plan()` — Five auto-build strategies: `pilot_first`, `by_tenant`, `by_risk`, `by_priority`, `balanced`. Dependency-graph cross-wave violation detection. Returns risk distribution, disk totals, tenant names, warnings, unassigned VM IDs.
- [x] `PREFLIGHT_CHECKS` — 6 checks (blocker/warning/info): network_mapped, target_project_set, vms_assessed, no_critical_gaps, agent_reachable, snapshot_baseline.
- [x] Wave status lifecycle — `planned → pre_checks_passed → executing → validating → complete / failed / cancelled` with transition guards and `started_at`/`completed_at` timestamps.
- [x] 11 new API routes — CRUD waves, assign/remove VMs, advance lifecycle, auto-build (dry-run), pre-flight CRUD, migration funnel rollup.
- [x] `WavePlannerView` React component — VM migration funnel bar, cohort filter, auto-build panel with strategy descriptions, dry-run preview table, wave cards with type/status/cohort badges, per-wave VM tables, pre-flight checklist (pass/fail/skip), advance-status buttons, delete (planned only).

### Phase 3 File Changes

| File | Change |
|------|--------|
| `db/migrate_wave_planning.sql` | NEW — Wave table extensions + preflights table |
| `api/migration_engine.py` | Added `build_wave_plan()`, `PREFLIGHT_CHECKS`, `WAVE_STRATEGIES` |
| `api/migration_routes.py` | Added 6 Pydantic models + 11 wave/funnel routes |
| `pf9-ui/src/components/migration/SourceAnalysis.tsx` | Added `WavePlannerView`, `Wave`/`WaveVM`/`WavePreflight`/`MigrationFunnel` types, "waves" SubView, 🌊 Wave Planner tab |

### Bug Fixes (v1.34.1)

- [x] **Cohort-scoped wave building** — `auto_build_waves` iterates cohorts in `cohort_order` sequence, calling `build_wave_plan()` once per cohort. VMs not in any cohort collected as an "Unassigned" group. VM SELECT now fetches `t.cohort_id AS vm_cohort_id`. Preview response includes `cohort_count`; preview table shows a Cohort column when `cohort_count > 1`.
- [x] **`pilot_first` wave naming** — Pilot name now `🧪 <cohort_prefix>`; regular waves counted from 1 independently of the pilot slot.
- [x] **`risk_category` column** — Fixed `v.risk_classification → v.risk_category AS risk_classification` in all VM SQL queries.
- [x] **`vm_name` NOT NULL** — `vm_name_map` built before INSERTs; ON CONFLICT on correct partial index.
- [x] **`RealDictCursor` scalar query** — `MAX(wave_number)` query uses plain cursor so `fetchone()[0]` works.
- [x] **`user.get()` Pydantic v2** — All activity-log calls use `getattr(user, "username", "?")` instead of `user.get()`.
- [x] **`cohort_order` column name** — Cohort sort query fixed from `"order"` to `cohort_order`.
- [x] **Double emoji in cohort badges** — Removed hardcoded `📦` prefix from preview table and wave card badges.

---

## Phase 4: Target Preparation & Auto-Provisioning 🔲 NOT STARTED
**Status**: NOT STARTED

> **Rationale**: Only after assessment (Phases 1–2) and planning (Phase 3) are complete and approved should target resources be provisioned. This prevents wasted resources and ensures the plan is locked before anything is created on PCD.
>
> **Scope boundary**: pf9-mngt plans and provisions. vJailbreak executes. The handoff artifact is the credential bundle generated at the end of Phase 4C. Migration execution, post-migration validation, and VM progress tracking are out of scope — that is vJailbreak's job.

---

### Phase 4A — Data Enrichment ✅ COMPLETE

> **Status**: DONE (2026-03-01, v1.35.0). All four items shipped: subnet details, flavor staging, image requirements, tenant users.

#### Phase 4A Hotfixes (v1.35.1 — 2026-03-01)
- [x] **Route ordering 405** — moved `GET /readiness` before `PATCH /{mapping_id}` in `migration_routes.py`
- [x] **GROUP BY failure** — replaced explicit column list with `GROUP BY m.id`
- [x] **dns_nameservers type mismatch** — UI now splits comma-string → `List[str]` before PATCH
- [x] **UI heading** — "Phase 4A — Data Enrichment" → "Pre-Migration Data Enrichment"
- [x] **Network Map Kind column** — Replaced read-only pill with an inline `<select>` dropdown; saves immediately on change

#### Phase 4A Hotfixes (v1.35.2 — 2026-03-01)
- [x] **Flavor staging — boot-volume model** — VCD flavors define CPU + RAM only (disk = 0 GB); the VM's boot disk is a separate volume handled at migration time. `refresh_flavor_staging` now groups VMs by `(cpu, ram)` only — collapsing all disk-size variants into one flavor entry — and sets `disk_gb = 0`. Stale old rows (with disk in shape name) are pruned on refresh.
- [x] **Image requirements GroupingError** — `POST /image-requirements/refresh` raised `GroupingError` due to a correlated subquery referencing an ungrouped outer alias. Fixed by wrapping the aggregate in a derived table `fam`.
- [x] **✓ Confirm All** — Added bulk-confirm button to both Flavor Staging and Image Requirements views.
- [x] **F&R for Image Requirements** — Added client-side find-and-replace panel to Image Requirements (matching Flavor Staging's UX).

---

#### 4A Detail — Data Enrichment (operator input required before provisioning)

> This sub-phase collects the information that cannot be derived from RVTools or the existing plan. All items must be confirmed before Phase 4B can run.

#### 4A.1 — Network Subnet Details

RVTools provides network name and VLAN ID. Neutron needs the full subnet spec to create a network. The operator must supply this per mapped network.

**Implemented features (v1.35.0–v1.35.7):**

- Per-row expandable Subnet Details panel (CIDR, gateway, DNS, DHCP pool, kind, is_external).
- **Excel Template Export/Import** — `GET /network-mappings/export-template` + `POST /network-mappings/import-template`. Bulk-fill subnet fields via XLSX. Formula detection (external-file VLOOKUP references) returns HTTP 422 with fix instructions. Header row auto-detected. Diagnostic response shows skipped-empty-patch vs skipped-no-db-match with sample names.
- **✓ Confirm Subnets** — `POST /network-mappings/confirm-subnets` bulk-confirms all rows with CIDR. Import auto-confirms when CIDR is provided.
- Subnet Details column shows CIDR inline (green ✓ confirmed, amber ⚠ unconfirmed-with-CIDR).
- **"none" network filtering** — RVTools literal `"none"` networks filtered at parse, excluded from auto-seed, cleaned from DB on load.
- **Network gap auto-resolve** — `network` gaps auto-resolve when the source network has a confirmed mapping; if all mappings confirmed → all remaining network gaps resolve.

**DB**: Columns on `migration_network_mappings`:
```
network_kind VARCHAR DEFAULT 'physical_managed',
cidr TEXT, gateway_ip TEXT, dns_nameservers TEXT[],
allocation_pool_start TEXT, allocation_pool_end TEXT,
dhcp_enabled BOOLEAN DEFAULT true, is_external BOOLEAN DEFAULT false,
subnet_details_confirmed BOOLEAN DEFAULT false
```

> **`network_kind` default logic**: rows that have a `vlan_id` default to `physical_managed` (VLAN-tagged provider networks — the common case). Flat/trunk-only L2 networks default to `physical_l2`. Purely internal networks with no external routing should be set to `virtual`. The gap analysis (Phase 2E) can pre-populate the suggested kind based on whether a VLAN ID is present, so operators rarely need to change the default.

**API**: `PATCH /network-mappings/{id}` — extend to accept all subnet fields including `network_kind`. `GET /projects/{id}/network-mappings/readiness` — returns count of networks missing subnet details.

**UI**: Network Map tab — expand each confirmed row to show a "Subnet Details" section with the new fields. The `network_kind` field renders as a small dropdown (`Physical Managed | Physical L2 | Virtual`) and defaults to `Physical Managed` for rows with a VLAN ID. Rows without subnet details show an ⚠️ badge. A "Subnet Details Ready" counter in the toolbar shows X/Y complete. Networks marked `is_external=true` skip subnet creation (they already exist on PCD).

---

#### 4A.2 — Flavor Staging

Gap analysis (Phase 2E) detects distinct VM shapes that don't exist as PCD flavors. Phase 4A turns those detected shapes into editable draft flavors the operator reviews before anything is created.

> **Boot-volume model**: VCD flavors define CPU + RAM only (`disk = 0 GB`). The VM's boot disk is handled as a separate volume at migration time and is **not** part of the flavor. Two VMs with the same CPU/RAM but different disk sizes map to the same flavor. `source_shape` therefore only encodes `"4vCPU-8GB"`, not `"4vCPU-8GB-300GB"`.

**DB**: `migration_flavor_staging` table:
```sql
CREATE TABLE migration_flavor_staging (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES migration_projects(project_id),
    source_shape TEXT NOT NULL,          -- e.g. "4vCPU-8GB" (CPU+RAM only; disk=0 boot-volume model)
    vcpus INTEGER NOT NULL,
    ram_mb INTEGER NOT NULL,
    disk_gb INTEGER NOT NULL DEFAULT 0,  -- always 0: boot-volume flavors carry no disk
    target_flavor_name TEXT,             -- operator edits this
    pcd_flavor_id TEXT,                  -- filled after creation in 4B
    vm_count INTEGER DEFAULT 0,          -- number of VMs using this shape
    confirmed BOOLEAN DEFAULT false,
    skip BOOLEAN DEFAULT false,          -- operator marks as "map to existing flavor instead"
    existing_flavor_id TEXT,             -- if skip=true, which existing PCD flavor to use
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**API**:
- `GET /projects/{id}/flavor-staging` — list all draft flavors (auto-populated from gap analysis)
- `POST /projects/{id}/flavor-staging/refresh` — re-run detection from current gaps, add new shapes, keep operator edits
- `PATCH /flavor-staging/{id}` — update name, skip flag, existing_flavor_id, confirmed
- `POST /projects/{id}/flavor-staging/bulk-rename` — find-and-replace across `target_flavor_name` column (same pattern as tenant/network F&R): `{ find, replace, case_sensitive, preview }`

**UI**: New **"🧊 Flavor Staging"** section in the PCD Readiness tab (or its own sub-tab):
- Table: Source Shape | VM Count | Target Name (editable) | Skip (checkbox) | Existing Flavor (picker if skip=true) | Confirmed
- Toolbar: "🔄 Refresh from Gaps" | "🔍 Find & Replace" | "✓ Confirm All" buttons
- Unconfirmed flavors show ⚠️; skipped flavors show ↪️
- "Flavors Ready" counter: X/Y confirmed or skipped

---

#### 4A.3 — Image Requirements Checklist

pf9-mngt cannot source or upload OS images. It generates a checklist of what is needed based on OS families detected in the inventory, and gates Phase 4B on the operator confirming they are available in Glance.

**DB**: `migration_image_requirements` table:
```sql
CREATE TABLE migration_image_requirements (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES migration_projects(project_id),
    os_family TEXT NOT NULL,             -- 'windows', 'linux-ubuntu', 'linux-rhel', etc.
    os_version_hint TEXT,                -- e.g. "Windows Server 2019", "Ubuntu 22.04"
    vm_count INTEGER DEFAULT 0,          -- VMs needing this image
    glance_image_id TEXT,                -- operator pastes Glance UUID once uploaded
    glance_image_name TEXT,
    confirmed BOOLEAN DEFAULT false,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**API**:
- `GET /projects/{id}/image-requirements` — list (auto-populated from distinct OS families in `migration_vms`)
- `PATCH /image-requirements/{id}` — set `glance_image_id`, `glance_image_name`, `confirmed`

**UI**: **"🖼️ Image Requirements"** section in PCD Readiness tab:
- Table: OS Family | Version Hint | VM Count | Glance Image ID (editable) | Glance Image Name | Confirmed
- Each row shows instructions: "Upload a QCOW2 image to Glance matching this OS, then paste the image UUID here."
- Windows rows show a note: "Windows images require a licensed QCOW2. Build using virtio drivers + cloudbase-init."
- "Images Ready" counter: X/Y confirmed

---

#### 4A.4 — Per-Tenant User Definitions

Every new PCD project needs at least two things before vJailbreak can run: a migration service account (admin role, used by vJailbreak) and a tenant owner account (admin or member role, used by the customer post-migration). The service account is auto-generated; the tenant owner must be defined by the operator.

**DB**: `migration_tenant_users` table:
```sql
CREATE TABLE migration_tenant_users (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES migration_tenants(id),
    user_type VARCHAR NOT NULL,           -- 'service_account' | 'tenant_owner'
    username TEXT NOT NULL,
    email TEXT,
    role VARCHAR NOT NULL DEFAULT 'admin', -- 'admin' | 'member' | 'reader'
    is_existing_user BOOLEAN DEFAULT false, -- true = user already exists in Keystone/LDAP
    temp_password TEXT,                   -- encrypted; only set for new users
    password_must_change BOOLEAN DEFAULT true,
    pcd_user_id TEXT,                     -- filled after creation in 4B
    confirmed BOOLEAN DEFAULT false,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Auto-seeding**: When a project is approved (or when the user clicks "Refresh Users"), auto-create one `service_account` row per in-scope tenant with:
- `username = svc-migration-<project_slug>-<tenant_slug>` (auto-generated, editable)
- `role = admin`
- `is_existing_user = false`
- `temp_password` = auto-generated 20-char random password (stored encrypted in DB, never shown in UI except in the export bundle)
- `password_must_change = false` (service accounts must not expire during migration window)

**API**:
- `GET /projects/{id}/tenant-users` — list all user definitions grouped by tenant
- `POST /projects/{id}/tenant-users` — add a user row (for tenant owner entries)
- `PATCH /tenant-users/{id}` — edit username, email, role, is_existing_user, notes, confirmed
- `DELETE /tenant-users/{id}` — remove a tenant owner row (service accounts cannot be deleted)
- `POST /projects/{id}/tenant-users/seed-service-accounts` — auto-generate service account rows for all in-scope tenants that don't have one yet

**UI**: New **"👤 Users"** sub-tab in SourceAnalysis (between Network Map and Wave Planner):
- Table grouped by tenant: Type | Username | Email | Role | Existing User | Must Change PW | Confirmed
- Each tenant section has a `+ Add Tenant Owner` button
- Service account rows are auto-generated and show 🔒 (locked type, can only edit username/notes)
- `is_existing_user = true` rows show no password column — existing Keystone users only need a role assignment
- Unconfirmed rows show ⚠️; a toolbar counter shows "X/Y tenants fully configured"
- Passwords never shown in plaintext — only "••••••••" with a "Regenerate" button

---

### Phase 4B — PCD Auto-Provisioning

> Requires: project `approved_at IS NOT NULL`, AND all 4A items confirmed (subnet details, flavors, images, users).

> **Implementation note — reuse the provisioning backend**: The network creation step (step 4 below) must NOT write a second Neutron client inside `migration_engine.py`. Instead, it builds a `ProvisionRequest` from migration plan data (`target_domain_name`, `target_project_name` from `migration_tenants`; `List[NetworkConfig]` from confirmed `migration_network_mappings` rows) and calls the existing `POST /provision` API. This keeps all Neutron logic in one place and inherits the naming conventions (`<domain>_tenant_extnet_vlan_<id>`, etc.), error handling, and `networks_created` JSONB audit trail already built in v1.34.2.

**DB**: `migration_prep_tasks` table:
```sql
CREATE TABLE migration_prep_tasks (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES migration_projects(project_id),
    cohort_id INTEGER REFERENCES migration_cohorts(id),   -- NULL = project-level task
    task_type VARCHAR NOT NULL,  -- 'domain' | 'project' | 'quota' | 'network' | 'subnet' | 'flavor' | 'user' | 'role_assignment'
    resource_name TEXT,
    resource_id TEXT,            -- PCD UUID after creation
    status VARCHAR DEFAULT 'pending',  -- 'pending' | 'running' | 'done' | 'failed' | 'skipped'
    error_message TEXT,
    rollback_data JSONB,         -- enough info to undo the action
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Provisioning sequence** (order matters — dependencies are strict):
1. **Domains** — create each distinct `target_domain_name` not already in Keystone
2. **Projects** — create each in-scope tenant's `target_project_name` under its domain
3. **Quotas** — apply Phase 2C quota recommendations per project (Nova + Cinder + Neutron)
4. **Networks** — build `List[NetworkConfig]` from confirmed `migration_network_mappings` rows (using `network_kind`, `vlan_id`, `cidr`, `gateway_ip`, `dns_nameservers`; skip `is_external=true` rows) and call `POST /provision` per tenant. On task completion, copy the returned `networks_created[].id` UUIDs back into `migration_network_mappings.target_network_id` — this closes the planning→execution loop and ensures Wave Planner pre-flight (`network_mapped`) and the vJailbreak bundle both carry real PCD network IDs
5. **Flavors** — create confirmed staging flavors; skip rows where `skip=true` (use existing)
6. **Users** — create new Keystone users for rows where `is_existing_user=false`; skip existing users
7. **Role assignments** — assign each user their role in their project(s)

**API**:
- `POST /projects/{id}/prepare` — kick off full provisioning sequence; gated on 4A completeness check; runs cohort by cohort in `cohort_order`; returns a job ID
- `GET /projects/{id}/prep-tasks` — list all tasks with status (for UI progress table)
- `POST /projects/{id}/prep-tasks/{task_id}/retry` — retry a single failed task
- `POST /projects/{id}/prep-tasks/{task_id}/rollback` — undo a single completed task (e.g. delete a project that was created by mistake)
- `GET /projects/{id}/prep-readiness` — pre-flight check: are all 4A items confirmed? Returns blocking items list.

**UI**: New **"⚙️ Prepare PCD"** sub-tab:
- **Readiness check panel** (shown before provisioning starts): four status rows — Subnet Details (X/Y), Flavors (X/Y), Images (X/Y), Users (X/Y). "▶️ Start Provisioning" button disabled until all green.
- **Task progress table**: task type | resource name | status badge | error (expandable) | Retry / Rollback buttons
- Tasks grouped by cohort, then by task type within each cohort
- Live refresh every 3s while provisioning is running
- Summary bar: "X tasks done · Y failed · Z pending"

---

### Phase 4C — vJailbreak Handoff Artifacts

> This is the terminal output of the Migration Planner. After 4C, execution moves entirely to vJailbreak.

#### 4C.1 — vJailbreak Credential Bundle

A downloadable JSON/YAML file per cohort (or for the full project) containing everything vJailbreak needs to connect to each PCD project and start migrating VMs.

**Structure per tenant entry:**
```json
{
  "tenant_name": "Acme Corp",
  "target_project_name": "acme-prod",
  "target_domain_name": "acme",
  "auth_url": "https://pcd.example.com:5000/v3",
  "project_id": "<pcd-project-uuid>",
  "service_account": {
    "username": "svc-migration-proj-acme",
    "password": "<generated-password>"
  },
  "networks": [
    { "source_network": "VLAN-100", "pcd_network_id": "<uuid>", "vlan_id": 100 }
  ],
  "wave_sequence": [
    { "wave_name": "🧪 Acme Pilot", "vm_count": 3 },
    { "wave_name": "Wave 1", "vm_count": 12 }
  ]
}
```

**API**: `GET /projects/{id}/export-vjailbreak-bundle` — returns JSON file. `GET /projects/{id}/cohorts/{cid}/export-vjailbreak-bundle` — cohort-scoped version.

**UI**: "📦 Export vJailbreak Bundle" button in Wave Planner tab (enabled once 4B is complete for the cohort). Button per-cohort and one for the full project.

---

#### 4C.2 — Tenant Handoff Sheet

A per-project PDF for the MSP to deliver to each customer — tells them their new PCD credentials and what was created for them.

**Structure per tenant:**
- Header: project name, domain, PCD region endpoint
- Table of tenant owner users: username, role, temporary password (plaintext in PDF — this is intentional, it's a sealed handoff document)
- Note: "You will be prompted to change your password on first login."
- List of networks created with their CIDRs
- Contact info / support section (configurable text)

**API**: `GET /projects/{id}/export-handoff-sheet.pdf` — one PDF with one section per in-scope tenant, sorted by cohort order

**UI**: "📄 Export Handoff Sheet" button in Prepare PCD tab (enabled once 4B is complete). Prominent warning: "This document contains plaintext passwords. Distribute securely."

---

### Phase 4 Summary Table

| Sub-phase | Description | Blocker for next? |
|-----------|-------------|------------------|
| **4A.1** | Network subnet details (CIDR, gateway, DNS, pools) | **Yes** — 4B cannot create networks without subnet spec |
| **4A.2** | Flavor staging (name editing, F&R, confirm-before-create) | **Yes** — 4B cannot create flavors without names confirmed |
| **4A.3** | Image requirements checklist (operator uploads to Glance, confirms) | **Yes** — vJailbreak needs images present before migration |
| **4A.4** | Per-tenant user definitions (service accounts auto-seeded, owner accounts operator-defined) | **Yes** — 4B creates users and role assignments from this |
| **4B** | PCD auto-provisioning (domains, projects, quotas, networks, flavors, users, roles) | **Yes** — 4C needs PCD UUIDs filled by 4B |
| **4C.1** | vJailbreak credential bundle export (JSON/YAML per cohort) | Terminal output |
| **4C.2** | Tenant handoff sheet (PDF with credentials per customer) | Terminal output |

### Phase 4 File Changes (planned)

| File | Action |
|------|--------|
| `db/migrate_phase4_preparation.sql` | NEW — `migration_flavor_staging`, `migration_image_requirements`, `migration_tenant_users`, `migration_prep_tasks` + subnet detail columns on `migration_network_mappings` |
| `db/migrate_migration_planner.sql` | Modified — add Phase 4 table/column definitions for fresh installs |
| `api/migration_engine.py` | Modified — `provision_pcd_resources()` sequenced provisioner, `generate_vjailbreak_bundle()`, `generate_handoff_pdf()` |
| `api/migration_routes.py` | Modified — all Phase 4 endpoints (~15 new routes) |
| `api/export_reports.py` | Modified — `generate_handoff_pdf()` |
| `pf9-ui/src/components/migration/SourceAnalysis.tsx` | Modified — Network Map subnet details expansion, Flavor Staging section, Image Requirements section, 👤 Users sub-tab, ⚙️ Prepare PCD sub-tab, export buttons in Wave Planner |
| `deployment.ps1` | Modified — add `migrate_phase4_preparation.sql` |
| `CHANGELOG.md` | Modified — v1.35.0 entry |

---

## Quick Reference

| Phase | Description | Status | Version |
|-------|-------------|--------|---------|
| 1 | Foundation — Source Import & Assessment | ✅ COMPLETE | v1.28.0 |
| 1.1 | Live Bandwidth, Schedule Sizing, Tenant Editing | ✅ COMPLETE | v1.28.1 |
| 1.2 | Bug Fixes — Disk/Network/Tenant Data Quality | ✅ COMPLETE | v1.28.1 hotfix |
| 1.3 | VM Detail, Filters, Migration Plan & Time Estimates | ✅ COMPLETE | v1.28.2 |
| 1.4 | Usage Metrics, Data Quality, Phase1 Timing Fix | ✅ COMPLETE | v1.28.3 |
| 1.5 | Report Export — Excel (4 sheets) + PDF (landscape A4) | ✅ COMPLETE | v1.28.3 |
| 2 | Tenant Scoping, Target Mapping & Capacity Planning | ✅ COMPLETE | v1.29.0 |
| 2A | Tenant Exclusion & Scoping | ✅ COMPLETE | v1.29.0 |
| 2B | Target Mapping (Source → PCD) | ✅ COMPLETE | v1.29.0 |
| 2C | Quota & Overcommit Modeling | ✅ COMPLETE | v1.29.0 |
| 2D | PCD Hardware Node Sizing (70% util cap = HA strategy; vCPU+RAM only) | ✅ COMPLETE | v1.29.7 |
| 2E | PCD Readiness & Gap Analysis | ✅ COMPLETE | v1.29.0 |
| 2.x | Phase 2 bug fixes & capacity improvements | ✅ COMPLETE | v1.29.1–v1.29.7 |
| 2.8 | Pre-Phase 3 Polish (export auth, gap report, auto-detect, risk breakdown) | ✅ COMPLETE | v1.30.0 |
| 2.9 | Performance-Based Node Sizing (actual cpu_usage_percent/memory_usage_percent) | ✅ COMPLETE | v1.30.1 |
| 2.10 | Pre-Phase 3 Foundations (cohorts, network map, VM status, deps, priority, readiness) | ✅ COMPLETE | v1.31.0 |
| 2.10.1 | Target Name Pre-seeding + Confirmed Flags (UX correctness fix) | ✅ COMPLETE | v1.31.1 |
| 2.10.2 | Cohorts 500 fix, target_project=OrgVDC, VLAN parse, per-cohort schedule | ✅ COMPLETE | v1.31.2 |
| 2.10.3 | Find & Replace for tenant target names (+ scope fix) | ✅ COMPLETE | v1.31.3–v1.31.4 |
| 2.10.4 | Find & Replace for network map target names | ✅ COMPLETE | v1.31.5 |
| 2.10.5 | Confirm All (tenants + networks) | ✅ COMPLETE | v1.31.6 |
| 2.10.6 | Domain/Project descriptions (DB + API + UI) + stale network purge | ✅ COMPLETE | v1.31.7 |
| 2.10.7 | Clear RVTools fix + network map re-edit UX | ✅ COMPLETE | v1.31.8 |
| 2.10.8 | Domain desc seeding + F&R all 4 fields + network map local edit | ✅ COMPLETE | v1.31.9 |
| 2.10.9 | Editable VLAN ID on network map rows | ✅ COMPLETE | v1.31.10 |
| 2.10.10 | VLAN ID edit in Networks tab + Network Map unconfirmed rows | ✅ COMPLETE | v1.31.11 |
| 3.0 | Smart Cohort Planning (Ease Score, Auto-Assign, Guardrails, What-If Sliders) | ✅ COMPLETE | v1.32.0 |
| 3.0.1 (v1.32.1) | Auto-Assign Ramp Profile mode + UX improvements (tooltips, avg ease, locked Apply) | ✅ COMPLETE | v1.32.1 |
| 3.0.1 | Cohort-Aligned Schedule, Two-Model What-If, Tenant Expand+Reassign, Execution Plan, Clean Slate | ✅ COMPLETE | v1.33.0 |
| 3 | Migration Wave Planning (5-strategy auto-builder, wave lifecycle, pre-flight, VM funnel, Wave Planner UI) | ✅ COMPLETE | v1.34.0 |
| 3.1 | Wave planner bug fixes — cohort-scoped building, naming, column names, Pydantic v2 compat | ✅ COMPLETE | v1.34.1 |
| **4A** | **Data Enrichment — subnet details, flavor staging, image checklist, user definitions** | ✅ COMPLETE | v1.35.0–v1.35.7 |
| **4B** | **PCD Auto-Provisioning — domains, projects, quotas, networks, flavors, users, roles** | 🔲 NOT STARTED | — |
| **4C** | **vJailbreak Handoff — credential bundle + tenant handoff sheet PDF** | 🔲 NOT STARTED | — |

### Next Up: Phase 4B — PCD Auto-Provisioning
> Phase 4A is complete (v1.35.0). Phase 4B is the PCD provisioning execution phase — creating domains, projects, quotas, networks (using confirmed subnet details), flavors (from flavor staging), users (from tenant user definitions). All Phase 4A items must be confirmed before 4B can run. After Phase 4C the plan is handed to vJailbreak for execution. Phases 5–7 (vJailbreak execution, post-migration validation, extended runbooks) are out of scope — that is vJailbreak's job.

### Scope Boundary
- **pf9-mngt owns**: source assessment → capacity planning → cohort design → wave sequencing → PCD provisioning → credential handoff
- **vJailbreak owns**: VM data movement, live migration progress, post-cutover validation
- **Handoff artifact**: vJailbreak credential bundle (JSON, one entry per PCD project) + tenant handoff sheet (PDF)

### HA & Utilization Policy
- **70% utilization cap IS the HA strategy** — no separate spare nodes added on top. Same model as VMware: keep cluster at ≤70% so any single-node failure has headroom.
- **Cinder disk**: independent storage backend (Ceph/SAN/NFS) — not a compute node driver. Sized separately.
- **Demand basis**: actual RVtools cpu_usage_percent / memory_usage_percent if ≥50% coverage, else allocation ÷ overcommit, else quota fallback.
- **Peak buffer**: configurable (default 15%) applied on top of actual demand before sizing.
