# Platform9 Management System

**Operational Management Platform for Platform9 / OpenStack**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.73.1-blue.svg)](CHANGELOG.md)
[![CI](https://github.com/erezrozenbaum/pf9-mngt/actions/workflows/ci.yml/badge.svg)](https://github.com/erezrozenbaum/pf9-mngt/actions/workflows/ci.yml)
[![Platform](https://img.shields.io/badge/platform-Docker%20%7C%20Windows%20%7C%20Linux-informational.svg)](#-deployment-flexibility--you-decide-how-to-run-this)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-orange.svg)](https://www.buymeacoffee.com/erezrozenbaum)

pf9-mngt is an open-source operational management platform for Platform9 / OpenStack — it gives engineering and MSP teams automated snapshots, VM restore, full inventory persistence, and day-to-day monitoring in a single self-hosted stack.

---

## What pf9-mngt Is

- A **self-hosted operational layer** that continuously persists all Platform9 / OpenStack metadata into your own PostgreSQL database — independently of platform availability
- A **snapshot automation engine** built from scratch (no native scheduler exists in Platform9 or OpenStack): quota-aware, multi-tenant, policy-driven, with SLA compliance reporting
- A **VM restore system** with side-by-side and replace modes — full flavor, network, IP, credential, and volume automation (no native equivalent exists in OpenStack)
- A **migration planning workbench** from RVTools ingestion through cohort design, wave planning, and PCD auto-provisioning
- An **engineering dashboard** with 30+ management tabs, RBAC, full audit trail, metering/chargeback, notifications, runbooks, a support ticket system, and an AI Ops Copilot

---

## What pf9-mngt Is Not

- **Not a replacement for the official Platform9 UI** — it is a complementary operational layer that adds engineering workflows the native UI does not provide
- **Not an official Platform9 product** — it is an independent open-source project, not endorsed by or affiliated with Platform9 Systems, Inc.
- **Not a cloud control plane** — it does not replace Keystone, Nova, Cinder, or Neutron; it orchestrates them via their APIs
- **Not intended for end users** — it is an engineering and MSP operations console for the team managing the platform

---

## 🚀 System Architecture

**14-container microservices platform:**

| Service | Stack | Port | Purpose |
|---------|-------|------|---------|
| **nginx (TLS proxy)** | nginx:1.27-alpine | 80/443 | HTTPS termination, HTTP→HTTPS redirect, reverse proxy to API and UI |
| **Frontend UI** | React 19.2+ / TypeScript / Vite | 5173 | 30+ management tabs + admin panel |
| **Backend API** | FastAPI / Gunicorn / Python | 8000 | 170+ REST endpoints, RBAC middleware, 4 workers + --max-requests 1000 |
| **Redis** | redis:7-alpine | internal | OpenStack inventory/quota cache (60–300 s TTL, allkeys-lru, 128 MiB cap) |
| **LDAP Server** | OpenLDAP | internal | Enterprise authentication directory (not exposed to host) |
| **LDAP Admin** | phpLDAPadmin | 8081 *(dev profile)* | Web-based LDAP management (`--profile dev`) |
| **Monitoring Service** | FastAPI / Python | 8001 | Real-time metrics via Prometheus |
| **Database** | PostgreSQL 16 | internal | 65+ tables, audit, metering, migration planner (not exposed to host) |
| **Database Admin** | pgAdmin4 | 8080 *(dev profile)* | Web-based PostgreSQL management (`--profile dev`) |
| **Snapshot Worker** | Python | — | Automated snapshot management |
| **Notification Worker** | Python / SMTP | — | Email alerts for drift, snapshots, compliance |
| **Backup Worker** | Python / PostgreSQL | — | Scheduled DB + LDAP backups to NFS, restore *(backup profile)* |
| **Scheduler Worker** | Python | — | Host metrics collection + RVTools inventory (runs inside Docker) |
| **Metering Worker** | Python / PostgreSQL | — | Resource metering every 15 minutes |
| **Search Worker** | Python / PostgreSQL | — | Incremental full-text indexing for Ops Assistant |

```text
Platform9 / OpenStack APIs
           │
     ┌─────┴─────┐
     │  pf9-api  │  FastAPI / Gunicorn (4 workers)
     └─────┬─────┘
           │
  ┌────────┼────────┬────────┐
  │        │        │        │
Redis     LDAP   pf9_db   nginx
(cache)  (auth)(PostgreSQL)(TLS)
           │
  ┌────────┼──────────────────────────────┐
  │        │         │         │          │
Snapshot Backup  Metering   Search  Notifications  Scheduler
Worker   Worker   Worker    Worker    Worker         Worker
           │
     ┌─────┴─────┐
     │  pf9-ui   │  React / Vite (served via nginx)
     └───────────┘
```

> `pf9_scheduler_worker` (Docker container) runs `host_metrics_collector.py` (every 60 s) and `pf9_rvtools.py` (configurable interval or daily schedule) for infrastructure discovery and metrics collection. No Windows Task Scheduler dependency.

---

## 📊 Feature Status

| Feature | Status |
|---------|--------|
| Inventory Engine (RVTools-style, 29 resource types) | ✅ Production |
| Snapshot Automation | ✅ Production |
| VM Restore (side-by-side + replace modes) | ✅ Production |
| Reports (20 types + CSV export) | ✅ Production |
| Customer Provisioning & Domain Management | ✅ Production |
| Metering & Chargeback | ✅ Production |
| Notifications (SMTP + Slack + Teams) | ✅ Production |
| Drift Detection | ✅ Production |
| Ops Assistant — Full-Text Search & Smart Queries | ✅ Production |
| Runbooks (25 built-in, dept visibility, approval workflows) | ✅ Production |
| External Integrations Framework (billing gate, CRM, webhooks) | ✅ Production |
| Dependency Graph: Health Scores, Blast Radius, Delete Impact | ✅ Production |
| Backup & Restore (DB) with Integrity Validation | ✅ Production |
| Inventory Versioning & Diff | ✅ Production |
| AI Ops Copilot | ✅ Production |
| Migration Planner (end-to-end) | ✅ Production |
| Support Ticket System (SLA, auto-tickets, approvals) | ✅ Production |
| Container Restart Alerting | ✅ Production |
| Multi-Region & Multi-Cluster Support | ✅ Production |
| Kubernetes Deployment | ⬜ Planned |
| Tenant Self-Service Portal | ⬜ Planned |

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

> **Note:** Kubernetes deployment is a design target — the architecture is planned but not yet tested in production. See [docs/KUBERNETES_MIGRATION_GUIDE.md](docs/KUBERNETES_MIGRATION_GUIDE.md) for the design plan.  
> See [docs/LINUX_DEPLOYMENT_GUIDE.md](docs/LINUX_DEPLOYMENT_GUIDE.md) for running on Linux.

---

## 📸 Screenshots

### Landing Dashboard
![Landing Dashboard](docs/images/dashboard-overview.png)

### Snapshot Compliance Report
![Snapshot Compliance Report](docs/images/snapshot-compliance-report.png)

### VM Inventory
![VM Inventory](docs/images/VMs-inventory.png)

### History & Monitoring
![History & Monitoring](docs/images/History-monitoring.png)

### API Performance
![API Performance](docs/images/API-Performance.png)

### Snapshot Restore Process
![Snapshot Restore Process](docs/images/snapshot-restore-process.png)

### Snapshot Restore Audit
![Snapshot Restore Audit](docs/images/Snapshot-restore-audit.png)

---

## 🎬 Video Walkthrough

A 15-minute explainer video walking through the UI and key features:

[![Watch on YouTube](https://img.shields.io/badge/YouTube-Watch%20Video-red?logo=youtube)](https://www.youtube.com/watch?v=68-LQ9ugU_E)

▶️ [**PF9 Management System — Full UI Walkthrough (15 min)**](https://www.youtube.com/watch?v=68-LQ9ugU_E)

---

## 🌟 Key Features

### 🔐 Enterprise Authentication & Authorization
- **LDAP Integration**: Production-ready OpenLDAP authentication — also compatible with Active Directory
- **Role-Based Access Control**: 5-tier permission system (Viewer, Operator, Admin, Superadmin, Technical)
- **MFA Support**: TOTP-based two-factor authentication (Google Authenticator compatible) with backup recovery codes
- **JWT Token Management**: Secure 480-minute sessions with Bearer token authentication
- **RBAC Middleware**: Automatic permission enforcement on all resource endpoints
- **Audit Logging**: Complete authentication event tracking — login, logout, failed attempts, user management
- **System Audit**: 90-day retention with filtering by user, action, date range, and IP address

### 📊 RVTools-Style Unified Inventory
- **29 Resource Types**: Domains, Projects, Users, VMs, Volumes, Snapshots, Networks, Subnets, Ports, Floating IPs, Routers, Security Groups, Hypervisors, Flavors, Images, Roles, Role Assignments, Groups, Snapshot Policies, and operational event types
- **Human-Friendly Names**: UUID-to-name resolution across all resource types
- **Local Persistent Store**: All metadata stored in your own PostgreSQL — independent of platform availability
- **Excel/CSV Export**: Customer-data-safe with masking options and delta reporting
- **Multi-Tenant Support**: Full domain and project-level filtering and management
- **Comprehensive Audit System**: Change tracking, deletion history, compliance reporting, resource timeline

<details>
<summary><strong>User Management Details</strong></summary>

- **Multi-Domain User Collection**: 100+ users across 28 OpenStack domains
- **Role Assignment Tracking**: Monitors role assignments across the infrastructure
- **Activity Monitoring**: User last-seen timestamps and account status
- **Role Inference System**: Intelligent role assignment when API access is limited
- **Domain-Scoped Authentication**: Complete user enumeration across tenants
- **LDAP Password Reset** *(v1.40)*: Superadmin can reset any LDAP user's password directly from the Users table — 🔑 button opens an inline form with SSHA-hashed password write, minimum-length validation, and full audit logging

</details>

### 🔄 Automated Snapshot Management
- **Built From Scratch**: No native scheduler exists in Platform9 or OpenStack — we built one
- **Metadata-Driven Policies**: Volume-level configuration via OpenStack metadata
- **Multi-Policy Support**: daily_5, monthly_1st, monthly_15th with independent retention per volume
- **Cross-Tenant Snapshots**: Dedicated service user architecture for correct tenant context
- **SLA Compliance Reporting**: Configurable thresholds with detailed tenant/domain aggregation
- **Policy Assignment Rules**: JSON-driven automatic policy assignment based on volume properties

<details>
<summary><strong>Snapshot System Components</strong></summary>

- **Automated Creation** (`snapshots/p9_auto_snapshots.py`): Policy-driven volume snapshots with retention management, dual-session architecture (admin for listing, service user for creating)
- **Service User Management** (`snapshots/snapshot_service_user.py`): Automatic admin role assignment per tenant project, Fernet-encrypted or plaintext password support
- **Policy Assignment** (`snapshots/p9_snapshot_policy_assign.py`): Opt-out rule engine, volume property matching, bulk metadata assignment
- **Compliance Reporting** (`snapshots/p9_snapshot_compliance_report.py`): Real-time SLA analysis, tenant/domain aggregation

</details>

### ⚡ Automated VM Restore *(No native equivalent exists in OpenStack)*
- **Full Restore Automation**: Flavor, network, IPs, user credentials, volume attachment — all handled
- **Side-by-Side Restore**: New VM with new name and IP alongside the original — non-destructive
- **Replace Restore**: Full recovery with original configuration — Superadmin-only with typed confirmation
- **IP Strategies**: NEW_IPS (DHCP), TRY_SAME_IPS (best-effort), SAME_IPS_OR_FAIL (strict)
- **3-Screen UI Wizard**: Guided restore flow with real-time progress tracking
- **Dry-Run Mode**: Validate the full restore plan before executing against OpenStack
- **Safety First**: Disabled by default, concurrent restore prevention, quota double-check, rollback on failure
- **Full Restore Audit**: Every operation logged — who, what mode, duration, outcome

### 👁️ Real-Time Monitoring
- **Host Metrics**: Live CPU, memory, storage from PF9 compute nodes via Prometheus node_exporter (port 9388)
- **VM Metrics**: Individual VM resource tracking via libvirt_exporter (port 9177)
- **Automated Collection**: Background collection every 30 minutes
- **Persistent Cache**: Metrics survive service restarts
- **Integrated Dashboard**: Real-time monitoring tab with auto-refresh

### 🔔 Smart Notifications
- **Event-Driven Alerts**: Snapshot failures, compliance violations, drift events, health score drops
- **Per-User Preferences**: Subscribe to specific event types with severity filtering (info/warning/critical)
- **Daily Digest**: Configurable daily summary aggregating all events from past 24 hours
- **SMTP Flexibility**: Authenticated and unauthenticated relay support, optional TLS
- **HTML Templates**: Professional Jinja2 email templates for each event type
- **Notification History**: Full delivery log with status tracking and retry information

### 💰 Metering & Chargeback
- **Per-VM Resource Tracking**: vCPU, RAM, disk allocation + actual usage, network I/O
- **Snapshot & Restore Metering**: Count, size, compliance, operation tracking
- **API Usage Metering**: Endpoint-level call counts, error rates, latency percentiles (avg/p95/p99)
- **Efficiency Scoring**: Per-VM classification (excellent/good/fair/poor/idle)
- **Multi-Category Pricing**: Compute, storage, snapshot, restore, volume, network — hourly + monthly rates
- **Chargeback Export**: Per-tenant cost breakdown with one-click CSV export
- **8 Sub-Tab UI**: Overview, Resources, Snapshots, Restores, API Usage, Efficiency, Pricing, Export

### 🏢 Customer Provisioning & Domain Management *(v1.16 → v1.34.2)*
- **5-Step Provisioning Wizard**: Domain → Project → User/Role → Quotas → Networks/Security Group
- **Multi-Network Support** *(v1.34.2)*: Add any combination of 3 network kinds per provisioning run:
  - 🔌 **Physical Managed** — provider/external VLAN network (`<domain>_tenant_extnet_vlan_<id>`)
  - 🔗 **Physical L2 (Beta)** — provider L2 network, no subnet (`<domain>_tenant_L2net_vlan_<id>`)
  - ☁️ **Virtual** — standard tenant network (`<domain>_tenant_virtnet[_N]`)
- **Dynamic Keystone Roles**: Fetches roles from PF9 Keystone, filters internal system roles
- **Tabbed Quota Editor**: Compute, Block Storage, Network tabs with "Set Unlimited" toggles
- **Network Auto-Discovery**: Physical networks from Neutron with VLAN/flat/VXLAN support
- **Customer Welcome Email**: HTML template listing all provisioned networks (kind, VLAN, subnet, gateway) per network card
- **Domain Management**: Full lifecycle — enable/disable, typed confirmation delete, resource inspection
- **Resource Deletion**: 8 DELETE endpoints for individual resources across all types
- **Central Activity Log**: Full audit trail for all provisioning and domain operations
- **DB Persistence**: `networks_config` + `networks_created` JSONB columns in `provisioning_jobs` store full input and output network details

### 📋 Reports & Resource Management *(v1.17 → v1.63)*
- **20 Report Types**: VM Report, Tenant Quota Usage, Domain Overview, Snapshot Compliance, Flavor Usage, Metering Summary, Resource Inventory, User/Role Audit, Idle Resources, Security Group Audit, Capacity Planning, Backup Status, Activity Log, Network Topology, Cost Allocation, Drift Summary, **Image Usage by Tenant** *(v1.40)*, **Flavor Usage by Tenant Detail** *(v1.40)*
- **BFV-aware reporting** *(v1.40)*: Image and Flavor by Tenant reports resolve instances booted from volume via Cinder `volume_image_metadata` — full VM counts including BFV workloads
- **CSV Export**: All reports support one-click CSV download
- **RVTools Exports Browser** *(v1.63)*: "📁 RVTools Exports" sub-tab inside Reports — file list (filename, size, date) with one-click authenticated download + run history table showing the last 100 `inventory_runs` entries (started, finished, duration, status badge)
- **Resource Provisioning Tool**: Full CRUD for Users, Flavors, Networks, Routers, Floating IPs, Volumes, Security Groups across tenants
- **Quota Management**: View and live-edit compute, network, and storage quotas per tenant
- **Safety Protections**: Last-user guard, in-use flavor check, attached-volume block, default SG protection
- **Three-Tier RBAC**: Viewer (read), Operator (read+write), Admin (read+write+delete)

### 🔍 Ops Assistant — Search & Similarity *(v1.20)*
- **Full-Text Search**: PostgreSQL tsvector + websearch across all 29 resource types, events, and audit logs
- **Trigram Similarity**: "Show Similar" per result — finds related resources, errors, or configurations via pg_trgm
- **Intent Detection**: Natural-language queries like *"quota for projectX"* or *"capacity"* auto-suggest the matching report endpoint
- **Smart Query Templates (v3)**: 26 question templates turn the search bar into an Ops Assistant — ask *"how many VMs are powered off?"*, *"quota for service"*, or *"show platform overview"* and get live answer cards inline
- **Scope Filters**: Domain and Tenant dropdowns filter smart query results to a specific project or domain — 20 of 26 query templates are scope-aware
- **Discoverability UI**: 🤖 button opens a categorised help panel with clickable example chips across 6 categories (Infrastructure, Projects & Quotas, Storage, Networking, Security & Access, Operations) — template chips auto-fill with the scoped tenant, instant chips run immediately. "New Question" button resets the search.
- **Quota & Usage Metering**: Background collector computes per-project resource consumption (VMs, vCPUs, RAM, volumes, storage, snapshots, floating IPs, networks, ports, security groups) from live inventory tables with flavor-based vCPU/RAM resolution
- **29 Indexed Document Types**: VMs, volumes, snapshots, hypervisors, networks, subnets, floating IPs, ports, security groups, domains, projects, users, flavors, images, routers, roles, role assignments, groups, snapshot policies, activity log, auth audit, drift events, snapshot runs/records, restore jobs, backups, notifications, provisioning, deletions
- **Incremental Indexing**: Background worker with per-doc-type watermarks — only re-indexes changed rows
- **Stale Cleanup**: Automatically removes search documents for deleted infrastructure resources
- **Paginated Results**: Relevance-ranked results with highlighted keyword snippets and metadata pill cards
- **Indexer Dashboard**: Real-time stats on document counts, last run time, and per-type health

### 📋 Policy-as-Code Runbooks *(v1.21 → v1.61)*
- **Runbook Catalogue**: Browse 25 built-in operational runbooks with schema-driven parameter forms:
  - **VM**: Stuck VM Remediation, VM Health Quick Fix, Snapshot Before Escalation, Password Reset + Console Access, **VM Rightsizing** *(v1.55)* — identifies over-provisioned VMs and suggests/executes flavor downsizing with pre-snapshot safety, **DR Drill** *(v1.56)* — clone DR-tagged VMs into isolated network, verify boot, auto-teardown, **Hypervisor Maintenance Evacuate** *(v1.57, Phase C2)* — drain a hypervisor before maintenance: live-migrate all VMs (graph-depth ordered), cold-migrate fallback, disable host after drain
  - **Security**: Security Group Audit, Security & Compliance Audit, User Last Login Report, Snapshot Quota Forecast, **Security Group Hardening** *(v1.57, Phase C)* — replaces 0.0.0.0/0 rules with graph-derived CIDRs, **Network Isolation Audit** *(v1.57)* — scans shared networks, cross-tenant routers, CIDR overlaps, and unexpected FIPs, **Image Lifecycle Audit** *(v1.57)* — scores images by age + EOL OS + FIP exposure
  - **Quota**: Quota Threshold Check, Upgrade Opportunity Detector, **Quota Adjustment** *(v1.53)* — sets Nova/Neutron/Cinder quota with billing gate + dry-run diff
  - **General**: Orphan Resource Cleanup, Diagnostics Bundle, Monthly Executive Snapshot, Cost Leakage Report, **Org Usage Report** *(v1.53)* — full usage + cost report with email-ready HTML body, **Capacity Forecast** *(v1.55)* — linear regression on cluster vCPU/RAM history, projects days to 80% capacity, **Cluster Capacity Planner** *(v1.61)* — HA-aware cluster capacity analysis: reserves N+1/N+2 host headroom, 70% safe-operating threshold, forecasts days to capacity, recommends minimum host spec for 6-month runway, per-flavor VM slot table
  - **Provisioning**: **Tenant Offboarding** *(v1.56)* — 10-step customer exit: FIP release → VM stop → port cleanup → Keystone disable → metadata tagging → CRM notification → final report email
- **Department Visibility** *(v1.52)*: Admins control which departments see each runbook via a live checkbox matrix in the UI; non-admin users receive only the runbooks their department is allowed to trigger
- **External Integrations** *(v1.52)*: Connect billing gates, CRM systems, or generic webhooks. `auth_credential` Fernet-encrypted at rest. Action runbooks call `_call_billing_gate()` for pre-authorization before applying changes — silently skips if no integration is configured
- **Result Export**: Every runbook result can be exported as CSV, JSON, or printed to PDF directly from the detail panel
- **ILS Pricing from Metering**: Cost-related runbooks pull real pricing from the `metering_pricing` table — per-flavor, per-resource, with automatic currency detection (ILS/USD)
- **Operator-Facing Trigger**: Tier 1 operators can browse and trigger runbooks with dry-run support — no admin access needed
- **Flexible Approval Workflows**: Configurable `trigger_role → approver_role` mapping per runbook with three modes: auto-approve, single approval, multi-approval
- **Admin Governance**: Execution History, Approvals queue, and Approval Policies managed via 3 dedicated sub-tabs in the Admin panel
- **Full Audit Trail**: Every execution records trigger user, approver, timestamps, parameters, results, items found/actioned
- **Pluggable Engine Architecture**: `@register_engine` decorator pattern — add new runbooks with zero framework changes

### 🕸️ Cloud Dependency Graph *(v1.47 → v1.51)*
- **BFS Graph Engine**: `GET /api/graph` — given any resource (VM, volume, network, tenant, snapshot, SG, FIP, subnet, port, host, image, domain), returns the full node+edge dependency graph up to 3 hops; 150-node cap with `truncated` flag
- **12 Node Types, 15 Edge Types**: All relationships derived from the existing DB schema with no schema changes required
- **Health Score Engine** *(v1.51)*: Every node shows a coloured 0–100 score circle; VM/volume/host each have tailored deduction rules for error states, missing snapshots, drift, and resource pressure; capacity pressure tinting on host nodes
- **Blast Radius Mode** *(v1.51)*: Click 💥 to highlight all resources impacted if the selected node fails; animated edges + node dimming; summary banner showing affected VMs, tenants, FIPs, and volumes
- **Delete Impact Mode** *(v1.51)*: Click 🗑 to preview cascade deletions, stranded resources, and OpenStack blockers before any destructive action
- **Orphan Detection** *(v1.51)*: Surfaces orphaned volumes (unattached), floating IPs (no port), security groups (unused), and dangling snapshots; visible in Tenant Health Panel
- **Tenant Health Panel** *(v1.51)*: Environment health score, critical/degraded VM counts, orphan count, expandable top-issues list shown above the canvas in Topology mode
- **VMware Migration Graph** *(v1.48)*: RVTools-side dependency graph with VM, disk, and portgroup/VLAN nodes; migration status rings (🟢 complete / 🟡 in progress / 🔴 failed); view from any Migration Planner tenant row or cohort expansion
- **ReactFlow UI** (`DependencyGraph.tsx`): Dagre hierarchical layout, 12 color-coded node types, depth pills (1/2/3), type filter checkboxes, **🔍 Explore from here** re-rooting with ← Back breadcrumb; **🔗 Open in tab**, **📸 Create Snapshot**, and **🚀 View in Migration Planner** quick actions on any node
- **Auto-Ticket Integration** *(v1.59)*: Graph node health score < 40 triggers `auto_incident` ticket; `POST /api/graph/request-delete` creates an `auto_change_request` before any destructive delete

### 🤖 Ops Copilot — AI Infrastructure Assistant *(v1.24)*
- **Three-Tier Architecture**: Built-in intent engine (zero setup) → Ollama (local LLM) → OpenAI/Anthropic (external LLM)
- **40+ Built-in Intents**: Inventory counts, VM power states, capacity metrics, error VMs, down hosts, networking (networks, subnets, routers, floating IPs), snapshot/drift/compliance summaries, user lists, role assignments, activity logs, runbook status, and full infrastructure overview — all powered by live SQL queries
- **Tenant / Project / Host Scoping**: Add "on tenant X", "for project X", or "on host Y" to any question for filtered results. Synonym expansion ensures natural phrasing always matches.
- **LLM Integration**: Free-form questions answered via Ollama (local, no data leaves your network) or OpenAI/Anthropic (with automatic sensitive data redaction)
- **Labeled FAB + Welcome Screen**: Prominent pill-shaped "🤖 Ask Copilot" button with pulse animation on first visit, welcome screen with examples, and a dedicated help view with 8 categorized question groups and usage tips
- **Admin Settings Panel**: Switch backends, configure URLs/keys/models, edit system prompts, test connectivity — all from the UI, no `.env` edits needed
- **Feedback & History**: Per-answer thumbs up/down, conversation history persisted per user with automatic trimming
- **Automatic Fallback**: If the LLM backend fails, seamlessly falls back to the built-in intent engine

### � Multi-Region & Multi-Cluster Support *(v1.73.0)*
- **Multiple Control Planes**: Register and manage multiple Platform9 installations (distinct Keystone endpoints) from a single pf9-mngt deployment — each with independent service-account credentials
- **Region Registry**: Full two-level model matching OpenStack's architecture — one Keystone per control plane, with multiple Nova/Neutron/Cinder/Glance regions underneath
- **Zero-Migration Rollout**: Existing single-region deployments are automatically seeded on first startup — current `PF9_AUTH_URL` + `PF9_REGION_NAME` become the `default` control plane and region; no operator action required
- **Per-Region Health Tracking**: `health_status` per region (`healthy` / `degraded` / `unreachable` / `auth_failed`), sync metrics, last sync timestamp, and per-region priority for failover scheduling
- **Cross-Region Task Engine**: State-machine (`cluster_tasks`) for long-running cross-cluster operations — snapshot replication, DR failover, cross-region migration — with `FOR UPDATE SKIP LOCKED` worker safety preventing double-execution
- **Region-Scoped Resources**: All infrastructure resources (VMs, volumes, networks, snapshots, provisioning jobs, etc.) carry a `region_id` FK — full per-region inventory, reporting, and audit trail
- **Endpoint Bug Fix**: Service catalog endpoint selection now correctly filters by `region_id`, preventing silent wrong-region API calls in multi-region control planes
- **Cache Namespacing**: Redis cache keys include `region_id` — prevents cross-region cache collisions when multiple `Pf9Client` instances share one Redis instance
- **Session Reuse**: Each `Pf9Client` owns a single `requests.Session` reused for all API calls — no per-call TCP/TLS overhead; sessions are closed cleanly on shutdown via `ClusterRegistry.shutdown()`
- **Per-Region Request Timeout**: Each region call in `MultiClusterQuery.gather()` enforces a hard `asyncio.wait_for` timeout (`REGION_REQUEST_TIMEOUT_SEC`, default 30 s) — a slow or unreachable region cannot block the semaphore slot and stall all other regions

### �🎫 Support Ticket System *(v1.58 → v1.60)*
- **Full Ticket Lifecycle**: Ticket refs (TKT-YYYY-NNNNN); 5 types (incident, service_request, change_request, auto_incident, auto_change_request); full status/priority/type model; approval gate; SLA deadlines; OpenStack resource linkage
- **35+ API Endpoints** at `/api/tickets`: create, list, get, update, assign, escalate, approve/reject, resolve/reopen/close, comment thread, SLA policies, email templates, analytics, bulk actions
- **SLA Daemon**: Background asyncio task (15-min interval) — breach detection, Slack/Teams notification, auto-escalate on breach, activity comment logged
- **Auto-Ticket Triggers** *(v1.59)*: Critical/warning drift events → `auto_incident`; health score < 40 → `auto_incident`; graph delete intent → `auto_change_request` with `auto_blocked` gate; runbook failure → `auto_incident` linked to execution; migration wave complete → `service_request`
- **Ticket Analytics** *(v1.60)*: Resolution time by dept, SLA breach rate, top openers, daily volume trend; **LandingDashboard KPI tile** (Open / SLA Breached / Resolved Today / Opened Today)
- **Bulk Actions** *(v1.60)*: `close_stale`, `reassign`, `export_csv` via checkbox multi-select toolbar
- **Integration**: Trigger runbooks from a ticket and attach results; `email-customer` action via named HTML templates; inline ticket creation from Metering and Runbooks rows; team-member assignment at creation
- **5 DB Tables**: `support_tickets`, `ticket_comments`, `ticket_sla_policies`, `ticket_email_templates`, `ticket_sequence`; 17 seeded SLA policies, 6 HTML email templates
- **Navigation**: New "Operations & Support" group (🎫) with Tickets and My Queue items

### 📈 30+ Tab Management Dashboard
A single engineering console covering every operational surface:

> Servers · Volumes · Snapshots · Networks · Security Groups · Subnets · Ports · Floating IPs · Domains · Projects · Flavors · Images · Hypervisors · Users · Roles · Snapshot Policies · History · Audit · Monitoring · Restore · Restore Audit · Notifications · Metering · Customer Provisioning · Domain Management · Activity Log · Reports · Resource Management · **Ops Search** · **Runbooks** · **Ops Copilot** · **Tickets** · **Dependency Graph**

<details>
<summary><strong>Landing Dashboard Widgets</strong></summary>

- **Health Summary Card**: System-wide metrics (VMs, volumes, networks, resource utilization)
- **Snapshot SLA Compliance**: Tenant-level compliance tracking with warning/critical alerting
- **Top Host Utilization**: Real-time CPU/memory usage across compute nodes
- **Recent Activity Widget**: Last 24 hours of infrastructure changes
- **Coverage Risk Analysis**: Volumes without snapshot protection
- **Capacity Pressure Indicators**: Storage and compute capacity warnings
- **VM Hotspots**: Top resource consumers (CPU/memory/storage)
- **Tenant Risk Scores**: Multi-factor risk assessments per tenant
- **Compliance Drift Tracking**: Policy adherence trending
- **Capacity Trends**: 7-day resource utilization forecasting
- **Trendlines**: Infrastructure growth patterns and velocity metrics

</details>

<details>
<summary><strong>History Tab Features</strong></summary>

- Filter by resource type (server, volume, snapshot, deletion, etc.), project, domain, and free-text search
- Sortable column headers with ascending/descending indicators
- Deletion record viewing — shows deletion timeline, original resource type, reason, and last-known state
- Most frequently changed resources section with direct history navigation
- Configurable timeframe (1 hour to 1 week)

</details>

- **Dark/Light Mode**: Full theme support with persistent preferences
- **Role-Based UI**: Tabs and actions shown based on user permission level
- **Write-Capable Indicators**: 🔧 icon marks tabs that can create, modify, or delete resources
- **Auto-Refresh**: 30-second refresh on dashboard, efficient pagination across all endpoints

### API Observability
- **Public Metrics**: `GET /metrics`
- **Authenticated Metrics (UI)**: `GET /api/metrics` — Admin/Superadmin only
- **Authenticated Logs (UI)**: `GET /api/logs` — with `limit`, `level`, `source`, `log_file` params
- **Swagger Docs**: `GET /docs` — interactive API documentation

---

## 🚀 Quick Start

### Prerequisites
- **Docker & Docker Compose** (for complete platform)
- **Python 3.11+** with packages: `requests`, `openpyxl`, `psycopg2-binary`, `aiofiles`
- **Valid Platform9 credentials** (service account recommended) — *not required in Demo Mode*
- **Network access** to Platform9 cluster and compute nodes — *not required in Demo Mode*

### 1. Complete Automated Setup (Recommended)
```powershell
# Clone repository
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt

# Configure environment (CRITICAL: No quotes around values)
cp .env.template .env
# Edit .env with your Platform9 credentials

# One-command complete deployment
.\deployment.ps1

# What deployment.ps1 does:
# ✓ Checks/installs Docker Desktop
# ✓ Creates and validates .env configuration
# ✓ Creates required directories (logs, secrets, cache)
# ✓ Installs Python dependencies
# ✓ Builds and starts all Docker containers
# ✓ Initializes PostgreSQL database schema
# ✓ Configures LDAP directory structure
# ✓ Creates automated scheduled tasks
# ✓ Runs comprehensive health checks

# Alternative quick startup (assumes Docker installed)
.\startup.ps1

# Access services after deployment:
# UI:            http://localhost:5173
# API:           http://localhost:8000
# API Docs:      http://localhost:8000/docs
# Monitoring:    http://localhost:8001
# Database:      http://localhost:8080
```

### 1b. Demo Mode (No Platform9 Required)

Want to try the portal without a Platform9 environment? Demo mode populates the
database with realistic sample data (3 tenants, 35 VMs, 50+ volumes, snapshots,
drift events, compliance reports, etc.) and generates a static metrics cache.

```powershell
git clone https://github.com/erezrozenbaum/pf9-mngt.git
cd pf9-mngt

# The deployment wizard will ask "Production or Demo?" — choose 2 for Demo
.\deployment.ps1

# Or enable demo mode manually on an existing install:
#   1. Set DEMO_MODE=true in .env
#   2. python seed_demo_data.py          # populates DB + generates metrics cache
#   3. docker-compose restart pf9_api    # API picks up DEMO_MODE env var
```

> In demo mode the UI shows an amber **DEMO** banner, the background metrics
> collector is skipped, and Platform9 credentials are not required.

### 2. Environment Configuration
```bash
# Platform9 Authentication
PF9_USERNAME=your-service-account@example.com
PF9_PASSWORD=your-secure-password
PF9_AUTH_URL=https://your-cluster.platform9.com/keystone/v3
PF9_USER_DOMAIN=Default
PF9_PROJECT_NAME=service
PF9_PROJECT_DOMAIN=Default
PF9_REGION_NAME=region-one

# Database
POSTGRES_USER=pf9
POSTGRES_PASSWORD=generate-secure-password-here
POSTGRES_DB=pf9_mgmt

# Monitoring
PF9_HOSTS=<HOST_IP_1>,<HOST_IP_2>,<HOST_IP_3>
METRICS_CACHE_TTL=60

# Production image version (docker-compose.prod.yml)
PF9_IMAGE_TAG=latest    # Pin to a release tag (e.g. v1.70.0) to lock images from ghcr.io
```

### 3. Manual Docker Setup
```bash
docker-compose up -d
docker-compose ps
docker-compose logs pf9_api
```

### 4. Standalone Script Usage (No Docker Required)
```bash
# Inventory export
python pf9_rvtools.py

# Snapshot automation
python snapshots/p9_auto_snapshots.py --policy daily_5 --dry-run
python snapshots/p9_auto_snapshots.py --policy daily_5

# Compliance reporting
python snapshots/p9_snapshot_compliance_report.py --input latest_export.xlsx --output compliance.xlsx

# Policy assignment
python snapshots/p9_snapshot_policy_assign.py --config snapshots/snapshot_policy_rules.json --dry-run
```

---

## 🔧 Configuration

### Snapshot Policies
```bash
# Daily snapshots with 5-day retention
openstack volume set --property auto_snapshot=true \
                    --property snapshot_policies=daily_5 \
                    --property retention_daily_5=5 \
                    <volume-id>

# Multiple policies on one volume
openstack volume set --property auto_snapshot=true \
                    --property snapshot_policies=daily_5,monthly_1st \
                    --property retention_daily_5=5 \
                    --property retention_monthly_1st=12 \
                    <volume-id>
```

### Scheduler Worker (v1.62.0+)
```powershell
# Check scheduler status
docker logs pf9_scheduler_worker --tail 30

# Trigger metrics collection manually
docker exec pf9_scheduler_worker python host_metrics_collector.py --once

# Trigger RVTools collection manually
docker exec pf9_scheduler_worker python pf9_rvtools.py
```
> Metrics collection and RVTools inventory now run inside the `pf9_scheduler_worker` container automatically.
> No Windows Task Scheduler setup is required.

---

## 🛠️ Administration

### Database
```bash
# Connect
psql -h localhost -U pf9 -d pf9_mgmt

# Manual backup
docker exec pf9_db pg_dump -U pf9 pf9_mgmt > backup.sql

# Restore
docker exec -i pf9_db psql -U pf9 pf9_mgmt < backup.sql
```

> For scheduled backups, use the 💾 Backup tab in the UI — the backup_worker runs pg_dump on a configurable schedule and writes compressed `.sql.gz` files.

### Service Management
```bash
docker-compose restart pf9_api
docker-compose up -d --scale pf9_api=2
docker stats
```

---

## 📁 Project Structure

```
pf9-mngt/
├── api/                          # FastAPI backend (155+ endpoints)
├── pf9-ui/                       # React 19 + TypeScript frontend
├── monitoring/                   # Prometheus metrics service
├── snapshots/                    # Snapshot automation engine
│   ├── p9_auto_snapshots.py      # Cross-tenant snapshot automation
│   ├── snapshot_service_user.py  # Service user management
│   ├── p9_snapshot_compliance_report.py
│   ├── p9_snapshot_policy_assign.py
│   └── snapshot_policy_rules.json
├── db/                           # PostgreSQL schema + migrations
├── backup_worker/                # Scheduled backup service
├── metering_worker/              # Resource metering service
├── search_worker/                # Full-text search indexer (Ops Assistant)
├── notifications/                # Email notification service
├── ldap/                         # OpenLDAP configuration
├── docs/                         # Full documentation suite
├── pf9_rvtools.py                # RVTools-style inventory export
├── host_metrics_collector.py     # Prometheus metrics collection
├── seed_demo_data.py             # Demo mode: populate DB + metrics cache
├── p9_common.py                  # Shared utilities
├── docker-compose.yml            # Full stack orchestration
├── deployment.ps1                # One-command deployment
├── startup.ps1                   # Quick start script
└── .env.template                 # Environment configuration template
```

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| [Deployment Guide](docs/DEPLOYMENT_GUIDE.md) | Step-by-step deployment instructions |
| [Admin Guide](docs/ADMIN_GUIDE.md) | Day-to-day administration reference |
| [Architecture](docs/ARCHITECTURE.md) | System design, trust boundaries, data model, auth flow |
| [API Reference](docs/API_REFERENCE.md) | Complete API endpoint documentation |
| [Security Guide](docs/SECURITY.md) | Security model, authentication, encryption |
| [Security Checklist](docs/SECURITY_CHECKLIST.md) | Pre-production security audit checklist |
| [Restore Guide](docs/RESTORE_GUIDE.md) | Snapshot restore feature documentation |
| [Snapshot Automation](docs/SNAPSHOT_AUTOMATION.md) | Snapshot system design and configuration |
| [Snapshot Service User](docs/SNAPSHOT_SERVICE_USER.md) | Service user setup and troubleshooting |
| [VM Provisioning Setup](docs/DEPLOYMENT_GUIDE.md) | Includes `provisionsrv` service user setup (Runbook 2) |
| [Quick Reference](docs/QUICK_REFERENCE.md) | Common commands and URLs cheat sheet |
| [Kubernetes Migration](docs/KUBERNETES_MIGRATION_GUIDE.md) | K8s migration planning guide |
| [Linux Deployment](docs/LINUX_DEPLOYMENT_GUIDE.md) | Running pf9-mngt on Linux instead of Windows |
| [Support Ticket System Guide](docs/TICKET_GUIDE.md) | Full reference for the ticket lifecycle, API, SLA, email templates, and auto-tickets |
| [CI/CD Guide](docs/CI_CD_GUIDE.md) | CI pipeline, release process, and Docker image publishing |
| [Contributing](CONTRIBUTING.md) | Contribution guidelines |

---

## �️ Project Status

**Current version:** [v1.73.1](CHANGELOG.md) — March 2026

**Development phase:** Production-hardened and ready for deployment. Full CI pipeline active (lint → unit tests → integration tests against a live Docker stack on every push). Docker images for all 9 services are automatically built and published to `ghcr.io` on every release. CORS restricted in production mode, database performance indexes applied automatically on startup.

**Platform:** Docker Compose with nginx TLS termination. All core containers (14) have restart policies and resource limits; a 15th `pf9_scheduler_worker` container handles automated collection, and `pf9_backup_worker` is added when `COMPOSE_PROFILES=backup` is set. Redis cache, rate limiting, and structured logging active.

**Maturity:** 15 of 17 tracked features are production-grade. AI Copilot is in beta. Kubernetes deployment is a planned future option.

---

## �🆘 Troubleshooting

**"Failed to fetch" in UI**
- Check API: `docker-compose logs pf9_api`
- Verify credentials in `.env`
- Test: `curl http://localhost:8000/health`

**Empty monitoring data**
- Check scheduler: `docker logs pf9_scheduler_worker --tail 20`
- Run once manually: `docker exec pf9_scheduler_worker python host_metrics_collector.py --once`
- Verify node_exporter on PF9 hosts (port 9388)

**Database connection errors**
- Check: `docker-compose logs db`
- Reset: `docker-compose down -v && docker-compose up -d`

**Authentication errors**
- Verify `.env` credentials and Platform9 URL
- Test: `curl -k https://your-cluster.com/keystone/v3`

**Monitoring not working after manual startup**
- Run: `.\fix_monitoring.ps1`

**Data synchronization issues**
- Force sync: `docker exec pf9_scheduler_worker python pf9_rvtools.py`
- Or run directly: `python pf9_rvtools.py`
- Check database via pgAdmin or CLI

---

## 🚨 Important Notes

**Environment file format — CRITICAL:**
```bash
# ✅ CORRECT
PF9_USERNAME=user@example.com

# ❌ WRONG
PF9_USERNAME="user@example.com"
```

**Security checklist for first-time setup:**
1. **NEVER commit `.env`** to version control
2. **Rotate credentials** if accidentally exposed
3. **Use service accounts**, not personal credentials
4. **Test with `--dry-run`** before production use

---

## ❓ FAQ

<details>
<summary><strong>General</strong></summary>

**Q: Does this replace the Platform9 UI?**
A: No. It is a complementary engineering console that adds operational capabilities not present in the native Platform9 UI — automated snapshot scheduling, SLA compliance, restore workflows, chargeback, and more.

**Q: Is this an official Platform9 product?**
A: No. This is an independent project built to work with Platform9 OpenStack APIs. It is not endorsed by or affiliated with Platform9 Systems, Inc.

**Q: Can I run this on Kubernetes?**
A: Yes. Every service is containerized. See [docs/KUBERNETES_MIGRATION_GUIDE.md](docs/KUBERNETES_MIGRATION_GUIDE.md).

**Q: What are the minimum hardware requirements?**
A: A Docker host with at least 4 GB RAM, 2 CPU cores, and network access to your Platform9 region endpoints.

**Q: Can I try this without a Platform9 environment?**
A: Yes! Set `DEMO_MODE=true` in your `.env` (or choose **Demo** during `deployment.ps1`) and run `python seed_demo_data.py`. The database will be populated with realistic sample data and a static metrics cache so every dashboard, report, and workflow is fully functional without a live cluster.

</details>

<details>
<summary><strong>Authentication & RBAC</strong></summary>

**Q: How does authentication work?**
A: Users authenticate against an LDAP directory (bundled OpenLDAP or your corporate LDAP/AD). JWT tokens are issued on login and validated on every API call. Optional TOTP-based MFA is supported.

**Q: What can each role do?**
A: `viewer` — read-only. `operator` — read + limited write. `admin` — full admin except user management. `superadmin` — full access including destructive operations. `technical` — read + write, no delete.

**Q: Can I use Active Directory instead of OpenLDAP?**
A: Yes. Set `LDAP_URL`, `LDAP_BASE_DN`, `LDAP_BIND_DN`, and `LDAP_BIND_PASSWORD` to point at your AD server.

**Q: How do I create the first admin user?**
A: The deployment script seeds a default admin via `admin_user.ldif`. After first login, use the Users tab to promote additional LDAP users. See [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md).

</details>

<details>
<summary><strong>Snapshots & Restore</strong></summary>

**Q: How does automated snapshot scheduling work?**
A: The snapshot scheduler evaluates policy rules, matches volumes by tenant/naming pattern/metadata, and creates snapshots via the Cinder API using a dedicated service user.

**Q: What is the Snapshot Service User?**
A: A dedicated Platform9 user automatically granted admin roles in each tenant project for cross-tenant snapshot creation. See [docs/SNAPSHOT_SERVICE_USER.md](docs/SNAPSHOT_SERVICE_USER.md).

**Q: What is the VM Provisioning Service User (`provisionsrv`)?**
A: A native Keystone service account (NOT in LDAP — invisible to tenant UIs) used by Runbook 2 (VM Provisioning) to create volumes and VMs with a properly project-scoped token. Without it, Nova/Cinder/Neutron resources would be created in the `service` project instead of the target tenant. Configure via `PROVISION_SERVICE_USER_EMAIL` and `PROVISION_USER_PASSWORD_ENCRYPTED`. Run `docker exec pf9_api python3 /app/setup_provision_user.py` once after initial deployment.

**Q: Is restore destructive?**
A: No. Side-by-side restore creates a new VM and a new volume. The original is untouched. Replace mode (superadmin-only) does delete the original and requires typed confirmation.

**Q: What is dry-run mode?**
A: When `RESTORE_DRY_RUN=true` (the default), the restore planner validates the full plan but does not execute it. Set to `false` to enable actual execution.

**Q: Can I cancel a restore in progress?**
A: Yes. Use the Cancel button or call `POST /api/restore/{job_id}/cancel`. The executor stops at the next step boundary and cleans up partial resources.

</details>

<details>
<summary><strong>Monitoring & UI</strong></summary>

**Q: What does the Monitoring tab show?**
A: Real-time host-level metrics (CPU, memory, disk) collected from Platform9 hypervisors via Prometheus node_exporter.

**Q: What do the 🔧 tab icons mean?**
A: Write-capable tabs — they can create, modify, or delete resources. Read-only tabs use default styling.

**Q: Does the UI support dark mode?**
A: Yes. Click the theme toggle (top-right moon/sun icon). Your preference is saved in local storage.

**Q: Where are the logs?**
A: Application logs are in `logs/` and available via the System Logs tab (admin-only). Container logs via `docker logs <container>`.

**Q: How do I access the API documentation?**
A: Swagger docs at `http://<host>:8000/docs`, ReDoc at `http://<host>:8000/redoc`.

</details>

---

## 🎯 Recent Updates

### v1.73.1 — ClusterRegistry + Multi-Region Client Hub
- ✅ **ClusterRegistry module** — new `api/cluster_registry.py`; synchronous, thread-safe two-level registry (control planes → regions) replaces the global `get_client()` singleton; all 100+ existing callers are unchanged
- ✅ **Auto-initializes from DB** — loads `pf9_control_planes` / `pf9_regions` on startup; falls back to env vars if DB empty so existing single-region installs need no changes
- ✅ **MultiClusterQuery** — parallel fan-out across all enabled regions with `asyncio + run_in_executor`; concurrency cap (`MAX_PARALLEL_REGIONS`, default 3); per-region hard timeout (`REGION_REQUEST_TIMEOUT_SEC`, default 30 s) prevents slow regions from blocking the others
- ✅ **Clean shutdown** — `ClusterRegistry.shutdown()` closes every `requests.Session` on app exit; no dangling connections
- ✅ **22 unit tests** — full coverage with no live DB or Platform9 instance required

### v1.73.0 — Multi-Region & Multi-Cluster Support
- ✅ **Control plane registry** — `pf9_control_planes` table: register multiple Platform9 installations (distinct Keystone endpoints) with independent service-account credentials
- ✅ **Region registry** — `pf9_regions` table: two-level model matching OpenStack's architecture; per-region health tracking (`healthy` / `degraded` / `unreachable` / `auth_failed`), sync metrics, and failover priority
- ✅ **Auto-seeded on first start** — existing deployments are automatically migrated; current `PF9_AUTH_URL` + `PF9_REGION_NAME` become the `default` control plane/region with no operator action
- ✅ **Cross-region task engine** — `cluster_tasks` state machine for snapshot replication, DR failover, and cross-region migration; workers use `FOR UPDATE SKIP LOCKED` to prevent double-execution
- ✅ **Region-scoped resources** — `region_id` FK added to all infrastructure tables (VMs, volumes, networks, snapshots, provisioning jobs, etc.)
- ✅ **Service catalog region bug fixed** — `_find_endpoint()` now correctly filters by `region_id`; prevents silent wrong-region API calls in multi-region control planes
- ✅ **Cache key namespacing** — Redis keys include `region_id`; prevents cross-region cache collisions on shared Redis instances

### v1.72.5 — System Metadata Routing Fix
- ✅ `/system-metadata-summary` and `/export` endpoints added to `nginx.prod.conf`, `nginx.conf`, and the Vite dev proxy — fixes System Metadata tab showing empty under Inventory

### v1.72.0 — Migration Planner Restored & Production Startup Fixes
- ✅ **Migration Planner restored** — `migration_routes.py`, `migration_engine.py`, and all frontend components re-added after being removed in v1.69.0; committed and included in CI-built images
- ✅ **`startup_prod.ps1` fixed** — replaced `--build` with `docker compose pull` + `docker compose up -d`; was silently overwriting pulled `ghcr.io` images with local source
- ✅ **nginx `/tenants` routing fixed** — `GET /tenants` alias added to resolve Migration Planner 404

### v1.71.0 — Dependency Security Patches & Quality Fixes
- ✅ **Python dependency CVEs** — `fastapi`, `requests`, `python-ldap`, `python-jose`, `python-multipart` upgraded (13 CVEs resolved)
- ✅ **npm CVE overrides** — `flatted`, `minimatch`, `rollup` forced to patched versions
- ✅ **CSV export quoting** — `QUOTE_ALL` prevents column corruption on fields with commas/newlines

### v1.68.0–v1.70.0 — Security Hardening, Bug Fixes & Performance
- ✅ **XSS fix** — OpsSearch `ts_headline` sanitized via DOMPurify; SMTP TLS certificate enforcement
- ✅ **LDAP fixes** — `create_user()` stores `{SSHA}` hashed passwords; backup uses `-y <tempfile>` (no plaintext in `ps aux`)
- ✅ **Report pagination** — `tenant-quota-usage` and `domain-overview` paged before per-project API calls; upload row cap (2,000) prevents memory exhaustion
- ✅ **Dependency vulnerability scanning in CI** — `pip-audit` + `npm audit` gating integration tests

> For the full history of all 121 releases, see [CHANGELOG.md](CHANGELOG.md).

---

## 🤝 Contributing

Contributions are welcome — code, documentation, bug reports, feature suggestions, or feedback.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:
- How to report bugs
- How to suggest features
- How to submit pull requests
- Development setup and coding standards

---

## 💝 Support the Project

If pf9-mngt saves your team time, consider:

- ⭐ **Star the repository** — helps others discover the project
- 🐛 **Report bugs** — open an issue
- 💻 **Contribute code** — PRs are welcome
- 💬 **Share feedback** — what would you add?

### ☕ Buy Me a Coffee

If this project saves you time or makes your Platform9 operations easier, you can support its continued development:

<a href="https://buymeacoffee.com/erezrozenbaum" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" width="200"></a>

---

## 👤 About the Creator

**Erez Rozenbaum** — Cloud Engineering Manager & Original Developer

Built as part of a serious Platform9 evaluation to solve real operational gaps for MSP and enterprise teams. 422+ commits, 110 releases, 15 containerized services, 170+ API endpoints — built alongside regular responsibilities.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

**Copyright © 2026 Erez Rozenbaum and Contributors**

---

**Project Status**: Production Ready | **Version**: 1.73.1 | **Last Updated**: March 21, 2026
