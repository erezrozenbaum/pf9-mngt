# Migration Planner — Operator Guide

> **Version**: v1.42.0 | **Last Updated**: 2026-03-05
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
10. [vJailbreak Handoff Exports](#vjailbreak-handoff-exports)
11. [Phase 5.0 — Migration Summary & Fix Time](#phase-50--migration-summary--fix-time)
12. [End-to-End Workflow](#end-to-end-workflow)
13. [API Reference](#api-reference)
14. [Database Schema](#database-schema)
15. [Troubleshooting](#troubleshooting)

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
| 4B.1 | Phase 4B Polish — run confirmation modal, execution summary panel, completion notification | ✅ Complete |
| 4B.2 | Phase 4B Approval Workflow (2-step gate), Dry Run simulation, Audit Log | ✅ Complete |
| 4C | vJailbreak Handoff — credential bundle + tenant handoff sheet | ✅ Complete | v1.37.0 |
| 5.0 | Tech Fix Time — per-VM fix model, Migration Summary tab, fix override UI | ✅ Complete | v1.42.0 |
| 5+ | vJailbreak agent integration — status probe + wave execution endpoint | ✅ Partial (stub) | v1.45.0 |
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

The engine calculates a day-by-day schedule from project parameters using a **shared-pipe throughput model** (v1.44.0+):

#### Throughput model

```
effective_gbph  = (bottleneck_mbps / 8) × 3600 / 1024 × AVG_BW_EFFICIENCY
max_gb_per_day  = effective_gbph × working_hours_per_day
```

Where:
- `bottleneck_mbps` — resolved by `compute_bandwidth_model()` as the minimum of source NIC, WAN link, agent ingest, and PCD storage write speeds.
- `AVG_BW_EFFICIENCY = 0.55` — realistic utilisation factor accounting for TCP slow-start, I/O burst gaps, and multi-agent coordination overhead.
- At 4 000 Mbps bottleneck and an 8-hour working day, `max_gb_per_day ≈ 7 742 GB` (~7.6 TB/day).

#### Day packing

VMs are added to the current day until `day_transfer_gb + vm_transfer_gb > max_gb_per_day`, then the day is closed and a new one opens.

`vm_transfer_gb` is:
- **warm migration** → `vm.in_use_gb` (only used blocks are transferred)
- **cold migration** → `vm.total_disk_gb` (full provisioned disk)

#### Wall-clock time

```
wall_clock_hours = day_transfer_gb / effective_gbph
```

This is the calendar time required to drain the day's entire data payload through the bottleneck pipe at the modelled efficiency. When `wall_clock_hours > working_hours_per_day` the day entry is flagged `over_capacity: true` and highlighted in the UI with a ⚠️ indicator. This can occur when a single VM's data payload exceeds one day's throughput capacity (the VM is never split across days).

#### Agent time vs wall-clock time

| Metric | Formula | Meaning |
|--------|---------|---------|
| `total_agent_hours` | Σ per-VM agent time | Total agent-slot hours across all VMs (parallelism increases throughput) |
| `wall_clock_hours` | `day_transfer_gb / effective_gbph` | Actual elapsed time for the day (pipe is the constraint) |

#### Legacy parameters (still configurable, no longer the primary constraint)

- `migration_duration_days` — maximum calendar days; plan stops after this
- `working_hours_per_day` — shift length used in throughput and wall-clock calculations
- `target_vms_per_day` — optional VM-count soft cap per day
- `migration_agent_slots` — parallel agent connections (affects per-VM time, not the GB/day ceiling)


### Export

`GET /api/migration/projects/{id}/export-plan` returns the full plan as Excel (`.xlsx`) with tabs:
- **Project Summary** — parameters, totals, risk breakdown
- **Per-Tenant Assessment** — cohort-grouped tenant table with target mapping
- **Daily Schedule** — day-by-day VM list with cohort separator rows
- **All VMs** — full VM inventory with risk, mode, disk, OS, and VMware cluster name

---

## Phase 2 — Scoping, Target Mapping & Capacity Planning

### Tenant Scoping

In the **👥 Tenants** sub-tab:
- Toggle each tenant **In Scope** / **Out of Scope**. Out-of-scope tenants are excluded from the schedule and plan.
- The **Clusters** column shows the VMware clusters that host that tenant's VMs (e.g. `Cluster-Prod`, `Cluster-DR`). Use the **All Clusters** filter dropdown to scope the view to a single vCenter cluster.
- Set **Migration Priority** (integer, lower = earlier) to control cohort auto-assign ordering.
- Set **Target Domain Name**, **Target Project Name**, and optional descriptions — these map to PCD's domain/project structure.
- Use **🔍 Find & Replace** to bulk-rename target fields across all tenants at once. Affected rows revert to unconfirmed for review.
- Use **✓ Confirm All** to bulk-confirm mappings once reviewed.

### Cluster-Level Scoping

In addition to scoping individual tenants, you can **exclude an entire VMware cluster** from the migration plan:
- In the Tenants tab, each cluster pill in the **Clusters** column is an interactive toggle button.
- **Click a blue pill** to exclude that cluster — the pill turns red with a strikethrough and a `⊘` prefix, and all VMs on that cluster are immediately omitted from wave calculations.
- **Click the red pill** to re-include the cluster.
- A `⊘` badge also appears in the **Cluster** column of the VMs tab for any VM whose cluster is excluded.
- Exclusion is persisted in `migration_clusters.include_in_plan` — it survives page refresh and container restarts.

> **vSphere environments**: excluding a cluster **automatically cascades** to all tenants whose `org_vdc` matches the cluster name (in vSphere, `org_vdc` is set to the cluster name during detection). This means the Networks tab and Cohorts auto-assignment will **immediately hide those tenants** as soon as the cluster is excluded — no separate tenant-level action needed. Re-including the cluster reverses the cascade only for tenants that were automatically excluded by it (user-set exclusions are preserved).
>
> **vCD environments**: tenant-level `include_in_plan` is controlled directly from the tenant row (vCD tenants already have explicit OrgVDC values). Cluster exclusion cascade does not apply.

### Empty Tenant Creation (vSphere)

For vSphere environments you can **pre-create an empty tenant** before moving VMs into it:

1. In the **🏢 Tenants** sub-tab, click **+ Add Tenant Rule**.
2. Enter a **Tenant Name** — this is the only required field.
3. Detection Method + Pattern are optional. Leave them blank to create an empty shell; fill them in if you want Re-run Detection to automatically assign matching VMs to this tenant in the future.
4. Click **Add**.

The tenant is created with `vm_count = 0` and `detection_method = manual`. You can then manually reassign VMs to it from the VMs tab.

### Unassigned VM Group

If any VMs have no detected tenant after detection runs, a synthetic **⚠️ (Unassigned)** row appears at the top of the Tenants tab (amber background). It shows the VM count and cluster pills for those VMs. You can:
- **Exclude the cluster** directly from the Unassigned row without re-running detection.
- **Manually assign** the VMs to a tenant (see below).

### Manual VM Reassignment

If the auto-detected tenant grouping is wrong, or you need to split a detected tenant across two logical tenants:

1. Switch to the **🖥️ VMs** sub-tab.
2. **Check the boxes** on the rows you want to move. A select-all checkbox is in the table header. Selected rows highlight blue.
3. Click **↪ Move to Tenant…** in the toolbar that appears above the table.
4. In the modal, choose the destination from the dropdown:
   - An **existing tenant** (it will receive the VMs and its vm_count will be recalculated).
   - **— Unassign —** to clear tenant assignment (moves the VMs to the Unassigned group).
   - **+ Create new tenant…** to provision a brand-new tenant row — type the new name in the text field that appears.
5. Click **Move VMs**.

**What happens under the hood:**
- The selected VMs get `manually_assigned = true` in the database.
- Re-running detection (via **Re-run Detection** button) will **skip manually-assigned VMs** — they will never be overwritten by auto-detection.
- VMs that were manually assigned show a 🔒 *manual* badge in the Tenant cell on the VMs tab.
- `vm_count` is recalculated on both the source tenant(s) and the target tenant atomically.
- To clear the manual lock and allow re-detection to reassign a VM, reassign it back to its correct tenant or unassign it and re-run detection.

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

> **Rebuilding cohorts from scratch?** If you ran auto-assign before finalising your exclusion list, stale assignments from excluded tenants exist in the database. Use:
> ```
> DELETE /api/migration/projects/{id}/cohorts
> ```
> This wipes all cohort groups and clears every tenant's `cohort_id` (including stale excluded-tenant rows). Then re-run auto-assign — results will reflect only in-scope tenants.

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

> **Rebuilding waves from scratch?** If cohorts or exclusions changed after waves were built, reset with:
> ```
> DELETE /api/migration/projects/{id}/waves
> ```
> This deletes all waves, removes all wave-VM assignments, and resets `migration_status` back to `not_started` for assigned VMs. Then re-run auto-build. Recommended sequence after changing exclusions:
> 1. `DELETE /cohorts` — wipe all cohort groups
> 2. `DELETE /waves` — wipe all wave groups
> 3. `POST /cohorts/auto-assign` — rebuild cohorts
> 4. `POST /auto-waves` — rebuild waves

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
| **4A.4 Tenant Users** | Define service accounts and owner accounts per tenant; seed all-tenant owner accounts in bulk, bulk find-and-replace fields, confirm & bulk-action | `GET/POST/PATCH/DELETE /tenant-users`, `POST /tenant-users/seed-tenant-owners`, `POST /tenant-users/bulk-replace`, `POST /tenant-users/confirm-all`, `POST /tenant-users/bulk-action` |

The **⚙️ Prepare PCD** tab gate (`GET /prep-readiness`) will show red ✗ for any unfinished item.

---

## Phase 4B — PCD Auto-Provisioning

> Prerequisite: All Phase 4A items confirmed.

### Workflow

1. Open the **⚙️ Prepare PCD** sub-tab in the Migration Planner.
2. Verify the Readiness grid shows all four cards green.
3. Click **🔄 Generate Plan** — calls `POST /prepare`, creates an ordered task list and sets plan status to `pending_approval`. A `prep_approval_requested` notification is fired to subscribed admins.
4. Review the task table (ordered: `create_domain` → `create_project` → `set_quotas` → `create_network` → `create_subnet` → `create_flavor` → `create_user` → `assign_role`).
5. *(Optional)* Click **🧪 Dry Run** — simulates execution against a live PCD without writing anything. Review the `would_create` / `would_skip_existing` / `would_execute` breakdown per task type.
6. An **admin** (requires `migration:admin` permission) approves or rejects the plan using the inline approval banner or `POST /prep-approval`. The person who generated the plan cannot approve their own plan (separation of duties).
7. Once the banner turns green (approved), **▶ Run All** becomes available. Click it to open the confirmation modal showing resource counts, then confirm to execute all pending tasks in order.
8. Failed tasks show an inline error — fix the root cause and use the per-row **▶** button to re-run the individual task.
9. Use **↩ Rollback** on any `done` task to delete the PCD resource and reset it to `pending`.
10. Use **📋 Audit Log** to review the full approval history, activity log, and execution history.
11. When all tasks are `done` or `skipped`, Phase 4B is complete — PCD UUIDs are written back to all source tables.

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
|--------|----------|--------------|
| `GET` | `/api/migration/projects/{id}/prep-readiness` | Pre-flight check — returns 4A gate status per item |
| `POST` | `/api/migration/projects/{id}/prepare` | Generate ordered task plan (sets `pending_approval`, fires notification) |
| `GET` | `/api/migration/projects/{id}/prep-tasks` | List all tasks with status counts |
| `POST` | `/api/migration/projects/{id}/prep-tasks/{task_id}/execute` | Execute a single task |
| `POST` | `/api/migration/projects/{id}/prepare/run` | Run all pending/failed tasks in order (requires `approved` status) |
| `POST` | `/api/migration/projects/{id}/prep-tasks/{task_id}/rollback` | Undo a completed task |
| `DELETE` | `/api/migration/projects/{id}/prep-tasks` | Clear all pending/failed tasks |
| `GET` | `/api/migration/projects/{id}/prep-summary` | Post-run summary counts by task type (v1.36.1) |
| `GET` | `/api/migration/projects/{id}/prep-approval` | Get approval status, approver, and full history (v1.36.2) |
| `POST` | `/api/migration/projects/{id}/prep-approval` | Approve or reject the plan — requires `migration:admin` (v1.36.2) |
| `POST` | `/api/migration/projects/{id}/prepare/dry-run` | Dry-run simulation — classifies tasks without executing (v1.36.2) |
| `GET` | `/api/migration/projects/{id}/prep-audit` | Full audit trail: approvals, activity log, execution history (v1.36.2) |

---

## vJailbreak Handoff Exports

> Prerequisite: Phase 4B complete (all provisioning tasks `done` or `skipped`).

Once PCD resources are provisioned the Migration Planner can produce two handoff artifacts for the execution phase:

### vJailbreak Credential Bundle (JSON)

A JSON document containing everything vJailbreak needs to connect to each PCD project and start migrating VMs: PCD project UUID, service-account credentials, all user temporary passwords, network UUIDs with CIDR/gateway/VLAN, and cohort/wave sequence.

- **Full project** — `GET /api/migration/projects/{id}/export-vjailbreak-bundle`
- **Single cohort** — `GET /api/migration/projects/{id}/cohorts/{cid}/export-vjailbreak-bundle`

If any tenants are missing service accounts or PCD project IDs (provisioning incomplete) the response includes a `warnings[]` array but still returns the partial bundle.

### vJailbreak Agent Status & Wave Execution (v1.45.0)

Once a vJailbreak agent is deployed, set `VJAILBREAK_API_URL` in the API environment and use these endpoints:

**GET** `/api/migration/projects/{id}/vjailbreak-status`  
Returns agent connectivity: `not_configured`, `connected`, or `unreachable`.

```json
{ "status": "connected", "message": "vJailbreak agent is reachable.", "agent_url": "https://vj.example.com" }
```

**POST** `/api/migration/projects/{id}/waves/{wave_id}/execute`  
*Requires: `migration:admin`*  
Forwards the wave to the vJailbreak REST API. Returns HTTP 503 with a clear message when the agent URL is not configured.

Request body (optional):
```json
{ "dry_run": false, "notes": "Executing wave 1 – low-risk tenants" }
```

Response:
```json
{
  "status": "accepted",
  "wave": { "id": 1, "wave_number": 1, "name": "Wave 1", "status": "planned", "tenant_count": 3 },
  "vjailbreak_response": { ... },
  "dry_run": false
}
```

### Tenant Handoff Sheet (PDF)

A CONFIDENTIAL A4 PDF document — one section per in-scope tenant — containing:
- Domain/project identity and PCD auth URL
- Network mappings: source name, target UUID, CIDR, gateway, VLAN
- User roster with temporary passwords (service accounts highlighted)
- Confidentiality notice on every page

`GET /api/migration/projects/{id}/export-handoff-sheet.pdf`

> ⚠️ This document contains plaintext temporary passwords. Distribute to tenants through a secure channel (encrypted email, password manager share, in-person handoff).

### UI

Both export buttons appear automatically in the **⚙️ Prepare PCD** tab once all provisioning tasks reach `done` or `skipped`. Click:
- **📦 vJailbreak Credential Bundle** to download the JSON file
- **📄 Tenant Handoff Sheet** to download the PDF

---

## Phase 5.0 — Migration Summary & Fix Time

> Accessible via the **📊 Summary** sub-tab in Source Analysis.

Phase 5.0 adds a post-migration effort model and an executive-level Migration Summary view. After VMs land on PCD there is always a "fix window" — time spent renaming NICs, fixing UUIDs, re-verifying routes, etc. Phase 5.0 quantifies this upfront so planners can present a realistic total project timeline.

### Fix Time Model

| Factor | Default (min) | Rationale |
|--------|---------------|-----------|
| Windows OS | 20 | NIC rename, drive letter reassignment |
| Extra data volume | 15 / disk | fstab / UUID changes |
| Extra NIC | 10 / NIC | Multi-IP, routes, DNS re-verify |
| Cold migration | 15 | Higher stale-driver risk at first boot |
| Elevated risk (Yellow, >50) | 15 | Flagged by risk scorer |
| High risk (Red, >75) | 25 | Complex VM |
| Has snapshots | 10 | Disk-chain consolidation |
| Cross-tenant dependency | 15 | Coordinated cutover |
| Unknown / other OS | 20 | Unpredictable boot behaviour |
| Cutover window (always) | 30 | Final sync + first boot |

**OS-family fix rates** (% of VMs expected to need any intervention): Windows 50%, Linux 20%, Other / Unknown 40%. All rates and all 10 weights are configurable per project via the Settings editor in the Summary tab.

### Per-VM Fix Override

Any VM can have `tech_fix_minutes_override` set, locking it to an operator-supplied value and bypassing the model. The ⏱ Fix Time Override card in the expanded VM row provides a number input, Save, and Clear button. The `🔒 Xm` amber pill in the VM table reflects the override immediately.

### Migration Summary Tab  *(v1.44.0 — per-day breakdown)*

- **Executive KPI strip** — Migration Days (blue), In-Use Data (TB) with provisioned subtitle (`X GB used / Y TB provisioned`), Estimated Data-Copy Time (h), Estimated Fix Time (h), Total Downtime (h)
- **Per-day schedule table** — one row per calendar day with: Cohort/Wave, Tenants, VMs, Storage GB (in-use), Wall-clock (h), Agent Total (h), ❄️ Cold, 🔥 Warm, 🟢/🟡/🔴 risk counts. Over-capacity days (`wall_clock_hours > working_hours_per_day`) are highlighted in red with a ⚠️ prefix.
- **OS-family table** — VM count + fix rate + data + fix time per OS family
- **Per-cohort table** — VM count, data (GB), copy time, fix time, downtime exposure per cohort
- **Methodology accordion** — expands to explain all three calculations in plain language
- **Settings editor** — 10 weight sliders + 3 fix-rate fields; **💾 Save & Recalculate** applies changes and refreshes

> **Alignment guarantee**: the Summary tab runs the same `generate_migration_plan()` engine as the Export Plan endpoint — day counts, cohort assignments, and GB totals are always identical.

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/fix-settings` | Current weights + rates (auto-created with defaults) |
| `PATCH` | `/api/migration/projects/{id}/fix-settings` | Update any weight or fix rate (`null` resets to default) |
| `PATCH` | `/api/migration/projects/{id}/vms/{vm_id}/fix-override` | Set or clear per-VM fix override (`null` = clear) |
| `GET` | `/api/migration/projects/{id}/migration-summary` | Full summary: KPIs, per-day schedule, OS breakdown, cohort breakdown, methodology |

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

11. EXPORT HANDOFF ARTIFACTS
    └── Prepare PCD tab → export panel appears once all tasks complete
    └── Download vJailbreak Credential Bundle (JSON) → hand to vJailbreak operator
    └── Download Tenant Handoff Sheet (PDF) → distribute credentials to tenant owners

12. VIEW MIGRATION SUMMARY (Phase 5.0)
    └── Source Analysis → 📊 Summary tab
    └── Review KPI strip: total VMs, total data, data-copy time, fix time, total downtime
    └── Check per-cohort breakdown → spot any cohort with outsized fix exposure
    └── Adjust settings (weight sliders + fix rates) if defaults don't fit the environment
    └── Set per-VM overrides for known complex VMs via expanded row ⏱ Fix Time Override card

13. EXECUTE WAVES (future Phase 5+ — vJailbreak)
    └── Advance Wave 0 to executing (pilot)
    └── Validate pilot → advance to complete
    └── Proceed wave by wave through the plan

14. EXPORT REPORTS
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
| `POST` | `/api/migration/projects/{id}/tenant-users/seed-tenant-owners` | Bulk-seed one `admin@<slug>` owner per tenant (idempotent) |
| `POST` | `/api/migration/projects/{id}/tenant-users/bulk-replace` | Regex find-and-replace across a user field (preview + apply) |
| `POST` | `/api/migration/projects/{id}/tenant-users/confirm-all` | Mark all unconfirmed users as confirmed |
| `POST` | `/api/migration/projects/{id}/tenant-users/bulk-action` | Confirm / set-role / delete for a set of user IDs |

### Phase 4D — vJailbreak CRD Push *(v1.46.0)*

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/vjailbreak-push-settings` | Get vJailbreak API URL, namespace, and token status |
| `PATCH` | `/api/migration/projects/{id}/vjailbreak-push-settings` | Update URL, namespace, or bearer token |
| `POST` | `/api/migration/projects/{id}/vjailbreak-push/dry-run` | Simulate CRD push — returns `would_create` / `would_skip` counts per type |
| `POST` | `/api/migration/projects/{id}/vjailbreak-push` | Push `OpenstackCreds`, `VMwareCreds`, `NetworkMappings` CRDs to vJailbreak cluster |
| `GET` | `/api/migration/projects/{id}/vjailbreak-push-tasks` | List task log for all CRD push attempts |
| `DELETE` | `/api/migration/projects/{id}/vjailbreak-push-tasks` | Clear push task log |

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

### Handoff Exports (v1.37.0)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/migration/projects/{id}/export-vjailbreak-bundle` | Full-project vJailbreak credential bundle (JSON) |
| `GET` | `/api/migration/projects/{id}/export-vjailbreak-bundle?cohort_id={cid}` | Cohort-scoped variant |
| `GET` | `/api/migration/projects/{id}/cohorts/{cid}/export-vjailbreak-bundle` | Cohort-scoped (path-param) |
| `GET` | `/api/migration/projects/{id}/export-handoff-sheet.pdf` | Tenant handoff sheet (PDF) |

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
