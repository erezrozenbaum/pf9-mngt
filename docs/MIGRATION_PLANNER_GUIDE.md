# Migration Planner — Operator Guide

> **Version**: v1.36.0 | **Last Updated**: 2026-03-01
> Complete reference for the pf9-mngt Migration Planner — from RVTools ingestion through wave execution.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture & Data Model](#architecture--data-model)
3. [Phase 1 — Assessment & Risk Scoring](#phase-1--assessment--risk-scoring)
4. [Phase 2 — Scoping, Target Mapping & Capacity Planning](#phase-2--scoping-target-mapping--capacity-planning)
5. [Phase 2.10 — Pre-Wave Foundations](#phase-210--pre-wave-foundations)
6. [Phase 3.0 — Cohort Planning](#phase-30--cohort-planning)
7. [Phase 3 — Wave Planning](#phase-3--wave-planning)
8. [Phase 4A — PCD Data Enrichment](#phase-4a--pcd-data-enrichment)
9. [Phase 4B — PCD Auto-Provisioning](#phase-4b--pcd-auto-provisioning)
10. [End-to-End Workflow](#end-to-end-workflow)
11. [API Reference](#api-reference)
12. [Database Schema](#database-schema)
13. [Troubleshooting](#troubleshooting)

---

## Overview

The **Migration Planner** is an integrated module within pf9-mngt that guides operators through the complete VMware-to-PCD (Private Cloud Director) migration process. It covers:

| Phase | Capability | Status |
|-------|-----------|--------|
| 1 | RVTools ingestion, risk scoring, VM classification, daily wave scheduling, Excel/PDF export | ✅ Complete |
| 2 | Tenant scoping, source→PCD target mapping, overcommit profiles, quota modeling, node sizing, gap analysis | ✅ Complete |
| 2.10 | Migration cohorts, network mapping, VM dependency annotation, per-VM status & mode, tenant priority, readiness checks | ✅ Complete |
| 3.0 | Smart cohort planning — ease scores, auto-assign strategies, ramp profiles, What-If estimator | ✅ Complete |
| 3.0.1 | Cohort-aligned scheduling, two-model What-If, cohort execution plan, tenant reassignment | ✅ Complete |
| 3 | Wave planning — auto-build, lifecycle management, pre-flight checklists, VM funnel tracking | ✅ Complete |
| 4A | PCD Data Enrichment — subnet details, flavor staging, image checklist, user definitions | ✅ Complete |
| 4B | PCD Auto-Provisioning — domains, projects, quotas, networks, flavors, users, roles | ✅ Complete |
| 4C | vJailbreak Handoff — credential bundle + tenant handoff sheet | 🔲 Planned |
| 5 | vJailbreak integration & live execution | 🔲 Planned |
| 6 | Post-migration validation | 🔲 Planned |

---

## Architecture & Data Model

### Hierarchy

```
migration_projects
  └── migration_tenants          (scoped VMware tenants / vCenters)
        └── migration_vms        (individual VMs with risk, mode, status)
              └── migration_vm_dependencies  (ordering constraints)
  └── migration_cohorts          (ordered workstreams within a project)
        └── migration_waves      (execution batches within a cohort)
              └── migration_wave_vms        (VM → wave assignment)
              └── migration_wave_preflights (gate checks per wave)
  └── migration_network_mappings (VMware network → PCD network)
  └── migration_pcd_nodes        (target hardware node profiles)
  └── migration_pcd_gaps         (gap analysis findings)
```

### Key Concepts

| Term | Meaning |
|------|---------|
| **Project** | Top-level container for a migration engagement. Has schedule parameters (duration days, working hours, VMs/day, agent slots). |
| **Tenant** | A VMware organisational unit (vCenter folder / logical grouping). Has a source→PCD target mapping, priority, and readiness checks. |
| **VM** | Individual virtual machine. Has risk classification (GREEN/YELLOW/RED), migration mode (warm/cold), status, and optional mode override. |
| **Cohort** | An ordered workstream — a named batch of tenants migrated together. Large projects use multiple cohorts to reduce blast radius. |
| **Wave** | An ordered execution batch within a cohort. A wave contains VMs assigned to it and progresses through a status lifecycle. |
| **Pre-flight** | A gate check that must pass before a wave advances to `executing`. |

---

## Phase 1 — Assessment & Risk Scoring

### Uploading RVTools Data

1. Open a Migration Project.
2. Go to the **📋 Source VMs** sub-tab.
3. Click **Upload RVTools XLSX** and select the exported file.
4. The engine parses `vInfo`, `vPartition`, `vDisk`, `vNetwork`, `vCPU`, and `vMemory` sheets.

**What gets parsed:**

| RVTools Sheet | Data Extracted |
|--------------|---------------|
| `vInfo` | VM name, power state, OS, vCPU, RAM, datastore, cluster, host |
| `vPartition` | Per-disk actual used GB (more accurate than allocated) |
| `vDisk` | Disk count, total allocated GB |
| `vNetwork` | Network adapter names → source network inventory |
| `vCPU` / `vMemory` | Actual usage % for performance-based node sizing |

### Risk Classification

Each VM is scored GREEN / YELLOW / RED based on cumulative risk factors:

| Factor | Impact |
|--------|--------|
| OS unsupported on PCD | +RED |
| Large disk (>2 TB) | +YELLOW |
| Many vNICs (>4) | +YELLOW |
| High vCPU (>16) | +YELLOW |
| Compressed/deduplicated storage hints | +YELLOW |
| 100% disk utilisation | +YELLOW/RED |

**GREEN** = straightforward warm migration candidate.
**YELLOW** = needs review; likely warm-eligible with caveats.
**RED** = cold migration required or manual intervention needed.

### Migration Mode

| Mode | When Assigned | Description |
|------|--------------|-------------|
| `warm_migration` | Default for GREEN/YELLOW | Live sync with minimal cutover window (~minutes) |
| `cold_migration` | Default for RED, or operator override | VM powered off for migration. Longer downtime. |

Operators can **force-override** the mode on any VM using the 🔒 mode override toggle.

### Daily Wave Schedule

The engine calculates a day-by-day schedule from project parameters:

- `migration_duration_days` — total calendar days available
- `working_hours_per_day` — e.g. 8 (shift hours)
- `target_vms_per_day` — throughput cap
- `migration_agent_slots` — parallel agent connections

Formula:
```
warm_hours = (vm.in_use_gb × 1024 × 8) / (bandwidth_mbps × 3600) × 1.14 + (cutover_mins / 60)
cold_hours = vm.total_disk_gb × cold_multiplier
day_capacity = working_hours_per_day × migration_agent_slots
```

### Export

`GET /api/migration/projects/{id}/export-plan` returns the full plan as Excel (`.xlsx`) with tabs:
- **Project Summary** — parameters, totals, risk breakdown
- **Per-Tenant Assessment** — cohort-grouped tenant table with target mapping
- **Daily Schedule** — day-by-day VM list with cohort separator rows
- **All VMs** — full VM inventory with risk, mode, disk, OS

---

## Phase 2 — Scoping, Target Mapping & Capacity Planning

### Tenant Scoping

In the **👥 Tenants** sub-tab:
- Toggle each tenant **In Scope** / **Out of Scope**. Out-of-scope tenants are excluded from the schedule and plan.
- Set **Migration Priority** (integer, lower = earlier) to control cohort auto-assign ordering.
- Set **Target Domain Name**, **Target Project Name**, and optional descriptions — these map to PCD's domain/project structure.
- Use **🔍 Find & Replace** to bulk-rename target fields across all tenants at once. Affected rows revert to unconfirmed for review.
- Use **✓ Confirm All** to bulk-confirm mappings once reviewed.

### Network Mapping

In the **🔌 Network Map** sub-tab:
- One row is auto-seeded per distinct source VMware network (from `vNetwork` sheet).
- Fill in the **Target Network Name** (PCD network that VMs will attach to post-migration).
- Optionally set/correct the **VLAN ID** (editable inline with ✏️ button).
- Unconfirmed rows show ⚠️ — confirm each row after review, or use **✓ Confirm All**.
- Use **🔍 Find & Replace (Network Map)** to bulk-rename target network names.
- Stale mappings (networks that no longer appear in the latest RVTools upload) are automatically purged on re-import.

> **Readiness Impact**: The `network_mapped` readiness check is `pending` until all in-scope-tenant networks are confirmed. Waves cannot safely advance until this resolves.

### Overcommit Profiles

Three built-in profiles control how physical resources are calculated:

| Profile | vCPU Overcommit | RAM Overcommit | Use Case |
|---------|----------------|----------------|----------|
| `conservative` | 2:1 | 1.2:1 | Business-critical / production |
| `balanced` | 4:1 | 1.5:1 | Mixed workloads (default) |
| `aggressive` | 8:1 | 2:1 | Dev/test |

### Node Sizing (Performance-Based)

The node sizing engine uses **actual RVTools usage data** when `cpu_usage_percent` / `memory_usage_percent` columns have ≥50% coverage. Otherwise falls back to allocation ÷ overcommit → quota.

```
physical_vcpu_demand = sum(vm.vcpu × (vm.cpu_usage_pct / 100)) / overcommit_ratio
physical_ram_demand  = sum(vm.ram_gb × (vm.mem_usage_pct / 100)) / overcommit_ratio
nodes_required       = ceil(max(cpu_demand / node_vcpu, ram_demand / node_ram_gb) / 0.70)
```

> **70% utilisation cap IS the HA strategy.** No separate spare nodes are allocated on top. This mirrors VMware's N+1 headroom: keep the cluster at ≤70% so any single-node failure has headroom.

### PCD Gap Analysis

`POST /api/migration/projects/{id}/analyze-gaps` compares the computed requirements against a live or manually entered PCD inventory and produces gap findings:

| Severity | Meaning |
|----------|---------|
| `critical` | Blocker — migration cannot proceed without remediation |
| `warning` | Risk — likely to cause issues; should be resolved |
| `info` | Advisory — no immediate impact |

Gap categories: vCPU quota, RAM quota, Cinder disk quota, missing networks, missing flavors, domain/project not created.

Download the gap action report from `GET /api/migration/projects/{id}/gap-report` (Excel/PDF).

---

## Phase 2.10 — Pre-Wave Foundations

### Migration Cohorts

Cohorts let you split a large project into **independent ordered workstreams**. Each cohort:
- Has its own owner, schedule window, and dependency gate (cannot start until the previous cohort is complete)
- Contains a subset of tenants (and through them, their VMs)
- Has its own wave plan (Phase 3)

**If no cohorts are created**, all functionality continues to work with the full project treated as a single implicit cohort.

#### Creating Cohorts

In the **🗃️ Cohorts** sub-tab → **➕ New Cohort**. Set:
- Name, description, owner
- `order` (integer) — processing sequence; cohorts execute in ascending order
- `max_vms_per_day`, `working_hours_per_day` (override project-level if set)

#### Auto-Assigning Tenants to Cohorts

Click **🤖 Smart Auto-Assign** to open the auto-assign panel:

| Strategy | Logic |
|----------|-------|
| `easiest_first` | Lowest ease-score (simplest) tenants go into the earliest cohorts |
| `riskiest_last` | Highest-risk tenants pushed to later cohorts |
| `pilot_bulk` | First cohort = pilot (small/easy), remaining cohorts = bulk |
| `balanced_load` | Distribute to balance disk GB per cohort |
| `os_first` | Tenants with best OS support % go first |
| `by_priority` | Respects the `migration_priority` integer on each tenant |

**Guardrails** (all optional):
- `max_vms_per_cohort` — hard cap on VM count per cohort
- `max_disk_tb` — hard cap on total disk per cohort
- `max_avg_risk` — reject assignments above a risk threshold
- `min_os_support_pct` — require a minimum OS compatibility percentage

Always run **Preview** before **Apply** to review the diff table.

**Ramp Profile mode** — instead of a fixed number of cohorts, define named cohort "slots" each with their own VM cap:
- Presets: Pilot+Bulk, 3-Wave, 4-Wave, 5-Wave
- Custom cohort rows with editable names and VM caps

### VM Dependency Annotation

In the expanded VM row → **Dependencies** tab:
- Add `depends_on: [vm_b_id]` to mark that VM A cannot start until VM B is complete.
- Circular dependencies are rejected at the API level.
- The wave planner uses the dependency graph to prevent cross-wave violations.

### Per-VM Migration Status

VM status values (colour-coded in the VM table):

| Status | Colour | Meaning |
|--------|--------|---------|
| `not_started` | ⬜ Grey | Not yet assigned to a wave |
| `assigned` | 🔵 Blue | Assigned to a wave but not yet executing |
| `in_progress` | 🟡 Amber | Wave is actively executing this VM |
| `migrated` | 🟢 Green | Successfully migrated |
| `failed` | 🔴 Red | Migration attempt failed |
| `skipped` | ⬛ Dark | Deliberately excluded from all waves |

### Per-Tenant Readiness Checks

Five auto-derived checks appear on each tenant row:

| Check | Source | Passes When |
|-------|--------|------------|
| `target_mapped` | `migration_tenants` | `target_domain_name` is confirmed |
| `network_mapped` | `migration_network_mappings` | All networks for this tenant's VMs are confirmed |
| `quota_sufficient` | Gap analysis | No critical quota gaps for this tenant |
| `no_critical_gaps` | Gap analysis | No critical gaps of any kind |
| `vms_classified` | `migration_vms` | All VMs have a risk classification |

---

## Phase 3.0 — Cohort Planning

### Ease Score

Each tenant receives an **Ease Score** (0–100, lower = easier) composed of 8 dimensions:

| Dimension | Higher Score When |
|-----------|------------------|
| Total disk used | Large disk footprint |
| Average VM risk | More RED/YELLOW VMs |
| Unsupported OS % | Many non-supported guest OSes |
| VM count | Large number of VMs |
| Distinct networks | Many distinct source networks |
| Cross-tenant dependencies | VMs depend on VMs in other tenants |
| Cold VM ratio | High proportion of cold-only VMs |
| Unconfirmed mappings | Target names / networks not yet confirmed |

The score drives the auto-assign strategy logic and appears as a colour-coded badge in the Tenants tab (🟢 Easy / 🟡 Medium / 🔴 Hard).

### What-If Estimator

Two parallel models estimate migration duration:

**BW Days** (bandwidth/transfer model):
```
eff_mbps       = bandwidth_gbps × 1000 × 0.75
transfer_hours = (total_in_use_gb × 1024 × 8) / (eff_mbps × 3600) × 1.14
cutover_hours  = tenant_count × 0.25 / agent_slots
bw_days        = (transfer_hours + cutover_hours) / working_hours_per_day
```

**Sched. Days** (VM-slots model — mirrors the backend scheduler exactly):
```
sched_days = vm_count / effective_vms_per_day
```

A **deadline banner** compares both models against `migration_duration_days` and turns red if either exceeds the budget.

---

## Phase 3 — Wave Planning

### Concepts

A **wave** is an ordered, gate-controlled execution batch within a cohort. Waves have:
- A **type**: `regular`, `pilot`, or `cleanup`
- A **status lifecycle** with enforced transitions
- A set of assigned VMs (sourced from the cohort's tenant pool)
- A **pre-flight checklist** that gates advancement to `executing`

### Wave Status Lifecycle

```
planned
  ├── pre_checks_passed   ← all pre-flight checks passed
  │     ├── executing     ← wave actively running
  │     │     ├── validating   ← post-migration checks
  │     │     │     ├── complete  ✅
  │     │     │     └── failed    ❌
  │     │     └── failed    ❌
  │     ├── planned        ← rolled back
  │     └── cancelled      🚫
  └── cancelled            🚫

failed / cancelled → planned   ← reopen for retry
```

Transitions are enforced at the API level — you cannot skip steps.

### Auto-Building a Wave Plan

In the **🌊 Wave Planner** sub-tab → **🤖 Auto-Build Waves**:

#### Strategies

| Strategy | Logic |
|----------|-------|
| `pilot_first` | Wave 0 = N lowest-risk, smallest VMs (configurable count). Remaining VMs fill subsequent waves. Use this to validate the toolchain before committing bulk VMs. |
| `by_tenant` | One wave per tenant, sorted by `migration_priority`. Large tenants are split if they exceed the VM cap. |
| `by_risk` | Wave 1 = GREEN (low risk) → Wave 2 = YELLOW → Wave 3+ = RED. Fail fast on safe VMs before attempting risky ones. |
| `by_priority` | Fill waves in tenant priority order (lower integer = earlier). Same-priority tenants spread evenly. |
| `balanced` | Distribute VMs to minimise variance in total disk GB per wave — each wave takes roughly equal time. |

#### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Max VMs per wave | 30 | Hard cap on VMs per wave |
| Pilot VM count | 5 | (pilot_first only) number of VMs in Wave 0 |
| Wave name prefix | "Wave" | E.g. "Wave 1", "Wave 2" |
| Cohort filter | All | Scope auto-build to a specific cohort |

#### Cohort-aware building

When cohorts are defined and **All Cohorts** is selected, the engine builds waves **cohort-by-cohort** in `cohort_order` sequence:
- Each cohort gets its own pilot wave (named `🧪 <Cohort Name>`) plus as many regular waves as needed to fit within the Max VMs/wave cap (named `<Cohort Name> 1`, `<Cohort Name> 2`, …).
- Each wave is tagged with its `cohort_id` — waves from different cohorts never mix.
- VMs not assigned to any cohort are grouped last as "Unassigned".
- The preview table shows a **Cohort** column and a cohort count badge when multiple cohorts are present.

When a **specific cohort** is selected, only VMs/tenants in that cohort are included.

**Always run Preview first.** The preview table shows wave number, name, cohort, type, VM count, total disk GB, risk distribution, and tenant names — plus any warnings (e.g. cross-wave dependency violations).

Once satisfied, click **✅ Apply & Create Waves**.

### Managing Waves Manually

`POST /api/migration/projects/{id}/waves` — create a wave with:
```json
{
  "wave_number": 1,
  "name": "Wave 1 — Finance",
  "wave_type": "regular",
  "cohort_id": 3,
  "scheduled_start": "2026-03-15",
  "scheduled_end": "2026-03-17",
  "owner_name": "ops-team",
  "agent_slots_override": 4
}
```

### Assigning VMs to a Wave

`POST /api/migration/projects/{id}/waves/{wave_id}/assign-vms`:
```json
{
  "vm_ids": [101, 102, 103],
  "replace": false
}
```
- `replace: true` — remove all current assignments and replace with the given list
- Assigned VMs have their `migration_status` set to `assigned`

Remove a single VM: `DELETE /projects/{id}/waves/{wave_id}/vms/{vm_id}` — reverts VM status to `not_started` if not in any other wave.

### Pre-Flight Checklists

Each wave has 6 pre-flight checks seeded automatically on creation:

| Check | Severity | Description |
|-------|----------|-------------|
| `network_mapped` | blocker | All VM networks in this wave have confirmed PCD mappings |
| `target_project_set` | blocker | Target PCD project/domain is confirmed for all tenants |
| `vms_assessed` | warning | All VMs have risk classification and mode set |
| `no_critical_gaps` | blocker | No unresolved critical PCD capacity/quota gaps |
| `agent_reachable` | warning | Migration agent has connectivity to source and target |
| `snapshot_baseline` | info | Pre-migration snapshot taken for rollback |

**Severity meanings:**

| Severity | Effect |
|----------|--------|
| `blocker` | Failing check should prevent advancing to `executing` |
| `warning` | Should be resolved but operator can override |
| `info` | Best-practice advisory only |

Update a check via the UI (✅ Pass / ❌ Fail / ⏭️ Skip buttons) or:
```
PATCH /api/migration/projects/{id}/waves/{wave_id}/preflights/{check_name}
{"check_status": "pass", "notes": "Confirmed by network team 2026-03-14"}
```

### Advancing a Wave

Click the advance button on the wave card, or:
```
POST /api/migration/projects/{id}/waves/{wave_id}/advance
{"status": "executing", "notes": "All pre-checks passed, starting now"}
```

Timestamps `started_at` and `completed_at` are set automatically on `executing` and terminal states (`complete`, `failed`, `cancelled`).

### VM Migration Funnel

`GET /api/migration/projects/{id}/migration-funnel` returns a rollup:
```json
{
  "funnel": {
    "total": 420,
    "not_started": 285,
    "assigned": 60,
    "in_progress": 15,
    "migrated": 52,
    "failed": 4,
    "skipped": 4
  }
}
```

Displayed as a colour-coded progress bar at the top of the Wave Planner tab.

---

## Phase 4A — PCD Data Enrichment

> Prerequisite: Wave plan built and reviewed (Phase 3 complete).

Phase 4A collects the information that cannot be derived from RVTools — the actual PCD target configuration. All four items must be confirmed before Phase 4B can run.

| Sub-phase | What you configure | API |
|-----------|-------------------|-----|
| **4A.1 Subnet Details** | CIDR, gateway, DNS, DHCP pool start/end per confirmed network mapping | `PATCH /network-mappings/{id}`, `POST /network-mappings/confirm-all` |
| **4A.2 Flavor Staging** | Review de-duplicated (vCPU, RAM) shapes; rename, Find & Replace, confirm or skip | `GET/PATCH /flavor-staging`, `POST /flavor-staging/confirm-all` |
| **4A.3 Image Requirements** | One row per OS family; confirm after uploading to PCD Glance | `GET/PATCH /image-requirements`, `POST /image-requirements/confirm-all` |
| **4A.4 Tenant Users** | Define service accounts and owner accounts per tenant | `GET/POST/PATCH/DELETE /tenant-users` |

The **⚙️ Prepare PCD** tab gate (`GET /prep-readiness`) will show red ✗ for any unfinished item.

---

## Phase 4B — PCD Auto-Provisioning

> Prerequisite: All Phase 4A items confirmed.

### Workflow

1. Open the **⚙️ Prepare PCD** sub-tab in the Migration Planner.
2. Verify the Readiness grid shows all four cards green.
3. Click **🔄 Generate Plan** — calls `POST /prepare`, creates an ordered task list (~667 tasks for a typical 120-tenant project).
4. Review the task table. Tasks are ordered: `create_domain` → `create_project` → `set_quotas` → `create_network` → `create_subnet` → `create_flavor` → `create_user` → `assign_role`.
5. Click **▶ Run All** to execute all pending tasks in order, or use the per-row **▶** button to execute individually.
6. Failed tasks show an inline error — fix the root cause and re-run the individual task.
7. Use **↩ Rollback** on any `done` task to delete the PCD resource and reset to `pending`.
8. When all tasks are `done` or `skipped`, Phase 4B is complete — PCD UUIDs are written back to all source tables.

### Task Types

| Task Type | What it does | Writes back |
|-----------|-------------|-------------|
| `create_domain` | Creates a Keystone domain; skips if already exists | — |
| `create_project` | Creates a Keystone project under its domain | — |
| `set_quotas` | Applies Nova + Neutron + Cinder quotas (from overcommit profile) | — |
| `create_network` | Creates provider network (VLAN type) or tenant network | `migration_network_mappings.target_network_id` |
| `create_subnet` | Creates subnet with CIDR, gateway, DNS, DHCP pool | — |
| `create_flavor` | Creates Nova flavor; skips if already exists | `migration_flavor_staging.pcd_flavor_id` |
| `create_user` | Creates Keystone user with auto-generated temp password | `migration_tenant_users.pcd_user_id`, `.temp_password` |
| `assign_role` | Assigns role to user in project | — |

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/prep-readiness` | Pre-flight check — returns 4A gate status per item |
| `POST` | `/api/migration/projects/{id}/prepare` | Generate ordered task plan (clears previous pending/failed) |
| `GET` | `/api/migration/projects/{id}/prep-tasks` | List all tasks with status counts |
| `POST` | `/api/migration/projects/{id}/prep-tasks/{task_id}/execute` | Execute a single task |
| `POST` | `/api/migration/projects/{id}/prepare/run` | Run all pending/failed tasks in order |
| `POST` | `/api/migration/projects/{id}/prep-tasks/{task_id}/rollback` | Undo a completed task |
| `DELETE` | `/api/migration/projects/{id}/prep-tasks` | Clear all pending/failed tasks |

---

## End-to-End Workflow

```
1. CREATE PROJECT
   └── Set name, migration_duration_days, working_hours_per_day,
       target_vms_per_day, migration_agent_slots, bandwidth_gbps

2. UPLOAD RVTOOLS
   └── Source VMs tab → Upload XLSX
   └── VM inventory + risk scores auto-generated

3. SCOPE TENANTS (Phase 2)
   └── Tenants tab → mark in/out of scope
   └── Set target domain/project names
   └── Set migration_priority integers

4. MAP NETWORKS (Phase 2.10)
   └── Network Map tab → fill target_network_name + VLAN IDs
   └── Confirm all rows

5. TARGET MAPPING & CAPACITY (Phase 2)
   └── Tenants tab → confirm domain/project names
   └── Node Sizing tab → choose overcommit profile
   └── Run gap analysis → download gap report
   └── Resolve critical gaps before proceeding

6. PLAN COHORTS (Phase 3.0)
   └── Cohorts tab → create cohorts (or use auto-assign)
   └── Check Ease Scores; run Smart Auto-Assign
   └── Use What-If estimator to validate timeline vs deadline

7. BUILD WAVE PLAN (Phase 3)
   └── Wave Planner tab → Auto-Build Waves
   └── Choose strategy (pilot_first recommended for first engagement)
   └── Preview → review warnings → Apply
   └── Optionally adjust: move VMs between waves, add/remove waves

8. PRE-FLIGHT (Phase 3)
   └── For each wave: expand Checks panel
   └── Verify + mark each check pass/fail/skip
   └── All blockers must pass before advancing

9. PHASE 4A — PCD DATA ENRICHMENT
   └── Network Map tab → fill CIDR/gateway/DNS per row → Confirm Subnets
   └── Flavor Staging tab → review shapes → confirm or skip each
   └── Image Requirements tab → confirm after uploading to Glance
   └── Users tab → define service accounts + owner accounts per tenant

10. PHASE 4B — PCD AUTO-PROVISIONING
    └── Prepare PCD tab → verify readiness grid (all green)
    └── Generate Plan → review task list
    └── Run All → monitor progress, fix failures, re-run
    └── All tasks done/skipped → PCD is fully provisioned

11. EXECUTE WAVES (future Phase 5 — vJailbreak)
    └── Advance Wave 0 to executing (pilot)
    └── Validate pilot → advance to complete
    └── Proceed wave by wave through the plan

12. EXPORT REPORTS
    └── GET /projects/{id}/export-plan  (XLSX / PDF)
    └── GET /projects/{id}/gap-report   (XLSX / PDF)
```

---

## API Reference

### Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects` | List all projects |
| `POST` | `/api/migration/projects` | Create project |
| `GET` | `/api/migration/projects/{id}` | Get project |
| `PATCH` | `/api/migration/projects/{id}` | Update project parameters |
| `DELETE` | `/api/migration/projects/{id}` | Delete project |
| `POST` | `/api/migration/projects/{id}/rvtools` | Upload RVTools XLSX |
| `DELETE` | `/api/migration/projects/{id}/rvtools` | Clear all RVTools data |

### VMs & Tenants

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/vms` | List VMs (filterable) |
| `PATCH` | `/api/migration/projects/{id}/vms/{vm_id}` | Update VM (status, mode, override) |
| `POST` | `/api/migration/projects/{id}/vms/bulk-status` | Bulk update VM status |
| `GET` | `/api/migration/projects/{id}/tenants` | List tenants |
| `PATCH` | `/api/migration/projects/{id}/tenants/{t_id}` | Update tenant (scoping, target, priority) |
| `POST` | `/api/migration/projects/{id}/tenants/confirm-all` | Bulk confirm all tenant mappings |
| `POST` | `/api/migration/projects/{id}/tenants/bulk-replace-target` | Find & Replace tenant target fields |
| `GET` | `/api/migration/projects/{id}/tenant-ease-scores` | Ease scores with per-dimension breakdown |

### Network Mappings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/network-mappings` | List mappings |
| `PATCH` | `/api/migration/projects/{id}/network-mappings/{nm_id}` | Update mapping |
| `POST` | `/api/migration/projects/{id}/network-mappings/confirm-all` | Confirm all |
| `POST` | `/api/migration/projects/{id}/network-mappings/bulk-replace` | Find & Replace target names |

### Cohorts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/cohorts` | List cohorts |
| `POST` | `/api/migration/projects/{id}/cohorts` | Create cohort |
| `PATCH` | `/api/migration/projects/{id}/cohorts/{c_id}` | Update cohort |
| `DELETE` | `/api/migration/projects/{id}/cohorts/{c_id}` | Delete cohort |
| `POST` | `/api/migration/projects/{id}/cohorts/auto-assign` | Auto-assign tenants to cohorts |

### Capacity & Gaps

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/pcd-nodes` | List node profiles |
| `POST` | `/api/migration/projects/{id}/pcd-nodes` | Add node profile |
| `POST` | `/api/migration/projects/{id}/analyze-gaps` | Run gap analysis |
| `GET` | `/api/migration/projects/{id}/gap-report` | Download gap report (XLSX/PDF) |

### Waves

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/waves` | List waves (optional `?cohort_id=N`) |
| `POST` | `/api/migration/projects/{id}/waves` | Create wave manually |
| `PATCH` | `/api/migration/projects/{id}/waves/{wid}` | Update wave metadata |
| `DELETE` | `/api/migration/projects/{id}/waves/{wid}` | Delete wave (planned status only) |
| `POST` | `/api/migration/projects/{id}/waves/{wid}/assign-vms` | Assign VMs to wave |
| `DELETE` | `/api/migration/projects/{id}/waves/{wid}/vms/{vm_id}` | Remove VM from wave |
| `POST` | `/api/migration/projects/{id}/waves/{wid}/advance` | Advance wave lifecycle status |
| `POST` | `/api/migration/projects/{id}/auto-waves` | Auto-build wave plan |
| `GET` | `/api/migration/projects/{id}/waves/{wid}/preflights` | Get pre-flight checklist |
| `PATCH` | `/api/migration/projects/{id}/waves/{wid}/preflights/{check_name}` | Update a pre-flight check |
| `GET` | `/api/migration/projects/{id}/migration-funnel` | VM status rollup funnel |

### Phase 4A — Data Enrichment

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/network-mappings/export-template` | Download pre-filled XLSX template |
| `POST` | `/api/migration/projects/{id}/network-mappings/import-template` | Import filled template |
| `POST` | `/api/migration/projects/{id}/network-mappings/confirm-subnets` | Bulk-confirm all rows with CIDR |
| `GET` | `/api/migration/projects/{id}/flavor-staging` | List flavor staging rows |
| `PATCH` | `/api/migration/projects/{id}/flavor-staging/{id}` | Update flavor row |
| `POST` | `/api/migration/projects/{id}/flavor-staging/confirm-all` | Confirm all flavors |
| `POST` | `/api/migration/projects/{id}/flavor-staging/match-pcd` | Match shapes against live Nova |
| `GET` | `/api/migration/projects/{id}/image-requirements` | List image requirement rows |
| `PATCH` | `/api/migration/projects/{id}/image-requirements/{id}` | Confirm/update image row |
| `POST` | `/api/migration/projects/{id}/image-requirements/confirm-all` | Confirm all images |
| `GET` | `/api/migration/projects/{id}/tenant-users` | List tenant user definitions |
| `POST` | `/api/migration/projects/{id}/tenant-users` | Add user definition |
| `PATCH` | `/api/migration/projects/{id}/tenant-users/{id}` | Update user |
| `DELETE` | `/api/migration/projects/{id}/tenant-users/{id}` | Remove user |

### Phase 4B — PCD Auto-Provisioning

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/prep-readiness` | Pre-flight 4A gate check |
| `POST` | `/api/migration/projects/{id}/prepare` | Generate ordered task plan |
| `GET` | `/api/migration/projects/{id}/prep-tasks` | List tasks with status counts |
| `POST` | `/api/migration/projects/{id}/prep-tasks/{task_id}/execute` | Execute single task |
| `POST` | `/api/migration/projects/{id}/prepare/run` | Run all pending/failed tasks |
| `POST` | `/api/migration/projects/{id}/prep-tasks/{task_id}/rollback` | Roll back completed task |
| `DELETE` | `/api/migration/projects/{id}/prep-tasks` | Clear pending/failed tasks |

### Plan & Export

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/export-plan` | Export full migration plan (XLSX/PDF) |
| `GET` | `/api/migration/projects/{id}/export-plan?format=pdf` | PDF variant |

---

## Database Schema

### Core Tables

```sql
migration_projects       -- project-level parameters
migration_tenants        -- scoped VMware tenants + target mapping
migration_vms            -- VM inventory, risk, mode, status
migration_vm_dependencies -- ordering constraints (vm_id → depends_on_vm_id)
migration_network_mappings -- source network → PCD network + VLAN + confirmed flag
migration_pcd_nodes      -- target hardware node profiles
migration_pcd_gaps       -- gap analysis findings
migration_cohorts        -- ordered workstreams within a project
migration_waves          -- execution batches; status lifecycle
migration_wave_vms       -- VM ↔ wave assignment
migration_wave_preflights -- per-wave gate checks
migration_flavor_staging  -- de-duped (vCPU, RAM) shapes; confirm/skip before 4B
migration_image_requirements -- one row per OS family; Glance confirm gate
migration_tenant_users   -- service + owner accounts per tenant
migration_prep_tasks     -- Phase 4B task plan: ordered create/assign tasks with status & PCD resource IDs
```

### `migration_waves` columns (v1.34.0)

| Column | Type | Notes |
|--------|------|-------|
| `id` | bigserial PK | |
| `project_id` | bigint FK | → migration_projects |
| `cohort_id` | bigint FK | → migration_cohorts (nullable — project-scoped if null) |
| `wave_number` | integer | Ordering within the project |
| `name` | text | Display name |
| `wave_type` | text | `regular` / `pilot` / `cleanup` |
| `status` | text | `planned` / `pre_checks_passed` / `executing` / `validating` / `complete` / `failed` / `cancelled` |
| `agent_slots_override` | integer | Override project-level agent slots for this wave |
| `scheduled_start` | date | Planned start date |
| `scheduled_end` | date | Planned end date |
| `owner_name` | text | Wave owner / responsible engineer |
| `notes` | text | Free-form notes |
| `started_at` | timestamptz | Set when status → `executing` |
| `completed_at` | timestamptz | Set on `complete` / `failed` / `cancelled` |

### `migration_wave_preflights` columns

| Column | Type | Notes |
|--------|------|-------|
| `id` | bigserial PK | |
| `wave_id` | bigint FK | → migration_waves |
| `check_name` | text | Unique check key (e.g. `network_mapped`) |
| `check_label` | text | Human-readable label |
| `check_status` | text | `pending` / `pass` / `fail` / `skipped` / `na` |
| `severity` | text | `blocker` / `warning` / `info` |
| `notes` | text | Operator notes |
| `checked_at` | timestamptz | When last updated |
| `checked_by` | text | Who updated it |

---

## Troubleshooting

### "Readiness check `network_mapped` stuck at pending"

All source networks for the tenant's VMs must have a confirmed mapping row in `migration_network_mappings`. Go to **🔌 Network Map**, find rows with ⚠️ status, fill in the target name, and click ✓ Confirm.

### "Wave won't advance to `executing`"

Check the pre-flight checklist. All `blocker`-severity checks must be in `pass` status before the API will accept a status advance to `executing`. Use the Checks panel to identify failing blockers.

### "Auto-build produced unexpected wave assignments"

Run with `dry_run: true` first and inspect the preview table. Common causes:
- Many VMs have `migration_status = migrated` or `skipped` — they are excluded from auto-build automatically.
- Cross-wave dependency warnings appear if VM A's dependency VM B is placed in a later wave. Review and manually move VMs if needed.
- `max_vms_per_wave` too low for the `by_tenant` strategy — large tenants get split across multiple waves.

### "DELETE wave returns 400"

Waves can only be deleted when their status is `planned`. Advance the wave to `cancelled` first, then delete.

### "Missing `in_use_gb` values on VMs"

This means the `vPartition` sheet was absent or empty in the uploaded RVTools file. The engine falls back to `total_disk_gb × 0.6` as an estimate. Re-export RVTools with the vPartition sheet included for accurate values.

### Re-uploading RVTools after creating waves

`DELETE /projects/{id}/rvtools` (Clear RVTools Data) will also remove all network mappings, cohorts, waves, and wave VM assignments — the entire planning state is reset. Export your current plan first if you need a record.

---

*For architecture decisions, phase history, and the full engineering rationale, see [MIGRATION_PLANNER_PHASES.md](../MIGRATION_PLANNER_PHASES.md).*
*For deployment and upgrade steps, see [ADMIN_GUIDE.md](ADMIN_GUIDE.md) and [../deployment.ps1](../deployment.ps1).*
