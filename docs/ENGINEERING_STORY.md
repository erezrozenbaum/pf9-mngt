# Engineering Story — Why pf9-mngt Was Built

> This document covers the Platform9 evaluation background and the four operational
> engineering gaps that motivated each core subsystem. For a high-level overview
> see [README.md](../README.md).

---

## 🧭 Why This Exists — An Engineering Evaluation Story

The conversation around VMware alternatives is real and growing. For MSPs and enterprise teams evaluating their options, Platform9 on OpenStack is genuinely worth looking at. Solid technology, strong business model, and a credible path for organizations managing private and hybrid cloud at scale.

This project was built during a serious Platform9 evaluation — testing Platform9 as a potential direction for our infrastructure. During that process, like any serious evaluation, you go beyond the demo and start stress-testing real operational workflows. That is where engineering gaps become visible — not because the platform is lacking, but because MSP and enterprise operations have very specific day-to-day requirements that take time for any platform to fully mature into.

Rather than pause the evaluation, we chose to solve the gaps ourselves and reach a better, more informed decision point. The result is pf9-mngt. What started as an evaluation tool grew into a production-grade platform in its own right — 409+ commits, 121 releases, 15 containerized services, full CI pipeline, and Docker images published to ghcr.io.

This entire project was built using AI as a genuine engineering partner — what some call vibe coding, but applied to a real production problem with real architectural decisions. One person, clear intent, and the right AI workflow can ship something with genuine depth. That is worth demonstrating.

---

### 🔐 Engineering Gap 1 — Metadata Ownership & Operational Resilience

OpenStack identifies everything by UUID. Resource names, relationships, network topology, and tenant context all live in the metadata layer on the management cluster. When you run Platform9 in SaaS mode, that metadata lives on their platform — not yours.

From an engineering perspective this creates a real operational resilience challenge. Without that metadata layer your resources become very difficult to identify and manage independently at scale. For MSPs managing multiple tenants and hundreds of resources, this is a genuine business continuity risk.

**The engineering answer:** pf9-mngt continuously pulls and persists all infrastructure metadata into a local PostgreSQL database that you own and control — independently of the platform. Resource names, relationships, tenant context, change history, and full inventory are always available locally, regardless of platform availability. This is exactly what RVTools does for VMware environments. We built the equivalent for Platform9 and OpenStack.

---

### ⚡ Engineering Gap 2 — VM Restore

In VMware, restoring a VM is a right-click. In OpenStack, there is no equivalent native workflow. To recover a VM from a snapshot you must manually reconstruct everything — remember the original flavor, network topology, IP configuration, re-attach the snapshot volume, and preserve user credentials. All of this under SLA pressure, without making a mistake.

For an MSP, that manual process is not sustainable at scale. It is exactly the kind of procedure that goes wrong at the worst possible moment.

**The engineering answer:** pf9-mngt automates the entire restore procedure. The restore engine handles flavor, network topology, IP addresses, user credentials, and volume attachment automatically. Two restore modes are supported:

- **Side-by-side restore** — a new VM with a new name and new IP spins up alongside the original, completely non-destructively. Validate before cutover. Nothing is touched until you are ready.
- **Replace restore** — full automated recovery with the original configuration restored. Superadmin-only for safety.

Every restore operation is fully audited — who triggered it, what was restored, what mode, duration, and outcome. For MSP accountability and compliance this is not optional.

---

### 🔄 Engineering Gap 3 — Snapshot Automation & Compliance

There is no native automated snapshot scheduler in Platform9 or OpenStack. No configurable per-volume policies. No retention management. No SLA compliance tracking. For an MSP, snapshot automation is table stakes — you cannot deliver a managed service without it.

**The engineering answer:** pf9-mngt includes a complete snapshot automation engine built from scratch. Configurable policies per volume — daily, monthly, custom retention — with automatic cleanup and full SLA compliance reporting aggregated by tenant and domain. v1.26.0 adds **quota-aware batching** with Cinder quota pre-checks, tenant-grouped batching with configurable rate limits, live progress tracking, and the `snapshot_quota_forecast` proactive runbook.

---

### 📦 Engineering Gap 4 — VMware Migration Assessment & Capacity Planning

Migrating hundreds of VMs from VMware to PCD is not just "move the disks." You need full source inventory analysis, OS compatibility classification, warm-vs-cold mode determination, per-VM time estimation, cohort planning, and target capacity validation — before a single VM moves. No native tooling ties RVTools data to PCD readiness in one end-to-end workflow.

**The engineering answer:** pf9-mngt includes a full **Migration Planner** — a multi-stage workflow that takes you from raw RVTools data all the way to an approved, wave-sequenced migration plan ready for execution.

**📥 Source Inventory & Assessment**
- RVTools XLSX ingestion — parses vInfo, vPartition, vDisk, vNetwork sheets into a structured per-VM inventory
- Per-VM risk scoring (GREEN / YELLOW / RED) with configurable weighted rules (OS, disk size, NIC count, snapshots)
- Warm-eligible vs cold-required classification — based on risk score and operator overrides
- OS family and version detection; actual used-disk data from vPartition (not provisioned size)
- Per-VM time estimation — warm phase-1 copy, incremental sync, cutover window, and cold total downtime
- Excel + PDF export — Project Summary, Per-Tenant Assessment, Daily Schedule, All VMs

**🗺️ Target Mapping & Capacity Planning**
- Per-tenant scoping — mark tenants in or out of plan with bulk-select toolbar and exclusion reasons
- Source → PCD target mapping — map each tenant to a target PCD domain and project; auto-seeded with confirmed-flag review workflow
- Source → PCD network mapping — auto-seeded from VM inventory; VLAN ID, confirmed status, Find & Replace, Confirm All
- VM dependency annotation — mark app-stack ordering constraints (web → DB) with circular-dependency validation
- Per-tenant readiness checks — 5 auto-derived: target mapped, network mapped, quota sufficient, no critical gaps, VMs classified
- Overcommit profile modeling — Aggressive / Balanced / Conservative presets with configurable ratios
- Quota requirements engine — recommended per-tenant vCPU, RAM, and storage on the PCD side
- **Performance-based node sizing** — uses actual `cpu_usage_percent` / `memory_usage_percent` from RVTools data (not vCPU allocation ÷ overcommit) for accurate physical node demand; falls back to allocation or quota if performance data is unavailable
- Auto-detect PCD node profile from live hypervisor inventory with one click
- PCD readiness gap analysis — missing flavors, networks, images, unmapped tenants — with severity scoring and downloadable action report (Excel + PDF)

**🗃️ Cohort Planning**
- **Migration Cohorts** — split large projects into ordered workstreams, each with its own schedule, owner, and dependency gate
- **Tenant ease scoring** — composite 0–100 score per tenant based on VM count, disk size, risk score, OS support rate, network complexity, and cross-tenant dependencies; configurable dimension weights
- **Auto-assign strategies** — six algorithms: easiest-first, riskiest-last, pilot + bulk, balanced load, OS-first, by-priority; with guardrails (max VMs, max disk, max avg risk per cohort)
- **What-if estimator** — two side-by-side models per cohort (bandwidth/transfer model + VM-slots scheduler model); live recalculation as you adjust agent slots or bandwidth; project deadline banner turns red if either model exceeds the target duration
- Expandable cohort cards — avg ease, risk distribution, OS mix, readiness counts, and cross-cohort dependency warnings
- Gantt-style date bars and dependency lock indicators

**🌊 Wave Planning**
- Cohort-scoped auto-builder — builds independent wave sets per cohort in execution order; five strategies: bandwidth-paced, risk-tiered, even-spread, dependency-ordered, pilot-first
- Pilot wave support — auto-creates a low-risk pilot wave per cohort to validate toolchain before committing the bulk
- Full wave lifecycle — planned → confirmed → in-progress → complete, with timestamps and transition guards
- Per-wave pre-flight checklists — network mapped, target project set, VMs assessed, no critical gaps, agent reachable, snapshot baseline
- Wave Planner UI — VM migration funnel, per-cohort wave cards, VM assignment tables, preflight status panel, dry-run preview before committing
- **Wave Approval Gates** — each wave requires explicit approval before advancing to execution; approval request notifications, inline approve/reject with comment, gated advance button; approval status badge (⏳ pending / ✅ approved / ❌ rejected)
- **VM Dependency Auto-Import** — automatically detects implicit VM dependencies from RDM disk sharing (confidence 0.95) and shared-datastore co-location (confidence 0.70); dry-run preview before committing; source badges (💽 RDM / 🗄 DS) distinguish auto-imports from manually entered dependencies
- **Maintenance Window Scheduling** — define recurring per-project maintenance windows (day-of-week, start/end time, timezone, cross-midnight support); Auto-Build Waves stamps each wave with `scheduled_start`/`scheduled_end` from the next available slot; preview strip shows next 8 upcoming calendar bands

**⚙️ PCD Data Enrichment (Network Map, Flavor Staging, Image Checklist)**
- Source → PCD network mapping with VLAN IDs, confirmed status, Find & Replace, Confirm All; subnet details panel per row (CIDR, gateway, DNS, DHCP pool)
- **Excel template export/import** — download a pre-filled XLSX for bulk subnet entry; import back to update all rows at once; formula detection catches VLOOKUP external-reference issues with a clear fix instruction; diagnostic response pinpoints any row-matching failures
- **Confirm Subnets** one-click bulk action marks all rows with CIDR as subnet-confirmed; inline CIDR display in the Subnet Details column; import auto-confirms on CIDR presence
- Flavor Staging — de-duplicated per (vCPU, RAM) shape; match against live PCD Nova API; confirmed rows show "✓ exists" vs "✓ new" status pill; Find & Replace, Confirm All
- Image Requirements checklist — one row per OS family; confirm after uploading to PCD Glance; Match PCD auto-links to existing Glance images; status pill differentiates existing vs new images
- PCD Readiness Score — live readiness counter per resource type; gaps auto-resolve when mappings/staging/image requirements are confirmed; network gaps resolve when all confirmed mappings cover the gap list

**⚙️ PCD Auto-Provisioning (Prepare PCD)**
- **Readiness gate** — pre-flight check (`GET /prep-readiness`) verifies all four data enrichment items are confirmed (subnets, flavors, images, users) before allowing task generation
- **Ordered task plan generation** (`POST /prepare`) — builds 667+ provisioning tasks in strict dependency order: create domains → create projects → set quotas → create networks → create subnets → create flavors → create users → assign roles
- **Per-task execution** (`POST /prep-tasks/{id}/execute`) — each task executes against the live PCD Keystone / Neutron / Nova API; writes back PCD UUIDs to source tables (`target_network_id`, `pcd_flavor_id`, `pcd_user_id`, `temp_password`)
- **Run All** (`POST /prepare/run`) — executes all pending/failed tasks in order; stops on first new failure to prevent cascade
- **Per-task rollback** (`POST /prep-tasks/{id}/rollback`) — deletes the PCD resource and resets the task; domain rollback is safety-checked (refuses if domain still contains projects)
- **⚙️ Prepare PCD UI tab** — readiness grid (4 cards), Generate Plan + Run All buttons, task table with status badges, inline error expansion, auto-refresh every 3 s

**📊 Migration Summary & Tech Fix Time Estimation**
- **Fix time model** — per-VM post-migration effort score: Windows OS, extra volumes, extra NICs, cold migration, risk tier, snapshots, cross-tenant dependencies, unknown OS; multiplied by OS-family fix rate (Windows 50%, Linux 20%, Other 40%) to produce expected intervention time in minutes
- **`migration_fix_settings`** — per-project weight sliders and OS fix rates, auto-created with defaults; all 10 factors are tunable per project without code changes
- **Per-VM fix override** — operators can lock any individual VM to a specific fix time (bypassing the model); inline ⏱ Fix Time Override card in the expanded VM row with number input, Save, and Clear
- **Migration Summary tab** — executive KPI strip (Migration Days, In-Use Data TB with provisioned subtitle, Estimated Data-Copy Time, Estimated Fix Time, Total Downtime); **per-day schedule table** with cohort, VMs, storage (GB), wall-clock time, agent hours, cold/warm split, and risk breakdown per day; over-capacity days highlighted in red with ⚠️; OS-family breakdown table; per-cohort breakdown; methodology accordion; settings editor
- **Throughput cap engine** — daily schedule uses a shared-pipe GB/day ceiling (`effective_gbph × working_hours`) instead of per-slot hour packing; `wall_clock_hours` is correctly derived from `day_transfer_gb / effective_gbph`; `over_capacity` flag emitted when a day's payload exceeds the ceiling
- **Tenant filter dropdowns** — Scope, Ease, Cohort, and Network Type filters in the Tenants tab with a Clear Filters button

---

### 🐳 Deployment Flexibility — You Decide How to Run This

pf9-mngt is currently developed on Windows using Docker containers. That is the development environment — but the architecture is deliberately not prescriptive about how you run it in production.

Every service is containerized. That means **you decide**:

| Option | When to use |
|--------|-------------|
| 🐳 **Docker Compose** | Simple, fast, perfectly viable for many teams |
| ☸️ **Kubernetes** | Production-grade HA and horizontal scaling — containers are ready, effort is minimal |
| 🔧 **Your own orchestration** | Adapt to whatever infrastructure decisions you have already made |

> **Note:** As of v1.82.0, Kubernetes is fully supported. A complete Helm chart, ArgoCD manifest, and Sealed Secrets guide live in `k8s/`. See [docs/KUBERNETES_GUIDE.md](docs/KUBERNETES_GUIDE.md) for the deployment guide.  
> See [docs/LINUX_DEPLOYMENT_GUIDE.md](docs/LINUX_DEPLOYMENT_GUIDE.md) for running on Linux.

---

