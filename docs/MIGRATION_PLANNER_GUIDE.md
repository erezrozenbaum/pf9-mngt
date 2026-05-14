# Migration Planner — Admin & Operator Guide

**Applies to**: pf9-mngt v1.67.0+  
**Audience**: Administrators, Technical operators, Migration engineers  
**Scope**: VMware (vSphere / vCD) → Platform9 PCD migration planning, target preparation, and vJailbreak handoff  
**Related**: [ADMIN_GUIDE.md](ADMIN_GUIDE.md) · [API_REFERENCE.md](API_REFERENCE.md) · [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)

---

## Table of Contents

1. [Overview & Concepts](#1-overview--concepts)
2. [Access Control (RBAC)](#2-access-control-rbac)
3. [Prerequisites & First-Time Setup](#3-prerequisites--first-time-setup)
4. [Project Lifecycle & Status States](#4-project-lifecycle--status-states)
5. [Source Import & Assessment](#5-source-import--assessment)
   - 5.1 [Creating a Migration Project](#51-creating-a-migration-project)
   - 5.2 [Bandwidth & Topology Configuration](#52-bandwidth--topology-configuration)
   - 5.3 [Uploading RVTools Data](#53-uploading-rvtools-data)
   - 5.4 [Tenant Detection](#54-tenant-detection)
   - 5.5 [Running the Assessment](#55-running-the-assessment)
   - 5.6 [Risk Configuration](#56-risk-configuration)
   - 5.7 [VM Table & Filters](#57-vm-table--filters)
   - 5.8 [Expandable VM Detail Rows](#58-expandable-vm-detail-rows)
   - 5.9 [Migration Plan View](#59-migration-plan-view)
6. [Tenant Scoping, Target Mapping & Capacity](#6-tenant-scoping-target-mapping--capacity)
   - 6.1 [Tenant Scoping](#61-tenant-scoping)
   - 6.2 [Target Mapping](#62-target-mapping)
   - 6.3 [Overcommit Profiles & Quota Modeling](#63-overcommit-profiles--quota-modeling)
   - 6.4 [PCD Node Sizing](#64-pcd-node-sizing)
   - 6.5 [PCD Readiness & Gap Analysis](#65-pcd-readiness--gap-analysis)
   - 6.6 [Network Map](#66-network-map)
7. [Pre-Wave Foundations](#7-pre-wave-foundations)
   - 7.1 [VM Status Tracking](#71-vm-status-tracking)
   - 7.2 [VM Migration Mode Override](#72-vm-migration-mode-override)
   - 7.3 [Tenant Migration Priority](#73-tenant-migration-priority)
   - 7.4 [VM Dependency Annotation](#74-vm-dependency-annotation)
   - 7.5 [Cohort Management](#75-cohort-management)
   - 7.6 [Tenant Readiness Checklist](#76-tenant-readiness-checklist)
8. [Smart Cohort Planning](#8-smart-cohort-planning)
   - 8.1 [Ease Score Engine](#81-ease-score-engine)
   - 8.2 [Auto-Assign Strategies & Guardrails](#82-auto-assign-strategies--guardrails)
   - 8.3 [What-If Estimator](#83-what-if-estimator)
   - 8.4 [Cohort Comparison View](#84-cohort-comparison-view)
9. [Wave Planning](#9-wave-planning)
   - 9.1 [Building Waves](#91-building-waves)
   - 9.2 [Wave Lifecycle](#92-wave-lifecycle)
   - 9.3 [Pre-Flight Checklist](#93-pre-flight-checklist)
   - 9.4 [Wave Approval Gates](#94-wave-approval-gates)
   - 9.5 [Dependency Auto-Import](#95-dependency-auto-import)
   - 9.6 [Maintenance Windows](#96-maintenance-windows)
10. [Data Enrichment](#10-data-enrichment)
    - 10.1 [Network Subnet Details](#101-network-subnet-details)
    - 10.2 [Flavor Staging](#102-flavor-staging)
    - 10.3 [Image Requirements](#103-image-requirements)
    - 10.4 [Per-Tenant User Definitions](#104-per-tenant-user-definitions)
11. [PCD Auto-Provisioning](#11-pcd-auto-provisioning)
    - 11.1 [Readiness Gate](#111-readiness-gate)
    - 11.2 [Approval Workflow](#112-approval-workflow)
    - 11.3 [Dry-Run Simulation](#113-dry-run-simulation)
    - 11.4 [Running Provisioning](#114-running-provisioning)
    - 11.5 [Task Rollback](#115-task-rollback)
    - 11.6 [Audit Log](#116-audit-log)
12. [vJailbreak Handoff](#12-vjailbreak-handoff)
    - 12.1 [Credential Bundle Export](#121-credential-bundle-export)
    - 12.2 [Tenant Handoff Sheet (PDF)](#122-tenant-handoff-sheet-pdf)
    - 12.3 [vJailbreak CRD Push](#123-vjailbreak-crd-push)
13. [Migration Summary & Tech Fix Time](#13-migration-summary--tech-fix-time)
    - 13.1 [Migration Summary Tab](#131-migration-summary-tab)
    - 13.2 [Fix Time Model](#132-fix-time-model)
    - 13.3 [Fix Settings Editor](#133-fix-settings-editor)
    - 13.4 [Per-VM Fix Override](#134-per-vm-fix-override)
14. [Exports & Reports](#14-exports--reports)
15. [Troubleshooting](#15-troubleshooting)
16. [API Quick Reference](#16-api-quick-reference)
17. [Database Schema Reference](#17-database-schema-reference)

---

## 1. Overview & Concepts

The **Migration Planner** is a complete end-to-end VMware → Platform9 PCD migration planning system built into pf9-mngt. It covers every stage from source inventory ingestion through to handing over execution credentials to vJailbreak.

### What it does

| Stage | What happens |
|-------|-------------|
| **Import** | Parse RVTools XLSX exports (vInfo, vDisk, vNIC, vHost, vCluster, vPartition, vCPU, vMemory, vNetwork, vSnapshot) — fuzzy column normalization handles every RVTools version |
| **Assess** | Score every VM for risk (0–100), classify warm vs cold migration, compute per-VM time estimates |
| **Scope** | Mark which tenants are in-scope; set target domain/project names in PCD |
| **Capacity** | Model PCD hardware requirements using actual performance data from RVTools; run gap analysis against a live PCD cluster |
| **Plan** | Group tenants into ordered cohorts; split cohorts into migration waves; schedule waves with or without maintenance windows |
| **Prepare** | Confirm subnet details, flavor shapes, OS images, and user definitions; auto-provision all PCD resources in the correct order |
| **Hand off** | Generate the vJailbreak credential bundle (JSON) and customer handoff sheet (PDF); push CRDs directly to vJailbreak's Kubernetes API |

### Key terminology

| Term | Meaning |
|------|---------|
| **Project** | A single migration engagement (one or more VMware environments → one PCD cluster) |
| **RVTools** | VMware inventory export tool — the primary data source |
| **Tenant** | A logical grouping of VMs (maps to a PCD project/domain). Auto-detected from VMware metadata |
| **Cohort** | An ordered batch of tenants that will be migrated together as a workstream |
| **Wave** | An execution unit within a cohort — a set of VMs that vJailbreak will migrate in one run |
| **Warm migration** | VM stays powered on; CBT sync runs live; brief cutover window at the end |
| **Cold migration** | VM powered off; full disk copy; higher downtime but no CBT dependency |
| **Agent** | A vJailbreak migration agent VM that drives the data movement |
| **Ease score** | A 0–100 composite score per tenant indicating migration complexity (lower = easier) |
| **Risk score** | A 0–100 per-VM score based on OS type, disk size, snapshot state, NIC count, etc. |
| **PCD** | Platform9 Distributed Cloud — the target OpenStack-based cloud |

### Scope boundary

```
pf9-mngt owns:  source assessment → capacity planning → cohort/wave design → PCD provisioning → credential handoff
vJailbreak owns: VM data movement, live migration progress, post-cutover validation
```

---

## 2. Access Control (RBAC)

The `migration` resource is checked on every Migration Planner endpoint.

| Role | `migration:read` | `migration:write` | `migration:admin` |
|------|:-:|:-:|:-:|
| **Viewer** | ✅ | ❌ | ❌ |
| **Operator** | ✅ | ❌ | ❌ |
| **Technical** | ✅ | ✅ | ❌ |
| **Admin** | ✅ | ✅ | ✅ |
| **Superadmin** | ✅ | ✅ | ✅ |

**`migration:admin`** is required for:
- Approving/rejecting a project (`POST /projects/{id}/approve`)
- Approving/rejecting PCD provisioning (`POST /projects/{id}/prep-approval`)
- Approving/rejecting individual waves (`POST /projects/{id}/waves/{wid}/approval`)
- Deleting a project
- Managing fix settings weights

The Migration Planner UI tab is visible to the **Engineering**, **Tier3 Support**, **Management**, and **Marketing** departments (nav visibility configured in the database `dept_nav_visibility` table).

---

## 3. Prerequisites & First-Time Setup

### Database migrations

All Migration Planner tables are created automatically on API startup (idempotent `_ensure_tables()` call). For manual application or fresh installs:

```powershell
# Apply the master migration (all core tables)
docker exec -i pf9_db psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB `
    < db/migrate_00_migration_planner.sql

# Scoping + capacity tables
docker exec -i pf9_db psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB `
    < db/migrate_phase2_scoping.sql

# Wave planning table extensions
docker exec -i pf9_db psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB `
    < db/migrate_wave_planning.sql

# Data enrichment tables
docker exec -i pf9_db psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB `
    < db/migrate_phase4_preparation.sql

# Provisioning approval workflow
docker exec -i pf9_db psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB `
    < db/migrate_prep_approval.sql

# Wave approvals, dependency auto-import, maintenance windows
docker exec -i pf9_db psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB `
    < db/migrate_wave_approvals.sql

# Tech fix time settings
docker exec -i pf9_db psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB `
    < db/migrate_tech_fix.sql
```

All migration files are **idempotent** — they use `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` throughout. Running them twice is safe.

### RVTools requirements

- **Format**: `.xlsx` (Excel 2007+)
- **Required sheets**: `vInfo` (mandatory — all other sheets are optional enrichment)
- **Recommended sheets** for full fidelity: `vInfo`, `vDisk`, `vNIC`, `vHost`, `vCluster`, `vPartition`, `vCPU`, `vMemory`, `vSnapshot`
- **RVTools version**: any version is supported — the column normalizer uses fuzzy alias matching across all known column header variants

> **Tip**: Export RVTools with all available sheets enabled. Missing sheets degrade the quality of risk scoring, performance-based sizing, and network mapping — but the import will not fail.

### PCD connectivity (for gap analysis and auto-provisioning)

To run gap analysis and auto-provision, you need a PCD API endpoint accessible from the pf9-mngt API container. The PCD credentials are stored per-project (not globally) and are never exposed in logs.

---

## 4. Project Lifecycle & Status States

Each migration project moves through the following states. Transitions are enforced server-side.

```
draft
  │  (upload RVTools)
  ▼
assessment
  │  (run assess + scope + plan)
  ▼
planned
  │  (admin approves)
  ▼
approved
  │  (start PCD prep)
  ▼
preparing
  │  (all prep tasks done)
  ▼
ready
  │  (export vJailbreak bundle)
  ▼
executing  ──(vJailbreak runs)──▶  completed
     │
     ▼
  cancelled / archived
```

| Status | Meaning | Who advances |
|--------|---------|-------------|
| `draft` | Project created; no data yet | (automatic on create) |
| `assessment` | RVTools uploaded and parsed | (automatic on upload) |
| `planned` | Assessment complete; tenants scoped; waves built | Operator |
| `approved` | Admin sign-off gate passed | Admin+ via `POST /approve` |
| `preparing` | PCD provisioning in progress | (set by Run All) |
| `ready` | All prep tasks `done`/`skipped` | (automatic after run) |
| `executing` | vJailbreak is running waves | Manual update |
| `completed` | Migration finished | Manual update |
| `cancelled` | Abandoned | Admin |
| `archived` | Data retained but project closed | Admin via `POST /archive` |

---

## 5. Source Import & Assessment

### 5.1 Creating a Migration Project

**UI**: Migration Planning → ➕ New Project

**Required fields**:

| Field | Default | Notes |
|-------|---------|-------|
| Project Name | — | Free text; unique within the system |
| Topology Type | `local` | `local` (datacenter-to-datacenter, same NIC speed) · `cross_site_dedicated` (MPLS/dark fibre WAN) · `cross_site_internet` (internet-routed) |

The topology type determines which bandwidth fields are used in the migration time model (see §5.2).

**API**:
```bash
curl -X POST http://localhost:8000/api/migration/projects \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp Q3 Migration", "topology_type": "local"}'
```

---

### 5.2 Bandwidth & Topology Configuration

The bandwidth model computes the **migration bottleneck** — the single slowest link that limits how fast data can move. Four speeds are evaluated; the minimum wins.

| Parameter | Meaning | Default |
|-----------|---------|---------|
| `source_nic_speed_gbps` | Source ESXi NIC speed | 10 Gbps |
| `source_usable_pct` | % of source NIC usable for migration | 40% |
| `link_speed_gbps` | WAN/dedicated link speed (cross-site only) | — |
| `link_usable_pct` | % of link usable for migration | 60% |
| `source_upload_mbps` | Internet upload cap (internet topology only) | — |
| `dest_download_mbps` | PCD internet download cap (internet only) | — |
| `target_ingress_speed_gbps` | PCD NIC ingress speed | 10 Gbps |
| `target_usable_pct` | % of target NIC usable for migration | 40% |
| `pcd_storage_write_mbps` | PCD Cinder/Ceph write throughput | 500 Mbps |

**Bottleneck formula** (engine: `compute_bandwidth_model()`):

```
effective_mbps = MIN(
    source_nic × source_usable_pct,
    link_speed  × link_usable_pct,     # only if cross-site
    target_nic  × target_usable_pct,
    pcd_storage_write_mbps
) × 0.8   # 20% overhead reserve
```

The live bandwidth preview on the ProjectSetup tab recalculates instantly as you change any field (client-side `useMemo` mirrors the server engine).

**Schedule-aware planning fields**:

| Field | Default | Notes |
|-------|---------|-------|
| `migration_duration_days` | 30 | Total calendar days in the migration window |
| `working_hours_per_day` | 8.0 | Active migration hours per day |
| `working_days_per_week` | 5 | Working days (e.g. 5 = Mon–Fri) |
| `target_vms_per_day` | auto | Override VMs/day for the VM-slot scheduler |
| `daily_change_rate_pct` | 5% | Warm migration: assumed daily churn for initial re-sync estimate |

---

### 5.3 Uploading RVTools Data

**UI**: Migration → [Project] → Setup → Upload RVTools File

1. Export RVTools from your vSphere Client with all sheets enabled.
2. Click **Upload RVTools File** and select the `.xlsx`.
3. The API parses all supported sheets in a single pass:

| Sheet | Data extracted |
|-------|---------------|
| `vInfo` | VM identity, power state, OS, CPU/RAM, folder, resource pool, vApp, UUID, firmware, CBT state, IP |
| `vDisk` | Per-disk label, path, capacity (MB), thin/thick provisioning, datastore |
| `vNIC` | Per-NIC adapter type, portgroup name, connected state, MAC, IP |
| `vHost` | Physical host CPU model, core/thread counts, RAM, NIC speed |
| `vCluster` | Cluster host count, total CPU/RAM, HA/DRS state |
| `vPartition` | Per-partition used space (aggregated to `in_use_gb` per VM) |
| `vCPU` | Per-VM `cpu_usage_percent` and `cpu_demand_mhz` (used in performance-based sizing) |
| `vMemory` | Per-VM `memory_usage_percent` and `memory_usage_mb` |
| `vNetwork` | Network/portgroup VLAN, subnet, gateway, DNS, DHCP range |
| `vSnapshot` | Snapshot count, depth, oldest snapshot age |

**Column normalization**: The parser uses a fuzzy alias table (`COLUMN_ALIASES` in `migration_engine.py`) that maps all known RVTools column header variants to canonical names. A column header that is unrecognized is silently ignored — the import never fails due to a missing or renamed column.

**Re-uploading**: Uploading a new file to an existing project performs a **full clean slate** — all VM, tenant, cohort, wave, and network mapping data is purged before re-ingesting. Confirmed subnet details and operator-edited target names are **not** preserved; you must re-confirm them.

**Clearing data** (without re-uploading): `DELETE /api/migration/projects/{id}/rvtools` — purges all VM/tenant/cohort/wave/network/flavor/image/user/prep task data but preserves the project settings and risk configuration.

---

### 5.4 Tenant Detection

After upload, the API runs tenant detection over every VM using the configured detection methods in priority order. The first method that returns a non-empty result wins.

**Default method order**:

| Priority | Method | How it works |
|----------|--------|-------------|
| 1 | `vcd_folder` | VMware Cloud Director: scans folder path + resource pool for `*[-_]VDC[-_]<number>` patterns or UUID-bearing segments. Returns `(org_name, org_vdc)` |
| 2 | `folder_path` | Extracts the Nth segment from the VM folder path (default: segment 2) |
| 3 | `resource_pool` | Extracts the last meaningful segment from the resource pool path, stripping UUID suffixes |
| 4 | `vapp_name` | Uses the vApp name directly as the tenant |
| 5 | `vm_name_prefix` | Splits the VM name on a separator (default: `-`) and uses the first N parts |
| 6 | `annotation_field` | Parses a key=value pair from the VM annotation field (default key: `Tenant`) |
| 7 | `cluster` | Uses the ESXi cluster name as the tenant (best fallback for non-vCD environments) |
| fallback | — | VMs that match no method are assigned to `"Unassigned"` |

**Editing detection configuration**:

1. Go to **Migration → [Project] → Source Analysis → ⚙️ Risk Config** (sub-tab within SourceAnalysis)
2. The detection config is stored as JSONB in `migration_tenant_rules.detection_config`
3. You can enable/disable individual methods and adjust parameters (folder depth, separator character, annotation field name)

**OrgVDC detection** (vCD environments): If `orgvdc_detection.use_resource_pool=true`, the resource pool path is also parsed to extract the OrgVDC name. `use_folder_depth3=true` extracts it from folder depth 3 instead.

After upload, detected tenants appear on the **Tenants** sub-tab. Click **✏️ Edit** on any tenant row to rename it or change its properties.

> **Inline tenant editing**: `PATCH /api/migration/projects/{id}/tenants/{tid}` — cascades the rename to all VMs assigned to that tenant.

---

### 5.5 Running the Assessment

**UI**: Migration → [Project] → Source Analysis → ▶️ Run Assessment  
**API**: `POST /api/migration/projects/{id}/assess`

The assessment engine:

1. **Risk scoring**: evaluates each VM against the configured risk rules (see §5.6); produces a score 0–100 and a `risk_category` (GREEN < 40, YELLOW 40–74, RED ≥ 75)
2. **OS classification**: classifies each VM's OS into `windows`, `linux`, or `other`
3. **Migration mode**: classifies each VM as `warm` or `cold` based on risk score and OS-specific rules
4. **Per-VM time estimate**: computes warm (initial data-sync + cutover) and cold (full offline copy) hours using the configured bandwidth model
5. **VM summaries**: aggregates disk count, total disk GB, used disk GB (from vPartition), snapshot count and age

Assessment results are stored back into `migration_vms` and are visible immediately in the VM table.

**Resetting assessment**: `POST /api/migration/projects/{id}/reset-assessment` — clears all computed scores without deleting VM records. Use before re-running with modified risk config.

---

### 5.6 Risk Configuration

**UI**: Migration → [Project] → Source Analysis → ⚙️ Risk Config sub-tab

The risk engine is fully config-driven. The rules are stored as JSONB in `migration_risk_config` and can be edited per-project.

**Default risk rules**:

| Rule | Default | Description |
|------|---------|-------------|
| `os_unsupported` | Windows NT 4, Solaris, AIX, HP-UX, FreeBSD, SCO | OS types that trigger maximum risk (+30 pts by default) |
| `os_deprecated` | WS 2003, WS 2008, WinXP, CentOS 6, RHEL 5, Ubuntu 12/14 | Deprecated OS (+15 pts) |
| `os_cold_required` | Solaris, AIX, HP-UX, FreeBSD, SCO | Forces cold migration regardless of risk score |
| `disk_large_threshold_gb` | 2000 GB | Large disk threshold (+10 pts) |
| `disk_very_large_threshold_gb` | 5000 GB | Very large disk threshold (+25 pts) |
| `disk_count_high` | 8 | High disk count threshold (+10 pts) |
| `snapshot_depth_warning` | 3 | Multiple snapshots warning (+8 pts) |
| `snapshot_depth_critical` | 5 | Critical snapshot depth (+20 pts) |
| `snapshot_age_warning_days` | 30 | Old snapshot threshold (+5 pts) |
| `nic_count_high` | 4 | High NIC count (+10 pts) |
| `ram_very_large_gb` | 512 | Very large RAM threshold (+10 pts) |

**Risk category thresholds** (also configurable):

| Category | Score range | Meaning |
|----------|-------------|---------|
| 🟢 GREEN | 0–39 | Standard migration; eligible for warm migration |
| 🟡 YELLOW | 40–74 | Elevated risk; review required before scheduling |
| 🔴 RED | 75–100 | High risk; may require cold migration or manual preparation |

**Warm vs cold classification logic**:
- VMs with OS in `os_cold_required` → always cold
- VMs with risk score ≥ `warm_risky_threshold` (default 50) AND OS in `os_warm_risky` → cold recommended
- All others → warm

After editing risk rules, click **▶️ Run Assessment** again to recompute scores.

---

### 5.7 VM Table & Filters

The VM table is accessible on the **VMs** sub-tab of Source Analysis. It supports server-side filtering, sorting, and pagination.

**Available filters**:

| Filter | Values | Notes |
|--------|--------|-------|
| Search | Free text | Matches VM name, OS, IP, cluster |
| Power State | All / poweredOn / poweredOff / suspended | |
| OS Family | All / Windows / Linux / Other | |
| Risk Category | All / GREEN / YELLOW / RED | Based on computed risk score |
| Migration Mode | All / warm / cold | After assessment |
| Cluster | All / [cluster names] | Populated from upload |
| Migration Status | All / not_started / assigned / in_progress / migrated / failed / skipped | |
| Tenant | All / [detected tenants] | |

**Columns displayed** (selectable):

VM Name · Power State · OS Version · CPU Count · RAM (GB) · Total Disk (GB) · Used (GB) · Disk Count · NIC Count · Network · Cluster · Risk Score · Migration Mode · Status · Fix Time

---

### 5.8 Expandable VM Detail Rows

Click any row in the VM table to expand it. The expanded row shows:

**Disk table**: Disk Label · Size (GB) · Thin · Datastore  
**NIC table**: NIC Label · Adapter Type · Network · IP Address · MAC Address · Connected  
**Risk Factors**: List of each rule that fired with its score contribution, e.g.:
```
⚠️ Large disk: 2400 GB (≥ 2000 GB) (+10)
⚠️ Multiple snapshots: 4 (+8)
```

**VM actions in expanded row**:

- **🔓 Override Mode**: Force `warm`, `cold`, or `auto` (engine decision) — overrides are shown with a 🔒 lock icon in the main table
- **Fix Time Override**: Set a manual tech fix estimate (minutes) for this specific VM
- **➕ Add Dependency**: Link this VM to another VM that must complete migration first

**API** (VM detail):
```bash
GET /api/migration/projects/{id}/vms/{vm_name}/details
```

---

### 5.9 Migration Plan View

**UI**: Migration → [Project] → Source Analysis → 📋 Migration Plan sub-tab

The migration plan is generated on-demand from the current scoping and bandwidth configuration.

**Plan contents**:

- **Executive KPI strip**: Total VMs · Total Data (TB) · Est. Copy Time · Est. Fix Time · Est. Downtime
- **Cohort Execution Plan**: Per-cohort table showing Start Day, End Day, Duration (days), VM count
- **Per-tenant assessment table**: Grouped by cohort; each tenant shows warm/cold VM counts, initial data-sync hours, cutover hours, total hours, risk distribution
- **Expandable tenant rows**: Individual VMs with per-VM timing (warm: copy hours + cutover hours + downtime window; cold: total hours + downtime)
- **Daily schedule**: Calendar-style table showing which VMs are scheduled on each day, with cohort separator rows. Each VM is shown as a pill with name and mode

**Cohort-sequential scheduling**: The daily scheduler processes cohorts one at a time in `cohort_order` sequence. Each cohort exhausts completely before the next begins, and each new cohort block starts on a fresh day.

**Exporting the plan**:

| Format | Endpoint | Contents |
|--------|----------|----------|
| JSON | `GET /export-plan` | Full nested structure (cohorts → tenants → VMs → daily schedule) |
| CSV | `GET /export-plan?format=csv` | Flat VM-level rows with tenant, mode, timing, scheduled day |
| Excel (4 sheets) | `GET /export-summary.xlsx` | Executive Summary · VMs · Tenants · Daily Schedule |
| PDF | `GET /export-summary.pdf` | Landscape A4, colour-coded risk tables |

---

## 6. Tenant Scoping, Target Mapping & Capacity

### 6.1 Tenant Scoping

**UI**: Source Analysis → Tenants sub-tab → Scope column

By default, all detected tenants are **in-scope** for the migration plan. Use the scope controls to exclude tenants that will not be migrated (e.g., infrastructure tenants, decommissioned environments, test VMs).

**Per-tenant actions**:

| Action | UI | API |
|--------|-----|-----|
| Exclude a tenant | Uncheck the **In Scope** checkbox | `PATCH /tenants/{tid}` with `include_in_plan: false` |
| Set exclude reason | Text field next to the checkbox | `PATCH /tenants/{tid}` with `exclude_reason: "..."` |
| Bulk exclude/include | Select rows → toolbar **Bulk Scope** | `PATCH /tenants/bulk-scope` |
| Auto-exclude by pattern | ⚙️ Tenant Filters | `POST /tenant-filters` |

**Auto-exclude patterns** (`migration_tenant_filters` table): Define regex or substring patterns. Any tenant whose name matches a pattern is automatically excluded when tenants are detected or refreshed. Useful for filtering out infrastructure tenants like `mgmt-*` or `infra-*`.

```bash
# Add an auto-exclude pattern
curl -X POST http://localhost:8000/api/migration/projects/{id}/tenant-filters \
  -H "Authorization: Bearer <token>" \
  -d '{"pattern": "infra-", "match_type": "prefix", "reason": "Infrastructure tenants"}'
```

The **summary banner** shows "X / Y tenants in scope" and warns when excluded tenants are present with "⚠️ N tenants excluded from this plan".

---

### 6.2 Target Mapping

**UI**: Source Analysis → Tenants sub-tab → Target Domain / Target Project columns

Every in-scope tenant must have a target mapping before provisioning can start. The mapping defines where the tenant's VMs will land in PCD.

**Fields per tenant**:

| Field | Meaning |
|-------|---------|
| `target_domain_name` | PCD Keystone domain to create/use |
| `target_domain_description` | Human-readable domain description |
| `target_project_name` | PCD project within the domain |
| `target_display_name` | Customer-visible project display name |

**Pre-seeding**: On import, tenant rows are pre-seeded with `target_domain_name = target_project_name = tenant_name` (and `target_confirmed = false`). Unconfirmed rows are highlighted amber with a ⚠️ badge.

**Confirming a mapping**: Click **Confirm** (for a pre-seeded row) or **Save** (after editing). Confirmed rows show ✓.

**Bulk operations**:

| Button | Action |
|--------|--------|
| 🔍 Find & Replace | Find-and-replace substring across any of the 4 name fields |
| ✓ Confirm All | Mark all unconfirmed tenant rows as confirmed |

**Find & Replace**:
- Works on: `target_domain_name`, `target_domain_description`, `target_project_name`, `target_display_name`
- Supports preview (dry-run) before applying
- `unconfirmed_only` option limits scope to pre-seeded rows
- After apply, affected rows are reset to `target_confirmed = false` for review

---

### 6.3 Overcommit Profiles & Quota Modeling

**UI**: Source Analysis → ⚖️ Capacity sub-tab

The quota model computes recommended PCD project quotas for each in-scope tenant, accounting for VM allocation, snapshot growth, and the selected overcommit ratios.

**Built-in overcommit profiles**:

| Profile | CPU overcommit | RAM overcommit | Disk growth factor |
|---------|:-:|:-:|:-:|
| **Aggressive** | 8:1 | 2:1 | 1.3× |
| **Balanced** (default) | 4:1 | 1.5:1 | 1.5× |
| **Conservative** | 2:1 | 1:1 | 2.0× |

Select a profile using the radio cards in the Capacity tab. The profile can be overridden per-cohort (see §7.5).

**Quota requirements table**: Shows per-tenant recommended vCPU quota, RAM quota (GB), and Cinder storage quota (GB). Values respect the overcommit ratios and include the disk growth factor.

---

### 6.4 PCD Node Sizing

**UI**: Source Analysis → ⚖️ Capacity sub-tab → Node Sizing section

The node sizing engine computes how many physical PCD compute nodes are needed to host the migrated VMs with a **70% utilization cap** (this is also the HA headroom — no additional N+1 spare nodes are added on top).

#### Three-tier sizing basis

The engine selects the most accurate demand basis automatically:

| Tier | When used | How |
|------|-----------|-----|
| **Actual performance** (most accurate) | ≥50% of powered-on VMs have `cpu_usage_percent` data from RVtools vCPU sheet | `SUM(cpu_count × cpu_usage_percent / 100)` — reflects real scheduler pressure |
| **Allocation ÷ overcommit** | No performance data available | `SUM(cpu_count) / overcommit_ratio` |
| **Quota** | No RVtools data at all | Tenant quota totals |

A **sizing basis badge** shows which tier was used and the coverage percentage:
- Green: "📊 Based on actual VM performance data · 100% VM coverage · 125 vCPU running of 1371 allocated"
- Amber: "⚠️ Based on vCPU allocation ÷ overcommit (no performance data)"

> **Note**: Node sizing is driven only by vCPU and RAM. Cinder block storage is independent infrastructure — sized separately and reported as `disk_tb_required` (informational only, shown as "provision via storage backend").

**Auto-detect from PCD**: Click **🔍 Auto-Detect from PCD** to query the `hypervisors` table for the dominant node type (most common vCPU+RAM configuration) in the existing PCD cluster. Pre-fills the node profile form.

**Live PCD inventory sync**: Click **📥 Sync to Inventory** to pull current node count and resource usage from the live PCD cluster (queries `hypervisors` + `servers` tables). Shown in a green "Live PCD Cluster" panel.

**Sizing output**:

| Field | Meaning |
|-------|---------|
| `nodes_additional` | PCD nodes to add (for the migration workload) |
| `nodes_total` | Total nodes after migration (existing + additional) |
| `post_migration_cpu_util_pct` | Projected CPU utilization after migration |
| `post_migration_ram_util_pct` | Projected RAM utilization after migration |
| `binding_dimension` | Which resource is the sizing constraint (CPU or RAM) |
| `sizing_basis` | Which tier was used (actual_performance / allocation / quota) |

---

### 6.5 PCD Readiness & Gap Analysis

**UI**: Source Analysis → 🎯 PCD Readiness sub-tab

Gap analysis compares what the migration plan needs against what the target PCD cluster already has. It requires a working PCD connection.

**Configuring PCD connection** (per project):
1. Enter Auth URL, Username, Password, Region in the Settings panel
2. Click **Run Gap Analysis**

**Gap types**:

| Gap type | Severity | What it means |
|----------|----------|--------------|
| `missing_flavor` | Warning | A required VM shape does not exist as a PCD flavor |
| `missing_network` | Critical | A source portgroup has no confirmed PCD network mapping |
| `missing_image` | Critical | A required OS image is not present in Glance |
| `unmapped_tenant` | Warning | An in-scope tenant has no target domain/project assigned |

**Readiness score**: 0–100 composite computed from gap severity (critical gaps lower the score more). Shown as a colour-coded badge.

**Gap details column**: Each gap row shows a "Why / Details" column explaining the gap (e.g., required vCPU count, affected VM names) and a collapsible affected VM list.

**Marking gaps resolved**: Once you have fixed a gap externally (e.g., created the missing flavor manually), click **Mark Resolved** on that row. Network gaps auto-resolve when the corresponding source network has a confirmed mapping.

**Exporting the gap report**:

| Format | Endpoint |
|--------|----------|
| Excel (3 sheets) | `GET /export-gaps-report.xlsx` |
| PDF (landscape A4) | `GET /export-gaps-report.pdf` |

Excel sheets: Executive Summary (score, gap counts, quota, sizing) · Action Items (unresolved gaps with effort estimate) · All Gaps

---

### 6.6 Network Map

**UI**: Source Analysis → 🔌 Network Map sub-tab

The network map records the source VMware portgroup → target PCD network mapping for every network found on in-scope VMs.

**Auto-seeding**: On upload, all distinct portgroup names are automatically inserted as unconfirmed rows with `target_network_name = source_network_name`. The literal `"none"` portgroup is filtered out.

**Columns**:

| Column | Editable | Notes |
|--------|----------|-------|
| Source Network | No | From RVtools vNIC sheet |
| VM Count | No | Number of VMs using this network |
| Network Type | Yes (dropdown) | `physical_managed`, `physical_l2`, `virtual` |
| VLAN ID | Yes | Extracted from name if `*_vlan_<id>*`; editable |
| Target Network | Yes | PCD network name |
| Status | — | ⚠️ unconfirmed · ✓ confirmed |

**Network type guidance**:

| Type | When to use |
|------|-------------|
| `physical_managed` | VLAN-tagged provider networks (most common for VLAN-backed portgroups) |
| `physical_l2` | Flat/trunk-only L2 networks without external routing |
| `virtual` | Isolated/internal-only networks with no external routing |

**Confirming a mapping**: Click **Confirm** (pre-seeded unedited row) or **Save** (after editing target name). Confirmed rows show ✓.

**Bulk operations**:

| Button | Action |
|--------|--------|
| 🔍 Find & Replace | Find-and-replace in `target_network_name` |
| ✓ Confirm All | Confirm all rows that have a target name |

**Stale network cleanup**: On re-upload, any mapping whose `source_network_name` is no longer present in the new VM dataset is automatically deleted.

> **Note**: The subnet details required for provisioning (CIDR, gateway, DNS, DHCP pool) are confirmed in the Data Enrichment section (see §10.1). The Network Map section only requires name confirmation.

---

## 7. Pre-Wave Foundations

### 7.1 VM Status Tracking

Each VM has a `migration_status` field tracking its position in the execution lifecycle.

| Status | Meaning |
|--------|---------|
| `not_started` | Default; VM has not been touched |
| `assigned` | VM has been assigned to a wave |
| `in_progress` | Wave is actively executing for this VM |
| `migrated` | VM successfully migrated |
| `failed` | Migration attempt failed |
| `skipped` | Intentionally excluded from migration |

**Updating status**:

```bash
# Single VM
PATCH /api/migration/projects/{id}/vms/{vm_id}/status
Body: {"status": "skipped", "status_note": "VM decommissioned"}

# Bulk
PATCH /api/migration/projects/{id}/vms/bulk-status
Body: {"vm_ids": [1, 2, 3], "status": "skipped"}
```

**UI**: Status pill column in VM table (colour-coded); filter by status in the VM filter bar.

---

### 7.2 VM Migration Mode Override

The assessment engine auto-classifies VMs as warm or cold. Operators can override this per VM.

**Override values**: `'warm'` · `'cold'` · `null` (revert to engine classification)

**UI**: Expanded VM row → 🔓 Override button → warm/cold/auto selector. VM table shows 🔒 when an override is active.

**API**:
```bash
PATCH /api/migration/projects/{id}/vms/{vm_id}/mode-override
Body: {"override": "warm"}  # or "cold" or null
```

---

### 7.3 Tenant Migration Priority

Tenants have a `migration_priority` integer (lower = migrated earlier, default 999). This drives auto-assignment in cohort planning and the `by_priority` wave strategy.

**UI**: Tenants tab → Priority column (editable number field). Sort tenants by priority. Unset priority (999) is displayed as "—".

**API**: `PATCH /api/migration/projects/{id}/tenants/{tid}` with `migration_priority: 1`

---

### 7.4 VM Dependency Annotation

VM dependencies ensure that during wave planning, a web-tier VM is never scheduled before its database VM.

**Adding a dependency manually** (UI):
1. Expand the VM row
2. Click **➕ Add Dependency**
3. Search and select the VM that must complete first

The system validates for circular dependencies before saving.

**Dependency types**: `must_complete_before` (only type currently used; extensible)

**API**:
```bash
# List dependencies
GET /api/migration/projects/{id}/vm-dependencies

# Add
POST /api/migration/projects/{id}/vm-dependencies
Body: {"vm_id": 42, "depends_on_vm_id": 17, "notes": "web depends on DB"}

# Remove
DELETE /api/migration/projects/{id}/vm-dependencies/{dep_id}
```

#### Automatic dependency import

**UI**: Wave Planner toolbar → 🔍 Auto-Import Dependencies

The engine (`detect_auto_dependencies()`) detects two classes of implicit dependencies:

| Detection type | Logic | Confidence |
|---------------|-------|:-:|
| **RDM shared disk** | VMs with `rdm_disk_count > 0` sharing an RDM LUN path → must co-migrate | 0.95 |
| **Shared datastore** | VMs sharing a non-standard datastore name within the same tenant | 0.70 |

Auto-imported dependencies are tagged with `dep_source = 'rdm'` or `'shared_datastore'` and shown with an amber badge (confidence %). Manual dependencies show a blue badge.

**Dry-run first**: Click **🔍 Auto-Import Dependencies** to see estimated counts before committing. The dialog shows `{would_create, skipped_existing}` per source type.

**Clearing auto-imported dependencies** (without affecting manual ones): Click **🗑 Clear Auto-Imported** or:
```bash
DELETE /api/migration/projects/{id}/vm-dependencies/auto-imported
```

---

### 7.5 Cohort Management

Cohorts allow splitting a large migration project (e.g., 130 tenants, 400 VMs) into independent ordered workstreams. Each cohort has its own schedule, team owner, and wave plan.

**Architecture**:
```
migration_projects (1)
  └── migration_cohorts (many)
        └── migration_tenants (many, one cohort per tenant)
              └── migration_waves (many — Wave Planning)
                    └── migration_wave_vms (many)
```

Cohorts are **optional**. If you create no cohorts, all existing functionality works on the full project as a single implicit cohort.

**UI**: Source Analysis → 🗃️ Cohorts sub-tab

**Creating a cohort**:

| Field | Required | Notes |
|-------|:--------:|-------|
| Name | Yes | e.g. "🧪 Pilot", "Cohort 1 — Finance" |
| Description | No | |
| Order | No | Execution sequence (lower = earlier); default 999 |
| Scheduled Start/End | No | Calendar dates for this cohort window |
| Owner | No | Team/person responsible |
| Depends On | No | Gate: this cohort cannot start until the predecessor cohort is complete |
| Overcommit Profile Override | No | Override the project-level profile for this cohort |
| Agent Slots Override | No | Different concurrency for this cohort |

**Assigning tenants**: In the right-hand assignment panel, check tenants and click **Assign to Selected Cohort**. Unassigned tenants show ⚠️.

**Gantt preview**: Horizontal bars showing cohort dates on a timeline with dependency arrows. Cohorts with `depends_on_cohort_id` show 🔒 when the predecessor is not complete.

**Cohort summary cards** show: VM count · tenant count · total used disk (TB) · estimated migration time · average ease score · risk distribution pill · OS mix · readiness status · cross-cohort dependency warnings.

**API**:
```bash
GET    /api/migration/projects/{id}/cohorts
POST   /api/migration/projects/{id}/cohorts
PATCH  /api/migration/projects/{id}/cohorts/{cid}
DELETE /api/migration/projects/{id}/cohorts/{cid}       # must be empty
POST   /api/migration/projects/{id}/cohorts/{cid}/assign-tenants
GET    /api/migration/projects/{id}/cohorts/{cid}/summary
```

---

### 7.6 Tenant Readiness Checklist

Each tenant has a readiness state automatically computed from plan completeness. The Tenants tab shows a 🟢/🟡/🔴 badge per tenant.

**Automatic checks**:

| Check | Pass condition |
|-------|---------------|
| `target_mapped` | `target_domain_name IS NOT NULL` and `target_confirmed = true` |
| `network_mapped` | All VM networks for this tenant have a confirmed mapping |
| `quota_sufficient` | Tenant quota fits within the cohort/project capacity |
| `no_critical_gaps` | No unresolved critical PCD gaps affecting this tenant's VMs |
| `vms_classified` | All powered-on VMs have a migration mode (warm/cold/override) |

**API**: `GET /api/migration/projects/{id}/tenants/{tid}/readiness`

---

## 8. Smart Cohort Planning

### 8.1 Ease Score Engine

The ease score is a composite 0–100 metric (lower = easier to migrate first) computed per tenant from existing data.

**Dimensions**:

| Dimension | Default weight | Signal |
|-----------|:-:|-------|
| Risk score | 25 | Average VM risk score |
| Disk usage | 20 | Total used disk GB (more data → harder) |
| OS support | 20 | % VMs with a confirmed/supported OS (inversely weighted) |
| VM count | 15 | More VMs → larger blast radius |
| Networks | 10 | Distinct network count (each NIC needs a confirmed mapping) |
| Cross-tenant deps | 5 | VM dependencies to VMs in other tenants |
| Warm/cold ratio | 3 | Cold VMs → higher business impact |
| Unconfirmed mappings | 2 | Unconfirmed target/network names |

**Ease score breakdown**: Click the ease score badge in the Tenants tab to see a per-dimension breakdown popover:

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

Weights are exposed as configurable sliders in the Cohorts tab (they do not affect stored data — only the preview ranking).

**API**: `GET /api/migration/projects/{id}/tenant-ease-scores?weights=...`

---

### 8.2 Auto-Assign Strategies & Guardrails

**UI**: Source Analysis → 🗃️ Cohorts sub-tab → **Auto-Assign** panel

The auto-assign engine proposes a cohort assignment for all unassigned tenants using the selected strategy. All strategies support dry-run preview before committing.

**Strategies**:

| Strategy | Logic |
|----------|-------|
| **Easiest first** | Sort by `ease_score ASC`; fill cohorts sequentially up to cap |
| **Riskiest last** | High-risk tenants always in the last cohort; remaining by ease score |
| **Pilot + bulk** | Auto-create "🧪 Pilot" (top 5 easiest) + "🚀 Main" (all others) — validates toolchain before committing |
| **Balanced load** | Minimise variance in `SUM(total_used_gb)` per cohort (equal wall-clock time per cohort) |
| **OS-first** | Group by OS family: Linux cohort → Windows cohort → Other |
| **By priority** | Uses `migration_priority` from §7.3 (ignores ease score) |

**Ramp profile mode**: Combine strategies with a ramp profile: `flat` (equal distribution), `ramp_up` (small pilot → growing cohorts), `ramp_down` (large first cohort → smaller finishing cohorts).

**Guardrails** (applied before the strategy runs):

| Guardrail | Default | Description |
|-----------|---------|-------------|
| `max_vms_per_cohort` | 50 | No cohort will exceed this VM count |
| `max_disk_tb_per_cohort` | 20 | No cohort will exceed this disk volume |
| `max_avg_risk` | 60 | Prevents high-risk tenants slipping into the pilot |
| `min_os_support_rate` | 0.80 | Each cohort must be ≥80% supported OSes |

**API**:
```bash
POST /api/migration/projects/{id}/cohorts/auto-assign
Body: {
  "strategy": "easiest_first",
  "num_cohorts": 4,
  "dry_run": true,
  "guardrails": {"max_vms_per_cohort": 50},
  "ease_weights": {"disk": 30, "risk": 30}
}
```

---

### 8.3 What-If Estimator

**UI**: Source Analysis → 🗃️ Cohorts sub-tab → What-If panel

The what-if estimator recalculates cohort time estimates live (no API calls) as you adjust parameters.

**Two-model comparison** (shown side-by-side per cohort):

| Model | Formula | Best for |
|-------|---------|---------|
| **BW Days** (bandwidth/transfer model) | `effMbps = bw × 0.75; transferH = (diskGb × 1024 × 8) / (effMbps × 3600) × 1.14; cutoverH = tenants × 0.25 / agentSlots; bwDays = (transferH + cutoverH) / workHours` | Data-heavy migrations |
| **Sched. Days** (VM-slots model) | `schedDays = vm_count / effectiveVmsPerDay` | VM-count-heavy migrations |

**Controls**:

| Slider | Range | Effect |
|--------|-------|--------|
| Bandwidth | 1–100 Gbps | Updates BW Days for all cohorts |
| Agent slots | 1–20 | Updates both models |
| Working hours/day | 4–24 | Updates both models |

**Project deadline banner**: Turns red if either model estimate exceeds `project.migration_duration_days`.

**Tenant reassignment**: Expand any cohort card with **▾ N Tenants** to see the tenant list. Each tenant row has a **Select cohort…** dropdown for instant reassignment (time estimates update immediately; committed on **💾 Save Assignment**).

**Reset to Saved**: Discard all local what-if changes without a page reload.

---

### 8.4 Cohort Comparison View

**UI**: Source Analysis → 🗃️ Cohorts sub-tab → **Compare** table

Side-by-side table of all cohorts showing: VM count · tenant count · total disk (TB) · avg ease score · avg risk score · OS mix · readiness status · estimated days (both models). Columns are sortable.

**Rebalance button**: Triggers `auto-assign` with the `balanced_load` strategy and previews the proposed change before committing.

---

## 9. Wave Planning

### 9.1 Building Waves

**UI**: Source Analysis → 🌊 Wave Planner sub-tab → **Auto-Build Waves** panel

Waves are execution units — a batch of VMs that vJailbreak runs in one migration operation. Waves belong to a cohort (or the whole project if no cohorts are defined).

**Auto-build strategies**:

| Strategy | Logic |
|----------|-------|
| `pilot_first` | Creates a small pilot wave (5 lowest-risk VMs) then remaining waves by tenant |
| `by_tenant` | All VMs of each tenant go into the same wave |
| `by_risk` | Green VMs in early waves; Red VMs in later waves |
| `by_priority` | Uses `migration_priority` from §7.3 |
| `balanced` | Minimise variance in VM count per wave |

**Cohort-scoped building**: `auto_build_waves` iterates cohorts in `cohort_order` sequence, calling `build_wave_plan()` once per cohort. VMs not in any cohort are collected as an "Unassigned" group.

**Dependency cross-wave validation**: The wave builder detects cross-wave dependency violations — cases where VM A is assigned to Wave 2 but VM B (which A depends on) is in Wave 3. Violations are returned as warnings; the plan is still created but flagged for review.

**Dry-run**: Set `dry_run: true` to preview the proposed wave plan without committing. The preview table shows a Cohort column when multiple cohorts exist.

**API**:
```bash
POST /api/migration/projects/{id}/waves/auto-build
Body: {
  "strategy": "by_risk",
  "vms_per_wave": 20,
  "cohort_id": 3,       # optional; omit for all cohorts
  "dry_run": true
}
```

---

### 9.2 Wave Lifecycle

Each wave moves through a state machine with enforced transitions.

```
planned
  │  (request approval)
  ▼
pending_approval  ──(admin approves)──▶  approved
                  ◀──(admin rejects)──  (stays at planned)
  │
  ▼ (advance, requires approval)
pre_checks_passed
  │
  ▼ (advance)
executing
  │
  ▼ (advance)
validating
  │
  ├──▶ complete
  ├──▶ failed
  └──▶ cancelled
```

**Advance API**:
```bash
POST /api/migration/projects/{id}/waves/{wid}/advance
Body: {"target_status": "pre_checks_passed"}
```

Advancing to `pre_checks_passed` requires the wave to have `approval_status = 'approved'` (see §9.4). Attempting to advance an unapproved wave returns HTTP 409.

**Wave fields**:

| Field | Meaning |
|-------|---------|
| `wave_type` | `standard` / `pilot` / `rollback` |
| `agent_slots_override` | Override project-level agent concurrency for this wave |
| `scheduled_start` / `scheduled_end` | Planned date window (used for Gantt display and maintenance window snapping) |
| `owner_name` | Team/person responsible for this wave |
| `started_at` / `completed_at` | Actual timestamps (set by lifecycle advances) |

---

### 9.3 Pre-Flight Checklist

Before a wave can advance to `executing`, six automated checks verify readiness.

| Check | Type | Pass condition |
|-------|------|---------------|
| `network_mapped` | Blocker | All VM NICs in the wave have a confirmed network mapping |
| `target_project_set` | Blocker | All tenants in the wave have a confirmed `target_project_name` |
| `vms_assessed` | Blocker | All VMs in the wave have a risk score and migration mode |
| `no_critical_gaps` | Blocker | No unresolved critical PCD gaps affect wave VMs |
| `agent_reachable` | Warning | vJailbreak agent is reachable (informational — not enforced) |
| `snapshot_baseline` | Info | Snapshot baseline taken for all warm VMs |

**UI**: Each wave card has an expandable **Pre-Flight Checklist** section with pass ✅ / fail ❌ / skip ⏭️ per check.

**API**:
```bash
# Create/update a preflight result
POST /api/migration/projects/{id}/waves/{wid}/preflights
Body: {"check_name": "snapshot_baseline", "result": "pass", "notes": "Baseline taken 2026-03-15"}

# List preflights
GET /api/migration/projects/{id}/waves/{wid}/preflights
```

---

### 9.4 Wave Approval Gates

Every wave requires an explicit sign-off before it can advance past `planned`. This mirrors the PCD auto-provisioning approval pattern.

**Approval flow**:

1. **Technical user** clicks **🔒 Request Approval** on the wave card → fires `wave_approval_requested` notification
2. **Admin** reviews the wave plan and either:
   - Clicks **✅ Approve** (with optional comment) → sets `approval_status = 'approved'`
   - Clicks **❌ Reject** (with required comment) → sets `approval_status = 'rejected'`; operator must re-request
3. Once approved, the **Advance** button becomes active for the technical user

**UI states**:
- Grey — no approval request yet; shows 🔒 Request Approval button
- Amber — `pending_approval`; shows inline Approve/Reject for admins
- Green — `approved`; shows approver name + timestamp
- Red — `rejected`; shows rejection comment + re-request note

**API**:
```bash
# Request approval
POST /api/migration/projects/{id}/waves/{wid}/request-approval

# Approve or reject (admin only)
POST /api/migration/projects/{id}/waves/{wid}/approval
Body: {"decision": "approved", "comment": "LGTM — all preflights green"}

# Check approval status
GET /api/migration/projects/{id}/waves/{wid}/approval
```

---

### 9.5 Dependency Auto-Import

See §7.4 for the full description. Wave planning reads both manual and auto-imported dependencies (no filter by `dep_source`) when building waves and detecting cross-wave violations.

---

### 9.6 Maintenance Windows

Maintenance windows constrain when waves are scheduled — useful when migration cutovers are only permitted outside business hours.

**Enabling maintenance windows**:
```bash
PATCH /api/migration/projects/{id}
Body: {"use_maintenance_windows": true}
```

**UI**: Wave Planner toolbar → 🗓 Maintenance Windows section (collapsible)

**Creating a window**:

| Field | Required | Notes |
|-------|:--------:|-------|
| Label | Yes | e.g. "Saturday 22:00–05:00" |
| Day of week | No | 0=Mon … 6=Sun; `null` = any day |
| Start time | Yes | Local time (e.g. `22:00`) |
| End time | Yes | Local time; may cross midnight (e.g. `05:00`) |
| Timezone | No | Default UTC; uses IANA tz names (e.g. `Asia/Jerusalem`) |
| Cohort | No | Scope to a specific cohort; `null` = applies to whole project |

When `use_maintenance_windows = true`, the wave auto-builder calls `next_window_start()` to snap each wave's `scheduled_start` to the next available maintenance window slot after the previous wave ends.

**Calendar preview**: Click **📅 Preview next slots** to see the next 8 upcoming window slots from a chosen date (API: `GET /maintenance-windows/preview?start_date=2026-04-01&num_windows=8`).

**API**:
```bash
GET    /api/migration/projects/{id}/maintenance-windows
POST   /api/migration/projects/{id}/maintenance-windows
PATCH  /api/migration/projects/{id}/maintenance-windows/{mw_id}
DELETE /api/migration/projects/{id}/maintenance-windows/{mw_id}
GET    /api/migration/projects/{id}/maintenance-windows/preview
```

---

## 10. Data Enrichment

This section collects information that cannot be derived from RVTools — the exact network subnet specs, PCD flavor names, required OS images, and per-tenant user definitions. All data enrichment items must be confirmed before PCD auto-provisioning can run.

---

### 10.1 Network Subnet Details

**UI**: Source Analysis → 🔌 Network Map sub-tab → expand a confirmed row → Subnet Details section

For each confirmed network mapping, the operator must provide the PCD subnet spec:

| Field | Required | Notes |
|-------|:--------:|-------|
| CIDR | Yes | e.g. `192.0.2.0/24` (RFC 5737 documentation range) |
| Gateway IP | Yes | e.g. `192.0.2.1` |
| DNS Nameservers | No | Comma-separated; stored as `TEXT[]` |
| DHCP Pool Start | No | e.g. `192.0.2.100` |
| DHCP Pool End | No | e.g. `192.0.2.200` |
| DHCP Enabled | No | Default `true` |
| Is External | No | If `true`, this network already exists on PCD — skip creation |

**Subnet Details Ready counter**: Toolbar shows "X/Y networks with subnet details confirmed".

**Bulk input via Excel template**:
1. Click **📥 Export Template** → downloads an XLSX with one row per network
2. Fill in the subnet details in Excel (no formulas or external references)
3. Click **📤 Import Template** → bulk-fills and auto-confirms rows with CIDR

> **Warning**: Excel templates with external file references (VLOOKUP pointing to another file) are rejected with HTTP 422 and instructions to remove the references before importing.

**✓ Confirm Subnets**: Bulk-confirms all rows that have a CIDR. Import auto-confirms when CIDR is present.

**API**:
```bash
GET  /api/migration/projects/{id}/network-mappings/export-template
POST /api/migration/projects/{id}/network-mappings/import-template
POST /api/migration/projects/{id}/network-mappings/confirm-subnets
GET  /api/migration/projects/{id}/network-mappings/readiness
```

---

### 10.2 Flavor Staging

**UI**: Source Analysis → 🎯 PCD Readiness sub-tab → 🧊 Flavor Staging section

Gap analysis (§6.5) detects VM shapes that don't exist as PCD flavors. Flavor staging turns those detected shapes into editable draft flavors that the operator reviews before anything is created.

> **Boot-volume model**: VCD flavors define CPU and RAM only (`disk = 0 GB`). The VM boot disk is handled as a separate volume at migration time. Two VMs with the same CPU/RAM but different disk sizes map to the same flavor.

**Columns**:

| Column | Notes |
|--------|-------|
| Source Shape | e.g. `4vCPU-8GB` (CPU+RAM only) |
| VM Count | Number of VMs using this shape |
| Target Flavor Name | Operator edits this — becomes the PCD flavor name |
| Skip | Mark ↪️ to map to an existing PCD flavor instead |
| Existing Flavor | If skip=true, paste the existing PCD flavor ID here |
| Confirmed | ✓ ready for provisioning |

**Toolbar actions**:

| Button | Action |
|--------|--------|
| 🔄 Refresh from Gaps | Re-run gap detection; add new shapes; preserve operator edits |
| 🔍 Find & Replace | Find-and-replace in `target_flavor_name` |
| ✓ Confirm All | Confirm all rows |

---

### 10.3 Image Requirements

**UI**: Source Analysis → 🎯 PCD Readiness sub-tab → 🖼️ Image Requirements section

pf9-mngt cannot source or upload OS images. It generates a checklist of what is needed based on the OS families detected in the inventory.

**Columns**:

| Column | Notes |
|--------|-------|
| OS Family | e.g. `windows`, `linux-ubuntu`, `linux-rhel` |
| Version Hint | e.g. "Windows Server 2019", "Ubuntu 22.04" |
| VM Count | Number of VMs needing this image |
| Glance Image ID | Operator pastes the Glance UUID once the image is uploaded |
| Glance Image Name | Optional human-readable name |
| Confirmed | ✓ image is available |

**Windows images**: Require a licensed QCOW2 built with VirtIO drivers + Cloudbase-Init. This is noted on Windows rows.

**Images Ready counter**: Toolbar shows "X/Y images confirmed".

---

### 10.4 Per-Tenant User Definitions

**UI**: Source Analysis → 👤 Users sub-tab

Every PCD project needs at least a migration service account (used by vJailbreak) and a tenant owner account (used by the customer post-migration).

**Service accounts (auto-seeded)**:
- Auto-generated on project approval or when clicking **👤 Seed Service Accounts**
- Username format: `svc-migration-<project_slug>-<tenant_slug>`
- Role: `admin`
- 20-character random password (stored encrypted; never shown in plaintext in UI)
- `password_must_change = false` (service accounts must not expire during migration)

**Tenant owner accounts (operator-defined)**:
- Click **+ Add Tenant Owner** in a tenant section
- Set username, email, role (`admin`/`member`/`reader`), and whether this user already exists in Keystone/LDAP

**Seeding tenant owners in bulk**: Click **👤 Seed Tenant Owners** — creates one `admin@<domain_slug>` owner per tenant.

**Filter bar**: Filter by type / status / role / free-text search.

**Bulk operations**:

| Button | Action |
|--------|--------|
| 🔍 Find & Replace | Find-and-replace on username/email/role |
| ✓ Confirm All | Confirm all unconfirmed user rows |
| Bulk Actions | Select rows → Confirm / Set Role / Delete |

**Passwords**: Never shown in plaintext. Only "••••••••" with a 🔄 Regenerate button. Passwords are exported in the vJailbreak credential bundle (§12.1).

---

## 11. PCD Auto-Provisioning

This section covers auto-provisioning all required PCD resources in strict dependency order.

### 11.1 Readiness Gate

**UI**: Source Analysis → ⚙️ Prepare PCD sub-tab → Readiness Check panel

The readiness gate checks all four data enrichment items before allowing provisioning to start:

| Check | Pass condition |
|-------|---------------|
| Subnet Details | All confirmed network mappings have CIDR |
| Flavors | All flavor rows are confirmed or skipped |
| Images | All image requirement rows are confirmed |
| Users | All tenant user definitions are confirmed |

The **▶️ Start Provisioning** (Generate Tasks) button is disabled until all four checks are green.

---

### 11.2 Approval Workflow

Generating provisioning tasks triggers a **2-step approval gate**:

1. **Operator** clicks **▶️ Start Provisioning** → creates all prep tasks; sets `prep_approval_status = 'pending_approval'`; fires `prep_approval_requested` notification
2. **Admin** reviews task list and either:
   - Clicks **✅ Approve** → sets `prep_approval_status = 'approved'`; **▶ Run All** button becomes active
   - Clicks **❌ Reject** (with comment) → tasks remain but run is blocked; operator must re-generate
3. Once approved, **▶ Run All** executes all tasks

**Approval banner states** (same UX pattern as wave approval):
- Grey — no plan generated yet
- Amber — `pending_approval`; inline Approve/Reject for admins
- Green — `approved`; approver + timestamp
- Red — `rejected`; comment + re-generate note

**API**:
```bash
GET  /api/migration/projects/{id}/prep-approval
POST /api/migration/projects/{id}/prep-approval
Body: {"decision": "approved", "comment": "Verified all task counts"}
```

---

### 11.3 Dry-Run Simulation

Before running for real, validate which resources would be created vs skipped.

**UI**: ⚙️ Prepare PCD → 🧪 Dry Run button

The dry run authenticates to PCD, fetches existing domains/networks/flavors, and classifies each pending task:

| Classification | Meaning |
|---------------|---------|
| `would_create` | Resource does not exist yet — will be created |
| `would_skip_existing` | Resource already exists — will be skipped (idempotent) |
| `would_execute` | Task will execute regardless (quotas, subnets always apply) |

**API**:
```bash
POST /api/migration/projects/{id}/prepare/dry-run
```

Returns `{summary: {total, would_create, would_skip_existing, would_execute}, by_type: [...]}`

---

### 11.4 Running Provisioning

**UI**: ⚙️ Prepare PCD → ▶ Run All (requires approval)

Clicking **▶ Run All** opens a confirmation modal listing exact resource counts per task type before firing.

**Provisioning sequence** (order is strictly enforced):

| Order | Task type | Action |
|-------|-----------|--------|
| 1000s | `create_domain` | Create each distinct `target_domain_name` in Keystone |
| 2000s | `create_project` | Create each tenant's `target_project_name` under its domain |
| 3000s | `set_quotas` | Apply capacity planning quota recommendations (Nova + Cinder + Neutron) |
| 4000s | `create_network` | Build Neutron networks from confirmed network mappings |
| 5000s | `create_subnet` | Create subnets using confirmed subnet details |
| 6000s | `create_flavor` | Create Nova flavors from confirmed staging rows |
| 7000s | `create_user` | Create Keystone users for rows where `is_existing_user=false` |
| 8000s | `assign_role` | Assign each user their role in their project(s) |

Networks are created by calling the existing `POST /provision` workflow, which handles the Neutron naming conventions (`<domain>_tenant_extnet_vlan_<id>`). On completion, the returned Neutron network UUIDs are written back into `migration_network_mappings.target_network_id`.

**Progress table**: Task type · Resource name · Status badge · Error (expandable) · Retry / Rollback buttons. Groups by cohort, then task type within each cohort. Live refresh every 3 seconds while running.

**Completion notification**: Fires `prep_tasks_completed` — severity `critical` if any tasks failed, `info` if all succeeded.

**Provisioning Summary panel**: Auto-loads when all tasks reach `done`/`skipped`, showing task type × created/skipped/failed counts.

---

### 11.5 Task Rollback

Any completed task can be individually rolled back (undoes the PCD resource creation):

```bash
POST /api/migration/projects/{id}/prep-tasks/{task_id}/rollback
```

Common rollback scenarios:
- Roll back a `create_project` task to delete a project that was created by mistake
- Roll back `create_domain` to remove a domain created under the wrong parent

Rollback data (enough info to undo the action) is stored in `migration_prep_tasks.rollback_data JSONB`.

---

### 11.6 Audit Log

**UI**: ⚙️ Prepare PCD → 📋 Audit Log toggle

Three inline tables:

| Table | Contents |
|-------|---------|
| **Approval History** | All approve/reject decisions with approver, decision, comment, timestamp |
| **Activity Log** | High-level action entries from `activity_log` table |
| **Execution History** | All tasks that have been executed (`executed_by IS NOT NULL`) with status and timestamp |

**API**: `GET /api/migration/projects/{id}/prep-audit`

---

## 12. vJailbreak Handoff

This section covers the terminal output of the Migration Planner. After these exports, execution moves entirely to vJailbreak.

### 12.1 Credential Bundle Export

**UI**: ⚙️ Prepare PCD tab → Export panel (appears when all prep tasks are `done`/`skipped`)

The credential bundle is a structured JSON file containing everything vJailbreak needs to run migrations for a cohort.

**Bundle contents per tenant**:
- PCD project ID + domain (from provisioning write-back)
- Service account credentials (username + encrypted temp password)
- User list with temp passwords (decrypted only in the bundle)
- Network UUIDs (from `migration_network_mappings.target_network_id`) with CIDR, gateway, VLAN
- Wave sequence (wave order, VMs per wave, migration mode per VM)

**Exports**:
```bash
# Full project bundle
GET /api/migration/projects/{id}/export-vjailbreak-bundle

# Single cohort (for staged handoff)
GET /api/migration/projects/{id}/cohorts/{cid}/export-vjailbreak-bundle
```

The response includes a `warnings[]` array when any tenants are missing service accounts or PCD project IDs.

**Activity log**: Every bundle export is logged to `activity_log` and fires a `vjailbreak_bundle_exported` notification.

---

### 12.2 Tenant Handoff Sheet (PDF)

The handoff sheet is a customer-facing A4 portrait PDF. One section per in-scope tenant.

**Contents per tenant section**:
- Domain and project identity
- Network mappings (CIDR, gateway, VLAN)
- Users/credentials table (service accounts highlighted in blue)
- Confidentiality notice on every page

```bash
GET /api/migration/projects/{id}/export-handoff-sheet.pdf
```

---

### 12.3 vJailbreak CRD Push

**UI**: Source Analysis → 🚀 vJailbreak Push sub-tab

Instead of exporting a bundle file, you can push Kubernetes CRDs directly to vJailbreak's API.

**Setup** (per project):
1. **⚙️ Connection Settings** → Enter vJailbreak K8s API URL, namespace (default `migration`), and Bearer token
2. Configure **🖥️ VMware Credentials** (vCenter host, username, password — never stored)

**Push flow**:
1. Click **🔍 Dry Run** → shows preview of `OpenstackCreds`, `NetworkMappings`, `VMwareCreds` to be created/updated (no writes)
2. Click **🚀 Push** → idempotent push of all three CRD types
   - `creds-<tenant-slug>` — OpenStack credentials (OpenstackCreds)
   - `netmap-<tenant-slug>` — Network mappings (NetworkMappings)
   - `vmware-<cid>` — VMware source credentials (VMwareCreds, optional)

**Idempotency**: Both dry-run and push check existing CRD names and skip any that already exist. Safe to re-run.

**CRD naming**: Slugified via `_k8s_name()` — lowercase alphanumeric + dashes, max 52 characters.

**Task log**: Shows push status, timestamps, and any errors per CRD. Can be cleared with `DELETE /vjailbreak-push-tasks` (does not touch vJailbreak).

---

## 13. Migration Summary & Tech Fix Time

### 13.1 Migration Summary Tab

**UI**: Source Analysis → 📊 Summary sub-tab

The Migration Summary provides a management-level view of total effort, downtime, and cost.

**Executive KPI strip**:

| Metric | Calculation |
|--------|-------------|
| Total VMs | Count of in-scope powered-on VMs |
| Total Data (TB) | `SUM(used_disk_gb) / 1024` |
| Est. Data-Copy Time | Derived from bandwidth model + per-VM time estimates |
| Est. Fix Time | From the tech fix time model (§13.2) |
| Est. Total Downtime | Warm: `cutover_hours` only · Cold: `total_hours + cutover_hours` |

**OS-family breakdown table**: Per-OS row showing VM count, data volume, copy time, fix time, total downtime.

**Per-cohort breakdown table**: Same columns grouped by cohort, with a totals row.

**Methodology accordion**: Explains the data-copy, fix-time, and downtime formulas in plain language for stakeholders.

**Per-day breakdown** (v1.44.0+): Daily throughput table showing VMs migrated/day, data transferred/day, cumulative progress, and throughput cap applied.

**Export**:
```bash
GET /api/migration/projects/{id}/migration-summary.xlsx
GET /api/migration/projects/{id}/migration-summary.pdf
```

---

### 13.2 Fix Time Model

The tech fix time model estimates post-migration engineering effort — the time between "VM powered on" and "VM fully validated by the application team". It uses a two-layer model:

**Layer 1 — VM fix score** (sum of weighted risk factors):

| Factor | Default weight (minutes) |
|--------|:-:|
| Windows OS | 20 |
| Extra data volume (per disk) | 15 |
| Extra NIC (per NIC) | 10 |
| Cold migration | 15 |
| Yellow risk (score > 50) | 15 |
| Red risk (score > 75) | 25 |
| Has snapshots | 10 |
| Cross-tenant dependency | 15 |
| Unknown / other OS | 20 |
| Cutover window (always added) | 30 |

**Layer 2 — Expected value** (raw score × OS-family fix rate):

| OS family | Default fix rate | Meaning |
|-----------|:-:|---------|
| Windows | 50% | 50% of Windows VMs need any manual intervention |
| Linux | 20% | Most Linux VMs boot clean |
| Other / Unknown | 40% | Conservative estimate |

**Total expected fix time per VM** = `raw_fix_score × fix_rate`

**Total project fix time** = `SUM(expected_fix_time)` over all in-scope VMs

---

### 13.3 Fix Settings Editor

**UI**: Source Analysis → 📊 Summary → Settings editor

All weights and fix rates are tunable per project (stored in `migration_fix_settings`):

1. Click **⚙️ Fix Settings**
2. Adjust weight sliders for each risk factor
3. Adjust OS fix rate percentages (or set a global override)
4. Click **💾 Save & Recalculate** → immediately updates the Summary tab

**API**:
```bash
GET  /api/migration/projects/{id}/fix-settings
PATCH /api/migration/projects/{id}/fix-settings
Body: {
  "weight_windows_os": 25,
  "fix_rate_windows": 0.45,
  "fix_rate_linux": 0.15
}
```

---

### 13.4 Per-VM Fix Override

For VMs where you have domain-specific knowledge, set a manual fix time that overrides the model entirely.

**UI**: Expand VM row → ⏱ Fix Time Override card → enter minutes → Save. The VM table badge updates immediately.

**API**: `PATCH /api/migration/projects/{id}/vms/{vm_id}/fix-override` with `{"fix_minutes": 90}`

Clear the override: `PATCH` with `{"fix_minutes": null}`

---

## 14. Exports & Reports

Complete list of all export endpoints:

| Output | Endpoint | Notes |
|--------|----------|-------|
| Migration plan (JSON) | `GET /export-plan` | Full nested cohort/tenant/VM/schedule structure |
| Migration plan (CSV) | `GET /export-plan?format=csv` | Flat VM-level rows |
| Migration report (Excel, 4 sheets) | `GET /export-report.xlsx` | VMs · Tenants · Daily Schedule · Summary |
| Migration report (PDF) | `GET /export-report.pdf` | Landscape A4, colour-coded |
| Migration summary (Excel) | `GET /export-summary.xlsx` | Executive + OS/cohort breakdown |
| Migration summary (PDF) | `GET /export-summary.pdf` | Management-level |
| Migration summary per-day (Excel) | `GET /export-summary-daily.xlsx` | Daily throughput breakdown |
| PCD readiness / gap report (Excel) | `GET /export-gaps-report.xlsx` | 3 sheets: Executive · Action Items · All Gaps |
| PCD readiness / gap report (PDF) | `GET /export-gaps-report.pdf` | Landscape A4 severity-coloured |
| vJailbreak bundle (JSON) | `GET /export-vjailbreak-bundle` | Per-tenant credentials + network UUIDs + wave sequence |
| vJailbreak bundle (cohort-scoped) | `GET /cohorts/{cid}/export-vjailbreak-bundle` | Same, filtered to one cohort |
| Tenant handoff sheet (PDF) | `GET /export-handoff-sheet.pdf` | Customer-facing A4 per-tenant credential sheet |

**Authentication**: All export endpoints require `Authorization: Bearer <token>`. The UI uses `downloadAuthBlob()` (fetch + blob URL) — direct `<a href>` navigation is not used as it would omit the auth header.

---

## 15. Troubleshooting

### Assessment returns empty risk scores

**Cause**: Assessment was not run after upload, or it was reset without re-running.  
**Fix**: Go to Source Analysis → ▶️ Run Assessment.

### Tenant detection assigns all VMs to "Unassigned"

**Cause**: The configured detection methods do not match the RVTools data structure (e.g., folder paths are not hierarchical in this environment).  
**Fix**:
1. Check the Risk Config sub-tab → detection_config methods
2. Try enabling `cluster` as the first method (good fallback for non-vCD environments)
3. Check `folder_path` in the VM table — if all paths are shallow (fewer than 2 segments), reduce `depth` to 1

### Disk capacity and network columns show 0 / empty

**Cause**: The vDisk or vNIC sheets were not included in the RVTools export, or the column headers use an unrecognised variant.  
**Fix**:
1. Re-export RVTools with all sheets enabled
2. Check that the `vDisk` sheet has columns matching any of: `Capacity MB`, `Size MB`, `Disk Size MB`
3. Re-upload

### PCD gap analysis returns HTTP 500

**Cause**: PCD connection settings are missing or incorrect.  
**Fix**:
1. Go to PCD Readiness → Settings panel
2. Verify Auth URL is reachable from the API container (`docker exec pf9_api curl <auth_url>`)
3. Verify username/password are correct

### Provisioning tasks fail with "domain already exists"

**Cause**: The domain was created in a previous run that was subsequently rolled back partially.  
**Fix**: Run dry-run first (`POST /prepare/dry-run`). Tasks that would fail are classified as `would_skip_existing`. If the domain truly exists but the task is set to `create`, mark the task as skipped manually or use the rollback endpoint to reset it.

### Export-plan returns empty daily schedule

**Cause**: No VMs have been assessed (no `migration_mode` set) or all tenants are excluded.  
**Fix**: Run assessment (`POST /assess`) and verify at least one tenant is in-scope.

### vJailbreak push fails with "unauthorized"

**Cause**: The Bearer token stored in `migration_projects.vjb_bearer_token` has expired or has insufficient permissions.  
**Fix**: Generate a new service account token in the vJailbreak Kubernetes cluster and update it via `PATCH /projects/{id}/vjailbreak-push-settings`.

### Wave advance returns HTTP 409

**Cause**: The wave's `approval_status` is not `approved`.  
**Fix**: Request approval via `POST /waves/{wid}/request-approval`, then have an admin approve via `POST /waves/{wid}/approval`.

### Node sizing shows dramatically different results after re-upload

**Cause**: Performance data coverage changed (e.g., vCPU sheet now missing → falls back to allocation ÷ overcommit basis).  
**Fix**: Check the sizing basis badge in the Capacity tab. If it shows amber ("Based on vCPU allocation ÷ overcommit"), your RVtools export is missing the `vCPU` sheet. Re-export with the vCPU sheet included.

---

## 16. API Quick Reference

All endpoints are under the `/api/migration` prefix and require `Authorization: Bearer <token>`.

### Project management

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| POST | `/projects` | write | Create project |
| GET | `/projects` | read | List all projects |
| GET | `/projects/{id}` | read | Get project detail |
| PATCH | `/projects/{id}` | write | Update settings / schedule |
| DELETE | `/projects/{id}` | admin | Delete project (cascade) |
| POST | `/projects/{id}/archive` | admin | Archive + purge |
| POST | `/projects/{id}/approve` | admin | Approve project (gate) |
| POST | `/projects/{id}/upload` | write | Upload RVTools XLSX |
| DELETE | `/projects/{id}/rvtools` | write | Clear all VM/tenant data |
| POST | `/projects/{id}/assess` | write | Run risk + mode scoring |
| POST | `/projects/{id}/reset-assessment` | write | Clear computed results |

### VM management

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET | `/projects/{id}/vms` | read | List VMs (filters, sort, page) |
| GET | `/projects/{id}/vms/{vm_name}/details` | read | Disk + NIC detail |
| PATCH | `/projects/{id}/vms/{vm_id}/status` | write | Update migration status |
| PATCH | `/projects/{id}/vms/bulk-status` | write | Bulk status update |
| PATCH | `/projects/{id}/vms/{vm_id}/mode-override` | write | Force warm/cold/auto |
| PATCH | `/projects/{id}/vms/{vm_id}/fix-override` | write | Set manual fix time |

### Tenant management

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET | `/projects/{id}/tenants` | read | List detected tenants |
| PATCH | `/projects/{id}/tenants/{tid}` | write | Update tenant mapping / scope / priority |
| PATCH | `/projects/{id}/tenants/bulk-scope` | write | Bulk include/exclude |
| POST | `/projects/{id}/tenants/bulk-replace-target` | write | Find-and-replace target names |
| POST | `/projects/{id}/tenants/confirm-all` | write | Confirm all target mappings |
| GET/POST/DELETE | `/projects/{id}/tenant-filters` | write | Auto-exclude patterns |

### Capacity planning

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET | `/overcommit-profiles` | read | List overcommit presets |
| PATCH | `/projects/{id}/overcommit-profile` | write | Set active profile |
| GET | `/projects/{id}/quota-requirements` | read | Per-tenant quota computation |
| GET/POST/DELETE | `/projects/{id}/node-profiles` | write | Manage node profiles |
| GET/PUT | `/projects/{id}/node-inventory` | write | Current PCD inventory |
| GET | `/projects/{id}/node-sizing` | read | HA-aware sizing result |
| GET | `/projects/{id}/pcd-live-inventory` | read | Live PCD cluster capacity |
| GET | `/projects/{id}/pcd-auto-detect-profile` | read | Auto-detect dominant node type |

### PCD readiness

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| PATCH | `/projects/{id}/pcd-settings` | write | Store PCD connection |
| POST | `/projects/{id}/pcd-gap-analysis` | write | Run gap analysis |
| GET | `/projects/{id}/pcd-gaps` | read | List gaps |
| PATCH | `/projects/{id}/pcd-gaps/{gid}/resolve` | write | Mark gap resolved |

### Network map

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET | `/projects/{id}/network-mappings` | read | List mappings |
| PATCH | `/network-mappings/{id}` | write | Update mapping + subnet details |
| POST | `/network-mappings/bulk-replace` | write | Find-and-replace target names |
| POST | `/network-mappings/confirm-all` | write | Confirm all mappings |
| POST | `/network-mappings/confirm-subnets` | write | Confirm rows with CIDR |
| GET | `/network-mappings/export-template` | read | XLSX template for bulk subnet input |
| POST | `/network-mappings/import-template` | write | Bulk import from XLSX |

### Cohort planning

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET/POST | `/projects/{id}/cohorts` | write | List / create cohorts |
| PATCH/DELETE | `/projects/{id}/cohorts/{cid}` | write | Update / delete cohort |
| POST | `/projects/{id}/cohorts/{cid}/assign-tenants` | write | Assign tenants to cohort |
| GET | `/projects/{id}/cohorts/{cid}/summary` | read | Cohort rollup stats |
| GET | `/projects/{id}/tenant-ease-scores` | read | Per-tenant ease score breakdown |
| POST | `/projects/{id}/cohorts/auto-assign` | write | Auto-assign with strategy + guardrails |

### Wave planning

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET/POST | `/projects/{id}/waves` | write | List / create waves |
| PATCH/DELETE | `/projects/{id}/waves/{wid}` | write | Update / delete wave |
| POST | `/projects/{id}/waves/auto-build` | write | Auto-build with strategy |
| POST | `/projects/{id}/waves/{wid}/advance` | write | Advance wave lifecycle status |
| GET/POST | `/projects/{id}/waves/{wid}/preflights` | write | Pre-flight checklist |
| GET | `/projects/{id}/waves/{wid}/approval` | read | Wave approval status |
| POST | `/projects/{id}/waves/{wid}/approval` | admin | Approve/reject wave |
| POST | `/projects/{id}/waves/{wid}/request-approval` | write | Request approval |
| GET | `/projects/{id}/migration-funnel` | read | VM migration funnel rollup |

### Dependencies & maintenance

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET/POST/DELETE | `/projects/{id}/vm-dependencies` | write | VM dependency management |
| POST | `/projects/{id}/vm-dependencies/auto-import` | write | Auto-detect dependencies |
| DELETE | `/projects/{id}/vm-dependencies/auto-imported` | write | Clear auto-imported |
| GET/POST/PATCH/DELETE | `/projects/{id}/maintenance-windows` | write | Maintenance window CRUD |
| GET | `/projects/{id}/maintenance-windows/preview` | read | Preview next N window slots |

### Data Enrichment

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET/PATCH | `/projects/{id}/flavor-staging` | write | Flavor staging management |
| POST | `/projects/{id}/flavor-staging/refresh` | write | Re-detect from gaps |
| GET/PATCH | `/projects/{id}/image-requirements` | write | Image checklist management |
| POST | `/projects/{id}/image-requirements/refresh` | write | Re-detect from VMs |
| GET/POST/PATCH/DELETE | `/projects/{id}/tenant-users` | write | User definitions |
| POST | `/projects/{id}/tenant-users/seed-service-accounts` | write | Auto-generate service accounts |
| POST | `/projects/{id}/tenant-users/seed-tenant-owners` | write | Bulk-seed owner accounts |
| POST | `/projects/{id}/tenant-users/confirm-all` | write | Confirm all user rows |
| POST | `/projects/{id}/tenant-users/bulk-replace` | write | Find-and-replace on users |
| POST | `/projects/{id}/tenant-users/bulk-action` | write | Mass confirm/set_role/delete |

### PCD Auto-Provisioning

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET | `/projects/{id}/prep-readiness` | read | Check data enrichment completeness |
| POST | `/projects/{id}/prepare` | write | Generate prep tasks |
| GET | `/projects/{id}/prep-tasks` | read | List all tasks with status |
| POST | `/projects/{id}/prepare/run` | write | Execute all approved tasks |
| POST | `/projects/{id}/prepare/dry-run` | write | Simulate without writes |
| POST | `/projects/{id}/prep-tasks/{id}/execute` | write | Execute one task |
| POST | `/projects/{id}/prep-tasks/{id}/rollback` | write | Undo one completed task |
| GET | `/projects/{id}/prep-summary` | read | Per-task-type status counts |
| GET | `/projects/{id}/prep-approval` | read | Approval status + history |
| POST | `/projects/{id}/prep-approval` | admin | Approve/reject provisioning |
| GET | `/projects/{id}/prep-audit` | read | Approval + activity + execution history |

### vJailbreak Handoff

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET | `/projects/{id}/export-vjailbreak-bundle` | write | Credential bundle (JSON) |
| GET | `/projects/{id}/cohorts/{cid}/export-vjailbreak-bundle` | write | Cohort-scoped bundle |
| GET | `/projects/{id}/export-handoff-sheet.pdf` | write | Tenant handoff PDF |
| GET/PATCH | `/projects/{id}/vjailbreak-push-settings` | write | vJailbreak K8s connection |
| POST | `/projects/{id}/vjailbreak-push/dry-run` | write | Preview CRD push |
| POST | `/projects/{id}/vjailbreak-push` | write | Push CRDs to vJailbreak |
| GET/DELETE | `/projects/{id}/vjailbreak-push-tasks` | write | Push task log |

### Migration Summary & Fix Time

| Method | Path | Permission | Description |
|--------|------|:-:|-------------|
| GET | `/projects/{id}/migration-summary` | read | Full summary with OS/cohort breakdown |
| GET/PATCH | `/projects/{id}/fix-settings` | write | Fix time weight sliders |

---

## 17. Database Schema Reference

Core migration tables (all created by `db/migrate_00_migration_planner.sql` and subsequent migration files):

| Table | Description |
|-------|-------------|
| `migration_projects` | Top-level project container; all settings, lifecycle, PCD connection |
| `migration_risk_config` | Per-project configurable risk rules (JSONB) |
| `migration_tenant_rules` | Tenant detection config (JSONB) and auto-exclude patterns |
| `migration_tenant_filters` | Auto-exclude regex/substring patterns |
| `migration_tenants` | Detected tenants; scope, target mapping, priority, cohort FK, readiness |
| `migration_vms` | Per-VM data from RVTools; risk score, mode, status, dependencies |
| `migration_vm_dependencies` | VM→VM dependency edges; `dep_source` (manual/auto_imported/rdm/shared_datastore), `confidence` |
| `migration_hosts` | Source ESXi host inventory from vHost sheet |
| `migration_clusters` | Source cluster inventory from vCluster sheet |
| `migration_networks` | Source network/portgroup inventory from vNetwork sheet |
| `migration_network_mappings` | Source portgroup → PCD network mapping; subnet details; `confirmed`, `subnet_details_confirmed` |
| `migration_cohorts` | Cohort definitions; `cohort_order`, `status`, `depends_on_cohort_id`, overrides |
| `migration_tenant_readiness` | Per-tenant auto-computed readiness checks |
| `migration_overcommit_profiles` | 3 built-in profiles (Aggressive/Balanced/Conservative) |
| `migration_pcd_node_profiles` | Physical node spec per project |
| `migration_pcd_node_inventory` | Current PCD node inventory per project |
| `migration_pcd_gaps` | Gap analysis results; `gap_type`, `severity`, `resolved` |
| `migration_flavor_staging` | Draft PCD flavors to create; `source_shape`, `target_flavor_name`, `skip`, `confirmed` |
| `migration_image_requirements` | Required OS images; `glance_image_id`, `confirmed` |
| `migration_tenant_users` | Per-tenant user definitions; `user_type`, `username`, `role`, `is_existing_user`, `temp_password` |
| `migration_waves` | Wave definitions; lifecycle status, approval status, cohort FK |
| `migration_wave_vms` | VM assignments to waves; `migration_order`, `wave_vm_status` |
| `migration_wave_preflights` | Pre-flight check results per wave |
| `migration_prep_tasks` | PCD provisioning task log; `task_type`, `status`, `resource_id`, `rollback_data` |
| `migration_prep_approvals` | Provisioning approval history |
| `migration_fix_settings` | Per-project tech fix time weights and OS fix rates |
| `maintenance_windows` | Recurring maintenance window schedules per project/cohort |
| `migration_vjailbreak_push_tasks` | vJailbreak CRD push task log |

**Relationships**:
```
migration_projects
  ├── migration_risk_config (1:1)
  ├── migration_tenant_rules (1:1)
  ├── migration_cohorts (1:many)
  │     └── migration_tenants (1:many per cohort)
  │           ├── migration_tenant_readiness (1:many per tenant)
  │           └── migration_tenant_users (1:many per tenant)
  ├── migration_tenants (1:many, cohort_id nullable)
  │     └── migration_vms (1:many per tenant)
  │           └── migration_vm_dependencies (1:many)
  ├── migration_waves (1:many)
  │     ├── migration_wave_vms (1:many)
  │     └── migration_wave_preflights (1:many)
  ├── migration_network_mappings (1:many)
  ├── migration_flavor_staging (1:many)
  ├── migration_image_requirements (1:many)
  ├── migration_pcd_gaps (1:many)
  ├── migration_prep_tasks (1:many)
  ├── migration_prep_approvals (1:many)
  ├── migration_fix_settings (1:1)
  └── maintenance_windows (1:many)
```

---

*End of Migration Planner Admin & Operator Guide*  
*For API details see [API_REFERENCE.md](API_REFERENCE.md). For deployment steps see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md).*
